"""批量获取视频信息测试"""
import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from bilibili_api.exceptions import ResponseCodeException

from core.bilibili_api import BilibiliAPI


class BatchFakeBili(BilibiliAPI):
    """不初始化登录，只测批量调度逻辑"""

    def __init__(self):
        pass

    async def get_video_info(self, bvid):
        if bvid == 'BAD':
            raise RuntimeError('boom')
        return {'bvid': bvid, 'title': bvid}


class BatchVideoInfoTests(unittest.TestCase):
    def test_dedupe_and_keep_order(self):
        api = BatchFakeBili()
        result = asyncio.run(
            api.get_videos_info_batch(['BV1', 'BV2', 'BV1', ' BAD ', '', 'BV3'])
        )
        self.assertEqual(set(result), {'BV1', 'BV2', 'BV3', 'BAD'})
        self.assertIsNone(result['BAD'])
        self.assertEqual(result['BV1']['title'], 'BV1')

    def test_empty_input(self):
        api = BatchFakeBili()
        self.assertEqual(asyncio.run(api.get_videos_info_batch([])), {})
        self.assertEqual(asyncio.run(api.get_videos_info_batch(None)), {})

    def test_bad_concurrency_falls_back(self):
        api = BatchFakeBili()
        result = asyncio.run(
            api.get_videos_info_batch(['BV1', 'BV2'], max_concurrent='oops')
        )
        self.assertEqual(set(result), {'BV1', 'BV2'})


class VideoInfoRetryTests(unittest.TestCase):
    def _api(self):
        api = BilibiliAPI.__new__(BilibiliAPI)
        api.credential = None
        return api

    def test_missing_video_is_not_retried(self):
        calls = []

        class StubVideo:
            def __init__(self, **kwargs):
                calls.append(kwargs.get('bvid'))

            async def get_info(self):
                raise ResponseCodeException(-404, '啥都木有', {})

        with patch('core.bilibili_api.video.Video', StubVideo), \
                patch('core.bilibili_api.asyncio.sleep', AsyncMock()):
            result = asyncio.run(self._api().get_video_info('BV1notexist'))
        self.assertIsNone(result)
        self.assertEqual(len(calls), 1)

    def test_other_errors_are_retried(self):
        calls = []

        class StubVideo:
            def __init__(self, **kwargs):
                calls.append(kwargs.get('bvid'))

            async def get_info(self):
                raise RuntimeError('network down')

        with patch('core.bilibili_api.video.Video', StubVideo), \
                patch('core.bilibili_api.asyncio.sleep', AsyncMock()):
            result = asyncio.run(self._api().get_video_info('BV1network'))
        self.assertIsNone(result)
        self.assertEqual(len(calls), 2)


if __name__ == '__main__':
    unittest.main()
