"""Comment/@ event collection and persistence."""

import asyncio
import json
import re
from pathlib import Path
from typing import List, Dict, Any

from loguru import logger


class CommentEventCollector:
    def __init__(self, bili, db, config, processed_rpids: set):
        self.bili = bili
        self.db = db
        self.config = config
        self.processed_rpids = processed_rpids

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
                    content_by_rpid = {
                        item.get('rpid'): item.get('content') or ''
                        for item in comments
                    }

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
                                'parent_content': content_by_rpid.get(parent, ''),
                                'root_content': content_by_rpid.get(root, ''),
                                'images': comment.get('images') or [],
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

    @staticmethod
    def _mentioned_users(content: str) -> list:
        if not content:
            return []
        return re.findall(r'@([^\s@:：,，。！!？?]+)', content)

    @staticmethod
    def _addressed_to_other(content: str, self_name: str) -> bool:
        """评论是否明确 @ 了别人；仅作为上下文，不再直接丢弃。"""
        names = CommentEventCollector._mentioned_users(content)
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
                content = comment.get('content') or ''
                mentioned = self._mentioned_users(content)
                addressed_to_other = self._addressed_to_other(content, self_name)
                results.append({
                    'rpid': rpid,
                    'root_rpid': rpid,
                    'user': comment.get('user'),
                    'mid': comment.get('mid'),
                    'content': comment.get('content'),
                    'mentioned_users': mentioned,
                    'addressed_to_other': addressed_to_other,
                    'images': comment.get('images') or [],
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
