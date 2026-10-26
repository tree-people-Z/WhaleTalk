"""Background worker for the read-only autonomous observation."""

import asyncio

from PyQt6.QtCore import QThread, pyqtSignal
from loguru import logger

from core.tool_agent import ToolAgent


class AgentWorker(QThread):
    done = pyqtSignal(bool, str)

    def __init__(self, bili_api, db, ai_client, config, parent=None):
        super().__init__(parent)
        self.bili_api = bili_api
        self.db = db
        self.ai_client = ai_client
        self.config = config

    def run(self):
        try:
            result = asyncio.run(
                ToolAgent(self.bili_api, self.db, self.ai_client, self.config).run()
            )
            self.done.emit(True, result.get('summary') or '观察完成')
        except Exception as exc:  # noqa: BLE001
            logger.warning(f'自主观察失败: {exc}')
            self.done.emit(False, str(exc))
