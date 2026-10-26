import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from bilibili_api import comment

from core.bilibili_api import BilibiliAPI


class BilibiliCommentTests(unittest.TestCase):
    def test_fetches_subreplies_by_known_root_even_if_root_not_on_first_page(self):
        async def run():
            api = BilibiliAPI.__new__(BilibiliAPI)
            api.credential = object()
            root_id = 123
            child = {
                'rpid': 456,
                'root': root_id,
                'parent': root_id,
                'member': {'uname': 'viewer'},
                'content': {'message': 'reply'},
                'like': 0,
                'ctime': 1,
            }
            with patch('core.bilibili_comment.comment.get_comments', new=AsyncMock(return_value={
                'replies': [{'rpid': 999, 'member': {}, 'content': {'message': 'top'}}]
            })) as get_comments, patch.object(
                comment.Comment, 'get_sub_comments', new=AsyncMock(return_value={'replies': [child]})
            ) as get_sub_comments:
                rows = await api.get_comments(42, count=10, include_replies=True, root_rpids={root_id})

            self.assertEqual(rows[-1]['rpid'], 456)
            self.assertEqual(rows[-1]['root'], root_id)
            self.assertEqual(rows[-1]['parent'], root_id)
            self.assertIs(get_comments.await_args.kwargs['credential'], api.credential)
            get_sub_comments.assert_awaited_once_with(page_index=1, page_size=20)

        asyncio.run(run())

    def test_comment_send_uses_root_and_parent_without_live_network(self):
        async def run():
            api = BilibiliAPI.__new__(BilibiliAPI)
            api.credential = object()
            api.blocked_until = None
            with patch('core.bilibili_comment.comment.send_comment', new=AsyncMock(return_value={
                'rpid': 789
            })) as send:
                sent = await api.post_comment(42, 'simulated reply', root_rpid=123, parent_rpid=456)
            self.assertTrue(sent)
            self.assertEqual(api.last_comment_rpid, 789)
            self.assertEqual(send.await_args.kwargs['root'], 123)
            self.assertEqual(send.await_args.kwargs['parent'], 456)

        asyncio.run(run())


if __name__ == '__main__':
    unittest.main()
