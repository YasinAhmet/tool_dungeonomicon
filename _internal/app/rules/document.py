"""A complete, renderer-neutral character sheet: the GUI sheet tab and every export format are built from this."""
from typing import Dict, List

from . import breakdown as B
from . import engine as E
from . import sheet
from . import spellcasting as SC
from .character import Character
from .data import rules
from .resources import resource_list


def _tip(lines, title: str = "") -> str:
    return B.text(lines, title)


def build(char: Character) -> Dict:
    """Everything the sheet shows, with a `tip` (source breakdown) on every number and feature."""
    v = sheet.vitals(char)
    effect_map = B.effects(char)
    saves = char.saving_throws()
    details = char.d["details"]

    doc: Dict = {
        "name": char.name,
        "subtitle": " · ".join(x for x in (char.race_display, char.class_summary) if x),
        "line": sheet.class_line(char),
        "info": [(k, val) for k, val in (("Background", char.background), ("Alignment", char.alignment),
                                          ("Experience", f"{char.xp} XP"),
                                          ("Sources", ", ".join(char.sources))) if val],
    }

    ac_lines = B.armor_class(char)
    doc["vitals"] = [
        {"label": "Armor Class", "value": str(v["ac"]), "tip": _tip(ac_lines, "Armor Class")},
        {"label": "Initiative", "value": sheet.signed(v["initiative"]), "tip": _tip(B.initiative(char), "Initiative")},
        {"label": "Speed", "value": f"{v['speed']} ft", "tip": _tip(B.speed(char), "Speed")},
        {"label": "Hit Points", "value": f"{v['hp']}/{v['max_hp']}" + (f" (+{v['temp_hp']})" if v["temp_hp"] else ""),
         "tip": _tip(B.hit_points(char), "Maximum hit points")},
        {"label": "Proficiency", "value": sheet.signed(v["proficiency"]), "tip": _tip(B.proficiency(char), "Proficiency bonus")},
        {"label": "Passive Perception", "value": str(v["passive_perception"]),
         "tip": _tip(B.passive_perception(char), "Passive Perception")},
    ]
    doc["vitals_extra"] = [x for x in (
        f"Hit dice: {v['hit_dice']}" if v["hit_dice"] else "",
        f"Darkvision {v['darkvision']} ft" if v["darkvision"] else "",
        f"Size: {v['size']}",
        "Conditions: " + ", ".join(v["conditions"]) if v["conditions"] else "",
        f"Exhaustion {v['exhaustion']}" if v["exhaustion"] else "",
        "Inspiration" if v["inspiration"] else "") if x]

    doc["abilities"] = [{
        "key": a, "name": E.ABILITY_NAMES[a], "short": E.ABILITY_SHORT[a], "score": char.ability_score(a),
        "mod": char.mod(a), "save": saves[a]["bonus"], "save_prof": saves[a]["proficient"],
        "tip": _tip(B.ability(char, a), E.ABILITY_NAMES[a]),
        "save_tip": _tip(B.save(char, a), f"{E.ABILITY_NAMES[a]} saving throw"),
    } for a in E.ABILITIES]

    doc["skills"] = [{
        "name": name, "ability": E.ABILITY_SHORT[s["ability"]], "bonus": s["bonus"],
        "marker": "◆" if s["expertise"] else "●" if s["proficient"] else "○",
        "tip": _tip(B.skill(char, name), name),
    } for name, s in char.skills().items()]

    p = char.d["proficiencies"]
    doc["proficiencies"] = [(k, ", ".join(sorted(p[key], key=str.lower)) or "—")
                            for k, key in (("Armor", "armor"), ("Weapons", "weapons"), ("Tools", "tools"),
                                           ("Languages", "languages"))]
    origins = B.proficiency_origins(char)
    doc["proficiency_list"] = [{"kind": key, "title": title, "items": [{"name": n, "origin": origins[key].get(n, "")}
                                                                      for n in sorted(p[key], key=str.lower)]}
                               for key, title in B.PROFICIENCY_KINDS]

    doc["attacks"] = [{"name": a["name"], "weapon": a["name"].split(" (")[0], "attack": a["attack"], "damage": a["damage"], "notes": ", ".join(a["notes"]),
                       "tip": f"{a['name']}\nAttack {sheet.signed(a['attack'])}: {E.ABILITY_NAMES[a['ability']]} modifier "
                              f"{sheet.signed(char.mod(a['ability']))} + proficiency/magic/style bonuses"}
                      for a in char.attacks()]

    casting: List[Dict] = []
    for info in SC.casters(char):
        sp = SC.class_spells(char, info["class"])
        casting.append({
            "class": info["class"], "ability": E.ABILITY_NAMES[info["ability"]], "dc": info["dc"],
            "attack": info["attack"], "tip": _tip(B.spell_dc(char, info), f"{info['class']} spellcasting"),
            "prepared": info["prepared"], "cantrips": len(sp["cantrips"]),
        })
    doc["casting"] = casting
    doc["slots"] = sheet.slots_text(char) if casting or char.d["racial_spells"] else ""
    by_level: Dict[int, List[Dict]] = {}
    for s in SC.spell_known_or_prepared(char):
        by_level.setdefault(s["level"], []).append({
            "name": s["name"], "school": s["school"], "time": s["casting_time"], "range": s["range"],
            "duration": s["duration"], "components": s["components"]["text"], "ritual": s["ritual"],
            "concentration": s["concentration"], "text": s["text"], "higher": s["higher_level"],
            "from": s["cast_class"], "uses": s.get("uses") or "",
            "tip": f"{s['name']}\n{s['school']} - {s['casting_time']} - {s['range']} - {s['components']['text']} - "
                   f"{s['duration']}\nSource: {s['cast_class']} spell list ({s['source']})"
                   + (f" - innate {s['uses']}" if s.get("uses") else "") + "\n\n" + s["text"]
                   + (f"\n\nAt higher levels: {s['higher_level']}" if s["higher_level"] else "")})
    doc["spells"] = [{"level": lv, "title": "Cantrips" if lv == 0 else f"{E.ordinal(lv)} level", "spells": rows}
                     for lv, rows in sorted(by_level.items())]

    doc["resources"] = sheet.resources_text(char)
    doc["resource_rows"] = resource_list(char)
    total = SC.spell_slots(char)
    remaining = SC.slots_remaining(char)
    slot_rows = [(str(i + 1), E.ordinal(i + 1), n, remaining.get(str(i + 1), 0)) for i, n in enumerate(total["slots"]) if n]
    if total["pact"]:
        slot_rows.append((SC.PACT_KEY, f"Pact {total['pact']['level']}", total["pact"]["slots"], remaining.get(SC.PACT_KEY, 0)))
    doc["slot_rows"] = slot_rows
    notes = []
    armor, shield = char.equipped_armor(), char.equipped_shield()
    if armor and armor.get("stealth_disadvantage"):
        notes.append("Stealth disadvantage from armor.")
    if armor and not char.armor_proficient(armor):
        notes.append("Not proficient with this armor: disadvantage on STR/DEX checks, saves and attacks; can't cast spells.")
    if shield and not char.armor_proficient(shield):
        notes.append("Not proficient with shields.")
    race = char.race_data()
    if race and race["resist"]:
        notes.append("Resistances: " + ", ".join(sorted(set(race["resist"]))))
    doc["defense_notes"] = notes
    doc["casters"] = [{"class": i["class"], "info": i, "prepared": i["prepared"], "spellbook": i["spellbook"]} for i in SC.casters(char)]

    groups: Dict[str, List[Dict]] = {}
    for f in char.features():
        groups.setdefault(f["source"], []).append({
            "name": f["name"], "level": f["level"], "book": f.get("book", ""), "text": f["text"],
            "tip": B.feature_tip(char, f, effect_map) + ("\n\n" + f["text"] if f["text"] else "")})
    doc["features"] = [{"source": s, "items": items} for s, items in groups.items()]

    doc["inventory"] = [{"name": e["name"], "qty": e["qty"], "equipped": bool(e.get("equipped")),
                         "attuned": bool(e.get("attuned")),
                         "tip": _item_tip(char, e)} for e in char.inventory]
    doc["currency"] = sheet.money_text(char)
    doc["weight"] = f"{char.carried_weight:g} lb ({char.encumbrance})"
    doc["details"] = [(k.capitalize(), details[k]) for k in ("gender", "age", "height", "weight", "eyes", "hair", "skin",
                                                             "deity") if details.get(k)]
    doc["story"] = [(k.capitalize(), details[k]) for k in ("personality", "ideal", "bond", "flaw", "appearance",
                                                          "backstory") if details.get(k)]
    doc["notes"] = [n["text"] if isinstance(n, dict) else str(n) for n in char.notes]
    return doc


def _item_tip(char: Character, entry: dict) -> str:
    item = rules.item(entry["name"])
    if not item:
        return entry["name"]
    lines = [entry["name"], f"Source: {item['source']}" + (f" · {item.get('rarity')}" if item.get("rarity") not in (None, "none") else "")]
    if item.get("ac"):
        lines.append(f"Armor Class {item['ac']}")
    if item.get("dmg1"):
        lines.append(f"Damage {item['dmg1']} {item.get('dmg_type', '')}")
    if item.get("attune") is not None:
        lines.append("Requires attunement" + (" (attuned)" if entry.get("attuned") else " (not attuned - no effect)"))
    return "\n".join(lines) + ("\n\n" + item["text"] if item.get("text") else "")
