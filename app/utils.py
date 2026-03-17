"""Shared UI helpers used by multiple modules."""


def format_shape_label(shape: tuple, cls_idx: int,
                       class_names: list, original_size=None) -> str:
    """Return a human-readable string for a bounding box.

    Parameters
    ----------
    shape        : (cx, cy, nw, nh) YOLO normalised tuple
    cls_idx      : class index (-1 = unassigned)
    class_names  : list[str]
    original_size: QSize or None — when provided, show pixel coordinates
    """
    cx, cy, nw, nh = shape
    cls_name = (class_names[cls_idx]
                if 0 <= cls_idx < len(class_names) else "unassigned")
    if original_size:
        iw = original_size.width()
        ih = original_size.height()
        x = round((cx - nw / 2) * iw)
        y = round((cy - nh / 2) * ih)
        w = round(nw * iw)
        h = round(nh * ih)
        return f"[{cls_name}] {x},{y} {w}×{h}"
    return f"[{cls_name}] {cx:.3f},{cy:.3f}"


def apply_draw_mode(canvas, button, enabled: bool) -> None:
    """Sync canvas draw mode and update the button's visual state.

    Parameters
    ----------
    canvas  : Canvas widget
    button  : QPushButton (may or may not be checkable)
    enabled : desired draw mode state
    """
    canvas.draw_mode = enabled
    if enabled:
        button.setStyleSheet(
            "background-color: #2980b9; color: white; font-weight: bold;")
    else:
        button.setStyleSheet("")
    canvas._update_cursor(canvas.mapFromGlobal(canvas.cursor().pos()))
