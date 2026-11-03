"""把 @、评论、私信事件去重并持久化投递状态。"""

import hashlib
from datetime import datetime
from typing import Any

from loguru import logger

_EVENT_METHODS = {
    'get_at_messages', 'get_comments', 'get_comment_thread',
    'get_private_messages',
}
_DELIVERY_WINDOW_SECONDS = 600
_MAX_DELIVERIES = 3


def filter_agent_events(db, method: str, params: dict, result: Any) -> Any:
    """丢弃已经投递过的事件，保证每条 @/评论/私信只处理一次。"""
    if db is None or not isinstance(result, list):
        return result
    if method not in _EVENT_METHODS:
        return result
    if method == 'get_comments' and not (
        params.get('root_rpids') or params.get('include_replies')
    ):
        return result

    own = set()
    if method in {'get_comments', 'get_comment_thread'}:
        try:
            own_ids = db.get_own_comment_rpids()
            if isinstance(own_ids, (set, list, tuple)):
                own = set(own_ids)
        except Exception:  # noqa: BLE001
            own = set()

    records = []
    for item in result:
        if not isinstance(item, dict):
            continue
        rpid = item.get('rpid')
        if method in {'get_comments', 'get_comment_thread'} and rpid in own:
            continue
        if method == 'get_at_messages':
            key = f'at:{rpid}'
            event_type = 'at'
        elif method == 'get_private_messages':
            talker_id = params.get('talker_id') or ''
            timestamp = item.get('timestamp') or 0
            digest = hashlib.sha1(
                str(item.get('content') or '').encode('utf-8')
            ).hexdigest()[:16]
            key = f'dm:{talker_id}:{timestamp}:{digest}'
            event_type = 'dm'
        else:
            key = f'comment:{rpid}'
            event_type = 'comment'
        records.append({
            'key': key,
            'type': event_type,
            'payload': {
                'rpid': rpid,
                'user': item.get('user') or item.get('nickname') or '',
                'content': str(item.get('content') or '')[:300],
                'aid': item.get('aid'),
                'bvid': item.get('bvid'),
            },
            '_item': item,
        })
    if not records:
        return result

    states = db.get_agent_event_states([item['key'] for item in records])
    now = datetime.now()
    new_items = []
    new_records = []
    for record in records:
        state = states.get(record['key']) or {}
        status = str(state.get('status') or '')
        if status in ('handled', 'ignored'):
            continue
        if status == 'delivered':
            last = state.get('last_delivered_at')
            count = int(state.get('delivery_count') or 0)
            if last and count < _MAX_DELIVERIES and (
                now - last
            ).total_seconds() < _DELIVERY_WINDOW_SECONDS:
                continue
            if count >= _MAX_DELIVERIES:
                continue
        new_items.append(record.pop('_item'))
        new_records.append(record)
    try:
        db.deliver_agent_events(new_records)
    except (AttributeError, TypeError, ValueError) as exc:
        logger.debug(f'记录事件状态失败: {exc}')
    return new_items
