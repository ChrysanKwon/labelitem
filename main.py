import sys
import os
from PySide6.QtWidgets import (QApplication, QMainWindow, QFileDialog,
                               QListWidget, QMessageBox,
                               QLineEdit, QProgressDialog)
from PySide6.QtGui import QPixmap, QBrush
from PySide6.QtCore import Qt, QTimer, QEvent, QThread
from app.ui_layout import Ui_MainWindow, CLASS_COLORS
from app import config
from app import io_labels
from app.export_dialog import ExportDialog
from app.auto_annotate_dialog import AutoAnnotateDialog, AnnotateWorker
from app.check_mode import CheckModeController
from app.video_mode import VideoModeController
from app.model_check import ModelCheckController
from app.utils import format_shape_label, apply_draw_mode


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
        self._check = CheckModeController(self)
        self._video = VideoModeController(self)
        self._mc    = ModelCheckController(self)

        # Load key scheme from config ("arrows" or "ad")
        _nav = config.load().get("nav_keys", "arrows")
        if _nav == "ad":
            self._nav_prev = Qt.Key.Key_A
            self._nav_next = Qt.Key.Key_D
        else:   # "arrows" (default)
            self._nav_prev = Qt.Key.Key_Left
            self._nav_next = Qt.Key.Key_Right

        # Annotation mode (detection / segmentation)
        _cfg = config.load()
        self.annotation_mode = _cfg.get("annotation_mode", "detection")
        if self.annotation_mode == "segmentation":
            self.ui.btn_mode_seg.setChecked(True)
        else:
            self.ui.btn_mode_det.setChecked(True)

        # Signal connections
        self.ui.btn_img_dir.clicked.connect(self.select_img_dir)
        self.ui.btn_save_dir.clicked.connect(self.select_save_dir)
        self.ui.btn_export_dataset.clicked.connect(self.export_dataset)
        self.ui.btn_auto_annotate.clicked.connect(self.auto_annotate)
        self.ui.btn_draw_mode.clicked.connect(self._toggle_draw_mode)
        self.ui.btn_polygon_mode.clicked.connect(self._toggle_polygon_mode)
        self.ui.btn_delete_image.clicked.connect(self._delete_current_image)
        self.ui.btn_clean_labels.clicked.connect(self._clean_orphaned_labels)
        self.ui.btn_mode_det.clicked.connect(lambda: self._on_annotation_mode_changed("detection"))
        self.ui.btn_mode_seg.clicked.connect(lambda: self._on_annotation_mode_changed("segmentation"))
        self.ui.btn_convert_to_seg.clicked.connect(self._convert_to_seg)
        self.ui.btn_convert_to_det.clicked.connect(self._convert_to_det)
        # Nav column
        self.ui.btn_nav_label.clicked.connect(lambda: self._on_nav("label"))
        self.ui.btn_nav_check.clicked.connect(lambda: self._on_nav("check"))
        self.ui.btn_nav_video.clicked.connect(lambda: self._on_nav("video"))
        self.ui.btn_nav_model_check.clicked.connect(lambda: self._on_nav("model_check"))
        # Model Check controls
        self.ui.btn_mc_open_video.clicked.connect(self._mc.open_video)
        self.ui.btn_mc_load_model.clicked.connect(self._mc.load_model)
        self.ui.btn_mc_play.clicked.connect(self._mc.toggle_play)
        self.ui.btn_mc_prev.clicked.connect(lambda: self._mc.step_frame(-1))
        self.ui.btn_mc_next.clicked.connect(lambda: self._mc.step_frame(1))
        self.ui.mc_scrubber.valueChanged.connect(self._mc.on_scrubber_moved)
        self.ui.mc_frame_input.returnPressed.connect(self._mc.jump_to_frame_input)
        self.ui.mc_conf_spin.valueChanged.connect(self._mc.on_conf_changed)
        self.ui.mc_class_filter.currentTextChanged.connect(self._mc.filter_detections)
        self.ui.btn_mc_delete_det.clicked.connect(self._mc.delete_detection)
        self.ui.btn_mc_capture.clicked.connect(self._mc.capture_with_labels)
        self.ui.btn_mc_mode_frame.clicked.connect(
            lambda: self.ui.mc_mode_stack.setCurrentIndex(0))
        self.ui.btn_mc_mode_scan.clicked.connect(
            lambda: self.ui.mc_mode_stack.setCurrentIndex(1))
        self.ui.btn_mc_scan.clicked.connect(self._mc.scan_all_frames)
        self.ui.mc_scan_class_combo.currentTextChanged.connect(self._mc._apply_scan_filter)
        self.ui.mc_scan_count_input.returnPressed.connect(self._mc._apply_scan_filter)
        self.ui.mc_scan_list.currentRowChanged.connect(self._mc.jump_to_scan_frame)
        # Video mode controls
        self.ui.btn_open_video.clicked.connect(self._video.open_video)
        self.ui.btn_extract_frames.clicked.connect(self._video.open_extract_dialog)
        self.ui.btn_video_play.clicked.connect(self._video.toggle_play)
        self.ui.btn_video_prev.clicked.connect(lambda: self._video.step_frame(-1))
        self.ui.btn_video_next.clicked.connect(lambda: self._video.step_frame(1))
        self.ui.btn_video_capture.clicked.connect(self._video.capture_frame)
        self.ui.video_scrubber.valueChanged.connect(self._video.on_scrubber_moved)
        self.ui.video_frame_input.returnPressed.connect(self._video.jump_to_frame_input)
        self.ui.file_list.itemClicked.connect(self.load_image)
        self.ui.check_class_list.itemClicked.connect(self._check.on_class_selected)
        self.ui.check_view.itemDoubleClicked.connect(self._check.on_item_double_clicked)
        self.ui.canvas.rectangle_drawn.connect(lambda _: self.on_rectangle_drawn())
        self.ui.canvas.polygon_drawn.connect(self.on_polygon_drawn)
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

        self._apply_mode_tool_state()
        self._restore_session()

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.KeyPress:
            focused = QApplication.focusWidget()
            if not isinstance(focused, QLineEdit):
                key = event.key()
                in_label = self.ui.btn_nav_label.isChecked()
                in_video = self.ui.btn_nav_video.isChecked()
                in_mc    = self.ui.btn_nav_model_check.isChecked()

                if in_video or in_mc:
                    if key == self._nav_prev:
                        (self._video if in_video else self._mc).step_frame(-1)
                        return True
                    if key == self._nav_next:
                        (self._video if in_video else self._mc).step_frame(1)
                        return True

                if not in_label:
                    return super().eventFilter(obj, event)
                if key == self._nav_prev:
                    self._switch_image(-1)
                    return True
                if key == self._nav_next:
                    self._switch_image(1)
                    return True
                if key == Qt.Key.Key_W and self.annotation_mode == 'detection':
                    self._toggle_draw_mode()
                    return True
                if key == Qt.Key.Key_P and self.annotation_mode == 'segmentation':
                    self._toggle_polygon_mode()
                    return True
                mods = event.modifiers()
                if key == Qt.Key.Key_Z and mods & Qt.KeyboardModifier.ControlModifier:
                    if mods & Qt.KeyboardModifier.ShiftModifier:
                        self._redo()
                    else:
                        self._undo()
                    return True
                if key == Qt.Key.Key_Delete and mods & Qt.KeyboardModifier.ControlModifier:
                    if self.ui.btn_nav_label.isChecked():
                        self._delete_current_image()
                    return True
        return super().eventFilter(obj, event)

    def _toggle_draw_mode(self):
        canvas = self.ui.canvas
        apply_draw_mode(canvas, self.ui.btn_draw_mode, not canvas.draw_mode)
        if canvas.draw_mode:   # turning on rect → turn off polygon
            apply_draw_mode(canvas, self.ui.btn_polygon_mode, False, polygon=True)

    def _toggle_polygon_mode(self):
        canvas = self.ui.canvas
        apply_draw_mode(canvas, self.ui.btn_polygon_mode, not canvas.polygon_mode, polygon=True)
        if canvas.polygon_mode:   # turning on polygon → turn off rect
            apply_draw_mode(canvas, self.ui.btn_draw_mode, False)

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
            self._load_classes()

    def _save_session(self):
        cfg = config.load()
        cfg["image_dir"]       = self.image_dir
        cfg["save_dir"]        = self.save_dir
        cfg["annotation_mode"] = self.annotation_mode
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

        if self.ui.btn_nav_check.isChecked():
            self._check.enter()

    def select_img_dir(self):
        start = self.image_dir if self.image_dir and os.path.isdir(self.image_dir) else ""
        path = QFileDialog.getExistingDirectory(self, "Select Image Directory", start)
        if path:
            self._apply_image_dir(path)
            self._save_session()

    def select_save_dir(self):
        start = self.save_dir if self.save_dir and os.path.isdir(self.save_dir) else (self.image_dir if self.image_dir else "")
        path = QFileDialog.getExistingDirectory(self, "Select Label Directory", start)
        if path:
            self.save_dir = path
            self.ui.lbl_save_path.setText(path)
            self._load_classes()
            self._save_session()
            if self.ui.btn_nav_check.isChecked():
                self._check.enter()
            # Reload labels for the currently displayed image
            self._reload_shapes()

    def load_image(self, item):
        """Switch image: autosave current, load new image, restore existing labels."""
        if self.current_img_name and self.ui.canvas.original_size:
            unassigned_count = sum(1 for c in self.ui.canvas.shape_classes if c < 0)
            if unassigned_count:
                box = QMessageBox(self)
                box.setWindowTitle("Unassigned Shapes")
                box.setText(
                    f"{unassigned_count} shape(s) have no class assigned.\n\n"
                    "They will not be saved if you switch images now."
                )
                btn_back = box.addButton("Go Back", QMessageBox.ButtonRole.RejectRole)
                box.addButton("Skip & Discard", QMessageBox.ButtonRole.DestructiveRole)
                box.setDefaultButton(btn_back)
                box.exec()
                if box.clickedButton() is btn_back:
                    # Restore file list selection to current image
                    for i in range(self.ui.file_list.count()):
                        if self.ui.file_list.item(i).text() == self.current_img_name:
                            self.ui.file_list.setCurrentRow(i)
                            break
                    return

        self._autosave_yolo()

        self.current_img_name = item.text()
        img_path = os.path.join(self.image_dir, self.current_img_name)
        self.ui.canvas.set_image(QPixmap(img_path))

        txt_path = self._txt_path_for(self.current_img_name)
        shapes, shape_classes = io_labels.load_yolo(txt_path, self.annotation_mode)
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
        mistaken for a background image — unless the file contains labels from
        the other annotation mode, in which case it is left untouched.
        """
        if not self.current_img_name or not self.save_dir:
            return
        canvas = self.ui.canvas
        if not canvas.original_size:
            return
        txt_path = self._txt_path_for(self.current_img_name)
        if not canvas.shapes:
            if os.path.exists(txt_path) and not self._txt_has_other_mode_labels(txt_path):
                os.remove(txt_path)
            return
        io_labels.save_yolo(txt_path, canvas.shapes, canvas.shape_classes)
        self.statusBar().showMessage(
            f"Saved: {os.path.basename(txt_path)}  ({len(canvas.shapes)} shape(s))", 2000)

    def _txt_has_other_mode_labels(self, txt_path: str) -> bool:
        """Return True if the .txt contains lines that belong to the OTHER annotation mode."""
        try:
            with open(txt_path, 'r', encoding='utf-8') as f:
                for line in f:
                    parts = line.strip().split()
                    if not parts:
                        continue
                    if self.annotation_mode == 'detection':
                        # Other mode = segmentation: odd field count >= 7
                        if len(parts) >= 7 and len(parts) % 2 == 1:
                            return True
                    else:
                        # Other mode = detection: exactly 5 fields
                        if len(parts) == 5:
                            return True
        except OSError:
            pass
        return False

    # ── Box operations ────────────────────────────────────────────────────────

    def _current_class_idx(self):
        return self.ui.class_list.currentRow()

    def _shape_label(self, shape_idx):
        canvas = self.ui.canvas
        class_names = [self.ui.class_list.item(i).text()
                       for i in range(self.ui.class_list.count())]
        return format_shape_label(
            canvas.shapes[shape_idx],
            canvas.shape_classes[shape_idx],
            class_names,
            canvas.original_size,
        )

    def on_rectangle_drawn(self):
        cls_idx = self._current_class_idx()
        last = len(self.ui.canvas.shapes) - 1
        self.ui.canvas.shape_classes[last] = cls_idx
        self.ui.canvas.update()
        self.ui.shape_list.addItem(self._shape_label(last))
        self._autosave_yolo()

    def on_polygon_drawn(self, index: int):
        cls_idx = self._current_class_idx()
        self.ui.canvas.shape_classes[index] = cls_idx
        self.ui.canvas.update()
        self.ui.shape_list.addItem(self._shape_label(index))
        self._autosave_yolo()

    def on_shape_modified(self, index):
        self.update_shape_in_list(index)
        self._autosave_yolo()

    def update_shape_in_list(self, index):
        item = self.ui.shape_list.item(index)
        if item:
            item.setText(self._shape_label(index))

    def _undo(self):
        if self.ui.canvas.undo():
            self._refresh_shape_list()
            self._autosave_yolo()

    def _redo(self):
        if self.ui.canvas.redo():
            self._refresh_shape_list()
            self._autosave_yolo()

    def _delete_shape(self, row):
        self.ui.canvas.save_snapshot()
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
        new_row = max(0, min(max(current, 0) + delta, count - 1))
        self.ui.file_list.setCurrentRow(new_row)
        self.load_image(self.ui.file_list.currentItem())

    def _delete_current_image(self):
        """Delete the current image file and its label, with double confirmation."""
        if not self.current_img_name or not self.image_dir:
            return
        fname = self.current_img_name
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

        current_row = self.ui.file_list.currentRow()
        img_path = os.path.join(self.image_dir, fname)
        txt_path = self._txt_path_for(fname)
        try:
            if os.path.exists(img_path):
                os.remove(img_path)
            if os.path.exists(txt_path):
                os.remove(txt_path)
        except OSError as e:
            QMessageBox.critical(self, "Delete Failed", str(e))
            return

        self.current_img_name = ""
        self.ui.canvas.shapes.clear()
        self.ui.canvas.shape_classes.clear()
        self.ui.file_list.takeItem(current_row)

        if self.ui.file_list.count() > 0:
            new_row = min(current_row, self.ui.file_list.count() - 1)
            self.ui.file_list.setCurrentRow(new_row)
            self.load_image(self.ui.file_list.currentItem())
        else:
            self.ui.canvas.set_image(QPixmap())
            self.ui.shape_list.clear()

    def _clean_orphaned_labels(self):
        """Delete .txt label files in save_dir that have no matching image in image_dir."""
        if not self.save_dir or not os.path.isdir(self.save_dir):
            QMessageBox.warning(self, "No Label Directory",
                                "Please select a label directory first.")
            return
        if not self.image_dir or not os.path.isdir(self.image_dir):
            QMessageBox.warning(self, "No Image Directory",
                                "Please select an image directory first.")
            return

        img_extensions = {'.jpg', '.jpeg', '.png', '.bmp', '.webp'}
        existing_stems = {
            os.path.splitext(f)[0]
            for f in os.listdir(self.image_dir)
            if os.path.splitext(f)[1].lower() in img_extensions
        }

        orphans = [
            f for f in os.listdir(self.save_dir)
            if f.lower().endswith('.txt') and f != 'classes.txt'
            and os.path.splitext(f)[0] not in existing_stems
        ]

        if not orphans:
            QMessageBox.information(self, "Clean Orphaned Labels",
                                    "No orphaned label files found.")
            return

        reply = QMessageBox.question(
            self, "Clean Orphaned Labels",
            f"Found {len(orphans)} label file(s) with no matching image:\n\n"
            + "\n".join(orphans[:20])
            + ("\n…" if len(orphans) > 20 else "")
            + "\n\nPermanently delete these files?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        deleted, failed = 0, []
        for fname in orphans:
            try:
                os.remove(os.path.join(self.save_dir, fname))
                deleted += 1
            except OSError as e:
                failed.append(f"{fname}: {e}")

        msg = f"Deleted {deleted} orphaned label file(s)."
        if failed:
            msg += "\n\nFailed to delete:\n" + "\n".join(failed)
            QMessageBox.warning(self, "Clean Orphaned Labels", msg)
        else:
            self.statusBar().showMessage(msg, 4000)

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
            self.ui.canvas.save_snapshot()
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

    def _reload_shapes(self):
        """Reload YOLO labels for the current image into canvas and shape list."""
        if not self.current_img_name or not self.ui.canvas.original_size:
            return
        txt_path = self._txt_path_for(self.current_img_name)
        shapes, shape_classes = io_labels.load_yolo(txt_path, self.annotation_mode)
        self.ui.canvas.shapes        = shapes
        self.ui.canvas.shape_classes = shape_classes
        self.ui.canvas.update()
        self._refresh_shape_list()

    # ── Check mode ───────────────────────────────────────────────────────────

    def _require_image_dir(self) -> bool:
        """Return True if image_dir is set and still exists; show a warning otherwise."""
        if not self.image_dir or not os.path.isdir(self.image_dir):
            self.image_dir = ""
            self.ui.lbl_img_path.setText("(not set)")
            QMessageBox.warning(self, "Image Directory Not Found",
                                "The image directory no longer exists.\n"
                                "Please select a new image directory.")
            return False
        return True

    def _on_nav(self, mode: str):
        """Switch between label / check / video / model_check views."""
        if mode != "video":
            self._video.pause()
        if mode != "model_check":
            self._mc.pause()
        if mode == "check":
            if not self._require_image_dir():
                self.ui.btn_nav_label.setChecked(True)
                return
            self._check.enter()
        elif mode == "label":
            self._check.exit()
            self.ui.center_stack.setCurrentIndex(0)
            self.ui.bottom_left_stack.setCurrentIndex(0)
        elif mode == "video":
            self._check.exit()
            self.ui.center_stack.setCurrentIndex(2)
            self.ui.bottom_left_stack.setCurrentIndex(2)
            self.ui.btn_extract_frames.setEnabled(self._video._cap is not None)
        else:  # model_check
            self._check.exit()
            self.ui.center_stack.setCurrentIndex(3)
            self.ui.bottom_left_stack.setCurrentIndex(3)
        self.ui.toolbar_widget.setVisible(mode == "label")
        self.ui.right_widget.setVisible(mode == "label")
        self.ui.btn_auto_annotate.setVisible(mode == "label")
        self.ui.btn_export_dataset.setVisible(mode in ("label", "check"))

    def _apply_mode_tool_state(self):
        """Enable only the draw tool that matches the current annotation mode."""
        det = (self.annotation_mode == 'detection')
        self.ui.btn_draw_mode.setEnabled(det)
        self.ui.btn_polygon_mode.setEnabled(not det)
        # Turn off whichever tool is now disabled
        canvas = self.ui.canvas
        if det and canvas.polygon_mode:
            apply_draw_mode(canvas, self.ui.btn_polygon_mode, False, polygon=True)
        if not det and canvas.draw_mode:
            apply_draw_mode(canvas, self.ui.btn_draw_mode, False)

    def _on_annotation_mode_changed(self, mode: str):
        if mode == self.annotation_mode:
            return
        QMessageBox.information(
            self, "Label Folder Warning",
            "Detection and Segmentation labels share the same filename (.txt).\n\n"
            "If your Label Folder is the same for both modes, saving will overwrite\n"
            "the other mode's labels.\n\n"
            "Recommended: use separate label folders for Detection and Segmentation."
        )
        self.annotation_mode = mode
        self._apply_mode_tool_state()
        self._save_session()
        if self.ui.btn_nav_check.isChecked():
            self._check.enter()   # rebuild check view with new mode
        else:
            self._reload_shapes()

    def _convert_to_seg(self):
        if not self.save_dir:
            QMessageBox.warning(self, "No Label Directory",
                                "Please select a label directory first.")
            return
        reply = QMessageBox.question(
            self, "Convert Detection → Segmentation",
            "This will convert all bbox labels in the label folder to 4-point polygon format.\n"
            "The operation is lossless (rectangles become 4-vertex polygons).\n\n"
            "Existing .txt files will be overwritten. Continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        self._autosave_yolo()
        try:
            count = io_labels.convert_det_to_seg(self.save_dir)
        except ValueError as e:
            QMessageBox.warning(self, "Mixed Labels Detected", str(e))
            return
        QMessageBox.information(self, "Convert Complete",
                                f"Converted {count} bounding box(es) to polygon format.")
        self._reload_shapes()

    def _convert_to_det(self):
        if not self.save_dir:
            QMessageBox.warning(self, "No Label Directory",
                                "Please select a label directory first.")
            return
        reply = QMessageBox.warning(
            self, "Convert Segmentation → Detection (Lossy)",
            "This will convert all polygon labels to bounding boxes (bounding rect).\n\n"
            "⚠️  This is LOSSY — polygon shape detail will be lost permanently.\n"
            "Existing .txt files will be overwritten. Are you sure?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        reply2 = QMessageBox.warning(
            self, "Confirm Lossy Conversion",
            "Confirm: permanently replace all polygon labels with bounding boxes?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if reply2 != QMessageBox.StandardButton.Yes:
            return
        self._autosave_yolo()
        try:
            count = io_labels.convert_seg_to_det(self.save_dir)
        except ValueError as e:
            QMessageBox.warning(self, "Mixed Labels Detected", str(e))
            return
        QMessageBox.information(self, "Convert Complete",
                                f"Converted {count} polygon(s) to bounding box format.")
        self._reload_shapes()

    # ── Auto annotate ─────────────────────────────────────────────────────────

    def auto_annotate(self):
        if not self._require_image_dir():
            return
        if not self.save_dir:
            QMessageBox.warning(self, "No Label Directory",
                                "Please select a label directory first.")
            return

        dlg = AutoAnnotateDialog(self, annotation_mode=self.annotation_mode,
                                 image_dir=self.image_dir)
        if dlg.exec() != AutoAnnotateDialog.DialogCode.Accepted:
            return

        model_path = dlg.model_path
        conf = dlg.conf()
        annotate_mode = dlg.annotation_mode()

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
        all_images = sorted([f for f in os.listdir(self.image_dir)
                             if os.path.splitext(f)[1].lower() in img_exts])
        if not all_images:
            QMessageBox.information(self, "No Images",
                                    "No images found in the image directory.")
            return

        self._autosave_yolo()

        total      = len(all_images)
        batch_size = config.load().get("annotate_batch_size", 400)
        batches    = [all_images[i:i+batch_size] for i in range(0, total, batch_size)]

        # Progress dialog
        progress = QProgressDialog("Loading model…", "Cancel", 0, total, self)
        progress.setWindowTitle("Auto Annotate")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumWidth(400)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        progress.setValue(0)
        progress.show()

        import time as _time
        _start = _time.time()
        _state = [0, total, "Loading model…"]   # [cur, total, fname] — written by QThread
        _all_errors = []
        _batch_idx  = [0]
        _cancelled  = [False]

        poll_timer = QTimer(self)
        poll_timer.setInterval(500)
        def _tick():
            cur, tot, fname = _state
            secs = int(_time.time() - _start)
            m, s = divmod(secs, 60)
            progress.setValue(cur)
            progress.setLabelText(
                f"[Batch {_batch_idx[0]}/{len(batches)}] [{cur}/{tot}] {fname}  ({m:02d}:{s:02d})")

            # Detect batch completion entirely in the main thread — no cross-thread signals.
            # PySide6 does not honour QueuedConnection for plain Python callables (no
            # QObject affinity), so any slot connected to worker.finished would run in
            # the QThread via DirectConnection, causing the timer/parent warnings.
            t = self._annotate_thread
            if t is not None and not t.isRunning():
                self._annotate_thread = None
                w = self._annotate_worker
                if w is not None:
                    _all_errors.extend(getattr(w, '_errors', []))
                _batch_idx[0] += 1
                if not _cancelled[0] and _batch_idx[0] < len(batches):
                    _start_batch()
                else:
                    _finish()

        poll_timer.timeout.connect(_tick)
        poll_timer.start()

        def _start_batch():
            idx = _batch_idx[0]
            offset = idx * batch_size
            worker = AnnotateWorker(
                model_path, conf,
                batches[idx], self.image_dir, self.save_dir,
                offset=offset, total=total,
                write_classes=(idx == 0),
                annotation_mode=annotate_mode,
            )
            worker.set_state(_state)
            thread = QThread(self)
            worker.moveToThread(thread)

            def _cancel_batch():
                worker._cancel = True
                _cancelled[0]  = True
            progress.canceled.connect(_cancel_batch)

            # No finished signal connection — _tick() polls isRunning() instead.
            thread.started.connect(worker.run)
            thread.start()
            self._annotate_thread = thread
            self._annotate_worker = worker

        def _finish():
            poll_timer.stop()
            _state[0] = total
            _tick()
            try:
                progress.canceled.disconnect()
            except RuntimeError:
                pass
            progress.setLabelText(f"Done — {total} image(s) annotated.")
            progress.setCancelButtonText("Finish")

            def on_finish_clicked():
                progress.close()
                try:
                    self._load_classes()
                    if self.current_img_name:
                        txt_path = self._txt_path_for(self.current_img_name)
                        shapes, shape_classes = io_labels.load_yolo(txt_path, self.annotation_mode)
                        self.ui.canvas.shapes        = shapes
                        self.ui.canvas.shape_classes = shape_classes
                        self.ui.canvas.update()
                        self._refresh_shape_list()
                except Exception as e:
                    QMessageBox.critical(self, "Post-process Error", str(e))
                    return
                if _all_errors:
                    QMessageBox.warning(self, "Auto Annotate — Some Errors",
                                        f"Completed with {len(_all_errors)} error(s):\n\n" +
                                        "\n".join(_all_errors[:10]))

            progress.canceled.connect(on_finish_clicked)

        _start_batch()

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
