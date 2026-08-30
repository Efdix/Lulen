"""Lulen 入口。

用法::

    python main.py                     正常启动(显示面板)
    python main.py --hidden            启动后仅驻留托盘(开机自启用)
    python main.py --selftest          离屏自检(独立临时配置)
    python main.py --screenshot a.png  渲染面板截图后退出(独立临时配置)
"""
from __future__ import annotations

import argparse
import os
import sys
import tempfile
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import QApplication, QSystemTrayIcon

from lulen import APP_NAME, APP_VERSION
from lulen import hotkey as hk
from lulen import icons as icons_mod
from lulen import singleinstance, theme
from lulen.config import ConfigStore, Group, Item
from lulen.hotkey import HotkeyManager
from lulen.icons import IconService
from lulen.panel import LulenPanel
from lulen.tray import Tray

_MAIN_HOTKEY_FALLBACKS = ("Ctrl+Alt+L", "Ctrl+Shift+L", "Ctrl+Alt+Space")


def _isolated_home() -> None:
    """测试 / 截图模式使用独立配置目录,避免污染真实配置。"""
    if not os.environ.get("LULEN_HOME"):
        os.environ["LULEN_HOME"] = tempfile.mkdtemp(prefix="lulen-run-")


def _seed_demo(store: ConfigStore) -> None:
    """截图模式填充演示条目。"""
    real = [
        ("app", "记事本", r"C:\Windows\System32\notepad.exe"),
        ("app", "画图", r"C:\Windows\System32\mspaint.exe"),
        ("app", "命令提示符", r"C:\Windows\System32\cmd.exe"),
        ("app", "资源管理器", r"C:\Windows\explorer.exe"),
        ("app", "任务管理器", r"C:\Windows\System32\taskmgr.exe"),
    ]
    items = [Item.create(t, n, p) for t, n, p in real if Path(p).exists()]
    items += [
        Item.create("url", "github.com", "https://github.com"),
        Item.create("url", "baidu.com", "https://www.baidu.com"),
        Item.create("folder", "下载", str(Path.home() / "Downloads")),
    ]
    store.groups[0].items = items
    store.groups.append(Group(id=Item.create("folder", "", "").id, name="第二页", items=[
        Item.create("url", "zhihu.com", "https://www.zhihu.com"),
        Item.create("app", "计算器", r"C:\Windows\System32\calc.exe"),
    ]))
    store.current_group = 0


def _apply_style(app: QApplication, store: ConfigStore) -> None:
    app.setStyleSheet(theme.build_qss(store.settings.theme, store.settings.accent))
    app.setWindowIcon(icons_mod.app_icon(store.settings.accent))


def _selftest(store: ConfigStore, panel: LulenPanel) -> int:
    fails: list[str] = []

    def check(name: str, cond: bool) -> None:
        print(("PASS  " if cond else "FAIL  ") + name)
        if not cond:
            fails.append(name)

    check("hotkey Ctrl+Shift+Z", hk.parse_hotkey("Ctrl+Shift+Z") == (0x6, 0x5A))
    check("hotkey Alt+Space", hk.parse_hotkey("Alt+Space") == (0x1, 0x20))
    check("hotkey F5", hk.parse_hotkey("F5") == (0, 0x74))
    check("hotkey bare Z", hk.parse_hotkey("Z") == (0, 0x5A))
    check("hotkey invalid", hk.parse_hotkey("Ctrl+") is None)

    import lulen.config as C
    check("guess exe", C.guess_type(r"C:\a\b.exe") == "app")
    check("guess url", C.guess_type("https://x.com") == "url")
    check("guess dir", C.guess_type(tempfile.gettempdir()) == "folder")
    check("guess file", C.guess_type(r"C:\a\b.txt") == "file")

    made = C.make_items([r"C:\Windows\System32\notepad.exe", "github.com"])
    check("make_items len", len(made) == 2)
    check("make_items url", made[1].type == "url" and made[1].path == "https://github.com")

    store.groups.append(Group(id=C.new_id(), name="自检组",
                              items=[Item.create("url", "例", "https://example.org")]))
    store.current_group = 1
    store.save()
    s2 = ConfigStore()
    s2.load()
    check("roundtrip groups", len(s2.groups) == 2 and s2.groups[1].name == "自检组")
    check("roundtrip item", s2.groups[1].items[0].path == "https://example.org")
    check("roundtrip current", s2.current_group == 1)

    m = panel.model
    m.set_group(s2.groups[1].items)
    check("model rows", m.rowCount() == 1)
    m.set_filter("例")
    check("model filter hit", m.rowCount() == 1)
    m.set_filter("不存在的关键词")
    check("model filter miss", m.rowCount() == 0)
    m.set_filter("")

    g = Group(id=C.new_id(), name="move", items=[
        Item.create("app", "a", "a.exe"), Item.create("app", "b", "b.exe"),
        Item.create("app", "c", "c.exe"),
    ])
    m.set_group(g.items)
    m.move_ids([g.items[2].id], 0)
    check("model move", [i.name for i in g.items] == ["c", "a", "b"])

    pm = panel.grab()
    check("render", not pm.isNull() and pm.width() > 100)

    print(f"SELFTEST {'PASS' if not fails else 'FAIL'} ({len(fails)} failed)")
    return 0 if not fails else 1


def _register_main_hotkey(hotkeys: HotkeyManager, store: ConfigStore, tray: Tray) -> None:
    if hotkeys.register_main(store.settings.hotkey):
        return
    for alt in _MAIN_HOTKEY_FALLBACKS:
        if hotkeys.register_main(alt):
            old = store.settings.hotkey
            store.settings.hotkey = alt
            store.save()
            tray.notify(APP_NAME, f"热键 {old} 被占用,已改用 {alt}(可在设置中修改)")
            return
    tray.notify(APP_NAME, "全局热键注册失败,请在设置中更换")


def main() -> int:
    parser = argparse.ArgumentParser(prog=APP_NAME, description="Lulen 快速启动面板")
    parser.add_argument("--hidden", action="store_true", help="启动后仅驻留托盘")
    parser.add_argument("--selftest", action="store_true", help="离屏自检")
    parser.add_argument("--screenshot", metavar="PNG", help="渲染面板截图后退出")
    parser.add_argument("--fresh", action="store_true", help="忽略现有配置(测试用)")
    parser.add_argument("--version", action="version", version=f"{APP_NAME} {APP_VERSION}")
    args = parser.parse_args()

    if args.selftest:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    if args.selftest or args.screenshot:
        _isolated_home()

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setApplicationVersion(APP_VERSION)
    app.setQuitOnLastWindowClosed(False)
    app.setStyle("Fusion")
    app.setFont(QFont("Microsoft YaHei UI", 9))

    store = ConfigStore()
    if args.fresh:
        store.init_default()
    else:
        store.load()
    if args.screenshot and not store.groups[0].items:
        _seed_demo(store)

    _apply_style(app, store)

    icons = IconService(store.icon_cache)
    hotkeys = HotkeyManager(app)
    single = singleinstance.SingleInstance()
    if not single.is_primary:
        return 0

    panel = LulenPanel(store, icons, hotkeys)
    panel.settings_changed.connect(lambda: _apply_style(app, store))
    single.another_show.connect(panel.show_panel)

    tray = Tray(icons_mod.app_icon(store.settings.accent), store)
    tray.toggle_requested.connect(panel.toggle)
    tray.show_settings.connect(panel.open_settings)
    tray.quit_requested.connect(app.quit)
    panel.notify_requested.connect(tray.notify)

    hotkeys.main_activated.connect(panel.toggle)
    hotkeys.item_activated.connect(panel.launch_by_hotkey)
    hotkeys.register_all_item_hotkeys(store.all_items())

    if not args.selftest:
        _register_main_hotkey(hotkeys, store, tray)

    if QSystemTrayIcon.isSystemTrayAvailable():
        tray.show()

    app.aboutToQuit.connect(store.save)
    app.aboutToQuit.connect(hotkeys.unregister_all)

    if args.selftest:
        code = _selftest(store, panel)
        hotkeys.unregister_all()
        return code

    if args.screenshot:
        out = args.screenshot

        def snap() -> None:
            panel.show_panel()
            QTimer.singleShot(1500, lambda: _save_shot(panel, out, app))

        QTimer.singleShot(200, snap)
        return app.exec()

    if not args.hidden:
        panel.show_panel()

    return app.exec()


def _save_shot(panel: LulenPanel, path: str, app: QApplication) -> None:
    pix = panel.grab()
    pix.save(path)
    print(f"screenshot saved: {path}")
    app.quit()


if __name__ == "__main__":
    sys.exit(main())
