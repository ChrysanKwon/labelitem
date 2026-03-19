# LabelItem

A lightweight YOLO image annotation tool built with PySide6. Supports both detection (bounding box) and segmentation (polygon) annotation, with Check Mode, Auto Annotate, Video Capture, Model Check, and dataset export.

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
- **Image Label / Image Check / Video Capture / Model Check** — switch views using the nav column on the left
- Arrow keys (← →) or A/D to navigate between images in Image Label mode (configurable in `app/config.json`)
- Arrow keys also step frames one at a time in Video Capture and Model Check modes

### Image Check
- Browse crops of a selected class across all images in a gallery view
- Label count per class shown in the sidebar — updates when switching annotation mode
- Double-click any crop to open a full editing dialog without leaving Image Check

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
- **Exclude images without labels** — optional checkbox to skip unlabeled images from the export

### Video Capture
- Load a video and scrub through it using a playback bar (⏮ ⏯ ⏭ + slider)
- Type a frame number directly in the input box next to the counter and press Enter to jump to that frame
- **Capture Frame** — save the current frame as a JPEG to the image folder; the file is immediately added to the file list
- **Extract Frames…** — batch-extract N frames by evenly spaced or random sampling into the image folder

### Model Check
- Load a video + any Ultralytics `.pt` model to review inference results frame by frame
- Scrub to any frame; inference fires automatically 400 ms after scrubbing stops
- Inference runs once per frame at conf=0.01 and caches all detections — adjusting the **Conf:** spinner re-filters the cache instantly without re-running the model
- **Class filter** — dropdown above the detection list to show only one class at a time
- Detected objects listed in the sidebar with class name and confidence score
- Type a frame number in the input box next to the counter and press Enter to jump directly to that frame
- **Delete Selected** — remove a false positive from the list; the overlay redraws instantly
- **Capture + Save Labels** — saves the frame as JPEG and writes the remaining (corrected) detections as a YOLO `.txt` label, both ready for further annotation in Image Label mode
- Supports both detection models (bounding boxes) and segmentation models (polygon masks)
- Model and video file dialogs track their own last-used directories independently

### Image Label — other features
- **Unassigned shape warning** — if any shape has no class assigned when switching images, a dialog prompts to go back or skip (unassigned shapes are never saved to file)
- **Undo / Redo** — Ctrl+Z / Ctrl+Shift+Z, per-image history (50 steps)
- **Delete Image & Label** — removes image and .txt together with double confirmation (keyboard: Ctrl+Delete, or the button in the file list)
- **Clean Orphaned Labels** — scans the label directory for `.txt` files with no matching image and deletes them after confirmation; useful after manually removing images outside the app
- **Session persistence** — remembers last image dir, label dir, and annotation mode across restarts
- **Label dir auto-sync** — selecting an image directory automatically sets the label directory to the same folder. If you need a separate label folder, select it **after** setting the image directory. The setting is remembered across restarts.
- **Safe-delete protection** — switching images in Segmentation mode will never delete detection labels that happen to be invisible in the current mode (and vice versa)
- **Status bar** — bottom of the window shows save confirmations, inference results, and capture events

---

## Quick Start

### Requirements

```bash
pip install PySide6

# Optional — needed for Auto Annotate, Video Capture, and Model Check
pip install ultralytics opencv-python
```

### GPU Acceleration (optional)

Auto Annotate uses CPU by default. For NVIDIA GPU acceleration:

1. Check your CUDA version: `nvidia-smi`
2. Uninstall CPU PyTorch: `pip uninstall torch torchvision -y`
3. Install CUDA version from [pytorch.org](https://pytorch.org/get-started/locally/) — example for CUDA 12.4:
   ```bash
   pip install torch torchvision --index-url https://download.pytorch.org/whl/cu124
   ```

### Configuration (optional)

`app/config.json` is created automatically — no setup needed. Most settings are managed through the UI. Two values can be adjusted manually in the file if needed:

- `nav_keys` — `"arrows"` (← →, default) or `"ad"` (A D keys)
- `annotate_batch_size` — images per Auto Annotate batch (default `400`; reduce if it crashes)

See `app/config.example.json` for the full list of available keys.

### Run

```bash
python main.py
```

---

## Hotkeys

| Action | Key | Mode |
|--------|-----|------|
| Previous image | `←` or `A` | Image Label |
| Next image | `→` or `D` | Image Label |
| Previous frame | `←` or `A` | Video Capture / Model Check |
| Next frame | `→` or `D` | Video Capture / Model Check |
| Toggle rect draw | `W` | Image Label (Detection) |
| Toggle polygon draw | `P` | Image Label (Segmentation) |
| Delete selected shape | `Delete` / `Backspace` | Image Label |
| Undo | `Ctrl+Z` | Image Label |
| Redo | `Ctrl+Shift+Z` | Image Label |
| Delete image & label | `Ctrl+Delete` | Image Label |

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
    check_mode.py              CheckModeController — all Image Check logic
    check_edit_dialog.py       Per-image label editing dialog used from Image Check
    export_dialog.py           Export dataset dialog (YOLO / COCO)
    auto_annotate_dialog.py    Auto-annotate settings dialog and QThread worker
    video_mode.py              VideoModeController — Video Capture playback and frame extraction
    frame_extract_dialog.py    Batch frame extraction dialog (evenly spaced / random)
    model_check.py             ModelCheckController — inference overlay, false positive removal
    video_utils.py             Shared video open + BGR→QPixmap helpers
    video_playback_base.py     Shared base class for video playback controllers
    inference_utils.py         Shared YOLO result parsing (detections + shapes)
```

---

## Notes

- **Label format isolation** — Detection mode only loads/saves 5-field lines; Segmentation mode only loads/saves odd-field (≥7) lines. Switching modes never silently overwrites the other format's data.
- **Mixed labels** — if a label folder has some files in bbox format and others in polygon format, Convert and COCO Export will warn and refuse to proceed. Use the convert buttons to unify the folder first.
- **Corrupted labels** — if a single .txt contains both bbox and polygon lines, Convert and Export will refuse with an error.
- **Unlabeled images** — included in dataset export by default; treated as background by YOLO trainers. A warning is shown before export, and an option to exclude them is available in the Export dialog.
- **Auto Annotate batch size** — default 400 images per batch. Reduce `annotate_batch_size` in `app/config.json` if it crashes.
- **Undo/Redo** — scoped to the current image; cleared on image switch.
- **Unassigned shapes** — shapes with no class assigned are never written to disk. Switching images while unassigned shapes exist triggers a warning; choose **Go Back** to assign them or **Skip & Discard** to proceed without saving them.
- **Image Check** — label counts and gallery update when switching annotation mode mid-session.
- **Model Check labels** — captured frames are saved to the image folder; corresponding `.txt` labels (with deleted detections excluded) are saved to the label folder. Both are immediately visible in Image Label mode.
- **Orphaned labels** — `.txt` files whose image has been deleted outside the app accumulate silently. Use **Clean Orphaned Labels** in the file list panel to find and remove them. Export already ignores orphaned labels automatically.

---

## License

This project uses [Ultralytics](https://github.com/ultralytics/ultralytics) (AGPL-3.0) as an optional dependency for Auto Annotate. LabelItem itself is for personal/open-source use.
