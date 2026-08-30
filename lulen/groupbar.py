"""分组页签条:切换分组、增删改名(经宿主面板执行)、接收跨组拖拽。"""
from __future__ import annotations

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QFontMetrics
from PySide6.QtWidgets import QButtonGroup, QHBoxLayout, QPushButton, QWidget

from .config import ConfigStore
from .model import MIME_ITEM

_TAB_MAX_W = 104


class _Tab(QPushButton):
    """单个分组页签,支持把条目拖进来换组、右键管理分组。"""

    def __init__(self, group_id: str, text: str, host: "GroupBar") -> None:
        super().__init__(text)
        self._gid = group_id
        self._host = host
        self.setObjectName("groupTab")
        self.setCheckable(True)
        self.setAcceptDrops(True)
        self.setMaximumWidth(_TAB_MAX_W)
        self.setToolTip(text)
        self.setContextMenuPolicy(Qt.ContextMenuPolicy.CustomContextMenu)
        self.customContextMenuRequested.connect(self._show_menu)
        self._switch_timer = QTimer(self)
        self._switch_timer.setSingleShot(True)
        self._switch_timer.setInterval(550)
        self._switch_timer.timeout.connect(self._switch_under_drag)

    @property
    def group_id(self) -> str:
        return self._gid

    def _show_menu(self, pos) -> None:
        from PySide6.QtWidgets import QMenu

        menu = QMenu(self)
        menu.addAction("重命名分组…", lambda: self._host.rename_requested.emit(self._gid))
        menu.addAction("删除分组", lambda: self._host.delete_requested.emit(self._gid))
        menu.exec(self.mapToGlobal(pos))

    def set_display_text(self, text: str) -> None:
        fm = QFontMetrics(self.font())
        self.setText(fm.elidedText(text, Qt.TextElideMode.ElideRight, _TAB_MAX_W - 18))
        self.setToolTip(text)

    # --- 拖拽换组 ---

    def dragEnterEvent(self, e) -> None:  # noqa: N802
        if e.mimeData().hasFormat(MIME_ITEM):
            e.acceptProposedAction()
            self.setProperty("dropHover", True)
            self._repolish()
            self._switch_timer.start()
        else:
            e.ignore()

    def dragLeaveEvent(self, e) -> None:  # noqa: N802
        self._switch_timer.stop()
        self.setProperty("dropHover", False)
        self._repolish()

    def dropEvent(self, e) -> None:  # noqa: N802
        self._switch_timer.stop()
        self.setProperty("dropHover", False)
        self._repolish()
        ids = [x for x in bytes(e.mimeData().data(MIME_ITEM)).decode("utf-8").split(",") if x]
        if ids:
            self._host.items_dropped.emit(self._gid, ids)
            e.acceptProposedAction()

    def _switch_under_drag(self) -> None:
        self._host.switch_to_group_id(self._gid)

    def _repolish(self) -> None:
        self.style().unpolish(self)
        self.style().polish(self)


class GroupBar(QWidget):
    """分组页签条 + 新建按钮。"""

    current_changed = Signal(int)
    items_dropped = Signal(str, list)          # 目标分组 id, 条目 id 列表
    rename_requested = Signal(str)             # 分组 id
    delete_requested = Signal(str)             # 分组 id

    def __init__(self, store: ConfigStore, host_panel) -> None:
        super().__init__(host_panel)
        self.setObjectName("strip")
        self._store = store
        self._panel = host_panel
        self._tabs: list[_Tab] = []
        self._group = QButtonGroup(self)
        self._group.setExclusive(True)
        self._group.idClicked.connect(self._on_tab_clicked)
        self.rename_requested.connect(host_panel.rename_group_by_id)
        self.delete_requested.connect(host_panel.delete_group_by_id)

        lay = QHBoxLayout(self)
        lay.setContentsMargins(2, 0, 0, 0)
        lay.setSpacing(2)
        self._plus = QPushButton("+")
        self._plus.setObjectName("addTab")
        self._plus.setToolTip("新建分组")
        self._plus.setFixedSize(QSize(24, 24))
        self._plus.setCursor(Qt.CursorShape.PointingHandCursor)
        self._plus.clicked.connect(self._panel.new_group)
        lay.addWidget(self._plus)
        self.rebuild()

    # ---------- 构建 ----------

    def rebuild(self) -> None:
        lay = self.layout()
        for tab in self._tabs:
            self._group.removeButton(tab)
            lay.removeWidget(tab)
            tab.deleteLater()
        self._tabs.clear()
        for i, g in enumerate(self._store.groups):
            tab = _Tab(g.id, g.name, self)
            lay.insertWidget(lay.count() - 1, tab)
            self._tabs.append(tab)
            self._group.addButton(tab, i)
        current = self._store.current_group
        if 0 <= current < len(self._tabs):
            self._tabs[current].setChecked(True)

    def set_current(self, index: int) -> None:
        if 0 <= index < len(self._tabs):
            self._tabs[index].setChecked(True)

    def switch_to_group_id(self, group_id: str) -> None:
        for i, g in enumerate(self._store.groups):
            if g.id == group_id:
                if i != self._store.current_group:
                    self._on_tab_clicked(i)
                return

    def _on_tab_clicked(self, index: int) -> None:
        self.set_current(index)
        self.current_changed.emit(index)
