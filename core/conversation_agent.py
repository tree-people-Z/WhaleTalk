"""Model-driven conversation agent for replies in own/other comment threads.

The fixed pipeline still handles video discovery/analysis/top-level comments.
Replies are decided by the model through read/write tools.
"""

import json
from typing import Any, Awaitable, Callable, Dict, Optional

from loguru import logger

from core.long_term_memory import load_memory

MAX_STEPS = 5
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
        send_dm_image: Optional[Callable[..., Awaitable[bool]]] = None,
    ):
        self.bili = bili_api
        self.db = db
        self.ai = ai_client
        self.config = config
        self.send_reply = send_reply
        self.send_dm = send_dm
        self.send_dm_image = send_dm_image

    def _read_tools(self, scope: str) -> list:
        if scope == 'dm':
            return [
                {
                    'name': 'read_memory',
                    'description': '读取长期记忆（事件、经验、风格）。',
                    'parameters': {},
                },
                {
                    'name': 'reply_dm',
                    'description': '回复当前私信。不想回就 finish。',
                    'parameters': {'text': 'string'},
                },
                {
                    'name': 'send_dm_image',
                    'description': '从图片库挑一张图发给对方，可配一句话。',
                    'parameters': {'caption': 'string(可选)'},
                },
            ]
        return [
            {
                'name': 'get_comment_thread',
                'description': '读取整栋评论楼，了解谁在跟谁说话。',
                'parameters': {'root_rpid': 'int', 'aid': 'int', 'limit': 'int(1-50)'},
            },
            {
                'name': 'get_video_info',
                'description': '读取视频标题、简介、UP主。',
                'parameters': {'bvid': 'string'},
            },
            {
                'name': 'read_memory',
                'description': '读取长期记忆（事件、经验、风格）。',
                'parameters': {},
            },
            {
                'name': 'reply_comment',
                'description': '回复目标评论。只在判断值得接话时调用。',
                'parameters': {'text': 'string'},
            },
            {
                'name': 'like_comment',
                'description': '给目标评论点赞。',
                'parameters': {},
            },
        ]

    def _system_prompt(self, event: Dict[str, Any]) -> str:
        from utils.persona_defaults import load_configured_persona
        persona = load_configured_persona(self.config, 4000)
        memory = load_memory(3000)
        scope = event.get('scope')
        if event.get('is_direct_at'):
            scope_rule = (
                '有人直接 @ 你。即使这是新楼，也可以回复；仍然由你判断值不值得回。'
            )
        elif scope == 'dm':
            scope_rule = (
                '这是B站私信。可以回复，也可以选择不回；不要群发，不要连续追问。'
                '有合适的图片时可以发一张，但不要频繁发图。'
            )
        elif scope == 'own_thread':
            scope_rule = (
                '这是你自己的评论楼，别人在回复你。可以回复，也可以选择不回；'
                '不要为了礼貌强行回复。'
            )
        else:
            scope_rule = (
                '这是你之前参与过的评论楼。只有别人回复你、话题继续时才接话；'
                '不要主动加入新的楼，也不要打断别人之间的对话。'
            )
        return (
            f'# 核心人格\n{persona or "你是鲸鱼娘。"}\n\n'
            f'# 长期记忆\n{memory or "（暂无）"}\n\n'
            f'# 当前规则\n{scope_rule}\n\n'
            f'# 可用工具\n{json.dumps(self._read_tools(scope), ensure_ascii=False)}\n\n'
            '每步只输出一个 JSON：\n'
            '{"action":"tool","tool":"工具名","arguments":{...}}\n'
            '或 {"action":"finish","reason":"不回/已回复"}\n'
            '最多 5 步。不要编造工具结果。'
        )

    async def _execute(self, name: str, args: Dict[str, Any], event: Dict[str, Any]) -> Any:
        if name == 'get_comment_thread':
            aid = int(args.get('aid') or event.get('aid') or 0)
            root = int(args.get('root_rpid') or event.get('root_rpid') or 0)
            if not aid or not root:
                return {'error': '缺少 aid 或 root_rpid'}
            comments = await self.bili.get_comment_thread(aid, root, count=50)
            return [
                {
                    'user': item.get('user'),
                    'content': (item.get('content') or '')[:160],
                    'rpid': item.get('rpid'),
                    'parent': item.get('parent'),
                }
                for item in (comments or [])[:30]
            ]
        if name == 'get_video_info':
            return await self.bili.get_video_info(
                str(args.get('bvid') or event.get('bvid') or '')
            ) or {'error': '视频读取失败'}
        if name == 'read_memory':
            return {'memory': load_memory(4000) or '（暂无长期记忆）'}
        if name == 'like_comment':
            aid = event.get('aid')
            rpid = event.get('rpid')
            if not aid or not rpid:
                return {'error': '缺少评论信息'}
            try:
                await self.bili.like_comment(int(aid), int(rpid))
                return {'ok': True}
            except Exception as exc:  # noqa: BLE001
                return {'error': str(exc)}
        if name == 'send_dm_image':
            if self.send_dm_image is None:
                return {'error': '当前不能发图'}
            caption = str(args.get('caption') or '').strip()
            ok = await self.send_dm_image(event, caption)
            return {'ok': bool(ok)}
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
            ok = await self.send_reply(event, text)
            return {'ok': bool(ok), 'text': text}
        return {'error': f'未知工具: {name}'}

    async def handle(self, event: Dict[str, Any]) -> bool:
        """Return True when a reply was sent."""
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
