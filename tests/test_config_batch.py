import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from utils.config_manager import ConfigManager


class ConfigBatchTests(unittest.TestCase):
    def test_batch_writes_disk_once(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            config = ConfigManager(path)
            with patch.object(config, 'save', wraps=config.save) as save:
                with config.batch():
                    config.set('test.a', 1)
                    config.set('test.b', 2)
                    config.set('test.c', 3)
                    self.assertEqual(save.call_count, 0)
                self.assertEqual(save.call_count, 1)
            saved = json.loads(path.read_text(encoding='utf-8'))
            self.assertEqual(saved['test'], {'a': 1, 'b': 2, 'c': 3})

    def test_batch_without_changes_does_not_write(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            config = ConfigManager(path)
            with patch.object(config, 'save') as save:
                with config.batch():
                    pass
                save.assert_not_called()

    def test_default_config_includes_round_write_limit(self):
        with tempfile.TemporaryDirectory() as directory:
            config = ConfigManager(Path(directory) / 'config.json')
            self.assertEqual(config.get('limits.max_writes_per_round'), 8)
            self.assertEqual(config.get('ai.timeout_seconds'), 60)
            self.assertEqual(config.get('ai.max_retries'), 2)


if __name__ == '__main__':
    unittest.main()
