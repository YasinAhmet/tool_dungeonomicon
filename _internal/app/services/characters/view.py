"""Read-only data the character windows show: the whole sheet in one dict, spell pools, the roster summary."""
import re
from typing import List, Optional

from ...core import portraits
from ...core.runtime import rt
from ...rules import document, engine as E, sheet
from ...rules import spellcasting as SC
from ...rules import combat_feats as CF
from ...rules.character import CONDITIONS, Character
from ...rules.data import rules
from ..common import ServiceError


def summary(c: Character, owner: Optional[int] = None) -> dict:
    """One roster line (with what a DM checks at a glance: AC, passive Perception, speed)."""
    out = {"name": c.name, "race": c.race_display, "classes": c.class_summary, "level": c.total_level,
           "hp": c.current_hp, "max_hp": c.max_hp, "temp_hp": c.temp_hp, "conditions": list(c.d.get("conditions") or []),
           "created": c.is_created, "owner": owner, "line": sheet.class_line(c), "portrait": portraits.of(c.d)}
    if c.is_created:
        try:
            out.update(ac=c.armor_class()[0], passive=c.passive_perception, speed=c.speed)
        except Exception:  # noqa: BLE001 - odd gear data shows on its own sheet; the roster still lists everyone
            pass
    return out


def portrait_info(name: str) -> dict:
    """What the portrait editor starts from: the race and main class (for the automatic portrait) and the saved one."""
    c = Character.load(name)
    if not c:
        raise ServiceError(f"Character '{name}' not found.")
    return {"race": c.race or "", "class": portraits.main_class(c.d), "portrait": dict(c.d.get("portrait") or {})}


def wearable(item: Optional[dict]) -> bool:
    """Can this item be equipped (armor, shields, weapons, attunable or magic items)?"""
    return bool(item and (item["type"] in ("LA", "MA", "HA", "S") or item.get("weapon") or item.get("attune") is not None
                          or item["magic"]))


USE_RE = re.compile(r"regain \d+d\d+(?: ?\+ ?\d+)? hit points")


def usable(item_name: str) -> bool:
    """Is this a consumable that 'Use' uses up (potions, scrolls, food, rations)? See CharacterService.use_item."""
    item = rules.item(item_name)
    if not item:
        return "ration" in item_name.lower()
    return item["type"] in ("P", "SC", "FD") or "ration" in item["name"].lower() or bool(USE_RE.search(item.get("text") or ""))


def item_price_gp(item_name: str) -> Optional[float]:
    """The list price of one item in gold pieces (None for unknown or priceless items)."""
    item = rules.item(item_name)
    return item["value"] / 100 if item and item.get("value") else None


def proficiency_options() -> dict:
    """What the proficiency editor suggests for each kind: {'armor', 'weapons', 'tools', 'languages'}."""
    from ...rules import custom_background as CB
    return {"armor": ["light", "medium", "heavy", "shield"],
            "weapons": ["simple", "martial"] + sorted({w["name"].lower() for w in rules.weapons()}),
            "tools": CB.tool_pool(), "languages": rules.all_languages()}


def sheet_data(name: str) -> dict:
    """Everything a character sheet window shows."""
    c = Character.load(name)
    if not c:
        raise ServiceError(f"Character '{name}' not found.")
    c._frozen = {}                                     # only read here: equipped items and scores worked out once
    doc = document.build(c)
    doc.pop("casters", None)
    nxt = E.xp_for_next_level(c.total_level) if c.total_level else 300
    casters = []
    for info in SC.casters(c):
        sp = SC.class_spells(c, info["class"])
        casters.append({"class": info["class"], "prepared": info["prepared"], "known": info["known"],
                        "spellbook": info["spellbook"], "prepared_now": sp["prepared"]})
    milestone = bool(c.d["choices"].get("milestone"))
    return {
        "doc": doc, "vitals": sheet.vitals(c), "name": c.name, "line": sheet.class_line(c),
        "death_saves": c.d["death_saves"], "conditions": c.conditions, "all_conditions": CONDITIONS,
        "exhaustion": c.d["exhaustion"], "inspiration": c.d["inspiration"], "xp": c.xp, "next_xp": nxt,
        "milestone": milestone, "can_level": c.total_level < E.MAX_LEVEL and (milestone or c.total_level < c.level_from_xp),
        "can_revert": c.can_revert, "can_edit_levels": c.total_level > 1, "can_edit_origin": c.is_created,
        "revert_to": c.d["level_history"][-1]["summary"] if c.can_revert else None,
        "hit_dice": c.hit_dice(), "classes": c.classes, "currency": c.currency, "notes": c.notes,
        "inventory": [{**e, "tip": document._item_tip(c, e), "attunable": (rules.item(e["name"]) or {}).get("attune") is not None,
                       "wearable": wearable(rules.item(e["name"])), "usable": usable(e["name"])} for e in c.inventory],
        "details": c.d["details"], "hp_bonus": c.d["hp"]["bonus"], "temp_hp": c.temp_hp,
        "owner": rt().players.owner_of(c.name), "casters": casters, "slots": SC.spell_slots(c),
        "alignment": c.alignment, "background": c.background, "feats": c.d["feats"], "sources": list(c.sources),
        "toggles": CF.state(c), "portrait": portraits.of(c.d),
    }


def spell_pool(name: str, class_name: str, mode: str = "prepare") -> dict:
    """Spells a caster may prepare (mode 'prepare') or copy into the spellbook (mode 'copy')."""
    c = rt().characters.get(name)
    info = next((i for i in SC.casters(c) if i["class"] == class_name), None)
    if not info:
        raise ServiceError(f"{c.name} isn't a {class_name} caster.")
    sp = SC.class_spells(c, class_name)
    if mode == "copy":
        pool = [s["name"] for s in SC.eligible_spells(c, info) if s["name"] not in sp["spellbook"]]
        return {"pool": pool, "count": 1, "selected": []}
    pool = sp["spellbook"] if info["spellbook"] else [s["name"] for s in SC.eligible_spells(c, info)]
    free = SC.always_prepared(c, class_name)
    return {"pool": [n for n in pool if n not in free], "count": info["prepared"], "selected": sp["prepared"]}


def roster() -> List[dict]:
    """Every character, sorted by name, with its owner."""
    owners = {}
    for uid, p in rt().players.all().items():
        for n in p["characters"]:
            owners[n] = uid
    chars = [c for c in (Character.peek(n) for n in Character.list_characters()) if c]       # only read: the kept sheets
    return [summary(c, owners.get(c.name)) for c in sorted(chars, key=lambda c: c.name.lower())]
