import unittest

from core.style_guard import (
    clean_rewrite,
    find_style_issues,
    prepare_outgoing_text,
)


class _FakeAI:
    def __init__(self, reply):
        self.reply = reply
        self.calls = 0

    async def chat(self, *_args, **_kwargs):
        self.calls += 1
        return self.reply


class _FakeDB:
    def __init__(self, recent, titles=None):
        self.recent = recent
        self.titles = titles or []

    def get_recent_own_comments(self, limit=20):
        return self.recent[:limit]

    def get_growth_items(self, kinds=None, limit=40):
        return [
            {'id': index, 'title': title, 'content': ''}
            for index, title in enumerate(self.titles)
        ]


class _FakeConfig:
    def get(self, key, default=None):
        return True if key == 'evolution.anti_repetition' else default


class StyleGuardTests(unittest.IsolatedAsyncioTestCase):
    def test_detects_repeated_opener_and_catchphrase(self):
        recent = ['哼，这个不错', '哼，才不是呢', '哼，好吧']
        issues = find_style_issues('哼，这个视频真棒', recent, [])
        self.assertTrue(any('开头' in issue for issue in issues))
        self.assertTrue(any('口头禅' in issue for issue in issues))

    def test_detects_duplicate_and_term_reuse(self):
        recent = ['完全一样的内容', '我绷不住了', '我绷不住了', '我绷不住了']
        issues = find_style_issues(
            '完全一样的内容', recent, ['绷不住了']
        )
        self.assertTrue(any('几乎一样' in issue for issue in issues))
        issues = find_style_issues('绷不住了哈哈', recent, ['绷不住了'])
        self.assertTrue(any('刚学到' in issue for issue in issues))

    def test_clean_rewrite_rejects_short_or_lost_mention(self):
        original = '@主人 这个视频讲得真好'
        self.assertEqual(clean_rewrite('太短', original), original)
        self.assertEqual(clean_rewrite('这个视频讲得真好', original), original)
        self.assertEqual(
            clean_rewrite('@主人 这个镜头切得真稳', original),
            '@主人 这个镜头切得真稳',
        )

    async def test_no_issue_does_not_call_model(self):
        ai = _FakeAI('不会用到')
        result = await prepare_outgoing_text(
            ai, _FakeDB(['完全不同的内容']), _FakeConfig(), '一个全新的评论'
        )
        self.assertEqual(result, '一个全新的评论')
        self.assertEqual(ai.calls, 0)

    async def test_issue_triggers_one_rewrite(self):
        ai = _FakeAI('这镜头切得真稳，我盯着看了两遍。')
        result = await prepare_outgoing_text(
            ai,
            _FakeDB(['哼，这个不错', '哼，才不是呢', '哼，好吧']),
            _FakeConfig(),
            '哼，这个视频真棒',
        )
        self.assertEqual(result, '这镜头切得真稳，我盯着看了两遍。')
        self.assertEqual(ai.calls, 1)


if __name__ == '__main__':
    unittest.main()
