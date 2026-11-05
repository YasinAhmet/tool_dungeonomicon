"""What can be put on the battle map, as the editor offers it: the map symbols (doors, stairs, windows, traps...) and
the props, with their names and icons, the buttons that place them (click, then a tile; or drag onto the map), and the
quick bar above the map holding the ones used most (right-click any of them to pin it there or take it off).

    AssetButton("door", compact=True)       # an icon-only button (the quick bar); compact=False: icon over its name
    quick_keys(); pin("ink_cask", True)       # the quick bar's keys, kept in the settings
"""
import json
from typing import List

from PySide6.QtCore import QMimeData, QSize, Qt
from PySide6.QtGui import QColor, QDrag, QFont, QIcon, QPainter, QPixmap, QRegion
from PySide6.QtWidgets import QHBoxLayout, QMenu, QToolButton, QWidget

from ....core.i18n import tr
from ....core.runtime import rt
from ....services.battle import props as P
from ....services.battle.drawing import SYMBOLS
from ....services.battle.sight import DOORS, SYMBOL_TERRAIN
from ...widgets.search import DRAG_MIME
from .common import battle_hub

QUICK = ("door", "locked_door", "secret_door", "stairs_up", "stairs_down", "window", "chest", "trap", "ink_cask", "ink_table",
         "ink_light", "ink_campfire")
SETTING = "quick_props"
_icons = {}


def known(key: str) -> bool:
    return key in SYMBOLS or key in P.PROPS


def name(key: str) -> str:
    return tr(P.PROPS[key][0]) if key in P.PROPS else tr(SYMBOLS[key][1]) if key in SYMBOLS else key


def tip(key: str) -> str:
    """What it does on the map: its cover, whether it blocks, light..."""
    if key in DOORS:
        return tr("cuts the walls around its tile while open (O or right-click opens and closes it)")
    if key in P.DOOR_PROPS:
        return tr("shut: fills its tile (total cover); open: cuts the walls around it (O or right-click opens and closes it)")
    if key in P.HATCHES:
        return tr("shut: nobody walks through, sight passes; open: nothing blocked (O or right-click opens and closes it)")
    if key in P.PROPS:
        return tr(next((c["tip"] for c in P.catalog() if c["key"] == key), ""))
    rules = SYMBOL_TERRAIN.get(key) or {}
    bits = [tr("{0} cover", tr(rules["cover"])) if rules.get("cover") else "", tr("blocks the tile") if rules.get("blocks") else "",
            tr("difficult terrain") if rules.get("difficult") else "", tr("light {0} ft", rules["light"][0]) if rules.get("light") else ""]
    return ", ".join(b for b in bits if b) or tr("a mark on the map")


def icon_pixmap(key: str, size: int) -> QPixmap:
    """Its picture (smoothed; empty margins cut so thin things like doors show), or
    the symbol's glyph drawn on a tile."""
    if (key, size) in _icons:
        return _icons[key, size]
    path = P.path(key)
    if path:
        pm = QPixmap(path)
        used = QRegion(pm.mask()).boundingRect() if not pm.mask().isNull() else pm.rect()
        if used.isValid() and used != pm.rect():
            side = max(used.width(), used.height())
            pm = pm.copy(used.adjusted(-(side - used.width()) // 2, -(side - used.height()) // 2,
                                       (side - used.width() + 1) // 2, (side - used.height() + 1) // 2))
        pm = pm.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation if P.smooth(key) else Qt.FastTransformation)
    else:
        pm = QPixmap(size, size)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QColor("#e6e9ef"))
        f = QFont()
        f.setPixelSize(int(size * 0.72))
        p.setFont(f)
        p.drawText(pm.rect(), Qt.AlignCenter, SYMBOLS.get(key, ("?", ""))[0])
        p.end()
    _icons[key, size] = pm
    return pm


def quick_keys() -> List[str]:
    keys = rt().settings.get(SETTING)
    keys = [P.LEGACY.get(k, k) for k in (keys if isinstance(keys, list) else QUICK) if isinstance(k, str)]
    return [k for i, k in enumerate(keys) if known(k) and k not in keys[:i]]


def pin(key: str, on: bool):
    keys = [k for k in quick_keys() if k != key] + ([key] if on else [])
    rt().settings[SETTING] = keys
    rt().save_config()
    battle_hub().quick.emit()


def pin_menu(menu: QMenu, key: str):
    if key in quick_keys():
        menu.addAction(tr("Take it off the quick bar"), lambda: pin(key, False))
    else:
        menu.addAction(tr("Pin to the quick bar above the map"), lambda: pin(key, True))


class AssetButton(QToolButton):
    """Click: the next click on the map places it (click again to stop); drag: drop it on a tile; right-click: pin."""

    def __init__(self, key: str, compact: bool = True):
        super().__init__()
        self.key = key
        n = 26 if compact else 40
        self.setIcon(QIcon(icon_pixmap(key, n)))
        self.setIconSize(QSize(n, n))
        if compact:
            self.setFixedSize(34, 32)
            self.setCheckable(True)
        else:
            self.setText(name(key))
            self.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            self.setFixedSize(86, 66)
        span = P.span(key) if key in P.PROPS else 1
        self.setToolTip(f"{name(key)}\n{tip(key)}" + (f"\n{span} × {span} tiles" if span > 1 else "")
                        + "\n\n" + tr("Click it and then a tile, or drag it onto the map. Right-click: the quick bar."))
        self.setAutoRaise(True)
        self._press = None
        self.clicked.connect(lambda: battle_hub().place.emit(self.key if not self.isCheckable() or self.isChecked() else ""))
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.customContextMenuRequested.connect(self._menu)

    def _menu(self, pos):
        m = QMenu(self)
        pin_menu(m, self.key)
        m.exec(self.mapToGlobal(pos))

    def mousePressEvent(self, e):
        self._press = e.position()
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._press is not None and (e.position() - self._press).manhattanLength() > 6:
            self._press = None
            mime = QMimeData()
            mime.setData(DRAG_MIME, json.dumps({"kind": "symbol", "sym": self.key}).encode())
            drag = QDrag(self)
            drag.setMimeData(mime)
            drag.setPixmap(icon_pixmap(self.key, 40))
            drag.exec(Qt.CopyAction)
            self.setDown(False)
            return
        super().mouseMoveEvent(e)


class QuickBar(QWidget):
    """The pinned symbols and props, then ▾ for every map symbol."""

    def __init__(self):
        super().__init__()
        self.lay = QHBoxLayout(self)
        self.lay.setContentsMargins(0, 0, 0, 0)
        self.lay.setSpacing(2)
        self.buttons: List[AssetButton] = []
        self.armed = None
        self.more = QToolButton()
        self.more.setText("▾")
        self.more.setAutoRaise(True)
        self.more.setPopupMode(QToolButton.InstantPopup)
        self.more.setToolTip(tr("Every map symbol; the props are in the drawer (🧰). Right-click any of them to pin it here."))
        menu = QMenu(self.more)
        menu.aboutToShow.connect(lambda: self._fill(menu))
        self.more.setMenu(menu)
        battle_hub().quick.connect(self.rebuild)
        self.rebuild()

    def rebuild(self):
        for b in self.buttons:
            b.setParent(None)
            b.deleteLater()
        self.lay.removeWidget(self.more)
        self.buttons = [AssetButton(k) for k in quick_keys()]
        for b in self.buttons:
            b.setChecked(b.key == self.armed)
            self.lay.addWidget(b)
        self.lay.addWidget(self.more)

    def show_armed(self, key):
        self.armed = key
        for b in self.buttons:
            b.setChecked(b.key == key)

    def _fill(self, menu: QMenu):
        menu.clear()
        pinned = set(quick_keys())
        for key in SYMBOLS:
            sub = menu.addMenu(QIcon(icon_pixmap(key, 20)), name(key) + ("  📌" if key in pinned else ""))
            sub.addAction(tr("Place it (then click a tile)"), lambda k=key: battle_hub().place.emit(k))
            pin_menu(sub, key)
        menu.addSeparator()
        menu.addAction(tr("Back to the usual quick bar"), self._reset)

    def _reset(self):
        rt().settings.pop(SETTING, None)
        rt().save_config()
        battle_hub().quick.emit()
