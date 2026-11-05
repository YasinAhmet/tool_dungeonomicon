"""What the Rules tab shows: the content of the enabled sourcebooks (and the custom rulebooks), by book and kind,
with the ways each kind can be grouped - spells by level, school or class; items by category, type or rarity...
"""
from collections import Counter
from typing import Dict, List

from . import engine as E
from .data import rules
from .monsters import CR_STEPS, bestiary
from .search import ITEM_TYPES, RARITY_ORDER, item_category

CUSTOM = "Custom"                                     # backgrounds and creatures made in the app's generators
ALL = "*"                                             # every enabled book at once
KINDS = [("races", "Races"), ("classes", "Classes"), ("subclasses", "Subclasses"), ("backgrounds", "Backgrounds"),
         ("feats", "Feats"), ("spells", "Spells"), ("items", "Items"), ("monsters", "Creatures"),
         ("optional_features", "Class options"), ("languages", "Languages")]
OPTION_TYPES = {"EI": "Eldritch Invocations", "PB": "Pact Boons", "MM": "Metamagic", "MV:B": "Battle Master Maneuvers",
                "FS:F": "Fighting Styles (Fighter)", "FS:P": "Fighting Styles (Paladin)", "FS:R": "Fighting Styles (Ranger)",
                "FS:B": "Fighting Styles (Bard)", "AI": "Artificer Infusions", "AS": "Arcane Shots", "RN": "Runes",
                "ED": "Elemental Disciplines"}
LEVELS = ["Cantrips"] + [f"{E.ordinal(n)} level" for n in range(1, 10)]


def entries(kind: str) -> List[dict]:
    return {"races": lambda: list(rules.races.values()), "classes": lambda: list(rules.classes.values()),
            "subclasses": lambda: list(rules._subclasses), "backgrounds": lambda: list(rules.backgrounds.values()),
            "feats": lambda: list(rules.feats.values()), "spells": lambda: list(rules.spells.values()),
            "items": lambda: list(rules.items.values()), "monsters": lambda: list(bestiary.all),
            "optional_features": lambda: list(rules.optional_features.values()), "languages": lambda: list(rules.languages)}[kind]()


def visible() -> set:
    return set(rules.active_sources) | {CUSTOM}


# ====================================================================== books
def overview() -> List[dict]:
    """The books the Rules tab lists: every enabled book plus every custom rulebook (on or off), with content counts."""
    counts: Dict[str, Counter] = {}
    for kind, _title in KINDS:
        for e in entries(kind):
            counts.setdefault(e.get("source", ""), Counter())[kind] += 1
    active = set(rules.active_sources)
    out = []
    for sid, info in rules.sources.items():
        if sid in active or info.get("homebrew"):
            out.append({"id": sid, "name": info["name"], "group": info.get("group", "other"), "adventure": bool(info.get("adventure")),
                        "homebrew": bool(info.get("homebrew")), "description": info.get("description", ""), "active": sid in active,
                        "counts": dict(counts.get(sid, {}))})
    if counts.get(CUSTOM):
        out.append({"id": CUSTOM, "name": "Made in the app", "group": "custom", "adventure": False, "homebrew": False, "active": True,
                    "counts": dict(counts[CUSTOM])})
    total = Counter()
    for b in out:
        if b["active"]:
            total.update(b["counts"])
    return [{"id": ALL, "name": "All enabled books", "group": "all", "adventure": False, "homebrew": False, "active": True,
             "counts": dict(total)}] + out


# ====================================================================== one kind of content in a book
def _prereq(f: dict) -> str:
    """'Strength 13', 'Spellcasting', ... - how a feat's prerequisite reads."""
    bits = []
    for req in f.get("prerequisite") or []:
        if "ability" in req:
            bits.append(" or ".join(", ".join(f"{E.ABILITY_NAMES[a]} {n}" for a, n in opt.items()) for opt in req["ability"]))
        if "race" in req:
            bits.append(", ".join(map(str, req["race"])))
        if "level" in req:
            bits.append(f"Level {req['level'] if not isinstance(req['level'], dict) else req['level'].get('level', '?')}")
        if "proficiency" in req:
            bits.append(", ".join(f"{p.get('armor') or p.get('weapon') or ''} proficiency".strip() for p in req["proficiency"]))
        if any(k.startswith("spellcasting") for k in req):
            bits.append("Spellcasting")
        if "other" in req:
            bits.append(str(req["other"]))
    return "; ".join(b for b in bits if b)


def _prereq_group(f: dict) -> str:
    keys = {k for req in f.get("prerequisite") or [] for k in req}
    if not keys:
        return "No prerequisite"
    for k, label in (("race", "Race"), ("ability", "Ability score"), ("proficiency", "Proficiency"), ("level", "Level")):
        if k in keys:
            return label
    return "Spellcasting" if any(k.startswith("spellcasting") for k in keys) else "Other"


def _feat_ability(f: dict) -> List[str]:
    ab = f.get("ability") or {}
    out = [f"{E.ABILITY_NAMES[a]} +{n}" for a, n in (ab.get("fixed") or {}).items()]
    if ab.get("choose"):
        out += [f"{E.ABILITY_NAMES[a]} +{ab['choose']['amount']}" for a in ab["choose"]["from"]]
    return out or ["No ability increase"]


def _cost(i: dict) -> str:
    return f"{(i['value'] or 0) / 100:g} gp" if i.get("value") else ""


# kind -> (row maker, [(grouping key, title, value order or None)])
SPEC: Dict[str, tuple] = {
    "races": (lambda r: {"id": r["name"], "meta": f"{r['size']}, {r['speed'].get('walk', 30)} ft"
                         + (f", {len(r['subraces'])} subraces" if r["subraces"] else ""),
                         "groups": {"size": [r["size"]]}},
              [("size", "Size", ["Tiny", "Small", "Medium", "Large"])]),
    "classes": (lambda c: {"id": c["name"], "meta": f"d{c['hit_die']} hit die", "groups": {"hit_die": [f"d{c['hit_die']} hit die"]}},
                [("hit_die", "Hit die", [f"d{n} hit die" for n in (6, 8, 10, 12)])]),
    "subclasses": (lambda s: {"id": f"{s['class']}::{s['name']}", "meta": s["class"], "groups": {"class": [s["class"]]}},
                   [("class", "Class", None)]),
    "backgrounds": (lambda b: {"id": b["name"], "meta": ", ".join(x.title() for x in (b.get("skills") or {}).get("fixed", [])),
                               "groups": {"skill": [x.title() for x in (b.get("skills") or {}).get("fixed", [])] or ["Any skills"]}},
                    [("skill", "Skill", None)]),
    "feats": (lambda f: {"id": f["name"], "meta": _prereq(f), "groups": {"prereq": [_prereq_group(f)], "ability": _feat_ability(f)}},
              [("prereq", "Prerequisite", ["No prerequisite", "Ability score", "Race", "Proficiency", "Spellcasting", "Level", "Other"]),
               ("ability", "Ability increase", None)]),
    "spells": (lambda s: {"id": s["name"], "meta": f"{LEVELS[s['level']].rstrip('s') if s['level'] else 'Cantrip'} {s['school'].lower()}"
                          + (" (ritual)" if s["ritual"] else "") + (" · C" if s["concentration"] else ""),
                          "groups": {"level": [LEVELS[s["level"]]], "school": [s["school"]], "class": list(s["classes"]) or ["No class list"]}},
               [("level", "Level", LEVELS), ("school", "School", None), ("class", "Class", None)]),
    "items": (lambda i: {"id": i["name"], "meta": " · ".join(x for x in (ITEM_TYPES.get(i["type"], i["type"]),
                                                                          i["rarity"] if i["rarity"] != "none" else "", _cost(i)) if x),
                         "groups": {"category": [item_category(i)], "type": [ITEM_TYPES.get(i["type"], i["type"]) or "Miscellaneous"],
                                    "rarity": [i["rarity"].title() if i["rarity"] != "none" else "Mundane"]}},
              [("category", "Category", None), ("type", "Type", None),
               ("rarity", "Rarity", [r.title() if r != "none" else "Mundane" for r in RARITY_ORDER])]),
    "monsters": (lambda m: {"id": m["id"], "meta": f"CR {m['cr']} {m['size'].lower()} {m['type']}",
                            "groups": {"type": [m["type"].split("/")[0].title()], "cr": [f"CR {m['cr']}"], "size": [m["size"].split("/")[0]]}},
                 [("type", "Type", None), ("cr", "Challenge", [f"CR {c}" for c in CR_STEPS]),
                  ("size", "Size", ["Tiny", "Small", "Medium", "Large", "Huge", "Gargantuan"])]),
    "optional_features": (lambda o: {"id": o["name"], "meta": ", ".join(OPTION_TYPES.get(t, t) for t in o["types"]),
                                     "groups": {"type": [OPTION_TYPES.get(t, t) for t in o["types"]]}},
                          [("type", "Type", None)]),
    "languages": (lambda l: {"id": l["name"], "meta": l["type"] + (f", {l['script']} script" if l.get("script") else ""),
                             "groups": {"type": [l["type"].title()]}},
                  [("type", "Type", ["Standard", "Exotic", "Rare", "Secret"])]),
}


def listing(book: str, kind: str) -> dict:
    """Every entry of one kind in one book (or in every enabled book), ready to be folded into groups."""
    if kind not in SPEC:
        raise KeyError(kind)
    make, groupings = SPEC[kind]
    allowed = visible() if book == ALL else {book}
    rows = []
    for e in entries(kind):
        if e.get("source") in allowed:
            r = make(e)
            r.update(name=e["name"], src=e.get("source", ""), homebrew=bool(e.get("homebrew")))
            r["groups"]["book"] = [(rules.sources.get(r["src"]) or {}).get("name", "Made in the app" if r["src"] == CUSTOM else r["src"])]
            rows.append(r)
    rows.sort(key=lambda r: r["name"].lower())
    out = []
    for key, title, order in groupings + ([("book", "Book", None)] if book == ALL else []):
        seen = {v for r in rows for v in r["groups"][key]}
        rank = {v: i for i, v in enumerate(order or [])}
        out.append({"key": key, "title": title, "order": sorted(seen, key=lambda v: (rank.get(v, 999), v.lower()))})
    return {"rows": rows, "groupings": out}


def feat_text(f: dict) -> str:
    pre = _prereq(f)
    return (f"Prerequisite: {pre}\n\n" if pre else "") + f["text"]


def subclass_text(s: dict) -> str:
    return "\n\n".join(f"Level {f['level']}: {f['name']}\n{f['text']}" for f in s["features"])


def language_text(l: dict) -> str:
    return f"{l['type'].title()} language" + (f"\nScript: {l['script']}" if l.get("script") else "")
