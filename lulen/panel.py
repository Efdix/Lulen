"""悬浮启动面板:无边框置顶工具窗,集成条目网格、分组页签、命令条与托盘联动。"""
from __future__ import annotations

import ctypes
import math
import os
import subprocess
import time
import urllib.parse

from PySide6.QtCore import QEvent, QPoint, QRect, QSize, Qt, QPropertyAnimation, QTimer, Signal
from PySide6.QtGui import QCursor, QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QApplication, QDialog, QFrame, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
    QListView, QMenu, QStackedLayout, QToolButton, QVBoxLayout, QWidget,
    QAbstractItemView,
)

from . import autostart
from .config import URL_RE, ConfigStore, Group, Item, make_items, new_id
from .delegate import ItemDelegate
from .edit_dialog import ItemDialog
from .groupbar import GroupBar
from .hotkey import HotkeyManager, hotkey_mods_with_symbol
from .icons import IconService
from .launch import open_containing, open_item
from .model import MIME_ITEM, ItemsModel
from .settings_dialog import SettingsWindow
from .theme import Palette, build_palette

_BLUR_GRACE_MS = 1200  # 失焦后隐藏的宽限期:给"点选文件→拖拽"留时间
_DRAG_RESCHEDULE_MS = 250  # 拖拽进行中时重查间隔
_EDGE_PX = 7  # 窗口边缘的缩放热区宽度(px)

# Win32 SC_SIZE 目标边(SC_SIZE + 边代号)
_SC_SIZE = {
    ("left",): 0xF001, ("right",): 0xF002, ("top",): 0xF003,
    ("left", "top"): 0xF004, ("top", "right"): 0xF005,
    ("bottom",): 0xF006, ("left", "bottom"): 0xF007,
    ("bottom", "right"): 0xF008,
}
_CURSOR_BY_EDGE = {
    ("left",): Qt.CursorShape.SizeHorCursor, ("right",): Qt.CursorShape.SizeHorCursor,
    ("top",): Qt.CursorShape.SizeVerCursor, ("bottom",): Qt.CursorShape.SizeVerCursor,
    ("left", "top"): Qt.CursorShape.SizeFDiagCursor,
    ("bottom", "right"): Qt.CursorShape.SizeFDiagCursor,
    ("top", "right"): Qt.CursorShape.SizeBDiagCursor,
    ("left", "bottom"): Qt.CursorShape.SizeBDiagCursor,
}

_RUN_DIALOG_CLSID = "shell:::{2559a1f3-21d7-11d4-bdaf-00c04f60b9f0}"
_SEARCH_ENGINES = (
    ("s ", "https://www.baidu.com/s?wd={}"),
    ("bd ", "https://www.baidu.com/s?wd={}"),
    ("b ", "https://www.bing.com/search?q={}"),
    ("g ", "https://www.google.com/search?q={}"),
    ("d ", "https://duckduckgo.com/?q={}"),
)


class GridView(QListView):
    """条目网格:接管外部拖放与内部排序。"""

    def __init__(self, panel: "LulenPanel") -> None:
        super().__init__(panel)
        self._panel = panel

    def dragEnterEvent(self, e) -> None:  # noqa: N802
        md = e.mimeData()
        if md.hasFormat(MIME_ITEM) and self._panel.model.filtered:
            e.ignore()
            return
        if md.hasFormat(MIME_ITEM) or md.hasUrls() or (md.hasText() and md.text().strip()):
            self._panel._begin_drag_hover()
            e.acceptProposedAction()
        else:
            super().dragEnterEvent(e)

    def dragMoveEvent(self, e) -> None:  # noqa: N802
        md = e.mimeData()
        if md.hasFormat(MIME_ITEM) or md.hasUrls() or (md.hasText() and md.text().strip()):
            e.acceptProposedAction()
        else:
            super().dragMoveEvent(e)

    def dragLeaveEvent(self, e) -> None:  # noqa: N802
        self._panel._end_drag_hover()
        super().dragLeaveEvent(e)

    def dropEvent(self, e) -> None:  # noqa: N802
        self._panel._end_drag_hover()
        if self._panel.handle_drop(e):
            e.acceptProposedAction()
        else:
            super().dropEvent(e)


class LulenPanel(QWidget):
    """主面板。"""

    notify_requested = Signal(str, str)   # 标题, 正文(托盘气泡)
    settings_changed = Signal()           # 设置变化,应用层需重建 QSS

    def __init__(self, store: ConfigStore, icons: IconService, hotkeys: HotkeyManager) -> None:
        super().__init__(None)
        self.store = store
        self.icons = icons
        self.hotkeys = hotkeys

        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowStaysOnTopHint
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.setAcceptDrops(True)  # 面板整体(含页签条/边距)都能接住外部拖放
        self.setWindowTitle("Lulen")

        self._shadow_margin = 16
        self._drag_offset: QPoint | None = None
        self._drag_source: QWidget | None = None
        self._drag_over = False  # 有 OLE 拖拽悬停在面板上
        self._hiding = False
        self._user_resizing = False  # 正在原生 SC_SIZE 循环中拖拽边缘
        self._manual_size = False  # 用户手动拖拽过尺寸:高度不再自动收缩
        self._opacity_base = store.settings.opacity / 100
        self._last_launch: tuple[str, float] = ("", 0.0)
        self._settings_win: SettingsWindow | None = None

        self._palette = build_palette(store.settings.theme, store.settings.accent)
        self._build_ui()
        self._build_anim()
        self.apply_settings()

        self.group_bar.current_changed.connect(self._on_group_changed)
        self.group_bar.items_dropped.connect(self._move_items_to_group)
        self.model.modelReset.connect(self._update_empty)
        self.model.rowsInserted.connect(lambda *a: self._update_empty())
        self.model.rowsRemoved.connect(lambda *a: self._update_empty())
        self.icons.favicon_ready.connect(self._on_favicon_ready)
        self.view.clicked.connect(self._on_clicked)
        self.view.doubleClicked.connect(self._on_double_clicked)
        self.view.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.view.customContextMenuRequested.connect(self._show_menu)
        self.view.installEventFilter(self)
        self.cmd.installEventFilter(self)
        self.group_bar.installEventFilter(self)
        self.group_bar._tabs.installEventFilter(self)
        self.drag_handle.installEventFilter(self)
        self.root.installEventFilter(self)  # 边缘缩放热区(所有控件就绪后安装)
        self.model.set_group(self.store.group().items)

        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(250)
        self._save_timer.timeout.connect(self.store.save)

        self._blur_timer = QTimer(self)
        self._blur_timer.setSingleShot(True)
        self._blur_timer.setInterval(_BLUR_GRACE_MS)
        self._blur_timer.timeout.connect(self._blur_maybe_hide)

    # ================= 界面构建 =================

    def _build_ui(self) -> None:
        outer = QVBoxLayout(self)
        m = self._shadow_margin
        outer.setContentsMargins(m, m, m, m + 8)

        self.root = QFrame(self)
        self.root.setObjectName("root")
        self.root.setMouseTracking(True)
        outer.addWidget(self.root)

        v = QVBoxLayout(self.root)
        v.setContentsMargins(10, 8, 10, 10)
        v.setSpacing(6)

        # 顶部:分组页签 + 拖拽把手 + 工具按钮
        strip = QWidget(self.root)
        h = QHBoxLayout(strip)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(2)
        self.group_bar = GroupBar(self.store, self)
        self.group_bar.setFixedHeight(28)
        self.group_bar.rename_requested.connect(self.rename_group_by_id)
        self.group_bar.delete_requested.connect(self.delete_group_by_id)
        h.addWidget(self.group_bar)
        self.drag_handle = QWidget(strip)
        self.drag_handle.setToolTip("拖动移动面板")
        self.drag_handle.setCursor(Qt.CursorShape.SizeAllCursor)
        self.drag_handle.setMouseTracking(True)
        h.addWidget(self.drag_handle, 1)
        self.btn_lock = QToolButton(self.root)
        self.btn_lock.setObjectName("toolBtn")
        self.btn_lock.setToolTip("锁定面板位置")
        self.btn_lock.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_lock.clicked.connect(self._toggle_lock)
        h.addWidget(self.btn_lock)
        self.btn_settings = QToolButton(self.root)
        self.btn_settings.setObjectName("toolBtn")
        self.btn_settings.setText("⚙")
        self.btn_settings.setToolTip("设置")
        self.btn_settings.setCursor(Qt.CursorShape.PointingHandCursor)
        self.btn_settings.clicked.connect(self.open_settings)
        h.addWidget(self.btn_settings)
        v.addWidget(strip)

        # 命令条(默认隐藏,直接打字唤出)
        self.cmd = QLineEdit(self.root)
        self.cmd.setObjectName("cmdBar")
        self.cmd.setPlaceholderText("搜索条目,或 > 命令  < 运行  s 百度  b 必应  g 谷歌  d duck")
        self.cmd.setFrame(False)
        self.cmd.textChanged.connect(self._on_cmd_text)
        self.cmd.returnPressed.connect(self._run_cmd)
        self.cmd.hide()
        v.addWidget(self.cmd)

        # 条目网格 + 空态提示(StackAll 叠放,空态时仍可拖放)
        self.model = ItemsModel(self.icons, self)
        self.view = GridView(self)
        self.view.setModel(self.model)
        self._delegate = ItemDelegate(self._palette, self.view)
        self.view.setItemDelegate(self._delegate)
        self.view.setViewMode(QListView.ViewMode.IconMode)
        self.view.setFlow(QListView.Flow.LeftToRight)
        self.view.setWrapping(True)
        self.view.setResizeMode(QListView.ResizeMode.Adjust)
        self.view.setMovement(QListView.Movement.Static)
        self.view.setDragDropMode(QAbstractItemView.DragDropMode.DragDrop)
        self.view.setDefaultDropAction(Qt.DropAction.MoveAction)
        self.view.setSelectionMode(QAbstractItemView.SelectionMode.ExtendedSelection)
        self.view.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.view.setMouseTracking(True)
        self.view.setVerticalScrollMode(QAbstractItemView.ScrollMode.ScrollPerPixel)
        self.view.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.view.setUniformItemSizes(True)
        self.view.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

        self.empty_hint = QLabel("把 应用 / 文件 / 文件夹 / 网址 拖进来\n或右键新建条目", self.root)
        self.empty_hint.setObjectName("emptyHint")
        self.empty_hint.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.empty_hint.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        stack = QStackedLayout()
        stack.setStackingMode(QStackedLayout.StackingMode.StackAll)
        stack.addWidget(self.view)
        stack.addWidget(self.empty_hint)
        v.addLayout(stack, 1)

        self._stack = stack

    def _build_anim(self) -> None:
        self._anim = QPropertyAnimation(self, b"windowOpacity", self)
        self._anim.setDuration(130)
        self._anim.finished.connect(self._finish_hide)

    # ================= 设置应用 =================

    def apply_settings(self) -> None:
        s = self.store.settings
        self._palette = build_palette(s.theme, s.accent)
        self._delegate.set_palette(self._palette)
        cell_w = s.icon_size + 36
        cell_h = s.icon_size + 40
        self._delegate.set_metrics(cell_w, cell_h, s.icon_size)
        self.view.setGridSize(QSize(cell_w + 6, cell_h + 6))
        self.view.setIconSize(QSize(s.icon_size, s.icon_size))
        self._opacity_base = max(0.3, min(1.0, s.opacity / 100))
        if not self._hiding:
            self.setWindowOpacity(self._opacity_base)
        self.btn_lock.setText("已锁定" if s.locked else "锁定")
        self._update_size()
        self._update_empty()

    def _update_size(self) -> None:
        if self._user_resizing:
            return  # 原生拖拽中,不能抢窗口尺寸
        s = self.store.settings
        grid = self.view.gridSize()
        w = s.columns * grid.width() + 20 + 2 * self._shadow_margin + 2
        if self._manual_size:
            rows = max(2, s.rows)  # 手动调过尺寸:高度完全由设置决定
        else:
            # 高度自适应:实际行数 = clamp(ceil(条目数/列数), 1, 设定行数)
            count = self.model.rowCount()
            used_rows = max(1, math.ceil(count / max(1, s.columns)))
            rows = min(max(1, s.rows), used_rows)
        h = 8 + 28 + 6 + rows * grid.height() + 10 + 2 * self._shadow_margin + 8 + 2
        self.resize(QSize(int(w), int(h)))

    def _update_empty(self) -> None:
        has_rows = self.model.rowCount() > 0
        self.empty_hint.setVisible(not has_rows)
        self.view.setVisible(True)
        self._update_size()

    # ================= 显示 / 隐藏 =================

    def toggle(self) -> None:
        if os.environ.get("LULEN_DEBUG"):
            print(f"[lulen] toggle visible={self.isVisible()} hiding={self._hiding} "
                  f"active={self.isActiveWindow()}", flush=True)
        if self._hiding:  # 正在淡出 → 直接拉回
            self._anim.stop()
            self._hiding = False
            self.setWindowOpacity(self._opacity_base)
            self.raise_()
            self.activateWindow()
            return
        if self.isVisible():
            self.hide_animated()
            return
        self.show_panel()

    def show_panel(self) -> None:
        self._hiding = False
        self._anim.stop()
        self.move(self._restore_pos())
        self.setWindowOpacity(self._opacity_base)
        self.show()
        self.raise_()
        self.activateWindow()
        self.view.setFocus()

    def hide_animated(self) -> None:
        if not self.isVisible() or self._hiding:
            return
        self._hiding = True
        self._anim.stop()
        self._anim.setStartValue(self.windowOpacity())
        self._anim.setKeyValueAt(0.5, self._opacity_base * 0.5)
        self._anim.setEndValue(0.0)
        self._anim.start()

    def _finish_hide(self) -> None:
        self.hide()
        self._hiding = False
        self.setWindowOpacity(self._opacity_base)

    def hide_now(self) -> None:
        self._anim.stop()
        self._hiding = False
        self.hide()
        self.setWindowOpacity(self._opacity_base)

    def _restore_pos(self) -> QPoint:
        s = self.store.settings
        if s.pos:
            p = QPoint(s.pos[0], s.pos[1])
            screen = QGuiApplication.screenAt(p + QPoint(80, 80)) or QGuiApplication.primaryScreen()
            avail = screen.availableGeometry()
            rect = QRect(p, self.size())
            if rect.right() > avail.right():
                p.setX(avail.right() - rect.width() + 1)
            if rect.bottom() > avail.bottom():
                p.setY(avail.bottom() - rect.height() + 1)
            p.setX(max(p.x(), avail.left()))
            p.setY(max(p.y(), avail.top()))
            return p
        avail = QGuiApplication.primaryScreen().availableGeometry()
        return QPoint(avail.center().x() - self.width() // 2,
                      avail.center().y() - self.height() // 2)

    def _save_pos(self) -> None:
        self.store.settings.pos = [self.x(), self.y()]
        self._touch()

    # ================= 边缘拖拽调大小 =================

    def _edge_at(self, gp: QPoint) -> tuple[str, ...] | None:
        """全局坐标落在窗口边缘热区时返回边组合,否则 None。"""
        r = self.frameGeometry()
        if not (r.left() - 2 <= gp.x() <= r.right() + 2
                and r.top() - 2 <= gp.y() <= r.bottom() + 2):
            return None
        sides: list[str] = []
        if gp.x() - r.left() <= _EDGE_PX:
            sides.append("left")
        if r.right() - gp.x() <= _EDGE_PX:
            sides.append("right")
        if gp.y() - r.top() <= _EDGE_PX:
            sides.append("top")
        if r.bottom() - gp.y() <= _EDGE_PX:
            sides.append("bottom")
        return tuple(sides) or None

    def _start_native_resize(self, sc_size: int) -> None:
        """进入 Win32 原生调整循环(跟随鼠标实时缩放),结束后把尺寸回写设置。"""
        self._user_resizing = True
        try:
            user32 = ctypes.windll.user32
            user32.ReleaseCapture()
            user32.SendMessageW(int(self.winId()), 0x0112, sc_size, 0)  # WM_SYSCOMMAND
        finally:
            self._user_resizing = False
            self._manual_size = True
            self._sync_size_from_window()

    def _sync_size_from_window(self) -> None:
        """把当前窗口尺寸换算回列数/行数并持久化(边缘拖拽后的落点)。"""
        s = self.store.settings
        grid = self.view.gridSize()
        cols = round((self.width() - 20 - 2 * self._shadow_margin - 2) / grid.width())
        rows = round((self.height() - (8 + 28 + 6 + 10 + 2 * self._shadow_margin + 8 + 2))
                     / grid.height())
        cols = max(4, min(24, cols))
        rows = max(2, min(8, rows))
        if cols != s.columns or rows != s.rows:
            s.columns, s.rows = cols, rows
            self._touch()

    def event(self, e: QEvent) -> bool:  # noqa: N802
        if self.store.settings.hide_on_blur:
            if e.type() == QEvent.Type.WindowDeactivate:
                self._blur_timer.start()
            elif e.type() == QEvent.Type.WindowActivate:
                self._blur_timer.stop()
        return super().event(e)

    def _blur_maybe_hide(self) -> None:
        """宽限期到点后的隐藏判定:拖拽进行中 / 悬停中则等待,其余隐藏。"""
        if not (self.isVisible() and self.store.settings.hide_on_blur) or self._hiding:
            return
        if self.isActiveWindow() or QApplication.activeWindow() is not None:
            return
        if QApplication.activePopupWidget() is not None:
            return
        if QApplication.activeModalWidget() is not None:
            return  # 自己弹出的对话框(编辑/设置)打开期间保持面板
        if self._drag_over:
            return  # 文件正拖在面板上
        if ctypes.windll.user32.GetAsyncKeyState(0x01) & 0x8000:
            # 左键按住:用户可能正从别的程序拖着文件过来
            QTimer.singleShot(_DRAG_RESCHEDULE_MS, self._blur_maybe_hide)
            return
        self.hide_animated()

    def _begin_drag_hover(self) -> None:
        self._drag_over = True
        self._blur_timer.stop()

    def _end_drag_hover(self) -> None:
        self._drag_over = False
        if self.store.settings.hide_on_blur:
            QTimer.singleShot(500, self._blur_maybe_hide)

    # ---- 面板级拖放(覆盖页签条/把手/边距;网格区域由 GridView 处理)----

    def dragEnterEvent(self, e) -> None:  # noqa: N802
        if self._external_drag_ok(e):
            self._begin_drag_hover()
            e.acceptProposedAction()
        else:
            e.ignore()

    def dragMoveEvent(self, e) -> None:  # noqa: N802
        if self._external_drag_ok(e):
            e.acceptProposedAction()
        else:
            e.ignore()

    def dragLeaveEvent(self, e) -> None:  # noqa: N802
        self._end_drag_hover()

    def dropEvent(self, e) -> None:  # noqa: N802
        self._end_drag_hover()
        if self.handle_drop(e):
            e.acceptProposedAction()

    def _external_drag_ok(self, e) -> bool:
        if os.environ.get("LULEN_DEBUG"):
            md = e.mimeData()
            print(f"[lulen] dragEnter urls={md.hasUrls()} item={md.hasFormat(MIME_ITEM)} "
                  f"text={md.hasText() and md.text().strip()[:40]!r}", flush=True)
        md = e.mimeData()
        return bool(md.hasFormat(MIME_ITEM) or md.hasUrls()
                    or (md.hasText() and md.text().strip()))

    def keyPressEvent(self, e) -> None:  # noqa: N802
        if e.key() == Qt.Key.Key_Escape:
            self.hide_animated()
            return
        super().keyPressEvent(e)

    # ================= 拖拽移动 / 键盘 / 命令条 =================

    def eventFilter(self, obj, ev) -> bool:  # noqa: N802
        try:
            return self._event_filter_impl(obj, ev)
        except (RuntimeError, AttributeError):
            return False  # 对象销毁阶段或构建早期的残缺事件

    def _event_filter_impl(self, obj, ev) -> bool:
        if getattr(self, "drag_handle", None) is None:
            return False  # 构建早期,过滤目标尚未创建
        if obj is self.root:
            t = ev.type()
            if t == QEvent.Type.MouseMove and not self.store.settings.locked:
                sides = self._edge_at(ev.globalPosition().toPoint())
                if sides is not None:
                    self.root.setCursor(_CURSOR_BY_EDGE[sides])
                else:
                    self.root.unsetCursor()
                return False
            if t == QEvent.Type.Leave:
                self.root.unsetCursor()
                return False
            if (t == QEvent.Type.MouseButtonPress and ev.button() == Qt.MouseButton.LeftButton
                    and not self.store.settings.locked):
                sides = self._edge_at(ev.globalPosition().toPoint())
                if sides is not None:
                    self._start_native_resize(_SC_SIZE[sides])
                    return True
        if obj in (self.drag_handle, self.group_bar):
            t = ev.type()
            if t == QEvent.Type.MouseButtonPress and ev.button() == Qt.MouseButton.LeftButton:
                if not self.store.settings.locked:
                    self._drag_offset = ev.globalPosition().toPoint() - self.frameGeometry().topLeft()
                    self._drag_source = obj
                    obj.grabMouse()
                return True
            if t == QEvent.Type.MouseMove and self._drag_offset is not None:
                self.move(ev.globalPosition().toPoint() - self._drag_offset)
                return True
            if t == QEvent.Type.MouseButtonRelease and self._drag_offset is not None:
                self._drag_offset = None
                if self._drag_source is not None:
                    self._drag_source.releaseMouse()
                    self._drag_source = None
                self._save_pos()
                return True
            if t == QEvent.Type.Wheel:
                delta = ev.angleDelta().y()
                if delta:
                    step = 1 if delta < 0 else -1
                    n = len(self.store.groups)
                    new_index = (self.store.current_group + step) % n
                    self.group_bar.set_current(new_index)
                    self._on_group_changed(new_index)
                return True
        if obj in (self.view, self.cmd) and ev.type() == QEvent.Type.KeyPress:
            return self._handle_key(obj, ev)
        return super().eventFilter(obj, ev)

    def _handle_key(self, obj, ev) -> bool:
        key = ev.key()
        if key == Qt.Key.Key_Escape:
            if self.cmd.isVisible():
                self._close_cmd()
            else:
                self.hide_animated()
            return True
        if obj is self.cmd:
            if key == Qt.Key.Key_Down and self.model.rowCount() > 0:
                self.view.setCurrentIndex(self.model.index(0))
                self.view.setFocus()
                return True
            return False  # 其余交给输入框
        if key in (Qt.Key.Key_Return, Qt.Key.Key_Enter):
            idx = self.view.currentIndex()
            if idx.isValid():
                self._launch(idx)
            return True
        if ev.text() and ev.text().isprintable() and key not in (
            Qt.Key.Key_Space, Qt.Key.Key_Tab,
            Qt.Key.Key_Backspace, Qt.Key.Key_Delete,
        ):
            self._open_cmd(ev.text())
            return True
        return False

    def _open_cmd(self, initial: str = "") -> None:
        self.cmd.show()
        self.cmd.setFocus()
        self.cmd.setText(initial)

    def _close_cmd(self) -> None:
        self.cmd.hide()
        self.cmd.clear()
        self.view.setFocus()

    def _on_cmd_text(self, text: str) -> None:
        stripped = text.strip()
        if any(stripped.startswith(p) for p in (">", "<")) or stripped == "":
            if stripped == "":
                self.model.set_filter("")
            return
        for prefix, _ in _SEARCH_ENGINES:
            if stripped.startswith(prefix.strip() + " "):
                self.model.set_filter("")
                return
        self.model.set_filter(stripped)
        if self.model.rowCount() > 0:
            self.view.setCurrentIndex(self.model.index(0))  # 回车即启动第一个结果

    def _run_cmd(self) -> None:
        text = self.cmd.text().strip()
        if not text:
            self._close_cmd()
            return
        if text.startswith(">"):
            rest = text[1:].strip()
            if rest:
                subprocess.Popen(["cmd", "/K", *rest.split()], creationflags=subprocess.CREATE_NEW_CONSOLE)
            self._close_cmd()
            self.hide_animated()
            return
        if text.startswith("<"):
            os.startfile(_RUN_DIALOG_CLSID)
            self._close_cmd()
            self.hide_animated()
            return
        for prefix, tpl in _SEARCH_ENGINES:
            if text.lower().startswith(prefix):
                q = urllib.parse.quote(text[len(prefix):].strip())
                if q:
                    QDesktopServices.openUrl(tpl.format(q))
                self._close_cmd()
                self.hide_animated()
                return
        item = self.model.first_visible()
        if item:
            idx = self.model.index(0)
            self._launch(idx)
            self._close_cmd()
        else:
            self.notify_requested.emit("Lulen", "没有匹配的条目")

    # ================= 启动条目 =================

    def _on_clicked(self, index) -> None:
        if index.isValid() and self.store.settings.single_click:
            self._launch(index)

    def _on_double_clicked(self, index) -> None:
        if index.isValid() and not self.store.settings.single_click:
            self._launch(index)

    def _launch(self, index) -> None:
        item = self.model.item_at(index.row())
        if item is None:
            return
        now = time.monotonic()
        if item.id == self._last_launch[0] and now - self._last_launch[1] < 0.4:
            return  # 双击去抖
        self._last_launch = (item.id, now)
        ok, err = open_item(item)
        if ok and self.store.settings.hide_after_launch:
            self.hide_animated()
        elif not ok:
            self.notify_requested.emit("启动失败", f"{item.name}: {err}")

    def launch_by_hotkey(self, text: str) -> None:
        for item in self.store.all_items():
            if item.hotkey == text:
                ok, err = open_item(item)
                if not ok:
                    self.notify_requested.emit("启动失败", f"{item.name}: {err}")
                return

    # ================= 拖放 =================

    def handle_drop(self, e) -> bool:
        md = e.mimeData()
        if md.hasFormat(MIME_ITEM):
            ids = [x for x in bytes(md.data(MIME_ITEM)).decode("utf-8").split(",") if x]
            idx = self.view.indexAt(e.position().toPoint())
            dp = self.view.dropIndicatorPosition()
            if idx.isValid():
                row = idx.row() if dp == QAbstractItemView.DropIndicatorPosition.AboveItem else idx.row() + 1
            else:
                row = self.model.rowCount()
            if self.model.move_ids(ids, row):
                self._touch()
            return True
        paths: list[str] = [u.toLocalFile() for u in md.urls() if u.isLocalFile()]
        if not paths and md.hasUrls():
            paths = [u.toString() for u in md.urls() if u.scheme() in ("http", "https")]
        if not paths and md.hasText():
            t = md.text().strip()
            if t and URL_RE.match(t):
                paths = [t]
        if paths:
            self.model.add_items(make_items(paths))
            self._touch()
            return True
        return False

    def _move_items_to_group(self, target_gid: str, ids: list) -> None:
        cur = self.store.group()
        tgt = next((g for g in self.store.groups if g.id == target_gid), None)
        if tgt is None or tgt is cur:
            return
        idset = set(ids)
        moved = [i for i in cur.items if i.id in idset]
        if not moved:
            return
        cur.items = [i for i in cur.items if i.id not in idset]
        tgt.items.extend(moved)
        self.model.set_group(cur.items)
        self._touch()

    # ================= 右键菜单 =================

    def _show_menu(self, pos) -> None:
        """构建并弹出右键菜单(构建逻辑在 _build_menu,便于测试)。"""
        menu = self._build_menu(self.view.indexAt(pos))
        if menu is None:
            return
        menu.exec(QCursor.pos())

    def _build_menu(self, index) -> QMenu | None:
        menu = QMenu(self)
        if index.isValid():
            selection = self.view.selectionModel().selectedIndexes()
            if len(selection) > 1:
                self._fill_multi_menu(menu, selection)
            else:
                self._fill_item_menu(menu, self.model.item_at(index.row()))
        else:
            self._fill_empty_menu(menu)
        return menu

    def _fill_item_menu(self, menu: QMenu, item: Item) -> None:
        menu.addAction("运行", lambda: self._launch(self.model.index(self.model.row_of(item))))
        if item.type == "app":
            menu.addAction("以管理员身份运行", lambda: self._launch_item_direct(item, admin=True))
        menu.addAction("在资源管理器中显示",
                       lambda: self._notify_or_err(open_containing(item)))
        menu.addAction("复制目标路径",
                       lambda: QApplication.clipboard().setText(item.path))
        menu.addSeparator()
        menu.addAction("编辑…", lambda: self._edit_item(item))
        menu.addAction("条目快捷键…", lambda: self._edit_item_hotkey(item))
        move_menu = menu.addMenu("移动到分组")
        for g in self.store.groups:
            if g is not self.store.group():
                move_menu.addAction(g.name,
                                    lambda gid=g.id, iid=item.id: self._move_items_to_group(gid, [iid]))
        menu.addSeparator()
        menu.addAction("删除", lambda: self._delete_items([item.id]))

    def _fill_multi_menu(self, menu: QMenu, selection) -> None:
        items = [self.model.item_at(i.row()) for i in selection if self.model.item_at(i.row())]
        ids = [i.id for i in items]
        menu.addAction(f"运行所选({len(items)})", lambda: self._launch_many(items))
        move_menu = menu.addMenu("移动到分组")
        for g in self.store.groups:
            if g is not self.store.group():
                move_menu.addAction(g.name, lambda gid=g.id: self._move_items_to_group(gid, ids))
        menu.addSeparator()
        menu.addAction(f"删除所选({len(items)})", lambda: self._delete_items(ids))

    def _fill_empty_menu(self, menu: QMenu) -> None:
        menu.addAction("新建条目…", lambda: self._edit_item(None))
        menu.addAction("新建网址…", lambda: self._edit_item(None, force_type="url"))
        menu.addAction("新建命令…", lambda: self._edit_item(None, force_type="command"))
        menu.addSeparator()
        gmenu = menu.addMenu("分组")
        gmenu.addAction("新建分组…", self.new_group)
        gmenu.addAction("重命名当前分组…", lambda: self.rename_group(self.store.current_group))
        gmenu.addAction("删除当前分组", lambda: self.delete_group(self.store.current_group))
        menu.addSeparator()
        menu.addAction("浅色主题" if self.store.settings.theme == "dark" else "深色主题",
                       self._toggle_theme)
        act_lock = menu.addAction("锁定面板位置")
        act_lock.setCheckable(True)
        act_lock.setChecked(self.store.settings.locked)
        act_lock.triggered.connect(self._toggle_lock)
        act_auto = menu.addAction("开机自启")
        act_auto.setCheckable(True)
        act_auto.setChecked(autostart.is_enabled())
        act_auto.triggered.connect(self._toggle_autostart)
        menu.addSeparator()
        menu.addAction("设置…", self.open_settings)
        menu.addAction("退出", lambda: QApplication.instance().quit())

    def _notify_or_err(self, result: tuple[bool, str]) -> None:
        ok, err = result
        if not ok:
            self.notify_requested.emit("Lulen", err)

    def _toggle_theme(self) -> None:
        self.store.settings.theme = "light" if self.store.settings.theme == "dark" else "dark"
        self._on_settings_changed()

    def _toggle_autostart(self, on: bool) -> None:
        if autostart.set_enabled(on):
            self.store.settings.autostart = on
            self._touch()
        else:
            self.notify_requested.emit("Lulen", "开机自启设置失败")

    # ================= 条目操作 =================

    def _launch_item_direct(self, item: Item, admin: bool = False) -> None:
        ok, err = open_item(item, run_as_admin=admin)
        if ok and self.store.settings.hide_after_launch:
            self.hide_animated()
        elif not ok:
            self.notify_requested.emit("启动失败", f"{item.name}: {err}")

    def _launch_many(self, items: list[Item]) -> None:
        for it in items:
            ok, err = open_item(it)
            if not ok:
                self.notify_requested.emit("启动失败", f"{it.name}: {err}")
        if self.store.settings.hide_after_launch:
            self.hide_animated()

    def _delete_items(self, ids: list) -> None:
        self.model.remove_ids(ids)
        self._touch()

    def _edit_item(self, item: Item | None, force_type: str | None = None) -> None:
        dlg = ItemDialog(self, item, self.icons, force_type)
        if dlg.exec() != QDialog.DialogCode.Accepted:
            return
        new_item = dlg.result_item()
        if item is None:
            self.model.add_items([new_item])
            if new_item.hotkey:
                self.hotkeys.register_item(new_item.hotkey)
        else:
            if item.hotkey and item.hotkey != new_item.hotkey:
                self.hotkeys.unregister_item(item.hotkey)
            item.type, item.name, item.path = new_item.type, new_item.name, new_item.path
            item.args, item.workdir, item.icon = new_item.args, new_item.workdir, new_item.icon
            item.hotkey = new_item.hotkey
            if item.hotkey:
                self.hotkeys.register_item(item.hotkey)
            self.icons.invalidate(item)
            self.model.set_group(self.store.group().items)
        self._touch()

    def _edit_item_hotkey(self, item: Item) -> None:
        text, ok = QInputDialog.getText(
            self, "条目快捷键", "输入快捷键(如 Alt+1、Ctrl+Alt+T),留空清除:",
            text=item.hotkey,
        )
        if not ok:
            return
        text = text.strip()
        if text:
            hk = hotkey_mods_with_symbol(text)
            if hk is None or hk[0] == 0:
                self.notify_requested.emit("Lulen", f"无法识别的快捷键:{text}")
                return
            if item.hotkey and item.hotkey != text:
                self.hotkeys.unregister_item(item.hotkey)
            item.hotkey = text
            if not self.hotkeys.register_item(text):
                item.hotkey = ""
                self.notify_requested.emit("Lulen", f"快捷键 {text} 注册失败(可能被占用)")
        else:
            if item.hotkey:
                self.hotkeys.unregister_item(item.hotkey)
            item.hotkey = ""
        self._touch()

    def _on_favicon_ready(self, item_id: str) -> None:
        g, item = self.store.find_item(item_id)
        if item is not None:
            self.icons.invalidate(item)
            self.model.refresh_item(item_id)

    # ================= 分组操作 =================

    def _on_group_changed(self, index: int) -> None:
        if index == self.store.current_group and self.model.bound_items is self.store.group().items:
            return
        self.store.current_group = index
        self.model.set_group(self.store.group().items)
        self._touch()

    def new_group(self) -> None:
        name, ok = QInputDialog.getText(self, "新建分组", "分组名称:")
        if not ok:
            return
        name = name.strip() or f"分组{len(self.store.groups) + 1}"
        self.store.groups.append(Group(id=new_id(), name=name, items=[]))
        self._refresh_groups(len(self.store.groups) - 1)

    def rename_group(self, index: int) -> None:
        if not (0 <= index < len(self.store.groups)):
            return
        g = self.store.groups[index]
        name, ok = QInputDialog.getText(self, "重命名分组", "分组名称:", text=g.name)
        if not ok:
            return
        g.name = name.strip() or g.name
        self._refresh_groups(index)

    def rename_group_by_id(self, group_id: str) -> None:
        for i, g in enumerate(self.store.groups):
            if g.id == group_id:
                self.rename_group(i)
                return

    def delete_group_by_id(self, group_id: str) -> None:
        for i, g in enumerate(self.store.groups):
            if g.id == group_id:
                self.delete_group(i)
                return

    def delete_group(self, index: int) -> None:
        if len(self.store.groups) <= 1:
            self.notify_requested.emit("Lulen", "至少保留一个分组")
            return
        if not (0 <= index < len(self.store.groups)):
            return
        g = self.store.groups[index]
        target = self.store.groups[index - 1] if index > 0 else self.store.groups[1]
        target.items.extend(g.items)
        del self.store.groups[index]
        self._refresh_groups(max(0, index - 1))

    def _refresh_groups(self, current: int) -> None:
        self.store.current_group = self.store._clamp_group(current)
        self.group_bar.rebuild()
        self.model.set_group(self.store.group().items)
        self._touch()

    def on_group_order_changed(self, new_current: int) -> None:
        """页签被拖动重排后刷新当前分组(QTabBar 已同步 store.groups)。"""
        self.store.current_group = self.store._clamp_group(new_current)
        self.model.set_group(self.store.group().items)
        self._touch()

    def _toggle_lock(self) -> None:
        self.store.settings.locked = not self.store.settings.locked
        self.apply_settings()
        self._touch()

    # ================= 设置窗口 / 保存 =================

    def open_settings(self) -> None:
        if self._settings_win is None:
            self._settings_win = SettingsWindow(self, self.store, self.hotkeys, self)
            self._settings_win.settings_changed.connect(self._on_settings_changed)
            self._settings_win.hotkey_change_failed.connect(
                lambda t: self.notify_requested.emit("Lulen", f"热键 {t} 注册失败(可能被占用)")
            )
        self._settings_win.show()
        self._settings_win.raise_()
        self._settings_win.activateWindow()

    def _on_settings_changed(self) -> None:
        self.apply_settings()
        self.settings_changed.emit()
        self._touch()

    def _touch(self) -> None:
        self._save_timer.start()

    def reload_config(self) -> None:
        """配置被导入等场景:整体重建。"""
        self.group_bar.rebuild()
        self.model.set_group(self.store.group().items)
        self.apply_settings()
