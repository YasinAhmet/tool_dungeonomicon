"""Custom backgrounds: build one from chosen proficiencies, with editable starting presets."""
from typing import Dict, List

from ..core.storage import read_json, write_json
from .data import rules
from .leveling import RulesError

CUSTOM_FILE = "data/custom_backgrounds.json"
PRESETS_FILE = "data/background_presets.json"

# Starting presets (editable and saveable in the generator). skills: names; tools: fixed tool names;
# tools_any / languages_any: how many the player chooses; equipment: one item per entry; gp: coins in the pouch.
DEFAULT_PRESETS: List[dict] = [
    {"name": "Arcane Scholar", "skills": ["Arcana", "History"], "tools": [], "tools_any": 0, "languages_any": 2,
     "feature_name": "Library Access", "feature_text": "Years of study earned you a welcome in libraries, colleges and archives. You can usually gain access to "
     "a scholarly collection, and you know whom to ask when you need lore on a subject.",
     "equipment": ["Ink (1 ounce bottle)", "Ink pen", "Parchment (5 sheets)", "Common clothes"], "gp": 10},
    {"name": "Veteran Fighter", "skills": ["Athletics", "Intimidation"], "tools": [], "tools_any": 1, "languages_any": 1,
     "feature_name": "Military Rank", "feature_text": "You served in a fighting company. Soldiers and guards who know of your service defer to you, and you can "
     "usually find a bunk and a meal among fighting folk.",
     "equipment": ["Insignia of rank", "Common clothes"], "gp": 10},
    {"name": "Shady Operator", "skills": ["Deception", "Stealth"], "tools": ["Thieves' Tools"], "tools_any": 1, "languages_any": 0,
     "feature_name": "Criminal Contact", "feature_text": "You have a reliable contact in the underworld who passes along messages and rumours "
     "and knows who is buying and selling.",
     "equipment": ["Crowbar", "Dark common clothes with a hood"], "gp": 15},
    {"name": "Wilderness Wanderer", "skills": ["Survival", "Nature"], "tools": ["Herbalism Kit"], "tools_any": 0, "languages_any": 1,
     "feature_name": "Wanderer", "feature_text": "You have an excellent memory for maps and geography and can always recall the general layout of terrain, "
     "settlements and waterways around you. You can find fresh water and food for yourself and up to five others each day.",
     "equipment": ["Staff", "Hunting trap", "Traveler's clothes"], "gp": 10},
    {"name": "Temple Servant", "skills": ["Insight", "Religion"], "tools": [], "tools_any": 0, "languages_any": 2,
     "feature_name": "Shelter of the Faithful", "feature_text": "You command the respect of those who share your faith. You and your companions can "
     "expect free healing and care at a temple or shrine of your faith.",
     "equipment": ["Holy symbol", "Prayer book", "Vestments", "Common clothes"], "gp": 15},
    {"name": "Silver Tongue", "skills": ["Persuasion", "Insight"], "tools": [], "tools_any": 1, "languages_any": 1,
     "feature_name": "Position of Privilege", "feature_text": "People assume the best of you. You are welcome in high society and can secure an audience "
     "with a local noble or merchant.",
     "equipment": ["Fine clothes", "Signet ring"], "gp": 25},
]
TOOL_POOL_TYPES = ("AT", "INS", "GS", "T")


def presets() -> List[dict]:
    saved = read_json(PRESETS_FILE, None)
    return saved if isinstance(saved, list) and saved else [dict(p) for p in DEFAULT_PRESETS]


def save_preset(spec: dict) -> List[dict]:
    spec = clean(spec)
    items = [p for p in presets() if p["name"].lower() != spec["name"].lower()] + [spec]
    write_json(PRESETS_FILE, items)
    return items


def delete_preset(name: str) -> List[dict]:
    items = [p for p in presets() if p["name"].lower() != name.lower()]
    write_json(PRESETS_FILE, items)
    return items


def reset_presets() -> List[dict]:
    write_json(PRESETS_FILE, [dict(p) for p in DEFAULT_PRESETS])
    return presets()


def tool_pool() -> List[str]:
    return sorted(i["name"] for i in rules.items.values() if i["type"] in TOOL_POOL_TYPES and not i["magic"] and i["source"] == "PHB")


def clean(spec: dict) -> dict:
    name = str(spec.get("name", "")).strip()
    if not name:
        raise RulesError("Give the background a name.")
    skills = []
    for s in spec.get("skills", []):
        try:
            skills.append(rules.skill_name(str(s)))
        except KeyError:
            raise RulesError(f"Unknown skill '{s}'.")
    if len(set(skills)) != len(skills):
        raise RulesError("Each skill can only be chosen once.")
    return {"name": name, "skills": skills, "tools": [str(t).strip() for t in spec.get("tools", []) if str(t).strip()],
            "tools_any": max(0, int(spec.get("tools_any") or 0)), "languages_any": max(0, int(spec.get("languages_any") or 0)),
            "feature_name": str(spec.get("feature_name", "")).strip(), "feature_text": str(spec.get("feature_text", "")).strip(),
            "equipment": [str(e).strip() for e in spec.get("equipment", []) if str(e).strip()], "gp": max(0, int(spec.get("gp") or 0))}


def build_background(spec: dict) -> dict:
    """A rules-engine background entry for a cleaned spec."""
    s = clean(spec)
    fixed = [{"special": e, "qty": 1} for e in s["equipment"]] + [{"item": "pouch", "qty": 1, "label": None, "contains_gp": float(s["gp"])}]
    return {"name": s["name"], "source": "Custom",
            "skills": {"fixed": [x.lower() for x in s["skills"]], "any": 0, "from": [], "count": 0},
            "languages": {"fixed": [], "any": s["languages_any"], "from": [], "count": 0},
            "tools": {"fixed": [t.lower() for t in s["tools"]], "any": s["tools_any"], "from": [], "count": 0},
            "equipment": [{"fixed": fixed}],
            "feature": {"name": s["feature_name"], "text": s["feature_text"]} if s["feature_name"] else None,
            "characteristics": {"personality": [], "ideal": [], "bond": [], "flaw": []},
            "text": "A custom background built from chosen proficiencies.", "spec": s}


def load_custom() -> Dict[str, dict]:
    data = read_json(CUSTOM_FILE, {})
    return data if isinstance(data, dict) else {}


def save_custom(spec: dict) -> str:
    """Create (or replace) a custom background and make it available to character creation. Returns its name."""
    bg = build_background(spec)
    existing = rules.backgrounds.get(bg["name"])
    if existing and existing["source"] != "Custom":
        raise RulesError(f"'{bg['name']}' is already a book background. Pick another name.")
    data = load_custom()
    data[bg["name"]] = bg
    write_json(CUSTOM_FILE, data)
    rules.backgrounds[bg["name"]] = bg
    return bg["name"]
