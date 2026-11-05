"""The rooms' look on the battle map: the old-school hand-drawn dungeon - a pale floor with an inked grid, little
cracks and scratches, a grey shadow inside the walls, thick black walls, stippled rock around them with a stone here
and there, and doors as small boxes standing in the wall. Everything is drawn from the rooms' plan (services.battle.
rooms), so any shape of joined rooms looks right; the scatter comes from a hash of the tile, so it stays put between
frames and matches the players' portal, which draws the same way (portal.js: drawRooms).

    paint_rooms(p, drawings, ox, oy, z, picked)     # under the drawings and the tokens (walls drawn with the draw tool too)
    paint_room_ghost(p, drawings, box, ox, oy, z, font)   # the box being dragged out with the room tool
    paint_room_carve(p, drawings, box, ox, oy, z, font)   # ... with Shift: the tiles it erases out of the rooms

The rooms are drawn once for a zoom into a picture (LAYER_MAX pixels across at most); panning only moves it.
"""
import math
from functools import lru_cache
from typing import List, Optional

from PySide6.QtCore import QLineF, QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QPainter, QPainterPath, QPainterPathStroker, QPen, QPixmap, QPolygonF

from ....services.battle import rooms as R

INK = QColor(29, 25, 21)
PAPER = QColor(242, 237, 225)
FLOOR = QColor(246, 242, 233)
WALL = 0.16                                                 # tiles: the wall's ink
SHADOW = (0.24, 0.12)                                       # tiles: the shadow inside a wall facing down/right, up/left
LAYER_MAX = 4096
_layers = {}


def rand(x: int, y: int, k: int) -> float:
    """A number in [0, 1) fixed for (x, y, k): the same scatter every frame (portal.js: rand)."""
    h = (x * 374761393 + y * 668265263 + k * 2147483647) & 0xffffffff
    h = ((h ^ (h >> 13)) * 1274126177) & 0xffffffff
    return ((h ^ (h >> 16)) & 0xffffff) / 0x1000000


def _key(drawings) -> tuple:
    rooms = tuple((d["type"], d["id"], d["x"], d["y"], d.get("w"), d.get("h"), d.get("v"), bool(d.get("open")), d.get("kind"), R.cut_of(d))
                  for d in drawings or [] if d.get("type") in ("room", "door"))
    return rooms + tuple(("path", d["id"], tuple(map(tuple, d["pts"])), bool(d.get("closed"))) for d in drawings or [] if R.built(d))


@lru_cache(maxsize=8)
def _art(key: tuple) -> Optional[dict]:
    """The rooms as paths in tile units, built once per set of rooms, doors and drawn walls."""
    drawings = [{"type": "path", "id": k[1], "pts": [list(p) for p in k[2]], "closed": k[3]} if k[0] == "path" else
                {"type": k[0], "id": k[1], "x": k[2], "y": k[3], "w": k[4], "h": k[5], "v": k[6], "open": k[7], "kind": k[8],
                 "cut": [list(c) for c in k[9]]} for k in key]
    plan = R.plan(drawings)
    if not plan["floor"] and not plan["walls"] and not plan["slants"]:
        return None
    floor = {(x, y) for x, y in plan["floor"]}
    walls = {(x, y, bool(v)): s for x, y, v, s in plan["walls"]}
    out = {"floor": QPainterPath(), "shadow": QPainterPath(), "soft": QPainterPath(), "grid": QPainterPath(), "marks": QPainterPath(),
           "walls": QPainterPath(), "stones": QPainterPath(), "dots": ([], [], []), "doors": plan["doors"]}
    for x, y in floor:
        out["floor"].addRect(QRectF(x, y, 1, 1))
    for x1, y1, x2, y2 in plan["runs"] + plan["slants"]:
        out["walls"].moveTo(x1, y1)
        out["walls"].lineTo(x2, y2)
    stroker = QPainterPathStroker()
    stroker.setCapStyle(Qt.RoundCap)
    stroker.setWidth(0.9)
    out["halo"] = stroker.createStroke(out["walls"])         # the paper the rooms are drawn on
    stroker.setWidth(1.6)
    out["haze"] = stroker.createStroke(out["walls"])
    for (x, y, v), side in walls.items():
        for s in ((1, -1) if side == 0 else () if side == 2 else (side,)):   # the shadow on the floor side(s); deeper under the top and left walls
            width = SHADOW[0] if s == 1 else SHADOW[1]
            for w, path in ((width, "shadow"), (width * 1.9, "soft")):
                if v:
                    out[path].addRect(QRectF(x, y, w, 1) if s == 1 else QRectF(x - w, y, w, 1))
                else:
                    out[path].addRect(QRectF(x, y, 1, w) if s == 1 else QRectF(x, y - w, 1, w))
        if side == 0:
            continue
        k = x * 2 + v
        for out_side in ((1, -1) if side == 2 else (side,)):  # a wall standing on its own: rock on both sides
            nx, ny = (-out_side, 0) if v else (0, -out_side)  # outwards, away from the floor
            q = 0 if out_side == side else 500                # the other side scatters differently
            for i in range(2):                               # the paper's ragged edge
                a, r, dist = rand(k, y, q + 50 + i), 0.3 + 0.25 * rand(k, y, q + 60 + i), 0.25 + 0.2 * rand(k, y, q + 70 + i)
                out["halo"].addEllipse(QPointF(x + dist * nx, y + a) if v else QPointF(x + a, y + dist * ny), r, r)
            for i in range(22 if side != 2 else 12):         # stipple: thick by the wall, thinning out
                a, b = rand(k, y, q + i * 3 + 1), rand(k, y, q + i * 3 + 2)
                along, off = -0.25 + 1.5 * a, 0.1 + (0.7 if side != 2 else 0.4) * b * b
                out["dots"][int(rand(k, y, q + i * 3 + 3) * 3)].append(QPointF(x + off * nx, y + along) if v else QPointF(x + along, y + off * ny))
            if rand(k, y, q + 99) < 0.09:                    # a loose stone
                along, dist, r = 0.2 + 0.6 * rand(k, y, q + 101), 0.45 + 0.3 * rand(k, y, q + 102), 0.07 + 0.06 * rand(k, y, q + 103)
                cx, cy = (x + dist * nx, y + along) if v else (x + along, y + dist * ny)
                pts = [QPointF(cx + r * (0.7 + 0.5 * rand(k, y, q + 110 + j)) * math.cos(j * 1.2566 + 0.4),
                               cy + r * (0.7 + 0.5 * rand(k, y, q + 120 + j)) * math.sin(j * 1.2566 + 0.4)) for j in range(5)]
                out["stones"].addPolygon(QPolygonF(pts + pts[:1]))
    for x, y in floor:                                       # the grid between floor tiles, a little wobbly
        for e, nb in (((x + 1, y, True), (x + 1, y)), ((x, y + 1, False), (x, y + 1))):
            if nb not in floor or e in walls:
                continue
            j = [(rand(x, y, 200 + i + (0 if e[2] else 10)) - 0.5) * 0.05 for i in range(3)]
            if e[2]:
                out["grid"].moveTo(x + 1 + j[0], y)
                out["grid"].lineTo(x + 1 + j[1], y + 0.5)
                out["grid"].lineTo(x + 1 + j[2], y + 1)
            else:
                out["grid"].moveTo(x, y + 1 + j[0])
                out["grid"].lineTo(x + 0.5, y + 1 + j[1])
                out["grid"].lineTo(x + 1, y + 1 + j[2])
        for i in range(int(rand(x, y, 300) * 4)):            # scratches
            cx, cy = x + 0.1 + 0.8 * rand(x, y, 310 + i), y + 0.1 + 0.8 * rand(x, y, 320 + i)
            a, n = rand(x, y, 330 + i) * math.pi, 0.03 + 0.06 * rand(x, y, 340 + i)
            out["marks"].moveTo(cx - n * math.cos(a), cy - n * math.sin(a))
            out["marks"].lineTo(cx + n * math.cos(a), cy + n * math.sin(a))
        if rand(x, y, 400) < 0.3:                            # a crack
            cx, cy = x + 0.2 + 0.6 * rand(x, y, 401), y + 0.2 + 0.6 * rand(x, y, 402)
            a = rand(x, y, 403) * math.tau
            out["marks"].moveTo(cx, cy)
            for i in range(3):
                a += (rand(x, y, 410 + i) - 0.5) * 1.6
                step = 0.07 + 0.08 * rand(x, y, 420 + i)
                cx, cy = cx + step * math.cos(a), cy + step * math.sin(a)
                out["marks"].lineTo(cx, cy)
    for path in ("shadow", "soft", "floor", "halo", "haze"):
        out[path].setFillRule(Qt.WindingFill)
        out[path] = out[path].simplified()                   # one shape: overlaps don't darken twice
    out["shadow"] = out["shadow"].intersected(out["floor"])
    out["soft"] = out["soft"].intersected(out["floor"])
    r = out["haze"].boundingRect().united(out["halo"].boundingRect())
    out["bounds"] = (math.floor(r.left()), math.floor(r.top()), math.ceil(r.right()), math.ceil(r.bottom()))
    return out


def _pen(color: QColor, width: float, cap=Qt.RoundCap, alpha: Optional[int] = None) -> QPen:
    c = QColor(color)
    if alpha is not None:
        c.setAlpha(alpha)
    return QPen(c, width, Qt.SolidLine, cap, Qt.MiterJoin if cap == Qt.SquareCap else Qt.RoundJoin)


def paint_rooms(p: QPainter, drawings: List[dict], ox: float, oy: float, z: float, picked: Optional[int] = None,
                dpr: float = 1.0):
    """The rooms (under the drawings and the tokens), from a picture of them made once for the zoom."""
    key = _key(drawings)
    art = _art(key)
    if art is None:
        return
    x0, y0, x1, y1 = art["bounds"]
    k = round(min(z * dpr, LAYER_MAX / max(1, x1 - x0, y1 - y0)), 3)
    img = _layers.get((key, k))
    if img is None:
        if len(_layers) > 3:
            _layers.clear()
        img = QImage(max(1, int((x1 - x0) * k)), max(1, int((y1 - y0) * k)), QImage.Format_ARGB32_Premultiplied)
        img.fill(Qt.transparent)
        q = QPainter(img)
        q.setRenderHint(QPainter.Antialiasing)
        q.scale(k, k)
        q.translate(-x0, -y0)
        _paint_art(q, art)
        q.end()
        _layers[(key, k)] = img
    p.save()
    p.setRenderHint(QPainter.SmoothPixmapTransform, True)
    p.drawImage(QRectF(ox + x0 * z, oy + y0 * z, (x1 - x0) * z, (y1 - y0) * z), img)
    door = next((d for d in art["doors"] if d["id"] == picked), None) if picked else None
    if door:
        p.translate(ox, oy)
        p.scale(z, z)
        _door_box(p, door)
    p.restore()
    sel = next((d for d in drawings if d["id"] == picked and d.get("type") in ("room", "path")), None) if picked else None
    if sel and sel["type"] == "room":
        p.setPen(QPen(QColor("#ffffff"), 2, Qt.DashLine))
        p.setBrush(Qt.NoBrush)
        p.drawRect(QRectF(ox + sel["x"] * z, oy + sel["y"] * z, sel["w"] * z, sel["h"] * z).adjusted(-3, -3, 3, 3))
    elif sel and R.built(sel):                                # a drawn wall: dashed along it
        p.setPen(QPen(QColor("#ffffff"), 2, Qt.DashLine))
        p.setBrush(Qt.NoBrush)
        for (x1, y1), (x2, y2) in R.segments(sel["pts"], sel.get("closed")):
            p.drawLine(QPointF(ox + x1 * z, oy + y1 * z), QPointF(ox + x2 * z, oy + y2 * z))


def _paint_art(p: QPainter, art: dict):
    """The rooms in tile units: the paper and its stipple, the floor, its shadow, grid and cracks, the walls, the doors."""
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(PAPER.red(), PAPER.green(), PAPER.blue(), 40))   # the paper, fading out at its edge
    p.drawPath(art["haze"])
    p.setBrush(PAPER)
    p.drawPath(art["halo"])
    p.setBrush(Qt.NoBrush)
    for i, dots in enumerate(art["dots"]):
        if dots:
            p.setPen(_pen(INK, (0.025, 0.04, 0.06)[i], alpha=(230, 210, 190)[i]))
            p.drawPoints(QPolygonF(dots))
    p.setPen(_pen(INK, 0.03))
    p.setBrush(PAPER)
    p.drawPath(art["stones"])
    p.setPen(Qt.NoPen)
    p.setBrush(FLOOR)
    p.drawPath(art["floor"])
    p.setBrush(QColor(0, 0, 0, 20))
    p.drawPath(art["soft"])
    p.setBrush(QColor(0, 0, 0, 40))
    p.drawPath(art["shadow"])
    p.setBrush(Qt.NoBrush)
    p.setPen(_pen(INK, 0.028, alpha=170))
    p.drawPath(art["grid"])
    p.setPen(_pen(INK, 0.02, alpha=130))
    p.drawPath(art["marks"])
    p.setPen(_pen(INK, WALL, Qt.SquareCap))
    p.drawPath(art["walls"])
    for d in art["doors"]:
        _paint_door(p, d)


def _door_box(p: Optional[QPainter], d: dict, color: str = "#ffffff") -> QRectF:
    """Where something in a wall stands (tile units). With a painter: its outline (selected, or previewed)."""
    x, y, v = d["x"], d["y"], d["v"]
    box = QRectF(x - 0.2, y + 0.14, 0.4, 0.72) if v else QRectF(x + 0.14, y - 0.2, 0.72, 0.4)
    if p is not None:
        p.setPen(QPen(QColor(color), 0.05, Qt.DashLine))
        p.setBrush(Qt.NoBrush)
        p.drawRect(box.adjusted(-0.08, -0.08, 0.08, 0.08))
    return box


def _letter_s(p: QPainter, s: float = 0.1):
    """The old-school mark of a secret door: an S, about the painter's origin."""
    path = QPainterPath(QPointF(s, -s * 1.3))
    path.cubicTo(s * 0.2, -s * 2, -s * 1.2, -s * 1.5, -s * 0.9, -s * 0.5)
    path.cubicTo(-s * 0.6, s * 0.2, s * 0.9, -s * 0.1, s, s * 0.7)
    path.cubicTo(s * 1.1, s * 1.7, -s * 0.5, s * 2, -s, s * 1.3)
    p.drawPath(path)


def _paint_door(p: QPainter, d: dict):
    """What stands in a wall (portal.js: roomDoor draws the same): in the painter's tile units, about the middle of its
    edge, turned so the wall runs along x. A shut door is a box across the wall (two for a double door, a bolt on a
    locked one, only an S beside the wall for a secret one); an open one a gap with the door swung on its hinge; a
    window a framed pane (open: its casements swung in), a portcullis a row of bars (raised: two posts, the bars
    faint), an archway a gap between two posts."""
    kind, x, y, v = d.get("kind") or "door", d["x"], d["y"], d["v"]
    ink, fine = _pen(INK, 0.05, Qt.SquareCap), _pen(INK, 0.025, Qt.SquareCap)
    p.save()
    p.translate(x, y + 0.5) if v else p.translate(x + 0.5, y)
    if v:
        p.rotate(90)

    def gap(half: float):
        p.setPen(Qt.NoPen)
        p.setBrush(FLOOR)
        p.drawRect(QRectF(-half, -0.11, 2 * half, 0.22))

    def box(x0: float, w: float, h: float = 0.3):
        p.setPen(ink)
        p.setBrush(FLOOR)
        p.drawRect(QRectF(x0, -h / 2, w, h))

    if kind in ("door", "double", "locked", "secret") and d.get("open"):
        gap(0.36)
        p.setPen(_pen(INK, 0.06, Qt.SquareCap))
        if kind == "double":
            p.drawLine(QLineF(-0.36, 0, -0.36, 0.32))
            p.drawLine(QLineF(0.36, 0, 0.36, 0.32))
        else:
            p.drawLine(QLineF(-0.36, 0, -0.36, 0.6))
    elif kind == "double":
        box(-0.32, 0.31, 0.28)
        box(0.01, 0.31, 0.28)
    elif kind in ("door", "locked"):
        box(-0.3, 0.6)
        if kind == "locked":                                 # the bolt
            p.setPen(Qt.NoPen)
            p.setBrush(INK)
            p.drawRect(QRectF(-0.06, -0.06, 0.12, 0.12))
    elif kind == "window" and d.get("open"):                 # its two casements swung in, the frame's ends left
        gap(0.36)
        p.setPen(fine)
        p.drawLine(QLineF(-0.36, -0.07, -0.36, 0.07))
        p.drawLine(QLineF(0.36, -0.07, 0.36, 0.07))
        p.setPen(_pen(INK, 0.04, Qt.SquareCap))
        p.drawLine(QLineF(-0.36, 0, -0.2, 0.3))
        p.drawLine(QLineF(0.36, 0, 0.2, 0.3))
    elif kind == "window":
        gap(0.36)
        p.setPen(fine)
        p.setBrush(FLOOR)
        p.drawRect(QRectF(-0.36, -0.07, 0.72, 0.14))
        p.drawLine(QLineF(-0.36, 0, 0.36, 0))
    elif kind == "portcullis" and d.get("open"):             # raised: the gap between its posts, its bars faint overhead
        gap(0.4)
        p.setPen(Qt.NoPen)
        p.setBrush(INK)
        p.drawRect(QRectF(-0.47, -0.09, 0.09, 0.18))
        p.drawRect(QRectF(0.38, -0.09, 0.09, 0.18))
        p.setBrush(QColor(INK.red(), INK.green(), INK.blue(), 70))
        for i in range(5):
            p.drawRect(QRectF(-0.36 + i * 0.18 - 0.03, -0.03, 0.06, 0.06))
    elif kind == "portcullis":
        gap(0.4)
        p.setPen(fine)
        p.drawLine(QLineF(-0.4, 0, 0.4, 0))
        p.setPen(Qt.NoPen)
        p.setBrush(INK)
        for i in range(5):
            p.drawRect(QRectF(-0.36 + i * 0.18 - 0.035, -0.035, 0.07, 0.07))
    elif kind == "archway":
        gap(0.4)
        p.setPen(Qt.NoPen)
        p.setBrush(INK)
        p.drawRect(QRectF(-0.5, -0.13, 0.13, 0.26))
        p.drawRect(QRectF(0.37, -0.13, 0.13, 0.26))
    if kind == "secret":
        p.translate(0, 0.33)
        if v:
            p.rotate(-90)
        p.setPen(_pen(INK, 0.04, alpha=110 if d.get("open") else None))
        p.setBrush(Qt.NoBrush)
        _letter_s(p)
    p.setBrush(Qt.NoBrush)
    p.restore()


def paint_wall_preview(p: QPainter, d: dict, ox: float, oy: float, z: float):
    """A door, window... not there yet (hovered in the wall's menu): over the room, outlined."""
    p.save()
    p.translate(ox, oy)
    p.scale(z, z)
    p.save()                                                 # what stands there now is covered, the wall drawn again
    p.translate(d["x"], d["y"] + 0.5) if d["v"] else p.translate(d["x"] + 0.5, d["y"])
    if d["v"]:
        p.rotate(90)
    p.fillRect(QRectF(-0.52, -0.2, 1.04, 0.4), FLOOR)
    p.setPen(_pen(INK, WALL, Qt.FlatCap))
    p.drawLine(QLineF(-0.52, 0, 0.52, 0))
    p.restore()
    _paint_door(p, d)
    _door_box(p, d, "#7c8cff")
    p.restore()


_icons = {}


def wall_icon(kind: str, size: int = 22) -> QPixmap:
    """A menu icon: a bit of wall with `kind` in it, drawn like the map draws it."""
    if (kind, size) not in _icons:
        pm = QPixmap(size, size)
        pm.fill(PAPER)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.translate(size / 2, size / 2)
        p.scale(size * 1.15, size * 1.15)
        p.setPen(_pen(INK, WALL, Qt.FlatCap))
        p.drawLine(QLineF(-0.55, 0, 0.55, 0))
        _paint_door(p, {"x": -0.5, "y": 0, "v": False, "kind": kind})
        p.end()
        _icons[kind, size] = pm
    return _icons[kind, size]


def paint_room_ghost(p: QPainter, drawings: List[dict], box: tuple, ox: float, oy: float, z: float, font: QFont):
    """The room tool's box while dragging: the rooms as they'd be with it, and its size."""
    x0, y0, x1, y1 = box
    xa, xb, ya, yb = min(x0, x1), max(x0, x1), min(y0, y1), max(y0, y1)
    ghost = {"type": "room", "id": -1, "x": xa, "y": ya, "w": xb - xa + 1, "h": yb - ya + 1}
    p.setOpacity(0.75)
    paint_rooms(p, list(drawings) + [ghost], ox, oy, z)
    p.setOpacity(1.0)
    r = QRectF(ox + xa * z, oy + ya * z, ghost["w"] * z, ghost["h"] * z)
    p.setPen(QPen(QColor(124, 140, 255, 230), 2, Qt.DashLine))
    p.setBrush(Qt.NoBrush)
    p.drawRect(r)
    f = QFont(font)
    f.setBold(True)
    f.setPixelSize(12)
    p.setFont(f)
    tag = QRectF(r.center().x() - 30, r.top() - 22, 60, 18)
    p.fillRect(tag, QColor(15, 17, 21, 210))
    p.setPen(QColor("#e6e9ef"))
    p.drawText(tag, Qt.AlignCenter, f"{ghost['w']} × {ghost['h']}")


def paint_room_carve(p: QPainter, drawings: List[dict], box: tuple, ox: float, oy: float, z: float, font: QFont):
    """The room tool's box while dragging with Shift: the rooms with those tiles erased out of them."""
    x0, y0, x1, y1 = box
    xa, xb, ya, yb = min(x0, x1), max(x0, x1), min(y0, y1), max(y0, y1)
    p.setOpacity(0.75)
    paint_rooms(p, R.carve(drawings, xa, ya, xb, yb), ox, oy, z)
    p.setOpacity(1.0)
    r = QRectF(ox + xa * z, oy + ya * z, (xb - xa + 1) * z, (yb - ya + 1) * z)
    p.setPen(QPen(QColor(248, 113, 113, 230), 2, Qt.DashLine))
    p.setBrush(QColor(248, 113, 113, 30))
    p.drawRect(r)
    p.setBrush(Qt.NoBrush)
    f = QFont(font)
    f.setBold(True)
    f.setPixelSize(12)
    p.setFont(f)
    tag = QRectF(r.center().x() - 50, r.top() - 22, 100, 18)
    p.fillRect(tag, QColor(15, 17, 21, 210))
    p.setPen(QColor("#f87171"))
    p.drawText(tag, Qt.AlignCenter, f"− {xb - xa + 1} × {yb - ya + 1}")
