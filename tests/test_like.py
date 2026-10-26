import asyncio
import unittest
from unittest.mock import AsyncMock, Mock, patch

from core.video_analyzer import VideoAnalyzer


class LikeAfterCommentTests(unittest.TestCase):
    def _analyzer(self, enabled=True):
        values = {
            'interaction.auto_like_commented_video': enabled,
            'limits.max_likes_per_day': 5,
        }
        config = Mock()
        config.get = lambda key, default=None: values.get(key, default)

        analyzer = VideoAnalyzer.__new__(VideoAnalyzer)
        analyzer.config = config
        analyzer.bili = Mock()
        analyzer.bili.is_blocked = Mock(return_value=False)
        analyzer.bili.is_posting_blocked = Mock(return_value=False)
        analyzer.bili.like_video = AsyncMock(return_value=True)
        analyzer.db = Mock()
        analyzer.db.get_today_like_count = Mock(return_value=0)
        analyzer.db.has_liked_video = Mock(return_value=False)
        return analyzer

    def test_likes_video_after_comment_when_enabled(self):
        analyzer = self._analyzer()
        async def run():
            with patch('core.video_analyzer.asyncio.sleep', AsyncMock()):
                return await analyzer._like_commented_video(
                    {'bvid': 'BV1', 'aid': 1, 'title': '视频'}, {'score': 15}
                )

        self.assertTrue(asyncio.run(run()))
        analyzer.bili.like_video.assert_awaited_once_with(1)
        analyzer.db.add_like_record.assert_called_once_with('BV1', 1, True)

    def test_skips_when_disabled(self):
        analyzer = self._analyzer(enabled=False)
        result = asyncio.run(analyzer._like_commented_video(
            {'bvid': 'BV1', 'aid': 1}, {'score': 15}
        ))
        self.assertFalse(result)
        analyzer.bili.like_video.assert_not_called()

    def test_skips_when_daily_limit_reached(self):
        analyzer = self._analyzer()
        analyzer.db.get_today_like_count = Mock(return_value=5)
        result = asyncio.run(analyzer._like_commented_video(
            {'bvid': 'BV1', 'aid': 1}, {'score': 15}
        ))
        self.assertFalse(result)
        analyzer.bili.like_video.assert_not_called()


if __name__ == '__main__':
    unittest.main()
