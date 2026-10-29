"""Free-form conversation agent: persona, diaries, memory and every B站 tool."""

import json
from typing import Any, Awaitable, Callable, Dict, Optional

from loguru import logger

from core.bili_tool import BiliTool
from core.free_context import DIARY_TOOLS, append_diary, build_agent_context, read_diary
from core.system_prompts import load_prompt

MAX_STEPS = 8
THREAD_COOLDOWN_MINUTES = 10
MAX_REPLIES_PER_THREAD_DAY = 6


def _parse(text: str) -> Optional[Dict[str, Any]]:
    from core.agent_protocol import parse_json_decision
    return parse_json_decision(text)


class ConversationAgent:
    def __init__(
        self,
        bili_api,
        db,
        ai_client,
        config,
        send_reply: Callable[..., Awaitable[bool]],
        send_dm: Optional[Callable[..., Awaitable[bool]]] = None,
        send_video_comment: Optional[Callable[..., Awaitable[bool]]] = None,
    ):
        self.bili = bili_api
        self.db = db
        self.ai = ai_client
        self.config = config
        self.self_uid = None
        self.self_name = ''
        self.send_reply = send_reply
        self.send_dm = send_dm
        self.send_video_comment = send_video_comment
        self.bili_tool = BiliTool(bili_api, db, config) if bili_api is not None else None

    def _read_tools(self, scope: str) -> list:
        tools = list(DIARY_TOOLS)
        if self.bili_tool is not None:
            tools.insert(0, self.bili_tool.spec())
        tools.append({
            'name': 'inspect_video',
            'description': '读取视频标题、字幕、评论和关键帧，用来理解视频内容。只读。',
            'parameters': {
                'bvid': 'string',
                'frames': 'int(可选，0-5，默认2)',
                'comments': 'int(可选，0-10，默认5)',
            },
        })
        if scope == 'dm':
            tools.append({
                'name': 'reply_dm',
                'description': '回复当前私信。',
                'parameters': {'text': 'string'},
            })
        else:
            tools.append({
                'name': 'reply_comment',
                'description': '回复当前评论。',
                'parameters': {'text': 'string'},
            })
        return tools

    def _system_prompt(self, event: Dict[str, Any]) -> str:
        owner = event.get('owner_name') or self.config.get('bilibili.owner_name', '') or '未配置'
        tools = self._read_tools(event.get('scope') or '')
        return (
            f'{build_agent_context(self.config)}\n\n'
            f'# 账号\n主人昵称：{owner}\n\n'
            f'# 可用工具\n{json.dumps(tools, ensure_ascii=False)}\n\n'
            f'# 输出\n{load_prompt("conversation_output")}'
        )

    @staticmethod
    def _maybe_mention_owner(
        event: Dict[str, Any], text: str, args: Dict[str, Any]
    ) -> str:
        # 程序不再自动加 @；模型正文里自己写什么就发什么。
        return text

    async def _transcribe_audio(self, bvid: str, media_urls: dict):
        from core.free_agent import FreeAgent
        return await FreeAgent._transcribe_audio(self, bvid, media_urls)

    async def _execute(self, name: str, args: Dict[str, Any], event: Dict[str, Any]) -> Any:
        if name == 'bili_api':
            if self.bili_tool is None:
                return {'error': 'B站接口不可用'}
            return await self.bili_tool.call(
                str(args.get('method') or ''),
                args.get('arguments') or args.get('params') or {},
            )
        if name == 'read_diary':
            return read_diary(str(args.get('day') or ''))
        if name == 'inspect_video':
            from core.free_agent import FreeAgent
            try:
                frames = int(args.get('frames') if args.get('frames') is not None else 2)
                comments = int(args.get('comments') if args.get('comments') is not None else 5)
            except (TypeError, ValueError):
                frames, comments = 2, 5
            return await FreeAgent.inspect_video(
                self, str(args.get('bvid') or ''), frames, comments
            )
        if name == 'write_diary':
            try:
                path = append_diary(str(args.get('content') or ''))
                return {'ok': True, 'path': str(path)}
            except Exception as exc:  # noqa: BLE001
                return {'error': str(exc)}
        if name == 'reply_dm':
            text = str(args.get('text') or '').strip()
            if not text or self.send_dm is None:
                return {'error': '回复内容为空'}
            ok = await self.send_dm(event, text)
            return {'ok': bool(ok), 'text': text}
        if name == 'reply_comment':
            text = str(args.get('text') or '').strip()
            if not text:
                return {'error': '回复内容为空'}
            text = self._maybe_mention_owner(event, text, args)
            ok = await self.send_reply(event, text)
            return {'ok': bool(ok), 'text': text}
        return {'error': f'未知工具: {name}'}

    async def handle(self, event: Dict[str, Any]) -> bool:
        """Return True when a reply was sent."""
        try:
            if hasattr(self.bili, 'get_self_info') and not self.self_uid:
                self_info = await self.bili.get_self_info() or {}
                self.self_uid = self_info.get('uid') or self.self_uid
                self.self_name = self_info.get('name') or self.self_name
        except Exception:  # noqa: BLE001
            pass
        if event.get('images'):
            from core.comment_images import describe_comment_images
            await describe_comment_images([event], self.ai, max_images=2)
        messages = [
            {'role': 'system', 'content': self._system_prompt(event)},
            {
                'role': 'user',
                'content': '当前事件：' + json.dumps(event, ensure_ascii=False, default=str),
            },
        ]
        for step in range(MAX_STEPS):
            response = await self.ai.chat(messages, temperature=0.7, max_tokens=700)
            if not response:
                return False
            decision = _parse(response)
            if decision is None:
                messages.append({'role': 'assistant', 'content': response})
                messages.append({'role': 'user', 'content': '只输出合法 JSON。'})
                continue
            if str(decision.get('action')).lower() == 'finish':
                logger.info(f"对话 Agent 选择不回复: {decision.get('reason', '')}")
                return False
            if str(decision.get('action')).lower() == 'reply':
                text = str(decision.get('text') or '').strip()
                if not text:
                    return False
                if event.get('scope') == 'dm' and self.send_dm is not None:
                    return bool(await self.send_dm(event, text))
                return bool(await self.send_reply(event, text))
            tool = str(decision.get('tool') or '')
            args = decision.get('arguments') or {}
            if not isinstance(args, dict):
                args = {}
            result = await self._execute(tool, args, event)
            if tool == 'reply_comment' and isinstance(result, dict) and result.get('ok'):
                return True
            messages.append({'role': 'assistant', 'content': response})
            messages.append({
                'role': 'user',
                'content': '工具结果：' + json.dumps(result, ensure_ascii=False, default=str)[:2200]
                + '\n继续决定下一步，或 finish。',
            })
        return False
