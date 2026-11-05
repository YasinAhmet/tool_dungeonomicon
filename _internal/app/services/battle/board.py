"""The battle map: placing tokens, footprints by creature size, map size.

Tiny creatures (`tiny`: Tiny monsters, conjured weapons) don't need a tile of their own: up to four share one, and
`at` [x, y] (floats, tile units) is the exact point they stand on - a tile's corner, anywhere. `pos` stays the tile under
that point, which is all the rules look at; an `at` outside `pos` is stale (the creature moved since) and is ignored.
"""
import copy
from typing import List, Optional

from ..common import ServiceError
from . import floors as F
from .constants import ACTIVE, MAP_MAX, MAP_MIN, faction_of


class BoardMixin:
    # ------------------------------------------------------------------ battle map
    def _footprint(self, c: dict, x: int, y: int):
        n = max(1, int(c.get("span") or 1))
        return {(x + i, y + j) for i in range(n) for j in range(n)}

    def _tile_ok(self, c: dict, x: int, y: int) -> bool:
        m = self.b["map"]
        cells = self._footprint(c, x, y)
        if any(not (0 <= cy < m["h"]) or F.floor_at(m, cx) is None for cx, cy in cells):     # (not in the gap between floors)
            return False
        sharing = 0
        for o in self.b["combatants"]:
            if o is not c and o.get("pos") and cells & self._footprint(o, *o["pos"]):
                if not (c.get("tiny") and o.get("tiny")):
                    return False
                sharing += 1                                    # Tiny creatures: four to a 5-foot square
        return sharing < 4

    def _free_near(self, c: dict, x: int, y: int) -> Optional[List[int]]:
        """The free tile closest to (x, y), searching outwards on its floor."""
        m = self.b["map"]
        a = F.left(m, F.nearest(m, x))
        for r in range(0, max(F.layout(m)[0], m["h"])):
            ring = [(x + dx, y + dy) for dx in range(-r, r + 1) for dy in range(-r, r + 1)
                    if max(abs(dx), abs(dy)) == r and a <= x + dx < a + F.layout(m)[0]]
            for cx, cy in sorted(ring, key=lambda t: (abs(t[0] - x) + abs(t[1] - y), t[1], t[0])):
                if self._tile_ok(c, cx, cy):
                    return [cx, cy]
        return None

    def _arrive(self, ids: List[int], roll: bool, pos: Optional[List[int]], place: Optional[bool] = None):
        """Newly added combatants: roll their initiative and/or drop them on the map - near `pos`, or (no `pos`) on
        free tiles of their side when `place` is True, or None and someone else already stands on the map. Mid-battle
        they get their turn budget at once."""
        new = [c for c in self.b["combatants"] if c["id"] in ids]
        if self.b["status"] == ACTIVE:
            for c in new:
                self._fresh_turn(c)
        if roll:
            for c in new:
                mate = next((o for o in self.b["combatants"] if o is not c and c["monster"] and o["monster"] == c["monster"]
                             and o["init"] is not None and o["id"] not in ids), None)
                if mate:
                    c["init"] = mate["init"]
                elif c["init"] is None:
                    self._roll_one(c)
            self._sort()
        if pos:
            for c in new:
                spot = self._free_near(c, int(pos[0]), int(pos[1]))
                if spot:
                    c["pos"] = spot
        elif place or (place is None and any(o.get("pos") for o in self.b["combatants"] if o["id"] not in ids)):
            self._auto_place(new)

    def _auto_place(self, rows: List[dict]) -> int:
        """Put these combatants on free tiles of the main floor: the party and its allies on the west side, enemies on
        the east, filling columns from the middle row outwards (a tile's margin from the edge when the map is big enough)."""
        m = self.b["map"]
        a = F.left(m, 0)
        m = dict(m, w=F.layout(m)[0])                        # the main floor's own width; its columns start at a
        try:
            blocked = set(self._blocked_tiles())
        except Exception:  # noqa: BLE001 - broken terrain must not stop placing tokens
            blocked = set()
        placed = 0
        for c in rows:
            if c.get("pos"):
                continue
            s = max(1, int(c.get("span") or 1))
            if s > m["w"] or s > m["h"]:
                continue
            margin = 1 if m["w"] >= 10 and m["w"] - s >= 2 else 0
            xs = list(range(margin, m["w"] - s + 1)) + list(range(0, margin))
            if faction_of(c) != 1:                          # the players' side starts west, everyone else east
                xs = [m["w"] - s - x for x in xs]
            mid = (m["h"] - s) // 2
            ys = sorted(range(0, m["h"] - s + 1), key=lambda y: (abs(y - mid), y))
            spot = next(([a + x, y] for x in xs for y in ys
                         if self._tile_ok(c, a + x, y) and not (self._footprint(c, a + x, y) & blocked)), None)
            if spot:
                c["pos"] = spot
                placed += 1
        return placed

    def place_unplaced(self) -> int:
        """Put every combatant that isn't on the map on a free tile (party west, enemies east). Returns how many."""
        with self.lock:
            rows = [c for c in self.b["combatants"] if not c.get("pos")]
            n = self._auto_place(rows)
            if n:
                self._commit(f"Placed {n} on the map" if n != 1 else f"Placed {next(c['name'] for c in rows if c.get('pos'))} on the map")
            return n

    def place(self, cid: int, x, y, free: bool = False):
        """Put a combatant on a map tile (its top-left tile for big creatures). `free`: (x, y) is a point where a Tiny
        creature stands - (3.0, 4.0) the corner between four tiles, (3.5, 4.5) the middle of tile (3, 4)."""
        with self.lock:
            c = self._find(cid)
            fx, fy = float(x), float(y)
            free = bool(free and c.get("tiny"))
            tx, ty = int(fx), int(fy)
            if free:
                m = self.b["map"]
                band = F.band(m, fx) or (0, m["w"] - 1)
                fx, fy = max(float(band[0]), min(band[1] + 0.99, fx)), max(0.0, min(m["h"] - 0.01, fy))
                tx, ty = int(fx), min(int(fy), m["h"] - 1)
            if not self._tile_ok(c, tx, ty):
                raise ServiceError("That tile is taken or off the map.")
            c["pos"] = [tx, ty]
            c["at"] = [round(fx, 3), round(fy, 3)] if free else None
            self._follow_zones(c)                                # put, not walked: no movement, reactions or zone triggers
            self._commit()

    def unplace(self, cid: int):
        with self.lock:
            c = self._find(cid)
            c["pos"] = None
            self._commit()

    def set_map_size(self, width: int, height: int):
        with self.lock:
            w, hgt = int(width), int(height)
            if not (MAP_MIN <= w <= MAP_MAX and MAP_MIN <= hgt <= MAP_MAX):
                raise ServiceError(f"The map must be between {MAP_MIN} and {MAP_MAX} tiles on each side.")
            m = self.b["map"]
            if F.many(m):                                         # every floor that size: what's on them moves along
                _fw, lo, hi = F.layout(m)
                self._relayout(F.shape(dict(m, h=hgt), w, lo, hi), {f: f for f in range(lo, hi + 1)})
            else:
                for c in self.b["combatants"]:                    # anyone left outside leaves the map
                    if c.get("pos") and not all(cx < w and cy < hgt for cx, cy in self._footprint(c, *c["pos"])):
                        c["pos"] = None
                self.b["map"] = dict(m, w=w, h=hgt)
            self._commit()

    def remove(self, cid: int):
        with self.lock:
            c = self._find(cid)
            if c.get("concentrating"):                      # its spells end with it (summons, Hold Person...)
                self._drop_conc(c, "left the battle")
            self._take_out(c)
            self._commit(f"{c['name']} left the battle")

    def _take_out(self, c: dict):
        """Take a combatant off the battle (undo_remove can bring it back); the turn passes on if it was its turn."""
        cid = c["id"]
        rows = self.b["combatants"]
        index = rows.index(c)
        self._removed = self._removed[-49:] + [(self.b, copy.deepcopy(c), index, self.b.get("turn"), self.b.get("round"))]
        rows.remove(c)
        for o in rows:                                       # a Spiritual Weapon token taken away: its attack goes too
            if any(a.get("token") == cid for a in o.get("spell_actions") or []):
                o["spell_actions"] = [a for a in o["spell_actions"] if a.get("token") != cid]
        if cid in (self.b.get("targets") or []):
            self.b["targets"] = [x for x in self.b["targets"] if x != cid]
            self.b["target"] = self.b["targets"][0] if self.b["targets"] else None
        if self.b["status"] == ACTIVE and self.b["turn"] == cid:
            if not rows:
                self.b["turn"] = None
            else:
                if index >= len(rows):
                    index, self.b["round"] = 0, self.b["round"] + 1
                self.b["turn"] = rows[index]["id"]
                self._skip_defeated()

    def undo_remove(self):
        """Bring back the last combatant taken out with remove(), where it was in the order."""
        with self.lock:
            while self._removed and self._removed[-1][0] is not self.b:   # removals from an earlier battle can't come back
                self._removed.pop()
            if not self._removed:
                last = self.undo_label() or ""
                if last.endswith(" left the battle"):                     # the battle was put back since: undo the step
                    self.undo()
                    return last[:-len(" left the battle")]
                raise ServiceError("Nothing to undo.")
            _b, c, index, turn, rnd = self._removed.pop()
            rows = self.b["combatants"]
            if any(x["id"] == c["id"] for x in rows):
                raise ServiceError("Nothing to undo.")
            if c.get("pos") and not self._tile_ok(c, *c["pos"]):
                c["pos"] = None
            rows.insert(min(index, len(rows)), c)
            if turn == c["id"] and self.b["status"] == ACTIVE:
                self.b["turn"], self.b["round"] = turn, rnd
            self._commit(f"{c['name']} is back in the battle")
            return c["name"]

    def clear_enemies(self):
        with self.lock:
            if self.b["status"] == ACTIVE:
                raise ServiceError("End the battle first.")
            self.b["combatants"] = [c for c in self.b["combatants"] if c["kind"] == "pc"]
            self._commit("Cleared all enemies")
