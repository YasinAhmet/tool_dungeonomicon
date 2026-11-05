"""Character creation: ability scores, race, background, first class level, starting equipment."""
import copy
from typing import Dict, List, Optional

from . import engine as E
from .character import Character, SKILLS
from .data import rules
from .leveling import RulesError, _check_pick, apply_feat, apply_level_up, check_no_new_doubles

SCORE_METHODS = ("point_buy", "standard_array", "rolled", "manual")
ORIGIN_KEYS = ("race", "subrace", "ancestry", "race_choices", "background", "background_choices")   # kept as d["origin"]
EQUIPMENT_TYPES = {
    "weaponSimple": lambda i: i.get("weapon") and i.get("category") == "simple",
    "weaponMartial": lambda i: i.get("weapon") and i.get("category") == "martial",
    "weaponSimpleMelee": lambda i: i.get("weapon") and i.get("category") == "simple" and i["type"] == "M",
    "weaponMartialMelee": lambda i: i.get("weapon") and i.get("category") == "martial" and i["type"] == "M",
    "focusSpellcastingArcane": lambda i: i["type"] == "SCF" and i.get("scf_type") == "arcane",
    "focusSpellcastingHoly": lambda i: i["type"] == "SCF" and i.get("scf_type") == "holy",
    "focusSpellcastingDruidic": lambda i: i["type"] == "SCF" and i.get("scf_type") == "druid",
    "instrumentMusical": lambda i: i["type"] == "INS",
    "setGaming": lambda i: i["type"] == "GS",
    "toolArtisan": lambda i: i["type"] == "AT",
}


# ---------------------------------------------------------------- ability scores
def validate_base_scores(method: str, scores: Dict[str, int]) -> None:
    if method not in SCORE_METHODS:
        raise RulesError(f"Ability score method must be one of: {', '.join(SCORE_METHODS)}.")
    if set(scores) != set(E.ABILITIES):
        raise RulesError("Provide a score for all six abilities.")
    try:
        if method == "point_buy":
            E.validate_point_buy(scores)
        elif method == "standard_array":
            E.validate_standard_array(scores)
        elif method == "manual":                     # scores entered by hand (rolled at the table, set by the DM)
            for a, s in scores.items():
                if not 1 <= s <= 20:
                    raise ValueError(f"{E.ABILITY_NAMES[a]} must be 1-20 before racial bonuses.")
        else:
            for a, s in scores.items():
                if not 3 <= s <= 18:
                    raise ValueError(f"A rolled {E.ABILITY_NAMES[a]} score must be 3-18 (4d6 drop lowest).")
    except ValueError as e:
        raise RulesError(str(e))


# ---------------------------------------------------------------- race
def race_requirements(race_name: str, subrace: Optional[str] = None) -> dict:
    """The choices a player must make for a race/subrace combination."""
    race = rules.races[race_name]
    sub = next((s for s in race["subraces"] if s["name"] == subrace), None)
    ab = race["ability"]["choose"] or (sub["ability"]["choose"] if sub else None)
    langs = race.get("languages", {"any": 0})
    lang_any = langs["any"]
    if sub and "languages" in sub:
        lang_any = sub["languages"]["any"] + (0 if "languages" in sub["overwrite"] else lang_any)
        if "languages" in sub["overwrite"]:
            lang_any = sub["languages"]["any"]
    skills = race.get("skills", {"any": 0, "from": [], "count": 0})
    tools = race.get("tools", {"from": [], "count": 0, "any": 0})
    cantrip = _cantrip_choices(_spell_blocks(race, sub))
    return {
        "subrace_required": race["subrace_required"],
        "subraces": [s["name"] for s in race["subraces"] if s["name"] and s.get("source", race["source"]) in rules.active_sources],
        "ancestries": [a["name"] for a in race["ancestries"]],
        "ability_choose": ab, "skills_any": skills["any"] + (skills.get("count", 0) if skills.get("from") else 0) + (sub.get("skills", {}).get("any", 0) if sub else 0),
        "skills_from": [rules.skill_name(x) for x in skills.get("from") or []],
        "languages_any": lang_any, "tool": tools if tools["from"] or tools["any"] else None,
        "feats": race.get("feats", 0) + (sub.get("feats", 0) if sub else 0), "cantrip_choice": cantrip,
        "spell_ability": _spell_ability_options(_spell_blocks(race, sub)),
    }


def _known_entries(block: dict):
    """Yield (class level, entry) for every 'known spell' entry of an additionalSpells block."""
    for lvl, names in block.get("known", {}).items():
        level_req = 1 if lvl == "_" else int(lvl)
        if isinstance(names, dict):                         # {'_': [...]} or {'daily': ...}-like nesting
            names = [n for value in names.values() if isinstance(value, list) for n in value]
        for n in names:
            yield level_req, n


def _innate_entries(block: dict):
    """Yield (class level, spell name, uses text) for the innate (limited-use / at-will) spells of a block."""
    for lvl, spec in block.get("innate", {}).items():
        level_req = 1 if lvl == "_" else int(lvl)
        if isinstance(spec, list):
            for n in spec:
                if isinstance(n, str):
                    yield level_req, n, "at will"
            continue
        for kind, per in spec.items():
            if kind == "will":
                for n in per:
                    if isinstance(n, str):
                        yield level_req, n, "at will"
            elif kind in ("daily", "rest", "ritual") and isinstance(per, dict):
                suffix = "long rest" if kind == "daily" else "short rest" if kind == "rest" else "ritual"
                for count, names in per.items():
                    for n in (names if isinstance(names, list) else [names]):
                        if isinstance(n, str):
                            yield level_req, n, f"{count}/{suffix}"


def _spell_blocks(race: dict, sub: Optional[dict]) -> List[dict]:
    """The race's innate spells plus the subrace's. A lineage that has its own (a tiefling's Legacy or Variant) replaces the base
    race's, as its text says ("replaces the Infernal Legacy trait"), instead of adding to them."""
    if sub and sub["spells"]:
        return list(sub["spells"])
    return list(race["spells"])


def _cantrip_choices(blocks: List[dict]) -> int:
    """High elves, kobolds... choose a cantrip: their 'known' spells contain {'choose': ...} entries."""
    return sum(1 for block in blocks for _lvl, n in _known_entries(block) if isinstance(n, dict) and "choose" in n)


def _spell_ability_options(blocks: List[dict]) -> List[str]:
    for block in blocks:
        ab = block.get("ability")
        if isinstance(ab, dict) and ab.get("choose"):
            return list(ab["choose"])
    return []


def choose_pool(spec: str) -> List[str]:
    """'level=0|class=Wizard' -> names of the matching spells (any enabled book)."""
    parts = dict(p.split("=", 1) for p in spec.split("|") if "=" in p)
    level = int(parts["level"]) if parts.get("level", "").isdigit() else 0
    klass = parts.get("class", "Wizard")
    return [s["name"] for s in rules.class_spell_list(klass, level=level, sources=list(rules.sources))]


def _canon_language(name: str) -> str:
    for lang in rules.all_languages():
        if lang.lower() == name.lower():
            return lang
    return name.capitalize()


def tool_name(t: str) -> str:
    """'carpenter's tools' -> "Carpenter's Tools" (str.title() would give "Carpenter'S Tools")."""
    return " ".join(w[:1].upper() + w[1:] for w in t.split(" "))


def racial_fixed(race: dict, sub: Optional[dict]) -> Dict[str, int]:
    """The fixed racial ability bonuses of a race and subrace. A subrace adds to its race (Hill Dwarf: +2 CON +1 WIS),
    except where it replaces the race's scores: when the data says so (overwrite), and when the race's own bonus is
    the human +1 to everything and the subrace brings its own (Variant Human, the human Dragonmarks)."""
    base = dict(race["ability"]["fixed"])
    if sub:
        own = sub["ability"]["fixed"] or sub["ability"]["choose"]
        if "ability" in sub.get("overwrite", []) or (own and len(base) == 6):
            base = {}
        for a, n in sub["ability"]["fixed"].items():
            base[a] = base.get(a, 0) + n
    return base


def racial_languages(race: dict, sub: Optional[dict]) -> List[str]:
    """The languages a race and subrace give without a choice."""
    langs = [_canon_language(l) for l in race.get("languages", {}).get("fixed", [])]
    if sub and "languages" in sub:
        langs = [_canon_language(l) for l in sub["languages"]["fixed"]] if "languages" in sub["overwrite"] else \
            langs + [_canon_language(l) for l in sub["languages"]["fixed"] if _canon_language(l) not in langs]
    return langs


def apply_race(char: Character, race_name: str, subrace: Optional[str], ancestry: Optional[str],
               choices: dict) -> None:
    if race_name not in rules.races:
        raise RulesError(f"Unknown race '{race_name}'.")
    race = rules.races[race_name]
    req = race_requirements(race_name, subrace)
    if req["subrace_required"] and not subrace:
        raise RulesError(f"{race_name} requires a subrace: {', '.join(req['subraces'])}.")
    if subrace and subrace not in req["subraces"]:
        raise RulesError(f"'{subrace}' is not a {race_name} subrace.")
    if req["ancestries"] and ancestry not in req["ancestries"]:
        raise RulesError(f"Choose a draconic ancestry: {', '.join(req['ancestries'])}.")
    before = copy.deepcopy(char.d)
    char.d["race"], char.d["subrace"], char.d["ancestry"] = race_name, subrace, ancestry
    sub = next((s for s in race["subraces"] if s["name"] == subrace), None)
    profs = char.d["proficiencies"]

    # ability bonuses
    racial = racial_fixed(race, sub)
    pick = req["ability_choose"]
    if pick:
        picks = choices.get("ability") or []
        if len(set(picks)) != pick["count"] or any(p not in pick["from"] for p in picks):
            raise RulesError(f"Choose {pick['count']} different abilities for your racial bonus "
                             f"({', '.join(E.ABILITY_NAMES[a] for a in pick['from'])}).")
        for a in picks:
            racial[a] = racial.get(a, 0) + pick["amount"]
    char.d["abilities"]["racial"] = racial

    # languages
    langs = racial_languages(race, sub)
    extra = choices.get("languages") or []
    if len(extra) != req["languages_any"]:
        raise RulesError(f"Choose {req['languages_any']} extra language(s).")
    for l in extra:
        if l not in rules.all_languages() or l in langs:
            raise RulesError(f"'{l}' isn't a valid extra language.")
    profs["languages"] = langs + list(extra)

    # skills
    for src in (race, sub or {}):
        for s in src.get("skills", {}).get("fixed", []):
            name = rules.skill_name(s)
            if name not in profs["skills"]:
                profs["skills"].append(name)
    if req["skills_any"]:
        picks = _check_pick(choices.get("skills"), [s for s in SKILLS if s not in profs["skills"]],
                            req["skills_any"], "racial skills")
        profs["skills"] += picks
    # tools / weapons / armor
    tool = req["tool"]
    if tool and tool["from"]:
        picks = _check_pick(choices.get("tools"), tool["from"], tool["count"], "racial tool")
        profs["tools"] += [tool_name(p) for p in picks]          # "smith's tools" in the data, "Smith's Tools" on the sheet
    for src in (race, sub or {}):
        profs["weapons"] += [w for w in src.get("weapons", []) if w not in profs["weapons"]]
        profs["armor"] += [a for a in src.get("armor", []) if a not in profs["armor"]]
        profs["tools"] += [tool_name(t) for t in src.get("tools", {}).get("fixed", [])
                           if t.lower() not in {x.lower() for x in profs["tools"]}]

    # racial spells (tiefling, drow, high elf, genasi, ...)
    picks = list(choices.get("cantrips") or ([choices["cantrip"]] if choices.get("cantrip") else []))
    for block in _spell_blocks(race, sub):
        ability = block.get("ability", "cha")
        if isinstance(ability, dict):                       # e.g. Hexblood: Int, Wis or Cha
            options = ability.get("choose", ["cha"])
            ability = choices.get("spell_ability") or options[0]
            if ability not in options:
                raise RulesError(f"Choose a spellcasting ability: {', '.join(E.ABILITY_NAMES[a] for a in options)}.")
        for level_req, n in _known_entries(block):
            if isinstance(n, dict):                         # a chosen cantrip
                if not picks:
                    raise RulesError("Choose your racial cantrip.")
                cantrip = picks.pop(0)
                if cantrip not in choose_pool(n.get("choose", "level=0|class=Wizard")):
                    raise RulesError(f"'{cantrip}' isn't a valid racial cantrip choice.")
                char.d["racial_spells"].append({"name": cantrip, "level_req": level_req, "ability": ability,
                                                "source": "Race"})
            else:
                spell = rules.spell(n.split("#")[0].split("|")[0])
                if spell:
                    spell_level = spell["level"]
                    entry = {"name": spell["name"], "level_req": level_req, "ability": ability, "source": "Race"}
                    if spell_level > 0:                     # a leveled spell known via a trait is limited-use
                        entry["uses"] = "1/long rest"
                    char.d["racial_spells"].append(entry)
        for level_req, n, uses in _innate_entries(block):
            spell = rules.spell(n.split("#")[0].split("|")[0])
            if spell:
                char.d["racial_spells"].append({"name": spell["name"], "level_req": level_req, "ability": ability,
                                                "uses": uses, "source": "Race"})

    # variant human feat
    if req["feats"]:
        feat = choices.get("feat")
        if not feat:
            raise RulesError("Choose a feat for your race.")
        apply_feat(char, feat, choices.get("feat_choices"))
    check_no_new_doubles(before, char)


# ---------------------------------------------------------------- background
def background_requirements(name: str) -> dict:
    bg = rules.backgrounds[name]
    skills, langs, tools = bg.get("skills", {}), bg.get("languages", {}), bg.get("tools", {})
    return {"skills_any": skills.get("any", 0), "languages_any": langs.get("any", 0),
            "tools_from": tools.get("from", []), "tools_count": tools.get("count", 0) or tools.get("any", 0),
            "characteristics": bg["characteristics"], "equipment": bg["equipment"], "feature": bg["feature"]}


def background_tool_pool(req: dict) -> List[str]:
    """What a background's tool choice picks from: its own list, else any PHB artisan's tool, instrument or game."""
    return req["tools_from"] or sorted(i["name"] for i in rules.items.values() if i["type"] in ("AT", "INS", "GS")
                                       and not i["magic"] and i["source"] == "PHB")


def apply_background(char: Character, name: str, choices: dict) -> None:
    if name not in rules.backgrounds:
        raise RulesError(f"Unknown background '{name}'.")
    bg = rules.backgrounds[name]
    req = background_requirements(name)
    profs = char.d["proficiencies"]
    before = copy.deepcopy(char.d)
    char.d["background"] = name
    # skills: if a background proficiency duplicates one already known, the player picks another (PHB p.125)
    duplicates = 0
    for s in bg.get("skills", {}).get("fixed", []):
        skill = rules.skill_name(s)
        if skill in profs["skills"]:
            duplicates += 1
        else:
            profs["skills"].append(skill)
    wanted = req["skills_any"] + duplicates
    if wanted:
        picks = _check_pick(choices.get("skills"), [s for s in SKILLS if s not in profs["skills"]], wanted,
                            "background skills")
        profs["skills"] += picks
    for t in bg.get("tools", {}).get("fixed", []):
        if t.lower() not in {x.lower() for x in profs["tools"]}:
            profs["tools"].append(tool_name(t))
    if req["tools_count"]:
        pool = background_tool_pool(req)
        have = {t.lower() for t in profs["tools"]}
        profs["tools"] += _check_pick(choices.get("tools"), [t for t in pool if t.lower() not in have], req["tools_count"],
                                      "background tools")
    if req["languages_any"]:
        langs = [l for l in rules.all_languages() if l not in profs["languages"]]
        profs["languages"] += _check_pick(choices.get("languages"), langs, req["languages_any"],
                                          "background languages")
    check_no_new_doubles(before, char)


# ---------------------------------------------------------------- equipment
def _resolve_item_name(name: str) -> str:
    item = rules.item(name)
    return item["name"] if item else name


def _give(char: Character, name: str, qty: int = 1) -> None:
    item = rules.item(name)
    if item and item.get("pack"):                      # packs unpack into their contents
        for ref in item["pack"]:
            if isinstance(ref, dict) and "item" in ref:
                _give(char, ref["item"].split("|")[0], ref.get("quantity", 1) * qty)
            elif isinstance(ref, dict):                   # {'special': 'little bag of sand', 'quantity': 1}
                char.add_item(str(ref.get("special", "Item")).capitalize(), ref.get("quantity", 1) * qty)
            else:
                _give(char, ref.split("|")[0], qty)
        return
    char.add_item(_resolve_item_name(name), qty)


def equipment_choices(class_name: str, background: Optional[str]) -> dict:
    """Starting-equipment options a player chooses between: {'class': [group...], 'background': [...], 'gold': '5d4 × 10'}."""
    cls = rules.classes[class_name]
    return {"class": cls["equipment"]["choices"], "text": cls["equipment"]["text"],
            "gold": cls["equipment"]["gold_alternative"],
            "background": rules.backgrounds[background]["equipment"] if background else []}


def type_options(type_key: str) -> List[str]:
    test = EQUIPMENT_TYPES[type_key]
    return sorted(i["name"] for i in rules.items.values() if i["source"] == "PHB" and not i["magic"] and test(i))


def _grant_group(char: Character, group: dict, pick: dict) -> None:
    option = pick.get("option", "a")
    items = group["fixed"] if "fixed" in group else group.get(option)
    if items is None:
        raise RulesError(f"Equipment option '{option}' doesn't exist.")
    picks = list(pick.get("picks", []))
    for it in items:
        qty = it.get("qty", 1) if isinstance(it, dict) else 1
        if "type" in it:                              # "any martial weapon": the player names one
            if not picks:
                raise RulesError("Choose a weapon/tool for each 'any ...' equipment option.")
            name = picks.pop(0)
            if name not in type_options(it["type"]):
                raise RulesError(f"'{name}' isn't a valid choice here.")
            _give(char, name, qty)
        elif "item" in it:
            _give(char, it["item"], qty)
            if it.get("contains_gp"):
                char.currency["gp"] += int(it["contains_gp"])
        elif "special" in it:
            char.add_item(it["special"].capitalize(), qty)
        elif "gp" in it:
            char.currency["gp"] += int(it["gp"])


def apply_equipment(char: Character, class_name: str, background: str, spec: dict) -> None:
    """spec: {'gold': int|None, 'class': [{'option': 'a', 'picks': [...]}...], 'background': [...]}."""
    gold = spec.get("gold")
    if gold is not None:
        if not isinstance(gold, int) or gold < 0:
            raise RulesError("Starting gold must be a non-negative whole number.")
        char.currency["gp"] += gold
    else:
        groups = rules.classes[class_name]["equipment"]["choices"]
        picks = spec.get("class") or []
        if len(picks) != len(groups):
            raise RulesError(f"Choose an option for each of the {len(groups)} equipment groups.")
        for group, pick in zip(groups, picks):
            _grant_group(char, group, pick)
        bg_groups = rules.backgrounds[background]["equipment"]
        bg_picks = spec.get("background") or []
        for i, group in enumerate(bg_groups):
            _grant_group(char, group, bg_picks[i] if i < len(bg_picks) else {"option": "a"})
    auto_equip(char)


def auto_equip(char: Character) -> None:
    """Wear the best armor and a shield, wield the first melee and ranged weapons."""
    armors = [(e, rules.item(e["name"])) for e in char.inventory if rules.item(e["name"])]
    body = [(e, d) for e, d in armors if d["type"] in ("LA", "MA", "HA") and not d["magic"]]
    if body:
        best = max(body, key=lambda x: x[1]["ac"])
        best[0]["equipped"] = True
    shields = [(e, d) for e, d in armors if d["type"] == "S"]
    if shields:
        shields[0][0]["equipped"] = True
    melee = [(e, d) for e, d in armors if d.get("weapon") and d["type"] == "M"]
    ranged = [(e, d) for e, d in armors if d.get("weapon") and d["type"] == "R"]
    for group in (melee, ranged):
        if group:
            group[0][0]["equipped"] = True


# ---------------------------------------------------------------- the whole thing
def create_character(spec: dict, sources=None) -> Character:
    """Build a level 1 character.

    spec keys: name, alignment, race, subrace, ancestry, race_choices, background, background_choices,
    scores_method, scores, class, class_choices (see apply_level_up), equipment, details.
    Raises RulesError for anything that breaks the rules.
    """
    name = (spec.get("name") or "").strip()
    if not name:
        raise RulesError("Give the character a name.")
    char = Character.create_blank(name)
    char.d["sources"] = list(sources or rules.active_sources)
    validate_base_scores(spec.get("scores_method", ""), spec.get("scores", {}))
    char.d["abilities"]["base"] = {a: int(spec["scores"][a]) for a in E.ABILITIES}
    char.d["ability_method"] = spec["scores_method"]
    if spec.get("alignment") and spec["alignment"] not in E.ALIGNMENTS:
        raise RulesError("Pick an alignment from the list.")
    char.d["alignment"] = spec.get("alignment", "")
    apply_race(char, spec.get("race"), spec.get("subrace"), spec.get("ancestry"), spec.get("race_choices", {}))
    apply_background(char, spec.get("background"), spec.get("background_choices", {}))
    class_name = spec.get("class")
    apply_level_up(char, class_name, spec.get("class_choices", {}), sources)
    apply_equipment(char, class_name, spec["background"], spec.get("equipment", {}))
    char.details.update({k: v for k, v in (spec.get("details") or {}).items() if k in char.details})
    char.d["origin"] = {k: copy.deepcopy(spec.get(k)) for k in ORIGIN_KEYS}    # so the choices can be edited later
    char.current_hp = char.max_hp
    return char
