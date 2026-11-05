import threading
from typing import Dict, List, Optional

from ..core.storage import read_json, write_json

PLAYERS_FILE = "data/players.json"
SESSION_FILE = "data/session_party.json"


def is_manual(user_id) -> bool:
    """A player added by hand (just a name, not a Discord account): their id is negative, so it never meets a Discord
    user ID. The bot can't reach them: the DM sends them their portal link."""
    try:
        return int(user_id) < 0
    except (TypeError, ValueError):
        return False


class PlayerManager:
    """Players and the characters they own. A player is attached one of two ways:

    - Discord: keyed by their Discord user ID. The bot knows them: slash commands, their portal link by DM.
    - Manual: just a name the DM typed, keyed by a negative id (`add_manual`). The DM sends their portal link.

    A character never stores its owner; ownership lives here as the player's
    list of character names. Each player also has an *active* character, which
    is the one Discord text commands act on.

    The DM also ticks the characters playing this session (the *session party*, whoever owns them): the battle's
    Add players window adds them in one click.

    File layout: {"<user_id>": {"name": str, "characters": [str], "active": str|None}} (a negative id: a manual player); the session party is a list of
    names in its own file.
    """

    def __init__(self):
        self._lock = threading.RLock()
        data = read_json(PLAYERS_FILE, {})
        self._players: Dict[str, dict] = data if isinstance(data, dict) else {}
        party = read_json(SESSION_FILE, [])
        self._session: List[str] = [n for n in party if isinstance(n, str)] if isinstance(party, list) else []

    def _save(self):
        write_json(PLAYERS_FILE, self._players)

    def session_party(self) -> List[str]:
        with self._lock:
            return list(self._session)

    def set_in_session(self, character: str, on: bool):
        with self._lock:
            if on and character not in self._session:
                self._session.append(character)
            elif not on and character in self._session:
                self._session.remove(character)
            else:
                return
            write_json(SESSION_FILE, self._session)

    # ---- queries ----
    def all(self) -> Dict[int, dict]:
        with self._lock:
            return {int(uid): {**p, "characters": list(p["characters"]), "manual": is_manual(uid)}
                    for uid, p in self._players.items()}

    def get(self, user_id: int) -> Optional[dict]:
        return self.all().get(user_id)

    def name_of(self, user_id: int) -> Optional[str]:
        player = self._players.get(str(user_id))
        return player["name"] if player else None

    def characters_of(self, user_id: int) -> List[str]:
        with self._lock:
            return list(self._players.get(str(user_id), {}).get("characters", []))

    def owner_of(self, character: str) -> Optional[int]:
        with self._lock:
            for uid, player in self._players.items():
                if character in player["characters"]:
                    return int(uid)
        return None

    def active_of(self, user_id: int) -> Optional[str]:
        with self._lock:
            player = self._players.get(str(user_id))
            if not player or not player["characters"]:
                return None
            return player["active"] if player["active"] in player["characters"] else player["characters"][0]

    def unassigned(self, all_characters: List[str]) -> List[str]:
        with self._lock:
            owned = {c for p in self._players.values() for c in p["characters"]}
        return [c for c in all_characters if c not in owned]

    # ---- changes ----
    def ensure(self, user_id: int, name: Optional[str] = None) -> dict:
        """Create the player if needed and refresh their display name."""
        with self._lock:
            player = self._players.get(str(user_id))
            if player is None:
                player = self._players[str(user_id)] = {"name": name or str(user_id), "characters": [],
                                                       "active": None}
                self._save()
            elif name and player["name"] != name:
                player["name"] = name
                self._save()
            return player

    def add_manual(self, name: str) -> int:
        """A player who isn't on Discord: a new negative id, below every other."""
        name = (name or "").strip()
        if not name:
            raise ValueError("Enter the player's name.")
        with self._lock:
            if any(is_manual(uid) and p["name"].lower() == name.lower() for uid, p in self._players.items()):
                raise ValueError(f"There is already a player named '{name}'.")
            uid = min([int(u) for u in self._players] + [0]) - 1
            self._players[str(uid)] = {"name": name, "characters": [], "active": None}
            self._save()
            return uid

    def rename(self, user_id: int, name: str):
        name = (name or "").strip()
        if not name:
            raise ValueError("Enter the player's name.")
        with self._lock:
            player = self._players.get(str(user_id))
            if player is None:
                raise ValueError("No such player.")
            if is_manual(user_id) and any(is_manual(u) and u != str(user_id) and p["name"].lower() == name.lower()
                                          for u, p in self._players.items()):
                raise ValueError(f"There is already a player named '{name}'.")
            player["name"] = name
            self._save()

    def move(self, old_id: int, new_id: int, name: Optional[str] = None):
        """Hand everything of one player (their characters, the active one) to another and forget the first: a player
        added by hand who joins Discord."""
        with self._lock:
            old = self._players.pop(str(old_id), None)
            if old is None:
                raise ValueError("No such player.")
            player = self.ensure(new_id, name or old["name"])
            for c in old["characters"]:
                if c not in player["characters"]:
                    player["characters"].append(c)
            if not player["active"]:
                player["active"] = old["active"]
            self._save()

    def remove(self, user_id: int):
        with self._lock:
            if self._players.pop(str(user_id), None) is not None:
                self._save()

    def assign(self, user_id: int, character: str, name: Optional[str] = None):
        """Give a character to a player (taking it from any previous owner)."""
        with self._lock:
            self._detach(character)
            player = self.ensure(user_id, name)
            player["characters"].append(character)
            if not player["active"]:
                player["active"] = character
            self._save()

    def unassign(self, character: str):
        with self._lock:
            self._detach(character)
            self._save()

    def set_active(self, user_id: int, character: str):
        with self._lock:
            player = self._players.get(str(user_id))
            if not player or character not in player["characters"]:
                raise ValueError(f"You don't own a character named '{character}'.")
            player["active"] = character
            self._save()

    def rename_character(self, old: str, new: str):
        with self._lock:
            for player in self._players.values():
                player["characters"] = [new if c == old else c for c in player["characters"]]
                if player["active"] == old:
                    player["active"] = new
            self._save()
            if old in self._session:
                self._session = [new if c == old else c for c in self._session]
                write_json(SESSION_FILE, self._session)

    def prune(self, existing: set):
        """Forget characters that no longer exist."""
        with self._lock:
            for player in self._players.values():
                player["characters"] = [c for c in player["characters"] if c in existing]
                if player["active"] not in player["characters"]:
                    player["active"] = player["characters"][0] if player["characters"] else None
            self._save()

    def _detach(self, character: str):
        for player in self._players.values():
            if character in player["characters"]:
                player["characters"].remove(character)
                if player["active"] == character:
                    player["active"] = player["characters"][0] if player["characters"] else None
