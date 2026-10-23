"""Local speech-to-text fallback using faster-whisper."""

import asyncio
import subprocess
import threading
from pathlib import Path
from typing import Optional

from loguru import logger


class LocalAudioTranscriber:
    """Convert a Bilibili audio stream to text locally (no audio API upload)."""

    _model = None
    _model_name = None
    _model_lock = threading.Lock()

    def __init__(self, model_name: str = 'small', model_dir: str = 'data/models/faster-whisper'):
        self.model_name = model_name or 'small'
        self.model_dir = Path(model_dir)

    @classmethod
    def _get_model(cls, model_name: str, model_dir: Path):
        with cls._model_lock:
            if cls._model is not None and cls._model_name == model_name:
                return cls._model
            try:
                from faster_whisper import WhisperModel
            except ImportError as exc:
                raise RuntimeError(
                    "本地语音识别依赖未安装，请执行 pip install faster-whisper"
                ) from exc
            model_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"正在加载本地语音识别模型: {model_name}（首次使用会下载模型）")
            cls._model = WhisperModel(
                model_name,
                device='cpu',
                compute_type='int8',
                download_root=str(model_dir),
            )
            cls._model_name = model_name
            return cls._model

    async def transcribe_url(
        self,
        audio_url: str,
        output_path: str,
        ffmpeg_path: str = 'ffmpeg',
        max_seconds: int = 1200,
    ) -> Optional[str]:
        """Decode remote audio to temporary 16 kHz mono WAV, then transcribe."""
        return await asyncio.to_thread(
            self._transcribe_url_sync, audio_url, Path(output_path), ffmpeg_path, max_seconds
        )

    def _transcribe_url_sync(
        self, audio_url: str, output_path: Path, ffmpeg_path: str, max_seconds: int
    ) -> Optional[str]:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        headers = "Referer: https://www.bilibili.com/\r\nUser-Agent: Mozilla/5.0\r\n"
        command = [
            ffmpeg_path, '-hide_banner', '-loglevel', 'error', '-y', '-headers', headers,
            '-i', audio_url, '-vn', '-t', str(max_seconds), '-ac', '1', '-ar', '16000',
            '-c:a', 'pcm_s16le', str(output_path),
        ]
        try:
            result = subprocess.run(command, capture_output=True, timeout=max_seconds + 60, check=False)
            if result.returncode != 0 or not output_path.exists() or output_path.stat().st_size == 0:
                detail = result.stderr.decode(errors='replace')[-500:]
                raise RuntimeError(f"ffmpeg音频解码失败: {detail}")
            model = self._get_model(self.model_name, self.model_dir)
            segments, _info = model.transcribe(
                str(output_path), beam_size=3, vad_filter=True, condition_on_previous_text=False
            )
            text = ' '.join(segment.text.strip() for segment in segments if segment.text.strip())
            if not text:
                logger.warning("本地语音识别未检测到可用语音")
                return None
            logger.info(f"本地语音识别完成，文本长度: {len(text)}")
            return text
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("音频提取超时") from exc
        finally:
            output_path.unlink(missing_ok=True)
