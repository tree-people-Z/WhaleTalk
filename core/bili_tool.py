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

_AID_METHODS = {
    'like_video', 'favorite_video', 'coin_video', 'share_video',
    'add_to_watch_later', 'report_watch', 'send_danmaku',
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
        self.video_refs: list[dict] = []
        self._video_cache: dict[str, dict] = {}
        self._specs = self._build_specs()

    @staticmethod
    def _video_url(bvid: str, aid: int) -> str:
        if bvid:
            return f'https://www.bilibili.com/video/{bvid}'
        if aid:
            return f'https://www.bilibili.com/video/av{aid}'
        return ''

    def _remember_video(self, bvid: str = '', aid: int = 0, title: str = '') -> None:
        bvid = str(bvid or '').strip()
        try:
            aid = int(aid or 0)
        except (TypeError, ValueError):
            aid = 0
        if not bvid and not aid:
            return
        for item in self.video_refs:
            if (bvid and item.get('bvid') == bvid) or (not bvid and item.get('aid') == aid):
                if title and not item.get('title'):
                    item['title'] = title
                if bvid and not item.get('bvid'):
                    item['bvid'] = bvid
                    item['url'] = self._video_url(bvid, aid)
                return
        if len(self.video_refs) >= 12:
            return
        self.video_refs.append({
            'bvid': bvid,
            'aid': aid,
            'title': title,
            'url': self._video_url(bvid, aid),
        })

    def _collect_videos(self, method: str, args: dict, result: Any, info: dict | None) -> None:
        payloads = []
        if isinstance(info, dict):
            payloads.append(info)
        payloads.append(args)
        if isinstance(result, dict):
            payloads.append(result)
        elif isinstance(result, list):
            payloads.extend(item for item in result[:5] if isinstance(item, dict))
        for item in payloads:
            bvid = str(item.get('bvid') or '')
            aid = item.get('aid') or item.get('avid') or 0
            title = str(item.get('title') or '')
            if bvid or aid:
                self._remember_video(bvid, int(aid or 0), title)


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

    async def _lookup_video(self, args: dict, bvid: str) -> dict | None:
        aid = int(args.get('aid') or 0)
        try:
            if bvid and hasattr(self.bili, 'get_video_info'):
                return await self.bili.get_video_info(bvid)
            if aid and hasattr(self.bili, 'get_video_info_by_aid'):
                return await self.bili.get_video_info_by_aid(aid)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f'校验视频失败: {exc}')
        return None

    def _prepare_arguments(
        self, method: str, args: dict, bvid: str
    ) -> tuple[dict, str]:
        """Validate model-provided arguments against the real B站 signature."""
        try:
            signature = inspect.signature(getattr(self.bili, method))
        except (TypeError, ValueError):
            return dict(args), ''
        parameters = signature.parameters
        accepts_kwargs = any(
            param.kind == inspect.Parameter.VAR_KEYWORD
            for param in parameters.values()
        )
        allowed = set(parameters)
        clean = {
            key: value for key, value in args.items()
            if key in allowed or accepts_kwargs
        }
        if 'bvid' in allowed and bvid:
            clean['bvid'] = bvid
        for name, param in parameters.items():
            if name not in clean or clean[name] in (None, ''):
                continue
            annotation = param.annotation
            try:
                if annotation is int or name in {
                    'aid', 'count', 'page', 'ps', 'limit', 'root_rpid',
                    'parent_rpid', 'talker_id', 'uid', 'cid', 'since_time',
                }:
                    clean[name] = int(clean[name])
                elif annotation is bool or name in {'include_replies'}:
                    if isinstance(clean[name], str):
                        clean[name] = clean[name].lower() in {'1', 'true', 'yes', 'on'}
                    else:
                        clean[name] = bool(clean[name])
                elif annotation is str:
                    clean[name] = str(clean[name])
            except (TypeError, ValueError):
                return {}, f'参数类型不正确: {name}'
        missing = [
            name for name, param in parameters.items()
            if param.default is inspect.Parameter.empty
            and param.kind not in (
                inspect.Parameter.VAR_POSITIONAL,
                inspect.Parameter.VAR_KEYWORD,
            )
            and name not in clean
        ]
        if missing:
            return {}, (
                f'缺少参数: {", ".join(missing)}；'
                f'可用参数: {", ".join(sorted(allowed))}'
            )
        return clean, ''

    async def call(self, method: str, arguments: dict | None = None) -> Any:
        if method not in {item['name'] for item in self._specs}:
            return {'error': f'没有这个接口: {method}'}
        args = arguments or {}
        if not isinstance(args, dict):
            return {'error': 'arguments 必须是对象'}
        for _ in range(3):
            nested = args.get('arguments')
            if not isinstance(nested, dict):
                break
            args = nested
        args = {
            key: value for key, value in args.items()
            if key not in {'tool', 'method', 'method_name', 'api'}
        }
        blocked = self._check_write(method, args)
        if blocked:
            return {'error': blocked}
        extra_bvid = str(args.get('bvid') or '')
        call_args = {
            key: value for key, value in args.items()
            if key not in {'bvid', 'video_title'}
        }
        cache_key = ''
        if method == 'get_video_info' and extra_bvid:
            cache_key = f'bvid:{extra_bvid}'
        elif method == 'get_video_info_by_aid' and call_args.get('aid'):
            cache_key = f'aid:{call_args.get("aid")}'
        if cache_key and cache_key in self._video_cache:
            return self._video_cache[cache_key]
        video_info = None
        if method in _AID_METHODS and not call_args.get('aid'):
            bvid = extra_bvid or str(call_args.get('bvid') or '')
            if bvid:
                video_info = await self._lookup_video({'bvid': bvid}, bvid)
                if video_info and video_info.get('aid'):
                    call_args['aid'] = int(video_info['aid'])
                    extra_bvid = str(video_info.get('bvid') or bvid)
        if method == 'post_comment' and (
            hasattr(self.bili, 'get_video_info_by_aid')
            or hasattr(self.bili, 'get_video_info')
        ):
            video_info = await self._lookup_video(call_args, extra_bvid)
            if not video_info:
                return {'error': '视频不存在、已删除或无法访问，评论未发送'}
            extra_bvid = str(video_info.get('bvid') or extra_bvid)
        call_args, arg_error = self._prepare_arguments(method, call_args, extra_bvid)
        if arg_error:
            return {'error': arg_error}
        try:
            result = getattr(self.bili, method)(**call_args)
            if inspect.isawaitable(result):
                result = await result
            if method in _WRITE_METHODS:
                self.writes += 1
                if method == 'post_comment' and self.db is not None:
                    await self._record_comment(
                        call_args, extra_bvid, bool(result), video_info
                    )
            self._collect_videos(method, call_args, result, video_info)
            if cache_key and isinstance(result, dict) and result.get('bvid'):
                self._video_cache[cache_key] = result
            return result
        except TypeError as exc:
            return {'error': f'参数不匹配: {exc}'}
        except Exception as exc:  # noqa: BLE001
            logger.warning(f'自由 Agent 调用 {method} 失败: {exc}')
            return {'error': str(exc)}

    async def _record_comment(
        self, args: dict, bvid: str, success: bool, video_info: dict | None
    ) -> None:
        aid = int(args.get('aid') or 0)
        title = str((video_info or {}).get('title') or '')
        author = str((video_info or {}).get('owner') or '')
        if not bvid and aid and hasattr(self.bili, 'get_video_info_by_aid'):
            try:
                info = await self.bili.get_video_info_by_aid(aid) or {}
                bvid = str(info.get('bvid') or '')
                title = title or str(info.get('title') or '')
                author = author or str(info.get('owner') or '')
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
