"""Who is who on the portal: one secret key per player, kept in data/portal_access.json.

A player's link carries their key (https://.../?k=KEY); the key is the login. Making a new key for a player
(`renew`) makes their old link stop working; `revoke` removes it. Players added by hand (not on Discord) have negative
ids; `move` hands a link to the Discord account such a player joins with.
"""
import secrets
import threading
from typing import Dict, Optional

from ...core.storage import read_json, write_json

ACCESS_FILE = "data/portal_access.json"


class PortalAccess:
    def __init__(self, path: str = ACCESS_FILE):
        self.path = path
        self.lock = threading.Lock()

    def _load(self) -> Dict[str, int]:
        data = read_json(self.path, {}) or {}
        return {k: int(v) for k, v in data.items() if str(v).lstrip("-").isdigit()}

    def key_for(self, user_id: int) -> str:
        """The player's key (made the first time it is asked for)."""
        with self.lock:
            data = self._load()
            for key, uid in data.items():
                if uid == int(user_id):
                    return key
            key = secrets.token_urlsafe(18)
            data[key] = int(user_id)
            write_json(self.path, data)
            return key

    def renew(self, user_id: int) -> str:
        self.revoke(user_id)
        return self.key_for(user_id)

    def revoke(self, user_id: int):
        with self.lock:
            data = {k: v for k, v in self._load().items() if v != int(user_id)}
            write_json(self.path, data)

    def move(self, old_id: int, new_id: int):
        """The old id's link now logs in as the new id (kept only if the new id had no link of its own)."""
        with self.lock:
            data = self._load()
            if int(new_id) in data.values():
                data = {k: v for k, v in data.items() if v != int(old_id)}
            else:
                data = {k: (int(new_id) if v == int(old_id) else v) for k, v in data.items()}
            write_json(self.path, data)

    def user_of(self, key: Optional[str]) -> Optional[int]:
        if not key:
            return None
        for k, uid in self._load().items():
            if secrets.compare_digest(k, key):
                return uid
        return None


access = PortalAccess()
