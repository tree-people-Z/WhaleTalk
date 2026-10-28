"""Free-form agent: all B站 interfaces, persona/diary/memory, no fixed workflow."""

import asyncio
import hashlib
import json
import random
import re
import tempfile
from datetime import datetime
from pathlib import Path
from typing import Any, Dict

from loguru import logger

from core.agent_protocol import parse_json_decision
from core.bili_tool import BiliTool
from core.free_context import (
    DIARY_TOOLS,
    append_diary,
    build_agent_context,
    read_diary,
)
from core.system_prompts import load_prompt

MAX_STEPS = 12

INSPECT_VIDEO_TOOL = {
    'name': 'inspect_video',
    'description': (
        '读取一个视频的标题、简介、字幕、热门评论，并可抽取关键帧做画面描述。'
        '只读，不点赞、不评论。'
    ),
    'parameters': {
        'bvid': 'string',
        'frames': 'int(可选，0-5，默认3)',
        'comments': 'int(可选，0-20，默认10)',
    },
}


class FreeAgent:
    """One autonomous session. The model chooses every action."""

    def __init__(self, bili_api, ai_client, db, config):
        self.bili = bili_api
        self.ai = ai_client
        self.db = db
        self.config = config
        self.bili_tool = BiliTool(bili_api, db, config)
        self._stop = None
        self._seen_io = set()
        self.self_uid = None
        self.self_name = ''
        self.enable_frame_analysis = True
        self.local_transcriber = None
        from core.comment_manager import CommentManager
        self.comment_manager = CommentManager(bili_api, ai_client, db, config)

    def request_stop(self):
        if self._stop is not None:
            self._stop.set()

    def _filter_agent_events(self, method: str, params: dict, result: Any) -> Any:
        """Drop already-delivered events so each @/comment/DM is handled once."""
        if self.db is None or not isinstance(result, list):
            return result
        if method not in {
            'get_at_messages', 'get_comments', 'get_comment_thread',
            'get_private_messages',
        }:
            return result
        if method == 'get_comments' and not (
            params.get('root_rpids') or params.get('include_replies')
        ):
            return result
        own = set()
        if method in {'get_comments', 'get_comment_thread'}:
            try:
                own_ids = self.db.get_own_comment_rpids()
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
        states = self.db.get_agent_event_states([item['key'] for item in records])
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
                if last and count < 3 and (now - last).total_seconds() < 600:
                    continue
                if count >= 3:
                    continue
            new_items.append(record.pop('_item'))
            new_records.append(record)
        try:
            self.db.deliver_agent_events(new_records)
        except Exception as exc:  # noqa: BLE001
            logger.debug(f'记录事件状态失败: {exc}')
        return new_items

    def _keyword_hint(self) -> str:
        if self.db is None or not hasattr(self.db, 'get_recent_search_keywords'):
            return ''
        try:
            recent = self.db.get_recent_search_keywords(8)
        except Exception:  # noqa: BLE001
            return ''
        if not isinstance(recent, (list, tuple)):
            return ''
        recent = [str(item).strip() for item in recent if str(item).strip()]
        if not recent:
            return ''
        keywords = self.config.get('search.keywords', []) if self.config else []
        if isinstance(keywords, str):
            keywords = [line.strip() for line in keywords.splitlines() if line.strip()]
        if not isinstance(keywords, (list, tuple)):
            keywords = []
        keywords = [str(item).strip() for item in keywords if str(item).strip()]
        recent_short = str(recent[0])
        return f'# 关键词轮换\n上一次使用：{recent_short}。'

    def _system_prompt(self, self_info: dict | None = None) -> str:
        tools = [self.bili_tool.spec(), INSPECT_VIDEO_TOOL, *DIARY_TOOLS]
        owner = self.config.get('bilibili.owner_name', '') or '未配置'
        self_info = self_info or {}
        self_uid = self_info.get('uid') or self.self_uid or '未获取'
        self_name = self_info.get('name') or self.self_name or '未获取'
        keyword_hint = self._keyword_hint()
        hint_block = f'{keyword_hint}\n\n' if keyword_hint else ''
        return (
            f'{build_agent_context(self.config)}\n\n'
            f'{hint_block}'
            f'# 你的B站账号\n'
            f'账号名：{self_name}，UID：{self_uid}。\n'
            '视频信息里 owner_mid 等于这个 UID，或者评论里 mid 等于这个 UID，'
            '就是你自己的视频/评论。在自己的视频下面互动时，不要把它说成别人的视频。\n\n'
            f'# 账号\n主人昵称：{owner}\n\n'
            f'# 可用工具\n{json.dumps(tools, ensure_ascii=False)}\n\n'
            f'# 输出\n{load_prompt("free_agent_output")}'
        )

    @staticmethod
    def _unwrap_arguments(params: Any) -> dict:
        """Strip accidental extra arguments/params wrappers from model output."""
        for _ in range(3):
            if not isinstance(params, dict):
                return {}
            nested = params.get('arguments')
            if not isinstance(nested, dict):
                nested = params.get('params')
            if not isinstance(nested, dict):
                break
            params = nested
        return params if isinstance(params, dict) else {}

    async def _call_tool(self, name: str, args: dict) -> Any:
        if name == 'bili_api':
            method = str(args.get('method') or '')
            params = self._unwrap_arguments(
                args.get('arguments') or args.get('params') or {}
            )
            if (
                method == 'post_comment'
                and not params.get('root_rpid')
                and not params.get('parent_rpid')
                and 'share_to_owner' not in params
            ):
                try:
                    probability = float(
                        self.config.get('interaction.owner_mention_probability', 35)
                    ) / 100.0
                except (TypeError, ValueError):
                    probability = 0.35
                if random.random() < max(0.0, min(1.0, probability)):
                    params['share_to_owner'] = True
            result = await self.bili_tool.call(method, params)
            return self._filter_agent_events(method, params, result)
        if name == 'inspect_video':
            return await self.inspect_video(
                str(args.get('bvid') or ''),
                frames=int(args.get('frames') if args.get('frames') is not None else 3),
                comments=int(args.get('comments') if args.get('comments') is not None else 10),
            )
        if name == 'read_diary':
            return read_diary(str(args.get('day') or ''))
        if name == 'write_diary':
            path = append_diary(str(args.get('content') or ''))
            return {'ok': True, 'path': str(path)}
        return {'error': f'未知工具: {name}'}

    async def _transcribe_audio(
        self, bvid: str, media_urls: dict
    ) -> tuple[str, str]:
        """Transcribe the audio stream when B站 has no subtitle."""
        mode = str(self.config.get('analysis.transcription_mode', 'off')) if self.config else 'off'
        if mode not in ('local', 'cloud'):
            return '', ''
        audio_url = (media_urls or {}).get('audio')
        if not audio_url and hasattr(self.bili, 'get_media_urls'):
            try:
                media_urls = await self.bili.get_media_urls(bvid) or {}
                audio_url = media_urls.get('audio')
            except Exception as exc:  # noqa: BLE001
                logger.debug(f'获取音频流失败 {bvid}: {exc}')
        if not audio_url:
            return '', ''
        try:
            from core.frame_analyzer import FrameAnalyzer
            analyzer = FrameAnalyzer()
            if not analyzer.ffmpeg_available:
                return '', ''
            with tempfile.TemporaryDirectory(prefix='bili-audio-') as audio_dir:
                if mode == 'cloud':
                    from core.cloud_transcriber import CloudAudioTranscriber
                    transcriber = CloudAudioTranscriber(
                        base_url=self.config.get(
                            'analysis.cloud_transcription.base_url',
                            'https://api.openai.com/v1',
                        ),
                        api_key=self.config.get('analysis.cloud_transcription.api_key', ''),
                        model=self.config.get(
                            'analysis.cloud_transcription.model', 'whisper-1'
                        ),
                    )
                    text = await transcriber.transcribe_url(
                        audio_url,
                        str(Path(audio_dir) / 'audio.mp3'),
                        ffmpeg_path=analyzer.ffmpeg_path,
                    )
                    source = '云端语音转写'
                else:
                    from core.audio_transcriber import LocalAudioTranscriber
                    transcriber = LocalAudioTranscriber(
                        model_name=self.config.get(
                            'analysis.local_transcription_model', 'medium'
                        )
                    )
                    text = await transcriber.transcribe_url(
                        audio_url,
                        str(Path(audio_dir) / 'audio.wav'),
                        ffmpeg_path=analyzer.ffmpeg_path,
                    )
                    source = '本地语音转写'
                if text:
                    logger.info(f'{source}成功 {bvid}, 长度: {len(text)}')
                    return str(text), source
        except Exception as exc:  # noqa: BLE001
            logger.warning(f'音频转写失败 {bvid}: {exc}')
        return '', ''

    async def inspect_video(self, bvid: str, frames: int = 3, comments: int = 10) -> dict:
        """Read title/subtitle/comments and optionally describe sampled frames."""
        bvid = (bvid or '').strip()
        if not bvid:
            return {'error': 'bvid 不能为空'}
        if not hasattr(self.bili, 'get_video_info'):
            return {'error': '当前没有视频读取接口'}
        try:
            info = await self.bili.get_video_info(bvid)
        except Exception as exc:  # noqa: BLE001
            return {'error': f'读取视频失败: {exc}'}
        if not info:
            return {'error': f'视频不存在或无法读取: {bvid}'}

        try:
            self.bili_tool._remember_video(
                bvid, int(info.get('aid') or 0), str(info.get('title') or '')
            )
        except Exception:  # noqa: BLE001
            pass

        aid = int(info.get('aid') or 0)
        subtitle = ''
        subtitle_source = ''
        if hasattr(self.bili, 'get_subtitle'):
            try:
                subtitle = str(await self.bili.get_subtitle(bvid) or '')
                if subtitle:
                    subtitle_source = 'B站字幕'
            except Exception as exc:  # noqa: BLE001
                logger.debug(f'读取字幕失败 {bvid}: {exc}')
        if not subtitle:
            subtitle, subtitle_source = await self._transcribe_audio(bvid, {})

        comment_items = []
        count = max(0, min(int(comments or 0), 20))
        if count and aid and hasattr(self.bili, 'get_comments'):
            try:
                raw = await self.bili.get_comments(aid, count=count)
                for item in (raw or [])[:count]:
                    comment_items.append({
                        'user': str(item.get('user') or item.get('nickname') or ''),
                        'content': str(item.get('content') or '')[:200],
                        'like': item.get('like') or 0,
                    })
            except Exception as exc:  # noqa: BLE001
                logger.debug(f'读取评论失败 {bvid}: {exc}')

        frame_items = []
        frame_note = ''
        frame_count = max(0, min(int(frames or 0), 5))
        if frame_count:
            try:
                from core.frame_analyzer import FrameAnalyzer
                analyzer = FrameAnalyzer()
                if not analyzer.ffmpeg_available:
                    frame_note = 'ffmpeg 不可用，未抽帧'
                elif hasattr(self.bili, 'get_media_urls'):
                    urls = await self.bili.get_media_urls(bvid) or {}
                    video_url = urls.get('video')
                    if not video_url:
                        frame_note = '没有可用的视频流地址，未抽帧'
                    else:
                        output_dir = Path('data') / 'frames' / bvid
                        paths = await analyzer.extract_frames(
                            video_url, str(output_dir), count=frame_count,
                            duration=info.get('duration'),
                        )
                        for path in paths:
                            description = ''
                            try:
                                if hasattr(self.ai, 'describe_image'):
                                    description = str(
                                        await analyzer.analyze_frame(path, self.ai) or ''
                                    )
                            except Exception as exc:  # noqa: BLE001
                                logger.debug(f'画面描述失败 {path}: {exc}')
                            frame_items.append({
                                'path': path,
                                'description': description[:500],
                            })
                        if not paths:
                            frame_note = '抽帧没有成功'
            except Exception as exc:  # noqa: BLE001
                frame_note = f'抽帧失败: {exc}'
                logger.warning(f'inspect_video 抽帧失败 {bvid}: {exc}')

        return {
            'bvid': bvid,
            'aid': aid,
            'title': str(info.get('title') or ''),
            'owner': str(info.get('owner') or ''),
            'owner_mid': info.get('owner_mid'),
            'is_own': bool(
                getattr(self, 'self_uid', None)
                and str(info.get('owner_mid') or '') == str(self.self_uid)
            ),
            'duration': info.get('duration'),
            'description': str(info.get('desc') or '')[:1000],
            'subtitle': subtitle[:4000],
            'subtitle_source': subtitle_source,
            'comments': comment_items,
            'frames': frame_items,
            'frame_note': frame_note,
        }

    @staticmethod
    def _infer_method(args: dict) -> str:
        """Infer a method when the model sends only its arguments."""
        keys = set(args)
        if 'keyword' in keys or 'search_type' in keys:
            return 'search_videos'
        if 'talker_id' in keys:
            return 'send_private_message' if 'text' in keys else 'get_private_messages'
        if 'bvid' in keys and 'text' not in keys:
            return 'get_video_info'
        if 'aid' in keys:
            if 'text' in keys:
                return 'post_comment'
            if 'root_rpid' in keys or 'parent_rpid' in keys:
                return 'get_comment_thread' if 'text' not in keys else 'post_comment'
            return 'get_comments'
        if 'uid' in keys:
            return 'get_user_info'
        return ''

    def _normalize_call(self, tool: str, args: Any) -> tuple[str, dict]:
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except ValueError:
                args = {}
        if not isinstance(args, dict):
            args = {}
        names = self.bili_tool.method_names
        if tool != 'bili_api' and tool in names:
            return 'bili_api', {'method': tool, 'arguments': args}
        if tool != 'bili_api':
            return tool, args

        method = str(
            args.get('method') or args.get('name') or args.get('api')
            or args.get('method_name') or args.get('tool') or ''
        )
        params = (
            args.get('arguments') or args.get('params')
            or args.get('parameters') or args.get('args')
        )
        if params is None:
            params = {
                key: value for key, value in args.items()
                if key not in {'method', 'method_name', 'name', 'api', 'tool'}
            }
        if isinstance(params, str):
            try:
                params = json.loads(params)
            except ValueError:
                params = {}
        if not isinstance(params, dict):
            params = {}
        params = self._unwrap_arguments(params)

        # Handle malformed shapes such as {"search_videos": {...}} or
        # {"arguments": {"method": "search_videos", ...}}.
        if method not in names:
            for key in ('arguments', 'params', 'parameters', 'payload', 'data'):
                nested = args.get(key)
                if isinstance(nested, str):
                    try:
                        nested = json.loads(nested)
                    except ValueError:
                        nested = None
                if isinstance(nested, dict):
                    nested_method = str(nested.get('method') or nested.get('name') or '')
                    if nested_method in names:
                        method = nested_method
                        nested_params = (
                            nested.get('arguments') or nested.get('params') or {}
                        )
                        if isinstance(nested_params, dict):
                            params = nested_params
                        break
            else:
                method_keys = [key for key in args if key in names]
                if len(method_keys) == 1:
                    method = method_keys[0]
                    value = args.get(method)
                    params = value if isinstance(value, dict) else {}
                if not method:
                    method = self._infer_method(args or params)
        return 'bili_api', {'method': method, 'arguments': params}

    def _log_io(self, tool: str, args: dict, result: Any) -> None:
        if tool != 'bili_api':
            return
        method = str(args.get('method') or '')
        params = args.get('arguments') or {}
        if method == 'get_private_messages' and isinstance(result, list) and result:
            for item in result[-3:]:
                key = (
                    'dm', params.get('talker_id'), item.get('timestamp'),
                    item.get('content'),
                )
                if key in self._seen_io:
                    continue
                self._seen_io.add(key)
                content = str(item.get('content') or '')[:80]
                logger.info(f'收到私信 {params.get("talker_id")}: {content}')
        elif method == 'get_at_messages' and isinstance(result, list) and result:
            for item in result[-3:]:
                key = ('at', item.get('rpid'))
                if key in self._seen_io:
                    continue
                self._seen_io.add(key)
                user = item.get('user') or item.get('nickname') or '网友'
                content = str(item.get('content') or '')[:80]
                logger.info(f'收到@{user}: {content}')
        elif method in {'get_comments', 'get_comment_thread'} and isinstance(result, list) and result:
            own = set()
            if self.db is not None and hasattr(self.db, 'get_own_comment_rpids'):
                try:
                    own_ids = self.db.get_own_comment_rpids()
                    if isinstance(own_ids, (set, list, tuple)):
                        own = set(own_ids)
                except Exception:  # noqa: BLE001
                    own = set()
            for item in result[-3:]:
                rpid = item.get('rpid')
                if rpid in own:
                    continue
                key = ('comment', rpid)
                if key in self._seen_io:
                    continue
                self._seen_io.add(key)
                user = item.get('user') or item.get('nickname') or '网友'
                content = str(item.get('content') or '')[:80]
                logger.info(f'收到评论 [{user}]: {content}')
        elif method == 'post_comment' and result is True:
            kind = '回复' if params.get('root_rpid') or params.get('parent_rpid') else '评论'
            title = self._video_title(
                str(params.get('bvid') or ''), int(params.get('aid') or 0)
            )
            target = (
                f'《{self._clip(title, 32)}》' if title
                else f' aid={params.get("aid")}'
            )
            logger.info(
                f'发送{kind}{target}：{self._clip(params.get("text"), 120)}'
            )
        elif method == 'send_private_message' and result is True:
            logger.info(
                f'发送私信 -> {params.get("talker_id")}: '
                f'{str(params.get("text") or "")[:120]}'
            )

    @staticmethod
    def _action_ok(result: Any) -> bool:
        if result is False:
            return False
        if isinstance(result, dict) and result.get('error'):
            return False
        return True

    def _video_title(self, bvid: str = '', aid: int = 0) -> str:
        try:
            for item in getattr(self.bili_tool, 'video_refs', []) or []:
                if bvid and item.get('bvid') == bvid:
                    return str(item.get('title') or '')
                if aid and int(item.get('aid') or 0) == int(aid):
                    return str(item.get('title') or '')
        except Exception:  # noqa: BLE001
            pass
        return ''

    @staticmethod
    def _clip(text: str, limit: int) -> str:
        text = str(text or '')
        return text if len(text) <= limit else text[:limit - 1] + '…'

    def _describe_action(self, tool: str, args: dict, result: Any) -> str:
        ok = self._action_ok(result)
        if tool == 'inspect_video':
            bvid = str(args.get('bvid') or '')
            if not isinstance(result, dict) or result.get('error'):
                return f'读取视频素材 {bvid}：失败'
            title = self._clip(str(result.get('title') or self._video_title(bvid)), 32)
            subtitle_len = len(str(result.get('subtitle') or ''))
            comments = len(result.get('comments') or [])
            frames = len(result.get('frames') or [])
            return (
                f'读取视频素材 {bvid}《{title or "未知标题"}》：'
                f'字幕 {subtitle_len} 字，评论 {comments} 条，抽帧 {frames} 张'
            )
        if tool == 'write_diary':
            content = str(args.get('content') or '')
            return f'写日记（{len(content)} 字）：{"成功" if ok else "失败"}'
        if tool == 'read_diary':
            day = str(args.get('day') or '')
            return f'读日记（{day or "列出日期"}）'
        if tool != 'bili_api':
            return f'{tool}：{"成功" if ok else "失败"}'

        method = str(args.get('method') or '')
        params = args.get('arguments') or args.get('params') or {}
        if not isinstance(params, dict):
            params = {}
        if method == 'is_blocked':
            if isinstance(result, dict) and result.get('error'):
                return '检查风控状态：调用失败'
            return f'检查风控状态：{"风控中" if result is True else "正常"}'
        if method == 'is_posting_blocked':
            if isinstance(result, dict) and result.get('error'):
                return '检查评论冷却：调用失败'
            return f'检查评论冷却：{"冷却中" if result is True else "正常"}'

        labels = {
            'search_videos': '搜索视频',
            'get_video_info': '获取视频信息',
            'get_video_info_by_aid': '获取视频信息',
            'get_subtitle': '读取字幕',
            'get_media_urls': '获取视频流',
            'get_at_messages': '检查@消息',
            'get_private_sessions': '读取私信会话',
            'get_private_messages': '读取私信',
            'get_comments': '读取评论',
            'get_comment_thread': '读取评论楼',
            'get_own_videos': '读取自己的投稿',
            'get_user_videos': '读取UP主投稿',
            'get_self_info': '读取账号信息',
            'get_user_info': '读取用户信息',
            'post_comment': '发送评论',
            'like_comment': '点赞评论',
            'like_video': '点赞视频',
            'favorite_video': '收藏视频',
            'coin_video': '投币视频',
            'share_video': '分享视频',
            'follow_video_author': '关注UP主',
            'add_to_watch_later': '稍后再看',
            'send_private_message': '发送私信',
            'send_danmaku': '发送弹幕',
            'like_danmaku': '点赞弹幕',
        }
        label = labels.get(method, f'调用 {method}' if method else '缺少方法名')
        target = ''
        for key in ('keyword', 'bvid', 'aid', 'talker_id', 'uid', 'rpid'):
            value = params.get(key)
            if value not in (None, ''):
                target = f' {value}'
                break
        if method in {'get_video_info', 'get_video_info_by_aid'} and isinstance(result, dict):
            title = str(result.get('title') or '')
            bvid = str(result.get('bvid') or params.get('bvid') or '')
            if bvid:
                target = f' {bvid}'
            if title:
                target += f'《{self._clip(title, 32)}》'
        elif method in {'post_comment', 'get_comments', 'get_comment_thread'}:
            aid = params.get('aid') or (result.get('aid') if isinstance(result, dict) else 0)
            title = self._video_title(str(params.get('bvid') or ''), int(aid or 0))
            if title:
                target += f'《{self._clip(title, 32)}》'
        detail = f'{label}{target}'
        if method in {'post_comment', 'send_private_message', 'send_danmaku'}:
            text = self._clip(str(params.get('text') or ''), 40)
            if text:
                detail += f'：{text}'
        if isinstance(result, list):
            detail += f'（{len(result)} 条）'
        if isinstance(result, dict) and result.get('error'):
            return f'{detail}：失败（{str(result.get("error"))[:100]}）'
        return f'{detail}：{"成功" if ok else "失败"}'

    @staticmethod
    def _summary_mismatch(summary: str, actions: list[str]) -> list[str]:
        actual = '；'.join(actions)
        claims = [
            ('点赞', ('点赞', '点了赞', '给了.*赞', '赞了'), ('点赞',)),
            ('收藏', ('收藏',), ('收藏',)),
            ('评论/留言', ('留言', '评论了', '留了评论', '发了评论', '回复了', '回了'),
             ('发送评论',)),
            ('私信', ('发送私信', '发了私信', '回了私信', '回复.{0,6}私信', '私信.{0,6}(回|发)'),
             ('发送私信',)),
            ('关注', ('关注',), ('关注',)),
            ('弹幕', ('弹幕',), ('发送弹幕',)),
        ]
        missing = []
        for claim, patterns, markers in claims:
            if not any(re.search(pattern, summary) for pattern in patterns):
                continue
            if not any(marker in actual for marker in markers):
                missing.append(claim)
        return missing

    @staticmethod
    def _log_actions(actions: list[str]) -> None:
        if actions:
            logger.info('🐋 本轮动作：' + '；'.join(actions))
        else:
            logger.info('🐋 本轮动作：没有调用工具')


    async def run_analysis_cycle(self) -> Dict[str, Any]:
        self._stop = asyncio.Event()
        self_info = {}
        try:
            if hasattr(self.bili, 'get_self_info'):
                self_info = await self.bili.get_self_info() or {}
                self.self_uid = self_info.get('uid') or self.self_uid
                self.self_name = self_info.get('name') or self.self_name
        except Exception as exc:  # noqa: BLE001
            logger.debug(f'读取当前B站账号失败: {exc}')
        messages = [
            {'role': 'system', 'content': self._system_prompt(self_info)},
            {
                'role': 'user',
                'content': (
                    f'现在：{datetime.now().strftime("%Y-%m-%d %H:%M")}。'
                    '自己决定这一轮做什么；可以什么都不做。'
                ),
            },
        ]
        comments = 0
        summary = ''
        actions: list[str] = []
        successful_actions: list[str] = []
        retried_empty_finish = False
        retried_false_summary = False
        try:
            for _ in range(MAX_STEPS):
                if self._stop.is_set():
                    raise asyncio.CancelledError()
                response = await self.ai.chat(messages, temperature=0.7, max_tokens=1000)
                if not response:
                    break
                decision = parse_json_decision(response)
                if decision is None:
                    messages.append({'role': 'assistant', 'content': response})
                    messages.append({'role': 'user', 'content': '只输出一个 JSON。'})
                    continue
                action = str(decision.get('action') or '').lower()
                if action == 'finish':
                    if not actions and not retried_empty_finish:
                        retried_empty_finish = True
                        messages.append({'role': 'assistant', 'content': response})
                        messages.append({
                            'role': 'user',
                            'content': (
                                '你还没有调用任何工具，不能用 finish 描述已经做过的事。'
                                '如果这轮要操作，先调用工具；如果确实不操作，'
                                '输出 {"action":"finish","reason":"本轮没有操作"}。'
                            ),
                        })
                        continue
                    summary = str(decision.get('reason') or '')
                    missing = self._summary_mismatch(summary, successful_actions)
                    if missing and not retried_false_summary:
                        retried_false_summary = True
                        messages.append({'role': 'assistant', 'content': response})
                        messages.append({
                            'role': 'user',
                            'content': (
                                '你的总结提到 '
                                + '、'.join(missing)
                                + '，但本轮没有成功的对应动作。不要编造已经做过的事。'
                                '如果这些事情还没做，现在调用工具完成；'
                                '如果不想做，重新输出 finish，只写实际完成的事。'
                            ),
                        })
                        continue
                    break
                tool = str(decision.get('tool') or decision.get('name') or 'bili_api')
                args = (
                    decision.get('arguments')
                    or decision.get('params')
                    or decision.get('args')
                    or decision.get('input')
                    or {}
                )
                if isinstance(args, list):
                    args = next(
                        (item for item in args if isinstance(item, dict)), {}
                    )
                if not isinstance(args, dict):
                    args = {}
                else:
                    args = dict(args)
                # Some models put method at the decision level instead of
                # inside arguments.
                for key in ('method', 'method_name', 'api'):
                    if decision.get(key) and not args.get('method'):
                        args['method'] = decision[key]
                tool, args = self._normalize_call(tool, args)
                if tool == 'bili_api' and not args.get('method'):
                    logger.warning(f'🐋 未识别的工具调用: {response[:800]}')
                try:
                    result = await self._call_tool(tool, args)
                except Exception as exc:  # noqa: BLE001
                    result = {'error': str(exc)}
                action_text = self._describe_action(tool, args, result)
                actions.append(action_text)
                if self._action_ok(result):
                    successful_actions.append(action_text)
                if (tool == 'bili_api' and self.db is not None
                        and str(args.get('method') or '') == 'search_videos'
                        and isinstance(result, list)):
                    keyword = str((args.get('arguments') or {}).get('keyword') or '')
                    if keyword:
                        try:
                            self.db.record_search_keyword(keyword)
                        except Exception as exc:  # noqa: BLE001
                            logger.debug(f'记录搜索关键词失败: {exc}')
                self._log_io(tool, args, result)
                if tool == 'bili_api' and self.db is not None:
                    method = str(args.get('method') or '')
                    params = args.get('arguments') or {}
                    if method == 'post_comment' and result is True and (
                        params.get('root_rpid') or params.get('parent_rpid')
                    ):
                        try:
                            self.db.mark_agent_events_handled(['at', 'comment'])
                        except Exception as exc:  # noqa: BLE001
                            logger.debug(f'标记评论事件已处理失败: {exc}')
                    elif method == 'send_private_message' and result is True:
                        try:
                            self.db.mark_agent_events_handled(['dm'])
                        except Exception as exc:  # noqa: BLE001
                            logger.debug(f'标记私信事件已处理失败: {exc}')
                if (tool == 'bili_api'
                        and str(args.get('method')) == 'post_comment'
                        and result is True):
                    comments += 1
                messages.append({'role': 'assistant', 'content': response})
                messages.append({
                    'role': 'user',
                    'content': '工具结果：' + BiliTool.dump(result, 3500)
                    + '\n继续，或 finish。',
                })
        finally:
            self._stop = None
            self._log_actions(actions)
        if summary:
            missing = self._summary_mismatch(summary, successful_actions)
            if missing:
                logger.warning(
                    '🐋 模型总结与实际动作不符：提到 '
                    + '、'.join(missing)
                    + '，但本轮没有成功的对应动作'
                )
                logger.info(f'🐋 模型自述（未采信）：{summary}')
                summary = (
                    '本轮实际完成：' + '；'.join(successful_actions)
                    if successful_actions else '本轮没有成功动作'
                )
                logger.info(f'🐋 实际总结：{summary}')
            else:
                logger.info(f'🐋 模型总结：{summary}')
        if not actions:
            logger.warning('🐋 本轮没有实际调用工具，模型总结不代表已执行操作')
        if not summary:
            summary = (
                '本轮实际完成：' + '；'.join(successful_actions)
                if successful_actions else '本轮没有成功动作'
            )
            logger.info(f'🐋 实际总结：{summary}（模型未给出总结）')
        if self.db is not None:
            try:
                self.db.add_agent_session(
                    summary, actions, comments, self.bili_tool.video_refs
                )
            except Exception as exc:  # noqa: BLE001
                logger.debug(f'记录 Agent 运行历史失败: {exc}')
        return {
            'status': 'success',
            'videos_found': 0,
            'videos_analyzed': 0,
            'worthy_count': 0,
            'comments_sent': comments,
            'summary': summary,
            'actions': actions,
        }

    async def check_replies(self) -> Dict[str, Any]:
        if not self.config.get('interaction.comment_monitor', False):
            return {'status': 'replies_checked', 'replied': 0, 'mentions': []}
        if self.bili.is_blocked():
            logger.warning('B站风控冷却中，跳过回复检查')
            return {'status': 'replies_checked', 'replied': 0, 'mentions': []}
        if getattr(self.bili, 'is_posting_blocked', lambda: False)() is True:
            logger.warning('B站评论发送限额冷却中，跳过回复检查')
            return {'status': 'replies_checked', 'replied': 0, 'mentions': []}
        result = await self.comment_manager.check_and_reply()
        return {
            'status': 'replies_checked',
            'replied': result.get('replied', 0),
            'mentions': result.get('mentions', []),
        }
