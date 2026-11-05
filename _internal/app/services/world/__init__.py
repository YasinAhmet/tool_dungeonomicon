"""The world map and the group's travel: a parchment the DM paints land onto, its towns and names, where the party
is and where it is heading, and the food it carries.

    world.paint([(x, y), ...], radius, strength, "raise")   # land up (lower: back into the sea, smooth) - map pixels
    world.paint(pts, radius, 0, "ground", ground=4)          # paint a ground on the land: desert sand (render.GROUNDS)
    world.paint(pts, radius, 0, "realm", ground=2)           # a realm over it: royal blue (render.REALMS; 0: none)
    world.begin_stroke() / world.end_stroke()                # one Ctrl+Z step around a stroke
    world.undo() / world.redo()
    world.add_mark("city", x, y, "Ravenhold")                # capital, city, town, village, fort, ruin, poi, mountain, hills, forest
    world.add_label("The Grey Sea", x, y, size=3, style="sea")
    world.publish()                                          # the players' copy: the picture, the marks and names, as now
    world.move_party(x, y)                                   # the party goes there along the roads: its trail grows, the days pass (meals eaten)
    world.undo_move()                                        # takes it back: the days turn back, the meals return
    world.set_route([(x, y), ...])                           # where it heads next (the players see it)
    world.ping(x, y, "Arin")                                 # a ripple on everyone's map; nothing is kept

    world.food() -> {"meals", "day", "average", "days_left", "mouths", "log", "stock"}   # the team inventory's food
    world.add_food(5) / world.spend_food(2, "Fed the horses") / world.end_day()
    world.member_food() -> [{"character", "owner", "meals", "items"}]
    world.give_meal("Arin")                                  # one of Arin's rations into the group's food

The DM paints in private: players see the version last sent (publish; or every change with `auto`). The party, its
route, the pings and the food are always live. There may be several maps (world.maps(), world.switch(id),
world.new_map(name)): the open one is the one the players see. Lines (world.add_line(points, "road")) are roads, paths,
rivers, borders and walls. Everything is in data/world/ (a folder a map); every change emits events.WORLD.
"""
import heapq
import io
import math
import os
import threading
import time
import zlib
from collections import deque
from typing import Callable, List, Optional

import numpy as np

from ...core import events
from ...core.storage import read_json, write_json
from ..common import Hooks, ServiceError, positive_int
from ..team import food_order, is_food
from . import dress as D
from . import render as R
from . import stamps

FOLDER = "data/world"
MAPS = FOLDER + "/maps"                      # one folder a map: map.json, mask.bin, ground.bin, shown_<version>.webp, view_<key>.png
STATE_FILE = FOLDER + "/state.json"          # which map is open (the one the players see), how sharp the pictures are
GROUP_FILE = FOLDER + "/group.json"
LINE_STYLES = ("road", "path", "river", "border", "wall", "guide")
LINE_LAYER = {"river": 0, "path": 1, "road": 2, "wall": 3, "border": 4, "guide": 5}     # a new line's layer: rivers under roads under walls
SCALE_MIN, SCALE_MAX = 0.3, 4.0             # a mark's or name's size (its picture and its words together)
LINES_MAX = 600
W, H = 1024, 640                             # map pixels
SCALE = 2                                    # output pixels per map pixel (the players' picture is 2048×1280)
SCALES = {1: "Low (quick)", 2: "Normal", 3: "High (slow)"}     # the sharpness setting: output pixels per map pixel
VIEW_VERSION = 5                             # up when render.py draws differently: the kept pictures are made again
UNDO = 30
TRAIL_MAX = 600
ROUTE_MAX = 60
MARKS_MAX = 4000
LABELS_MAX = 200
PACES = {"slow": 18, "normal": 24, "fast": 30}         # miles a day (PHB travel pace)
MARK_KINDS = ("capital", "city", "town", "village", "fort", "ruin", "poi", "mountain", "hills", "forest", "compass")
TERRAIN = ("mountain", "hills", "forest")      # drawn in ink like the land: sprayed on, no names
SIZED = TERRAIN + ("compass",)               # marks with a size (and a drawing of their own)
ART = "art"                                  # a stamp: a picture from a pack (stamps.py), m["art"] its key
LABEL_STYLES = ("land", "sea", "region", "banner", "plaque", "title")
GRIDS = ("none", "hex", "square")               # a grid over the map (hexes for a hexcrawl), grid_miles across
AVERAGE_DAYS = 7
PING_KEEP = 4.0                              # seconds a ping stays in recent()
FOLLOWED = ("road", "path")                  # the lines the party travels along
WAY_STEP = 10.0                              # map pixels between the points a road is walked by
WAY_JOIN = 8.0                               # roads closer than this meet (a crossroads; over half a step: crossings are caught)
OFFROAD = 1.35                               # a mile across the land weighs this many on a road (the way is picked so; the miles are real)
TRAVEL_DAYS_MAX = 365                        # days one move may end


_keeping = threading.Lock()                  # keep_view: one picture written at a time


def line_order(line: dict):
    """Bottom to top: the line's layer (old lines: by their kind), then the order they were drawn."""
    z = line.get("z")
    return (LINE_LAYER.get(line.get("style"), 2) if z is None else z, line.get("id") or 0)


def _clamp(v, lo, hi):
    return max(lo, min(hi, v))


def _walked(pts) -> List[tuple]:
    """A drawn line as the map draws it (curving round its corners: render.py, art.line_path), a point every few pixels."""
    pts = [(float(p[0]), float(p[1])) for p in pts]
    out = [pts[0]]

    def go(a, c, b):                                 # a quadratic from a round c to b (c None: straight)
        c = c or a
        n = max(1, int((math.hypot(c[0] - a[0], c[1] - a[1]) + math.hypot(b[0] - c[0], b[1] - c[1])) / WAY_STEP))
        for i in range(1, n + 1):
            t = i / n
            u = 1 - t
            out.append((u * u * a[0] + 2 * u * t * c[0] + t * t * b[0], u * u * a[1] + 2 * u * t * c[1] + t * t * b[1]))
    at = pts[0]
    for a, b in zip(pts[1:-1], pts[2:]):
        mid = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2)
        go(at, a, mid)
        at = mid
    go(at, None, pts[-1])
    return out


def _simplify(pts, eps: float = 0.75) -> List[tuple]:
    """Fewer points, the same way (Douglas-Peucker, `eps` map pixels)."""
    if len(pts) < 3:
        return list(pts)
    keep = [False] * len(pts)
    keep[0] = keep[-1] = True
    todo = [(0, len(pts) - 1)]
    while todo:
        i, j = todo.pop()
        (ax, ay), (bx, by) = pts[i], pts[j]
        L = math.hypot(bx - ax, by - ay) or 1e-9
        far, k = 0.0, None
        for m in range(i + 1, j):
            d = abs((bx - ax) * (ay - pts[m][1]) - (ax - pts[m][0]) * (by - ay)) / L
            if d > far:
                far, k = d, m
        if k is not None and far > eps:
            keep[k] = True
            todo += [(i, k), (k, j)]
    return [p for p, kept in zip(pts, keep) if kept]


def road_way(lines: List[dict], a, b) -> List[list]:
    """The way from a to b (map pixels): along the roads and paths where that is the easier going (a mile across the
    land weighs OFFROAD on a road), straight across otherwise. Roads meet where they come close."""
    a, b = (float(a[0]), float(a[1])), (float(b[0]), float(b[1]))
    direct = math.hypot(b[0] - a[0], b[1] - a[1]) * OFFROAD
    if direct < WAY_STEP:
        return [list(a), list(b)]
    # every way weighs at least its length, so one through a point further than `direct` (there and on) never wins
    reach = direct / 2 + WAY_STEP
    cx, cy = (a[0] + b[0]) / 2, (a[1] + b[1]) / 2
    nodes: List[tuple] = []
    links: dict = {}

    def near(p) -> bool:
        return math.hypot(p[0] - a[0], p[1] - a[1]) + math.hypot(p[0] - b[0], p[1] - b[1]) < direct

    def link(i, j):
        d = math.hypot(nodes[i][0] - nodes[j][0], nodes[i][1] - nodes[j][1])
        links.setdefault(i, []).append((j, d))
        links.setdefault(j, []).append((i, d))
    for ln in lines:
        pts = ln.get("pts") or []
        if ln.get("style") not in FOLLOWED or len(pts) < 2:
            continue
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        if min(xs) > cx + reach or max(xs) < cx - reach or min(ys) > cy + reach or max(ys) < cy - reach:
            continue                                         # (a curve stays inside its points' box)
        prev = None
        for p in _walked(pts):
            if not near(p):
                prev = None
                continue
            nodes.append(p)
            if prev is not None:
                link(prev, len(nodes) - 1)
            prev = len(nodes) - 1
    if not nodes:
        return [list(a), list(b)]
    grid: dict = {}
    for i, (x, y) in enumerate(nodes):
        grid.setdefault((int(x // WAY_JOIN), int(y // WAY_JOIN)), []).append(i)
    for i, (x, y) in enumerate(nodes):
        gx, gy = int(x // WAY_JOIN), int(y // WAY_JOIN)
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for j in grid.get((gx + dx, gy + dy), ()):
                    if j > i + 1 and math.hypot(nodes[j][0] - x, nodes[j][1] - y) < WAY_JOIN:
                        link(i, j)
    # A* from a (n) to b (n + 1): a reaches any road point across the land, any road point reaches b
    n = len(nodes)
    end = n + 1

    def left(p):                                             # never more than what is left to go
        return math.hypot(b[0] - p[0], b[1] - p[1])
    best = {n: 0.0}
    came: dict = {}
    heap = [(direct / OFFROAD, 0.0, n)]
    while heap:
        _f, cost, i = heapq.heappop(heap)
        if i == end:
            break
        if cost > best.get(i, math.inf):
            continue
        here = a if i == n else nodes[i]
        steps = [(end, left(here) * OFFROAD)]
        if i == n:
            steps += [(j, math.hypot(p[0] - a[0], p[1] - a[1]) * OFFROAD) for j, p in enumerate(nodes)]
        else:
            steps += links.get(i, [])
        for j, d in steps:
            c = cost + d
            f = c + (0.0 if j == end else left(nodes[j]))
            if c < best.get(j, math.inf) and f <= direct + 1e-6:
                best[j], came[j] = c, i
                heapq.heappush(heap, (f, c, j))
    way, i = [b], came.get(end, n)
    while i != n:
        way.append(nodes[i])
        i = came[i]
    way.append(a)
    return [list(p) for p in _simplify(way[::-1])]


class WorldService:
    def __init__(self, hooks: Hooks, characters, players, team):
        self.h, self.chars, self.players, self.team = hooks, characters, players, team
        self.lock = threading.RLock()
        self._renderer: Optional[R.Renderer] = None
        self._renderer_lock = threading.Lock()
        self.listeners: List[Callable[[dict], None]] = []       # each ping, from any thread (the portal's live stream)
        self._pings: "deque[dict]" = deque(maxlen=20)
        self._undo: List[tuple] = []
        self._redo: List[tuple] = []
        self._moves: List[dict] = []                            # the party's moves, to take back (undo_move)
        self._before: Optional[tuple] = None                   # (land, ground) as they were when the stroke began
        self._stroke_box = None
        self._publishing = False
        self._load()

    # ------------------------------------------------------------------ files
    def _dir(self, mid: Optional[str] = None) -> str:
        return f"{MAPS}/{mid or self.mid}"

    def _map_file(self, mid: Optional[str] = None) -> str:
        return self._dir(mid) + "/map.json"

    def _mask_file(self, mid: Optional[str] = None) -> str:
        return self._dir(mid) + "/mask.bin"

    def _ground_file(self, mid: Optional[str] = None) -> str:
        return self._dir(mid) + "/ground.bin"

    def _shown(self, v: int, mid: Optional[str] = None) -> str:
        return self._dir(mid) + f"/shown_{v}.webp"

    def _ids(self) -> List[str]:
        if not os.path.isdir(MAPS):
            return []
        return sorted((n for n in os.listdir(MAPS) if n.isdigit() and os.path.isfile(f"{MAPS}/{n}/map.json")), key=int)

    def _migrate(self):
        """The first maps lived in data/world itself: that one becomes a map of its own."""
        old = FOLDER + "/map.json"
        if not os.path.exists(old):
            return
        taken = set(self._ids())
        mid = next(str(i) for i in range(1, 10 ** 6) if str(i) not in taken)
        os.makedirs(f"{MAPS}/{mid}", exist_ok=True)
        for name in os.listdir(FOLDER):
            if name in ("map.json", "mask.bin") or (name.startswith("shown_") and name.endswith(".webp")):
                os.replace(f"{FOLDER}/{name}", f"{MAPS}/{mid}/{name}")

    def _load(self):
        self._migrate()
        ids = self._ids()
        state = read_json(STATE_FILE, {}) or {}
        want = str(state.get("active") or "")
        self.scale = int(state.get("scale") or SCALE) if int(state.get("scale") or SCALE) in SCALES else SCALE
        self._load_map(want if want in ids else (ids[0] if ids else "1"))
        g = read_json(GROUP_FILE, {}) or {}
        self.g = {"day": max(1, int(g.get("day") or 1)),
                  "eaten": {str(k): int(v) for k, v in (g.get("eaten") or {}).items()},
                  "log": [e for e in g.get("log") or [] if isinstance(e, dict)][-60:],
                  "mouths": g.get("mouths") if isinstance(g.get("mouths"), int) else None,
                  "walked": _clamp(float(g.get("walked") or 0.0), 0.0, 0.999)}    # how much of today the party has travelled
        if int(g.get("meals") or 0) > 0:            # the food used to be a number of its own: now rations in the team's pack
            self.team.stock(int(g["meals"]))
            write_json(GROUP_FILE, self.g)

    def _load_map(self, mid: str):
        self.mid = str(mid)
        d = read_json(self._map_file(), {}) or {}
        self.d = {"name": str(d.get("name") or "The Known World"), "w": int(d.get("w") or W), "h": int(d.get("h") or H),
                  "seed": int(d.get("seed") or 7), "rough": float(d.get("rough") or 1.0), "miles": float(d.get("miles") or 1200.0), "pace": d.get("pace") if d.get("pace") in PACES else "normal",
                  "look": d.get("look") if d.get("look") in R.LOOKS else ("parchment" if d else R.LOOKS[0]),   # (maps from before: as they were)
                  "grid": d.get("grid") if d.get("grid") in GRIDS else "none", "grid_miles": float(d.get("grid_miles") or 24.0),
                  "scale_bar": bool(d.get("scale_bar")), "plaques": bool(d.get("plaques")), "frame": d.get("frame") if d.get("frame") in R.FRAMES else ("none" if d.get("frame") is False else "border"),
                  "marks": [m for m in d.get("marks") or [] if isinstance(m, dict)],
                  "labels": [x for x in d.get("labels") or [] if isinstance(x, dict)],
                  "lines": [x for x in d.get("lines") or [] if isinstance(x, dict) and len(x.get("pts") or []) >= 2],
                  "party": d.get("party") if isinstance(d.get("party"), dict) else {"pos": None, "trail": [], "route": []},
                  "published": d.get("published") if isinstance(d.get("published"), dict) else None,
                  "auto": bool(d.get("auto")), "next_id": int(d.get("next_id") or 1), "changed": bool(d.get("changed"))}
        self.mask = np.zeros((self.d["h"], self.d["w"]), np.float32)
        if os.path.exists(self._mask_file()):
            try:
                with open(self._mask_file(), "rb") as f:
                    raw = np.frombuffer(zlib.decompress(f.read()), np.uint16)
                if raw.size == self.mask.size:
                    self.mask[:] = raw.reshape(self.mask.shape) / 65535.0
            except (OSError, zlib.error, ValueError):
                pass
        self.ground = np.zeros((self.d["h"], self.d["w"]), np.uint8)   # the grounds painted on the land (render.GROUNDS), the realms (>> 4)
        if os.path.exists(self._ground_file()):
            try:
                with open(self._ground_file(), "rb") as f:
                    raw = np.frombuffer(zlib.decompress(f.read()), np.uint8)
                if raw.size == self.ground.size:
                    self.ground[:] = raw.reshape(self.ground.shape)
            except (OSError, zlib.error, ValueError):
                pass
        self._undo, self._redo, self._moves = [], [], []

    def _save_map(self, changed: bool = True):
        if changed:
            self.d["changed"] = True
        write_json(self._map_file(), self.d)
        self.h.notify(events.WORLD)
        if changed and self.d["auto"]:
            self._auto_soon()

    def _save_state(self):
        write_json(STATE_FILE, {"active": self.mid, "scale": self.scale})

    def _save_mask(self):
        os.makedirs(self._dir(), exist_ok=True)
        data = zlib.compress((np.clip(self.mask, 0, 1) * 65535).astype(np.uint16).tobytes(), 6)
        tmp = self._mask_file() + ".tmp"
        with open(tmp, "wb") as f:
            f.write(data)
        os.replace(tmp, self._mask_file())
        if self.ground.any() or os.path.exists(self._ground_file()):
            tmp = self._ground_file() + ".tmp"
            with open(tmp, "wb") as f:
                f.write(zlib.compress(self.ground.tobytes(), 6))
            os.replace(tmp, self._ground_file())

    # ------------------------------------------------------------------ the maps
    def maps(self) -> List[dict]:
        """Every map: [{"id", "name", "active"}] (the open one is what the players see)."""
        with self.lock:
            out = []
            for mid in self._ids() or [self.mid]:
                name = self.d["name"] if mid == self.mid else str((read_json(self._map_file(mid), {}) or {}).get("name") or "?")
                out.append({"id": mid, "name": name, "active": mid == self.mid})
            if self.mid not in [m["id"] for m in out]:
                out.append({"id": self.mid, "name": self.d["name"], "active": True})
            return out

    def switch(self, mid: str):
        """Open another map: the DM paints on it and the players see it (as it was last sent)."""
        mid = str(mid)
        with self.lock:
            if mid == self.mid:
                return
            if mid not in self._ids():
                raise ServiceError("There is no such map.")
            self._load_map(mid)
            self._save_state()
            self.h.log(f"World map: {self.d['name']} is open.")
            self.h.notify(events.WORLD)

    def new_map(self, name: str, miles: float = 1200.0) -> str:
        """A new map, all sea, and open it."""
        with self.lock:
            ids = self._ids()
            mid = str(max([int(i) for i in ids] + [int(self.mid) if self.mid.isdigit() else 0]) + 1)
            if self.mid not in ids:                          # the open one was never saved: keep it
                self._save_mask()
                write_json(self._map_file(), self.d)
            self._load_map(mid)
            self.d["name"] = (str(name).strip() or "New map")[:60]
            self.d["miles"] = _clamp(float(miles), 1.0, 100000.0)
            self.d["seed"] = int(time.time()) % 100000 + 1
            self._save_mask()
            self._save_state()
            self._save_map()
            return mid

    def delete_map(self, mid: str):
        """Remove a map for good (not the last one); another opens if it was the open one."""
        import shutil
        mid = str(mid)
        with self.lock:
            ids = self._ids()
            if mid not in ids:
                raise ServiceError("There is no such map.")
            if len(ids) < 2:
                raise ServiceError("This is the only map.")
            if mid == self.mid:
                self._load_map(next(i for i in ids if i != mid))
                self._save_state()
            shutil.rmtree(self._dir(mid), ignore_errors=True)
            self.h.notify(events.WORLD)

    def _save_group(self, line: Optional[str] = None):
        write_json(GROUP_FILE, self.g)
        if line:
            self.h.log(line)
            self.h.discord_log("🍖 " + line, "xp")
        self.h.notify(events.WORLD)

    def _id(self) -> int:
        n = self.d["next_id"]
        self.d["next_id"] = n + 1
        return n

    # ------------------------------------------------------------------ the picture
    @property
    def size(self):
        return self.d["w"], self.d["h"]

    def renderer(self) -> R.Renderer:
        """The map's renderer (its paper takes a few seconds to make the first time; then it is kept)."""
        with self._renderer_lock:
            r = self._renderer
            warp = R.WARP * self.d["rough"]
            want = (self.d["w"], self.d["h"], self.d["seed"], warp, self.scale, self.d["look"], self.d["frame"])
            if not r or (r.w, r.h, r.seed, r.warp, r.s, r.look, r.frame) != want:
                self._renderer = r = R.Renderer(self.d["w"], self.d["h"], self.scale, self.d["seed"], warp, self.d["look"],
                                                self.d["frame"])
            return r

    def render(self, rect=None) -> np.ndarray:
        """The picture (RGBA, `scale` pixels a map pixel), or a part of it. The whole one is made from a copy of the
        land, without holding the map (seconds: the editor keeps working meanwhile)."""
        if rect is None:
            with self.lock:
                mask, ground = self.mask.copy(), self.ground.copy()
            return self.renderer().render(mask, None, ground)
        with self.lock:
            return self.renderer().render(self.mask, rect, self.ground)

    def view_path(self) -> str:
        """Where the editor keeps the whole picture of the map as it is now (view_<key>.png in its folder): the key
        changes with the land, the coast's roughness, the look, the sharpness and the map's size and seed."""
        with self.lock:
            key = zlib.crc32(self.ground.tobytes(), zlib.crc32(self.mask.tobytes()))
            key = zlib.crc32(repr((self.d["w"], self.d["h"], self.d["seed"], self.d["rough"], self.scale, self.d["look"], self.d["frame"], VIEW_VERSION)).encode(), key)
            return self._dir() + f"/view_{key:08x}.png"

    def cached_view(self) -> Optional[str]:
        """The kept picture of the map as it is now, None when there is none (it changed since)."""
        p = self.view_path()
        return p if os.path.isfile(p) else None

    @staticmethod
    def keep_view(path: str, write: Callable[[str], bool]):
        """Keep a whole picture (`write` saves it as PNG to the path it is given); the map's older ones go."""
        folder, name = os.path.split(path)
        with _keeping:                                          # (one at a time; and only a picture not kept yet)
            if os.path.isfile(path):
                return
            os.makedirs(folder, exist_ok=True)
            tmp = path + ".tmp"
            try:
                if not write(tmp):
                    return
                os.replace(tmp, path)
            except OSError:                                     # only a help for next time: never in the way
                return
        for old in os.listdir(folder):
            if old.startswith("view_") and old != name:
                try:
                    os.remove(os.path.join(folder, old))
                except OSError:
                    pass

    # ------------------------------------------------------------------ painting
    def begin_stroke(self):
        with self.lock:
            self._before = (self.mask.copy(), self.ground.copy())
            self._stroke_box = None

    def paint(self, points, radius: float, strength: float, mode: str = "raise", ground: int = 0) -> tuple:
        """Brush dabs along the points (map pixels); returns the rect changed (x0, y0, x1, y1). mode "ground" paints
        that ground (render.GROUNDS' id; 0: the land's own) instead of raising, lowering or smoothing the land."""
        if mode not in ("raise", "lower", "smooth", "ground", "realm"):
            raise ServiceError(f"Unknown brush '{mode}'.")
        if mode == "ground" and ground not in R.GROUNDS and ground != 0:
            raise ServiceError(f"Unknown ground '{ground}'.")
        if mode == "realm" and ground not in R.REALMS and ground != 0:
            raise ServiceError(f"Unknown realm '{ground}'.")
        with self.lock:
            if mode in ("ground", "realm"):
                box = R.ground_stroke(self.ground, points, _clamp(float(radius), 1.0, 400.0), int(ground), mode == "realm")
            else:
                box = R.stroke(self.mask, points, _clamp(float(radius), 1.0, 400.0), _clamp(float(strength), 0.01, 1.0), mode)
            if box[2] > box[0]:
                b = self._stroke_box
                self._stroke_box = box if b is None else (min(b[0], box[0]), min(b[1], box[1]), max(b[2], box[2]), max(b[3], box[3]))
            return box

    def end_stroke(self):
        with self.lock:
            b, before = self._stroke_box, self._before
            self._before = self._stroke_box = None
            if b is None or before is None:
                return
            x0, y0, x1, y1 = b
            self._undo.append(("mask", b, (before[0][y0:y1, x0:x1].copy(), before[1][y0:y1, x0:x1].copy())))
            del self._undo[:-UNDO]
            self._redo.clear()
            self._save_mask()
            self._save_map()

    def _swap(self, step) -> Optional[tuple]:
        kind, b, data = step
        if kind == "mask":
            x0, y0, x1, y1 = b
            now = (self.mask[y0:y1, x0:x1].copy(), self.ground[y0:y1, x0:x1].copy())
            self.mask[y0:y1, x0:x1], self.ground[y0:y1, x0:x1] = data
            self._save_mask()
            self._save_map()
            return ("mask", b, now), b
        if kind == "dress":                                     # the marks and the ground together
            now = (self.ground.copy(), {k: self.d[k] for k in ("marks", "labels", "lines")})
            self.ground[:] = data[0]
            self.d.update(data[1])
            self._save_mask()
            self._save_map()
            return ("dress", None, now), (0, 0, self.d["w"], self.d["h"])
        now = {k: self.d[k] for k in ("marks", "labels", "lines")}
        self.d.update(data)
        self._save_map()
        return ("items", None, now), None

    def undo(self) -> Optional[tuple]:
        """Undo the last stroke or mark change; returns the rect of the land that changed (None: only marks)."""
        with self.lock:
            if not self._undo:
                raise ServiceError("Nothing to undo.")
            back, rect = self._swap(self._undo.pop())
            self._redo.append(back)
            return rect or (0, 0, 0, 0)

    def redo(self) -> Optional[tuple]:
        with self.lock:
            if not self._redo:
                raise ServiceError("Nothing to redo.")
            back, rect = self._swap(self._redo.pop())
            self._undo.append(back)
            return rect or (0, 0, 0, 0)

    def _keep_items(self):
        """Before a change to the marks or names: an undo step."""
        self._undo.append(("items", None, {"marks": [dict(m) for m in self.d["marks"]], "labels": [dict(x) for x in self.d["labels"]],
                                           "lines": [dict(x) for x in self.d["lines"]]}))
        del self._undo[:-UNDO]
        self._redo.clear()

    def clear_land(self):
        with self.lock:
            self.begin_stroke()
            self.mask[:] = 0.0
            self._stroke_box = (0, 0, self.d["w"], self.d["h"])
            self.end_stroke()

    def generate(self, seed: Optional[int] = None, land: float = 0.4, parts: int = 1):
        """A random coast to start from (one undo step): `parts` continents."""
        with self.lock:
            self.begin_stroke()
            R.island(self.mask, int(seed if seed is not None else time.time() * 1000) % 2 ** 31, _clamp(float(land), 0.1, 0.8),
                     int(_clamp(int(parts), 1, 5)))
            self._stroke_box = (0, 0, self.d["w"], self.d["h"])
            self.end_stroke()

    def dress(self, seed: Optional[int] = None) -> int:
        """Dress the land with mountains, hills, woods and trees (painted, or ink for the parchment looks), rivers from
        the ranges to the sea, and snow, dry ground and forest floor under them where the ground is still the land's
        own; what is on the map stays. One undo step. How many stamps were set."""
        with self.lock:
            spots, ground = D.plan(self.mask, self.ground, self.d["marks"],
                                   int(seed if seed is not None else time.time() * 1000) % 2 ** 31,
                                   ink=self.d["look"] not in R.COLOUR_LOOKS)
            spots = spots[:max(0, MARKS_MAX - len(self.d["marks"]))]
            if not spots and np.array_equal(ground, self.ground):
                raise ServiceError("There is no land to dress (or no room left on it).")
            self._undo.append(("dress", None, (self.ground.copy(), {"marks": [dict(m) for m in self.d["marks"]],
                                                                     "labels": [dict(x) for x in self.d["labels"]],
                                                                     "lines": [dict(x) for x in self.d["lines"]]})))
            del self._undo[:-UNDO]
            self._redo.clear()
            for x, y, s, key in spots:
                self.d["marks"].append(self._mark(ART, x, y, "", s, art=key))
            ranges = [(x, y) for x, y, _s, key in spots if "_range_" in key or "_peaks_" in key or "_mountain_" in key]
            for pts in D.rivers(self.mask, ranges, len(spots))[:max(0, LINES_MAX - len(self.d["lines"]))]:
                self.d["lines"].append({"id": self._id(), "pts": pts, "style": "river", "z": LINE_LAYER["river"]})
            self.ground[:] = ground
            self._save_mask()
            self._save_map()
            return len(spots)

    @staticmethod
    def _name_language():
        """Made-up names in the editor's language (Turkish ones when it is Turkish)."""
        from ...core.i18n import i18n
        D.LANG = "tr" if i18n.language == "tr" else "en"

    def settle(self, seed: Optional[int] = None) -> int:
        """Set named cities, towns, villages, harbours and castles over the land (painted, or ink for the parchment
        looks), on the rivers and coasts, joined by roads, and name the land and the sea; what is on the map stays. One
        undo step. How many towns were set."""
        self._name_language()
        with self.lock:
            towns, roads, n_towns = D.settle(self.mask, self.ground, self.d["marks"], self.d["lines"],
                                    int(seed if seed is not None else time.time() * 1000) % 2 ** 31,
                                    ink=self.d["look"] not in R.COLOUR_LOOKS)
            towns = towns[:max(0, MARKS_MAX - len(self.d["marks"]))]
            if not towns:
                raise ServiceError("There is no room on the land for towns.")
            self._keep_items()
            for x, y, s, key, name in towns:
                self.d["marks"].append(self._mark(ART, x, y, name, s, art=key))
            for pts in roads[:max(0, LINES_MAX - len(self.d["lines"]))]:
                self.d["lines"].append({"id": self._id(), "pts": pts, "style": "road", "z": LINE_LAYER["road"]})
            named = [(m["x"], m["y"] - 6) for m in self.d["marks"] if m.get("name")]
            got = (D.realm_names(self.ground, self.d["labels"], len(towns), named, self.mask)      # the realms painted on it, or the
                   or D.names(self.mask, self.d["labels"], len(towns), named))      # land's own name (and the sea's)
            if not any(st == "sea" for *_r, st in got):
                got += [n for n in D.names(self.mask, self.d["labels"] + [{"text": t_, "x": x, "y": y} for t_, x, y, *_r in got], len(towns), named)
                        if n[4] == "sea"]
            got += D.lake_names(self.mask, self.d["labels"] + [{"text": g_[0], "x": g_[1], "y": g_[2], "size": g_[3], "style": g_[4]} for g_ in got],
                                len(towns), named)
            if not any(lab.get("style") == "sea" and int(lab.get("size") or 2) == 1 and not lab.get("angle")
                       and self.mask[min(int(lab["y"]), self.d["h"] - 1), min(int(lab["x"]), self.d["w"] - 1)] < R.WATER
                       for lab in self.d["labels"]):                # (bays named once; a label may sit right on the edge)
                got += D.bay_names(self.mask, self.d["labels"] + [{"text": g_[0], "x": g_[1], "y": g_[2], "size": g_[3], "style": g_[4]} for g_ in got],
                                   len(towns), named)
            got += D.feature_names(self.d["marks"], self.d["labels"] + [{"text": g_[0], "x": g_[1], "y": g_[2], "size": g_[3], "style": g_[4]} for g_ in got],
                                   len(towns), named, sheet=(self.d["w"], self.d["h"]))   # the biggest forests and ranges
            got = [g_ + (0.0,) for g_ in got] + D.river_names(self.d["lines"], self.d["labels"] + [{"text": g_[0], "x": g_[1], "y": g_[2], "size": g_[3], "style": g_[4]}
                                                                                for g_ in got],
                                                             len(towns), named)
            if not any(lab.get("style") == "title" for lab in self.d["labels"]):    # the map's own name, its title, out at sea
                at = D.title_spot(self.mask, self.d["name"], self.d["labels"] + [{"text": g_[0], "x": g_[1], "y": g_[2]} for g_ in got],
                                  self.d["marks"], 26.0 if self.d["frame"] == "clouds" else 0.0)
                if at:
                    got.append((self.d["name"], at[0], at[1], 3, "title", 0.0))
            for text, x, y, size, style, angle in got[:max(0, LABELS_MAX - len(self.d["labels"]))]:
                self.d["labels"].append(self._auto_label(text, x, y, size, style, angle))
            self._save_map()
            return min(n_towns, len(towns))                     # (the towns, not the landmarks, farms, boats or bridges)

    def _auto_label(self, text: str, x: float, y: float, size: int, style: str, angle: float = 0.0) -> dict:
        """A name settle() or divide() placed: a realm's or a sea's bowed a little (dress.arch)."""
        lab = {"id": self._id(), "text": text, "x": x, "y": y, "size": size, "style": style, "angle": angle}
        bend = D.arch(text, style, size, angle)
        if bend:
            lab["bend"] = bend
        return lab

    def divide(self, n: int = 0, seed: Optional[int] = None) -> int:
        """Split the land into realms round its biggest towns (only land no realm was painted on), and name them; one
        undo step. How many realms."""
        self._name_language()
        with self.lock:
            ground = D.divide(self.mask, self.ground, self.d["marks"], int(seed if seed is not None else time.time() * 1000) % 2 ** 31, n)
            land = self.mask >= R.WATER
            if np.array_equal(ground[land], self.ground[land]):     # (on the land: the sea round it doesn't count)
                raise ServiceError("There is no land left without a realm.")
            self._undo.append(("dress", None, (self.ground.copy(), {"marks": [dict(m) for m in self.d["marks"]],
                                                                     "labels": [dict(x) for x in self.d["labels"]],
                                                                     "lines": [dict(x) for x in self.d["lines"]]})))
            del self._undo[:-UNDO]
            self._redo.clear()
            self.ground[:] = ground
            named = [(m["x"], m["y"] - 6) for m in self.d["marks"] if m.get("name")]
            for text, x, y, size, style in D.realm_names(self.ground, self.d["labels"], len(self.d["marks"]), named, self.mask):
                if len(self.d["labels"]) < LABELS_MAX:
                    self.d["labels"].append(self._auto_label(text, x, y, size, style))
            self._save_mask()
            self._save_map()
            return len([v for v in np.unique(self.ground[land] >> 4) if v])

    def restyle(self) -> int:
        """Every stamp with a twin in the look's set swapped for it - ink and top-down stamps for painted ones on a painted
        map, painted ones for ink on a parchment or sepia one - covering the same ground. One undo step. How many changed."""
        ink = self.d["look"] not in R.COLOUR_LOOKS
        with self.lock:
            swaps = []
            for m in self.d["marks"]:
                if m.get("kind") == ART and m.get("art"):
                    got = D.twin(m["art"], float(m.get("s") or 1), float(m["y"]), ink, int(m.get("id") or 0) * 7919)
                    if got:
                        swaps.append((m, got))
            if not swaps:
                raise ServiceError("No stamps here have a twin in this look's set.")
            self._keep_items()
            for m, (key, s, y) in swaps:
                m.update(art=key, s=s, y=y)
                if key.startswith("pt_") and not key.startswith(D.FLAT):     # (a painted mountain or town stands upright)
                    m.pop("r", None)
            self._save_map()
            return len(swaps)

    def land_at(self, x: float, y: float) -> bool:
        xi, yi = int(_clamp(x, 0, self.d["w"] - 1)), int(_clamp(y, 0, self.d["h"] - 1))
        return bool(self.mask[yi, xi] >= R.WATER)

    # ------------------------------------------------------------------ marks and names
    def _in_map(self, x, y):
        return round(_clamp(float(x), 0, self.d["w"]), 1), round(_clamp(float(y), 0, self.d["h"]), 1)

    def marks(self) -> List[dict]:
        with self.lock:
            return [dict(m) for m in self.d["marks"]]

    def labels(self) -> List[dict]:
        with self.lock:
            return [dict(x) for x in self.d["labels"]]

    def lines(self) -> List[dict]:
        with self.lock:
            return [dict(x, pts=[list(p) for p in x["pts"]]) for x in self.d["lines"]]

    def add_line(self, pts, style: str = "road") -> dict:
        """A drawn line (map points): a road, a path, a river, a border or a wall."""
        pts = [list(self._in_map(x, y)) for x, y in list(pts)[:2000]]
        if len(pts) < 2:
            raise ServiceError("Draw a longer line.")
        with self.lock:
            if len(self.d["lines"]) >= LINES_MAX:
                raise ServiceError("The map has too many lines; remove some first.")
            self._keep_items()
            style = style if style in LINE_STYLES else "road"
            if style == "river" and not self.land_at(*pts[0]) and self.land_at(*pts[-1]):
                pts.reverse()                                   # a river runs to the sea (it widens on its way)
            line = {"id": self._id(), "pts": pts, "style": style, "z": LINE_LAYER[style]}
            self.d["lines"].append(line)
            self._save_map()
            return dict(line)

    def lines_in_order(self) -> List[dict]:
        """The lines bottom to top (their layer, then the order they were drawn)."""
        return sorted(self.lines(), key=line_order)

    def restack_line(self, ident: int, how: str):
        """A line to another layer: "front" / "back" (over or under every other line), "up" / "down" (past the next one)."""
        with self.lock:
            line = self._find("lines", ident)
            order = sorted(self.d["lines"], key=line_order)
            self._keep_items()
            for i, x in enumerate(order):                       # layers as they are drawn: 0, 1, 2...
                x["z"] = i
            i = order.index(line)
            if how == "front":
                line["z"] = len(order)
            elif how == "back":
                line["z"] = -1
            elif how in ("up", "down"):
                j = i + (1 if how == "up" else -1)
                if 0 <= j < len(order):
                    line["z"], order[j]["z"] = order[j]["z"], line["z"]
            else:
                raise ServiceError(f"Unknown layer move '{how}'.")
            self._save_map()

    def edit_line(self, ident: int, style: Optional[str] = None, dx: float = 0.0, dy: float = 0.0) -> dict:
        with self.lock:
            line = self._find("lines", ident)
            self._keep_items()
            if style in LINE_STYLES:
                line["style"] = style
            if dx or dy:
                line["pts"] = [list(self._in_map(x + dx, y + dy)) for x, y in line["pts"]]
            self._save_map()
            return dict(line)

    def remove_line(self, ident: int):
        with self.lock:
            line = self._find("lines", ident)
            self._keep_items()
            self.d["lines"].remove(line)
            self._save_map()

    def remove_items(self, marks=(), lines=()) -> int:
        """Marks and lines at once, one undo step (the eraser)."""
        marks, lines = set(marks), set(lines)
        with self.lock:
            n = sum(1 for m in self.d["marks"] if m.get("id") in marks) + sum(1 for x in self.d["lines"] if x.get("id") in lines)
            if not n:
                return 0
            self._keep_items()
            self.d["marks"] = [m for m in self.d["marks"] if m.get("id") not in marks]
            self.d["lines"] = [x for x in self.d["lines"] if x.get("id") not in lines]
            self._save_map()
            return n

    @staticmethod
    def _check_kind(kind: str, art: Optional[str]):
        if kind == ART:
            if not stamps.get(art):
                raise ServiceError("There is no such stamp.")
        elif kind not in MARK_KINDS:
            raise ServiceError(f"Unknown map mark '{kind}'.")

    def _mark(self, kind, x, y, name="", s=1.0, v=None, art=None, r=0.0) -> dict:
        x, y = self._in_map(x, y)
        m = {"id": self._id(), "kind": kind, "x": x, "y": y, "name": (name or "").strip()[:60]}
        if kind == ART:
            m["art"] = art
            if r:                                                # how far it is turned (degrees, clockwise)
                m["r"] = round(float(r) % 360.0, 1)
        if kind in SIZED or kind == ART or float(s) != 1.0:      # its size (the picture and the name together)
            m["s"] = round(_clamp(float(s), SCALE_MIN, SCALE_MAX), 2)
        if kind in SIZED:                                        # which of its drawings
            m["v"] = int(v if v is not None else (m["id"] * 7919) % 97)
        return m

    def add_mark(self, kind: str, x, y, name: str = "", s: float = 1.0, v: Optional[int] = None, art: Optional[str] = None,
                 r: float = 0.0) -> dict:
        """A mark (MARK_KINDS), or a stamp: kind ART, `art` the stamp's key (stamps.catalog()), turned `r` degrees."""
        self._check_kind(kind, art)
        with self.lock:
            if len(self.d["marks"]) >= MARKS_MAX:
                raise ServiceError("The map has too many marks; remove some first.")
            self._keep_items()
            m = self._mark(kind, x, y, name, s, v, art, r)
            self.d["marks"].append(m)
            self._save_map()
            return dict(m)

    def add_marks(self, kind: str, spots) -> int:
        """Many at once, one undo step (a sprayed range of mountains): spots [(x, y, size), ...]; stamps (kind ART):
        [(x, y, size, key[, degrees turned]), ...]."""
        spots = list(spots)
        for sp in spots:
            self._check_kind(kind, sp[3] if len(sp) > 3 else None)
        with self.lock:
            spots = list(spots)[:max(0, MARKS_MAX - len(self.d["marks"]))]
            if not spots:
                raise ServiceError("The map has too many marks; remove some first.")
            self._keep_items()
            for sp in spots:
                self.d["marks"].append(self._mark(kind, sp[0], sp[1], "", sp[2] if len(sp) > 2 else 1.0, art=sp[3] if len(sp) > 3 else None,
                                                  r=sp[4] if len(sp) > 4 else 0.0))
            self._save_map()
            return len(spots)

    def remove_marks(self, ids) -> int:
        """Several at once, one undo step (the eraser)."""
        ids = set(ids)
        with self.lock:
            gone = [m for m in self.d["marks"] if m.get("id") in ids]
            if not gone:
                return 0
            self._keep_items()
            self.d["marks"] = [m for m in self.d["marks"] if m.get("id") not in ids]
            self._save_map()
            return len(gone)

    def _find(self, key: str, ident: int) -> dict:
        found = next((e for e in self.d[key] if e.get("id") == ident), None)
        if not found:
            raise ServiceError("That isn't on the map any more.")
        return found

    def edit_mark(self, ident: int, **changes) -> dict:
        with self.lock:
            m = self._find("marks", ident)
            self._keep_items()
            if "x" in changes or "y" in changes:
                m["x"], m["y"] = self._in_map(changes.get("x", m["x"]), changes.get("y", m["y"]))
            if "name" in changes:
                m["name"] = (changes["name"] or "").strip()[:60]
            if changes.get("kind") in MARK_KINDS:
                m["kind"] = changes["kind"]
                if m["kind"] in SIZED and "v" not in m:
                    m["v"] = (m["id"] * 7919) % 97
            if changes.get("s") is not None:
                m["s"] = round(_clamp(float(changes["s"]), SCALE_MIN, SCALE_MAX), 2)
            if changes.get("r") is not None and m["kind"] == ART:
                m["r"] = round(float(changes["r"]) % 360.0, 1)
            self._save_map()
            return dict(m)

    def remove_mark(self, ident: int):
        with self.lock:
            m = self._find("marks", ident)
            self._keep_items()
            self.d["marks"].remove(m)
            self._save_map()

    def add_label(self, text: str, x, y, size: int = 2, style: str = "land", angle: float = 0.0) -> dict:
        text = (text or "").strip()[:80]
        if not text:
            raise ServiceError("Write the name first.")
        with self.lock:
            if len(self.d["labels"]) >= LABELS_MAX:
                raise ServiceError("The map has too many names; remove some first.")
            self._keep_items()
            x, y = self._in_map(x, y)
            lab = {"id": self._id(), "text": text, "x": x, "y": y, "size": int(_clamp(int(size), 1, 4)),
                   "style": style if style in LABEL_STYLES else "land", "angle": round(_clamp(float(angle), -90, 90), 1)}
            self.d["labels"].append(lab)
            self._save_map()
            return dict(lab)

    def edit_label(self, ident: int, **changes) -> dict:
        with self.lock:
            lab = self._find("labels", ident)
            self._keep_items()
            if "x" in changes or "y" in changes:
                lab["x"], lab["y"] = self._in_map(changes.get("x", lab["x"]), changes.get("y", lab["y"]))
            if changes.get("text"):
                lab["text"] = str(changes["text"]).strip()[:80]
            if "size" in changes:
                lab["size"] = int(_clamp(int(changes["size"]), 1, 4))
            if changes.get("style") in LABEL_STYLES:
                lab["style"] = changes["style"]
            if "angle" in changes:
                lab["angle"] = round(_clamp(float(changes["angle"]), -90, 90), 1)
            if "bend" in changes:                                 # bowed along an arc: + arches up, - sags (degrees of arc)
                bend = round(_clamp(float(changes["bend"]), -120, 120), 1)
                if bend:
                    lab["bend"] = bend
                else:
                    lab.pop("bend", None)
            if changes.get("s") is not None:
                lab["s"] = round(_clamp(float(changes["s"]), SCALE_MIN, SCALE_MAX), 2)
            self._save_map()
            return dict(lab)

    def remove_label(self, ident: int):
        with self.lock:
            lab = self._find("labels", ident)
            self._keep_items()
            self.d["labels"].remove(lab)
            self._save_map()

    # ------------------------------------------------------------------ settings
    def settings(self) -> dict:
        with self.lock:
            return dict({k: self.d[k] for k in ("name", "miles", "pace", "auto", "rough", "look", "grid", "grid_miles", "scale_bar", "frame", "plaques")}, scale=self.scale)

    def set_settings(self, **s):
        with self.lock:
            if "name" in s:
                self.d["name"] = (str(s["name"]).strip() or "The Known World")[:60]
            if "miles" in s:
                self.d["miles"] = _clamp(float(s["miles"]), 1.0, 100000.0)
            if s.get("pace") in PACES:
                self.d["pace"] = s["pace"]
            if "auto" in s:
                self.d["auto"] = bool(s["auto"])
            if "rough" in s:                                     # how far the coast wanders off the painted line
                self.d["rough"] = round(_clamp(float(s["rough"]), 0.1, 1.5), 2)
            if s.get("look") in R.LOOKS:                         # painted colour, or ink on parchment
                self.d["look"] = s["look"]
            if s.get("grid") in GRIDS:
                self.d["grid"] = s["grid"]
            if "grid_miles" in s:
                self.d["grid_miles"] = _clamp(float(s["grid_miles"]), 0.1, 10000.0)
            if s.get("frame") in R.FRAMES:                       # the painted looks' edge: a border, clouds, none
                self.d["frame"] = s["frame"]
            if "plaques" in s:                                   # the towns' names on parchment plaques
                self.d["plaques"] = bool(s["plaques"])
            if "scale_bar" in s:                                 # a bar of miles in a corner of the map
                self.d["scale_bar"] = bool(s["scale_bar"])
            if int(s.get("scale") or 0) in SCALES:              # how sharp the pictures are (every map's; the editor's too)
                self.scale = int(s["scale"])
                self._save_state()
            drawn = {"name", "rough", "look", "grid", "grid_miles", "scale_bar", "frame", "plaques"}
            if self.d["grid"] != "none" or self.d["scale_bar"]:     # (the miles change what the grid and the bar show)
                drawn.add("miles")
            self._save_map(changed=bool(drawn & set(s)))

    def grid(self, d: Optional[dict] = None) -> Optional[dict]:
        """The grid over the map (or over `d`, a map's data): {"kind": "hex" | "square", "px": its cells' size in map
        pixels}; None: no grid."""
        d = d or self.d
        if d["grid"] == "none":
            return None
        return {"kind": d["grid"], "px": round(max(6.0, d["grid_miles"] / (d["miles"] / d["w"])), 2)}

    def miles_per_px(self) -> float:
        return self.d["miles"] / self.d["w"]

    def miles(self, pts) -> float:
        """The length of a line of map points, in miles."""
        return sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(pts, pts[1:])) * self.miles_per_px()

    def days(self, miles: float) -> float:
        return miles / PACES[self.d["pace"]]

    # ------------------------------------------------------------------ publishing
    def published(self) -> Optional[dict]:
        with self.lock:
            return dict(self.d["published"]) if self.d["published"] else None

    @property
    def changed(self) -> bool:
        """Changes the players don't see yet."""
        return bool(self.d.get("changed")) or not self.d["published"]

    def publish(self, wait: bool = False):
        """Send the map as it is now to the players: the picture is made on a thread of its own (wait: here)."""
        if wait:
            return self._publish()
        if self._publishing:
            return None
        self._publishing = True
        threading.Thread(target=self._publish, daemon=True, name="world-publish").start()
        return None

    def _publish(self) -> dict:
        from PIL import Image
        try:
            self._publishing = True
            with self.lock:                                     # (the map may be switched meanwhile: keep its own)
                mid, d = self.mid, self.d
                mask, ground = self.mask.copy(), self.ground.copy()
                marks, labels, lines, name = self.marks(), self.labels(), self.lines_in_order(), d["name"]
                old = d["published"]
                v = (old or {}).get("v", 0) + 1
                cached = self.cached_view()                     # the editor's picture of the land as it is: no new one
                renderer = None if cached else self.renderer()
            rgba = np.asarray(Image.open(cached).convert("RGBA")) if cached else renderer.render(mask, None, ground)
            buf = io.BytesIO()
            Image.fromarray(rgba, "RGBA").save(buf, "WEBP", quality=88, method=4)
            os.makedirs(self._dir(mid), exist_ok=True)
            with open(self._shown(v, mid), "wb") as f:
                f.write(buf.getvalue())
            with self.lock:
                d["published"] = {"v": v, "at": time.time(), "marks": marks, "labels": labels, "lines": lines, "name": name,
                                  "w": d["w"], "h": d["h"], "look": d["look"], "grid": self.grid(d),
                                  "scale_bar": d["miles"] / d["w"] if d["scale_bar"] else None, "plaques": d["plaques"]}       # (the map sent: maybe not the open one now)
                d["changed"] = False
                write_json(self._map_file(mid), d)
            if old and old.get("v") != v:
                try:
                    os.remove(self._shown(old["v"], mid))
                except OSError:
                    pass
            self.h.log(f"World map sent to the players: {name} (version {v}).")
            self.h.notify(events.WORLD)
            return d["published"]
        finally:
            self._publishing = False

    @property
    def publishing(self) -> bool:
        return self._publishing

    def shown_key(self) -> Optional[str]:
        """The name of the players' picture of the open map ("<map>_<version>"), None before it was sent."""
        p = self.d["published"]
        return f"{self.mid}_{p['v']}" if p else None

    def shown_file(self, key) -> Optional[str]:
        """The players' picture by its name (only the open map's latest)."""
        if str(key) != self.shown_key():
            return None
        f = self._shown(self.d["published"]["v"])
        return f if os.path.exists(f) else None

    _auto_timer: Optional[threading.Timer] = None

    def _auto_soon(self):
        """With auto on: send a few seconds after the last change."""
        if self._auto_timer:
            self._auto_timer.cancel()
        self._auto_timer = threading.Timer(2.5, lambda: self.publish())
        self._auto_timer.daemon = True
        self._auto_timer.start()

    # ------------------------------------------------------------------ the party
    def party(self) -> dict:
        with self.lock:
            p = self.d["party"]
            leg = p.get("leg") if isinstance(p.get("leg"), dict) else None
            return {"pos": list(p["pos"]) if p.get("pos") else None, "trail": [list(t) for t in p.get("trail") or []],
                    "route": [list(t) for t in p.get("route") or []],
                    "leg": {"pts": [list(t) for t in leg["pts"]], "back": bool(leg.get("back")), "n": int(leg.get("n") or 0)}
                    if leg else None}

    def _leg(self, pts, back: bool):
        """The way the party's banner last went (`back`: a move taken back), for the maps to glide it along."""
        p = self.d["party"]
        n = int((p.get("leg") or {}).get("n") or 0) + 1
        p["leg"] = {"pts": [list(t) for t in pts], "back": back, "n": n} if len(pts) > 1 else None

    def place_party(self, x, y):
        """Put the party somewhere (no trail: a new start)."""
        with self.lock:
            p = self.d["party"]
            p["pos"] = list(self._in_map(x, y))
            p["trail"] = [list(p["pos"])]
            p["leg"] = None
            self._moves.clear()
            self._save_map(changed=False)

    def way(self, x, y) -> List[list]:
        """The way the party would go to (x, y): along the roads and paths where they help."""
        with self.lock:
            p = self.d["party"]
            to = list(self._in_map(x, y))
            return road_way(self.d["lines"], p["pos"], to) if p.get("pos") else [to]

    def move_party(self, x, y, eat: bool = True) -> dict:
        """The party travels to (x, y), along the roads and paths where they help: its trail grows, and the days the
        trip takes pass (each one a meal each from the group's food; `eat` False: the days don't count). Returns the
        miles, the days, `path` (the way it went), `ended` (days that passed), `ate` and `hungry`. undo_move takes it back."""
        with self.lock:
            p = self.d["party"]
            to = list(self._in_map(x, y))
            if not p.get("pos"):
                self.place_party(*to)
                return {"miles": 0.0, "days": 0.0, "path": [], "ended": 0, "ate": 0, "hungry": 0}
            way = road_way(self.d["lines"], p["pos"], to)
            miles = self.miles(way)
            days = self.days(miles)
            back = {"pos": list(p["pos"]), "trail": [list(t) for t in p.get("trail") or []], "way": way,
                    "walked": self.g["walked"], "reached": None, "ends": []}
            p["pos"] = to
            trail = p.setdefault("trail", [])
            trail.extend(way[1:])
            del trail[:-TRAIL_MAX]
            route = p.get("route") or []
            if route and math.hypot(route[0][0] - to[0], route[0][1] - to[1]) < 6:   # reached the next waypoint
                back["reached"] = route.pop(0)
            self._leg(way, False)
            if eat:
                whole = self.g["walked"] + days
                n = min(int(whole), TRAVEL_DAYS_MAX)
                back["ends"] = [self._day_ends() for _ in range(n)]
                self.g["walked"] = round(whole - int(whole), 4)
            self._moves.append(back)
            del self._moves[:-UNDO]
            self._save_map(changed=False)
            ate = sum(e["ate"] for e in back["ends"])
            hungry = sum(e["hungry"] for e in back["ends"])
            line = None
            if back["ends"]:
                line = (f"The party travels {round(miles)} mi: {len(back['ends'])} day(s) pass, the group eats {ate} "
                        f"meal(s) - {self.team.meals()} left" + (f"; {hungry} meal(s) short" if hungry else ""))
            self._save_group(line)
            return {"miles": round(miles, 1), "days": round(days, 2), "path": way, "ended": len(back["ends"]),
                    "ate": ate, "hungry": hungry}

    def moves_back(self) -> int:
        """How many of the party's moves can be taken back."""
        return len(self._moves)

    def undo_move(self) -> dict:
        """Take the party's last move back: it goes back where it was (its trail too), the days the trip took turn
        back, and the meals eaten on the way go back into the team's pack. Returns `path` (the way it goes back),
        `days` (turned back) and `meals` (returned)."""
        with self.lock:
            if not self._moves:
                raise ServiceError("There is no move to take back.")
            back = self._moves.pop()
            p = self.d["party"]
            p["pos"], p["trail"] = back["pos"], back["trail"]
            if back["reached"]:
                p.setdefault("route", []).insert(0, back["reached"])
            meals = 0
            for end in reversed(back["ends"]):
                for e in end["went"]:
                    self.team.stock(e["qty"], e["name"], e["note"])
                    meals += e["qty"]
                k = str(end["day"])
                left = self.g["eaten"].get(k, 0) - end["ate"]
                if left > 0:
                    self.g["eaten"][k] = left
                else:
                    self.g["eaten"].pop(k, None)
                self.g["log"] = [x for x in self.g["log"] if x is not end["note"]]
            self.g["day"] = max(1, self.g["day"] - len(back["ends"]))
            self.g["walked"] = back["walked"]
            way = back["way"][::-1]
            self._leg(way, True)
            self._save_map(changed=False)
            days = len(back["ends"])
            self._save_group("The party's last move is taken back" +
                             (f": {days} day(s) turn back, {meals} meal(s) go back into the group's food" if days else ""))
            return {"path": way, "days": days, "meals": meals}

    def clear_trail(self):
        with self.lock:
            p = self.d["party"]
            p["trail"] = [list(p["pos"])] if p.get("pos") else []
            self._save_map(changed=False)

    def remove_party(self):
        with self.lock:
            self.d["party"] = {"pos": None, "trail": [], "route": []}
            self._moves.clear()
            self._save_map(changed=False)

    def set_route(self, pts):
        with self.lock:
            self.d["party"]["route"] = [list(self._in_map(x, y)) for x, y in list(pts)[:ROUTE_MAX]]
            self._save_map(changed=False)

    def route_info(self) -> dict:
        """Miles and days from the party along its route."""
        p = self.party()
        pts = ([p["pos"]] if p["pos"] else []) + p["route"]
        miles = self.miles(pts) if len(pts) > 1 else 0.0
        return {"miles": round(miles, 1), "days": round(self.days(miles), 1)}

    def nearest(self, x: float, y: float, marks: Optional[List[dict]] = None) -> Optional[dict]:
        """The named place closest to a point (within a sixth of the map), and how far (`marks`: the players' copy)."""
        best = None
        for m in self.marks() if marks is None else marks:
            if not m.get("name") or m["kind"] in SIZED:
                continue
            d = math.hypot(m["x"] - x, m["y"] - y)
            if best is None or d < best[0]:
                best = (d, m)
        if not best or best[0] > self.d["w"] / 6:
            return None
        return {"name": best[1]["name"], "miles": round(best[0] * self.miles_per_px(), 1), "here": best[0] < 8}

    # ------------------------------------------------------------------ pings
    def ping(self, x, y, who: str = "DM", uid: Optional[int] = None):
        x, y = self._in_map(x, y)
        p = {"x": x, "y": y, "who": (who or "?")[:40], "at": time.time(), "uid": str(uid) if uid else None}
        self._pings.append(p)
        for fn in list(self.listeners):
            try:
                fn(p)
            except Exception:
                pass
        self.h.notify(events.WORLD_PING)

    def recent_pings(self) -> List[dict]:
        cut = time.time() - PING_KEEP
        return [dict(p) for p in self._pings if p["at"] >= cut]

    # ------------------------------------------------------------------ food
    def mouths(self) -> int:
        """How many eat each day: the DM's number, or everyone sharing the team inventory."""
        return self.g["mouths"] if self.g["mouths"] else max(1, len(self.team.members()))

    def food(self) -> dict:
        """The group's food: the food in the team inventory (`stock`: its stacks, in the order they are eaten)."""
        with self.lock:
            stock = self.team.food()
            meals = sum(e["qty"] for e in stock)
            day = self.g["day"]
            days = [d for d in range(max(1, day - AVERAGE_DAYS), day)]
            avg = sum(self.g["eaten"].get(str(d), 0) for d in days) / len(days) if days else 0.0
            per = avg or self.mouths()
            return {"meals": meals, "day": day, "average": round(avg, 1), "mouths": self.mouths(),
                    "mouths_set": self.g["mouths"], "today": self.g["eaten"].get(str(day), 0),
                    "days_left": round(meals / per, 1) if per else None, "log": list(self.g["log"][-12:]),
                    "stock": [{"name": e["name"], "qty": e["qty"]} for e in stock]}

    def _note(self, n: int, why: str, by: str = "") -> dict:
        note = {"day": self.g["day"], "n": n, "why": why, "by": by, "at": time.strftime("%H:%M")}
        self.g["log"].append(note)
        del self.g["log"][:-60]
        return note

    def _eat(self, n: int) -> int:
        """`n` meals out of the team's pack (fewer when there aren't that many), counted as eaten today."""
        had = sum(e["qty"] for e in self.team.eat(n)) if n > 0 else 0
        day = str(self.g["day"])
        if had:
            self.g["eaten"][day] = self.g["eaten"].get(day, 0) + had
        return had

    def add_food(self, n, why: str = "", by: str = "The DM"):
        """Rations into the team's pack (bought, hunted, foraged...)."""
        n = positive_int(n, "Meals")
        with self.lock:
            self.team.stock(n)
            self._note(n, why or "Added", by)
            self._save_group(f"{by} adds {n} meal(s) to the group's food" + (f" ({why})" if why else "") +
                             f" - {self.team.meals()} left")

    def spend_food(self, n, why: str = "", by: str = "The DM"):
        n = positive_int(n, "Meals")
        with self.lock:
            have = self.team.meals()
            if n > have:
                raise ServiceError(f"The group has only {have} meal(s).")
            self._eat(n)
            self._note(-n, why or "Spent", by)
            self._save_group(f"The group spends {n} meal(s)" + (f" ({why})" if why else "") + f" - {have - n} left")

    def set_food(self, n):
        with self.lock:
            n = max(0, int(n))
            have = self.team.meals()
            if n == have:
                return
            if n > have:
                self.team.stock(n - have)
            else:
                self.team.eat(have - n)
            self._note(n - have, "Set by the DM", "The DM")
            self._save_group()

    def set_mouths(self, n: Optional[int]):
        with self.lock:
            self.g["mouths"] = int(n) if n else None
            self._save_group()

    def end_day(self, eat: bool = True) -> dict:
        """The day ends: the group eats a meal each (what there is), the day counter goes on."""
        with self.lock:
            end = self._day_ends(eat)
            self.g["walked"] = 0.0
            line = (f"Day {end['day']} ends: the group eats {end['ate']} meal(s) - {self.team.meals()} left" if eat
                    else f"Day {end['day']} ends")
            if end["hungry"]:
                line += f"; {end['hungry']} go hungry"
            self._save_group(line)
            return {"ate": end["ate"], "hungry": end["hungry"], "day": self.g["day"]}

    def _day_ends(self, eat: bool = True) -> dict:
        """A day ends (nothing saved): a meal each from the team's pack (what there is), the counter goes on. What
        happened, for undo_move to turn back: {"day", "ate", "hungry", "went": the food, "note": its log line}."""
        need = self.mouths() if eat else 0
        day = self.g["day"]
        went = self.team.eat(need) if need > 0 else []
        had = sum(e["qty"] for e in went)
        note = None
        if had:
            self.g["eaten"][str(day)] = self.g["eaten"].get(str(day), 0) + had
            note = self._note(-had, "Daily meals", "")
        self.g["day"] += 1
        for k in [k for k in self.g["eaten"] if int(k) < self.g["day"] - 40]:
            del self.g["eaten"][k]
        return {"day": day, "ate": had, "hungry": need - had, "went": went, "note": note}

    def set_day(self, n):
        with self.lock:
            self.g["day"] = max(1, int(n))
            self._save_group()

    def member_food(self) -> List[dict]:
        """Each character sharing the team inventory, and the food in their pack."""
        out = []
        for name in self.team.members():
            try:
                char = self.chars.get(name)
            except ServiceError:
                continue
            items = [{"name": e["name"], "qty": int(e.get("qty") or 1)} for e in char.inventory if is_food(e["name"])]
            items.sort(key=lambda e: food_order(e["name"]))
            out.append({"character": name, "owner": self.players.owner_of(name), "meals": sum(e["qty"] for e in items),
                        "items": items})
        return out

    def give_meal(self, character: str, item: Optional[str] = None, n: int = 1, by: Optional[str] = None):
        """Food out of a character's pack into the group's - the team inventory (rations first)."""
        n = positive_int(n, "Meals")
        with self.lock:
            char = self.chars.get(character)
            foods = [e for e in char.inventory if is_food(e["name"])]
            if item:
                foods = [e for e in foods if e["name"].lower() == item.lower()]
            foods.sort(key=lambda e: food_order(e["name"]))
            if not foods:
                raise ServiceError(f"{char.name} has no food to share.")
            entry = foods[0]
            n = min(n, int(entry.get("qty") or 1))
            name, note = entry["name"], entry.get("note") or ""
            line = f"{by or char.name} adds {n}× {name} from {char.name}'s pack to the group's food"
            self.chars.remove_item(char.name, name, n, note=line)
            self.team.stock(n, name, note)
            self._note(n, name, char.name)
            self._save_group()                                  # (the pack's change already said it)

    def take_meal(self, character: str, n: int = 1, by: Optional[str] = None):
        """Food out of the group's (rations first) into a character's pack (the DM hands it out)."""
        n = positive_int(n, "Meals")
        with self.lock:
            have = self.team.meals()
            if n > have:
                raise ServiceError(f"The group has only {have} meal(s).")
            char = self.chars.get(character)
            went = self.team.eat(n)
            line = f"{by or 'The DM'} gives " + ", ".join(f"{e['qty']}× {e['name']}" for e in went) + \
                f" from the group's food to {char.name}"
            try:
                for e in went:
                    self.chars.add_item(char.name, e["name"], e["qty"], note=line, desc=e["note"] or None)
            except ServiceError:
                for e in went:
                    self.team.stock(e["qty"], e["name"], e["note"])
                raise
            self._note(-n, "To " + char.name, by or "The DM")
            self._save_group()
