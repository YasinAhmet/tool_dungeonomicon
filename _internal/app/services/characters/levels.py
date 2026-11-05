"""Creating characters, levelling up, and editing earlier levels (later levels are replayed from their recorded choices)."""
import copy
import random
from typing import List, Optional

from ...core import events
from ...rules import engine as E
from ...rules import leveling as LV
from ...rules import quickgen
from ...rules.reconstruct import base_of, keep_hand_edits, origin_base, reconstruct
from ...rules.character import Character
from ...rules.creation import create_character
from ..common import ServiceError, rules_errors, valid_name, whole_int


class LevelsMixin:
    # ---- creation & leveling ----
    @rules_errors
    def create_from_spec(self, spec: dict, owner_id: Optional[int] = None, owner_name: Optional[str] = None) -> Character:
        """Create a level 1 D&D 5e character. `spec` is described in rules.creation.create_character."""
        spec = dict(spec)
        spec["name"] = valid_name(spec.get("name", ""), "Character name")
        with self.lock:
            if spec["name"] in self.names():
                raise ServiceError(f"Character '{spec['name']}' already exists.")
            char = create_character(spec)
            char.save()
            if owner_id is not None:
                self.players.assign(owner_id, char.name, owner_name)
            self._commit(char, f"Created {char.race_display} {char.class_summary}: {char.name}",
                         f"🆕 **{char.name}** the {char.race_display} {char.class_summary} joins the party!")
        return char

    @rules_errors
    def create_quick(self, options: dict, owner_id: Optional[int] = None, owner_name: Optional[str] = None) -> Character:
        """A ready-to-play character of any level: race, class and level chosen, everything else decided by
        rules.quickgen (see there for the options). Without a name it gets a fresh one in the style of its race."""
        opts = dict(options)
        with self.lock:
            taken = set(self.names())
            if (opts.get("name") or "").strip():
                opts["name"] = valid_name(opts["name"], "Character name")
                if opts["name"] in taken:
                    raise ServiceError(f"Character '{opts['name']}' already exists.")
            else:
                rnd = random.Random(opts.get("seed"))
                for _ in range(50):
                    opts["name"] = quickgen.random_name(opts.get("race") or "", opts.get("gender") or "", rnd)
                    if opts["name"] not in taken:
                        break
            char = quickgen.generate(opts)
            char.save()
            if owner_id is not None:
                self.players.assign(owner_id, char.name, owner_name)
            self._commit(char, f"Created {char.race_display} {char.class_summary}: {char.name} (quick, level {char.total_level})",
                         f"🆕 **{char.name}** the {char.race_display} {char.class_summary} joins the party!")
        return char

    @rules_errors
    def plan_level_up(self, name: str, class_name: str, subclass: Optional[str] = None) -> dict:
        return LV.plan_level_up(self.get(name), class_name, subclass)

    @rules_errors
    def level_up(self, name: str, class_name: str, choices: dict, replay: bool = False) -> Character:
        with self.lock:
            char = self.get(name)
            if not char.is_created:
                raise ServiceError(f"{name} hasn't been created with the D&D 5e system.")
            if char.total_level >= E.MAX_LEVEL:
                raise ServiceError("Characters cannot go beyond level 20.")
            if not replay and not char.d["choices"].get("milestone") and char.total_level >= char.level_from_xp:
                need = E.xp_for_next_level(char.total_level)
                raise ServiceError(f"{name} needs {need} XP for level {char.total_level + 1} "
                                   f"(or enable milestone leveling).")
            if replay:                                          # a recorded level taken again (Edit levels)
                choices = LV.fit_prepared(char, class_name, choices)
            trial = Character.from_dict(char.d)
            LV.apply_level_up(trial, class_name, choices)       # validate on a copy so a refused level leaves no history
            char.snapshot_level(class_name, choices)
            LV.apply_level_up(char, class_name, choices)
            self._commit(char, f"{char.name} reached level {char.total_level} ({char.class_summary})",
                         f"⬆️ **{char.name}** reached level **{char.total_level}** ({char.class_summary})!")
        return char

    # ---- edit levels: step back to an earlier level and redo it (later levels are replayed from their recorded choices)
    def _complete(self, char: Character) -> bool:
        return len(char.d.get("level_history", [])) >= max(0, char.total_level - 1)

    def level_history(self, name: str) -> List[dict]:
        """One row per editable level (2..N). Characters without a full record are rebuilt from their sheet when edited."""
        char = self.get(name)
        history = char.d.get("level_history", [])
        if self._complete(char):
            return [{"index": i, "level": e["level"] + 1, "before": e["summary"], "class": e.get("class"),
                     "recorded": e.get("choices") is not None} for i, e in enumerate(history)]
        rows, order = [], []
        for entry in char.classes:
            order += [entry["name"]] * entry["level"]
        offset = (char.total_level - 1) - len(history)                 # recorded entries cover the last levels only
        for i in range(char.total_level - 1):
            j = i - offset
            rows.append({"index": i, "level": i + 2, "before": f"level {i + 1}", "class": order[i + 1],
                         "recorded": 0 <= j < len(history) and history[j].get("choices") is not None})
        return rows

    def begin_edit(self, name: str, index: int) -> dict:
        """Go back to just before the level at `index` (0 = level 2). Returns the undone levels, in order (class and the
        choices made then) so the caller can redo them. A character without a full record is first rebuilt from its
        sheet. A backup is kept until finish_edit / cancel_edit."""
        with self.lock:
            char = self.get(name)
            if not 0 <= int(index) < max(0, char.total_level - 1):
                raise ServiceError("That level can't be edited (the first level comes from character creation).")
            self._edit_backups[name] = copy.deepcopy(char.d)
            if not self._complete(char):
                history = char.d.get("level_history", [])
                offset = (char.total_level - 1) - len(history)
                recorded = [None] + [None] * offset + [e.get("choices") for e in history]
                char = reconstruct(char, recorded)
                char.save()
            history = char.d["level_history"]
            undone = [{"class": e.get("class"), "choices": e.get("choices"), "level": e["level"] + 1} for e in history[int(index):]]
            for _ in undone:
                char.revert_level()
            self._commit(char, f"{char.name} is being edited from level {undone[0]['level']}")
        return {"queue": undone}

    def reset_levels(self, name: str, entries: list, origin: Optional[dict] = None) -> Character:
        """RESET ALL: rebuild the character from level 0, taking each class level with the given choices
        ([{class, choices}] from the first level to the last). With `origin` (race, subrace, ancestry, race_choices,
        background, background_choices, scores_method, scores, alignment, details) the creation choices are made again
        too; otherwise race, background and scores stay. Gear, notes and the rest of the sheet always stay."""
        if not entries:
            raise ServiceError("A character needs at least one class level.")
        with self.lock:
            char = self.get(name)
            try:
                work = origin_base(char, origin) if origin else base_of(char)
            except LV.RulesError as err:
                raise ServiceError(f"Creation choices: {err}")
            for i, e in enumerate(entries):
                e = dict(e, choices=LV.fit_prepared(work, e["class"], e["choices"]))
                try:
                    trial = Character.from_dict(work.d)
                    LV.apply_level_up(trial, e["class"], e["choices"])
                except LV.RulesError as err:
                    raise ServiceError(f"Level {i + 1} ({e['class']}): {err}")
                work.snapshot_level(e["class"], e["choices"])
                LV.apply_level_up(work, e["class"], e["choices"])
            work.d["level_history"] = work.d["level_history"][1:]
            keep_hand_edits(char, work)
            work.d["conditions"] = list(char.d["conditions"])
            self._commit(work, f"{name} was rebuilt from level 1 ({work.class_summary})")
        return work

    def cancel_edit(self, name: str) -> Character:
        with self.lock:
            backup = self._edit_backups.pop(name, None)
            if backup is None:
                raise ServiceError("There is no edit to cancel.")
            char = Character.from_dict(backup)
            self._commit(char, f"{char.name}: level edit cancelled, original restored")
        return char

    def finish_edit(self, name: str) -> None:
        backup = self._edit_backups.pop(name, None)
        if backup is None:
            self.h.notify(events.CHARACTERS)
            return
        with self.lock:
            char = self.get(name)
            keep_hand_edits(Character.from_dict(backup), char)
            self._commit(char, f"{char.name}: level edit finished ({char.class_summary})")

    def revert_level(self, name: str) -> Character:
        """Undo the last level-up so its choices can be made again."""
        with self.lock:
            char = self.get(name)
            if not char.can_revert:
                raise ServiceError(f"{char.name} has no level-up to undo.")
            before = char.class_summary
            was = Character.from_dict(char.d)
            char.revert_level()
            keep_hand_edits(was, char)
            self._commit(char, f"{char.name} undid a level-up ({before} -> {char.class_summary})",
                         f"↩️ **{char.name}** went back to **{char.class_summary}**.")
        return char

    @rules_errors
    def autolevel(self, name: str, class_name: str) -> Character:
        with self.lock:
            char = self.get(name)
            char.snapshot_level(class_name, None)
            LV.autolevel(char, class_name)
            self._commit(char, f"{char.name} auto-leveled to {char.total_level} ({char.class_summary})")
        return char

    def set_milestone(self, name: str, enabled: bool) -> Character:
        with self.lock:
            char = self.get(name)
            char.d["choices"]["milestone"] = bool(enabled)
            self._commit(char, f"Milestone leveling {'on' if enabled else 'off'} for {char.name}")
        return char

    def add_xp(self, name: str, amount) -> Character:
        amount = whole_int(amount, "XP", -10 ** 9, 10 ** 9)
        with self.lock:
            char = self.get(name)
            before = char.level_from_xp
            char.xp = max(0, char.xp + amount)
            msg = f"{char.name} gained {amount} XP (total {char.xp})"
            discord = f"✨ **{char.name}** gained **{amount} XP**"
            if char.level_from_xp > before and char.total_level < char.level_from_xp:
                discord += f" — ready to reach level {char.level_from_xp}!"
            self._commit(char, msg, discord)
        return char
