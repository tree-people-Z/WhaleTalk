"""统一的现代浅色界面主题。

设计 token（与 ARCHITECTURE.md 保持一致）：
- 背景 #F5F7FA / 卡片 #FFFFFF / 边框 #E4E9F0
- 主色 #287C78 / 主色浅底 #E6F2F1
- 文本 #101828 / 次级 #5B6B82 / 弱化 #8A97A8
- 圆角：卡片 14px、控件 9px、胶囊 999px
"""

MODERN_STYLE = """
QMainWindow, QWidget {
    background-color: #f5f7fa;
    color: #101828;
    font-family: "Segoe UI", "Microsoft YaHei UI", sans-serif;
    font-size: 13px;
}

QMainWindow { background-color: #f5f7fa; }
QLabel { background: transparent; }
QWidget#contentShell { background-color: #f5f7fa; }
QWidget#qt_scrollarea_viewport, QScrollArea { background: transparent; border: none; }

/* ---------- 左侧导航 ---------- */
QWidget#sidebar {
    background-color: #ffffff;
    border-right: 1px solid #e4e9f0;
}
QLabel#brandTitle {
    font-size: 18px;
    font-weight: 700;
    color: #101828;
}
QLabel#brandSubtitle {
    font-size: 11px;
    color: #8a97a8;
    letter-spacing: 0.4px;
}
QLabel#sideSection {
    color: #98a5b6;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 1.2px;
    padding: 12px 10px 4px 10px;
}
QPushButton#navButton {
    text-align: left;
    background: transparent;
    border: none;
    border-radius: 9px;
    padding: 9px 12px;
    color: #4a5a70;
    font-weight: 500;
}
QPushButton#navButton:hover { background: #f1f5f9; }
QPushButton#navButton:checked {
    background: #eaf3f2;
    color: #1d6360;
    font-weight: 600;
}
QLabel#sideAccount {
    color: #586a80;
    font-size: 12px;
    padding: 9px 10px;
    background: #f5f7fa;
    border: 1px solid #edf1f6;
    border-radius: 9px;
}
QLabel#sideVersion { color: #94a3b8; font-size: 11px; padding-left: 4px; }

/* ---------- 顶部页头 ---------- */
QWidget#pageHeader { background: transparent; }
QLabel#pageTitle { font-size: 24px; font-weight: 700; color: #101828; }
QLabel#pageSubtitle { font-size: 12px; color: #6b7a90; }
QLabel#headerMeta {
    color: #5b6b82;
    font-size: 12px;
    padding: 6px 11px;
    background: #ffffff;
    border: 1px solid #e4e9f0;
    border-radius: 999px;
}
QLabel#statusPill {
    font-size: 12px;
    font-weight: 600;
    padding: 6px 11px;
    border-radius: 999px;
    background: #fdecec;
    color: #b42318;
}
QLabel#statusPill[state="ok"] { background: #e7f7ee; color: #067647; }

/* ---------- 卡片 ---------- */
QGroupBox {
    background-color: #ffffff;
    border: 1px solid #e4e9f0;
    border-radius: 14px;
    margin-top: 16px;
    padding: 18px 16px 14px 16px;
    font-size: 13px;
    font-weight: 600;
    color: #26344b;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 14px;
    padding: 0 7px;
    background-color: #ffffff;
    color: #34445e;
}

/* ---------- KPI / 侧栏卡片 ---------- */
QFrame#kpiCard {
    background: #ffffff;
    border: 1px solid #e4e9f0;
    border-radius: 14px;
}
QLabel#kpiLabel { color: #5b6b82; font-size: 12px; font-weight: 600; }
QLabel#kpiValue { color: #101828; font-size: 28px; font-weight: 700; }
QLabel#kpiHint { color: #8a97a8; font-size: 11px; }
QFrame#sidePanel {
    background: #ffffff;
    border: 1px solid #e4e9f0;
    border-radius: 14px;
}
QLabel#panelTitle { color: #101828; font-size: 15px; font-weight: 700; }
QLabel#cardSubtitle { color: #6b7a90; font-size: 12px; }
QFrame#divider { background: #edf1f6; border: none; }

QProgressBar {
    background: #eef2f7;
    border: none;
    border-radius: 5px;
}
QProgressBar::chunk {
    background: #287c78;
    border-radius: 5px;
}
QProgressBar#quotaBar::chunk { background: #287c78; }

/* ---------- 按钮 ---------- */
QPushButton {
    background-color: #ffffff;
    color: #34445e;
    border: 1px solid #d8e1ec;
    border-radius: 9px;
    padding: 9px 16px;
    min-height: 18px;
    font-weight: 600;
}
QPushButton:hover { background-color: #f2f6fb; border-color: #b8c8dc; }
QPushButton:pressed { background-color: #e8eef6; }
QPushButton:disabled { background-color: #eef1f5; color: #9aa6b6; border-color: #e4e8ee; }
QPushButton#primaryButton {
    background-color: #287c78;
    color: #ffffff;
    border: 1px solid #287c78;
}
QPushButton#primaryButton:hover { background-color: #216b68; border-color: #216b68; }
QPushButton#primaryButton:pressed { background-color: #1b5c59; }
QPushButton#primaryButton:disabled { background-color: #9fc4c2; border-color: #9fc4c2; color: #f4fbfa; }
QPushButton#ghostButton {
    background-color: transparent;
    border: 1px solid #dfe6ef;
    color: #3f5068;
}
QPushButton#ghostButton:hover { background-color: #f1f5f9; border-color: #c8d4e2; }

/* ---------- 标签页（原生 tab bar 已隐藏） ---------- */
QTabWidget#contentTabs::pane {
    background: transparent;
    border: none;
}
QTabBar::tab {
    background: transparent;
    color: #75839a;
    border: none;
    padding: 10px 18px;
    margin-right: 6px;
    font-weight: 600;
}
QTabBar::tab:selected { color: #287c78; }

/* ---------- 表单控件 ---------- */
QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QSpinBox {
    background-color: #fbfcfe;
    color: #1d293b;
    border: 1px solid #d9e2ed;
    border-radius: 9px;
    padding: 8px 11px;
    min-height: 18px;
    selection-background-color: #cfe7e4;
    selection-color: #173b39;
}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus,
QComboBox:focus, QSpinBox:focus { background-color: #ffffff; border: 1px solid #5a9c98; }
QTextEdit, QPlainTextEdit { padding: 10px; }
QTextEdit#logText {
    background-color: #f8fafc;
    border: 1px solid #e7edf4;
    font-family: "Cascadia Code", Consolas, monospace;
    font-size: 12px;
}
QComboBox::drop-down, QSpinBox::up-button, QSpinBox::down-button { border: none; width: 20px; }
QComboBox QAbstractItemView {
    background-color: #ffffff;
    border: 1px solid #d9e2ed;
    selection-background-color: #e6f2f1;
    selection-color: #245f5c;
    outline: none;
}

QCheckBox { spacing: 10px; color: #34445e; padding: 4px 0; }
QCheckBox::indicator { width: 17px; height: 17px; border: 1px solid #cbd6e3; border-radius: 5px; background: #ffffff; }
QCheckBox::indicator:hover { border-color: #5a9c98; }
QCheckBox::indicator:checked { background: #287c78; border-color: #287c78; }

QListWidget#flatList {
    background: #fbfcfe;
    border: 1px solid #edf1f6;
    border-radius: 10px;
    outline: none;
}
QListWidget#flatList::item {
    padding: 9px 10px;
    border-bottom: 1px solid #f1f4f8;
    color: #3f5068;
}
QListWidget#flatList::item:last { border-bottom: none; }
QListWidget#flatList::item:selected {
    background: #e6f2f1;
    color: #1f5f5b;
}

QListWidget#settingsNav {
    background: transparent;
    border: none;
    outline: none;
    padding: 4px;
}
QListWidget#settingsNav::item {
    padding: 11px 12px;
    border-radius: 8px;
    color: #4b5b73;
    margin: 2px 0;
}
QListWidget#settingsNav::item:hover { background: #edf2f7; }
QListWidget#settingsNav::item:selected {
    background: #e2f0ef;
    color: #245f5c;
    font-weight: 600;
}

/* ---------- 表格 ---------- */
QTableWidget {
    background-color: #ffffff;
    alternate-background-color: #f8fafc;
    border: 1px solid #e2e8f0;
    border-radius: 12px;
    gridline-color: #edf1f5;
    selection-background-color: #e2f0ef;
    selection-color: #1f514f;
    outline: none;
}
QTableWidget::item { padding: 9px; border: none; }
QHeaderView::section {
    background-color: #f7f9fc;
    color: #62718a;
    padding: 9px 8px;
    border: none;
    border-bottom: 1px solid #e2e8f0;
    font-weight: 600;
}

/* ---------- 滚动条 ---------- */
QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: #cbd5e1; min-height: 28px; border-radius: 5px; }
QScrollBar::handle:vertical:hover { background: #9eacbd; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; height: 0; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px; }
QScrollBar::handle:horizontal { background: #cbd5e1; min-width: 28px; border-radius: 5px; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal,
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background: transparent; width: 0; }

QStatusBar { background: #ffffff; color: #718096; border-top: 1px solid #e4eaf2; padding: 4px 12px; }
QStatusBar::item { border: none; }
QLabel { color: #34445e; }
"""
