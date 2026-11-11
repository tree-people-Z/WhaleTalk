import tempfile
import unittest
from datetime import date, timedelta
from pathlib import Path
from unittest.mock import patch

from core import free_context, long_term_memory
from utils.config_manager import ConfigManager
from utils.database import Database


class DiaryContextTests(unittest.TestCase):
    def test_recent_diaries_keep_each_day_and_latest_tail(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            today = date.today()
            for offset in range(3):
                day = today - timedelta(days=offset)
                (root / f'{day.isoformat()}.md').write_text(
                    f'{day} 开头\n' + ('内容' * 3000) + f'\n{day} 结尾',
                    encoding='utf-8',
                )
            with patch.object(free_context, 'DIARY_DIR', root):
                text = free_context.load_recent_diaries(3, 9000)
            for offset in range(3):
                day = today - timedelta(days=offset)
                self.assertIn(day.isoformat(), text)
                self.assertIn(f'{day} 结尾', text)
            self.assertLessEqual(len(text), 9000)

    def test_append_diary_caps_single_entry(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(free_context, 'DIARY_DIR', root):
                path = free_context.append_diary('字' * 5000)
                text = path.read_text(encoding='utf-8')
            self.assertLess(len(text), 4200)
            self.assertIn('已截断', text)

    def test_context_includes_growth_and_human_style(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            db = Database(str(root / 'growth.db'))
            config = ConfigManager(root / 'config.json')
            try:
                db.upsert_growth_item(
                    'language', '绷不住了', '忍不住笑出来', '我绷不住了'
                )
                db.upsert_growth_item('interest', '技术教程', '喜欢讲原理的')
                with patch.object(free_context, 'DIARY_DIR', root / 'diaries'):
                    context = free_context.build_agent_context(config, db=db)
                self.assertIn('成长档案', context)
                self.assertIn('绷不住了', context)
                self.assertIn('说话方式', context)
            finally:
                db.close()


class LongTermMemoryDiaryTests(unittest.TestCase):
    def test_prefers_free_form_diary_and_reads_both_patterns(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            day = date.today()
            (root / f'{day.isoformat()}.md').write_text('自由格式日记', encoding='utf-8')
            (root / f'{day.isoformat()}_to_owner.md').write_text(
                '旧格式日记', encoding='utf-8'
            )
            with patch.object(long_term_memory, 'DIARY_DIR', root):
                rows = long_term_memory._new_diaries(None)
            self.assertEqual(len(rows), 1)
            self.assertIn('自由格式日记', rows[0][1])
            self.assertNotIn('旧格式日记', rows[0][1])

    def test_reads_old_suffix_when_only_old_diary_exists(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            day = date.today() - timedelta(days=1)
            (root / f'{day.isoformat()}_to_owner.md').write_text(
                '旧格式日记', encoding='utf-8'
            )
            with patch.object(long_term_memory, 'DIARY_DIR', root):
                rows = long_term_memory._new_diaries(None)
            self.assertEqual(len(rows), 1)
            self.assertIn('旧格式日记', rows[0][1])


if __name__ == '__main__':
    unittest.main()


class MemoryFallbackTests(unittest.IsolatedAsyncioTestCase):
    async def test_consolidation_falls_back_when_model_returns_nothing(self):
        from core import long_term_memory as memory
        from core.long_term_memory import consolidate

        class _EmptyAI:
            async def chat(self, *_args, **_kwargs):
                return ''

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            diary_dir = root / 'diaries'
            diary_dir.mkdir()
            today = date.today()
            (diary_dir / f'{today.isoformat()}.md').write_text(
                '# 今天\n下午看了两个视频，讲得清楚，点赞留言了。',
                encoding='utf-8',
            )
            with patch.object(memory, 'DIARY_DIR', diary_dir), \
                    patch.object(memory, 'MEMORY_FILE', root / 'memory.md'), \
                    patch.object(memory, 'STATE_FILE', root / 'state.json'):
                result = await consolidate(_EmptyAI(), force=True)
                self.assertIn(today.isoformat(), result)
                self.assertIn('## 二、学到的东西', result)
                self.assertIn(today.isoformat(), (root / 'memory.md').read_text(
                    encoding='utf-8'
                ))
                import json
                state = json.loads((root / 'state.json').read_text(encoding='utf-8'))
                self.assertEqual(state['last_consolidated'], today.isoformat())


class DiaryLimitTests(unittest.TestCase):
    def test_diary_allows_only_three_entries_per_day(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(free_context, 'DIARY_DIR', root):
                for i in range(free_context.MAX_DIARY_ENTRIES_PER_DAY):
                    free_context.append_diary(f'## 第{i}条\n今天有点事。')
                with self.assertRaises(ValueError):
                    free_context.append_diary('## 第四条\n还想写。')

    def test_diary_rejects_when_day_is_full(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(free_context, 'DIARY_DIR', root):
                free_context.append_diary('## 一\n' + '字' * 3000)
                with self.assertRaises(ValueError):
                    free_context.append_diary('## 二\n' + '字' * 2000)


class VoiceSampleTests(unittest.TestCase):
    def test_voice_samples_skip_at_short_and_report_lines(self):
        class _DB:
            def get_recent_own_comments(self, limit=20):
                return [
                    '@Tree-people 这条像在跟我说话，先接一句',
                    '短',
                    '这轮写操作三次，审计最高分 17/20',
                    '尾巴都替她拍手了，嘴上讲攻略手先护住自己的位置。',
                ]

        samples = free_context.load_voice_samples(_DB())
        self.assertEqual(samples, ['尾巴都替她拍手了，嘴上讲攻略手先护住自己的位置。'])

    def test_context_contains_voice_samples_and_diary_rules(self):
        class _DB:
            def get_recent_own_comments(self, limit=20):
                return ['这句我听懂了，先认一半再慢慢补剩下的那半。']

            def get_growth_items(self, kinds=None, limit=60):
                return []

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            config = ConfigManager(root / 'config.json')
            context = free_context.build_agent_context(config, db=_DB())
        self.assertIn('你最近在评论区说过的话', context)
        self.assertIn('先认一半', context)
        self.assertIn('日记怎么写', context)
        self.assertIn('一天最多 3 条', context)


class DiaryNoiseFilterTests(unittest.TestCase):
    def test_audit_and_write_count_lines_are_dropped(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            root.mkdir(exist_ok=True)
            today = date.today().isoformat()
            (root / f'{today}.md').write_text(
                '## 时间\n看了两个视频，笑到尾巴打结。\n\n'
                '这轮写操作三次（一赞一评＋日记），数着花的。\n\n'
                '审计：最高分 15/20；@主人 是。\n',
                encoding='utf-8',
            )
            with patch.object(free_context, 'DIARY_DIR', root):
                text = free_context.load_recent_diaries(1, 2000)
        self.assertIn('笑到尾巴打结', text)
        self.assertNotIn('审计：', text)
        self.assertNotIn('这轮写操作', text)
