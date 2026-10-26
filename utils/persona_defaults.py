"""Create the bundled default persona file on first launch."""

from pathlib import Path
from typing import Optional

from loguru import logger

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PERSONA_ASSET = PROJECT_ROOT / "assets" / "default_persona.md"
DEFAULT_PERSONA_FILE = "data/persona.md"


def load_persona(persona_file: str = DEFAULT_PERSONA_FILE, max_chars: int = 4000) -> str:
    """Read the user-owned core persona; never modify it automatically."""
    try:
        path = Path(persona_file)
        if path.is_file():
            return path.read_text(encoding='utf-8').strip()[:max_chars]
    except OSError:
        pass
    return ''


def load_configured_persona(config, max_chars: int = 4000) -> str:
    """Load the persona configured by the user, with a small fallback."""
    if config is None or not config.get('persona.enabled', True):
        return ''
    content = load_persona(
        config.get('persona.persona_file', DEFAULT_PERSONA_FILE), max_chars
    )
    if content:
        return content
    name = config.get('persona.name', 'AI助手')
    return f"你是 {name}，一个友好的AI助手。"


def ensure_default_persona(persona_file: str = DEFAULT_PERSONA_FILE) -> Optional[Path]:
    """Copy the bundled default persona when the user's persona file is missing.

    Existing persona files are never overwritten, so user edits survive upgrades.
    """
    target = Path(persona_file)
    if target.exists():
        return target
    try:
        if not DEFAULT_PERSONA_ASSET.exists():
            logger.warning("未找到默认人设资源，跳过创建默认人设")
            return None
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            DEFAULT_PERSONA_ASSET.read_text(encoding="utf-8"), encoding="utf-8"
        )
        logger.info(f"已创建默认人设文件: {target}")
        return target
    except OSError as exc:
        logger.warning(f"创建默认人设文件失败: {exc}")
        return None
