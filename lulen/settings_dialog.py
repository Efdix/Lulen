"""设置窗口(非模态,改动即时生效)。"""
from __future__ import annotations

import os

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor, QKeySequence
from PySide6.QtWidgets import (
    QCheckBox,
    QColorDialog,
    QComboBox,
    QDialog,
    QFileDialog,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QSlider,
    QSpinBox,
    QVBoxLayout,
)

from . import autostart
from .config import ConfigStore
from .hotkey import HotkeyManager

_MOD_NAMES = (
    (Qt.KeyboardModifier.ControlModifier, "Ctrl"),
    (Qt.KeyboardModifier.ShiftModifier, "Shift"),
    (Qt.KeyboardModifier.AltModifier, "Alt"),
    (Qt.KeyboardModifier.MetaModifier, "Win"),
)


class HotkeyEdit(QLineEdit):
    """点击后按下组合键完成录制。"""

    captured = Signal(str)

    def __init__(self, text: str, parent=None) -> None:
        super().__init__(parent)
        self.setReadOnly(True)
        self.setPlaceholderText("点击后按下新热键(Esc 取消)")
        self.setText(text)
        self._original = text
        self._capturing = False

    def mousePressEvent(self, e) -> None:
        self._capturing = True
        self.setText("")
        self.setPlaceholderText("请按下组合键…")

    def keyPressEvent(self, e) -> None:
        key = e.key()
        mods = e.modifiers()
        if key in (Qt.Key.Key_Control, Qt.Key.Key_Shift, Qt.Key.Key_Alt, Qt.Key.Key_Meta,
                   Qt.Key.Key_AltGr):
            return
        if key in (Qt.Key.Key_Escape, Qt.Key.Key_Backspace) and not mods:
            self._capturing = False
            self.setPlaceholderText("点击后按下新热键(Esc 取消)")
            self.setText(self._original)
            return
        if key == Qt.Key.Key_unknown:
            return
        names = [name for m, name in _MOD_NAMES if mods & m]
        key_text = QKeySequence(key).toString()
        if not key_text:
            return
        seq = "+".join(names + [key_text])
        self._capturing = False
        self.setPlaceholderText("点击后按下新热键(Esc 取消)")
        self.setText(seq)
        self._original = seq
        self.captured.emit(seq)


class SettingsWindow(QDialog):
    settings_changed = Signal()
    hotkey_change_failed = Signal(str)

    def __init__(self, panel, store: ConfigStore, hotkeys: HotkeyManager, parent=None) -> None:
        super().__init__(parent)
        self._panel = panel
        self._store = store
        self._hotkeys = hotkeys
        self.setWindowTitle("Lulen 设置")
        self.setMinimumWidth(430)
        self.setModal(False)

        v = QVBoxLayout(self)
        v.setSpacing(10)

        # ---- 外观 ----
        form_look = QFormLayout()
        form_look.setSpacing(8)
        self.cb_theme = QComboBox(self)
        self.cb_theme.addItem("深色", "dark")
        self.cb_theme.addItem("浅色", "light")
        self.cb_theme.setCurrentIndex(0 if store.settings.theme == "dark" else 1)
        form_look.addRow("主题", self.cb_theme)

        self.btn_accent = QPushButton(self)
        self.btn_accent.setFixedHeight(24)
        self.btn_accent.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_accent.clicked.connect(self._pick_accent)
        self._refresh_accent_btn()
        form_look.addRow("强调色", self.btn_accent)

        self.sp_icon = QSpinBox(self)
        self.sp_icon.setRange(28, 64)
        self.sp_icon.setValue(store.settings.icon_size)
        form_look.addRow("图标大小", self.sp_icon)

        self.sp_cols = QSpinBox(self)
        self.sp_cols.setRange(4, 24)
        self.sp_cols.setValue(store.settings.columns)
        form_look.addRow("列数", self.sp_cols)

        self.sp_rows = QSpinBox(self)
        self.sp_rows.setRange(2, 8)
        self.sp_rows.setValue(store.settings.rows)
        form_look.addRow("行数", self.sp_rows)

        row_op = QHBoxLayout()
        self.sl_opacity = QSlider(Qt.Orientation.Horizontal, self)
        self.sl_opacity.setRange(60, 100)
        self.sl_opacity.setValue(store.settings.opacity)
        self.lb_opacity = QLabel(f"{store.settings.opacity}%", self)
        row_op.addWidget(self.sl_opacity, 1)
        row_op.addWidget(self.lb_opacity)
        form_look.addRow("不透明度", row_op)

        # ---- 行为 ----
        form_act = QFormLayout()
        form_act.setSpacing(8)
        self.ed_hotkey = HotkeyEdit(store.settings.hotkey, self)
        form_act.addRow("呼出热键", self.ed_hotkey)

        self.ck_single = QCheckBox("单击启动条目(否则双击)", self)
        self.ck_single.setChecked(store.settings.single_click)
        form_act.addRow(self.ck_single)

        self.ck_blur = QCheckBox("失焦自动隐藏", self)
        self.ck_blur.setChecked(store.settings.hide_on_blur)
        form_act.addRow(self.ck_blur)

        self.ck_hide_launch = QCheckBox("启动条目后自动隐藏面板", self)
        self.ck_hide_launch.setChecked(store.settings.hide_after_launch)
        form_act.addRow(self.ck_hide_launch)

        # ---- 系统 ----
        form_sys = QFormLayout()
        form_sys.setSpacing(8)
        self.ck_autostart = QCheckBox("开机自动启动(注册表 HKCU Run)", self)
        self.ck_autostart.setChecked(autostart.is_enabled())
        form_sys.addRow(self.ck_autostart)

        # 数据目录:可迁移到任意文件夹(指针文件记录,删掉即回默认)
        row_dir = QHBoxLayout()
        self.lb_datadir = QLabel(self)
        self.lb_datadir.setToolTip(str(store.dir))
        btn_change_dir = QPushButton("更改…")
        btn_reset_dir = QPushButton("使用默认位置")
        row_dir.addWidget(self.lb_datadir, 1)
        row_dir.addWidget(btn_change_dir)
        row_dir.addWidget(btn_reset_dir)
        form_sys.addRow("数据目录", row_dir)
        self._refresh_data_dir_label()

        row_data = QHBoxLayout()
        btn_export = QPushButton("导出配置…")
        btn_import = QPushButton("导入配置…")
        btn_folder = QPushButton("打开配置文件夹")
        row_data.addWidget(btn_export)
        row_data.addWidget(btn_import)
        row_data.addWidget(btn_folder)
        form_sys.addRow(row_data)

        for title, layout in (("外观", form_look), ("行为", form_act), ("系统", form_sys)):
            group = QGroupBox(title, self)
            group.setLayout(layout)
            v.addWidget(group)

        btn_close = QPushButton("关闭")
        btn_close.setObjectName("primaryBtn")
        btn_close.clicked.connect(self.close)
        v.addWidget(btn_close, 0, Qt.AlignmentFlag.AlignRight)

        # ---- 信号 ----
        self.cb_theme.currentIndexChanged.connect(self._apply)
        self.sp_icon.valueChanged.connect(self._apply)
        self.sp_cols.valueChanged.connect(self._apply)
        self.sp_rows.valueChanged.connect(self._apply)
        self.sl_opacity.valueChanged.connect(
            lambda val: (self.lb_opacity.setText(f"{val}%"), self._apply())
        )
        self.ck_single.toggled.connect(self._apply)
        self.ck_blur.toggled.connect(self._apply)
        self.ck_hide_launch.toggled.connect(self._apply)
        self.ed_hotkey.captured.connect(self._apply_hotkey)
        self.ck_autostart.toggled.connect(self._apply_autostart)
        btn_export.clicked.connect(self._export)
        btn_import.clicked.connect(self._import)
        btn_folder.clicked.connect(self._open_config_dir)
        btn_change_dir.clicked.connect(self._change_data_dir)
        btn_reset_dir.clicked.connect(self._use_default_data_dir)

    # ---------- 应用 ----------

    def _apply(self, *args) -> None:
        s = self._store.settings
        s.theme = self.cb_theme.currentData()
        s.icon_size = self.sp_icon.value()
        s.columns = self.sp_cols.value()
        s.rows = self.sp_rows.value()
        s.opacity = self.sl_opacity.value()
        s.single_click = self.ck_single.isChecked()
        s.hide_on_blur = self.ck_blur.isChecked()
        s.hide_after_launch = self.ck_hide_launch.isChecked()
        self.settings_changed.emit()

    def _apply_hotkey(self, seq: str) -> None:
        if seq == self._store.settings.hotkey:
            return
        if self._hotkeys.register_main(seq):
            self._store.settings.hotkey = seq
            self.settings_changed.emit()
        else:
            self.hotkey_change_failed.emit(seq)
            self.ed_hotkey.setText(self._store.settings.hotkey)

    def _apply_autostart(self, on: bool) -> None:
        if autostart.set_enabled(on):
            self._store.settings.autostart = on
            self.settings_changed.emit()
        else:
            self.ck_autostart.blockSignals(True)
            self.ck_autostart.setChecked(autostart.is_enabled())
            self.ck_autostart.blockSignals(False)

    def _pick_accent(self) -> None:
        color = QColorDialog.getColor(QColor(self._store.settings.accent), self, "选择强调色")
        if color.isValid():
            self._store.settings.accent = color.name()
            self._refresh_accent_btn()
            self.settings_changed.emit()

    def _refresh_accent_btn(self) -> None:
        c = QColor(self._store.settings.accent)
        self.btn_accent.setText(f"    {c.name()}    ")
        self.btn_accent.setStyleSheet(
            f"QPushButton {{ background: {c.name()}; color: {'#000' if c.lightness() > 150 else '#fff'};"
            f" border-radius: 7px; font-weight: 600; }}"
        )

    # ---------- 配置导入导出 ----------

    def _export(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "导出配置", os.path.join(os.path.expanduser("~"), "Desktop", "lulen-config.json"),
            "JSON (*.json)",
        )
        if path and self._store.export_to(path):
            QMessageBox.information(self, "Lulen", "配置已导出")

    def _import(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "导入配置", "", "JSON (*.json)")
        if not path:
            return
        if QMessageBox.question(self, "Lulen", "导入将覆盖当前全部条目与设置,继续?") != QMessageBox.StandardButton.Yes:
            return
        if self._store.import_from(path):
            self._panel.reload_config()
            self.settings_changed.emit()
            QMessageBox.information(self, "Lulen", "配置已导入")
        else:
            QMessageBox.warning(self, "Lulen", "导入失败:文件格式不正确")

    def _open_config_dir(self) -> None:
        os.startfile(str(self._store.dir))

    # ---------- 数据目录迁移 ----------

    def _refresh_data_dir_label(self) -> None:
        from lulen.config import default_data_dir, read_data_dir_pointer

        home = os.path.expanduser("~")
        text = str(self._store.dir)
        if text.startswith(home):
            text = "~" + text[len(home):]
        if read_data_dir_pointer() is not None:
            text += "(自定义)"
        self.lb_datadir.setText(text)
        self.lb_datadir.setToolTip(
            f"{self._store.dir}\n默认位置:{default_data_dir()}")

    def _change_data_dir(self) -> None:
        new = QFileDialog.getExistingDirectory(self, "选择新的数据目录", str(self._store.dir))
        if not new:
            return
        from pathlib import Path as _Path
        new_dir = _Path(new)
        if new_dir.resolve() == self._store.dir.resolve():
            return
        on_conflict = "keep"
        if (new_dir / "config.json").exists():
            box = QMessageBox(self)
            box.setWindowTitle("Lulen")
            box.setText("目标目录中已有 Lulen 配置,如何处理?")
            keep = box.addButton("保留目标目录的数据", QMessageBox.ButtonRole.YesRole)
            overwrite = box.addButton("用当前数据覆盖", QMessageBox.ButtonRole.NoRole)
            box.addButton("取消", QMessageBox.ButtonRole.RejectRole)
            box.exec()
            clicked = box.clickedButton()
            if clicked is keep:
                on_conflict = "keep"
            elif clicked is overwrite:
                on_conflict = "overwrite"
            else:
                return
        ok, err = self._store.relocate(new_dir, on_conflict)
        if not ok:
            QMessageBox.warning(self, "Lulen", err)
            return
        self._after_relocate()

    def _use_default_data_dir(self) -> None:
        from lulen.config import default_data_dir

        default = default_data_dir()
        if default.resolve() == self._store.dir.resolve():
            return
        ok, err = self._store.relocate(default, "keep")  # 默认目录常有旧数据,保留它
        if not ok:
            QMessageBox.warning(self, "Lulen", err)
            return
        from lulen.config import write_data_dir_pointer
        write_data_dir_pointer(None)  # 清指针,回到默认位置
        self._after_relocate()

    def _after_relocate(self) -> None:
        """迁移成功:面板整体重建、窗口字段按新配置刷新。"""
        self._panel.reload_config()
        self.settings_changed.emit()
        self._refresh_data_dir_label()
        self.ed_hotkey.setText(self._store.settings.hotkey)
        self.cb_theme.setCurrentIndex(0 if self._store.settings.theme == "dark" else 1)
        self.sp_icon.setValue(self._store.settings.icon_size)
        self.sp_cols.setValue(self._store.settings.columns)
        self.sp_rows.setValue(self._store.settings.rows)
        self.sl_opacity.setValue(self._store.settings.opacity)
        self._refresh_accent_btn()
        QMessageBox.information(self, "Lulen", f"数据目录已切换到:\n{self._store.dir}")

    def closeEvent(self, e) -> None:
        self.settings_changed.emit()
        super().closeEvent(e)
