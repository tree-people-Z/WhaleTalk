import unittest

from core.agent_summary import (
    compact_tool_results,
    parse_model_audit,
    summary_mismatch,
)


class AgentSummaryTests(unittest.TestCase):
    def test_audit_parses_score_and_owner_mention(self):
        audit = parse_model_audit('审计：最高分 17/20；@主人 是')
        self.assertEqual(audit['max_score'], 17)
        self.assertTrue(audit['mentioned_owner'])
        self.assertEqual(parse_model_audit('本轮没有操作'), {})

    def test_mismatch_detects_claims_without_actions(self):
        self.assertIn(
            '点赞', summary_mismatch('给视频点赞并留言', ['搜索视频 鲸鱼娘：成功'])
        )
        self.assertEqual(summary_mismatch('搜索了鲸鱼娘', ['搜索视频：成功']), [])

    def test_compaction_keeps_recent_tool_results_intact(self):
        messages = [
            {'role': 'user', 'content': '工具结果：' + ('x' * 2000)}
            for _ in range(6)
        ]
        compacted = compact_tool_results(messages, keep_recent=2, limit=100)
        self.assertEqual(compacted, 4)
        self.assertTrue(all(len(msg['content']) < 200 for msg in messages[:4]))
        self.assertIn('已压缩', messages[0]['content'])
        self.assertEqual(len(messages[-1]['content']), len('工具结果：' + 'x' * 2000))

    def test_compaction_ignores_short_and_non_tool_messages(self):
        messages = [
            {'role': 'user', 'content': '工具结果：short'},
            {'role': 'assistant', 'content': 'ok'},
        ]
        self.assertEqual(compact_tool_results(messages, keep_recent=0, limit=10), 0)


if __name__ == '__main__':
    unittest.main()
