import unittest

from core.agent_protocol import parse_dsml_decision, parse_json_decision

DSML_TEXT = (
    '<\uff5cDSML\uff5c calls>\n'
    '<\uff5cDSML\uff5c invoke name="bili_api">\n'
    '<\uff5cDSML\uff5c parameter name="arguments" string="false">'
    '{"keyword": "DeepSeek", "order": "pubdate"}'
    '</\uff5cDSML\uff5c parameter>\n'
    '<\uff5cDSML\uff5c parameter name="method" string="true">'
    'search_videos'
    '</\uff5cDSML\uff5c parameter>\n'
    '</\uff5cDSML\uff5c invoke>\n'
    '</\uff5cDSML\uff5c calls>'
)


class AgentProtocolTests(unittest.TestCase):
    def test_parses_deepseek_dsml(self):
        decision = parse_json_decision(DSML_TEXT)
        self.assertEqual(decision['action'], 'tool')
        self.assertEqual(decision['tool'], 'bili_api')
        self.assertEqual(decision['arguments']['method'], 'search_videos')
        self.assertEqual(
            decision['arguments']['arguments'],
            {'keyword': 'DeepSeek', 'order': 'pubdate'},
        )

    def test_plain_json_still_works(self):
        decision = parse_json_decision(
            '{"action":"tool","tool":"bili_api","arguments":{"method":"get_x"}}'
        )
        self.assertEqual(decision['arguments']['method'], 'get_x')

    def test_dsml_returns_none_for_plain_text(self):
        self.assertIsNone(parse_dsml_decision('hello'))

    def test_dsml_tool_parameter_is_kept(self):
        text = (
            '<\uff5cDSML\uff5c calls>\n'
            '<\uff5cDSML\uff5c invoke name="bili_api">\n'
            '<\uff5cDSML\uff5c parameter name="arguments" string="false">'
            '{"bvid": "BV1test", "frames": 2}'
            '</\uff5cDSML\uff5c parameter>\n'
            '<\uff5cDSML\uff5c parameter name="tool" string="true">'
            'inspect_video'
            '</\uff5cDSML\uff5c parameter>\n'
            '</\uff5cDSML\uff5c invoke>\n'
            '</\uff5cDSML\uff5c calls>'
        )
        decision = parse_json_decision(text)
        self.assertEqual(decision['tool'], 'inspect_video')
        self.assertEqual(decision['arguments']['bvid'], 'BV1test')


if __name__ == '__main__':
    unittest.main()
