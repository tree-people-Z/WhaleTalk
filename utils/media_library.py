"""Download and remember images for later reuse (DM/dynamic)."""

import hashlib
from pathlib import Path
from typing import Any, Dict, Optional

import requests
from loguru import logger

LIBRARY_DIR = Path('data') / 'media_library'


async def collect_image(
    db,
    url: str,
    *,
    source: str = '',
    ai_client=None,
    headers: Optional[Dict[str, str]] = None,
) -> Optional[Dict[str, Any]]:
    if not url or not url.startswith('http'):
        return None
    try:
        response = requests.get(
            url,
            headers=headers or {
                'User-Agent': 'Mozilla/5.0',
                'Referer': 'https://www.bilibili.com/',
            },
            timeout=20,
        )
        content = response.content or b''
        if not response.ok or not content or len(content) > 12 * 1024 * 1024:
            return None
        content_type = response.headers.get('Content-Type', '')
        if content_type and not content_type.startswith('image/'):
            return None
        suffix = '.jpg'
        for candidate in ('.png', '.jpeg', '.webp', '.gif'):
            if candidate in content_type:
                suffix = candidate
                break
        LIBRARY_DIR.mkdir(parents=True, exist_ok=True)
        path = LIBRARY_DIR / (hashlib.md5(url.encode('utf-8')).hexdigest() + suffix)
        if not path.exists():
            path.write_bytes(content)
        description = ''
        if ai_client is not None:
            try:
                description = await ai_client.describe_image(str(path.resolve())) or ''
            except Exception as exc:  # noqa: BLE001
                logger.debug(f'识别收藏图片失败: {exc}')
        db.add_media_asset(
            str(path.resolve()),
            source=source,
            source_url=url,
            description=description,
        )
        logger.info(f'已收集图片: {path.name} ({source})')
        return {'path': str(path.resolve()), 'description': description}
    except Exception as exc:  # noqa: BLE001
        logger.debug(f'收集图片失败: {exc}')
        return None
