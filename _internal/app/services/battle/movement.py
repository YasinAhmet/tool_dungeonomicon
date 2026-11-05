"""Moving on the map: paths around walls and creatures, the movement a turn has left, opportunity attacks, zones
entered on the way, and forced movement (push, pull) that provokes nothing.

    walk(cid, x, y)              move along the cheapest path (a 'walk' resolution: it can stop for reactions); ending
                                 on stairs linked to another floor goes up or down them (floors.py)
    path_preview(cid, x, y)      {'path', 'cost', 'ok', 'why', 'threats'} for the screen (threats: opportunity attacks on the way)
"""
import heapq
import math
from typing import Optional

from ..common import ServiceError
from . import conditions as K
from . import geometry as G
from .constants import ACTIVE
from .floors import floor_at
from .resolve import DONE, NEXT


class MovementMixin:
    # ------------------------------------------------------------------ paths
    def _step_ok(self, c: dict, a: G.Tile, b: G.Tile, blocked: set, hostile_tiles: set) -> bool:
        m = self.b["map"]
        span = c.get("span") or 1
        ter = self._terrain()
        for i in range(span):
            for j in range(span):
                fa, fb = (a[0] + i, a[1] + j), (b[0] + i, b[1] + j)
                if not (0 <= fb[1] < m["h"]) or floor_at(m, fb[0]) is None:
                    return False
                if fb in blocked or fb in hostile_tiles:
                    return False
                if ter.wall_between(fa, fb) and not (self._fx(c, "incorporeal") and not self._fx(c, "solid")):     # (Yrden holds it solid)
                    return False
        return True

    def _occupied(self, c: dict):
        """(tiles of hostile creatures, tiles of everyone else) - hostiles block the way, nobody can end on an occupied tile."""
        hostile, other = set(), set()
        for o in self.b["combatants"]:
            if o is c or not o.get("pos") or self._is_out(o):
                continue
            tiles = G.footprint(o["pos"], o.get("span") or 1)
            if self._hostile(o, c) and abs((o.get("span") or 1) - (c.get("span") or 1)) < 2:
                hostile |= tiles
            else:
                other |= tiles
        return hostile, other

    def _find_path(self, c: dict, goal: G.Tile, budget: Optional[int] = None):
        """Cheapest path (list of top-left tiles, start included) and its cost in feet, or (None, reason). Of the paths
        that cost the same, the one that keeps closest to the straight line there: no dog-legs on an open floor."""
        if not c.get("pos"):
            return None, "Put the creature on the map first"
        start = tuple(c["pos"])
        goal = (int(goal[0]), int(goal[1]))
        if start == goal:
            return [list(start)], 0
        blocked = self._blocked_tiles()
        hostile, other = self._occupied(c)
        span = c.get("span") or 1
        dest = G.footprint(goal, span)
        if dest & (blocked | hostile | other):
            return None, "That space is taken"
        difficult = self._difficult_tiles(c)
        crawl = "Prone" in self._conds(c)
        lx, ly = goal[0] - start[0], goal[1] - start[1]
        ln = math.hypot(lx, ly)
        best = {start: (0, 0.0)}                                # tile: (feet, how far the way has strayed from the line)
        prev = {}
        heap = [(0, 0, 0.0, start)]
        limit = budget if budget is not None else 10 ** 6
        far = (10 ** 9, 0.0)
        while heap:
            f, cost, dev, cur = heapq.heappop(heap)
            if goal in best and f > best[goal][0]:              # every way as cheap as the best one has been looked at
                break
            if cur == goal or (cost, dev) > best.get(cur, far) or cost > limit:
                continue
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    if not dx and not dy:
                        continue
                    nxt = (cur[0] + dx, cur[1] + dy)
                    if not self._step_ok(c, cur, nxt, blocked, hostile):
                        continue
                    tiles = G.footprint(nxt, span)
                    step = 5 * (2 if tiles & (difficult | other) else 1) * (2 if crawl else 1)    # another creature's space: difficult
                    nc = cost + step
                    nd = dev + abs((nxt[0] - start[0]) * ly - (nxt[1] - start[1]) * lx) / ln
                    if nc > limit or (nc, nd) >= best.get(nxt, far):
                        continue
                    best[nxt] = (nc, nd)
                    prev[nxt] = cur
                    h = 5 * max(abs(goal[0] - nxt[0]), abs(goal[1] - nxt[1]))
                    heapq.heappush(heap, (nc + h, nc, nd, nxt))
        if goal not in best:
            return None, "No way there" if budget is None else "Not enough movement to get there"
        path = [goal]
        while path[-1] != start:
            path.append(prev[path[-1]])
        path.reverse()
        return [list(p) for p in path], best[goal][0]

    def _movement_left(self, c: dict) -> Optional[int]:
        if not self._economy_on():
            return None
        t = c.get("turn") or {}
        return int(t.get("move", 0))

    def _dragging(self, c: dict) -> list:
        """The creatures `c` holds in a grapple, or has swallowed (it drags them along when it moves)."""
        return [o for o in self.b["combatants"] if o is not c and o.get("pos") and self._alive(o)
                and any(c["id"] in ((e.get("mods") or {}).get("grappler"), (e.get("mods") or {}).get("swallowed_by")) for e in o.get("effects") or [])]

    def _drag_factor(self, c: dict) -> int:
        """Dragging a grappled creature halves the speed, unless it is two or more sizes smaller (PHB ch. 9)."""
        from .standard import SIZES
        me = SIZES.index(self._size_of(c))
        return 2 if any(SIZES.index(self._size_of(o)) > me - 2 for o in self._dragging(c)
                        if not any((e.get("mods") or {}).get("swallowed_by") == c["id"] for e in o.get("effects") or [])) else 1

    def path_preview(self, cid: int, x: int, y: int) -> dict:
        with self.lock:
            c = self._find(cid)
            left = self._movement_left(c)
            path, cost = self._find_path(c, (x, y))
            if path is None:
                return {"ok": False, "why": cost, "path": [], "cost": 0, "left": left}
            cost *= self._drag_factor(c)
            why = None
            if left is not None and cost > left:
                why = f"Needs {cost} ft, {left} ft left"
            if self._economy_on() and self.b.get("turn") != cid:
                why = f"It isn't {c['name']}'s turn"
            if not K.can_move(self._conds(c), self._exhaustion(c)) or self._speed(c) <= 0:
                why = f"{c['name']} can't move"
            for e in c.get("effects") or []:
                src = self._find_or_none(e.get("source_id"))
                if "Frightened" in (e.get("conditions") or []) and src and src.get("pos") and src is not c:
                    if G.distance_ft((x, y), c.get("span") or 1, src["pos"], src.get("span") or 1) < self._dist(c, src):
                        why = f"{c['name']} is too frightened of {src['name']} to move closer"
            why = self._subd_leash(c, x, y) or why              # Champion Challenge (subfeats_d.py)
            return {"ok": why is None, "why": why, "path": path, "cost": cost, "left": left, "threats": self._path_threats(c, path)}

    # ------------------------------------------------------------------ walking
    def walk(self, cid: int, x: int, y: int) -> str:
        """Move a creature along the cheapest path to (x, y): spends movement, provokes opportunity attacks, enters zones."""
        with self.lock:
            self._busy()
            c = self._find(cid)
            pv = self.path_preview(cid, x, y)
            if not pv["ok"]:
                raise ServiceError(pv["why"])
            path, cost = pv["path"], pv["cost"]
            if len(path) < 2:
                return ""
            R = self._new_r("walk", c, "move", path=path, i=0, cost=cost, summary_targets="")
            out = self._run_r(R)
            self._commit()
            return out

    def _step_walk(self, R: dict) -> str:
        c = self._find_or_none(R["actor"])
        if c is None or not self._alive(c) and c["kind"] != "pc":
            return DONE
        path = R["path"]
        if R["stage"] == "done":                                # what went off as the run ended (Headfirst Charge) has played out
            return DONE
        if R["stage"] == "start":
            R["stage"] = "step"
            R["from"] = list(path[0])
            R["was_prone"] = "Prone" in self._conds(c)
        if R["stage"] == "step":
            if R["i"] >= len(path) - 1 or self._hp_of(c) <= 0 or K.incapacitated(self._conds(c)) or self._speed(c) <= 0 \
                    or R.get("stopped") or self._walk_cut(c, R) or not K.can_move(self._conds(c), self._exhaustion(c)):    # webbed or grabbed on the way
                if R["i"] and R["i"] < len(path) - 1 and not R.get("displaced"):
                    self._back_to_free_tile(c, path[:R["i"] + 1])
                if R["i"]:
                    at = self._tile_label(path[R["i"]] if R.get("displaced") else c["pos"])    # pushed away: where the walk was cut short
                    self._line(R, f"{c['name']} moves {5 * R['i']} ft to {at}", f"to {at}")
                    self._note_run(c, R.get("from"), c["pos"], path[:R["i"] + 1])     # a charge looks at how far it came this turn
                if R["i"] == len(path) - 1 and not R.get("stopped") and self._hp_of(c) > 0:
                    self._take_stairs(c, R)                       # walked onto stairs to another floor: up or down them
                ends = self._run_end_strikes(c) if R["i"] and self._alive(c) else []
                if ends:                                          # traits.py: Headfirst Charge slams whoever the run ended at
                    R["stage"] = "done"
                    self._stack().extend(reversed(ends))
                    return NEXT
                return DONE
            nxt = path[R["i"] + 1]
            entry = []
            t = c.get("turn") or {}
            here = G.box(c["pos"], c.get("span") or 1)
            there = G.box(nxt, c.get("span") or 1)
            threats = self._oa_threats(c, here, there, R.get("no_oa") or int(t.get("no_oa_ft") or 0) > 0)   # Tempestuous Magic: the first 10 ft
            for o in (self.b["combatants"] if self.b["status"] == ACTIVE else ()):
                if o is c or not o.get("pos") or not self._hostile(o, c) or not self._can_act(o) or not (self._may_react(o) or self._subc_vigil_ok(o)):
                    continue
                reach = self._reach(o)
                ob = G.box(o["pos"], o.get("span") or 1)
                if self._feat(o, "polearm_master") and 5 * G.gap(ob, here) > reach >= 5 * G.gap(ob, there) and self._sees(o, c):
                    w = self._melee_weapon_of(o)
                    if w and any(p in (w.get("weapon_name") or w.get("name") or "").lower() for p in ("glaive", "halberd", "quarterstaff", "spear", "pike")):
                        entry.append(o["id"])
                if o["id"] not in entry and self._brace_ok(o) and 5 * G.gap(ob, here) > reach >= 5 * G.gap(ob, there) and self._sees(o, c):
                    entry.append(o["id"])                       # Brace (a maneuver): an attack on a creature coming into reach
                if o["id"] not in entry and 5 * G.gap(ob, here) > 5 >= 5 * G.gap(ob, there) and self._sees(o, c) and self._wonder_item(o, "item_repel")[1]:
                    entry.append(o["id"])                       # a Dissuader's Repel: a creature comes within 5 ft (itemmore.py)
                er = self._entry_reaction(o) if o["id"] not in entry and not self._sheet(o) else None
                if er and 5 * G.gap(ob, here) > (er[1] or reach) >= 5 * G.gap(ob, there) and self._sees(o, c):
                    entry.append(o["id"])                       # a boneclaw's Deadly Reach, an ogre's Block the Path
            R["next"] = nxt
            R["threats"], R["entry"] = threats, entry
            R["echo_oa"] = self._echo_threats(c, here, there) if self.b["status"] == ACTIVE and not (
                t.get("disengaged") or self._fx(c, "no_opportunity") or R.get("no_oa") or int(t.get("no_oa_ft") or 0) > 0) else []   # an Echo Knight's echo
            R["stage"] = "leave" if threats or R["echo_oa"] else "enter" if entry else "move"
            return NEXT
        if R["stage"] == "leave":
            return self._window(R, "leave", "enter" if R.get("entry") else "move", mover=c["id"], threats=R.get("threats") or [])
        if R["stage"] == "enter":
            return self._window(R, "enter", "move", mover=c["id"], threats=R.get("entry") or [])
        if R["stage"] == "move":
            if self._hp_of(c) <= 0 or self._fxs(c, "speed_set") and self._speed(c) <= 0 or self._walk_cut(c, R):
                R["stage"] = "step"
                R["stopped"] = True
                return NEXT
            for e, _v in self._fxs(c, "stop_move"):              # stepped on caltrops: this move ends here
                e["mods"].pop("stop_move", None)
                R["stage"] = "step"
                R["stopped"] = True
                return NEXT
            nxt = R["next"]
            before = G.footprint(c["pos"], c.get("span") or 1)
            span = c.get("span") or 1
            after = G.footprint(nxt, span)
            dragged = self._dragging(c)
            crowd = self._occupied(c)[1] - set(map(tuple, G.footprint(c["pos"], span))) - {t for o in dragged for t in map(tuple, self._footprint(o, *o["pos"]))}
            step = 5 * (2 if after & (self._difficult_tiles(c) | crowd) else 1) * (2 if "Prone" in self._conds(c) else 1) * self._drag_factor(c)
            t = c.get("turn")
            if t is not None and self._economy_on() and not R.get("free_move"):    # a legendary Move isn't its own turn's movement
                t["move"] = max(0, t.get("move", 0) - step)
                t["no_oa_ft"] = max(0, int(t.get("no_oa_ft") or 0) - step)
            old = list(c["pos"])
            c["pos"] = list(nxt)
            self._vfx("step", id=c["id"], to=list(nxt))
            self._follow_zones(c)
            R["i"] += 1
            for o in dragged:                                   # the grappled creature comes along into the space left behind
                if self._dist(o, c) > 5:
                    spot = old if (o.get("span") or 1) == 1 else self._free_near(o, *old)
                    if spot:
                        was = G.footprint(o["pos"], o.get("span") or 1)
                        o["pos"] = list(spot)
                        for S in reversed(self._zone_entered(o, set(was), G.footprint(spot, o.get("span") or 1), R)):
                            self._stack().append(S)
                        self._vfx("step", id=o["id"], to=list(spot), push=True)
                        self._follow_zones(o)
                        if not R.get("dragged"):
                            R["dragged"] = True
                            self._line(R, f"{c['name']} drags {o['name']} along")
            for e, v in self._fxs(c, "on_move"):
                if e in (c.get("effects") or []):
                    dice, dtype = v
                    self._line(R, f"{e['name']} bursts: " + self._deal(c, [[dice, dtype]], label=e["name"]), self._short)
                    self._effect_off(c, e, "moved")
            for S in reversed(self._zone_entered(c, set(before), set(after), R)):
                self._stack().append(S)
            for S in reversed(self._trail_strikes(c)):          # spells.py: Ashardalon's Stride burns those it passes
                self._stack().append(S)
            for S in reversed(self._space_entry_strikes(c, set(after))):     # traits.py: Duke Zalto's Tackle
                self._stack().append(S)
            R["stage"] = "step"
            return NEXT
        return DONE

    def _walk_cut(self, c: dict, R: dict) -> bool:
        """A walk ends when something on the way knocks the walker prone or moves it off the path (a shove, a smite's push)."""
        if not c.get("pos") or list(c["pos"]) != list(R["path"][R["i"]]):
            R["displaced"] = True
            return True
        return "Prone" in self._conds(c) and not R.get("was_prone")

    def _oa_threats(self, c: dict, here, there, no_oa=False) -> list:
        """The enemies whose reach `c` leaves stepping from box `here` to box `there` and who may take an opportunity attack."""
        t = c.get("turn") or {}
        mobile = set(t.get("melee_targets") or []) if self._feat(c, "mobile") or self._fancy_footwork(c) else set()
        out = []
        for o in (self.b["combatants"] if self.b["status"] == ACTIVE else ()):    # no opportunity attacks out of combat
            if o is c or not o.get("pos") or not self._hostile(o, c) or not self._can_act(o) or not (self._may_react(o) or self._subc_vigil_ok(o)):
                continue                                        # (Vigilant Defender: the cavalier's special reaction, subfeats_c.py)
            reach = self._reach(o)
            ob = G.box(o["pos"], o.get("span") or 1)
            if 5 * G.gap(ob, here) <= reach < 5 * G.gap(ob, there) and self._sees(o, c):
                free = (t.get("disengaged") and not self._feat(o, "sentinel")) or self._fx(c, "no_opportunity") or o["id"] in mobile or no_oa
                if not free:
                    out.append(o["id"])
        return out

    def _path_threats(self, c: dict, path: list) -> list:
        """For the preview: [{'id', 'name', 'at'}] - the enemies the mover can see that would get an opportunity attack on
        this path, each once (one reaction), at the tile it is leaving their reach from."""
        span = c.get("span") or 1
        free_ft = int((c.get("turn") or {}).get("no_oa_ft") or 0)
        out, seen = [], set()
        for a, b in zip(path, path[1:]):
            for oid in self._oa_threats(c, G.box(a, span), G.box(b, span), free_ft > 0):
                o = self._find_or_none(oid)
                if oid not in seen and o and self._sees(c, o):
                    seen.add(oid)
                    out.append({"id": oid, "name": o["name"], "at": list(a)})
            free_ft -= 5
        return out

    def _back_to_free_tile(self, c: dict, walked: list):
        """A walk cut short on a tile it was only passing through (an ally's): back to the last tile that is free."""
        if c.get("tiny"):
            return
        span = c.get("span") or 1
        others = set()
        for o in self.b["combatants"]:
            if o is not c and o.get("pos") and not o.get("tiny") and (self._hp_of(o) > 0 or o["kind"] == "pc"):
                others |= set(map(tuple, self._footprint(o, *o["pos"])))
        for p in reversed(walked):
            if not set(map(tuple, G.footprint(p, span))) & others:
                if list(p) != list(c["pos"]):
                    c["pos"] = list(p)
                    self._follow_zones(c)
                return

    # ------------------------------------------------------------------ forced movement
    def _push(self, tgt: dict, src: dict, feet: int, R: Optional[dict] = None):
        """Push `tgt` straight away from `src` (negative feet: pull towards it) until something is in the way."""
        if not tgt.get("pos") or not src.get("pos") or feet == 0:
            return
        feet = self._forced_move_cut(tgt, feet)                 # Dwarven Plate: a reaction takes up to 10 ft off it (spellitems.py)
        if feet == 0:
            return
        if (self._monster(tgt) or {}).get("size") in ("Huge", "Gargantuan") and abs(feet) <= 10:
            pass
        sx, sy = G.centre(src["pos"], src.get("span") or 1)
        tx, ty = G.centre(tgt["pos"], tgt.get("span") or 1)
        dx, dy = tx - sx, ty - sy
        if feet < 0:
            dx, dy = -dx, -dy
        m = max(abs(dx), abs(dy)) or 1
        ux = 0 if abs(dx) / m < .4 else (1 if dx > 0 else -1)
        uy = 0 if abs(dy) / m < .4 else (1 if dy > 0 else -1)
        if not ux and not uy:
            ux = 1
        batter = feet > 0 and src.get("kind") == "pc" and self._dist(src, tgt) <= self._reach(src)    # a Battering Shield's charge (itemmore.py)
        blocked = self._blocked_tiles()
        hostile, other = self._occupied(tgt)
        moved = 0
        strikes = []
        for _ in range(abs(feet) // 5):
            nxt = (tgt["pos"][0] + ux, tgt["pos"][1] + uy)
            if feet < 0 and G.distance_ft(nxt, tgt.get("span") or 1, src["pos"], src.get("span") or 1) < 5:
                break
            if not self._step_ok(tgt, tuple(tgt["pos"]), nxt, blocked, hostile | other):
                break
            if G.footprint(nxt, tgt.get("span") or 1) & other:
                break
            was = G.footprint(tgt["pos"], tgt.get("span") or 1)
            tgt["pos"] = list(nxt)
            self._vfx("step", id=tgt["id"], to=list(nxt), push=True)
            moved += 5
            strikes += self._zone_entered(tgt, set(was), G.footprint(nxt, tgt.get("span") or 1), R)   # spikes on every step
        if moved:
            self._follow_zones(tgt)
            line = f"{tgt['name']} is {'pushed' if feet > 0 else 'pulled'} {moved} ft"
            if R is not None:
                self._line(R, line, line)
                R.setdefault("follow", []).extend(strikes)
            else:
                self._say(line)
                for S in strikes:                                   # a shove: the zones it lands in bite now
                    self._run_r(S)
        if batter and moved >= 5:
            self._battering_push(tgt, src, R)

    def teleport(self, cid: int, x: int, y: int):
        """Put a creature on a tile without moving through the space between (no opportunity attacks)."""
        with self.lock:
            c = self._find(cid)
            if not self._tile_ok(c, int(x), int(y)):
                raise ServiceError("That tile is taken or off the map.")
            self._vfx("blink", id=c["id"], at=c.get("pos"), to=[int(x), int(y)])
            c["pos"] = [int(x), int(y)]
            self._follow_zones(c)
            self._commit(f"{c['name']} teleports")
