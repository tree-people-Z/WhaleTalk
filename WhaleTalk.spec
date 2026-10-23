# Build with: python -m PyInstaller --clean --noconfirm WhaleTalk.spec
from pathlib import Path
import os
import site
import sys

from PyInstaller.utils.hooks import collect_data_files, collect_submodules

project_root = Path(SPECPATH)

datas = [
    (str(project_root / "assets"), "assets"),
    # requirements files are only used by the source bootstrap (pip install); the
    # frozen build is self-contained and never reads them.
]
# bilibili_api registers its HTTP clients by importing submodules dynamically, so
# the static analysis cannot see bilibili_api.clients.*; collect them explicitly.
# The package also ships JSON tables under bilibili_api/data.
hiddenimports = ["bilibili_api"] + collect_submodules("bilibili_api")
datas += collect_data_files("bilibili_api")

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
    ],
    noarchive=False,
    optimize=0,
)

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
    console=False,
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
