"""Spellcasting rules: slots, spells known/prepared limits, eligible spell lists, save DC and attack."""
import re
from typing import Dict, List, Optional

from . import engine as E
from .character import Character
from .data import rules

PACT_KEY = "pact"
# Eldritch Knight / Arcane Trickster: most spells must come from two schools; one spell each at these
# class levels may be from any school.
SUBCLASS_SCHOOLS = {"Eldritch Knight": ("Abjuration", "Evocation"), "Arcane Trickster": ("Enchantment", "Illusion")}
FREE_CHOICE_LEVELS = (3, 8, 14, 20)


def _slot_level(text: str) -> int:
    return int("".join(ch for ch in str(text) if ch.isdigit()) or 0)


def spellcasting_info(char: Character, entry: dict) -> Optional[dict]:
    """Spellcasting details for one class entry, or None if that class doesn't cast spells."""
    cls = rules.classes[entry["name"]]
    level = entry["level"]
    sc, sub = cls["spellcasting"], (rules.subclass(cls["name"], entry["subclass"]) if entry.get("subclass") else None)
    own_list = cls["name"]
    restricted = None
    source = "class"
    if sc:
        slots_row = (cls["table"]["slots"] or [[0] * 9] * 20)[level - 1] if cls["table"]["slots"] else [0] * 9
    elif sub and sub.get("spellcasting"):
        sc, source = sub["spellcasting"], "subclass"
        own_list = "Wizard"
        restricted = SUBCLASS_SCHOOLS.get(sub["name"])
        slots_row = (sc["slots"][level - 1] if sc.get("slots") else [0])
    else:
        return None
    slots = list(slots_row) + [0] * (9 - len(slots_row))
    ability = sc["ability"]
    mod = char.mod(ability)
    pb = char.proficiency_bonus
    item_dc = sum(i.get("bonus_spell_dc") or 0 for _e, i in char._active_items())
    item_atk = sum(i.get("bonus_spell_attack") or 0 for _e, i in char._active_items())
    cantrips = (sc.get("cantrips") or [0] * 20)[level - 1]
    known = None
    if sc.get("known"):
        known = sc["known"][level - 1]
    prepared = None
    if cls.get("spellcasting") and sc.get("prepared"):
        mods = {a: char.mod(a) for a in E.ABILITIES}
        prepared = E.eval_prepared_formula(sc["prepared"], level, mods)
    pact = None
    if sc["progression"] == "pact":
        cols = cls["table"]["cols"]
        row = cls["table"]["rows"][level - 1]
        pact = {"slots": int(row[cols.index("Spell Slots")]), "level": _slot_level(row[cols.index("Slot Level")])}
        slots = [0] * 9
    max_level = pact["level"] if pact else max([i + 1 for i, n in enumerate(slots) if n] or [0])
    spellbook = cls["name"] == "Wizard"
    return {
        "class": cls["name"], "level": level, "ability": ability, "progression": sc["progression"],
        "cantrips": cantrips, "known": known, "prepared": prepared, "spellbook": spellbook,
        "spellbook_size": 6 + 2 * (level - 1) if spellbook else None,
        "slots": slots, "pact": pact, "max_spell_level": max_level,
        "list_class": own_list, "restricted_schools": restricted, "source": source,
        "dc": 8 + pb + mod + item_dc, "attack": pb + mod + item_atk, "ritual": sc.get("ritual", False),
    }


def casters(char: Character) -> List[dict]:
    return [i for i in (spellcasting_info(char, e) for e in char.classes) if i]


def spell_slots(char: Character) -> Dict[str, object]:
    """Total spell slots: {'slots': [max for levels 1-9], 'pact': {'slots', 'level'} | None}.

    One spellcasting class uses its own table. Several use the Multiclass Spellcaster table
    (full levels + half + third); Warlock pact slots are always tracked separately.
    """
    infos = casters(char)
    pact = next((i["pact"] for i in infos if i["pact"]), None)
    regular = [i for i in infos if i["progression"] in ("full", "1/2", "1/3", "artificer")]
    if len(regular) == 1:
        slots = list(regular[0]["slots"])
    elif regular:
        slots = E.multiclass_slots(E.caster_levels((i["class"], i["level"], i["progression"]) for i in regular))
    else:
        slots = [0] * 9
    return {"slots": slots, "pact": pact}


def slots_remaining(char: Character) -> Dict[str, int]:
    """{'1': remaining, ..., 'pact': remaining} for slots that exist."""
    total = spell_slots(char)
    used = char.d["slots_used"]
    out = {str(i + 1): max(0, n - used.get(str(i + 1), 0)) for i, n in enumerate(total["slots"]) if n}
    if total["pact"]:
        out[PACT_KEY] = max(0, total["pact"]["slots"] - used.get(PACT_KEY, 0))
    return out


def class_spells(char: Character, class_name: str) -> dict:
    return char.d["spells"].setdefault(class_name, {"cantrips": [], "known": [], "prepared": [], "spellbook": []})


def always_prepared(char: Character, class_name: str) -> List[str]:
    """Domain / oath / circle spells that are always prepared and don't count against the limit."""
    entry = char.class_entry(class_name)
    sub = rules.subclass(class_name, entry["subclass"]) if entry and entry.get("subclass") else None
    names: List[str] = []
    for block in (sub["additional_spells"] if sub else []):
        for level, spells in block.get("prepared", {}).items():
            if int(level) <= entry["level"]:
                names += [s for s in spells if isinstance(s, str)]
        for level, spells in block.get("known", {}).items():
            if int(level) <= entry["level"]:
                names += [s for s in spells if isinstance(s, str)]
    return [rules.spell(n)["name"] for n in names if rules.spell(n)]


def expanded_spells(class_name: str, subclass: Optional[str], level: int) -> List[str]:
    """Extra spells added to a class's choosable list by its subclass (Warlock patrons)."""
    sub = rules.subclass(class_name, subclass) if subclass else None
    names: List[str] = []
    for block in (sub["additional_spells"] if sub else []):
        for lvl, spells in block.get("expanded", {}).items():
            # numeric keys are class levels; 's1'..'s9' (warlock patrons) are spell levels, gated by slot level
            if lvl.startswith("s") or int(lvl) <= level:
                names += [s for s in spells if isinstance(s, str)]
    return [rules.spell(n)["name"] for n in names if rules.spell(n)]


def eligible_spells(char: Character, info: dict, cantrips: bool = False) -> List[dict]:
    """Spells this class entry may choose from right now (for learning or preparing)."""
    entry = char.class_entry(info["class"])
    pool = rules.class_spell_list(info["list_class"], sources=char.sources)
    for name in expanded_spells(info["class"], entry.get("subclass"), entry["level"]):
        spell = rules.spell(name)
        if spell and spell not in pool:
            pool.append(spell)
    if cantrips:
        return sorted((s for s in pool if s["level"] == 0), key=lambda s: s["name"])
    return sorted((s for s in pool if 1 <= s["level"] <= info["max_spell_level"]), key=lambda s: (s["level"], s["name"]))


def validate_restricted_choice(char: Character, info: dict, chosen: List[str]) -> None:
    """Eldritch Knight / Arcane Trickster school restriction on the full list of known spells."""
    schools = info["restricted_schools"]
    if not schools:
        return
    free = sum(1 for lv in FREE_CHOICE_LEVELS if lv <= info["level"])
    off_school = [n for n in chosen if rules.spell(n)["school"] not in schools and rules.spell(n)["level"] > 0]
    if len(off_school) > free:
        raise ValueError(f"Only {free} of your {info['class']} spells may be outside "
                         f"{' and '.join(schools)} at level {info['level']}.")


def innate_limit(char: Character, uses: Optional[str]) -> Optional[tuple]:
    """(number of casts, 'short' or 'long') of an innate spell's `uses`: "1/long rest", "3/short rest" or "pb/long rest"
    (as many as the proficiency bonus). None for at will or anything else."""
    m = re.match(r"(\d+|pb)/(short|long) rest", uses or "")
    if not m:
        return None
    return (char.proficiency_bonus if m.group(1) == "pb" else int(m.group(1)), m.group(2))


def innate_spent(char: Character, spell: dict) -> bool:
    lim = innate_limit(char, spell.get("uses"))
    return bool(lim) and char.d["resources"].get(f"spell:{spell['name']}", 0) >= lim[0]


def top_slot_level(char: Character) -> int:
    """The highest spell slot level the character has (0 without spell slots): the Adept feats' spells follow it."""
    slots = spell_slots(char)
    top = max([i + 1 for i, n in enumerate(slots["slots"]) if n] or [0])
    return max(top, (slots["pact"] or {}).get("level", 0) if slots["pact"] else 0)


# subclass features that let a spell be cast free a few times: {subclass: (spell, ability, class, level)}
FREE_SUBCLASS_CASTS = {"Circle of Stars": ("Guiding Bolt", "wis", "Druid", 2),
                       "Cartographer": ("Faerie Fire", "int", "Artificer", 3, "mod")}       # Illuminated Cartography: the Intelligence modifier (at least 1) times


def free_subclass_casts(char: Character) -> List[dict]:
    """The free casts a subclass gives (Circle of Stars' Star Map: Guiding Bolt, proficiency bonus times per long rest)."""
    out = []
    for entry in char.classes:
        grant = FREE_SUBCLASS_CASTS.get(entry.get("subclass") or "")
        if grant and entry["name"] == grant[2] and entry["level"] >= grant[3]:
            n = max(1, char.mod(grant[1])) if len(grant) > 4 else char.proficiency_bonus
            out.append({"name": grant[0], "ability": grant[1], "uses": f"{n}/long rest"})   # (innate_limit also reads "pb/long rest")
    return out


def spell_known_or_prepared(char: Character) -> List[dict]:
    """Every spell the character can cast right now (cantrips, prepared, always prepared, racial)."""
    out: List[dict] = []
    seen = set()
    for info in casters(char):
        sp = class_spells(char, info["class"])
        names = list(sp["cantrips"]) + char.d["choices"].get("bonus_cantrips", {}).get(info["class"], [])
        if info["prepared"] is not None:
            names += sp["prepared"]
        else:
            names += sp["known"]
        names += always_prepared(char, info["class"])
        for name in names:
            spell = rules.spell(name)
            if spell and (name, info["class"]) not in seen:
                seen.add((name, info["class"]))
                out.append({**spell, "cast_class": info["class"], "ability": info["ability"]})
    for racial in char.d["racial_spells"]:
        spell = rules.spell(racial["name"])
        if spell and racial.get("level_req", 1) <= char.total_level and racial.get("slot_req", 0) <= top_slot_level(char):
            entry = {**spell, "cast_class": "Racial", "ability": racial["ability"], "uses": racial.get("uses")}
            if racial.get("slots") and innate_spent(char, entry):
                entry["uses"] = None                   # a feat spell "also cast with spell slots": the free cast is gone, now it costs a slot
            if racial.get("ritual"):
                entry["feat_ritual"] = True            # a feat lets anyone cast it as a ritual (Emerald Enclave Fledgling)
            out.append(entry)
    for free in free_subclass_casts(char):             # Star Map's Guiding Bolt: free casts until they're spent, then the class copy (slots)
        spell = rules.spell(free["name"])
        if spell and not innate_spent(char, free):
            out = [s for s in out if s["name"] != spell["name"]]
            out.append({**spell, "cast_class": "Racial", "ability": free["ability"], "uses": free["uses"]})
    return sorted(out, key=lambda s: (s["level"], s["name"]))


def prepare_choices(char: Character) -> List[dict]:
    """What a long rest lets each spellcasting class change. Classes that prepare (Cleric, Druid, Paladin, Artificer, and
    the Wizard from their spellbook) pick again from `pool`, up to `limit` (always-prepared spells come free); classes that
    know their spells (Bard, Sorcerer, Warlock, Ranger, Eldritch Knight, Arcane Trickster) keep them: `prepares` False."""
    out: List[dict] = []
    for info in casters(char):
        sp = class_spells(char, info["class"])
        if info["prepared"] is None:
            out.append({"class": info["class"], "prepares": False, "known": [n for n in sp["known"] if rules.spell(n)]})
            continue
        if info["max_spell_level"] < 1:            # a level 1 Paladin: no slots, nothing to prepare yet
            continue
        always = always_prepared(char, info["class"])
        pool = [rules.spell(n) for n in sp["spellbook"]] if info["spellbook"] else eligible_spells(char, info)
        pool += [rules.spell(n) for n in always]
        by_name = {s["name"]: s for s in pool if s and 1 <= s["level"] <= info["max_spell_level"]}
        out.append({"class": info["class"], "prepares": True, "limit": info["prepared"], "spellbook": info["spellbook"],
                    "max_level": info["max_spell_level"], "always": always,
                    "prepared": [n for n in sp["prepared"] if n not in always and n in by_name],
                    "pool": sorted(by_name, key=lambda n: (by_name[n]["level"], n))})
    return out
