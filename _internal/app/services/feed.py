"""The table feed: what everyone at the table sees scroll by - rolls, XP and chat between the DM and the players.

The rolls are the same announcements that go to the Discord log channel (Runtime.discord_log adds them here too,
with the same per-kind ticks), so the editor's Table chat window, the player portal and Discord all show the same.

    rt().feed.say("Alice", "I check the door", from_dm=False)
    rt().feed.since(last_id)            # entries newer than the ones a window already shows

Kept in data/table_feed.json (the last FEED_KEEP entries). Emits events.FEED.
"""
import itertools
import re
import threading
import time
from collections import deque
from typing import Callable, List, Optional

from ..core.storage import read_json, write_json, write_json_soon

FEED_FILE = "data/table_feed.json"
FEED_KEEP = 300
KINDS = {"player_rolls": "roll", "npc_rolls": "roll", "xp": "xp", "chat": "chat", "system": "system"}
MAX_CHAT = 500
# a damage or healing roll on a character ("💥 **Bugbear** · Morningstar damage → Bram · **7** · 7 piercing → 18/25 HP",
# "💚 **Sera** · Cure Wounds healing → Bram · **7** · 25/25 HP") and the character's own line just before it
# ("💔 Bram took **7** damage (HP: 18/25)", "💚 Bram healed **7** (HP: 25/25)"): the same news, kept once
_HIT = re.compile(r"(?:damage|healing) → (.+?)(?: \(critical\))? · .*?(\d+)/(\d+) HP")
_HURT = re.compile(r"(?:💔|💚) (.+) (?:took|healed) \*\*\d+\*\*(?: damage)? \(HP: (\d+)/(\d+)\)$")
_NOTHING = re.compile(r" · \*\*0\*\* · ")      # a roll that changed nothing (immune): not the news of an earlier line


class TableFeed:
    def __init__(self, notify: Callable[[], None] = lambda: None, path: str = FEED_FILE):
        self.path = path
        self.notify = notify
        self.lock = threading.Lock()
        saved = read_json(path, []) or []
        self.entries: "deque[dict]" = deque((e for e in saved if isinstance(e, dict) and "id" in e), maxlen=FEED_KEEP)
        self._ids = itertools.count((self.entries[-1]["id"] + 1) if self.entries else 1)

    def add(self, kind: str, text: str, who: str = "", from_dm: bool = False, user_id: Optional[int] = None) -> dict:
        with self.lock:
            e = {"id": next(self._ids), "time": time.strftime("%H:%M"), "kind": KINDS.get(kind, kind), "who": who,
                 "text": text, "dm": from_dm, "uid": str(user_id) if user_id else None}
            hit = _HIT.search(text) if e["kind"] == "roll" and not _NOTHING.search(text) else None
            if hit:                                          # it says what the "💔 took" line just before it said
                for old in reversed(list(self.entries)[-4:]):          # (the nearest one: the same HP can repeat)
                    hurt = _HURT.match(old.get("text") or "")
                    if hurt and hurt.groups() == hit.groups():
                        self.entries.remove(old)
                        break
            self.entries.append(e)
            write_json_soon(self.path, list(self.entries))      # every roll: saved by the writer thread
        self.notify()
        return e

    def say(self, who: str, text: str, from_dm: bool = False, user_id: Optional[int] = None) -> dict:
        text = " ".join(str(text or "").split())[:MAX_CHAT]
        if not text:
            raise ValueError("Write something first.")
        return self.add("chat", text, who, from_dm, user_id)

    def since(self, last_id: int = 0, limit: int = FEED_KEEP) -> List[dict]:
        with self.lock:
            return [e for e in self.entries if e["id"] > last_id][-limit:]

    def clear(self):
        with self.lock:
            self.entries.clear()
            write_json(self.path, [])
        self.notify()
