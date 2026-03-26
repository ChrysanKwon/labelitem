"""ModelCheckController — video playback with YOLO inference overlay."""

import os

from PySide6.QtCore import QTimer, QThread, Signal
from PySide6.QtWidgets import QFileDialog, QMessageBox

from app import io_labels
from app.ui_layout import CLASS_COLORS
from app.video_utils import bgr_to_pixmap
from app.video_playback_base import VideoPlaybackBase
from app.inference_utils import parse_result_detections


class ModelCheckController(VideoPlaybackBase):
    def __init__(self, main_window):
        super().__init__(main_window)
        ui = main_window.ui
        self._play_btn      = ui.btn_mc_play
        self._scrubber      = ui.mc_scrubber
        self._frame_label   = ui.mc_frame_label
        self._frame_input   = ui.mc_frame_input
        self._counter_label = ui.lbl_mc_counter

        self._path               = ""   # last loaded video path
        self._model_path         = ""   # last loaded model path (independent of video)
        self._model              = None
        self._model_names        = {}
        self._raw_detections     = []   # all detections at conf=0.01
        self._current_detections = []   # filtered by conf threshold
        self._filtered_indices   = []   # indices into _current_detections shown in list

        self._infer_timer = QTimer(main_window)
        self._infer_timer.setSingleShot(True)
        self._infer_timer.timeout.connect(self._run_inference)

        self._scan_results: list = []   # [{frame, counts, boxes}]
        self._scan_thread = None
        self._playback_cache: dict = {}  # {frame_idx: [boxes]} loaded from cache file

    @property
    def _save_dir(self) -> str:
        return self._mw.save_dir

    # ── Slots (called from main.py) ───────────────────────────────────────────

    def toggle_play(self):
        super().toggle_play()
        if not self._playing and self._current_frame_bgr is not None:
            self._on_frame_shown(self._current_frame, self._current_frame_bgr)

    def open_video(self):
        result = self._load_video_cap(os.path.dirname(self._path))
        if result is None:
            return
        cap, path, stem, fps, total = result
        self._apply_video(cap, path, fps, total)

    def _apply_video(self, cap, path, fps, total, defer_first_frame=False):
        import cv2
        iw = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        ih = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self._ui.lbl_mc_video_info.setText(
            f"{os.path.basename(path)}\n"
            f"{iw}×{ih}  ·  {total} frames  ·  {fps:.1f} fps"
        )
        self._ui.lbl_mc_video_info.setStyleSheet("color: gray; font-size: 11px;")
        self._scrubber.setRange(0, max(0, total - 1))
        self._scrubber.setValue(0)
        self._clear_scan()
        self._set_controls_enabled(True)
        self._load_playback_cache()
        if defer_first_frame:
            from PySide6.QtCore import QTimer
            QTimer.singleShot(0, lambda: self._show_frame(0))
        else:
            self._show_frame(0)

    def load_video_from_path(self, path: str):
        """Restore video from a saved path (no dialog)."""
        if not path or not os.path.isfile(path):
            return
        import cv2
        cap = cv2.VideoCapture(path)
        if not cap.isOpened():
            return
        fps   = cap.get(cv2.CAP_PROP_FPS) or 30.0
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        if self._cap:
            self._cap.release()
        from pathlib import Path
        self._cap   = cap
        self._path  = path
        self._stem  = Path(path).stem
        self._fps   = fps
        self._total_frames = total
        self._apply_video(cap, path, fps, total, defer_first_frame=True)

    def load_model(self):
        try:
            from ultralytics import YOLO  # noqa: F401
        except ImportError:
            QMessageBox.critical(self._mw, "Ultralytics Not Installed",
                                 "Please run:  pip install ultralytics")
            return

        from app import config as _cfg
        _c = _cfg.load()
        model_dir = os.path.dirname(self._model_path) or os.path.dirname(_c.get("last_model_path", ""))
        path, _ = QFileDialog.getOpenFileName(
            self._mw, "Load YOLO Model",
            model_dir,
            "YOLO model (*.pt)",
        )
        if not path:
            return

        try:
            from ultralytics import YOLO
            self._model       = YOLO(path)
            self._model_names = self._model.names
            self._model_path  = path
            _c["last_model_path"] = path; _cfg.save(_c)
        except Exception as e:
            QMessageBox.critical(self._mw, "Model Load Error", str(e))
            return
        self._apply_model(path)

    def _apply_model(self, path: str):
        self._clear_scan()
        model_name = os.path.basename(path)
        n_classes = len(self._model_names)
        self._ui.lbl_mc_model_info.setText(f"{model_name}\n{n_classes} classes")
        self._ui.lbl_mc_model_info.setStyleSheet("color: #aaa; font-size: 11px;")
        if self._cap:
            self._set_controls_enabled(True)
            if self._current_frame_bgr is not None:
                self._run_inference()

    def load_model_from_path(self, path: str):
        """Restore model from a saved path (no dialog)."""
        if not path or not os.path.isfile(path):
            return
        try:
            from ultralytics import YOLO
            self._model       = YOLO(path)
            self._model_names = self._model.names
            self._model_path  = path
        except Exception as e:
            self._mw.statusBar().showMessage(f"Model load failed: {e}", 5000)
            return
        self._apply_model(path)

    def on_conf_changed(self):
        """Re-filter cached raw detections without re-running inference."""
        if self._raw_detections:
            self._apply_conf_filter()

    def filter_detections(self):
        """Public slot: rebuild detection list based on class filter combobox."""
        self._filter_detections()
        self._draw_overlay()

    def delete_detection(self):
        row = self._ui.mc_detection_list.currentRow()
        if row < 0 or row >= len(self._filtered_indices):
            return
        real_idx = self._filtered_indices[row]
        self._current_detections.pop(real_idx)
        self._filter_detections()
        self._draw_overlay()

    def capture_with_labels(self):
        if not self._cap or self._current_frame_bgr is None:
            return
        if not self._image_dir:
            QMessageBox.warning(self._mw, "No Image Folder",
                                "Please select an image folder first.")
            return

        import cv2
        out_name = f"{self._stem}_f{self._current_frame:06d}.jpg"
        out_path = self._unique_out_path(os.path.join(self._image_dir, out_name))
        cv2.imwrite(out_path, self._current_frame_bgr)

        if self._save_dir and self._current_detections:
            base_name = os.path.splitext(os.path.basename(out_path))[0]
            txt_path  = os.path.join(self._save_dir, base_name + ".txt")
            shapes       = [d['shape']     for d in self._current_detections]
            shape_classes = [d['class_idx'] for d in self._current_detections]
            io_labels.save_yolo(txt_path, shapes, shape_classes)

        fname = os.path.basename(out_path)
        existing = [self._ui.file_list.item(r).text()
                    for r in range(self._ui.file_list.count())]
        if fname not in existing:
            self._ui.file_list.addItem(fname)

        self._mw.statusBar().showMessage(f"Captured: {fname}", 3000)

    # ── VideoPlaybackBase hook ────────────────────────────────────────────────

    def _render_frame(self, idx: int, frame):
        """Draw cached boxes onto frame before pixmap conversion."""
        if self._playing and self._playback_cache:
            boxes = self._playback_cache.get(idx, [])
            if boxes:
                import cv2
                frame = frame.copy()
                names_list = list(self._model.names.values()) if self._model else []
                _colors = [(76,175,80),(33,150,243),(244,67,54),(255,152,0),
                           (156,39,176),(0,188,212),(255,87,34),(96,125,139)]
                for b in boxes:
                    cls_name = b['cls']
                    x1, y1, x2, y2 = [int(v) for v in b['box']]
                    ci = names_list.index(cls_name) if cls_name in names_list else 0
                    color = _colors[ci % len(_colors)]
                    cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
                    cv2.putText(frame, f"{cls_name} {b['conf']:.2f}",
                                (x1, max(y1 - 6, 10)),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)
        return frame

    def _on_frame_shown(self, idx: int, frame):
        """Load detections from cache if available, else run inference."""
        if self._ui.mc_mode_stack.currentIndex() != 0 or self._playing:
            return
        if self._playback_cache and idx in self._playback_cache:
            self._load_detections_from_cache(idx)
        elif self._model:
            self._infer_timer.start(400)

    def _load_detections_from_cache(self, idx: int):
        """Populate _current_detections from playback cache for frame idx."""
        boxes = self._playback_cache.get(idx, [])
        names = self._model.names if self._model else {}
        name_to_idx = {v: k for k, v in names.items()}
        h_px, w_px = (self._current_frame_bgr.shape[:2]
                      if self._current_frame_bgr is not None else (1, 1))
        self._raw_detections = []
        for b in boxes:
            cls_name = b['cls']
            cls_idx  = name_to_idx.get(cls_name, 0)
            x1, y1, x2, y2 = b['box']
            cx = (x1 + x2) / 2; cy = (y1 + y2) / 2
            w  = x2 - x1;       h  = y2 - y1
            self._raw_detections.append({
                'class_idx':  cls_idx,
                'class_name': cls_name,
                'conf':       b['conf'],
                'cx': cx, 'cy': cy, 'w': w, 'h': h,
                'shape':      (cx / w_px, cy / h_px, w / w_px, h / h_px),
            })
        self._apply_conf_filter()

    def _cache_current_frame(self):
        """Persist current frame's detections to playback cache file (per-frame)."""
        path = self._cache_path()
        if not path or self._current_frame_bgr is None:
            return
        import json
        idx = self._current_frame
        h_px, w_px = self._current_frame_bgr.shape[:2]
        boxes = []
        for d in self._current_detections:
            shape = d.get('shape')
            if shape is None:
                # Loaded from cache — pixel cx/cy/w/h already available
                cx, cy, w, h = d['cx'], d['cy'], d['w'], d['h']
                boxes.append({'cls': d['class_name'], 'conf': round(d['conf'], 3),
                              'box': [round(cx - w/2, 1), round(cy - h/2, 1),
                                      round(cx + w/2, 1), round(cy + h/2, 1)]})
            elif not isinstance(shape, list):
                # Normalized bbox tuple (cx, cy, nw, nh) from inference
                cx, cy, nw, nh = shape
                x1 = (cx - nw / 2) * w_px
                y1 = (cy - nh / 2) * h_px
                x2 = (cx + nw / 2) * w_px
                y2 = (cy + nh / 2) * h_px
                boxes.append({'cls': d['class_name'], 'conf': round(d['conf'], 3),
                              'box': [round(x1, 1), round(y1, 1),
                                      round(x2, 1), round(y2, 1)]})
            # segmentation polygons skipped — no compact bbox representation

        self._playback_cache[idx] = boxes
        existing = {}
        if os.path.isfile(path):
            try:
                with open(path, 'r', encoding='utf-8') as f:
                    existing = json.load(f)
            except Exception:
                pass
        existing[str(idx)] = boxes
        with open(path, 'w', encoding='utf-8') as f:
            json.dump(existing, f)

    # ── Private ───────────────────────────────────────────────────────────────

    def _run_inference(self):
        """Run model at conf=0.01 and cache all raw detections."""
        if not self._model or self._current_frame_bgr is None:
            return
        try:
            results = self._model.predict(
                self._current_frame_bgr, conf=0.01, verbose=False)
        except Exception as e:
            self._ui.lbl_mc_model_info.setText(f"Inference error:\n{e}")
            return

        self._raw_detections = parse_result_detections(results[0], self._model_names)
        self._apply_conf_filter()

    def _apply_conf_filter(self):
        """Filter _raw_detections by conf threshold → _current_detections, then redisplay."""
        conf_threshold = self._ui.mc_conf_spin.value()
        self._current_detections = [
            d for d in self._raw_detections if d['conf'] >= conf_threshold
        ]

        prev_filter  = self._ui.mc_class_filter.currentText()
        unique_classes = ["All"] + sorted(  # frame mode class filter keeps "All"
            set(d['class_name'] for d in self._current_detections))
        self._ui.mc_class_filter.blockSignals(True)
        self._ui.mc_class_filter.clear()
        self._ui.mc_class_filter.addItems(unique_classes)
        if prev_filter in unique_classes:
            self._ui.mc_class_filter.setCurrentText(prev_filter)
        self._ui.mc_class_filter.blockSignals(False)

        self._filter_detections()
        self._draw_overlay()
        self._cache_current_frame()

        n = len(self._current_detections)
        self._mw.statusBar().showMessage(
            f"Inference: {n} detection{'s' if n != 1 else ''} (conf ≥ {conf_threshold:.2f})", 3000)

    def _filter_detections(self):
        """Rebuild mc_detection_list based on mc_class_filter selection."""
        filter_name = self._ui.mc_class_filter.currentText()
        self._ui.mc_detection_list.clear()
        self._filtered_indices = []
        for i, d in enumerate(self._current_detections):
            if filter_name == "All" or d['class_name'] == filter_name:
                self._ui.mc_detection_list.addItem(
                    f"{d['class_name']}  {d['conf']:.0%}")
                self._filtered_indices.append(i)

    def _draw_overlay(self):
        """Redraw current frame with detection overlay."""
        if self._current_frame_bgr is None:
            return
        import cv2
        import numpy as np
        frame = self._current_frame_bgr.copy()
        h, w  = frame.shape[:2]

        for det in self._current_detections:
            cls_idx  = det['class_idx']
            qt_color = CLASS_COLORS[cls_idx % len(CLASS_COLORS)]
            bgr      = (qt_color.blue(), qt_color.green(), qt_color.red())
            label    = f"{det['class_name']} {det['conf']:.0%}"
            shape    = det['shape']

            if isinstance(shape, list):
                pts    = [(int(x * w), int(y * h)) for x, y in shape]
                pts_np = np.array(pts, dtype=np.int32)
                cv2.polylines(frame, [pts_np], isClosed=True,
                              color=bgr, thickness=2)
                if pts:
                    tx, ty = pts[0]
                    cv2.putText(frame, label, (tx, ty - 4),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 2)
                    cv2.putText(frame, label, (tx, ty - 4),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, bgr, 1)
            else:
                cx, cy, nw, nh = shape
                x1 = int((cx - nw / 2) * w)
                y1 = int((cy - nh / 2) * h)
                x2 = int((cx + nw / 2) * w)
                y2 = int((cy + nh / 2) * h)
                cv2.rectangle(frame, (x1, y1), (x2, y2), bgr, 2)
                cv2.putText(frame, label, (x1, max(y1 - 4, 12)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 2)
                cv2.putText(frame, label, (x1, max(y1 - 4, 12)),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, bgr, 1)

        self._frame_label.setPixmap(bgr_to_pixmap(frame))

    # ── Scan all frames ───────────────────────────────────────────────────────

    def scan_all_frames(self):
        """Start background scan of all frames."""
        if not self._cap or not self._model or not self._path:
            return
        if self._scan_thread and self._scan_thread.isRunning():
            return

        conf = self._ui.mc_conf_spin.value()
        self._scan_thread = ScanWorker(self._path, self._model, conf)
        self._scan_thread.progress.connect(self._on_scan_progress)
        self._scan_thread.finished.connect(self._on_scan_done)

        self._ui.mc_scan_progress.setVisible(True)
        self._ui.mc_scan_progress.setValue(0)
        self._ui.btn_mc_scan.setEnabled(False)
        self._scan_thread.start()

    def _on_scan_progress(self, cur: int, total: int):
        self._ui.mc_scan_progress.setMaximum(total)
        self._ui.mc_scan_progress.setValue(cur)
        self._mw.statusBar().showMessage(f"Scanning {cur}/{total} frames…")

    def _on_scan_done(self, results: list):
        self._scan_results = results
        self._ui.mc_scan_progress.setVisible(False)
        self._ui.btn_mc_scan.setEnabled(True)
        has_results = bool(results)
        self._ui.btn_mc_chart.setEnabled(has_results)
        self._ui.btn_mc_export.setEnabled(has_results)

        # Populate class combo from all seen class names
        all_classes = sorted({name for r in results for name in r['counts']})
        self._ui.mc_scan_class_combo.blockSignals(True)
        self._ui.mc_scan_class_combo.clear()
        self._ui.mc_scan_class_combo.addItem("Total")
        self._ui.mc_scan_class_combo.addItems(all_classes)
        self._ui.mc_scan_class_combo.blockSignals(False)

        self._apply_scan_filter()
        self._save_playback_cache(results)
        n = len(results)
        self._mw.statusBar().showMessage(f"Scan complete: {n} frames processed.", 5000)

    def _apply_scan_filter(self, *_):
        """Filter scan results by class + count (exact match) and populate scan list."""
        cls_name  = self._ui.mc_scan_class_combo.currentText()
        count_val = self._ui.mc_scan_count_input.value()

        def matches(counts: dict) -> bool:
            if cls_name == "Total":
                total = sum(counts.values())
            else:
                total = counts.get(cls_name, 0)
            return total == count_val

        self._ui.mc_scan_list.clear()
        for r in self._scan_results:
            if matches(r['counts']):
                summary = "  ".join(f"{n}:{c}" for n, c in sorted(r['counts'].items()))
                self._ui.mc_scan_list.addItem(
                    f"Frame {r['frame'] + 1:>6}  |  {summary or '(no detections)'}")

        found = self._ui.mc_scan_list.count()
        total = len(self._scan_results)
        self._mw.statusBar().showMessage(f"Scan filter: {found}/{total} frames match.", 3000)

    def jump_to_scan_frame(self, row: int):
        """Called when user clicks a scan result row — jump to that frame."""
        if row < 0:
            return
        item = self._ui.mc_scan_list.item(row)
        if item is None:
            return
        text = item.text()
        # parse "Frame   42  | ..." → frame index 41 (0-based)
        try:
            frame_1based = int(text.split("|")[0].replace("Frame", "").strip())
            self._show_frame(frame_1based - 1)
            if self._model:
                self._run_inference()   # draw overlay on this scan frame
        except ValueError:
            pass

    def _clear_scan(self):
        """Reset scan state when video/model changes."""
        self._scan_results = []
        self._playback_cache = {}
        self._ui.mc_scan_progress.setVisible(False)
        self._ui.mc_scan_list.clear()
        self._ui.btn_mc_chart.setEnabled(False)
        self._ui.btn_mc_export.setEnabled(False)

    # ── Playback cache ────────────────────────────────────────────────────────

    def _cache_path(self) -> str:
        from app import config as _cfg
        if not _cfg.load().get("playback_cache", False):
            return ""
        if not self._path or not self._model_path:
            return ""
        _app_dir  = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        cache_dir = os.path.join(_app_dir, ".mc_cache")
        os.makedirs(cache_dir, exist_ok=True)
        video_stem = os.path.splitext(os.path.basename(self._path))[0]
        model_stem = os.path.splitext(os.path.basename(self._model_path))[0]
        conf_tag   = f"{self._ui.mc_conf_spin.value():.2f}".replace(".", "p")
        return os.path.join(cache_dir, f"{video_stem}_{model_stem}_{conf_tag}.json")

    def _save_playback_cache(self, results: list):
        path = self._cache_path()
        if not path:
            return
        import json
        data = {str(r["frame"]): r["boxes"] for r in results}
        with open(path, "w", encoding="utf-8") as f:
            json.dump(data, f)
        self._playback_cache = {int(k): v for k, v in data.items()}
        self._mw.statusBar().showMessage(
            f"Playback cache saved: {os.path.basename(path)}", 3000)

    def _load_playback_cache(self):
        path = self._cache_path()
        if not path or not os.path.isfile(path):
            self._playback_cache = {}
            return
        import json
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            self._playback_cache = {int(k): v for k, v in data.items()}
        except Exception:
            self._playback_cache = {}

    def show_chart(self):
        """Open a dialog with a detection-count-per-frame line chart."""
        if not self._scan_results:
            return
        try:
            import matplotlib
            matplotlib.use("QtAgg")
            import matplotlib.pyplot as plt
            from matplotlib.backends.backend_qtagg import FigureCanvasQTAgg
        except ImportError:
            QMessageBox.critical(self._mw, "Missing Dependency",
                                 "Please run:  pip install matplotlib")
            return

        from PySide6.QtWidgets import QDialog, QVBoxLayout

        frames = [r["frame"] + 1 for r in self._scan_results]
        all_classes = sorted({n for r in self._scan_results for n in r["counts"]})

        fig, ax = plt.subplots(figsize=(10, 4))
        fig.patch.set_facecolor("#1e1e1e")
        ax.set_facecolor("#2d2d2d")
        totals = [sum(r["counts"].values()) for r in self._scan_results]
        ax.plot(frames, totals, label="Total", color="white", linewidth=1.5)
        _colors = ["#4caf50", "#ff9800", "#2196f3", "#e91e63", "#00bcd4", "#ff5722"]
        for i, cls in enumerate(all_classes):
            counts = [r["counts"].get(cls, 0) for r in self._scan_results]
            ax.plot(frames, counts, label=cls, color=_colors[i % len(_colors)], linewidth=1)
        for spine in ax.spines.values():
            spine.set_color("#555")
        ax.tick_params(colors="#ccc")
        ax.set_xlabel("Frame", color="#ccc")
        ax.set_ylabel("Detections", color="#ccc")
        ax.set_title("Detections per Frame", color="#ccc")
        ax.legend(facecolor="#2d2d2d", labelcolor="#ccc")
        fig.tight_layout()

        dlg = QDialog(self._mw)
        dlg.setWindowTitle("Scan Chart")
        dlg.resize(900, 420)
        layout = QVBoxLayout(dlg)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(FigureCanvasQTAgg(fig))
        dlg.exec()
        plt.close(fig)

    def export_excel(self):
        """Export scan results to Excel with an embedded chart image."""
        if not self._scan_results:
            return
        try:
            import openpyxl
            from openpyxl.drawing.image import Image as XLImage
            import matplotlib
            matplotlib.use("Agg")
            import matplotlib.pyplot as plt
            import io
        except ImportError:
            QMessageBox.critical(self._mw, "Missing Dependency",
                                 "Please run:  pip install openpyxl matplotlib")
            return

        path, _ = QFileDialog.getSaveFileName(
            self._mw, "Export Excel",
            os.path.join(self._image_dir or "", "scan_results.xlsx"),
            "Excel (*.xlsx)",
        )
        if not path:
            return

        all_classes = sorted({n for r in self._scan_results for n in r["counts"]})
        frames      = [r["frame"] + 1 for r in self._scan_results]
        totals      = [sum(r["counts"].values()) for r in self._scan_results]

        # ── Chart image ──────────────────────────────────────────────────────
        fig, ax = plt.subplots(figsize=(12, 4))
        ax.plot(frames, totals, label="Total", color="#333", linewidth=1.5)
        _colors = ["#4caf50", "#ff9800", "#2196f3", "#e91e63", "#00bcd4", "#ff5722"]
        for i, cls in enumerate(all_classes):
            counts = [r["counts"].get(cls, 0) for r in self._scan_results]
            ax.plot(frames, counts, label=cls, color=_colors[i % len(_colors)], linewidth=1)
        ax.set_xlabel("Frame")
        ax.set_ylabel("Detections")
        ax.set_title("Detections per Frame")
        ax.legend()
        fig.tight_layout()
        buf = io.BytesIO()
        fig.savefig(buf, format="png", dpi=150, bbox_inches="tight")
        plt.close(fig)
        buf.seek(0)

        # ── Workbook ─────────────────────────────────────────────────────────
        wb = openpyxl.Workbook()
        ws = wb.active
        ws.title = "Scan Results"
        ws.append(["Frame"] + all_classes + ["Total"])
        for r in self._scan_results:
            ws.append(
                [r["frame"] + 1]
                + [r["counts"].get(cls, 0) for cls in all_classes]
                + [sum(r["counts"].values())]
            )

        ws_chart = wb.create_sheet("Chart")
        ws_chart.add_image(XLImage(buf), "A1")

        wb.save(path)
        self._mw.statusBar().showMessage(f"Exported: {os.path.basename(path)}", 3000)

    def _set_controls_enabled(self, enabled: bool):
        for widget in (self._play_btn,
                       self._ui.btn_mc_prev,
                       self._ui.btn_mc_next,
                       self._scrubber,
                       self._frame_input):
            widget.setEnabled(enabled)
        has_both = enabled and bool(self._model)
        self._ui.btn_mc_capture.setEnabled(has_both)
        self._ui.btn_mc_scan.setEnabled(has_both)
        self._ui.btn_mc_export_video.setEnabled(has_both)

    # ── Export annotated video ────────────────────────────────────────────────

    def export_video(self):
        if not self._cap or not self._model:
            return
        conf = self._ui.mc_conf_spin.value()
        default_name = (self._stem or "output") + "_annotated.mp4"
        out_dir = os.path.dirname(self._path) if self._path else ""
        path, _ = QFileDialog.getSaveFileName(
            self._mw, "Export Annotated Video",
            os.path.join(out_dir, default_name),
            "Video (*.mp4)",
        )
        if not path:
            return
        self._ui.btn_mc_export_video.setEnabled(False)
        self._ui.mc_export_progress.setVisible(True)
        self._ui.mc_export_progress.setValue(0)
        self._export_worker = ExportVideoWorker(self._path, self._model, conf, path)
        self._export_worker.progress.connect(self._on_export_progress)
        self._export_worker.finished.connect(self._on_export_done)
        self._export_worker.start()

    def _on_export_progress(self, current: int, total: int):
        self._ui.mc_export_progress.setMaximum(total)
        self._ui.mc_export_progress.setValue(current)

    def _on_export_done(self, out_path: str):
        self._ui.mc_export_progress.setVisible(False)
        self._ui.btn_mc_export_video.setEnabled(True)
        self._mw.statusBar().showMessage(f"Exported: {out_path}", 5000)


# ── Background scan worker ────────────────────────────────────────────────────

class ScanWorker(QThread):
    progress = Signal(int, int)
    finished = Signal(object)

    def __init__(self, video_path: str, model, conf: float):
        super().__init__()
        self._video_path = video_path
        self._model      = model
        self._conf       = conf

    def run(self):
        import cv2
        cap   = cv2.VideoCapture(self._video_path)
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        results = []
        for i in range(total):
            ret, frame = cap.read()
            if not ret:
                break
            r = self._model(frame, conf=0.01, verbose=False)[0]
            counts: dict = {}
            boxes: list  = []
            for box in r.boxes:
                if not len(box.cls) or not len(box.conf):
                    continue
                if float(box.conf[0]) < self._conf:
                    continue
                name = self._model.names[int(box.cls[0])]
                counts[name] = counts.get(name, 0) + 1
                x1, y1, x2, y2 = [round(float(v), 1) for v in box.xyxy[0]]
                boxes.append({'cls': name, 'conf': round(float(box.conf[0]), 3),
                               'box': [x1, y1, x2, y2]})
            results.append({'frame': i, 'counts': counts, 'boxes': boxes})
            self.progress.emit(i + 1, total)
        cap.release()
        self.finished.emit(results)


# ── Background export video worker ───────────────────────────────────────────

class ExportVideoWorker(QThread):
    progress = Signal(int, int)
    finished = Signal(str)

    def __init__(self, video_path: str, model, conf: float, output_path: str):
        super().__init__()
        self._video_path  = video_path
        self._model       = model
        self._conf        = conf
        self._output_path = output_path

    def run(self):
        import cv2
        cap   = cv2.VideoCapture(self._video_path)
        fps   = cap.get(cv2.CAP_PROP_FPS) or 30.0
        w     = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        h     = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        out   = cv2.VideoWriter(
            self._output_path,
            cv2.VideoWriter_fourcc(*"mp4v"),
            fps, (w, h),
        )
        names = self._model.names
        colors = [(76,175,80),(33,150,243),(244,67,54),(255,152,0),
                  (156,39,176),(0,188,212),(255,87,34),(96,125,139)]
        for i in range(total):
            ret, frame = cap.read()
            if not ret:
                break
            results = self._model(frame, conf=self._conf, verbose=False)[0]
            if results.boxes is not None:
                for box in results.boxes:
                    if not len(box.cls) or not len(box.conf):
                        continue
                    cls_id = int(box.cls[0])
                    conf   = float(box.conf[0])
                    x1, y1, x2, y2 = map(int, box.xyxy[0])
                    color  = colors[cls_id % len(colors)]
                    cv2.rectangle(frame, (x1, y1), (x2, y2), color, 2)
                    label  = f"{names[cls_id]} {conf:.2f}"
                    cv2.putText(frame, label, (x1, max(y1 - 6, 10)),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 2)
            out.write(frame)
            self.progress.emit(i + 1, total)
        cap.release()
        out.release()
        self.finished.emit(self._output_path)
