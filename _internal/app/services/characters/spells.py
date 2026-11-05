"""Casting, spell slots, prepared spells, the spellbook and limited-use class resources."""
from typing import List

from ...rules import engine as E
from ...rules import leveling as LV
from ...rules import spellcasting as SC
from ...rules.character import Character
from ...rules.data import rules
from ...rules.resources import resource_list
from ..common import ServiceError, rules_errors, whole_int


class SpellsMixin:
    # ---- spells ----
    def cast_spell(self, name: str, spell_name: str, slot=None, ritual: bool = False) -> dict:
        """Cast a known/prepared spell, spending a slot (or none for cantrips, rituals and innate spells).

        `slot` is a spell level (1-9) or 'pact'. Defaults to the lowest slot that works.
        Returns {'spell', 'slot', 'text', 'char'}.
        """
        with self.lock:
            char = self.get(name)
            available = {}
            for s in SC.spell_known_or_prepared(char):
                if s["name"].lower() not in available or not self._innate_spent(char, s):
                    available[s["name"].lower()] = s  # a spent innate copy doesn't hide the class one (tiefling warlock)
            spell = available.get(spell_name.strip().lower())
            if not spell:
                raise ServiceError(f"{char.name} doesn't have {spell_name} known or prepared.")
            used_slot = None
            if spell["level"] == 0:
                note = "cantrip"
            elif spell.get("uses"):                    # innate (racial / feat): at will, or N per rest
                uses = spell["uses"]
                match = SC.innate_limit(char, uses)             # "1/long rest", "pb/long rest" (Star Map)
                if match:
                    key, limit = f"spell:{spell['name']}", match[0]
                    if char.d["resources"].get(key, 0) >= limit:
                        raise ServiceError(f"{spell['name']} has no uses left until your next {match[1]} rest.")
                    char.d["resources"][key] = char.d["resources"].get(key, 0) + 1
                note = f"innate, {uses}"
            elif ritual:
                info = next((i for i in SC.casters(char) if i["class"] == spell["cast_class"]), None)
                if not spell["ritual"] or not ((info and info["ritual"]) or spell.get("feat_ritual")):
                    raise ServiceError(f"{spell['name']} can't be cast as a ritual by {char.name}.")
                note = "ritual (10 extra minutes, no slot)"
            else:
                used_slot = self._spend_slot(char, spell["level"], slot)
                note = f"{'pact' if used_slot == SC.PACT_KEY else E.ordinal(int(used_slot))}-level slot"
            ability = spell["ability"]
            text = (f"✨ **{char.name}** cast **{spell['name']}** ({note}). "
                    f"Save DC {8 + char.proficiency_bonus + char.mod(ability)}, "
                    f"spell attack {char.proficiency_bonus + char.mod(ability):+d}.")
            self._commit(char, f"{char.name} cast {spell['name']} ({note})", text)
        return {"spell": spell, "slot": used_slot, "text": text, "char": char}

    @staticmethod
    def _innate_spent(char: Character, spell: dict) -> bool:
        return SC.innate_spent(char, spell)

    def _spend_slot(self, char: Character, spell_level: int, choice) -> str:
        remaining = SC.slots_remaining(char)
        if choice is None:
            options = [lvl for lvl in sorted(int(k) for k in remaining if k != SC.PACT_KEY)
                       if lvl >= spell_level and remaining[str(lvl)] > 0]
            if options:
                choice = options[0]
            elif SC.PACT_KEY in remaining and remaining[SC.PACT_KEY] > 0 and SC.spell_slots(char)["pact"]["level"] >= spell_level:
                choice = SC.PACT_KEY
        if choice is None:
            raise ServiceError(f"No spell slot of level {spell_level} or higher is available.")
        key = SC.PACT_KEY if choice == SC.PACT_KEY else str(int(choice))
        pact = SC.spell_slots(char)["pact"]
        if key != SC.PACT_KEY and remaining.get(key, 0) <= 0 and pact and pact["level"] == int(key) and remaining.get(SC.PACT_KEY, 0) > 0:
            key = SC.PACT_KEY                          # a warlock asked for its pact slot by level
        if key != SC.PACT_KEY and int(key) < spell_level:
            raise ServiceError(f"A level {key} slot is too low for a level {spell_level} spell.")
        if key == SC.PACT_KEY and SC.spell_slots(char)["pact"]["level"] < spell_level:
            raise ServiceError("Your pact slots are too low for that spell.")
        if remaining.get(key, 0) <= 0:
            raise ServiceError(f"No {'pact' if key == SC.PACT_KEY else 'level ' + key} slots left.")
        char.d["slots_used"][key] = char.d["slots_used"].get(key, 0) + 1
        return key

    def set_slot_used(self, name: str, key: str, used) -> Character:
        """Manually correct how many slots of a level ('1'-'9' or 'pact') are used."""
        with self.lock:
            char = self.get(name)
            total = SC.spell_slots(char)
            maximum = total["pact"]["slots"] if key == SC.PACT_KEY and total["pact"] else \
                (total["slots"][int(key) - 1] if key != SC.PACT_KEY else 0)
            char.d["slots_used"][key] = whole_int(used, "Used slots", 0, maximum)
            self._commit(char, f"{char.name} used {key} slots set to {used}")
        return char

    @rules_errors
    def set_prepared(self, name: str, class_name: str, spells: List[str]) -> Character:
        with self.lock:
            char = self.get(name)
            LV.set_prepared(char, class_name, spells)
            self._commit(char, f"{char.name} prepared {len(spells)} {class_name} spells")
        return char

    @rules_errors
    def add_spellbook_spell(self, name: str, spell: str) -> Character:
        """A wizard copies a found spell into their spellbook."""
        with self.lock:
            char = self.get(name)
            info = next((i for i in SC.casters(char) if i["spellbook"]), None)
            data = rules.spell(spell)
            if not info or not data:
                raise ServiceError("Only wizards have spellbooks, and the spell must exist.")
            sp = SC.class_spells(char, "Wizard")
            if data["name"] in sp["spellbook"]:
                raise ServiceError(f"{data['name']} is already in the spellbook.")
            if data["level"] < 1 or data["level"] > info["max_spell_level"] or "Wizard" not in data["classes"]:
                raise ServiceError(f"{data['name']} isn't a wizard spell you can copy (level 1-{info['max_spell_level']}).")
            sp["spellbook"].append(data["name"])
            char.d["choices"].setdefault("copied_spells", []).append(data["name"])     # kept when the levels are rebuilt
            self._commit(char, f"{char.name} copied {data['name']} into their spellbook")
        return char

    # ---- class resources ----
    def use_resource(self, name: str, resource: str, amount: int = 1) -> Character:
        with self.lock:
            char = self.get(name)
            res = next((r for r in resource_list(char) if r["name"].lower() == resource.lower()), None)
            if not res:
                raise ServiceError(f"{char.name} has no resource called '{resource}'.")
            used = char.d["resources"].get(res["name"], 0)
            if res["max"] is not None and used + amount > res["max"]:
                raise ServiceError(f"Only {res['max'] - used} use(s) of {res['name']} left.")
            char.d["resources"][res["name"]] = max(0, used + amount)
            self._commit(char, f"{char.name} used {res['name']} ({amount})")
        return char
