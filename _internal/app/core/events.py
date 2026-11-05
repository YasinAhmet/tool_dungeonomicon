"""Thread-safe publish/subscribe that keeps every window in step with the data.

Any thread (the Discord bot, a service, a window) may `emit(topic)`. Handlers always run on the UI thread when the
bus is drained, and repeated emits of the same topic between two drains are coalesced into one handler call.
The editor attaches a waker (`attach`) so a drain runs as soon as something is emitted; without one (tests, scripts)
call `drain()` yourself. `watch` hears every emit at once on the emitting thread (the portal), and `counts` tells how
often each topic changed (cache keys).
"""
import queue
import threading
import traceback
from collections import defaultdict
from typing import Callable, Dict, List, Optional

# Topics
CHARACTERS = "characters"   # any character data changed (hp, inventory, notes, roster...)
DICE = "dice"               # dice history changed
SELECTION = "selection"     # the selected character changed
GUILD = "guild"             # the selected Discord server or its options changed
BATTLE = "battle"           # the battle tracker changed
BOT = "bot"                 # bot / voice connection state changed
RULES = "rules"             # sourcebooks or homebrew content changed
LOG = "log"                 # new lines in the application log
LANGUAGE = "language"       # the interface language changed
PORTAL = "portal"           # the player portal started, stopped or got its public address
RIGHTS = "rights"           # the DM changed what players may do on the portal (services/portal/api.RIGHTS)
FEED = "feed"               # a new roll or chat message in the table feed
NOWPLAYING = "nowplaying"   # the song Spotify plays changed (or got its cover, or a heart)
TEAM = "team"               # the team inventory changed
NOTES = "notes"             # a team note was added, changed or deleted, or someone began or stopped editing one
SOUND = "sound"             # the audio manager's loops, effects volume or outputs changed
WORLD = "world"             # the world map, the party on it or the group's food changed
WORLD_PING = "world_ping"   # someone pinged the world map (world.recent_pings())
DUEL = "duel"               # the duel opened or closed, someone joined it, or its fight changed (services/duel)


class UiBus:
    def __init__(self, on_error: Callable[[str], None] = print):
        self._pending: "queue.SimpleQueue[str]" = queue.SimpleQueue()
        self._subs: Dict[str, List[Callable[[], None]]] = defaultdict(list)
        self._on_error = on_error
        self._wake: Optional[Callable[[], None]] = None
        self._scheduled = threading.Event()
        self._watchers: List[Callable[[str], None]] = []
        self._keys: Dict[int, object] = {}                 # id(handler) -> its key (subscribe)
        self._count_lock = threading.Lock()
        self.counts: Dict[str, int] = defaultdict(int)     # emits per topic so far: a cache built after it is current

    def watch(self, fn: Callable[[str], None]) -> Callable[[], None]:
        """fn(topic) right on the emitting thread, not waiting for the UI (the player portal); returns an unsubscriber.
        It must be quick and must not touch widgets."""
        self._watchers.append(fn)

        def unwatch():
            if fn in self._watchers:
                self._watchers.remove(fn)
        return unwatch

    def attach(self, wake: Callable[[], None]) -> None:
        """`wake()` must arrange for drain() to run soon on the UI thread; it may be called from any thread."""
        self._wake = wake

    def subscribe(self, topic: str, handler: Callable[[], None], key=None) -> Callable[[], None]:
        """Register a handler; returns a function that unsubscribes it. Handlers with the same `key` (a window's refresh
        on several topics) run once a drain, however many of their topics changed."""
        self._subs[topic].append(handler)
        if key is not None:
            self._keys[id(handler)] = key

        def unsubscribe():
            if handler in self._subs[topic]:
                self._subs[topic].remove(handler)
                self._keys.pop(id(handler), None)
        return unsubscribe

    def emit(self, topic: str) -> None:
        with self._count_lock:
            self.counts[topic] += 1
        for fn in list(self._watchers):
            try:
                fn(topic)
            except Exception:
                self._on_error(f"[ERROR] watching '{topic}' failed:\n{traceback.format_exc()}")
        self._pending.put(topic)
        if self._wake is not None and not self._scheduled.is_set():
            self._scheduled.set()
            self._wake()

    def drain(self) -> None:
        self._scheduled.clear()
        topics: List[str] = []
        while True:
            try:
                topic = self._pending.get_nowait()
            except queue.Empty:
                break
            if topic not in topics:
                topics.append(topic)
        ran = set()                                         # keys already run this drain (battle + characters: once)
        for topic in topics:
            for handler in list(self._subs[topic]):
                key = self._keys.get(id(handler))
                if key is not None:
                    if key in ran:
                        continue
                    ran.add(key)
                try:
                    handler()
                except Exception:
                    self._on_error(f"[ERROR] refreshing '{topic}' failed:\n{traceback.format_exc()}")
