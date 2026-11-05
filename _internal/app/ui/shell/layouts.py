"""Window layouts: ready-made presets, and the user's own saved ones (Documents\\Dungeonomicon\\layouts\\*.json).

A preset is a list of steps (panel_id, area[, beside_panel[, share]]):
    ("characters.roster", "left", None, 0.22)        # dock at the left edge, taking 22% of the width
    ("world.map", "center", "battle.map")             # a tab next to the Battle map
    ("audio.manager", "bottom", "battle.map")         # below the Battle map
Panels that don't exist are skipped, so presets keep working while features come and go.
"""
import json
import os
import re
from typing import Dict, List, Optional

from ...core.storage import read_json, write_json

FOLDER = "layouts"
LAST = "_last"                  # what was open when the editor closed

PRESETS: Dict[str, Dict] = {
    "Game night": {
        "description": "Run a session: the party on the left, the maps and sound in the middle, the inspector (the "
                       "picked character's sheet, rules, the map's selection) on the right; Enter opens the log, chat "
                       "and dice over the map.",
        "steps": [
            ("battle.map", "center"),
            ("world.map", "center", "battle.map"),
            ("audio.manager", "center", "battle.map"),
            ("characters.roster", "left", "battle.map", 0.2),
            ("app.inspector", "right", "battle.map", 0.3),
        ],
    },
    "Battle": {
        "description": "Fight: the map in the middle (Edit to set it up, Play to run the turns) with the initiative order "
                       "and the inspector beside it; Enter opens the log, chat and dice over the map.",
        "steps": [
            ("battle.map", "center"),
            ("app.inspector", "right", "battle.map", 0.24),
        ],
    },
    "Travel": {
        "description": "Between fights: the world map with the party, its route and food in the middle, the inspector "
                       "beside it; Enter opens the log, chat and dice over it.",
        "steps": [
            ("world.map", "center"),
            ("app.inspector", "right", "world.map", 0.3),
        ],
    },
    "Characters": {
        "description": "Build and manage characters: the party and players beside the inspector, which shows the picked "
                       "character's sheet.",
        "steps": [
            ("app.inspector", "center"),
            ("characters.roster", "left", "app.inspector", 0.3),
        ],
    },
    "Prep": {
        "description": "Prepare content: browse the rules, write homebrew, make creatures, set up a fight.",
        "steps": [
            ("library.rules", "center"),
            ("battle.map", "center", "library.rules"),
            ("world.map", "center", "library.rules"),
            ("app.inspector", "right", "library.rules", 0.3),
        ],
    },
    "Sound": {
        "description": "The table's sound and the Discord bot that carries it, the party with the player portal beside it.",
        "steps": [
            ("audio.manager", "center"),
            ("characters.roster", "right", "audio.manager", 0.35),
        ],
    },
}
DEFAULT = "Game night"


def _path(name: str) -> str:
    safe = re.sub(r'[<>:"/\\|?*]+', "_", name).strip() or "layout"
    return os.path.join(FOLDER, f"{safe}.json")


def saved() -> List[str]:
    """Names of the user's saved layouts."""
    if not os.path.isdir(FOLDER):
        return []
    out = []
    for f in sorted(os.listdir(FOLDER)):
        if f.endswith(".json") and not f.startswith("_"):
            data = read_json(os.path.join(FOLDER, f), {}) or {}
            out.append(data.get("name") or f[:-5])
    return out


def load(name: str) -> Optional[dict]:
    data = read_json(_path(name), None)
    return data.get("layout") if isinstance(data, dict) else None


def save(name: str, layout: dict):
    os.makedirs(FOLDER, exist_ok=True)
    write_json(_path(name), {"name": name, "layout": layout})


def delete(name: str):
    try:
        os.remove(_path(name))
    except OSError:
        pass


def export_to(path: str, name: str, layout: dict):
    with open(path, "w", encoding="utf-8") as f:
        json.dump({"name": name, "layout": layout}, f, ensure_ascii=False, indent=1)


def import_from(path: str) -> str:
    """Copy a layout file into the saved layouts; returns its name."""
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    name = data.get("name") or os.path.splitext(os.path.basename(path))[0]
    save(name, data["layout"])
    return name
