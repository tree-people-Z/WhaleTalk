import asyncio
import unittest
from unittest.mock import AsyncMock, Mock, patch

from core.video_analyzer import VideoAnalyzer


class SearchInterleaveTests(unittest.TestCase):
    def test_round_robin_interleaves_keywords(self):
        config = Mock()
        config.get = lambda key, default=None: {
            'search.keywords': ['alpha', 'beta', 'gamma'],
            'search.max_results_per_keyword': 2,
            'search.order': 'totalrank',
        }.get(key, default)
        analyzer = VideoAnalyzer.__new__(VideoAnalyzer)
        analyzer.config = config

        async def fake_search(keyword, page=1, order='totalrank'):
            return [
                {'bvid': f'{keyword}-1', 'title': keyword},
                {'bvid': f'{keyword}-2', 'title': keyword},
            ]

        analyzer.bili = Mock()
        analyzer.bili.search_videos = AsyncMock(side_effect=fake_search)

        async def run():
            with patch('core.video_analyzer.asyncio.sleep', AsyncMock()):
                return await analyzer._search_videos()

        videos = asyncio.run(run())
        self.assertEqual(len(videos), 6)
        self.assertEqual(len({video['bvid'] for video in videos}), 6)
        first_round = videos[:3]
        self.assertEqual(
            len({video['bvid'].split('-')[0] for video in first_round}), 3
        )
        self.assertTrue(all(video['bvid'].endswith('-2') for video in videos[3:]))


if __name__ == '__main__':
    unittest.main()
