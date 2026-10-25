import asyncio
import unittest
from unittest.mock import AsyncMock, Mock

from core.bilibili_api import BilibiliAPI
from core.comment_manager import CommentManager


class RequestedVideoTests(unittest.TestCase):
    def _api(self):
        api = BilibiliAPI.__new__(BilibiliAPI)
        api.credential = None
        api.get_video_info = AsyncMock(return_value={
            'bvid': 'BV1xx411c7mD',
            'title': '我的视频',
            'desc': '简介',
            'owner': 'viewer',
            'owner_mid': 42,
            'duration': 60,
        })
        api.get_subtitle = AsyncMock(return_value='字幕内容')
        api.get_user_videos = AsyncMock(return_value=[
            {'bvid': 'BV1xx411c7mD', 'aid': 1, 'title': '我的视频'}
        ])
        return api

    def test_resolves_explicit_bvid(self):
        api = self._api()
        result = asyncio.run(api.resolve_requested_video(
            '帮我看看 BV1xx411c7mD 这个视频', 7
        ))
        self.assertEqual(result['bvid'], 'BV1xx411c7mD')
        self.assertEqual(result['requested_by'], 'explicit_link')
        self.assertEqual(result['subtitle'], '字幕内容')
        api.get_user_videos.assert_not_called()

    def test_resolves_commenters_own_upload(self):
        api = self._api()
        result = asyncio.run(api.resolve_requested_video(
            '看看我的视频嘛', 42
        ))
        self.assertEqual(result['bvid'], 'BV1xx411c7mD')
        self.assertEqual(result['requested_by'], 'commenter_upload')
        api.get_user_videos.assert_awaited_once_with(42, limit=3)

    def test_returns_none_without_video_request(self):
        api = self._api()
        self.assertIsNone(asyncio.run(api.resolve_requested_video('写得好', 42)))

    def test_posts_comment_under_requested_video(self):
        manager = CommentManager.__new__(CommentManager)
        values = {
            'interaction.comment_requested_video': True,
            'limits.max_comments_per_day': 96,
        }
        manager.config = Mock()
        manager.config.get = lambda key, default=None: values.get(key, default)
        manager.bili = Mock()
        manager.bili.get_self_info = AsyncMock(return_value={'uid': 42})
        manager.bili.is_blocked = Mock(return_value=False)
        manager.bili.is_posting_blocked = Mock(return_value=False)
        manager.bili.post_comment = AsyncMock(return_value=True)
        manager.bili.last_comment_rpid = 123
        manager.ai = Mock()
        manager.ai.generate_comment = AsyncMock(return_value='这个视频的节奏我喜欢')
        manager.db = Mock()
        manager.db.has_commented_video = Mock(return_value=False)
        manager.db.get_today_comment_count = Mock(return_value=0)
        manager.db.add_comment_record = Mock()

        requested = {
            'aid': 99,
            'bvid': 'BV1xx411c7mD',
            'owner_mid': 7,
            'title': '她的视频',
            'desc': '简介',
            'subtitle': '字幕',
        }
        text = asyncio.run(manager._comment_on_requested_video(
            requested, {'aid': 1}, '人设'
        ))
        self.assertEqual(text, '这个视频的节奏我喜欢')
        manager.bili.post_comment.assert_awaited_once_with(
            aid=99, text='这个视频的节奏我喜欢'
        )
        manager.db.add_comment_record.assert_called_once()


if __name__ == '__main__':
    unittest.main()
