"""Walls, cover, line of sight, light and who can see whom. Pure functions over the map's drawings and zones.

What the DM draws becomes terrain:
    snapped paths (lines along tile edges, rooms)     walls: block movement, sight, light and areas ('wall': False opts
                                                      out)
    a line given a cover level (rooms.cover_of)       'total': blocks like a wall, drawn as a line; 'half': half cover
                                                      across it, walked over; 'none': only a drawing
    rooms (rooms.py)                                  walls all round; a room door cuts its edge while it is open, an
                                                      archway always; a window or portcullis lets sight and light
                                                      through, creatures only while it is open (raised)
    door / locked door / secret door symbol           cuts the walls around its tile while it is open ('open': True)
    door props (props.DOOR_PROPS)                     shut: fill the tile (total cover); open: cut the walls around it
    pillar, statue                                    fill the tile: total cover, can't be entered
    chest, altar                                      half cover, can't be entered
    tree, rubble                                      half cover, difficult terrain
    water                                             difficult terrain
    fire, campfire, torch                             a light source (bright 20 ft, dim 20 ft more); walls and
                                                      total-cover tiles throw shadows (light_at, light_shapes)
    window, gate, portcullis                          shut: can't be entered, doesn't block sight; open: nothing

Cover is the DMG grid rule: from the attacker's best corner, lines to the four corners of the target's square.
Walls and total-cover objects blocking 1-2 lines give half cover, 3 three-quarters, all 4 total cover. Creatures and
low objects in the way give half cover at most.
"""
import math
from functools import lru_cache
from typing import Dict, FrozenSet, Iterable, List, Optional, Sequence, Tuple

from . import geometry as G
from .props import DOOR_PROPS, HATCHES, span as prop_span, terrain as prop_terrain
from .rooms import SEE_THROUGH, _walls as rooms_walls, cover_of, cut_of as rooms_cut, kind_of as rooms_kind

Edge = Tuple[Tuple[float, float], Tuple[float, float]]
SYMBOL_TERRAIN = {
    "pillar": {"cover": "total", "blocks": True}, "statue": {"cover": "total", "blocks": True},
    "chest": {"cover": "half", "blocks": True}, "altar": {"cover": "half", "blocks": True},
    "tree": {"cover": "half", "difficult": True}, "rock": {"cover": "half", "difficult": True},
    "water": {"difficult": True}, "window": {"blocks": True}, "fire": {"light": (20, 20)},
}
DOORS = ("door", "locked_door", "secret_door")
NONE, HALF, THREE_QUARTERS, TOTAL = 0, 2, 5, 99
COVER_NAME = {NONE: "no cover", HALF: "half cover", THREE_QUARTERS: "three-quarters cover", TOTAL: "total cover"}
INSET = 0.04


class Terrain:
    """The map's walls and objects, built once per set of drawings (see terrain())."""

    def __init__(self, edges: List[Edge], total: FrozenSet, half: FrozenSet, blocked: FrozenSet, difficult: FrozenSet,
                 lights: List[Tuple[float, float, int, int]], door_edges: Dict, low: Optional[List[Edge]] = None):
        self.edges = edges
        self.total = total            # tiles that block sight (pillars, statues)
        self.half = half              # tiles that give half cover
        self.blocked = blocked        # tiles nobody can enter
        self.difficult = difficult
        self.lights = lights          # (x, y, bright ft, dim ft)
        self.low = low or []          # half-cover lines: a low wall, a fence
        self.unit = set()             # unit wall edges, for movement between neighbouring tiles
        for (a, b) in edges:
            if a[0] == b[0] or a[1] == b[1]:
                self.unit |= set(_units(a, b))
        self.door_edges = door_edges
        self._lit = {}                # tile -> light level from the light sources (light_level)
        self._shapes = None

    def light_level(self, tile: G.Tile) -> int:
        """2 (bright), 1 (dim) or 0 from the map's light sources: in reach and no wall or total cover in between."""
        tile = (int(tile[0]), int(tile[1]))
        if tile not in self._lit:
            cx, cy, level = tile[0] + .5, tile[1] + .5, 0
            for x, y, bright, dim in self.lights:
                d = math.hypot(cx - x, cy - y) * 5
                if d > bright + dim or (d > 0.8 and wall_blocks(self, (x, y), (cx, cy), skip=(int(x), int(y)))):
                    continue
                level = max(level, 2 if d <= bright else 1)
                if level == 2:
                    break
            self._lit[tile] = level
        return self._lit[tile]

    def wall_between(self, a: G.Tile, b: G.Tile) -> bool:
        """Can't step from tile a to the neighbouring tile b (a wall on the shared edge, or a diagonal squeezing past one)."""
        dx, dy = b[0] - a[0], b[1] - a[1]
        if abs(dx) + abs(dy) == 1:
            return _edge_between(a, b) in self.unit
        if abs(dx) == 1 and abs(dy) == 1:
            via1, via2 = (a[0] + dx, a[1]), (a[0], a[1] + dy)
            return (self.wall_between(a, via1) or self.wall_between(via1, b)) and (self.wall_between(a, via2) or self.wall_between(via2, b)) \
                or (self.wall_between(a, via1) and self.wall_between(a, via2)) or (self.wall_between(via1, b) and self.wall_between(via2, b))
        return False


def _units(a, b) -> List[Edge]:
    (x1, y1), (x2, y2) = a, b
    out = []
    if x1 == x2:
        for y in range(int(min(y1, y2)), int(max(y1, y2))):
            out.append(((x1, y), (x1, y + 1)))
    else:
        for x in range(int(min(x1, x2)), int(max(x1, x2))):
            out.append(((x, y1), (x + 1, y1)))
    return out


def _edge_between(a: G.Tile, b: G.Tile) -> Edge:
    if a[0] != b[0]:
        x = max(a[0], b[0])
        return ((x, a[1]), (x, a[1] + 1))
    y = max(a[1], b[1])
    return ((a[0], y), (a[0] + 1, y))


def _tile_edges(t: G.Tile) -> List[Edge]:
    x, y = t
    return [((x, y), (x + 1, y)), ((x, y + 1), (x + 1, y + 1)), ((x, y), (x, y + 1)), ((x + 1, y), (x + 1, y + 1))]


def terrain(drawings: Optional[list]) -> Terrain:
    key = _key(drawings or [])
    return _terrain(key)


def _key(drawings: list):
    out = []
    for d in drawings:
        if d.get("type") == "path":
            out.append(("p", tuple(tuple(p) for p in d["pts"]), bool(d.get("closed")), cover_of(d)))
        elif d.get("type") == "symbol":
            out.append(("s", d.get("sym"), int(d.get("x", 0)), int(d.get("y", 0)), bool(d.get("open"))))
        elif d.get("type") == "room":
            out.append(("r", d["id"], d["x"], d["y"], d["w"], d["h"], rooms_cut(d)))
        elif d.get("type") == "door":
            out.append(("d", int(d["x"]), int(d["y"]), bool(d["v"]), bool(d.get("open")), rooms_kind(d)))
    return tuple(out)


@lru_cache(maxsize=64)
def _terrain(key) -> Terrain:
    units, edges, low = set(), [], []
    total, half, blocked, difficult, lights = set(), set(), set(), set(), []
    open_doors, closed_doors = set(), set()
    room_walls = rooms_walls(tuple(item[1:] for item in key if item[0] == "r"))
    for (x, y, v) in room_walls:
        units.add(((float(x), float(y)), (float(x), float(y + 1))) if v else ((float(x), float(y)), (float(x + 1), float(y))))
    wall_doors = []
    for item in key:
        if item[0] == "r":
            continue
        if item[0] == "d":                                   # (once every wall is known: drawn walls take doors too)
            _d, x, y, v, is_open, kind = item
            wall_doors.append(((((float(x), float(y)), (float(x), float(y + 1))) if v else ((float(x), float(y)), (float(x + 1), float(y)))),
                               (x, y), is_open, kind))
            continue
        if item[0] == "p":
            _p, pts, closed, cover = item
            if cover == "none":
                continue
            seq = list(pts) + ([pts[0]] if closed and pts[0] != pts[-1] else [])
            for a, b in zip(seq, seq[1:]):
                a, b = (float(a[0]), float(a[1])), (float(b[0]), float(b[1]))
                if cover == "half":
                    low.append((a, b))
                elif a[0] == b[0] and a[0].is_integer() or a[1] == b[1] and a[1].is_integer():
                    units |= set(_units(a, b))
                else:
                    edges.append((a, b))
        else:
            _s, sym, x, y, is_open = item
            t = (x, y)
            if sym in DOORS or sym in DOOR_PROPS and is_open:
                (open_doors if is_open else closed_doors).add(t)
                continue
            rule = {"cover": "total", "blocks": True} if sym in DOOR_PROPS else \
                {} if sym in HATCHES and is_open else SYMBOL_TERRAIN.get(sym) or prop_terrain(sym) or {}
            n = prop_span(sym)
            cells = [(x + i, y + j) for i in range(n) for j in range(n)]
            if rule.get("cover") == "total":
                total.update(cells)
            elif rule.get("cover") == "half":
                half.update(cells)
            if rule.get("blocks"):
                blocked.update(cells)
            if rule.get("difficult"):
                difficult.update(cells)
            if rule.get("light"):
                lights.append((x + n / 2, y + n / 2) + tuple(rule["light"]))
    room_doors = [w for w in wall_doors if w[0] in units]
    door_edges, no_way = {}, set()
    for e, t, is_open, kind in room_doors:                   # an open door or an archway: a way through; a window: sight only
        door_edges[e] = t
        if is_open or kind == "archway" or kind in SEE_THROUGH:
            units.discard(e)
        if kind in SEE_THROUGH:
            no_way.add(e)
    for t in open_doors | closed_doors:
        for e in _tile_edges(t):
            e = ((float(e[0][0]), float(e[0][1])), (float(e[1][0]), float(e[1][1])))
            if e in units:
                door_edges[e] = t
                if t in open_doors:
                    units.discard(e)
    edges += _merge(units)
    t = Terrain(edges, frozenset(total), frozenset(half), frozenset(blocked), frozenset(difficult), lights, door_edges, low)
    t.unit |= no_way                                         # windows: nobody steps through
    return t


# ---------------------------------------------------------------------- segments
def _orient(a, b, c) -> float:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0])


def crosses(p, q, a, b) -> bool:
    """Does segment p-q cross wall a-b? Running along a wall doesn't count; passing over its end does (DMG: touching)."""
    d1, d2 = _orient(a, b, p), _orient(a, b, q)
    if not ((d1 > 1e-9 and d2 < -1e-9) or (d1 < -1e-9 and d2 > 1e-9)):
        return False
    d3, d4 = _orient(p, q, a), _orient(p, q, b)
    if (d3 > 1e-9 and d4 < -1e-9) or (d3 < -1e-9 and d4 > 1e-9):
        return True
    return (abs(d3) <= 1e-9 and _on(p, q, a)) or (abs(d4) <= 1e-9 and _on(p, q, b))


def _on(p, q, r) -> bool:
    return min(p[0], q[0]) - 1e-9 <= r[0] <= max(p[0], q[0]) + 1e-9 and min(p[1], q[1]) - 1e-9 <= r[1] <= max(p[1], q[1]) + 1e-9


def _merge(units) -> List[Edge]:
    """Unit wall edges joined into the longest straight runs (fewer segments, no gaps at the joints)."""
    out = []
    horiz = sorted((a[1], a[0]) for a, b in units if a[1] == b[1])
    vert = sorted((a[0], a[1]) for a, b in units if a[0] == b[0])
    for rows, horizontal in ((horiz, True), (vert, False)):
        run = None
        for line, pos in rows:
            if run and run[0] == line and run[2] == pos:
                run[2] = pos + 1
                continue
            if run:
                out.append(((run[1], run[0]), (run[2], run[0])) if horizontal else ((run[0], run[1]), (run[0], run[2])))
            run = [line, pos, pos + 1]
        if run:
            out.append(((run[1], run[0]), (run[2], run[0])) if horizontal else ((run[0], run[1]), (run[0], run[2])))
    return out


def through_square(p, q, t: G.Tile, shrink: float = .08, solid=frozenset()) -> bool:
    """Does segment p-q pass through the inside of tile t (not just graze its border)? A side touching another tile of
    `solid` isn't a border to graze: a row of pillars or a magical wall is one block, with no seams to see through."""
    x, y = t
    x0 = x + (0 if (x - 1, y) in solid else shrink)
    y0 = y + (0 if (x, y - 1) in solid else shrink)
    x1 = x + 1 - (0 if (x + 1, y) in solid else shrink)
    y1 = y + 1 - (0 if (x, y + 1) in solid else shrink)
    # Liang-Barsky clipping
    dx, dy = q[0] - p[0], q[1] - p[1]
    lo, hi = 0.0, 1.0
    for pv, qv in ((-dx, p[0] - x0), (dx, x1 - p[0]), (-dy, p[1] - y0), (dy, y1 - p[1])):
        if abs(pv) < 1e-12:
            if qv < 0:
                return False
        else:
            r = qv / pv
            if pv < 0:
                lo = max(lo, r)
            else:
                hi = min(hi, r)
            if lo > hi:
                return False
    return hi - lo > 1e-6


def wall_blocks(ter: Terrain, p, q, skip=None) -> bool:
    """Walls or total-cover objects between two points (`skip`: a tile not to count, the one a light stands on)."""
    lx, hx, ly, hy = min(p[0], q[0]), max(p[0], q[0]), min(p[1], q[1]), max(p[1], q[1])
    for a, b in ter.edges:
        if max(a[0], b[0]) < lx - 1e-9 or min(a[0], b[0]) > hx + 1e-9 or max(a[1], b[1]) < ly - 1e-9 or min(a[1], b[1]) > hy + 1e-9:
            continue
        if crosses(p, q, a, b):
            return True
    for t in ter.total:
        if t[0] + 1 < lx or t[0] > hx or t[1] + 1 < ly or t[1] > hy or t == skip:
            continue
        if through_square(p, q, t, solid=ter.total):
            return True
    return False


def _low_blocks(ter: Terrain, p, q) -> bool:
    """A half-cover line (a low wall, a fence) between two points."""
    return any(crosses(p, q, a, b) for a, b in ter.low)


def _corners(t: G.Tile) -> List[Tuple[float, float]]:
    x, y = t
    return [(x + INSET, y + INSET), (x + 1 - INSET, y + INSET), (x + INSET, y + 1 - INSET), (x + 1 - INSET, y + 1 - INSET)]


def cover(ter: Terrain, att_pos, att_span: int, tgt_pos, tgt_span: int, others: Iterable[Tuple[Sequence[int], int]] = ()) -> int:
    """0 (none), 2 (half), 5 (three-quarters) or 99 (total) for an attack from one creature at another."""
    att_tiles = sorted(G.footprint(att_pos, att_span))
    tgt_tiles = sorted(G.footprint(tgt_pos, tgt_span))
    soft = set(ter.half)
    for pos, span in others:
        soft |= G.footprint(pos, span)
    soft -= set(att_tiles) | set(tgt_tiles)
    best = TOTAL
    for at in att_tiles:
        for a in _corners(at):
            for tt in tgt_tiles:
                hard, any_soft = 0, False
                for b in _corners(tt):
                    if wall_blocks(ter, a, b):
                        hard += 1
                    elif not any_soft and (any(through_square(a, b, s) for s in soft if _near(a, b, s)) or _low_blocks(ter, a, b)):
                        any_soft = True
                value = TOTAL if hard >= 4 else THREE_QUARTERS if hard == 3 else HALF if hard or any_soft else NONE
                best = min(best, value)
                if best == NONE:
                    return NONE
    return best


def _near(p, q, t) -> bool:
    return not (t[0] > max(p[0], q[0]) or t[0] + 1 < min(p[0], q[0]) or t[1] > max(p[1], q[1]) or t[1] + 1 < min(p[1], q[1]))


def line_of_sight(ter: Terrain, a_pos, a_span: int, b_pos, b_span: int) -> bool:
    return cover(ter, a_pos, a_span, b_pos, b_span) < TOTAL


def reaches(ter: Terrain, origin: Tuple[float, float], tile: G.Tile) -> bool:
    """Does an area spreading from `origin` reach the tile (nothing that gives total cover in between)?"""
    q = (tile[0] + .5, tile[1] + .5)
    return not wall_blocks(ter, origin, q)


def filter_area(ter: Terrain, origin: Tuple[float, float], tiles: Iterable[G.Tile]) -> FrozenSet[G.Tile]:
    return frozenset(t for t in tiles if reaches(ter, origin, t))


# ---------------------------------------------------------------------- light and seeing
LIGHT_ORDER = {"magic_dark": -1, "dark": 0, "dim": 1, "bright": 2}


def light_at(ter: Terrain, tile: G.Tile, base: str = "bright", zones: Iterable[dict] = ()) -> str:
    """'bright', 'dim', 'dark' or 'magic_dark' on a tile: the map's lighting, light sources, then darkness zones."""
    level = LIGHT_ORDER.get(base, 2)
    if level < 2 and ter.lights:
        level = max(level, ter.light_level(tile))
    dark = False
    for z in zones:
        if tuple(tile) not in z.get("_tiles", ()):
            continue
        if z.get("darkness"):
            dark = True
        lit = z.get("light")
        if lit == "bright":
            level = max(level, 2)
        elif lit == "dim":
            level = max(level, 1)
    if dark:
        return "magic_dark"
    return {2: "bright", 1: "dim", 0: "dark"}[max(0, min(2, level))]


LIGHT_RAYS = 72                                              # rays all round a light, besides the ones to wall corners


def light_shapes(ter: Terrain) -> List[dict]:
    """Each light source's lit area, cast the way 2D games do: rays from the light to every corner of the walls and
    total-cover tiles in its reach (and all round it), each stopped by the first one it meets - walls throw the
    shadows. In tile units: [{'x', 'y', 'bright', 'dim' (tiles), 'poly': [[x, y], ...]}]; worked out once for a map
    (the Terrain keeps it until a door opens or a wall changes)."""
    if ter._shapes is None:
        ter._shapes = [_light_shape(ter, x, y, bright / 5, dim / 5) for x, y, bright, dim in ter.lights]
    return ter._shapes


def _seg_dist(p, a, b) -> float:
    ex, ey = b[0] - a[0], b[1] - a[1]
    k = max(0.0, min(1.0, ((p[0] - a[0]) * ex + (p[1] - a[1]) * ey) / ((ex * ex + ey * ey) or 1)))
    return math.hypot(p[0] - a[0] - k * ex, p[1] - a[1] - k * ey)


def _ray_hit(ox, oy, dx, dy, a, b) -> Optional[float]:
    """How far along the ray (ox, oy) + t (dx, dy) it meets segment a-b, or None."""
    ex, ey = b[0] - a[0], b[1] - a[1]
    den = dx * ey - dy * ex
    if abs(den) < 1e-12:
        return None
    ax, ay = a[0] - ox, a[1] - oy
    t, u = (ax * ey - ay * ex) / den, (ax * dy - ay * dx) / den
    return t if t > 1e-9 and -1e-9 <= u <= 1 + 1e-9 else None


def _light_shape(ter: Terrain, lx: float, ly: float, bright: float, dim: float) -> dict:
    reach = bright + dim
    segs = [(a, b) for a, b in ter.edges if _seg_dist((lx, ly), a, b) <= reach]
    own = (int(math.floor(lx)), int(math.floor(ly)))
    for x, y in ter.total:
        if (x, y) != own and math.hypot(x + .5 - lx, y + .5 - ly) <= reach + 1:
            segs += [((x, y), (x + 1, y)), ((x + 1, y), (x + 1, y + 1)), ((x + 1, y + 1), (x, y + 1)), ((x, y + 1), (x, y))]
    angles = [i * math.tau / LIGHT_RAYS for i in range(LIGHT_RAYS)]
    for a, b in segs:
        for px, py in (a, b):
            if math.hypot(px - lx, py - ly) <= reach:          # a corner: one ray at it, one a hair either side
                at = math.atan2(py - ly, px - lx)
                angles += [at - 1e-4, at, at + 1e-4]
    poly = []
    for at in sorted(angles):
        dx, dy = math.cos(at), math.sin(at)
        far = reach
        for a, b in segs:
            t = _ray_hit(lx, ly, dx, dy, a, b)
            if t is not None and t < far:
                far = t
        poly.append([round(lx + dx * far, 3), round(ly + dy * far, 3)])
    return {"x": lx, "y": ly, "bright": bright, "dim": dim, "poly": poly}


def obscured(tile: G.Tile, zones: Iterable[dict]) -> Optional[str]:
    """'heavy' or 'light' when a zone obscures the tile (Fog Cloud, Darkness counts through light_at)."""
    out = None
    for z in zones:
        if tuple(tile) in z.get("_tiles", ()):
            o = z.get("obscure")
            if o == "heavy":
                return "heavy"
            if o == "light":
                out = "light"
    return out


def _crosses(a, b, tiles) -> bool:
    """Does the segment between two points pass over any of these tiles?"""
    n = max(2, int(math.hypot(b[0] - a[0], b[1] - a[1]) * 8))
    for k in range(1, n):
        x = a[0] + (b[0] - a[0]) * k / n
        y = a[1] + (b[1] - a[1]) * k / n
        if (int(math.floor(x)), int(math.floor(y))) in tiles:
            return True
    return False


def can_see(ter: Terrain, viewer: dict, target: dict, *, base_light: str = "bright", zones: Iterable[dict] = ()) -> bool:
    """Can `viewer` see `target`? Both are dicts with pos, span, conditions and senses
    ({'darkvision', 'blindsight', 'truesight', 'devils_sight': feet, 'see_invisible': bool})."""
    if not viewer.get("pos") or not target.get("pos"):
        return True
    zones = list(zones)
    d = G.distance_ft(viewer["pos"], viewer.get("span", 1), target["pos"], target.get("span", 1))
    s = viewer.get("senses") or {}
    los = line_of_sight(ter, viewer["pos"], viewer.get("span", 1), target["pos"], target.get("span", 1))
    if not los:
        return False
    if s.get("blindsight", 0) >= d or s.get("tremorsense", 0) >= d and not target.get("flying"):
        return True
    if "Blinded" in (viewer.get("conditions") or []):
        return False
    if "Invisible" in (target.get("conditions") or []) and not (s.get("see_invisible") or s.get("truesight", 0) >= d):
        return False
    vt = G.footprint(viewer["pos"], viewer.get("span", 1))
    tt = G.footprint(target["pos"], target.get("span", 1))
    if any(obscured(t, zones) == "heavy" for t in tt) or all(obscured(t, zones) == "heavy" for t in vt):
        return False
    pierce = s.get("truesight", 0) >= d or s.get("devils_sight", 0) >= d
    if not pierce and all(light_at(ter, t, base_light, zones) == "magic_dark" for t in vt):
        return False                                         # inside magical darkness nothing can be seen (BG3: blinded)
    walls = set()
    for z in zones:
        if z.get("opaque"):
            walls |= set(z.get("_tiles", ()))
    if walls - vt - tt and _crosses(G.centre(viewer["pos"], viewer.get("span", 1)), G.centre(target["pos"], target.get("span", 1)),
                                    walls - vt - tt):
        return False                                         # a Wall of Fire, an illusory wall: nothing seen through it
    best = max((LIGHT_ORDER[light_at(ter, t, base_light, zones)] for t in tt), default=2)
    if best >= 1:
        return True
    if best == 0:
        return s.get("darkvision", 0) >= d or s.get("truesight", 0) >= d or s.get("devils_sight", 0) >= d
    return s.get("truesight", 0) >= d or s.get("devils_sight", 0) >= d
