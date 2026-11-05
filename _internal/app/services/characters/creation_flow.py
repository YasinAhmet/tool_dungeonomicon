"""What the character creation wizard needs at each step: the lists, the open choices, validation and the review.

A `spec` is the wizard's state so far (see rules.creation.create_character for its fields). Every step works on a
scratch character built from the spec, so a half-made choice never breaks the steps after it.
"""
from typing import List, Optional

from ...core.runtime import rt
from ...rules import engine as E, leveling as LV, sheet
from ...rules import feat_extras as FE
from ...rules import spellcasting as SC
from ...rules.character import Character
from ...rules.creation import (racial_fixed, apply_background, apply_equipment, apply_race, background_requirements, choose_pool,
                               create_character, equipment_choices, race_requirements, type_options,
                               validate_base_scores)
from ...rules.data import rules
from ...rules.describe import background_text, class_text, race_text
from ..common import ServiceError
from .levelup_flow import plan_extras


def lists() -> dict:
    return {
        "races": [{"name": r["name"], "source": r["source"]} for r in rules.race_list()],
        "classes": [{"name": c["name"], "source": c["source"], "hit_die": c["hit_die"]} for c in rules.class_list()],
        "backgrounds": [{"name": b["name"], "source": b["source"]} for b in rules.background_list()],
        "feats": [f["name"] for f in rules.feat_list()], "alignments": E.ALIGNMENTS,
        "abilities": [{"key": a, "name": E.ABILITY_NAMES[a]} for a in E.ABILITIES],
        "standard_array": E.STANDARD_ARRAY, "point_buy_cost": dict(E.POINT_BUY_COST),
        "point_buy_budget": E.POINT_BUY_BUDGET, "skills": list(rules.skills), "languages": rules.all_languages(),
    }


def tool_pool() -> List[str]:
    """Tools a background or feat may grant (PHB artisan's tools, instruments, gaming sets)."""
    return sorted(i["name"] for i in rules.items.values() if i["type"] in ("AT", "INS", "GS") and not i["magic"] and i["source"] == "PHB")


def race_step(spec: dict) -> dict:
    req = race_requirements(spec["race"], spec.get("subrace") or None)
    req["info"] = race_text(spec["race"], spec.get("subrace") or None, spec.get("ancestry") or None, req["ability_choose"])
    req["languages_pool"] = rules.all_languages()
    req["skills_pool"] = list(rules.skills)
    req["cantrip_pool"] = choose_pool("level=0|class=Wizard") if req["cantrip_choice"] else []
    return req


def racial_bonuses(spec: dict) -> dict:
    """The racial ability bonuses the current race choices give (the fixed ones while choices are still open)."""
    probe = Character.create_blank("probe")
    probe.d["abilities"]["base"] = {a: 10 for a in E.ABILITIES}
    try:
        apply_race(probe, spec["race"], spec.get("subrace") or None, spec.get("ancestry") or None, spec.get("race_choices", {}))
    except LV.RulesError:
        race = rules.races[spec["race"]]
        return racial_fixed(race, next((x for x in race["subraces"] if x["name"] == spec.get("subrace")), None))
    return dict(probe.d["abilities"]["racial"])


def background_step(spec: dict) -> dict:
    req = background_requirements(spec["background"])
    req["info"] = background_text(spec["background"])
    bg = rules.backgrounds[spec["background"]]
    known = scratch(spec, "race").d["proficiencies"]
    fixed = [rules.skill_name(x) for x in bg.get("skills", {}).get("fixed", [])]
    dup = sum(1 for x in fixed if x in known["skills"])
    taken = picked(spec, "background")
    req["skills_wanted"] = req["skills_any"] + dup
    req["skills_pool"] = [x for x in rules.skills if x not in known["skills"] and x not in fixed and x.lower() not in taken["skills"]]
    req["languages_pool"] = [x for x in rules.all_languages() if x not in known["languages"] and x.lower() not in taken["languages"]]
    have = {t.lower() for t in known["tools"]} | taken["tools"]
    req["tools_pool"] = [t for t in req["tools_from"] or tool_pool() if t.lower() not in have]
    req["duplicates"] = dup
    return req


def class_step(spec: dict, subclass: Optional[str] = None) -> dict:
    sc = scratch(spec, "class")
    plan = plan_extras(sc, LV.plan_level_up(sc, spec["class"], subclass or None))
    return {"plan": drop_taken(plan, picked(spec, "class")), "info": class_text(rules.classes[spec["class"]])}


def picked(spec: dict, upto: str) -> dict:
    """What the steps before `upto` chose, lowercased by kind: {'skills', 'tools', 'languages', 'spells'}. The scratch
    character misses picks of a step that isn't finished yet, so later steps also leave these out."""
    out = {k: set() for k in ("skills", "tools", "languages", "spells")}
    steps = [spec.get("race_choices") or {}] + ([spec.get("background_choices") or {}] if upto == "class" else [])
    for ch in steps:
        feat = ch.get("feat_choices") or {}
        for kind, names in (("skills", ch.get("skills")), ("tools", ch.get("tools")), ("languages", ch.get("languages")),
                            ("spells", ch.get("cantrips")), ("spells", feat.get("cantrips")), ("spells", [feat.get("spell")])):
            out[kind] |= {n.lower() for n in names or [] if isinstance(n, str) and n}
        for n in feat.get("proficiencies") or []:                  # Skilled: skills or tools
            out["skills" if n in rules.skills else "tools"].add(n.lower())
    return out


def drop_taken(plan: dict, taken: dict) -> dict:
    """Leave out of a level plan's pick lists what earlier creation steps already chose."""
    keep = lambda names, kind: [n for n in names if (n.get("value") if isinstance(n, dict) else n).lower() not in taken[kind]]
    for key, kind in (("skills", "skills"), ("tools", "tools")):
        if plan.get(key) and plan[key].get("from"):
            plan[key]["from"] = keep(plan[key]["from"], kind)
    for key, spec in (plan.get("subclass_grants") or {}).items():
        kind = {"skills": "skills", "expertise_skills": "skills", "languages": "languages", "cantrip": "spells", "tools": "tools"}.get(key)
        if kind and isinstance(spec, dict) and spec.get("from"):
            spec["from"] = keep(spec["from"], kind)
    sp = plan.get("spells")
    if sp:
        for key in ("cantrip_pool", "any_class_pool"):
            if sp.get(key):
                sp[key] = keep(sp[key], "spells")
        if sp.get("known") is not None or sp.get("spellbook"):
            sp["spell_pool"] = keep(sp["spell_pool"], "spells")
    return plan


def equipment_step(spec: dict) -> dict:
    data = equipment_choices(spec["class"], spec.get("background"))
    for group in data["class"] + data["background"]:
        for key in ("fixed", "a", "b", "c", "d", "e"):          # give every {'type': ...} slot its selectable items
            for item in group.get(key, []) or []:
                if isinstance(item, dict) and item.get("type"):
                    item["options"] = type_options(item["type"])
    return data


def review(spec: dict) -> dict:
    try:
        char = create_character(spec)
    except LV.RulesError as e:
        return {"ok": False, "problem": str(e)}
    return {"ok": True, "text": sheet.sheet_text(char).replace("**", ""), "notes": creation_notes(char, spec)}


def validate(spec: dict, what: str) -> dict:
    """Dry-run one wizard step: {'ok': True} or {'ok': False, 'problem': the rules message}."""
    try:
        if what == "race":
            probe = Character.create_blank("probe")
            probe.d["abilities"]["base"] = {a: 15 for a in E.ABILITIES}
            apply_race(probe, spec["race"], spec.get("subrace") or None, spec.get("ancestry") or None, spec.get("race_choices", {}))
        elif what == "scores":
            validate_base_scores(spec["scores_method"], spec["scores"])
        elif what == "background":
            apply_background(scratch(spec, "race"), spec["background"], spec.get("background_choices", {}))
        elif what == "class":
            LV.apply_level_up(scratch(spec, "background"), spec["class"], spec.get("class_choices", {}))
        elif what == "equipment":
            char = scratch(spec, "background")
            LV.apply_level_up(char, spec["class"], spec.get("class_choices", {}))
            apply_equipment(char, spec["class"], spec["background"], spec.get("equipment", {}))
        else:
            raise ServiceError(f"Unknown step {what}")
    except LV.RulesError as e:
        return {"ok": False, "problem": str(e)}
    return {"ok": True}


def scratch(spec: dict, upto: str) -> Character:
    """A throwaway character with the spec applied up to (and excluding) `upto`'s step."""
    char = Character.create_blank("scratch")
    scores = spec.get("scores") or {}
    char.d["abilities"]["base"] = {a: (scores.get(a) or 10) for a in E.ABILITIES}
    try:
        if spec.get("race"):
            apply_race(char, spec["race"], spec.get("subrace"), spec.get("ancestry"), spec.get("race_choices", {}))
    except LV.RulesError:
        pass
    try:
        if upto != "race" and spec.get("background"):
            apply_background(char, spec["background"], spec.get("background_choices", {}))
    except LV.RulesError:
        pass
    return char


def creation_notes(c: Character, spec: dict) -> List[dict]:
    """Things worth knowing about the finished build: warnings (important) and info (good to know)."""
    notes: List[dict] = []
    add = lambda level, text, section=None: notes.append({"level": level, "text": text, "section": section})
    scores = c.ability_scores()
    for a_, n in scores.items():
        if n <= 8:
            add("warn", f"{E.ABILITY_NAMES[a_]} is only {n} ({E.modifier(n):+d}).", "scores")
    for info in SC.casters(c):
        if c.mod(info["ability"]) < 2:
            add("warn", f"{info['class']} casts with {E.ABILITY_NAMES[info['ability']]} ({scores[info['ability']]}): spell save DC {info['dc']} is low.", "scores")
    armor, shield = c.equipped_armor(), c.equipped_shield()
    if armor and not c.armor_proficient(armor):
        add("warn", f"Not proficient with {armor['name']}: disadvantage on STR/DEX checks, saves and attacks, and no spellcasting.", "equipment")
    if shield and not c.armor_proficient(shield):
        add("warn", "Not proficient with shields.", "equipment")
    for atk in c.attacks():
        if "not proficient" in atk["notes"]:
            add("warn", f"Not proficient with {atk['name']}.", "equipment")
    if c.encumbrance != "Unencumbered":
        add("warn", f"Starting gear weighs {c.carried_weight:g} lb ({c.encumbrance}).", "equipment")
    if spec.get("equipment", {}).get("gold"):
        add("info", f"You start with {spec['equipment']['gold']} gp and no starting equipment.", "equipment")
    if not spec.get("alignment"):
        add("info", "No alignment chosen (optional).", "concept")
    if not (spec.get("details", {}).get("backstory") or spec.get("details", {}).get("appearance")):
        add("info", "Appearance and backstory are empty (optional).", "details")
    ac = c.armor_class()
    add("info", f"Hit points {c.max_hp}, Armor Class {ac[0]} ({ac[1]}), speed {c.speed} ft, initiative {c.initiative:+d}.")
    add("info", "Languages: " + (", ".join(c.d["proficiencies"]["languages"]) or "none") + ".")
    if c.d["proficiencies"]["tools"]:
        add("info", "Tools: " + ", ".join(c.d["proficiencies"]["tools"]) + ".")
    return notes


def feat_form(feat_name: str, char_name: Optional[str] = None, mi_class: Optional[str] = None) -> dict:
    """The extra decisions a feat needs, as form fields: {'text', 'warning', 'fields': [{key, kind, label, options...}]}.

    kind 'select' picks one of [{'value', 'label'}]; kind 'pick' picks `count` names. A field with 'reload' changes the
    form (Magic Initiate's spell list): ask again with the chosen value as `mi_class`."""
    feat = rules.feats.get(feat_name)
    if not feat:
        return {"text": "", "warning": None, "fields": []}
    char = rt().characters.get(char_name) if char_name else Character.create_blank("probe")
    if not char_name:
        char.d["abilities"]["base"] = {a: 15 for a in E.ABILITIES}
    out = {"text": feat["text"], "warning": LV.feat_prereq_status(char, feat), "fields": []}
    f = out["fields"]
    abil = lambda keys: [{"value": a, "label": E.ABILITY_NAMES[a]} for a in keys]
    if feat["ability"]["choose"]:
        f.append({"key": "ability", "kind": "select", "label": "Raise which ability by 1?", "options": abil(feat["ability"]["choose"]["from"])})
    if feat_name == "Resilient":
        f.append({"key": "ability", "kind": "select", "label": "Saving throw proficiency in", "options": abil(E.ABILITIES)})
    elif feat_name == "Skilled":
        have = char.d["proficiencies"]
        pool = [x for x in rules.skills if x not in have["skills"]] + [
            t for t in sorted(i["name"] for i in rules.items.values() if i["type"] in ("AT", "T", "GS", "INS") and not i["magic"] and i["source"] == "PHB")
            if t not in have["tools"]]
        f.append({"key": "proficiencies", "kind": "pick", "label": "Choose three skills or tools", "options": pool, "count": 3})
    elif feat_name == "Weapon Master":
        f.append({"key": "weapons", "kind": "pick", "label": "Choose four weapons", "options": sorted(w["name"] for w in rules.weapons()), "count": 4})
    elif feat_name == "Elemental Adept":
        f.append({"key": "damage", "kind": "select", "label": "Damage type",
                  "options": [{"value": x, "label": x} for x in ("acid", "cold", "fire", "lightning", "thunder")]})
    elif feat_name == "Magic Initiate":
        classes = ["Bard", "Cleric", "Druid", "Sorcerer", "Warlock", "Wizard"]
        f.append({"key": "class", "kind": "select", "label": "Spell list", "options": [{"value": c, "label": c} for c in classes], "reload": True})
        known = LV.taken_spells(char)
        spells = [s for s in rules.class_spell_list(mi_class or classes[0]) if s["name"].lower() not in known]
        f.append({"key": "cantrips", "kind": "pick", "label": "Choose two cantrips", "options": [s["name"] for s in spells if s["level"] == 0], "count": 2})
        f.append({"key": "spell", "kind": "pick", "label": "Choose a 1st-level spell", "options": [s["name"] for s in spells if s["level"] == 1], "count": 1, "single": True})
    else:
        f += FE.fields(feat_name, char, mi_class)       # Fey Touched, Fighting Initiate, Metamagic Adept, the dragonmarks... (rules/feat_extras.py)
    return out


# ---------------------------------------------------------------------- helpers for the desktop wizard
def book_groups(entries: List[dict]) -> List[dict]:
    """Entries ({'name', 'source'}) in folders by book: the Player's Handbook first, then Custom, then the rest by name."""
    names = {k: (v or {}).get("name", k) for k, v in rules.sources.items()}
    by: dict = {}
    for e in entries:
        src = e.get("source", "")
        title = "Player's Handbook" if src == "PHB" else "Custom" if src == "Custom" else names.get(src, src)
        by.setdefault(title, []).append(e["name"])
    rank = lambda t: 0 if t == "Player's Handbook" else 1 if t == "Custom" else 2
    return [{"title": t, "items": items} for t, items in sorted(by.items(), key=lambda kv: (rank(kv[0]), kv[0]))]


def language_options(names: List[str]) -> List[dict]:
    """Languages for a pick list, folded by kind (Standard, Exotic...)."""
    from ...rules.describe import language_group
    return [{"value": n, "label": n, "group": language_group(n)} for n in names]


def point_buy_spent(scores: dict) -> int:
    """Points the scores cost (a score outside 8-15 counts as over budget)."""
    return sum(E.POINT_BUY_COST.get(scores.get(a) or 8, 99) for a in E.ABILITIES)


def scores_problem(method: str, scores: dict, rolled: Optional[List[int]] = None) -> Optional[str]:
    """What is wrong with the ability scores step, or None. `rolled`: the values rolled for the 'rolled' method."""
    if any(not scores.get(a) for a in E.ABILITIES):
        return "Assign a score to every ability."
    if method == "rolled":
        if not rolled:
            return "Roll your scores first."
        if sorted(scores[a] for a in E.ABILITIES) != sorted(rolled):
            return "Use each rolled value exactly once."
    r = validate({"scores_method": method, "scores": scores}, "scores")
    return None if r["ok"] else r["problem"]


def equipment_problem(equipment: dict) -> Optional[str]:
    """The checks the equipment step makes before asking the rules: gold entered, every 'any ...' slot picked."""
    if equipment.get("gold") == -1:
        return "Enter or roll your starting gold."
    if equipment.get("gold") is None and any(not p for g in equipment.get("class", []) + equipment.get("background", [])
                                             for p in g.get("picks", [])):
        return "Pick an item for every equipment choice."
    return None
