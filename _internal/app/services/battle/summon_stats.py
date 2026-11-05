"""Stat blocks that depend on whoever summoned them (Tasha's spirits, class companions): the summoner's numbers written in.

fill(monster_id, ctx) -> a copy of the stat block, ctx = {'attack', 'dc', 'level' (spell level), 'pb', 'variant'}:
    "Melee Weapon Attack:  to hit" (the bonus left out) / "your spell attack modifier to hit" -> "+attack to hit"
    "summonSpellLevel", "PB", "+3 plus PB", "your spell save DC" -> numbers; "1d8 + 4 + 3" -> "1d8 + 7"
    "a number of attacks equal to half this spell's level (rounded down)" -> "makes N attacks"
    entries for another variant ("Claws (Slaad Only)" on a Beholderkin spirit) are dropped
owner_class(m) -> the class whose level the stat block's hit points use ('Ranger' for Beast of the Land), or None.
hp(m, ctx) -> hit points from "5 + five times your ranger level" or a plain number, None when it can't tell.
"""
import copy
import json
import re
from functools import lru_cache
from typing import Optional

from ...rules.monsters import bestiary

SECTIONS = ("traits", "actions", "bonus_actions", "reactions", "legendary")
# companions whose armor class adds the proficiency bonus (lost on import: the data says AC 10)
AC_PLUS_PB = {"Beast of the Land|TCE": 13, "Beast of the Sea|TCE": 13, "Beast of the Sky|TCE": 13, "Drake Companion|FTD": 14}
CLASS_ABILITY = {"Ranger": "wis", "Artificer": "int", "Druid": "wis", "Bard": "cha", "Wizard": "int", "Cleric": "wis",
                 "Sorcerer": "cha", "Warlock": "cha", "Paladin": "cha"}


def needs_summoner(m: dict) -> bool:
    """A stat block with blanks only a summoner can fill."""
    text = json.dumps([m.get(s) for s in SECTIONS])
    return bool(re.search(r"summonSpellLevel|\bPB\b|:\s{2,}to hit|your spell (?:attack modifier|save DC)", text))


def stock(m: dict) -> dict:
    """The numbers of a spirit put in the battle on its own (no summoner): a caster of the spell's lowest level
    ("... for each spell level above 4th"), its proficiency bonus and a +3/+4/+5 spellcasting modifier."""
    g = re.search(r"above (\d+)", m.get("hp_formula") or "")
    lvl = int(g.group(1)) if g else 3
    pb = 2 + max(0, 2 * lvl - 2) // 4
    mod = 3 if lvl < 3 else 4 if lvl < 5 else 5
    return {"level": lvl, "pb": pb, "attack": pb + mod, "dc": 8 + pb + mod}


def owner_class(m: dict) -> Optional[str]:
    hit = re.search(r"your (\w+) level", m.get("hp_formula") or "")
    return hit.group(1).capitalize() if hit else None


def _sum_dice(text: str) -> str:
    """'1d8 + 4 + 3' -> '1d8 + 7', '+3 + 2 to hit' -> '+5 to hit'."""
    def add(m):
        nums = [int(x) for x in re.findall(r"\d+", m.group(2))]
        return f"{m.group(1)} + {sum(nums)}" if m.group(1) else f"+{sum(nums)}"
    text = re.sub(r"(\d+d\d+)((?:\s*\+\s*\d+){2,})", add, text)
    return re.sub(r"()\+(\d+(?:\s*\+\s*\d+)+)(?= to hit)", add, text)


def _fill_text(text: str, ctx: dict) -> str:
    atk, pb = ctx.get("attack"), ctx.get("pb")
    if ctx.get("burst") and "explodes" in text:       # Improved Reanimation: the Death Burst of a Reanimated Companion
        text = text.replace("2d4 Necrotic damage", f"{ctx['burst']} Necrotic damage")
    if ctx.get("int") is not None and "plus your Intelligence modifier" in text:
        text = text.replace("plus your Intelligence modifier", f"+ {ctx['int']}")
    if atk is not None:                                # the Reanimated Companion's blanks: a swipe and a burst (the import lost their wording)
        text = re.sub(r"^m Bonus equals your spell attack modifier, reach (\d+) ft\. Hit: (\d+d\d+) plus your Intelligence modifier (\w+) damage",
                      lambda g: f"Melee Weapon Attack: +{atk} to hit, reach {g.group(1)} ft., one target. Hit: {g.group(2)} + {ctx.get('int', 0)} {g.group(3).lower()} damage", text)
    if ctx.get("dc") is not None:
        text = re.sub(r"dex DC equals , each creature in a 10-foot Emanation originating from the companion\.\s+(\d+d\d+) Necrotic damage\.\s+Half damage\.",
                      lambda g: f"Each creature within 10 feet of the companion must make a DC {ctx['dc']} Dexterity saving throw, taking "
                                f"{ctx.get('burst') or g.group(1)} necrotic damage on a failed save, or half as much damage on a successful one.", text)
    if atk is not None:
        text = re.sub(r"Attack:\s+(?:your spell attack modifier\s+)?to hit", f"Attack: +{atk} to hit", text)
    if ctx.get("spell") == "homunculus servant" and ctx.get("level") is not None:       # the EFA spell's Force Strike: 1d6 + the spell's level
        text = re.sub(r"1d4 \+ PB", f"1d6 + {int(ctx['level'])}", text)
        text = re.sub(r"Attack:\s*\+(\d+) plus PB to hit", lambda m: f"Attack: +{int(m.group(1)) + (pb or 0)} to hit", text)
    if ctx.get("level") is not None:
        lvl = int(ctx["level"])
        text = text.replace("summonSpellLevel", str(lvl))
        text = re.sub(r"makes a number of ((?:\w+ )*?)attacks equal to half (?:this spell's level|the spell's level|the level of the spell) "
                      r"\(round(?:ed)? down\)", lambda m: f"makes {max(1, lvl // 2)} {m.group(1)}attacks", text)
    if pb is not None:
        text = re.sub(r"\s+plus PB\b", f" + {pb}", text)
        text = re.sub(r"\bPB\b", str(pb), text)
    if ctx.get("dc") is not None:                      # "a Dexterity saving throw against your spell save DC": the usual order
        text = re.sub(r"escape DC equals your spell save DC", f"escape DC {ctx['dc']}", text)
        text = re.sub(r"(?:an? )?(Strength|Dexterity|Constitution|Intelligence|Wisdom|Charisma) saving throw against your spell save DC",
                      lambda m: f"a DC {ctx['dc']} {m.group(1)} saving throw", text)
        text = re.sub(r"(?:against )?your spell save DC", f"against DC {ctx['dc']}", text)
        text = text.replace("against against", "against")
    return _sum_dice(text)


def _variant_ok(name: str, variant: Optional[str]) -> bool:
    only = re.search(r"\(([^)]*?) Only\)", name)
    if not only or not variant:
        return True
    return variant.lower() in [v.strip().lower() for v in re.split(r",|\bor\b|\band\b", only.group(1))]


@lru_cache(maxsize=512)
def _fill_cached(monster_id: str, key: str) -> Optional[dict]:
    m = bestiary.get(monster_id)
    if not m:
        return None
    ctx = json.loads(key)
    out = copy.deepcopy(m)
    for sec in SECTIONS:
        out[sec] = [dict(e, text=_fill_text(e.get("text", ""), ctx)) for e in out.get(sec) or [] if _variant_ok(e.get("name", ""), ctx.get("variant"))]
    for fld, sep in (("speed", ","), ("vulnerable", ";"), ("resist", ";"), ("immune", ";")):     # "fly 30 ft. (hover; Flyer only)", "fire (Tree only); slashing (Fungus or Vine only)"
        if ctx.get("variant") and re.search(r"\bonly\)", out.get(fld) or "", re.I):
            keep = []
            for part in str(out[fld]).split(sep):
                g = re.search(r"\(([^)]*?)\s+only\)", part, re.I)
                if g and not _variant_ok(f"x ({g.group(1).replace(';', ',')} Only)", ctx["variant"]):
                    continue
                keep.append(re.sub(r"\s*\([^)]*?\bonly\)", "", part, flags=re.I).strip())
            out[fld] = (sep + " ").join(p for p in keep if p)
    kinds = re.findall(r"acid|cold|fire|lightning|poison|necrotic|radiant|psychic|thunder|force", (m.get("resist") or "").lower())
    if kinds:                                          # the Draconic Spirit's breath: "a type this dragon has resistance to (your choice)"
        for sec in SECTIONS:
            for e in out[sec]:
                e["text"] = re.sub(r"(\d+d\d+(?: ?\+ ?\d+)?) damage of a type (?:this|the) \w+ has resistance to(?: \(your choice\))?",
                                   lambda g: f"{g.group(1)} {kinds[0]} damage", e["text"])
    if monster_id in AC_PLUS_PB and ctx.get("pb") is not None:
        out["ac"] = AC_PLUS_PB[monster_id] + ctx["pb"]
    return class_bonuses(out, ctx)


def class_bonuses(out: dict, ctx: dict) -> dict:
    """What the summoner's class adds to a companion: Improved Defender's +2 AC, a Beast Master's Bestial Fury (two attacks), a
    drakewarden's Draconic Essence, wings, size and Magic Fang."""
    if ctx.get("bonus_ac"):
        out["ac"] = int(out.get("ac") or 10) + int(ctx["bonus_ac"])
    if ctx.get("fury") and not any((e.get("name") or "").lower() == "multiattack" for e in out["actions"]):
        atk = next((e for e in out["actions"] if "Weapon Attack" in (e.get("text") or "")), None)
        if atk:
            out["actions"] = [{"name": "Multiattack", "text": f"The beast makes two {atk['name']} attacks."}] + list(out["actions"])
    ess = ctx.get("essence")
    if ess:
        out["immune"] = ess
        if ctx.get("bond"):
            speed = int((re.match(r"(\d+)", str(out.get("speed") or "30")) or [0, 30])[1])
            out["speed"] = f"{speed} ft., fly {speed} ft."
            out["size"] = "Large" if ctx["bond"] >= 2 else "Medium"
            more = f" plus {ctx['bond']}d6 {ess} damage"
            out["actions"] = [dict(e, text=re.sub(r"(piercing damage)", lambda g: g.group(1) + more, e.get("text") or "", count=1)) if e.get("name") == "Bite" else e
                              for e in out["actions"]]
    return out


def fill(monster_id: str, ctx: Optional[dict]) -> Optional[dict]:
    if not ctx:
        return bestiary.get(monster_id)
    return _fill_cached(monster_id, json.dumps(ctx, sort_keys=True))


def hp(m: dict, ctx: dict) -> Optional[int]:
    """Hit points of a companion or conjured object: 'N', '5 + five times your ranger level', '2 + your Intelligence
    modifier + five times your artificer level', '1 + your Intelligence modifier + your artificer level'."""
    f = (m.get("hp_formula") or "").strip()
    if re.fullmatch(r"\d+", f):
        return int(f)
    hit = re.match(r"(\d+)\s*(?:\+|plus)\s*(your Intelligence modifier\s*\+\s*)?(?:(one|two|three|four|five|six) times )?your \w+ level", f)
    if not hit:                                         # "5 plus five times your Artificer level", "4 + four times your Warlock level"
        return None
    lvl = int(ctx.get("owner_level") or 1)
    times = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6}.get(hit.group(3) or "", 1)
    return max(1, int(hit.group(1)) + (int(ctx.get("int") or 0) if hit.group(2) else 0) + times * lvl)
