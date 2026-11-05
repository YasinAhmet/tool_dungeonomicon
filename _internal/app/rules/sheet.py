"""Human-readable views of a character, shared by the GUI, Discord embeds and text commands."""
from typing import Dict, List, Tuple

from . import engine as E
from . import spellcasting as SC
from .character import Character
from .data import rules
from .resources import resource_list


def hp_bar(char: Character, width: int = 10) -> str:
    filled = round(char.hp_fraction * width)
    return "█" * filled + "░" * (width - filled)


def title(char: Character) -> str:
    bits = [char.race_display, char.class_summary]
    return " · ".join(b for b in bits if b and b != "No race")


def class_line(char: Character) -> str:
    """'Level 5 Wizard (School of Evocation) / Fighter 2'."""
    parts = []
    for c in char.classes:
        sub = f" ({c['subclass']})" if c.get("subclass") else ""
        parts.append(f"{c['name']} {c['level']}{sub}")
    return f"Level {char.total_level} — " + " / ".join(parts) if parts else "Not created"


def vitals(char: Character) -> Dict[str, object]:
    ac, why = char.armor_class()
    nxt = E.xp_for_next_level(char.total_level) if char.total_level else 300
    return {
        "hp": char.current_hp, "max_hp": char.max_hp, "temp_hp": char.temp_hp, "ac": ac, "ac_note": why,
        "initiative": char.initiative, "speed": char.speed, "proficiency": char.proficiency_bonus,
        "passive_perception": char.passive_perception, "xp": char.xp, "next_xp": nxt,
        "hit_dice": ", ".join(f"{d['total'] - d['used']}/{d['total']}d{d['die']}" for d in char.hit_dice().values()),
        "conditions": list(char.conditions), "exhaustion": char.d["exhaustion"], "inspiration": char.d["inspiration"],
        "darkvision": char.darkvision, "size": char.size,
    }


def signed(n: int) -> str:
    return f"{n:+d}"


def abilities(char: Character) -> List[Tuple[str, int, int, int, bool]]:
    """[(Abbr, score, modifier, save bonus, save proficient)] in Str..Cha order."""
    saves = char.saving_throws()
    return [(E.ABILITY_SHORT[a], char.ability_score(a), char.mod(a), saves[a]["bonus"], saves[a]["proficient"])
            for a in E.ABILITIES]


def skills(char: Character) -> List[Tuple[str, str, int, str]]:
    """[(skill, Abbr, bonus, marker)] marker: '◆' expertise, '●' proficient, '○' none."""
    return [(name, E.ABILITY_SHORT[s["ability"]], s["bonus"], "◆" if s["expertise"] else "●" if s["proficient"] else "○")
            for name, s in char.skills().items()]


def inventory_lines(char: Character) -> List[str]:
    lines = []
    for e in char.inventory:
        flags = ("E" if e.get("equipped") else "") + ("A" if e.get("attuned") else "")
        qty = f" ×{e['qty']}" if e["qty"] != 1 else ""
        lines.append(f"{e['name']}{qty}" + (f" [{flags}]" if flags else ""))
    return lines


def money_text(char: Character) -> str:
    return "  ".join(f"{n} {c}" for c, n in char.currency.items() if n) or "no coins"


def slots_text(char: Character) -> str:
    total = SC.spell_slots(char)
    remaining = SC.slots_remaining(char)
    parts = [f"{E.ordinal(i + 1)}: {remaining.get(str(i + 1), 0)}/{n}" for i, n in enumerate(total["slots"]) if n]
    if total["pact"]:
        parts.append(f"Pact (lvl {total['pact']['level']}): {remaining.get(SC.PACT_KEY, 0)}/{total['pact']['slots']}")
    return " · ".join(parts) or "no spell slots"


def spells_by_level(char: Character) -> Dict[int, List[str]]:
    out: Dict[int, List[str]] = {}
    for s in SC.spell_known_or_prepared(char):
        label = s["name"] + (" (r)" if s["ritual"] else "") + (" (c)" if s["concentration"] else "")
        out.setdefault(s["level"], []).append(label)
    return out


def feature_groups(char: Character) -> Dict[str, List[str]]:
    groups: Dict[str, List[str]] = {}
    for f in char.features():
        groups.setdefault(f["source"], []).append(f["name"])
    return groups


def resources_text(char: Character) -> List[str]:
    return [f"{r['name']}: {(r['max'] - r['used']) if r['max'] is not None else '∞'}/{r['max'] if r['max'] is not None else '∞'}"
            f" ({r['recharge']} rest)" for r in resource_list(char)]


def sheet_text(char: Character) -> str:
    """Compact plain-text character sheet."""
    v = vitals(char)
    lines = [f"👤 **{char.name}** — {title(char)}", class_line(char),
             f"❤️ HP {v['hp']}/{v['max_hp']}" + (f" (+{v['temp_hp']} temp)" if v["temp_hp"] else "") + f"  {hp_bar(char)}",
             f"🛡️ AC {v['ac']}  ⚡ Init {signed(v['initiative'])}  🏃 {v['speed']} ft  Prof {signed(v['proficiency'])}  "
             f"👁️ Passive Perception {v['passive_perception']}",
             "  ".join(f"**{a}** {s} ({signed(m)})" for a, s, m, _b, _p in abilities(char))]
    if v["conditions"] or v["exhaustion"]:
        lines.append("⚠️ " + ", ".join(v["conditions"] + ([f"Exhaustion {v['exhaustion']}"] if v["exhaustion"] else [])))
    if SC.casters(char) or char.d["racial_spells"]:
        lines.append(f"✨ Slots: {slots_text(char)}")
    lines.append(f"🎒 {len(char.inventory)} items · {money_text(char)} · {char.carried_weight:g} lb ({char.encumbrance})")
    return "\n".join(lines)


CONSUMABLE_TYPES = ("P", "SC", "FD", "EXP")
CONSUMABLE_WORDS = ("ration", "antitoxin", "oil (flask)", "alchemist", "acid (vial)", "holy water", "healer's kit",
                    "torch", "waterskin")


def is_consumable(name: str) -> bool:
    item = rules.item(name)
    if item and item["type"] in CONSUMABLE_TYPES:
        return True
    low = name.lower()
    return any(w in low for w in CONSUMABLE_WORDS)


def consumables(char: Character) -> List[dict]:
    return [e for e in char.inventory if is_consumable(e["name"])]


def roadmap(char, class_name: str) -> list:
    """Levels 1-20 of one class: what each grants, and whether the character has reached it."""
    from . import engine as E
    from .data import rules
    from .leveling import asi_levels
    cls = rules.classes[class_name]
    entry = char.class_entry(class_name)
    have = entry["level"] if entry else 0
    sub = rules.subclass(class_name, entry["subclass"]) if entry and entry.get("subclass") else None
    asi = set(asi_levels(class_name))
    sub_level = cls["subclass_levels"][0] if cls["subclass_levels"] else None
    rows = []
    for lvl in range(1, E.MAX_LEVEL + 1):
        feats = [f["name"] for f in cls["features"] if f["level"] == lvl]
        if sub:
            feats += [f"{f['name']} ({sub['name']})" for f in sub["features"] if f["level"] == lvl]
        elif sub_level == lvl and cls["subclass_title"] not in feats:
            feats.append(f"Choose {cls['subclass_title']}")
        if lvl in asi:
            feats.append("Ability Score Improvement / Feat")
        rows.append({"level": lvl, "proficiency": E.proficiency_bonus(lvl), "features": feats,
                     "reached": lvl <= have, "next": lvl == have + 1})
    return rows
