"""The Party list: every character with its portrait, class and hit points, folded under the player who owns it (the
selected Discord server's players, then the characters nobody owns). Selecting a character selects it everywhere;
double-click opens its sheet; drag characters onto a player to give them; right-click marks a character as playing this
session (the battle's Add players window takes those in one click), renames, moves, awards XP, rests, exports or deletes
- for every selected character at once. New characters come from the creation wizard; exported HTML sheets can be
imported. A player is attached by Discord (a server member or a Discord ID: the bot sends their portal link and takes
their commands) or by hand (just a name, 🔗: the DM sends their link - Copy portal link on the player's menu)."""
import html
from typing import List, Optional

from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtGui import QColor, QGuiApplication, QIcon, QPainter
from PySide6.QtWidgets import (QAbstractItemView, QButtonGroup, QComboBox, QFormLayout, QMenu, QRadioButton,
                               QStyledItemDelegate, QTreeWidget, QTreeWidgetItem, QWidget)

from ....core import events
from ....core.i18n import tr
from ....core.runtime import rt
from ....services import table
from ....services.players import is_manual
from ... import dialogs, notify
from ...errors import guard
from ...panel import Panel
from ...theme import COLORS
from ...widgets.common import Combo, button, label, line_edit, row, stretch, title
from ...widgets.icons import icon_button
from . import char_actions as A
from .char_actions import UNASSIGNED
from .portrait import portrait_pixmap
from .roster import party_rest

SESSION = "● "                                   # before the name of a character playing this session
BY_HAND = "🔗 "                                  # before the name of a player added by hand (not on Discord)


SUMMARY = Qt.UserRole + 1                                  # a character row's roster line (hp, conditions...)


def _condition_html(name: str) -> str:
    """A condition in a hover card: its picture and its name in its colour."""
    from ....services.battle.icons import BADGES, path as icon_path
    pic = BADGES.get(name) and icon_path(BADGES[name][0])
    colour = (BADGES.get(name) or (None, COLORS["warn"]))[1]
    img = f"<img src='{html.escape(pic)}' width='14' height='14'> " if pic else ""
    return f"{img}<span style='color:{colour}'>{html.escape(tr(name))}</span>"


class _NameDelegate(QStyledItemDelegate):
    """The name as usual, and the character's conditions as small pictures at the cell's right end (names on hover)."""

    def paint(self, p: QPainter, opt, index):
        super().paint(p, opt, index)
        c = index.data(SUMMARY)
        if not c:
            return
        from ....services.battle.icons import BADGES
        from ...widgets.icons import game_pixmap
        pics = [game_pixmap(k, 13, BADGES[k][1]) for k in c.get("conditions") or [] if k in BADGES][:3]
        x = opt.rect.right() - 2
        for pm in reversed([pm for pm in pics if pm]):
            x -= 14
            p.drawPixmap(x, opt.rect.center().y() - 6, pm)


class _HpDelegate(QStyledItemDelegate):
    """Hit points as a bar with the numbers on it (red when low), like the initiative order's."""

    def paint(self, p: QPainter, opt, index):
        c = index.data(SUMMARY)
        if not c or not c.get("max_hp"):
            return super().paint(p, opt, index)
        self.initStyleOption(opt, index)
        opt.text = ""
        opt.widget.style().drawControl(opt.widget.style().ControlElement.CE_ItemViewItem, opt, p, opt.widget)
        r = opt.rect.adjusted(2, 3, -2, -3)
        f = max(0.0, min(1.0, c["hp"] / c["max_hp"]))
        p.save()
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(COLORS["input"]))
        p.drawRoundedRect(r, 3, 3)
        if f > 0:
            fill = QColor(COLORS["bad"] if f <= .25 else COLORS["warn"] if f <= .5 else COLORS["good"])
            fill.setAlpha(110)
            p.setBrush(fill)
            p.drawRoundedRect(QRectF(r.left(), r.top(), max(4.0, r.width() * f), r.height()), 3, 3)
        p.setPen(QColor(COLORS["bad"] if c["hp"] <= 0 else COLORS["text"]))
        p.drawText(r, Qt.AlignCenter, f"{c['hp']}/{c['max_hp']}" + (f" +{c['temp_hp']}" if c.get("temp_hp") else ""))
        p.restore()


class _Tree(QTreeWidget):
    """Players and their characters; characters dropped on a player (or on one of their characters) move to them."""
    dropped = Signal(list, int)

    def __init__(self):
        super().__init__()
        self.setDragEnabled(True)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(True)
        self.setDragDropMode(QAbstractItemView.DragDrop)
        self.setSelectionMode(QAbstractItemView.ExtendedSelection)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        narrow = self.viewport().width() < 300              # the names keep their room; the class is in the row's hover card
        if self.isColumnHidden(1) != narrow:
            self.setColumnHidden(1, narrow)

    @staticmethod
    def player_of(it: Optional[QTreeWidgetItem]) -> Optional[int]:
        while it is not None:
            kind, value = it.data(0, Qt.UserRole) or (None, None)
            if kind == "player":
                return value
            it = it.parent()
        return None

    def dragEnterEvent(self, e):
        if e.source() is self:
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        target = self.itemAt(e.position().toPoint())
        if e.source() is self and self.player_of(target) is not None:
            e.acceptProposedAction()
        else:
            e.ignore()

    def dropEvent(self, e):
        target = self.player_of(self.itemAt(e.position().toPoint()))
        e.ignore()                                   # the tree never moves rows itself; the refresh redraws them
        names = [it.data(0, Qt.UserRole)[1] for it in self.selectedItems()
                 if (it.data(0, Qt.UserRole) or (None,))[0] == "char" and self.player_of(it) != target]
        if names and target is not None:
            self.dropped.emit(names, target)


class PartyListPanel(Panel):
    def build(self):
        self.closed = set()                         # players folded shut
        self.hint = label("⚠", role="warn")           # why the list may be short: on hover (the bottom row)
        self.query = line_edit(placeholder=tr("search characters and players…"),
                               tip=tr("Players without characters are hidden; search to find them."))
        self.query.textChanged.connect(lambda _t: self.refresh())
        self.layout().addLayout(row(self.query,
                                    button(tr("New…"), lambda: self.new_character(), kind="primary",
                                           tip=tr("Create a new character (the creation wizard), for the selected player")),
                                    button("⚡", lambda: self.quick_character(self.selected_player()),
                                           tip=tr("Quick adventurer: pick a concept or a race, class and level; the rest is "
                                                  "decided for you")),
                                    icon_button("import", lambda: A.import_dialog(self), tr("Import…") + "\n" +
                                                tr("Bring exported HTML sheets back in. A sheet for an existing character "
                                                   "replaces it (the old one is backed up first); other sheets become new "
                                                   "characters.")),
                                    icon_button("add_players", self.add_player, tr("Add a player: a Discord user, or just a name"),
                                                color=COLORS["accent"]), spacing=2))
        self.tree = _Tree()
        self.tree.setHeaderLabels([tr("Player / character"), tr("Class"), tr("HP")])
        self.tree.setColumnWidth(0, 160)
        self.tree.setColumnWidth(1, 96)
        head = self.tree.header()                                             # the name takes what's left: the HP bar stays in sight
        head.setStretchLastSection(False)
        head.setSectionResizeMode(0, head.ResizeMode.Stretch)
        head.setSectionResizeMode(2, head.ResizeMode.Fixed)
        self.tree.setColumnWidth(2, 60)
        self.tree.setItemDelegateForColumn(0, _NameDelegate(self.tree))      # the conditions at the name's end
        self.tree.setItemDelegateForColumn(2, _HpDelegate(self.tree))        # hit points as a bar
        self.tree.setUniformRowHeights(True)
        self.tree.currentItemChanged.connect(lambda cur, _p: self._picked(cur))
        self.tree.itemDoubleClicked.connect(self._double)
        self.tree.itemChanged.connect(self._ticked)
        self.tree.itemExpanded.connect(lambda it: self.closed.discard(_Tree.player_of(it)))
        self.tree.itemCollapsed.connect(lambda it: self.closed.add(_Tree.player_of(it)))
        self.tree.dropped.connect(self._give)
        self.tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tree.customContextMenuRequested.connect(self._menu)
        self.layout().addWidget(self.tree, 1)
        self.count = label("", role="dim")
        export = icon_button("export", None, tr("Export") + "\n" + tr("Export the selected character's sheet"))
        export.setPopupMode(export.ToolButtonPopupMode.InstantPopup)
        export.setMenu(A.export_menu(self, self.current))
        self.layout().addLayout(row(self.count, self.hint, stretch(),
                                    icon_button("award", lambda: self.chosen() and A.award_xp(self, self.chosen()),
                                                tr("XP…") + "\n" + tr("Award XP to the selected characters"), color=COLORS["warn"]),
                                    export,
                                    icon_button("clear", lambda: self.current() and A.archive(self, self.current()),
                                                tr("Delete…") + "\n" + tr("Archive the selected character"), color=COLORS["bad"]),
                                    spacing=2))
        self.on(events.CHARACTERS, self.refresh)
        self.on(events.GUILD, self.refresh)
        self.on(events.BOT, self.refresh)
        self.on(events.SELECTION, self._sync)

    # ------------------------------------------------------------------ data
    def refresh(self):
        s = table.players()
        bot = table.bot_state()
        if not rt().guild_id:
            why = tr("No Discord server selected: only players known from earlier sessions are listed.")
        elif not bot["ready"]:
            why = tr("Bot offline: only known players are listed.")
        elif not bot["members_enabled"]:
            why = tr("Members intent is off: only players who used the bot are listed.")
        else:
            why = ""
        self.hint.setToolTip(why)
        self.hint.setVisible(bool(why))
        needle = self.query.text().strip().lower()
        chars = {c["name"]: c for c in s["characters"]}
        session = set(rt().players.session_party())
        keep = self.selected_player()

        def hit(n: str) -> bool:
            c = chars.get(n) or {}
            return needle in f"{n} {c.get('classes', '')} {c.get('race', '')}".lower()
        groups = []
        for p in sorted(s["players"], key=lambda p: (not p["characters"], p["name"].lower())):
            mine = p["characters"] if not needle or needle in p["name"].lower() or needle in str(p["id"]) else \
                [n for n in p["characters"] if hit(n)]
            if mine or (needle and (needle in p["name"].lower() or needle in str(p["id"]))) or (not needle and p["id"] == keep):
                groups.append({**p, "shown": mine})
        free = [n for n in s["unassigned"] if not needle or hit(n)]
        if free or not needle:
            groups.append({"id": UNASSIGNED, "name": "🗂 " + tr("Unassigned"), "characters": s["unassigned"], "shown": free,
                           "active": None})
        self.tree.blockSignals(True)
        self.tree.clear()
        for p in groups:
            mine = p["characters"]
            playing = sum(1 for n in mine if n in session)
            head = QTreeWidgetItem([(BY_HAND if p.get("manual") else "") + f"{p['name']}  ({len(mine)})"
                                    + (f"  · {SESSION}{playing}" if playing else "")])
            head.setData(0, Qt.UserRole, ("player", p["id"]))
            head.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsDropEnabled)
            f = head.font(0)
            f.setBold(True)
            head.setFont(0, f)
            if p.get("manual"):
                head.setToolTip(0, tr("{0}\nAdded by hand (not on Discord): send them their portal link yourself.", p["name"]))
            elif p["id"] != UNASSIGNED:
                head.setToolTip(0, tr("{0}\nDiscord ID {1}", p["name"], p["id"]))
            self.tree.addTopLevelItem(head)
            for n in p["shown"]:
                c = chars.get(n)
                if c:
                    head.addChild(self._row(c, n in session, p.get("active") == n and len(mine) > 1 and not p.get("manual")))
            if not p["shown"]:
                none = QTreeWidgetItem([tr("No characters")])
                none.setFlags(Qt.ItemIsEnabled)
                none.setForeground(0, QColor(COLORS["dim"]))
                head.addChild(none)
            head.setExpanded(bool(needle) or p["id"] not in self.closed)
            if p["id"] == keep and rt().selected_name not in mine:
                self.tree.setCurrentItem(head)
        self.tree.blockSignals(False)
        total = len(chars)
        shown = sum(len(p["shown"]) for p in groups)
        text = tr("{0} characters", total) if shown == total else tr("{0} of {1}", shown, total)
        playing = len(session & set(chars))
        self.count.setText(text + (" · " + tr("{0} this session", playing) if playing else ""))
        if chars and rt().selected_name not in chars:
            rt().select_character(min(chars, key=str.lower))   # something is always selected when there is anyone
        self._sync()

    def _row(self, c: dict, playing: bool, discord: bool) -> QTreeWidgetItem:
        n = c["name"]
        it = QTreeWidgetItem([n + ("  💬" if discord else ""), c["classes"] or tr("(not created)"),
                              f"{c['hp']}/{c['max_hp']}"])
        it.setData(0, Qt.UserRole, ("char", n))
        it.setData(0, SUMMARY, c)
        it.setData(2, SUMMARY, c)
        it.setFlags(Qt.ItemIsEnabled | Qt.ItemIsSelectable | Qt.ItemIsDragEnabled | Qt.ItemIsUserCheckable)
        it.setCheckState(0, Qt.Checked if playing else Qt.Unchecked)     # ☑ playing this session
        it.setIcon(0, QIcon(portrait_pixmap(*c["portrait"], 22)))
        tip = [f"<b>{html.escape(n)}</b>", html.escape(f"{c['race']} · {c['line']}")]
        if c.get("ac") is not None:                          # what the DM checks at a glance
            temp = f" (+{c['temp_hp']})" if c.get("temp_hp") else ""
            tip.append(f"HP {c['hp']}/{c['max_hp']}{temp} · " + tr("AC {0}", c["ac"]) + " · "
                       + tr("Passive Perception {0}", c["passive"]) + " · " + tr("{0} ft", c["speed"]))
        if c.get("conditions"):
            tip.append(" ".join(_condition_html(x) for x in c["conditions"]))
        tip.append(tr("☑ the box: playing this session - they share the team inventory, eat from the group's food and "
                      "show on the World map"))
        if playing:
            tip.append(f"<span style='color:{COLORS['good']}'>" + tr("Playing this session") + "</span>")
            it.setForeground(0, QColor(COLORS["good"]))
        if discord:
            tip.append(tr("The character this player's Discord commands act on"))
        it.setToolTip(0, "<qt>" + "<br>".join(tip) + "</qt>")
        if c["max_hp"] and c["hp"] <= c["max_hp"] // 4:
            it.setForeground(2, QColor(COLORS["bad"]))
        return it

    def _sync(self):
        """Highlight the selected character."""
        name = rt().selected_name
        if self.current() == name:
            return
        for i in range(self.tree.topLevelItemCount()):
            head = self.tree.topLevelItem(i)
            for j in range(head.childCount()):
                it = head.child(j)
                if it.data(0, Qt.UserRole) == ("char", name):
                    self.tree.blockSignals(True)
                    self.tree.setCurrentItem(it)
                    self.tree.blockSignals(False)
                    return

    def selected_player(self) -> Optional[int]:
        return _Tree.player_of(self.tree.currentItem())

    def current(self) -> Optional[str]:
        kind, value = (self.tree.currentItem().data(0, Qt.UserRole) or (None, None)) if self.tree.currentItem() else (None, None)
        return value if kind == "char" else None

    def chosen(self) -> List[str]:
        names = [it.data(0, Qt.UserRole)[1] for it in self.tree.selectedItems() if (it.data(0, Qt.UserRole) or (None,))[0] == "char"]
        return names or ([self.current()] if self.current() else [])

    def _player_name(self, pid: Optional[int]) -> Optional[str]:
        return rt().players.name_of(pid) if pid else None

    # ------------------------------------------------------------------ clicks
    def _picked(self, it: Optional[QTreeWidgetItem]):
        kind, value = (it.data(0, Qt.UserRole) or (None, None)) if it is not None else (None, None)
        if kind == "char":
            rt().select_character(value)

    def _ticked(self, it: QTreeWidgetItem, col: int):
        """The box before a character's name: playing this session (the team inventory, the World map's eaters and packs,
        the battle's Add players)."""
        kind, value = it.data(0, Qt.UserRole) or (None, None)
        if kind != "char" or col != 0:
            return
        on = it.checkState(0) == Qt.Checked
        if on != (value in rt().players.session_party()):
            guard(rt().characters.set_in_session, value, on)

    def _double(self, it: QTreeWidgetItem, _col: int):
        kind, value = it.data(0, Qt.UserRole) or (None, None)
        if kind == "char":
            A.open_sheet(self, value)

    def _menu(self, pos):
        it = self.tree.itemAt(pos)
        kind, value = (it.data(0, Qt.UserRole) or (None, None)) if it is not None else (None, None)
        menu = QMenu(self)
        names = self.chosen()
        session = set(rt().players.session_party())
        if kind == "char" and len(names) > 1 and value in names:
            on = not all(n in session for n in names)
            menu.addAction(tr("Mark all {0} as active session chars", len(names)) if on else
                           tr("Unmark all {0} as active session chars", len(names)), lambda: self.set_session(names, on))
            menu.addSeparator()
            menu.addAction(tr("Award XP to {0} characters…", len(names)), lambda: A.award_xp(self, names))
            menu.addAction(tr("Short rest for all {0}", len(names)), lambda: party_rest(self, names, "short_rest"))
            menu.addAction(tr("Long rest for all {0}…", len(names)), lambda: party_rest(self, names, "long_rest"))
        elif kind == "char":
            act = menu.addAction(tr("Active session char"), lambda: self.set_session([value], value not in session))
            act.setCheckable(True)
            act.setChecked(value in session)
            act.setToolTip(tr("Playing this session: the battle's Add players window adds them in one click"))
            menu.addSeparator()
            A.character_menu(self, value, menu)
            owner = _Tree.player_of(it)
            if owner and owner != UNASSIGNED:
                menu.addSeparator()
                menu.addAction(tr("Unassign"), lambda: A.set_owner(value, None))
                if not is_manual(owner):
                    menu.addAction(tr("Make it {0}'s active character (Discord commands)", self._player_name(owner) or owner),
                                   lambda: guard(rt().characters.use, owner, value))
        elif kind == "player":
            mine = rt().players.characters_of(value) if value != UNASSIGNED else table.players()["unassigned"]
            if mine:
                on = not all(n in session for n in mine)
                menu.addAction(tr("Mark all their characters as active session chars") if on else
                               tr("Unmark all their characters as active session chars"), lambda: self.set_session(mine, on))
                menu.addSeparator()
            menu.addAction(tr("New character…"), lambda: self.new_character(value))
            menu.addAction(tr("Quick adventurer…"), lambda: self.quick_character(value))
            if value != UNASSIGNED:
                menu.addAction(tr("Give a character…"), lambda: self.give(value))
                menu.addSeparator()
                self._link_actions(menu, value)
                if is_manual(value):
                    menu.addAction(tr("Rename player…"), lambda: self.rename_player(value))
                    menu.addAction(tr("Attach to Discord…"), lambda: self.attach_to_discord(value))
                menu.addAction(tr("Remove player…"), lambda: self.remove_player(value))
        else:
            menu.addAction(tr("New character…"), lambda: A.new_character(self))
            menu.addAction(tr("Quick adventurer…"), lambda: A.quick_character(self))
            menu.addAction(tr("Import HTML sheets…"), lambda: A.import_dialog(self))
            menu.addAction(tr("Add player…"), self.add_player)
        if session:
            menu.addSeparator()
            menu.addAction(tr("Clear this session's characters ({0})", len(session)), lambda: self.set_session(sorted(session), False))
        menu.exec(self.tree.viewport().mapToGlobal(pos))

    # ------------------------------------------------------------------ actions
    def set_session(self, names: List[str], on: bool):
        for n in names:
            guard(rt().characters.set_in_session, n, on)

    def _give(self, names: List[str], pid: int):
        for n in names:
            A.set_owner(n, None if pid == UNASSIGNED else pid)

    def new_character(self, pid: Optional[int] = None):
        pid = self.selected_player() if pid is None else pid
        pid = None if pid == UNASSIGNED else pid
        A.new_character(self, pid or None, self._player_name(pid))

    def quick_character(self, pid: int):
        pid = None if pid == UNASSIGNED else pid
        A.quick_character(self, pid or None, self._player_name(pid))

    def give(self, pid: int):
        """Claim: hand a character (unassigned ones first) to this player."""
        s = table.players()
        free = set(s["unassigned"])
        mine = set(rt().players.characters_of(pid))
        options = [(c["name"] + ("" if c["name"] in free else "  · " + tr("owned")), c["name"])
                   for c in sorted(s["characters"], key=lambda c: (c["name"] not in free, c["name"].lower()))
                   if c["name"] not in mine]
        if not options:
            notify.warn(tr("There is no other character to give."))
            return
        name = dialogs.choose_from(self, tr("Give a character to {0}", self._player_name(pid) or pid), options)
        if name:
            A.set_owner(name, pid)

    def remove_player(self, pid: Optional[int] = None):
        pid = self.selected_player() if pid is None else pid
        if pid is None:
            notify.warn(tr("Select a player first."))
            return
        if pid == UNASSIGNED:
            notify.warn(tr("The Unassigned group can't be removed."))
            return
        who = self._player_name(pid) or str(pid)
        if dialogs.confirm(self, tr("Remove {0}? Their characters become unassigned.", who), tr("Remove player")):
            guard(rt().characters.remove_player, pid)

    def _link_actions(self, menu: QMenu, pid: int):
        """The player's portal link: copy it (how a manual player gets it), or send it on Discord."""
        from ....services.portal.access import access
        from ....services.portal.controller import portal
        url = portal.url
        copy = menu.addAction(tr("Copy portal link"),
                              lambda: (QGuiApplication.clipboard().setText(f"{url.rstrip('/')}/?k={access.key_for(pid)}"),
                                       notify.good(tr("Copied."))))
        copy.setEnabled(bool(url))
        if not url:
            copy.setToolTip(tr("Start sharing first: the links aren't ready yet."))
        if not is_manual(pid):
            send = menu.addAction(tr("Send portal link on Discord"),
                                  lambda: guard(portal.send_links, pid) and notify.good(tr("Link sent.")))
            send.setEnabled(bool(url) and rt().bot_manager.is_ready)
        menu.setToolTipsVisible(True)
        menu.addSeparator()

    def rename_player(self, pid: int):
        new = dialogs.ask_text(self, tr("Rename player"), tr("Name"), self._player_name(pid) or "")
        if new:
            guard(rt().characters.rename_player, pid, new)

    def attach_to_discord(self, pid: int):
        """A player added by hand joins Discord: their characters (and portal link) move to their Discord account."""
        got = AddPlayerDialog.ask(self, discord_only=True, title_text=tr("Attach {0} to Discord", self._player_name(pid) or pid))
        if not got:
            return
        _kind, uid, name, _char = got
        new = guard(rt().characters.attach_to_discord, pid, uid, name)
        if new is not None:
            self.closed.discard(new)
            notify.good(tr("{0} is now attached to Discord.", rt().players.name_of(new) or new))

    def add_player(self):
        got = AddPlayerDialog.ask(self)
        if not got:
            return
        kind, uid, name, char = got
        pid = guard(rt().characters.add_manual_player, name) if kind == MANUAL else guard(rt().characters.add_player, uid, name)
        if pid is None:
            return
        self.closed.discard(pid)
        if char:
            A.set_owner(char, pid)
        else:
            notify.good(tr("Added player {0}", name or uid))

    def save_state(self) -> dict:
        return {"closed": sorted(self.closed), "query": self.query.text()}

    def restore_state(self, state: dict):
        self.closed = {int(p) for p in state.get("closed", []) if str(p).lstrip("-").isdigit()}
        self.query.setText(state.get("query", ""))
        self.refresh()


DISCORD, MANUAL = "discord", "manual"


class AddPlayerDialog(dialogs.Dialog):
    """How the player is attached - Discord (a server member or a Discord user ID: the bot knows them, sends their
    portal link, takes their slash commands) or Manual (just a name: the DM sends their link) - and, optionally, a
    character to give them. discord_only: attaching a manual player to Discord (no method, no character)."""

    def __init__(self, parent, discord_only: bool = False, title_text: str = ""):
        super().__init__(parent, title_text or tr("Add player"), 440)
        s = table.players()
        self.members = s["members"]
        self.discord_only = discord_only
        if not discord_only:
            self.method = QButtonGroup(self)
            self.by_discord = QRadioButton(tr("Discord"))
            self.by_hand = QRadioButton(tr("Manual"))
            self.method.addButton(self.by_discord)
            self.method.addButton(self.by_hand)
            self.by_discord.setChecked(True)
            self.by_discord.toggled.connect(self._method)
            self.method_hint = label("", role="dim", wrap=True)
            self.body.addWidget(title(tr("Attach by")))
            self.body.addLayout(row(self.by_discord, self.by_hand, stretch()))
            self.body.addWidget(self.method_hint)
        self.discord_box = QWidget()
        form = QFormLayout(self.discord_box)
        form.setContentsMargins(0, 0, 0, 0)
        self.member = Combo()
        self.member.addItem(tr("— pick a server member —") if self.members else tr("(member list unavailable)"), None)
        for m in self.members:
            self.member.addItem(f"{m['name']} ({m['id']})", m["id"])
        self.member.setEnabled(bool(self.members))
        form.addRow(tr("Server member"), self.member)
        self.uid = line_edit(placeholder=tr("or a Discord user ID"))
        self.name = line_edit(placeholder=tr("display name (optional; looked up from Discord)"))
        form.addRow(tr("Discord user ID"), self.uid)
        form.addRow(tr("Display name"), self.name)
        form.addRow(label(tr("Not listed? Enter their Discord user ID (the list can be partial when the Server "
                             "Members Intent is off).") if self.members else
                          tr("The member list isn't available (bot offline, or the Server Members Intent is "
                             "off), so enter the player's Discord ID."), role="dim", wrap=True))
        self.body.addWidget(self.discord_box)
        self.manual_box = QWidget()
        form = QFormLayout(self.manual_box)
        form.setContentsMargins(0, 0, 0, 0)
        self.manual_name = line_edit(placeholder=tr("the player's name"))
        form.addRow(tr("Name"), self.manual_name)
        self.body.addWidget(self.manual_box)
        self.char = Combo()
        if not discord_only:
            self.char.addItem(tr("— none, just add the player —"), "")
            for c in s["characters"]:
                self.char.addItem(c["name"] + ("" if c["owner"] else "  " + tr("(unassigned)")), c["name"])
            if rt().selected_name:
                self.char.setCurrentIndex(max(0, self.char.findData(rt().selected_name)))
            form = QFormLayout()
            form.addRow(tr("Character"), self.char)
            self.body.addLayout(form)
        self.result_value = None
        self.ok_cancel(tr("Attach") if discord_only else tr("Add"), self._ok)
        self._method()

    def manual(self) -> bool:
        return not self.discord_only and self.by_hand.isChecked()

    def _method(self, *_):
        manual = self.manual()
        self.discord_box.setVisible(not manual)
        self.manual_box.setVisible(manual)
        self.show_problem("")
        if not self.discord_only:
            self.method_hint.setText(
                tr("Just a name. Their characters show on the player portal; you copy their link and send it to them "
                   "yourself (no Discord commands).") if manual else
                tr("Attached to their Discord account: the bot can send them their portal link, and they can use the "
                   "slash commands."))
        if manual:
            self.manual_name.setFocus()

    def _ok(self):
        char = self.char.currentData() or None
        if self.manual():
            name = self.manual_name.text().strip()
            if not name:
                self.show_problem(tr("Enter the player's name."))
                return
            self.result_value = (MANUAL, None, name, char)
            self.accept()
            return
        mid = self.member.currentData()
        uid = str(mid) if mid else self.uid.text().strip()
        if not uid.isdigit() or int(uid) <= 0:
            self.show_problem(tr("Enter the player's numeric Discord user ID."))
            return
        name = next((m["name"] for m in self.members if m["id"] == mid), None) if mid else (self.name.text().strip() or None)
        self.result_value = (DISCORD, int(uid), name, char)
        self.accept()

    @classmethod
    def ask(cls, parent, **kw):
        d = cls(parent, **kw)
        return d.result_value if d.exec() else None
