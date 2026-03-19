"""Shared utilities for parsing Ultralytics YOLO inference results."""


def parse_result_detections(result, model_names: dict) -> list:
    """Parse an Ultralytics result into a list of detection dicts.

    Each dict contains:
        class_idx  (int)   — model class index
        class_name (str)   — human-readable class name
        conf       (float) — confidence score
        shape              — list of (x, y) tuples for masks,
                             or (cx, cy, w, h) tuple for bounding boxes

    Used by ModelCheckController to build the detection sidebar and overlay.
    """
    detections = []
    if result.masks is not None:
        for i, mask in enumerate(result.masks):
            cls_idx  = int(result.boxes.cls[i].item())
            conf_val = float(result.boxes.conf[i].item())
            pts = [(float(x), float(y)) for x, y in mask.xyn[0]]
            detections.append({
                'class_idx':  cls_idx,
                'class_name': model_names.get(cls_idx, str(cls_idx)),
                'conf':       conf_val,
                'shape':      pts,
            })
    elif result.boxes is not None:
        for box in result.boxes:
            cls_idx  = int(box.cls[0].item())
            conf_val = float(box.conf[0].item())
            cx, cy, nw, nh = box.xywhn[0].tolist()
            detections.append({
                'class_idx':  cls_idx,
                'class_name': model_names.get(cls_idx, str(cls_idx)),
                'conf':       conf_val,
                'shape':      (cx, cy, nw, nh),
            })
    return detections


def parse_result_shapes(result, annotation_mode: str) -> tuple:
    """Parse an Ultralytics result into (shapes, class_indices) for saving.

    annotation_mode — 'segmentation' or 'detection'
    Returns (shapes, shape_classes) suitable for io_labels.save_yolo().

    Used by AnnotateWorker to write YOLO label files.
    """
    shapes, shape_classes = [], []
    if annotation_mode == 'segmentation' and result.masks is not None:
        for i, mask in enumerate(result.masks):
            cls_idx = int(result.boxes.cls[i].item())
            pts = [(float(x), float(y)) for x, y in mask.xyn[0]]
            if len(pts) >= 3:
                shapes.append(pts)
                shape_classes.append(cls_idx)
    elif result.boxes is not None:
        for box in result.boxes:
            cls_idx = int(box.cls[0].item())
            cx, cy, nw, nh = box.xywhn[0].tolist()
            if nw > 0 and nh > 0:
                shapes.append((cx, cy, nw, nh))
                shape_classes.append(cls_idx)
    return shapes, shape_classes
