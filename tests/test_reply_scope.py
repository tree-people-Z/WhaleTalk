import unittest

from core.comment_manager import CommentManager
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

    def test_all_scope_enables_broad_behaviour(self):
        config = Config()
        apply_reply_scope(config, REPLY_SCOPE_ALL)
        self.assertEqual(config.get('interaction.reply_scope'), REPLY_SCOPE_ALL)

    def test_resolve_migrates_old_config(self):
        config = Config({'interaction.reply_only_owner': True})
        self.assertEqual(resolve_reply_scope(config), REPLY_SCOPE_OWNER)
        config = Config({})
        self.assertEqual(resolve_reply_scope(config), REPLY_SCOPE_ALL)


class OwnerEventTests(unittest.TestCase):
    def test_matches_owner_by_uid_or_name(self):
        check = CommentManager._is_owner_event
        self.assertTrue(check({'mid': 42}, '', '42'))
        self.assertTrue(check({'user': '主人'}, '主人', '42'))
        self.assertFalse(check({'mid': 7, 'user': 'viewer'}, '主人', '42'))


if __name__ == '__main__':
    unittest.main()
