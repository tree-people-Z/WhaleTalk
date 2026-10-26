import asyncio
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from core import long_term_memory as memory


class FakeAI:
    async def chat(self, messages, **kwargs):
        return (
            '# 长期记忆\n\n'
            '## 一、以前发生的事件\n'
            '- 2026-10-26：和 viewer 聊了剪辑。\n\n'
            '## 二、学到的东西\n'
            '### 经验\n'
            '- 晚上回复率更高。\n'
            '### 风格\n'
            '- 少用固定开场白。\n'
        )


class LongTermMemoryTests(unittest.TestCase):
    def test_consolidates_diary_into_two_sections(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            diary_dir = root / 'diaries'
            diary_dir.mkdir()
            (diary_dir / '2026-10-26_to_owner.md').write_text(
                '# 日记\n今天和 viewer 聊了剪辑。', encoding='utf-8'
            )
            with patch.object(memory, 'DIARY_DIR', diary_dir), \
                    patch.object(memory, 'MEMORY_FILE', root / 'memory.md'), \
                    patch.object(memory, 'STATE_FILE', root / 'state.json'):
                text = asyncio.run(memory.consolidate(FakeAI(), force=True))
                self.assertIn('以前发生的事件', text)
                self.assertIn('学到的东西', text)
                self.assertIn('### 风格', text)
                self.assertTrue((root / 'memory.md').is_file())
                # Same day: no second consolidation.
                self.assertEqual(
                    asyncio.run(memory.consolidate(FakeAI())), ''
                )

    def test_invalid_output_is_not_written(self):
        class BadAI:
            async def chat(self, messages, **kwargs):
                return '随便写一段'

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            with patch.object(memory, 'DIARY_DIR', root / 'diaries'), \
                    patch.object(memory, 'MEMORY_FILE', root / 'memory.md'), \
                    patch.object(memory, 'STATE_FILE', root / 'state.json'):
                result = asyncio.run(memory.consolidate(BadAI(), force=True))
                self.assertEqual(result, '')
                self.assertFalse((root / 'memory.md').exists())


if __name__ == '__main__':
    unittest.main()
