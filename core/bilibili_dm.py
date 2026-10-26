"""B站私信与 @ 通知能力。"""

import json
import re
from typing import Any, Dict, List

from bilibili_api import session as bili_session
from bilibili_api.session import EventType
from loguru import logger


class BiliDMMixin:
    @staticmethod
    def _message_text(message: Dict[str, Any]) -> str:
        """Extract readable text from a private-message payload."""
        content = message.get('content')
        if isinstance(content, str):
            try:
                content = json.loads(content)
            except (TypeError, ValueError):
                return content.strip()
        if isinstance(content, dict):
            for key in ('content', 'text', 'title'):
                value = content.get(key)
                if isinstance(value, str) and value.strip():
                    return value.strip()
            return '[非文本消息]'
        return '' if content is None else str(content)

    async def get_at_messages(self, since_time: int = 0) -> List[Dict[str, Any]]:
        """Read B站 @ notifications, including comments in new threads."""
        if not self.credential:
            return []
        try:
            data = await bili_session.get_at(self.credential)
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"获取@消息失败: {exc}")
            return []
        results = []
        for entry in (data or {}).get('items') or []:
            inner = entry.get('item') or {}
            user = entry.get('user') or {}
            at_time = int(entry.get('at_time') or 0)
            if at_time <= since_time:
                continue
            uri = inner.get('uri') or inner.get('native_uri') or ''
            match = re.search(r'(BV[0-9A-Za-z]+)', uri)
            if not match:
                continue
            bvid = match.group(1)
            source_id = inner.get('source_id') or inner.get('target_id')
            if not source_id:
                continue
            root_id = inner.get('root_id') or 0
            content = inner.get('source_content') or inner.get('title') or ''
            results.append({
                'rpid': int(source_id),
                'root_rpid': int(root_id) if root_id else int(source_id),
                'bvid': bvid,
                'aid': int(inner.get('subject_id') or 0),
                'user': user.get('nickname') or '',
                'mid': user.get('mid'),
                'content': content,
                'at_time': at_time,
                'type': 'at',
            })
        return results

    async def get_private_sessions(self, session_type: int = 1) -> List[Dict[str, Any]]:
        """获取私信会话列表。session_type: 1 私信, 4 全部。"""
        if not self.credential:
            return []
        try:
            data = await bili_session.get_sessions(
                credential=self.credential, session_type=session_type
            )
        except Exception as exc:
            logger.warning(f"获取私信会话失败: {exc}")
            return []

        sessions = []
        for item in (data.get('session_list') or []):
            talker_id = item.get('talker_id')
            if not talker_id:
                continue
            last = item.get('last_msg') or {}
            account = item.get('account_info') or {}
            sessions.append({
                'talker_id': int(talker_id),
                'session_type': item.get('session_type') or session_type,
                'name': account.get('name') or item.get('name') or f'UID {talker_id}',
                'unread': int(item.get('unread_count') or 0),
                'last_message': self._message_text(last),
                'last_sender_uid': last.get('sender_uid'),
                'last_timestamp': int(last.get('timestamp') or item.get('top_ts') or 0),
            })
        sessions.sort(key=lambda row: row.get('last_timestamp') or 0, reverse=True)
        return sessions

    @staticmethod
    def _message_image_url(message: Dict[str, Any]) -> str:
        content = message.get('content')
        if isinstance(content, str):
            try:
                content = json.loads(content)
            except (TypeError, ValueError):
                return ''
        if isinstance(content, dict):
            for key in ('url', 'image_url', 'img_src', 'original'):
                value = content.get(key)
                if isinstance(value, str) and value.startswith('http'):
                    return value
        return ''

    async def get_private_messages(
        self, talker_id: int, session_type: int = 1
    ) -> List[Dict[str, Any]]:
        """获取与某个用户的私信消息（按时间升序）。"""
        if not self.credential:
            return []
        try:
            data = await bili_session.fetch_session_msgs(
                talker_id=int(talker_id),
                credential=self.credential,
                session_type=session_type,
            )
        except Exception as exc:
            logger.warning(f"获取私信消息失败 talker={talker_id}: {exc}")
            return []

        messages = []
        for item in (data.get('messages') or []):
            if item.get('msg_type') == 5:  # 撤回的消息
                content = '[消息已撤回]'
            else:
                content = self._message_text(item)
            messages.append({
                'sender_uid': item.get('sender_uid'),
                'timestamp': int(item.get('timestamp') or 0),
                'content': content,
                'image_url': self._message_image_url(item),
                'msg_type': item.get('msg_type'),
            })
        messages.sort(key=lambda row: row.get('timestamp') or 0)
        return messages

    async def send_private_message(self, talker_id: int, text: str) -> bool:
        """给私信会话对象发送纯文本消息。"""
        if not self.credential or not talker_id or not text.strip():
            return False
        try:
            await bili_session.send_msg(
                credential=self.credential,
                receiver_id=int(talker_id),
                msg_type=EventType.TEXT,
                content=text.strip(),
            )
            logger.info(f"私信发送成功: {talker_id}")
            return True
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"私信发送失败 {talker_id}: {self._short_error(str(exc))}")
            return False
