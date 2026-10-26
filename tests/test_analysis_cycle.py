import asyncio
import threading
import unittest
from unittest.mock import AsyncMock, Mock, patch

from core.video_analyzer import VideoAnalyzer


class AnalysisCycleTests(unittest.TestCase):
    def _analyzer(self):
        analyzer = VideoAnalyzer.__new__(VideoAnalyzer)
        analyzer._stop_requested = threading.Event()
        analyzer._search_page = 1

        values = {
            'interaction.auto_comment': True,
            'interaction.comment_monitor': False,
            'limits.max_videos_per_run': 2,
            'limits.min_score_to_comment': 10,
            'limits.skip_analyzed_within_hours': 2,
            'limits.same_video_cooldown_days': 7,
            'limits.max_comments_per_day': 999,
        }
        config = Mock()
        config.get = lambda key, default=None: values.get(key, default)
        analyzer.config = config

        analyzer.bili = Mock()
        analyzer.bili.is_blocked = Mock(return_value=False)
        analyzer.bili.is_posting_blocked = Mock(return_value=False)

        quota = Mock()
        quota.comments_sent = 0
        analyzer.db = Mock()
        analyzer.db.get_today_quota = Mock(return_value=quota)
        analyzer.db.is_video_analyzed_recently = Mock(return_value=False)
        analyzer.db.check_video_commented_recently = Mock(return_value=False)

        analyzer._analyze_video = AsyncMock(return_value={
            'score': 15,
            'worthy': True,
            'confidence': 'high',
            'summary': '内容',
            'owner_directive': False,
        })
        analyzer._post_comment_for_video = AsyncMock(return_value=True)
        return analyzer

    def test_analyzes_up_to_limit_and_comments_only_when_eligible(self):
        analyzer = self._analyzer()
        analyzer._search_videos = AsyncMock(return_value=[
            {'bvid': f'BV{index}', 'aid': index, 'title': f'视频{index}'}
            for index in range(1, 8)
        ])

        async def run():
            with patch('core.video_analyzer.asyncio.sleep', AsyncMock()):
                return await analyzer.run_analysis_cycle()

        result = asyncio.run(run())
        self.assertEqual(result['videos_analyzed'], 2)
        self.assertEqual(result['comments_sent'], 2)
        self.assertEqual(analyzer._search_videos.await_count, 1)
        self.assertEqual(analyzer._post_comment_for_video.await_count, 2)

    def test_does_not_force_comments_when_candidates_are_skipped(self):
        analyzer = self._analyzer()
        analyzer._search_videos = AsyncMock(return_value=[
            {'bvid': 'BV1', 'aid': 1, 'title': '视频1'},
            {'bvid': 'BV2', 'aid': 2, 'title': '视频2'},
        ])
        analyzer.db.is_video_analyzed_recently = Mock(return_value=True)

        async def run():
            with patch('core.video_analyzer.asyncio.sleep', AsyncMock()):
                return await analyzer.run_analysis_cycle()

        result = asyncio.run(run())
        self.assertEqual(result['videos_analyzed'], 0)
        self.assertEqual(result['comments_sent'], 0)
        self.assertEqual(analyzer._search_videos.await_count, 1)
        analyzer._post_comment_for_video.assert_not_called()


if __name__ == '__main__':
    unittest.main()
