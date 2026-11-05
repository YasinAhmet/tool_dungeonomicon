"""Small pieces the character sheet is made of: chips, rich tooltips, the HP bar, section cards, ability tiles."""
from typing import Callable, Optional

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QFrame, QLabel, QProgressBar, QPushButton, QSizePolicy, QWidget

from ...theme import COLORS
from ...widgets.common import FlowLayout, card, label, title
from ...widgets.text import to_html

CHIP_QSS = "QPushButton { padding: 1px 6px; }"


def rich_tip(text: str) -> str:
    """A tooltip that keeps the line breaks and word-wraps long rule texts."""
    return f"<qt>{to_html(text)}</qt>" if text else ""


def sign(n) -> str:
    try:
        return f"{int(n):+d}"
    except (TypeError, ValueError):
        return str(n)


class Chip(QPushButton):
    """A small button for spells, features, conditions, proficiencies. right_clicked fires on a right click; hovered
    with True/False as the mouse enters and leaves."""
    right_clicked = Signal()
    hovered = Signal(bool)

    def __init__(self, text: str, on_click: Optional[Callable] = None, tip: str = "", kind: str = "",
                 checked: Optional[bool] = None, parent=None):
        super().__init__(text, parent)
        self.setStyleSheet(CHIP_QSS)
        self.setCursor(Qt.PointingHandCursor if on_click else Qt.ArrowCursor)
        if kind:
            self.setProperty("kind", kind)
        if tip:
            self.setToolTip(rich_tip(tip))
        if checked is not None:
            self.setCheckable(True)
            self.setChecked(checked)
        if on_click:
            self.clicked.connect(lambda *_: on_click())
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(lambda _p: self.right_clicked.emit())

    def enterEvent(self, e):
        self.hovered.emit(True)
        super().enterEvent(e)

    def leaveEvent(self, e):
        self.hovered.emit(False)
        super().leaveEvent(e)


def pips(left: int, total: int, use: Callable, back: Callable, what: str, color: str = "") -> list:
    """A small button per use (spell slots, Second Wind...): a full one (●) spends one, an empty one (○) gives one back."""
    from ....core.i18n import tr
    out = []
    for i in range(total):
        full = i < left
        b = QPushButton("●" if full else "○")
        b.setProperty("kind", "flat")
        b.setCursor(Qt.PointingHandCursor)
        b.setFixedWidth(16)
        b.setToolTip(rich_tip(f"{what}: " + tr("{0} of {1} left", left, total) + "\n" +
                              (tr("Click to use one") if full else tr("Click to get one back"))))
        b.setStyleSheet(f"QPushButton {{ padding: 0; font-size: 12pt; color: {(color or COLORS['accent']) if full else COLORS['dim']}; }}")
        b.clicked.connect(lambda *_, f=full: (use if f else back)())
        out.append(b)
    return out


def bare(w: QWidget) -> QWidget:
    """No background of its own (a layout host inside a card)."""
    w.setObjectName("bare")
    w.setStyleSheet("#bare { background: transparent; }")
    return w


def flow(*widgets: QWidget, spacing: int = 3) -> QWidget:
    """Widgets that wrap like words; takes the width it is given."""
    host = bare(QWidget())
    policy = QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
    policy.setHeightForWidth(True)
    host.setSizePolicy(policy)
    lay = FlowLayout(host, spacing=spacing)
    for w in widgets:
        if w is not None:
            lay.addWidget(w)
    return host


def section(heading: str, *children, extra: Optional[QWidget] = None) -> QFrame:
    """A card with a heading (and an optional widget at the heading's right, e.g. an Add button)."""
    from ...widgets.common import row, stretch
    head = row(title(heading), stretch(), extra) if extra is not None else title(heading)
    return card(head, *children, spacing=3)


def clickable(text: str, on_click: Callable, tip: str = "", big: bool = False) -> QPushButton:
    """A flat button that reads like text (a number to roll, a skill name)."""
    b = QPushButton(text)
    b.setProperty("kind", "flat")
    b.setCursor(Qt.PointingHandCursor)
    style = "QPushButton { padding: 0 3px; text-align: left; }"
    if big:
        style = "QPushButton { padding: 0 2px; font-size: 13pt; font-weight: 600; }"
    b.setStyleSheet(style)
    if tip:
        b.setToolTip(rich_tip(tip))
    b.clicked.connect(lambda *_: on_click())
    return b


class HpBar(QProgressBar):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setTextVisible(False)
        self.setFixedHeight(6)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    def set_hp(self, hp: int, max_hp: int):
        self.setMaximum(max(1, max_hp))
        self.setValue(max(0, min(hp, max_hp)))
        pct = hp / max_hp if max_hp else 0
        colour = COLORS["bad"] if pct <= .25 else COLORS["warn"] if pct <= .5 else COLORS["good"]
        self.setStyleSheet(f"QProgressBar {{ border: 0; border-radius: 3px; }} "
                           f"QProgressBar::chunk {{ background: {colour}; border-radius: 3px; }}")


def tile(caption: str, value: str, tip: str = "") -> QFrame:
    """A small raised box: a caption and a value (AC, speed...)."""
    v = QLabel(value)
    v.setAlignment(Qt.AlignCenter)
    f = v.font()
    f.setPointSize(f.pointSize() + 3)
    f.setBold(True)
    v.setFont(f)
    c = label(caption, role="dim")
    c.setAlignment(Qt.AlignCenter)
    box = card(c, v, spacing=0)
    box.layout().setContentsMargins(6, 3, 6, 3)
    if tip:
        box.setToolTip(rich_tip(tip))
    box.setMinimumWidth(64)
    return box
