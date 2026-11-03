import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from utils.database import Database
from utils.db_models import CommentRecord


class ActivityDaysTests(unittest.TestCase):
    def test_series_covers_requested_days_and_counts_today(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Database(str(Path(directory) / 'activity.db'))
            try:
                db.add_comment_record('BV1', 1, '评论', comment_type='post', rpid=1)
                db.add_comment_record(
                    'BV1', 1, '回复', comment_type='reply', rpid=2,
                    parent_rpid=1, target_user='viewer',
                )
                db.add_agent_session('测试', ['工具调用'], 1, [])
                # 一条 10 天前的数据不应出现在 7 天窗口里
                old = CommentRecord(
                    bvid='BV1', aid=1, content='old', comment_type='post',
                    success=True, created_at=datetime.now() - timedelta(days=10),
                )
                db.session.add(old)
                db.session.commit()

                series = db.get_activity_days(7)
                self.assertEqual(len(series['dates']), 7)
                self.assertEqual(len(series['sent']), 7)
                self.assertEqual(series['posts'][-1], 1)
                self.assertEqual(series['replies'][-1], 1)
                self.assertEqual(series['sent'][-1], 2)
                self.assertEqual(series['runs'][-1], 1)
                self.assertEqual(sum(series['sent'][:-1]), 0)
                self.assertEqual(db.get_today_agent_runs(), 1)
            finally:
                db.close()


if __name__ == '__main__':
    unittest.main()
