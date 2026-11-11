"""CLI: compact old diary files (same logic the app runs automatically).

用法：
    python tools/compact_diaries.py --dry-run --only 2026-11-09
    python tools/compact_diaries.py --only 2026-11-09
    python tools/compact_diaries.py            # 按配置处理过期的长日记
"""

import argparse
import asyncio
from pathlib import Path

from core.diary_maintenance import compact_diaries
from core.self_evolution import housekeeping
from utils.config_manager import ConfigManager
from utils.database import Database
from utils.secure_store import unprotect


def build_client(config: ConfigManager):
    from core.ai_client import AIClient

    return AIClient(
        provider=config.get('ai.provider', 'openai'),
        api_key=unprotect(config.get('ai.api_key', '')),
        model=config.get('ai.model'),
        base_url=config.get('ai.base_url'),
        timeout=180,
        max_retries=2,
        max_output_tokens=8000,
    )


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument('--dry-run', action='store_true')
    parser.add_argument('--only', default='')
    parser.add_argument('--dir', default='')
    parser.add_argument('--days', type=int, default=0)
    parser.add_argument('--min-chars', type=int, default=0)
    parser.add_argument('--housekeeping', action='store_true',
                        help='顺便做成长档案衰减与清理')
    args = parser.parse_args()

    config = ConfigManager(Path('data') / 'config.json')
    client = build_client(config)
    stats = await compact_diaries(
        client,
        config,
        days=args.days,
        min_chars=args.min_chars,
        dry_run=args.dry_run,
        directory=Path(args.dir) if args.dir else None,
        only=args.only,
    )
    print(
        f'文件 {stats["files"]} 篇，{stats["before"]} -> {stats["after"]} 字'
        + (f'，失败 {stats["failed"]} 篇' if stats['failed'] else '')
    )
    if args.housekeeping and not args.dry_run:
        db = Database('data/history.db')
        try:
            print('成长档案清理:', housekeeping(db, config))
        finally:
            db.close()
    return 0


if __name__ == '__main__':
    raise SystemExit(asyncio.run(main()))
