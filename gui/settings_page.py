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
    QMessageBox, QScrollArea
)
from PyQt6.QtCore import Qt
from PyQt6.QtCore import pyqtSignal, QThread
from PyQt6.QtGui import QDesktopServices
from PyQt6.QtCore import QUrl
from loguru import logger

from utils.config_manager import ConfigManager
from utils.reply_scope import apply_reply_scope, resolve_reply_scope
from utils.subprocess_helpers import hidden_window_kwargs
from utils.updater import APP_VERSION, REPOSITORY_URL


class TranscriptionSetupWorker(QThread):
    """Prepare local transcription: component download (portable) and model download."""
    setup_complete = pyqtSignal(bool, str)
    status = pyqtSignal(str)

    def __init__(self, model_name: str):
        super().__init__()
        self.model_name = model_name

    def run(self):
        try:
            if getattr(sys, 'frozen', False):
                if not self._ensure_portable_component():
                    return
            else:
                if not self._install_source_dependencies():
                    return
            self._download_model()
            self.setup_complete.emit(
                True, f"本地语音模型加载成功（{self.model_name}），可以开始本地转写。"
            )
        except Exception as exc:  # noqa: BLE001
            self.setup_complete.emit(False, f"本地识别准备失败：{exc}")

    def _ensure_portable_component(self) -> bool:
        from utils.transcription_component import (
            download_component, ensure_importable, is_installed,
        )

        if not is_installed():
            self.status.emit("正在下载本地识别组件（约 100 MB）…")

            def report(done: int, total: int):
                if total:
                    self.status.emit(
                        f"正在下载本地识别组件… {done / 1048576:.1f} / {total / 1048576:.1f} MB"
                    )
                else:
                    self.status.emit("正在下载本地识别组件…")

            try:
                download_component(progress=report)
            except Exception as exc:  # noqa: BLE001
                self.setup_complete.emit(False, f"下载本地识别组件失败：{exc}")
                return False
        if not ensure_importable():
            self.setup_complete.emit(False, "本地识别组件不可用，请重试。")
            return False
        return True

    def _install_source_dependencies(self) -> bool:
        project_root = Path(__file__).resolve().parent.parent
        requirements = project_root / 'requirements-transcription.txt'
        self.status.emit("正在安装 faster-whisper…")
        install = subprocess.run(
            [sys.executable, '-m', 'pip', 'install', '-r', str(requirements)],
            cwd=project_root, capture_output=True, text=True,
            **hidden_window_kwargs(),
        )
        if install.returncode:
            self.setup_complete.emit(False, (install.stderr or install.stdout)[-1800:])
            return False
        return True

    def _download_model(self):
        from utils.transcription_component import configure_hf_endpoint, ensure_importable
        from utils.model_downloader import download_model

        try:
            ensure_importable()
        except Exception:  # noqa: BLE001
            pass
        configure_hf_endpoint()
        from core.audio_transcriber import LocalAudioTranscriber

        model_dir = Path('data/models/faster-whisper')
        manual_path = LocalAudioTranscriber.local_model_path(model_dir, self.model_name)
        if not manual_path:
            self.status.emit(
                "正在从国内镜像下载 medium 模型（约 1.5 GB，支持多线程和断点续传）…"
            )

            def report(done: int, total: int):
                if total:
                    percent = done * 100 // total
                    self.status.emit(
                        f"正在下载 medium 模型… {percent}% "
                        f"({done / 1048576:.1f} / {total / 1048576:.1f} MB)"
                    )

            download_model(
                model_dir,
                self.model_name,
                progress=report,
            )
            manual_path = LocalAudioTranscriber.local_model_path(
                model_dir, self.model_name
            )
        if not manual_path:
            raise RuntimeError("模型下载完成但文件校验不完整")

        self.status.emit("模型下载完成，正在加载本地语音模型…")
        from faster_whisper import WhisperModel

        WhisperModel(
            str(manual_path),
            device='cpu',
            compute_type='int8',
            download_root=str(model_dir),
        )
        self.status.emit("✅ 本地语音模型加载成功（medium）")


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
        for spin in (
            self.max_comments_spin,
            self.browse_interval_min_spin,
            self.browse_interval_max_spin,
            self.reply_check_interval_spin,
        ):
            spin.valueChanged.connect(self.auto_save)
            self.disable_wheel_event(spin)

        for check in (
            self.persona_enabled_check,
            self.comment_monitor_check,
            self.auto_reply_check,
            self.like_replied_comment_check,
            self.reply_private_messages_check,
            self.deepseek_offpeak_check,
        ):
            check.stateChanged.connect(self.auto_save)

        self.reply_scope_combo.currentIndexChanged.connect(self.auto_save)
        self.ai_provider_combo.currentIndexChanged.connect(self.auto_save)
        self.deepseek_offpeak_windows_input.editingFinished.connect(self.auto_save)

        self.disable_wheel_event(self.ai_provider_combo)
        self.disable_wheel_event(self.reply_scope_combo)

    def disable_wheel_event(self, widget):
        """禁用控件的鼠标滚轮事件"""
        widget.wheelEvent = lambda event: None
        widget.setFocusPolicy(Qt.FocusPolicy.StrongFocus)

    @staticmethod
    def _section_header(text: str) -> QLabel:
        label = QLabel(text)
        label.setStyleSheet(
            "font-weight: 600; font-size: 13px; color: #1f6feb; margin-top: 10px;"
        )
        return label

    def _toggle_probability_panel(self, expanded: bool):
        self.prob_panel.setVisible(expanded)
        self.prob_toggle_btn.setText(
            "收起概率" if expanded else "行为概率"
        )

    def _toggle_schedule_panel(self, visible: bool):
        self.schedule_group.setVisible(visible)
        self.schedule_toggle_btn.setText(
            "隐藏自动运行与闲时设置" if visible else "显示自动运行与闲时设置"
        )

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

        # 限制设置
        limits_group = self._create_limits_section()
        layout.addWidget(limits_group)

        # 高级功能设置
        advanced_group = self._create_advanced_section()
        layout.addWidget(advanced_group)

        schedule_group = self._create_schedule_section()
        schedule_group.setVisible(False)
        self.schedule_group = schedule_group
        self.schedule_toggle_btn = QPushButton("显示自动运行与闲时设置")
        self.schedule_toggle_btn.setCheckable(True)
        self.schedule_toggle_btn.toggled.connect(self._toggle_schedule_panel)
        layout.addWidget(self.schedule_toggle_btn)
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

        # 增加表单间距和标签对齐，降低界面文字拥挤感。
        for box in content_widget.findChildren(QGroupBox):
            box_layout = box.layout()
            if box_layout is not None:
                box_layout.setSpacing(10)
        for form in content_widget.findChildren(QFormLayout):
            form.setVerticalSpacing(12)
            form.setHorizontalSpacing(18)
            form.setLabelAlignment(
                Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
            )

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
        """创建发送上限区域"""
        group = QGroupBox("发送上限")
        layout = QFormLayout()

        self.max_comments_spin = QSpinBox()
        self.max_comments_spin.setRange(0, 9999)
        layout.addRow("每日最大发送数（评论+回复）:", self.max_comments_spin)

        hint = QLabel("自由 Agent 可以自己决定做什么，但仍受这个上限和 B站冷却保护。")
        hint.setWordWrap(True)
        hint.setStyleSheet("color: #888; font-size: 12px;")
        layout.addRow("", hint)

        group.setLayout(layout)
        return group

    def _create_about_section(self) -> QGroupBox:
        """创建关于与更新区域"""
        group = QGroupBox("关于与更新")
        layout = QVBoxLayout()
        layout.setSpacing(8)

        version_label = QLabel(f"鲸语 · AI 运营助手  v{APP_VERSION}")
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
        """创建回复与私信设置区域。"""
        group = QGroupBox("回复与私信")
        layout = QVBoxLayout()
        layout.setSpacing(10)

        scope_layout = QHBoxLayout()
        scope_layout.addWidget(QLabel("回复范围:"))
        self.reply_scope_combo = QComboBox()
        self.reply_scope_combo.addItem("只回主人", "owner")
        self.reply_scope_combo.addItem("所有人", "all")
        scope_layout.addWidget(self.reply_scope_combo)
        scope_layout.addStretch()
        layout.addLayout(scope_layout)

        self.comment_monitor_check = QCheckBox("启用评论监听（检测回复和@）")
        layout.addWidget(self.comment_monitor_check)
        self.auto_reply_check = QCheckBox("启用自动回复")
        layout.addWidget(self.auto_reply_check)
        self.like_replied_comment_check = QCheckBox("回复后顺手给网友评论点赞")
        layout.addWidget(self.like_replied_comment_check)
        self.reply_private_messages_check = QCheckBox("允许回复私信")
        layout.addWidget(self.reply_private_messages_check)

        group.setLayout(layout)
        return group

    def _create_schedule_section(self) -> QGroupBox:
        """自动运行、回复检查和 DeepSeek 闲时段。"""
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
        browse_layout.addWidget(QLabel("分钟，随机运行一次"))
        layout.addRow("巡视间隔:", browse_layout)

        self.reply_check_interval_spin = QSpinBox()
        self.reply_check_interval_spin.setRange(1, 60)
        self.reply_check_interval_spin.setSuffix(" 分钟")
        layout.addRow("回复检查间隔:", self.reply_check_interval_spin)

        self.deepseek_offpeak_check = QCheckBox("仅在 DeepSeek API 闲时自动运行")
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
        self.owner_uid_input.setText(self.config.get('bilibili.owner_uid', ''))
        self.owner_name_input.setText(self.config.get('bilibili.owner_name', ''))

        self.persona_name_input.setText(self.config.get('persona.name', 'AI娘'))
        persona_file = self.config.get('persona.persona_file', 'data/persona.md')
        try:
            from pathlib import Path
            if Path(persona_file).exists():
                self.persona_desc_text.setPlainText(Path(persona_file).read_text(encoding='utf-8'))
        except OSError:
            pass
        self.persona_enabled_check.setChecked(self.config.get('persona.enabled', True))

        provider = self.config.get('ai.provider', 'openai')
        index = self.ai_provider_combo.findText(provider)
        if index >= 0:
            self.ai_provider_combo.setCurrentIndex(index)
        self.api_key_input.setText(self.config.get('ai.api_key', ''))
        self.model_input.setText(self.config.get('ai.model', ''))
        self.base_url_input.setText(self.config.get('ai.base_url', ''))

        self.max_comments_spin.setValue(self.config.get('limits.max_comments_per_day', 60))
        self.comment_monitor_check.setChecked(self.config.get('interaction.comment_monitor', False))
        scope = resolve_reply_scope(self.config)
        scope_index = self.reply_scope_combo.findData(scope)
        if scope_index >= 0:
            self.reply_scope_combo.setCurrentIndex(scope_index)
        self.auto_reply_check.setChecked(self.config.get('interaction.auto_reply', True))
        self.like_replied_comment_check.setChecked(
            self.config.get('interaction.like_replied_comments', True)
        )
        self.reply_private_messages_check.setChecked(
            self.config.get('interaction.reply_private_messages', True)
        )

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
            self.config.set('bilibili.owner_uid', self.owner_uid_input.text())
            self.config.set('bilibili.owner_name', self.owner_name_input.text())

            self.config.set('persona.name', self.persona_name_input.text())
            self.config.set('persona.enabled', self.persona_enabled_check.isChecked())
            persona_file = self.config.get('persona.persona_file', 'data/persona.md')
            from pathlib import Path
            Path(persona_file).parent.mkdir(parents=True, exist_ok=True)
            Path(persona_file).write_text(self.persona_desc_text.toPlainText(), encoding='utf-8')

            self.config.set('ai.provider', self.ai_provider_combo.currentText())
            self.config.set('ai.api_key', self.api_key_input.text().strip())
            self.config.set('ai.model', self.model_input.text())
            self.config.set('ai.base_url', self.base_url_input.text())

            self.config.set('limits.max_comments_per_day', self.max_comments_spin.value())
            self.config.set('interaction.comment_monitor', self.comment_monitor_check.isChecked())
            apply_reply_scope(
                self.config, self.reply_scope_combo.currentData() or 'all'
            )
            self.config.set('interaction.auto_reply', self.auto_reply_check.isChecked())
            self.config.set(
                'interaction.like_replied_comments',
                self.like_replied_comment_check.isChecked(),
            )
            self.config.set(
                'interaction.reply_private_messages',
                self.reply_private_messages_check.isChecked(),
            )

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

    def on_transcription_mode_changed(self):
        self._update_transcription_controls()
        self.auto_save()

    def _update_transcription_controls(self):
        mode = self.transcription_mode_combo.currentData()
        is_cloud = mode == 'cloud'
        is_local = mode == 'local'
        for widget in (
            self.cloud_stt_base_url_input,
            self.cloud_stt_api_key_input,
            self.cloud_stt_model_input,
        ):
            widget.setEnabled(is_cloud)
        self.transcription_setup_btn.setEnabled(is_local)

    def open_local_model_dir(self):
        """Create and open the folder for manually downloaded model files."""
        target = Path('data/models/faster-whisper/medium')
        target.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(target.resolve())))

    def setup_local_transcription(self):
        """Install faster-whisper and download the chosen model on demand."""
        if getattr(self, '_transcription_worker', None) and self._transcription_worker.isRunning():
            return
        model_name = 'medium'
        self.transcription_setup_btn.setEnabled(False)
        self.transcription_status_label.setText(
            f"正在准备 {model_name} 模型，首次下载可能需要一些时间..."
        )
        self._transcription_worker = TranscriptionSetupWorker(model_name)
        self._transcription_worker.status.connect(self.transcription_status_label.setText)
        self._transcription_worker.setup_complete.connect(self.on_transcription_setup_complete)
        self._transcription_worker.start()

    def _refresh_transcription_state(self):
        """Show whether the local model files are complete on disk."""
        try:
            from core.audio_transcriber import LocalAudioTranscriber
            path = LocalAudioTranscriber.local_model_path(
                Path('data/models/faster-whisper'), 'medium'
            )
        except Exception:  # noqa: BLE001
            path = None
        if path:
            self.transcription_state_label.setText(
                "✅ 本地语音模型已就绪（medium），可以开始本地转写"
            )
            self.transcription_state_label.setStyleSheet(
                "color: #1a7f37; font-weight: 600;"
            )
            self.transcription_setup_btn.setText("重新检测本地模型")
        else:
            self.transcription_state_label.setText(
                "本地语音模型未下载或文件不完整"
            )
            self.transcription_state_label.setStyleSheet(
                "color: #9a6700; font-weight: 600;"
            )
            self.transcription_setup_btn.setText("下载本地识别组件和模型")

    def on_transcription_setup_complete(self, success: bool, message: str):
        self.transcription_setup_btn.setEnabled(True)
        self.transcription_status_label.setText(message)
        if success:
            self.transcription_state_label.setText(
                "✅ 本地语音模型加载成功（medium）"
            )
            self.transcription_state_label.setStyleSheet(
                "color: #1a7f37; font-weight: 600;"
            )
            self.transcription_setup_btn.setText("重新检测本地模型")
            self.config.set('analysis.transcription_mode', 'local')
            self.config.set('analysis.local_transcription_enabled', True)
            self.config.set('analysis.local_transcription_model', 'medium')
            mode_index = self.transcription_mode_combo.findData('local')
            if mode_index >= 0:
                self.transcription_mode_combo.setCurrentIndex(mode_index)
            self._update_transcription_controls()
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
        self.persona_name_input.setPlaceholderText("例如: 鲸鱼娘")
        name_layout.addWidget(self.persona_name_input)
        layout.addLayout(name_layout)

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
