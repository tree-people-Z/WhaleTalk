import datetime
import unittest

from gui.comments_tab import CommentsTab


class CommentThreadGroupingTests(unittest.TestCase):
    def test_merges_records_of_the_same_thread(self):
        base = datetime.datetime(2026, 10, 25, 12, 0)
        records = [
            {'aid': 1, 'rpid': 100, 'thread_root': 100, 'comment_type': 'post',
             'content': '我的评论', 'commented_at': base, 'video_title': '视频'},
            {'aid': 1, 'rpid': 200, 'thread_root': 100, 'comment_type': 'reply',
             'content': '我的第一条回复', 'commented_at': base + datetime.timedelta(minutes=1)},
            {'aid': 1, 'rpid': 201, 'thread_root': 100, 'comment_type': 'reply',
             'content': '我的第二条回复', 'commented_at': base + datetime.timedelta(minutes=2)},
            {'aid': 2, 'rpid': 300, 'thread_root': 300, 'comment_type': 'post',
             'content': '另一个视频的评论', 'commented_at': base + datetime.timedelta(minutes=3)},
        ]
        groups = CommentsTab._group_threads(records)
        self.assertEqual(len(groups), 2)
        first = next(group for group in groups if group['thread_root'] == 100)
        self.assertEqual(first['my_count'], 3)
        self.assertEqual(first['last_content'], '我的第二条回复')
        self.assertEqual(first['content'], '我的评论')


if __name__ == '__main__':
    unittest.main()
