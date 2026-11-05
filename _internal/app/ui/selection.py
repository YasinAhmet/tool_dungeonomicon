"""What the user is looking at, shared by every window (like Unity's selection).

    show_content("spells", "Fireball")         # the Inspector window shows the entry
    hub().content.connect(lambda kind, ident: ...)

The selected character is part of the runtime (rt().select_character, events.SELECTION) because the Discord
console commands use it too.
"""
from typing import Optional

from PySide6.QtCore import QObject, Signal


class SelectionHub(QObject):
    content = Signal(str, str)          # kind, ident (a kind of app.rules.describe.KINDS)
    combatant = Signal(int)             # a battle combatant id (0: none selected)
    battle_pick = Signal(object, object)   # the Battle map's canvas and what it has selected: (kind, id), or None

    def __init__(self):
        super().__init__()
        self.last_content: Optional[tuple] = None
        self.last_battle_pick: Optional[tuple] = None   # (canvas, (kind, id)) while something on the map is selected


_hub: Optional[SelectionHub] = None


def hub() -> SelectionHub:
    global _hub
    if _hub is None:
        _hub = SelectionHub()
    return _hub


def show_content(kind: str, ident: str):
    h = hub()
    h.last_content = (kind, ident)
    h.content.emit(kind, ident)


def show_battle_pick(canvas, sel: Optional[tuple]):
    """The Battle map selected something (a creature, prop, picture, area, item on the ground; None: nothing)."""
    h = hub()
    h.last_battle_pick = (canvas, sel) if sel else None
    try:
        h.battle_pick.emit(canvas, sel)
    except RuntimeError:                # the editor is closing: the hub went first
        pass
