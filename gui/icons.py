"""Load bundled SVG icons."""

from pathlib import Path

from PyQt6.QtGui import QIcon

_ICON_DIR = Path(__file__).resolve().parent.parent / 'assets' / 'icons'
_cache = {}


def load_icon(name: str) -> QIcon:
    """Load an SVG icon from assets/icons by name (without extension)."""
    key = str(name or '').strip()
    if not key:
        return QIcon()
    cached = _cache.get(key)
    if cached is not None:
        return cached
    path = _ICON_DIR / f'{key}.svg'
    icon = QIcon(str(path)) if path.is_file() else QIcon()
    _cache[key] = icon
    return icon
