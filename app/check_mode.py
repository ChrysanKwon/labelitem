"""CheckModeController — manages all Check Mode logic for SimpleLabeler.

Keeps check-mode responsibilities out of main.py.
The controller holds a reference to the main window and accesses its
image_dir / save_dir / ui attributes through well-defined properties.
"""

import os

from PySide6.QtCore import Qt, QSize
from PySide6.QtGui import QPixmap, QPainter, QColor, QFont, QIcon
from PySide6.QtWidgets import QListWidgetItem

from app.check_edit_dialog import CheckEditDialog


class CheckModeController:
    def __init__(self, main_window):
        self._mw = main_window

    # ── Convenience accessors ─────────────────────────────────────────────

    @property
    def _ui(self):
        return self._mw.ui

    @property
    def _image_dir(self) -> str:
        return self._mw.image_dir

    @property
    def _save_dir(self) -> str:
        return self._mw.save_dir

    def _txt_path_for(self, fname: str) -> str:
        return self._mw._txt_path_for(fname)

    # ── Public entry points (called from main.py) ─────────────────────────

    def enter(self):
        """Switch UI to Label Review and populate the class list."""
        from PySide6.QtWidgets import QApplication
        self._mw.statusBar().showMessage("Loading images, please wait…")
        QApplication.processEvents()
        self._ui.center_stack.setCurrentIndex(1)
        self._ui.bottom_left_stack.setCurrentIndex(1)

        counts = self._count_labels_by_class()
        self._ui.check_class_list.clear()
        for i in range(self._ui.class_list.count()):
            src = self._ui.class_list.item(i)
            n = counts.get(i, 0)
            self._ui.check_class_list.addItem(f"{src.text()}  ({n})")
            self._ui.check_class_list.item(i).setForeground(src.foreground())

        if self._ui.check_class_list.count() > 0:
            self._ui.check_class_list.setCurrentRow(0)
            self.refresh_view(0)
        self._mw.statusBar().clearMessage()

    def exit(self):
        """Clear check view (nav column controls actual stack switching)."""
        self._ui.check_view.clear()

    def on_class_selected(self, item):
        self.refresh_view(self._ui.check_class_list.row(item))

    def on_item_double_clicked(self, item):
        """Open CheckEditDialog; refresh only the edited image on save."""
        fname = item.data(Qt.ItemDataRole.UserRole)
        if not fname:
            return
        image_path  = os.path.join(self._image_dir, fname)
        txt_path    = self._txt_path_for(fname)
        class_names = [self._ui.class_list.item(i).text()
                       for i in range(self._ui.class_list.count())]
        box_coords  = item.data(Qt.ItemDataRole.UserRole + 1)
        dlg = CheckEditDialog(self._mw, image_path, txt_path,
                              class_names, select_box=box_coords,
                              annotation_mode=self._annotation_mode)
        dlg.exec()

        if dlg.delete_requested:
            self._remove_all_items_for(fname)
            self._refresh_class_counts()
        elif dlg.result() == CheckEditDialog.DialogCode.Accepted:
            cls_idx = self._ui.check_class_list.currentRow()
            self._update_view_for_image(fname, cls_idx)

    def refresh_view(self, cls_idx: int):
        """Rebuild check_view from scratch for the given class."""
        self._ui.check_view.clear()
        if not self._image_dir or not self._save_dir:
            return
        img_exts = {'.jpg', '.jpeg', '.png'}
        for fname in sorted(os.listdir(self._image_dir)):
            if os.path.splitext(fname)[1].lower() not in img_exts:
                continue
            for it in self._items_for(fname, cls_idx):
                self._ui.check_view.addItem(it)

    # ── Private helpers ───────────────────────────────────────────────────

    @property
    def _annotation_mode(self) -> str:
        return getattr(self._mw, 'annotation_mode', 'detection')

    def _count_labels_by_class(self) -> dict:
        """Return {class_idx: count} across all label files in save_dir, filtered by annotation mode."""
        counts = {}
        if not self._save_dir or not os.path.isdir(self._save_dir):
            return counts
        mode = self._annotation_mode
        for fname in os.listdir(self._save_dir):
            if not fname.endswith('.txt') or fname == 'classes.txt':
                continue
            try:
                with open(os.path.join(self._save_dir, fname),
                          'r', encoding='utf-8') as f:
                    for line in f:
                        parts = line.strip().split()
                        if mode == 'detection' and len(parts) == 5:
                            counts[int(parts[0])] = counts.get(int(parts[0]), 0) + 1
                        elif mode == 'segmentation' and len(parts) >= 7 and len(parts) % 2 == 1:
                            counts[int(parts[0])] = counts.get(int(parts[0]), 0) + 1
            except (ValueError, OSError):
                pass
        return counts

    def _make_thumb(self, crop: QPixmap, fname: str) -> QPixmap:
        """Composite crop + filename into a fixed 176×130 pixmap."""
        THUMB_W, THUMB_H, LABEL_H = 176, 130, 22
        thumb = QPixmap(THUMB_W, THUMB_H)
        thumb.fill(QColor(30, 30, 30))
        with QPainter(thumb) as p:
            img_area_h = THUMB_H - LABEL_H
            ox = (THUMB_W - crop.width()) // 2
            oy = (img_area_h - crop.height()) // 2
            p.drawPixmap(ox, oy, crop)
            p.fillRect(0, img_area_h, THUMB_W, LABEL_H, QColor(0, 0, 0, 180))
            short = fname if len(fname) <= 22 else fname[:20] + "…"
            p.setPen(QColor(220, 220, 220))
            font = QFont()
            font.setPointSize(8)
            p.setFont(font)
            p.drawText(4, img_area_h, THUMB_W - 8, LABEL_H,
                       Qt.AlignmentFlag.AlignVCenter | Qt.AlignmentFlag.AlignLeft,
                       short)
        return thumb

    def _items_for(self, fname: str, cls_idx: int) -> list:
        """Build QListWidgetItems for all shapes of cls_idx in fname."""
        txt_path = self._txt_path_for(fname)
        if not os.path.exists(txt_path):
            return []
        pixmap = QPixmap(os.path.join(self._image_dir, fname))
        if pixmap.isNull():
            return []
        iw, ih = pixmap.width(), pixmap.height()
        mode = self._annotation_mode
        items = []
        with open(txt_path, 'r', encoding='utf-8') as f:
            for line in f:
                parts = line.strip().split()
                if not parts or int(parts[0]) != cls_idx:
                    continue

                if mode == 'detection' and len(parts) == 5:
                    cx, cy, nw, nh = (float(parts[1]), float(parts[2]),
                                       float(parts[3]), float(parts[4]))
                    x = max(0, int((cx - nw / 2) * iw))
                    y = max(0, int((cy - nh / 2) * ih))
                    w = min(int(nw * iw), iw - x)
                    h = min(int(nh * ih), ih - y)
                    if w < 1 or h < 1:
                        continue
                    crop = pixmap.copy(x, y, w, h).scaled(
                        QSize(160, 100),
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                    box_data = (cx, cy, nw, nh)

                elif mode == 'segmentation' and len(parts) >= 7 and len(parts) % 2 == 1:
                    xs = [float(parts[i]) for i in range(1, len(parts), 2)]
                    ys = [float(parts[i]) for i in range(2, len(parts), 2)]
                    x = max(0, int(min(xs) * iw))
                    y = max(0, int(min(ys) * ih))
                    w = min(int((max(xs) - min(xs)) * iw), iw - x)
                    h = min(int((max(ys) - min(ys)) * ih), ih - y)
                    if w < 1 or h < 1:
                        continue
                    crop = pixmap.copy(x, y, w, h).scaled(
                        QSize(160, 100),
                        Qt.AspectRatioMode.KeepAspectRatio,
                        Qt.TransformationMode.SmoothTransformation,
                    )
                    box_data = list(zip(xs, ys))  # polygon points list

                else:
                    continue

                thumb = self._make_thumb(crop, fname)
                item = QListWidgetItem(QIcon(thumb), "")
                item.setToolTip(fname)
                item.setData(Qt.ItemDataRole.UserRole, fname)
                item.setData(Qt.ItemDataRole.UserRole + 1, box_data)
                items.append(item)
        return items

    def _remove_all_items_for(self, fname: str):
        """Remove every check_view item that belongs to fname."""
        view = self._ui.check_view
        i = 0
        while i < view.count():
            if view.item(i).data(Qt.ItemDataRole.UserRole) == fname:
                view.takeItem(i)
            else:
                i += 1

    def _refresh_class_counts(self):
        """Update the label counts shown in check_class_list."""
        counts = self._count_labels_by_class()
        for i in range(self._ui.check_class_list.count()):
            src_item = self._ui.class_list.item(i)
            if src_item is None:
                continue
            n = counts.get(i, 0)
            self._ui.check_class_list.item(i).setText(f"{src_item.text()}  ({n})")

    def _update_view_for_image(self, fname: str, cls_idx: int):
        """Remove items for fname and re-insert updated ones in place."""
        view = self._ui.check_view
        insert_pos = None
        i = 0
        while i < view.count():
            if view.item(i).data(Qt.ItemDataRole.UserRole) == fname:
                if insert_pos is None:
                    insert_pos = i
                view.takeItem(i)
            else:
                i += 1
        if insert_pos is None:
            insert_pos = view.count()
            for i in range(view.count()):
                if view.item(i).data(Qt.ItemDataRole.UserRole) > fname:
                    insert_pos = i
                    break
        for j, item in enumerate(self._items_for(fname, cls_idx)):
            view.insertItem(insert_pos + j, item)
