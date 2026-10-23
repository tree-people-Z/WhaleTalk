import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from core.cloud_transcriber import CloudAudioTranscriber


def _fake_ffmpeg(command, **_kwargs):
    Path(command[-1]).write_bytes(b'mp3')
    return Mock(returncode=0, stderr=b'')


class CloudTranscriberTests(unittest.TestCase):
    def test_transcribes_audio_with_bearer_token(self):
        transcriber = CloudAudioTranscriber(
            base_url='https://api.example.com/v1', api_key='sk-test', model='whisper-1'
        )
        response = Mock(status_code=200)
        response.json.return_value = {'text': ' 你好世界 '}
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'audio.mp3'
            with patch('core.cloud_transcriber.subprocess.run', side_effect=_fake_ffmpeg), \
                    patch('core.cloud_transcriber.requests.post', return_value=response) as post:
                text = transcriber._transcribe_sync(
                    'https://example.test/audio', output, 'ffmpeg', 60
                )
        self.assertEqual(text, '你好世界')
        kwargs = post.call_args.kwargs
        self.assertEqual(kwargs['headers']['Authorization'], 'Bearer sk-test')
        self.assertEqual(kwargs['data']['model'], 'whisper-1')
        self.assertIn('file', kwargs['files'])

    def test_missing_api_key_raises_before_decoding(self):
        transcriber = CloudAudioTranscriber(api_key='')
        with self.assertRaises(RuntimeError):
            transcriber._transcribe_sync('u', Path('x.mp3'), 'ffmpeg', 10)

    def test_retries_without_optional_fields_on_bad_request(self):
        transcriber = CloudAudioTranscriber(
            base_url='https://api.example.com/v1', api_key='sk-test'
        )
        bad = Mock(status_code=400, text='bad request')
        good = Mock(status_code=200)
        good.json.return_value = {'text': '重试成功'}
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'audio.mp3'
            with patch('core.cloud_transcriber.subprocess.run', side_effect=_fake_ffmpeg), \
                    patch('core.cloud_transcriber.requests.post', side_effect=[bad, good]) as post:
                text = transcriber._transcribe_sync(
                    'https://example.test/audio', output, 'ffmpeg', 60
                )
        self.assertEqual(text, '重试成功')
        self.assertEqual(post.call_count, 2)
        self.assertNotIn('response_format', post.call_args.kwargs['data'])

    def test_http_error_is_reported(self):
        transcriber = CloudAudioTranscriber(
            base_url='https://api.example.com/v1', api_key='sk-test'
        )
        response = Mock(status_code=500, text='server error')
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / 'audio.mp3'
            with patch('core.cloud_transcriber.subprocess.run', side_effect=_fake_ffmpeg), \
                    patch('core.cloud_transcriber.requests.post', return_value=response):
                with self.assertRaises(RuntimeError) as context:
                    transcriber._transcribe_sync(
                        'https://example.test/audio', output, 'ffmpeg', 60
                    )
        self.assertIn('HTTP 500', str(context.exception))


if __name__ == '__main__':
    unittest.main()
