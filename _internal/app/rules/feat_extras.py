"""What some feats add to a character beyond their text: innate spells (Fey Touched, Shadow Touched, Telepathic, Drow High Magic...)
and the options they pick (Fighting Initiate's style, Eldritch Adept's invocation, Metamagic Adept's and Martial Adept's picks).

`fields(feat, char)` are the form fields the feat needs on top of its ability choice (creation_flow.feat_form shows them);
`apply(char, feat, choices)` writes the result onto the sheet (leveling.apply_feat calls it). A pick that is left out is
skipped: the feat's fixed spells are still learned. The battle reads them like any racial spell (`racial_spells`) or option."""
from typing import List

from . import feat_tables as T
from .data import rules

PICK_KEYS = ("spell", "spell2", "cantrips", "options", "spell_ability", "damage", "familiar", "class", "skills", "tools", "languages", "expertise")

# feat -> fixed innate spells [(spell, uses)], the spellcasting ability when the feat doesn't raise one, and a spell to pick
SPELLS = {
    "Fey Touched": {"fixed": [("Misty Step", "1/long rest")],
                    "pick": {"label": "Choose a 1st-level divination or enchantment spell", "schools": ("Divination", "Enchantment")}},
    "Shadow Touched": {"fixed": [("Invisibility", "1/long rest")],
                       "pick": {"label": "Choose a 1st-level illusion or necromancy spell", "schools": ("Illusion", "Necromancy")}},
    "Artificer Initiate": {"ability": "int", "cantrip": {"label": "Choose an artificer cantrip", "class": "Artificer"},
                           "pick": {"label": "Choose a 1st-level artificer spell", "class": "Artificer"}},
    "Aberrant Dragonmark": {"ability": "con", "cantrip": {"label": "Choose a sorcerer cantrip", "class": "Sorcerer"},
                            "pick": {"label": "Choose a 1st-level sorcerer spell", "class": "Sorcerer", "uses": "1/short rest"}},
    "Outlands Envoy": {"fixed": [("Misty Step", "1/long rest"), ("Tongues", "1/long rest")]},
    "Telepathic": {"fixed": [("Detect Thoughts", "1/long rest")]},
    "Telekinetic": {"fixed": [("Mage Hand", None)]},
    "Drow High Magic": {"ability": "cha", "fixed": [("Detect Magic", "at will"), ("Levitate", "1/long rest"), ("Dispel Magic", "1/long rest")]},
    "Fey Teleportation": {"fixed": [("Misty Step", "1/short rest")]},
    "Gift of the Metallic Dragon": {"fixed": [("Cure Wounds", "1/long rest")]},       # Draconic Healing: the ability raised is the casting one
    "Wood Elf Magic": {"ability": "wis", "cantrip": {"label": "Choose a druid cantrip", "class": "Druid"},
                       "fixed": [("Longstrider", "1/long rest"), ("Pass without Trace", "1/long rest")]},
    "Svirfneblin Magic": {"ability": "int", "fixed": [("Nondetection", "at will"), ("Blindness/Deafness", "1/long rest"), ("Blur", "1/long rest"),
                                                       ("Disguise Self", "1/long rest")]},
}
SPELLS.update({feat: {"ability": "choose"} for feat in T.ADEPT})   # the Adept feats: their table spells (feat_tables.ADEPT) in the ability the feat raises
SPELLS.update(T.SPELLS)                               # Heroes of Faerun, Eberron's marks, Ravenloft, Arcana Unleashed, Lorwyn... (feat_tables.py)
# feat -> (what is picked: option types, how many, label)
OPTIONS = {
    "Fighting Initiate": ({"FS:F"}, 1, "Choose a fighting style"),
    "Eldritch Adept": ({"EI"}, 1, "Choose an eldritch invocation (one without prerequisites)"),
    "Metamagic Adept": ({"MM"}, 2, "Choose two metamagic options"),
    "Martial Adept": ({"MV:B"}, 2, "Choose two maneuvers"),
}
ABILITY_FEATS = ("Eldritch Adept",)         # no ability to raise, but the invocation's casting ability is picked


def _spells(cls=None, schools=None, level=1) -> List[str]:
    pool = rules.class_spell_list(cls) if cls else rules.offered(rules.spells.values())
    return sorted({s["name"] for s in pool if s["level"] == level and (not schools or s.get("school") in schools)})


def _options(char, types) -> List[str]:
    have = set(char.d["options"])
    return sorted(o["name"] for o in rules.option_list(char.sources) if set(o["types"]) & types and o["name"] not in have
                  and not o["prerequisite"])


def _known(char, name: str) -> bool:
    from .leveling import taken_spells
    return name.lower() in taken_spells(char)


def _have(char, kind: str) -> set:
    return set(char.d["proficiencies"][kind])


def _pool(char, p: dict, level: int = 1) -> List[str]:
    """Spells a pick offers: from a class list (or two), a school, a casting time, up to a level; what the character knows is left out."""
    classes = p.get("class")
    classes = [classes] if isinstance(classes, str) else list(classes or [])
    pool = [s for c in classes for s in rules.class_spell_list(c)] if classes else rules.offered(rules.spells.values())
    top = p.get("max", level)
    names = {s["name"] for s in pool if (s["level"] == level if p.get("max") is None else 1 <= s["level"] <= top)
             and (not p.get("schools") or s.get("school") in p["schools"])
             and (not p.get("action") or str(s.get("casting_time") or "").lower().startswith("1 action"))}
    names |= {n for n in p.get("extra") or [] if rules.spell(n)}
    return sorted(n for n in names if char is None or not _known(char, n))


def _cantrips(char, p: dict) -> List[str]:
    classes = p.get("class")
    classes = [classes] if isinstance(classes, str) else list(classes or [])
    names = {s["name"] for c in classes for s in rules.class_spell_list(c) if s["level"] == 0 and (not p.get("schools") or s.get("school") in p["schools"])}
    return sorted(n for n in names if char is None or not _known(char, n))


def _select(key: str, label: str, values, reload: bool = False) -> dict:
    f = {"key": key, "kind": "select", "label": label, "options": [{"value": v, "label": v if v not in E_ABILITY else E_ABILITY[v]} for v in values]}
    if reload:
        f["reload"] = True
    return f


E_ABILITY = {"int": "Intelligence", "wis": "Wisdom", "cha": "Charisma"}
SCHOOLS = ["Abjuration", "Conjuration", "Divination", "Enchantment", "Evocation", "Illusion", "Necromancy", "Transmutation"]
MI_CLASSES = ["Bard", "Cleric", "Druid", "Sorcerer", "Warlock", "Wizard"]


def mi_class(char) -> str:
    """The Magic Initiate list a character chose (the one that holds every spell the feat gave), Wizard if it can't tell."""
    mine = [s["name"] for s in char.d["racial_spells"] if s.get("source") == "Magic Initiate"]
    for k in MI_CLASSES:
        if mine and set(mine) <= {s["name"] for s in rules.class_spell_list(k)}:
            return k
    return "Wizard"


def fields(feat: str, char, sel=None) -> List[dict]:
    """Extra form fields: [{key, kind: 'pick' | 'select', label, options, count, single?, reload?}]. `sel`: the value of the
    field that reloads the form (the school of Boon of Magic School Mastery, the list of Magic Connoisseur)."""
    out = []
    spec = SPELLS.get(feat)
    if spec and spec.get("ability") in ("pick", "familiar", "connoisseur") and not (spec["ability"] == "familiar" and "Familiar Friend" in char.d["feats"]) \
            and not (spec["ability"] == "connoisseur" and any(s.get("source") == "Magic Initiate" for s in char.d["racial_spells"])):
        out.append(_select("spell_ability", "Spellcasting ability for this feat's spells", T.ABILITY_PICK))
    if spec and spec.get("cantrip"):
        c = spec["cantrip"]
        out.append({"key": "cantrips", "kind": "pick", "label": c["label"], "options": _cantrips(char, c), "count": c.get("count", 1)})
    if spec and spec.get("cantrip_fixed") and _known(char, spec["cantrip_fixed"]):
        c = spec["cantrip_alt"]
        out.append({"key": "cantrips", "kind": "pick", "label": c["label"], "options": _cantrips(char, c), "count": 1})
    if spec and spec.get("pick"):
        p = spec["pick"]
        out.append({"key": "spell", "kind": "pick", "label": p["label"], "options": _pool(char, p), "count": 1, "single": True})
    if spec and spec.get("ability") == "connoisseur":
        out.append(_select("class", "Magic Initiate spell list", MI_CLASSES, True))
        pick = {"class": sel or mi_class(char)}
        out.append({"key": "spell", "kind": "pick", "label": "Choose a 1st-level spell", "options": _pool(char, pick, 1), "count": 1, "single": True})
        out.append({"key": "spell2", "kind": "pick", "label": "Choose a 2nd-level spell", "options": _pool(char, pick, 2), "count": 1, "single": True})
    if spec and spec.get("school_mastery"):
        school = sel if sel in SCHOOLS else SCHOOLS[0]
        mine = [c for c in (i["class"] for i in _casters(char))]
        out.append(_select("class", "Mastered school of magic", SCHOOLS, True))
        out.append({"key": "spell", "kind": "pick", "label": f"Rote Casting: a 1st-level {school} spell from your class's list",
                    "options": _pool(char, {"class": mine or None, "schools": (school,)}, 1), "count": 1, "single": True})
        out.append({"key": "spell2", "kind": "pick", "label": f"Signature Arcanum: a {school} spell of level 7 or lower",
                    "options": _pool(char, {"schools": (school,), "max": 7}), "count": 1, "single": True})
    if feat in OPTIONS:
        types, count, label = OPTIONS[feat]
        out.append({"key": "options", "kind": "pick", "label": label, "options": _options(char, types), "count": count})
    if feat in T.RESIST_PICKS:
        out.append(_select("damage", "Damage resistance", T.RESIST_PICKS[feat]))
    if feat in T.FAMILIAR_PICKS:
        out.append(_select("familiar", "Damage your familiar is imbued with", T.FAMILIAR_PICKS[feat]))
    g = T.GRANTS.get(feat) or {}
    proficient = _have(char, "skills")
    if g.get("skills_from"):
        pool, n = g["skills_from"]
        out.append({"key": "skills", "kind": "pick", "label": f"Choose {n} skill proficienc{'y' if n == 1 else 'ies'}", "options": [s for s in pool if s not in proficient], "count": n})
    if g.get("skills_any"):
        out.append({"key": "skills", "kind": "pick", "label": f"Choose {g['skills_any']} skills", "options": [s for s in rules.skills if s not in proficient], "count": g["skills_any"]})
    if g.get("expertise_pick"):
        out.append({"key": "expertise", "kind": "pick", "label": "Choose a skill you are proficient in for Expertise",
                    "options": [s for s in (rules.skills if g.get("skills_any") else sorted(proficient)) if s not in _have(char, "expertise")],
                    "count": 1, "single": True})
    if g.get("instrument"):
        have = {t.lower() for t in _have(char, "tools")}
        pool = sorted(i["name"] for i in rules.items.values() if i["type"] == "INS" and not i["magic"] and i["source"] == "PHB" and i["name"].lower() not in have)
        out.append({"key": "tools", "kind": "pick", "label": "Choose a musical instrument", "options": pool, "count": 1})
    if g.get("language_any") or (g.get("draconic") and "Draconic" in _have(char, "languages")):
        out.append({"key": "languages", "kind": "pick", "label": "Choose a language", "options": [x for x in rules.all_languages() if x not in _have(char, "languages")], "count": 1})
    return out


def _casters(char) -> List[dict]:
    from . import spellcasting as SC
    return SC.casters(char)


def _ability_of(char, feat: str, spec: dict, choices: dict) -> str:
    """The ability a feat's spells are cast with."""
    kind = spec.get("ability")
    picked = choices.get("spell_ability")
    if kind == "pick":
        return picked if picked in T.ABILITY_PICK else "int"
    if kind == "choose":
        return choices.get("ability") if choices.get("ability") in T.ABILITY_PICK else picked if picked in T.ABILITY_PICK else "cha"
    if kind in ("familiar", "connoisseur"):
        src = "Familiar Friend" if kind == "familiar" else "Magic Initiate"
        have = next((s["ability"] for s in char.d["racial_spells"] if s.get("source") == src), None)
        return have or (picked if picked in T.ABILITY_PICK else "int")
    return choices.get("ability") or kind or "cha"


def _ok_pick(value, allowed, what: str):
    """One valid pick out of a form answer (a name or a list of names): the name, or None when it isn't one of `allowed`."""
    one = value if isinstance(value, str) else (list(value or [None]) or [None])[0]
    if one and one not in allowed:
        from .leveling import RulesError
        raise RulesError(f"{one} isn't a valid choice for {what}.")
    return one or None


def _spells_for(char, feat: str, spec: dict, choices: dict) -> None:
    ab = _ability_of(char, feat, spec, choices)
    mine = {s["name"].lower() for s in char.d["racial_spells"] if s.get("source") == feat}

    def add(name, uses, level=1, **more):
        sp = rules.spell(name)
        if sp and sp["name"].lower() not in mine:
            mine.add(sp["name"].lower())
            entry = {"name": sp["name"], "level_req": level, "ability": ab, "source": feat}
            if uses:
                entry["uses"] = uses
                if spec.get("slots"):
                    entry["slots"] = True              # the free cast first, then spell slots
            if spec.get("ritual"):
                entry["ritual"] = True
            entry.update(more)
            char.d["racial_spells"].append(entry)

    for item in spec.get("fixed", []):
        name, uses, level = (tuple(item) + (1,))[:3]
        if uses is None and _known(char, name) and spec.get("cantrip_fixed") is None and sp_level(name) == 0:
            continue                                       # a cantrip it already knows
        add(name, uses, level)
    if spec.get("cantrip_fixed"):
        name = spec["cantrip_fixed"]
        if not _known(char, name):
            add(name, None)
        else:
            alt = _ok_pick(choices.get("cantrips"), _cantrips(None, spec["cantrip_alt"]), feat)
            if alt:
                add(alt, None)
    if spec.get("pick"):
        p = spec["pick"]
        one = _ok_pick(choices.get("spell"), _pool(None, p), feat)
        if one:
            add(one, p.get("uses", "1/long rest"))
    if spec.get("cantrip"):
        c = spec["cantrip"]
        ok = _cantrips(None, c)
        picked = [choices["cantrips"]] if isinstance(choices.get("cantrips"), str) else list(choices.get("cantrips") or [])
        for n in picked[:c.get("count", 1)]:
            _ok_pick(n, ok, feat)
            add(n, None)
    if spec.get("ability") == "connoisseur":
        pool = {"class": choices.get("class") if choices.get("class") in MI_CLASSES else mi_class(char)}
        for key, level in (("spell", 1), ("spell2", 2)):
            one = _ok_pick(choices.get(key), _pool(None, pool, level), feat)
            if one:
                add(one, T.FREE, 1)
    if spec.get("school_mastery"):
        school = choices.get("class") if choices.get("class") in SCHOOLS else None
        if school:
            lists = [c["class"] for c in _casters(char)]
            rote = _ok_pick(choices.get("spell"), _pool(None, {"class": lists or None, "schools": (school,)}, 1), feat)
            if rote:
                add(rote, "at will", 1)                    # Rote Casting: no slot and no components
            arcanum = _ok_pick(choices.get("spell2"), _pool(None, {"schools": (school,), "max": 7}), feat)
            if arcanum:
                add(arcanum, T.FREE, 1, slots=True)
    for slot, name in (T.ADEPT.get(feat) or {}).items():   # the Adept feats: always prepared once a slot of that level is there
        add(name, None, 1, slot_req=slot)


def sp_level(name: str) -> int:
    return (rules.spell(name) or {}).get("level", 1)


def _grants(char, feat: str, g: dict, choices: dict) -> None:
    """Skills, expertise, tools and languages a feat gives. A pick that isn't valid raises a RulesError (it is a choice the player makes)."""
    from .leveling import RulesError
    profs = char.d["proficiencies"]

    def need(key, n):
        got = choices.get(key)
        got = [got] if isinstance(got, str) else list(got or [])
        if len(got) != n:
            raise RulesError(f"{feat}: choose {n} {key if n > 1 else key.rstrip('s')}.")
        return got

    for s in g.get("expert", []):
        if s not in profs["skills"]:
            profs["skills"].append(s)
        if s not in profs["expertise"]:
            profs["expertise"].append(s)
    new = []
    if g.get("skills_from") or g.get("skills_any"):
        pool = g["skills_from"][0] if g.get("skills_from") else list(rules.skills)
        n = g["skills_from"][1] if g.get("skills_from") else g["skills_any"]
        for s in need("skills", n):
            if s not in pool or s in profs["skills"]:
                raise RulesError(f"You are already proficient in {s} (or it isn't one of the choices): choose another skill.")
            profs["skills"].append(s)
            new.append(s)
    if g.get("expertise_pick"):
        (s,) = need("expertise", 1)
        if s not in profs["skills"] or s in profs["expertise"]:
            raise RulesError(f"{feat}: Expertise needs a skill you are proficient in and have no Expertise in.")
        profs["expertise"].append(s)
    if g.get("instrument"):
        (t,) = need("tools", 1)
        if t.lower() in {x.lower() for x in profs["tools"]}:
            raise RulesError(f"You are already proficient with {t}.")
        profs["tools"].append(t)
    for lang in g.get("languages_fixed", []):
        if lang not in profs["languages"]:
            profs["languages"].append(lang)
    if g.get("draconic") and "Draconic" not in profs["languages"]:
        profs["languages"].append("Draconic")
    elif g.get("language_any") or (g.get("draconic") and choices.get("languages")):
        (lang,) = need("languages", 1)
        if lang in profs["languages"]:
            raise RulesError(f"You already speak {lang}: choose another language.")
        profs["languages"].append(lang)


def apply(char, feat: str, choices: dict) -> None:
    """Innate spells, picked options, resistances and proficiencies onto the sheet. Invalid spell picks are ignored."""
    spec = SPELLS.get(feat)
    if spec:
        char.d["racial_spells"] = [r for r in char.d["racial_spells"] if r.get("source") != feat]       # taking it again (editing) starts from nothing
        _spells_for(char, feat, spec, choices)
    if feat == "Potent Dragonmark":                        # Spells of the Mark of every mark held: always prepared
        for mark in char.d["feats"]:
            ab = (picks(char, mark) or {}).get("spell_ability") or next((s["ability"] for s in char.d["racial_spells"] if s.get("source") == mark), "int")
            for level, names in (T.MARK_SPELLS.get(mark) or {}).items():
                for n in names:
                    sp = rules.spell(n)
                    if sp and not any(r["name"] == sp["name"] and r.get("source") == feat for r in char.d["racial_spells"]):
                        char.d["racial_spells"].append({"name": sp["name"], "level_req": 1, "ability": ab, "source": feat, "slot_req": level})
    if feat == "Greater Mark of Healing":                  # Cure Wounds free a proficiency bonus times
        for r in char.d["racial_spells"]:
            if r.get("source") == "Mark of Healing" and r["name"] == "Cure Wounds":
                r["uses"] = "pb/long rest"
    if feat in T.GRANTS:
        _grants(char, feat, T.GRANTS[feat], choices)
    if feat in T.RESIST_PICKS and choices.get("damage") not in T.RESIST_PICKS[feat]:
        from .leveling import RulesError
        raise RulesError(f"{feat}: choose a damage type ({', '.join(T.RESIST_PICKS[feat])}).")
    if feat in T.FAMILIAR_PICKS and choices.get("familiar") not in T.FAMILIAR_PICKS[feat]:
        from .leveling import RulesError
        raise RulesError(f"{feat}: choose a damage type ({', '.join(T.FAMILIAR_PICKS[feat])}).")
    if feat in OPTIONS:
        types, count, _label = OPTIONS[feat]
        ok = set(_options(char, types))
        for n in list(choices.get("options") or [])[:count]:
            if n in ok and n not in char.d["options"]:
                char.d["options"].append(n)
    kept = {k: choices[k] for k in PICK_KEYS if choices.get(k)}
    if spec or feat in OPTIONS or feat in T.GRANTS or feat in T.RESIST_PICKS or feat in T.FAMILIAR_PICKS or kept:
        # kept so editing the character later shows the same picks (reconstruct.py)
        char.d.setdefault("choices", {}).setdefault("feat_picks", {})[feat] = kept


def picks(char, feat: str) -> dict:
    """The form answers `apply` stored for a feat: {'spell', 'cantrips', 'options', 'damage', 'skills'...} (empty for older sheets)."""
    return dict((char.d.get("choices") or {}).get("feat_picks", {}).get(feat) or {})


# ---------------------------------------------------------------- what the sheet shows (character.py asks)
def speed_bonus(char) -> int:
    """Feet a feat adds to the walking speed (Mark of Passage, Transmuted Anatomy)."""
    return sum(n for feat, n in T.SPEED.items() if feat in char.d["feats"])


def resistances(char) -> List[str]:
    """Damage types the feats give resistance to: fixed ones and the one picked (Dragonscarred, Portal Jumper, Spell Resistant)."""
    out: List[str] = []
    for feat in char.d["feats"]:
        out += T.RESIST_FIXED.get(feat, [])
        if feat in T.RESIST_PICKS:
            pick = picks(char, feat).get("damage")
            if pick in T.RESIST_PICKS[feat]:
                out.append(pick)
    return out
