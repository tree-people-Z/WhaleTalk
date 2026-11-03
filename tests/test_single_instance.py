import tempfile
import unittest
from pathlib import Path

from utils.single_instance import acquire_instance_lock


class SingleInstanceTests(unittest.TestCase):
    def test_second_lock_is_rejected_until_released(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'app.lock'
            first = acquire_instance_lock(path)
            self.assertIsNotNone(first)
            try:
                self.assertIsNone(acquire_instance_lock(path))
            finally:
                first.unlock()
            second = acquire_instance_lock(path)
            self.assertIsNotNone(second)
            second.unlock()


if __name__ == '__main__':
    unittest.main()
