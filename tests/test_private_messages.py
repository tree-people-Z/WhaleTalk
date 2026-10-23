import asyncio
import unittest
from unittest.mock import AsyncMock, patch

from core.bilibili_api import BilibiliAPI


class PrivateMessageTests(unittest.TestCase):
    def test_message_text_parses_json_and_plain_content(self):
        self.assertEqual(
            BilibiliAPI._message_text({'content': '{"content": "你好"}'}), '你好'
        )
        self.assertEqual(
            BilibiliAPI._message_text({'content': {'title': '视频标题'}}), '视频标题'
        )
        self.assertEqual(BilibiliAPI._message_text({'content': '纯文本'}), '纯文本')
        self.assertEqual(BilibiliAPI._message_text({'content': None}), '')

    def test_sessions_are_parsed_and_sorted_by_time(self):
        async def run():
            api = BilibiliAPI.__new__(BilibiliAPI)
            api.credential = object()
            payload = {
                'session_list': [
                    {'talker_id': 2, 'unread_count': 3,
                     'account_info': {'name': '用户B'},
                     'last_msg': {'content': '你好', 'timestamp': 100}},
                    {'talker_id': 1, 'unread_count': 0,
                     'account_info': {'name': '用户A'},
                     'last_msg': {'content': '在吗', 'timestamp': 200}},
                ]
            }
            with patch('core.bilibili_api.bili_session.get_sessions',
                       new=AsyncMock(return_value=payload)):
                return await api.get_private_sessions()

        sessions = asyncio.run(run())
        self.assertEqual([row['name'] for row in sessions], ['用户A', '用户B'])
        self.assertEqual(sessions[0]['last_message'], '在吗')
        self.assertEqual(sessions[1]['unread'], 3)

    def test_messages_are_sorted_and_withdrawn_messages_are_marked(self):
        async def run():
            api = BilibiliAPI.__new__(BilibiliAPI)
            api.credential = object()
            payload = {
                'messages': [
                    {'sender_uid': 1, 'content': '{"content": "later"}',
                     'timestamp': 200, 'msg_type': 1},
                    {'sender_uid': 1, 'content': 'earlier', 'timestamp': 100,
                     'msg_type': 1},
                    {'sender_uid': 1, 'content': '', 'timestamp': 300,
                     'msg_type': 5},
                ]
            }
            with patch('core.bilibili_api.bili_session.fetch_session_msgs',
                       new=AsyncMock(return_value=payload)):
                return await api.get_private_messages(9)

        messages = asyncio.run(run())
        self.assertEqual(
            [message['content'] for message in messages],
            ['earlier', 'later', '[消息已撤回]'],
        )


if __name__ == '__main__':
    unittest.main()
