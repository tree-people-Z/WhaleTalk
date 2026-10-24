"""Extract the bundled ffmpeg payload on first run of the single-file build."""
import sys
import zipfile
from pathlib import Path

from loguru import logger


def ensure_ffmpeg() -> bool:
    """Extract ffmpeg.zip next to the exe once, for the onefile build."""
    if not getattr(sys, 'frozen', False):
        return False
    base = Path(sys.executable).resolve().parent
    target_dir = base / 'data' / 'ffmpeg'
    target = target_dir / 'ffmpeg.exe'
    if target.is_file():
        return True

    candidates = []
    meipass = getattr(sys, '_MEIPASS', None)
    if meipass:
        candidates.append(Path(meipass) / 'assets' / 'ffmpeg.zip')
    candidates.append(base / '_internal' / 'assets' / 'ffmpeg.zip')
    for archive in candidates:
        if not archive.is_file():
            continue
        try:
            target_dir.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(archive) as bundle:
                for info in bundle.infolist():
                    name = Path(info.filename).name
                    if name not in ('ffmpeg.exe', 'FFMPEG_LICENSE.txt'):
                        continue
                    with bundle.open(info) as source, open(target_dir / name, 'wb') as dest:
                        dest.write(source.read())
            logger.info(f"已解压内置 ffmpeg: {target}")
            return target.is_file()
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"解压内置 ffmpeg 失败: {exc}")
    return False
