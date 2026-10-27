"""Daily diary -> long-term memory consolidation worker."""

import asyncio

from PyQt6.QtCore import QThread, pyqtSignal

from core.long_term_memory import consolidate


class MemoryWorker(QThread):
    done = pyqtSignal(bool, str)

    def __init__(self, ai_client, db, parent=None):
        super().__init__(parent)
        self.ai_client = ai_client
        self.db = db

    def run(self):
        try:
            text = asyncio.run(consolidate(self.ai_client))
            self.done.emit(bool(text), '' if text else '没有新日记或未到整理时间')
        except Exception as exc:  # noqa: BLE001
            self.done.emit(False, str(exc))
