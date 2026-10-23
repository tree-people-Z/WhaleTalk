import asyncio
import unittest
from unittest.mock import AsyncMock, Mock

from core.ai_client import AIClient
from core.video_analyzer import VideoAnalyzer
from utils.config_manager import ConfigManager


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

    async def test_owner_is_mentioned_only_for_interesting_video(self):
        config = Mock()
        config.get = lambda key, default=None: {
            'interaction.auto_comment': True,
            'limits.min_score_to_comment': 13,
            'limits.min_score_to_mention_owner': 17,
            'interaction.mention_owner_on_interesting': True,
            'bilibili.owner_name': '主人昵称',
            'persona.enabled': False,
        }.get(key, default)
        analyzer = VideoAnalyzer.__new__(VideoAnalyzer)
        analyzer.config = config
        analyzer.ai = Mock()
        analyzer.ai.generate_comment = AsyncMock(return_value='测试评论')
        analyzer.bili = Mock()
        analyzer.bili.post_comment = AsyncMock(return_value=True)
        analyzer.db = Mock()

        video = {'bvid': 'BVtest', 'aid': 1, 'title': '测试视频'}
        await analyzer._post_comment_for_video(video, {
            'score': 16, 'interesting': False, 'notify_owner': False, 'summary': '普通内容'
        })
        self.assertIsNone(analyzer.ai.generate_comment.await_args.kwargs['mention_user'])

        await analyzer._post_comment_for_video(video, {
            'score': 19, 'interesting': True, 'notify_owner': True, 'summary': '特别内容'
        })
        self.assertEqual(
            analyzer.ai.generate_comment.await_args.kwargs['mention_user'], '主人昵称'
        )

    async def test_owner_mention_is_off_by_default_even_for_interesting_video(self):
        config = Mock()
        config.get = lambda key, default=None: {
            'interaction.auto_comment': True,
            'limits.min_score_to_comment': 13,
            'limits.min_score_to_mention_owner': 17,
            'bilibili.owner_name': '主人昵称',
            'persona.enabled': False,
            'interaction.mention_owner_on_interesting': False,
        }.get(key, default)
        analyzer = VideoAnalyzer.__new__(VideoAnalyzer)
        analyzer.config = config
        analyzer.ai = Mock()
        analyzer.ai.generate_comment = AsyncMock(return_value='聊聊视频里的内容')
        analyzer.bili = Mock()
        analyzer.bili.post_comment = AsyncMock(return_value=True)
        analyzer.db = Mock()

        await analyzer._post_comment_for_video(
            {'bvid': 'BVtest', 'aid': 1, 'title': '测试视频'},
            {'score': 20, 'interesting': True, 'notify_owner': True, 'summary': '特别内容'}
        )
        self.assertIsNone(analyzer.ai.generate_comment.await_args.kwargs['mention_user'])

    async def test_generate_comment_removes_unrequested_mentions(self):
        client = AIClient.__new__(AIClient)
        client.provider = None
        client.chat = AsyncMock(return_value='这个视频真有趣 @主人昵称，讲解也很棒。')

        result = await client.generate_comment('视频', '摘要')
        self.assertNotIn('@', result)
        self.assertIn('讲解也很棒', result)


if __name__ == '__main__':
    unittest.main()
