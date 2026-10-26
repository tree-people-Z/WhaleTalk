"""
评论管理模块
负责监听评论区的@提醒并回复
"""

import asyncio
import json
import re
from pathlib import Path
from typing import List, Dict, Any
from datetime import datetime
from loguru import logger

from core.bilibili_api import BilibiliAPI
from core.ai_client import AIClient
from utils.database import Database
from utils.config_manager import ConfigManager
from utils.probability import roll_probability


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

    async def check_mentions(self) -> List[Dict[str, Any]]:
        """
        检查是否有人@我或回复我的评论

        Returns:
            未处理的@提醒和回复列表
        """
        if not self.config.get('interaction.comment_monitor', False):
            return []

        try:
            mentions = []
            already_replied = self.db.get_replied_comment_ids()
            self.processed_rpids.update(already_replied)
            self.processed_rpids.update(self._load_skipped())
            # 自己发过的评论/回复不能当作“别人回复我”，否则会自问自答刷屏。
            own_rpids = self.db.get_own_comment_rpids()
            self.processed_rpids.update(own_rpids)
            self_uid = None
            self_name = ''
            try:
                self_info = await self.bili.get_self_info()
                self_uid = self_info.get('uid')
                self_name = self_info.get('name') or ''
            except Exception as exc:
                logger.debug(f"获取当前账号信息失败: {exc}")

            # 1. 检查我发送的评论和回复是否有回复
            my_comments = self.db.get_recent_comments(limit=20, include_replies=True)
            found_rpids = set()

            for my_comment in my_comments:
                if not my_comment.get('aid'):
                    continue

                aid = my_comment['aid']
                my_rpid = my_comment.get('rpid')
                thread_root = my_comment.get('thread_root') or my_rpid

                if not my_rpid:
                    continue

                # 获取该视频的评论
                try:
                    comments = await self.bili.get_comments(
                        aid, count=50, include_replies=True,
                        root_rpids={thread_root}
                    )

                    for comment in comments:
                        # 检查是否是回复我的评论/回复
                        root = comment.get('root', 0)
                        parent = comment.get('parent', 0)
                        rpid = comment.get('rpid')

                        # 跳过自己发出的评论（含自动回复产生的楼层），避免自问自答。
                        if rpid in self.processed_rpids or rpid in found_rpids:
                            continue
                        if self_uid is not None and comment.get('mid') == self_uid:
                            logger.debug(f"跳过自己发出的评论: {rpid}")
                            continue
                        if self_name and comment.get('user') == self_name:
                            logger.debug(f"跳过自己账号的评论: {rpid}")
                            continue

                        # 只有直接回复我，或在我的楼里直接回复我，才算对我说；
                        # 别人在我的楼里回复另一个网友时，不要插话。
                        direct_to_me = parent == my_rpid
                        top_level_to_me = (
                            root == my_rpid and parent in (0, None, root)
                        )
                        if direct_to_me or top_level_to_me:
                            mentions.append({
                                'rpid': rpid,
                                'root_rpid': root or my_rpid,
                                'user': comment.get('user'),
                                'mid': comment.get('mid'),
                                'content': comment.get('content'),
                                'aid': aid,
                                'bvid': my_comment.get('bvid'),
                                'type': 'reply',
                                'video_title': my_comment.get('video_title', '')
                            })
                            found_rpids.add(rpid)
                            logger.info(f"发现回复: {comment.get('user')} -> {comment.get('content')[:30]}")

                except Exception as e:
                    logger.debug(f"检查评论回复失败 aid={aid}: {e}")
                    continue

                await asyncio.sleep(0.5)  # 避免请求过快

            # 2. 自己投稿视频下的评论（仅在“所有人”范围）
            from utils.reply_scope import REPLY_SCOPE_ALL, resolve_reply_scope
            if resolve_reply_scope(self.config) == REPLY_SCOPE_ALL:
                own_mentions = await self._check_own_video_comments(
                    self_uid, self_name, found_rpids
                )
                mentions = own_mentions + mentions

            logger.info(f"检查完成，发现 {len(mentions)} 条新回复")
            return mentions

        except Exception as e:
            logger.error(f"检查@提醒失败: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return []

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

    @staticmethod
    def _addressed_to_other(content: str, self_name: str) -> bool:
        """评论是否明确 @ 了别人；是的话不要当成本人在被搭话。"""
        if not content:
            return False
        names = re.findall(r'@([^\s@:：,，。！!？?]+)', content)
        if not names:
            return False
        if self_name and any(name == self_name for name in names):
            return False
        return True

    async def _check_own_video_comments(
        self, self_uid, self_name, found_rpids: set
    ) -> List[Dict[str, Any]]:
        """检查自己投稿视频下的新评论，按时间优先返回。"""
        try:
            video_limit = int(
                self.config.get('interaction.own_video_count', 10)
            )
        except (TypeError, ValueError):
            video_limit = 10
        try:
            max_replies = int(
                self.config.get('interaction.max_own_video_replies_per_check', 10)
            )
        except (TypeError, ValueError):
            max_replies = 10
        if max_replies <= 0:
            return []
        try:
            videos = await self.bili.get_own_videos(limit=video_limit)
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"获取自己投稿视频失败: {exc}")
            return []

        results = []
        for video in videos or []:
            if len(results) >= max_replies:
                break
            aid = video.get('aid')
            if not aid:
                continue
            try:
                comments = await self.bili.get_comments(
                    aid, sort=0, count=20
                )
            except Exception as exc:  # noqa: BLE001
                logger.debug(f"获取自己视频评论失败 aid={aid}: {exc}")
                continue
            for comment in comments or []:
                rpid = comment.get('rpid')
                if not rpid or rpid in self.processed_rpids or rpid in found_rpids:
                    continue
                # 只处理顶层评论，楼中楼由“回复我的评论”路径处理。
                if comment.get('root') not in (0, None):
                    continue
                if self_uid is not None and comment.get('mid') == self_uid:
                    continue
                if self_name and comment.get('user') == self_name:
                    continue
                if self._addressed_to_other(comment.get('content'), self_name):
                    logger.info(
                        f"跳过 @ 其他人的评论: {comment.get('user')} "
                        f"-> {(comment.get('content') or '')[:30]}"
                    )
                    continue
                results.append({
                    'rpid': rpid,
                    'root_rpid': rpid,
                    'user': comment.get('user'),
                    'mid': comment.get('mid'),
                    'content': comment.get('content'),
                    'aid': aid,
                    'bvid': video.get('bvid'),
                    'type': 'own_video',
                    'video_title': video.get('title', ''),
                })
                found_rpids.add(rpid)
                if len(results) >= max_replies:
                    break
            await asyncio.sleep(0.5)
        if results:
            logger.info(f"自己视频下发现 {len(results)} 条待回复评论")
        return results

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
                'user': mention.get('user') or '',
                'mid': mention.get('mid'),
                'content': mention.get('content') or '',
                'aid': mention.get('aid'),
                'bvid': mention.get('bvid') or '',
                'video_title': mention.get('video_title') or '',
            }
            agent = ConversationAgent(
                self.bili, self.db, self.ai, self.config, self._send_agent_reply
            )
            success = await agent.handle(event)
            self.processed_rpids.add(rpid)
            self._mark_skipped(rpid)
            if success:
                self.db.record_thread_reply(root)
            return success
        except Exception as exc:  # noqa: BLE001
            logger.error(f"对话 Agent 处理失败: {exc}")
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
        """Reply to unread B站 private messages, with strict daily limits."""
        if not self.config.get('interaction.reply_private_messages', True):
            return 0
        if getattr(self.bili, 'is_blocked', lambda: False)():
            return 0
        try:
            max_per_check = int(self.config.get('limits.max_dm_per_check', 3))
        except (TypeError, ValueError):
            max_per_check = 3
        try:
            max_per_day = int(self.config.get('limits.max_dm_per_day', 10))
        except (TypeError, ValueError):
            max_per_day = 10
        try:
            if self.db.get_today_memory_event_count('dm') >= max_per_day:
                return 0
            sessions = await self.bili.get_private_sessions(session_type=1)
            self_info = await self.bili.get_self_info()
            self_uid = self_info.get('uid')
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"读取私信会话失败: {exc}")
            return 0
        sent = 0
        for session in sessions:
            if sent >= max_per_check:
                break
            talker_id = session.get('talker_id')
            if not talker_id:
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
            }
            from core.conversation_agent import ConversationAgent
            agent = ConversationAgent(
                self.bili,
                self.db,
                self.ai,
                self.config,
                self._send_agent_reply,
                self._send_agent_dm,
                self._send_agent_dm_image,
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

    async def _send_agent_dm_image(self, event: Dict[str, Any], caption: str = '') -> bool:
        talker_id = int(event.get('talker_id') or 0)
        if not talker_id:
            return False
        asset = self.db.get_random_media_asset()
        if not asset:
            return False
        path = Path(asset.get('path') or '')
        if not path.is_file():
            return False
        if not await self.bili.send_private_picture(talker_id, str(path)):
            return False
        if caption:
            await self.bili.send_private_message(talker_id, caption)
        self.db.mark_media_asset_used(asset['id'])
        try:
            self.db.add_memory_event(
                'dm_image',
                user_name=event.get('user') or '',
                user_mid=talker_id,
                content=event.get('content') or '',
                my_content=caption or '[图片]',
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"记录发图记忆失败: {exc}")
        return True

    def _load_skipped(self) -> set:
        try:
            path = Path('data') / 'skipped_mentions.json'
            if path.is_file():
                return set(int(item) for item in json.loads(path.read_text(encoding='utf-8')))
        except (OSError, ValueError, TypeError):
            pass
        return set()

    def _mark_skipped(self, rpid: int) -> None:
        skipped = self._load_skipped()
        skipped.add(int(rpid))
        try:
            path = Path('data') / 'skipped_mentions.json'
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps(sorted(skipped)[-1000:]), encoding='utf-8')
        except OSError:
            pass

    def _load_at_seen(self) -> set:
        try:
            path = Path('data') / 'at_seen.json'
            if path.is_file():
                return set(int(item) for item in json.loads(path.read_text(encoding='utf-8')))
        except (OSError, ValueError, TypeError):
            pass
        return set()

    def _mark_at_seen(self, rpid: int) -> None:
        seen = self._load_at_seen()
        seen.add(int(rpid))
        try:
            path = Path('data') / 'at_seen.json'
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(
                json.dumps(sorted(seen)[-500:]), encoding='utf-8'
            )
        except OSError:
            pass

    async def check_at_messages(self) -> List[Dict[str, Any]]:
        """Read direct @ notifications, including comments in new threads."""
        if not self.config.get('interaction.comment_monitor', False):
            return []
        try:
            seen = self._load_at_seen()
            items = await self.bili.get_at_messages(since_time=0)
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"读取@消息失败: {exc}")
            return []
        results = []
        for item in items or []:
            rpid = item.get('rpid')
            if not rpid or rpid in seen or rpid in self.processed_rpids:
                continue
            item['is_direct_at'] = True
            results.append(item)
            if len(results) >= 5:
                break
        return results

    @staticmethod
    def _is_owner_event(event: Dict[str, Any], owner_name: str, owner_uid: str) -> bool:
        mid = str(event.get('mid') or '')
        user = event.get('user') or ''
        return bool(
            (owner_uid and mid == str(owner_uid))
            or (owner_name and user == owner_name)
        )

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
                if self._is_owner_event(item, owner_name, owner_uid)
            ]
            at_messages = [
                item for item in at_messages
                if self._is_owner_event(item, owner_name, owner_uid)
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
