"""The portal's web server: the page, a small JSON API and live updates. It listens on 127.0.0.1 only; players
reach it through the Cloudflare tunnel (tunnel.py), which connects to it from this PC.

    GET  /                  the page (static/)
    GET  /api/state         everything the logged-in player sees           (key: X-Key header or ?k=)
                            (?strings=1: also the page's words in the player's language)
    POST /api/act           {"action": ..., ...} - see api.act
    GET  /api/events?k=     server-sent events: "<topic> <version>" whenever the battle or the characters change, and
                            "ping <x> <y> <press>" / "ping off" while the DM points at the battle map (controller.ping)
    GET  /api/music?k=      the table's sound (the DM's streamed apps and loops), an endless Ogg Opus stream (music.py)
    GET  /token/<id>?k=     a combatant's token picture
    GET  /mapimg/<key>?k=   a picture the DM put on the battle map (content-named: kept by the browser)

Every API call needs a player's key (access.py); requests are size-limited and rate-limited per key.

Presence: a player is online while they hold a live-update stream open; every request they make is their last_seen.
"""
import gzip
import json
import mimetypes
import os
import queue
import socket
import threading
import time
import traceback
import zlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Callable, Dict, List, Optional
from urllib.parse import parse_qs, unquote, urlparse

from ...core import events
from ...core.runtime import rt
from ..common import ServiceError
from . import api
from .access import access

STATIC = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
DEFAULT_PORT = 8800
MAX_BODY = 16 * 1024
RATE = (12, 4.0)                # a key may make 12 actions per 4 seconds
TOPICS = (events.BATTLE, events.CHARACTERS, events.DICE, events.FEED, events.NOWPLAYING, events.TEAM, events.WORLD, events.NOTES,
          events.DUEL, events.RIGHTS)       # (rights: the DM changed what players may do - the pages reload everything)
KEEPALIVE = 10.0                # seconds between keep-alive lines on a quiet stream (also how soon a closed page is noticed)
MUSIC_PAGE = 25                 # at most this many 20 ms Opus packets in one page of the music stream
BURST = 0.025                   # seconds a change waits for the rest of its burst before the pages hear of it
ZIPPABLE = ("application/json", "text/", "application/javascript", "image/svg")
UNITS = {"battle", "character", "team", "feed", "world", "now", "duel", "dbattle"}   # parts left out when the page has them unchanged
SPLIT = {"battle", "character", "team", "world", "dbattle"}         # ...and of these, each key on its own
_STATIC: Dict[str, tuple] = {}  # file -> (stamp, body, type, etag, gzipped body)

def _dump(value) -> str:
    return json.dumps(value, ensure_ascii=False, default=str, separators=(",", ":"))


def _have(header: Optional[str]) -> Dict[str, str]:
    """The page's X-Have header, "battle.actions=1a2b,character=3c4d": the fingerprints of what it already holds."""
    out = {}
    for pair in (header or "")[:8000].split(","):
        k, _, h = pair.partition("=")
        if k and h:
            out[k.strip()] = h.strip()
    return out


_TEXTS: Dict[int, tuple] = {}   # id(part) -> (the part, its JSON, its fingerprint)


def _text(value) -> tuple:
    """(JSON, fingerprint) of a part of a state. The battle's map, a sheet, the world... are shared, never-changed objects
    (portal/api.py keeps them per change): made once for all six pages, not once each."""
    if isinstance(value, (dict, list)):
        hit = _TEXTS.get(id(value))
        if hit is not None and hit[0] is value:                # (kept alive here: its id can't be reused meanwhile)
            return hit[1], hit[2]
    text = _dump(value)
    h = format(zlib.crc32(text.encode("utf-8")), "x")
    if isinstance(value, (dict, list)):
        if len(_TEXTS) > 4000:
            _TEXTS.clear()
        _TEXTS[id(value)] = (value, text, h)
    return text, h


def _state_json(data: dict, have: Dict[str, str]) -> bytes:
    """The state as JSON, leaving out every part the page already holds unchanged. A part (and each key of the battle:
    its map, its props, an action bar...) goes with its fingerprint; one the page has: named in "same" instead. A
    move then sends what moved, not the character sheet and the map again."""
    out, prints, same = [], {}, []
    for key, value in data.items():
        if key not in UNITS:
            out.append(f"{_dump(key)}:{_dump(value)}")
            continue
        if key in SPLIT and isinstance(value, dict):        # key by key: a hit sends the hit points, not the whole sheet
            inner = []
            for bk, bv in value.items():
                unit = f"{key}.{bk}"
                text, h = _text(bv)
                if have.get(unit) == h:
                    same.append(unit)
                else:
                    prints[unit] = h                        # (the page keeps the fingerprints of what it keeps)
                    inner.append(f"{_dump(bk)}:{text}")
            out.append(f'{_dump(key)}:{{' + ",".join(inner) + "}")
            continue
        text, h = _text(value)
        if have.get(key) == h:
            same.append(key)
        else:
            prints[key] = h
            out.append(f"{_dump(key)}:{text}")
    out.append(f'"prints":{_dump(prints)},"same":{_dump(same)}')
    return ("{" + ",".join(out) + "}").encode("utf-8")


class _Hub:
    def __init__(self):
        self.clients: List["queue.Queue"] = []
        self.lock = threading.Lock()
        self.version = 0                   # goes up with every change; pages poll it when a proxy holds the stream back
        self._topics: set = set()          # changed since the last line went out
        self._wake = threading.Event()
        self._flusher: Optional[threading.Thread] = None

    def add(self) -> "queue.Queue":
        q: "queue.Queue" = queue.Queue(maxsize=50)
        with self.lock:
            self.clients.append(q)
        return q

    def remove(self, q):
        with self.lock:
            if q in self.clients:
                self.clients.remove(q)

    def push(self, msg: str):
        """Something passing (the DM's ping) straight to every open page: no version, nothing to reload, and dropped
        for a page whose stream is falling behind."""
        with self.lock:
            for q in list(self.clients):
                if q.qsize() < 20:
                    try:
                        q.put_nowait(msg)
                    except queue.Full:
                        pass

    def publish(self, what: str):
        """A change (any thread, straight from the bus): a burst of them goes out as one line, "<topics> <version>"
        (topics comma-separated), so a page reloads only the parts they touch, once."""
        with self.lock:
            self._topics.add(what)
            if self._flusher is None:
                self._flusher = threading.Thread(target=self._flush_loop, daemon=True, name="portal-events")
                self._flusher.start()
        self._wake.set()

    def _flush_loop(self):
        while True:
            self._wake.wait()
            time.sleep(BURST)                                      # the rest of the burst (one action: several topics)
            self._wake.clear()
            with self.lock:
                topics, self._topics = self._topics, set()
                if not topics:
                    continue
                self.version += 1
                msg = f"{','.join(sorted(topics))} {self.version}"
                for q in list(self.clients):
                    try:
                        q.put_nowait(msg)                          # the page skips a reload its state already has
                    except queue.Full:
                        pass


class _Handler(BaseHTTPRequestHandler):
    server_version = "DungeonPortal/1.0"
    protocol_version = "HTTP/1.1"
    portal: "PortalServer" = None

    def log_message(self, fmt, *args):
        pass

    # ---- plumbing
    def _send(self, code: int, body: bytes, ctype: str = "application/json; charset=utf-8", cache=False, etag: str = "",
              zipped: Optional[bytes] = None):
        """zipped: the body already gzipped (static files keep theirs); text over 1 KB is zipped here for a browser that
        takes it - a state is ~90 KB of JSON, ~20 KB zipped, sent up the tunnel to every player after each change."""
        if code == 200 and "gzip" in (self.headers.get("Accept-Encoding") or ""):
            if zipped is None and len(body) > 1024 and ctype.startswith(ZIPPABLE):
                zipped = gzip.compress(body, 5)
        else:
            zipped = None
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        if zipped is not None:
            body = zipped
            self.send_header("Content-Encoding", "gzip")
        if code == 200 and ctype.startswith(ZIPPABLE):
            self.send_header("Vary", "Accept-Encoding")
        self.send_header("Content-Length", str(len(body)))
        if etag:
            self.send_header("ETag", etag)
        self.send_header("Cache-Control", "public, max-age=2592000" if cache == "long" else "max-age=3600" if cache
                         else "no-cache" if etag else "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'")
        self.end_headers()
        self.wfile.write(body)

    def _json(self, data, code: int = 200):
        self._send(code, json.dumps(data, ensure_ascii=False, default=str, separators=(",", ":")).encode("utf-8"))

    def _uid(self, query: dict) -> Optional[int]:
        key = self.headers.get("X-Key") or (query.get("k") or [""])[0]
        uid = access.user_of(key)
        if uid:
            self.portal.touch(uid)
        return uid

    @staticmethod
    def _who(uid: Optional[int]) -> str:
        """The player's name for the log (the Discord id when it is not known)."""
        return (rt().players.name_of(uid) if uid else None) or str(uid or "?")

    # ---- verbs
    def do_GET(self):
        url = urlparse(self.path)
        query = parse_qs(url.query)
        path = unquote(url.path)
        try:
            if path == "/api/state":
                uid = self._uid(query)
                if not uid:
                    return self._json({"error": "login"}, 403)
                parts = [p for p in ((query.get("parts") or [""])[0]).split(",") if p in api.PARTS]
                v = self.portal.hub.version                  # read first: the state is at least this new
                data = api.state(uid, strings=(query.get("strings") or [""])[0] == "1", parts=parts or None)
                data["parts"] = parts or list(api.PARTS)             # what this answer holds (the page keeps the rest)
                data["v"] = v
                return self._send(200, _state_json(data, _have(self.headers.get("X-Have"))))
            if path == "/api/version":
                uid = self._uid(query)
                return self._json({"v": self.portal.hub.version}) if uid else self._json({"error": "login"}, 403)
            if path == "/api/events":
                uid = self._uid(query)
                return self._stream(uid) if uid else self._json({"error": "login"}, 403)
            if path == "/api/music":
                uid = self._uid(query)
                if not uid:
                    return self._json({"error": "login"}, 403)
                return self._music() if api.settings()["music"] else self._send(404, b"", "text/plain")
            if path == "/api/art":                    # the cover of the song playing now
                from ..nowplaying import nowplaying
                file = nowplaying.art_file() if self._uid(query) else None
                if not file or not os.path.isfile(file):
                    return self._send(404, b"", "text/plain")
                with open(file, "rb") as f:
                    return self._send(200, f.read(), mimetypes.guess_type(file)[0] or "image/png", cache=True)
            if path.startswith("/icon/"):                # an action bar picture: small, the same for everyone, kept by the browser
                from ..battle import icons
                file = icons.path(path[6:].removesuffix(".webp"))
                if not file:
                    return self._send(404, b"", "text/plain")
                with open(file, "rb") as f:
                    return self._send(200, f.read(), "image/webp", cache="long")
            if path.startswith("/prop/"):                # a map prop's or symbol's picture (small WebP, kept by the browser)
                from ..battle import props
                file = props.path(path[6:].removesuffix(".webp"))
                if not file:
                    return self._send(404, b"", "text/plain")
                with open(file, "rb") as f:
                    return self._send(200, f.read(), "image/webp", cache="long")
            if path.startswith("/itemsprite/"):          # an item's sprite on the battle map (32 px PNG, kept by the browser)
                from ..battle import itemsprites
                file = itemsprites.path(path[12:].removesuffix(".png"))
                if not file:
                    return self._send(404, b"", "text/plain")
                with open(file, "rb") as f:
                    return self._send(200, f.read(), "image/png", cache="long")
            if path.startswith("/worldart/"):            # a world map stamp's picture (small, kept by the browser)
                file = api.world_art_path(path[10:]) if self._uid(query) else None
                if not file:
                    return self._send(404, b"", "text/plain")
                with open(file, "rb") as f:
                    return self._send(200, f.read(), mimetypes.guess_type(file)[0] or "image/webp", cache="long")
            if path.startswith("/worldimg/"):            # the world map the players were sent (a new version: a new name)
                file = api.world_image_path(self._uid(query), path[10:])
                if not file:
                    return self._send(404, b"", "text/plain")
                with open(file, "rb") as f:
                    return self._send(200, f.read(), "image/webp", cache="long")
            if path.startswith("/mapimg/"):
                file = api.map_image_path(self._uid(query), path[8:])
                if not file:
                    return self._send(404, b"", "text/plain")
                with open(file, "rb") as f:
                    return self._send(200, f.read(), mimetypes.guess_type(file)[0] or "image/webp", cache="long")
            if path.startswith("/token/"):
                uid = self._uid(query)
                cid = path[7:]
                room = (query.get("duel") or [""])[0]               # (a token on a duel lobby's map)
                file = api.token_path(uid, int(cid), int(room) if room.isdigit() else None) if uid and cid.isdigit() else None
                if not file or not os.path.isfile(file):
                    return self._send(404, b"", "text/plain")
                with open(file, "rb") as f:                # ?v=: the picture's version is in the address, kept for long
                    return self._send(200, f.read(), mimetypes.guess_type(file)[0] or "image/webp",
                                      cache="long" if query.get("v") else True)
            return self._static(path)
        except (BrokenPipeError, ConnectionResetError):
            return
        except Exception:
            rt().log("[ERROR] portal: " + traceback.format_exc())
            return self._json({"error": "Server error."}, 500)

    def do_POST(self):
        url = urlparse(self.path)
        try:
            if url.path != "/api/act":
                return self._json({"error": "Not found."}, 404)
            uid = self._uid(parse_qs(url.query))
            if not uid:
                return self._json({"error": "login"}, 403)
            n = int(self.headers.get("Content-Length") or 0)
            if n <= 0 or n > MAX_BODY:
                return self._json({"error": "Bad request."}, 400)
            body = json.loads(self.rfile.read(n).decode("utf-8"))
            if not isinstance(body, dict) or not isinstance(body.get("action"), str):
                return self._json({"error": "Bad request."}, 400)
            if not self.portal.allow(uid if body["action"] != "preview" else ("preview", uid)):    # (a hover's previews: a
                return self._json({"error": "Slow down a little."}, 429)                               # count of their own)
            if body["action"] != "preview" and not (body.get("duel") or body["action"].startswith("duel_")):   # (a hover's preview
                # is not something the player did; nothing of a duel is kept)
                rt().log(f"[PORTAL] {self._who(uid)}: {json.dumps(body, ensure_ascii=False)[:1000]}")
            out = api.act(uid, body["action"], body)
            if isinstance(out, dict):
                return self._json({"ok": True, "text": "", "data": out})
            return self._json({"ok": True, "text": out})
        except (BrokenPipeError, ConnectionResetError):
            return
        except (ServiceError, ValueError, KeyError) as e:
            uid = locals().get("uid")
            from ...core.i18n import i18n
            msg = str(e.args[0] if isinstance(e, KeyError) and e.args else e)
            rt().log(f"[{'BUSY' if type(e).__name__ == 'Busy' else 'REFUSED'}] portal {self._who(uid)}: {msg}")
            return self._json({"error": i18n.t(msg, i18n.player_language(uid)) if uid else msg}, 400)
        except Exception:
            rt().log("[ERROR] portal: " + traceback.format_exc())
            return self._json({"error": "Server error."}, 500)

    def _static(self, path: str):
        if path in ("", "/"):
            path = "/index.html"
        full = os.path.normpath(os.path.join(STATIC, path.lstrip("/")))
        if not full.startswith(STATIC + os.sep) or not os.path.isfile(full):
            return self._send(404, b"Not found", "text/plain")
        st = os.stat(full)
        hit = _STATIC.get(full)
        if not hit or hit[0] != (st.st_mtime_ns, st.st_size):  # read and zipped once per version of the file
            with open(full, "rb") as f:
                body = f.read()
            ctype = mimetypes.guess_type(full)[0] or "application/octet-stream"
            if ctype.startswith("text/") or ctype in ("application/javascript",):
                ctype += "; charset=utf-8"
            etag = f'"{st.st_mtime_ns:x}-{st.st_size:x}"'
            hit = _STATIC[full] = ((st.st_mtime_ns, st.st_size), body, ctype, etag,
                                   gzip.compress(body, 9) if ctype.startswith(ZIPPABLE) else None)
        _stamp, body, ctype, etag, zipped = hit
        if etag in (self.headers.get("If-None-Match") or ""):  # the browser has it: revalidated, nothing sent
            self.send_response(304)
            self.send_header("ETag", etag)
            self.send_header("Cache-Control", "no-cache")
            self.end_headers()
            return
        return self._send(200, body, ctype, etag=etag, zipped=zipped)

    def _stream(self, uid: int):
        q = self.portal.hub.add()
        self.portal.stream_open(uid)
        try:
            self.send_response(200)
            self.send_header("Content-Type", "text/event-stream")
            self.send_header("Cache-Control", "no-cache, no-transform")      # proxies (Cloudflare) must not buffer or zip it
            self.send_header("X-Accel-Buffering", "no")
            self.send_header("Content-Encoding", "identity")
            self.end_headers()
            self.wfile.write(b":" + b" " * 2048 + b"\n\nretry: 3000\n\n")   # padding pushes the first bytes through
            self.wfile.flush()
            while not self.portal.stopping.is_set():
                try:
                    msg = q.get(timeout=KEEPALIVE)
                    self.wfile.write(f"data: {msg}\n\n".encode())
                except queue.Empty:
                    self.wfile.write(b": keepalive\n\n")
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            self.portal.hub.remove(q)
            self.portal.stream_closed(uid)
            self.close_connection = True


    def _music(self):
        """The table's sound as an endless Ogg Opus stream, for as long as the page plays it (music.py)."""
        from .music import OggOpus, music
        q, ogg = music.listen(), OggOpus()
        try:
            self.send_response(200)
            self.send_header("Content-Type", "audio/ogg")
            self.send_header("Cache-Control", "no-cache, no-store, no-transform")
            self.send_header("X-Accel-Buffering", "no")
            self.send_header("Connection", "close")
            self.end_headers()
            self.wfile.write(ogg.head())
            while not self.portal.stopping.is_set() and api.settings()["music"]:
                try:
                    packets = [q.get(timeout=2.0)]
                except queue.Empty:
                    if not music.serving(q):
                        break
                    continue
                while len(packets) < MUSIC_PAGE:
                    try:
                        packets.append(q.get_nowait())
                    except queue.Empty:
                        break
                self.wfile.write(ogg.page(packets))
                self.wfile.flush()
                self.portal.stopping.wait(0.1)           # a few packets a page, not fifty small writes a second
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            music.leave(q)
            self.close_connection = True


class _ExclusiveServer(ThreadingHTTPServer):
    """Never share a port: on Windows SO_REUSEADDR would let a second program bind the same port and take requests."""
    allow_reuse_address = False

    def server_bind(self):
        if hasattr(socket, "SO_EXCLUSIVEADDRUSE"):
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


class PortalServer:
    def __init__(self, port: int = DEFAULT_PORT):
        self.port = port
        self.hub = _Hub()
        self.stopping = threading.Event()
        self._httpd: Optional[ThreadingHTTPServer] = None
        self._unsub = []
        self._hits = {}
        self._hits_lock = threading.Lock()
        self._streams: Dict[int, int] = {}          # uid -> open live-update streams
        self._seen: Dict[int, float] = {}           # uid -> last request (epoch seconds)
        self._presence_lock = threading.Lock()
        self.on_presence: Optional[Callable[[], None]] = None    # a player came online or went away (any thread)

    @property
    def running(self) -> bool:
        return self._httpd is not None

    @property
    def url(self) -> str:
        return f"http://127.0.0.1:{self.port}"

    def allow(self, uid: int) -> bool:
        limit, window = RATE
        now = time.time()
        with self._hits_lock:
            hits = [t for t in self._hits.get(uid, []) if now - t < window]
            ok = len(hits) < limit
            if ok:
                hits.append(now)
            self._hits[uid] = hits
        return ok

    # ---- presence (handler threads call these)
    def touch(self, uid: int):
        with self._presence_lock:
            self._seen[uid] = time.time()

    def stream_open(self, uid: int):
        with self._presence_lock:
            self._streams[uid] = self._streams.get(uid, 0) + 1
            self._seen[uid] = time.time()
            came = self._streams[uid] == 1
        if came:
            self._presence_changed()

    def stream_closed(self, uid: int):
        with self._presence_lock:
            n = self._streams.get(uid, 0) - 1
            if n > 0:
                self._streams[uid] = n
            else:
                self._streams.pop(uid, None)
            self._seen[uid] = time.time()
            left = n <= 0
        if left:
            self._presence_changed()

    def _presence_changed(self):
        if self.on_presence:
            try:
                self.on_presence()
            except Exception:
                rt().log("[ERROR] portal presence: " + traceback.format_exc())

    def presence(self) -> Dict[int, dict]:
        """{uid: {"online": bool, "last_seen": epoch seconds or 0}} for every player seen since the server started."""
        with self._presence_lock:
            uids = set(self._seen) | set(self._streams)
            return {u: {"online": self._streams.get(u, 0) > 0, "last_seen": self._seen.get(u, 0.0)} for u in uids}

    def start(self):
        if self._httpd:
            return
        handler = type("PortalHandler", (_Handler,), {"portal": self})
        for port in [self.port] + list(range(self.port + 1, self.port + 20)):
            try:
                self._httpd = _ExclusiveServer(("127.0.0.1", port), handler)
                self.port = port
                break
            except OSError:
                continue
        if not self._httpd:
            raise ServiceError("No free port for the player portal.")
        self._httpd.daemon_threads = True
        self.stopping.clear()
        threading.Thread(target=self._httpd.serve_forever, daemon=True, name="portal").start()
        bus = rt().bus                              # heard on the emitting thread: pages never wait for the editor's screen
        self._unsub = [bus.watch(lambda t: t in TOPICS and self.hub.publish(t))]
        world = rt().world                          # pings on the world map go straight down the live streams

        def wping(p, hub=self.hub):
            hub.push("wping " + json.dumps({"x": p["x"], "y": p["y"], "who": p["who"], "uid": p["uid"]}))
        world.listeners.append(wping)
        self._unsub.append(lambda: wping in world.listeners and world.listeners.remove(wping))
        rt().log_action(f"Player portal running on {self.url}")

    def stop(self):
        if not self._httpd:
            return
        self.stopping.set()
        for u in self._unsub:
            u()
        self._unsub = []
        self._httpd.shutdown()
        self._httpd.server_close()
        self._httpd = None
        rt().log_action("Player portal stopped.")
