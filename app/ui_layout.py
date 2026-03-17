from PySide6.QtWidgets import (QVBoxLayout, QHBoxLayout, QPushButton,
                               QListWidget, QLabel, QWidget, QLineEdit,
                               QStackedWidget, QSizePolicy)
from PySide6.QtGui import QPainter, QPen, QColor, QBrush, QCursor
from PySide6.QtCore import Qt, QRect, QPoint, QSize, Signal

HANDLE_SIZE = 8

TL, TC, TR, ML, MR, BL, BC, BR = range(8)

HANDLE_CURSORS = [
    Qt.CursorShape.SizeFDiagCursor,
    Qt.CursorShape.SizeVerCursor,
    Qt.CursorShape.SizeBDiagCursor,
    Qt.CursorShape.SizeHorCursor,
    Qt.CursorShape.SizeHorCursor,
    Qt.CursorShape.SizeBDiagCursor,
    Qt.CursorShape.SizeVerCursor,
    Qt.CursorShape.SizeFDiagCursor,
]

# Class colors by index (-1 = unassigned, shown in gray)
CLASS_COLORS = [
    QColor(0,   255,  0),   # 0 green
    QColor(255, 100,  0),   # 1 orange
    QColor(80,  120, 255),  # 2 blue
    QColor(255,  0,  255),  # 3 magenta
    QColor(0,   220, 220),  # 4 cyan
    QColor(255,  60,  60),  # 5 red
    QColor(180, 255,  0),   # 6 yellow-green
    QColor(255, 180,  0),   # 7 amber
]
UNASSIGNED_COLOR = QColor(160, 160, 160)
SELECTED_COLOR   = QColor(255, 200,   0)


def _class_color(class_idx):
    if class_idx < 0:
        return UNASSIGNED_COLOR
    return CLASS_COLORS[class_idx % len(CLASS_COLORS)]


def handle_rects(rect):
    s = HANDLE_SIZE
    hs = s // 2
    cx = rect.center().x()
    cy = rect.center().y()
    return [
        QRect(rect.left() - hs,  rect.top() - hs,    s, s),
        QRect(cx - hs,           rect.top() - hs,    s, s),
        QRect(rect.right() - hs, rect.top() - hs,    s, s),
        QRect(rect.left() - hs,  cy - hs,            s, s),
        QRect(rect.right() - hs, cy - hs,            s, s),
        QRect(rect.left() - hs,  rect.bottom() - hs, s, s),
        QRect(cx - hs,           rect.bottom() - hs, s, s),
        QRect(rect.right() - hs, rect.bottom() - hs, s, s),
    ]


def apply_handle_drag(original, handle, delta):
    r = QRect(original)
    dx, dy = delta.x(), delta.y()
    if handle in (TL, TC, TR):
        r.setTop(r.top() + dy)
    if handle in (BL, BC, BR):
        r.setBottom(r.bottom() + dy)
    if handle in (TL, ML, BL):
        r.setLeft(r.left() + dx)
    if handle in (TR, MR, BR):
        r.setRight(r.right() + dx)
    return r.normalized()


class Canvas(QLabel):
    rectangle_drawn  = Signal(QRect)
    shape_modified   = Signal(int, QRect)
    selection_changed = Signal(int)   # emits selected_index (-1 = deselected)

    def __init__(self):
        super().__init__()
        self.setStyleSheet("background-color: #1e1e1e; border: 2px solid #333;")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMouseTracking(True)
        # Prevent the pixmap sizeHint from feeding back into the layout size,
        # which would cause the canvas (and window) to grow on repeated image loads.
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)

        # shapes stores YOLO normalized tuples (cx, cy, nw, nh) — the source of truth.
        # Widget-space QRects are computed on the fly for display and hit-testing only.
        self.shapes        = []   # list[tuple[float,float,float,float]]
        self.shape_classes = []   # list[int], same length as shapes; -1 = unassigned
        self.class_names   = []   # list[str], maintained by main.py for label rendering
        self.current_pixmap = None
        self.original_size  = None   # QSize, original image dimensions

        self.draw_mode      = False   # W key toggles; always draws, never selects
        self.mode           = 'idle'
        self.selected_index = -1
        self.active_handle  = -1
        self.drag_start         = QPoint()
        self.drag_original_rect = None   # widget-space QRect, valid only during drag
        self.begin = QPoint()
        self.end   = QPoint()

        self._history    = []   # list of (shapes, shape_classes) snapshots for undo
        self._redo_stack = []

    # ── Undo / Redo ──────────────────────────────────────────────────────────

    def save_snapshot(self):
        """Save current shapes state before a mutating operation."""
        self._history.append((list(self.shapes), list(self.shape_classes)))
        self._redo_stack.clear()
        if len(self._history) > 50:
            self._history.pop(0)

    def undo(self) -> bool:
        if not self._history:
            return False
        self._redo_stack.append((list(self.shapes), list(self.shape_classes)))
        self.shapes, self.shape_classes = self._history.pop()
        self.selected_index = -1
        self.update()
        return True

    def redo(self) -> bool:
        if not self._redo_stack:
            return False
        self._history.append((list(self.shapes), list(self.shape_classes)))
        self.shapes, self.shape_classes = self._redo_stack.pop()
        self.selected_index = -1
        self.update()
        return True

    def set_image(self, pixmap):
        self.current_pixmap = pixmap
        self.original_size  = pixmap.size()
        self.shapes         = []
        self.shape_classes  = []
        self.selected_index = -1
        self.mode           = 'idle'
        self._history.clear()
        self._redo_stack.clear()
        self._rescale_pixmap()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._rescale_pixmap()

    def _rescale_pixmap(self):
        if self.current_pixmap:
            self.setPixmap(self.current_pixmap.scaled(
                self.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            ))

    def get_display_rect(self) -> QRect:
        """Return the QRect where the image is actually rendered (KeepAspectRatio + AlignCenter)."""
        if not self.original_size:
            return QRect()
        iw = self.original_size.width()
        ih = self.original_size.height()
        ww = self.width()
        wh = self.height()
        scale = min(ww / iw, wh / ih)
        sw = int(iw * scale)
        sh = int(ih * scale)
        ox = (ww - sw) // 2
        oy = (wh - sh) // 2
        return QRect(ox, oy, sw, sh)

    # ── Coordinate helpers ────────────────────────────────────────────────────

    def _yolo_to_wrect(self, cx, cy, nw, nh) -> QRect:
        """Convert a YOLO normalized box to a widget-space QRect for display/hit-testing."""
        dr = self.get_display_rect()
        if not self.original_size or dr.isEmpty():
            return QRect()
        iw = self.original_size.width()
        ih = self.original_size.height()
        sx = dr.width()  / iw
        sy = dr.height() / ih
        return QRect(
            round((cx - nw / 2) * iw * sx + dr.x()),
            round((cy - nh / 2) * ih * sy + dr.y()),
            round(nw * iw * sx),
            round(nh * ih * sy),
        )

    def _wrect_to_yolo(self, rect: QRect) -> tuple:
        """Convert a widget-space QRect to a YOLO normalized (cx, cy, nw, nh) tuple."""
        dr = self.get_display_rect()
        if not self.original_size or dr.isEmpty() or dr.width() == 0 or dr.height() == 0:
            return (0.5, 0.5, 0.1, 0.1)
        iw = self.original_size.width()
        ih = self.original_size.height()
        sx = iw / dr.width()
        sy = ih / dr.height()
        img_x = (rect.x() - dr.x()) * sx
        img_y = (rect.y() - dr.y()) * sy
        img_w = rect.width()  * sx
        img_h = rect.height() * sy
        cx = (img_x + img_w / 2) / iw
        cy = (img_y + img_h / 2) / ih
        nw = img_w / iw
        nh = img_h / ih
        return (
            max(0.0, min(1.0, cx)),
            max(0.0, min(1.0, cy)),
            max(0.0, min(1.0, nw)),
            max(0.0, min(1.0, nh)),
        )

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _handle_at(self, pos, rect):
        for i, hr in enumerate(handle_rects(rect)):
            if hr.contains(pos):
                return i
        return -1

    def _box_at(self, pos):
        for i in range(len(self.shapes) - 1, -1, -1):
            if self._yolo_to_wrect(*self.shapes[i]).contains(pos):
                return i
        return -1

    # ── Mouse events ─────────────────────────────────────────────────────────

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton or not self.current_pixmap:
            return
        pos = event.position().toPoint()

        if self.draw_mode:
            self.selected_index = -1
            self.mode  = 'drawing'
            self.begin = self._clamp_to_image(pos)
            self.end   = self.begin
            self.update()
            return

        if self.selected_index >= 0:
            _wrect = self._yolo_to_wrect(*self.shapes[self.selected_index])
            h = self._handle_at(pos, _wrect)
            if h >= 0:
                self.save_snapshot()
                self.mode               = 'resizing'
                self.active_handle      = h
                self.drag_start         = pos
                self.drag_original_rect = _wrect
                return

        idx = self._box_at(pos)
        if idx >= 0:
            self.save_snapshot()
            self.selected_index     = idx
            self.mode               = 'moving'
            self.drag_start         = pos
            self.drag_original_rect = self._yolo_to_wrect(*self.shapes[idx])
            self.selection_changed.emit(idx)
            self.update()
            return

        # Normal mode, clicked on empty space → do nothing (no accidental drawing)
        self.selected_index = -1
        self.selection_changed.emit(-1)
        self.update()

    def _clamp_to_image(self, pos: QPoint) -> QPoint:
        dr = self.get_display_rect()
        if dr.isEmpty():
            return pos
        return QPoint(
            max(dr.left(), min(dr.right(),  pos.x())),
            max(dr.top(),  min(dr.bottom(), pos.y())),
        )

    def _clamp_rect_to_image(self, rect: QRect) -> QRect:
        """Clamp rect so it stays fully inside the image display area."""
        dr = self.get_display_rect()
        if dr.isEmpty():
            return rect
        x = max(dr.left(), min(rect.x(), dr.right()  + 1 - rect.width()))
        y = max(dr.top(),  min(rect.y(), dr.bottom() + 1 - rect.height()))
        return QRect(x, y, rect.width(), rect.height())

    def mouseMoveEvent(self, event):
        pos = event.position().toPoint()

        if self.mode == 'drawing':
            self.end = self._clamp_to_image(pos)
            self.update()

        elif self.mode == 'moving' and self.selected_index >= 0:
            new_wrect = self._clamp_rect_to_image(
                self.drag_original_rect.translated(pos - self.drag_start))
            self.shapes[self.selected_index] = self._wrect_to_yolo(new_wrect)
            self.update()

        elif self.mode == 'resizing' and self.selected_index >= 0:
            clamped_pos = self._clamp_to_image(pos)
            new_wrect = self._clamp_rect_to_image(
                apply_handle_drag(self.drag_original_rect, self.active_handle, clamped_pos - self.drag_start))
            self.shapes[self.selected_index] = self._wrect_to_yolo(new_wrect)
            self.update()

        else:
            self._update_cursor(pos)

    def mouseReleaseEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton:
            return

        if self.mode == 'drawing':
            new_rect = QRect(self.begin, self.end).normalized()
            if new_rect.width() > 5 and new_rect.height() > 5:
                self.save_snapshot()
                self.shapes.append(self._wrect_to_yolo(new_rect))
                self.shape_classes.append(-1)          # unassigned; main.py will update it
                self.selected_index = len(self.shapes) - 1
                self.rectangle_drawn.emit(new_rect)

        elif self.mode in ('moving', 'resizing') and self.selected_index >= 0:
            self.shape_modified.emit(self.selected_index, self._yolo_to_wrect(*self.shapes[self.selected_index]))

        self.mode = 'idle'
        self._update_cursor(event.position().toPoint())
        self.update()

    # ── Cursor ───────────────────────────────────────────────────────────────

    def _update_cursor(self, pos):
        if self.draw_mode:
            self.setCursor(QCursor(Qt.CursorShape.CrossCursor))
            return
        if self.selected_index >= len(self.shapes):
            self.selected_index = -1
        if self.selected_index >= 0:
            h = self._handle_at(pos, self._yolo_to_wrect(*self.shapes[self.selected_index]))
            if h >= 0:
                self.setCursor(QCursor(HANDLE_CURSORS[h]))
                return
        if self._box_at(pos) >= 0:
            self.setCursor(QCursor(Qt.CursorShape.SizeAllCursor))
        else:
            self.setCursor(QCursor(Qt.CursorShape.CrossCursor))

    # ── Paint ────────────────────────────────────────────────────────────────

    def paintEvent(self, event):
        super().paintEvent(event)
        with QPainter(self) as painter:
            for i, shape in enumerate(self.shapes):
                rect = self._yolo_to_wrect(*shape)
                cls_color = _class_color(self.shape_classes[i])

                if i == self.selected_index:
                    # Selected box: class-color border + yellow handles
                    painter.setPen(QPen(cls_color, 2))
                    painter.drawRect(rect)
                    painter.setBrush(QBrush(SELECTED_COLOR))
                    painter.setPen(QPen(QColor(0, 0, 0), 1))
                    for hr in handle_rects(rect):
                        painter.drawRect(hr)
                    painter.setBrush(Qt.BrushStyle.NoBrush)
                else:
                    painter.setPen(QPen(cls_color, 2))
                    painter.drawRect(rect)

                # Class label text (top-left corner, black outline + white fill)
                cls_idx = self.shape_classes[i]
                if 0 <= cls_idx < len(self.class_names):
                    text = self.class_names[cls_idx]
                    tx = rect.left() + 3
                    ty = rect.top() + 13
                    painter.setPen(QPen(QColor(0, 0, 0)))
                    for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                        painter.drawText(tx + dx, ty + dy, text)
                    painter.setPen(QPen(QColor(255, 255, 255)))
                    painter.drawText(tx, ty, text)

            if self.mode == 'drawing':
                painter.setPen(QPen(QColor(255, 0, 0), 2, Qt.PenStyle.DashLine))
                painter.drawRect(QRect(self.begin, self.end).normalized())


class Ui_MainWindow(object):
    def setupUi(self, MainWindow):
        MainWindow.setWindowTitle("LabelItem")
        MainWindow.resize(1280, 800)

        self.central_widget = QWidget()
        self.main_layout = QHBoxLayout(self.central_widget)

        # ── Left panel ────────────────────────────────────────────────────
        self.left_bar = QVBoxLayout()

        self.btn_img_dir = QPushButton("📂 Image Directory")
        self.btn_img_dir.setFixedHeight(40)
        self.lbl_img_path = QLabel("Image: Not selected")
        self.lbl_img_path.setStyleSheet("color: gray; font-size: 10px;")
        self.lbl_img_path.setWordWrap(True)

        self.btn_save_dir = QPushButton("💾 Label Directory")
        self.btn_save_dir.setFixedHeight(40)
        self.lbl_save_path = QLabel("Labels: Not selected")
        self.lbl_save_path.setStyleSheet("color: gray; font-size: 10px;")
        self.lbl_save_path.setWordWrap(True)

        self.btn_export_dataset = QPushButton("📦 Export Dataset")
        self.btn_export_dataset.setFixedHeight(44)
        self.btn_export_dataset.setStyleSheet(
            "background-color: #1565c0; color: white; font-weight: bold; border-radius: 5px;"
        )

        self.btn_auto_annotate = QPushButton("🤖 Auto Annotate")
        self.btn_auto_annotate.setFixedHeight(36)
        self.btn_auto_annotate.setStyleSheet(
            "background-color: #2e7d32; color: white; font-weight: bold; border-radius: 4px;"
        )

        self.btn_draw_mode = QPushButton("✏️ Draw  [W]")
        self.btn_draw_mode.setFixedHeight(36)
        self.btn_draw_mode.setToolTip("Toggle draw mode (W) — always draws new boxes, never selects")

        self.btn_check_mode = QPushButton("🔍 Check Mode")
        self.btn_check_mode.setFixedHeight(36)
        self.btn_check_mode.setCheckable(True)
        self.btn_check_mode.setStyleSheet(
            "QPushButton:checked { background-color: #6a1b9a; color: white; font-weight: bold; border-radius: 4px; }"
        )

        # Bottom-left: page 0 = file list (label mode), page 1 = class selector (check mode)
        self.bottom_left_stack = QStackedWidget()

        page_files = QWidget()
        files_layout = QVBoxLayout(page_files)
        files_layout.setContentsMargins(0, 0, 0, 0)
        files_layout.addWidget(QLabel("File List:"))
        self.file_list = QListWidget()
        files_layout.addWidget(self.file_list)
        self.btn_delete_image = QPushButton("🗑  Delete Image & Label")
        self.btn_delete_image.setFixedHeight(28)
        self.btn_delete_image.setStyleSheet(
            "background-color: #b71c1c; color: white; border-radius: 3px;")
        files_layout.addWidget(self.btn_delete_image)

        page_check = QWidget()
        check_layout = QVBoxLayout(page_check)
        check_layout.setContentsMargins(0, 0, 0, 0)
        check_layout.addWidget(QLabel("Select Class:"))
        self.check_class_list = QListWidget()
        check_layout.addWidget(self.check_class_list)

        self.bottom_left_stack.addWidget(page_files)   # index 0
        self.bottom_left_stack.addWidget(page_check)   # index 1

        self.left_bar.addWidget(self.btn_img_dir)
        self.left_bar.addWidget(self.lbl_img_path)
        self.left_bar.addSpacing(8)
        self.left_bar.addWidget(self.btn_save_dir)
        self.left_bar.addWidget(self.lbl_save_path)
        self.left_bar.addSpacing(16)
        self.left_bar.addWidget(self.btn_export_dataset)
        self.left_bar.addSpacing(4)
        self.left_bar.addWidget(self.btn_auto_annotate)
        self.left_bar.addSpacing(4)
        self.left_bar.addWidget(self.btn_draw_mode)
        self.left_bar.addSpacing(4)
        self.left_bar.addWidget(self.btn_check_mode)
        self.left_bar.addStretch()
        self.left_bar.addWidget(self.bottom_left_stack, stretch=2)

        # ── Center: stacked (canvas | check gallery) ──────────────────────
        self.canvas = Canvas()

        self.check_view = QListWidget()
        self.check_view.setViewMode(QListWidget.ViewMode.IconMode)
        self.check_view.setIconSize(QSize(176, 130))
        self.check_view.setGridSize(QSize(186, 144))
        self.check_view.setResizeMode(QListWidget.ResizeMode.Adjust)
        self.check_view.setMovement(QListWidget.Movement.Static)
        self.check_view.setSpacing(6)
        self.check_view.setUniformItemSizes(True)
        self.check_view.setWordWrap(True)
        self.check_view.setStyleSheet(
            "QListWidget { background-color: #1e1e1e; color: #ccc; border: 2px solid #333; }"
            "QListWidget::item { color: #aaa; font-size: 10px; }"
            "QListWidget::item:selected { background-color: #6a1b9a; color: white; }"
        )

        self.center_stack = QStackedWidget()
        self.center_stack.addWidget(self.canvas)     # index 0
        self.center_stack.addWidget(self.check_view) # index 1

        # ── Right panel ───────────────────────────────────────────────────
        self.right_bar = QVBoxLayout()

        # Bounding boxes
        self.right_bar.addWidget(QLabel("Bounding Boxes (Delete to remove):"))
        self.shape_list = QListWidget()
        self.right_bar.addWidget(self.shape_list, stretch=1)

        # Class management
        self.right_bar.addSpacing(8)
        self.right_bar.addWidget(QLabel("Classes (select, then draw to apply):"))

        class_input_row = QHBoxLayout()
        self.class_input = QLineEdit()
        self.class_input.setPlaceholderText("Enter class name…")
        self.btn_add_class = QPushButton("Add")
        self.btn_add_class.setFixedWidth(48)
        class_input_row.addWidget(self.class_input)
        class_input_row.addWidget(self.btn_add_class)
        self.right_bar.addLayout(class_input_row)

        self.class_list = QListWidget()
        self.class_list.setMaximumHeight(160)
        self.right_bar.addWidget(self.class_list)

        self.btn_del_class = QPushButton("Delete Selected Class")
        self.btn_del_class.setFixedHeight(32)
        self.right_bar.addWidget(self.btn_del_class)

        # Compose
        self.main_layout.addLayout(self.left_bar, stretch=1)
        self.main_layout.addWidget(self.center_stack, stretch=4)
        self.main_layout.addLayout(self.right_bar, stretch=1)

        MainWindow.setCentralWidget(self.central_widget)
