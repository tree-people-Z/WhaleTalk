"""Free-form agent: all B站 interfaces, persona/diary/memory, no fixed workflow."""

import asyncio
import json
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
        self.enable_frame_analysis = True
        self.local_transcriber = None
        from core.comment_manager import CommentManager
        self.comment_manager = CommentManager(bili_api, ai_client, db, config)

    def request_stop(self):
        if self._stop is not None:
            self._stop.set()

    def _system_prompt(self) -> str:
        tools = [self.bili_tool.spec(), INSPECT_VIDEO_TOOL, *DIARY_TOOLS]
        owner = self.config.get('bilibili.owner_name', '') or '未配置'
        return (
            f'{build_agent_context(self.config)}\n\n'
            f'# 账号\n主人昵称：{owner}\n\n'
            f'# 可用工具\n{json.dumps(tools, ensure_ascii=False)}\n\n'
            '# 输出\n'
            '每步只输出一个 JSON：\n'
            '{"action":"tool","tool":"工具名","arguments":{...}}\n'
            '或 {"action":"finish","reason":"这一轮做了什么/为什么不做"}\n'
            '工具结果会返回给你。最多 12 步。\n'
            'finish 的 reason 只能描述本轮实际调用过的工具；没有调用工具就写“本轮没有操作”，'
            '不要复述日记或之前的轮次。'
        )

    async def _call_tool(self, name: str, args: dict) -> Any:
        if name == 'bili_api':
            method = str(args.get('method') or '')
            params = args.get('arguments') or args.get('params') or {}
            return await self.bili_tool.call(method, params)
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
            logger.info(f'发送{kind}: {str(params.get("text") or "")[:80]}')
        elif method == 'send_private_message' and result is True:
            logger.info(
                f'发送私信 -> {params.get("talker_id")}: '
                f'{str(params.get("text") or "")[:80]}'
            )

    @staticmethod
    def _action_ok(result: Any) -> bool:
        if result is False:
            return False
        if isinstance(result, dict) and result.get('error'):
            return False
        return True

    @staticmethod
    def _describe_action(tool: str, args: dict, result: Any) -> str:
        if tool == 'bili_api':
            method = str(args.get('method') or '') or '(缺少 method)'
            params = args.get('arguments') or args.get('params') or {}
            target = ''
            for key in ('keyword', 'bvid', 'aid', 'talker_id', 'uid'):
                if params.get(key) not in (None, ''):
                    target = f' {params[key]}'
                    break
            detail = f'{method}{target}'
            if method in {'post_comment', 'send_private_message', 'send_danmaku'}:
                text = str(params.get('text') or '')[:24]
                if text:
                    detail += f'：{text}'
            return f'{detail} {"成功" if FreeAgent._action_ok(result) else "失败"}'
        if tool == 'write_diary':
            content = str(args.get('content') or '')
            return f'写日记（{len(content)} 字）{"成功" if FreeAgent._action_ok(result) else "失败"}'
        if tool == 'read_diary':
            day = str(args.get('day') or '')
            return f'读日记（{day or "列出日期"}）'
        return f'{tool} {"成功" if FreeAgent._action_ok(result) else "失败"}'

    @staticmethod
    def _log_actions(actions: list[str]) -> None:
        if actions:
            logger.info('🐋 本轮动作：' + '；'.join(actions))
        else:
            logger.info('🐋 本轮动作：没有调用工具')


    async def run_analysis_cycle(self) -> Dict[str, Any]:
        self._stop = asyncio.Event()
        messages = [
            {'role': 'system', 'content': self._system_prompt()},
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
        retried_empty_finish = False
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
                actions.append(self._describe_action(tool, args, result))
                self._log_io(tool, args, result)
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
            logger.info(f'🐋 模型总结：{summary}')
        if not actions:
            logger.warning('🐋 本轮没有实际调用工具，模型总结不代表已执行操作')
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
