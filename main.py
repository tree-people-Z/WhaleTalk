#!/usr/bin/env python3
"""
鲸语 - B站智能运营助手
主入口文件
"""

import sys
import os
from pathlib import Path

# The bootstrap uses only the standard library and runs before PyQt/app imports.
PROJECT_ROOT = Path(__file__).parent
if getattr(sys, 'frozen', False):
    # Keep user data beside the downloaded executable, outside PyInstaller's temp extraction.
    os.chdir(Path(sys.executable).resolve().parent)
    if os.name == 'nt':
        # PyQt's DLLs are nested below _internal; retain directory handles for Windows DLL lookup.
        _DLL_DIRECTORY_HANDLES = []
        for dll_dir in (
            Path(getattr(sys, '_MEIPASS', PROJECT_ROOT)) / 'PyQt6' / 'Qt6' / 'bin',
            Path(getattr(sys, '_MEIPASS', PROJECT_ROOT)),
        ):
            if dll_dir.is_dir():
                _DLL_DIRECTORY_HANDLES.append(os.add_dll_directory(str(dll_dir)))
sys.path.insert(0, str(PROJECT_ROOT))
from utils.dependency_bootstrap import ensure_required_dependencies

try:
    ensure_required_dependencies()
except Exception as exc:
    print(f"依赖准备失败: {exc}", file=sys.stderr, flush=True)
    raise SystemExit(1)

from PyQt6.QtWidgets import QApplication
from PyQt6.QtCore import Qt

from gui.main_window import MainWindow
from utils.logger import setup_logger
from utils.config_manager import ConfigManager


def main():
    """程序主入口"""
    # 初始化日志
    logger = setup_logger()
    logger.info("=" * 60)
    logger.info("鲸语 · B站智能运营助手启动")
    logger.info("=" * 60)

    # 初始化配置
    config_manager = ConfigManager()
    if not config_manager.config_file.exists():
        logger.info("首次运行，创建默认配置文件")
        config_manager.create_default_config()

    # 创建应用
    app = QApplication(sys.argv)
    app.setApplicationName("鲸语")
    icon_path = PROJECT_ROOT / "assets" / "whale-assistant.ico"
    if icon_path.exists():
        from PyQt6.QtGui import QIcon
        app.setWindowIcon(QIcon(str(icon_path)))
    app.setStyle("Fusion")  # 使用Fusion风格

    # 设置高DPI支持
    if hasattr(Qt, 'AA_EnableHighDpiScaling'):
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_EnableHighDpiScaling, True)
    if hasattr(Qt, 'AA_UseHighDpiPixmaps'):
        QApplication.setAttribute(Qt.ApplicationAttribute.AA_UseHighDpiPixmaps, True)

    # 创建主窗口
    main_window = MainWindow()
    main_window.show()

    logger.info("主窗口已显示")

    # 运行应用
    exit_code = app.exec()

    logger.info(f"程序退出，退出码: {exit_code}")
    return exit_code


if __name__ == "__main__":
    sys.exit(main())
