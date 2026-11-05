"""The Duel window: open duel mode for the players (their page gets a Duel tab where anyone opens a lobby, joins one
or watches any of them), see every lobby and who joined it as what, open lobbies of your own, start and end any
lobby's fight, and show a duel's own map on the battle windows - where everything works as on the campaign's
battle. Nothing of a duel is kept (services/duel)."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QTreeWidget, QTreeWidgetItem, QWidget

from ....core import events
from ....core.i18n import tr
from ... import dialogs, notify
from ...errors import guard
from ...panel import Panel
from ...registry import panel
from ...widgets.common import FlowLayout, button, card, check, label, title


def pick_text(p: dict) -> str:
    """'Wizard, level 5 · 3 spells' / 'A random monster, CR 2' / 'A copy of Bram'."""
    if p.get("kind") == "hero":
        text = tr("{0}, level {1}", tr(p["class"]), p["level"])
        return text + (" · " + tr("{0} spells picked", len(p["spells"])) if p.get("spells") else "")
    if p.get("kind") == "copy":
        return tr("A copy of {0}", p.get("character"))
    if p.get("monster"):
        return tr("{0}, CR {1}", tr(p.get("name") or p["monster"]), p.get("cr"))
    return tr("A random monster, CR {0}", p.get("cr"))


def state_text(r: dict) -> str:
    """How a lobby stands: 'Lobby: 3 joined' / 'Fighting: round 2' / 'Alice wins the duel!' / 'The fight is over'."""
    if r["winner"]:
        return "🏆 " + tr("{0} wins the duel!", r["winner"])
    if r["running"]:
        return tr("Fighting: round {0}.", r["round"]) if r["status"] == "active" else tr("The fight is over. End the duel to go back to the lobby.")
    return tr("Lobby: {0} joined. Start when everyone has picked.", len(r["rows"])) if r["rows"] else tr("Lobby: waiting for players to join.")


def _wrap(*widgets) -> QWidget:
    """Buttons that wrap to a new line in a narrow window."""
    host = QWidget()
    lay = FlowLayout(host, spacing=4)
    for w in widgets:
        lay.addWidget(w)
    return host


def open_duel_window(from_widget) -> None:
    """Bring the Duel window up (a tab with the Inspector when it isn't open)."""
    from ..characters.char_actions import host_of
    host = host_of(from_widget)
    if hasattr(host, "docks"):
        host.open("battle.duel")


@panel("battle.duel", "Duel", "Battle", icon="🤺", area="right",
       description="Duels for fun, apart from everything else and as many at once as the players like: anyone opens a "
                   "lobby on their page, the others join it - a premade hero (any core class, level 1 to 12, with their "
                   "own spells), a random monster of a challenge rating or a copy of their own character - or watch, and "
                   "each is played on a map of its own. Nothing of it is kept.")
class DuelPanel(Panel):
    def build(self):
        lay = self.layout()
        self.sel = None                                      # the lobby picked in the list (its id)
        self.open_box = check(tr("Duel open: players see a Duel tab on their page"), False, self._open,
                              tip=tr("Players open lobbies there, join one or watch any of them. Untick to close duel mode: "
                                     "every lobby and fight is gone."))
        self.mode = label("", role="dim", wrap=True)
        self.rooms = QTreeWidget()
        self.rooms.setHeaderLabels([tr("Lobby"), tr("Host"), tr("Fighters"), tr("State")])
        self.rooms.setRootIsDecorated(False)
        self.rooms.setColumnWidth(0, 130)
        self.rooms.setColumnWidth(1, 80)
        self.rooms.setColumnWidth(2, 60)
        self.rooms.currentItemChanged.connect(lambda it, _old: self._pick(it))
        self.new_btn = button("＋ " + tr("New lobby"), self._new, tip=tr("Open a lobby of your own: players join it, you start it"))
        self.close_btn = button(tr("Close lobby"), self._close, kind="danger", tip=tr("Close the selected lobby (its fight is thrown away)"))
        lay.addWidget(card(title(tr("Duels")), self.open_box, self.mode, self.rooms, _wrap(self.new_btn, self.close_btn)))

        self.room_title = title(tr("Lobby"))
        self.state = label("", wrap=True)
        self.start_btn = button("▶ " + tr("Start the duel"), self._start, kind="primary",
                                tip=tr("Make everyone's fighter, put them around the arena, roll initiative and begin"))
        self.stop_btn = button("⏹ " + tr("End the duel"), self._stop, kind="danger",
                               tip=tr("Throw the fight and its fighters away; back to the lobby (the arena and the picks stay)"))
        self.show_btn = button("🗺 " + tr("Show on the battle map"), self._show, checkable=True,
                               tip=tr("The battle windows show this duel's map - every tool works there - "
                                      "instead of the campaign's battle (which goes on untouched)"))
        self.rows = QTreeWidget()
        self.rows.setHeaderLabels([tr("Player"), tr("Fights as"), tr("HP")])
        self.rows.setRootIsDecorated(False)
        self.rows.setColumnWidth(0, 110)
        self.rows.setColumnWidth(1, 190)
        self.kick_btn = button(tr("Take out of the duel"), self._kick, tip=tr("Remove the selected player from the lobby"))
        lay.addWidget(card(self.room_title, self.state, _wrap(self.start_btn, self.stop_btn, self.show_btn), self.rows,
                           _wrap(self.kick_btn)), 1)

        self.camp_btn = button(tr("Use the campaign's map"), lambda: self._arena("use_campaign_map"),
                               tip=tr("The campaign battle's map, walls and pictures become the arena (its creatures stay out)"))
        self.empty_btn = button(tr("Empty arena"), lambda: self._arena("new_arena"))
        lay.addWidget(card(title(tr("Arena")), label(tr("Each lobby has a map of its own. Show it on the battle map to draw "
                                                        "walls, place props, add monsters from the bestiary or move tokens - "
                                                        "as on any battle."), role="dim", wrap=True),
                           _wrap(self.camp_btn, self.empty_btn)))
        self.on(events.DUEL, self.refresh)

    # ------------------------------------------------------------------ showing
    def refresh(self):
        v = self.rt.duel.view()
        self.open_box.blockSignals(True)
        self.open_box.setChecked(v["open"])
        self.open_box.blockSignals(False)
        rooms = {r["id"]: r for r in v["rooms"]}
        if self.sel not in rooms:
            self.sel = v["shown"] if v["shown"] in rooms else next(iter(rooms), None)
        fighting = sum(1 for r in v["rooms"] if r["running"])
        self.mode.setText(tr("Closed. Open the duel and the players get a Duel tab on their page.") if not v["open"]
                          else tr("{0} lobbies, {1} fighting.", len(rooms), fighting) if rooms
                          else tr("No lobbies yet: players open them on their page, or open one here."))
        self.rooms.blockSignals(True)
        self.rooms.clear()
        for r in v["rooms"]:
            it = QTreeWidgetItem([("🗺 " if r["shown"] else "") + r["name"], r["host_name"] or tr("DM"), str(len(r["rows"])),
                                  tr("Fighting") if r["running"] else tr("Lobby")])
            it.setData(0, Qt.UserRole, r["id"])
            self.rooms.addTopLevelItem(it)
            if r["id"] == self.sel:
                self.rooms.setCurrentItem(it)
        self.rooms.blockSignals(False)
        r = rooms.get(self.sel)
        self.new_btn.setEnabled(v["open"])
        self.close_btn.setEnabled(r is not None)
        self.room_title.setText((r["name"] if r else tr("Lobby")).upper())
        self.state.setText(state_text(r) if r else "")
        self.start_btn.setEnabled(bool(r) and not r["running"] and bool(r["rows"]))
        self.stop_btn.setEnabled(bool(r) and r["running"])
        self.show_btn.blockSignals(True)
        self.show_btn.setChecked(bool(r) and r["shown"])
        self.show_btn.blockSignals(False)
        self.show_btn.setEnabled(r is not None)
        for b in (self.camp_btn, self.empty_btn):
            b.setEnabled(bool(r) and not r["running"])
        self.kick_btn.setEnabled(bool(r) and not r["running"] and bool(r["rows"]))
        self.rows.clear()
        for row in (r["rows"] if r else []):
            hp = f"{row['hp']}/{row['max_hp']}" if row["hp"] is not None else ""
            it = QTreeWidgetItem([row["player"], row["name"] or pick_text(row["pick"]), ("✖ " if row["out"] else "") + hp])
            it.setToolTip(1, pick_text(row["pick"]))
            it.setData(0, Qt.UserRole, row["uid"])
            self.rows.addTopLevelItem(it)

    def _pick(self, it):
        if it is not None:
            self.sel = it.data(0, Qt.UserRole)
            guard(self.refresh)

    # ------------------------------------------------------------------ doing
    def _open(self, on: bool):
        duel = self.rt.duel
        if not on and any(r.running for r in duel.rooms.values()) and not dialogs.confirm(
                self, tr("A duel is being fought. Close duel mode and throw every lobby away?"), tr("Close the duel")):
            self.refresh()
            return
        guard(duel.set_open, on)

    def _new(self):
        room = guard(self.rt.duel.create, None)
        if room is not None:
            self.sel = room.id
            guard(self.refresh)

    def _close(self):
        room = self.rt.duel.rooms.get(self.sel)
        if room is not None and (not room.running or dialogs.confirm(self, tr("The fight is on. Close this lobby and throw it away?"),
                                                                     tr("Close lobby"))):
            guard(self.rt.duel.close, room.id)

    def _start(self):
        duel = self.rt.duel
        text = guard(duel.start, self.sel)
        if text:
            notify.good(tr(text))
            duel.show(True, self.sel)
            from ..characters.char_actions import host_of
            host = host_of(self)
            if hasattr(host, "docks") and host.docks.get("battle.map") is None:
                host.open("battle.map", "center")

    def _stop(self):
        if dialogs.confirm(self, tr("Throw this fight and its fighters away?"), tr("End the duel")):
            guard(self.rt.duel.stop, self.sel)

    def _show(self):
        guard(self.rt.duel.show, self.show_btn.isChecked(), self.sel)

    def _kick(self):
        it = self.rows.currentItem()
        if it is not None:
            guard(self.rt.duel.kick, self.sel, it.data(0, Qt.UserRole))

    def _arena(self, what: str):
        if dialogs.confirm(self, tr("Replace the duel's map? What is drawn on it now is lost."), tr("Arena")):
            guard(getattr(self.rt.duel, what), self.sel)
