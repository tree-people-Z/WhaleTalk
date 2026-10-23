"""私信会话面板：查看与用户的私信对话。"""

import asyncio
import datetime
import time
from typing import Any, Dict, List

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtWidgets import (
    QHBoxLayout, QLabel, QListWidget, QListWidgetItem, QPushButton,
    QSplitter, QTextEdit, QVBoxLayout, QWidget,
)
from loguru import logger


class SessionLoadWorker(QThread):
    """Load the private-message session list in the background."""

    loaded = pyqtSignal(list, dict)
    failed = pyqtSignal(str)

    def __init__(self, bili_api, parent=None):
        super().__init__(parent)
        self.bili_api = bili_api

    def run(self):
        try:
            async def load():
                self_info = await self.bili_api.get_self_info()
                sessions = await self.bili_api.get_private_sessions()
                return sessions, self_info or {}

            sessions, self_info = asyncio.run(load())
            self.loaded.emit(sessions, self_info)
        except Exception as exc:  # noqa: BLE001
            logger.error(f"加载私信会话失败: {exc}")
            self.failed.emit(str(exc))


class MessageLoadWorker(QThread):
    """Load the messages of one private-message session in the background."""

    loaded = pyqtSignal(list)
    failed = pyqtSignal(str)

    def __init__(self, bili_api, talker_id: int, session_type: int = 1, parent=None):
        super().__init__(parent)
        self.bili_api = bili_api
        self.talker_id = talker_id
        self.session_type = session_type

    def run(self):
        try:
            messages = asyncio.run(
                self.bili_api.get_private_messages(self.talker_id, self.session_type)
            )
            self.loaded.emit(messages)
        except Exception as exc:  # noqa: BLE001
            logger.error(f"加载私信消息失败: {exc}")
            self.failed.emit(str(exc))


class MessagesTab(QWidget):
    """只读的私信会话浏览器。"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.bili_api = None
        self.self_uid = None
        self.sessions: List[Dict[str, Any]] = []
        self._session_worker = None
        self._message_worker = None
        self._loaded_at = 0.0
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        toolbar = QHBoxLayout()
        self.status_label = QLabel("请先登录B站账号后查看私信")
        self.refresh_btn = QPushButton("🔄 刷新私信")
        self.refresh_btn.clicked.connect(self.refresh_sessions)
        toolbar.addWidget(self.status_label, 1)
        toolbar.addWidget(self.refresh_btn)
        layout.addLayout(toolbar)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.session_list = QListWidget()
        self.session_list.setMinimumWidth(220)
        self.session_list.itemClicked.connect(self._on_session_selected)
        splitter.addWidget(self.session_list)

        self.message_view = QTextEdit()
        self.message_view.setReadOnly(True)
        self.message_view.setPlaceholderText("选择左侧会话查看私信内容")
        splitter.addWidget(self.message_view)
        splitter.setSizes([300, 620])
        layout.addWidget(splitter, 1)

    def set_bili_api(self, bili_api):
        self.bili_api = bili_api
        self._loaded_at = 0.0
        if bili_api is None or not getattr(bili_api, 'credential', None):
            self.status_label.setText("请先登录B站账号后查看私信")
            return
        self.status_label.setText("切换到本页或点击“刷新私信”加载")

    def refresh_if_stale(self, seconds: float = 60.0):
        if time.time() - self._loaded_at >= seconds:
            self.refresh_sessions()

    def refresh_sessions(self):
        if self.bili_api is None or not getattr(self.bili_api, 'credential', None):
            self.status_label.setText("请先登录B站账号后查看私信")
            return
        if self._session_worker is not None and self._session_worker.isRunning():
            return
        self.refresh_btn.setEnabled(False)
        self.status_label.setText("正在加载私信会话…")
        worker = SessionLoadWorker(self.bili_api, self)
        self._session_worker = worker
        worker.loaded.connect(self._on_sessions_loaded)
        worker.failed.connect(self._on_load_failed)
        worker.finished.connect(lambda: self._finish_worker(worker, 'session'))
        worker.start()

    def _finish_worker(self, worker, kind: str):
        worker.deleteLater()
        if kind == 'session' and self._session_worker is worker:
            self._session_worker = None
            self.refresh_btn.setEnabled(True)
        if kind == 'message' and self._message_worker is worker:
            self._message_worker = None

    def _on_sessions_loaded(self, sessions, self_info):
        self.sessions = sessions or []
        self.self_uid = (self_info or {}).get('uid')
        self._loaded_at = time.time()
        self.session_list.clear()
        for session in self.sessions:
            name = session.get('name') or f"UID {session.get('talker_id')}"
            unread = session.get('unread') or 0
            preview = (session.get('last_message') or '').replace('\n', ' ')[:40]
            label = name + (f"  🔴{unread}" if unread else '')
            if preview:
                label += f"\n{preview}"
            item = QListWidgetItem(label)
            item.setData(Qt.ItemDataRole.UserRole, session)
            self.session_list.addItem(item)
        if self.sessions:
            self.status_label.setText(f"共 {len(self.sessions)} 个私信会话")
            self.session_list.setCurrentRow(0)
            self._on_session_selected(self.session_list.item(0))
        else:
            self.status_label.setText("暂无未读私信会话")
            self.message_view.setPlainText("")

    def _on_session_selected(self, item):
        if item is None:
            return
        session = item.data(Qt.ItemDataRole.UserRole) or {}
        talker_id = session.get('talker_id')
        if not talker_id:
            return
        if self._message_worker is not None and self._message_worker.isRunning():
            return
        self.status_label.setText(f"正在加载与 {session.get('name')} 的对话…")
        self.message_view.setPlainText("")
        worker = MessageLoadWorker(
            self.bili_api, talker_id, session.get('session_type') or 1, self
        )
        self._message_worker = worker
        worker.loaded.connect(lambda messages: self._render_messages(messages, session))
        worker.failed.connect(self._on_load_failed)
        worker.finished.connect(lambda: self._finish_worker(worker, 'message'))
        worker.start()

    def _render_messages(self, messages, session):
        lines = []
        for message in messages or []:
            is_self = self.self_uid is not None and message.get('sender_uid') == self.self_uid
            sender = '我' if is_self else (session.get('name') or f"UID {session.get('talker_id')}")
            timestamp = message.get('timestamp') or 0
            when = (
                datetime.datetime.fromtimestamp(timestamp).strftime('%m-%d %H:%M')
                if timestamp else '--'
            )
            lines.append(f"[{when}] {sender}：{message.get('content', '')}")
        self.message_view.setPlainText("\n".join(lines) if lines else "（没有可显示的消息）")
        self.status_label.setText(f"{session.get('name')} · {len(messages or [])} 条消息")

    def _on_load_failed(self, message: str):
        self.status_label.setText(f"加载失败：{message}")
        logger.warning(f"私信面板加载失败: {message}")
