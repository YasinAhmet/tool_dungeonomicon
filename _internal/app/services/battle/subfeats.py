"""Subclass features of the later rounds, played in battle (the bar's items are in features.py's ACTIVE; classfeats.py hands over):

    Fighter, Echo Knight      Manifest Echo (a hittable token), attacks from its space, swapping places, Unleash Incarnation,
                              Shadow Martyr (a reaction before an attack), Reclaim Potential (temporary HP when it is destroyed)
    Barbarian, Path of Giant  Giant Stature (reach, size: rage_extras), Crushing Throw, Elemental Cleaver, Mighty Impel
    Rogue, Soulknife          Psionic Energy dice: Psi-Bolstered Knack, Homing Strikes, Psychic Teleportation
    Monk, Ascendant Dragon    Breath of the Dragon, Draconic Strike, Wings Unfurled, Aspect of the Wyrm
    Artificer, Alchemist      Experimental Elixirs, Restorative Reagents, Chemical Mastery
    Sorcerer, Storm Sorcery   Tempestuous Magic, Storm's Fury
"""
from typing import List, Optional

from ...rules import combat_feats as CF
from ...rules import spellcasting as SC
from ...rules.data import rules
from ..common import ServiceError
from . import conditions as K
from . import economy as EC
from . import features as F
from . import geometry as G
from .resolve import roll
from .standard import SIZES
from .subfeats_b import SUB_B_FAMILIES, SUB_B_FREE, SubFeatsBMixin       # Monster Slayer, Twilight, Spores, Vengeance, Fathomless, Open Hand
from .subfeats_c import SUB_C_FAMILIES, SUB_C_FREE, SubFeatsCMixin       # Trickery, Forge, Grave, Knowledge, Shadow, Drunken Master... (subfeats_c.py)
from .subfeats_d import SUB_D_FAMILIES, SUB_D_FREE, SubFeatsDMixin       # Paladin, Ranger, Rogue, Sorcerer, Warlock, Wizard, Artificer (subfeats_d.py)
from .racefeats import RACE_FAMILIES, RACE_FREE                          # Astral Spark, Hadozee Dodge, Built for Success (racefeats.py)

ECHO = "Manifest Echo"
ALL_CONDITIONS = ["Blinded", "Charmed", "Deafened", "Frightened", "Grappled", "Incapacitated", "Invisible", "Paralyzed", "Petrified",
                  "Poisoned", "Prone", "Restrained", "Stunned", "Unconscious"]
SUB_FAMILIES = {"echo_oa": "Echo opportunity attack", "shadow_martyr": "Shadow Martyr", "homing_strikes": "Homing Strikes", "storm_fury": "Storm's Fury"}
SUB_FAMILIES.update(SUB_B_FAMILIES)
SUB_FAMILIES.update(SUB_C_FAMILIES)
SUB_FAMILIES.update(SUB_D_FAMILIES)
SUB_FAMILIES.update(RACE_FAMILIES)
SUB_FREE = {"homing_strikes"} | SUB_B_FREE | SUB_C_FREE | SUB_D_FREE | RACE_FREE


class SubFeatsMixin(SubFeatsBMixin, SubFeatsCMixin, SubFeatsDMixin):
    # ------------------------------------------------------------------ Echo Knight
    def _ek_all(self, c: dict) -> List[dict]:
        return [o for o in self.b["combatants"] if (o.get("conjured") or {}).get("spell") == ECHO and o["conjured"].get("owner") == c["id"]]

    def _ek_echo(self, c: dict) -> Optional[dict]:
        """The echo of an Echo Knight, while it lasts (it ends when its knight is incapacitated)."""
        tok = next(iter(self._ek_all(c)), None)
        if tok is not None and K.incapacitated(self._conds(c)):
            self._ek_end(tok, f"{c['name']}'s echo fades (incapacitated)")
            return None
        return tok

    def _ek_end(self, tok: dict, line: str):
        self._vfx_unsummon(tok)
        if tok in self.b["combatants"]:
            self._take_out(tok)
        self._say(line)

    def _ek_reach_why(self, c: dict, char, tgt: Optional[dict], melee: bool) -> Optional[str]:
        """Why the echo's space can't strike the target (None: it can)."""
        tok = self._ek_echo(c)
        if tok is None or not tok.get("pos") or not c.get("pos"):
            return "No echo on the map"
        if not tgt or tgt is c or tgt is tok:
            return "Pick a target first."
        if not self._hostile(c, tgt):
            return f"Pick a foe, not {tgt['name']}."
        home = list(c["pos"])
        c["pos"] = list(tok["pos"])
        try:
            self._cf_weapon(c, char, tgt, False if melee else None)
        except ServiceError as e:
            return str(e)
        finally:
            c["pos"] = home
        return None

    def _ek_strike(self, c: dict, char, tgt: dict, label: str, melee: bool, pay: bool) -> str:
        """An attack made from the echo's space: the knight stands there while the attack resolves."""
        tok = self._ek_echo(c)
        home = list(c["pos"])
        c["pos"] = list(tok["pos"])
        try:
            w, atk = self._cf_weapon(c, char, tgt, False if melee else None)
            if pay:
                self._pay_attack(c, F.extra_attacks(char), f"{w['name']} (echo)")
            R = self._strike(c, f"{w['name']} ({label})", [tgt["id"]], mode="attack", atk=atk, magical=atk.get("magical", False))
            R["echo_home"] = home                               # resolve.py puts the knight back when the strike is over
            return self._run_r(R)
        except Exception:
            c["pos"] = home
            raise

    def _ek_manifest(self, c: dict, char, point) -> str:
        for old in self._ek_all(c):                             # a new echo replaces the old one
            self._ek_end(old, f"{c['name']}'s old echo fades")
        sp = {"name": ECHO, "duration": "Until destroyed", "level": 1, "classes": ["Fighter"]}
        tdef = {"name": "Echo", "move": 30, "hp": 1, "ac": 14 + char.proficiency_bonus, "span": c.get("span") or 1}
        tok = self._conjure_token(c, sp, tdef, {"point": point}, [], None)
        self._effect_on(tok, "Echo", [], None, None, None, None, c["name"], {"immune_cond": list(ALL_CONDITIONS)}, None, c["id"])
        return self._out(f"{c['name']} manifests an echo at {self._tile_label(tok['pos']) if tok.get('pos') else 'its side'} "
                         f"(AC {tdef['ac']}, 1 HP)")

    def _ek_destroyed(self, tok: dict):
        """The echo fell to damage: Reclaim Potential (15th level) gives its knight 2d6 + Constitution temporary hit points."""
        owner = self._find_or_none((tok.get("conjured") or {}).get("owner"))
        char = self._sheet(owner) if owner else None
        if not char or not F.sub_at(char, "Fighter", "Echo Knight", 15) or not self._alive(owner):
            return
        if not self._cf_left(owner, "Reclaim Potential", max(1, char.mod("con"))) or char.temp_hp > 0:
            return
        self._cf_use(owner, "Reclaim Potential")
        n = max(1, roll("2d6") + char.mod("con"))
        self._give_temp(owner, n)
        self._say(f"{owner['name']} absorbs the echo's magic: {n} temporary HP (Reclaim Potential)")

    # ------------------------------------------------------------------ hooks into classfeats.py
    def _sub_families(self, char) -> List[str]:
        out = []
        if F.sub_at(char, "Fighter", "Echo Knight", 3):
            out.append("echo_oa")
        if F.sub_at(char, "Fighter", "Echo Knight", 10):
            out.append("shadow_martyr")
        if F.sub_at(char, "Rogue", "Soulknife", 9):
            out.append("homing_strikes")
        if F.sub_at(char, "Sorcerer", "Storm Sorcery", 14):
            out.append("storm_fury")
        return out + self._subb_families(char) + self._subc_families(char) + self._subd_families(char) + self._race_families(char)

    def _sub_why(self, c: dict, char, key: str, f: dict, tgt: Optional[dict], option, menu: bool, point) -> Optional[str]:
        """Why one of these features can't be used now (None: it can, or it isn't one of these)."""
        why = self._subb_why(c, char, key, f, tgt, option, menu, point)       # subfeats_b.py
        if why:
            return why
        why = self._subc_why(c, char, key, f, tgt, option, menu, point)       # subfeats_c.py
        if why:
            return why
        why = self._subd_why(c, char, key, f, tgt, option, menu, point)       # subfeats_d.py
        if why:
            return why
        why = self._race_why(c, char, key, f, tgt, option, menu, point)       # racefeats.py
        if why:
            return why
        t = c.get("turn") or {}
        econ = self._economy_on()
        when = f.get("when")
        if when == "echo" and self._ek_echo(c) is None:
            return "No echo on the map"
        if when == "step_wind" and econ and not t.get("step_wind"):
            return "Use Step of the Wind first"
        if when == "wyrm" and not self._fx(c, "wyrm_fright"):
            return "Only under the Frightful Presence aura"
        if when == "leveled_spell" and econ and not any(int(lv) >= 1 for _cost, lv in t.get("spells") or []):
            return "Cast a spell of 1st level or higher first"
        if key == "echo_move":
            tok = self._ek_echo(c)
            if not self._cf_turn_free(c, "echo_move"):
                return "The echo already moved this turn"
            if not menu:
                if not point:
                    return "Pick where it goes."
                x, y = int(point[0]), int(point[1])
                if tok.get("pos") and max(abs(x - tok["pos"][0]), abs(y - tok["pos"][1])) * 5 > 30:
                    return "It moves up to 30 ft."
                if not self._tile_ok(tok, x, y):
                    return "That tile is taken or off the map."
        if key == "echo_swap" and econ:
            return EC.why_not(t, "move:15")
        if key in ("echo_attack", "unleash_incarnation"):
            if key == "unleash_incarnation" and econ and not t.get("attacked"):
                return "Take the Attack action first"
            if not menu:
                return self._ek_reach_why(c, char, tgt, melee=key == "unleash_incarnation")
        if key == "cleaver_type" and not self._fx(c, "cleaver"):
            return "No infused weapon (rage with a weapon in hand)"
        if key == "mighty_impel":
            grand = F.sub_at(char, "Barbarian", "Path of the Giant", 14)
            if not menu:
                if not tgt or tgt is c:
                    return "Pick the creature to move first."
                if SIZES.index(self._size_of(tgt)) > SIZES.index("Large" if grand else "Medium"):
                    return f"{tgt['name']} is too big (Medium or smaller" + (", Large at 14th level)" if not grand else ")")
                if c.get("pos") and tgt.get("pos") and self._dist(c, tgt) > max(5, self._reach(c)):
                    return f"{tgt['name']} is out of your reach"
                if not point:
                    return "Pick where it lands."
                x, y = int(point[0]), int(point[1])
                if G.distance_ft(c["pos"], c.get("span") or 1, [x, y], 1) > 30:
                    return "Too far (up to 30 ft)"
                if not self._tile_ok(tgt, x, y):
                    return "That tile is taken or off the map."
        if key in ("psychic_teleport", "psionic_regain"):
            left = self._cf_left(c, "Psionic Energy", F.psionic_dice(char))
            if key == "psychic_teleport":
                if left <= 0:
                    return "No Psionic Energy die left"
                if not menu and not point:
                    return "Pick where to land."
            elif left >= F.psionic_dice(char):
                return "No expended Psionic Energy die"
        if key in ("dragon_breath_cone", "dragon_breath_line") and not menu and econ:
            return self._pay(c, "attack", f["name"], check_only=True)
        if key == "wyrm_fright" and not menu and (not tgt or not self._hostile(c, tgt)):
            return "Pick a foe in the aura."
        if key == "elixir_drink":
            if not F.elixir_options(char):
                return "No elixir left"
            if not menu and option not in [o["value"] for o in F.elixir_options(char)]:
                return "Pick an elixir."
        if key == "elixir_make" and not menu:
            if option not in list(F.ELIXIRS.values()):
                return "Pick the effect."
        if key == "elixir_make" and not self._free_slot(char):
            return "No spell slot left"
        if key == "mastery_heal" and not menu and tgt is not None and self._dead(tgt):
            return f"{tgt['name']} is dead"
        return None

    @staticmethod
    def _free_slot(char) -> Optional[int]:
        left = SC.slots_remaining(char)
        levels = sorted(int(k) for k, v in left.items() if k != SC.PACT_KEY and v > 0)
        return levels[0] if levels else None

    def _sub_feature(self, c: dict, char, key: str, f: dict, tgt: Optional[dict], option, point) -> Optional[str]:
        """Plays one of these features (None: not one of these, or it only noted something)."""
        name = c["name"]
        t = c.get("turn")
        done = self._subb_feature(c, char, key, f, tgt, option, point)       # subfeats_b.py
        if done is not None:
            return done
        done = self._subc_feature(c, char, key, f, tgt, option, point)       # subfeats_c.py
        if done is not None:
            return done
        done = self._subd_feature(c, char, key, f, tgt, option, point)       # subfeats_d.py
        if done is not None:
            return done
        done = self._race_feature(c, char, key, f, tgt, option, point)       # racefeats.py
        if done is not None:
            return done
        if key == "step_of_the_wind":
            if t is not None:
                t["step_wind"] = True
            return None
        if key == "manifest_echo":
            return self._ek_manifest(c, char, point)
        if key == "echo_move":
            tok = self._ek_echo(c)
            self._move_token(tok, point)
            self._once_per_turn(c, "echo_move")
            return self._out(f"{name} moves the echo to {self._tile_label(tok['pos'])}")
        if key == "echo_swap":
            tok = self._ek_echo(c)
            EC.spend(t, "move:15")
            a, b = list(c["pos"]), list(tok["pos"])
            self._vfx("blink", id=c["id"], at=a, to=b)
            self._vfx("blink", id=tok["id"], at=b, to=a)
            c["pos"], tok["pos"] = b, a
            self._follow_zones(c)
            return self._out(f"{name} swaps places with the echo (15 ft of movement)")
        if key == "echo_dismiss":
            self._ek_end(self._ek_echo(c), f"{name} dismisses the echo")
            return f"{name} dismisses the echo"
        if key in ("echo_attack", "unleash_incarnation"):
            if key == "unleash_incarnation":
                return self._ek_strike(c, char, tgt, "Unleash Incarnation", True, False)
            return self._ek_strike(c, char, tgt, "from the echo", False, True)
        if key == "cleaver_type":
            kind = option if option in F.ELEMENTS else "fire"
            for e, _v in self._fx(c, "cleaver"):
                e["mods"]["cleaver"] = kind
            return self._out(f"{name}'s infused weapon turns {kind} (Elemental Cleaver)")
        if key == "mighty_impel":
            return self._giant_impel(c, char, tgt, point)
        if key == "psionic_regain":
            res = char.d["resources"]
            res["feature:Psionic Energy"] = max(0, int(res.get("feature:Psionic Energy") or 0) - 1)
            char.save()
            return self._out(f"{name} regains a Psionic Energy die")
        if key == "psychic_teleport":
            return self._psychic_teleport(c, char, point)
        if key in ("dragon_breath_cone", "dragon_breath_line"):
            return self._dragon_breath(c, char, key, f, tgt, option, point)
        if key == "wings_unfurled":
            self._effect_on(c, "Wings Unfurled", [], None, None, None, None, name, {"fly": char.speed}, None, c["id"],
                            until={"end": c["id"], "skip": 0})
            return self._out(f"{name} unfurls spectral wings (fly {char.speed} ft until the end of the turn)")
        if key == "aspect_wyrm":
            return self._aspect_wyrm(c, char, tgt, option)
        if key == "wyrm_fright":
            return self._wyrm_fright(c, char, tgt)
        if key == "elixir_drink":
            return self._elixir_drink(c, char, tgt or c, option)
        if key == "elixir_make":
            lvl = self._free_slot(char)
            used = char.d["slots_used"]
            used[str(lvl)] = int(used.get(str(lvl)) or 0) + 1
            char.d.setdefault("elixirs", []).append(option)
            char.save()
            return self._out(f"{name} brews an elixir of {option} (a level {lvl} slot)")
        if key in ("reagent_lesser", "mastery_greater", "mastery_heal"):
            spell = {"reagent_lesser": "Lesser Restoration", "mastery_greater": "Greater Restoration", "mastery_heal": "Heal"}[key]
            sp = rules.spell(spell)
            EC.refund(t, "action")                              # the spell pays its own casting time
            ab = char.mod("int")
            self._say(f"{name} uses {f['name']}")
            return self._cast_on(c, sp, tgt or c, slot_level=sp["level"], caster_level=char.total_level, mod=ab,
                                 attack_bonus=char.proficiency_bonus + ab, dc=self._spell_dc(c), adv=None, paid=True)
        if key == "tempestuous_magic":
            if t is not None:
                t["move"] = int(t.get("move", 0)) + 10
                t["no_oa_ft"] = int(t.get("no_oa_ft") or 0) + 10
            return self._out(f"{name} is carried by whirling gusts: 10 ft of movement that provokes no opportunity attacks")
        return None

    # ---- Path of the Giant
    def _giant_impel(self, c: dict, char, tgt: dict, point) -> str:
        x, y = int(point[0]), int(point[1])
        dc = 8 + char.proficiency_bonus + char.mod("str")
        if self._hostile(c, tgt):                               # an ally is a willing passenger
            res = self._saving_throw(tgt, "str", dc, label="Mighty Impel")
            self._say(f"{tgt['name']} STR save vs Mighty Impel (DC {dc}): {res['total']} — " + ("resists" if res["ok"] else "fails"))
            if res["ok"]:
                return f"{tgt['name']} resists being moved"
        self._vfx("blink", id=tgt["id"], at=tgt.get("pos"), to=[x, y])
        tgt["pos"] = [x, y]
        self._follow_zones(tgt)
        return self._out(f"{c['name']} hurls {tgt['name']} to {self._tile_label(tgt['pos'])} (Mighty Impel)")

    # ---- Soulknife
    def _psychic_teleport(self, c: dict, char, point) -> str:
        die = F.psionic_die(char)
        n = roll("1" + die)
        self._cf_use(c, "Psionic Energy")
        reach = 10 * n
        x, y = int(point[0]), int(point[1])
        span = c.get("span") or 1
        spot = None
        if c.get("pos") and G.distance_ft(c["pos"], span, [x, y], span) <= reach and self._tile_ok(c, x, y):
            spot = [x, y]
        elif c.get("pos"):                                      # too far: the free tile within the roll that is closest to the one picked
            k = reach // 5
            cx, cy = c["pos"]
            cand = [[cx + dx, cy + dy] for dx in range(-k, k + 1) for dy in range(-k, k + 1) if self._tile_ok(c, cx + dx, cy + dy)]
            cand = [p for p in cand if G.distance_ft(c["pos"], span, p, span) <= reach]
            spot = min(cand, key=lambda p: (max(abs(p[0] - x), abs(p[1] - y)), abs(p[0] - x) + abs(p[1] - y)), default=None)
        if spot is None:
            return self._out(f"{c['name']} throws a psychic blade (d{die[1:]}: {n}, {reach} ft) but has nowhere to land")
        self._cf_teleport(c, spot)
        return self._out(f"{c['name']} throws a psychic blade and teleports to {self._tile_label(c['pos'])} "
                         f"({die} → {n}: up to {reach} ft; Psychic Teleportation)")

    def _sk_check_boost(self, c: dict, skill: str, total: int, dc: int) -> int:
        """Psi-Bolstered Knack: a failed check with a skill the Soulknife is proficient in; the die is expended only if it turns the failure around."""
        char = self._sheet(c)
        if not char or c.get("form") or not F.sub_at(char, "Rogue", "Soulknife", 3) or skill not in char.d["proficiencies"]["skills"]:
            return 0
        if not self._cf_left(c, "Psionic Energy", F.psionic_dice(char)):
            return 0
        n = roll("1" + F.psionic_die(char))
        if total + n < dc:
            self._say(f"{c['name']}'s Psi-Bolstered Knack: +{n} is not enough (the die is kept)")
            return 0
        self._cf_use(c, "Psionic Energy")
        self._say(f"{c['name']}'s Psi-Bolstered Knack: +{n} ({skill} {total} → {total + n} vs DC {dc})")
        return n

    def _sub_check_boost(self, c: dict, skill: str, total: int, dc: int) -> int:
        return self._sk_check_boost(c, skill, total, dc)

    # ---- Way of the Ascendant Dragon
    def _dragon_breath(self, c: dict, char, key: str, f: dict, tgt: Optional[dict], option, point) -> str:
        if not c.get("pos"):
            raise ServiceError("Not on the map.")
        dtype = option if option in F.DRAGON_TYPES else "fire"
        die = F.martial_die(char) or "1d4"
        n = 3 if char.class_level("Monk") >= 11 else 2
        parts = [[f"{n}d{die.split('d')[1]}", dtype]]
        self._pay_attack(c, F.extra_attacks(char), f["name"])
        aim = point or self.b.get("aim") or (list(G.centre(tgt["pos"], tgt.get("span") or 1)) if tgt and tgt.get("pos") else None)
        tiles = G.area_for(f["area"], c["pos"], c.get("span") or 1, tuple(aim) if aim else None, *self._bounds())
        ids = [o["id"] for o in G.creatures_in(tiles, self.b["combatants"]) if o is not c and not self._is_out(o)]
        self._area_vfx(c, tiles, parts, f["area"].get("shape", ""), aim)
        return self._run_r(self._strike(c, "Breath of the Dragon", ids, mode="save", magical=True, parts=parts, summary_targets=None,
                                        sv={"ab": "dex", "dc": F.ki_dc(char), "half": True}))

    def _wyrm_fright(self, c: dict, char, tgt: dict) -> str:
        sv = {"ab": "wis", "dc": F.ki_dc(char), "half": False, "conds": ["Frightened"], "repeat": "end", "rounds": 10}
        return self._run_r(self._strike(c, "Frightful Presence (Aspect of the Wyrm)", [tgt["id"]], mode="save", magical=True, sv=sv, parts=[]))

    def _aspect_wyrm(self, c: dict, char, tgt: Optional[dict], option) -> str:
        name = c["name"]
        for e in [e for e in c.get("effects") or [] if e["name"] == "Aspect of the Wyrm"]:
            self._effect_off(c, e, "a new aspect")
        if option in F.DRAGON_TYPES:
            self._effect_on(c, "Aspect of the Wyrm", [], None, None, None, 10, name, {"resist": [option], "aura_ft": 10}, None, c["id"])
            return self._out(f"{name} radiates draconic power: resistance to {option} for you and your allies within 10 ft")
        self._effect_on(c, "Aspect of the Wyrm", [], None, None, None, 10, name, {"wyrm_fright": True, "aura_ft": 10}, None, c["id"])
        line = self._out(f"{name} radiates a frightful draconic presence")
        if tgt and tgt is not c and self._hostile(c, tgt) and self._within(c, tgt, 10):
            return self._wyrm_fright(c, char, tgt) or line
        return line

    # ---- Alchemist
    def _elixir_drink(self, c: dict, char, who: dict, option) -> str:
        if str(option).startswith("flask:"):
            i = int(str(option).split(":")[1])
            fx = char.d["elixirs"].pop(i)
            char.save()
        else:
            self._cf_use(c, "Experimental Elixir")
            fx = F.ELIXIRS[roll("1d6")]
        name = c["name"]
        ab = char.mod("int")
        bits = []
        if fx == "Healing":
            n = roll("2d4") + ab
            self._heal(who, max(1, n))
            bits.append(f"+{max(1, n)} HP")
        elif fx == "Swiftness":
            self._effect_on(who, "Elixir of Swiftness", [], None, None, None, 600, name, {"speed": 10}, None, c["id"])
            bits.append("+10 ft speed for an hour")
        elif fx == "Resilience":
            self._effect_on(who, "Elixir of Resilience", [], None, None, None, 100, name, {"ac": 1}, None, c["id"])
            bits.append("+1 AC for 10 minutes")
        elif fx == "Boldness":
            self._effect_on(who, "Elixir of Boldness", [], None, None, None, 10, name, {"attack": "1d4", "save": "1d4"}, None, c["id"])
            bits.append("+1d4 to attacks and saves for a minute")
        elif fx == "Flight":
            self._effect_on(who, "Elixir of Flight", [], None, None, None, 100, name, {"fly": 10}, None, c["id"])
            bits.append("a flying speed of 10 ft for 10 minutes")
        else:
            self._effect_on(who, "Elixir of Transformation", [], None, None, None, 100, name, {"alter_self": True}, None, c["id"])
            bits.append("transformed as if by alter self (10 minutes)")
        if F.sub_at(char, "Artificer", "Alchemist", 9):         # Restorative Reagents
            tmp = max(1, roll("2d6") + ab)
            self._give_temp(who, tmp)
            bits.append(f"{tmp} temporary HP (Restorative Reagents)")
        return self._out(f"{who['name']} drinks the elixir of {fx.lower()}" + (f" from {name}" if who is not c else "") + ": " + ", ".join(bits))

    # ------------------------------------------------------------------ weapon and hit hooks
    def _sub_weapon_atk(self, att: dict, w: dict, atk: dict) -> dict:
        """Giant Stature's reach, the infused weapon of Elemental Cleaver, Draconic Strike: a weapon attack changed."""
        char = self._sheet(att)
        if not char or att.get("form"):
            return atk
        atk = self._subc_weapon_atk(att, w, atk)                     # One with the Blade, the astral arms (subfeats_c.py)
        if not w.get("ranged"):
            far = sum(int(v) for _e, v in self._fx(att, "giant_reach")) + self._race_reach(att, char)      # + a bugbear's Long-Limbed (racefeats.py)
            if far:
                atk["reach"] = atk.get("reach", 5) + far
        for e, kind in self._fx(att, "cleaver"):
            if (e.get("mods") or {}).get("cleaver_weapon") == w.get("name") and "unarmed" not in (w.get("props") or []):
                atk["parts"] = [[atk["parts"][0][0], kind]] + [list(p) for p in atk["parts"][1:]] + [[e["mods"].get("cleaver_dice") or "1d6", kind]]
                if not w.get("ranged") and not (atk.get("thrown") and (atk.get("long") or 0) >= 60):
                    atk.update(thrown=True, normal=20, long=60)            # it can be thrown, and comes back to the hand
                    atk["props"] = list(atk.get("props") or []) + ["thrown"]
                break
        if "unarmed" in (w.get("props") or []) and F.sub_at(char, "Monk", "Way of the Ascendant Dragon", 3):
            kind = CF.is_on(char, "draconic_strike")
            if kind and kind != "bludgeoning":
                atk["parts"] = [[atk["parts"][0][0], kind]] + [list(p) for p in atk["parts"][1:]]
        return atk

    def _sub_hit_parts(self, att: dict, tgt: dict, R: dict, char) -> list:
        """[(dice, type, label)] added to a hit: Crushing Throw (the Rage damage on a Strength thrown weapon)."""
        a = R.get("atk") or {}
        out = []
        self._subb_hit(att, tgt, R, char)                            # Slayer's Counter, Relentless Avenger (subfeats_b.py)
        out += self._subc_hit_parts(att, tgt, R, char)               # Empowered Arms, Call the Hunt, Ferocious Charger (subfeats_c.py)
        out += [tuple(p) for p in self._subd_hit(att, tgt, R, char)]  # Mortal Bulwark, Rend Mind (subfeats_d.py)
        out += self._nf_hit_parts(att, tgt, R, char)                 # Power from Pain (newfeats.py)
        if a.get("weapon") and not a.get("melee") and a.get("thrown") and a.get("str_based") and self._raging(att) \
                and F.sub_at(char, "Barbarian", "Path of the Giant", 3):
            out.append((F.rage_damage(char), (a.get("parts") or [["", ""]])[0][1] or "", "Crushing Throw"))
        return out

    # ------------------------------------------------------------------ reactions
    def _sub_eligible(self, out: list, window: str, R: dict, att: Optional[dict], tgt: Optional[dict], ctx: dict):
        cur = R.get("cur") or {}
        a = R.get("atk") or {}
        self._subb_eligible(out, window, R, att, tgt, ctx)      # subfeats_b.py
        self._subc_eligible(out, window, R, att, tgt, ctx)      # subfeats_c.py
        self._subd_eligible(out, window, R, att, tgt, ctx)      # subfeats_d.py
        self._race_eligible(out, window, R, att, tgt, ctx)      # racefeats.py
        if window == "declared" and att and tgt and self._hostile(att, tgt):
            for o in self.b["combatants"]:                      # Shadow Martyr: the echo takes the attack meant for someone else
                oc = self._sheet(o)
                if not oc or o.get("form") or o is tgt or not F.sub_at(oc, "Fighter", "Echo Knight", 10) or not self._may_react(o) \
                        or self._hostile(o, tgt) or not self._hostile(o, att):
                    continue
                tok = self._ek_echo(o)
                if tok is None or tok is tgt or not tgt.get("pos") or not self._sees(o, tgt) \
                        or not self._cf_left(o, "Shadow Martyr", 1, "short") or self._ek_spot(tok, tgt) is None:
                    continue
                self._cf_offer(out, o, "reaction", [{"key": "shadow_martyr", "label": f"Shadow Martyr: the echo takes the attack for {tgt['name']}",
                                                     "detail": ""}], f"{att['name']} attacks {tgt['name']}. {o['name']}: send the echo in front of it?")
        elif window == "leave" and R.get("echo_oa"):
            mover = self._find_or_none(ctx.get("mover"))
            for oid in R["echo_oa"]:
                o = self._find_or_none(oid)
                if mover and o and self._ek_echo(o) is not None and self._may_react(o):
                    self._cf_offer(out, o, "reaction", [{"key": "echo_oa", "label": f"Opportunity attack on {mover['name']} from the echo", "detail": ""}],
                                   f"{mover['name']} is leaving {o['name']}'s echo. Opportunity attack from its space?")
        elif window == "missed" and att and tgt and a.get("psychic_blade") and cur.get("kept") != 1 and not cur.get("homing"):
            ac_ = self._sheet(att)
            need = cur.get("ac", 0) + cur.get("ac_extra", 0) - cur.get("total", 0)
            if ac_ and not att.get("form") and F.sub_at(ac_, "Rogue", "Soulknife", 9) and 0 < need <= int(F.psionic_die(ac_)[1:]) \
                    and self._cf_left(att, "Psionic Energy", F.psionic_dice(ac_)):
                self._cf_offer(out, att, "free", [{"key": "homing_strikes", "label": f"Homing Strikes (+{F.psionic_die(ac_)}, kept if it still misses)",
                                                   "detail": f"{cur.get('total')} vs AC {cur.get('ac')}"}],
                               f"{att['name']} misses {tgt['name']} ({cur.get('total')} vs AC {cur.get('ac')}). Add something?")
        elif window == "after_damage" and att and tgt and tgt is not att and self._alive(tgt) and self._alive(att):
            tc = self._sheet(tgt)
            if tc and not tgt.get("form") and F.sub_at(tc, "Sorcerer", "Storm Sorcery", 14) and R.get("mode") == "attack" and a.get("melee") \
                    and self._may_react(tgt):
                self._cf_offer(out, tgt, "reaction", [{"key": "storm_fury", "label": f"Storm's Fury on {att['name']} "
                                                       f"({tc.class_level('Sorcerer')} lightning, Strength save or pushed 20 ft)", "detail": ""}],
                               f"{att['name']} hit {tgt['name']} in melee. Storm's Fury?", "after_damage")

    def _ek_spot(self, tok: dict, tgt: dict) -> Optional[list]:
        """A free tile within 5 ft of the creature for the echo to teleport to."""
        x0, y0, x1, y1 = G.box(tgt["pos"], tgt.get("span") or 1)
        ring = [(x, y) for x in range(x0 - 1, x1 + 2) for y in range(y0 - 1, y1 + 2) if not (x0 <= x <= x1 and y0 <= y <= y1)]
        near = [list(p) for p in sorted(ring, key=lambda p: (abs(p[0] - tok["pos"][0]) + abs(p[1] - tok["pos"][1]), p)) if self._tile_ok(tok, *p)]
        return near[0] if near else None

    def _echo_threats(self, mover: dict, here, there) -> List[int]:
        """The Echo Knights whose echo the mover is leaving the reach (5 ft) of with this step: they may take an opportunity attack from the echo."""
        out = []
        for tok in self.b["combatants"]:
            if (tok.get("conjured") or {}).get("spell") != ECHO or not tok.get("pos"):
                continue
            owner = self._find_or_none(tok["conjured"].get("owner"))
            oc = self._sheet(owner) if owner else None
            if not oc or owner is mover or not self._hostile(owner, mover) or not F.sub_at(oc, "Fighter", "Echo Knight", 3) \
                    or not self._may_react(owner) or not self._sees(owner, mover) or K.incapacitated(self._conds(owner)):
                continue
            eb = G.box(tok["pos"], tok.get("span") or 1)
            if 5 * G.gap(eb, here) <= 5 < 5 * G.gap(eb, there) and owner["id"] not in out:
                out.append(owner["id"])
        return out

    def _sub_react(self, window: str, R: dict, reactor: dict, fam: str, arg: str, ctx: dict) -> bool:
        """What these features' reactions do (False: not one of them)."""
        cur = R.setdefault("cur", {})
        char = self._sheet(reactor)
        name = reactor["name"]
        att = self._find_or_none(ctx.get("attacker") or R.get("actor"))
        if self._subb_react(window, R, reactor, fam, arg, ctx):  # subfeats_b.py
            return True
        if self._subc_react(window, R, reactor, fam, arg, ctx):  # subfeats_c.py
            return True
        if self._subd_react(window, R, reactor, fam, arg, ctx):  # subfeats_d.py
            return True
        if self._race_react(window, R, reactor, fam, arg, ctx):  # racefeats.py
            return True
        if fam == "shadow_martyr":
            tok = self._ek_echo(reactor)
            tgt = self._find_or_none(R["targets"][R["ti"]]) if R.get("ti", 0) < len(R.get("targets") or []) else None
            if tok is None or tgt is None:
                return True
            self._cf_use(reactor, "Shadow Martyr", "short")
            spot = self._ek_spot(tok, tgt)
            if spot:
                self._vfx("blink", id=tok["id"], at=tok.get("pos"), to=spot)
                tok["pos"] = spot
            R["targets"][R["ti"]] = tok["id"]
            self._line(R, f"{name}'s echo throws itself in front of {tgt['name']}: the attack is made against the echo", "Shadow Martyr")
            return True
        if fam == "echo_oa":
            mover = self._find_or_none(ctx.get("mover"))
            tok = self._ek_echo(reactor)
            if mover is None or tok is None or not reactor.get("pos"):
                return True
            home = list(reactor["pos"])
            reactor["pos"] = list(tok["pos"])
            child = self._opportunity_strike(reactor, mover)
            if child is None:
                reactor["pos"] = home
                return True
            child["atk"]["opportunity"] = True
            child["echo_home"] = home
            self._stack().append(child)
            return True
        if fam == "homing_strikes":
            cur["homing"] = True
            n = roll("1" + F.psionic_die(char))
            ac = int(cur.get("ac") or 0) + int(cur.get("ac_extra") or 0)
            if int(cur.get("total") or 0) + n >= ac:
                self._cf_use(reactor, "Psionic Energy")
                cur["total"] = int(cur.get("total") or 0) + n
                self._line(R, f"{name}'s Homing Strikes: +{n} → {cur['total']} (a Psionic Energy die spent)", "Homing Strikes")
            else:
                self._line(R, f"{name}'s Homing Strikes: +{n} is not enough, the die is kept", "Homing Strikes")
            return True
        if fam == "storm_fury" and att:
            lvl = char.class_level("Sorcerer")
            self._line(R, "Storm's Fury: " + self._deal(att, [[lvl, "lightning"]], by=reactor, label="Storm's Fury"), "Storm's Fury")
            self._stack().append(self._strike(reactor, "Storm's Fury (push)", [att["id"]], mode="save", magical=True, spell=True, parts=[],
                                              sv={"ab": "str", "dc": self._spell_dc(reactor), "half": False, "push": 20}))
            return True
        return False

    def _sub_turn_end(self, c: dict):
        """The echo is destroyed when it is more than 30 ft from its knight at the end of the knight's turn."""
        self._subc_turn_end(c)                                  # a Shadow monk's cloak (subfeats_c.py)
        self._subd_turn_end(c)                                  # Protective Spirit (subfeats_d.py)
        self._race_turn_end(c)                                  # Feline Agility (racefeats.py)
        for tok in self._ek_all(c):
            if self._ek_echo(c) is None:
                return
            if c.get("pos") and tok.get("pos") and self._dist(c, tok) > 30:
                self._ek_end(tok, f"{c['name']}'s echo drifts too far away and is destroyed")

    def _sub_killed(self, c: dict):
        """A creature dropped to 0: an echo that fell to damage gives Reclaim Potential."""
        self._subc_killed(c)                                    # Cauterizing Flames (subfeats_c.py)
        if (c.get("conjured") or {}).get("spell") == ECHO:
            self._ek_destroyed(c)
