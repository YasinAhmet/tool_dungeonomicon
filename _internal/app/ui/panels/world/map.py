"""The World map window: a sheet that starts as open sea; the DM raises land out of it with a soft brush (lowers it
back, smooths the coast), paints its grounds and realms, sets mountains, woods, towns and names on it (or has the land
dressed and settled for them), and sends it to the players' portal. Its look: painted (Inkarnate's), turquoise,
antique, sepia or old parchment. Beside it the group's column: the party on the map, its route, its food.

Tools: ✋ move (drag marks, names and the party; double-click to edit; Del removes) · ⛰ raise / 🌊 lower / 〰 smooth
land · 🏳 paint a realm's colour · 🎨 paint the ground (grass, desert, snow...) · 🏰 place a mark (a town needs a name;
mountains, hills and forests spray while you drag) · 🖼 stamp pictures · 🧽 erase marks · 🔤 a name · ✒ a line · 🚩 the
party travels where you click (Shift: put it there with no trail) · 🧭 its route (click the way, Backspace: take a point
back) · 📍 ping (everyone sees it). Wheel zooms, right-drag pans, [ ] size the brush, Ctrl+Z / Ctrl+Y undo and redo."""
import math
import os
import random
import threading
import time

from PySide6.QtCore import QEvent, QPointF, QRectF, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices, QIcon, QImage, QLinearGradient, QPainter, QPixmap
from PySide6.QtWidgets import (QApplication, QButtonGroup, QListView, QListWidget, QListWidgetItem, QMenu, QPushButton, QSlider,
                               QSplitter, QWidget)

from ....core import events
from ....core.i18n import tr
from ....core.runtime import rt
from ....services.world import ART, LINE_STYLES, MARK_KINDS, PACES, SCALE_MAX, SCALE_MIN, SCALES, SIZED, TERRAIN, stamps
from ....services.world import dress as D
from ....services.world import render as R
from ... import dialogs, notify
from ...errors import guard, guard_ok, report
from ...panel import Panel
from ...registry import panel
from ...widgets.common import FlowLayout, button, check, col, combo, label, row, scroll, set_items, spin, stretch, widget
from . import art
from .group import GroupColumn

ZMAX = 10.0
LAYER_WHOLE = 3.0                                       # up to this many screen pixels a map pixel, the layer is the whole sheet
PING_LIFE = 1.6
GLIDE_SPEED = 260.0                             # map pixels a second the party's banner travels (0.45 to 2.4 s a move)


def split_way(pts, f: float) -> tuple:
    """A way cut a fraction `f` of its length along: (the points up to there, ending there; from there on, starting there)."""
    lens = [math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(pts, pts[1:])]
    left = max(0.0, min(1.0, f)) * sum(lens)
    for i, d in enumerate(lens):
        if left <= d and d > 0:
            a, b = pts[i], pts[i + 1]
            at = [a[0] + (b[0] - a[0]) * left / d, a[1] + (b[1] - a[1]) * left / d]
            return [list(p) for p in pts[:i + 1]] + [at], [at] + [list(p) for p in pts[i + 1:]]
        left -= d
    return [list(p) for p in pts], [list(pts[-1])]
TOOLS = [("move", "✋", "Move: drag marks, names, lines and the party · double-click: edit · Del: remove · drag empty map: pan"),
         ("raise", "⛰", "Raise land: paint land up out of the sea (keep painting: it grows)"),
         ("lower", "🌊", "Lower land: paint it back into the sea (bays, straits, lakes)"),
         ("smooth", "〰", "Smooth the coast"),
         ("realm", "🏳", "Paint a realm: a kingdom's colour over its land, its border drawn round it (No realm: rub it out)"),
         ("ground", "🎨", "Paint the ground: grassland, dry steppe, forest floor, desert, snow, bare rock, swamp or farmland "
                         "(the land's own: back to its wet and dry patches) · shows with the Painted look"),
         ("mark", "🏰", "Place a mark: a town and its name, or spray mountains, hills and forests"),
         ("stamp", "🖼", "Stamp a picture: painted mountains, woods, towns and ships, or top-down houses, castles, trees, "
                         "boulders, piers, boats, fields (click: one · drag: a row along the way, or scatter them under the brush · "
                         "Q / E: turn · 🎲: any of the group)"),
         ("erase", "🧽", "Erase marks and lines under the brush (mountains, trees, towns, roads)"),
         ("label", "🔤", "Write a name on the map (a sea, a kingdom, a forest)"),
         ("line", "✒", "Draw a line - a road, path, river, border or wall: drag to draw freehand, or click point by point "
                       "(double-click, Enter or right-click: done · Esc: cancel)"),
         ("party", "🚩", "Move the party: click where it travels, along the roads and paths where they help (Shift+click: put it there, no trail · Ctrl+Z: take the move back)"),
         ("route", "🧭", "Plan the route: click the way from the party (Backspace: take a point back, right-click: done)"),
         ("ping", "📍", "Ping: everyone sees a ripple where you click")]
BRUSHES = ("raise", "lower", "smooth", "ground", "realm", "erase")
KIND_NAMES = {"capital": "Capital", "city": "City", "town": "Town", "village": "Village", "fort": "Fort", "ruin": "Ruin",
              "poi": "Place of interest", "mountain": "Mountains", "hills": "Hills", "forest": "Forest", "compass": "Compass rose"}
KIND_GLYPH = {"capital": "★", "city": "◉", "town": "●", "village": "○", "fort": "♜", "ruin": "◌", "poi": "✕",
              "mountain": "⛰", "hills": "◠", "forest": "🌲", "compass": "✣"}
LOOK_NAMES = {"painted": "Painted", "teal": "Painted, turquoise sea", "antique": "Antique", "sepia": "Sepia",
              "parchment": "Parchment"}
LINE_NAMES = {"road": "Road", "path": "Path", "river": "River", "border": "Border", "wall": "Wall", "guide": "Guide line"}
LINE_GLYPH = {"road": "━", "path": "┅", "river": "〜", "border": "╍", "wall": "▬", "guide": "┄"}
LAYER_KEYS = {Qt.Key_Home: "front", Qt.Key_PageUp: "up", Qt.Key_PageDown: "down", Qt.Key_End: "back"}
SPRAY_GAP = {"mountain": 11.0, "hills": 10.0, "forest": 6.0}
def _near_line(pts, x, y, tol) -> bool:
    for (ax, ay), (bx, by) in zip(pts, pts[1:]):
        dx, dy = bx - ax, by - ay
        t = max(0.0, min(1.0, ((x - ax) * dx + (y - ay) * dy) / (dx * dx + dy * dy or 1)))
        if math.hypot(x - ax - dx * t, y - ay - dy * t) <= tol:
            return True
    return False


def simplify(pts, eps):
    """Fewer points along a freehand line (Ramer-Douglas-Peucker), the shape kept within `eps` map pixels."""
    if len(pts) < 3:
        return [list(p) for p in pts]
    (ax, ay), (bx, by) = pts[0], pts[-1]
    dx, dy = bx - ax, by - ay
    n = math.hypot(dx, dy) or 1.0
    far, at = -1.0, 0
    for i, (x, y) in enumerate(pts[1:-1], 1):
        d = abs(dy * (x - ax) - dx * (y - ay)) / n if (dx or dy) else math.hypot(x - ax, y - ay)
        if d > far:
            far, at = d, i
    if far <= eps:
        return [list(pts[0]), list(pts[-1])]
    return simplify(pts[:at + 1], eps)[:-1] + simplify(pts[at:], eps)


def busy(fn, *args):
    """guard() with the wait cursor up: for the few seconds dressing or settling the land takes."""
    QApplication.setOverrideCursor(Qt.WaitCursor)
    try:
        return guard(fn, *args)
    finally:
        QApplication.restoreOverrideCursor()


def suggest_name() -> str:
    from ....core.i18n import i18n
    D.LANG = "tr" if i18n.language == "tr" else "en"            # (a Turkish name when the editor is in Turkish)
    return D.place_name()


class WorldCanvas(QWidget):
    rendered = Signal(object)                           # a whole picture made on a thread
    moved = Signal(object)                              # the party's move, worked out on a thread (or its error)
    way_found = Signal(object)                          # (map point, way) for 🚩's preview

    def __init__(self, panel: "WorldPanel"):
        super().__init__()
        self.panel = panel
        self.setMouseTracking(True)
        self.setFocusPolicy(Qt.StrongFocus)
        self.setMinimumSize(320, 220)
        self.tool, self.radius, self.strength, self.kind = "raise", 34.0, 0.35, "city"
        self.ground = 1                                 # what the 🎨 brush paints (render.GROUNDS; 0: the land's own)
        self.realm = 1                                  # what the 🏳 brush paints (render.REALMS; 0: none)
        self.z, self.ox, self.oy = 1.0, 0.0, 0.0
        self.fitted = self.auto_fit = False
        self.pix = None                                 # the parchment (2× the map's pixels)
        self.busy = self.again = False
        self.mouse = None                               # map point under the mouse
        self.drag = None                                # what a held button is doing
        self.selected = None                            # ("mark" | "label", id)
        self.spray = []                                 # marks being sprayed (not yet in the service)
        self.erasing = set()
        self.erasing_lines = set()
        self.line_style = "road"
        self.drawing = []                               # the line being drawn (map points)
        self.clicking = False                           # drawn point by point (clicks) rather than dragged
        self.dirty = None
        self.stroke_box = None
        self.flush = QTimer(self, singleShot=True, interval=12, timeout=self._flush)
        self.scaling = None                             # (kind, id, size) while the wheel resizes a mark or name
        self.size_timer = QTimer(self, singleShot=True, interval=450, timeout=self._commit_size)
        self.anim = QTimer(self, interval=16, timeout=self._tick)
        self.glide = None                               # the party's banner on its way: {"pts", "back", "t0", "dur"}
        self.moving = False                             # a move being worked out (on a thread: the roads take a moment)
        self.hover_way, self.finding = None, False      # (map point, the way there) for 🚩's preview; one being found
        self.way_timer = QTimer(self, singleShot=True, interval=90, timeout=self._find_way)
        self.moved.connect(self._moved)
        self.way_found.connect(self._got_way)
        self.keeper = QTimer(self, singleShot=True, interval=2500, timeout=self._keep)
        self.art, self.mix = None, False                # the stamp the 🖼 tool sets; a random one of its group each time
        self.angle, self.spin, self.stamp_mode = 0.0, False, "row"      # turned (degrees); each a random way; row / line / scatter
        self.rendered.connect(self._got_picture)
        self.layer, self.layer_stale = None, True       # the lines, marks and names drawn once ({"pix", "rect", "scale", "snap"})
        self.layer_timer = QTimer(self, singleShot=True, interval=160, timeout=self._settled)
        self.grid_pix = None                            # (key, QPixmap) of the map's grid, made when it changes

    # ------------------------------------------------------------------ the picture
    def full_render(self):
        """Make the whole parchment again, on a thread (the first time also makes its paper: a few seconds). The
        picture kept from last time shows at once when the land hasn't changed since; the brushes get ready behind it."""
        if self.busy:
            self.again = True                               # (another map opened meanwhile: once more when done)
            return
        self.busy, self.again = True, False
        world = rt().world
        w, h = world.size
        kept = world.cached_view()
        img = QImage(kept) if kept else None
        if img is not None and img.width() == w * world.scale and img.height() == h * world.scale:
            self.pix = QPixmap.fromImage(img)
            if not self.fitted:
                self.fit()
            job = world.renderer
        else:
            job = world.render
        self.update()

        def work():
            try:
                self.rendered.emit(job())
            except Exception as e:                   # noqa: BLE001 - shown, not swallowed
                self.rendered.emit(e)
        threading.Thread(target=work, daemon=True, name="world-render").start()

    def _got_picture(self, rgba):
        self.busy = False
        if self.again:
            self.full_render()
            return
        if isinstance(rgba, Exception):
            notify.error(tr("The map couldn't be drawn: {0}", rgba))
            return
        if isinstance(rgba, R.Renderer):                    # the kept picture shows: the brushes are ready now
            self.update()
            return
        h, w = rgba.shape[:2]
        img = QImage(rgba.data, w, h, w * 4, QImage.Format_RGBA8888).copy()
        self.pix = QPixmap.fromImage(img)
        if not self.fitted:
            self.fit()
        self.keeper.start()
        self.update()

    def _keep(self):
        """Keep the whole picture for next time (once the land is still: nothing painted or waiting to be drawn)."""
        if self.pix is None:
            return
        if self.busy or self.dirty or self.flush.isActive() or (self.drag and self.drag[0] == "paint"):
            self.keeper.start()
            return
        world = rt().world
        path, img = world.view_path(), self.pix.toImage()
        threading.Thread(target=lambda: world.keep_view(path, lambda p: img.save(p, "PNG", 80)), daemon=True,
                         name="world-keep").start()

    def redraw(self, rect, reach: int = R.REACH):
        """Render the part of the map round a changed rect (map pixels) into the parchment. While the brush is held
        only round the brush (`reach` small: the ripples further out catch up when it is let go)."""
        if not rect or rect[2] <= rect[0] or self.pix is None:
            return
        x0, y0, x1, y1 = rect
        e = reach
        w, h = rt().world.size
        r = (max(0, x0 - e), max(0, y0 - e), min(w, x1 + e), min(h, y1 + e))
        d = self.dirty
        self.dirty = r if d is None else (min(d[0], r[0]), min(d[1], r[1]), max(d[2], r[2]), max(d[3], r[3]))
        if not self.flush.isActive():
            self.flush.start()

    def _dab(self, box):
        if not box or box[2] <= box[0]:
            return
        b = self.stroke_box
        self.stroke_box = box if b is None else (min(b[0], box[0]), min(b[1], box[1]), max(b[2], box[2]), max(b[3], box[3]))
        self.redraw(box, int(R.WARP) + 4)

    def _flush(self):
        r, self.dirty = self.dirty, None
        if not r or self.pix is None:
            return
        world = rt().world
        if self.pix.width() != world.size[0] * world.scale:     # (the sharpness changed: a whole new picture is coming)
            return
        patch = world.render(r)
        h, w = patch.shape[:2]
        img = QImage(patch.data, w, h, w * 4, QImage.Format_RGBA8888)
        p = QPainter(self.pix)
        p.setCompositionMode(QPainter.CompositionMode_Source)
        p.drawImage(int(r[0] * world.scale), int(r[1] * world.scale), img)
        p.end()
        self.keeper.start()
        self.update()

    # ------------------------------------------------------------------ view
    def fit(self):
        w, h = rt().world.size
        if self.width() < 50:
            return
        self.z = min(self.width() / w, self.height() / h) * 0.96
        self.ox = (self.width() - w * self.z) / 2
        self.oy = (self.height() - h * self.z) / 2
        self.fitted = self.auto_fit = True
        self.update()

    def find_party(self):
        p = rt().world.party()["pos"]
        if not p:
            notify.warn(tr("Put the party on the map first (🚩)."))
            return
        w, h = rt().world.size
        self.z = max(self.z, min(self.width() / w, self.height() / h) * 2.2)
        self.ox, self.oy = self.width() / 2 - p[0] * self.z, self.height() / 2 - p[1] * self.z
        self.auto_fit = False
        self.update()

    def zoom(self, factor, at=None):
        self.auto_fit = False
        w, h = rt().world.size
        lo = min(self.width() / w, self.height() / h) * 0.5
        nz = max(lo, min(ZMAX, self.z * factor))
        ax, ay = at if at else (self.width() / 2, self.height() / 2)
        mx, my = (ax - self.ox) / self.z, (ay - self.oy) / self.z
        self.z = nz
        self.ox, self.oy = ax - mx * nz, ay - my * nz
        self.update()

    def to_map(self, p) -> tuple:
        return (p.x() - self.ox) / self.z, (p.y() - self.oy) / self.z

    def resizeEvent(self, e):
        if (not self.fitted or self.auto_fit) and self.pix is not None:   # fitted until the DM zooms or pans
            self.fit()
        super().resizeEvent(e)

    # ------------------------------------------------------------------ painting
    def paintEvent(self, _e):
        g = QPainter(self)
        bg = QLinearGradient(0, 0, 0, self.height())
        bg.setColorAt(0, QColor(30, 24, 19))
        bg.setColorAt(1, QColor(16, 13, 11))
        g.fillRect(self.rect(), bg)
        world = rt().world
        if art.LOOK != world.d["look"] or art.PLAQUES != world.d["plaques"]:   # (names and shadows follow the map's look)
            art.set_look(world.d["look"])
            art.PLAQUES = world.d["plaques"]
            self.layer = None
        w, h = world.size
        if self.pix is None:
            g.setPen(QColor(200, 180, 140))
            g.drawText(self.rect(), Qt.AlignCenter, tr("Unrolling the parchment…"))
            return
        g.setRenderHint(QPainter.Antialiasing)
        g.setRenderHint(QPainter.SmoothPixmapTransform)
        g.translate(self.ox, self.oy)
        g.scale(self.z, self.z)
        g.fillRect(QRectF(6, 8, w, h), QColor(0, 0, 0, 70))      # a soft shadow under the sheet
        g.drawPixmap(QRectF(0, 0, w, h), self.pix, QRectF(self.pix.rect()))
        grid = world.grid()
        if grid:                                             # (drawn once at the picture's sharpness, kept)
            key = (grid["kind"], grid["px"], w, h, world.d["look"], world.scale)
            if self.grid_pix is None or self.grid_pix[0] != key:
                gp = QPixmap(w * world.scale, h * world.scale)
                gp.fill(Qt.transparent)
                q = QPainter(gp)
                q.setRenderHint(QPainter.Antialiasing)
                q.scale(world.scale, world.scale)
                art.paint_grid(q, grid, w, h)
                q.end()
                self.grid_pix = (key, gp)
            g.drawPixmap(QRectF(0, 0, w, h), self.grid_pix[1], QRectF(self.grid_pix[1].rect()))
        k = 1.0 / self.z
        self._paint_layer(g, world)                          # the lines, marks and names: drawn once, kept
        if world.d["scale_bar"]:
            art.paint_scale_bar(g, world.miles_per_px(), w, h)
        sel = self.selected                                  # on top: what is picked, being erased, drawn, sprayed
        if sel:
            item = self._find(world, sel)
            if item is not None:
                if sel[0] == "line":
                    art.paint_line(g, item, selected=True)
                elif sel[0] == "mark":
                    art.paint_mark(g, self._sized("mark", item), selected=True)
                else:
                    art.paint_label(g, self._sized("label", item), selected=True)
        if self.erasing or self.erasing_lines:
            for m in world.marks():
                if m["id"] in self.erasing:
                    art.paint_erasing(g, m, k)
            for ln in world.lines():
                if ln["id"] in self.erasing_lines:
                    art.paint_line(g, ln, selected=True)
        if self.drawing:
            pts = self.drawing + ([list(self.mouse)] if self.clicking and self.mouse else [])
            if len(pts) >= 2:
                art.paint_line(g, {"pts": pts, "style": self.line_style})
        for m in sorted(self.spray, key=lambda m: m["y"]):
            art.paint_mark(g, m)
        p = world.party()
        at, trail = self._banner(p)
        art.paint_trail(g, trail, k)
        ri = world.route_info()
        art.paint_route(g, p["pos"], p["route"], k,
                        tr("{0} mi · {1} d", round(ri["miles"]), ri["days"]) if ri["miles"] else "")
        if self.tool == "party" and self.mouse and p["pos"] and self.drag is None and not self.glide:   # where a click would take them
            hw = self.hover_way
            known = hw and hw[0] == tuple(self.mouse) and hw[2] == p["pos"]
            way = hw[1] if known else [p["pos"], list(self.mouse)]
            if not known:
                self.way_timer.start()                      # the roads' way, once the mouse rests
            miles = world.miles(way)
            art.paint_route(g, way[0], way[1:], k, tr("{0} mi · {1} d", round(miles), round(world.days(miles), 1)))
        art.paint_party(g, at, k)
        now = time.time()
        for pg in world.recent_pings():
            art.paint_ping(g, pg, now - pg["at"], k, PING_LIFE)
        if self.mouse and self.tool in BRUSHES and self.underMouse():
            rgb = (R.GROUNDS[self.ground][1] if self.tool == "ground" and self.ground in R.GROUNDS else
                   R.REALMS[self.realm][1] if self.tool == "realm" and self.realm in R.REALMS else None)
            art.paint_brush(g, self.mouse[0], self.mouse[1], self.radius, k, self.tool, rgb)
        if self.mouse and self.tool == "stamp" and self.art and self.drag is None and self.underMouse():   # where a click puts it
            g.setOpacity(0.55)
            if self.stamp_mode == "scatter":
                art.paint_brush(g, self.mouse[0], self.mouse[1], self.radius, k, "stamp")
            art.paint_stamp(g, dict(self._stamp(self.mouse, self.art), r=self.angle))
            g.setOpacity(1.0)
        if self.busy:
            g.resetTransform()
            g.setPen(QColor(230, 210, 170))
            g.drawText(self.rect().adjusted(0, 0, -10, -8), Qt.AlignRight | Qt.AlignBottom, tr("Drawing the map…"))

    # ------------------------------------------------------------------ the kept layer
    def stale(self):
        """The marks, names or lines changed: the layer is looked at again (only what is new is drawn, when it can be)."""
        self.layer_stale = True
        self.update()

    @staticmethod
    def _find(world, what):
        items = {"mark": world.marks, "label": world.labels, "line": world.lines}[what[0]]()
        return next((x for x in items if x["id"] == what[1]), None)

    def _layer_want(self) -> tuple:
        """(map rect, scale) the layer should cover: the whole sheet while zoomed out, round the view (with a margin
        to pan in) at the screen's sharpness when zoomed in."""
        w, h = rt().world.size
        want = self.z * self.devicePixelRatioF()
        if want <= LAYER_WHOLE:
            return QRectF(0, 0, w, h), max(1.0, math.ceil(want - 0.1))
        vw, vh = self.width() / self.z, self.height() / self.z
        view = QRectF(-self.ox / self.z - vw * 0.5, -self.oy / self.z - vh * 0.5, vw * 2, vh * 2)
        return view.intersected(QRectF(0, 0, w, h)), round(want * 2) / 2

    def _paint_layer(self, g, world):
        want_rect, want_scale = self._layer_want()
        lay = self.layer
        vw, vh = self.width() / self.z, self.height() / self.z
        view = QRectF(-self.ox / self.z, -self.oy / self.z, vw, vh).intersected(QRectF(0, 0, *world.size))
        covers = lay is not None and lay["rect"].contains(view)
        if lay is None or not covers:                        # nothing to show (or panned past it): drawn now
            self._build_layer(world, want_rect, want_scale)
        elif self.layer_stale:
            self._refresh_layer(world)
        elif lay["scale"] != want_scale and not self.layer_timer.isActive():
            self.layer_timer.start()                         # the zoom changed: sharper once it settles
        lay = self.layer
        g.drawPixmap(lay["rect"], lay["pix"], QRectF(lay["pix"].rect()))

    def _settled(self):
        want_rect, want_scale = self._layer_want()
        if self.layer is None or self.layer["scale"] != want_scale or not self.layer["rect"].contains(want_rect):
            self._build_layer(rt().world, want_rect, want_scale)
            self.update()

    def _items(self, world, rect=None):
        """The lines (bottom to top), the marks (back to front) and the names, only those near `rect` (one the wheel
        is resizing shows on top, as it is picked)."""
        def near(x, y, pad):
            return rect is None or rect.adjusted(-pad, -pad, pad, pad).contains(QPointF(x, y))
        lines = [ln for ln in world.lines_in_order()
                 if rect is None or any(near(px, py, 12) for px, py in ln["pts"]) or len(ln["pts"]) > 1 and
                 QRectF(QPointF(min(q[0] for q in ln["pts"]), min(q[1] for q in ln["pts"])),
                        QPointF(max(q[0] for q in ln["pts"]), max(q[1] for q in ln["pts"]))).intersects(rect)]
        marks = sorted((m for m in world.marks() if near(m["x"], m["y"], art.mark_reach(m))), key=lambda m: m["y"])
        labels = [lab for lab in world.labels() if near(lab["x"], lab["y"], 260)]
        return lines, marks, labels

    def _snapshot(self, world):
        sig = lambda d: tuple(sorted((k, str(v)) for k, v in d.items()))     # noqa: E731
        return ({m["id"]: (sig(m), m) for m in world.marks()}, hash(tuple(sig(ln) for ln in world.lines())),
                hash(tuple(sig(lab) for lab in world.labels())))

    def _build_layer(self, world, rect, scale):
        w, h = max(1, int(math.ceil(rect.width() * scale))), max(1, int(math.ceil(rect.height() * scale)))
        pix = QPixmap(w, h)
        pix.fill(Qt.transparent)
        p = QPainter(pix)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.scale(scale, scale)
        p.translate(-rect.x(), -rect.y())
        lines, marks, labels = self._items(world, None if rect == QRectF(0, 0, *world.size) else rect)
        for ln in lines:
            art.paint_line(p, ln)
        art.paint_marks(p, marks)
        for lab in labels:
            art.paint_label(p, lab)
        p.end()
        self.layer = {"pix": pix, "rect": QRectF(rect), "scale": scale, "snap": self._snapshot(world)}
        self.layer_stale = False

    def _refresh_layer(self, world):
        """After a change only what changed is drawn again: new marks on top; round marks moved, removed or edited, that
        part of the layer (a change of the lines or the names, or a big one, draws it all)."""
        self.layer_stale = False
        lay = self.layer
        snap = self._snapshot(world)
        old_marks, old_lines, old_labels = lay["snap"]
        new_marks = snap[0]
        if old_lines != snap[1] or old_labels != snap[2]:
            self._build_layer(world, lay["rect"], lay["scale"])
            return
        added = [new_marks[i][1] for i in new_marks if i not in old_marks]
        changed = [i for i, (sg, _m) in old_marks.items() if new_marks.get(i, (None,))[0] != sg]
        dirty = None
        for i in changed:                                    # where they were, and where they are now
            for m in (old_marks[i][1], new_marks.get(i, (None, None))[1]):
                if m:
                    pad = art.mark_reach(m)
                    r = QRectF(m["x"] - pad, m["y"] - pad, pad * 2, pad * 2)
                    dirty = r if dirty is None else dirty.united(r)
        if dirty is not None:                                # (new ones along with them, if some changed too)
            for m in added:
                pad = art.mark_reach(m)
                dirty = dirty.united(QRectF(m["x"] - pad, m["y"] - pad, pad * 2, pad * 2))
        if dirty is not None and dirty.width() * dirty.height() > lay["rect"].width() * lay["rect"].height() * 0.4:
            self._build_layer(world, lay["rect"], lay["scale"])
            return
        p = QPainter(lay["pix"])
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.scale(lay["scale"], lay["scale"])
        p.translate(-lay["rect"].x(), -lay["rect"].y())
        if dirty is not None:                                # that part cleared and drawn again (all that reaches into it)
            p.setClipRect(dirty)
            p.setCompositionMode(QPainter.CompositionMode_Clear)
            p.fillRect(dirty, Qt.transparent)
            p.setCompositionMode(QPainter.CompositionMode_SourceOver)
            lines, marks, labels = self._items(world, dirty)
            for ln in lines:
                art.paint_line(p, ln)
            art.paint_marks(p, marks)
            for lab in labels:
                art.paint_label(p, lab)
            p.setClipping(False)
        elif added:
            for m in sorted(added, key=lambda m: m["y"]):
                art.paint_mark(p, m)
        p.end()
        lay["snap"] = snap

    def _tick(self):
        if self.glide and time.time() - self.glide["t0"] >= self.glide["dur"]:
            self.glide = None
            self.update()
        if self.glide or rt().world.recent_pings():
            self.update()
        else:
            self.anim.stop()

    # ------------------------------------------------------------------ the party on its way
    def _banner(self, p) -> tuple:
        """Where the party's banner is drawn now, and its trail behind it (gliding along its last way, or still)."""
        gl, pos = self.glide, p["pos"]
        if not gl or not pos:
            return pos, p["trail"] + ([pos] if pos else [])
        t = min(1.0, (time.time() - gl["t0"]) / gl["dur"])
        e = 2 * t * t if t < 0.5 else 1 - (-2 * t + 2) ** 2 / 2
        done, ahead = split_way(gl["pts"], e)
        if gl["back"]:                                      # taken back: the trail shrinks behind the banner
            return done[-1], p["trail"] + ahead[::-1]
        keep = p["trail"][:max(1, len(p["trail"]) - (len(gl["pts"]) - 1))]
        return done[-1], keep + done

    def _glide(self, pts, back=False):
        if not pts or len(pts) < 2:
            return
        length = sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(pts, pts[1:]))
        self.glide = {"pts": pts, "back": back, "t0": time.time(), "dur": max(0.45, min(2.4, length / GLIDE_SPEED))}
        if not self.anim.isActive():
            self.anim.start()
        self.update()

    def travel(self, mp):
        """The party travels to a map point (along the roads where they help: worked out on a thread), its banner
        gliding there."""
        world = rt().world
        if not world.party()["pos"]:
            guard(world.place_party, *mp)
            return
        if self.moving:
            return
        self.moving = True
        mp = list(mp)

        def work():
            try:
                self.moved.emit(world.move_party(*mp))
            except Exception as e:                   # noqa: BLE001 - shown, not swallowed
                self.moved.emit(e)
        threading.Thread(target=work, daemon=True, name="world-move").start()

    def _moved(self, got):
        self.moving = False
        if isinstance(got, Exception):
            report(got)
            return
        world = rt().world
        self._glide(got["path"])
        if got["ended"]:
            notify.info(tr("The party travels {0} mi: {1} days pass on the way and the group eats {2} meals.",
                           round(got["miles"]), got["ended"], got["ate"]))
            if got["hungry"]:
                notify.warn(tr("Not enough food on the way: {0} meals short.", got["hungry"]))
        elif got["miles"]:
            notify.info(tr("The party travels {0} mi (about {1} days at a {2} pace).", round(got["miles"]), got["days"],
                           tr(world.settings()["pace"])))

    def _find_way(self):
        """🚩's preview: the way to the point under the mouse, found on a thread (one at a time)."""
        world = rt().world
        pos = world.party()["pos"]
        if self.finding or not self.mouse or not pos or self.tool != "party":
            if self.finding:
                self.way_timer.start()
            return
        self.finding = True
        mp = tuple(self.mouse)

        def work():
            try:
                self.way_found.emit((mp, world.way(*mp), pos))
            except Exception:                        # noqa: BLE001 - only a preview: the straight line stays
                self.way_found.emit(None)
        threading.Thread(target=work, daemon=True, name="world-way").start()

    def _got_way(self, got):
        self.finding = False
        if got:
            self.hover_way = got
            self.update()

    def take_back(self):
        """The party's last move is taken back: back it goes, the days turn back, the meals return."""
        got = guard(rt().world.undo_move)
        if not got:
            return
        self._glide(got["path"], back=True)
        if got["days"]:
            notify.info(tr("Move taken back: {0} days turn back and {1} meals go back into the group's food.",
                           got["days"], got["meals"]))
        else:
            notify.info(tr("The party's last move is taken back."))

    def pinged(self):
        if not self.anim.isActive():
            self.anim.start()
        self.update()

    # ------------------------------------------------------------------ finding things
    def hit(self, mp) -> tuple:
        """What is under a map point: ("party",) / ("mark", id) / ("label", id) / None."""
        world = rt().world
        x, y = mp
        tol = 7 / self.z
        p = world.party()["pos"]
        if p and math.hypot(p[0] - x, p[1] - y - 8 / self.z) < 14 / self.z:
            return ("party", None)
        best = None
        for m in world.marks():
            if m["kind"] == ART:                                # a stamp: anywhere on its picture
                if art.stamp_hit(m, x, y, tol):
                    d = math.hypot(m["x"] - x, m["y"] - y) * 0.5
                    if best is None or d < best[0]:
                        best = (d, ("mark", m["id"]))
                continue
            ms = float(m.get("s") or 1)
            r = 6 * ms if m["kind"] in TERRAIN else art.MARK_R.get(m["kind"], 6) * ms
            d = math.hypot(m["x"] - x, m["y"] - (r * 0.6 if m["kind"] in TERRAIN else 0) - y)
            if d <= r + tol and (best is None or d < best[0]):
                best = (d, ("mark", m["id"]))
        if best:
            return best[1]
        for lab in reversed(world.labels()):
            if art.label_rect(lab).contains(QPointF(x, y)):
                return ("label", lab["id"])
        for ln in reversed(world.lines_in_order()):
            if _near_line(ln["pts"], x, y, 6 / self.z + 1.5):
                return ("line", ln["id"])
        return None

    # ------------------------------------------------------------------ mouse
    def mousePressEvent(self, e):
        self.setFocus()
        mp = self.to_map(e.position())
        if e.button() in (Qt.RightButton, Qt.MiddleButton):
            self.drag = ("pan", e.position(), self.ox, self.oy, e.button(), False)
            return
        if e.button() != Qt.LeftButton:
            return
        world, t = rt().world, self.tool
        if t in ("raise", "lower", "smooth", "ground", "realm"):
            if self.busy or self.pix is None:
                return
            world.begin_stroke()
            self.drag = ("paint", mp)
            self.stroke_box = None
            self._dab(world.paint([mp], self.radius, self.strength, t, self.realm if t == "realm" else self.ground))
        elif t == "erase":
            self.drag = ("erase", mp)
            self._erase_at(mp)
        elif t == "mark":
            if self.kind in TERRAIN:
                self.drag = ("spray", mp)
                self.spray = []
                self._spray(mp, first=True)
            else:
                self._new_mark(mp)
        elif t == "stamp":
            key = self._stamp_key()
            if not key:
                notify.warn(tr("Pick a picture first."))
                return
            self.drag = ("stamp", mp, mp)
            self.spray = []
            if self.stamp_mode == "scatter":
                self._scatter(mp)
            else:
                self.spray = [self._stamp(mp, key)]
        elif t == "label":
            self._new_label(mp)
        elif t == "line":
            if not self.clicking:
                self.drawing = [list(mp)]
            self.drag = ("line", mp, False)
        elif t == "party":
            if e.modifiers() & Qt.ShiftModifier or not world.party()["pos"]:
                guard(world.place_party, *mp)
            else:
                self.travel(mp)
        elif t == "route":
            p = world.party()
            if not p["pos"]:
                notify.warn(tr("Put the party on the map first (🚩)."))
                return
            guard(world.set_route, p["route"] + [list(mp)])
        elif t == "ping":
            world.ping(*mp, "DM")
        elif t == "move":
            what = self.hit(mp)
            self.selected = what if what and what[0] != "party" else None
            if what:
                self.drag = ("move", what, mp, mp)
            else:
                self.drag = ("pan", e.position(), self.ox, self.oy, Qt.LeftButton, False)
            self.update()

    def mouseMoveEvent(self, e):
        mp = self.to_map(e.position())
        self.mouse = mp
        d = self.drag
        if d and d[0] == "pan":
            moved = d[5] or (e.position() - d[1]).manhattanLength() > 4
            self.drag = d[:5] + (moved,)
            if moved:
                self.auto_fit = False
                self.ox = d[2] + e.position().x() - d[1].x()
                self.oy = d[3] + e.position().y() - d[1].y()
        elif d and d[0] == "paint":
            self._dab(rt().world.paint([d[1], mp], self.radius, self.strength, self.tool,
                                       self.realm if self.tool == "realm" else self.ground))
            self.drag = ("paint", mp)
        elif d and d[0] == "erase":
            self._erase_at(mp)
        elif d and d[0] == "spray":
            if math.hypot(mp[0] - d[1][0], mp[1] - d[1][1]) >= SPRAY_GAP[self.kind] * 0.6:
                self._spray(mp)
                self.drag = ("spray", mp)
        elif d and d[0] == "stamp" and self.stamp_mode == "scatter":     # scattered under the brush
            if math.hypot(mp[0] - d[1][0], mp[1] - d[1][1]) >= max(1.0, self.radius * 0.25):
                self._scatter(mp)
                self.drag = ("stamp", mp, d[2])
        elif d and d[0] == "stamp":                            # a row of them, a picture's width apart (turned along the way)
            last = self.spray[-1] if self.spray else None
            rr = art.stamp_rect(last) if last else None
            along = self.stamp_mode == "row"
            way = math.degrees(math.atan2(mp[1] - d[1][1], mp[0] - d[1][0]))
            gap = max(1.0, (rr.width() if along else max(rr.width(), rr.height())) * 1.02) if rr else 4.0
            if along and len(self.spray) == 1 and math.hypot(mp[0] - d[2][0], mp[1] - d[2][1]) > 1:
                self.spray[0]["r"] = (self.angle + way) % 360
            if math.hypot(mp[0] - d[1][0], mp[1] - d[1][1]) >= gap:
                key = self._stamp_key()
                if key:
                    m = self._stamp(mp, key)
                    if along:
                        m["r"] = (self.angle + way) % 360
                    self.spray.append(m)
                self.drag = ("stamp", mp, d[2])
        elif d and d[0] == "move":
            self.drag = ("move", d[1], d[2], mp)
        elif d and d[0] == "line" and not self.clicking:
            last = self.drawing[-1]
            if math.hypot(mp[0] - last[0], mp[1] - last[1]) * self.z >= 3:
                self.drawing.append(list(mp))
                self.drag = ("line", d[1], True)
        self.update()

    def mouseReleaseEvent(self, e):
        d, self.drag = self.drag, None
        world = rt().world
        if not d:
            return
        if d[0] == "pan":
            if not d[5] and d[4] == Qt.RightButton:
                if self.clicking:
                    self.finish_line()
                else:
                    self._menu(e.position())
            return
        if d[0] == "paint":
            world.end_stroke()
            self.redraw(self.stroke_box)                       # the ripples round the whole stroke
        elif d[0] == "erase":
            ids, self.erasing = self.erasing, set()
            lines, self.erasing_lines = self.erasing_lines, set()
            if ids or lines:
                guard(world.remove_items, ids, lines)
        elif d[0] == "line":
            if d[2] and not self.clicking:                     # dragged: a freehand line
                pts, self.drawing = simplify(self.drawing, 0.8), []
                if len(pts) >= 2:
                    guard(world.add_line, pts, self.line_style)
            elif not self.clicking:                            # a click: the first point of a line drawn point by point
                self.clicking = True
            else:
                self.drawing.append(list(self.to_map(e.position())))
        elif d[0] == "spray":
            spots, self.spray = [(m["x"], m["y"], m["s"]) for m in self.spray], []
            if spots:
                guard(world.add_marks, self.kind, spots)
        elif d[0] == "stamp":
            spots, self.spray = [(m["x"], m["y"], m["s"], m["art"], m.get("r") or 0.0) for m in self.spray], []
            if spots:
                guard(world.add_marks, ART, spots)
        elif d[0] == "move":
            what, start, end = d[1], d[2], d[3]
            dx, dy = end[0] - start[0], end[1] - start[1]
            if math.hypot(dx, dy) * self.z < 3:
                return
            if what[0] == "party":
                if e.modifiers() & Qt.ShiftModifier:
                    guard(world.place_party, *end)
                else:
                    self.travel(end)
            elif what[0] == "mark":
                m = next((x for x in world.marks() if x["id"] == what[1]), None)
                if m:
                    guard(world.edit_mark, m["id"], x=m["x"] + dx, y=m["y"] + dy)
            elif what[0] == "label":
                lab = next((x for x in world.labels() if x["id"] == what[1]), None)
                if lab:
                    guard(world.edit_label, lab["id"], x=lab["x"] + dx, y=lab["y"] + dy)
            elif what[0] == "line":
                guard(world.edit_line, what[1], dx=dx, dy=dy)
        self.update()

    def mouseDoubleClickEvent(self, e):
        if self.tool == "move" and e.button() == Qt.LeftButton:
            what = self.hit(self.to_map(e.position()))
            if what and what[0] != "party":
                self.drag = None
                self.edit(what)
        elif self.tool == "route" and e.button() == Qt.LeftButton:
            self.panel.set_tool("move")
        elif self.tool == "line" and e.button() == Qt.LeftButton:
            self.drag = None
            self.finish_line()

    def wheelEvent(self, e):
        steps = e.angleDelta().y() / 120.0
        if e.modifiers() & Qt.ControlModifier:                # over a mark or a name: its size (the picture and words together)
            what = self.hit(self.to_map(e.position()))
            if what and what[0] in ("mark", "label"):
                self.resize_item(what, 1.1 ** steps)
                e.accept()
                return
        if e.modifiers() & Qt.AltModifier or (e.modifiers() & Qt.ShiftModifier and self.tool in BRUSHES):
            self.radius = max(3.0, min(200.0, self.radius * (1.12 ** (steps or e.angleDelta().x() / 120.0))))
            self.panel.brush_size.setValue(int(self.radius))
        else:
            self.zoom(1.18 ** steps, (e.position().x(), e.position().y()))
        e.accept()

    def leaveEvent(self, e):
        self.mouse = None
        self.update()

    def keyPressEvent(self, e):
        world = rt().world
        k, mods = e.key(), e.modifiers()
        if k == Qt.Key_Z and mods & Qt.ControlModifier:
            self.undo(redo=bool(mods & Qt.ShiftModifier))
        elif k == Qt.Key_Y and mods & Qt.ControlModifier:
            self.undo(redo=True)
        elif k in (Qt.Key_Delete, Qt.Key_Backspace) and self.selected and self.tool == "move":
            kind, ident = self.selected
            guard({"mark": world.remove_mark, "label": world.remove_label, "line": world.remove_line}[kind], ident)
            self.selected = None
        elif k in (Qt.Key_Return, Qt.Key_Enter) and self.clicking:
            self.finish_line()
        elif k == Qt.Key_Backspace and self.clicking and len(self.drawing) > 1:
            self.drawing.pop()
        elif k == Qt.Key_Backspace and self.tool == "route":
            guard(world.set_route, world.party()["route"][:-1])
        elif k == Qt.Key_BracketLeft:
            self.panel.brush_size.setValue(max(3, int(self.radius / 1.2)))
        elif k == Qt.Key_BracketRight:
            self.panel.brush_size.setValue(min(200, int(self.radius * 1.2 + 1)))
        elif k in (Qt.Key_Q, Qt.Key_E) and not mods & Qt.ControlModifier:  # turn the stamp to come, or the stamp picked
            step = (5 if mods & Qt.ShiftModifier else 15) * (-1 if k == Qt.Key_Q else 1)
            m = next((x for x in world.marks() if self.selected and self.selected[0] == "mark" and x["id"] == self.selected[1]), None)
            if self.tool != "stamp" and m and m["kind"] == ART:
                guard(world.edit_mark, m["id"], r=float(m.get("r") or 0) + step)
            elif self.tool == "stamp":
                self.panel.art_angle.setValue(int(round(self.angle + step)) % 360)
        elif k in (Qt.Key_Plus, Qt.Key_Equal, Qt.Key_Minus) and self.selected and self.selected[0] in ("mark", "label"):
            self.resize_item(self.selected, 1.1 if k != Qt.Key_Minus else 1 / 1.1)
        elif k in LAYER_KEYS and self.selected and self.selected[0] == "line":
            guard(world.restack_line, self.selected[1], LAYER_KEYS[k])
        elif k == Qt.Key_Escape:
            self.selected = None
            self.drawing, self.clicking = [], False
            if self.tool == "route":
                self.panel.set_tool("move")
        else:
            return super().keyPressEvent(e)
        self.update()

    def _sized(self, kind, item):
        """The item with the size the wheel is giving it (not saved yet)."""
        sc = self.scaling
        return dict(item, s=sc[2]) if sc and sc[0] == kind and sc[1] == item.get("id") else item

    def resize_item(self, what, factor):
        """A mark or name bigger or smaller (its picture and words together); saved when the wheel stops."""
        world = rt().world
        sc = self.scaling
        if sc and (sc[0], sc[1]) == tuple(what):
            now = sc[2]
        else:
            if sc:
                self._commit_size()
            items = world.marks() if what[0] == "mark" else world.labels()
            item = next((x for x in items if x["id"] == what[1]), None)
            if not item:
                return
            now = float(item.get("s") or 1)
        self.scaling = (what[0], what[1], round(max(SCALE_MIN, min(SCALE_MAX, now * factor)), 3))
        self.selected = tuple(what)
        self.size_timer.start()
        self.update()

    def _commit_size(self):
        sc, self.scaling = self.scaling, None
        if sc:
            world = rt().world
            guard(world.edit_mark if sc[0] == "mark" else world.edit_label, sc[1], s=sc[2])

    def finish_line(self):
        """End a line drawn point by point (two points at least)."""
        pts, self.drawing, self.clicking = self.drawing, [], False
        if len(pts) >= 2:
            guard(rt().world.add_line, pts, self.line_style)
        self.update()

    def undo(self, redo=False):
        if self.tool == "party" and not redo and rt().world.moves_back():     # with 🚩: Ctrl+Z takes the last move back
            self.take_back()
            return
        rect = guard(rt().world.redo if redo else rt().world.undo)
        if rect and rect[2] > rect[0]:
            if rect[2] - rect[0] >= rt().world.size[0] and rect[3] - rect[1] >= rt().world.size[1]:
                self.full_render()
            else:
                self.redraw(rect)
        self.update()

    # ------------------------------------------------------------------ marks
    def _stamp(self, mp, key) -> dict:
        """A stamp not yet on the map (the size of new marks, turned as set - or any way, with 🎲 Turn)."""
        return {"id": None, "kind": ART, "art": key, "x": mp[0], "y": mp[1], "name": "", "s": self.panel.mark_size.value() / 100.0,
                "r": random.uniform(0, 360) if self.spin else self.angle}

    def _scatter(self, mp):
        """Stamps scattered round the brush, not on top of each other (a wood of single trees, a town of houses)."""
        key = self._stamp_key()
        if not key:
            return
        size = art.stamp_rect(self._stamp(mp, key))
        gap = max(0.8, math.hypot(size.width(), size.height()) * 0.42)
        n = 1 if self.radius < gap * 1.2 else max(1, int((self.radius / gap) ** 2 * 0.25))
        reach = self.radius + gap * 3
        near = [art.stamp_box(m) for m in rt().world.marks() if m["kind"] == ART and abs(m["x"] - mp[0]) < reach
                and abs(m["y"] - mp[1]) < reach] + [art.stamp_box(m) for m in self.spray]
        for _ in range(n * 6):
            if n <= 0:
                break
            a, rr = random.uniform(0, math.tau), self.radius * math.sqrt(random.random()) if self.radius > gap else 0
            m = self._stamp((mp[0] + math.cos(a) * rr, mp[1] + math.sin(a) * rr), key)
            box = art.stamp_box(m)
            if any(art.boxes_cross(box, b) for b in near):           # never on top of another stamp
                continue
            self.spray.append(m)
            near.append(box)
            key = self._stamp_key() or key
            n -= 1

    def _stamp_key(self):
        """The picture the next stamp gets: the one picked, or (🎲) any of its group."""
        e = stamps.get(self.art)
        if not e:
            return None
        return random.choice(stamps.in_group(e["group"]))["key"] if self.mix else e["key"]

    def _spray(self, mp, first=False):
        """A few terrain marks scattered round the brush."""
        gap = SPRAY_GAP[self.kind]
        n = 1 if self.radius < gap * 1.2 else max(1, int((self.radius / gap) ** 1.4 * 0.5))
        world = rt().world
        taken = [(m["x"], m["y"]) for m in world.marks() if m["kind"] in TERRAIN] + [(m["x"], m["y"]) for m in self.spray]
        for _ in range(n * 3):
            if n <= 0:
                break
            a, rr = random.uniform(0, math.tau), self.radius * math.sqrt(random.random()) if self.radius > gap else 0
            x, y = mp[0] + math.cos(a) * rr, mp[1] + math.sin(a) * rr * 0.8
            if any(math.hypot(x - tx, (y - ty) * 1.4) < gap for tx, ty in taken[-400:]):
                continue
            s = round(random.uniform(0.8, 1.25) * (1.15 if self.kind == "mountain" and self.radius > 40 else 1.0), 2)
            m = {"id": None, "kind": self.kind, "x": x, "y": y, "name": "", "s": s, "v": random.randrange(97)}
            self.spray.append(m)
            taken.append((x, y))
            n -= 1

    def _erase_at(self, mp):
        r = self.radius
        for m in rt().world.marks():
            if math.hypot(m["x"] - mp[0], m["y"] - mp[1]) <= r:
                self.erasing.add(m["id"])
        for ln in rt().world.lines():
            if _near_line(ln["pts"], mp[0], mp[1], r):
                self.erasing_lines.add(ln["id"])

    def _new_mark(self, mp):
        world = rt().world
        if self.kind == "compass":                             # no name: it just goes there
            m = guard(world.add_mark, "compass", mp[0], mp[1], "", 1.0 if self.z > 0.6 else 1.6)
            if m:
                self.selected = ("mark", m["id"])
            return
        got = dialogs.form(self, tr("New {0}", tr(KIND_NAMES[self.kind]).lower()), [
            {"key": "name", "label": tr("Name"), "value": suggest_name() if self.kind not in ("poi",) else ""},
            {"key": "kind", "label": tr("Kind"), "kind": "select", "value": self.kind,
             "options": [(f"{KIND_GLYPH[k]}  {tr(KIND_NAMES[k])}", k) for k in MARK_KINDS if k not in SIZED]}], tr("Place"))
        if got:
            m = guard(world.add_mark, got["kind"], mp[0], mp[1], got["name"], self.panel.mark_size.value() / 100.0)
            if m:
                self.selected = ("mark", m["id"])

    def _new_label(self, mp, lab=None):
        world = rt().world
        got = dialogs.form(self, tr("Edit the name") if lab else tr("A name on the map"), [
            {"key": "text", "label": tr("Name"), "value": lab["text"] if lab else "", "required": True},
            {"key": "style", "label": tr("Kind"), "kind": "select", "value": lab["style"] if lab else ("land" if world.land_at(*mp) else "sea"),
             "options": [(tr("Land (a place)"), "land"), (tr("Sea (italic)"), "sea"), (tr("Region (wide letters)"), "region"),
                         (tr("Banner (on a ribbon)"), "banner"), (tr("Plaque (on a parchment tag)"), "plaque"),
                         (tr("Title (the map's own name, with flourishes)"), "title")]},
            {"key": "size", "label": tr("Size"), "kind": "select", "value": lab["size"] if lab else 2,
             "options": [(tr("Small"), 1), (tr("Medium"), 2), (tr("Large"), 3), (tr("Huge"), 4)]},
            {"key": "angle", "label": tr("Angle (degrees)"), "kind": "int", "value": int(lab["angle"]) if lab else 0, "min": -90, "max": 90},
            {"key": "bend", "label": tr("Bend (degrees of arc)"), "kind": "int", "value": int(lab.get("bend") or 0) if lab else 0,
             "min": -120, "max": 120, "tip": tr("Bow the name along an arc, as a kingdom's name follows its land: + arches up, - sags")},
            {"key": "scale", "label": tr("Scale (%)"), "kind": "int", "value": round(float(lab.get("s") or 1) * 100) if lab else 100,
             "min": 30, "max": 400}],
            tr("OK"))
        if not got or not got["text"].strip():
            return
        if lab:
            guard(world.edit_label, lab["id"], text=got["text"], style=got["style"], size=got["size"], angle=got["angle"],
                  s=got["scale"] / 100.0, bend=got["bend"])
        else:
            new = guard(world.add_label, got["text"], mp[0], mp[1], got["size"], got["style"], got["angle"])
            if new:
                self.selected = ("label", new["id"])
                if got["scale"] != 100 or got["bend"]:
                    guard(world.edit_label, new["id"], s=got["scale"] / 100.0, bend=got["bend"])

    def edit(self, what):
        world = rt().world
        if what[0] == "line":
            ln = next((x for x in world.lines() if x["id"] == what[1]), None)
            if ln:
                got = dialogs.form(self, tr("Edit the line"), [
                    {"key": "style", "label": tr("Kind"), "kind": "select", "value": ln["style"],
                     "options": [(tr(LINE_NAMES[k]), k) for k in LINE_STYLES]}], tr("OK"))
                if got:
                    guard(world.edit_line, ln["id"], style=got["style"])
            return
        if what[0] == "label":
            lab = next((x for x in world.labels() if x["id"] == what[1]), None)
            if lab:
                self._new_label((lab["x"], lab["y"]), lab)
            return
        m = next((x for x in world.marks() if x["id"] == what[1]), None)
        if not m:
            return
        if m["kind"] == ART:
            got = dialogs.form(self, tr("Edit the stamp"), [
                {"key": "name", "label": tr("Name"), "value": m["name"], "tip": tr("Written beside the picture (leave it empty for none)")},
                {"key": "scale", "label": tr("Size (%)"), "kind": "int", "value": round(float(m.get("s") or 1) * 100), "min": 30, "max": 400},
                {"key": "angle", "label": tr("Turned (degrees)"), "kind": "int", "value": round(float(m.get("r") or 0)), "min": 0, "max": 359,
                 "tip": tr("Q and E turn it too, when it is picked")}],
                tr("OK"))
            if got:
                guard(world.edit_mark, m["id"], name=got["name"], s=got["scale"] / 100.0, r=got["angle"])
            return
        kinds = [k for k in MARK_KINDS if (k in SIZED) == (m["kind"] in SIZED)]
        got = dialogs.form(self, tr("Edit the mark"), [
            {"key": "name", "label": tr("Name"), "value": m["name"]},
            {"key": "kind", "label": tr("Kind"), "kind": "select", "value": m["kind"],
             "options": [(f"{KIND_GLYPH[k]}  {tr(KIND_NAMES[k])}", k) for k in kinds]},
            {"key": "scale", "label": tr("Size (%)"), "kind": "int", "value": round(float(m.get("s") or 1) * 100), "min": 30, "max": 400,
             "tip": tr("The mark and its name together (Ctrl+wheel over it, or + and - when it is picked)")}], tr("OK"))
        if got:
            guard(world.edit_mark, m["id"], name=got["name"], kind=got["kind"], s=got["scale"] / 100.0)

    def _menu(self, pos):
        world = rt().world
        mp = self.to_map(pos)
        what = self.hit(mp)
        menu = QMenu(self)
        if what and what[0] in ("mark", "label", "line"):
            self.selected = what
            menu.addAction(tr("Edit…"), lambda: self.edit(what))
            menu.addAction(tr("Remove"), lambda: guard({"mark": world.remove_mark, "label": world.remove_label,
                                                        "line": world.remove_line}[what[0]], what[1]))
            if what[0] == "line":
                layer = menu.addMenu(tr("Layer"))
                for how, words in (("front", "⤒ Bring to the front (Home)"), ("up", "↑ Bring forward (Page Up)"),
                                   ("down", "↓ Send backward (Page Down)"), ("back", "⤓ Send to the back (End)")):
                    layer.addAction(tr(words), lambda h=how: guard(world.restack_line, what[1], h))
            menu.addSeparator()
        menu.addAction(tr("🚩 The party travels here"), lambda: self.travel(mp))
        menu.addAction(tr("🚩 Put the party here (no trail)"), lambda: guard(world.place_party, *mp))
        if world.moves_back():
            menu.addAction(tr("↩ Take back the party's last move"), self.take_back)
        if world.party()["pos"]:
            menu.addAction(tr("🧭 Add to the route"), lambda: guard(world.set_route, world.party()["route"] + [list(mp)]))
        menu.addAction(tr("📍 Ping here"), lambda: world.ping(*mp, "DM"))
        menu.addSeparator()
        for k in ("city", "town", "village"):
            menu.addAction(tr("{0} {1} here…", KIND_GLYPH[k], tr(KIND_NAMES[k])), lambda k=k: (setattr(self, "kind", k), self._new_mark(mp)))
        menu.addAction(tr("🔤 A name here…"), lambda: self._new_label(mp))
        menu.exec(self.mapToGlobal(pos.toPoint()))
        self.update()


@panel("world.map", "World map", "World", icon="🗺", area="center",
       description="Paint a parchment world map (raise land from the sea), mark towns and names, send it to the players; "
                   "the party's position, route and food.")
class WorldPanel(Panel):
    def build(self):
        self.canvas = WorldCanvas(self)
        bar = QWidget()
        flow = FlowLayout(bar, spacing=3)
        self.tools = QButtonGroup(self)
        self.tool_btns = {}
        for key, glyph, tip in TOOLS:
            b = QPushButton(glyph)
            b.setCheckable(True)
            b.setFixedSize(32, 28)
            b.setToolTip(tr(tip))
            b.clicked.connect(lambda _c=False, k=key: self.set_tool(k))
            self.tools.addButton(b)
            self.tool_btns[key] = b
            flow.addWidget(b)
        flow.addWidget(label(" │ ", role="dim"))
        self.size_lbl = label(tr("Brush"), role="dim")
        self.brush_size = QSlider(Qt.Horizontal)
        self.brush_size.setRange(3, 200)
        self.brush_size.setValue(int(self.canvas.radius))
        self.brush_size.setFixedWidth(110)
        self.brush_size.setToolTip(tr("Brush size ([ and ], or Alt+wheel)"))
        self.brush_size.valueChanged.connect(lambda v: setattr(self.canvas, "radius", float(v)) or self.canvas.update())
        self.power_lbl = label(tr("Strength"), role="dim")
        self.power = QSlider(Qt.Horizontal)
        self.power.setRange(2, 100)
        self.power.setValue(int(self.canvas.strength * 100))
        self.power.setFixedWidth(80)
        self.power.setToolTip(tr("How much each dab raises or lowers the land"))
        self.power.valueChanged.connect(lambda v: setattr(self.canvas, "strength", v / 100.0))
        self.kind = combo([(f"{KIND_GLYPH[k]}  {tr(KIND_NAMES[k])}", k) for k in MARK_KINDS], "city",
                          on_change=self._kind, tip=tr("What the 🏰 tool places"))
        self.ground_kind = combo([(tr("The land's own"), 0)] + [(tr(g[0]), k) for k, g in R.GROUNDS.items()], 1,
                                 on_change=lambda k: setattr(self.canvas, "ground", k), tip=tr("What the 🎨 brush paints"))
        self.realm_kind = combo([(tr("No realm"), 0)] + [(tr(v[0]), k) for k, v in R.REALMS.items()], 1,
                                on_change=lambda k: setattr(self.canvas, "realm", k), tip=tr("Which realm the 🏳 brush paints"))
        self.line_kind = combo([(f"{LINE_GLYPH[k]}  {tr(LINE_NAMES[k])}", k) for k in LINE_STYLES], "road",
                               on_change=lambda k: setattr(self.canvas, "line_style", k), tip=tr("What the ✒ tool draws"))
        self.mark_size = spin(100, 30, 400, width=58, tip=tr("Size of new marks and their names (%) · Ctrl+wheel over a mark or "
                                                             "name resizes it"))
        self.mark_size.setSuffix(" %")
        for w in (self.size_lbl, self.brush_size, self.power_lbl, self.power, self.kind, self.mark_size, self.ground_kind, self.realm_kind,
                  self.line_kind):
            flow.addWidget(w)
        flow.addWidget(label(" │ ", role="dim"))
        flow.addWidget(button("↶", lambda: self.canvas.undo(), kind="flat", width=30, tip=tr("Undo (Ctrl+Z)")))
        flow.addWidget(button("↷", lambda: self.canvas.undo(redo=True), kind="flat", width=30, tip=tr("Redo (Ctrl+Y)")))
        flow.addWidget(button("⤢", self.canvas.fit, kind="flat", width=30, tip=tr("Fit the whole map")))
        flow.addWidget(button("⌖", self.canvas.find_party, kind="flat", width=30, tip=tr("Show where the party is")))
        flow.addWidget(button("⋯", self._more, kind="flat", width=30, tip=tr("New land, map settings, export")))
        # the 🖼 tool's pictures: a group, and its pictures in a strip
        self.art_group = combo([], None, on_change=self._art_group, width=210, tip=tr("Which pictures the strip shows"))
        self.art_mix = check(tr("🎲 Mix"), False, lambda on: setattr(self.canvas, "mix", on),
                             tip=tr("Each stamp a different picture of the group (a wood of different trees, a town of different houses)"))
        self.art_spin = check(tr("🎲 Turn"), False, lambda on: setattr(self.canvas, "spin", on),
                              tip=tr("Each stamp turned a random way (trees, boulders, scattered houses)"))
        self.art_mode = combo([(tr("Row along the drag"), "row"), (tr("Row, all one way"), "line"), (tr("Scatter under the brush"), "scatter")],
                              "row", on_change=self._art_mode, width=170,
                              tip=tr("What dragging does: a row turned along the way you drag (houses along a road, a pier, a "
                                     "hedge), a row all turned the same way, or stamps scattered under the brush ([ and ] size it)"))
        self.art_angle = spin(0, -1, 360, width=62, tip=tr("How far new stamps are turned (degrees) · Q / E: 15° (Shift: 5°)"))
        self.art_angle.setSuffix("°")
        self.art_angle.setWrapping(True)
        self.art_angle.valueChanged.connect(self._art_angle)
        self.art_strip = QListWidget()
        self.art_strip.setViewMode(QListView.IconMode)
        self.art_strip.setFlow(QListView.LeftToRight)
        self.art_strip.setWrapping(False)
        self.art_strip.setMovement(QListView.Static)
        self.art_strip.setIconSize(QSize(46, 46))
        self.art_strip.setGridSize(QSize(54, 54))
        self.art_strip.setFixedHeight(72)
        self.art_strip.setHorizontalScrollMode(QListView.ScrollPerPixel)
        self.art_strip.currentItemChanged.connect(self._art_pick)
        picks = widget(col(row(self.art_group, button(
            "📂", self.open_stamps, kind="flat", width=30, tip=tr("Your own pictures: put PNG or WebP files in this folder (a folder "
                                                               "in it: a group of its own); they show here next time"))),
            row(self.art_mode, self.art_angle), row(self.art_mix, self.art_spin, stretch())))
        picks.setFixedWidth(260)
        self.art_strip.setFixedHeight(92)
        self.stamp_row = widget(row(picks, self.art_strip))
        # sending to the players
        self.status = label("", role="dim")
        self.send = button(tr("📤 Send to players"), self.publish, kind="primary",
                           tip=tr("The players see the map as it is now (land, marks and names). The party, its route, "
                                  "pings and food always show live."))
        self.auto = check(tr("Live"), False, self._auto, tip=tr("Send every change to the players by itself"))
        self.map_pick = combo([], None, on_change=self._switch, width=200,
                              tip=tr("The map open here is the one the players see (as you last sent it)"))
        self._mid = rt().world.mid
        self.look_pick = combo([(tr(LOOK_NAMES[k]), k) for k in R.LOOKS], rt().world.d["look"], on_change=self._look, width=150,
                               tip=tr("How the land and the sea are drawn, here and for the players"))
        top = row(label("🗺", role="dim"), self.map_pick,
                  button("＋", self.new_map, kind="flat", width=30, tip=tr("A new map (all sea), opened")), self.look_pick,
                  stretch(), widget(row(self.status, self.send, self.auto)))
        split = QSplitter(Qt.Horizontal)
        split.addWidget(self.canvas)
        self.group = GroupColumn(self)
        side = scroll(self.group)
        side.setMinimumWidth(230)
        split.addWidget(side)
        split.setStretchFactor(0, 1)
        split.setStretchFactor(1, 0)
        split.setSizes([900, 270])
        self.split = split
        self.hint = label("", role="dim", wrap=True)
        lay = self.layout()
        lay.addWidget(bar)
        lay.addWidget(self.stamp_row)
        lay.addLayout(top)
        lay.addWidget(split, 1)
        lay.addWidget(self.hint)
        self.set_tool("raise")
        self.on(events.WORLD, self.refresh)
        self.on(events.WORLD_PING, self._pinged)
        self._told = 0.0
        self.canvas.full_render()

    @staticmethod
    def _undo_key(e):
        """Ctrl+Z (undo), Ctrl+Y or Ctrl+Shift+Z (redo); None for any other key."""
        if not e.modifiers() & Qt.ControlModifier:
            return None
        if e.key() == Qt.Key_Z:
            return "redo" if e.modifiers() & Qt.ShiftModifier else "undo"
        return "redo" if e.key() == Qt.Key_Y else None

    def event(self, e):
        # The Battle menu's Undo / Redo are keys of the whole editor: inside this window they undo the map instead
        if e.type() == QEvent.ShortcutOverride and self._undo_key(e):
            e.accept()
            return True
        return super().event(e)

    def keyPressEvent(self, e):
        how = self._undo_key(e)
        if how:
            self.canvas.undo(redo=how == "redo")
            return
        super().keyPressEvent(e)

    def _pinged(self):
        """A ping: the rings on the map, and a word when a player pinged (at most every few seconds)."""
        self.canvas.pinged()
        pings = rt().world.recent_pings()
        last = pings[-1] if pings else None
        if last and last.get("uid") and time.time() - self._told > 4:
            self._told = time.time()
            notify.info(tr("📍 {0} pinged the world map", last["who"]))

    def set_tool(self, key):
        self.canvas.tool = key
        self.tool_btns[key].setChecked(True)
        brushy = key in BRUSHES or (key == "mark" and self.canvas.kind in TERRAIN) or (key == "stamp" and self.canvas.stamp_mode == "scatter")
        for w in (self.size_lbl, self.brush_size):
            w.setVisible(brushy)
        for w in (self.power_lbl, self.power):
            w.setVisible(key in ("raise", "lower", "smooth"))
        self.kind.setVisible(key == "mark")
        self.ground_kind.setVisible(key == "ground")
        self.realm_kind.setVisible(key == "realm")
        self.mark_size.setVisible(key == "stamp" or (key == "mark" and self.canvas.kind not in SIZED))
        self.stamp_row.setVisible(key == "stamp")
        if key == "stamp":
            self._fill_groups()
        self.line_kind.setVisible(key == "line")
        if key != "line":
            self.canvas.drawing, self.canvas.clicking = [], False
        self.hint.setText(tr(next(t for k, _g, t in TOOLS if k == key)) + "  ·  " +
                          tr("wheel: zoom · right-drag: pan · Ctrl+Z / Ctrl+Y: undo, redo"))
        self.canvas.setCursor(Qt.CrossCursor if key != "move" else Qt.ArrowCursor)
        self.canvas.update()

    def _kind(self, k):
        self.canvas.kind = k
        self.set_tool("mark")

    # ------------------------------------------------------------------ stamps
    def _fill_groups(self):
        """The groups of pictures (the DM's own folder looked at again: new pictures show)."""
        stamps.reload()
        art.forget_stamps()
        e = stamps.get(self.canvas.art)
        lead = "Painted" if rt().world.d["look"] in R.COLOUR_LOOKS else "Ink"      # (the set that suits the look first)
        groups = sorted(stamps.groups(), key=lambda g: not g.startswith(lead))
        want = e["group"] if e else (self.art_group.currentData() or (groups[0] if groups else None))
        set_items(self.art_group, [(tr(g), g) for g in groups], want)
        self._art_group(self.art_group.currentData())

    def _art_group(self, group):
        strip = self.art_strip
        strip.blockSignals(True)
        strip.clear()
        pick = None
        for e in stamps.in_group(group) if group else []:
            it = QListWidgetItem(QIcon(art.stamp_icon(e["key"], 46)), "")
            it.setData(Qt.UserRole, e["key"])
            it.setToolTip(tr(e["name"]))
            it.setSizeHint(QSize(54, 54))
            strip.addItem(it)
            if e["key"] == self.canvas.art:
                pick = it
        strip.blockSignals(False)
        if strip.count():
            strip.setCurrentItem(pick or strip.item(0))
            strip.scrollToItem(strip.currentItem())

    def _art_mode(self, mode):
        self.canvas.stamp_mode = mode
        self.set_tool("stamp")

    def _art_angle(self, v):
        if v < 0 or v > 359:                                    # (the arrows go round)
            self.art_angle.setValue(v % 360)
            return
        self.canvas.angle = float(v)
        self.canvas.update()

    def _art_pick(self, item, _old=None):
        if item:
            self.canvas.art = item.data(Qt.UserRole)
            self.canvas.update()

    def open_stamps(self):
        os.makedirs(stamps.USER, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(os.path.abspath(stamps.USER)))

    def _look(self, look):
        world = rt().world
        if look and look != world.d["look"]:
            guard(world.set_settings, look=look)
            self.canvas.full_render()
            if self.canvas.tool == "stamp":
                self._fill_groups()

    def refresh(self):
        world = rt().world
        if self.look_pick.currentData() != world.d["look"]:
            self.look_pick.blockSignals(True)
            self.look_pick.setCurrentIndex(max(0, self.look_pick.findData(world.d["look"])))
            self.look_pick.blockSignals(False)
        maps = [(m["name"], m["id"]) for m in world.maps()]
        if [(self.map_pick.itemText(i), self.map_pick.itemData(i)) for i in range(self.map_pick.count())] != maps \
                or self.map_pick.currentData() != world.mid:
            self.map_pick.blockSignals(True)
            set_items(self.map_pick, maps, world.mid)
            self.map_pick.blockSignals(False)
        if world.mid != self._mid:                              # another map is open: draw it
            self._mid = world.mid
            c = self.canvas
            c.selected, c.drawing, c.clicking, c.fitted, c.auto_fit = None, [], False, False, False
            c.layer = None
            c.full_render()
        pub = world.published()
        if world.publishing:
            self.status.setText(tr("Sending…"))
        elif not pub:
            self.status.setText(tr("The players haven't been sent the map yet."))
        elif world.changed:
            self.status.setText(tr("Players see the map from {0} · changes not sent", time.strftime("%H:%M", time.localtime(pub["at"]))))
        else:
            self.status.setText(tr("Players see this map (sent {0})", time.strftime("%H:%M", time.localtime(pub["at"]))))
        self.send.setEnabled(not world.publishing)
        self.auto.blockSignals(True)
        self.auto.setChecked(world.settings()["auto"])
        self.auto.blockSignals(False)
        self.group.refresh()
        self.canvas.stale()

    def publish(self):
        guard(rt().world.publish)
        self.refresh()

    def _auto(self, on):
        guard(rt().world.set_settings, auto=on)
        if on:
            guard(rt().world.publish)

    def _switch(self, mid):
        if mid and mid != rt().world.mid:
            guard(rt().world.switch, mid)

    def new_map(self):
        got = dialogs.form(self, tr("A new map"), [
            {"key": "name", "label": tr("The map's name"), "value": "", "required": True},
            {"key": "miles", "label": tr("Width of the map in miles"), "kind": "int", "value": 300, "min": 1, "max": 100000}], tr("Make it"))
        if got and got["name"].strip():
            guard(rt().world.new_map, got["name"], got["miles"])

    def delete_map(self):
        world = rt().world
        if len(world.maps()) < 2:
            notify.warn(tr("This is the only map."))
            return
        if dialogs.confirm(self, tr("Delete the map \"{0}\" for good? Its land, marks, names and lines go with it.", world.d["name"])):
            guard(world.delete_map, world.mid)

    def _more(self):
        world = rt().world
        menu = QMenu(self)
        menu.addAction(tr("🗺 A new map…"), self.new_map)
        menu.addAction(tr("🗑 Delete this map…"), self.delete_map)
        menu.addSeparator()
        menu.addAction(tr("🎲 Random land…"), self.generate)
        menu.addAction(tr("🌲 Dress the land (mountains, woods, hills)"), self.dress)
        menu.addAction(tr("🏘 Settle the land (named towns and roads)"), self.settle)
        menu.addAction(tr("🏳 Divide the land into realms"), self.divide)
        menu.addAction(tr("🖌 Repaint the stamps for this look"), self.restyle)
        menu.addAction(tr("🌊 All sea again (clear the land)"), self.clear_land)
        menu.addSeparator()
        menu.addAction(tr("⚙ Map settings…"), self.settings)
        menu.addAction(tr("💾 Save the map as a picture…"), self.export)
        menu.addSeparator()
        menu.addAction(tr("🚩 Take the party off the map"), lambda: guard(world.remove_party))
        menu.exec(self.cursor().pos())

    def generate(self):
        got = dialogs.form(self, tr("Random land"), [
            {"key": "land", "label": tr("How much land (%)"), "kind": "int", "value": 40, "min": 10, "max": 80},
            {"key": "parts", "label": tr("How many continents"), "kind": "int", "value": 1, "min": 1, "max": 5},
            {"key": "dress", "label": tr("Dress it with mountains, woods and hills"), "kind": "check", "value": True},
            {"key": "settle", "label": tr("Settle it with named towns and roads"), "kind": "check", "value": False},
            {"key": "divide", "label": tr("Divide it into realms"), "kind": "check", "value": False}],
            tr("Make it"))
        if got and dialogs.confirm(self, tr("Replace the land on the map with a random coast? (Ctrl+Z brings it back)")):
            if not guard_ok(rt().world.generate, None, got["land"] / 100.0, got["parts"]):
                return                                          # (no new land: nothing to dress or settle)
            if got["dress"]:
                busy(rt().world.dress)
            if got["settle"]:
                busy(rt().world.settle)
            if got["divide"]:                                   # (after the towns: the realms gather round them)
                busy(rt().world.divide)
            self.canvas.full_render()

    def dress(self):
        if dialogs.confirm(self, tr("Set mountain ranges, hills, woods and trees over the land (painted ones, or ink ones on a "
                                    "parchment or sepia map), around what is on the map already? (Ctrl+Z takes it back)")):
            n = busy(rt().world.dress)
            if n is not None:
                notify.info(tr("{0} stamps set on the land.", n))
                self.canvas.full_render()

    def settle(self):
        if dialogs.confirm(self, tr("Set named cities, towns, villages, harbours and castles over the land, on its rivers and "
                                    "coasts, joined by roads, and name the land, the sea, its bays, lakes and rivers and the map "
                                    "itself? (Ctrl+Z takes them back)")):
            n = busy(rt().world.settle)
            if n is not None:
                notify.info(tr("{0} towns set on the land.", n))

    def divide(self):
        got = dialogs.form(self, tr("Divide the land into realms"), [
            {"key": "n", "label": tr("How many realms"), "kind": "int", "value": 3, "min": 2, "max": len(R.REALMS)}], tr("Divide"))
        if got:
            n = busy(rt().world.divide, got["n"])
            if n is not None:
                notify.info(tr("The land is split into {0} realms (Ctrl+Z takes it back).", n))
                self.canvas.full_render()

    def restyle(self):
        world = rt().world
        painted = world.d["look"] in R.COLOUR_LOOKS
        if dialogs.confirm(self, tr("Swap the map's ink and top-down stamps for painted ones (mountains, woods, towns, fields, "
                                    "ships...), keeping where they are and how much ground they cover? (Ctrl+Z takes it back)") if painted else
                           tr("Swap the map's painted stamps for ink ones, keeping where they are and how much ground they "
                              "cover? (Ctrl+Z takes it back)")):
            n = busy(world.restyle)
            if n is not None:
                notify.info(tr("{0} stamps repainted.", n))

    def clear_land(self):
        if dialogs.confirm(self, tr("Sink all the land back into the sea? (Ctrl+Z brings it back)")):
            guard(rt().world.clear_land)
            self.canvas.full_render()

    def settings(self):
        world = rt().world
        s = world.settings()
        got = dialogs.form(self, tr("Map settings"), [
            {"key": "name", "label": tr("The map's name"), "value": s["name"]},
            {"key": "miles", "label": tr("Width of the map in miles"), "kind": "int", "value": int(s["miles"]), "min": 1, "max": 100000,
             "tip": tr("Sets the distances and travel days the party's moves and route show")},
            {"key": "pace", "label": tr("Travel pace"), "kind": "select", "value": s["pace"],
             "options": [(tr("{0} ({1} miles a day)", tr(p), n), p) for p, n in PACES.items()]},
            {"key": "rough", "label": tr("Coast roughness (%)"), "kind": "int", "value": round(s["rough"] * 100), "min": 10, "max": 150,
             "tip": tr("How far the coast wanders off what you paint: low for a real place's coastline, high for wild shores")},
            {"key": "look", "label": tr("Look"), "kind": "select", "value": s["look"],
             "options": [(tr("Painted (colour land and sea)"), "painted"), (tr("Painted, turquoise sea"), "teal"),
                         (tr("Antique (golden land, dark sea)"), "antique"),
                         (tr("Sepia (tan land, grey sea, ink marks)"), "sepia"), (tr("Parchment (ink on old paper)"), "parchment")],
             "tip": tr("How the land and the sea are drawn, here and for the players")},
            {"key": "grid", "label": tr("Grid"), "kind": "select", "value": s["grid"],
             "options": [(tr("None"), "none"), (tr("Hexes"), "hex"), (tr("Squares"), "square")],
             "tip": tr("A faint grid over the map (hexes for a hexcrawl), here and for the players")},
            {"key": "grid_miles", "label": tr("Grid size in miles"), "kind": "int", "value": int(round(s["grid_miles"])), "min": 1, "max": 10000},
            {"key": "scale_bar", "label": tr("Show a scale bar of miles"), "kind": "check", "value": s["scale_bar"]},
            {"key": "plaques", "label": tr("Town names on parchment plaques"), "kind": "check", "value": s["plaques"]},
            {"key": "frame", "label": tr("The map's edge (painted looks)"), "kind": "select", "value": s["frame"],
             "options": [(tr("A gilt-lined border"), "border"), (tr("Clouds drifting in"), "clouds"), (tr("None"), "none")]},
            {"key": "scale", "label": tr("Sharpness"), "kind": "select", "value": s["scale"],
             "options": [(tr(v), k) for k, v in SCALES.items()],
             "tip": tr("How sharp the parchment is drawn (here and for the players). Low is about four times quicker to "
                       "open and to paint on, and blurrier up close; High is crisp when zoomed in, and slower.")}],
            tr("OK"))
        if got:
            guard(world.set_settings, name=got["name"], miles=got["miles"], pace=got["pace"], rough=got["rough"] / 100.0,
                  scale=got["scale"], look=got["look"], grid=got["grid"], grid_miles=got["grid_miles"],
                  scale_bar=got["scale_bar"], frame=got["frame"], plaques=got["plaques"])
            self.canvas.update()
            if abs(got["rough"] / 100.0 - s["rough"]) > 0.001 or got["scale"] != s["scale"] or got["look"] != s["look"] or got["frame"] != s["frame"]:
                self.canvas.full_render()

    def export(self):
        from PySide6.QtWidgets import QFileDialog
        path, _ = QFileDialog.getSaveFileName(self, tr("Save the map as a picture"), rt().world.settings()["name"] + ".png",
                                              "PNG (*.png)")
        if not path or self.canvas.pix is None:
            return
        out = QPixmap(self.canvas.pix.size())
        out.fill(Qt.transparent)
        g = QPainter(out)
        g.setRenderHint(QPainter.Antialiasing)
        g.drawPixmap(0, 0, self.canvas.pix)
        world = rt().world
        art.set_look(world.d["look"])
        art.PLAQUES = world.d["plaques"]
        g.scale(world.scale, world.scale)
        art.paint_grid(g, world.grid(), *world.size)
        for ln in world.lines_in_order():
            art.paint_line(g, ln)
        art.paint_marks(g, sorted(world.marks(), key=lambda m: m["y"]))
        for lab in world.labels():
            art.paint_label(g, lab)
        if world.d["scale_bar"]:
            art.paint_scale_bar(g, world.miles_per_px(), *world.size)
        g.end()
        if out.save(path):
            notify.info(tr("Saved {0}", path))

    def save_state(self) -> dict:
        c = self.canvas
        return {"tool": c.tool, "radius": c.radius, "strength": c.strength, "kind": c.kind, "split": self.split.sizes(),
                "art": c.art, "mix": c.mix, "spin": c.spin, "angle": c.angle, "stamp_mode": c.stamp_mode, "ground": c.ground}

    def restore_state(self, state: dict):
        c = self.canvas
        c.radius = float(state.get("radius") or c.radius)
        c.strength = float(state.get("strength") or c.strength)
        if state.get("kind") in MARK_KINDS:
            c.kind = state["kind"]
            self.kind.setCurrentIndex(max(0, self.kind.findData(c.kind)))
        if state.get("ground") in R.GROUNDS or state.get("ground") == 0:
            c.ground = state["ground"]
            self.ground_kind.setCurrentIndex(max(0, self.ground_kind.findData(c.ground)))
        self.brush_size.setValue(int(c.radius))
        self.power.setValue(int(c.strength * 100))
        if state.get("split"):
            self.split.setSizes(state["split"])
        c.art = state.get("art") or c.art
        c.mix, c.spin = bool(state.get("mix")), bool(state.get("spin"))
        c.stamp_mode = state.get("stamp_mode") if state.get("stamp_mode") in ("row", "line", "scatter") else "row"
        self.art_mix.setChecked(c.mix)
        self.art_spin.setChecked(c.spin)
        self.art_mode.setCurrentIndex(max(0, self.art_mode.findData(c.stamp_mode)))
        self.art_angle.setValue(int(state.get("angle") or 0) % 360)
        if state.get("tool") in dict((k, 1) for k, _g, _t in TOOLS):
            self.set_tool(state["tool"])

