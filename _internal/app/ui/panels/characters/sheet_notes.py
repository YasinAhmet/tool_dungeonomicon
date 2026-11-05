"""The sheet's Notes: free notes (add, edit in place, remove) and the character's details - alignment, looks,
personality, ideals, bonds, flaws and backstory. Unsaved detail edits survive refreshes until saved or discarded."""
from typing import Dict, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QPlainTextEdit, QVBoxLayout, QWidget

from ....core.i18n import tr
from ....rules import engine as E
from ... import dialogs, notify
from ...widgets.common import button, card, clear_layout, col, combo, label, line_edit, row, scroll, stretch, title, widget

TEXTS = (("personality", "Personality traits"), ("ideal", "Ideals"), ("bond", "Bonds"), ("flaw", "Flaws"),
         ("appearance", "Appearance"), ("backstory", "Backstory"))
FIELDS = (("gender", "Gender"), ("age", "Age"), ("height", "Height"), ("weight", "Weight"), ("eyes", "Eyes"),
          ("hair", "Hair"), ("skin", "Skin"), ("deity", "Deity"))


class _Growing(QPlainTextEdit):
    """A text box one line high while empty, taller as its text grows (up to `most` px, then it scrolls)."""

    def __init__(self, most: int):
        super().__init__()
        self.most = most
        self.textChanged.connect(self._fit)
        self._fit()

    def _fit(self):
        lines = max(1, int(self.document().documentLayout().documentSize().height()))
        h = lines * self.fontMetrics().lineSpacing() + int(2 * self.document().documentMargin()) + 2 * self.frameWidth() + 2
        if h != self.height():
            self.setFixedHeight(min(self.most, max(28, h)))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if e.oldSize().width() != e.size().width():          # a new width wraps the lines anew
            self._fit()


class NotesTab(QWidget):
    def __init__(self, sheet, parent=None, scrolling: bool = True):
        super().__init__(parent)
        self.sheet = sheet
        self.name: Optional[str] = None
        self.dirty = False
        self._notes = None
        self._filling = False
        self._data: Optional[dict] = None
        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        content = col(spacing=5, margins=4)
        content.setAlignment(Qt.AlignTop)
        outer.addWidget(scroll(widget(content)) if scrolling else widget(content))   # the one-page sheet scrolls it

        self.note_rows = col(spacing=2)
        content.addWidget(card(row(title(tr("Notes")), stretch(), button(tr("+ Note"), self.add_note, kind="primary")),
                               self.note_rows, spacing=3))

        self.align = combo([("—", "")] + [(tr(a), a) for a in E.ALIGNMENTS], on_change=lambda _v: self._edited())
        self.inputs: Dict[str, object] = {}
        grid = QGridLayout()
        grid.setSpacing(4)
        grid.addWidget(label(tr("Alignment"), role="dim"), 0, 0)
        grid.addWidget(self.align, 0, 1)
        for i, (key, text) in enumerate(FIELDS, start=1):
            e = line_edit()
            e.textEdited.connect(lambda _t: self._edited())
            self.inputs[key] = e
            r, c = divmod(i, 3)
            grid.addWidget(label(tr(text), role="dim"), r, c * 2)
            grid.addWidget(e, r, c * 2 + 1)
        for c in (1, 3, 5):
            grid.setColumnStretch(c, 1)
        boxes = []
        for key, text in TEXTS:
            t = _Growing(240 if key == "backstory" else 110)
            t.textChanged.connect(self._edited)
            self.inputs[key] = t
            boxes += [label(tr(text), role="dim"), t]
        self.unsaved = label(tr("Unsaved changes"), role="warn")
        self.unsaved.hide()
        content.addWidget(card(title(tr("Character details")), grid, *boxes,
                               row(self.unsaved, stretch(), button(tr("Discard"), self.discard, kind="flat"),
                                   button(tr("Save details"), self.save, kind="primary")), spacing=3))

    # ------------------------------------------------------------------ data
    def set_data(self, d: dict):
        if d["name"] != self.name:
            self.dirty = False
        self.name = d["name"]
        self._data = d
        if d["notes"] != self._notes:
            self._notes = [dict(n) for n in d["notes"]]
            self._draw_notes()
        if not self.dirty:
            self._fill(d)

    def _fill(self, d: dict):
        self._filling = True
        i = self.align.findData(d["alignment"] or "")
        self.align.setCurrentIndex(max(0, i))
        for key, w in self.inputs.items():
            value = d["details"].get(key) or ""
            if isinstance(w, QPlainTextEdit):
                if w.toPlainText() != value:
                    w.setPlainText(value)
            elif w.text() != value:
                w.setText(value)
        self._filling = False
        self._set_dirty(False)

    def _edited(self):
        if not self._filling:
            self._set_dirty(True)

    def _set_dirty(self, on: bool):
        self.dirty = on
        self.unsaved.setVisible(on)

    def values(self) -> dict:
        out = {"alignment": self.align.currentData() or ""}
        for key, w in self.inputs.items():
            out[key] = (w.toPlainText() if isinstance(w, QPlainTextEdit) else w.text()).strip()
        return out

    def save(self):
        if self.sheet.call("update_details", **self.values()) is not None:
            self._set_dirty(False)
            notify.good(tr("Details saved."))

    def discard(self):
        if self._data:
            self._fill(self._data)

    # ------------------------------------------------------------------ notes
    def _draw_notes(self):
        clear_layout(self.note_rows)
        if not self._notes:
            self.note_rows.addWidget(label(tr("No notes yet."), role="dim"))
        for n in self._notes:
            e = line_edit(n["text"])
            e.editingFinished.connect(lambda nid=n["id"], e=e, old=n["text"]: self._edit_note(nid, e.text().strip(), old))
            self.note_rows.addLayout(row(label(f"#{n['id']}", role="dim"), e,
                                         button("✕", lambda nid=n["id"]: self.remove_note(nid), kind="danger",
                                                tip=tr("Delete note"), width=26)))

    def add_note(self):
        text = dialogs.ask_text(self, tr("New note"), tr("Note text"), multiline=True)
        if text:
            self.sheet.call("add_note", text)

    def _edit_note(self, note_id: int, text: str, old: str):
        if text and text != old:
            self.sheet.call("edit_note", note_id, text)

    def remove_note(self, note_id: int):
        if dialogs.confirm(self, tr("Delete note #{0}?", note_id), tr("Delete note")):
            self.sheet.call("remove_note", note_id)
