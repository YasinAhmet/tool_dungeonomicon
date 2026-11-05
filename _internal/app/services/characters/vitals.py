"""Hit points, death saves, rests, hit dice, conditions, exhaustion and inspiration."""
import copy
import random
from typing import Dict, List, Optional, Tuple

from ...rules import leveling as LV
from ...rules.character import Character, CONDITIONS

VITALS = ("conditions", "death_saves", "exhaustion", "slots_used", "resources", "hit_dice_used", "xp", "inspiration", "inventory")
from ..common import RollResult, ServiceError, positive_int, rules_errors, whole_int


class VitalsMixin:
    # ---- hit points ----
    def damage(self, name: str, amount) -> Tuple[int, Character]:
        amount = positive_int(amount, "Damage")
        with self.lock:
            char = self.get(name)
            taken = char.damage(amount)
            self._commit(char, f"Damaged {char.name} for {amount} (took {taken}).",
                         f"💔 {char.name} took **{taken}** damage (HP: {char.current_hp}/{char.max_hp})")
        return taken, char

    def heal(self, name: str, amount) -> Tuple[int, Character]:
        amount = positive_int(amount, "Heal amount")
        with self.lock:
            char = self.get(name)
            healed = char.heal(amount)
            self._commit(char, f"Healed {char.name} for {amount} (healed {healed}).",
                         f"💚 {char.name} healed **{healed}** (HP: {char.current_hp}/{char.max_hp})")
        return healed, char

    def set_temp_hp(self, name: str, amount) -> Character:
        """PHB: temporary hit points don't stack; keep whichever pool is larger."""
        amount = whole_int(amount, "Temporary HP", 0, 10 ** 6)
        with self.lock:
            char = self.get(name)
            char.temp_hp = max(char.temp_hp, amount) if amount else 0
            self._commit(char, f"{char.name} temp HP set to {char.temp_hp}")
        return char

    def set_hp_adjustment(self, name: str, value) -> Character:
        """DM override: a flat bonus (or penalty) to maximum hit points."""
        value = whole_int(value, "HP adjustment", -1000, 1000)
        with self.lock:
            char = self.get(name)
            char.d["hp"]["bonus"] = value
            char.current_hp = min(char.current_hp, char.max_hp)
            self._commit(char, f"Max HP adjustment for {char.name} set to {value:+d}")
        return char

    def death_save(self, name: str, result: Optional[str] = None, roll: Optional[int] = None) -> RollResult:
        """Roll (or record 'success'/'failure') a death saving throw. Three of either ends it. `roll`: a d20 already
        rolled (the battle's async rolling shows it first)."""
        with self.lock:
            char = self.get(name)
            if char.current_hp > 0:
                raise ServiceError(f"{char.name} isn't at 0 HP.")
            saves = char.d["death_saves"]
            if saves.get("failure", 0) >= 3:
                raise ServiceError(f"{char.name} is dead.")
            if saves.get("success", 0) >= 3:
                raise ServiceError(f"{char.name} is stable and doesn't roll death saves.")
            if result is not None:
                roll = None
            else:
                roll = roll or random.randint(1, 20)
                if roll == 20:
                    char.heal(1)
                    saves.update(success=0, failure=0)
                    self._commit(char, f"{char.name} rolled a natural 20 on a death save and rises with 1 HP",
                                 f"🎲 **{char.name}** rolled a **natural 20** on a death save and regains 1 HP!")
                    return RollResult(20, "Natural 20! You regain 1 hit point.", 20)
                result = "failure2" if roll == 1 else "success" if roll >= 10 else "failure"
            if result.startswith("success"):
                saves["success"] += 1
            else:
                saves["failure"] += 2 if result == "failure2" else 1
            text = f"Death save{f' ({roll})' if roll else ''}: {saves['success']} successes, {saves['failure']} failures"
            if saves["success"] >= 3:
                saves.update(success=3, failure=0)                  # stable until healed or hurt again
                text += " — stable."
            elif saves["failure"] >= 3:
                text += " — dead."
            self._commit(char, f"{char.name}: {text}", f"☠️ {char.name}: {text}")
            return RollResult(roll or 0, text, roll)

    def adjust_death_save(self, name: str, kind: str, delta) -> Character:
        """DM edit: add to (or take from) the death save successes or failures, kept within 0-3."""
        if kind not in ("success", "failure"):
            raise ServiceError(f"Unknown death save tally '{kind}'.")
        delta = whole_int(delta, "Death save change", -3, 3)
        with self.lock:
            char = self.get(name)
            saves = char.d.setdefault("death_saves", {"success": 0, "failure": 0})
            saves[kind] = max(0, min(3, int(saves.get(kind) or 0) + delta))
            self._commit(char, f"{char.name} death saves set to {saves.get('success', 0)} successes, "
                               f"{saves.get('failure', 0)} failures")
        return char

    def spend_hit_die(self, name: str, class_name: Optional[str] = None, roll: Optional[int] = None) -> Tuple[int, int]:
        """Short-rest healing: spend a hit die. Returns (die result, hp healed)."""
        with self.lock:
            char = self.get(name)
            dice = char.hit_dice()
            if class_name is None:
                avail = [(n, d) for n, d in dice.items() if d["used"] < d["total"]]
                if not avail:
                    raise ServiceError(f"{char.name} has no hit dice left.")
                class_name = max(avail, key=lambda x: x[1]["die"])[0]
            if class_name not in dice:
                raise ServiceError(f"{char.name} has no {class_name} levels.")
            die = dice[class_name]["die"]
            roll = roll if roll is not None else random.randint(1, die)
            feats = char.d.get("feats") or []
            if "Boon of Bountiful Health" in feats:      # Superior Recuperation: the highest number on every die
                roll = die
            elif "Bloodlust" in feats:                   # Powerful Recovery: a 1 or 2 counts as a 3
                roll = max(roll, min(3, die))
            try:
                healed = char.spend_hit_die(class_name, roll)
            except ValueError as e:
                raise ServiceError(str(e))
            self._commit(char, f"{char.name} spent a d{die} hit die: rolled {roll}, healed {healed}",
                         f"🎲 {char.name} spent a d{die} hit die and healed **{healed}** (HP: {char.current_hp}/{char.max_hp})")
        return roll, healed

    def short_rest(self, name: str) -> Character:
        with self.lock:
            char = self.get(name)
            char.short_rest()
            self._commit(char, f"{char.name} took a short rest", f"🏕️ **{char.name}** took a short rest.")
        return char

    @rules_errors
    def long_rest(self, name: str, prepare: Optional[Dict[str, List[str]]] = None) -> Character:
        """`prepare`: {class: spells} prepared afresh for the new day (classes that prepare spells)."""
        with self.lock:
            char = self.get(name)
            for class_name, spells in (prepare or {}).items():
                LV.set_prepared(char, str(class_name), [str(n) for n in spells])
            char.long_rest()
            self._commit(char, f"{char.name} took a long rest", f"🛌 **{char.name}** took a long rest and is fully restored.")
        return char

    # ---- conditions ----
    def set_condition(self, name: str, condition: str, on: bool) -> Character:
        if condition not in CONDITIONS:
            raise ServiceError(f"Unknown condition '{condition}'.")
        with self.lock:
            char = self.get(name)
            current = set(char.d["conditions"])
            (current.add if on else current.discard)(condition)
            char.d["conditions"] = sorted(current)
            self._commit(char, f"{char.name} {'gained' if on else 'lost'} condition {condition}",
                         f"{'⚠️' if on else '✅'} **{char.name}** is {'now' if on else 'no longer'} **{condition}**")
        return char

    def set_exhaustion(self, name: str, level) -> Character:
        level = whole_int(level, "Exhaustion", 0, 6)
        with self.lock:
            char = self.get(name)
            char.d["exhaustion"] = level
            self._commit(char, f"{char.name} exhaustion level {level}")
        return char

    def toggle_inspiration(self, name: str) -> Character:
        with self.lock:
            char = self.get(name)
            char.d["inspiration"] = not char.d["inspiration"]
            self._commit(char, f"{char.name} inspiration: {char.d['inspiration']}")
        return char

    # ---- snapshots (the battle's undo) ----
    def vitals(self, name: str) -> dict:
        """What a battle changes on a character: hit points, temporary HP, conditions, death saves, exhaustion,
        spent slots / resources / hit dice, XP, inspiration and the pack (thrown, dropped, picked up) (a copy)."""
        char = self.get(name)
        out = {k: copy.deepcopy(char.d.get(k)) for k in VITALS}
        out.update(hp=char.current_hp, temp=char.temp_hp)
        return out

    def restore_vitals(self, name: str, vitals: dict, log: str = "") -> bool:
        """Put back what vitals() returned (or some of it: only the keys given). Saves only when something differs."""
        with self.lock:
            char = self.get(name)
            changed = False
            for k, v in vitals.items():
                if k == "hp":
                    if char.current_hp != int(v):
                        char.current_hp, changed = int(v), True
                elif k == "temp":
                    if char.temp_hp != int(v):
                        char.temp_hp, changed = int(v), True
                elif k in VITALS and char.d.get(k) != v:
                    char.d[k], changed = copy.deepcopy(v), True
            if changed:
                self._commit(char, log or f"{char.name}: hit points and conditions put back")
            return changed
