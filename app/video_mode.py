"""VideoModeController — manages video playback and frame capture."""

import os

from PySide6.QtWidgets import QMessageBox

from app.frame_extract_dialog import FrameExtractDialog
from app.video_playback_base import VideoPlaybackBase


class VideoModeController(VideoPlaybackBase):
    def __init__(self, main_window):
        super().__init__(main_window)
        ui = main_window.ui
        self._play_btn      = ui.btn_video_play
        self._scrubber      = ui.video_scrubber
        self._frame_label   = ui.video_frame_label
        self._frame_input   = ui.video_frame_input
        self._counter_label = ui.lbl_video_counter

    # ── Slots (called from main.py) ───────────────────────────────────────────

    def open_video(self):
        result = self._load_video_cap(os.path.dirname(getattr(self, '_path', '')) or "")
        if result is None:
            return

        cap, path, stem, fps, total = result

        import cv2
        iw = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
        ih = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        self._ui.lbl_video_info.setText(
            f"{os.path.basename(path)}\n"
            f"{iw}×{ih}  ·  {total} frames  ·  {fps:.1f} fps"
        )

        self._scrubber.setRange(0, max(0, total - 1))
        self._scrubber.setValue(0)
        self._set_controls_enabled(True)
        self._ui.btn_extract_frames.setEnabled(True)
        self._show_frame(0)

    def capture_frame(self):
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

        fname = os.path.basename(out_path)
        existing = [self._ui.file_list.item(r).text()
                    for r in range(self._ui.file_list.count())]
        if fname not in existing:
            self._ui.file_list.addItem(fname)

        self._mw.statusBar().showMessage(f"Captured: {fname}", 3000)

    def open_extract_dialog(self):
        dlg = FrameExtractDialog(
            self._mw,
            video_path=getattr(self, '_path', ''),
            image_dir=self._image_dir,
        )
        if dlg.exec() == FrameExtractDialog.DialogCode.Accepted:
            if self._image_dir and os.path.isdir(self._image_dir):
                exts = {'.jpg', '.jpeg', '.png'}
                files = [f for f in os.listdir(self._image_dir)
                         if os.path.splitext(f)[1].lower() in exts]
                self._ui.file_list.clear()
                self._ui.file_list.addItems(sorted(files))

    # ── Private ───────────────────────────────────────────────────────────────

    def _set_controls_enabled(self, enabled: bool):
        for w in (self._play_btn,
                  self._ui.btn_video_prev,
                  self._ui.btn_video_next,
                  self._ui.btn_video_capture,
                  self._scrubber,
                  self._frame_input):
            w.setEnabled(enabled)
