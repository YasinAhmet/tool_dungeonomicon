"""Start and end of turns: the turn's action budget, effects that end "at the start of your next turn", repeated saves,
damage over time, regeneration, zones, recharges, Blink - and the round clock for durations.

Everything a turn boundary sets off that rolls dice runs as one 'seq' resolution, so a reaction prompt can pause it.
"""
import re
from typing import Optional

from . import economy as EC
from .resolve import DONE, NEXT, roll

AURA_RE = re.compile(r"starts its turn within (\d+) (?:feet|ft\.?) of (?:the|him|her|it|(?-i:[A-Z][\w'’-]*))\b", re.I)    # Stench, Fear Aura, Petrifying Gaze...


class DurationsMixin:
    # ------------------------------------------------------------------ the turn budget
    def _legendary_max(self, c: dict) -> int:
        m = self._monster(c)
        if not m or not m.get("legendary"):
            return 0
        g = re.search(r"can take (\d+) legendary actions", m.get("legendary_note", "") or "", re.I)
        return int(g.group(1)) if g else 3

    def _fresh_turn(self, c: dict) -> dict:
        extra = sum(int(v) for _e, v in self._fxs(c, "extra_action"))
        t = EC.new_turn(self._speed(c), self._legendary_max(c), extra_actions=min(1, extra))
        c["turn"] = t
        return t

    def _ready_all(self):
        """At the start of a battle everyone has a full turn budget (reactions work before their first turn)."""
        for c in self.b["combatants"]:
            self._fresh_turn(c)
        self._subb_battle_start()                               # Tranquility (subfeats_b.py)
        self._subc_battle_start()                               # Blessing of the Forge, Stormborn (subfeats_c.py)
        self._subd_battle_start()                               # Celestial Resilience (subfeats_d.py)

    # ------------------------------------------------------------------ turn boundaries
    def _turn_end(self, cid):
        c = next((x for x in self.b["combatants"] if x["id"] == cid), None)
        if not c:
            return
        items = []
        items += self._repeat_saves(c, "end")
        items += self._dots(c, "end")
        items += self._zone_turn_items(c, "end")
        items += self._spell_turn_end_items(c)                  # spells.py: Storm Call's bolts
        self._bead_grow(c)                                      # Delayed Blast Fireball: +1d6
        for o in self.b["combatants"]:
            for eff in list(o.get("effects") or []):
                u = eff.get("until") or {}
                if u.get("end") == cid:
                    if u.get("skip", 0) > 0:
                        u["skip"] -= 1
                    else:
                        self._effect_off(o, eff, "its time is up")
        self._tick_timers(cid, "end")
        if self._fx(c, "blink"):
            r = self.rng.randint(1, 20)
            if r >= 11:
                self._effect_on(c, "Blinked away", [], None, None, None, None, c["name"], {"untargetable": True}, None, c["id"],
                                until={"start": c["id"]})
                self._say(f"{c['name']} blinks to the Ethereal Plane ({r})")
        self._class_turn_end(c)                                 # a scout's Skirmisher
        self._trait_turn_end(c)                                 # a treasure goblin's portal at the end of its fourth turn (traits.py)
        self._run_items(c, items, "end of turn")

    def _turn_start(self, cid):
        c = next((x for x in self.b["combatants"] if x["id"] == cid), None)
        if not c:
            return
        for o in self.b["combatants"]:
            o.pop("leg_move", None)                             # a Wing Attack's flight is for right after it
        self._fresh_turn(c)
        c["readied"] = None
        c["had_turn"] = True                                    # an assassin's Assassinate looks for creatures without one
        for o in self.b["combatants"]:
            for eff in list(o.get("effects") or []):
                u = eff.get("until") or {}
                if u.get("start") == cid or u.get("start_next") == cid:
                    self._effect_off(o, eff, "its time is up")
        self._tick_timers(cid, "start")
        self._regen(c)
        self._trait_turn_start(c)                               # a berserker's Reckless
        self._class_turn_start(c)                               # Twilight Sanctuary, Halo of Spores, Dread Ambusher
        self._token_turn_start(c)
        self._spell_turn_start(c)                               # spells.py: Confusion's d10, Aura of Life
        for e, v in self._fxs(c, "temp_each"):
            src = self._find_or_none(e.get("source_id"))
            n = self._casting_mod(src) if src and v == "MOD" else int(v) if str(v).isdigit() else 0
            if n > 0:
                self._give_temp(c, n)
        if c.get("spent"):
            self._recharge_roll(c)
        self._monster_auras(c)
        items = []
        items += self._repeat_saves(c, "start")
        items += self._dots(c, "start")
        items += self._source_dots(c)                           # what it has swallowed burns in it
        items += self._zone_turn_items(c, "start")
        items += self._spell_turn_items(c)                      # spells.py: Storm of Vengeance's later rounds
        for z in list(self.b.get("zones") or []):
            if z.get("drift") and z.get("owner") == c["id"]:        # Doomtide moves on 10 ft from its caster
                S = self._zone_drift(z)
                if S:
                    items.append(S)
            if z.get("ally_boost") and z.get("owner") == c["id"]:   # Distorted Distance: Shortened Space again for the friends in the sphere
                self._zone_boost(z)
            if z.get("caster_turn") and z.get("owner") == c["id"]:
                from . import geometry as G
                ids = [o["id"] for o in G.creatures_in({tuple(t) for t in z["tiles"]}, self.b["combatants"]) if not self._is_out(o)
                       and self._zone_affects(z, o)]                # Wrath of Nature: only the caster's enemies
                S = self._zone_strike(z, ids, "caster")
                if S:
                    items.append(S)
        if c["kind"] == "pc" and self._hp_of(c) <= 0 and not self._stable(c) and not self._dead(c) \
                and (self.b.get("rules") or {}).get("auto_death_saves", True):
            items.insert(0, self._new_r("dsave", c, "Death save", summary_targets=c["name"]))
        self._run_items(c, items, "start of turn")

    def _banished_turn(self, c: Optional[dict]) -> bool:
        """A banished creature (Banishment, Maze) has no turn here: True when its turn should pass by itself. A way out
        (Maze: a DC 20 Intelligence check, for its action) is rolled for it first."""
        if not c or not self._fx(c, "banished"):
            return False
        for e, _v in self._fx(c, "way_out"):
            ab, dc = e["mods"]["way_out"]
            total = self._check(c, ab)
            ok = total >= dc
            self._say(f"{c['name']} {ab.upper()} check to escape {e['name']}: {total} vs DC {dc} — " + ("escapes" if ok else "failed"))
            if ok:
                self._effect_off(c, e, "escaped")
                c["turn"]["action"] = max(0, c["turn"]["action"] - 1)
        if self._fx(c, "banished"):
            self._say(f"{c['name']} is banished: its turn passes")
            return True
        return False

    def _run_items(self, c: dict, items: list, label: str):
        items = [i for i in items if i]
        if not items:
            return
        R = self._new_r("seq", c, label, items=items, i=0, summary_targets=c["name"])
        stack = self._stack()
        if stack and any(r.get("wait") or r.get("dice") for r in stack):
            stack.insert(0, R)
            return
        stack.clear()
        stack.append(R)
        self._drive()

    def _step_seq(self, R: dict) -> str:
        if R["i"] >= len(R["items"]):
            return DONE
        child = R["items"][R["i"]]
        R["i"] += 1
        self._stack().append(child)
        return NEXT

    def _zone_turn_items(self, c: dict, when: str) -> list:
        """The zones' strikes for a creature starting or ending its turn (built, not run)."""
        from . import geometry as G
        out = []
        if not c.get("pos") or self._is_out(c):
            return out
        key = self._turn_key()
        for z in list(self.b.get("zones") or []):
            if not self._zone_affects(z, c):
                continue
            tiles = {tuple(t) for t in z["tiles"]}
            mine = G.footprint(c["pos"], c.get("span") or 1)
            inside = bool(mine & tiles)
            if when == "start" and inside and z.get("conc_save") and c.get("concentrating"):     # Sleet Storm shakes a caster's focus
                res = self._saving_throw(c, z["conc_save"], int(z.get("dc") or 13), spell=True, label=z["name"])
                self._say(f"{c['name']} concentration in the {z['name'].lower()}: {z['conc_save'].upper()} save d20 {res['kept']} = "
                          f"{res['total']} vs DC {z.get('dc')} — " + ("kept" if res["ok"] else "lost"))
                if not res["ok"]:
                    self._drop_conc(c, z["name"])
            if when == "start" and inside and z.get("start_auto"):
                parts = z["start_auto"]
                out.append(self._strike(self._find_or_none(z["owner"]), z["name"], [c["id"]], mode="auto", parts=parts, spell=True))
            if when == "end" and inside and z.get("end_save"):
                es = z["end_save"]
                out.append(self._strike(self._find_or_none(z["owner"]), z["name"], [c["id"]], mode="save",
                                        sv={"ab": es["save"], "dc": z["dc"], "half": False}, parts=es["parts"], spell=True))
            if not (inside and z.get(when)):                   # a zone strikes only on its own tiles, what the maps draw
                continue
            if z["hits"].get(str(c["id"])) == key:
                continue
            z["hits"][str(c["id"])] = key
            S = self._zone_strike(z, [c["id"]], when)
            if S:
                out.append(S)
        return out

    def _regen(self, c: dict):
        if self._hp_of(c) <= 0 and c["kind"] != "pc":
            return
        for eff, dice in self._fx(c, "regen"):
            stop = set((eff.get("mods") or {}).get("regen_stop") or [])
            if stop and stop & set(c.get("took_types") or []):
                self._say(f"{c['name']}'s {eff['name']} doesn't work this turn")
                continue
            if c["kind"] != "pc" and c["hp"] <= 0:
                continue
            n = roll(dice)
            self._heal(c, n)
            self._say(f"{c['name']} regains {n} HP from {eff['name']}")
            self._npc_roll(c, "💚", f"{eff['name']} regeneration", n, str(dice))
        c["took_types"] = []
        char = self._sheet(c)                                   # Champion 18: Survivor, while at half hit points or fewer
        if char and char.class_level("Fighter") >= 18 and char.class_entry("Fighter").get("subclass") == "Champion" \
                and 0 < self._hp_of(c) <= self._max_hp(c) // 2:
            n = 5 + char.mod("con")
            self._heal(c, n)
            self._say(f"{c['name']} regains {n} HP (Survivor)")

    def _monster_auras(self, c: dict):
        """Stat block traits that work on whoever starts its turn near the monster: Stench, Fear Aura, Petrifying Gaze,
        an eladrin's presence... A save (both must see each other for a gaze); damage and conditions from the text; a
        success that grants immunity is remembered. A gaze that turns to stone restrains first, petrifies on a second failure."""
        from . import combat_rules as CR
        from . import conditions as K
        if not c.get("pos") or self._hp_of(c) <= 0 or "Petrified" in self._conds(c):
            return
        for m in self.b["combatants"]:
            if m is c or m["kind"] == "pc" or not m.get("pos") or self._hp_of(m) <= 0 or not self._hostile(m, c) or K.incapacitated(self._conds(m)):
                continue
            for tr in (self._monster(m) or {}).get("traits") or []:
                text = tr.get("text") or ""
                near = AURA_RE.search(text)
                if not near or self._dist(m, c) > int(near.group(1)):
                    continue
                if re.search(r"see each other|can see the [\w ]+?'s eyes", text) and not (self._sees(m, c) and self._sees(c, m)):
                    continue
                key = f"{m.get('monster')}:{tr['name']}"
                if key in (c.get("aura_immune") or []) or any(e["name"] == tr["name"] for e in c.get("effects") or []):
                    continue                                    # immune, or still under it (a stoning repeats its own save)
                _pre, post, sv = CR.split_save(text)
                if not sv:                                      # no save: an ice toad's Cold Aura just hurts
                    parts = CR.damage_parts(text[near.end():], now_only=False) if re.search(r"\btakes? \d+", text[near.end():]) else []
                    if parts:
                        self._say(self._deal(c, parts, by=m, label=tr["name"]))
                    continue
                res = self._saving_throw(c, sv[0], sv[1], label=tr["name"])
                self._say(f"{c['name']} {sv[0].upper()} save against {m['name']}'s {tr['name']}: d20 {res['kept']} = {res['total']} vs DC {sv[1]} — "
                          + ("success" if res["ok"] else "failed"))
                if res["ok"]:
                    if re.search(r"immune to", post, re.I):
                        c.setdefault("aura_immune", []).append(key)
                    continue
                zero = re.search(r"fails? by 5 or more, the creature is reduced to 0 hit points(?:, unless it is immune to the (\w+) condition)?", post, re.I)
                if zero and res["total"] <= int(sv[1]) - 5 and not (zero.group(1) and zero.group(1).capitalize() in (self._defenses(c).get("immune_cond") or set())):
                    sheet = self._sheet(c)                      # a bodak's Death Gaze: dropped to 0 hit points
                    self._say(self._deal_rolled(c, [[self._hp_of(c) + int(sheet.temp_hp if sheet else c.get("temp_hp") or 0), ""]], by=m, label=tr["name"]))
                    continue
                parts = CR.damage_parts(post)
                if parts:
                    self._say(self._deal(c, parts, by=m, label=tr["name"]))
                conds = [x for x in CR.conditions_in(post) if x != "Incapacitated" or "incapacitated" in post.lower()]
                worse = CR.fail_by_five(post) if res["total"] <= int(sv[1]) - 5 else []     # "fails by 5 or more, ... instantly petrified"
                if worse:
                    self._effect_on(c, tr["name"], worse, None, None, None, None, m["name"], None, None, m["id"])
                    self._say(f"{c['name']} fails by 5 or more: {', '.join(x.lower() for x in worse)} ({tr['name']})")
                elif "turn to stone" in post.lower():             # restrained now; the save again at the end of its turn decides
                    self._effect_on(c, tr["name"], ["Restrained"], sv[0], sv[1], "end", None, m["name"], {"stoning": True}, None, m["id"])
                    self._say(f"{c['name']} begins to turn to stone: restrained ({tr['name']})")
                elif conds:
                    rounds = CR.duration_rounds(post)
                    self._effect_on(c, tr["name"], conds, None, None, None, rounds, m["name"], None, None, m["id"],
                                    until=None if rounds else {"start": c["id"]})    # "until the start of its next turn"
                    self._say(f"{c['name']} is now {', '.join(x.lower() for x in conds)} ({tr['name']})")

    def _repeat_saves(self, c: dict, when: str) -> list:
        """Saves the creature repeats now: rolled here; a success ends the effect."""
        for eff in list(c.get("effects") or []):
            if eff.get("repeat") != when or not eff.get("ability") or ((eff.get("mods") or {}).get("dot") or {}).get("save"):   # its dot's save
                continue
            src = self._find_or_none(eff.get("source_id")) if (eff.get("mods") or {}).get("unseen_only") else None
            if src is not None and c.get("pos") and src.get("pos") and self._sees(c, src):
                continue                                        # Fear: only out of the caster's sight
            res = self._saving_throw(c, eff["ability"], int(eff["dc"] or 10), spell=True, conds=eff.get("conditions") or [], label=eff["name"])
            self._say(f"{c['name']} {eff['ability'].upper()} save against {eff['name']}: d20 {res['kept']}{res['note']} = {res['total']} vs DC {eff['dc']} — "
                      + ("success" if res["ok"] else "failed"))
            if not res["ok"] and (eff.get("mods") or {}).get("fail_exhaust"):     # Vision of Elapsing Eons: a failed save is a level of exhaustion
                self._exhaust(c, 1)
            need = int((eff.get("mods") or {}).get("stone_need") or 0)     # a Sword of the Medusa: three of a kind decides it
            if need:
                key = "stone_ok" if res["ok"] else "stone_fail"
                eff[key] = int(eff.get(key) or 0) + 1
                if eff[key] < need:
                    continue
            if res["ok"]:
                self._effect_off(c, eff, "saved")
            elif (eff.get("mods") or {}).get("stoning"):             # a second failure against a petrifying gaze: stone
                self._effect_off(c, eff, "turned to stone")
                self._effect_on(c, eff["name"], ["Petrified"], None, None, None, None, eff.get("source", ""), None, eff.get("conc_by"), eff.get("source_id"))
                self._say(f"{c['name']} turns to stone")
            elif (eff.get("mods") or {}).get("worsen"):              # Song of Sinking: each failure sinks it deeper (spells.py)
                self._worsen(c, eff)
            elif (eff.get("mods") or {}).get("fail_effect"):         # Contagion: the third failure and the disease takes hold
                fe = eff["mods"]["fail_effect"]
                self._effect_off(c, eff, "the disease takes hold")
                self._effect_on(c, fe.get("name") or eff["name"], list(fe.get("conds") or []), None, None, None, fe.get("rounds"), eff.get("source", ""),
                                dict(fe.get("mods") or {}), eff.get("conc_by"), eff.get("source_id"))
                self._say(f"{c['name']} comes down with {fe.get('name') or eff['name']}")
        return []

    def _dots(self, c: dict, when: str) -> list:
        """Damage over time (Melf's Acid Arrow, Phantasmal Killer, Caustic Brew): strikes to run."""
        out = []
        for eff in list(c.get("effects") or []):
            dot = (eff.get("mods") or {}).get("dot")
            if not dot or dot.get("when") != when:
                continue
            src = self._find_or_none(eff.get("source_id"))
            if dot.get("near") and not (src is not None and src.get("pos") and c.get("pos") and self._dist(src, c) <= int(dot["near"])):
                continue                                        # Transfix: only when it ends its turn within 5 ft of the caster
            if dot.get("save"):
                S = self._strike(src, eff["name"], [c["id"]], mode="save", sv={"ab": dot["save"], "dc": eff.get("dc") or 13, "half": False,
                                                                              "end_on_save": eff["name"]}, parts=[[dot["dice"], dot["type"]]], spell=True)
            else:
                S = self._strike(src, eff["name"], [c["id"]], mode="auto", parts=[[dot["dice"], dot["type"]]], spell=True)
            out.append(S)
            if dot.get("times"):
                dot["times"] -= 1
                if dot["times"] <= 0:
                    self._effect_off(c, eff, "done")
        return out

    def _tick_rounds(self):
        for c in self.b["combatants"]:
            st = c.get("concentrating")
            if st and st.get("rounds") is not None:
                st["rounds"] -= 1
                if st["rounds"] <= 0:
                    self._drop_conc(c, "duration over")
            for eff in list(c.get("effects") or []):
                if eff.get("rounds") is not None:
                    eff["rounds"] -= 1
                    if eff["rounds"] <= 0:
                        self._effect_off(c, eff, "duration over")
            keep = []
            for a in c.get("spell_actions") or []:
                if a.get("rounds") is not None:
                    a["rounds"] -= 1
                    if a["rounds"] <= 0:
                        continue
                keep.append(a)
            c["spell_actions"] = keep
        for z in list(self.b.get("zones") or []):
            if z.get("rounds") is not None:
                z["rounds"] -= 1
                if z["rounds"] <= 0:
                    (self._bead_boom if z.get("bead") else self._zone_off)(z, "duration over")
        for t in self.b["combatants"]:
            if (t.get("conjured") or {}).get("rounds") is not None:
                t["conjured"]["rounds"] -= 1
        self._prune_tokens()
