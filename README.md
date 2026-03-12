# LabelItem

A lightweight YOLO image annotation tool built with PySide6. Designed as a personal alternative to labelImg with a cleaner workflow and a few extra quality-of-life features.

> Built as a hands-on experiment using Claude Code to develop a custom labeling solution from scratch.

---

## Features

- **Draw & resize bounding boxes** with 8-handle precision editing
- **Zero coordinate drift** — labels are stored as YOLO normalized floats and never converted through pixel rounding on load/save
- **Check Mode** — browse all crops of a selected class across every image in a gallery view; double-click any crop to jump to that image in label mode
- **Auto Annotate** — run any Ultralytics YOLO model on your entire image directory in the background; model class names are written to `classes.txt` automatically
- **Export datasets** — YOLO and COCO format; all images are included (unlabeled images are treated as background during training)
- **Session persistence** — remembers last opened directory and class list across restarts

---

## Quick Start

### Requirements

```bash
pip install PySide6

# Optional — only needed for Auto Annotate
pip install ultralytics
```

### Run

```bash
python main.py
```

---

## Hotkeys

| Action | Key |
|---|---|
| Previous image | `A` or `←` |
| Next image | `D` or `→` |
| Delete selected box | `Delete` / `Backspace` |
| Confirm class assignment | `Enter` |

---

## Project Structure

```
labelitem/
  main.py          Entry point
  app/
    ui_layout.py   Canvas widget and full UI layout
    io_labels.py   YOLO / COCO label I/O and dataset export logic
    config.py      Session state and settings (reads/writes config.json)
    config.json    Persisted session data
    export_dialog.py      Export dataset dialog
    auto_annotate_dialog.py  Auto-annotate settings dialog and QThread worker
```

---

## Notes

- Labels are stored in YOLO normalized format (`class_id cx cy w h`) alongside images or in a separate label directory.
- Unlabeled images **are included** during dataset export and will be treated as background by most YOLO trainers. A warning is shown before export.
- Auto Annotate runs in a background thread — the UI stays responsive and shows a progress dialog with a Cancel button. When complete, the button changes to **Finish**; clicking it reloads the labels and class list. The model's class names are written to `classes.txt` automatically when the model is loaded.
- Check Mode is read-only — navigating back from a crop resumes normal label editing.

---

## License

This project uses [Ultralytics](https://github.com/ultralytics/ultralytics) (AGPL-3.0) as an optional dependency for Auto Annotate. LabelItem itself is for personal/open-source use.
