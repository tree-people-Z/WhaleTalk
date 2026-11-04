import os
import socket
import tempfile
import unittest
from pathlib import Path

from utils.single_instance import (
    acquire_instance_lock,
    clear_stale_lock,
    is_pid_alive,
    read_lock_pid,
)

_DEAD_PID = 999999


def _write_lock(path: Path, pid) -> None:
    path.write_text(f"{pid}\n{socket.gethostname()}\nWhaleTalk\n", encoding='utf-8')


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

    def test_pid_liveness(self):
        self.assertTrue(is_pid_alive(os.getpid()))
        self.assertFalse(is_pid_alive(_DEAD_PID))
        self.assertFalse(is_pid_alive(None))
        self.assertFalse(is_pid_alive(0))

    def test_lock_pid_round_trip(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'app.lock'
            _write_lock(path, _DEAD_PID)
            self.assertEqual(read_lock_pid(path), _DEAD_PID)
            _write_lock(path, os.getpid())
            self.assertEqual(read_lock_pid(path), os.getpid())

    def test_stale_lock_from_killed_instance_is_removed(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'app.lock'
            _write_lock(path, _DEAD_PID)
            self.assertTrue(clear_stale_lock(path))
            self.assertFalse(path.exists())
            # 清掉之后应该能重新拿到锁。
            lock = acquire_instance_lock(path)
            self.assertIsNotNone(lock)
            lock.unlock()

    def test_lock_of_live_process_is_kept(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'app.lock'
            _write_lock(path, os.getpid())
            self.assertFalse(clear_stale_lock(path))
            self.assertTrue(path.exists())

    def test_unparsable_lock_is_left_to_qt(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'app.lock'
            path.write_text('not a lock file\n', encoding='utf-8')
            self.assertIsNone(read_lock_pid(path))
            self.assertFalse(clear_stale_lock(path))
            self.assertTrue(path.exists())


if __name__ == '__main__':
    unittest.main()
