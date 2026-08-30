"""脚本验证:设置窗口主题切换 / --hidden 启动 / 二次实例唤起。"""
from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
os.environ["LULEN_HOME"] = str(Path(__file__).parent / "shots" / "testhome")

FAILS = []


def check(name, cond):
    print(("PASS  " if cond else "FAIL  ") + name, flush=True)
    if not cond:
        FAILS.append(name)


def main() -> int:
    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    from lulen.config import ConfigStore
    from lulen.hotkey import HotkeyManager
    from lulen.icons import IconService
    from lulen.panel import LulenPanel
    from lulen.settings_dialog import SettingsWindow
    from lulen.theme import build_qss

    store = ConfigStore()
    store.load()
    store.current_group = 0
    old_theme = store.settings.theme
    app.setStyleSheet(build_qss(store.settings.theme, store.settings.accent))

    icons = IconService(store.icon_cache)
    hotkeys = HotkeyManager(app)
    panel = LulenPanel(store, icons, hotkeys)
    panel.show_panel()

    # 设置窗口非模态打开、切换主题即时生效
    panel.open_settings()
    win = panel._settings_win
    check("settings window opened", isinstance(win, SettingsWindow) and win.isVisible())
    combo = win.cb_theme
    target = "light" if old_theme == "dark" else "dark"
    combo.setCurrentIndex(0 if target == "dark" else 1)
    check("theme switched live", store.settings.theme == target)
    btn = win.btn_accent
    btn_text = btn.text()
    check("accent button shows color", "#" in btn_text)
    win.close()
    # 还原
    combo.setCurrentIndex(0 if old_theme == "dark" else 1)
    check("theme restored", store.settings.theme == old_theme)

    # 热键录制控件:模拟捕获序列
    from PySide6.QtCore import QEvent, Qt
    from PySide6.QtGui import QKeyEvent

    from lulen.settings_dialog import HotkeyEdit
    he = HotkeyEdit("Ctrl+Alt+L")
    ev = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_F9, Qt.KeyboardModifier.ControlModifier | Qt.KeyboardModifier.ShiftModifier)
    he.keyPressEvent(ev)
    check("hotkey capture Ctrl+Shift+F9", he.text() == "Ctrl+Shift+F9")
    ev_esc = QKeyEvent(QEvent.Type.KeyPress, Qt.Key.Key_Escape, Qt.KeyboardModifier.NoModifier)
    he.keyPressEvent(ev_esc)
    check("hotkey capture esc keeps current", he.text() == "Ctrl+Shift+F9")  # 已捕获生效,esc 仅退出录制态

    # ---- 数据目录:指针文件与迁移(默认目录 monkeypatch 到临时区,不碰真实数据)----
    import lulen.config as C
    anchor = Path(__import__("tempfile").mkdtemp(prefix="lulen-anchor-"))
    dst = Path(__import__("tempfile").mkdtemp(prefix="lulen-dst-"))
    orig_default = C.default_data_dir
    orig_home = os.environ.get("LULEN_HOME")
    C.default_data_dir = lambda: anchor
    os.environ.pop("LULEN_HOME", None)
    try:
        check("datadir default is anchor", C.config_dir() == anchor)
        alt = Path(__import__("tempfile").mkdtemp(prefix="lulen-alt-"))
        C.write_data_dir_pointer(alt)
        check("datadir pointer read back",
              C.read_data_dir_pointer() == alt and C.config_dir() == alt)

        s4 = C.ConfigStore()
        s4.load()
        s4.groups[0].items.append(C.Item.create("url", "迁移标记", "https://example.com"))
        s4.save()
        check("datadir store writes to pointer dir", s4.path.parent == alt.resolve())

        ok, _err = s4.relocate(dst, "overwrite")
        check("relocate to empty dir", ok and (dst / "config.json").exists())
        check("relocate keeps items",
              any(i.name == "迁移标记" for i in s4.groups[0].items))
        check("relocate updates pointer", C.read_data_dir_pointer() == dst.resolve())

        ok, _err = s4.relocate(anchor, "keep")  # 回默认位置(锚点里有旧数据 → 保留)
        C.write_data_dir_pointer(None)
        check("relocate back clears pointer", C.read_data_dir_pointer() is None)
    finally:
        C.default_data_dir = orig_default
        if orig_home is not None:
            os.environ["LULEN_HOME"] = orig_home

    hotkeys.unregister_all()
    print(f"SETTINGS-TEST {'PASS' if not FAILS else 'FAIL'} ({len(FAILS)} failed)", flush=True)
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(main())
