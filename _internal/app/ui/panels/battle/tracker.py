"""The Battle map's initiative band under the map: the battle's name, status, round and difficulty with the controls of
each stage (add players, roll initiative, saved encounters, start, next/previous turn, end with XP, new battle) on one
line, and under it the initiative order as a row of tokens, left to right. Tokens are dragged to reorder (or onto the
map to place them), a double-click sets the initiative (on the hit point bar: damage or healing), right-click opens
their menu - for every selected token at once (Ctrl/Shift-click to select several: one Fireball's damage, a condition
on the whole party). A click selects the creature: its card shows in the Inspector."""
import html
import json

from PySide6.QtCore import QMimeData, QRect, QSize, Qt, QTimer
from PySide6.QtGui import QColor, QDrag, QPainter, QPen
from PySide6.QtWidgets import (QAbstractItemView, QHBoxLayout, QListView, QListWidget, QListWidgetItem, QMenu, QSizePolicy,
                               QSlider, QStyle, QStyledItemDelegate, QToolButton, QWidget)

from ....core import events
from ....core.i18n import tr
from ....core.runtime import rt
from ....services.battle import view as V
from ....services.battle.icons import BADGES
from ... import dialogs, notify
from ...errors import guard
from ...panel import Panel
from ...selection import hub
from ...theme import COLORS
from ...widgets.common import FlowLayout, button, clear_layout, label, row
from ...widgets.icons import game_pixmap, icon_button
from ...widgets.search import DRAG_MIME
from .common import (TURN, add_players, attempt, combatant_menu, hp_color, hp_change, next_turn, token, token_card, undo)

ROLE = Qt.UserRole
CELL_W, CELL_H, TOKEN = 60, 74, 40                     # one creature of the order: its token, hit points and name
INIT_BOX = QRect(2, 2, 20, 14)                         # (the initiative badge, top left of a cell)


def _portal_players() -> dict:
    """{character: (player's name, their portal page is open)} while the portal runs ({} when it doesn't)."""
    from ....services.portal.controller import portal
    if not portal.running:
        return {}
    seen = portal.presence()
    out = {}
    for uid, pl in rt().players.all().items():
        for name in rt().characters.characters_of(uid):
            out[name] = (pl.get("name") or str(uid), bool((seen.get(int(uid)) or {}).get("online")))
    return out


def _hp_rect(cell: QRect) -> QRect:
    """The hit point bar of a cell, under its token."""
    return QRect(cell.left() + 7, cell.top() + 4 + TOKEN + 4, cell.width() - 14, 5)


class TokenDelegate(QStyledItemDelegate):
    """A creature of the order: its token (faded when out) with its initiative, its conditions' pictures and a portal
    player's dot on it, a hit point bar under it and its name. Whose turn it is is framed in gold, a target is red."""

    def __init__(self, strip: "OrderStrip"):
        super().__init__(strip)
        self.strip = strip

    def sizeHint(self, _opt, _index):
        return QSize(CELL_W, CELL_H)

    def paint(self, p: QPainter, opt, index):
        c = index.data(ROLE)
        if not c:
            return super().paint(p, opt, index)
        r = opt.rect.adjusted(1, 1, -1, -1)
        v = self.strip.owner.v or {}
        turn = v.get("turn") == c["id"]
        chosen = bool(opt.state & QStyle.State_Selected)
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        back = QColor(COLORS["accent_dim"]) if chosen else QColor(120, 40, 40) if c["id"] in (v.get("picked") or []) else \
            QColor(COLORS["hover"]) if opt.state & QStyle.State_MouseOver else QColor(COLORS["raised"])
        p.setPen(QPen(QColor(TURN), 2) if turn else QPen(QColor(COLORS["border"]), 1))
        p.setBrush(back)
        p.drawRoundedRect(r, 5, 5)
        tx = r.left() + (r.width() - TOKEN) // 2
        ty = r.top() + 3
        p.setOpacity(0.4 if c.get("out") else 1.0)
        p.drawPixmap(tx, ty, token(c, TOKEN))
        p.setOpacity(1.0)
        f = p.font()                                         # the initiative, top left ("?" while there is none)
        f.setPixelSize(10)
        f.setBold(True)
        p.setFont(f)
        box = INIT_BOX.translated(opt.rect.topLeft())
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 190))
        p.drawRoundedRect(box, 4, 4)
        p.setPen(QColor(TURN if turn else COLORS["warn"] if c["init"] is None else COLORS["text"]))
        p.drawText(box, Qt.AlignCenter, "?" if c["init"] is None else str(c["init"]))
        if c.get("_online") is not None:                     # a portal player's character: is their page open?
            p.setPen(QPen(QColor(0, 0, 0, 200), 1))
            p.setBrush(QColor(COLORS["good"] if c["_online"] else "#4b5263"))
            p.drawEllipse(r.right() - 9, r.top() + 3, 7, 7)
        x = tx + TOKEN - 12                                  # conditions and effects with a picture, at the token's foot
        for e in reversed([e for e in c.get("extra") or [] if BADGES.get(e)][:3]):
            pm = game_pixmap(e, 12, BADGES[e][1])
            if pm:
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(0, 0, 0, 200))
                p.drawEllipse(x - 1, ty + TOKEN - 13, 14, 14)
                p.drawPixmap(x, ty + TOKEN - 12, pm)
                x -= 11
        bar = _hp_rect(opt.rect)                             # hit points (temporary ones: a blue line on top)
        frac = max(0.0, min(1.0, c["hp"] / c["max_hp"])) if c["max_hp"] else 0.0
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(COLORS["input"]))
        p.drawRoundedRect(bar, 2, 2)
        if frac > 0:
            p.setBrush(QColor(hp_color(frac)))
            p.drawRoundedRect(QRect(bar.left(), bar.top(), max(3, int(bar.width() * frac)), bar.height()), 2, 2)
        if c.get("temp_hp"):
            p.setBrush(QColor("#5aa9ff"))
            p.drawRoundedRect(QRect(bar.left(), bar.top(), bar.width(), 2), 1, 1)
        f.setBold(c["kind"] == "pc")                         # the name
        p.setFont(f)
        p.setPen(QColor(COLORS["dim"] if c.get("out") else COLORS["accent"] if c["kind"] == "pc" else COLORS["text"]))
        name_box = QRect(r.left() + 2, bar.bottom() + 2, r.width() - 4, r.bottom() - bar.bottom() - 2)
        p.drawText(name_box, Qt.AlignCenter, p.fontMetrics().elidedText(c["name"], Qt.ElideRight, name_box.width()))
        p.restore()


class OrderStrip(QListWidget):
    """The initiative order as tokens left to right. Drag one to a new place (or onto the map); drop a library creature
    to add it. The wheel scrolls it sideways."""

    def __init__(self, owner: "TrackerPanel"):
        super().__init__()
        self.owner = owner
        self.drop_x = None
        self.setViewMode(QListView.ListMode)
        self.setFlow(QListView.LeftToRight)
        self.setWrapping(False)
        self.setUniformItemSizes(True)
        self.setSpacing(2)
        self.setMouseTracking(True)
        self.setHorizontalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAsNeeded)
        self.horizontalScrollBar().setStyleSheet("QScrollBar:horizontal { height: 6px; }")
        self.setFixedHeight(CELL_H + 4 + 2 * self.frameWidth() + 6)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDragDropMode(QAbstractItemView.DragDrop)
        self.setContextMenuPolicy(Qt.CustomContextMenu)
        self.setItemDelegate(TokenDelegate(self))
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)

    @staticmethod
    def cid(it):
        c = it.data(ROLE) if it else None
        return c["id"] if c else None

    def items(self):
        return [self.item(n) for n in range(self.count())]

    def wheelEvent(self, e):
        d = e.angleDelta()
        sb = self.horizontalScrollBar()
        sb.setValue(sb.value() - (d.y() if abs(d.y()) > abs(d.x()) else d.x()))
        e.accept()

    def mouseDoubleClickEvent(self, e):
        pos = e.position().toPoint()
        it = self.itemAt(pos)
        c = it.data(ROLE) if it else None
        if not c or e.button() != Qt.LeftButton:
            return super().mouseDoubleClickEvent(e)
        if _hp_rect(self.visualItemRect(it)).adjusted(-3, -3, 3, 3).contains(pos):
            guard(hp_change, self.owner, c["id"], "damage", c["name"])
        else:
            self.owner.ask_initiative(c)
        e.accept()

    # ---- dragging tokens out
    def startDrag(self, _actions):
        it = self.currentItem()
        c = it and it.data(ROLE)
        if not c:
            return
        mime = QMimeData()
        mime.setData(DRAG_MIME, json.dumps({"kind": "combatant", "id": c["id"]}).encode())
        mime.setText(c["name"])
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.setPixmap(token(c, 32))
        drag.exec(Qt.MoveAction | Qt.CopyAction)
        self._clear_line()

    # ---- drops: reorder or add
    def _index_at(self, x: int) -> int:
        return sum(1 for it in self.items() if x > self.visualItemRect(it).center().x())

    def dragEnterEvent(self, e):
        if e.mimeData().hasFormat(DRAG_MIME):
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        if not e.mimeData().hasFormat(DRAG_MIME):
            return
        e.acceptProposedAction()
        i = self._index_at(int(e.position().x()))
        n = self.count()
        if not n:
            self.drop_x = 2
        elif i >= n:
            self.drop_x = self.visualItemRect(self.item(n - 1)).right() + 1
        else:
            self.drop_x = self.visualItemRect(self.item(i)).left() - 1
        self.viewport().update()

    def dragLeaveEvent(self, _e):
        self._clear_line()

    def _clear_line(self):
        self.drop_x = None
        self.viewport().update()

    def dropEvent(self, e):
        idx = self._index_at(int(e.position().x()))
        self._clear_line()
        try:
            payload = json.loads(bytes(e.mimeData().data(DRAG_MIME)).decode())
        except ValueError:
            return
        e.acceptProposedAction()
        b = self.owner.rt.battle
        if payload.get("kind") == "monster":
            if guard(b.add_enemy, payload["id"], int(payload.get("count") or 1), None, payload.get("hp_mode") or "average",
                     None, True):
                notify.good(tr("Added to the battle."))
        elif payload.get("kind") == "combatant":
            ids = [self.cid(it) for it in self.items()]
            if payload["id"] in ids and ids.index(payload["id"]) < idx:
                idx -= 1
            if payload["id"] not in ids or ids.index(payload["id"]) != idx:
                guard(b.move, payload["id"], idx)

    def paintEvent(self, e):
        super().paintEvent(e)
        p = QPainter(self.viewport())
        if not self.count():                                 # nothing yet: how to fill it
            p.setPen(QColor(COLORS["dim"]))
            p.drawText(self.viewport().rect().adjusted(8, 0, -8, 0), Qt.AlignCenter | Qt.TextWordWrap,
                       tr("Add your players, then drag creatures here (or onto the map) from the drawer beside the map or "
                          "the Library."))
        if self.drop_x is not None:
            p.setPen(QPen(QColor(COLORS["accent"]), 2))
            p.drawLine(self.drop_x, 2, self.drop_x, self.viewport().height() - 2)
        p.end()


class TrackerPanel(Panel):
    def build(self):
        self.v = None
        self.stage = None
        self.in_play = False
        self.group = True
        self.last_turn = None
        self.top = self.layout()
        self.top.setContentsMargins(0, 0, 0, 0)
        self.top.setSpacing(2)
        self.name = label("")
        f = self.name.font()
        f.setBold(True)
        self.name.setFont(f)
        self.status = label("", role="dim")
        self.diff = label("", role="dim")
        self.controls_host = QWidget()                       # (wraps under itself when the band is narrow)
        self.controls = FlowLayout(self.controls_host)
        self.head = row(self.name, icon_button("edit", self._rename, tr("Rename the battle"), size=14), self.status, self.diff,
                        8, self.controls_host)               # the Battle map adds its fold button at the end
        self.head.setStretchFactor(self.controls_host, 1)
        self.top.addLayout(self.head)
        self.tree = OrderStrip(self)
        self.tree.currentItemChanged.connect(lambda cur, _prev: self._picked(cur))
        self.tree.customContextMenuRequested.connect(self._menu)
        self.top.addWidget(self.tree)
        self.reveal_all = self.undo_btn = None                # made with the controls (their row of pictures)
        hub().combatant.connect(self._focus)
        self.on(events.BATTLE, self.refresh)
        self.on(events.CHARACTERS, self.refresh)
        self.on(events.PORTAL, self.refresh)                 # a player's page opened or closed: their dot

    # ------------------------------------------------------------------ drawing
    def refresh(self):
        v = self.v = V.battle_view()
        n = V.counts(v)
        self.name.setText(v["name"])
        bits = [tr(V.STATUS[v["status"]])]
        if v["status"] == "active":
            bits.append(tr("Round {0}", v["round"]))
        bits.append(tr("{0} players, {1} enemies", n["pcs"], n["enemies"]))
        self.status.setText(" · ".join(bits))
        d = v["difficulty"]
        if d.get("rating"):
            self.diff.setText(tr("{0} encounter · {1} XP", tr(d["rating"]), f"{d['xp']:,}"))
            self.diff.setProperty("role", {"Deadly": "bad", "Hard": "warn", "Easy": "good", "Trivial": "dim"}.get(d["rating"], "accent"))
            self.diff.setToolTip(tr("Encounter difficulty") + "\n" + tr("Adjusted XP {0}", f"{d['adjusted']:,}") + "\n" +
                                 "\n".join(f"{tr(k)}: {x:,} XP" for k, x in (d.get("thresholds") or {}).items()))
        else:
            self.diff.setText(tr("{0} XP", f"{d['xp']:,}") if d.get("xp") else "")
            self.diff.setProperty("role", "dim")
            self.diff.setToolTip("")
        self.diff.style().polish(self.diff)
        self._controls(v)
        self._order(v)
        self.reveal_all.blockSignals(True)
        self.reveal_all.setChecked(bool(v.get("reveal_hp")))
        self.reveal_all.blockSignals(False)
        label_ = getattr(self.rt.battle, "undo_label", None)
        what = guard(label_) if label_ else None
        self.undo_btn.setToolTip(tr("Undo") + "\n" + (tr("Take back: {0}", tr(what)) + " (Ctrl+Z)" if what else tr("Take back the last change (Ctrl+Z)")))

    def _controls(self, v: dict):
        s = v.get("summary") or {}
        enemies = any(c["kind"] == "enemy" for c in v["combatants"])
        missing = any(c["init"] is None and not c.get("out") for c in v["combatants"])
        stage = (v["status"], bool(s.get("xp") and not s.get("awarded")), json.dumps(s, sort_keys=True), self._unplaced(v),
                 enemies, missing)                          # (Clear enemies and Roll missing show only when they'd do something)
        if stage == self.stage:
            self._sync_dice()
            return
        self.stage = stage
        clear_layout(self.controls)
        add = lambda w: w is not None and self.controls.addWidget(w)  # noqa: E731 - None: nothing to show (no unplaced tokens)
        if v["status"] == "ended":                           # how it went; then out of combat, free like setting up
            add(label(tr("{0} round(s) · {1} enemies defeated · {2} XP", s.get("rounds", 0), len(s.get("defeated") or []),
                         f"{s.get('xp', 0):,}") + (tr(" ({0} each, awarded)", s.get("share")) if s.get("awarded") else ""),
                      role="good"))
            if s.get("xp") and not s.get("awarded"):
                add(button(tr("Award XP to party"), self._award, kind="primary"))
            add(button(tr("New battle"), self._new_battle, tip=tr("A fresh battle with the same party: the enemies and the log go")))
        if v["status"] != "active":                         # one main button, then pictures with their words on hover
            add(button(tr("▶ Start battle"), self._start, kind="primary", tip=tr("Roll what's missing and start round 1")))
            add(icon_button("add_players", self._add_players, tr("Add players…") + "\n" + tr("Bring party members into the battle"),
                            color=COLORS["accent"]))
            add(self._roll_button())
            add(self._place_button(v))
            add(self._encounters_button())
            if enemies:
                add(icon_button("clear", self._clear_enemies, tr("Clear enemies") + "\n" + tr("Take every enemy out (Ctrl+Z brings them back)"),
                                color=COLORS["bad"]))
            add(self._rules_button())
            add(self._dice_controls())
        elif v["status"] == "active":
            if not self.in_play:                             # the map's play bar has its own Next turn
                add(button(tr("Next turn ▶"), lambda: next_turn(self), kind="primary", tip=tr("End this turn (Ctrl+Space)")))
            add(icon_button("previous_turn", lambda: self.run(self.rt.battle.previous_turn),
                            tr("Back") + "\n" + tr("Back to the previous turn (Ctrl+Shift+Space)")))
            if missing:
                add(icon_button("roll", lambda: self._roll("missing"), tr("Roll missing") + "\n" + tr("Roll initiative for those who have none"),
                                color=COLORS["warn"]))
            add(icon_button("add_players", self._add_players, tr("Add players…") + "\n" + tr("Bring party members into the battle"),
                            color=COLORS["accent"]))
            add(self._place_button(v))
            add(self._rules_button())
            add(self._dice_controls())
            add(icon_button("end_battle", self._end, tr("End battle") + "\n" + tr("Count the XP and end the fight"), color=COLORS["bad"]))
        self.reveal_all = icon_button("reveal", None, tr("Show exact enemy HP to players") + "\n" +
                                      tr("Players see every enemy's hit points instead of Healthy / Wounded / Bloodied"),
                                      checked=False, color=COLORS["warn"])
        self.reveal_all.toggled.connect(self._reveal_all)
        self.undo_btn = icon_button("undo", undo, "")
        add(self.reveal_all)
        add(self.undo_btn)

    def _roll_button(self) -> QToolButton:
        """Roll initiative: for whom, and whether copies of a monster share one roll."""
        b = icon_button("roll", None, tr("Roll initiative") + "\n" + tr("Everyone, the enemies, the players or only those missing"),
                        color=COLORS["warn"])
        b.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(b)
        for text, scope in ((tr("Everyone"), "all"), (tr("Enemies only"), "enemies"), (tr("Players only"), "players"),
                            (tr("Only those missing"), "missing")):
            menu.addAction(text, lambda sc=scope: self._roll(sc))
        menu.addSeparator()
        same = menu.addAction(tr("Same creatures together"), lambda: setattr(self, "group", not self.group))
        same.setCheckable(True)
        same.setChecked(self.group)
        same.setToolTip(tr("Copies of one monster share one initiative roll"))
        menu.setToolTipsVisible(True)
        menu.aboutToShow.connect(lambda: same.setChecked(self.group))
        b.setMenu(menu)
        return b

    def set_play(self, on: bool):
        """The Battle map is in play mode: its bar over the map has the Next turn button."""
        if on != self.in_play:
            self.in_play = on
            self.stage = None
            if self.v is not None:
                guard(self.refresh)

    def _rules_button(self) -> QToolButton:
        """The battle's rules: the action economy, how creatures react (BG3's Ask / Always / Never), the light."""
        b = icon_button("rules", None, tr("Rules") + "\n" + tr("Action economy, reactions, death saves and light for this battle"))
        b.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(b)
        menu.aboutToShow.connect(lambda: self._fill_rules(menu))
        b.setMenu(menu)
        return b

    # Async rolling: the slider goes from slow (3.5 s of rolling) to fast (0.8 s)
    @staticmethod
    def _seconds(speed: int) -> float:
        return round(3.5 - 0.3 * (speed - 1), 2)

    @staticmethod
    def _speed(seconds: float) -> int:
        return max(1, min(10, round((3.5 - float(seconds)) / 0.3) + 1))

    def _dice_controls(self) -> QWidget:
        """The Async rolling tick and its speed: players' attack rolls, saves and death saves roll on every screen."""
        r = self.rt.battle.rules_view()
        host = QWidget()
        lay = QHBoxLayout(host)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        self.dice_box = icon_button("async_dice", lambda: self.run(self.rt.battle.set_rule, "async_rolls", self.dice_box.isChecked()),
                                    tr("Async rolling") + "\n" +
                                    tr("Players' attack rolls, saving throws and death saves roll as a d20 on every screen "
                                       "(yours and the players'), and the action goes on when the die stops. Monsters roll at once."),
                                    checked=bool(r["async_rolls"]), color=COLORS["accent"])
        self.dice_slider = QSlider(Qt.Horizontal)
        self.dice_slider.setRange(1, 10)
        self.dice_slider.setFixedWidth(60)
        self.dice_slider.setVisible(bool(r["async_rolls"]))       # the speed only matters while the dice roll on screen
        self.dice_slider.setValue(self._speed(r["roll_seconds"]))
        self._dice_tip()
        self.dice_wait = QTimer(host)                      # set the rule once the slider rests, not on every step
        self.dice_wait.setSingleShot(True)
        self.dice_wait.setInterval(300)
        self.dice_wait.timeout.connect(lambda: self.run(self.rt.battle.set_rule, "roll_seconds", self._seconds(self.dice_slider.value())))
        self.dice_slider.valueChanged.connect(lambda _v: (self._dice_tip(), self.dice_wait.start()))
        lay.addWidget(self.dice_box)
        lay.addWidget(self.dice_slider)
        return host

    def _dice_tip(self):
        self.dice_slider.setToolTip(tr("How fast the dice roll: {0} s on screen", f"{self._seconds(self.dice_slider.value()):.1f}"))

    def _sync_dice(self):
        box = getattr(self, "dice_box", None)
        try:
            if box is None:
                return
            r = self.rt.battle.rules_view()
            box.blockSignals(True)
            box.setChecked(bool(r["async_rolls"]))
            box.blockSignals(False)
            self.dice_slider.setVisible(bool(r["async_rolls"]))
            if not self.dice_slider.isSliderDown() and not self.dice_wait.isActive():
                self.dice_slider.blockSignals(True)
                self.dice_slider.setValue(self._speed(r["roll_seconds"]))
                self.dice_slider.blockSignals(False)
                self._dice_tip()
        except RuntimeError:                               # the controls were rebuilt (their Qt objects are gone)
            self.dice_box = None

    def _fill_rules(self, menu: QMenu):
        menu.clear()
        r = self.rt.battle.rules_view()
        act = menu.addAction(tr("Enforce the action economy"), lambda: self.run(self.rt.battle.set_rule, "economy", not r["economy"]))
        act.setCheckable(True)
        act.setChecked(bool(r["economy"]))
        act = menu.addAction(tr("Roll death saves at the start of a downed character's turn"),
                             lambda: self.run(self.rt.battle.set_rule, "auto_death_saves", not r["auto_death_saves"]))
        act.setCheckable(True)
        act.setChecked(bool(r["auto_death_saves"]))
        for key, title in (("npc_reactions", tr("Monsters react")), ("pc_reactions", tr("Players react"))):
            sub = menu.addMenu(title)
            for text, mode in ((tr("By themselves (always)"), "always"), (tr("Ask each time"), "ask"), (tr("Never"), "never")):
                a = sub.addAction(text, lambda k=key, m=mode: self.run(self.rt.battle.set_rule, k, m))
                a.setCheckable(True)
                a.setChecked(r[key] == mode)
        sub = menu.addMenu(tr("Players' time to answer a reaction"))
        for text, secs in ((tr("No limit"), 0), (tr("30 seconds"), 30), (tr("1 minute"), 60), (tr("2 minutes"), 120)):
            a = sub.addAction(text, lambda s=secs: self.run(self.rt.battle.set_rule, "react_timeout", s))
            a.setCheckable(True)
            a.setChecked(int(r.get("react_timeout") or 0) == secs)
        sub = menu.addMenu(tr("Light on the map"))
        for text, mode in ((tr("Bright"), "bright"), (tr("Dim"), "dim"), (tr("Dark"), "dark")):
            a = sub.addAction(text, lambda m=mode: self.run(self.rt.battle.set_rule, "light", m))
            a.setCheckable(True)
            a.setChecked(r["light"] == mode)

    def _order(self, v: dict):
        t = self.tree
        keep = t.horizontalScrollBar().value()
        cur = t.cid(t.currentItem())
        chosen = {t.cid(i) for i in t.selectedItems()}
        t.blockSignals(True)
        t.clear()
        picked = set(v.get("picked") or [])
        players = _portal_players()
        for c in v["combatants"]:
            who = players.get(c.get("character") or "")
            c["_online"] = who[1] if who else None            # (the token's dot)
            it = QListWidgetItem()
            it.setData(ROLE, c)
            it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsDragEnabled)
            more = [tr(x) for x in c.get("extra") or [] if x in ("ally", "neutral", "dead", "stable", "down!")] +                 [tr("Initiative {0}", c["init"]) if c["init"] is not None else tr("No initiative yet"),
                 tr("Notes: {0}", c["notes"]) if c.get("notes") else "", tr("🎯 Target") if c["id"] in picked else "",
                 tr("Not on the map") if not c.get("pos") else "",
                 (tr("{0} has the portal open", who[0]) if who[1] else tr("{0} isn't on the portal", who[0])) if who else ""]
            # (the map's hover card, what only the order knows, and what a double-click does)
            card = token_card(v, c)[:-len("</qt>")] + "".join(f"<br>{html.escape(x)}" for x in more if x) +                 f"<br><span style='color:{COLORS['dim']}'>" + html.escape(tr("Double-click to set the initiative")) + "</span></qt>"
            it.setToolTip(card)
            t.addItem(it)
            if c["id"] == cur:
                t.setCurrentItem(it)
            if c["id"] in chosen:
                it.setSelected(True)
        t.blockSignals(False)
        t.horizontalScrollBar().setValue(keep)
        if v.get("turn") != self.last_turn:                 # a new turn: bring its token into view
            self.last_turn = v.get("turn")
            for it in t.items():
                if t.cid(it) == v.get("turn"):
                    t.scrollToItem(it)
        t.viewport().update()

    # ------------------------------------------------------------------ tokens
    def _picked(self, it):
        cid = self.tree.cid(it)
        if cid:
            hub().combatant.emit(cid)

    def _focus(self, cid: int):
        t = self.tree
        if t.cid(t.currentItem()) == (cid or None):
            return
        t.blockSignals(True)
        t.setCurrentItem(None)
        for it in t.items():
            if t.cid(it) == cid:
                t.setCurrentItem(it)
                t.scrollToItem(it)
        t.blockSignals(False)
        t.viewport().update()

    def ask_initiative(self, c: dict):
        """Set (or clear) a creature's initiative by hand."""
        text = dialogs.ask_text(self, tr("Set initiative here…").rstrip("…"), c["name"], "" if c["init"] is None else str(c["init"]))
        if text is None:
            return
        text = text.strip()
        if text and not text.lstrip("-").isdigit():
            notify.error(tr("Initiative must be a whole number."))
            return
        value = int(text) if text else None
        if value != c["init"]:
            self.run(self.rt.battle.set_initiative, c["id"], value)

    def _menu(self, pos):
        it = self.tree.itemAt(pos)
        c = it.data(ROLE) if it else None
        if not c:
            return
        chosen = [i.data(ROLE) for i in self.tree.selectedItems() if i.data(ROLE)]
        cs = chosen if c["id"] in [x["id"] for x in chosen] and len(chosen) > 1 else [c]
        m = combatant_menu(self, cs, self._play)
        if len(cs) == 1:
            m.insertAction(m.actions()[0], m.addAction(tr("Set initiative here…"), lambda: self.ask_initiative(c)))
        m.exec(self.tree.viewport().mapToGlobal(pos))

    def _play(self, cid: int):
        """Play a creature from its menu: the Battle map's play mode on it."""
        w = self.parentWidget()
        while w is not None and not hasattr(w, "deck"):
            w = w.parentWidget()
        if w is not None:
            w.set_mode("play")
            w.deck.play(cid)

    # ------------------------------------------------------------------ stages
    def _rename(self):
        n = dialogs.ask_text(self, tr("Rename battle"), tr("Battle name"), self.v["name"] if self.v else "")
        if n:
            self.run(self.rt.battle.rename, n)

    def _add_players(self):
        add_players(self, V.free_characters(self.v))

    def _roll(self, scope: str):
        rolled = self.run(self.rt.battle.roll_initiative, scope, self.group)
        if rolled:
            notify.good(tr("Initiative: {0}", ", ".join(rolled[:6]) + ("…" if len(rolled) > 6 else "")))

    @staticmethod
    def _unplaced(v: dict) -> int:
        return sum(1 for c in v["combatants"] if not c.get("pos") and not c.get("out"))

    def _place_button(self, v: dict):
        n = self._unplaced(v)
        if not n:
            return None
        return icon_button("place", lambda: self._place_all(), tr("Place {0} on the map", n) + "\n" +
                           tr("Put every creature that isn't on the map yet on a free tile: the party on the left, the enemies on the right"),
                           color=COLORS["warn"], text=str(n))

    def _place_all(self):
        n = self.run(self.rt.battle.place_unplaced)
        if n:
            notify.good(tr("{0} placed on the map.", n))

    def _encounters_button(self) -> QToolButton:
        """Prepared fights: save the enemies, the map and its drawings; load one when the party gets there."""
        b = icon_button("encounters", None, tr("Encounters") + "\n" +
                        tr("Save this setup (enemies, positions, the map and its drawings) to load it when the party gets there"))
        b.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(b)
        menu.aboutToShow.connect(lambda: self._fill_encounters(menu))
        b.setMenu(menu)
        return b

    def _fill_encounters(self, menu: QMenu):
        menu.clear()
        menu.addAction(tr("Save this setup as an encounter…"), self._save_encounter)
        saved = guard(self.rt.battle.encounters) or []
        if not saved:
            a = menu.addAction(tr("(no saved encounters yet)"))
            a.setEnabled(False)
            return
        menu.addSection(tr("Load"))
        for e in saved:
            menu.addAction(f"{e['name']}  ·  " + tr("{0} creatures", e.get("enemies", 0)) + (f"  ·  {e['xp']:,} XP" if e.get("xp") else ""),
                           lambda n=e["name"]: self._load_encounter(n))
        dele = menu.addMenu(tr("Delete"))
        for e in saved:
            dele.addAction(e["name"], lambda n=e["name"]: dialogs.confirm(self, tr("Delete the encounter '{0}'?", n), yes=tr("Delete"))
                           and self.run(self.rt.battle.delete_encounter, n))

    def _save_encounter(self):
        n = dialogs.ask_text(self, tr("Save encounter"), tr("Name of this encounter"), self.v["name"] if self.v else "")
        if n and self.run(self.rt.battle.save_encounter, n) is not None:
            notify.good(tr("Encounter '{0}' saved.", n))

    def _load_encounter(self, name: str):
        has = self.v and any(c["kind"] != "pc" for c in self.v["combatants"])
        if has and not dialogs.confirm(self, tr("Replace this battle with '{0}'? Your players stay (Ctrl+Z undoes it).", name), yes=tr("Load")):
            return
        if self.run(self.rt.battle.load_encounter, name, True) is not None:
            notify.good(tr("Encounter '{0}' loaded.", name))

    def _clear_enemies(self):
        if self.run(self.rt.battle.clear_enemies) is not None:
            notify.info(tr("Enemies cleared. Ctrl+Z brings them back."))

    def _new_battle(self):
        s = (self.v or {}).get("summary") or {}
        if s.get("xp") and not s.get("awarded") and not dialogs.confirm(
                self, tr("The {0} XP of this battle hasn't been awarded. Start a new battle anyway?", f"{s['xp']:,}"), yes=tr("New battle")):
            return
        self.run(self.rt.battle.reset)

    def _start(self):
        missing = self.rt.battle.missing_initiative()
        auto = False
        if missing:
            if not dialogs.confirm(self, tr("No initiative yet for: {0}", ", ".join(missing[:8]) + ("…" if len(missing) > 8 else ""))
                                   + "\n\n" + tr("Roll it now and start?"), tr("Start battle")):
                return
            auto = True
        if attempt(self.rt.battle.start, auto):
            notify.good(tr("Battle started!"))

    def _end(self):
        p = V.end_preview(self.v)
        if p["xp"] and p["pcs"]:                            # one question: end, and award the XP or not
            got = dialogs.form(self, tr("End the battle?"), [
                {"key": "award", "label": tr("Award {0} XP ({1} each) to the party", f"{p['xp']:,}", f"{p['share']:,}"), "kind": "check",
                 "value": True}], tr("End battle"))
            if got is None:
                return
            award = got["award"]
        elif dialogs.confirm(self, tr("End the battle?"), tr("End battle")):
            award = False
        else:
            return
        self.run(self.rt.battle.end, award)

    def _award(self):
        share = self.run(self.rt.battle.award_xp)
        if share:
            notify.good(tr("Awarded {0} XP to each player.", share))

    def _reveal_all(self, on: bool):
        self.run(self.rt.battle.reveal, None, on)

    def save_state(self) -> dict:
        return {"group": self.group}

    def restore_state(self, state: dict):
        self.group = bool(state.get("group", True))
        self.stage = None
        guard(self.refresh)

