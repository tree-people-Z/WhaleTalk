"""
自动回复功能增强
包括：@提醒、评论回复、私信回复
"""

from core.comment_manager import CommentManager
import asyncio
from loguru import logger


class AutoReplyManager:
    """自动回复管理器"""

    def __init__(self, comment_manager: CommentManager, bili_api, ai_client):
        self.comment_manager = comment_manager
        self.bili = bili_api
        self.ai = ai_client
        self.processed_messages = set()

    async def check_and_reply_all(self):
        """检查并回复所有类型的消息"""

        # 1. 检查评论回复
        logger.info("🔍 检查评论回复...")
        mentions = await self.comment_manager.check_mentions()

        for mention in mentions:
            try:
                await self.comment_manager.reply_to_mention(mention)
                await asyncio.sleep(3)  # 避免频繁回复
            except Exception as e:
                logger.error(f"回复评论失败: {e}")

        # 2. 检查私信
        logger.info("🔍 检查私信...")
        await self.check_and_reply_dm()

    async def check_and_reply_dm(self):
        """检查并回复私信"""
        try:
            # 获取未读私信
            # 注意：需要B站API支持
            # 这里使用bilibili_api的消息相关功能

            from bilibili_api import user

            # 获取私信列表
            # sessions = await user.get_sessions(credential=self.bili.credential)

            logger.info("私信功能开发中...")
            # TODO: 实现私信获取和回复

            # 示例逻辑：
            # for session in sessions:
            #     messages = await get_messages(session_id)
            #     for msg in messages:
            #         if msg['id'] not in self.processed_messages:
            #             reply = await self.ai.generate_reply(...)
            #             await send_message(session_id, reply)
            #             self.processed_messages.add(msg['id'])

        except Exception as e:
            logger.error(f"检查私信失败: {e}")


# 使用示例
async def test_auto_reply():
    """测试自动回复"""
    from core.bilibili_api import BilibiliAPI
    from core.ai_client import AIClient
    from utils.database import Database
    from utils.config_manager import ConfigManager

    config = ConfigManager()
    db = Database()
    bili = BilibiliAPI()

    ai = AIClient(
        provider=config.get('ai.provider'),
        api_key=config.get('ai.api_key'),
        model=config.get('ai.model'),
        base_url=config.get('ai.base_url')
    )

    comment_mgr = CommentManager(bili, ai, db, config)
    auto_reply = AutoReplyManager(comment_mgr, bili, ai)

    # 检查并回复
    await auto_reply.check_and_reply_all()


if __name__ == "__main__":
    asyncio.run(test_auto_reply())
