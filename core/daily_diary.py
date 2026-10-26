"""Ensure a daily diary exists even when no analysis cycle runs."""

from datetime import datetime
from pathlib import Path
from typing import Optional

from loguru import logger

from core.diary_system import DiarySystem


def ensure_daily_diary(db, diary_dir: Optional[Path] = None) -> Optional[Path]:
    """Write today's factual diary once; later analysis may overwrite it."""
    diary = DiarySystem(diary_dir)
    today = datetime.now().strftime('%Y-%m-%d')
    target = diary.to_owner_dir / f'{today}_to_owner.md'
    if target.is_file():
        return target
    try:
        stats = db.get_statistics()
        events = db.get_recent_memory_events(limit=20)
        lines = [
            f"- 对 {item.get('user_name') or '网友'}："
            f"{(item.get('content') or '')[:80]} → 我回："
            f"{(item.get('my_content') or '')[:80]}"
            for item in events[:8]
            if item.get('content') or item.get('my_content')
        ]
        content = (
            f"今天发送了 {stats.get('today_comments', 0)} 条（评论+回复），"
            f"分析了 {stats.get('today_videos', 0)} 个视频。"
        )
        if lines:
            content += "\n\n最近互动：\n" + "\n".join(lines)
        else:
            content += "\n\n今天还没有新的对话。"
        diary.write_to_owner(
            content=content,
            videos_found=stats.get('today_videos', 0),
            videos_analyzed=stats.get('today_videos', 0),
            comments_sent=stats.get('today_comments', 0),
            mood='平静',
        )
        diary.write_to_self(
            raw_data={'stats': stats, 'events': events},
            thoughts='这是当天的基础记录，不编造未发生的互动。',
        )
        logger.info(f'已生成每日日记: {target.name}')
        return target
    except Exception as exc:  # noqa: BLE001
        logger.warning(f'生成每日日记失败: {exc}')
        return None
