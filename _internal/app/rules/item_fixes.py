"""Corrections to the imported magic item data, made once when the items load (rules.items).

The 5etools numbers are mostly right; these are the ones the battle and the sheet would otherwise get wrong:
    staffs that are quarterstaffs (Staff of Striking, Staff of Power...) come without the weapon flag: they get it, so they
        are wielded with their +N;
    "+1 to AC and saving throws" read as +4 to saves (Netherese Ring of Protection): the text's number wins;
    a deck's cards (Deck of Wonder) aren't worn bonuses: no saves or resistances from holding the deck;
    AC only without armour and shield (Bracers of Defense): `unarmored_only`, the sheet checks it;
    AC only against ranged attacks (Arrow-Catching Shield): `bonus_ac_ranged` instead of `bonus_ac` (wondrous.py);
    ability increases (Belt of Dwarvenkind, Ioun stones +2): `ability_max` from "to a maximum of N"; manuals and tomes
        raise a score for good once read, never while carried: `ability_permanent`;
    +N to unarmed strikes (Wraps of Unarmed Prowess, Eldritch Claw Tattoo): `unarmed_bonus`, the sheet's unarmed strike;
    +N to one skill's checks (Eyes of Deceit, Ring of Candor, Gloves of Thievery): `bonus_skill` {skill: n}, the sheet's skill bonus;
    a Mythallar Bracelet's three beads: three `charges`; charges told only in the text (Ring of Three Wishes): `charges`;
    a weapon attacking with Intelligence instead of Strength (Moonlight Greatsword): `int_weapon`, the sheet's attacks.
"""
import re

_AC_SAVES = re.compile(r"gain a \+(\d) bonus to AC and saving throws", re.I)
_UNARMORED = re.compile(r"if you are wearing no armor and using no shield|if you do not wear armor or use a shield", re.I)


def fix_item(i: dict) -> None:
    text = i.get("text") or ""
    if i.get("dmg1") and i.get("category") in ("simple", "martial") and not i.get("weapon") and i.get("type") not in ("A", "AF"):
        i["weapon"] = True
    m = _AC_SAVES.search(text)
    if m and i.get("bonus_save") and i["bonus_save"] != int(m.group(1)):
        i["bonus_save"] = int(m.group(1))
    if i.get("name", "").startswith("Deck of"):
        for k in ("bonus_save", "bonus_ac", "resist"):
            i.pop(k, None)
    if i.get("bonus_ac") and "transfer some or all of the sword's bonus to your Armor Class" in text:
        i.pop("bonus_ac")                         # a Defender: AC only when its bonus is moved (itempowers.py), not always +1
    if i.get("bonus_ac") and _UNARMORED.search(text):
        i["unarmored_only"] = True
    elif i.get("bonus_ac") and re.search(r"bonus to AC if you aren't using a shield", text):
        i["no_shield_only"] = True                # a Badge of the Watch
    if i.get("bonus_ac") and re.search(r"bonus to AC against ranged attacks", text):
        i["bonus_ac_ranged"] = i.pop("bonus_ac")
    m = re.search(r"\+(\d) bonus to (?:the )?attack (?:rolls )?and (?:the )?damage rolls (?:of|with|made with|you make with) (?:your )?unarmed strikes",
                  text)
    if m and not i.get("weapon"):
        i["unarmed_bonus"] = int(m.group(1))
    if i.get("type") == "MA" and re.search(r"apply your full Dexterity modifier \(instead of a maximum of \+2\)", text):
        i["full_dex"] = True                      # Serpent Scale Armor: medium armour without the Dex cap
    if re.search(r"hit point maximum increases by 1 for each level you have attained", text):
        i["hp_per_level"] = 1                     # a Berserker Axe while attuned
    m = re.search(r"\+(\d+) bonus to initiative", text)
    if m and not i.get("weapon"):
        i["bonus_init"] = int(m.group(1))         # Scorpion Armor: +5 (the sheet's initiative)
    ab = i.get("ability")
    if isinstance(ab, dict) and any(isinstance(v, int) for v in ab.values()):
        m = re.search(r"to a maximum of (\d+)", text)
        if m:
            i["ability_max"] = int(m.group(1))
        if re.search(r"^(?:Manual|Tome) of", i.get("name", "")) or re.search(r"48 hours over a period of 6 days|spend 80 hours reading", text):
            i["ability_permanent"] = True
    for m in re.finditer(r"\+(\d) bonus to (?:Strength|Dexterity|Constitution|Intelligence|Wisdom|Charisma) \(([A-Z][\w ]+)\) checks(?!\s+made to)", text):
        if i.get("name") != "Gloves of Swimming and Climbing":
            i.setdefault("bonus_skill", {})[m.group(2)] = int(m.group(1))     # Eyes of Deceit, Ring of Candor, Gloves of Thievery (Sleight of Hand)
    if i.get("name") == "Mythallar Bracelet":
        i["charges"] = 3                          # its three beads (each a use; the item keeps no recharge)
    m = None if i.get("charges") or "gains a charge, to a maximum" in text else \
        re.search(r"\b(?:has|of its|with) (\d+d\d+(?: ?[+-] ?\d+)?|\d+) charges\b", text)
    if m:                                         # charges only in the text (Ring of Three Wishes' 3, Staff of Charming's 10, a Planar Key's 1d4 + 1)
        i["charges"] = int(m.group(1)) if m.group(1).isdigit() else m.group(1)
    if i.get("weapon") and re.search(r"you can use your Intelligence modifier,? instead of Strength,? for the attack and damage rolls", text):
        i["int_weapon"] = True                    # a Moonlight Greatsword: the sheet's attack uses Intelligence when it is better
