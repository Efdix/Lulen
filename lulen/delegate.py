"""条目绘制委托:图标 + 名称,自绘悬停 / 按压 / 选中底色。"""
from __future__ import annotations

from PySide6.QtCore import QRect, QSize, Qt
from PySide6.QtGui import QFontMetrics, QColor, QIcon, QPainter, QPen
from PySide6.QtWidgets import QStyle, QStyledItemDelegate

from .model import ItemsModel
from .theme import Palette


class ItemDelegate(QStyledItemDelegate):
    def __init__(self, palette: Palette, parent=None) -> None:
        super().__init__(parent)
        self._palette = palette
        self._cell_w = 78
        self._cell_h = 82
        self._icon_size = 44

    def set_palette(self, palette: Palette) -> None:
        self._palette = palette

    def set_metrics(self, cell_w: int, cell_h: int, icon_size: int) -> None:
        self._cell_w, self._cell_h, self._icon_size = cell_w, cell_h, icon_size

    def sizeHint(self, option, index) -> QSize:  # noqa: N802
        return QSize(self._cell_w, self._cell_h)

    def paint(self, painter: QPainter, option, index) -> None:
        painter.save()
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)
        pal = self._palette
        rect = option.rect.adjusted(2, 2, -2, -2)

        state = option.state
        hovered = bool(state & QStyle.StateFlag.State_MouseOver)
        pressed = bool(state & QStyle.StateFlag.State_Sunken)
        selected = bool(state & QStyle.StateFlag.State_Selected)

        if selected:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(pal.selected)
            painter.drawRoundedRect(rect, 10, 10)
            painter.setPen(QPen(pal.accent, 1))
            painter.setBrush(Qt.BrushStyle.NoBrush)
            painter.drawRoundedRect(rect.adjusted(0, 0, -1, -1), 10, 10)
        elif pressed:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(pal.pressed)
            painter.drawRoundedRect(rect, 10, 10)
        elif hovered:
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(pal.hover)
            painter.drawRoundedRect(rect, 10, 10)

        # 图标
        icon: QIcon = index.data(ItemsModel.IconRole)
        if icon is not None and not icon.isNull():
            top = rect.top() + max(2, (self._cell_h - self._icon_size - 20) // 2)
            icon_rect = QRect(
                rect.center().x() - self._icon_size // 2, top,
                self._icon_size, self._icon_size,
            )
            mode = QIcon.Mode.Selected if selected else QIcon.Mode.Normal
            icon.paint(painter, icon_rect, Qt.AlignmentFlag.AlignCenter, mode)

        # 名称
        name: str = index.data(ItemsModel.NameRole) or ""
        fm = QFontMetrics(option.font)
        label_h = fm.height() + 2
        label_rect = QRect(rect.left() + 2, rect.bottom() - label_h - 1,
                           rect.width() - 4, label_h)
        painter.setPen(QPen(pal.text if selected else pal.text, 1))
        painter.setFont(option.font)
        elided = fm.elidedText(name, Qt.TextElideMode.ElideRight, label_rect.width())
        painter.drawText(label_rect, Qt.AlignmentFlag.AlignHCenter | Qt.AlignmentFlag.AlignVCenter, elided)

        # 拖动排序指示线:目标格左/右边缘的强调色竖条
        view = self.parent()
        if hasattr(view, "indicator"):
            ind = view.indicator()
            if ind is not None and ind[0] == index.row():
                _, after = ind
                x = rect.right() - 1 if after else rect.left() + 1
                painter.setPen(Qt.PenStyle.NoPen)
                painter.setBrush(pal.accent)
                painter.drawRoundedRect(QRect(x - 2, rect.top() + 2, 4, rect.height() - 4), 2, 2)

        painter.restore()
