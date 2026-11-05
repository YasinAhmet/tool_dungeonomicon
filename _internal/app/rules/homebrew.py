"""Custom rulebooks: books written in the Rules tab, one file each (data/homebrew/<id>.json).

A custom rulebook is a sourcebook like the imported ones: its id is listed in `rules.sources` (group "homebrew"),
it is switched on and off in the Sourcebooks window, and its content is merged into the rules data - so a custom
race is offered in character creation, a custom spell in level-up, a custom item in the item search and so on.

Every entry keeps the form it was made from ("form"), so the Rules tab can open it again for editing.
"""
import os
import re
import threading
from functools import wraps
from typing import Dict, List, Optional, Tuple

from ..core.storage import read_json, write_json
from . import engine as E
from .data import rules
from .leveling import RulesError

BOOKS_DIR = os.path.join("data", "homebrew")
CUSTOM_ITEMS = os.path.join("data", "custom_items.json")
KINDS = ("races", "subclasses", "backgrounds", "feats", "spells", "items", "optional_features", "languages", "monsters")
SCHOOLS = ["Abjuration", "Conjuration", "Divination", "Enchantment", "Evocation", "Illusion", "Necromancy", "Transmutation"]
DAMAGE_TYPES = ["acid", "bludgeoning", "cold", "fire", "force", "lightning", "necrotic", "piercing", "poison", "psychic",
                "radiant", "slashing", "thunder"]
RARITIES = ["none", "common", "uncommon", "rare", "very rare", "legendary", "artifact"]
WEAPON_PROPERTIES = ["ammunition", "finesse", "heavy", "light", "loading", "reach", "special", "thrown", "two-handed", "versatile"]
OPTION_TYPES = {"EI": "Eldritch Invocation", "PB": "Pact Boon", "MM": "Metamagic", "MV:B": "Battle Master Maneuver",
                "FS:F": "Fighting Style (Fighter)", "FS:P": "Fighting Style (Paladin)", "FS:R": "Fighting Style (Ranger)",
                "FS:B": "Fighting Style (Bard)", "AI": "Artificer Infusion", "AS": "Arcane Shot", "RN": "Rune",
                "ED": "Elemental Discipline"}
LANGUAGE_TYPES = ["standard", "exotic", "rare", "secret"]

_books: Optional[List[dict]] = None
_lock = threading.RLock()                             # the web server saves from several threads at once


def _locked(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        with _lock:
            return fn(*args, **kwargs)
    return wrapper


# ====================================================================== reading
def books() -> List[dict]:
    """Every custom rulebook, sorted by name."""
    global _books
    if _books is None:
        out = []
        if os.path.isdir(BOOKS_DIR):
            for f in sorted(os.listdir(BOOKS_DIR)):
                if f.endswith(".json"):
                    b = read_json(os.path.join(BOOKS_DIR, f), None)
                    if isinstance(b, dict) and b.get("id") and b.get("name"):
                        b.setdefault("description", "")
                        b["content"] = {k: list((b.get("content") or {}).get(k) or []) for k in KINDS}
                        out.append(b)
        _books = sorted(out, key=lambda b: b["name"].lower())
    return _books


def book(book_id: str) -> dict:
    b = next((b for b in books() if b["id"] == book_id), None)
    if not b:
        raise RulesError("That rulebook doesn't exist (any more).")
    return b


def entries(kind: str) -> List[dict]:
    """The content of one kind from every custom rulebook (merged into the rules data by app.rules.data)."""
    return [e for b in books() for e in b["content"].get(kind, [])]


def source_entries() -> Dict[str, dict]:
    return {b["id"]: {"name": b["name"], "group": "homebrew", "homebrew": True, "description": b["description"]} for b in books()}


# ====================================================================== books
def _path(book_id: str) -> str:
    return os.path.join(BOOKS_DIR, re.sub(r"[^\w\-]", "_", book_id) + ".json")


def _write(b: dict) -> None:
    write_json(_path(b["id"]), b)
    refresh()


def _new_id(name: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", name)
    base = "HB-" + ("".join(w[0] for w in words[:4]).upper() or "BOOK")
    taken = set(rules.sources)
    n, out = 1, base
    while out in taken:
        n += 1
        out = f"{base}{n}"
    return out


@_locked
def save_book(name: str, description: str = "", book_id: Optional[str] = None) -> dict:
    """Create a rulebook (no id) or rename / redescribe one."""
    name = str(name or "").strip()
    if not name:
        raise RulesError("Give the rulebook a name.")
    if any(b["name"].lower() == name.lower() and b["id"] != book_id for b in books()) or \
            any(v["name"].lower() == name.lower() for k, v in rules.sources.items() if not v.get("homebrew")):
        raise RulesError(f"There already is a rulebook called '{name}'.")
    if book_id:
        b = book(book_id)
        b.update(name=name, description=str(description or "").strip())
    else:
        b = {"id": _new_id(name), "name": name, "description": str(description or "").strip(), "content": {k: [] for k in KINDS}}
    _write(b)
    return b


@_locked
def delete_book(book_id: str) -> None:
    from ..core.userdata import keep_copy
    b = book(book_id)
    keep_copy(_path(b["id"]), "deleted")              # deleting a book is never final: a copy stays in backups/deleted
    os.remove(_path(b["id"]))
    refresh()


# ====================================================================== content
@_locked
def save_entry(book_id: str, kind: str, form: dict, original: Optional[str] = None) -> dict:
    """Add (or, with `original` = its current name, replace) one piece of content. Returns the stored entry."""
    if kind not in BUILDERS:
        raise RulesError(f"Unknown content type '{kind}'.")
    b = book(book_id)
    entry = BUILDERS[kind](form)
    entry.update(source=b["id"], homebrew=True)
    if kind == "monsters":                             # a creature keeps its generator spec ("spec") instead of a form
        entry["id"] = f"{entry['name']}|{b['id']}"
    else:
        entry["form"] = form
    key, old = _key(kind, entry), (original or "").lower()
    if key != old:
        _check_clash(kind, entry)
    b["content"][kind] = [e for e in b["content"][kind] if _key(kind, e) not in (key, old)] + [entry]
    _write(b)
    return entry


@_locked
def import_entries(book_id: str, content: Dict[str, List[dict]]) -> Tuple[int, List[str]]:
    """Add ready-made records ({kind: [records]}, a module's) to a rulebook in one go; the ones that clash with content
    already there are left out. Records that came from a rulebook keep their "form" (or a creature its "spec"), so the
    Rules tab edits them as before. Returns (added, ['name: why it was left out'])."""
    b = book(book_id)
    added, skipped = 0, []
    for kind, rows in content.items():
        if kind not in KINDS:
            continue
        for r in rows:
            entry = {k: v for k, v in r.items() if k not in ("module", "pack", "portrait", "homebrew")}
            entry.update(source=b["id"], homebrew=True)
            if kind == "monsters":
                entry["id"] = f"{entry['name']}|{b['id']}"
            key = _key(kind, entry)
            if any(_key(kind, e) == key for e in b["content"][kind]):
                skipped.append(f"{entry['name']}: twice in the module")
                continue
            try:
                _check_clash(kind, entry)
            except RulesError as e:
                skipped.append(f"{entry['name']}: {e}")
                continue
            b["content"][kind].append(entry)
            added += 1
    _write(b)
    return added, skipped


@_locked
def delete_entry(book_id: str, kind: str, name: str) -> None:
    b = book(book_id)
    keep = [e for e in b["content"].get(kind, []) if entry_id(kind, e) != name]
    if len(keep) == len(b["content"].get(kind, [])):
        raise RulesError(f"'{name}' isn't in {b['name']}.")
    b["content"][kind] = keep
    _write(b)


# ====================================================================== items made in the app (CUSTOMS, source "Custom")
def custom_items() -> List[dict]:
    """The Item workshop's items outside any rulebook (data/custom_items.json), merged into the rules data."""
    items = read_json(CUSTOM_ITEMS, [])
    return [i for i in items if isinstance(i, dict) and i.get("name")] if isinstance(items, list) else []


@_locked
def save_custom_item(form: dict, original: Optional[str] = None) -> dict:
    """Add (or, with `original` = its current name, replace) an item of CUSTOMS. Returns the stored entry."""
    entry = build_item(form)
    entry.update(source="Custom", form=form)
    key, old = entry["name"].lower(), (original or "").lower()
    if key != old:
        _check_clash("items", entry)
    write_json(CUSTOM_ITEMS, [i for i in custom_items() if i["name"].lower() not in (key, old)] + [entry])
    refresh()
    return entry


@_locked
def delete_custom_item(name: str) -> None:
    keep = [i for i in custom_items() if i["name"].lower() != name.lower()]
    if len(keep) == len(custom_items()):
        raise RulesError(f"'{name}' isn't one of your items.")
    write_json(CUSTOM_ITEMS, keep)
    refresh()


def entry_id(kind: str, e: dict) -> str:
    """How the Rules tab names an entry: a subclass as 'Class::Name', a creature by its id, everything else by name."""
    return f"{e['class']}::{e['name']}" if kind == "subclasses" else e["id"] if kind == "monsters" else e["name"]


def _key(kind: str, e: dict) -> str:
    return entry_id(kind, e).lower()


def _check_clash(kind: str, entry: dict) -> None:
    name = entry["name"]
    if kind == "races" and name in rules.races or kind == "feats" and name in rules.feats \
            or kind == "backgrounds" and name in rules.backgrounds or kind == "spells" and rules.spell(name) \
            or kind == "items" and rules.item(name) or kind == "optional_features" and name in rules.optional_features:
        raise RulesError(f"'{name}' already exists. Pick another name.")
    if kind == "subclasses" and rules.subclass(entry["class"], name):
        raise RulesError(f"{entry['class']} already has a subclass called '{name}'.")
    if kind == "languages" and any(l["name"].lower() == name.lower() for l in rules.languages):
        raise RulesError(f"The language '{name}' already exists.")
    if kind == "monsters":
        from .monsters import bestiary
        if bestiary.get(entry["id"]):
            raise RulesError(f"This rulebook already has a creature called '{name}'.")


# ====================================================================== form -> rules entry
def _text(form: dict, key: str, required: str = "") -> str:
    v = str(form.get(key) or "").strip()
    if required and not v:
        raise RulesError(required)
    return v


def _int(form: dict, key: str, default: int = 0, lo: Optional[int] = None, hi: Optional[int] = None) -> int:
    try:
        n = int(float(form.get(key) if form.get(key) not in (None, "") else default))
    except (TypeError, ValueError):
        raise RulesError(f"'{form.get(key)}' isn't a number.")
    if lo is not None:
        n = max(lo, n)
    return n if hi is None else min(hi, n)


def _float(form: dict, key: str) -> float:
    try:
        return float(form.get(key) or 0)
    except (TypeError, ValueError):
        raise RulesError(f"'{form.get(key)}' isn't a number.")


def _list(form: dict, key: str, allowed=None) -> List[str]:
    vals = form.get(key) or []
    if isinstance(vals, str):
        vals = [v for v in re.split(r"[,\n]", vals)]
    out = [str(v).strip() for v in vals if str(v).strip()]
    if allowed is not None:
        out = [v for v in out if v in allowed]
    return list(dict.fromkeys(out))


def _named_list(form: dict, key: str, with_level: bool = False) -> List[dict]:
    out = []
    for row in form.get(key) or []:
        name, text = str(row.get("name") or "").strip(), str(row.get("text") or "").strip()
        if not name and not text:
            continue
        if not name:
            raise RulesError("Every entry needs a name.")
        e = {"name": name, "text": text}
        if with_level:
            e["level"] = _int(row, "level", 1, 1, 20)
        out.append(e)
    return out


def build_spell(f: dict) -> dict:
    name = _text(f, "name", "Give the spell a name.")
    level = _int(f, "level", 0, 0, 9)
    school = f.get("school") if f.get("school") in SCHOOLS else "Evocation"
    material = _text(f, "material")
    comps = {"v": bool(f.get("v")), "s": bool(f.get("s")), "m": material}
    comps["text"] = ", ".join([x for x, on in (("V", comps["v"]), ("S", comps["s"])) if on]
                              + ([f"M ({material})"] if material else [])) or "None"
    duration = _text(f, "duration") or "Instantaneous"
    concentration = bool(f.get("concentration"))
    if concentration and not duration.lower().startswith("concentration"):
        duration = "Concentration, " + duration[0].lower() + duration[1:]
    return {"name": name, "level": level, "school": school, "casting_time": _text(f, "casting_time") or "1 action",
            "range": _text(f, "range") or "Self", "components": comps, "duration": duration, "concentration": concentration,
            "ritual": bool(f.get("ritual")), "text": _text(f, "text", "Describe what the spell does."),
            "higher_level": _text(f, "higher_level"), "classes": _list(f, "classes", set(rules.classes)),
            "save": _list(f, "save", set(E.ABILITY_NAMES.values())), "damage": _list(f, "damage", DAMAGE_TYPES), "scaling_dice": None}


def build_item(f: dict) -> dict:
    from .search import ITEM_TYPES
    name = _text(f, "name", "Give the item a name.")
    kind = f.get("type") if f.get("type") in ITEM_TYPES else "G"
    rarity = f.get("rarity") if f.get("rarity") in RARITIES else "none"
    magic = bool(f.get("magic")) or rarity != "none"
    out = {"name": name, "type": kind, "rarity": rarity, "weight": max(0.0, _float(f, "weight")),
           "value": round(max(0.0, _float(f, "cost")) * 100), "text": _text(f, "text"), "magic": magic}
    if f.get("attune"):
        out["attune"] = _text(f, "attune_by")
    if kind in ("M", "R"):
        dmg = _text(f, "dmg1", "A weapon needs its damage dice (e.g. 1d8).")
        if not re.fullmatch(r"\d+(d\d+)?", dmg):
            raise RulesError("Damage should look like 1d8 (or a flat number).")
        out.update(weapon=True, category="martial" if f.get("category") == "martial" else "simple", dmg1=dmg,
                   dmg_type=f.get("dmg_type") if f.get("dmg_type") in DAMAGE_TYPES else "slashing",
                   properties=_list(f, "properties", WEAPON_PROPERTIES))
        if _text(f, "dmg2"):
            out["dmg2"] = _text(f, "dmg2")
            if "versatile" not in out["properties"]:
                out["properties"].append("versatile")
        if _text(f, "range"):
            out["range"] = _text(f, "range")
    if kind in ("LA", "MA", "HA", "S"):
        out.update(armor=kind != "S", ac=_int(f, "ac", 2 if kind == "S" else 11, 0, 30), stealth_disadvantage=bool(f.get("stealth")))
        if _int(f, "strength", 0, 0, 30):
            out["strength"] = str(_int(f, "strength", 0, 0, 30))
    for key in ("bonus_weapon", "bonus_ac"):
        if _int(f, key, 0, 0, 3):
            out[key] = _int(f, key, 0, 0, 3)
    return out


def build_feat(f: dict) -> dict:
    name = _text(f, "name", "Give the feat a name.")
    prereq = []
    if f.get("pre_ability") in E.ABILITIES:
        prereq.append({"ability": [{f["pre_ability"]: _int(f, "pre_score", 13, 1, 30)}]})
    if _int(f, "pre_level", 0, 0, 20):
        prereq.append({"level": _int(f, "pre_level", 0, 0, 20)})
    if _list(f, "pre_race"):
        prereq.append({"race": _list(f, "pre_race", set(rules.races))})
    if f.get("pre_spellcasting"):
        prereq.append({"spellcasting": True})
    fixed, choose = {}, None
    plus = _list(f, "ability_plus", E.ABILITIES)
    if len(plus) == 1:
        fixed = {plus[0]: 1}
    elif plus:
        choose = {"from": plus, "count": 1, "amount": 1}
    return {"name": name, "prerequisite": prereq, "ability": {"fixed": fixed, "choose": choose},
            "text": _text(f, "text", "Describe what the feat does."), "armor": [], "weapons": [], "skills": None, "tools": None}


def build_race(f: dict) -> dict:
    name = _text(f, "name", "Give the race a name.")
    speed = {"walk": _int(f, "walk", 30, 0, 120)}
    for k in ("fly", "swim", "climb"):
        if _int(f, k, 0, 0, 120):
            speed[k] = _int(f, k, 0, 0, 120)
    fixed = {a: _int(f, "ab_" + a, 0, -4, 4) for a in E.ABILITIES if _int(f, "ab_" + a, 0, -4, 4)}
    choose = None
    if _int(f, "ab_choose", 0, 0, 6):
        choose = {"from": [a for a in E.ABILITIES if a not in fixed] or list(E.ABILITIES),
                  "count": _int(f, "ab_choose", 0, 0, 6), "amount": _int(f, "ab_amount", 1, 1, 2)}
    traits = _named_list(f, "traits")
    skills = [s.lower() for s in _list(f, "skills", set(rules.skills))]
    return {"name": name, "size": f.get("size") if f.get("size") in ("Small", "Medium") else "Medium", "speed": speed,
            "ability": {"fixed": fixed, "choose": choose}, "darkvision": _int(f, "darkvision", 0, 0, 300),
            "feats": _int(f, "feats", 0, 0, 2), "spells": [], "traits": [dict(t, overwrite=None) for t in traits],
            "age": "", "languages": {"fixed": [l.lower() for l in _list(f, "languages")], "any": _int(f, "languages_any", 0, 0, 5),
                                     "from": [], "count": 0},
            "skills": {"fixed": skills, "any": _int(f, "skills_any", 0, 0, 5), "from": [], "count": 0},
            "resist": _list(f, "resist", DAMAGE_TYPES), "resist_choose": [], "subraces": [], "subrace_required": False, "ancestries": []}


def build_background(f: dict) -> dict:
    from .custom_background import build_background as build
    lines = f.get("equipment") or []
    bg = build({**f, "equipment": lines.split("\n") if isinstance(lines, str) else lines})    # one item per line
    bg.pop("spec", None)
    if _text(f, "text"):
        bg["text"] = _text(f, "text")
    return bg


def build_subclass(f: dict) -> dict:
    name = _text(f, "name", "Give the subclass a name.")
    cls = f.get("class")
    if cls not in rules.classes:
        raise RulesError("Choose the class this subclass belongs to.")
    features = _named_list(f, "features", with_level=True)
    if not features:
        raise RulesError("Add at least one feature.")
    return {"class": cls, "name": name, "short": _text(f, "short") or name, "features": sorted(features, key=lambda x: x["level"]),
            "additional_spells": [], "optional_progression": [], "spellcasting": None}


def build_option(f: dict) -> dict:
    name = _text(f, "name", "Give the option a name.")
    kind = f.get("kind") if f.get("kind") in OPTION_TYPES else "EI"
    text = _text(f, "text", "Describe what the option does.")
    if _text(f, "prerequisite"):
        text = f"Prerequisite: {_text(f, 'prerequisite')}\n\n{text}"
    return {"name": name, "types": [kind], "prerequisite": [], "text": text}


def build_language(f: dict) -> dict:
    return {"name": _text(f, "name", "Give the language a name."),
            "type": f.get("type") if f.get("type") in LANGUAGE_TYPES else "standard", "script": _text(f, "script")}


def build_monster(f: dict) -> dict:
    from . import monster_gen as G
    m = G.build(f)
    if not G.clean(f)["name"]:
        raise RulesError("Give the creature a name.")
    if not m["actions"] and not m["traits"] and not m["spellcasting"]:
        raise RulesError("Add at least one trait or action.")
    return m


BUILDERS = {"spells": build_spell, "items": build_item, "feats": build_feat, "races": build_race, "backgrounds": build_background,
            "subclasses": build_subclass, "optional_features": build_option, "languages": build_language, "monsters": build_monster}


# ====================================================================== keeping everything in step
def refresh() -> None:
    """Forget every cached view of the rules data so the change shows up everywhere at once."""
    global _books
    _books = None
    for key in ("sources", "races", "spells", "items", "feats", "backgrounds", "_subclasses", "optional_features", "languages"):
        rules.__dict__.pop(key, None)
    from . import monster_gen, search
    from .monsters import bestiary
    bestiary.reload_custom()
    search.monster_index = search.item_index = None
    monster_gen.invalidate()
