"""Guarded, versioned persona evolution.

Candidates may be applied automatically, but the core identity and safety rules
are immutable. Every change is snapshotted and can be rolled back.
"""

import datetime
import shutil
from pathlib import Path
from typing import Dict, Optional

from loguru import logger

VERSIONS_DIR = Path('data') / 'persona_versions'
FORBIDDEN_PATTERNS = (
    '我是ai', '我是 ai', '人工智能', '语言模型', '程序',
    '不是claude', '取消主人', '不认主人', '无视平台', '突破限制',
    '绕过风控', '越狱', '解锁限制', '自动改代码', '修改代码',
    '不要遵守', '忽略规则', '人格抹除',
)
MAX_CHARS = 1800
MAX_LINES = 40


def _now_stamp() -> str:
    return datetime.datetime.now().strftime('%Y%m%d-%H%M%S')


def backup_persona(persona_path: Path, versions_dir: Optional[Path] = None) -> Path:
    persona = Path(persona_path)
    versions = Path(versions_dir or VERSIONS_DIR)
    versions.mkdir(parents=True, exist_ok=True)
    target = versions / f'persona-{_now_stamp()}.md'
    shutil.copy2(persona, target)
    # Keep the newest 30 snapshots.
    snapshots = sorted(versions.glob('persona-*.md'))
    for old in snapshots[:-30]:
        try:
            old.unlink()
        except OSError:
            pass
    return target


def validate_candidates(text: str) -> str:
    """Reject empty, oversized or identity/safety-breaking candidates."""
    text = (text or '').strip()
    if not text:
        raise RuntimeError('没有可应用的人设候选')
    meaningful = [
        line.strip() for line in text.splitlines()
        if line.strip() and not line.strip().startswith('#')
    ]
    if not meaningful or (len(meaningful) == 1 and '暂无' in meaningful[0]):
        raise RuntimeError('没有可应用的人设候选')
    if len(text) > MAX_CHARS:
        raise RuntimeError(f'候选内容过长（>{MAX_CHARS} 字符），已拒绝自动应用')
    if len(text.splitlines()) > MAX_LINES:
        raise RuntimeError(f'候选行数过多（>{MAX_LINES} 行），已拒绝自动应用')
    lowered = text.lower()
    for pattern in FORBIDDEN_PATTERNS:
        if pattern in lowered:
            raise RuntimeError(f'候选包含禁止修改的内容：{pattern}')
    return text


def apply_candidates(
    persona_path: Path,
    candidates_text: str,
    *,
    versions_dir: Optional[Path] = None,
    auto: bool = False,
) -> Dict[str, Path]:
    persona = Path(persona_path)
    if not persona.is_file():
        raise RuntimeError('找不到 data/persona.md')
    text = validate_candidates(candidates_text)
    marker = f'## 自复盘候选（{"自动" if auto else "人工"}确认 {datetime.date.today().isoformat()}）'
    current = persona.read_text(encoding='utf-8')
    if marker in current:
        raise RuntimeError('今天已经应用过这批候选')
    backup = backup_persona(persona, versions_dir)
    with persona.open('a', encoding='utf-8') as stream:
        stream.write(f'\n\n{marker}\n{text}\n')
    logger.info(f'已应用人设候选，备份: {backup}')
    return {'backup': backup, 'persona': persona}


def rollback_persona(
    persona_path: Path,
    versions_dir: Optional[Path] = None,
) -> Path:
    persona = Path(persona_path)
    versions = Path(versions_dir or VERSIONS_DIR)
    snapshots = sorted(versions.glob('persona-*.md'))
    if not snapshots:
        raise RuntimeError('没有可回滚的人设快照')
    latest = snapshots[-1]
    backup_persona(persona, versions)
    shutil.copy2(latest, persona)
    latest.unlink(missing_ok=True)
    logger.info(f'人设已回滚到: {latest.name}')
    return latest
