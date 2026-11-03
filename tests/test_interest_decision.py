import unittest
from unittest.mock import AsyncMock

from core.ai_client import AIClient


class InterestDecisionTests(unittest.IsolatedAsyncioTestCase):
    def test_analysis_normalization_requires_high_score_for_notification(self):
        ordinary = AIClient._normalize_analysis_result({
            'worthy': True, 'interesting': True, 'score': 16,
            'summary': '普通优质视频', 'tags': ['教程']
        })
        special = AIClient._normalize_analysis_result({
            'worthy': True, 'interesting': True, 'score': 19,
            'summary': '特别符合角色兴趣', 'tags': ['AI']
        })
        self.assertFalse(ordinary['notify_owner'])
        self.assertTrue(special['notify_owner'])
        self.assertEqual(special['tags'], ['AI'])

    def test_analysis_prompt_weights_views_and_comments_as_popularity_signals(self):
        prompt = AIClient.__new__(AIClient)._build_analyze_prompt(
            '优质视频', '讲解内容', ['观众评论'], '角色人设',
            video_metrics={'play': '300万', 'comment_count': '5000', 'like': '20万', 'author': 'UP主'}
        )
        self.assertIn('内容价值与准确性', prompt)
        self.assertIn('播放量和评论量是明确的正向热度信号', prompt)
        self.assertIn('300万', prompt)
        self.assertIn('评论量：5000', prompt)
        self.assertIn('不能因为题材不符合人设偏好', prompt)

    def test_analysis_prompt_uses_up_to_fifteen_comments(self):
        prompt = AIClient.__new__(AIClient)._build_analyze_prompt(
            '标题', '字幕', [f'评论{i}' for i in range(25)], ''
        )
        self.assertIn('评论14', prompt)
        self.assertNotIn('评论15', prompt)

    async def test_generate_comment_includes_requested_mention(self):
        client = AIClient.__new__(AIClient)
        client.provider = None
        client.chat = AsyncMock(return_value='这个视频讲得不错。')

        result = await client.generate_comment('视频', '摘要', mention_user='主人昵称')
        self.assertIn('@主人昵称', result)

    async def test_generate_comment_removes_unrequested_mentions(self):
        client = AIClient.__new__(AIClient)
        client.provider = None
        client.chat = AsyncMock(return_value='这个视频真有趣 @主人昵称，讲解也很棒。')

        result = await client.generate_comment('视频', '摘要')
        self.assertNotIn('@', result)
        self.assertIn('讲解也很棒', result)


if __name__ == '__main__':
    unittest.main()
