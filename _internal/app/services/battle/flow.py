"""Starting and ending the battle, turns and rounds, experience points."""
from typing import List

from ..common import ServiceError
from .constants import ACTIVE, ENDED, blank_battle, faction_of


class FlowMixin:
    # ------------------------------------------------------------------ flow
    def missing_initiative(self) -> List[str]:
        return [c["name"] for c in self.b["combatants"] if c["init"] is None]

    def start(self, auto_roll: bool = False):
        """The fight begins - from setting up, or right after the last one ended (out of combat, everything stays where
        it is: tokens, hit points, the map)."""
        with self.lock:
            if self.b["status"] == ACTIVE:
                raise ServiceError("The battle already started.")
            if not self.b["combatants"]:
                raise ServiceError("Add combatants first.")
            if not self.b.get("duel") and not any(c["kind"] == "enemy" for c in self.b["combatants"]):   # (a duel: heroes alone)
                raise ServiceError("Add at least one enemy.")
            if self.missing_initiative():
                if not auto_roll:
                    raise ServiceError("Roll initiative first. Missing: " + ", ".join(self.missing_initiative()))
                for c in self.b["combatants"]:
                    if c["init"] is None:
                        self._roll_one(c)
            self._sort()
            self.b.update(status=ACTIVE, round=1, summary=None, pending=[])
            self.b["turn"] = self.b["combatants"][0]["id"]
            self._skip_defeated()
            self._ready_all()
            self._say(f"Battle started! {self._name_of(self.b['turn'])} goes first.")
            self._vfx("banner", text="The battle begins", tone="start", round=1)
            self._turn_start(self.b["turn"])
            self._vfx("turn", id=self.b["turn"])
            self._commit(label="Start the battle")

    def _name_of(self, cid) -> str:
        c = next((c for c in self.b["combatants"] if c["id"] == cid), None)
        return c["name"] if c else "?"

    def _is_out(self, c: dict) -> bool:
        """Out of the fight: a creature at 0 hit points, or a player character who has died (three failed death saves)."""
        return c["kind"] == "enemy" and c["hp"] <= 0 or self._dead(c)

    def _dead(self, c: dict) -> bool:
        if c["kind"] != "pc":
            return False
        char = self._peek(c)
        return bool(char) and char.current_hp <= 0 and (char.d.get("death_saves") or {}).get("failure", 0) >= 3

    def _skips_turn(self, c: dict) -> bool:
        """Out of the fight, or a conjured token that acts through its caster (Spiritual Weapon)."""
        return self._is_out(c) or bool(c.get("conjured"))

    def _stable(self, c: dict) -> bool:
        char = self._peek(c)
        return bool(char) and char.current_hp <= 0 and (char.d.get("death_saves") or {}).get("success", 0) >= 3

    def _skip_defeated(self):
        rows = self.b["combatants"]
        if all(self._skips_turn(c) for c in rows):
            return
        while self._skips_turn(next(c for c in rows if c["id"] == self.b["turn"])):
            self._step(1)

    def _step(self, delta: int):
        rows = self.b["combatants"]
        index = next((i for i, c in enumerate(rows) if c["id"] == self.b["turn"]), None)
        if index is None:                       # nobody holds the turn (everyone had left): start from the top
            self.b["turn"] = rows[0]["id"] if rows else None
            return
        index += delta
        if index >= len(rows):
            index, self.b["round"] = 0, self.b["round"] + 1
        elif index < 0:
            index, self.b["round"] = len(rows) - 1, max(1, self.b["round"] - 1)
        self.b["turn"] = rows[index]["id"]

    def _advance(self):
        rows = self.b["combatants"]
        if len(rows) <= 1:
            self.b["turn"] = rows[0]["id"] if rows else None
            return
        self._step(1)
        if all(self._skips_turn(c) for c in rows):
            return
        while self._skips_turn(next(c for c in rows if c["id"] == self.b["turn"])):
            self._step(1)

    def next_turn(self):
        with self.lock:
            if self.b["status"] != ACTIVE:
                raise ServiceError("The battle hasn't started.")
            self._clear_pending("the turn ended")
            before = self.b["round"]
            for _ in range(len(self.b["combatants"]) + 1):     # a banished creature's turn passes by itself
                was = self.b["round"]
                self._turn_end(self.b["turn"])
                cur = next((c for c in self.b["combatants"] if c["id"] == self.b["turn"]), None)
                if cur and cur.get("extra_turns"):
                    cur["extra_turns"] -= 1
                    self._say(f"{cur['name']} takes another turn (Time Stop)")
                elif self._subd_reflex(cur):                    # Thief's Reflexes: a second turn in the first round (subfeats_d.py)
                    pass
                else:
                    self._advance()
                    if self.b["round"] != was:
                        self._tick_rounds()
                note = f" — round {self.b['round']} begins" if self.b["round"] != was else ""
                self._say(f"{self._name_of(self.b['turn'])}'s turn{note}")
                if self.b["round"] != was:
                    self._vfx("banner", text="Round {0}", tone="round", round=self.b["round"])
                self._turn_start(self.b["turn"])
                if any(r.get("wait") or r.get("dice") for r in self._stack()) \
                        or not self._banished_turn(self._find_or_none(self.b["turn"])):
                    break
            note = f" — round {self.b['round']} begins" if self.b["round"] != before else ""
            self._vfx("turn", id=self.b["turn"])                # its ring draws itself; on its player's page: "Your turn"
            self._raise("turn_start", creature=self._find(self.b["turn"]))
            self._commit(label=f"Next turn: {self._name_of(self.b['turn'])}{note}")

    def previous_turn(self):
        with self.lock:
            if self.b["status"] != ACTIVE:
                raise ServiceError("The battle hasn't started.")
            rows = self.b["combatants"]
            for _ in range(len(rows)):
                self._step(-1)
                if not self._skips_turn(next(c for c in rows if c["id"] == self.b["turn"])):
                    break
            self._commit(f"Back to {self._name_of(self.b['turn'])}")

    def end(self, award_xp: bool = False) -> dict:
        """End the battle. Optionally split the defeated enemies' XP among the player characters."""
        with self.lock:
            if self.b["status"] != ACTIVE:
                raise ServiceError("There is no battle in progress.")
            view = self.view()["combatants"]
            defeated = [c for c in view if c["kind"] == "enemy" and c["defeated"] and faction_of(c) != 1]
            xp = sum(c["xp"] for c in defeated)
            party = [c["character"] for c in view if c["kind"] == "pc" and not c.get("missing")]
            share = xp // len(party) if party else 0
            if award_xp and share:
                for name in party:
                    try:
                        self.chars.add_xp(name, share)
                    except ServiceError:
                        pass
            summary = {"rounds": self.b["round"], "defeated": [c["name"] for c in defeated], "xp": xp,
                       "share": share, "awarded": bool(award_xp and share), "party": party,
                       "downed": [c["name"] for c in view if c["kind"] == "pc" and c.get("downed")]}
            self.b.update(status=ENDED, turn=None, summary=summary)
            won = all(c["defeated"] or faction_of(c) == 1 for c in view if c["kind"] == "enemy")
            self._vfx("banner", text="Victory" if won else "The battle is over", tone="victory" if won else "end")
            self._ready_all()                                   # out of combat: nobody is left with a spent turn
            self._commit(f"Battle over after {summary['rounds']} round(s). {len(defeated)} enemies defeated, {xp} XP"
                         + (f" ({share} each)" if award_xp and share else ""))
            return summary

    def award_xp(self) -> int:
        """After the battle: split the defeated enemies' XP among the party (once)."""
        with self.lock:
            s = self.b["summary"]
            if self.b["status"] != ENDED or not s:
                raise ServiceError("Only a finished battle can award XP.")
            if s["awarded"] or not s["share"]:
                raise ServiceError("There is no XP to award." if not s["share"] else "XP was already awarded.")
            for name in s["party"]:
                try:
                    self.chars.add_xp(name, s["share"])
                except ServiceError:
                    pass
            s["awarded"] = True
            self._commit(f"Awarded {s['share']} XP to each player")
            return s["share"]

    def reset(self):
        """Throw the finished (or planned) battle away and start a fresh setup keeping the party."""
        with self.lock:
            if self.b["status"] == ACTIVE:
                raise ServiceError("End the battle first.")
            party = [c["character"] for c in self.b["combatants"] if c["kind"] == "pc"]
            self.b = blank_battle(self.b["name"])
            for n in party:
                try:
                    self.add_player(n)
                except ServiceError:
                    pass
            self._commit("Ready for a new battle")
