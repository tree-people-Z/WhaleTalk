import asyncio
import tempfile
import unittest
from pathlib import Path

from core.self_review import SelfReview
from utils.database import Database


class SelfReviewTests(unittest.TestCase):
    def test_no_data_raises_clear_error(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Database(str(Path(directory) / 'history.db'))
            try:
                review = SelfReview(db, None, Path(directory) / 'diaries')
                with self.assertRaises(RuntimeError):
                    asyncio.run(review.generate())
            finally:
                db.session.close()
                db.engine.dispose()

    def test_review_is_written_when_data_exists(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Database(str(Path(directory) / 'history.db'))
            try:
                db.add_memory_event(
                    'reply', user_name='viewer', user_mid=1,
                    content='聊天', my_content='回复',
                )
                review = SelfReview(db, None, Path(directory) / 'diaries')
                review.candidates_path = Path(directory) / 'persona_candidates.md'
                result = asyncio.run(review.generate())
                self.assertTrue(Path(result['review_path']).is_file())
                self.assertTrue(Path(result['candidates_path']).is_file())
            finally:
                db.session.close()
                db.engine.dispose()


if __name__ == '__main__':
    unittest.main()
