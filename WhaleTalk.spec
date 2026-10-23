# Build with: python -m PyInstaller --clean --noconfirm WhaleTalk.spec
from pathlib import Path
import sys

project_root = Path(SPECPATH)
datas = [
    (str(project_root / "assets"), "assets"),
    (str(project_root / "requirements.txt"), "."),
    (str(project_root / "requirements-transcription.txt"), "."),
]
hiddenimports = ["bilibili_api"]
# Python's DLL imports the MSVC runtime. Some Windows PCs lack the redistributable,
# so ship the Python installation's matching runtime beside the bundled interpreter.
binaries = [
    (str(Path(sys.prefix) / name), ".")
    for name in ("vcruntime140.dll", "vcruntime140_1.dll", "msvcp140.dll")
    if (Path(sys.prefix) / name).exists()
]

analysis = Analysis(
    [str(project_root / "main.py")],
    pathex=[str(project_root)],
    binaries=binaries,
    datas=datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["pytest", "tests"],
    noarchive=False,
    optimize=0,
)
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
    upx=True,
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
    upx=True,
    upx_exclude=[],
    name="WhaleTalk",
)
