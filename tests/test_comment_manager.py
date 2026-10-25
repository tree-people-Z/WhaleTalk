import asyncio
import unittest
from unittest.mock import AsyncMock, Mock

from core.comment_manager import CommentManager


class CommentManagerFilteringTests(unittest.TestCase):
    def test_ignores_own_comments_and_own_reply_rpids(self):
        async def run():
            config = Mock()
            config.get = lambda key, default=None: {
                'interaction.comment_monitor': True,
            }.get(key, default)

            bili = Mock()
            bili.get_self_info = AsyncMock(return_value={'uid': 42, 'name': 'Deep_Claude'})
            bili.get_comments = AsyncMock(return_value=[
                # our own reply under our comment thread
                {'rpid': 201, 'mid': 42, 'user': 'Deep_Claude', 'content': '自问自答',
                 'root': 100, 'parent': 100},
                # a rpid we already recorded as our own comment
                {'rpid': 111, 'mid': 7, 'user': 'someone', 'content': '旧回复',
                 'root': 100, 'parent': 100},
                # a real viewer replying to us
                {'rpid': 202, 'mid': 7, 'user': 'viewer', 'content': '真的回复',
                 'root': 100, 'parent': 100},
                # another viewer replying to 202, not to us
                {'rpid': 203, 'mid': 8, 'user': 'other', 'content': '回复楼上',
                 'root': 100, 'parent': 202},
            ])

            db = Mock()
            db.get_replied_comment_ids = Mock(return_value=set())
            db.get_own_comment_rpids = Mock(return_value={111})
            db.get_recent_comments = Mock(return_value=[
                {'aid': 1, 'bvid': 'BV1', 'rpid': 100, 'video_title': '测试视频'}
            ])

            manager = CommentManager(bili, Mock(), db, config)
            mentions = await manager.check_mentions()
            return mentions

        mentions = asyncio.run(run())
        self.assertEqual([m['rpid'] for m in mentions], [202])

    def test_check_mentions_includes_own_video_comments(self):
        async def run():
            config = Mock()
            config.get = lambda key, default=None: {
                'interaction.comment_monitor': True,
                'interaction.reply_own_video_comments': True,
                'interaction.own_video_count': 1,
                'interaction.max_own_video_replies_per_check': 5,
            }.get(key, default)

            bili = Mock()
            bili.get_self_info = AsyncMock(
                return_value={'uid': 42, 'name': 'Deep_Claude'}
            )
            bili.get_own_videos = AsyncMock(return_value=[
                {'aid': 1, 'bvid': 'BV1', 'title': '我的视频'}
            ])
            bili.get_comments = AsyncMock(return_value=[
                {'rpid': 900, 'mid': 7, 'user': 'viewer',
                 'content': '沙发', 'root': 0, 'parent': 0},
                {'rpid': 901, 'mid': 42, 'user': 'Deep_Claude',
                 'content': '自己', 'root': 0, 'parent': 0},
                {'rpid': 902, 'mid': 8, 'user': 'other',
                 'content': '@someone 你看这个', 'root': 0, 'parent': 0},
            ])
            db = Mock()
            db.get_replied_comment_ids = Mock(return_value=set())
            db.get_own_comment_rpids = Mock(return_value={901})
            db.get_recent_comments = Mock(return_value=[])

            manager = CommentManager(bili, Mock(), db, config)
            return await manager.check_mentions()

        mentions = asyncio.run(run())
        self.assertEqual([m['rpid'] for m in mentions], [900])
        self.assertEqual(mentions[0]['type'], 'own_video')

    def test_check_and_reply_returns_mentions_when_auto_reply_is_off(self):
        async def run():
            config = Mock()
            config.get = lambda key, default=None: {
                'interaction.comment_monitor': True,
                'interaction.auto_reply': False,
            }.get(key, default)

            manager = CommentManager(Mock(), Mock(), Mock(), config)
            manager.check_mentions = AsyncMock(return_value=[
                {'rpid': 7, 'user': 'viewer', 'content': '新回复'}
            ])
            manager.reply_to_mention = AsyncMock()
            result = await manager.check_and_reply()
            return result, manager

        result, manager = asyncio.run(run())
        self.assertEqual(result['replied'], 0)
        self.assertEqual(result['mentions'][0]['rpid'], 7)
        manager.reply_to_mention.assert_not_called()


if __name__ == '__main__':
    unittest.main()
