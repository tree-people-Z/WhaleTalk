"""自由 Agent 的后台工作线程。"""

import asyncio

from PyQt6.QtCore import QThread, pyqtSignal
from loguru import logger


class AnalysisWorker(QThread):
    """在独立线程里跑一轮 Agent，避免阻塞 GUI。"""

    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, analyzer, operation='analysis'):
        super().__init__()
        self.analyzer = analyzer
        self.operation = operation

    def run(self):
        loop = asyncio.new_event_loop()
        try:
            asyncio.set_event_loop(loop)
            if self.operation == 'replies':
                result = loop.run_until_complete(self.analyzer.check_replies())
            else:
                result = loop.run_until_complete(self.analyzer.run_analysis_cycle())
            self.finished.emit(result)
        except asyncio.CancelledError:
            self.finished.emit({'status': 'cancelled'})
        except Exception as e:  # noqa: BLE001
            logger.error(f"Agent 任务异常: {e}")
            self.error.emit(str(e))
        finally:
            # 释放本线程的数据库 Session，避免线程结束后连接被长期占用
            db = getattr(self.analyzer, 'db', None)
            if db is not None:
                try:
                    db.close_session()
                except Exception:  # noqa: BLE001
                    pass
            try:
                pending = asyncio.all_tasks(loop)
                for task in pending:
                    task.cancel()
                if pending:
                    loop.run_until_complete(
                        asyncio.gather(*pending, return_exceptions=True)
                    )
            finally:
                loop.close()
                asyncio.set_event_loop(None)
