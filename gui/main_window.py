"""
主窗口GUI
"""

import os
import sys
from pathlib import Path
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QPushButton, QLabel, QTabWidget, QTextEdit,
    QGroupBox, QMessageBox, QStatusBar, QTableWidget,
    QTableWidgetItem, QHeaderView, QProgressDialog, QApplication
)
from PyQt6.QtCore import QTimer, Qt, QThread, pyqtSignal
from PyQt6.QtGui import QFont, QIcon, QDesktopServices
from PyQt6.QtCore import QUrl
from loguru import logger

from gui.login_dialog import LoginDialog
from gui.settings_page import SettingsPage
from gui.comments_tab import CommentsTab
from gui.messages_tab import MessagesTab
from gui.styles import MODERN_STYLE
from gui.update_check import UpdateCheckWorker, UpdateDownloadWorker, prompt_update
from core.bilibili_api import BilibiliAPI
from core.ai_client import AIClient
from core.video_analyzer import VideoAnalyzer
from core.scheduler import TaskScheduler
from utils.database import Database
from utils.config_manager import ConfigManager
from utils.updater import launch_update_installer


class AnalysisWorker(QThread):
    """分析任务工作线程"""
    finished = pyqtSignal(dict)
    error = pyqtSignal(str)

    def __init__(self, analyzer, operation='analysis'):
        super().__init__()
        self.analyzer = analyzer
        self.operation = operation

    def run(self):
        """运行分析任务"""
        import asyncio
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
        except Exception as e:
            logger.error(f"分析任务异常: {e}")
            self.error.emit(str(e))
        finally:
            try:
                pending = asyncio.all_tasks(loop)
                for task in pending:
                    task.cancel()
                if pending:
                    loop.run_until_complete(asyncio.gather(*pending, return_exceptions=True))
            finally:
                loop.close()
                asyncio.set_event_loop(None)


class MainWindow(QMainWindow):
    """主窗口"""

    scheduled_run_requested = pyqtSignal()
    scheduled_reply_check_requested = pyqtSignal()
    log_message_received = pyqtSignal(str)

    def __init__(self):
        super().__init__()

        # 初始化组件
        self.config = ConfigManager()
        self.db = Database()
        self.bili_api = None
        self.ai_client = None
        self.video_analyzer = None
        self.scheduler = None
        self.worker = None
        self.reply_worker = None

        # APScheduler 回调运行于后台线程，界面更新转发至 Qt 主线程。
        self.scheduled_run_requested.connect(self.scheduled_run)
        self.scheduled_reply_check_requested.connect(self.scheduled_reply_check)

        self.init_ui()
        self.log_message_received.connect(self._append_runtime_log)
        self._gui_log_sink_id = logger.add(
            lambda message: self.log_message_received.emit(str(message).rstrip()),
            level="INFO",
            format="{time:HH:mm:ss} | {level:<8} | {message}",
        )
        self.init_components()
        self.load_status()

        # 后台检查更新（不阻塞启动），设置页也可手动触发。
        self._update_worker = None
        self._update_download = None
        self._update_progress = None
        self.settings_page.check_update_requested.connect(self.check_updates_manually)
        self._update_timer = QTimer(self)
        self._update_timer.setSingleShot(True)
        self._update_timer.setInterval(5000)
        self._update_timer.timeout.connect(lambda: self.check_updates(silent=True))
        self._update_timer.start()

        # 运行期间每 6 小时复查一次更新。
        self._update_recheck_timer = QTimer(self)
        self._update_recheck_timer.setInterval(6 * 60 * 60 * 1000)
        self._update_recheck_timer.timeout.connect(lambda: self.check_updates(silent=True))
        self._update_recheck_timer.start()

    def init_ui(self):
        """初始化UI"""
        self.setWindowTitle("鲸语 · B站智能运营助手")
        icon_path = Path(__file__).resolve().parent.parent / 'assets' / 'whale-assistant.ico'
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))
        self.setMinimumSize(1000, 700)

        # 应用现代化样式
        self.setStyleSheet(MODERN_STYLE)

        # 主布局
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        layout = QVBoxLayout(main_widget)
        layout.setSpacing(14)
        layout.setContentsMargins(22, 18, 22, 14)

        # 顶部状态栏
        status_group = self._create_status_section()
        layout.addWidget(status_group)

        # 标签页
        self.tabs = QTabWidget()

        # 控制台标签
        self.console_tab = self._create_console_tab()
        self.tabs.addTab(self.console_tab, "控制台")

        # 历史记录标签
        self.history_tab = self._create_history_tab()
        self.tabs.addTab(self.history_tab, "历史记录")

        # 评论对话标签
        self.comments_tab = CommentsTab(self.db)
        self.tabs.addTab(self.comments_tab, "评论")

        # 私信标签
        self.messages_tab = MessagesTab()
        self.tabs.addTab(self.messages_tab, "私信")

        # 设置标签
        self.settings_page = SettingsPage(self.config)
        self.settings_page.auto_run_btn.clicked.connect(self.toggle_auto_run)
        self.settings_page.schedule_settings_saved.connect(self.refresh_scheduler_settings)
        self.settings_page.ai_settings_saved.connect(self.refresh_ai_settings)
        self.settings_page.analysis_settings_saved.connect(self.refresh_analysis_settings)
        self.tabs.addTab(self.settings_page, "设置")

        layout.addWidget(self.tabs)
        self.tabs.currentChanged.connect(self._on_tab_changed)

        # 状态栏
        self.statusBar = QStatusBar()
        self.setStatusBar(self.statusBar)
        self.statusBar.showMessage("就绪")

    def _create_status_section(self) -> QGroupBox:
        """创建状态区域"""
        group = QGroupBox("📊 运行状态")
        layout = QVBoxLayout()
        layout.setSpacing(12)

        # 登录状态行
        login_layout = QHBoxLayout()
        self.login_status_label = QLabel("● 未登录")
        self.login_status_label.setObjectName("statusLabel")
        self.login_status_label.setStyleSheet("color: #dc3545; font-size: 14px; font-weight: 600;")
        login_layout.addWidget(self.login_status_label)
        login_layout.addStretch()

        self.login_btn = QPushButton("🔐 登录B站")
        self.login_btn.clicked.connect(self.show_login_dialog)
        self.login_btn.setMinimumHeight(36)
        login_layout.addWidget(self.login_btn)

        layout.addLayout(login_layout)

        # 统计信息
        stats_layout = QHBoxLayout()
        self.stats_label = QLabel("📈 今日: 0条评论 | 总计: 0个视频 | 0条评论")
        self.stats_label.setStyleSheet("color: #586069; font-size: 13px;")
        stats_layout.addWidget(self.stats_label)
        stats_layout.addStretch()
        layout.addLayout(stats_layout)

        group.setLayout(layout)
        return group

    def _create_console_tab(self) -> QWidget:
        """创建控制台标签"""
        widget = QWidget()
        layout = QVBoxLayout()
        layout.setSpacing(15)

        # 控制按钮
        btn_layout = QHBoxLayout()
        btn_layout.setSpacing(10)

        self.run_now_btn = QPushButton("🚀 现在巡视一轮")
        self.run_now_btn.setObjectName("primaryButton")
        self.run_now_btn.clicked.connect(self.run_analysis_now)
        self.run_now_btn.setMinimumHeight(45)
        self.run_now_btn.setStyleSheet("""
            QPushButton#primaryButton {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #2ea44f, stop:1 #2c974b);
                font-size: 14px;
                font-weight: 600;
            }
            QPushButton#primaryButton:hover {
                background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
                    stop:0 #2c974b, stop:1 #298e46);
            }
        """)
        btn_layout.addWidget(self.run_now_btn)

        self.auto_run_btn = QPushButton("⏰ 启动自动运营")
        self.auto_run_btn.clicked.connect(self.toggle_auto_run)
        self.auto_run_btn.setMinimumHeight(45)
        self.auto_run_btn.setStyleSheet("font-size: 14px; font-weight: 600;")
        btn_layout.addWidget(self.auto_run_btn)

        layout.addLayout(btn_layout)

        # 日志显示
        log_group = QGroupBox("运行日志")
        log_layout = QVBoxLayout()

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setObjectName("logText")
        self.log_text.setFont(QFont("Consolas", 9))
        log_layout.addWidget(self.log_text)

        log_group.setLayout(log_layout)
        layout.addWidget(log_group)

        widget.setLayout(layout)
        return widget

    def _create_history_tab(self) -> QWidget:
        """创建历史记录标签"""
        widget = QWidget()
        layout = QVBoxLayout()

        # 刷新按钮
        refresh_btn = QPushButton("🔄 刷新")
        refresh_btn.clicked.connect(self.load_history)
        layout.addWidget(refresh_btn)

        # 历史记录表格
        self.history_table = QTableWidget()
        self.history_table.setAlternatingRowColors(True)
        self.history_table.setShowGrid(False)
        self.history_table.setColumnCount(7)
        self.history_table.setHorizontalHeaderLabels([
            "时间", "标题", "作者", "评分", "已评论", "评论内容", "视频链接"
        ])
        self.history_table.cellClicked.connect(self._open_history_video)

        header = self.history_table.horizontalHeader()
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(5, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.ResizeToContents)

        layout.addWidget(self.history_table)

        widget.setLayout(layout)
        return widget

    def init_components(self):
        """初始化组件"""
        try:
            # 初始化B站API
            self.bili_api = BilibiliAPI()
            self.messages_tab.set_bili_api(self.bili_api)
            self.comments_tab.set_bili_api(self.bili_api)

            # 初始化AI客户端
            ai_config = self.config.get('ai', {})
            if ai_config.get('api_key'):
                self.ai_client = AIClient(
                    provider=ai_config.get('provider', 'openai'),
                    api_key=ai_config.get('api_key'),
                    model=ai_config.get('model'),
                    base_url=ai_config.get('base_url')
                )
                self.log("✅ AI客户端已初始化")
            else:
                self.log("⚠️ 未配置AI API密钥，请前往设置页面配置")

            # 初始化视频分析器
            if self.bili_api and self.ai_client:
                self.video_analyzer = VideoAnalyzer(
                    self.bili_api,
                    self.ai_client,
                    self.db,
                    self.config
                )
            self._active_ai_signature = self._ai_signature()

            # 初始化调度器
            self.scheduler = TaskScheduler(self.config)
            if self.video_analyzer:
                self.scheduler.set_wake_callback(self.scheduled_run)
                self.scheduler.set_reply_check_callback(self.scheduled_reply_check)

        except Exception as e:
            logger.error(f"初始化组件失败: {e}")
            self.log(f"❌ 初始化失败: {e}")

    def load_status(self):
        """加载状态"""
        # 检查登录状态
        import asyncio
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            is_logged_in = loop.run_until_complete(self.bili_api.check_login())

            # 即使API检查失败，只要cookies存在就认为已登录
            has_credential = (self.bili_api.credential and
                            self.bili_api.credential.sessdata and
                            len(self.bili_api.credential.sessdata) > 20)

            if is_logged_in or has_credential:
                self.login_status_label.setText("● 已登录")
                self.login_status_label.setStyleSheet("color: #2ea44f; font-size: 14px; font-weight: 600;")
                self.login_btn.setText("🔐 切换账号")
                self.log("✅ B站账号已登录")
            else:
                self.login_status_label.setText("● 未登录")
                self.login_status_label.setStyleSheet("color: #dc3545; font-size: 14px; font-weight: 600;")
                self.log("请先登录B站账号")
        except Exception as e:
            logger.error(f"检查登录状态失败: {e}")

        # 加载统计信息
        self.update_stats()

        # 检查自动运行状态
        if self.config.get('schedule.auto_run', False):
            self.scheduler.start()
            if self.scheduler.is_running:
                self.auto_run_btn.setText("⏸️ 停止自动运营")
                self.settings_page.auto_run_btn.setText("⏸️ 停止自动运营")
                self.log("自动运营已启动")
            else:
                self.auto_run_btn.setText("⏰ 启动自动运营")
                self.settings_page.auto_run_btn.setText("⏰ 启动自动运营")
                self.log("自动运行配置未能启动，请检查AI配置与唤醒时段")

    def update_stats(self):
        """更新统计信息"""
        stats = self.db.get_statistics()
        self.stats_label.setText(
            f"今日: {stats['today_comments']}条评论 | "
            f"总计: {stats['total_videos_analyzed']}个视频 | "
            f"{stats['total_comments_sent']}条评论"
        )

    def show_login_dialog(self):
        """显示登录对话框"""
        dialog = LoginDialog(self.bili_api, self)
        if dialog.exec():
            self.login_status_label.setText("● 已登录")
            self.login_status_label.setStyleSheet("color: #2ea44f; font-size: 14px; font-weight: 600;")
            self.login_btn.setText("🔐 切换账号")
            self.log("✅ 登录成功！")
            self.messages_tab.set_bili_api(self.bili_api)
            self.comments_tab.set_bili_api(self.bili_api)

    def run_analysis_now(self):
        """立即运行分析"""
        if not self.video_analyzer:
            QMessageBox.warning(self, "错误", "请先配置AI API密钥")
            return

        if self.worker and self.worker.isRunning():
            if self.sender() is self.run_now_btn:
                QMessageBox.information(self, "提示", "任务正在运行中...")
            return
        if self.reply_worker and self.reply_worker.isRunning():
            if self.sender() is self.run_now_btn:
                QMessageBox.information(self, "提示", "正在检查评论回复，请稍候...")
            return

        self.run_now_btn.setEnabled(False)
        self.statusBar.showMessage("正在分析...")
        self.log("开始执行分析任务...")

        # 创建工作线程
        self.worker = AnalysisWorker(self.video_analyzer)
        self.worker.finished.connect(self.on_analysis_finished)
        self.worker.error.connect(self.on_analysis_error)
        self.worker.start()

    def on_analysis_finished(self, result: dict):
        """分析完成"""
        QTimer.singleShot(0, self.refresh_ai_settings)
        self.run_now_btn.setEnabled(True)
        if result.get('status') == 'cancelled':
            self.statusBar.showMessage("任务已停止")
            self.log("⏹️ 分析任务已安全停止")
            return
        if result.get('status') == 'replies_checked':
            self.on_reply_check_finished(result)
            return
        self.statusBar.showMessage("任务完成")

        status = result.get('status', 'unknown')

        if status == 'success':
            self.log(f"✅ 分析完成!")
            self.log(f"  - 找到视频: {result['videos_found']}个")
            self.log(f"  - 分析视频: {result['videos_analyzed']}个")
            self.log(f"  - 值得关注: {result['worthy_count']}个")
            self.log(f"  - 发送评论: {result['comments_sent']}条")
        elif status == 'quota_exhausted':
            self.log("⚠️ 今日评论配额已用完")
        elif status == 'no_videos_found':
            self.log("ℹ️ 未找到符合条件的视频")

        self.update_stats()
        self.load_history()

    def on_analysis_error(self, error: str):
        """分析出错"""
        QTimer.singleShot(0, self.refresh_ai_settings)
        self.run_now_btn.setEnabled(True)
        self.statusBar.showMessage("任务失败")
        self.log(f"❌ 任务失败: {error}")
        QMessageBox.critical(self, "错误", f"任务执行失败:\n{error}")

    def scheduled_reply_check(self):
        """由调度器触发的评论回复检查。"""
        if (not self.video_analyzer or not self.config.get('interaction.auto_reply', True)
                or (self.worker and self.worker.isRunning())
                or (self.reply_worker and self.reply_worker.isRunning())):
            return False
        if QThread.currentThread() != self.thread():
            self.scheduled_reply_check_requested.emit()
            return True
        self.reply_worker = AnalysisWorker(self.video_analyzer, operation='replies')
        self.reply_worker.finished.connect(self.on_reply_check_finished)
        self.reply_worker.error.connect(lambda error: self.log(f"❌ 回复检查失败: {error}"))
        self.reply_worker.start()
        return True

    def refresh_scheduler_settings(self):
        """保存调度设置后，让运行中的调度器立即应用新时段和间隔。"""
        if not self.scheduler or not self.scheduler.is_running:
            return
        self.scheduler.stop()
        self.scheduler.start()
        if self.scheduler.is_running:
            self.log("⚙️ 自动运营设置已更新")

    def _ai_signature(self):
        return tuple(self.config.get(f'ai.{key}', '') for key in ('provider', 'api_key', 'model', 'base_url'))

    def refresh_analysis_settings(self):
        """Apply media-analysis switches and model choice to the live analyzer."""
        if not self.video_analyzer:
            return
        from core.audio_transcriber import LocalAudioTranscriber
        self.video_analyzer.enable_frame_analysis = self.config.get(
            'analysis.enable_frame_analysis', True
        )
        self.video_analyzer.local_transcriber = LocalAudioTranscriber(
            model_name=self.config.get('analysis.local_transcription_model', 'medium')
        )
        self.log("⚙️ 画面分析与本地转写设置已应用")

    def refresh_ai_settings(self):
        """AI连接参数变化后重建客户端和分析器，使保存的设置立即生效。"""
        signature = self._ai_signature()
        if signature == getattr(self, '_active_ai_signature', None):
            return
        if ((self.worker and self.worker.isRunning())
                or (self.reply_worker and self.reply_worker.isRunning())):
            self.log("⚙️ AI设置已保存；当前任务结束后会自动应用")
            return
        provider, api_key, model, base_url = signature
        try:
            self.ai_client = AIClient(
                provider=provider, api_key=api_key, model=model, base_url=base_url
            ) if api_key else None
            self.video_analyzer = VideoAnalyzer(
                self.bili_api, self.ai_client, self.db, self.config
            ) if self.bili_api and self.ai_client else None
            scheduler_was_running = bool(self.scheduler and self.scheduler.is_running)
            if scheduler_was_running:
                self.scheduler.stop()
            self.scheduler = TaskScheduler(self.config)
            if self.video_analyzer:
                self.scheduler.set_wake_callback(self.scheduled_run)
                self.scheduler.set_reply_check_callback(self.scheduled_reply_check)
            if scheduler_was_running and self.video_analyzer:
                self.scheduler.start()
            self._active_ai_signature = signature
            self.log("✅ AI设置已应用，客户端已重建")
        except Exception as exc:
            logger.exception(f"应用AI设置失败: {exc}")
            self.log(f"❌ 应用AI设置失败: {exc}")

    def on_reply_check_finished(self, result: dict):
        QTimer.singleShot(0, self.refresh_ai_settings)
        if result.get('status') == 'replies_checked' and result.get('replied', 0):
            self.log(f"💬 已自动回复 {result['replied']} 条新评论")

    def toggle_auto_run(self):
        """切换自动运行"""
        if not self.scheduler:
            return

        if self.scheduler.is_running:
            self.scheduler.stop()
            self.auto_run_btn.setText("⏰ 启动自动运营")
            self.settings_page.auto_run_btn.setText("⏰ 启动自动运营")
            self.config.set('schedule.auto_run', False)
            self.log("自动运营已停止")
        else:
            if not self.video_analyzer:
                QMessageBox.warning(self, "无法启动", "请先配置有效的AI API密钥。")
                return
            if not self.bili_api or not self.bili_api.credential:
                QMessageBox.warning(self, "无法启动", "请先登录B站账号。")
                return
            self.config.set('schedule.auto_run', True)
            self.scheduler.start()
            if not self.scheduler.is_running:
                self.config.set('schedule.auto_run', False)
                QMessageBox.warning(self, "无法启动", "没有有效的自动运行时段，请检查设置。")
                return
            self.auto_run_btn.setText("⏸️ 停止自动运营")
            self.settings_page.auto_run_btn.setText("⏸️ 停止自动运营")
            self.log("自动运营已启动")

            # 显示下次运行时间
            next_run = self.scheduler.get_next_run_time()
            if next_run:
                self.log(f"下次运行: {next_run.strftime('%Y-%m-%d %H:%M')}")

    def scheduled_run(self):
        """计划任务执行"""
        if ((self.worker and self.worker.isRunning())
                or (self.reply_worker and self.reply_worker.isRunning())):
            if QThread.currentThread() == self.thread():
                self.log("⏭️ 上一轮仍在运行，保留定时任务稍后重试")
            return False
        if QThread.currentThread() != self.thread():
            self.scheduled_run_requested.emit()
            return True
        self.log("⏰ 定时任务触发")
        self.run_analysis_now()
        return True

    def load_history(self):
        """加载历史记录"""
        records = self.db.get_recent_videos(limit=50)

        self.history_table.setRowCount(len(records))

        for i, record in enumerate(records):
            # 时间
            time_item = QTableWidgetItem(
                record.analyzed_at.strftime('%m-%d %H:%M') if record.analyzed_at else ""
            )
            self.history_table.setItem(i, 0, time_item)

            # 标题
            title_item = QTableWidgetItem(record.title or "")
            self.history_table.setItem(i, 1, title_item)

            # 作者
            author_item = QTableWidgetItem(record.author or "")
            self.history_table.setItem(i, 2, author_item)

            # 评分
            score_item = QTableWidgetItem(str(record.score or 0))
            self.history_table.setItem(i, 3, score_item)

            # 已评论
            commented_item = QTableWidgetItem("✅" if record.commented else "")
            self.history_table.setItem(i, 4, commented_item)

            # 评论内容
            comment_item = QTableWidgetItem(record.comment_text or "")
            self.history_table.setItem(i, 5, comment_item)

            # 视频链接
            link_item = QTableWidgetItem("打开视频 ↗" if record.bvid else "")
            if record.bvid:
                link_item.setData(
                    Qt.ItemDataRole.UserRole,
                    f"https://www.bilibili.com/video/{record.bvid}"
                )
                link_item.setForeground(Qt.GlobalColor.blue)
                link_item.setToolTip("点击打开B站视频")
            self.history_table.setItem(i, 6, link_item)

    def _open_history_video(self, row: int, column: int):
        """打开历史记录对应的视频页面。"""
        if column != 6:
            return
        item = self.history_table.item(row, column)
        url = item.data(Qt.ItemDataRole.UserRole) if item else None
        if url:
            QDesktopServices.openUrl(QUrl(url))

    def log(self, message: str):
        """添加日志"""
        logger.info(message)

    def _append_runtime_log(self, message: str):
        """Append structured runtime logs safely from workers to the GUI."""
        self.log_text.append(message)

    def _on_tab_changed(self, index: int):
        """切换到对话页时按需刷新数据。"""
        widget = self.tabs.widget(index)
        if widget is self.comments_tab:
            self.comments_tab.refresh_if_stale()
        elif widget is self.messages_tab:
            self.messages_tab.refresh_if_stale()

    def check_updates_manually(self):
        """手动检查更新（来自设置页按钮）。"""
        self.check_updates(silent=False)

    def check_updates(self, silent: bool = False):
        """在后台线程检查 GitHub Releases，避免阻塞界面。"""
        if self._update_worker is not None and self._update_worker.isRunning():
            return
        if not silent:
            self.settings_page.check_update_btn.setEnabled(False)
            self.statusBar.showMessage("正在检查更新…")
        worker = UpdateCheckWorker(self)
        self._update_worker = worker
        worker.checked.connect(lambda result: self._handle_update_result(result, silent))
        worker.finished.connect(lambda: self._update_check_finished(worker))
        worker.start()

    def _update_check_finished(self, worker):
        worker.deleteLater()
        if self._update_worker is worker:
            self._update_worker = None
        self.settings_page.check_update_btn.setEnabled(True)
        if self.statusBar.currentMessage() == "正在检查更新…":
            self.statusBar.clearMessage()

    def _handle_update_result(self, result, silent):
        action = prompt_update(self, result, silent)
        if action == "install":
            self._start_update_download(result)
            return
        if result.get("status") == "update":
            version = result.get("version", "")
            self.settings_page.check_update_btn.setText(f"⬆️ 更新到 v{version}")
            self.statusBar.showMessage(
                f"发现新版本 v{version}：可在 设置 → 关于与更新 中一键更新"
            )
        elif result.get("status") == "latest":
            self.settings_page.check_update_btn.setText("🔃 检查更新")

    def _start_update_download(self, result):
        if not getattr(sys, 'frozen', False):
            QMessageBox.information(self, "更新", "源码运行模式请直接 git pull 更新。")
            return
        dialog = QProgressDialog("正在下载更新包…", "取消", 0, 100, self)
        dialog.setWindowTitle("正在更新")
        dialog.setWindowModality(Qt.WindowModality.WindowModal)
        dialog.setMinimumDuration(0)
        dialog.setAutoClose(False)
        dialog.setAutoReset(False)
        worker = UpdateDownloadWorker(
            result.get("asset_url", ""), result.get("asset_digest", ""), self
        )
        self._update_download = worker
        self._update_progress = dialog

        def on_progress(done, total):
            if total > 0:
                dialog.setMaximum(100)
                dialog.setValue(min(100, int(done * 100 / total)))
                dialog.setLabelText(
                    f"正在下载更新包… {done / 1048576:.1f} / {total / 1048576:.1f} MB"
                )
            else:
                dialog.setMaximum(0)

        worker.progress.connect(on_progress)
        worker.ready.connect(lambda source: self._apply_update(source, dialog))
        worker.failed.connect(lambda message: self._update_failed(message, dialog))
        worker.cancelled.connect(lambda: self._update_cancelled(dialog))
        dialog.canceled.connect(worker.cancel)
        worker.finished.connect(worker.deleteLater)
        worker.start()

    def _apply_update(self, source, dialog):
        dialog.setLabelText("正在准备安装…")
        dialog.setMaximum(0)
        try:
            install_dir = Path(sys.executable).resolve().parent
            launch_update_installer(Path(source), install_dir, os.getpid())
        except Exception as exc:
            dialog.close()
            QMessageBox.critical(self, "更新失败", f"无法启动更新程序：{exc}")
            return
        dialog.close()
        self._update_progress = None
        QMessageBox.information(
            self,
            "更新准备完成",
            "程序将关闭并自动完成更新，随后会重新启动，请稍候…",
        )
        self.close()
        QApplication.instance().quit()

    def _update_failed(self, message, dialog):
        dialog.close()
        self._update_progress = None
        self._update_download = None
        QMessageBox.warning(self, "更新失败", f"下载或解压更新包失败：{message}\n\n也可以打开发布页手动下载。")

    def _update_cancelled(self, dialog):
        dialog.close()
        self._update_progress = None
        self._update_download = None
        self.statusBar.showMessage("已取消更新", 3000)

    def closeEvent(self, event):
        """关闭事件"""
        self._update_timer.stop()
        self._update_recheck_timer.stop()
        self.comments_tab.shutdown()
        self.messages_tab.shutdown()
        if self._update_worker is not None and self._update_worker.isRunning():
            self._update_worker.wait(3000)
        if self._update_download is not None and self._update_download.isRunning():
            self._update_download.cancel()
            self._update_download.wait(3000)

        if self.scheduler and self.scheduler.is_running:
            self.scheduler.stop()

        if getattr(self, '_gui_log_sink_id', None) is not None:
            logger.remove(self._gui_log_sink_id)
            self._gui_log_sink_id = None

        workers = [worker for worker in (self.worker, self.reply_worker)
                   if worker and worker.isRunning()]
        if workers:
            if self.video_analyzer:
                self.video_analyzer.request_stop()
            for worker in workers:
                worker.requestInterruption()
            stopped = True
            for worker in workers:
                stopped = worker.wait(10000) and stopped
            if not stopped:
                self.log("后台任务仍在等待网络请求结束，请稍后再次关闭窗口")
                event.ignore()
                return

        self.db.close()
        event.accept()
