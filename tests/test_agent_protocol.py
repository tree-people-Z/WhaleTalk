import unittest

from core.agent_protocol import (
    normalize_bvid,
    parse_dsml_decision,
    parse_json_decision,
    strip_tool_markup,
)

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

    def test_dsml_nested_method_and_stray_brace(self):
        text = (
            '<\uff5cDSML\uff5c calls>\n'
            '<\uff5cDSML\uff5c invoke name="bili_api">\n'
            '<\uff5cDSML\uff5c parameter name="arguments" string="false">'
            '{"method": "inspect_video", "arguments": '
            '{"bvid": "BV1test", "frames": 2}}'
            '</\uff5cDSML\uff5c parameter>\n'
            '<\uff5cDSML\uff5c parameter name="tool" string="true">'
            'inspect_video"}'
            '</\uff5cDSML\uff5c parameter>\n'
            '</\uff5cDSML\uff5c invoke>\n'
            '</\uff5cDSML\uff5c calls>'
        )
        decision = parse_json_decision(text)
        self.assertEqual(decision['tool'], 'inspect_video')
        self.assertEqual(decision['arguments']['bvid'], 'BV1test')

    def test_closing_tag_with_attributes_does_not_pollute_next_value(self):
        # Regression: a run logged `bvid 提供错误` because the bvid value had
        # swallowed the next parameter after a malformed closing tag.
        text = (
            '<\uff5cDSML\uff5c calls>\n'
            '<\uff5cDSML\uff5c invoke name="inspect_video">\n'
            '<\uff5cDSML\uff5c parameter name="bvid" string="true">'
            'BV1iwxD6NECk'
            '</\uff5cDSML\uff5c parameter name="comments" string="false">10'
            '</\uff5cDSML\uff5c parameter>\n'
            '</\uff5cDSML\uff5c invoke>\n'
            '</\uff5cDSML\uff5c calls>'
        )
        decision = parse_json_decision(text)
        self.assertEqual(decision['tool'], 'inspect_video')
        self.assertEqual(decision['arguments']['bvid'], 'BV1iwxD6NECk')

    def test_json_bvid_markup_is_cleaned(self):
        decision = parse_json_decision(
            '{"action":"tool","tool":"inspect_video","arguments":'
            '{"bvid":"BV1iwxD6NECk</\uff5cDSML\uff5c parameter","frames":"3"}}'
        )
        self.assertEqual(decision['arguments']['bvid'], 'BV1iwxD6NECk')

    def test_strip_tool_markup_keeps_plain_values(self):
        self.assertEqual(strip_tool_markup(' 普通评论 10 条 '), '普通评论 10 条')
        dirty = 'BV1iwxD6NECk</\uff5cDSML\uff5c parameter name="x">10'
        self.assertEqual(strip_tool_markup(dirty), 'BV1iwxD6NECk')
        self.assertEqual(normalize_bvid(dirty), 'BV1iwxD6NECk')
        self.assertEqual(normalize_bvid(''), '')
        self.assertEqual(normalize_bvid('BV1test'), '')

    def test_double_pipe_marker_is_parsed(self):
        """The model sometimes emits `<｜｜DSML｜｜>`; it must still parse."""
        doubled = DSML_TEXT.replace('<\uff5cDSML\uff5c', '<\uff5c\uff5cDSML\uff5c\uff5c')
        doubled = doubled.replace('</\uff5cDSML\uff5c', '</\uff5c\uff5cDSML\uff5c\uff5c')
        decision = parse_json_decision(doubled)
        self.assertIsNotNone(decision)
        self.assertEqual(decision['tool'], 'bili_api')
        self.assertEqual(decision['arguments']['method'], 'search_videos')
        self.assertEqual(
            decision['arguments']['arguments'],
            {'keyword': 'DeepSeek', 'order': 'pubdate'},
        )

    def test_double_pipe_markup_is_stripped(self):
        dirty = 'BV1iwxD6NECk</\uff5c\uff5cDSML\uff5c\uff5c parameter name="x">10'
        self.assertEqual(strip_tool_markup(dirty), 'BV1iwxD6NECk')
        self.assertEqual(normalize_bvid(dirty), 'BV1iwxD6NECk')

    def test_unparsable_markup_never_degrades_to_json_fragment(self):
        """A broken tool block must not be read as `{}` or a params fragment."""
        text = (
            '<\uff5c\uff5cDSML\uff5c\uff5c calls>\n'
            '<\uff5c\uff5cDSML\uff5c\uff5c parameter name="arguments">'
            '{"keyword": "x"}</\uff5c\uff5cDSML\uff5c\uff5c parameter>\n'
            '<\uff5c\uff5cDSML\uff5c\uff5c invoke name="bili_api">\n'
            '</\uff5c\uff5cDSML\uff5c\uff5c calls>'
        )
        self.assertIsNone(parse_json_decision(text))

    def test_unparsable_empty_arguments_block_returns_none(self):
        text = (
            '<\uff5c\uff5cDSML\uff5c\uff5c calls>\n'
            '<\uff5c\uff5cDSML\uff5c\uff5c parameter name="arguments">{}</\uff5c\uff5cDSML\uff5c\uff5c parameter>\n'
            '</\uff5c\uff5cDSML\uff5c\uff5c calls>'
        )
        self.assertIsNone(parse_json_decision(text))



if __name__ == '__main__':
    unittest.main()
