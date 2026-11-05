"""Targets and aim points, the numbers spells and effects change (AC, saves, attack bonuses) and concentration."""
from typing import List, Optional

from ...rules import engine as E
from ...rules.dice import roll_dice
from ...rules.monsters import ability_mod
from ..common import ServiceError
from . import combat_rules as CR
from . import conditions as K
from . import spell_effects as X


class TargetingMixin:
    # ------------------------------------------------------------------ targets and aim points
    def set_target(self, cid: Optional[int], add: bool = False):
        """The creature the next attack is aimed at (None clears; picking it again clears too). `add`: shift-click, one more target
        for spells that can reach several creatures (Bless, Mass Cure Wounds...); the first one picked is the main target."""
        with self.lock:
            picked = list(self.b.get("targets") or [])
            if cid is None:
                picked = []
            else:
                self._find(cid)
                if add:
                    picked = [x for x in picked if x != cid] if cid in picked else picked + [cid]
                else:
                    picked = [] if picked == [cid] else [cid]
            self.b["targets"] = picked
            self.b["target"] = picked[0] if picked else None
            self._commit()

    def set_aim(self, point: Optional[List[float]]):
        """A point on the map (tile units, floats) that area spells are aimed at; None clears it."""
        with self.lock:
            self.b["aim"] = [float(point[0]), float(point[1])] if point else None
            self._commit()

    def _selected(self, tgt: dict) -> list:
        """The targets a spell that can reach several creatures goes to: everyone picked, the main target first."""
        ids = self.b.get("targets") or []
        if tgt["id"] not in ids or len(ids) < 2:
            return [tgt]
        by = {c["id"]: c for c in self.b["combatants"]}
        return [by[i] for i in ids if i in by]

    def _target(self, cid: Optional[int] = None) -> dict:
        cid = cid or self.b.get("target")
        if not cid:
            raise ServiceError("Right-click a creature to pick a target first.")
        c = self._find(cid)
        if c["kind"] != "pc" and c["hp"] <= 0:
            raise ServiceError(f"{c['name']} is down.")
        if c.get("conjured") and not c["conjured"].get("hittable"):     # Spiritual Weapon, Guardian of Faith: a spell's effect
            raise ServiceError(f"{c['name']} isn't a creature to attack.")
        return c

    # ---- numbers that spells and effects change
    def _fx(self, c: Optional[dict], key: str):
        return self._fxs(c, key) if c else []

    def _dex_mod(self, c: dict) -> int:
        return self._ability(c, "dex")

    def _ac_of(self, c: dict) -> int:
        char = self._char(c["character"]) if c["kind"] == "pc" else None
        ac = char.armor_class()[0] if char else c["ac"]
        if c.get("form"):
            ac = int((self._monster(c) or {}).get("ac") or ac)
            if char and char.has_feature("Circle Forms"):
                ac = max(ac, 13 + char.mod("wis"))             # Circle of the Moon: 13 + Wisdom in a beast shape when better
        elif char and self._feat(c, "dual_wielder") and len([a for a in char.attacks() if not a.get("ranged") and "unarmed" not in (a.get("props") or [])]) >= 2:
            ac += 1
        for _e, base in self._fx(c, "ac_base"):
            ac = max(ac, base + self._dex_mod(c))
        for _e, floor in self._fx(c, "ac_min"):
            ac = max(ac, floor)
        return ac + sum(int(v) for _e, v in self._fx(c, "ac"))

    def _mod_roll(self, c: Optional[dict], key: str, chips: Optional[list] = None):
        """Dice that effects add to (or take from) a creature's rolls, e.g. Bless +1d4. Returns (total, ' +3 (Bless)').
        Each one shows on the maps (its badge blinks) and, with `chips`, is listed there for the d20 on screen."""
        total, bits = 0, []
        for e, dice in self._fx(c, key):
            sign = -1 if str(dice).startswith("-") else 1
            try:
                n = sign * int(roll_dice(str(dice).lstrip("+-")).total)
            except Exception:  # noqa: BLE001
                continue
            total += n
            bits.append(f"{n:+d} {e['name']}")
            self._vfx("tell", id=c["id"], name=e["name"], amt=n)
            if chips is not None:
                chips.append([e["name"], n])
        return total, (" (" + ", ".join(bits) + ")" if bits else "")

    def _save_bonus(self, c: dict, ab: str) -> int:
        if c["kind"] == "pc":
            char = self._char(c["character"])
            if char:
                st = char.saving_throws()[ab]
                if (self._fx(c, "save_prof_all") or any(ab in v for _e, v in self._fx(c, "save_prof"))) and not st.get("proficient"):
                    return st["bonus"] + char.proficiency_bonus
                return st["bonus"]
        m = self._monster(c)
        return CR.monster_save(m["saves"], ab, ability_mod(m, ab)) if m else 0

    def _save_roll(self, c: dict, ab: str, dc: Optional[int] = None):
        """A saving throw of `c`: (total, natural d20, note about effects such as Bless)."""
        res = self._saving_throw(c, ab, dc if dc is not None else 10)
        return res["total"], res["kept"], res["note"]

    def _d20(self, bonus: int, adv: Optional[str] = None):
        adv = adv if adv in ("adv", "dis") else None
        total, rolls = E.roll_d20(bonus, adv, self.rng)
        kept = max(rolls) if adv == "adv" else min(rolls) if adv == "dis" else rolls[0]
        return total, kept

    def _cond(self, c: dict, cond: str, on: bool, keep_conc: bool = False):
        if c["kind"] == "pc":
            char = self._char(c["character"])
            if char and (cond in char.conditions) == on:
                return
            self.chars.set_condition(c["character"], cond, on)
            self._vfx("cond", id=c["id"], name=cond, on=on)
        elif on and cond not in c["conditions"]:
            c["conditions"].append(cond)
            self._vfx("cond", id=c["id"], name=cond, on=True)       # its icon pops over the token, then sits as a badge
        elif not on and cond in c["conditions"]:
            c["conditions"].remove(cond)
            self._vfx("cond", id=c["id"], name=cond, on=False)
        if on and not keep_conc and c.get("concentrating") and K.incapacitated([cond]):
            self._drop_conc(c, cond.lower())                   # an incapacitated creature can't hold a spell (PHB ch. 10)

    def _hp_of(self, c: dict) -> int:
        if c["kind"] == "pc":
            char = self._peek(c)
            return char.current_hp if char else 0
        return c["hp"]

    @staticmethod
    def _lose_hp(c: dict, amount: int):
        """Damage to a creature that isn't a player character: temporary hit points go first."""
        soak = min(amount, c.get("temp_hp") or 0)
        c["temp_hp"] = (c.get("temp_hp") or 0) - soak
        c["hp"] = max(0, c["hp"] - (amount - soak))

    def _deal(self, tgt: dict, parts, crit: bool = False, factor: float = 1.0, by: Optional[dict] = None, label: str = "",
              magical: bool = True, spell: bool = False) -> str:
        """Hurt the target. `parts` are [(dice, type)] to roll, or [(amount, type)] already rolled (one roll for an area)."""
        rolled = self._roll_parts(parts, crit)
        return self._deal_rolled(tgt, rolled, by=by, label=label, crit=crit, factor=factor, magical=magical, spell=spell)

    # ---- concentration
    def _start_conc(self, c: dict, sp: dict):
        if c.get("concentrating"):
            self._drop_conc(c, f"casting {sp['name']}")
        c["concentrating"] = {"spell": sp["name"], "rounds": CR.duration_rounds(sp.get("duration", "")),
                              "src": self._magic_source(c, sp)}          # the colour of its ring on the maps

    def _held_by(self, c: dict) -> list:
        """Where the things a caster's concentration holds are (tile units): the creatures it affects or summoned, its zones."""
        out = []
        for o in self.b["combatants"]:
            if o is not c and o.get("pos") and (o.get("summon_conc") == c["id"] or any(e.get("conc_by") == c["id"] for e in o.get("effects") or [])):
                s = max(1, int(o.get("span") or 1))
                out.append([o["pos"][0] + s / 2, o["pos"][1] + s / 2])
        for z in self.b.get("zones") or []:
            if z.get("conc_by") == c["id"] and z.get("tiles"):
                out.append([sum(t[0] for t in z["tiles"]) / len(z["tiles"]) + .5, sum(t[1] for t in z["tiles"]) / len(z["tiles"]) + .5])
        return out

    def _drop_conc(self, c: dict, why: str):
        st = c.get("concentrating")
        if not st:
            return
        self._vfx("conc", id=c["id"], ok=False, check=why == "failed the save", spell=st["spell"], src=st.get("src") or "arcane",
                  ends=self._held_by(c))                        # the ring breaks, everything it held lets go at once
        c["concentrating"] = None
        for gone in [o for o in self.b["combatants"] if o.get("summon_conc") == c["id"]]:
            if CR.norm(gone.get("summon_spell") or "") in X.TURN_ON_CONC_LOSS:
                gone.update(summon_conc=None, faction=0, turned=True)      # Conjure Elemental: free, and hostile to everyone now
                self._vfx("turned", id=gone["id"])
                self._say(f"{gone['name']} breaks free of {c['name']}'s control and turns on them")
            else:
                self._vfx_unsummon(gone)
                self._take_out(gone)
                self._say(f"{gone['name']} disappears")
        for o in self.b["combatants"]:
            for eff in list(o.get("effects") or []):
                if eff.get("conc_by") == c["id"]:
                    self._effect_off(o, eff, f"{c['name']} lost concentration")
        for z in [z for z in self.b.get("zones") or [] if z.get("conc_by") == c["id"]]:
            if z.get("bead"):                                   # Delayed Blast Fireball: the bead erupts
                self._bead_boom(z, f"{c['name']} lost concentration")
            else:
                self._zone_off(z, f"{c['name']} lost concentration")
        for o in self.b["combatants"]:
            if (o.get("form") or {}).get("conc_by") == c["id"]:          # Polymorph: back to its own shape
                self._say(f"{o['name']} returns to its own shape ({o.pop('form')['name']} form ends)")
        for o in self.b["combatants"]:
            o["spell_actions"] = [s for s in o.get("spell_actions") or [] if s.get("conc_by") != c["id"]]
        self._prune_tokens()
        self._say(f"{c['name']} loses concentration on {st['spell']} ({why})")

    def _conc_check(self, c: dict, dealt: int, by: Optional[dict] = None):
        """Taking damage while concentrating: a Constitution save (DC 10 or half the damage); at 0 HP the spell ends.
        Mage Slayer's damage imposes disadvantage."""
        if dealt <= 0 or not c.get("concentrating"):
            return
        if self._hp_of(c) <= 0 or K.incapacitated(self._conds(c)):
            return self._drop_conc(c, "knocked out" if self._hp_of(c) <= 0 else "incapacitated")
        if self._subd_conc_safe(c) or self._nf_conc_safe(c):    # Focused Conjuration (subfeats_d.py); Boon of the Iron Mind (newfeats.py)
            return
        dc = max(10, dealt // 2)
        adv = bool(self._fx(c, "conc_adv"))
        if adv:
            c.setdefault("effects", []).append({"name": "War Caster", "mods": {"save_adv": ["con"]}, "conditions": [], "rounds": None,
                                                "repeat": None, "_tmp": True})
        plus = sum(int(v) for _e, v in self._fx(c, "conc_bonus"))       # Bladesong: + Intelligence
        if plus:
            c.setdefault("effects", []).append({"name": "Bladesong", "mods": {"save": f"+{plus}"}, "conditions": [], "rounds": None,
                                                "repeat": None, "_tmp": True})
        if by is not None and self._feat(by, "mage_slayer"):
            c.setdefault("effects", []).append({"name": "Mage Slayer", "mods": {"save_dis": ["con"]}, "conditions": [], "rounds": None,
                                                "repeat": None, "_tmp": True})
        if self._conc_disadvantage(by):                         # a Mage Breaker's hit (itemmore.py)
            c.setdefault("effects", []).append({"name": "Mage Breaker", "mods": {"save_dis": ["con"]}, "conditions": [], "rounds": None,
                                                "repeat": None, "_tmp": True})
        if self._fx(c, "conc_dis"):                             # Disruptive Tune: disadvantage on saves to keep concentration
            c.setdefault("effects", []).append({"name": "Disruptive Tune", "mods": {"save_dis": ["con"]}, "conditions": [], "rounds": None,
                                                "repeat": None, "_tmp": True})
        res = self._saving_throw(c, "con", dc, label="concentration")
        c["effects"] = [e for e in c.get("effects") or [] if not e.get("_tmp")]
        if not res["ok"] and res["kept"] < 10 and any(v == "dragon" for _e, v in self._fx(c, "starry")):   # Starry Form (Dragon): a 9 or lower is a 10
            res = dict(res, total=res["total"] - res["kept"] + 10, kept=10)
            res["ok"] = res["total"] >= dc
        if not res["ok"]:
            res = self._conc_rescue(c, res, dc)                 # a Mind Sharpener, a Scholar's Anchoring Bangle, a Ring of Dedicated Focus (itemmore.py)
        self._say(f"{c['name']} concentration on {c['concentrating']['spell']}: CON save d20 {res['kept']}{self._save_mode_note(res)} = "
                  f"{res['total']}{res['note']} vs DC {dc} — " + ("kept" if res["ok"] else "lost"))
        if not res["ok"]:
            self._drop_conc(c, "failed the save")
        else:
            self._vfx("conc", id=c["id"], ok=True, check=True, spell=c["concentrating"]["spell"], src=c["concentrating"].get("src") or "arcane")
