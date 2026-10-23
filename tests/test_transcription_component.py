import json
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

from utils import transcription_component as tc


class TranscriptionComponentTests(unittest.TestCase):
    def test_is_installed_requires_marker_and_site_packages(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with patch.object(tc, 'COMPONENT_DIR', root):
                self.assertFalse(tc.is_installed())
                (root / 'site-packages').mkdir()
                self.assertFalse(tc.is_installed())
                (root / 'component.json').write_text(
                    json.dumps({'component_version': 1}), encoding='utf-8'
                )
                self.assertTrue(tc.is_installed())
                (root / 'component.json').write_text(
                    json.dumps({'component_version': 0}), encoding='utf-8'
                )
                self.assertFalse(tc.is_installed())

    def test_ensure_importable_appends_site_packages(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / 'site-packages').mkdir()
            (root / 'component.json').write_text(
                json.dumps({'component_version': 1}), encoding='utf-8'
            )
            with patch.object(tc, 'COMPONENT_DIR', root):
                tc._PATH_READY = False
                try:
                    self.assertTrue(tc.ensure_importable())
                    self.assertIn(
                        str((root / 'site-packages').resolve()),
                        [str(Path(entry).resolve()) for entry in sys.path if entry],
                    )
                finally:
                    tc._PATH_READY = False

    def test_extract_component_rejects_path_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / 'bad.zip'
            with zipfile.ZipFile(archive, 'w') as handle:
                handle.writestr('../evil.txt', 'x')
            with patch.object(tc, 'COMPONENT_DIR', Path(tmp) / 'component'):
                with self.assertRaises(RuntimeError):
                    tc.extract_component(archive)

    def test_extract_component_unpacks_site_packages(self):
        with tempfile.TemporaryDirectory() as tmp:
            archive = Path(tmp) / 'good.zip'
            with zipfile.ZipFile(archive, 'w') as handle:
                handle.writestr('site-packages/demo_pkg/mod.py', 'value = 1')
                handle.writestr(
                    'component.json',
                    json.dumps({'component_version': 1}),
                )
            root = Path(tmp) / 'component'
            with patch.object(tc, 'COMPONENT_DIR', root):
                result = tc.extract_component(archive)
                self.assertTrue((result / 'site-packages/demo_pkg/mod.py').is_file())
                self.assertTrue(tc.is_installed())

    def test_configure_hf_endpoint_uses_mirror_when_direct_is_unreachable(self):
        with patch.dict('os.environ', {}, clear=False):
            tc.os.environ.pop('HF_ENDPOINT', None)
            with patch('requests.head', side_effect=RuntimeError('offline')):
                endpoint = tc.configure_hf_endpoint()
            self.assertEqual(endpoint, 'https://hf-mirror.com')
            self.assertEqual(tc.os.environ.get('HF_ENDPOINT'), 'https://hf-mirror.com')
            tc.os.environ.pop('HF_ENDPOINT', None)


if __name__ == '__main__':
    unittest.main()
