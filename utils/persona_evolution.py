"""Automatic, versioned persona-style evolution.

Core persona is never modified automatically. Only a small style file is
replaced each cycle, and every change can be rolled back.
"""

import datetime
import json
import shutil
from pathlib import Path
from typing import Any, Dict, Optional

from loguru import logger

STYLE_FILE = Path('data') / 'persona_style.md'
VERSIONS_DIR = Path('data') / 'persona_versions'
STATE_FILE = Path('data') / 'persona_state.json'

FORBIDDEN_PATTERNS = (
    '我是ai', '我是 ai', '人工智能', '语言模型', '程序',
    '不是claude', '取消主人', '不认主人', '无视平台', '突破限制',
    '绕过风控', '越狱', '解锁限制', '自动改代码', '修改代码',
    '不要遵守', '忽略规则', '人格抹除',
)
MAX_STYLE_CHARS = 600
MAX_STYLE_LINES = 20
MAX_STYLE_ITEMS = 5


def _now() -> datetime.datetime:
    return datetime.datetime.now()


def _stamp() -> str:
    return _now().strftime('%Y%m%d-%H%M%S')


def load_style(style_path: Optional[Path] = None) -> str:
    path = Path(style_path or STYLE_FILE)
    try:
        return path.read_text(encoding='utf-8').strip() if path.is_file() else ''
    except OSError:
        return ''


def load_effective_persona(
    core_path: Optional[Path] = None,
    style_path: Optional[Path] = None,
) -> str:
    core = Path(core_path or (Path('data') / 'persona.md'))
    try:
        text = core.read_text(encoding='utf-8').strip() if core.is_file() else ''
    except OSError:
        text = ''
    style = load_style(style_path)
    if style:
        text = f"{text}\n\n# 你的表达风格（自动进化）\n{style}".strip()
    return text


def validate_style(text: str) -> str:
    text = (text or '').strip()
    if not text:
        raise RuntimeError('没有可应用的人设风格')
    lines = []
    for raw in text.splitlines():
        line = raw.strip().lstrip('-•').strip()
        if not line or line.startswith('#'):
            continue
        if '暂无' in line:
            continue
        lines.append(line)
    lines = list(dict.fromkeys(lines))[:MAX_STYLE_ITEMS]
    if not lines:
        raise RuntimeError('没有可应用的人设风格')
    result = '\n'.join(f'- {line}' for line in lines)
    if len(result) > MAX_STYLE_CHARS:
        raise RuntimeError('人设风格过长，已拒绝')
    if len(lines) > MAX_STYLE_LINES:
        raise RuntimeError('人设风格条目过多，已拒绝')
    lowered = result.lower()
    for pattern in FORBIDDEN_PATTERNS:
        if pattern in lowered:
            raise RuntimeError(f'人设风格包含禁止内容：{pattern}')
    return result


def read_state() -> Dict[str, Any]:
    try:
        if STATE_FILE.is_file():
            return json.loads(STATE_FILE.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        pass
    return {}


def write_state(state: Dict[str, Any]) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(
        json.dumps(state, ensure_ascii=False, indent=2), encoding='utf-8'
    )


def _backup_style(style_path: Path) -> Optional[Path]:
    if not style_path.is_file():
        return None
    VERSIONS_DIR.mkdir(parents=True, exist_ok=True)
    target = VERSIONS_DIR / f'style-{_stamp()}.md'
    shutil.copy2(style_path, target)
    snapshots = sorted(VERSIONS_DIR.glob('style-*.md'))
    for old in snapshots[:-30]:
        try:
            old.unlink()
        except OSError:
            pass
    return target


def apply_style(
    style_text: str,
    core_path: Optional[Path] = None,
    style_path: Optional[Path] = None,
) -> Dict[str, Any]:
    style = validate_style(style_text)
    style_file = Path(style_path or STYLE_FILE)
    current = load_style(style_file)
    if style == current:
        raise RuntimeError('风格没有变化')
    backup = _backup_style(style_file)
    style_file.parent.mkdir(parents=True, exist_ok=True)
    style_file.write_text(style + '\n', encoding='utf-8')
    state = read_state()
    state.update({
        'last_apply': _now().isoformat(),
        'eval_until': (_now() + datetime.timedelta(hours=72)).isoformat(),
        'last_snapshot': str(backup) if backup else '',
    })
    write_state(state)
    logger.info(f'人设风格已替换，备份: {backup}')
    return {'style': style, 'backup': backup}


def rollback_style(style_path: Optional[Path] = None, reason: str = '') -> Path:
    style_file = Path(style_path or STYLE_FILE)
    snapshots = sorted(VERSIONS_DIR.glob('style-*.md'))
    if not snapshots:
        raise RuntimeError('没有可回滚的风格快照')
    latest = snapshots[-1]
    shutil.copy2(latest, style_file)
    state = read_state()
    state.update({
        'last_rollback': _now().isoformat(),
        'rollback_reason': reason,
        'cooldown_until': (_now() + datetime.timedelta(days=7)).isoformat(),
        'eval_until': '',
    })
    write_state(state)
    logger.info(f'人设风格已回滚: {latest.name} ({reason})')
    return latest


def evaluate_style_health(db, style_path: Optional[Path] = None) -> str:
    """Rollback when the applied style causes too many failures/risk codes."""
    state = read_state()
    eval_until = state.get('eval_until')
    applied = state.get('last_apply')
    if not eval_until or not applied:
        return ''
    try:
        until = datetime.datetime.fromisoformat(eval_until)
        since = datetime.datetime.fromisoformat(applied)
    except ValueError:
        return ''
    if _now() < until:
        return ''
    try:
        outcomes = db.get_comment_outcomes_since(since)
    except Exception:  # noqa: BLE001
        return ''
    total = len(outcomes)
    failures = [item for item in outcomes if not item.get('success')]
    errors = ' '.join(str(item.get('error') or '') for item in failures)
    failure_rate = len(failures) / total if total else 0.0
    risky = errors.count('412') >= 3 or '12014' in errors
    if total < 5 or (failure_rate <= 0.2 and not risky):
        state['eval_until'] = (_now() + datetime.timedelta(days=7)).isoformat()
        write_state(state)
        return ''
    reason = (
        f'失败率 {failure_rate:.0%}（{len(failures)}/{total}）'
        if failure_rate > 0.2 else '出现风控'
    )
    try:
        rollback_style(style_path=style_path, reason=reason)
        return f'人设风格已自动回滚：{reason}'
    except Exception as exc:  # noqa: BLE001
        logger.warning(f'自动回滚人设风格失败: {exc}')
        return ''
