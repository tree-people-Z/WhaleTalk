import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from bilibili_api.search import OrderVideo

from core.bilibili_api import BilibiliAPI


class SearchOrderTests(unittest.TestCase):
    def test_totalrank_config_uses_comprehensive_search_order(self):
        async def run():
            api = BilibiliAPI.__new__(BilibiliAPI)
            api.blocked_until = None
            with patch('core.bilibili_api.search.search_by_type', new=AsyncMock(return_value={
                'result': []
            })) as search:
                await api.search_videos('AI', order='totalrank')
            self.assertIs(search.await_args.kwargs['order_type'], OrderVideo.TOTALRANK)

        asyncio.run(run())

    def test_search_filters_results_without_valid_video_ids(self):
        async def run():
            api = BilibiliAPI.__new__(BilibiliAPI)
            api.blocked_until = None
            payload = {'result': [
                {'bvid': '', 'aid': 1, 'title': 'missing'},
                {'bvid': 'not-a-bvid', 'aid': 2, 'title': 'invalid'},
                {'bvid': 'BV1can66KEpA', 'aid': 3, 'title': 'valid'},
                {'bvid': 'BV1can66KEty', 'title': 'missing aid'},
            ]}
            with patch('core.bilibili_api.search.search_by_type', new=AsyncMock(return_value=payload)):
                rows = await api.search_videos('AI', order='totalrank')
            self.assertEqual([row['bvid'] for row in rows], ['BV1can66KEpA'])

        asyncio.run(run())


if __name__ == '__main__':
    unittest.main()
