"""Shared UI helpers used by multiple modules."""


def format_shape_label(shape, cls_idx: int,
                       class_names: list, original_size=None) -> str:
    """Return a human-readable string for a bbox or polygon shape.

    Parameters
    ----------
    shape        : (cx, cy, nw, nh) tuple for bbox, or [(x,y),...] list for polygon
    cls_idx      : class index (-1 = unassigned)
    class_names  : list[str]
    original_size: QSize or None — when provided, show pixel coordinates
    """
    cls_name = (class_names[cls_idx]
                if 0 <= cls_idx < len(class_names) else "unassigned")
    if isinstance(shape, list):   # polygon
        n = len(shape)
        if original_size:
            iw, ih = original_size.width(), original_size.height()
            xs = [round(x * iw) for x, _ in shape]
            ys = [round(y * ih) for _, y in shape]
            w = max(xs) - min(xs)
            h = max(ys) - min(ys)
            return f"[{cls_name}] poly({n}pts) {w}×{h}px"
        return f"[{cls_name}] poly({n}pts)"
    else:                          # bbox
        cx, cy, nw, nh = shape
        if original_size:
            iw = original_size.width()
            ih = original_size.height()
            x = round((cx - nw / 2) * iw)
            y = round((cy - nh / 2) * ih)
            w = round(nw * iw)
            h = round(nh * ih)
            return f"[{cls_name}] {x},{y} {w}×{h}"
        return f"[{cls_name}] {cx:.3f},{cy:.3f}"


def apply_draw_mode(canvas, button, enabled: bool, polygon: bool = False) -> None:
    """Sync canvas draw/polygon mode and update the button's visual state.

    Parameters
    ----------
    canvas  : Canvas widget
    button  : QPushButton
    enabled : desired mode state
    polygon : if True, controls polygon_mode; otherwise controls draw_mode
    """
    if polygon:
        canvas.polygon_mode = enabled
    else:
        canvas.draw_mode = enabled
    if enabled:
        button.setStyleSheet(
            "background-color: #2980b9; color: white; font-weight: bold;")
    else:
        button.setStyleSheet("")
    canvas._update_cursor(canvas.mapFromGlobal(canvas.cursor().pos()))
