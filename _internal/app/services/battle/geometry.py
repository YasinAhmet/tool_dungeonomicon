"""The grid: footprints, distances in feet and the tiles an area covers. Pure functions, no battle state.

A tile is 5 feet. Positions are the top-left tile of a creature; `span` is how many tiles it covers across. Distances
follow the PHB grid rule: every square counts 5 feet, diagonals too. "Within 5 feet" means touching.

Points (the origin of a sphere, the end of a line) are floats in tile units: (3.0, 4.0) is the corner between four
tiles, (3.5, 4.5) the middle of tile (3, 4). A tile is in an area when its centre is (the DMG's "half a square" rule).
Areas are computed inside their bounding box only, and cached, so the map size doesn't matter.
"""
import math
from functools import lru_cache
from typing import FrozenSet, Iterable, Optional, Sequence, Tuple

from .floors import GAP

Tile = Tuple[int, int]
Point = Tuple[float, float]
FT = 5
EPS = 1e-6
SHAPES = ("sphere", "cylinder", "cone", "cube", "line", "emanation", "square")


# ---------------------------------------------------------------------- creatures on the grid
def footprint(pos: Sequence[int], span: int = 1) -> FrozenSet[Tile]:
    x, y = int(pos[0]), int(pos[1])
    n = max(1, int(span or 1))
    return frozenset((x + i, y + j) for i in range(n) for j in range(n))


def box(pos: Sequence[int], span: int = 1) -> Tuple[int, int, int, int]:
    """(x0, y0, x1, y1) inclusive tiles of a footprint."""
    n = max(1, int(span or 1))
    return int(pos[0]), int(pos[1]), int(pos[0]) + n - 1, int(pos[1]) + n - 1


def centre(pos: Sequence[int], span: int = 1) -> Point:
    n = max(1, int(span or 1))
    return pos[0] + n / 2, pos[1] + n / 2


def gap(a: Tuple[int, int, int, int], b: Tuple[int, int, int, int]) -> int:
    """Squares between two boxes along the worse axis: 0 overlapping, 1 touching (5 ft), 2 one square apart (10 ft)."""
    dx = max(0, b[0] - a[2], a[0] - b[2])
    dy = max(0, b[1] - a[3], a[1] - b[3])
    return max(dx, dy)


def distance_ft(a_pos, a_span, b_pos, b_span) -> int:
    """Feet between two creatures (0 when they overlap, 5 when adjacent)."""
    return FT * gap(box(a_pos, a_span), box(b_pos, b_span))


def distance_to_tile(pos, span, tile: Tile) -> int:
    return FT * gap(box(pos, span), (tile[0], tile[1], tile[0], tile[1]))


def distance_to_point(pos, span, point: Point) -> int:
    """Feet from a creature to the tile a point lies in."""
    return distance_to_tile(pos, span, (int(math.floor(point[0])), int(math.floor(point[1]))))


def within(a_pos, a_span, b_pos, b_span, feet: int) -> bool:
    return distance_ft(a_pos, a_span, b_pos, b_span) <= feet


def tile_of(point: Point) -> Tile:
    return int(math.floor(point[0] + EPS)), int(math.floor(point[1] + EPS))


def snap_corner(point: Point) -> Point:
    """The grid intersection nearest a point (where the DMG puts a sphere's origin)."""
    return float(round(point[0])), float(round(point[1]))


# ---------------------------------------------------------------------- areas
def area_tiles(shape: str, size: int, *, origin: Point, toward: Optional[Point] = None, width: int = 5,
               caster_box: Optional[Tuple[int, int, int, int]] = None, w: int = 999, h: int = 999, fw: int = 0) -> FrozenSet[Tile]:
    """Tiles an area covers.

    shape: sphere / cylinder (radius `size` around `origin`), emanation (every tile within `size` feet of `caster_box`,
    the caster's own tiles excluded), cone / line (from `origin` towards `toward`, `size` long, a line `width` wide),
    cube / square (`size` across; centred on `origin`, or - when `caster_box` is given - touching the caster on the side
    facing `toward`). fw: the map has floors that wide (floors.py) - the area stays on the floor of its origin.
    Results are cached."""
    key = (shape, int(size), _r(origin), _r(toward) if toward else None, int(width), caster_box, int(w), int(h), int(fw))
    return _area(*key)


def _r(p):
    return (round(float(p[0]), 3), round(float(p[1]), 3))


@lru_cache(maxsize=4096)
def _area(shape, size, origin, toward, width, caster_box, w, h, fw) -> FrozenSet[Tile]:
    n = size / FT
    ox, oy = origin
    out = set()
    x_lo, x_hi = 0, w
    if fw:                                                   # one floor of several: its own columns only
        x_lo = math.floor(ox / (fw + GAP)) * (fw + GAP)
        x_hi = min(w, x_lo + fw)

    def add(x, y):
        if x_lo <= x < x_hi and 0 <= y < h:
            out.add((x, y))

    if shape in ("sphere", "cylinder"):
        for x in range(int(math.floor(ox - n)) - 1, int(math.ceil(ox + n)) + 1):
            for y in range(int(math.floor(oy - n)) - 1, int(math.ceil(oy + n)) + 1):
                if math.hypot(x + .5 - ox, y + .5 - oy) <= n + EPS:
                    add(x, y)
        return frozenset(out)
    if shape == "emanation":
        x0, y0, x1, y1 = caster_box
        k = int(n)
        for x in range(x0 - k, x1 + k + 1):
            for y in range(y0 - k, y1 + k + 1):
                if not (x0 <= x <= x1 and y0 <= y <= y1):
                    add(x, y)
        return frozenset(out)
    dx, dy = (toward[0] - ox, toward[1] - oy) if toward else (1.0, 0.0)
    norm = math.hypot(dx, dy)
    ux, uy = (dx / norm, dy / norm) if norm > EPS else (1.0, 0.0)
    if shape in ("cube", "square"):
        if caster_box:                                       # touching the caster's side towards the aim (8 directions)
            sx = 0 if abs(ux) < .383 else (1 if ux > 0 else -1)
            sy = 0 if abs(uy) < .383 else (1 if uy > 0 else -1)
            x0, y0, x1, y1 = caster_box
            k = max(1, int(round(n)))
            if sx > 0:
                xs = range(x1 + 1, x1 + 1 + k)
            elif sx < 0:
                xs = range(x0 - k, x0)
            else:
                mid = (x0 + x1) // 2
                xs = range(mid - (k - 1) // 2, mid - (k - 1) // 2 + k)
            if sy > 0:
                ys = range(y1 + 1, y1 + 1 + k)
            elif sy < 0:
                ys = range(y0 - k, y0)
            else:
                mid = (y0 + y1) // 2
                ys = range(mid - (k - 1) // 2, mid - (k - 1) // 2 + k)
            for x in xs:
                for y in ys:
                    add(x, y)
            return frozenset(out)
        half = n / 2
        for x in range(int(math.floor(ox - half)) - 1, int(math.ceil(ox + half)) + 1):
            for y in range(int(math.floor(oy - half)) - 1, int(math.ceil(oy + half)) + 1):
                if abs(x + .5 - ox) <= half + EPS and abs(y + .5 - oy) <= half + EPS:
                    add(x, y)
        return frozenset(out)
    # cone and line start at the caster's edge
    reach = n + 1
    lo_x, hi_x = int(math.floor(ox - reach)) - 1, int(math.ceil(ox + reach)) + 1
    lo_y, hi_y = int(math.floor(oy - reach)) - 1, int(math.ceil(oy + reach)) + 1
    half_w = max(width / FT / 2, .5)
    for x in range(lo_x, hi_x):
        for y in range(lo_y, hi_y):
            vx, vy = x + .5 - ox, y + .5 - oy
            along = vx * ux + vy * uy
            if along <= EPS or along > n + EPS:
                continue
            side = abs(-vx * uy + vy * ux)
            if shape == "cone":
                if side <= along / 2 + EPS:
                    add(x, y)
            elif side <= half_w + EPS:
                add(x, y)
    if caster_box:
        x0, y0, x1, y1 = caster_box
        out = {t for t in out if not (x0 <= t[0] <= x1 and y0 <= t[1] <= y1)}
    return frozenset(out)


def edge_point(caster_box: Tuple[int, int, int, int], toward: Point) -> Point:
    """Where a cone or line leaves its caster: the point of the caster's square border facing `toward`."""
    x0, y0, x1, y1 = caster_box
    cx, cy = (x0 + x1 + 1) / 2, (y0 + y1 + 1) / 2
    dx, dy = toward[0] - cx, toward[1] - cy
    half = (x1 - x0 + 1) / 2
    m = max(abs(dx), abs(dy))
    if m < EPS:
        return cx + half, cy
    return cx + dx / m * half, cy + dy / m * half


def area_for(area: dict, caster_pos, caster_span: int, aim: Optional[Point], w: int, h: int, fw: int = 0) -> FrozenSet[Tile]:
    """The tiles of a spell's area, cast by a creature at (caster_pos, caster_span) and aimed at `aim` (a point).

    area: {'shape', 'size', 'width', 'origin': 'caster' | 'point'} (see spellbook)."""
    shape, size, width = area["shape"], int(area["size"]), int(area.get("width") or 5)
    cbox = box(caster_pos, caster_span) if caster_pos is not None else None
    if area.get("origin") == "caster" or aim is None:
        if cbox is None:
            return frozenset()
        if shape in ("sphere", "cylinder", "emanation"):
            return area_tiles("emanation", size, origin=centre(caster_pos, caster_span), caster_box=cbox, w=w, h=h, fw=fw) | (
                frozenset() if area.get("exclude_self", True) else footprint(caster_pos, caster_span))
        target = aim or (cbox[2] + 2.0, cbox[1] + .5)
        if shape in ("cube", "square"):
            return area_tiles("cube", size, origin=centre(caster_pos, caster_span), toward=target, caster_box=cbox, w=w, h=h, fw=fw)
        return area_tiles(shape, size, origin=edge_point(cbox, target), toward=target, width=width, caster_box=cbox, w=w, h=h, fw=fw)
    if shape in ("cone", "line"):                             # aimed: start at the caster, point at the aim
        if cbox is None:
            return frozenset()
        return area_tiles(shape, size, origin=edge_point(cbox, aim), toward=aim, width=width, caster_box=cbox, w=w, h=h, fw=fw)
    if shape == "emanation":
        shape = "sphere"
    return area_tiles(shape, size, origin=aim, width=width, w=w, h=h, fw=fw)


def creatures_in(tiles: Iterable[Tile], creatures: Iterable[dict]) -> list:
    """The creatures (dicts with 'pos' and 'span') any of whose tiles are in `tiles` - not the tokens of conjured things
    (Spiritual Weapon: a spell's effect, nothing an area catches) unless they have hit points to lose (Bigby's Hand)."""
    s = tiles if isinstance(tiles, (set, frozenset)) else set(tiles)
    return [c for c in creatures if c.get("pos") and not (c.get("conjured") and not c["conjured"].get("hittable"))
            and footprint(c["pos"], c.get("span") or 1) & s]


class TileIndex:
    """tile -> ids of the things (zones) covering it, for quick 'what is here' questions while creatures move."""

    def __init__(self):
        self.at = {}

    def add(self, key, tiles: Iterable[Tile]):
        for t in tiles:
            self.at.setdefault(tuple(t), set()).add(key)

    def keys_at(self, tiles: Iterable[Tile]) -> set:
        out = set()
        for t in tiles:
            out |= self.at.get(tuple(t), set())
        return out
