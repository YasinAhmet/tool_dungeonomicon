"""The Battle map window, in two modes.

✏ Edit (setting up, or fixing things mid-fight): a tile grid with the combatants' tokens - drag them anywhere (put
there: no movement spent, no opportunity attacks, reactions or zone triggers), draw
walls and rooms, drop props, pictures and creatures (from the drawer beside the map or the Library), edit spell areas.
▶ Play (running the fight): the turn's creature is played like a player plays theirs on the portal - its action bar
under the map, aiming with range and area previews, click a tile or drag the token to walk (the path and its cost show
while hovering), right-click a creature for "Play it now" to play another instead.

In both: wheel zooms, right-drag pans, a click selects (a creature, prop, picture, area or item: it shows in the
Inspector window), a double-click on a creature brings the Inspector forward (a player character: its full sheet),
right-click a token for its menu, D / H damage or heal the selected token, Esc deselects, and a waiting reaction pops up
on the map. The drawer of creatures, props and items folds away
on the left, the initiative band (a row of tokens, and in play the action bar) under the map."""
import html
import json
import math
import os
import time

from PySide6.QtCore import QLineF, QPointF, QRectF, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QGuiApplication, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QFrame, QMenu, QSizePolicy, QSplitter, QTabWidget, QToolButton, QToolTip, QVBoxLayout,
                               QWidget, QWidgetAction)

from ....core import events
from ....core.i18n import tr
from ....services.battle import floors as FL, props, rooms as R, view as V
from ....services.battle.battlemap import col_name
from ....services.battle.ground import default_throw_damage
from ... import dialogs, notify, registry
from ...errors import guard
from ...panel import Panel
from ...registry import panel
from ...selection import hub, show_battle_pick
from ...theme import COLORS
from ...widgets.common import button, col, label, row, spin, stretch, tool_button
from ...widgets.icons import icon_button
from ...widgets.search import DRAG_MIME
from .common import (AREA, SELECTED, TARGET, TURN, aim_count, apply_hp, battle_hub, combatant_menu, hp_color, needs_click, say,
                     token, token_card, type_choice)
from .drawtools import (IMAGE_FILES, LINE_COVER_TEXT, DrawBar, encode_image, far_enough, free_point, ground_hit, ground_spots, open_text,
                        item_sprite, paint_drawings, paint_ground, paint_images, paint_item, paint_item_label, paint_stroke, prop_pixmap,
                        SACK, tile_point)
from .creature import open_creature
from .inspector import selection_of
from .play import MapHost, PlayDeck, pick_target, render_aimbar, render_pending
from .assets import icon_pixmap as asset_icon, known as asset_known, name as asset_name, quick_keys
from .lighting import paint_light
from .roomart import paint_room_carve, paint_room_ghost, paint_rooms, paint_wall_preview, wall_icon
from .tracker import TrackerPanel
from .vfx import Fx, paint_zone

ZMIN, ZMAX = 10, 140
PING_EVERY, PING_LIFE = 0.06, 1.4                           # seconds: between pointer updates sent; a ping rippling out
PING = (250, 204, 21)
HINTS = {"edit": "Edit: drag tokens anywhere (no movement spent, no opportunity attacks or reactions) · right-drag: move the map · wheel: zoom · "
                 "double-click a token: its sheet or stat block · right-click a token: its menu · "
                 "D / H: damage or heal the selected token · Del: remove · Ctrl+Z: undo · O or right-click on a door or window: "
                 "open/close · right-click a room's wall: a door, window or archway in it, stairs or a chest beside it (hover to see it) · "
                 "right-click a drawn line: wall, full, half or no cover · a dim or dark map (initiative Rules ▸ Light on the map): "
                 "campfires and torches light it, walls throw shadows · "
                 "room tool + Shift-drag: erase those tiles out of the rooms · "
                 "stairs up / down: the next floor appears beside the map (up: right, down: left) with the same building · "
                 "📍 Ping: the players see your pointer, click to ping · "
                 "right-click an empty tile: things to put on it · drop "
                 "picture files on the map: hold one and scroll to turn it (Shift: size), right-click it for layer, lock, "
                 "hide, erase · spell areas: drag to move, double-click to edit, Del: take off",
         "play": "Play: pick an action below (or press 1-9 for the first nine), then its target on the map (Enter: go · Esc / "
                 "right-click: cancel) · click a "
                 "tile or drag the token: walk · out of combat: drag any token · right-click a door or window: open/close · "
                 "drag: move the map · double-click a creature: its "
                 "sheet or stat block · right-click a token: its menu (▶ Play it now) · walk onto linked stairs: up or down "
                 "to the next floor · 📍 Ping: the players see your pointer, click to ping · Ctrl+Space: next turn · Ctrl+Z: undo"}


class TokenMenu(QFrame):
    """The little box next to a clicked token: its hit points, damage (typed, halved on a save) or heal.
    Enter: damage · Shift+Enter: heal · Esc: close."""

    def __init__(self, canvas: "MapCanvas"):
        super().__init__(canvas)
        self.canvas = canvas
        self.setObjectName("card")
        self.cid = None
        self.name = label("")
        f = self.name.font()
        f.setBold(True)
        self.name.setFont(f)
        self.hp = label("", role="dim")
        self.amount = spin(0, 0, 9999, width=54, tip=tr("Amount (Enter: damage · Shift+Enter: heal)"))
        self.dtype = type_choice()
        self.half = QCheckBox("½")
        self.half.setToolTip(tr("Saved: half damage"))
        close = button("×", self.hide, kind="flat", tip=tr("Close (Esc)"))
        close.setStyleSheet("padding: 0 5px;")
        more = button("⋯", self._more, kind="flat", tip=tr("Conditions, hit points, initiative, remove…"))
        more.setStyleSheet("padding: 0 5px;")
        self.setLayout(col(row(self.name, self.hp, stretch(), more, close),        # (the card's pictures: one row)
                           row(self.amount, self.dtype, self.half,
                               icon_button("damage", lambda: self._apply("damage"), tr("Damage") + " (Enter)", color=COLORS["bad"]),
                               icon_button("heal", lambda: self._apply("heal"), tr("Heal") + " (Shift+Enter)", color=COLORS["good"]),
                               spacing=2), margins=6))
        self.hide()

    def open(self, cid: int, focus: bool = False):
        if cid != self.cid:
            self.half.setChecked(False)
        self.cid = cid
        self.place()
        if focus and self.isVisible():
            self.amount.setFocus()
            self.amount.selectAll()

    def place(self):
        v = self.canvas.view
        c = V.find(v, self.cid) if v and self.cid else None
        if not c or not c.get("pos"):
            self.hide()
            return
        self.name.setText(c["name"])
        self.hp.setText(tr("{0}/{1} HP · AC {2}", c["hp"], c["max_hp"], c["ac"]) + (f" +{c['temp_hp']}" if c.get("temp_hp") else ""))
        self.adjustSize()
        cam = self.canvas.cam
        x = cam["x"] + (c["pos"][0] + V.span(c)) * cam["z"] + 6
        y = cam["y"] + c["pos"][1] * cam["z"]
        self.move(int(max(4, min(x, self.canvas.width() - self.width() - 4))), int(max(4, min(y, self.canvas.height() - self.height() - 4))))
        self.show()
        self.raise_()

    def _apply(self, kind: str):
        n = self.amount.value()
        if not n:
            notify.warn(tr("Enter the amount first."))
            return
        if self.cid and guard(lambda: (apply_hp([self.cid], kind, n, self.dtype.currentData() or None,
                                                [self.cid] if self.half.isChecked() else []), True)[1]):
            self.amount.setValue(0)
            self.half.setChecked(False)

    def _more(self):
        c = V.find(self.canvas.view or {}, self.cid)
        if c:
            combatant_menu(self, [c], self.canvas.owner.deck.play).exec(self.mapToGlobal(self.rect().topRight()))

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Escape:
            self.hide()
            self.canvas.setFocus()
            return
        if e.key() in (Qt.Key_Return, Qt.Key_Enter):
            self._apply("heal" if e.modifiers() & Qt.ShiftModifier else "damage")
            return
        super().keyPressEvent(e)


def _selection(name: str):
    """A canvas attribute whose changes are announced (selection_changed, once per turn of the event loop)."""
    key = "_" + name

    def get(self):
        return getattr(self, key, None)

    def put(self, value):
        if getattr(self, key, None) != value:
            setattr(self, key, value)
            if not getattr(self, "_sel_due", False):
                self._sel_due = True
                QTimer.singleShot(0, self, self._sel_emit)
    return property(get, put)


class MapCanvas(QWidget):
    selection_changed = Signal()
    selected = _selection("selected")                        # the selected creature's id
    picked = _selection("picked")                            # the selected drawing's id
    zone_pick = _selection("zone_pick")                      # the selected lasting area's id (a spell's mark on the map)
    gpick = _selection("gpick")                              # the selected item on the ground

    def __init__(self, owner: "BattleMapPanel"):
        super().__init__()
        self.owner = owner
        self.cam = {"x": 20.0, "y": 20.0, "z": 40.0}       # screen position of tile (0,0) and pixels per tile
        self.view = None
        self.fitted = False                                  # the camera was set once
        self.auto_fit = True                                 # keep fitting the map to the window until the user zooms or pans
        self.drag = None                                     # a carried token {id, tx, ty, ox, oy, ok, moved}
        self.pan = None
        self.ghost = None                                    # the tile under something dragged from another window
        self.area = None                                     # tiles an area spell would cover
        self.hover = None
        self.stroke = None                                   # the points of a line being drawn
        self.carry = None                                    # a symbol or room being moved {id, tx, ty, ox, oy}
        self.room_box = None                                 # the room tool's box being dragged out (x0, y0, x1, y1)
        self.room_erase = False                              # ... with Shift held: erasing those tiles out of the rooms
        self.preview = None                                  # a menu item hovered: ('wall', edge, kind) | ('place', key, tile, rot)
        self.zone_carry = None                               # a lasting area being dragged {id, t0, dx, dy}
        self.gcarry = None                                   # an item on the ground being dragged {id, x, y, from, one, moved, onto}
        self.ghover = None                                   # the item on the ground under the pointer: its name shows
        self.tool, self.ink, self.place = "select", "#c9b27a", None   # set by the DrawBar
        self.aim = None                                      # an action being aimed {'cid', 'item', 'targets', 'point'...}
        self.aim_hover = None                                # the half-tile under the pointer while aiming
        self.aim_tiles, self.aim_ids = [], []
        self.path = None                                     # play mode: (path, cost, ok, why, threats) to the hovered tile
        self.path_tile = None
        self.pinging = False                                 # the ping tool: the pointer shows on the players' maps
        self.ping_at = None                                  # where the pointer is (tile units) while pinging
        self.pings = []                                      # pings rippling out: (x, y, when)
        self._ping_sent, self._ping_due = 0.0, None
        self._ping_timer = QTimer(self)
        self._ping_timer.setInterval(30)
        self._ping_timer.timeout.connect(self._ping_tick)
        self.setAcceptDrops(True)
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.ClickFocus)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setMinimumSize(200, 150)
        self.menu = TokenMenu(self)
        self.fx = Fx(self)                                   # steps, hits, misses, bursts, shake
        self.fx.mine = lambda: {owner.deck.playing_id()} if self.playing else set()   # the played creature's hurt shows harder
        self.fx.paint_token = lambda p, c, rect, size: p.drawPixmap(rect, token(c, int(size)), QRectF(0, 0, max(8, int(size)), max(8, int(size))))

    def _sel_emit(self):
        self._sel_due = False
        self.selection_changed.emit()

    def deselect(self):
        self.selected = self.picked = self.zone_pick = self.gpick = None
        self.menu.hide()
        hub().combatant.emit(0)
        self.update()

    @property
    def rt(self):
        return self.owner.rt

    @property
    def playing(self) -> bool:
        return self.owner.mode == "play"

    # ------------------------------------------------------------------ camera
    def map_size(self):
        m = (self.view or {}).get("map") or {"w": 30, "h": 20}
        return m["w"], m["h"]

    def fit(self):
        w, h = self.map_size()
        z = max(12.0, min(90.0, min((self.width() - 30) / w, (self.height() - 30) / h)))
        self.cam = {"x": (self.width() - w * z) / 2 + 6, "y": (self.height() - h * z) / 2 + 6, "z": z}
        self.fitted = True
        self.auto_fit = True
        self.update()
        if self.menu.isVisible():
            self.menu.place()

    def fit_creatures(self):
        """Zoom to the creatures on the map (two tiles of room around them, at least 12 × 8 tiles); the whole map when
        none is placed."""
        placed = [c for c in (self.view or {}).get("combatants") or [] if c.get("pos")]
        if not placed:
            self.fit()
            return
        x0 = min(c["pos"][0] for c in placed) - 2
        y0 = min(c["pos"][1] for c in placed) - 2
        x1 = max(c["pos"][0] + (c.get("span") or 1) for c in placed) + 2
        y1 = max(c["pos"][1] + (c.get("span") or 1) for c in placed) + 2
        w, h = max(12, x1 - x0), max(8, y1 - y0)
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        z = max(ZMIN, min(ZMAX, 90.0, min((self.width() - 30) / w, (self.height() - 30) / h)))
        mw, mh = self.map_size()

        def start(centre: float, want: float, most: float) -> float:
            """Where the view begins (tiles): on the creatures, but showing more map rather than the void past its edge."""
            if want >= most:
                return (most - want) / 2
            return max(0.0, min(most - want, centre - want / 2))
        sx = start(cx, (self.width() - 30) / z, mw)
        sy = start(cy, (self.height() - 30) / z, mh)
        self.cam = {"x": 15 - sx * z, "y": 15 - sy * z, "z": z}
        self.auto_fit = False
        self.update()
        if self.menu.isVisible():
            self.menu.place()

    def zoom_at(self, f: float, px: float = None, py: float = None):
        px = self.width() / 2 if px is None else px
        py = self.height() / 2 if py is None else py
        z = max(ZMIN, min(ZMAX, self.cam["z"] * f))
        f = z / self.cam["z"]
        self.auto_fit = False
        self.cam = {"x": px - (px - self.cam["x"]) * f, "y": py - (py - self.cam["y"]) * f, "z": z}
        self.update()
        if self.menu.isVisible():
            self.menu.place()

    def to_tile(self, pos):
        z = self.cam["z"]
        return int((pos.x() - self.cam["x"]) // z), int((pos.y() - self.cam["y"]) // z)

    def on_map(self, t) -> bool:
        """A tile of the map (on a floor, not in the gap between two)."""
        _w, h = self.map_size()
        return 0 <= t[1] < h and FL.floor_at((self.view or {}).get("map") or {"w": _w, "h": h}, t[0]) is not None

    def set_view(self, v: dict):
        was = (self.view or {}).get("map")
        if was and not self.auto_fit:                        # a floor added or taken away below: the main floor stays put
            self.cam["x"] -= (FL.left(v["map"], 0) - FL.left(was, 0)) * self.cam["z"]
        self.view = v
        self.fx.feed(v)
        if self.selected and not V.find(v, self.selected):
            self.selected = None
        if self.picked and not any(d["id"] == self.picked for d in v.get("drawings") or []):
            self.picked = None
        if self.gpick and not any(g["id"] == self.gpick for g in v.get("ground") or []):
            self.gpick = None
        if self.auto_fit and self.width() > 50:
            self.fit()
        self.update()
        if self.menu.isVisible():
            self.menu.place()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.auto_fit and self.width() > 50 and self.height() > 50:
            self.fit()

    # ------------------------------------------------------------------ drawing
    def _grid(self, ground: bool, shown, fw: int, h: int, z: float, ox: float, oy: float) -> QPixmap:
        """The grid lines as a see-through picture of the whole map area, drawn again only when the camera, the size or
        the floors change (the map paints on every change, hover and animation frame; the lines cost the most)."""
        dpr = self.devicePixelRatioF()
        key = (ground, tuple(shown), fw, h, z, ox, oy, self.width(), self.height(), dpr)
        if getattr(self, "_grid_key", None) != key:
            pm = QPixmap(max(1, int(self.width() * dpr)), max(1, int(self.height() * dpr)))
            pm.setDevicePixelRatio(dpr)
            pm.fill(Qt.transparent)
            g = QPainter(pm)
            g.setRenderHint(QPainter.Antialiasing)
            g.setPen(QPen(QColor(170, 180, 200, 60) if ground else QColor(160, 170, 190, 46), 1))
            lines = []
            for x0 in shown:
                for i in range(fw + 1):
                    x = round(ox + (x0 + i) * z) + 0.5
                    lines.append(QLineF(x, oy, x, oy + h * z))
                for j in range(h + 1):
                    y = round(oy + j * z) + 0.5
                    lines.append(QLineF(ox + x0 * z, y, ox + (x0 + fw) * z, y))
            g.drawLines(lines)
            g.end()
            self._grid_key, self._grid_pm = key, pm
        return self._grid_pm

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)              # tokens popping in, shrinking away: scaled pictures
        p.fillRect(self.rect(), QColor(COLORS["bg"]))
        w, h = self.map_size()
        z, ox, oy = self.cam["z"], self.cam["x"], self.cam["y"]
        dx, dy = self.fx.shake()
        ox, oy = ox + dx, oy + dy
        m = (self.view or {}).get("map") or {"w": w, "h": h}
        fw, bands = FL.layout(m)[0], [x0 for _f, x0 in FL.floors(m)]   # each floor of the building, side by side
        shown = [x0 for x0 in bands if ox + (x0 + fw) * z > -z and ox + x0 * z < self.width() + z]
        for x0 in bands:
            p.fillRect(QRectF(ox + x0 * z, oy, fw * z, h * z), QColor(COLORS["raised"]))
        v = self.view
        drawn = (v or {}).get("drawings") or []
        if self.carry:
            c_ = self.carry
            drawn = [dict(d, **({k: c_[k] for k in ("x", "y", "w", "h", "rot")} if c_.get("img") else {"x": c_["tx"], "y": c_["ty"]}))
                     if d["id"] == c_["id"] else d for d in drawn]
        ground = paint_images(p, drawn, "ground", ox, oy, z, self.picked)      # a battle map picture: under the grid
        p.drawPixmap(0, 0, self._grid(bool(ground), shown, fw, h, z, ox, oy))
        p.setPen(QPen(QColor(160, 170, 190, 128), 1))
        for x0 in shown:
            p.drawRect(QRectF(ox + x0 * z + 0.5, oy + 0.5, fw * z, h * z))
        if z >= 22:                                          # the coordinates /battlemap prints (each floor from A)
            small = QFont(self.font())
            small.setPixelSize(10)
            p.setFont(small)
            p.setPen(QColor(160, 170, 190, 180))
            for x0 in shown:
                for i in range(fw):
                    x = ox + (x0 + i) * z
                    if -z < x < self.width():
                        p.drawText(QRectF(x, oy - 15, z, 14), Qt.AlignHCenter | Qt.AlignBottom, col_name(i))
                for j in range(h):
                    y = oy + j * z
                    if -z < y < self.height():
                        p.drawText(QRectF(ox + x0 * z - 30, y, 26, z), Qt.AlignRight | Qt.AlignVCenter, str(j + 1))
        if FL.many(m):                                       # each floor's name over it
            title = QFont(self.font())
            title.setBold(True)
            title.setPixelSize(12)
            p.setFont(title)
            for f, x0 in FL.floors(m):
                if x0 in shown:
                    p.setPen(QColor(COLORS["text"]) if f == 0 else QColor(160, 170, 190, 220))
                    p.drawText(QRectF(ox + x0 * z, oy - (32 if z >= 22 else 18), fw * z, 16), Qt.AlignHCenter | Qt.AlignBottom,
                               floor_name(f))
        if not v:
            return
        clip = QPainterPath()                                # the rooms' paper stays on its floor
        for x0 in bands:
            clip.addRect(QRectF(ox + x0 * z, oy, fw * z, h * z).adjusted(-z * .1, -z * .1, z * .1, z * .1))
        p.setClipPath(clip)
        if self.room_box and self.room_erase:
            paint_room_carve(p, drawn, self.room_box, ox, oy, z, self.font())
        elif self.room_box:
            paint_room_ghost(p, drawn, self.room_box, ox, oy, z, self.font())
        else:
            paint_rooms(p, drawn, ox, oy, z, self.picked, self.devicePixelRatioF())
        p.setClipping(False)
        flying = self.fx.hidden("did")                       # a thrown prop still in the air: not yet where it lands
        paint_drawings(p, [d for d in drawn if d["id"] not in flying] if flying else drawn, ox, oy, z, self.picked, self.font())
        paint_light(p, drawn, m.get("light", "bright"), bands, fw, h, ox, oy, z, self.devicePixelRatioF())
        self._paint_zones(p, v, ox, oy, z)                   # (spell areas over the dark: they stay readable)
        if self.preview:
            self._paint_preview(p, ox, oy, z)
        if self.stroke:
            paint_stroke(p, self.stroke, ox, oy, z, self.ink)
        ground = self._ground_shown()
        paint_ground(p, ground, ox, oy, z, self.gpick)
        self.fx.paint_under(p, ox, oy, z)
        if self.area:
            p.setPen(QPen(QColor(255, 140, 40, 230), 1))
            p.setBrush(QColor(255, 140, 40, 72))
            for x, y in self.area["tiles"]:
                p.drawRect(QRectF(ox + x * z + 0.5, oy + y * z + 0.5, z - 1, z - 1))
            p.setBrush(Qt.NoBrush)
        number = {c["id"]: i + 1 for i, c in enumerate(v["combatants"])}
        picked = set(v.get("picked") or [])
        played = self.owner.deck.playing_id() if self.playing else None
        for c in v["combatants"]:
            if not c.get("pos"):
                continue
            carried = self.drag and self.drag["id"] == c["id"] and self.drag["moved"]
            bx, by, bs = V.draw_box(v, c)                     # a Tiny token: half a tile, where it stands in its tile
            walked = self.fx.pos(c["id"])
            x, y = (self.drag["tx"], self.drag["ty"]) if carried else                 (walked[0] + bx - c["pos"][0], walked[1] + by - c["pos"][1]) if walked else (bx, by)
            s = bs * z
            px, py = ox + x * z, oy + y * z
            pose = None if carried else self.fx.pose(c["id"])   # a lunge, a flinch, a fade: (dx, dy, scale, opacity)
            if pose:
                px, py = px + pose[0] * z + s * (1 - pose[2]) / 2, py + pose[1] * z + s * (1 - pose[2]) / 2
                s *= pose[2]
            veil = None if carried or c["out"] else V.VEILS.get(c.get("veil"))   # banished, invisible...: see-through, tinted
            if veil and veil[1] < 1:                          # banished: a small token in the middle of its place
                px, py, s = px + s * (1 - veil[1]) / 2, py + s * (1 - veil[1]) / 2, s * veil[1]
            p.setOpacity((0.55 if carried else 0.45 if c["out"] else veil[0] if veil else 1.0) * (pose[3] if pose else 1.0))
            pad = max(1.0, s * 0.04)
            if not c["out"]:
                self.fx.paint_conc(p, c, px + s / 2, py + s / 2, s, z)        # concentrating: a dashed ring at its feet
            full = bs * z * 0.92                              # the picture at its own size, scaled while it pops or lunges
            p.drawPixmap(QRectF(px + pad, py + pad, s - 2 * pad, s - 2 * pad), token(c, int(full)), QRectF(0, 0, int(max(8, full)), int(max(8, full))))
            if veil:
                tint = QColor(veil[2])
                tint.setAlpha(70)
                p.setPen(QPen(QColor(veil[2]), 2, Qt.DashLine))
                p.setBrush(tint)
                p.drawEllipse(QRectF(px + pad, py + pad, s - 2 * pad, s - 2 * pad))
                p.setBrush(Qt.NoBrush)
            ring = TURN if v.get("turn") == c["id"] else SELECTED if self.selected == c["id"] or played == c["id"] else None
            if ring:
                p.setPen(QPen(QColor(ring), 3 if ring == TURN else 2, Qt.SolidLine if ring == TURN or self.selected == c["id"] else Qt.DotLine))
                p.drawEllipse(QRectF(px + pad, py + pad, s - 2 * pad, s - 2 * pad))
            r2 = max(7.0, s * 0.16)                          # the order number (or ×) in a badge
            bx, by = px + s - r2 - 1, py + s - r2 - 1
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(10, 12, 16, 220))
            p.drawEllipse(QPointF(bx, by), r2, r2)
            f = QFont(self.font())
            f.setBold(True)
            f.setPixelSize(int(max(8, r2 * 1.15)))
            p.setFont(f)
            p.setPen(QColor("#ffffff"))
            p.drawText(QRectF(bx - r2, by - r2, 2 * r2, 2 * r2), Qt.AlignCenter, "×" if c["out"] else str(number[c["id"]]))
            p.setBrush(Qt.NoBrush)
            if z >= 30:
                f.setBold(False)
                f.setPixelSize(11)
                p.setFont(f)
                name = c["name"] if len(c["name"]) <= 14 else c["name"][:13] + "…"
                tw = p.fontMetrics().horizontalAdvance(name) + 6       # on a dark tag: readable on a pale room floor too
                p.fillRect(QRectF(px + s / 2 - tw / 2, py + s, tw, 14), QColor(15, 17, 21, 170))
                p.setPen(QColor(COLORS["text"]))
                p.drawText(QRectF(px - z, py + s, s + 2 * z, 14), Qt.AlignHCenter | Qt.AlignTop, name)
                if c["max_hp"] and not c["out"]:
                    fr = max(0.0, min(1.0, c["hp"] / c["max_hp"]))
                    p.fillRect(QRectF(px + s * 0.1, py + 1, s * 0.8, 4), QColor(0, 0, 0, 150))
                    p.fillRect(QRectF(px + s * 0.1, py + 1, s * 0.8 * fr, 4), QColor(hp_color(fr)))
            if not c["out"]:
                self.fx.paint_badges(p, c, px + s / 2, py, z, self.font())     # its conditions, over its top edge
            p.setOpacity(1.0)
            self.fx.paint_pips(p, c, px, py, s)              # dying: its death saves, on its bottom edge
            if c["id"] in picked:
                pen = QPen(QColor(TARGET), 3, Qt.DashLine)
                p.setPen(pen)
                p.drawRect(QRectF(px + 1.5, py + 1.5, s - 3, s - 3))
            if self.area and c["id"] in self.area.get("ids", []):
                p.setPen(QPen(QColor(AREA), 3))
                p.drawRect(QRectF(px + 1.5, py + 1.5, s - 3, s - 3))
            if carried:
                p.setPen(QPen(QColor(COLORS["good"] if self.drag["ok"] else COLORS["bad"]), 2))
                p.drawRect(QRectF(px + 1, py + 1, s - 2, s - 2))
        for c in v["combatants"]:                            # the hovered or selected caster: what its concentration holds
            if c.get("concentrating") and c["id"] in (self.hover, self.selected):
                self.fx.paint_links(p, c, v, self.rt.battle.zones_view() if v.get("zones") else [], ox, oy, z)
        paint_images(p, drawn, "top", ox, oy, z, self.picked)                  # roofs, canopies: over the tokens
        self._paint_ground_over(p, v, ground, ox, oy, z)
        self.fx.paint_over(p, ox, oy, z, self.font())
        if self.ghost:
            p.setPen(QPen(QColor(COLORS["good"]), 2))
            p.drawRect(QRectF(ox + self.ghost[0] * z + 1, oy + self.ghost[1] * z + 1, z - 2, z - 2))
        if self.aim:
            self._paint_aim(p, v, ox, oy, z)
        elif self.path and self.playing:
            self._paint_path(p, ox, oy, z)
        self.fx.paint_screen(p, QRectF(self.rect()), self.font())
        self._paint_ping(p, ox, oy, z)
        p.end()

    # ------------------------------------------------------------------ the ping tool
    def set_ping(self, on: bool):
        """The ping tool: the pointer shows on every player's map (portal) as a ring; a click pings that spot."""
        self.pinging = bool(on)
        if on:
            self._ping_timer.start()
        elif self.ping_at is not None:
            self.ping_at, self._ping_due = None, None
            self._send_ping(None)
        self.setCursor(Qt.CrossCursor if on else Qt.ArrowCursor)
        self.update()

    def _ping(self, pos, press: bool):
        pt = tile_point(self, pos)
        self.ping_at = pt
        now = time.monotonic()
        if press:
            self.pings.append((pt[0], pt[1], now))
            self._ping_timer.start()
        if press or now - self._ping_sent >= PING_EVERY:
            self._ping_sent, self._ping_due = now, None
            self._send_ping(pt, press)
        else:
            self._ping_due = pt                              # sent on the next tick: the players' ring ends where it stopped
        self.update()

    def _send_ping(self, pt, press: bool = False):
        from ....services.portal.controller import portal
        guard(portal.ping, *(pt if pt else (None,)), press)

    def _ping_tick(self):
        now = time.monotonic()
        if self._ping_due and self.pinging and now - self._ping_sent >= PING_EVERY:
            self._ping_sent, pt, self._ping_due = now, self._ping_due, None
            self._send_ping(pt)
        if self.pings:
            self.pings = [q for q in self.pings if now - q[2] < PING_LIFE]
            self.update()
        elif not self.pinging:
            self._ping_timer.stop()

    def _paint_ping(self, p, ox, oy, z):
        """What the players see of the pointer: a ring where it is, and rings rippling out from a ping."""
        now = time.monotonic()
        for x, y, t0 in self.pings:
            for k in range(3):
                u = (now - t0) / PING_LIFE * 1.5 - k * 0.25
                if 0 <= u <= 1:
                    c = QColor(*PING)
                    c.setAlphaF(0.9 * (1 - u))
                    p.setPen(QPen(c, 2 + 3 * (1 - u)))
                    p.setBrush(Qt.NoBrush)
                    r = z * (0.3 + 2.2 * u)
                    p.drawEllipse(QPointF(ox + x * z, oy + y * z), r, r)
        if self.pinging and self.ping_at:
            at, r = QPointF(ox + self.ping_at[0] * z, oy + self.ping_at[1] * z), max(10.0, z * 0.45)
            p.setPen(QPen(QColor(*PING), 2.5))
            p.setBrush(QColor(*PING, 45))
            p.drawEllipse(at, r, r)
            p.setBrush(QColor(*PING))
            p.drawEllipse(at, 3, 3)
            p.setBrush(Qt.NoBrush)

    def _paint_path(self, p, ox, oy, z):
        """Play mode: the way to the hovered tile, what it costs, and where it draws an opportunity attack."""
        path, cost, ok, why, threats = self.path
        me = self._me()
        s = V.span(me) if me else 1
        col_ = QColor(74, 222, 128, 220) if ok else QColor(248, 113, 113, 220)
        p.setPen(QPen(col_, 3, Qt.DashLine, Qt.RoundCap, Qt.RoundJoin))
        pts = [QPointF(ox + (x + s / 2) * z, oy + (y + s / 2) * z) for x, y in path]
        for a, b in zip(pts, pts[1:]):
            p.drawLine(a, b)
        x, y = path[-1]
        p.setPen(QPen(col_, 2))
        p.drawRect(QRectF(ox + x * z + 2, oy + y * z + 2, s * z - 4, s * z - 4))
        f = QFont(self.font())
        f.setBold(True)
        p.setFont(f)
        text = f"{cost} ft" + (f" · {tr(why)}" if why and not ok else "")
        rect = QRectF(ox + x * z - 60, oy + y * z - 20, s * z + 120, 18)
        p.fillRect(QRectF(rect.center().x() - len(text) * 3.6, rect.top(), len(text) * 7.2, 17), QColor(15, 17, 21, 210))
        p.setPen(col_)
        p.drawText(rect, Qt.AlignCenter, text)
        if threats:
            warn = QColor(251, 146, 60)
            for at in {tuple(t["at"]) for t in threats}:      # where the way leaves their reach
                c_ = QPointF(ox + (at[0] + s / 2) * z, oy + (at[1] + s / 2) * z)
                r = max(7.0, z * 0.22)
                p.setPen(QPen(QColor(15, 17, 21), 2))
                p.setBrush(warn)
                p.drawEllipse(c_, r, r)
                p.setPen(QColor(15, 17, 21))
                p.drawText(QRectF(c_.x() - r, c_.y() - r, 2 * r, 2 * r), Qt.AlignCenter, "!")
            p.setBrush(Qt.NoBrush)
            text = "⚔ " + tr("Opportunity attack: {0}", ", ".join(t["name"] for t in threats))
            rect = QRectF(rect.center().x() - 400, rect.top() - 19, 800, 18)
            p.fillRect(QRectF(rect.center().x() - len(text) * 3.6, rect.top(), len(text) * 7.2, 17), QColor(15, 17, 21, 210))
            p.setPen(warn)
            p.drawText(rect, Qt.AlignCenter, text)

    # ------------------------------------------------------------------ items on the ground
    def _ground_shown(self) -> list:
        """The stacks on the ground as drawn: the one being dragged (or the one item taken off it) left out, and one
        still flying there (thrown)."""
        ground = (self.view or {}).get("ground") or []
        flying = self.fx.hidden("gid")
        if flying:
            ground = [g for g in ground if g["id"] not in flying]
        gc = self.gcarry
        if not gc or not gc["moved"]:
            return ground
        return [dict(g, qty=g["qty"] - 1) if g["id"] == gc["id"] and gc["one"] else g
                for g in ground if g["id"] != gc["id"] or (gc["one"] and g["qty"] > 1)]

    def _ground_under(self, pos):
        return ground_hit((self.view or {}).get("ground") or [], *tile_point(self, pos)) if self.view else None

    def _paint_ground_over(self, p, v, ground, ox, oy, z):
        """Over the tokens: the name of the hovered item, and the item being dragged (onto a creature: given to it)."""
        gc = self.gcarry
        if gc and gc["moved"]:
            g = next((x for x in v.get("ground") or [] if x["id"] == gc["id"]), None)
            if g:
                g = dict(g, qty=1 if gc["one"] else g["qty"])
                tok = V.find(v, gc.get("onto")) if gc.get("onto") else None
                if tok and tok.get("pos"):
                    bx, by, bs = V.draw_box(v, tok)
                    s_ = bs * z
                    p.setPen(QPen(QColor(COLORS["good"]), 3))
                    p.drawEllipse(QRectF(ox + bx * z + 2, oy + by * z + 2, s_ - 4, s_ - 4))
                pm = item_sprite(g["name"]) or prop_pixmap(SACK)
                if pm is not None:                           # held up off the floor: a bigger sprite, a further shadow
                    paint_item(p, pm, ox + gc["x"] * z, oy + gc["y"] * z, z * .85, alpha=.9)
                label = dict(g, name=tr("Give to {0}", tok["name"]) + ": " + tr(g["name"])) if tok else g
                paint_item_label(p, label, ox + gc["x"] * z, oy + (gc["y"] - 0.3) * z, self.font())
            return
        if self.ghover is not None:
            spot = next(((g, cx, cy) for g, cx, cy in ground_spots(ground) if g["id"] == self.ghover), None)
            if spot:
                g, cx, cy = spot
                paint_item_label(p, g, ox + cx * z, oy + (cy - 0.3) * z, self.font())

    def _start_gcarry(self, g: dict, e):
        x, y = tile_point(self, e.position())
        self.gcarry = {"id": g["id"], "x": x, "y": y, "from": (g["x"], g["y"]), "one": bool(e.modifiers() & Qt.ControlModifier),
                       "moved": False, "onto": None}
        self.gpick = g["id"]
        self.picked = self.zone_pick = None
        self.setCursor(Qt.ClosedHandCursor)
        self.update()

    def _move_gcarry(self, pos):
        gc = self.gcarry
        x, y = tile_point(self, pos)
        if not gc["moved"] and abs(x - gc["x"]) + abs(y - gc["y"]) < 0.15:
            return
        tok = self._at(pos)
        gc.update(x=x, y=y, moved=True, onto=tok["id"] if tok else None)
        self.update()

    def _drop_gcarry(self, pos):
        gc, self.gcarry = self.gcarry, None
        self.setCursor(Qt.OpenHandCursor)
        b = self.rt.battle
        qty = 1 if gc["one"] else None
        if gc["moved"]:
            tok = self._at(pos)
            t = self.to_tile(pos)
            if tok:
                out = guard(b.give_ground, gc["id"], tok["id"], qty)
                if out:
                    notify.good(tr(out))
            elif self.on_map(t):                             # it lies right where it was let go (Shift: a corner or a middle)
                pt = free_point(tile_point(self, pos), QGuiApplication.keyboardModifiers())
                guard(b.move_ground, gc["id"], pt[0], pt[1], qty, True)
        self.update()

    def _ground_menu(self, g: dict, at):
        """Right-click on an item lying on the map: give it to a creature, change the amount, erase it."""
        b = self.rt.battle
        self.gpick = g["id"]
        self.update()
        m = QMenu(self)
        head = m.addAction(f"{tr(g['name'])} ×{g['qty']}" if g["qty"] > 1 else tr(g["name"]))
        head.setEnabled(False)
        give = m.addMenu(tr("Give to"))
        for c in (self.view or {}).get("combatants") or []:
            give.addAction(c["name"], lambda cid=c["id"]: (lambda out: out and notify.good(tr(out)))(guard(b.give_ground, g["id"], cid)))
        give.setEnabled(not give.isEmpty())
        m.addAction(tr("Amount…"), lambda: (lambda n: n and guard(b.set_ground_qty, g["id"], n))(
            dialogs.ask_int(self, tr("Amount"), tr("How many {0}?", tr(g["name"])), g["qty"], 1, 10 ** 6)))
        m.addSeparator()
        m.addAction(tr("Erase (Delete)"), lambda: (setattr(self, "gpick", None), guard(b.erase_ground, g["id"])))
        m.exec(at)

    def _drop_item(self, payload: dict, t, one: bool, pt=None):
        """An item dragged from a sheet's inventory or the library: onto a creature it is given, else it lies where it was
        dropped (`pt`, a point; Shift snaps it to a tile's corner or middle)."""
        b = self.rt.battle
        tok = (V.at_point(self.view, *pt) if pt else V.at_tile(self.view, *t)) if self.view else None
        name = payload.get("item") or payload.get("name") or ""
        who = payload.get("character")
        qty = 1 if one else max(1, int(payload.get("qty") or 1))
        if tok:
            out = guard(b.hand_item, who, name, qty, tok["id"]) if who else guard(b.give_new, name, qty, tok["id"])
            if out:
                notify.good(tr(out))
        elif pt:
            guard(b.drop_item, name, qty, pt[0], pt[1], who or None, None, True)
        else:
            guard(b.drop_item, name, qty, t[0], t[1], who or None)

    def _paint_zones(self, p, v, ox, oy, z):
        """Lasting areas (Spirit Guardians, Web, Darkness, walls of fire...) under the tokens."""
        for zone in self.rt.battle.zones_view() if v.get("zones") else []:
            zc = self.zone_carry if self.zone_carry and self.zone_carry["id"] == zone["id"] else None
            sx, sy = (zc["dx"], zc["dy"]) if zc else self.fx.zone_offset(zone["id"]) or (0, 0)    # dragged, or gliding after a move
            tiles = [(x + sx, y + sy) for x, y in zone["tiles"]]
            paint_zone(p, zone, tiles, ox, oy, z, .5 if zone["hidden"] else 1.0)   # hidden from the players: fainter here
            if zone["id"] == self.zone_pick:                 # selected: its outline
                p.setPen(QPen(QColor(SELECTED), 2, Qt.DashLine))
                p.setBrush(Qt.NoBrush)
                for x, y in tiles:
                    p.drawRect(QRectF(ox + x * z + 1, oy + y * z + 1, z - 2, z - 2))
            if tiles and z >= 18:
                x, y = min(tiles, key=lambda t: (t[1], t[0]))
                small = QFont(self.font())
                small.setPixelSize(10)
                p.setFont(small)
                p.setPen(QColor(230, 233, 239, 200))
                text = tr(zone["name"]) + (" 📝" if zone["note"] else "") + (" 👁" if zone["hidden"] else "")
                p.drawText(QRectF(ox + x * z + 2, oy + y * z + 1, z * 6, 12), Qt.AlignLeft | Qt.AlignTop, text)
        p.setBrush(Qt.NoBrush)

    def _paint_aim(self, p, v, ox, oy, z):
        """While aiming: the range around the caster, the area under the pointer and who it reaches (the instructions
        are on the aim bar above the map)."""
        a = self.aim
        item = a["item"]
        me = V.find(v, a["cid"])
        reach = (item.get("target") or {}).get("teleport") or item.get("range")
        if me and me.get("pos") and reach and 0 < reach < 2000:
            k = reach / 5
            s_ = V.span(me)
            p.setPen(QPen(QColor(124, 140, 255, 190), 2, Qt.DashLine))
            p.drawRect(QRectF(ox + (me["pos"][0] - k) * z, oy + (me["pos"][1] - k) * z, (s_ + 2 * k) * z, (s_ + 2 * k) * z))
        p.setPen(QPen(QColor(255, 140, 40, 230), 1))
        p.setBrush(QColor(255, 140, 40, 70))
        for x, y in self.aim_tiles:
            p.drawRect(QRectF(ox + x * z + 0.5, oy + y * z + 0.5, z - 1, z - 1))
        p.setBrush(Qt.NoBrush)
        f = QFont(self.font())
        f.setBold(True)
        p.setFont(f)
        for c in v["combatants"]:
            if c.get("pos") and (c["id"] in a["targets"] or c["id"] in self.aim_ids):
                p.setPen(QPen(QColor(AREA), 3))
                bx, by, bs = V.draw_box(v, c)
                s_ = bs * z
                p.drawEllipse(QRectF(ox + bx * z + 2, oy + by * z + 2, s_ - 4, s_ - 4))
                n = a["targets"].count(c["id"])
                if n > 1:
                    p.drawText(QRectF(ox + bx * z, oy + by * z - 14, s_, 14), Qt.AlignCenter, f"×{n}")

    # ------------------------------------------------------------------ aiming
    def set_aim(self, aim):
        self.aim = aim
        self.aim_tiles, self.aim_ids, self.aim_hover = [], [], None
        if aim:
            self.path, self.path_tile = None, None
            self.setFocus()
            self.setCursor(Qt.CrossCursor)
        else:
            self.setCursor(Qt.ArrowCursor)
        self.update()

    def _aim_point(self, pos):
        z = self.cam["z"]
        return ((pos.x() - self.cam["x"]) / z, (pos.y() - self.cam["y"]) / z)

    def _snap(self, pt):
        """Spheres start on a grid corner (DMG); everything else on the middle of a tile."""
        a = self.aim
        area = a["item"].get("area") or (a["item"].get("target") or {}).get("area")
        if area and area.get("shape") in ("sphere", "cylinder"):
            return [float(round(pt[0])), float(round(pt[1]))]
        return [math.floor(pt[0]) + 0.5, math.floor(pt[1]) + 0.5]

    def _aim_preview(self, pt):
        a = self.aim
        item = a["item"]
        t = item.get("target") or {}
        self.aim_tiles, self.aim_ids = [], []
        if t.get("type") in ("point", "self_area"):
            point = self._snap(pt)
            if item.get("kind") == "spell":
                r = guard(self.rt.battle.cast_check, a["cid"], item["name"], a.get("slot"), None, point) or {}
                self.aim_tiles, self.aim_ids = r.get("tiles") or [], r.get("targets") or []
            else:
                area = item.get("area") or t.get("area")
                me = V.find(self.view, a["cid"]) if self.view else None
                if area and me and me.get("pos"):
                    from ....services.battle import geometry as G
                    m = self.view["map"]
                    tiles = G.area_for(area, me["pos"], V.span(me), tuple(point), m["w"], m["h"], FL.layout(m)[0] if FL.many(m) else 0)
                    self.aim_tiles = sorted(tiles)
                    self.aim_ids = [c["id"] for c in G.creatures_in(tiles, self.view["combatants"]) if c["id"] != me["id"]]
        else:
            c = V.at_tile(self.view, math.floor(pt[0]), math.floor(pt[1])) if self.view else None
            self.aim_ids = [c["id"]] if c else []
        self.update()

    def _aim_click(self, pt):
        a = self.aim
        t = a["item"].get("target") or {}
        if t.get("type") in ("creature", "split"):
            c = V.at_tile(self.view, math.floor(pt[0]), math.floor(pt[1]))
            if not c:
                return
            if t["type"] == "creature" and c["id"] in a["targets"]:
                a["targets"].remove(c["id"])
            else:
                a["targets"].append(c["id"])
            if len(a["targets"]) >= aim_count(a):
                self.owner.commit(a)
                return
            self.update()
            self.owner.render_aimbar()
            return
        a["point"] = self._snap(pt)
        self.owner.commit(a)

    # ------------------------------------------------------------------ play mode: who walks
    def _me(self):
        return V.find(self.view, self.owner.deck.playing_id()) if self.view else None

    def _can_walk(self) -> bool:
        v, me = self.view, self._me()
        return bool(self.playing and v and me and me.get("pos")
                    and (v.get("status") != "active" or v.get("turn") == me["id"]))   # out of combat (before or after): any time

    def _may_carry(self, c) -> bool:
        """Play mode: the played creature's token walks when it may; out of combat any token is picked up and put down."""
        me = self._me()
        return bool(c and (me and c["id"] == me["id"] and self._can_walk() or (self.view or {}).get("status") != "active"))

    # ------------------------------------------------------------------ mouse
    def _at(self, pos):
        return V.at_point(self.view, *tile_point(self, pos)) if self.view else None

    def _start_pan(self, e):
        self.pan = {"px": e.position().x(), "py": e.position().y(), "x": self.cam["x"], "y": self.cam["y"], "moved": False,
                    "button": e.button()}
        self.setCursor(Qt.ClosedHandCursor)

    def mousePressEvent(self, e):
        self.setFocus()
        if self.pinging and e.button() == Qt.LeftButton:     # the ping tool: a click pings, and does nothing else
            self._ping(e.position(), True)
            return
        if self.aim:
            if e.button() == Qt.RightButton:
                self.owner.cancel_aim()
            elif e.button() == Qt.LeftButton:
                self._aim_click(self._aim_point(e.position()))
            return
        if e.button() == Qt.LeftButton and (self.playing or self.tool == "select") and not self._at(e.position()):
            g = self._ground_under(e.position())             # an item on the ground: dragged (Ctrl: one of the stack)
            if g:
                self._start_gcarry(g, e)
                return
        if self.playing:                                     # left-drag pans, except a token that may be carried
            if e.button() == Qt.LeftButton:
                c = self._at(e.position())
                if self._may_carry(c):
                    self._start_drag(c, e.position())
                    return
            if e.button() in (Qt.LeftButton, Qt.RightButton, Qt.MiddleButton):
                self._start_pan(e)
            return
        if e.button() in (Qt.RightButton, Qt.MiddleButton):
            self._start_pan(e)
            return
        if e.button() != Qt.LeftButton:
            return
        if self.tool in ("draw", "free"):
            self.stroke = [tile_point(self, e.position())]
            return
        if self.tool == "room":                              # drag out a box (Shift: erase it out of the rooms); a click on a wall: a door in, or out
            t = self.to_tile(e.position())
            if self.on_map(t):
                self.room_box = (t[0], t[1], t[0], t[1])
                self.room_erase = bool(e.modifiers() & Qt.ShiftModifier)
                self.update()
            return
        if self.tool == "erase":
            self.stroke = None
            self._erase(e.position())
            return
        if self.tool == "place" and self.place:
            t = self.to_tile(e.position())
            if self.on_map(t):
                guard(self.rt.battle.add_symbol, self.place, t[0], t[1])
            return
        c = self._at(e.position())
        d = zn = None
        if not c and self.view:                              # a drawing under the pointer: select it (symbols move)
            pt = tile_point(self, e.position())
            d = guard(self.rt.battle.drawing_at, *pt)
            zn = None if d else guard(self.rt.battle.zone_at, *pt)
        if not (c or d or zn):                               # nowhere: a drag pans, a click lets go of the selection (on release)
            self._start_pan(e)
            return
        self.gpick = None
        if not c:
            self.picked = d["id"] if d else None
            self.zone_pick = zn["id"] if zn else None
            if zn:                                           # a spell's lasting area: selected, and dragged by whole tiles
                self.zone_carry = {"id": zn["id"], "t0": self.to_tile(e.position()), "dx": 0, "dy": 0}
            if d and d["type"] in ("symbol", "room"):        # a room is held where it was grabbed
                t = self.to_tile(e.position())
                self.carry = {"id": d["id"], "tx": d["x"], "ty": d["y"], "from": (d["x"], d["y"]),
                              "ox": t[0] - d["x"] if d["type"] == "room" else 0, "oy": t[1] - d["y"] if d["type"] == "room" else 0}
            elif d and d["type"] == "image":                 # a picture: carried (and turned with the wheel) until let go
                self.carry = {"id": d["id"], "img": True, "x": d["x"], "y": d["y"], "w": d["w"], "h": d["h"],
                              "rot": float(d.get("rot") or 0), "x0": d["x"], "y0": d["y"], "px": pt[0], "py": pt[1], "changed": False}
        else:
            self.picked = self.zone_pick = None
        self.selected = c["id"] if c else None
        if not c:
            self.menu.hide()
            hub().combatant.emit(0)
        else:
            self._start_drag(c, e.position())
        self.update()

    def _start_drag(self, c: dict, pos):
        """Pick up a token: whole tiles for most, any point for a Tiny one (`free`: tx, ty are then the drawn box's corner)."""
        if c.get("tiny"):
            bx, by, _s = V.draw_box(self.view, c)
            px, py = tile_point(self, pos)
            self.drag = {"id": c["id"], "tx": bx, "ty": by, "ok": True, "ox": px - bx, "oy": py - by, "moved": False, "free": True}
            return
        tx, ty = self.to_tile(pos)
        self.drag = {"id": c["id"], "tx": c["pos"][0], "ty": c["pos"][1], "ok": True, "ox": tx - c["pos"][0],
                     "oy": ty - c["pos"][1], "moved": False}

    def _erase(self, pos):
        pt = tile_point(self, pos)
        if self.stroke is None or far_enough(self.stroke[-1], pt, 0.25):
            self.stroke = [pt]
            guard(self.rt.battle.erase_near, *pt)

    def mouseMoveEvent(self, e):
        pos = e.position()
        if self.pinging and not self.pan:
            self._ping(pos, False)
            return
        if self.aim and not self.pan:
            pt = self._aim_point(pos)
            key = (math.floor(pt[0] * 2), math.floor(pt[1] * 2))
            if key != self.aim_hover:
                self.aim_hover = key
                self._aim_preview(pt)
            return
        if self.gcarry:
            self._move_gcarry(pos)
            return
        if not self.playing:
            if self.tool in ("draw", "free") and self.stroke is not None:
                pt = tile_point(self, pos)
                if far_enough(self.stroke[-1], pt):
                    self.stroke.append(pt)
                    self.update()
                return
            if self.tool == "erase" and e.buttons() & Qt.LeftButton:
                self._erase(pos)
                return
            if self.room_box:
                w, h = self.map_size()
                t = self.to_tile(pos)
                band = FL.band(self.view["map"], self.room_box[0]) if self.view else None
                lo, hi = band or (0, w - 1)                  # on the floor the box started on
                box = self.room_box[:2] + (max(lo, min(hi, t[0])), max(0, min(h - 1, t[1])))
                erase = bool(e.modifiers() & Qt.ShiftModifier)
                if box != self.room_box or erase != self.room_erase:
                    self.room_box, self.room_erase = box, erase
                    self.update()
                return
            if self.carry and self.carry.get("img"):
                pt = tile_point(self, pos)
                c = self.carry
                x, y = c["x0"] + pt[0] - c["px"], c["y0"] + pt[1] - c["py"]
                if not (e.modifiers() & Qt.AltModifier):            # snap the corner to the grid when close (Alt: free)
                    x = round(x) if abs(x - round(x)) < .15 else x
                    y = round(y) if abs(y - round(y)) < .15 else y
                if (x, y) != (c["x"], c["y"]):
                    c.update(x=x, y=y, changed=True)
                    self.update()
                return
            if self.carry:
                t = self.to_tile(pos)
                at = (t[0] - self.carry.get("ox", 0), t[1] - self.carry.get("oy", 0))
                if self.on_map(t) and at != (self.carry["tx"], self.carry["ty"]):
                    self.carry.update(tx=at[0], ty=at[1])
                    self.update()
                return
            if self.zone_carry:
                t, zc = self.to_tile(pos), self.zone_carry
                d = (t[0] - zc["t0"][0], t[1] - zc["t0"][1])
                if d != (zc["dx"], zc["dy"]):
                    zc.update(dx=d[0], dy=d[1])
                    self.update()
                return
        if self.pan:
            dx, dy = pos.x() - self.pan["px"], pos.y() - self.pan["py"]
            if abs(dx) + abs(dy) > 4:
                self.pan["moved"] = True
                self.auto_fit = False
            self.cam["x"], self.cam["y"] = self.pan["x"] + dx, self.pan["y"] + dy
            self.update()
            if self.menu.isVisible():
                self.menu.place()
            return
        if self.drag:
            c = V.find(self.view, self.drag["id"])
            if not c:
                self.drag = None
                return
            if self.drag.get("free"):                        # a Tiny token follows the pointer (Shift: snaps)
                half = V.TINY / 2
                cx, cy = free_point(tile_point(self, pos), e.modifiers())
                if not (e.modifiers() & Qt.ShiftModifier):
                    cx, cy = cx - self.drag["ox"] + half, cy - self.drag["oy"] + half
                m = self.view["map"]
                cx, cy = max(0.0, min(m["w"] - 0.01, cx)), max(0.0, min(m["h"] - 0.01, cy))
                self.drag.update(tx=cx - half, ty=cy - half, cx=cx, cy=cy, moved=True,
                                 ok=V.tile_free(self.view, c["id"], int(cx), int(cy)))
                if self._walks(c["id"]):
                    self._hover_path((int(cx), int(cy)), dragging=True)
                self.update()
                return
            tx, ty = self.to_tile(pos)
            nx, ny = V.clamp_tile(self.view, c, tx - self.drag["ox"], ty - self.drag["oy"])
            if (nx, ny) != (self.drag["tx"], self.drag["ty"]) or self.drag["moved"]:
                self.drag.update(tx=nx, ty=ny, moved=True, ok=V.tile_free(self.view, c["id"], nx, ny))
                if self._walks(c["id"]):                     # the played creature: its way there and the opportunity attacks on it
                    self._hover_path((nx, ny), dragging=True)
                self.update()
            return
        c = self._at(pos)
        gi = None if c else self._ground_under(pos)
        zn = None if c or gi or not self.view or not self.view.get("zones") else guard(self.rt.battle.zone_at, *tile_point(self, pos))
        key = c["id"] if c else ("ground", gi["id"]) if gi else ("zone", zn["id"]) if zn else None
        if key != self.hover:
            if any(o.get("concentrating") and o["id"] in (key, self.hover) for o in (self.view or {}).get("combatants") or []):
                self.update()                                # a concentrating caster: its links show while hovered
            self.hover = key
            if (gi["id"] if gi else None) != self.ghover:   # an item on the ground: its name over it
                self.ghover = gi["id"] if gi else None
                self.update()
            self.setCursor(Qt.OpenHandCursor if (c and (not self.playing or self._may_carry(c))) or gi else Qt.ArrowCursor)
            if c:
                QToolTip.showText(e.globalPosition().toPoint(), token_card(self.view, c), self)
            elif zn:
                QToolTip.showText(e.globalPosition().toPoint(), self._zone_tip(zn), self)
            else:
                QToolTip.hideText()
        if self.playing:
            self._hover_path(self.to_tile(pos))

    def _hover_path(self, t, dragging=False):
        """Play mode: the path to the hovered tile (or to where the played creature's token is being dragged), its cost in
        feet and the opportunity attacks it would draw."""
        if t == self.path_tile:
            return
        self.path_tile = t
        self.path = None
        if self._can_walk() and self.on_map(t) and (list(t) != list(self._me()["pos"]) if dragging else not V.at_tile(self.view, *t)):
            pv = guard(self.rt.battle.path_preview, self._me()["id"], t[0], t[1]) or {}
            if pv.get("path"):
                self.path = (pv["path"], pv["cost"], pv["ok"], pv.get("why"), pv.get("threats") or [])
        self.update()

    def leaveEvent(self, e):
        if self.pinging and self.ping_at is not None:        # off the map: the players' ring goes
            self.ping_at, self._ping_due = None, None
            self._send_ping(None)
            self.update()
        if self.path or self.ghover is not None:
            self.path, self.path_tile, self.ghover, self.hover = None, None, None, None
            self.update()
        super().leaveEvent(e)

    def mouseReleaseEvent(self, e):
        if self.aim:
            return
        if self.gcarry and e.button() == Qt.LeftButton:
            self._drop_gcarry(e.position())
            return
        if not self.playing:
            if self.tool in ("draw", "free") and self.stroke is not None and e.button() == Qt.LeftButton:
                pts, self.stroke = self.stroke, None
                if self.tool == "draw" and len(pts) == 1:    # a click on a wall (a room's or a drawn one): a door in, or out
                    guard(self.rt.battle.door_on_wall, *pts[0])
                else:
                    guard(self.rt.battle.draw_path, pts, self.ink, 3, self.tool == "draw", self.owner.drawbar.line_cover())
                self.update()
                return
            if self.tool == "erase" and e.button() == Qt.LeftButton:
                self.stroke = None
                return
            if self.room_box and e.button() == Qt.LeftButton:
                box, self.room_box, self.room_erase = self.room_box, None, False
                if e.modifiers() & Qt.ShiftModifier:         # Shift: those tiles erased out of the rooms
                    if not guard(self.rt.battle.erase_rooms, *box):
                        notify.info(tr("No room there to erase from."))
                elif box[:2] != box[2:]:
                    guard(self.rt.battle.add_room, *box, self.owner.drawbar.room_doors())
                else:                                        # a click: on a room's wall, a door put in or taken off
                    put = guard(self.rt.battle.door_on_wall, *tile_point(self, e.position()))
                    if put is None:
                        notify.info(tr("Drag out a box to make a room. Click a room's wall to put a door in (or take it out)."))
                self.update()
                return
            if self.carry and self.carry.get("img"):
                c, self.carry = self.carry, None
                if c["changed"]:
                    guard(self.rt.battle.set_image, c["id"], x=c["x"], y=c["y"], w=c["w"], h=c["h"], rot=c["rot"])
                self.update()
                return
            if self.carry:
                c, self.carry = self.carry, None
                if (c["tx"], c["ty"]) != c["from"]:
                    guard(self.rt.battle.move_drawing, c["id"], c["tx"], c["ty"])
                self.update()
                return
            if self.zone_carry:
                zc, self.zone_carry = self.zone_carry, None
                if zc["dx"] or zc["dy"]:
                    guard(self.rt.battle.shift_zone, zc["id"], zc["dx"], zc["dy"])
                self.update()
                return
        if self.pan:
            pan, self.pan = self.pan, None
            self.setCursor(Qt.ArrowCursor)
            if pan["moved"]:
                return
            c = self._at(e.position())
            if pan["button"] == Qt.RightButton and c:            # right-click a token: its menu
                self._token_menu(c, e.globalPosition().toPoint())
                return
            g = self._ground_under(e.position()) if pan["button"] == Qt.RightButton else None
            if g:                                                # an item on the ground: give, amount, erase
                self._ground_menu(g, e.globalPosition().toPoint())
                return
            if pan["button"] == Qt.RightButton and self.view and self.playing:      # play mode: a door or window opened or shut
                self._door_menu(tile_point(self, e.position()), e.globalPosition().toPoint())
                return
            if pan["button"] == Qt.RightButton and self.view and not self.playing:   # a picture's, symbol's, area's menu
                pt = tile_point(self, e.position())
                at = e.globalPosition().toPoint()
                d = guard(self.rt.battle.drawing_at, *pt, 0.45, True)
                if d and d["type"] in ("image", "symbol"):
                    self.picked, self.zone_pick = d["id"], None
                    self.update()
                    (self._image_menu if d["type"] == "image" else self._symbol_menu)(d, at)
                    return
                drawings = self.view.get("drawings") or []
                edge = R.nearest_wall(drawings, *pt) or (R.door_edge(d) if d and d["type"] == "door" else None)
                if edge:                                     # a room's wall: a door, window... in it; things beside it
                    self._wall_menu(edge, pt, at)
                    return
                if d and d["type"] == "path":                # a drawn line: full, half or no cover
                    self.picked, self.zone_pick = d["id"], None
                    self.update()
                    self._line_menu(d, at)
                    return
                zn = guard(self.rt.battle.zone_at, *pt)
                if zn:
                    self.picked, self.zone_pick = None, zn["id"]
                    self.update()
                    self._zone_menu(zn, at)
                elif self.on_map(self.to_tile(e.position())):  # an empty tile: things to put on it
                    self._place_menu(self.to_tile(e.position()), at)
                return
            if pan["button"] != Qt.LeftButton:
                return
            t = self.to_tile(e.position())
            if self.playing and c:                           # play mode: a click selects a creature...
                self.selected, self.gpick = c["id"], None
                hub().combatant.emit(c["id"])
                self.update()
            elif self.playing and self._can_walk() and self.on_map(t):   # ... or walks
                self.owner.walk(*t)
            else:                                            # a click on nowhere: nothing selected (the Inspector steps aside)
                self.deselect()
            return
        if not self.drag:
            return
        d, self.drag = self.drag, None
        self.path, self.path_tile = None, None               # the dragged way's preview goes (the hover's comes back on the next move)
        c = V.find(self.view, d["id"]) if self.view else None
        if d.get("free"):
            self._drop_free(d, c)
            return
        walks = self._walks(d["id"])
        if not d["moved"]:
            if not self.playing:
                self.menu.open(d["id"])
            elif not walks:                                  # play mode: a click on another creature selects it
                self.selected = d["id"]
            hub().combatant.emit(d["id"])
        elif d["ok"] and c and [d["tx"], d["ty"]] != list(c["pos"]):
            if walks:                                        # the played creature walks (movement, opportunity attacks, zones)
                self.owner.walk(d["tx"], d["ty"])
            else:                                            # edit mode / out of combat: put there, nothing triggers
                guard(self.rt.battle.place, d["id"], d["tx"], d["ty"])
        self.update()

    def _walks(self, cid: int) -> bool:
        """Only the played creature's token walks (play mode); everything else carried is put down where it's let go."""
        me = self._me() if self.playing else None
        return bool(me and me["id"] == cid)

    def _drop_free(self, d: dict, c):
        """A Tiny token let go: the played creature walks to the tile (movement, opportunity attacks), then stands on the
        point; anything else is put there."""
        b = self.rt.battle
        walking = self._walks(d["id"])
        if not d["moved"]:
            if not self.playing:
                self.menu.open(d["id"])
            elif not walking:
                self.selected = d["id"]
            hub().combatant.emit(d["id"])
        elif d["ok"] and c and "cx" in d:
            tile = [int(d["cx"]), int(d["cy"])]
            if walking and tile != list(c["pos"]):
                self.owner.walk(*tile)
            now = next((x for x in b.state()["combatants"] if x["id"] == d["id"]), {})
            if now.get("pos") == tile or not walking:        # it got there: stand on the very point
                guard(b.place, d["id"], d["cx"], d["cy"], True)
        self.update()

    def _token_menu(self, c: dict, at):
        self.selected = c["id"]
        hub().combatant.emit(c["id"])
        self.update()
        combatant_menu(self, [c], self.owner.deck.play).exec(at)

    def mouseDoubleClickEvent(self, e):
        if e.button() != Qt.LeftButton or self.aim:
            return
        c = self._at(e.position())
        if c:                                                # its character sheet or stat block, in the Inspector
            self.drag = None
            self.selected = c["id"]
            open_creature(self, c)
            return
        if self.zone_pick and self.tool == "select" and not self.playing:
            self.zone_carry = None
            zn = next((z for z in self.rt.battle.zones_view() if z["id"] == self.zone_pick), None)
            if zn:
                self._edit_zone(zn)
            return
        d = next((x for x in (self.view or {}).get("drawings") or [] if x["id"] == self.picked), None) if self.picked else None
        if d and d["type"] == "door" and not self.playing:  # a room's door: opened or shut
            self.carry = None
            guard(self.rt.battle.toggle_door, d["id"])

    def wheelEvent(self, e):
        c = self.carry
        if c and c.get("img"):                               # holding a picture: the wheel turns it (Shift: sizes it)
            step = e.angleDelta().y() or e.angleDelta().x()
            if not step:
                return
            up = step > 0
            if e.modifiers() & Qt.ShiftModifier:
                k = 1.08 if up else 1 / 1.08                 # about its middle, keeping its shape
                if min(c["w"], c["h"]) * k < .2:
                    return
                old = (c["x"], c["y"])
                cx, cy = c["x"] + c["w"] / 2, c["y"] + c["h"] / 2
                c["w"], c["h"] = c["w"] * k, c["h"] * k
                c["x"], c["y"] = cx - c["w"] / 2, cy - c["h"] / 2
                c["x0"] += c["x"] - old[0]                   # the pointer keeps holding the same spot
                c["y0"] += c["y"] - old[1]
            else:
                c["rot"] = (c["rot"] + (1 if e.modifiers() & Qt.ControlModifier else 15) * (1 if up else -1)) % 360
            c["changed"] = True
            self.update()
            e.accept()
            return
        f = 1.15 if e.angleDelta().y() > 0 else 1 / 1.15
        self.zoom_at(f, e.position().x(), e.position().y())

    def keyReleaseEvent(self, e):
        if self.room_box and e.key() == Qt.Key_Shift and self.room_erase:
            self.room_erase = False                          # Shift let go mid-drag: a room again
            self.update()
        super().keyReleaseEvent(e)

    def keyPressEvent(self, e):
        if self.pinging and e.key() == Qt.Key_Escape:
            self.owner.set_ping(False)
            return
        if self.room_box and e.key() == Qt.Key_Shift:
            self.room_erase = True                           # Shift held mid-drag: erasing
            self.update()
            return
        if self.aim:
            if e.key() == Qt.Key_Escape:
                self.owner.cancel_aim()
                return
            if e.key() in (Qt.Key_Return, Qt.Key_Enter):
                if self.aim.get("pick") and not self.aim["targets"]:      # the target the aim bar offers
                    pick_target(self.owner, self.aim, self.aim["pick"])
                else:
                    self.owner.commit(self.aim)
                return
        if self.playing and Qt.Key_1 <= e.key() <= Qt.Key_9 and not (e.modifiers() & ~Qt.KeypadModifier):
            if self.owner.deck.hotkey(e.key() - Qt.Key_0):      # 1-9: the play bar's first nine, like a game's hotbar
                return
        if self.selected and e.key() in (Qt.Key_D, Qt.Key_H) and not e.modifiers():
            self.menu.open(self.selected, focus=True)        # D / H: the amount box of the selected token, ready to type
            return
        if self.picked and e.key() == Qt.Key_O:
            self._toggle_open(self.picked)
            return
        if self.picked and e.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            did, self.picked = self.picked, None
            guard(self.rt.battle.erase, did)
            return
        if self.gpick and e.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            gid, self.gpick = self.gpick, None
            guard(self.rt.battle.erase_ground, gid)
            return
        if self.zone_pick and e.key() in (Qt.Key_Delete, Qt.Key_Backspace):
            zid, self.zone_pick = self.zone_pick, None
            guard(self.rt.battle.end_zone, zid)
            return
        pic = next((d for d in (self.view or {}).get("drawings") or [] if d["id"] == self.picked and d["type"] == "image"), None)
        if pic and e.key() == Qt.Key_R:
            guard(self.rt.battle.set_image, pic["id"], rot=float(pic.get("rot") or 0) + (-90 if e.modifiers() & Qt.ShiftModifier else 90))
            return
        if pic and e.key() in (Qt.Key_PageUp, Qt.Key_PageDown):
            guard(self.rt.battle.restack, pic["id"], "up" if e.key() == Qt.Key_PageUp else "down")
            return
        if self.picked and e.key() == Qt.Key_R and any(d["id"] == self.picked and d["type"] == "symbol"
                                                       for d in (self.view or {}).get("drawings") or []):
            guard(self.rt.battle.rotate_symbol, self.picked)
            return
        if e.key() == Qt.Key_Escape and self.place:
            self.owner.drawbar.arm(None)
            return
        if e.key() == Qt.Key_Delete and self.selected:
            c = V.find(self.view or {}, self.selected)
            self.selected = None
            self.menu.hide()
            hub().combatant.emit(0)
            if c and guard(lambda: (self.rt.battle.remove(c["id"]), True)[1]):
                notify.info(tr("{0} removed. Ctrl+Z brings it back.", c["name"]))
            return
        if e.key() == Qt.Key_Escape:
            if self.menu.isVisible():
                self.menu.hide()
            else:
                self.deselect()
            return
        super().keyPressEvent(e)

    # ------------------------------------------------------------------ pictures
    def _image_menu(self, d: dict, at):
        """Right-click on a picture: its layer, its place in the layer, lock, hide from the players, turn, fit, erase."""
        b = self.rt.battle
        m = QMenu(self)
        lay = m.addMenu(tr("Layer"))
        for key, text in (("ground", tr("Ground: under the grid (a battle map)")), ("map", tr("Map: with the drawings, under the tokens")),
                          ("top", tr("Top: over the tokens (a roof, a canopy)"))):
            a = lay.addAction(text, lambda k=key: guard(b.set_image, d["id"], layer=k))
            a.setCheckable(True)
            a.setChecked(d.get("layer", "map") == key)
        order = m.addMenu(tr("Order in its layer"))
        for key, text in (("front", tr("Bring to front")), ("up", tr("Bring forward (Page Up)")), ("down", tr("Send backward (Page Down)")),
                          ("back", tr("Send to back"))):
            order.addAction(text, lambda k=key: guard(b.restack, d["id"], k))
        m.addSeparator()
        a = m.addAction(tr("Locked (clicks go through it)"), lambda: guard(b.set_image, d["id"], locked=not d.get("locked")))
        a.setCheckable(True)
        a.setChecked(bool(d.get("locked")))
        a = m.addAction(tr("Hidden from the players"), lambda: guard(b.set_image, d["id"], hidden=not d.get("hidden")))
        a.setCheckable(True)
        a.setChecked(bool(d.get("hidden")))
        m.addSeparator()
        m.addAction(tr("Turn 90° (R)"), lambda: guard(b.set_image, d["id"], rot=float(d.get("rot") or 0) + 90))
        m.addAction(tr("Straighten"), lambda: guard(b.set_image, d["id"], rot=0))
        m.addAction(tr("Fit to the map"), lambda: self._fit_image(d))
        m.addSeparator()
        m.addAction(tr("Erase (Delete)"), lambda: (setattr(self, "picked", None), guard(b.erase, d["id"])))
        m.exec(at)

    # ------------------------------------------------------------------ rooms: the wall's menu, things to put down
    def _wall_menu(self, edge: tuple, pt: tuple, at):
        """Right-click on a room's wall: what stands in it (open or shut it, take it out), a door, window, archway...
        to put in (or change it to), things to put on the floor beside it, the room. Hovering one shows it on the map."""
        b = self.rt.battle
        drawings = self.view.get("drawings") or []
        here = next((d for d in drawings if d["type"] == "door" and R.door_edge(d) == edge), None)
        tile, rot = R.inside_tile(drawings, edge, *pt)
        m = QMenu(self)
        if here:
            self.picked, self.zone_pick = here["id"], None
            kind = R.kind_of(here)
            menu_head(m, tr(R.WALL_KINDS[kind][0]))
            if R.WALL_KINDS[kind][1]:
                m.addAction(open_text(here), lambda: self._toggle_open(here["id"]))
            m.addAction(tr("Take it out (a plain wall)"), lambda: (setattr(self, "picked", None), guard(b.put_in_wall, *edge, None)))
        menu_head(m, tr("Change it to") if here else tr("Put in the wall"))
        for kind, (name, _opens) in R.WALL_KINDS.items():
            if here and kind == R.kind_of(here):
                continue
            a = m.addAction(QIcon(wall_icon(kind)), tr(name), lambda k=kind: guard(b.put_in_wall, *edge, k))
            a.setData(("wall", edge, kind))
        line = next((d for d in drawings if R.built(d) and edge in R.path_edges(d["pts"], d.get("closed"))), None)
        if line:                                             # a wall drawn with the draw tool: it can be a cover line instead
            self._cover_items(m, line)
        self._place_items(m, tile, rot)
        self._room_items(m, tile)
        self._run_menu(m, at)

    def _place_menu(self, tile: tuple, at):
        """Right-click on an empty tile: things to put on it, and its room."""
        m = QMenu(self)
        self._place_items(m, tile, 0)
        self._room_items(m, tile)
        f = FL.floor_at(self.view["map"], tile[0]) if FL.many(self.view["map"]) else 0
        if f:
            menu_head(m, floor_name(f))
            m.addAction(tr("Remove this floor…"), lambda: dialogs.confirm(
                self, tr("Remove {0} and everything on it? (Ctrl+Z brings it back)", floor_name(f)), tr("Remove a floor"))
                and guard(self.rt.battle.remove_floor, f))
        self._run_menu(m, at)

    PLACE = ("stairs_up", "stairs_down", "ink_stairs", "ink_ladder_down", "chest", "trap", "ink_pillar", "ink_statue", "ink_altar",
             "lever", "ink_campfire", "ink_light")

    def _place_items(self, m: QMenu, tile: tuple, rot: int):
        """The common things (stairs, a chest, a trap, a pillar...) to put on `tile`, turned to face away from the wall
        beside it, then the quick bar's other ones."""
        b = self.rt.battle
        menu_head(m, tr("Place on {0}", f"{col_name(tile[0])}{tile[1] + 1}"))

        def add(menu, key):
            a = menu.addAction(QIcon(asset_icon(key, 22)), asset_name(key), lambda: guard(b.add_symbol, key, tile[0], tile[1], rot))
            a.setData(("place", key, tile, rot))
        for key in self.PLACE:
            if asset_known(key):
                add(m, key)
        more = [k for k in quick_keys() if k not in self.PLACE]
        if more:
            sub = m.addMenu(tr("From the quick bar"))
            for key in more:
                add(sub, key)

    def _room_items(self, m: QMenu, tile: tuple):
        b = self.rt.battle
        rooms = [d for d in (self.view or {}).get("drawings") or [] if d["type"] == "room"
                 and d["x"] <= tile[0] < d["x"] + d["w"] and d["y"] <= tile[1] < d["y"] + d["h"]
                 and (tile[0] - d["x"], tile[1] - d["y"]) not in R.cut_of(d)]
        for d in rooms[-1:]:
            menu_head(m, tr("Room {0} × {1}", d["w"], d["h"]))
            m.addAction(tr("Erase the room"), lambda d=d: (setattr(self, "picked", None), guard(b.erase, d["id"])))

    def _run_menu(self, m: QMenu, at):
        """Show the menu; the door, window or thing under the pointer in it shows on the map until it closes."""
        for menu in [m] + [a.menu() for a in m.actions() if a.menu()]:
            menu.hovered.connect(self._preview_action)
        m.aboutToHide.connect(lambda: self._preview_action(None))
        self.update()
        m.exec(at)
        self.preview = None
        self.update()

    def _preview_action(self, action):
        data = action.data() if action is not None else None
        data = data if isinstance(data, tuple) else None
        if data != self.preview:
            self.preview = data
            self.update()

    def _paint_preview(self, p, ox, oy, z):
        """The hovered menu item, on the map: a door, window... in its wall, or a thing on its tile."""
        pv = self.preview
        if pv[0] == "wall":
            (x, y, v), kind = pv[1], pv[2]
            paint_wall_preview(p, {"x": x, "y": y, "v": v, "kind": kind, "open": False}, ox, oy, z)
            return
        _w, key, (x, y), rot = pv
        p.setOpacity(0.75)
        paint_drawings(p, [{"type": "symbol", "id": -1, "sym": key, "x": x, "y": y, "rot": rot}], ox, oy, z, None, self.font())
        p.setOpacity(1.0)
        n = props.span(key)
        p.setPen(QPen(QColor(124, 140, 255, 230), 2, Qt.DashLine))
        p.setBrush(Qt.NoBrush)
        p.drawRect(QRectF(ox + x * z + 1, oy + y * z + 1, n * z - 2, n * z - 2))

    def _openable_at(self, pt: tuple):
        """The door, window, gate... under a point (tile units) that opens: one in a wall, or a symbol or prop."""
        drawings = (self.view or {}).get("drawings") or []
        edge = R.nearest_wall(drawings, *pt)
        here = next((d for d in drawings if edge and d["type"] == "door" and R.door_edge(d) == edge), None)
        if here and R.WALL_KINDS[R.kind_of(here)][1]:
            return here
        tile = (math.floor(pt[0]), math.floor(pt[1]))
        return next((d for d in reversed(drawings) if d["type"] == "symbol" and d.get("sym") in props.OPENS
                     and d["x"] <= tile[0] < d["x"] + props.span(d["sym"]) and d["y"] <= tile[1] < d["y"] + props.span(d["sym"])), None)

    def _door_menu(self, pt: tuple, at):
        """Play mode, right-click on a door or window: open it or shut it."""
        d = self._openable_at(pt)
        if d is None:
            return
        m = QMenu(self)
        name = R.WALL_KINDS[R.kind_of(d)][0] if d["type"] == "door" else asset_name(d["sym"])
        menu_head(m, tr(name))
        m.addAction(open_text(d), lambda: self._toggle_open(d["id"]))
        m.exec(at)

    def _toggle_open(self, did: int):
        opened = guard(self.rt.battle.toggle_door, did)
        if opened is not None:
            notify.info(tr("Opened.") if opened else tr("Shut."))

    def _line_menu(self, d: dict, at):
        """Right-click on a drawn line: what it is on the battlefield (a wall, full, half or no cover), erase."""
        m = QMenu(self)
        self._cover_items(m, d)
        m.addSeparator()
        m.addAction(tr("Erase (Delete)"), lambda: (setattr(self, "picked", None), guard(self.rt.battle.erase, d["id"])))
        m.exec(at)

    def _cover_items(self, m: QMenu, d: dict):
        menu_head(m, tr("This line"))
        now = R.cover_of(d)
        for key, text in LINE_COVER_TEXT:
            if key == "wall" and not (R.built(d) or all(float(x).is_integer() and float(y).is_integer() for x, y in d["pts"])):
                continue                                     # (a free stroke can't be a room's kind of wall)
            a = m.addAction(tr(text), lambda k=key: guard(self.rt.battle.set_cover, d["id"], k))
            a.setCheckable(True)
            a.setChecked(now == key)

    def _symbol_menu(self, d: dict, at):
        """Right-click on a map symbol or a prop: turn, open (doors, windows, gates), erase."""
        b = self.rt.battle
        m = QMenu(self)
        if d.get("sym") in props.OPENS:
            m.addAction(open_text(d), lambda: self._toggle_open(d["id"]))
        m.addAction(tr("Turn 90° (R)"), lambda: guard(b.rotate_symbol, d["id"]))
        m.addSeparator()
        dmg = d.get("throw_dmg") or default_throw_damage(d.get("sym", ""))
        a = m.addAction(tr("Throwable ({0} bludgeoning)", dmg), lambda: guard(b.set_throwable, d["id"], not d.get("throw")))
        a.setCheckable(True)
        a.setChecked(bool(d.get("throw")))
        a.setToolTip(tr("Creatures next to it can throw it with the Throw action"))

        def damage():
            text = dialogs.ask_text(self, tr("Throw damage"), tr("Damage when it hits (dice, bludgeoning):"), dmg)
            if text is not None:
                guard(b.set_throwable, d["id"], True, text.strip())
        m.addAction(tr("Throw damage…"), damage)
        m.addSeparator()
        m.addAction(tr("Erase (Delete)"), lambda: (setattr(self, "picked", None), guard(b.erase, d["id"])))
        m.exec(at)

    # ------------------------------------------------------------------ lasting areas (spell marks)
    def _zone_tip(self, zn: dict) -> str:
        owner = V.find(self.view, zn["owner"]) if zn.get("owner") else None
        bits = [f"<b>{tr(zn['name'])}</b>"]
        if owner:
            bits.append(tr("by {0}", owner["name"]))
        bits.append(tr("{0} rounds left", zn["rounds"]) if zn.get("rounds") is not None else tr("until taken off"))
        if zn.get("hidden"):
            bits.append(tr("hidden from the players"))
        if zn.get("note"):
            bits.append("<i>" + html.escape(zn["note"]).replace("\n", "<br>") + "</i>")
        if not self.playing:
            bits.append(tr("Drag: move · double-click: edit · right-click: menu · Del: take off"))
        return "<br>".join(bits)

    def _zone_menu(self, zn: dict, at):
        """Right-click on a lasting area: edit (name, note, rounds), hide from the players, take it off the map."""
        b = self.rt.battle
        m = QMenu(self)
        m.addAction(tr("Edit name, note, rounds…"), lambda: self._edit_zone(zn))
        a = m.addAction(tr("Hidden from the players"), lambda: guard(b.edit_zone, zn["id"], hidden=not zn.get("hidden")))
        a.setCheckable(True)
        a.setChecked(bool(zn.get("hidden")))
        m.addSeparator()
        m.addAction(tr("Take it off the map (Delete)"), lambda: (setattr(self, "zone_pick", None), guard(b.end_zone, zn["id"])))
        m.exec(at)

    def _edit_zone(self, zn: dict):
        dialogs.form(self, tr("Edit {0}", tr(zn["name"])), [
            {"key": "name", "label": tr("Name"), "value": zn["name"], "required": True},
            {"key": "note", "label": tr("Note"), "kind": "multiline", "value": zn.get("note", "")},
            {"key": "rounds", "label": tr("Rounds left (0: until taken off)"), "kind": "int", "value": zn.get("rounds") or 0, "min": 0,
             "max": 10000},
            {"key": "hidden", "label": tr("Hidden from the players"), "kind": "check", "value": bool(zn.get("hidden"))}],
            submit=lambda v: self.rt.battle.edit_zone(zn["id"], name=v["name"], note=v["note"], rounds=v["rounds"] or None,
                                                       hidden=v["hidden"]))

    def _fit_image(self, d: dict):
        """The picture over the whole floor it lies on."""
        m = self.view["map"]
        w, h, a = FL.layout(m)[0], m["h"], FL.left(m, FL.nearest(m, d["x"] + d["w"] / 2))
        k = min(w / d["w"], h / d["h"])
        nw, nh = d["w"] * k, d["h"] * k
        guard(self.rt.battle.set_image, d["id"], w=nw, h=nh, x=a + (w - nw) / 2, y=(h - nh) / 2, rot=0)

    def add_pictures(self, files, at):
        """Picture files onto the map, centred on `at` (tile units), a little apart when there are several."""
        added = 0
        for i, path in enumerate(files):
            try:
                data, ext, pw, ph = encode_image(path)
            except ValueError as err:
                notify.error(str(err))
                continue
            if guard(self.rt.battle.add_image, data, ext, pw, ph, at[0] + i * .6, at[1] + i * .6, os.path.basename(path)):
                added += 1
        if added:
            notify.good(tr("Picture on the map: players see it too.") if added == 1 else tr("{0} pictures on the map.", added))

    @staticmethod
    def _picture_files(e) -> list:
        md = e.mimeData()
        if not md.hasUrls():
            return []
        return [u.toLocalFile() for u in md.urls() if u.isLocalFile() and u.toLocalFile().lower().rsplit(".", 1)[-1] in IMAGE_FILES]

    # ------------------------------------------------------------------ drops from the other battle windows
    def _payload(self, e):
        try:
            return json.loads(bytes(e.mimeData().data(DRAG_MIME)).decode())
        except ValueError:
            return None

    def dragEnterEvent(self, e):
        if e.mimeData().hasFormat(DRAG_MIME) or self._picture_files(e):
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        if self._picture_files(e):
            e.acceptProposedAction()
            return
        if not e.mimeData().hasFormat(DRAG_MIME):
            return
        t = self.to_tile(e.position())
        self.ghost = t if self.on_map(t) else None
        e.acceptProposedAction()
        self.update()

    def dragLeaveEvent(self, _e):
        self.ghost = None
        self.update()

    def dropEvent(self, e):
        self.ghost = None
        self.update()
        files = self._picture_files(e)
        if files:                                            # picture files from the desktop or a folder
            e.acceptProposedAction()
            self.add_pictures(files, tile_point(self, e.position()))
            return
        payload = self._payload(e)
        t = self.to_tile(e.position())
        if not payload:
            return
        if not self.on_map(t):
            notify.error(tr("Drop it on a tile of the map."))
            return
        e.acceptProposedAction()
        b = self.rt.battle
        if payload.get("kind") == "monster":
            if guard(b.add_enemy, payload["id"], int(payload.get("count") or 1), None, payload.get("hp_mode") or "average",
                     None, True, list(t)):
                notify.good(tr("Added to the battle."))
        elif payload.get("kind") == "combatant":
            guard(b.place, payload["id"], t[0], t[1])
        elif payload.get("kind") == "symbol":
            guard(b.add_symbol, payload["sym"], t[0], t[1])
        elif payload.get("kind") == "team_item":                  # from the team inventory (more than one: how many)
            from ..characters.team import how_many
            n = 1 if e.keyboardModifiers() & Qt.ControlModifier else how_many(self, payload["item"], int(payload.get("qty") or 1))
            tok = V.at_point(self.view, *tile_point(self, e.position())) if self.view else None
            if n and tok:
                out = guard(self.rt.team.hand, payload["item"], n, tok["id"])
                if out:
                    notify.good(tr(out))
            elif n:
                pt = free_point(tile_point(self, e.position()), e.keyboardModifiers())
                guard(self.rt.team.drop, payload["item"], n, pt[0], pt[1], None, True)
        elif payload.get("kind") in ("item", "inv_item"):         # from the library or a sheet's inventory (Ctrl: one)
            self._drop_item(payload, t, bool(e.keyboardModifiers() & Qt.ControlModifier),
                            free_point(tile_point(self, e.position()), e.keyboardModifiers()))


def floor_name(f: int) -> str:
    return tr("Main floor") if f == 0 else tr("Floor +{0}", f) if f > 0 else tr("Floor −{0}", -f)


def menu_head(m: QMenu, text: str):
    """A heading in a menu (a section's own title isn't drawn by every style): a bold line that can't be picked."""
    if not m.isEmpty():
        m.addSeparator()
    a = m.addAction(text)
    a.setEnabled(False)
    f = a.font()
    f.setBold(True)
    a.setFont(f)


def fold_strip(text: str, on_click, tip: str):
    """The thin bar at the map's edge standing in for a pane folded away: a click folds it out again."""
    b = tool_button(text, on_click, tip=tip)
    b.setFixedWidth(18)
    b.setSizePolicy(QSizePolicy.Fixed, QSizePolicy.Expanding)
    return b


@panel("battle.map", "Battle map", "Battle", icon="🗺", area="center",
       description="The battle map with its initiative order; what's selected on it shows in the Inspector. Edit: tokens, "
                   "walls, props, pictures and creatures from the drawer beside it. Play: the turn's creature played like "
                   "a player plays theirs - its action bar, aiming with range and area previews, click to walk; "
                   "reactions pop up on the map.")
class BattleMapPanel(Panel):
    fits_itself = True               # no dock scroll area: in a short dock the map shrinks and the action bar stays in sight

    def build(self):
        self.mode = "edit"
        self.aim = None
        self.pending_key = None
        self.drawer_open = {"edit": True, "play": False}
        self.side_open = True
        self.drawer_pages = {}
        self._status = None
        self.deck = PlayDeck(self)
        self.canvas = MapCanvas(self)
        self.host = MapHost(self.canvas)
        # ---- the top bar: mode, drawer, camera, map size, hints
        self.edit_btn = button(tr("✏ Edit"), lambda: self.set_mode("edit"), checkable=True,
                               tip=tr("Set the scene: move any token, draw, place props and creatures (Ctrl+E switches)"))
        self.play_btn = button(tr("▶ Play"), lambda: self.set_mode("play"), checkable=True,
                               tip=tr("Run the fight: play the turn's creature with its action bar (Ctrl+E switches)"))
        modes = QButtonGroup(self)
        modes.addButton(self.edit_btn)
        modes.addButton(self.play_btn)
        self.drawer_btn = button("🧰", self._toggle_drawer, kind="flat", checkable=True, width=30,
                                 tip=tr("Drawer: fold out or away the bestiary, the props and the items to drag onto the map"))
        self.side_btn = button("⚔", self._toggle_side, kind="flat", checkable=True, width=30,
                               tip=tr("Initiative: fold out or away the initiative order under the map"))
        self.paint_btn = button("🎨", lambda: self._show_paint(not self.paint_open), kind="flat", checkable=True, width=30,
                                tip=tr("Paint tools: fold out or away the rooms, drawing, props and pictures bar"))
        self.paint_open = True
        self.paint_btn.setChecked(True)
        self.w = spin(30, 5, 80, width=48, tip=tr("Map width in tiles"))
        self.h = spin(20, 5, 80, width=48, tip=tr("Map height in tiles"))
        self.w.lineEdit().returnPressed.connect(self._set_size)
        self.h.lineEdit().returnPressed.connect(self._set_size)
        self.settings_btn = self._settings_button()
        self.hint = tool_button("ⓘ")                         # how the mode works: on hover
        self.ping_btn = button("📍", lambda: self.set_ping(self.ping_btn.isChecked()), kind="flat", checkable=True, width=30,
                               tip=tr("Ping: the players see your pointer on their map as a ring; click to ping a spot "
                                      "(rings ripple out from it). Right-drag still moves the map. Esc stops."))
        self.duel_btn = button("🤺 " + tr("Duel"), self._duel_click, kind="flat", checkable=True,
                               tip=tr("Show the duel's own map here instead of the campaign's battle (every tool works on "
                                      "it; the campaign's battle goes on untouched). Opens the Duel window when no duel is open."))
        bar = row(self.edit_btn, self.play_btn, 8, self.drawer_btn, self.side_btn, self.paint_btn, self.ping_btn, self.duel_btn, 8,
                  button("＋", lambda: self.canvas.zoom_at(1.25), kind="flat", width=30, tip=tr("Zoom in (wheel)")),
                  button("－", lambda: self.canvas.zoom_at(0.8), kind="flat", width=30, tip=tr("Zoom out (wheel)")),
                  button("⤢", self.canvas.fit, kind="flat", width=30, tip=tr("Fit: show the whole map")),
                  button("◎", self.canvas.fit_creatures, kind="flat", width=30, tip=tr("Zoom to the creatures on the map")),
                  stretch(), self.hint, self.settings_btn)
        self.layout().addLayout(bar)
        self.drawbar = DrawBar(self.canvas, on_fold=lambda: self._show_paint(False))
        self.layout().addWidget(self.drawbar)
        # ---- the drawer, the map, and the initiative order
        self.drawer = QTabWidget()
        self.drawer.setDocumentMode(True)
        self.drawer.setMinimumWidth(220)
        self.drawer.setCornerWidget(tool_button("«", lambda: self._show_drawer(False, remember=True), tip=tr("Fold the drawer away")),
                                    Qt.TopRightCorner)
        self.tracker = TrackerPanel(None, "tracker")
        self.play_box = QWidget()                            # play mode: who is played, the action bar, the results
        box = QVBoxLayout(self.play_box)
        box.setContentsMargins(0, 4, 0, 0)
        box.setSpacing(2)
        box.addWidget(self.deck.top)
        box.addWidget(self.deck.bottom, 1)
        self.side = QWidget()                                # the band under the map: the order, under it the turn's actions
        band = QVBoxLayout(self.side)
        band.setContentsMargins(4, 2, 4, 0)
        band.setSpacing(2)
        band.addWidget(self.tracker)
        band.addWidget(self.play_box, 1)
        self.center = QSplitter(Qt.Vertical)                 # the map over the initiative band
        self.center.addWidget(self.host)
        self.center.addWidget(self.side)
        self.center.setStretchFactor(0, 1)
        self.center.setStretchFactor(1, 0)
        self.center.setCollapsible(0, False)                 # the band folds away when dragged shut
        self.center.splitterMoved.connect(self._split_moved)
        self.side_strip = tool_button("︽  ⚔  ︽", lambda: self._show_side(True), tip=tr("Fold out the initiative order"))
        self.side_strip.setFixedHeight(16)
        self.side_strip.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        middle = QWidget()
        stack = QVBoxLayout(middle)
        stack.setContentsMargins(0, 0, 0, 0)
        stack.setSpacing(0)
        stack.addWidget(self.center, 1)
        stack.addWidget(self.side_strip)
        self.split = QSplitter(Qt.Horizontal)
        self.split.addWidget(self.drawer)
        self.split.addWidget(middle)
        self.split.setStretchFactor(1, 1)
        self.split.setSizes([280, 1230])
        self.split.setCollapsible(1, False)                  # the drawer folds away when dragged shut
        self.split.splitterMoved.connect(self._split_moved)
        self.tracker.head.addWidget(tool_button("︾", lambda: self._show_side(False), tip=tr("Fold the initiative order away")))
        self.drawer_strip = fold_strip("»\n\n🧰", lambda: self._show_drawer(True, remember=True),
                                       tr("Fold out the drawer: the bestiary, the props and the items to drag onto the map"))
        self.layout().addLayout(row(self.drawer_strip, self.split, spacing=0), 1)
        battle_hub().area.connect(self._area)
        battle_hub().aim.connect(self._hub_aim)
        battle_hub().place.connect(self._place)
        hub().combatant.connect(self._focus)
        self.destroyed.connect(lambda *_: show_battle_pick(None, None))   # the Inspector lets go of the closed map
        self.canvas.selection_changed.connect(self._selection)
        self.on(events.BATTLE, self.refresh)
        self.on(events.CHARACTERS, self.refresh)
        self.on(events.DUEL, self._duel_state)
        self.set_mode("edit", refresh=False)
        self._show_side(True)
        self._duel_state()

    # ------------------------------------------------------------------ the duel (services/duel): its own map, shown here
    def _duel_state(self):
        on = self.rt.duel.on_screen
        if self.duel_btn.isChecked() != on:
            self.duel_btn.setChecked(on)
        self.retitle()                                       # (the lobby shown is in the title)
        self.duel_btn.setStyleSheet(f"color: {COLORS['warn']}; font-weight: bold;" if on else "")

    def _duel_click(self):
        duel = self.rt.duel
        if not duel.open or not duel.rooms:                  # nothing to show: the Duel window, to open one
            self.duel_btn.setChecked(duel.on_screen)
            from .duel import open_duel_window
            open_duel_window(self)
            return
        self.cancel_aim(quiet=True)
        guard(duel.show, self.duel_btn.isChecked())          # (the lobby picked in the Duel window, or shown last)
        self._duel_state()
        guard(self.refresh)                                  # (the other battle at once, then the whole of its map)
        self.canvas.fit()
        self.retitle()

    # ------------------------------------------------------------------ modes and the drawer
    def set_mode(self, mode: str, refresh: bool = True):
        self.mode = mode if mode in ("edit", "play") else "edit"
        play = self.mode == "play"
        self.edit_btn.setChecked(not play)
        self.play_btn.setChecked(play)
        if play:
            self.drawbar.select()
            self.canvas.carry = self.canvas.zone_carry = self.canvas.stroke = None
            self.canvas.picked = self.canvas.zone_pick = None
            self.canvas.room_box = None
        self.canvas.path = self.canvas.path_tile = None
        self.drawbar.setVisible(not play and self.paint_open)
        self.paint_btn.setVisible(not play)
        self.settings_btn.setVisible(not play)
        self.tracker.set_play(play)
        self.play_box.setVisible(play)
        self._show_drawer(self.drawer_open[self.mode])
        self.hint.setToolTip("<br>".join("• " + html.escape(part) for part in tr(HINTS[self.mode]).split(" · ")))
        if refresh:
            guard(self.refresh)
        self.retitle()

    def toggle_mode(self):
        self.set_mode("edit" if self.mode == "play" else "play")

    def title_suffix(self) -> str:
        mode = tr("Play") if self.mode == "play" else tr("Edit")
        room = self.rt.duel.shown_room()
        return "🤺 " + room.name + " · " + mode if room is not None else mode

    def _toggle_drawer(self):
        self._show_drawer(not self.drawer.isVisible(), remember=True)

    def _show_drawer(self, on: bool, remember: bool = False):
        if remember:
            self.drawer_open[self.mode] = on
        if on and not self.drawer.count():                  # made the first time it opens
            from .library import EnemiesPanel
            from .itemsbox import ItemsDrawerPanel
            from .propsbox import PropsPanel
            for key, text, cls in (("creatures", "👹 " + tr("Creatures"), EnemiesPanel), ("props", "🪵 " + tr("Props"), PropsPanel),
                                   ("items", "🎒 " + tr("Items"), ItemsDrawerPanel)):
                page = guard(cls, None, key)
                if page is not None:
                    self.drawer_pages[key] = page
                    if isinstance(self.drawer_pages.get("_state_" + key), dict):
                        guard(page.restore_state, self.drawer_pages.pop("_state_" + key))
                    self.drawer.addTab(page, text)
        self.drawer.setVisible(on)
        self.drawer_btn.setChecked(on)
        self.drawer_strip.setVisible(not on)
        if on:
            self._unfold(0, 280)

    def _toggle_side(self):
        self._show_side(not self.side.isVisible())

    def _show_side(self, on: bool):
        self.side_open = on
        self.side.setVisible(on)
        self.side_btn.setChecked(on)
        self.side_strip.setVisible(not on)
        if on:
            sizes = self.center.sizes()
            want = self.side.sizeHint().height()
            if sizes[1] < 40 and sum(sizes) > want + 150:    # dragged shut before: its room back
                self.center.setSizes([sum(sizes) - want, want])

    def _unfold(self, i: int, width: int):
        """Give a pane folded shut (dragged to nothing) its room back."""
        sizes = self.split.sizes()
        if sizes[i] < 60 and sum(sizes) > width + 200:
            sizes[1] -= width - sizes[i]
            sizes[i] = width
            self.split.setSizes(sizes)

    def _split_moved(self, _pos: int, _index: int):
        """Dragging the drawer or the initiative band shut folds it (its button unchecks)."""
        if self.split.sizes()[0] == 0 and self.drawer.isVisible():
            self._show_drawer(False, remember=True)
        if self.center.sizes()[1] == 0 and self.side.isVisible():
            self._show_side(False)

    # ------------------------------------------------------------------ the Inspector window shows the selection
    def _selection(self):
        sel = selection_of(self.canvas)
        was = (hub().last_battle_pick or (None, None))[1]
        show_battle_pick(self.canvas, sel)
        if sel is not None and sel != was:
            self._show_inspector()

    def _show_inspector(self):
        """Opened beside the map when it isn't open; brought forward when it's a tab behind another window (but never over
        the map itself)."""
        from ..characters.char_actions import host_of
        host = host_of(self)
        if host is None:
            return
        dock, mine = host.docks.get("app.inspector"), host.docks.get(self.instance)
        if dock is None:                                  # a tab of a side window, or beside the map when there is none
            dock = host.open("app.inspector", "right", None if host.tab_target(registry.get_panel("app.inspector")) else
                             (self.instance if mine is not None else None), focus=False)
        if dock is not None and (dock.tucked or mine is None or dock.dockAreaWidget() is not mine.dockAreaWidget()):
            host.raise_dock(dock)

    def _place(self, key: str):
        if self.mode != "edit":
            self.set_mode("edit")
        self.drawbar.arm(key)

    # ------------------------------------------------------------------ showing it
    def refresh(self):
        v = V.battle_view()
        if self._status is not None and v["status"] != self._status:    # the fight starts: play it; it ends: edit again
            if v["status"] == "active" and self.mode != "play":
                self.set_mode("play", refresh=False)
            elif self._status == "active" and self.mode != "edit":
                self.set_mode("edit", refresh=False)
        elif self._status is None and v["status"] == "active" and self.mode != "play":
            self.set_mode("play", refresh=False)            # opened during a fight (a saved layout's own mode still wins)
        self._status = v["status"]
        fw, lo, hi = FL.layout(v["map"])
        self.floors_text.setText(tr("Only the main floor") if lo == hi else tr("{0} floors: {1} to {2}", hi - lo + 1, floor_name(lo), floor_name(hi)))
        for box, value in ((self.w, fw), (self.h, v["map"]["h"])):
            if not box.hasFocus():
                box.blockSignals(True)
                box.setValue(value)
                box.blockSignals(False)
        self.canvas.set_view(v)
        if self.mode == "play":
            self.deck.refresh(v)
            self._follow_turn(v)
            if self.aim and self.aim.get("local") and self.aim["cid"] != self.deck.playing_id():
                self.cancel_aim()
        render_pending(self)

    def _follow_turn(self, v: dict):
        """Play mode: unless the DM picked something by hand, the creature whose turn it is is the one selected (its
        card fills the Inspector instead of an empty page)."""
        turn = v.get("turn") if v["status"] == "active" else None
        cv = self.canvas
        if turn == getattr(self, "_turn_seen", None):        # only when the turn moves on (a cleared selection stays clear)
            return
        self._turn_seen = turn
        if not turn or turn == cv.selected or cv.picked or cv.zone_pick or cv.gpick:
            return
        if cv.selected is not None and cv.selected != getattr(self, "_followed", None):
            return
        self._followed = cv.selected = turn
        cv.update()
        show_battle_pick(cv, selection_of(cv))

    def _set_size(self):
        self.run(self.rt.battle.set_map_size, self.w.value(), self.h.value())
        self.settings_btn.menu().hide()

    def _floor(self, way: int, remove: str = ""):
        """A floor added over the highest or under the lowest, or the highest / lowest one removed."""
        m = (self.canvas.view or {}).get("map") or {"w": 30, "h": 20}
        _fw, lo, hi = FL.layout(m)
        if remove:
            f = hi if remove == "hi" else lo
            if f == 0:
                notify.info(tr("The main floor stays: there is no other floor that way."))
                return
            if dialogs.confirm(self, tr("Remove {0} and everything on it? (Ctrl+Z brings it back)", floor_name(f)), tr("Remove a floor")):
                self.run(self.rt.battle.remove_floor, f)
            return
        f = guard(self.rt.battle.add_floor, way)
        if f is not None:
            notify.good(tr("{0} added.", floor_name(f)))

    def set_ping(self, on: bool):
        """The ping tool on or off (the button and Esc on the map)."""
        self.ping_btn.setChecked(on)
        self.canvas.set_ping(on)
        if on:
            from ....services.portal.controller import portal
            if not portal.running:
                notify.info(tr("The player portal isn't running: only you see the ping."))
            self.canvas.setFocus()

    def _settings_button(self):
        """⚙: the map's settings in a box that folds out under it (the map size for now)."""
        b = tool_button("⚙", tip=tr("Map settings: its size and its floors"))
        b.setPopupMode(QToolButton.InstantPopup)
        box = QFrame()
        box.setObjectName("card")
        self.floors_text = label("", role="dim")
        floor_btn = lambda text, fn, tip: button(text, fn, kind="flat", tip=tip)   # noqa: E731
        box.setLayout(col(label(tr("<b>Map size</b>"), tip=tr("In tiles of 5 ft; every floor is this size")),
                          row(label(tr("Width"), role="dim"), self.w, label(tr("Height"), role="dim"), self.h),
                          row(stretch(), button(tr("Set"), self._set_size, kind="primary", tip=tr("Change the map size"))),
                          label(tr("<b>Floors</b>"), tip=tr("Stairs up or down put on the map make the next floor (with the same "
                                                           "building) beside it: upstairs to the right, downstairs to the left")),
                          self.floors_text,
                          row(floor_btn(tr("＋ Up"), lambda: self._floor(1), tr("An empty floor over the highest, on the right")),
                              floor_btn(tr("＋ Down"), lambda: self._floor(-1), tr("An empty floor under the lowest, on the left")),
                              floor_btn(tr("－ Top"), lambda: self._floor(0, "hi"), tr("Remove the highest floor and everything on it")),
                              floor_btn(tr("－ Bottom"), lambda: self._floor(0, "lo"), tr("Remove the lowest floor and everything on it"))),
                          margins=8))
        act = QWidgetAction(b)
        act.setDefaultWidget(box)
        m = QMenu(b)
        m.addAction(act)
        b.setMenu(m)
        return b

    def _show_paint(self, on: bool):
        """Fold the paint tools (rooms, drawing, props, pictures) out or away, like the drawer and the initiative."""
        self.paint_open = on
        self.paint_btn.setChecked(on)
        self.drawbar.setVisible(on and self.mode == "edit")
        if not on:
            self.drawbar.select()

    def _area(self, area):
        self.canvas.area = area
        self.canvas.update()

    def _focus(self, cid: int):
        if self.canvas.selected != (cid or None):
            self.canvas.selected = cid or None
            if cid:                                          # picked in the initiative order: nothing else stays selected
                self.canvas.picked = self.canvas.zone_pick = self.canvas.gpick = None
            if self.canvas.menu.cid != cid:
                self.canvas.menu.hide()
            self.canvas.update()

    # ------------------------------------------------------------------ aiming (from the action bar below or a card)
    def _hub_aim(self, aim):
        if aim is None:
            if self.aim and not self.aim.get("local"):
                self.cancel_aim(quiet=True)
            return
        self.set_aim(aim)

    def set_aim(self, aim: dict):
        self.aim = aim
        aim.setdefault("targets", [])
        self.canvas.set_aim(aim)
        self.deck.set_aiming(aim["item"]["id"] if aim.get("local") else None)
        self.render_aimbar()

    def cancel_aim(self, quiet: bool = False):
        was = self.aim
        self.aim = None
        self.canvas.set_aim(None)
        self.deck.set_aiming(None)
        self.render_aimbar()
        if was and not was.get("local") and not quiet:
            battle_hub().aim.emit(None)

    def render_aimbar(self):
        render_aimbar(self)

    def pick_item(self, item: dict):
        """An action or spell picked on the action bar under the map: do it now, or aim it on the map (like the portal)."""
        if not item.get("ok", True):
            notify.warn(tr(item.get("why") or "Not now"))
            return
        cid = self.deck.playing_id()
        aim = {"cid": cid, "item": item, "targets": [], "point": None, "adv": self.deck.prefs.get("adv"), "metamagic": None,
               "slot": item.get("level") if item.get("kind") == "spell" and item.get("level") else None,
               "dtype": (item.get("types") or [None])[0], "options": list(item.get("options") or []), "option": None, "local": True}
        if aim["options"]:
            aim["option"] = aim["options"][0]["value"]
        if item.get("kind") == "spell":
            info = guard(self.rt.battle.spell_info, item["name"], aim["slot"]) or {}
            if info.get("options"):
                aim["options"] = info["options"]
                aim["option"] = info["options"][0]["value"]
        t = item.get("target") or {}
        if t.get("type") == "fixed":
            aim["targets"] = [t["id"]]
            return self.commit(aim)
        if not needs_click(item) and item.get("kind") != "spell" and not item.get("types") and not aim["options"]:
            return self.commit(aim)
        self.set_aim(aim)

    def commit(self, a: dict):
        self.cancel_aim(quiet=True)
        if not a.get("local"):
            battle_hub().aim.emit(None)
        out = guard(self.rt.battle.act, a["cid"], a["item"]["id"], a.get("targets") or None, a.get("point"), a.get("slot"),
                    a.get("dtype"), a.get("option"), a.get("adv"), False, a.get("metamagic"))
        if a.get("adv"):
            self.deck.used_adv()
        self.show_result(out)

    def walk(self, x: int, y: int):
        cid = self.deck.playing_id()
        self.canvas.path, self.canvas.path_tile = None, None
        if cid:
            self.show_result(guard(self.rt.battle.walk, cid, x, y))

    def show_result(self, text):
        if self.mode == "play":
            self.deck.show_result(text)
        else:
            say(text)

    # ------------------------------------------------------------------ remembered
    def save_state(self) -> dict:
        st = {"mode": self.mode, "drawer": dict(self.drawer_open), "split": self.split.sizes(), "band": self.center.sizes(),
              "side": self.side_open,
              "paint": self.paint_open,
              "tracker": guard(self.tracker.save_state) or {}}
        if not self.canvas.auto_fit:
            st["cam"] = dict(self.canvas.cam)
        if self.deck.playing:
            st["playing"] = self.deck.playing
        for key in ("creatures", "props", "items"):
            page = self.drawer_pages.get(key)
            if page is not None:
                st[key] = guard(page.save_state) or {}
        return st

    def restore_state(self, state: dict):
        cam = state.get("cam")
        if isinstance(cam, dict) and all(isinstance(cam.get(k), (int, float)) for k in ("x", "y", "z")):
            self.canvas.cam = {k: float(cam[k]) for k in ("x", "y", "z")}
            self.canvas.cam["z"] = max(ZMIN, min(ZMAX, self.canvas.cam["z"]))
            self.canvas.fitted = True
            self.canvas.auto_fit = False
            self.canvas.update()
        if isinstance(state.get("drawer"), dict):
            self.drawer_open.update({k: bool(v) for k, v in state["drawer"].items() if k in self.drawer_open})
        for key in ("creatures", "props", "items"):
            if isinstance(state.get(key), dict):
                page = self.drawer_pages.get(key)
                if page is not None:
                    guard(page.restore_state, state[key])
                else:
                    self.drawer_pages["_state_" + key] = state[key]
        sizes = state.get("split")
        if isinstance(sizes, list) and len(sizes) in (2, 3) and all(isinstance(x, int) for x in sizes):
            self.split.setSizes([sizes[0], sum(sizes[1:])])  # (3: from when the initiative was a column on the right)
        band = state.get("band")
        if isinstance(band, list) and len(band) == 2 and all(isinstance(x, int) for x in band) and band[1] > 0:
            self.center.setSizes(band)
        if isinstance(state.get("tracker"), dict):
            guard(self.tracker.restore_state, state["tracker"])
        self._show_side(bool(state.get("side", True)))
        self._show_paint(bool(state.get("paint", True)))
        if isinstance(state.get("playing"), int):
            self.deck.playing = state["playing"]
        self.set_mode(state.get("mode") or "edit")
