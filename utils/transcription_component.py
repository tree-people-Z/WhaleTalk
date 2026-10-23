"""On-demand local transcription component for the portable build.

The base portable package stays small; when the user asks for local
transcription the app downloads a component ZIP containing faster-whisper and
its dependencies, extracted next to the user's data so updates keep it.
"""

import json
import os
import shutil
import sys
import zipfile
from pathlib import Path
from typing import Any, Callable, List, Optional

from loguru import logger

COMPONENT_VERSION = 1
COMPONENT_ASSET_NAME = "WhaleTalk-Transcription-Win64.zip"
COMPONENT_URL = (
    "https://github.com/tree-people-Z/WhaleTalk/releases/download/"
    f"v1.5.0/{COMPONENT_ASSET_NAME}"
)
COMPONENT_SHA256 = "3ddd18c6b2f7fce66f068b5d4dd8d2736dfbc39105cc902afb8dcbc18f37f4b1"  # filled by the build script, verified on download

COMPONENT_DIR = Path("data/transcription")
SITE_PACKAGES_NAME = "site-packages"
MARKER_NAME = "component.json"

_PATH_READY = False
_DLL_HANDLES: List[Any] = []


def component_dir() -> Path:
    return COMPONENT_DIR


def site_packages_dir() -> Path:
    return COMPONENT_DIR / SITE_PACKAGES_NAME


def is_installed() -> bool:
    """Return True when a usable component is already unpacked."""
    marker = COMPONENT_DIR / MARKER_NAME
    site = site_packages_dir()
    if not marker.is_file() or not site.is_dir():
        return False
    try:
        data = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return False
    return int(data.get("component_version", 0)) >= COMPONENT_VERSION


def component_info() -> dict:
    return {
        "installed": is_installed(),
        "version": COMPONENT_VERSION,
        "path": str(COMPONENT_DIR.resolve()),
    }


def ensure_importable() -> bool:
    """Make the downloaded component importable by this frozen application."""
    global _PATH_READY
    if not is_installed():
        return False
    if _PATH_READY:
        return True
    site = site_packages_dir().resolve()
    if str(site) not in sys.path:
        # Append so bundled modules still win over same-named packages.
        sys.path.append(str(site))
    if sys.platform == "win32":
        for directory in sorted({path.parent for path in site.rglob("*.dll")}):
            try:
                _DLL_HANDLES.append(os.add_dll_directory(str(directory)))
            except OSError as exc:
                logger.debug(f"无法加入 DLL 搜索目录 {directory}: {exc}")
    _PATH_READY = True
    logger.info(f"本地识别组件已启用: {site}")
    return True


def configure_hf_endpoint() -> str:
    """Prefer huggingface.co, fall back to the hf-mirror mirror."""
    current = os.environ.get("HF_ENDPOINT")
    if current:
        return current
    endpoint = "https://huggingface.co"
    try:
        import requests

        requests.head(endpoint, timeout=5, allow_redirects=True)
    except Exception as exc:  # noqa: BLE001
        endpoint = "https://hf-mirror.com"
        os.environ["HF_ENDPOINT"] = endpoint
        logger.warning(f"无法连接 huggingface.co，改用镜像下载模型: {exc}")
    return endpoint


def _safe_extract(archive: zipfile.ZipFile, target: Path) -> None:
    base = target.resolve()
    for member in archive.infolist():
        resolved = (base / member.filename).resolve()
        if not resolved.is_relative_to(base):
            raise RuntimeError("识别组件包包含非法路径")
    archive.extractall(target)


def extract_component(archive_path: Path) -> Path:
    """Extract a component ZIP into the data directory."""
    archive_path = Path(archive_path)
    staging = COMPONENT_DIR / "extracted"
    shutil.rmtree(staging, ignore_errors=True)
    staging.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(archive_path) as archive:
        _safe_extract(archive, staging)
    if not (staging / SITE_PACKAGES_NAME).is_dir() or not (staging / MARKER_NAME).is_file():
        shutil.rmtree(staging, ignore_errors=True)
        raise RuntimeError("识别组件包结构异常")
    COMPONENT_DIR.mkdir(parents=True, exist_ok=True)
    for item in staging.iterdir():
        target = COMPONENT_DIR / item.name
        if target.is_dir():
            shutil.rmtree(target)
        elif target.exists():
            target.unlink()
        shutil.move(str(item), str(target))
    shutil.rmtree(staging, ignore_errors=True)
    logger.info(f"本地识别组件已解压: {COMPONENT_DIR.resolve()}")
    return COMPONENT_DIR


def download_component(
    progress: Optional[Callable[[int, int], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
) -> Path:
    """Download, verify and unpack the transcription component."""
    from utils.updater import download_update

    if is_installed():
        return COMPONENT_DIR
    if not COMPONENT_SHA256:
        raise RuntimeError("当前版本未配置识别组件校验值，无法安装")
    COMPONENT_DIR.mkdir(parents=True, exist_ok=True)
    archive = COMPONENT_DIR / "component.zip"
    try:
        download_update(
            COMPONENT_URL,
            archive,
            COMPONENT_SHA256,
            progress=progress,
            should_cancel=should_cancel,
        )
        return extract_component(archive)
    finally:
        archive.unlink(missing_ok=True)
