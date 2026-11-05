"""Floors: the storeys of a building side by side on one wide map - the main map (floor 0) with the floors upstairs to its
right (+1, +2...) and the cellars to its left (-1, -2...), each as big as the main map, GAP tiles apart. The rules see
one map: a wall runs round every floor (profile._terrain), the gaps can't be entered, and areas stop at the edge of
their floor (geometry), so nothing reaches from one floor to another but the stairs.

Stairs up or down put on a floor lead to the next floor up or down. When that floor isn't there yet it is made with
the same building (rooms, their doors and windows, drawn walls); either way matching stairs stand on the same tile of
it, linked to these ('link': the other one's id). A creature that walks onto linked stairs comes out at the other end.
When the last stairs leading to a floor are erased (either end), the floor goes too; Ctrl+Z brings both back.

    map = {'w': every floor's width with the gaps, 'h', 'fw': one floor's width, 'lo': lowest floor, 'hi': highest}
          (one floor: no fw, lo or hi)
    b.add_floor(+1)          # an empty floor over the highest (-1: under the lowest); returns its number
    b.remove_floor(-2)       # a floor (never 0) and everything on it; the ones beyond come one closer to the main map
"""
import copy
import math
from typing import Dict, List, Optional, Tuple

from ..common import ServiceError

GAP = 2                                                     # tiles between two floors
TOP = 99                                                    # floors up, and down
# stairs that lead to another floor: symbol or prop -> (floors up, what stands at the other end)
STAIRS = {"stairs_up": (1, "stairs_down"), "stairs_down": (-1, "stairs_up"),
          "ink_stairs_up": (1, "ink_stairs_down"), "ink_stairs_down": (-1, "ink_stairs_up"),
          "ink_ladder_up": (1, "ink_ladder_down"), "ink_ladder_down": (-1, "ink_ladder_up")}


def layout(m: dict) -> Tuple[int, int, int]:
    """(one floor's width, the lowest floor, the highest)."""
    return int(m.get("fw") or m["w"]), int(m.get("lo") or 0), int(m.get("hi") or 0)


def many(m: dict) -> bool:
    _fw, lo, hi = layout(m)
    return hi > lo


def shape(m: dict, fw: int, lo: int, hi: int) -> dict:
    """The map `m` (its height, light...) laid out for floors lo..hi, `fw` tiles wide each."""
    out = {k: v for k, v in m.items() if k not in ("fw", "lo", "hi")}
    out["w"] = (hi - lo + 1) * (fw + GAP) - GAP
    if hi > lo:
        out.update(fw=fw, lo=lo, hi=hi)
    return out


def left(m: dict, f: int) -> int:
    """Floor f's first column."""
    fw, lo, _hi = layout(m)
    return (f - lo) * (fw + GAP)


def floor_at(m: dict, x) -> Optional[int]:
    """The floor whose columns hold x (tile units); None in a gap or off the map."""
    fw, lo, hi = layout(m)
    i, r = divmod(math.floor(x), fw + GAP)
    return lo + i if 0 <= i <= hi - lo and r < fw else None


def nearest(m: dict, x) -> int:
    """The floor holding x, or in a gap the one on its left (lines and pictures may run off a floor's edge)."""
    fw, lo, hi = layout(m)
    return lo + max(0, min(hi - lo, math.floor(x) // (fw + GAP)))


def band(m: dict, x) -> Optional[Tuple[int, int]]:
    """The first and last column of the floor holding x."""
    f = floor_at(m, x)
    if f is None:
        return None
    a = left(m, f)
    return a, a + layout(m)[0] - 1


def floors(m: dict) -> List[Tuple[int, int]]:
    """[(floor, its first column)], the lowest first."""
    fw, lo, hi = layout(m)
    return [(f, (f - lo) * (fw + GAP)) for f in range(lo, hi + 1)]


def label(f: int) -> str:
    return "Main floor" if f == 0 else f"Floor +{f}" if f > 0 else f"Floor −{-f}"


def edge_walls(m: dict) -> List[dict]:
    """A wall round every floor when there are several: what keeps sight, steps and areas on their own floor."""
    if not many(m):
        return []
    fw, h = layout(m)[0], m["h"]
    return [{"type": "path", "pts": [[x, 0], [x + fw, 0], [x + fw, h], [x, h]], "closed": True, "wall": True} for _f, x in floors(m)]


class FloorsMixin:
    def add_floor(self, way: int) -> int:
        """An empty floor over the highest (way > 0) or under the lowest. Returns its number."""
        with self.lock:
            f = self._new_floor(1 if way > 0 else -1)
            self._commit(f"{label(f)} added")
            return f

    def remove_floor(self, f: int):
        """A floor and everything on it (creatures on it leave the map); the floors beyond it come one closer to the
        main map, which stays."""
        with self.lock:
            f = int(f)
            _fw, lo, hi = layout(self.b["map"])
            if f == 0 or not lo <= f <= hi:
                raise ServiceError("The main floor stays; pick another floor.")
            self._drop_floor(f)
            self._commit(f"{label(f)} removed")

    def _drop_floor(self, f: int):
        m = self.b["map"]
        fw, lo, hi = layout(m)
        moves = {k: None if k == f else k - 1 if k > f > 0 else k + 1 if k < f < 0 else k for k in range(lo, hi + 1)}
        self._relayout(shape(m, fw, lo + (f < 0), hi - (f > 0)), moves)

    def _linked_floors(self) -> set:
        """The floors linked stairs lead to or from (both ends still on the map)."""
        m = self.b["map"]
        stairs = {d["id"]: d for d in self.b.get("drawings") or [] if d.get("type") == "symbol" and d.get("sym") in STAIRS}
        out = set()
        for d in stairs.values():
            mate = stairs.get(d.get("link"))
            if mate and mate.get("link") == d["id"]:
                out |= {floor_at(m, d["x"]), floor_at(m, mate["x"])}
        return out - {None}

    def _drop_unlinked(self, before: set) -> Optional[str]:
        """After drawings were erased: the floors (never the main one) whose last stairs went with them go too, with
        everything on them - in the same undo step, so Ctrl+Z brings them back. `before`: _linked_floors() before the
        erasing. Returns what happened, for the log."""
        gone = sorted(before - self._linked_floors() - {0}, key=abs, reverse=True)   # the farthest first: no renumbering
        for f in gone:
            self._drop_floor(f)
        if not gone:
            return None
        names = " and ".join(label(f) for f in sorted(gone))
        return f"{names} removed: no stairs lead there any more"

    def _new_floor(self, way: int) -> int:
        m = self.b["map"]
        fw, lo, hi = layout(m)
        f = hi + 1 if way > 0 else lo - 1
        if abs(f) > TOP:
            raise ServiceError(f"A map has at most {TOP} floors up and {TOP} down.")
        self._relayout(shape(m, fw, min(lo, f), max(hi, f)), {k: k for k in range(lo, hi + 1)})
        return f

    def _relayout(self, new: dict, moves: Dict[int, Optional[int]]):
        """Everything on the map moved for a new layout of the floors (`new`, the map's new size): `moves` maps each old
        floor to its new number (None: it's gone, and what stood on it). Whatever is off its floor afterwards (it got
        smaller) goes too; creatures leave the map."""
        old = self.b["map"]
        fw, h = layout(new)[0], new["h"]

        def shift(x) -> Optional[Tuple[int, int]]:
            """(how far something at x moves, where it is on its floor), None when its floor is gone."""
            f = nearest(old, x)
            to = moves.get(f)
            return None if to is None else (left(new, to) - left(old, f), math.floor(x) - left(old, f))

        def fits(x, y, n=1) -> Optional[int]:
            s = shift(x)
            return s[0] if s and 0 <= s[1] and s[1] + n <= fw and 0 <= y and y + n <= h else None

        for c in self.b["combatants"]:
            if c.get("pos"):
                dx = fits(c["pos"][0], c["pos"][1], max(1, int(c.get("span") or 1)))
                if dx is None:
                    c["pos"], c["at"] = None, None
                else:
                    c["pos"] = [c["pos"][0] + dx, c["pos"][1]]
                    if c.get("at"):
                        c["at"] = [round(c["at"][0] + dx, 3), c["at"][1]]
        keep = []
        for d in self.b.get("drawings") or []:
            t = d.get("type")
            if t == "symbol":
                from .props import span
                dx = fits(d["x"], d["y"], span(d.get("sym", "")))
            elif t == "room":
                s = shift(d["x"])
                dx = None
                if s and s[1] < fw and d["y"] < h:
                    dx = s[0]
                    d["w"], d["h"] = min(d["w"], fw - s[1]), min(d["h"], h - d["y"])
                    if d.get("cut"):
                        d["cut"] = [[i, j] for i, j in d["cut"] if i < d["w"] and j < d["h"]]
            elif t == "path":
                s = shift(d["pts"][0][0])
                dx = s and s[0]
                if s:
                    d["pts"] = [[x + dx, y] for x, y in d["pts"]]
                    dx = 0
            elif t == "image":
                s = shift(d["x"] + d["w"] / 2)
                dx = s and s[0]
            else:                                            # a door: its wall moves with it (or it's tidied away)
                s = shift(d["x"] - (0.5 if d.get("v") else 0))
                dx = s and s[0]
            if dx is None:
                continue
            if "x" in d and t != "path":
                d["x"] += dx
            keep.append(d)
        self.b["drawings"] = keep
        for z in list(self.b.get("zones") or []):
            dx = fits(*z["tiles"][0]) if z.get("tiles") else None
            if dx is None:
                self._zone_off(z, "its floor is gone")
                continue
            base = left(new, nearest(new, z["tiles"][0][0] + dx))
            z["tiles"] = [[x + dx, y] for x, y in z["tiles"] if base <= x + dx < base + fw and y < h]
            if z.get("point"):
                z["point"] = [z["point"][0] + dx, z["point"][1]]
        ground = []
        for g in self.b.get("ground") or []:
            dx = fits(g["x"], g["y"])
            if dx is not None:
                g["x"] += dx
                if g.get("at"):
                    g["at"] = [round(g["at"][0] + dx, 3), g["at"][1]]
                ground.append(g)
        if "ground" in self.b:
            self.b["ground"] = ground
        self.b["map"] = new
        self._tidy_doors()

    # ------------------------------------------------------------------ stairs
    def _link_stairs(self, d: dict) -> Optional[str]:
        """Stairs up or down just put on a floor: matching stairs on the same tile of the next floor, made first (with
        this floor's building) when it isn't there. Returns what happened, for the log."""
        way, other = STAIRS.get(d.get("sym"), (0, None))
        f = floor_at(self.b["map"], d["x"]) if way else None
        if f is None or abs(f + way) > TOP:
            return None
        to = f + way
        _fw, lo, hi = layout(self.b["map"])
        made = not lo <= to <= hi
        if made:
            self._new_floor(way)                             # (a floor below: everything moved right, this too)
            self._copy_building(f, to)
        m, items = self.b["map"], self.b["drawings"]
        x = d["x"] - left(m, f) + left(m, to)
        mate = next((o for o in items if o.get("type") == "symbol" and o.get("sym") == other and o["x"] == x and o["y"] == d["y"]
                     and not any(p.get("link") == o["id"] for p in items)), None)
        if mate is None:
            mate = {"type": "symbol", "id": self._draw_id(), "sym": other, "x": x, "y": d["y"], "rot": d.get("rot", 0)}
            items.append(mate)
        d["link"], mate["link"] = mate["id"], d["id"]
        return f"{label(to)} added, its stairs linked" if made else f"Stairs linked to {label(to)}"

    def _copy_building(self, f: int, to: int):
        """Floor f's rooms, the doors and windows in their walls and its drawn walls, copied onto floor `to`."""
        from .drawing import MAX_DRAWINGS
        from .rooms import built
        m, items = self.b["map"], self.b["drawings"]
        a, fw = left(m, f), layout(m)[0]
        dx = left(m, to) - a
        src = [d for d in items if (d["type"] == "room" and a <= d["x"] < a + fw) or (built(d) and nearest(m, d["pts"][0][0]) == f)
               or (d["type"] == "door" and nearest(m, d["x"] - (0.5 if d["v"] else 0)) == f)]
        if len(items) + len(src) >= MAX_DRAWINGS:
            return
        for d in src:
            c = copy.deepcopy(d)
            c["id"] = self._draw_id()
            if c["type"] == "path":
                c["pts"] = [[x + dx, y] for x, y in c["pts"]]
            else:
                c["x"] += dx
            if c["type"] == "door":
                c["open"] = False
            c.pop("link", None)
            items.append(c)

    def _stairs_under(self, c: dict) -> Optional[Tuple[dict, dict]]:
        """(the linked stairs the creature stands on, the other end)."""
        from .props import span
        if not c.get("pos"):
            return None
        feet = {tuple(t) for t in self._footprint(c, *c["pos"])}
        items = self.b.get("drawings") or []
        for d in items:
            if d.get("type") == "symbol" and d.get("link") and d.get("sym") in STAIRS:
                n = span(d["sym"])
                if any((d["x"] + i, d["y"] + j) in feet for i in range(n) for j in range(n)):
                    mate = next((o for o in items if o["id"] == d["link"] and o.get("type") == "symbol"), None)
                    if mate:
                        return d, mate
        return None

    def _take_stairs(self, c: dict, R: Optional[dict] = None) -> bool:
        """A creature that ended its walk on linked stairs comes out at their other end (a free tile next to it when
        someone stands there). Zones there bite as if it walked in."""
        found = self._stairs_under(c)
        if not found:
            return False
        d, mate = found
        m = self.b["map"]
        spot = self._free_near(c, mate["x"], mate["y"])
        to = floor_at(m, mate["x"])
        if not spot or floor_at(m, spot[0]) != to:
            return False
        before = set(map(tuple, self._footprint(c, *c["pos"])))
        self._vfx("blink", id=c["id"], at=c.get("pos"), to=list(spot))
        c["pos"], c["at"] = list(spot), None
        self._follow_zones(c)
        text = f"{c['name']} takes the {'stairs' if 'stair' in d['sym'] else 'ladder'} {'up' if STAIRS[d['sym']][0] > 0 else 'down'} to {label(to)}"
        if R is not None:
            self._line(R, text, label(to))
            for S in reversed(self._zone_entered(c, before, set(map(tuple, self._footprint(c, *spot))), R)):
                self._stack().append(S)
        else:
            self._say(text)
        return True

    def _follow_link(self, d: dict, was: Tuple[int, int]):
        """Stairs moved on their floor: the other end moves the same way, when it stood on the matching tile."""
        m, items = self.b["map"], self.b.get("drawings") or []
        mate = next((o for o in items if o["id"] == d.get("link") and o.get("type") == "symbol"), None) if d.get("link") else None
        f, f2 = floor_at(m, was[0]), floor_at(m, d["x"])
        if mate is None or f is None or f != f2:
            return
        g = floor_at(m, mate["x"])
        if g is None or mate["x"] - left(m, g) != was[0] - left(m, f) or mate["y"] != was[1]:
            return
        x = d["x"] - left(m, f) + left(m, g)
        if floor_at(m, x) == g:
            mate["x"], mate["y"] = x, d["y"]
