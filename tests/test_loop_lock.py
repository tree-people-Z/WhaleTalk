import asyncio
import unittest

from core.bilibili_api import BilibiliAPI


class LoopBoundLockTests(unittest.TestCase):
    def test_comment_pacing_lock_can_be_reused_across_event_loops(self):
        api = BilibiliAPI.__new__(BilibiliAPI)
        api._comment_min_interval = -100
        api._last_comment_request_at = 0.0
        asyncio.run(api._pace_comment_request())
        # The old code kept the first loop's asyncio.Lock and failed here.
        asyncio.run(api._pace_comment_request())


if __name__ == '__main__':
    unittest.main()
