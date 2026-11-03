import json
import tempfile
import unittest
from pathlib import Path

from core.ai_client import AIClient
from utils import secure_store
from utils.config_manager import ConfigManager


class ApiKeyNormalizationTests(unittest.TestCase):
    def test_default_daily_send_limit_is_60(self):
        config = ConfigManager(Path('nonexistent-config-for-defaults.json'))
        self.assertEqual(config.get('limits.max_comments_per_day'), 60)

    def test_config_load_and_save_strip_key_whitespace(self):
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / 'config.json'
            path.write_text(json.dumps({'ai': {'api_key': '  test-key\r\n'}}), encoding='utf-8')

            config = ConfigManager(path)
            self.assertEqual(config.get('ai.api_key'), 'test-key')

            config.set('ai.api_key', '  another-key\n')
            saved = json.loads(path.read_text(encoding='utf-8'))
            stored = saved['ai']['api_key']
            if secure_store.available():
                self.assertTrue(secure_store.is_encrypted(stored))
            self.assertEqual(secure_store.unprotect(stored), 'another-key')
            # 再次加载应还原为明文
            self.assertEqual(ConfigManager(path).get('ai.api_key'), 'another-key')

    def test_ai_client_strips_key_before_sdk_initialization(self):
        client = AIClient(provider='deepseek', api_key='  test-key\r\n')
        self.assertEqual(client.api_key, 'test-key')


if __name__ == '__main__':
    unittest.main()
