import unittest

from core.bili_tool import BiliTool


class FakeConfig:
    def __init__(self, values=None):
        self.values = values or {}

    def get(self, key, default=None):
        return self.values.get(key, default)


class FakeBili:
    def __init__(self):
        self.likes = 0
        self.is_posting_blocked = lambda: False

    async def like_video(self, aid: int):
        self.likes += 1
        return True

    async def post_comment(self, aid: int, text: str):
        return True


class WriteLimitTests(unittest.IsolatedAsyncioTestCase):
    async def test_round_write_limit_blocks_extra_writes(self):
        bili = FakeBili()
        tool = BiliTool(bili, None, FakeConfig({'limits.max_writes_per_round': 2}))
        self.assertTrue(await tool.call('like_video', {'aid': 1}))
        self.assertTrue(await tool.call('like_video', {'aid': 2}))
        result = await tool.call('like_video', {'aid': 3})
        self.assertIn('上限', result['error'])
        self.assertEqual(bili.likes, 2)
        self.assertEqual(tool.writes, 2)

    async def test_reset_allows_next_round(self):
        bili = FakeBili()
        tool = BiliTool(bili, None, FakeConfig({'limits.max_writes_per_round': 1}))
        self.assertTrue(await tool.call('like_video', {'aid': 1}))
        self.assertIn('上限', (await tool.call('like_video', {'aid': 2}))['error'])
        tool.reset_writes()
        self.assertTrue(await tool.call('like_video', {'aid': 3}))
        self.assertEqual(bili.likes, 2)

    async def test_zero_means_unlimited(self):
        bili = FakeBili()
        tool = BiliTool(bili, None, FakeConfig({'limits.max_writes_per_round': 0}))
        for aid in range(5):
            self.assertTrue(await tool.call('like_video', {'aid': aid}))
        self.assertEqual(bili.likes, 5)


if __name__ == '__main__':
    unittest.main()
