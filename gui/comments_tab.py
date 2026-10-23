"""评论区对话面板：查看自己发出的评论楼层与网友回复。"""

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


class ThreadLoadWorker(QThread):
    """Load the replies of one comment thread in the background."""

    loaded = pyqtSignal(list)
    failed = pyqtSignal(str)

    def __init__(self, bili_api, aid: int, root_rpid: int, parent=None):
        super().__init__(parent)
        self.bili_api = bili_api
        self.aid = aid
        self.root_rpid = root_rpid

    def run(self):
        try:
            replies = asyncio.run(
                self.bili_api.get_comment_thread(self.aid, self.root_rpid)
            )
            self.loaded.emit(replies)
        except Exception as exc:  # noqa: BLE001
            logger.error(f"加载评论对话失败: {exc}")
            self.failed.emit(str(exc))


class CommentsTab(QWidget):
    """展示「我的评论 + 网友回复」的评论区对话。"""

    def __init__(self, db, parent=None):
        super().__init__(parent)
        self.db = db
        self.bili_api = None
        self.threads: List[Dict[str, Any]] = []
        self.own_rpids = set()
        self._worker = None
        self._loaded_at = 0.0
        self._notified_aids = set()
        self._build_ui()

    def _build_ui(self):
        layout = QVBoxLayout(self)
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(8)

        toolbar = QHBoxLayout()
        self.status_label = QLabel("切换到本页或点击“刷新评论”加载")
        self.refresh_btn = QPushButton("🔄 刷新评论")
        self.refresh_btn.clicked.connect(self.refresh_threads)
        toolbar.addWidget(self.status_label, 1)
        toolbar.addWidget(self.refresh_btn)
        layout.addLayout(toolbar)

        self.notice_label = QLabel("")
        self.notice_label.setWordWrap(True)
        self.notice_label.setStyleSheet(
            "background-color: #fff7e0; border: 1px solid #f0d38a; border-radius: 8px;"
            " padding: 10px 12px; color: #6b4b00;"
        )
        self.notice_label.hide()
        layout.addWidget(self.notice_label)

        splitter = QSplitter(Qt.Orientation.Horizontal)
        self.thread_list = QListWidget()
        self.thread_list.setMinimumWidth(240)
        self.thread_list.itemClicked.connect(self._on_user_selected_thread)
        splitter.addWidget(self.thread_list)

        self.transcript = QTextEdit()
        self.transcript.setReadOnly(True)
        self.transcript.setPlaceholderText("选择左侧评论查看对话")
        splitter.addWidget(self.transcript)
        splitter.setSizes([300, 620])
        layout.addWidget(splitter, 1)

    def set_bili_api(self, bili_api):
        self.bili_api = bili_api
        self._loaded_at = 0.0
        if bili_api is None or not getattr(bili_api, 'credential', None):
            self.status_label.setText("请先登录B站账号后加载网友回复")
        else:
            self.status_label.setText("切换到本页或点击“刷新评论”加载")

    def refresh_if_stale(self, seconds: float = 30.0):
        if time.time() - self._loaded_at >= seconds:
            self.refresh_threads()

    def refresh_threads(self):
        if self._worker is not None and self._worker.isRunning():
            return
        try:
            self.threads = self.db.get_recent_comments(limit=30)
            self.own_rpids = self.db.get_own_comment_rpids()
        except Exception as exc:  # noqa: BLE001
            self.status_label.setText(f"读取评论记录失败：{exc}")
            return
        self._loaded_at = time.time()
        self.thread_list.clear()
        for thread in self.threads:
            commented_at = thread.get('commented_at')
            when = (
                commented_at.strftime('%m-%d %H:%M')
                if hasattr(commented_at, 'strftime') else ''
            )
            title = thread.get('video_title') or thread.get('bvid') or '视频'
            content = (thread.get('content') or '').replace('\n', ' ')[:50]
            prefix = "🔔 " if thread.get('aid') in self._notified_aids else ""
            item = QListWidgetItem(f"{prefix}{title}\n{when} · {content}")
            item.setData(Qt.ItemDataRole.UserRole, thread)
            self.thread_list.addItem(item)
        if self.threads:
            self.status_label.setText(f"共 {len(self.threads)} 条评论对话")
            self.thread_list.setCurrentRow(0)
            self._on_thread_selected(self.thread_list.item(0))
        else:
            self.status_label.setText("还没有发送过评论")
            self.transcript.setPlainText("")

    def show_reply_notice(self, replies: List[Dict[str, Any]]):
        """Display a banner for newly detected replies and mark their threads."""
        if not replies:
            return
        for mention in replies:
            aid = mention.get('aid')
            if aid is not None:
                self._notified_aids.add(aid)
        lines = []
        for mention in replies[:3]:
            user = mention.get('user') or '网友'
            content = (mention.get('content') or '').replace('\n', ' ')[:60]
            lines.append(f"🔔 {user}：{content}")
        if len(replies) > 3:
            lines.append(f"…等 {len(replies)} 条新回复")
        self.notice_label.setText("收到新回复：\n" + "\n".join(lines))
        self.notice_label.show()
        self._mark_notified_threads()

    def _mark_notified_threads(self):
        """Mark thread rows that received a newly detected reply."""
        for row in range(self.thread_list.count()):
            item = self.thread_list.item(row)
            thread = item.data(Qt.ItemDataRole.UserRole) or {}
            if thread.get('aid') in self._notified_aids and not item.text().startswith("🔔"):
                item.setText("🔔 " + item.text())

    def _on_user_selected_thread(self, item):
        self.notice_label.hide()
        self._on_thread_selected(item)

    def _on_thread_selected(self, item):
        if item is None:
            return
        thread = item.data(Qt.ItemDataRole.UserRole) or {}
        self._render_thread(thread, [])
        if self.bili_api is None or not getattr(self.bili_api, 'credential', None):
            self.status_label.setText("登录B站后可加载网友回复")
            return
        if not thread.get('aid') or not thread.get('rpid'):
            return
        if self._worker is not None and self._worker.isRunning():
            return
        self.status_label.setText("正在加载评论对话…")
        worker = ThreadLoadWorker(self.bili_api, thread['aid'], thread['rpid'], self)
        self._worker = worker
        worker.loaded.connect(lambda replies: self._render_thread(thread, replies))
        worker.failed.connect(self._on_failed)
        worker.finished.connect(self._finish_worker)
        worker.start()

    def _finish_worker(self):
        worker = self.sender()
        if worker is not None:
            worker.deleteLater()
        if self._worker is worker:
            self._worker = None

    def _render_thread(self, thread: Dict[str, Any], replies: List[Dict[str, Any]]):
        lines = []
        commented_at = thread.get('commented_at')
        when = (
            commented_at.strftime('%m-%d %H:%M')
            if hasattr(commented_at, 'strftime') else ''
        )
        lines.append(f"[{when}] 我：{thread.get('content', '')}")
        count = 0
        for comment in replies or []:
            rpid = comment.get('rpid')
            if rpid == thread.get('rpid'):
                continue
            count += 1
            ctime = comment.get('ctime') or 0
            timestamp = (
                datetime.datetime.fromtimestamp(ctime).strftime('%m-%d %H:%M')
                if ctime else '--'
            )
            who = comment.get('user') or '未知用户'
            if rpid in self.own_rpids:
                who = f"{who}（我）"
            content = (comment.get('content') or '').replace('\n', ' ')
            lines.append(f"[{timestamp}] {who}：{content}")
        self.transcript.setPlainText("\n".join(lines))
        title = thread.get('video_title') or '评论对话'
        if count:
            self.status_label.setText(f"{title} · {count} 条回复")
        else:
            self.status_label.setText(f"{title} · 暂无网友回复")

    def _on_failed(self, message: str):
        self.status_label.setText(f"加载评论对话失败：{message}")
        logger.warning(f"评论对话加载失败: {message}")

    def shutdown(self, timeout_ms: int = 2000):
        if self._worker is not None and self._worker.isRunning():
            self._worker.wait(timeout_ms)
