"""A double-clicked token on the Battle map: the Inspector comes forward with it - a player character's full sheet, or
anything else's card (its stat block with one-click attacks, saves and spells, hit points and conditions), which the
map's selection already shows there."""
from ...selection import hub


def open_creature(widget, c: dict):
    """Bring the Inspector forward on a combatant: a player character's full sheet, else its card."""
    from ..characters.char_actions import host_of
    from ..workspace.inspector import inspect_character
    if c.get("kind") == "pc" and c.get("character"):
        inspect_character(widget, c["character"])
        return
    host = host_of(widget)
    if host is None:
        return
    dock = host.open("app.inspector", focus=False)
    if dock is not None:
        host.raise_dock(dock)
        if hub().last_battle_pick:
            dock.panel.show_battle_pick(*hub().last_battle_pick)
