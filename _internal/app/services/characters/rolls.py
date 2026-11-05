"""Checks, saves, attacks and damage rolled for a character (and announced to the Discord log)."""
import re
from typing import Optional

from ...rules import engine as E
from ...rules import spellcasting as SC
from ...rules.character import Character, SKILLS
from ...rules.data import rules
from ..common import RollResult, ServiceError, plain_text, roll_damage_expression


class RollsMixin:
    # ---- rolls ----
    def roll_check(self, name: str, what: str, advantage: Optional[str] = None, who: Optional[str] = None) -> RollResult:
        """A skill check ('Stealth'), an ability check ('Strength'), or initiative."""
        with self.lock:
            char = self.get(name)
        key = what.strip().lower()
        if key in ("initiative", "init"):
            bonus, label = char.initiative, "Initiative"
        elif key in E.NAME_TO_ABILITY or key in E.ABILITIES:
            ability = E.NAME_TO_ABILITY.get(key, key)
            bonus, label = char.mod(ability), f"{E.ABILITY_NAMES[ability]} check"
        else:
            skill = next((s for s in SKILLS if s.lower() == key), None)
            if not skill:
                raise ServiceError(f"'{what}' isn't a skill or ability.")
            bonus, label = char.skill_bonus(skill)["bonus"], f"{skill} check"
        return self._d20(char, label, bonus, advantage, who)

    def roll_save(self, name: str, ability: str, advantage: Optional[str] = None, who: Optional[str] = None) -> RollResult:
        char = self.get(name)
        key = ability.strip().lower()
        ab = E.NAME_TO_ABILITY.get(key, key)
        if ab not in E.ABILITIES:
            raise ServiceError(f"'{ability}' isn't an ability.")
        sv = char.saving_throws()[ab]
        return self._d20(char, f"{E.ABILITY_NAMES[ab]} saving throw", sv["bonus"], advantage, who)

    def roll_attack(self, name: str, weapon: str, advantage: Optional[str] = None, who: Optional[str] = None) -> RollResult:
        char = self.get(name)
        low = weapon.strip().lower()
        atk = next((a for a in char.attacks() if a["name"].lower() == low or low in a["name"].lower()), None)
        if not atk:
            raise ServiceError(f"{char.name} has no equipped weapon matching '{weapon}'.")
        result = self._d20(char, f"{atk['name']} attack", atk["attack"], advantage, who)
        result.text += f"  •  damage {atk['damage']}"
        return result

    def attack_roll_and_damage(self, name: str, weapon: str, advantage: Optional[str] = None, who: Optional[str] = None) -> RollResult:
        """One button: roll the attack, then the damage (doubled dice on a natural 20; no damage on a natural 1)."""
        hit = self.roll_attack(name, weapon, advantage, who)
        if hit.natural == 1:
            return RollResult(hit.total, hit.text.split("  •  damage")[0] + " — automatic miss.", 1)
        dmg = self.roll_damage(name, weapon, crit=hit.natural == 20, who=who)
        return RollResult(dmg.total, hit.text.split("  •  damage")[0] + "\n" + dmg.text, hit.natural)

    def roll_damage(self, name: str, weapon: str, crit: bool = False, two_handed: bool = False,
                    who: Optional[str] = None) -> RollResult:
        """Roll a weapon's damage. A critical hit doubles the dice (not the modifier)."""
        char = self.get(name)
        low = weapon.strip().lower()
        atk = next((a for a in char.attacks() if a["name"].lower() == low or low in a["name"].lower()), None)
        if not atk:
            raise ServiceError(f"{char.name} has no equipped weapon matching '{weapon}'.")
        dice = atk["versatile"] if two_handed and atk["versatile"] else atk["dice"]
        bonus = atk["bonus"]
        if crit and dice:
            dice = E.double_dice(dice)
        expr = (f"{dice}{bonus:+d}" if bonus else dice) if dice else str(bonus)
        result = roll_damage_expression(expr)
        label = f"{atk['name']} {'critical ' if crit else ''}damage{' (two-handed)' if two_handed else ''}"
        text = f"💥 **{char.name}** {label}: **{result.total}** {atk['type']}  *({result.breakdown})*"
        self._record_roll(who or char.name, label, f"{result.total} ({result.breakdown})")
        self.h.log(f"{char.name} {label}: {result.total}")
        self._announce_roll("💥", char.name, label, result.total, f"{atk['type']} *({result.breakdown})*")
        return RollResult(result.total, text)

    DAMAGE_RE = re.compile(r"(\d+)d(\d+)(?:\s*\+\s*(\d+))?\s+(\w+)\s+damage")

    def spell_damage_expr(self, char: Character, spell: dict, slot=None, crit: bool = False) -> Optional[tuple]:
        """(dice expression, damage type) for a spell that deals damage, scaled by character level (cantrips) or slot."""
        if "{" in spell["text"]:
            return None
        m = self.DAMAGE_RE.search(spell["text"])
        if not m:
            return None
        count, die, flat, kind = int(m.group(1)), int(m.group(2)), int(m.group(3) or 0), m.group(4)
        level = spell["level"]
        slot_level = level if slot in (None, SC.PACT_KEY) else int(slot)
        if slot == SC.PACT_KEY:
            pact = SC.spell_slots(char)["pact"]
            slot_level = pact["level"] if pact else level
        if spell["name"] == "Magic Missile":                      # one dart = 1d4+1; one more dart per slot level
            darts = 3 + max(0, slot_level - 1)
            count, die, flat = darts, 4, darts
        elif level == 0:
            count *= 1 + (char.total_level >= 5) + (char.total_level >= 11) + (char.total_level >= 17)
        else:
            extra = re.search(r"damage increases by (\d+)d(\d+) for each slot level above", spell["higher_level"] or "")
            if extra and slot_level > level:
                count += int(extra.group(1)) * (slot_level - level)
        if crit:
            count *= 2
        return (f"{count}d{die}" + (f"+{flat}" if flat else ""), kind)

    def spell_damage(self, name: str, spell_name: str, slot=None, crit: bool = False,
                     who: Optional[str] = None) -> RollResult:
        """Roll the damage of a spell the character knows (after the player confirms it hit)."""
        char = self.get(name)
        spell = rules.spell(spell_name)
        found = self.spell_damage_expr(char, spell, slot, crit) if spell else None
        if not found:
            raise ServiceError(f"{spell_name} doesn't deal rollable damage.")
        expr, kind = found
        result = roll_damage_expression(expr)
        label = f"{spell['name']} {'critical ' if crit else ''}damage"
        text = f"💥 **{char.name}** {label}: **{result.total}** {kind}  *({result.breakdown})*"
        self._record_roll(who or char.name, label, f"{result.total} ({result.breakdown})")
        self.h.log(f"{char.name} {label}: {result.total}")
        self._announce_roll("💥", char.name, label, result.total, f"{kind} *({result.breakdown})*")
        return RollResult(result.total, text)

    def use_item(self, name: str, item: str) -> str:
        """Use up one consumable (potion, ration, scroll, oil...). Healing potions heal automatically."""
        with self.lock:
            char = self.get(name)
            entry = char.find_item(item)
            if not entry:
                raise ServiceError(f"{char.name} doesn't have '{item}'.")
            data = rules.item(entry["name"])
            text = f"🧪 **{char.name}** used **{entry['name']}**."
            if data:
                match = re.search(r"regain (\d+d\d+(?: ?\+ ?\d+)?) hit points", data["text"])
                if match:
                    roll = roll_damage_expression(match.group(1).replace(" ", ""))
                    healed = char.heal(roll.total)
                    text = (f"🧪 **{char.name}** drank **{entry['name']}** and healed **{healed}** HP "
                            f"*({roll.breakdown})* — HP {char.current_hp}/{char.max_hp}")
                elif data["type"] == "FD" or "ration" in entry["name"].lower():
                    text = f"🍖 **{char.name}** ate **{entry['name']}**."
                elif data["type"] == "SC":
                    text = f"📜 **{char.name}** read **{entry['name']}**: {data['text'].split('.')[0]}."
            char.remove_item(entry["name"], 1)
            self._commit(char, plain_text(text), text)
        return text

    def use_slot(self, name: str, key: str) -> Character:
        with self.lock:
            char = self.get(name)
            if SC.slots_remaining(char).get(key, 0) <= 0:
                raise ServiceError(f"No {'pact' if key == SC.PACT_KEY else 'level ' + key} slots left.")
            char.d["slots_used"][key] = char.d["slots_used"].get(key, 0) + 1
            self._commit(char, f"{char.name} used a {key} spell slot")
        return char

    def restore_slot(self, name: str, key: str) -> Character:
        with self.lock:
            char = self.get(name)
            used = char.d["slots_used"].get(key, 0)
            if used <= 0:
                raise ServiceError("That slot isn't used.")
            char.d["slots_used"][key] = used - 1
            self._commit(char, f"{char.name} recovered a {key} spell slot")
        return char

    def _d20(self, char: Character, label: str, bonus: int, advantage: Optional[str], who: Optional[str]) -> RollResult:
        total, rolls = E.roll_d20(bonus, advantage)
        kept = (max(rolls) if advantage == "adv" else min(rolls) if advantage == "dis" else rolls[0])
        dice = f"[{', '.join(map(str, rolls))}]" + (" adv" if advantage == "adv" else " dis" if advantage == "dis" else "")
        text = f"🎲 **{char.name}** {label}: **{total}** (d20 {dice} {bonus:+d})"
        if kept == 20:
            text += " — **Natural 20!**"
        elif kept == 1:
            text += " — **Natural 1!**"
        self._record_roll(who or char.name, label, f"{total} ({dice} {bonus:+d})")
        self.h.log(f"{char.name} {label}: {total}")
        self._announce_roll("🎲", char.name, label, total, f"d20 {dice} {bonus:+d}"
                            + (" · **NAT 20**" if kept == 20 else " · **NAT 1**" if kept == 1 else ""))
        return RollResult(total, text, kept)
