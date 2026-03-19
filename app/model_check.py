"""ModelCheckController — video playback with YOLO inference overlay."""

import os

from PySide6.QtCore import QTimer
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

        self._model              = None
        self._model_names        = {}
        self._raw_detections     = []   # all detections at conf=0.01
        self._current_detections = []   # filtered by conf threshold
        self._filtered_indices   = []   # indices into _current_detections shown in list

        self._infer_timer = QTimer(main_window)
        self._infer_timer.setSingleShot(True)
        self._infer_timer.timeout.connect(self._run_inference)

    @property
    def _save_dir(self) -> str:
        return self._mw.save_dir

    # ── Slots (called from main.py) ───────────────────────────────────────────

    def open_video(self):
        result = self._load_video_cap(os.path.dirname(getattr(self, '_path', '')) or "")
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
        self._set_controls_enabled(True)
        self._show_frame(0)

    def load_model(self):
        try:
            from ultralytics import YOLO  # noqa: F401
        except ImportError:
            QMessageBox.critical(self._mw, "Ultralytics Not Installed",
                                 "Please run:  pip install ultralytics")
            return

        model_dir = os.path.dirname(getattr(self, '_model_path', '')) or ""
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
        except Exception as e:
            QMessageBox.critical(self._mw, "Model Load Error", str(e))
            return

        model_name = os.path.basename(path)
        n_classes = len(self._model_names)
        self._ui.lbl_mc_model_info.setText(f"{model_name}\n{n_classes} classes")
        self._ui.lbl_mc_model_info.setStyleSheet("color: #aaa; font-size: 11px;")

        if self._cap:
            self._ui.btn_mc_capture.setEnabled(True)
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
        if self._model:
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

    def _set_controls_enabled(self, enabled: bool):
        for widget in (self._play_btn,
                       self._ui.btn_mc_prev,
                       self._ui.btn_mc_next,
                       self._scrubber,
                       self._frame_input):
            widget.setEnabled(enabled)
        if enabled and self._model:
            self._ui.btn_mc_capture.setEnabled(True)
