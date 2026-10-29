"""Local speech-to-text fallback using faster-whisper."""

import asyncio
import gc
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Optional

from loguru import logger

from utils.subprocess_helpers import hidden_window_kwargs


class LocalAudioTranscriber:
    """Convert a Bilibili audio stream to text locally (no audio API upload)."""

    _model = None
    _model_name = None
    _model_lock = threading.Lock()
    _last_used = 0.0

    # Files required by a faster-whisper / CTranslate2 model directory.
    MODEL_FILES = ('config.json', 'model.bin', 'tokenizer.json', 'vocabulary.txt')

    def __init__(self, model_name: str = 'medium', model_dir: str = 'data/models/faster-whisper'):
        self.model_name = model_name or 'medium'
        self.model_dir = Path(model_dir)

    @classmethod
    def local_model_path(cls, model_dir: Path, model_name: str = 'medium'):
        """Return a manually placed model directory when all files exist."""
        directory = Path(model_dir) / model_name
        if all((directory / name).is_file() for name in cls.MODEL_FILES):
            return str(directory)
        return None

    @classmethod
    def _get_model(cls, model_name: str, model_dir: Path):
        with cls._model_lock:
            if cls._model is not None and cls._model_name == model_name:
                return cls._model
            # 便携版按需下载的组件位于 data/transcription，需要先加入导入路径。
            try:
                from utils.transcription_component import (
                    configure_hf_endpoint,
                    ensure_importable,
                )
                ensure_importable()
                configure_hf_endpoint()
            except Exception as exc:  # noqa: BLE001
                logger.debug(f"准备本地识别组件失败: {exc}")
            try:
                from faster_whisper import WhisperModel
            except ImportError as exc:
                if getattr(sys, 'frozen', False):
                    raise RuntimeError(
                        "本地识别组件未安装，请在设置页点击“下载本地识别组件和模型”后重试。"
                    ) from exc
                raise RuntimeError(
                    "本地语音识别依赖未安装，请执行 pip install faster-whisper"
                ) from exc
            model_dir.mkdir(parents=True, exist_ok=True)
            manual_path = cls.local_model_path(model_dir, model_name)
            if not manual_path and model_name == 'medium':
                try:
                    from utils.model_downloader import download_model
                    logger.info("本地语音模型未就绪，开始多线程下载（支持断点续传）")
                    download_model(model_dir, model_name)
                    manual_path = cls.local_model_path(model_dir, model_name)
                except Exception as exc:  # noqa: BLE001
                    logger.warning(f"预下载本地语音模型失败，将尝试默认加载: {exc}")
            model_argument = manual_path or model_name
            if manual_path:
                logger.info(f"使用本地语音识别模型: {manual_path}")
            else:
                logger.info(f"正在加载本地语音识别模型: {model_name}（首次使用会下载模型）")
            cls._model = WhisperModel(
                model_argument,
                device='cpu',
                compute_type='int8',
                download_root=str(model_dir),
            )
            cls._model_name = model_name
            cls._last_used = time.time()
            return cls._model

    @classmethod
    def release_if_idle(cls, max_idle_seconds: float = 600) -> bool:
        """空闲一段时间后释放本地模型，降低常驻内存。"""
        released = False
        with cls._model_lock:
            if (cls._model is not None
                    and time.time() - cls._last_used > max_idle_seconds):
                cls._model = None
                cls._model_name = None
                released = True
        if released:
            gc.collect()
            logger.info('本地语音模型空闲，已释放内存')
        return released

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
            ffmpeg_path, '-hide_banner', '-loglevel', 'error', '-nostdin', '-y', '-headers', headers,
            '-i', audio_url, '-vn', '-t', str(max_seconds), '-ac', '1', '-ar', '16000',
            '-c:a', 'pcm_s16le', str(output_path),
        ]
        try:
            result = subprocess.run(
                command, capture_output=True, timeout=max_seconds + 60, check=False,
                **hidden_window_kwargs(),
            )
            if result.returncode != 0 or not output_path.exists() or output_path.stat().st_size == 0:
                detail = result.stderr.decode(errors='replace')[-500:]
                raise RuntimeError(f"ffmpeg音频解码失败: {detail}")
            model = self._get_model(self.model_name, self.model_dir)
            # 直接传入 float32 采样数组，避免依赖 PyAV 的版本相关解码接口。
            try:
                audio_input = self._read_wav_float32(output_path)
            except Exception as exc:  # noqa: BLE001
                logger.debug(f"读取 WAV 失败，回退为文件路径: {exc}")
                audio_input = str(output_path)
            segments, _info = model.transcribe(
                audio_input, beam_size=3, vad_filter=True, condition_on_previous_text=False
            )
            text = ' '.join(segment.text.strip() for segment in segments if segment.text.strip())
            self.__class__._last_used = time.time()
            if not text:
                logger.warning("本地语音识别未检测到可用语音")
                return None
            logger.info(f"本地语音识别完成，文本长度: {len(text)}")
            return text
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("音频提取超时") from exc
        finally:
            output_path.unlink(missing_ok=True)

    @staticmethod
    def _read_wav_float32(path: Path):
        """Read the 16 kHz mono PCM WAV produced by ffmpeg as float32 samples."""
        import wave

        import numpy as np

        with wave.open(str(path), 'rb') as handle:
            frames = handle.readframes(handle.getnframes())
        return np.frombuffer(frames, dtype=np.int16).astype(np.float32) / 32768.0
