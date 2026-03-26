import sys
import os

DEBUG_MODE = False  # set True to show developer-only controls (Restart button)
from PySide6.QtWidgets import QApplication, QMainWindow, QFileDialog, QLineEdit
from PySide6.QtCore import Qt, QTimer, QEvent
from app.ui_layout import Ui_MainWindow
from app import config
from app.check_mode import CheckModeController
from app.video_mode import VideoModeController
from app.model_check import ModelCheckController
from app.label_mode import LabelModeController
from app.settings_dialog import SettingsDialog


class SimpleLabeler(QMainWindow):
    def __init__(self):
        super().__init__()
        self.ui = Ui_MainWindow()
        self.ui.setupUi(self)
        self.image_dir        = ""
        self.save_dir         = ""
        self.current_img_name = ""
        self.statusBar()  # pre-create so showMessage works on first use

        self._check = CheckModeController(self)
        self._video = VideoModeController(self)
        self._mc    = ModelCheckController(self)
        self._label = LabelModeController(self)

        # Load config once for init-time settings
        _cfg = config.load()
        _nav = _cfg.get("nav_keys", "arrows")
        if _nav == "ad":
            self._nav_prev = Qt.Key.Key_A
            self._nav_next = Qt.Key.Key_D
        else:
            self._nav_prev = Qt.Key.Key_Left
            self._nav_next = Qt.Key.Key_Right

        self.annotation_mode = _cfg.get("annotation_mode", "detection")
        if self.annotation_mode == "segmentation":
            self.ui.btn_mode_seg.setChecked(True)
        else:
            self.ui.btn_mode_det.setChecked(True)

        # ── Signal connections ─────────────────────────────────────────────
        # Directories
        self.ui.btn_img_dir.clicked.connect(self.select_img_dir)
        self.ui.btn_save_dir.clicked.connect(self.select_save_dir)

        # Label mode
        self.ui.file_list.itemClicked.connect(self._label.load_image)
        self.ui.canvas.rectangle_drawn.connect(lambda _: self._label.on_rectangle_drawn())
        self.ui.canvas.polygon_drawn.connect(self._label.on_polygon_drawn)
        self.ui.canvas.shape_modified.connect(lambda idx, _: self._label.on_shape_modified(idx))
        self.ui.shape_list.keyPressEvent = self._label.shape_list_key_press
        self.ui.btn_draw_mode.clicked.connect(self._label.toggle_draw_mode)
        self.ui.btn_polygon_mode.clicked.connect(self._label.toggle_polygon_mode)
        self.ui.btn_mode_det.clicked.connect(
            lambda: self._label.on_annotation_mode_changed("detection"))
        self.ui.btn_mode_seg.clicked.connect(
            lambda: self._label.on_annotation_mode_changed("segmentation"))
        self.ui.btn_convert_to_seg.clicked.connect(self._label.convert_to_seg)
        self.ui.btn_convert_to_det.clicked.connect(self._label.convert_to_det)
        self.ui.btn_delete_image.clicked.connect(self._label.delete_current_image)
        self.ui.btn_clean_labels.clicked.connect(self._label.clean_orphaned_labels)
        self.ui.btn_auto_annotate.clicked.connect(self._label.auto_annotate)
        self.ui.btn_export_dataset.clicked.connect(self._label.export_dataset)

        # Class management
        self.ui.btn_add_class.clicked.connect(self._label.add_class)
        self.ui.class_input.returnPressed.connect(self._label.add_class)
        self.ui.btn_del_class.clicked.connect(self._label.delete_class)
        self.ui.class_list.itemClicked.connect(self._label.on_class_selected)

        # Check mode
        self.ui.check_class_list.itemClicked.connect(self._check.on_class_selected)
        self.ui.check_view.itemDoubleClicked.connect(self._check.on_item_double_clicked)

        # Video mode
        self.ui.btn_open_video.clicked.connect(self._video.open_video)
        self.ui.btn_extract_frames.clicked.connect(self._video.open_extract_dialog)
        self.ui.btn_video_play.clicked.connect(self._video.toggle_play)
        self.ui.btn_video_prev.clicked.connect(lambda: self._video.step_frame(-1))
        self.ui.btn_video_next.clicked.connect(lambda: self._video.step_frame(1))
        self.ui.btn_video_capture.clicked.connect(self._video.capture_frame)
        self.ui.video_scrubber.valueChanged.connect(self._video.on_scrubber_moved)
        self.ui.video_frame_input.returnPressed.connect(self._video.jump_to_frame_input)

        # Model Check
        self.ui.btn_mc_open_video.clicked.connect(self._mc.open_video)
        self.ui.btn_mc_load_model.clicked.connect(self._mc.load_model)
        self.ui.btn_mc_export_video.clicked.connect(self._mc.export_video)
        self.ui.btn_mc_play.clicked.connect(self._mc.toggle_play)
        self.ui.btn_mc_prev.clicked.connect(lambda: self._mc.step_frame(-1))
        self.ui.btn_mc_next.clicked.connect(lambda: self._mc.step_frame(1))
        self.ui.mc_scrubber.valueChanged.connect(self._mc.on_scrubber_moved)
        self.ui.mc_frame_input.returnPressed.connect(self._mc.jump_to_frame_input)
        self.ui.mc_conf_spin.valueChanged.connect(self._mc.on_conf_changed)
        self.ui.mc_class_filter.currentTextChanged.connect(self._mc.filter_detections)
        self.ui.btn_mc_delete_det.clicked.connect(self._mc.delete_detection)
        self.ui.btn_mc_capture.clicked.connect(self._mc.capture_with_labels)
        self.ui.btn_mc_mode_frame.clicked.connect(
            lambda: self.ui.mc_mode_stack.setCurrentIndex(0))
        self.ui.btn_mc_mode_scan.clicked.connect(
            lambda: self.ui.mc_mode_stack.setCurrentIndex(1))
        self.ui.btn_mc_scan.clicked.connect(self._mc.scan_all_frames)
        self.ui.mc_scan_class_combo.currentTextChanged.connect(self._mc._apply_scan_filter)
        self.ui.mc_scan_count_input.valueChanged.connect(self._mc._apply_scan_filter)
        self.ui.mc_scan_list.currentRowChanged.connect(self._mc.jump_to_scan_frame)
        self.ui.btn_mc_chart.clicked.connect(self._mc.show_chart)
        self.ui.btn_mc_export.clicked.connect(self._mc.export_excel)

        # Nav column
        self.ui.btn_settings.clicked.connect(self._open_settings)
        self.ui.btn_restart.setVisible(DEBUG_MODE)
        self.ui.btn_restart.clicked.connect(self._restart)
        self.ui.btn_nav_label.clicked.connect(lambda: self._on_nav("label"))
        self.ui.btn_nav_check.clicked.connect(lambda: self._on_nav("check"))
        self.ui.btn_nav_video.clicked.connect(lambda: self._on_nav("video"))
        self.ui.btn_nav_model_check.clicked.connect(lambda: self._on_nav("model_check"))

        QApplication.instance().installEventFilter(self)
        self._label.apply_mode_tool_state()
        self._restore_session()

    # ── Event handling ────────────────────────────────────────────────────────

    def eventFilter(self, obj, event):
        if event.type() == QEvent.Type.KeyPress:
            focused = QApplication.focusWidget()
            if not isinstance(focused, QLineEdit):
                key     = event.key()
                in_label = self.ui.btn_nav_label.isChecked()
                in_video = self.ui.btn_nav_video.isChecked()
                in_mc    = self.ui.btn_nav_model_check.isChecked()

                if in_video or in_mc:
                    if key == self._nav_prev:
                        (self._video if in_video else self._mc).step_frame(-1)
                        return True
                    if key == self._nav_next:
                        (self._video if in_video else self._mc).step_frame(1)
                        return True

                if not in_label:
                    return super().eventFilter(obj, event)
                if key == self._nav_prev:
                    self._label.switch_image(-1)
                    return True
                if key == self._nav_next:
                    self._label.switch_image(1)
                    return True
                if key == Qt.Key.Key_W and self.annotation_mode == 'detection':
                    self._label.toggle_draw_mode()
                    return True
                if key == Qt.Key.Key_P and self.annotation_mode == 'segmentation':
                    self._label.toggle_polygon_mode()
                    return True
                mods = event.modifiers()
                if key == Qt.Key.Key_Z and mods & Qt.KeyboardModifier.ControlModifier:
                    if mods & Qt.KeyboardModifier.ShiftModifier:
                        self._label.redo()
                    else:
                        self._label.undo()
                    return True
                if key == Qt.Key.Key_Delete and mods & Qt.KeyboardModifier.ControlModifier:
                    if self.ui.btn_nav_label.isChecked():
                        self._label.delete_current_image()
                    return True
        return super().eventFilter(obj, event)

    def keyPressEvent(self, event):  # noqa: N802
        if event.key() in (Qt.Key.Key_Delete, Qt.Key.Key_Backspace):
            self._label.delete_selected_shape()
            return
        super().keyPressEvent(event)

    # ── Session persistence ───────────────────────────────────────────────────

    def _restore_session(self):
        cfg      = config.load()
        img_dir  = cfg.get("image_dir", "")
        last_img = cfg.get("last_image", "")
        if img_dir and os.path.isdir(img_dir):
            self._apply_image_dir(img_dir, defer_load=True,
                                  load_first=not bool(last_img))
        save_dir = cfg.get("save_dir", "")
        if save_dir and os.path.isdir(save_dir):
            self.save_dir = save_dir
            self.ui.lbl_save_path.setText(save_dir)
            self._label.load_classes()
        if last_img:
            def _restore_img():
                for i in range(self.ui.file_list.count()):
                    if self.ui.file_list.item(i).text() == last_img:
                        self.ui.file_list.setCurrentRow(i)
                        self._label.load_image(self.ui.file_list.item(i))
                        return
                if self.ui.file_list.count() > 0:
                    self._label.load_image(self.ui.file_list.item(0))
            QTimer.singleShot(0, _restore_img)
        if cfg.get("session_restart", False):
            cfg.pop("session_restart"); config.save(cfg)
            self._mc.load_video_from_path(cfg.get("last_video_path", ""))
            self._mc.load_model_from_path(cfg.get("last_model_path", ""))

    def _save_session(self):
        cfg = config.load()
        cfg["image_dir"]       = self.image_dir
        cfg["save_dir"]        = self.save_dir
        cfg["annotation_mode"] = self.annotation_mode
        cfg["last_image"]      = self.current_img_name
        config.save(cfg)

    # ── Directories ───────────────────────────────────────────────────────────

    def _apply_image_dir(self, path, defer_load=False, load_first=True):
        self.image_dir = path
        self.ui.lbl_img_path.setText(path)
        files = [f for f in os.listdir(path) if f.lower().endswith(('.jpg', '.png', '.jpeg'))]
        self.ui.file_list.clear()
        self.ui.file_list.addItems(files)
        self.save_dir = path
        self.ui.lbl_save_path.setText(path)
        self._label.load_classes()
        if self.ui.file_list.count() > 0 and load_first:
            self.ui.file_list.setCurrentRow(0)
            if defer_load:
                QTimer.singleShot(0, lambda: self._label.load_image(self.ui.file_list.item(0)))
            else:
                self._label.load_image(self.ui.file_list.item(0))
        if self.ui.btn_nav_check.isChecked():
            self._check.enter()

    def select_img_dir(self):
        start = self.image_dir if self.image_dir and os.path.isdir(self.image_dir) else ""
        path = QFileDialog.getExistingDirectory(self, "Select Image Directory", start)
        if path:
            self._apply_image_dir(path)
            self._save_session()

    def select_save_dir(self):
        start = (self.save_dir if self.save_dir and os.path.isdir(self.save_dir)
                 else self.image_dir or "")
        path = QFileDialog.getExistingDirectory(self, "Select Label Directory", start)
        if path:
            self.save_dir = path
            self.ui.lbl_save_path.setText(path)
            self._label.load_classes()
            self._save_session()
            if self.ui.btn_nav_check.isChecked():
                self._check.enter()
            self._label.reload_shapes()

    # Delegator so CheckModeController needs no changes
    def _txt_path_for(self, img_name: str) -> str:
        return self._label.txt_path_for(img_name)

    # ── Navigation ────────────────────────────────────────────────────────────

    def _on_nav(self, mode: str):
        if mode != "video":
            self._video.pause()
        if mode != "model_check":
            self._mc.pause()
        if mode == "check":
            if not self._label.require_image_dir():
                self.ui.btn_nav_label.setChecked(True)
                return
            self._check.enter()
        elif mode == "label":
            self._check.exit()
            self.ui.center_stack.setCurrentIndex(0)
            self.ui.bottom_left_stack.setCurrentIndex(0)
        elif mode == "video":
            self._check.exit()
            self.ui.center_stack.setCurrentIndex(2)
            self.ui.bottom_left_stack.setCurrentIndex(2)
            self.ui.btn_extract_frames.setEnabled(self._video._cap is not None)
        else:  # model_check
            self._check.exit()
            self.ui.center_stack.setCurrentIndex(3)
            self.ui.bottom_left_stack.setCurrentIndex(3)
        self.ui.toolbar_widget.setVisible(mode == "label")
        self.ui.mc_toolbar_widget.setVisible(mode == "model_check")
        self.ui.right_widget.setVisible(mode == "label")
        self.ui.btn_auto_annotate.setVisible(mode == "label")
        self.ui.btn_export_dataset.setVisible(mode in ("label", "check"))

    # ── App-level controls ────────────────────────────────────────────────────

    def _open_settings(self):
        SettingsDialog(self).exec()

    def _restart(self):
        import subprocess
        self._save_session()
        cfg = config.load(); cfg["session_restart"] = True; config.save(cfg)
        self._clear_mc_cache()
        subprocess.Popen([sys.executable] + sys.argv)
        QApplication.quit()

    def closeEvent(self, event):  # noqa: N802
        self._clear_mc_cache()
        event.accept()

    def _clear_mc_cache(self):
        import shutil
        cache_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".mc_cache")
        if os.path.isdir(cache_dir):
            shutil.rmtree(cache_dir)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = SimpleLabeler()
    window.show()
    sys.exit(app.exec())
