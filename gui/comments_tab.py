"""评论对话面板：清晰查看自己发出的评论/回复与网友回复。"""

import asyncio
import datetime
import html
import time
from typing import Any, Dict, List

from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QAbstractItemView, QHBoxLayout, QHeaderView, QLabel, QPushButton,
    QSplitter, QTableWidget, QTableWidgetItem, QTextEdit, QVBoxLayout, QWidget,
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
    """展示「我的评论/回复 + 网友回复」的评论区对话。"""

    HEADERS = ['类型', '时间', '视频 / 对象', '内容']

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

        self.thread_table = QTableWidget(0, len(self.HEADERS))
        self.thread_table.setHorizontalHeaderLabels(self.HEADERS)
        self.thread_table.verticalHeader().setVisible(False)
        self.thread_table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.thread_table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.thread_table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.thread_table.setShowGrid(False)
        self.thread_table.setAlternatingRowColors(True)
        self.thread_table.setStyleSheet(
            "QTableWidget { border: 1px solid #e5e7eb; border-radius: 8px; }"
            "QTableWidget::item { padding: 6px 8px; }"
            "QHeaderView::section { background: #f8fafc; padding: 6px;"
            " border: none; border-bottom: 1px solid #e5e7eb; font-weight: 600; }"
        )
        header = self.thread_table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.Stretch)
        self.thread_table.setColumnWidth(1, 92)
        self.thread_table.setMinimumWidth(360)
        self.thread_table.itemSelectionChanged.connect(self._on_selection_changed)
        splitter.addWidget(self.thread_table)

        self.transcript = QTextEdit()
        self.transcript.setReadOnly(True)
        self.transcript.setPlaceholderText("选择左侧记录查看评论对话")
        self.transcript.setStyleSheet(
            "QTextEdit { border: 1px solid #e5e7eb; border-radius: 8px;"
            " padding: 8px; background: #ffffff; }"
        )
        splitter.addWidget(self.transcript)
        splitter.setSizes([430, 560])
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

    # ------------------------------------------------------------------ data
    def refresh_threads(self):
        if self._worker is not None and self._worker.isRunning():
            return
        try:
            self.threads = self.db.get_recent_comments(limit=500, include_replies=True)
            self.own_rpids = self.db.get_own_comment_rpids()
        except Exception as exc:  # noqa: BLE001
            self.status_label.setText(f"读取评论记录失败：{exc}")
            return
        self._loaded_at = time.time()
        self.thread_table.setRowCount(0)
        self.thread_table.setRowCount(len(self.threads))
        for row, thread in enumerate(self.threads):
            self._fill_row(row, thread)
        if self.threads:
            self.status_label.setText(f"共 {len(self.threads)} 条已发评论/回复")
            self.thread_table.selectRow(0)
            self._load_thread(self.threads[0])
        else:
            self.status_label.setText("还没有发送过评论或回复")
            self.transcript.setHtml("")

    def _fill_row(self, row: int, thread: Dict[str, Any]):
        commented_at = thread.get('commented_at')
        when = (
            commented_at.strftime('%m-%d %H:%M')
            if hasattr(commented_at, 'strftime') else ''
        )
        title = thread.get('video_title') or thread.get('bvid') or '视频'
        content = (thread.get('content') or '').replace('\n', ' ')
        target = thread.get('target_user') or ''
        is_reply = thread.get('comment_type') == 'reply'
        notified = thread.get('aid') in self._notified_aids
        type_text = ('🔔 ' if notified else '') + ('回复' if is_reply else '评论')
        if is_reply:
            object_text = f'回复 @{target}' if target else '回复评论'
        else:
            object_text = title

        type_item = QTableWidgetItem(type_text)
        type_item.setData(Qt.ItemDataRole.UserRole, thread)
        type_item.setToolTip(title)
        if is_reply:
            type_item.setForeground(QColor('#1d4ed8'))
        else:
            type_item.setForeground(QColor('#15803d'))

        when_item = QTableWidgetItem(when)
        object_item = QTableWidgetItem(object_text)
        object_item.setToolTip(title)
        content_item = QTableWidgetItem(content)
        content_item.setToolTip(content)

        for column, item in enumerate(
            (type_item, when_item, object_item, content_item)
        ):
            self.thread_table.setItem(row, column, item)
        self.thread_table.setRowHeight(row, 34)

    # --------------------------------------------------------------- selection
    def _current_thread(self) -> Dict[str, Any]:
        row = self.thread_table.currentRow()
        if row < 0:
            return {}
        item = self.thread_table.item(row, 0)
        return (item.data(Qt.ItemDataRole.UserRole) or {}) if item else {}

    def _on_selection_changed(self):
        self.notice_label.hide()
        thread = self._current_thread()
        if thread:
            self._load_thread(thread)

    def _load_thread(self, thread: Dict[str, Any]):
        self._render_thread(thread, [])
        if self.bili_api is None or not getattr(self.bili_api, 'credential', None):
            self.status_label.setText("登录B站后可加载网友回复")
            return
        root_rpid = thread.get('thread_root') or thread.get('rpid')
        if not thread.get('aid') or not root_rpid:
            return
        if self._worker is not None and self._worker.isRunning():
            return
        self.status_label.setText("正在加载评论对话…")
        worker = ThreadLoadWorker(self.bili_api, thread['aid'], root_rpid, self)
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

    # --------------------------------------------------------------- rendering
    def _render_thread(self, thread: Dict[str, Any], replies: List[Dict[str, Any]]):
        commented_at = thread.get('commented_at')
        when = (
            commented_at.strftime('%Y-%m-%d %H:%M')
            if hasattr(commented_at, 'strftime') else ''
        )
        title = html.escape(thread.get('video_title') or '评论对话')
        content = html.escape(thread.get('content') or '').replace('\n', '<br>')
        if thread.get('comment_type') == 'reply':
            target = html.escape(thread.get('target_user') or '评论')
            mine_label = f'我 · 回复 @{target}'
        else:
            mine_label = '我 · 评论'

        parts = [
            '<div style="font-family:\'Microsoft YaHei\',sans-serif;'
            ' font-size:13px; color:#1f2937; line-height:1.65;">',
            '<div style="background:#f5f8ff; border:1px solid #dbe7ff;'
            ' border-radius:10px; padding:10px 12px; margin-bottom:14px;">',
            f'<div style="color:#8a94a6; font-size:12px;">{title}'
            f' · {when}</div>',
            f'<div style="color:#2563eb; font-weight:700; margin-top:2px;">'
            f'{mine_label}</div>',
            f'<div style="margin-top:4px;">{content}</div>',
            '</div>',
        ]

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
            who = html.escape(comment.get('user') or '未知用户')
            is_own = rpid in self.own_rpids
            who_color = '#2563eb' if is_own else '#374151'
            suffix = '（我）' if is_own else ''
            body = html.escape(comment.get('content') or '').replace('\n', '<br>')
            parts.extend([
                '<div style="border-left:3px solid #e5e7eb;'
                ' padding:2px 0 2px 10px; margin:0 0 11px 2px;">',
                f'<div><span style="color:#9aa3b2; font-size:12px;">'
                f'{timestamp}</span> '
                f'<span style="color:{who_color}; font-weight:700;">'
                f'{who}{suffix}</span></div>',
                f'<div style="margin-top:2px;">{body}</div>',
                '</div>',
            ])

        if count == 0:
            parts.append(
                '<div style="color:#9aa3b2; font-size:12px; padding:6px 2px;">'
                '暂无网友回复</div>'
            )
        parts.append('</div>')
        self.transcript.setHtml(''.join(parts))
        if count:
            self.status_label.setText(f"{thread.get('video_title') or '评论对话'}"
                                      f" · {count} 条回复")
        else:
            self.status_label.setText(f"{thread.get('video_title') or '评论对话'}"
                                      f" · 暂无网友回复")

    def _on_failed(self, message: str):
        self.status_label.setText(f"加载评论对话失败：{message}")
        logger.warning(f"评论对话加载失败: {message}")

    # ------------------------------------------------------------------ notice
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
        """Mark rows whose video received a newly detected reply."""
        for row, thread in enumerate(self.threads):
            if thread.get('aid') not in self._notified_aids:
                continue
            item = self.thread_table.item(row, 0)
            if item is not None and not item.text().startswith('🔔'):
                item.setText('🔔 ' + item.text())

    def shutdown(self, timeout_ms: int = 2000):
        if self._worker is not None and self._worker.isRunning():
            self._worker.wait(timeout_ms)
