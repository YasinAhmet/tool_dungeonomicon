"""Picture buttons: the game-icons pictures of the icon modules (white on transparent) tinted, as compact square
buttons whose words live in the tooltip - the editor's version of the portal's icon bar.

    icon_button("short_rest", self.rest, tr("Short rest"))              # a key of icons.UI, or a picture's name
    icon_button("Poisoned", fn, tip, color="#4ade80", checked=True)    # a toggle: dim when off, coloured when on
    QIcon(game_pixmap("campfire", 18, COLORS["warn"]))
"""
from typing import Callable, Optional

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QColor, QGuiApplication, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QButtonGroup, QHBoxLayout, QMenu, QToolButton, QWidget

from ..theme import COLORS
from .common import amp
from .text import to_html

_cache = {}


def slug_of(key: str) -> Optional[str]:
    """A UI key ("short_rest"), a condition ("Poisoned") or a picture's own name ("campfire") -> the picture's name."""
    from ...services.battle import icons
    if key in icons.UI:
        return icons.UI[key]
    if key in icons.BADGES:
        return icons.BADGES[key][0]
    return key if icons.path(key) else None


def game_pixmap(key: str, size: int, color: Optional[str] = None, opacity: float = 1.0) -> Optional[QPixmap]:
    """The picture at `size` px, tinted `color` (white when None); None when there is no such picture."""
    from ...services.battle import icons
    slug = slug_of(key)
    path = icons.path(slug) if slug else None
    if not path:
        return None
    k = (slug, size, color, round(opacity, 2))
    if k not in _cache:
        app = QGuiApplication.instance()
        dpr = app.devicePixelRatio() if app else 1.0          # sharp on a scaled (125 %, 150 %) screen
        pm = QPixmap(path).scaled(round(size * dpr), round(size * dpr), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        pm.setDevicePixelRatio(dpr)
        if color or opacity < 1:
            out = QPixmap(pm.size())
            out.setDevicePixelRatio(dpr)
            out.fill(Qt.transparent)
            p = QPainter(out)
            p.setOpacity(opacity)
            p.drawPixmap(0, 0, pm)
            if color:
                p.setOpacity(1.0)
                p.setCompositionMode(QPainter.CompositionMode_SourceIn)
                p.fillRect(out.rect(), QColor(color))
            p.end()
            pm = out
        _cache[k] = pm
    return _cache[k]


def game_icon(key: str, size: int = 18, color: Optional[str] = None, off_color: Optional[str] = None) -> QIcon:
    """An icon for a button: `color` normally (or when checked), `off_color` when a toggle is off, dim when disabled."""
    icon = QIcon()
    on = game_pixmap(key, size, color or COLORS["text"])
    if on is None:
        return icon
    icon.addPixmap(on, QIcon.Normal, QIcon.On)
    icon.addPixmap(game_pixmap(key, size, off_color) if off_color else on, QIcon.Normal, QIcon.Off)
    icon.addPixmap(game_pixmap(key, size, COLORS["dim"], 0.45), QIcon.Disabled, QIcon.Off)
    icon.addPixmap(game_pixmap(key, size, COLORS["dim"], 0.45), QIcon.Disabled, QIcon.On)
    return icon


def icon_button(key: str, on_click: Optional[Callable] = None, tip: str = "", color: Optional[str] = None,
                checked: Optional[bool] = None, size: int = 18, kind: str = "flat", text: str = "",
                fallback: str = "") -> QToolButton:
    """A square picture button with its words in the tooltip. checked: a toggle (dim when off, `color` when on);
    text: a few words beside the picture (a count); fallback: what to show when the picture is missing."""
    b = QToolButton()
    b.setProperty("kind", kind)
    b.setAutoRaise(True)
    b.setCursor(Qt.PointingHandCursor)
    toggle = checked is not None
    icon = game_icon(key, size, color, COLORS["dim"] if toggle else None)
    if icon.isNull():
        b.setText(amp(fallback or tip.split("\n")[0][:3]))
    else:
        b.setIcon(icon)
        b.setIconSize(QSize(size, size))
    if text:
        b.setText(amp(text))
        b.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
    b.setStyleSheet("QToolButton { padding: 2px; }" + ("QToolButton:checked { background: #262e40; border-color: #3a4256; }"
                                                       if toggle else ""))
    if tip:
        b.setToolTip(f"<qt>{to_html(tip)}</qt>")
    if toggle:
        b.setCheckable(True)
        b.setChecked(bool(checked))
    if on_click:
        b.clicked.connect(lambda *_: on_click())
    return b


class IconChoice(QToolButton):
    """A choice shown as the chosen item's picture (in its colour), the others in a menu of pictures and words - a
    combo box in a square. Reads like a combo: currentData(), setCurrentIndex(). items: (words, value, picture, colour);
    an item without a picture shows `blank` (the "no choice" one)."""

    def __init__(self, items, tip: str = "", size: int = 18, blank: str = "◌"):
        super().__init__()
        self.items, self.tip, self.size, self.blank = list(items), tip, size, blank
        self.index = 0
        self.setAutoRaise(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setPopupMode(QToolButton.InstantPopup)
        self.setStyleSheet("QToolButton { padding: 2px; } QToolButton::menu-indicator { image: none; width: 0; }")
        menu = QMenu(self)
        for i, (words, _value, pic, colour) in enumerate(self.items):
            act = menu.addAction(game_icon(pic, 16, colour) if pic else QIcon(), words)
            act.triggered.connect(lambda _=False, i=i: self.setCurrentIndex(i))
        self.setMenu(menu)
        self.setCurrentIndex(0)

    def currentData(self):
        return self.items[self.index][1]

    def currentIndex(self) -> int:
        return self.index

    def setCurrentIndex(self, i: int):
        self.index = max(0, min(i, len(self.items) - 1))
        words, _value, pic, colour = self.items[self.index]
        icon = game_icon(pic, self.size, colour) if pic else QIcon()
        self.setIcon(icon)
        self.setIconSize(QSize(self.size, self.size))
        self.setText("" if not icon.isNull() else self.blank)
        self.setToolTip(f"<qt>{to_html(f'**{words}**' + (chr(10) + self.tip if self.tip else ''))}</qt>")


class AdvSwitch(QWidget):
    """Normal / advantage / disadvantage as three small toggles in one segment, with the words on hover. Reads like
    the combo box it replaces: currentData(), findData(), setCurrentIndex(); on_change(value) when clicked."""
    VALUES = (None, "adv", "dis")

    def __init__(self, on_change: Optional[Callable] = None, tip: str = "", parent=None):
        super().__init__(parent)
        from ...core.i18n import tr
        self.on_change = on_change
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        self.group = QButtonGroup(self)
        self.group.setExclusive(True)
        looks = (("=", COLORS["dim"], tr("Normal roll")),
                 ("▲", COLORS["good"], tr("Advantage: roll two d20s and keep the higher")),
                 ("▼", COLORS["bad"], tr("Disadvantage: roll two d20s and keep the lower")))
        for i, (glyph, color, words) in enumerate(looks):
            b = QToolButton()
            b.setText(glyph)
            b.setCheckable(True)
            b.setCursor(Qt.PointingHandCursor)
            b.setFixedSize(24, 22)
            left, right = ("4px", "0") if i == 0 else ("0", "4px") if i == 2 else ("0", "0")
            b.setStyleSheet(f"QToolButton {{ color: {color}; font-weight: 700; border: 1px solid {COLORS['border']}; padding: 0;"
                            f" border-top-left-radius: {left}; border-bottom-left-radius: {left};"
                            f" border-top-right-radius: {right}; border-bottom-right-radius: {right}; }}"
                            f" QToolButton:checked {{ background: {COLORS['hover']}; border-color: {color}; }}")
            b.setToolTip(f"<qt><b>{to_html(words)}</b>" + (f"<br>{to_html(tip)}" if tip else "") + "</qt>")
            self.group.addButton(b, i)
            lay.addWidget(b)
        self.group.button(0).setChecked(True)
        self.group.idClicked.connect(self._clicked)

    def _clicked(self, i: int):
        if self.on_change and not self.signalsBlocked():
            self.on_change(self.VALUES[i])

    def currentData(self):
        return self.VALUES[max(0, self.group.checkedId())]

    def currentIndex(self) -> int:
        return max(0, self.group.checkedId())

    def findData(self, value) -> int:
        return self.VALUES.index(value) if value in self.VALUES else -1

    def setCurrentIndex(self, i: int):
        b = self.group.button(i if 0 <= i < len(self.VALUES) else 0)
        b.setChecked(True)
