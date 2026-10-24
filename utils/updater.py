"""Application version, GitHub release checking and one-click updates."""

import hashlib
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path
from typing import Any, Callable, Dict, Optional

APP_NAME = "鲸语"
APP_VERSION = "1.7.9"

GITHUB_REPOSITORY = "tree-people-Z/WhaleTalk"
RELEASES_URL = f"https://github.com/{GITHUB_REPOSITORY}/releases"
REPOSITORY_URL = f"https://github.com/{GITHUB_REPOSITORY}"
LATEST_RELEASE_API = f"https://api.github.com/repos/{GITHUB_REPOSITORY}/releases/latest"

_VERSION_PATTERN = re.compile(r"\d+")
_UPDATE_HEADERS = {
    "Accept": "application/vnd.github+json",
    "User-Agent": f"WhaleTalk/{APP_VERSION}",
}
_CHUNK_SIZE = 256 * 1024


class UpdateCancelled(Exception):
    """Raised when the user cancels a download."""


def parse_version(value: Any) -> tuple:
    """Turn a version such as ``v1.2.3`` into a comparable tuple."""
    if value is None:
        return ()
    return tuple(int(part) for part in _VERSION_PATTERN.findall(str(value))[:4])


def is_newer_version(candidate: Any, current: Any) -> bool:
    """Return True when ``candidate`` is newer than ``current``."""
    candidate_key = parse_version(candidate)
    current_key = parse_version(current)
    if not candidate_key:
        return False
    width = max(len(candidate_key), len(current_key))
    candidate_key += (0,) * (width - len(candidate_key))
    current_key += (0,) * (width - len(current_key))
    return candidate_key > current_key


def _find_windows_asset(release: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Pick the portable ZIP asset from a release payload."""
    for asset in release.get("assets", []):
        name = str(asset.get("name", ""))
        if name.lower().endswith(".zip") and "windows" in name.lower():
            return asset
    for asset in release.get("assets", []):
        if str(asset.get("name", "")).lower().endswith(".zip"):
            return asset
    return None


def check_for_update(timeout: float = 10.0) -> Dict[str, Any]:
    """Ask GitHub for the latest release.

    Returns a dict with ``status`` set to ``update``, ``latest`` or ``error``.
    It never raises so the GUI can call it from a worker thread unguarded.
    """
    try:
        import requests

        response = requests.get(LATEST_RELEASE_API, timeout=timeout, headers=_UPDATE_HEADERS)
        if response.status_code == 404:
            return {"status": "error", "message": "没有找到发布记录"}
        if response.status_code != 200:
            return {"status": "error", "message": f"GitHub 返回 HTTP {response.status_code}"}
        release = response.json()
    except Exception as exc:  # requests errors, timeouts, invalid JSON, ...
        return {"status": "error", "message": str(exc) or exc.__class__.__name__}

    tag = str(release.get("tag_name") or "")
    version = tag[1:] if tag[:1] in ("v", "V") else tag
    if not is_newer_version(version, APP_VERSION):
        return {"status": "latest", "version": APP_VERSION}

    asset = _find_windows_asset(release) or {}
    return {
        "status": "update",
        "version": version or tag,
        "tag": tag,
        "url": release.get("html_url") or RELEASES_URL,
        "notes": release.get("body") or "",
        "asset_url": asset.get("browser_download_url") or "",
        "asset_name": asset.get("name") or "",
        "asset_size": asset.get("size") or 0,
        "asset_digest": asset.get("digest") or "",
    }


def download_update(
    asset_url: str,
    destination: Path,
    expected_digest: str = "",
    progress: Optional[Callable[[int, int], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
    timeout: float = 60.0,
) -> Path:
    """Stream the release asset to ``destination`` and verify its digest."""
    import requests

    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    hasher = hashlib.sha256()
    downloaded = 0
    with requests.get(
        asset_url, stream=True, timeout=timeout, headers={"User-Agent": _UPDATE_HEADERS["User-Agent"]}
    ) as response:
        response.raise_for_status()
        total = int(response.headers.get("Content-Length") or 0)
        with open(destination, "wb") as handle:
            for chunk in response.iter_content(_CHUNK_SIZE):
                if should_cancel is not None and should_cancel():
                    destination.unlink(missing_ok=True)
                    raise UpdateCancelled()
                if not chunk:
                    continue
                handle.write(chunk)
                hasher.update(chunk)
                downloaded += len(chunk)
                if progress is not None:
                    progress(downloaded, total)

    if expected_digest:
        expected = expected_digest.split(":", 1)[-1].strip().lower()
        if hasher.hexdigest().lower() != expected:
            destination.unlink(missing_ok=True)
            raise RuntimeError("更新包校验失败，请重试")
    return destination


def _safe_extract(archive: zipfile.ZipFile, target: Path) -> None:
    base = target.resolve()
    for member in archive.infolist():
        resolved = (base / member.filename).resolve()
        if not resolved.is_relative_to(base):
            raise RuntimeError("更新包包含非法路径")
    archive.extractall(target)


def extract_update(zip_path: Path, extract_dir: Path) -> Path:
    """Extract the portable ZIP and return the folder that contains WhaleTalk.exe."""
    extract_dir = Path(extract_dir)
    shutil.rmtree(extract_dir, ignore_errors=True)
    extract_dir.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(zip_path) as archive:
        _safe_extract(archive, extract_dir)
    for executable in extract_dir.rglob("WhaleTalk.exe"):
        return executable.parent
    raise RuntimeError("更新包结构异常：未找到 WhaleTalk.exe")


_UPDATE_SCRIPT = """$ErrorActionPreference = 'Stop'
$Target = {target}
$Source = {source}
$Staging = {staging}
$Log = Join-Path $Staging 'update.log'
function Write-Log($message) {{
    Add-Content -LiteralPath $Log -Value ("{{0}} {{1}}" -f (Get-Date -Format 'HH:mm:ss'), $message) -Encoding UTF8
}}
try {{
    $deadline = (Get-Date).AddSeconds(180)
    while ((Get-Process -Id {pid} -ErrorAction SilentlyContinue) -and ((Get-Date) -lt $deadline)) {{
        Start-Sleep -Milliseconds 500
    }}
    Start-Sleep -Milliseconds 800
    Write-Log "applying $Source to $Target"
    $excluded = Join-Path $Target 'data'
    $null = robocopy $Source $Target /MIR /XD $excluded /R:1 /W:1 /NFL /NDL /NJH /NJS /NP
    $code = $LASTEXITCODE
    Write-Log "robocopy exit code: $code"
    if ($code -lt 8) {{
        Write-Log 'update applied'
    }} else {{
        Write-Log 'update copy failed; restarting previous files'
    }}
    Start-Process -FilePath (Join-Path $Target 'WhaleTalk.exe') -WorkingDirectory $Target
}} catch {{
    Write-Log "update error: $_"
    try {{ Start-Process -FilePath (Join-Path $Target 'WhaleTalk.exe') -WorkingDirectory $Target }} catch {{}}
}} finally {{
    Remove-Item -LiteralPath (Join-Path $Staging 'update.zip') -Force -ErrorAction SilentlyContinue
    Remove-Item -LiteralPath (Join-Path $Staging 'extracted') -Recurse -Force -ErrorAction SilentlyContinue
    $cleanup = 'ping -n 4 127.0.0.1 >nul & rmdir /s /q "' + $Staging + '"'
    Start-Process -FilePath 'cmd.exe' -ArgumentList '/c', $cleanup -WindowStyle Hidden
}}
"""


def update_staging_dir() -> Path:
    """Directory beside the portable install used for downloads and scripts."""
    install_dir = Path(sys.executable).resolve().parent
    return install_dir.parent / f"{install_dir.name}.update"


def _powershell_quote(value: Path) -> str:
    return "'" + str(value).replace("'", "''") + "'"


def launch_update_installer(source: Path, install_dir: Path, pid: int) -> Path:
    """Write and start the updater script that replaces files after this process exits."""
    staging = update_staging_dir()
    staging.mkdir(parents=True, exist_ok=True)
    script = staging / "apply_update.ps1"
    script.write_text(
        _UPDATE_SCRIPT.format(
            target=_powershell_quote(install_dir),
            source=_powershell_quote(source),
            staging=_powershell_quote(staging),
            pid=int(pid),
        ),
        encoding="utf-8-sig",
    )
    creationflags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
    subprocess.Popen(
        [
            "powershell.exe",
            "-NoProfile",
            "-ExecutionPolicy",
            "Bypass",
            "-WindowStyle",
            "Hidden",
            "-File",
            str(script),
        ],
        cwd=tempfile.gettempdir(),
        creationflags=creationflags,
        close_fds=True,
    )
    return script
