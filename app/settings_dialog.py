"""Settings dialog for user-configurable preferences."""

from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout,
                                QPushButton, QCheckBox, QLabel, QGroupBox)
from app import config


class SettingsDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Settings")
        self.setMinimumWidth(360)
        self.setStyleSheet("background:#1e1e1e; color:#ccc;")

        cfg = config.load()
        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        # ── Model Check ──────────────────────────────────────────────────────
        mc_group = QGroupBox("Model Check")
        mc_group.setStyleSheet(
            "QGroupBox { color:#aaa; border:1px solid #444; border-radius:4px;"
            " margin-top:8px; padding-top:8px; }"
            "QGroupBox::title { subcontrol-origin:margin; left:8px; }"
        )
        mc_layout = QVBoxLayout(mc_group)

        self.chk_playback_cache = QCheckBox(
            "Cache inference results for video playback")
        self.chk_playback_cache.setChecked(cfg.get("playback_cache", False))
        self.chk_playback_cache.setStyleSheet("color:#ccc;")

        hint = QLabel(
            "When enabled, inference results are cached to .mc_cache/ (app folder).\n"
            "During playback, cached overlays are drawn without re-running inference.\n"
            "Recommended for short videos (< 2 min). Cache is cleared on close.")
        hint.setStyleSheet("color:#666; font-size:10px;")
        hint.setWordWrap(True)

        mc_layout.addWidget(self.chk_playback_cache)
        mc_layout.addWidget(hint)
        layout.addWidget(mc_group)

        # ── Buttons ──────────────────────────────────────────────────────────
        btn_row = QHBoxLayout()
        btn_row.addStretch()
        btn_ok = QPushButton("OK")
        btn_ok.setFixedWidth(80)
        btn_ok.setStyleSheet(
            "background:#1565c0; color:white; border-radius:4px; padding:4px;")
        btn_cancel = QPushButton("Cancel")
        btn_cancel.setFixedWidth(80)
        btn_cancel.setStyleSheet(
            "background:#2d2d2d; color:#ccc; border-radius:4px; padding:4px;")
        btn_row.addWidget(btn_cancel)
        btn_row.addWidget(btn_ok)
        layout.addLayout(btn_row)

        btn_ok.clicked.connect(self._save)
        btn_cancel.clicked.connect(self.reject)

    def _save(self):
        cfg = config.load()
        cfg["playback_cache"] = self.chk_playback_cache.isChecked()
        config.save(cfg)
        self.accept()
