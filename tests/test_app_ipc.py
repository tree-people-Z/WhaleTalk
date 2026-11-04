import tempfile
import unittest
from pathlib import Path

from utils.app_ipc import (
    QuitServer,
    is_quit_command,
    is_running,
    request_quit,
    server_name,
)


class AppIpcTests(unittest.TestCase):
    def test_server_name_is_stable_and_per_directory(self):
        self.assertEqual(server_name(Path('data')), server_name(Path('data')))
        self.assertNotEqual(server_name(Path('data')), server_name(Path('data2')))

    def test_only_quit_command_is_accepted(self):
        self.assertTrue(is_quit_command(b'quit\n'))
        self.assertTrue(is_quit_command(b'  QUIT  '))
        self.assertFalse(is_quit_command(b'quit now'))
        self.assertFalse(is_quit_command(b''))
        self.assertFalse(is_quit_command(b'\xff\xfe'))
        self.assertFalse(is_quit_command('删除所有评论\n'.encode('utf-8')))

    def test_no_instance_means_not_running_and_quit_fails_softly(self):
        with tempfile.TemporaryDirectory() as directory:
            data_dir = Path(directory)
            self.assertFalse(is_running(data_dir, timeout_ms=100))
            self.assertFalse(request_quit(data_dir, timeout_ms=100))

    def test_listening_instance_is_detected_until_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            data_dir = Path(directory)
            server = QuitServer(data_dir)
            try:
                self.assertTrue(is_running(data_dir, timeout_ms=500))
            finally:
                server.close()
            self.assertFalse(is_running(data_dir, timeout_ms=100))


if __name__ == '__main__':
    unittest.main()
