"""Daily diary -> long-term memory consolidation worker."""

import asyncio

from PyQt6.QtCore import QThread, pyqtSignal
from loguru import logger

from core.long_term_memory import consolidate
from core.self_evolution import learn


class MemoryWorker(QThread):
    done = pyqtSignal(bool, str)

    def __init__(self, ai_client, db, config=None, parent=None):
        super().__init__(parent)
        self.ai_client = ai_client
        self.db = db
        self.config = config

    def run(self):
        try:
            text = ''
            try:
                text = asyncio.run(consolidate(self.ai_client))
            except Exception as exc:  # noqa: BLE001
                logger.warning(f'长期记忆整理失败: {exc}')
            learned = {}
            if self.config is not None:
                try:
                    learned = asyncio.run(
                        learn(self.ai_client, self.db, self.config)
                    )
                except Exception as exc:  # noqa: BLE001
                    logger.warning(f'在线学习失败: {exc}')
            added = int(learned.get('added') or 0)
            if text and added:
                message = f'长期记忆已更新；成长档案新增 {added} 条'
            elif text:
                message = '长期记忆已更新'
            elif added:
                message = f'成长档案新增 {added} 条'
            else:
                reason = learned.get('skipped') or ''
                message = {
                    'interval': '未到学习间隔',
                    'no-material': '暂无可学习的素材',
                    'disabled': '在线学习已关闭',
                }.get(reason, '没有新日记或未到整理时间')
                self.done.emit(False, message)
                return
            self.done.emit(True, message)
        except Exception as exc:  # noqa: BLE001
            self.done.emit(False, str(exc))
        finally:
            if self.db is not None:
                try:
                    self.db.close_session()
                except Exception:  # noqa: BLE001
                    pass
