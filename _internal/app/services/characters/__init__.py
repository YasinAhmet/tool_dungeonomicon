"""Everything that changes a character, as one service (`rt().characters`) assembled from focused parts.

    base.py       lookup, commit (save + log + refresh) and roll announcements
    levels.py     creation, level up, editing earlier levels
    vitals.py     hit points, death saves, rests, hit dice, conditions
    rolls.py      checks, saves, attacks, damage
    spells.py     casting, slots, prepared spells, class resources
    inventory.py  items, equipment, attunement, coins, trade
    details.py    notes, personal details, proficiencies
    roster.py     rename, archive, import, ownership, snapshots

A new kind of change gets its own module with a mixin class, added to CharacterService below.
"""
from .base import CharacterServiceBase
from .details import DetailsMixin
from .inventory import InventoryMixin
from .levels import LevelsMixin
from .rolls import RollsMixin
from .roster import RosterMixin
from .spells import SpellsMixin
from .vitals import VitalsMixin


class CharacterService(LevelsMixin, VitalsMixin, RollsMixin, SpellsMixin, InventoryMixin, DetailsMixin, RosterMixin,
                       CharacterServiceBase):
    """Every mutation of a character goes through here, so logging, Discord and the windows stay in step."""
