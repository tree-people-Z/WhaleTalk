import tempfile
import unittest
from pathlib import Path

from core.daily_diary import ensure_daily_diary
from utils.database import Database


class DailyDiaryTests(unittest.TestCase):
    def test_creates_one_daily_diary(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            db = Database(str(root / 'history.db'))
            try:
                first = ensure_daily_diary(db, root / 'diaries')
                self.assertIsNotNone(first)
                self.assertTrue(first.is_file())
                self.assertIn('今天发送了', first.read_text(encoding='utf-8'))
                second = ensure_daily_diary(db, root / 'diaries')
                self.assertEqual(first, second)
            finally:
                db.session.close()
                db.engine.dispose()


if __name__ == '__main__':
    unittest.main()
