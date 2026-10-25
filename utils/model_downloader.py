"""Resumable, multi-threaded downloader for faster-whisper models."""

import os
import threading
from pathlib import Path
from typing import Callable, List, Optional

from loguru import logger

from utils.downloader import download_file

MODEL_REPO = 'Systran/faster-whisper-medium'
MODEL_FILES = {
    'config.json': 2257,
    'model.bin': 1527906378,
    'tokenizer.json': 2203239,
    'vocabulary.txt': 459861,
}
MODEL_TOTAL = sum(MODEL_FILES.values())
_DOWNLOAD_LOCK = threading.Lock()

Progress = Callable[[int, int], None]
CancelCheck = Callable[[], bool]


def mirror_endpoints() -> List[str]:
    """Domestic mirror first, then official HuggingFace."""
    endpoints = []
    custom = os.environ.get('WHALETALK_HF_ENDPOINT') or os.environ.get('HF_ENDPOINT')
    if custom:
        endpoints.append(custom.rstrip('/'))
    endpoints.extend([
        'https://hf-mirror.com',
        'https://huggingface.co',
    ])
    result = []
    for endpoint in endpoints:
        if endpoint and endpoint not in result:
            result.append(endpoint)
    return result


def model_file_url(endpoint: str, filename: str) -> str:
    return f"{endpoint.rstrip('/')}/{MODEL_REPO}/resolve/main/{filename}"


def is_model_ready(model_dir: Path, model_name: str = 'medium') -> bool:
    directory = Path(model_dir) / model_name
    return all(
        (directory / filename).is_file()
        and (directory / filename).stat().st_size == size
        for filename, size in MODEL_FILES.items()
    )


def download_model(
    model_dir: Path,
    model_name: str = 'medium',
    *,
    threads: int = 4,
    progress: Optional[Progress] = None,
    should_cancel: Optional[CancelCheck] = None,
) -> Path:
    """Download the four faster-whisper files with resume and parallel chunks."""
    # Only one download may run at a time; a second caller waits and then
    # observes the completed files instead of downloading the same model again.
    with _DOWNLOAD_LOCK:
        return _download_model_locked(
            model_dir,
            model_name,
            threads=threads,
            progress=progress,
            should_cancel=should_cancel,
        )


def _download_model_locked(
    model_dir: Path,
    model_name: str = 'medium',
    *,
    threads: int = 4,
    progress: Optional[Progress] = None,
    should_cancel: Optional[CancelCheck] = None,
) -> Path:
    if model_name != 'medium':
        raise RuntimeError(f'不支持的本地模型: {model_name}')
    directory = Path(model_dir) / model_name
    directory.mkdir(parents=True, exist_ok=True)
    if is_model_ready(model_dir, model_name):
        logger.info(f'本地语音模型已存在: {directory}')
        return directory

    endpoints = mirror_endpoints()
    done_before = sum(
        size for filename, size in MODEL_FILES.items()
        if (directory / filename).is_file()
        and (directory / filename).stat().st_size == size
    )
    reported = {'base': done_before}

    def file_progress(done: int, _total: int):
        if progress:
            progress(min(reported['base'] + done, MODEL_TOTAL), MODEL_TOTAL)

    for filename, size in MODEL_FILES.items():
        target = directory / filename
        if target.is_file() and target.stat().st_size == size:
            continue
        last_error = None
        for endpoint in endpoints:
            url = model_file_url(endpoint, filename)
            try:
                logger.info(f'下载语音模型文件: {filename} <- {endpoint}')
                download_file(
                    url,
                    target,
                    expected_size=size,
                    threads=threads,
                    progress=file_progress,
                    should_cancel=should_cancel,
                )
                last_error = None
                break
            except Exception as exc:  # noqa: BLE001
                last_error = exc
                logger.warning(f'{endpoint} 下载 {filename} 失败，尝试下一个镜像: {exc}')
        if last_error is not None:
            raise RuntimeError(f'下载模型文件 {filename} 失败: {last_error}')
        reported['base'] += size
        if progress:
            progress(min(reported['base'], MODEL_TOTAL), MODEL_TOTAL)

    if not is_model_ready(model_dir, model_name):
        raise RuntimeError('模型文件不完整，请重试')
    logger.info(f'本地语音模型已就绪: {directory}')
    return directory
