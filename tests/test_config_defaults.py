import json
import tempfile
import unittest
from pathlib import Path

from utils.config_manager import ConfigManager


class ConfigDefaultTests(unittest.TestCase):
    def test_defaults_match_operating_preferences_without_private_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            config = ConfigManager(Path(directory) / 'config.json')

        self.assertEqual(config.get('ai.provider'), 'deepseek')
        self.assertEqual(config.get('ai.model'), 'deepseek-flash')
        self.assertEqual(config.get('schedule.browse_interval_min_minutes'), 5)
        self.assertEqual(config.get('schedule.browse_interval_max_minutes'), 30)
        self.assertEqual(config.get('schedule.reply_check_interval_minutes'), 1)
        self.assertFalse(config.get('schedule.auto_run'))
        self.assertTrue(config.get('schedule.deepseek_offpeak_only'))
        self.assertEqual(config.get('search.order'), 'totalrank')
        self.assertEqual(config.get('search.max_results_per_keyword'), 5)
        self.assertEqual(config.get('limits.max_comments_per_day'), 60)
        self.assertEqual(config.get('limits.max_videos_per_run'), 20)
        self.assertEqual(config.get('limits.min_score_to_comment'), 10)
        self.assertEqual(config.get('limits.min_score_to_mention_owner'), 13)
        self.assertTrue(config.get('interaction.auto_comment'))
        self.assertTrue(config.get('interaction.comment_monitor'))
        self.assertTrue(config.get('interaction.auto_reply'))
        self.assertFalse(config.get('interaction.mention_owner_on_interesting'))
        self.assertTrue(config.get('analysis.enable_frame_analysis'))
        self.assertEqual(config.get('analysis.transcription_mode'), 'off')
        self.assertFalse(config.get('analysis.local_transcription_enabled'))
        self.assertEqual(config.get('analysis.local_transcription_model'), 'medium')
        self.assertEqual(
            config.get('analysis.cloud_transcription.base_url'), 'https://api.openai.com/v1'
        )
        self.assertEqual(config.get('analysis.cloud_transcription.model'), 'whisper-1')
        self.assertEqual(config.get('analysis.cloud_transcription.api_key'), '')
        self.assertEqual(config.get('ai.api_key'), '')
        self.assertEqual(config.get('bilibili.owner_uid'), '')

    def test_old_owner_only_setting_survives_default_merge(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'config.json'
            path.write_text(
                json.dumps({'interaction': {'reply_only_owner': True}}),
                encoding='utf-8',
            )
            config = ConfigManager(path)
            from utils.reply_scope import REPLY_SCOPE_OWNER, resolve_reply_scope
            self.assertEqual(resolve_reply_scope(config), REPLY_SCOPE_OWNER)


if __name__ == '__main__':
    unittest.main()
