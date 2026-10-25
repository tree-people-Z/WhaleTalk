"""
评论管理模块
负责监听评论区的@提醒并回复
"""

import asyncio
import re
from typing import List, Dict, Any, Optional
from datetime import datetime, timedelta
from loguru import logger

from core.bilibili_api import BilibiliAPI
from core.ai_client import AIClient
from utils.database import Database
from utils.config_manager import ConfigManager


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

            # 2. 自己投稿视频下的评论（必回）
            if self.config.get('interaction.reply_own_video_comments', True):
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

    async def _comment_on_requested_video(
        self, requested_video: Dict[str, Any], mention: Dict[str, Any], persona: str
    ) -> Optional[str]:
        """对方让看视频时，去她的视频下面留一条真实评论。"""
        if not requested_video:
            return None
        if not self.config.get('interaction.comment_requested_video', True):
            return None
        aid = requested_video.get('aid')
        bvid = requested_video.get('bvid', '')
        if not aid or not bvid:
            return None
        if mention.get('aid') == aid:
            return None
        if getattr(self.bili, 'is_blocked', lambda: False)():
            return None
        if getattr(self.bili, 'is_posting_blocked', lambda: False)() is True:
            return None
        try:
            self_info = await self.bili.get_self_info()
            if requested_video.get('owner_mid') == self_info.get('uid'):
                return None
        except Exception:  # noqa: BLE001
            pass
        try:
            if self.db.has_commented_video(bvid):
                logger.debug(f"已经在她视频下评论过，跳过: {bvid}")
                return None
            max_comments = int(self.config.get('limits.max_comments_per_day', 96))
            if self.db.get_today_comment_count() >= max_comments:
                logger.info("今日顶层评论已达上限，跳过对方视频下的评论")
                return None
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"检查视频评论记录失败: {exc}")

        video_content = (
            f"简介：{requested_video.get('desc', '')}\n"
            f"字幕片段：{requested_video.get('subtitle', '')}"
        )
        comment_text = await self.ai.generate_comment(
            requested_video.get('title', ''),
            video_content,
            persona,
        )
        if not comment_text:
            return None
        success = await self.bili.post_comment(aid=aid, text=comment_text)
        if not success:
            logger.warning(f"在她视频下评论失败: {bvid}")
            return None
        try:
            self.db.add_comment_record(
                bvid=bvid,
                aid=aid,
                content=comment_text,
                comment_type='post',
                success=True,
                rpid=getattr(self.bili, 'last_comment_rpid', None),
                thread_root=getattr(self.bili, 'last_comment_rpid', None),
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug(f"记录视频评论失败: {exc}")
        logger.info(f"✅ 已在她视频下评论: {requested_video.get('title')} - {comment_text}")
        return comment_text

    async def reply_to_mention(
        self,
        mention: Dict[str, Any]
    ) -> bool:
        """
        回复@提醒

        Args:
            mention: @提醒信息

        Returns:
            是否成功
        """
        try:
            # 提取信息
            rpid = mention.get('rpid')
            user = mention.get('user')
            content = mention.get('content')
            video_title = mention.get('video_title', '')
            aid = mention.get('aid')

            # 检查是否已处理
            if rpid in self.processed_rpids:
                logger.info(f"已处理过该评论: {rpid}")
                return False

            # 加载人设
            persona = self._load_persona()

            # 对方让你“看看我的视频/这个视频”时，先取视频资料再回复。
            video_context = f"视频: {video_title}"
            try:
                requested_video = await self.bili.resolve_requested_video(
                    content or '', mention.get('mid')
                )
            except Exception as exc:  # noqa: BLE001
                logger.debug(f"解析对方请求的视频失败: {exc}")
                requested_video = None
            if requested_video:
                video_context += (
                    "\n\n# 对方让你看的视频\n"
                    f"标题：{requested_video.get('title', '')}\n"
                    f"UP主：{requested_video.get('owner', '')}\n"
                    f"简介：{requested_video.get('desc', '')}\n"
                    f"链接：{requested_video.get('url', '')}\n"
                    f"字幕片段：{requested_video.get('subtitle') or '（无字幕）'}\n"
                )
                logger.info(
                    f"准备回应对方请求的视频: {requested_video.get('title')} "
                    f"({requested_video.get('bvid')})"
                )
                posted_video_comment = await self._comment_on_requested_video(
                    requested_video, mention, persona
                )
                if getattr(self.bili, 'is_posting_blocked', lambda: False)() is True:
                    return False
                if posted_video_comment:
                    video_context += (
                        "\n# 你已经在她的视频下评论过\n"
                        f"{posted_video_comment}\n"
                    )

            # 生成回复
            reply_text = await self.ai.generate_reply(
                original_comment=content,
                video_context=video_context,
                persona=persona,
                user_name=user or '',
                is_owner=bool(
                    user and user == self.config.get('bilibili.owner_name', '')
                ),
            )

            if not reply_text:
                logger.error("生成回复失败")
                return False

            logger.info(f"准备回复 @{user}: {reply_text}")

            # 发送回复
            success = await self.bili.post_comment(
                aid=aid,
                text=reply_text,
                root_rpid=mention.get('root_rpid') or rpid,
                parent_rpid=rpid
            )

            if success:
                # 记录到数据库
                self.db.add_comment_record(
                    bvid=mention.get('bvid', ''),
                    aid=aid,
                    content=reply_text,
                    comment_type='reply',
                    success=True,
                    rpid=getattr(self.bili, 'last_comment_rpid', None),
                    parent_rpid=rpid,
                    thread_root=mention.get('root_rpid') or rpid,
                    target_user=user or '',
                    parent_content=content or '',
                )
                self.processed_rpids.add(rpid)
                logger.info(f"✅ 回复成功: @{user}")
            else:
                logger.error(f"❌ 回复失败: @{user}")

            return success

        except Exception as e:
            logger.error(f"回复评论异常: {e}")
            return False

    async def check_and_reply(self) -> Dict[str, Any]:
        """检查新回复；自动回复开启时逐条回复，并返回检测到的回复列表。"""
        mentions = await self.check_mentions()
        replied = 0
        if self.config.get('interaction.auto_reply', True):
            for mention in mentions:
                if getattr(self.bili, 'is_posting_blocked', lambda: False)() is True:
                    logger.warning("评论发送冷却中，停止本轮回复")
                    break
                if await self.reply_to_mention(mention):
                    replied += 1
                await asyncio.sleep(2)
        return {'replied': replied, 'mentions': mentions}

    async def monitor_loop(self):
        """
        评论监听循环
        """
        interval = self.config.get('interaction.monitor_interval_minutes', 10)
        logger.info(f"启动评论监听，检查间隔: {interval}分钟")

        while True:
            try:
                # 检查@提醒
                mentions = await self.check_mentions()

                if mentions:
                    logger.info(f"发现 {len(mentions)} 条@提醒")

                    for mention in mentions:
                        await self.reply_to_mention(mention)
                        await asyncio.sleep(3)  # 避免频繁操作

                # 等待下一次检查
                await asyncio.sleep(interval * 60)

            except Exception as e:
                logger.error(f"监听循环异常: {e}")
                await asyncio.sleep(60)  # 出错后等待1分钟

    def _load_persona(self) -> str:
        """加载角色人设"""
        from pathlib import Path

        if not self.config.get('persona.enabled', True):
            return ""

        persona_file = self.config.get('persona.persona_file', 'data/persona.md')
        persona_path = Path(persona_file)

        if not persona_path.exists():
            name = self.config.get('persona.name', 'AI助手')
            return f"你是 {name}，一个友好的AI助手。"

        try:
            with open(persona_path, 'r', encoding='utf-8') as f:
                content = f.read()
            return content[:3000]
        except Exception as e:
            logger.warning(f"加载人设文件失败: {e}")
            return ""


# 使用示例
if __name__ == "__main__":
    async def test():
        from core.bilibili_api import BilibiliAPI
        from core.ai_client import AIClient
        from utils.database import Database
        from utils.config_manager import ConfigManager

        config = ConfigManager()
        db = Database()
        bili = BilibiliAPI()
        ai = AIClient(provider="openai", api_key="your-key")

        manager = CommentManager(bili, ai, db, config)

        # 检查@提醒
        mentions = await manager.check_mentions()
        print(f"发现 {len(mentions)} 条@提醒")

    asyncio.run(test())
