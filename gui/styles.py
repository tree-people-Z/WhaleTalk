"""统一的现代浅色界面主题。"""

MODERN_STYLE = """
QMainWindow, QWidget {
    background-color: #f4f7fb;
    color: #172033;
    font-family: "Segoe UI", "Microsoft YaHei UI", sans-serif;
    font-size: 14px;
}

QMainWindow { background-color: #f4f7fb; }
QWidget#qt_scrollarea_viewport, QScrollArea { background: transparent; border: none; }

QGroupBox {
    background-color: #ffffff;
    border: 1px solid #e4eaf2;
    border-radius: 12px;
    margin-top: 18px;
    padding: 20px 18px 16px 18px;
    font-size: 15px;
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

QPushButton {
    background-color: #ffffff;
    color: #34445e;
    border: 1px solid #d8e1ec;
    border-radius: 8px;
    padding: 10px 18px;
    min-height: 20px;
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

QTabWidget::pane {
    background-color: #ffffff;
    border: 1px solid #e1e8f0;
    border-radius: 12px;
    top: -1px;
}
QTabBar::tab {
    background: transparent;
    color: #75839a;
    border: none;
    border-bottom: 2px solid transparent;
    padding: 12px 20px;
    margin-right: 6px;
    font-weight: 600;
}
QTabBar::tab:selected { color: #287c78; border-bottom-color: #287c78; }
QTabBar::tab:hover:!selected { color: #34445e; background-color: #edf2f7; border-radius: 7px 7px 0 0; }

QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QSpinBox {
    background-color: #fbfcfe;
    color: #1d293b;
    border: 1px solid #d9e2ed;
    border-radius: 8px;
    padding: 9px 12px;
    min-height: 20px;
    selection-background-color: #cfe7e4;
    selection-color: #173b39;
}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus,
QComboBox:focus, QSpinBox:focus { background-color: #ffffff; border: 1px solid #5a9c98; }
QTextEdit, QPlainTextEdit { padding: 10px; }
QTextEdit#logText { background-color: #f8fafc; font-family: "Cascadia Code", Consolas, monospace; }
QComboBox::drop-down, QSpinBox::up-button, QSpinBox::down-button { border: none; width: 20px; }
QComboBox QAbstractItemView {
    background-color: #ffffff;
    border: 1px solid #d9e2ed;
    selection-background-color: #e6f2f1;
    selection-color: #245f5c;
    outline: none;
}

QCheckBox { spacing: 10px; color: #34445e; padding: 5px 0; }
QCheckBox::indicator { width: 17px; height: 17px; border: 1px solid #cbd6e3; border-radius: 5px; background: #ffffff; }
QCheckBox::indicator:hover { border-color: #5a9c98; }
QCheckBox::indicator:checked { background: #287c78; border-color: #287c78; }

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

QTableWidget {
    background-color: #ffffff;
    alternate-background-color: #f8fafc;
    border: 1px solid #e2e8f0;
    border-radius: 10px;
    gridline-color: #edf1f5;
    selection-background-color: #e2f0ef;
    selection-color: #1f514f;
    outline: none;
}
QTableWidget::item { padding: 10px; border: none; }
QHeaderView::section {
    background-color: #f5f8fb;
    color: #62718a;
    padding: 10px 8px;
    border: none;
    border-bottom: 1px solid #e2e8f0;
    font-weight: 600;
}

QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: #cbd5e1; min-height: 28px; border-radius: 5px; }
QScrollBar::handle:vertical:hover { background: #9eacbd; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; height: 0; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px; }
QScrollBar::handle:horizontal { background: #cbd5e1; min-width: 28px; border-radius: 5px; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal,
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background: transparent; width: 0; }

QStatusBar { background: #ffffff; color: #718096; border-top: 1px solid #e4eaf2; padding: 4px 10px; }
QStatusBar::item { border: none; }
QLabel { color: #34445e; }
"""

DARK_STYLE = """
QMainWindow, QWidget {
    background-color: #0f172a;
    color: #e2e8f0;
    font-family: "Segoe UI", "Microsoft YaHei UI", sans-serif;
    font-size: 14px;
}
QMainWindow { background-color: #0f172a; }
QWidget#qt_scrollarea_viewport, QScrollArea { background: transparent; border: none; }
QLabel { color: #dbe4f0; }

QGroupBox {
    background-color: #1e293b;
    border: 1px solid #334155;
    border-radius: 12px;
    margin-top: 18px;
    padding: 20px 18px 16px 18px;
    font-size: 15px;
    font-weight: 600;
    color: #e2e8f0;
}
QGroupBox::title {
    subcontrol-origin: margin;
    subcontrol-position: top left;
    left: 14px;
    padding: 0 7px;
    background-color: #1e293b;
    color: #cbd5e1;
}

QPushButton {
    background-color: #1e293b;
    color: #e2e8f0;
    border: 1px solid #334155;
    border-radius: 8px;
    padding: 10px 18px;
    min-height: 20px;
    font-weight: 600;
}
QPushButton:hover { background-color: #243449; border-color: #475569; }
QPushButton:pressed { background-color: #172033; }
QPushButton:disabled { background-color: #172033; color: #64748b; border-color: #263449; }
QPushButton#primaryButton {
    background-color: #0f766e;
    color: #ffffff;
    border: 1px solid #0f766e;
}
QPushButton#primaryButton:hover { background-color: #0d9488; border-color: #0d9488; }

QTabWidget::pane {
    background-color: #1e293b;
    border: 1px solid #334155;
    border-radius: 12px;
    top: -1px;
}
QTabBar::tab {
    background: transparent;
    color: #94a3b8;
    border: none;
    border-bottom: 2px solid transparent;
    padding: 12px 18px;
    margin-right: 4px;
    font-weight: 600;
}
QTabBar::tab:selected { color: #2dd4bf; border-bottom-color: #2dd4bf; }
QTabBar::tab:hover:!selected { color: #e2e8f0; background-color: #1e293b; border-radius: 7px 7px 0 0; }

QLineEdit, QTextEdit, QPlainTextEdit, QComboBox, QSpinBox {
    background-color: #111827;
    color: #e2e8f0;
    border: 1px solid #334155;
    border-radius: 8px;
    padding: 9px 12px;
    min-height: 20px;
    selection-background-color: #115e59;
    selection-color: #ecfeff;
}
QLineEdit:focus, QTextEdit:focus, QPlainTextEdit:focus,
QComboBox:focus, QSpinBox:focus { background-color: #0b1220; border: 1px solid #2dd4bf; }
QTextEdit, QPlainTextEdit { padding: 10px; }
QTextEdit#logText { background-color: #0b1220; color: #cbd5e1; font-family: "Cascadia Code", Consolas, monospace; }
QComboBox::drop-down, QSpinBox::up-button, QSpinBox::down-button { border: none; width: 20px; }
QComboBox QAbstractItemView {
    background-color: #1e293b;
    color: #e2e8f0;
    border: 1px solid #334155;
    selection-background-color: #115e59;
    selection-color: #ecfeff;
    outline: none;
}

QCheckBox { spacing: 10px; color: #dbe4f0; padding: 5px 0; }
QCheckBox::indicator { width: 17px; height: 17px; border: 1px solid #475569; border-radius: 5px; background: #111827; }
QCheckBox::indicator:hover { border-color: #2dd4bf; }
QCheckBox::indicator:checked { background: #0f766e; border-color: #2dd4bf; }

QListWidget#settingsNav {
    background: transparent;
    border: none;
    outline: none;
    padding: 4px;
}
QListWidget#settingsNav::item {
    padding: 11px 12px;
    border-radius: 8px;
    color: #cbd5e1;
    margin: 2px 0;
}
QListWidget#settingsNav::item:hover { background: #1e293b; }
QListWidget#settingsNav::item:selected {
    background: #134e4a;
    color: #5eead4;
    font-weight: 600;
}

QTableWidget {
    background-color: #111827;
    alternate-background-color: #172033;
    color: #e2e8f0;
    border: 1px solid #334155;
    border-radius: 10px;
    gridline-color: #263449;
    selection-background-color: #134e4a;
    selection-color: #ecfeff;
    outline: none;
}
QTableWidget::item { padding: 10px; border: none; }
QHeaderView::section {
    background-color: #1e293b;
    color: #94a3b8;
    padding: 10px 8px;
    border: none;
    border-bottom: 1px solid #334155;
    font-weight: 600;
}

QListWidget {
    background-color: #111827;
    color: #e2e8f0;
    border: 1px solid #334155;
    border-radius: 8px;
}

QScrollBar:vertical { background: transparent; width: 10px; margin: 2px; }
QScrollBar::handle:vertical { background: #475569; min-height: 28px; border-radius: 5px; }
QScrollBar::handle:vertical:hover { background: #64748b; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical,
QScrollBar::add-page:vertical, QScrollBar::sub-page:vertical { background: transparent; height: 0; }
QScrollBar:horizontal { background: transparent; height: 10px; margin: 2px; }
QScrollBar::handle:horizontal { background: #475569; min-width: 28px; border-radius: 5px; }
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal,
QScrollBar::add-page:horizontal, QScrollBar::sub-page:horizontal { background: transparent; width: 0; }

QStatusBar { background: #1e293b; color: #94a3b8; border-top: 1px solid #334155; padding: 4px 10px; }
QStatusBar::item { border: none; }

QToolTip {
    background: #0b1220;
    color: #e2e8f0;
    border: 1px solid #334155;
    padding: 6px 10px;
    border-radius: 6px;
}
"""
