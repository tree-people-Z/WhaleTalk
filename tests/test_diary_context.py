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
