"""手动触发在线学习的后台线程。"""

import asyncio

from PyQt6.QtCore import QThread, pyqtSignal
from loguru import logger

from core.self_evolution import learn


class EvolutionWorker(QThread):
    """跑一次成长整理，避免设置页卡住。"""

    done = pyqtSignal(bool, str, dict)

    def __init__(self, ai_client, db, config, parent=None):
        super().__init__(parent)
        self.ai_client = ai_client
        self.db = db
        self.config = config

    def run(self):
        try:
            result = asyncio.run(
                learn(self.ai_client, self.db, self.config, force=True)
            )
            if result.get('skipped'):
                message = {
                    'disabled': '在线学习已关闭',
                    'no-material': '暂无可学习的素材',
                    'no-ai-or-db': '缺少 AI 或数据库',
                }.get(result['skipped'], result['skipped'])
                self.done.emit(False, message, result)
                return
            added = int(result.get('added') or 0)
            message = f'已学习 {added} 条新内容'
            if result.get('decayed'):
                message += f'，衰减 {result["decayed"]} 条'
            self.done.emit(True, message, result)
        except Exception as exc:  # noqa: BLE001
            logger.exception(f'在线学习失败: {exc}')
            self.done.emit(False, str(exc), {})
        finally:
            if self.db is not None:
                try:
                    self.db.close_session()
                except Exception:  # noqa: BLE001
                    pass
