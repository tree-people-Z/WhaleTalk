import asyncio
import threading
import unittest
from unittest.mock import AsyncMock, Mock, patch

from core.video_analyzer import VideoAnalyzer


class AnalysisCycleTargetTests(unittest.TestCase):
    def test_continues_until_comment_target_is_met(self):
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

        videos = [
            {'bvid': f'BV{index}', 'aid': index, 'title': f'视频{index}'}
            for index in range(1, 8)
        ]
        analyzer._search_videos = AsyncMock(return_value=videos)
        analyzer._analyze_video = AsyncMock(return_value={
            'score': 15,
            'worthy': True,
            'confidence': 'high',
            'summary': '内容',
            'owner_directive': False,
            'reply_invitations': [],
        })
        analyzer._reply_to_invitations = AsyncMock(return_value=0)
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


if __name__ == '__main__':
    unittest.main()
