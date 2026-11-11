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
    """读取尚未整理进长期记忆的日记。

    自由 Agent 写 ``YYYY-MM-DD.md``，旧流水线写 ``YYYY-MM-DD_to_owner.md``；
    同一天两者都存在时优先使用自由格式，避免重复整理。
    """
    if not DIARY_DIR.is_dir():
        return []
    by_day: dict[datetime.date, Path] = {}
    for path in DIARY_DIR.glob('*.md'):
        day = _diary_date(path)
        if day is None or (since is not None and day <= since):
            continue
        preferred = path.name == f'{day.isoformat()}.md'
        if day not in by_day or preferred:
            by_day[day] = path
    rows = []
    for day in sorted(by_day):
        try:
            text = by_day[day].read_text(encoding='utf-8')
        except OSError:
            continue
        rows.append((day, text[-4000:]))
    return rows


def _valid_memory(text: str) -> bool:
    return (
        '## 一、以前发生的事件' in text
        and '## 二、学到的东西' in text
        and '### 风格' in text
        and len(text) <= MAX_MEMORY_CHARS
    )


def _memory_prompt(existing: str, diary_text: str) -> str:
    return f"""你是鲸鱼娘的长期记忆整理器。只整理事实和表达经验，不修改核心人格。

# 已有长期记忆
{existing[:4200]}

# 新增日记
{diary_text}

# 输出要求
只输出一个 Markdown 文档，结构必须是：
# 长期记忆
## 一、以前发生的事件
- 2026-11-09：一句话说清发生了什么，加一句她当时的反应
## 二、学到的东西
### 经验
- 一句可复用的规律（怎么做更容易被接话/更容易踩雷）
### 风格
- 她真的会这么说：「原话示例」，再补一句什么时候用

规则：
1. 事件一行一条，一行只写一个事件；不写播放量、点赞数、时长、帧数、评分、工具调用次数、审计行。只保留最近 7 天和 [重要] 事件，最多 12 行。
2. 风格必须带原话示例（引号里是她说过的话），不要只写“语气温和”这类描述。
   经验、风格各最多 12 条，去重，不写空话。
3. 不编造；没有内容写“- 暂无”。
4. 不写身份规则、平台规则、代码建议。
5. 全文不超过 2500 字。"""


def _diary_excerpt(text: str, limit: int = 180) -> str:
    """从日记结尾取一段可用于事件记录的话（最新内容更相关）。"""
    selected = []
    total = 0
    for line in reversed(str(text or '').splitlines()):
        cleaned = line.strip().lstrip('#>-* ').strip()
        cleaned = cleaned.replace('**', '').strip()
        if not cleaned or cleaned == '---' or cleaned.startswith('日期'):
            continue
        if len(cleaned) < 6:
            continue
        selected.append(cleaned)
        total += len(cleaned)
        if total >= limit:
            break
    selected.reverse()
    excerpt = ' '.join(selected)
    if len(excerpt) > limit:
        excerpt = '…' + excerpt[-limit:]
    return excerpt


def _fallback_memory(existing: str, day: datetime.date, text: str) -> str:
    """模型不支持长提示时的本地回退：追加一条事件，保留已有经验/风格。"""
    memory = existing if _valid_memory(existing) else DEFAULT_MEMORY
    marker = '## 二、学到的东西'
    if marker in memory:
        head, tail = memory.split(marker, 1)
        tail = marker + tail
    else:
        head = memory
        tail = marker + """
### 经验
- 暂无

### 风格
- 暂无
"""
    events = [
        line.rstrip() for line in head.splitlines()
        if line.strip().startswith('- ') and '暂无' not in line
    ]
    excerpt = _diary_excerpt(text)
    if excerpt:
        events.append(f'- {day.isoformat()}：{excerpt}')
    events = events[-20:]
    while events:
        head = (
            '# 长期记忆' + chr(10) + chr(10)
            + '## 一、以前发生的事件' + chr(10)
            + chr(10).join(events) + chr(10) + chr(10)
        )
        merged = head + tail
        if len(merged) <= MAX_MEMORY_CHARS:
            return merged
        events.pop(0)
    return (head + tail)[:MAX_MEMORY_CHARS]


async def _request_memory(ai_client, existing: str, diary_text: str) -> str:
    """让模型合并一天的日记；失败时带反馈重试。"""
    prompt = _memory_prompt(existing, diary_text)
    for attempt in range(3):
        try:
            text = await ai_client.chat(
                [
                    {'role': 'system', 'content': '你是严谨的长期记忆整理器。'},
                    {'role': 'user', 'content': prompt},
                ],
                temperature=0.2,
                max_tokens=6000,
            ) or ''
        except Exception as exc:  # noqa: BLE001
            logger.warning(f'长期记忆整理失败（第 {attempt + 1} 次）: {exc}')
            continue
        text = text.strip()
        if text.startswith('```'):
            text = text.strip('`')
            if text.startswith('markdown'):
                text = text[len('markdown'):].lstrip()
        if _valid_memory(text):
            return text
        missing = [
            item for item in (
                '## 一、以前发生的事件', '## 二、学到的东西', '### 风格'
            ) if item not in text
        ]
        logger.warning(
            f'长期记忆格式不符合要求（第 {attempt + 1} 次）：'
            f'长度 {len(text)}，缺少 {missing or "无"}'
        )
        prompt = (
            _memory_prompt(existing, diary_text)
            + '\n\n上一次输出不合格：'
            + (f'缺少 {missing}；' if missing else '')
            + (
                f'长度 {len(text)} 超过 5000 字；'
                if len(text) > MAX_MEMORY_CHARS else ''
            )
            + '请重新输出完整结构，并压缩到 4000 字以内。'
        )
    return ''


def _write_memory(text: str) -> None:
    MEMORY_FILE.parent.mkdir(parents=True, exist_ok=True)
    temp = MEMORY_FILE.with_suffix('.md.tmp')
    temp.write_text(text.strip() + '\n', encoding='utf-8')
    temp.replace(MEMORY_FILE)


async def consolidate(ai_client, *, force: bool = False) -> str:
    """Merge new diaries into memory.md once per day.

    逐天合并，单次提示保持在 8k 字以内，避免长日记撑爆模型上下文。
    """
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
    changed = False
    ai_available = True
    for day, text in diaries:
        merged = (
            await _request_memory(ai_client, existing, text[-1800:])
            if ai_available else ''
        )
        if not merged:
            if ai_available:
                logger.warning(
                    'AI 不支持当前长度的记忆整理，本次剩余日记改用本地事件记录'
                )
                ai_available = False
            merged = _fallback_memory(existing, day, text)
        if not merged:
            break
        existing = merged
        changed = True
        _write_memory(existing)
        _write_state({'last_consolidated': day.isoformat()})
        logger.info(f'长期记忆已更新到 {day.isoformat()}')

    if changed:
        logger.info(f'长期记忆整理完成：{MEMORY_FILE}')
        return existing.strip()
    return ''
