"""Notes, personal details and hand-set proficiencies."""
from typing import List, Optional

from ...rules import engine as E
from ...rules.character import Character
from ..common import ServiceError


class DetailsMixin:
    # ---- situational feat switches (Great Weapon Master's power attack, Sentinel...) ----
    def set_toggle(self, name: str, key: str, value) -> None:
        """Turn a situational feat's switch on or off (or pick its option); see rules/combat_feats.py."""
        from ...rules import combat_feats as CF
        with self.lock:
            char = self.get(name)
            try:
                CF.set_toggle(char, key, value)
            except KeyError:
                raise ServiceError(f"{char.name} doesn't have that feat.")
            except ValueError as e:
                raise ServiceError(str(e))
            f = CF.FEATS[key]
            on = CF.is_on(char, key)
            self._commit(char, f"{char.name}: {f['feat']} " + (f"set to {on}" if f["kind"] == "option" else "on" if on else "off"))

    # ---- notes & details ----
    def add_note(self, name: str, text: str) -> int:
        text = (text or "").strip()
        if not text:
            raise ServiceError("Note text cannot be empty.")
        with self.lock:
            char = self.get(name)
            note_id = char.add_note(text)
            self._commit(char, f"Added note #{note_id} to {char.name}: '{text}'")
        return note_id

    def edit_note(self, name: str, note_id: int, text: str) -> None:
        with self.lock:
            char = self.get(name)
            for note in char.notes:
                if note["id"] == note_id:
                    if note["text"] == text:
                        return
                    note["text"] = text
                    self._commit(char, f"Updated note #{note_id} for {char.name}")
                    return
        raise ServiceError(f"Note #{note_id} not found.")

    def remove_note(self, name: str, note_id: int) -> None:
        with self.lock:
            char = self.get(name)
            if not char.remove_note(note_id):
                raise ServiceError(f"Note #{note_id} not found.")
            self._commit(char, f"Removed note #{note_id} from {char.name}")

    def update_details(self, name: str, **fields) -> Character:
        with self.lock:
            char = self.get(name)
            if "alignment" in fields:
                if fields["alignment"] and fields["alignment"] not in E.ALIGNMENTS:
                    raise ServiceError("Pick an alignment from the list.")
                char.alignment = fields.pop("alignment")
            for key, value in fields.items():
                if key not in char.details:
                    raise ServiceError(f"Unknown detail '{key}'.")
                char.details[key] = value
            self._commit(char, f"Updated details of {char.name}")
        return char

    def set_portrait(self, name: str, portrait: Optional[dict]) -> Character:
        """Give a character its own picture, or None to go back to the automatic one (its race in its main class).
        portrait: {'png': the token (PNG bytes), 'framed': it has its own border, 'inner': the picture without the
        border (PNG bytes, for editing it again), 'border': the border's settings}."""
        from ...core import portraits
        if portrait and not portrait.get("png"):
            raise ServiceError("The portrait has no picture.")
        with self.lock:
            char = self.get(name)
            char.d["portrait"] = portraits.save_choice(portrait) if portrait else {}
            self._commit(char, f"{char.name}: " + ("new portrait" if portrait else "automatic portrait"))
        return char

    def set_proficiencies(self, name: str, kind: str, values: List[str]) -> Character:
        """Replace a character's armor, weapon, tool or language proficiencies (e.g. swap a racial language).
        Additions are remembered as 'added by hand', so the sheet can tell them apart from granted ones."""
        if kind not in ("armor", "weapons", "tools", "languages"):
            raise ServiceError(f"Unknown proficiency kind '{kind}'.")
        with self.lock:
            char = self.get(name)
            old = char.d["proficiencies"][kind]
            new = list(dict.fromkeys(str(v).strip() for v in values if str(v).strip()))
            manual = char.d["choices"].setdefault("manual_profs", {})
            mine = [v for v in manual.get(kind, []) if v in new] + [v for v in new if v not in old and v not in manual.get(kind, [])]
            removed = char.d["choices"].setdefault("manual_removed", {})        # granted ones taken off (kept off on a rebuild)
            removed[kind] = [v for v in removed.get(kind, []) if v not in new] + \
                [v for v in old if v not in new and v not in manual.get(kind, []) and v not in removed.get(kind, [])]
            manual[kind] = mine
            added, removed = [v for v in new if v not in old], [v for v in old if v not in new]
            char.d["proficiencies"][kind] = new
            self._commit(char, f"{char.name}: {kind} proficiencies" + (f" +{', '.join(added)}" if added else "")
                         + (f" -{', '.join(removed)}" if removed else ""))
        return char
