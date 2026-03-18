# LabelItem

A lightweight YOLO image annotation tool built with PySide6. Supports both detection (bounding box) and segmentation (polygon) annotation, with Check Mode, Auto Annotate, and dataset export.

> Built as a hands-on experiment using Claude Code to develop a custom labeling solution from scratch.

---

## Features

### Annotation modes
- **Detection** — draw and resize bounding boxes with 8-handle precision editing; saved as YOLO `class cx cy w h`
- **Segmentation** — draw polygons by clicking vertices, double-click to finish; saved as YOLO `class x1 y1 x2 y2 …`
- Switch modes with the **Detection / Segmentation** buttons in the toolbar above the canvas
- Each mode only reads and writes its own format — the other format's lines are left untouched in the .txt file

### Drawing tools (toolbar)
- **Rect [W]** — toggle rectangle draw mode (only available in Detection mode)
- **Polygon [P]** — toggle polygon draw mode (only available in Segmentation mode)
- **→ to Seg** — batch-convert all bbox labels to 4-point polygons (lossless)
- **→ to Det** — batch-convert all polygon labels to bounding rects (lossy, double confirmation required)
- Both convert buttons block if a single .txt file contains mixed bbox+polygon lines

### Navigation
- **Label / Check / Video** — switch views using the nav column on the left
- Arrow keys or A/D to navigate between images (configurable in `app/config.json`)

### Check Mode
- Browse crops of a selected class across all images in a gallery view
- Label count per class shown in the sidebar — updates when switching annotation mode
- Double-click any crop to open a full editing dialog without leaving Check Mode

### Auto Annotate
- Run any Ultralytics YOLO model on the entire image directory in the background
- Choose output format (Detection or Segmentation) directly in the dialog — defaults to the current annotation mode
- Segmentation models write polygon masks; detection models write bboxes
- Processed in configurable batches (default 400 images) to keep memory stable
- Model class names are written to `classes.txt` automatically

### Export
- **YOLO format** — standard `images/` + `labels/` split with `classes.txt`
- **COCO format** — auto-detects bbox vs polygon from the label folder:
  - Detection labels → `bbox` field, empty `segmentation`
  - Segmentation labels → `segmentation` polygon + `bbox` bounding rect
  - Mixed folder (some files bbox, others polygon) → blocked with a warning

### Other
- **Unassigned shape warning** — if any shape has no class assigned when switching images, a dialog prompts to go back or skip (unassigned shapes are never saved to file)
- **Undo / Redo** — Ctrl+Z / Ctrl+Shift+Z, per-image history (50 steps)
- **Delete Image & Label** — removes image and .txt together with double confirmation (keyboard: Ctrl+Delete, or the button in the file list)
- **Session persistence** — remembers last image dir, label dir, and annotation mode across restarts
- **Safe-delete protection** — switching images in Segmentation mode will never delete detection labels that happen to be invisible in the current mode (and vice versa)

---

## Quick Start

### Requirements

```bash
pip install PySide6

# Optional — only needed for Auto Annotate
pip install ultralytics
```

### GPU Acceleration (optional)

Auto Annotate uses CPU by default. For NVIDIA GPU acceleration:

1. Check your CUDA version: `nvidia-smi`
2. Uninstall CPU PyTorch: `pip uninstall torch torchvision -y`
3. Install CUDA version from [pytorch.org](https://pytorch.org/get-started/locally/) — example for CUDA 12.4:
   ```bash
   pip install torch torchvision --index-url https://download.pytorch.org/whl/cu124
   ```

### Run

```bash
python main.py
```

---

## Hotkeys

| Action | Key |
|--------|-----|
| Previous image | `←` or `A` |
| Next image | `→` or `D` |
| Toggle rect draw (Detection) | `W` |
| Toggle polygon draw (Segmentation) | `P` |
| Delete selected shape | `Delete` / `Backspace` |
| Undo | `Ctrl+Z` |
| Redo | `Ctrl+Shift+Z` |
| Delete image & label | `Ctrl+Delete` |

> Navigation key scheme (`arrows` or `ad`) can be changed in `app/config.json` via the `nav_keys` setting.

---

## Project Structure

```
labelitem/
  main.py                      Entry point and main window controller
  app/
    ui_layout.py               Canvas widget (bbox + polygon drawing) and full UI layout
    io_labels.py               YOLO / COCO label I/O, format detection, dataset export
    config.py                  Session state and settings (reads/writes config.json)
    config.json                Persisted session data (gitignored)
    utils.py                   Shared UI helpers (shape label formatting, draw mode sync)
    check_mode.py              CheckModeController — all Check Mode logic
    check_edit_dialog.py       Per-image label editing dialog used from Check Mode
    export_dialog.py           Export dataset dialog (YOLO / COCO)
    auto_annotate_dialog.py    Auto-annotate settings dialog and QThread worker
```

---

## Notes

- **Label format isolation** — Detection mode only loads/saves 5-field lines; Segmentation mode only loads/saves odd-field (≥7) lines. Switching modes never silently overwrites the other format's data.
- **Mixed labels** — if a label folder has some files in bbox format and others in polygon format, Convert and COCO Export will warn and refuse to proceed. Use the convert buttons to unify the folder first.
- **Corrupted labels** — if a single .txt contains both bbox and polygon lines, Convert and Export will refuse with an error.
- **Unlabeled images** — included in dataset export; treated as background by YOLO trainers. A warning is shown before export.
- **Auto Annotate batch size** — default 400 images per batch. Reduce `annotate_batch_size` in `app/config.json` if it crashes.
- **Undo/Redo** — scoped to the current image; cleared on image switch.
- **Unassigned shapes** — shapes with no class assigned are never written to disk. Switching images while unassigned shapes exist triggers a warning; choose **Go Back** to assign them or **Skip & Discard** to proceed without saving them.
- **Check Mode** — label counts and gallery update when switching annotation mode mid-session.

---

## Roadmap

### Video Mode *(TODO)*

The Video tab in the nav column is a placeholder. Planned features:

1. **Random frame extraction** — specify a video file and N; the tool randomly samples N frames and copies them into the current image folder, ready for annotation
2. **Interactive frame capture** — load a video and play it through a scrubber; pause and capture the current frame to the image folder at any point

---

## License

This project uses [Ultralytics](https://github.com/ultralytics/ultralytics) (AGPL-3.0) as an optional dependency for Auto Annotate. LabelItem itself is for personal/open-source use.
