"""图标服务:文件图标提取、网址 favicon 后台抓取、内置占位图标,统一缓存。"""
from __future__ import annotations

import hashlib
import os
import urllib.request
from pathlib import Path

from PySide6.QtCore import QObject, QPointF, QRectF, Qt, QRunnable, QThreadPool, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QLinearGradient, QPainter, QPen, QPixmap

try:  # Qt >= 6.7 时 QFileIconProvider 位于 QtGui
    from PySide6.QtGui import QFileIconProvider
except ImportError:  # pragma: no cover - 兼容旧版
    from PySide6.QtWidgets import QFileIconProvider

from PySide6.QtCore import QFileInfo

from .config import Item

_IMG_EXTS = {".png", ".jpg", ".jpeg", ".ico", ".bmp", ".svg", ".webp"}


def _domain(url: str) -> str:
    u = (url or "").strip()
    if "://" in u:
        u = u.split("://", 1)[1]
    return u.split("/")[0].split(":")[0]


class _FaviconFetcher(QRunnable):
    """工作线程里用 urllib 抓取站点图标(QNetworkAccessManager 需事件循环,线程内不便)。"""

    def __init__(self, service: "IconService", item_id: str, domain: str, out_file: Path) -> None:
        super().__init__()
        self._service = service
        self._item_id = item_id
        self._domain = domain
        self._out_file = out_file

    def run(self) -> None:  # pragma: no cover - 网络路径
        for url in (f"https://favicon.im/{self._domain}?larger=true",
                    f"https://api.iowen.cn/favicon/{self._domain}.png"):
            try:
                req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
                data = urllib.request.urlopen(req, timeout=8).read()
                pix = QPixmap()
                if pix.loadFromData(data) and pix.width() >= 16:
                    self._out_file.parent.mkdir(parents=True, exist_ok=True)
                    pix.save(str(self._out_file))
                    self._service._favicon_ready(self._item_id, self._domain)
                    return
            except Exception:
                continue


class IconService(QObject):
    """条目 -> QIcon;favicon 到达后发 ``favicon_ready(item_id)``。"""

    favicon_ready = Signal(str)

    def __init__(self, cache_dir: Path, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._cache_dir = Path(cache_dir)
        self._provider = QFileIconProvider()
        self._cache: dict[str, QIcon] = {}
        self._fetching: set[str] = set()
        self._pool = QThreadPool.globalInstance()

    # ---------- 对外 ----------

    def icon_for(self, item: Item) -> QIcon:
        key = f"{item.type}|{item.icon}|{item.path or item.name}"
        cached = self._cache.get(key)
        if cached is not None:
            return cached
        icon = self._build(item)
        self._cache[key] = icon
        return icon

    def invalidate(self, item: Item) -> None:
        self._cache.pop(f"{item.type}|{item.icon}|{item.path or item.name}", None)

    # ---------- 构建 ----------

    def _build(self, item: Item) -> QIcon:
        if item.type == "url":
            if item.icon and os.path.isfile(item.icon):
                return QIcon(item.icon)
            dom = _domain(item.path)
            if dom:
                f = self._favicon_file(dom)
                if f:
                    return QIcon(str(f))
                self._request_favicon(item.id, dom)
            return self._globe()
        if item.icon:
            return self._icon_from_source(item.icon)
        if item.path:
            fi = QFileInfo(item.path)
            if fi.exists():
                icon = self._provider.icon(fi)
                if not icon.isNull():
                    return icon
        return self._generic(item.type)

    def _icon_from_source(self, path: str) -> QIcon:
        """自定义图标:.ico/.png 等直接加载,exe/dll 走系统提取。"""
        ext = os.path.splitext(path)[1].lower()
        if ext in _IMG_EXTS and os.path.isfile(path):
            return QIcon(path)
        fi = QFileInfo(path)
        if fi.exists():
            icon = self._provider.icon(fi)
            if not icon.isNull():
                return icon
        return self._generic("file")

    def _favicon_file(self, domain: str) -> Path | None:
        f = self._cache_dir / f"fav-{hashlib.md5(domain.encode()).hexdigest()}.png"
        return f if f.exists() else None

    def _request_favicon(self, item_id: str, domain: str) -> None:
        if domain in self._fetching:
            return
        self._fetching.add(domain)
        out = self._cache_dir / f"fav-{hashlib.md5(domain.encode()).hexdigest()}.png"
        self._pool.start(_FaviconFetcher(self, item_id, domain, out))

    def _favicon_ready(self, item_id: str, domain: str) -> None:
        """工作线程回调(经 Qt 队列切回主线程)。"""
        self._fetching.discard(domain)
        self.favicon_ready.emit(item_id)

    # ---------- 占位图标(手绘,避免资源文件) ----------

    def _painter(self, size: int = 64) -> tuple[QPainter, QPixmap]:
        pix = QPixmap(size, size)
        pix.fill(Qt.GlobalColor.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.RenderHint.Antialiasing)
        return p, pix

    def _globe(self) -> QIcon:
        p, pix = self._painter()
        pen = QPen(QColor("#7E8AA5"), 4)
        p.setPen(pen)
        p.drawEllipse(QRectF(6, 6, 52, 52))
        p.drawEllipse(QRectF(22, 6, 20, 52))
        p.drawLine(QPointF(6, 32), QPointF(58, 32))
        p.end()
        return QIcon(pix)

    def _generic(self, type_: str) -> QIcon:
        if type_ == "url":
            return self._globe()
        if type_ == "command":
            p, pix = self._painter()
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#2B2E38"))
            p.drawRoundedRect(QRectF(4, 8, 56, 48), 10, 10)
            p.setPen(QPen(QColor("#9BE58B"), 4, Qt.PenStyle.SolidLine, Qt.PenCapStyle.RoundCap))
            f = QFont("Consolas", 20)
            f.setBold(True)
            p.setFont(f)
            p.setPen(QColor("#9BE58B"))
            p.drawText(QRectF(4, 8, 56, 48), Qt.AlignmentFlag.AlignCenter, ">_")
            p.end()
            return QIcon(pix)
        if type_ == "folder":
            p, pix = self._painter()
            p.setPen(Qt.PenStyle.NoPen)
            p.setBrush(QColor("#E8B84B"))
            p.drawRoundedRect(QRectF(6, 16, 52, 40), 6, 6)
            p.drawRoundedRect(QRectF(6, 12, 26, 12), 4, 4)
            p.end()
            return QIcon(pix)
        # 默认:白纸
        p, pix = self._painter()
        p.setPen(QPen(QColor("#C4C9D4"), 2))
        p.setBrush(QColor("#F2F4F8"))
        p.drawRoundedRect(QRectF(12, 6, 40, 52), 5, 5)
        p.setPen(QPen(QColor("#AEB4C2"), 3))
        for y in (22, 32, 42):
            p.drawLine(QPointF(20, y), QPointF(44, y))
        p.end()
        return QIcon(pix)


def app_icon(accent: str) -> QIcon:
    """应用图标:圆角方块 + 渐变 + 白色 L。"""
    pix = QPixmap(256, 256)
    pix.fill(Qt.GlobalColor.transparent)
    p = QPainter(pix)
    p.setRenderHint(QPainter.RenderHint.Antialiasing)
    grad = QLinearGradient(0, 0, 0, 256)
    c = QColor(accent)
    grad.setColorAt(0.0, c.lightness(160) if c.lightness() < 150 else c)
    grad.setColorAt(1.0, c.darker(135))
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(grad)
    p.drawRoundedRect(QRectF(12, 12, 232, 232), 56, 56)
    p.setPen(QColor(255, 255, 255, 45))
    p.setBrush(QColor(255, 255, 255, 28))
    p.drawRoundedRect(QRectF(20, 20, 216, 100), 48, 48)
    f = QFont("Segoe UI", 118)
    f.setBold(True)
    p.setFont(f)
    p.setPen(QColor("#FFFFFF"))
    p.drawText(QRectF(12, 12, 232, 232), Qt.AlignmentFlag.AlignCenter, "L")
    p.end()
    return QIcon(pix)
