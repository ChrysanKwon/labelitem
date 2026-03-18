"""
Label I/O: YOLO read/write, COCO export.

Coordinate conversion:
  Canvas boxes are stored in widget display coordinates.
  Before saving they must be converted to original image pixel coords,
  then to YOLO normalized (0-1).

  widget -> image pixel:
    img_x = (widget_x - display_rect.x()) / scale_x
    img_y = (widget_y - display_rect.y()) / scale_y
    (scale_x = display_rect.width()  / orig_w)
    (scale_y = display_rect.height() / orig_h)

  image pixel -> YOLO:
    cx = (img_x + img_w/2) / orig_w
    cy = (img_y + img_h/2) / orig_h
    nw = img_w / orig_w
    nh = img_h / orig_h
"""
import json
import os
from PySide6.QtCore import QRect, QSize
from PySide6.QtGui import QImageReader


def _widget_rect_to_image(rect: QRect, display_rect: QRect, orig_size: QSize) -> tuple:
    """Return (img_x, img_y, img_w, img_h) in original image pixel coords (float)."""
    if display_rect.width() == 0 or display_rect.height() == 0:
        return 0, 0, 0, 0
    scale_x = orig_size.width()  / display_rect.width()
    scale_y = orig_size.height() / display_rect.height()
    img_x = (rect.x() - display_rect.x()) * scale_x
    img_y = (rect.y() - display_rect.y()) * scale_y
    img_w = rect.width()  * scale_x
    img_h = rect.height() * scale_y
    return img_x, img_y, img_w, img_h


def _image_rect_to_widget(img_x, img_y, img_w, img_h,
                           display_rect: QRect, orig_size: QSize) -> QRect:
    """Convert original image pixel coords to a widget QRect."""
    if orig_size.width() == 0 or orig_size.height() == 0:
        return QRect()
    scale_x = display_rect.width()  / orig_size.width()
    scale_y = display_rect.height() / orig_size.height()
    wx = int(img_x * scale_x + display_rect.x())
    wy = int(img_y * scale_y + display_rect.y())
    ww = int(img_w * scale_x)
    wh = int(img_h * scale_y)
    return QRect(wx, wy, ww, wh)


def save_yolo(txt_path: str, shapes: list, shape_classes: list) -> None:
    """Save shapes to a YOLO .txt file.
    shapes items can be (cx,cy,nw,nh) tuples (detection) or [(x,y),...] lists (segmentation).
    """
    lines = []
    for shape, cls_idx in zip(shapes, shape_classes):
        if cls_idx < 0:   # unassigned — never write to file
            continue
        c = cls_idx
        if isinstance(shape, list):   # polygon segmentation
            pts_str = " ".join(f"{x:.6f} {y:.6f}" for x, y in shape)
            lines.append(f"{c} {pts_str}")
        else:                          # bbox detection
            cx, cy, nw, nh = shape
            lines.append(f"{c} {cx:.6f} {cy:.6f} {nw:.6f} {nh:.6f}")
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def load_yolo(txt_path: str, mode: str = 'detection') -> tuple[list, list]:
    """Load a YOLO .txt file filtered by mode.
    mode='detection'    → returns only 5-field bbox lines as (cx,cy,nw,nh) tuples.
    mode='segmentation' → returns only polygon lines as [(x1,y1),(x2,y2),...] lists.
    """
    if not os.path.exists(txt_path):
        return [], []
    shapes = []
    shape_classes = []
    with open(txt_path, "r", encoding="utf-8") as f:
        for line in f:
            parts = line.strip().split()
            if not parts:
                continue
            if mode == 'detection' and len(parts) == 5:
                cls_idx = int(parts[0])
                cx, cy, nw, nh = float(parts[1]), float(parts[2]), float(parts[3]), float(parts[4])
                if nw > 0 and nh > 0:
                    shapes.append((cx, cy, nw, nh))
                    shape_classes.append(cls_idx)
            elif mode == 'segmentation' and len(parts) >= 7 and len(parts) % 2 == 1:
                cls_idx = int(parts[0])
                pts = [(float(parts[i]), float(parts[i + 1]))
                       for i in range(1, len(parts), 2)]
                shapes.append(pts)
                shape_classes.append(cls_idx)
    return shapes, shape_classes


def scan_label_format(label_dir: str) -> str:
    """Scan all .txt label files in label_dir.
    Returns:
      'detection'   — all labeled files contain only bbox lines
      'segmentation'— all labeled files contain only polygon lines
      'mixed'       — some files are bbox, others are polygon (cross-file)
      'corrupted'   — at least one file contains both bbox and polygon lines
      'empty'       — no labeled files found
    """
    has_det_files = False
    has_seg_files = False
    for fname in os.listdir(label_dir):
        if not fname.endswith('.txt') or fname == 'classes.txt':
            continue
        file_has_det = False
        file_has_seg = False
        try:
            with open(os.path.join(label_dir, fname), 'r', encoding='utf-8') as f:
                for line in f:
                    parts = line.strip().split()
                    if not parts:
                        continue
                    if len(parts) == 5:
                        file_has_det = True
                    elif len(parts) >= 7 and len(parts) % 2 == 1:
                        file_has_seg = True
                    if file_has_det and file_has_seg:
                        return 'corrupted'
        except OSError:
            continue
        if file_has_det:
            has_det_files = True
        if file_has_seg:
            has_seg_files = True
        if has_det_files and has_seg_files:
            return 'mixed'
    if has_det_files:
        return 'detection'
    if has_seg_files:
        return 'segmentation'
    return 'empty'


def convert_det_to_seg(label_dir: str) -> int:
    """Convert all detection bbox labels to 4-point polygon segmentation format.
    Lossless: rectangle corners become the 4 polygon vertices.
    Returns number of boxes converted.
    Raises ValueError if mixed bbox+polygon labels are detected.
    """
    fmt = scan_label_format(label_dir)
    if fmt == 'corrupted':
        raise ValueError(
            "One or more label files contain both bbox and polygon lines in the same file.\n"
            "Please fix these files manually before converting."
        )
    count = 0
    for fname in os.listdir(label_dir):
        if not fname.endswith('.txt') or fname == 'classes.txt':
            continue
        path = os.path.join(label_dir, fname)
        lines_out = []
        modified = False
        try:
            with open(path, 'r', encoding='utf-8') as f:
                for line in f:
                    parts = line.strip().split()
                    if len(parts) == 5:
                        c = int(parts[0])
                        cx, cy, nw, nh = (float(parts[1]), float(parts[2]),
                                          float(parts[3]), float(parts[4]))
                        x1, y1 = cx - nw / 2, cy - nh / 2
                        x2, y2 = cx + nw / 2, cy + nh / 2
                        lines_out.append(
                            f"{c} {x1:.6f} {y1:.6f} {x2:.6f} {y1:.6f}"
                            f" {x2:.6f} {y2:.6f} {x1:.6f} {y2:.6f}")
                        count += 1
                        modified = True
                    elif parts:
                        lines_out.append(line.strip())
        except (OSError, ValueError):
            continue
        if modified:
            with open(path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(lines_out))
    return count


def convert_seg_to_det(label_dir: str) -> int:
    """Convert all polygon segmentation labels to detection bbox (bounding rect).
    Lossy: polygon shape information is lost.
    Returns number of polygons converted.
    Raises ValueError if mixed bbox+polygon labels are detected.
    """
    fmt = scan_label_format(label_dir)
    if fmt == 'corrupted':
        raise ValueError(
            "One or more label files contain both bbox and polygon lines in the same file.\n"
            "Please fix these files manually before converting."
        )
    count = 0
    for fname in os.listdir(label_dir):
        if not fname.endswith('.txt') or fname == 'classes.txt':
            continue
        path = os.path.join(label_dir, fname)
        lines_out = []
        modified = False
        try:
            with open(path, 'r', encoding='utf-8') as f:
                for line in f:
                    parts = line.strip().split()
                    if len(parts) >= 7 and len(parts) % 2 == 1:
                        c = int(parts[0])
                        xs = [float(parts[i]) for i in range(1, len(parts), 2)]
                        ys = [float(parts[i]) for i in range(2, len(parts), 2)]
                        x1, y1 = min(xs), min(ys)
                        x2, y2 = max(xs), max(ys)
                        cx = (x1 + x2) / 2
                        cy = (y1 + y2) / 2
                        nw = x2 - x1
                        nh = y2 - y1
                        lines_out.append(f"{c} {cx:.6f} {cy:.6f} {nw:.6f} {nh:.6f}")
                        count += 1
                        modified = True
                    elif parts:
                        lines_out.append(line.strip())
        except (OSError, ValueError):
            continue
        if modified:
            with open(path, 'w', encoding='utf-8') as f:
                f.write('\n'.join(lines_out))
    return count


def export_yolo_dataset(image_dir: str, label_dir: str, class_names: list,
                        output_dir: str, train_ratio: float = 0.8,
                        seed: int = 42) -> tuple[int, int]:
    """
    Split ALL images in image_dir into train/val sets and write a YOLO dataset:
      output_dir/train/images/  output_dir/train/labels/
      output_dir/val/images/    output_dir/val/labels/
      output_dir/classes.txt
    Unlabeled images are included without a .txt (treated as background by YOLO).
    Returns (n_train, n_val).
    """
    import random, shutil

    img_exts = {'.jpg', '.jpeg', '.png'}
    all_imgs = sorted(f for f in os.listdir(image_dir)
                      if os.path.splitext(f)[1].lower() in img_exts)

    rng = random.Random(seed)
    rng.shuffle(all_imgs)
    n_train = max(1, round(len(all_imgs) * train_ratio))
    train_set = all_imgs[:n_train]
    val_set   = all_imgs[n_train:]

    for split, files in (('train', train_set), ('val', val_set)):
        img_out = os.path.join(output_dir, split, 'images')
        lbl_out = os.path.join(output_dir, split, 'labels')
        os.makedirs(img_out, exist_ok=True)
        os.makedirs(lbl_out, exist_ok=True)
        for fname in files:
            shutil.copy2(os.path.join(image_dir, fname), os.path.join(img_out, fname))
            txt_name = os.path.splitext(fname)[0] + '.txt'
            txt_src  = os.path.join(label_dir, txt_name)
            if os.path.exists(txt_src):
                shutil.copy2(txt_src, os.path.join(lbl_out, txt_name))

    with open(os.path.join(output_dir, 'classes.txt'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(class_names))

    return len(train_set), len(val_set)


def export_coco_dataset(image_dir: str, label_dir: str, class_names: list,
                        output_dir: str, train_ratio: float = 0.8,
                        seed: int = 42) -> tuple[int, int]:
    """
    Split ALL images in image_dir into train/valid sets and write a COCO dataset:
      output_dir/train/  (images + _annotations.coco.json)
      output_dir/valid/  (images + _annotations.coco.json)
    Unlabeled images are included with no annotations in the JSON.
    Auto-detects detection (bbox) or segmentation (polygon) format from labels.
    Raises ValueError if both formats are present in the label folder.
    Returns (n_train, n_val).
    """
    import random, shutil

    fmt = scan_label_format(label_dir)
    if fmt == 'corrupted':
        raise ValueError(
            "One or more label files contain both bbox and polygon lines in the same file.\n"
            "Please fix these files manually before exporting."
        )
    if fmt == 'mixed':
        raise ValueError(
            "The label folder contains a mix of bbox-only and polygon-only files.\n"
            "Please convert everything to one format first (use → to Seg or → to Det)."
        )

    img_exts = {'.jpg', '.jpeg', '.png'}
    all_imgs = sorted(f for f in os.listdir(image_dir)
                      if os.path.splitext(f)[1].lower() in img_exts)

    rng = random.Random(seed)
    rng.shuffle(all_imgs)
    n_train = max(1, round(len(all_imgs) * train_ratio))
    train_set = all_imgs[:n_train]
    val_set   = all_imgs[n_train:]

    categories = [{'id': i, 'name': name, 'supercategory': ''}
                  for i, name in enumerate(class_names)]

    for split_name, files in (('train', train_set), ('valid', val_set)):
        split_dir = os.path.join(output_dir, split_name)
        os.makedirs(split_dir, exist_ok=True)

        images, annotations = [], []
        ann_id = 1
        for img_id, fname in enumerate(files, start=1):
            shutil.copy2(os.path.join(image_dir, fname), os.path.join(split_dir, fname))
            reader = QImageReader(os.path.join(image_dir, fname))
            size = reader.size()
            if not size.isValid():
                continue
            iw, ih = size.width(), size.height()
            images.append({'id': img_id, 'file_name': fname, 'width': iw, 'height': ih})

            txt_path = os.path.join(label_dir, os.path.splitext(fname)[0] + '.txt')
            if not os.path.exists(txt_path):
                continue

            with open(txt_path, 'r', encoding='utf-8') as f:
                for line in f:
                    parts = line.strip().split()
                    if not parts:
                        continue

                    if fmt == 'segmentation' and len(parts) >= 7 and len(parts) % 2 == 1:
                        cls_idx = int(parts[0])
                        xs = [float(parts[i]) * iw for i in range(1, len(parts), 2)]
                        ys = [float(parts[i]) * ih for i in range(2, len(parts), 2)]
                        seg = [round(v, 2) for pair in zip(xs, ys) for v in pair]
                        x = round(min(xs), 2)
                        y = round(min(ys), 2)
                        w = round(max(xs) - min(xs), 2)
                        h = round(max(ys) - min(ys), 2)
                        annotations.append({
                            'id':           ann_id,
                            'image_id':     img_id,
                            'category_id':  cls_idx,
                            'segmentation': [seg],
                            'bbox':         [x, y, w, h],
                            'area':         round(w * h, 2),
                            'iscrowd':      0,
                        })
                        ann_id += 1

                    elif fmt == 'detection' and len(parts) == 5:
                        cls_idx = int(parts[0])
                        cx, cy, nw, nh = float(parts[1]), float(parts[2]), float(parts[3]), float(parts[4])
                        x = round((cx - nw / 2) * iw, 2)
                        y = round((cy - nh / 2) * ih, 2)
                        w = round(nw * iw, 2)
                        h = round(nh * ih, 2)
                        annotations.append({
                            'id':           ann_id,
                            'image_id':     img_id,
                            'category_id':  cls_idx,
                            'segmentation': [],
                            'bbox':         [x, y, w, h],
                            'area':         round(w * h, 2),
                            'iscrowd':      0,
                        })
                        ann_id += 1

        coco = {'images': images, 'annotations': annotations, 'categories': categories}
        json_path = os.path.join(split_dir, '_annotations.coco.json')
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(coco, f, ensure_ascii=False, indent=2)

    return len(train_set), len(val_set)
