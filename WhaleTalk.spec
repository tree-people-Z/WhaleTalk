# Build with: python -m PyInstaller --clean --noconfirm WhaleTalk.spec
from pathlib import Path
import os
import site
import sys

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

project_root = Path(SPECPATH)
ONEFILE = os.environ.get("WHALETALK_ONEFILE") == "1"
CONSOLE = os.environ.get("WHALETALK_CONSOLE") == "1"

datas = [
    (str(project_root / "assets"), "assets"),
    # requirements files are only used by the source bootstrap (pip install); the
    # frozen build is self-contained and never reads them.
]
# bilibili_api registers its HTTP clients by importing submodules dynamically, so
# the static analysis cannot see bilibili_api.clients.*; collect them explicitly.
# The package also ships JSON tables under bilibili_api/data.
hiddenimports = ["bilibili_api"] + collect_submodules("bilibili_api")
hiddenimports += [
    "gui.memory_worker",
    "core.conversation_agent",
    "core.long_term_memory",
    "core.daily_diary",
    "core.agent_protocol",
    "core.comment_events",
    "core.comment_images",
    "core.bilibili_dm",
    "core.bilibili_comment",
    "core.bilibili_interact",
    "utils.media_library",
    "utils.probability",
    "utils.reply_scope",
]
datas += collect_data_files("bilibili_api")
if ONEFILE:
    ffmpeg_payload = project_root / "build" / "ffmpeg.zip"
    if ffmpeg_payload.is_file():
        datas.append((str(ffmpeg_payload), "assets"))

runtime_names = {
    "vcruntime140.dll", "vcruntime140_1.dll", "msvcp140.dll",
    "msvcp140_1.dll", "msvcp140_2.dll", "msvcp140_atomic_wait.dll",
    "msvcp140_codecvt_ids.dll",
}
runtime_sources = {
    "vcruntime140.dll": Path(sys.prefix) / "vcruntime140.dll",
    "vcruntime140_1.dll": Path(sys.prefix) / "vcruntime140_1.dll",
}
system_runtime = Path(os.environ["SystemRoot"]) / "System32"
for name in runtime_names - runtime_sources.keys():
    runtime_sources[name] = system_runtime / name

analysis = Analysis(
    [str(project_root / "main.py")],
    pathex=[str(project_root)],
    binaries=[],
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "pytest", "tests", "torch", "torchaudio", "torchvision", "torchmetrics",
        "scipy", "pandas", "gradio", "transformers", "librosa", "lightning",
        "sklearn", "tensorflow", "onnxruntime", "cv2", "numba", "sympy",
        "numpy", "pandas-stubs", "IPython", "matplotlib", "tkinter",
        # Pulled in by optional dependency paths but unused by WhaleTalk.
        "grpc", "google", "cryptography",
    ],
    noarchive=False,
    optimize=0,
)

# Qt ships PDF support, every locale and every plugin by default. WhaleTalk is a
# widgets-only Chinese app: keep the platform/style/image plugins it needs and a
# couple of Qt translations, but drop the unused PDF DLL and bulk locale data.
_QT_ALLOWED_PLUGIN_DIRS = {"platforms", "styles", "imageformats", "iconengines"}
_QT_KEPT_TRANSLATIONS = {"qtbase_zh_CN.qm", "qt_zh_CN.qm", "qtbase_en.qm"}


def _keep_qt_entry(dest: str) -> bool:
    normalized = dest.replace("\\", "/")
    if normalized.endswith("/Qt6/bin/Qt6Pdf.dll"):
        return False
    if "/Qt6/translations/" in normalized:
        return Path(normalized).name in _QT_KEPT_TRANSLATIONS
    if "/Qt6/plugins/" in normalized:
        category = normalized.split("/Qt6/plugins/", 1)[1].split("/", 1)[0]
        return category in _QT_ALLOWED_PLUGIN_DIRS
    return True


analysis.datas = [entry for entry in analysis.datas if _keep_qt_entry(entry[0])]
analysis.binaries = [
    entry for entry in analysis.binaries if _keep_qt_entry(entry[0])
]

# Drop binaries that only exist on the build machine and must come from the OS.
#
# PyInstaller resolves imported DLLs by name through PATH. If the packaging shell
# has unrelated SDKs on PATH (a poppler/libheif cache, for example), same-named
# files from there end up in the bundle and shadow the OS copies. A poppler
# icuuc.dll exports only versioned ICU symbols (ucnv_open_78) while Qt 6 imports
# the unversioned names (ucnv_open) that Windows 10+ provides, which surfaces as:
#   ImportError: DLL load failed while importing QtWidgets: The specified procedure
#   could not be found.
# Only keep binaries that live inside the Python installation or its site-packages.
trusted_roots = {Path(sys.base_prefix).resolve(), Path(sys.prefix).resolve()}
for packages_dir in site.getsitepackages() + [site.getusersitepackages()]:
    trusted_roots.add(Path(packages_dir).resolve())


def _bundled_from_python(entry):
    source = Path(entry[1]).resolve()
    return any(source.is_relative_to(root) for root in trusted_roots if root.exists())


kept_binaries = []
for entry in analysis.binaries:
    if _bundled_from_python(entry):
        kept_binaries.append(entry)
    else:
        print(f"[spec] dropping build-machine binary: {entry[0]} <- {entry[1]}")
analysis.binaries = kept_binaries

# Use one matching MSVC runtime set for Python and Qt to avoid DLL entry-point conflicts.
analysis.binaries = [
    entry for entry in analysis.binaries
    if Path(entry[0]).name.lower() not in runtime_names
]
for name, source in runtime_sources.items():
    if source.exists():
        analysis.binaries.append((name, str(source), "BINARY"))
        analysis.binaries.append((f"PyQt6/Qt6/bin/{name}", str(source), "BINARY"))
pyz = PYZ(analysis.pure)
if ONEFILE:
    exe = EXE(
        pyz,
        analysis.scripts,
        analysis.binaries,
        analysis.datas,
        [],
        name="WhaleTalk",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        upx=False,
        console=CONSOLE,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
        icon=str(project_root / "assets" / "whale-assistant.ico"),
    )
else:
    exe = EXE(
        pyz,
        analysis.scripts,
        [],
        exclude_binaries=True,
        name="WhaleTalk",
        debug=False,
        bootloader_ignore_signals=False,
        strip=False,
        # UPX on Qt DLLs is a known source of "DLL load failed" reports; keep the bundle unpacked.
        upx=False,
        console=CONSOLE,
        disable_windowed_traceback=False,
        argv_emulation=False,
        target_arch=None,
        codesign_identity=None,
        entitlements_file=None,
        icon=str(project_root / "assets" / "whale-assistant.ico"),
    )
    collection = COLLECT(
        exe,
        analysis.binaries,
        analysis.datas,
        strip=False,
        upx=False,
        upx_exclude=[],
        name="WhaleTalk",
    )

# ffmpeg is the only external command-line tool the app requires. Copy it into
# the portable output after PyInstaller has finished so a machine without a
# system ffmpeg can still extract frames and decode audio. (Adding a 200 MB
# executable to datas/binaries makes PyInstaller's onedir collection unreliable.)
import shutil

_bundled_ffmpeg_candidates = []
_ffmpeg_env = os.environ.get("FFMPEG_PATH")
if _ffmpeg_env:
    _bundled_ffmpeg_candidates.append(Path(_ffmpeg_env))
_bundled_ffmpeg_candidates.extend([
    project_root / "assets" / "ffmpeg.exe",
    Path(r"C:\ffmpeg\bin\ffmpeg.exe"),
])
for _ffmpeg_candidate in _bundled_ffmpeg_candidates:
    if _ffmpeg_candidate and _ffmpeg_candidate.is_file():
        _dist_dir = Path(DISTPATH) / "WhaleTalk"
        _dist_dir.mkdir(parents=True, exist_ok=True)
        shutil.copy2(_ffmpeg_candidate, _dist_dir / "ffmpeg.exe")
        _license = _ffmpeg_candidate.parent.parent / "LICENSE"
        if _license.is_file():
            shutil.copy2(_license, _dist_dir / "FFMPEG_LICENSE.txt")
        print(f"[spec] bundled ffmpeg: {_ffmpeg_candidate}")
        break
else:
    print("[spec] ffmpeg not found at build time; portable build relies on system ffmpeg")

