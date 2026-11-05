"""The short facts an action bar entry's hover card shows: tags (level and school, range, area, duration...), the roll
(attack bonus or save DC, damage dice) and a one- or two-sentence summary. Plain text; the screens lay it out."""
import re
from typing import Optional

from . import combat_rules as CR

ORD = {1: "1st", 2: "2nd", 3: "3rd"}


# a sentence that only sets up a roll ("The target must make a Wisdom saving throw."): the next one says what it does
SETUP = re.compile(r"(saving throws?|ability check|\bcheck)\.$|:$")


def summary(text: str, limit: int = 170) -> str:
    """The first sentence or two of a rules text, whole sentences when it can be. A sentence that only calls for a save
    or check always brings the next one along, so the card says what happens on a failure."""
    t = re.sub(r"\s+", " ", (text or "").split("\n\n")[0]).strip()
    if len(t) <= limit:
        return t
    sents, out = re.split(r"(?<=\.) (?=[A-Z])", t), ""
    while sents:
        s = sents.pop(0)
        if out and SETUP.search(out):
            # skip an exception ("A creature that can't be charmed succeeds...") for the failure that follows it
            pick = next((i for i, x in enumerate([s] + sents[:2]) if re.search(r"\bfail", x)), 0)
            out = f"{out} {([s] + sents)[pick]}"
            del sents[:pick]
            continue
        if out and len(out) + len(s) >= limit:
            break
        out = f"{out} {s}".strip()
    hard = limit * 2
    if len(out) > hard or (len(out) > limit and not re.search(r"[.:]$", out)):
        out = out[:hard if len(out) > hard else limit].rsplit(" ", 1)[0].rstrip(",;") + "…"
    return out


def _area(area: Optional[dict]) -> Optional[str]:
    if not area:
        return None
    shape = {"emanation": "radius", "sphere": "sphere", "cylinder": "cylinder", "cone": "cone", "line": "line", "cube": "cube", "square": "square"}
    s = f"{area['size']}-ft {shape.get(area['shape'], area['shape'])}"
    if area["shape"] == "line" and area.get("width"):
        s = f"{area['size']} × {area['width']} ft line"
    return s


def spell(sp: dict, spec: dict, *, dc: Optional[int] = None, attack: Optional[int] = None, level: Optional[int] = None,
          caster_level: int = 1, mod: int = 0) -> dict:
    lvl = level if level is not None else sp.get("level", 0)
    tags = [("Cantrip" if not lvl else f"{ORD.get(lvl, f'{lvl}th')}-level") + f" {sp.get('school', '').lower()}".rstrip()]
    tags.append(sp.get("range") or "")
    a = _area(spec.get("area"))
    if a:
        tags.append(a)
    dur = sp.get("duration") or ""
    if dur and dur.lower() != "instantaneous":
        tags.append(dur.replace("Concentration, ", "◎ "))
    comp = (sp.get("components") or {}).get("text") if isinstance(sp.get("components"), dict) else None
    if comp:
        tags.append(re.sub(r"\s*\(.*\)", "", comp))
    if sp.get("ritual"):
        tags.append("ritual")
    roll = []
    plan = CR.spell_plan(sp, lvl or None, caster_level, mod)
    if spec.get("atk_type"):
        roll.append(f"{spec['atk_type'].capitalize()} spell attack" + (f" {attack:+d}" if attack is not None else ""))
    elif sp.get("save"):
        roll.append(f"{sp['save'][0][:3].upper()} save" + (f" DC {dc}" if dc else ""))
    dmg = " + ".join(f"{d} {t}" for d, t in plan.get("parts") or [] if t != "healing")
    if plan.get("kind") == "heal" and plan.get("parts"):
        dmg = f"heals {plan['parts'][0][0]}" + (" + mod" if "mod" not in str(plan["parts"][0][0]) else "")
    if dmg:
        roll.append(dmg + (" (half on a save)" if plan.get("half") and sp.get("save") else ""))
    if plan.get("conds"):
        roll.append(", ".join(c.lower() for c in plan["conds"]))
    return {"tags": [t for t in tags if t], "roll": " · ".join(roll), "text": summary(sp.get("text", ""))}


def weapon(w: dict) -> dict:
    tags = [w.get("weapon_name") or w.get("name", "")]
    if w.get("range"):
        tags.append(f"range {w['range']} ft")
    elif "reach" in (w.get("props") or []):
        tags.append("reach 10 ft")
    else:
        tags.append("reach 5 ft")
    tags += [p for p in w.get("props") or [] if p not in ("reach", "unarmed")]
    return {"tags": tags, "roll": f"{w['attack']:+d} to hit · {w.get('damage', '')}", "text": ""}


def stat_block(name: str, text: str) -> dict:
    """A monster's action: its kind, reach or range, the roll and what else it does."""
    tags = []
    m = re.match(r"(Melee or Ranged|Melee|Ranged) (Weapon|Spell) Attack", text or "", re.I)
    if m:
        tags.append(m.group(0).lower().capitalize())
    reach = re.search(r"reach (\d+) ft", text or "")
    rng = re.search(r"range (\d+(?:/\d+)?) ft", text or "")
    if reach:
        tags.append(f"reach {reach.group(1)} ft")
    if rng:
        tags.append(f"range {rng.group(1)} ft")
    area = re.search(r"(\d+)-foot (cone|line|radius|sphere|cube)", text or "")
    if area:
        tags.append(f"{area.group(1)}-ft {area.group(2)}")
    rch = re.search(r"\((Recharge [^)]*|\d+/Day[^)]*|Costs \d Actions)\)", name or "")
    if rch:
        tags.append(rch.group(1))
    roll = []
    hit = re.search(r"([+-]\d+) to hit", text or "")
    pre, post, save = CR.split_save(text or "")
    if hit:
        roll.append(f"{hit.group(1)} to hit")
    if save:
        roll.append(f"{save[0].upper()} save DC {save[1]}")
    parts = CR.damage_parts(pre if hit else text or "")
    if parts:
        roll.append(" + ".join(f"{d} {t}" for d, t in parts))
    rest = re.sub(r"^.*?Hit: [^.]*\.\s*", "", text or "") if hit else text
    return {"tags": tags, "roll": " · ".join(roll), "text": summary(rest if hit else text, 150)}


def plain(text: str) -> dict:
    return {"tags": [], "roll": "", "text": summary(text, 200)}
