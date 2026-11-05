"""Looking characters up and the shared commit/announce plumbing every other part builds on."""
import threading
from typing import Dict, List, Optional

from ...core import events
from ...rules.character import Character, in_memory
from ..players import PlayerManager
from ..common import Hooks, ServiceError


class CharacterServiceBase:
    def __init__(self, hooks: Hooks, players: PlayerManager):
        self.h = hooks
        self.players = players
        self.lock = threading.RLock()
        self._edit_backups: Dict[str, dict] = {}

    # ---- lookup ----
    def get(self, name: str) -> Character:
        char = Character.load(name)
        if not char:
            raise ServiceError(f"Character '{name}' not found.")
        return char

    def names(self) -> List[str]:
        return Character.list_characters()

    def owner_of(self, name: str) -> Optional[int]:
        return self.players.owner_of(name)

    def characters_of(self, user_id: int) -> List[str]:
        names = set(self.names())
        return [n for n in self.players.characters_of(user_id) if n in names]

    def active_for(self, user_id: int) -> Optional[Character]:
        """The character a player's Discord text commands act on."""
        name = self.players.active_of(user_id)
        return Character.load(name) if name else None

    def _commit(self, char: Character, log: str, discord: Optional[str] = None, save: bool = True):
        if save:
            char.save()
        if char.transient:                             # a duel's fighter: nothing for the logs, only the screens
            self.h.notify(events.DUEL)
            self.h.notify(events.CHARACTERS)
            return
        self.h.log(log)
        if discord:
            self.h.discord_log(discord, "xp")
        self.h.notify(events.CHARACTERS)

    def _record_roll(self, who: str, label: str, result: str):
        if self.h.session:
            self.h.session.log_dice_roll(who, label, result)

    def _announce_roll(self, icon: str, char_name: str, label: str, total, detail: str):
        """Every roll is its own compact line in the Discord log channel: who · what · result · the dice."""
        if in_memory(char_name):                       # a duel's fighter: the duel's own log has it
            return
        self.h.discord_log(f"{icon} **{char_name}** · {label} · **{total}** · {detail}", "player_rolls")
