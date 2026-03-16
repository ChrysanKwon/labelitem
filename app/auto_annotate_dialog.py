"""Dialog and background worker for auto-annotation using an Ultralytics YOLO model."""

import os, gc
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton,
    QDoubleSpinBox, QFileDialog, QFrame,
)
from PySide6.QtCore import Qt, QObject, QThread, Signal


# ── Background worker ──────────────────────────────────────────────────────────

class AnnotateWorker(QObject):
    """Processes a slice of images in a background thread.

    progress is reported by writing to _state (a shared list) instead of
    emitting Qt signals, so QProgressDialog.setValue() is never called from
    a cross-thread queued connection — avoiding the processEvents deadlock.
    """

    finished = Signal(list)   # (errors,)

    def __init__(self, model_path: str, conf: float,
                 images: list, image_dir: str, save_dir: str,
                 offset: int, total: int, write_classes: bool):
        """
        images       — the slice this worker handles
        offset       — global index of images[0]
        total        — grand total of all images (for display)
        write_classes — whether to write classes.txt (only first batch)
        """
        super().__init__()
        self.model_path    = model_path
        self.conf          = conf
        self.images        = images
        self.image_dir     = image_dir
        self.save_dir      = save_dir
        self.offset        = offset
        self.total         = total
        self.write_classes = write_classes
        self._cancel       = False
        self._state        = None   # [cur, total, fname] — set by main thread

    def set_state(self, state: list):
        self._state = state

    def cancel(self):
        self._cancel = True

    def run(self):
        import torch
        torch.set_num_threads(1)
        from PIL import Image as _PIL

        errors     = []
        update_every = max(1, self.total // 100)

        try:
            from ultralytics import YOLO
            model = YOLO(self.model_path)
        except Exception as e:
            errors.append(f"Failed to load model: {e}")
            self.finished.emit(errors)
            return

        if self.write_classes:
            class_names = dict(model.names) if model.names else {}
            if class_names:
                try:
                    max_idx = max(int(k) for k in class_names)
                    lines   = [str(class_names.get(i, f"class{i}")) for i in range(max_idx + 1)]
                    with open(os.path.join(self.save_dir, "classes.txt"), "w", encoding="utf-8") as f:
                        f.write("\n".join(lines))
                except Exception:
                    pass

        for local_i, fname in enumerate(self.images):
            if self._cancel:
                break

            global_i = self.offset + local_i
            if self._state is not None and (local_i % update_every == 0 or local_i == len(self.images) - 1):
                self._state[0] = global_i
                self._state[2] = fname

            img_path = os.path.join(self.image_dir, fname)

            try:
                with _PIL.open(img_path) as _im:
                    _im.convert("RGB")
            except Exception as e:
                errors.append(f"{fname}: PIL error — {e}")
                continue

            try:
                results = model.predict(img_path, conf=self.conf, verbose=False)
                result  = results[0]
                shapes, shape_classes = [], []
                if result.boxes is not None:
                    for box in result.boxes:
                        cls_idx = int(box.cls[0].item())
                        cx, cy, nw, nh = box.xywhn[0].tolist()
                        if nw > 0 and nh > 0:
                            shapes.append((cx, cy, nw, nh))
                            shape_classes.append(cls_idx)

                txt_path = os.path.join(self.save_dir, os.path.splitext(fname)[0] + ".txt")
                if shapes:
                    _write_yolo(txt_path, shapes, shape_classes)
                elif os.path.exists(txt_path):
                    os.remove(txt_path)

                del results, result, shapes, shape_classes
            except Exception as e:
                errors.append(f"{fname}: {e}")

            if local_i % 100 == 99:
                gc.collect()

        self.finished.emit(errors)


def _write_yolo(path, shapes, shape_classes):
    lines = []
    for (cx, cy, nw, nh), cls_idx in zip(shapes, shape_classes):
        lines.append(f"{max(0, cls_idx)} {cx:.6f} {cy:.6f} {nw:.6f} {nh:.6f}")
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines))


# ── Settings dialog ────────────────────────────────────────────────────────────

class AutoAnnotateDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Auto Annotate")
        self.setMinimumWidth(440)
        self.model_path = ""

        layout = QVBoxLayout(self)
        layout.setSpacing(12)

        layout.addWidget(QLabel("YOLO model (.pt):"))
        row_model = QHBoxLayout()
        self.lbl_model = QLabel("No model selected")
        self.lbl_model.setStyleSheet("color: gray; font-size: 11px;")
        self.lbl_model.setWordWrap(True)
        self.btn_browse = QPushButton("Browse…")
        self.btn_browse.setFixedWidth(80)
        self.btn_browse.clicked.connect(self._browse_model)
        row_model.addWidget(self.lbl_model, stretch=1)
        row_model.addWidget(self.btn_browse)
        layout.addLayout(row_model)

        row_conf = QHBoxLayout()
        row_conf.addWidget(QLabel("Confidence threshold:"))
        self.spin_conf = QDoubleSpinBox()
        self.spin_conf.setRange(0.01, 1.0)
        self.spin_conf.setSingleStep(0.05)
        self.spin_conf.setValue(0.25)
        self.spin_conf.setDecimals(2)
        self.spin_conf.setFixedWidth(80)
        row_conf.addWidget(self.spin_conf)

        row_conf.addStretch()
        layout.addLayout(row_conf)

        sep = QFrame()
        sep.setFrameShape(QFrame.Shape.HLine)
        sep.setStyleSheet("color: #555;")
        layout.addWidget(sep)

        warn = QLabel(
            "⚠  This will overwrite ALL existing label files (.txt) in the\n"
            "label directory. This action cannot be undone."
        )
        warn.setStyleSheet("color: #e65100; font-weight: bold;")
        warn.setWordWrap(True)
        layout.addWidget(warn)

        row_btns = QHBoxLayout()
        row_btns.addStretch()
        self.btn_ok = QPushButton("Run Auto Annotate")
        self.btn_ok.setEnabled(False)
        self.btn_ok.setStyleSheet(
            "background-color: #1565c0; color: white; font-weight: bold; padding: 6px 16px;"
        )
        self.btn_ok.clicked.connect(self.accept)
        btn_cancel = QPushButton("Cancel")
        btn_cancel.clicked.connect(self.reject)
        row_btns.addWidget(btn_cancel)
        row_btns.addWidget(self.btn_ok)
        layout.addLayout(row_btns)

    def _browse_model(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Select YOLO model", "", "PyTorch model (*.pt)"
        )
        if path:
            self.model_path = path
            self.lbl_model.setText(path)
            self.lbl_model.setStyleSheet("color: #ccc; font-size: 11px;")
            self.btn_ok.setEnabled(True)

    def conf(self) -> float:
        return self.spin_conf.value()
