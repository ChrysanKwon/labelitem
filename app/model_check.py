"""ModelCheckController — video playback with YOLO inference overlay."""

import os

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QFileDialog, QMessageBox

from app import io_labels
from app.ui_layout import CLASS_COLORS


class ModelCheckController:
    def __init__(self, main_window):
        self._mw = main_window
        self._cap   = None          # cv2.VideoCapture
        self._model = None          # YOLO instance
        self._model_names = {}      # {int: str}
        self._fps           = 25.0
        self._total_frames  = 0
        self._current_frame = 0
        self._playing       = False
        self._current_frame_bgr  = None   # numpy BGR array of current frame
        self._current_detections = []     # list of dicts

        self._play_timer = QTimer(main_window)
        self._play_timer.timeout.connect(self._advance_frame)

        # Debounce timer: 400 ms after scrub settles → run inference
        self._infer_timer = QTimer(main_window)
        self._infer_timer.setSingleShot(True)
        self._infer_timer.timeout.connect(self._run_inference)

    # ── Convenience ──────────────────────────────────────────────────────────

    @property
    def _ui(self):
        return self._mw.ui

    @property
    def _image_dir(self) -> str:
        return self._mw.image_dir

    @property
    def _save_dir(self) -> str:
        return self._mw.save_dir

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def pause(self):
        """Pause playback (called when leaving Model Check tab)."""
        if self._playing:
            self._playing = False
            self._play_timer.stop()
            self._ui.btn_mc_play.setText("▶  Play")

    # ── Slots (called from main.py) ───────────────────────────────────────────

    def open_video(self):
        try:
            import cv2
        except ImportError:
            QMessageBox.critical(self._mw, "OpenCV Not Installed",
                                 "Please run:  pip install opencv-python")
            return

        path, _ = QFileDialog.getOpenFileName(
            self._mw, "Open Video",
            self._image_dir if self._image_dir else "",
            "Video files (*.mp4 *.avi *.mov *.mkv *.wmv *.flv *.webm)",
        )
        if not path:
            return

        if self._cap:
            self._cap.release()

        import cv2
        cap = cv2.VideoCapture(path)
        if not cap.isOpened():
            QMessageBox.critical(self._mw, "Cannot Open Video",
                                 f"Failed to open:\n{path}")
            return

        self._cap           = cap
        self._path          = path
        self._stem          = os.path.splitext(os.path.basename(path))[0]
        self._fps           = cap.get(cv2.CAP_PROP_FPS) or 25.0
        self._total_frames  = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        self._current_frame = 0
        self._playing       = False
        self._play_timer.stop()
        self._ui.btn_mc_play.setText("▶  Play")

        iw = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        ih = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fname = os.path.basename(path)
        self._ui.lbl_mc_video_info.setText(
            f"{fname}\n{iw}×{ih}  ·  {self._total_frames} frames  ·  {self._fps:.1f} fps"
        )
        self._ui.lbl_mc_video_info.setStyleSheet("color: gray; font-size: 11px;")

        self._ui.mc_scrubber.setRange(0, max(0, self._total_frames - 1))
        self._ui.mc_scrubber.setValue(0)
        self._set_controls_enabled(True)
        self._show_frame(0)

    def load_model(self):
        try:
            from ultralytics import YOLO  # noqa: F401
        except ImportError:
            QMessageBox.critical(self._mw, "Ultralytics Not Installed",
                                 "Please run:  pip install ultralytics")
            return

        path, _ = QFileDialog.getOpenFileName(
            self._mw, "Load YOLO Model",
            self._image_dir if self._image_dir else "",
            "YOLO model (*.pt)",
        )
        if not path:
            return

        try:
            from ultralytics import YOLO
            self._model = YOLO(path)
            self._model_names = self._model.names
        except Exception as e:
            QMessageBox.critical(self._mw, "Model Load Error", str(e))
            return

        model_name = os.path.basename(path)
        n_classes = len(self._model_names)
        self._ui.lbl_mc_model_info.setText(f"{model_name}\n{n_classes} classes")
        self._ui.lbl_mc_model_info.setStyleSheet("color: #aaa; font-size: 11px;")

        # Enable capture now that model is loaded (video must also be loaded)
        if self._cap:
            self._ui.btn_mc_capture.setEnabled(True)
            # Auto-infer on current frame
            if self._current_frame_bgr is not None:
                self._run_inference()

    def toggle_play(self):
        if not self._cap:
            return
        if self._playing:
            self._playing = False
            self._play_timer.stop()
            self._ui.btn_mc_play.setText("▶  Play")
        else:
            self._playing = True
            self._play_timer.start(max(1, round(1000 / self._fps)))
            self._ui.btn_mc_play.setText("⏸  Pause")

    def step_frame(self, delta: int):
        if not self._cap:
            return
        self._show_frame(self._current_frame + delta)

    def on_scrubber_moved(self, value: int):
        if not self._cap:
            return
        self._show_frame(value)

    def delete_detection(self):
        row = self._ui.mc_detection_list.currentRow()
        if row < 0 or row >= len(self._current_detections):
            return
        self._current_detections.pop(row)
        self._ui.mc_detection_list.takeItem(row)
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
        out_path = os.path.join(self._image_dir, out_name)

        if os.path.exists(out_path):
            i = 2
            base, ext = os.path.splitext(out_path)
            while os.path.exists(f"{base}_{i}{ext}"):
                i += 1
            out_path = f"{base}_{i}{ext}"

        cv2.imwrite(out_path, self._current_frame_bgr)

        # Save labels if save_dir is set and there are detections
        if self._save_dir and self._current_detections:
            base_name = os.path.splitext(os.path.basename(out_path))[0]
            txt_path = os.path.join(self._save_dir, base_name + ".txt")
            shapes = [d['shape'] for d in self._current_detections]
            shape_classes = [d['class_idx'] for d in self._current_detections]
            io_labels.save_yolo(txt_path, shapes, shape_classes)

        # Add to file list
        fname = os.path.basename(out_path)
        existing = [self._ui.file_list.item(r).text()
                    for r in range(self._ui.file_list.count())]
        if fname not in existing:
            self._ui.file_list.addItem(fname)

        # Brief green feedback
        orig = self._ui.lbl_mc_video_info.styleSheet()
        self._ui.lbl_mc_video_info.setStyleSheet("color: #4caf50; font-size: 11px;")
        QTimer.singleShot(600, lambda: self._ui.lbl_mc_video_info.setStyleSheet(orig))

    # ── Private ───────────────────────────────────────────────────────────────

    def _advance_frame(self):
        if not self._cap or not self._playing:
            return
        next_frame = self._current_frame + 1
        if next_frame >= self._total_frames:
            self.toggle_play()
            return
        self._show_frame(next_frame)

    def _show_frame(self, idx: int):
        import cv2
        idx = max(0, min(idx, self._total_frames - 1))
        self._cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ret, frame = self._cap.read()
        if not ret:
            return
        self._current_frame     = idx
        self._current_frame_bgr = frame

        # Display raw frame immediately (no inference lag)
        self._display_bgr(frame)

        self._ui.mc_scrubber.blockSignals(True)
        self._ui.mc_scrubber.setValue(idx)
        self._ui.mc_scrubber.blockSignals(False)
        self._ui.lbl_mc_counter.setText(f"{idx + 1} / {self._total_frames}")

        # Restart debounce — inference fires 400 ms after scrubbing stops
        if self._model:
            self._infer_timer.start(400)

    def _display_bgr(self, frame_bgr):
        """Convert a BGR numpy frame to QPixmap and show in mc_frame_label."""
        import cv2
        rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        qi = QImage(rgb.data, w, h, ch * w, QImage.Format.Format_RGB888)
        pix = QPixmap.fromImage(qi).scaled(
            self._ui.mc_frame_label.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._ui.mc_frame_label.setPixmap(pix)

    def _run_inference(self):
        if not self._model or self._current_frame_bgr is None:
            return
        conf = self._ui.mc_conf_spin.value()
        try:
            results = self._model.predict(
                self._current_frame_bgr, conf=conf, verbose=False)
        except Exception as e:
            self._ui.lbl_mc_model_info.setText(
                f"Inference error:\n{e}")
            return

        result = results[0]
        self._current_detections = []

        if result.masks is not None:
            # Segmentation model
            for i, mask in enumerate(result.masks):
                cls_idx  = int(result.boxes.cls[i].item())
                conf_val = float(result.boxes.conf[i].item())
                pts = [(float(x), float(y)) for x, y in mask.xyn[0]]
                self._current_detections.append({
                    'class_idx':  cls_idx,
                    'class_name': self._model_names.get(cls_idx, str(cls_idx)),
                    'conf':       conf_val,
                    'shape':      pts,
                })
        elif result.boxes is not None:
            # Detection model
            for box in result.boxes:
                cls_idx  = int(box.cls[0].item())
                conf_val = float(box.conf[0].item())
                cx, cy, nw, nh = box.xywhn[0].tolist()
                self._current_detections.append({
                    'class_idx':  cls_idx,
                    'class_name': self._model_names.get(cls_idx, str(cls_idx)),
                    'conf':       conf_val,
                    'shape':      (cx, cy, nw, nh),
                })

        self._ui.mc_detection_list.clear()
        for d in self._current_detections:
            self._ui.mc_detection_list.addItem(
                f"{d['class_name']}  {d['conf']:.0%}")

        self._draw_overlay()

    def _draw_overlay(self):
        """Redraw current frame with detection overlay from _current_detections."""
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
                # Polygon
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
                # Bounding box
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

        self._display_bgr(frame)

    def _set_controls_enabled(self, enabled: bool):
        for widget in (self._ui.btn_mc_play,
                       self._ui.btn_mc_prev,
                       self._ui.btn_mc_next,
                       self._ui.mc_scrubber):
            widget.setEnabled(enabled)
        # Capture only when both video and model are loaded
        if enabled and self._model:
            self._ui.btn_mc_capture.setEnabled(True)
