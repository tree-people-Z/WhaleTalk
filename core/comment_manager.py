"""
评论管理模块
负责监听评论区的@提醒并回复
"""

import asyncio
from typing import List, Dict, Any
from datetime import datetime
from loguru import logger

from core.bilibili_api import BilibiliAPI
from core.ai_client import AIClient
from utils.database import Database
from utils.config_manager import ConfigManager
from utils.probability import roll_probability
from core.comment_events import CommentEventCollector


class CommentManager:
    """评论管理器"""

    def __init__(
        self,
        bili_api: BilibiliAPI,
        ai_client: AIClient,
        database: Database,
        config: ConfigManager
    ):
        self.bili = bili_api
        self.ai = ai_client
        self.db = database
        self.config = config

        # 记录已处理的评论ID
        self.processed_rpids = set()
        self.events = CommentEventCollector(
            self.bili, self.db, self.config, self.processed_rpids
        )

    def _roll_probability(self, key: str, default: float) -> bool:
        return roll_probability(self.config, key, default)

    def _daily_send_quota_remaining(self) -> int:
        try:
            max_total = int(self.config.get('limits.max_comments_per_day', 60))
        except (TypeError, ValueError):
            max_total = 60
        try:
            used = int(self.db.get_today_comment_count(include_replies=True))
        except (TypeError, ValueError, AttributeError):
            used = 0
        return max(0, max_total - used)

    async def check_mentions(self) -> List[Dict[str, Any]]:
        return await self.events.check_mentions()

    async def check_at_messages(self) -> List[Dict[str, Any]]:
        return await self.events.check_at_messages()

    @staticmethod
    def _is_owner_event(event: Dict[str, Any], owner_name: str, owner_uid: str) -> bool:
        return CommentEventCollector._is_owner_event(event, owner_name, owner_uid)

    def _mark_skipped(self, rpid: int) -> None:
        self.events._mark_skipped(rpid)

    async def reply_to_mention(self, mention: Dict[str, Any]) -> bool:
        """Let the model decide whether/how to reply in own or other threads."""
        try:
            rpid = mention.get('rpid')
            if not rpid or rpid in self.processed_rpids:
                return False
            if self._daily_send_quota_remaining() <= 0:
                logger.info("今日发送配额已用完，跳过回复")
                return False
            if getattr(self.bili, 'is_posting_blocked', lambda: False)() is True:
                return False

            root = mention.get('root_rpid') or rpid
            from core.conversation_agent import (
                MAX_REPLIES_PER_THREAD_DAY,
                THREAD_COOLDOWN_MINUTES,
                ConversationAgent,
            )
            try:
                own_rpids = self.db.get_own_comment_rpids()
            except Exception:  # noqa: BLE001
                own_rpids = set()
            scope = 'own_thread' if int(root) in own_rpids else 'other_thread'
            state = self.db.get_thread_state(root)
            now = datetime.now()
            reply_count = int(state.get('reply_count') or 0)
            last = state.get('last_reply_at')
            if last and last.date() != now.date():
                reply_count = 0
            if reply_count >= MAX_REPLIES_PER_THREAD_DAY:
                logger.info(f"同一楼今日回复已达上限: {root}")
                return False
            if last and (now - last).total_seconds() < THREAD_COOLDOWN_MINUTES * 60:
                logger.info(f"同一楼回复冷却中: {root}")
                return False

            event = {
                'rpid': rpid,
                'root_rpid': root,
                'scope': scope,
                'root_owner_is_me': scope == 'own_thread',
                'bot_participated': bool(state.get('bot_participated')),
                'bot_reply_count': reply_count,
                'last_bot_reply_at': last.isoformat() if last else '',
                'is_reply_to_bot': True,
                'is_direct_at': bool(mention.get('is_direct_at')),
                'owner_name': self.config.get('bilibili.owner_name', ''),
                'user': mention.get('user') or '',
                'mid': mention.get('mid'),
                'content': mention.get('content') or '',
                'mentioned_users': mention.get('mentioned_users') or [],
                'addressed_to_other': bool(mention.get('addressed_to_other')),
                'parent_content': mention.get('parent_content') or '',
                'root_content': mention.get('root_content') or '',
                'images': mention.get('images') or [],
                'aid': mention.get('aid'),
                'bvid': mention.get('bvid') or '',
                'video_title': mention.get('video_title') or '',
            }
            agent = ConversationAgent(
                self.bili,
                self.db,
                self.ai,
                self.config,
                self._send_agent_reply,
                None,
                self._send_agent_video_comment,
            )
            success = await agent.handle(event)
            self.processed_rpids.add(rpid)
            self.events._mark_skipped(rpid)
            if success:
                self.db.record_thread_reply(root)
            return success
        except Exception as exc:  # noqa: BLE001
            logger.error(f"对话 Agent 处理失败: {exc}")
            return False

    async def _ensure_video_title(self, bvid: str, aid: int) -> None:
        """Keep a title row so reply history never falls back to a BV id."""
        bvid = str(bvid or '').strip()
        if not bvid or not hasattr(self.bili, 'get_video_info'):
            return
        try:
            info = await self.bili.get_video_info(bvid)
            if info:
                self.db.ensure_video_record(
                    bvid,
                    int(info.get('aid') or aid or 0),
                    str(info.get('title') or ''),
                    str(info.get('owner') or ''),
                )
        except Exception as exc:  # noqa: BLE001
            logger.debug(f'补全回复视频标题失败 {bvid}: {exc}')

    async def _send_agent_video_comment(
        self, event: Dict[str, Any], bvid: str, text: str
    ) -> bool:
        """Comment under a video the viewer asked the bot to look at."""
        try:
            if not bvid or not text.strip():
                return False
            if self._daily_send_quota_remaining() <= 0:
                return False
            if getattr(self.bili, 'is_posting_blocked', lambda: False)() is True:
                return False
            if self.db.has_commented_video(bvid):
                return False
            info = await self.bili.get_video_info(bvid)
            if not info or not info.get('aid'):
                return False
            aid = int(info['aid'])
            success = await self.bili.post_comment(aid=aid, text=text)
            if not success:
                return False
            rpid = getattr(self.bili, 'last_comment_rpid', None)
            self.db.add_comment_record(
                bvid=bvid,
                aid=aid,
                content=text,
                comment_type='post',
                success=True,
                rpid=rpid,
                thread_root=rpid,
            )
            await self._ensure_video_title(bvid, aid)
            try:
                self.db.add_memory_event(
                    'comment',
                    user_name=event.get('user') or '',
                    user_mid=event.get('mid'),
                    aid=aid,
                    bvid=bvid,
                    video_title=info.get('title') or '',
                    content=event.get('content') or '',
                    my_content=text,
                )
            except Exception as exc:  # noqa: BLE001
                logger.debug(f"记录视频评论记忆失败: {exc}")
            logger.info(f"✅ Agent 在请求视频下评论: {info.get('title')}")
            return True
        except Exception as exc:  # noqa: BLE001
            logger.error(f"Agent 视频评论失败: {exc}")
            return False

    async def _send_agent_reply(self, event: Dict[str, Any], text: str) -> bool:
        """Execute a model-selected reply after policy checks."""
        try:
            aid = int(event.get('aid') or 0)
            rpid = event.get('rpid')
            root = event.get('root_rpid') or rpid
            if not aid or not rpid or not text.strip():
                return False
            if self._daily_send_quota_remaining() <= 0:
                return False
            success = await self.bili.post_comment(
                aid=aid,
                text=text,
                root_rpid=root,
                parent_rpid=rpid,
            )
            if not success:
                return False
            self.db.add_comment_record(
                bvid=event.get('bvid', ''),
                aid=aid,
                content=text,
                comment_type='reply',
                success=True,
                rpid=getattr(self.bili, 'last_comment_rpid', None),
                parent_rpid=rpid,
                thread_root=root,
                target_user=event.get('user') or '',
                parent_content=event.get('content') or '',
            )
            await self._ensure_video_title(event.get('bvid', ''), aid)
            try:
                self.db.add_memory_event(
                    'reply',
                    user_name=event.get('user') or '',
                    user_mid=event.get('mid'),
                    aid=aid,
                    bvid=event.get('bvid', ''),
                    video_title=event.get('video_title') or '',
                    content=event.get('content') or '',
                    my_content=text,
                )
            except Exception as exc:  # noqa: BLE001
                logger.debug(f"记录回复记忆失败: {exc}")
            if (
                self.config.get('interaction.like_replied_comments', True)
                and self._roll_probability('prob_like_reply', 50)
            ):
                try:
                    await self.bili.like_comment(aid, rpid)
                except Exception as exc:  # noqa: BLE001
                    logger.debug(f"给网友评论点赞失败: {exc}")
            logger.info(f"✅ 对话回复成功: @{event.get('user')}")
            return True
        except Exception as exc:  # noqa: BLE001
            logger.error(f"发送对话回复失败: {exc}")
            return False

    async def check_private_messages(self) -> int:
        """Reply to unread B站 private messages."""
        if not self.config.get('interaction.reply_private_messages', True):
            return 0
        if getattr(self.bili, 'is_blocked', lambda: False)():
            return 0
        try:
            sessions = await self.bili.get_private_sessions(session_type=1)
            self_info = await self.bili.get_self_info()
            self_uid = self_info.get('uid')
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"读取私信会话失败: {exc}")
            return 0
        sent = 0
        for session in sessions:
            talker_id = session.get('talker_id')
            if not talker_id:
                continue
            if str(talker_id).startswith('844424930'):
                logger.debug(f"跳过B站系统私信会话: {talker_id}")
                continue
            try:
                messages = await self.bili.get_private_messages(talker_id)
            except Exception as exc:  # noqa: BLE001
                logger.debug(f"读取私信消息失败 {talker_id}: {exc}")
                continue
            incoming = [
                message for message in messages
                if message.get('sender_uid') != self_uid
                and (message.get('content') or '').strip()
                and message.get('content') != '[消息已撤回]'
            ]
            if not incoming:
                continue
            last = incoming[-1]
            timestamp = int(last.get('timestamp') or 0)
            if timestamp <= self.db.get_dm_state(talker_id):
                continue
            image_description = ''
            image_url = last.get('image_url') or ''
            if image_url:
                try:
                    from utils.media_library import collect_image
                    asset = await collect_image(
                        self.db,
                        image_url,
                        source='dm',
                        ai_client=self.ai,
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.debug(f"收集私信图片失败: {exc}")
                    asset = None
                if asset:
                    image_description = (
                        asset.get('description') or '收到一张图片，内容未能识别'
                    )
            event = {
                'scope': 'dm',
                'talker_id': talker_id,
                'user': session.get('name') or '',
                'mid': talker_id,
                'content': last.get('content') or '',
                'image_description': image_description,
                'owner_name': self.config.get('bilibili.owner_name', ''),
            }
            from core.conversation_agent import ConversationAgent
            agent = ConversationAgent(
                self.bili,
                self.db,
                self.ai,
                self.config,
                self._send_agent_reply,
                self._send_agent_dm,
                self._send_agent_video_comment,
            )
            replied_now = await agent.handle(event)
            self.db.set_dm_state(talker_id, timestamp)
            if replied_now:
                sent += 1
                logger.info(f"✅ 私信已回复: {session.get('name') or talker_id}")
                await asyncio.sleep(3)
        return sent

    async def _send_agent_dm(self, event: Dict[str, Any], text: str) -> bool:
        talker_id = int(event.get('talker_id') or 0)
        if not talker_id or not text.strip():
            return False
        if not await self.bili.send_private_message(talker_id, text):
            return False
        try:
            self.db.add_memory_event(
                'dm',
                user_name=event.get('user') or '',
                user_mid=talker_id,
                content=event.get('content') or '',
                my_content=text,
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"记录私信记忆失败: {exc}")
        return True

    async def check_and_reply(self) -> Dict[str, Any]:
        """检查新回复；自动回复开启时逐条交给对话模型处理。"""
        mentions = await self.check_mentions()
        at_messages = await self.check_at_messages()
        from utils.reply_scope import REPLY_SCOPE_OWNER, resolve_reply_scope
        if resolve_reply_scope(self.config) == REPLY_SCOPE_OWNER:
            owner_name = self.config.get('bilibili.owner_name', '')
            owner_uid = self.config.get('bilibili.owner_uid', '')
            mentions = [
                item for item in mentions
                if CommentEventCollector._is_owner_event(item, owner_name, owner_uid)
            ]
            at_messages = [
                item for item in at_messages
                if CommentEventCollector._is_owner_event(item, owner_name, owner_uid)
            ]
        replied = 0
        if self.config.get('interaction.auto_reply', True):
            for mention in mentions + at_messages:
                if self._daily_send_quota_remaining() <= 0:
                    logger.warning("今日发送配额已用完（评论+回复），停止本轮回复")
                    break
                if getattr(self.bili, 'is_posting_blocked', lambda: False)() is True:
                    logger.warning("评论发送冷却中，停止本轮回复")
                    break
                if await self.reply_to_mention(mention):
                    replied += 1
                if mention.get('type') == 'at':
                    self._mark_at_seen(mention.get('rpid'))
                await asyncio.sleep(2)
        dm_replied = await self.check_private_messages()
        return {
            'replied': replied,
            'dm_replied': dm_replied,
            'mentions': mentions,
            'at_messages': at_messages,
        }
