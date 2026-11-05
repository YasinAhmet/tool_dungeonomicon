"""Limited-use class resources (Rage, Ki, Channel Divinity...) derived from class and level."""
from typing import List, Optional

from .character import Character

UNLIMITED = None


def _num(value) -> Optional[int]:
    text = str(value)
    if "unlimited" in text.lower():
        return UNLIMITED
    digits = "".join(ch for ch in text if ch.isdigit())
    return int(digits) if digits else 0


def resource_list(char: Character) -> List[dict]:
    """[{'name', 'max' (None = unlimited), 'recharge' ('short'|'long'), 'used'}] for the current build."""
    out: List[dict] = []

    def add(name, maximum, recharge):
        out.append({"name": name, "max": maximum, "recharge": recharge,
                    "used": min(char.d["resources"].get(name, 0), maximum or 0) if maximum else 0})

    lv = char.class_level
    cha = max(1, char.mod("cha"))
    if lv("Barbarian"):
        add("Rage", _num(char.table_value("Barbarian", "Rages", "0")), "long")
    if lv("Bard"):
        add("Bardic Inspiration", cha, "short" if lv("Bard") >= 5 else "long")
    if lv("Cleric") >= 2:
        add("Channel Divinity (Cleric)", 1 if lv("Cleric") < 6 else 2 if lv("Cleric") < 18 else 3, "short")
    if lv("Cleric") >= 10:
        add("Divine Intervention", 1, "long")
    if lv("Druid") >= 2:
        add("Wild Shape", UNLIMITED if lv("Druid") >= 20 else 2, "short")     # Archdruid: as often as you like
    if lv("Fighter"):
        add("Second Wind", 1, "short")
    if lv("Fighter") >= 2:
        add("Action Surge", 2 if lv("Fighter") >= 17 else 1, "short")
    if lv("Fighter") >= 9:
        add("Indomitable", 3 if lv("Fighter") >= 17 else 2 if lv("Fighter") >= 13 else 1, "long")
    fighter = char.class_entry("Fighter")
    extra = (1 if "Martial Adept" in char.d["feats"] else 0) + (1 if char.has_option("Superior Technique") else 0)
    if fighter and fighter.get("subclass") == "Battle Master" and lv("Fighter") >= 3:
        add("Superiority Dice", (6 if lv("Fighter") >= 15 else 5 if lv("Fighter") >= 7 else 4) + extra, "short")
    elif extra:                                         # Martial Adept, the Superior Technique fighting style: d6s
        add("Superiority Dice", extra, "short")
    if lv("Monk") >= 2:
        add("Ki Points", _num(char.table_value("Monk", "Ki Points", "0")), "short")
    if lv("Paladin"):
        add("Lay on Hands (HP pool)", 5 * lv("Paladin"), "long")
        add("Divine Sense", max(1, 1 + char.mod("cha")), "long")
    if lv("Paladin") >= 3:
        add("Channel Divinity (Paladin)", 1, "short")
    adept = 2 if "Metamagic Adept" in char.d["feats"] else 0          # the feat's own 2 sorcery points (for its Metamagic)
    if lv("Sorcerer") >= 2:
        add("Sorcery Points", _num(char.table_value("Sorcerer", "Sorcery Points", "0")) + adept, "long")
    elif adept:
        add("Sorcery Points", adept, "long")
    if lv("Wizard"):
        add("Arcane Recovery", 1, "long")
    wizard = char.class_entry("Wizard")
    if wizard and wizard.get("subclass") == "Bladesinging" and lv("Wizard") >= 2:
        add("Bladesong", char.proficiency_bonus, "long")
    return out
