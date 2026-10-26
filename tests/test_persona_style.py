import datetime
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from utils import persona_evolution as pe


class PersonaStyleTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.core = self.root / 'persona.md'
        self.style = self.root / 'persona_style.md'
        self.core.write_text('# 核心\n我是鲸鱼娘。', encoding='utf-8')
        self.versions = self.root / 'versions'
        self.state = self.root / 'state.json'
        self.patches = [
            patch.object(pe, 'VERSIONS_DIR', self.versions),
            patch.object(pe, 'STATE_FILE', self.state),
        ]
        for item in self.patches:
            item.start()

    def tearDown(self):
        for item in reversed(self.patches):
            item.stop()
        self.temp.cleanup()

    def test_compose_core_and_style(self):
        self.style.write_text('- 偶尔先问一句\n', encoding='utf-8')
        text = pe.load_effective_persona(self.core, self.style)
        self.assertIn('我是鲸鱼娘', text)
        self.assertIn('偶尔先问一句', text)

    def test_validate_style_rejects_headings_and_identity(self):
        with self.assertRaises(RuntimeError):
            pe.validate_style('# 我是AI')
        with self.assertRaises(RuntimeError):
            pe.validate_style('- 我是AI，不是鲸鱼娘')
        self.assertEqual(
            pe.validate_style('- 偶尔先问一句\n- 少用固定开场白'),
            '- 偶尔先问一句\n- 少用固定开场白',
        )

    def test_apply_replaces_style_and_rollback(self):
        self.style.write_text('- 旧风格\n', encoding='utf-8')
        pe.apply_style('- 新风格\n', style_path=self.style)
        self.assertEqual(pe.load_style(self.style), '- 新风格')
        pe.rollback_style(self.style, reason='test')
        self.assertEqual(pe.load_style(self.style), '- 旧风格')

    def test_health_check_rolls_back_on_failures(self):
        self.style.write_text('- 旧风格\n', encoding='utf-8')
        pe.apply_style('- 新风格\n', style_path=self.style)
        state = pe.read_state()
        state['eval_until'] = (
            datetime.datetime.now() - datetime.timedelta(hours=1)
        ).isoformat()
        pe.write_state(state)

        class FakeDB:
            def get_comment_outcomes_since(self, since):
                return [
                    {'success': False, 'error': '412'},
                    {'success': False, 'error': '412'},
                    {'success': False, 'error': '412'},
                    {'success': False, 'error': '12014'},
                    {'success': True, 'error': ''},
                ]

        message = pe.evaluate_style_health(FakeDB(), self.style)
        self.assertIn('回滚', message)
        self.assertEqual(pe.load_style(self.style), '- 旧风格')


if __name__ == '__main__':
    unittest.main()
