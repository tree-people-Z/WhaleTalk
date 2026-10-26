"""Download and describe images attached to B站 comments."""

import hashlib
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import urlparse

import requests
from loguru import logger

CACHE_DIR = Path('data') / 'comment_images'
HEADERS = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64)',
    'Referer': 'https://www.bilibili.com/',
}


def _download(url: str) -> Path | None:
    try:
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        suffix = Path(urlparse(url).path).suffix.lower()
        if suffix not in ('.jpg', '.jpeg', '.png', '.webp', '.gif'):
            suffix = '.jpg'
        path = CACHE_DIR / (hashlib.md5(url.encode('utf-8')).hexdigest() + suffix)
        if path.is_file():
            return path
        response = requests.get(url, headers=HEADERS, timeout=10)
        content = response.content or b''
        if (
            response.ok
            and len(content) < 8 * 1024 * 1024
            and response.headers.get('Content-Type', '').startswith('image/')
        ):
            path.write_bytes(content)
            return path
    except Exception as exc:  # noqa: BLE001
        logger.debug(f'下载评论图片失败: {exc}')
    return None


async def describe_comment_images(
    comments: List[Dict[str, Any]],
    ai_client,
    max_images: int = 3,
) -> List[Dict[str, Any]]:
    """Attach image_descriptions to comments; bounded to avoid vision cost."""
    if ai_client is None:
        return comments
    described = 0
    for comment in comments or []:
        descriptions = []
        for url in (comment.get('images') or [])[:2]:
            if described >= max_images:
                break
            path = _download(url)
            if path is None:
                continue
            cache = path.with_suffix(path.suffix + '.txt')
            try:
                if cache.is_file():
                    text = cache.read_text(encoding='utf-8').strip()
                else:
                    text = await ai_client.describe_image(str(path)) or ''
                    if text:
                        cache.write_text(text, encoding='utf-8')
            except Exception as exc:  # noqa: BLE001
                logger.debug(f'识别评论图片失败: {exc}')
                text = ''
            if text:
                descriptions.append(text)
                described += 1
        comment['image_descriptions'] = descriptions
    return comments
