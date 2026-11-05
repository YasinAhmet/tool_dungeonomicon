"""What the Battle map has selected, shown in the Inspector window while something is selected: a
creature's card (stat block or sheet, attacks and spells in one click), a prop or map symbol (turn, open, throwable,
erase), a picture (layer, lock, hide, turn, fit), a spell's lasting area (name, note, rounds) or an item on the ground
(give, amount)."""
import html

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QMenu, QToolButton, QVBoxLayout, QWidget

from ....core import events
from ....core.i18n import tr
from ....rules.describe import describe
from ....services.battle import props, rooms
from ....services.battle import view as V
from ....services.battle.battlemap import col_name
from ....services.battle.drawing import SYMBOLS
from ....services.battle.ground import default_throw_damage
from ....services.battle.sight import DOORS, SYMBOL_TERRAIN
from ... import dialogs, notify
from ...errors import guard
from ...panel import Panel
from ...widgets.common import FlowLayout, button, check, clear_layout, combo, label, row, stretch, title
from .drawtools import LINE_COVER_TEXT
from .roomart import wall_icon
from .turn import CardPanel

KINDS = {"creature": "Creature", "symbol": "Prop", "image": "Picture", "zone": "Lasting area", "ground": "On the ground",
         "room": "Room", "door": "Door", "path": "Line"}
LAYERS = (("ground", "Ground: under the grid"), ("map", "Map: under the tokens"), ("top", "Top: over the tokens"))


def selection_of(canvas):
    """What the map has selected: (kind, id) or None. A creature first, then a drawing, an area, an item on the ground."""
    if canvas.selected:
        return "creature", canvas.selected
    if canvas.picked:
        d = drawing(canvas, canvas.picked)
        if d and d["type"] in ("symbol", "image", "room", "door", "path"):
            return d["type"], d["id"]
    if canvas.zone_pick:
        return "zone", canvas.zone_pick
    if canvas.gpick:
        return "ground", canvas.gpick
    return None


def drawing(canvas, did):
    return next((d for d in (canvas.view or {}).get("drawings") or [] if d["id"] == did), None)


def terrain_text(rules: dict) -> str:
    bits = []
    if rules.get("cover"):
        bits.append(tr("{0} cover", tr(rules["cover"])))
    if rules.get("blocks"):
        bits.append(tr("blocks the tile"))
    if rules.get("difficult"):
        bits.append(tr("difficult terrain"))
    if rules.get("light"):
        bits.append(tr("light {0} ft", rules["light"][0]))
    return ", ".join(bits) or tr("decoration")


def tile_name(x, y) -> str:
    return f"{col_name(int(x))}{int(y) + 1}"


def flow(*widgets) -> QWidget:
    host = QWidget()
    lay = FlowLayout(host, spacing=3)
    for w in widgets:
        if w is not None:
            lay.addWidget(w)
    return host


class MapInspector(Panel):
    def build(self):
        self.canvas = None           # the Battle map's canvas the selection is on
        self.sel = None
        self.shown = None            # what the body was last built for: (kind, id, the data it showed)
        self.layout().setContentsMargins(0, 2, 0, 0)
        self.kind = title("")
        self.kind.setToolTip(tr("Pick an action or spell, then aim it on the battle map."))
        self.layout().addLayout(row(self.kind, stretch(),
                                    button("×", self.deselect, kind="flat", width=24, tip=tr("Deselect (Esc)"))))
        self.thing = QWidget()
        self.box = QVBoxLayout(self.thing)
        self.box.setContentsMargins(0, 0, 0, 0)
        self.box.setSpacing(4)
        self.layout().addWidget(self.thing)
        self.card = CardPanel(None, "card")
        self.layout().addWidget(self.card, 1)
        self.on(events.BATTLE, self.refresh)

    def deselect(self):
        if self.canvas is not None:
            self.canvas.deselect()

    def show_selection(self, canvas, sel):
        self.canvas, self.sel = canvas, sel
        guard(self.refresh)

    def refresh(self):
        sel = self.sel
        if self.canvas is None or not sel:
            self.shown = None
            self.card.show_creature(None)
            return
        kind, ident = sel
        self.kind.setText(tr(KINDS[kind]).upper())
        creature = kind == "creature"
        self.card.setVisible(creature)
        self.thing.setVisible(not creature)
        if creature:
            self.shown = None
            owner = getattr(self.canvas, "owner", None)      # the creature the map's play bar plays: no second action bar here
            played = owner.deck.playing_id() if owner is not None and getattr(owner, "mode", "") == "play" else None
            self.card.prefs["_no_bar"] = played
            self.card.show_creature(ident)
            return
        self.card.show_creature(None)
        data = self._data(kind, ident)
        if data is None:                                    # erased meanwhile
            self.deselect()
            return
        key = (kind, ident, repr(sorted(data.items())))
        if key == self.shown:
            return
        self.shown = key
        clear_layout(self.box)
        getattr(self, "_" + kind)(data)

    def _data(self, kind, ident):
        """The selected thing as the battle has it now (the map may not have redrawn yet)."""
        if kind == "zone":
            return next((z for z in guard(self.rt.battle.zones_view) or [] if z["id"] == ident), None)
        v = V.battle_view()
        return next((x for x in v.get("drawings" if kind in ("symbol", "image", "room", "door", "path") else "ground") or []
                     if x["id"] == ident), None)

    def _head(self, text: str, pic=None, sub: str = ""):
        name = label(f"<b>{html.escape(text)}</b>" + (f"<br><span style='color:#8b93a3'>{html.escape(sub)}</span>" if sub else ""),
                     wrap=True)
        name.setTextFormat(Qt.RichText)
        if pic is None:
            self.box.addWidget(name)
            return
        icon = label("")
        icon.setPixmap(pic)
        icon.setFixedSize(pic.size())
        r = row(icon, name)
        r.setStretchFactor(name, 1)
        self.box.addLayout(r)

    # ------------------------------------------------------------------ a prop or a map symbol
    def _symbol(self, d: dict):
        b, sym = self.rt.battle, d.get("sym", "")
        path = props.path(sym)
        pic = None
        if path:
            pm = QPixmap(path)
            pic = pm.scaled(44, 44, Qt.KeepAspectRatio, Qt.SmoothTransformation if props.smooth(sym) else Qt.FastTransformation)
        if sym in props.PROPS:
            name, rules = props.PROPS[sym][0], props.terrain(sym) or {}
        else:
            name, rules = SYMBOLS.get(sym, ("?", sym))[1], SYMBOL_TERRAIN.get(sym, {})
        if sym in DOORS:
            rules = {"blocks": not d.get("open")}
        elif sym in props.DOOR_PROPS:
            rules = {} if d.get("open") else {"cover": "total", "blocks": True}
        elif sym in props.HATCHES and d.get("open"):
            rules = {}
        glyph = "" if pic is not None else SYMBOLS.get(sym, ("", ""))[0] + " "
        state = ((tr("open") if d.get("open") else tr("shut")) + " · ") if sym in props.OPENS else ""
        self._head(glyph + tr(name), pic, tr("Tile {0}", tile_name(d["x"], d["y"])) + " · " + state + terrain_text(rules))
        btns = [button(tr("⟳ Turn (R)"), lambda: guard(b.rotate_symbol, d["id"]), kind="flat")]
        if sym in props.OPENS:
            btns.append(button(tr("Close (O)") if d.get("open") else tr("Open (O)"), lambda: guard(b.toggle_door, d["id"]), kind="flat"))
        btns.append(button(tr("🗑 Erase (Del)"), lambda: self._erase(lambda: b.erase(d["id"])), kind="flat"))
        self.box.addWidget(flow(*btns))
        dmg = d.get("throw_dmg") or default_throw_damage(sym)
        throw = check(tr("Throwable ({0} bludgeoning)", dmg), bool(d.get("throw")), lambda on: guard(b.set_throwable, d["id"], on),
                      tip=tr("Creatures next to it can throw it with the Throw action"))

        def damage():
            text = dialogs.ask_text(self, tr("Throw damage"), tr("Damage when it hits (dice, bludgeoning):"), dmg)
            if text is not None:
                guard(b.set_throwable, d["id"], True, text.strip())
        r = row(throw, stretch(), button(tr("Damage…"), damage, kind="flat"))
        self.box.addLayout(r)

    # ------------------------------------------------------------------ a picture
    def _image(self, d: dict):
        b = self.rt.battle
        self._head(d.get("name") or tr("Picture"), None, tr("{0} × {1} tiles", f"{d['w']:.1f}", f"{d['h']:.1f}")
                   + (" · " + tr("turned {0}°", round(float(d.get("rot") or 0))) if d.get("rot") else ""))
        self.box.addLayout(row(label(tr("Layer"), role="dim"),
                               combo([(tr(t), k) for k, t in LAYERS], d.get("layer", "map"),
                                     lambda k: guard(b.set_image, d["id"], layer=k)), stretch()))
        self.box.addWidget(flow(check(tr("Locked"), bool(d.get("locked")), lambda on: guard(b.set_image, d["id"], locked=on),
                                      tip=tr("Clicks go through it")),
                                check(tr("Hidden from the players"), bool(d.get("hidden")),
                                      lambda on: guard(b.set_image, d["id"], hidden=on))))
        order = QToolButton()
        order.setText(tr("Order ▾"))
        order.setPopupMode(QToolButton.InstantPopup)
        m = QMenu(order)
        for key, text in (("front", tr("Bring to front")), ("up", tr("Bring forward (Page Up)")), ("down", tr("Send backward (Page Down)")),
                          ("back", tr("Send to back"))):
            m.addAction(text, lambda k=key: guard(b.restack, d["id"], k))
        order.setMenu(m)
        self.box.addWidget(flow(button(tr("⟳ Turn (R)"), lambda: guard(b.set_image, d["id"], rot=float(d.get("rot") or 0) + 90), kind="flat"),
                                button(tr("Straighten"), lambda: guard(b.set_image, d["id"], rot=0), kind="flat"),
                                button(tr("Fit to the map"), lambda: self.canvas._fit_image(d), kind="flat"), order,
                                button(tr("🗑 Erase (Del)"), lambda: self._erase(lambda: b.erase(d["id"])), kind="flat")))

    # ------------------------------------------------------------------ a room and a door in its wall
    def _room(self, d: dict):
        b = self.rt.battle
        self._head(tr("Room"), None, tr("{0} × {1} tiles", d["w"], d["h"]) + " · " + tr("Tile {0}", tile_name(d["x"], d["y"])))
        self.box.addWidget(label(tr("Drag it by its wall to move it. With the ▦ room tool, click its wall to put a door in."),
                                 role="dim", wrap=True))
        self.box.addWidget(flow(button(tr("🗑 Erase (Del)"), lambda: self._erase(lambda: b.erase(d["id"])), kind="flat")))

    def _door(self, d: dict):
        """A door, window, archway... in a room's wall: open or shut it, change what it is, take it out."""
        b = self.rt.battle
        kind = rooms.kind_of(d)
        opens = rooms.WALL_KINDS[kind][1]
        does = (tr("an opening: nothing blocked") if kind == "archway" else
                tr("lets creatures and sight through") if d.get("open") else
                tr("sight passes, nobody does") if kind in rooms.SEE_THROUGH else tr("blocks like the wall"))
        self._head(tr(rooms.WALL_KINDS[kind][0]), wall_icon(kind, 40),
                   ((tr("open") if d.get("open") else tr("shut")) + " · " if opens else "") + does)
        self.box.addLayout(row(label(tr("Make it"), role="dim"),
                               combo([(tr(v[0]), k) for k, v in rooms.WALL_KINDS.items()], kind,
                                     lambda k: k != kind and guard(b.put_in_wall, d["x"], d["y"], d["v"], k)), stretch()))
        btns = [button(tr("Close (O)") if d.get("open") else tr("Open (O)"), lambda: guard(b.toggle_door, d["id"]), kind="flat")] if opens else []
        self.box.addWidget(flow(*btns, button(tr("🗑 Take out (Del)"), lambda: self._erase(lambda: b.erase(d["id"])), kind="flat")))

    # ------------------------------------------------------------------ a drawn line
    def _path(self, d: dict):
        """A line drawn on the map: what it is on the battlefield (a wall, full, half or no cover), erase."""
        b = self.rt.battle
        cover = rooms.cover_of(d)
        snapped = all(float(x).is_integer() and float(y).is_integer() for x, y in d["pts"])
        self._head(tr("Wall") if cover == "wall" else tr("Line"), None, tr("{0} points", len(d["pts"])) + (" · " + tr("closed") if d.get("closed") else ""))
        choices = [(tr(text), k) for k, text in LINE_COVER_TEXT if k != "wall" or snapped]
        self.box.addLayout(row(label(tr("It is"), role="dim"), combo(choices, cover, lambda k: k != cover and guard(b.set_cover, d["id"], k)),
                               stretch()))
        self.box.addWidget(flow(button(tr("🗑 Erase (Del)"), lambda: self._erase(lambda: b.erase(d["id"])), kind="flat")))

    # ------------------------------------------------------------------ a spell's lasting area
    def _zone(self, zn: dict):
        b = self.rt.battle
        owner = V.find(self.canvas.view, zn["owner"]) if zn.get("owner") and self.canvas.view else None
        bits = [tr("by {0}", owner["name"]) if owner else "",
                tr("{0} rounds left", zn["rounds"]) if zn.get("rounds") is not None else tr("until taken off"),
                tr("{0} tiles", len(zn.get("tiles") or []))]
        self._head(tr(zn["name"]), None, " · ".join(x for x in bits if x))
        if zn.get("note"):
            self.box.addWidget(label(zn["note"], wrap=True))
        self.box.addWidget(check(tr("Hidden from the players"), bool(zn.get("hidden")), lambda on: guard(b.edit_zone, zn["id"], hidden=on)))
        self.box.addWidget(flow(button(tr("Edit name, note, rounds…"), lambda: self.canvas._edit_zone(zn), kind="flat"),
                                button(tr("Take it off (Del)"), lambda: self._erase(lambda: b.end_zone(zn["id"])), kind="flat")))

    # ------------------------------------------------------------------ an item on the ground
    def _ground(self, g: dict):
        b = self.rt.battle
        self._head(tr(g["name"]) + (f" ×{g['qty']}" if g["qty"] > 1 else ""), None, tr("Tile {0}", tile_name(g["x"], g["y"])))
        give = QToolButton()
        give.setText(tr("Give to ▾"))
        give.setPopupMode(QToolButton.InstantPopup)
        m = QMenu(give)
        for c in (self.canvas.view or {}).get("combatants") or []:
            m.addAction(c["name"], lambda cid=c["id"]: (lambda out: out and notify.good(tr(out)))(guard(b.give_ground, g["id"], cid)))
        give.setMenu(m)
        give.setEnabled(not m.isEmpty())
        self.box.addWidget(flow(give, button(tr("Amount…"), lambda: (lambda n: n and guard(b.set_ground_qty, g["id"], n))(
                                    dialogs.ask_int(self, tr("Amount"), tr("How many {0}?", tr(g["name"])), g["qty"], 1, 10 ** 6)), kind="flat"),
                                button(tr("🗑 Erase (Del)"), lambda: self._erase(lambda: b.erase_ground(g["id"])), kind="flat")))
        try:
            d = describe("items", g["name"])
        except Exception:                                   # a homebrew or made-up item: no text to show
            d = None
        if d and d.get("text"):
            text = label(tr(d["text"])[:600] + ("…" if len(d["text"]) > 600 else ""), role="dim", wrap=True)
            self.box.addWidget(text)

    def _erase(self, fn):
        self.deselect()
        guard(fn)
