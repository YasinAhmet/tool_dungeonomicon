"""Battle effects on the DM's maps: tokens walking tile by tile, hits, misses and crits, areas flashing in the colour of
their damage, numbers rising off the hurt, a slight screen shake - more, with a red edge, when the creature you are
playing gets hurt - and, with async rolling, a player's d20 tumbling in the middle of the screen until it lands.
A spell starts with a casting circle under its caster (bigger for higher slots, coloured by where its magic comes from);
motes rise off a heal, burst off a hit; a token leans into its melee swing, flinches when hit, fades out and in when it
teleports. A condition's icon pops over the creature that gets it and flies into a row of badges over its token; one
that ends lifts off and fades. Bless, Rage, Hunter's Mark and Hex have badges too, which blink when they change a number
(the number rises beside them, and joins the d20 on screen as a chip). docs/vfx-catalog.md has the whole picture.
The battle lists what happened in b['fx'] (BattleBase._vfx); the portal plays the same list."""
import math
import random
import time

from PySide6.QtCore import QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QFontMetrics, QLinearGradient, QPainterPath, QPen, QPixmap, QPolygonF, QRadialGradient

from ....core.i18n import tr
from ....services.battle import icons

DAMAGE = {"acid": "#a3e635", "bludgeoning": "#d6c3a1", "cold": "#7dd3fc", "fire": "#ff7a1a", "force": "#e879f9",
          "lightning": "#fde047", "necrotic": "#8fa85a", "piercing": "#e5e7eb", "poison": "#4ade80", "psychic": "#f472b6",
          "radiant": "#fff3b0", "slashing": "#f87171", "thunder": "#60a5fa"}
HIT, MISS, CRIT, MAGIC, HEAL, SAVED, FAILED, DOWN = ("#f87171", "#9aa3b2", "#fbbf24", "#a78bfa", "#5eead4", "#93c5fd",
                                                     "#f87171", "#7f1d1d")
LEGENDARY = "#f59e0b"
BANNER = {"start": "#fbbf24", "round": "#e6e9ef", "victory": "#fcd34d", "end": "#9aa3b2", "mine": "#fbbf24"}   # text colour by tone
SOURCE = {"arcane": MAGIC, "divine": "#fcd34d", "primal": "#86efac", "ki": "#bae6fd", "martial": "#cbd5e1", "fury": "#ef4444",
          "song": "#f9a8d4"}                                  # where a power comes from, when it isn't a damage type
GATHER = (.15, .25, .35, .45)                                 # seconds a casting circle shows before its spell goes, by tier
BADGE, BADGE_GAP, BADGE_MAX = .16, .36, 3                     # condition badges over a token: radius, spacing (tiles), how many
BLINK = .45                                                   # seconds a badge blinks when its effect changes a number
STEP = 0.085                                                  # seconds per tile walked: quick, but you see the way taken
BURSTS = ("sphere", "cylinder", "cube", "square", "emanation", "burst")
SHATTER = {"potion_orange": "#ff7a1a", "potion_green": "#a3e635", "potion_white": "#e0f2fe", "potion_brown": "#a16207"}   # a broken flask's splash
LOBBED = ("fire", "acid", "cold", "poison")                   # bursts of these arc over as a bead; sound and energy just go off there
DECAL = {"fire": ("#1c1008", .42), "cold": ("#dbeafe", .16), "acid": ("#84cc16", .16), "poison": ("#4ade80", .1)}   # left on the floor
REVEAL = 0.8                                                  # the landed die and its total stay up this long
GOOD = {"hit": "#4ade80", "saved": "#4ade80", "success": "#4ade80", "back up": "#fbbf24", "crit": "#fbbf24"}
OUTCOME = {"crit": "Critical hit!", "hit": "Hit", "miss": "Miss", "saved": "Saved", "failed": "Failed", "success": "Success",
           "failure": "Failure", "two failures": "Two failures", "back up": "Natural 20: back up with 1 HP"}


def tint(dtype: str, default: str = HIT) -> str:
    return DAMAGE.get((dtype or "").lower(), default)


# a damage number's look by its type: how far it rises (tiles; below 0 it sinks), a glow, an outline, doubles beside it
NUM_LOOK = {"fire": {"rise": .8, "glow": "#ff5a00"}, "cold": {"rise": .4, "edge": "#f0f9ff"}, "lightning": {"rise": .7, "glow": "#fef08a"},
            "acid": {"rise": .25}, "poison": {"rise": .5}, "necrotic": {"rise": -.3}, "radiant": {"rise": .8, "glow": "#fffbe6"},
            "thunder": {"rise": .5}, "force": {"rise": .6, "edge": "#fae8ff"}, "psychic": {"rise": .6, "ghosts": True},
            "bludgeoning": {"rise": .35}, "piercing": {"rise": 1.0}, "slashing": {"rise": .6}}
NUM_SPARKS = {"fire": ("#ff7a1a", 6, "rise", .3, .035), "cold": ("#e0f2fe", 6, "fall", .35, .03),    # embers, frost flakes, drips
              "acid": ("#a3e635", 4, "fall", .25, .035)}


def _noise(k: int, j: int) -> float:
    """-1..1, always the same for the same (k, j): the damage numbers' jitter (portal.js has the same)."""
    v = math.sin(k * 12.9898 + j * 78.233) * 43758.5453
    return (v - math.floor(v)) * 2 - 1


def mix(a: str, b: str, k: float) -> str:
    ca, cb = QColor(a), QColor(b)
    return QColor(*(round(x + (y - x) * k) for x, y in zip(ca.getRgb()[:3], cb.getRgb()[:3]))).name()


def num_glyph(dtype: str, u: float, s: float, j: int, n: int):
    """How the j-th of n characters of a damage number sits u (0..1) into its life, s seconds in: offset (tiles), scale,
    turn (degrees), colour and alpha. Each damage type moves its own way; numGlyph in portal.js is the twin."""
    col = tint(dtype)
    dx = dy = rot = 0.0
    sx = sy = a = 1.0
    if dtype == "fire":                         # burning: the digits lick upward and flicker through the flame colours
        dy = math.sin(s * 15 + j * 1.7) * .035 - abs(_noise(int(s * 18), j)) * .03
        sy = 1 + .1 * abs(math.sin(s * 11 + j * 2.1))
        f = _noise(int(s * 14), j + 7)
        col = "#fde047" if f > .45 else "#ef4444" if f < -.55 else col
    elif dtype == "cold":                       # shivering: quick little shakes, calming as it fades
        k, amp = int(s * 32), .045 * (1 - .6 * u)
        dx, dy, rot = _noise(k, j) * amp, _noise(k, j + 31) * amp * .5, _noise(k, j + 63) * 6 * (1 - .6 * u)
    elif dtype == "lightning":                  # crackling: the number jumps about and flashes white
        k = int(s * 20)
        dx, dy = _noise(k, 0) * .05, _noise(k, 1) * .05
        col = "#ffffff" if _noise(k, 2) > .3 else col
    elif dtype == "acid":                       # melting: the digits sag and drip down, one after another
        v = max(0.0, u - .15 * j / max(1, n))
        dy, sy = v * v * .35 * (1 + .5 * _noise(j, 5)), 1 + .5 * v
    elif dtype == "poison":                     # a sickly sway, the colour throbbing
        dx, rot = math.sin(s * 7 + j * .9) * .05, math.sin(s * 7 + j * .9 + 1) * 8
        a = .75 + .25 * math.sin(s * 9)
    elif dtype == "necrotic":                   # it sinks, darkening, the digits drifting apart
        dx, a, col = (j - (n - 1) / 2) * .05 * u, 1 - .2 * u, mix(col, "#1a1f12", u * .4)
    elif dtype == "radiant":                    # a slow bright swell
        sx = sy = 1 + .15 * math.sin(math.pi * min(1.0, u * 1.5))
    elif dtype == "thunder":                    # a boom: big at once, snapping back, the shudder dying out
        b = max(0.0, 1 - u / .25)
        sx = sy = 1 + .7 * b * b
        dx = math.sin(s * 60) * .04 * b
    elif dtype == "force":                      # popped out, settling with a wobble
        sx = sy = 1 + .35 * math.exp(-u * 9) * math.cos(u * 40)
    elif dtype == "psychic":                    # the digits tilt and drift as if unreal (the painter adds the doubles)
        rot, dy = math.sin(s * 5 + j) * 10, math.sin(s * 6 + j * 1.4) * .03
    elif dtype == "bludgeoning":                # slammed down from above, squashing flat, springing back
        dy = -.35 * (1 - min(1.0, u / .15)) ** 2
        sq = max(0.0, 1 - abs(u - .17) / .08)
        sx, sy = 1 + .35 * sq, 1 - .35 * sq
    elif dtype == "piercing":                   # shot up fast, thin and tall at first
        b = max(0.0, 1 - u / .3)
        sx, sy = 1 - .3 * b, 1 + .4 * b
    elif dtype == "slashing":                   # slid in from the side, slanted along the cut
        d = 1 - min(1.0, u / .18)
        dx, rot = -.3 * d * d * (1 + j * .3), -12 * d - 4
    return dx, dy, sx, sy, rot, col, a


def colour(hexa: str, alpha: float) -> QColor:
    c = QColor(hexa)
    c.setAlphaF(max(0.0, min(1.0, alpha)))
    return c


_pictures = {}


def picture(slug: str):
    """An icon (white on transparent, the icon modules), or None."""
    if slug not in _pictures:
        path = icons.path(slug)
        _pictures[slug] = QPixmap(path) if path else None
    return _pictures[slug]


def badges(c: dict) -> list:
    """The badges a token shows: its conditions and effects with a badge (Bless, Rage...), or the first ones and '+N'
    when there are more than fit."""
    shown = icons.badge_keys(c.get("conditions"), c.get("effects"))
    return shown if len(shown) <= BADGE_MAX else shown[:BADGE_MAX - 1] + [f"+{len(shown) - BADGE_MAX + 1}"]


def badge_slot(cx: float, top: float, i: int, n: int, z: float):
    """Where badge i of n sits (pixels): in a row over the token's top edge, centred on it. (x, y, radius)"""
    r = max(7.0, BADGE * z)
    gap = max(2 * r + 2, BADGE_GAP * z)
    return cx + (i - (n - 1) / 2) * gap, top - r - 1, r              # just over the edge: the hit point bar stays clear


def paint_badge(p, x: float, y: float, r: float, name: str, font: QFont, alpha: float = 1.0):
    """One badge: a dark disc ringed in the condition's (or effect's) colour with its icon (or '+N')."""
    slug, col = icons.BADGES.get(name, (None, "#9aa3b2"))
    c = QPointF(x, y)
    p.setPen(QPen(colour(col, alpha), max(1.2, r * .16)))
    p.setBrush(QColor(11, 13, 18, int(220 * alpha)))
    p.drawEllipse(c, r, r)
    p.setBrush(Qt.NoBrush)
    pm = picture(slug) if slug else None
    if pm:
        o = p.opacity()
        p.setOpacity(o * alpha)
        p.drawPixmap(QRectF(x - r * .68, y - r * .68, r * 1.36, r * 1.36), pm, QRectF(pm.rect()))
        p.setOpacity(o)
    else:
        f = QFont(font)
        f.setBold(True)
        f.setPixelSize(int(max(8, r * .95)))
        p.setFont(f)
        p.setPen(colour("#e6e9ef", alpha))
        p.drawText(QRectF(x - r, y - r, 2 * r, 2 * r), Qt.AlignCenter, name)


# lasting areas: a colour per family (and kind), the damage type's for the ones that hurt by it
ZONE_COL = {"fire": "#ff7a1a", "cloud:fog": "#c8d2e6", "cloud:poison": "#a3e635", "cloud:smoke": "#9ca3af", "cloud:sleet": "#dbeafe",
            "dark": "#05060a", "light": "#fde047", "tangle:web": "#e7e5e4", "tangle:vine": "#65a30d", "tangle:thorn": "#84cc16",
            "tangle:grease": "#57534e", "tangle:earth": "#d6c3a1", "whirl:daggers": "#e5e7eb", "whirl:insects": "#57534e",
            "whirl:wind": "#e5e7eb", "whirl:storm": "#60a5fa", "wall:stone": "#9ca3af", "wall:ice": "#bae6fd", "wall:force": "#67e8f9",
            "wall:wind": "#e5e7eb", "wall:water": "#38bdf8", "wall:sand": "#d6c3a1", "beam:moon": "#e0f2fe", "beam:sick": "#bef264",
            "beam:sun": "#fff3b0", "help": "#5eead4", "dome": "#93c5fd", "silence": "#94a3b8", "illusion": "#c4b5fd", "arrows": "#d6c3a1",
            "area": "#7c8cff"}


def zone_colour(fam: str, sub: str = "", dtype: str = "") -> str:
    if dtype and fam in ("whirl", "beam") and sub in ("spirits", "", "storm") and dtype in DAMAGE:
        return DAMAGE[dtype]
    return ZONE_COL.get(f"{fam}:{sub}") or ZONE_COL.get(fam) or ZONE_COL.get(next((k for k in ZONE_COL if k.startswith(fam + ":")), ""), ZONE_COL["area"])


def _rnd(x: int, y: int, k: int, seed: int) -> float:
    """A fixed 'random' number in [0, 1) for a tile: the same texture every time the map is drawn."""
    v = math.sin(x * 12.9898 + y * 78.233 + k * 37.719 + seed * .137) * 43758.5453
    return v - math.floor(v)


def paint_zone(p, zone: dict, tiles, ox, oy, z, alpha: float = 1.0):
    """A lasting area on the map, under the tokens: its family's colour, a still texture that says what it is (embers,
    cloud, strands, blades, stone...), and a crisp outline. Nothing in it moves: an idle map isn't redrawn."""
    fam, sub, zid = zone.get("family") or "area", zone.get("kind") or "", int(zone.get("id") or 0)
    col = zone_colour(fam, sub, zone.get("dtype") or "")
    base = {"dark": .6, "wall": .5, "fire": .2, "cloud": .14, "light": .1, "beam": .12, "help": .12, "silence": .16, "illusion": .08,
            "dome": .07}.get(fam, .12)
    p.setPen(Qt.NoPen)
    p.setBrush(colour(col, base * alpha))
    area = QPainterPath()
    area.setFillRule(Qt.WindingFill)
    for x, y in tiles:
        p.drawRect(QRectF(ox + x * z, oy + y * z, z, z))
        area.addRect(QRectF(ox + x * z, oy + y * z, z, z))
    p.save()
    p.setClipPath(area, Qt.IntersectClip)                    # the glow and the texture stay inside its tiles: no bigger than it is
    if fam in ("light", "beam") and tiles:                   # a glow from its middle
        cx, cy = sum(t[0] for t in tiles) / len(tiles) + .5, sum(t[1] for t in tiles) / len(tiles) + .5
        R = max(1.0, max(math.hypot(x + .5 - cx, y + .5 - cy) for x, y in tiles) + .5) * z
        g = QRadialGradient(QPointF(ox + cx * z, oy + cy * z), R)
        g.setColorAt(0, colour(col, (.35 if fam == "beam" else .22) * alpha))
        g.setColorAt(1, colour(col, 0))
        p.setBrush(g)
        p.drawEllipse(QPointF(ox + cx * z, oy + cy * z), R, R)
    pt = lambda x, y: QPointF(ox + x * z, oy + y * z)  # noqa: E731
    for x, y in tiles:                                       # the texture, tile by tile
        r = lambda k: _rnd(x, y, k, zid)  # noqa: E731
        if fam == "fire":                                    # embers
            for k in range(3):
                p.setBrush(colour("#fde047" if k % 2 else col, .7 * alpha))
                p.drawEllipse(pt(x + .15 + .7 * r(k), y + .15 + .7 * r(k + 9)), z * (.04 + .04 * r(k + 3)), z * (.04 + .04 * r(k + 3)))
        elif fam in ("cloud", "dark"):                       # soft overlapping blobs
            p.setBrush(colour(col if fam == "cloud" else "#4c1d95", (.13 if fam == "cloud" else .1) * alpha))
            for k in range(2):
                rr = z * (.42 + .25 * r(k + 5))
                p.drawEllipse(pt(x + .2 + .6 * r(k), y + .2 + .6 * r(k + 7)), rr, rr)
        elif fam in ("help", "arrows") or (fam == "tangle" and sub == "earth"):
            p.setBrush(colour(col, .6 * alpha))
            for k in range(2):
                p.drawEllipse(pt(x + .2 + .6 * r(k), y + .2 + .6 * r(k + 4)), z * .035, z * .035)
        p.setBrush(Qt.NoBrush)
        if fam == "tangle" and sub in ("web", "vine", "thorn", "grease"):
            p.setPen(QPen(colour(col, (.25 if sub == "grease" else .55) * alpha), max(1.0, z * (.02 if sub == "web" else .03)), Qt.SolidLine, Qt.RoundCap))
            for k in range(3 if sub in ("web", "thorn") else 2):
                a, mx, my = math.pi * r(k), x + .5 + (r(k + 3) - .5) * .4, y + .5 + (r(k + 6) - .5) * .4
                L = .5 if sub == "web" else .12 if sub == "thorn" else .3
                if sub == "vine":                            # curls
                    p.drawArc(QRectF(ox + (mx - .25) * z, oy + (my - .25) * z, z * .5, z * .5), int(math.degrees(a) * 16), 200 * 16)
                else:
                    p.drawLine(pt(mx - math.cos(a) * L, my - math.sin(a) * L), pt(mx + math.cos(a) * L, my + math.sin(a) * L))
            p.setPen(Qt.NoPen)
        elif fam == "whirl":                                 # blades glinting, insects swarming
            p.setPen(QPen(colour(col, .75 * alpha), max(1.0, z * (.025 if sub != "insects" else .05)), Qt.SolidLine, Qt.RoundCap))
            for k in range(3 if sub != "insects" else 5):
                a, mx, my = 2 * math.pi * r(k), x + .15 + .7 * r(k + 3), y + .15 + .7 * r(k + 6)
                L = .1 if sub != "insects" else .01
                p.drawLine(pt(mx - math.cos(a) * L, my - math.sin(a) * L), pt(mx + math.cos(a) * L, my + math.sin(a) * L))
            p.setPen(Qt.NoPen)
        elif fam == "wall":                                  # its material: block joints, ice glints, wind streaks
            p.setPen(QPen(colour("#0b0d12" if sub in ("stone", "sand") else "#ffffff", .3 * alpha), max(1.0, z * .02)))
            if sub in ("stone", "sand"):
                p.drawLine(pt(x, y + .5), pt(x + 1, y + .5))
                p.drawLine(pt(x + (.3 if y % 2 else .7), y), pt(x + (.3 if y % 2 else .7), y + .5))
            elif sub in ("ice", "water", "wind"):
                p.drawLine(pt(x + .2, y + .8), pt(x + .5, y + .2))
            p.setPen(Qt.NoPen)
    p.restore()
    have = {(round(x), round(y)) for x, y in tiles}          # the outline: every edge with no tile of the area beyond it
    pen = QPen(colour("#7c3aed" if fam == "dark" else col, .75 * alpha), max(1.5, z * .04))
    if fam in ("illusion", "dome"):
        pen.setStyle(Qt.DashLine)
    p.setPen(pen)
    for x, y in tiles:                                       # where the tiles are drawn (a gliding area: between tiles)
        for dx, dy, a, b in ((0, -1, (0, 0), (1, 0)), (0, 1, (0, 1), (1, 1)), (-1, 0, (0, 0), (0, 1)), (1, 0, (1, 0), (1, 1))):
            if (round(x + dx), round(y + dy)) not in have:
                p.drawLine(pt(x + a[0], y + a[1]), pt(x + b[0], y + b[1]))
    p.setPen(Qt.NoPen)
    p.setBrush(Qt.NoBrush)


class Fx:
    def __init__(self, canvas):
        self.w = canvas
        self.seen = None                                     # the last fx number played (None: not started - skip the past)
        self.items = []                                      # {'t0', 'dur', 'kind', ...} drawn while they last
        self.moves = {}                                      # combatant id -> [(t0, dur, from, to)] steps still to show
        self.poses = {}                                      # combatant id -> [(t0, dur, ease, dx, dy, scale, opacity)] (_pose)
        self.landing = {}                                    # (combatant id, condition) -> when its popped icon reaches its badge
        self.blinks = {}                                     # (combatant id, effect) -> when its badge blinks (it changed a number)
        self.zone_moves = {}                                 # zone id -> (t0, dur, dx, dy): a moved area gliding to its new place
        self.flying = {}                                     # ('gid' | 'did', id) -> when a thrown item (prop) lands: hidden till then
        self.shakes = []                                     # (t0, dur, amplitude in px)
        self.red = None                                      # when the red edge started
        self.clock = 0.0                                     # when the effects already queued are over
        self.prev = {}                                       # where each token was shown last
        self.mine = lambda: set()                            # ids whose hurt shakes harder and reddens the edge
        self.paint_token = None                              # (painter, combatant, QRectF, picture px): a token (a leaving one shrinks)
        self.bodies, self.old = {}, {}                       # the creatures now, and on the screen before (one that just left)
        self.timer = QTimer(canvas)
        self.timer.setInterval(16)
        self.timer.timeout.connect(self._tick)

    # ------------------------------------------------------------------ queueing
    def feed(self, v: dict):
        n = int(v.get("fx_n") or 0)
        bodies = {c["id"]: c for c in v.get("combatants") or []}
        if self.seen is None or n < self.seen:               # a new screen or an undone battle: nothing old replays
            self.seen = n
            self.prev = {i: list(c["pos"]) for i, c in bodies.items() if c.get("pos")}
            self.bodies = bodies
            return
        new = [f for f in v.get("fx") or [] if f.get("n", 0) > self.seen]
        self.seen = n
        now = time.monotonic()
        t = max(now, self.clock)
        if t - now > 1.5:                                    # never lag far behind the battle
            t = now
        self.where = dict(self.prev)
        self.old, self.bodies = self.bodies, bodies
        for f in new:
            try:
                t = self._queue(f, t)
            except (KeyError, TypeError, ValueError, IndexError):
                continue                                     # a malformed or unknown effect is just not shown
        self.clock = t
        self.prev = {i: list(c["pos"]) for i, c in bodies.items() if c.get("pos")}
        if new:
            self.timer.start()

    def _centre(self, cid):
        c = self.bodies.get(cid)
        p = self.where.get(cid) or (c or {}).get("pos")
        if not p:
            return None
        s = max(1, int((c or {}).get("span") or 1))
        return (p[0] + s / 2, p[1] + s / 2)

    def _tiles(self, cid):
        c = self.bodies.get(cid)
        p = self.where.get(cid) or (c or {}).get("pos")
        if not p:
            return []
        s = max(1, int((c or {}).get("span") or 1))
        return [(p[0] + i, p[1] + j) for i in range(s) for j in range(s)]

    def _add(self, kind: str, t0: float, dur: float, **kw):
        self.items.append(dict(kind=kind, t0=t0, dur=dur, **kw))

    def _shake(self, t0: float, amp: float, dur: float = .28):
        self.shakes.append((t0, dur, amp))

    def _pose(self, cid, t0: float, dur: float, ease: str, dx=0.0, dy=0.0, k=0.0, a=0.0):
        """Draw a token off its place for a while: moved by (dx, dy) tiles, scaled by 1 + k, opacity 1 + a. `ease`:
        'bump' there and back, 'to' going there, 'from' coming back from there, 'in' the same but already there
        until it starts (a summoned creature stays unseen until it pops in)."""
        self.poses.setdefault(cid, []).append((t0, dur, ease, dx, dy, k, a))

    def _motes(self, t0: float, dur: float, at, col: str, n: int, mode: str, spread: float, size: float = .055, arc=None):
        """Small glowing dots around a point (tile units): 'rise' (good things), 'fall' (bad things), 'burst' (an impact),
        'inward' (gathering), 'orbit' (a swirl), each on its own path and a little late or early. `arc` (angle, half
        width): only that way (a cone)."""
        lo, hi = (arc[0] - arc[1], arc[0] + arc[1]) if arc else (0, 2 * math.pi)
        dots = [(random.uniform(lo, hi), random.uniform(.25, 1), random.uniform(0, .3), random.uniform(.75, 1.25))
                for _ in range(n)]
        self._add("motes", t0, dur, at=at, col=col, mode=mode, spread=spread, size=size, dots=dots)

    def _decal(self, t0: float, tiles, dtype: str):
        """What an area leaves on the floor for a few seconds: scorch, rime, an acid sheen (by its damage type)."""
        if dtype in DECAL:
            self._add("decal", t0, 3.0, cells=[tuple(x) for x in tiles], col=DECAL[dtype][0], peak=DECAL[dtype][1])

    def _puff(self, t0: float, at, col: str, r: float):
        """A soft cloud swelling and thinning out (tile units): hides a creature arriving or leaving."""
        blobs = [(random.uniform(-1, 1), random.uniform(-.8, .8), random.uniform(.7, 1.2)) for _ in range(7)]
        self._add("puff", t0, .6, at=at, col=col, r=r, blobs=blobs)

    def _crack(self, t0: float, at, col: str, size: float):
        """Jagged cracks running out over the floor from a point, glowing in a colour (fiends, undead coming up)."""
        lines = []
        for j in range(6):
            a, pts = 2 * math.pi * j / 6 + random.uniform(-.3, .3), [(at[0], at[1])]
            r = .12 * size
            for _ in range(4):
                a += random.uniform(-.55, .55)
                r += .17 * size
                pts.append((at[0] + math.cos(a) * r, at[1] + math.sin(a) * r))
            lines.append(pts)
        self._add("crack", t0, 1.0, col=col, lines=lines)

    def _summon_twist(self, kind: str, T, s: int, t: float, col: str, name: str):
        """What a summoning circle brings with it, by the kind of creature arriving (not by spell): one look per kind."""
        r = s / 2 + .2
        if kind == "celestial":                              # a light from above, feathers of light drifting down
            self._add("column", t + .05, .7, at=T, r=r, col="#fff3b0")
            self._motes(t + .15, .9, T, "#fcd34d", 10, "fall", r)
        elif kind == "fiend":                                # the floor cracks red, embers, brimstone smoke
            self._crack(t, T, "#ef4444", s)
            self._motes(t + .2, .7, T, "#ff7a1a", 12, "rise", r)
            self._puff(t + .2, T, "#57534e", s * .7)
        elif kind == "undead":                               # the floor cracks, sickly motes, it climbs out (its pose)
            self._crack(t, T, "#8fa85a", s)
            self._motes(t + .2, .8, T, "#8fa85a", 10, "rise", r)
        elif kind == "elemental":                            # a swirl of its element (the name tells which)
            low = name.lower()
            elem = next((c for w, c in (("fire", DAMAGE["fire"]), ("water", "#38bdf8"), ("earth", "#d6c3a1"), ("air", "#e5e7eb"),
                                        ("ice", DAMAGE["cold"])) if w in low), "#5eead4")
            self._motes(t, .8, T, elem, 14, "orbit", r)
        elif kind == "fey":                                  # petals spiralling
            self._motes(t, .8, T, "#f9a8d4", 8, "orbit", r)
            self._motes(t + .05, .8, T, "#86efac", 6, "orbit", r * .8)
        elif kind in ("beast", "plant"):                     # leaves bursting off it
            self._motes(t + .25, .6, T, "#86efac", 10, "burst", r + .2)
        elif kind == "construct":                            # sparks gathering into it, then a flash of them
            self._motes(t, .4, T, "#7dd3fc", 12, "inward", r + .3)
            self._motes(t + .3, .4, T, "#e0f2fe", 8, "burst", r)
        elif kind == "aberration":                           # a rift opening, things drawn into it
            self._add("ring", t, .5, at=T, col="#a78bfa", r0=.1, r1=r + .1, width=3)
            self._motes(t, .5, T, "#c084fc", 10, "inward", r + .2)
        elif kind == "dragon":                               # a gust of wings pushing the dust out
            self._add("ring", t + .25, .45, at=T, col="#e5e7eb", r0=s / 2, r1=s / 2 + .8, width=3)
            self._motes(t + .25, .5, T, "#d6c3a1", 12, "burst", r + .5)
        else:                                                # a conjured thing, anything else: its magic gathers
            self._motes(t, .4, T, col, 10, "inward", r + .2)

    def _zone_fx(self, f: dict, t: float) -> float:
        """A lasting area's moments: it spreads out from its middle as it appears; it flares under whoever it strikes, in
        its own way (embers rise, a cloud billows, strands tighten, blades glint); it ends its own way; moved, it glides."""
        fam, sub, op = f.get("fam") or "area", f.get("sub") or "", f.get("op")
        col = zone_colour(fam, sub, f.get("dtype") or "")
        if op == "move":
            d = f.get("d") or [0, 0]
            self.zone_moves[f["zid"]] = (t, .3, float(d[0]), float(d[1]))
            return t + .05
        if op == "hit":
            for cid in f.get("ids") or []:
                T = self._centre(cid)
                if not T:
                    continue
                self._add("flash", t, .4, tiles=[(x, y, 0) for x, y in self._tiles(cid)], col=col, peak=.5)
                if fam in ("fire", "help", "light"):
                    self._motes(t, .6, T, col, 8, "rise", .4)
                elif fam in ("cloud", "dark"):
                    self._puff(t, T, col if fam == "cloud" else "#4c1d95", .5)
                elif fam == "tangle":                        # strands drawing tight around it
                    self._motes(t, .4, T, col, 8, "inward", .7)
                elif fam == "beam":
                    self._add("column", t, .45, at=T, r=.5, col=col)
                else:
                    self._motes(t, .4, T, col, 8, "burst", .55)
            return t + .05
        tiles = [tuple(x) for x in f.get("tiles") or []]
        if not tiles:
            return t
        mid = (sum(x for x, _ in tiles) / len(tiles) + .5, sum(y for _, y in tiles) / len(tiles) + .5)
        far = max(math.hypot(x + .5 - mid[0], y + .5 - mid[1]) for x, y in tiles)
        if op == "on":                                       # it spreads out from its middle
            self._add("flash", t, .5, tiles=[(x, y, math.hypot(x + .5 - mid[0], y + .5 - mid[1]) * .03) for x, y in tiles], col=col, peak=.45)
            self._add("ring", t, .35 + far * .03, at=mid, col=col, r0=.2, r1=far + .3, width=3)
            return t + .1
        self._add("flash", t, .6, tiles=[(x, y, 0) for x, y in tiles], col=col, peak=.3)   # 'off': its own way of going
        spread = min(far + .3, 4.0)
        if fam in ("fire", "help", "light", "beam"):
            self._motes(t, .8, mid, col, 14, "rise", spread)
        elif fam in ("cloud", "dark", "silence", "illusion"):
            self._puff(t, mid, col if fam != "dark" else "#4c1d95", spread * .8)
        else:                                                # walls crumble, strands snap, blades scatter
            self._motes(t, .6, mid, col, 16, "burst", spread)
        return t + .1

    def _death(self, kind: str, T, tiles, t: float, name: str):
        """How a creature falls, by what it is: the living bleed, the undead crumble, constructs spark apart, elementals
        come undone into their element, oozes splat, fiends burn away, celestials and fey turn to light."""
        if kind == "undead":
            self._motes(t, .8, T, "#9ca3af", 12, "fall", .45)
            self._puff(t + .1, T, "#9ca3af", .6)
        elif kind == "construct":
            self._motes(t, .5, T, "#e0f2fe", 12, "burst", .8)
            self._shake(t, 2)
        elif kind == "elemental":
            low = name.lower()
            elem = next((c for w, c in (("fire", DAMAGE["fire"]), ("water", "#38bdf8"), ("earth", "#d6c3a1"), ("air", "#e5e7eb"),
                                        ("ice", DAMAGE["cold"])) if w in low), "#5eead4")
            self._motes(t, .8, T, elem, 14, "burst", 1.0)
        elif kind == "ooze":
            self._add("decal", t, 3.0, cells=[(x, y) for x, y in tiles], col="#65a30d", peak=.3)
        elif kind == "fiend":
            self._motes(t, .8, T, DAMAGE["fire"], 12, "rise", .45)
        elif kind in ("celestial", "fey"):
            self._motes(t, .9, T, "#fcd34d" if kind == "celestial" else "#f9a8d4", 12, "rise", .45)
        else:                                                # beasts, humanoids, giants, monstrosities, dragons...: blood
            self._add("decal", t, 3.0, cells=[(x, y) for x, y in tiles], col="#7f1d1d", peak=.32)

    @staticmethod
    def pip_spots(px: float, py: float, s: float, least: float = 2.5):
        """Where a dying creature's six death save pips sit (on its token's bottom edge): three successes, a gap, three
        failures; and their radius. In pixels (at least `least` px), or in tiles with least=0."""
        r = max(least, s * .05)
        gap = r * 2.7
        return [(px + s * .42 + (i - 2.5) * gap + (r * .6 if i >= 3 else -r * .6), py + s - r * 1.8) for i in range(6)], r

    @classmethod
    def paint_pips(cls, p, c: dict, px: float, py: float, s: float):
        """A dying character's death saves (map.py, over its token): green pips for successes, red for failures."""
        ds = c.get("dsaves")
        if not ds:
            return
        spots, r = cls.pip_spots(px, py, s)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(11, 13, 18, 200))
        p.drawRoundedRect(QRectF(spots[0][0] - r * 1.6, spots[0][1] - r * 1.6, spots[5][0] - spots[0][0] + r * 3.2, r * 3.2), r * 1.6, r * 1.6)
        for i, (x, y) in enumerate(spots):
            col = "#4ade80" if i < 3 else "#f87171"
            done = ds[0] > i if i < 3 else ds[1] > i - 3
            p.setPen(QPen(QColor(col), max(1.0, r * .35)))
            p.setBrush(QColor(col) if done else Qt.NoBrush)
            p.drawEllipse(QPointF(x, y), r, r)
        p.setPen(Qt.NoPen)
        p.setBrush(Qt.NoBrush)

    def _dsave(self, f: dict, t: float) -> float:
        T = self._centre(f["id"])
        c = self.bodies.get(f["id"]) or {}
        if not T or not c.get("pos"):
            return t
        span = max(1, int(c.get("span") or 1))
        s_, f_, nat = int(f.get("s") or 0), int(f.get("f") or 0), f.get("nat")
        if nat == 20 or f.get("up"):                         # back on its feet
            self._motes(t, .7, T, CRIT, 14, "burst", .9)
            self._add("ring", t, .5, at=T, col=CRIT, r0=.2, r1=span / 2 + .5, width=4)
            self._add("text", t, 1.1, at=(T[0], T[1] - .2), text=tr("back up!"), col=CRIT, size=.34)
            return t + .15
        if f_ >= 3:                                          # dead: a pale wisp rises and is gone
            self._motes(t, 1.2, T, "#e5e7eb", 12, "rise", .3)
            self._add("text", t, 1.3, at=(T[0], T[1] - .1), text=tr("dead"), col="#e5e7eb", size=.34, rise=.4)
            return t + .2
        if s_ >= 3:                                          # stable: a heartbeat drawn over it
            self._add("ecg", t, 1.0, at=(T[0], c["pos"][1] - .15), w=span * .8, col=HEAL)
            self._add("text", t + .2, 1.0, at=(T[0], T[1] + .3), text=tr("stable"), col=HEAL, size=.3)
            return t + .15
        failed = f.get("hit") or (nat is not None and nat < 10)
        idx = [3 + f_ - 1] if failed else [s_ - 1]
        if nat == 1 and f_ >= 2:
            idx.append(3 + f_ - 2)
        spots, _r = self.pip_spots(c["pos"][0], c["pos"][1], span, 0)
        for i in idx:
            if 0 <= i < 6:
                self._add("ring", t, .45, at=spots[i], col="#f87171" if i >= 3 else "#4ade80", r0=.03, r1=.28, width=3)
        if f.get("hit"):
            self._shake(t, 2)
        return t + .1

    def zone_offset(self, zid):
        """(dx, dy) tiles a moved area is still drawn back from where it now is (it glides there), or None."""
        mv = self.zone_moves.get(zid)
        if not mv:
            return None
        t0, dur, dx, dy = mv
        u = (time.monotonic() - t0) / dur
        if u >= 1:
            del self.zone_moves[zid]
            return None
        u = max(0.0, u)
        k = 1 - u * u * (3 - 2 * u)
        return -dx * k, -dy * k

    def _feature_fx(self, f: dict, t: float) -> float:
        """A class feature or a standard action: its name under the creature, then a look made of the usual pieces in
        the colour of where it comes from (steel for a fighter's grit, ember for rage, sky for ki, gold for the divine,
        rose for a bard). Healing and damage they cause play by themselves after this."""
        C = self._centre(f["id"])
        if not C:
            return t
        s = max(1, int((self.bodies.get(f["id"]) or {}).get("span") or 1))
        O = self._centre(f.get("other"))
        key = f.get("key") or ""
        self._add("text", t, 1.0, at=(C[0], C[1] + s / 2 + .2), text=tr(f.get("name") or ""), col="#e6e9ef", size=.24, rise=.2)
        r = s / 2
        steel, ki, gold, song, fury = SOURCE["martial"], SOURCE["ki"], SOURCE["divine"], SOURCE["song"], SOURCE["fury"]
        if key == "second_wind":                             # a breath drawn in, then the heal
            self._add("ring", t, .4, at=C, col=steel, r0=r + .6, r1=r * .6, width=3)
            self._motes(t, .4, C, steel, 10, "inward", r + .7)
            return t + .3
        if key == "action_surge":                            # a surge: a crackling burst, gold-white
            self._add("ring", t, .4, at=C, col="#fde68a", r0=r, r1=r + .7, width=4)
            self._motes(t, .5, C, "#fde68a", 14, "burst", r + .6)
            self._shake(t, 2)
        elif key == "rage":                                  # a roar: an ember nova, the ground trembles
            self._add("ring", t, .5, at=C, col=fury, r0=r, r1=r + 1.4, width=5)
            self._motes(t, .6, C, fury, 16, "burst", r + .8)
            self._shake(t, 4)
        elif key == "reckless":                              # all guard dropped: red slashes across itself
            self._add("slash", t, .3, at=C, col=fury, big=True)
            self._add("slash", t + .08, .3, at=C, col=fury, big=True, flip=True)
        elif key in ("cunning_dash", "step_of_the_wind", "dash", "charge"):     # a burst of speed: wind streaks off it
            self._motes(t, .45, C, ki if key == "step_of_the_wind" else "#e5e7eb", 12, "burst", r + .7)
            self._add("ring", t, .35, at=C, col="#d6c3a1", r0=r * .8, r1=r + .3, width=2)
        elif key in ("cunning_disengage", "disengage", "cunning_hide", "hide"):   # it slips away: a little smoke
            self._puff(t, C, "#9ca3af", s * .5)
        elif key == "steady_aim" or key == "ready":          # the sight closing in on what it watches
            A = O or C
            self._add("ring", t, .5, at=A, col="#ffffff" if key == "steady_aim" else steel, r0=r + .9, r1=r * .5, width=2)
        elif key in ("martial_arts", "flurry") and O:        # quick blows: small ki bursts on the one hit
            self._motes(t, .3, O, ki, 8, "burst", .5)
            if key == "flurry":
                self._motes(t + .1, .3, O, ki, 8, "burst", .5)
        elif key in ("patient_defense", "dodge"):            # guard up: a calm ring settles, a shell for a moment
            self._add("ring", t, .5, at=C, col=ki if key == "patient_defense" else steel, r0=r + .5, r1=r + .1, width=3)
            self._add("shell", t, .6, at=C, r=r + .18, col=ki if key == "patient_defense" else steel, ang=-math.pi / 2)
        elif key == "stunning_strike" and O:
            self._add("ring", t, .4, at=O, col=ki, r0=.2, r1=1.0, width=3)
        elif key in ("lay_on_hands", "healing_hands"):       # a golden touch, then the heal
            A = O or C
            self._add("ring", t, .45, at=A, col=gold, r0=.9, r1=.3, width=3)
            self._motes(t, .5, A, gold, 10, "inward", .9)
            return t + .25
        elif key == "divine_smite" and O:
            self._add("column", t, .5, at=O, r=.55, col=DAMAGE["radiant"])
        elif key == "bardic_inspiration" and O:              # a note flies to the ally and becomes its die
            self._add("bolt", t, .3, a=C, b=O, col=song)
            self._motes(t + .3, .6, O, song, 10, "rise", .4)
            return t + .3
        elif key == "turn_undead":                           # holy light washing out from the cleric
            self._add("ring", t, .7, at=C, col=gold, r0=r, r1=6.5, width=5)
            self._motes(t, .7, C, gold, 18, "burst", 3.0)
            self._shake(t, 2)
        elif key == "wild_shape":                            # leaves swirling round it as it changes
            self._puff(t, C, "#65a30d", s * .6)
            self._motes(t, .7, C, "#86efac", 12, "orbit", r + .3)
        elif key == "relentless_endurance":                  # it refuses to fall: a red burst, back up at 1
            self._add("ring", t, .5, at=C, col=fury, r0=r, r1=r + 1.0, width=5)
            self._motes(t, .5, C, fury, 14, "burst", r + .7)
            self._add("text", t, 1.1, at=(C[0], C[1] - .2), text=tr("Relentless!"), col=fury, size=.34)
            self._shake(t, 3)
        elif key == "help" and O:                            # a hand lent: gold to the ally
            self._add("bolt", t, .25, a=C, b=O, col=gold)
            self._add("ring", t + .25, .4, at=O, col=gold, r0=.8, r1=.3, width=2)
        elif key in ("grapple", "shove") and O:              # a grab or a shove: it lunges at the other
            self._pose(f["id"], t, .25, "bump", *self._away(C, O, .2))
            self._motes(t + .1, .35, O, steel, 8, "burst" if key == "shove" else "inward", .5)
        elif key in ("stand_up", "drop_prone"):              # a little dust
            self._motes(t, .4, (C[0], C[1] + r * .6), "#d6c3a1", 8, "burst", r * .8)
        elif key == "stabilize" and O:                       # a heartbeat steadied
            T = self.bodies.get(f.get("other")) or {}
            if T.get("pos"):
                self._add("ecg", t, 1.0, at=(O[0], T["pos"][1] - .15), w=max(1, int(T.get("span") or 1)) * .8, col=HEAL)
        elif key == "search":                                # it looks around
            self._add("ring", t, .6, at=C, col="#e5e7eb", r0=r, r1=r + 2.0, width=2)
        return t + .15

    def _react(self, f: dict, t: float) -> float:
        """Every reaction: a '!' over the reactor, its outline blinks white, its name under it (and a casting circle for a
        spell); then a picture of its own: Shield's shell facing the attacker, crossed steel for a parry, a side-step..."""
        R = self._centre(f["id"])
        if not R:
            return t
        s = max(1, int((self.bodies.get(f["id"]) or {}).get("span") or 1))
        O = self._centre(f.get("other"))
        key, name = f.get("key") or "", f.get("name") or ""
        self._add("text", t, .55, at=(R[0], R[1] - s / 2 - .4), text="!", col="#ffffff", size=.55, rise=.15)
        self._add("ring", t, .3, at=R, col="#ffffff", r0=s / 2, r1=s / 2 + .12, width=3)
        self._add("text", t + .05, 1.1, at=(R[0], R[1] + s / 2 + .2), text=tr(name), col="#e6e9ef", size=.24, rise=.2)
        if f.get("src"):
            tier = max(0, min(3, int(f.get("tier") or 0)))
            self._add("glyph", t, .6, at=R, r=s / 2 + (.15, .35, .6, .9)[tier], col=SOURCE.get(f["src"], MAGIC), tier=tier, spin=1)
        ang = math.atan2(O[1] - R[1], O[0] - R[0]) if O else -math.pi / 2
        if key in ("shield", "absorb"):                      # a faceted shell, brightest on the side the blow comes from
            col = MAGIC if key == "shield" else tint(f.get("arg"), MAGIC)
            self._add("shell", t + .05, .8, at=R, r=s / 2 + .22, col=col, ang=ang)
        elif key in ("parry", "duelist", "riposte"):         # steel meets steel between them
            P = (R[0] + math.cos(ang) * s * .45, R[1] + math.sin(ang) * s * .45)
            self._add("slash", t + .05, .26, at=P, col="#e5e7eb", big=False)
            self._add("slash", t + .1, .26, at=P, col="#e5e7eb", big=False, flip=True)
            self._motes(t + .1, .35, P, "#ffffff", 8, "burst", .4)
        elif key in ("uncanny", "deflect"):                  # a side-step away from the line of the blow
            self._pose(f["id"], t + .05, .3, "bump", -math.sin(ang) * .22, math.cos(ang) * .22)
            if key == "deflect":
                self._motes(t + .1, .35, (R[0] + math.cos(ang) * s * .45, R[1] + math.sin(ang) * s * .45), "#e5e7eb", 8, "burst", .35)
        elif key == "counterspell" and O:
            self._add("ray", t + .15, .4, a=R, b=O, col=MAGIC, jag=False)
        elif key in ("barbs", "cutting") and O:              # silver (or a bard's rose) drawn into the one rolling
            self._motes(t + .1, .5, O, "#e5e7eb" if key == "barbs" else SOURCE["song"], 10, "inward", .9)
        elif key in ("lucky", "second_chance", "indomitable"):
            self._motes(t + .05, .5, R, CRIT, 10, "burst", .7)
        elif key == "rebuke" and O:                          # fire erupts under the attacker
            self._add("column", t + .15, .6, at=O, r=.6, col=DAMAGE["fire"])
            self._motes(t + .15, .6, O, DAMAGE["fire"], 12, "rise", .5)
        elif key == "smite" and O:                           # Divine Smite: radiance comes down on the one hit
            self._add("column", t, .5, at=O, r=.55, col=DAMAGE["radiant"])
        elif key == "stun" and O:                            # a ki burst on the one hit
            self._add("ring", t, .4, at=O, col=SOURCE["ki"], r0=.2, r1=1.0, width=3)
        elif key == "orcish_fury":
            self._motes(t, .45, R, SOURCE["fury"], 10, "burst", .6)
        elif key == "fade_away":
            self._puff(t, R, "#cbd5e1", s * .55)
        elif key == "wings":
            self._add("shell", t + .05, .7, at=R, r=s / 2 + .2, col=SOURCE["divine"], ang=ang)
        elif key == "reprisal" and O:
            self._add("ring", t + .1, .4, at=O, col=MAGIC, r0=.2, r1=.9, width=3)
        return t + .15

    def _away(self, A, T, d: float):
        """(dx, dy): d tiles from A toward T."""
        if not A or not T:
            return 0.0, 0.0
        L = math.hypot(T[0] - A[0], T[1] - A[1]) or 1.0
        return (T[0] - A[0]) / L * d, (T[1] - A[1]) / L * d

    def _queue(self, f: dict, t: float) -> float:
        k = f["k"]
        if k == "roll":                                      # a player's d20, rolled on screen: nothing else plays meanwhile
            roll = max(0.3, float(f.get("dur") or 1.8))
            self._add("dice", t, roll + REVEAL, roll=roll, f=f)
            return t + roll + REVEAL
        if k == "step":
            cid, to = f["id"], list(f["to"])
            a = self.where.get(cid) or to
            self.moves.setdefault(cid, []).append((t, STEP * (1.4 if f.get("push") else 1), list(a), to))
            self.where[cid] = to
            return t + STEP
        if k == "blink":
            cid, to = f["id"], list(f["to"])
            a = self.where.get(cid) or f.get("at") or to
            s = max(1, int((self.bodies.get(cid) or {}).get("span") or 1))
            self.moves.setdefault(cid, []).append((t, .16, list(a), list(a)))
            self._pose(cid, t, .16, "to", a=-1)                     # fades out where it was, in where it lands
            self._pose(cid, t + .16, .2, "from", a=-1)
            self._add("ring", t, .4, at=(a[0] + s / 2, a[1] + s / 2), col=MAGIC, r0=.2, r1=.9)
            self._add("ring", t + .16, .4, at=(to[0] + s / 2, to[1] + s / 2), col=MAGIC, r0=.9, r1=.2)
            self.where[cid] = to
            return t + .2
        if k == "attack":
            A, T = self._centre(f.get("by")), self._centre(f["id"])
            if not T:
                return t
            res, col = f.get("res"), tint(f.get("dtype"))
            hit = t
            if f.get("melee") and A:                                         # the attacker leans into its swing
                self._pose(f.get("by"), t, .24, "bump", *self._away(A, T, .2))
                hit = t + .08
            if not f.get("melee") and A and f.get("item"):                 # a thrown thing: it arcs over, turning
                dist = math.hypot(T[0] - A[0], T[1] - A[1])
                fly = max(.3, min(.75, .22 + dist * .05))
                end = T if res != "miss" else (T[0] + .55, T[1] - .45)
                self._add("toss", t, fly, a=A, b=end, look=f["item"], h=min(1.4, .25 + dist * .12),
                          spin=1 if f.get("n", 0) % 2 else -1)
                hit = t + fly
                if f["item"].get("shatter"):                                 # a flask breaks where it comes down
                    glass = SHATTER.get(f["item"].get("sprite"), "#e5e7eb")
                    self._motes(hit, .45, end, glass, 12, "burst", .6)
                    self._add("ring", hit, .35, at=end, col=glass, r0=.1, r1=.55)
            elif not f.get("melee") and A:
                dist = math.hypot(T[0] - A[0], T[1] - A[1])
                fly = max(.12, min(.32, dist * .028))
                end = T if res != "miss" else (T[0] + .55, T[1] - .45)
                self._add("bolt", t, fly, a=A, b=end, col=col if res != "miss" else MISS)
                hit = t + fly
            if res == "miss":
                if f.get("melee"):
                    self._add("slash", hit, .26, at=(T[0] + .3, T[1] - .25), col=MISS, big=False)
                self._add("ring", hit, .32, at=(T[0] + (.55 if not f.get("melee") else .3), T[1] - .4), col=MISS, r0=.05, r1=.3)
                self._add("text", hit, .8, at=T, text=tr("miss"), col=MISS, size=.34)
                return hit + .12
            crit = res == "crit"
            if f.get("melee"):
                self._add("slash", hit, .28, at=T, col=col, big=crit)
                if crit:
                    self._add("slash", hit + .06, .28, at=T, col=CRIT, big=True, flip=True)
            self._add("flash", hit, .38, tiles=[(x, y, 0) for x, y in self._tiles(f["id"])], col=col, peak=.55)
            self._motes(hit, .4, T, col, 12 if crit else 6, "burst", .75 if crit else .5)
            if A:                                                            # the one hit flinches away
                self._pose(f["id"], hit, .22, "bump", *self._away(A, T, .14 if crit else .08))
            if crit:
                cx, cy = int(T[0]), int(T[1])
                ring = [(cx + i, cy + j, .05 * max(abs(i), abs(j))) for i in (-1, 0, 1) for j in (-1, 0, 1) if i or j]
                self._add("flash", hit, .45, tiles=ring, col=CRIT, peak=.35)
                self._add("ring", hit, .45, at=T, col=CRIT, r0=.3, r1=1.4)
                self._add("text", hit, 1.0, at=(T[0], T[1] - .8), text=tr("CRIT!"), col=CRIT, size=.42)
                self._shake(hit, 5)
            return hit + .14
        if k == "land":                                      # the thrown thing drops to where it lies (a bounce, a short roll)
            a, b = tuple(f["at"]), tuple(f["to"])
            dur = max(.28, min(.5, .25 + math.hypot(b[0] - a[0], b[1] - a[1]) * .08))
            self._add("toss", t, dur, a=a, b=b, look=f["item"], h=.35, spin=1 if f.get("n", 0) % 2 else -1, slow=True)
            for key in ("gid", "did"):                       # the stack (or prop) stays hidden until it gets there
                if f.get(key) is not None:
                    self.flying[(key, f[key])] = t + dur
            self.timer.start()
            return t + .05
        if k == "dmg":
            T = self._centre(f["id"])
            if not T:
                return t
            n = int(f.get("amt") or 0)
            dtype = (f.get("dtype") or "").lower()
            if n > 0:                                                        # the number in its type's colour, moving its type's way
                self._add("num", t, 1.1 if dtype in NUM_LOOK else .95, at=(T[0], T[1] - .1), text=str(-n), dtype=dtype,
                          size=.5 if f.get("crit") else .4)
                if dtype in NUM_SPARKS:
                    self._motes(t, .9, (T[0], T[1] - .15), *NUM_SPARKS[dtype])
            else:
                self._add("text", t, .95, at=(T[0], T[1] - .1), text="0", col=MISS, size=.4)
            if n > 0:
                if f["id"] in self.mine():
                    self._shake(t, 9, .4)
                    self.red = t
                else:
                    self._shake(t, 4 if f.get("crit") else 2)
            return t + .05
        if k == "save":
            T = self._centre(f["id"])
            if not T:
                return t
            ok = f.get("ok")
            self._add("ring", t, .45, at=T, col=SAVED if ok else FAILED, r0=.55, r1=.4 if ok else .7, width=3)
            self._add("text", t, .8, at=(T[0], T[1] + .35), text=tr("save") if ok else tr("fail"), col=SAVED if ok else FAILED, size=.3)
            return t + .04
        if k == "area":
            tiles = [tuple(x) for x in f.get("tiles") or []]
            if not tiles:
                return t
            dtype, shape = (f.get("dtype") or "").lower(), f.get("shape") or ""
            col = tint(dtype, MAGIC) if dtype else MAGIC
            A = self._centre(f.get("by"))
            mid = (sum(x for x, _ in tiles) / len(tiles) + .5, sum(y for _, y in tiles) / len(tiles) + .5)
            if shape in ("cone", "line") and A:                               # from the caster outward: a sweep
                far = max(math.hypot(x + .5 - A[0], y + .5 - A[1]) for x, y in tiles)
                speed = .02 if shape == "cone" else .012
                ang = math.atan2(mid[1] - A[1], mid[0] - A[0])
                self._add("flash", t, .4, tiles=[(x, y, math.hypot(x + .5 - A[0], y + .5 - A[1]) * speed) for x, y in tiles], col=col, peak=.6)
                if shape == "cone":                                           # a bright front running out, motes streaming with it
                    half = min(.9, max(abs(math.remainder(math.atan2(y + .5 - A[1], x + .5 - A[0]) - ang, 2 * math.pi)) for x, y in tiles) + .1)
                    self._add("front", t, .12 + far * speed, at=A, ang=ang, half=half, far=far, col=col)
                    self._motes(t, .3 + far * speed, A, col, 16, "burst", far, .065, arc=(ang, half))
                else:                                                         # the whole line at once (lightning flickers)
                    B = max(((x + .5, y + .5) for x, y in tiles), key=lambda q: math.hypot(q[0] - A[0], q[1] - A[1]))
                    self._add("ray", t, .4, a=A, b=B, col=col, jag=dtype == "lightning")
                if len(tiles) > 12:
                    self._shake(t, 2)
                self._decal(t + .2, tiles, dtype)
                return t + min(.5, .15 + far * speed)
            o = f.get("at") or A or mid
            o = (float(o[0]), float(o[1]))
            if shape == "cylinder":                                           # it comes from above
                self._add("column", t, .6, at=o, r=max(.6, math.sqrt(len(tiles) / math.pi)), col=col)
                t += .12
            elif shape in BURSTS and A and math.hypot(o[0] - A[0], o[1] - A[1]) > 1.5 and dtype in LOBBED:
                fly = max(.25, min(.5, math.hypot(o[0] - A[0], o[1] - A[1]) * .035))    # a bead (a flask, a glob) arcs over
                self._add("lob", t, fly, a=A, b=o, col=col)
                t += fly
            far = max(math.hypot(x + .5 - o[0], y + .5 - o[1]) for x, y in tiles)
            speed = .035 if shape in BURSTS else .025
            cells = [(x, y, math.hypot(x + .5 - o[0], y + .5 - o[1]) * speed) for x, y in tiles]
            small = len(tiles) <= 9
            self._add("flash", t, .3 if small else .5, tiles=cells, col=col, peak=.6)
            self._decal(t + .15, tiles, dtype)
            if shape in BURSTS and not small:                                 # an explosion: a hot core and a ring going out
                self._add("ring", t, .35 + far * speed, at=o, col=col, r0=.2, r1=far + .5, width=4)
                self._add("ring", t, .25, at=o, col="#fff7e0", r0=.1, r1=1.0, width=6)
                self._motes(t, .55, o, col, 16, "burst", min(far, 3.0), .07)
                self._shake(t, min(7, 2 + len(tiles) / 25))
            elif small:                                                       # a splash
                self._add("ring", t, .3, at=o, col=col, r0=.1, r1=1.1)
            return t + min(.45, .15 + far * speed)
        if k == "heal":
            T = self._centre(f["id"])
            if not T:
                return t
            self._add("flash", t, .5, tiles=[(x, y, 0) for x, y in self._tiles(f["id"])], col=HEAL, peak=.45)
            self._add("ring", t, .5, at=T, col=HEAL, r0=.7, r1=.2)
            self._motes(t, .85, T, HEAL, 9, "rise", .4)
            self._add("text", t, .95, at=(T[0], T[1] - .1), text=f"+{int(f.get('amt') or 0)}", col=HEAL, size=.4)
            return t + .06
        if k == "down":
            T = self._centre(f["id"])
            if not T:
                return t
            tiles = self._tiles(f["id"])
            self._add("flash", t + .1, .9, tiles=[(x, y, 0) for x, y in tiles], col=DOWN, peak=.75)
            pc = f.get("pc", True)
            self._add("text", t + .1, 1.1, at=(T[0], T[1] + .25), text=tr("down") if pc else tr("defeated"), col="#fca5a5", size=.34)
            if not pc and not f.get("summoned"):             # (a summon vanishes instead: its own puff follows)
                self._death(f.get("type") or "", T, tiles, t + .1, (self.bodies.get(f["id"]) or {}).get("name") or "")
            return t + .1
        if k in ("feature", "action"):                       # a class feature, a standard action: its name and its look
            return self._feature_fx(f, t)
        if k == "inhale":                                    # a breath weapon draws in before it goes: the telegraph
            T = self._centre(f["id"])
            if not T:
                return t
            s = max(1, int((self.bodies.get(f["id"]) or {}).get("span") or 1))
            self._motes(t, .45, T, tint(f.get("dtype"), "#e5e7eb"), 16, "inward", s / 2 + 1.2, .06)
            self._pose(f["id"], t, .4, "bump", k=.06)
            return t + .35
        if k == "multi":                                     # Multiattack: how many attacks are coming
            T = self._centre(f["id"])
            if T:
                s = max(1, int((self.bodies.get(f["id"]) or {}).get("span") or 1))
                self._add("text", t, .9, at=(T[0], T[1] - s / 2 - .3), text=f"×{int(f.get('n') or 1)}", col=HIT, size=.36, rise=.2)
            return t + .05
        if k == "banner":                                    # the battle begins, a new round, victory: a strip across the screen
            text = tr(f.get("text") or "", f["round"]) if "{0}" in (f.get("text") or "") else tr(f.get("text") or "")
            self._add("banner", t, 1.1 if f.get("tone") == "round" else 1.7, text=text, tone=f.get("tone") or "")
            return t + .1
        if k == "turn":                                      # whose turn: its ring draws itself and pulses once
            T = self._centre(f["id"])
            if not T:
                return t
            s = max(1, int((self.bodies.get(f["id"]) or {}).get("span") or 1))
            self._add("sweep", t, .55, at=T, r=s / 2 + .04, col=CRIT)
            self._add("ring", t + .3, .45, at=T, col=CRIT, r0=s / 2, r1=s / 2 + .35, width=2)
            if f["id"] in self.mine():                       # the creature you are playing: it's your turn
                self._add("banner", t, 1.1, text=tr("Your turn"), tone="mine")
            return t + .05
        if k == "legendary":                                 # a crown flashes over it, the action's name under it
            T = self._centre(f["id"])
            if not T:
                return t
            s = max(1, int((self.bodies.get(f["id"]) or {}).get("span") or 1))
            self._add("crown", t, .9, at=(T[0], T[1] - s / 2 - .35))
            self._add("text", t + .05, 1.2, at=(T[0], T[1] + s / 2 + .2), text=tr(f.get("name") or "Legendary action"), col=LEGENDARY, size=.26, rise=.2)
            return t + .2
        if k == "lres":                                      # Legendary Resistance: a gold shield bursts out of it and shatters
            T = self._centre(f["id"])
            if not T:
                return t
            s = max(1, int((self.bodies.get(f["id"]) or {}).get("span") or 1))
            self._add("shell", t, .5, at=T, r=s / 2 + .3, col=LEGENDARY, ang=-math.pi / 2)
            self._add("shatter", t + .35, .5, at=T, r=s / 2 + .3, col=LEGENDARY, spin=random.uniform(0, 360))
            self._add("text", t + .1, 1.4, at=(T[0], T[1] - s / 2 - .2), text=tr("Legendary Resistance ({0} left)", f.get("left", 0)),
                      col=LEGENDARY, size=.26, rise=.3)
            return t + .3
        if k == "recharge":                                  # a recharge ability is ready again: a glint
            T = self._centre(f["id"])
            if not T:
                return t
            self._motes(t, .5, T, LEGENDARY, 8, "burst", .6)
            self._add("text", t, 1.0, at=(T[0], T[1] - .3), text=tr("{0} recharged", tr(f.get("name") or "")), col=LEGENDARY, size=.24, rise=.3)
            return t + .05
        if k == "dsave":                                     # a death save: a pip fills; three of a kind: stable, or dead
            return self._dsave(f, t)
        if k == "cast":
            A = self._centre(f.get("by"))
            col = tint(f.get("dtype")) if f.get("dtype") else SOURCE.get(f.get("src"), MAGIC)
            if A:
                self._add("ring", t, .4, at=A, col=col, r0=.25, r1=.85, width=3)
            for cid in f.get("ids") or []:
                T = self._centre(cid)
                if T and T != A:
                    self._add("ring", t + .12, .4, at=T, col=col, r0=.85, r1=.3)
                if T and not f.get("dtype"):                                # no damage: something given - it rises
                    self._motes(t + .12, .7, T, col, 7, "rise", .4)
            return t + .12
        if k == "cond":                                      # a condition: its icon pops over the token, then becomes a badge
            T = self._centre(f["id"])
            name = f.get("name")
            if not T or name not in icons.BADGES:
                return t
            col = icons.BADGES[name][1]
            if f.get("on"):
                self._add("icon", t, .8, id=f["id"], name=name, col=col, on=True)
                self._add("ring", t + .08, .4, at=T, col=col, r0=.3, r1=.85, width=3)
                self._add("text", t + .08, .9, at=(T[0], T[1] + .45), text=tr(name), col=col, size=.28, rise=.3)
                self.landing[(f["id"], name)] = t + .8
                return t + .25
            self._add("icon", t, .55, id=f["id"], name=name, col=col, on=False)
            return t + .08
        if k == "summon":                                    # a circle where it arrives, then the token pops in out of it
            cid = f["id"]
            T = self._centre(cid)
            if not T:
                return t
            c = self.bodies.get(cid) or {}
            s = max(1, int(c.get("span") or 1))
            kind, col = f.get("type") or "", SOURCE.get(f.get("src"), MAGIC)
            tier = max(0, min(3, int(f.get("tier") or 0)))
            if kind == "familiar":                           # a familiar, a steed: a little puff, no circle
                self._puff(t, T, "#cbd5e1", s * .55)
                start = t + .05
            else:
                self._add("glyph", t, .85, at=T, r=s / 2 + (.25, .35, .5, .7)[tier], col=col, tier=tier, spin=1 if f.get("n", 0) % 2 else -1)
                self._summon_twist(kind, T, s, t, col, c.get("name") or "")
                start = t + .25
            self._pose(cid, start, .12, "in", a=-1)          # unseen until now, then it pops: small, a little too big, settled
            if kind == "undead":
                self._pose(cid, start, .35, "in", dy=.35 * s)  # climbing up out of the floor
            else:
                self._pose(cid, start, .3, "in", k=-.8)
                self._pose(cid, start + .22, .18, "bump", k=.08)
            self._add("ring", start + .25, .35, at=T, col="#d6c3a1", r0=s / 2, r1=s / 2 + .45, width=2)
            self._add("ring", start + .3, .4, at=T, col="#4ade80" if c.get("faction") == 1 else "#f87171", r0=s / 2 + .05, r1=s / 2 + .2, width=3)
            return t + .05                                   # several arriving: one after another, quickly
        if k == "unsummon":                                  # it shrinks away into a puff
            at, s = f["at"], max(1, int(f.get("span") or 1))
            T = (at[0] + s / 2, at[1] + s / 2)
            c = self.old.get(f["id"]) or self.bodies.get(f["id"])
            if c:
                self._add("ghost", t, .45, c=c, at=list(at), s=s)
            self._add("ring", t, .45, at=T, col=MAGIC, r0=s / 2 + .3, r1=.1, width=2)
            self._puff(t + .3, T, "#cbd5e1", s * .55)
            return t + .05
        if k == "turned":                                    # a summon breaks free and turns on its caster
            T = self._centre(f["id"])
            if not T:
                return t
            s = max(1, int((self.bodies.get(f["id"]) or {}).get("span") or 1))
            self._pose(f["id"], t, .3, "bump", dx=.12)
            self._add("ring", t, .5, at=T, col=FAILED, r0=s / 2, r1=s / 2 + .6, width=4)
            self._motes(t, .5, T, FAILED, 10, "burst", s / 2 + .3)
            self._add("text", t, 1.1, at=(T[0], T[1] - s / 2 - .3), text=tr("breaks free!"), col=FAILED, size=.3)
            self._shake(t, 3)
            return t + .1
        if k == "conc":                                      # concentration: a save wobbles the ring; kept it brightens, lost it shatters
            T = self._centre(f["id"])
            if not T:
                return t
            s = max(1, int((self.bodies.get(f["id"]) or {}).get("span") or 1))
            col, r = SOURCE.get(f.get("src"), MAGIC), s / 2 + .1
            if f.get("check"):
                self._add("wobble", t, .35, at=T, r=r, col=col)
                t += .35
            if f.get("ok"):
                self._add("ring", t, .4, at=T, col=col, r0=r, r1=r + .18, width=4)
                return t + .05
            self._add("shatter", t, .5, at=T, r=r, col=col, spin=random.uniform(0, 360))
            for end in f.get("ends") or []:                  # every link flashes into view and snaps at once
                self._add("snap", t, .6, a=T, b=(float(end[0]), float(end[1])), col=col)
            self._add("text", t, 1.0, at=(T[0], T[1] + s / 2 + .1), text=tr("{0} ends", tr(f.get("spell") or "")), col=col, size=.24, rise=.25)
            return t + .1
        if k == "zone":                                      # a lasting area appears, strikes, ends, or is moved
            return self._zone_fx(f, t)
        if k == "react":                                     # a reaction: the same tell for all, then what it does
            return self._react(f, t)
        if k == "countered":                                 # Counterspell decided: the caster's circle breaks, or the counter's ray does
            C, B = self._centre(f["id"]), self._centre(f.get("by"))
            if not C:
                return t
            if f.get("ok"):
                s = max(1, int((self.bodies.get(f["id"]) or {}).get("span") or 1))
                self._add("shatter", t, .5, at=C, r=s / 2 + .35, col=MAGIC, spin=random.uniform(0, 360))
                self._add("text", t, 1.0, at=(C[0], C[1] - .2), text=tr("countered!"), col=MAGIC, size=.32, rise=.4)
                self._shake(t, 2)
            elif B:
                self._add("snap", t, .5, a=B, b=C, col=MAGIC)
                self._add("text", t, .9, at=(B[0], B[1] - .2), text=tr("counter failed"), col=MISS, size=.26, rise=.3)
            return t + .15
        if k == "tell":                                      # a lasting effect changed a number: its badge blinks, the number rises
            T = self._centre(f["id"])
            name = f.get("name") or ""
            if not T:
                return t
            s = max(1, int((self.bodies.get(f["id"]) or {}).get("span") or 1))
            self.blinks[(f["id"], name)] = t
            text = f"½ {tr(name)}" if f.get("half") else f"{int(f.get('amt') or 0):+d} {tr(name)}"
            self._add("text", t, .9, at=(T[0], T[1] - s / 2 - .5), text=text, col=icons.BADGES.get(name, (None, MAGIC))[1], size=.22, rise=.35)
            return t
        if k == "glyph":                                     # a casting circle under the caster: the spell gathers
            A = self._centre(f["id"])
            if not A:
                return t
            tier = max(0, min(3, int(f.get("tier") or 0)))
            s = max(1, int((self.bodies.get(f["id"]) or {}).get("span") or 1))
            col, hold = SOURCE.get(f.get("src"), MAGIC), GATHER[tier]
            r = s / 2 + (.15, .35, .6, .9)[tier]
            self._add("glyph", t, hold + .35, at=A, r=r, col=col, tier=tier, spin=1 if f.get("n", 0) % 2 else -1)
            self._motes(t, hold + .1, A, col, 6 + 4 * tier, "inward", r)
            if tier >= 2 and f.get("spell"):
                self._add("text", t, hold + .7, at=(A[0], A[1] - s / 2 - .2), text=tr(f["spell"]), col=col, size=.26, rise=.25)
            return t + hold
        return t

    # ------------------------------------------------------------------ playing
    def busy(self) -> bool:
        return bool(self.items or self.moves or self.poses or self.zone_moves or self.shakes or self.flying or self.red is not None)

    def hidden(self, key: str) -> set:
        """The ground stacks ('gid') or props ('did') a thrown thing is still flying to: the map leaves them out."""
        if not self.flying:
            return set()
        now = time.monotonic()
        return {i for (k, i), end in self.flying.items() if k == key and now < end}

    def _tick(self):
        now = time.monotonic()
        self.items = [i for i in self.items if now < i["t0"] + i["dur"] + max((c[2] for c in i.get("tiles") or []), default=0)]
        self.poses = {cid: kept for cid, segs in self.poses.items() if (kept := [s for s in segs if now < s[0] + s[1]])}
        self.landing = {k: v for k, v in self.landing.items() if now < v}
        self.zone_moves = {k: v for k, v in self.zone_moves.items() if now < v[0] + v[1]}
        self.flying = {k: v for k, v in self.flying.items() if now < v}
        self.blinks = {k: v for k, v in self.blinks.items() if now < v + BLINK}
        self.shakes = [s for s in self.shakes if now < s[0] + s[1]]
        if self.red is not None and now > self.red + 1.0:
            self.red = None
        self.w.update()
        if not self.busy():
            self.timer.stop()

    def pos(self, cid):
        """Where a walking token is drawn now (tile units, floats), or None to draw it where the battle says."""
        segs = self.moves.get(cid)
        if not segs:
            return None
        now = time.monotonic()
        while segs and now >= segs[0][0] + segs[0][1]:
            segs.pop(0)
        if not segs:
            del self.moves[cid]
            return None
        t0, dur, a, b = segs[0]
        if now <= t0:
            return a
        u = (now - t0) / dur
        u = u * u * (3 - 2 * u)
        return (a[0] + (b[0] - a[0]) * u, a[1] + (b[1] - a[1]) * u)

    def pose(self, cid):
        """How a token is drawn now beside where it stands: (dx, dy in tiles, scale, opacity), or None to draw it as it is."""
        segs = self.poses.get(cid)
        if not segs:
            return None
        now = time.monotonic()
        dx = dy = k = a = 0.0
        for t0, dur, ease, sx, sy, sk, sa in segs:
            u = (now - t0) / dur
            if u < 0 and ease == "in":
                u = 0.0
            if not 0 <= u <= 1:
                continue
            w = math.sin(math.pi * u) if ease == "bump" else u * u * (3 - 2 * u) if ease == "to" else 1 - u * u * (3 - 2 * u)
            dx, dy, k, a = dx + sx * w, dy + sy * w, k + sk * w, a + sa * w
        return dx, dy, max(0.05, 1 + k), max(0.0, min(1.0, 1 + a))

    def paint_badges(self, p, c: dict, cx: float, top: float, z: float, font: QFont):
        """A token's badges over its top edge (map.py calls it for each token, where the token is drawn); one whose
        effect just changed a number swells and flashes (a '+N' badge for the ones it stands for)."""
        shown = badges(c)
        every = icons.badge_keys(c.get("conditions"), c.get("effects"))
        now = time.monotonic()
        for i, name in enumerate(shown):
            if self.landing.get((c["id"], name), 0) > now:
                continue                                     # its icon is still on its way there
            x, y, r = badge_slot(cx, top, i, len(shown), z)
            under = every[BADGE_MAX - 1:] if name.startswith("+") else [name]
            u = max(((now - self.blinks[(c["id"], k)]) / BLINK for k in under if (c["id"], k) in self.blinks), default=-1)
            if 0 <= u <= 1:
                col = icons.BADGES.get(name, (None, "#e6e9ef"))[1]
                g = QRadialGradient(QPointF(x, y), r * 2.2)
                g.setColorAt(0, colour(col, .55 * (1 - u)))
                g.setColorAt(1, colour(col, 0))
                p.setPen(Qt.NoPen)
                p.setBrush(g)
                p.drawEllipse(QPointF(x, y), r * 2.2, r * 2.2)
                r *= 1 + .4 * math.sin(math.pi * u)
            paint_badge(p, x, y, r, name, font)
            if 0 <= u <= 1:
                p.setPen(QPen(colour("#ffffff", .9 * (1 - u)), max(1.5, r * .2)))
                p.drawEllipse(QPointF(x, y), r, r)

    @staticmethod
    def paint_conc(p, c: dict, cx: float, cy: float, s: float, z: float):
        """A concentrating creature's ring at its feet (map.py, under the token): dashed, in the colour of its magic."""
        st = c.get("concentrating")
        if not st:
            return
        pen = QPen(colour(SOURCE.get(st.get("src"), MAGIC), .85), max(1.5, z * .04))
        pen.setStyle(Qt.CustomDashLine)
        pen.setDashPattern([3.0, 2.0])
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QPointF(cx, cy), s / 2 + z * .1, s / 2 + z * .1)

    @staticmethod
    def paint_links(p, c: dict, view: dict, zones: list, ox, oy, z):
        """What a concentrating creature's spell holds (map.py, while it is hovered or selected): faint dashed lines
        from it to each creature it affects or summoned and to each of its zones."""
        st = c.get("concentrating")
        if not st or not c.get("pos"):
            return
        span = lambda o: max(1, int(o.get("span") or 1))  # noqa: E731
        A = QPointF(ox + (c["pos"][0] + span(c) / 2) * z, oy + (c["pos"][1] + span(c) / 2) * z)
        ends = [(o["pos"][0] + span(o) / 2, o["pos"][1] + span(o) / 2) for o in view.get("combatants") or []
                if o is not c and o.get("pos") and (o.get("summon_conc") == c["id"] or any(e.get("conc_by") == c["id"] for e in o.get("effects") or []))]
        ends += [(sum(t[0] for t in zn["tiles"]) / len(zn["tiles"]) + .5, sum(t[1] for t in zn["tiles"]) / len(zn["tiles"]) + .5)
                 for zn in zones if zn.get("conc_by") == c["id"] and zn.get("tiles")]
        col = SOURCE.get(st.get("src"), MAGIC)
        pen = QPen(colour(col, .6), max(1.5, z * .035), Qt.DashLine, Qt.RoundCap)
        for x, y in ends:
            B = QPointF(ox + x * z, oy + y * z)
            p.setPen(pen)
            p.drawLine(A, B)
            p.setPen(Qt.NoPen)
            p.setBrush(colour(col, .8))
            p.drawEllipse(B, max(2.5, z * .07), max(2.5, z * .07))
        p.setBrush(Qt.NoBrush)

    def _paint_icon(self, p, i: dict, u: float, ox, oy, z, font: QFont):
        """A condition's icon: going on, it pops big over the token, holds, then shrinks into its badge; going off,
        it lifts off the badge row and fades."""
        c = self.bodies.get(i["id"]) or {}
        at = self.pos(i["id"]) or c.get("pos")
        if not at:
            return
        s = max(1, int(c.get("span") or 1))
        cx, top = ox + (at[0] + s / 2) * z, oy + at[1] * z
        shown = badges(c)
        if not i["on"]:
            x, y, r = badge_slot(cx, top, 0, 1, z)
            paint_badge(p, x, y - .35 * z * u, r * (1 + .3 * u), i["name"], font, 1 - u)
            return
        k = shown.index(i["name"]) if i["name"] in shown else max(0, len(shown) - 1)
        sx, sy, sr = badge_slot(cx, top, k, max(1, len(shown)), z)
        big, mid = .42 * z, (cx, top + s * z / 2)
        if u < .15:                                          # pops out, a little too big, and settles
            v = u / .15 - 1
            x, y, r = mid[0], mid[1], big * (1 + 2.70158 * v ** 3 + 1.70158 * v ** 2)
        elif u < .5:
            x, y, r = mid[0], mid[1], big
        else:                                                # and flies into its place in the row
            v = (u - .5) / .5
            v = v * v * (3 - 2 * v)
            x, y, r = mid[0] + (sx - mid[0]) * v, mid[1] + (sy - mid[1]) * v, big + (sr - big) * v
        glow = 1 - max(0.0, (u - .5) / .5)
        g = QRadialGradient(QPointF(x, y), r * 1.9)
        g.setColorAt(0, colour(i["col"], .4 * glow))
        g.setColorAt(1, colour(i["col"], 0))
        p.setPen(Qt.NoPen)
        p.setBrush(g)
        p.drawEllipse(QPointF(x, y), r * 1.9, r * 1.9)
        paint_badge(p, x, y, max(1.0, r), i["name"], font)

    def shake(self):
        now = time.monotonic()
        dx = dy = 0.0
        for t0, dur, amp in self.shakes:
            u = (now - t0) / dur
            if 0 <= u <= 1:
                k = amp * (1 - u) ** 2
                dx += k * math.sin(u * 47)
                dy += k * math.cos(u * 39)
        return dx, dy

    def paint_under(self, p, ox, oy, z):
        now = time.monotonic()
        p.setPen(Qt.NoPen)
        for i in self.items:
            if i["kind"] == "glyph" and 0 <= now - i["t0"] <= i["dur"]:
                self._paint_glyph(p, i, now, ox, oy, z)
                p.setPen(Qt.NoPen)
            if i["kind"] == "crack" and 0 <= now - i["t0"] <= i["dur"]:
                self._paint_crack(p, i, (now - i["t0"]) / i["dur"], ox, oy, z)
                p.setPen(Qt.NoPen)
            if i["kind"] == "decal" and 0 <= now - i["t0"] <= i["dur"]:   # fades in quickly, then slowly away
                u = (now - i["t0"]) / i["dur"]
                fill = colour(i["col"], i["peak"] * (min(1.0, u / .05) if u < .3 else (1 - u) / .7))
                for x, y in i["cells"]:
                    p.fillRect(QRectF(ox + x * z, oy + y * z, z, z), fill)
            if i["kind"] != "flash":
                continue
            for x, y, delay in i["tiles"]:
                u = (now - i["t0"] - delay) / i["dur"]
                if 0 <= u <= 1:
                    a = i["peak"] * (math.sin(math.pi * min(1.0, u * 1.6)) if u < .31 else (1 - u) / .69)
                    p.fillRect(QRectF(ox + x * z, oy + y * z, z, z), colour(i["col"], a))

    @staticmethod
    def _paint_glyph(p, i: dict, now: float, ox, oy, z):
        """A casting circle on the floor: a soft glow, a ring of runes turning (and an inner ring from a 1st-level slot,
        a triangle from a 3rd, a star and broken outer ring from a 6th). Grows in, fades out as the spell goes."""
        e, tier, col = now - i["t0"], i["tier"], i["col"]
        a = min(1.0, e / .15) if e < .15 else max(0.0, (i["dur"] - e) / .3) if e > i["dur"] - .3 else 1.0
        grow = 1 - (1 - min(1.0, e / .2)) ** 2
        R = i["r"] * z * (.7 + .3 * grow)
        c = QPointF(ox + i["at"][0] * z, oy + i["at"][1] * z)
        spin = i["spin"] * e * (50 + 25 * tier)
        g = QRadialGradient(c, R)
        g.setColorAt(0, colour(col, .22 * a))
        g.setColorAt(1, colour(col, 0))
        p.setPen(Qt.NoPen)
        p.setBrush(g)
        p.drawEllipse(c, R, R)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(colour(col, .9 * a), max(1.5, z * .035)))
        p.drawEllipse(c, R, R)
        inner = R * .8
        if tier:
            p.setPen(QPen(colour(col, .65 * a), max(1.0, z * .022)))
            p.drawEllipse(c, inner, inner)
        p.setPen(QPen(colour(col, .85 * a), max(1.0, z * .03), Qt.SolidLine, Qt.RoundCap))
        n = 8 + 4 * tier
        for j in range(n):                                   # the runes: ticks between the rings, long and short
            ang = math.radians(spin + 360 * j / n)
            r0, r1 = (inner * 1.04, R * (.96 if j % 2 else .9)) if tier else (R * .8, R * (.95 if j % 2 else .88))
            p.drawLine(QPointF(c.x() + r0 * math.cos(ang), c.y() + r0 * math.sin(ang)), QPointF(c.x() + r1 * math.cos(ang), c.y() + r1 * math.sin(ang)))
        if tier >= 2:                                        # a triangle inside, a star (two triangles) at the top tier
            p.setPen(QPen(colour(col, .6 * a), max(1.0, z * .022)))
            for off in ((0, 180) if tier >= 3 else (0,)):
                pts = [math.radians(-spin * .6 + off + 120 * j - 90) for j in range(3)]
                p.drawPolygon(QPolygonF([QPointF(c.x() + inner * math.cos(q), c.y() + inner * math.sin(q)) for q in pts]))
        if tier >= 3:                                        # a broken ring outside, turning the other way
            box = QRectF(c.x() - R * 1.15, c.y() - R * 1.15, R * 2.3, R * 2.3)
            p.setPen(QPen(colour(col, .7 * a), max(1.5, z * .03), Qt.SolidLine, Qt.RoundCap))
            for j in range(6):
                p.drawArc(box, int((-spin * .8 + 60 * j) * 16), 38 * 16)

    @staticmethod
    def _paint_crack(p, i: dict, u: float, ox, oy, z):
        """Cracks running out over the floor (a dark line with a glowing core), then fading."""
        grow = min(1.0, u / .25)
        a = 1.0 if u < .6 else (1 - u) / .4
        for pen in (QPen(QColor(11, 13, 18, int(190 * a)), max(2.0, z * .05), Qt.SolidLine, Qt.RoundCap),
                    QPen(colour(i["col"], .85 * a), max(1.0, z * .022), Qt.SolidLine, Qt.RoundCap)):
            p.setPen(pen)
            for pts in i["lines"]:
                n = 1 + int(grow * (len(pts) - 1))
                p.drawPolyline(QPolygonF([QPointF(ox + x * z, oy + y * z) for x, y in pts[:n]]))

    def _paint_motes(self, p, i: dict, u: float, pt, z):
        at, R, mode = i["at"], i["spread"], i["mode"]
        for ang, dist, delay, sp in i["dots"]:
            v = (u - delay) / .7
            if not 0 <= v <= 1:
                continue
            ca, sa = math.cos(ang), math.sin(ang)
            if mode == "burst":
                d = R * dist * sp * (1 - (1 - v) ** 2)
                q, alpha = (at[0] + ca * d, at[1] + sa * d), 1 - v
            elif mode == "inward":
                d = R * (.8 + .2 * dist) * (1 - v)
                q, alpha = (at[0] + ca * d, at[1] + sa * d), min(1.0, v * 4)
            elif mode == "fall":
                q, alpha = (at[0] + ca * R * dist, at[1] - .45 + sa * R * .3 + v * .7 * sp), math.sin(math.pi * v)
            elif mode == "orbit":                            # round and round, drawing in a little
                a, d = ang + v * 2 * math.pi * .8 * sp, R * (.6 + .4 * dist) * (1 - .4 * v)
                q, alpha = (at[0] + math.cos(a) * d, at[1] + math.sin(a) * d), math.sin(math.pi * v)
            else:                                            # rise
                q = (at[0] + ca * R * dist + math.sin(v * 6 + ang) * .05, at[1] + sa * R * dist * .6 - v * .9 * sp)
                alpha = math.sin(math.pi * v)
            r = max(1.2, i["size"] * z * (1 - .5 * v if mode == "burst" else 1))
            c = pt(q)
            p.setBrush(colour(i["col"], alpha * .25))
            p.drawEllipse(c, r * 2.2, r * 2.2)
            p.setBrush(colour(i["col"], alpha))
            p.drawEllipse(c, r, r)

    @staticmethod
    def _paint_toss(p, i: dict, u: float, now: float, pt, z: float):
        """A thrown thing in flight: its sprite (or prop) arcing from a to b over its shadow, turning over and over - or
        point first along its path (a javelin, a dart) - with a faint trail behind it (portal.js: tossDraw)."""
        from ....services.battle import props
        from .drawtools import item_pixmap, paint_item, prop_pixmap
        look = i["look"]
        pm = prop_pixmap(props.shown(look["prop"])) if look.get("prop") else item_pixmap(look.get("sprite") or "")
        if pm is None:
            return
        (ax, ay), (bx, by), h = i["a"], i["b"], i["h"]
        size = z * (.9 if look.get("prop") else .62)
        turns = (1.2 if i.get("slow") else 2.6) * i["dur"]   # turns per flight: a quick spin thrown, a slow tumble dropping

        def at(v):
            v = min(1.0, max(0.0, v))
            return ax + (bx - ax) * v, ay + (by - ay) * v - 4 * v * (1 - v) * h

        def turn(v):
            if look.get("point"):                            # along the path (the sprite's tip points `point` degrees up)
                vx, vy = bx - ax, (by - ay) - 4 * h * (1 - 2 * v)
                return math.degrees(math.atan2(vy, vx)) + float(look["point"])
            return i["spin"] * 360 * turns * v + (0 if look.get("prop") else -20)

        gx, gy = ax + (bx - ax) * u, ay + (by - ay) * u     # the shadow on the floor, smaller the higher it flies
        lift = 4 * u * (1 - u) * h
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, int(90 / (1 + lift))))
        p.drawEllipse(pt((gx, gy + .22)), z * .2 / (1 + lift * .6), z * .07 / (1 + lift * .6))
        p.setBrush(Qt.NoBrush)
        if not i.get("slow"):
            for back, al in ((.12, .18), (.06, .35)):        # a faint trail
                if u > back:
                    x, y = at(u - back)
                    q = pt((x, y))
                    paint_item(p, pm, q.x(), q.y(), size, turn(u - back), shadow=0, alpha=al)
        x, y = at(u)
        q = pt((x, y))
        paint_item(p, pm, q.x(), q.y(), size * (1 + .15 * lift / max(h, .01)), turn(u), shadow=0)

    def paint_over(self, p, ox, oy, z, font: QFont):
        now = time.monotonic()
        pt = lambda q: QPointF(ox + q[0] * z, oy + q[1] * z)  # noqa: E731
        p.setBrush(Qt.NoBrush)                               # rings and arcs are outlines, whatever was drawn before
        for i in self.items:
            u = (now - i["t0"]) / i["dur"]
            if i["kind"] == "ghost" and u < 0:               # a leaving creature stays where it was until its turn to go
                u = 0.0
            if not 0 <= u <= 1 or i["kind"] in ("flash", "glyph", "crack", "decal"):
                continue
            k = i["kind"]
            if k == "ghost":
                if self.paint_token:                         # it shrinks away
                    s = i["s"] * z * (1 - .85 * u * u)
                    c = pt((i["at"][0] + i["s"] / 2, i["at"][1] + i["s"] / 2))
                    o = p.opacity()
                    p.setOpacity(o * (1 - u ** 1.5))
                    self.paint_token(p, i["c"], QRectF(c.x() - s / 2, c.y() - s / 2, s, s), i["s"] * z * .92)
                    p.setOpacity(o)
            elif k == "sweep":                               # a ring drawing itself round, then fading
                c, R = pt(i["at"]), i["r"] * z
                p.setPen(QPen(colour(i["col"], 1 if u < .7 else (1 - u) / .3), max(2.0, z * .06), Qt.SolidLine, Qt.RoundCap))
                p.drawArc(QRectF(c.x() - R, c.y() - R, 2 * R, 2 * R), 90 * 16, -int(360 * min(1.0, u / .6) * 16))
            elif k == "crown":                               # a crown popping over a legendary creature
                pm = picture("crown")
                if pm:
                    c, sz = pt(i["at"]), z * .55 * (1 + .25 * math.sin(math.pi * min(1.0, u / .3)))
                    g = QRadialGradient(c, sz)
                    g.setColorAt(0, colour(LEGENDARY, .5 * (1 - u)))
                    g.setColorAt(1, colour(LEGENDARY, 0))
                    p.setPen(Qt.NoPen)
                    p.setBrush(g)
                    p.drawEllipse(c, sz, sz)
                    p.setBrush(Qt.NoBrush)
                    o = p.opacity()
                    p.setOpacity(o * (1 if u < .7 else (1 - u) / .3))
                    p.drawPixmap(QRectF(c.x() - sz / 2, c.y() - sz / 2, sz, sz), pm, QRectF(pm.rect()))
                    p.setOpacity(o)
            elif k == "ecg":                                 # a heartbeat line drawn across, then fading
                w, (cx, cy) = i["w"], i["at"]
                trace = [(-.5, 0), (-.18, 0), (-.1, -.12), (-.03, .18), (.05, -.32), (.12, 0), (.5, 0)]
                shown = max(2, int(1 + min(1.0, u * 1.6) * (len(trace) - 1)))
                p.setPen(QPen(colour(i["col"], 1 if u < .7 else (1 - u) / .3), max(1.5, z * .05), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
                p.drawPolyline(QPolygonF([pt((cx + x * w, cy + y * w)) for x, y in trace[:shown]]))
            elif k == "shell":                               # a faceted bubble; the facet facing the blow is the bright one
                c, R = pt(i["at"]), i["r"] * z
                a = min(1.0, u / .12) if u < .12 else 1.0 if u < .6 else (1 - u) / .4
                corners = [QPointF(c.x() + R * math.cos(i["ang"] + math.radians(30 + 60 * j)), c.y() + R * math.sin(i["ang"] + math.radians(30 + 60 * j)))
                           for j in range(6)]
                p.setPen(QPen(colour(i["col"], .55 * a), max(1.5, z * .04)))
                p.setBrush(colour(i["col"], .12 * a))
                p.drawPolygon(QPolygonF(corners))
                p.setBrush(Qt.NoBrush)
                for w, col, al in ((z * .12, i["col"], .9), (z * .04, "#ffffff", .9)):   # the facing facet: between the last corner and the first
                    p.setPen(QPen(colour(col, al * a), max(1.5, w), Qt.SolidLine, Qt.RoundCap))
                    p.drawLine(corners[5], corners[0])
            elif k == "wobble":                              # a concentration ring shaken by a hit, while the save is rolled
                c = pt(i["at"])
                R = i["r"] * z * (1 + .08 * math.sin(u * 40) * (1 - u))
                p.setPen(QPen(colour(i["col"], .95), max(2.0, z * .05)))
                p.drawEllipse(c, R + math.cos(u * 33) * z * .03, R - math.cos(u * 33) * z * .03)
            elif k == "shatter":                             # the ring breaks: its pieces fly off, turning, fading
                c, R = pt(i["at"]), i["r"] * z * (1 + .9 * u)
                p.setPen(QPen(colour(i["col"], 1 - u), max(2.0, z * .05), Qt.SolidLine, Qt.RoundCap))
                for j in range(8):
                    a0 = i["spin"] + 45 * j + 120 * u * (1 if j % 2 else -1)
                    p.drawArc(QRectF(c.x() - R, c.y() - R, 2 * R, 2 * R), int(a0 * 16), int(28 * 16))
            elif k == "snap":                                # a link to what the spell held: it flashes, then breaks in the middle
                a, b = i["a"], i["b"]
                m = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
                if u < .35:
                    segs, al = [(a, b)], 1.0
                else:                                        # each half pulls back to its own end
                    v = (u - .35) / .65
                    segs, al = [(e, (e[0] + (m[0] - e[0]) * (1 - v), e[1] + (m[1] - e[1]) * (1 - v))) for e in (a, b)], 1 - v
                for w, col, k2 in ((z * .14, i["col"], .35), (z * .04, "#ffffff", .9)):
                    p.setPen(QPen(colour(col, k2 * al), max(1.0, w), Qt.SolidLine, Qt.RoundCap))
                    for q0, q1 in segs:
                        p.drawLine(pt(q0), pt(q1))
            elif k == "front":                               # a cone's bright leading edge running out from the caster
                R = i["far"] * z * (1 - (1 - u) ** 2)
                c = pt(i["at"])
                p.setPen(QPen(colour(i["col"], .9 * (1 - u * u)), max(2.0, z * .12), Qt.SolidLine, Qt.RoundCap))
                p.drawArc(QRectF(c.x() - R, c.y() - R, 2 * R, 2 * R), int(-math.degrees(i["ang"] + i["half"]) * 16), int(math.degrees(2 * i["half"]) * 16))
            elif k == "ray":                                 # a line all at once: a glow, a core; lightning zig-zags and flickers
                a = 1.0 if u < .5 else (1 - u) / .5
                pts = [i["a"], i["b"]]
                if i["jag"]:
                    rng = random.Random(int(now * 25))
                    L = math.hypot(i["b"][0] - i["a"][0], i["b"][1] - i["a"][1]) or 1.0
                    nx, ny = -(i["b"][1] - i["a"][1]) / L, (i["b"][0] - i["a"][0]) / L
                    n = max(2, int(L * 2))
                    pts = [i["a"]] + [(i["a"][0] + (i["b"][0] - i["a"][0]) * j / n + nx * rng.uniform(-.18, .18),
                                       i["a"][1] + (i["b"][1] - i["a"][1]) * j / n + ny * rng.uniform(-.18, .18)) for j in range(1, n)] + [i["b"]]
                line = QPolygonF([pt(q) for q in pts])
                for w, col, al in ((z * .32, i["col"], .3), (z * .1, i["col"], .95), (z * .035, "#ffffff", .9)):
                    p.setPen(QPen(colour(col, al * a), max(1.0, w), Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
                    p.drawPolyline(line)
            elif k == "lob":                                 # a bead arcing over, its shadow running along the floor
                a, b = i["a"], i["b"]
                gx, gy = a[0] + (b[0] - a[0]) * u, a[1] + (b[1] - a[1]) * u
                lift = 4 * u * (1 - u) * min(2.5, math.hypot(b[0] - a[0], b[1] - a[1]) * .25)
                p.setPen(Qt.NoPen)
                p.setBrush(QColor(0, 0, 0, 90))
                p.drawEllipse(pt((gx, gy)), z * .12, z * .06)
                for back, rr, al in ((.1, .1, .3), (.05, .13, .55), (0, .16, 1)):   # a short tail behind the bead
                    v = max(0.0, u - back)
                    hx, hy = a[0] + (b[0] - a[0]) * v, a[1] + (b[1] - a[1]) * v - 4 * v * (1 - v) * min(2.5, math.hypot(b[0] - a[0], b[1] - a[1]) * .25)
                    p.setBrush(colour(i["col"], al))
                    p.drawEllipse(pt((hx, hy)), z * rr, z * rr)
                p.setBrush(colour("#ffffff", .9))
                p.drawEllipse(pt((gx, gy - lift)), z * .06, z * .06)
                p.setBrush(Qt.NoBrush)
            elif k == "column":                              # a light from above: a tall soft band standing on the point
                c, R, H = pt(i["at"]), i["r"] * z, 3 * z
                a = min(1.0, u / .2) if u < .2 else (1 - u) / .8
                g = QLinearGradient(QPointF(c.x(), c.y() - H), c)
                g.setColorAt(0, colour(i["col"], 0))
                g.setColorAt(1, colour(i["col"], .55 * a))
                p.fillRect(QRectF(c.x() - R * .6, c.y() - H, R * 1.2, H), g)
                p.fillRect(QRectF(c.x() - R * .12, c.y() - H * .8, R * .24, H * .8), colour("#ffffff", .35 * a))
                rg = QRadialGradient(c, R)
                rg.setColorAt(0, colour(i["col"], .6 * a))
                rg.setColorAt(1, colour(i["col"], 0))
                p.setPen(Qt.NoPen)
                p.setBrush(rg)
                p.drawEllipse(c, R, R * .5)
                p.setBrush(Qt.NoBrush)
            elif k == "puff":                                # soft blobs swelling out and thinning
                R = i["r"] * z
                p.setPen(Qt.NoPen)
                p.setBrush(colour(i["col"], .45 * (1 - u)))
                for dx, dy, rs in i["blobs"]:
                    c = pt(i["at"])
                    spread = R * (.3 + .7 * u)
                    p.drawEllipse(QPointF(c.x() + dx * spread, c.y() + dy * spread), R * .45 * (.5 + .5 * u) * rs, R * .45 * (.5 + .5 * u) * rs)
                p.setBrush(Qt.NoBrush)
            elif k == "motes":
                p.setPen(Qt.NoPen)
                self._paint_motes(p, i, u, pt, z)
                p.setBrush(Qt.NoBrush)
            elif k == "icon":
                self._paint_icon(p, i, u, ox, oy, z, font)
                p.setBrush(Qt.NoBrush)
            elif k == "toss":
                self._paint_toss(p, i, u, now, pt, z)
            elif k == "bolt":
                a, b = i["a"], i["b"]
                head = (a[0] + (b[0] - a[0]) * u, a[1] + (b[1] - a[1]) * u)
                tu = max(0.0, u - .35)
                tail = (a[0] + (b[0] - a[0]) * tu, a[1] + (b[1] - a[1]) * tu)
                p.setPen(QPen(colour(i["col"], .35), max(3.0, z * .16), Qt.SolidLine, Qt.RoundCap))
                p.drawLine(pt(tail), pt(head))
                p.setPen(QPen(colour(i["col"], .95), max(1.5, z * .06), Qt.SolidLine, Qt.RoundCap))
                p.drawLine(pt(tail), pt(head))
                p.setPen(Qt.NoPen)
                p.setBrush(colour("#ffffff", .9))
                p.drawEllipse(pt(head), max(2.0, z * .07), max(2.0, z * .07))
                p.setBrush(Qt.NoBrush)
            elif k == "slash":
                r = z * (.62 if i.get("big") else .45)
                c = pt(i["at"])
                sweep = 150 * min(1.0, u * 2.2)
                start = (210 if i.get("flip") else 30) * 16
                p.setPen(QPen(colour(i["col"], 1 - max(0.0, u - .45) / .55), max(2.0, z * (.11 if i.get("big") else .08)),
                              Qt.SolidLine, Qt.RoundCap))
                p.drawArc(QRectF(c.x() - r, c.y() - r, 2 * r, 2 * r), start, int(sweep * 16))
            elif k == "ring":
                rr = (i["r0"] + (i["r1"] - i["r0"]) * (1 - (1 - u) ** 2)) * z
                p.setPen(QPen(colour(i["col"], (1 - u) * .9), i.get("width", 2)))
                p.drawEllipse(pt(i["at"]), rr, rr)
            elif k == "text":
                f = QFont(font)
                f.setBold(True)
                f.setPixelSize(int(max(11, z * i["size"])))
                p.setFont(f)
                c = pt((i["at"][0], i["at"][1] - i.get("rise", .7) * u))
                a = 1.0 if u < .6 else (1 - u) / .4
                box = QRectF(c.x() - 200, c.y() - 20, 400, 40)          # wide: a spell's name fits
                p.setPen(colour("#0b0d12", a * .85))
                p.drawText(box.translated(1.2, 1.2), Qt.AlignCenter, i["text"])
                p.setPen(colour(i["col"], a))
                p.drawText(box, Qt.AlignCenter, i["text"])
            elif k == "num":
                self._paint_num(p, i, u, now - i["t0"], pt, z, font)
        p.setBrush(Qt.NoBrush)

    def _paint_num(self, p, i, u, s, pt, z, font):
        """A damage number, character by character, each moved, turned and coloured by num_glyph; a glow, an outline or
        doubles where its type has them."""
        look, dtype, text = NUM_LOOK.get(i["dtype"], {}), i["dtype"], i["text"]
        f = QFont(font)
        f.setBold(True)
        f.setPixelSize(int(max(11, z * i["size"])))
        p.setFont(f)
        fm = QFontMetrics(f)
        rise = look.get("rise", .7)
        lift = rise * (1 - (1 - u) ** 3) if dtype == "piercing" else rise * u
        c = pt((i["at"][0], i["at"][1] - lift))
        fade = 1.0 if u < .6 else (1 - u) / .4
        widths = [fm.horizontalAdvance(ch) for ch in text]
        x = c.x() - sum(widths) / 2
        h = fm.height()
        for j, (ch, cw) in enumerate(zip(text, widths)):
            dx, dy, sx, sy, rot, col, a = num_glyph(dtype, u, s, j, len(text))
            a *= fade
            p.save()
            p.translate(x + cw / 2 + dx * z, c.y() + dy * z)
            p.rotate(rot)
            p.scale(sx, sy)
            box = QRectF(-cw, -h, 2 * cw, 2 * h)
            if look.get("glow"):                     # fire, lightning, radiant: a soft halo of light around the digits
                r = max(1.5, z * .04)
                p.setPen(colour(look["glow"], .22 * a))
                for q in range(8):
                    p.drawText(box.translated(r * math.cos(q * math.pi / 4), r * math.sin(q * math.pi / 4)), Qt.AlignCenter, ch)
            if look.get("ghosts"):                   # psychic: faint doubles drifting either side
                off = math.sin(s * 4 + j) * z * .07
                p.setPen(colour(col, .35 * a))
                p.drawText(box.translated(off, -off * .4), Qt.AlignCenter, ch)
                p.drawText(box.translated(-off, off * .4), Qt.AlignCenter, ch)
            p.setPen(colour("#0b0d12", a * .85))
            p.drawText(box.translated(1.2, 1.2), Qt.AlignCenter, ch)
            if look.get("edge"):                     # cold, force: a thin bright rim
                p.setPen(colour(look["edge"], .9 * a))
                for ex, ey in ((-1, 0), (1, 0), (0, -1), (0, 1)):
                    p.drawText(box.translated(ex, ey), Qt.AlignCenter, ch)
            p.setPen(colour(col, a))
            p.drawText(box, Qt.AlignCenter, ch)
            p.restore()
            x += cw

    def paint_screen(self, p, rect, font: QFont = None):
        """Screen-wide: the rolling dice, and the red edge when your own creature gets hurt (in fast, fading in a second)."""
        now = time.monotonic()
        for i in self.items:
            if i["kind"] == "banner" and i["t0"] <= now <= i["t0"] + i["dur"]:
                self._paint_banner(p, rect, font or QFont(), i, (now - i["t0"]) / i["dur"])
            if i["kind"] == "dice" and i["t0"] <= now <= i["t0"] + i["dur"]:
                self._paint_dice(p, rect, font or QFont(), i, now)
        if self.red is None:
            return
        u = (time.monotonic() - self.red) / 1.0
        if not 0 <= u <= 1:
            return
        a = (u / .08 if u < .08 else (1 - u) / .92) * .6
        g = QRadialGradient(rect.center(), max(rect.width(), rect.height()) * .62)
        g.setColorAt(0.55, QColor(120, 0, 0, 0))
        g.setColorAt(1.0, QColor(150, 0, 8, int(255 * a)))
        p.fillRect(rect, g)

    @staticmethod
    def _paint_banner(p, rect, font: QFont, i: dict, u: float):
        """A strip across the screen with a word, sliding in and out: a new round high up and small; the battle
        beginning, victory and your turn bigger, a third of the way down."""
        small = i["tone"] == "round"
        h = 34.0 if small else 60.0
        y = rect.top() + rect.height() * (.08 if small else .26)
        a = min(1.0, u / .15) if u < .15 else 1.0 if u < .75 else (1 - u) / .25
        slide = (1 - min(1.0, u / .15)) ** 2 * 60 - (max(0.0, u - .75) / .25) ** 2 * 60
        g = QLinearGradient(QPointF(rect.left(), y), QPointF(rect.right(), y))
        for stop, al in ((0, 0), (.2, .78), (.8, .78), (1, 0)):
            g.setColorAt(stop, QColor(10, 12, 16, int(255 * al * a)))
        p.fillRect(QRectF(rect.left(), y, rect.width(), h), g)
        col = BANNER.get(i["tone"], "#e6e9ef")
        p.fillRect(QRectF(rect.left() + rect.width() * .25, y, rect.width() * .5, 1.5), colour(col, .6 * a))
        p.fillRect(QRectF(rect.left() + rect.width() * .25, y + h - 1.5, rect.width() * .5, 1.5), colour(col, .6 * a))
        f = QFont(font)
        f.setBold(True)
        f.setPixelSize(18 if small else 30)
        p.setFont(f)
        p.setPen(colour(col, a))
        p.drawText(QRectF(rect.left() + slide, y, rect.width(), h), Qt.AlignCenter, i["text"])

    # ------------------------------------------------------------------ the dice
    def _paint_dice(self, p, rect, font: QFont, i: dict, now: float):
        f, roll = i["f"], i["roll"]
        e = now - i["t0"]
        prog = min(1.0, e / roll)
        ease = 1 - (1 - prog) ** 3
        done = prog >= 1
        dice = [int(d) for d in f.get("dice") or [f.get("kept") or 1]]
        kept = int(f.get("kept") or dice[0])
        n = len(dice)
        R = max(30.0, min(60.0, min(rect.width(), rect.height()) * .085))
        cx, cy = rect.center().x(), rect.top() + rect.height() * .42
        fade = 1.0 if e < i["dur"] - .25 else max(0.0, (i["dur"] - e) / .25)
        p.save()
        p.setOpacity(fade)
        big = QFont(font)
        big.setBold(True)
        big.setPixelSize(20)
        segs = self._maths(f, kept)
        fm = QFontMetrics(big)
        widths = [fm.horizontalAdvance(text) + (12 if chip is not None else 0) for text, _col, chip in segs]
        w = min(rect.width() - 16, max(280.0, n * R * 2.5 + 60, sum(widths) + 40))
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(10, 12, 16, 185))
        p.drawRoundedRect(QRectF(cx - w / 2, cy - R - 36, w, 2 * R + 104), 14, 14)
        small = QFont(font)
        small.setPixelSize(13)
        p.setFont(small)
        p.setPen(QColor(230, 233, 239, 210))
        p.drawText(QRectF(cx - w / 2, cy - R - 32, w, 22), Qt.AlignCenter, f"{f.get('who', '')} · {tr(f.get('label', ''))}")
        first = dice.index(kept) if kept in dice else 0
        for k, d in enumerate(dice):
            x = cx + (k - (n - 1) / 2) * R * 2.5
            spin = (1 - ease) * 900 * (1 if k % 2 == 0 else -1)
            hop = abs(math.sin(ease * math.pi * 3)) * (1 - ease) * R * .5
            step = int(ease * 24)                            # the ease-out spends its last third on step 23: settle on the real face
            shown = d if done or step >= 23 else (kept * 7 + k * 11 + d * 3 + step * 7) % 20 + 1
            pop = 1 + .16 * math.sin(min(1.0, (e - roll) / .25) * math.pi) if done and e - roll < .25 else 1.0
            self._d20(p, QPointF(x, cy - hop), R * pop, spin, shown, d if done else 0, done and n > 1 and k != first, font)
        if done:
            p.setFont(big)
            x, y = cx - sum(widths) / 2, cy + R + 8
            for (text, col, chip), wd in zip(segs, widths):
                if chip is None:
                    p.setPen(QColor(col))
                    p.drawText(QRectF(x, y, wd, 28), Qt.AlignCenter, text)
                else:                                        # an effect's die joins the roll: it drops in, one after another
                    u = max(0.0, min(1.0, (e - roll - .12 - .16 * chip) / .22))
                    box = QRectF(x + 4, y + 2 - 12 * (1 - u) ** 2, wd - 8, 24)
                    p.setOpacity(fade * u)
                    p.setPen(Qt.NoPen)
                    p.setBrush(colour(col, .22))
                    p.drawRoundedRect(box, 8, 8)
                    p.setBrush(Qt.NoBrush)
                    p.setPen(QColor(col))
                    p.drawText(box, Qt.AlignCenter, text)
                    p.setOpacity(fade)
                x += wd
            res = f.get("res") or ""
            big.setPixelSize(17)
            p.setFont(big)
            p.setPen(QColor(GOOD.get(res, "#f87171")))
            p.drawText(QRectF(cx - w / 2, cy + R + 38, w, 24), Qt.AlignCenter, tr(OUTCOME.get(res, res.capitalize())))
        p.restore()

    @staticmethod
    def _maths(f: dict, kept: int) -> list:
        """The landed roll's sum as [(text, colour, chip number or None)]: the die, the creature's own bonus, each effect
        that added to it as a chip in its colour (Bless, Bane...), the total and what it is against."""
        bonus, total, chips = int(f.get("bonus") or 0), int(f.get("total") or kept), f.get("chips") or []
        own = bonus - sum(int(n) for _name, n in chips)
        sign = lambda n: f"{'+' if n >= 0 else '−'} {abs(n)}"  # noqa: E731
        segs = [(str(kept), "#f5f6f8", None)]
        if own:
            segs.append((f" {sign(own)}", "#f5f6f8", None))
        for j, (name, n) in enumerate(chips):
            col = icons.BADGES.get(name, (None, "#fcd34d" if int(n) >= 0 else "#a78bfa"))[1]
            segs.append((f"{sign(int(n))} {tr(name)}", col, j))
        segs.append(((f" = {total}" if bonus else "") + f"   {tr('vs')} {f.get('vs', '')}", "#f5f6f8", None))
        return segs

    @staticmethod
    def _d20(p, c: QPointF, R: float, angle: float, shown: int, nat: int, dim: bool, font: QFont):
        """A d20 seen face on: a hexagon, the front triangle with the number, the edges running out to the rim."""
        body, face, edge = ("#7a4b05", "#b8860b", "#fde68a") if nat == 20 else ("#5b1010", "#8b1a1a", "#fca5a5") if nat == 1             else ("#3b1f75", "#5b34a8", "#c4b5fd")
        rim = [QPointF(R * math.cos(math.radians(-90 + 60 * j)), R * math.sin(math.radians(-90 + 60 * j))) for j in range(6)]
        tri = [QPointF(R * .6 * math.cos(math.radians(a)), R * .6 * math.sin(math.radians(a))) for a in (-90, 30, 150)]
        p.save()
        p.translate(c)
        p.rotate(angle)
        if dim:
            p.setOpacity(p.opacity() * .35)
        p.setPen(QPen(QColor(edge), 2))
        p.setBrush(QColor(body))
        p.drawPolygon(QPolygonF(rim))
        p.setPen(QPen(QColor(edge), 1.4))
        for t, js in zip(tri, ((5, 0, 1), (1, 2, 3), (3, 4, 5))):
            for j in js:
                p.drawLine(t, rim[j])
        p.setBrush(QColor(face))
        p.setPen(QPen(QColor(edge), 1.6))
        p.drawPolygon(QPolygonF(tri))
        num = QFont(font)
        num.setBold(True)
        num.setPixelSize(int(R * .42))
        p.setFont(num)
        p.setPen(QColor("#ffffff"))
        p.drawText(QRectF(-R * .5, -R * .25, R, R * .5), Qt.AlignCenter, str(shown))
        p.restore()
