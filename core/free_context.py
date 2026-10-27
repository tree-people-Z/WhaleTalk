"""Context and diary helpers for the free-form agent."""

from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Optional

from core.long_term_memory import load_memory
from utils.persona_defaults import load_configured_persona

DIARY_DIR = Path('data') / 'diaries' / 'to_owner'


def _diary_files(days: int = 3) -> list[Path]:
    if not DIARY_DIR.is_dir():
        return []
    earliest = date.today() - timedelta(days=max(1, days) - 1)
    files = []
    for path in DIARY_DIR.glob('*.md'):
        try:
            day = datetime.strptime(path.stem, '%Y-%m-%d').date()
        except ValueError:
            continue
        if earliest <= day <= date.today():
            files.append((day, path))
    return [path for _, path in sorted(files)]


def load_recent_diaries(days: int = 3, max_chars: int = 8000) -> str:
    parts = []
    for path in _diary_files(days):
        try:
            text = path.read_text(encoding='utf-8').strip()
        except OSError:
            continue
        if text:
            parts.append(f"## {path.stem}\n{text}")
    return '\n\n'.join(parts)[:max_chars]


def list_diary_days() -> list[str]:
    if not DIARY_DIR.is_dir():
        return []
    days = []
    for path in DIARY_DIR.glob('*.md'):
        try:
            datetime.strptime(path.stem, '%Y-%m-%d')
        except ValueError:
            continue
        days.append(path.stem)
    return sorted(set(days))


def read_diary(day: str = '', max_chars: int = 12000) -> str:
    """Read any diary. Empty day lists available dates; 'all' reads all."""
    if not day:
        days = list_diary_days()
        return '可用日记日期：' + ('、'.join(days) if days else '（暂无日记）')
    if day == 'all':
        parts = []
        for name in list_diary_days():
            path = DIARY_DIR / f'{name}.md'
            try:
                text = path.read_text(encoding='utf-8').strip()
            except OSError:
                continue
            if text:
                parts.append(f'## {name}\n{text}')
        return '\n\n'.join(parts)[:max_chars] or '（暂无日记）'
    try:
        datetime.strptime(day, '%Y-%m-%d')
    except ValueError:
        return '日期格式应为 YYYY-MM-DD'
    path = DIARY_DIR / f'{day}.md'
    if not path.is_file():
        return f'{day} 没有日记'
    return path.read_text(encoding='utf-8')[:max_chars]


def append_diary(content: str, day: Optional[date] = None) -> Path:
    """Append free-form text to the day's diary; no template is imposed."""
    content = (content or '').strip()
    if not content:
        raise ValueError('日记内容为空')
    day = day or date.today()
    DIARY_DIR.mkdir(parents=True, exist_ok=True)
    path = DIARY_DIR / f'{day.isoformat()}.md'
    existing = path.read_text(encoding='utf-8').rstrip() if path.is_file() else ''
    separator = '\n\n' if existing else ''
    path.write_text(existing + separator + content + '\n', encoding='utf-8')
    return path


DIARY_TOOLS = [
    {
        'name': 'read_diary',
        'description': (
            '读取日记。day 为空时列出所有日期；day=YYYY-MM-DD 读取当天；'
            "day='all' 读取全部（有长度上限）。"
        ),
        'parameters': {'day': 'string(可选)'},
    },
    {
        'name': 'write_diary',
        'description': (
            '写今天的日记。内容、格式、长短都由你决定；会追加到当天日记。'
        ),
        'parameters': {'content': 'string'},
    },
]


def build_agent_context(config, diary_days: int = 3) -> str:
    persona = load_configured_persona(config, 5000)
    diaries = load_recent_diaries(diary_days)
    memory = load_memory(4000)
    keywords = config.get('search.keywords', []) if config is not None else []
    if isinstance(keywords, str):
        keywords = [line.strip() for line in keywords.splitlines() if line.strip()]
    if not isinstance(keywords, (list, tuple)):
        keywords = []
    keywords = [str(item).strip() for item in keywords if str(item).strip()]
    max_videos = config.get('limits.max_videos_per_run', 20) if config is not None else 20
    try:
        max_videos = int(max_videos)
    except (TypeError, ValueError):
        max_videos = 20
    preference = (
        f'# 刷视频偏好\n关键词：{"、".join(keywords) if keywords else "（未设置）"}\n'
        f'每轮大致看 {max_videos} 个视频；最终看多少由你决定。'
    )
    return (
        f'# 人设\n{persona or "（没有人设文件）"}\n\n'
        f'# 最近三天日记\n{diaries or "（最近三天没有日记）"}\n\n'
        f'# 长期记忆\n{memory or "（暂无长期记忆）"}\n\n'
        f'{preference}'
    )
