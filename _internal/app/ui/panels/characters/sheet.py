"""The character sheet: a header (name, HP bar, roll mode, spell slot to cast with, level-up and the character menu)
over one page that scrolls when it needs to - HP, rests, conditions, XP, abilities, skills, attacks, resources,
proficiencies, spells, inventory, features and notes. Every number has its breakdown on hover and every roll is one
click.

    sheet = CharacterSheet("Ilya")                 # follows that character's changes by itself
    sheet = CharacterSheet(compact=True)           # condensed: vitals, abilities, skills, attacks, spells (battle turn card)
    sheet.set_character("Bram")
    sheet.attack_hook = lambda name, weapon, adv: battle_handled   # True: the battle resolved it; False: roll as usual
    sheet.cast_hook = lambda name, spell, slot, ritual, adv: battle_handled
    sheet.hp_hook = lambda name, kind, amount: battle_handled      # kind: 'damage' or 'heal'
    sheet.spell_hovered.connect(lambda spell: ...)  # a spell's name while the mouse is over it, "" when it leaves

The Inspector window shows it for the character picked last (app/ui/panels/workspace/inspector.py).
"""
from typing import Callable, Optional

from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QMenu, QSizePolicy, QVBoxLayout, QWidget

from ....core import events
from ....core.i18n import i18n, tr
from ....core.runtime import rt
from ....rules.character import revision
from ....services.characters import view
from ....services.common import ServiceError, plain_text
from ... import notify
from ...errors import guard
from ...widgets.common import (ElideLabel, button, clear_layout, col, combo, label, row, scroll, set_items, stretch,
                               tool_button, widget)
from ...widgets.icons import AdvSwitch
from ...widgets.text import to_html
from . import char_actions as A
from . import sheet_inventory, sheet_notes, sheet_overview, sheet_spells
from .portrait import edit_portrait, portrait_pixmap
from .sheet_widgets import HpBar, section



class CharacterSheet(QWidget):
    spell_hovered = Signal(str)

    def __init__(self, name: Optional[str] = None, parent=None, compact: bool = False, in_card: bool = False):
        super().__init__(parent)
        self.compact = compact
        self.in_card = in_card                                # inside a battle card: the card has the HP row and bar
        self.name: Optional[str] = None
        self.data: Optional[dict] = None
        self._key = None                                      # what the shown sheet was built from (reload)
        self._stale = False                                   # changed while out of sight: built when shown
        self._kept = {}                                       # part -> (what it shows, its widget): _keep
        self.attack_hook: Optional[Callable[[str, str, Optional[str]], bool]] = None
        self.cast_hook: Optional[Callable[[str, str, object, bool, Optional[str]], bool]] = None
        self.hp_hook: Optional[Callable[[str, str, int], bool]] = None     # (name, 'damage'|'heal', amount) -> handled
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(3)

        self.face = tool_button("", lambda: self.name and edit_portrait(self, self.name),
                                tip=tr("Portrait: the character's token on the battle maps. Click to change it."))
        self.face.setIconSize(QSize(32 if compact else 44, 32 if compact else 44))
        self.title = label("")
        f = self.title.font()
        f.setPointSize(f.pointSize() + (2 if compact else 4))
        f.setBold(True)
        self.title.setFont(f)
        self.meta = label("", role="dim") if compact else ElideLabel(role="dim")    # (full size: one line ending in …)
        self.tools = row(spacing=2)                           # the window puts its pin here
        self.adv = AdvSwitch(tip=tr("How this sheet rolls checks, saves and attacks"))
        self.slot = combo([(tr("auto"), None)], tip=tr("The spell slot clicking a spell casts with (auto: the lowest "
                                                       "that works)"), width=70)
        self.slot_label = label(tr("slot"), role="dim")
        self.level_btn = button(tr("⬆ Level up"), lambda: self.name and A.level_up(self, self.name), kind="primary")
        self.more = tool_button("⋯", tip=tr("Character menu: level up, edit the levels or the creation, undo a level-up, export…"), kind="")
        self.more.setPopupMode(self.more.ToolButtonPopupMode.InstantPopup)
        self.more.setMenu(QMenu(self.more))
        self.more.menu().aboutToShow.connect(self._fill_menu)
        self.meta.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)     # long class lines never widen the window
        if compact and in_card:                              # the card above names the character: one line
            self.face.setIconSize(QSize(24, 24))
            head = row(self.face, self.meta, self.tools, self.adv, self.slot_label, self.slot, self.more)
            self.meta.setWordWrap(True)
            self.title.setParent(self)
            self.title.hide()
        elif compact:
            box.addLayout(row(self.face, self.title, stretch(), self.tools, self.more))
            head = row(self.meta, self.adv, self.slot_label, self.slot)
            self.meta.setWordWrap(True)
        else:
            head = row(self.face, self.title, self.meta, self.tools, self.adv, self.slot_label, self.slot, self.level_btn, self.more)
        head.setStretchFactor(self.meta, 1)
        box.addLayout(head)
        self.hp_bar = HpBar()
        box.addWidget(self.hp_bar)
        self.result = label("", wrap=True, selectable=True)
        self.result.setTextFormat(Qt.RichText)
        self.result.hide()
        box.addWidget(self.result)
        self.empty = label(tr("Select a character to see their sheet."), role="dim", wrap=True)
        self.empty.setAlignment(Qt.AlignTop | Qt.AlignLeft)
        box.addWidget(self.empty, 1)

        self.pages = []                                       # (scroll area, content layout, builder)
        if compact:
            self.body = self._page(self._build_compact)
            box.addWidget(self.body, 1)
        else:
            self.features = sheet_overview.FeaturesTab()
            self.features.setMinimumHeight(340)
            self.notes = sheet_notes.NotesTab(self, scrolling=False)
            self.body = self._page(self._build_full, after=(section(tr("Features & traits"), self.features), self.notes))
            box.addWidget(self.body, 1)

        bus = rt().bus
        unsubs = [bus.subscribe(events.CHARACTERS, lambda: guard(self.reload)),
                  bus.subscribe(events.RULES, lambda: guard(self.reload, True))]
        self.destroyed.connect(lambda *_: [u() for u in unsubs])
        self.set_character(name)

    def _page(self, builder, after=()) -> QWidget:
        """A scrolling page: `builder` fills its top part anew on every change; the `after` widgets stay below it."""
        lay = col(spacing=5)
        outer = col(lay, *after, spacing=5, margins=4)
        outer.setAlignment(Qt.AlignTop)
        area = scroll(widget(outer))
        self.pages.append((area, lay, builder))
        return area

    # ------------------------------------------------------------------ api
    def set_character(self, name: Optional[str]):
        if name != self.name:
            self.result.hide()
        self.name = name or None
        self.data = None
        guard(self.reload, True)

    def showEvent(self, e):
        super().showEvent(e)
        if self._stale:
            QTimer.singleShot(0, self, lambda: guard(self.reload))

    def advantage(self) -> Optional[str]:
        return self.adv.currentData()

    def reload(self, force: bool = False):
        # every character change reaches every sheet (each hit of a battle): building the sheet takes ~0.1 s, so only when
        # this character's file (or owner) changed - and a sheet out of sight waits until it is shown
        key = (self.name, revision(self.name), rt().players.owner_of(self.name)) if self.name else None
        if not force and key is not None and key == self._key and self.data is not None:
            return
        if not force and self.data is not None and not self.isVisible():
            self._stale = True
            return
        self._key, self._stale = key, False
        d = None
        if self.name:
            try:
                d = view.sheet_data(self.name)
            except ServiceError:
                d = None
        if d is None:
            self.data = None
            self.empty.setText(tr("{0} doesn't exist any more.", self.name) if self.name
                               else tr("Select a character to see their sheet."))
            self._show(False)
            return
        if d == self.data and not force:
            return
        self.data = d
        self._render()

    # ------------------------------------------------------------------ actions the sections use
    def call(self, method: str, *args, **kwargs):
        """Run a character service method on the shown character; failures become notifications."""
        if not self.name:
            return None
        return guard(getattr(rt().characters, method), self.name, *args, **kwargs)

    def say(self, text: str, kind: str = "good"):
        """Show a roll or an action's result under the header (and as a notification)."""
        text = tr(text)
        self.result.setText(to_html(text))
        self.result.show()
        getattr(notify, kind if kind in ("good", "warn", "error") else "info")(plain_text(text))

    def roll(self, method: str, what: str):
        r = self.call(method, what, self.advantage())
        if r is not None:
            self.say(r.text)

    def attack(self, weapon: str):
        if self.attack_hook and guard(self.attack_hook, self.name, weapon, self.advantage()):
            return
        r = self.call("attack_roll_and_damage", weapon, self.advantage())
        if r is not None:
            self.say(r.text)

    def cast(self, spell: str, ritual: bool = False):
        slot = self.slot.currentData()
        if self.cast_hook and guard(self.cast_hook, self.name, spell, slot, ritual, self.advantage()):
            return
        r = self.call("cast_spell", spell, slot, ritual)
        if r is not None:
            self.say(r["text"])

    # ------------------------------------------------------------------ drawing
    def _show(self, on: bool):
        self.empty.setVisible(not on)
        self.body.setVisible(on)
        self.hp_bar.setVisible(on and not self.in_card)
        for w in (self.face, self.adv, self.slot, self.slot_label, self.more) + (() if self.compact else (self.level_btn,)):
            w.setVisible(on)                         # (the compact sheet has no Level up button: shown unparented it became a window)
        if not on:
            self.title.setText("")
            self.meta.setText("")
            self.result.hide()

    def _render(self):
        d = self.data
        self._show(True)
        self.title.setText(d["name"])
        size = self.face.iconSize().width()
        self.face.setIcon(QIcon(portrait_pixmap(*d["portrait"], size)))
        meta = [tr(d["line"])] + [tr(x) for x in (d["background"], d["alignment"]) if x]
        self.meta.setText(" · ".join(meta))
        self.meta.setToolTip(self.meta.text())
        v = d["vitals"]
        self.hp_bar.set_hp(v["hp"], v["max_hp"])
        self.hp_bar.setToolTip(tr("HP {0}/{1}", v["hp"], v["max_hp"]))
        slots = [(tr("auto"), None)] + [(str(i + 1), i + 1) for i, n in enumerate(d["slots"]["slots"]) if n]
        if d["slots"]["pact"]:
            slots.append((tr("pact"), "pact"))
        set_items(self.slot, slots, self.slot.currentData())
        has_slots = len(slots) > 1
        self.slot.setVisible(has_slots)
        self.slot_label.setVisible(has_slots)
        self.level_btn.setEnabled(bool(d["can_level"]))
        self.level_btn.setToolTip(tr("Take the next level") if d["can_level"] else
                                  tr("{0} needs {1} XP for the next level (or turn on milestone leveling).",
                                     d["name"], d["next_xp"]))
        for area, lay, builder in self.pages:
            pos = area.verticalScrollBar().value()
            area.setUpdatesEnabled(False)
            for _key, kept in self._kept.values():            # kept when unchanged (_build_full): not deleted with the rest
                lay.removeWidget(kept)
            clear_layout(lay)
            builder(lay, d)
            area.setUpdatesEnabled(True)
            QTimer.singleShot(0, area, lambda a=area, p=pos: a.verticalScrollBar().setValue(p))
        if not self.compact:
            self.features.set_data(d)
            self.notes.set_data(d)

    def _build_full(self, lay, d):
        # a hit in battle changes the hit points, not the skills, spells or pack: those parts (most of the sheet's ~600
        # widgets) are kept while what they show is the same, and only the band at the top is made again
        sheet_overview.build_overview_head(self, d, lay)

        def body(inner):
            inner.addWidget(sheet_overview.overview_body(self, d))
            if d["doc"]["casting"] or d["doc"]["spells"]:
                sheet_spells.build(self, d, inner)
        self._keep(lay, "body", self._rest_key(d), body)
        self._keep(lay, "inventory", repr((d["name"], d["currency"], d["doc"]["weight"], d["inventory"], i18n.language)),
                   lambda inner: sheet_inventory.build(self, d, inner))

    def _keep(self, lay, name: str, key: str, build):
        """Add a part of the sheet to `lay`: the one made last time when `key` (what it shows) is the same, else a new one."""
        hit = self._kept.get(name)
        if hit is None or hit[0] != key:
            if hit is not None:
                hit[1].deleteLater()
            box = QWidget()
            inner = QVBoxLayout(box)
            inner.setContentsMargins(0, 0, 0, 0)
            inner.setSpacing(lay.spacing())
            build(inner)
            hit = self._kept[name] = (key, box)
        lay.addWidget(hit[1])
        hit[1].show()

    def _build_compact(self, lay, d):
        sheet_overview.build_compact_head(self, d, lay)

        def body(inner):
            sheet_overview.compact_body(self, d, inner)
            sheet_spells.build(self, d, inner, compact=True)
        self._keep(lay, "body", self._rest_key(d), body)       # (a battle card: kept through every hit, like the full sheet)

    @staticmethod
    def _rest_key(d: dict) -> str:
        """Everything the sheet shows below its hit points band (what a hit or a heal doesn't change)."""
        doc = {k: v for k, v in d["doc"].items() if k not in ("vitals", "vitals_extra", "weight")}
        rest = {k: v for k, v in d.items() if k not in ("doc", "vitals", "death_saves", "temp_hp", "hp_bonus", "xp", "next_xp",
                                                         "inventory", "currency", "notes", "portrait", "details")}
        return repr((rest, doc, i18n.language))

    def _fill_menu(self):
        menu = self.more.menu()
        menu.clear()
        d = self.data
        if not d:
            return
        name = d["name"]
        if self.compact:
            menu.addAction(tr("Open sheet"), lambda: A.open_sheet(self, name))
            menu.addAction(tr("Level up…"), lambda: A.level_up(self, name)).setEnabled(bool(d["can_level"]))
        menu.addAction(tr("Edit levels…"), lambda: A.edit_levels(self, name)).setEnabled(bool(d["can_edit_levels"]))
        undo = menu.addAction(tr("Undo last level-up ({0})", d["revert_to"]) if d["can_revert"] else tr("Undo last level-up"),
                              lambda: A.revert_level(self, name, d["revert_to"]))
        undo.setEnabled(bool(d["can_revert"]))
        menu.addAction(tr("Reset all levels…"), lambda: A.reset_levels(self, name)).setEnabled(bool(d["can_edit_levels"]))
        menu.addAction(tr("Edit race, ability scores & background…"),
                       lambda: A.edit_creation(self, name)).setEnabled(bool(d["can_edit_origin"]))
        menu.addSeparator()
        A.character_menu(self, name, menu, sheet=False)
