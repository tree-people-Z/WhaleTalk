import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from core.bilibili_api import BilibiliAPI


class CommentThreadTests(unittest.TestCase):
    def test_thread_filters_unrelated_replies_sorts_and_dedupes(self):
        async def run():
            api = BilibiliAPI.__new__(BilibiliAPI)
            api.credential = object()
            raw = [
                {'rpid': 10, 'root': 100, 'parent': 100, 'user': 'u1',
                 'content': 'second', 'ctime': 200},
                {'rpid': 11, 'root': 999, 'parent': 999, 'user': 'u2',
                 'content': 'other thread', 'ctime': 50},
                {'rpid': 12, 'root': 100, 'parent': 10, 'user': 'u3',
                 'content': 'first', 'ctime': 100},
                {'rpid': 10, 'root': 100, 'parent': 100, 'user': 'u1',
                 'content': 'duplicate', 'ctime': 200},
            ]
            with patch.object(api, 'get_comments', new=AsyncMock(return_value=raw)):
                return await api.get_comment_thread(1, 100)

        thread = asyncio.run(run())
        self.assertEqual([comment['rpid'] for comment in thread], [12, 10])
        self.assertEqual(thread[1]['content'], 'second')


if __name__ == '__main__':
    unittest.main()
