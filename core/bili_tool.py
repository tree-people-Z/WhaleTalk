"""Expose the public BilibiliAPI surface as one agent tool."""

import inspect
import json
from typing import Any

from loguru import logger

_EXCLUDED = {
    'login_with_qr', 'check_qr_status', 'check_login',
    'set_blocked', 'set_posting_blocked',
    'get_my_info',
}
_WRITE_METHODS = {
    'post_comment', 'send_private_message', 'send_danmaku',
    'post_video_dynamic', 'repost_latest_user_dynamic',
    'repost_video_author_dynamic', 'like_video', 'like_comment',
    'like_latest_user_dynamic', 'like_video_author_dynamic',
    'like_video_danmaku', 'favorite_video', 'follow_user',
    'follow_video_author', 'coin_video', 'share_video',
    'add_to_watch_later', 'report_watch',
}


def _short(value: Any) -> Any:
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, (list, tuple)):
        return [_short(item) for item in value[:5]]
    if isinstance(value, dict):
        return {str(key): _short(item) for key, item in list(value.items())[:12]}
    return str(value)


class BiliTool:
    """Single generic tool so the model can choose any public B站 method."""

    def __init__(self, bili, db=None, config=None):
        self.bili = bili
        self.db = db
        self.config = config
        self.writes = 0
        self.max_writes = 8
        self._specs = self._build_specs()

    def _build_specs(self) -> list[dict]:
        methods = []
        for name in dir(self.bili):
            if name.startswith('_') or name in _EXCLUDED:
                continue
            try:
                attr = getattr(self.bili, name)
            except Exception:  # noqa: BLE001
                continue
            if not callable(attr):
                continue
            try:
                signature = inspect.signature(attr)
            except (TypeError, ValueError):
                continue
            params = []
            for param in signature.parameters.values():
                if param.name == 'self':
                    continue
                item = {'name': param.name}
                if param.default is not inspect.Parameter.empty:
                    item['default'] = repr(param.default)
                params.append(item)
            doc = (inspect.getdoc(attr) or '').splitlines()
            methods.append({
                'name': name,
                'params': params,
                'doc': doc[0][:120] if doc else '',
            })
        return sorted(methods, key=lambda item: item['name'])

    def spec(self) -> dict:
        return {
            'name': 'bili_api',
            'description': (
                '调用 B 站接口。method 取下面 methods 里的名字，'
                'arguments 是该方法的参数对象。读、写接口都在这里，自己判断。'
            ),
            'parameters': {
                'method': 'string',
                'arguments': 'object(可选)',
            },
            'methods': self._specs,
        }

    @property
    def method_names(self) -> set:
        return {item['name'] for item in self._specs}

    def _check_write(self, method: str, args: dict) -> str:
        if method not in _WRITE_METHODS:
            return ''
        if self.writes >= self.max_writes:
            return f'本轮写操作已达上限 {self.max_writes} 次'
        if method in {'post_comment', 'send_private_message', 'send_danmaku',
                      'post_video_dynamic'}:
            try:
                if self.bili.is_posting_blocked():
                    return '当前处于发帖冷却/风控状态，写操作已暂停'
            except Exception:  # noqa: BLE001
                pass
        if method == 'post_comment' and self.db is not None:
            try:
                maximum = int(self.config.get('limits.max_comments_per_day', 60))
            except Exception:  # noqa: BLE001
                maximum = 60
            try:
                used = int(self.db.get_today_comment_count(include_replies=True))
            except Exception:  # noqa: BLE001
                used = 0
            if used >= maximum:
                return f'今日评论/回复已达上限 {maximum} 条'
        return ''

    async def call(self, method: str, arguments: dict | None = None) -> Any:
        if method not in {item['name'] for item in self._specs}:
            return {'error': f'没有这个接口: {method}'}
        args = arguments or {}
        if not isinstance(args, dict):
            return {'error': 'arguments 必须是对象'}
        blocked = self._check_write(method, args)
        if blocked:
            return {'error': blocked}
        extra_bvid = str(args.get('bvid') or '')
        call_args = {
            key: value for key, value in args.items()
            if key not in {'bvid', 'video_title'}
        }
        try:
            result = getattr(self.bili, method)(**call_args)
            if inspect.isawaitable(result):
                result = await result
            if method in _WRITE_METHODS:
                self.writes += 1
                if method == 'post_comment' and self.db is not None:
                    await self._record_comment(call_args, extra_bvid, bool(result))
            return result
        except TypeError as exc:
            return {'error': f'参数不匹配: {exc}'}
        except Exception as exc:  # noqa: BLE001
            logger.warning(f'自由 Agent 调用 {method} 失败: {exc}')
            return {'error': str(exc)}

    async def _record_comment(self, args: dict, bvid: str, success: bool) -> None:
        aid = int(args.get('aid') or 0)
        title = ''
        author = ''
        if not bvid and aid and hasattr(self.bili, 'get_video_info_by_aid'):
            try:
                info = await self.bili.get_video_info_by_aid(aid) or {}
                bvid = str(info.get('bvid') or '')
                title = str(info.get('title') or '')
                author = str(info.get('owner') or '')
            except Exception as exc:  # noqa: BLE001
                logger.debug(f'补全视频信息失败 aid={aid}: {exc}')
        try:
            self.db.add_comment_record(
                bvid=bvid,
                aid=aid,
                content=str(args.get('text') or ''),
                comment_type='reply' if args.get('root_rpid') or args.get('parent_rpid') else 'post',
                success=success,
                rpid=getattr(self.bili, 'last_comment_rpid', None),
                parent_rpid=args.get('parent_rpid'),
                thread_root=args.get('root_rpid'),
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(f'记录自由 Agent 评论失败: {exc}')
        if bvid and title:
            try:
                self.db.ensure_video_record(bvid, aid, title, author)
            except Exception as exc:  # noqa: BLE001
                logger.debug(f'补全视频记录失败: {exc}')

    @staticmethod
    def dump(result: Any, limit: int = 4000) -> str:
        data = _short(result)
        try:
            return json.dumps(data, ensure_ascii=False, default=str)[:limit]
        except Exception:  # noqa: BLE001
            return str(data)[:limit]
