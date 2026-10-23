"""
评论管理模块
负责监听评论区的@提醒并回复
"""

import asyncio
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

            # 1. 检查我发送的评论是否有回复
            my_comments = self.db.get_recent_comments(limit=20)

            for my_comment in my_comments:
                if not my_comment.get('aid'):
                    continue

                aid = my_comment['aid']
                my_rpid = my_comment.get('rpid')

                if not my_rpid:
                    continue

                # 获取该视频的评论
                try:
                    comments = await self.bili.get_comments(
                        aid, count=50, include_replies=True, root_rpids={my_rpid}
                    )

                    for comment in comments:
                        # 检查是否是回复我的评论
                        root = comment.get('root', 0)
                        parent = comment.get('parent', 0)
                        rpid = comment.get('rpid')

                        # 跳过自己发出的评论（含自动回复产生的楼层），避免自问自答。
                        if rpid in self.processed_rpids:
                            continue
                        if self_uid is not None and comment.get('mid') == self_uid:
                            logger.debug(f"跳过自己发出的评论: {rpid}")
                            continue
                        if self_name and comment.get('user') == self_name:
                            logger.debug(f"跳过自己账号的评论: {rpid}")
                            continue

                        # 如果root或parent是我的评论ID，说明是回复我的
                        if root == my_rpid or parent == my_rpid:
                            thread_root = root or my_rpid
                            mentions.append({
                                'rpid': rpid,
                                'root_rpid': thread_root,
                                'user': comment.get('user'),
                                'content': comment.get('content'),
                                'aid': aid,
                                'bvid': my_comment.get('bvid'),
                                'type': 'reply',
                                'video_title': my_comment.get('video_title', '')
                            })
                            logger.info(f"发现回复: {comment.get('user')} -> {comment.get('content')[:30]}")

                except Exception as e:
                    logger.debug(f"检查评论回复失败 aid={aid}: {e}")
                    continue

                await asyncio.sleep(0.5)  # 避免请求过快

            logger.info(f"检查完成，发现 {len(mentions)} 条新回复")
            return mentions

        except Exception as e:
            logger.error(f"检查@提醒失败: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return []

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

            # 生成回复
            reply_text = await self.ai.generate_reply(
                original_comment=content,
                video_context=f"视频: {video_title}",
                persona=persona
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
                    parent_rpid=rpid
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
