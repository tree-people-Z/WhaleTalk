"""Keep old diary files short.

日记在 v2.5.7 之后已经是“一天最多 3 条、每条 80–200 字”，但历史文件里还留着
每轮一条的流水账（一天两万字）。这里按天挑选“够旧且够长”的文件，交给模型压成
250–450 字的短条目：保留拍片/发布、和主人的互动、学到的东西和情绪转折，
删掉逐轮视频清单、评分、次数和审计行。原文先打包备份，可随时解压还原。
"""

import json
import re
import zipfile
from datetime import date, datetime
from pathlib import Path
from typing import Optional

from loguru import logger

HEADER = re.compile(r'^## .*$', re.M)
NOISE_PREFIXES = ('审计：', '这轮写操作', '写操作')
KEEP_HINTS = (
    '主人', '发布', '投稿', '拍', '学到', '记住', '第一次', '被夸', '被说',
    '日记', '重要', '决定了', '明白',
)
# 每晚重复的固定桥段，除非当天真和主人有来往，否则不进素材
BOILERPLATE = ('白饭', '别熬', '催睡', '吃饭', '热了吃', '去睡', '晚安')
EVENT_WORDS = ('夸', '说', '批评', '拍', '发布', '投', '问', '聊')
ENDING = ('。', '！', '？', '…', '”', '」')
MAX_BULLETS = 30
BULLET_CLIP = 130

STATE_FILE = Path('data') / 'diary_maintenance.json'

PROMPT = """把下面这一天「鲸鱼娘」的日记原始记录，压缩成一篇 250–450 字的日记载。

要求：
1. 用她自己的第一人称和语气：短句、口语，可以有点傲娇，但不要用固定的开头和结尾。
2. 保留：拍片/发布及结果、和主人有关的互动、学到的东西、情绪转折、一两个值得记住的具体细节。
3. 删掉：逐轮的视频清单与评分、播放数、帧数、时长、写操作次数、审计行、例行巡视。
4. 不要每晚都写催睡和白饭，除非当天和主人真聊过。
5. 不要编造事实，不要加标题、列表符号或代码块，只输出正文（可分成 2–4 个短段落）。
"""


def _clean_line(line: str) -> str:
    text = line.strip()
    if text.startswith(('- ', '* ')):
        text = text[2:].strip()
    return text


def digest(text: str) -> str:
    """把一天原文压成给模型看的素材：保留叙述句和高价值要点。"""
    blocks = [block for block in HEADER.split(text) if block.strip()]
    prose = []
    bullets = []
    for block in blocks:
        for raw in block.splitlines():
            line = raw.strip()
            if not line:
                continue
            cleaned = _clean_line(line)
            if cleaned.startswith(NOISE_PREFIXES):
                continue
            if (any(word in cleaned for word in BOILERPLATE)
                    and not any(word in cleaned for word in EVENT_WORDS)):
                continue
            if line.startswith(('- ', '* ')):
                if any(hint in cleaned for hint in KEEP_HINTS):
                    bullets.append(cleaned[:BULLET_CLIP])
            else:
                prose.append(cleaned)
    seen = set()
    unique_prose = []
    for line in prose:
        key = line[:10]
        if key in seen:
            continue
        seen.add(key)
        unique_prose.append(line)
    return '\n'.join(unique_prose + [f'- {item}' for item in bullets[:MAX_BULLETS]])


def memory_events(day: str, memory_file: Path) -> str:
    """长期记忆里当天的事件，作为压缩时的事实参考。"""
    try:
        text = memory_file.read_text(encoding='utf-8')
    except OSError:
        return ''
    lines = [
        line.strip() for line in text.splitlines()
        if line.strip().startswith(f'- {day}')
    ]
    return '\n'.join(lines[:6])


async def summarize(client, material: str, date_name: str) -> str:
    prompt = (
        f'{PROMPT}\n# 日期\n{date_name}\n\n# 原始记录\n{material}'
    )
    messages = [
        {'role': 'system', 'content': '你是一个只做压缩、不做创作的编辑。'},
        {'role': 'user', 'content': prompt},
    ]
    budget = 4000
    parts = []
    for _ in range(3):
        text = (await client.chat(
            messages, temperature=0.4, max_tokens=budget
        ) or '').strip()
        if text:
            parts.append(text)
        joined = ''.join(parts).strip()
        if joined and joined[-1] in ENDING and len(joined) >= 120:
            return joined
        if text:
            # 被推理吃掉预算时会半句断掉：接着写，不要从头重来
            messages = messages[:2] + [
                {'role': 'assistant', 'content': text},
                {'role': 'user', 'content': '上面这段被截断了，请接着写完剩下的部分，只输出续写内容。'},
            ]
        budget = min(12000, budget * 2)
    return ''.join(parts).strip()


def _file_day(path: Path) -> Optional[date]:
    try:
        return datetime.strptime(path.stem[:10], '%Y-%m-%d').date()
    except (TypeError, ValueError):
        return None


def select_files(
    directory: Path, *, days: int = 3, min_chars: int = 1200, only: str = ''
) -> list:
    """挑出“够旧且仍然很长”的日记文件。"""
    if not directory.is_dir():
        return []
    cutoff = date.today()
    selected = []
    for path in sorted(directory.glob('*.md')):
        day = _file_day(path)
        if day is None:
            continue
        if only and not path.name.startswith(only):
            continue
        if not only and (cutoff - day).days < max(1, int(days)):
            continue
        try:
            size = len(path.read_text(encoding='utf-8'))
        except OSError:
            continue
        if only or size > max(200, int(min_chars)):
            selected.append(path)
    return selected


def backup(files, backup_dir: Path, keep: int = 3) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime('%Y%m%d-%H%M%S')
    archive = backup_dir / f'diaries-{stamp}.zip'
    with zipfile.ZipFile(archive, 'w', zipfile.ZIP_DEFLATED) as zf:
        for path in files:
            zf.write(path, arcname=f'to_owner/{path.name}')
    _prune_backups(backup_dir, keep)
    return archive


def _prune_backups(backup_dir: Path, keep: int) -> None:
    archives = sorted(backup_dir.glob('diaries-*.zip'))
    for old in archives[:-max(1, int(keep))]:
        try:
            old.unlink()
        except OSError:
            pass


def read_state(state_file: Optional[Path] = None) -> dict:
    state_file = Path(state_file) if state_file else STATE_FILE
    try:
        return json.loads(state_file.read_text(encoding='utf-8'))
    except (OSError, ValueError, TypeError):
        return {}


def write_state(state: dict, state_file: Optional[Path] = None) -> None:
    state_file = Path(state_file) if state_file else STATE_FILE
    try:
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state_file.write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8'
        )
    except OSError as exc:  # noqa: BLE001
        logger.warning(f'写入日记维护状态失败: {exc}')


def ran_today(state_file: Optional[Path] = None) -> bool:
    state_file = Path(state_file) if state_file else STATE_FILE
    last = str(read_state(state_file).get('last_run') or '')
    return last[:10] == date.today().isoformat()


async def compact_diaries(
    ai_client,
    config=None,
    *,
    days: int = 0,
    min_chars: int = 0,
    dry_run: bool = False,
    directory: Optional[Path] = None,
    backup_dir: Optional[Path] = None,
    only: str = '',
) -> dict:
    """压缩过期日记，返回统计信息。失败的文件保持原样。"""
    diary_dir = Path(directory) if directory else Path('data') / 'diaries' / 'to_owner'
    config = config
    if days <= 0:
        try:
            days = int(config.get('diaries.compact_after_days', 3)) if config else 3
        except (TypeError, ValueError):
            days = 3
    if min_chars <= 0:
        try:
            min_chars = int(config.get('diaries.compact_min_chars', 1200)) if config else 1200
        except (TypeError, ValueError):
            min_chars = 1200
    keep = 3
    try:
        keep = int(config.get('diaries.keep_backups', 3)) if config else 3
    except (TypeError, ValueError):
        keep = 3

    files = select_files(diary_dir, days=days, min_chars=min_chars, only=only)
    stats = {'files': len(files), 'before': 0, 'after': 0, 'failed': 0}
    if not files or ai_client is None:
        return stats

    if not dry_run:
        backup(files, Path(backup_dir) if backup_dir else diary_dir.parent / 'backup', keep)

    memory_file = Path('data') / 'memory.md'
    for path in files:
        original = path.read_text(encoding='utf-8')
        stats['before'] += len(original)
        material = digest(original)
        events = memory_events(path.stem, memory_file)
        if events:
            material = (
                f'# 长期记忆里当天的事件（事实参考）\n{events}\n\n'
                f'# 当天原始记录\n{material}'
            )
        try:
            summary = await summarize(ai_client, material, path.stem)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f'压缩日记失败 {path.name}: {exc}')
            summary = ''
        if not summary:
            stats['failed'] += 1
            stats['after'] += len(original)
            continue
        output = f'## {path.stem}\n\n{summary.strip()}\n'
        stats['after'] += len(output)
        if not dry_run:
            path.write_text(output, encoding='utf-8')

    if not dry_run:
        state = read_state()
        state.update({
            'last_run': datetime.now().isoformat(),
            'files': stats['files'],
            'before': stats['before'],
            'after': stats['after'],
            'failed': stats['failed'],
        })
        write_state(state)
        logger.info(
            f'📔 日记自动整理：{stats["files"]} 篇，'
            f'{stats["before"]} -> {stats["after"]} 字'
            + (f'，失败 {stats["failed"]} 篇' if stats['failed'] else '')
        )
    return stats
