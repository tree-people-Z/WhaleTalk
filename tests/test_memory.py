import tempfile
import unittest
from pathlib import Path

from utils.database import Database


class MemoryTests(unittest.TestCase):
    def test_memory_event_is_stored(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Database(str(Path(directory) / 'history.db'))
            try:
                db.add_memory_event(
                    'reply',
                    user_name='viewer',
                    user_mid=42,
                    aid=1,
                    bvid='BV1',
                    video_title='视频',
                    content='上次聊到剪辑',
                    my_content='记得，卡点确实麻烦',
                )
                events = db.get_recent_memory_events()
                self.assertEqual(len(events), 1)
                self.assertEqual(events[0]['content'], '上次聊到剪辑')
                self.assertEqual(events[0]['my_content'], '记得，卡点确实麻烦')
            finally:
                db.session.close()
                db.engine.dispose()


if __name__ == '__main__':
    unittest.main()
