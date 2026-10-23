"""Extract a small set of representative video frames for visual analysis."""

import asyncio
import subprocess
from pathlib import Path
from typing import List, Optional

from loguru import logger

from utils.subprocess_helpers import hidden_window_kwargs


class FrameAnalyzer:
    """Use ffmpeg to sample frames without saving the source video."""

    def __init__(self):
        self.ffmpeg_path = self._find_ffmpeg()

    @staticmethod
    def _find_ffmpeg() -> Optional[str]:
        try:
            result = subprocess.run(
                ['ffmpeg', '-version'], capture_output=True, timeout=5, check=False,
                **hidden_window_kwargs(),
            )
            return 'ffmpeg' if result.returncode == 0 else None
        except (OSError, subprocess.TimeoutExpired):
            return None

    @property
    def ffmpeg_available(self) -> bool:
        return self.ffmpeg_path is not None

    @staticmethod
    def _duration_seconds(duration) -> Optional[float]:
        if isinstance(duration, (int, float)):
            return float(duration) if duration > 0 else None
        if not isinstance(duration, str):
            return None
        try:
            parts = [float(part) for part in duration.split(':')]
            seconds = 0.0
            for part in parts:
                seconds = seconds * 60 + part
            return seconds if seconds > 0 else None
        except ValueError:
            return None

    async def extract_frames(
        self,
        video_url: str,
        output_dir: str,
        count: int = 3,
        duration=None,
    ) -> List[str]:
        """Extract evenly spaced JPEG frames, bounded to at most five images."""
        if not self.ffmpeg_available:
            logger.warning("ffmpeg不可用，跳过画面分析")
            return []
        seconds = self._duration_seconds(duration)
        if not seconds or not video_url:
            logger.warning("视频时长或播放地址不可用，跳过画面抽帧")
            return []
        return await asyncio.to_thread(
            self._extract_frames_sync, video_url, output_dir, count, seconds
        )

    def _extract_frames_sync(
        self, video_url: str, output_dir: str, count: int, duration: float
    ) -> List[str]:
        output_path = Path(output_dir)
        output_path.mkdir(parents=True, exist_ok=True)
        count = max(1, min(int(count), 5))
        positions = [duration * i / (count + 1) for i in range(1, count + 1)]
        frames = []
        headers = "Referer: https://www.bilibili.com/\r\nUser-Agent: Mozilla/5.0\r\n"
        for index, position in enumerate(positions, 1):
            target = output_path / f"frame-{index}.jpg"
            command = [
                self.ffmpeg_path, '-hide_banner', '-loglevel', 'error', '-nostdin', '-y',
                '-headers', headers, '-ss', str(position), '-i', video_url,
                '-frames:v', '1', '-vf', 'scale=960:-2', '-q:v', '5', str(target)
            ]
            try:
                result = subprocess.run(
                    command, capture_output=True, timeout=45, check=False,
                    **hidden_window_kwargs(),
                )
                if result.returncode == 0 and target.exists() and target.stat().st_size:
                    frames.append(str(target))
                else:
                    target.unlink(missing_ok=True)
                    logger.warning(
                        f"第{index}帧提取失败: {result.stderr.decode(errors='replace')[-300:]}"
                    )
            except (OSError, subprocess.TimeoutExpired) as exc:
                target.unlink(missing_ok=True)
                logger.warning(f"第{index}帧提取失败: {exc}")
        logger.info(f"视频关键帧提取完成: {len(frames)}/{count}")
        return frames

    async def analyze_frame(self, image_path: str, ai_client) -> Optional[str]:
        """Analyze one frame through the configured multimodal AI client."""
        return await ai_client.describe_image(image_path)
