"""Long-term memory built from diaries.

`data/memory.md` has exactly two sections:
1. past events (recent 7 days + important events)
2. learned things (experience + style)

The core persona is never modified here.
"""

import datetime
import json
from pathlib import Path
from typing import Optional

from loguru import logger

MEMORY_FILE = Path('data') / 'memory.md'
STATE_FILE = Path('data') / 'memory_state.json'
DIARY_DIR = Path('data') / 'diaries' / 'to_owner'
MAX_MEMORY_CHARS = 5000

DEFAULT_MEMORY = (
    '# 长期记忆\n\n'
    '## 一、以前发生的事件\n'
    '- 暂无\n\n'
    '## 二、学到的东西\n'
    '### 经验\n'
    '- 暂无\n'
    '### 风格\n'
    '- 暂无\n'
)


def load_memory(max_chars: int = MAX_MEMORY_CHARS) -> str:
    try:
        if MEMORY_FILE.is_file():
            return MEMORY_FILE.read_text(encoding='utf-8').strip()[:max_chars]
    except OSError:
        pass
    return ''


def _state() -> dict:
    try:
        if STATE_FILE.is_file():
            return json.loads(STATE_FILE.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        pass
    return {}


def _write_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8'
    )


def _diary_date(path: Path) -> Optional[datetime.date]:
    try:
        return datetime.datetime.strptime(path.name[:10], '%Y-%m-%d').date()
    except (TypeError, ValueError):
        return None


def _new_diaries(since: Optional[datetime.date]) -> list[tuple[datetime.date, str]]:
    if not DIARY_DIR.is_dir():
        return []
    rows = []
    for path in sorted(DIARY_DIR.glob('*_to_owner.md')):
        day = _diary_date(path)
        if day is None or (since is not None and day <= since):
            continue
        try:
            rows.append((day, path.read_text(encoding='utf-8')[:4000]))
        except OSError:
            continue
    return rows


def _valid_memory(text: str) -> bool:
    return (
        '## 一、以前发生的事件' in text
        and '## 二、学到的东西' in text
        and '### 风格' in text
        and len(text) <= MAX_MEMORY_CHARS
    )


async def consolidate(ai_client, *, force: bool = False) -> str:
    """Merge new diaries into memory.md once per day."""
    if ai_client is None:
        return ''
    today = datetime.date.today()
    state = _state()
    last = state.get('last_consolidated')
    if not force and last == today.isoformat():
        return ''
    since = None
    if last:
        try:
            since = datetime.date.fromisoformat(last)
        except ValueError:
            since = None
    diaries = _new_diaries(since)
    if not diaries and last:
        return ''
    existing = load_memory() or DEFAULT_MEMORY
    diary_text = '\n\n'.join(
        f'### {day.isoformat()}\n{text}' for day, text in diaries[-14:]
    ) or '（没有新日记）'
    prompt = (
        '你是鲸鱼娘的长期记忆整理器。只整理事实和表达经验，不修改核心人格。\n\n'
        f'# 已有长期记忆\n{existing}\n\n'
        f'# 新增日记\n{diary_text}\n\n'
        '# 输出要求\n'
        '只输出一个 Markdown 文档，结构必须是：\n'
        '# 长期记忆\n'
        '## 一、以前发生的事件\n'
        '- 日期：事件、对象、结果\n'
        '## 二、学到的东西\n'
        '### 经验\n'
        '- 从互动中总结出的规律\n'
        '### 风格\n'
        '- 表达方式上的偏好\n\n'
        '规则：\n'
        '1. 事件只保留最近 7 天，以及标注为重要的事件；重要事件以 [重要] 开头。\n'
        '2. 经验最多 15 条，风格最多 15 条，去重，不写空话。\n'
        '3. 不编造；没有内容写“- 暂无”。\n'
        '4. 不写身份规则、平台规则、代码建议。\n'
        '5. 全文控制在 4000 字以内。'
    )
    text = ''
    for attempt in range(2):
        try:
            text = await ai_client.chat(
                [
                    {'role': 'system', 'content': '你是严谨的长期记忆整理器。'},
                    {'role': 'user', 'content': prompt},
                ],
                temperature=0.2,
                max_tokens=1600,
            ) or ''
        except Exception as exc:  # noqa: BLE001
            logger.warning(f'长期记忆整理失败（第 {attempt + 1} 次）: {exc}')
            text = ''
            continue
        text = text.strip()
        if text.startswith('```'):
            text = text.strip('`')
            if text.startswith('markdown'):
                text = text[len('markdown'):].lstrip()
        if _valid_memory(text):
            break
        logger.warning(f'长期记忆格式不符合要求（第 {attempt + 1} 次）')
        text = ''
    if not _valid_memory(text):
        return ''
    MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp = MEMORY_FILE.with_suffix('.md.tmp')
    temp.write_text(text.strip() + '\n', encoding='utf-8')
    temp.replace(MEMORY_FILE)
    _write_state({'last_consolidated': today.isoformat()})
    logger.info(f'长期记忆已更新：{MEMORY_FILE}')
    return text.strip()
