"""The Discord part of the main toolbar: the server strip (the void and one round button per server) on the left and
the bot's status with a start/stop button on the right."""
import threading
from typing import Dict, Optional

from PySide6.QtCore import QObject, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QGuiApplication, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QToolButton, QWidget

from ....core import assets, events
from ....core.i18n import tr
from ....core.runtime import rt
from ....services import table
from ...errors import guard
from ...registry import toolbar_widget
from ...theme import COLORS
from ...widgets.common import button, clear_layout, label, row, tool_button

ICON = 24
STATUS = {"stopped": ("Stopped", "dim"), "connecting": ("Connecting…", "warn"), "online": ("Online", "good"),
          "error": ("Error", "bad")}


# ---------------------------------------------------------------------------- pictures
class _Pictures(QObject):
    """Server icons downloaded once, off the UI thread; `loaded(url)` says a download finished (or failed)."""
    loaded = Signal(str)

    def __init__(self):
        super().__init__()
        self.paths: Dict[str, Optional[str]] = {}
        self._lock = threading.Lock()

    def path(self, url: str) -> Optional[str]:
        """The cached picture of `url`, or None (the first call starts the download)."""
        with self._lock:
            if url in self.paths:
                return self.paths[url]
            self.paths[url] = None
        threading.Thread(target=self._fetch, args=(url,), daemon=True).start()
        return None

    def _fetch(self, url: str):
        found = assets.remote_image(url)
        with self._lock:
            self.paths[url] = found
        if found:
            self.loaded.emit(url)


_pictures: Optional[_Pictures] = None


def pictures() -> _Pictures:
    global _pictures
    if _pictures is None:
        _pictures = _Pictures()
    return _pictures


def round_icon(colour: str, text: str = "", picture: Optional[str] = None, ring: bool = False, size: int = ICON) -> QPixmap:
    """A round server button face: the picture clipped to a circle, else the text on the colour; `ring` marks the
    selected one."""
    dpr = QGuiApplication.primaryScreen().devicePixelRatio() if QGuiApplication.primaryScreen() else 1.0
    pm = QPixmap(int(size * dpr), int(size * dpr))
    pm.setDevicePixelRatio(dpr)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    inner = QRectF(2.5, 2.5, size - 5, size - 5)
    pic = QPixmap(picture) if picture else QPixmap()
    if not pic.isNull():
        clip = QPainterPath()
        clip.addEllipse(inner)
        p.setClipPath(clip)
        p.drawPixmap(inner, pic, QRectF(pic.rect()))
        p.setClipping(False)
    else:
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(colour))
        p.drawEllipse(inner)
        font = QFont(p.font())
        font.setPixelSize(int(size * (0.5 if len(text) < 2 else 0.4)))
        font.setBold(True)
        p.setFont(font)
        p.setPen(QColor("#ffffff"))
        p.drawText(inner, Qt.AlignCenter, text)
    if ring:
        p.setPen(QPen(QColor(COLORS["accent"]), 2))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QRectF(1, 1, size - 2, size - 2))
    p.end()
    return pm


def _dot(colour: str, size: int = 10) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(Qt.NoPen)
    p.setBrush(QColor(colour))
    p.drawEllipse(QRectF(1, 1, size - 2, size - 2))
    p.end()
    return pm


def _follow(widget: QWidget, *topics: str):
    """Refresh `widget` (guarded) on these bus topics until it is destroyed."""
    subs = [rt().bus.subscribe(t, lambda: guard(widget.refresh)) for t in topics]
    widget.destroyed.connect(lambda *_: [u() for u in subs])


# ---------------------------------------------------------------------------- the server strip
class ServerStrip(QWidget):
    """∅ (the void) and one round button per server; the selected one has a ring."""

    def __init__(self):
        super().__init__()
        self.box = row(spacing=1)
        self.setLayout(self.box)
        self._key, self._urls = None, set()
        pictures().loaded.connect(self._picture_ready)
        _follow(self, events.BOT, events.GUILD)
        self.refresh()

    def _button(self, face: QPixmap, tip: str, on_click=None, enabled: bool = True) -> QToolButton:
        b = tool_button("", on_click, tip=tip)
        b.setIcon(face)
        b.setIconSize(QSize(ICON, ICON))
        b.setFixedSize(ICON + 6, ICON + 6)
        b.setStyleSheet("padding: 0;")
        b.setEnabled(enabled)
        return b

    def refresh(self):
        s = table.server_strip()
        faces = [(g["id"], g["name"], g["colour"], g["initials"], pictures().path(g["icon_url"]) if g["icon_url"] else None,
                  g["selected"] and not s["void"]) for g in s["guilds"]]
        key = (s["void"], faces)
        if key == self._key:
            return
        self._key = key
        self._urls = {g["icon_url"] for g in s["guilds"] if g["icon_url"]}
        clear_layout(self.box)
        self.box.addWidget(self._button(round_icon(COLORS["raised"], "∅", ring=s["void"]),
                                        tr("Void\nNothing is sent to Discord."), lambda: guard(rt().set_void)))
        if not faces:
            self.box.addWidget(self._button(round_icon(COLORS["panel"], "?"), tr("Start the bot to load your servers"),
                                            enabled=False))
        for gid, name, colour, initials, picture, selected in faces:
            self.box.addWidget(self._button(round_icon(colour, initials, picture, selected), name,
                                            lambda gid=gid: guard(rt().set_guild, gid)))

    def _picture_ready(self, url: str):
        if url in self._urls:
            self._key = None
            guard(self.refresh)


@toolbar_widget("discord.servers", order=10, side="left")
def server_strip(window) -> QWidget:
    return ServerStrip()


# ---------------------------------------------------------------------------- the bot status
class BotStatus(QWidget):
    """A coloured dot and the bot's state (click: the Discord bot window) and a start/stop button."""

    def __init__(self, window):
        super().__init__()
        self.dot = label()
        self.text = tool_button("", lambda: window.host.open_page("audio.manager", "discord"), tip=tr("Open the Discord bot settings"))
        self.toggle = button(tr("Start"), self._toggle)
        self.setLayout(row(self.dot, self.text, self.toggle, spacing=2))
        _follow(self, events.BOT)
        self.refresh()

    def refresh(self):
        b = table.bot_view()
        text, role = STATUS.get(b["status"], (b["status"], "dim"))
        self.dot.setPixmap(_dot(COLORS[role]))
        self.text.setText(tr(text))
        tip = tr("Bot: {0}", tr(text)) + "\n" + tr(b["voice_text"])
        self.dot.setToolTip(tip)
        self.text.setToolTip(tip + "\n" + tr("Open the Discord bot window"))
        self.toggle.setText(tr("Stop") if b["running"] else tr("Start"))
        self.toggle.setProperty("kind", "danger" if b["running"] else "primary")
        self.toggle.style().unpolish(self.toggle)
        self.toggle.style().polish(self.toggle)

    def _toggle(self):
        if table.bot_view()["running"]:
            guard(rt().stop_bot)
        else:
            guard(rt().start_bot)


@toolbar_widget("discord.status", order=10, side="right")
def bot_status(window) -> QWidget:
    return BotStatus(window)
