import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from core.bili_tool import BiliTool
from core.free_agent import FreeAgent
from core import free_context
from utils.database import Database


class FakeBili:
    last_comment_rpid = 1

    def __init__(self):
        self.posts = 0

    async def get_x(self, value: int = 1):
        return {'value': value}

    async def post_comment(self, aid: int, text: str, root_rpid=None, parent_rpid=None):
        self.posts += 1
        return True

    def is_posting_blocked(self):
        return False

    def is_blocked(self):
        return False


class FakeAI:
    async def chat(self, messages, **kwargs):
        return '{"action":"finish","reason":"本轮不操作"}'


class SequenceAI:
    def __init__(self):
        self.calls = 0

    async def chat(self, messages, **kwargs):
        self.calls += 1
        if self.calls == 1:
            return ('{"action":"tool","tool":"bili_api","arguments":'
                    '{"method":"get_x","arguments":{"value":3}}}')
        return '{"action":"finish","reason":"查了一个值"}'


class DsmlAI:
    def __init__(self):
        self.calls = 0

    async def chat(self, messages, **kwargs):
        self.calls += 1
        if self.calls == 1:
            return (
                '<\uff5cDSML\uff5c calls>\n'
                '<\uff5cDSML\uff5c invoke name="bili_api">\n'
                '<\uff5cDSML\uff5c parameter name="arguments" string="false">'
                '{"value": 9}</\uff5cDSML\uff5c parameter>\n'
                '<\uff5cDSML\uff5c parameter name="method" string="true">'
                'get_x</\uff5cDSML\uff5c parameter>\n'
                '</\uff5cDSML\uff5c invoke>\n'
                '</\uff5cDSML\uff5c calls>'
            )
        return '{"action":"finish","reason":"完成"}'


class BiliToolTests(unittest.TestCase):
    def test_lists_and_calls_public_methods(self):
        tool = BiliTool(FakeBili(), Mock(), Mock())
        names = {item['name'] for item in tool.spec()['methods']}
        self.assertIn('get_x', names)
        self.assertIn('post_comment', names)
        result = asyncio.run(tool.call('get_x', {'value': 7}))
        self.assertEqual(result, {'value': 7})
        self.assertIn('error', asyncio.run(tool.call('missing', {})))

    def test_write_cap(self):
        bili = FakeBili()
        db = Mock()
        db.get_today_comment_count.return_value = 0
        config = Mock()
        config.get.return_value = 60
        tool = BiliTool(bili, db, config)
        results = [asyncio.run(tool.call('post_comment', {'aid': 1, 'text': 'x'})) for _ in range(9)]
        self.assertEqual(results[:8], [True] * 8)
        self.assertIn('error', results[8])


class FreeContextTests(unittest.TestCase):
    def test_diary_read_write_and_recent_context(self):
        with tempfile.TemporaryDirectory() as directory:
            diary_dir = Path(directory)
            with patch.object(free_context, 'DIARY_DIR', diary_dir):
                free_context.append_diary('今天很开心')
                days = free_context.list_diary_days()
                self.assertTrue(days)
                self.assertIn(days[0], free_context.read_diary())
                self.assertIn('今天很开心', free_context.read_diary(days[0]))
                self.assertIn('今天很开心', free_context.load_recent_diaries())


class FreeAgentTests(unittest.TestCase):
    def test_finish_returns_success(self):
        agent = FreeAgent(FakeBili(), FakeAI(), Mock(), Mock())
        with patch('core.free_agent.build_agent_context', return_value='人设/日记/记忆'):
            result = asyncio.run(agent.run_analysis_cycle())
        self.assertEqual(result['status'], 'success')
        self.assertEqual(result['summary'], '本轮不操作')
        self.assertEqual(result['actions'], [])

    def test_action_log_records_tool_call(self):
        agent = FreeAgent(FakeBili(), SequenceAI(), Mock(), Mock())
        with patch('core.free_agent.build_agent_context', return_value='人设/日记/记忆'):
            result = asyncio.run(agent.run_analysis_cycle())
        self.assertEqual(len(result['actions']), 1)
        self.assertIn('get_x', result['actions'][0])
        self.assertIn('成功', result['actions'][0])

    def test_dsml_call_executes_tool(self):
        agent = FreeAgent(FakeBili(), DsmlAI(), Mock(), Mock())
        with patch('core.free_agent.build_agent_context', return_value='人设/日记/记忆'):
            result = asyncio.run(agent.run_analysis_cycle())
        self.assertEqual(len(result['actions']), 1)
        self.assertIn('get_x', result['actions'][0])
        self.assertIn('成功', result['actions'][0])

    def test_normalizes_malformed_bili_calls(self):
        agent = FreeAgent(FakeBili(), FakeAI(), Mock(), Mock())
        self.assertEqual(
            agent._normalize_call('bili_api', {'get_x': {'value': 1}}),
            ('bili_api', {'method': 'get_x', 'arguments': {'value': 1}}),
        )
        self.assertEqual(
            agent._normalize_call(
                'bili_api',
                {'arguments': {'method': 'get_x', 'arguments': {'value': 2}}},
            ),
            ('bili_api', {'method': 'get_x', 'arguments': {'value': 2}}),
        )
        self.assertEqual(
            agent._normalize_call('get_x', '{"value": 3}'),
            ('bili_api', {'method': 'get_x', 'arguments': {'value': 3}}),
        )
        self.assertEqual(
            agent._normalize_call(
                'bili_api',
                {'keyword': '鲸鱼娘', 'order': 'pubdate', 'page': 1},
            ),
            ('bili_api', {
                'method': 'search_videos',
                'arguments': {'keyword': '鲸鱼娘', 'order': 'pubdate', 'page': 1},
            }),
        )
        self.assertEqual(
            agent._normalize_call(
                'bili_api', {'talker_id': 1, 'text': 'hi'}
            )[1]['method'],
            'send_private_message',
        )

    def test_top_level_method_is_normalized(self):
        ai = Mock()
        ai.chat = AsyncMock(side_effect=[
            '{"action":"tool","tool":"bili_api","method":"get_x","arguments":{"value":4}}',
            '{"action":"finish","reason":"done"}',
        ])
        agent = FreeAgent(FakeBili(), ai, Mock(), Mock())
        with patch('core.free_agent.build_agent_context', return_value='ctx'):
            result = asyncio.run(agent.run_analysis_cycle())
        self.assertIn('get_x 成功', result['actions'][0])

    def test_session_history_is_saved(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Database(str(Path(directory) / 'history.db'))
            try:
                db.add_agent_session('这一轮做了什么', ['get_x 成功'], 1)
                rows = db.get_recent_agent_sessions()
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]['summary'], '这一轮做了什么')
                self.assertEqual(rows[0]['actions'], ['get_x 成功'])
                self.assertEqual(rows[0]['comments_sent'], 1)
            finally:
                db.session.close()
                db.engine.dispose()


if __name__ == '__main__':
    unittest.main()
