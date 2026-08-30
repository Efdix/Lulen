"""单实例:第二个进程把 "show" 发给首个进程后退出。

服务键按配置目录区分:默认安装只有一份配置 → 全机单实例;
LULEN_HOME 隔离的测试实例互不干扰,也不与正式实例冲突。
"""
from __future__ import annotations

import hashlib
import os

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket


def _server_key() -> str:
    home = os.environ.get("LULEN_HOME")
    if home:
        tag = hashlib.md5(home.encode("utf-8")).hexdigest()[:8]
        return f"Lulen-SingleInstance-{tag}-v1"
    return "Lulen-SingleInstance-v1"


class SingleInstance(QObject):
    another_show = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.is_primary = True
        self._server: QLocalServer | None = None

        key = _server_key()
        sock = QLocalSocket()
        sock.connectToServer(key)
        if sock.waitForConnected(300):
            sock.write(b"show")
            sock.flush()
            sock.waitForBytesWritten(300)
            sock.disconnectFromServer()
            self.is_primary = False
            return

        QLocalServer.removeServer(key)  # 清理崩溃残留
        self._server = QLocalServer()
        self._server.newConnection.connect(self._on_connection)
        self._server.listen(key)

    def _on_connection(self) -> None:
        sock = self._server.nextPendingConnection()
        if sock is None:
            return

        def _emit() -> None:
            if sock.bytesAvailable() or sock.waitForReadyRead(200):
                sock.readAll()
            self.another_show.emit()
            sock.deleteLater()

        QTimer.singleShot(40, _emit)
