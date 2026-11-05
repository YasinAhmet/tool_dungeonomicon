"""Starting a battle and adding or removing combatants (enemies from the bestiary, custom ones, the party)."""
from typing import List, Optional

from ...rules.monsters import ability_mod, bestiary, roll_hp
from ..common import ServiceError
from . import summon_stats as SS
from .constants import ACTIVE, SPANS, blank_battle


class SetupMixin:
    # ------------------------------------------------------------------ setup
    def new_battle(self, name: str = "Battle", keep_players: bool = True) -> None:
        with self.lock:
            if self.b["status"] == ACTIVE:
                raise ServiceError("A battle is in progress. End it first.")
            party = [c for c in self.b["combatants"] if c["kind"] == "pc"] if keep_players else []
            keep = {k: self.b[k] for k in ("map", "drawings", "draw_next", "ground", "ground_next", "faction_colors") if k in self.b}   # the map stays the map
            self.b = blank_battle(name.strip() or "Battle")
            self.b.update(keep)
            for c in party:
                self._add(dict(c, init=None, id=None, effects=[], concentrating=None))
            self._commit(f"New battle: {self.b['name']}")

    def rename(self, name: str):
        with self.lock:
            self.b["name"] = name.strip() or self.b["name"]
            self._commit()

    def _add(self, c: dict, at: Optional[int] = None) -> dict:
        c["id"] = self.b["next_id"]
        self.b["next_id"] += 1
        rows = self.b["combatants"]
        rows.insert(len(rows) if at is None else max(0, min(at, len(rows))), c)
        if at is not None:
            self._fit_initiative(c)
        return c

    def _new(self, kind: str, name: str, hp: int, max_hp: int, ac: int, init_bonus: int, **extra) -> dict:
        return {"id": None, "kind": kind, "name": name, "hp": hp, "max_hp": max_hp, "ac": ac, "init": None,
                "init_bonus": init_bonus, "conditions": [], "notes": "", "revealed": False, "character": None,
                "monster": None, "xp": 0, "pos": None, "span": 1, "effects": [], "concentrating": None, "ally": False,
                "summoned_by": None, "summon_conc": None, **extra}

    def _label(self, base: str, multiple: bool) -> str:
        """'Goblin' stays plain when alone; otherwise creatures are numbered 'Goblin 1', 'Goblin 2'..."""
        rows = self.b["combatants"]
        same = [c for c in rows if c["name"] == base or (c["name"].startswith(base + " ") and c["name"][len(base) + 1:].isdigit())]
        if not same and not multiple:
            return base
        for c in same:
            if c["name"] == base:
                c["name"] = f"{base} 1"
        taken = {c["name"] for c in rows}
        n = 1
        while f"{base} {n}" in taken:
            n += 1
        return f"{base} {n}"

    def add_enemy(self, monster_id: str, count: int = 1, at: Optional[int] = None, hp_mode: str = "average",
                  name: Optional[str] = None, roll: bool = False, pos: Optional[List[int]] = None,
                  place: Optional[bool] = None) -> List[int]:
        """Add `count` copies of a library monster. `at` inserts at that position of the order (drag & drop).
        `roll` rolls their initiative at once, also mid-battle (copies of one monster share a roll; the order is sorted
        again, the turn stays with whoever has it); `pos` puts them on the map near that tile; without `pos`, `place` True puts them on free tiles on the
        east side, None does that only when someone already stands on the map, False leaves them off the map."""
        with self.lock:
            m = bestiary.get(monster_id)
            if not m:
                raise ServiceError("Unknown monster.")
            if not 1 <= count <= 40:
                raise ServiceError("Add between 1 and 40 creatures at a time.")
            base = (name or m["name"]).strip()
            owner, ctx = self._companion_owner(m)
            ids, labels = [], []
            for i in range(count):
                hp = roll_hp(m["hp_formula"], m["hp"], self.rng) if hp_mode == "roll" else m["hp"]
                if ctx is not None or not hp:                  # a companion's hit points come from its owner's level
                    hp = SS.hp(m, ctx or {}) or hp or 1
                label = self._label(base, count > 1)
                c = self._new("enemy", label, hp, hp, SS.fill(monster_id, ctx)["ac"], ability_mod(m, "dex"), monster=monster_id, xp=m["xp"],
                              span=SPANS.get(m.get("size"), 1), tiny=(m.get("size") or "").startswith("Tiny"))
                if owner is not None:
                    c.update(summon=ctx, faction=self._side(owner), summoned_by=owner["id"], xp=0)
                elif SS.needs_summoner(m):                     # a Draconic Spirit put down on its own: the spell's lowest level
                    from . import combat_rules as CR
                    from .spell_effects import SPIRITS
                    c["summon"] = st = SS.stock(m)
                    ac_base = next((v[2] for v in SPIRITS.values() if v[0] == monster_id), None)
                    c["ac"] = ac_base + st["level"] if ac_base else SS.fill(monster_id, st)["ac"]
                    if not m["hp"] and "spell level" in (m.get("hp_formula") or ""):
                        c["hp"] = c["max_hp"] = CR.spirit_hp(m["hp_formula"], "", st["level"])
                ids.append(self._add(c, None if at is None or roll else at + i)["id"])
                labels.append(label)
            self._arrive(ids, roll, pos, place)
            self._commit("Added " + ", ".join(labels))
            return ids

    def add_custom(self, name: str, hp: int, ac: int, init_bonus: int = 0, count: int = 1, at: Optional[int] = None,
                   xp: int = 0, roll: bool = False, pos: Optional[List[int]] = None, place: Optional[bool] = None) -> List[int]:
        """A creature that isn't in the library; `at`, `roll`, `pos` and `place` as for add_enemy."""
        with self.lock:
            if not name.strip():
                raise ServiceError("Give the creature a name.")
            if hp < 1:
                raise ServiceError("Hit points must be at least 1.")
            ids, labels = [], []
            for i in range(max(1, count)):
                label = self._label(name.strip(), count > 1)
                c = self._new("enemy", label, hp, hp, ac, init_bonus, xp=xp)
                ids.append(self._add(c, None if at is None or roll else at + i)["id"])
                labels.append(label)
            self._arrive(ids, roll, pos, place)
            self._commit("Added " + ", ".join(labels))
            return ids

    def add_player(self, character: str, at: Optional[int] = None, roll: bool = False,
                   pos: Optional[List[int]] = None, place: Optional[bool] = None) -> int:
        """A player character joins; `at`, `roll`, `pos` and `place` as for add_enemy (placed on the west side)."""
        with self.lock:
            char = self.chars.get(character)
            if any(c["character"] == char.name for c in self.b["combatants"]):
                raise ServiceError(f"{char.name} is already in the battle.")
            c = self._new("pc", char.name, char.current_hp, char.max_hp, char.armor_class()[0], char.initiative,
                          character=char.name)
            self._add(c, None if roll else at)
            self._arrive([c["id"]], roll, pos, place)
            self._commit(f"{char.name} joined the battle")
            return c["id"]

    def add_party(self, names: List[str]) -> int:
        """Add these characters (one undo step); returns how many joined."""
        with self.lock:
            added = 0
            for n in names:
                try:
                    self.add_player(n)
                    added += 1
                except ServiceError:
                    pass
            if added:
                self._commit(label="Add the party")
            return added
