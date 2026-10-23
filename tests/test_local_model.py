import tempfile
import unittest
from pathlib import Path

from core.audio_transcriber import LocalAudioTranscriber


class LocalModelDetectionTests(unittest.TestCase):
    def test_detects_complete_manual_model_directory(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory) / 'faster-whisper'
            model = base / 'medium'
            model.mkdir(parents=True)
            for name in LocalAudioTranscriber.MODEL_FILES:
                (model / name).write_bytes(b'data')
            self.assertEqual(LocalAudioTranscriber.local_model_path(base), str(model))

    def test_returns_none_when_a_required_file_is_missing(self):
        with tempfile.TemporaryDirectory() as directory:
            base = Path(directory)
            model = base / 'medium'
            model.mkdir(parents=True)
            (model / 'config.json').write_bytes(b'data')
            self.assertIsNone(LocalAudioTranscriber.local_model_path(base))


if __name__ == '__main__':
    unittest.main()
