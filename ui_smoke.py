"""脚本化 UI 冒烟测试:真实窗口事件驱动,输出关键界面截图。

用法::

    python ui_smoke.py            # 使用 shots/testhome 配置(隔离)
"""
from __future__ import annotations

import os
import subprocess
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
os.environ["LULEN_HOME"] = str(Path(__file__).parent / "shots" / "testhome")

from PySide6.QtCore import QPoint, QRect, Qt, QTimer
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QMenu

from lulen.config import ConfigStore
from lulen.hotkey import HotkeyManager
from lulen.icons import IconService
from lulen.model import MIME_ITEM as MIME_ITEM_IDS
from lulen.panel import LulenPanel
from lulen.theme import build_qss

SHOTS = Path(__file__).parent / "shots"
FAILS: list[str] = []


def check(name: str, cond: bool) -> None:
    print(("PASS  " if cond else "FAIL  ") + name, flush=True)
    if not cond:
        FAILS.append(name)


def snap(name: str) -> None:
    screen = QApplication.primaryScreen()
    pix = screen.grabWindow(0)
    pix.save(str(SHOTS / name))
    print(f"  [shot] {name}", flush=True)


def wait(ms: int) -> None:
    QTest.qWait(ms)


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyleSheet(build_qss("dark", "#4F8CFF"))

    store = ConfigStore()
    store.load()
    store.current_group = 0
    store.settings.hide_on_blur = False  # 测试期间固定显示
    store.settings.pos = None
    store.save()

    icons = IconService(store.icon_cache)
    hotkeys = HotkeyManager(app)
    panel = LulenPanel(store, icons, hotkeys)
    panel.show_panel()
    panel.move(300, 200)
    wait(400)

    # ---------- 1. 面板与条目 ----------
    check("panel visible", panel.isVisible())
    check("items loaded", panel.model.rowCount() >= 4)

    # ---------- 2. 单击启动(记事本)----------
    idx = panel.model.index(0)
    rect = panel.view.visualRect(idx)
    QTest.mouseClick(panel.view.viewport(), Qt.MouseButton.LeftButton,
                     Qt.KeyboardModifier.NoModifier, rect.center())
    wait(1200)
    launched = "notepad.exe" in subprocess.run(
        ["tasklist", "/FI", "IMAGENAME eq notepad.exe"],
        capture_output=True, text=True, encoding="gbk", errors="ignore",
    ).stdout.lower()
    check("click launches notepad", launched)
    if launched:
        subprocess.run(["taskkill", "/F", "/IM", "notepad.exe"], capture_output=True)
    check("hide after launch", not panel.isVisible())

    # ---------- 3. 重新显示 + 搜索过滤 ----------
    print("  step3: reshow", flush=True)
    panel.show_panel()
    wait(300)
    print("  step3: typing ascii", flush=True)
    QTest.keyClicks(panel.view, "b")  # ASCII 打字唤出命令条(真实按键事件)
    wait(300)
    check("cmd bar opened by typing", panel.cmd.isVisible())
    # 中文过滤走 IME 输入事件,QTest 不模拟 IME,直接驱动命令条文本
    panel.cmd.setText("命令")
    panel._on_cmd_text("命令")
    wait(300)
    check("filter applied", panel.model.rowCount() == 1)
    snap("smoke-filter.png")

    # ---------- 4. 命令条:esc 关闭恢复 ----------
    QTest.keyClick(panel.cmd, Qt.Key_Escape)
    wait(150)
    check("esc closes cmd", not panel.cmd.isVisible())
    check("filter cleared", panel.model.rowCount() >= 4)

    # ---------- 5. 右键菜单(纯构建函数,不弹窗)----------
    idx = panel.model.index(0)
    menu = panel._build_menu(idx)
    check("item menu built", menu is not None)
    if menu is not None:
        actions = [a.text() for a in menu.actions() if a.text()]
        print(f"  menu items: {actions}", flush=True)
        check("menu has run+edit+delete", "运行" in actions and "编辑…" in actions and "删除" in actions)
        menu.clear()
        menu.deleteLater()
    empty_menu = panel._build_menu(panel.model.index(-1))
    check("empty menu built", empty_menu is not None)
    if empty_menu is not None:
        eactions = [a.text() for a in empty_menu.actions() if a.text()]
        print(f"  empty menu: {eactions}", flush=True)
        check("empty menu has new+settings", "新建条目…" in eactions and "设置…" in eactions)
        empty_menu.clear()
        empty_menu.deleteLater()
    tab_count = len(panel.group_bar._tabs)
    check("tabs exist", tab_count >= 2)
    if tab_count >= 2:
        QTest.mouseClick(panel.group_bar._tabs[1], Qt.MouseButton.LeftButton)
        wait(250)
        check("group switched", store.current_group == 1 and panel.model.rowCount() >= 1)
        snap("smoke-group2.png")

    # ---------- 7. 新建条目对话框(monkeypatch exec)----------
    opened_dialogs: list = []
    from PySide6.QtWidgets import QDialog
    QDialog.exec = lambda self: opened_dialogs.append(self) or QDialog.DialogCode.Rejected  # type: ignore[method-assign]
    panel._edit_item(None)
    wait(300)
    check("item dialog opened", bool(opened_dialogs))
    if opened_dialogs:
        snap("smoke-dialog.png")

    # ---------- 8. 拖放:排序 + 外部路径添加(构造 QDropEvent 走真实 handle_drop)----------
    store.current_group = 0
    panel.model.set_group(store.group().items)
    wait(200)
    from PySide6.QtCore import QMimeData, QUrl
    from PySide6.QtGui import QDropEvent

    if panel.model.rowCount() >= 2:
        before = [i.name for i in store.group().items]
        md = QMimeData()
        md.setData(MIME_ITEM_IDS, ",".join([store.group().items[-1].id]).encode("utf-8"))
        dst = panel.view.visualRect(panel.model.index(0)).center()
        ev = QDropEvent(dst, Qt.DropAction.MoveAction, md,
                        Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        panel.handle_drop(ev)
        wait(200)
        after = [i.name for i in store.group().items]
        print(f"  order: {before} -> {after}", flush=True)
        check("drop reorder applied to store",
              before != after and after.index(before[-1]) < len(before) - 1
              and sorted(after) == sorted(before))

        # 外部拖入:模拟资源管理器拖来一个文件
        n_before = panel.model.rowCount()
        md2 = QMimeData()
        md2.setUrls([QUrl.fromLocalFile(r"C:\Windows\System32\winver.exe")])
        ev2 = QDropEvent(dst, Qt.DropAction.CopyAction, md2,
                         Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        panel.handle_drop(ev2)
        wait(200)
        check("external file dropped", panel.model.rowCount() == n_before + 1
              and store.group().items[-1].name == "winver")

    # ---------- 9. 空态提示 ----------
    empty_group_items = []
    store.groups.append(type(store.groups[0])(id="ui-empty", name="空组", items=[]))
    panel._refresh_groups(len(store.groups) - 1)
    wait(250)
    check("empty hint visible", panel.empty_hint.isVisible())
    snap("smoke-empty.png")
    store.groups.pop()
    panel._refresh_groups(0)

    panel.hide_now()
    hotkeys.unregister_all()
    print(f"UI-SMOKE {'PASS' if not FAILS else 'FAIL'} ({len(FAILS)} failed)", flush=True)
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(main())
