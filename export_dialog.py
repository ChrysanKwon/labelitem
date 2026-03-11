"""Export dataset dialog."""
from PySide6.QtWidgets import (QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
                               QComboBox, QSpinBox, QLineEdit, QPushButton,
                               QLabel, QDialogButtonBox, QFileDialog, QMessageBox)
from PySide6.QtCore import Qt
import os
import io_labels


class ExportDialog(QDialog):
    def __init__(self, parent=None, image_dir="", label_dir="", class_names=None):
        super().__init__(parent)
        self.image_dir   = image_dir
        self.label_dir   = label_dir
        self.class_names = class_names or []
        self._total, self._unlabeled = self._count_images()

        self.setWindowTitle("Export Dataset")
        self.setMinimumWidth(440)
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowType.WindowContextHelpButtonHint)
        self._build_ui()

    def _count_images(self):
        """Return (total_images, unlabeled_images)."""
        if not self.image_dir or not self.label_dir:
            return 0, 0
        img_exts = {'.jpg', '.jpeg', '.png'}
        total = 0
        unlabeled = 0
        for fname in os.listdir(self.image_dir):
            if os.path.splitext(fname)[1].lower() not in img_exts:
                continue
            total += 1
            txt = os.path.join(self.label_dir, os.path.splitext(fname)[0] + '.txt')
            if not os.path.exists(txt):
                unlabeled += 1
        return total, unlabeled

    def _build_ui(self):
        layout = QVBoxLayout(self)
        form = QFormLayout()
        form.setLabelAlignment(Qt.AlignmentFlag.AlignRight)

        # Format
        self.fmt = QComboBox()
        self.fmt.addItems(['YOLO', 'COCO'])
        form.addRow('Format:', self.fmt)

        # Output directory
        out_row = QHBoxLayout()
        self.out_edit = QLineEdit()
        self.out_edit.setPlaceholderText('Select output folder…')
        btn_browse = QPushButton('…')
        btn_browse.setFixedWidth(32)
        btn_browse.clicked.connect(self._browse_output)
        out_row.addWidget(self.out_edit)
        out_row.addWidget(btn_browse)
        form.addRow('Output dir:', out_row)

        # Train ratio
        ratio_row = QHBoxLayout()
        self.train_spin = QSpinBox()
        self.train_spin.setRange(10, 90)
        self.train_spin.setValue(80)
        self.train_spin.setSuffix(' %  (Train)')
        self.train_spin.valueChanged.connect(self._on_ratio_changed)
        self.val_label = QLabel('Val: 20 %')
        ratio_row.addWidget(self.train_spin)
        ratio_row.addWidget(self.val_label)
        form.addRow('Train ratio:', ratio_row)

        # Seed
        self.seed_spin = QSpinBox()
        self.seed_spin.setRange(0, 99999)
        self.seed_spin.setValue(42)
        form.addRow('Seed:', self.seed_spin)

        layout.addLayout(form)

        # Info
        labeled = self._total - self._unlabeled
        info = QLabel(f'{self._total} images total  ·  {labeled} labeled  ·  {self._unlabeled} unlabeled')
        info.setStyleSheet('color: gray; font-size: 11px;')
        layout.addWidget(info)

        # Unlabeled warning (shown only when relevant)
        if self._unlabeled > 0:
            warn = QLabel(
                f'⚠  {self._unlabeled} image(s) have no labels and will be treated as '
                f'background during training.'
            )
            warn.setWordWrap(True)
            warn.setStyleSheet('color: #e65100; font-size: 11px;')
            layout.addWidget(warn)

        layout.addSpacing(8)

        # OK / Cancel
        btns = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel
        )
        btns.button(QDialogButtonBox.StandardButton.Ok).setText('Export')
        btns.accepted.connect(self._on_export)
        btns.rejected.connect(self.reject)
        layout.addWidget(btns)

    def _browse_output(self):
        path = QFileDialog.getExistingDirectory(self, 'Select Output Directory')
        if path:
            self.out_edit.setText(path)

    def _on_ratio_changed(self, val):
        self.val_label.setText(f'Val: {100 - val} %')

    def _on_export(self):
        output_dir = self.out_edit.text().strip()
        if not output_dir:
            QMessageBox.warning(self, 'No Output Directory', 'Please select an output directory.')
            return
        if self._total == 0:
            QMessageBox.warning(self, 'No Images', 'No images found in the image directory.')
            return

        fmt         = self.fmt.currentText()
        train_ratio = self.train_spin.value() / 100
        seed        = self.seed_spin.value()

        try:
            if fmt == 'YOLO':
                n_train, n_val = io_labels.export_yolo_dataset(
                    self.image_dir, self.label_dir, self.class_names,
                    output_dir, train_ratio, seed
                )
            else:
                n_train, n_val = io_labels.export_coco_dataset(
                    self.image_dir, self.label_dir, self.class_names,
                    output_dir, train_ratio, seed
                )
        except Exception as e:
            QMessageBox.critical(self, 'Export Failed', str(e))
            return

        QMessageBox.information(
            self, 'Export Complete',
            f'Format: {fmt}\n'
            f'Train: {n_train}    Val: {n_val}\n'
            f'→ {output_dir}'
        )
        self.accept()
