"""The action bar of a creature's card (and of the Battle map's play mode): what the creature can still do this turn (action, bonus action, reaction,
movement, legendary actions) and every action, feature and spell it has, grouped by what they cost. A click either
does it (Dash, Dodge, Second Wind...) or starts aiming it on the battle map (attacks, spells at creatures or points)."""
import html
import threading
from typing import Optional

from PySide6.QtCore import QObject, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPixmap
from PySide6.QtWidgets import QFrame, QLabel, QMenu, QToolButton, QVBoxLayout, QWidget

from ....core.i18n import tr
from ....core.runtime import rt
from ...errors import guard
from ...widgets.common import FlowLayout, button, combo, label
from ...widgets.icons import icon_button
from .actiontip import action_tip
from .common import HoverButton, preview_area, start_aim

COST_COLOR = {"action": "#4ade80", "attack": "#4ade80", "multi": "#4ade80", "bonus": "#fbbf24", "reaction": "#c084fc",
              "free": "#8b93a3", "legendary": "#f472b6", "move": "#8b93a3", "long": "#4ade80"}
MODES = (("Ask", "ask"), ("Always", "always"), ("Never", "never"))


class _Built(QObject):
    done = Signal()                                          # sent from the worker, handled on the screen's thread


def _divider(title: str, color: str) -> QWidget:
    """A thin bar in a group's cost colour that starts the group (its name on hover)."""
    bar = QFrame()
    bar.setFixedSize(4, ICON + 12)
    bar.setStyleSheet(f"QFrame {{ background: {color}; border-radius: 2px; margin: 6px 0; }}")
    bar.setToolTip(title)
    return bar


def _level_tag(g: dict) -> QWidget:
    """A spell level's narrow tag in the spell strip: its number (◌ for cantrips), the slots left on hover."""
    slots = g.get("slots")
    tag = QLabel(str(g["level"]) if g.get("level") else "◌")
    tag.setAlignment(Qt.AlignCenter)
    tag.setFixedSize(16, ICON + 12)
    spent = slots and not slots["left"]
    tag.setStyleSheet(f"QLabel {{ background: {'#262a33' if spent else '#3b2a55'}; color: {'#6b7280' if spent else '#e9d5ff'};"
                      f" border-radius: 3px; font-weight: 600; margin: 4px 0; }}")
    tag.setToolTip(tr(g["title"]) + (f"\n{'●' * slots['left']}{'○' * max(0, slots['total'] - slots['left'])}  "
                                     + tr("{0} of {1} slots left", slots["left"], slots["total"]) if slots else ""))
    return tag


def _flow(*widgets) -> QWidget:
    host = QWidget()
    lay = FlowLayout(host)
    for w in widgets:
        if w is not None:
            lay.addWidget(w)
    return host


class ActionBar(QWidget):
    def __init__(self, cid: int, prefs: dict, parent=None, on_pick=None, fold_spells: bool = False, hotkeys: bool = False):
        """on_pick(item): what a click does (the Play tab aims it itself); fold_spells: spells behind a Show button."""
        super().__init__(parent)
        self.cid = cid
        self.prefs = prefs
        self.on_pick = on_pick
        self.fold_spells = fold_spells
        self.spells_open = False
        self.on_fold = None                                  # called after the spells fold out or away (the box can resize)
        self.numbered = hotkeys                              # number keys pick the first nine (the map's play bar)
        self.hotkeys = []
        self.aiming = None                                   # the id of the item being aimed (shown highlighted)
        self.box = QVBoxLayout(self)
        self.box.setContentsMargins(0, 0, 0, 0)
        self.box.setSpacing(3)
        self.key = None
        self.built = _Built(self)
        self.built.done.connect(self.refresh)
        self.building = False
        self.refresh()

    def _build_later(self):
        """Build the menu on a worker thread (off the battle lock, see battle.menu); refresh when it is ready."""
        if self.building:
            return
        self.building = True
        cid, sig = self.cid, self.built

        def work():
            try:
                ok = rt().battle.available_actions(cid) is not None
            except Exception:                                # gone from the battle: nothing to show
                ok = False
            self.building = False
            if ok:
                try:
                    sig.done.emit()
                except RuntimeError:                         # the bar was closed meanwhile
                    pass
        threading.Thread(target=work, daemon=True, name="action-bar").start()

    def refresh(self):
        if self.key is None:                                 # a new bar: filled at once
            a = guard(rt().battle.available_actions, self.cid)
        else:                                                # after a change: built on a worker, the screen keeps going
            a = rt().battle.cached_actions(self.cid)
            if a is None:
                self._build_later()
                return
        if not a:
            return
        key = repr((a["turn"], [(i["id"], i["ok"], i.get("uses")) for g in a["groups"] for i in g["items"]],
                    [(i["id"], i["ok"], i.get("uses"), i.get("readied")) for g in a["spells"] for i in g["items"]], a["reactions"], a["concentrating"],
                    a["is_turn"], a["economy"], [(g["level"], (g.get("slots") or {}).get("left")) for g in a["spells"]],
                    [(t["key"], t["on"]) for t in a.get("toggles") or []]))
        key += repr((self.spells_open, self.aiming))
        if key == self.key:
            return
        self.key = key
        while self.box.count():
            w = self.box.takeAt(0).widget()
            if w:
                w.hide()
                w.deleteLater()
        t = a["turn"]

        def pip(text, n, color):
            on = n > 0
            return f"<span style='color:{color if on else '#3a3f4b'}'>●</span> <span style='color:{'#e6e9ef' if on else '#6b7280'}'>{html.escape(text)}</span>"
        bits = [pip(tr("Action") + (f" ×{t['action']}" if t.get("action", 0) > 1 else ""), t.get("action", 0), "#4ade80"),
                pip(tr("Bonus"), t.get("bonus", 0), "#fbbf24"), pip(tr("Reaction"), t.get("reaction", 0), "#c084fc"),
                f"🦶 {min(t.get('move', 0), a['speed'])}/{a['speed']} {tr('ft')}"]          # (speed 0 mid-turn: nothing left)
        if t.get("attacks"):
            bits.append(f"<span style='color:#7c8cff'>{html.escape(tr('{0} more attack(s)', t['attacks']))}</span>")
        if t.get("multi"):
            bits.append(f"<span style='color:#7c8cff'>{html.escape(tr('Multiattack: {0} left', t['multi']))}</span>")
        if t.get("legendary_max"):
            bits.append(f"<span style='color:#f472b6'>★ {t.get('legendary', 0)}/{t['legendary_max']}</span>")
        if a["concentrating"]:
            bits.append(f"<span style='color:#fbbf24'>◎ {html.escape(tr(a['concentrating']))}</span>")
        if not a.get("in_combat", True):
            bits.append(f"<span style='color:#8b93a3'>{html.escape(tr('(out of combat: full budget for every action)'))}</span>")
        elif not a["economy"]:
            bits.append(f"<span style='color:#8b93a3'>{html.escape(tr('(action economy off)'))}</span>")
        head = label("  ".join(bits))
        head.setTextFormat(Qt.RichText)
        head.setToolTip(tr("Right-click to give a spent action back"))
        head.setContextMenuPolicy(Qt.CustomContextMenu)
        head.customContextMenuRequested.connect(lambda _p: self._refund_menu(head))
        self.box.addWidget(head)
        strip = []                       # every group in one wrapping strip, a thin bar in the group's cost colour before each
        self.hotkeys = [i for g in a["groups"] if g["key"] != "reaction" for i in g["items"]][:9] if self.numbered else []
        for n, i in enumerate(self.hotkeys, 1):
            i["hotkey"] = n
        for g in a["groups"]:
            if g["key"] == "reaction" and all(not i["ok"] for i in g["items"]):
                continue
            strip.append(_divider(tr(g["title"]), COST_COLOR.get(g["key"], COST_COLOR["free"])))
            strip += [self._button(i) for i in g["items"]]
        if a["spells"] and self.fold_spells:
            strip.append(_divider(tr("Spells"), "#c084fc"))
            fold = icon_button("spell-book", self._fold, tr("Hide spells") if self.spells_open else tr("Show spells"),
                               checked=self.spells_open, color="#c084fc", size=ICON - 6)
            fold.setFixedSize(ICON + 12, ICON + 12)
            strip.append(fold)
        if strip:
            self.box.addWidget(_flow(*strip))
        if a["spells"] and (self.spells_open or not self.fold_spells):    # one strip: a level tag (slots on hover) before each level
            self.box.addWidget(_flow(*[w for g in a["spells"] for w in [_level_tag(g)] + [self._button(i, spell=True) for i in g["items"]]]))
        if a.get("toggles"):
            self.box.addWidget(_flow(label(tr("Feats") + ":", role="dim"), *[self._toggle(a["character"], t) for t in a["toggles"]]))
        if a["reactions"]:
            self.box.addWidget(_flow(_divider(tr("Reactions"), COST_COLOR["reaction"]), *[self._reaction(r) for r in a["reactions"]]))

    def _reaction(self, r: dict) -> QWidget:
        """A reaction's setting: its picture with a mark (? ask, ✓ always, ✕ never); a click picks another."""
        words = {v: tr(t_) for t_, v in MODES}
        tip = (f"{tr(r['label'])}: {words[r['mode']]}\n" + tr("Ask: you decide each time · Always: by itself · Never: skipped"))
        b = icon_button(r.get("icon") or "", tip=tip, color={"ask": "#d8b4fe", "always": "#4ade80", "never": "#5b6170"}[r["mode"]],
                        size=20, text={"ask": "?", "always": "✓", "never": "✕"}[r["mode"]], fallback=tr(r["label"]))
        menu = QMenu(b)
        for v, word in words.items():
            act = menu.addAction(word, lambda v=v: guard(rt().battle.set_reaction_mode, self.cid, r["family"], v))
            act.setCheckable(True)
            act.setChecked(v == r["mode"])
        b.setMenu(menu)
        b.setPopupMode(QToolButton.InstantPopup)
        b.setStyleSheet(b.styleSheet() + " QToolButton::menu-indicator { image: none; width: 0; }")
        return b

    def _button(self, item: dict, spell: bool = False) -> QWidget:
        uses = item.get("uses") if item.get("uses") not in (None, "") else None
        pix = icon_pixmap(item.get("icon"), uses)
        text = "" if pix else tr(item["name"]) + (f" ({uses})" if uses else "")
        b = HoverButton(text, lambda: self._go(item))
        area = spell and item.get("area")
        b._enter = lambda: (action_tip().show_for(b, item), preview_area(item["name"]) if area else None)
        b._leave = lambda: (action_tip().hide_for(b), preview_area(None) if area else None)
        color = "#c084fc" if spell else COST_COLOR.get((item.get("cost") or "action").split(":")[0], "#4ade80")
        if not item["ok"]:
            color = "#3a3f4b"                                # not usable now: no cost colour
        lit = "background: #4b52a8;" if self.aiming == item["id"] else "background: #5b3a85;" if item.get("readied") else ""
        if pix:
            b.setIcon(QIcon(pix))
            b.setIconSize(QSize(ICON, ICON))
            b.setFixedSize(ICON + 12, ICON + 12)
            b.setStyleSheet(f"QPushButton {{ border: 1px solid #262c37; border-bottom: 3px solid {color}; border-radius: 6px; padding: 0;"
                            f" background: qlineargradient(x1:0, y1:0, x2:0, y2:1, stop:0 #262e40, stop:1 #161a21); {lit} }}"
                            f" QPushButton:hover {{ background: #323c55; }} QPushButton:disabled {{ background: #12151b; border-bottom-color: #3a3f4b; }}")
        else:
            b.setStyleSheet(f"border-left: 3px solid {color}; padding: 1px 6px; {lit}")
        b.setEnabled(True)                                   # disabled buttons get no hover events; a click on one just explains why
        if not item["ok"]:
            b.setStyleSheet(b.styleSheet() + " QPushButton { color: #6b7280; }")
            if pix:
                b.setIcon(QIcon(_dimmed(pix)))
        return b

    def _toggle(self, character: str, t: dict) -> QWidget:
        """A situational feat's switch (the same one as on the character sheet)."""
        from ...panels.characters.sheet_overview import toggle_tip
        from ...panels.characters.sheet_widgets import rich_tip
        if t["kind"] == "option":
            return combo([(tr("{0}: off", tr(t["label"])), "")] + [(f"{tr(t['label'])}: {tr(o)}", o) for o in t["options"]],
                         current=t["on"] or "", on_change=lambda v: guard(rt().characters.set_toggle, character, t["key"], v or False),
                         tip=rich_tip(toggle_tip(t)))
        b = button(("● " if t["on"] else "○ ") + tr(t["label"]), lambda: guard(rt().characters.set_toggle, character, t["key"], not t["on"]),
                   checkable=True)
        b.setChecked(bool(t["on"]))
        b.setToolTip(rich_tip(toggle_tip(t)))
        color = {"power": "#f87171", "reaction": "#c084fc"}.get(t["kind"], "#7c8cff")
        b.setStyleSheet(f"border-left: 3px solid {color}; padding: 1px 6px;")
        return b

    def _fold(self):
        self.spells_open = not self.spells_open
        self.refresh()
        if self.on_fold:
            self.on_fold()

    def set_aiming(self, item_id):
        self.aiming = item_id
        self.refresh()

    def _go(self, item: dict):
        action_tip().hide()
        if not item.get("ok", True):
            from ... import notify
            notify.warn(tr(item.get("why") or "Not now"))
            return
        if self.on_pick:
            self.on_pick(item)
            return
        start_aim(self, self.cid, item, item.get("level") if item.get("kind") == "spell" else None, self.prefs.get("adv"))

    def _refund_menu(self, anchor: QWidget):
        from PySide6.QtGui import QCursor
        from PySide6.QtWidgets import QMenu
        m = QMenu(anchor)
        for text, cost in ((tr("Give the action back"), "action"), (tr("Give the bonus action back"), "bonus"),
                           (tr("Give the reaction back"), "reaction"), (tr("Give the movement back"), "move")):
            m.addAction(text, lambda c=cost: guard(rt().battle.refund, self.cid, c))
        m.exec(QCursor.pos())


ICON = 30
COST_WORD = {"action": "Action", "attack": "Action", "multi": "Action", "bonus": "Bonus action", "reaction": "Reaction", "free": "Free",
             "legendary": "Legendary action", "move": "Movement", "long": "Takes longer than a turn",
             "on_hit": "On hit"}
_pixmaps = {}


def icon_pixmap(slug: Optional[str], uses=None) -> Optional[QPixmap]:
    """The action's icon (the icon modules), with how many uses are left in a corner badge; None when there is none."""
    from ....services.battle import icons
    path = icons.path(slug) if slug else None
    if not path:
        return None
    key = (slug, str(uses) if uses is not None else None)
    if key in _pixmaps:
        return _pixmaps[key]
    pm = QPixmap(path).scaled(ICON, ICON, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    if uses is not None:
        p = QPainter(pm)
        f = QFont()
        f.setPixelSize(10)
        f.setBold(True)
        p.setFont(f)
        text = str(uses)
        w = p.fontMetrics().horizontalAdvance(text) + 4
        rect = QRectF(ICON - w, ICON - 12, w, 12)
        p.fillRect(rect, QColor(15, 17, 21, 220))
        p.setPen(QColor("#e6e9ef"))
        p.drawText(rect, Qt.AlignCenter, text)
        p.end()
    _pixmaps[key] = pm
    return pm


def _dimmed(pm: QPixmap) -> QPixmap:
    out = QPixmap(pm.size())
    out.fill(Qt.transparent)
    p = QPainter(out)
    p.setOpacity(0.32)
    p.drawPixmap(0, 0, pm)
    p.end()
    return out
