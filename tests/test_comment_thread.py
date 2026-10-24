import asyncio
import unittest
from unittest.mock import AsyncMock, Mock, patch

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
            with patch.object(api, 'get_comments', new=AsyncMock(return_value=raw)), \
                    patch.object(
                        api, '_load_all_subcomments',
                        new=AsyncMock(return_value=[])
                    ):
                return await api.get_comment_thread(1, 100)

        thread = asyncio.run(run())
        self.assertEqual([comment['rpid'] for comment in thread], [12, 10])
        self.assertEqual(thread[1]['content'], 'second')

    def test_paginates_all_subcomment_pages(self):
        api = BilibiliAPI.__new__(BilibiliAPI)
        api.credential = object()
        pages = [
            {
                'replies': [{'rpid': 1}, {'rpid': 2}],
                'page': {'count': 3},
            },
            {
                'replies': [{'rpid': 3}],
                'page': {'count': 3},
            },
        ]

        async def fake_get_sub(**kwargs):
            index = kwargs.get('page_index', 1)
            return pages[index - 1] if index <= len(pages) else {'replies': []}

        fake_comment = Mock()
        fake_comment.get_sub_comments = AsyncMock(side_effect=fake_get_sub)

        async def run():
            with patch('core.bilibili_api.comment.Comment',
                       return_value=fake_comment), \
                    patch('core.bilibili_api.asyncio.sleep', AsyncMock()):
                return await api._load_all_subcomments(1, 100)

        entries = asyncio.run(run())
        self.assertEqual([entry['rpid'] for entry in entries], [1, 2, 3])
        self.assertEqual(fake_comment.get_sub_comments.await_count, 2)


if __name__ == '__main__':
    unittest.main()
