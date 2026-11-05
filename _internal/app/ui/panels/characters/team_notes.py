"""Team notes (a section of the Party window): the entries every player sees on the portal's Team notes tab and can add
to - a header each, its description on hover in the list or below it when the note is selected. One person edits a
note at a time: Edit takes it (players see "The DM is editing"), Save or Cancel lets it go; a note a player is
editing shows who, and can't be edited here until they are done. The DM may delete any note."""
from typing import Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QListWidget, QListWidgetItem, QPlainTextEdit

from ....core import events
from ....core.i18n import tr
from ....core.runtime import rt
from ....services.team_notes import DM, TEXT_MAX, TITLE_MAX
from ... import dialogs
from ...errors import guard, guard_ok
from ...panel import Panel
from ...widgets.common import button, label, line_edit, row, stretch
from .sheet_widgets import rich_tip, section

BY = "The DM"
HOLD_MS = 15000                        # the hold is renewed well inside services.team_notes.HOLD_SECONDS


class TeamNotesPanel(Panel):
    def build(self):
        lay = self.layout()
        self.editing: Optional[int] = None                   # the note held here (renewed by self.beat)
        self.shown: Optional[int] = None                     # the note the detail shows
        # ---- a new note
        self.new_title = line_edit(placeholder=tr("Header"))
        self.new_title.setMaxLength(TITLE_MAX)
        self.new_text = QPlainTextEdit()
        self.new_text.setPlaceholderText(tr("Description (shown on hover)"))
        self.new_text.setFixedHeight(54)
        lay.addWidget(section(tr("New team note"), self.new_title, self.new_text,
                              extra=button(tr("Add note"), self.add, kind="primary")))
        # ---- the notes
        self.list = QListWidget()
        self.list.setWordWrap(True)
        self.list.currentItemChanged.connect(lambda *_: self._show())
        self.list.itemDoubleClicked.connect(lambda *_: self.begin())
        lay.addWidget(label(tr("Team notes"), role="title"))
        lay.addWidget(self.list, 1)
        # ---- the selected note
        self.title_edit = line_edit()
        self.title_edit.setMaxLength(TITLE_MAX)
        self.text_edit = QPlainTextEdit()
        self.text_edit.setMinimumHeight(90)
        self.who = label("", role="dim", wrap=True)
        self.edit_btn = button(tr("Edit"), self.begin, tip=tr("Change the header or add details (no one else can until you save)"))
        self.save_btn = button(tr("Save"), self.save, kind="primary")
        self.cancel_btn = button(tr("Cancel"), self.cancel)
        self.del_btn = button(tr("Delete"), self.remove, kind="danger")
        self.detail = section(tr("Note"), self.title_edit, self.text_edit, self.who,
                              row(self.edit_btn, self.save_btn, self.cancel_btn, stretch(), self.del_btn))
        lay.addWidget(self.detail)
        lay.addWidget(label(tr("Every player sees these notes on the portal and can add to them. One person edits a "
                               "note at a time."), role="dim", wrap=True))
        self.beat = QTimer(self)
        self.beat.setInterval(HOLD_MS)
        self.beat.timeout.connect(self._hold)
        self.lapse = QTimer(self)                            # someone's hold lapses unless renewed: look again then
        self.lapse.setSingleShot(True)
        self.lapse.timeout.connect(lambda: guard(self.refresh))
        self._notes = {}
        self.on(events.NOTES, self.refresh)                  # (a window closed mid-edit: the hold lapses by itself)

    def _let_go(self):
        if self.editing is not None:
            rt().notes.cancel(self.editing, DM)
            self.editing = None
            self.beat.stop()

    # ------------------------------------------------------------------ showing
    def refresh(self):
        notes = rt().notes.all()
        self._notes = {n["id"]: n for n in notes}
        if self.editing is not None and self.editing not in self._notes:
            self.editing = None
            self.beat.stop()
        keep = self.shown
        self.list.blockSignals(True)
        self.list.clear()
        for n in notes:
            other = n["editing"] if n["editing"] and n["editing"]["owner"] != DM else None
            text = n["title"] + (f"   ✎ {tr('{0} is editing', other['who'])}" if other else "")
            it = QListWidgetItem(text)
            it.setData(Qt.UserRole, n["id"])
            it.setToolTip(rich_tip(f"**{n['title']}**\n{n['text']}" if n["text"] else n["title"]))
            self.list.addItem(it)
            if n["id"] == keep:
                self.list.setCurrentItem(it)
        self.list.blockSignals(False)
        if keep not in self._notes:
            self.shown = None
        lefts = [n["editing"]["left"] for n in notes if n["editing"] and n["editing"]["owner"] != DM]
        if lefts:
            self.lapse.start(int((max(0, min(lefts)) + 1) * 1000))
        self._show()

    def _show(self):
        it = self.list.currentItem()
        nid = it.data(Qt.UserRole) if it else None
        if self.editing is not None and nid != self.editing:
            nid = self.editing                               # the note being edited stays in view
            for i in range(self.list.count()):
                if self.list.item(i).data(Qt.UserRole) == nid:
                    self.list.blockSignals(True)
                    self.list.setCurrentRow(i)
                    self.list.blockSignals(False)
        n = self._notes.get(nid)
        self.shown = nid
        self.detail.setVisible(n is not None)
        if n is None:
            return
        mine = self.editing == nid
        if not mine:
            self.title_edit.setText(n["title"])
            self.text_edit.setPlainText(n["text"])
        self.title_edit.setReadOnly(not mine)
        self.text_edit.setReadOnly(not mine)
        other = n["editing"] if n["editing"] and n["editing"]["owner"] != DM else None
        bits = [tr("by {0}", tr(n["by"])) if n["by"] else ""]
        if n["edited_by"]:
            bits.append(tr("edited by {0}", tr(n["edited_by"])))
        if other:
            bits.append("✎ " + tr("{0} is editing this note right now.", other["who"]))
        self.who.setText(" · ".join(b for b in bits if b))
        self.edit_btn.setVisible(not mine)
        self.edit_btn.setEnabled(other is None)
        self.save_btn.setVisible(mine)
        self.cancel_btn.setVisible(mine)
        self.del_btn.setEnabled(other is None)

    # ------------------------------------------------------------------ changing
    def add(self):
        title = self.new_title.text()
        if guard(rt().notes.add, title, self.new_text.toPlainText()[:TEXT_MAX], by=BY) is not None:
            self.new_title.clear()
            self.new_text.clear()

    def begin(self):
        if self.shown is None or self.editing is not None:
            return
        n = guard(rt().notes.begin, self.shown, DM, BY)
        if n is None:
            return
        self.editing = n["id"]
        self.title_edit.setText(n["title"])
        self.text_edit.setPlainText(n["text"])
        self.beat.start()
        self._show()
        self.text_edit.setFocus()

    def _hold(self):
        if self.editing is not None and not rt().notes.hold(self.editing, DM):
            guard(rt().notes.begin, self.editing, DM, BY)    # lapsed: take it back unless someone else has it

    def save(self):
        nid = self.editing
        if nid is None:
            return
        if guard_ok(rt().notes.save, nid, DM, self.title_edit.text(), self.text_edit.toPlainText(), by=BY):
            self.editing = None
            self.beat.stop()
            self.refresh()

    def cancel(self):
        self._let_go()
        self.refresh()

    def remove(self):
        n = self._notes.get(self.shown)
        if n and dialogs.confirm(self, tr("Delete the note \"{0}\" for everyone?", n["title"]), yes=tr("Delete")):
            if self.editing == n["id"]:
                self.editing = None
                self.beat.stop()
            guard(rt().notes.remove, n["id"], DM, by=BY)
