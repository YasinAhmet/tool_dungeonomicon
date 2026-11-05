"""Drawing on the battle map: snapped lines and rooms, and map symbols (doors, stairs, traps...). They belong to the
map, not to one fight: a new battle keeps them. Players see them on the portal.

    b.draw_path([[1.2, 3.1], [5.8, 2.9], ...], color="#c9b27a")    # a rough stroke, snapped to the grid
    b.set_cover(id, "half")             # a line as a wall, full / half / no cover (rooms.cover_of; draw_path(cover=) too)
    b.add_symbol("door", 4, 2)          # SYMBOLS lists them;  b.rotate_symbol(id)  b.move_drawing(id, x, y)  b.toggle_door(id)
    b.add_symbol("stairs_up", 6, 2)     # stairs up / down: linked to the next floor's, made when needed (floors.py)
    b.erase_near(4.5, 2.5)              # everything within half a tile;  b.erase(id)  b.undo_drawing()  b.clear_drawings()
    b.add_image(data, "webp", 800, 600, 5.0, 4.0)   # a picture dropped on the map;  b.set_image(id, x=, rot=, layer=...)
    b.restack(id, "front")              # its place among the pictures of its layer: front, back, up, down
    b.add_room(2, 3, 8, 7)              # a room: floor and walls; touching rooms get a door (rooms.py)

Pictures (type 'image') are stored once by their content in battle_images/ next to the battle file. Their layer is
'ground' (under the grid: a whole battle map), 'map' (with the drawings, under the tokens) or 'top' (over the tokens:
a roof, a canopy). A locked picture can't be picked up by a click; a hidden one isn't sent to the players.
"""
import hashlib
import math
import os
import re
from typing import Dict, List, Optional

from ..common import ServiceError
from . import floors as F, shapes
from .props import OPENS, PROPS, span
from .rooms import LINE_COVER, WALL_KINDS, RoomsMixin, built, kind_of

# id -> (glyph, label): drawn as the glyph in the middle of its tile, in the editor and on the players' page
SYMBOLS: Dict[str, tuple] = {
    "door": ("🚪", "Door"), "locked_door": ("🔒", "Locked door"), "secret_door": ("S", "Secret door"),
    "stairs_up": ("▲", "Stairs up"), "stairs_down": ("▼", "Stairs down"), "window": ("▭", "Window"),
    "trap": ("⚠", "Trap"), "chest": ("🧰", "Chest"), "pillar": ("●", "Pillar"), "statue": ("🗿", "Statue"),
    "fire": ("🔥", "Fire"), "water": ("💧", "Water"), "tree": ("🌲", "Tree"), "rock": ("🪨", "Rubble"),
    "altar": ("⛩", "Altar"), "lever": ("🕹", "Lever"),
}
COLORS = ("#c9b27a", "#e6e9ef", "#7c8cff", "#4ade80", "#f87171", "#fbbf24", "#3a3f4b")
MAX_DRAWINGS = 800
MAX_POINTS = 2000
IMAGE_TYPES = {"webp": "image/webp", "png": "image/png", "jpg": "image/jpeg"}
IMAGE_LAYERS = ("ground", "map", "top")
MAX_IMAGES = 60
MAX_IMAGE_BYTES = 6_000_000
BIG_IMAGE = 700                                             # pixels: a picture this big is taken for a whole battle map


def image_hit(d: dict, x: float, y: float) -> bool:
    """Is the point (tile units) on the picture, rotation included?"""
    cx, cy = d["x"] + d["w"] / 2, d["y"] + d["h"] / 2
    a = math.radians(-float(d.get("rot") or 0))
    dx, dy = x - cx, y - cy
    rx, ry = dx * math.cos(a) - dy * math.sin(a), dx * math.sin(a) + dy * math.cos(a)
    return abs(rx) <= d["w"] / 2 and abs(ry) <= d["h"] / 2


def _outline(d: dict) -> Optional[list]:
    """A room's walls, or a room door's edge, as points (for picking them and the eraser)."""
    if d.get("type") == "room":
        x, y, w, h = d["x"], d["y"], d["w"], d["h"]
        return [[x, y], [x + w, y], [x + w, y + h], [x, y + h]]
    if d.get("type") == "door":
        x, y = d["x"], d["y"]
        return [[x, y], [x, y + 1]] if d["v"] else [[x, y], [x + 1, y]]
    return None


def _span(d: dict) -> int:
    """Tiles across a symbol covers (props such as a tent are 2 x 2)."""
    return span(d.get("sym", "")) if d.get("type") == "symbol" else 1


class DrawingMixin(RoomsMixin):
    # ------------------------------------------------------------------ plumbing
    def drawings(self) -> List[dict]:
        with self.lock:
            return [dict(d) for d in self.b.get("drawings", [])]

    def _new_drawing(self, d: dict) -> int:
        items = self.b.setdefault("drawings", [])
        if len(items) >= MAX_DRAWINGS:
            raise ServiceError("The map has too many drawings; erase some first.")
        d["id"] = self.b.get("draw_next", 1)
        self.b["draw_next"] = d["id"] + 1
        items.append(d)
        self._commit()
        return d["id"]

    def _drawing(self, did: int) -> dict:
        d = next((x for x in self.b.get("drawings", []) if x["id"] == did), None)
        if d is None:
            raise ServiceError("That drawing isn't on the map any more.")
        return d

    # ------------------------------------------------------------------ adding
    def draw_path(self, points, color: str = COLORS[0], width: int = 3, snap: bool = True, cover: Optional[str] = None) -> Optional[int]:
        """A stroke: snapped to the grid (lines along tile edges, closed into a room when it ends at its start)
        or kept as drawn (snap=False). `cover` (rooms.LINE_COVER) other than its default: snapped lines are walls, free
        strokes only drawings. Returns its id, or None when nothing was left (a click)."""
        pts = [(float(x), float(y)) for x, y in list(points)[:MAX_POINTS]]
        if cover is not None and cover not in LINE_COVER:
            raise ServiceError("A line is a wall, full cover, half cover or no cover.")
        with self.lock:
            if snap:
                path, closed = shapes.snap(pts)
            else:
                path, closed = [[round(x, 2), round(y, 2)] for x, y in shapes.simplify(pts, 0.08)], False
            if len(path) < 2:
                return None
            d = {"type": "path", "pts": path, "closed": closed, "color": color if color in COLORS else COLORS[0],
                 "width": max(1, min(8, int(width)))}
            if cover and cover != "wall" and (snap or cover != "none"):
                d["cover"] = cover
            elif cover == "wall" and not snap:
                d["cover"] = "total"                         # a free stroke can't be a room's wall: it blocks like one
            return self._new_drawing(d)

    def add_symbol(self, symbol: str, x: int, y: int, rot: int = 0, link: bool = True) -> int:
        """A map symbol (SYMBOLS) or a prop picture (props.PROPS) on a tile. Stairs up or down lead to the next floor
        (floors.py: made, with this floor's building, when it isn't there yet); link=False: just the picture."""
        if symbol not in SYMBOLS and symbol not in PROPS:
            raise ServiceError(f"Unknown map symbol '{symbol}'.")
        with self.lock:
            m = self.b["map"]
            if not (0 <= int(y) < m["h"]) or F.floor_at(m, int(x)) is None:
                raise ServiceError("Put it on a tile of the map.")
            items = self.b.setdefault("drawings", [])
            if len(items) >= MAX_DRAWINGS:
                raise ServiceError("The map has too many drawings; erase some first.")
            d = {"type": "symbol", "id": self._draw_id(), "sym": symbol, "x": int(x), "y": int(y), "rot": int(rot) % 4}
            items.append(d)
            done = self._link_stairs(d) if link else None
            self._commit(done)
            return d["id"]

    # ------------------------------------------------------------------ pictures
    def _image_dir(self) -> str:
        return os.path.join(os.path.dirname(self.path) or ".", "battle_images")

    def image_file(self, key: str) -> Optional[str]:
        """The stored file of a picture key, or None."""
        if not re.fullmatch(r"[0-9a-f]{20}\.(webp|png|jpg)", key or ""):
            return None
        path = os.path.join(self._image_dir(), key)
        return path if os.path.isfile(path) else None

    def add_image(self, data: bytes, ext: str, px_w: int, px_h: int, x: float, y: float, name: str = "") -> int:
        """A picture dropped on the map (the editor has already scaled it down), centred on (x, y). A big one is taken
        for a whole battle map: it covers the map, under the grid. A small one is three tiles across, under the tokens."""
        ext = (ext or "").lower().lstrip(".").replace("jpeg", "jpg")
        if ext not in IMAGE_TYPES:
            raise ServiceError("Pictures can be WebP, PNG or JPEG.")
        if not data or len(data) > MAX_IMAGE_BYTES:
            raise ServiceError("That picture is too big for the map.")
        px_w, px_h = max(1, int(px_w)), max(1, int(px_h))
        key = hashlib.sha1(data).hexdigest()[:20] + "." + ext
        with self.lock:
            if sum(1 for d in self.b.get("drawings", []) if d["type"] == "image") >= MAX_IMAGES:
                raise ServiceError("The map has too many pictures; erase some first.")
            path = os.path.join(self._image_dir(), key)
            if not os.path.isfile(path):
                os.makedirs(self._image_dir(), exist_ok=True)
                with open(path, "wb") as f:
                    f.write(data)
            m = self.b["map"]
            if max(px_w, px_h) >= BIG_IMAGE:                  # (the floor it was dropped on, when there are several)
                fw, a = F.layout(m)[0], F.left(m, F.nearest(m, float(x)))
                k = min(fw / px_w, m["h"] / px_h)
                w, h, layer = px_w * k, px_h * k, "ground"
                x0, y0 = a + (fw - w) / 2, (m["h"] - h) / 2
            else:
                k = 3.0 / max(px_w, px_h)
                w, h, layer = px_w * k, px_h * k, "map"
                x0, y0 = float(x) - w / 2, float(y) - h / 2
            return self._new_drawing({"type": "image", "img": key, "x": round(x0, 3), "y": round(y0, 3), "w": round(w, 3),
                                      "h": round(h, 3), "rot": 0.0, "layer": layer, "name": str(name or "")[:80]})

    def set_image(self, did: int, *, x: Optional[float] = None, y: Optional[float] = None, w: Optional[float] = None,
                  h: Optional[float] = None, rot: Optional[float] = None, layer: Optional[str] = None,
                  locked: Optional[bool] = None, hidden: Optional[bool] = None):
        """Move, size, turn (degrees), layer, lock or hide a picture - all in one change."""
        with self.lock:
            d = self._drawing(did)
            if d["type"] != "image":
                raise ServiceError("That isn't a picture.")
            m = self.b["map"]
            top = 4.0 * max(m["w"], m["h"])
            if w is not None:
                d["w"] = round(max(0.2, min(top, float(w))), 3)
            if h is not None:
                d["h"] = round(max(0.2, min(top, float(h))), 3)
            if x is not None:
                d["x"] = round(max(-d["w"] + 0.5, min(m["w"] - 0.5, float(x))), 3)
            if y is not None:
                d["y"] = round(max(-d["h"] + 0.5, min(m["h"] - 0.5, float(y))), 3)
            if rot is not None:
                d["rot"] = round(float(rot) % 360, 2)
            if layer is not None:
                if layer not in IMAGE_LAYERS:
                    raise ServiceError("A picture's layer is ground, map or top.")
                d["layer"] = layer
            if locked is not None:
                d["locked"] = bool(locked)
            if hidden is not None:
                d["hidden"] = bool(hidden)
            self._commit()

    def restack(self, did: int, where: str):
        """A picture's place among the others of its layer: 'front', 'back', 'up' (one forward) or 'down'."""
        if where not in ("front", "back", "up", "down"):
            raise ServiceError("Move it to the front, the back, up or down.")
        with self.lock:
            d = self._drawing(did)
            items = self.b["drawings"]
            layer = d.get("layer", "map")
            same = [x for x in items if x["type"] == "image" and x.get("layer", "map") == layer]
            i = same.index(d)
            j = {"front": len(same) - 1, "back": 0, "up": min(len(same) - 1, i + 1), "down": max(0, i - 1)}[where]
            if i != j:
                same.insert(j, same.pop(i))
                it = iter(same)                              # the layer's pictures in their new order, the rest where they were
                self.b["drawings"] = [next(it) if x["type"] == "image" and x.get("layer", "map") == layer else x for x in items]
            self._commit()

    # ------------------------------------------------------------------ changing
    def move_drawing(self, did: int, x: int, y: int):
        """Move a symbol to a tile (a path: shift it so its first corner lands there)."""
        with self.lock:
            d = self._drawing(did)
            m = self.b["map"]
            if d["type"] == "room":                          # kept on one floor, all of it on the map
                band = F.band(m, int(x)) or F.band(m, int(x) + d["w"] - 1)
                if band is None:
                    raise ServiceError("Put it on a tile of the map.")
                d["x"] = max(band[0], min(band[1] - d["w"] + 1, int(x)))
                d["y"] = max(0, min(m["h"] - d["h"], int(y)))
            elif d["type"] == "symbol":
                if F.floor_at(m, int(x)) is None or not 0 <= int(y) < m["h"]:
                    raise ServiceError("Put it on a tile of the map.")
                was = (d["x"], d["y"])
                d["x"], d["y"] = int(x), int(y)
                self._follow_link(d, was)
            elif d["type"] == "door":
                raise ServiceError("A door stays in its wall.")
            else:
                dx, dy = int(x) - d["pts"][0][0], int(y) - d["pts"][0][1]
                d["pts"] = [[px + dx, py + dy] for px, py in d["pts"]]
            self._tidy_doors()
            self._commit()

    def toggle_door(self, did: int) -> bool:
        """Open or close a door, window, gate or portcullis: a symbol or prop (props.OPENS) or what stands in a room's
        wall (an open door lets creatures, sight and light through the wall; an open window lets creatures climb through)."""
        with self.lock:
            d = self._drawing(did)
            if d.get("sym") not in OPENS and not (d["type"] == "door" and WALL_KINDS[kind_of(d)][1]):
                raise ServiceError("That doesn't open.")
            d["open"] = not d.get("open")
            self._commit()
            return d["open"]

    def set_wall(self, did: int, on: bool):
        """Whether a drawn line blocks movement and sight (snapped lines do by default, free strokes don't)."""
        with self.lock:
            d = self._drawing(did)
            if d["type"] != "path":
                raise ServiceError("Only lines can be walls.")
            d["wall"] = bool(on)
            d.pop("cover", None)
            self._tidy_doors()
            self._commit()

    def set_cover(self, did: int, cover: str):
        """What a drawn line is (rooms.cover_of): 'wall' (a room's kind of wall: only a line along the grid), 'total' (blocks
        like a wall, drawn as a line), 'half' (half cover across it) or 'none' (a drawing). Doors in a wall that stops
        being one go."""
        if cover not in LINE_COVER:
            raise ServiceError("A line is a wall, full cover, half cover or no cover.")
        with self.lock:
            d = self._drawing(did)
            if d["type"] != "path":
                raise ServiceError("Only drawn lines have a cover level.")
            d.pop("wall", None)
            if cover == "wall":
                d.pop("cover", None)
                if not built(d):
                    raise ServiceError("Only a line along the grid can be a room's kind of wall; make it full cover instead.")
            else:
                d["cover"] = cover
            self._tidy_doors()
            self._commit()

    def rotate_symbol(self, did: int):
        with self.lock:
            d = self._drawing(did)
            if d["type"] != "symbol":
                raise ServiceError("Only symbols and props turn.")
            d["rot"] = (d.get("rot", 0) + 1) % 4
            self._commit()

    # ------------------------------------------------------------------ erasing
    def erase(self, did: int):
        """Erase a drawing. The last stairs to a floor erased: the floor goes too (floors.py; Ctrl+Z brings it back)."""
        with self.lock:
            self._drawing(did)
            linked = self._linked_floors()
            self.b["drawings"] = [d for d in self.b["drawings"] if d["id"] != did]
            self._tidy_doors()
            self._commit(self._drop_unlinked(linked))

    def drawing_at(self, x: float, y: float, radius: float = 0.45, locked: bool = False) -> Optional[dict]:
        """The topmost drawing under a point (tile coordinates): pictures over the tokens first, then the drawings and
        the pictures with them (a room's door before its walls), then the ground pictures. Locked pictures only with
        locked=True. A room is picked by its walls."""
        with self.lock:
            items = list(reversed(self.b.get("drawings", [])))
            items.sort(key=lambda d: d["type"] == "room")       # stable: a room under everything else drawn
            for layer in ("top", "map", "ground"):
                for d in items:
                    if d["type"] == "image":
                        if d.get("layer", "map") == layer and (locked or not d.get("locked")) and image_hit(d, x, y):
                            return dict(d)
                        continue
                    if layer != "map":
                        continue
                    n = _span(d)
                    if d["type"] == "symbol" and d["x"] <= x < d["x"] + n and d["y"] <= y < d["y"] + n:
                        return dict(d)
                    if d["type"] == "path" and shapes.near_path((x, y), d["pts"], d.get("closed"), radius):
                        return dict(d)
                    if _outline(d) and shapes.near_path((x, y), _outline(d), d["type"] == "room", min(radius, 0.3)):
                        return dict(d)
        return None

    def erase_near(self, x: float, y: float, radius: float = 0.45) -> int:
        """Erase everything under the eraser; returns how many drawings went."""
        with self.lock:
            keep, gone = [], 0
            items = self.b.get("drawings", [])
            linked = self._linked_floors()
            door = any(d["type"] == "door" and shapes.near_path((x, y), _outline(d), False, radius) for d in items)
            for d in items:
                n = _span(d)
                hit = (d["type"] == "symbol" and abs(d["x"] + n / 2 - x) <= n / 2 + radius and abs(d["y"] + n / 2 - y) <= n / 2 + radius) or \
                      (d["type"] == "path" and shapes.near_path((x, y), d["pts"], d.get("closed"), radius)) or \
                      (d["type"] == "door" and shapes.near_path((x, y), _outline(d), False, radius)) or \
                      (d["type"] == "room" and not door and shapes.near_path((x, y), _outline(d), True, radius))   # a door goes first
                if hit:
                    gone += 1
                else:
                    keep.append(d)
            if gone:
                self.b["drawings"] = keep
                self._tidy_doors()
                self._commit(self._drop_unlinked(linked))
            return gone

    def undo_drawing(self) -> bool:
        with self.lock:
            if not self.b.get("drawings"):
                return False
            linked = self._linked_floors()
            self.b["drawings"].pop()
            self._tidy_doors()
            self._commit(self._drop_unlinked(linked))
            return True

    def clear_drawings(self):
        with self.lock:
            linked = self._linked_floors()
            self.b["drawings"] = []
            dropped = self._drop_unlinked(linked)
            self._commit(f"The map was cleared. {dropped}." if dropped else "The map was cleared.")
