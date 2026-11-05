"""The DM's small edits of a combatant: hit points, temporary hit points, its name, and a copy of it."""
import copy
import re

from ..common import ServiceError
from .constants import ACTIVE

RUNTIME = ("turn", "readied", "spent", "lr_used", "form", "took_types", "spell_actions", "extra_turns", "react_used",
           "temp_hp", "exhaustion", "subd")              # what a fresh copy of a creature doesn't inherit


class EditingMixin:
    def set_hp(self, cid: int, hp: int) -> str:
        """Set a combatant's hit points (a player character's through its sheet). An enemy set above its maximum gets
        that as its new maximum; 0 knocks out (a player character falls unconscious), more than 0 brings one back."""
        with self.lock:
            c = self._find(cid)
            try:
                hp = int(hp)
            except (TypeError, ValueError):
                raise ServiceError("Hit points must be a whole number.")
            if hp < 0:
                raise ServiceError("Hit points can't be negative.")
            before = self._hp_of(c)
            if c["kind"] == "pc":
                char = self._sheet(c)
                if not char:
                    raise ServiceError(f"{c['name']}'s character sheet is missing.")
                hp = min(hp, char.max_hp)
                vit = {"hp": hp}
                conds = list(char.conditions)
                if hp == 0 and "Unconscious" not in conds:
                    vit["conditions"] = sorted(conds + ["Unconscious"])
                elif hp > 0 and before == 0:
                    vit["conditions"] = [x for x in conds if x != "Unconscious"]
                    vit["death_saves"] = {"success": 0, "failure": 0}
                self.chars.restore_vitals(c["character"], vit, f"{c['name']} HP set to {hp} in battle")
            else:
                c["hp"] = hp
                c["max_hp"] = max(c["max_hp"], hp)
            if hp <= 0 < before and c.get("concentrating"):
                self._drop_conc(c, "knocked out")
            line = f"{c['name']}'s hit points set to {hp}" + (" (defeated)" if c["kind"] == "enemy" and hp <= 0 else "")
            self._commit(line)
            return line

    def set_temp_hp(self, cid: int, n: int) -> str:
        """Set a combatant's temporary hit points exactly (0 removes them)."""
        with self.lock:
            c = self._find(cid)
            try:
                n = int(n)
            except (TypeError, ValueError):
                raise ServiceError("Temporary hit points must be a whole number.")
            if n < 0:
                raise ServiceError("Temporary hit points can't be negative.")
            if c["kind"] == "pc":
                self.chars.restore_vitals(c["character"], {"temp": n}, f"{c['name']} temp HP set to {n} in battle")
            else:
                c["temp_hp"] = n
            line = f"{c['name']} has {n} temporary hit points" if n else f"{c['name']} loses its temporary hit points"
            self._commit(line)
            return line

    def rename_combatant(self, cid: int, name: str) -> str:
        """Give a combatant another name in this battle (a player character's sheet keeps its name)."""
        with self.lock:
            c = self._find(cid)
            new = re.sub(r"\s+", " ", str(name or "")).strip()
            if not new:
                raise ServiceError("Give the combatant a name.")
            if len(new) > 60:
                raise ServiceError("That name is too long (60 characters at most).")
            if any(o is not c and o["name"].lower() == new.lower() for o in self.b["combatants"]):
                raise ServiceError(f"Someone in the battle is already called {new}.")
            old = c["name"]
            if old == new:
                return new
            c["name"] = new
            self._commit(f"{old} is now called {new}")
            return new

    def duplicate(self, cid: int) -> int:
        """Another copy of a creature (not a player character): full hit points, no conditions or effects, the same
        initiative right after it in the order, on a free tile next to it if it is on the map. Returns the new id."""
        with self.lock:
            c = self._find(cid)
            if c["kind"] == "pc":
                raise ServiceError("A player character can't be copied.")
            twin = copy.deepcopy(c)
            for k in RUNTIME:
                twin.pop(k, None)
            twin.update(hp=c["max_hp"], conditions=[], effects=[], concentrating=None, summon_conc=None, pos=None, revealed=False)
            base = re.sub(r" \d+$", "", c["name"])
            twin["name"] = self._label(base, True)
            twin["id"] = self.b["next_id"]
            self.b["next_id"] += 1
            rows = self.b["combatants"]
            rows.insert(rows.index(c) + 1, twin)
            if c.get("pos"):
                spot = self._free_near(twin, *c["pos"])
                if spot:
                    twin["pos"] = spot
            if self.b["status"] == ACTIVE:
                self._fresh_turn(twin)
            self._commit(f"Added {twin['name']} (a copy of {c['name']})")
            return twin["id"]
