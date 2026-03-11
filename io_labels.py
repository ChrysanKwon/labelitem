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
    """Save shapes (list of YOLO (cx,cy,nw,nh) tuples) to a YOLO .txt file."""
    lines = []
    for (cx, cy, nw, nh), cls_idx in zip(shapes, shape_classes):
        cls_idx = max(0, cls_idx)  # unassigned (-1) defaults to class 0
        lines.append(f"{cls_idx} {cx:.6f} {cy:.6f} {nw:.6f} {nh:.6f}")
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


def load_yolo(txt_path: str) -> tuple[list, list]:
    """Load a YOLO .txt file. Returns (shapes, shape_classes) where shapes is a
    list of (cx, cy, nw, nh) normalized tuples — the exact values from the file."""
    if not os.path.exists(txt_path):
        return [], []
    shapes = []
    shape_classes = []
    with open(txt_path, "r", encoding="utf-8") as f:
        for line in f:
            parts = line.strip().split()
            if len(parts) != 5:
                continue
            cls_idx = int(parts[0])
            cx, cy, nw, nh = float(parts[1]), float(parts[2]), float(parts[3]), float(parts[4])
            if nw > 0 and nh > 0:
                shapes.append((cx, cy, nw, nh))
                shape_classes.append(cls_idx)
    return shapes, shape_classes


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
                    if len(parts) != 5:
                        continue
                    cls_idx = int(parts[0])
                    cx, cy, nw, nh = float(parts[1]), float(parts[2]), float(parts[3]), float(parts[4])
                    x = round((cx - nw / 2) * iw, 2)
                    y = round((cy - nh / 2) * ih, 2)
                    w = round(nw * iw, 2)
                    h = round(nh * ih, 2)
                    annotations.append({
                        'id':          ann_id,
                        'image_id':    img_id,
                        'category_id': cls_idx,
                        'bbox':        [x, y, w, h],
                        'area':        round(w * h, 2),
                        'iscrowd':     0,
                    })
                    ann_id += 1

        coco = {'images': images, 'annotations': annotations, 'categories': categories}
        json_path = os.path.join(split_dir, '_annotations.coco.json')
        with open(json_path, 'w', encoding='utf-8') as f:
            json.dump(coco, f, ensure_ascii=False, indent=2)

    return len(train_set), len(val_set)


def export_coco(image_dir: str, label_dir: str,
                class_names: list[str], output_path: str) -> int:
    """
    Read all .txt files under label_dir and write a COCO JSON to output_path.
    Returns the total number of annotations.
    Uses QImageReader to get image dimensions without loading the full image.
    """
    img_exts = {".jpg", ".jpeg", ".png"}
    images = []
    annotations = []
    categories = [{"id": i, "name": name, "supercategory": ""}
                  for i, name in enumerate(class_names)]

    ann_id = 1
    img_id = 1

    for fname in sorted(os.listdir(image_dir)):
        if os.path.splitext(fname)[1].lower() not in img_exts:
            continue

        img_path = os.path.join(image_dir, fname)
        reader = QImageReader(img_path)
        size = reader.size()
        if not size.isValid():
            continue
        iw, ih = size.width(), size.height()

        images.append({"id": img_id, "file_name": fname, "width": iw, "height": ih})

        txt_name = os.path.splitext(fname)[0] + ".txt"
        txt_path = os.path.join(label_dir, txt_name)

        if os.path.exists(txt_path):
            with open(txt_path, "r", encoding="utf-8") as f:
                for line in f:
                    parts = line.strip().split()
                    if len(parts) != 5:
                        continue
                    cls_idx = int(parts[0])
                    cx, cy, nw, nh = float(parts[1]), float(parts[2]), float(parts[3]), float(parts[4])
                    x = round((cx - nw / 2) * iw, 2)
                    y = round((cy - nh / 2) * ih, 2)
                    w = round(nw * iw, 2)
                    h = round(nh * ih, 2)
                    annotations.append({
                        "id":          ann_id,
                        "image_id":    img_id,
                        "category_id": cls_idx,
                        "bbox":        [x, y, w, h],
                        "area":        round(w * h, 2),
                        "iscrowd":     0,
                    })
                    ann_id += 1

        img_id += 1

    coco = {"images": images, "annotations": annotations, "categories": categories}
    with open(output_path, "w", encoding="utf-8") as f:
        json.dump(coco, f, ensure_ascii=False, indent=2)

    return len(annotations)
