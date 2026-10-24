import tempfile
import unittest
from pathlib import Path

from utils.database import Database


class CommentHistoryTests(unittest.TestCase):
    def test_skips_recently_analyzed_videos(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Database(str(Path(directory) / 'history.db'))
            try:
                db.add_video_record(
                    'BV1', {'aid': 1, 'title': '标题'}, {'score': 10}
                )
                self.assertTrue(db.is_video_analyzed_recently('BV1', hours=2))
                self.assertFalse(db.is_video_analyzed_recently('BV2', hours=2))
            finally:
                db.session.close()
                db.engine.dispose()

    def test_today_comment_count_includes_replies(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Database(str(Path(directory) / 'history.db'))
            try:
                db.add_comment_record('BV1', 1, '评论', comment_type='post', rpid=1)
                db.add_comment_record(
                    'BV1', 1, '回复', comment_type='reply', rpid=2,
                    parent_rpid=1, target_user='viewer'
                )
                self.assertEqual(db.get_today_comment_count(), 1)
                self.assertEqual(db.get_today_comment_count(include_replies=True), 2)
            finally:
                db.session.close()
                db.engine.dispose()

    def test_like_records_are_counted(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Database(str(Path(directory) / 'history.db'))
            try:
                db.add_like_record('BV1', 1, True)
                db.add_like_record('BV2', 2, False)
                self.assertEqual(db.get_today_like_count(), 1)
                self.assertTrue(db.has_liked_video('BV1'))
                self.assertFalse(db.has_liked_video('BV2'))
            finally:
                db.session.close()
                db.engine.dispose()

    def test_recent_comments_can_include_replies(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Database(str(Path(directory) / 'history.db'))
            try:
                db.add_comment_record(
                    'BV1', 1, '顶层评论', comment_type='post', rpid=100
                )
                db.add_comment_record(
                    'BV1', 1, '回复内容', comment_type='reply', rpid=200,
                    parent_rpid=100, target_user='viewer'
                )

                posts = db.get_recent_comments(limit=10)
                self.assertEqual([item['content'] for item in posts], ['顶层评论'])

                all_items = db.get_recent_comments(limit=10, include_replies=True)
                self.assertEqual(len(all_items), 2)
                self.assertEqual(all_items[0]['comment_type'], 'reply')
                self.assertEqual(all_items[0]['thread_root'], 100)
                self.assertEqual(all_items[0]['target_user'], 'viewer')
            finally:
                db.session.close()
                db.engine.dispose()


if __name__ == '__main__':
    unittest.main()
