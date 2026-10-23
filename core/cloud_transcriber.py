"""Cloud speech-to-text through an OpenAI-compatible transcription endpoint."""

import asyncio
import subprocess
from pathlib import Path
from typing import Optional

import requests
from loguru import logger

from utils.subprocess_helpers import hidden_window_kwargs


class CloudAudioTranscriber:
    """Extract audio with ffmpeg, then upload it to a Whisper-compatible API."""

    def __init__(
        self,
        base_url: str = 'https://api.openai.com/v1',
        api_key: str = '',
        model: str = 'whisper-1',
        timeout: float = 180.0,
    ):
        self.base_url = (base_url or '').rstrip('/')
        self.api_key = (api_key or '').strip()
        self.model = model or 'whisper-1'
        self.timeout = timeout

    async def transcribe_url(
        self,
        audio_url: str,
        output_path: str,
        ffmpeg_path: str = 'ffmpeg',
        max_seconds: int = 900,
    ) -> Optional[str]:
        """Decode the audio stream to a small MP3 and send it to the API."""
        return await asyncio.to_thread(
            self._transcribe_sync, audio_url, Path(output_path), ffmpeg_path, max_seconds
        )

    def _transcribe_sync(
        self, audio_url: str, output_path: Path, ffmpeg_path: str, max_seconds: int
    ) -> Optional[str]:
        if not self.api_key:
            raise RuntimeError('未配置云端语音转写 API Key')
        if not self.base_url:
            raise RuntimeError('未配置云端语音转写接口地址')
        output_path.parent.mkdir(parents=True, exist_ok=True)
        headers = "Referer: https://www.bilibili.com/\r\nUser-Agent: Mozilla/5.0\r\n"
        # 48 kbps mono MP3 keeps a 15-minute clip under 6 MB for API limits.
        command = [
            ffmpeg_path, '-hide_banner', '-loglevel', 'error', '-nostdin', '-y',
            '-headers', headers, '-i', audio_url, '-vn', '-t', str(max_seconds),
            '-ac', '1', '-ar', '16000', '-b:a', '48k', str(output_path),
        ]
        try:
            result = subprocess.run(
                command, capture_output=True, timeout=max_seconds + 60, check=False,
                **hidden_window_kwargs(),
            )
            if result.returncode != 0 or not output_path.exists() or output_path.stat().st_size == 0:
                detail = result.stderr.decode(errors='replace')[-500:]
                raise RuntimeError(f'ffmpeg音频解码失败: {detail}')
            return self._post_audio(output_path)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError('云端语音转写音频提取超时') from exc
        finally:
            output_path.unlink(missing_ok=True)

    def _post_audio(self, output_path: Path) -> Optional[str]:
        url = f"{self.base_url}/audio/transcriptions"
        auth_headers = {'Authorization': f'Bearer {self.api_key}'}
        base_data = {'model': self.model, 'language': 'zh'}

        def send(data: dict):
            with open(output_path, 'rb') as handle:
                files = {'file': (output_path.name, handle, 'audio/mpeg')}
                return requests.post(
                    url, headers=auth_headers, files=files, data=data, timeout=self.timeout
                )

        response = send({**base_data, 'response_format': 'json'})
        if response.status_code == 400:
            # Some compatible endpoints reject language/response_format.
            response = send(base_data)
        if response.status_code >= 400:
            detail = (response.text or '')[:300]
            raise RuntimeError(f'云端语音转写失败: HTTP {response.status_code} {detail}')
        try:
            payload = response.json()
        except ValueError as exc:
            raise RuntimeError('云端语音转写返回了无法解析的内容') from exc
        text = (payload.get('text') or '').strip()
        if not text:
            logger.warning('云端语音识别未检测到可用语音')
            return None
        logger.info(f'云端语音转写完成，文本长度: {len(text)}')
        return text
