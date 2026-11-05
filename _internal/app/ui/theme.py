"""The editor's look: one compact dark theme. Colours live in COLORS so widgets that paint themselves share them.

    from app.ui.theme import COLORS
    painter.setPen(QColor(COLORS["accent"]))

Object names give widgets a role in the style sheet: setObjectName("dim"), "title", "good", "bad", "warn", "accent",
"mono", "card". Buttons take the property kind="primary" | "danger" | "flat".
"""
from PySide6.QtGui import QColor, QFont, QPalette
from PySide6.QtWidgets import QApplication

COLORS = {
    "bg": "#0f1115", "panel": "#161a21", "raised": "#1d2330", "hover": "#262e40", "input": "#0d0f14", "border": "#262c37",
    "text": "#e6e9ef", "dim": "#8b93a3", "accent": "#7c8cff", "accent_dim": "#4b52a8",
    "good": "#4ade80", "bad": "#f87171", "warn": "#fbbf24",
}
FONT, MONO, SIZE = "Segoe UI", "Consolas", 9

QSS = """
* {{ outline: 0; }}
QWidget {{ color: {text}; background: {panel}; }}                     /* the font comes from apply(): setFont() keeps working */
QMainWindow, QMenuBar, QStatusBar, QToolBar {{ background: {bg}; }}
QToolTip {{ background: {raised}; color: {text}; border: 1px solid {border}; padding: 4px; }}
QMenuBar::item {{ padding: 3px 8px; background: transparent; }}
QMenuBar::item:selected, QMenu::item:selected {{ background: {hover}; }}
QMenu {{ background: {raised}; border: 1px solid {border}; padding: 3px; }}
QMenu::item {{ padding: 3px 18px 3px 10px; }}
QMenu::separator {{ height: 1px; background: {border}; margin: 3px 6px; }}
QToolBar {{ border: 0; border-bottom: 1px solid {border}; spacing: 3px; padding: 2px 4px; }}
QStatusBar {{ border-top: 1px solid {border}; color: {dim}; }}
QStatusBar::item {{ border: 0; }}

QPushButton, QToolButton {{ background: {raised}; border: 1px solid {border}; border-radius: 4px; padding: 3px 9px; }}
QPushButton:hover, QToolButton:hover {{ background: {hover}; }}
QPushButton:pressed, QToolButton:pressed, QToolButton:checked, QPushButton:checked {{ background: {accent_dim}; }}
QPushButton[kind="primary"] {{ background: {accent_dim}; border-color: {accent}; }}
QPushButton[kind="primary"]:hover {{ background: {accent}; }}
QPushButton[kind="danger"] {{ border-color: {bad}; color: {bad}; }}
QPushButton[kind="flat"], QToolButton[kind="flat"] {{ background: transparent; border-color: transparent; }}
QPushButton[kind="flat"]:hover, QToolButton[kind="flat"]:hover {{ background: {hover}; }}
QPushButton[kind="flat"]:checked, QToolButton[kind="flat"]:checked {{ background: {accent_dim}; }}
QPushButton:disabled, QToolButton:disabled, QPushButton[kind="primary"]:disabled, QPushButton[kind="danger"]:disabled {{
    color: {dim}; background: {panel}; border-color: {border}; }}
QToolButton::menu-indicator {{ image: none; }}

QLineEdit, QSpinBox, QDoubleSpinBox, QComboBox, QPlainTextEdit, QTextEdit, QDateEdit {{
    background: {input}; border: 1px solid {border}; border-radius: 4px; padding: 2px 5px;
    selection-background-color: {accent_dim}; }}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus, QPlainTextEdit:focus, QTextEdit:focus {{ border-color: {accent_dim}; }}
QComboBox QAbstractItemView {{ background: {raised}; border: 1px solid {border}; selection-background-color: {hover}; }}
QComboBox::drop-down {{ border: 0; width: 16px; }}
QAbstractSpinBox::up-button, QAbstractSpinBox::down-button {{ subcontrol-origin: border; width: 0px; border: 0; }}
QAbstractSpinBox QLineEdit {{ padding: 0; border: 0; background: transparent; }}
QCheckBox, QRadioButton {{ background: transparent; spacing: 5px; }}
QCheckBox::indicator, QRadioButton::indicator {{ width: 13px; height: 13px; border: 1px solid {border}; background: {input}; }}
QCheckBox::indicator {{ border-radius: 3px; }}
QRadioButton::indicator {{ border-radius: 7px; }}
QCheckBox::indicator:checked, QRadioButton::indicator:checked {{ background: {accent}; border-color: {accent}; }}

QTabWidget::pane {{ border: 1px solid {border}; border-radius: 4px; top: -1px; }}
QTabBar::tab {{ background: {bg}; color: {dim}; padding: 4px 10px; border: 1px solid {border}; border-bottom: 0; margin-right: 1px;
                border-top-left-radius: 4px; border-top-right-radius: 4px; }}
QTabBar::tab:selected {{ background: {panel}; color: {text}; }}
QTabBar::tab:hover {{ color: {text}; }}

QTreeView, QListView, QTableView, QTreeWidget, QListWidget, QTableWidget {{
    background: {input}; alternate-background-color: {panel}; border: 1px solid {border}; border-radius: 4px;
    selection-background-color: {accent_dim}; selection-color: {text}; gridline-color: {border}; }}
QTreeView::item, QListView::item {{ padding: 1px 2px; }}
QTreeView::item:hover, QListView::item:hover, QTableView::item:hover {{ background: {hover}; }}
QHeaderView::section {{ background: {raised}; color: {dim}; border: 0; border-right: 1px solid {border};
                        border-bottom: 1px solid {border}; padding: 2px 5px; }}
QScrollBar:vertical {{ width: 9px; background: transparent; margin: 0; }}
QScrollBar:horizontal {{ height: 9px; background: transparent; margin: 0; }}
QScrollBar::handle {{ background: #2b3242; border-radius: 4px; min-height: 24px; min-width: 24px; }}
QScrollBar::add-line, QScrollBar::sub-line {{ width: 0; height: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}
QSplitter::handle {{ background: {border}; }}
QGroupBox {{ border: 1px solid {border}; border-radius: 5px; margin-top: 14px; padding: 6px 4px 4px 4px; }}
QGroupBox::title {{ subcontrol-origin: margin; left: 8px; padding: 0 3px; color: {dim}; }}
QProgressBar {{ background: {input}; border: 1px solid {border}; border-radius: 3px; text-align: center; height: 12px; }}
QProgressBar::chunk {{ background: {accent_dim}; border-radius: 3px; }}
QSlider::groove:horizontal {{ height: 4px; background: {border}; border-radius: 2px; }}
QSlider::handle:horizontal {{ background: {accent}; width: 12px; margin: -5px 0; border-radius: 6px; }}

QLabel {{ background: transparent; }}
QLabel#dim, QLabel[role="dim"] {{ color: {dim}; }}
QLabel#title, QLabel[role="title"] {{ color: {dim}; font-size: {small}pt; font-weight: 600; letter-spacing: 1px; }}
QLabel#good, QLabel[role="good"] {{ color: {good}; }}
QLabel#bad, QLabel[role="bad"] {{ color: {bad}; }}
QLabel#warn, QLabel[role="warn"] {{ color: {warn}; }}
QLabel#accent, QLabel[role="accent"] {{ color: {accent}; }}
QFrame#card, QFrame[role="card"] {{ background: {raised}; border: 1px solid {border}; border-radius: 5px; }}
QFrame#card QLabel, QFrame#card > QWidget, QFrame[role="card"] > QWidget {{ background: transparent; }}
QFrame#card QAbstractScrollArea > QWidget > QWidget {{ background: transparent; }}
*[role="mono"], QPlainTextEdit#mono {{ font-family: "{mono}"; }}

QFrame#toast {{ background: {raised}; border: 1px solid {border}; border-left: 3px solid {accent}; border-radius: 4px; }}
QFrame#toast[kind="good"] {{ border-left-color: {good}; }}
QFrame#toast[kind="warn"] {{ border-left-color: {warn}; }}
QFrame#toast[kind="error"] {{ border-left-color: {bad}; }}

/* docking (Qt Advanced Docking System) */
ads--CDockContainerWidget, ads--CDockAreaWidget {{ background: {bg}; }}
ads--CDockAreaTitleBar {{ background: {bg}; border-bottom: 1px solid {border}; }}
ads--CDockWidgetTab {{ background: {bg}; border: 0; border-right: 1px solid {border}; padding: 0 2px; }}
ads--CDockWidgetTab[activeTab="true"] {{ background: {panel}; border-top: 2px solid {accent}; }}
ads--CDockWidgetTab QLabel {{ color: {dim}; }}
ads--CDockWidgetTab[activeTab="true"] QLabel {{ color: {text}; }}
ads--CDockWidget {{ background: {panel}; border: 0; }}
ads--CDockSplitter::handle {{ background: {border}; }}
ads--CTitleBarButton, ads--CDockAreaTitleBar QToolButton, ads--CDockWidgetTab QPushButton {{ background: transparent; border: 0; padding: 0; }}
ads--CDockAreaTitleBar QToolButton:hover, ads--CDockWidgetTab QPushButton:hover {{ background: {hover}; }}
ads--CAutoHideTab {{ background: {bg}; color: {dim}; padding: 2px 6px; border: 0; }}
ads--CAutoHideTab:hover {{ color: {text}; }}
ads--CAutoHideSideBar {{ background: {bg}; border: 0; }}
"""


def apply(app: QApplication):
    app.setStyle("Fusion")
    font = QFont(FONT, SIZE)
    app.setFont(font)
    pal = QPalette()
    c = {k: QColor(v) for k, v in COLORS.items()}
    for role, key in ((QPalette.Window, "panel"), (QPalette.WindowText, "text"), (QPalette.Base, "input"),
                      (QPalette.AlternateBase, "panel"), (QPalette.Text, "text"), (QPalette.Button, "raised"),
                      (QPalette.ButtonText, "text"), (QPalette.Highlight, "accent_dim"), (QPalette.HighlightedText, "text"),
                      (QPalette.ToolTipBase, "raised"), (QPalette.ToolTipText, "text"), (QPalette.PlaceholderText, "dim"),
                      (QPalette.Link, "accent")):
        pal.setColor(role, c[key])
    pal.setColor(QPalette.Disabled, QPalette.Text, c["dim"])
    pal.setColor(QPalette.Disabled, QPalette.ButtonText, c["dim"])
    app.setPalette(pal)
    app.setStyleSheet(QSS.format(**COLORS, font=FONT, mono=MONO, size=SIZE, small=SIZE - 1))
