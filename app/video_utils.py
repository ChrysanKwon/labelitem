"""Shared video-capture utilities used by VideoModeController and ModelCheckController."""

import os

from PySide6.QtWidgets import QFileDialog, QMessageBox

_VIDEO_FILTER = "Video files (*.mp4 *.avi *.mov *.mkv *.wmv *.flv *.webm)"


def open_capture(parent_widget, initial_dir: str = ""):
    """Show open-file dialog, validate the file, and return a ready VideoCapture.

    Returns (cap, path, stem, fps, total_frames) on success, or None if the
    user cancelled or the file could not be opened.
    """
    try:
        import cv2
    except ImportError:
        QMessageBox.critical(parent_widget, "OpenCV Not Installed",
                             "Please run:  pip install opencv-python")
        return None

    path, _ = QFileDialog.getOpenFileName(
        parent_widget, "Open Video",
        initial_dir,
        _VIDEO_FILTER,
    )
    if not path:
        return None

    cap = cv2.VideoCapture(path)
    if not cap.isOpened():
        QMessageBox.critical(parent_widget, "Cannot Open Video",
                             f"Failed to open:\n{path}")
        return None

    fps   = cap.get(cv2.CAP_PROP_FPS) or 25.0
    total = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    stem  = os.path.splitext(os.path.basename(path))[0]
    return cap, path, stem, fps, total


def bgr_to_pixmap(frame_bgr, target_size):
    """Convert a BGR numpy frame to a QPixmap scaled to target_size (QSize)."""
    import cv2
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QImage, QPixmap

    rgb = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2RGB)
    h, w, ch = rgb.shape
    qi = QImage(rgb.data, w, h, ch * w, QImage.Format.Format_RGB888)
    return QPixmap.fromImage(qi).scaled(
        target_size,
        Qt.AspectRatioMode.KeepAspectRatio,
        Qt.TransformationMode.SmoothTransformation,
    )
