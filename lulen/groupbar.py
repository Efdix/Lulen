"""分组页签条:基于 QTabBar(原生拖拽重排),支持跨组拖入条目与右键管理。"""
from __future__ import annotations

from PySide6.QtCore import QPoint, Qt, QMimeData, QTimer, Signal
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QHBoxLayout, QMenu, QPushButton, QTabBar, QWidget

from .config import ConfigStore
from .model import MIME_ITEM

_TAB_MAX_W = 108
_HOVER_SWITCH_MS = 550


class GroupTabs(QTabBar):
    """可拖动重排的分组页签;条目拖入页签即换组,悬停自动切换。"""

    items_dropped = Signal(str, list)   # 目标分组 id, 条目 id 列表
    rename_requested = Signal(str)      # 分组 id
    delete_requested = Signal(str)      # 分组 id

    def __init__(self, store: ConfigStore, parent: QWidget) -> None:
        super().__init__(parent)
        self._store = store
        self._drop_index = -1
        self.setMovable(True)
        self.setExpanding(False)
        self.setDrawBase(False)
        self.setElideMode(Qt.TextElideMode.ElideRight)
        self.setUsesScrollButtons(False)
        self.setChangeCurrentOnDrag(True)
        self.setAcceptDrops(True)
        self.setMinimumHeight(26)
        self._switch_timer = QTimer(self)
        self._switch_timer.setSingleShot(True)
        self._switch_timer.setInterval(_HOVER_SWITCH_MS)
        self._switch_timer.timeout.connect(self._switch_under_drag)
        self.tabMoved.connect(self._on_tab_moved)

    # ---------- 拖拽换组 ----------

    def dragEnterEvent(self, e) -> None:  # noqa: N802
        if e.mimeData().hasFormat(MIME_ITEM) and not self._panel_locked():
            e.acceptProposedAction()
            self._update_drop_hover(e.position().toPoint())
        else:
            e.ignore()

    def dragMoveEvent(self, e) -> None:  # noqa: N802
        if e.mimeData().hasFormat(MIME_ITEM):
            e.acceptProposedAction()
            self._update_drop_hover(e.position().toPoint())
        else:
            e.ignore()

    def dragLeaveEvent(self, e) -> None:  # noqa: N802
        self._switch_timer.stop()
        self._drop_index = -1

    def dropEvent(self, e) -> None:  # noqa: N802
        self._switch_timer.stop()
        index = self.tabAt(e.position().toPoint())
        self._drop_index = -1
        if index < 0:
            return
        ids = [x for x in bytes(e.mimeData().data(MIME_ITEM)).decode("utf-8").split(",") if x]
        if ids and index < len(self._store.groups):
            self.items_dropped.emit(self._store.groups[index].id, ids)
            e.acceptProposedAction()

    def _panel_locked(self) -> bool:
        return self._store.settings.locked

    def _update_drop_hover(self, pos: QPoint) -> None:
        index = self.tabAt(pos)
        if index != self._drop_index:
            self._drop_index = index
            self._switch_timer.start()

    def _switch_under_drag(self) -> None:
        if 0 <= self._drop_index < self.count():
            self.setCurrentIndex(self._drop_index)

    # ---------- 右键管理 ----------

    def contextMenuEvent(self, e) -> None:  # noqa: N802
        index = self.tabAt(e.pos())
        if not (0 <= index < len(self._store.groups)):
            return
        gid = self._store.groups[index].id
        menu = QMenu(self)
        menu.addAction("重命名分组…", lambda: self.rename_requested.emit(gid))
        menu.addAction("删除分组", lambda: self.delete_requested.emit(gid))
        menu.exec(QCursor.pos())

    # ---------- 重排 ----------

    def _on_tab_moved(self, from_: int, to: int) -> None:
        groups = self._store.groups
        if not (0 <= from_ < len(groups) and 0 <= to < len(groups)):
            return
        current_gid = groups[self._store.current_group].id
        g = groups.pop(from_)
        groups.insert(to, g)
        self._store.current_group = next(
            (i for i, x in enumerate(groups) if x.id == current_gid), 0)
        self._store.save()
        parent = self.parent()
        if parent is not None and hasattr(parent, "group_moved"):
            parent.group_moved(self._store.current_group)


class GroupBar(QWidget):
    """分组页签容器:页签条 + 新建按钮。"""

    current_changed = Signal(int)
    items_dropped = Signal(str, list)
    rename_requested = Signal(str)
    delete_requested = Signal(str)

    def __init__(self, store: ConfigStore, host_panel) -> None:
        super().__init__(host_panel)
        self.setObjectName("strip")
        self._store = store
        self._panel = host_panel

        self._tabs = GroupTabs(store, self)
        self._tabs.currentChanged.connect(self._on_current_changed)
        self._tabs.items_dropped.connect(self.items_dropped.emit)
        self._tabs.rename_requested.connect(self.rename_requested.emit)
        self._tabs.delete_requested.connect(self.delete_requested.emit)

        self._plus = QPushButton("+")
        self._plus.setObjectName("addTab")
        self._plus.setToolTip("新建分组")
        self._plus.setFixedSize(24, 24)
        self._plus.setCursor(Qt.CursorShape.PointingHandCursor)
        self._plus.clicked.connect(self._panel.new_group)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(2, 0, 0, 0)
        lay.setSpacing(2)
        lay.addWidget(self._tabs, 1)
        lay.addWidget(self._plus, 0, Qt.AlignmentFlag.AlignTop)
        self.rebuild()

    # ---------- 同步 ----------

    def rebuild(self) -> None:
        bar = self._tabs
        bar.blockSignals(True)
        while bar.count():
            bar.removeTab(bar.count() - 1)
        for g in self._store.groups:
            bar.addTab(g.name)
            bar.setTabToolTip(bar.count() - 1, g.name)
        bar.blockSignals(False)
        self.set_current(self._store.current_group)

    def set_current(self, index: int) -> None:
        bar = self._tabs
        bar.blockSignals(True)
        bar.setCurrentIndex(max(0, min(index, bar.count() - 1)))
        bar.blockSignals(False)

    def switch_to_group_id(self, group_id: str) -> None:
        for i, g in enumerate(self._store.groups):
            if g.id == group_id:
                self._tabs.setCurrentIndex(i)
                return

    def refresh_texts(self) -> None:
        bar = self._tabs
        for i, g in enumerate(self._store.groups):
            if i < bar.count():
                bar.setTabText(i, g.name)
                bar.setTabToolTip(i, g.name)

    # ---------- 事件 ----------

    def _on_current_changed(self, index: int) -> None:
        self.current_changed.emit(index)

    def group_moved(self, new_current: int) -> None:
        """页签拖动重排后由 GroupTabs 通知面板刷新。"""
        self._panel.on_group_order_changed(new_current)
