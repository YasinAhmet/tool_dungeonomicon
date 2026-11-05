"""What changes when a character levels up: a before/after comparison of two Character objects."""
from typing import Dict, List, Tuple

from . import engine as E
from . import sheet
from . import spellcasting as SC
from .character import Character
from .resources import resource_list


def _snapshot(c: Character) -> Dict[str, object]:
    scores = c.ability_scores()
    snap: Dict[str, object] = {
        "Level": c.total_level, "Hit points": c.max_hp, "Proficiency bonus": sheet.signed(c.proficiency_bonus),
        "Armor Class": c.armor_class()[0], "Initiative": sheet.signed(c.initiative), "Speed": f"{c.speed} ft",
        "Spell slots": sheet.slots_text(c) if SC.casters(c) else "",
    }
    for a in E.ABILITIES:
        snap[E.ABILITY_NAMES[a]] = scores[a]
    for info in SC.casters(c):
        snap[f"{info['class']} save DC"] = info["dc"]
        snap[f"{info['class']} cantrips"] = info["cantrips"]
        if info["prepared"] is not None:
            snap[f"{info['class']} prepared"] = info["prepared"]
        elif info["known"] is not None:
            snap[f"{info['class']} spells known"] = info["known"]
    for r in resource_list(c):
        snap[r["name"]] = r["max"] if r["max"] is not None else "unlimited"
    return snap


def _spell_names(c: Character) -> set:
    out = set()
    for entry in c.d["spells"].values():
        for key in ("cantrips", "known", "prepared", "spellbook"):
            out.update(entry.get(key, []))
    for names in c.d["choices"].get("bonus_cantrips", {}).values():
        out.update(names)
    return out


def diff(before: Character, after: Character) -> Dict[str, object]:
    """{'stats': [(label, old, new)], 'features': [feature dicts], 'spells': [names], 'proficiencies': [text]}"""
    old, new = _snapshot(before), _snapshot(after)
    stats: List[Tuple[str, object, object]] = []
    for key, value in new.items():
        was = old.get(key, "—" if key not in old else None)
        if was != value:
            stats.append((key, was if was != "" else "—", value if value != "" else "—"))

    seen = {(f["source"], f["name"]) for f in before.features()}
    features = [f for f in after.features() if (f["source"], f["name"]) not in seen]
    spells = sorted(_spell_names(after) - _spell_names(before))

    gained: List[str] = []
    for key, label in (("skills", "Skill"), ("expertise", "Expertise"), ("tools", "Tool"), ("languages", "Language"),
                       ("armor", "Armor"), ("weapons", "Weapon"), ("saves", "Saving throw")):
        gained += [f"{label}: {x}" for x in after.d["proficiencies"][key] if x not in before.d["proficiencies"][key]]
    gained += [f"Feat: {x}" for x in after.d["feats"] if x not in before.d["feats"]]
    return {"stats": stats, "features": features, "spells": spells, "proficiencies": gained}
