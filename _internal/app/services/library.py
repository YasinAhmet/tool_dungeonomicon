"""The content library: faceted search over monsters and items, custom rulebooks (homebrew) and custom creatures.

    search("monsters", q="dragon", sets={"type": {"dragon"}}, ranges={"cr": (5, None)}, sort="cr")
    app.rules.describe.describe(kind, id)  # the text of any entry
    save_book(...), save_entry(...)        # custom rulebooks: data/homebrew/<id>.json
    save_creature(spec) / delete_creature  # the monster generator's CUSTOMS (or a rulebook's creature)
    save_item(form) / delete_item          # the Item workshop's CUSTOMS (or a rulebook's item); item_form(name)
    rule_books(), rule_listing(book, kind)  # what the Rules window lists
    content_fields(kind)                   # the 'add content' form of a custom rulebook, as field definitions
    sourcebook_sections(), set_sources(ids)

Every change logs and emits events.RULES so the windows refresh.
"""
from typing import Dict, Iterable, List, Optional, Set, Tuple

from ..core import events
from ..core.runtime import rt
from ..rules import catalog as CAT
from ..rules import custom_background as CB
from ..rules import engine as E
from ..rules import homebrew as HB
from ..rules import monster_gen as G
from ..rules import search as S
from ..rules.data import rules
from ..rules.leveling import RulesError
from ..rules.monsters import broad_type, bestiary
from .common import ServiceError

KINDS = ("monsters", "items")


def index(kind: str) -> S.Index:
    if kind not in KINDS:
        raise ServiceError(f"Can't search '{kind}'.")
    return S.monsters() if kind == "monsters" else S.items()


def search(kind: str, q: str = "", sets: Optional[Dict[str, Iterable[str]]] = None,
           ranges: Optional[Dict[str, Tuple[Optional[float], Optional[float]]]] = None, sort: Optional[str] = None,
           limit: int = 300) -> dict:
    """Rows, totals and facet counts for the search windows.

    {'total', 'rows': [...], 'facets': [{key, title, open, sorted_by_count, values: [[value, count, label]], chosen}],
     'numbers': [{key, title}], 'sorts': [...]}. Custom creatures and items come first so the CUSTOMS folder is never cut
    off."""
    idx = index(kind)
    flt = S.Filters()
    for k, vals in (sets or {}).items():
        if k in idx.facets and vals:
            flt.sets[k] = set(vals)
    for k, (lo, hi) in (ranges or {}).items():
        if k in idx.numbers:
            flt.ranges[k] = (None if lo in (None, "") else float(lo), None if hi in (None, "") else float(hi))
    rows = idx.search(q, flt, sort or ("cr" if kind == "monsters" else "name"))
    rows = [m for m in rows if m["source"] == "Custom"] + [m for m in rows if m["source"] != "Custom"]
    counts = idx.counts(q, flt)
    facets = []
    for f in idx.facet_list:
        chosen: Set[str] = flt.sets.get(f.key, set())
        c = counts[f.key]
        values = set(c) | chosen
        if f.order:
            order = {v: i for i, v in enumerate(f.order)}
            ranked = sorted(values, key=lambda v: (order.get(v, 99), v))
        else:
            ranked = sorted(values, key=lambda v: (-c.get(v, 0), v))
        facets.append({"key": f.key, "title": f.title, "open": f.open, "sorted_by_count": not f.order,
                       "values": [[v, c.get(v, 0), f.label(v)] for v in ranked[:400]], "chosen": sorted(chosen)})
    if kind == "monsters":
        out = [{"id": m["id"], "name": m["name"], "cr": m["cr"], "type": m["type"], "hp": m["hp"], "ac": m["ac"],
                "src": m["source"], "size": m["size"], "kind": broad_type(m["type"])} for m in rows[:limit]]
    else:
        out = [{"id": i["name"], "name": i["name"], "type": S.ITEM_TYPES.get(i["type"], i["type"]),
                "rarity": i["rarity"] if i["rarity"] != "none" else "mundane",
                "cost": f"{(i['value'] or 0) / 100:g} gp" if i["value"] else "-", "wt": f"{i.get('weight') or 0:g}",
                "src": i["source"], "cat": S.item_category(i)} for i in rows[:limit]]
    return {"total": len(rows), "rows": out, "facets": facets, "sorts": list(idx.sorts),
            "numbers": [{"key": n.key, "title": n.title} for n in idx.number_list]}


SEARCH_SYNTAX = """Search syntax
words            all must match (name, type, traits, text)
-word            exclude
"two words"      exact phrase
type:undead      field filter (any facet or number)
cr:>=5  cr:1/2-4 ranges for numbers (also hp, ac, xp, gp, weight)
-env:forest      negate a field"""


# ---------------------------------------------------------------------- choice lists for the content forms
def options() -> dict:
    """The lists the 'add content' forms choose from."""
    return {"classes": sorted(c["name"] for c in rules.class_list()), "skills": list(rules.skills), "tools": CB.tool_pool(),
            "languages": sorted({l["name"] for l in rules.offered(rules.languages) if l["type"] in ("standard", "exotic")}),
            "races": sorted(r["name"] for r in rules.race_list()), "abilities": [{"key": a, "name": E.ABILITY_NAMES[a]} for a in E.ABILITIES],
            "schools": HB.SCHOOLS, "damage_types": HB.DAMAGE_TYPES, "rarities": HB.RARITIES, "properties": HB.WEAPON_PROPERTIES,
            "item_types": {k: v for k, v in S.ITEM_TYPES.items() if k}, "option_types": HB.OPTION_TYPES,
            "language_types": HB.LANGUAGE_TYPES}


def proficiency_options() -> dict:
    return {"armor": ["light", "medium", "heavy", "shield"],
            "weapons": ["simple", "martial"] + sorted({w["name"].lower() for w in rules.weapons()}),
            "tools": CB.tool_pool(), "languages": rules.all_languages()}


# ---------------------------------------------------------------------- custom rulebooks
def _changed(message: str):
    from .battle import icons, itemsprites
    from ..rules import character
    icons.forget()                                     # a new homebrew item: its picture looked up afresh
    itemsprites.forget()                               # ...and its sprite on the battle maps
    character.forget_kept()                            # ...and the kept sheets' worked-out bonuses
    rt().log_action(message)
    rt().bus.emit(events.RULES)


def _rules(fn, *args):
    try:
        return fn(*args)
    except RulesError as e:
        raise ServiceError(str(e))


def save_book(name: str, description: str = "", book_id: Optional[str] = None) -> dict:
    book = _rules(HB.save_book, name, description, book_id or None)
    if not book_id:                                   # a new book is switched on straight away
        rt().set_sources(list(rules.active_sources) + [book["id"]])
    _changed(f"Rulebook saved: {book['name']}")
    return {"id": book["id"], "name": book["name"]}


def delete_book(book_id: str):
    name = HB.book(book_id)["name"]
    _rules(HB.delete_book, book_id)
    rt().set_sources([s for s in rules.active_sources if s != book_id])
    _changed(f"Rulebook deleted: {name}")


def set_book_active(book_id: str, on: bool):
    rt().set_sources([s for s in rules.active_sources if s != book_id] + ([book_id] if on else []))


def save_entry(book: str, kind: str, form: dict, original: Optional[str] = None) -> dict:
    e = _rules(HB.save_entry, book, kind, form or {}, original or None)
    _changed(f"Rulebook {book}: saved {e['name']}")
    return {"id": HB.entry_id(kind, e), "name": e["name"]}


def delete_entry(book: str, kind: str, ident: str):
    _rules(HB.delete_entry, book, kind, ident)
    _changed(f"Rulebook {book}: deleted {ident}")


# ---------------------------------------------------------------------- custom creatures (the monster generator)
def save_creature(spec: dict, original: Optional[str] = None, book: Optional[str] = None) -> dict:
    """Save to CUSTOMS, or into a custom rulebook when `book` is given."""
    if book:
        return save_entry(book, "monsters", spec, original)
    m = _rules(G.save, spec, original)
    _changed(f"Custom creature saved: {m['name']} (CR {m['cr']})")
    return {"id": m["id"], "name": m["name"]}


def delete_creature(ident: str):
    m = bestiary.get(ident) or {}
    if m.get("homebrew"):
        return delete_entry(m["source"], "monsters", ident)
    _rules(G.delete, ident)
    _changed(f"Custom creature deleted: {ident.split('|')[0]}")


# ---------------------------------------------------------------------- items made in the Item workshop
def save_item(form: dict, original: Optional[str] = None, book: Optional[str] = None) -> dict:
    """Save to CUSTOMS, or into a custom rulebook when `book` is given."""
    if book:
        return save_entry(book, "items", form, original)
    e = _rules(HB.save_custom_item, form or {}, original or None)
    _changed(f"Custom item saved: {e['name']}")
    return {"id": e["name"], "name": e["name"]}


def delete_item(name: str):
    i = rules.item(name) or {}
    if i.get("homebrew"):
        return delete_entry(i["source"], "items", i["name"])
    _rules(HB.delete_custom_item, name)
    _changed(f"Custom item deleted: {name}")


def item_is_custom(name: str) -> bool:
    """An item of CUSTOMS or of a custom rulebook (so it can be edited and deleted)."""
    i = rules.item(name) or {}
    return i.get("source") == CUSTOM_BOOK or bool(i.get("homebrew"))


def item_book(name: str) -> Optional[str]:
    """The custom rulebook an item belongs to (None: CUSTOMS, or a book's)."""
    i = rules.item(name) or {}
    return i["source"] if i.get("homebrew") else None


def item_form(name: str) -> dict:
    """The Item workshop's form for an item: the one it was made from, or one read off a book's item."""
    i = rules.item(name)
    if not i:
        raise ServiceError("Unknown item.")
    if isinstance(i.get("form"), dict):
        return {**blank_form("items"), **i["form"]}
    f = blank_form("items")
    f.update(name=i["name"], type=i["type"] if i["type"] in S.ITEM_TYPES else "G",
             rarity=i["rarity"] if i["rarity"] in HB.RARITIES else "none", magic=bool(i.get("magic")),
             cost=f"{(i.get('value') or 0) / 100:g}", weight=f"{i.get('weight') or 0:g}", text=str(i.get("text") or ""))
    if i.get("attune") is not None:
        f.update(attune=True, attune_by=str(i["attune"]) if i["attune"] is not True else "")
    if i.get("dmg1"):
        f.update(dmg1=i["dmg1"], dmg2=i.get("dmg2") or "", range=i.get("range") or "",
                 category="martial" if i.get("category") == "martial" else "simple",
                 dmg_type=i["dmg_type"] if i.get("dmg_type") in HB.DAMAGE_TYPES else "slashing",
                 properties=[p for p in (str(x).split("|")[0].lower() for x in i.get("properties") or []) if p in HB.WEAPON_PROPERTIES])
    if i.get("ac"):
        f.update(ac=str(i["ac"]), strength=str(i.get("strength") or ""), stealth=bool(i.get("stealth_disadvantage")))
    for key in ("bonus_weapon", "bonus_ac"):
        try:
            f[key] = max(0, min(3, int(str(i.get(key) or 0).lstrip("+"))))
        except ValueError:
            f[key] = 0
    return f


def item_preview(form: dict, where: str = "CUSTOMS") -> str:
    """The item card of an item being edited, `where` it is saved (a problem with the form raises a ServiceError)."""
    i = _rules(HB.build_item, form or {})
    return S.item_text({**i, "source": where})


def creature_preview(spec: dict) -> dict:
    """The stat block and CR check of a creature being edited."""
    from ..rules.monsters import statblock
    m = _rules(G.build, spec)
    return {"text": statblock(m), "check": G.cr_check(m), "hp": m["hp"], "hp_formula": m["hp_formula"],
            "target_hp": G.typical(m["cr"])["hp"], "prof": G.TABLE[m["cr"]]["prof"], "xp": m["xp"]}


# ---------------------------------------------------------------------- the Rules window: books, kinds, listings
ALL_BOOKS = CAT.ALL                                    # every enabled book at once
CUSTOM_BOOK = CAT.CUSTOM                               # what the generators made
CORE_BOOKS = ["PHB", "DMG", "MM"]
RULE_KINDS = CAT.KINDS                                 # [(kind, title)] in the order the Rules window shows them
ADDABLE = ("races", "subclasses", "backgrounds", "feats", "spells", "items", "monsters", "optional_features", "languages")
SINGULAR = {"races": "race", "classes": "class", "subclasses": "subclass", "backgrounds": "background", "feats": "feat",
            "spells": "spell", "items": "item", "monsters": "creature", "optional_features": "class option",
            "languages": "language"}
BOOK_SECTIONS = [("all", ""), ("homebrew", "Your rulebooks"), ("custom", "Made in the app"), ("module", "Modules"), ("core", "Core rules"),
                 ("supplement", "Supplements"), ("setting", "Settings"), ("adventure", "Adventures"), ("other", "Other")]


def _section(b: dict) -> str:
    if b.get("adventure"):
        return "adventure"
    g = b.get("group", "other")
    return g if g in ("all", "homebrew", "custom", "module", "core", "supplement", "setting") else "other"


def rule_books() -> List[dict]:
    """The books the Rules window lists (app.rules.catalog.overview), each with its 'section' (a key of BOOK_SECTIONS)
    and the 'total' number of entries."""
    return [{**b, "section": _section(b), "total": sum(b["counts"].values())} for b in CAT.overview()]


def rule_kinds(book: dict) -> List[Tuple[str, str, int]]:
    """[(kind, title, count)] a book offers: what it has, and for a custom rulebook everything that can be written."""
    return [(k, t, book["counts"].get(k, 0)) for k, t in RULE_KINDS
            if book["counts"].get(k) or (book.get("homebrew") and k in ADDABLE)]


def rule_listing(book_id: str, kind: str) -> dict:
    """{'rows': [{id, name, meta, src, homebrew, groups}], 'groupings': [{key, title, order}]} - see catalog.listing."""
    if kind not in CAT.SPEC:
        raise ServiceError(f"Unknown content type '{kind}'.")
    return CAT.listing(book_id, kind)


def lookup_entries() -> List[dict]:
    """Every entry of the enabled books (and the custom rulebooks and creatures), for a look-up line:
    [{kind, id, name, meta, what}] - `what` is the kind as one word ('Spell', 'Creature', 'Class option')."""
    out = []
    for kind, _title in RULE_KINDS:
        try:
            rows = CAT.listing(ALL_BOOKS, kind)["rows"]
        except Exception as e:                           # one broken kind leaves the others findable
            rt().log(f"[WARN] look-up: {kind} couldn't be listed: {e}")
            continue
        what = SINGULAR[kind][:1].upper() + SINGULAR[kind][1:]
        out.extend({"kind": kind, "id": r["id"], "name": r["name"], "meta": r.get("meta") or "", "what": what}
                   for r in rows)
    return out


def can_add(book: dict, kind: str) -> bool:
    return bool(book.get("homebrew")) and kind in ADDABLE


# ---------------------------------------------------------------------- sourcebooks (which books are offered)
SOURCE_SECTIONS = ["Your rulebooks", "Modules", "Core rules", "Supplements", "Settings", "Adventures", "Other"]


def sourcebook_sections() -> List[Tuple[str, List[dict]]]:
    """[(section title, [{id, name, group, adventure, homebrew, on}])] for the Sourcebooks window, books by name."""
    from .table import sources
    by: Dict[str, List[dict]] = {}
    for b in sources():
        title = "Adventures" if b["adventure"] else {"core": "Core rules", "supplement": "Supplements", "setting": "Settings",
                                                     "homebrew": "Your rulebooks", "module": "Modules"}.get(b["group"], "Other")
        by.setdefault(title, []).append(b)
    return [(t, sorted(by[t], key=lambda b: b["name"].lower())) for t in SOURCE_SECTIONS if t in by]


def set_sources(ids: Iterable[str]) -> int:
    """Switch on exactly these books (the core rules when none). Returns how many are on."""
    ids = list(dict.fromkeys(ids)) or list(CORE_BOOKS)
    rt().set_sources(ids)
    rt().log_action(f"Sourcebooks: {len(ids)} enabled")
    return len(ids)


# ---------------------------------------------------------------------- the 'add content' forms of a custom rulebook
# A field: {key, label, type: text|textarea|number|select|check|multi|entries|abilities, options: [(value, label)],
# default, required, rows, hint, search, level, decimal, show: {key: [values] | True}, hide: {key: [values]}}.
# content_fields(kind) is a list of rows; a row is a list of fields shown side by side. Labels are English.
_WEAPON, _ARMOR = {"type": ["M", "R"]}, {"type": ["LA", "MA", "HA", "S"]}
_SPELL_LEVELS = ["Cantrip"] + [f"{E.ordinal(n)} level" for n in range(1, 10)]


def _f(key: str, label: str, type: str = "text", **kw) -> dict:
    return {"key": key, "label": label, "type": type, **kw}


def _pairs(xs) -> list:
    return [(x, x) for x in xs]


def content_fields(kind: str) -> List[List[dict]]:
    o = options()
    ab = [(a["key"], a["name"]) for a in o["abilities"]]
    bonus = [(n, f"+{n}" if n else "none") for n in (0, 1, 2, 3)]
    forms = {
        "spells": [
            [_f("name", "Name", required=True)],
            [_f("level", "Level", "select", options=list(enumerate(_SPELL_LEVELS)), default=1),
             _f("school", "School", "select", options=_pairs(o["schools"]), default="Evocation")],
            [_f("casting_time", "Casting time", default="1 action"), _f("range", "Range", default="60 feet"),
             _f("duration", "Duration", default="Instantaneous")],
            [_f("v", "Verbal (V)", "check", default=True), _f("s", "Somatic (S)", "check", default=True),
             _f("concentration", "Concentration", "check"), _f("ritual", "Ritual", "check")],
            [_f("material", "Material component (leave empty for none)")],
            [_f("classes", "Spell lists (classes that can learn it)", "multi", options=_pairs(o["classes"]))],
            [_f("save", "Saving throw", "multi", options=_pairs(a["name"] for a in o["abilities"])),
             _f("damage", "Damage types", "multi", options=_pairs(o["damage_types"]))],
            [_f("text", "Description", "textarea", rows=7, required=True)],
            [_f("higher_level", "At higher levels", "textarea", rows=2)],
        ],
        "items": [
            [_f("name", "Name", required=True)],
            [_f("type", "Type", "select", options=list(o["item_types"].items()), default="G"),
             _f("rarity", "Rarity", "select", options=[(r, "Mundane" if r == "none" else r[0].upper() + r[1:]) for r in o["rarities"]],
                default="none")],
            [_f("cost", "Cost (gp)", "number", default=0, decimal=True), _f("weight", "Weight (lb)", "number", default=0, decimal=True)],
            [_f("magic", "Magic item", "check"), _f("attune", "Requires attunement", "check")],
            [_f("attune_by", 'Attunement only by… (e.g. "by a wizard"; empty = anyone)', show={"attune": True})],
            [_f("category", "Weapon class", "select", options=[("simple", "Simple"), ("martial", "Martial")], default="simple", show=_WEAPON),
             _f("dmg1", "Damage", default="1d6", show=_WEAPON),
             _f("dmg_type", "Damage type", "select", options=_pairs(o["damage_types"]), default="slashing", show=_WEAPON),
             _f("dmg2", "Two-handed (versatile)", show=_WEAPON)],
            [_f("properties", "Weapon properties", "multi", options=_pairs(o["properties"]), show=_WEAPON),
             _f("range", "Range (e.g. 80/320)", show=_WEAPON)],
            [_f("ac", "Armor Class", "number", default=11, show=_ARMOR), _f("strength", "Minimum Strength", "number", show=_ARMOR),
             _f("stealth", "Stealth disadvantage", "check", show=_ARMOR)],
            [_f("bonus_weapon", "Attack & damage bonus", "select", options=bonus, default=0, show=_WEAPON),
             _f("bonus_ac", "AC bonus", "select", options=bonus, default=0, hide=_WEAPON)],
            [_f("text", "Description", "textarea", rows=6)],
        ],
        "feats": [
            [_f("name", "Name", required=True)],
            [_f("pre_ability", "Prerequisite: ability score", "select", options=[("", "none")] + ab, default=""),
             _f("pre_score", "of at least", "number", default=13, show={"pre_ability": True}),
             _f("pre_level", "Minimum character level", "number", default=0)],
            [_f("pre_spellcasting", "Prerequisite: the ability to cast at least one spell", "check")],
            [_f("pre_race", "Prerequisite: race (any of)", "multi", options=_pairs(o["races"]), search=True)],
            [_f("ability_plus", "Ability score +1", "multi", options=ab,
                hint="Tick one for a fixed +1, or several to let the player pick one of them.")],
            [_f("text", "Description", "textarea", rows=8, required=True)],
        ],
        "races": [
            [_f("name", "Name", required=True), _f("size", "Size", "select", options=_pairs(["Small", "Medium"]), default="Medium")],
            [_f("walk", "Speed (ft)", "number", default=30), _f("fly", "Fly", "number"), _f("swim", "Swim", "number"),
             _f("climb", "Climb", "number"), _f("darkvision", "Darkvision (ft)", "number", default=0)],
            [_f("ab_", "Ability score increases", "abilities")],
            [_f("ab_choose", "Plus: abilities of the player's choice", "number", default=0),
             _f("ab_amount", "each raised by", "select", options=[(1, "+1"), (2, "+2")], default=1)],
            [_f("languages", "Languages", "multi", options=_pairs(o["languages"]), search=True),
             _f("languages_any", "Extra languages of choice", "number", default=0)],
            [_f("skills", "Skill proficiencies", "multi", options=_pairs(o["skills"])),
             _f("skills_any", "Skills of choice", "number", default=0)],
            [_f("resist", "Damage resistances", "multi", options=_pairs(o["damage_types"])),
             _f("feats", "Bonus feats at level 1", "number", default=0)],
            [_f("traits", "Traits", "entries")],
        ],
        "backgrounds": [
            [_f("name", "Name", required=True)],
            [_f("skills", "Skill proficiencies (usually two)", "multi", options=_pairs(o["skills"]))],
            [_f("tools", "Tool proficiencies", "multi", options=_pairs(o["tools"]), search=True),
             _f("tools_any", "Tools of choice", "number", default=0), _f("languages_any", "Languages of choice", "number", default=0)],
            [_f("feature_name", "Feature name")],
            [_f("feature_text", "Feature", "textarea", rows=3)],
            [_f("equipment", "Equipment (one per line)", "textarea", rows=4), _f("gp", "Gold in the pouch", "number", default=10)],
            [_f("text", "Description", "textarea", rows=3)],
        ],
        "subclasses": [
            [_f("class", "Class", "select", options=_pairs(o["classes"]), default=(o["classes"] or [""])[0]),
             _f("name", "Name", required=True)],
            [_f("features", "Features (the level is the class level that grants it)", "entries", level=True)],
        ],
        "optional_features": [
            [_f("kind", "Kind", "select", options=list(o["option_types"].items()), default="EI"), _f("name", "Name", required=True)],
            [_f("prerequisite", "Prerequisite (shown in the description)")],
            [_f("text", "Description", "textarea", rows=7, required=True)],
        ],
        "languages": [
            [_f("name", "Name", required=True),
             _f("type", "Kind", "select", options=_pairs(o["language_types"]), default="standard"), _f("script", "Script")],
        ],
    }
    if kind not in forms:
        raise ServiceError(f"There is no form for '{kind}'.")
    return forms[kind]


def field_shown(field: dict, form: dict) -> bool:
    """Whether a form field applies, given the values entered so far (weapon fields only for weapons...)."""
    def match(cond: dict) -> bool:
        return all(bool(form.get(k)) if want is True else str(form.get(k)) in {str(v) for v in want}
                   for k, want in cond.items())
    return (not field.get("show") or match(field["show"])) and (not field.get("hide") or not match(field["hide"]))


def blank_form(kind: str) -> dict:
    """The starting values of a form (its defaults)."""
    out: Dict[str, object] = {}
    for f in (f for r in content_fields(kind) for f in r):
        if f["type"] == "abilities":
            out.update({f["key"] + a: 0 for a in E.ABILITIES})
        elif f["type"] in ("multi", "entries"):
            out[f["key"]] = []
        else:
            out[f["key"]] = f.get("default", False if f["type"] == "check" else "")
    return out


def missing_field(kind: str, form: dict) -> Optional[str]:
    """The label of the first required field left empty (None when the form is complete)."""
    for f in (f for r in content_fields(kind) for f in r):
        if f.get("required") and not str(form.get(f["key"]) or "").strip():
            return f["label"]
    return None
