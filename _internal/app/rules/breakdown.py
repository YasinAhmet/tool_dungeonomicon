"""Where every number on a sheet comes from (shown as tooltips) and what each feature changes.

Each function returns a list of lines (text, feature) - `feature` names the feature, feat, option or item that
contributed, or None. `effects()` inverts that into {feature name: [what it changes]} for feature tooltips.
"""
from typing import Dict, List, Optional, Tuple

from . import engine as E
from .character import SKILLS, Character
from .data import rules

Line = Tuple[str, Optional[str]]


def _s(n: int) -> str:
    return f"{n:+d}"


def _items(char: Character):
    return list(char._active_items())


# ------------------------------------------------------------------ abilities
def ability(char: Character, a: str) -> List[Line]:
    ab = char.d["abilities"]
    name = E.ABILITY_NAMES[a]
    method = char.d.get("ability_method")
    lines: List[Line] = [(f"Base score {ab['base'].get(a, 10)}" + (f" ({method})" if method else ""), None)]
    if ab["racial"].get(a):
        lines.append((f"Race ({char.race_display}) {_s(ab['racial'][a])}", None))
    if ab["improvement"].get(a):
        lines.append((f"Ability Score Improvements {_s(ab['improvement'][a])}", None))
    if ab["feat"].get(a):
        feats = [f for f in char.d["feats"] if (rules.feats.get(f) or {}).get("ability")]
        lines.append((f"Feats {_s(ab['feat'][a])}" + (f" ({', '.join(feats)})" if feats else ""),
                      feats[0] if len(feats) == 1 else None))
    raw = ab["base"].get(a, 10) + sum(ab[k].get(a, 0) for k in ("racial", "improvement", "feat"))
    if raw > E.MAX_ABILITY:
        lines.append((f"Capped at {E.MAX_ABILITY}", None))
    for entry, item in _items(char):
        static = (item.get("ability") or {}).get("static", {})
        if a in static and static[a] > min(raw, E.MAX_ABILITY):
            lines.append((f"{entry['name']} sets {name} to {static[a]}", entry["name"]))
    score = char.ability_score(a)
    lines.append((f"= {score}  (modifier {_s(E.modifier(score))})", None))
    return lines


def save(char: Character, a: str) -> List[Line]:
    lines: List[Line] = [(f"{E.ABILITY_NAMES[a]} modifier {_s(char.mod(a))}", None)]
    if char.save_proficient(a):
        cls = next((c["name"] for c in char.classes if a in rules.classes[c["name"]]["saves"]), None)
        lines.append((f"Proficiency {_s(char.proficiency_bonus)}" + (f" (class: {cls})" if cls else ""), None))
    for entry, item in _items(char):
        if item.get("bonus_save"):
            lines.append((f"{entry['name']} {_s(item['bonus_save'])}", entry["name"]))
    if char.has_feature("Aura of Protection") and char.current_hp > 0:
        lines.append((f"Aura of Protection {_s(max(1, char.mod('cha')))} (Charisma)", "Aura of Protection"))
    lines.append((f"= {_s(char.saving_throws()[a]['bonus'])}", None))
    return lines


RACE_SKILLS = {"Keen Senses": "Perception", "Menacing": "Intimidation", "Natural Athlete": "Athletics"}


def _skill_origin(char: Character, skill_name: str) -> str:
    key = skill_name.lower()
    bg = rules.backgrounds.get(char.background) if char.background else None
    if bg and key in [str(x).lower() for x in bg["skills"].get("fixed", [])]:
        return f"background: {bg['name']}"
    race = char.race_data()
    for trait in (race["traits"] if race else []):
        if RACE_SKILLS.get(trait["name"]) == skill_name:
            return f"race: {trait['name']}"
    for c in char.classes:
        if skill_name in [rules.skill_name(s) for s in rules.classes[c["name"]]["skills"]["choose"]]:
            return f"class: {c['name']}"
    return "chosen"


def skill(char: Character, name: str) -> List[Line]:
    sb = char.skill_bonus(name)
    pb = char.proficiency_bonus
    lines: List[Line] = [(f"{E.ABILITY_NAMES[sb['ability']]} modifier {_s(char.mod(sb['ability']))}", None)]
    if sb["expertise"]:
        lines.append((f"Expertise {_s(2 * pb)} (double proficiency)", "Expertise"))
    elif sb["proficient"]:
        lines.append((f"Proficiency {_s(pb)} ({_skill_origin(char, name)})", None))
    elif char.has_feature("Jack of All Trades"):
        lines.append((f"Jack of All Trades {_s(pb // 2)}", "Jack of All Trades"))
    elif sb["ability"] in ("str", "dex", "con") and char.has_feature("Remarkable Athlete"):
        lines.append((f"Remarkable Athlete {_s((pb + 1) // 2)}", "Remarkable Athlete"))
    else:
        lines.append(("Not proficient", None))
    lines.append((f"= {_s(sb['bonus'])}", None))
    return lines


def passive_perception(char: Character) -> List[Line]:
    lines: List[Line] = [("10 base", None), (f"Perception {_s(char.skill_bonus('Perception')['bonus'])}", None)]
    if "Observant" in char.d["feats"]:
        lines.append(("Observant +5", "Observant"))
    lines.append((f"= {char.passive_perception}", None))
    return lines


def proficiency(char: Character) -> List[Line]:
    return [(f"Total level {char.total_level}: {_s(char.proficiency_bonus)}", None)]


def initiative(char: Character) -> List[Line]:
    lines: List[Line] = [(f"Dexterity modifier {_s(char.mod('dex'))}", None)]
    if "Alert" in char.d["feats"]:
        lines.append(("Alert +5", "Alert"))
    if char.has_feature("Jack of All Trades"):
        lines.append((f"Jack of All Trades {_s(char.proficiency_bonus // 2)}", "Jack of All Trades"))
    lines.append((f"= {_s(char.initiative)}", None))
    return lines


def speed(char: Character) -> List[Line]:
    race = char.race_data()
    base = race["speed"].get("walk", 30) if race else 30
    lines: List[Line] = [(f"Base walking speed {base} ft ({char.race_display})", None)]
    armor = char.equipped_armor()
    if armor and armor.get("strength") and char.ability_score("str") < int(armor["strength"]):
        lines.append((f"{armor['name']} needs Strength {armor['strength']}: -10 ft", armor["name"]))
    heavy = armor is not None and armor["type"] == "HA"
    if char.has_feature("Fast Movement") and not heavy and char.class_level("Barbarian") >= 5:
        lines.append(("Fast Movement +10 ft", "Fast Movement"))
    if char.has_feature("Unarmored Movement") and armor is None:
        lines.append((f"Unarmored Movement +{char.table_value('Monk', 'Unarmored Movement', default=0, number=True)} ft",
                      "Unarmored Movement"))
    if "Mobile" in char.d["feats"]:
        lines.append(("Mobile +10 ft", "Mobile"))
    lines.append((f"= {char.speed} ft", None))
    return lines


def hit_points(char: Character) -> List[Line]:
    hp = char.d["hp"]
    level = char.total_level
    lines: List[Line] = []
    for c in char.classes:
        lines.append((f"{c['name']}: d{rules.classes[c['name']]['hit_die']} hit die, {c['level']} level(s)", None))
    lines.append((f"Hit die results {sum(hp['gains'])}", None))
    lines.append((f"Constitution {_s(char.mod('con'))} x {level} levels = {_s(char.mod('con') * level)}", None))
    for name in ("Dwarven Toughness", "Draconic Resilience"):
        if char.has_feature(name):
            lines.append((f"{name} +1 x {level} = {_s(level)}", name))
    if "Tough" in char.d["feats"]:
        lines.append((f"Tough +2 x {level} = {_s(2 * level)}", "Tough"))
    if hp["bonus"]:
        lines.append((f"Manual adjustment {_s(hp['bonus'])}", None))
    lines.append((f"= {char.max_hp}", None))
    return lines


def armor_class(char: Character) -> List[Line]:
    ac, why = char.armor_class()
    armor, shield = char.equipped_armor(), char.equipped_shield()
    lines: List[Line] = []
    for part in (p.strip() for p in why.split(", ")):
        feature = None
        if armor and part.startswith(armor["name"]):
            feature = armor["name"]
        elif shield and part.startswith("Shield"):
            feature = shield["name"]
        elif "Defense" in part:
            feature = "Defense"
        elif part.startswith("10 + Dex +") or part.startswith("13 + Dex"):
            feature = "Draconic Resilience" if part.startswith("13") else "Unarmored Defense"
        elif "magic" in part and armor:
            feature = armor["name"]
        else:
            for _e, item in _items(char):
                if part.startswith(item["name"]):
                    feature = item["name"]
        lines.append((part, feature))
    lines.append((f"= {ac}", None))
    return lines


def spell_dc(char: Character, info: dict) -> List[Line]:
    mod = E.modifier(char.ability_score(info["ability"]))
    return [(f"8 base + proficiency {char.proficiency_bonus} + {E.ABILITY_NAMES[info['ability']]} {_s(mod)}", None),
            (f"= {info['dc']}  (spell attack {_s(info['attack'])})", None)]


# ------------------------------------------------------------------ rendering helpers
def text(lines: List[Line], title: str = "") -> str:
    body = "\n".join(t for t, _f in lines)
    return f"{title}\n{body}" if title else body


# ------------------------------------------------------------------ feature -> what it changes
def effects(char: Character) -> Dict[str, List[str]]:
    """{feature/feat/option/item name: ['Armor Class: +1', ...]} for everything that visibly alters a stat."""
    out: Dict[str, List[str]] = {}

    def collect(stat: str, lines: List[Line]):
        for t, f in lines:
            if f and not t.startswith("="):
                note = f"{stat}: {t}"
                if note not in out.setdefault(f, []):
                    out[f].append(note)

    for a in E.ABILITIES:
        collect(E.ABILITY_NAMES[a], ability(char, a))
        collect(f"{E.ABILITY_NAMES[a]} save", save(char, a))
    for s in SKILLS:
        collect(s, skill(char, s))
    collect("Armor Class", armor_class(char))
    collect("Initiative", initiative(char))
    collect("Speed", speed(char))
    collect("Hit points", hit_points(char))
    collect("Passive Perception", passive_perception(char))
    return out


def origin(feature: dict) -> str:
    """'Class: Wizard (PHB) - gained at level 2'."""
    where = feature["source"] + (f" ({feature['book']})" if feature.get("book") else "")
    if feature.get("level", 0) > 1:
        where += f" - gained at level {feature['level']}"
    return where


def feature_tip(char: Character, feature: dict, effect_map: Optional[Dict[str, List[str]]] = None) -> str:
    effect_map = effect_map if effect_map is not None else effects(char)
    lines = [feature["name"], f"Source: {origin(feature)}"]
    changes = effect_map.get(feature["name"], [])
    if changes:
        lines.append("Affects:")
        lines += [f"  • {c}" for c in changes]
    return "\n".join(lines)


# ---------------------------------------------------------------------- where each proficiency comes from
PROFICIENCY_KINDS = (("armor", "Armor"), ("weapons", "Weapons"), ("tools", "Tools"), ("languages", "Languages"))


def proficiency_origins(char: Character) -> Dict[str, Dict[str, str]]:
    """{kind: {proficiency: 'race: Dwarf, class: Fighter'}} for armor, weapons, tools and languages.

    The character keeps only the lists, so the origin is worked out from the race, background, classes,
    subclasses and feats that grant each one; what none of them grants was chosen (at creation or level-up)
    or added by hand on the sheet."""
    from .leveling import SUBCLASS_GRANTS
    low = lambda xs: {f for x in xs if isinstance(x, str) for f in (x.lower(), x.lower()[:-1] if x.lower().endswith("s") else x.lower())}  # 'daggers' grants 'dagger'
    grants: List[Tuple[str, Dict[str, set]]] = []
    race = rules.races.get(char.race) if char.race else None
    if race:
        sub = next((s for s in race["subraces"] if s["name"] == char.d.get("subrace")), None)
        g = {"armor": set(), "weapons": set(), "tools": set(), "languages": set()}
        for src in (race, sub or {}):
            g["armor"] |= low(src.get("armor", []))
            g["weapons"] |= low(src.get("weapons", []))
            g["tools"] |= low((src.get("tools") or {}).get("fixed", []))
            g["languages"] |= low((src.get("languages") or {}).get("fixed", []))
        grants.append((f"race: {char.race_display}", g))
    bg = rules.backgrounds.get(char.background) if char.background else None
    if bg:
        grants.append((f"background: {bg['name']}", {"tools": low((bg.get("tools") or {}).get("fixed", [])),
                                                     "languages": low((bg.get("languages") or {}).get("fixed", []))}))
    for i, c in enumerate(char.classes):
        cls = rules.classes.get(c["name"])
        if cls:
            src = cls if i == 0 else cls["multiclass"].get("gained", {})
            grants.append((f"class: {c['name']}", {"armor": low(src.get("armor", [])), "weapons": low(src.get("weapons", [])),
                                                   "tools": low(cls["tools"]) if i == 0 else set()}))
        sg = SUBCLASS_GRANTS.get(c.get("subclass") or "", {})
        if sg:
            grants.append((f"subclass: {c['subclass']}", {"armor": low(sg.get("armor", [])), "weapons": low(sg.get("weapons", [])),
                                                         "tools": low(sg.get("tools", [])), "languages": low(sg.get("languages_fixed", []))}))
    for name in char.d["feats"]:
        feat = rules.feats.get(name) or {}
        grants.append((f"feat: {name}", {"armor": low(feat.get("armor") or [])}))
    manual = char.d["choices"].get("manual_profs", {})
    out: Dict[str, Dict[str, str]] = {}
    for kind, _title in PROFICIENCY_KINDS:
        out[kind] = {}
        for p in char.d["proficiencies"][kind]:
            key = p.lower()
            where = [label for label, g in grants if key in g.get(kind, set())]
            if p in manual.get(kind, []):
                where.append("added by hand")
            if not where:
                feats = [f for f, k in (("Weapon Master", "weapons"), ("Skilled", "tools")) if f in char.d["feats"] and k == kind]
                where = [f"chosen (feat: {feats[0]}, or at creation / level-up)" if feats else "chosen at creation or level-up"]
            out[kind][p] = ", ".join(where)
    return out
