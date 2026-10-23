import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from bilibili_api import request_settings

from core.bilibili_api import BilibiliAPI


class BilibiliRiskControlTests(unittest.TestCase):
    def test_init_disables_bili_ticket(self):
        previous = request_settings.get_enable_bili_ticket()
        try:
            request_settings.set_enable_bili_ticket(True)
            with tempfile.TemporaryDirectory() as directory:
                BilibiliAPI(credential_path=Path(directory) / 'cookies.json')
            self.assertFalse(request_settings.get_enable_bili_ticket())
        finally:
            request_settings.set_enable_bili_ticket(previous)

    def _bare_api(self):
        api = BilibiliAPI.__new__(BilibiliAPI)
        api.blocked_until = None
        api._comment_min_interval = 2.0
        api._last_comment_request_at = 0.0
        api._comment_request_lock = None
        api._comments_cache = {}
        api.credential = None
        api._self_info = None
        return api

    def test_short_error_strips_html_and_truncates(self):
        text = BilibiliAPI._short_error(
            '<html><body><h1>412</h1>' + 'x' * 400 + '</body></html>'
        )
        self.assertIn('412', text)
        self.assertNotIn('<html>', text)
        self.assertLessEqual(len(text), 161)

    def test_412_sets_blocked_and_stops_further_requests(self):
        api = self._bare_api()

        async def scenario():
            with patch(
                'core.bilibili_api.comment.get_comments',
                AsyncMock(side_effect=Exception('网络错误，状态码：412 - <html>')),
            ):
                first = await api.get_comments(123)
            self.assertEqual(first, [])
            self.assertTrue(api.is_blocked())

            calls = []

            async def fake_get_comments(*args, **kwargs):
                calls.append(args)
                return {}

            with patch(
                'core.bilibili_api.comment.get_comments',
                side_effect=fake_get_comments,
            ):
                second = await api.get_comments(456)
            self.assertEqual(second, [])
            self.assertEqual(calls, [])

        asyncio.run(scenario())


if __name__ == '__main__':
    unittest.main()
