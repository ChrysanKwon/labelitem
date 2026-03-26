"""
CheckEditDialog — edit a single image's labels from within Check Mode.

Opens a modal dialog with a full Canvas, class list, and shape list.
Saving writes the YOLO .txt immediately; closing without saving discards changes.
Check Mode is never exited, so the user's scroll position is preserved.
"""

import os

from PySide6.QtWidgets import (QDialog, QHBoxLayout, QVBoxLayout,
                               QPushButton, QListWidget, QListWidgetItem,
                               QLabel, QSizePolicy, QApplication, QMessageBox)
from PySide6.QtGui import QPixmap, QBrush, QKeySequence, QShortcut
from PySide6.QtCore import Qt, QSize

from app.ui_layout import Canvas, CLASS_COLORS
from app import io_labels
from app.utils import format_shape_label, apply_draw_mode


class CheckEditDialog(QDialog):
    """
    Parameters
    ----------
    parent       : QWidget
    image_path   : str   — full path to the image file
    txt_path     : str   — full path to the YOLO .txt (may not exist yet)
    class_names  : list[str]
    """

    def __init__(self, parent, image_path: str, txt_path: str, class_names: list[str],
                 select_box=None, annotation_mode: str = 'detection'):
        super().__init__(parent)
        self.txt_path         = txt_path
        self.image_path       = image_path
        self.class_names      = class_names
        self.annotation_mode  = annotation_mode
        self.delete_requested = False   # set True if user chose to delete image+label

        self.setWindowTitle(f"Edit — {os.path.basename(image_path)}")
        self.resize(1100, 700)
        self.setMinimumSize(700, 450)

        # ── Canvas ────────────────────────────────────────────────────────
        self.canvas = Canvas()
        self.canvas.class_names = list(class_names)
        pixmap = QPixmap(image_path)
        self.canvas.set_image(pixmap)

        shapes, shape_classes = io_labels.load_yolo(txt_path, annotation_mode)
        self.canvas.shapes        = shapes
        self.canvas.shape_classes = shape_classes

        # Pre-select the shape that was double-clicked in check view
        if select_box is not None:
            for i, shape in enumerate(shapes):
                if isinstance(select_box, list) and isinstance(shape, list):
                    # polygon: compare first vertex
                    if shape and select_box and abs(shape[0][0] - select_box[0][0]) < 1e-6:
                        self.canvas.selected_index = i
                        break
                elif isinstance(select_box, tuple) and isinstance(shape, tuple):
                    # bbox: compare cx, cy
                    if abs(shape[0] - select_box[0]) < 1e-6 and abs(shape[1] - select_box[1]) < 1e-6:
                        self.canvas.selected_index = i
                        break

        self.canvas.update()

        # ── Right panel ───────────────────────────────────────────────────
        right = QVBoxLayout()
        right.setSpacing(6)

        # Shape list
        right.addWidget(QLabel("Shapes:"))
        self.shape_list = QListWidget()
        self.shape_list.setSizePolicy(QSizePolicy.Policy.Preferred, QSizePolicy.Policy.Expanding)
        right.addWidget(self.shape_list, stretch=1)

        btn_del_shape = QPushButton("Delete Selected Shape  [Del]")
        btn_del_shape.setFixedHeight(30)
        btn_del_shape.clicked.connect(self._delete_selected_shape)
        right.addWidget(btn_del_shape)

        right.addSpacing(10)

        # Class list
        right.addWidget(QLabel("Classes (click to assign):"))
        self.class_list = QListWidget()
        self.class_list.setMaximumHeight(200)
        for i, name in enumerate(class_names):
            item = QListWidgetItem(name)
            color = CLASS_COLORS[i % len(CLASS_COLORS)]
            item.setForeground(QBrush(color))
            self.class_list.addItem(item)
        if self.class_list.count() > 0:
            self.class_list.setCurrentRow(0)
        right.addWidget(self.class_list)

        right.addSpacing(12)

        # Draw mode toggle (label and behaviour depend on annotation mode)
        if annotation_mode == 'segmentation':
            draw_label = "🔷 Polygon Draw  [P]"
        else:
            draw_label = "✏️ Rect Draw  [W]"
        self.btn_draw = QPushButton(draw_label)
        self.btn_draw.setCheckable(True)
        self.btn_draw.setFixedHeight(34)
        self.btn_draw.clicked.connect(self._toggle_draw_mode)
        right.addWidget(self.btn_draw)

        right.addSpacing(8)

        # Save & Close
        btn_save = QPushButton("💾 Save & Close")
        btn_save.setFixedHeight(40)
        btn_save.setStyleSheet(
            "background-color: #1565c0; color: white; font-weight: bold; border-radius: 5px;")
        btn_save.clicked.connect(self._save_and_close)
        right.addWidget(btn_save)

        btn_cancel = QPushButton("Discard & Close")
        btn_cancel.setFixedHeight(32)
        btn_cancel.clicked.connect(self.reject)
        right.addWidget(btn_cancel)

        right.addSpacing(16)

        btn_delete = QPushButton("🗑  Delete Image & Label")
        btn_delete.setFixedHeight(32)
        btn_delete.setStyleSheet(
            "background-color: #b71c1c; color: white; border-radius: 4px;")
        btn_delete.clicked.connect(self._delete_image_and_label)
        right.addWidget(btn_delete)

        # ── Layout ────────────────────────────────────────────────────────
        main = QHBoxLayout(self)
        main.addWidget(self.canvas, stretch=4)
        main.addLayout(right, stretch=1)

        # ── Signals ───────────────────────────────────────────────────────
        self.canvas.rectangle_drawn.connect(self._on_rectangle_drawn)
        self.canvas.polygon_drawn.connect(self._on_polygon_drawn)
        self.canvas.shape_modified.connect(self._on_shape_modified)
        self.canvas.selection_changed.connect(self._on_canvas_selection_changed)
        self.class_list.itemClicked.connect(self._on_class_selected)

        # Keyboard shortcuts — key depends on mode
        draw_key = "P" if annotation_mode == 'segmentation' else "W"
        QShortcut(QKeySequence(draw_key), self).activated.connect(
            lambda: self.btn_draw.setChecked(not self.btn_draw.isChecked()) or self._toggle_draw_mode())
        QShortcut(QKeySequence(Qt.Key.Key_Delete), self).activated.connect(self._delete_selected_shape)
        QShortcut(QKeySequence(Qt.Key.Key_Backspace), self).activated.connect(self._delete_selected_shape)
        QShortcut(QKeySequence("Ctrl+Z"), self).activated.connect(self._undo)
        QShortcut(QKeySequence("Ctrl+Shift+Z"), self).activated.connect(self._redo)

        self._refresh_shape_list()
        if self.canvas.selected_index >= 0:
            self.shape_list.setCurrentRow(self.canvas.selected_index)

    # ── Helpers ──────────────────────────────────────────────────────────

    def _current_class_idx(self) -> int:
        return self.class_list.currentRow()

    def _shape_label(self, idx: int) -> str:
        return format_shape_label(
            self.canvas.shapes[idx],
            self.canvas.shape_classes[idx],
            self.class_names,
            self.canvas.original_size,
        )

    def _refresh_shape_list(self):
        self.shape_list.clear()
        for i in range(len(self.canvas.shapes)):
            self.shape_list.addItem(self._shape_label(i))

    def _update_shape_in_list(self, idx: int):
        item = self.shape_list.item(idx)
        if item:
            item.setText(self._shape_label(idx))

    # ── Slots ─────────────────────────────────────────────────────────────

    def _toggle_draw_mode(self):
        apply_draw_mode(self.canvas, self.btn_draw, self.btn_draw.isChecked(),
                        polygon=(self.annotation_mode == 'segmentation'))

    def _on_rectangle_drawn(self, _rect):
        cls_idx = self._current_class_idx()
        last = len(self.canvas.shapes) - 1
        self.canvas.shape_classes[last] = cls_idx
        self.canvas.update()
        self.shape_list.addItem(self._shape_label(last))

    def _on_polygon_drawn(self, index: int):
        cls_idx = self._current_class_idx()
        self.canvas.shape_classes[index] = cls_idx
        self.canvas.update()
        self.shape_list.addItem(self._shape_label(index))

    def _undo(self):
        if self.canvas.undo():
            self._refresh_shape_list()

    def _redo(self):
        if self.canvas.redo():
            self._refresh_shape_list()

    def _on_canvas_selection_changed(self, idx: int):
        self.shape_list.setCurrentRow(idx)

    def _on_shape_modified(self, idx, _rect):
        self._update_shape_in_list(idx)
        self.shape_list.setCurrentRow(idx)

    def _on_class_selected(self, item):
        cls_idx = self.class_list.row(item)
        sel = self.canvas.selected_index
        if sel >= 0:
            self.canvas.save_snapshot()
            self.canvas.shape_classes[sel] = cls_idx
            self.canvas.update()
            self._refresh_shape_list()

    def _delete_selected_shape(self):
        # Canvas selection takes priority (user clicked a box on the image)
        row = self.canvas.selected_index
        if row < 0:
            row = self.shape_list.currentRow()
        if row < 0:
            return
        self.canvas.save_snapshot()
        self.shape_list.takeItem(row)
        self.canvas.shapes.pop(row)
        self.canvas.shape_classes.pop(row)
        self.canvas.selected_index = -1
        self.canvas.update()

    def _save_and_close(self):
        io_labels.save_yolo(
            self.txt_path,
            self.canvas.shapes,
            self.canvas.shape_classes,
        )
        self.accept()

    def _delete_image_and_label(self):
        """Double-confirm then delete the image file and its label."""
        fname = os.path.basename(self.image_path)
        reply = QMessageBox.question(
            self, "Delete Image?",
            f"Delete image and label for:\n{fname}\n\nThis cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        reply2 = QMessageBox.warning(
            self, "Confirm Permanent Delete",
            f"Permanently delete  {fname}  and its label file?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if reply2 != QMessageBox.StandardButton.Yes:
            return

        try:
            if os.path.exists(self.image_path):
                os.remove(self.image_path)
            if os.path.exists(self.txt_path):
                os.remove(self.txt_path)
        except OSError as e:
            QMessageBox.critical(self, "Delete Failed", str(e))
            return

        self.delete_requested = True
        self.reject()   # close without saving (files already gone)
