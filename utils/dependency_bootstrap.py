"""Install required Python packages on first launch when they are missing.

Set ``WHALETALK_NO_AUTO_INSTALL=1`` to disable automatic installation and
print the pip command instead (recommended for managed environments).
"""

import importlib.util
import os
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
    'Pillow': 'PIL',
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
    if getattr(sys, 'frozen', False):
        # The PyInstaller bundle ships these packages, and a frozen executable has
        # no pip to install into. Never try to self-install from the packaged app.
        return
    missing = missing_required_packages()
    if not missing:
        return
    install_command = (
        f"{sys.executable} -m pip install -r "
        f"{REQUIREMENTS.name}"
    )
    if sys.stdout is not None:
        print(f"缺少运行依赖: {', '.join(missing)}", flush=True)
    if os.environ.get('WHALETALK_NO_AUTO_INSTALL', '').strip().lower() in {
        '1', 'true', 'yes', 'on',
    }:
        raise RuntimeError(
            f"缺少运行依赖且已禁用自动安装，请手动执行: {install_command}"
        )
    if sys.stdout is not None:
        print("正在自动安装项目依赖，请保持网络连接...", flush=True)
        print("（如需禁用自动安装，设置 WHALETALK_NO_AUTO_INSTALL=1）", flush=True)
    from utils.subprocess_helpers import hidden_window_kwargs

    result = subprocess.run(
        [sys.executable, '-m', 'pip', 'install', '-r', str(REQUIREMENTS)],
        cwd=PROJECT_ROOT,
        check=False,
        **hidden_window_kwargs(),
    )
    if result.returncode:
        raise RuntimeError(
            "自动安装依赖失败。请检查网络和 Python 环境后重试："
            f"{sys.executable} -m pip install -r requirements.txt"
        )
    still_missing = missing_required_packages()
    if still_missing:
        raise RuntimeError(f"依赖安装后仍无法导入: {', '.join(still_missing)}")

