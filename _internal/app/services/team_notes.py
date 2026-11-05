"""Team notes: entries every player (and the DM) can read and add to - a header, and a description shown on hover or
when the note is opened. One person edits a note at a time: `begin` takes the note for them (others see who is
editing and can't start), `save` or `cancel` lets it go. The hold is a lease: the editing page renews it (`hold`)
while it stays open, so a closed tab or a lost connection frees the note within HOLD_SECONDS.

    notes.all()                                     # [{'id', 'title', 'text', 'by', 'uid', 'at', 'edited_by',
                                                    #   'edited_at', 'editing': {'who', 'owner', 'left'} | None}]
    notes.add("The mill", "Ask Bela about it", by="Arin", uid=12)
    notes.begin(3, "p12", "Arin")                   # Arin's page edits note 3 (owner: whoever holds it, "dm" for the DM)
    notes.hold(3, "p12")                            # still editing
    notes.save(3, "p12", "The mill", "…burned down", by="Arin")
    notes.cancel(3, "p12")
    notes.remove(3, "dm", by="The DM")

It lives in data/team_notes.json; every change (a hold taken or let go too) emits events.NOTES.
"""
import threading
import time
from typing import List, Optional

from ..core import events
from ..core.storage import read_json, write_json
from .common import Hooks, ServiceError

NOTES_FILE = "data/team_notes.json"
MAX_NOTES = 300
TITLE_MAX = 120
TEXT_MAX = 4000
HOLD_SECONDS = 45                       # a page renews its hold well inside this (every 15 s)
DM = "dm"                               # the editor's owner key


class TeamNotes:
    def __init__(self, hooks: Hooks):
        self.h = hooks
        self.lock = threading.RLock()
        data = read_json(NOTES_FILE, {})
        data = data if isinstance(data, dict) else {}
        self._notes: List[dict] = [self._clean(n) for n in data.get("notes") or [] if isinstance(n, dict) and n.get("id")]
        self._next = max([int(data.get("next") or 1)] + [n["id"] + 1 for n in self._notes])
        self._holds = {}                # note id -> {'owner', 'who', 'until'}

    @staticmethod
    def _clean(n: dict) -> dict:
        return {"id": int(n["id"]), "title": str(n.get("title") or "")[:TITLE_MAX], "text": str(n.get("text") or "")[:TEXT_MAX],
                "by": str(n.get("by") or ""), "uid": n.get("uid"), "at": float(n.get("at") or 0),
                "edited_by": str(n.get("edited_by") or ""), "edited_at": float(n.get("edited_at") or 0)}

    # ------------------------------------------------------------------ reading
    def _hold(self, nid: int) -> Optional[dict]:
        """The live hold on a note (a lapsed one is dropped)."""
        h = self._holds.get(nid)
        if h and h["until"] <= time.time():
            del self._holds[nid]
            return None
        return h

    def all(self) -> List[dict]:
        """Every note, newest first, with who is editing it (`left`: seconds until that hold lapses unless renewed)."""
        with self.lock:
            now = time.time()
            out = []
            for n in sorted(self._notes, key=lambda n: -(n["edited_at"] or n["at"])):
                h = self._hold(n["id"])
                out.append(dict(n, editing={"who": h["who"], "owner": h["owner"], "left": round(h["until"] - now, 1)} if h else None))
            return out

    def get(self, nid) -> dict:
        with self.lock:
            return dict(self._get(nid))

    def _get(self, nid) -> dict:
        try:
            nid = int(nid)
        except (TypeError, ValueError):
            nid = 0
        n = next((n for n in self._notes if n["id"] == nid), None)
        if not n:
            raise ServiceError("That note is gone.")
        return n

    # ------------------------------------------------------------------ changing
    @staticmethod
    def _title(title) -> str:
        title = " ".join(str(title or "").split())[:TITLE_MAX]
        if not title:
            raise ServiceError("A note needs a header.")
        return title

    @staticmethod
    def _text(text) -> str:
        return str(text or "").strip()[:TEXT_MAX]

    def _save(self, line: Optional[str] = None):
        write_json(NOTES_FILE, {"next": self._next, "notes": self._notes})
        if line:
            self.h.log(line)
        self.h.notify(events.NOTES)

    def add(self, title, text="", by: str = "The DM", uid: Optional[int] = None) -> int:
        """A new note; returns its id."""
        title, text = self._title(title), self._text(text)
        with self.lock:
            if len(self._notes) >= MAX_NOTES:
                raise ServiceError("There are too many team notes; delete some first.")
            nid, self._next = self._next, self._next + 1
            self._notes.append({"id": nid, "title": title, "text": text, "by": by, "uid": uid, "at": time.time(),
                                "edited_by": "", "edited_at": 0.0})
            self._save(f"{by} adds the team note '{title}'")
            return nid

    def _check(self, nid: int, owner: str):
        h = self._hold(nid)
        if h and h["owner"] != owner:
            raise ServiceError(f"{h['who']} is editing this note right now.")

    def begin(self, nid, owner: str, who: str) -> dict:
        """Take the note for editing (again, for its holder: renewed); refused while someone else edits it."""
        with self.lock:
            n = self._get(nid)
            self._check(n["id"], owner)
            fresh = n["id"] not in self._holds
            self._holds[n["id"]] = {"owner": owner, "who": who, "until": time.time() + HOLD_SECONDS}
            if fresh:
                self.h.notify(events.NOTES)
            return dict(n)

    def hold(self, nid, owner: str) -> bool:
        """Still editing: renew the hold. False when it was lost (lapsed and taken by someone else, or the note gone)."""
        with self.lock:
            try:
                n = self._get(nid)
            except ServiceError:
                return False
            h = self._hold(n["id"])
            if h is None or h["owner"] != owner:
                return False
            h["until"] = time.time() + HOLD_SECONDS
            return True

    def cancel(self, nid, owner: str):
        """Stop editing without saving (nothing happens when `owner` doesn't hold it)."""
        with self.lock:
            try:
                nid = int(nid)
            except (TypeError, ValueError):
                return
            h = self._holds.get(nid)
            if h and h["owner"] == owner:
                del self._holds[nid]
                self.h.notify(events.NOTES)

    def save(self, nid, owner: str, title, text, by: str):
        """The edit done: the new header and description, and the note is free again. A hold that lapsed is fine as long
        as no one else took the note meanwhile."""
        title, text = self._title(title), self._text(text)
        with self.lock:
            n = self._get(nid)
            self._check(n["id"], owner)
            self._holds.pop(n["id"], None)
            if (n["title"], n["text"]) == (title, text):
                self.h.notify(events.NOTES)
                return
            n.update(title=title, text=text, edited_by=by, edited_at=time.time())
            self._save(f"{by} edits the team note '{title}'")

    def remove(self, nid, owner: str, by: str, uid: Optional[int] = None):
        """Delete a note: the DM, or the player who wrote it (`uid`); not while someone else edits it."""
        with self.lock:
            n = self._get(nid)
            if owner != DM and (uid is None or n["uid"] != uid):
                raise ServiceError("Only the DM or whoever wrote a note can delete it.")
            self._check(n["id"], owner)
            self._holds.pop(n["id"], None)
            self._notes.remove(n)
            self._save(f"{by} deletes the team note '{n['title']}'")
