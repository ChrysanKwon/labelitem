import copy

from PySide6.QtWidgets import (QVBoxLayout, QHBoxLayout, QPushButton,
                               QListWidget, QLabel, QWidget, QLineEdit,
                               QStackedWidget, QSizePolicy, QButtonGroup, QSlider,
                               QDoubleSpinBox, QSpinBox, QComboBox, QProgressBar)
from PySide6.QtGui import QPainter, QPen, QColor, QBrush, QCursor, QPolygon
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
    polygon_drawn    = Signal(int)   # emits index of new polygon shape
    shape_modified   = Signal(int, QRect)
    selection_changed = Signal(int)   # emits selected_index (-1 = deselected)

    def __init__(self):
        super().__init__()
        self.setStyleSheet("background-color: #1e1e1e; border: 2px solid #333;")
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setMouseTracking(True)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)

        self.shapes        = []   # list[tuple|list]: tuple=(cx,cy,nw,nh) bbox; list=[(x,y),...] polygon
        self.shape_classes = []   # list[int], same length as shapes; -1 = unassigned
        self.class_names   = []   # list[str], maintained by main.py for label rendering
        self.current_pixmap = None
        self.original_size  = None   # QSize, original image dimensions

        self.draw_mode      = False   # W key: always draw bbox
        self.polygon_mode   = False   # P key: always draw polygon
        self.mode           = 'idle'  # 'idle','drawing','moving','resizing','drawing_polygon','moving_vertex'
        self.selected_index = -1
        self.active_handle  = -1
        self.drag_start         = QPoint()
        self.drag_original_rect = None

        # Bbox drawing
        self.begin = QPoint()
        self.end   = QPoint()

        # Polygon drawing
        self._poly_points       = []    # list[QPoint] widget-space, in-progress vertices
        self._poly_preview      = None  # QPoint: current mouse pos during drawing
        self._active_vertex_idx = -1    # index of vertex being dragged

        self._history    = []   # list of (shapes, shape_classes) snapshots for undo
        self._redo_stack = []

    # ── Undo / Redo ──────────────────────────────────────────────────────────

    def save_snapshot(self):
        self._history.append((copy.deepcopy(self.shapes), list(self.shape_classes)))
        self._redo_stack.clear()
        if len(self._history) > 50:
            self._history.pop(0)

    def undo(self) -> bool:
        if not self._history:
            return False
        self._redo_stack.append((copy.deepcopy(self.shapes), list(self.shape_classes)))
        self.shapes, self.shape_classes = self._history.pop()
        self.selected_index = -1
        self._poly_points.clear()
        self.mode = 'idle'
        self.update()
        return True

    def redo(self) -> bool:
        if not self._redo_stack:
            return False
        self._history.append((copy.deepcopy(self.shapes), list(self.shape_classes)))
        self.shapes, self.shape_classes = self._redo_stack.pop()
        self.selected_index = -1
        self._poly_points.clear()
        self.mode = 'idle'
        self.update()
        return True

    def set_image(self, pixmap):
        self.current_pixmap = pixmap
        self.original_size  = pixmap.size()
        self.shapes         = []
        self.shape_classes  = []
        self.selected_index = -1
        self.mode           = 'idle'
        self._poly_points.clear()
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
        """Convert a YOLO normalized box to a widget-space QRect."""
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

    def _yolo_pt_to_widget(self, x: float, y: float) -> QPoint:
        """Convert a normalized (x, y) point to widget-space QPoint."""
        dr = self.get_display_rect()
        return QPoint(int(dr.x() + x * dr.width()),
                      int(dr.y() + y * dr.height()))

    def _widget_pt_to_yolo(self, pt: QPoint) -> tuple:
        """Convert a widget-space QPoint to normalized (x, y)."""
        dr = self.get_display_rect()
        if dr.width() == 0 or dr.height() == 0:
            return (0.5, 0.5)
        x = (pt.x() - dr.x()) / dr.width()
        y = (pt.y() - dr.y()) / dr.height()
        return (max(0.0, min(1.0, x)), max(0.0, min(1.0, y)))

    def _poly_wrect(self, shape: list) -> QRect:
        """Return bounding QRect of a polygon shape in widget coords."""
        pts = [self._yolo_pt_to_widget(x, y) for x, y in shape]
        xs = [p.x() for p in pts]
        ys = [p.y() for p in pts]
        return QRect(min(xs), min(ys), max(xs) - min(xs), max(ys) - min(ys))

    # ── Helpers ──────────────────────────────────────────────────────────────

    def _handle_at(self, pos, rect):
        for i, hr in enumerate(handle_rects(rect)):
            if hr.contains(pos):
                return i
        return -1

    def _vertex_at(self, pos) -> int:
        """Return vertex index of selected polygon near pos, -1 if none."""
        if self.selected_index < 0:
            return -1
        shape = self.shapes[self.selected_index]
        if not isinstance(shape, list):
            return -1
        hs = HANDLE_SIZE
        for i, (x, y) in enumerate(shape):
            pt = self._yolo_pt_to_widget(x, y)
            if abs(pt.x() - pos.x()) <= hs and abs(pt.y() - pos.y()) <= hs:
                return i
        return -1

    def _box_at(self, pos) -> int:
        """Return index of topmost shape containing pos, -1 if none."""
        for i in range(len(self.shapes) - 1, -1, -1):
            shape = self.shapes[i]
            if isinstance(shape, list):
                pts = [self._yolo_pt_to_widget(x, y) for x, y in shape]
                poly = QPolygon(pts)
                if poly.containsPoint(pos, Qt.FillRule.OddEvenFill):
                    return i
            else:
                if self._yolo_to_wrect(*shape).contains(pos):
                    return i
        return -1

    # ── Mouse events ─────────────────────────────────────────────────────────

    def mousePressEvent(self, event):
        if event.button() != Qt.MouseButton.LeftButton or not self.current_pixmap:
            return
        pos = event.position().toPoint()

        # Polygon draw mode: add vertex on each click
        if self.polygon_mode:
            if self.mode != 'drawing_polygon':
                self.mode = 'drawing_polygon'
                self._poly_points = []
            clamped = self._clamp_to_image(pos)
            self._poly_points.append(clamped)
            self._poly_preview = clamped
            self.update()
            return

        # Bbox draw mode
        if self.draw_mode:
            self.selected_index = -1
            self.mode  = 'drawing'
            self.begin = self._clamp_to_image(pos)
            self.end   = self.begin
            self.update()
            return

        # Selection / move / resize
        # Check vertex drag on selected polygon first
        v = self._vertex_at(pos)
        if v >= 0:
            self.save_snapshot()
            self.mode = 'moving_vertex'
            self._active_vertex_idx = v
            self.drag_start = pos
            return

        # Check handle drag on selected bbox
        if self.selected_index >= 0:
            shape = self.shapes[self.selected_index]
            if not isinstance(shape, list):
                _wrect = self._yolo_to_wrect(*shape)
                h = self._handle_at(pos, _wrect)
                if h >= 0:
                    self.save_snapshot()
                    self.mode               = 'resizing'
                    self.active_handle      = h
                    self.drag_start         = pos
                    self.drag_original_rect = _wrect
                    return

        # Click on any shape → select and move
        idx = self._box_at(pos)
        if idx >= 0:
            self.save_snapshot()
            self.selected_index     = idx
            self.mode               = 'moving'
            self.drag_start         = pos
            shape = self.shapes[idx]
            if isinstance(shape, list):
                self.drag_original_rect = self._poly_wrect(shape)
                self._drag_poly_origin  = [pt for pt in shape]  # copy
            else:
                self.drag_original_rect = self._yolo_to_wrect(*shape)
            self.selection_changed.emit(idx)
            self.update()
            return

        # Clicked empty space
        self.selected_index = -1
        self.selection_changed.emit(-1)
        self.update()

    def mouseDoubleClickEvent(self, event):
        """Double-click in polygon_mode finalizes the polygon."""
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if self.mode == 'drawing_polygon' and self.polygon_mode:
            # Double-click fires a prior single-click too, which added an extra point — remove it
            if len(self._poly_points) > 0:
                self._poly_points.pop()
            if len(self._poly_points) >= 3:
                self.save_snapshot()
                pts_yolo = [self._widget_pt_to_yolo(p) for p in self._poly_points]
                self.shapes.append(pts_yolo)
                self.shape_classes.append(-1)
                self.selected_index = len(self.shapes) - 1
                self.polygon_drawn.emit(self.selected_index)
            self._poly_points.clear()
            self._poly_preview = None
            self.mode = 'idle'
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

        elif self.mode == 'drawing_polygon':
            self._poly_preview = self._clamp_to_image(pos)
            self.update()

        elif self.mode == 'moving' and self.selected_index >= 0:
            shape = self.shapes[self.selected_index]
            delta = pos - self.drag_start
            if isinstance(shape, list):
                # Translate all polygon points
                dr = self.get_display_rect()
                if dr.width() > 0 and dr.height() > 0:
                    dx = delta.x() / dr.width()
                    dy = delta.y() / dr.height()
                    self.shapes[self.selected_index] = [
                        (max(0.0, min(1.0, ox + dx)), max(0.0, min(1.0, oy + dy)))
                        for ox, oy in self._drag_poly_origin
                    ]
            else:
                new_wrect = self._clamp_rect_to_image(
                    self.drag_original_rect.translated(delta))
                self.shapes[self.selected_index] = self._wrect_to_yolo(new_wrect)
            self.update()

        elif self.mode == 'resizing' and self.selected_index >= 0:
            clamped_pos = self._clamp_to_image(pos)
            new_wrect = self._clamp_rect_to_image(
                apply_handle_drag(self.drag_original_rect, self.active_handle,
                                  clamped_pos - self.drag_start))
            self.shapes[self.selected_index] = self._wrect_to_yolo(new_wrect)
            self.update()

        elif self.mode == 'moving_vertex' and self.selected_index >= 0:
            clamped = self._clamp_to_image(pos)
            yolo_pt = self._widget_pt_to_yolo(clamped)
            shape = self.shapes[self.selected_index]
            if isinstance(shape, list) and 0 <= self._active_vertex_idx < len(shape):
                shape[self._active_vertex_idx] = yolo_pt
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
                self.shape_classes.append(-1)
                self.selected_index = len(self.shapes) - 1
                self.rectangle_drawn.emit(new_rect)

        elif self.mode == 'moving_vertex' and self.selected_index >= 0:
            shape = self.shapes[self.selected_index]
            rect = self._poly_wrect(shape) if isinstance(shape, list) else self._yolo_to_wrect(*shape)
            self.shape_modified.emit(self.selected_index, rect)

        elif self.mode in ('moving', 'resizing') and self.selected_index >= 0:
            shape = self.shapes[self.selected_index]
            rect = self._poly_wrect(shape) if isinstance(shape, list) else self._yolo_to_wrect(*shape)
            self.shape_modified.emit(self.selected_index, rect)

        if self.mode != 'drawing_polygon':
            self.mode = 'idle'
        self._active_vertex_idx = -1
        self._update_cursor(event.position().toPoint())
        self.update()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key.Key_Escape and self.mode == 'drawing_polygon':
            self._poly_points.clear()
            self._poly_preview = None
            self.mode = 'idle'
            self.update()
        super().keyPressEvent(event)

    # ── Cursor ───────────────────────────────────────────────────────────────

    def _update_cursor(self, pos):
        if self.draw_mode or self.polygon_mode:
            self.setCursor(QCursor(Qt.CursorShape.CrossCursor))
            return
        if self.selected_index >= len(self.shapes):
            self.selected_index = -1
        # Polygon vertex handle
        if self._vertex_at(pos) >= 0:
            self.setCursor(QCursor(Qt.CursorShape.SizeAllCursor))
            return
        if self.selected_index >= 0:
            shape = self.shapes[self.selected_index]
            if not isinstance(shape, list):
                h = self._handle_at(pos, self._yolo_to_wrect(*shape))
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
                cls_color = _class_color(self.shape_classes[i])
                is_selected = (i == self.selected_index)

                if isinstance(shape, list):   # polygon
                    pts_w = [self._yolo_pt_to_widget(x, y) for x, y in shape]
                    poly  = QPolygon(pts_w)

                    painter.setPen(QPen(cls_color, 2))
                    painter.drawPolygon(poly)

                    if is_selected:
                        # Draw vertex handles
                        painter.setBrush(QBrush(SELECTED_COLOR))
                        painter.setPen(QPen(QColor(0, 0, 0), 1))
                        hs = HANDLE_SIZE
                        for pt in pts_w:
                            painter.drawEllipse(pt, hs, hs)
                        painter.setBrush(Qt.BrushStyle.NoBrush)

                    # Class label at centroid
                    cls_idx = self.shape_classes[i]
                    if 0 <= cls_idx < len(self.class_names) and pts_w:
                        text = self.class_names[cls_idx]
                        tx = min(p.x() for p in pts_w) + 3
                        ty = min(p.y() for p in pts_w) + 13
                        painter.setPen(QPen(QColor(0, 0, 0)))
                        for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                            painter.drawText(tx + dx, ty + dy, text)
                        painter.setPen(QPen(QColor(255, 255, 255)))
                        painter.drawText(tx, ty, text)

                else:   # bbox
                    rect = self._yolo_to_wrect(*shape)

                    if is_selected:
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

            # Bbox draw preview
            if self.mode == 'drawing':
                painter.setPen(QPen(QColor(255, 0, 0), 2, Qt.PenStyle.DashLine))
                painter.drawRect(QRect(self.begin, self.end).normalized())

            # Polygon draw preview
            if self.mode == 'drawing_polygon' and self._poly_points:
                painter.setPen(QPen(QColor(255, 140, 0), 2))
                for j in range(len(self._poly_points) - 1):
                    painter.drawLine(self._poly_points[j], self._poly_points[j + 1])
                # Last segment to current mouse
                if self._poly_preview:
                    painter.setPen(QPen(QColor(255, 140, 0), 2, Qt.PenStyle.DashLine))
                    painter.drawLine(self._poly_points[-1], self._poly_preview)
                # Vertex dots
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(QBrush(QColor(255, 140, 0)))
                for pt in self._poly_points:
                    painter.drawEllipse(pt, 4, 4)


class VideoFrameLabel(QLabel):
    """QLabel that always scales its stored source pixmap to fit on resize."""

    def __init__(self):
        super().__init__()
        self._src_pixmap = None

    def setPixmap(self, pixmap):           # noqa: N802
        self._src_pixmap = pixmap
        self._rescale()

    def resizeEvent(self, event):          # noqa: N802
        super().resizeEvent(event)
        self._rescale()

    def _rescale(self):
        if self._src_pixmap and not self._src_pixmap.isNull():
            super().setPixmap(self._src_pixmap.scaled(
                self.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            ))


class Ui_MainWindow(object):
    def setupUi(self, MainWindow):
        MainWindow.setWindowTitle("LabelItem")
        MainWindow.resize(1400, 800)

        self.central_widget = QWidget()
        self.main_layout = QHBoxLayout(self.central_widget)
        self.main_layout.setSpacing(0)
        self.main_layout.setContentsMargins(0, 0, 0, 0)

        # ── Nav column ────────────────────────────────────────────────────
        nav_widget = QWidget()
        nav_widget.setFixedWidth(90)
        nav_widget.setStyleSheet("background-color: #252526; border-right: 1px solid #333;")
        nav_layout = QVBoxLayout(nav_widget)
        nav_layout.setContentsMargins(4, 8, 4, 8)
        nav_layout.setSpacing(4)

        _nav_style = (
            "QPushButton { background:transparent; color:#ccc; border-radius:6px;"
            " font-size:10px; padding:6px 2px; }"
            "QPushButton:checked { background:#6a1b9a; color:white; font-weight:bold; }"
            "QPushButton:hover:!checked { background:#3a3a3a; }"
        )

        self.btn_nav_label       = QPushButton("🏷️\nImage Label")
        self.btn_nav_check       = QPushButton("🔍\nLabel Review")
        self.btn_nav_video       = QPushButton("🎬\nVideo Capture")
        self.btn_nav_model_check = QPushButton("🤖\nModel Check")
        for btn in (self.btn_nav_label, self.btn_nav_check,
                    self.btn_nav_video, self.btn_nav_model_check):
            btn.setCheckable(True)
            btn.setFixedHeight(56)
            btn.setStyleSheet(_nav_style)

        self.btn_nav_label.setChecked(True)

        self._nav_group = QButtonGroup(nav_widget)
        self._nav_group.setExclusive(True)
        self._nav_group.addButton(self.btn_nav_label,       0)
        self._nav_group.addButton(self.btn_nav_check,       1)
        self._nav_group.addButton(self.btn_nav_video,       2)
        self._nav_group.addButton(self.btn_nav_model_check, 3)

        nav_layout.addWidget(self.btn_nav_label)
        nav_layout.addWidget(self.btn_nav_check)
        nav_layout.addWidget(self.btn_nav_video)
        nav_layout.addWidget(self.btn_nav_model_check)
        nav_layout.addStretch()

        _nav_util_style = (
            "QPushButton { background:transparent; color:#666; border-radius:6px;"
            " font-size:10px; padding:4px 2px; }"
            "QPushButton:hover { background:#2a2a2a; color:#aaa; }"
        )
        self.btn_settings = QPushButton("⚙️\nSettings")
        self.btn_settings.setFixedHeight(48)
        self.btn_settings.setStyleSheet(_nav_util_style)
        nav_layout.addWidget(self.btn_settings)

        self.btn_restart = QPushButton("🔄\nRestart")
        self.btn_restart.setFixedHeight(48)
        self.btn_restart.setStyleSheet(
            "QPushButton { background:transparent; color:#666; border-radius:6px;"
            " font-size:10px; padding:4px 2px; }"
            "QPushButton:hover { background:#3a2020; color:#e57373; }"
        )
        nav_layout.addWidget(self.btn_restart)

        # ── Left panel ────────────────────────────────────────────────────
        left_widget = QWidget()
        self.left_bar = QVBoxLayout(left_widget)
        self.left_bar.setContentsMargins(8, 8, 8, 8)

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

        # Bottom-left stack: page 0 = file list, page 1 = check class, page 2 = video
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

        self.btn_clean_labels = QPushButton("🧹  Clean Orphaned Labels")
        self.btn_clean_labels.setFixedHeight(28)
        self.btn_clean_labels.setStyleSheet(
            "background-color: #4a148c; color: white; border-radius: 3px;")
        files_layout.addWidget(self.btn_clean_labels)

        page_check = QWidget()
        check_layout = QVBoxLayout(page_check)
        check_layout.setContentsMargins(0, 0, 0, 0)
        check_layout.addWidget(QLabel("Select Class:"))
        self.check_class_list = QListWidget()
        check_layout.addWidget(self.check_class_list)

        page_video = QWidget()
        video_layout = QVBoxLayout(page_video)
        video_layout.setContentsMargins(0, 0, 0, 0)
        video_layout.setSpacing(6)

        self.btn_open_video = QPushButton("📂 Open Video")
        self.btn_open_video.setFixedHeight(36)
        self.lbl_video_info = QLabel("No video loaded")
        self.lbl_video_info.setWordWrap(True)
        self.lbl_video_info.setStyleSheet("color: gray; font-size: 11px;")
        self.btn_video_capture = QPushButton("📷 Capture Frame")
        self.btn_video_capture.setFixedHeight(40)
        self.btn_video_capture.setEnabled(False)
        self.btn_video_capture.setStyleSheet(
            "QPushButton { background-color: #37474f; color: white; font-weight: bold;"
            " border-radius: 4px; }"
            "QPushButton:hover { background-color: #455a64; }"
            "QPushButton:disabled { background-color: #222; color: #484848; }"
        )
        self.btn_extract_frames = QPushButton("📸 Extract Frames…")
        self.btn_extract_frames.setFixedHeight(32)
        self.btn_extract_frames.setEnabled(False)

        video_layout.addWidget(self.btn_open_video)
        video_layout.addWidget(self.lbl_video_info)
        video_layout.addSpacing(8)
        video_layout.addWidget(self.btn_video_capture)
        video_layout.addSpacing(4)
        video_layout.addWidget(self.btn_extract_frames)
        video_layout.addStretch()

        # Model Check left panel (page 3)
        page_mc = QWidget()
        mc_layout = QVBoxLayout(page_mc)
        mc_layout.setContentsMargins(0, 0, 0, 0)
        mc_layout.setSpacing(6)

        self.btn_mc_open_video = QPushButton("📂 Open Video")
        self.btn_mc_open_video.setFixedHeight(36)
        self.lbl_mc_video_info = QLabel("No video loaded")
        self.lbl_mc_video_info.setWordWrap(True)
        self.lbl_mc_video_info.setStyleSheet("color: gray; font-size: 11px;")

        _mc_sep_style = "background:#444; max-height:1px; min-height:1px; margin:2px 0;"
        sep_a = QWidget(); sep_a.setStyleSheet(_mc_sep_style)

        self.btn_mc_load_model = QPushButton("🤖 Load Model (.pt)")
        self.btn_mc_load_model.setFixedHeight(36)
        self.lbl_mc_model_info = QLabel("No model loaded")
        self.lbl_mc_model_info.setWordWrap(True)
        self.lbl_mc_model_info.setStyleSheet("color: gray; font-size: 11px;")

        mc_conf_row = QHBoxLayout()
        mc_conf_row.addWidget(QLabel("Conf:"))
        self.mc_conf_spin = QDoubleSpinBox()
        self.mc_conf_spin.setRange(0.01, 1.0)
        self.mc_conf_spin.setSingleStep(0.05)
        self.mc_conf_spin.setValue(0.25)
        self.mc_conf_spin.setFixedWidth(85)
        mc_conf_row.addWidget(self.mc_conf_spin)
        mc_conf_row.addStretch()

        sep_b = QWidget(); sep_b.setStyleSheet(_mc_sep_style)

        # ── Mode toggle ───────────────────────────────────────────────────────
        _mc_mode_style = (
            "QPushButton { border:1px solid #555; border-radius:4px; color:#ccc;"
            " padding:4px 10px; background:#2d2d2d; }"
            "QPushButton:checked { background:#1565c0; color:white; font-weight:bold; border-color:#1565c0; }"
            "QPushButton:hover:!checked { background:#3a3a3a; }"
            "QPushButton:disabled { color:#484848; border-color:#333; background:#222; }"
        )
        self.btn_mc_mode_frame = QPushButton("▶ Frame")
        self.btn_mc_mode_frame.setCheckable(True)
        self.btn_mc_mode_frame.setChecked(True)
        self.btn_mc_mode_frame.setStyleSheet(_mc_mode_style)
        self.btn_mc_mode_scan  = QPushButton("📊 Scan")
        self.btn_mc_mode_scan.setCheckable(True)
        self.btn_mc_mode_scan.setStyleSheet(_mc_mode_style)
        self.mc_mode_group = QButtonGroup()
        self.mc_mode_group.setExclusive(True)
        self.mc_mode_group.addButton(self.btn_mc_mode_frame, 0)
        self.mc_mode_group.addButton(self.btn_mc_mode_scan,  1)
        mc_mode_row = QHBoxLayout()
        mc_mode_row.setSpacing(0)
        mc_mode_row.addWidget(self.btn_mc_mode_frame)
        mc_mode_row.addWidget(self.btn_mc_mode_scan)

        # ── Mode stack (page 0 = Frame, page 1 = Scan) ───────────────────────
        from PySide6.QtWidgets import QStackedWidget as _SW
        self.mc_mode_stack = _SW()

        # Page 0 — Frame inference
        page_frame = QWidget()
        frame_layout = QVBoxLayout(page_frame)
        frame_layout.setContentsMargins(0, 0, 0, 0)
        frame_layout.setSpacing(4)

        mc_det_header = QHBoxLayout()
        mc_det_header.addWidget(QLabel("Detections:"))
        _combo_style = (
            "QComboBox { background:#2d2d2d; color:#ccc; border:1px solid #444;"
            " border-radius:3px; padding:1px 4px; font-size:10pt; }"
            "QComboBox::drop-down { border:none; }"
            "QComboBox QAbstractItemView { background:#2d2d2d; color:#ccc; }"
        )
        self.mc_class_filter = QComboBox()
        self.mc_class_filter.addItem("All")
        self.mc_class_filter.setStyleSheet(_combo_style)
        mc_det_header.addWidget(self.mc_class_filter)
        frame_layout.addLayout(mc_det_header)

        self.mc_detection_list = QListWidget()
        self.mc_detection_list.setStyleSheet(
            "QListWidget { background:#1e1e1e; color:#ccc; border:1px solid #333; outline:none; }"
            "QListWidget::item:selected { background:#2a2a2a; color:white;"
            " border-left:3px solid #1565c0; outline:none; }"
            "QListWidget::item:selected:!active { background:#2a2a2a; color:white;"
            " border-left:3px solid #1565c0; }"
        )
        frame_layout.addWidget(self.mc_detection_list, stretch=1)

        self.btn_mc_delete_det = QPushButton("🗑 Delete Selected")
        self.btn_mc_delete_det.setFixedHeight(28)
        self.btn_mc_delete_det.setStyleSheet(
            "background-color: #b71c1c; color: white; border-radius: 3px;")
        frame_layout.addWidget(self.btn_mc_delete_det)

        sep_c = QWidget(); sep_c.setStyleSheet(_mc_sep_style)
        frame_layout.addWidget(sep_c)

        self.btn_mc_capture = QPushButton("📷 Capture + Save Labels")
        self.btn_mc_capture.setFixedHeight(44)
        self.btn_mc_capture.setEnabled(False)
        self.btn_mc_capture.setStyleSheet(
            "QPushButton { background-color: #1565c0; color: white; font-weight: bold;"
            " border-radius: 5px; }"
            "QPushButton:hover { background-color: #1976d2; }"
            "QPushButton:disabled { background-color: #222; color: #484848; }"
        )
        frame_layout.addWidget(self.btn_mc_capture)
        self.mc_mode_stack.addWidget(page_frame)  # index 0

        # Page 1 — Scan all frames
        page_scan = QWidget()
        scan_layout = QVBoxLayout(page_scan)
        scan_layout.setContentsMargins(0, 0, 0, 0)
        scan_layout.setSpacing(4)

        self.btn_mc_scan = QPushButton("📊 Scan All Frames")
        self.btn_mc_scan.setFixedHeight(36)
        self.btn_mc_scan.setEnabled(False)
        self.btn_mc_scan.setStyleSheet(
            "QPushButton { background-color: #2d4a2d; color: #8bc34a; font-weight: bold;"
            " border-radius: 5px; border: 1px solid #4a7c4a; }"
            "QPushButton:hover { background-color: #3a5e3a; }"
            "QPushButton:disabled { background-color: #222; color: #484848; border-color:#333; }"
        )
        scan_layout.addWidget(self.btn_mc_scan)

        self.mc_scan_progress = QProgressBar()
        self.mc_scan_progress.setFixedHeight(6)
        self.mc_scan_progress.setTextVisible(False)
        self.mc_scan_progress.setStyleSheet(
            "QProgressBar { border:none; background:#333; border-radius:3px; }"
            "QProgressBar::chunk { background:#8bc34a; border-radius:3px; }"
        )
        self.mc_scan_progress.setVisible(False)
        scan_layout.addWidget(self.mc_scan_progress)

        # Scan filter row  (class = count)
        scan_filter_row = QHBoxLayout()
        scan_filter_row.setSpacing(6)
        self.mc_scan_class_combo = QComboBox()
        self.mc_scan_class_combo.addItem("Total")
        self.mc_scan_class_combo.setStyleSheet(_combo_style)
        self.mc_scan_count_input = QSpinBox()
        self.mc_scan_count_input.setRange(0, 9999)
        self.mc_scan_count_input.setValue(0)
        self.mc_scan_count_input.setFixedWidth(68)
        self.mc_scan_count_input.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.mc_scan_count_input.setStyleSheet(
            "QSpinBox { background:#2d2d2d; color:#ccc; border:1px solid #444;"
            " border-radius:3px; padding:1px 4px; font-size:10pt; }"
            "QSpinBox::up-button, QSpinBox::down-button { width:0; border:none; }"
        )
        scan_filter_row.addWidget(self.mc_scan_class_combo, stretch=1)
        scan_filter_row.addWidget(QLabel("="))
        scan_filter_row.addWidget(self.mc_scan_count_input)
        scan_layout.addLayout(scan_filter_row)

        self.mc_scan_list = QListWidget()
        self.mc_scan_list.setStyleSheet(
            "QListWidget { background:#1e1e1e; color:#ccc; border:1px solid #333; outline:none; }"
            "QListWidget::item:selected { background:#2a2a2a; color:white;"
            " border-left:3px solid #2e7d32; outline:none; }"
            "QListWidget::item:selected:!active { background:#2a2a2a; color:white;"
            " border-left:3px solid #2e7d32; }"
        )
        scan_layout.addWidget(self.mc_scan_list, stretch=1)

        _scan_action_style = (
            "QPushButton { background:#2d2d2d; color:#ccc; border:1px solid #444;"
            " border-radius:3px; font-size:10pt; }"
            "QPushButton:hover { background:#3a3a3a; }"
            "QPushButton:disabled { color:#484848; border-color:#333; background:#222; }"
        )
        scan_action_row = QHBoxLayout()
        scan_action_row.setSpacing(4)
        self.btn_mc_chart = QPushButton("📈 Chart")
        self.btn_mc_chart.setFixedHeight(28)
        self.btn_mc_chart.setEnabled(False)
        self.btn_mc_chart.setStyleSheet(_scan_action_style)
        self.btn_mc_export = QPushButton("📊 Export")
        self.btn_mc_export.setFixedHeight(28)
        self.btn_mc_export.setEnabled(False)
        self.btn_mc_export.setStyleSheet(_scan_action_style)
        scan_action_row.addWidget(self.btn_mc_chart)
        scan_action_row.addWidget(self.btn_mc_export)
        scan_layout.addLayout(scan_action_row)

        self.mc_mode_stack.addWidget(page_scan)   # index 1

        self.btn_mc_export_video = QPushButton("🎬 Export Annotated Video")
        self.btn_mc_export_video.setFixedHeight(36)
        self.btn_mc_export_video.setEnabled(False)
        self.btn_mc_export_video.setStyleSheet(
            "QPushButton { background:#1a3a2a; color:#80cbc4; font-weight:bold;"
            " border-radius:5px; border:1px solid #2e7d62; }"
            "QPushButton:hover { background:#1e4d38; }"
            "QPushButton:disabled { background:#222; color:#484848; border-color:#333; }"
        )
        self.mc_export_progress = QProgressBar()
        self.mc_export_progress.setFixedHeight(6)
        self.mc_export_progress.setTextVisible(False)
        self.mc_export_progress.setStyleSheet(
            "QProgressBar { border:none; background:#333; border-radius:3px; }"
            "QProgressBar::chunk { background:#80cbc4; border-radius:3px; }"
        )
        self.mc_export_progress.setVisible(False)

        mc_layout.addWidget(self.btn_mc_open_video)
        mc_layout.addWidget(self.lbl_mc_video_info)
        mc_layout.addWidget(sep_a)
        mc_layout.addWidget(self.btn_mc_load_model)
        mc_layout.addWidget(self.lbl_mc_model_info)
        mc_layout.addWidget(self.btn_mc_export_video)
        mc_layout.addWidget(self.mc_export_progress)
        mc_layout.addWidget(sep_b)
        mc_layout.addWidget(self.mc_mode_stack, stretch=1)

        self.bottom_left_stack.addWidget(page_files)   # index 0
        self.bottom_left_stack.addWidget(page_check)   # index 1
        self.bottom_left_stack.addWidget(page_video)   # index 2
        self.bottom_left_stack.addWidget(page_mc)      # index 3

        self.left_bar.addWidget(self.btn_img_dir)
        self.left_bar.addWidget(self.lbl_img_path)
        self.left_bar.addSpacing(10)
        self.left_bar.addWidget(self.btn_save_dir)
        self.left_bar.addWidget(self.lbl_save_path)
        self.left_bar.addSpacing(10)
        self.left_bar.addWidget(self.btn_export_dataset)
        self.left_bar.addSpacing(6)
        self.left_bar.addWidget(self.btn_auto_annotate)
        self.left_bar.addSpacing(10)
        self.left_bar.addWidget(self.bottom_left_stack, stretch=2)

        # ── Toolbar (above canvas) ────────────────────────────────────────
        _mode_style = (
            "QPushButton { border:1px solid #555; border-radius:4px; color:#ccc;"
            " padding:4px 10px; background:#2d2d2d; }"
            "QPushButton:checked { background:#1565c0; color:white; font-weight:bold; border-color:#1565c0; }"
            "QPushButton:hover:!checked { background:#3a3a3a; }"
            "QPushButton:disabled { color:#484848; border-color:#333; background:#222; }"
        )
        _draw_style = (
            "QPushButton { border:1px solid #555; border-radius:4px; color:#ccc;"
            " padding:4px 10px; background:#2d2d2d; }"
            "QPushButton:checked { background:#2980b9; color:white; font-weight:bold; border-color:#2980b9; }"
            "QPushButton:hover:!checked { background:#3a3a3a; }"
            "QPushButton:disabled { color:#484848; border-color:#333; background:#222; }"
        )
        _conv_style = (
            "QPushButton { border:1px solid #444; border-radius:4px; color:#aaa;"
            " padding:4px 8px; font-size:10pt; background:#2d2d2d; }"
            "QPushButton:hover { background:#3a3a3a; color:#ddd; }"
        )
        _sep_style = "background:#444; max-width:1px; min-width:1px; margin:4px 6px;"

        self.toolbar_widget = QWidget()
        self.toolbar_widget.setFixedHeight(40)
        self.toolbar_widget.setStyleSheet("background-color: #252526; border-bottom: 1px solid #333;")
        toolbar_layout = QHBoxLayout(self.toolbar_widget)
        toolbar_layout.setContentsMargins(8, 4, 8, 4)
        toolbar_layout.setSpacing(4)

        # Annotation mode buttons (exclusive)
        self.btn_mode_det = QPushButton("⬛ Detection")
        self.btn_mode_seg = QPushButton("🔷 Segmentation")
        for btn in (self.btn_mode_det, self.btn_mode_seg):
            btn.setCheckable(True)
            btn.setFixedHeight(28)
            btn.setStyleSheet(_mode_style)
        self.btn_mode_det.setChecked(True)
        self._mode_group = QButtonGroup()
        self._mode_group.setExclusive(True)
        self._mode_group.addButton(self.btn_mode_det, 0)
        self._mode_group.addButton(self.btn_mode_seg, 1)

        sep1 = QWidget(); sep1.setStyleSheet(_sep_style)
        sep2 = QWidget(); sep2.setStyleSheet(_sep_style)

        # Draw tool buttons
        self.btn_draw_mode = QPushButton("✏️ Rect [W]")
        self.btn_draw_mode.setFixedHeight(28)
        self.btn_draw_mode.setStyleSheet(_draw_style)
        self.btn_draw_mode.setToolTip("Toggle rectangle draw mode (W)")
        self.btn_polygon_mode = QPushButton("🔷 Polygon [P]")
        self.btn_polygon_mode.setFixedHeight(28)
        self.btn_polygon_mode.setStyleSheet(_draw_style)
        self.btn_polygon_mode.setToolTip(
            "Toggle polygon draw mode (P) — click to add vertices, double-click to finish, Esc to cancel"
        )

        # Convert buttons
        self.btn_convert_to_seg = QPushButton("→ to Seg")
        self.btn_convert_to_det = QPushButton("→ to Det")
        for btn in (self.btn_convert_to_seg, self.btn_convert_to_det):
            btn.setFixedHeight(28)
            btn.setStyleSheet(_conv_style)
        self.btn_convert_to_seg.setToolTip("Convert all bbox labels → 4-point polygon (lossless)")
        self.btn_convert_to_det.setToolTip("Convert all polygon labels → bounding rect (lossy)")

        toolbar_layout.addWidget(self.btn_mode_det)
        toolbar_layout.addWidget(self.btn_mode_seg)
        toolbar_layout.addWidget(sep1)
        toolbar_layout.addWidget(self.btn_draw_mode)
        toolbar_layout.addWidget(self.btn_polygon_mode)
        toolbar_layout.addWidget(sep2)
        toolbar_layout.addWidget(self.btn_convert_to_seg)
        toolbar_layout.addWidget(self.btn_convert_to_det)
        toolbar_layout.addStretch()

        # ── Center: stacked (canvas | check gallery | video placeholder) ──
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

        # Video page: frame display + playback bar
        video_page = QWidget()
        video_page_layout = QVBoxLayout(video_page)
        video_page_layout.setContentsMargins(0, 0, 0, 0)
        video_page_layout.setSpacing(0)

        self.video_frame_label = QLabel()
        self.video_frame_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video_frame_label.setStyleSheet("background-color: #111;")
        self.video_frame_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)

        # Playback bar
        playback_bar = QWidget()
        playback_bar.setFixedHeight(44)
        playback_bar.setStyleSheet("background-color: #1e1e1e; border-top: 1px solid #333;")
        pb_layout = QHBoxLayout(playback_bar)
        pb_layout.setContentsMargins(8, 4, 8, 4)
        pb_layout.setSpacing(6)

        self.btn_video_prev    = QPushButton("⏮")
        self.btn_video_play    = QPushButton("▶  Play")
        self.btn_video_next    = QPushButton("⏭")
        self.video_scrubber    = QSlider(Qt.Orientation.Horizontal)
        self.video_frame_input = QLineEdit()
        self.lbl_video_counter = QLabel("0 / 0")

        self.video_frame_input.setFixedWidth(55)
        self.video_frame_input.setPlaceholderText("frame")
        self.video_frame_input.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.video_frame_input.setStyleSheet(
            "background:#2d2d2d; color:#ccc; border:1px solid #444;"
            " border-radius:3px; padding:1px 4px; font-size:10pt;")
        self.video_frame_input.setEnabled(False)

        self.lbl_video_counter.setStyleSheet("color: #aaa; font-size: 11px; min-width: 80px;")
        self.lbl_video_counter.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        for btn in (self.btn_video_prev, self.btn_video_play, self.btn_video_next):
            btn.setFixedHeight(30)
            btn.setEnabled(False)

        self.video_scrubber.setEnabled(False)
        self.video_scrubber.setStyleSheet(
            "QSlider::groove:horizontal { height:4px; background:#444; border-radius:2px; }"
            "QSlider::handle:horizontal { width:12px; height:12px; margin:-4px 0;"
            " background:#aaa; border-radius:6px; }"
            "QSlider::sub-page:horizontal { background:#2980b9; border-radius:2px; }"
        )

        pb_layout.addWidget(self.btn_video_prev)
        pb_layout.addWidget(self.btn_video_play)
        pb_layout.addWidget(self.btn_video_next)
        pb_layout.addWidget(self.video_scrubber, stretch=1)
        pb_layout.addWidget(self.video_frame_input)
        pb_layout.addWidget(self.lbl_video_counter)

        video_page_layout.addWidget(self.video_frame_label, stretch=1)
        video_page_layout.addWidget(playback_bar)

        # Model Check center page (index 3)
        mc_page = QWidget()
        mc_page_layout = QVBoxLayout(mc_page)
        mc_page_layout.setContentsMargins(0, 0, 0, 0)
        mc_page_layout.setSpacing(0)

        self.mc_frame_label = VideoFrameLabel()
        self.mc_frame_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.mc_frame_label.setStyleSheet("background-color: #111;")
        self.mc_frame_label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)

        mc_playback_bar = QWidget()
        mc_playback_bar.setFixedHeight(44)
        mc_playback_bar.setStyleSheet("background-color: #1e1e1e; border-top: 1px solid #333;")
        mc_pb_layout = QHBoxLayout(mc_playback_bar)
        mc_pb_layout.setContentsMargins(8, 4, 8, 4)
        mc_pb_layout.setSpacing(6)

        self.btn_mc_prev    = QPushButton("⏮")
        self.btn_mc_play    = QPushButton("▶  Play")
        self.btn_mc_next    = QPushButton("⏭")
        self.mc_scrubber    = QSlider(Qt.Orientation.Horizontal)
        self.mc_frame_input = QLineEdit()
        self.lbl_mc_counter = QLabel("0 / 0")

        self.mc_frame_input.setFixedWidth(55)
        self.mc_frame_input.setPlaceholderText("frame")
        self.mc_frame_input.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.mc_frame_input.setStyleSheet(
            "background:#2d2d2d; color:#ccc; border:1px solid #444;"
            " border-radius:3px; padding:1px 4px; font-size:10pt;")
        self.mc_frame_input.setEnabled(False)

        self.lbl_mc_counter.setStyleSheet("color: #aaa; font-size: 11px; min-width: 80px;")
        self.lbl_mc_counter.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)

        for btn in (self.btn_mc_prev, self.btn_mc_play, self.btn_mc_next):
            btn.setFixedHeight(30)
            btn.setEnabled(False)

        self.mc_scrubber.setEnabled(False)
        self.mc_scrubber.setStyleSheet(
            "QSlider::groove:horizontal { height:4px; background:#444; border-radius:2px; }"
            "QSlider::handle:horizontal { width:12px; height:12px; margin:-4px 0;"
            " background:#aaa; border-radius:6px; }"
            "QSlider::sub-page:horizontal { background:#2980b9; border-radius:2px; }"
        )

        mc_pb_layout.addWidget(self.btn_mc_prev)
        mc_pb_layout.addWidget(self.btn_mc_play)
        mc_pb_layout.addWidget(self.btn_mc_next)
        mc_pb_layout.addWidget(self.mc_scrubber, stretch=1)
        mc_pb_layout.addWidget(self.mc_frame_input)
        mc_pb_layout.addWidget(self.lbl_mc_counter)

        mc_page_layout.addWidget(self.mc_frame_label, stretch=1)
        mc_page_layout.addWidget(mc_playback_bar)

        self.center_stack = QStackedWidget()
        self.center_stack.addWidget(self.canvas)      # index 0
        self.center_stack.addWidget(self.check_view)  # index 1
        self.center_stack.addWidget(video_page)       # index 2
        self.center_stack.addWidget(mc_page)          # index 3

        # ── Right panel ───────────────────────────────────────────────────
        self.right_bar = QVBoxLayout()

        self.right_bar.addWidget(QLabel("Shapes (Delete to remove):"))
        self.shape_list = QListWidget()
        self.right_bar.addWidget(self.shape_list, stretch=1)

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

        # ── Model Check toolbar ────────────────────────────────────────────────
        self.mc_toolbar_widget = QWidget()
        self.mc_toolbar_widget.setFixedHeight(40)
        self.mc_toolbar_widget.setStyleSheet(
            "background-color: #252526; border-bottom: 1px solid #333;")
        mc_tl = QHBoxLayout(self.mc_toolbar_widget)
        mc_tl.setContentsMargins(8, 4, 8, 4)
        mc_tl.setSpacing(4)
        mc_tl.addWidget(self.btn_mc_mode_frame)
        mc_tl.addWidget(self.btn_mc_mode_scan)
        _mc_vs = QWidget(); _mc_vs.setStyleSheet(_sep_style)
        mc_tl.addWidget(_mc_vs)
        mc_tl.addWidget(QLabel("Conf:"))
        mc_tl.addWidget(self.mc_conf_spin)
        mc_tl.addStretch()
        self.mc_toolbar_widget.setVisible(False)

        # Wrap toolbar + center_stack in a single vertical container
        center_container = QWidget()
        center_vbox = QVBoxLayout(center_container)
        center_vbox.setContentsMargins(0, 0, 0, 0)
        center_vbox.setSpacing(0)
        center_vbox.addWidget(self.toolbar_widget)
        center_vbox.addWidget(self.mc_toolbar_widget)
        center_vbox.addWidget(self.center_stack)

        # Compose
        self.main_layout.addWidget(nav_widget)
        self.main_layout.addWidget(left_widget, stretch=1)
        self.main_layout.addWidget(center_container, stretch=4)

        self.right_widget = QWidget()
        self.right_widget.setLayout(self.right_bar)
        self.main_layout.addWidget(self.right_widget, stretch=1)

        MainWindow.setCentralWidget(self.central_widget)
