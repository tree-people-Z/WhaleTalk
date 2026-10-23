"""
登录对话框
"""

import asyncio
from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QPushButton,
    QMessageBox, QProgressBar
)
from PyQt6.QtCore import QTimer, Qt
from PyQt6.QtGui import QPixmap
from loguru import logger

from core.bilibili_api import BilibiliAPI


class LoginDialog(QDialog):
    """B站登录对话框"""

    def __init__(self, bili_api: BilibiliAPI, parent=None):
        super().__init__(parent)
        self.bili_api = bili_api
        self.qr_login = None
        self.check_timer = None

        self.init_ui()
        self.start_login()

    def init_ui(self):
        """初始化UI"""
        self.setWindowTitle("扫码登录B站")
        self.setModal(True)
        self.setMinimumSize(400, 500)

        layout = QVBoxLayout()

        # 提示文字
        tip_label = QLabel("请使用哔哩哔哩APP扫描二维码登录")
        tip_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(tip_label)

        # 二维码显示
        self.qr_label = QLabel()
        self.qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.qr_label.setMinimumSize(300, 300)
        self.qr_label.setStyleSheet("QLabel { background-color: white; border: 1px solid #ccc; }")
        layout.addWidget(self.qr_label)

        # 状态标签
        self.status_label = QLabel("正在生成二维码...")
        self.status_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.status_label)

        # 进度条
        self.progress = QProgressBar()
        self.progress.setMaximum(0)  # 无限进度条
        layout.addWidget(self.progress)

        # 取消按钮
        cancel_btn = QPushButton("取消")
        cancel_btn.clicked.connect(self.reject)
        layout.addWidget(cancel_btn)

        self.setLayout(layout)

    def start_login(self):
        """开始登录流程"""
        try:
            # 使用事件循环获取二维码
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            success, qr_image, qr_login = loop.run_until_complete(self.bili_api.login_with_qr())

            if success and qr_image and qr_login:
                # 保存登录对象
                self.qr_login = qr_login

                # 显示二维码
                pixmap = QPixmap()
                pixmap.loadFromData(qr_image)
                scaled_pixmap = pixmap.scaled(
                    280, 280,
                    Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation
                )
                self.qr_label.setPixmap(scaled_pixmap)
                self.status_label.setText("请扫码登录")

                # 开始轮询检查登录状态
                self.start_check_timer()
            else:
                self.status_label.setText("❌ 生成二维码失败")
                QMessageBox.critical(self, "错误", "无法生成登录二维码")
                self.reject()

        except Exception as e:
            logger.error(f"登录流程启动失败: {e}")
            import traceback
            logger.error(traceback.format_exc())
            self.status_label.setText(f"❌ 错误: {e}")
            QMessageBox.critical(self, "错误", f"登录失败:\n{e}")
            self.reject()

    def start_check_timer(self):
        """启动登录状态检查定时器"""
        # 简化版本：直接提示用户刷新
        self.progress.setMaximum(100)
        self.progress.setValue(0)

        # 模拟检查（实际应该轮询B站API）
        self.check_timer = QTimer()
        self.check_timer.timeout.connect(self.check_login_status)
        self.check_timer.start(2000)  # 每2秒检查一次

        # 60秒后超时
        QTimer.singleShot(60000, self.on_timeout)

    def check_login_status(self):
        """检查登录状态"""
        if not self.qr_login:
            return

        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            result = loop.run_until_complete(self.bili_api.check_qr_status(self.qr_login))

            if result['status'] == 'success':
                self.status_label.setText("✅ 登录成功！")
                self.progress.setValue(100)
                if self.check_timer:
                    self.check_timer.stop()
                QTimer.singleShot(500, self.accept)
            elif result['status'] == 'error':
                self.status_label.setText(f"❌ 错误: {result.get('message', '未知错误')}")
                if self.check_timer:
                    self.check_timer.stop()
            else:
                # 更新进度条
                current = self.progress.value()
                self.progress.setValue(min(current + 5, 95))

        except Exception as e:
            logger.error(f"检查登录状态失败: {e}")

    def on_timeout(self):
        """超时处理"""
        if self.check_timer:
            self.check_timer.stop()

        if not self.bili_api.credential:
            self.status_label.setText("⏱️ 二维码已过期")
            QMessageBox.warning(self, "提示", "二维码已过期，请重新登录")
            self.reject()

    def closeEvent(self, event):
        """关闭事件"""
        if self.check_timer:
            self.check_timer.stop()
        event.accept()
