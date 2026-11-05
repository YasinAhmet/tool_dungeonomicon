"""The Inspector: whatever was picked last, anywhere - a rules entry (a monster, item, spell, race... selected in any
window), a character (selected in the Party, or looked up: its full sheet, every roll one click), or what's selected on
the Battle map (a creature's card, a prop's or picture's controls...). Back / forward walk what it showed; the look-up
line finds any entry or character by name as you type; the lock keeps it on what it shows while you pick other things."""
from typing import Optional

from PySide6.QtWidgets import QStackedWidget, QVBoxLayout, QWidget

from ....core import events
from ....core.i18n import tr
from ....rules.describe import describe
from ....services import library
from ...errors import guard
from ...panel import Panel
from ...registry import panel
from ...selection import hub
from ...widgets.common import button, label, row, scroll, tool_button
from ...widgets.lookup import LookupBox
from ...widgets.text import TextView

ENTRY, SHEET = 0, 1                     # the stack's pages (the Battle map's page is added the first time it's needed)


@panel("app.inspector", "Inspector", "Session", icon="🔍", area="right",
       description="Whatever you pick last: a rules entry selected in any window, a character's full sheet (select one in "
                   "the Party), or what's selected on the Battle map. Type in the look-up line to find any entry or "
                   "character by name.")
class InspectorPanel(Panel):
    fits_itself = True                  # its pages scroll themselves: the look-up line stays in sight

    def build(self):
        self.history, self.pos = [], -1             # ("content", kind, ident) / ("character", name, "")
        self.base = ENTRY                           # what shows when the Battle map's selection goes
        self.seen_name = self.rt.selected_name      # the selected character last time (only a change shows it)
        self.title = ""
        self._library = None
        self.back = button("◀", lambda: self._step(-1), kind="flat", width=26, tip=tr("Back: what was shown before"))
        self.fwd = button("▶", lambda: self._step(1), kind="flat", width=26, tip=tr("Forward"))
        self.query = LookupBox(self._entries, tr("look up a spell, item, creature, character…"))
        self.query.setToolTip(tr("Type part of a name: the matches list below. Up / Down and Enter (or a click) pick one; "
                                 "Enter alone picks the best match."))
        self.query.picked.connect(lambda e: guard(self._looked_up, e))
        self.lock = tool_button("🔓", self._locked, tip=tr("Lock: keep showing this while you select other things"))
        self.lock.setCheckable(True)

        entry = QWidget()
        box = QVBoxLayout(entry)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(4)
        self.where = label("", role="dim")
        self.text = TextView(heading_first_line=True)
        self.text.setPlaceholderText(tr("Select a monster, item, spell, character or any other entry in another window "
                                        "to read it here, or look it up by name above."))
        box.addWidget(self.where)
        box.addWidget(self.text, 1)
        self.sheet = None                           # the character sheet, made the first time a character shows
        self.sheet_page = QWidget()
        QVBoxLayout(self.sheet_page).setContentsMargins(0, 0, 0, 0)
        self.stack = QStackedWidget()
        self.stack.addWidget(entry)
        self.stack.addWidget(scroll(self.sheet_page))
        self.battle = None                          # the Battle map's selection page
        self.layout().addLayout(row(self.back, self.fwd, self.query, self.lock, spacing=2))
        self.layout().addWidget(self.stack, 1)

        hub().content.connect(self._on_content)
        hub().battle_pick.connect(self._on_battle_pick)
        self.on(events.SELECTION, self._on_selection)
        self.on(events.RULES, self._rules_changed)
        self.on(events.CHARACTERS, self.query.forget)
        if hub().last_content:
            self.show_entry(*hub().last_content)
        elif self.seen_name:
            self.show_character(self.seen_name)
        if hub().last_battle_pick:
            self.show_battle_pick(*hub().last_battle_pick)

    # ------------------------------------------------------------------ what comes in
    def _on_content(self, kind: str, ident: str):
        if not self.lock.isChecked():
            self.show_entry(kind, ident)
            self._untuck()

    def _on_selection(self):
        name = self.rt.selected_name
        if name == self.seen_name:
            return
        self.seen_name = name
        if name and not self.lock.isChecked():
            self.show_character(name)
            self._untuck()

    def _on_battle_pick(self, canvas, sel):
        if not self.lock.isChecked() or not sel:
            self.show_battle_pick(canvas, sel)
            if sel:
                self._untuck()

    def _locked(self):
        self.lock.setText("🔒" if self.lock.isChecked() else "🔓")

    # ------------------------------------------------------------------ showing
    def show_entry(self, kind: str, ident: str, remember: bool = True):
        d = self.run(describe, kind, ident)
        if not d:
            return
        self._remember(("content", kind, ident), remember)
        self.text.set_text(tr(d["title"]) + "\n" + tr(d["text"]))
        self.where.setText(tr("{0} · {1}", tr(kind.replace("_", " ").title()), d["book"]) + (" · " + tr("homebrew") if d["homebrew"] else ""))
        self._settle(ENTRY, tr(d["title"]))

    def show_character(self, name: str, remember: bool = True):
        """A character's full sheet (it follows the character's changes by itself)."""
        if self.sheet is None:
            from ..characters.sheet import CharacterSheet
            self.sheet = guard(CharacterSheet, None, self.sheet_page)
            if self.sheet is None:
                return
            self.sheet_page.layout().addWidget(self.sheet, 1)
        self._remember(("character", name, ""), remember)
        if self.sheet.name != name:
            self.sheet.set_character(name)
        self._settle(SHEET, name)

    def show_battle_pick(self, canvas, sel):
        if not sel:
            if self.battle is not None:
                self.battle.show_selection(None, None)
                if self.stack.currentWidget() is self.battle_page:
                    self.stack.setCurrentIndex(self.base)
                    if 0 <= self.pos < len(self.history):          # (its title back too)
                        self._show(self.history[self.pos], remember=False)
                    if canvas is not None and not self.lock.isChecked():    # deselected on the map: out of the way
                        self._tuck()
            return
        if self.battle is None:
            from ..battle.inspector import MapInspector
            self.battle = guard(MapInspector, None, "battle")
            if self.battle is None:
                return
            self.battle_page = scroll(self.battle)
            self.stack.addWidget(self.battle_page)
        self.battle.show_selection(canvas, sel)
        self.stack.setCurrentWidget(self.battle_page)
        if self.title:                                      # (the map's selection names itself)
            self.title = ""
            self.retitle()

    def _dock(self):
        from ..characters.char_actions import host_of
        host = host_of(self)
        return host, (host.docks.get(self.instance) if host is not None else None)

    def _tuck(self):
        """Nothing selected: the window hides, its room going to the map; the next pick brings it back where it was."""
        host, dock = self._dock()
        if dock is not None and dock.panel is self:
            host.tuck(dock)

    def _untuck(self):
        host, dock = self._dock()
        if dock is not None and dock.panel is self and dock.tucked:
            host.raise_dock(dock)

    def _settle(self, page: int, title: str):
        self.base = page
        self.stack.setCurrentIndex(page)
        if title != self.title:
            self.title = title
            self.retitle()
        self._buttons()

    def _remember(self, item: tuple, remember: bool):
        if not remember:
            return
        if 0 <= self.pos < len(self.history) and self.history[self.pos] == item:
            return
        self.history = self.history[: self.pos + 1] + [item]
        self.history = self.history[-100:]
        self.pos = len(self.history) - 1

    def _show(self, item: tuple, remember: bool = True):
        what, a, b = item
        if what == "character":
            if a in (self.run(self.rt.characters.names) or []):
                self.show_character(a, remember)
        else:
            self.show_entry(a, b, remember)

    def _step(self, delta: int):
        p = self.pos + delta
        if 0 <= p < len(self.history):
            self.pos = p
            self._show(self.history[p], remember=False)

    def _buttons(self):
        self.back.setEnabled(self.pos > 0)
        self.fwd.setEnabled(self.pos < len(self.history) - 1)

    # ------------------------------------------------------------------ the look-up line
    def _entries(self):
        if self._library is None:
            self._library = [{"name": e["name"], "kind": e["what"], "meta": e["meta"], "key": ("content", e["kind"], e["id"])}
                             for e in (self.run(library.lookup_entries) or [])]
        people = [{"name": n, "kind": "Character", "key": ("character", n, "")} for n in (self.run(self.rt.characters.names) or [])]
        return people + self._library

    def _rules_changed(self):
        self._library = None
        self.query.forget()

    def _looked_up(self, e: dict):
        self._show(e["key"])
        self.query.clearFocus()

    # ------------------------------------------------------------------ the window
    def title_suffix(self) -> str:
        return self.title

    def save_state(self) -> dict:
        here = self.history[self.pos] if 0 <= self.pos < len(self.history) else None
        return {"shown": list(here) if here else None, "locked": self.lock.isChecked()}

    def restore_state(self, state: dict):
        shown = state.get("shown")
        if isinstance(shown, list) and len(shown) == 3:
            self._show(tuple(shown))
        elif state.get("entry"):                            # (a layout saved before characters showed here)
            self.show_entry(*state["entry"])
        self.lock.setChecked(bool(state.get("locked")))
        self._locked()
        if hub().last_battle_pick:                          # a restored layout: the map's selection still shows
            self.show_battle_pick(*hub().last_battle_pick)

    def refresh(self):
        self._buttons()


def inspect_character(widget, name: str) -> Optional[InspectorPanel]:
    """Bring the Inspector forward showing a character's full sheet (opened when it isn't open)."""
    from ..characters.char_actions import host_of
    host = host_of(widget)
    dock = host.open("app.inspector") if host is not None else None
    if dock is None:
        return None
    dock.panel.show_character(name)
    return dock.panel
