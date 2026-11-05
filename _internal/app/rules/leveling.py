"""Leveling: plan what a level-up requires, validate the player's choices, apply them.

Creating a character is just the first level-up (character.total_level == 0), so the same
code enforces proficiencies, HP, subclass, ASI/feat, expertise, optional features
(fighting styles, invocations, metamagic, maneuvers...) and spell choices at every level.
"""
import copy
from typing import Dict, Iterable, List, Optional

from . import engine as E
from .character import Character, SKILLS
from .data import rules
from . import feat_extras as FE
from . import spellcasting as SC

ASI_NAME = "Ability Score Improvement"
BARD_MAGIC_SECRETS_LEVELS = (10, 14, 18)

# Proficiencies and extras granted when a subclass is chosen. The rules data only has these as prose, so
# they are listed here (PHB). 'skills'/'languages'/'cantrip'/'tools_any' need a player choice.
SUBCLASS_GRANTS = {
    "Life Domain": {"armor": ["heavy"]},
    "War Domain": {"armor": ["heavy"], "weapons": ["martial"]},
    "Tempest Domain": {"armor": ["heavy"], "weapons": ["martial"]},
    "Nature Domain": {"armor": ["heavy"], "skills": {"count": 1, "from": ["Animal Handling", "Nature", "Survival"]},
                      "cantrip": {"class": "Druid", "count": 1}},
    "Knowledge Domain": {"languages": 2,
                         "expertise_skills": {"count": 2, "from": ["Arcana", "History", "Nature", "Religion"]}},
    "Light Domain": {"cantrip_fixed": ["Light"]},
    "Circle of the Land": {"cantrip": {"class": "Druid", "count": 1}},
    "College of Valor": {"armor": ["medium", "shield"], "weapons": ["martial"]},
    "College of Lore": {"skills": {"count": 3, "from": None}},
    "Assassin": {"tools": ["Disguise Kit", "Poisoner's Kit"]},
    "Draconic Bloodline": {"languages_fixed": ["Draconic"]},
    "Battle Master": {"tools_any": {"count": 1, "types": ["AT"]}},
    # the fixed grants of the later books (the ones that offer a choice of skill, weapon or tool are not listed)
    "Armorer": {"armor": ["heavy"], "tools": ["Smith's Tools"]},
    "Battle Smith": {"weapons": ["martial"], "tools": ["Smith's Tools"]},
    "Alchemist": {"tools": ["Alchemist's Supplies"]},
    "Reanimator": {"tools": ["Alchemist's Supplies"]},
    "Cartographer": {"tools": ["Calligrapher's Supplies", "Cartographer's Tools"]},
    "Artillerist": {"tools": ["Woodcarver's Tools"]},
    "College of Swords": {"armor": ["medium"], "weapons": ["scimitars"]},
    "College of Spirits": {"cantrip_fixed": ["Guidance"]},
    "Death Domain": {"weapons": ["martial"]},
    "Arcana Domain": {"cantrip": {"class": "Wizard", "count": 2}},
    "Forge Domain": {"armor": ["heavy"], "tools": ["Smith's Tools"]},
    "Grave Domain": {"cantrip_fixed": ["Spare the Dying"]},
    "Order Domain": {"armor": ["heavy"], "skills": {"count": 1, "from": ["Intimidation", "Persuasion"]}},
    "Peace Domain": {"skills": {"count": 1, "from": ["Insight", "Performance", "Persuasion"]}},
    "Fey Wanderer": {"skills": {"count": 1, "from": ["Deception", "Performance", "Persuasion"]}},
    "Samurai": {"skills": {"count": 1, "from": ["History", "Insight", "Performance", "Persuasion"]}},       # (or a language: not offered)
    "Cavalier": {"skills": {"count": 1, "from": ["Animal Handling", "History", "Insight", "Performance", "Persuasion"]}},
    "Scout": {"expertise_fixed": ["Nature", "Survival"]},
    # one weapon type per pick: {'type': 'M' / 'R', 'exclude': properties it may not have, 'allow': names that count anyway}
    "Way of the Kensei": {"weapon_picks": {"kensei_melee": {"type": "M", "exclude": ["heavy", "special"]},
                                           "kensei_ranged": {"type": "R", "exclude": ["heavy", "special"], "allow": ["Longbow"]}}},
    "Twilight Domain": {"armor": ["heavy"], "weapons": ["martial"]},
    "Circle of Spores": {"cantrip_fixed": ["Chill Touch"]},
    "Rune Knight": {"tools": ["Smith's Tools"], "languages_fixed": ["Giant"]},
    "Way of Mercy": {"tools": ["Herbalism Kit"], "skills_fixed": ["Insight", "Medicine"]},
    "Way of the Drunken Master": {"tools": ["Brewer's Supplies"]},
    "Swarmkeeper": {"cantrip_fixed": ["Mage Hand"]},
    "Drakewarden": {"cantrip_fixed": ["Thaumaturgy"]},
    "Mastermind": {"tools": ["Disguise Kit", "Forgery Kit"]},
    "The Undying": {"cantrip_fixed": ["Spare the Dying"]},
    "The Hexblade": {"armor": ["medium", "shield"], "weapons": ["martial"]},
    "School of Illusion": {"cantrip_fixed": ["Minor Illusion"]},
    "Bladesinging": {"armor": ["light"], "skills_fixed": ["Performance"],
                     "weapon_picks": {"bladesinging_weapon": {"type": "M", "exclude": ["two-handed"]}}},
    "Circle of Stars": {"cantrip_fixed": ["Guidance"]},
}


class RulesError(ValueError):
    """The requested choice breaks a D&D rule. The message explains which."""


# ---------------------------------------------------------------- one pick, one source
def taken_spells(char: Character) -> set:
    """Every spell the character has learned from any source (all classes' cantrips, known spells and spellbooks,
    bonus cantrips, racial and feat spells), lowercased. Choices never offer these again."""
    out = {n.lower() for sp in char.d["spells"].values() for k in ("cantrips", "known", "spellbook") for n in sp.get(k, [])}
    out |= {n.lower() for names in char.d["choices"].get("bonus_cantrips", {}).values() for n in names}
    return out | {r["name"].lower() for r in char.d["racial_spells"]}


def _holdings(d: dict) -> Dict[tuple, List[str]]:
    """Proficiencies and learned spells of a character dict, {(kind, lowercased name): [names as written]}: more than
    one entry is something picked twice. Racial/feat spells count once per source (a race listing a spell both as
    known and innate is no double)."""
    out: Dict[tuple, List[str]] = {}
    profs = d.get("proficiencies", {})
    names = [(kind, x) for kind in ("skills", "tools", "languages", "expertise") for x in profs.get(kind, [])]
    names += [("spells", n) for sp in d.get("spells", {}).values() for k in ("cantrips", "known", "spellbook") for n in sp.get(k, [])]
    names += [("spells", n) for v in d.get("choices", {}).get("bonus_cantrips", {}).values() for n in v]
    names += [("spells", n) for _src, n in {(r.get("source"), r["name"]) for r in d.get("racial_spells", [])
                                            if not (r.get("slots") or r.get("slot_req") or r.get("ritual"))}]     # an always-prepared feat spell may repeat a class spell
    for kind, n in names:
        out.setdefault((kind, n.lower()), []).append(n)
    return out


def check_no_new_doubles(before: dict, char: Character) -> None:
    """Raise when a change gave the character something it already had (the same skill from race and background, the
    same cantrip from a class and a feat...). Doubles the character already carried are left alone."""
    old = _holdings(before)
    for (kind, key), names in _holdings(char.d).items():
        if len(names) > max(1, len(old.get((kind, key), []))):
            what = {"skills": "are already proficient in", "tools": "are already proficient with", "languages": "already speak",
                    "expertise": "already have expertise in", "spells": "already know"}[kind]
            raise RulesError(f"You {what} {names[0]}: it was picked twice. Choose something else.")


# ---------------------------------------------------------------- helpers
def _lower_set(values: Iterable[str]) -> set:
    return {v.lower() for v in values}


def meets_requirements(req: dict, scores: Dict[str, int]) -> bool:
    """Multiclass ability prerequisites: {'str': 13} (all) or {'or': [{'str': 13, 'dex': 13}]} (any)."""
    for key, value in req.items():
        if key == "or":
            if not any(any(scores[a] >= n for a, n in alt.items()) for alt in value):
                return False
        elif scores[key] < value:
            return False
    return True


def describe_requirements(req: dict) -> str:
    parts = []
    for key, value in req.items():
        if key == "or":
            parts.append(" or ".join(f"{E.ABILITY_NAMES[a]} {n}" for alt in value for a, n in alt.items()))
        else:
            parts.append(f"{E.ABILITY_NAMES[key]} {value}")
    return ", ".join(parts)


def check_multiclass(char: Character, class_name: str) -> None:
    """PHB: you must meet the prerequisites of your current classes and of the new one."""
    scores = char.ability_scores()
    for name in [c["name"] for c in char.classes] + [class_name]:
        req = rules.classes[name]["multiclass"]["requirements"]
        if not meets_requirements(req, scores):
            raise RulesError(f"Multiclassing requires {describe_requirements(req)} for {name}.")


def option_total(progression, level: int) -> int:
    """Total options known at `level` from a progression ({'3': 2, '10': 3} or a 20-entry list)."""
    if level <= 0:
        return 0
    if isinstance(progression, list):
        return progression[level - 1]
    best = 0
    for lvl, count in progression.items():
        if int(lvl) <= level:
            best = max(best, count)
    return best


def tool_choice_spec(raw: List[dict]) -> dict:
    """Class/background tool proficiency data -> {'fixed': [...], 'count': n, 'from': [names]}."""
    fixed, groups = [], []
    for entry in raw or []:
        for key, value in entry.items():
            if value is True:
                fixed.append(key)
            elif key == "anyMusicalInstrument":
                groups.append(("INS", value))
            elif key == "anyArtisansTool":
                groups.append(("AT", value))
    if not groups:
        return {"fixed": fixed, "count": 0, "from": []}
    if len(groups) > 1 or (len(raw or []) > 1):   # monk: one artisan's tool OR one instrument
        count = 1
    else:
        count = groups[0][1]
    types = {t for t, _n in groups}
    pool = sorted(i["name"] for i in rules.items.values() if i["type"] in types and not i["magic"]
                  and i["source"] == "PHB")
    return {"fixed": fixed, "count": count, "from": pool}


def asi_levels(class_name: str) -> List[int]:
    return [f["level"] for f in rules.classes[class_name]["features"] if f["name"] == ASI_NAME]


def subclass_options(class_name: str, sources=None) -> List[dict]:
    sources = rules._src(sources)
    return [s for s in rules.subclasses_of(class_name) if s["source"] in sources]


def ordered_options(groups: dict) -> List[str]:
    return [name for names in groups.values() for name in names]


# ---------------------------------------------------------------- feats
def feat_prereq_status(char: Character, feat: dict) -> Optional[str]:
    """None if the character qualifies for the feat, else the reason they don't."""
    scores = char.ability_scores()
    for req in feat["prerequisite"]:
        if "ability" in req and not any(all(scores[a] >= n for a, n in opt.items()) for opt in req["ability"]):
            need = " or ".join(", ".join(f"{E.ABILITY_NAMES[a]} {n}" for a, n in opt.items()) for opt in req["ability"])
            return f"Requires {need}."
        if "race" in req and char.race not in req["race"]:
            return f"Requires race: {', '.join(req['race'])}."
        if "level" in req and char.total_level < req["level"]:
            return f"Requires level {req['level']}."
        if "proficiency" in req:
            for prof in req["proficiency"]:
                if "armor" in prof and prof["armor"] not in char.d["proficiencies"]["armor"]:
                    return f"Requires {prof['armor']} armor proficiency."
                if prof.get("weaponGroup") and prof["weaponGroup"] not in char.d["proficiencies"]["weapons"]:
                    return f"Requires proficiency with {prof['weaponGroup']} weapons."
        if req.get("spellcasting") and not SC.casters(char) and not char.d["racial_spells"]:
            return "Requires the ability to cast at least one spell."
        if (req.get("spellcasting2020") or req.get("spellcastingFeature")) and not SC.casters(char):            # 2024 wording: the Spellcasting or Pact Magic feature
            return "Requires the Spellcasting or Pact Magic feature."
        if req.get("feature") and not any(char.has_feature(n) for n in req["feature"]):
            return f"Requires the {' or '.join(req['feature'])} feature."
    return None


def apply_feat(char: Character, name: str, choices: Optional[dict] = None) -> None:
    """Add a feat and its mechanical benefits (ability bonus, proficiencies, spells)."""
    choices = choices or {}
    feat = rules.feats.get(name)
    if not feat:
        raise RulesError(f"Unknown feat '{name}'.")
    if name in char.d["feats"]:
        raise RulesError(f"You already have {name}.")
    reason = feat_prereq_status(char, feat)
    if reason:
        raise RulesError(f"{name}: {reason}")
    ab = feat["ability"]
    feat_bonus = char.d["abilities"]["feat"]
    for a, n in ab["fixed"].items():
        feat_bonus[a] = feat_bonus.get(a, 0) + n
    if ab["choose"]:
        pick = choices.get("ability")
        if pick not in ab["choose"]["from"]:
            raise RulesError(f"{name}: choose one of {', '.join(E.ABILITY_NAMES[a] for a in ab['choose']['from'])}.")
        feat_bonus[pick] = feat_bonus.get(pick, 0) + ab["choose"]["amount"]
    profs = char.d["proficiencies"]
    for kind in ("armor",):
        for p in feat.get(kind, []):
            if p not in profs[kind]:
                profs[kind].append(p)
    if name == "Resilient":
        if choices["ability"] not in profs["saves"]:
            profs["saves"].append(choices["ability"])
        else:
            raise RulesError("You are already proficient in that saving throw.")
    elif name == "Skilled":
        picks = choices.get("proficiencies", [])
        if len(picks) != 3:
            raise RulesError("Skilled: choose exactly three skills or tools.")
        for p in picks:
            if p in profs["skills"] or p in profs["tools"]:
                raise RulesError(f"You are already proficient with {p}.")
            (profs["skills"] if p in SKILLS else profs["tools"]).append(p)
    elif name == "Weapon Master":
        picks = choices.get("weapons", [])
        if len(picks) != 4:
            raise RulesError("Weapon Master: choose four weapons.")
        profs["weapons"] += [w for w in picks if w not in profs["weapons"]]
    elif name == "Magic Initiate":
        cls = choices.get("class")
        if cls not in ("Bard", "Cleric", "Druid", "Sorcerer", "Warlock", "Wizard"):
            raise RulesError("Magic Initiate: choose a class.")
        cantrips, spell = choices.get("cantrips", []), choices.get("spell")
        pool = rules.class_spell_list(cls)
        if len(cantrips) != 2 or not spell or any(c not in [s["name"] for s in pool if s["level"] == 0] for c in cantrips) \
                or spell not in [s["name"] for s in pool if s["level"] == 1]:
            raise RulesError("Magic Initiate: choose two cantrips and one 1st-level spell from that class's list.")
        ability = {"Bard": "cha", "Cleric": "wis", "Druid": "wis", "Sorcerer": "cha", "Warlock": "cha",
                   "Wizard": "int"}[cls]
        for c in cantrips:
            char.d["racial_spells"].append({"name": c, "level_req": 1, "ability": ability, "source": "Magic Initiate"})
        char.d["racial_spells"].append({"name": spell, "level_req": 1, "ability": ability, "uses": "1/long rest",
                                        "source": "Magic Initiate"})
    elif name == "Elemental Adept":
        if choices.get("damage") not in ("acid", "cold", "fire", "lightning", "thunder"):
            raise RulesError("Elemental Adept: choose acid, cold, fire, lightning or thunder.")
        char.d["choices"]["elemental_adept"] = choices["damage"]
    FE.apply(char, name, choices)                       # Fey Touched's spells, Fighting Initiate's style, Metamagic Adept's picks... (feat_extras.py)
    char.d["feats"].append(name)


# ---------------------------------------------------------------- optional features (styles, invocations...)
def option_prereq_ok(char: Character, option: dict, class_name: str, level: int) -> bool:
    for req in option["prerequisite"]:
        if "level" in req and level < req["level"]:
            return False
        if "pact" in req and f"Pact of the {req['pact']}" not in char.d["options"]:
            return False
        if "spell" in req:
            known = {s.lower() for info in SC.casters(char) for s in
                     SC.class_spells(char, info["class"])["cantrips"] + SC.class_spells(char, info["class"])["known"]}
            for needed in req["spell"]:
                if needed.split("#")[0].lower() not in known:
                    return False
    return True


def option_groups(char: Character, class_name: str, level: int, subclass: Optional[str]) -> List[dict]:
    """Optional-feature groups available to a class at a level: [{'key','name','types','total'}]."""
    cls = rules.classes[class_name]
    groups = [{"key": f"{class_name}:{p['name']}", "name": p["name"], "types": p["types"],
               "total": option_total(p["progression"], level)} for p in cls["optional_progression"]]
    sub = rules.subclass(class_name, subclass) if subclass else None
    for p in (sub["optional_progression"] if sub else []):
        groups.append({"key": f"{subclass}:{p['name']}", "name": p["name"], "types": p["types"],
                       "total": option_total(p["progression"], level)})
    return groups


def option_pool(char: Character, group: dict, class_name: str, level: int) -> List[dict]:
    chosen = set(char.d["options"])
    return [o for o in rules.option_list(char.sources)
            if set(o["types"]) & set(group["types"]) and o["name"] not in chosen
            and option_prereq_ok(char, o, class_name, level)]


# ---------------------------------------------------------------- planning
def _hypothetical(char: Character, class_name: str, subclass: Optional[str]) -> Character:
    """A copy of the character one level higher in `class_name` (used to read the new class tables)."""
    clone = Character.from_dict(char.d)
    entry = clone.class_entry(class_name)
    if not entry:
        entry = {"name": class_name, "level": 0, "subclass": None}
        clone.classes.append(entry)
    entry["level"] += 1
    if subclass and not entry.get("subclass"):
        entry["subclass"] = subclass
    return clone


def plan_level_up(char: Character, class_name: str, subclass: Optional[str] = None,
                  sources=None) -> dict:
    """Everything the player must decide to gain a level in `class_name`."""
    sources = sources or char.sources
    if class_name not in rules.classes:
        if char.class_entry(class_name):
            raise RulesError(f"{class_name}: its book isn't installed (see the Installations window).")
        raise RulesError(f"Unknown class '{class_name}'.")
    if char.total_level >= E.MAX_LEVEL:
        raise RulesError("Characters cannot go beyond level 20.")
    cls = rules.classes[class_name]
    existing = char.class_entry(class_name)
    first_ever = not char.classes
    new_class = existing is None
    if new_class and not first_ever:
        check_multiclass(char, class_name)
    level = (existing["level"] if existing else 0) + 1
    current_sub = existing["subclass"] if existing else None
    sub_level = cls["subclass_levels"][0] if cls["subclass_levels"] else None
    needs_subclass = bool(sub_level and level >= sub_level and not current_sub)
    chosen_sub = current_sub or subclass
    after = _hypothetical(char, class_name, subclass)
    entry_after = after.class_entry(class_name)

    plan = {
        "class": class_name, "level": level, "total_level": char.total_level + 1, "first_ever": first_ever,
        "new_class": new_class, "hit_die": cls["hit_die"],
        "hp": {"first_level_max": cls["hit_die"] if first_ever else None, "average": E.average_hp(cls["hit_die"])},
        "subclass": {"title": cls["subclass_title"], "options": [s["name"] for s in subclass_options(class_name, sources)]}
        if needs_subclass else None,
        "features": [f for f in cls["features"] if f["level"] == level]
        + ([f for f in rules.subclass(class_name, chosen_sub)["features"] if f["level"] == level]
           if chosen_sub and rules.subclass(class_name, chosen_sub) else []),
        "asi": level in asi_levels(class_name),
        "skills": None, "tools": None, "expertise": None, "options": [], "spells": None,
    }

    # proficiencies/extras that come with the chosen subclass
    plan["subclass_grants"] = None
    if needs_subclass and subclass in SUBCLASS_GRANTS:
        g = SUBCLASS_GRANTS[subclass]
        need = {}
        if g.get("skills"):
            have = char.d["proficiencies"]["skills"]
            need["skills"] = {"count": g["skills"]["count"],
                              "from": [x for x in (g["skills"]["from"] or SKILLS) if x not in have]}
        if g.get("expertise_skills"):
            ex = g["expertise_skills"]
            need["expertise_skills"] = {**ex, "from": [x for x in ex["from"] if x not in char.d["proficiencies"]["expertise"]]}
        if g.get("languages"):
            need["languages"] = {"count": g["languages"],
                                 "from": [l for l in rules.all_languages() if l not in char.d["proficiencies"]["languages"]]}
        if g.get("cantrip"):
            cur = taken_spells(char)
            need["cantrip"] = {"count": g["cantrip"]["count"], "from": [s["name"] for s in
                                                                       rules.class_spell_list(g["cantrip"]["class"], level=0)
                                                                       if s["name"].lower() not in cur]}
        if g.get("tools_any"):
            have = _lower_set(char.d["proficiencies"]["tools"])
            need["tools"] = {"count": g["tools_any"]["count"], "from": sorted(
                i["name"] for i in rules.items.values() if i["type"] in g["tools_any"]["types"] and not i["magic"]
                and i["source"] == "PHB" and i["name"].lower() not in have)}
        for key, spec in (g.get("weapon_picks") or {}).items():      # a kensei's two weapons, a bladesinger's one-handed melee weapon
            need[key] = {"count": 1, "from": weapon_choices(spec)}
        plan["subclass_grants"] = need or None

    # starting / multiclass proficiencies
    if first_ever:
        plan["skills"] = {"from": [rules.skill_name(s) for s in cls["skills"]["choose"]] or list(SKILLS),
                          "count": cls["skills"]["count"]}
        plan["tools"] = tool_choice_spec(cls["tool_choice"])
    elif new_class:
        gained = cls["multiclass"]["gained"]
        for s in gained.get("skills", []):
            if "choose" in s:
                plan["skills"] = {"from": [rules.skill_name(x) for x in s["choose"]["from"]],
                                  "count": s["choose"]["count"]}
        if gained.get("toolProficiencies"):
            plan["tools"] = tool_choice_spec(gained["toolProficiencies"])
    if plan["skills"]:
        plan["skills"]["from"] = [s for s in plan["skills"]["from"] if s not in char.d["proficiencies"]["skills"]]
    if plan["tools"]:
        have = _lower_set(char.d["proficiencies"]["tools"])
        plan["tools"]["from"] = [t for t in plan["tools"]["from"] if t.lower() not in have]

    # expertise
    if any(f["name"] == "Expertise" and f["level"] == level for f in cls["features"]):
        options = [s for s in char.d["proficiencies"]["skills"] if s not in char.d["proficiencies"]["expertise"]]
        rogue_tools = cls["name"] == "Rogue" and thieves_tools_open(char.d["proficiencies"])
        room = len(options) + (plan["skills"]["count"] if plan["skills"] else 0) + (1 if rogue_tools else 0)
        plan["expertise"] = {"count": min(2, room), "from": options, "tools": cls["name"] == "Rogue"}   # fewer when fewer qualify

    # optional features: fighting style, invocations, metamagic, maneuvers, pact boon
    groups_state = char.d["choices"].setdefault("groups", {})
    for g in option_groups(after, class_name, level, chosen_sub):
        have = len(groups_state.get(g["key"], []))
        need = g["total"] - have
        if need > 0:
            plan["options"].append({"key": g["key"], "name": g["name"], "count": need,
                                    "pool": [o["name"] for o in option_pool(after, g, class_name, level)]})

    # spells
    info = SC.spellcasting_info(after, entry_after)
    if info:
        sp = SC.class_spells(char, class_name)
        spells = {"class": class_name, "ability": info["ability"], "max_spell_level": info["max_spell_level"],
                  "cantrips": max(0, info["cantrips"] - len(sp["cantrips"])), "known": None, "spellbook": None,
                  "prepared": info["prepared"], "swap": False, "slots": info["slots"], "pact": info["pact"],
                  "magic_secrets": 2 if class_name == "Bard" and level in BARD_MAGIC_SECRETS_LEVELS else 0,
                  "restricted_schools": info["restricted_schools"], "always_prepared": SC.always_prepared(after, class_name)}
        if info["known"] is not None:
            spells["known"] = max(0, info["known"] - len(sp["known"]))
            spells["swap"] = bool(sp["known"])
        if info["spellbook"]:
            copied = set(char.d["choices"].get("copied_spells") or [])      # copied from scrolls: not the level's free picks
            spells["spellbook"] = max(0, info["spellbook_size"] - len([s for s in sp["spellbook"] if s not in copied]))
        # nothing learned from another class, the race, a feat or the subclass is offered again; a class that only
        # prepares keeps its whole list (preparing isn't learning)
        taken = taken_spells(char) | {n.lower() for n in (SUBCLASS_GRANTS.get(subclass) or {}).get("cantrip_fixed", [])
                                      if needs_subclass}
        learning = info["known"] is not None or info["spellbook"]
        spells["cantrip_pool"] = [s["name"] for s in SC.eligible_spells(after, info, cantrips=True)
                                  if s["name"].lower() not in taken]
        spells["spell_pool"] = [s["name"] for s in SC.eligible_spells(after, info)
                                if (s["name"].lower() not in taken if learning
                                    else s["name"] not in sp["known"] + sp["spellbook"])]
        if spells["magic_secrets"]:
            spells["any_class_pool"] = sorted(s["name"] for s in rules.offered(rules.spells.values())
                                              if 1 <= s["level"] <= info["max_spell_level"]
                                              and s["name"].lower() not in taken)
        plan["spells"] = spells if any([spells["cantrips"], spells["known"], spells["spellbook"],
                                        spells["prepared"] is not None]) else None
    return plan


# ---------------------------------------------------------------- applying
def _check_pick(chosen: List[str], pool: Iterable[str], count: int, what: str) -> List[str]:
    chosen = list(chosen or [])
    if len(chosen) != count:
        raise RulesError(f"Choose exactly {count} {what} (you chose {len(chosen)}).")
    if len(set(c.lower() for c in chosen)) != len(chosen):
        raise RulesError(f"Duplicate choice in {what}.")
    low = _lower_set(pool)
    bad = [c for c in chosen if c.lower() not in low]
    if bad:
        raise RulesError(f"Not a valid choice for {what}: {', '.join(bad)}.")
    return chosen


def fit_prepared(char: Character, class_name: str, choices: Optional[dict]) -> Optional[dict]:
    """Recorded level choices with the prepared list cut to what this level allows the character now: replayed on new
    creation choices a lower casting score prepares fewer. Preparing is a daily choice, not one worth asking again."""
    if not choices or choices.get("prepared") is None:
        return choices
    try:
        sp = plan_level_up(char, class_name, choices.get("subclass"))["spells"]
    except RulesError:
        return choices
    if not sp or sp["prepared"] is None:
        return choices
    always = set(sp.get("always_prepared") or [])
    keep = [n for n in choices["prepared"] if n not in always][: sp["prepared"]]
    return choices if len(keep) == len(choices["prepared"]) else dict(choices, prepared=keep)


def apply_level_up(char: Character, class_name: str, choices: Optional[dict] = None,
                   sources=None) -> dict:
    """Validate `choices` against the plan and apply the level. All-or-nothing: the character is
    restored if any choice is invalid. Returns the plan that was applied.

    choices keys: hp ('average' | 'roll' | int), subclass, skills, tools, asi ({'abilities': {'str': 2}} or
    {'feat': name, 'feat_choices': {...}}), expertise, options ({group key: [names]}), cantrips, spells,
    spellbook, swap ({'remove': name, 'add': name}), prepared, magic_secrets.
    """
    choices = choices or {}
    snapshot = copy.deepcopy(char.d)
    try:
        plan = _apply(char, class_name, choices, sources)
        check_no_new_doubles(snapshot, char)
        return plan
    except Exception:
        char.d.clear()
        char.d.update(snapshot)
        raise


def _apply(char: Character, class_name: str, choices: dict, sources) -> dict:
    plan = plan_level_up(char, class_name, choices.get("subclass"), sources)
    cls = rules.classes[class_name]
    profs = char.d["proficiencies"]
    old_max = char.max_hp if char.is_created else 0

    entry = char.class_entry(class_name)
    if not entry:
        entry = {"name": class_name, "level": 0, "subclass": None}
        char.classes.append(entry)
    entry["level"] += 1

    # hit points
    if plan["first_ever"]:
        gain = cls["hit_die"]
    else:
        method = choices.get("hp", "average")
        if method == "average":
            gain = E.average_hp(cls["hit_die"])
        elif method == "roll":
            if "hp_roll" not in choices:
                raise RulesError("Provide the rolled hit die result (hp_roll).")
            gain = int(choices["hp_roll"])
        elif isinstance(method, int):
            gain = method
        else:
            raise RulesError("hp must be 'average', 'roll' or a number.")
        if not 1 <= gain <= cls["hit_die"]:
            raise RulesError(f"A d{cls['hit_die']} result must be between 1 and {cls['hit_die']}.")
    char.d["hp"]["gains"].append(gain)

    # subclass
    if plan["subclass"]:
        sub = choices.get("subclass")
        if sub not in plan["subclass"]["options"]:
            raise RulesError(f"Choose a {plan['subclass']['title']}.")
        entry["subclass"] = sub
        _apply_subclass_grants(char, class_name, sub, plan.get("subclass_grants"), choices.get("subclass_choices", {}))

    # proficiencies from the class
    if plan["first_ever"]:
        profs["saves"] = list(cls["saves"])
        for kind, key in (("armor", "armor"), ("weapons", "weapons")):
            profs[kind] += [p for p in cls[key] if p not in profs[kind]]
        profs["tools"] += [_tool_title(t) for t in cls["tools"] if t.lower() not in _lower_set(profs["tools"]) and not _is_choice_text(t)]
    elif plan["new_class"]:
        gained = cls["multiclass"]["gained"]
        profs["armor"] += [a for a in gained.get("armor", []) if isinstance(a, str) and a not in profs["armor"]]
        profs["weapons"] += [w for w in gained.get("weapons", []) if w not in profs["weapons"]]
    if plan["skills"]:
        picks = _check_pick(choices.get("skills"), plan["skills"]["from"], plan["skills"]["count"], "skills")
        profs["skills"] += picks
    if plan["tools"]:
        spec = plan["tools"]
        profs["tools"] += [t.capitalize() if t.islower() else t for t in spec["fixed"] if t.lower() not in _lower_set(profs["tools"])]
        if spec["count"]:
            picks = _check_pick(choices.get("tools"), spec["from"], spec["count"], "tool proficiencies")
            profs["tools"] += picks

    # ability score improvement / feat
    if plan["asi"]:
        _apply_asi(char, choices.get("asi"))

    # expertise
    if plan["expertise"]:
        pool = [x for x in profs["skills"] if x not in profs["expertise"]]   # includes skills picked this level
        if plan["expertise"]["tools"] and thieves_tools_open(profs):
            pool.append("Thieves' Tools")
        picks = _check_pick(choices.get("expertise"), pool, plan["expertise"]["count"], "expertise picks")
        profs["expertise"] += picks

    # optional features
    taken = choices.get("options", {})
    groups_state = char.d["choices"].setdefault("groups", {})
    replaced = choices.get("replace_options", {})
    for old, new in replaced.items():
        for key, names in groups_state.items():
            if old in names:
                if new not in [o["name"] for o in rules.optional_features.values()]:
                    raise RulesError(f"Unknown option '{new}'.")
                names[names.index(old)] = new
                char.d["options"][char.d["options"].index(old)] = new
    for opt in plan["options"]:
        picks = _check_pick(taken.get(opt["key"]), opt["pool"], opt["count"], opt["name"])
        groups_state.setdefault(opt["key"], []).extend(picks)
        char.d["options"].extend(picks)

    # spells
    if plan["spells"]:
        _apply_spells(char, class_name, plan["spells"], choices)

    char.d["xp"] = max(char.xp, E.XP_THRESHOLDS[char.total_level - 1])
    new_max = char.max_hp
    char.current_hp = min(new_max, max(char.current_hp, 0) + (new_max - old_max)) if old_max else new_max
    return plan


def weapon_choices(spec: dict) -> List[str]:
    """Names of the (nonmagical, Player's Handbook) weapons a SUBCLASS_GRANTS 'weapon_picks' entry offers."""
    out = []
    for i in rules.items.values():
        if not i.get("weapon") or i.get("magic") or i.get("source") != "PHB" or i.get("category") not in ("simple", "martial"):
            continue
        if i["name"] in spec.get("allow", []) or (i["type"] == spec["type"] and not set(i.get("properties") or []) & set(spec.get("exclude", []))):
            out.append(i["name"])
    return sorted(dict.fromkeys(out))


def _fixed_subclass_grants(char: Character, class_name: str, sub: str) -> None:
    """What a subclass gives without a choice: armour, weapons, tools, languages, skills, expertise and cantrips.
    The subclass is remembered as given, so a grant removed by hand on the sheet stays removed."""
    g = SUBCLASS_GRANTS.get(sub) or {}
    profs = char.d["proficiencies"]
    for kind in ("armor", "weapons"):
        profs[kind] += [x for x in g.get(kind, []) if x not in profs[kind]]
    profs["tools"] += [t for t in g.get("tools", []) if t.lower() not in _lower_set(profs["tools"])]
    profs["languages"] += [l for l in g.get("languages_fixed", []) if l not in profs["languages"]]
    for sk in list(g.get("skills_fixed", [])) + list(g.get("expertise_fixed", [])):     # Way of Mercy's Insight and Medicine, a Scout's Nature and Survival
        if sk not in profs["skills"]:
            profs["skills"].append(sk)
    for sk in g.get("expertise_fixed", []):
        if sk not in profs["expertise"]:
            profs["expertise"].append(sk)
    known = taken_spells(char)
    cantrips = char.d["choices"].setdefault("bonus_cantrips", {}).setdefault(class_name, [])  # don't count against cantrips known
    for name in g.get("cantrip_fixed", []):
        if name.lower() not in known:                    # "if you don't already know it"
            cantrips.append(name)
    given = char.d["choices"].setdefault("subclass_grants_given", [])
    if sub not in given:
        given.append(sub)


def catch_up_subclass_grants(char: Character) -> None:
    """A character who took a subclass before its fixed grants were listed in SUBCLASS_GRANTS gets them once, on load."""
    given = (char.d.get("choices") or {}).get("subclass_grants_given", [])
    for c in char.d.get("classes") or []:
        sub = c.get("subclass")
        if sub in SUBCLASS_GRANTS and sub not in given:
            _fixed_subclass_grants(char, c["name"], sub)


def _apply_subclass_grants(char: Character, class_name: str, sub: str, need: Optional[dict], picks: dict) -> None:
    if sub not in SUBCLASS_GRANTS:
        return
    _fixed_subclass_grants(char, class_name, sub)
    g = SUBCLASS_GRANTS[sub]
    profs = char.d["proficiencies"]
    need = need or {}
    for key, spec in (g.get("weapon_picks") or {}).items():          # a kensei's weapons, a bladesinger's one-handed weapon: proficient, and remembered
        if key not in need:
            continue
        name = _check_pick(picks.get(key), need[key]["from"], need[key]["count"], "weapons")[0]
        item = rules.item(name)
        if item and not char.weapon_proficient(item):
            profs["weapons"].append(name)
        char.d["choices"].setdefault("subclass_weapons", {})[key] = name
    if "skills" in need:
        profs["skills"] += _check_pick(picks.get("skills"), need["skills"]["from"], need["skills"]["count"], "skills")
    if "expertise_skills" in need:
        spec = need["expertise_skills"]
        chosen = _check_pick(picks.get("expertise_skills"), spec["from"], spec["count"], "expertise skills")
        for sk in chosen:
            if sk not in profs["skills"]:
                profs["skills"].append(sk)
            profs["expertise"].append(sk)
    if "languages" in need:
        profs["languages"] += _check_pick(picks.get("languages"), need["languages"]["from"],
                                          need["languages"]["count"], "languages")
    if "tools" in need:
        profs["tools"] += _check_pick(picks.get("tools"), need["tools"]["from"], need["tools"]["count"], "tools")
    cantrips = char.d["choices"].setdefault("bonus_cantrips", {}).setdefault(class_name, [])
    if "cantrip" in need:
        cantrips += _check_pick(picks.get("cantrip"), need["cantrip"]["from"], need["cantrip"]["count"], "cantrip")


def _tool_title(t: str) -> str:
    """"thieves' tools" -> "Thieves' Tools", as backgrounds and races give it (creation.tool_name)."""
    return " ".join(w[:1].upper() + w[1:] for w in t.split(" "))


def thieves_tools_open(profs: dict) -> bool:
    """Proficient with thieves' tools (however it is spelled; older sheets say "thieves' tools") and not yet doubled."""
    return "thieves' tools" in _lower_set(profs["tools"]) and "thieves' tools" not in _lower_set(profs["expertise"])


def _is_choice_text(tool: str) -> bool:
    return any(w in tool.lower() for w in ("of your choice", "any one", "musical instrument"))


def _apply_asi(char: Character, asi: Optional[dict]) -> None:
    if not asi:
        raise RulesError("Choose an Ability Score Improvement or a feat.")
    if asi.get("feat"):
        apply_feat(char, asi["feat"], asi.get("feat_choices"))
        return
    increases = {a: n for a, n in (asi.get("abilities") or {}).items() if n}
    if sum(increases.values()) != 2 or any(n > 2 or n < 0 for n in increases.values()):
        raise RulesError("Ability Score Improvement: increase one score by 2 or two scores by 1.")
    bonus = char.d["abilities"]["improvement"]
    for a, n in increases.items():
        if char.ability_score(a) + n > E.MAX_ABILITY:
            raise RulesError(f"{E.ABILITY_NAMES[a]} cannot go above {E.MAX_ABILITY}.")
        bonus[a] = bonus.get(a, 0) + n


def _apply_spells(char: Character, class_name: str, plan: dict, choices: dict) -> None:
    sp = SC.class_spells(char, class_name)
    info = SC.spellcasting_info(char, char.class_entry(class_name))
    if plan["cantrips"]:
        sp["cantrips"] += _check_pick(choices.get("cantrips"), plan["cantrip_pool"], plan["cantrips"], "cantrips")
    secrets = list(choices.get("magic_secrets") or [])
    if plan["magic_secrets"] and len(secrets) > plan["magic_secrets"]:
        raise RulesError(f"Magical Secrets lets you take at most {plan['magic_secrets']} spells from any class.")
    if plan["known"]:
        picks = list(choices.get("spells") or [])
        picks = _check_pick(picks, plan["spell_pool"] + plan.get("any_class_pool", []), plan["known"], "spells")
        outside = [p for p in picks if p not in plan["spell_pool"]]
        if len(outside) > plan["magic_secrets"]:
            raise RulesError("Only Magical Secrets spells may come from outside your class list.")
        sp["known"] += picks
    elif choices.get("spells") and plan["known"] is None and not plan["spellbook"]:
        raise RulesError(f"{class_name} doesn't learn spells this way.")
    if plan["spellbook"]:
        sp["spellbook"] += _check_pick(choices.get("spellbook"), plan["spell_pool"], plan["spellbook"],
                                        "spellbook spells")
    swap = choices.get("swap")
    if swap:
        if not plan["swap"] or swap["remove"] not in sp["known"]:
            raise RulesError("You can only replace a spell you know, one per level.")
        if swap["add"] not in plan["spell_pool"] or swap["add"] in sp["known"]:
            raise RulesError("The replacement spell isn't available to you.")
        sp["known"][sp["known"].index(swap["remove"])] = swap["add"]
    if info["restricted_schools"]:
        try:
            SC.validate_restricted_choice(char, info, sp["known"])
        except ValueError as e:
            raise RulesError(str(e))
    prepared = choices.get("prepared")
    if prepared is not None:
        set_prepared(char, class_name, prepared)
    elif plan["prepared"] is not None and not info["spellbook"]:
        sp["prepared"] = [p for p in sp["prepared"]][: plan["prepared"]]


def set_prepared(char: Character, class_name: str, names: List[str]) -> None:
    """Replace the list of prepared spells (Cleric, Druid, Paladin, Wizard)."""
    info = SC.spellcasting_info(char, char.class_entry(class_name))
    if not info or info["prepared"] is None:
        raise RulesError(f"{class_name} doesn't prepare spells.")
    sp = SC.class_spells(char, class_name)
    always = SC.always_prepared(char, class_name)
    names = [n for n in names if n not in always]
    if len(set(names)) != len(names):
        raise RulesError("Duplicate prepared spell.")
    if len(names) > info["prepared"]:
        raise RulesError(f"You can prepare at most {info['prepared']} spells (always-prepared domain spells are free).")
    pool = sp["spellbook"] if info["spellbook"] else [s["name"] for s in SC.eligible_spells(char, info)]
    for n in names:
        spell = rules.spell(n)
        if not spell or n not in pool:
            raise RulesError(f"'{n}' is not available to prepare.")
        if spell["level"] > info["max_spell_level"]:
            raise RulesError(f"'{n}' is above your highest spell slot level.")
    sp["prepared"] = names


# ---------------------------------------------------------------- automatic choices (NPCs, tests)
def autolevel(char: Character, class_name: str, sources=None, subclass: Optional[str] = None) -> dict:
    """Level up taking the first valid option for every decision. Handy for quick NPCs and for testing."""
    plan = plan_level_up(char, class_name, None, sources)
    ch: dict = {"hp": "average"}
    if plan["subclass"]:
        ch["subclass"] = subclass or plan["subclass"]["options"][0]
        plan = plan_level_up(char, class_name, ch["subclass"], sources)
        grants = plan.get("subclass_grants") or {}
        ch["subclass_choices"] = {k: list(v["from"])[: v["count"]] for k, v in grants.items()
                                  if isinstance(v, dict) and v.get("from") is not None}      # (a weapon pick too)
    granted = {n for v in (ch.get("subclass_choices") or {}).values() for n in v}   # not picked a second time below
    free = lambda names: [n for n in names if n not in granted]
    taken_skills: List[str] = []
    if plan["skills"]:
        taken_skills = free(plan["skills"]["from"])[: plan["skills"]["count"]]
        ch["skills"] = taken_skills
    if plan["tools"] and plan["tools"]["count"]:
        ch["tools"] = free(plan["tools"]["from"])[: plan["tools"]["count"]]
    if plan["asi"]:
        for a in E.ABILITIES:
            if char.ability_score(a) + 2 <= E.MAX_ABILITY:
                ch["asi"] = {"abilities": {a: 2}}
                break
        else:
            first, second = [a for a in E.ABILITIES if char.ability_score(a) < E.MAX_ABILITY][:2]
            ch["asi"] = {"abilities": {first: 1, second: 1}}
    if plan["expertise"]:
        known = [x for x in char.d["proficiencies"]["skills"] + taken_skills if x not in char.d["proficiencies"]["expertise"]]
        ch["expertise"] = known[:2]
    if plan["options"]:
        ch["options"] = {o["key"]: o["pool"][: o["count"]] for o in plan["options"]}
    sp = plan["spells"]
    if sp:
        if sp["cantrips"]:
            ch["cantrips"] = free(sp["cantrip_pool"])[: sp["cantrips"]]
        if sp["known"]:
            pool = sp["spell_pool"]
            if sp["restricted_schools"]:   # Eldritch Knight / Arcane Trickster: prefer their two schools
                pool = sorted(pool, key=lambda n: rules.spell(n)["school"] not in sp["restricted_schools"])
            ch["spells"] = pool[: sp["known"]]
        if sp["spellbook"]:
            ch["spellbook"] = sp["spell_pool"][: sp["spellbook"]]
    apply_level_up(char, class_name, ch, sources)
    return ch
