"""Free-form agent: all B站 interfaces, persona/diary/memory, no fixed workflow."""

import asyncio
import json
from datetime import datetime
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


class FreeAgent:
    """One autonomous session. The model chooses every action."""

    def __init__(self, bili_api, ai_client, db, config):
        self.bili = bili_api
        self.ai = ai_client
        self.db = db
        self.config = config
        self.bili_tool = BiliTool(bili_api, db, config)
        self._stop = None
        self.enable_frame_analysis = True
        self.local_transcriber = None
        from core.comment_manager import CommentManager
        self.comment_manager = CommentManager(bili_api, ai_client, db, config)

    def request_stop(self):
        if self._stop is not None:
            self._stop.set()

    def _system_prompt(self) -> str:
        tools = [self.bili_tool.spec(), *DIARY_TOOLS]
        owner = self.config.get('bilibili.owner_name', '') or '未配置'
        return (
            f'{build_agent_context(self.config)}\n\n'
            f'# 账号\n主人昵称：{owner}\n\n'
            f'# 可用工具\n{json.dumps(tools, ensure_ascii=False)}\n\n'
            '# 输出\n'
            '每步只输出一个 JSON：\n'
            '{"action":"tool","tool":"工具名","arguments":{...}}\n'
            '或 {"action":"finish","reason":"这一轮做了什么/为什么不做"}\n'
            '工具结果会返回给你。最多 12 步。'
        )

    async def _call_tool(self, name: str, args: dict) -> Any:
        if name == 'bili_api':
            method = str(args.get('method') or '')
            params = args.get('arguments') or args.get('params') or {}
            return await self.bili_tool.call(method, params)
        if name == 'read_diary':
            return read_diary(str(args.get('day') or ''))
        if name == 'write_diary':
            path = append_diary(str(args.get('content') or ''))
            return {'ok': True, 'path': str(path)}
        return {'error': f'未知工具: {name}'}

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
            or args.get('method_name') or ''
        )
        params = (
            args.get('arguments') or args.get('params')
            or args.get('parameters') or args.get('args') or {}
        )
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
        return 'bili_api', {'method': method, 'arguments': params}

    @staticmethod
    def _log_io(tool: str, args: dict, result: Any) -> None:
        if tool != 'bili_api':
            return
        method = str(args.get('method') or '')
        params = args.get('arguments') or {}
        if method == 'get_private_messages' and isinstance(result, list) and result:
            last = result[-1]
            content = str(last.get('content') or '')[:80]
            logger.info(f'收到私信 {params.get("talker_id")}: {content}')
        elif method == 'get_at_messages' and isinstance(result, list) and result:
            last = result[-1]
            user = last.get('user') or last.get('nickname') or '网友'
            content = str(last.get('content') or '')[:80]
            logger.info(f'收到@{user}: {content}')
        elif method in {'get_comments', 'get_comment_thread'} and isinstance(result, list) and result:
            last = result[-1]
            user = last.get('user') or last.get('nickname') or '网友'
            content = str(last.get('content') or '')[:80]
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
                    summary = str(decision.get('reason') or '')
                    break
                tool = str(decision.get('tool') or decision.get('name') or 'bili_api')
                args = decision.get('arguments') or {}
                if not isinstance(args, dict):
                    args = {}
                tool, args = self._normalize_call(tool, args)
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
