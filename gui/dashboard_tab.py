"""
仪表盘页面 - 状态概览与快速操作
"""

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QGroupBox, QLabel,
    QPushButton, QListWidget, QSpinBox, QProgressBar
)
from PyQt6.QtCore import QTimer, Qt
from datetime import datetime, timedelta
from loguru import logger


class DashboardTab(QWidget):
    """仪表盘 - 首页概览"""
    
    def __init__(self, analyzer, bili_api, config, db):
        super().__init__()
        self.analyzer = analyzer
        self.bili_api = bili_api
        self.config = config
        self.db = db
        self.init_ui()
    
    def init_ui(self):
        """初始化UI"""
        layout = QVBoxLayout(self)
        layout.setSpacing(16)
        layout.setContentsMargins(20, 20, 20, 20)
        
        # 1. 顶部状态卡片区
        status_layout = QHBoxLayout()
        status_layout.setSpacing(16)
        
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
        
        # 定时更新
        self.update_timer = QTimer(self)
        self.update_timer.timeout.connect(self.update_dashboard)
        self.update_timer.start(5000)  # 每5秒更新
        
        # 初始更新
        self.update_dashboard()
    
    def _create_status_card(self):
        """创建运行状态卡片"""
        card = QGroupBox("🔄 运行状态")
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
        card = QGroupBox("📊 今日活跃")
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
        group = QGroupBox("⚡ 快速操作")
        layout = QVBoxLayout()
        layout.setSpacing(12)
        
        # 第一行：运行控制
        control_layout = QHBoxLayout()
        
        self.run_now_btn = QPushButton("▶️ 立即运行一轮")
        self.run_now_btn.setMinimumHeight(45)
        self.run_now_btn.setStyleSheet(
            "background-color: #10b981; color: white; font-weight: bold;"
        )
        control_layout.addWidget(self.run_now_btn)
        
        self.pause_btn = QPushButton("⏸️ 暂停自动运营")
        self.pause_btn.setMinimumHeight(45)
        self.pause_btn.setStyleSheet(
            "background-color: #f59e0b; color: white; font-weight: bold;"
        )
        control_layout.addWidget(self.pause_btn)
        
        layout.addLayout(control_layout)
        
        # 第二行：@主人概率调整
        mention_layout = QHBoxLayout()
        mention_layout.addWidget(QLabel("@主人概率:"))
        
        self.mention_spin = QSpinBox()
        self.mention_spin.setRange(0, 100)
        self.mention_spin.setSuffix("%")
        self.mention_spin.setValue(
            self.config.get('interaction.owner_mention_probability', 35)
        )
        self.mention_spin.setMinimumHeight(35)
        self.mention_spin.valueChanged.connect(self._update_mention_probability)
        mention_layout.addWidget(self.mention_spin)
        
        mention_hint = QLabel("（影响主动评论，不影响回复）")
        mention_hint.setStyleSheet("color: #64748b; font-size: 12px;")
        mention_layout.addWidget(mention_hint)
        
        mention_layout.addStretch()
        layout.addLayout(mention_layout)
        
        group.setLayout(layout)
        return group
    
    def _create_recent_actions_group(self):
        """创建最近动作区"""
        group = QGroupBox("📋 最近动作")
        layout = QVBoxLayout()
        
        self.recent_list = QListWidget()
        self.recent_list.setMaximumHeight(120)
        self.recent_list.setStyleSheet(
            "QListWidget { border: 1px solid #e4eaf2; border-radius: 6px; }"
            "QListWidget::item { padding: 8px; }"
        )
        layout.addWidget(self.recent_list)
        
        group.setLayout(layout)
        return group
    
    def _create_notifications_group(self):
        """创建通知区"""
        group = QGroupBox("🔔 待处理通知")
        layout = QVBoxLayout()
        
        self.notification_list = QListWidget()
        self.notification_list.setMaximumHeight(100)
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
        # 检查是否正在运行
        is_running = False
        if hasattr(self.analyzer, 'is_running'):
            is_running = self.analyzer.is_running
        
        if is_running:
            self.status_label.setText("🟢 运行中")
            self.status_label.setStyleSheet(
                "font-size: 20px; font-weight: bold; color: #10b981;"
            )
            self.pause_btn.setText("⏸️ 暂停自动运营")
        else:
            self.status_label.setText("⏸️ 已暂停")
            self.status_label.setStyleSheet(
                "font-size: 20px; font-weight: bold; color: #f59e0b;"
            )
            self.pause_btn.setText("▶️ 启动自动运营")
        
        # 运行时长（简化版）
        self.runtime_label.setText("运行时长: 查看控制台")
        
        # 下次运行时间
        self.next_run_label.setText("下次运行: 根据设置间隔")
    
    def _update_stats(self):
        """更新统计数据"""
        if not self.db:
            return
        
        try:
            # 今日评论数
            comment_count = self.db.get_today_comment_count(include_replies=True)
            max_comments = self.config.get('limits.max_comments_per_day', 60)
            
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
            
            # 今日运行轮数
            sessions = self.db.get_recent_agent_sessions(days=1)
            self.runs_label.setText(f"🔄 运行轮数: {len(sessions)}")
            
        except Exception as e:
            logger.debug(f'更新统计数据失败: {e}')
    
    def _update_recent_actions(self):
        """更新最近动作"""
        if not self.db:
            return
        
        try:
            self.recent_list.clear()
            
            # 获取最近的会话
            sessions = self.db.get_recent_agent_sessions(limit=5)
            
            for session in sessions:
                time_str = session.get('created_at', '')[:16]  # YYYY-MM-DD HH:MM
                summary = session.get('summary', '无摘要')
                
                # 截断过长的摘要
                if len(summary) > 60:
                    summary = summary[:60] + '...'
                
                item_text = f"{time_str} | {summary}"
                self.recent_list.addItem(item_text)
            
            if not sessions:
                self.recent_list.addItem("暂无最近动作")
                
        except Exception as e:
            logger.debug(f'更新最近动作失败: {e}')
    
    def _update_notifications(self):
        """更新通知"""
        # 简化版本：显示是否有未读回复/私信
        has_notifications = False
        
        self.notification_list.clear()
        
        # TODO: 实际检查未读回复和私信
        # 这里先显示占位符
        
        if has_notifications:
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
