"""Rebuild a character's level-by-level history from the character as it is now.

Characters made before levels were recorded (or entered by hand) have no record of what was chosen at each level.
`reconstruct()` goes back to a level-0 base and replays every class level, choosing at each step what the current
sheet shows (skills, spells, fighting styles, ability score improvements, feats, hit points...) and falling back to
the first valid option where the sheet doesn't say. The result carries a complete `level_history`, so any level can be
edited and the later ones replayed.
"""
import copy
from typing import Dict, List, Optional

from . import engine as E
from . import feat_extras as FE
from . import leveling as LV
from .character import Character
from .creation import (ORIGIN_KEYS, _known_entries, _spell_blocks, apply_background, apply_race, background_requirements,
                       background_tool_pool, choose_pool, race_requirements, racial_fixed, racial_languages, tool_name,
                       validate_base_scores)
from .data import rules

# what character creation and the class levels build; everything else (gear, notes, portrait, hit points...) is kept
BUILD_KEYS = ("race", "subrace", "ancestry", "background", "alignment", "classes", "abilities", "hit_dice_used", "proficiencies",
              "feats", "options", "racial_spells", "spells", "slots_used", "resources", "choices", "level_history",
              "ability_method", "origin")
TRAIT_KEYS = ("personality", "ideal", "bond", "flaw")


def _prefer(pool: List[str], count: int, wanted) -> List[str]:
    """`count` entries of `pool`, those the character already has first."""
    wanted = set(wanted)
    return ([x for x in pool if x in wanted] + [x for x in pool if x not in wanted])[:count]


def base_of(c: Character) -> Character:
    """The character as if no class level had been taken yet (race, background, scores, gear and notes kept)."""
    b = Character.from_dict(copy.deepcopy(c.d))
    d = b.d
    race = c.race_data()
    d["classes"], d["hit_dice_used"], d["slots_used"], d["resources"], d["spells"], d["options"] = [], {}, {}, {}, {}, []
    d["hp"]["gains"] = []
    d["abilities"]["improvement"], d["abilities"]["feat"] = {}, {}
    d["feats"] = d["feats"][: (race or {}).get("feats", 0)]            # a race's own feat (variant human) stays
    d["racial_spells"] = [r for r in d["racial_spells"] if r.get("source") in (None, "Race") or r.get("source") in d["feats"]]    # the spells of later feats go
    d["choices"] = {k: v for k, v in d["choices"].items() if k == "milestone"}
    d["level_history"] = []
    prof = d["proficiencies"]
    first = rules.classes[c.classes[0]["name"]]
    prof["saves"] = []
    origin = c.d.get("origin") or {}
    own = {t.lower() for src in (rules.backgrounds.get(c.d["background"] or "") or {}, race or {})       # the race's and the
           for t in src.get("tools", {}).get("fixed", [])}                                             # background's stay
    own |= {t.lower() for key in ("race_choices", "background_choices") for t in (origin.get(key) or {}).get("tools") or []}
    for name in {e["name"] for e in c.classes}:
        cls = rules.classes[name]
        for key, source in (("armor", cls["armor"]), ("weapons", cls["weapons"])):
            prof[key] = [x for x in prof[key] if x not in source]
        prof["tools"] = [t for t in prof["tools"] if t.lower() in own or t.lower() not in [x.lower() for x in cls["tools"]]]
    spec = LV.tool_choice_spec(first["tool_choice"])                     # a bard's three instruments, a monk's tool: the
    if spec["count"]:                                                     # first class's picks come last, after the race's
        hand = {t.lower() for t in (c.d["choices"].get("manual_profs") or {}).get("tools", [])}       # and background's
        pool = {t.lower() for t in spec["from"]}
        picked = [t for t in prof["tools"] if t.lower() in pool and t.lower() not in own and t.lower() not in hand][-spec["count"]:]
        prof["tools"] = [t for t in prof["tools"] if t not in picked]
    _drop_granted(b, _granted(c))                     # before guessing the class skills below
    pool = [rules.skill_name(s) for s in first["skills"]["choose"]] or list(rules.skills)
    given = {rules.skill_name(s) for src in (rules.backgrounds.get(c.d["background"] or "") or {}, race or {})    # never the
             for s in src.get("skills", {}).get("fixed", [])}                                                   # class's picks
    given |= {s for key in ("race_choices", "background_choices") for s in (origin.get(key) or {}).get("skills") or []}
    picks = [s for s in prof["skills"] if s in pool and s not in given][-first["skills"]["count"]:]   # the class's come last
    prof["skills"] = [s for s in prof["skills"] if s not in picks]
    prof["expertise"] = []
    return b


def _granted(c: Character) -> set:
    """Proficiencies the recorded level choices gave (multiclass skills, feats like Skilled, subclass grants)."""
    out = set()
    for feat in c.d["feats"][(c.race_data() or {}).get("feats", 0):]:       # picks of feats whose level was never recorded
        for key in ("skills", "tools", "languages"):
            v = FE.picks(c, feat).get(key)
            out.update([v] if isinstance(v, str) else v or [])
    for e in c.d.get("level_history", []):
        ch = e.get("choices") or {}
        out.update(ch.get("skills") or [], ch.get("tools") or [])
        for v in (ch.get("subclass_choices") or {}).values():
            out.update(v if isinstance(v, list) else [])
        fc = (ch.get("asi") or {}).get("feat_choices") or {}
        out.update(fc.get("proficiencies") or [])
        for key in ("skills", "tools", "languages"):                # Echoing Soul's skills, Harper Agent's instrument, a feat's language
            v = fc.get(key)
            out.update([v] if isinstance(v, str) else v or [])
    return out


def _drop_granted(c: Character, granted: set):
    prof = c.d["proficiencies"]
    for key in ("skills", "tools", "languages"):
        prof[key] = [x for x in prof[key] if x not in granted]


def infer_choices(plan: dict, current: Character, work: Character, spare: dict) -> dict:
    """What to choose at this level so the result matches `current`; `spare` tracks ability points / feats not used yet."""
    cls = plan["class"]
    cur_spells = current.d["spells"].get(cls, {})
    ch: Dict = {"hp": "average"}
    if plan["subclass"]:
        entry = current.class_entry(cls)
        want = entry.get("subclass") if entry else None
        ch["subclass"] = want if want in plan["subclass"]["options"] else plan["subclass"]["options"][0]
        plan = LV.plan_level_up(work, cls, ch["subclass"])
    grants = plan.get("subclass_grants") or {}
    if grants:
        ch["subclass_choices"] = {k: _prefer(list(v["from"]), v["count"], current.d["proficiencies"]["skills"] + current.d["proficiencies"]["languages"]
                                             + current.d["proficiencies"]["tools"] + cur_spells.get("cantrips", [])
                                             + list(current.d["choices"].get("subclass_weapons", {}).values()))     # (a kensei's picked weapons)
                                  for k, v in grants.items() if isinstance(v, dict) and v.get("from") is not None}
    if plan["skills"]:
        ch["skills"] = _prefer(plan["skills"]["from"], plan["skills"]["count"], current.d["proficiencies"]["skills"])
    if plan["tools"] and plan["tools"]["count"]:
        ch["tools"] = _prefer(plan["tools"]["from"], plan["tools"]["count"], current.d["proficiencies"]["tools"])
    if plan["asi"]:
        feats = [f for f in spare["feats"] if f in [x["name"] for x in rules.feat_list(work.sources)]
                 and all(r.get("level", 0) <= work.total_level + 1 for r in rules.feats[f]["prerequisite"])]     # a level 19 boon waits for level 19
        feats = [f for f in feats if f in current.d["feats"] and f not in work.d["feats"]]   # by this level (a snapshot: at it)
        if feats:
            name = feats[0]
            spare["feats"].remove(name)
            fc: Dict = {}
            ab = rules.feats[name]["ability"]
            if ab["choose"]:                                           # raise the ability the sheet shows the bonus on
                allowed = ab["choose"]["from"]
                pick = next((a for a in allowed if spare["points"].get(a, 0) >= ab["choose"]["amount"]), allowed[0])
                fc["ability"] = pick
                spare["points"][pick] = max(0, spare["points"].get(pick, 0) - ab["choose"]["amount"])
            fc.update(FE.picks(current, name))                         # the spells, skills and damage types the feat chose (feat_extras.py)
            ch["asi"] = {"feat": name, "feat_choices": fc}
        else:
            pts = spare["points"]
            two = next((a for a in E.ABILITIES if pts.get(a, 0) >= 2), None)
            ones = [a for a in E.ABILITIES if pts.get(a, 0) >= 1]
            if two:
                ch["asi"] = {"abilities": {two: 2}}; pts[two] -= 2
            elif len(ones) >= 2:
                ch["asi"] = {"abilities": {ones[0]: 1, ones[1]: 1}}; pts[ones[0]] -= 1; pts[ones[1]] -= 1
            else:
                a = next((x for x in E.ABILITIES if work.ability_score(x) + 2 <= E.MAX_ABILITY), E.ABILITIES[0])
                ch["asi"] = {"abilities": {a: 2}}
    if plan["expertise"]:
        pool = plan["expertise"]["from"] + [s for s in (ch.get("skills") or [])]
        ch["expertise"] = _prefer(pool, plan["expertise"]["count"], current.d["proficiencies"]["expertise"])
    if plan["options"]:
        ch["options"] = {o["key"]: _prefer(o["pool"], o["count"], current.d["options"]) for o in plan["options"]}
    sp = plan["spells"]
    if sp:
        if sp["cantrips"]:
            ch["cantrips"] = _prefer(sp["cantrip_pool"], sp["cantrips"], cur_spells.get("cantrips", []))
        if sp["known"]:
            ch["spells"] = _prefer(sp["spell_pool"], sp["known"], cur_spells.get("known", []))
        if sp["spellbook"]:
            ch["spellbook"] = _prefer(sp["spell_pool"], sp["spellbook"], cur_spells.get("spellbook", []))
        if sp["prepared"] is not None:
            book = ch.get("spellbook", []) + (work.d["spells"].get(cls, {}).get("spellbook", []))
            pool = book if sp["spellbook"] is not None else [n for n in sp["spell_pool"] if n not in sp["always_prepared"]]
            ch["prepared"] = _prefer(pool, sp["prepared"], cur_spells.get("prepared", []))
    return ch


def _replay(current: Character, recorded: Optional[List[Optional[dict]]] = None):
    """Replay every class level on the level-0 base. Returns (character with full history, [{class, choices}] per level)."""
    order: List[str] = []
    for entry in current.classes:
        order += [entry["name"]] * entry["level"]
    work = base_of(current)
    wanted = Character.from_dict(copy.deepcopy(current.d))     # what unrecorded levels should aim for: the sheet minus
    _drop_granted(wanted, _granted(current))                    # what recorded later levels will add themselves
    spare = {"feats": list(current.d["feats"][(current.race_data() or {}).get("feats", 0):]),
             "points": {a: current.d["abilities"]["improvement"].get(a, 0) + current.d["abilities"]["feat"].get(a, 0)
                        for a in E.ABILITIES}}
    gains = current.d["hp"]["gains"]
    after = {e["level"]: e["state"] for e in current.d.get("level_history", []) if e.get("state")}   # the sheet after level N
    entries: List[dict] = []
    for i, cls in enumerate(order):
        choices = LV.fit_prepared(work, cls, recorded[i]) if recorded and i < len(recorded) else None
        target = _at_level(current, after[i + 1]) if i + 1 in after else wanted
        if choices is None:
            plan = LV.plan_level_up(work, cls)
            choices = infer_choices(plan, target, work, spare)
            if i < len(gains) and i > 0 and 1 <= gains[i] <= rules.classes[cls]["hit_die"]:
                choices["hp"], choices["hp_roll"] = "roll", gains[i]            # keep the hit points actually gained
        ok = _fits(work, cls, choices)
        if not ok and recorded and i < len(recorded) and recorded[i] is not None:
            # recorded before the rules asked for something more (a Cavalier's bonus skill): keep every recorded choice
            # and fill in only what is missing, read off the sheet
            trial_spare = copy.deepcopy(spare)
            guess = infer_choices(LV.plan_level_up(work, cls, choices.get("subclass")), target, work, trial_spare)
            filled = {**guess, **{k: ({**guess[k], **v} if isinstance(v, dict) and isinstance(guess.get(k), dict) else v)
                                  for k, v in choices.items()}}
            if _fits(work, cls, filled):
                choices, ok = filled, True
                spare.update(trial_spare)
        work.snapshot_level(cls, choices if ok else None)
        if ok:
            LV.apply_level_up(work, cls, choices)
        else:                                                                   # the sheet didn't fit: first valid option
            entry = current.class_entry(cls)
            LV.autolevel(work, cls, subclass=(entry or {}).get("subclass"))
        entries.append({"class": cls, "choices": choices if ok else None})
    work.d["hp"]["current"] = min(current.current_hp, work.max_hp)
    work.d["conditions"] = list(current.d["conditions"])
    return work, entries


def _fits(work: Character, cls: str, choices: dict) -> bool:
    try:
        LV.apply_level_up(Character.from_dict(work.d), cls, choices)
        return True
    except LV.RulesError:
        return False


def _at_level(current: Character, state: dict) -> Character:
    """The character as a level-up snapshot shows it: what an unrecorded level aims for when the sheet right after it is
    known. The final sheet would mislead: a wizard's level 1 would take spells a recorded later level picked."""
    c = Character.from_dict(current.d)
    for k, v in state.items():
        if k == "hp_gains":
            c.d["hp"]["gains"] = list(v)
        else:
            c.d[k] = copy.deepcopy(v)
    return c


def reconstruct(current: Character, recorded: Optional[List[Optional[dict]]] = None) -> Character:
    """A copy of `current` carrying a complete level history (level 2 onwards; level 1 is character creation)."""
    work, _entries = _replay(current, recorded)
    work.d["level_history"] = work.d["level_history"][1:]
    return work


def level_entries(current: Character) -> List[dict]:
    """Every level from the first, as {class, choices}: recorded choices where known, otherwise rebuilt from the sheet."""
    history = current.d.get("level_history", [])
    offset = max(0, current.total_level - 1 - len(history))
    recorded = [None] * (1 + offset) + [e.get("choices") for e in history]
    return _replay(current, recorded)[1]


# ---------------------------------------------------------------- creation choices (race, background, ability scores)
def infer_origin(c: Character) -> dict:
    """The creation choices of a character as an editable spec (see creation.create_character): as recorded when it was
    made, otherwise read back from the sheet. Picks the sheet doesn't show are left out (the editor asks for them)."""
    d = c.d
    out = {"race": d["race"], "subrace": d["subrace"], "ancestry": d["ancestry"], "background": d["background"],
           "alignment": d["alignment"] or "", "scores_method": d.get("ability_method") or "manual",
           "scores": {a: d["abilities"]["base"].get(a, 10) for a in E.ABILITIES},
           "details": {k: d["details"].get(k, "") for k in TRAIT_KEYS}}
    if out["scores_method"] not in ("point_buy", "standard_array", "rolled", "manual"):
        out["scores_method"] = "manual"
    saved = d.get("origin") or {}
    if saved and all(saved.get(k) == d[k] for k in ("race", "subrace", "ancestry", "background")):
        out["race_choices"] = copy.deepcopy(saved.get("race_choices") or {})
        out["background_choices"] = copy.deepcopy(saved.get("background_choices") or {})
        return out
    out["race_choices"] = _race_choices(c) if d["race"] in rules.races else {}
    out["background_choices"] = _background_choices(c, out) if d["background"] in rules.backgrounds else {}
    return out


def _race_choices(c: Character) -> dict:
    """Racial picks read from the sheet. Creation adds the race's proficiencies first, so they lead each list."""
    race = rules.races[c.race]
    sub = next((s for s in race["subraces"] if s["name"] == c.subrace), None)
    try:
        req = race_requirements(c.race, c.subrace)
    except (KeyError, LV.RulesError):
        return {}
    prof, ch = c.d["proficiencies"], {}
    pick = req["ability_choose"]
    if pick:
        fixed, racial = racial_fixed(race, sub), c.d["abilities"]["racial"]
        raised = [a for a in pick["from"] if racial.get(a, 0) - fixed.get(a, 0) >= pick["amount"]]
        ch["ability"] = _prefer(pick["from"], pick["count"], raised)
    if req["languages_any"]:
        fixed = racial_languages(race, sub)
        ch["languages"] = [x for x in prof["languages"] if x not in fixed][:req["languages_any"]]
    fixed_skills = {rules.skill_name(s) for src in (race, sub or {}) for s in src.get("skills", {}).get("fixed", [])}
    if req["skills_any"]:
        ch["skills"] = [s for s in prof["skills"] if s not in fixed_skills][:req["skills_any"]]
    if req["tool"] and req["tool"]["from"]:
        ch["tools"] = _prefer(req["tool"]["from"], req["tool"]["count"], prof["tools"])
    blocks = _spell_blocks(race, sub)
    if req["cantrip_choice"]:
        specs = [n["choose"] for b in blocks for _l, n in _known_entries(b) if isinstance(n, dict) and "choose" in n]
        pool = {x for spec in specs for x in choose_pool(spec)}
        ch["cantrips"] = [s["name"] for s in c.d["racial_spells"] if s.get("source") == "Race" and s["name"] in pool][:req["cantrip_choice"]]
    if req["spell_ability"]:
        ab = next((s.get("ability") for s in c.d["racial_spells"] if s.get("source") == "Race"), None)
        ch["spell_ability"] = ab if ab in req["spell_ability"] else req["spell_ability"][0]
    if req["feats"] and c.d["feats"]:
        ch["feat"] = c.d["feats"][0]                    # the race's feat came before any class level
        race_profs = {"skills": fixed_skills | set(ch.get("skills") or []),
                      "tools": {t.lower() for src in (race, sub or {}) for t in src.get("tools", {}).get("fixed", [])}
                      | {t.lower() for t in ch.get("tools") or []}}
        ch["feat_choices"] = _feat_choices(c, ch["feat"], race_profs, race, sub)
    return ch


def _feat_choices(c: Character, name: str, race_profs: dict, race: dict, sub: Optional[dict]) -> dict:
    """What a feat taken at creation chose, read from the sheet (as far as it shows)."""
    feat = rules.feats.get(name)
    if not feat:
        return {}
    prof, fc = c.d["proficiencies"], {}
    ab = feat["ability"]["choose"]
    if ab:
        bonus = c.d["abilities"]["feat"]
        fc["ability"] = next((a for a in ab["from"] if bonus.get(a, 0) >= ab["amount"]), ab["from"][0])
    if name == "Resilient":
        first = rules.classes.get(c.classes[0]["name"]) if c.classes else None
        fc["ability"] = next((a for a in prof["saves"] if not first or a not in first["saves"]), None)
    elif name == "Skilled":                             # the feat's picks follow the race's, before the background's
        bg = rules.backgrounds.get(c.background) or {}
        bg_skills = {rules.skill_name(s) for s in bg.get("skills", {}).get("fixed", [])}
        bg_tools = {t.lower() for t in bg.get("tools", {}).get("fixed", [])}
        skills = [s for s in prof["skills"] if s not in race_profs["skills"]]
        skills = skills[:next((i for i, s in enumerate(skills) if s in bg_skills), len(skills))]
        tools = [t for t in prof["tools"] if t.lower() not in race_profs["tools"]]
        tools = tools[:next((i for i, t in enumerate(tools) if t.lower() in bg_tools), len(tools))]
        fc["proficiencies"] = (skills + tools)[:3]
    elif name == "Weapon Master":
        own = {w for src in (race, sub or {}) for w in src.get("weapons", [])}
        names = {w["name"] for w in rules.weapons()}
        fc["weapons"] = [w for w in prof["weapons"] if w in names and w not in own][:4]
    elif name == "Magic Initiate":
        spells = [s["name"] for s in c.d["racial_spells"] if s.get("source") == "Magic Initiate"]
        levels = {n: (rules.spell(n) or {}).get("level") for n in spells}
        fc["cantrips"] = [n for n in spells if levels[n] == 0][:2]
        fc["spell"] = next((n for n in spells if levels[n] == 1), "")
        lists = {k: {s["name"] for s in rules.class_spell_list(k)} for k in ("Bard", "Cleric", "Druid", "Sorcerer", "Warlock", "Wizard")}
        fc["class"] = next((k for k, names in lists.items() if set(spells) <= names), "Wizard")
    elif name == "Elemental Adept" and c.d["choices"].get("elemental_adept"):
        fc["damage"] = c.d["choices"]["elemental_adept"]
    else:
        fc.update(FE.picks(c, name))                    # Fey Touched's spell, Metamagic Adept's options...
    return fc


def _background_choices(c: Character, origin: dict) -> dict:
    """Background picks read from the sheet: what the race didn't give, in the order creation added them."""
    work = Character.create_blank("probe")
    try:
        apply_race(work, origin["race"], origin["subrace"], origin["ancestry"], origin["race_choices"])
    except (KeyError, LV.RulesError):
        pass
    known, prof = work.d["proficiencies"], c.d["proficiencies"]
    bg = rules.backgrounds[c.background]
    req = background_requirements(c.background)
    fixed = [rules.skill_name(s) for s in bg.get("skills", {}).get("fixed", [])]
    ch = {}
    wanted = req["skills_any"] + sum(1 for s in fixed if s in known["skills"])
    if wanted:
        ch["skills"] = [s for s in prof["skills"] if s not in known["skills"] and s not in fixed][:wanted]
    if req["languages_any"]:
        ch["languages"] = [x for x in prof["languages"] if x not in known["languages"]][:req["languages_any"]]
    if req["tools_count"]:
        pool = {t.lower(): t for t in background_tool_pool(req)}
        have = {t.lower() for t in known["tools"]} | {tool_name(t).lower() for t in bg.get("tools", {}).get("fixed", [])}
        ch["tools"] = [pool[t.lower()] for t in prof["tools"] if t.lower() in pool and t.lower() not in have][:req["tools_count"]]
    return ch


def origin_base(c: Character, origin: dict) -> Character:
    """The character before any class level, made again from new creation choices (`origin`: race, subrace, ancestry,
    race_choices, background, background_choices, scores_method, scores, alignment, details). Gear, notes, portrait,
    hit points and the rest of the sheet are kept. Raises RulesError when a choice breaks the rules."""
    b = Character.create_blank(c.name)
    for k, v in c.d.items():
        if k not in BUILD_KEYS:
            b.d[k] = copy.deepcopy(v)
    b.d["hp"]["gains"] = []
    b.d["choices"] = {k: v for k, v in c.d["choices"].items() if k == "milestone"}
    try:
        scores = {a: int(origin["scores"][a]) for a in E.ABILITIES}
    except (KeyError, TypeError, ValueError):
        raise LV.RulesError("Give every ability a score.")
    validate_base_scores(origin.get("scores_method", ""), scores)
    b.d["abilities"]["base"], b.d["ability_method"] = scores, origin["scores_method"]
    if origin.get("alignment") and origin["alignment"] not in E.ALIGNMENTS:
        raise LV.RulesError("Pick an alignment from the list.")
    b.d["alignment"] = origin.get("alignment") or ""
    if origin.get("race") not in rules.races:
        raise LV.RulesError("Choose a race.")
    apply_race(b, origin["race"], origin.get("subrace") or None, origin.get("ancestry") or None, origin.get("race_choices") or {})
    if origin.get("background") not in rules.backgrounds:
        raise LV.RulesError("Choose a background.")
    apply_background(b, origin["background"], origin.get("background_choices") or {})
    b.details.update({k: v for k, v in (origin.get("details") or {}).items() if k in TRAIT_KEYS})
    b.d["origin"] = {k: copy.deepcopy(origin.get(k)) for k in ORIGIN_KEYS}
    return b


# ---------------------------------------------------------------- hand edits survive a rebuild
def _recorded_prepared(c: Character, cls: str) -> Optional[list]:
    """The prepared list the last recorded level of `cls` chose (None when no level recorded one)."""
    for e in reversed(c.d.get("level_history", [])):
        ch = e.get("choices") or {}
        if e.get("class") == cls and ch.get("prepared") is not None:
            return list(ch["prepared"])
    return None


def copied_spells(c: Character) -> List[str]:
    """Spells in a spellbook that no level chose: copied in later (recorded since copying was, read off the history
    for older sheets)."""
    book = c.d["spells"].get("Wizard", {}).get("spellbook", [])
    known = list(c.d["choices"].get("copied_spells") or [])
    history = c.d.get("level_history", [])
    first = next((e["state"] for e in history if e.get("level") == 1 and e.get("state")), None)
    if not first or any(e.get("choices") is None for e in history):
        return known                                              # a level without its choices: can't be told apart
    picked = set(first.get("spells", {}).get("Wizard", {}).get("spellbook", []))
    for e in history:
        picked.update(e["choices"].get("spellbook") or [])
    return known + [s for s in book if s not in picked and s not in known]


def keep_hand_edits(before: Character, after: Character) -> None:
    """What was changed by hand outside level-ups stays when the levels are rebuilt (Edit levels, Undo last level-up,
    RESET ALL, new creation choices): proficiencies added or removed, milestone levelling, spells copied into a
    spellbook, a prepared list changed since the last level-up, the hit points missing, spent slots, hit dice and
    class resources. Without this the rebuilt levels would bring back the sheet as it was when each level was taken."""
    b, a = before.d, after.d
    if "milestone" in b["choices"]:
        a["choices"]["milestone"] = b["choices"]["milestone"]
    profs = a["proficiencies"]
    for key, add in (("manual_profs", True), ("manual_removed", False)):
        marks = copy.deepcopy(b["choices"].get(key) or {})
        if not marks:
            continue
        a["choices"][key] = marks
        for kind, names in marks.items():
            low = {n.lower() for n in names}
            if add:
                have = {x.lower() for x in profs.get(kind, [])}
                profs[kind] = profs.get(kind, []) + [n for n in names if n.lower() not in have]
            else:
                profs[kind] = [x for x in profs.get(kind, []) if x.lower() not in low]
    copied = copied_spells(before)
    book = a["spells"].get("Wizard", {}).get("spellbook")
    if copied and book is not None:
        book += [s for s in copied if s not in book]
        a["choices"]["copied_spells"] = copied
    for cls, sp in b["spells"].items():
        hand = sp.get("prepared")
        if cls not in a["spells"] or hand is None or hand == _recorded_prepared(before, cls):
            continue                                                  # not changed by hand since its last level-up
        if _recorded_prepared(after, cls) != _recorded_prepared(before, cls):
            continue                                                  # the edit chose the preparation again
        try:
            LV.set_prepared(after, cls, hand)
        except LV.RulesError:
            pass
    missing = max(0, before.max_hp - before.current_hp)
    a["hp"]["current"] = 0 if before.current_hp <= 0 else max(1, after.max_hp - missing)
    a["hit_dice_used"] = dict(b.get("hit_dice_used") or {})          # read capped by the class levels
    a["resources"] = dict(b.get("resources") or {})                   # read capped by each resource's maximum
    a["slots_used"] = dict(b.get("slots_used") or {})                 # read capped by the slots there are
