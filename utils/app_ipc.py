"""跨进程的「请优雅退出」通道。

鲸语是托盘程序：`closeEvent` 默认只隐藏窗口，所以 `taskkill`（不带 /F）、
任务管理器结束任务、以及各种脚本发来的 WM_CLOSE 都不会真正退出进程，
只能强杀，留下残留的 `data/app.lock` 和写着「后台任务仍在等待网络请求
结束」的半截日志。

这里用本地套接字补一条明确通路：

- 运行中的实例启动一个 `QLocalServer`（管道名按数据目录派生，开发版和
  安装版互不干扰）；
- `WhaleTalk.exe --quit` 连上去发一行 `quit`，由主线程走完整的退出流程
  （保存设置、停调度、关数据库、释放锁）。

本地套接字名在 Windows 上是命名管道，在其它平台是 Unix socket，两边
语义一致，不需要平台分支。
"""

import hashlib
from pathlib import Path
from typing import Optional

from loguru import logger
from PyQt6.QtCore import QObject, pyqtSignal
from PyQt6.QtNetwork import QLocalServer, QLocalSocket

QUIT_COMMAND = 'quit'
_OK_REPLY = b'ok'


def server_name(data_dir: Path = Path('data')) -> str:
    """按数据目录派生管道名，避免不同安装互相抢同一个名字。"""
    resolved = str(Path(data_dir).resolve()).lower()
    digest = hashlib.sha1(resolved.encode('utf-8')).hexdigest()[:12]
    return f'whaletalk-quit-{digest}'


def is_quit_command(payload: bytes) -> bool:
    """只认 ``quit`` 这一行，其它内容一律忽略（不对外当命令通道用）。"""
    try:
        text = payload.decode('utf-8', 'replace')
    except Exception:  # noqa: BLE001 - 解码不该让监听线程出错
        return False
    return text.strip().lower() == QUIT_COMMAND


class QuitServer(QObject):
    """在主线程上等待 ``quit`` 请求，收到后发信号走正常退出流程。"""

    quit_requested = pyqtSignal()

    def __init__(self, data_dir: Path = Path('data'), parent: Optional[QObject] = None):
        super().__init__(parent)
        self._name = server_name(data_dir)
        self._server: Optional[QLocalServer] = None
        # 上一个进程被强杀时命名管道可能残留，先清掉再监听。
        QLocalServer.removeServer(self._name)
        server = QLocalServer(self)
        server.setSocketOptions(QLocalServer.SocketOption.UserAccessOption)
        if server.listen(self._name):
            server.newConnection.connect(self._on_new_connection)
            self._server = server
            logger.debug(f'退出通道已监听: {self._name}')
        else:
            logger.warning(f'退出通道监听失败（--quit 将不可用）: {server.errorString()}')

    def close(self) -> None:
        """停止监听并移除管道，退出前调用。"""
        if self._server is None:
            return
        self._server.close()
        QLocalServer.removeServer(self._name)
        self._server = None

    def _on_new_connection(self) -> None:
        if self._server is None:
            return
        # 一次性处理所有待接入连接，避免请求排队等待事件循环。
        while self._server.hasPendingConnections():
            socket = self._server.nextPendingConnection()
            if socket is None:
                continue
            socket.readyRead.connect(lambda s=socket: self._on_ready_read(s))
            socket.disconnected.connect(socket.deleteLater)
            if socket.bytesAvailable():
                self._on_ready_read(socket)

    def _on_ready_read(self, socket: QLocalSocket) -> None:
        payload = bytes(socket.readAll())
        if not is_quit_command(payload):
            socket.disconnectFromServer()
            return
        logger.info('收到退出请求，开始关闭鲸语')
        socket.write(_OK_REPLY)
        socket.flush()
        socket.waitForBytesWritten(1000)
        socket.disconnectFromServer()
        self.quit_requested.emit()


def is_running(data_dir: Path = Path('data'), timeout_ms: int = 200) -> bool:
    """只探测有没有实例在监听，不发任何命令。"""
    socket = QLocalSocket()
    socket.connectToServer(server_name(data_dir))
    connected = socket.waitForConnected(timeout_ms)
    socket.disconnectFromServer()
    return connected


def request_quit(data_dir: Path = Path('data'), timeout_ms: int = 5000) -> bool:
    """把退出请求发给正在运行的实例；没有实例在跑时返回 ``False``。"""
    socket = QLocalSocket()
    socket.connectToServer(server_name(data_dir))
    if not socket.waitForConnected(timeout_ms):
        return False
    socket.write((QUIT_COMMAND + '\n').encode('utf-8'))
    socket.flush()
    delivered = socket.waitForBytesWritten(timeout_ms)
    # 回包只是确认，不等它：实例可能正卡在长网络请求里，主线程稍后才处理。
    socket.disconnectFromServer()
    if socket.state() != QLocalSocket.LocalSocketState.UnconnectedState:
        socket.waitForDisconnected(1000)
    return delivered
