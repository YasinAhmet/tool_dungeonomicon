"""Drawing on the battle map: the tool bar (select, rooms (roomart.py), draw with snapping, free draw, erase, colours, the quick bar of
doors, stairs, windows and chests to drag onto the map or click and then a tile, undo, clear), and the painting of the
drawings under the tokens. The drawings live in the battle (services.battle.drawing), so players see them too."""
import math
import os
from typing import List, Optional

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QImageWriter, QPainter, QPainterPath, QPen, QPixmap, QPolygonF
from PySide6.QtWidgets import QButtonGroup, QFileDialog, QPushButton, QWidget

from ....core.i18n import tr
from ....services.battle import props, rooms as R
from ....services.battle.drawing import COLORS as INK, SYMBOLS
from ... import dialogs
from ...errors import guard
from ...widgets.common import FlowLayout, button, label
from .assets import QuickBar

TOOLS = (("select", "✋", "Select and move: tokens, symbols and rooms (grab a room by its wall). R rotates a symbol, Del "
                           "erases, double-click a room's door to open or shut it"),
         ("room", "▦", "Room: drag out a box on the grid for a room - floor and walls, no doors. A room touching another "
                       "gets a door in their shared wall; overlapping rooms become one. Shift+drag erases those tiles out "
                       "of the rooms. Click a room's wall to put a door in or take it out"),
         ("draw", "✏", "Draw: rough strokes become straight walls along the grid, built like a room's (click or right-click "
                       "one for a door, window or archway in it); end near the start for a room"),
         ("free", "〰", "Free draw: kept as drawn (rivers, paths)"),
         ("erase", "🧽", "Erase: drag over drawings, symbols, rooms and doors to remove them"))
INKED = ("draw", "free")                                     # the tools the colours are for
COVER_BUTTONS = (("wall", "🧱", "New lines are walls, built like a room's (doors and windows go in them)"),
                 ("total", "▮", "New lines give full cover: they block movement, sight and light like a wall, drawn as a line "
                                "(a hedge, a palisade)"),
                 ("half", "▯", "New lines give half cover: creatures step over them (a low wall, a fence, a railing)"),
                 ("none", "─", "New lines are only drawings: no cover, nothing blocked"))


LINE_COVER_TEXT = (("wall", "Wall (like a room's)"), ("total", "Full cover: blocks like a wall"),
                   ("half", "Half cover: a low wall, a fence"), ("none", "No cover: only a drawing"))
LEAVES = {"window": "panes", "ink_window": "panes", "ink_double_door": "pair", "ink_gate": "pair",
          "ink_sliding_door": None, "ink_revolving_door": None, "ink_portcullis": None}   # an opened prop's leaf (default: one door)


def open_text(d: dict) -> str:
    """'Open it (O)' or 'Shut it (O)' for a door, window, gate... (a drawing that opens)."""
    return tr("Shut it (O)") if d.get("open") else tr("Open it (O)")


def cover_ticks(pts, closed: bool, step: float = 0.3, half: float = 0.11) -> List[tuple]:
    """A half-cover line's ticks across it, every `step` tiles (tile units): [(x1, y1, x2, y2)] (portal.js: coverTicks)."""
    out = []
    for (x1, y1), (x2, y2) in R.segments(pts, closed):
        n = math.hypot(x2 - x1, y2 - y1)
        if n < 1e-6:
            continue
        ux, uy = (x2 - x1) / n, (y2 - y1) / n
        for i in range(max(1, int(n / step))):
            t = (i + 0.5) * n / max(1, int(n / step))
            cx, cy = x1 + ux * t, y1 + uy * t
            out.append((cx - uy * half, cy + ux * half, cx + uy * half, cy - ux * half))
    return out


def _paint_line(p: QPainter, d: dict, ox: float, oy: float, z: float, selected: Optional[int]):
    """A drawn line as what it is: a plain stroke (no cover), a railing of ticks across it (half cover) or a thick
    inked barrier (full cover). A closed one gets a faint fill."""
    pts = QPolygonF([QPointF(ox + x * z, oy + y * z) for x, y in d["pts"]])
    col = QColor("#ffffff") if d["id"] == selected else QColor(d.get("color") or INK[0])
    cover = R.cover_of(d)
    width = max(1.5, d.get("width", 3) * z / 14)
    if d.get("closed") and cover == "none":
        fill = QColor(col)
        fill.setAlpha(28)
        p.setPen(Qt.NoPen)
        p.setBrush(fill)
        p.drawPolygon(pts)
        p.setBrush(Qt.NoBrush)
    if d.get("closed"):
        pts.append(pts[0])
    if cover == "total":                                     # a dark edge round a solid band of its colour
        p.setPen(QPen(QColor(20, 18, 15, 230), max(4.0, z * 0.2), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.drawPolyline(pts)
        width = max(2.0, z * 0.11)
    elif cover == "half":                                    # a rail with posts across it
        p.setPen(QPen(col, max(1.2, z * 0.035), Qt.SolidLine, Qt.FlatCap))
        for x1, y1, x2, y2 in cover_ticks(d["pts"], d.get("closed")):
            p.drawLine(QPointF(ox + x1 * z, oy + y1 * z), QPointF(ox + x2 * z, oy + y2 * z))
        width = max(1.5, z * 0.05)
    p.setPen(QPen(col, width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    p.drawPolyline(pts)


def paint_leaf(p: QPainter, sym: str, z: float):
    """An opened door's leaf swung out of the wall, a window's panes, a gate's two leaves - about the painter's origin
    (the middle of the tile, already turned), over the open picture's gap (portal.js: drawLeaf)."""
    kind = LEAVES.get(sym, "door")
    if kind is None:
        return
    p.setPen(QPen(QColor(29, 25, 21), max(1.5, z * 0.05), Qt.SolidLine, Qt.FlatCap))
    if kind == "door":
        p.drawLine(QPointF(-0.27 * z, 0), QPointF(-0.27 * z, 0.52 * z))
    elif kind == "pair":
        p.drawLine(QPointF(-0.27 * z, 0), QPointF(-0.27 * z, 0.27 * z))
        p.drawLine(QPointF(0.27 * z, 0), QPointF(0.27 * z, 0.27 * z))
    else:                                                    # casements swung in
        p.drawLine(QPointF(-0.27 * z, 0), QPointF(-0.1 * z, 0.24 * z))
        p.drawLine(QPointF(0.27 * z, 0), QPointF(0.1 * z, 0.24 * z))


def paint_drawings(p: QPainter, drawings: List[dict], ox: float, oy: float, z: float, selected: Optional[int] = None,
                   font: Optional[QFont] = None):
    """Paths and symbols, in screen space for the camera (ox, oy = tile 0,0 on screen; z = pixels per tile)."""
    for d in drawings:
        if d["type"] == "path" and R.built(d):                 # a wall: drawn like a room's (roomart.py)
            continue
        if d["type"] == "path":
            _paint_line(p, d, ox, oy, z, selected)
        elif d["type"] == "image":
            if d.get("layer", "map") == "map":
                paint_image(p, d, ox, oy, z, selected)
        elif d["type"] == "symbol" and prop_pixmap(key := props.shown(d["sym"], bool(d.get("open")))) is not None:
            n = props.span(d["sym"])                                    # (an opened door shows its open picture)
            r = QRectF(ox + d["x"] * z, oy + d["y"] * z, z * n, z * n)
            box = QRectF(-r.width() / 2, -r.height() / 2, r.width(), r.height()).toRect()
            p.save()
            p.setRenderHint(QPainter.SmoothPixmapTransform, props.smooth(key))   # pixel art: keep the pixels square
            p.translate(r.center())
            p.rotate(90 * d.get("rot", 0))
            p.drawPixmap(box, prop_pixmap(key, box.width()))
            if d.get("open") and key == "door_open":
                paint_leaf(p, d["sym"], z * n)
            p.restore()
            if d["id"] == selected:
                p.setPen(QPen(QColor("#ffffff"), 2, Qt.DashLine))
                p.drawRect(r.adjusted(1, 1, -1, -1))
        elif d["type"] == "symbol":
            glyph = SYMBOLS.get(d["sym"], ("?", ""))[0]
            r = QRectF(ox + d["x"] * z + 1, oy + d["y"] * z + 1, z - 2, z - 2)
            p.setPen(QPen(QColor("#ffffff") if d["id"] == selected else QColor(0, 0, 0, 0), 2))
            p.setBrush(QColor(20, 24, 32, 170))
            p.drawRoundedRect(r, z * 0.15, z * 0.15)
            p.setBrush(Qt.NoBrush)
            f = QFont(font) if font else QFont()
            f.setPixelSize(max(8, int(z * 0.62)))
            p.setFont(f)
            p.setPen(QColor("#f2e6c8"))
            if d.get("open"):
                p.setOpacity(0.4)
            p.save()
            p.translate(r.center())
            p.rotate(90 * d.get("rot", 0))
            p.drawText(QRectF(-z / 2, -z / 2, z, z), Qt.AlignCenter, glyph)
            p.restore()
            p.setOpacity(1.0)


# ---------------------------------------------------------------------- pictures on the map
IMAGE_FILES = ("png", "jpg", "jpeg", "webp", "bmp", "gif")
IMAGE_MAX = 1600                                             # pixels on the longest side, as kept and sent to the players
_images = {}


def image_pixmap(key: str):
    """A map picture (stored by the battle under its content key), or None while it isn't there."""
    if key not in _images:
        from ....core.runtime import rt
        path = rt().battle.image_file(key)
        pm = QPixmap(path) if path else QPixmap()
        if pm.isNull():
            return None
        _images[key] = pm
    return _images[key]


def paint_image(p: QPainter, d: dict, ox: float, oy: float, z: float, selected: Optional[int] = None):
    """One picture: turned about its middle. Hidden from the players: see-through, with an orange edge."""
    pm = image_pixmap(d["img"])
    w, h = d["w"] * z, d["h"] * z
    p.save()
    p.translate(ox + (d["x"] + d["w"] / 2) * z, oy + (d["y"] + d["h"] / 2) * z)
    p.rotate(float(d.get("rot") or 0))
    box = QRectF(-w / 2, -h / 2, w, h)
    if d.get("hidden"):
        p.setOpacity(0.5)
    if pm is not None:
        p.setRenderHint(QPainter.SmoothPixmapTransform, True)
        p.drawPixmap(box, pm, QRectF(pm.rect()))
    else:
        p.fillRect(box, QColor(60, 66, 80, 120))
    p.setOpacity(1.0)
    if d.get("hidden"):
        p.setPen(QPen(QColor("#fb923c"), 2, Qt.DashLine))
        p.drawRect(box)
    if d["id"] == selected:
        p.setPen(QPen(QColor("#ffffff"), 2, Qt.DashLine))
        p.drawRect(box.adjusted(1, 1, -1, -1))
        if d.get("locked"):
            p.drawText(box.adjusted(4, 2, -4, -2), Qt.AlignTop | Qt.AlignRight, "🔒")
    p.restore()


def paint_images(p: QPainter, drawings: List[dict], layer: str, ox: float, oy: float, z: float, selected: Optional[int] = None) -> int:
    """The pictures of one layer ('ground' under the grid, 'top' over the tokens), in their order. Returns how many."""
    n = 0
    for d in drawings:
        if d["type"] == "image" and d.get("layer", "map") == layer:
            paint_image(p, d, ox, oy, z, selected)
            n += 1
    return n


def encode_image(path: str):
    """A picture file made ready for the map: at most IMAGE_MAX pixels across, WebP (PNG or JPEG where WebP can't be
    written). Returns (bytes, extension, width, height); raises ValueError when it isn't a picture."""
    img = QImage(path)
    if img.isNull():
        raise ValueError(tr("{0} isn't a picture this can open.", os.path.basename(path)))
    if max(img.width(), img.height()) > IMAGE_MAX:
        img = img.scaled(IMAGE_MAX, IMAGE_MAX, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    formats = [bytes(f).decode().lower() for f in QImageWriter.supportedImageFormats()]
    for fmt, ext, quality in (("webp", "webp", 82), ("png", "png", -1) if img.hasAlphaChannel() else ("jpg", "jpg", 85)):
        if fmt not in formats and not (fmt == "jpg" and "jpeg" in formats):
            continue
        data = QByteArray()
        buf = QBuffer(data)
        buf.open(QIODevice.WriteOnly)
        if img.save(buf, fmt.upper(), quality):
            return bytes(data), ext, img.width(), img.height()
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    return bytes(data), "png", img.width(), img.height()


_props = {}
_scaled = {}


def prop_pixmap(key: str, size: Optional[int] = None):
    """A prop's (or a built-in symbol's) picture (the map props module), or None when it has none. With `size`, a
    hand-drawn one comes ready scaled to size x size (smoothly: thin ink lines don't break up when drawn small)."""
    if key not in _props:
        path = props.path(key)
        _props[key] = QPixmap(path) if path else None
    pm = _props[key]
    if pm is None or not size or size <= 0 or not props.smooth(key):
        return pm
    if (key, size) not in _scaled:
        if len(_scaled) > 600:                                  # zooming makes new sizes: forget the old ones
            _scaled.clear()
        _scaled[(key, size)] = pm.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    return _scaled[(key, size)]


# ------------------------------------------------------------------ items on the ground
SACK = "dungeon_sack"                                       # (the old look of every item on the ground: a loot pile)
_items = {}


def item_pixmap(key: str):
    """An item sprite (services/battle/itemsprites.py: 32 px pixel art), or None when it has none."""
    if key not in _items:
        from ....services.battle import itemsprites
        path = itemsprites.path(key)
        pm = QPixmap(path) if path else QPixmap()
        _items[key] = None if pm.isNull() else pm
    return _items[key]


def item_sprite(name: str):
    """The sprite of an item by its name (the sack when nothing fits), or None."""
    from ....services.battle.itemsprites import sprite_for
    return item_pixmap(sprite_for(name))


def paint_item(p: QPainter, pm: QPixmap, cx: float, cy: float, s: float, rot: float = 0.0, shadow: float = 1.0, alpha: float = 1.0):
    """One item sprite centred on (cx, cy) pixels, s across, turned `rot` degrees, over a soft shadow on the floor
    (`shadow`: how strongly; 0 none) - the pixels kept square unless it is turned."""
    if shadow > 0:
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, int(80 * shadow * alpha)))
        p.drawEllipse(QPointF(cx, cy + s * .3), s * .34, s * .12)
        p.setBrush(Qt.NoBrush)
    p.save()
    p.setOpacity(p.opacity() * alpha)
    p.setRenderHint(QPainter.SmoothPixmapTransform, bool(rot))
    p.translate(cx, cy)
    if rot:
        p.rotate(rot)
    p.drawPixmap(QRectF(-s / 2, -s / 2, s, s), pm, QRectF(pm.rect()))
    p.restore()


def ground_spots(ground: List[dict]) -> List[tuple]:
    """[(stack, cx, cy)] in tile units: a stack dropped on a point lies there; others in the middle of their tile, several
    on one tile spread around it."""
    by_tile = {}
    out = []
    for g in ground:
        at = g.get("at")
        if at and int(at[0]) == g["x"] and int(at[1]) == g["y"]:
            out.append((g, at[0], at[1]))
        else:
            by_tile.setdefault((g["x"], g["y"]), []).append(g)
    for (x, y), stacks in by_tile.items():
        n = len(stacks)
        for i, g in enumerate(stacks):
            a = 2 * math.pi * i / n - math.pi / 2
            r = 0 if n == 1 else 0.22
            out.append((g, x + 0.5 + r * math.cos(a), y + 0.5 + r * math.sin(a)))
    return out


def ground_hit(ground: List[dict], x: float, y: float) -> Optional[dict]:
    """The stack under a point (tile units), the last dropped first."""
    for g, cx, cy in reversed(ground_spots(ground)):
        if abs(cx - x) <= 0.3 and abs(cy - y) <= 0.3:
            return g
    return None


def paint_ground(p: QPainter, ground: List[dict], ox: float, oy: float, z: float, picked: Optional[int] = None):
    """The items lying on the map (under the tokens): each its own sprite (a sword, a potion, a ring...); a stack of
    several shows a second one behind it."""
    for g, cx, cy in ground_spots(ground):
        s = z * .7
        r = QRectF(ox + cx * z - s / 2, oy + cy * z - s / 2, s, s)
        pm = item_sprite(g["name"]) or prop_pixmap(SACK)
        if pm is not None:
            if g["qty"] > 1:                                   # a pile: another one peeking out behind
                paint_item(p, pm, r.center().x() + s * .16, r.center().y() - s * .12, s * .9, shadow=0, alpha=.8)
            paint_item(p, pm, r.center().x(), r.center().y(), s)
        else:
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(150, 110, 60))
            p.drawEllipse(r.adjusted(s * .25, s * .25, -s * .25, -s * .25))
            p.setBrush(Qt.NoBrush)
        if g["id"] == picked:
            p.setPen(QPen(QColor("#ffffff"), 1.5, Qt.DashLine))
            p.drawEllipse(r.adjusted(s * .12, s * .12, -s * .12, -s * .12))


def paint_item_label(p: QPainter, g: dict, sx: float, sy: float, font: QFont):
    """An item's name over its sack, the way games show loot on the floor: the amount in brackets above the name."""
    f = QFont(font)
    f.setPixelSize(11)
    f.setBold(True)
    p.setFont(f)
    fm = p.fontMetrics()
    lines = ([(f"({g['qty']}×)", QColor("#7fd8ff"))] if g["qty"] > 1 else []) + [(tr(g["name"]), QColor("#f2f2f2"))]
    w = max(fm.horizontalAdvance(t) for t, _c in lines) + 10
    h = fm.height() * len(lines) + 4
    box = QRectF(sx - w / 2, sy - h - 2, w, h)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(0, 0, 0, 150))
    p.drawRoundedRect(box, 3, 3)
    p.setBrush(Qt.NoBrush)
    for i, (text, col) in enumerate(lines):
        line = QRectF(box.left(), box.top() + 2 + i * fm.height(), w, fm.height())
        p.setPen(QColor(0, 0, 0, 200))
        p.drawText(line.translated(1, 1), Qt.AlignCenter, text)
        p.setPen(col)
        p.drawText(line, Qt.AlignCenter, text)


def paint_stroke(p: QPainter, pts: List[tuple], ox: float, oy: float, z: float, color: str):
    if len(pts) < 2:
        return
    path = QPainterPath(QPointF(ox + pts[0][0] * z, oy + pts[0][1] * z))
    for x, y in pts[1:]:
        path.lineTo(QPointF(ox + x * z, oy + y * z))
    p.setPen(QPen(QColor(color), 2, Qt.DashLine, Qt.RoundCap, Qt.RoundJoin))
    p.drawPath(path)


class DrawBar(QWidget):
    """The tools above the map. `canvas.tool` is 'select' | 'room' | 'draw' | 'free' | 'erase' | 'place'. The colours
    show only while drawing, the room tool's door switch only while it is picked; `on_fold` folds the bar away."""

    def __init__(self, canvas, on_fold=None):
        super().__init__()
        self.canvas = canvas
        canvas.tool, canvas.ink, canvas.place = "select", INK[0], None
        flow = FlowLayout(self, spacing=3)
        self.tools = QButtonGroup(self)
        self.tool_btns = {}
        for key, glyph, tip in TOOLS:
            b = QPushButton(glyph)
            b.setCheckable(True)
            b.setFixedSize(30, 26)
            b.setToolTip(tr(tip))
            b.setChecked(key == "select")
            b.clicked.connect(lambda _c=False, k=key: self.set_tool(k))
            self.tools.addButton(b)
            self.tool_btns[key] = b
            flow.addWidget(b)
        self.inks = QButtonGroup(self)
        for color in INK:
            b = QPushButton("")
            b.setCheckable(True)
            b.setFixedSize(20, 20)
            b.setToolTip(tr("Ink colour for drawing"))
            b.setStyleSheet(f"QPushButton {{ background: {color}; border: 1px solid #000; border-radius: 3px; }}"
                            "QPushButton:checked { border: 2px solid #ffffff; }")
            b.setChecked(color == INK[0])
            b.clicked.connect(lambda _c=False, c=color: setattr(canvas, "ink", c))
            self.inks.addButton(b)
            flow.addWidget(b)
        self.cover = {"draw": "wall", "free": "none"}        # what a new line is, for each drawing tool
        self.covers = QButtonGroup(self)
        self.cover_btns = {}
        for key, glyph, tip in COVER_BUTTONS:
            b = QPushButton(glyph)
            b.setCheckable(True)
            b.setFixedSize(30, 26)
            b.setToolTip(tr(tip))
            b.clicked.connect(lambda _c=False, k=key: self.cover.__setitem__(self.canvas.tool, k))
            self.covers.addButton(b)
            self.cover_btns[key] = b
            flow.addWidget(b)
        self.doors = QPushButton("🚪")                       # the room tool's switch: doors where rooms touch
        self.doors.setCheckable(True)
        self.doors.setChecked(True)
        self.doors.setFixedSize(30, 26)
        self.doors.setProperty("kind", "flat")
        self.doors.setToolTip(tr("Doors where rooms touch: a new room touching another gets a door in their shared wall"))
        flow.addWidget(self.doors)
        flow.addWidget(label(" │ ", role="dim"))
        self.quick = QuickBar()                              # doors, stairs, windows, chests...: the ones used most
        flow.addWidget(self.quick)
        flow.addWidget(label(" │ ", role="dim"))
        flow.addWidget(button("🖼", self._picture, kind="flat", width=30,
                              tip=tr("Put a picture on the map (or drag picture files onto it). Drag it around; while holding it, "
                                     "scroll to turn it and Shift+scroll to size it. Right-click it for its layer, lock, hide or erase.")))
        flow.addWidget(button("↶", lambda: guard(canvas.rt.battle.undo_drawing), kind="flat", width=30,
                              tip=tr("Take back the last drawing")))
        flow.addWidget(button("🗑", self._clear, kind="flat", width=30, tip=tr("Clear map: erase every drawing, room, symbol and picture")))
        if on_fold:
            flow.addWidget(button("︽", on_fold, kind="flat", width=30, tip=tr("Fold the paint tools away (🎨 above brings them back)")))
        self._show_extras()

    def _show_extras(self):
        tool = self.canvas.tool
        inked, room = tool in INKED, tool == "room"
        for b in self.inks.buttons():
            b.setVisible(inked)
        for key, b in self.cover_btns.items():
            b.setVisible(inked and (key != "wall" or tool == "draw"))   # free strokes can't be a room's kind of wall
            b.setChecked(inked and self.cover.get(tool) == key)
        self.doors.setVisible(room)

    def room_doors(self) -> bool:
        """Whether a new room gets doors where it touches others."""
        return self.doors.isChecked()

    def line_cover(self) -> Optional[str]:
        """What the drawing tool's next line is (rooms.LINE_COVER), or None for any other tool."""
        return self.cover.get(self.canvas.tool)

    def _picture(self):
        files, _f = QFileDialog.getOpenFileNames(self, tr("Put a picture on the map"), "",
                                                 tr("Pictures") + " (" + " ".join(f"*.{x}" for x in IMAGE_FILES) + ")")
        if files:
            w, h = self.canvas.map_size()
            self.canvas.add_pictures(files, (w / 2, h / 2))

    def set_tool(self, key: str):
        self.canvas.tool = key
        self.canvas.room_box = None
        self.arm(None, keep_tool=True)
        self.canvas.setCursor(Qt.CrossCursor if key in ("draw", "free", "erase", "room") else Qt.ArrowCursor)
        self.tool_btns[key].setChecked(True)
        self._show_extras()

    def select(self):
        """Back to ✋ select (leaving edit mode): no tool left armed."""
        self.set_tool("select")

    def arm(self, symbol: Optional[str], keep_tool: bool = False):
        """Click-to-place: the next click on the map puts this symbol there."""
        symbol = symbol or None
        self.quick.show_armed(symbol)
        self.canvas.place = symbol
        if symbol:
            self.canvas.tool = "place"
            self.canvas.setCursor(Qt.PointingHandCursor)
        elif not keep_tool and self.canvas.tool == "place":
            self.canvas.tool = "select"
            self.tool_btns["select"].setChecked(True)
        self._show_extras()

    def _clear(self):
        if dialogs.confirm(self, tr("Erase every drawing, room, symbol and picture on the map? Players see it at once.")):
            guard(self.canvas.rt.battle.clear_drawings)


def tile_point(canvas, pos) -> tuple:
    """Screen position -> tile coordinates as floats."""
    z = canvas.cam["z"]
    return ((pos.x() - canvas.cam["x"]) / z, (pos.y() - canvas.cam["y"]) / z)


def free_point(pt: tuple, modifiers) -> tuple:
    """Where a small thing let go at `pt` (tile units) lies: right there, or with Shift on the nearest tile corner, edge
    middle or tile middle."""
    if modifiers & Qt.ShiftModifier:
        return round(pt[0] * 2) / 2, round(pt[1] * 2) / 2
    return round(pt[0], 3), round(pt[1], 3)


def far_enough(a: tuple, b: tuple, step: float = 0.12) -> bool:
    return math.hypot(a[0] - b[0], a[1] - b[1]) >= step

