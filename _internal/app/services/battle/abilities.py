"""Class, race and feat features used in battle (features.ACTIVE): Second Wind, Action Surge, Rage, Cunning Action, the
monk's ki actions, Lay on Hands, Bardic Inspiration, Turn Undead, Breath Weapon, Wild Shape..."""
import copy
from typing import Optional

from ...rules.monsters import bestiary
from ..common import ServiceError
from . import economy as EC
from . import features as F
from . import geometry as G
from . import sight as V
from .resolve import roll
from .standard import SIZES


class AbilitiesMixin:
    def use_feature(self, cid: int, key: str, target_id: Optional[int] = None, option: Optional[str] = None, point=None) -> str:
        with self.lock:
            self._busy()
            c = self._find(cid)
            char = self._sheet(c)
            f = F.ACTIVE.get(key)
            if not f or not char or not F._safe(f["needs"], char):
                raise ServiceError("That feature isn't available.")
            tgt = self._find_or_none(target_id or self.b.get("target"))
            if f.get("range") and tgt and c.get("pos") and tgt.get("pos") and self._dist(c, tgt) > f["range"]:
                raise ServiceError(f"{tgt['name']} is out of range ({f['range']} ft)")
            res = f.get("resource")
            per_key = F.per_key(f, char)
            cost_res = int(f.get("ki") or 1)                    # Empty Body: 4 ki, Quickened Healing: 2
            if res and self._resource_left(c, res) < cost_res and key != "lay_on_hands":
                raise ServiceError(f"No {res} left.")
            alt = int(f.get("alt_ki") or 0) if F.per_left(f, char) == 0 else 0      # the uses are gone: ki pays for one more
            if alt and self._resource_left(c, "Ki Points") < alt:
                alt = 0
            if F.per_left(f, char) == 0 and not alt:
                raise ServiceError(f"{f['name']} is used until your next {F.per_of(f, char)} rest.")
            if key in ("martial_arts", "flurry") and self._economy_on() and not (c.get("turn") or {}).get("attacked"):   # PHB: right after the Attack action
                raise ServiceError("Take the Attack action first.")
            why = self._feature_why(c, char, key, f, tgt, option, point=point)     # classfeats.py: raging, a target, a tile...
            if why:
                raise ServiceError(why)
            if key == "cunning_hide":
                self._check_can_hide(c)
            before = copy.deepcopy(self.b), copy.deepcopy(char.d["resources"])     # a failure past this point spends nothing
            try:
                if f["cost"] != "attack":                       # one attack of the Attack action: paid as the attack is made
                    self._pay(c, f["cost"], f["name"])
                if res and key not in ("lay_on_hands",):
                    self._use_resource(c, res, cost_res)
                    if res == "Ki Points" and f["cost"] in ("action", "attack") and c.get("turn") is not None:
                        c["turn"]["ki_action"] = True           # Ki-Fueled Attack: ki spent in the action
                if alt:
                    self._use_resource(c, "Ki Points", alt)
                elif F.per_of(f, char):
                    char.d["resources"][per_key] = int(char.d["resources"].get(per_key) or 0) + 1
                    char.save()
                self._vfx("feature", id=c["id"], key=key, name=f["name"], other=tgt["id"] if tgt and tgt is not c else None)   # its look on the maps
                out = self._feature(c, char, key, f, tgt, option, point)
            except Exception:
                self.b.clear()
                self.b.update(before[0])
                for sheet in (char, self._sheet(c)):            # _use_resource saves through a fresh copy of the sheet
                    if sheet and sheet.d["resources"] != before[1]:
                        sheet.d["resources"] = copy.deepcopy(before[1])
                        sheet.save()
                raise
            self._commit()
            return out

    def _feature(self, c, char, key, f, tgt, option, point) -> str:
        name = c["name"]
        t = c.get("turn")
        done = self._class_feature(c, char, key, f, tgt, option, point)     # subclass and race features: classfeats.py
        if done is not None:
            return done
        if key == "second_wind":
            n = roll("1d10") + char.class_level("Fighter")
            self._heal(c, n)
            return self._out(f"{name} uses Second Wind: +{n} HP")
        if key == "action_surge":
            if t is not None:
                t["action"] = t.get("action", 0) + 1
            return self._out(f"{name} surges: one more action this turn")
        if key == "rage":
            if c.get("concentrating"):                          # no concentrating while raging (PHB)
                self._drop_conc(c, "raging")
            mods = {"resist": ["bludgeoning", "piercing", "slashing"], "rage": True, "rage_damage": F.rage_damage(char), "save_adv": ["str"],
                    "check_adv": ["str"]}
            mods.update(F.rage_extras(char))                    # Bear and Elk totems, Mindless Rage
            self._effect_on(c, "Rage", [], None, None, None, 10, name, mods, None, c["id"])
            surge = self._class_after_rage(c, char)             # Path of Wild Magic: a Wild Surge
            return self._out(f"{name} rages (+{F.rage_damage(char)} melee damage, resists " + ("all damage but psychic)" if len(mods["resist"]) > 3
                                                                                               else "weapon damage)") + (f"; {surge}" if surge else ""))
        if key == "reckless":
            self._effect_on(c, "Reckless Attack", [], None, None, None, None, name, {"str_melee_adv": True, "attacks_against": "adv"}, None,
                            c["id"], until={"start": c["id"]})
            return self._out(f"{name} attacks recklessly")
        if key in ("cunning_dash", "step_of_the_wind") and (key == "cunning_dash" or option != "disengage"):
            EC.dash(t)
            return self._out(f"{name} dashes ({f['name']})")
        if key in ("cunning_disengage", "step_of_the_wind"):
            if t is not None:
                t["disengaged"] = True
            return self._out(f"{name} disengages ({f['name']})")
        if key == "cunning_hide":
            return self._out(self._hide_now(c))
        if key == "steady_aim":
            self._effect_on(c, "Steady Aim", [], None, None, None, None, name, {"attacks_with": "adv", "once": True, "speed_set": 0}, None,
                            c["id"], until={"end": c["id"]})
            if t is not None:
                t["move"] = 0
            return self._out(f"{name} takes steady aim")
        if key in ("martial_arts", "flurry"):
            if not tgt:
                raise ServiceError("Pick a target first.")
            w = next((a for a in char.attacks() if "unarmed" in (a.get("props") or [])), None)
            atk = self._check_reach(c, tgt, self._weapon_atk(c, w))
            atk["n"] = 2 if key == "flurry" else 1
            return self._run_r(self._strike(c, f["name"], [tgt["id"]], mode="attack", atk=atk))
        if key == "patient_defense":
            self._effect_on(c, "Dodge", [], None, None, None, None, name, {"attacks_against": "dis", "save_adv": ["dex"]}, None, c["id"],
                            until={"start": c["id"]})
            return self._out(f"{name} dodges (Patient Defense)")
        if key == "lay_on_hands":
            target = tgt or c
            pool = self._resource_left(c, "Lay on Hands (HP pool)")
            want = int(option) if str(option or "").isdigit() else min(pool, self._max_hp(target) - self._hp_of(target))
            want = max(0, min(pool, want))
            if want <= 0:
                raise ServiceError("Nothing to heal (or the pool is empty).")
            self._use_resource(c, "Lay on Hands (HP pool)", want)
            self._heal(target, want)
            return self._out(f"{name} lays on hands: {target['name']} +{want} HP ({pool - want} left in the pool)")
        if key == "bardic_inspiration":
            if not tgt or tgt is c:
                raise ServiceError("Pick an ally (not yourself).")
            die = F.bardic_die(char)
            mods = {"attack": die, "save": die, "check": die, "once": True}
            if F.sub_at(char, "Bard", "College of Valor", 3):  # Combat Inspiration: its holder picks attack, damage or AC (classfeats.py)
                mods = {"save": die, "check": die, "once": True, "valor": die}
            self._effect_on(tgt, "Bardic Inspiration", [], None, None, None, 100, name, mods, None, c["id"])
            return self._out(f"{name} inspires {tgt['name']} ({die})")
        if key == "bladesong":
            n = max(1, char.mod("int"))
            self._effect_on(c, "Bladesong", [], None, None, None, 10, name, {"ac": n, "speed": 10, "conc_bonus": n}, None, c["id"])
            return self._out(f"{name} starts the Bladesong: +{n} AC, +10 ft speed, +{n} on concentration saves")
        if key == "vow_of_enmity":
            if not tgt or not self._hostile(c, tgt):
                raise ServiceError("Pick the foe to swear against.")
            self._effect_on(c, f"Vow of Enmity ({tgt['name']})", [], None, None, None, 10, name, {"adv_vs": tgt["id"]}, None, c["id"])
            return self._out(f"{name} swears a Vow of Enmity against {tgt['name']}: advantage on attacks against it")
        if key == "sacred_weapon":
            bonus = max(1, char.mod("cha"))
            self._effect_on(c, "Sacred Weapon", [], None, None, None, 10, name, {"weapon_attack": str(bonus)}, None, c["id"])
            return self._out(f"{name}'s weapon shines: +{bonus} to weapon attack rolls")
        if key == "preserve_life":
            pool = 5 * char.class_level("Cleric")
            healed = []
            for o in sorted((o for o in self.b["combatants"] if not self._hostile(o, c) and self._within(c, o, 30) and not self._dead(o)
                             and (self._monster(o) or {}).get("type") not in ("undead", "construct")), key=self._hp_of):
                room = self._max_hp(o) // 2 - self._hp_of(o)
                n = min(room, pool)
                if n > 0:
                    self._heal(o, n)
                    pool -= n
                    healed.append(f"{o['name']} +{n}")
            return self._out(f"{name} uses Preserve Life: " + (", ".join(healed) if healed else "nobody below half their hit points"))
        if key == "turn_undead":
            dc = 8 + char.proficiency_bonus + char.mod("wis")
            held = set()                                        # possessing ghosts that resist stay hidden in their bodies
            for o in [o for o in self.b["combatants"] if o.get("possessing") and (self._monster(o) or {}).get("type") == "undead"]:
                body = self._find_or_none(o["possessing"])         # a possessing ghost: turned out of the body first
                if not body or not body.get("pos") or not self._within(c, body, 30):
                    held.add(o["id"])
                elif self._saving_throw(o, "wis", dc, label="Turn Undead")["ok"]:
                    held.add(o["id"])
                    self._say(f"{o['name']} holds on inside {body['name']} (Turn Undead)")
                else:                                           # that failed save turns it as well: no second roll
                    held.add(o["id"])
                    self._say(self._release_possession(o, "turned out") or "")
                    self._effect_on(o, "Turn Undead", ["Frightened"], None, None, None, 10, name, {"turned": True}, None, c["id"], ends_on=["damage"])
                    self._say(f"{o['name']} is turned: it flees")
            near = [o for o in self.b["combatants"] if (self._monster(o) or {}).get("type") == "undead" and self._within(c, o, 30)
                    and not self._is_out(o) and not self._fx(o, "turn_immune") and o["id"] not in held]     # a crawling claw's Turn Immunity
            if not near:
                return self._out(f"{name} presents a holy symbol" + (": no undead within 30 ft" if not held else ""))
            lv = char.class_level("Cleric")                     # Destroy Undead: a failed save destroys undead up to this CR
            destroy = 4 if lv >= 17 else 3 if lv >= 14 else 2 if lv >= 11 else 1 if lv >= 8 else .5 if lv >= 5 else None
            S = self._strike(c, "Turn Undead", [o["id"] for o in near], mode="save",
                             sv={"ab": "wis", "dc": dc, "half": False, "conds": ["Frightened"], "rounds": 10, "ends_on": ["damage"],
                                 "note": "turned: flees", "mods": {"turned": True}, "destroy_cr": destroy}, parts=[])
            return self._run_r(S)
        if key == "breath_weapon":
            b = F.breath(char)
            if not b or not c.get("pos"):
                raise ServiceError("No breath weapon (or not on the map).")
            aim = point or self.b.get("aim") or (list(G.centre(tgt["pos"], tgt.get("span") or 1)) if tgt and tgt.get("pos") else None)
            tiles = G.area_for(b["area"], c["pos"], c.get("span") or 1, tuple(aim) if aim else None, *self._bounds())
            ids = [o["id"] for o in G.creatures_in(tiles, self.b["combatants"]) if o is not c and not self._is_out(o)]
            self._area_vfx(c, tiles, [[b["dice"], b["type"]]], b["area"].get("shape", ""), aim)
            return self._run_r(self._strike(c, "Breath Weapon", ids, mode="save", sv={"ab": b["save"], "dc": b["dc"], "half": True},
                                            parts=[[b["dice"], b["type"]]], magical=True, summary_targets=None))
        if key == "healing_hands":
            target = tgt or c
            n = roll(f"{char.proficiency_bonus}d4") if F.mpmm(char) else char.total_level     # MPMM: proficiency bonus d4s
            self._heal(target, n)
            return self._out(f"{name} heals {target['name']} with Healing Hands: +{n} HP")
        if key in ("wild_shape", "combat_wild_shape"):
            beast = bestiary.get(option or "Wolf|MM") or bestiary.get("Wolf|MM")
            c["form"] = {"monster": beast["id"], "hp": beast["hp"], "max_hp": beast["hp"], "name": beast["name"]}
            kind = beast["name"].lower()
            return self._out(f"{name} turns into {'an' if kind[:1] in 'aeiou' else 'a'} {kind} ({beast['hp']} HP)")
        return self._out(f"{name} uses {f['name']}")

    def _out(self, line: str) -> str:
        self._say(line)
        return line

    def _check_can_hide(self, c: dict):
        """5e: you can't hide from a creature that can see you clearly - a foe with a clear view (less than three-quarters
        cover, not heavily obscured, not invisible to it) stops the attempt before it costs anything (BG3 greys it out)."""
        if not c.get("pos"):
            return
        ter, base, zones = self._terrain(), self.b.get("map", {}).get("light", "bright"), self._live_zones()
        view = self._viewer(c)
        tiles = G.footprint(c["pos"], c.get("span") or 1)
        dim = any(V.light_at(ter, t, base, zones) in ("dim", "dark") for t in tiles)       # lightly obscured
        haze = any(V.obscured(t, zones) == "light" for t in tiles)
        char = self._sheet(c)
        skulker = (self._feat(c, "skulker") or self._mantle_hide(c)) and (dim or haze)     # Skulker, Nature's Mantle: lightly obscured is enough
        wild = bool(char and char.has_feature("Mask of the Wild")) and haze       # a wood elf in mist, rain, foliage
        small = bool(char and char.has_feature("Naturally Stealthy"))             # a lightfoot behind someone bigger
        for o in self.b["combatants"]:
            if not self._hostile(o, c) or not o.get("pos") or not self._can_act(o):
                continue
            if not V.can_see(ter, self._viewer(o), view, base_light=base, zones=zones) or self._cover_between(o, c) >= V.THREE_QUARTERS:
                continue
            if skulker or wild:
                continue
            if small:
                big = [(x["pos"], x.get("span") or 1) for x in self.b["combatants"] if x is not c and x is not o and x.get("pos")
                       and SIZES.index(self._size_of(x)) > SIZES.index(self._size_of(c))]
                if big and V.cover(V.terrain([]), o["pos"], o.get("span") or 1, c["pos"], c.get("span") or 1, big) >= V.HALF:
                    continue
            raise ServiceError(f"{o['name']} can see {c['name']} clearly: nowhere to hide (get behind cover, into darkness or out of sight).")

    def _hide_now(self, c: dict) -> str:
        seers = [o for o in self.b["combatants"] if self._hostile(o, c) and o.get("pos") and self._alive(o)]
        best = max([self._passive(o) for o in seers] or [0])
        total = self._check(c, "Stealth", dc=best)              # (Psi-Bolstered Knack may turn a failure round)
        if total >= best:
            self._effect_on(c, "Hidden", [], None, None, None, None, c["name"], {"hidden": total, "attacks_with": "adv", "ends_on": ["attack", "cast"]},
                            None, c["id"])
            return f"{c['name']} hides (Stealth {total})"
        return f"{c['name']} tries to hide but is spotted (Stealth {total} vs {best})"

    def end_form(self, cid: int):
        """Leave Wild Shape or Polymorph: back to the creature's own shape."""
        with self.lock:
            c = self._find(cid)
            if c.pop("form", None):
                self._commit(f"{c['name']} returns to its own shape")
