"""The duel's character service: the heroes fighting in it, and only them. Their sheets live in memory only
(rules/character.py hold_in_memory), so whatever the duel does to them - hit points, spell slots, items - is never
written anywhere, and no real character can be brought into the duel."""
from typing import Dict, List, Optional

from ...rules.character import Character, forget_memory, hold_in_memory, in_memory
from ..characters import CharacterService
from ..common import ServiceError


class DuelRoster(CharacterService):
    def __init__(self, hooks, players):
        super().__init__(hooks, players)
        self.owners: Dict[str, int] = {}                 # fighter's name -> the player's id

    def add(self, char: Character, user_id: int) -> None:
        hold_in_memory(char)
        self.owners[char.name] = user_id

    def clear(self) -> None:
        for name in list(self.owners):
            forget_memory(name)
        self.owners = {}

    # ---- lookup: the fighters only
    def get(self, name: str) -> Character:
        if name not in self.owners or not in_memory(name):
            raise ServiceError("Only the duel's own fighters can take part in the duel.")
        return Character.load(name)

    def names(self) -> List[str]:
        return list(self.owners)

    def owner_of(self, name: str) -> Optional[int]:
        return self.owners.get(name)

    def characters_of(self, user_id: int) -> List[str]:
        return [n for n, u in self.owners.items() if u == user_id]

    def active_for(self, user_id: int) -> Optional[Character]:
        mine = self.characters_of(user_id)
        return Character.load(mine[0]) if mine else None
