"""Renaming, archiving and importing characters, who owns them, and whole-roster snapshots."""
import os
import shutil
from datetime import datetime
from typing import Dict, List, Optional

from ...core import events, userdata
from ...rules.character import Character
from ...rules import html_import
from ..common import ARCHIVE_FOLDER, ServiceError, positive_int, valid_name
from ..players import is_manual


class RosterMixin:
    # ---- roster ----
    def rename(self, old: str, new: str) -> Character:
        new = valid_name(new, "Character name")
        with self.lock:
            char = self.get(old)
            if new == old:
                return char
            if char.transient:                         # (renamed, it would be saved to disk)
                raise ServiceError("A duel's fighter keeps its name.")
            if new in self.names():
                raise ServiceError(f"Character '{new}' already exists.")
            Character.delete(old)
            char.name = new
            char.save()
            self.players.rename_character(old, new)
            self._commit(char, f"Renamed character from '{old}' to '{new}'")
        return char

    def archive(self, name: str) -> None:
        with self.lock:
            char = self.get(name)
            os.makedirs(ARCHIVE_FOLDER, exist_ok=True)
            shutil.move(Character._path(name), os.path.join(ARCHIVE_FOLDER, f"{name}.json"))
            self.players.unassign(name)
            self.players.set_in_session(name, False)
            self.h.log(f"Archived character {char.name}")
            self.h.notify(events.CHARACTERS)

    def import_html(self, files: List[dict]) -> dict:
        """Bring exported HTML sheets ([{'file', 'html'}]) in. A sheet for a character that exists replaces it (the old
        one is kept in backups/imports/<time>/ first); any other sheet becomes a new, unassigned character."""
        stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
        out: Dict[str, list] = {"created": [], "updated": [], "failed": []}
        with self.lock:
            for f in files:
                try:
                    name = html_import.name_in(f["html"])
                    if not name:
                        raise ServiceError("Not a character sheet exported by the panel.")
                    name = valid_name(name, "Character name")
                    previous = Character.load(name)
                    char = html_import.from_html(f["html"], previous)
                    char.name = name
                    if previous:
                        userdata.keep_copy(Character._path(name), "imports", stamp)
                    char.save()
                    done = out["updated" if previous else "created"]
                    if name not in done:
                        done.append(name)
                except Exception as e:                       # one bad file doesn't stop the others
                    out["failed"].append({"file": f.get("file", ""), "error": str(e) or "Not a character sheet."})
            if out["created"] or out["updated"]:
                self.h.log(f"Imported HTML sheets: {len(out['updated'])} updated, {len(out['created'])} new"
                           + (f" (old versions in {os.path.join(userdata.BACKUPS, 'imports', stamp)})" if out["updated"] else ""))
                self.h.notify(events.CHARACTERS)
        out["backup"] = os.path.abspath(os.path.join(userdata.BACKUPS, "imports", stamp)) if out["updated"] else ""
        return out

    # ---- ownership ----
    def set_owner(self, name: str, owner_id: Optional[int], owner_name: Optional[str] = None) -> Character:
        """Give a character to a player, or make it unassigned with owner_id=None."""
        with self.lock:
            char = self.get(name)
            if owner_id is None:
                self.players.unassign(name)
                msg = f"Unassigned {char.name}"
            else:
                self.players.assign(owner_id, name, owner_name)
                msg = f"Assigned {char.name} to {self.players.name_of(owner_id) or owner_id}"
            self._commit(char, msg)
        return char

    def add_player(self, user_id, name: Optional[str] = None) -> int:
        user_id = positive_int(user_id, "Discord user ID")
        name = (name or "").strip() or self.h.user_name(user_id)
        self.players.ensure(user_id, name or None)
        self.h.log(f"Added player {name or user_id}")
        self.h.notify(events.CHARACTERS)
        return user_id

    def add_manual_player(self, name: str) -> int:
        """A player who isn't on Discord, known by a name only: the DM sends them their portal link."""
        try:
            uid = self.players.add_manual(name)
        except ValueError as e:
            raise ServiceError(str(e))
        self.h.log(f"Added player {name.strip()} (manual)")
        self.h.notify(events.CHARACTERS)
        return uid

    def rename_player(self, user_id: int, name: str) -> None:
        """Rename a manual player (a Discord player's name comes from Discord)."""
        if not is_manual(user_id):
            raise ServiceError("A Discord player's name comes from Discord.")
        try:
            self.players.rename(user_id, name)
        except ValueError as e:
            raise ServiceError(str(e))
        self.h.notify(events.CHARACTERS)

    def attach_to_discord(self, user_id: int, discord_id, name: Optional[str] = None) -> int:
        """A manual player joins Discord: their characters move to their Discord account, and their portal link keeps
        working (unless that account had a link already: then that one is kept)."""
        from ..portal.access import access
        if not is_manual(user_id):
            raise ServiceError("This player is already on Discord.")
        discord_id = positive_int(discord_id, "Discord user ID")
        name = (name or "").strip() or self.h.user_name(discord_id) or None
        with self.lock:
            try:
                self.players.move(user_id, discord_id, name)
            except ValueError as e:
                raise ServiceError(str(e))
            access.move(user_id, discord_id)
            self.h.log(f"Attached player {self.players.name_of(discord_id) or discord_id} to Discord ({discord_id})")
            self.h.notify(events.CHARACTERS)
        return discord_id

    def remove_player(self, user_id: int) -> None:
        """Forget a player; their characters become unassigned and their portal link stops working."""
        from ..portal.access import access
        with self.lock:
            mine = self.players.characters_of(user_id)
            self.players.remove(user_id)
            access.revoke(user_id)
            self.h.log(f"Removed player {user_id} ({len(mine)} characters unassigned)")
            self.h.notify(events.CHARACTERS)

    def claim(self, owner_id: int, name: str, owner_name: Optional[str] = None) -> Character:
        """Discord: take a free character."""
        with self.lock:
            char = self.get(name)
            owner = self.owner_of(name)
            if owner is not None:
                raise ServiceError(f"Character '{name}' is not free (owned by {self.players.name_of(owner) or owner}).")
            return self.set_owner(char.name, owner_id, owner_name)

    def release(self, owner_id: int, name: Optional[str] = None) -> Character:
        """Discord: give up one of your characters (default: the active one)."""
        with self.lock:
            name = name or self.players.active_of(owner_id)
            if not name or name not in self.players.characters_of(owner_id):
                raise ServiceError("You don't own that character." if name else "You don't have a character assigned.")
            return self.set_owner(name, None)

    def set_in_session(self, name: str, on: bool) -> None:
        """Tick a character as playing this session (or untick it)."""
        with self.lock:
            char = self.get(name)
            self.players.set_in_session(char.name, on)
            self.h.notify(events.CHARACTERS)

    def use(self, owner_id: int, name: str) -> Character:
        """Make `name` the character the player's Discord commands act on."""
        with self.lock:
            try:
                self.players.set_active(owner_id, name)
            except ValueError as e:
                raise ServiceError(str(e))
            self.h.notify(events.CHARACTERS)
            return self.get(name)

    # ---- whole-roster snapshots (character sets) ----
    def snapshot(self) -> List[dict]:
        return [c.to_dict() for c in Character.load_all()]

    def restore(self, snapshot: List[dict]) -> None:
        with self.lock:
            old = set(Character.list_characters())
            for name in old:
                Character.delete(name)
            new = [Character.from_dict(d) for d in snapshot]
            for char in new:
                char.save()
            self.players.prune({c.name for c in new})
            self.h.log(f"Restored {len(new)} characters from a set")
            self.h.notify(events.CHARACTERS)
