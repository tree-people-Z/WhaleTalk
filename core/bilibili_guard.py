"""B 站风控状态、发评论冷却与请求限速。

这些限制不交给模型，始终由程序强制执行。
"""

import asyncio
import json
import random
import re
import time
from datetime import datetime, timedelta

from loguru import logger


class BiliGuardMixin:
    """风控冷却、12014 发帖冷却、评论请求限速。"""

    def is_blocked(self) -> bool:
        """检查是否处于风控状态（412 等）。"""
        blocked_until = getattr(self, 'blocked_until', None)
        if blocked_until:
            if datetime.now() < blocked_until:
                return True
            self.blocked_until = None
        return False

    def set_blocked(self, duration_minutes: int = 30):
        self.blocked_until = datetime.now() + timedelta(minutes=duration_minutes)
        logger.warning(f"触发风控，将暂停 {duration_minutes} 分钟")

    def _load_posting_state(self):
        path = getattr(self, '_posting_state_path', None)
        if not path or not path.exists():
            return
        try:
            data = json.loads(path.read_text(encoding='utf-8'))
            until = datetime.fromisoformat(data.get('until', ''))
        except Exception:  # noqa: BLE001
            return
        if until and datetime.now() < until:
            self.posting_blocked_until = until
            self.posting_block_reason = data.get('reason', '')
            logger.info(f"恢复评论发送冷却至 {until:%Y-%m-%d %H:%M}")
        else:
            self._clear_posting_state()

    def _save_posting_state(self):
        path = getattr(self, '_posting_state_path', None)
        if not path:
            return
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(json.dumps({
                'until': self.posting_blocked_until.isoformat()
                if self.posting_blocked_until else '',
                'reason': self.posting_block_reason,
            }, ensure_ascii=False), encoding='utf-8')
        except OSError:
            pass

    def _clear_posting_state(self):
        path = getattr(self, '_posting_state_path', None)
        if path:
            try:
                path.unlink()
            except OSError:
                pass

    def is_posting_blocked(self) -> bool:
        """B站评论发送额度是否已用完（错误码 12014）。"""
        until = getattr(self, 'posting_blocked_until', None)
        if until:
            if datetime.now() < until:
                return True
            self.posting_blocked_until = None
            self._clear_posting_state()
        return False

    def set_posting_blocked(self, reason: str = ''):
        """暂停发评论到次日凌晨，避免反复触发 12014。"""
        reset = (datetime.now() + timedelta(days=1)).replace(
            hour=0, minute=5, second=0, microsecond=0
        )
        self.posting_blocked_until = reset
        self.posting_block_reason = reason
        self._save_posting_state()
        logger.warning(
            f"B站评论发送已达上限（12014），暂停发评论至 "
            f"{reset:%Y-%m-%d %H:%M}"
        )

    @staticmethod
    def _short_error(message: str, limit: int = 160) -> str:
        """折叠 B站 HTML 错误页，让日志保持可读。"""
        text = re.sub(r'<[^>]+>', ' ', message or '')
        text = re.sub(r'\s+', ' ', text).strip()
        return text[:limit] + ('…' if len(text) > limit else '')

    async def _pace_comment_request(self) -> None:
        """给评论请求加最小间隔和随机抖动。

        API 对象会被多个工作线程共享，每个线程有自己的事件循环；
        asyncio.Lock 绑定首次使用它的循环，所以换循环时要重建。
        """
        loop = asyncio.get_running_loop()
        lock = getattr(self, '_comment_request_lock', None)
        if lock is None or getattr(self, '_comment_request_lock_loop', None) is not loop:
            lock = asyncio.Lock()
            self._comment_request_lock = lock
            self._comment_request_lock_loop = loop
        async with lock:
            target = (
                getattr(self, '_last_comment_request_at', 0.0)
                + getattr(self, '_comment_min_interval', 2.0)
                + random.uniform(0, 1.5)
            )
            wait = target - time.monotonic()
            if wait > 0:
                await asyncio.sleep(wait)
            self._last_comment_request_at = time.monotonic()
