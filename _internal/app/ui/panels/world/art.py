"""How the world map's marks, names, party and pings look in the editor (the portal draws the same in world.js).

Everything here paints in map pixels: the caller has already scaled the painter. `k` is map pixels per screen pixel,
for what keeps its size on screen whatever the zoom (the party's banner, the route's numbers, pings, selection)."""
import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QImage, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, QPolygonF, QTransform

from ....core.i18n import tr
from ....services.world import ART, TERRAIN, stamps
from ....services.world.render import COLOUR_LOOKS, GRADES

INK = QColor(58, 40, 26)
SEA_INK = QColor(46, 66, 80)
PAPER = QColor(236, 222, 184)
SHADE = QColor(58, 40, 26, 70)
RED = QColor(160, 42, 30)
PARTY = QColor(176, 46, 34)
ROUTE = QColor(70, 46, 30)
PING = QColor(250, 204, 21)
TITLING = ["Felix Titling", "Palatino Linotype", "Book Antiqua", "Palatino", "Georgia", "serif"]   # world.js: W_TITLING
SERIF = ["Palatino Linotype", "Book Antiqua", "Palatino", "Georgia", "serif"]
NAME_SIZE = {"capital": 15, "city": 13, "town": 11, "village": 9, "fort": 10, "ruin": 9, "poi": 9}
MARK_R = {"capital": 8, "city": 5.5, "town": 3.6, "village": 2.6, "fort": 4.5, "ruin": 4, "poi": 3.5, "compass": 24}
LABEL_SIZE = {1: 11, 2: 16, 3: 24, 4: 36}
PLAQUES = False                                                 # the map's names on plaques (the canvas sets it with LOOK)
LOOK = "painted"                                                # the open map's look (render.LOOKS): the canvas sets it
SEA_LIGHT = QColor(230, 238, 234)                               # the painted look's names at sea: pale on the dark water
SEA_HALO = QColor(14, 28, 38)
SHADOW = 0.5                                                    # how dark a stamp's shadow is (the painted look)
NAME_LIGHT = QColor(244, 236, 216)                              # the painted look's names: pale, with a dark halo
NAME_HALO = QColor(26, 20, 14)
RIBBON = ((236, 218, 176), (186, 160, 112), (58, 40, 26))       # a banner's ribbon: front, its folded ends, outline


def font(size: float, italic=False, bold=False, spacing: float = 0.0, families=None) -> QFont:
    f = QFont()
    f.setFamilies(families or SERIF)
    f.setPixelSize(max(1, round(size * 4)))                     # set big and scaled down: smooth at any zoom
    f.setItalic(italic)
    f.setBold(bold)
    f.setHintingPreference(QFont.PreferNoHinting)
    if spacing:
        f.setLetterSpacing(QFont.PercentageSpacing, 100 + spacing * 100)
    return f


def _rand(v: int, i: int) -> float:
    """0..1, the same every time for (v, i): a mark's own wobble."""
    x = math.sin(v * 12.9898 + i * 78.233) * 43758.5453
    return x - math.floor(x)


def text_path(text: str, f: QFont, x: float, y: float, align: str = "left") -> QPainterPath:
    """The text as a path at map size (the font is made 4× big and the path scaled down)."""
    p = QPainterPath()
    p.addText(0, 0, f, text)
    r = p.boundingRect()
    dx = {"left": 0, "center": -r.width() / 2, "right": -r.width()}[align]
    return QTransform().translate(x, y).scale(0.25, 0.25).translate(dx * 1.0 - r.left(), 0).map(p)


def name_text(g, path: QPainterPath, color: QColor = INK):
    """A mark's name: on a parchment plaque when the map wants (PLAQUES), else ink letters with their halo."""
    if PLAQUES:
        paint_plaque(g, path.boundingRect())
        g.setPen(Qt.NoPen)
        g.setBrush(color if color.rgb() != INK.rgb() else C3(RIBBON[2]))
        g.drawPath(path)
    else:
        halo_text(g, path, color)


def halo_text(g, path: QPainterPath, color: QColor = INK, halo: float = 2.4, halo_alpha: int = 200, halo_color: QColor = PAPER):
    """Ink letters with a paper halo so they read over coasts and ripples (on the painted look's colour: pale letters
    with a dark halo instead)."""
    if LOOK in COLOUR_LOOKS and halo_color is PAPER and color.rgb() == INK.rgb():
        light = QColor(NAME_LIGHT)
        light.setAlpha(color.alpha())
        color, halo_color, halo_alpha = light, NAME_HALO, min(halo_alpha, 175)
    c = QColor(halo_color)
    c.setAlpha(halo_alpha)
    g.setPen(QPen(c, halo, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    g.setBrush(Qt.NoBrush)
    g.drawPath(path)
    g.setPen(Qt.NoPen)
    g.setBrush(color)
    g.drawPath(path)


# ---------------------------------------------------------------------- marks
def _star(cx, cy, r, inner):
    pts = []
    for i in range(10):
        a = -math.pi / 2 + i * math.pi / 5
        rr = r if i % 2 == 0 else inner
        pts.append(QPointF(cx + math.cos(a) * rr, cy + math.sin(a) * rr))
    return QPolygonF(pts)


def paint_marks(g, marks):
    """Marks back to front, then all their names over them (a name is never hidden under the next stamp)."""
    for m in marks:
        paint_mark(g, m, name=False)
    for m in marks:
        paint_mark_name(g, m)


def paint_mark_name(g, m: dict):
    """Only a mark's name, where paint_mark puts it."""
    if not m.get("name") or m["kind"] in TERRAIN or m["kind"] == "compass":
        return
    if m["kind"] == ART:
        _stamp_name(g, m)
        return
    pic = stamps.terrain_art(m) if LOOK in COLOUR_LOOKS and m["kind"] in stamps.SETTLEMENT_ART else None
    if pic:
        _pic_name(g, m, pic)
        return
    x, y, s = m["x"], m["y"], float(m.get("s") or 1)
    if s != 1:
        g.save()
        g.translate(x, y)
        g.scale(s, s)
        g.translate(-x, -y)
    _settlement_name(g, m)
    if s != 1:
        g.restore()


def paint_mark(g, m: dict, selected: bool = False, name: bool = True):
    """A mark and its name, `s` times their size (scaled as drawings: sharp at any zoom); name False: without it."""
    kind, x, y = m["kind"], m["x"], m["y"]
    s = float(m.get("s") or 1)
    if kind in TERRAIN:
        paint_terrain(g, m)
        if selected:
            _ring(g, x, y - 5 * s, 9 * s)
        return
    if kind == "compass":
        paint_compass(g, x, y, 24 * s, selected)
        return
    if kind == ART:
        paint_stamp(g, m, selected, name)
        return
    pic = stamps.terrain_art(m) if LOOK in COLOUR_LOOKS and kind in stamps.SETTLEMENT_ART else None
    if pic:                                                     # the painted looks: a painted town, castle or ruin
        paint_stamp(g, {"kind": ART, "art": pic[0], "x": x, "y": y, "s": pic[1]}, selected, name=False)
        if name:
            _pic_name(g, m, pic)
        return
    if s != 1:
        g.save()
        g.translate(x, y)
        g.scale(s, s)
        g.translate(-x, -y)
    _settlement(g, m, selected, name)
    if s != 1:
        g.restore()


def _pic_name(g, m: dict, pic: tuple):
    """A settlement's name beside the painted picture it is drawn with (sized as the mark's name)."""
    if not m.get("name"):
        return
    kind = m["kind"]
    r = stamp_rect({"kind": ART, "art": pic[0], "x": m["x"], "y": m["y"], "s": pic[1]})
    size = NAME_SIZE.get(kind, 10) * float(m.get("s") or 1)
    f = font(size, bold=kind == "capital", spacing=0.04 if kind in ("capital", "city") else 0.0)
    name_text(g, text_path(m["name"], f, r.right() + 2.5 + (size * 0.6 if PLAQUES else 0), r.center().y() + size * 0.34), INK)


def _settlement(g, m: dict, selected: bool, name: bool = True):
    kind, x, y = m["kind"], m["x"], m["y"]
    pen = QPen(INK, 1.3)
    g.setPen(pen)
    if kind == "capital":
        g.setBrush(PAPER)
        g.drawEllipse(QPointF(x, y), 7.5, 7.5)
        g.setPen(Qt.NoPen)
        g.setBrush(INK)
        g.drawPolygon(_star(x, y, 6.2, 2.6))
    elif kind == "city":
        g.setPen(QPen(INK, 1.4))
        g.setBrush(PAPER)
        g.drawEllipse(QPointF(x, y), 5.5, 5.5)
        g.setPen(Qt.NoPen)
        g.setBrush(INK)
        g.drawEllipse(QPointF(x, y), 2.9, 2.9)
    elif kind == "town":
        g.setPen(QPen(PAPER, 1.0))
        g.setBrush(INK)
        g.drawEllipse(QPointF(x, y), 3.6, 3.6)
    elif kind == "village":
        g.setPen(QPen(INK, 1.2))
        g.setBrush(PAPER)
        g.drawEllipse(QPointF(x, y), 2.6, 2.6)
    elif kind == "fort":
        g.setPen(QPen(PAPER, 0.8))
        g.setBrush(INK)
        p = QPainterPath()
        p.moveTo(x - 4.5, y + 4)
        p.lineTo(x - 4.5, y - 4.5)
        for i, top in enumerate((-4.5, -2.8, -4.5, -2.8, -4.5)):
            p.lineTo(x - 4.5 + i * 2.25, y + top)
            p.lineTo(x - 4.5 + (i + 1) * 2.25 if i < 4 else x + 4.5, y + top)
        p.lineTo(x + 4.5, y + 4)
        p.closeSubpath()
        g.drawPath(p)
        g.setBrush(PAPER)
        g.setPen(Qt.NoPen)
        g.drawRect(QRectF(x - 1.1, y + 0.6, 2.2, 3.4))
    elif kind == "ruin":
        g.setPen(QPen(INK, 1.3, Qt.CustomDashLine))
        pen = g.pen()
        pen.setDashPattern([2.2, 1.6])
        g.setPen(pen)
        g.setBrush(Qt.NoBrush)
        g.drawEllipse(QPointF(x, y), 4, 4)
        g.setPen(QPen(INK, 1.1))
        g.drawLine(QPointF(x - 1.6, y - 1.6), QPointF(x + 1.6, y + 1.6))
        g.drawLine(QPointF(x - 1.6, y + 1.6), QPointF(x + 1.6, y - 1.6))
    elif kind == "poi":
        g.setPen(QPen(RED, 1.8, Qt.SolidLine, Qt.RoundCap))
        g.drawLine(QPointF(x - 3.4, y - 3.4), QPointF(x + 3.4, y + 3.4))
        g.drawLine(QPointF(x - 3.4, y + 3.4), QPointF(x + 3.4, y - 3.4))
    if selected:
        _ring(g, x, y, MARK_R.get(kind, 5) + 3)
    if name:
        _settlement_name(g, m)


def _settlement_name(g, m: dict):
    kind, x, y = m["kind"], m["x"], m["y"]
    if m.get("name"):
        r = MARK_R.get(kind, 4)
        size = NAME_SIZE.get(kind, 10)
        f = font(size, bold=kind == "capital", spacing=0.04 if kind in ("capital", "city") else 0.0)
        name_text(g, text_path(m["name"], f, x + r + 2.5 + (size * 0.6 if PLAQUES else 0), y + size * 0.34), RED if kind == "poi" else INK)


_stamps = {}                                                    # key -> QPixmap (None: no picture)
_scaled = {}                                                    # (key, height in device pixels) -> QPixmap


def set_look(look: str):
    """The open map's look (its stamps are graded to it: the pictures are loaded again when it changes)."""
    global LOOK
    if look != LOOK:
        LOOK = look
        forget_stamps()
        _tints.clear()


def grade(c: QColor) -> QColor:
    """A colour in the look's grade (render.GRADES: the antique look's warm tone)."""
    if LOOK not in GRADES:
        return c
    (tr_, tg, tb), k = GRADES[LOOK]
    lum = c.red() * 0.3 + c.green() * 0.59 + c.blue() * 0.11
    return QColor(*(max(0, min(255, round(v + (lum * t - v) * k))) for v, t in ((c.red(), tr_), (c.green(), tg), (c.blue(), tb))),
                  c.alpha())


def _graded(pm: QPixmap) -> QPixmap:
    if LOOK not in GRADES:
        return pm
    import numpy as np
    img = pm.toImage().convertToFormat(QImage.Format_RGBA8888)
    w, h = img.width(), img.height()
    a = np.frombuffer(img.constBits(), np.uint8).reshape(h, img.bytesPerLine() // 4, 4)[:, :w].astype(np.float32)
    tone, k = GRADES[LOOK]
    lum = a[..., :3] @ np.float32([0.3, 0.59, 0.11])
    a[..., :3] += (lum[..., None] * np.float32(tone) - a[..., :3]) * k
    out = np.ascontiguousarray(np.clip(a, 0, 255).astype(np.uint8))
    return QPixmap.fromImage(QImage(out.data, w, h, w * 4, QImage.Format_RGBA8888).copy())


def stamp_pixmap(key: str, px: int = 0):
    """A stamp's picture (in the look's grade); with `px`, ready scaled to about that many pixels tall (smoothly: fine
    ink lines stay whole when a big picture is drawn small)."""
    if key not in _stamps:
        path = stamps.path(key)
        pm = QPixmap(path) if path else None
        _stamps[key] = _graded(pm) if pm and not pm.isNull() else None
    pm = _stamps[key]
    if pm is None or px <= 0 or px >= pm.height():
        return pm
    px = max(4, (px + 3) // 4 * 4)                              # a size every 4 px: zooming doesn't make new ones all the time
    if (key, px) not in _scaled:
        if len(_scaled) > 800:
            _scaled.clear()
        _scaled[(key, px)] = pm.scaledToHeight(px, Qt.SmoothTransformation)
    return _scaled[(key, px)]


_shadows = {}                                                   # key -> (QImage of its soft shadow, margin as a share of its size)
_shadows_scaled = {}


def stamp_shadow(key: str, px: int = 0):
    """A picture stamp's soft shadow (its outline blurred, dark), with the margin the blur adds round the picture:
    (QPixmap or None, margin x, margin y as shares of its width and height)."""
    if key not in _shadows:
        pm = stamp_pixmap(key)
        _shadows[key] = None
        if pm is not None:
            import numpy as np
            from ....services.world import render as R
            img = pm.toImage().convertToFormat(QImage.Format_ARGB32)
            w, h = img.width(), img.height()
            a = np.frombuffer(img.constBits(), np.uint8).reshape(h, img.bytesPerLine() // 4, 4)[:, :w, 3].astype(np.float32) / 255
            sig = max(1.5, h * 0.035)
            m = int(sig * 3)
            a = R.blur(np.pad(a, m), sig)
            out = np.zeros(a.shape + (4,), np.uint8)
            out[..., 3] = np.clip(a * 255 * SHADOW, 0, 255)            # (black: premultiplied and straight are the same)
            sh = QImage(out.data, out.shape[1], out.shape[0], out.shape[1] * 4, QImage.Format_ARGB32).copy()
            _shadows[key] = (QPixmap.fromImage(sh), m / w, m / h)
    got = _shadows[key]
    if got is None or px <= 0:
        return got
    pm, mx, my = got
    px = max(4, (px + 3) // 4 * 4)
    if px >= pm.height():
        return got
    if (key, px) not in _shadows_scaled:
        if len(_shadows_scaled) > 800:
            _shadows_scaled.clear()
        _shadows_scaled[(key, px)] = pm.scaledToHeight(px, Qt.SmoothTransformation)
    return _shadows_scaled[(key, px)], mx, my


def forget_stamps():
    """After the DM's own pictures changed: load them again."""
    _stamps.clear()
    _scaled.clear()
    _shadows.clear()
    _shadows_scaled.clear()


_shapes = {}                                                    # key -> (paper, ink) QPainterPaths of an ink stamp
INK_PAPER = QColor(226, 208, 164)                               # an ink stamp's paper (the parchment's own tone)
INK_BLACK = QColor(28, 22, 16)
INK_TINTS = {   # the painted look: an ink stamp's paper coloured as what it is, by its family (world.js: W_INK_TINTS)
    "tree": (112, 146, 76), "wood": (98, 134, 70), "bush": (112, 146, 76), "pine": (78, 116, 74), "palm": (118, 152, 82),
    "deadtree": (150, 132, 102), "cactus": (112, 150, 92), "swamp": (112, 126, 82), "grass": (138, 146, 78),
    "mountain": (186, 170, 138), "range": (186, 170, 138), "cliffs": (176, 160, 128), "volcano": (150, 118, 100),
    "hills": (160, 156, 98), "dunes": (224, 202, 150), "fields": (204, 182, 108),
    "village": (222, 200, 160), "town": (222, 200, 160), "city": (222, 200, 160), "farmstead": (222, 200, 160),
    "castle": (206, 198, 182), "tower": (206, 198, 182), "watchtower": (206, 198, 182), "lighthouse": (230, 222, 206),
    "temple": (218, 206, 184), "ruins": (190, 182, 166), "stones": (180, 176, 166), "obelisk": (190, 184, 170),
    "serpent": (104, 140, 132), "whale": (126, 146, 156), "kraken": (156, 108, 112), "searocks": (150, 146, 136),
}
INK_PALE = ("waves", "whirlpool")                               # the painted look: drawn pale on the dark sea
_tints = {}                                                     # key -> QColor of its paper in the painted look


def ink_paper(key: str) -> QColor:
    """The paper an ink stamp is filled with: the parchment's tone, or (painted) a colour for what it shows."""
    if LOOK not in COLOUR_LOOKS:
        return INK_PAPER
    if key not in _tints:
        fam = (key or "").rstrip("0123456789").rstrip("_")
        fam = fam[4:] if fam.startswith("ink_") else fam
        _tints[key] = grade(QColor(*INK_TINTS[fam])) if fam in INK_TINTS else INK_PAPER
    return _tints[key]


def ink_ink(key: str) -> QColor:
    """An ink stamp's ink: black, but pale for the sea's waves on the painted look's dark water."""
    if LOOK in COLOUR_LOOKS and (key or "").rstrip("0123456789").rstrip("_")[4:] in INK_PALE:
        return QColor(214, 228, 224, 220)
    return INK_BLACK


def _svg_path(d: str) -> QPainterPath:
    """Our SVG path data (polygons: "M x y L x y ... Z") as a path filled even-odd."""
    p = QPainterPath()
    p.setFillRule(Qt.OddEvenFill)
    for chunk in d.split("Z"):
        chunk = chunk.strip().lstrip("M")
        if not chunk:
            continue
        pts = [QPointF(*map(float, xy.split())) for xy in chunk.split(" L")]
        p.addPolygon(QPolygonF(pts))
        p.closeSubpath()
    return p


def stamp_shapes(key: str):
    """An ink stamp's paper and ink, in map pixels round its point (None for a picture stamp)."""
    if key not in _shapes:
        e = stamps.get(key)
        _shapes[key] = (_svg_path(e.get("p") or ""), _svg_path(e.get("i") or "")) if e and e.get("vector") else None
    return _shapes[key]


def stamp_icon(key: str, size: int) -> QPixmap:
    """A stamp's picture for the strip: size × size, its drawing fitted in."""
    out = QPixmap(size, size)
    out.fill(Qt.transparent)
    shapes = stamp_shapes(key)
    if shapes:
        e = stamps.get(key)
        w, h = float(e.get("w") or e["h"]), float(e["h"])
        k = (size - 4) / max(w, h)
        g = QPainter(out)
        g.setRenderHint(QPainter.Antialiasing)
        g.translate(size / 2, size / 2 + (h * k / 2 if e["anchor"] == "b" else 0))
        g.scale(k, k)
        g.fillPath(shapes[0], INK_PAPER)
        g.fillPath(shapes[1], INK_BLACK)
        g.end()
    else:
        pm = stamp_pixmap(key)
        if pm:
            pm = pm.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            g = QPainter(out)
            g.drawPixmap((size - pm.width()) // 2, (size - pm.height()) // 2, pm)
            g.end()
    return out


def stamp_rect(m: dict) -> QRectF:
    """Where a stamp lies on the map before it is turned (map pixels): h × s tall, standing on its point or around it."""
    e = stamps.get(m.get("art")) or {"h": 20.0, "anchor": "c"}
    h = float(e["h"]) * float(m.get("s") or 1)
    if e.get("vector"):
        w = float(e["w"]) * float(m.get("s") or 1)
    else:
        pm = stamp_pixmap(m.get("art"))
        w = h * (pm.width() / pm.height() if pm else 1.0)
    top = m["y"] - h if e["anchor"] == "b" else m["y"] - h / 2
    return QRectF(m["x"] - w / 2, top, w, h)


def mark_reach(m: dict) -> float:
    """How far round its point a mark (and its name) may draw: for keeping only those in sight."""
    s = float(m.get("s") or 1)
    if m["kind"] == ART:
        e = stamps.get(m.get("art"))
        reach = (float(e["h"]) if e else 20.0) * s * 1.6
    else:
        reach = (30.0 if m["kind"] in ("compass", "capital", "city") else 22.0) * s     # (a painted city is big)
    return reach + (len(m.get("name") or "") * 8 * s if m.get("name") else 0)


def paint_erasing(g, m: dict, k: float):
    """A mark the eraser is taking: a red wash over it (it goes when the button is let go)."""
    r = stamp_rect(m) if m["kind"] == ART else QRectF(m["x"] - 6, m["y"] - 10, 12, 14)
    c = QColor(RED)
    c.setAlpha(110)
    g.setPen(QPen(QColor(RED), 1.2 * k))
    g.setBrush(c)
    g.drawEllipse(r.center(), r.width() / 2, r.height() / 2)


def stamp_box(m: dict, foot: float = 0.9) -> tuple:
    """A stamp's footprint as a turned box (x, y, half width, half height, radians): its picture less the margin."""
    r = stamp_rect(m)
    return (r.center().x(), r.center().y(), r.width() / 2 * foot, r.height() / 2 * foot, math.radians(float(m.get("r") or 0)))


def boxes_cross(a: tuple, b: tuple) -> bool:
    """Do two turned boxes overlap? (separating axes)"""
    dx, dy = b[0] - a[0], b[1] - a[1]
    if math.hypot(dx, dy) > math.hypot(a[2], a[3]) + math.hypot(b[2], b[3]):
        return False
    axes = [(math.cos(t), math.sin(t)) for t in (a[4], a[4] + math.pi / 2, b[4], b[4] + math.pi / 2)]
    for nx, ny in axes:
        ra = a[2] * abs(math.cos(a[4]) * nx + math.sin(a[4]) * ny) + a[3] * abs(-math.sin(a[4]) * nx + math.cos(a[4]) * ny)
        rb = b[2] * abs(math.cos(b[4]) * nx + math.sin(b[4]) * ny) + b[3] * abs(-math.sin(b[4]) * nx + math.cos(b[4]) * ny)
        if abs(dx * nx + dy * ny) >= ra + rb:
            return False
    return True


def stamp_hit(m: dict, x: float, y: float, tol: float = 0.0) -> bool:
    """Is the map point on the stamp (turned as it is)?"""
    a = -math.radians(float(m.get("r") or 0))
    dx, dy = x - m["x"], y - m["y"]
    px, py = m["x"] + dx * math.cos(a) - dy * math.sin(a), m["y"] + dx * math.sin(a) + dy * math.cos(a)
    return stamp_rect(m).adjusted(-tol, -tol, tol, tol).contains(QPointF(px, py))


def paint_stamp(g, m: dict, selected: bool = False, name: bool = True):
    """A stamp, turned `r` degrees about its point."""
    r = stamp_rect(m)
    turn = float(m.get("r") or 0)
    if turn:
        g.save()
        g.translate(m["x"], m["y"])
        g.rotate(turn)
        g.translate(-m["x"], -m["y"])
    shapes = stamp_shapes(m.get("art"))
    pm = None if shapes else stamp_pixmap(m.get("art"), round(r.height() * math.hypot(g.worldTransform().m11(), g.worldTransform().m12())))
    if shapes:                                                  # an ink stamp: its paper and its ink, two fills
        g.save()
        g.translate(m["x"], m["y"])
        g.scale(float(m.get("s") or 1), float(m.get("s") or 1))
        if LOOK in COLOUR_LOOKS:                                   # (a shadow down and to the right)
            off = 0.3 + stamps.get(m.get("art"))["h"] * 0.05
            g.translate(off * 0.7, off)
            g.fillPath(shapes[0], QColor(0, 0, 0, 70))
            g.translate(-off * 0.7, -off)
        g.fillPath(shapes[0], ink_paper(m.get("art")))
        g.fillPath(shapes[1], ink_ink(m.get("art")))
        g.restore()
    elif pm is None:                                            # (a picture of the DM's since taken away)
        g.setPen(QPen(INK, 0.8, Qt.DashLine))
        g.setBrush(Qt.NoBrush)
        g.drawRect(r)
    else:
        if LOOK in COLOUR_LOOKS:                                   # a soft shadow down and to the right, as Inkarnate's
            sh = stamp_shadow(m.get("art"))
            if sh:
                px = r.height() * (1 + 2 * sh[2]) * math.hypot(g.worldTransform().m11(), g.worldTransform().m12())
                spm, mx, my = stamp_shadow(m.get("art"), round(px))
                off = 0.4 + r.height() * (0.09 if r.height() > 15 else 0.05)     # (tall ones cast longer shadows; world.js too)
                g.drawPixmap(r.adjusted(-r.width() * mx, -r.height() * my, r.width() * mx, r.height() * my)
                             .translated(off * 0.7, off), spm, QRectF(spm.rect()))
        g.drawPixmap(r, pm, QRectF(pm.rect()))
    if selected:
        pen = QPen(QColor(250, 204, 21), 1.6, Qt.DashLine)
        pen.setCosmetic(True)                                   # (the same on screen at any zoom)
        g.setPen(pen)
        g.setBrush(Qt.NoBrush)
        g.drawRect(r.adjusted(-0.5, -0.5, 0.5, 0.5))
    if turn:
        g.restore()
    if name:
        _stamp_name(g, m)


STAMP_NAME = (("city", 13.5, True), ("castle", 12, True), ("palace", 12, True), ("harbour", 11.5, False),
              ("town", 11.5, False), ("village", 9.5, False), ("hamlet", 9.5, False))   # (by what it shows; world.js: W_STAMP_NAME)


def _stamp_name(g, m: dict):
    if m.get("name"):
        r, turn = stamp_rect(m), float(m.get("r") or 0)
        size, bold = next(((sz, b) for k, sz, b in STAMP_NAME if k in (m.get("art") or "")), (NAME_SIZE["town"], False))
        size *= float(m.get("s") or 1) ** 0.5                   # (a bigger picture: a bigger name, not as much bigger)
        half = max(r.width(), r.height()) / 2 if turn else r.width() / 2
        name_text(g, text_path(m["name"], font(size, bold=bold, spacing=0.03 if bold else 0.0), m["x"] + half + 2.5 + (size * 0.6 if PLAQUES else 0),
                               r.center().y() + size * 0.34), INK)


def paint_compass(g, x, y, r, selected=False):
    """A compass rose: rings, eight points (the four winds dark on one side) and an N; on the painted look, rhumb lines
    run from it right across the sea."""
    if LOOK in COLOUR_LOOKS:
        for i in range(16):
            a = i * math.pi / 8
            g.setPen(QPen(QColor(232, 222, 196, 70 if i % 4 == 0 else 38), 0.7 if i % 4 == 0 else 0.5))
            g.drawLine(QPointF(x + math.cos(a) * r * 0.8, y + math.sin(a) * r * 0.8), QPointF(x + math.cos(a) * 4000, y + math.sin(a) * 4000))
    g.setBrush(Qt.NoBrush)
    g.setPen(QPen(INK, 0.9))
    g.drawEllipse(QPointF(x, y), r * 0.72, r * 0.72)
    g.setPen(QPen(INK, 0.5))
    g.drawEllipse(QPointF(x, y), r * 0.64, r * 0.64)
    for i in range(32):                                      # the ticks between the rings
        a = i * math.pi / 16
        g.drawLine(QPointF(x + math.cos(a) * r * 0.64, y + math.sin(a) * r * 0.64),
                   QPointF(x + math.cos(a) * r * 0.72, y + math.sin(a) * r * 0.72))
    for i, (length, width) in enumerate([(r, r * 0.16)] * 4 + [(r * 0.62, r * 0.12)] * 4):
        a = -math.pi / 2 + (i % 4) * math.pi / 2 + (math.pi / 4 if i >= 4 else 0)
        tip = QPointF(x + math.cos(a) * length, y + math.sin(a) * length)
        left = QPointF(x + math.cos(a - math.pi / 2) * width, y + math.sin(a - math.pi / 2) * width)
        right = QPointF(x + math.cos(a + math.pi / 2) * width, y + math.sin(a + math.pi / 2) * width)
        g.setPen(QPen(INK, 0.7))
        g.setBrush(PAPER)
        g.drawPolygon(QPolygonF([QPointF(x, y), left, tip]))
        g.setBrush(INK)
        g.drawPolygon(QPolygonF([QPointF(x, y), tip, right]))
    halo_text(g, text_path("N", font(r * 0.42, bold=True), x, y - r * 1.06, "center"), INK, halo=r * 0.08)
    if selected:
        _ring(g, x, y, r + 3)


def _ring(g, x, y, r):
    g.setPen(QPen(QColor(250, 204, 21), 1.4, Qt.DashLine))
    g.setBrush(Qt.NoBrush)
    g.drawEllipse(QPointF(x, y), r, r)


def paint_terrain(g, m: dict):
    """A mountain, a hill or a tree, drawn in ink like an old map (a paper fill hides what is behind it)."""
    x, y, s, v = m["x"], m["y"], float(m.get("s") or 1.0), int(m.get("v") or 0)
    kind = m["kind"]
    pic = stamps.terrain_art(m) if LOOK in COLOUR_LOOKS else None
    if pic:                                                     # the painted look: its painted picture
        paint_stamp(g, {"kind": ART, "art": pic[0], "x": x, "y": y, "s": pic[1]})
        return
    g.setPen(QPen(INK, 1.0, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    if kind == "mountain":
        w, h = (13 + _rand(v, 1) * 6) * s, (11 + _rand(v, 2) * 6) * s
        px = x + (_rand(v, 3) - 0.5) * w * 0.3
        shoulder = _rand(v, 4) > 0.45
        p = QPainterPath(QPointF(x - w / 2, y))
        if shoulder:
            p.lineTo(x - w * 0.28, y - h * 0.45)
            p.lineTo(x - w * 0.2, y - h * 0.38)
        p.lineTo(px, y - h)
        p.lineTo(px + w * 0.12, y - h * 0.82)
        p.lineTo(px + w * 0.18, y - h * 0.86)
        p.lineTo(x + w / 2, y)
        g.setBrush(PAPER)
        g.drawPath(p)
        shade = QPainterPath(QPointF(px, y - h))                 # the far side in shadow
        shade.lineTo(px + w * 0.12, y - h * 0.82)
        shade.lineTo(px + w * 0.18, y - h * 0.86)
        shade.lineTo(x + w / 2, y)
        shade.lineTo(px + w * 0.05, y)
        shade.closeSubpath()
        g.setPen(Qt.NoPen)
        g.setBrush(SHADE)
        g.drawPath(shade)
        g.setPen(QPen(INK, 0.8, Qt.SolidLine, Qt.RoundCap))
        ridge = QPainterPath(QPointF(px, y - h))                 # the ridge down the middle
        ridge.quadTo(QPointF(px + w * 0.02, y - h * 0.45), QPointF(px + w * 0.05, y))
        g.setBrush(Qt.NoBrush)
        g.drawPath(ridge)
        for i in range(1, 4):                                    # hatching down the shaded side
            t = i / 4.5
            ax, ay = px + w * 0.05 + (x + w / 2 - px - w * 0.05) * t * 0.85, y - h * (1 - t) * 0.72
            g.drawLine(QPointF(ax, ay), QPointF(ax + w * 0.02, min(y, ay + h * 0.28)))
    elif kind == "hills":
        w, h = (12 + _rand(v, 1) * 6) * s, (5 + _rand(v, 2) * 3) * s
        p = QPainterPath(QPointF(x - w / 2, y))
        p.cubicTo(QPointF(x - w * 0.3, y - h * 1.3), QPointF(x + w * 0.3, y - h * 1.3), QPointF(x + w / 2, y))
        g.setBrush(PAPER)
        g.drawPath(p)
        g.setPen(QPen(INK, 0.7))
        g.drawLine(QPointF(x + w * 0.12, y - h * 0.55), QPointF(x + w * 0.24, y - h * 0.2))
        g.drawLine(QPointF(x + w * 0.24, y - h * 0.62), QPointF(x + w * 0.34, y - h * 0.3))
    elif kind == "forest":
        r = (3.2 + _rand(v, 1) * 1.6) * s
        g.drawLine(QPointF(x, y), QPointF(x, y - r * 0.9))
        crown = QPainterPath()
        n = 7
        for i in range(n + 1):                                   # a bumpy round crown
            a = math.pi * 2 * i / n
            rr = r * (0.88 + 0.14 * _rand(v, 10 + i % n))
            pt = QPointF(x + math.cos(a) * rr, y - r * 1.6 + math.sin(a) * rr)
            crown.moveTo(pt) if i == 0 else crown.lineTo(pt)
        g.setBrush(QColor(206, 200, 158))
        g.drawPath(crown)
        g.setPen(Qt.NoPen)
        g.setBrush(SHADE)
        g.drawPie(QRectF(x - r, y - r * 2.6, r * 2, r * 2), -30 * 16, -150 * 16)


# ---------------------------------------------------------------------- the grid
def grid_path(kind: str, px: float, w: float, h: float) -> QPainterPath:
    """A grid over a w × h map: hexes (pointy-topped, px across their flats) or squares px wide (world.js: wGrid)."""
    p = QPainterPath()
    if kind == "square":
        for i in range(1, int(w / px) + 1):
            p.moveTo(i * px, 0)
            p.lineTo(i * px, h)
        for j in range(1, int(h / px) + 1):
            p.moveTo(0, j * px)
            p.lineTo(w, j * px)
        return p
    r = px / math.sqrt(3.0)
    for row in range(int(h / (1.5 * r)) + 2):
        cy, off = row * 1.5 * r, (row % 2) * px / 2
        for c in range(-1, int(w / px) + 2):
            cx = c * px + off
            pts = [QPointF(cx + math.cos(math.radians(a)) * r, cy + math.sin(math.radians(a)) * r) for a in (90, 150, 210, 270)]
            p.moveTo(pts[0])                                    # three sides a hex: its neighbours draw the rest
            for q in pts[1:]:
                p.lineTo(q)
    return p


def paint_grid(g, grid, w: float, h: float):
    """The map's grid ({"kind", "px"} or None), faint: pale on the colour looks, ink on the others."""
    if not grid:
        return
    color = QColor(250, 244, 226, 60) if LOOK in COLOUR_LOOKS else QColor(58, 40, 26, 55)
    g.save()
    g.setClipRect(QRectF(0, 0, w, h))
    g.setPen(QPen(color, 0.6))
    g.setBrush(Qt.NoBrush)
    g.drawPath(grid_path(grid["kind"], float(grid["px"]), w, h))
    g.restore()


def bar_miles(mpp: float, w: float) -> float:
    """The scale bar's length in miles: a round number about a sixth of the map's width (world.js: wBarMiles)."""
    want = mpp * w / 6.0
    k = 10 ** math.floor(math.log10(want))
    return max(n * k for n in (1, 2, 5, 10) if n * k <= want)


def paint_scale_bar(g, mpp: float, w: float, h: float):
    """A bar of miles in the map's bottom left corner: four blocks dark and light, 0 and its miles under it."""
    if not mpp:
        return
    miles = bar_miles(mpp, w)
    length = miles / mpp
    x, y, bh = 34.0, h - 30.0, 3.4
    dark, light = (QColor(30, 24, 18), QColor(240, 232, 212)) if LOOK in COLOUR_LOOKS else (INK, PAPER)
    g.setPen(QPen(dark, 0.7))
    for i in range(4):
        g.setBrush(dark if i % 2 == 0 else light)
        g.drawRect(QRectF(x + length * i / 4, y, length / 4, bh))
    f = font(7.5, bold=True)
    for text, at, align in (("0", x, "center"), (tr("{0} mi", f"{miles:g}"), x + length, "center")):
        halo_text(g, text_path(text, f, at, y + bh + 8.5, align), INK, halo=2.0)


# ---------------------------------------------------------------------- lines
LINE_LOOK = {   # style: [(colour, width, dashes in widths or None), ...] drawn in order (world.js: W_LINES)
    "road": [((236, 222, 184, 150), 3.6, None), ((58, 40, 26, 255), 1.6, None)],
    "path": [((58, 40, 26, 235), 1.4, [2.6, 1.8])],
    "river": [((236, 222, 184, 120), 3.8, None), ((52, 86, 108, 235), 2.0, None)],
    "border": [((150, 40, 28, 45), 6.0, None), ((150, 40, 28, 220), 1.5, [4.0, 1.6, 1.0, 1.6])],
    "guide": [((58, 40, 26, 120), 0.7, [6.0, 4.0])],         # a latitude, a rhumb line: thin and faint
    "wall": [((58, 40, 26, 255), 3.0, None), ((58, 40, 26, 255), 5.6, [0.3, 1.0])],
}
LINE_LOOK_PAINTED = dict(LINE_LOOK, **{
    "guide": [((240, 232, 210, 110), 0.7, [6.0, 4.0])],   # the painted look: earth roads, rivers the colour of its water (world.js)
    "road": [((236, 226, 196, 150), 2.8, None), ((40, 28, 18, 250), 1.45, [2.4, 1.5])],
    "path": [((236, 226, 196, 90), 2.0, None), ((44, 32, 22, 200), 0.9, [0.8, 2.0])],
    "river": [((48, 62, 60, 255), 3.8, None), ((96, 138, 150, 255), 2.6, None), ((170, 200, 204, 150), 0.7, None)],
})
TAPERED = ("river",)                                            # (painted) narrow at the start, wide at the end
TAPER = (0.35, 1.9)


def line_path(pts) -> QPainterPath:
    """Through the points, smoothed: straight to each midpoint, curving round the corners."""
    p = QPainterPath(QPointF(*pts[0]))
    if len(pts) == 2:
        p.lineTo(QPointF(*pts[1]))
        return p
    for a, b in zip(pts[1:-1], pts[2:]):
        p.quadTo(QPointF(*a), QPointF((a[0] + b[0]) / 2, (a[1] + b[1]) / 2))
    p.lineTo(QPointF(*pts[-1]))
    return p


def paint_line(g, line: dict, selected: bool = False):
    path = line_path(line["pts"])
    g.setBrush(Qt.NoBrush)
    if selected:
        g.setPen(QPen(QColor(250, 204, 21, 160), 7.0, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        g.drawPath(path)
    looks = LINE_LOOK_PAINTED if LOOK in COLOUR_LOOKS else LINE_LOOK
    if LOOK in COLOUR_LOOKS and line.get("style") in TAPERED:     # widening from its source to its mouth
        n = max(2, int(path.length() / 1.5))
        pts = [path.pointAtPercent(i / n) for i in range(n + 1)]
        layers = looks[line["style"]]
        for color, width, _d in layers[:-1]:
            for i in range(n):
                g.setPen(QPen(QColor(*color), width * (TAPER[0] + (TAPER[1] - TAPER[0]) * i / n), Qt.SolidLine, Qt.RoundCap))
                g.drawLine(pts[i], pts[i + 1])
        color, width, _d = layers[-1]
        g.setPen(QPen(QColor(*color), width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        g.drawPath(path)
        return
    for color, width, dashes in looks.get(line.get("style"), looks["road"]):
        pen = QPen(QColor(*color), width, Qt.SolidLine, Qt.FlatCap if dashes else Qt.RoundCap, Qt.RoundJoin)
        if dashes:
            pen.setDashPattern(dashes)
        g.setPen(pen)
        g.drawPath(path)


# ---------------------------------------------------------------------- names
def label_font(lab: dict) -> QFont:
    size = LABEL_SIZE.get(int(lab.get("size") or 2), 16)
    style = lab.get("style")
    if style == "sea":
        return font(size, italic=True, spacing=0.14)
    if style == "region":                                      # (a titling face where there is one: Office's)
        return font(size, bold=True, spacing=0.32, families=TITLING)
    if style == "title":
        return font(size * 1.5, bold=True, spacing=0.18, families=TITLING)
    if style in ("banner", "plaque"):
        return font(size * 0.8, bold=True, spacing=0.12)
    return font(size, spacing=0.1)


def caps(text: str) -> str:
    """Upper case, with a Turkish name's dotted i as İ (Çamhisar: ÇAMHİSAR, not ÇAMHISAR; world.js: wCaps)."""
    return text.replace("i", "İ").upper() if any(c in text for c in "ıİşŞğĞçÇöÖüÜ") else text.upper()


def label_text(lab: dict) -> str:
    return lab["text"] if lab.get("style") == "sea" else caps(lab["text"])


def bend_path(path: QPainterPath, bend: float) -> QPainterPath:
    """A name's letters bowed along an arc of `bend` degrees (+: arching up, -: sagging), its middle where it was
    (world.js: wBent draws the same letter by letter)."""
    r = path.boundingRect()
    if not bend or r.width() <= 0:
        return path
    radius = r.width() / math.radians(abs(bend))
    sign = 1.0 if bend > 0 else -1.0
    cx = r.center().x()
    out = QPainterPath(path)
    for i in range(out.elementCount()):                          # the arc's centre below the name (above it: sagging)
        e = out.elementAt(i)
        a = (e.x - cx) / radius
        d = radius - sign * e.y
        out.setElementPositionAt(i, cx + math.sin(a) * d, sign * (radius - math.cos(a) * d))
    return out


def paint_label(g, lab: dict, selected: bool = False):
    size = LABEL_SIZE.get(int(lab.get("size") or 2), 16)
    g.save()
    g.translate(lab["x"], lab["y"])
    g.rotate(float(lab.get("angle") or 0))
    g.scale(float(lab.get("s") or 1), float(lab.get("s") or 1))
    bend = 0.0 if lab.get("style") in ("banner", "plaque", "title") else float(lab.get("bend") or 0)     # (they stay straight)
    path = bend_path(text_path(label_text(lab), label_font(lab), 0, size * 0.35, "center"), bend)
    style = lab.get("style")
    color = QColor(SEA_INK) if style == "sea" else QColor(INK)
    if style == "region":
        color.setAlpha(150 if LOOK in COLOUR_LOOKS else 200)
    if style in ("banner", "plaque"):
        (paint_ribbon if style == "banner" else paint_plaque)(g, path.boundingRect())
        g.setPen(Qt.NoPen)
        g.setBrush(C3(RIBBON[2]))
        g.drawPath(path)
    elif style == "title":                                      # the map's name: flourishes either side, dark letters on a halo
        paint_flourish(g, path.boundingRect())
        halo_text(g, path, QColor(INK), halo=max(2.0, size * 0.22), halo_alpha=210, halo_color=PAPER)
    elif style == "sea" and LOOK in COLOUR_LOOKS:
        halo_text(g, path, SEA_LIGHT, halo=max(2.0, size * 0.18), halo_alpha=150, halo_color=SEA_HALO)
    else:
        halo_text(g, path, color, halo=max(2.0, size * 0.16), halo_alpha=150 if style == "sea" else 190)
    if selected:
        g.setPen(QPen(QColor(250, 204, 21), 1.2, Qt.DashLine))
        g.setBrush(Qt.NoBrush)
        g.drawRect(path.boundingRect().adjusted(-3, -3, 3, 3))
    g.restore()


def C3(rgb, a=255) -> QColor:
    return QColor(rgb[0], rgb[1], rgb[2], a)


def paint_ribbon(g, r: QRectF):
    """A ribbon banner behind a name (r: the letters' box): its band bowed a little, the ends folded back and cut."""
    h = r.height() * 1.7
    pad = h * 0.7
    x0, x1, cy = r.left() - pad, r.right() + pad, r.center().y()
    bow = h * 0.12
    for side in (-1, 1):                                        # the folded ends, behind and below the band
        xe = x0 if side < 0 else x1
        tail = QPainterPath(QPointF(xe - side * h * 0.1, cy - h * 0.2))
        tail.lineTo(xe + side * h * 0.95, cy - h * 0.2 + h * 0.25)
        tail.lineTo(xe + side * h * 0.65, cy + h * 0.3 + h * 0.25)
        tail.lineTo(xe + side * h * 0.95, cy + h * 0.8 + h * 0.25)
        tail.lineTo(xe - side * h * 0.1, cy + h * 0.8)
        tail.closeSubpath()
        g.setPen(QPen(C3(RIBBON[2]), h * 0.05, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        g.setBrush(C3(RIBBON[1]))
        g.drawPath(tail)
    band = QPainterPath(QPointF(x0, cy - h / 2))
    band.quadTo(QPointF((x0 + x1) / 2, cy - h / 2 - bow * 2), QPointF(x1, cy - h / 2))
    band.lineTo(x1, cy + h / 2)
    band.quadTo(QPointF((x0 + x1) / 2, cy + h / 2 - bow * 2), QPointF(x0, cy + h / 2))
    band.closeSubpath()
    grad = QLinearGradient(QPointF(0, cy - h / 2), QPointF(0, cy + h / 2))
    grad.setColorAt(0, C3(RIBBON[0]))
    grad.setColorAt(1, C3(RIBBON[1]))
    g.setBrush(grad)
    g.drawPath(band)
    g.setPen(QPen(C3(RIBBON[1]), h * 0.03))                       # a fine line along each edge
    g.setBrush(Qt.NoBrush)
    for k in (-1, 1):
        edge = QPainterPath(QPointF(x0 + h * 0.15, cy + k * h * 0.36))
        edge.quadTo(QPointF((x0 + x1) / 2, cy + k * h * 0.36 - bow * 2), QPointF(x1 - h * 0.15, cy + k * h * 0.36))
        g.drawPath(edge)


def paint_flourish(g, r: QRectF):
    """Ornaments either side of a title (r: its letters' box): a rule tapering out to a diamond, a dot past it."""
    h = r.height()
    cy = r.center().y()
    for side in (-1, 1):
        x0 = r.left() - h * 0.35 if side < 0 else r.right() + h * 0.35
        x1 = x0 + side * h * 2.6
        rule = QPainterPath(QPointF(x0, cy - h * 0.035))
        rule.lineTo(x1, cy)
        rule.lineTo(x0, cy + h * 0.035)
        rule.closeSubpath()
        dia = QPolygonF([QPointF(x0 + side * h * 0.9, cy - h * 0.16), QPointF(x0 + side * h * 1.12, cy),
                         QPointF(x0 + side * h * 0.9, cy + h * 0.16), QPointF(x0 + side * h * 0.68, cy)])
        pairs = ((NAME_HALO, NAME_LIGHT) if LOOK in COLOUR_LOOKS else (PAPER, INK))      # (as the letters: halo, then ink)
        for color, width in ((pairs[0], h * 0.12), (pairs[1], 0.0)):
            g.setPen(QPen(color, width, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin) if width else Qt.NoPen)
            g.setBrush(color)
            g.drawPath(rule)
            g.drawPolygon(dia)
            g.drawEllipse(QPointF(x1 + side * h * 0.18, cy), h * 0.06, h * 0.06)


def paint_plaque(g, r: QRectF):
    """A parchment tag behind a name (r: the letters' box): its corners cut, a dark rim and a fine line inside it."""
    px, py = r.height() * 0.9, r.height() * 0.55
    b = r.adjusted(-px, -py, px, py)
    c = b.height() * 0.22

    def cut(rr, k):
        return QPolygonF([QPointF(rr.left() + k, rr.top()), QPointF(rr.right() - k, rr.top()), QPointF(rr.right(), rr.top() + k),
                          QPointF(rr.right(), rr.bottom() - k), QPointF(rr.right() - k, rr.bottom()), QPointF(rr.left() + k, rr.bottom()),
                          QPointF(rr.left(), rr.bottom() - k), QPointF(rr.left(), rr.top() + k)])
    g.setPen(Qt.NoPen)
    g.setBrush(QColor(0, 0, 0, 70))
    g.drawPolygon(cut(b.translated(b.height() * 0.06, b.height() * 0.09), c))
    grad = QLinearGradient(QPointF(0, b.top()), QPointF(0, b.bottom()))
    grad.setColorAt(0, C3((240, 226, 190)))
    grad.setColorAt(1, C3((206, 184, 140)))
    g.setPen(QPen(C3(RIBBON[2]), b.height() * 0.07, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    g.setBrush(grad)
    g.drawPolygon(cut(b, c))
    g.setPen(QPen(C3((150, 120, 80)), b.height() * 0.03))
    g.setBrush(Qt.NoBrush)
    k = b.height() * 0.12
    g.drawPolygon(cut(b.adjusted(k, k, -k, -k), c * 0.7))


def label_rect(lab: dict) -> QRectF:
    """Where a name lies (unrotated, around its point): for clicking on it."""
    size = LABEL_SIZE.get(int(lab.get("size") or 2), 16)
    bend = 0.0 if lab.get("style") in ("banner", "plaque", "title") else float(lab.get("bend") or 0)
    r = bend_path(text_path(label_text(lab), label_font(lab), 0, size * 0.35, "center"), bend).boundingRect()
    k = float(lab.get("s") or 1)
    r = QRectF(r.x() * k, r.y() * k, r.width() * k, r.height() * k)
    return r.translated(lab["x"], lab["y"]).adjusted(-3, -3, 3, 3)


# ---------------------------------------------------------------------- the party
def paint_trail(g, trail, k: float):
    if len(trail) < 2:
        return
    pen = QPen(QColor(150, 40, 28, 190), 1.6, Qt.CustomDashLine, Qt.RoundCap, Qt.RoundJoin)
    pen.setDashPattern([1.2, 2.2])
    g.setPen(pen)
    g.setBrush(Qt.NoBrush)
    g.drawPolyline(QPolygonF([QPointF(*p) for p in trail]))


def paint_route(g, pos, route, k: float, text: str = ""):
    pts = ([pos] if pos else []) + list(route)
    if len(pts) < 2:
        return
    pen = QPen(ROUTE, 1.8, Qt.CustomDashLine, Qt.RoundCap, Qt.RoundJoin)
    pen.setDashPattern([4.0, 2.6])
    g.setPen(pen)
    g.setBrush(Qt.NoBrush)
    g.drawPolyline(QPolygonF([QPointF(*p) for p in pts]))
    g.setPen(QPen(ROUTE, 1.0))
    g.setBrush(PAPER)
    for p in route[:-1]:
        g.drawEllipse(QPointF(*p), 2.4, 2.4)
    # the end: an arrowhead on the last leg
    (ax, ay), (bx, by) = pts[-2], pts[-1]
    a = math.atan2(by - ay, bx - ax)
    head = QPolygonF([QPointF(bx, by), QPointF(bx - math.cos(a - 0.45) * 8, by - math.sin(a - 0.45) * 8),
                      QPointF(bx - math.cos(a + 0.45) * 8, by - math.sin(a + 0.45) * 8)])
    g.setPen(Qt.NoPen)
    g.setBrush(ROUTE)
    g.drawPolygon(head)
    if text:
        f = font(13 * k, bold=True)
        halo_text(g, text_path(text, f, bx + 9 * k, by - 7 * k), ROUTE, halo=3.5 * k)


def paint_party(g, pos, k: float, label: str = ""):
    """The party's banner: a pole and a red pennant over a ring, the same size on screen at any zoom."""
    if not pos:
        return
    x, y = pos
    s = max(0.6, min(2.6, k * 0.95))
    g.setPen(QPen(QColor(30, 18, 10), 1.1 * s))
    g.setBrush(QColor(236, 222, 184, 220))
    g.drawEllipse(QPointF(x, y), 4.2 * s, 4.2 * s)
    g.setBrush(PARTY)
    g.drawEllipse(QPointF(x, y), 2.0 * s, 2.0 * s)
    g.setPen(QPen(QColor(30, 18, 10), 1.3 * s, Qt.SolidLine, Qt.RoundCap))
    g.drawLine(QPointF(x, y - 2 * s), QPointF(x, y - 20 * s))
    flag = QPainterPath(QPointF(x, y - 20 * s))
    flag.cubicTo(QPointF(x + 5 * s, y - 22 * s), QPointF(x + 8 * s, y - 17 * s), QPointF(x + 13 * s, y - 18 * s))
    flag.lineTo(x + 9 * s, y - 15 * s)
    flag.lineTo(x + 13 * s, y - 12 * s)
    flag.cubicTo(QPointF(x + 8 * s, y - 11 * s), QPointF(x + 5 * s, y - 15 * s), QPointF(x, y - 13 * s))
    flag.closeSubpath()
    g.setPen(QPen(QColor(30, 18, 10), 0.8 * s))
    g.setBrush(PARTY)
    g.drawPath(flag)
    if label:
        halo_text(g, text_path(label, font(11 * k, bold=True), x, y + 16 * k, "center"), QColor(30, 18, 10), halo=3 * k)


def paint_ping(g, p: dict, age: float, k: float, life: float):
    """Rings rippling out from a ping, with who it was."""
    t = max(0.0, min(1.0, age / life))
    for i in range(3):
        tt = t - i * 0.18
        if tt <= 0 or tt >= 1:
            continue
        c = QColor(PING)
        c.setAlphaF(max(0.0, 1 - tt) * 0.95)
        g.setPen(QPen(c, 2.4 * k))
        g.setBrush(Qt.NoBrush)
        g.drawEllipse(QPointF(p["x"], p["y"]), (4 + tt * 34) * k, (4 + tt * 34) * k)
    c = QColor(PING)
    c.setAlphaF(max(0.0, 1 - t))
    g.setPen(QPen(QColor(30, 18, 10), 1.0 * k))
    g.setBrush(c)
    g.drawEllipse(QPointF(p["x"], p["y"]), 3.2 * k, 3.2 * k)
    if p.get("who") and t < 0.85:
        dark = QColor(30, 18, 10)
        dark.setAlphaF(1 - t)
        halo_text(g, text_path(p["who"], font(12 * k, bold=True), p["x"], p["y"] - 9 * k, "center"), dark, halo=3 * k,
                  halo_alpha=int(200 * (1 - t)))


def paint_brush(g, x, y, r, k, mode, rgb=None):
    """The brush's ring under the mouse (rgb: the colour it paints, for the ground and realm brushes)."""
    color = QColor(*rgb) if rgb else {"raise": QColor(74, 222, 128), "lower": QColor(96, 165, 250),
                                      "smooth": QColor(250, 204, 21)}.get(mode, QColor(230, 230, 230))
    g.setBrush(Qt.NoBrush)
    g.setPen(QPen(QColor(0, 0, 0, 140), 3 * k))
    g.drawEllipse(QPointF(x, y), r, r)
    g.setPen(QPen(color, 1.4 * k))
    g.drawEllipse(QPointF(x, y), r, r)
    g.drawEllipse(QPointF(x, y), 1.2 * k, 1.2 * k)

