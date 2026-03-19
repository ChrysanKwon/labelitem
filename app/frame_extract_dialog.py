"""FrameExtractDialog — extract N frames from a video into the image folder."""

import os
import random

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QSpinBox, QButtonGroup, QDialogButtonBox, QMessageBox, QProgressDialog,
)
from PySide6.QtCore import Qt


class FrameExtractDialog(QDialog):
    def __init__(self, parent=None, video_path: str = "", image_dir: str = ""):
        super().__init__(parent)
        self.video_path = video_path
        self.image_dir  = image_dir

        self.setWindowTitle("Extract Frames")
        self.setMinimumWidth(380)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)

        layout = QVBoxLayout(self)
        layout.setSpacing(10)

        # Method
        layout.addWidget(QLabel("Extraction method:"))
        _btn_style = (
            "QPushButton { border:1px solid #555; border-radius:4px; color:#ccc;"
            " padding:4px 14px; background:#2d2d2d; }"
            "QPushButton:checked { background:#1565c0; color:white; font-weight:bold;"
            " border-color:#1565c0; }"
            "QPushButton:hover:!checked { background:#3a3a3a; }"
        )
        self.btn_evenly = QPushButton("Evenly Spaced")
        self.btn_random = QPushButton("Random")
        for btn in (self.btn_evenly, self.btn_random):
            btn.setCheckable(True)
            btn.setFixedHeight(30)
            btn.setStyleSheet(_btn_style)
        self.btn_evenly.setChecked(True)
        grp = QButtonGroup(self)
        grp.setExclusive(True)
        grp.addButton(self.btn_evenly, 0)
        grp.addButton(self.btn_random, 1)
        method_row = QHBoxLayout()
        method_row.addWidget(self.btn_evenly)
        method_row.addWidget(self.btn_random)
        layout.addLayout(method_row)

        # Count
        count_row = QHBoxLayout()
        count_row.addWidget(QLabel("Number of frames:"))
        self.spin_n = QSpinBox()
        self.spin_n.setRange(1, 9999)
        self.spin_n.setValue(50)
        self.spin_n.setFixedWidth(80)
        count_row.addWidget(self.spin_n)
        count_row.addStretch()
        layout.addLayout(count_row)

        # Output dir
        layout.addWidget(QLabel("Output folder:"))
        lbl_out = QLabel(image_dir or "(no image folder selected)")
        lbl_out.setStyleSheet("color: gray; font-size: 11px;")
        lbl_out.setWordWrap(True)
        layout.addWidget(lbl_out)

        layout.addSpacing(4)

        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.button(QDialogButtonBox.StandardButton.Ok).setText("Extract")
        btns.accepted.connect(self._run)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _run(self):
        if not self.image_dir:
            QMessageBox.warning(self, "No Image Folder",
                                "Please select an image folder first.")
            return
        if not self.video_path:
            QMessageBox.warning(self, "No Video", "No video is loaded.")
            return

        try:
            import cv2
        except ImportError:
            QMessageBox.critical(self, "OpenCV Not Installed",
                                 "Please run:  pip install opencv-python")
            return

        cap = cv2.VideoCapture(self.video_path)
        if not cap.isOpened():
            QMessageBox.critical(self, "Cannot Open Video",
                                 f"Failed to open:\n{self.video_path}")
            return

        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        n = min(self.spin_n.value(), total_frames)
        stem = os.path.splitext(os.path.basename(self.video_path))[0]

        if self.btn_evenly.isChecked():
            indices = [round(i * (total_frames - 1) / max(n - 1, 1)) for i in range(n)]
        else:
            indices = sorted(random.sample(range(total_frames), n))

        progress = QProgressDialog("Extracting frames…", "Cancel", 0, n, self)
        progress.setWindowTitle("Extract Frames")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumWidth(320)

        saved = 0
        for i, frame_idx in enumerate(indices):
            if progress.wasCanceled():
                break
            progress.setValue(i)

            out_name = f"{stem}_f{frame_idx:06d}.jpg"
            out_path = os.path.join(self.image_dir, out_name)
            if os.path.exists(out_path):
                continue   # skip — don't overwrite

            cap.set(cv2.CAP_PROP_POS_FRAMES, frame_idx)
            ret, frame = cap.read()
            if ret:
                cv2.imwrite(out_path, frame)
                saved += 1

        cap.release()
        progress.setValue(n)
        progress.close()

        QMessageBox.information(self, "Done", f"Saved {saved} frame(s) to:\n{self.image_dir}")
        self.accept()
