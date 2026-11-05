"""The readable text of any piece of game content - one place for every 'show me this entry' in the app.

    describe("spells", "Fireball")          -> {"title", "text", "src", "book", "homebrew", "form"}
    describe("races", "Elf::High Elf")      -> a race, or one of its subraces ('race::subrace')
    describe("subclasses", "Wizard::School of Evocation")

KINDS lists what can be described. A new kind of content adds one function to _TEXT.
"""
from typing import Callable, Dict, Optional, Tuple

from . import catalog as CAT
from . import engine as E
from . import search as S
from .character import Character
from .creation import racial_fixed, tool_name
from .data import rules
from .monsters import bestiary, statblock


class UnknownContent(ValueError):
    """The entry isn't in the active rules (any more)."""


def spell_text(s: dict) -> str:
    head = (f"{s['name']} — {'Cantrip' if s['level'] == 0 else E.ordinal(s['level']) + '-level'} {s['school']}"
            f"{' (ritual)' if s['ritual'] else ''}\n{s['casting_time']} · {s['range']} · {s['components']['text']} · "
            f"{s['duration']}\n")
    return head + s["text"] + (f"\n\nAt higher levels: {s['higher_level']}" if s["higher_level"] else "")


def spell_detail(name: str) -> str:
    s = rules.spell(name)
    return spell_text(s) if s else name


def feature_detail(name: str) -> str:
    """An optional class feature (invocation, maneuver...) or a feat, by name."""
    opt = rules.optional_features.get(name)
    if opt:
        return f"{name}\n{opt['text']}"
    feat = rules.feats.get(name)
    return f"{name}\n{feat['text']}" if feat else name


def race_text(race_name: str, sub: Optional[str] = None, ancestry: Optional[str] = None,
              ability_choose: Optional[dict] = None) -> str:
    race = rules.races[race_name]
    probe = Character.create_blank("probe")
    probe.d["race"], probe.d["subrace"], probe.d["ancestry"] = race_name, sub, ancestry
    data = probe.race_data()
    fixed = racial_fixed(race, next((x for x in race["subraces"] if x["name"] == sub), None))
    bonus = ", ".join(f"{E.ABILITY_NAMES[a]} +{n}" for a, n in fixed.items())
    if ability_choose:
        c = ability_choose
        bonus += (", " if bonus else "") + f"+{c['amount']} to {c['count']} other abilities of your choice"
    text = [f"{race_name}{f' ({sub})' if sub else ''} - {data['size']}, speed {data['speed'].get('walk', 30)} ft"
            + (f", darkvision {data['darkvision']} ft" if data["darkvision"] else ""), f"Ability scores: {bonus or 'none'}"]
    text += [f"{t['name']}. {t['text']}" for t in data["traits"] if t["name"] not in ("Age", "Size", "Speed")]
    return "\n\n".join(text)


def background_text(name: str) -> str:
    bg = rules.backgrounds[name]
    lines = [bg["text"]]
    if bg.get("skills", {}).get("fixed"):
        lines.append("Skills: " + ", ".join(rules.skill_name(x) for x in bg["skills"]["fixed"]))
    if bg.get("tools", {}).get("fixed"):
        lines.append("Tools: " + ", ".join(tool_name(t) for t in bg["tools"]["fixed"]))
    if bg["feature"]:
        lines.append(f"Feature - {bg['feature']['name']}: {bg['feature']['text']}")
    return "\n\n".join(x for x in lines if x)


def class_text(c: dict) -> str:
    profs = [f"Hit die d{c['hit_die']}", "Saving throws: " + ", ".join(E.ABILITY_NAMES[x] for x in c["saves"])]
    if c["armor"]:
        profs.append("Armor: " + ", ".join(c["armor"]))
    profs.append("Weapons: " + ", ".join(c["weapons"]) if c["weapons"] else "Weapons: none")
    if c["tools"]:
        profs.append("Tools: " + ", ".join(c["tools"]))
    feats = "\n".join(f"Level {f['level']}: {f['name']}" for f in c["features"] if f["level"] == 1)
    return "\n".join(profs) + "\n\nLevel 1 features:\n" + feats


# ---------------------------------------------------------------------- one entry of each kind: (entry, text)
def _race(ident: str) -> Tuple[Optional[dict], str]:
    name, _, sub = ident.partition("::")
    e = rules.races.get(name)
    if not e:
        return None, ""
    if sub:
        return e, race_text(name, sub)
    text = race_text(name, None, None, e["ability"]["choose"])
    if e["subraces"]:
        text += "\n\nSubraces\n" + "\n".join(f"• {s['name']}" + (f" ({s['source']})" if s.get("source", e["source"]) != e["source"] else "")
                                            for s in e["subraces"] if s["name"])
    return e, text


def _class(ident: str):
    e = rules.classes.get(ident)
    return e, e and class_text(e) + "\n\nSubclasses: " + (", ".join(s["name"] for s in rules.subclasses_of(ident)) or "none")


def _subclass(ident: str):
    cls, _, name = ident.partition("::")
    e = rules.subclass(cls, name)
    return e, e and CAT.subclass_text(e)


def _language(ident: str):
    e = next((l for l in rules.languages if l["name"] == ident), None)
    return e, e and CAT.language_text(e)


_TEXT: Dict[str, Callable[[str], tuple]] = {
    "races": _race,
    "classes": _class,
    "subclasses": _subclass,
    "backgrounds": lambda i: (rules.backgrounds.get(i), i in rules.backgrounds and background_text(i)),
    "feats": lambda i: (rules.feats.get(i), i in rules.feats and CAT.feat_text(rules.feats[i])),
    "spells": lambda i: (rules.spell(i), rules.spell(i) and spell_text(rules.spell(i))),
    "items": lambda i: (rules.item(i), rules.item(i) and S.item_text(rules.item(i))),
    "monsters": lambda i: (bestiary.get(i), bestiary.get(i) and statblock(bestiary.get(i))),
    "optional_features": lambda i: (rules.optional_features.get(i), (rules.optional_features.get(i) or {}).get("text")),
    "languages": _language,
}
KINDS = tuple(_TEXT)


def describe(kind: str, ident: str) -> dict:
    if kind not in _TEXT:
        raise UnknownContent(f"Unknown content type '{kind}'.")
    e, text = _TEXT[kind](ident)
    if not e:
        raise UnknownContent(f"'{ident}' isn't in the rules (any more).")
    src = e.get("source", "")
    return {"title": e["name"] if kind not in ("races",) or "::" not in ident else ident.replace("::", " - "),
            "text": text or "", "src": src, "book": (rules.sources.get(src) or {}).get("name", src),
            "homebrew": bool(e.get("homebrew")), "form": e.get("form")}


def language_group(name: str) -> str:
    """'Standard', 'Exotic', 'Secret', 'Rare' or 'Other' - how pick lists fold languages."""
    e = next((l for l in rules.languages if l["name"] == name), None)
    return e["type"].title() if e and e.get("type") else "Other"


def describe_name(name: str) -> str:
    """A short description for any name a pick list offers: a skill, a language, an item or tool, a spell, a feat
    or an optional feature (empty when unknown)."""
    sk = rules.skills.get(name)
    if sk:
        return f"Skill - {E.ABILITY_NAMES[sk['ability']]}\n{sk['text']}"
    if any(l["name"] == name for l in rules.languages):
        return f"Language ({language_group(name)})"
    for kind in ("items", "spells", "feats", "optional_features"):
        try:
            return describe(kind, name)["text"]
        except UnknownContent:
            continue
    return ""
