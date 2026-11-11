import unittest
from datetime import datetime
from unittest.mock import Mock, patch

from core.scheduler import TaskScheduler


class SchedulerTests(unittest.TestCase):
    def make_config(self, **values):
        config = Mock()
        defaults = {
            'schedule.auto_run': True,
            'schedule.browse_interval_min_minutes': 60,
            'schedule.browse_interval_max_minutes': 120,
            'schedule.reply_check_interval_minutes': 2,
            'schedule.deepseek_offpeak_only': True,
            'schedule.deepseek_offpeak_windows': '00:00-09:00,12:00-14:00,18:00-24:00',
            'interaction.comment_monitor': True,
            'ai.provider': 'deepseek'
        }
        defaults.update(values)
        config.get.side_effect = lambda key, default=None: defaults.get(key, default)
        return config

    def test_restart_recreates_shutdown_scheduler(self):
        scheduler = TaskScheduler(self.make_config())
        scheduler.set_wake_callback(lambda: None)
        scheduler.start()
        self.assertTrue(scheduler.is_running)
        scheduler.stop()
        scheduler.start()
        self.assertTrue(scheduler.is_running)
        self.assertEqual(len(scheduler.scheduler.get_jobs()), 1)
        scheduler.stop()

    def test_offpeak_windows_cover_expected_weekday_periods(self):
        scheduler = TaskScheduler(self.make_config())
        # Friday, UTC-independent local Beijing wall clock.
        self.assertFalse(scheduler._is_low_price_time(datetime(2026, 10, 23, 10, 0)))
        self.assertTrue(scheduler._is_low_price_time(datetime(2026, 10, 23, 12, 30)))
        self.assertTrue(scheduler._is_low_price_time(datetime(2026, 10, 24, 10, 0)))

    def test_custom_offpeak_windows_are_respected(self):
        scheduler = TaskScheduler(self.make_config(**{
            'schedule.deepseek_offpeak_windows': '01:00-03:00'
        }))
        self.assertTrue(scheduler._is_low_price_time(datetime(2026, 10, 23, 2, 0)))
        self.assertFalse(scheduler._is_low_price_time(datetime(2026, 10, 23, 4, 0)))

    def test_non_deepseek_provider_ignores_offpeak_gate(self):
        scheduler = TaskScheduler(self.make_config(**{'ai.provider': 'openai'}))
        self.assertTrue(scheduler._is_low_price_time(datetime(2026, 10, 23, 10, 0)))

    def test_poll_only_schedules_browse(self):
        # 回复检查已交给界面上的常驻定时器，调度器不再触发它。
        scheduler = TaskScheduler(self.make_config())
        browse = Mock()
        scheduler.set_wake_callback(browse)
        scheduler.is_running = True
        now = datetime(2026, 10, 24, 10, 0)  # 周末 = 非高峰
        scheduler._next_browse_at = now
        with patch('core.scheduler.datetime') as dt,              patch.object(scheduler, '_next_time', return_value=now):
            dt.now.return_value = now
            scheduler._poll_tasks()
        browse.assert_called_once_with()

    def test_peak_hours_defer_video_browsing(self):
        scheduler = TaskScheduler(self.make_config())
        browse = Mock()
        scheduler.set_wake_callback(browse)
        scheduler.is_running = True
        now = datetime(2026, 10, 23, 10, 0)  # 工作日高峰
        scheduler._next_browse_at = now
        with patch('core.scheduler.datetime') as dt:
            dt.now.return_value = now
            scheduler._poll_tasks()
        browse.assert_not_called()
        self.assertEqual(scheduler._next_browse_at, now)

    def test_manual_browse_works_while_automatic_scheduler_is_stopped(self):
        scheduler = TaskScheduler(self.make_config(**{'schedule.auto_run': False}))
        browse = Mock()
        scheduler.set_wake_callback(browse)
        scheduler.run_now()
        browse.assert_called_once_with()

    def test_due_browse_is_retained_when_main_window_is_busy(self):
        scheduler = TaskScheduler(self.make_config())
        callback = Mock(side_effect=[False, True])
        scheduler.set_wake_callback(callback)
        scheduler.is_running = True
        now = datetime(2026, 10, 24, 10, 0)
        scheduler._next_browse_at = now
        with patch('core.scheduler.datetime') as dt, \
             patch.object(scheduler, '_next_time', return_value=now):
            dt.now.return_value = now
            scheduler._poll_tasks()
            self.assertEqual(scheduler._next_browse_at, now)
            scheduler._poll_tasks()
        self.assertEqual(callback.call_count, 2)

if __name__ == '__main__':
    unittest.main()
