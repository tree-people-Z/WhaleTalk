"""Resumable multi-thread HTTP downloads for model/component packages."""

import hashlib
import os
import threading
from pathlib import Path
from typing import Callable, Optional

import requests
from loguru import logger

Progress = Callable[[int, int], None]
CancelCheck = Callable[[], bool]


class DownloadCancelled(Exception):
    pass


def _cancel_requested(should_cancel: Optional[CancelCheck]) -> bool:
    return bool(should_cancel and should_cancel())


def _probe_size(url: str) -> int:
    try:
        response = requests.head(
            url, allow_redirects=True, timeout=(10, 30),
            headers={'Accept-Encoding': 'identity'},
        )
        size = int(response.headers.get('Content-Length') or 0)
        if size:
            return size
    except Exception:  # noqa: BLE001
        pass
    try:
        response = requests.get(
            url, stream=True, timeout=(10, 30),
            headers={'Range': 'bytes=0-0', 'Accept-Encoding': 'identity'},
        )
        content_range = response.headers.get('Content-Range') or ''
        response.close()
        if '/' in content_range:
            return int(content_range.rsplit('/', 1)[-1])
        return int(response.headers.get('Content-Length') or 0)
    except Exception:  # noqa: BLE001
        return 0


def _hash_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def _download_single(
    url: str,
    target: Path,
    expected_size: int,
    progress: Optional[Progress],
    should_cancel: Optional[CancelCheck],
) -> None:
    """Fallback for servers that ignore Range requests."""
    part = target.with_name(target.name + '.single.part')
    done = part.stat().st_size if part.exists() else 0
    headers = {'Accept-Encoding': 'identity'}
    if done:
        headers['Range'] = f'bytes={done}-'
    with requests.get(
        url, headers=headers, stream=True, timeout=(15, 90),
        allow_redirects=True,
    ) as response:
        if done and response.status_code == 206:
            mode = 'ab'
        elif response.status_code == 200:
            mode = 'wb'
            done = 0
        else:
            response.raise_for_status()
            mode = 'wb'
        with part.open(mode) as stream:
            for chunk in response.iter_content(1024 * 256):
                if _cancel_requested(should_cancel):
                    raise DownloadCancelled()
                if chunk:
                    stream.write(chunk)
                    done += len(chunk)
                    if progress:
                        progress(done, expected_size or done)
    if expected_size and part.stat().st_size != expected_size:
        raise RuntimeError(f'下载大小不一致: {part.stat().st_size} != {expected_size}')
    os.replace(part, target)


def download_file(
    url: str,
    target: Path,
    *,
    expected_size: int = 0,
    expected_sha256: str = '',
    threads: int = 4,
    progress: Optional[Progress] = None,
    should_cancel: Optional[CancelCheck] = None,
) -> Path:
    """Download one file with parallel Range requests and persistent resume parts."""
    target = Path(target)
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.is_file():
        if not expected_size or target.stat().st_size == expected_size:
            if not expected_sha256 or _hash_file(target) == expected_sha256:
                return target

    total = int(expected_size or _probe_size(url))
    if total <= 0:
        _download_single(url, target, 0, progress, should_cancel)
    else:
        threads = max(1, min(int(threads), 8))
        chunk_size = max(1, (total + threads - 1) // threads)
        parts = [
            target.with_name(target.name + f'.part{index}')
            for index in range(threads)
        ]
        state = {'done': sum(min(p.stat().st_size, chunk_size) for p in parts if p.exists())}
        lock = threading.Lock()

        def report(delta: int):
            with lock:
                state['done'] += delta
                if progress:
                    progress(min(state['done'], total), total)

        def worker(index: int):
            start = index * chunk_size
            end = min(total, start + chunk_size)
            part = parts[index]
            existing = part.stat().st_size if part.exists() else 0
            if existing >= end - start:
                return
            headers = {
                'Accept-Encoding': 'identity',
                'Range': f'bytes={start + existing}-{end - 1}',
            }
            last_error = None
            for _attempt in range(3):
                if _cancel_requested(should_cancel):
                    raise DownloadCancelled()
                try:
                    with requests.get(
                        url, headers=headers, stream=True, timeout=(15, 90),
                        allow_redirects=True,
                    ) as response:
                        if response.status_code == 200:
                            # Range ignored by this CDN; use a single stream.
                            with lock:
                                if not state.get('fallback'):
                                    state['fallback'] = True
                                    raise _UseSingleStream()
                        if response.status_code != 206:
                            response.raise_for_status()
                        with part.open('ab') as stream:
                            for chunk in response.iter_content(1024 * 256):
                                if _cancel_requested(should_cancel):
                                    raise DownloadCancelled()
                                if chunk:
                                    stream.write(chunk)
                                    report(len(chunk))
                        break
                except _UseSingleStream:
                    return
                except DownloadCancelled:
                    raise
                except Exception as exc:  # noqa: BLE001
                    last_error = exc
            else:
                raise RuntimeError(f'分块下载失败: {last_error}') from last_error
            if part.stat().st_size != end - start:
                raise RuntimeError(f'分块大小不一致: {part.stat().st_size} != {end - start}')

        from concurrent.futures import ThreadPoolExecutor
        with ThreadPoolExecutor(max_workers=threads) as executor:
            futures = [executor.submit(worker, index) for index in range(threads)]
            for future in futures:
                future.result()

        if state.get('fallback'):
            _download_single(url, target, total, progress, should_cancel)
        else:
            with target.open('wb') as output:
                for part in parts:
                    with part.open('rb') as source:
                        for chunk in iter(lambda: source.read(1024 * 256), b''):
                            output.write(chunk)
                    part.unlink(missing_ok=True)
            if target.stat().st_size != total:
                raise RuntimeError(f'下载大小不一致: {target.stat().st_size} != {total}')

    if expected_size and target.stat().st_size != expected_size:
        raise RuntimeError(f'下载大小不一致: {target.stat().st_size} != {expected_size}')
    if expected_sha256:
        actual = _hash_file(target)
        if actual.lower() != expected_sha256.lower():
            raise RuntimeError('下载文件校验失败')
    logger.info(f'下载完成: {target}')
    return target


class _UseSingleStream(Exception):
    """Internal signal: CDN ignored Range, fall back to one stream."""
