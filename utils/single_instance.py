"""单实例保护：避免两个进程同时自动运营导致重复评论/私信。"""

import os
from pathlib import Path
from typing import Optional

from loguru import logger

_STILL_ACTIVE = 259
_ERROR_ACCESS_DENIED = 5


def _pid_alive_windows(pid: int) -> bool:
    """Windows 上不能用 ``os.kill(pid, 0)``：它等价于 TerminateProcess。"""
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL('kernel32', use_last_error=True)
    handle = kernel32.OpenProcess(0x1000, False, pid)  # PROCESS_QUERY_LIMITED_INFORMATION
    if not handle:
        # 拒绝访问说明进程还在，只是无权查询；其它错误按“已退出”处理。
        return ctypes.get_last_error() == _ERROR_ACCESS_DENIED
    try:
        code = wintypes.DWORD()
        if not kernel32.GetExitCodeProcess(handle, ctypes.byref(code)):
            return True
        return code.value == _STILL_ACTIVE
    finally:
        kernel32.CloseHandle(handle)


def is_pid_alive(pid: Optional[int]) -> bool:
    """判断进程是否还在运行（pid 为空或非法时视为已退出）。"""
    if not pid or int(pid) <= 0:
        return False
    pid = int(pid)
    if os.name == 'nt':
        return _pid_alive_windows(pid)
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def clear_stale_lock(path: Path) -> bool:
    """清理上次强制退出留下的锁文件；返回是否真的删掉了文件。

    托盘程序不响应 WM_CLOSE，被强杀时 QLockFile 会把锁留在盘上。虽然
    QLockFile 自己也能判定进程已死，但显式清理能保证下次启动一定拿得到
    锁，并在日志里留下一条可追溯的记录。

    锁文件读不出 pid 时一律不动手：宁可让 QLockFile 自己判断，也不能因为
    解析失败把一个活着的实例的锁删掉，那会直接导致双开重复评论。
    """
    lock_path = Path(path)
    if not lock_path.exists():
        return False
    pid = read_lock_pid(lock_path)
    if pid is None:
        logger.debug(f'锁文件内容无法解析，交由 QLockFile 判断: {lock_path}')
        return False
    if is_pid_alive(pid):
        return False
    try:
        lock_path.unlink()
    except OSError as exc:
        logger.warning(f'无法删除残留锁文件 {lock_path}: {exc}')
        return False
    logger.info(f'已清理残留锁文件: {lock_path}（上次 pid={pid or "?"} 已不存在）')
    return True


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
    clear_stale_lock(lock_path)
    lock = QLockFile(str(lock_path))
    lock.setStaleLockTime(0)
    if lock.tryLock(100):
        return lock
    pid = read_lock_pid(lock_path)
    logger.warning(f'检测到另一个鲸语实例正在运行 (pid={pid or "?"})；可用 --quit 让它退出')
    return None


def read_lock_pid(path: Path) -> Optional[int]:
    """读取当前锁文件里的进程号，便于日志排查。

    PyQt6 的 ``getLockInfo()`` 返回 ``(ok, pid, hostname, appName)``，而老版本
    PyQt 返回 ``(pid, hostname, appName)``；两种形状都要能解析。
    """
    try:
        from PyQt6.QtCore import QLockFile
    except ImportError:  # pragma: no cover
        return None
    lock = QLockFile(str(Path(path)))
    try:
        info = lock.getLockInfo()
    except Exception:  # noqa: BLE001
        return None
    if not info:
        return None
    if isinstance(info[0], bool):
        if not info[0] or len(info) < 2:
            return None
        pid = info[1]
    else:
        pid = info[0]
    try:
        return int(pid) or None
    except (TypeError, ValueError):
        return None
