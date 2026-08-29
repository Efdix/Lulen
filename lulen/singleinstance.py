"""单实例:第二个进程把 "show" 发给首个进程后退出。"""
from __future__ import annotations

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtNetwork import QLocalServer, QLocalSocket

KEY = "Lulen-SingleInstance-v1"


class SingleInstance(QObject):
    another_show = Signal()

    def __init__(self, parent=None) -> None:
        super().__init__(parent)
        self.is_primary = True
        self._server: QLocalServer | None = None

        sock = QLocalSocket()
        sock.connectToServer(KEY)
        if sock.waitForConnected(300):
            sock.write(b"show")
            sock.flush()
            sock.waitForBytesWritten(300)
            sock.disconnectFromServer()
            self.is_primary = False
            return

        QLocalServer.removeServer(KEY)  # 清理崩溃残留
        self._server = QLocalServer()
        self._server.newConnection.connect(self._on_connection)
        self._server.listen(KEY)

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
