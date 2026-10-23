"""
设置页面
"""

import subprocess
import sys
from pathlib import Path

from PyQt6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QFormLayout,
    QLineEdit, QPushButton, QSpinBox, QCheckBox,
    QGroupBox, QComboBox, QTextEdit, QLabel,
    QMessageBox, QFileDialog, QScrollArea
)
from PyQt6.QtCore import Qt
from PyQt6.QtCore import pyqtSignal, QThread
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtCore import QUrl
from loguru import logger

from utils.config_manager import ConfigManager
from utils.subprocess_helpers import hidden_window_kwargs
from utils.updater import APP_VERSION, REPOSITORY_URL


class TranscriptionSetupWorker(QThread):
    """Install optional faster-whisper and download its selected local model."""
    setup_complete = pyqtSignal(bool, str)

    def __init__(self, model_name: str):
        super().__init__()
        self.model_name = model_name

    def run(self):
        if getattr(sys, 'frozen', False):
            self.setup_complete.emit(
                False,
                "便携版无法自动安装本地识别组件；如需本地转写，请使用源码版（python main.py）安装 faster-whisper。",
            )
            return
        project_root = Path(__file__).resolve().parent.parent
        requirements = project_root / 'requirements-transcription.txt'
        install = subprocess.run(
            [sys.executable, '-m', 'pip', 'install', '-r', str(requirements)],
            cwd=project_root, capture_output=True, text=True,
            **hidden_window_kwargs(),
        )
        if install.returncode:
            self.setup_complete.emit(False, (install.stderr or install.stdout)[-1800:])
            return
        try:
            from faster_whisper import WhisperModel
            model_dir = project_root / 'data' / 'models' / 'faster-whisper'
            WhisperModel(
                self.model_name, device='cpu', compute_type='int8',
                download_root=str(model_dir),
            )
            self.setup_complete.emit(True, f"本地识别依赖与 {self.model_name} 模型已准备完成。")
        except Exception as exc:
            self.setup_complete.emit(False, f"依赖已安装，但模型下载/初始化失败：{exc}")


class SettingsPage(QWidget):
    """设置页面"""
    schedule_settings_saved = pyqtSignal()
    ai_settings_saved = pyqtSignal()
    analysis_settings_saved = pyqtSignal()
    check_update_requested = pyqtSignal()

    def __init__(self, config: ConfigManager):
        super().__init__()
        self.config = config
        self.init_ui()
        self.load_settings()

        # 连接信号，实现实时保存
        self.connect_signals()

    def connect_signals(self):
        """连接信号实现实时保存"""
        # 数字输入框
        self.max_comments_spin.valueChanged.connect(self.auto_save)
        self.cooldown_spin.valueChanged.connect(self.auto_save)
        self.min_score_spin.valueChanged.connect(self.auto_save)
        self.max_results_spin.valueChanged.connect(self.auto_save)
        self.browse_interval_min_spin.valueChanged.connect(self.auto_save)
        self.browse_interval_max_spin.valueChanged.connect(self.auto_save)
        self.reply_check_interval_spin.valueChanged.connect(self.auto_save)
        self.mention_threshold_spin.valueChanged.connect(self.auto_save)

        # 复选框
        self.auto_comment_check.stateChanged.connect(self.auto_save)
        self.mention_owner_check.stateChanged.connect(self.auto_save)
        self.persona_enabled_check.stateChanged.connect(self.auto_save)
        self.comment_monitor_check.stateChanged.connect(self.auto_save)
        self.auto_reply_check.stateChanged.connect(self.auto_save)
        self.reply_interesting_check.stateChanged.connect(self.auto_save)
        self.reply_only_owner_check.stateChanged.connect(self.auto_save)
        self.reply_to_others_check.stateChanged.connect(self.auto_save)
        self.frame_analysis_check.stateChanged.connect(self.auto_save)
        self.diary_check.stateChanged.connect(self.auto_save)
        self.deepseek_offpeak_check.stateChanged.connect(self.auto_save)

        # 下拉框
        self.ai_provider_combo.currentIndexChanged.connect(self.auto_save)
        self.order_combo.currentIndexChanged.connect(self.auto_save)
        # Save the whole range after editing; saving every keystroke would
        # temporarily persist malformed windows and restart the scheduler.
        self.deepseek_offpeak_windows_input.editingFinished.connect(self.auto_save)

        # 禁用所有数字输入框的鼠标滚轮
        self.disable_wheel_event(self.max_comments_spin)
        self.disable_wheel_event(self.cooldown_spin)
        self.disable_wheel_event(self.min_score_spin)
        self.disable_wheel_event(self.max_results_spin)
        self.disable_wheel_event(self.mention_threshold_spin)

        # 禁用所有下拉框的鼠标滚轮
        self.disable_wheel_event(self.ai_provider_combo)
        self.disable_wheel_event(self.order_combo)

    def disable_wheel_event(self, widget):
        """禁用控件的鼠标滚轮事件"""
        widget.wheelEvent = lambda event: None
        widget.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    def auto_save(self):
        """自动保存设置（静默）"""
        try:
            # 保存所有设置，不弹窗提示
            self.save_settings(silent=True)
        except Exception as e:
            logger.error(f"自动保存设置失败: {e}")

    def init_ui(self):
        """初始化UI"""
        # 主布局
        main_layout = QVBoxLayout(self)
        main_layout.setContentsMargins(0, 0, 0, 0)

        # 创建滚动区域
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)

        # 滚动区域内容
        content_widget = QWidget()
        layout = QVBoxLayout(content_widget)
        layout.setSpacing(12)
        layout.setContentsMargins(14, 14, 14, 14)

        # B站设置
        bili_group = self._create_bilibili_section()
        layout.addWidget(bili_group)

        # 人设设置
        persona_group = self._create_persona_section()
        layout.addWidget(persona_group)

        # AI设置
        ai_group = self._create_ai_section()
        layout.addWidget(ai_group)

        # 搜索设置
        search_group = self._create_search_section()
        layout.addWidget(search_group)

        # 限制设置
        limits_group = self._create_limits_section()
        layout.addWidget(limits_group)

        # 高级功能设置
        advanced_group = self._create_advanced_section()
        layout.addWidget(advanced_group)

        schedule_group = self._create_schedule_section()
        layout.addWidget(schedule_group)

        about_group = self._create_about_section()
        layout.addWidget(about_group)

        self.auto_run_btn = QPushButton("⏰ 启动自动运营")
        self.auto_run_btn.setMinimumHeight(40)
        layout.addWidget(self.auto_run_btn)

        # 按钮
        btn_layout = QHBoxLayout()
        btn_layout.addStretch()

        save_btn = QPushButton("💾 保存设置")
        save_btn.clicked.connect(self.save_settings)
        save_btn.setMinimumHeight(40)
        save_btn.setStyleSheet("font-size: 14px; font-weight: 600;")
        btn_layout.addWidget(save_btn)

        reset_btn = QPushButton("🔄 恢复默认")
        reset_btn.clicked.connect(self.reset_to_default)
        reset_btn.setMinimumHeight(40)
        btn_layout.addWidget(reset_btn)

        layout.addLayout(btn_layout)
        layout.addStretch()

        # 设置滚动区域
        scroll.setWidget(content_widget)
        main_layout.addWidget(scroll)

    def _create_bilibili_section(self) -> QGroupBox:
        """创建B站设置区域"""
        group = QGroupBox("B站账号设置")
        layout = QFormLayout()

        self.owner_uid_input = QLineEdit()
        self.owner_uid_input.setPlaceholderText("你的B站UID")
        layout.addRow("主人UID:", self.owner_uid_input)

        self.owner_name_input = QLineEdit()
        self.owner_name_input.setPlaceholderText("你的B站昵称")
        layout.addRow("主人昵称:", self.owner_name_input)

        group.setLayout(layout)
        return group

    def _create_ai_section(self) -> QGroupBox:
        """创建AI设置区域"""
        group = QGroupBox("AI模型设置")
        layout = QFormLayout()

        # AI提供商
        self.ai_provider_combo = QComboBox()
        self.ai_provider_combo.addItems(["openai", "claude", "deepseek", "qwen"])
        layout.addRow("AI提供商:", self.ai_provider_combo)

        # API密钥
        self.api_key_input = QLineEdit()
        self.api_key_input.setPlaceholderText("输入API密钥")
        self.api_key_input.setEchoMode(QLineEdit.EchoMode.Password)
        layout.addRow("API密钥:", self.api_key_input)

        # 模型名称
        self.model_input = QLineEdit()
        self.model_input.setPlaceholderText("例如: gpt-4o-mini")
        layout.addRow("模型名称:", self.model_input)

        # Base URL
        self.base_url_input = QLineEdit()
        self.base_url_input.setPlaceholderText("留空使用默认")
        layout.addRow("Base URL:", self.base_url_input)

        group.setLayout(layout)
        return group

    def _create_search_section(self) -> QGroupBox:
        """创建搜索设置区域"""
        group = QGroupBox("视频搜索设置")
        layout = QFormLayout()

        # 搜索关键词
        self.keywords_input = QTextEdit()
        self.keywords_input.setPlaceholderText("每行一个关键词，例如:\nPython教程\nAI技术\n机器学习")
        self.keywords_input.setMaximumHeight(100)
        layout.addRow("搜索关键词:", self.keywords_input)

        # 每个关键词最大结果数
        self.max_results_spin = QSpinBox()
        self.max_results_spin.setRange(1, 20)
        layout.addRow("每个关键词结果数:", self.max_results_spin)

        # 排序方式
        self.order_combo = QComboBox()
        self.order_combo.addItems([
            "totalrank (综合排序)",
            "pubdate (最新发布)",
            "click (最多播放)",
            "dm (最多弹幕)",
            "stow (最多收藏)"
        ])
        layout.addRow("排序方式:", self.order_combo)

        group.setLayout(layout)
        return group

    def _create_limits_section(self) -> QGroupBox:
        """创建限制设置区域"""
        group = QGroupBox("⚙️ 运营限制设置")
        layout = QFormLayout()

        # 每日最大评论数
        self.max_comments_spin = QSpinBox()
        self.max_comments_spin.setRange(0, 9999)
        layout.addRow("每日最大评论数:", self.max_comments_spin)

        # 同视频冷却天数
        self.cooldown_spin = QSpinBox()
        self.cooldown_spin.setRange(1, 30)
        layout.addRow("同视频冷却天数:", self.cooldown_spin)

        # 最低评分阈值
        self.min_score_spin = QSpinBox()
        self.min_score_spin.setRange(0, 20)
        layout.addRow("评论最低评分:", self.min_score_spin)
        layout.addRow("", QLabel(
            "评分按内容质量与观众热度综合判断：播放量、评论量最多影响5分；不因题材不合口味扣分。"
        ))

        # 自动评论开关
        self.auto_comment_check = QCheckBox("启用自动评论")
        layout.addRow("", self.auto_comment_check)

        self.mention_owner_check = QCheckBox("在评论中 @我（默认关闭）")
        layout.addRow("", self.mention_owner_check)

        self.mention_threshold_spin = QSpinBox()
        self.mention_threshold_spin.setRange(0, 20)
        layout.addRow("评论 @我 的最低评分:", self.mention_threshold_spin)
        layout.addRow("", QLabel(
            "评分达到该值时在评论中 @主人；调低可提高 @ 的概率，调高可减少打扰。"
        ))

        group.setLayout(layout)
        return group

    def _create_about_section(self) -> QGroupBox:
        """创建关于与更新区域"""
        group = QGroupBox("关于与更新")
        layout = QVBoxLayout()
        layout.setSpacing(8)

        version_label = QLabel(f"鲸语 · B站智能运营助手  v{APP_VERSION}")
        version_label.setStyleSheet("font-weight: 600;")
        layout.addWidget(version_label)

        hint = QLabel("从 GitHub Releases 检查新版本；便携版下载完成后会自动替换文件并重启。")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #888; font-size: 12px;")
        layout.addWidget(hint)

        button_layout = QHBoxLayout()
        self.check_update_btn = QPushButton("🔃 检查更新")
        self.check_update_btn.setMinimumHeight(36)
        self.check_update_btn.clicked.connect(self.check_update_requested.emit)
        button_layout.addWidget(self.check_update_btn)

        repo_button = QPushButton("🌐 GitHub 仓库")
        repo_button.setMinimumHeight(36)
        repo_button.clicked.connect(lambda: QDesktopServices.openUrl(QUrl(REPOSITORY_URL)))
        button_layout.addWidget(repo_button)
        button_layout.addStretch()
        layout.addLayout(button_layout)

        group.setLayout(layout)
        return group

    def _create_advanced_section(self) -> QGroupBox:
        """创建高级功能设置区域"""
        group = QGroupBox("🚀 高级功能")
        layout = QVBoxLayout()
        layout.setSpacing(10)

        # 评论监听
        self.comment_monitor_check = QCheckBox("启用评论监听（检测回复和@）")
        layout.addWidget(self.comment_monitor_check)

        # 自动回复
        self.auto_reply_check = QCheckBox("启用自动回复")
        layout.addWidget(self.auto_reply_check)

        # 回复有趣评论
        self.reply_interesting_check = QCheckBox("回复别人的有趣评论")
        layout.addWidget(self.reply_interesting_check)

        # 回复范围
        reply_layout = QHBoxLayout()
        reply_layout.addWidget(QLabel("  回复范围:"))
        self.reply_only_owner_check = QCheckBox("仅处理主人发来的@提醒（不影响对我评论的回复）")
        reply_layout.addWidget(self.reply_only_owner_check)
        self.reply_to_others_check = QCheckBox("回复其他人")
        reply_layout.addWidget(self.reply_to_others_check)
        reply_layout.addStretch()
        layout.addLayout(reply_layout)

        # 画面分析
        self.frame_analysis_check = QCheckBox("每条视频分析画面（需要ffmpeg和支持视觉的模型）")
        layout.addWidget(self.frame_analysis_check)

        transcription_layout = QHBoxLayout()
        transcription_layout.addWidget(QLabel("本地语音识别模型:"))
        self.transcription_model_combo = QComboBox()
        self.transcription_model_combo.addItems(["base", "small", "medium"])
        transcription_layout.addWidget(self.transcription_model_combo)
        self.transcription_setup_btn = QPushButton("下载本地识别组件和模型")
        self.transcription_setup_btn.clicked.connect(self.setup_local_transcription)
        transcription_layout.addWidget(self.transcription_setup_btn)
        layout.addLayout(transcription_layout)
        self.transcription_status_label = QLabel("可选功能：点击后安装 faster-whisper 并下载所选模型；音频仅在本地转写。")
        self.transcription_status_label.setWordWrap(True)
        layout.addWidget(self.transcription_status_label)

        # 双日记系统
        self.diary_check = QCheckBox("启用双日记系统（记忆）")
        layout.addWidget(self.diary_check)

        group.setLayout(layout)
        return group

    def _create_schedule_section(self) -> QGroupBox:
        """自动巡视、回复检查和 DeepSeek 闲时段。"""
        group = QGroupBox("⏱️ 自动运行与 DeepSeek 闲时")
        layout = QFormLayout()

        self.browse_interval_min_spin = QSpinBox()
        self.browse_interval_min_spin.setRange(5, 1440)
        self.browse_interval_max_spin = QSpinBox()
        self.browse_interval_max_spin.setRange(5, 1440)
        browse_layout = QHBoxLayout()
        browse_layout.addWidget(self.browse_interval_min_spin)
        browse_layout.addWidget(QLabel("至"))
        browse_layout.addWidget(self.browse_interval_max_spin)
        browse_layout.addWidget(QLabel("分钟，随机巡视一次"))
        layout.addRow("巡视间隔:", browse_layout)

        self.reply_check_interval_spin = QSpinBox()
        self.reply_check_interval_spin.setRange(1, 60)
        self.reply_check_interval_spin.setSuffix(" 分钟")
        layout.addRow("回复检查间隔:", self.reply_check_interval_spin)

        self.deepseek_offpeak_check = QCheckBox("仅在 DeepSeek API 闲时自动巡视视频")
        layout.addRow("", self.deepseek_offpeak_check)
        self.deepseek_offpeak_windows_input = QLineEdit()
        self.deepseek_offpeak_windows_input.setPlaceholderText(
            "00:00-09:00,12:00-14:00,18:00-24:00"
        )
        preset_button = QPushButton("恢复 DeepSeek 官方闲时")
        preset_button.clicked.connect(self.set_deepseek_offpeak_preset)
        offpeak_layout = QHBoxLayout()
        offpeak_layout.addWidget(self.deepseek_offpeak_windows_input, 1)
        offpeak_layout.addWidget(preset_button)
        layout.addRow("工作日闲时段:", offpeak_layout)
        layout.addRow("", QLabel(
            "回复检查不受闲时限制；默认按北京时间工作日 09-12、14-18 高峰设置，周末全天按闲时处理。法定节假日请按实际情况调整时段。"
        ))
        group.setLayout(layout)
        return group

    def set_deepseek_offpeak_preset(self):
        self.deepseek_offpeak_check.setChecked(True)
        self.deepseek_offpeak_windows_input.setText(
            '00:00-09:00,12:00-14:00,18:00-24:00'
        )

    def load_settings(self):
        """加载设置"""
        # B站设置
        self.owner_uid_input.setText(self.config.get('bilibili.owner_uid', ''))
        self.owner_name_input.setText(self.config.get('bilibili.owner_name', ''))

        # 人设设置
        self.persona_name_input.setText(self.config.get('persona.name', 'AI娘'))
        self.persona_self_ref_input.setText(self.config.get('persona.self_reference', '我'))
        self.persona_user_ref_input.setText(self.config.get('persona.user_reference', '主人'))

        # 加载人设描述
        persona_file = self.config.get('persona.persona_file', 'data/persona.md')
        try:
            from pathlib import Path
            if Path(persona_file).exists():
                with open(persona_file, 'r', encoding='utf-8') as f:
                    self.persona_desc_text.setPlainText(f.read())
        except:
            pass

        self.persona_enabled_check.setChecked(self.config.get('persona.enabled', True))

        # AI设置
        provider = self.config.get('ai.provider', 'openai')
        index = self.ai_provider_combo.findText(provider)
        if index >= 0:
            self.ai_provider_combo.setCurrentIndex(index)

        self.api_key_input.setText(self.config.get('ai.api_key', ''))
        self.model_input.setText(self.config.get('ai.model', ''))
        self.base_url_input.setText(self.config.get('ai.base_url', ''))

        # 搜索设置
        keywords = self.config.get('search.keywords', [])
        self.keywords_input.setPlainText('\n'.join(keywords))
        self.max_results_spin.setValue(self.config.get('search.max_results_per_keyword', 5))

        order = self.config.get('search.order', 'totalrank')
        order_map = {
            'totalrank': 0,
            'pubdate': 1,
            'click': 2,
            'dm': 3,
            'stow': 4
        }
        self.order_combo.setCurrentIndex(order_map.get(order, 0))

        # 限制设置
        self.max_comments_spin.setValue(self.config.get('limits.max_comments_per_day', 999))
        self.cooldown_spin.setValue(self.config.get('limits.same_video_cooldown_days', 7))
        self.min_score_spin.setValue(self.config.get('limits.min_score_to_comment', 13))
        self.mention_threshold_spin.setValue(
            self.config.get('limits.min_score_to_mention_owner', 13)
        )
        self.auto_comment_check.setChecked(self.config.get('interaction.auto_comment', False))
        self.mention_owner_check.setChecked(
            self.config.get('interaction.mention_owner_on_interesting', False)
        )

        # 高级功能设置
        self.comment_monitor_check.setChecked(self.config.get('interaction.comment_monitor', False))
        self.auto_reply_check.setChecked(self.config.get('interaction.auto_reply', True))
        self.reply_interesting_check.setChecked(self.config.get('interaction.reply_interesting_comments', False))
        self.reply_only_owner_check.setChecked(self.config.get('interaction.reply_only_owner', True))
        self.reply_to_others_check.setChecked(self.config.get('interaction.reply_to_others', False))
        self.frame_analysis_check.setChecked(self.config.get('analysis.enable_frame_analysis', True))
        model = self.config.get('analysis.local_transcription_model', 'small')
        model_index = self.transcription_model_combo.findText(model)
        if model_index >= 0:
            self.transcription_model_combo.setCurrentIndex(model_index)
        self.diary_check.setChecked(self.config.get('diary.enabled', True))

        # 自动运行
        self.browse_interval_min_spin.setValue(
            self.config.get('schedule.browse_interval_min_minutes', 60)
        )
        self.browse_interval_max_spin.setValue(
            self.config.get('schedule.browse_interval_max_minutes', 120)
        )
        self.reply_check_interval_spin.setValue(
            self.config.get('schedule.reply_check_interval_minutes', 1)
        )
        self.deepseek_offpeak_check.setChecked(
            self.config.get('schedule.deepseek_offpeak_only', True)
        )
        self.deepseek_offpeak_windows_input.setText(
            self.config.get(
                'schedule.deepseek_offpeak_windows',
                '00:00-09:00,12:00-14:00,18:00-24:00'
            )
        )

    def save_settings(self, silent=False):
        """保存设置"""
        try:
            # B站设置
            self.config.set('bilibili.owner_uid', self.owner_uid_input.text())
            self.config.set('bilibili.owner_name', self.owner_name_input.text())

            # 人设设置
            self.config.set('persona.name', self.persona_name_input.text())
            self.config.set('persona.self_reference', self.persona_self_ref_input.text())
            self.config.set('persona.user_reference', self.persona_user_ref_input.text())
            self.config.set('persona.enabled', self.persona_enabled_check.isChecked())

            # 保存人设描述到文件
            persona_file = self.config.get('persona.persona_file', 'data/persona.md')
            from pathlib import Path
            Path(persona_file).parent.mkdir(parents=True, exist_ok=True)
            with open(persona_file, 'w', encoding='utf-8') as f:
                f.write(self.persona_desc_text.toPlainText())

            # AI设置
            self.config.set('ai.provider', self.ai_provider_combo.currentText())
            self.config.set('ai.api_key', self.api_key_input.text().strip())
            self.config.set('ai.model', self.model_input.text())
            self.config.set('ai.base_url', self.base_url_input.text())

            # 搜索设置
            keywords_text = self.keywords_input.toPlainText()
            keywords = [k.strip() for k in keywords_text.split('\n') if k.strip()]
            self.config.set('search.keywords', keywords)
            self.config.set('search.max_results_per_keyword', self.max_results_spin.value())

            order_map = ['totalrank', 'pubdate', 'click', 'dm', 'stow']
            order = order_map[self.order_combo.currentIndex()]
            self.config.set('search.order', order)

            # 限制设置
            self.config.set('limits.max_comments_per_day', self.max_comments_spin.value())
            self.config.set('limits.same_video_cooldown_days', self.cooldown_spin.value())
            self.config.set('limits.min_score_to_comment', self.min_score_spin.value())
            self.config.set(
                'limits.min_score_to_mention_owner', self.mention_threshold_spin.value()
            )
            self.config.set('interaction.auto_comment', self.auto_comment_check.isChecked())
            self.config.set(
                'interaction.mention_owner_on_interesting', self.mention_owner_check.isChecked()
            )

            # 高级功能设置
            self.config.set('interaction.comment_monitor', self.comment_monitor_check.isChecked())
            self.config.set('interaction.auto_reply', self.auto_reply_check.isChecked())
            self.config.set('interaction.reply_interesting_comments', self.reply_interesting_check.isChecked())
            self.config.set('interaction.reply_only_owner', self.reply_only_owner_check.isChecked())
            self.config.set('interaction.reply_to_others', self.reply_to_others_check.isChecked())
            self.config.set('analysis.enable_frame_analysis', self.frame_analysis_check.isChecked())
            self.config.set('analysis.local_transcription_model', self.transcription_model_combo.currentText())
            self.config.set('diary.enabled', self.diary_check.isChecked())
            self.analysis_settings_saved.emit()

            # 自动巡视与 DeepSeek 闲时调度
            interval_min = self.browse_interval_min_spin.value()
            interval_max = self.browse_interval_max_spin.value()
            self.config.set('schedule.browse_interval_min_minutes', min(interval_min, interval_max))
            self.config.set('schedule.browse_interval_max_minutes', max(interval_min, interval_max))
            self.config.set('schedule.reply_check_interval_minutes', self.reply_check_interval_spin.value())
            self.config.set('schedule.deepseek_offpeak_only', self.deepseek_offpeak_check.isChecked())
            self.config.set(
                'schedule.deepseek_offpeak_windows',
                self.deepseek_offpeak_windows_input.text().strip()
            )
            self.schedule_settings_saved.emit()
            self.ai_settings_saved.emit()

            if not silent:
                QMessageBox.information(self, "成功", "设置已保存并立即生效！")
            logger.info("设置已保存")

        except Exception as e:
            QMessageBox.critical(self, "错误", f"保存设置失败:\n{e}")
            logger.error(f"保存设置失败: {e}")

    def setup_local_transcription(self):
        """Install faster-whisper and download the chosen model on demand."""
        if getattr(self, '_transcription_worker', None) and self._transcription_worker.isRunning():
            return
        model_name = self.transcription_model_combo.currentText()
        self.transcription_setup_btn.setEnabled(False)
        self.transcription_status_label.setText(
            f"正在准备 {model_name} 模型，首次下载可能需要一些时间..."
        )
        self._transcription_worker = TranscriptionSetupWorker(model_name)
        self._transcription_worker.setup_complete.connect(self.on_transcription_setup_complete)
        self._transcription_worker.start()

    def on_transcription_setup_complete(self, success: bool, message: str):
        self.transcription_setup_btn.setEnabled(True)
        self.transcription_status_label.setText(message)
        if success:
            self.config.set('analysis.local_transcription_enabled', True)
            self.config.set('analysis.local_transcription_model', self.transcription_model_combo.currentText())
            self.analysis_settings_saved.emit()
            QMessageBox.information(self, "本地识别已就绪", message)
        else:
            QMessageBox.warning(self, "本地识别准备失败", message)

    def reset_to_default(self):
        """恢复默认设置"""
        reply = QMessageBox.question(
            self,
            "确认",
            "确定要恢复默认设置吗？\n当前设置将被覆盖。",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            self.config.create_default_config()
            self.load_settings()
            QMessageBox.information(self, "完成", "已恢复默认设置")
    def _create_persona_section(self) -> QGroupBox:
        """创建人设设置区域"""
        group = QGroupBox("🎭 人设设置")
        layout = QVBoxLayout()
        layout.setSpacing(10)

        # 人设名称
        name_layout = QHBoxLayout()
        name_layout.addWidget(QLabel("角色名称:"))
        self.persona_name_input = QLineEdit()
        self.persona_name_input.setPlaceholderText("例如: AI娘")
        name_layout.addWidget(self.persona_name_input)
        layout.addLayout(name_layout)

        # 自称
        self_ref_layout = QHBoxLayout()
        self_ref_layout.addWidget(QLabel("自称:"))
        self.persona_self_ref_input = QLineEdit()
        self.persona_self_ref_input.setPlaceholderText("例如: 我")
        self_ref_layout.addWidget(self.persona_self_ref_input)
        layout.addLayout(self_ref_layout)

        # 对用户的称呼
        user_ref_layout = QHBoxLayout()
        user_ref_layout.addWidget(QLabel("对用户称呼:"))
        self.persona_user_ref_input = QLineEdit()
        self.persona_user_ref_input.setPlaceholderText("例如: 主人")
        user_ref_layout.addWidget(self.persona_user_ref_input)
        layout.addLayout(user_ref_layout)

        # 人设描述
        layout.addWidget(QLabel("人设描述:"))
        self.persona_desc_text = QTextEdit()
        self.persona_desc_text.setPlaceholderText(
            "详细描述角色性格、说话风格、特点等...\n\n"
            "例如：\n"
            "- 性格：傲娇、活泼\n"
            "- 口头禅：哼！\n"
            "- 特点：喜欢吃饭\n"
            "- 说话风格：带点任性但很关心主人"
        )
        self.persona_desc_text.setMinimumHeight(150)
        layout.addWidget(self.persona_desc_text)

        # 启用开关
        self.persona_enabled_check = QCheckBox("启用自定义人设")
        layout.addWidget(self.persona_enabled_check)

        group.setLayout(layout)
        return group
