import asyncio
import tempfile
import unittest
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from core import diary_maintenance, self_evolution
from core.diary_maintenance import (
    backup,
    compact_diaries,
    digest,
    ran_today,
    select_files,
    write_state,
)
from utils.config_manager import ConfigManager
from utils.database import Database
from utils.db_models import GrowthItem


class _FakeConfig:
    def __init__(self, values=None):
        self.values = values or {}

    def get(self, key, default=None):
        return self.values.get(key, default)


class _FakeAI:
    def __init__(self, reply):
        self.reply = reply
        self.calls = 0

    async def chat(self, *_args, **_kwargs):
        self.calls += 1
        return self.reply


SUMMARY = (
    '尾巴搭在椅背上，今天把《测试》发出去了，主人拍了一下说还行。'
    '翻投稿的时候记下一句：先给时间点，别拿今天谁火倒推。'
    '零播太多，短的跳、长的也跳，翻到后面有点烦，收工。'
) * 2


def _write_diary(directory: Path, day: date, multiply: int = 20) -> Path:
    path = directory / f'{day.isoformat()}.md'
    body = ''.join(
        f'## {day} 第{i}趟\n\n尾巴凉。\n\n- 《片子{i}》14/20，点赞留言，没@主人。\n\n'
        '这轮写操作三次，数着花的，没超额。\n\n'
        '审计：最高分 14/20；@主人 否。\n\n'
        for i in range(multiply)
    )
    path.write_text(body, encoding='utf-8')
    return path


class DigestTests(unittest.TestCase):
    def test_noise_and_boilerplate_are_dropped(self):
        text = (
            '## 时间\n\n尾巴暖了，今天想通一件事。\n\n'
            '- 《新片》17/20，点赞留言并@主人，记下改稿顺序。\n'
            '- @消息空，评论额度没被卡。\n\n'
            '这轮写操作三次（两赞一评＋日记）。\n\n'
            '审计：最高分 17/20；@主人 是。\n'
        )
        material = digest(text)
        self.assertIn('尾巴暖了，今天想通一件事', material)
        self.assertIn('《新片》', material)
        self.assertNotIn('审计：', material)
        self.assertNotIn('这轮写操作', material)

    def test_boilerplate_kept_when_owner_really_talked(self):
        text = '## 时间\n\n主人夸我这次排版干净，白饭都多盛了半碗。\n'
        material = digest(text)
        self.assertIn('主人夸我', material)


class SelectionTests(unittest.TestCase):
    def test_only_old_and_long_files_are_selected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            old_long = _write_diary(root, date.today() - timedelta(days=5))
            _write_diary(root, date.today() - timedelta(days=1))
            short = root / f'{(date.today() - timedelta(days=6)).isoformat()}.md'
            short.write_text('## x\n\n短\n', encoding='utf-8')

            selected = select_files(root, days=3, min_chars=1200)
            self.assertEqual(selected, [old_long])

    def test_only_expression_selects_even_short_file(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            path = root / '2026-01-02.md'
            path.write_text('## 2026-01-02\n\n短\n', encoding='utf-8')
            self.assertEqual(select_files(root, only='2026-01-02'), [path])


class CompactionTests(unittest.TestCase):
    def test_compacts_and_keeps_a_backup(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            diary_dir = root / 'to_owner'
            diary_dir.mkdir()
            path = _write_diary(diary_dir, date.today() - timedelta(days=6))
            original = path.read_text(encoding='utf-8')
            config = _FakeConfig({'diaries.compact_after_days': 3,
                                  'diaries.compact_min_chars': 1200})
            ai = _FakeAI(SUMMARY)
            with patch.object(diary_maintenance, 'STATE_FILE', root / 'state.json'):
                stats = asyncio.run(compact_diaries(
                    ai, config, directory=diary_dir,
                    backup_dir=root / 'backup',
                ))
            text = path.read_text(encoding='utf-8')
            self.assertEqual(stats['files'], 1)
            self.assertEqual(stats['failed'], 0)
            self.assertLess(len(text), 1200)
            self.assertTrue(text.startswith('## '))
            backups = list((root / 'backup').glob('diaries-*.zip'))
            self.assertEqual(len(backups), 1)
            with zipfile.ZipFile(backups[0]) as archive:
                archived = archive.read(f'to_owner/{path.name}').decode('utf-8')
                self.assertEqual(
                    archived.replace(chr(13) + chr(10), chr(10)), original
                )
            self.assertTrue(ran_today(root / 'state.json'))

    def test_second_run_has_nothing_to_do(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            diary_dir = root / 'to_owner'
            diary_dir.mkdir()
            _write_diary(diary_dir, date.today() - timedelta(days=6))
            config = _FakeConfig({'diaries.compact_after_days': 3,
                                  'diaries.compact_min_chars': 1200})
            with patch.object(diary_maintenance, 'STATE_FILE', root / 'state.json'):
                asyncio.run(compact_diaries(
                    _FakeAI(SUMMARY), config, directory=diary_dir,
                    backup_dir=root / 'backup',
                ))
                again = asyncio.run(compact_diaries(
                    _FakeAI(SUMMARY), config, directory=diary_dir,
                    backup_dir=root / 'backup',
                ))
            self.assertEqual(again['files'], 0)

    def test_failed_summary_keeps_original(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            diary_dir = root / 'to_owner'
            diary_dir.mkdir()
            path = _write_diary(diary_dir, date.today() - timedelta(days=6))
            original = path.read_text(encoding='utf-8')
            config = _FakeConfig({'diaries.compact_after_days': 3,
                                  'diaries.compact_min_chars': 1200})
            with patch.object(diary_maintenance, 'STATE_FILE', root / 'state.json'):
                stats = asyncio.run(compact_diaries(
                    _FakeAI(''), config, directory=diary_dir,
                    backup_dir=root / 'backup',
                ))
            self.assertEqual(stats['failed'], 1)
            self.assertEqual(path.read_text(encoding='utf-8'), original)

    def test_dry_run_changes_nothing(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            diary_dir = root / 'to_owner'
            diary_dir.mkdir()
            path = _write_diary(diary_dir, date.today() - timedelta(days=6))
            original = path.read_text(encoding='utf-8')
            config = _FakeConfig({'diaries.compact_after_days': 3,
                                  'diaries.compact_min_chars': 1200})
            with patch.object(diary_maintenance, 'STATE_FILE', root / 'state.json'):
                asyncio.run(compact_diaries(
                    _FakeAI(SUMMARY), config, dry_run=True,
                    directory=diary_dir, backup_dir=root / 'backup',
                ))
            self.assertEqual(path.read_text(encoding='utf-8'), original)
            self.assertFalse((root / 'backup').exists())


class BackupRetentionTests(unittest.TestCase):
    def test_old_archives_are_pruned(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / 'to_owner'
            source.mkdir()
            path = source / '2026-01-01.md'
            path.write_text('内容', encoding='utf-8')
            backup_dir = root / 'backup'
            backup_dir.mkdir()
            for index in range(5):
                (backup_dir / f'diaries-2026010{index}-000000.zip').write_bytes(b'')
            backup([path], backup_dir, keep=3)
            self.assertEqual(len(list(backup_dir.glob('diaries-*.zip'))), 3)


class HousekeepingTests(unittest.TestCase):
    def _db_with_old_item(self, directory: Path):
        db = Database(str(directory / 'growth.db'))
        db.upsert_growth_item('language', '旧梗', '很久没用了')
        db.upsert_growth_item('language', '新梗', '刚学会')
        old = db.session.query(GrowthItem).filter_by(title='旧梗').first()
        old.created_at = datetime.now() - timedelta(days=30)
        old.last_used_at = datetime.now() - timedelta(days=30)
        old.weight = 8
        db.session.commit()
        return db

    def test_decays_once_per_day(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            db = self._db_with_old_item(root)
            config = ConfigManager(root / 'config.json')
            try:
                with patch.object(self_evolution, 'STATE_FILE', root / 'state.json'), \
                        patch.object(self_evolution, 'GROWTH_FILE', root / 'growth.md'):
                    first = self_evolution.housekeeping(db, config)
                    second = self_evolution.housekeeping(db, config)
                self.assertEqual(first.get('decayed'), 1)
                self.assertEqual(second.get('skipped'), 'interval')
                self.assertEqual(
                    [item['title'] for item in db.get_growth_items()],
                    ['新梗'],
                )
            finally:
                db.close()

    def test_state_file_records_last_run(self):
        with tempfile.TemporaryDirectory() as directory:
            state = Path(directory) / 'state.json'
            write_state({'last_run': datetime.now().isoformat()}, state)
            self.assertTrue(ran_today(state))


if __name__ == '__main__':
    unittest.main()


class NothingToDoTests(unittest.TestCase):
    def test_empty_run_still_records_last_run(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            diary_dir = root / 'to_owner'
            diary_dir.mkdir()
            config = _FakeConfig({})
            with patch.object(diary_maintenance, 'STATE_FILE', root / 'state.json'):
                stats = asyncio.run(compact_diaries(
                    _FakeAI(''), config, directory=diary_dir,
                    backup_dir=root / 'backup',
                ))
                self.assertEqual(stats['files'], 0)
                self.assertTrue(ran_today(root / 'state.json'))
