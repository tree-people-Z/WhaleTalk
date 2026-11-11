import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from core import self_evolution
from core.self_evolution import (
    learn,
    parse_items,
    record_growth_usage,
    render_growth_context,
)
from utils.config_manager import ConfigManager
from utils.database import Database
from utils.db_models import GrowthItem


class _FakeAI:
    def __init__(self, payload):
        self.payload = payload
        self.calls = 0

    async def chat(self, *_args, **_kwargs):
        self.calls += 1
        return json.dumps({'items': self.payload}, ensure_ascii=False)


class EvolutionStorageTests(unittest.TestCase):
    def test_observed_texts_are_deduplicated(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Database(str(Path(directory) / 'growth.db'))
            try:
                self.assertEqual(
                    db.record_observed_texts(['这条评论挺有意思', '这条评论挺有意思']),
                    1,
                )
                self.assertEqual(
                    db.record_observed_texts(['这条评论挺有意思']), 0
                )
                rows = db.get_observed_texts()
                self.assertEqual(rows[0]['seen_count'], 3)
            finally:
                db.close()

    def test_growth_upsert_counts_and_usage(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Database(str(Path(directory) / 'growth.db'))
            try:
                item_id = db.upsert_growth_item(
                    'language', '绷不住了', '忍不住笑出来', '我绷不住了'
                )
                self.assertIsNotNone(item_id)
                # 重复学习只加权重，不新增
                db.upsert_growth_item(
                    'language', '绷不住了', '忍不住笑出来', '我绷不住了'
                )
                self.assertEqual(len(db.get_growth_items()), 1)
                self.assertEqual(db.growth_counts(), {'language': 1})
                db.mark_growth_used([item_id])
                item = db.get_growth_items()[0]
                self.assertEqual(item['use_count'], 1)
            finally:
                db.close()

    def test_decay_and_prune(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Database(str(Path(directory) / 'growth.db'))
            try:
                db.upsert_growth_item('language', '旧梗', '很久没用了')
                db.upsert_growth_item('language', '新梗', '刚学会')
                old = db.session.query(GrowthItem).filter_by(
                    title='旧梗'
                ).first()
                old.created_at = datetime.now() - timedelta(days=30)
                old.last_used_at = datetime.now() - timedelta(days=30)
                old.weight = 8
                db.session.commit()

                self.assertEqual(db.decay_growth_items(days=14, amount=8), 1)
                self.assertEqual(
                    [item['title'] for item in db.get_growth_items()],
                    ['新梗'],
                )

                for index in range(70):
                    db.upsert_growth_item('knowledge', f'知识{index}', '内容')
                db.prune_growth_items(max_items=10)
                self.assertLessEqual(len(db.get_growth_items(limit=100)), 10)
            finally:
                db.close()


class EvolutionParseTests(unittest.TestCase):
    def test_filters_invalid_items(self):
        payload = {
            'items': [
                {'kind': 'language', 'title': '绷不住了', 'content': '忍不住笑'},
                {'kind': 'unknown', 'title': '无效', 'content': 'x'},
                {'kind': 'language', 'title': '联系我', 'content': '微信 13800138000'},
                {'kind': 'knowledge', 'title': '链接', 'content': 'https://example.com'},
                {'kind': 'language', 'title': '绷不住了', 'content': '重复'},
                {'kind': 'interest', 'title': '技术教程', 'content': '喜欢讲原理的'},
            ]
        }
        items = parse_items(json.dumps(payload, ensure_ascii=False))
        self.assertEqual(
            [item['title'] for item in items], ['绷不住了', '技术教程']
        )

    def test_parse_handles_fenced_json(self):
        text = '```json\n{"items":[{"kind":"value","title":"别急","content":"慢慢来"}]}\n```'
        self.assertEqual(parse_items(text)[0]['title'], '别急')


class EvolutionLearnTests(unittest.IsolatedAsyncioTestCase):
    async def test_learn_stores_items_and_writes_state(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            db = Database(str(root / 'growth.db'))
            config = ConfigManager(root / 'config.json')
            try:
                db.record_observed_texts(['这句「绷不住了」最近好多人在用'])
                ai = _FakeAI([
                    {
                        'kind': 'language',
                        'title': '绷不住了',
                        'content': '忍不住笑出来',
                        'example': '这视频我绷不住了',
                    }
                ])
                with patch.object(self_evolution, 'STATE_FILE', root / 'state.json'), \
                        patch.object(self_evolution, 'GROWTH_FILE', root / 'growth.md'):
                    result = await learn(ai, db, config, force=True)
                    self.assertEqual(result['added'], 1)
                    self.assertTrue((root / 'growth.md').is_file())
                    self.assertEqual(len(db.get_growth_items()), 1)

                    # 未到间隔时自动跳过
                    skipped = await learn(ai, db, config)
                    self.assertEqual(skipped.get('skipped'), 'interval')
            finally:
                db.close()

    async def test_disabled_learning_is_skipped(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            db = Database(str(root / 'growth.db'))
            config = ConfigManager(root / 'config.json')
            config.set('evolution.enabled', False)
            try:
                result = await learn(_FakeAI([]), db, config, force=True)
                self.assertEqual(result.get('skipped'), 'disabled')
            finally:
                db.close()


class EvolutionContextTests(unittest.TestCase):
    def test_context_and_usage(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Database(str(Path(directory) / 'growth.db'))
            config = ConfigManager(Path(directory) / 'config.json')
            try:
                item_id = db.upsert_growth_item(
                    'language', '绷不住了', '忍不住笑出来', '我绷不住了'
                )
                db.upsert_growth_item('interest', '技术教程', '喜欢讲原理的')
                text = render_growth_context(db, config)
                self.assertIn('绷不住了', text)
                self.assertIn('技术教程', text)
                self.assertIn('成长档案', text)

                self.assertEqual(record_growth_usage('这视频我绷不住了', db), 1)
                items = {item['id']: item for item in db.get_growth_items()}
                self.assertEqual(items[item_id]['use_count'], 1)
            finally:
                db.close()

    def test_recent_comments_used_for_style_check(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Database(str(Path(directory) / 'growth.db'))
            try:
                db.add_comment_record(
                    'BV1', 1, '哼，这个视频挺有意思', comment_type='post',
                    rpid=1,
                )
                db.add_comment_record(
                    'BV1', 1, '第二条评论', comment_type='reply',
                    rpid=2, parent_rpid=1,
                )
                recent = db.get_recent_own_comments(limit=10)
                self.assertEqual(recent[0], '第二条评论')
                self.assertIn('哼，这个视频挺有意思', recent)
            finally:
                db.close()


class GrowthUsageMatchingTests(unittest.TestCase):
    def test_example_fragment_counts_as_usage(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Database(str(Path(directory) / 'growth.db'))
            try:
                db.upsert_growth_item(
                    'language', '大米饭=token',
                    '把烧掉的 token 说成大米饭',
                    '别一崩就梭哈仨月大米饭',
                )
                used = record_growth_usage(
                    '别一崩就梭哈仨月大米饭，先看看官方返不返 token。', db
                )
                self.assertEqual(used, 1)
            finally:
                db.close()

    def test_interaction_items_are_counted_too(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Database(str(Path(directory) / 'growth.db'))
            try:
                db.upsert_growth_item(
                    'interaction', '先认再补',
                    '先说「这层我确实没点出来」，再补一句细节',
                )
                used = record_growth_usage('这层我确实没点出来，算你提醒一回。', db)
                self.assertEqual(used, 1)
            finally:
                db.close()


class GrowthContextBudgetTests(unittest.TestCase):
    def test_interaction_kept_and_knowledge_capped(self):
        with tempfile.TemporaryDirectory() as directory:
            db = Database(str(Path(directory) / 'growth.db'))
            config = ConfigManager(Path(directory) / 'config.json')
            try:
                for index in range(6):
                    db.upsert_growth_item(
                        'knowledge', f'知识点{index}', '很长的知识解释' * 8
                    )
                for index in range(3):
                    db.upsert_growth_item(
                        'interaction', f'接话经验{index}', '先认一句再补细节'
                    )
                text = render_growth_context(db, config)
                self.assertIn('互动经验', text)
                self.assertIn('接话经验0', text)
                self.assertLessEqual(
                    sum(1 for line in text.splitlines() if line.startswith('- 知识点')),
                    2,
                )
            finally:
                db.close()


if __name__ == '__main__':
    unittest.main()
