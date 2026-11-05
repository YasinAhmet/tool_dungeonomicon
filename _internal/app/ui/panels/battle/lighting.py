"""The light on the battle map: while the map is dim or dark (the "Light on the map" rule), darkness over it with each
light source's lit area cut out - a campfire, a torch, a fireplace - and a warm glow in it. Walls, shut doors and
total-cover tiles throw the shadows (services.battle.sight.light_shapes); the players' portal draws the same
(portal.js: drawLight), a little darker, since the DM still has to see the map.

    paint_light(p, drawings, light, bands, fw, h, ox, oy, z, dpr)    # over the drawings, under the tokens

The darkness is drawn once for a zoom into a picture of the map (LAYER_MAX pixels across at most); panning only moves it.
"""
from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPainterPath, QPolygonF, QRadialGradient

from ....services.battle import sight as V

DARK = {"dim": 0.3, "dark": 0.62}                           # how dark the unlit map is, in the editor
NIGHT = QColor(6, 8, 14)
GLOW = QColor(255, 160, 70)
LAYER_MAX = 4096
_layers = {}


def stops(light: str, inner: float) -> list:
    """The light's fall-off, as (where, how much darkness it takes away): bright all the way out to its bright radius;
    on a dark map dim light beyond that, on a dim one nothing more than the map has."""
    if light == "dim":
        return [(0, 1.0), (inner * .8, 1.0), (min(1.0, inner * 1.25), 0.0), (1.0, 0.0)]
    return [(0, 1.0), (inner * .8, 1.0), (inner, .6), (.85, .35), (1.0, 0.0)]


def _layer(shapes: list, light: str, bands: list, fw: int, h: int, k: float) -> QImage:
    x0, x1 = min(bands), max(bands) + fw
    img = QImage(max(1, int((x1 - x0) * k)), max(1, int(h * k)), QImage.Format_ARGB32_Premultiplied)
    night = QColor(NIGHT)
    night.setAlphaF(DARK[light])
    img.fill(night)
    q = QPainter(img)
    q.setRenderHint(QPainter.Antialiasing)
    q.scale(k, k)
    q.translate(-x0, 0)
    q.setPen(Qt.NoPen)
    for s in shapes:
        band = max((b for b in bands if b <= s["x"]), default=x0)   # a light stays on its own floor
        poly = QPolygonF([QPointF(x, y) for x, y in s["poly"]])
        reach = s["bright"] + s["dim"]
        q.save()
        q.setClipRect(QRectF(band, 0, fw, h))
        q.setCompositionMode(QPainter.CompositionMode_DestinationOut)
        g = QRadialGradient(QPointF(s["x"], s["y"]), reach)
        for at, cut in stops(light, s["bright"] / reach):
            g.setColorAt(at, QColor(0, 0, 0, int(255 * cut)))
        q.setBrush(g)
        q.drawPolygon(poly)
        q.setCompositionMode(QPainter.CompositionMode_SourceOver)
        g = QRadialGradient(QPointF(s["x"], s["y"]), reach)  # firelight: warm in the middle, fading out
        for at, a in ((0, 70), (s["bright"] / reach, 30), (1.0, 0)):
            c = QColor(GLOW)
            c.setAlpha(a)
            g.setColorAt(at, c)
        q.setBrush(g)
        q.drawPolygon(poly)
        q.restore()
    q.end()
    return img


def paint_light(p: QPainter, drawings: list, light: str, bands: list, fw: int, h: int, ox: float, oy: float, z: float,
                dpr: float = 1.0):
    """The map's darkness and its lit areas (nothing on a bright map)."""
    if light not in DARK or not bands:
        return
    shapes = V.light_shapes(V.terrain(drawings))
    x0, x1 = min(bands), max(bands) + fw
    k = round(min(z * dpr, LAYER_MAX / max(1, x1 - x0, h)), 3)
    key = (id(shapes), light, tuple(bands), fw, h, k)
    img = _layers.get(key)
    if img is None:
        if len(_layers) > 6:
            _layers.clear()
        img = _layers[key] = _layer(shapes, light, bands, fw, h, k)
        _layers[key, "keep"] = shapes                         # (the id stays this list's while the layer is kept)
    clip = QPainterPath()
    for b in bands:
        clip.addRect(QRectF(ox + b * z, oy, fw * z, h * z))
    p.save()
    p.setClipPath(clip)
    p.setRenderHint(QPainter.SmoothPixmapTransform, True)
    p.drawImage(QRectF(ox + x0 * z, oy, (x1 - x0) * z, h * z), img)
    p.restore()
