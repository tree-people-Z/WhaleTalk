import json
import tempfile
import unittest
from pathlib import Path

from core.ai_client import AIClient
from utils.config_manager import ConfigManager


class ApiKeyNormalizationTests(unittest.TestCase):
    def test_default_daily_comment_limit_is_96(self):
        config = ConfigManager(Path('nonexistent-config-for-defaults.json'))
        self.assertEqual(config.get('limits.max_comments_per_day'), 96)

    def test_config_load_and_save_strip_key_whitespace(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / 'config.json'
            path.write_text(json.dumps({'ai': {'api_key': '  test-key\r\n'}}), encoding='utf-8')

            config = ConfigManager(path)
            self.assertEqual(config.get('ai.api_key'), 'test-key')

            config.set('ai.api_key', '  another-key\n')
            saved = json.loads(path.read_text(encoding='utf-8'))
            self.assertEqual(saved['ai']['api_key'], 'another-key')

    def test_ai_client_strips_key_before_sdk_initialization(self):
        client = AIClient(provider='deepseek', api_key='  test-key\r\n')
        self.assertEqual(client.api_key, 'test-key')


if __name__ == '__main__':
    unittest.main()
