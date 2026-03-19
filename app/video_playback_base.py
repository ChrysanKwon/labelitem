"""Shared video-playback logic for VideoModeController and ModelCheckController."""

import os

from PySide6.QtCore import QTimer

from app.video_utils import open_capture, bgr_to_pixmap


class VideoPlaybackBase:
    """Common video playback state and controls.

    Subclass must assign these widget references in __init__ before any
    playback methods are called:

        self._play_btn      — QPushButton  (▶ / ⏸)
        self._scrubber      — QSlider
        self._frame_label   — QLabel       (displays frames)
        self._frame_input   — QLineEdit    (1-based frame number)
        self._counter_label — QLabel       ("N / total")
    """

    def __init__(self, main_window):
        self._mw                = main_window
        self._cap               = None
        self._fps               = 25.0
        self._total_frames      = 0
        self._current_frame     = 0
        self._playing           = False
        self._current_frame_bgr = None

        self._play_timer = QTimer(main_window)
        self._play_timer.timeout.connect(self._advance_frame)

        # Widget references — subclass must populate before use
        self._play_btn      = None
        self._scrubber      = None
        self._frame_label   = None
        self._frame_input   = None
        self._counter_label = None

    # ── Convenience ───────────────────────────────────────────────────────────

    @property
    def _ui(self):
        return self._mw.ui

    @property
    def _image_dir(self) -> str:
        return self._mw.image_dir

    # ── Lifecycle ──────────────────────────────────────────────────────────────

    def pause(self):
        """Pause playback (called when leaving the tab)."""
        if self._playing:
            self._playing = False
            self._play_timer.stop()
            self._play_btn.setText("▶  Play")

    # ── Public playback slots ──────────────────────────────────────────────────

    def toggle_play(self):
        if not self._cap:
            return
        if self._playing:
            self._playing = False
            self._play_timer.stop()
            self._play_btn.setText("▶  Play")
        else:
            self._playing = True
            self._play_timer.start(max(1, round(1000 / self._fps)))
            self._play_btn.setText("⏸  Pause")

    def step_frame(self, delta: int):
        if not self._cap:
            return
        self._show_frame(self._current_frame + delta)

    def on_scrubber_moved(self, value: int):
        if not self._cap:
            return
        self._show_frame(value)

    def jump_to_frame_input(self):
        """Called when the user presses Enter in the frame input box."""
        try:
            idx = int(self._frame_input.text()) - 1  # 1-based display
            self._show_frame(idx)
        except ValueError:
            pass

    # ── Helpers ────────────────────────────────────────────────────────────────

    def _load_video_cap(self, initial_dir: str = ""):
        """Open a video file dialog and populate shared playback state.

        Returns (cap, path, stem, fps, total) on success, None on cancel.
        Also resets play state and updates the play button label.
        """
        result = open_capture(self._mw, initial_dir)
        if result is None:
            return None
        if self._cap:
            self._cap.release()
        cap, path, stem, fps, total = result
        self._cap           = cap
        self._path          = path
        self._stem          = stem
        self._fps           = fps
        self._total_frames  = total
        self._current_frame = 0
        self._playing       = False
        self._play_timer.stop()
        self._play_btn.setText("▶  Play")
        return result

    @staticmethod
    def _unique_out_path(out_path: str) -> str:
        """Return a collision-free path by appending _2, _3 … if needed."""
        if not os.path.exists(out_path):
            return out_path
        base, ext = os.path.splitext(out_path)
        i = 2
        while os.path.exists(f"{base}_{i}{ext}"):
            i += 1
        return f"{base}_{i}{ext}"

    # ── Private ────────────────────────────────────────────────────────────────

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

        self._frame_label.setPixmap(
            bgr_to_pixmap(frame, self._frame_label.size()))

        self._scrubber.blockSignals(True)
        self._scrubber.setValue(idx)
        self._scrubber.blockSignals(False)
        self._frame_input.blockSignals(True)
        self._frame_input.setText(str(idx + 1))
        self._frame_input.blockSignals(False)
        self._counter_label.setText(f"{idx + 1} / {self._total_frames}")

        self._on_frame_shown(idx, frame)

    def _on_frame_shown(self, idx: int, frame):
        """Hook called after each frame is rendered. Override in subclasses."""
        pass
