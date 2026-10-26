import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, Mock, patch

from core.ai_client import AIClient, AIProvider
from core.audio_transcriber import LocalAudioTranscriber
from core.frame_analyzer import FrameAnalyzer
from core.video_analyzer import VideoAnalyzer


class MediaAnalysisTests(unittest.IsolatedAsyncioTestCase):
    def test_duration_parser_supports_search_result_format(self):
        self.assertEqual(FrameAnalyzer._duration_seconds('12:34'), 754)
        self.assertEqual(FrameAnalyzer._duration_seconds('1:02:03'), 3723)
        self.assertIsNone(FrameAnalyzer._duration_seconds('unknown'))

    async def test_frame_extractor_samples_multiple_frames_and_caps_count(self):
        analyzer = FrameAnalyzer()
        analyzer.ffmpeg_path = 'ffmpeg'
        with tempfile.TemporaryDirectory() as directory:
            def fake_run(command, **_kwargs):
                Path(command[-1]).write_bytes(b'jpeg')
                return Mock(returncode=0, stderr=b'')

            with patch('core.frame_analyzer.subprocess.run', side_effect=fake_run) as run:
                frames = await analyzer.extract_frames(
                    'https://video.example/stream', directory, count=99, duration='00:10'
                )
            self.assertEqual(len(frames), 5)
            self.assertEqual(run.call_count, 5)
            self.assertTrue(all(Path(frame).exists() for frame in frames))

    async def test_local_transcriber_decodes_then_uses_local_model(self):
        class FakeModel:
            def transcribe(self, _audio_path, **_kwargs):
                return ([Mock(text=' 本地识别文本 ')], Mock())

        transcriber = LocalAudioTranscriber()
        with tempfile.TemporaryDirectory() as directory:
            wav_path = Path(directory) / 'audio.wav'

            def fake_ffmpeg(command, **_kwargs):
                Path(command[-1]).write_bytes(b'wav')
                return Mock(returncode=0, stderr=b'')

            with patch('core.audio_transcriber.subprocess.run', side_effect=fake_ffmpeg), \
                    patch.object(transcriber, '_get_model', return_value=FakeModel()):
                result = await transcriber.transcribe_url(
                    'https://video.example/audio', str(wav_path)
                )
            self.assertEqual(result, '本地识别文本')
            self.assertFalse(wav_path.exists())

    async def test_vision_request_attaches_compressed_frame(self):
        client = AIClient.__new__(AIClient)
        client.provider = AIProvider.DEEPSEEK
        client.model = 'deepseek-flash'
        client.client = Mock()
        client.client.chat.completions.create.return_value.choices = [
            Mock(message=Mock(content='画面分析结果'))
        ]
        with tempfile.TemporaryDirectory() as directory:
            image = Path(directory) / 'frame.png'
            from PIL import Image
            Image.new('RGB', (20, 20), 'blue').save(image)
            result = await client._chat_with_images('分析画面', [str(image)])
        self.assertEqual(result, '画面分析结果')
        sent_content = client.client.chat.completions.create.call_args.kwargs['messages'][1]['content']
        self.assertEqual(sent_content[-1]['type'], 'image_url')
        self.assertTrue(sent_content[-1]['image_url']['url'].startswith('data:image/jpeg;base64,'))

    async def test_frames_are_attached_even_when_subtitles_exist(self):
        analyzer = VideoAnalyzer.__new__(VideoAnalyzer)
        analyzer.config = Mock()
        analyzer.config.get = lambda key, default=None: default
        analyzer.enable_frame_analysis = True
        analyzer.bili = Mock()
        analyzer.bili.get_subtitle = AsyncMock(return_value='现成字幕')
        analyzer.bili.get_media_urls = AsyncMock(return_value={
            'audio': 'audio-url', 'video': 'video-url'
        })
        analyzer.bili.get_comments = AsyncMock(return_value=[])
        analyzer.frame_analyzer = Mock()
        analyzer.frame_analyzer.ffmpeg_available = True
        analyzer.frame_analyzer.extract_frames = AsyncMock(return_value=['frame.jpg'])
        analyzer.local_transcriber = Mock()
        analyzer.ai = Mock()
        analyzer.ai.analyze_video = AsyncMock(return_value={
            'score': 12, 'worthy': False, 'confidence': 'medium'
        })
        analyzer._load_persona = lambda: ''
        with patch('core.video_analyzer.tempfile.TemporaryDirectory') as tempdir:
            tempdir.return_value.name = 'temp-frames'
            tempdir.return_value.cleanup = Mock()
            result = await analyzer._analyze_video({
                'bvid': 'BV123', 'aid': 1, 'title': '有字幕视频', 'duration': '00:30'
            })
        self.assertEqual(result['score'], 12)
        self.assertEqual(analyzer.ai.analyze_video.call_args.kwargs['image_paths'], ['frame.jpg'])

    def test_visual_only_analysis_is_blocked_from_public_commenting(self):
        analyzer = VideoAnalyzer.__new__(VideoAnalyzer)
        config = Mock()
        config.get = lambda key, default=None: {
            'interaction.auto_comment': True,
            'limits.min_score_to_comment': 10,
        }.get(key, default)
        analyzer.config = config
        analyzer.ai = Mock()
        analyzer.bili = Mock()
        analyzer.db = Mock()
        import asyncio
        result = asyncio.run(analyzer._post_comment_for_video(
            {'bvid': 'BV123', 'aid': 1, 'title': '仅画面视频'},
            {'score': 20, 'confidence': 'low', 'summary': '画面有趣'},
        ))
        self.assertFalse(result)
        analyzer.bili.post_comment.assert_not_called()


if __name__ == '__main__':
    unittest.main()
