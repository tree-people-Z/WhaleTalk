import asyncio
import threading
import unittest
from unittest.mock import AsyncMock, Mock, patch

from core.video_analyzer import VideoAnalyzer


class AnalysisCycleTargetTests(unittest.TestCase):
    def _analyzer(self):
        analyzer = VideoAnalyzer.__new__(VideoAnalyzer)
        analyzer._stop_requested = threading.Event()
        analyzer._greetings_sent_this_run = 0
        analyzer._interactions_sent_this_run = 0
        analyzer._search_page = 1
        values = {
            'interaction.auto_comment': True,
            'interaction.comment_monitor': False,
            'limits.max_videos_per_run': 2,
            'limits.min_score_to_comment': 10,
            'limits.skip_analyzed_within_hours': 2,
            'limits.same_video_cooldown_days': 7,
            'limits.max_comments_per_day': 999,
            'limits.max_search_rounds_per_run': 3,
        }
        config = Mock()
        config.get = lambda key, default=None: values.get(key, default)
        analyzer.config = config
        analyzer.bili = Mock()
        analyzer.bili.is_blocked = Mock(return_value=False)
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
            'reply_invitations': [],
        })
        analyzer._reply_to_invitations = AsyncMock(return_value=0)
        return analyzer

    def test_continues_until_comment_target_is_met(self):
        analyzer = self._analyzer()
        videos = [
            {'bvid': f'BV{index}', 'aid': index, 'title': f'视频{index}'}
            for index in range(1, 8)
        ]
        analyzer._search_videos = AsyncMock(return_value=videos)
        # First candidate fails, the following two comments succeed.
        analyzer._post_comment_for_video = AsyncMock(
            side_effect=[False, True, True]
        )

        async def run():
            with patch('core.video_analyzer.asyncio.sleep', AsyncMock()):
                return await analyzer.run_analysis_cycle()

        result = asyncio.run(run())
        self.assertEqual(result['comments_sent'], 2)
        self.assertEqual(result['videos_analyzed'], 3)
        self.assertEqual(analyzer._post_comment_for_video.await_count, 3)

    def test_searches_next_page_when_candidates_are_exhausted(self):
        analyzer = self._analyzer()
        first_page = [
            {'bvid': 'BV1', 'aid': 1, 'title': '已分析1'},
            {'bvid': 'BV2', 'aid': 2, 'title': '已分析2'},
        ]
        second_page = [
            {'bvid': 'BV3', 'aid': 3, 'title': '新视频3'},
            {'bvid': 'BV4', 'aid': 4, 'title': '新视频4'},
        ]
        analyzer._search_videos = AsyncMock(
            side_effect=[first_page, second_page]
        )
        analyzer.db.is_video_analyzed_recently = Mock(
            side_effect=lambda bvid, hours: bvid in {'BV1', 'BV2'}
        )
        analyzer._post_comment_for_video = AsyncMock(return_value=True)

        async def run():
            with patch('core.video_analyzer.asyncio.sleep', AsyncMock()):
                return await analyzer.run_analysis_cycle()

        result = asyncio.run(run())
        self.assertEqual(result['comments_sent'], 2)
        self.assertEqual(analyzer._search_videos.await_count, 2)
        self.assertEqual(result['videos_analyzed'], 2)


if __name__ == '__main__':
    unittest.main()
