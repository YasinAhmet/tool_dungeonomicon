"""The Item workshop: making and editing items the way the Creature workshop makes creatures. The list on the left
(folded by category, type or rarity, every folder shut until opened; the open ones are remembered) opens one of your
items (CUSTOMS or a custom rulebook's) to edit, or copies any other; the form is in the middle, the item's card beside
it."""
from typing import Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QSplitter, QVBoxLayout, QWidget

from ....core import events
from ....core.i18n import tr
from ....services import library
from ....services import monster_workshop as W
from ... import dialogs, notify
from ...errors import guard, user_errors
from ...panel import Panel
from ...widgets.common import FlipSplitter, button, combo, label, row, scroll, set_items, stretch, title
from ...widgets.search import SearchPanel
from ...widgets.text import TextView
from .contentform import FormBody


class ItemWorkshop(Panel):
    def build(self):
        self.original: Optional[str] = None        # the name of the item being edited (None: a new one)
        self.book: Optional[str] = None            # the rulebook it is saved into (None: CUSTOMS)
        self.loaded: dict = {}
        self.body: Optional[FormBody] = None
        self.target = combo(tip=tr("Where new items and copies are saved"))
        self.list = SearchPanel(
            "items", columns=[("name", tr("Name"), 0), ("rarity", tr("Rarity"), 70)], sorts=["name", "rarity", "type"],
            default_sort="name", groups={tr("Category"): "cat", tr("Type"): "type", tr("Rarity"): "rarity"},
            default_group="cat", compact=True, show_detail=False, hover_detail=True, remember="item_workshop",
            pinned=lambda r: library.item_is_custom(r["id"]), pinned_label="CUSTOMS", actions=self._actions,
            on_double=self.open_row)
        self.list.setMinimumWidth(300)
        self.list.query.setMinimumWidth(110)
        self.heading = title("")
        self.form_box = QVBoxLayout()
        self.form_box.setContentsMargins(0, 0, 0, 0)
        host = QWidget()
        host.setLayout(self.form_box)
        self.scroller = scroll(host)
        self.scroller.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.preview = TextView(heading_first_line=True)
        self.problem = label("", role="bad", wrap=True)
        self.delete_btn = button(tr("Delete"), self.delete, kind="danger")
        self.save_btn = button(tr("Save"), self.save, kind="primary")
        editor = FlipSplitter(Qt.Horizontal)                 # the preview goes under the form when narrow
        editor.addWidget(self.scroller)
        editor.addWidget(self.preview)
        editor.setStretchFactor(0, 3)
        editor.setStretchFactor(1, 2)
        editor.setChildrenCollapsible(False)
        editor.setSizes([3000, 2000])
        self.scroller.setMinimumWidth(420)
        self.preview.setMinimumWidth(240)
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(self.heading)
        rl.addWidget(editor, 1)
        rl.addLayout(row(self.problem, stretch(), self.delete_btn, self.save_btn))
        split = QSplitter(Qt.Horizontal)
        split.addWidget(self.list)
        split.addWidget(right)
        split.setStretchFactor(1, 1)
        split.setSizes([340, 1060])
        self.layout().addLayout(row(button("＋ " + tr("New item"), self.new, kind="primary"),
                                    label(tr("New items and copies go to")), self.target, stretch()))
        self.layout().addWidget(split, 1)
        self._timer = QTimer(self, singleShot=True, interval=250)
        self._timer.timeout.connect(self._preview)
        self.on(events.RULES, self.refresh)
        self._show(library.blank_form("items"), None, None)

    def _actions(self, bar, selected):
        bar.addWidget(button(tr("Edit"), lambda: self.open_row(selected()), tip=tr("Edit one of your items; any other is copied")))
        bar.addWidget(button(tr("Copy"), lambda: self.copy(selected()), tip=tr("Start a new item from this one")))
        bar.addStretch(1)

    def refresh(self):
        set_items(self.target, [(tr("CUSTOMS"), "")] + W.books(), self.target.currentData())

    def title_suffix(self) -> str:
        return self.original or ""

    @property
    def dirty(self) -> bool:
        return self.body is not None and self.body.values() != self.loaded

    # ------------------------------------------------------------------ the form
    def _show(self, form: dict, original: Optional[str], book: Optional[str]):
        if self.body is not None:
            self.body.setParent(None)
            self.body.deleteLater()
        self.original, self.book = original, book
        self.body = FormBody("items", form)
        self.body.changed.connect(self._timer.start)
        self.form_box.addWidget(self.body)
        self.loaded = self.body.values()
        where = tr(W.book_name(book))
        self.heading.setText((tr("Edit {0}", original) if original else tr("New item")) + f"  ·  {where}")
        self.delete_btn.setVisible(bool(original))
        self.problem.setText("")
        self._preview()
        self.retitle()

    def _preview(self):
        try:
            self.preview.set_text(library.item_preview(self.body.values(), tr(W.book_name(self.book))))
        except user_errors() as e:                  # a half-filled form: say why instead of a toast per key
            self.preview.set_text(tr(str(e)))

    # ------------------------------------------------------------------ opening
    def _leave(self) -> bool:
        return not self.dirty or dialogs.confirm(
            self, tr("Discard the changes to {0}?", self.original or tr("this item")), yes=tr("Discard"))

    def new(self):
        if self._leave():
            self._show(library.blank_form("items"), None, self.target.currentData() or None)

    def open_row(self, r):
        if not r:
            return
        if not library.item_is_custom(r["id"]):
            return self.copy(r)
        form = guard(library.item_form, r["id"])
        if form and self._leave():
            self._show(form, form["name"], library.item_book(r["id"]))

    def copy(self, r):
        form = guard(library.item_form, r["id"]) if r else None
        if form and self._leave():
            form["name"] = form["name"] + " (custom)"
            self._show(form, None, self.target.currentData() or None)

    # ------------------------------------------------------------------ saving
    def save(self):
        form = self.body.values()
        missing = library.missing_field("items", form)
        if missing:
            self.problem.setText(tr("{0} is required.", tr(missing)))
            return
        try:
            r = library.save_item(form, self.original, self.book)
        except user_errors() as e:
            self.problem.setText(tr(str(e)))
            return
        notify.good(tr("{0} saved to {1}.", r["name"], tr(W.book_name(self.book))))
        self._show(form, r["name"], self.book)

    def delete(self):
        if not self.original:
            return
        if not dialogs.confirm(self, tr("Delete {0} from {1}?", self.original, tr(W.book_name(self.book))),
                               tr("Delete item"), tr("Delete")):
            return
        guard(library.delete_item, self.original)
        if library.item_is_custom(self.original):     # still there: the failure was reported
            return
        notify.good(tr("Deleted."))
        self._show(library.blank_form("items"), None, self.target.currentData() or None)

    # ------------------------------------------------------------------ layouts
    def save_state(self) -> dict:
        return {"edit": self.original or "", "target": self.target.currentData() or ""}

    def restore_state(self, state: dict):
        i = self.target.findData(state.get("target") or "")
        if i >= 0:
            self.target.setCurrentIndex(i)
        if state.get("edit") and library.item_is_custom(state["edit"]):
            self.open_row({"id": state["edit"]})
