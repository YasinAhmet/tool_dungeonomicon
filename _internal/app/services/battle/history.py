"""Undo and redo for the whole battle.

Every commit made outside an action in progress is one step: the battle as it was before, plus what the battle may
have changed on the party's sheets (hit points, temporary HP, conditions, death saves, spent slots and resources, XP).
Only the outermost of nested commits records a step (an attack that knocks a summoner out and dismisses its summon is
one step), and a whole action that paused for a reaction or rolling dice becomes one step when it finishes. Changes to
screen effects, the event list and the log alone are not steps. Map drawings are steps like everything else.
"""
from typing import Optional

from ...core.storage import clone
from ..common import Busy, ServiceError
from .resolve import held

UNDO_STEPS = 40
QUIET = ("fx", "fx_n", "events", "rid_next", "pending", "log")      # bookkeeping: never a step by itself


def _bare(b: dict) -> dict:
    return {k: v for k, v in b.items() if k not in QUIET}


class HistoryMixin:
    # ------------------------------------------------------------------ recording
    def _history_reset(self):
        self._undo, self._redo, self._since = [], [], []
        self._replay = False
        self._last = self._snapshot()

    def _snapshot(self) -> dict:
        """The battle (a copy) and the vitals of every player character in it."""
        pcs = {}
        vitals = getattr(self.chars, "vitals", None)
        for c in self.b["combatants"]:
            if c["kind"] == "pc" and c.get("character") and vitals:
                try:
                    pcs[c["character"]] = vitals(c["character"])
                except ServiceError:
                    pass
        return {"b": clone(self.b), "pcs": pcs}

    def _history_step(self, label: Optional[str]):
        """Called by every commit: record the state before this change as an undo step, when it is one."""
        if getattr(self, "_last", None) is None:
            return
        if self._replay:                                    # an undo / redo being saved: it is the new "before"
            self._last, self._since = self._snapshot(), []
            return
        if self.lock.depth > 1 or any(held(r) for r in self.b.get("pending") or []):
            return                                          # part of a bigger action: it records the step
        now = self._snapshot()
        if _bare(now["b"]) == _bare(self._last["b"]) and now["pcs"] == self._last["pcs"]:
            self._last, self._since = now, []
            return
        name = label or (self._since[0] if self._since else self._guess(self._last["b"], now["b"]))
        self._undo.append({"label": name, "state": self._last})
        del self._undo[:-UNDO_STEPS]
        self._redo = []
        self._last, self._since = now, []

    @staticmethod
    def _guess(old: dict, new: dict) -> str:
        """A name for a step that logged nothing: what changed."""
        before = {c["id"]: c for c in old["combatants"]}
        for c in new["combatants"]:
            o = before.get(c["id"])
            if o is None:
                return f"{c['name']} added"
            if o.get("pos") != c.get("pos"):
                return f"Move {c['name']}" if c.get("pos") else f"{c['name']} taken off the map"
            if o.get("notes") != c.get("notes"):
                return f"Note on {c['name']}"
            if o != c:
                return f"Change to {c['name']}"
        if len(before) > len(new["combatants"]):
            return "Combatant removed"
        for key, what in (("drawings", "Map drawing"), ("ground", "Items on the ground"), ("map", "Map change"), ("rules", "Battle rules"),
                          ("zones", "Lasting areas"), ("name", "Battle renamed")):
            if old.get(key) != new.get(key):
                return what
        return "Battle change"

    # ------------------------------------------------------------------ undo / redo
    def _history_guard(self):
        try:
            self._busy()
        except Busy:
            raise Busy("Wait for the reaction / dice first.")

    def _restore(self, state: dict):
        fx_n, fx, rid = self.b.get("fx_n", 0), self.b.get("fx") or [], self.b.get("rid_next", 1)
        self.b = clone(state["b"])
        self.b["fx_n"], self.b["fx"] = fx_n, fx                       # screen effects never play again
        self.b["rid_next"] = max(rid, self.b.get("rid_next", 1))
        if any(held(r) for r in self.b.get("pending") or []):
            self.b["pending"] = []
        for name, v in state["pcs"].items():
            try:
                self.chars.restore_vitals(name, v, f"{name}: battle undo")
            except ServiceError:
                pass

    def _replayed(self, line: str):
        self._replay = True
        try:
            self._commit(line)
        finally:
            self._replay = False

    def undo_label(self) -> Optional[str]:
        """What undo() would take back (for a tooltip), or None."""
        with self.lock:
            return self._undo[-1]["label"] if self._undo else None

    def redo_label(self) -> Optional[str]:
        with self.lock:
            return self._redo[-1]["label"] if self._redo else None

    def undo(self) -> str:
        """Take back the last change (hit points, a move, a turn, a removal, a cleared or reset battle...).
        Returns what was undone, e.g. 'Goblin 2 takes 7 damage'."""
        with self.lock:
            self._history_guard()
            if not self._undo:
                raise ServiceError("Nothing to undo.")
            step = self._undo.pop()
            self._redo.append({"label": step["label"], "state": self._snapshot()})
            self._restore(step["state"])
            self._replayed(f"Undone: {step['label']}")
            return step["label"]

    def redo(self) -> str:
        """Do again what undo() took back. Returns its name."""
        with self.lock:
            self._history_guard()
            if not self._redo:
                raise ServiceError("Nothing to redo.")
            step = self._redo.pop()
            self._undo.append({"label": step["label"], "state": self._snapshot()})
            self._restore(step["state"])
            self._replayed(f"Redone: {step['label']}")
            return step["label"]
