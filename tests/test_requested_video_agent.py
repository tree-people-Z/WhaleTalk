import asyncio
import unittest
from unittest.mock import AsyncMock, Mock

from core.comment_manager import CommentManager


class RequestedVideoAgentTests(unittest.TestCase):
    def test_comments_under_requested_video(self):
        manager = CommentManager.__new__(CommentManager)
        manager.config = Mock()
        manager.config.get = lambda key, default=None: {
            'limits.max_comments_per_day': 60,
        }.get(key, default)
        manager.bili = Mock()
        manager.bili.get_video_info = AsyncMock(return_value={
            'aid': 99, 'bvid': 'BV1test', 'title': '她让我看的视频',
        })
        manager.bili.post_comment = AsyncMock(return_value=True)
        manager.bili.last_comment_rpid = 123
        manager.bili.is_posting_blocked = Mock(return_value=False)
        manager.db = Mock()
        manager.db.get_today_comment_count = Mock(return_value=0)
        manager.db.has_commented_video = Mock(return_value=False)
        manager.db.add_comment_record = Mock()
        manager.db.add_memory_event = Mock()

        ok = asyncio.run(manager._send_agent_video_comment(
            {'user': 'viewer', 'mid': 7, 'content': '看看我的视频'},
            'BV1test',
            '这个视频的节奏我喜欢',
        ))
        self.assertTrue(ok)
        manager.bili.post_comment.assert_awaited_once_with(
            aid=99, text='这个视频的节奏我喜欢'
        )
        manager.db.add_comment_record.assert_called_once()

    def test_skips_when_already_commented(self):
        manager = CommentManager.__new__(CommentManager)
        manager.config = Mock()
        manager.config.get = lambda key, default=None: default
        manager.bili = Mock()
        manager.bili.is_posting_blocked = Mock(return_value=False)
        manager.db = Mock()
        manager.db.get_today_comment_count = Mock(return_value=0)
        manager.db.has_commented_video = Mock(return_value=True)
        manager.db.get_today_comment_count = Mock(return_value=0)

        ok = asyncio.run(manager._send_agent_video_comment(
            {}, 'BV1test', '评论'
        ))
        self.assertFalse(ok)


if __name__ == '__main__':
    unittest.main()
