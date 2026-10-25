"""评论对话面板：清晰查看自己发出的评论/回复与网友回复。"""

import asyncio
import datetime
import hashlib
import html
import time
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import urlparse

import requests
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
            self._cache_images(replies)
            self.loaded.emit(replies)
        except Exception as exc:  # noqa: BLE001
            logger.error(f"加载评论对话失败: {exc}")
            self.failed.emit(str(exc))

    @staticmethod
    def _cache_images(replies: List[Dict[str, Any]]):
        """把楼里的评论图片下载到本地，供 QTextEdit 直接显示。"""
        cache_dir = Path('data') / 'comment_images'
        try:
            cache_dir.mkdir(parents=True, exist_ok=True)
        except OSError:
            return
        headers = {
            'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
            'Referer': 'https://www.bilibili.com/',
        }
        for reply in replies or []:
            urls = reply.get('images') or []
            local = []
            for url in urls[:4]:
                suffix = Path(urlparse(url).path).suffix.lower()
                if suffix not in ('.jpg', '.jpeg', '.png', '.webp', '.gif'):
                    suffix = '.jpg'
                path = cache_dir / (hashlib.md5(url.encode('utf-8')).hexdigest() + suffix)
                if not path.exists():
                    try:
                        response = requests.get(url, headers=headers, timeout=8)
                        content = response.content or b''
                        if (
                            response.ok
                            and len(content) < 8 * 1024 * 1024
                            and response.headers.get('Content-Type', '').startswith('image/')
                        ):
                            path.write_bytes(content)
                    except Exception:  # noqa: BLE001
                        continue
                if path.exists():
                    local.append(str(path.resolve()))
            reply['local_images'] = local


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
    @staticmethod
    def _thread_key(thread: Dict[str, Any]) -> tuple:
        return (
            thread.get('aid'),
            thread.get('thread_root'),
            thread.get('comment_type'),
        )

    @staticmethod
    def _group_threads(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Merge records into one row per thread, falling back per video for old rows."""
        post_roots = {}
        for record in records:
            if record.get('comment_type') == 'post' and record.get('rpid'):
                post_roots.setdefault(record.get('aid'), set()).add(record.get('rpid'))

        grouped: Dict[tuple, List[Dict[str, Any]]] = {}
        for record in records:
            aid = record.get('aid') or 0
            comment_type = record.get('comment_type')
            known = bool(record.get('thread_root_known')) or comment_type == 'post'
            if known:
                root = record.get('rpid') if comment_type == 'post' else record.get('thread_root')
                key = (aid, 'thread', root)
            else:
                roots = post_roots.get(aid) or set()
                if len(roots) == 1:
                    key = (aid, 'thread', next(iter(roots)))
                else:
                    key = (aid, 'video', None)
            grouped.setdefault(key, []).append(record)

        merged = []
        for (aid, _kind, _root), items in grouped.items():
            items.sort(key=lambda item: item.get('commented_at') or datetime.datetime.min)
            post_record = next(
                (item for item in items if item.get('comment_type') == 'post'),
                None,
            )
            root_record = post_record or items[-1]
            group = dict(root_record)
            group['thread_root'] = (
                post_record.get('rpid') if post_record
                else (root_record.get('thread_root') or root_record.get('rpid'))
            )
            group['records'] = items
            group['my_count'] = len(items)
            group['last_at'] = items[-1].get('commented_at')
            group['last_content'] = items[-1].get('content') or ''
            group['content'] = root_record.get('content') or ''
            group['commented_at'] = root_record.get('commented_at')
            group['merged_by_video'] = not any(
                item.get('thread_root_known') or item.get('comment_type') == 'post'
                for item in items
            )
            merged.append(group)
        merged.sort(
            key=lambda group: group.get('last_at') or datetime.datetime.min,
            reverse=True,
        )
        return merged

    def refresh_threads(self):
        if self._worker is not None and self._worker.isRunning():
            return
        try:
            records = self.db.get_recent_comments(limit=500, include_replies=True)
            self.own_rpids = self.db.get_own_comment_rpids()
        except Exception as exc:  # noqa: BLE001
            self.status_label.setText(f"读取评论记录失败：{exc}")
            return
        groups = self._group_threads(records)
        signature = tuple(
            (
                group.get('aid'),
                group.get('thread_root'),
                group.get('my_count'),
                group.get('last_at'),
                group.get('last_content'),
            )
            for group in groups
        )
        if signature == getattr(self, '_signature', None):
            self.threads = groups
            self.status_label.setText(
                f"共 {len(groups)} 个评论楼（{len(records)} 条已发评论/回复）"
            )
            return
        self._signature = signature
        self.threads = groups
        self._loaded_at = time.time()

        selected = self._current_thread()
        selected_key = self._thread_key(selected) if selected else None
        scroll = self.thread_table.verticalScrollBar().value()

        self.thread_table.blockSignals(True)
        self.thread_table.setUpdatesEnabled(False)
        self.thread_table.setRowCount(0)
        self.thread_table.setRowCount(len(self.threads))
        for row, thread in enumerate(self.threads):
            self._fill_row(row, thread)
        target_row = 0
        if selected_key:
            for row, thread in enumerate(self.threads):
                if self._thread_key(thread) == selected_key:
                    target_row = row
                    break
        if self.threads:
            self.thread_table.selectRow(target_row)
            self.thread_table.scrollToItem(
                self.thread_table.item(target_row, 0)
            )
            self.thread_table.verticalScrollBar().setValue(scroll)
            self.status_label.setText(
                f"共 {len(self.threads)} 个评论楼（{len(records)} 条已发评论/回复）"
            )
        else:
            self.status_label.setText("还没有发送过评论或回复")
            self.transcript.setHtml("")
        self.thread_table.setUpdatesEnabled(True)
        self.thread_table.blockSignals(False)

        if self.threads:
            current = self._current_thread()
            current_key = self._thread_key(current)
            has_transcript = bool(self.transcript.toPlainText().strip())
            if not (selected_key == current_key and has_transcript):
                self._load_thread(current)
        self._loaded_at = time.time()

    def _fill_row(self, row: int, thread: Dict[str, Any]):
        commented_at = thread.get('last_at') or thread.get('commented_at')
        when = (
            commented_at.strftime('%m-%d %H:%M')
            if hasattr(commented_at, 'strftime') else ''
        )
        title = thread.get('video_title') or thread.get('bvid') or '视频'
        content = (thread.get('last_content') or thread.get('content') or '').replace('\n', ' ')
        count = int(thread.get('my_count') or 1)
        is_reply = thread.get('comment_type') == 'reply'
        notified = thread.get('aid') in self._notified_aids
        if count > 1:
            label = '视频楼' if thread.get('merged_by_video') else '楼'
            type_text = ('🔔 ' if notified else '') + f'{label}·{count}'
        else:
            type_text = ('🔔 ' if notified else '') + ('回复' if is_reply else '评论')
        object_text = title

        type_item = QTableWidgetItem(type_text)
        type_item.setData(Qt.ItemDataRole.UserRole, thread)
        type_item.setToolTip(f"{title}（本楼共 {count} 条记录）")
        if is_reply:
            type_item.setForeground(QColor('#1d4ed8'))
        else:
            type_item.setForeground(QColor('#15803d'))

        when_item = QTableWidgetItem(when)
        object_item = QTableWidgetItem(object_text)
        object_item.setToolTip(title)
        content_item = QTableWidgetItem(content)
        content_item.setToolTip(
            content + (f"\n本楼共 {count} 条，这里显示最新一条" if count > 1 else '')
        )

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
    @staticmethod
    def _fmt_time(value) -> str:
        if hasattr(value, 'strftime'):
            return value.strftime('%m-%d %H:%M')
        try:
            timestamp = int(value or 0)
            return (
                datetime.datetime.fromtimestamp(timestamp).strftime('%m-%d %H:%M')
                if timestamp else ''
            )
        except (TypeError, ValueError, OSError):
            return ''

    @staticmethod
    def _avatar(name: str, color: str = '#2563eb', size: int = 28,
                text: str = '') -> str:
        initial = html.escape(text or (name or '?')[:1])
        return (
            f'<div style="width:{size}px; height:{size}px; border-radius:{size // 2}px;'
            f' background:#e8f0ff; color:{color}; text-align:center;'
            f' line-height:{size}px; font-weight:700;">{initial}</div>'
        )

    @staticmethod
    def _images_html(comment: Dict[str, Any]) -> str:
        parts = []
        for path in comment.get('local_images') or []:
            try:
                uri = Path(path).as_uri()
            except (ValueError, OSError):
                continue
            parts.append(
                f'<div style="margin-top:6px;"><img src="{uri}" width="200"></div>'
            )
        if not parts and comment.get('images'):
            parts.append(
                '<div style="margin-top:5px; color:#9aa3b2; font-size:12px;">'
                '🖼 评论含图片（加载中或不可访问）</div>'
            )
        return ''.join(parts)

    @staticmethod
    def _reply_html(comment: Dict[str, Any], own_rpids: set, depth: int) -> str:
        rpid = comment.get('rpid')
        is_own = rpid in own_rpids
        user = html.escape(comment.get('user') or '未知用户')
        body = html.escape(comment.get('content') or '').replace('\n', '<br>')
        images = CommentsTab._images_html(comment)
        timestamp = CommentsTab._fmt_time(comment.get('ctime'))
        color = '#2563eb' if is_own else '#374151'
        badge = (
            '<span style="font-size:11px; color:#2563eb; background:#eef4ff;'
            ' border-radius:4px; padding:1px 5px;">我</span>'
            if is_own else ''
        )
        avatar = CommentsTab._avatar(
            comment.get('user') or '?', color, 24,
            '鱼' if is_own else (comment.get('user') or '?')[:1],
        )
        return (
            f'<div style="border-left:2px solid #eef1f6; margin-left:'
            f'{6 + depth * 16}px; padding:2px 0 2px 10px;">'
            '<table width="100%" cellspacing="0" cellpadding="0"><tr>'
            f'<td width="30" valign="top">{avatar}</td>'
            '<td valign="top" style="padding-left:6px;">'
            f'<div><b style="color:{color};">{user}</b> {badge}'
            f'<span style="color:#9aa3b2; font-size:12px;"> {timestamp}</span></div>'
            f'<div style="margin-top:3px; color:#1f2937;">{body}{images}</div>'
            '</td></tr></table></div>'
        )

    def _render_thread(self, thread: Dict[str, Any], replies: List[Dict[str, Any]]):
        root_rpid = thread.get('thread_root') or thread.get('rpid')
        comments = list(replies or [])
        by_rpid = {
            comment.get('rpid'): comment
            for comment in comments
            if comment.get('rpid')
        }
        root = by_rpid.get(root_rpid)
        root_is_me = root_rpid in self.own_rpids
        if root is None:
            if thread.get('comment_type') == 'reply':
                root = {
                    'rpid': root_rpid,
                    'user': thread.get('target_user') or '原评论',
                    'content': (
                        thread.get('parent_content')
                        or '（原评论内容未缓存，可在 B 站查看）'
                    ),
                    'ctime': None,
                }
            else:
                root = {
                    'rpid': thread.get('rpid'),
                    'user': '我',
                    'content': thread.get('content') or '',
                    'ctime': None,
                }
                root_is_me = True

        root_name = '我' if root_is_me else (root.get('user') or '未知用户')
        root_time = self._fmt_time(root.get('ctime')) or self._fmt_time(
            thread.get('commented_at')
        )
        root_content = html.escape(root.get('content') or '').replace('\n', '<br>')
        root_images = self._images_html(root)
        root_color = '#2563eb' if root_is_me else '#374151'
        root_avatar = self._avatar(
            root_name, root_color, 32, '鱼' if root_is_me else root_name[:1]
        )
        title = html.escape(thread.get('video_title') or '评论对话')

        items = [
            comment for comment in comments
            if comment.get('rpid') != root_rpid
        ]
        if (
            thread.get('comment_type') == 'reply'
            and thread.get('rpid') not in by_rpid
            and thread.get('content')
        ):
            items.append({
                'rpid': thread.get('rpid'),
                'user': '我',
                'content': thread.get('content'),
                'ctime': thread.get('commented_at'),
                'parent': root_rpid,
            })
        items.sort(key=lambda item: item.get('ctime') or 0)

        parts = [
            '<div style="font-family:\'Microsoft YaHei\',sans-serif;'
            ' font-size:13px; color:#1f2937; line-height:1.65;">',
            f'<div style="color:#8a94a6; font-size:12px;">{title}</div>',
            '<table width="100%" cellspacing="0" cellpadding="0"><tr>',
            f'<td width="38" valign="top" style="padding:10px 0 10px 8px;">'
            f'{root_avatar}</td>',
            '<td valign="top" style="padding:10px 10px 10px 6px;">',
            f'<div><b style="color:{root_color};">{html.escape(root_name)}</b> '
            '<span style="font-size:11px; color:#2563eb; background:#eef4ff;'
            ' border-radius:4px; padding:1px 5px;">楼主</span></div>',
            f'<div style="color:#9aa3b2; font-size:12px;">{root_time}</div>',
            f'<div style="margin-top:5px;">{root_content}{root_images}</div>',
            '</td></tr></table>',
        ]

        if items:
            parts.append(
                f'<div style="margin-top:14px; margin-bottom:8px; color:#8a94a6;'
                f' font-size:12px;">{len(items)} 条回复</div>'
            )
            for comment in items:
                parent = comment.get('parent') or 0
                depth = 1 if parent and parent != root_rpid else 0
                parts.append(self._reply_html(comment, self.own_rpids, depth))
        else:
            parts.append(
                '<div style="color:#9aa3b2; font-size:12px; padding:12px 4px;">'
                '暂无网友回复</div>'
            )
        parts.append('</div>')
        self.transcript.setHtml(''.join(parts))
        count = len(items)
        if count:
            self.status_label.setText(
                f"{thread.get('video_title') or '评论对话'} · {count} 条回复"
            )
        else:
            self.status_label.setText(
                f"{thread.get('video_title') or '评论对话'} · 暂无网友回复"
            )

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
