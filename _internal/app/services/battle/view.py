"""The battle as the windows show it: the tracker's view plus each combatant's picture, subtitle and the difficulty,
and the read-side helpers of the battle windows (a monster's card with its one-click rolls, a player character's
attacks and spells, map tile checks, the XP an ending would award).

Everything here returns English text; the windows translate it where they show it.
"""
import re
from typing import Dict, List, Optional

from ...core import portraits
from ...core.storage import clone
from ...core.runtime import rt
from ...rules import spellcasting as SC
from ...rules.character import Character, file_stamp
from ...rules.character import saves as character_saves
from ...rules.describe import spell_detail
from ...rules.monsters import ability_mod, bestiary, encounter_difficulty
from . import combat_rules as CR
from .battlemap import tile_name
from .constants import health_word
from .floors import floor_at

ABILITIES = ("str", "dex", "con", "int", "wis", "cha")
STATUS = {"setup": "Setting up", "active": "In progress", "ended": "Finished"}


_MEMO: Dict[int, tuple] = {}                           # id(battle) -> (what it was built from, the view): one tuple, swapped
                                                       # whole (the campaign's battle and the duel's, services/duel)


def battle_view(shared: bool = False) -> dict:
    """The battle as the windows show it. Built once per change of the battle (or of a character in it): every call
    returns its own copy, so callers may change what they get. shared: the kept view itself, no copy - for a reader
    that never changes it (the player portal, six pages after every change)."""
    battle = rt().battle
    try:                                               # unchanged since it was built: no need to wait for the battle (a
        hit = _MEMO.get(id(battle))                    # change half made is the one before it; its event follows)
        if hit is not None and hit[0] == _view_key(battle):
            return hit[1] if shared else clone(hit[1])
    except RuntimeError:                               # the battle changed while we looked: ask with the lock
        pass
    with battle.lock:
        key = _view_key(battle)
        hit = _MEMO.get(id(battle))
        if hit is None or hit[0] != key:
            if len(_MEMO) > 16:                        # (closed duels')
                _MEMO.clear()
            hit = _MEMO[id(battle)] = (key, _build_view(battle))
        return hit[1] if shared else clone(hit[1])


def _view_key(battle) -> tuple:
    pcs = sorted(c["character"] for c in battle.b["combatants"] if c["kind"] == "pc" and c.get("character"))
    return (id(battle), id(battle.b), battle.version, character_saves(), tuple((n, file_stamp(n)) for n in pcs),
            id(bestiary.all))                           # a custom creature saved (a new portrait): a new list


def _build_view(battle) -> dict:
    view = battle.view()
    levels, enemy_xp = [], []
    for c in view["combatants"]:
        c["sub"], c["token"] = "", None
        m = bestiary.get(c["monster"]) if c["kind"] == "enemy" and c.get("monster") else None
        if m:
            c["sub"] = f"CR {m['cr']} {m['type']}"
            c["token"], c["framed"] = portraits.of_monster(m)
        if c["kind"] == "pc":
            char = Character.load(c["character"]) if c.get("character") else None
            if char:
                c["token"], c["framed"] = portraits.of(char.d)
                levels.append(char.total_level)
        elif c["kind"] == "enemy":
            enemy_xp.append(c["xp"])
        c["out"] = c["hp"] <= 0 if c["kind"] == "enemy" else bool(c.get("downed"))
        c["veil"] = veil_of(c)
        c["extra"] = _extra(c)
        c["health"] = health_word(c["hp"], c["max_hp"])
        c["hp_shown"] = c["kind"] == "pc" or bool(c.get("revealed")) or bool(view.get("reveal_hp"))
    view["difficulty"] = encounter_difficulty(levels, enemy_xp)
    view["picked"] = list(view.get("targets") or ([view["target"]] if view.get("target") else []))
    return view


# a token drawn see-through: (opacity, size, tint) - a banished creature is small and faintest, a hidden one barely faded
VEILS = {"banished": (0.35, 0.55, "#c084fc"), "ethereal": (0.45, 1.0, "#5eead4"), "invisible": (0.5, 1.0, "#bae6fd"),
         "hidden": (0.7, 1.0, "#9ca3af")}


def veil_of(c: dict) -> Optional[str]:
    """Why its token is drawn see-through (a key of VEILS), or None: banished (Banishment, Maze), on the Ethereal Plane
    (Blink, Etherealness), invisible, hidden."""
    effs = c.get("effects") or []
    names = " ".join((e.get("name") or "").lower() for e in effs)
    if any((e.get("mods") or {}).get("banished") for e in effs):
        return "banished"
    if "ethereal" in names or "blinked" in names:
        return "ethereal"
    if "Invisible" in (c.get("conditions") or []) or "invisib" in names:
        return "invisible"
    if any("hidden" in (e.get("mods") or {}) for e in effs):
        return "hidden"
    return None


def _extra(c: dict) -> List[str]:
    """The short notes after a name in the order list: conditions, ally or neutral, effects that change numbers, concentration."""
    out = list(c.get("conditions") or [])
    if c.get("faction") == 0:
        out.append("neutral")
    elif c.get("faction") == 1 and c["kind"] != "pc":
        out.append("ally")
    out += [e["name"] for e in (c.get("effects") or []) if e.get("mods")]
    if c.get("concentrating"):
        out.append("◎ " + c["concentrating"]["spell"])
    if c.get("dead"):
        out.append("dead")
    elif c.get("stable"):
        out.append("stable")
    elif c.get("downed"):
        out.append("down!")
    return out


def find(view: dict, cid: Optional[int]) -> Optional[dict]:
    return next((c for c in view["combatants"] if c["id"] == cid), None) if cid else None


def free_characters(view: dict) -> List[str]:
    """Characters who could still join the battle."""
    inside = {c["character"] for c in view["combatants"] if c["kind"] == "pc"}
    return [n for n in rt().battle.chars.names() if n not in inside]        # (the duel's: only its fighters)


def counts(view: dict) -> Dict[str, int]:
    return {"pcs": sum(1 for c in view["combatants"] if c["kind"] == "pc"),
            "enemies": sum(1 for c in view["combatants"] if c["kind"] == "enemy")}


def end_preview(view: dict) -> Dict[str, int]:
    """What ending now would give: the defeated enemies' XP and each player's share."""
    xp = sum(c["xp"] for c in view["combatants"] if c["kind"] == "enemy" and c["hp"] <= 0)
    pcs = sum(1 for c in view["combatants"] if c["kind"] == "pc")
    return {"xp": xp, "pcs": pcs, "share": xp // pcs if pcs else 0}


# ---------------------------------------------------------------------- the map
def span(c: dict) -> int:
    return max(1, int(c.get("span") or 1))


def at_tile(view: dict, x: int, y: int) -> Optional[dict]:
    """The token covering a tile (the last drawn wins)."""
    for c in reversed(view["combatants"]):
        p = c.get("pos")
        if p and p[0] <= x < p[0] + span(c) and p[1] <= y < p[1] + span(c):
            return c
    return None


def clamp_tile(view: dict, c: dict, x: int, y: int) -> List[int]:
    """Keep a carried token's top-left tile inside the map."""
    m, s = view["map"], span(c)
    return [max(0, min(m["w"] - s, x)), max(0, min(m["h"] - s, y))]


def tile_free(view: dict, cid: int, x: int, y: int) -> bool:
    """Could this combatant stand with its top-left on (x, y)? (The same test the tracker's place() makes: Tiny creatures
    share a tile, four at most.)"""
    c = find(view, cid)
    if not c:
        return False
    s, m = span(c), view["map"]
    if x < 0 or y < 0 or x + s > m["w"] or y + s > m["h"] or floor_at(m, x) != floor_at(m, x + s - 1) or floor_at(m, x) is None:
        return False                                             # (all of it on one floor, not in the gap between two)
    sharing = 0
    for o in view["combatants"]:
        p = o.get("pos")
        if o["id"] != cid and p and x < p[0] + span(o) and x + s > p[0] and y < p[1] + span(o) and y + s > p[1]:
            if not (c.get("tiny") and o.get("tiny")):
                return False
            sharing += 1
    return sharing < 4


TINY = 0.5                                                       # a Tiny token is drawn half a tile across
SLOTS = [(.25, .25), (.75, .25), (.25, .75), (.75, .75)]          # where Tiny tokens without a point of their own stand


def draw_box(view: dict, c: dict) -> Optional[tuple]:
    """(x, y, size) in tile units: where a token is drawn. A Tiny one at its point (`at`), or in a quarter of its tile
    when several share it, else in the middle."""
    p = c.get("pos")
    if not p:
        return None
    if not c.get("tiny"):
        return float(p[0]), float(p[1]), float(span(c))
    at = c.get("at")
    if at and int(at[0]) == p[0] and int(at[1]) == p[1]:
        return at[0] - TINY / 2, at[1] - TINY / 2, TINY
    mates = [o["id"] for o in view["combatants"] if o.get("tiny") and o.get("pos") == p and not (o.get("at") and int(o["at"][0]) == p[0])]
    if len(mates) <= 1:
        return p[0] + .25, p[1] + .25, TINY
    sx, sy = SLOTS[mates.index(c["id"]) % 4]
    return p[0] + sx - TINY / 2, p[1] + sy - TINY / 2, TINY


def at_point(view: dict, x: float, y: float) -> Optional[dict]:
    """The token under a point (tile units): Tiny tokens over the big ones, the last drawn first."""
    best = None
    for c in reversed(view["combatants"]):
        box = draw_box(view, c)
        if box and box[0] <= x < box[0] + box[2] and box[1] <= y < box[1] + box[2]:
            if c.get("tiny"):
                return c
            best = best or c
    return best


def token_tip(view: dict, c: dict) -> str:
    hp = f"  {c['hp']}/{c['max_hp']} HP" if c["hp_shown"] else ""
    where = f"\n{tile_name(*c['pos'])}" if c.get("pos") else ""
    carried = ", ".join(f"{i['name']} ×{i['qty']}" if i["qty"] > 1 else i["name"] for i in c.get("items") or [])
    return f"{c['name']}{hp}  AC {c['ac']}{where}" + (f"\nCarries: {carried}" if carried else "")


# ---------------------------------------------------------------------- a monster's card
_TO_HIT = re.compile(r"([+-]\d+) to hit")
_SAVE_DC = re.compile(r"DC \d+ \w+ saving throw")
_RECHARGE = re.compile(r"\(Recharge\s*[\d–-]+\)", re.I)
_SPELL_LINE = re.compile(r"^\s*([^:]{2,40}):\s*(.+)$")


def _title_case(s: str) -> str:
    return re.sub(r"(?<![\w'])[a-z]", lambda m: m.group(0).upper(), s)         # Otiluke's, not Otiluke'S


def _drop_notes(name: str) -> str:
    """'otiluke's freezing sphere (45 (13d6) damage)' -> "otiluke's freezing sphere": notes in brackets, nested ones too."""
    while True:
        out = re.sub(r"\s*\([^()]*\)\s*", " ", name)
        if out == name:
            return out.replace("(", "").replace(")", "").strip()
        name = out


def _spell_lines(text: str) -> List[dict]:
    """'Cantrips: fire bolt, light' -> [{'label': 'Cantrips', 'spells': ['Fire Bolt', 'Light']}]."""
    out = []
    for ln in text.split("\n"):
        mm = _SPELL_LINE.match(ln)
        if not mm or (re.match(r"^(spellcasting|innate spellcasting)", mm.group(1), re.I) and len(mm.group(2)) > 160):
            continue
        names = [_drop_notes(s).rstrip(".").strip() for s in re.split(r",\s*(?![^()]*\))", mm.group(2).replace("*", ""))]
        names = [_title_case(n) for n in names if n and len(n) < 40]
        if names:
            out.append({"label": mm.group(1), "spells": names})
    return out


def _entry(e: dict, kind: str) -> dict:
    text, name = e.get("text", ""), e.get("name", "")
    hit = _TO_HIT.search(text)
    out = {"name": name, "text": text, "kind": kind, "to_hit": int(hit.group(1)) if hit else None,
           "parts": [list(p) for p in CR.damage_parts(text)], "save": bool(_SAVE_DC.search(text)),
           "recharge": name.split(" (")[0] if _RECHARGE.search(name) else None,
           "announce": kind == "action" and bool(name) and name != "Multiattack"}
    if kind == "spell":
        dc = re.search(r"(?i)\bsave DC (\d+)", text)
        atk = re.search(r"([+-]\d+) to hit with spell attacks", text)
        lvl = re.search(r"(\d+)(?:st|nd|rd|th)-level spellcaster", text)
        out["spell"] = {"dc": int(dc.group(1)) if dc else 13, "has_dc": bool(dc),
                        "attack": int(atk.group(1)) if atk else None, "level": int(lvl.group(1)) if lvl else 1,
                        "lines": _spell_lines(text)}
    return out


def monster_card(monster_id: str) -> Optional[dict]:
    """A monster's stat block cut into the pieces the combat card shows, each roll ready to be clicked. Made once per
    monster (the card asks again after every change of the battle); every call gets its own copy."""
    key = (monster_id, id(bestiary.all))                # (custom monsters read again: a new list)
    if key not in _CARDS:
        if len(_CARDS) > 256:
            _CARDS.clear()
        _CARDS[key] = _monster_card(monster_id)
    return clone(_CARDS[key])


_CARDS: Dict[tuple, Optional[dict]] = {}


def _monster_card(monster_id: str) -> Optional[dict]:
    m = bestiary.get(monster_id)
    if not m:
        return None
    tags = f" ({', '.join(m['tags'])})" if m.get("tags") else ""
    abilities = []
    for a in ABILITIES:
        md = ability_mod(m, a)
        abilities.append({"key": a, "score": m["abilities"][a], "mod": md, "save": CR.monster_save(m["saves"], a, md)})
    lines = [("Armor Class", f"{m['ac']}" + (f" ({m['ac_note']})" if m["ac_note"] else "")),
             ("Hit Points", f"{m['hp']}" + (f" ({m['hp_formula']})" if m["hp_formula"] else "")),
             ("Speed", m["speed"])]
    more = [("Saving Throws", m["saves"]), ("Skills", m["skills"]), ("Vulnerabilities", m["vulnerable"]),
            ("Resistances", m["resist"]), ("Damage Immunities", m["immune"]), ("Condition Immunities", m["condition_immune"]),
            ("Senses", (m["senses"] + ", " if m["senses"] else "") + f"passive Perception {m['passive']}"),
            ("Languages", m["languages"]), ("Challenge", f"{m['cr']} ({m['xp']:,} XP)")]
    sections = []
    for title, key, kind in (("", "traits", "trait"), ("Spellcasting", "spellcasting", "spell"), ("Actions", "actions", "action"),
                             ("Bonus actions", "bonus_actions", "action"), ("Reactions", "reactions", "action"),
                             ("Legendary actions", "legendary", "action")):
        if m.get(key):
            sections.append({"title": title, "note": m["legendary_note"] if key == "legendary" else "",
                             "entries": [_entry(e, kind) for e in m[key]]})
    lore = m.get("description", "") if m.get("source") == "Custom" or m.get("homebrew") or m.get("module") else bestiary.lore(m["id"])
    return {"id": m["id"], "name": m["name"], "head": f"{m['size']} {m['type']}{tags}, {m['alignment']} · {m['source']}",
            "lines": lines, "abilities": abilities, "more": [(k, v) for k, v in more if v], "sections": sections,
            "lore": lore or "", "lair": m.get("lair") or ""}


def usable_on(entry: dict, attacker_id: int, target_id: Optional[int]) -> bool:
    """Can this action be played out on the target by itself (an attack roll or a saving throw)?"""
    return (entry["kind"] in ("action", "trait") and bool(target_id) and target_id != attacker_id
            and (entry["to_hit"] is not None or entry["save"]))


# ---------------------------------------------------------------------- a player character in battle
def pc_actions(character: str) -> dict:
    """A player character's weapons, the spells it can cast now and the slots it may spend."""
    char = rt().characters.get(character)
    attacks = []
    for a in char.attacks():
        dmg = f"{a['dice']}{a['bonus']:+d}" if a.get("dice") and a.get("bonus") else (a.get("dice") or str(a.get("bonus", "")))
        attacks.append({"name": a["name"], "attack": a["attack"], "damage": dmg, "type": a.get("type", "")})
    spells = sorted(({"name": s["name"], "level": s["level"], "ritual": bool(s.get("ritual"))}
                     for s in SC.spell_known_or_prepared(char)), key=lambda s: (s["level"], s["name"]))
    left = SC.slots_remaining(char)
    slots = [("auto", None)] + [(k, int(k)) for k in sorted((k for k in left if k != SC.PACT_KEY), key=int) if left[k] > 0]
    if left.get(SC.PACT_KEY):
        slots.append(("pact", SC.PACT_KEY))
    return {"attacks": attacks, "spells": spells, "slots": slots, "slots_left": {k: v for k, v in left.items()}}


def spell_tip(name: str) -> str:
    return spell_detail(name)
