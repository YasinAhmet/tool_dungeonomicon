"""The player portal as one switch: the local server plus (optionally) the public Cloudflare tunnel.

    portal.start(public=True)     # serve, then open the tunnel; portal.url becomes the address to share
    portal.links()                # each player's personal link (+ online, last_seen)
    portal.presence()             # {uid: {"online": bool, "last_seen": epoch or 0}}
    portal.send_links()           # DM every Discord player their link through the bot (manual players: the DM sends it)
    portal.stop()

It emits events.PORTAL whenever its state changes (also when a player's page comes online or goes away, or starts or
stops listening to the music), so the editor's window follows it.
"""
from typing import Dict, List, Optional

from ...core import events
from ...core.runtime import rt
from ..common import ServiceError
from ..players import is_manual
from . import api
from .access import access
from .music import music
from .server import PortalServer
from .tunnel import Tunnel


class Portal:
    def __init__(self):
        self.server: Optional[PortalServer] = None
        self.tunnel = Tunnel()
        self.tunnel.on_change = self._changed
        self.public = False

    def _changed(self):
        rt().bus.emit(events.PORTAL)

    @property
    def running(self) -> bool:
        return bool(self.server and self.server.running)

    @property
    def url(self) -> str:
        """The address players use: the tunnel's when public, else the local one (this PC only)."""
        if not self.running:
            return ""
        if self.public:
            return self.tunnel.url
        return self.server.url

    def status(self) -> dict:
        return {"running": self.running, "public": self.public, "url": self.url, "local": self.server.url if self.running else "",
                "tunnel": self.tunnel.running, "tunnel_error": self.tunnel.error, "settings": api.settings(),
                "listeners": music.listeners}

    def start(self, public: bool = True):
        if not self.server:
            self.server = PortalServer()
        self.server.on_presence = self._changed          # called on the server's threads; the bus is thread-safe
        self.server.start()
        self.public = public
        if api.settings()["now_playing"]:
            from ..nowplaying import nowplaying
            nowplaying.start(lambda: rt().bus.emit(events.NOWPLAYING))
        if public:
            self.tunnel.start(self.server.port)
        self._changed()

    def stop(self):
        from ..nowplaying import nowplaying
        nowplaying.stop()
        self.tunnel.stop()
        if self.server:
            self.server.stop()
        self._changed()

    def ping(self, x: Optional[float], y: float = 0.0, press: bool = False):
        """The DM's pointer on the battle map (tile units), shown on every player's map; press: a ping rippling out
        from it. x=None: the pointer is gone. Nothing is kept: it goes straight down the live streams."""
        if self.running:
            self.server.hub.push("ping off" if x is None else f"ping {float(x):.2f} {float(y):.2f} {1 if press else 0}")

    def links(self) -> List[dict]:
        return api.roster_links(self.url, self.presence())

    def presence(self) -> Dict[int, dict]:
        """{uid: {"online": bool, "last_seen": epoch seconds or 0}}: online while the player's page is open (it holds
        the live-update stream); last_seen is their last request. Only players seen since the app started."""
        return self.server.presence() if self.server else {}

    def renew(self, user_id: int):
        access.renew(user_id)
        self._changed()

    def send_links(self, only: Optional[int] = None) -> int:
        """DM each Discord player (or one) their link; returns how many messages were sent. Players added by hand
        aren't on Discord: they are skipped (asked for alone, it is refused)."""
        if only is not None and is_manual(only):
            raise ServiceError("This player isn't on Discord: copy their link and send it to them yourself.")
        if not self.url or (self.public and not self.tunnel.url):
            raise ServiceError("Start sharing first: the link isn't ready yet.")
        if not rt().bot_manager.is_ready:
            raise ServiceError("Start the Discord bot to send the links.")
        sent = 0
        for p in self.links():
            if (only is not None and p["id"] != only) or not p["discord"]:
                continue
            text = (f"🗺️ Your link to the table: {p['link']}\n"
                    "It shows the battle map and your character, and lets you roll from it. Keep it to yourself - it logs you in.")
            if rt().bot_manager.send_dm(p["id"], text):
                sent += 1
        rt().log_action(f"Player portal links sent to {sent} player(s).")
        return sent


portal = Portal()
