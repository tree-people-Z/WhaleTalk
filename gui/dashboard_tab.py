"""仪表盘：今日数据、最近动作、账号与风控。"""

from datetime import datetime

from PyQt6.QtCore import Qt, QTimer, pyqtSignal
from PyQt6.QtGui import QColor, QPainter, QPainterPath, QPen
from PyQt6.QtWidgets import (
    QFrame, QGroupBox, QHBoxLayout, QLabel, QListWidget, QProgressBar,
    QPushButton, QScrollArea, QSpinBox, QVBoxLayout, QWidget,
)
from loguru import logger

from core.self_evolution import last_learned_at
from gui.icons import load_icon


class Sparkline(QWidget):
    """极简趋势线：只表达走向，不画坐标轴。"""

    def __init__(self, color: str = '#287C78', parent=None):
        super().__init__(parent)
        self._values = []
        self._color = QColor(color)
        self.setFixedHeight(34)
        self.setMinimumWidth(80)

    def set_values(self, values, color: str = ''):
        self._values = [float(value or 0) for value in (values or [])]
        if color:
            self._color = QColor(color)
        self.update()

    def paintEvent(self, event):  # noqa: N802 - Qt API
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing, True)
        values = self._values
        if len(values) < 2:
            painter.end()
            return
        width = self.width() - 2
        height = self.height() - 6
        top = 3
        maximum = max(values) or 1.0
        minimum = min(values)
        span = max(1.0, maximum - minimum)
        step = width / (len(values) - 1)
        points = [
            (
                1 + index * step,
                top + height - (value - minimum) / span * height,
            )
            for index, value in enumerate(values)
        ]

        area = QPainterPath()
        area.moveTo(points[0][0], top + height)
        for x, y in points:
            area.lineTo(x, y)
        area.lineTo(points[-1][0], top + height)
        area.closeSubpath()
        fill = QColor(self._color)
        fill.setAlpha(28)
        painter.fillPath(area, fill)

        pen = QPen(self._color, 1.8)
        pen.setCapStyle(Qt.PenCapStyle.RoundCap)
        pen.setJoinStyle(Qt.PenJoinStyle.RoundJoin)
        painter.setPen(pen)
        path = QPainterPath()
        path.moveTo(*points[0])
        for point in points[1:]:
            path.lineTo(*point)
        painter.drawPath(path)
        painter.end()


class DashboardTab(QWidget):
    """首页概览：KPI、最近动作、账号与风控。"""

    mention_score_changed = pyqtSignal(int)

    def __init__(self, analyzer, bili_api, config, db):
        super().__init__()
        self.analyzer = analyzer
        self.bili_api = bili_api
        self.config = config
        self.db = db
        self._status_provider = None
        self._notification_provider = None
        self._kpis = {}
        self._sparklines = {}
        self.init_ui()

    def set_analyzer(self, analyzer):
        self.analyzer = analyzer
        self.update_dashboard()

    def set_bili_api(self, bili_api):
        self.bili_api = bili_api
        self.update_dashboard()

    def set_status_provider(self, provider):
        self._status_provider = provider

    def set_notification_provider(self, provider):
        self._notification_provider = provider

    # ------------------------------------------------------------------ UI
    def init_ui(self):
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.Shape.NoFrame)
        scroll.setHorizontalScrollBarPolicy(
            Qt.ScrollBarPolicy.ScrollBarAlwaysOff
        )

        content = QWidget()
        layout = QVBoxLayout(content)
        layout.setSpacing(16)
        layout.setContentsMargins(20, 18, 20, 20)

        layout.addLayout(self._create_kpi_row())

        middle = QHBoxLayout()
        middle.setSpacing(16)
        middle.addWidget(self._create_recent_actions_group(), 1)
        middle.addWidget(self._create_account_panel())
        layout.addLayout(middle, 1)

        layout.addWidget(self._create_notifications_group())
        layout.addStretch()

        scroll.setWidget(content)
        outer.addWidget(scroll)

        self.update_timer = QTimer(self)
        self.update_timer.timeout.connect(self.update_dashboard)
        self.update_timer.start(15000)
        self.update_dashboard()

    def _create_kpi_row(self) -> QHBoxLayout:
        row = QHBoxLayout()
        row.setSpacing(14)
        for key, title, color in (
            ('sent', '今日发送', '#287C78'),
            ('replies', '今日回复', '#3B82F6'),
            ('runs', 'Agent 轮次', '#7C5CFF'),
            ('pending', '待处理回复', '#D29922'),
        ):
            card = QFrame()
            card.setObjectName('kpiCard')
            card.setMinimumHeight(118)
            box = QVBoxLayout(card)
            box.setContentsMargins(16, 14, 16, 12)
            box.setSpacing(4)

            head = QHBoxLayout()
            head.setSpacing(8)
            label = QLabel(title)
            label.setObjectName('kpiLabel')
            head.addWidget(label)
            head.addStretch()
            hint = QLabel('')
            hint.setObjectName('kpiHint')
            head.addWidget(hint)
            box.addLayout(head)

            value = QLabel('0')
            value.setObjectName('kpiValue')
            box.addWidget(value)

            spark = Sparkline(color)
            box.addWidget(spark)
            box.addStretch()

            self._kpis[key] = {'value': value, 'hint': hint}
            self._sparklines[key] = spark
            row.addWidget(card, 1)
        return row

    def _create_recent_actions_group(self) -> QGroupBox:
        group = QGroupBox("最近动作")
        layout = QVBoxLayout()
        layout.setSpacing(10)

        head = QHBoxLayout()
        self.recent_subtitle = QLabel("最近 2 小时 · 0 次工具调用")
        self.recent_subtitle.setObjectName('cardSubtitle')
        head.addWidget(self.recent_subtitle)
        head.addStretch()
        layout.addLayout(head)

        self.recent_list = QListWidget()
        self.recent_list.setObjectName('flatList')
        self.recent_list.setMinimumHeight(280)
        layout.addWidget(self.recent_list)

        group.setLayout(layout)
        return group

    def _create_account_panel(self) -> QFrame:
        panel = QFrame()
        panel.setObjectName('sidePanel')
        panel.setFixedWidth(286)
        layout = QVBoxLayout(panel)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)

        title = QLabel("账号与风控")
        title.setObjectName('panelTitle')
        layout.addWidget(title)

        self.login_state_label = QLabel("未登录 B 站")
        self.login_state_label.setObjectName('statusPill')
        self.login_state_label.setProperty('state', 'off')
        layout.addWidget(self.login_state_label)

        self.account_label = QLabel("UID：--")
        self.account_label.setObjectName('cardSubtitle')
        layout.addWidget(self.account_label)

        layout.addSpacing(6)
        quota_head = QHBoxLayout()
        quota_head.addWidget(self._muted_label("今日配额"))
        quota_head.addStretch()
        self.quota_label = self._muted_label("0 / 60")
        quota_head.addWidget(self.quota_label)
        layout.addLayout(quota_head)

        self.quota_bar = QProgressBar()
        self.quota_bar.setObjectName('quotaBar')
        self.quota_bar.setRange(0, 100)
        self.quota_bar.setTextVisible(False)
        self.quota_bar.setFixedHeight(8)
        layout.addWidget(self.quota_bar)

        self.risk_label = self._muted_label("风控：正常")
        layout.addWidget(self.risk_label)
        self.next_run_label = self._muted_label("自动运营：未启动")
        layout.addWidget(self.next_run_label)
        self.growth_label = self._muted_label("成长档案：暂无")
        layout.addWidget(self.growth_label)

        layout.addSpacing(8)
        divider = QFrame()
        divider.setObjectName('divider')
        divider.setFixedHeight(1)
        layout.addWidget(divider)
        layout.addSpacing(6)

        self.run_now_btn = QPushButton("立即运行一轮")
        self.run_now_btn.setObjectName('primaryButton')
        self.run_now_btn.setIcon(load_icon('play'))
        self.run_now_btn.setMinimumHeight(38)
        layout.addWidget(self.run_now_btn)

        self.pause_btn = QPushButton("启动自动运营")
        self.pause_btn.setObjectName('ghostButton')
        self.pause_btn.setIcon(load_icon('play'))
        self.pause_btn.setMinimumHeight(38)
        layout.addWidget(self.pause_btn)

        mention_row = QHBoxLayout()
        mention_row.addWidget(self._muted_label("@主人阈值"))
        self.mention_spin = QSpinBox()
        self.mention_spin.setRange(0, 20)
        self.mention_spin.setSuffix(" 分")
        try:
            threshold = int(
                self.config.get('limits.min_score_to_mention_owner', 13)
            )
        except (TypeError, ValueError):
            threshold = 13
        self.mention_spin.setValue(max(0, min(20, threshold)))
        self.mention_spin.valueChanged.connect(self._update_mention_score)
        mention_row.addWidget(self.mention_spin)
        layout.addLayout(mention_row)

        layout.addStretch()
        return panel

    def _create_notifications_group(self) -> QGroupBox:
        group = QGroupBox("待处理通知")
        layout = QVBoxLayout()

        self.notification_list = QListWidget()
        self.notification_list.setObjectName('flatList')
        self.notification_list.setMinimumHeight(64)
        self.notification_list.setMaximumHeight(110)
        layout.addWidget(self.notification_list)

        self.no_notification_label = QLabel("暂无待处理通知")
        self.no_notification_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.no_notification_label.setObjectName('cardSubtitle')
        layout.addWidget(self.no_notification_label)

        group.setLayout(layout)
        return group

    @staticmethod
    def _muted_label(text: str) -> QLabel:
        label = QLabel(text)
        label.setObjectName('cardSubtitle')
        return label

    # --------------------------------------------------------------- update
    def update_dashboard(self):
        try:
            self._update_kpis()
            self._update_recent_actions()
            self._update_account_panel()
            self._update_notifications()
        except Exception as exc:  # noqa: BLE001
            logger.debug(f'更新仪表盘失败: {exc}')

    def _status_state(self) -> dict:
        if self._status_provider is None:
            return {}
        try:
            return self._status_provider() or {}
        except Exception as exc:  # noqa: BLE001
            logger.debug(f'读取运行状态失败: {exc}')
            return {}

    def _notifications(self) -> list:
        if self._notification_provider is None:
            return []
        try:
            return list(self._notification_provider() or [])
        except Exception as exc:  # noqa: BLE001
            logger.debug(f'读取通知失败: {exc}')
            return []

    def _update_kpis(self):
        stats = self.db.get_statistics() if self.db else {}
        series = (
            self.db.get_activity_days(7)
            if self.db else {'posts': [], 'replies': [], 'sent': [], 'runs': []}
        )
        today_runs = self.db.get_today_agent_runs() if self.db else 0
        pending = self._notifications()

        cards = {
            'sent': (
                stats.get('today_comments', 0),
                f"评论 {stats.get('today_posts', 0)} · 回复 {stats.get('today_replies', 0)}",
                series.get('sent'),
                '',
            ),
            'replies': (
                stats.get('today_replies', 0),
                '来自评论与私信',
                series.get('replies'),
                '',
            ),
            'runs': (
                today_runs,
                f"累计 {stats.get('total_agent_runs', 0)} 轮",
                series.get('runs'),
                '',
            ),
            'pending': (
                len(pending),
                '未读提醒' if not pending else pending[0][:18],
                [0, 0, 0, 0, 0, 0, len(pending)],
                '#D29922',
            ),
        }
        for key, (value, hint, values, color) in cards.items():
            self._kpis[key]['value'].setText(str(value))
            self._kpis[key]['hint'].setText(hint)
            self._sparklines[key].set_values(values or [0, 0], color)

        state = self._status_state()
        if state.get('running'):
            self.pause_btn.setText('暂停自动运营')
            self.pause_btn.setIcon(load_icon('pause'))
        else:
            self.pause_btn.setText('启动自动运营')
            self.pause_btn.setIcon(load_icon('play'))

    def _update_recent_actions(self):
        if not self.db:
            return
        self.recent_list.clear()
        sessions = self.db.get_recent_agent_sessions(limit=6)
        for session in sessions:
            created = session.get('created_at')
            if isinstance(created, datetime):
                time_str = created.strftime('%H:%M')
            else:
                time_str = str(created or '')[11:16]
            summary = str(session.get('summary') or '无摘要')
            if len(summary) > 64:
                summary = summary[:64] + '…'
            self.recent_list.addItem(f"{time_str}    {summary}")
        if not sessions:
            self.recent_list.addItem("暂无最近动作")
        self.recent_subtitle.setText(
            f"最近 6 轮 · {len(sessions)} 次记录"
        )

    def _update_account_panel(self):
        credential = getattr(self.bili_api, 'credential', None)
        logged_in = bool(credential and getattr(credential, 'sessdata', ''))
        self.login_state_label.setText(
            "● 已登录" if logged_in else "● 未登录"
        )
        self.login_state_label.setProperty(
            'state', 'ok' if logged_in else 'off'
        )
        self.login_state_label.style().unpolish(self.login_state_label)
        self.login_state_label.style().polish(self.login_state_label)

        uid = getattr(credential, 'dedeuserid', '') if credential else ''
        self.account_label.setText(f"UID：{uid or '--'}")

        try:
            maximum = int(self.config.get('limits.max_comments_per_day', 60))
        except (TypeError, ValueError):
            maximum = 60
        used = 0
        if self.db:
            try:
                used = int(self.db.get_today_comment_count(include_replies=True))
            except Exception:  # noqa: BLE001
                used = 0
        self.quota_label.setText(f"{used} / {maximum}")
        percent = int(used * 100 / maximum) if maximum else 0
        self.quota_bar.setValue(max(0, min(100, percent)))

        risk = '正常'
        try:
            if getattr(self.bili_api, 'is_posting_blocked', lambda: False)():
                until = getattr(self.bili_api, 'posting_blocked_until', None)
                risk = f"发评论冷却至 {until:%m-%d %H:%M}" if until else '发评论冷却中'
            elif getattr(self.bili_api, 'is_blocked', lambda: False)():
                risk = '412 风控冷却中'
        except Exception:  # noqa: BLE001
            pass
        self.risk_label.setText(f"风控：{risk}")

        state = self._status_state()
        next_run = str(state.get('next_run') or '')
        self.next_run_label.setText(
            f"自动运营：{state.get('label') or ('运行中' if state.get('running') else '已暂停')}"
            + (f" · {next_run}" if next_run and next_run not in ('已启动', '未启动') else '')
        )

        growth_text = '成长档案：暂无'
        if self.db:
            try:
                total = sum(self.db.growth_counts().values())
                last = last_learned_at()
                growth_text = f"成长档案：{total} 条"
                if last:
                    growth_text += f" · {last:%m-%d %H:%M} 更新"
            except Exception:  # noqa: BLE001
                pass
        self.growth_label.setText(growth_text)

    def _update_notifications(self):
        items = self._notifications()
        self.notification_list.clear()
        for item in items:
            self.notification_list.addItem(str(item))
        self.notification_list.setVisible(bool(items))
        self.no_notification_label.setVisible(not items)

    def sync_mention_score(self):
        """设置页修改阈值后同步到仪表盘。"""
        try:
            value = int(
                self.config.get('limits.min_score_to_mention_owner', 13)
            )
        except (TypeError, ValueError):
            value = 13
        self.mention_spin.blockSignals(True)
        self.mention_spin.setValue(max(0, min(20, value)))
        self.mention_spin.blockSignals(False)

    def _update_mention_score(self, value):
        try:
            self.config.set('limits.min_score_to_mention_owner', value)
            logger.info(f'已更新@主人分数阈值为 {value}/20')
            self.mention_score_changed.emit(int(value))
        except Exception as exc:  # noqa: BLE001
            logger.warning(f'保存@主人分数阈值失败: {exc}')
