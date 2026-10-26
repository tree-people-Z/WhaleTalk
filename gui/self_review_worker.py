"""Background worker for the weekly self-review."""

import asyncio

from PyQt6.QtCore import QThread, pyqtSignal

from loguru import logger


class SelfReviewWorker(QThread):
    done = pyqtSignal(bool, str)

    def __init__(self, review, parent=None):
        super().__init__(parent)
        self.review = review

    def run(self):
        try:
            result = asyncio.run(self.review.generate())
            message = result.get('auto_message') or result.get('review_path', '')
            self.done.emit(True, message)
        except Exception as exc:  # noqa: BLE001
            logger.warning(f'自我复盘生成失败: {exc}')
            self.done.emit(False, str(exc))
