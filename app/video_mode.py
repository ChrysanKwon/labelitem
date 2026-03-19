"""VideoModeController — manages video playback and frame capture."""

import os

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QFileDialog, QMessageBox

from app.frame_extract_dialog import FrameExtractDialog


class VideoModeController:
    def __init__(self, main_window):
        self._mw  = main_window
        self._cap = None          # cv2.VideoCapture
        self._fps = 25.0
        self._total_frames = 0
        self._current_frame = 0
        self._playing = False

        self._timer = QTimer(main_window)
        self._timer.timeout.connect(self._advance_frame)

    # ── Convenience ──────────────────────────────────────────────────────────

    @property
    def _ui(self):
        return self._mw.ui

    @property
    def _image_dir(self) -> str:
        return self._mw.image_dir

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def pause(self):
        """Pause playback (called when leaving Video tab)."""
        if self._playing:
            self._playing = False
            self._timer.stop()
            self._ui.btn_video_play.setText("▶  Play")

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
            self._mw.image_dir if self._mw.image_dir else "",
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
        self._timer.stop()
        self._ui.btn_video_play.setText("▶  Play")

        iw = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        ih = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        fname = os.path.basename(path)
        self._ui.lbl_video_info.setText(
            f"{fname}\n{iw}×{ih}  ·  {self._total_frames} frames  ·  {self._fps:.1f} fps"
        )

        self._ui.video_scrubber.setRange(0, max(0, self._total_frames - 1))
        self._ui.video_scrubber.setValue(0)
        self._set_controls_enabled(True)
        self._ui.btn_extract_frames.setEnabled(True)
        self._show_frame(0)

    def toggle_play(self):
        if not self._cap:
            return
        if self._playing:
            self._playing = False
            self._timer.stop()
            self._ui.btn_video_play.setText("▶  Play")
        else:
            self._playing = True
            self._timer.start(max(1, round(1000 / self._fps)))
            self._ui.btn_video_play.setText("⏸  Pause")

    def step_frame(self, delta: int):
        if not self._cap:
            return
        self._show_frame(self._current_frame + delta)

    def on_scrubber_moved(self, value: int):
        if not self._cap:
            return
        self._show_frame(value)

    def capture_frame(self):
        if not self._cap:
            return
        if not self._image_dir:
            QMessageBox.warning(self._mw, "No Image Folder",
                                "Please select an image folder first.")
            return

        import cv2
        self._cap.set(cv2.CAP_PROP_POS_FRAMES, self._current_frame)
        ret, frame = self._cap.read()
        if not ret:
            return

        stem = self._stem
        out_name = f"{stem}_f{self._current_frame:06d}.jpg"
        out_path = os.path.join(self._image_dir, out_name)

        if os.path.exists(out_path):
            # Find a non-colliding name
            i = 2
            base, ext = os.path.splitext(out_path)
            while os.path.exists(f"{base}_{i}{ext}"):
                i += 1
            out_path = f"{base}_{i}{ext}"

        cv2.imwrite(out_path, frame)

        # Add to file list if not already there
        fname = os.path.basename(out_path)
        existing = [self._ui.file_list.item(r).text()
                    for r in range(self._ui.file_list.count())]
        if fname not in existing:
            self._ui.file_list.addItem(fname)

        # Brief visual feedback on the label
        orig = self._ui.lbl_video_info.styleSheet()
        self._ui.lbl_video_info.setStyleSheet("color: #4caf50; font-size: 11px;")
        QTimer.singleShot(600, lambda: self._ui.lbl_video_info.setStyleSheet(orig))

    def open_extract_dialog(self):
        dlg = FrameExtractDialog(
            self._mw,
            video_path=self._video_path(),
            image_dir=self._image_dir,
        )
        if dlg.exec() == FrameExtractDialog.DialogCode.Accepted:
            # Refresh file list
            if self._image_dir and os.path.isdir(self._image_dir):
                exts = {'.jpg', '.jpeg', '.png'}
                files = [f for f in os.listdir(self._image_dir)
                         if os.path.splitext(f)[1].lower() in exts]
                self._ui.file_list.clear()
                self._ui.file_list.addItems(sorted(files))

    # ── Private ───────────────────────────────────────────────────────────────

    def _advance_frame(self):
        if not self._cap or not self._playing:
            return
        next_frame = self._current_frame + 1
        if next_frame >= self._total_frames:
            self.toggle_play()   # stop at end
            return
        self._show_frame(next_frame)

    def _show_frame(self, idx: int):
        import cv2
        idx = max(0, min(idx, self._total_frames - 1))
        self._cap.set(cv2.CAP_PROP_POS_FRAMES, idx)
        ret, frame = self._cap.read()
        if not ret:
            return
        self._current_frame = idx

        # BGR → RGB → QImage → QPixmap
        rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
        h, w, ch = rgb.shape
        qi = QImage(rgb.data, w, h, ch * w, QImage.Format.Format_RGB888)
        pix = QPixmap.fromImage(qi).scaled(
            self._ui.video_frame_label.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        self._ui.video_frame_label.setPixmap(pix)

        # Update scrubber and counter without re-triggering the signal
        self._ui.video_scrubber.blockSignals(True)
        self._ui.video_scrubber.setValue(idx)
        self._ui.video_scrubber.blockSignals(False)
        self._ui.lbl_video_counter.setText(f"{idx + 1} / {self._total_frames}")

    def _set_controls_enabled(self, enabled: bool):
        for w in (self._ui.btn_video_play,
                  self._ui.btn_video_prev,
                  self._ui.btn_video_next,
                  self._ui.btn_video_capture,
                  self._ui.video_scrubber):
            w.setEnabled(enabled)

    def _video_path(self) -> str:
        return getattr(self, '_path', '')
