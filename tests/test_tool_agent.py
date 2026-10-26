import unittest

from core.tool_agent import ReadOnlyTools, ToolAgent
from utils.probability import roll_probability


class ToolAgentTests(unittest.TestCase):
    def test_parse_plain_json(self):
        decision = ToolAgent._parse_decision(
            '{"action":"tool","tool":"search_videos","arguments":{"keyword":"猫"}}'
        )
        self.assertEqual(decision['tool'], 'search_videos')

    def test_parse_fenced_json(self):
        decision = ToolAgent._parse_decision(
            '```json\n{"action":"finish","summary":"看完了"}\n```'
        )
        self.assertEqual(decision['action'], 'finish')

    def test_invalid_json_returns_none(self):
        self.assertIsNone(ToolAgent._parse_decision('我想先看看视频。'))

    def test_registry_is_read_only(self):
        names = {spec['name'] for spec in ReadOnlyTools(None, None, None, None).specs()}
        self.assertIn('search_videos', names)
        self.assertIn('get_video_comments', names)
        for forbidden in ('post_comment', 'reply_comment', 'send_dm', 'like_video'):
            self.assertNotIn(forbidden, names)


class ProbabilityTests(unittest.TestCase):
    class Config(dict):
        def get(self, key, default=None):
            return dict.get(self, key, default)

    def test_zero_never_fires(self):
        config = self.Config({'interaction.test_prob': 0})
        for _ in range(20):
            self.assertFalse(roll_probability(config, 'test_prob', 50))

    def test_hundred_always_fires(self):
        config = self.Config({'interaction.test_prob': 100})
        for _ in range(20):
            self.assertTrue(roll_probability(config, 'test_prob', 0))


if __name__ == '__main__':
    unittest.main()
