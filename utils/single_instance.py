"""单实例保护：避免两个进程同时自动运营导致重复评论/私信。"""

from pathlib import Path
from typing import Optional

from loguru import logger


def acquire_instance_lock(path: Path):
    """尝试获取单实例锁。

    返回锁对象（需要调用方保持引用直到退出），失败返回 ``None``。
    使用 QLockFile，进程异常退出后残留的锁会被自动清理。
    """
    try:
        from PyQt6.QtCore import QLockFile
    except ImportError:  # pragma: no cover - GUI 依赖缺失时放弃保护
        logger.warning('无法导入 QLockFile，跳过单实例检查')
        return None

    lock_path = Path(path)
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    lock = QLockFile(str(lock_path))
    lock.setStaleLockTime(0)
    if lock.tryLock(100):
        return lock
    logger.warning('检测到另一个鲸语实例正在运行')
    return None


def read_lock_pid(path: Path) -> Optional[int]:
    """读取当前锁文件里的进程号，便于日志排查。"""
    try:
        from PyQt6.QtCore import QLockFile
    except ImportError:  # pragma: no cover
        return None
    lock = QLockFile(str(Path(path)))
    try:
        pid, _, _ = lock.getLockInfo()
        return int(pid) or None
    except Exception:  # noqa: BLE001
        return None
