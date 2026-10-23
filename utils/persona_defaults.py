"""Create the bundled default persona file on first launch."""

from pathlib import Path
from typing import Optional

from loguru import logger

PROJECT_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_PERSONA_ASSET = PROJECT_ROOT / "assets" / "default_persona.md"
DEFAULT_PERSONA_FILE = "data/persona.md"


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
