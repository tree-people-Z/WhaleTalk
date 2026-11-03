"""扫码登录对话框：网络请求全部放在工作线程，避免卡住界面。"""

import asyncio
import time

from PyQt6.QtCore import QThread, Qt, pyqtSignal
from PyQt6.QtGui import QPixmap
from PyQt6.QtWidgets import (
    QDialog, QLabel, QMessageBox, QProgressBar, QPushButton, QVBoxLayout,
)
from loguru import logger

from core.bilibili_api import BilibiliAPI

QR_TIMEOUT_SECONDS = 180


class LoginWorker(QThread):
    """生成二维码并轮询扫码状态。"""

    qr_ready = pyqtSignal(bytes)
    scanned = pyqtSignal()
    succeeded = pyqtSignal()
    failed = pyqtSignal(str)
    expired = pyqtSignal()

    def __init__(self, bili_api: BilibiliAPI, parent=None):
        super().__init__(parent)
        self.bili_api = bili_api
        self._stop = False

    def stop(self):
        self._stop = True

    def run(self):
        try:
            asyncio.run(self._flow())
        except Exception as exc:  # noqa: BLE001
            logger.exception(f'扫码登录失败: {exc}')
            self.failed.emit(str(exc))

    async def _flow(self):
        ok, qr_image, qr_login = await self.bili_api.login_with_qr()
        if not ok or not qr_image or qr_login is None:
            self.failed.emit('无法生成登录二维码')
            return
        logger.info('二维码已生成，等待扫描...')
        self.qr_ready.emit(qr_image)

        scanned = False
        deadline = time.monotonic() + QR_TIMEOUT_SECONDS
        while not self._stop and time.monotonic() < deadline:
            result = await self.bili_api.check_qr_status(qr_login)
            status = result.get('status')
            if status == 'success':
                self.succeeded.emit()
                return
            if status == 'expired':
                self.expired.emit()
                return
            if status == 'error':
                self.failed.emit(result.get('message') or '登录状态检查失败')
                return
            if result.get('scanned') and not scanned:
                scanned = True
                self.scanned.emit()
            await asyncio.sleep(1.5)
        if not self._stop:
            self.expired.emit()


class LoginDialog(QDialog):
    """B站登录对话框"""

    def __init__(self, bili_api: BilibiliAPI, parent=None):
        super().__init__(parent)
        self.bili_api = bili_api
        self.worker = None
        self.init_ui()
        self.start_login()

    def init_ui(self):
        self.setWindowTitle("扫码登录B站")
        self.setModal(True)
        self.setMinimumSize(420, 520)

        layout = QVBoxLayout()
        tip_label = QLabel("请使用哔哩哔哩APP扫描二维码登录")
        tip_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(tip_label)

        self.qr_label = QLabel("正在生成二维码…")
        self.qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.qr_label.setMinimumSize(300, 300)
        self.qr_label.setStyleSheet(
            "QLabel { background-color: white; border: 1px solid #d0d7de;"
            " border-radius: 8px; }"
        )
        layout.addWidget(self.qr_label)

        self.status_label = QLabel("正在生成二维码...")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.status_label)

        self.progress = QProgressBar()
        self.progress.setMaximum(0)
        layout.addWidget(self.progress)

        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        layout.addWidget(cancel_btn)
        self.setLayout(layout)

    def start_login(self):
        self.worker = LoginWorker(self.bili_api, self)
        self.worker.qr_ready.connect(self._on_qr_ready)
        self.worker.scanned.connect(self._on_scanned)
        self.worker.succeeded.connect(self._on_success)
        self.worker.failed.connect(self._on_failure)
        self.worker.expired.connect(self._on_expired)
        self.worker.start()

    def _on_qr_ready(self, image: bytes):
        pixmap = QPixmap()
        pixmap.loadFromData(image)
        self.qr_label.setPixmap(
            pixmap.scaled(
                280, 280,
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        )
        self.status_label.setText("请扫码登录")
        self.progress.setMaximum(100)
        self.progress.setValue(10)

    def _on_scanned(self):
        self.status_label.setText("已扫描，请在手机上确认登录")
        self.progress.setValue(60)

    def _on_success(self):
        self.status_label.setText("✅ 登录成功！")
        self.progress.setValue(100)
        self._stop_worker()
        self.accept()

    def _on_failure(self, message: str):
        self.status_label.setText(f"❌ 错误: {message}")
        QMessageBox.critical(self, "错误", f"登录失败:\n{message}")
        self.reject()

    def _on_expired(self):
        self.status_label.setText("⏱️ 二维码已过期")
        QMessageBox.warning(self, "提示", "二维码已过期，请重新登录")
        self.reject()

    def _stop_worker(self):
        if self.worker is not None and self.worker.isRunning():
            self.worker.stop()
            self.worker.wait(3000)
        self.worker = None

    def closeEvent(self, event):
        self._stop_worker()
        event.accept()

    def reject(self):
        self._stop_worker()
        super().reject()
