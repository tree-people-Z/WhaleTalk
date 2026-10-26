import unittest

from utils.reply_scope import (
    REPLY_SCOPE_ALL,
    REPLY_SCOPE_OWNER,
    apply_reply_scope,
    resolve_reply_scope,
)


class Config(dict):
    def get(self, key, default=None):
        return dict.get(self, key, default)

    def set(self, key, value):
        self[key] = value


class ReplyScopeTests(unittest.TestCase):
    def test_owner_scope_disables_broad_behaviour(self):
        config = Config()
        apply_reply_scope(config, REPLY_SCOPE_OWNER)
        self.assertEqual(config.get('interaction.reply_scope'), REPLY_SCOPE_OWNER)
        self.assertTrue(config.get('interaction.reply_only_owner'))
        self.assertFalse(config.get('interaction.reply_to_others'))
        self.assertFalse(config.get('interaction.reply_interesting_comments'))
        self.assertFalse(config.get('interaction.greet_other_whales'))
        self.assertFalse(config.get('interaction.comment_requested_video'))
        self.assertFalse(config.get('interaction.reply_own_video_comments'))

    def test_all_scope_enables_broad_behaviour(self):
        config = Config()
        apply_reply_scope(config, REPLY_SCOPE_ALL)
        self.assertEqual(config.get('interaction.reply_scope'), REPLY_SCOPE_ALL)
        self.assertFalse(config.get('interaction.reply_only_owner'))
        self.assertTrue(config.get('interaction.reply_to_others'))
        self.assertTrue(config.get('interaction.reply_interesting_comments'))
        self.assertTrue(config.get('interaction.greet_other_whales'))
        self.assertTrue(config.get('interaction.comment_requested_video'))
        self.assertTrue(config.get('interaction.reply_own_video_comments'))

    def test_resolve_migrates_old_config(self):
        config = Config({'interaction.reply_only_owner': True})
        self.assertEqual(resolve_reply_scope(config), REPLY_SCOPE_OWNER)
        config = Config({})
        self.assertEqual(resolve_reply_scope(config), REPLY_SCOPE_ALL)


if __name__ == '__main__':
    unittest.main()
