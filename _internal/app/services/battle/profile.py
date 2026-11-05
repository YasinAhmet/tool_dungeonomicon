"""Who a combatant is right now: its stat block or character sheet merged with effects, conditions and passive traits.
Everything that asks "what can this creature do, how fast is it, what does it resist, can it see that one" goes here."""
import re
from typing import Dict, List, Optional

from ...rules.monsters import ability_mod, bestiary
from . import conditions as K
from . import features as F
from . import floors as FL
from . import geometry as G
from . import modifiers as M
from . import sight as V
from . import summon_stats as SS
from .constants import faction_of

SIZE_SPAN = {"Tiny": 1, "Small": 1, "Medium": 1, "Large": 2, "Huge": 3, "Gargantuan": 4}


class ProfileMixin:
    # ------------------------------------------------------------------ sources
    def _monster(self, c: Optional[dict]) -> Optional[dict]:
        """The stat block in use: a Wild Shape or Polymorph form first."""
        if c and c.get("form"):
            mon = bestiary.get(c["form"]["monster"])
            own = bestiary.get(c.get("monster")) if c["form"].get("keeps_hp") and c.get("monster") and mon else None
            if own:          # a monster's Change Shape: it keeps the Change Shape bonus action and its Intelligence, Wisdom and Charisma
                keep = [e for e in own.get("bonus_actions") or [] if re.search(r"Change Shape", e.get("name", ""))]
                return dict(mon, bonus_actions=[e for e in mon.get("bonus_actions") or [] if e not in keep] + keep,
                            abilities=dict(mon["abilities"], **{k: own["abilities"][k] for k in ("int", "wis", "cha")}))
            return mon
        if c and c.get("monster") and c.get("summon"):
            return SS.fill(c["monster"], c["summon"])          # a spirit or companion: its summoner's numbers written in
        return bestiary.get(c["monster"]) if c and c.get("monster") else None

    def _sheet(self, c: Optional[dict]):
        return self._char(c["character"]) if c and c.get("kind") == "pc" and c.get("character") else None

    def _conds(self, c: dict) -> List[str]:
        char = self._sheet(c)
        return list(char.conditions) if char else list(c.get("conditions") or [])

    def _exhaustion(self, c: dict) -> int:
        char = self._sheet(c)
        return int(char.d.get("exhaustion") or 0) if char else int(c.get("exhaustion") or 0)

    def _all_effects(self, c: dict) -> list:
        """The creature's effects plus its passive traits and features (as effect-like entries). On a frozen copy of the
        battle (a menu being built: nothing changes) each creature's are gathered once."""
        memo = getattr(self, "_frozen", None)
        if memo is not None:
            hit = memo.get(("all", id(c)))
            if hit is None or hit[0] is not c:                # kept with the creature: a passing copy's id is never reused
                hit = memo[("all", id(c))] = (c, self._gather_effects(c))
            return list(hit[1])
        return self._gather_effects(c)

    def _gather_effects(self, c: dict) -> list:
        out = list(c.get("effects") or [])
        m = self._monster(c)
        if m:
            out += M.trait_mods(m.get("traits"))
            out += self._trait_counters(c)                   # Seven Radiances: resistance while any are left (traits.py)
            if any((t.get("text") or "").startswith("While Bloodied") for t in m.get("traits") or []) \
                    and 0 < self._hp_of(c) <= self._max_hp(c) // 2:     # Bloodied Fury, Nearer to the Dead...
                out += M.bloodied_mods(m.get("traits"))
        char = self._sheet(c)
        if char:
            out += F.passives(char) + self._wonder_passives(c, char)     # worn magic items (wondrous.py)
            out += self._subd_passives(c, char)                          # Unyielding Spirit, Durable Magic... (subfeats_d.py)
            out += self._nf_passives(c, char)                            # Bloodied resistances, Eyes of Eirdu, Stronger Together... (newfeats.py)
        if c.get("pos"):                                     # a monster's trait aura: Aura of Command (its side), Aura of Murder (its foes)
            for o in self.b["combatants"]:
                if not o.get("pos") or o.get("kind") == "pc" or not M.has_trait_aura(o.get("monster")) \
                        or K.incapacitated(o.get("conditions") or []):
                    continue
                for t in M.trait_mods((self._monster(o) or {}).get("traits")):
                    for key, friendly in (("ally_aura", True), ("foe_aura", False)):
                        au = t["mods"].get(key)
                        if not au:
                            continue
                        if o is c:
                            if not au.get("self_too"):                  # "the commander and its allies"
                                continue
                        elif self._hostile(o, c) == friendly or self._dist(o, c) > au["ft"]:
                            continue
                        if au.get("only_type") and au["only_type"] not in str((self._monster(c) or {}).get("type") or "").lower():
                            continue                                    # Marshal Undead: only the undead
                        if au.get("unless_resist") and re.search(au["unless_resist"], " ".join(str((m or {}).get(k) or "") for k in ("resist", "immune"))):
                            continue                         # "unless they have resistance or immunity to such damage"
                        out.append({"name": f"{o['name']}: {t['name']}", "mods": dict(au["mods"]), "conditions": [], "trait": True})
        if self.b.get("aura_fx") and c.get("pos"):           # Aura of Life, Circle of Power...: an ally's aura reaches this creature
            for o in self.b["combatants"]:
                if o is c or not o.get("pos"):
                    continue
                for e in o.get("effects") or []:
                    ft = (e.get("mods") or {}).get("aura_ft")
                    if ft and not self._hostile(o, c) and self._dist(o, c) <= ft \
                            and not ((e.get("mods") or {}).get("aura_active") and K.incapacitated(self._conds(c))):    # Aura of Evasion
                        out.append(e)
        if self.b.get("zone_fx") and c.get("pos"):           # Yrden, Slow Time: what the area it stands in does to it (zones._zone_mods)
            out += self._zone_mods(c, out)
        return out

    def _fxs(self, c: Optional[dict], key: str):
        memo = getattr(self, "_frozen", None)
        if memo is not None and c:
            hit = memo.get(("fxs", id(c), key))
            if hit is None or hit[0] is not c:
                hit = memo[("fxs", id(c), key)] = (c, M.effect_list(self._all_effects(c), key))
            return list(hit[1])
        return M.effect_list(self._all_effects(c) if c else [], key)

    # ------------------------------------------------------------------ numbers
    def _ability(self, c: dict, ab: str) -> int:
        char = self._sheet(c)
        if char:
            return max([char.mod(ab)] + [(int(v[ab]) - 10) // 2 for _e, v in self._fxs(c, "ability_set") if ab in v])
        m = self._monster(c)
        return ability_mod(m, ab) if m else 0

    def _prof(self, c: dict) -> int:
        char = self._sheet(c)
        if char:
            return char.proficiency_bonus
        m = self._monster(c)
        cr = float(m.get("cr_num") or 0) if m else 0
        return 2 + max(0, int((max(cr, 1) - 1) // 4))

    def _speeds(self, c: dict) -> Dict[str, int]:
        char = self._sheet(c)
        if char:
            race = char.race_data() or {}
            sp = {k: int(v) for k, v in (race.get("speed") or {}).items() if isinstance(v, (int, float)) and not isinstance(v, bool)}
            sp["walk"] = char.speed
            for k, v in (race.get("speed") or {}).items():          # "fly": true - a speed equal to the walking speed (a faerie's wings: not in medium or heavy armour)
                if v is True and k != "walk" and not ((char.equipped_armor() or {}).get("type") in ("MA", "HA") and k == "fly"):
                    sp[k] = char.speed
        else:
            m = self._monster(c)
            sp = M.form_speeds(m["speed"], c.get("shape")) if m else {"walk": 30}    # a werewolf runs faster as a wolf
            if m and c.get("shape"):                           # "While in bat form, ... its walking speed is 5 feet, and it has a flying speed of 30 feet"
                for t in m.get("traits") or []:
                    g = re.search(r"While in " + re.escape(c["shape"]) + r" form, ([^.]*\.(?: It [^.]*\.)?)", t.get("text") or "", re.I)
                    if g:
                        w, f = re.search(r"walking speed is (\d+)", g.group(1)), re.search(r"flying speed of (\d+)", g.group(1))
                        sp.update({k: int(v.group(1)) for k, v in (("walk", w), ("fly", f)) if v})
                        if f and not w:                        # mist: it only floats
                            sp["walk"] = 0
        for _e, v in self._fxs(c, "fly"):
            sp["fly"] = max(sp.get("fly", 0), int(v))
        for _e, v in self._fxs(c, "fly_set"):                  # Earthbind
            sp["fly"] = int(v)
        return sp

    def _speed(self, c: dict) -> int:
        """Feet of movement a turn: the map has no height, so a flier moves at its flying speed (a swarm of bats, the Fly
        spell), anyone else at its walking speed."""
        sp = self._speeds(c)
        base = max(sp.get("walk", 30), sp.get("fly", 0))
        conds = self._conds(c)
        return M.speed_of(base, self._all_effects(c), K.speed_factor(conds, self._exhaustion(c)))

    def _senses(self, c: dict) -> Dict[str, int]:
        char = self._sheet(c)
        if char:
            s = {"darkvision": char.darkvision} if char.darkvision else {}
        else:
            m = self._monster(c)
            s = M.monster_senses(m.get("senses", "")) if m else {}
        for _e, v in self._fxs(c, "senses"):
            for k, n in (v or {}).items():
                s[k] = max(s.get(k, 0), n) if isinstance(n, (int, float)) and not isinstance(n, bool) else n
        return s

    def _defenses(self, c: dict) -> Dict[str, set]:
        char = self._sheet(c)
        race_resist, item_resist = [], []
        if char:
            race = char.race_data() or {}
            race_resist = race.get("resist") or []
            for _e, item in char._active_items():
                item_resist += [r for r in item.get("resist") or [] if isinstance(r, str)]
        extra = {}
        if char:
            extra["immune_cond"] = set()
        return M.defenses(monster=self._monster(c), race_resist=race_resist, item_resist=item_resist,
                          effects=self._all_effects(c), conditions=self._conds(c), extra=extra)

    def _size_span(self, c: dict) -> int:
        return max(1, int(c.get("span") or 1))

    def _reach(self, c: dict) -> int:
        """Melee reach in feet: 10 with a reach weapon or a stat block attack that says so."""
        char = self._sheet(c)
        if char and not c.get("form"):
            far = sum(int(v) for _e, v in self._fxs(c, "giant_reach")) + self._race_reach(c, char)        # Giant Stature (Path of the Giant); a bugbear's Long-Limbed
            return (10 if any("reach" in (a.get("props") or []) and not a.get("ranged") for a in char.attacks()) else 5) + far
        m = self._monster(c)
        best = 5
        for e in (m or {}).get("actions") or []:
            r = re.search(r"reach (\d+) ft", e.get("text", ""))
            if r:
                best = max(best, int(r.group(1)))
        return best

    # ------------------------------------------------------------------ sides
    def _side(self, c: dict) -> int:
        """The faction it fights for now: its own (constants.faction_of), or its dominator's while dominated."""
        for e in c.get("effects") or []:
            if (e.get("mods") or {}).get("dominated"):
                src = next((o for o in self.b["combatants"] if o["id"] == e.get("source_id")), None)
                if src is not None and src is not c:
                    return faction_of(src)
        return faction_of(c)

    def _root(self, c: dict) -> dict:
        """Whoever summoned it, and who summoned them...: a neutral creature's summons are on its side (a summon that
        turned on its master is on its own)."""
        seen = set()
        while c.get("summoned_by") is not None and not c.get("turned") and c["id"] not in seen:
            seen.add(c["id"])
            up = next((o for o in self.b["combatants"] if o["id"] == c["summoned_by"]), None)
            if up is None:
                break
            c = up
        return c

    def _hostile(self, a: dict, b: dict) -> bool:
        """Enemies: different factions, or both neutral (faction 0 is hostile to everyone but its own summons)."""
        if a is b:
            return False
        fa, fb = self._side(a), self._side(b)
        return fa != fb or (fa == 0 and self._root(a) is not self._root(b))

    def _alive(self, c: dict) -> bool:
        return self._hp_of(c) > 0 and not self._is_out(c)

    def _can_act(self, c: dict) -> bool:
        return self._alive(c) and not K.incapacitated(self._conds(c))

    # ------------------------------------------------------------------ the map
    def _terrain(self):
        """The map's walls and props, the magical walls standing on it (Wall of Force, Wall of Stone: total cover) and
        the walls round each of its floors (floors.py)."""
        walls = [{"type": "symbol", "sym": "pillar", "x": t[0], "y": t[1]} for z in self.b.get("zones") or [] if z.get("blocks")
                 for t in z.get("tiles") or []] + FL.edge_walls(self.b["map"])
        return V.terrain((self.b.get("drawings") or []) + walls) if walls else V.terrain(self.b.get("drawings"))

    def _bounds(self) -> tuple:
        """(the map's width, its height, one floor's width or 0): what an area is cut to (geometry.area_for)."""
        m = self.b["map"]
        return m["w"], m["h"], FL.layout(m)[0] if FL.many(m) else 0

    def _bounds_kw(self) -> dict:
        """_bounds() as geometry.area_tiles' keywords."""
        return dict(zip(("w", "h", "fw"), self._bounds()))

    def _live_zones(self) -> list:
        """The battle's zones with their tiles as a set (`_tiles`), for sight and triggers."""
        out = []
        for z in self.b.get("zones") or []:
            out.append(dict(z, _tiles=frozenset(tuple(t) for t in z.get("tiles") or [])))
        return out

    def _dist(self, a: dict, b: dict) -> int:
        if not a.get("pos") or not b.get("pos"):
            return 0
        return G.distance_ft(a["pos"], a.get("span") or 1, b["pos"], b.get("span") or 1)

    def _viewer(self, c: dict) -> dict:
        conds = self._conds(c)
        if "Invisible" in conds and (self._fxs(c, "outlined") or self._wonder_revealed(c)):     # Faerie Fire, a Lantern of Revealing
            conds = [x for x in conds if x != "Invisible"]
        return {"pos": c.get("pos"), "span": c.get("span") or 1, "conditions": conds, "senses": self._senses(c),
                "flying": bool(c.get("flying"))}

    def _sees(self, a: dict, b: dict) -> bool:
        if a is b:
            return True
        hidden = [int(v) for _e, v in M.effect_list(b.get("effects"), "hidden")]
        if hidden and self._hostile(a, b) and max(hidden) > self._passive(a):
            return False
        return V.can_see(self._terrain(), self._viewer(a), self._viewer(b), base_light=self.b.get("map", {}).get("light", "bright"),
                         zones=self._live_zones())

    def _cover_between(self, a: dict, b: dict) -> int:
        if not a.get("pos") or not b.get("pos"):
            return V.NONE
        others = [(o["pos"], o.get("span") or 1) for o in self.b["combatants"]
                  if o is not a and o is not b and o.get("pos") and self._alive(o)]
        cov = V.cover(self._terrain(), a["pos"], a.get("span") or 1, b["pos"], b.get("span") or 1, others)
        if self._fxs(b, "cover34"):                              # Holy Star of Mystra: three-quarters cover
            cov = max(cov, V.THREE_QUARTERS)
        if self._fxs(b, "half_cover"):                           # Alustriel's Mooncloak, Fizban's Platinum Shield
            cov = max(cov, V.HALF)
        return max(cov, V.HALF) if self._fxs(b, "twilight_cover") else cov      # Twilight Shroud: half cover inside the sanctuary

    def _within(self, a: dict, b: dict, feet: int) -> bool:
        return not a.get("pos") or not b.get("pos") or self._dist(a, b) <= feet
