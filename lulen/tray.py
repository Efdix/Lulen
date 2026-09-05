"""托盘图标:左键切换面板,菜单提供设置 / 自启 / 退出。"""
from __future__ import annotations

from PySide6.QtCore import Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from . import autostart
from .config import ConfigStore


class Tray(QSystemTrayIcon):
    toggle_requested = Signal()
    show_settings = Signal()
    quit_requested = Signal()
    notify_requested = Signal(str, str)

    def __init__(self, icon: QIcon, store: ConfigStore, parent=None) -> None:
        super().__init__(icon, parent)
        self._store = store
        self._update_tooltip()

        menu = QMenu()
        act_toggle = menu.addAction("显示 / 隐藏面板")
        act_toggle.triggered.connect(self.toggle_requested.emit)
        act_settings = menu.addAction("设置…")
        act_settings.triggered.connect(self.show_settings.emit)
        self._act_autostart = menu.addAction("开机自启")
        self._act_autostart.setCheckable(True)
        self._act_autostart.setChecked(autostart.is_enabled())
        self._act_autostart.toggled.connect(self._set_autostart)
        menu.addSeparator()
        act_quit = menu.addAction("退出")
        act_quit.triggered.connect(self.quit_requested.emit)
        self.setContextMenu(menu)

        self.activated.connect(self._on_activated)

    def _on_activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.ActivationReason.Trigger,
                      QSystemTrayIcon.ActivationReason.DoubleClick):
            self.toggle_requested.emit()

    def _set_autostart(self, on: bool) -> None:
        if autostart.set_enabled(on):
            self._store.settings.autostart = on
            self._store.save()
        else:
            self._act_autostart.blockSignals(True)
            self._act_autostart.setChecked(autostart.is_enabled())
            self._act_autostart.blockSignals(False)
            self.notify_requested.emit("开机自启设置失败", "注册表写入被拒绝,请检查杀毒软件或权限")

    def _update_tooltip(self) -> None:
        self.setToolTip(f"Lulen — 按 {self._store.settings.hotkey} 呼出面板")

    def notify(self, title: str, body: str) -> None:
        self.showMessage(title, body, QSystemTrayIcon.MessageIcon.Information, 3500)
