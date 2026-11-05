"""Rolling, setting and ordering initiative."""
import re
from typing import List, Optional

from ...rules import engine as E
from ..common import ServiceError
from .constants import ACTIVE


class InitiativeMixin:
    # ------------------------------------------------------------------ initiative
    def _fit_initiative(self, c: dict):
        """After a drag & drop: give the combatant an initiative that is consistent with its new place."""
        rows = self.b["combatants"]
        i = rows.index(c)
        above = next((r["init"] for r in reversed(rows[:i]) if r["init"] is not None), None)
        below = next((r["init"] for r in rows[i + 1:] if r["init"] is not None), None)
        value = c["init"]
        if value is None:
            value = above if above is not None else below if below is not None else None
        else:
            if above is not None and value > above:
                value = above
            if below is not None and value < below:
                value = below
        c["init"] = value

    def move(self, cid: int, new_index: int):
        """Drag & drop: put a combatant at a new place in the order (its initiative adjusts to fit)."""
        with self.lock:
            rows = self.b["combatants"]
            c = self._find(cid)
            rows.remove(c)
            rows.insert(max(0, min(new_index, len(rows))), c)
            self._fit_initiative(c)
            self._commit(f"{c['name']} moved to position {rows.index(c) + 1}" + (f" (initiative {c['init']})" if c["init"] is not None else ""))

    def set_initiative(self, cid: int, value: Optional[int]):
        with self.lock:
            c = self._find(cid)
            c["init"] = None if value is None else int(value)
            self._sort()
            self._commit(f"{c['name']} initiative set to {value}")

    def _sort(self):
        """Order by initiative (highest first); ties keep the current order, then higher Dex bonus."""
        rows = self.b["combatants"]
        position = {c["id"]: i for i, c in enumerate(rows)}
        rows.sort(key=lambda c: (c["init"] is None, -(c["init"] if c["init"] is not None else 0), -c["init_bonus"],
                                 position[c["id"]]))

    def _roll_one(self, c: dict, advantage: Optional[str] = None) -> int:
        texts = []
        if c["kind"] == "pc":
            char = self._char(c["character"])
            c["init_bonus"] = char.initiative if char else c["init_bonus"]
            if char:                                    # a Weapon of Warning, a barbarian's Feral Instinct
                texts = [d.get("text") or "" for _e, d in char._active_items()] + (["advantage on initiative"] if char.has_feature("Feral Instinct") else [])
        else:
            texts = [t.get("text") or "" for t in (self._monster(c) or {}).get("traits") or []]
        if advantage is None and (any(re.search(r"advantage on (?:its |their )?initiative", t, re.I) for t in texts) or self._fxs(c, "init_adv")):
            advantage = "adv"                           # (init_adv: a Rod of Alertness, a Sentinel Shield... wondrous.py)
        total, _rolls = E.roll_d20(c["init_bonus"], advantage, self.rng)
        total = self._nf_initiative(c, total, _rolls)       # Survivor's Hypervigilance: a 9 or lower is rolled again (newfeats.py)
        for e in [e for e in c.get("effects") or [] if e["name"] == "Vigilant Blessing"]:
            self._effect_off(c, e, "the initiative roll")      # a Twilight cleric's blessing is used up by the roll
        self._subb_initiative(c)                                # Tireless Spirit (subfeats_b.py)
        self._subc_initiative(c)                                # Ever-Ready Shot, Legion of One (subfeats_c.py)
        total += self._wonder_initiative(c) if c["kind"] == "pc" else 0    # a Spindle of Fate's Battle Foreknowledge (wondrous.py)
        total += self._subd_initiative(c)                       # Temporal Awareness, Aura of the Sentinel (subfeats_d.py)
        c["init"] = total
        self._npc_roll(c, "🎲", "Initiative", total, f"d20 {_rolls} {c['init_bonus']:+d}")
        return total

    def roll_initiative(self, scope: str = "all", group_enemies: bool = True) -> List[str]:
        """Roll initiative: scope 'all', 'enemies', 'players' or 'missing' (only those without a value)."""
        with self.lock:
            rolled, group_rolls = [], {}
            for c in self.b["combatants"]:
                if scope == "enemies" and c["kind"] != "enemy" or scope == "players" and c["kind"] != "pc":
                    continue
                if scope == "missing" and c["init"] is not None:
                    continue
                if c["kind"] == "enemy" and group_enemies and c["monster"]:
                    if c["monster"] in group_rolls:
                        c["init"] = group_rolls[c["monster"]]
                    else:
                        group_rolls[c["monster"]] = self._roll_one(c)
                else:
                    self._roll_one(c)
                rolled.append(f"{c['name']} {c['init']}")
            if not rolled:
                raise ServiceError("Nobody to roll for.")
            self._sort()
            self._commit("Initiative rolled: " + ", ".join(rolled))
            return rolled

    def roll_for_character(self, character: str, advantage: Optional[str] = None) -> int:
        """A player rolls their own initiative (before the battle starts, or if they joined late)."""
        with self.lock:
            c = next((x for x in self.b["combatants"] if x["character"] == character), None)
            if not c:
                raise ServiceError(f"{character} isn't in this battle.")
            if c["init"] is not None and self.b["status"] == ACTIVE:
                raise ServiceError("Initiative is already rolled.")
            total = self._roll_one(c, advantage)
            self._sort()
            self._commit(f"{character} rolled initiative: {total}")
            self.h.discord_log(f"🎲 **{character}** · Initiative · **{total}** · d20 {c['init_bonus']:+d}", "player_rolls")
            return total
