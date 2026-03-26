"""LabelModeController — all Image Label logic (canvas, shapes, classes, I/O)."""

import os

from PySide6.QtWidgets import (QListWidget, QMessageBox, QProgressDialog,
                               QFileDialog)
from PySide6.QtGui import QPixmap, QBrush
from PySide6.QtCore import Qt, QTimer, QThread

from app import config, io_labels
from app.ui_layout import CLASS_COLORS
from app.export_dialog import ExportDialog
from app.auto_annotate_dialog import AutoAnnotateDialog, AnnotateWorker
from app.utils import format_shape_label, apply_draw_mode


class LabelModeController:
    def __init__(self, main_window):
        self._mw = main_window
        self._annotate_thread = None
        self._annotate_worker = None

    # ── Convenience ───────────────────────────────────────────────────────────

    @property
    def _ui(self):
        return self._mw.ui

    @property
    def _image_dir(self) -> str:
        return self._mw.image_dir

    @property
    def _save_dir(self) -> str:
        return self._mw.save_dir

    @property
    def _annotation_mode(self) -> str:
        return self._mw.annotation_mode

    # ── Image loading ─────────────────────────────────────────────────────────

    def load_image(self, item):
        """Switch image: autosave current, load new image, restore existing labels."""
        if self._mw.current_img_name and self._ui.canvas.original_size:
            unassigned_count = sum(1 for c in self._ui.canvas.shape_classes if c < 0)
            if unassigned_count:
                box = QMessageBox(self._mw)
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
                    for i in range(self._ui.file_list.count()):
                        if self._ui.file_list.item(i).text() == self._mw.current_img_name:
                            self._ui.file_list.setCurrentRow(i)
                            break
                    return

        self._autosave_yolo()

        self._mw.current_img_name = item.text()
        img_path = os.path.join(self._image_dir, self._mw.current_img_name)
        self._ui.canvas.set_image(QPixmap(img_path))

        txt_path = self.txt_path_for(self._mw.current_img_name)
        shapes, shape_classes = io_labels.load_yolo(txt_path, self._annotation_mode)
        self._ui.canvas.shapes        = shapes
        self._ui.canvas.shape_classes = shape_classes
        self._ui.canvas.update()
        self._refresh_shape_list()

    def txt_path_for(self, img_name: str) -> str:
        base = os.path.splitext(img_name)[0] + ".txt"
        return os.path.join(self._save_dir, base)

    def reload_shapes(self):
        """Reload YOLO labels for the current image into canvas and shape list."""
        if not self._mw.current_img_name or not self._ui.canvas.original_size:
            return
        txt_path = self.txt_path_for(self._mw.current_img_name)
        shapes, shape_classes = io_labels.load_yolo(txt_path, self._annotation_mode)
        self._ui.canvas.shapes        = shapes
        self._ui.canvas.shape_classes = shape_classes
        self._ui.canvas.update()
        self._refresh_shape_list()

    def switch_image(self, delta: int):
        count = self._ui.file_list.count()
        if count == 0:
            return
        current = self._ui.file_list.currentRow()
        new_row = max(0, min(max(current, 0) + delta, count - 1))
        self._ui.file_list.setCurrentRow(new_row)
        self.load_image(self._ui.file_list.currentItem())

    def delete_current_image(self):
        if not self._mw.current_img_name or not self._image_dir:
            return
        fname = self._mw.current_img_name
        reply = QMessageBox.question(
            self._mw, "Delete Image?",
            f"Delete image and label for:\n{fname}\n\nThis cannot be undone.",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        reply2 = QMessageBox.warning(
            self._mw, "Confirm Permanent Delete",
            f"Permanently delete  {fname}  and its label file?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if reply2 != QMessageBox.StandardButton.Yes:
            return

        current_row = self._ui.file_list.currentRow()
        img_path = os.path.join(self._image_dir, fname)
        txt_path = self.txt_path_for(fname)
        try:
            if os.path.exists(img_path):
                os.remove(img_path)
            if os.path.exists(txt_path):
                os.remove(txt_path)
        except OSError as e:
            QMessageBox.critical(self._mw, "Delete Failed", str(e))
            return

        self._mw.current_img_name = ""
        self._ui.canvas.shapes.clear()
        self._ui.canvas.shape_classes.clear()
        self._ui.file_list.takeItem(current_row)

        if self._ui.file_list.count() > 0:
            new_row = min(current_row, self._ui.file_list.count() - 1)
            self._ui.file_list.setCurrentRow(new_row)
            self.load_image(self._ui.file_list.currentItem())
        else:
            self._ui.canvas.set_image(QPixmap())
            self._ui.shape_list.clear()

    def clean_orphaned_labels(self):
        if not self._save_dir or not os.path.isdir(self._save_dir):
            QMessageBox.warning(self._mw, "No Label Directory",
                                "Please select a label directory first.")
            return
        if not self._image_dir or not os.path.isdir(self._image_dir):
            QMessageBox.warning(self._mw, "No Image Directory",
                                "Please select an image directory first.")
            return

        img_extensions = {'.jpg', '.jpeg', '.png', '.bmp', '.webp'}
        existing_stems = {
            os.path.splitext(f)[0]
            for f in os.listdir(self._image_dir)
            if os.path.splitext(f)[1].lower() in img_extensions
        }
        orphans = [
            f for f in os.listdir(self._save_dir)
            if f.lower().endswith('.txt') and f != 'classes.txt'
            and os.path.splitext(f)[0] not in existing_stems
        ]
        if not orphans:
            QMessageBox.information(self._mw, "Clean Orphaned Labels",
                                    "No orphaned label files found.")
            return

        reply = QMessageBox.question(
            self._mw, "Clean Orphaned Labels",
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
                os.remove(os.path.join(self._save_dir, fname))
                deleted += 1
            except OSError as e:
                failed.append(f"{fname}: {e}")

        msg = f"Deleted {deleted} orphaned label file(s)."
        if failed:
            msg += "\n\nFailed to delete:\n" + "\n".join(failed)
            QMessageBox.warning(self._mw, "Clean Orphaned Labels", msg)
        else:
            self._mw.statusBar().showMessage(msg, 4000)

    # ── YOLO auto-save ────────────────────────────────────────────────────────

    def _autosave_yolo(self):
        if not self._mw.current_img_name or not self._save_dir:
            return
        canvas = self._ui.canvas
        if not canvas.original_size:
            return
        txt_path = self.txt_path_for(self._mw.current_img_name)
        if not canvas.shapes:
            if os.path.exists(txt_path) and not self._txt_has_other_mode_labels(txt_path):
                os.remove(txt_path)
            return
        io_labels.save_yolo(txt_path, canvas.shapes, canvas.shape_classes)
        self._mw.statusBar().showMessage(
            f"Saved: {os.path.basename(txt_path)}  ({len(canvas.shapes)} shape(s))", 2000)

    def _txt_has_other_mode_labels(self, txt_path: str) -> bool:
        try:
            with open(txt_path, 'r', encoding='utf-8') as f:
                for line in f:
                    parts = line.strip().split()
                    if not parts:
                        continue
                    if self._annotation_mode == 'detection':
                        if len(parts) >= 7 and len(parts) % 2 == 1:
                            return True
                    else:
                        if len(parts) == 5:
                            return True
        except OSError:
            pass
        return False

    # ── Canvas event handlers ─────────────────────────────────────────────────

    def on_rectangle_drawn(self):
        cls_idx = self._current_class_idx()
        last = len(self._ui.canvas.shapes) - 1
        self._ui.canvas.shape_classes[last] = cls_idx
        self._ui.canvas.update()
        self._ui.shape_list.addItem(self._shape_label(last))
        self._autosave_yolo()

    def on_polygon_drawn(self, index: int):
        cls_idx = self._current_class_idx()
        self._ui.canvas.shape_classes[index] = cls_idx
        self._ui.canvas.update()
        self._ui.shape_list.addItem(self._shape_label(index))
        self._autosave_yolo()

    def on_shape_modified(self, index: int):
        self.update_shape_in_list(index)
        self._autosave_yolo()

    def update_shape_in_list(self, index: int):
        item = self._ui.shape_list.item(index)
        if item:
            item.setText(self._shape_label(index))

    def undo(self):
        if self._ui.canvas.undo():
            self._refresh_shape_list()
            self._autosave_yolo()

    def redo(self):
        if self._ui.canvas.redo():
            self._refresh_shape_list()
            self._autosave_yolo()

    def delete_shape(self, row: int):
        self._ui.canvas.save_snapshot()
        self._ui.shape_list.takeItem(row)
        self._ui.canvas.shapes.pop(row)
        self._ui.canvas.shape_classes.pop(row)
        self._ui.canvas.selected_index = -1
        self._ui.canvas.update()
        self._autosave_yolo()

    def delete_selected_shape(self):
        sel = self._ui.canvas.selected_index
        if sel >= 0:
            self.delete_shape(sel)

    def shape_list_key_press(self, event):
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            row = self._ui.shape_list.currentRow()
            if row >= 0:
                self.delete_shape(row)
        else:
            super(QListWidget, self._ui.shape_list).keyPressEvent(event)

    # ── Class management ──────────────────────────────────────────────────────

    def add_class(self):
        name = self._ui.class_input.text().strip()
        if not name:
            return
        self._ui.class_list.addItem(name)
        self._ui.class_input.clear()
        self._ui.class_list.setCurrentRow(self._ui.class_list.count() - 1)
        self._refresh_class_colors()
        self._save_classes()

    def delete_class(self):
        row = self._ui.class_list.currentRow()
        if row < 0:
            return
        self._ui.class_list.takeItem(row)
        for i, cls_idx in enumerate(self._ui.canvas.shape_classes):
            if cls_idx == row:
                self._ui.canvas.shape_classes[i] = -1
            elif cls_idx > row:
                self._ui.canvas.shape_classes[i] -= 1
        self._ui.canvas.update()
        self._refresh_shape_list()
        self._save_classes()

    def on_class_selected(self, item):
        cls_idx = self._ui.class_list.row(item)
        sel = self._ui.canvas.selected_index
        if sel >= 0:
            self._ui.canvas.save_snapshot()
            self._ui.canvas.shape_classes[sel] = cls_idx
            self._ui.canvas.update()
            self._refresh_shape_list()
            self._autosave_yolo()

    def load_classes(self):
        if not self._save_dir:
            return
        path = os.path.join(self._save_dir, "classes.txt")
        if not os.path.exists(path):
            return
        with open(path, "r", encoding="utf-8") as f:
            names = [line.strip() for line in f if line.strip()]
        self._ui.class_list.clear()
        for name in names:
            self._ui.class_list.addItem(name)
        self._refresh_class_colors()

    def _save_classes(self):
        if not self._save_dir:
            return
        names = [self._ui.class_list.item(i).text()
                 for i in range(self._ui.class_list.count())]
        with open(os.path.join(self._save_dir, "classes.txt"), "w", encoding="utf-8") as f:
            f.write("\n".join(names))

    def _refresh_class_colors(self):
        for i in range(self._ui.class_list.count()):
            color = CLASS_COLORS[i % len(CLASS_COLORS)]
            self._ui.class_list.item(i).setForeground(QBrush(color))
        self._ui.canvas.class_names = [
            self._ui.class_list.item(i).text()
            for i in range(self._ui.class_list.count())
        ]
        self._ui.canvas.update()

    # ── Draw mode / annotation mode ───────────────────────────────────────────

    def toggle_draw_mode(self):
        canvas = self._ui.canvas
        apply_draw_mode(canvas, self._ui.btn_draw_mode, not canvas.draw_mode)
        if canvas.draw_mode:
            apply_draw_mode(canvas, self._ui.btn_polygon_mode, False, polygon=True)

    def toggle_polygon_mode(self):
        canvas = self._ui.canvas
        apply_draw_mode(canvas, self._ui.btn_polygon_mode,
                        not canvas.polygon_mode, polygon=True)
        if canvas.polygon_mode:
            apply_draw_mode(canvas, self._ui.btn_draw_mode, False)

    def apply_mode_tool_state(self):
        det = (self._annotation_mode == 'detection')
        self._ui.btn_draw_mode.setEnabled(det)
        self._ui.btn_polygon_mode.setEnabled(not det)
        canvas = self._ui.canvas
        if det and canvas.polygon_mode:
            apply_draw_mode(canvas, self._ui.btn_polygon_mode, False, polygon=True)
        if not det and canvas.draw_mode:
            apply_draw_mode(canvas, self._ui.btn_draw_mode, False)

    def on_annotation_mode_changed(self, mode: str):
        if mode == self._annotation_mode:
            return
        QMessageBox.information(
            self._mw, "Label Folder Warning",
            "Detection and Segmentation labels share the same filename (.txt).\n\n"
            "If your Label Folder is the same for both modes, saving will overwrite\n"
            "the other mode's labels.\n\n"
            "Recommended: use separate label folders for Detection and Segmentation."
        )
        self._mw.annotation_mode = mode
        self.apply_mode_tool_state()
        self._mw._save_session()
        if self._ui.btn_nav_check.isChecked():
            self._mw._check.enter()
        else:
            self.reload_shapes()

    # ── Label conversion ──────────────────────────────────────────────────────

    def convert_to_seg(self):
        if not self._save_dir:
            QMessageBox.warning(self._mw, "No Label Directory",
                                "Please select a label directory first.")
            return
        reply = QMessageBox.question(
            self._mw, "Convert Detection → Segmentation",
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
            count = io_labels.convert_det_to_seg(self._save_dir)
        except ValueError as e:
            QMessageBox.warning(self._mw, "Mixed Labels Detected", str(e))
            return
        QMessageBox.information(self._mw, "Convert Complete",
                                f"Converted {count} bounding box(es) to polygon format.")
        self.reload_shapes()

    def convert_to_det(self):
        if not self._save_dir:
            QMessageBox.warning(self._mw, "No Label Directory",
                                "Please select a label directory first.")
            return
        reply = QMessageBox.warning(
            self._mw, "Convert Segmentation → Detection (Lossy)",
            "This will convert all polygon labels to bounding boxes (bounding rect).\n\n"
            "⚠️  This is LOSSY — polygon shape detail will be lost permanently.\n"
            "Existing .txt files will be overwritten. Are you sure?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return
        reply2 = QMessageBox.warning(
            self._mw, "Confirm Lossy Conversion",
            "Confirm: permanently replace all polygon labels with bounding boxes?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if reply2 != QMessageBox.StandardButton.Yes:
            return
        self._autosave_yolo()
        try:
            count = io_labels.convert_seg_to_det(self._save_dir)
        except ValueError as e:
            QMessageBox.warning(self._mw, "Mixed Labels Detected", str(e))
            return
        QMessageBox.information(self._mw, "Convert Complete",
                                f"Converted {count} polygon(s) to bounding box format.")
        self.reload_shapes()

    # ── Auto annotate ─────────────────────────────────────────────────────────

    def auto_annotate(self):
        if not self.require_image_dir():
            return
        if not self._save_dir:
            QMessageBox.warning(self._mw, "No Label Directory",
                                "Please select a label directory first.")
            return

        dlg = AutoAnnotateDialog(self._mw, annotation_mode=self._annotation_mode,
                                 image_dir=self._image_dir)
        if dlg.exec() != AutoAnnotateDialog.DialogCode.Accepted:
            return

        model_path   = dlg.model_path
        conf         = dlg.conf()
        annotate_mode = dlg.annotation_mode()

        reply = QMessageBox.warning(
            self._mw, "Overwrite Labels?",
            "This will overwrite ALL existing label files (.txt) in the label directory.\n\n"
            "Are you sure you want to continue?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.Cancel,
            QMessageBox.StandardButton.Cancel,
        )
        if reply != QMessageBox.StandardButton.Yes:
            return

        try:
            import ultralytics  # noqa: F401
        except ImportError:
            QMessageBox.critical(self._mw, "Ultralytics Not Installed",
                                 "Please run:  pip install ultralytics")
            return

        img_exts = {'.jpg', '.jpeg', '.png', '.bmp', '.webp'}
        all_images = sorted([f for f in os.listdir(self._image_dir)
                             if os.path.splitext(f)[1].lower() in img_exts])
        if not all_images:
            QMessageBox.information(self._mw, "No Images",
                                    "No images found in the image directory.")
            return

        self._autosave_yolo()

        total      = len(all_images)
        batch_size = config.load().get("annotate_batch_size", 400)
        batches    = [all_images[i:i+batch_size] for i in range(0, total, batch_size)]

        progress = QProgressDialog("Loading model…", "Cancel", 0, total, self._mw)
        progress.setWindowTitle("Auto Annotate")
        progress.setWindowModality(Qt.WindowModality.WindowModal)
        progress.setMinimumWidth(400)
        progress.setAutoClose(False)
        progress.setAutoReset(False)
        progress.setValue(0)
        progress.show()

        import time as _time
        _start  = _time.time()
        _state  = [0, total, "Loading model…"]
        _all_errors = []
        _batch_idx  = [0]
        _cancelled  = [False]

        poll_timer = QTimer(self._mw)
        poll_timer.setInterval(500)

        def _tick():
            cur, tot, fname = _state
            secs = int(_time.time() - _start)
            m, s = divmod(secs, 60)
            progress.setValue(cur)
            progress.setLabelText(
                f"[Batch {_batch_idx[0]}/{len(batches)}] [{cur}/{tot}] {fname}  ({m:02d}:{s:02d})")
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
            idx    = _batch_idx[0]
            offset = idx * batch_size
            worker = AnnotateWorker(
                model_path, conf,
                batches[idx], self._image_dir, self._save_dir,
                offset=offset, total=total,
                write_classes=(idx == 0),
                annotation_mode=annotate_mode,
            )
            worker.set_state(_state)
            thread = QThread(self._mw)
            worker.moveToThread(thread)

            def _cancel_batch():
                worker._cancel = True
                _cancelled[0]  = True
            progress.canceled.connect(_cancel_batch)

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
                    self.load_classes()
                    if self._mw.current_img_name:
                        txt_path = self.txt_path_for(self._mw.current_img_name)
                        shapes, shape_classes = io_labels.load_yolo(
                            txt_path, self._annotation_mode)
                        self._ui.canvas.shapes        = shapes
                        self._ui.canvas.shape_classes = shape_classes
                        self._ui.canvas.update()
                        self._refresh_shape_list()
                except Exception as e:
                    QMessageBox.critical(self._mw, "Post-process Error", str(e))
                    return
                if _all_errors:
                    QMessageBox.warning(self._mw, "Auto Annotate — Some Errors",
                                        f"Completed with {len(_all_errors)} error(s):\n\n"
                                        + "\n".join(_all_errors[:10]))

            progress.canceled.connect(on_finish_clicked)

        _start_batch()

    # ── Export ────────────────────────────────────────────────────────────────

    def export_dataset(self):
        if not self._image_dir:
            QMessageBox.warning(self._mw, "No Image Directory",
                                "Please select an image directory before exporting.")
            return
        self._autosave_yolo()
        class_names = [self._ui.class_list.item(i).text()
                       for i in range(self._ui.class_list.count())]
        dlg = ExportDialog(
            self._mw,
            image_dir=self._image_dir,
            label_dir=self._save_dir or self._image_dir,
            class_names=class_names,
        )
        dlg.exec()

    # ── Guards ────────────────────────────────────────────────────────────────

    def require_image_dir(self) -> bool:
        if not self._image_dir or not os.path.isdir(self._image_dir):
            self._mw.image_dir = ""
            self._ui.lbl_img_path.setText("(not set)")
            QMessageBox.warning(self._mw, "Image Directory Not Found",
                                "The image directory no longer exists.\n"
                                "Please select a new image directory.")
            return False
        return True

    # ── Private helpers ───────────────────────────────────────────────────────

    def _current_class_idx(self) -> int:
        return self._ui.class_list.currentRow()

    def _shape_label(self, shape_idx: int) -> str:
        canvas = self._ui.canvas
        class_names = [self._ui.class_list.item(i).text()
                       for i in range(self._ui.class_list.count())]
        return format_shape_label(
            canvas.shapes[shape_idx],
            canvas.shape_classes[shape_idx],
            class_names,
            canvas.original_size,
        )

    def _refresh_shape_list(self):
        self._ui.shape_list.clear()
        for i in range(len(self._ui.canvas.shapes)):
            self._ui.shape_list.addItem(self._shape_label(i))
