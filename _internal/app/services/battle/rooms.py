"""Rooms on the battle map: a box dragged out on the grid becomes a room - its floor and walls all round, no doors or
windows. Rooms that touch share a wall and get a door in the middle of it; rooms that overlap become one space. A
click on a wall puts a door there (or takes it off). They are drawings (type 'room', and 'door' for a door in a room's
wall), so they belong to the map like the other drawings, block movement and sight (sight.py) and players see them.

A room's `cut` lists the tiles erased out of it ([i, j] from its corner): its walls follow the shape that's left. Walls
drawn with the draw tool (snapped lines, built()) are walls like a room's: drawn the same, doors and windows go in them,
and a closed one has a floor inside.

    b.add_room(2, 3, 8, 7)              # tiles (2,3) to (8,7), both corners included; returns its id
    b.erase_rooms(4, 4, 5, 6)           # those tiles out of every room (a room left with none is gone)
    b.door_on_wall(5.0, 3.1)            # the wall nearest the point: a door put in, or taken off
    b.put_in_wall(5, 3, True, "window") # a window (WALL_KINDS) in that wall edge; None: a plain wall again
    b.toggle_door(id)                   # a room's door opens and closes like a door symbol (drawing.py)
    plan(drawings)                      # {'floor', 'walls', 'runs', 'doors'}: what the screens draw

An edge is (x, y, v): v=True the upright edge from (x, y) to (x, y+1), between tiles (x-1, y) and (x, y); v=False the
flat one from (x, y) to (x+1, y), between tiles (x, y-1) and (x, y).
"""
import math
from functools import lru_cache
from typing import Dict, List, Optional, Tuple

from ..common import ServiceError
from . import floors as F

Edge = Tuple[int, int, bool]
MAX_ROOM = 80                                               # tiles across, either way
# what can stand in a room's wall (a door drawing's 'kind'): label, opens (O / double-click / right-click), and what it
#   does: shut door: blocks like the wall, open: lets creatures and sight through;  window, portcullis: sight and light
#   pass, nobody does - open (raised): creatures climb or walk through too;  archway: an opening, nothing blocked
WALL_KINDS = {
    "door": ("Door", True), "double": ("Double door", True), "locked": ("Locked door", True),
    "secret": ("Secret door", True), "window": ("Window", True), "portcullis": ("Portcullis", True),
    "archway": ("Archway", False),
}
SEE_THROUGH = ("window", "portcullis")


def kind_of(d: dict) -> str:
    return d.get("kind") if d.get("kind") in WALL_KINDS else "door"


def cut_of(d: dict) -> tuple:
    """The tiles erased out of a room, as sorted (i, j) from its corner."""
    return tuple(sorted({(int(i), int(j)) for i, j in d.get("cut") or []}))


def _rooms_key(drawings) -> tuple:
    return tuple((d["id"], d["x"], d["y"], d["w"], d["h"], cut_of(d)) for d in drawings or [] if d.get("type") == "room")


def built(d: dict) -> bool:
    """A drawn line that is a wall like a room's: snapped to the tile corners and not opted out of being a wall (nor
    given a cover level instead: see cover_of)."""
    return d.get("type") == "path" and d.get("wall") is not False and not d.get("cover") and len(d.get("pts") or []) > 1 and \
        all(float(x).is_integer() and float(y).is_integer() for x, y in d["pts"])


LINE_COVER = ("wall", "total", "half", "none")


def cover_of(d: dict) -> str:
    """What a drawn line is on the battlefield: 'wall' (a room's kind of wall, snapped lines by default), 'total' (blocks
    movement, sight and light, drawn as a line: a hedge, a palisade), 'half' (half cover, walked over: a low wall, a
    fence) or 'none' (only a drawing: free strokes by default)."""
    if d.get("cover") in LINE_COVER[1:]:
        return d["cover"]
    if built(d):
        return "wall"
    return "total" if d.get("wall") is True else "none"


def _paths_key(drawings) -> tuple:
    return tuple((d["id"], tuple((int(x), int(y)) for x, y in d["pts"]), bool(d.get("closed"))) for d in drawings or [] if built(d))


def segments(pts, closed: bool) -> list:
    seq = list(pts) + ([pts[0]] if closed and len(pts) > 2 and tuple(pts[0]) != tuple(pts[-1]) else [])
    return list(zip(seq, seq[1:]))


def path_edges(pts, closed: bool) -> List[Edge]:
    """The wall edges along a snapped line's straight (upright or flat) parts; slanted parts aren't on the grid."""
    out = []
    for (x1, y1), (x2, y2) in segments(pts, closed):
        if x1 == x2:
            out += [(int(x1), y, True) for y in range(int(min(y1, y2)), int(max(y1, y2)))]
        elif y1 == y2:
            out += [(x, int(y1), False) for x in range(int(min(x1, x2)), int(max(x1, x2)))]
    return out


def inside(pts) -> List[Tuple[int, int]]:
    """The tiles whose middle is inside a closed line (its floor)."""
    xs, ys = [p[0] for p in pts], [p[1] for p in pts]
    if max(xs) - min(xs) > 4 * MAX_ROOM or max(ys) - min(ys) > 4 * MAX_ROOM:
        return []
    edges = segments(pts, True)
    out = []
    for ty in range(int(min(ys)), int(max(ys))):
        cy = ty + 0.5
        cuts = sorted(x1 + (cy - y1) * (x2 - x1) / (y2 - y1) for (x1, y1), (x2, y2) in edges if (y1 > cy) != (y2 > cy))
        for a, b in zip(cuts[::2], cuts[1::2]):
            out += [(tx, ty) for tx in range(math.ceil(a - 0.5), math.floor(b - 0.5) + 1)]
    return out


def owners(rooms, paths=()) -> Dict[Tuple[int, int], frozenset]:
    """Floor tile -> the rooms it belongs to. `rooms`: (id, x, y, w, h, cut) rows; `paths`: (id, pts, closed) rows of
    built walls, a closed one with its inside as a room's floor."""
    own = {}
    for rid, x, y, w, h, *rest in rooms:
        cut = set(rest[0]) if rest else ()
        for i in range(w):
            for j in range(h):
                if (i, j) not in cut:
                    own.setdefault((x + i, y + j), set()).add(rid)
    for pid, pts, closed in paths:
        if closed and len(pts) > 2:
            for t in inside(pts):
                own.setdefault(t, set()).add(pid)
    return {t: frozenset(s) for t, s in own.items()}


@lru_cache(maxsize=32)
def _walls(rooms: tuple, paths: tuple = ()) -> Dict[Edge, int]:
    """Every wall edge -> where its floor is: 1 (right of it / below), -1 (left / above), 0 (both: two rooms share it,
    or a drawn wall across a room), 2 (neither: a drawn wall standing on its own)."""
    own = owners(rooms, paths)
    out = {}
    for (x, y), ids in own.items():
        for n, edge, side in (((x - 1, y), (x, y, True), 1), ((x + 1, y), (x + 1, y, True), -1),
                              ((x, y - 1), (x, y, False), 1), ((x, y + 1), (x, y + 1, False), -1)):
            other = own.get(n)
            if other is None:
                out[edge] = side
            elif not ids & other:
                out[edge] = 0
    for _pid, pts, closed in paths:
        for e in path_edges(pts, closed):
            if e not in out:
                x, y, v = e
                before, after = ((x - 1, y), (x, y)) if v else ((x, y - 1), (x, y))
                out[e] = (0 if before in own else 1) if after in own else -1 if before in own else 2
    return out


def walls(drawings) -> Dict[Edge, int]:
    """The rooms' walls and the drawn walls (see _walls)."""
    return _walls(_rooms_key(drawings), _paths_key(drawings))


def room_walls(drawings) -> Dict[Edge, int]:
    """The rooms' walls alone."""
    return _walls(_rooms_key(drawings))


def carve(drawings, x0: int, y0: int, x1: int, y1: int) -> list:
    """The drawings with the tiles from (x0, y0) to (x1, y1) erased out of every room: a room keeps the shape that's
    left (its box shrunk to it), and is gone when nothing is. The rooms changed are new dicts; the rest are the same."""
    xa, xb = sorted((int(x0), int(x1)))
    ya, yb = sorted((int(y0), int(y1)))
    out = []
    for d in drawings or []:
        if d.get("type") != "room" or d["x"] > xb or d["x"] + d["w"] <= xa or d["y"] > yb or d["y"] + d["h"] <= ya:
            out.append(d)
            continue
        cut = set(cut_of(d))
        left = [(d["x"] + i, d["y"] + j) for i in range(d["w"]) for j in range(d["h"])
                if (i, j) not in cut and not (xa <= d["x"] + i <= xb and ya <= d["y"] + j <= yb)]
        if not left:
            continue
        nx, ny = min(t[0] for t in left), min(t[1] for t in left)
        nw, nh = max(t[0] for t in left) - nx + 1, max(t[1] for t in left) - ny + 1
        keep = set(left)
        gone = sorted([i, j] for i in range(nw) for j in range(nh) if (nx + i, ny + j) not in keep)
        room = {k: v for k, v in d.items() if k != "cut"}
        room.update(x=nx, y=ny, w=nw, h=nh)
        if gone:
            room["cut"] = gone
        out.append(room)
    return out


def runs(edges) -> List[Tuple[Edge, int]]:
    """Wall edges joined into straight runs: [(first edge, length)]."""
    out = []
    for v in (True, False):
        line = sorted((e[0], e[1]) if v else (e[1], e[0]) for e in edges if e[2] == v)
        start = prev = None
        for a, b in line:
            if prev and prev[0] == a and prev[1] + 1 == b:
                prev = (a, b)
                continue
            if start:
                out.append(((start[0], start[1], True) if v else (start[1], start[0], False), prev[1] - start[1] + 1))
            start = prev = (a, b)
        if start:
            out.append(((start[0], start[1], True) if v else (start[1], start[0], False), prev[1] - start[1] + 1))
    return out


def run_edges(first: Edge, n: int) -> List[Edge]:
    x, y, v = first
    return [(x, y + i, True) if v else (x + i, y, False) for i in range(n)]


def door_edge(d: dict) -> Edge:
    return int(d["x"]), int(d["y"]), bool(d["v"])


def plan(drawings) -> dict:
    """What the screens draw: the floor tiles, the wall edges with where their floor is ([x, y, v, side]), the walls
    as straight runs ([x1, y1, x2, y2]), the slanted bits of drawn walls ([x1, y1, x2, y2]) and what stands in a wall
    ({id, x, y, v, open, kind}: WALL_KINDS)."""
    w = walls(drawings)
    doors = [{"id": d["id"], "x": d["x"], "y": d["y"], "v": bool(d["v"]), "open": bool(d.get("open")), "kind": kind_of(d)}
             for d in drawings or [] if d.get("type") == "door" and door_edge(d) in w]
    rows = []
    for (x, y, v), n in runs(w):
        rows.append([x, y, x, y + n] if v else [x, y, x + n, y])
    slants = [[a[0], a[1], b[0], b[1]] for _i, pts, closed in _paths_key(drawings) for a, b in segments(pts, closed)
              if a[0] != b[0] and a[1] != b[1]]
    return {"floor": sorted([x, y] for x, y in owners(_rooms_key(drawings), _paths_key(drawings))),
            "walls": [[x, y, v, s] for (x, y, v), s in sorted(w.items())], "runs": rows, "slants": slants, "doors": doors}


def nearest_wall(drawings, x: float, y: float, reach: float = 0.35) -> Optional[Edge]:
    """The wall edge nearest a point (tile units), if one is within `reach` of it."""
    best, far = None, reach
    for (ex, ey, v) in walls(drawings):
        across, along = (x - ex, y - ey - 0.5) if v else (y - ey, x - ex - 0.5)
        d = math.hypot(across, max(0.0, abs(along) - 0.5))
        if d <= far:
            best, far = (ex, ey, v), d
    return best


def inside_tile(drawings, edge: Edge, x: float, y: float) -> Tuple[Tuple[int, int], int]:
    """The floor tile beside a wall edge (on the clicked side when rooms share it) and the turn (0-3, a quarter each,
    clockwise) that puts the top of a picture against that wall."""
    ex, ey, v = edge
    side = walls(drawings).get(edge, 1)
    if side in (0, 2):
        side = 1 if (x >= ex if v else y >= ey) else -1
    if v:
        return ((ex, ey), 3) if side == 1 else ((ex - 1, ey), 1)
    return ((ex, ey), 0) if side == 1 else ((ex, ey - 1), 2)


class RoomsMixin:
    def _draw_id(self) -> int:
        n = self.b.get("draw_next", 1)
        self.b["draw_next"] = n + 1
        return n

    def add_room(self, x0: int, y0: int, x1: int, y1: int, doors: bool = True) -> int:
        """A room over the tiles from (x0, y0) to (x1, y1), both included, cut to the map. Where it touches another room
        their shared wall gets a door in its middle (doors=False: none)."""
        with self.lock:
            m = self.b["map"]
            band = F.band(m, int(x0)) or F.band(m, int(x1))         # one floor: the one the box starts on
            if band is None:
                raise ServiceError("Drag the room out over the map's tiles.")
            xa, xb = sorted((int(x0), int(x1)))
            ya, yb = sorted((int(y0), int(y1)))
            xa, ya, xb, yb = max(band[0], xa), max(0, ya), min(band[1], xb), min(m["h"] - 1, yb)
            if xa > xb or ya > yb:
                raise ServiceError("Drag the room out over the map's tiles.")
            if xb - xa >= MAX_ROOM or yb - ya >= MAX_ROOM:
                raise ServiceError("That room is too big.")
            items = self.b.setdefault("drawings", [])
            from .drawing import MAX_DRAWINGS
            if len(items) >= MAX_DRAWINGS:
                raise ServiceError("The map has too many drawings; erase some first.")
            room = {"type": "room", "id": self._draw_id(), "x": xa, "y": ya, "w": xb - xa + 1, "h": yb - ya + 1}
            new = []
            if doors:
                w = room_walls(items + [room])
                mine = {(xa + i, ya + j) for i in range(room["w"]) for j in range(room["h"])}
                have = {door_edge(d) for d in items if d.get("type") == "door"}
                shared = [e for e, side in w.items() if side == 0 and
                          ((e[0], e[1]) in mine or ((e[0] - 1, e[1]) if e[2] else (e[0], e[1] - 1)) in mine)]
                for first, n in runs(shared):
                    run = run_edges(first, n)
                    if not have.intersection(run):
                        x, y, v = run[(n - 1) // 2]
                        new.append({"type": "door", "id": self._draw_id(), "x": x, "y": y, "v": v, "open": False})
            items.extend(new)                                # the doors first: undoing the last drawing takes the room
            items.append(room)
            self._tidy_doors()
            self._commit()
            return room["id"]

    def erase_rooms(self, x0: int, y0: int, x1: int, y1: int) -> int:
        """The tiles from (x0, y0) to (x1, y1), both included, erased out of the rooms: each keeps the shape that's left,
        its walls following it (doors in walls that are gone go too). Returns how many rooms changed."""
        with self.lock:
            items = self.b.get("drawings", [])
            after = carve(items, x0, y0, x1, y1)
            changed = sum(1 for d in items if d.get("type") == "room" and d not in after)
            if not changed:
                return 0
            self.b["drawings"] = after
            self._tidy_doors()
            self._commit()
            return changed

    def door_on_wall(self, x: float, y: float) -> Optional[bool]:
        """The room wall nearest the point gets a door, or loses the one it has. True: a door put in, False: taken off,
        None: no wall there."""
        with self.lock:
            items = self.b.get("drawings", [])
            e = nearest_wall(items, x, y)
            if e is None:
                return None
            had = [d for d in items if d.get("type") == "door" and door_edge(d) == e]
            if had:
                self.b["drawings"] = [d for d in items if d not in had]
            else:
                items.append({"type": "door", "id": self._draw_id(), "x": e[0], "y": e[1], "v": e[2], "open": False})
            self._commit()
            return not had

    def put_in_wall(self, x: int, y: int, v: bool, kind: Optional[str]) -> Optional[int]:
        """A door, window, archway... (WALL_KINDS) in the room wall at edge (x, y, v), in place of what stood there;
        kind=None takes it out (a plain wall again). Returns the new drawing's id."""
        if kind is not None and kind not in WALL_KINDS:
            raise ServiceError(f"Nothing called '{kind}' goes in a wall.")
        e = (int(x), int(y), bool(v))
        with self.lock:
            items = self.b.get("drawings", [])
            if e not in walls(items):
                raise ServiceError("There's no room wall there.")
            had = next((d for d in items if d.get("type") == "door" and door_edge(d) == e), None)
            if had and kind:                                 # changed: the same drawing (it stays selected)
                had.update(kind=kind, open=False)
            elif had:
                self.b["drawings"] = [d for d in items if d is not had]
            elif kind:
                had = {"type": "door", "id": self._draw_id(), "x": e[0], "y": e[1], "v": e[2], "open": False, "kind": kind}
                items.append(had)
            self._commit()
            return had["id"] if had and kind else None

    def _tidy_doors(self):
        """Doors whose wall is gone (its room moved or erased) go too."""
        items = self.b.get("drawings", [])
        if not any(d.get("type") == "door" for d in items):
            return
        w = walls(items)
        self.b["drawings"] = [d for d in items if d.get("type") != "door" or door_edge(d) in w]
