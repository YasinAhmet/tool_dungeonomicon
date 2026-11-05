"""The enemy generator: quick generation from a few choices (CR, type, role...), a full manual editor spec, a library of
every trait/action in the bestiary (by CR and creature family) that can be borrowed and rescaled, and saving the
result as a custom monster (data/custom_monsters/<name>.json, source "Custom") that the Battle page lists under CUSTOMS.

A *spec* is the editable form of a monster (hit dice instead of HP, proficient saves/skills instead of their bonuses...);
`build()` turns it into a normal bestiary record, and the record keeps its spec so it can be edited again.
"""
import math
import os
import random
import re
from statistics import median
from typing import Dict, List, Optional, Tuple

from . import engine as E
from .data import rules
from .leveling import RulesError
from .monsters import CR_STEPS, CUSTOM_DIR, _cr, bestiary, broad_type
from ..core.storage import write_json

SIZES = ["Tiny", "Small", "Medium", "Large", "Huge", "Gargantuan"]
HIT_DIE = {"Tiny": 4, "Small": 6, "Medium": 8, "Large": 10, "Huge": 12, "Gargantuan": 20}
TYPES = ["aberration", "beast", "celestial", "construct", "dragon", "elemental", "fey", "fiend", "giant", "humanoid",
         "monstrosity", "ooze", "plant", "undead"]
DAMAGE = ["acid", "bludgeoning", "cold", "fire", "force", "lightning", "necrotic", "piercing", "poison", "psychic",
          "radiant", "slashing", "thunder"]
PHYSICAL = ["bludgeoning", "piercing", "slashing"]
CONDITIONS = ["blinded", "charmed", "deafened", "exhaustion", "frightened", "grappled", "incapacitated", "paralyzed",
              "petrified", "poisoned", "prone", "restrained", "stunned", "unconscious"]
SECTIONS = {"traits": "Traits", "actions": "Actions", "bonus_actions": "Bonus actions", "reactions": "Reactions",
            "legendary": "Legendary actions"}
ABILITY_NAMES = {"str": "Strength", "dex": "Dexterity", "con": "Constitution", "int": "Intelligence", "wis": "Wisdom", "cha": "Charisma"}
ROLES = {
    "brute": "Brute - big hits, lots of HP, low AC",
    "skirmisher": "Skirmisher - fast and slippery, hit and run",
    "defender": "Defender - high AC, protects others",
    "artillery": "Artillery - attacks from range",
    "spellcaster": "Spellcaster - fragile, casts spells",
    "controller": "Controller - saves and conditions",
    "leader": "Leader - commands and boosts allies",
    "boss": "Solo boss - legendary actions and resistances",
}
THEMES = ["none", "fire", "cold", "lightning", "acid", "poison", "necrotic", "radiant", "thunder", "psychic", "force"]
MOBILITY = ["auto", "walker", "flyer", "swimmer", "climber", "burrower"]

# DMG "Monster Statistics by Challenge Rating": proficiency, AC, HP range, attack bonus, damage per round range, save DC
_TABLE = [("0", 2, 13, 1, 6, 3, 0, 1, 13), ("1/8", 2, 13, 7, 35, 3, 2, 3, 13), ("1/4", 2, 13, 36, 49, 3, 4, 5, 13),
          ("1/2", 2, 13, 50, 70, 3, 6, 8, 13), ("1", 2, 13, 71, 85, 3, 9, 14, 13), ("2", 2, 13, 86, 100, 3, 15, 20, 13),
          ("3", 2, 13, 101, 115, 4, 21, 26, 13), ("4", 2, 14, 116, 130, 5, 27, 32, 14), ("5", 3, 15, 131, 145, 6, 33, 38, 15),
          ("6", 3, 15, 146, 160, 6, 39, 44, 15), ("7", 3, 15, 161, 175, 6, 45, 50, 15), ("8", 3, 16, 176, 190, 7, 51, 56, 16),
          ("9", 4, 16, 191, 205, 7, 57, 62, 16), ("10", 4, 17, 206, 220, 7, 63, 68, 16), ("11", 4, 17, 221, 235, 8, 69, 74, 17),
          ("12", 4, 17, 236, 250, 8, 75, 80, 17), ("13", 5, 18, 251, 265, 8, 81, 86, 18), ("14", 5, 18, 266, 280, 8, 87, 92, 18),
          ("15", 5, 18, 281, 295, 8, 93, 98, 18), ("16", 5, 18, 296, 310, 9, 99, 104, 18), ("17", 6, 19, 311, 325, 10, 105, 110, 19),
          ("18", 6, 19, 326, 340, 10, 111, 116, 19), ("19", 6, 19, 341, 355, 10, 117, 122, 19), ("20", 6, 19, 356, 400, 10, 123, 140, 19),
          ("21", 7, 19, 401, 445, 11, 141, 158, 20), ("22", 7, 19, 446, 490, 11, 159, 176, 20), ("23", 7, 19, 491, 535, 11, 177, 194, 20),
          ("24", 7, 19, 536, 580, 12, 195, 212, 21), ("25", 8, 19, 581, 625, 12, 213, 230, 21), ("26", 8, 19, 626, 670, 12, 231, 248, 21),
          ("27", 8, 19, 671, 715, 13, 249, 266, 22), ("28", 8, 19, 716, 760, 13, 267, 284, 22), ("29", 9, 19, 761, 805, 13, 285, 302, 22),
          ("30", 9, 19, 806, 850, 14, 303, 320, 23)]
TABLE = {r[0]: dict(prof=r[1], ac=r[2], hp=(r[3], r[4]), atk=r[5], dmg=(r[6], r[7]), dc=r[8]) for r in _TABLE}
XP = dict(zip(CR_STEPS, [10, 25, 50, 100, 200, 450, 700, 1100, 1800, 2300, 2900, 3900, 5000, 5900, 7200, 8400, 10000, 11500,
                         13000, 15000, 18000, 20000, 22000, 25000, 33000, 41000, 50000, 62000, 75000, 90000, 105000, 120000,
                         135000, 155000]))
NUMBER_WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6}


def cr_text(cr) -> str:
    cr = str(cr).strip()
    if cr not in TABLE:
        raise RulesError(f"Unknown challenge rating '{cr}'.")
    return cr


def dpr(cr: str) -> float:
    lo, hi = TABLE[cr]["dmg"]
    return max(1.0, (lo + hi) / 2)


def mod(score) -> int:
    return E.modifier(int(score))


def signed(n: int) -> str:
    return f"{n:+d}"


def dice_avg(n: int, die: int, bonus: int = 0) -> int:
    return max(1, int(n * (die + 1) / 2 + bonus))


def dice_text(n: int, die: int, bonus: int = 0) -> str:
    return f"{n}d{die}" + (f" + {bonus}" if bonus > 0 else f" - {-bonus}" if bonus < 0 else "")


def ordinal(n: int) -> str:
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


# ====================================================================== typical stats measured from the bestiary
_typical: Dict[str, dict] = {}


def typical(cr: str) -> dict:
    """What the printed monsters of a CR are like: median effective HP, AC, damage per round and attack bonus.
    (The DMG table's HP runs far above the books' own monsters, so the CR check compares with these instead.)"""
    if not _typical:
        keys = ("hp", "ac", "dpr", "atk")
        by: Dict[str, Dict[str, list]] = {c: {k: [] for k in keys} for c in CR_STEPS}
        for m in bestiary.all:
            if m.get("source") == "Custom" or m.get("homebrew") or m["cr"] not in by or not m["hp"]:
                continue
            off = offense(m)
            if off["dpr"] <= 0:
                continue
            row = by[m["cr"]]
            row["hp"].append(effective_hp(m))
            row["ac"].append(m["ac"])
            row["dpr"].append(off["dpr"])
            if off["atk"] is not None:
                row["atk"].append(off["atk"])
        fallback = lambda c: {"hp": sum(TABLE[c]["hp"]) / 2, "ac": TABLE[c]["ac"], "dpr": dpr(c), "atk": TABLE[c]["atk"]}
        prev = None
        for c in CR_STEPS:
            vals = by[c]
            t = {k: median(vals[k]) if len(vals[k]) >= 4 else fallback(c)[k] for k in keys}
            if prev:                                      # keep every column rising with CR (few monsters at some CRs)
                t = {k: max(t[k], prev[k] * (1.04 if k in ("hp", "dpr") else 1)) for k in keys}
            _typical[c] = prev = t
    return _typical[cr]


def _nearest(value: float, key: str) -> int:
    """The CR step whose typical `key` is closest (on a ratio scale)."""
    value = max(0.5, value)
    return min(range(len(CR_STEPS)), key=lambda i: abs(math.log(value / max(0.5, typical(CR_STEPS[i])[key]))))


_common: Optional[set] = None


def is_proper(name: str) -> bool:
    """'Grishnak' is a proper name ('Grishnak attacks'); 'Mage' or 'Goblin' is not ('the mage attacks')."""
    global _common
    if _common is None:
        _common = {m["name"].lower() for m in bestiary.all if m.get("source") != "Custom" and not m.get("homebrew")} | set(TYPES)
    return " " not in name.strip() and name.strip().lower() not in _common


def ref(name: str, capital: bool = False) -> str:
    """How the stat block text calls the creature."""
    r = name if is_proper(name) else f"{'T' if capital else 't'}he {name.lower()}"
    return r


def a_an(word: str) -> str:
    return ("an " if word[:1] in "8aeiou" or word.startswith(("11", "18")) else "a ") + word


# ====================================================================== spec -> monster record
def blank_spec(cr: str = "1") -> dict:
    return {"name": "", "size": "Medium", "type": "humanoid", "tags": "", "alignment": "unaligned", "cr": cr,
            "ac": 12, "ac_note": "", "hit_dice": 4, "speed": {"walk": 30, "burrow": 0, "climb": 0, "fly": 0, "swim": 0, "hover": False},
            "abilities": {a: 10 for a in E.ABILITIES}, "save_profs": [], "skill_profs": [], "skill_expert": [],
            "resist": [], "immune": [], "vulnerable": [], "nonmagical": False, "condition_immune": [],
            "senses": {"blindsight": 0, "darkvision": 0, "tremorsense": 0, "truesight": 0}, "languages": "—",
            "environment": [], "traits": [], "spellcasting": [], "actions": [], "bonus_actions": [], "reactions": [],
            "legendary": [], "legendary_count": 3, "lair": "", "description": "", "portrait": {}}


def _num(v, default=0, lo=-10 ** 6, hi=10 ** 6) -> int:
    try:
        return max(lo, min(hi, int(float(v))))
    except (TypeError, ValueError):
        return default


def clean(spec: dict) -> dict:
    """Fill in missing keys and coerce types, so the builder can trust the spec."""
    out = blank_spec()
    for k in out:
        if k in spec and spec[k] is not None:
            out[k] = spec[k]
    out["name"] = re.sub(r"\s+", " ", str(out["name"])).strip()
    out["cr"] = cr_text(out["cr"])
    out["size"] = out["size"] if out["size"] in SIZES else "Medium"
    out["type"] = str(out["type"]).strip().lower() or "humanoid"
    for k in ("tags", "alignment", "ac_note", "languages", "lair", "description"):
        out[k] = str(out[k] or "").strip()
    out["ac"] = _num(out["ac"], 10, 1, 40)
    out["hit_dice"] = _num(out["hit_dice"], 1, 1, 99)
    out["legendary_count"] = _num(out["legendary_count"], 3, 1, 5)
    sp = dict(blank_spec()["speed"], **(spec.get("speed") or {}))
    out["speed"] = {k: (bool(v) if k == "hover" else _num(v, 0, 0, 300)) for k, v in sp.items() if k in blank_spec()["speed"]}
    out["abilities"] = {a: _num((spec.get("abilities") or {}).get(a), 10, 1, 30) for a in E.ABILITIES}
    out["senses"] = {k: _num((spec.get("senses") or {}).get(k), 0, 0, 1000) for k in blank_spec()["senses"]}
    out["save_profs"] = [a for a in E.ABILITIES if a in (out["save_profs"] or [])]
    out["skill_profs"] = sorted(s for s in set(out["skill_profs"] or []) if s in rules.skills)
    out["skill_expert"] = sorted(s for s in set(out["skill_expert"] or []) if s in out["skill_profs"])
    for k in ("resist", "immune", "vulnerable"):
        out[k] = [d for d in DAMAGE if d in (out[k] or [])]
    out["nonmagical"] = bool(out["nonmagical"])
    out["condition_immune"] = [c for c in CONDITIONS if c in (out["condition_immune"] or [])]
    out["environment"] = [str(e).strip() for e in (out["environment"] or []) if str(e).strip()]
    keep = lambda e: isinstance(e, dict) and (str(e.get("name", "")).strip() or str(e.get("text", "")).strip() or e.get("setup"))
    for k in list(SECTIONS) + ["spellcasting"]:
        out[k] = [dict({"name": str(e.get("name", "")).strip(), "text": str(e.get("text", "")).strip()},
                       **({"setup": e["setup"]} if k == "spellcasting" and isinstance(e.get("setup"), dict) else {}))
                  for e in (out[k] or []) if keep(e)]
    p = out["portrait"]                                  # {} or core/portraits' {'file', 'framed', 'inner', 'border'}
    out["portrait"] = {k: p[k] for k in ("file", "framed", "inner", "border") if k in p} \
        if isinstance(p, dict) and isinstance(p.get("file"), str) else {}
    return out


def hit_points(spec: dict) -> Tuple[int, str]:
    n, die, con = spec["hit_dice"], HIT_DIE[spec["size"]], mod(spec["abilities"]["con"])
    return max(1, int(n * (die + 1) / 2) + n * con), dice_text(n, die, n * con)


def _speed_text(sp: dict) -> str:
    parts = [f"{sp['walk']} ft."]
    for k in ("burrow", "climb", "fly", "swim"):
        if sp.get(k):
            parts.append(f"{k} {sp[k]} ft." + (" (hover)" if k == "fly" and sp.get("hover") else ""))
    return ", ".join(parts)


def _damage_text(kinds: List[str], nonmagical: bool) -> str:
    phys = [d for d in PHYSICAL if d in kinds] if nonmagical else []
    rest = [d for d in kinds if d not in phys]
    out = ", ".join(rest)
    if phys:
        tail = (", ".join(phys[:-1]) + (", and " if len(phys) > 2 else " and ") + phys[-1]) if len(phys) > 1 else phys[0]
        out = (out + "; " if out else "") + tail + " from nonmagical attacks"
    return out


def skill_bonus(spec: dict, skill: str) -> int:
    prof = TABLE[spec["cr"]]["prof"]
    return mod(spec["abilities"][rules.skills[skill]["ability"]]) + prof * (2 if skill in spec["skill_expert"] else 1)


def build(spec: dict) -> dict:
    """A bestiary record (the same shape as monsters.json) from a spec."""
    s = clean(spec)
    s["spellcasting"] = [spellcasting_entry(s, e["setup"]) if e.get("setup") else e for e in s["spellcasting"]]   # DC and bonus follow the stats
    name = s["name"] or "Unnamed creature"
    prof = TABLE[s["cr"]]["prof"]
    ab = s["abilities"]
    hp, formula = hit_points(s)
    perception = skill_bonus(s, "Perception") if "Perception" in s["skill_profs"] else mod(ab["wis"])
    senses = ", ".join(f"{k} {v} ft." for k, v in s["senses"].items() if v)
    legendary = s["legendary"]
    who = ref(name, True)
    note = (f"{who} can take {s['legendary_count']} legendary actions, choosing from the options below. "
            f"Only one legendary action option can be used at a time and only at the end of another creature's turn. "
            f"{who} regains spent legendary actions at the start of its turn.") if legendary else ""
    flags = []
    if s["spellcasting"] or any("spellcasting" in t["name"].lower() for t in s["traits"]):
        flags.append("spellcaster")
    if s["speed"]["fly"]:
        flags.append("flies")
    if s["speed"]["swim"]:
        flags.append("swims")
    if legendary:
        flags.append("legendary")
    return {
        "name": name, "source": "Custom", "size": s["size"], "type": s["type"],
        "tags": [t.strip() for t in s["tags"].split(",") if t.strip()], "alignment": s["alignment"] or "unaligned",
        "ac": s["ac"], "ac_note": s["ac_note"], "hp": hp, "hp_formula": formula, "speed": _speed_text(s["speed"]),
        "abilities": dict(ab), "saves": ", ".join(f"{a.title()} {signed(mod(ab[a]) + prof)}" for a in s["save_profs"]),
        "skills": ", ".join(f"{k} {signed(skill_bonus(s, k))}" for k in s["skill_profs"]),
        "resist": _damage_text(s["resist"], s["nonmagical"]), "immune": _damage_text(s["immune"], s["nonmagical"]),
        "vulnerable": ", ".join(s["vulnerable"]), "condition_immune": ", ".join(s["condition_immune"]),
        "senses": senses, "passive": 10 + perception, "languages": s["languages"] or "—",
        "cr": s["cr"], "cr_num": _cr(s["cr"]), "xp": XP[s["cr"]] if s["cr"] != "0" else 10,
        "environment": s["environment"], "traits": s["traits"], "spellcasting": s["spellcasting"], "actions": s["actions"],
        "bonus_actions": s["bonus_actions"], "reactions": s["reactions"], "legendary": legendary, "legendary_note": note,
        "lair": s["lair"], "flags": flags, "id": f"{name}|Custom", "description": s["description"], "spec": s,
        "portrait": dict(s["portrait"]),
    }


# ====================================================================== reading a printed monster back into a spec
def spec_from_monster(m: dict) -> dict:
    if m.get("spec"):
        return clean(m["spec"])
    s = blank_spec(m["cr"] if m["cr"] in TABLE else "1")
    prof = TABLE[s["cr"]]["prof"]
    s.update(name=m["name"], size=m["size"].split("/")[0], type=m["type"], tags=", ".join(m["tags"]), alignment=m["alignment"],
             ac=m["ac"], ac_note=m["ac_note"], abilities=dict(m["abilities"]), languages=m["languages"],
             environment=list(m["environment"]), lair=m["lair"], description=bestiary.lore(m["id"]))
    die, con = HIT_DIE.get(s["size"], 8), mod(m["abilities"]["con"])
    f = re.match(r"\s*(\d+)d", m.get("hp_formula") or "")
    s["hit_dice"] = int(f.group(1)) if f else max(1, round(m["hp"] / max(1, (die + 1) / 2 + con)))
    for k in ("walk", "burrow", "climb", "fly", "swim"):
        hit = re.search(rf"{'' if k == 'walk' else k + ' '}(\d+) ft", m["speed"]) if k != "walk" else re.match(r"\s*(\d+) ft", m["speed"])
        s["speed"][k] = int(hit.group(1)) if hit else 0
    s["speed"]["hover"] = "hover" in m["speed"]
    s["save_profs"] = [a for a in E.ABILITIES if re.search(rf"\b{a}\b", m["saves"], re.I)]
    for part in filter(None, (p.strip() for p in m["skills"].split(","))):
        hit = re.match(r"(.+?)\s*([+-]\d+)", part)
        if hit and hit.group(1).strip().title() in {k.title(): k for k in rules.skills}:
            skill = {k.title(): k for k in rules.skills}[hit.group(1).strip().title()]
            s["skill_profs"].append(skill)
            if int(hit.group(2)) >= mod(m["abilities"][rules.skills[skill]["ability"]]) + 2 * prof:
                s["skill_expert"].append(skill)
    for k in ("resist", "immune", "vulnerable"):
        s[k] = [d for d in DAMAGE if d in m[k].lower()]
    s["nonmagical"] = "nonmagical" in (m["resist"] + m["immune"]).lower()
    s["condition_immune"] = [c for c in CONDITIONS if c in m["condition_immune"].lower()]
    for k in s["senses"]:
        hit = re.search(rf"{k} (\d+) ft", m["senses"])
        s["senses"][k] = int(hit.group(1)) if hit else 0
    for k in list(SECTIONS) + ["spellcasting"]:
        s[k] = [dict(name=e["name"], text=e["text"]) for e in m[k]]
    for e in s["spellcasting"]:
        st = parse_spellcasting(e)
        if st["spells"] and not st.pop("missed"):          # only when every listed spell is in the library
            e["setup"] = st
    hit = re.search(r"can take (\d+) legendary", m.get("legendary_note") or "")
    s["legendary_count"] = int(hit.group(1)) if hit else 3
    return clean(s)


# ====================================================================== rescaling borrowed text to another CR / name
_DMG = re.compile(r"(\d+) \((\d+)d(\d+)(?:\s*([+-−])\s*(\d+))?\)")


def _names_of(old: str, kind: str = "") -> List[str]:
    """How a stat block may call its creature: 'the young red dragon', 'the dragon', 'Andir'..."""
    base = re.sub(r"\(.*?\)", "", old).split(",")[0].strip()
    words = [w for w in re.findall(r"[A-Za-z'-]+", base) if len(w) > 3]
    out = {old, base, *words, *(w for w in re.findall(r"[a-z]+", kind.lower()) if len(w) > 3)}
    return sorted((o for o in out if o), key=len, reverse=True)


def _rename(text: str, old: str, new: str, kind: str = "") -> str:
    if not old or not new or old == new:
        return text
    for o in _names_of(old, kind):
        text = re.sub(rf"\b([Tt])he {re.escape(o.lower())}\b", lambda mt: new if is_proper(new) else f"{mt.group(1)}he {new.lower()}", text)
        if o[:1].isupper():                                # a named NPC: 'Gristle adds 2' -> 'The ogre brute adds 2'
            text = re.sub(rf"(?<![Tt]he )\b{re.escape(o)}\b", ref(new), text)
    return re.sub(r"(^|[.!?]\s+|\n)the ", lambda mt: mt.group(1) + "The ", text)


def _borrow(f: dict, cr: str, name: str) -> str:
    src = bestiary.get(f["mon"]) or {"name": "", "type": ""}
    return rescale(f["text"], f["cr"], cr, src["name"], name, src.get("type", ""))


_ATTACK_REF = re.compile(r"\b(?:with (?:its|a|an|one)|one|its|a|an) ([a-z]+) attack", re.I)
_GENERIC = {"weapon", "melee", "ranged", "spell", "opportunity", "sneak", "single", "unarmed", "extra", "legendary", "one", "the"}


def _fits(f: dict, s: dict, name: str) -> bool:
    """A borrowed trait must be about the creature (its name got swapped in) and name only attacks it really has."""
    text = _borrow(f, s["cr"], name)
    if "\n" in f["text"] or name.lower() not in text.lower():
        return False
    if re.search(r"(?:wearing|wears) no armor|unarmored", text, re.I) and s["ac_note"] and "natural" not in s["ac_note"]:
        return False
    have = " ".join(e["name"].lower() for e in s["actions"])
    return all(w.lower() in _GENERIC or w.lower() in have for w in _ATTACK_REF.findall(text))


def rescale(text: str, from_cr: str, to_cr: str, old_name: str = "", new_name: str = "", kind: str = "") -> str:
    """Move attack bonuses, save DCs and damage dice from one CR's budget to another's, and swap the creature's name."""
    text = _rename(text, old_name, new_name, kind)
    if from_cr not in TABLE or to_cr not in TABLE or from_cr == to_cr:
        return text
    a, b = TABLE[from_cr], TABLE[to_cr]
    text = re.sub(r"([+-]\d+) to hit", lambda mt: f"{signed(int(mt.group(1)) + b['atk'] - a['atk'])} to hit", text)
    text = re.sub(r"\bDC (\d+)", lambda mt: f"DC {max(8, int(mt.group(1)) + b['dc'] - a['dc'])}", text)
    f = typical(to_cr)["dpr"] / typical(from_cr)["dpr"]
    if not 0.85 <= f <= 1.15:
        def dmg(mt):
            n, die = int(mt.group(2)), int(mt.group(3))
            bonus = int(mt.group(5) or 0) * (-1 if mt.group(4) in ("-", "−") else 1)
            n2 = max(1, round(n * f))
            return f"{dice_avg(n2, die, bonus)} ({dice_text(n2, die, bonus)})"
        text = _DMG.sub(dmg, text)
    return text


# ====================================================================== the feature library (every trait/action of the bestiary)
_features: Optional[tuple] = None                    # (the books it was made for, the list)


def features() -> List[dict]:
    """Deduplicated by name within each CR and creature family; refreshed when custom monsters change."""
    global _features
    if _features is None or _features[0] != rules.active_sources:
        seen, out = set(), []
        for m in sorted(bestiary.offered(), key=lambda m: (m["cr_num"], m["name"])):
            fam = broad_type(m["type"])
            for sec in SECTIONS:
                for e in m[sec]:
                    if not e["name"] or e["name"].lower() == "multiattack":
                        continue
                    key = (e["name"].lower(), sec, m["cr"], fam)
                    if key in seen:
                        continue
                    seen.add(key)
                    out.append({"name": e["name"], "sec": sec, "cr": m["cr"], "fam": fam, "mon": m["id"], "text": e["text"]})
        _features = (rules.active_sources, out)
    return _features[1]


def feature_rows() -> List[list]:
    return [[f["name"], f["sec"], f["cr"], f["fam"], f["mon"].split("|")[0]] for f in features()]


def feature_text(i: int) -> str:
    f = features()[i]
    return f"{SECTIONS[f['sec']][:-1]} of {f['mon'].split('|')[0]} (CR {f['cr']})\n\n{f['text']}"


def adapt_feature(i: int, spec: dict) -> dict:
    """A library feature rewritten for this creature: its name, its CR's attack bonus, DCs and damage."""
    f = features()[i]
    s = clean(spec)
    return {"sec": f["sec"], "name": f["name"], "text": _borrow(f, s["cr"], s["name"] or "creature")}


def rescale_spec(spec: dict, from_cr: str, old_name: str = "") -> dict:
    """After the CR (or name) changed in the editor: every entry follows."""
    s = clean(spec)
    for k in list(SECTIONS) + ["spellcasting"]:
        for e in s[k]:
            e["text"] = rescale(e["text"], from_cr, s["cr"], old_name, s["name"])
    if from_cr in TABLE and from_cr != s["cr"]:          # hit points follow too
        s["hit_dice"] = max(1, min(99, round(s["hit_dice"] * typical(s["cr"])["hp"] / typical(from_cr)["hp"])))
    return s


def invalidate():
    global _features
    _features = None


# ====================================================================== attacks
def attack_entry(spec: dict, a: dict) -> dict:
    """{name, kind: melee|ranged|both, ability: str|dex|..., dice: n, die: m, dtype, reach, range, extra_n, extra_die, extra_type, text}."""
    s = clean(spec)
    prof = TABLE[s["cr"]]["prof"]
    am = mod(s["abilities"].get(a.get("ability") or "str", 10))
    n, die = _num(a.get("dice"), 1, 1, 40), _num(a.get("die"), 6, 1, 20)
    kind = a.get("kind") or "melee"
    reach, rng = _num(a.get("reach"), 5, 5, 60), str(a.get("range") or "80/320").strip()
    how = {"melee": f"Melee Weapon Attack: {signed(am + prof)} to hit, reach {reach} ft., one target.",
           "ranged": f"Ranged Weapon Attack: {signed(am + prof)} to hit, range {rng} ft., one target.",
           "both": f"Melee or Ranged Weapon Attack: {signed(am + prof)} to hit, reach {reach} ft. or range {rng} ft., one target.",
           "spell": f"Ranged Spell Attack: {signed(am + prof)} to hit, range {rng.split('/')[0]} ft., one target.",
           "melee spell": f"Melee Spell Attack: {signed(am + prof)} to hit, reach {reach} ft., one target."}.get(kind)
    if not how:
        raise RulesError("Unknown attack kind.")
    bonus = 0 if "spell" in kind else am
    text = f"{how} Hit: {dice_avg(n, die, bonus)} ({dice_text(n, die, bonus)}) {a.get('dtype') or 'bludgeoning'} damage"
    en = _num(a.get("extra_n"), 0, 0, 40)
    if en and a.get("extra_type"):
        ed = _num(a.get("extra_die"), 6, 1, 20)
        text += f" plus {dice_avg(en, ed)} ({dice_text(en, ed)}) {a['extra_type']} damage"
    text += "." + (" " + str(a.get("text")).strip() if str(a.get("text") or "").strip() else "")
    return {"name": str(a.get("name") or "Attack").strip(), "text": text}


# ====================================================================== the CR check (DMG chapter 9)
def _cr_index(cr: str) -> int:
    return CR_STEPS.index(cr)


def _avg_damage(text: str) -> int:
    return sum(int(mt.group(1)) for mt in _DMG.finditer(text))


def effective_hp(m: dict) -> float:
    """HP, raised for broad resistances or immunities (DMG chapter 9)."""
    res = [d for d in DAMAGE if d in m["resist"].lower()]
    imm = [d for d in DAMAGE if d in m["immune"].lower()]
    if not (len(res) + len(imm) >= 3 or any(d in res + imm for d in PHYSICAL)):
        return float(m["hp"])
    crn, immune = _cr(m["cr"]), len(imm) >= 3 or any(d in imm for d in PHYSICAL)
    mult = (2 if crn <= 4 or immune and crn <= 10 else 1.5 if crn <= 10 or immune and crn <= 16
            else 1.25 if crn <= 16 or immune else 1)
    return m["hp"] * mult


def offense(m: dict) -> dict:
    """Damage per round over the first three rounds (multiattack, recharge powers once, legendary actions), best attack bonus and DC."""
    acts = [a for a in m["actions"] if a["name"].lower() != "multiattack"]
    recharge = [a for a in acts if re.search(r"recharge|/day", a["name"], re.I)]
    every = [a for a in acts if a not in recharge]
    total = max((_avg_damage(a["text"]) for a in every), default=0)
    multi = next((a["text"] for a in m["actions"] if a["name"].lower() == "multiattack"), "")
    if multi:
        words = re.findall(r"\b(one|two|three|four|five|six)\b", multi.lower())
        count = max(1, sum(NUMBER_WORDS[w] for w in words[1:]) if len(words) > 1 and "attacks:" in multi else NUMBER_WORDS.get(words[0], 1) if words else 1)
        named = [a for a in every if "to hit" in a["text"] and a["name"].split(" (")[0].lower() in multi.lower()]
        weapon = [_avg_damage(a["text"]) for a in named or [a for a in every if "Weapon Attack" in a["text"]]]
        total = max(total, (max(weapon) if weapon else total) * count)
    if recharge:                                  # used once in the first three rounds: average it in
        total = max(total, (max(_avg_damage(a["text"]) for a in recharge) + 2 * total) / 3)
    if m["legendary"]:
        total += max((_avg_damage(a["text"]) for a in m["legendary"]), default=0)
    hits = [int(x) for a in acts for x in re.findall(r"([+-]\d+) to hit", a["text"])]
    dcs = [int(x) for a in acts for x in re.findall(r"\bDC (\d+)", a["text"])]
    return {"dpr": total, "atk": max(hits) if hits else None, "dc": max(dcs) if dcs else None}


def cr_check(m: dict) -> dict:
    """Defensive and offensive CR of a built monster, compared with the printed monsters, and the CR they average to."""
    ehp, off = effective_hp(m), offense(m)
    clamp = lambda i: max(0, min(len(CR_STEPS) - 1, i))
    d_i = _nearest(ehp, "hp")
    d_i = clamp(d_i + int((m["ac"] - typical(CR_STEPS[d_i])["ac"]) / 2))
    o_i = _nearest(off["dpr"], "dpr") if off["dpr"] > 0 else 0
    ref = typical(CR_STEPS[o_i])
    if off["atk"] is not None:
        o_i += int((off["atk"] - ref["atk"]) / 2)
    elif off["dc"] is not None:
        o_i += int((off["dc"] - (ref["atk"] + 8)) / 2)
    o_i = clamp(o_i)
    return {"defensive": CR_STEPS[d_i], "offensive": CR_STEPS[o_i], "suggested": CR_STEPS[clamp(int((d_i + o_i) / 2 + 0.5))],
            "ehp": int(ehp), "dpr": int(off["dpr"]), "d_i": d_i, "o_i": o_i}


# ====================================================================== quick generation
NATURAL = {
    "beast": [("Bite", "piercing"), ("Claws", "slashing"), ("Gore", "piercing"), ("Hooves", "bludgeoning"), ("Tail", "bludgeoning")],
    "monstrosity": [("Bite", "piercing"), ("Claws", "slashing"), ("Tail", "bludgeoning"), ("Stinger", "piercing")],
    "dragon": [("Bite", "piercing"), ("Claw", "slashing"), ("Tail", "bludgeoning")],
    "aberration": [("Tentacle", "bludgeoning"), ("Bite", "piercing"), ("Claw", "slashing")],
    "construct": [("Slam", "bludgeoning"), ("Fist", "bludgeoning"), ("Blade Arm", "slashing")],
    "elemental": [("Slam", "bludgeoning"), ("Touch", "bludgeoning")],
    "ooze": [("Pseudopod", "bludgeoning")],
    "plant": [("Slam", "bludgeoning"), ("Vine Lash", "bludgeoning"), ("Thorns", "piercing")],
    "undead": [("Claw", "slashing"), ("Bite", "piercing"), ("Rotting Fist", "bludgeoning")],
}
WEAPONS = {  # name, die, damage type, kind
    "brute": [("Greataxe", 12, "slashing", "melee"), ("Maul", 6, "bludgeoning", "melee"), ("Greatclub", 8, "bludgeoning", "melee")],
    "defender": [("Longsword", 8, "slashing", "melee"), ("Warhammer", 8, "bludgeoning", "melee"), ("Spear", 6, "piercing", "both")],
    "skirmisher": [("Scimitar", 6, "slashing", "melee"), ("Shortsword", 6, "piercing", "melee"), ("Rapier", 8, "piercing", "melee")],
    "artillery": [("Longbow", 8, "piercing", "ranged"), ("Heavy Crossbow", 10, "piercing", "ranged"), ("Shortbow", 6, "piercing", "ranged")],
    "spellcaster": [("Quarterstaff", 6, "bludgeoning", "melee"), ("Dagger", 4, "piercing", "both")],
    "controller": [("Whip", 4, "slashing", "melee"), ("Quarterstaff", 6, "bludgeoning", "melee")],
    "leader": [("Longsword", 8, "slashing", "melee"), ("Glaive", 10, "slashing", "melee"), ("Battleaxe", 8, "slashing", "melee")],
    "boss": [("Greatsword", 6, "slashing", "melee"), ("Halberd", 10, "slashing", "melee"), ("Morningstar", 8, "piercing", "melee")],
}
TYPE_INFO = {  # senses, languages, damage immunities, condition immunities, resistances (CR 5+)
    "aberration": ({"darkvision": 120}, "Deep Speech, telepathy 60 ft.", [], [], ["psychic"]),
    "beast": ({}, "—", [], [], []),
    "celestial": ({"darkvision": 120}, "all, telepathy 120 ft.", [], ["charmed", "exhaustion", "frightened"], ["radiant"] + PHYSICAL),
    "construct": ({"darkvision": 60}, "understands the languages of its creator but can't speak", ["poison", "psychic"],
                  ["charmed", "exhaustion", "frightened", "paralyzed", "petrified", "poisoned"], []),
    "dragon": ({"blindsight": 30, "darkvision": 120}, "Common, Draconic", [], [], []),
    "elemental": ({"darkvision": 60}, "Primordial", ["poison"], ["exhaustion", "grappled", "paralyzed", "petrified", "poisoned", "prone", "restrained", "unconscious"], PHYSICAL),
    "fey": ({"darkvision": 60}, "Common, Elvish, Sylvan", [], ["charmed"], []),
    "fiend": ({"darkvision": 120}, "Abyssal, Infernal, telepathy 120 ft.", ["poison"], ["poisoned"], ["cold", "fire", "lightning"] + PHYSICAL),
    "giant": ({}, "Giant", [], [], []),
    "humanoid": ({}, "Common and one other language", [], [], []),
    "monstrosity": ({"darkvision": 60}, "—", [], [], []),
    "ooze": ({"blindsight": 60}, "—", ["acid"], ["blinded", "charmed", "deafened", "exhaustion", "frightened", "prone"], []),
    "plant": ({"blindsight": 60}, "—", [], ["blinded", "deafened", "exhaustion"], []),
    "undead": ({"darkvision": 60}, "the languages it knew in life", ["poison"], ["exhaustion", "poisoned"], ["necrotic"]),
}
ROLE_TRAITS = {  # library features that suit a role, looked up by name
    "brute": ["Brute", "Reckless", "Charge", "Rampage", "Relentless", "Trampling Charge", "Savage Attacker", "Siege Monster"],
    "skirmisher": ["Nimble Escape", "Pack Tactics", "Pounce", "Sneak Attack", "Flyby", "Cunning Action", "Evasion", "Keen Smell", "Ambusher"],
    "defender": ["Parry", "Protection", "Shield Bash", "Sentinel", "Steadfast"],
    "artillery": ["Keen Sight", "Sure-Footed", "Archer's Eye", "Volley", "Sniper"],
    "spellcaster": ["Magic Resistance", "Arcane Ward", "Spell Turning"],
    "controller": ["Magic Resistance", "Grappler", "Web Sense", "Spider Climb"],
    "leader": ["Leadership", "Martial Advantage", "Commanding Presence", "Aggressive"],
    "boss": ["Magic Resistance", "Regeneration", "Siege Monster", "Frightful Presence"],
}
NAME_ADJ = {"none": ["Dread", "Grim", "Feral", "Ashen", "Hollow", "Iron", "Blood", "Shadow", "Thorn", "Storm"],
            "fire": ["Ember", "Cinder", "Blaze", "Pyre"], "cold": ["Frost", "Rime", "Glacial", "Winter"],
            "lightning": ["Storm", "Thunderbolt", "Spark", "Static"], "acid": ["Caustic", "Corrosive", "Bile"],
            "poison": ["Venom", "Blight", "Toxic"], "necrotic": ["Grave", "Wither", "Death"], "radiant": ["Dawn", "Sun", "Halo"],
            "thunder": ["Thunder", "Booming", "Quake"], "psychic": ["Mind", "Dream", "Whisper"], "force": ["Void", "Arcane", "Rift"]}
NAME_NOUN = {"brute": ["Brute", "Mauler", "Ravager", "Crusher"], "skirmisher": ["Stalker", "Skulker", "Prowler", "Raider"],
             "defender": ["Warden", "Sentinel", "Guardian", "Bulwark"], "artillery": ["Archer", "Slinger", "Spitter", "Sniper"],
             "spellcaster": ["Adept", "Hexer", "Oracle", "Magus"], "controller": ["Binder", "Snarer", "Weaver", "Mesmer"],
             "leader": ["Captain", "Chieftain", "Warlord", "Matron"], "boss": ["Tyrant", "Overlord", "Behemoth", "Sovereign"]}
TYPE_NOUN = {"beast": "Beast", "construct": "Construct", "undead": "Revenant", "fiend": "Fiend", "celestial": "Seraph", "dragon": "Drake",
             "elemental": "Elemental", "ooze": "Ooze", "plant": "Bloom", "fey": "Sprite", "giant": "Giant", "aberration": "Horror",
             "monstrosity": "Horror", "humanoid": ""}
CASTER = {"celestial": ("Cleric", "wis"), "undead": ("Wizard", "int"), "fiend": ("Sorcerer", "cha"), "fey": ("Druid", "wis"),
          "plant": ("Druid", "wis"), "beast": ("Druid", "wis"), "dragon": ("Sorcerer", "cha"), "aberration": ("Wizard", "int"),
          "elemental": ("Sorcerer", "cha"), "giant": ("Cleric", "wis"), "humanoid": ("Wizard", "int"), "monstrosity": ("Sorcerer", "cha"),
          "construct": ("Wizard", "int"), "ooze": ("Sorcerer", "cha")}
FULL_SLOTS = [[], [2], [3], [4, 2], [4, 3], [4, 3, 2], [4, 3, 3], [4, 3, 3, 1], [4, 3, 3, 2], [4, 3, 3, 3, 1], [4, 3, 3, 3, 2],
              [4, 3, 3, 3, 2, 1], [4, 3, 3, 3, 2, 1], [4, 3, 3, 3, 2, 1, 1], [4, 3, 3, 3, 2, 1, 1], [4, 3, 3, 3, 2, 1, 1, 1],
              [4, 3, 3, 3, 2, 1, 1, 1], [4, 3, 3, 3, 2, 1, 1, 1, 1], [4, 3, 3, 3, 3, 1, 1, 1, 1], [4, 3, 3, 3, 3, 2, 1, 1, 1],
              [4, 3, 3, 3, 3, 2, 2, 1, 1]]
CONTROL = [("Strength", "restrained", "Grasping {elem}", "Each creature of the {name}'s choice within 10 feet of it must succeed on a DC {dc} Strength saving throw or take {dmg} {dtype} damage and be restrained until the end of its next turn."),
           ("Wisdom", "frightened", "Terrifying Gaze", "The {name} targets one creature it can see within 30 feet of it. The target must succeed on a DC {dc} Wisdom saving throw or take {dmg} {dtype} damage and be frightened until the end of its next turn."),
           ("Constitution", "poisoned", "Noxious Spray", "The {name} sprays a 15-foot cone. Each creature in that area must succeed on a DC {dc} Constitution saving throw or take {dmg} {dtype} damage and be poisoned until the end of its next turn."),
           ("Dexterity", "prone", "Sweeping Blast", "Each creature in a 15-foot cone must succeed on a DC {dc} Dexterity saving throw or take {dmg} {dtype} damage and be knocked prone.")]


def options() -> dict:
    return {"crs": CR_STEPS, "types": TYPES, "sizes": SIZES, "roles": ROLES, "themes": THEMES, "mobility": MOBILITY,
            "damage": DAMAGE, "conditions": CONDITIONS, "skills": list(rules.skills), "sections": SECTIONS,
            "environments": sorted({e for m in bestiary.offered() for e in m["environment"]}), "table": TABLE, "hit_die": HIT_DIE}


def _auto_size(t: str, crn: float, rng: random.Random) -> str:
    if t == "giant":
        return "Huge" if crn >= 5 else "Large"
    if t == "dragon":
        return "Gargantuan" if crn >= 17 else "Huge" if crn >= 10 else "Large" if crn >= 3 else "Medium"
    if t in ("humanoid", "fey"):
        return rng.choice(["Small", "Medium"]) if crn < 1 else "Medium"
    if t == "beast" and crn < 1:
        return rng.choice(["Tiny", "Small", "Medium"])
    return "Huge" if crn >= 12 else "Large" if crn >= 3 else "Medium"


def _abilities(t: str, role: str, crn: float, cast: str, rng: random.Random) -> Dict[str, int]:
    top = 10 if crn == 0 else min(30, round(12 + 2.6 * math.sqrt(crn)))
    mid, low = max(8, top - 3), 10
    j = lambda v: max(1, min(30, v + rng.randint(-1, 1)))
    ab = {a: j(low) for a in E.ABILITIES}
    plan = {"brute": {"str": top + 1, "con": top - 1, "dex": low},
            "defender": {"str": top, "con": top - 1, "dex": low, "wis": mid - 2},
            "skirmisher": {"dex": top, "con": mid - 1, "str": mid - 2, "wis": mid - 2},
            "artillery": {"dex": top, "wis": mid, "con": mid - 2},
            "spellcaster": {cast: top, "dex": mid - 1, "con": mid - 2},
            "controller": {cast: top, "con": mid, "dex": mid - 2},
            "leader": {"str": top - 1, "cha": top - 1, "con": mid, "wis": mid - 1},
            "boss": {"str": top + 1, "con": top, "wis": mid, "cha": mid}}[role]
    for a, v in plan.items():
        ab[a] = j(v)
    if t == "beast":
        ab.update(int=rng.randint(2, 4), cha=rng.randint(5, 7))
    elif t in ("ooze", "plant"):
        ab.update(int=rng.randint(1, 3), cha=rng.randint(1, 5), wis=min(ab["wis"], 8))
    elif t == "construct" and role not in ("spellcaster", "controller"):
        ab.update(int=rng.randint(3, 6), cha=rng.randint(1, 5))
    elif t == "giant":
        ab["str"] = min(30, ab["str"] + 2)
    elif t in ("dragon", "celestial", "fiend") and crn >= 3:
        ab.update(int=max(ab["int"], top - 4), wis=max(ab["wis"], top - 5), cha=max(ab["cha"], top - 3))
    return ab


# ====================================================================== spellcasting (any spell of the library, no class or level limits)
INNATE_USES = ["at will", "3/day", "2/day", "1/day"]


def spell_list() -> List[dict]:
    """Every spell in the library, for the editor's spell picker."""
    return [{"name": s["name"], "level": s["level"], "school": s["school"], "classes": s.get("classes", []), "source": s["source"],
             "conc": bool(s.get("concentration")), "damage": s.get("damage") or []}
            for s in sorted(rules.offered(rules.spells.values()), key=lambda s: (s["level"], s["name"]))]


def clean_setup(setup: dict) -> dict:
    spells, seen = [], set()
    for e in setup.get("spells") or []:
        e = {"name": e} if isinstance(e, str) else e
        sp = rules.spell(str(e.get("name", "")))
        if sp and sp["name"] not in seen:
            seen.add(sp["name"])
            uses = e.get("uses") if e.get("uses") in INNATE_USES else ("at will" if sp["level"] == 0 else "1/day")
            spells.append({"name": sp["name"], "uses": uses})
    return {"mode": "innate" if setup.get("mode") == "innate" else "slots",
            "ability": setup.get("ability") if setup.get("ability") in ABILITY_NAMES else "int",
            "level": _num(setup.get("level"), 0, 0, 20), "class_name": str(setup.get("class_name") or "").strip(), "spells": spells}


def needed_level(top: int) -> int:
    """The lowest full-caster level with a slot of that spell level."""
    return 1 if top <= 1 else min(17, top * 2 - 1)


def spellcasting_entry(spec: dict, setup: dict) -> dict:
    """The stat block entry (book format, which the battle page reads) for the chosen spells."""
    s, st = clean(spec), clean_setup(setup)
    The = ref(s["name"] or "creature", True)
    prof, am = TABLE[s["cr"]]["prof"], mod(s["abilities"][st["ability"]])
    stats = f"spell save DC {8 + prof + am}, {signed(prof + am)} to hit with spell attacks"
    lvl = lambda n: (rules.spell(n) or {"level": 0})["level"]
    if st["mode"] == "innate":
        lines = []
        for uses in INNATE_USES:
            names = [e["name"].lower() for e in st["spells"] if e["uses"] == uses]
            if names:
                label = "At will" if uses == "at will" else uses + (" each" if len(names) > 1 else "")
                lines.append(f"{label}: {', '.join(names)}")
        text = (f"{The}'s innate spellcasting ability is {ABILITY_NAMES[st['ability']]} ({stats}). "
                f"It can innately cast the following spells, requiring no material components:" + "".join("\n" + ln for ln in lines))
        return {"name": "Innate Spellcasting", "text": text, "setup": st}
    top = max((lvl(e["name"]) for e in st["spells"]), default=0)
    level = st["level"] or max(needed_level(top), min(20, max(1, round(_cr(s["cr"]) * 1.5))))
    slots = FULL_SLOTS[level]
    lines = []
    cantrips = [e["name"].lower() for e in st["spells"] if lvl(e["name"]) == 0]
    if cantrips:
        lines.append(f"Cantrips: {', '.join(cantrips)}")
    for lv in range(1, 10):
        names = [e["name"].lower() for e in st["spells"] if lvl(e["name"]) == lv]
        if names:
            n = slots[lv - 1] if lv <= len(slots) else 1             # no limits: a spell above the caster's slots still gets one
            lines.append(f"Level {lv} ({n} slot{'s' if n != 1 else ''}): {', '.join(names)}")
    kind = f"{st['class_name'].lower()} " if st["class_name"] else ""
    text = (f"{The} is {a_an(ordinal(level))}-level spellcaster. Its spellcasting ability is {ABILITY_NAMES[st['ability']]} "
            f"({stats}). {The} has the following {kind}spells prepared:" + "".join("\n" + ln for ln in lines))
    return {"name": "Spellcasting", "text": text, "setup": st}


def parse_spellcasting(entry: dict) -> dict:
    """A setup read back from printed spellcasting text (for editing a book creature's spells)."""
    text = entry.get("text", "")
    innate = "innate" in (entry.get("name", "") + text[:200]).lower()
    ability = next((a for a, n in ABILITY_NAMES.items() if f"ability is {n}" in text), "int")
    hit = re.search(r"(\d+)(?:st|nd|rd|th)-level spellcaster", text)
    kind = re.search(r"following (\w+) spells", text)
    spells, missed = [], 0
    for line in text.split("\n")[1:]:
        label, _, rest = line.partition(":")
        low = label.lower()
        uses = "at will" if "will" in low or "cantrip" in low else next((u for u in ("3/day", "2/day", "1/day") if u in low), "1/day")
        for part in re.split(r",\s*(?![^()]*\))", rest):
            name = re.sub(r"\s*\(.*?\)|\*", "", part).strip().rstrip(".")
            if rules.spell(name):
                spells.append({"name": rules.spell(name)["name"], "uses": uses})
            elif name:
                missed += 1
    return dict(missed=missed, **clean_setup({"mode": "innate" if innate else "slots", "ability": ability, "level": int(hit.group(1)) if hit else 0,
                        "class_name": kind.group(1) if kind else "", "spells": spells}))


def _spellcasting(name: str, cls: str, ability: str, spec: dict, theme: str, rng: random.Random) -> dict:
    crn = _cr(spec["cr"])
    level = max(1, min(20, round(crn * 1.5) or 1))
    slots = FULL_SLOTS[level]
    pool = rules.class_spell_list(cls)
    if not pool:
        return {}

    def choose(lv: int, n: int) -> List[str]:
        spells = [s for s in pool if s["level"] == lv]
        hurt = [s for s in spells if s.get("damage")]
        themed = [s for s in hurt if theme in (s.get("damage") or [])]
        out = []
        for group in (themed, hurt, spells):
            rng.shuffle(group)
            for s in group:
                if len(out) < n and s["name"] not in out:
                    out.append(s["name"])
        return out
    picks = choose(0, 3 if level < 10 else 4)
    for lv, count in enumerate(slots, 1):
        picks += choose(lv, min(3, count + (1 if lv <= 3 else 0)) if lv < 6 else 1)
    return spellcasting_entry(dict(spec, name=name), {"mode": "slots", "ability": ability, "level": level, "class_name": cls, "spells": picks})


def _library_trait(names: List[str], s: dict, rng: random.Random, taken: set, sec: str = "traits") -> Optional[dict]:
    want = {n.lower() for n in names}
    t, crn = s["type"], _cr(s["cr"])
    fam = broad_type(t)
    hits = [f for f in features() if f["sec"] == sec and f["name"].lower() in want and f["name"].lower() not in taken and len(f["text"]) < 500
            and _fits(f, s, s["name"])]
    hits.sort(key=lambda f: (f["fam"] != fam, abs(_cr(f["cr"]) - crn)))
    return rng.choice(hits[:4]) if hits else None


def _type_traits(s: dict, rng: random.Random, taken: set, n: int) -> List[dict]:
    """Thematic traits borrowed from printed creatures of the same type and a nearby CR."""
    skip = ("spellcasting", "legendary resistance", "innate", "shapechanger", "lair", "variant", "illumination", "multiattack",
            "proficienc", "special equipment", "tongue")
    t, crn = s["type"], _cr(s["cr"])
    lo, hi = crn / 2 - 1, crn * 2 + 1
    pool = [f for f in features() if f["sec"] == "traits" and lo <= _cr(f["cr"]) <= hi and len(f["text"]) < 420
            and not any(x in f["name"].lower() for x in skip) and f["name"].lower() not in taken
            and (bestiary.get(f["mon"]) or {}).get("type", "").split("/")[0] == t and f["mon"].split("|")[1] != "Custom"]
    rng.shuffle(pool)
    out = []
    for f in pool:
        if len(out) >= n:
            break
        if re.search(r"[A-Z][a-z]+'s ", f["name"]):         # 'Raxivort's Tongue': tied to one named creature
            continue
        if f["name"].lower() not in taken and not re.search(r"\(\d+/day\)", f["name"].lower()) and _fits(f, s, s["name"]):
            taken.add(f["name"].lower())
            out.append(f)
    return out


# role -> (defence, offence) lean in CR steps; the two always average out to the chosen CR
LEAN = {"brute": (-1, 1), "defender": (1, -1), "skirmisher": (0, 0), "artillery": (-1, 1), "spellcaster": (-1, 1),
        "controller": (0, 0), "leader": (0, 0), "boss": (0, 0)}


def scale_damage(spec: dict, f: float) -> dict:
    """Every damage roll in the creature's actions multiplied by about `f` (dice counts; flat bonuses stay)."""
    s = clean(spec)

    def dmg(mt):
        n, die = int(mt.group(2)), int(mt.group(3))
        bonus = int(mt.group(5) or 0) * (-1 if mt.group(4) in ("-", "−") else 1)
        n2 = max(1, round(n * f))
        return f"{dice_avg(n2, die, bonus)} ({dice_text(n2, die, bonus)})"
    for k in ("actions", "bonus_actions", "reactions", "legendary"):
        for e in s[k]:
            e["text"] = _DMG.sub(dmg, e["text"])
    return s


def calibrate(spec: dict, role: str = "skirmisher") -> dict:
    """Tune hit dice and damage dice until the CR check puts the creature where it was asked to be."""
    target = CR_STEPS.index(spec["cr"])
    lean_d, lean_o = LEAN.get(role, (0, 0))
    clamp = lambda i: max(0, min(len(CR_STEPS) - 1, i))
    want_d, want_o = clamp(target + lean_d), clamp(target + lean_o)
    s = clean(spec)
    lo, hi = 1, 99                                   # defence rises with hit dice: smallest that reaches the wanted step
    while lo < hi:
        mid = (lo + hi) // 2
        s["hit_dice"] = mid
        if cr_check(build(s))["d_i"] >= want_d:
            hi = mid
        else:
            lo = mid + 1
    s["hit_dice"] = lo
    if lo > 1:                                       # one die fewer may sit closer
        below = dict(s, hit_dice=lo - 1)
        if abs(cr_check(build(below))["d_i"] - want_d) < abs(cr_check(build(s))["d_i"] - want_d):
            s = clean(below)
    best, best_key = s, None
    for step in range(-14, 21):                       # damage x0.3 .. x4.7: the overall CR first, then the role's lean, then least change
        cand = scale_damage(s, 1.08 ** step) if step else s
        c = cr_check(build(cand))
        key = (abs(CR_STEPS.index(c["suggested"]) - target), abs(c["o_i"] - want_o), abs(step))
        if best_key is None or key < best_key:
            best, best_key = cand, key
    return best


def generate(choices: dict, seed: Optional[int] = None) -> dict:
    """A complete spec from the quick choices: cr, type, role, size ('auto'), theme, mobility, name (optional)."""
    rng = random.Random(seed)
    cr = cr_text(choices.get("cr") or "1")
    crn = _cr(cr)
    t = (choices.get("type") or "auto").lower()
    t = rng.choice(TYPES) if t not in TYPES else t
    role = choices.get("role") if choices.get("role") in ROLES else rng.choice(list(ROLES))
    theme = choices.get("theme") if choices.get("theme") in THEMES else "none"
    if theme == "none" and t in ("dragon", "elemental") and choices.get("theme") != "none":
        theme = rng.choice(["fire", "cold", "lightning", "acid", "poison"] if t == "dragon" else ["fire", "cold", "lightning", "thunder"])
    size = choices.get("size") if choices.get("size") in SIZES else _auto_size(t, crn, rng)
    tbl = TABLE[cr]
    tdpr = typical(cr)["dpr"]
    prof = tbl["prof"]
    name = re.sub(r"\s+", " ", str(choices.get("name") or "")).strip()
    if not name:
        noun = rng.choice(NAME_NOUN[role])
        name = " ".join(x for x in (rng.choice(NAME_ADJ[theme]), TYPE_NOUN[t] if TYPE_NOUN[t] and rng.random() < .5 else "", noun) if x)
    cast_cls, cast = CASTER[t]
    s = blank_spec(cr)
    s.update(name=name, size=size, type=t, cr=cr)
    s["abilities"] = ab = _abilities(t, role, crn, cast, rng)
    senses, langs, dimm, cimm, dres = TYPE_INFO[t]
    s["senses"].update(senses)
    s["languages"] = langs
    s["immune"] = list(dimm)
    s["condition_immune"] = list(cimm)
    if crn >= 5 and dres:
        s["resist"] = [d for d in dres if d not in s["immune"]]
        s["nonmagical"] = any(d in PHYSICAL for d in s["resist"])
    if theme != "none":
        (s["immune"] if crn >= 5 or t in ("elemental", "dragon") else s["resist"]).append(theme)
        s["resist"] = [d for d in s["resist"] if d not in s["immune"]]
    s["alignment"] = {"celestial": "lawful good", "fiend": rng.choice(["lawful evil", "chaotic evil"]), "undead": "neutral evil",
                      "fey": rng.choice(["chaotic neutral", "neutral"]), "beast": "unaligned", "construct": "unaligned",
                      "ooze": "unaligned", "plant": "unaligned"}.get(t, rng.choice(["neutral evil", "chaotic evil", "lawful evil", "neutral"]))
    if t == "humanoid":
        s["tags"] = rng.choice(["human", "orc", "goblinoid", "elf", "dwarf", "any race", "gnoll", "kobold"])
    s["environment"] = [choices["environment"]] if choices.get("environment") else []
    # --- movement
    mob = choices.get("mobility") if choices.get("mobility") in MOBILITY else "auto"
    if mob == "auto":
        mob = "flyer" if t in ("dragon", "celestial") or t == "fiend" and rng.random() < .4 or t == "fey" and rng.random() < .3 else \
            "walker" if t != "beast" or rng.random() < .6 else rng.choice(["climber", "swimmer", "flyer"])
    walk = 25 if size in ("Tiny", "Small") else 30 if size == "Medium" else 40
    walk += 10 if role == "skirmisher" else 0
    s["speed"]["walk"] = walk if mob != "flyer" or t != "beast" else 10
    if mob != "walker":
        key = {"flyer": "fly", "swimmer": "swim", "climber": "climb", "burrower": "burrow"}[mob]
        s["speed"][key] = walk * (2 if key == "fly" else 1)
        s["speed"]["hover"] = key == "fly" and t in ("celestial", "elemental", "undead") and rng.random() < .5
    # --- defence
    typ = typical(cr)
    s["ac"] = max(10, min(22, round(typ["ac"] + {"defender": 2, "boss": 1, "brute": -1, "spellcaster": -2, "artillery": -1}.get(role, 0))))
    dex_ac = 10 + mod(ab["dex"])
    s["ac_note"] = "" if s["ac"] <= dex_ac else \
        {"defender": "plate" if s["ac"] >= 18 else "chain mail, shield", "brute": "hide armor", "skirmisher": "studded leather",
         "artillery": "leather armor", "spellcaster": "mage armor", "leader": "breastplate, shield"}.get(role, "natural armor") \
        if t == "humanoid" else "natural armor"
    target_hp = typ["hp"] * {"brute": 1.25, "boss": 1.6, "defender": 1.1, "skirmisher": 0.9, "artillery": 0.8, "spellcaster": 0.75,
                             "controller": 0.9, "leader": 1.0}[role]
    per_die = (HIT_DIE[size] + 1) / 2 + mod(ab["con"])
    s["hit_dice"] = max(1, round(target_hp / max(1.0, per_die)))
    # --- proficiencies
    saves = {"brute": ["str", "con"], "defender": ["str", "con"], "skirmisher": ["dex", "wis"], "artillery": ["dex", "wis"],
             "spellcaster": [cast, "wis" if cast != "wis" else "int"], "controller": [cast, "con"], "leader": ["str", "wis", "cha"],
             "boss": ["dex", "con", "wis", "cha"]}[role]
    s["save_profs"] = saves if crn >= 3 else saves[:1] if crn >= 1 else []
    skills = {"brute": ["Athletics", "Intimidation"], "defender": ["Athletics", "Perception"], "skirmisher": ["Stealth", "Acrobatics", "Perception"],
              "artillery": ["Perception", "Stealth"], "spellcaster": ["Arcana", "History"] if cast == "int" else ["Insight", "Religion"] if cast == "wis" else ["Deception", "Persuasion"],
              "controller": ["Insight", "Deception"], "leader": ["Intimidation", "Persuasion", "Athletics"], "boss": ["Perception", "Intimidation", "Insight"]}[role]
    s["skill_profs"] = skills[:1 + (crn >= 4) + (crn >= 11)]
    if t == "beast" and "Perception" not in s["skill_profs"]:
        s["skill_profs"].append("Perception")
    s["skill_expert"] = ["Perception"] if role == "boss" and crn >= 10 else []
    # --- attacks
    natural = t in NATURAL and (t != "humanoid")
    swing = "dex" if role in ("skirmisher", "artillery") or ab["dex"] > ab["str"] else "str"
    sm = mod(ab[swing])
    attacks = 1 if crn < 2 or role in ("spellcaster", "controller") else 2 if crn < 8 else 3 if crn < 17 else 4
    budget = tdpr * {"brute": 1.15, "boss": 1.0, "artillery": 1.05, "spellcaster": 0.45, "controller": 0.6, "leader": 0.85,
                        "defender": 0.85, "skirmisher": 1.0}[role]
    if role == "boss":
        budget *= 0.8                                # legendary actions carry the rest
    per = budget / attacks if role not in ("spellcaster", "controller") else tdpr * 0.25     # casters hurt with their magic
    rider = per * 0.3 if theme != "none" else 0
    if natural:
        kinds = list(NATURAL[t])
        rng.shuffle(kinds)
        weapons = [(nm, HIT_DIE[size] if HIT_DIE[size] <= 12 else 12, dt, "melee") for nm, dt in kinds[:1 if attacks == 1 else 2]]
    else:
        weapons = [rng.choice(WEAPONS[role])]
        if role in ("skirmisher", "leader", "defender", "brute") and t in ("humanoid", "giant", "fiend", "celestial", "fey"):
            weapons.append(("Rock" if t == "giant" else "Javelin", 10 if t == "giant" else 6, "bludgeoning" if t == "giant" else "piercing", "both"))
    reach = 10 if size in ("Large", "Huge", "Gargantuan") and natural or size in ("Huge", "Gargantuan") else 5
    entries = []
    for nm, die, dt, kind in weapons:
        want = per - sm - rider
        n = max(1, round(want / ((die + 1) / 2)))
        rn = max(1, round(rider / 3.5)) if rider >= 2 else 0
        a = {"name": nm, "kind": kind, "ability": swing, "dice": n, "die": die, "dtype": dt, "reach": reach,
             "range": "60/240" if nm == "Rock" else "30/120" if nm == "Javelin" else "20/60" if nm == "Dagger" else "150/600" if nm == "Longbow" else "80/320",
             "extra_n": rn, "extra_die": 6, "extra_type": theme if rn else ""}
        entries.append(attack_entry(s, a))
    if attacks > 1:
        first, second = entries[0]["name"].lower(), entries[1]["name"].lower() if len(entries) > 1 else ""
        words = {2: "two", 3: "three", 4: "four"}[attacks]
        if natural and second:
            rest = {2: "one", 3: "two", 4: "three"}[attacks]
            head = f"The {name.lower()} makes {words} attacks: one with its {first} and {rest} with its {second}."
        else:
            head = f"The {name.lower()} makes {words} {first} attacks."
        entries.insert(0, {"name": "Multiattack", "text": head})
    s["actions"] = entries
    # --- role extras
    taken = set()
    dc = 8 + prof + max(mod(ab[cast]), mod(ab["con"]))
    if role in ("spellcaster",) or role == "controller" and crn >= 3 and rng.random() < .5:
        sc = _spellcasting(name, cast_cls, cast, s, theme, rng)
        if sc:
            s["spellcasting"] = [sc]
        if role == "spellcaster":
            ranged = {"name": {"fire": "Fire Bolt", "cold": "Frost Ray", "lightning": "Shock", "necrotic": "Withering Ray",
                               "radiant": "Searing Light", "psychic": "Mind Spike", "acid": "Acid Dart", "poison": "Venom Dart",
                               "thunder": "Thunderclap", "force": "Arcane Bolt"}.get(theme, "Arcane Bolt"),
                      "kind": "spell", "ability": cast, "dice": max(1, round(tdpr * .6 / 5.5)), "die": 10,
                      "dtype": theme if theme != "none" else "force", "range": "120"}
            s["actions"].append(attack_entry(s, ranged))
    if role == "controller" or t == "dragon" or theme != "none" and role in ("boss", "brute") and crn >= 3:
        if t == "dragon" or theme != "none" and role != "controller":
            elem = theme if theme != "none" else "fire"
            n = max(2, round(tdpr * 1.2 / (5.5 if crn < 10 else 7)))
            die = 10 if crn < 10 else 12
            cone = 15 if crn < 5 else 30 if crn < 11 else 60
            save = "Constitution" if elem in ("poison", "cold", "necrotic") else "Dexterity"
            noun = "Breath" if t in ("dragon", "beast", "monstrosity") else "Burst"
            s["actions"].append({"name": f"{elem.title()} {noun} (Recharge 5–6)",
                                 "text": f"The {name.lower()} {'exhales' if noun == 'Breath' else 'unleashes'} {elem} energy in a {cone}-foot cone. "
                                         f"Each creature in that area must make a DC {dc} {save} saving throw, taking {dice_avg(n, die)} ({dice_text(n, die)}) "
                                         f"{elem} damage on a failed save, or half as much damage on a successful one."})
        else:
            ability, cond, title, body = rng.choice(CONTROL)
            dtype = theme if theme != "none" else rng.choice(["psychic", "bludgeoning", "poison", "force"])
            n = max(1, round(tdpr * .5 / 4.5))
            s["actions"].append({"name": title.format(elem="Tendrils" if theme == "none" else f"{theme.title()} Tendrils"),
                                 "text": body.format(name=name.lower(), dc=dc, dmg=f"{dice_avg(n, 8)} ({dice_text(n, 8)})", dtype=dtype)})
    traits = []
    pick = _library_trait(ROLE_TRAITS[role], s, rng, taken)
    if pick:
        taken.add(pick["name"].lower())
        traits.append(pick)
    traits += _type_traits(s, rng, taken, 1 if crn < 3 else 2 if role != "boss" else 3)
    s["traits"] = [{"name": f["name"], "text": _borrow(f, cr, name)} for f in traits]
    if role in ("defender", "leader"):
        r = _library_trait(["Parry"] if role == "defender" else ["Leadership", "Parry"], s, rng, taken,
                           "reactions" if role == "defender" else "actions") or _library_trait(["Parry"], s, rng, taken, "reactions")
        if r:
            (s["reactions"] if r["sec"] == "reactions" else s["actions"]).append({"name": r["name"], "text": _borrow(r, cr, name)})
    if role == "skirmisher" and crn >= 1:
        s["bonus_actions"].append({"name": "Quick Step", "text": f"The {name.lower()} takes the Dash, Disengage, or Hide action."})
    if role == "boss":
        if crn >= 3:
            s["traits"].insert(0, {"name": f"Legendary Resistance ({3 if crn >= 10 else 2}/Day)",
                                   "text": f"If the {name.lower()} fails a saving throw, it can choose to succeed instead."})
        first = next((e["name"] for e in s["actions"] if "to hit" in e["text"]), "")
        s["legendary"] = [{"name": "Detect", "text": f"The {name.lower()} makes a Wisdom (Perception) check."},
                          {"name": "Move", "text": f"The {name.lower()} moves up to half its speed without provoking opportunity attacks."}]
        if first:
            s["legendary"].insert(1, {"name": "Attack", "text": f"The {name.lower()} makes one {first.lower()} attack."})
        if crn >= 5:
            n = max(1, round(tdpr * .25 / 4.5))
            s["legendary"].append({"name": "Sweep (Costs 2 Actions)",
                                   "text": f"Each creature within 10 feet of the {name.lower()} must succeed on a DC {dc} Dexterity saving throw "
                                           f"or take {dice_avg(n, 8, mod(ab['str']))} ({dice_text(n, 8, mod(ab['str']))}) bludgeoning damage and be knocked prone."})
    if role == "leader" and not any(e["name"].lower().startswith("leadership") for e in s["actions"] + s["traits"]):
        s["bonus_actions"].append({"name": "Command Ally", "text": f"The {name.lower()} targets one ally it can see within 30 feet of it. "
                                                                  f"If the target can see or hear the {name.lower()}, the target can use its reaction to make one weapon attack."})
    s["description"] = str(choices.get("description") or "").strip()
    return calibrate(clean(s), role)


# ====================================================================== saving
def _filename(name: str) -> str:
    base = re.sub(r"[^\w\- ']", "", name).strip().replace("'", "")
    return os.path.join(CUSTOM_DIR, (base or "monster") + ".json")


def _refresh():
    from . import search
    bestiary.reload_custom()
    search.monster_index = None
    invalidate()


def save(spec: dict, original: Optional[str] = None) -> dict:
    """Write the creature to data/custom_monsters/. `original`: the id it had when editing started (renaming replaces it)."""
    m = build(spec)
    if not clean(spec)["name"]:
        raise RulesError("Give the creature a name.")
    if not m["actions"] and not m["traits"] and not m["spellcasting"]:
        raise RulesError("Add at least one trait or action.")
    clash = bestiary.get(m["id"])
    if clash and m["id"] != original:
        raise RulesError(f"There already is a custom creature called '{m['name']}'.")
    if original and original != m["id"]:
        delete(original, refresh=False)
    write_json(_filename(m["name"]), m)
    _refresh()
    return m


def delete(monster_id: str, refresh: bool = True):
    m = bestiary.get(monster_id)
    if not m or m.get("source") != "Custom":
        raise RulesError("Only custom creatures can be deleted.")
    for f in os.listdir(CUSTOM_DIR) if os.path.isdir(CUSTOM_DIR) else []:
        path = os.path.join(CUSTOM_DIR, f)
        if f.endswith(".json") and path == _filename(m["name"]) or f.endswith(".json") and _id_in(path) == monster_id:
            os.remove(path)
    if refresh:
        _refresh()


def _id_in(path: str) -> Optional[str]:
    from ..core.storage import read_json
    d = read_json(path, {})
    return d.get("id") if isinstance(d, dict) else None
