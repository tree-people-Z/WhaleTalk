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
