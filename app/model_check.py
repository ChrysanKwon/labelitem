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

        self._scan_results: list = []   # [{frame: int, counts: {class_name: int}}]
        self._scan_thread = None

    @property
    def _save_dir(self) -> str:
        return self._mw.save_dir

    # ── Slots (called from main.py) ───────────────────────────────────────────

    def open_video(self):
        result = self._load_video_cap(os.path.dirname(self._path) or os.path.expanduser("~"))
        if result is None:
            return

        cap, path, stem, fps, total = result

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
        self._show_frame(0)

    def load_model(self):
        try:
            from ultralytics import YOLO  # noqa: F401
        except ImportError:
            QMessageBox.critical(self._mw, "Ultralytics Not Installed",
                                 "Please run:  pip install ultralytics")
            return

        model_dir = os.path.dirname(self._model_path) or ""
        path, _ = QFileDialog.getOpenFileName(
            self._mw, "Load YOLO Model",
            model_dir,
            "YOLO model (*.pt)",
            options=QFileDialog.Option.DontUseNativeDialog,
        )
        if not path:
            return

        try:
            from ultralytics import YOLO
            self._model       = YOLO(path)
            self._model_names = self._model.names
            self._model_path  = path
        except Exception as e:
            QMessageBox.critical(self._mw, "Model Load Error", str(e))
            return
        self._clear_scan()

        model_name = os.path.basename(path)
        n_classes = len(self._model_names)
        self._ui.lbl_mc_model_info.setText(f"{model_name}\n{n_classes} classes")
        self._ui.lbl_mc_model_info.setStyleSheet("color: #aaa; font-size: 11px;")

        if self._cap:
            self._ui.btn_mc_capture.setEnabled(True)
            self._ui.btn_mc_scan.setEnabled(True)
            if self._current_frame_bgr is not None:
                self._run_inference()

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

    def _on_frame_shown(self, idx: int, frame):
        """Trigger debounced inference 400 ms after scrubbing stops."""
        if self._model and self._ui.mc_mode_stack.currentIndex() == 0:
            self._infer_timer.start(400)

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
        unique_classes = ["All"] + sorted(
            set(d['class_name'] for d in self._current_detections))
        self._ui.mc_class_filter.blockSignals(True)
        self._ui.mc_class_filter.clear()
        self._ui.mc_class_filter.addItems(unique_classes)
        if prev_filter in unique_classes:
            self._ui.mc_class_filter.setCurrentText(prev_filter)
        self._ui.mc_class_filter.blockSignals(False)

        self._filter_detections()
        self._draw_overlay()

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

        self._frame_label.setPixmap(bgr_to_pixmap(frame, self._frame_label.size()))

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

        # Populate class combo from all seen class names
        all_classes = sorted({name for r in results for name in r['counts']})
        self._ui.mc_scan_class_combo.blockSignals(True)
        self._ui.mc_scan_class_combo.clear()
        self._ui.mc_scan_class_combo.addItem("All")
        self._ui.mc_scan_class_combo.addItems(all_classes)
        self._ui.mc_scan_class_combo.blockSignals(False)

        self._apply_scan_filter()
        n = len(results)
        self._mw.statusBar().showMessage(f"Scan complete: {n} frames processed.", 5000)

    def _apply_scan_filter(self, *_):
        """Filter scan results by class + count (exact match) and populate scan list."""
        cls_name = self._ui.mc_scan_class_combo.currentText()
        try:
            count_val = int(self._ui.mc_scan_count_input.text())
        except ValueError:
            return

        def matches(counts: dict) -> bool:
            if cls_name == "All":
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
        self._ui.mc_scan_progress.setVisible(False)
        self._ui.mc_scan_list.clear()

    def _set_controls_enabled(self, enabled: bool):
        for widget in (self._play_btn,
                       self._ui.btn_mc_prev,
                       self._ui.btn_mc_next,
                       self._scrubber,
                       self._frame_input):
            widget.setEnabled(enabled)
        if enabled and self._model:
            self._ui.btn_mc_capture.setEnabled(True)
            self._ui.btn_mc_scan.setEnabled(True)
        elif not enabled:
            self._ui.btn_mc_scan.setEnabled(False)


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
            for box in r.boxes:
                if float(box.conf[0]) < self._conf:
                    continue
                name = self._model.names[int(box.cls[0])]
                counts[name] = counts.get(name, 0) + 1
            results.append({'frame': i, 'counts': counts})
            self.progress.emit(i + 1, total)
        cap.release()
        self.finished.emit(results)
