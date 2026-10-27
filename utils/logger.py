"""
日志模块
"""

import sys
from pathlib import Path
from loguru import logger


def setup_logger(log_file: str = "data/logs/bot.log", level: str = "INFO"):
    """
    配置日志系统

    Args:
        log_file: 日志文件路径
        level: 日志级别
    """
    # 移除默认handler
    logger.remove()

    # 窗口化打包（console=False）时没有控制台，sys.stdout 为 None，不能作为 sink。
    if sys.stdout is not None:
        try:
            sys.stdout.reconfigure(encoding='utf-8', errors='replace')
        except (AttributeError, OSError):
            pass
        logger.add(
            sys.stdout,
            format="<green>{time:YYYY-MM-DD HH:mm:ss}</green> | <level>{level: <8}</level> | <level>{message}</level>",
            level=level,
            colorize=True
        )

    # 添加文件输出
    log_path = Path(log_file)
    log_path.parent.mkdir(parents=True, exist_ok=True)

    logger.add(
        log_file,
        format="{time:YYYY-MM-DD HH:mm:ss} | {level: <8} | {name}:{function}:{line} - {message}",
        level=level,
        rotation="10 MB",  # 文件大小超过10MB时轮转
        retention="7 days",  # 保留7天
        compression="zip",  # 压缩旧日志
        encoding="utf-8"
    )

    logger.info(f"日志系统已初始化: {log_file}")

    return logger
