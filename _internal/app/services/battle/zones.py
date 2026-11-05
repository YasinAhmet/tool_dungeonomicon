"""Lasting areas on the map: Spirit Guardians, Moonbeam, Web, Cloud of Daggers, Darkness, Fog Cloud, Spike Growth, walls...

A zone is kept in b['zones'] with its tiles, its owner, how long it lasts and what it does:
    enter / start / end       trigger when a creature enters it (first time on a turn), starts or ends its turn in it
                              (only its own tiles, what the maps draw: nothing strikes the tiles around it)
    on_cast                   creatures in it when it appears are affected at once
    save, half, parts, conds, cond_rounds, prone, push, pull, heal, exhaustion, start_auto, end_save
    fail_mods / fail_until / on_save   what a failed save puts on the creature (until its next turn ends) / a successful one does (Grave Ground, Dirge)
    sweep                     an aura that strikes whoever it newly covers when its owner moves (Dirge, Cacophonic Shield)
    drift (feet)              moves away from its owner at the start of each of the owner's turns (Doomtide); ally_boost: +speed for its friends inside
    no_heal / spell_save / duel_ground   no healing inside (Dirge); a save to cast inside or the spell dissipates (Spellfire Storm); a duelling ring
    affects                   'all' (default), 'enemies' or 'allies' of its owner
    difficult, obscure ('light'|'heavy'), darkness, light ('bright'|'dim'), silence, opaque, blocks
    follow                    moves with its owner (auras); move {'cost', 'feet', 'ram'}: the owner can move it
    per_5ft                   damage for every 5 feet moved inside (Spike Growth); cap: total damage it can deal
    inside / inside_allies    mods a creature it affects / its owner and the owner's friends have while inside (Yrden: no reactions;
                              Slow Time: ranged attacks at disadvantage); solidify: an incorporeal foe inside is solid (Yrden) - _zone_mods
    sees_owner                only creatures that can see its owner (Helm of Awe); on_save {'mods': {'zone_immune': True}}: a success
                              makes the creature immune to this casting
    trap {radius, save, half, parts, fail_mods, fail_until}   the first creature other than its owner to come onto its tiles sets off
                              a burst around its point, then it is gone (Fire Rune)
Sight, movement and the strike pipeline read these; this part creates, moves, triggers and ends them.
"""
from typing import List, Optional, Tuple

from ..common import ServiceError
from . import geometry as G
from .resolve import roll

# how a lasting area looks on the maps: (family, kind within it); the families are in docs/vfx-catalog.md (5.5)
FAMILIES = {
    "wall of fire": ("fire", "wall"), "create bonfire": ("fire", ""), "flaming sphere": ("fire", "sphere"),
    "fog cloud": ("cloud", "fog"), "stinking cloud": ("cloud", "poison"), "cloudkill": ("cloud", "poison"),
    "incendiary cloud": ("cloud", "smoke"), "sleet storm": ("cloud", "sleet"),
    "darkness": ("dark", ""), "hunger of hadar": ("dark", ""),
    "light": ("light", ""), "daylight": ("light", ""), "continual flame": ("light", ""), "dancing lights": ("light", ""),
    "web": ("tangle", "web"), "entangle": ("tangle", "vine"), "plant growth": ("tangle", "vine"), "spike growth": ("tangle", "thorn"),
    "wall of thorns": ("tangle", "thorn"), "grease": ("tangle", "grease"), "mold earth": ("tangle", "earth"),
    "cloud of daggers": ("whirl", "daggers"), "blade barrier": ("whirl", "daggers"), "insect plague": ("whirl", "insects"),
    "spirit guardians": ("whirl", "spirits"), "dust devil": ("whirl", "wind"), "storm sphere": ("whirl", "storm"),
    "maelstrom": ("whirl", "storm"),
    "wall of stone": ("wall", "stone"), "wall of ice": ("wall", "ice"), "wall of force": ("wall", "force"), "forcecage": ("wall", "force"),
    "wind wall": ("wall", "wind"), "wall of water": ("wall", "water"), "wall of sand": ("wall", "sand"),
    "moonbeam": ("beam", "moon"), "sickening radiance": ("beam", "sick"), "dawn": ("beam", "sun"), "wall of light": ("beam", "sun"),
    "healing spirit": ("help", ""), "circle of power": ("help", ""), "guardian of faith": ("help", ""),
    "globe of invulnerability": ("dome", ""), "antilife shell": ("dome", ""), "antimagic field": ("dome", ""),
    "silence": ("silence", ""), "minor illusion": ("illusion", ""), "silent image": ("illusion", ""), "major image": ("illusion", ""),
    "cordon of arrows": ("arrows", ""),
    "yrden": ("help", ""), "helm of awe": ("dome", ""), "slow time": ("dome", ""),      # Legends Reforged
}


def zone_family(name: str, z: dict) -> Tuple[str, str]:
    """(family, kind) of a lasting area: by its spell, else by what it does."""
    hit = FAMILIES.get((name or "").lower())
    if hit:
        return hit
    dtype = next((str(t).lower() for _d, t in z.get("parts") or [] if t), "")
    return ("dark", "") if z.get("darkness") else ("cloud", "fog") if z.get("obscure") else ("wall", "stone") if z.get("blocks") or z.get("opaque") \
        else ("light", "") if z.get("light") and not z.get("parts") else ("fire", "") if dtype == "fire" else ("help", "") if z.get("heal") \
        else ("tangle", "web") if z.get("difficult") else ("whirl", "") if z.get("parts") else ("area", "")


class ZonesMixin:
    def _zones(self) -> list:
        return self.b.setdefault("zones", [])

    def _add_zone(self, owner: dict, name: str, tiles, zdef: dict, *, rounds=None, conc=None, dc: int = 13, area=None, point=None) -> dict:
        zid = self.b.get("zone_next", 1)
        self.b["zone_next"] = zid + 1
        z = dict(zdef)
        z.update({"id": zid, "name": name, "owner": owner["id"] if owner else None, "tiles": [list(t) for t in tiles], "rounds": rounds,
                  "conc_by": conc, "dc": dc, "area": area, "point": point, "hits": {}, "dealt": 0})
        z["family"], z["family_kind"] = zone_family(name, z)
        if z.get("inside") or z.get("inside_allies") or z.get("solidify"):
            self.b["zone_fx"] = True                            # effect lookups start looking at the zones a creature stands in
        self._zones().append(z)
        self._zone_vfx("on", z)
        return z

    def _zone_vfx(self, op: str, z: dict, **more):
        """A lasting area appearing ('on'), striking someone ('hit', ids), ending ('off') or moved ('move', d): the maps play it."""
        dtype = next((str(t).lower() for _d, t in z.get("parts") or [] if t), "")
        self._vfx("zone", op=op, zid=z["id"], tiles=[list(t) for t in z["tiles"]] if op in ("on", "off") else None,
                  fam=z.get("family") or "area", sub=z.get("family_kind") or "", dtype=dtype, hidden=bool(z.get("hidden")), **more)

    def _bead_grow(self, c: dict):
        """Delayed Blast Fireball: at the end of its caster's turn, still concentrating, the bead's damage grows by 1d6."""
        if not c.get("concentrating"):
            return
        for z in self._zones():
            if z.get("bead") and z.get("conc_by") == c["id"] and z.get("parts"):
                n, sep, rest = str(z["parts"][0][0]).partition("d")
                if sep and n.isdigit():
                    z["parts"][0][0] = f"{int(n) + 1}d{rest}"
                    self._say(f"{z['name']} glows brighter: {z['parts'][0][0]} fire damage when it erupts")

    def _bead_boom(self, z: dict, why: str):
        """Delayed Blast Fireball erupts (its caster's concentration ends, or its minute is up): one damage roll, a Dexterity
        save for every creature in the 20-foot sphere, half on a success."""
        if z not in self._zones():
            return
        from . import geometry as G
        owner = self._find_or_none(z.get("owner"))
        tiles = {tuple(t) for t in z["tiles"]}
        self._zone_off(z, why)
        ids = [c["id"] for c in G.creatures_in(tiles, self.b["combatants"]) if not self._is_out(c)]
        parts = [list(p) for p in z.get("parts") or []]
        self._area_vfx(owner, tiles, parts, "burst", z.get("point"))
        R = self._new_r("seq", owner, z["name"], magical=True)
        rolled = self._roll_parts(parts)
        self._line(R, f"{z['name']} erupts: {sum(n for n, _t in rolled)} fire damage on a failed save", "erupts")
        for i in ids:
            tgt = self._find_or_none(i)
            if tgt is not None and self._alive(tgt):
                self._apply_save(R, owner, tgt, {"ab": "dex", "dc": z.get("dc", 13), "half": True, "spell": True}, rolled=[list(x) for x in rolled])

    def _zone_off(self, z: dict, why: str):
        if z in self._zones():
            self._zone_vfx("off", z)
            self._zones().remove(z)
            self._say(f"{z['name']} ends ({why})")
        for c in self.b["combatants"]:
            c["spell_actions"] = [a for a in c.get("spell_actions") or [] if a.get("zone") != z["id"]]

    def end_zone(self, zone_id: int):
        """The DM takes a lasting area off the map."""
        with self.lock:
            self._zone_off(self._zone(zone_id), "removed")
            self._commit()

    def _zone(self, zone_id: int) -> dict:
        z = next((x for x in self._zones() if x["id"] == int(zone_id)), None)
        if not z:
            raise ServiceError("That area is already gone.")
        return z

    def zone_at(self, x: float, y: float) -> Optional[dict]:
        """The newest lasting area on the tile under a point (tile coordinates), for the DM's clicks."""
        t = [int(x // 1), int(y // 1)]
        with self.lock:
            return next((dict(z) for z in reversed(self._zones()) if t in z["tiles"]), None)

    def edit_zone(self, zone_id: int, *, name: Optional[str] = None, note: Optional[str] = None, rounds=..., hidden: Optional[bool] = None):
        """The DM renames a lasting area, writes a note on it (what the illusion shows...), sets the rounds it has left
        (None: until taken off) or hides it from the players."""
        with self.lock:
            z = self._zone(zone_id)
            if name is not None:
                if not name.strip():
                    raise ServiceError("Give it a name.")
                z["name"] = name.strip()[:60]
            if note is not None:
                z["note"] = note.strip()[:500]
            if rounds is not ...:
                z["rounds"] = None if rounds is None or int(rounds) <= 0 else min(int(rounds), 10000)
            if hidden is not None:
                z["hidden"] = bool(hidden)
            self._commit()

    def shift_zone(self, zone_id: int, dx: int, dy: int):
        """The DM drags a lasting area by whole tiles (kept on the map)."""
        with self.lock:
            z = self._zone(zone_id)
            m = self.b["map"]
            xs, ys = [t[0] for t in z["tiles"]] or [0], [t[1] for t in z["tiles"]] or [0]
            dx = max(-min(xs), min(m["w"] - 1 - max(xs), int(dx)))
            dy = max(-min(ys), min(m["h"] - 1 - max(ys), int(dy)))
            if not dx and not dy:
                return
            z["tiles"] = [[t[0] + dx, t[1] + dy] for t in z["tiles"]]
            if z.get("point"):
                z["point"] = [z["point"][0] + dx, z["point"][1] + dy]
            self._zone_vfx("move", z, d=[dx, dy])
            self._commit()

    def _zone_affects(self, z: dict, c: dict) -> bool:
        owner = self._find_or_none(z.get("owner"))
        if ((z.get("on_save") or {}).get("mods") or {}).get("zone_immune") and any(
                (e.get("mods") or {}).get("zone_immune") and e["name"] == z["name"] and e.get("source_id") == z.get("owner") for e in c.get("effects") or []):
            return False                                        # Helm of Awe: it saved once, it's immune to this casting
        if z.get("sees_owner") and owner is not None and c is not owner and c.get("pos") and owner.get("pos") and not self._sees(c, owner):
            return False
        who = z.get("affects", "all")
        if who == "all" or owner is None:
            return True
        if who == "enemies":
            return self._hostile(owner, c)
        return not self._hostile(owner, c)

    def _zones_at(self, c: dict) -> List[dict]:
        if not c.get("pos"):
            return []
        mine = G.footprint(c["pos"], c.get("span") or 1)
        return [z for z in self._zones() if mine & {tuple(t) for t in z["tiles"]}]

    def _antimagic_blocks(self, att: Optional[dict], R: dict) -> bool:
        """Antimagic Field: a spell cast from inside the sphere, aimed at a point in it, or whose every target stands in it, is suppressed
        (the slot is spent)."""
        tiles = set()
        for z in self._zones():
            if z.get("antimagic"):
                tiles |= {tuple(t) for t in z["tiles"]}
                own = self._find_or_none(z.get("owner")) if z.get("follow") else None
                if own is not None and own.get("pos"):
                    tiles |= set(G.footprint(own["pos"], own.get("span") or 1))      # the emanation leaves out the caster's own tiles
        if not tiles or att is None:
            return False
        if att.get("pos") and G.footprint(att["pos"], att.get("span") or 1) & tiles:
            return True
        pt = R.get("point")
        if pt is not None and (int(pt[0]), int(pt[1])) in tiles:
            return True
        who = [self._find_or_none(i) for i in dict.fromkeys(R.get("targets") or []) if i != att["id"]]
        return bool(who) and all(o is not None and o.get("pos") and G.footprint(o["pos"], o.get("span") or 1) & tiles for o in who)

    def _follow_zones(self, c: dict):
        """Auras move with their owner. A `sweep` aura (Dirge, Cacophonic Shield...) strikes the creatures it newly covers, once a turn each."""
        for z in self._zones():
            if z.get("follow") and z.get("owner") == c["id"] and c.get("pos") and z.get("area"):
                old = {tuple(t) for t in z["tiles"]}
                tiles = G.area_for(z["area"], c["pos"], c.get("span") or 1, None, *self._bounds())
                z["tiles"] = [list(t) for t in sorted(tiles)]
                if z.get("sweep") and self._stack():
                    key = self._turn_key()
                    ids = [o["id"] for o in G.creatures_in({tuple(t) for t in tiles} - old, self.b["combatants"])
                           if o is not c and not self._is_out(o) and self._zone_affects(z, o) and z["hits"].get(str(o["id"])) != key]
                    for i in ids:
                        z["hits"][str(i)] = key
                    S = self._zone_strike(z, ids, "sweep") if ids else None
                    if S:
                        self._stack().append(S)               # inside the move: it goes off next

    def _turn_key(self) -> str:
        return f"{self.b.get('round')}:{self.b.get('turn')}"

    # ------------------------------------------------------------------ triggers
    def _zone_strike(self, z: dict, ids: List[int], why: str) -> Optional[dict]:
        """The strike (save / damage / conditions / healing) a zone makes on these creatures now."""
        owner = self._find_or_none(z.get("owner"))
        ids = [i for i in ids if self._find_or_none(i)]
        if not ids:
            return None
        self._zone_vfx("hit", z, ids=list(ids))                       # it flares under the ones it strikes
        if z.get("heal"):
            for i in ids:
                if z.get("uses_left", 1) <= 0:
                    break
                c = self._find(i)
                if (self._monster(c) or {}).get("type") in ("undead", "construct"):
                    continue                                    # the spirit can't heal constructs or undead
                n = roll(z["heal"])
                self._heal(c, n)
                self._say(f"{z['name']}: {c['name']} regains {n} hit points")
                z["uses_left"] = z.get("uses_left", 1) - 1
            if z.get("uses_left", 1) <= 0:
                self._zone_off(z, "used up")
            return None
        parts = [list(p) for p in z.get("parts") or []]
        if z.get("cap"):
            left = z["cap"] - z.get("dealt", 0)
            if left <= 0:
                self._zone_off(z, "spent")
                return None
        label = f"{z['name']}"
        if z.get("save"):
            sv = {"ab": z["save"], "dc": z.get("dc", 13), "half": z.get("half", False), "conds": z.get("conds") or [],
                  "rounds": z.get("cond_rounds") or (z.get("rounds") if z.get("conds") else None), "prone": z.get("prone"),
                  "push": z.get("push"), "pull_to_point": z.get("pull"), "repeat": z.get("repeat"),   # Wall of Light's blindness: a save at the end of each turn; Maelstrom's pull to its centre
                  "dis_types": z.get("dis_types"), "revert_shape": z.get("revert_shape"),      # Moonbeam: shapechangers
                  "mods": dict(z["fail_mods"]) if z.get("fail_mods") else None,
                  "until": z.get("fail_until"), "on_save": dict(z["on_save"]) if z.get("on_save") else None}   # Grave Ground, Doomtide; Dirge's halved speed
            if z.get("escape"):
                sv["repeat"] = None
            S = self._strike(owner, label, ids, mode="save", sv=sv, parts=parts, spell=True, conc=z.get("conc_by"), origin=z.get("point") or [0, 0])
        elif parts:
            S = self._strike(owner, label, ids, mode="auto", parts=parts, spell=True)
        else:
            return None
        S["zone"] = z["id"]
        if z.get("exhaustion"):
            S["exhaustion_on_fail"] = True
        return S

    def _burn_webs(self, c: dict):
        """Fire on a creature caught in a Web burns the webbing around it away: those tiles are gone, it is free, and the
        burning strands deal 2d4 fire when its next turn starts."""
        if not c.get("pos"):
            return
        mine = {tuple(p) for p in self._footprint(c, *c["pos"])}
        for z in [z for z in self._zones() if z.get("burns")]:
            if not any(tuple(t) in mine for t in z["tiles"]):
                continue
            z["tiles"] = [t for t in z["tiles"] if tuple(t) not in mine]
            for e in [e for e in c.get("effects") or [] if e["name"] == z["name"]]:
                self._effect_off(c, e, "the web burns away")
            self._effect_on(c, f"Burning {z['name'].lower()}", [], None, None, None, None, z["name"],
                            {"dot": {"dice": "2d4", "type": "fire", "when": "start", "times": 1}}, None, z.get("owner"))
            self._say(f"The {z['name'].lower()} around {c['name']} catches fire and burns away")
            if not z["tiles"]:
                self._zone_off(z, "burned away")

    def _trap_burst(self, z: dict, c: dict) -> Optional[dict]:
        """A rune that erupts when a creature comes near it (Fire Rune): it is gone, and everyone in the burst around its point
        saves (a failure can also slow, the frost rune's)."""
        tr = z["trap"]
        owner = self._find_or_none(z.get("owner"))
        self._zone_off(z, f"{c['name']} sets it off")
        xs, ys = [t[0] for t in z["tiles"]] or [0], [t[1] for t in z["tiles"]] or [0]
        at = tuple(z.get("point") or ((min(xs) + max(xs)) / 2 + .5, (min(ys) + max(ys)) / 2 + .5))
        tiles = G.area_tiles("sphere", int(tr.get("radius") or 15), origin=at, **self._bounds_kw())
        self._area_vfx(owner, tiles, tr.get("parts") or [], "burst", list(at))
        ids = [o["id"] for o in G.creatures_in(tiles, self.b["combatants"]) if not self._is_out(o)]
        return self._strike(owner, z["name"], ids, mode="save", sv={"ab": tr.get("save") or "dex", "dc": z.get("dc", 13), "half": bool(tr.get("half")),
                                                                     "mods": dict(tr["fail_mods"]) if tr.get("fail_mods") else None,
                                                                     "until": tr.get("fail_until")},
                            parts=tr.get("parts") or [], spell=True, origin=list(at))

    def _disperse(self, tiles) -> None:
        """A blast of wind or force (Aard) clears the gas and vapour of the clouds it sweeps through (fog, stinking clouds...)."""
        cut = {tuple(t) for t in tiles}
        for z in list(self._zones()):
            if z.get("family") != "cloud" or z.get("family_kind") == "sleet" or not cut & {tuple(t) for t in z["tiles"]}:
                continue
            z["tiles"] = [t for t in z["tiles"] if tuple(t) not in cut]
            self._say(f"{z['name']} is blown away where the blast passes")
            if not z["tiles"]:
                self._zone_off(z, "dispersed")

    def _zone_mods(self, c: dict, have: list) -> list:
        """What standing in a lasting area does to a creature, as effects (profile._all_effects): `inside` for the creatures it affects
        (Yrden: no reactions), `inside_allies` for its owner and the owner's friends (Slow Time: ranged attacks at disadvantage), and
        `solidify`: an incorporeal foe inside (`have`: its other effects) loses its incorporeal movement and B/P/S resistance (Yrden)."""
        out = []
        mine = G.footprint(c["pos"], c.get("span") or 1)
        for z in self.b.get("zones") or []:
            if not (z.get("inside") or z.get("inside_allies") or z.get("solidify")):
                continue
            owner = self._find_or_none(z.get("owner"))
            if not ((c is owner and z.get("follow")) or mine & {tuple(t) for t in z["tiles"]}):
                continue
            foe = owner is not None and self._hostile(owner, c)
            if foe and z.get("inside"):
                out.append({"name": z["name"], "mods": dict(z["inside"]), "conditions": [], "zone": z["id"]})
            if not foe and z.get("inside_allies"):
                out.append({"name": z["name"], "mods": dict(z["inside_allies"]), "conditions": [], "zone": z["id"]})
            if foe and z.get("solidify") and any((e.get("mods") or {}).get("incorporeal") for e in have):
                out.append({"name": f"{z['name']} (solid form)", "mods": {"solid": True, "unresist": ["bludgeoning", "piercing", "slashing"]},
                            "conditions": [], "zone": z["id"]})
        return out

    def _zone_entered(self, c: dict, before: set, after: set, R: Optional[dict] = None) -> list:
        """Movement: strikes for the zones a creature just walked into (first time this turn), and Spike Growth's per-step
        damage. Returns the strikes to run."""
        out = []
        key = self._turn_key()
        for z in list(self._zones()):
            tiles = {tuple(t) for t in z["tiles"]}
            if z.get("duel_ground") and after & tiles and not before & tiles and c["id"] not in (z.get("duel_ids") or []):
                self._zone_off(z, f"{c['name']} entered the duelling ground")       # Dueling Ground: only the duellists may be inside
                continue
            if z.get("trap") and after & tiles and not before & tiles and c["id"] != z.get("owner"):
                S = self._trap_burst(z, c)                          # Fire Rune: someone came within 5 ft of it
                if S:
                    out.append(S)
                continue
            if not self._zone_affects(z, c):
                continue
            if z.get("per_5ft") and after & tiles:
                S = self._strike(self._find_or_none(z["owner"]), z["name"], [c["id"]], mode="auto", parts=z["per_5ft"], spell=True)
                out.append(S)
                continue
            if z.get("enter") and after & tiles and not before & tiles:
                if z["hits"].get(str(c["id"])) == key:
                    continue
                z["hits"][str(c["id"])] = key
                S = self._zone_strike(z, [c["id"]], "enter")
                if S:
                    out.append(S)
        return out

    def _difficult_tiles(self, c: Optional[dict] = None) -> set:
        if c is not None and self._fx(c, "free_move"):          # Freedom of Movement: difficult terrain doesn't slow it
            return set()
        out = set(self._terrain().difficult)
        for z in self._zones():
            if z.get("difficult") == "affected" and c is not None and not self._zone_affects(z, c):
                continue                                        # Wrath of Nature: only the caster's enemies are slowed
            if z.get("difficult") == "others" and c is not None and z.get("owner") == c["id"]:
                continue                                        # Investiture of Ice: "difficult terrain for creatures other than you"
            if z.get("difficult") or (z.get("slow") and c is not None and self._zone_affects(z, c)):
                out |= {tuple(t) for t in z["tiles"]}
        return out

    def _blocked_tiles(self) -> set:
        out = set(self._terrain().blocked)
        for z in self._zones():
            if z.get("blocks"):
                out |= {tuple(t) for t in z["tiles"]}
        return out

    # ------------------------------------------------------------------ moving a zone
    def move_zone(self, cid: int, zone_id: int, point) -> str:
        """The caster moves a zone it controls (Moonbeam, Flaming Sphere, Healing Spirit...) to a new point."""
        with self.lock:
            self._busy()
            c = self._find(cid)
            z = next((x for x in self._zones() if x["id"] == int(zone_id) and x.get("owner") == cid), None)
            if not z or not z.get("move"):
                raise ServiceError("That area can't be moved.")
            mv = z["move"]
            old = z.get("point") or (z["tiles"][0] if z["tiles"] else [0, 0])
            if G.distance_to_point(G.tile_of(tuple(old)), 1, tuple(point)) > mv["feet"] + 5:
                raise ServiceError(f"It moves up to {mv['feet']} ft.")
            self._pay(c, mv["cost"], f"move {z['name']}")
            area = z.get("area") or {"shape": "square", "size": 5, "origin": "point"}
            tiles = G.area_for(area, c["pos"], c.get("span") or 1, tuple(point), *self._bounds())
            mid = lambda ts: (sum(t[0] for t in ts) / max(1, len(ts)), sum(t[1] for t in ts) / max(1, len(ts)))  # noqa: E731
            (x0, y0), (x1, y1) = mid(z["tiles"]), mid(list(tiles))
            z["tiles"] = [list(t) for t in sorted(tiles)]
            z["point"] = [float(point[0]), float(point[1])]
            self._zone_vfx("move", z, d=[x1 - x0, y1 - y0])           # it glides there on the maps
            text = f"{c['name']} moves {z['name']}"
            if mv.get("carry"):                                       # Whirlwind: the creatures caught in it go along
                dx, dy = round(x1 - x0), round(y1 - y0)
                w, h = self._bounds()[:2]
                for o in [o for o in self.b["combatants"] if o.get("pos") and any(e["name"] == z["name"] and e.get("source_id") == cid
                                                                                  and "Restrained" in e.get("conditions", []) for e in o.get("effects") or [])]:
                    to = [min(max(0, o["pos"][0] + dx), w - 1), min(max(0, o["pos"][1] + dy), h - 1)]
                    if not any(p is not o and p.get("pos") and G.footprint(p["pos"], p.get("span") or 1) & G.footprint(to, o.get("span") or 1)
                               for p in self.b["combatants"]):
                        o["pos"] = to
                        text += f"\n{o['name']} is carried along"
            if mv.get("ram"):
                hit = [o["id"] for o in G.creatures_in(tiles, self.b["combatants"]) if not self._is_out(o) and o is not c]
                if hit:
                    S = self._zone_strike(z, hit[:1], "ram")
                    if S:
                        text += "\n" + self._run_r(S)
            else:
                inside = [o["id"] for o in G.creatures_in(tiles, self.b["combatants"]) if not self._is_out(o) and self._zone_affects(z, o)
                          and z.get("enter") and z["hits"].get(str(o["id"])) != self._turn_key()]
                for i in inside:
                    z["hits"][str(i)] = self._turn_key()
                if inside:
                    S = self._zone_strike(z, inside, "moved")
                    if S:
                        text += "\n" + self._run_r(S)
            self._commit(text.split("\n")[0])
            return text

    def zones_view(self) -> List[dict]:
        """What the maps draw: each zone's tiles, name and look."""
        with self.lock:
            out = []
            for z in self._zones():
                look = "dark" if z.get("darkness") else "fog" if z.get("obscure") else "wall" if z.get("blocks") or z.get("opaque") else \
                    "light" if z.get("light") and not z.get("parts") else "harm" if z.get("parts") or z.get("start_auto") or z.get("per_5ft") else "area"
                out.append({"id": z["id"], "name": z["name"], "owner": z.get("owner"), "tiles": z["tiles"], "look": look,
                            "rounds": z.get("rounds"), "movable": bool(z.get("move")), "note": z.get("note", ""),
                            "hidden": bool(z.get("hidden")), "conc_by": z.get("conc_by"),
                            "family": z.get("family") or zone_family(z["name"], z)[0], "kind": z.get("family_kind") or "",
                            "dtype": next((str(t).lower() for _d, t in z.get("parts") or [] if t), "")})
            return out
