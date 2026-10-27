import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from core.bili_tool import BiliTool
from core.free_agent import FreeAgent
from core import free_context


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


if __name__ == '__main__':
    unittest.main()
