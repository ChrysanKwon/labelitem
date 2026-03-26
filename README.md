# LabelItem

A lightweight YOLO image annotation tool built with PySide6. Supports detection (bounding box) and segmentation (polygon) annotation, with Label Review, Auto Annotate, Video Capture, and Model Check.

> Built as a hands-on experiment using Claude Code to develop a custom labeling solution from scratch.

---

## Features

**Image Label** — draw and resize bounding boxes (8 handles) or polygons; saved as YOLO `.txt`. Detection and Segmentation modes are isolated — switching modes never touches the other format's lines.

**Label Review** — browse crops by class in a gallery view; double-click to edit labels inline.

**Auto Annotate** — run any Ultralytics `.pt` model on the whole image dir in a background thread; writes Detection or Segmentation labels automatically.

**Export** — YOLO (`images/` + `labels/`) or COCO JSON; auto-detects bbox vs polygon. Option to exclude unlabeled images.

**Video Capture** — scrub a video, capture frames as JPEG, or batch-extract N frames (evenly spaced / random).

**Model Check** — load a video + YOLO model and review inference frame by frame.
- **Frame mode** — inference fires 400 ms after scrubbing stops; Conf spinner filters display only (no re-inference); delete false positives; capture frame + labels
- **Scan mode** — scan all frames in background; filter by class + count; jump to any result; line chart; export Excel; export annotated MP4
- **Playback cache** (Settings) — saves bbox results to `.mc_cache/` for overlay playback without re-running inference; cleared on close

---

## Quick Start

```bash
pip install PySide6

# For Auto Annotate, Video Capture, Model Check
pip install ultralytics opencv-python

# For Chart and Export Excel
pip install matplotlib openpyxl
```

**GPU acceleration** (optional): uninstall CPU torch and reinstall from [pytorch.org](https://pytorch.org/get-started/locally/) with your CUDA version.

```bash
python main.py
```

---

## Hotkeys

| Action | Key |
|--------|-----|
| Prev / Next image | `←` `→` or `A` `D` |
| Prev / Next frame | `←` `→` or `A` `D` |
| Toggle rect draw | `W` |
| Toggle polygon draw | `P` |
| Delete shape | `Delete` / `Backspace` |
| Undo / Redo | `Ctrl+Z` / `Ctrl+Shift+Z` |
| Delete image & label | `Ctrl+Delete` |

Key scheme (`arrows` / `ad`) configurable via `nav_keys` in `app/config.json`.

---

## Project Structure

```
labelitem/
  main.py                      Entry point, signal wiring, session management
  app/
    ui_layout.py               Canvas (bbox + polygon drawing) and UI layout
    label_mode.py              Image Label controller
    check_mode.py              Label Review controller
    video_mode.py              Video Capture controller
    model_check.py             Model Check controller (inference, scan, export)
    io_labels.py               YOLO / COCO label I/O and export
    config.py                  Session state (reads/writes config.json)
    check_edit_dialog.py       Inline label editing dialog
    export_dialog.py           Export dialog (YOLO / COCO)
    auto_annotate_dialog.py    Auto-annotate dialog and worker thread
    frame_extract_dialog.py    Batch frame extraction dialog
    settings_dialog.py         Settings dialog
    video_playback_base.py     Shared video playback base class
    video_utils.py             Video open + BGR→QPixmap helpers
    inference_utils.py         YOLO result parsing
    utils.py                   Shared UI helpers
```

---

## Notes

- **Label isolation** — Detection mode reads/writes 5-field lines only; Segmentation reads/writes polygon lines only. Mixed-format files block Convert and COCO Export.
- **Session** — remembers image dir, label dir, annotation mode, last image, last video, and last model.
- **Playback cache** — `.mc_cache/` deleted automatically on app close.
- **Developer** — set `DEBUG_MODE = True` in `main.py` to show a Restart button that saves session and relaunches.

---

## License

Uses [Ultralytics](https://github.com/ultralytics/ultralytics) (AGPL-3.0) as an optional dependency. LabelItem itself is for personal/open-source use.
