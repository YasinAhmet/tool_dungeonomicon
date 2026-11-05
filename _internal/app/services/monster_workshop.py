"""The creature workshop behind the generator window: starting points, the editor's small helpers and the lists its
pickers show. The numbers and texts themselves come from app.rules.monster_gen; saving goes through library.

    spec, original, book = start(edit_id="Thorn Brute|Custom")    # or copy_id="Goblin|MM", or neither (a blank CR 1)
    spec = set_cr(spec, "5")                                       # attacks, DCs, damage and HP follow
    feature_tree("bite", "actions")                                # [(cr, [(family, [feature index...])])]
    save(spec, original, book)                                     # -> {'id', 'name'}
"""
from typing import Dict, List, Optional, Tuple

from ..rules import homebrew as HB
from ..rules import monster_gen as G
from ..rules.monsters import broad_type, bestiary
from . import library
from .common import ServiceError

CASTING = ("int", "wis", "cha")
ATTACK_KINDS = ["melee", "ranged", "both", "melee spell", "spell"]
DICE = ["4", "6", "8", "10", "12"]

_options: Optional[dict] = None


def options() -> dict:
    """The generator's choice lists (CRs, types, roles...); loaded once."""
    global _options
    if _options is None:
        _options = G.options()
    return _options


# ---------------------------------------------------------------------- where an editing session starts
def start(edit_id: Optional[str] = None, copy_id: Optional[str] = None, book: Optional[str] = None,
          cr: str = "1") -> Tuple[dict, Optional[str], Optional[str]]:
    """(spec, original id, book). Editing a rulebook's creature saves it back into that rulebook."""
    ident = edit_id or copy_id
    if not ident:
        return G.blank_spec(cr), None, book
    m = bestiary.get(ident)
    if not m:
        raise ServiceError("Unknown monster.")
    spec = G.spec_from_monster(m)
    if edit_id:
        if m.get("homebrew"):
            book = book or m["source"]
        elif m.get("source") != "Custom":
            raise ServiceError("Only custom creatures can be edited; make a copy instead.")
        return spec, edit_id, book
    spec["name"] = spec["name"] + " (custom)"
    return spec, None, book


def is_custom(ident: str) -> bool:
    """A creature of CUSTOMS or of a custom rulebook (so it can be edited and deleted)."""
    m = bestiary.get(ident) or {}
    return m.get("source") == "Custom" or bool(m.get("homebrew"))


def book_name(book: Optional[str]) -> str:
    return HB.book(book)["name"] if book else "CUSTOMS"


def books() -> List[Tuple[str, str]]:
    """(name, id) of every custom rulebook."""
    return [(b["name"], b["id"]) for b in HB.books()]


# ---------------------------------------------------------------------- the editor's helpers
def set_cr(spec: dict, cr: str) -> dict:
    """A new CR: attack bonuses, DCs, damage and hit dice follow."""
    old = spec.get("cr") or "1"
    return G.rescale_spec(dict(spec, cr=cr), old)


def renamed(spec: dict, old_name: str) -> dict:
    """After a rename: the old name in every entry becomes the new one."""
    return G.rescale_spec(spec, spec.get("cr") or "1", old_name)


def fit_hit_dice(spec: dict) -> int:
    """Hit dice that give the typical HP of the creature's CR (from the printed monsters)."""
    s = G.clean(spec)
    per = (G.HIT_DIE[s["size"]] + 1) / 2 + G.mod(s["abilities"]["con"])
    return max(1, min(99, round(G.typical(s["cr"])["hp"] / max(1, per))))


def multiattack(spec: dict) -> dict:
    return {"name": "Multiattack", "text": f"The {(spec.get('name') or 'creature').lower()} makes two attacks."}


def attack_defaults(spec: dict) -> dict:
    ab = spec["abilities"]
    return {"name": "Claw", "kind": "melee", "ability": "dex" if G.mod(ab["dex"]) > G.mod(ab["str"]) else "str",
            "dice": 1, "die": "8", "dtype": "slashing", "reach": 5, "range": "80/320", "extra_n": 0, "extra_die": "6",
            "extra_type": "fire", "text": ""}


def spell_setup(spec: dict, entry: Optional[dict] = None, mode: str = "slots") -> dict:
    """The spell picker's starting choices: the entry's own, read back from its text, or a new list."""
    if entry and entry.get("setup"):
        return G.clean_setup(entry["setup"])
    if entry:
        st = G.parse_spellcasting(entry)
        st.pop("missed", None)
        return st
    best = max(CASTING, key=lambda a: (spec["abilities"][a], -CASTING.index(a)))
    return {"mode": mode, "ability": best, "level": 0, "class_name": "", "spells": []}


def spellcasting_groups(setup: dict) -> List[Tuple[str, List[str]]]:
    """A setup's spells by level (slots) or by uses per day (innate), for showing it in the editor."""
    st = G.clean_setup(setup)
    if st["mode"] == "innate":
        return [(u, names) for u in G.INNATE_USES
                for names in [[e["name"] for e in st["spells"] if e["uses"] == u]] if names]
    levels = {s["name"]: s["level"] for s in G.spell_list()}
    out = []
    for lv in range(10):
        names = [e["name"] for e in st["spells"] if levels.get(e["name"], 0) == lv]
        if names:
            out.append(("Cantrips" if lv == 0 else f"Level {lv}", names))
    return out


def save(spec: dict, original: Optional[str] = None, book: Optional[str] = None) -> dict:
    if not str(spec.get("name") or "").strip():
        raise ServiceError("Give the creature a name.")
    return library.save_creature(spec, original, book)


# ---------------------------------------------------------------------- the feature library
def family_of(creature_type: str) -> str:
    return broad_type(str(creature_type or ""))


def feature_tree(query: str = "", section: str = "") -> Tuple[int, List[Tuple[str, List[Tuple[str, List[int]]]]]]:
    """(matches, [(cr, [(family, [feature index])])]) in CR order, families by name."""
    needle = query.strip().lower()
    tree: Dict[str, Dict[str, List[int]]] = {}
    n = 0
    for i, (name, sec, cr, fam, mon) in enumerate(G.feature_rows()):
        if section and sec != section:
            continue
        if needle and needle not in name.lower() and needle not in mon.lower():
            continue
        n += 1
        tree.setdefault(cr, {}).setdefault(fam, []).append(i)
    return n, [(cr, sorted(tree[cr].items())) for cr in G.CR_STEPS if cr in tree]


def feature_row(i: int) -> list:
    """[name, section, cr, family, creature] of one library feature."""
    return G.feature_rows()[i]


# ---------------------------------------------------------------------- the spell picker
def spell_classes() -> List[str]:
    return sorted({c for s in G.spell_list() for c in s["classes"]})


def find_spells(query: str = "", level: Optional[int] = None, cls: str = "", damage: bool = False) -> List[dict]:
    needle = query.strip().lower()
    return [s for s in G.spell_list()
            if (not needle or needle in s["name"].lower() or needle in s["school"].lower())
            and (level is None or s["level"] == level) and (not cls or cls in s["classes"]) and (not damage or s["damage"])]


def spell_levels() -> Dict[str, int]:
    return {s["name"]: s["level"] for s in G.spell_list()}


def default_uses(level: int) -> str:
    """How often an innate spell is cast when it is first picked."""
    return "at will" if level == 0 else "3/day" if level <= 3 else "1/day"
