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
    QTableWidgetItem, QHeaderView, QProgressDialog, QApplication,
    QSystemTrayIcon, QMenu, QButtonGroup
)
from PyQt6.QtCore import QTimer, Qt, QThread, pyqtSignal, QSize
from PyQt6.QtGui import QFont, QIcon, QPixmap, QDesktopServices, QAction
from PyQt6.QtCore import QUrl
from loguru import logger

from gui.login_dialog import LoginDialog
from gui.settings_page import SettingsPage
from gui.comments_tab import CommentsTab
from gui.messages_tab import MessagesTab
from gui.dashboard_tab import DashboardTab
from gui.icons import load_icon
from gui.styles import MODERN_STYLE
from gui.update_check import UpdateCheckWorker, UpdateDownloadWorker, prompt_update
from core.bilibili_api import BilibiliAPI
from core.ai_client import AIClient
from core.free_agent import FreeAgent
from core.scheduler import TaskScheduler
from gui.analysis_worker import AnalysisWorker
from gui.memory_worker import MemoryWorker
from utils.database import Database
from utils.config_manager import ConfigManager
from utils.updater import APP_VERSION, launch_update_installer


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
        self.agent = None
        self.scheduler = None
        self.worker = None
        self.reply_worker = None

        # APScheduler 回调运行于后台线程，界面更新转发至 Qt 主线程。
        self.scheduled_run_requested.connect(self.scheduled_run)
        self.scheduled_reply_check_requested.connect(self.scheduled_reply_check)

        self.init_ui()
        self._force_quit = False
        # 启动更新或外部 --quit 时置位：后台任务等不到就继续关，不无限拖延。
        self._shutdown_forced = False
        self._tray_hint_shown = False
        self.tray_icon = None
        self._setup_tray()
        self.apply_theme()
        self.log_message_received.connect(self._append_runtime_log)
        self._gui_log_sink_id = logger.add(
            lambda message: self.log_message_received.emit(str(message).rstrip()),
            level="INFO",
            format="{time:HH:mm:ss} | {level:<8} | {message}",
        )
        self.init_components()
        self.settings_page.set_ai_provider(lambda: self.ai_client)
        self.load_status()
        self._attach_dashboard()

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
        self._memory_worker = None
        QTimer.singleShot(20000, self._maybe_consolidate_memory)
        self._memory_check_timer = QTimer(self)
        self._memory_check_timer.setInterval(6 * 60 * 60 * 1000)
        self._memory_check_timer.timeout.connect(self._maybe_consolidate_memory)
        self._memory_check_timer.start()

        # 运行期间每 6 小时复查一次更新。
        self._update_recheck_timer = QTimer(self)
        self._update_recheck_timer.setInterval(6 * 60 * 60 * 1000)
        self._update_recheck_timer.timeout.connect(lambda: self.check_updates(silent=True))
        self._update_recheck_timer.start()

        # 常驻回复检查：应用打开期间按设置频率检查回复并提醒，不依赖自动运营开关。
        self._unread_reply_count = 0
        self._notified_reply_rpids = set()
        self._reply_poll_timer = QTimer(self)
        self._reply_poll_timer.timeout.connect(self.scheduled_reply_check)
        # 因为 Agent/回复任务在跑而跳过时，1 分钟后再试一次；
        # 否则短任务会把回复拖到下一个 30 分钟周期。
        self._reply_retry_timer = QTimer(self)
        self._reply_retry_timer.setSingleShot(True)
        self._reply_retry_timer.setInterval(60 * 1000)
        self._reply_retry_timer.timeout.connect(self.scheduled_reply_check)
        self._apply_reply_poll_interval()
        self._reply_poll_timer.start()

        # 定期释放空闲的本地语音模型，降低长时间驻留内存。
        self._resource_timer = QTimer(self)
        self._resource_timer.setInterval(5 * 60 * 1000)
        self._resource_timer.timeout.connect(self._release_idle_models)
        self._resource_timer.start()

        # 每天自动整理一次过期日记（长文件压成短条目），历史不会越堆越重。
        self._diary_worker = None
        QTimer.singleShot(90000, self._maybe_compact_diaries)
        self._diary_check_timer = QTimer(self)
        self._diary_check_timer.setInterval(6 * 60 * 60 * 1000)
        self._diary_check_timer.timeout.connect(self._maybe_compact_diaries)
        self._diary_check_timer.start()

    def _maybe_compact_diaries(self):
        """启动后与运行期间各检查一次；每天最多真正跑一次。"""
        from core.diary_maintenance import ran_today

        if self.ai_client is None:
            return
        if not self.config.get('diaries.auto_compact', True):
            return
        if self._diary_worker is not None and self._diary_worker.isRunning():
            return
        if ran_today():
            return
        busy = any(
            getattr(worker, 'isRunning', lambda: False)()
            for worker in (getattr(self, 'worker', None),
                           getattr(self, 'reply_worker', None))
            if worker is not None
        )
        if busy:
            return
        from gui.maintenance_worker import DiaryMaintenanceWorker

        self._diary_worker = DiaryMaintenanceWorker(
            self.ai_client, self.db, self.config, self
        )
        self._diary_worker.done.connect(self._on_diary_maintenance_done)
        self._diary_worker.finished.connect(self._on_diary_maintenance_finished)
        self._diary_worker.start()

    def _on_diary_maintenance_finished(self):
        self._diary_worker = None

    def _on_diary_maintenance_done(self, success: bool, message: str):
        if success:
            self.log(f"📔 {message}")
        else:
            logger.debug(f"日记维护: {message}")

    def _release_idle_models(self):
        """空闲时释放本地 Whisper 模型，降低内存占用。"""
        try:
            from core.audio_transcriber import LocalAudioTranscriber
            try:
                minutes = int(self.config.get(
                    'analysis.local_model_idle_unload_minutes', 10
                ))
            except (TypeError, ValueError):
                minutes = 10
            LocalAudioTranscriber.release_if_idle(max(60, minutes * 60))
        except Exception as exc:  # noqa: BLE001
            logger.debug(f'释放空闲模型失败: {exc}')

    def init_ui(self):
        """初始化UI"""
        self.setWindowTitle("鲸语 · AI 运营助手")
        icon_path = Path(__file__).resolve().parent.parent / 'assets' / 'whale-assistant.ico'
        if icon_path.exists():
            self.setWindowIcon(QIcon(str(icon_path)))
        self.setMinimumSize(1040, 760)

        # 主布局：左侧导航 + 右侧内容（成熟产品常见的桌面布局）
        main_widget = QWidget()
        self.setCentralWidget(main_widget)
        shell = QHBoxLayout(main_widget)
        shell.setSpacing(0)
        shell.setContentsMargins(0, 0, 0, 0)
        shell.addWidget(self._create_sidebar())

        content = QWidget()
        content.setObjectName("contentShell")
        layout = QVBoxLayout(content)
        layout.setSpacing(14)
        layout.setContentsMargins(24, 18, 24, 16)
        layout.addWidget(self._create_header())

        # 标签页（隐藏原生 tab bar，由左侧导航驱动）
        self.tabs = QTabWidget()
        self.tabs.setObjectName("contentTabs")
        self.tabs.setIconSize(QSize(18, 18))
        self.tabs.tabBar().hide()

        # 仪表盘标签（新增 - 作为首页）
        self.dashboard_tab = DashboardTab(
            self.agent,
            self.bili_api, 
            self.config, 
            self.db
        )
        self.tabs.addTab(self.dashboard_tab, load_icon('dashboard'), "仪表盘")

        # 控制台标签
        self.console_tab = self._create_console_tab()
        self.tabs.addTab(self.console_tab, load_icon('console'), "控制台")

        # 评论对话标签
        self.comments_tab = CommentsTab(self.db)
        self.tabs.addTab(self.comments_tab, load_icon('comments'), "评论")

        # 私信标签
        self.messages_tab = MessagesTab()
        self.tabs.addTab(self.messages_tab, load_icon('messages'), "私信")

        # 历史记录标签
        self.history_tab = self._create_history_tab()
        self.tabs.addTab(self.history_tab, load_icon('history'), "历史记录")

        # 设置标签
        self.settings_page = SettingsPage(self.config, self.db)
        self.settings_page.auto_run_btn.clicked.connect(self.toggle_auto_run)
        self.settings_page.schedule_settings_saved.connect(self.refresh_scheduler_settings)
        self.settings_page.ai_settings_saved.connect(self.refresh_ai_settings)
        self.tabs.addTab(self.settings_page, load_icon('settings'), "设置")

        # 连接仪表盘按钮
        self.dashboard_tab.run_now_btn.clicked.connect(self.run_analysis_now)
        self.dashboard_tab.pause_btn.clicked.connect(self.toggle_auto_run)
        # 仪表盘和设置页的 @主人分数阈值双向同步
        self.dashboard_tab.mention_score_changed.connect(
            self.settings_page.sync_mention_score
        )
        self.settings_page.analysis_settings_saved.connect(
            self.dashboard_tab.sync_mention_score
        )

        layout.addWidget(self.tabs, 1)
        shell.addWidget(content, 1)
        self.tabs.currentChanged.connect(self._on_tab_changed)

        # 侧边导航与页面标题同步
        self._on_tab_changed(0)

        # 状态栏
        self.statusBar = QStatusBar()
        self.setStatusBar(self.statusBar)
        self.statusBar.showMessage("就绪")

    def _create_sidebar(self) -> QWidget:
        """左侧导航：品牌、分组页面入口、账号与版本信息。"""
        sidebar = QWidget()
        sidebar.setObjectName("sidebar")
        sidebar.setFixedWidth(216)
        layout = QVBoxLayout(sidebar)
        layout.setContentsMargins(14, 18, 14, 16)
        layout.setSpacing(6)

        brand = QHBoxLayout()
        brand.setSpacing(10)
        logo = QLabel()
        whale_path = Path(__file__).resolve().parent.parent / 'assets' / 'whale-assistant.png'
        if whale_path.exists():
            logo.setPixmap(
                QPixmap(str(whale_path)).scaled(
                    32, 32, Qt.AspectRatioMode.KeepAspectRatio,
                    Qt.TransformationMode.SmoothTransformation,
                )
            )
        else:
            logo.setPixmap(load_icon('dashboard').pixmap(28, 28))
        brand.addWidget(logo)
        brand_text = QVBoxLayout()
        brand_text.setSpacing(0)
        title = QLabel("鲸语")
        title.setObjectName("brandTitle")
        subtitle = QLabel("AI 运营助手")
        subtitle.setObjectName("brandSubtitle")
        brand_text.addWidget(title)
        brand_text.addWidget(subtitle)
        brand.addLayout(brand_text)
        brand.addStretch()
        layout.addLayout(brand)
        layout.addSpacing(14)

        self._nav_group = QButtonGroup(self)
        self._nav_group.setExclusive(True)
        self.nav_buttons = []

        def add_section(text: str):
            label = QLabel(text)
            label.setObjectName("sideSection")
            layout.addWidget(label)

        def add_nav(index: int, icon: str, text: str):
            button = QPushButton(text)
            button.setObjectName("navButton")
            button.setCheckable(True)
            button.setIcon(load_icon(icon))
            button.setIconSize(QSize(18, 18))
            button.setMinimumHeight(38)
            button.clicked.connect(
                lambda _checked=False, page=index: self.tabs.setCurrentIndex(page)
            )
            self._nav_group.addButton(button, index)
            self.nav_buttons.append(button)
            layout.addWidget(button)

        add_section("工作台")
        add_nav(0, 'dashboard', "仪表盘")
        add_nav(1, 'console', "控制台")
        add_section("互动")
        add_nav(2, 'comments', "评论")
        add_nav(3, 'messages', "私信")
        add_section("记录")
        add_nav(4, 'history', "历史记录")
        add_section("系统")
        add_nav(5, 'settings', "设置")

        layout.addStretch()

        self.sidebar_account = QLabel("未登录 B 站")
        self.sidebar_account.setObjectName("sideAccount")
        self.sidebar_account.setWordWrap(True)
        layout.addWidget(self.sidebar_account)

        version_row = QHBoxLayout()
        version = QLabel(f"v{APP_VERSION}")
        version.setObjectName("sideVersion")
        version_row.addWidget(version)
        version_row.addStretch()
        self.sidebar_update_hint = QLabel("")
        self.sidebar_update_hint.setObjectName("sideVersion")
        version_row.addWidget(self.sidebar_update_hint)
        layout.addLayout(version_row)
        return sidebar

    def _create_header(self) -> QWidget:
        """内容区顶部：页面标题、运行统计与主要操作。"""
        header = QWidget()
        header.setObjectName("pageHeader")
        layout = QHBoxLayout(header)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(12)

        titles = QVBoxLayout()
        titles.setSpacing(2)
        self.page_title = QLabel("仪表盘")
        self.page_title.setObjectName("pageTitle")
        self.page_subtitle = QLabel("账号状态、今日数据与最近动作")
        self.page_subtitle.setObjectName("pageSubtitle")
        titles.addWidget(self.page_title)
        titles.addWidget(self.page_subtitle)
        layout.addLayout(titles)
        layout.addStretch()

        # 统计信息只在窗口足够宽时显示，避免窄窗口挤压操作按钮
        self.stats_label = QLabel("今日: 0 条发送")
        self.stats_label.setObjectName("headerMeta")
        self.stats_label.setVisible(False)

        self.login_status_label = QLabel("● 未登录")
        self.login_status_label.setObjectName("statusPill")
        layout.addWidget(self.login_status_label)

        self.login_btn = QPushButton("登录 B 站")
        self.login_btn.setObjectName("ghostButton")
        self.login_btn.setIcon(load_icon('login'))
        self.login_btn.setMinimumHeight(34)
        self.login_btn.clicked.connect(self.show_login_dialog)
        layout.addWidget(self.login_btn)

        self.auto_run_btn = QPushButton("启动自动运营")
        self.auto_run_btn.setObjectName("ghostButton")
        self.auto_run_btn.setIcon(load_icon('play'))
        self.auto_run_btn.setMinimumHeight(36)
        self.auto_run_btn.clicked.connect(self.toggle_auto_run)
        layout.addWidget(self.auto_run_btn)

        self.run_now_btn = QPushButton("立即运行一轮")
        self.run_now_btn.setObjectName("primaryButton")
        self.run_now_btn.setIcon(load_icon('play'))
        self.run_now_btn.setMinimumHeight(36)
        self.run_now_btn.clicked.connect(self.run_analysis_now)
        layout.addWidget(self.run_now_btn)
        return header

    _PAGE_META = {
        '仪表盘': ('仪表盘', '账号状态、今日数据与最近动作'),
        '控制台': ('控制台', '运行日志与手动触发'),
        '历史记录': ('历史记录', '已发送的评论与对应视频'),
        '评论': ('评论', '按楼查看对话与回复提醒'),
        '私信': ('私信', '读取并回复 B 站私信'),
        '设置': ('设置', '账号、模型、人设与运行策略'),
    }

    def _set_login_state(self, logged_in: bool, name: str = ''):
        """同步顶部状态胶囊与侧边栏账号信息。"""
        state = 'ok' if logged_in else 'off'
        self.login_status_label.setText(f"● 已登录 {name}".strip() if logged_in else "● 未登录")
        self.login_status_label.setProperty('state', state)
        self.login_status_label.style().unpolish(self.login_status_label)
        self.login_status_label.style().polish(self.login_status_label)
        self.login_btn.setText("切换账号" if logged_in else "登录 B 站")
        self.login_btn.setIcon(load_icon('login'))
        self.sidebar_account.setText(
            f"B 站 · {name}" if logged_in and name else
            "B 站 · 已登录" if logged_in else "未登录 B 站"
        )
        if hasattr(self, 'dashboard_tab'):
            self.dashboard_tab.update_dashboard()

    def _create_console_tab(self) -> QWidget:
        """创建控制台标签"""
        widget = QWidget()
        layout = QVBoxLayout()
        layout.setSpacing(15)

        # 日志显示
        log_group = QGroupBox("运行日志")
        log_layout = QVBoxLayout()
        toolbar = QHBoxLayout()
        toolbar.addStretch()
        clear_btn = QPushButton("清空日志")
        clear_btn.setObjectName("ghostButton")
        clear_btn.setMinimumHeight(30)
        clear_btn.clicked.connect(lambda: self.log_text.clear())
        toolbar.addWidget(clear_btn)
        log_layout.addLayout(toolbar)

        self.log_text = QTextEdit()
        self.log_text.setReadOnly(True)
        self.log_text.setObjectName("logText")
        self.log_text.setFont(QFont("Consolas", 9))
        # 只保留最近 3000 行，避免日志越积越多导致界面卡顿
        self.log_text.document().setMaximumBlockCount(3000)
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
        refresh_btn = QPushButton("刷新")
        refresh_btn.setIcon(load_icon('reset'))
        refresh_btn.clicked.connect(self.load_history)
        layout.addWidget(refresh_btn)

        # 历史记录表格
        self.history_table = QTableWidget()
        self.history_table.setAlternatingRowColors(True)
        self.history_table.setShowGrid(False)
        self.history_table.setColumnCount(4)
        self.history_table.setHorizontalHeaderLabels([
            "时间", "视频标题", "评论", "链接"
        ])
        self.history_table.cellClicked.connect(self._open_history_video)

        header = self.history_table.horizontalHeader()
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(3, QHeaderView.ResizeMode.ResizeToContents)

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
                self.ai_client = self._create_ai_client(ai_config)
                self.log("✅ AI客户端已初始化")
            else:
                self.log("⚠️ 未配置AI API密钥，请前往设置页面配置")

            # 初始化自由 Agent
            if self.bili_api and self.ai_client:
                self.agent = FreeAgent(
                    self.bili_api,
                    self.ai_client,
                    self.db,
                    self.config
                )
            self._active_ai_signature = self._ai_signature()

            # 初始化调度器
            self.scheduler = TaskScheduler(self.config)
            if self.agent:
                self.scheduler.set_wake_callback(self.scheduled_run)

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
                info = {}
                try:
                    info = loop.run_until_complete(self.bili_api.get_self_info()) or {}
                except Exception:  # noqa: BLE001
                    info = {}
                self._set_login_state(True, str(info.get('name') or ''))
                self.log("✅ B站账号已登录")
            else:
                self._set_login_state(False)
                self.log("请先登录B站账号")
        except Exception as e:
            logger.error(f"检查登录状态失败: {e}")

        # 加载统计信息
        self.update_stats()

        # 检查自动运行状态
        if self.config.get('schedule.auto_run', False):
            self.scheduler.start()
            if self.scheduler.is_running:
                self.auto_run_btn.setText("停止自动运营")
                self.auto_run_btn.setIcon(load_icon('pause'))
                self.settings_page.auto_run_btn.setText("停止自动运营")
                self.settings_page.auto_run_btn.setIcon(load_icon('pause'))
                self.log("自动运营已启动")
            else:
                self.auto_run_btn.setText("启动自动运营")
                self.auto_run_btn.setIcon(load_icon('play'))
                self.settings_page.auto_run_btn.setText("启动自动运营")
                self.settings_page.auto_run_btn.setIcon(load_icon('play'))
                self.log("自动运行配置未能启动，请检查AI配置与唤醒时段")

    def update_stats(self):
        """更新统计信息"""
        stats = self.db.get_statistics()
        self.stats_label.setText(
            f"今日 {stats['today_comments']} 条发送 · "
            f"累计 {stats.get('total_agent_runs', 0)} 轮 Agent · "
            f"{stats['total_comments_sent']} 条记录"
        )

    def show_login_dialog(self):
        """显示登录对话框"""
        dialog = LoginDialog(self.bili_api, self)
        if dialog.exec():
            info = {}
            try:
                import asyncio
                info = asyncio.run(self.bili_api.get_self_info()) or {}
            except Exception:  # noqa: BLE001
                info = {}
            self._set_login_state(True, str(info.get('name') or ''))
            self.log("✅ 登录成功！")
            self.messages_tab.set_bili_api(self.bili_api)
            self.comments_tab.set_bili_api(self.bili_api)

    def run_analysis_now(self):
        """立即运行一轮自由 Agent"""
        if not self.agent:
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
        self.statusBar.showMessage("自由 Agent 正在运行...")
        self.log("开始自由 Agent 一轮...")

        # 创建工作线程
        self.worker = AnalysisWorker(self.agent)
        self.worker.finished.connect(self.on_analysis_finished)
        self.worker.error.connect(self.on_analysis_error)
        self.worker.start()

    def on_analysis_finished(self, result: dict):
        """自由 Agent 完成"""
        QTimer.singleShot(0, self.refresh_ai_settings)
        self.run_now_btn.setEnabled(True)
        if result.get('status') == 'cancelled':
            self.statusBar.showMessage("任务已停止")
            self.log("⏹️ Agent 任务已安全停止")
            return
        if result.get('status') == 'replies_checked':
            self.on_reply_check_finished(result)
            return
        self.statusBar.showMessage("任务完成")

        status = result.get('status', 'unknown')

        if status == 'success':
            self.log("✅ 自由 Agent 本轮结束")
            if result.get('comments_sent'):
                self.log(f"  - 发送评论: {result['comments_sent']}条")
        elif status == 'quota_exhausted':
            self.log("⚠️ 今日评论配额已用完")
        elif status == 'no_videos_found':
            self.log("ℹ️ 未找到符合条件的视频")
        elif status == 'posting_limited':
            self.log("⏸️ B站评论发送上限冷却中，本轮已跳过")

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
        """按间隔检查评论回复；自动回复是否执行由配置决定。"""
        busy = any(
            getattr(worker, 'isRunning', lambda: False)()
            for worker in (getattr(self, 'worker', None),
                           getattr(self, 'reply_worker', None))
            if worker is not None
        )
        if (not self.agent
                or not self.config.get('interaction.comment_monitor', False)
                or not self.bili_api or not self.bili_api.credential
                or busy):
            if busy and getattr(self, '_reply_retry_timer', None) is not None:
                # 1 分钟后再试，别等下一个整周期
                self._reply_retry_timer.start()
            return False
        if QThread.currentThread() != self.thread():
            self.scheduled_reply_check_requested.emit()
            return True
        if getattr(self, '_reply_retry_timer', None) is not None:
            self._reply_retry_timer.stop()
        self.reply_worker = AnalysisWorker(self.agent, operation='replies')
        self.reply_worker.finished.connect(self.on_reply_check_finished)
        self.reply_worker.error.connect(lambda error: self.log(f"❌ 回复检查失败: {error}"))
        self.reply_worker.start()
        return True

    def refresh_scheduler_settings(self):
        """保存调度设置后，让运行中的调度器立即应用新时段和间隔。"""
        self._apply_reply_poll_interval()
        if not self.scheduler or not self.scheduler.is_running:
            return
        self.scheduler.stop()
        self.scheduler.start()
        if self.scheduler.is_running:
            self.log("⚙️ 自动运营设置已更新")

    def _ai_signature(self):
        return tuple(self.config.get(f'ai.{key}', '') for key in ('provider', 'api_key', 'model', 'base_url'))

    def _create_ai_client(self, ai_config):
        """按当前配置创建 AI 客户端（统一超时与重试策略）。"""
        return AIClient(
            provider=ai_config.get('provider', 'openai'),
            api_key=ai_config.get('api_key'),
            model=ai_config.get('model'),
            base_url=ai_config.get('base_url'),
            timeout=self.config.get('ai.timeout_seconds', 60),
            max_retries=self.config.get('ai.max_retries', 2),
            max_output_tokens=self.config.get('ai.max_output_tokens', 8000),
            vision_timeout=self.config.get('ai.vision_timeout_seconds', 20),
        )

    def refresh_ai_settings(self):
        """AI连接参数变化后重建客户端和 Agent，使保存的设置立即生效。"""
        signature = self._ai_signature()
        if signature == getattr(self, '_active_ai_signature', None):
            return
        if ((self.worker and self.worker.isRunning())
                or (self.reply_worker and self.reply_worker.isRunning())):
            self.log("⚙️ AI设置已保存；当前任务结束后会自动应用")
            return
        provider, api_key, model, base_url = signature
        try:
            self.ai_client = self._create_ai_client({
                'provider': provider,
                'api_key': api_key,
                'model': model,
                'base_url': base_url,
            }) if api_key else None
            self.agent = FreeAgent(
                self.bili_api, self.ai_client, self.db, self.config
            ) if self.bili_api and self.ai_client else None
            scheduler_was_running = bool(self.scheduler and self.scheduler.is_running)
            if scheduler_was_running:
                self.scheduler.stop()
            self.scheduler = TaskScheduler(self.config)
            if self.agent:
                self.scheduler.set_wake_callback(self.scheduled_run)
            if scheduler_was_running and self.agent:
                self.scheduler.start()
            self._active_ai_signature = signature
            self.log("✅ AI设置已应用，客户端已重建")
            self._attach_dashboard()
        except Exception as exc:
            logger.exception(f"应用AI设置失败: {exc}")
            self.log(f"❌ 应用AI设置失败: {exc}")

    def _attach_dashboard(self):
        """把当前 Agent 和运行状态接到仪表盘（Agent 重建后需要重新接）。"""
        if not hasattr(self, 'dashboard_tab'):
            return
        try:
            self.dashboard_tab.set_analyzer(self.agent)
            self.dashboard_tab.set_bili_api(self.bili_api)
            self.dashboard_tab.set_status_provider(self._dashboard_status)
            self.dashboard_tab.set_notification_provider(self._dashboard_notifications)
        except Exception as exc:  # noqa: BLE001
            logger.debug(f'连接仪表盘失败: {exc}')

    def _dashboard_status(self) -> dict:
        """仪表盘运行状态"""
        if not self.agent:
            return {
                'running': False,
                'label': '未配置 AI',
                'next_run': '未启动',
                'runtime': '',
            }
        running = bool(self.worker and self.worker.isRunning())
        reply_running = bool(self.reply_worker and self.reply_worker.isRunning())
        if running:
            label = '自由 Agent 运行中'
        elif reply_running:
            label = '检查回复中'
        elif self.scheduler and self.scheduler.is_running:
            label = '自动运营中，等待下次巡视'
        else:
            label = '已暂停'
        next_run = (
            '已启动' if self.scheduler and self.scheduler.is_running else '未启动'
        )
        return {
            'running': running or reply_running,
            'label': label,
            'next_run': next_run,
            'runtime': '',
            'scheduler_running': bool(self.scheduler and self.scheduler.is_running),
        }

    def _dashboard_notifications(self) -> list:
        items = []
        unread = int(getattr(self, '_unread_reply_count', 0) or 0)
        if unread > 0:
            items.append(f'● {unread} 条新回复待处理')
        return items

    def on_reply_check_finished(self, result: dict):
        QTimer.singleShot(0, self.refresh_ai_settings)
        mentions = result.get('mentions') or []
        if mentions:
            self._publish_new_replies(mentions)
        if result.get('replied', 0):
            self.log(f"💬 已自动回复 {result['replied']} 条新评论")

    def toggle_auto_run(self):
        """切换自动运行"""
        if not self.scheduler:
            return

        if self.scheduler.is_running:
            self.scheduler.stop()
            self.auto_run_btn.setText("启动自动运营")
            self.auto_run_btn.setIcon(load_icon('play'))
            self.settings_page.auto_run_btn.setText("启动自动运营")
            self.settings_page.auto_run_btn.setIcon(load_icon('play'))
            self.config.set('schedule.auto_run', False)
            self.log("自动运营已停止")
        else:
            if not self.agent:
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
            self.auto_run_btn.setText("停止自动运营")
            self.auto_run_btn.setIcon(load_icon('pause'))
            self.settings_page.auto_run_btn.setText("停止自动运营")
            self.settings_page.auto_run_btn.setIcon(load_icon('pause'))
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
        """加载评论历史：时间、视频标题、评论、链接。"""
        records = self.db.get_recent_comment_history(limit=300)
        self.history_table.setRowCount(len(records))
        for i, record in enumerate(records):
            when = record.get('created_at')
            self.history_table.setItem(
                i, 0, QTableWidgetItem(when.strftime('%m-%d %H:%M') if when else '')
            )

            title_item = QTableWidgetItem(record.get('title') or '')
            title_item.setToolTip(record.get('title') or '')
            self.history_table.setItem(i, 1, title_item)

            content_item = QTableWidgetItem((record.get('content') or '').replace('\n', ' '))
            content_item.setToolTip(record.get('content') or '')
            self.history_table.setItem(i, 2, content_item)

            url = record.get('url') or ''
            link_item = QTableWidgetItem('打开视频 ↗' if url else '')
            if url:
                link_item.setData(Qt.ItemDataRole.UserRole, url)
                link_item.setForeground(Qt.GlobalColor.blue)
                link_item.setToolTip(url)
            self.history_table.setItem(i, 3, link_item)

    def _open_history_video(self, row: int, column: int):
        """打开历史记录对应的视频页面。"""
        if column != 3:
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
        import html

        text = html.escape(str(message))
        color = '#374151'
        if '| ERROR' in text:
            color = '#b42318'
        elif '| WARNING' in text:
            color = '#8a5d00'
        elif '✅' in text or '成功' in text:
            color = '#1e7b3c'
        self.log_text.append(
            f'<span style="color:{color}; white-space:pre-wrap;">{text}</span>'
        )

    def _on_tab_changed(self, index: int):
        """切换页面时同步标题、侧边栏，并按需刷新数据。"""
        widget = self.tabs.widget(index)
        if hasattr(self, 'page_title') and widget is not None:
            name = self.tabs.tabText(index)
            title, subtitle = self._PAGE_META.get(name, (name, ''))
            self.page_title.setText(title)
            self.page_subtitle.setText(subtitle)
        if hasattr(self, 'nav_buttons') and 0 <= index < len(self.nav_buttons):
            self.nav_buttons[index].setChecked(True)
        if widget is self.comments_tab:
            self._clear_reply_badge()
            self.comments_tab.refresh_if_stale(0)
        elif widget is self.messages_tab:
            self.messages_tab.refresh_if_stale()
        elif widget is self.history_tab:
            self.load_history()
        elif widget is self.settings_page:
            self.settings_page.refresh_growth_list()

    def _apply_reply_poll_interval(self):
        """应用设置中的回复检查间隔。"""
        try:
            minutes = int(self.config.get('schedule.reply_check_interval_minutes', 1))
        except (TypeError, ValueError):
            minutes = 1
        self._reply_poll_timer.setInterval(max(1, minutes) * 60 * 1000)

    def _publish_new_replies(self, mentions):
        """Show newly detected comment replies in the UI."""
        new_replies = []
        for mention in mentions or []:
            rpid = mention.get('rpid')
            if rpid is None or rpid in self._notified_reply_rpids:
                continue
            self._notified_reply_rpids.add(rpid)
            new_replies.append(mention)
        if not new_replies:
            return

        self.comments_tab.show_reply_notice(new_replies)
        latest = new_replies[-1]
        content = (latest.get('content') or '').replace('\n', ' ')[:40]
        self.statusBar.showMessage(
            f"收到 {len(new_replies)} 条新回复：{latest.get('user')}：{content}", 12000
        )
        for mention in new_replies:
            preview = (mention.get('content') or '').replace('\n', ' ')[:80]
            self.log(f"🔔 {mention.get('user')} 回复了你：{preview}")

        if self.tabs.currentWidget() is self.comments_tab:
            self.comments_tab.refresh_if_stale(0)
        else:
            self._unread_reply_count += len(new_replies)
            index = self.tabs.indexOf(self.comments_tab)
            if index >= 0:
                self.tabs.setTabText(index, f"评论 ({self._unread_reply_count})")

    def _clear_reply_badge(self):
        self._unread_reply_count = 0
        index = self.tabs.indexOf(self.comments_tab)
        if index >= 0:
            self.tabs.setTabText(index, "评论")

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
            if hasattr(self, 'sidebar_update_hint'):
                self.sidebar_update_hint.setText(f"可更新 v{version}")
            self.settings_page.check_update_btn.setText(f"更新到 v{version}")
            self.settings_page.check_update_btn.setIcon(load_icon('update'))
            self.statusBar.showMessage(
                f"发现新版本 v{version}：可在 设置 → 关于与更新 中一键更新"
            )
        elif result.get("status") == "latest":
            self.settings_page.check_update_btn.setText("检查更新")
            self.settings_page.check_update_btn.setIcon(load_icon('update'))

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
            result.get("asset_url", ""),
            result.get("asset_digest", ""),
            self,
            asset_name=result.get("asset_name", ""),
            checksums_url=result.get("checksums_url", ""),
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
        self.quit_application(force=True)

    def _maybe_consolidate_memory(self):
        if self.ai_client is None:
            return
        if self._memory_worker is not None and self._memory_worker.isRunning():
            return
        self._memory_worker = MemoryWorker(
            self.ai_client, self.db, self.config, self
        )
        self._memory_worker.done.connect(self._on_memory_done)
        self._memory_worker.finished.connect(self._on_memory_finished)
        self._memory_worker.start()

    def _on_memory_finished(self):
        # 不 deleteLater；QThread 由 Qt 父对象管理，避免 finished 时线程栈未退出就销毁。
        self._memory_worker = None

    def _on_memory_done(self, success: bool, message: str):
        if success and message:
            self.log("🧠 长期记忆已更新")
        elif message:
            logger.debug(f"长期记忆整理: {message}")

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

    def _setup_tray(self):
        """关闭窗口时留在系统托盘，后台继续运行。"""
        if not QSystemTrayIcon.isSystemTrayAvailable():
            return
        icon = self.windowIcon()
        if icon.isNull():
            icon = QApplication.style().standardIcon(
                QApplication.style().StandardPixmap.SP_ComputerIcon
            )
        self.tray_icon = QSystemTrayIcon(icon, self)
        self.tray_icon.setToolTip("鲸语 · AI 运营助手")

        menu = QMenu(self)
        show_action = QAction("显示主窗口", self)
        show_action.triggered.connect(self._show_from_tray)
        quit_action = QAction("退出鲸语", self)
        quit_action.triggered.connect(self._quit_from_tray)
        menu.addAction(show_action)
        menu.addSeparator()
        menu.addAction(quit_action)
        self.tray_icon.setContextMenu(menu)
        self.tray_icon.activated.connect(self._on_tray_activated)
        self.tray_icon.show()

    def _on_tray_activated(self, reason):
        if reason in (
            QSystemTrayIcon.ActivationReason.Trigger,
            QSystemTrayIcon.ActivationReason.DoubleClick,
        ):
            self._show_from_tray()

    def _show_from_tray(self):
        self.showNormal()
        self.raise_()
        self.activateWindow()

    def quit_application(self, force: bool = False):
        """真正退出程序。

        托盘菜单、更新流程、以及外部 ``--quit`` 请求都走这里，保证行为一致：
        标记强制退出、保存设置、停调度、关数据库并释放单实例锁。

        ``force=True`` 用于更新和外部退出请求：后台任务等不到时不再拒绝关闭，
        否则更新脚本会白等到超时，最后还是得强杀。
        """
        self._force_quit = True
        self._shutdown_forced = self._shutdown_forced or force
        self.close()
        QApplication.instance().quit()

    def _quit_from_tray(self):
        self.quit_application()

    def apply_theme(self):
        """应用浅色界面主题。"""
        try:
            app = QApplication.instance()
            if app is not None:
                app.setStyleSheet(MODERN_STYLE)
        except Exception as exc:  # noqa: BLE001
            logger.debug(f'应用主题失败: {exc}')

    def closeEvent(self, event):
        """关闭窗口：默认隐藏到托盘继续运行；托盘菜单“退出”才真正结束。"""
        if (
            not self._force_quit
            and self.tray_icon is not None
            and self.tray_icon.isVisible()
        ):
            self.hide()
            if not self._tray_hint_shown:
                self.tray_icon.showMessage(
                    "鲸语仍在后台运行",
                    "点击托盘图标可重新打开，右键托盘图标可退出。",
                    QSystemTrayIcon.MessageIcon.Information,
                    3000,
                )
                self._tray_hint_shown = True
            event.ignore()
            return
        self.settings_page.flush_pending_save()
        self._update_timer.stop()
        self._update_recheck_timer.stop()
        self._reply_poll_timer.stop()
        if getattr(self, '_resource_timer', None) is not None:
            self._resource_timer.stop()
        if getattr(self, '_memory_check_timer', None) is not None:
            self._memory_check_timer.stop()
        self.comments_tab.shutdown()
        self.messages_tab.shutdown()
        if self._update_worker is not None and self._update_worker.isRunning():
            self._update_worker.wait(3000)
        if self._update_download is not None and self._update_download.isRunning():
            self._update_download.cancel()
            self._update_download.wait(3000)
        if self._memory_worker is not None and self._memory_worker.isRunning():
            self._memory_worker.wait(5000)
        settings_worker = getattr(
            self.settings_page, '_transcription_worker', None
        )
        if settings_worker is not None and settings_worker.isRunning():
            settings_worker.wait(5000)

        leftover = []
        for worker in (
            self._memory_worker,
            self._update_worker,
            self._update_download,
            settings_worker,
        ):
            if worker is not None and worker.isRunning():
                leftover.append(worker)
        for tab in (self.comments_tab, self.messages_tab):
            for attr in ('_worker', '_session_worker', '_message_worker', '_send_worker'):
                worker = getattr(tab, attr, None)
                if worker is not None and worker.isRunning():
                    leftover.append(worker)
        if leftover:
            if not self._shutdown_forced:
                self.log("后台任务仍在运行，请稍后再关闭窗口")
                event.ignore()
                return
            logger.warning(
                f'更新/退出请求不再等待 {len(leftover)} 个后台任务，继续关闭'
            )

        if self.scheduler and self.scheduler.is_running:
            self.scheduler.stop()

        if getattr(self, '_gui_log_sink_id', None) is not None:
            logger.remove(self._gui_log_sink_id)
            self._gui_log_sink_id = None

        workers = [worker for worker in (self.worker, self.reply_worker)
                   if worker and worker.isRunning()]
        if workers:
            if self.agent:
                self.agent.request_stop()
            for worker in workers:
                worker.requestInterruption()
            wait_ms = 30000 if self._shutdown_forced else 10000
            stopped = True
            for worker in workers:
                stopped = worker.wait(wait_ms) and stopped
            if not stopped:
                if not self._shutdown_forced:
                    self.log("后台任务仍在等待网络请求结束，请稍后再次关闭窗口")
                    event.ignore()
                    return
                logger.warning('更新/退出请求不再等待本轮网络请求，继续关闭')

        if getattr(self, 'tray_icon', None) is not None:
            self.tray_icon.hide()
        try:
            self.db.dispose()
        except Exception as exc:  # noqa: BLE001
            logger.debug(f'关闭数据库时出错: {exc}')
        event.accept()
