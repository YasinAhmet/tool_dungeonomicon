"""Dress a world map as an Inkarnate one is dressed (painted stamps, or their ink twins for the parchment looks): chains
of mountain ranges through the heart of each landmass with peaks and hills round them, woods with a dark forest floor
under them, trees between; snow in the far north, a dry south with its deserts, a marsh or two by the coast; rivers
running off the mountains to the sea; a compass rose, ships, a sea creature and waves on the water. Then settle it:
named towns on the rivers and coasts joined by roads, the land and the sea named. Nothing goes where a mark already
is, and only ground the DM left as the land's own is painted (numpy and the stamps' catalog; no Qt).

    spots, ground = dress.plan(mask, ground, marks, seed)          # spots: [(x, y, size, picture key)], ground: a new copy
    rivers = dress.rivers(mask, [(x, y), ...], seed)               # from those mountains: [[[x, y], ...], ...]
    towns, roads, n = dress.settle(mask, ground, marks, lines, seed)  # towns: [(x, y, size, key, name)], the first n the towns
    labels = dress.names(mask, labels, seed, avoid)                # [(text, x, y, size, style)]
    dress.twin(key, s, y, ink, pick)                               # a stamp's twin in the other set: (key, size, y)
"""
import heapq
import math
import random
from typing import List, Optional, Tuple

import numpy as np

from . import render as R
from . import stamps

SNOWY_RANGES = ("pt_range_2", "pt_range_3", "pt_range_8")
ROCKS = {   # a rock's ranges, and the lone peaks that go round them
    "brown": (("pt_range_1", "pt_range_1", "pt_range_2"), ("pt_mountain_1", "pt_mountain_2", "pt_peaks_1")),
    "grey": (("pt_range_5", "pt_range_3"), ("pt_mountain_6", "pt_peaks_2")),
    "green": (("pt_range_4",), ("pt_mountain_7", "pt_mountain_8", "pt_peaks_5")),
    "red": (("pt_range_6",), ("pt_mountain_9", "pt_peaks_6")),
    "dark": (("pt_range_7", "pt_range_9", "pt_range_8"), ("pt_mountain_6", "pt_peaks_2")),
}
SNOWY_PEAKS = ("pt_mountain_4", "pt_mountain_5", "pt_peak_big", "pt_peaks_3", "pt_peaks_4")
HILLS = ("pt_hills_2", "pt_hills_4", "pt_hills_5", "pt_hills_1")
DRY_HILLS = ("pt_hills_3", "pt_hills_6")
SNOWY_HILLS = ("pt_hills_snow_1", "pt_hills_snow_2")
DUNES = ("pt_dunes_1", "pt_dunes_2")
SHIPS = ("pt_ship_1", "pt_ship_2", "pt_boat")
MONSTERS = ("pt_serpent", "pt_whale", "pt_kraken")
WAVES = ("pt_waves_1", "pt_waves_2", "pt_waves_3")
CLIFFS = ("pt_cliffs_1", "pt_cliffs_2", "pt_cliffs_3")
MESAS = ("pt_mesa_1", "pt_mesa_2", "pt_mesa_3")
MARSHES = ("pt_marsh_1", "pt_marsh_2")
WOODS = ("pt_wood_1", "pt_wood_2", "pt_wood_5", "pt_wood_8", "pt_wood_6")
PINE_WOODS = ("pt_wood_3", "pt_wood_4")
SNOWY_WOODS = ("pt_wood_7",)
TREES = ("pt_tree_1", "pt_tree_2", "pt_tree_3", "pt_pine_1", "pt_pine_2")
TWINS = (   # painted family, its ink twin (a family: keys "<prefix><n>", or the one key itself)
    ("pt_village_", "ink_village_"), ("pt_town_", "ink_town_"), ("pt_city_", "ink_city_"), ("pt_castle_", "ink_castle"),
    ("pt_tower_", "ink_tower"), ("pt_range_", "ink_range_"), ("pt_mountain_", "ink_mountain_"), ("pt_hills_", "ink_hills_"),
    ("pt_wood_", "ink_wood_"), ("pt_tree_", "ink_tree_"), ("pt_pine_", "ink_pine_"), ("pt_palm_", "ink_palm_"),
    ("pt_deadtree_", "ink_deadtree_"), ("pt_dunes_", "ink_dunes_"), ("pt_cactus", "ink_cactus"), ("pt_volcano", "ink_volcano"),
    ("pt_cave", "ink_cave"), ("pt_stones", "ink_stones"), ("pt_ruins_", "ink_ruins"), ("pt_lighthouse", "ink_lighthouse"),
    ("pt_windmill", "ink_windmill"), ("pt_ship_", "ink_ship_"), ("pt_boat", "ink_rowboat"), ("pt_serpent", "ink_serpent"),
    ("pt_whale", "ink_whale"), ("pt_searocks", "ink_searocks"), ("pt_compass", "ink_compass"), ("pt_waves_", "ink_waves_"),
    ("pt_grass_", "ink_grass_"), ("pt_fields_", "ink_fields_"), ("pt_marsh_", "ink_swamp_"), ("pt_camp", "ink_camp_"),
    ("pt_bridge", "ink_bridge"), ("pt_kraken", "ink_kraken"), ("pt_whirlpool", "ink_whirlpool"), ("pt_farm_", "ink_farmstead"),
    ("pt_signpost", "ink_signpost"), ("pt_temple", "ink_temple"), ("pt_tree_", "ink_bush_"),
    # painted only: inked as the nearest
    ("pt_desert_town_", "ink_town_"), ("pt_harbour_", "ink_town_"), ("pt_peaks_", "ink_range_"), ("pt_peak_big", "ink_mountain_"),
    ("pt_hills_snow_", "ink_hills_"), ("pt_mesa_", "ink_cliffs"), ("pt_cliffs_", "ink_cliffs"), ("pt_great_tree", "ink_tree_"),
    ("pt_dark_tower", "ink_tower"),
    ("pt_sunken", "ink_ruins"), ("pt_dwarf_gate", "ink_cave"), ("pt_elf_city", "ink_town_"),
)
FLAT = ("pt_fields_", "pt_waves_", "pt_cloud_", "pt_compass", "pt_whirlpool")   # painted stamps that lie flat (they may turn)
ROAD_CELL = 8                                   # the grid roads find their ways over (map pixels)
TOPDOWN = (   # the top-down colour set (tools/build_world_art.py), family, and the painted family it is swapped for
    ("tree_", "pt_tree_"), ("autumn_", "pt_tree_"), ("bush_", "pt_tree_"), ("pine_", "pt_pine_"), ("palm_", "pt_palm_"),
    ("deadtree_", "pt_deadtree_"), ("clump_", "pt_wood_"), ("forest_", "pt_wood_"), ("wood_", "pt_wood_"), ("orchard_", "pt_wood_"),
    ("peak_", "pt_mountain_"), ("range_", "pt_range_"), ("hills_", "pt_hills_"), ("rocks_", "pt_boulders_"),
    ("rock_", "pt_boulders_"), ("stones_", "pt_stones"), ("dunes_", "pt_dunes_"), ("marsh_", "pt_marsh_"),
    ("village_", "pt_village_"), ("hamlet_", "pt_village_"), ("town_", "pt_town_"), ("city_", "pt_city_"),
    ("quarter_", "pt_city_"), ("harbor_", "pt_harbour_"), ("castle_", "pt_castle_"), ("keep_", "pt_castle_"),
    ("palace_", "pt_castle_"), ("roundtower_", "pt_tower_"), ("squaretower_", "pt_tower_"), ("lighthouse", "pt_lighthouse"),
    ("windmill_", "pt_windmill"), ("ruins_", "pt_ruins_"), ("camp_", "pt_camp"), ("tent_", "pt_camp"),
    ("house_", "pt_village_"), ("hiphouse_", "pt_village_"), ("lhouse_", "pt_village_"), ("barn_", "pt_farm_"),
    ("hall_", "pt_village_"), ("ship_", "pt_ship_"), ("bigship_", "pt_ship_"), ("sailboat_", "pt_boat"), ("rowboat_", "pt_boat"),
    ("serpent_", "pt_serpent"), ("whale", "pt_whale"), ("whirlpool", "pt_whirlpool"), ("searocks_", "pt_searocks"), ("waves_", "pt_waves_"),
    ("field_", "pt_fields_"), ("patchwork_", "pt_fields_"), ("hedgedfield_", "pt_fields_"), ("rose_", "pt_compass"),
    ("bridge_", "pt_bridge"), ("block_", "pt_village_"), ("pasture_", "pt_fields_"), ("vineyard_", "pt_fields_"),
    ("cathedral", "pt_temple"), ("church_", "pt_temple"),
)
RANGE_RX, RANGE_RY = 62.0, 22.0                 # about how far a painted range reaches round its middle (map pixels)
NORTH, SOUTH = 0.2, 0.8                         # the share of the map's height that is the cold north, the dry south


def _reach(m: dict) -> float:
    """About how far round its point a mark already on the map fills."""
    e = stamps.get(m.get("art")) if m.get("kind") == "art" else None
    return float(e["h"]) * float(m.get("s") or 1) * 0.6 if e else 8.0


SNOWY = {"pt_wood_7", "pt_pine_3", "pt_mountain_4", "pt_mountain_5", "pt_range_2", "pt_range_3", "pt_range_8", "pt_peaks_3", "pt_peaks_4"}


def _family(prefix: str) -> List[str]:
    """A family's pictures (not its snowy ones: a twin is picked for any land)."""
    if not prefix.endswith("_"):
        return [prefix] if stamps.get(prefix) else []
    return sorted((k for k in stamps.catalog() if k.startswith(prefix) and k[len(prefix):].isdigit() and k not in SNOWY),
                  key=lambda k: int(k[len(prefix):]))


def _of(key: str, family: str) -> bool:
    """Is the key one of the family's pictures? ("ink_tree_" holds ink_tree_3, "pt_hills_" not pt_hills_snow_1; a top-down
    family any of its kinds: "castle_" holds castle_blue, "field_" field_wheat_2; "ink_castle" is itself)"""
    if not family.endswith("_"):
        return key == family
    if not key.startswith(family) or key == family:
        return False
    rest = key[len(family):]
    return rest.isdigit() or (not family.startswith(("pt_", "ink_")) and rest.replace("_", "").isalnum())


def twin(key: str, s: float, y: float, ink: bool, pick: int):
    """The stamp's twin in the other set - ink for a painted one (ink True), painted for an ink or a top-down one - covering
    about the same ground: (key, size, y); None when it has none. pick: which of the family's pictures."""
    pairs = [(pt, ik, 0.75) for pt, ik in TWINS] if ink else \
        [(ik, pt, 1 / 0.75) for pt, ik in TWINS] + [(td, pt, 1.0) for td, pt in TOPDOWN]
    for mine, other, k in pairs:
        if _of(key, mine):
            fam = _family(other)
            if not fam:
                return None
            a, b = stamps.get(key), stamps.get(fam[pick % len(fam)])
            if not a:
                return None
            s2 = max(0.3, min(4.0, s * float(a["h"]) / float(b["h"]) * k))
            if a["anchor"] == "c" and b["anchor"] == "b":       # (a painted wood lies round its point; an ink one stands on it)
                y += float(b["h"]) * s2 / 2
            elif a["anchor"] == "b" and b["anchor"] == "c":
                y -= float(a["h"]) * s / 2
            return b["key"], round(s2, 2), round(y, 1)
    return None


def _inked(key: str, s: float, y: float, rng) -> tuple:
    """A painted stamp's ink twin (the ink set for the parchment looks): (key, size, y), about as big."""
    return twin(key, s, y, True, rng.randrange(1000)) or (key, s, y)


def plan(mask: np.ndarray, ground: np.ndarray, marks: List[dict], seed: int, ink: bool = False) -> Tuple[list, np.ndarray]:
    h, w = mask.shape
    rng = random.Random(seed)
    cover = (mask >= R.WATER).astype(np.float32)
    inland = R.blur(cover, 16.0)                                 # 1 deep in the land .. 0.5 at the coast .. 0 at sea
    kept, ground = ground, ground.copy()
    taken = [(m["x"], m["y"], _reach(m)) for m in marks]
    spots = []
    dry = rng.random() < 0.65                                   # (not every world has a dry south)

    ashore = R.blur(cover, 3.0) > 0.9                            # (off the water: a lake too small to dim `inland`)

    def deep(x, y, d):
        xi, yi = int(x), int(y)
        return 0 <= xi < w and 0 <= yi < h and inland[yi, xi] >= d and bool(ashore[yi, xi])

    def free(x, y, r):
        return all((x - a) ** 2 + (y - b) ** 2 >= (r + c) ** 2 for a, b, c in taken)

    def put(key, x, y, r, s=1.0, cx=None, cy=None):
        if not stamps.get(key):
            return False
        taken.append((x if cx is None else cx, y if cy is None else cy, r))
        if ink:
            key, s, y = _inked(key, s, y, rng)
        spots.append((round(x, 1), round(y, 1), round(s, 2), key))
        return True

    def zone(y):
        return "north" if y < h * NORTH else ("south" if dry and y > h * SOUTH else "mid")     # (about: lat wanders)

    def hills_for(y):
        return {"south": DRY_HILLS, "north": SNOWY_HILLS}.get(zone(y), HILLS)

    def paint(kind, x, y, rx, ry):                              # a ground where the DM left the land's own
        x0, y0, x1, y1 = max(0, int(x - rx)), max(0, int(y - ry)), min(w, int(x + rx + 1)), min(h, int(y + ry + 1))
        if x0 >= x1 or y0 >= y1:
            return
        ys = (np.arange(y0, y1, dtype=np.float32)[:, None] - y) / ry
        xs = (np.arange(x0, x1, dtype=np.float32)[None, :] - x) / rx
        part = ground[y0:y1, x0:x1]
        hit = (xs * xs + ys * ys <= 1.0) & (part & 15 == 0)
        part[hit] = (part[hit] & 0xF0) | kind

    land = int(cover.sum())
    if land < 400:
        return [], ground
    k = land / float(w * h)
    nrng = np.random.default_rng(seed)
    forest = R.fractal(h, w, [w / 5.0, w / 10.0, w / 24.0], nrng, 0.55)   # where the woods gather (> 0) and the open land is
    forest += 0.07 - float(np.quantile(forest[cover > 0], 0.66))  # (every world about a third wooded, whatever its noise)
    # the far north under snow, the south dry: their edges wandering
    lat = np.arange(h, dtype=np.float32)[:, None] / h + R.fractal(h, w, [w / 6.0, w / 16.0, w / 40.0], nrng, 0.5) * 0.12
    shores = R.blur(cover, 12.0) > 0.005                         # (the land and a little past it: the coast is drawn wandering)
    for zone_, kind in ((lat < NORTH, 5), (lat > SOUTH, 2 if dry else 0)):
        if kind:
            hit = zone_ & shores & (ground & 15 == 0)
            ground[hit] = (ground[hit] & 0xF0) | kind
    # chains of ranges through the heart of the land, foothills round them
    hearts = [(x, y) for y in range(8, h - 8, 6) for x in range(8, w - 8, 6) if inland[y, x] > 0.9]
    rng.shuffle(hearts)
    chains = max(1, int(k * 14))
    feet = []
    main = rng.choice(("brown", "grey", "grey", "dark", "brown", "green"))   # one rock for the world's mountains (and a
    second = rng.choice([r_ for r_ in ROCKS if r_ != main])                  # second for a few chains), as a map is painted
    tries_ = chains * 30                                        # (bounded: a land too narrow for any chain gives up soon)
    for x, y in hearts:
        if chains <= 0 or tries_ <= 0:
            break
        if not deep(x, y, 0.6) or not free(x, y, 46):
            continue
        tries_ -= 1
        laid = len(feet)
        a = rng.uniform(-0.9, 0.9) + (math.pi if rng.random() < 0.5 else 0.0)
        fam = main if rng.random() < 0.75 else second
        rock = rng.choice(ROCKS[fam][0])                        # one rock all along a chain
        for _ in range(rng.randint(3, 6)):
            if not (all(deep(x + dx, y + dy, 0.6) for dx in range(-48, 49, 8) for dy in (-14, 0, 10)) and free(x, y - 12, 34)):
                break
            snowy = zone(y) == "north"
            if put(rng.choice(SNOWY_RANGES) if snowy else rock, x, y + 12, 34, cy=y - 12):
                paint(5 if snowy else 6, x, y - 4, 58, 16)              # bare rock (or snow) under the range
            feet.append((x, y, snowy, fam))
            a += rng.uniform(-0.7, 0.7)
            x, y = x + math.cos(a) * 80, y + math.sin(a) * 55
        chains -= len(feet) > laid                              # (a chain that found no room doesn't count)
    for x, y, snowy, fam in feet:
        for _ in range(6):
            fx, fy = x + rng.uniform(-75, 75), y + rng.uniform(-35, 45)
            if deep(fx, fy, 0.6) and free(fx, fy, 11):
                put(rng.choice(SNOWY_PEAKS if snowy else ROCKS[fam][1]), fx, fy + 12, 11, rng.uniform(0.6, 0.85), cy=fy)
        for _ in range(6):
            hx, hy = x + rng.uniform(-95, 95), y + rng.uniform(-40, 60)
            if deep(hx, hy, 0.58) and free(hx, hy, 12):
                put(rng.choice(hills_for(hy)), hx, hy + 4, 12)
    # woods where the forest gathers, the forest floor dark under them
    for _ in range(int(k * 6000)):
        x, y = rng.uniform(10, w - 10), rng.uniform(10, h - 10)
        if not (deep(x, y, 0.58) and forest[int(y), int(x)] > 0.07 and free(x, y, 9 + rng.uniform(-2, 5))):   # (close: woods merge)
            continue
        z = zone(y)
        if z == "south" and rng.random() < 0.75:
            continue
        key = rng.choice(SNOWY_WOODS if z == "north" else PINE_WOODS if forest[int(y), int(x)] > 0.15 else WOODS)
        sz = rng.choice((0.45, 0.6, 0.75, 0.9, 1.0))
        e = stamps.get(key)
        hw, hh = (float(e["h"]) * sz * 0.9, float(e["h"]) * sz * 0.35) if e else (10.0, 4.0)
        if not all(deep(x + dx * hw, y + dy * hh, 0.52) for dx, dy in ((-1, 0), (1, 0), (0, -1), (0, 1), (-0.7, 0.7), (0.7, 0.7))):
            continue                                              # (all of it on the land)
        if put(key, x, y, 17 * sz, sz):
            e = stamps.get(key)
            paint(3, x, y + 1, float(e["h"]) * sz * 0.8, float(e["h"]) * sz * 0.4)
    # deserts in the dry south: dunes, mesas and cacti on the sand
    if dry:
        sand = (lat > SOUTH - 0.06) & (forest < 0.05) & (cover > 0) & np.isin(ground & 15, (0, 2))
        ground[sand] = (ground[sand] & 0xF0) | 4
        for _ in range(int(k * 2500)):
            x, y = rng.uniform(10, w - 10), rng.uniform(10, h - 10)
            if not (deep(x, y, 0.58) and (int(ground[int(y), int(x)]) & 15) == 4):
                continue
            roll = rng.random()
            if roll < 0.45 and free(x, y, 14):
                put(rng.choice(DUNES), x, y + 3, 14, rng.uniform(0.8, 1.1))
            elif roll < 0.6 and free(x, y, 11):
                put(rng.choice(MESAS), x, y + 3, 11, rng.uniform(0.8, 1.1))
            elif free(x, y, 3):
                put(rng.choice(("pt_cactus", "pt_palm_1", "pt_palm_2") if rng.random() < 0.3 else ("pt_cactus",)), x, y, 3, rng.uniform(0.7, 0.9))
    # a marsh or two in the low land by the coast
    for _ in range(max(1, round(k * 4))):
        for _try in range(300):
            x, y = rng.uniform(40, w - 40), rng.uniform(40, h - 40)
            if zone(y) == "mid" and deep(x, y, 0.55) and not deep(x, y, 0.75) and free(x, y, 30):
                paint(7, x, y, rng.uniform(28, 40), rng.uniform(14, 20))
                for _m in range(4):
                    mx, my = x + rng.uniform(-22, 22), y + rng.uniform(-9, 9)
                    if free(mx, my, 6):
                        put(rng.choice(MARSHES), mx, my, 6, rng.uniform(0.8, 1.1))
                break
    # a few hills out on the open land, and lone trees along the woods' edges
    for _ in range(int(k * 120)):                               # (hill country: a knot of hills round a seed, not hills everywhere)
        x, y = rng.uniform(10, w - 10), rng.uniform(10, h - 10)
        if not (deep(x, y, 0.62) and forest[int(y), int(x)] < -0.08):
            continue
        for _hill_ in range(rng.randint(3, 6)):
            hx, hy = x + rng.gauss(0, 22), y + rng.gauss(0, 10)
            if deep(hx, hy, 0.6) and free(hx, hy, 12):
                put(rng.choice(hills_for(hy)), hx, hy + 4, 12)
    bluffs = max(1, round(k * 6))
    for _ in range(int(k * 1500)):                              # a bluff or two breaking up the wide open plains
        if bluffs <= 0:
            break
        x, y = rng.uniform(40, w - 40), rng.uniform(40, h - 40)
        if zone(y) == "mid" and forest[int(y), int(x)] < -0.05 and all(deep(x + dx, y, 0.66) for dx in (-22, 0, 22)) and free(x, y, 22):
            bluffs -= 1
            sz, dy = rng.uniform(1.1, 1.4), rng.uniform(-0.25, 0.25)
            chain = [(x + i * 27 * sz, y + i * 27 * sz * dy) for i in range(rng.randint(1, 3))]   # (an escarpment)
            while len(chain) > 1 and not all(deep(cx_, cy_, 0.62) and free(cx_, cy_, 18) for cx_, cy_ in chain):
                chain.pop()
            for cx_, cy_ in chain:
                put(rng.choice(CLIFFS), cx_, cy_ + 3, 14 * sz, sz)
    for _ in range(int(k * 9000)):
        x, y = rng.uniform(6, w - 6), rng.uniform(6, h - 6)
        f = forest[int(y), int(x)]
        edge = -0.08 < f < 0.06
        if not (edge or rng.random() < 0.025) or zone(y) == "south":   # (thick along the woods; out in the open a few,
            continue                                                  # each a little clump)
        kind = ("pt_pine_3",) if zone(y) == "north" else TREES
        for _t in range(1 if edge else rng.randint(2, 4)):
            tx, ty = (x, y) if edge else (x + rng.gauss(0, 5), y + rng.gauss(0, 2.5))
            if deep(tx, ty, 0.55) and free(tx, ty, 3.5):
                put(rng.choice(kind), tx, ty, 3.5, rng.uniform(0.75, 0.95))
    # the sea: a compass rose in its emptiest corner, ships off the coasts, a creature far out, strokes of waves
    if not any("compass" in (m.get("art") or "") or m.get("kind") == "compass" for m in marks):
        def land_round(c, r):
            return float(cover[max(0, int(c[1]) - r):int(c[1]) + r, max(0, int(c[0]) - r):int(c[0]) + r].mean())
        corners = [(x_, y_) for y_ in (110.0, 160.0, h - 110.0, h - 160.0) for x_ in (110.0, 170.0, w - 110.0, w - 170.0)]
        open_ = [c for c in corners if land_round(c, 55) < 0.02 and free(c[0], c[1], 55)]
        if open_:
            cx, cy = min(open_, key=lambda c: land_round(c, 110))
            put("pt_compass", cx, cy, 60)
    sea = R.blur(cover, 10.0)
    for keys, lo, hi, n, r in ((SHIPS, 0.002, 0.08, 3, 16), (MONSTERS, 0.0, 0.002, 1, 24), (WAVES, 0.0, 0.01, 8, 14),
                               (("pt_searocks",), 0.12, 0.3, 3, 10)):
        got = 0
        for _ in range(n * 200):
            if got >= n:
                break
            x, y = rng.uniform(40, w - 40), rng.uniform(40, h - 40)
            if cover[int(y), int(x)] == 0 and lo <= sea[int(y), int(x)] <= hi and free(x, y, r):
                got += put(rng.choice(keys), x, y + (0 if keys is WAVES else 4), r, 1.6 if keys is WAVES else 0.7 if keys[0] == "pt_searocks" else 1.0)
    floes = 0 if ink else 8                                     # (the ink set has none)
    for _ in range(int(k * 600)):                               # ice floes in the cold sea off the north (a scatter)
        x, y = rng.uniform(40, w - 40), rng.uniform(30, h * NORTH * 1.2)
        if floes > 0 and cover[int(y), int(x)] == 0 and 0.0 < sea[int(y), int(x)] < 0.25 and free(x, y, 16):
            floes -= put(rng.choice(("pt_ice_1", "pt_ice_2", "pt_ice_3")), x, y, 16, rng.uniform(0.8, 1.2))
    steppe = (forest < -0.3) & shores & (ground & 15 == 0)         # dry grass out on the widest open land
    ground[steppe] = (ground[steppe] & 0xF0) | 2
    spots.sort(key=lambda sp: sp[1])
    return spots, (kept.copy() if ink else ground)              # (the ink looks: the ground as it was)


def rivers(mask: np.ndarray, sources: List[tuple], seed: int, most: int = 6) -> List[list]:
    """Rivers from the feet of the mountain ranges down to the sea, winding: each runs downhill (away from the heart
    of the land) until it reaches the sea or joins another river. [[x, y], ...] for each, from source to mouth."""
    h, w = mask.shape
    rng = random.Random(seed + 1)
    cover = (mask >= R.WATER).astype(np.float32)
    field = R.blur(cover, 24.0) + R.blur(cover, 8.0) * 0.3       # high in the land's heart, falling to its coasts
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    for sx, sy in sources:                                      # and high on the mountains: the rivers run off them
        field += np.exp(-((xx - sx) / RANGE_RX) ** 2 - ((yy - sy) / RANGE_RY) ** 2) * 0.5
    gy, gx = np.gradient(field)
    out: List[list] = []
    srcs = list(sources)
    rng.shuffle(srcs)
    for sx, sy in srcs:
        if len(out) >= most:
            break
        if not (0 <= sx < w and 0 <= sy < h):
            continue
        dx, dy = -gx[int(sy), int(sx)], -gy[int(sy), int(sx)]           # set off on the range's downhill side
        n = math.hypot(dx, dy) or 1.0
        x, y = float(sx + dx / n * 40 + rng.uniform(-20, 20)), float(sy + dy / n * 22 + rng.uniform(-4, 8))
        if not (0 <= x < w and 0 <= y < h) or cover[int(y), int(x)] < 1:
            continue
        pts, ang, phase, ended = [[round(x, 1), round(y, 1)]], None, rng.uniform(0, math.pi * 2), False
        for step in range(400):
            xi, yi = int(x), int(y)
            dx, dy = -float(gx[yi, xi]), -float(gy[yi, xi])
            down = math.atan2(dy, dx) if abs(dx) + abs(dy) > 1e-6 else (ang if ang is not None else rng.uniform(0, 6.28))
            ang = down if ang is None else ang + math.atan2(math.sin(down - ang), math.cos(down - ang)) * 0.35
            a = ang + math.sin(step * 0.3 + phase) * 0.55 + rng.uniform(-0.2, 0.2)
            x, y = x + math.cos(a) * 4.0, y + math.sin(a) * 4.0
            if not (0 <= x < w - 1 and 0 <= y < h - 1):
                break
            if step % 2:
                pts.append([round(x, 1), round(y, 1)])
            if cover[int(y), int(x)] < 1:                       # the sea (or a lake): its mouth
                pts.append([round(x, 1), round(y, 1)])
                ended = True
                break
            near = next((q for r in out for q in r if (q[0] - x) ** 2 + (q[1] - y) ** 2 < 36), None)
            if near and step > 6:                               # another river: it flows into it
                pts.append(list(near))
                ended = True
                break
        if ended and len(pts) >= 14:
            out.append(pts)
    return out


NAMES_A = ["Raven", "Stone", "Ash", "Elder", "Thorn", "Wolf", "Gold", "Mist", "Iron", "Oak", "Frost", "Amber", "Black", "Silver",
           "Red", "High", "Low", "Cold", "Brine", "Salt", "Willow", "Dun", "Kings", "Crow", "Hollow", "Bright", "Grey", "Marsh"]
NAMES_B = ["hold", "ford", "wick", "haven", "mere", "gate", "fall", "watch", "brook", "moor", "dale", "port", "stead", "hollow",
           "bury", "crest", "reach", "barrow", "march", "vale", "keep", "cairn", "field", "mouth"]


NAMES_TR = (["Kara", "Ak", "Demir", "Kızıl", "Gök", "Yeşil", "Taş", "Kurt", "Kartal", "Çam", "Meşe", "Ayaz", "Sarı", "Boz",
              "Yıldız", "Ulu", "Dumanlı", "Tuz", "Altın", "Gümüş", "Kuzgun", "Ilgın", "Sis", "Kaya"],
             ["köy", "kale", "hisar", "pınar", "dere", "yurt", "ova", "göl", "tepe", "liman", "kent", "yayla", "bağ", "beli",
              "kuyu", "çay", "dağ", "konak"])
LANG = "en"                                     # the names' language: "tr" for Turkish ones (the service sets it from the editor's)


def place_name(rng=random, avoid=()) -> str:
    """A made-up place name: Ravenhold, Saltmere, Dunwatch... (Karakale, Akpınar, Demirhisar... in Turkish); if it can,
    one that doesn't start or end like the names in `avoid` (starts())."""
    for _try in range(20):
        if LANG == "tr":
            name = rng.choice(NAMES_TR[0]) + rng.choice(NAMES_TR[1])
        else:
            a, b = rng.choice(NAMES_A), rng.choice(NAMES_B)
            while a.lower() == b or a[-1] == b[0]:              # (no Hollowhollow, no Oakkeep)
                b = rng.choice(NAMES_B)
            name = a + b
        if name[:4].lower() not in avoid and "~" + name[-4:].lower() not in avoid:
            break
    return name


def half_width(lab: dict) -> float:
    """About half a placed name's width (map pixels), by its size: for keeping other names off it."""
    size = int(lab.get("size") or 2)
    return len(lab.get("text") or "") * (11.5 if size >= 3 else 8.0 if size == 2 else 3.2)


def name_boxes(labels: List[dict]) -> List[tuple]:
    """The names on the map as (x, y, half width, size, how far its ends rise or fall when it's bent)."""
    def bend(lab):                                              # (one just made bows as it will once placed: arch())
        return float(lab["bend"]) if "bend" in lab else arch(lab["text"], lab.get("style") or "", int(lab.get("size") or 2))
    return [(lab["x"], lab["y"], half_width(lab), int(lab.get("size") or 2), half_width(lab) * abs(bend(lab)) * 0.0044)
            for lab in labels if lab.get("text")]


def in_use(labels: List[dict], made=()) -> set:
    """How the names on the map, and those just `made` ([(text, ...)]), start: starts() of them all."""
    return starts([lab.get("text") for lab in labels] + [m[0] for m in made])


def fresh_adjective(rng, labels: List[dict], made=()) -> str:
    """An adjective for a name (The Weeping Peaks) that no name on the map, or just `made`, has yet, if one is left."""
    have = " ".join([lab.get("text") or "" for lab in labels] + [m[0] for m in made])
    pool = LANDMARK_A_TR if LANG == "tr" else LANDMARK_A
    return rng.choice([w for w in pool if w not in have] or pool)


def starts(texts) -> set:
    """How the names in these texts start and end (their first four letters; "~" and their last four): what
    place_name(avoid=) keeps clear of - no Dunfield beside Duncairn, no Ashbury beside Coldbury."""
    words = [w for t in texts for w in (t or "").split() if len(w) > 3 and w[0].isupper()]
    return {w[:4].lower() for w in words} | {"~" + w[-4:].lower() for w in words if len(w) > 5}


def settle(mask: np.ndarray, ground: np.ndarray, marks: List[dict], lines: List[dict], seed: int, ink: bool = False):
    """Towns over the land as an Inkarnate map has them: a city or two, towns and villages along the coasts and the
    rivers, harbours on the shore, castles inland, desert towns on dry ground; each named, and joined by roads that
    keep to the land. (stamps [(x, y, size, key, name)], roads [[[x, y], ...]], how many of the stamps (the first) are towns)"""
    h, w = mask.shape
    rng = random.Random(seed + 7)
    cover = (mask >= R.WATER).astype(np.float32)
    inland = R.blur(cover, 16.0)
    land = int(cover.sum())
    if land < 400:
        return [], [], 0
    taken = [(m["x"], m["y"], 2.0 if "_wood_" in (m.get("art") or "")                   # (a town may stand in a wood's clearing;
              else 30.0 if any(t in (m.get("art") or "") for t in ("ship", "boat", "serpent", "whale"))   # ships keep off it)
              else max(10.0, _reach(m) * 0.7)) for m in marks]
    rivers_at = [tuple(p) for ln in lines if ln.get("style") == "river" for p in ln["pts"][2::3]]

    def free(x, y, r):
        return all((x - a) ** 2 + (y - b) ** 2 >= (r + c) ** 2 for a, b, c in taken)

    def at(x, y):
        return 0 <= int(x) < w and 0 <= int(y) < h

    n = max(3, int(land / float(w * h) * 30))
    snow = (ground & 15) == 5

    ranges = [(m["x"], m["y"] - 12) for m in marks if "range" in (m.get("art") or "") or "peaks" in (m.get("art") or "")]

    fronts = []                                                 # what is drawn over a spot: (x0, y0, x1, y1, its foot)
    for m in marks:
        e = stamps.get(m.get("art")) if m.get("kind") == "art" else None
        if not e:
            continue
        art, hh = e["key"], float(e["h"]) * float(m.get("s") or 1)
        wide = (2.8 if "_range_" in art else 1.7 if "_peaks_" in art else 1.3 if "mountain" in art or "_peak" in art
                else 2.0 if "_wood_" in art else 0.0)
        if wide:
            top = m["y"] - (hh / 2 if e["anchor"] == "c" else hh)
            fronts.append((m["x"] - hh * wide / 2, top, m["x"] + hh * wide / 2, m["y"] + (hh * 0.3 if e["anchor"] == "c" else 0)))

    def behind_wood(x, y):                                      # (a wood or a mountain further down the map is drawn over it)
        return any(x0 < x < x1 and y0 < y < foot + 4 and foot > y for x0, y0, x1, foot in fronts)

    def off_ranges(x, y, pad=14.0):                             # (a range is wide and low: an ellipse round it)
        return all(((x - rx) / (RANGE_RX + pad)) ** 2 + ((y - ry) / (RANGE_RY + pad)) ** 2 >= 1.0 for rx, ry in ranges)

    def ok(x, y):
        if not (30 <= x <= w - 120 and 36 <= y <= h - 24):       # (off the frame, room for the name to its right)
            return False
        if not (at(x, y) and inland[int(y), int(x)] >= 0.5 and cover[int(y), int(x)] > 0 and free(x, y, 16) and off_ranges(x, y)
                and not behind_wood(x, y)):
            return False
        return not (snow[int(y), int(x)] and rng.random() < 0.8)    # (few in the snow)
    picks = []

    def roomy_farm(x, y):                                       # (not on a town's name)
        return not any(px - 10 < x < px + 85 and abs(py - y) < 14 for px, py in picks)

    def roomy(x, y):                                            # (room for it and its name, written to its right)
        return all((x - a) ** 2 + (y - b) ** 2 >= 60 ** 2 and not (abs(x - a) < 105 and abs(y - b) < 26) for a, b in picks)
    for x, y in rng.sample(rivers_at, min(len(rivers_at), n // 3)):          # a few on the rivers
        if ok(x, y) and roomy(x, y):
            picks.append((x, y))
            taken.append((x, y, 16))
    for _ in range(n * 3):                                       # the rest spread out: of a few tries, the furthest from the others
        if len(picks) >= n:
            break
        cands = [(rng.uniform(12, w - 12), rng.uniform(12, h - 12)) for _ in range(40)]
        cands = [c for c in cands if ok(*c)]
        if not cands:
            continue
        x, y = max(cands, key=lambda c: min([(c[0] - a) ** 2 + (c[1] - b) ** 2 for a, b in picks] or [1e9]))
        if not roomy(x, y):
            continue
        picks.append((x, y))
        taken.append((x, y, 16))
    out = []
    names = {m.get("name") for m in marks if m.get("name")}         # (none twice, those on the map already too)
    for i, (x, y) in enumerate(picks):
        coast = inland[int(y), int(x)] < 0.62
        dry = (int(ground[int(y), int(x)]) & 15) in (2, 4)
        if i == 0 or (i % 7 == 0):
            key = "pt_city_%d" % rng.randint(1, 2)
        elif coast and rng.random() < 0.55:
            key = "pt_harbour_%d" % rng.randint(1, 2)
        elif dry:
            key = "pt_desert_town_%d" % rng.randint(1, 2)
        elif rng.random() < 0.12:
            key = "pt_castle_%d" % rng.randint(1, 3)
        elif rng.random() < 0.45:
            key = "pt_town_%d" % rng.randint(1, 2)
        else:
            key = "pt_village_%d" % rng.randint(1, 3)
        name = place_name(rng)
        for _try in range(60):                                  # (a port by the sea; no Goldbarrow beside Coldbarrow)
            if not (name in names or (not coast and name.endswith(("port", "haven", "mouth", "liman")))
                    or any(n_[-4:] == name[-4:] or n_[:4] == name[:4] for n_ in names)):
                break
            name = place_name(rng)
        if name in names:
            continue
        names.add(name)
        s, yy = 1.0, y + 6
        if ink:
            key, s, yy = _inked(key, s, yy, rng)
        if stamps.get(key):
            out.append((round(x, 1), round(yy, 1), round(s, 2), key, name))
    towns_only = len(out)
    # a few landmarks, each where it belongs and named: a volcano among the mountains, a great tree or a dark tower in
    # the woods, ruins, a temple, standing stones or a cave out in the open land
    peaks = [(m["x"], m["y"]) for m in marks if any(t in (m.get("art") or "") for t in ("_range_", "_peaks_", "_mountain_"))]
    woods = [(m["x"], m["y"]) for m in marks if "_wood_" in (m.get("art") or "")]
    wants = [("pt_volcano", peaks, "Mount {n}"), ("pt_great_tree", woods, "The {a} Oak"), ("pt_dark_tower", woods, "The {a} Spire"),
             ("pt_ruins_1", None, "Ruins of {n}"), ("pt_temple", None, "Temple of the {a} Moon"),
             ("pt_stones", None, "The {a} Stones"), ("pt_cave", peaks, "The {a} Caves"),
             ("pt_dwarf_gate", peaks, "The Halls of {n}"), ("pt_elf_city", woods, "{n} Glade")]
    rng.shuffle(wants)
    for key, near_, label in wants[:rng.randint(2, 3)]:
        for _try in range(400):
            if near_:
                bx, by = rng.choice(near_)                       # (just beside it: it fills its own ground)
                a_, d_ = rng.uniform(0, math.pi * 2), rng.uniform(30, 75)
                x, y = bx + math.cos(a_) * d_, by + math.sin(a_) * d_ * 0.6
            else:
                x, y = rng.uniform(40, w - 60), rng.uniform(40, h - 30)
            inside = 30 <= x <= w - 60 and 36 <= y <= h - 24 and cover[int(y), int(x)] > 0 and inland[int(y), int(x)] >= 0.55
            if inside and free(x, y, 7) and off_ranges(x, y, 2.0) and roomy(x, y) and not behind_wood(x, y):
                tr_ = LANG == "tr"
                name = (LANDMARKS_TR[key] if tr_ else label).format(n=place_name(rng), a=rng.choice(LANDMARK_A_TR if tr_ else LANDMARK_A))
                if x + 14 + len(name) * 6.2 > w - 16:               # (its name all on the sheet)
                    continue
                k2, s2, y2 = (key, 1.0, y + 6)
                if ink:
                    k2, s2, y2 = _inked(key, 1.0, y + 6, rng)
                if stamps.get(k2):
                    out.append((round(x, 1), round(y2, 1), round(s2, 2), k2, name))
                    picks.append((x, y))
                    taken.append((x, y, 16))
                break
    # roads: the shortest net joining the towns, each leg a way found over the land (round the sea and the mountains,
    # through the woods only where it must), and a few more short legs
    pts = [(x, y) for x, y, *_ in out[:towns_only]]              # (the landmarks stand off the roads)
    cell = ROAD_CELL
    gh, gw = h // cell, w // cell
    small = cover[:gh * cell, :gw * cell].reshape(gh, cell, gw, cell).mean(axis=(1, 3)) > 0.4   # (much of it land: off a narrow lake)
    cost = np.where(small, 1.0, np.inf)
    gy_, gx_ = np.mgrid[0:gh, 0:gw]
    cx_, cy_ = gx_ * cell + cell / 2, gy_ * cell + cell / 2
    for rx, ry in ranges:                                       # mountains: very dear; woods: dearer than open land
        cost[((cx_ - rx) / RANGE_RX) ** 2 + ((cy_ - ry) / RANGE_RY) ** 2 < 1.0] += 14.0
    for x0, y0, x1, foot in fronts:
        if foot - y0 < 60 and x1 - x0 < 140:                    # (a wood, or a lone peak)
            cost[(cx_ > x0) & (cx_ < x1) & (cy_ > y0 + (foot - y0) * 0.4) & (cy_ < foot)] += 1.5

    def way(a, b):
        """The cheapest way between two points over the grid (A*), or None; as map points, smoothed."""
        def snap(p):                                            # (a coastal town's foot may be in the water: the land by it)
            c = (min(gh - 1, int(p[1] // cell)), min(gw - 1, int(p[0] // cell)))
            if np.isfinite(cost[c]):
                return c
            near_ = [(abs(dy) + abs(dx), (c[0] + dy, c[1] + dx)) for dy in range(-3, 4) for dx in range(-3, 4)
                     if 0 <= c[0] + dy < gh and 0 <= c[1] + dx < gw and np.isfinite(cost[c[0] + dy, c[1] + dx])]
            return min(near_)[1] if near_ else None
        sa, sb = snap(a), snap(b)
        if sa is None or sb is None:
            return None
        best = {sa: 0.0}
        came = {}
        todo = [(0.0, sa)]
        while todo:
            _f, cur = heapq.heappop(todo)
            if cur == sb:
                break
            for dy, dx, ln in ((0, 1, 1.0), (1, 0, 1.0), (0, -1, 1.0), (-1, 0, 1.0), (1, 1, 1.41), (1, -1, 1.41), (-1, 1, 1.41), (-1, -1, 1.41)):
                nb = (cur[0] + dy, cur[1] + dx)
                if not (0 <= nb[0] < gh and 0 <= nb[1] < gw) or not np.isfinite(cost[nb]):
                    continue
                g_ = best[cur] + ln * (cost[nb] + cost[cur]) / 2
                if g_ < best.get(nb, np.inf):
                    best[nb], came[nb] = g_, cur
                    heapq.heappush(todo, (g_ + math.hypot(nb[0] - sb[0], nb[1] - sb[1]), nb))
        if sb not in came and sb != sa:
            return None
        cells = [sb]
        while cells[-1] != sa:
            cells.append(came[cells[-1]])
        cells.reverse()
        line = [list(a)] + [[c[1] * cell + cell / 2, c[0] * cell + cell / 2] for c in cells[1:-1]] + [list(b)]
        for _ in range(2):                                      # (smoothed: no stair steps)
            line = [line[0]] + [[(p[0] + q[0] * 2 + r[0]) / 4, (p[1] + q[1] * 2 + r[1]) / 4]
                                for p, q, r in zip(line, line[1:], line[2:])] + [line[-1]]
        keep = [line[0]] + line[1:-1][::2] + [line[-1]]
        length = sum(math.dist(p_, q_) for p_, q_ in zip(line, line[1:]))
        return [[round(float(x), 1), round(float(y), 1)] for x, y in keep], length
    legs = sorted((math.dist(pts[i], pts[j]), i, j) for i in range(len(pts)) for j in range(i + 1, len(pts))
                  if math.dist(pts[i], pts[j]) < 420)
    group = list(range(len(pts)))

    def root(i):
        while group[i] != i:
            i = group[i]
        return i
    roads = []
    for d, i, j in legs:
        joins = root(i) != root(j)
        if not (joins or (d < 150 and rng.random() < 0.3)):
            continue
        got = way(pts[i], pts[j])
        if got and got[1] < d * 1.9:                            # (not a way round half the continent)
            if joins:
                group[root(i)] = root(j)
            roads.append(got[0])
    # bridges where the roads cross a river or a narrow strait
    rivers_ = [ln["pts"] for ln in lines if ln.get("style") == "river" and len(ln.get("pts") or []) > 1]
    spans = []
    for road in roads:
        for (ax, ay), (bx, by) in zip(road, road[1:]):
            for rv in rivers_:                                  # (a river: where the two lines cross)
                for (px, py), (qx, qy) in zip(rv, rv[1:]):
                    den = (bx - ax) * (qy - py) - (by - ay) * (qx - px)
                    if abs(den) < 1e-6:
                        continue
                    t = ((px - ax) * (qy - py) - (py - ay) * (qx - px)) / den
                    u = ((px - ax) * (by - ay) - (py - ay) * (bx - ax)) / den
                    if 0 <= t <= 1 and 0 <= u <= 1:
                        spans.append((ax + (bx - ax) * t, ay + (by - ay) * t))
        walk = [(ax + (bx - ax) * k / n_, ay + (by - ay) * k / n_)    # (the way every few pixels)
                for (ax, ay), (bx, by) in zip(road, road[1:]) for n_ in [max(1, int(math.dist((ax, ay), (bx, by)) / 3))]
                for k in range(n_)] + [tuple(road[-1])]
        wet = [cover[min(h - 1, int(y)), min(w - 1, int(x))] == 0 for x, y in walk]   # (the sea: a short run over water)
        i = 0
        while i < len(wet):
            if wet[i]:
                j = i
                while j + 1 < len(wet) and wet[j + 1]:
                    j += 1
                if 0 < i and j + 1 < len(wet) and math.dist(walk[i - 1], walk[j + 1]) < 60:
                    spans.append(((walk[i - 1][0] + walk[j + 1][0]) / 2, (walk[i - 1][1] + walk[j + 1][1]) / 2))
                i = j + 1
            i += 1
    built = []
    for x, y in spans:
        if len(built) < 10 and all(math.dist((x, y), q) > 30 for q in built) and all(math.dist((x, y), p) > 18 for p in pts):
            key, s_, yy = "pt_bridge", 0.8, y + 2
            if ink:
                key, s_, yy = _inked(key, s_, yy, rng)
            if stamps.get(key):
                out.append((round(float(x), 1), round(float(yy), 1), round(s_, 2), key, ""))
                built.append((x, y))
    # a boat or two moored off each harbour
    for x, y, _s, key, _n in out[:towns_only]:
        if "harbour" not in key and "ink_town" not in key:
            continue
        for _try in range(30):
            a_, d_ = rng.uniform(0, math.pi * 2), rng.uniform(22, 40)
            bx, by = x + math.cos(a_) * d_, y + math.sin(a_) * d_ * 0.6
            if at(bx, by) and cover[int(by), int(bx)] == 0 and inland[int(by), int(bx)] > 0.12 and free(bx, by, 6):
                bkey, bs, byy = "pt_boat", 0.8, by + 2
                if ink:
                    bkey, bs, byy = _inked(bkey, bs, byy, rng)
                if stamps.get(bkey):
                    out.append((round(bx, 1), round(byy, 1), round(bs, 2), bkey, ""))
                    taken.append((bx, by, 6))
                break
    # farms on the open land round the towns
    for x, y, *_r in out[:towns_only]:
        for _try in range(10):
            a_, d_ = rng.uniform(0, math.pi * 2), rng.uniform(26, 48)
            fx, fy = x + math.cos(a_) * d_, y + math.sin(a_) * d_ * 0.6
            ok_ = at(fx, fy + 4) and cover[int(fy), int(fx)] > 0 and cover[int(fy + 4), int(fx)] > 0 and inland[int(fy), int(fx)] >= 0.6
            if ok_ and (int(ground[int(fy), int(fx)]) & 15) not in (4, 5) and free(fx, fy, 12) and off_ranges(fx, fy) \
                    and not behind_wood(fx, fy) and roomy_farm(fx, fy):
                key, s_, yy = "pt_farm_%d" % rng.randint(1, 3), 1.0, fy + 4
                if ink:
                    key, s_, yy = _inked(key, s_, yy, rng)
                if stamps.get(key):
                    out.append((round(fx, 1), round(yy, 1), round(s_, 2), key, ""))
                    taken.append((fx, fy, 12))
                break
    return out, roads, towns_only


SEAS_TR = ["{a} Deniz", "{n} Denizi", "{a} Sular", "{n} Körfezi"]
SEA_A_TR = ["Sessiz", "Fırtınalı", "Gümüş", "Gri", "Kehribar", "Fısıldayan", "Donmuş", "Safir", "Yaslı", "Zümrüt"]
REALMS_TR = ["{n} Krallığı", "{n} Diyarı", "{n} Beyliği", "Özgür {n} Toprakları"]
LANDMARKS_TR = {"pt_volcano": "{n} Dağı", "pt_great_tree": "{a} Meşe", "pt_dark_tower": "{a} Kule", "pt_ruins_1": "{n} Harabeleri",
                "pt_temple": "{a} Ay Tapınağı", "pt_stones": "{a} Taşlar", "pt_cave": "{a} Mağaralar",
                "pt_dwarf_gate": "{n} Cüce Kapısı", "pt_elf_city": "{n} Ormanı"}
LANDMARK_A_TR = ["Kara", "Kadim", "Ağlayan", "Yanan", "Sessiz", "Kovuk", "Batık", "Fısıldayan", "Solgun", "Kızıl", "Küllü"]
LANDMARK_A = ["Black", "Elder", "Weeping", "Burning", "Silent", "Hollow", "Sunken", "Whispering", "Pale", "Crimson", "Ashen"]
SEAS = ["The {a} Sea", "Sea of {n}", "The {a} Deep", "{n} Bay", "The {a} Waters"]
SEA_A = ["Sundered", "Silent", "Shimmering", "Grey", "Amber", "Whispering", "Frozen", "Sapphire", "Stormy", "Mourning", "Emerald"]
REALMS = ["Kingdom of {n}", "The {n} Reach", "{n} March", "Realm of {n}", "The Free Lands of {n}"]


def names(mask: np.ndarray, labels: List[dict], seed: int, avoid=()) -> List[tuple]:
    """Names for the land and the sea, where an Inkarnate map writes them: a realm's name across the heart of the land,
    a sea's in the widest open water; clear of the map's edges, of the points in `avoid` (towns) and of the names on it
    already. [(text, x, y, size, style)]"""
    h, w = mask.shape
    rng = random.Random(seed + 13)
    cover = (mask >= R.WATER).astype(np.float32)
    if cover.sum() < 400:
        return []
    near = [(lab["x"], lab["y"]) for lab in labels]
    named = {lab.get("style") for lab in labels if lab.get("style") == "region" or (lab.get("style") == "sea" and not lab.get("angle")
             and int(lab.get("size") or 2) >= 2 and 0 <= int(lab["y"]) < h and 0 <= int(lab["x"]) < w and cover[int(lab["y"]), int(lab["x"])] == 0)}

    def spot(score, text, per_char, water, towns=True):
        """The best-scoring point (lowest) whose name's box fits: inside the map, off the towns, on land or at sea."""
        hw, hh = len(text) * per_char / 2 + 8, 16
        if w - 2 * hw - 48 < 6 or h - 2 * hh - 60 < 6:            # (a map too small for it)
            return None
        ys, xs = np.mgrid[int(hh + 30):int(h - hh - 30):6, int(hw + 24):int(w - hw - 24):6]     # (off the frame)
        if not xs.size:
            return None
        order = np.argsort(score[ys, xs], axis=None)[:3000]
        for k in order:
            x, y = float(xs.flat[k]), float(ys.flat[k])
            if (cover[int(y), int(x)] == 0) != water:
                continue
            if towns and any(px - 8 - hw < x < px + 75 + hw and abs(py - y) < hh + 16 for px, py in avoid):  # (a town and its name)
                continue
            if any(math.dist((x, y), q) < 160 for q in near):
                continue
            return round(x, 1), round(y, 1)
        return None
    out = []
    used = starts(lab.get("text") for lab in labels)
    land_name = realm_title(rng, used)
    for text, score, per_char, water, style in (
            (land_name, -R.blur(cover, 40.0), 22.0, False, "region"),
            (rng.choice(SEAS_TR if LANG == "tr" else SEAS).format(a=rng.choice(SEA_A_TR if LANG == "tr" else SEA_A),
                                                                  n=place_name(rng, used | starts([land_name]))),
             R.blur(cover, 30.0) + R.blur(cover, 90.0), 13.0, True, "sea")):
        if style in named:                                      # (named already: a second settling adds none)
            continue
        for size, k, towns in ((3, 1.0, True), (2, 0.67, True), (2, 0.67, False)):   # (smaller when it doesn't fit; at
            at = spot(score, text, per_char * k, water, towns)                    # last over a town's name)
            if at:
                out.append((text, at[0], at[1], size, style))
                break
    return out


def realm_names(ground: np.ndarray, labels: List[dict], seed: int, avoid=(), mask: Optional[np.ndarray] = None) -> List[tuple]:
    """A name for each realm painted on the map (render.REALMS), across its middle (of its land, given the `mask`);
    none for a realm with a name near its middle already. [(text, x, y, size, "region")]"""
    rng = random.Random(seed + 29)
    realms = ground >> 4
    if mask is not None:                                        # (a realm's reach out to sea: not where its name goes)
        realms = np.where(mask >= R.WATER, realms, 0)
    out = []
    near = [(lab["x"], lab["y"]) for lab in labels if lab.get("style") not in ("sea", "title")]   # (a river's name is no realm's)
    H, W = realms.shape
    has = {int(realms[int(lab["y"]), int(lab["x"])]) for lab in labels
           if lab.get("style") == "region" and 0 <= int(lab["y"]) < H and 0 <= int(lab["x"]) < W}
    for k in sorted(int(v) for v in np.unique(realms) if v):
        if k in has:
            continue
        ys, xs = np.nonzero(realms == k)
        if xs.size < 400:
            continue
        x, y = float(np.median(xs)), float(np.median(ys))
        inside = realms[int(y), int(x)] == k
        if not inside:                                          # (a crescent: its middle outside it) the nearest of its own
            i = int(np.argmin((xs - x) ** 2 + (ys - y) ** 2))
            x, y = float(xs[i]), float(ys[i])
        if any(math.dist((x, y), q) < 120 for q in near):
            continue
        used = in_use(labels, out)
        boxes = [(lab["x"], lab["y"], len(lab.get("text") or "") * (11.5 if int(lab.get("size") or 2) >= 3 else 8.0))
                 for lab in labels if lab.get("text")]
        boxes += [(bx, by, len(t_) * (11.0 if sz == 3 else 7.5)) for t_, bx, by, sz, _st in out]
        tries = sorted(((dx, dy) for dy in range(-120, 121, 30) for dx in range(-150, 151, 50)), key=lambda t: abs(t[0]) * 0.6 + abs(t[1]))
        sizes = (3, 2) if xs.size > 40000 else (2,)
        found = None                                            # (fit, text, x, y, size): the best way found to name it
        for short in (False, True):                             # (a shorter title when the long one won't lie on it)
            text = realm_title(rng, used, short)
            for size in sizes:                                  # (smaller when it won't fit by the sheet's edge)
                hw = len(text) * (11.0 if size == 3 else 7.5)
                x0 = min(max(x, hw + 30), W - hw - 30)           # (all of it on the sheet)
                for dx, dy in tries:                            # (off the towns' names and the other names)
                    xx, yy = min(max(x0 + dx, hw + 30), W - hw - 30), y + dy
                    if not (30 < yy < H - 30 and 0 <= xx < W and realms[int(yy), int(xx)] == k):
                        continue
                    if any(px - 8 - hw < xx < px + 75 + hw and abs(py - yy) < 26 for px, py in avoid):
                        continue
                    if any(abs(bx - xx) < hw + bw and abs(by - yy) < (48 if size == 3 else 34) for bx, by, bw in boxes):
                        continue
                    fit = sum(realms[int(yy), min(W - 1, max(0, int(xx + t * hw * 0.9)))] == k for t in np.linspace(-1, 1, 9)) / 9.0
                    score = fit if size == 2 or fit == 1.0 else fit - 0.25   # (big letters only all over their realm)
                    if found is None or score > found[0] + 1e-6:  # (all of it over the realm's own land, best; big before small)
                        found = (score, text, round(xx, 1), round(yy, 1), size)
                    if fit == 1.0:
                        break
                if found and found[0] == 1.0:
                    break
            if found and found[0] >= 0.75:
                break
        if found:
            out.append((found[1], found[2], found[3], found[4], "region"))
    return out


def realm_title(rng, avoid=(), short: bool = False) -> str:
    """A realm's name ("Kingdom of Eldermarch"), never one that says the same word twice ("Eldermarch March"); `short`:
    one of the shorter forms (for a small realm)."""
    forms = REALMS_TR if LANG == "tr" else REALMS
    if short:
        forms = sorted(forms, key=len)[:3]
    n = place_name(rng, avoid)
    form = rng.choice([f for f in forms if f.replace("{n}", "").strip().split()[-1].lower() not in n.lower()] or forms)
    return form.format(n=n)


def divide(mask: np.ndarray, ground: np.ndarray, marks: List[dict], seed: int, n: int = 0) -> np.ndarray:
    """The land split into realms round its biggest towns (cities first; else spread points), its borders wandering:
    a new ground with the realms in its high four bits (where none was painted yet)."""
    h, w = mask.shape
    rng = np.random.default_rng(seed + 31)
    cover = mask >= R.WATER
    out = ground.copy()
    if cover.sum() < 400:
        return out
    rank = {"pt_city": 0, "pt_castle": 1, "pt_town": 2, "pt_harbour": 2, "pt_desert": 2, "ink_city": 0, "ink_castle": 1, "ink_town": 2}
    seats = sorted(((next((v for k, v in rank.items() if (m.get("art") or "").startswith(k)), 9), m["x"], m["y"]) for m in marks
                    if m.get("name") and m.get("kind") == "art"), key=lambda t: t[0])
    n = n or max(2, min(len(R.REALMS), int(cover.sum() / (w * h) * 9) + 1))
    used = {int(v) for v in np.unique(out >> 4) if v}
    spare = [k for k in range(1, len(R.REALMS) + 1) if k not in used]   # (a painted realm keeps its own: none merge)
    n = min(n, len(spare))
    if not n:
        return out
    pts = []
    for _r, x, y in seats:                                      # the seats of power, spread apart
        if len(pts) < n and all(math.dist((x, y), p) > min(w, h) * 0.22 for p in pts):
            pts.append((x, y))
    ys, xs = np.nonzero(cover)
    while len(pts) < n:                                         # (too few towns: points on the land, spread apart)
        i = int(rng.integers(xs.size))
        if all(math.dist((xs[i], ys[i]), p) > min(w, h) * 0.22 for p in pts) or rng.random() < 0.02:
            pts.append((float(xs[i]), float(ys[i])))
    wx = R.fractal(h, w, [w / 8.0, w / 20.0, w / 50.0], rng, 0.55) * w * 0.06
    wy = R.fractal(h, w, [w / 8.0, w / 20.0, w / 50.0], rng, 0.55) * w * 0.06
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    xx, yy = xx + wx, yy + wy                                   # (warped: the borders wander like real ones)
    best = np.full((h, w), np.inf, np.float32)
    owner = np.zeros((h, w), np.uint8)
    for k, (px, py) in zip(spare, pts):
        d = (xx - px) ** 2 + (yy - py) ** 2
        closer = d < best
        best[closer], owner[closer] = d[closer], k
    free_ = cover & ((out >> 4) == 0)
    out[free_] = (out[free_] & 15) | (owner[free_] << 4)
    sea_ = ~cover & ((out >> 4) == 0) & (R.blur(cover.astype(np.float32), 12.0) > 0.01)   # (out to sea as far as the drawn
    ids = [int(v) for v in np.unique(out[cover] >> 4) if v]                               # coast wanders, render.WARP: each
    if sea_.any() and ids:                                                                # stretch the realm of its nearest land)
        near_ = np.stack([R.blur((cover & ((out >> 4) == k)).astype(np.float32), 12.0) for k in ids])
        pick = np.asarray(ids, np.uint8)[np.argmax(near_, axis=0)]
        out[sea_] = (out[sea_] & 15) | (pick[sea_] << 4)
    return out


RIVERS = ["The {n} River", "River {n}", "The {n}"]
RIVERS_TR = ["{n} Irmağı", "{n} Çayı", "{n} Suyu"]


def river_names(lines: List[dict], labels: List[dict], seed: int, avoid=(), most: int = 3) -> List[tuple]:
    """Names for the longest rivers, written beside them and turned along their course, as an Inkarnate map labels them.
    [(text, x, y, size, "sea", angle)]"""
    rng = random.Random(seed + 41)
    rivers = sorted((ln for ln in lines if ln.get("style") == "river" and len(ln.get("pts") or []) >= 6),
                    key=lambda ln: -sum(math.dist(a, b) for a, b in zip(ln["pts"], ln["pts"][1:])))
    near = [(lab["x"], lab["y"]) for lab in labels]
    boxes = name_boxes(labels)
    out = []
    for ln in rivers[:most]:
        pts = ln["pts"]
        for f in (0.45, 0.6, 0.3):                              # where along it: the middle, else either side
            i = max(1, min(len(pts) - 2, int(len(pts) * f)))
            (ax, ay), (bx, by) = pts[i - 1], pts[i + 1]
            ang = math.degrees(math.atan2(by - ay, bx - ax))
            if ang > 90:                                         # (never upside down)
                ang -= 180
            elif ang < -90:
                ang += 180
            if abs(ang) > 65:
                continue
            nx, ny = -math.sin(math.radians(ang)), math.cos(math.radians(ang))
            x, y = pts[i][0] + nx * 7, pts[i][1] + ny * 7          # (beside it, not on it)
            if any(math.dist((x, y), q) < 60 for q in near + [(o[1], o[2]) for o in out]):
                continue
            text = rng.choice(RIVERS_TR if LANG == "tr" else RIVERS).format(n=place_name(rng, in_use(labels, out)))
            hw = len(text) * 3.2                                  # (about half its width: size 1 italic)
            if any(px - 10 - hw < x < px + 90 + hw and abs(py - y) < 20 + hw * abs(math.sin(math.radians(ang)))
                   for px, py in avoid):                          # (a town and its name)
                continue
            rise = hw * abs(math.sin(math.radians(ang)))        # (turned: it reaches up and down as far)
            if any(abs(bx - x) < hw + bw and abs(by - y) < 18 + rise + br + (14 if bs >= 3 else 4) for bx, by, bw, bs, br in boxes):
                continue                                        # (off the other names, all their width)
            out.append((text, round(x, 1), round(y, 1), 1, "sea", round(ang, 1)))
            break
    return out


SEA_DECOR = ("waves", "_ice_", "searocks", "cloud")             # (small things a title may lie over: not ships or monsters)


def title_spot(mask: np.ndarray, name: str, labels: List[dict], marks: List[dict], inset: float = 0.0) -> Optional[tuple]:
    """Where the map's own name goes as its title (size 3, flourishes either side): along the top or the bottom of the
    sheet, wherever the sea is widest and nothing else is drawn; None when there's no open water for it. (x, y)"""
    h, w = mask.shape
    hw, hh = len(name) * 15.0 + 78.0, 22.0                       # (its letters and their flourishes, half of each)
    if not name.strip() or hw * 2 + 60 > w:
        return None
    cover = (mask >= R.WATER).astype(np.float32)
    best = None
    for y in (54.0 + inset, h - 50.0 - inset):                  # (inset: further in, past a frame of clouds)
        for x in (w / 2, hw + 34 + inset, w - hw - 34 - inset, w * 0.3, w * 0.7):
            x0, x1, y0, y1 = int(x - hw), int(x + hw), int(y - hh), int(y + hh)
            if x0 < 30 + inset or x1 > w - 30 - inset:               # (clear of the frame)
                continue
            land = float(cover[y0:y1, x0:x1].mean())
            busy = sum(0.1 if any(t in (m.get("art") or "") for t in SEA_DECOR) else 1.0      # (waves and floes: a title may
                       for m in marks if x0 - 12 < m["x"] < x1 + 12 and y0 - 30 < m["y"] < y1 + 16)  # lie over them)
            busy += sum(3 for lab in labels if abs(lab["x"] - x) < hw + len(lab.get("text") or "") * 6 and abs(lab["y"] - y) < hh + 20)
            score = land * 10 + busy + (0 if x == w / 2 else 0.3) + (0 if y < h / 2 else 0.2)   # (top middle, by choice)
            if land < 0.08 and (best is None or score < best[0]):
                best = (score, x, y)
    return (round(best[1], 1), round(best[2], 1)) if best and best[0] < 3 else None


def arch(text: str, style: str, size: int, angle: float = 0.0) -> float:
    """How far a placed name bows (art.bend_path, degrees of arc): a realm's or a sea's gently, as an Inkarnate map
    curves them; the same name the same way every time. 0 for the rest."""
    if size < 2 or angle or style not in ("region", "sea"):
        return 0.0
    k = sum(ord(c) * (i + 1) for i, c in enumerate(text)) % 1000 / 1000.0
    return round((1 if k < 0.6 else -1) * (10 + k * 10 if style == "region" else 6 + k * 6), 1)


WOODS_NAMED = ["The {a} Wood", "{n} Forest", "The {n} Woods"]
WOODS_NAMED_TR = ["{n} Ormanı", "{a} Orman"]
RANGES_NAMED = ["The {a} Peaks", "The {n} Mountains", "The {n} Range"]
RANGES_NAMED_TR = ["{n} Dağları", "{a} Dağlar"]


def feature_names(marks: List[dict], labels: List[dict], seed: int, avoid=(), most: int = 2, sheet=(1024, 640)) -> List[tuple]:
    """Names for the biggest forests (across them) and mountain ranges (just under them), small, as an Inkarnate map
    labels them: from the wood and range stamps on the map, gathered where they stand together; all of each name on
    the `sheet` (w, h). [(text, x, y, 1, "land")]"""
    w, h = sheet
    rng = random.Random(seed + 71)
    near = [(lab["x"], lab["y"]) for lab in labels]
    boxes = name_boxes(labels)
    out = []
    for part, link, least, forms, below in (("_wood_", 50.0, 4, WOODS_NAMED_TR if LANG == "tr" else WOODS_NAMED, 0.0),
                                             ("_range_", 95.0, 2, RANGES_NAMED_TR if LANG == "tr" else RANGES_NAMED, 12.0)):
        pts = [(float(m["x"]), float(m["y"])) for m in marks if part in (m.get("art") or "")]
        group = list(range(len(pts)))

        def root(i):
            while group[i] != i:
                group[i] = group[group[i]]
                i = group[i]
            return i
        cells = {}                                              # (stamps standing together: one forest, one range;
        for i, (px, py) in enumerate(pts):                      # each compared with those in the cells round it only)
            cells.setdefault((int(px // link), int(py // link)), []).append(i)
        for (cx, cy), here in cells.items():
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    for i in here:
                        for j in cells.get((cx + dx, cy + dy), ()):
                            if i < j and math.dist(pts[i], pts[j]) < link:
                                group[root(i)] = root(j)
        clusters = {}
        for i in range(len(pts)):
            clusters.setdefault(root(i), []).append(pts[i])
        named = 0
        for c in sorted(clusters.values(), key=len, reverse=True):
            if named >= most or len(c) < least:
                break
            mx, my = sum(p[0] for p in c) / len(c), sum(p[1] for p in c) / len(c)
            x, y = min(c, key=lambda p: (p[0] - mx) ** 2 + (p[1] - my) ** 2)   # (on a stamp of it: a ring of woods' middle is open)
            if below:
                y = max(p[1] for p in c if abs(p[0] - x) < 70) + below
            a = fresh_adjective(rng, labels, out)
            text = rng.choice(forms).format(n=place_name(rng, in_use(labels, out)), a=a)
            hw = len(text) * 3.4
            if not (hw + 30 < x < w - hw - 30 and 30 < y < h - 20):
                continue                                        # (all of it on the sheet)
            if any(math.dist((x, y), q) < 70 for q in near + [(o[1], o[2]) for o in out]):
                continue                                        # (named already, or another name there)
            if any(abs(bx - x) < hw + bw and abs(by - y) < 22 + br + (12 if bs >= 3 else 8 if bs == 2 else 0) for bx, by, bw, bs, br in boxes):
                continue
            if any(px - 10 - hw < x < px + 90 + hw and abs(py - y) < 18 for px, py in avoid):
                continue                                        # (a town and its name)
            out.append((text, round(x, 1), round(y, 1), 1, "land"))
            boxes.append((x, y, hw, 1, 0.0))                    # (the next keeps off this one too)
            named += 1
    return out


BAYS = ["Bay of {n}", "{n} Bay", "The {a} Gulf", "{n} Sound"]
BAYS_TR = ["{n} Körfezi", "{a} Koy"]


def bay_names(mask: np.ndarray, labels: List[dict], seed: int, avoid=(), most: int = 2) -> List[tuple]:
    """Names for the sea's widest bays - water the land wraps round on most sides - as an Inkarnate map names its gulfs
    and sounds besides the open sea. [(text, x, y, 1, "sea")]"""
    h, w = mask.shape
    rng = random.Random(seed + 61)
    cover = (mask >= R.WATER).astype(np.float32)
    if cover.sum() < 400:
        return []
    around, coast = R.blur(cover, 28.0), R.blur(cover, 4.0)
    sea = open_sea(mask, 2)
    boxes = name_boxes(labels)
    spots = sorted(((float(around[y, x]), x, y) for y in range(40, h - 40, 6) for x in range(60, w - 60, 6)
                    if cover[y, x] == 0 and coast[y, x] < 0.05 and sea[y // 2, x // 2] and 0.38 < around[y, x] < 0.85), reverse=True)
    out = []
    for _sc, x, y in spots:
        if len(out) >= most:
            break
        if any(math.dist((x, y), (ox, oy)) < 220 for _t, ox, oy, *_r in out):
            continue
        a = fresh_adjective(rng, labels, out)
        text = rng.choice(BAYS_TR if LANG == "tr" else BAYS).format(n=place_name(rng, in_use(labels, out)), a=a)
        if any(text == o[0] for o in out) or any(text == lab.get("text") for lab in labels):
            continue                                            # (no two the same)
        hw = len(text) * 3.2
        if not (hw + 30 < x < w - hw - 30):
            continue
        if any(coast[y, int(x + t * hw)] > 0.05 for t in (-0.8, -0.4, 0.4, 0.8)):
            continue                                            # (all of it on the water)
        if any(abs(bx - x) < hw + bw + 20 and abs(by - y) < 30 + br for bx, by, bw, _s, br in boxes):
            continue                                            # (off the other names)
        if any(px - 10 - hw < x < px + 90 + hw and abs(py - y) < 20 for px, py in avoid):
            continue
        out.append((text, float(x), float(y), 1, "sea"))
    return out


LAKES = ["Lake {n}", "{n} Mere", "The {a} Lake", "{n} Water"]
LAKES_TR = ["{n} Gölü", "{a} Göl"]


def open_sea(mask: np.ndarray, step: int = 2) -> np.ndarray:
    """The water the sea reaches from the map's edges (every `step` map pixels): the rest of the water is lakes."""
    water = mask[::step, ::step] < R.WATER
    sea = np.zeros(water.shape, bool)
    sea[0, :], sea[-1, :], sea[:, 0], sea[:, -1] = water[0, :], water[-1, :], water[:, 0], water[:, -1]
    while True:                                                 # (the sea flooded in from the map's edges)
        grown = sea.copy()
        grown[1:] |= sea[:-1]
        grown[:-1] |= sea[1:]
        grown[:, 1:] |= sea[:, :-1]
        grown[:, :-1] |= sea[:, 1:]
        grown &= water
        if np.array_equal(grown, sea):
            return sea
        sea = grown


def lakes(mask: np.ndarray, step: int = 2) -> List[tuple]:
    """The lakes: water the open sea doesn't reach (fine enough a narrow strait still joins a bay to it), biggest first.
    [(area in map pixels, x, y)] - the point in each nearest its middle."""
    water = mask[::step, ::step] < R.WATER
    left, out = water & ~open_sea(mask, step), []
    for y0, x0 in zip(*np.nonzero(left)):
        if not left[y0, x0]:
            continue
        todo, cells = [(y0, x0)], []
        left[y0, x0] = False
        while todo:
            y, x = todo.pop()
            cells.append((y, x))
            for yy, xx in ((y + 1, x), (y - 1, x), (y, x + 1), (y, x - 1)):
                if 0 <= yy < left.shape[0] and 0 <= xx < left.shape[1] and left[yy, xx]:
                    left[yy, xx] = False
                    todo.append((yy, xx))
        cy, cx = np.mean(cells, axis=0)
        y, x = min(cells, key=lambda c: (c[0] - cy) ** 2 + (c[1] - cx) ** 2)
        out.append((len(cells) * step * step, float(x * step + step / 2), float(y * step + step / 2)))
    return sorted(out, reverse=True)


def lake_names(mask: np.ndarray, labels: List[dict], seed: int, avoid=(), most: int = 2) -> List[tuple]:
    """Names across the biggest lakes, small and italic as a sea's. [(text, x, y, 1, "sea")]"""
    rng = random.Random(seed + 53)
    near = [(lab["x"], lab["y"]) for lab in labels]
    boxes = name_boxes(labels)
    out = []
    for area, x, y in lakes(mask):
        if len(out) >= most or area < 640:                      # (a pond goes unnamed)
            break
        a = fresh_adjective(rng, labels, out)
        text = rng.choice(LAKES_TR if LANG == "tr" else LAKES).format(n=place_name(rng, in_use(labels, out)), a=a)
        hw = len(text) * 3.2
        if any(abs(bx - x) < hw + bw and abs(by - y) < 26 + br for bx, by, bw, _s, br in boxes) or any(math.dist((x, y), q) < 50 for q in near):
            continue                                            # (off the other names, all their width)
        if any(px - 10 - hw < x < px + 90 + hw and abs(py - y) < 20 for px, py in avoid):
            continue                                            # (a town and its name)
        out.append((text, round(x, 1), round(y, 1), 1, "sea"))
        boxes.append((x, y, hw, 1, 0.0))
    return out
