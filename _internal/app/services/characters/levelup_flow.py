"""What the level-up window needs: which classes can be taken, the plan of choices, a preview, and RESET ALL."""
from typing import Dict, List, Optional

from ...core.runtime import rt
from ...rules import leveling as LV, preview
from ...rules import spellcasting as SC
from ...rules.character import Character
from ...rules.data import rules
from ...rules.reconstruct import base_of, infer_origin, level_entries, origin_base


def options(name: str) -> List[dict]:
    """Every class the character could take a level in (own classes first), and why not where they can't."""
    c = rt().characters.get(name)
    out = [{"class": e["name"], "label": f"{e['name']}  {e['level']} -> {e['level'] + 1}", "ok": True, "note": ""} for e in c.classes]
    for cls in rules.class_list(c.sources):
        if c.class_entry(cls["name"]):
            continue
        try:
            LV.check_multiclass(c, cls["name"])
            out.append({"class": cls["name"], "label": f"Multiclass: {cls['name']}", "ok": True, "note": ""})
        except LV.RulesError:
            out.append({"class": cls["name"], "label": f"Multiclass: {cls['name']}", "ok": False,
                        "note": "needs " + LV.describe_requirements(cls["multiclass"]["requirements"])})
    return out


def plan_extras(c: Character, plan: dict) -> dict:
    """What a plan's form needs besides the plan itself: feats on offer, current spell lists, subclass blurbs."""
    plan["feat_pool"] = [f["name"] for f in rules.feat_list(c.sources) if f["name"] not in c.d["feats"]]
    cls = plan["class"]
    spells = SC.class_spells(c, cls)
    plan["spell_state"] = {"spellbook": spells["spellbook"], "prepared": spells["prepared"]}
    if plan.get("subclass"):
        plan["subclass"]["blurbs"] = {s["name"]: [{"name": f["name"], "level": f["level"], "text": f["text"][:240]} for f in s["features"][:2]]
                                     for s in (rules.subclass(cls, n) for n in plan["subclass"]["options"]) if s}
    plan["known_skills"] = list(c.d["proficiencies"]["skills"])
    return plan


def plan(name: str, class_name: str, subclass: Optional[str] = None) -> dict:
    c = rt().characters.get(name)
    return plan_extras(c, LV.plan_level_up(c, class_name, subclass or None))


def preview_level(name: str, class_name: str, choices: dict) -> dict:
    """What would change: {'ok': True, 'stats', 'features', 'spells', 'proficiencies'} or {'ok': False, 'problem'}."""
    c = rt().characters.get(name)
    trial = Character.from_dict(c.d)
    try:
        LV.apply_level_up(trial, class_name, choices)
    except LV.RulesError as e:
        return {"ok": False, "problem": str(e)}
    d = preview.diff(c, trial)
    return {"ok": True, "stats": d["stats"], "features": d["features"], "spells": d["spells"], "proficiencies": d["proficiencies"]}


def reset_start(name: str) -> dict:
    """RESET ALL: the recorded levels, the classes on offer and the creation choices (race, scores, background)."""
    c = rt().characters.get(name)
    return {"entries": level_entries(c), "classes": [x["name"] for x in rules.class_list(c.sources)], "origin": infer_origin(c)}


def reset_chain(name: str, entries: list, origin: Optional[dict] = None) -> list:
    """RESET ALL: the plan of every level given the choices made at the levels before it. With `origin` (new creation
    choices) the levels stand on a character made again from them, otherwise on the character's own."""
    c = rt().characters.get(name)
    try:
        work = origin_base(c, origin) if origin else base_of(c)
    except LV.RulesError as err:
        return [{"plan": None, "problem": f"Creation choices: {err}"} for _e in entries]
    out, blocked = [], None
    for i, e in enumerate(entries):
        if blocked:
            out.append({"plan": None, "problem": blocked})
            continue
        try:
            p = plan_extras(work, LV.plan_level_up(work, e["class"], e.get("subclass") or (e.get("choices") or {}).get("subclass")))
        except LV.RulesError as err:
            blocked = f"Level {i + 1}: {err}"
            out.append({"plan": None, "problem": blocked})
            continue
        row = {"plan": p, "problem": None}
        choices = LV.fit_prepared(work, e["class"], e.get("choices"))
        if choices is not None:
            try:
                trial = Character.from_dict(work.d)
                LV.apply_level_up(trial, e["class"], choices)
                work.snapshot_level(e["class"], choices)
                LV.apply_level_up(work, e["class"], choices)
            except LV.RulesError as err:
                row["problem"] = str(err)
                blocked = f"Level {i + 1} still needs choices."
        else:
            row["problem"] = "Make the choices for this level."
            blocked = f"Level {i + 1} still needs choices."
        out.append(row)
    return out


def subclass_options(class_name: str) -> List[dict]:
    """Subclasses of a class with their first features (for pickers)."""
    return [{"name": s["name"], "features": [{"name": f["name"], "level": f["level"], "text": f["text"]} for f in s["features"][:3]]}
            for s in LV.subclass_options(class_name, rules.active_sources)]


def expertise_pool(plan: dict, picked_skills: Optional[List[str]] = None) -> List[str]:
    """What Expertise may double: the skills already known, the skills picked at this level, Thieves' Tools for rogues."""
    known = list((plan.get("expertise") or {}).get("from") or [])
    pool = known + [s for s in (picked_skills or []) if s not in known]
    if (plan.get("expertise") or {}).get("tools"):
        pool.append("Thieves' Tools")
    return pool


def spell_facts(names: List[str]) -> Dict[str, dict]:
    """{name: {'level', 'school'}} of the spells among `names` the rules know (for folding a spell list)."""
    out = {}
    for n in names:
        s = rules.spell(str(n))
        if s:
            out[n] = {"level": s["level"], "school": s["school"]}
    return out


def level_history(name: str) -> List[dict]:
    """Edit levels: one row per editable level (2..N)."""
    return rt().characters.level_history(name)
