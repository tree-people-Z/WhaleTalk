"""Install required Python packages on first launch when they are missing."""

import importlib.util
import subprocess
import sys
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parent.parent
REQUIREMENTS = PROJECT_ROOT / 'requirements.txt'

# Map distribution names to import names when they differ.
REQUIRED_IMPORTS = {
    'bilibili-api-python': 'bilibili_api',
    'aiohttp': 'aiohttp',
    'PyQt6': 'PyQt6',
    'openai': 'openai',
    'anthropic': 'anthropic',
    'APScheduler': 'apscheduler',
    'SQLAlchemy': 'sqlalchemy',
    'qrcode[pil]': 'qrcode',
    'Pillow': 'PIL',
    'PyYAML': 'yaml',
    'python-dotenv': 'dotenv',
    'requests': 'requests',
    'loguru': 'loguru',
}


def missing_required_packages():
    missing = []
    for distribution, module in REQUIRED_IMPORTS.items():
        try:
            available = importlib.util.find_spec(module) is not None
        except (ImportError, ModuleNotFoundError, ValueError):
            available = False
        if not available:
            missing.append(distribution)
    return missing


def ensure_required_dependencies():
    """Install the base requirements before importing the GUI or app modules."""
    missing = missing_required_packages()
    if not missing:
        return
    print(f"缺少运行依赖: {', '.join(missing)}", flush=True)
    print("正在自动安装项目依赖，请保持网络连接...", flush=True)
    result = subprocess.run(
        [sys.executable, '-m', 'pip', 'install', '-r', str(REQUIREMENTS)],
        cwd=PROJECT_ROOT,
        check=False,
    )
    if result.returncode:
        raise RuntimeError(
            "自动安装依赖失败。请检查网络和 Python 环境后重试："
            f"{sys.executable} -m pip install -r requirements.txt"
        )
    still_missing = missing_required_packages()
    if still_missing:
        raise RuntimeError(f"依赖安装后仍无法导入: {', '.join(still_missing)}")

