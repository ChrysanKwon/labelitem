# LabelItem

A lightweight YOLO image annotation tool built with PySide6. Designed as a personal alternative to labelImg with a cleaner workflow and a few extra quality-of-life features.

> Built as a hands-on experiment using Claude Code to develop a custom labeling solution from scratch.

---

## Features

- **Draw & resize bounding boxes** with 8-handle precision editing
- **Undo / Redo** — Ctrl+Z / Ctrl+Shift+Z, scoped to the current image
- **Zero coordinate drift** — labels are stored as YOLO normalized floats and never converted through pixel rounding on load/save
- **Check Mode** — browse all crops of a selected class across every image in a gallery view; double-click any crop to open a full editing dialog without leaving Check Mode; label count per class is shown in the sidebar
- **Auto Annotate** — run any Ultralytics YOLO model on your entire image directory in the background; processed in configurable batches to keep memory stable; model class names are written to `classes.txt` automatically
- **Export datasets** — YOLO and COCO format; all images are included (unlabeled images are treated as background during training)
- **Delete Image & Label** — remove an image and its label file together, with double confirmation
- **Session persistence** — remembers last opened directory and class list across restarts

---

## Quick Start

### Requirements

```bash
pip install PySide6

# Optional — only needed for Auto Annotate
pip install ultralytics
```

### GPU Acceleration (optional)

Auto Annotate uses CPU by default. If you have an NVIDIA GPU, installing the CUDA version of PyTorch will significantly speed up inference.

1. Check your CUDA version:
   ```bash
   nvidia-smi
   ```

2. Uninstall the CPU version:
   ```bash
   pip uninstall torch torchvision -y
   ```

3. Install the CUDA version from [pytorch.org](https://pytorch.org/get-started/locally/) — select your OS, CUDA version, and copy the command. Example for CUDA 12.4:
   ```bash
   pip install torch torchvision --index-url https://download.pytorch.org/whl/cu124
   ```

4. Verify:
   ```python
   import torch
   print(torch.cuda.is_available())  # Should print True
   ```

### Run

```bash
python main.py
```

---

## Hotkeys

| Action | Key |
|---|---|
| Previous image | `←` or `A` |
| Next image | `→` or `D` |
| Toggle draw mode | `W` |
| Delete selected box | `Delete` / `Backspace` |
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
    ui_layout.py               Canvas widget and full UI layout definition
    io_labels.py               YOLO / COCO label I/O and dataset export logic
    config.py                  Session state and settings (reads/writes config.json)
    config.json                Persisted session data (gitignored)
    utils.py                   Shared UI helpers (shape label formatting, draw mode)
    check_mode.py              CheckModeController — all Check Mode logic
    check_edit_dialog.py       Per-image label editing dialog used from Check Mode
    export_dialog.py           Export dataset dialog
    auto_annotate_dialog.py    Auto-annotate settings dialog and QThread worker
```

---

## Notes

- Labels are stored in YOLO normalized format (`class_id cx cy w h`) alongside images or in a separate label directory.
- Unlabeled images **are included** during dataset export and will be treated as background by most YOLO trainers. A warning is shown before export.
- Auto Annotate runs in background QThread batches (default 400 images per batch) — the UI stays responsive throughout. When complete, the button changes to **Finish**; clicking it reloads labels and the class list. Batch size can be adjusted in `app/config.json` (`annotate_batch_size`) if needed.
- Undo/Redo history is per-image and cleared when switching images.
- Check Mode shows label counts per class in the sidebar. Double-clicking a crop opens an edit dialog; closing it returns to the same position in the gallery without reloading the entire view.

---

## License

This project uses [Ultralytics](https://github.com/ultralytics/ultralytics) (AGPL-3.0) as an optional dependency for Auto Annotate. LabelItem itself is for personal/open-source use.
