"""Battle constants and small helpers shared by every part of the battle tracker."""

BATTLE_FILE = "data/battle.json"
SETUP, ACTIVE, ENDED = "setup", "active", "ended"
MAX_LOG = 300
MAP_MIN, MAP_MAX, MAP_DEFAULT = 5, 80, (30, 20)
SPANS = {"Tiny": 1, "Small": 1, "Medium": 1, "Small/Medium": 1, "Large": 2, "Huge": 3, "Gargantuan": 4}   # tiles across
# factions: 1 the players', 2 the monsters' (their defaults), 3 and 4 more sides; 0 is neutral - hostile to everyone
FACTIONS = (1, 2, 3, 4, 0)
FACTION_COLORS = {0: "#e0a03a", 1: "#4f8cff", 2: "#e0524d", 3: "#2fb59a", 4: "#b072ff"}


def blank_battle(name: str = "Battle") -> dict:
    return {"name": name, "status": SETUP, "round": 0, "turn": None, "combatants": [], "next_id": 1, "log": [],
            "reveal_hp": False, "summary": None, "target": None, "targets": [], "events": [], "map": {"w": MAP_DEFAULT[0], "h": MAP_DEFAULT[1]}}


def faction_of(c: dict) -> int:
    """A creature's own faction (not who dominates it): the one the DM gave it, else 1 for a player character or an
    ally of theirs (a battle saved before factions), else 2."""
    f = c.get("faction")
    if f is None:
        return 1 if c.get("kind") == "pc" or c.get("ally") else 2
    return int(f)


def faction_colors(b: dict) -> dict:
    """{faction: colour} - the defaults with the DM's colours over them."""
    out = dict(FACTION_COLORS)
    out.update({int(k): v for k, v in (b.get("faction_colors") or {}).items()})
    return out


def health_word(hp: int, max_hp: int) -> str:
    """What players see for an enemy whose exact hit points are hidden."""
    if hp <= 0:
        return "Defeated"
    ratio = hp / max_hp if max_hp else 1
    return "Healthy" if ratio > 0.75 else "Wounded" if ratio > 0.5 else "Bloodied" if ratio > 0.25 else "Critical"
