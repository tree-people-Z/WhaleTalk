"""
仪表盘页面 - 状态概览与快速操作
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QLabel,
    QPushButton, QListWidget, QSpinBox, QProgressBar, QScrollArea
)
from PyQt6.QtCore import QTimer, Qt
from datetime import datetime, timedelta
from loguru import logger

from gui.icons import load_icon


class DashboardTab(QWidget):
    """仪表盘 - 首页概览"""
    
    def __init__(self, analyzer, bili_api, config, db):
        super().__init__()
        self.analyzer = analyzer
        self.bili_api = bili_api
        self.config = config
        self.db = db
        self._status_provider = None
        self._notification_provider = None
        self.init_ui()

    def set_analyzer(self, analyzer):
        """主窗口重建 Agent 后同步过来"""
        self.analyzer = analyzer
        self.update_dashboard()

    def set_status_provider(self, provider):
        """provider 返回 {running, label, next_run, runtime}"""
        self._status_provider = provider

    def set_notification_provider(self, provider):
        """provider 返回通知字符串列表"""
        self._notification_provider = provider
    
    def init_ui(self):
        """初始化UI"""
        # 外层只放滚动区域：窗口变小时滚动，而不是把控件压扁重叠
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setSpacing(14)
        layout.setContentsMargins(18, 18, 18, 18)

        # 1. 顶部状态卡片区
        status_layout = QHBoxLayout()
        status_layout.setSpacing(14)
        
        # 运行状态卡片
        self.status_card = self._create_status_card()
        status_layout.addWidget(self.status_card)
        
        # 今日统计卡片
        self.stats_card = self._create_stats_card()
        status_layout.addWidget(self.stats_card)
        
        layout.addLayout(status_layout)
        
        # 2. 快速操作区
        actions_group = self._create_actions_group()
        layout.addWidget(actions_group)
        
        # 3. 最近动作
        recent_group = self._create_recent_actions_group()
        layout.addWidget(recent_group)
        
        # 4. 待处理通知
        notifications_group = self._create_notifications_group()
        layout.addWidget(notifications_group)
        
        layout.addStretch()

        scroll.setWidget(content)
        outer.addWidget(scroll)
        
        # 定时更新
        self.update_timer = QTimer(self)
        self.update_timer.timeout.connect(self.update_dashboard)
        self.update_timer.start(5000)  # 每5秒更新
        
        # 初始更新
        self.update_dashboard()
    
    def _create_status_card(self):
        """创建运行状态卡片"""
        card = QGroupBox("运行状态")
        card.setMinimumWidth(300)
        card.setMinimumHeight(150)
        layout = QVBoxLayout()
        layout.setSpacing(8)
        
        # 状态标签
        self.status_label = QLabel("⏸️ 已暂停")
        self.status_label.setStyleSheet(
            "font-size: 20px; font-weight: bold; color: #f59e0b;"
        )
        layout.addWidget(self.status_label)
        
        # 运行时长
        self.runtime_label = QLabel("运行时长: --")
        self.runtime_label.setStyleSheet("color: #64748b;")
        layout.addWidget(self.runtime_label)
        
        # 下次运行
        self.next_run_label = QLabel("下次运行: --")
        self.next_run_label.setStyleSheet("color: #64748b;")
        layout.addWidget(self.next_run_label)
        
        card.setLayout(layout)
        return card
    
    def _create_stats_card(self):
        """创建统计卡片"""
        card = QGroupBox("今日活跃")
        card.setMinimumWidth(300)
        card.setMinimumHeight(150)
        layout = QVBoxLayout()
        layout.setSpacing(8)
        
        # 评论数
        self.comments_label = QLabel("💬 评论: 0 / 60")
        layout.addWidget(self.comments_label)
        
        # 进度条
        self.comments_progress = QProgressBar()
        self.comments_progress.setMaximum(100)
        self.comments_progress.setValue(0)
        self.comments_progress.setTextVisible(False)
        self.comments_progress.setMaximumHeight(6)
        layout.addWidget(self.comments_progress)
        
        # 浏览视频数
        self.videos_label = QLabel("📹 浏览视频: 0")
        self.videos_label.setStyleSheet("color: #64748b;")
        layout.addWidget(self.videos_label)
        
        # 运行轮数
        self.runs_label = QLabel("🔄 运行轮数: 0")
        self.runs_label.setStyleSheet("color: #64748b;")
        layout.addWidget(self.runs_label)
        
        card.setLayout(layout)
        return card
    
    def _create_actions_group(self):
        """创建快速操作区"""
        group = QGroupBox("快速操作")
        layout = QVBoxLayout()
        layout.setSpacing(12)
        
        # 第一行：运行控制
        control_layout = QHBoxLayout()
        
        self.run_now_btn = QPushButton("立即运行一轮")
        self.run_now_btn.setIcon(load_icon('play'))
        self.run_now_btn.setMinimumHeight(45)
        self.run_now_btn.setMinimumWidth(150)
        self.run_now_btn.setStyleSheet(
            "QPushButton { background-color: #10b981; color: white; "
            "font-weight: bold; font-size: 13px; }"
        )
        control_layout.addWidget(self.run_now_btn)
        
        self.pause_btn = QPushButton("暂停自动运营")
        self.pause_btn.setIcon(load_icon('pause'))
        self.pause_btn.setMinimumHeight(45)
        self.pause_btn.setMinimumWidth(150)
        self.pause_btn.setStyleSheet(
            "QPushButton { background-color: #f59e0b; color: white; "
            "font-weight: bold; font-size: 13px; }"
        )
        control_layout.addWidget(self.pause_btn)
        
        layout.addLayout(control_layout)
        
        # 第二行：@主人概率调整
        mention_layout = QHBoxLayout()
        
        mention_label = QLabel("@主人概率:")
        mention_label.setMinimumWidth(80)
        mention_layout.addWidget(mention_label)
        
        self.mention_spin = QSpinBox()
        self.mention_spin.setRange(0, 100)
        self.mention_spin.setSuffix("%")
        self.mention_spin.setValue(
            self.config.get('interaction.owner_mention_probability', 35)
        )
        self.mention_spin.setMinimumHeight(35)
        self.mention_spin.setMinimumWidth(80)
        self.mention_spin.valueChanged.connect(self._update_mention_probability)
        mention_layout.addWidget(self.mention_spin)
        
        mention_hint = QLabel("（影响主动评论，不影响回复）")
        mention_hint.setStyleSheet("color: #64748b; font-size: 11px;")
        mention_hint.setWordWrap(True)
        mention_layout.addWidget(mention_hint, 1)  # 可伸缩
        
        layout.addLayout(mention_layout)
        
        group.setLayout(layout)
        return group
    
    def _create_recent_actions_group(self):
        """创建最近动作区"""
        group = QGroupBox("最近动作")
        layout = QVBoxLayout()
        
        self.recent_list = QListWidget()
        self.recent_list.setMinimumHeight(90)
        self.recent_list.setMaximumHeight(140)
        self.recent_list.setStyleSheet(
            "QListWidget { border: 1px solid #e4eaf2; border-radius: 6px; }"
            "QListWidget::item { padding: 8px; }"
        )
        layout.addWidget(self.recent_list)
        
        group.setLayout(layout)
        return group
    
    def _create_notifications_group(self):
        """创建通知区"""
        group = QGroupBox("待处理通知")
        layout = QVBoxLayout()
        
        self.notification_list = QListWidget()
        self.notification_list.setMinimumHeight(70)
        self.notification_list.setMaximumHeight(110)
        self.notification_list.setStyleSheet(
            "QListWidget { border: 1px solid #e4eaf2; border-radius: 6px; }"
            "QListWidget::item { padding: 8px; }"
        )
        layout.addWidget(self.notification_list)
        
        # 无通知提示
        self.no_notification_label = QLabel("✅ 暂无待处理通知")
        self.no_notification_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.no_notification_label.setStyleSheet("color: #64748b; padding: 20px;")
        layout.addWidget(self.no_notification_label)
        
        group.setLayout(layout)
        return group
    
    def update_dashboard(self):
        """更新仪表盘数据"""
        try:
            # 更新运行状态
            self._update_status()
            
            # 更新统计数据
            self._update_stats()
            
            # 更新最近动作
            self._update_recent_actions()
            
            # 更新通知
            self._update_notifications()
            
        except Exception as e:
            logger.debug(f'更新仪表盘失败: {e}')
    
    def _update_status(self):
        """更新运行状态"""
        state = None
        if self._status_provider is not None:
            try:
                state = self._status_provider()
            except Exception as exc:  # noqa: BLE001
                logger.debug(f'读取运行状态失败: {exc}')

        if state:
            running = bool(state.get('running'))
            label = str(state.get('label') or ('运行中' if running else '已暂停'))
            next_run = str(state.get('next_run') or '')
            runtime = str(state.get('runtime') or '')
        else:
            running = bool(getattr(self.analyzer, 'is_running', False))
            label = '运行中' if running else '已暂停'
            next_run = '根据设置间隔'
            runtime = ''

        if running:
            icon = "●"
            color = "#10b981"
        elif "自动运营中" in label:
            icon = "◔"
            color = "#f59e0b"
        else:
            icon = "○"
            color = "#f59e0b"
        self.status_label.setText(f"{icon} {label}")
        self.status_label.setStyleSheet(
            f"font-size: 20px; font-weight: bold; color: {color};"
        )
        scheduler_running = bool(
            state.get('scheduler_running') if state else False
        )
        if running or scheduler_running:
            self.pause_btn.setText("暂停自动运营")
            self.pause_btn.setIcon(load_icon('pause'))
        else:
            self.pause_btn.setText("启动自动运营")
            self.pause_btn.setIcon(load_icon('play'))

        self.runtime_label.setText(f"状态: {label}")
        self.next_run_label.setText(f"自动运营: {next_run}" if next_run else "自动运营: 未启动")
    
    def _update_stats(self):
        """更新统计数据"""
        if not self.db:
            return
        
        try:
            # 今日评论数
            comment_count = self.db.get_today_comment_count(include_replies=True)
            try:
                max_comments = int(self.config.get('limits.max_comments_per_day', 60))
            except (TypeError, ValueError):
                max_comments = 60
            if max_comments <= 0:
                max_comments = 60
            
            self.comments_label.setText(f"💬 评论: {comment_count} / {max_comments}")
            
            # 更新进度条
            progress = int((comment_count / max_comments) * 100) if max_comments > 0 else 0
            self.comments_progress.setValue(min(progress, 100))
            
            # 根据使用率改变颜色
            if progress >= 90:
                color = "#ef4444"  # 红色
            elif progress >= 70:
                color = "#f59e0b"  # 橙色
            else:
                color = "#10b981"  # 绿色
            
            self.comments_progress.setStyleSheet(f"""
                QProgressBar {{
                    border: 1px solid #e4eaf2;
                    border-radius: 3px;
                    background-color: #f1f5f9;
                }}
                QProgressBar::chunk {{
                    background-color: {color};
                    border-radius: 2px;
                }}
            """)
            
            # 今日运行轮数（按日期过滤，接口只接受 limit）
            sessions = self.db.get_recent_agent_sessions(limit=300)
            today = datetime.now().date()
            today_runs = 0
            for session in sessions:
                created = session.get('created_at')
                if isinstance(created, datetime):
                    if created.date() == today:
                        today_runs += 1
                else:
                    try:
                        if str(created)[:10] == today.isoformat():
                            today_runs += 1
                    except (TypeError, ValueError):
                        continue
            self.runs_label.setText(f"🔄 今日轮数: {today_runs}")
            
        except Exception as e:
            logger.debug(f'更新统计数据失败: {e}')
    
    def _update_recent_actions(self):
        """更新最近动作"""
        if not self.db:
            return
        
        try:
            self.recent_list.clear()
            sessions = self.db.get_recent_agent_sessions(limit=5)
            
            for session in sessions:
                created = session.get('created_at')
                if isinstance(created, datetime):
                    time_str = created.strftime('%m-%d %H:%M')
                else:
                    time_str = str(created or '')[:16]
                summary = str(session.get('summary') or '无摘要')
                if len(summary) > 60:
                    summary = summary[:60] + '...'
                self.recent_list.addItem(f"{time_str} | {summary}")
            
            if not sessions:
                self.recent_list.addItem("暂无最近动作")
                
        except Exception as e:
            logger.debug(f'更新最近动作失败: {e}')
    
    def _update_notifications(self):
        """更新通知"""
        items = []
        if self._notification_provider is not None:
            try:
                items = list(self._notification_provider() or [])
            except Exception as exc:  # noqa: BLE001
                logger.debug(f'读取通知失败: {exc}')

        self.notification_list.clear()
        for item in items:
            self.notification_list.addItem(str(item))

        if items:
            self.notification_list.setVisible(True)
            self.no_notification_label.setVisible(False)
        else:
            self.notification_list.setVisible(False)
            self.no_notification_label.setVisible(True)
    
    def _update_mention_probability(self, value):
        """更新@主人概率"""
        try:
            self.config.set('interaction.owner_mention_probability', value)
            self.config.save()
            logger.info(f'已更新@主人概率为 {value}%')
        except Exception as e:
            logger.warning(f'保存@主人概率失败: {e}')
