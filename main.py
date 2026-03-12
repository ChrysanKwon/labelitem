import sys
import os
from PySide6.QtWidgets import (QApplication, QMainWindow, QFileDialog,
                               QListWidget, QListWidgetItem, QMessageBox,
                               QLineEdit, QProgressDialog)
from PySide6.QtGui import QPixmap, QBrush, QIcon
from PySide6.QtCore import Qt, QTimer, QEvent, QThread
from app.ui_layout import Ui_MainWindow, CLASS_COLORS
from app import config
from app import io_labels
from app.export_dialog import ExportDialog
from app.auto_annotate_dialog import AutoAnnotateDialog, AnnotateWorker


class SimpleLabeler(QMainWindow):
    def __init__(self):
        super().__init__()
        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)
        self.image_dir        = ""
        self.save_dir         = ""
        self.current_img_name = ""
        self._annotate_thread = None
        self._annotate_worker = None

        # Load key scheme from config ("arrows" or "ad")
        _nav = config.load().get("nav_keys", "arrows")
        if _nav == "ad":
            self._nav_prev = Qt.Key.Key_A
            self._nav_next = Qt.Key.Key_D
        else:   # "arrows" (default)
            self._nav_prev = Qt.Key.Key_Left
            self._nav_next = Qt.Key.Key_Right

        # Signal connections
        self.ui.btn_img_dir.clicked.connect(self.select_img_dir)
        self.ui.btn_save_dir.clicked.connect(self.select_save_dir)
        self.ui.btn_export_dataset.clicked.connect(self.export_dataset)
        self.ui.btn_auto_annotate.clicked.connect(self.auto_annotate)
        self.ui.btn_check_mode.toggled.connect(self.toggle_check_mode)
        self.ui.file_list.itemClicked.connect(self.load_image)
        self.ui.check_class_list.itemClicked.connect(self.on_check_class_selected)
        self.ui.check_view.itemDoubleClicked.connect(self.on_check_item_double_clicked)
        self.ui.canvas.rectangle_drawn.connect(lambda _: self.on_rectangle_drawn())
        self.ui.canvas.shape_modified.connect(lambda idx, _: self.on_shape_modified(idx))
        self.ui.shape_list.keyPressEvent = self.shape_list_key_press

        # Class management
        self.ui.btn_add_class.clicked.connect(self.add_class)
        self.ui.class_input.returnPressed.connect(self.add_class)
        self.ui.btn_del_class.clicked.connect(self.delete_class)
        self.ui.class_list.itemClicked.connect(self.on_class_selected)

        # Intercept nav keys at app level so they work regardless of which
        # widget has focus (but skip when a text input is focused).
        QApplication.instance().installEventFilter(self)

        self._restore_session()

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.KeyPress:
            focused = QApplication.focusWidget()
            if not isinstance(focused, QLineEdit):
                key = event.key()
                if key == self._nav_prev:
                    self._switch_image(-1)
                    return True
                if key == self._nav_next:
                    self._switch_image(1)
                    return True
        return super().eventFilter(obj, event)

    # ── Session persistence ───────────────────────────────────────────────────

    def _restore_session(self):
        cfg = config.load()
        img_dir = cfg.get("image_dir", "")
        if img_dir and os.path.isdir(img_dir):
            self._apply_image_dir(img_dir, defer_load=True)
        save_dir = cfg.get("save_dir", "")
        if save_dir and os.path.isdir(save_dir):
            self.save_dir = save_dir
            self.ui.lbl_save_path.setText(save_dir)

    def _save_session(self):
        cfg = config.load()
        cfg["image_dir"] = self.image_dir
        cfg["save_dir"]  = self.save_dir
        config.save(cfg)

    # ── Directories / images ─────────────────────────────────────────────────

    def _apply_image_dir(self, path, defer_load=False):
        """Apply image directory: update UI, file list, default label dir, load classes.txt.
        defer_load=True defers loading the first image until after the window is shown.
        """
        self.image_dir = path
        self.ui.lbl_img_path.setText(path)
        files = [f for f in os.listdir(path) if f.lower().endswith(('.jpg', '.png', '.jpeg'))]
        self.ui.file_list.clear()
        self.ui.file_list.addItems(files)
        self.save_dir = path
        self.ui.lbl_save_path.setText(path)
        self._load_classes()
        if self.ui.file_list.count() > 0:
            self.ui.file_list.setCurrentRow(0)
            if defer_load:
                QTimer.singleShot(0, lambda: self.load_image(self.ui.file_list.item(0)))
            else:
                self.load_image(self.ui.file_list.item(0))

    def select_img_dir(self):
        path = QFileDialog.getExistingDirectory(self, "Select Image Directory")
        if path:
            self._apply_image_dir(path)
            self._save_session()

    def select_save_dir(self):
        path = QFileDialog.getExistingDirectory(self, "Select Label Directory")
        if path:
            self.save_dir = path
            self.ui.lbl_save_path.setText(path)
            self._load_classes()
            self._save_session()

    def load_image(self, item):
        """Switch image: autosave current, load new image, restore existing labels."""
        self._autosave_yolo()

        self.current_img_name = item.text()
        img_path = os.path.join(self.image_dir, self.current_img_name)
        self.ui.canvas.set_image(QPixmap(img_path))

        txt_path = self._txt_path_for(self.current_img_name)
        shapes, shape_classes = io_labels.load_yolo(txt_path)
        self.ui.canvas.shapes        = shapes
        self.ui.canvas.shape_classes = shape_classes
        self.ui.canvas.update()
        self._refresh_shape_list()

    def _txt_path_for(self, img_name: str) -> str:
        base = os.path.splitext(img_name)[0] + ".txt"
        return os.path.join(self.save_dir, base)

    # ── YOLO auto-save ────────────────────────────────────────────────────────

    def _autosave_yolo(self):
        """Save current boxes as a YOLO .txt. Skips if no image or directory is set.
        If there are no boxes, deletes the .txt (if it exists) to avoid being
        mistaken for a background image.
        """
        if not self.current_img_name or not self.save_dir:
            return
        canvas = self.ui.canvas
        if not canvas.original_size:
            return
        txt_path = self._txt_path_for(self.current_img_name)
        if not canvas.shapes:
            if os.path.exists(txt_path):
                os.remove(txt_path)
            return
        io_labels.save_yolo(txt_path, canvas.shapes, canvas.shape_classes)

    # ── Box operations ────────────────────────────────────────────────────────

    def _current_class_idx(self):
        return self.ui.class_list.currentRow()

    def _shape_label(self, shape_idx):
        cx, cy, nw, nh = self.ui.canvas.shapes[shape_idx]
        cls_idx = self.ui.canvas.shape_classes[shape_idx]
        cls_name = (self.ui.class_list.item(cls_idx).text()
                    if 0 <= cls_idx < self.ui.class_list.count() else "unassigned")
        if self.ui.canvas.original_size:
            iw = self.ui.canvas.original_size.width()
            ih = self.ui.canvas.original_size.height()
            x = round((cx - nw / 2) * iw); y = round((cy - nh / 2) * ih)
            w = round(nw * iw);             h = round(nh * ih)
            return f"[{cls_name}] {x},{y} {w}×{h}"
        return f"[{cls_name}] {cx:.3f},{cy:.3f}"

    def on_rectangle_drawn(self):
        cls_idx = self._current_class_idx()
        last = len(self.ui.canvas.shapes) - 1
        self.ui.canvas.shape_classes[last] = cls_idx
        self.ui.canvas.update()
        self.ui.shape_list.addItem(self._shape_label(last))
        self._autosave_yolo()

    def on_shape_modified(self, index):
        self.update_shape_in_list(index)
        self._autosave_yolo()

    def update_shape_in_list(self, index):
        item = self.ui.shape_list.item(index)
        if item:
            item.setText(self._shape_label(index))

    def _delete_shape(self, row):
        self.ui.shape_list.takeItem(row)
        self.ui.canvas.shapes.pop(row)
        self.ui.canvas.shape_classes.pop(row)
        self.ui.canvas.selected_index = -1
        self.ui.canvas.update()
        self._autosave_yolo()

    def shape_list_key_press(self, event):
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            row = self.ui.shape_list.currentRow()
            if row >= 0:
                self._delete_shape(row)
        else:
            super(QListWidget, self.ui.shape_list).keyPressEvent(event)

    def keyPressEvent(self, event):
        # Nav keys are handled by eventFilter globally.
        # Only handle Delete/Backspace here (deletes selected canvas box).
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            sel = self.ui.canvas.selected_index
            if sel >= 0:
                self._delete_shape(sel)
                return
        super().keyPressEvent(event)

    def _switch_image(self, delta: int):
        """Switch to the previous (delta=-1) or next (delta=+1) image."""
        count = self.ui.file_list.count()
        if count == 0:
            return
        current = self.ui.file_list.currentRow()
        new_row = (max(current, 0) + delta) % count
        self.ui.file_list.setCurrentRow(new_row)
        self.load_image(self.ui.file_list.currentItem())

    # ── Class management ──────────────────────────────────────────────────────

    def add_class(self):
        name = self.ui.class_input.text().strip()
        if not name:
            return
        self.ui.class_list.addItem(name)
        self.ui.class_input.clear()
        self.ui.class_list.setCurrentRow(self.ui.class_list.count() - 1)
        self._refresh_class_colors()
        self._save_classes()

    def delete_class(self):
        row = self.ui.class_list.currentRow()
        if row < 0:
            return
        self.ui.class_list.takeItem(row)
        for i, cls_idx in enumerate(self.ui.canvas.shape_classes):
            if cls_idx == row:
                self.ui.canvas.shape_classes[i] = -1
            elif cls_idx > row:
                self.ui.canvas.shape_classes[i] -= 1
        self.ui.canvas.update()
        self._refresh_shape_list()
        self._save_classes()

    def on_class_selected(self, item):
        cls_idx = self.ui.class_list.row(item)
        sel = self.ui.canvas.selected_index
        if sel >= 0:
            self.ui.canvas.shape_classes[sel] = cls_idx
            self.ui.canvas.update()
            self._refresh_shape_list()
            self._autosave_yolo()

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _refresh_class_colors(self):
        for i in range(self.ui.class_list.count()):
            color = CLASS_COLORS[i % len(CLASS_COLORS)]
            self.ui.class_list.item(i).setForeground(QBrush(color))
        self.ui.canvas.class_names = [
            self.ui.class_list.item(i).text()
            for i in range(self.ui.class_list.count())
        ]
        self.ui.canvas.update()

    def _save_classes(self):
        """Save class list to classes.txt in the label directory."""
        if not self.save_dir:
            return
        names = [self.ui.class_list.item(i).text()
                 for i in range(self.ui.class_list.count())]
        with open(os.path.join(self.save_dir, "classes.txt"), "w", encoding="utf-8") as f:
            f.write("\n".join(names))

    def _load_classes(self):
        """Restore class list from classes.txt if it exists."""
        if not self.save_dir:
            return
        path = os.path.join(self.save_dir, "classes.txt")
        if not os.path.exists(path):
            return
        with open(path, "r", encoding="utf-8") as f:
            names = [line.strip() for line in f if line.strip()]
        self.ui.class_list.clear()
        for name in names:
            self.ui.class_list.addItem(name)
        self._refresh_class_colors()

    def _refresh_shape_list(self):
        self.ui.shape_list.clear()
        for i in range(len(self.ui.canvas.shapes)):
            self.ui.shape_list.addItem(self._shape_label(i))

    # ── Check mode ───────────────────────────────────────────────────────────

    def toggle_check_mode(self, checked: bool):
        if checked:
            self.ui.btn_check_mode.setText("✏️  Label Mode")
            self.ui.center_stack.setCurrentIndex(1)
            self.ui.bottom_left_stack.setCurrentIndex(1)
            # Sync class list into check_class_list
            self.ui.check_class_list.clear()
            for i in range(self.ui.class_list.count()):
                src = self.ui.class_list.item(i)
                self.ui.check_class_list.addItem(src.text())
                self.ui.check_class_list.item(i).setForeground(src.foreground())
            # Auto-select first class and refresh
            if self.ui.check_class_list.count() > 0:
                self.ui.check_class_list.setCurrentRow(0)
                self._refresh_check_view(0)
        else:
            self.ui.btn_check_mode.setText("🔍 Check Mode")
            self.ui.center_stack.setCurrentIndex(0)
            self.ui.bottom_left_stack.setCurrentIndex(0)
            self.ui.check_view.clear()

    def on_check_class_selected(self, item):
        self._refresh_check_view(self.ui.check_class_list.row(item))

    def _refresh_check_view(self, cls_idx: int):
        """Populate check_view with all cropped boxes of cls_idx across all images."""
        self.ui.check_view.clear()
        if not self.image_dir or not self.save_dir:
            return

        img_exts = {'.jpg', '.jpeg', '.png'}
        for fname in sorted(os.listdir(self.image_dir)):
            if os.path.splitext(fname)[1].lower() not in img_exts:
                continue
            txt_path = os.path.join(self.save_dir, os.path.splitext(fname)[0] + '.txt')
            if not os.path.exists(txt_path):
                continue

            pixmap = QPixmap(os.path.join(self.image_dir, fname))
            if pixmap.isNull():
                continue
            iw, ih = pixmap.width(), pixmap.height()

            with open(txt_path, 'r', encoding='utf-8') as f:
                for line in f:
                    parts = line.strip().split()
                    if len(parts) != 5 or int(parts[0]) != cls_idx:
                        continue
                    cx, cy, nw, nh = float(parts[1]), float(parts[2]), float(parts[3]), float(parts[4])
                    x = max(0, int((cx - nw / 2) * iw))
                    y = max(0, int((cy - nh / 2) * ih))
                    w = min(int(nw * iw), iw - x)
                    h = min(int(nh * ih), ih - y)
                    if w < 1 or h < 1:
                        continue
                    crop = pixmap.copy(x, y, w, h)
                    item = QListWidgetItem(QIcon(crop), fname)
                    item.setData(Qt.ItemDataRole.UserRole, fname)
                    self.ui.check_view.addItem(item)

    def on_check_item_double_clicked(self, item):
        """Switch to label mode and navigate to the image that was double-clicked."""
        fname = item.data(Qt.ItemDataRole.UserRole)
        if not fname:
            return
        # Exit check mode
        self.ui.btn_check_mode.setChecked(False)
        # Find and select the image in file_list
        for i in range(self.ui.file_list.count()):
            if self.ui.file_list.item(i).text() == fname:
                self.ui.file_list.setCurrentRow(i)
                self.load_image(self.ui.file_list.item(i))
                break

    # ── Auto annotate ─────────────────────────────────────────────────────────

    def auto_annotate(self):
        if not self.image_dir:
            QMessageBox.warning(self, "No Image Directory",
                                "Please select an image directory first.")
            return
        if not self.save_dir:
            QMessageBox.warning(self, "No Label Directory",
                                "Please select a label directory first.")
            return

        dlg = AutoAnnotateDialog(self)
        if dlg.exec() != AutoAnnotateDialog.DialogCode.Accepted:
            return

        model_path = dlg.model_path
        conf = dlg.conf()

        reply = QMessageBox.warning(
            self, "Overwrite Labels?",
            "This will overwrite ALL existing label files (.txt) in the label directory.\n\n"
            "Are you sure you want to continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            import ultralytics  # noqa: F401 — check install before spawning thread
        except ImportError:
            QMessageBox.critical(self, "Ultralytics Not Installed",
                                 "Please run:  pip install ultralytics")
            return

        img_exts = {'.jpg', '.jpeg', '.png', '.bmp', '.webp'}
        images = [f for f in os.listdir(self.image_dir)
                  if os.path.splitext(f)[1].lower() in img_exts]
        if not images:
            QMessageBox.information(self, "No Images",
                                    "No images found in the image directory.")
            return

        self._autosave_yolo()

        # Progress dialog — disable auto-close so it doesn't fire canceled when done
        progress = QProgressDialog("Loading model…", "Cancel", 0, len(images), self)
        progress.setWindowTitle("Auto Annotate")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumWidth(400)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        progress.setValue(0)
        progress.show()

        # Worker + thread
        worker = AnnotateWorker(model_path, conf, images, self.image_dir, self.save_dir)
        thread = QThread(self)
        worker.moveToThread(thread)

        worker.progress.connect(lambda cur, total, fname: (
            progress.setValue(cur),
            progress.setLabelText(f"[{cur}/{total}] {fname}"),
        ))
        progress.canceled.connect(worker.cancel)

        def on_finished(errors):
            # Thread is still running — switch button to Finish, don't close yet
            progress.canceled.disconnect(worker.cancel)
            progress.setLabelText(f"Done — {len(images)} image(s) annotated.")
            progress.setCancelButtonText("Finish")

            def on_finish_clicked():
                progress.close()
                thread.quit()

                try:
                    self._load_classes()
                    if self.current_img_name:
                        txt_path = self._txt_path_for(self.current_img_name)
                        shapes, shape_classes = io_labels.load_yolo(txt_path)
                        self.ui.canvas.shapes        = shapes
                        self.ui.canvas.shape_classes = shape_classes
                        self.ui.canvas.update()
                        self._refresh_shape_list()
                except Exception as e:
                    QMessageBox.critical(self, "Auto Annotate — Post-process Error", str(e))
                    return

                if errors:
                    QMessageBox.warning(self, "Auto Annotate — Some Errors",
                                        f"Completed with {len(errors)} error(s):\n\n" +
                                        "\n".join(errors[:10]))

            progress.canceled.connect(on_finish_clicked)

        # Wire lifecycle: thread done → schedule deletion
        worker.finished.connect(on_finished)
        thread.finished.connect(thread.deleteLater)
        thread.finished.connect(worker.deleteLater)
        thread.started.connect(worker.run)
        thread.start()

        # Keep references alive until thread.deleteLater fires
        self._annotate_thread = thread
        self._annotate_worker = worker

    # ── Dataset export ────────────────────────────────────────────────────────

    def export_dataset(self):
        if not self.image_dir:
            QMessageBox.warning(self, "No Image Directory",
                                "Please select an image directory before exporting.")
            return
        self._autosave_yolo()

        class_names = [self.ui.class_list.item(i).text()
                       for i in range(self.ui.class_list.count())]
        dlg = ExportDialog(
            self,
            image_dir=self.image_dir,
            label_dir=self.save_dir or self.image_dir,
            class_names=class_names,
        )
        dlg.exec()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = SimpleLabeler()
    window.show()
    sys.exit(app.exec())
