"""Background worker: compact old diaries and clean up growth items."""

import asyncio

from PyQt6.QtCore import QThread, pyqtSignal
from loguru import logger

from core.diary_maintenance import compact_diaries
from core.self_evolution import housekeeping


class DiaryMaintenanceWorker(QThread):
    """压缩过期日记；顺手按天清理成长档案。"""

    done = pyqtSignal(bool, str)

    def __init__(self, ai_client, db, config=None, parent=None):
        super().__init__(parent)
        self.ai_client = ai_client
        self.db = db
        self.config = config

    def run(self):
        try:
            stats = asyncio.run(
                compact_diaries(self.ai_client, self.config)
            )
            cleaned = {}
            if self.db is not None and self.config is not None:
                try:
                    cleaned = housekeeping(self.db, self.config)
                except Exception as exc:  # noqa: BLE001
                    logger.warning(f'成长档案清理失败: {exc}')
            if stats['files']:
                message = (
                    f'日记整理 {stats["files"]} 篇：'
                    f'{stats["before"]} → {stats["after"]} 字'
                )
                if cleaned.get('decayed') or cleaned.get('pruned'):
                    message += (
                        f'；成长条目衰减 {cleaned.get("decayed", 0)}、'
                        f'清理 {cleaned.get("pruned", 0)}'
                    )
                self.done.emit(True, message)
            else:
                self.done.emit(False, '没有需要整理的日记')
        except Exception as exc:  # noqa: BLE001
            self.done.emit(False, str(exc))
        finally:
            if self.db is not None:
                try:
                    self.db.close_session()
                except Exception:  # noqa: BLE001
                    pass
