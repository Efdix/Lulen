"""条目数据模型:QAbstractListModel 绑定当前分组的条目列表。

模型直接持有 ConfigStore 中 Group.items 的引用,所有变更同步写回配置。
过滤(搜索)模式下只显示匹配行,并禁用结构变更(拖拽排序等)。
"""
from __future__ import annotations

from typing import Iterable

from PySide6.QtCore import QAbstractListModel, QMimeData, QModelIndex, Qt
from PySide6.QtGui import QIcon

from .config import Item, tip_text

MIME_ITEM = "application/x-lulen-items"


class ItemsModel(QAbstractListModel):
    IconRole = Qt.ItemDataRole.UserRole + 1
    NameRole = Qt.ItemDataRole.UserRole + 2
    IdRole = Qt.ItemDataRole.UserRole + 3
    TipRole = Qt.ItemDataRole.UserRole + 4

    def __init__(self, icons, parent=None) -> None:
        super().__init__(parent)
        self._icons = icons
        self._items: list[Item] = []
        self._rows: list[Item] = []  # 过滤后的可见行
        self._filter = ""

    # ---------- 装载 / 过滤 ----------

    def set_group(self, items: list[Item]) -> None:
        self.beginResetModel()
        self._items = items
        self._refilter()
        self.endResetModel()

    @property
    def bound_items(self) -> list[Item]:
        """当前绑定的分组条目列表(与 ConfigStore 共享同一对象)。"""
        return self._items

    def row_of(self, item: Item) -> int:
        return self._rows.index(item) if item in self._rows else -1

    @property
    def filtered(self) -> bool:
        return bool(self._filter)

    def set_filter(self, text: str) -> None:
        self.beginResetModel()
        self._filter = (text or "").strip().lower()
        self._refilter()
        self.endResetModel()

    def _refilter(self) -> None:
        if not self._filter:
            self._rows = list(self._items)
        else:
            self._rows = [i for i in self._items if self._filter in i.name.lower()]

    # ---------- 只读访问 ----------

    def rowCount(self, parent=QModelIndex()) -> int:  # noqa: N802
        return 0 if parent.isValid() else len(self._rows)

    def item_at(self, row: int) -> Item | None:
        return self._rows[row] if 0 <= row < len(self._rows) else None

    def visible_items(self) -> list[Item]:
        return list(self._rows)

    def first_visible(self) -> Item | None:
        return self._rows[0] if self._rows else None

    def data(self, index: QModelIndex, role: int = Qt.ItemDataRole.DisplayRole):  # noqa: N802
        item = self.item_at(index.row())
        if item is None:
            return None
        if role == Qt.ItemDataRole.DisplayRole or role == self.NameRole:
            return item.name
        if role == self.IconRole:
            return self._icons.icon_for(item)
        if role == self.IdRole:
            return item.id
        if role == self.TipRole:
            return tip_text(item)
        return None

    def flags(self, index: QModelIndex) -> Qt.ItemFlag:  # noqa: N802
        return Qt.ItemFlag.ItemIsEnabled | Qt.ItemFlag.ItemIsSelectable | Qt.ItemFlag.ItemIsDragEnabled

    def roleNames(self):  # noqa: N802
        return {
            int(Qt.ItemDataRole.DisplayRole): b"display",
            int(self.IconRole): b"icon",
            int(self.NameRole): b"name",
            int(self.IdRole): b"id",
            int(self.TipRole): b"tip",
        }

    # ---------- 拖拽载荷 ----------

    def mimeTypes(self):  # noqa: N802
        return [MIME_ITEM, "text/uri-list"]

    def mimeData(self, indexes):  # noqa: N802
        md = QMimeData()
        ids = ",".join(self._rows[i.row()].id for i in indexes if i.isValid())
        md.setData(MIME_ITEM, ids.encode("utf-8"))
        return md

    # ---------- 结构变更(过滤模式下禁用) ----------

    def _check_mutable(self) -> bool:
        return not self._filter

    def add_items(self, items: Iterable[Item]) -> None:
        new = [i for i in items if i.name or i.path]
        if not new or not self._check_mutable():
            return
        self.beginResetModel()
        self._items.extend(new)
        self._refilter()
        self.endResetModel()

    def remove_ids(self, ids: Iterable[str]) -> None:
        idset = set(ids)
        if not idset or not self._check_mutable():
            return
        self.beginResetModel()
        self._items[:] = [i for i in self._items if i.id not in idset]
        self._refilter()
        self.endResetModel()

    def move_ids(self, ids: Iterable[str], row: int) -> bool:
        """把 ids(保持相对顺序)移动到可见行 ``row`` 之前;返回是否发生变化。"""
        if not self._check_mutable():
            return False
        idset = set(ids)
        if not idset:
            return False
        seq = [i.id for i in self._items]
        moving = [i for i in self._items if i.id in idset]
        kept = [i for i in self._items if i.id not in idset]
        insert_at = row - sum(1 for x in seq[:max(0, row)] if x in idset)
        insert_at = max(0, min(insert_at, len(kept)))
        new = kept[:insert_at] + moving + kept[insert_at:]
        if [i.id for i in new] == seq:
            return False
        self.beginResetModel()
        self._items[:] = new
        self._refilter()
        self.endResetModel()
        return True

    def refresh_item(self, item_id: str) -> None:
        """图标更新后重刷对应行。"""
        for row, item in enumerate(self._rows):
            if item.id == item_id:
                self.dataChanged.emit(self.index(row), self.index(row), [self.IconRole])
                return
