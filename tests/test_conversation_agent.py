import tempfile
import unittest
from pathlib import Path

from core.conversation_agent import ConversationAgent, _parse
from utils.database import Database


class Config(dict):
    def get(self, key, default=None):
        return dict.get(self, key, default)


class FakeAI:
    async def chat(self, messages, **kwargs):
        return '{"action":"finish","reason":"不相关"}'


class ConversationAgentTests(unittest.TestCase):
    def test_parse_action(self):
        self.assertEqual(_parse('{"action":"finish"}')['action'], 'finish')
        self.assertEqual(
            _parse('```json\n{"action":"tool","tool":"read_memory"}\n```')['tool'],
            'read_memory',
        )
        self.assertIsNone(_parse('不回复'))

    def test_thread_state_counts(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Database(str(Path(directory) / 'history.db'))
            try:
                self.assertEqual(db.get_thread_state(1)['reply_count'], 0)
                db.record_thread_reply(1)
                db.record_thread_reply(1)
                state = db.get_thread_state(1)
                self.assertTrue(state['bot_participated'])
                self.assertEqual(state['reply_count'], 2)
            finally:
                db.session.close()
                db.engine.dispose()

    def test_agent_skip_returns_false(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Database(str(Path(directory) / 'history.db'))
            async def send(event, text):
                return False
            try:
                agent = ConversationAgent(
                    None, db, FakeAI(), Config(), send
                )
                result = __import__('asyncio').run(agent.handle({
                    'scope': 'other_thread',
                    'root_rpid': 1,
                    'rpid': 2,
                    'aid': 3,
                }))
                self.assertFalse(result)
            finally:
                db.session.close()
                db.engine.dispose()

    def test_reply_tools_hide_bili_api(self):
        async def send(event, text):
            return True
        agent = ConversationAgent(None, None, FakeAI(), Config(), send)
        names = {tool.get('name') for tool in agent._read_tools('')}
        self.assertNotIn('bili_api', names)
        self.assertIn('reply_comment', names)
        result = __import__('asyncio').run(
            agent._execute('bili_api', {'method': 'post_comment'}, {})
        )
        self.assertIn('error', result)

    def test_reply_text_is_not_modified(self):
        sent = {}

        async def send(event, text):
            sent['text'] = text
            return True

        agent = ConversationAgent(None, None, FakeAI(), Config(), send)
        result = __import__('asyncio').run(agent._execute(
            'reply_comment',
            {'text': '@Tree-people 模型自己写的回复'},
            {'root_rpid': 1, 'rpid': 2, 'aid': 3},
        ))
        self.assertTrue(result.get('ok'))
        self.assertEqual(sent['text'], '@Tree-people 模型自己写的回复')


if __name__ == '__main__':
    unittest.main()
