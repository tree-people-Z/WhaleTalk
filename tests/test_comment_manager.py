import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

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
                {'rpid': 903, 'mid': 9, 'user': 'viewer2',
                 'content': '@Deep_Claude 这鱼成偶像了吧', 'root': 0, 'parent': 0},
            ])
            db = Mock()
            db.get_replied_comment_ids = Mock(return_value=set())
            db.get_own_comment_rpids = Mock(return_value={901})
            db.get_recent_comments = Mock(return_value=[])

            manager = CommentManager(bili, Mock(), db, config)
            return await manager.check_mentions()

        from core.comment_events import CommentEventCollector
        with tempfile.TemporaryDirectory() as directory:
            with patch.object(
                CommentEventCollector, 'CURSOR_FILE',
                Path(directory) / 'cursor.json',
            ):
                mentions = asyncio.run(run())
        self.assertEqual([m['rpid'] for m in mentions], [900, 902, 903])
        by_rpid = {m['rpid']: m for m in mentions}
        self.assertTrue(by_rpid[902]['addressed_to_other'])
        self.assertEqual(by_rpid[902]['mentioned_users'], ['someone'])
        self.assertFalse(by_rpid[903]['addressed_to_other'])
        self.assertEqual(by_rpid[903]['mentioned_users'], ['Deep_Claude'])
        self.assertEqual(by_rpid[900]['type'], 'own_video')

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


class MarkAtSeenRoutingTests(unittest.TestCase):
    def test_at_mention_marks_seen_on_event_collector(self):
        from unittest.mock import patch
        from core.comment_manager import CommentManager

        async def run():
            config = Mock()
            config.get = lambda key, default=None: {
                'interaction.comment_monitor': True,
                'interaction.auto_reply': True,
                'limits.max_comments_per_day': 60,
            }.get(key, default)

            manager = CommentManager(Mock(), Mock(), Mock(), config)
            manager.check_mentions = AsyncMock(return_value=[])
            manager.check_at_messages = AsyncMock(return_value=[
                {'rpid': 99, 'type': 'at', 'user': 'viewer', 'content': '@我'},
            ])
            manager.reply_to_mention = AsyncMock(return_value=True)
            manager.check_private_messages = AsyncMock(return_value=0)
            manager.events._mark_at_seen = Mock()
            with patch('core.comment_manager.asyncio.sleep', AsyncMock()):
                result = await manager.check_and_reply()
            return result, manager

        result, manager = asyncio.run(run())
        manager.events._mark_at_seen.assert_called_once_with(99)
        self.assertEqual(result['replied'], 1)


class _CursorConfig:
    def __init__(self, values=None):
        self.values = values or {}

    def get(self, key, default=None):
        return self.values.get(key, default)


class CommentCheckEfficiencyTests(unittest.TestCase):
    def _collector(self, bili, db, config):
        from core.comment_events import CommentEventCollector
        return CommentEventCollector(bili, db, config, set())

    def test_my_comments_on_same_video_are_fetched_once(self):
        async def run():
            bili = Mock()
            bili.get_self_info = AsyncMock(return_value={'uid': 42, 'name': 'me'})
            bili.get_comments = AsyncMock(return_value=[])
            db = Mock()
            db.get_replied_comment_ids = Mock(return_value=set())
            db.get_own_comment_rpids = Mock(return_value=set())
            db.get_recent_comments = Mock(return_value=[
                {'aid': 1, 'rpid': 100, 'thread_root': 100, 'bvid': 'BV1'},
                {'aid': 1, 'rpid': 101, 'thread_root': 100, 'bvid': 'BV1'},
                {'aid': 2, 'rpid': 200, 'thread_root': 200, 'bvid': 'BV2'},
            ])
            collector = self._collector(
                bili, db, _CursorConfig({'interaction.comment_monitor': True,
                                         'interaction.reply_scope': 'owner'})
            )
            await collector.check_mentions()
            return bili.get_comments

        get_comments = asyncio.run(run())
        self.assertEqual(get_comments.await_count, 2)
        root_sets = [
            call.kwargs['root_rpids'] for call in get_comments.await_args_list
        ]
        self.assertEqual(root_sets, [{100}, {200}])

    def test_own_video_cursor_skips_seen_comments(self):
        from core.comment_events import CommentEventCollector

        async def run(cursor_path):
            bili = Mock()
            bili.get_own_videos = AsyncMock(return_value=[
                {'aid': 1, 'bvid': 'BV1', 'title': '我的视频'}
            ])
            bili.get_comments = AsyncMock(return_value=[
                {'rpid': 900, 'mid': 7, 'user': 'viewer', 'content': '旧评论',
                 'root': 0, 'parent': 0},
                {'rpid': 950, 'mid': 8, 'user': 'viewer2', 'content': '新评论',
                 'root': 0, 'parent': 0},
            ])
            db = Mock()
            db.get_replied_comment_ids = Mock(return_value=set())
            db.get_own_comment_rpids = Mock(return_value=set())
            db.get_recent_comments = Mock(return_value=[])
            collector = self._collector(
                bili, db, _CursorConfig({
                    'interaction.comment_monitor': True,
                    'interaction.reply_scope': 'all',
                    'interaction.own_video_count': 1,
                    'interaction.max_new_comments_per_check': 10,
                })
            )
            with patch.object(CommentEventCollector, 'CURSOR_FILE', cursor_path):
                first = await collector.check_mentions()
                second = await collector.check_mentions()
            return first, second, cursor_path.read_text(encoding='utf-8').strip()

        with tempfile.TemporaryDirectory() as directory:
            first, second, saved = asyncio.run(run(Path(directory) / 'cursor.json'))
        self.assertEqual([m['rpid'] for m in first], [900, 950])
        self.assertEqual(second, [])
        self.assertEqual(saved, '{"1": 950}')

    def test_at_messages_respect_configured_limit(self):
        async def run():
            bili = Mock()
            bili.get_at_messages = AsyncMock(return_value=[
                {'rpid': 1000 + i, 'user': 'u', 'content': f'@{i}'} for i in range(40)
            ])
            collector = self._collector(
                bili, Mock(), _CursorConfig({
                    'interaction.comment_monitor': True,
                    'interaction.max_new_comments_per_check': 12,
                })
            )
            return await collector.check_at_messages()

        self.assertEqual(len(asyncio.run(run())), 12)
