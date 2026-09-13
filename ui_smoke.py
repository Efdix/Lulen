"""脚本化 UI 冒烟测试:真实窗口事件驱动,输出关键界面截图。

用法::

    python ui_smoke.py            # 使用 shots/testhome 配置(隔离)
"""
from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
os.environ["LULEN_HOME"] = str(Path(__file__).parent / "shots" / "testhome")

from PySide6.QtCore import QPoint, Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication

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


def seed_testhome() -> None:
    """重置测试配置,保证测试不依赖外部状态。"""
    from lulen.config import Group, Item, new_id
    store = ConfigStore()
    store.load()
    store.groups = [
        Group(id=new_id(), name="常用", items=[
            Item.create("app", "记事本", r"C:\Windows\System32\notepad.exe"),
            Item.create("app", "命令提示符", r"C:\Windows\System32\cmd.exe"),
            Item.create("app", "资源管理器", r"C:\Windows\explorer.exe"),
            Item.create("url", "baidu.com", "https://www.baidu.com"),
            Item.create("folder", "下载", r"C:\Users\13984\Downloads"),
        ]),
        Group(id=new_id(), name="工具", items=[
            Item.create("app", "计算器", r"C:\Windows\System32\calc.exe"),
        ]),
    ]
    store.current_group = 0
    store.settings.hide_on_blur = False
    store.settings.columns = 10
    store.settings.rows = 4
    store.settings.icon_size = 48
    store.save()


def main() -> int:
    app = QApplication(sys.argv)
    app.setStyleSheet(build_qss("dark", "#4F8CFF"))

    seed_testhome()
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
    from PySide6.QtGui import QFontMetrics
    fm_tab = QFontMetrics(panel.group_bar._tabs.font())
    check("first tab not elided", panel.group_bar._tabs.tabRect(0).width()
          >= fm_tab.horizontalAdvance("Life") + 14)

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
    tab_count = panel.group_bar._tabs.count()
    check("tabs exist", tab_count >= 2)
    if tab_count >= 2:
        panel.group_bar._tabs.setCurrentIndex(1)  # currentChanged → 切组
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

    if panel.model.rowCount() >= 3:
        names0 = [i.name for i in store.group().items]
        md = QMimeData()
        md.setData(MIME_ITEM_IDS, store.group().items[0].id.encode("utf-8"))
        # 前插:把第 1 项插到第 3 项前面
        ev = QDropEvent(panel.view.visualRect(panel.model.index(2)).center(),
                        Qt.DropAction.MoveAction, md,
                        Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        panel.handle_drop(ev, target=(2, False))
        wait(150)
        mid = [i.name for i in store.group().items]
        check("reorder insert-before exact",
              mid == [names0[1], names0[0], names0[2], *names0[3:]])
        # 后插:再把该项插到第 3 项后面
        ev2 = QDropEvent(panel.view.visualRect(panel.model.index(2)).center(),
                         Qt.DropAction.MoveAction, md,
                         Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        panel.handle_drop(ev2, target=(2, True))
        wait(150)
        after = [i.name for i in store.group().items]
        check("reorder insert-after exact",
              after == [names0[1], names0[2], names0[0], *names0[3:]])

        # 外部拖入:模拟资源管理器拖来一个文件(落在空白处 → 追加到末尾)
        n_before = panel.model.rowCount()
        md2 = QMimeData()
        md2.setUrls([QUrl.fromLocalFile(r"C:\Windows\System32\winver.exe")])
        ev3 = QDropEvent(panel.view.viewport().rect().center(), Qt.DropAction.CopyAction, md2,
                         Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        panel.handle_drop(ev3, target=(panel.model.rowCount(), False))
        wait(200)
        check("external file dropped", panel.model.rowCount() == n_before + 1
              and store.group().items[-1].name == "winver")

    # ---------- 9. 空态提示 ----------
    store.groups.append(type(store.groups[0])(id="ui-empty", name="空组", items=[]))
    panel._refresh_groups(len(store.groups) - 1)
    wait(250)
    check("empty hint visible", panel.empty_hint.isVisible())
    snap("smoke-empty.png")
    store.groups.pop()
    panel._refresh_groups(0)

    # ---------- 10. 失焦宽限期 + 拖拽感知(拖拽添加失效修复的回归)----------
    from PySide6.QtGui import QDragEnterEvent, QDragLeaveEvent

    # 真机上 WindowDeactivate 由前台切换触发;自动化无法可靠夺取前台,
    # 故直接启动同一代码路径使用的宽限定时器,并把激活状态断言遮蔽为"失焦"。
    panel.isActiveWindow = lambda: False  # type: ignore[method-assign]
    app_activeWindow_orig = QApplication.activeWindow
    QApplication.activeWindow = staticmethod(lambda: None)  # 模拟前台是 Explorer(非 Qt 程序)
    panel.store.settings.hide_on_blur = True  # 打开失焦隐藏以验证宽限逻辑
    try:
        panel.show_panel()
        wait(250)
        panel._blur_timer.start()  # 等价于收到 WindowDeactivate
        wait(200)
        check("grace keeps panel visible", panel.isVisible())
        wait(1500)  # 超过 1200ms 宽限期
        check("panel hides after grace", not panel.isVisible())

        # 拖拽悬停面板:dragEnter 置 _drag_over,失焦判定必须放行
        panel.show_panel()
        wait(250)
        md = QMimeData()
        md.setUrls([QUrl.fromLocalFile(r"C:\Windows\System32\winver.exe")])
        enter_ev = QDragEnterEvent(QPoint(200, 100), Qt.DropAction.CopyAction, md,
                                   Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        panel.dragEnterEvent(enter_ev)
        check("panel dragEnter accepted", enter_ev.isAccepted())
        check("drag hover flagged", panel._drag_over)
        panel._blur_timer.start()
        wait(1800)  # 远超宽限期,拖拽仍在面板上
        check("drag hover keeps panel visible", panel.isVisible())

        # 拖离面板:复位后按正常逻辑隐藏
        panel.dragLeaveEvent(QDragLeaveEvent())
        wait(1100)
        check("panel hides after drag leaves", not panel.isVisible())

        # 面板级拖放入口(页签条/边距区域):合成 drop 到 panel 本体
        panel.show_panel()
        wait(250)
        n_before = panel.model.rowCount()
        drop_ev = QDropEvent(QPoint(200, 100), Qt.DropAction.CopyAction, md,
                             Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
        panel.dropEvent(drop_ev)
        wait(200)
        check("panel-level drop adds item", panel.model.rowCount() == n_before + 1)
    finally:
        QApplication.activeWindow = app_activeWindow_orig

    # ---------- 11. 边缘拖拽调大小:尺寸回写设置 + 手动尺寸不被收缩 ----------
    from PySide6.QtCore import QSize

    from lulen.config import Item as _Item
    panel.show_panel()
    wait(200)
    grid = panel.view.gridSize()
    w6 = 20 + 2 * panel._shadow_margin + 2 + 6 * grid.width()
    h4 = (8 + 28 + 6 + 10 + 2 * panel._shadow_margin + 8 + 2) + 4 * grid.height()
    panel.resize(QSize(int(w6), int(h4)))
    panel._sync_size_from_window()
    wait(150)
    check("edge resize syncs columns", store.settings.columns == 6)
    check("edge resize syncs rows", store.settings.rows == 4)
    panel._manual_size = True
    panel.store.settings.rows = 4
    panel._update_size()
    h_before = panel.height()
    panel.model.add_items([_Item.create("app", f"extra{i}", "x.exe") for i in range(20)])
    wait(200)
    check("manual size preserved on item add", panel.height() == h_before)
    store.settings.columns, store.settings.rows = 10, 4

    # ---------- 12. 边缘热区判定(以可见面板为基准,而非含阴影的窗口)----------
    tl = panel.root.mapToGlobal(QPoint(0, 0))
    gp_left = QPoint(tl.x() + 3, tl.y() + panel.root.height() // 2)
    check("edge zone left", panel._edge_at(gp_left) == ("left",))
    gp_corner = QPoint(tl.x() + 3, tl.y() + 3)
    check("edge zone corner", set(panel._edge_at(gp_corner)) == {"left", "top"})
    gp_mid = QPoint(tl.x() + panel.root.width() // 2, tl.y() + panel.root.height() // 2)
    check("edge zone middle none", panel._edge_at(gp_mid) is None)

    # ---------- 12b. 页签条:容器空白区显示移动十字,页签本体显示箭头 ----------
    from PySide6.QtCore import QEvent, QPointF
    from PySide6.QtGui import QMouseEvent
    gb = panel.group_bar
    check("group bar shows move cursor", gb.cursor().shape() == Qt.CursorShape.SizeAllCursor)
    bar = gb._tabs

    def hover_tabs(pos: QPoint) -> None:
        ev = QMouseEvent(QEvent.Type.MouseMove, QPointF(pos),
                         Qt.MouseButton.NoButton, Qt.MouseButton.NoButton,
                         Qt.KeyboardModifier.NoModifier)
        panel._event_filter_impl(bar, ev)

    hover_tabs(bar.tabRect(0).center())
    check("tab area shows arrow cursor",
          bar.cursor().shape() == Qt.CursorShape.ArrowCursor)

    # ---------- 12c. 边缘光标改由 WM_SETCURSOR 接管:root 不再常驻/卡死光标 ----------
    import lulen.panel as lulen_panel

    def hover_root(gp: QPoint) -> None:
        ev2 = QMouseEvent(QEvent.Type.MouseMove, QPointF(panel.root.mapFromGlobal(gp)),
                          Qt.MouseButton.NoButton, Qt.MouseButton.NoButton,
                          Qt.KeyboardModifier.NoModifier)
        panel._event_filter_impl(panel.root, ev2)

    was_locked = panel.store.settings.locked
    panel.store.settings.locked = False
    hover_root(gp_left)  # 边缘悬停不得在 root 上设常驻光标(旧实现的卡死根因)
    check("edge hover leaves root cursor clean",
          not panel.root.testAttribute(Qt.WidgetAttribute.WA_SetCursor))
    hover_root(gp_mid)  # 移入中部同样不得设
    check("middle hover leaves root cursor clean",
          not panel.root.testAttribute(Qt.WidgetAttribute.WA_SetCursor))
    # 行为:热区设 resize,离开热区必须归还鼠标下控件的实际光标(否则会一直卡着)
    check("idle cursor untouched", panel._update_cursor(gp_mid) is False)
    check("edge cursor applied", panel._update_cursor(gp_left) is True)
    check("cursor restored after edge", panel._update_cursor(gp_mid) is True)
    check("restore happens once", panel._update_cursor(gp_mid) is False)
    panel.store.settings.locked = True
    check("locked panel no resize cursor", panel._update_cursor(gp_left) is False)
    panel.store.settings.locked = was_locked
    check("win32 resize cursors loaded",
          all(lulen_panel._resize_hcursor(k) for k in lulen_panel._IDC_BY_EDGE))

    # ---------- 13. 跨分组拖拽:页签落下,快速落与悬停切换两种时序 ----------
    store.current_group = 0
    panel.model.set_group(store.group().items)
    wait(150)
    bar = panel.group_bar._tabs
    item_a = store.groups[0].items[0]
    md3 = QMimeData()
    md3.setData(MIME_ITEM_IDS, item_a.id.encode("utf-8"))
    ev3 = QDropEvent(bar.tabRect(1).center(), Qt.DropAction.MoveAction, md3,
                     Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    bar.dropEvent(ev3)  # 快速落下(未触发悬停切换)
    wait(150)
    check("tab drop fast moves item",
          any(i.id == item_a.id for i in store.groups[1].items)
          and not any(i.id == item_a.id for i in store.groups[0].items))

    item_b = store.groups[0].items[0]
    bar.setCurrentIndex(1)  # 模拟悬停 550ms 后自动切换到目标分组
    wait(200)
    md4 = QMimeData()
    md4.setData(MIME_ITEM_IDS, item_b.id.encode("utf-8"))
    ev4 = QDropEvent(bar.tabRect(1).center(), Qt.DropAction.MoveAction, md4,
                     Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    bar.dropEvent(ev4)
    wait(150)
    check("tab drop after hover-switch moves item",
          any(i.id == item_b.id for i in store.groups[1].items)
          and not any(i.id == item_b.id for i in store.groups[0].items))

    # 还原:两个条目移回分组 0
    panel._move_items_to_group(store.groups[0].id, [item_a.id, item_b.id])
    wait(150)
    check("move back to group 0", len(store.groups[0].items) >= 5)

    # ---------- 14. 悬停翻组后"放进面板"的跨组手势 ----------
    store.current_group = 0
    panel.model.set_group(store.group().items)
    wait(150)
    item_c = store.groups[0].items[0]
    panel.group_bar.switch_to_group_id(store.groups[1].id)  # 模拟悬停自动翻组
    wait(200)
    check("hover-switch changed page", store.current_group == 1)
    md5 = QMimeData()
    md5.setData(MIME_ITEM_IDS, item_c.id.encode("utf-8"))
    target_pos = (panel.view.visualRect(panel.model.index(1)).center()
                  if panel.model.rowCount() > 1 else
                  panel.view.visualRect(panel.model.index(0)).center())
    ev5 = QDropEvent(target_pos, Qt.DropAction.MoveAction, md5,
                     Qt.MouseButton.LeftButton, Qt.KeyboardModifier.NoModifier)
    panel.handle_drop(ev5)  # 翻组后把条目"放进面板"松手
    wait(150)
    check("drop into panel after hover-switch moves item",
          any(i.id == item_c.id for i in store.groups[1].items)
          and not any(i.id == item_c.id for i in store.groups[0].items))
    # 还原
    panel._move_items_to_group(store.groups[0].id, [item_c.id])
    store.current_group = 0
    panel.model.set_group(store.group().items)
    wait(150)

    panel.show_panel()

    panel.hide_now()
    hotkeys.unregister_all()
    print(f"UI-SMOKE {'PASS' if not FAILS else 'FAIL'} ({len(FAILS)} failed)", flush=True)
    return 0 if not FAILS else 1


if __name__ == "__main__":
    sys.exit(main())
