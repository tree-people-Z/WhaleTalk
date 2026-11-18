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


class ModelReleaseTests(unittest.TestCase):
    def setUp(self):
        import time
        self._saved = (
            LocalAudioTranscriber._model,
            LocalAudioTranscriber._model_name,
            LocalAudioTranscriber._last_used,
        )
        LocalAudioTranscriber._model = object()
        LocalAudioTranscriber._model_name = 'tiny'
        LocalAudioTranscriber._last_used = time.time()

    def tearDown(self):
        (
            LocalAudioTranscriber._model,
            LocalAudioTranscriber._model_name,
            LocalAudioTranscriber._last_used,
        ) = self._saved

    def test_release_now_drops_model_immediately(self):
        self.assertTrue(LocalAudioTranscriber.release_now('测试释放'))
        self.assertIsNone(LocalAudioTranscriber._model)

    def test_release_if_idle_keeps_recently_used_model(self):
        self.assertFalse(LocalAudioTranscriber.release_if_idle(60))
        self.assertIsNotNone(LocalAudioTranscriber._model)

    def test_release_if_idle_drops_model_after_window(self):
        LocalAudioTranscriber._last_used -= 120
        self.assertTrue(LocalAudioTranscriber.release_if_idle(15))
        self.assertIsNone(LocalAudioTranscriber._model)
