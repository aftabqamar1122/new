"""Dark theme: palette, stylesheet and the procedurally drawn tray icon."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPalette, QPixmap

BG = "#12151c"
PANEL = "#1a1f29"
PANEL_2 = "#212836"
LINE = "#2c3446"
TEXT = "#e6eaf2"
MUTED = "#94a0b8"
ACCENT = "#5b9dff"
HIGH = "#ff5f56"
MEDIUM = "#ffa23a"
LOW = "#7e8aa2"
SUCCESS = "#4cc38a"
WARN = "#ffa23a"
ERROR = "#ff5f56"

IMPORTANCE_COLORS = {"high": HIGH, "medium": MEDIUM, "low": LOW}

LEVEL_COLORS = {
    "debug": MUTED,
    "info": "#b9c3d6",
    "warn": WARN,
    "error": ERROR,
    "success": SUCCESS,
}

STYLESHEET = f"""
QWidget {{
    background-color: {BG};
    color: {TEXT};
    font-size: 13px;
}}
QMainWindow, QDialog {{ background-color: {BG}; }}

QToolBar {{
    background: {PANEL};
    border: 0;
    border-bottom: 1px solid {LINE};
    padding: 6px 8px;
    spacing: 6px;
}}
QToolBar QToolButton {{
    background: {PANEL_2};
    border: 1px solid {LINE};
    border-radius: 6px;
    padding: 6px 12px;
    color: {TEXT};
}}
QToolBar QToolButton:hover {{ background: #2a3242; border-color: {ACCENT}; }}
QToolBar QToolButton:disabled {{ color: {LOW}; background: {PANEL}; }}

QGroupBox {{
    border: 1px solid {LINE};
    border-radius: 8px;
    margin-top: 14px;
    padding-top: 10px;
    font-weight: 600;
}}
QGroupBox::title {{
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 5px;
    color: {MUTED};
}}

QLineEdit, QComboBox, QSpinBox, QPlainTextEdit, QTextEdit, QListWidget, QTableWidget {{
    background: {PANEL};
    border: 1px solid {LINE};
    border-radius: 6px;
    padding: 5px 8px;
    selection-background-color: {ACCENT};
    selection-color: #0d1017;
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{ border-color: {ACCENT}; }}
QComboBox::drop-down {{ border: 0; width: 20px; }}
QComboBox QAbstractItemView {{
    background: {PANEL_2};
    border: 1px solid {LINE};
    selection-background-color: {ACCENT};
    selection-color: #0d1017;
}}

QTableWidget {{
    gridline-color: {LINE};
    alternate-background-color: {PANEL_2};
    padding: 0;
}}
QTableWidget::item {{ padding: 6px 8px; border: 0; }}
QTableWidget::item:selected {{ background: #2d3a52; color: {TEXT}; }}
QHeaderView::section {{
    background: {PANEL_2};
    color: {MUTED};
    border: 0;
    border-right: 1px solid {LINE};
    border-bottom: 1px solid {LINE};
    padding: 7px 8px;
    font-weight: 600;
}}

QTabWidget::pane {{ border: 1px solid {LINE}; border-radius: 8px; top: -1px; }}
QTabBar::tab {{
    background: {PANEL};
    border: 1px solid {LINE};
    border-bottom: 0;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
    padding: 8px 16px;
    margin-right: 3px;
    color: {MUTED};
}}
QTabBar::tab:selected {{ background: {PANEL_2}; color: {TEXT}; }}

QPushButton {{
    background: {PANEL_2};
    border: 1px solid {LINE};
    border-radius: 6px;
    padding: 7px 16px;
}}
QPushButton:hover {{ background: #2a3242; border-color: {ACCENT}; }}
QPushButton:disabled {{ color: {LOW}; }}
QPushButton#primary {{
    background: {ACCENT};
    border-color: {ACCENT};
    color: #0d1017;
    font-weight: 600;
}}
QPushButton#primary:hover {{ background: #74aeff; }}

QCheckBox::indicator, QRadioButton::indicator {{
    width: 15px; height: 15px;
    border: 1px solid {LINE};
    border-radius: 4px;
    background: {PANEL};
}}
QCheckBox::indicator:checked {{ background: {ACCENT}; border-color: {ACCENT}; }}

QScrollBar:vertical {{ background: {BG}; width: 11px; margin: 0; }}
QScrollBar::handle:vertical {{ background: #384259; border-radius: 5px; min-height: 28px; }}
QScrollBar::handle:vertical:hover {{ background: #47536f; }}
QScrollBar:horizontal {{ background: {BG}; height: 11px; }}
QScrollBar::handle:horizontal {{ background: #384259; border-radius: 5px; min-width: 28px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

QSplitter::handle {{ background: {LINE}; }}
QSplitter::handle:horizontal {{ width: 3px; }}
QSplitter::handle:vertical {{ height: 3px; }}

QStatusBar {{ background: {PANEL}; border-top: 1px solid {LINE}; color: {MUTED}; }}
QStatusBar::item {{ border: 0; }}

QProgressBar {{
    background: {PANEL};
    border: 1px solid {LINE};
    border-radius: 6px;
    text-align: center;
    max-height: 16px;
    color: {MUTED};
}}
QProgressBar::chunk {{ background: {ACCENT}; border-radius: 5px; }}

QMenu {{ background: {PANEL_2}; border: 1px solid {LINE}; padding: 4px; }}
QMenu::item {{ padding: 6px 22px; border-radius: 4px; }}
QMenu::item:selected {{ background: {ACCENT}; color: #0d1017; }}

QToolTip {{
    background: {PANEL_2};
    color: {TEXT};
    border: 1px solid {LINE};
    padding: 5px;
}}
"""


def apply_theme(app) -> None:
    """Apply the Fusion style plus a dark palette and the stylesheet above."""
    app.setStyle("Fusion")
    palette = QPalette()
    palette.setColor(QPalette.Window, QColor(BG))
    palette.setColor(QPalette.WindowText, QColor(TEXT))
    palette.setColor(QPalette.Base, QColor(PANEL))
    palette.setColor(QPalette.AlternateBase, QColor(PANEL_2))
    palette.setColor(QPalette.Text, QColor(TEXT))
    palette.setColor(QPalette.Button, QColor(PANEL_2))
    palette.setColor(QPalette.ButtonText, QColor(TEXT))
    palette.setColor(QPalette.Highlight, QColor(ACCENT))
    palette.setColor(QPalette.HighlightedText, QColor("#0d1017"))
    palette.setColor(QPalette.ToolTipBase, QColor(PANEL_2))
    palette.setColor(QPalette.ToolTipText, QColor(TEXT))
    palette.setColor(QPalette.PlaceholderText, QColor(MUTED))
    palette.setColor(QPalette.Disabled, QPalette.Text, QColor(LOW))
    palette.setColor(QPalette.Disabled, QPalette.ButtonText, QColor(LOW))
    app.setPalette(palette)
    app.setStyleSheet(STYLESHEET)


def app_icon(size: int = 64, busy: bool = False) -> QIcon:
    """Draw the app/tray icon at runtime so no binary assets are needed."""
    pixmap = QPixmap(size, size)
    pixmap.fill(Qt.transparent)
    painter = QPainter(pixmap)
    painter.setRenderHint(QPainter.Antialiasing)

    painter.setBrush(QColor(PANEL_2))
    painter.setPen(QColor(ACCENT if not busy else MEDIUM))
    radius = size * 0.18
    painter.drawRoundedRect(2, 2, size - 4, size - 4, radius, radius)

    # Three "headline" bars, the top one accented.
    bar_x = size * 0.2
    bar_w = size * 0.6
    painter.setPen(Qt.NoPen)
    for index, (ratio, color) in enumerate(
        ((1.0, HIGH), (0.8, MEDIUM), (0.6, MUTED))
    ):
        painter.setBrush(QColor(color))
        y = size * (0.3 + index * 0.17)
        painter.drawRoundedRect(
            int(bar_x), int(y), int(bar_w * ratio), max(3, int(size * 0.09)), 2, 2
        )
    painter.end()
    return QIcon(pixmap)


def mono_font(point_size: int = 11) -> QFont:
    font = QFont("Menlo")
    font.setStyleHint(QFont.Monospace)
    font.setFamilies(["Menlo", "Consolas", "DejaVu Sans Mono", "Courier New", "monospace"])
    font.setPointSize(point_size)
    return font
