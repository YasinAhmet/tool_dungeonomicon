"""What Spotify is playing on this PC, for the players' portal: song, artist and cover, plus the hearts.

The song comes from the Spotify desktop window's title, which reads "Artist - Song" while music plays (and just
"Spotify" when paused). The cover comes from Apple's public iTunes search (no account, no key), downloaded once into
data/cache/images. Nothing is sent to Spotify.

A song can be hearted once per session (until the app restarts), by whoever is first: that puts one line in the
table feed. `rt().bus` gets events.NOWPLAYING when the song changes.
"""
import json
import threading
import urllib.parse
import urllib.request
from typing import Dict, Optional

from ..core import assets

POLL = 3.0                     # seconds between looks at the Spotify window
SEARCH = "https://itunes.apple.com/search?entity=song&limit=1&term="


def spotify_title() -> Optional[str]:
    """The Spotify window's title, if Spotify is running (Windows only)."""
    try:
        import psutil
        import win32gui
        import win32process
    except ImportError:
        return None
    pids = {p.pid for p in psutil.process_iter(["name"]) if (p.info.get("name") or "").lower() == "spotify.exe"}
    if not pids:
        return None
    titles = []

    def on_window(hwnd, _):
        try:
            _tid, pid = win32process.GetWindowThreadProcessId(hwnd)
            if pid in pids:
                t = win32gui.GetWindowText(hwnd)
                if t:
                    titles.append(t)
        except Exception:                          # a window that closed while we looked
            pass
    win32gui.EnumWindows(on_window, None)
    return next((t for t in titles if " - " in t), titles[0] if titles else None)


def parse(title: Optional[str]) -> Optional[Dict[str, str]]:
    """'Artist - Song' -> {'artist', 'song'}; None when nothing plays ('Spotify', 'Spotify Premium', ad breaks)."""
    if not title or " - " not in title:
        return None
    artist, _, song = title.partition(" - ")
    artist, song = artist.strip(), song.strip()
    if not artist or not song or artist.lower().startswith("spotify"):
        return None
    return {"artist": artist, "song": song}


class NowPlaying:
    def __init__(self):
        self.lock = threading.Lock()
        self.current: Optional[Dict[str, str]] = None
        self.hearted: Dict[str, str] = {}             # song key -> who hearted it first (this session)
        self._art: Dict[str, Optional[str]] = {}      # song key -> cover file
        self._stop: Optional[threading.Event] = None
        self._notify = lambda: None

    @staticmethod
    def key(info: Dict[str, str]) -> str:
        return f"{info['artist']}|{info['song']}".lower()

    # ------------------------------------------------------------------ watching
    def start(self, notify):
        """Watch the Spotify window on a background thread (the portal starts and stops this)."""
        self._notify = notify
        if self._stop is None:
            self._stop = threading.Event()
            threading.Thread(target=self._run, args=(self._stop,), daemon=True, name="nowplaying").start()

    def stop(self):
        if self._stop is not None:
            self._stop.set()
            self._stop = None
        with self.lock:
            self.current = None

    def _run(self, stop: threading.Event):
        while not stop.is_set():
            self.poll()
            stop.wait(POLL)

    def poll(self, title: Optional[str] = None):
        info = parse(title if title is not None else spotify_title())
        with self.lock:
            changed = info != self.current
            self.current = info
        if changed:
            if info:
                threading.Thread(target=self.cover, args=(info,), daemon=True).start()
            self._notify()

    # ------------------------------------------------------------------ the cover
    def cover(self, info: Dict[str, str]) -> Optional[str]:
        """The song's cover picture (a file path), looked up once per song."""
        k = self.key(info)
        if k in self._art:
            return self._art[k]
        path = None
        try:
            term = urllib.parse.quote(f"{info['artist']} {info['song']}")
            with urllib.request.urlopen(SEARCH + term, timeout=5) as r:
                hits = json.load(r).get("results") or []
            if hits and hits[0].get("artworkUrl100"):
                path = assets.remote_image(hits[0]["artworkUrl100"].replace("100x100", "300x300"))
        except (OSError, ValueError):
            path = None
        self._art[k] = path
        if path:
            self._notify()
        return path

    # ------------------------------------------------------------------ for the page
    def view(self) -> Optional[dict]:
        with self.lock:
            info = dict(self.current) if self.current else None
        if not info:
            return None
        k = self.key(info)
        return {**info, "key": k, "art": bool(self._art.get(k)), "hearted_by": self.hearted.get(k),
                "url": "https://open.spotify.com/search/" + urllib.parse.quote(f"{info['artist']} {info['song']}")}

    def art_file(self) -> Optional[str]:
        with self.lock:
            info = self.current
        return self._art.get(self.key(info)) if info else None

    def heart(self, who: str, feed) -> bool:
        """The first heart of a song this session puts it in the table feed; later hearts do nothing (False)."""
        with self.lock:
            info = self.current
            if not info:
                return False
            k = self.key(info)
            if k in self.hearted:
                return False
            self.hearted[k] = who
        feed.add("system", f"❤️ **{who}** loves “{info['song']}” — {info['artist']}")
        self._notify()
        return True


nowplaying = NowPlaying()
