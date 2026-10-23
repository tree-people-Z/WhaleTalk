import asyncio
import unittest
from unittest.mock import AsyncMock, Mock

from core.video_analyzer import VideoAnalyzer


class ReplyInvitationTests(unittest.TestCase):
    def test_detects_reply_invitation(self):
        self.assertTrue(VideoAnalyzer._looks_like_reply_invitation('鱼会回复吗'))
        self.assertTrue(VideoAnalyzer._looks_like_reply_invitation('鲸鱼娘在吗？'))
        self.assertTrue(VideoAnalyzer._looks_like_reply_invitation('回我一下嘛'))
        self.assertFalse(VideoAnalyzer._looks_like_reply_invitation('这个视频讲得不错'))
        self.assertFalse(VideoAnalyzer._looks_like_reply_invitation(''))

    def test_finds_top_level_invitations_with_limit(self):
        config = Mock()
        config.get = lambda key, default=None: {
            'interaction.reply_interesting_comments': True,
            'interaction.reply_to_others': True,
            'interaction.reply_only_owner': False,
            'bilibili.owner_name': '',
            'limits.max_interactions_per_video': 1,
        }.get(key, default)
        analyzer = VideoAnalyzer.__new__(VideoAnalyzer)
        analyzer.config = config
        analyzer.bili = Mock()
        analyzer.bili.get_self_info = AsyncMock(return_value={'uid': 1, 'name': 'Me'})
        analyzer.db = Mock()
        analyzer.db.get_replied_comment_ids = Mock(return_value=set())
        comments = [
            {'rpid': 1, 'mid': 2, 'user': 'viewer', 'content': '鱼会回复吗',
             'root': 0, 'parent': 0},
            {'rpid': 2, 'mid': 2, 'user': 'viewer', 'content': '普通评论',
             'root': 0, 'parent': 0},
            {'rpid': 3, 'mid': 1, 'user': 'Me', 'content': '鱼会回复吗',
             'root': 0, 'parent': 0},
            {'rpid': 4, 'mid': 2, 'user': 'viewer', 'content': '回复我吗',
             'root': 100, 'parent': 100},
        ]
        candidates = asyncio.run(analyzer._find_reply_invitations(comments))
        self.assertEqual([candidate['rpid'] for candidate in candidates], [1])

    def test_replies_to_invitations_with_per_run_limit(self):
        config = Mock()
        config.get = lambda key, default=None: {
            'interaction.reply_interesting_comments': True,
            'interaction.auto_comment': True,
            'limits.max_interactions_per_run': 2,
            'persona.enabled': False,
        }.get(key, default)
        analyzer = VideoAnalyzer.__new__(VideoAnalyzer)
        analyzer.config = config
        analyzer._interactions_sent_this_run = 0
        analyzer.ai = Mock()
        analyzer.ai.generate_reply = AsyncMock(return_value='哼，会啊')
        analyzer.bili = Mock()
        analyzer.bili.post_comment = AsyncMock(return_value=True)
        analyzer.bili.last_comment_rpid = 999
        analyzer.bili.is_blocked = Mock(return_value=False)
        analyzer.db = Mock()
        analysis = {
            'reply_invitations': [
                {'rpid': index, 'user': f'viewer{index}', 'content': '鱼会回复吗'}
                for index in (1, 2, 3)
            ]
        }
        sent = asyncio.run(analyzer._reply_to_invitations(
            {'aid': 1, 'bvid': 'BV1', 'title': '视频'}, analysis
        ))
        self.assertEqual(sent, 2)
        self.assertEqual(analyzer.bili.post_comment.await_count, 2)
        self.assertEqual(analyzer._interactions_sent_this_run, 2)


if __name__ == '__main__':
    unittest.main()
