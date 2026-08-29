"""条目新建 / 编辑对话框。"""
from __future__ import annotations

import os

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout,
    QLabel, QLineEdit, QPushButton, QVBoxLayout,
)

from .config import Item, guess_name, guess_type
from .icons import IconService

_TYPES = [("app", "应用"), ("file", "文件"), ("folder", "文件夹"), ("url", "网址"), ("command", "命令")]


class ItemDialog(QDialog):
    """item 传 None 表示新建。force_type 用于"新建网址/命令"快捷入口。"""

    def __init__(self, parent, item: Item | None, icons: IconService, force_type: str | None = None) -> None:
        super().__init__(parent)
        self._icons = icons
        self._source = item
        self.setWindowTitle("编辑条目" if item else "新建条目")
        self.setMinimumWidth(430)

        v = QVBoxLayout(self)
        form = QFormLayout()
        form.setSpacing(8)
        v.addLayout(form)

        self.ed_name = QLineEdit(self)
        form.addRow("名称", self.ed_name)

        self.cb_type = QComboBox(self)
        for value, label in _TYPES:
            self.cb_type.addItem(label, value)
        form.addRow("类型", self.cb_type)

        self.ed_path = QLineEdit(self)
        self.ed_path.setPlaceholderText("文件路径 / 网址 / 命令")
        btn_browse = QPushButton("浏览…")
        btn_browse.clicked.connect(self._browse_path)
        row_path = QHBoxLayout()
        row_path.setContentsMargins(0, 0, 0, 0)
        row_path.addWidget(self.ed_path, 1)
        row_path.addWidget(btn_browse)
        form.addRow("目标", row_path)

        self.ed_args = QLineEdit(self)
        self.ed_args.setPlaceholderText("启动参数,支持 %mp%(所在目录)")
        form.addRow("参数", self.ed_args)

        self.ed_workdir = QLineEdit(self)
        btn_wd = QPushButton("浏览…")
        btn_wd.clicked.connect(self._browse_workdir)
        row_wd = QHBoxLayout()
        row_wd.setContentsMargins(0, 0, 0, 0)
        row_wd.addWidget(self.ed_workdir, 1)
        row_wd.addWidget(btn_wd)
        form.addRow("工作目录", row_wd)

        self.ed_icon = QLineEdit(self)
        self.ed_icon.setPlaceholderText("留空自动提取")
        btn_icon = QPushButton("浏览…")
        btn_icon.clicked.connect(self._browse_icon)
        btn_clear = QPushButton("清除")
        btn_clear.clicked.connect(lambda: self.ed_icon.clear())
        row_icon = QHBoxLayout()
        row_icon.setContentsMargins(0, 0, 0, 0)
        row_icon.addWidget(self.ed_icon, 1)
        row_icon.addWidget(btn_icon)
        row_icon.addWidget(btn_clear)
        form.addRow("图标", row_icon)

        row_preview = QHBoxLayout()
        self.lb_preview = QLabel(self)
        self.lb_preview.setFixedSize(36, 36)
        row_preview.addStretch(1)
        row_preview.addWidget(self.lb_preview)
        form.addRow("预览", row_preview)

        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self)
        buttons.button(QDialogButtonBox.StandardButton.Ok).setObjectName("primaryBtn")
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        v.addWidget(buttons)

        # 联动
        self.cb_type.currentIndexChanged.connect(self._type_changed)
        self.ed_path.textChanged.connect(self._auto_fill)
        self.ed_icon.textChanged.connect(lambda _t: self._update_preview())
        self.ed_path.textChanged.connect(lambda _t: self._update_preview())

        # 初始值
        if item is not None:
            self.ed_name.setText(item.name)
            self.cb_type.setCurrentIndex(max(0, [t for t, _ in _TYPES].index(item.type)))
            self.ed_path.setText(item.path)
            self.ed_args.setText(item.args)
            self.ed_workdir.setText(item.workdir)
            self.ed_icon.setText(item.icon)
        elif force_type:
            self.cb_type.setCurrentIndex([t for t, _ in _TYPES].index(force_type))
        self._type_changed()

    # ---------- 联动 ----------

    def _type_changed(self) -> None:
        is_app = self.cb_type.currentData() == "app"
        is_cmd = self.cb_type.currentData() == "command"
        self.ed_args.setEnabled(is_app)
        self.ed_workdir.setEnabled(is_app)
        self.ed_icon.setEnabled(not is_cmd)
        self.ed_path.setPlaceholderText("命令行(如 notepad C:\\a.txt)" if is_cmd else "文件路径 / 网址")
        self._update_preview()

    def _auto_fill(self, text: str) -> None:
        """目标变化时自动补类型与名称(仅新建时)。"""
        if self._source is not None:
            return
        p = text.strip()
        if p:
            idx = [t for t, _ in _TYPES].index(guess_type(p))
            self.cb_type.blockSignals(True)
            self.cb_type.setCurrentIndex(idx)
            self.cb_type.blockSignals(False)
            self._type_changed()
            if not self.ed_name.text().strip():
                self.ed_name.setText(guess_name(p))

    # ---------- 浏览 ----------

    def _browse_path(self) -> None:
        t = self.cb_type.currentData()
        if t == "url":
            return
        if t == "folder":
            d = QFileDialog.getExistingDirectory(self, "选择文件夹", self.ed_path.text())
        elif t == "app":
            d, _ = QFileDialog.getOpenFileName(
                self, "选择程序", self.ed_path.text(),
                "程序 (*.exe *.lnk *.bat *.cmd *.msi *.ahk *.py *.ps1);;所有文件 (*.*)",
            )
        else:
            d, _ = QFileDialog.getOpenFileName(self, "选择文件", self.ed_path.text(), "所有文件 (*.*)")
        if d:
            self.ed_path.setText(d)

    def _browse_workdir(self) -> None:
        d = QFileDialog.getExistingDirectory(self, "选择工作目录", self.ed_workdir.text())
        if d:
            self.ed_workdir.setText(d)

    def _browse_icon(self) -> None:
        f, _ = QFileDialog.getOpenFileName(
            self, "选择图标", self.ed_icon.text(),
            "图标 (*.ico *.png *.jpg *.jpeg *.bmp *.svg *.exe *.dll);;所有文件 (*.*)",
        )
        if f:
            self.ed_icon.setText(f)

    def _update_preview(self) -> None:
        tmp = self.result_item()
        icon = self._icons.icon_for(tmp)
        self.lb_preview.setPixmap(icon.pixmap(32, 32))

    # ---------- 结果 ----------

    def result_item(self) -> Item:
        t = self.cb_type.currentData()
        path = self.ed_path.text().strip()
        name = self.ed_name.text().strip() or guess_name(path) or path
        if t == "url" and path and "://" not in path:
            path = "https://" + path
        base = self._source or Item.create(t, name, path)
        return Item(
            id=base.id, type=t, name=name, path=path,
            args=self.ed_args.text().strip() if t == "app" else "",
            workdir=self.ed_workdir.text().strip() if t == "app" else "",
            icon=self.ed_icon.text().strip() if t != "command" else "",
            hotkey=base.hotkey,
        )

    def accept(self) -> None:  # noqa: N802
        item = self.result_item()
        if item.type != "command" and not item.path:
            self.ed_path.setFocus()
            return
        if item.type == "app" and item.path and not os.path.exists(item.path) \
                and not item.path.lower().endswith(".lnk"):
            pass  # 允许添加尚未安装的目标
        super().accept()
