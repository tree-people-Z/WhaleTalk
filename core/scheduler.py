"""自动运营与回复检查调度。"""

import random
from datetime import datetime, timedelta
from typing import Callable, Optional

from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger
from loguru import logger

from utils.config_manager import ConfigManager


class TaskScheduler:
    """按随机间隔巡视视频，并独立调度评论回复检查。"""

    def __init__(self, config: ConfigManager):
        self.config = config
        self.scheduler = BackgroundScheduler()
        self.is_running = False
        self._scheduler_shutdown = False
        self.on_wake_callback: Optional[Callable] = None
        self.on_reply_check_callback: Optional[Callable] = None
        self._next_browse_at: Optional[datetime] = None
        self._next_reply_check_at: Optional[datetime] = None

    def set_wake_callback(self, callback: Callable):
        self.on_wake_callback = callback

    def set_reply_check_callback(self, callback: Callable):
        self.on_reply_check_callback = callback

    def start(self):
        if self.is_running:
            logger.warning("调度器已在运行")
            return
        if not self.config.get('schedule.auto_run', False):
            logger.info("自动运行未启用，调度器不启动")
            return
        if not self.on_wake_callback and not self.on_reply_check_callback:
            logger.error("未设置自动运营回调，调度器不启动")
            return
        if self._scheduler_shutdown:
            self.scheduler = BackgroundScheduler()
            self._scheduler_shutdown = False

        self.scheduler.remove_all_jobs()
        now = datetime.now()
        self._next_browse_at = self._next_time(
            self.config.get('schedule.browse_interval_min_minutes', 60),
            self.config.get('schedule.browse_interval_max_minutes', 120)
        )
        reply_interval = max(1, int(self.config.get('schedule.reply_check_interval_minutes', 1)))
        self._next_reply_check_at = now + timedelta(minutes=reply_interval)
        self.scheduler.add_job(
            self._poll_tasks,
            IntervalTrigger(seconds=30),
            id='automatic_operation_poll',
            name='自动运营轮询',
            replace_existing=True,
            coalesce=True,
            max_instances=1,
            misfire_grace_time=30
        )
        self.scheduler.start()
        self.is_running = True
        logger.info("✅ 自动运营已启动：随机巡视、定期检查评论回复")

    def stop(self):
        if not self.is_running:
            return
        self.scheduler.shutdown(wait=False)
        self.is_running = False
        self._scheduler_shutdown = True
        logger.info("调度器已停止")

    def _next_time(self, minimum: int, maximum: int) -> datetime:
        minimum, maximum = max(1, int(minimum)), max(1, int(maximum))
        return datetime.now() + timedelta(minutes=random.randint(minimum, max(minimum, maximum)))

    @staticmethod
    def _parse_time(value: str) -> Optional[int]:
        try:
            hour_text, minute_text = value.strip().split(':', 1)
            hour, minute = int(hour_text), int(minute_text)
            if 0 <= hour <= 24 and 0 <= minute <= 59 and not (hour == 24 and minute):
                return hour * 60 + minute
        except (AttributeError, TypeError, ValueError):
            pass
        return None

    def _is_low_price_time(self, now: datetime) -> bool:
        if not self.config.get('schedule.deepseek_offpeak_only', True):
            return True
        if self.config.get('ai.provider', '').lower() != 'deepseek':
            return True
        # DeepSeek lists weekends and Chinese public holidays as off-peak all day.
        if now.weekday() >= 5:
            return True
        windows = self.config.get(
            'schedule.deepseek_offpeak_windows',
            '00:00-09:00,12:00-14:00,18:00-24:00'
        )
        if not isinstance(windows, str):
            return False
        current_minute = now.hour * 60 + now.minute
        for window in windows.split(','):
            parts = window.strip().split('-', 1)
            if len(parts) != 2:
                continue
            start, end = (self._parse_time(part) for part in parts)
            if start is not None and end is not None and start < end and start <= current_minute < end:
                return True
        return False

    def _poll_tasks(self):
        if not self.is_running:
            return
        now = datetime.now()

        # Urgent reply checks run throughout the day. The DeepSeek off-peak
        # gate applies to the more expensive video browsing/analysis cycle.
        if (self.on_reply_check_callback
                and self.config.get('interaction.comment_monitor', False)
                and self._next_reply_check_at and now >= self._next_reply_check_at):
            try:
                accepted = self.on_reply_check_callback()
                # A busy worker may decline the run. Keep it due so a transient
                # overlap cannot silently lose an urgent reply check.
                if accepted is not False:
                    self._next_reply_check_at = now + timedelta(
                        minutes=max(1, int(self.config.get('schedule.reply_check_interval_minutes', 1)))
                    )
                    # Reply checks have priority; do not queue a browse run
                    # alongside a worker that has just started checking replies.
                    return
            except Exception as exc:
                logger.error(f"触发评论回复检查失败: {exc}")

        if (self._next_browse_at and now >= self._next_browse_at
                and self._is_low_price_time(now)):
            try:
                accepted = self._execute_wake()
                if accepted is not False:
                    self._next_browse_at = self._next_time(
                        self.config.get('schedule.browse_interval_min_minutes', 60),
                        self.config.get('schedule.browse_interval_max_minutes', 120)
                    )
            except Exception as exc:
                logger.error(f"触发巡视任务失败: {exc}")

    def _execute_wake(self):
        if not self.is_running:
            logger.info("自动运行已停止，忽略已排队的巡视任务")
            return False
        logger.info("开始执行自动巡视任务")
        if self.on_wake_callback:
            try:
                return self.on_wake_callback()
            except Exception as exc:
                logger.error(f"执行巡视回调失败: {exc}")
                return False
        return False

    def run_now(self):
        logger.info("手动触发巡视任务")
        if self.on_wake_callback:
            self.on_wake_callback()

    def run_reply_check_now(self):
        if self.on_reply_check_callback:
            self.on_reply_check_callback()

    def get_next_run_time(self) -> Optional[datetime]:
        times = [t for t in (self._next_browse_at, self._next_reply_check_at) if t]
        return min(times) if times else None

    def get_status(self) -> dict:
        return {
            'running': self.is_running,
            'auto_run_enabled': self.config.get('schedule.auto_run', False),
            'wake_windows': self.config.get('schedule.wake_windows', []),
            'next_run_time': self.get_next_run_time().isoformat() if self.get_next_run_time() else None,
            'next_browse_at': self._next_browse_at.isoformat() if self._next_browse_at else None,
            'next_reply_check_at': self._next_reply_check_at.isoformat() if self._next_reply_check_at else None,
            'jobs_count': len(self.scheduler.get_jobs())
        }
