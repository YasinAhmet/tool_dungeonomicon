"""What a duel's fighters are made from: a premade hero of a core class at levels 1 to 12 (the quick-adventurer
builder, the same character every time for a class and level), with the spells its player picked in place of the
premade's own; or a monster of a challenge rating - one the player picked from its list, or a random one.

    char = hero("Wizard", 5, ["Fire Bolt", "Shield", "Fireball"])     # a Character (not saved, not held anywhere)
    spell_choices("Wizard", 5)      # what a level 5 Wizard may pick: its counts, the options, the premade's picks
    monsters("3")                   # the CR 3 monsters a player may pick ({id, name, size, type, ac, hp, source})
    random_monster("3", rng)        # a monster id of CR 3
"""
import random
import re
from typing import Dict, List, Optional

from ...core.storage import clone
from ...rules import quickgen
from ...rules import spellcasting as SC
from ...rules.character import Character
from ...rules.data import rules
from ...rules.monsters import bestiary
from ..battle.summon_stats import needs_summoner

LEVELS = list(range(1, 13))
_ATTACKS = re.compile(r"to hit|saving throw", re.I)
_PREMADE: Dict[tuple, dict] = {}                       # (class, level, sources) -> the premade's sheet
_POOL: Dict[str, tuple] = {}                           # "kv" -> (the bestiary list, {cr: [monster ids]})


def classes() -> List[str]:
    """The core classes there is a premade for (in the enabled books)."""
    have = {c["name"] for c in rules.class_list()}
    return [c for c in quickgen.PROFILES if c in have]


def premade(class_name: str, level: int) -> Character:
    """The premade hero of this class and level: always the same one (a fresh copy each call)."""
    if class_name not in classes():
        raise ValueError(f"There is no premade {class_name}.")
    if level not in LEVELS:
        raise ValueError(f"Premade heroes go from level 1 to {LEVELS[-1]}.")
    key = (class_name, level, tuple(rules.active_sources))
    if key not in _PREMADE:
        concept = next((a for a in quickgen.archetypes() if a["class"] == class_name), None)
        opts = quickgen.archetype_options(concept["key"], level=level, seed=f"duel-{class_name}-{level}") if concept \
            else {"race": "Human", "class": class_name, "level": level, "seed": f"duel-{class_name}-{level}"}
        _PREMADE[key] = quickgen.generate(opts).d
    return Character.from_dict(clone(_PREMADE[key]))


def _caster(char: Character) -> Optional[dict]:
    """The premade's spellcasting (one class), or None when it has nothing to pick."""
    info = next(iter(SC.casters(char)), None)
    if not info or (info["max_spell_level"] < 1 and not info["cantrips"]):
        return None
    return info


def _counts(char: Character, info: dict) -> dict:
    sp = SC.class_spells(char, info["class"])
    always = SC.always_prepared(char, info["class"])
    prepares = info["prepared"] is not None
    leveled = [s["name"] for s in SC.eligible_spells(char, info) if s["name"] not in always] if info["max_spell_level"] >= 1 else []
    return {"cantrips": info["cantrips"], "cantrip_options": [s["name"] for s in SC.eligible_spells(char, info, cantrips=True)],
            "spells": (info["prepared"] if prepares else info["known"] or 0) if leveled else 0, "spell_options": leveled,
            "prepares": prepares, "always": always, "max_level": info["max_spell_level"],
            "picked": list(sp["cantrips"]) + list(sp["prepared"] if prepares else sp["known"])}


def spell_choices(class_name: str, level: int) -> dict:
    """What a premade of this class and level may pick: {summary, caster: None | {cantrips: how many, cantrip_options,
    spells: how many, spell_options, prepares, always (granted anyway), max_level, picked (the premade's own)}}."""
    char = premade(class_name, level)
    info = _caster(char)
    return {"class": class_name, "level": level, "summary": quickgen.summary(char),
            "caster": _counts(char, info) if info else None}


def hero(class_name: str, level: int, spells: List[str]) -> Character:
    """The premade with the spells its player picked: picks off its lists or over its counts are left out, and what
    is left open keeps the premade's own choice."""
    char = premade(class_name, level)
    info = _caster(char)
    if not info or not spells:
        return char
    ch = _counts(char, info)
    picks = list(dict.fromkeys(str(s) for s in spells))
    sp = SC.class_spells(char, info["class"])

    def choose(options: List[str], count: int, own: List[str]) -> List[str]:
        out = [n for n in picks if n in options][:count]
        out += [n for n in own if n in options and n not in out][:max(0, count - len(out))]
        return out
    sp["cantrips"] = choose(ch["cantrip_options"], ch["cantrips"], sp["cantrips"])
    if ch["spells"]:
        if ch["prepares"]:
            sp["prepared"] = choose(ch["spell_options"], ch["spells"], sp["prepared"])
            if info["spellbook"]:                               # a Wizard prepares from the book: the picks go in it
                sp["spellbook"] = list(dict.fromkeys(list(sp["spellbook"]) + sp["prepared"]))
        else:
            above = [n for n in sp["known"] if (rules.spell(n) or {}).get("level", 0) > ch["max_level"]]   # (a Mystic Arcanum)
            sp["known"] = choose(ch["spell_options"], ch["spells"], sp["known"]) + above
    return char


# ---------------------------------------------------------------- monsters
def _pool() -> Dict[str, List[str]]:
    """{challenge rating: monsters that can fight on their own} - something to hit with, hit points of their own."""
    every = bestiary.offered()                       # the books ticked in the Sourcebooks window
    hit = _POOL.get("kv")
    if hit is not None and hit[0] is every:
        return hit[1]
    pool: Dict[str, List[str]] = {}
    for m in every:
        if not m.get("cr") or m.get("hp", 0) <= 0 or m.get("cr_num") is None or needs_summoner(m):
            continue
        if any(_ATTACKS.search(e.get("text") or "") for e in m.get("actions") or []):
            pool.setdefault(m["cr"], []).append(m["id"])
    _POOL["kv"] = (every, pool)
    return pool


def crs() -> List[str]:
    """The challenge ratings there are monsters of, lowest first."""
    pool = _pool()
    num = {cr: bestiary.get(ids[0])["cr_num"] for cr, ids in pool.items()}
    return sorted(pool, key=lambda cr: num[cr])


def random_monster(cr: str, rng=random) -> str:
    ids = _pool().get(str(cr))
    if not ids:
        raise ValueError(f"There is no monster of challenge rating {cr}.")
    return rng.choice(ids)


def monsters(cr: str) -> List[dict]:
    """The monsters of a challenge rating a player may pick, by name: {id, name, size, type, ac, hp, source}."""
    rows = [bestiary.get(mid) for mid in _pool().get(str(cr)) or []]
    return sorted(({"id": m["id"], "name": m["name"], "size": m["size"], "type": m["type"], "ac": m["ac"], "hp": m["hp"],
                    "source": m["source"]} for m in rows if m), key=lambda m: (m["name"].lower(), m["source"]))


def usable(monster_id: str) -> Optional[dict]:
    """The monster when it is one a duel may have (in the pool), else None."""
    m = bestiary.get(str(monster_id or ""))
    return m if m and monster_id in (_pool().get(m.get("cr")) or ()) else None
