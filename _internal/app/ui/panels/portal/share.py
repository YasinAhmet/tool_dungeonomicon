"""The Player portal window: share the battle map and each player's character on a web page they open in a
browser - start/stop, the public link (Cloudflare tunnel), each player's personal link, and what players may do."""
import threading
import time

from PySide6.QtCore import QObject, Qt, Signal
from PySide6.QtGui import QGuiApplication
from PySide6.QtWidgets import QProgressBar, QToolButton, QTreeWidget, QTreeWidgetItem, QWidget

from ....core import events
from ....core.i18n import tr
from ....core.runtime import rt
from ....services.portal import api, tunnel
from ....services.portal.controller import portal
from ... import dialogs, notify
from ...errors import guard
from ...panel import Panel
from ...registry import toolbar_widget
from ...theme import COLORS
from ...widgets.common import FlowLayout, button, card, check, label, line_edit, row, stretch, title, tool_button
from .rights import apply_rights, open_rights


class _Signals(QObject):
    progress = Signal(int, int)
    done = Signal(str)


def _wrap(*widgets) -> QWidget:
    """Buttons that wrap to a new line in a narrow window instead of pushing it wider."""
    host = QWidget()
    lay = FlowLayout(host, spacing=4)
    for w in widgets:
        lay.addWidget(w)
    return host


class PortalPanel(Panel):
    def build(self):
        lay = self.layout()
        self.sig = _Signals()
        self.sig.progress.connect(self._progress)
        self.sig.done.connect(self._downloaded)
        self.state = label("", wrap=True)
        self.start_btn = button(tr("Share with players"), lambda: self._start(True), kind="primary",
                                tip=tr("Start the page and a public address through Cloudflare (free, no router setup)"))
        self.local_btn = button(tr("This PC only"), lambda: self._start(False),
                                tip=tr("Start the page for this PC (and testing) without a public address"))
        self.stop_btn = button(tr("Stop sharing"), self._stop, kind="danger")
        lay.addWidget(card(title(tr("Sharing")), self.state, _wrap(self.start_btn, self.local_btn, self.stop_btn)))

        self.dl_text = label("", role="dim", wrap=True)
        self.dl_btn = button(tr("Download cloudflared (about 60 MB)"), self._download,
                             tip=tr("From Cloudflare's official GitHub releases into Documents\\Dungeonomicon\\tools; "
                                    "checked against Cloudflare's signature. Nothing is installed."))
        self.dl_bar = QProgressBar()
        self.dl_bar.hide()
        self.dl_card = card(title(tr("Cloudflare tunnel")), self.dl_text, row(self.dl_btn, stretch()), self.dl_bar)
        lay.addWidget(self.dl_card)

        self.link = line_edit()
        self.link.setReadOnly(True)
        self.copy_btn = button(tr("Copy"), lambda: self._copy(self.link.text()))
        # short words (the window is often narrow), the whole of it on hover; every right in the ⚙ window
        self.move = check(tr("Players move their token"), True, lambda on: apply_rights({"move_tokens": on}),
                          tip=tr("Players may move their own token on their turn"))
        self.battle_act = check(tr("Turns play out on the map"), True, lambda on: apply_rights({"battle_actions": on}),
                                tip=tr("On their turn, attacks and spells are played out on the target they pick"))
        self.music = check(tr("Show the Spotify song"), True, lambda on: apply_rights({"now_playing": on}),
                           tip=tr("Show players the song Spotify is playing (with a heart button)"))
        self.listen = check(tr("Players can listen"), True, lambda on: apply_rights({"music": on}),
                            tip=tr("Players can listen to the music on the page") + "\n" +
                            tr("The apps streamed from the Audio window (and its loops and effects, if Player page is "
                               "ticked there).\nEach player presses Listen on the page and sets their own volume."))
        self.listeners = label("", role="dim")
        self.rights = tool_button("⚙", lambda: open_rights(self),
                                  tip=tr("Player rights: what players may do on their page - see the maps, roll dice, "
                                         "rest, change their hit points, chat..."))
        self.rights_note = label("", role="dim")
        lay.addWidget(card(row(title(tr("Address")), stretch(), self.rights_note, self.rights), row(self.link, self.copy_btn),
                           self.move, self.battle_act, self.music, row(self.listen, self.listeners, stretch())))

        self.players = QTreeWidget()
        self.players.setHeaderLabels([tr("Player"), tr("Characters"), tr("Link")])
        self.players.setRootIsDecorated(False)
        self.players.setColumnWidth(0, 120)
        self.players.setColumnWidth(1, 150)
        self.players.itemDoubleClicked.connect(lambda it, _c: self._copy(it.data(0, Qt.UserRole + 1)))
        self.players.currentItemChanged.connect(lambda *_: self._can_send())
        self.send_one = button(tr("Send on Discord"), lambda: self._send_one())
        self.send_all = button(tr("Send everyone their link on Discord"), self._send_all, kind="primary",
                               tip=tr("Players added by hand (🔗) aren't on Discord: copy their link and send it yourself"))
        lay.addWidget(card(title(tr("Players")), label(tr("Each player has their own link: it logs them in, so send it only "
                                                          "to them. Double-click a row to copy its link."), role="dim", wrap=True),
                           self.players,
                           _wrap(button(tr("Copy link"), lambda: self._copy(self._sel("link"))),
                                 button(tr("Copy every link"), self._copy_all,
                                        tip=tr("Every player's name and link, one per line, to paste where you talk to them")),
                                 self.send_one,
                                 button(tr("New link"), self._renew, tip=tr("Make a new link for this player; the old one stops working")),
                                 self.send_all)), 1)
        self.on(events.PORTAL, self.refresh)
        self.on(events.RIGHTS, self.refresh)
        self.on(events.CHARACTERS, self.refresh)
        self.on(events.BOT, self.refresh)

    # ------------------------------------------------------------------ showing
    def refresh(self):
        st = portal.status()
        have = bool(tunnel.find())
        if not st["running"]:
            text = tr("Not sharing. Players can't reach anything.")
        elif st["public"] and not st["url"]:
            text = tr("Starting the public address…") if st["tunnel"] else tr("The tunnel stopped: {0}", tr(st["tunnel_error"] or ""))
        elif st["public"]:
            text = tr("Sharing on the internet. Send each player their own link below.")
        else:
            text = tr("Sharing on this PC only: {0}", st["local"])
        self.state.setText(text)
        self.start_btn.setEnabled(not st["running"] and have)
        self.local_btn.setEnabled(not st["running"])
        self.stop_btn.setEnabled(st["running"])
        self.dl_card.setVisible(not have or self.dl_bar.isVisible())
        self.dl_text.setText(tr("Players reach the page through a free Cloudflare quick tunnel. It needs cloudflared, "
                                "one program from Cloudflare (nothing is installed)."))
        self.link.setText(st["url"])
        self.copy_btn.setEnabled(bool(st["url"]))
        self.move.blockSignals(True)
        self.move.setChecked(st["settings"]["move_tokens"])
        self.move.blockSignals(False)
        self.battle_act.blockSignals(True)
        self.battle_act.setChecked(st["settings"]["battle_actions"])
        self.battle_act.blockSignals(False)
        self.music.blockSignals(True)
        self.music.setChecked(st["settings"]["now_playing"])
        self.music.blockSignals(False)
        self.listen.blockSignals(True)
        self.listen.setChecked(st["settings"]["music"])
        self.listen.blockSignals(False)
        self.listeners.setText(tr("🎧 {0} listening", st["listeners"]) if st["listeners"] else "")
        off = [k for k, on in st["settings"].items() if not on]
        self.rights_note.setText(tr("{0} turned off", len(off)) if off else "")
        self.rights_note.setToolTip("\n".join(tr(w) for _g, rows in api.RIGHTS for k, w, _t in rows if k in off))
        chosen = self._sel("id")
        self.players.clear()
        for p in portal.links() if st["url"] else api.roster_links(""):
            online = bool(p.get("online"))
            it = QTreeWidgetItem([("🟢 " if online else "⚪ ") + ("" if p["discord"] else "🔗 ") + p["name"],
                                  ", ".join(p["characters"]), p["link"] or tr("(start sharing first)")])
            seen = p.get("last_seen") or 0
            it.setToolTip(0, (tr("On the portal now") if online else
                              tr("Last seen {0}", time.strftime("%H:%M", time.localtime(seen))) if seen else tr("Not on the portal yet"))
                          + ("" if p["discord"] else "\n" + tr("Added by hand (not on Discord): send them their portal link yourself.")))
            it.setData(0, Qt.UserRole, p["id"])
            it.setData(0, Qt.UserRole + 1, p["link"])
            it.setData(0, Qt.UserRole + 2, p["discord"])
            self.players.addTopLevelItem(it)
            if p["id"] == chosen:
                self.players.setCurrentItem(it)
        self.send_all.setEnabled(bool(st["url"]) and self.rt.bot_manager.is_ready)
        self._can_send()

    def _can_send(self):
        """Send on Discord: only for a Discord player (a manual one's link is copied and sent by hand)."""
        it = self.players.currentItem()
        self.send_one.setEnabled(bool(portal.url) and self.rt.bot_manager.is_ready and it is not None
                                 and bool(it.data(0, Qt.UserRole + 2)))

    def _sel(self, what: str):
        it = self.players.currentItem()
        if not it:
            return None
        return it.data(0, Qt.UserRole) if what == "id" else it.data(0, Qt.UserRole + 1)

    # ------------------------------------------------------------------ doing
    def _start(self, public: bool):
        self.run(portal.start, public)

    def _stop(self):
        on = [p["name"] for p in portal.links() if p.get("online")] if portal.url else []
        if on and not dialogs.confirm(self, tr("{0} are on the portal now. Stop sharing? The next address is new, so everyone "
                                               "needs a new link.", ", ".join(on)), yes=tr("Stop sharing")):
            return
        self.run(portal.stop)

    def _copy_all(self):
        rows = [f"{p['name']}: {p['link']}" for p in portal.links() if p.get("link")] if portal.url else []
        if not rows:
            notify.warn(tr("Start sharing first: the links aren't ready yet."))
            return
        self._copy("\n".join(rows))

    def _copy(self, text: str):
        if text:
            QGuiApplication.clipboard().setText(text)
            notify.good(tr("Copied."))

    def _renew(self):
        uid = self._sel("id")
        if uid and dialogs.confirm(self, tr("Make a new link for this player? Their old link stops working.")):
            self.run(portal.renew, uid)

    def _send_one(self):
        uid = self._sel("id")
        if uid:
            n = self.run(portal.send_links, uid)
            if n:
                notify.good(tr("Link sent."))

    def _send_all(self):
        n = self.run(portal.send_links)
        if n is not None:
            notify.good(tr("Links sent to {0} player(s).", n))
            by_hand = [p["name"] for p in portal.links() if not p["discord"]]
            if by_hand:
                notify.info(tr("Not on Discord, send their links yourself: {0}", ", ".join(by_hand)))

    def _download(self):
        self.dl_btn.setEnabled(False)
        self.dl_bar.show()
        self.dl_bar.setRange(0, 0)

        def work():
            try:
                tunnel.download(lambda done, total: self.sig.progress.emit(done, total))
                self.sig.done.emit("")
            except Exception as e:                    # noqa: BLE001 - shown in the window
                self.sig.done.emit(str(e))
        threading.Thread(target=work, daemon=True, name="cloudflared-download").start()

    def _progress(self, done: int, total: int):
        if total:
            self.dl_bar.setRange(0, total)
            self.dl_bar.setValue(done)

    def _downloaded(self, error: str):
        self.dl_bar.hide()
        self.dl_btn.setEnabled(True)
        if error:
            notify.error(tr(error))
        else:
            notify.good(tr("cloudflared is ready."))
        self.refresh()


class PortalStatus(QToolButton):
    """The toolbar's glance at the portal: 🌐 and how many players have their page open (dim while not sharing); who, on
    hover; a click opens the Player portal page."""

    def __init__(self, window):
        super().__init__()
        self.setAutoRaise(True)
        self.setCursor(Qt.PointingHandCursor)
        self.clicked.connect(lambda: window.host.open_page("characters.roster", "portal"))
        subs = [rt().bus.subscribe(t, lambda: guard(self.refresh)) for t in (events.PORTAL, events.CHARACTERS)]
        self.destroyed.connect(lambda *_: [u() for u in subs])
        self.refresh()

    def refresh(self):
        st = portal.status()
        players = api.roster_links("", portal.presence()) if st["running"] else []
        online = [p["name"] for p in players if p["online"]]
        opening = st["running"] and st["public"] and st["tunnel"] and not st["url"]     # the tunnel is still coming up
        self.setText("🌐 …" if opening else f"🌐 {len(online)}/{len(players)}" if st["running"] else "🌐")
        self.setStyleSheet(f"QToolButton {{ color: {COLORS['good'] if online else COLORS['dim'] if opening or not st['running'] else COLORS['text']}; }}")
        where = (tr("Opening the players' link…") if opening else tr("Sharing on the internet") if st["public"]
                 else tr("Sharing on this PC only")) if st["running"] else tr("Not sharing")
        self.setToolTip(tr("Player portal") + ": " + where +
                        ("\n" + tr("Online: {0}", ", ".join(online)) if online else "") +
                        "\n" + tr("Click: the Player portal page"))


@toolbar_widget("portal.status", order=5, side="right")
def portal_status(window) -> QWidget:
    return PortalStatus(window)
