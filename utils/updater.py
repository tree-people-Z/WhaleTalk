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

from loguru import logger

APP_NAME = "鲸语"
APP_VERSION = "2.5.12"

GITHUB_REPOSITORY = "tree-people-Z/WhaleTalk"
RELEASES_URL = f"https://github.com/{GITHUB_REPOSITORY}/releases"
REPOSITORY_URL = f"https://github.com/{GITHUB_REPOSITORY}"
LATEST_RELEASE_API = f"https://api.github.com/repos/{GITHUB_REPOSITORY}/releases/latest"
# 未登录的 API 只有 60 次/小时；共用出口 IP 时很容易 403。
# 这两个地址不受 API 配额限制，用作兜底。
RELEASES_LATEST_PAGE = f"{RELEASES_URL}/latest"
RELEASES_ATOM = f"{RELEASES_URL}.atom"
WINDOWS_ASSET_NAME = "WhaleTalk-Windows-x64.zip"
CHECKSUMS_ASSET_NAME = "SHA256SUMS.txt"

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


def _find_checksums_asset(release: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Pick the release's SHA256SUMS.txt asset, if the maintainer uploaded one."""
    for asset in release.get("assets", []):
        name = str(asset.get("name", "")).lower()
        if name in {"sha256sums.txt", "sha256sums", "checksums.txt"}:
            return asset
    return None


def checksum_from_file(text: str, filename: str) -> str:
    """Return the hex digest listed for ``filename`` in a SHA256SUMS file."""
    for line in str(text or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split()
        if len(parts) < 2:
            continue
        digest, listed = parts[0].lower(), parts[-1].lstrip("*").strip()
        if listed == filename or listed.endswith("/" + filename):
            return digest if re.fullmatch(r"[0-9a-f]{64}", digest) else ""
    return ""


def _download_url(tag: str, name: str) -> str:
    return f"{RELEASES_URL}/download/{tag}/{name}"


def _html_to_text(value: str) -> str:
    """粗略把发布说明的 HTML 变成纯文本。"""
    from html import unescape

    text = re.sub(r'<(script|style)[^>]*>.*?</\1>', '', value or '', flags=re.S | re.I)
    text = re.sub(r'<br\s*/?>', '\n', text, flags=re.I)
    text = re.sub(r'</(p|div|li|h\d)>', '\n', text, flags=re.I)
    text = re.sub(r'<[^>]+>', '', text)
    text = unescape(text)
    return re.sub(r'\n{3,}', '\n\n', text).strip()[:4000]


def _latest_tag_from_redirect(timeout: float) -> str:
    import requests

    try:
        response = requests.get(
            RELEASES_LATEST_PAGE, timeout=timeout,
            headers={"User-Agent": _UPDATE_HEADERS["User-Agent"]},
            allow_redirects=False,
        )
    except Exception:  # noqa: BLE001
        return ''
    location = str(response.headers.get('Location') or '')
    marker = '/releases/tag/'
    if response.status_code in (301, 302, 303, 307, 308) and marker in location:
        return location.rsplit(marker, 1)[-1].strip()
    return ''


def _tag_and_notes_from_atom(timeout: float) -> tuple:
    import requests
    from xml.etree import ElementTree

    try:
        response = requests.get(
            RELEASES_ATOM, timeout=timeout,
            headers={"User-Agent": _UPDATE_HEADERS["User-Agent"]},
        )
        response.raise_for_status()
        root = ElementTree.fromstring(response.content)
    except Exception:  # noqa: BLE001
        return '', ''
    ns = {'a': 'http://www.w3.org/2005/Atom'}
    entry = root.find('a:entry', ns)
    if entry is None:
        return '', ''
    link = entry.find('a:link', ns)
    href = str(link.get('href') or '') if link is not None else ''
    tag = href.rsplit('/releases/tag/', 1)[-1].strip() if '/releases/tag/' in href else ''
    content = entry.find('a:content', ns)
    notes = _html_to_text(content.text if content is not None else '')
    return tag, notes


def _asset_exists(url: str, timeout: float = 8.0) -> bool:
    import requests

    try:
        response = requests.head(
            url, timeout=timeout, allow_redirects=True,
            headers={"User-Agent": _UPDATE_HEADERS["User-Agent"]},
        )
        return int(getattr(response, 'status_code', 500) or 500) < 400
    except Exception:  # noqa: BLE001
        return False


def _check_without_api(timeout: float = 10.0) -> Optional[Dict[str, Any]]:
    """API 被限流（403）或连不上时的兜底：用发布页和 Atom 源判断版本。"""
    tag = _latest_tag_from_redirect(timeout)
    atom_tag, notes = _tag_and_notes_from_atom(timeout)
    tag = tag or atom_tag
    if not tag:
        return None
    version = tag[1:] if tag[:1] in ('v', 'V') else tag
    if not is_newer_version(version, APP_VERSION):
        return {"status": "latest", "version": APP_VERSION}
    asset_url = _download_url(tag, WINDOWS_ASSET_NAME)
    if not _asset_exists(asset_url, timeout=max(5.0, timeout)):
        return {
            "status": "update",
            "version": version or tag,
            "tag": tag,
            "url": f"{RELEASES_URL}/tag/{tag}",
            "notes": notes,
            "asset_url": "",
            "asset_name": "",
            "asset_size": 0,
            "asset_digest": "",
            "checksums_url": "",
        }
    return {
        "status": "update",
        "version": version or tag,
        "tag": tag,
        "url": f"{RELEASES_URL}/tag/{tag}",
        "notes": notes,
        "asset_url": asset_url,
        "asset_name": WINDOWS_ASSET_NAME,
        "asset_size": 0,
        "asset_digest": "",
        "checksums_url": _download_url(tag, CHECKSUMS_ASSET_NAME),
    }


def check_for_update(timeout: float = 10.0) -> Dict[str, Any]:
    """Ask GitHub for the latest release.

    Returns a dict with ``status`` set to ``update``, ``latest`` or ``error``.
    It never raises so the GUI can call it from a worker thread unguarded.
    API 被限流时自动改用发布页 / Atom 源，避免“检查更新失败”。
    """
    api_message = ''
    release = None
    try:
        import requests

        response = requests.get(LATEST_RELEASE_API, timeout=timeout, headers=_UPDATE_HEADERS)
        if response.status_code == 200:
            release = response.json()
        elif response.status_code == 404:
            api_message = "没有找到发布记录"
        else:
            api_message = f"GitHub 返回 HTTP {response.status_code}"
    except Exception as exc:  # requests errors, timeouts, invalid JSON, ...
        api_message = str(exc) or exc.__class__.__name__

    if release is None:
        fallback = _check_without_api(timeout)
        if fallback is not None:
            return fallback
        return {"status": "error", "message": api_message or "检查更新失败"}

    tag = str(release.get("tag_name") or "")
    version = tag[1:] if tag[:1] in ("v", "V") else tag
    if not is_newer_version(version, APP_VERSION):
        return {"status": "latest", "version": APP_VERSION}

    asset = _find_windows_asset(release) or {}
    checksums = _find_checksums_asset(release) or {}
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
        "checksums_url": checksums.get("browser_download_url") or "",
    }


def fetch_expected_digest(
    checksums_url: str,
    asset_name: str,
    timeout: float = 20.0,
) -> str:
    """Download SHA256SUMS.txt and return the digest for ``asset_name``."""
    if not checksums_url or not asset_name:
        return ""
    import requests

    response = requests.get(
        checksums_url, timeout=timeout,
        headers={"User-Agent": _UPDATE_HEADERS["User-Agent"]},
    )
    response.raise_for_status()
    return checksum_from_file(response.text, asset_name)


def download_update(
    asset_url: str,
    destination: Path,
    expected_digest: str = "",
    progress: Optional[Callable[[int, int], None]] = None,
    should_cancel: Optional[Callable[[], bool]] = None,
    timeout: float = 60.0,
    asset_name: str = "",
    checksums_url: str = "",
) -> Path:
    """Stream the release asset to ``destination`` and verify its digest.

    优先使用 GitHub 提供的 digest；没有时退回发布页的 SHA256SUMS.txt。
    """
    import requests

    if not expected_digest and checksums_url and asset_name:
        try:
            expected_digest = fetch_expected_digest(checksums_url, asset_name)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f"读取 SHA256SUMS.txt 失败: {exc}")
    if not expected_digest:
        logger.warning("更新包没有可用的 SHA256 校验值，将跳过完整性校验")

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
        if not re.fullmatch(r"[0-9a-f]{64}", expected):
            destination.unlink(missing_ok=True)
            raise RuntimeError("更新包校验值格式不正确")
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
    $app = Join-Path $Target 'WhaleTalk.exe'
    function Wait-Exit([int]$seconds) {{
        $until = (Get-Date).AddSeconds($seconds)
        while ((Get-Process -Id {pid} -ErrorAction SilentlyContinue) -and ((Get-Date) -lt $until)) {{
            Start-Sleep -Milliseconds 500
        }}
        return -not (Get-Process -Id {pid} -ErrorAction SilentlyContinue)
    }}
    $gone = Wait-Exit 45
    if (-not $gone) {{
        # 界面可能卡在长网络请求上拒绝了关闭：先请它自己体面退出。
        Write-Log 'instance still running; sending --quit'
        $helper = $null
        try {{
            $helper = Start-Process -FilePath $app -ArgumentList '--quit' -PassThru -WindowStyle Hidden
        }} catch {{
            Write-Log "quit helper failed to start: $_"
        }}
        $gone = Wait-Exit 30
        if (-not $gone) {{
            # 旧版本不认识 --quit，会拉起第二个界面（单实例提示框），清掉它。
            if ($helper -and -not $helper.HasExited) {{
                Stop-Process -Id $helper.Id -Force -ErrorAction SilentlyContinue
            }}
            Write-Log 'quit request was ignored (older build?)'
        }}
    }}
    if (-not $gone) {{
        Write-Log 'forcing stop of the running instance'
        Stop-Process -Id {pid} -Force -ErrorAction SilentlyContinue
        Start-Sleep -Milliseconds 1500
    }}
    Start-Sleep -Milliseconds 500
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
