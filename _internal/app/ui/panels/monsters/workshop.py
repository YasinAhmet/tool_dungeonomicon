"""The Creature workshop: the creature generator as a window of its own, for making and editing creatures without
a battle. The list on the left (folded by CR or type, every folder shut until opened; the open ones are remembered)
opens a custom creature (CUSTOMS or a custom rulebook's) to edit, or copies any other."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QSplitter

from ....core import events
from ....core.i18n import tr
from ....services import monster_workshop as W
from ... import dialogs
from ...panel import Panel
from ...widgets.common import button, combo, label, row, set_items, stretch
from ...widgets.search import SearchPanel
from .generator import CreatureEditor


class CreatureWorkshop(Panel):
    def build(self):
        self.target = combo(tip=tr("Where new creatures and copies are saved"))
        self.editor = CreatureEditor(self)
        self.editor.on_saved = lambda _id, _add: self.retitle()
        self.list = SearchPanel(
            "monsters", columns=[("name", tr("Name"), 0), ("cr", tr("CR"), 40)], sorts=["cr", "name"], default_sort="cr",
            groups={tr("CR"): "cr", tr("Type"): "type"}, default_group="cr", subgroup="kind", compact=True,
            show_detail=False, hover_detail=True, remember="creature_workshop", pinned=lambda r: W.is_custom(r["id"]),
            pinned_label="CUSTOMS", actions=self._actions, on_double=self.open_row)
        self.list.setMinimumWidth(300)
        self.list.query.setMinimumWidth(110)
        split = QSplitter(Qt.Horizontal)
        split.addWidget(self.list)
        split.addWidget(self.editor)
        split.setStretchFactor(1, 1)
        split.setSizes([340, 1060])
        self.layout().addLayout(row(button("＋ " + tr("New creature"), self.new, kind="primary"),
                                    label(tr("New creatures and copies go to")), self.target, stretch()))
        self.layout().addWidget(split, 1)
        self.on(events.RULES, self.refresh)

    def _actions(self, bar, selected):
        bar.addWidget(button(tr("Edit"), lambda: self.open_row(selected()), tip=tr("Edit a custom creature; any other is copied")))
        bar.addWidget(button(tr("Copy"), lambda: self.copy(selected()), tip=tr("Start a new creature from this one")))
        bar.addStretch(1)

    def refresh(self):
        set_items(self.target, [(tr("CUSTOMS"), "")] + W.books(), self.target.currentData())

    def title_suffix(self) -> str:
        return self.editor.spec["name"] if self.editor.original else ""

    # ------------------------------------------------------------------ opening
    def _leave(self) -> bool:
        return not self.editor.dirty or dialogs.confirm(
            self, tr("Discard the changes to {0}?", self.editor.spec["name"] or tr("this creature")), yes=tr("Discard"))

    def _load(self, **kw) -> bool:
        if not self._leave():
            return False
        ok = self.editor.load(**kw)
        self.retitle()
        return ok

    def new(self):
        self._load(book=self.target.currentData() or None)

    def open_row(self, r):
        if not r:
            return
        if W.is_custom(r["id"]):
            self._load(edit_id=r["id"])
        else:
            self.copy(r)

    def copy(self, r):
        if r:
            self._load(copy_id=r["id"], book=self.target.currentData() or None)

    # ------------------------------------------------------------------ layouts
    def save_state(self) -> dict:
        return {"edit": self.editor.original or "", "target": self.target.currentData() or ""}

    def restore_state(self, state: dict):
        i = self.target.findData(state.get("target") or "")
        if i >= 0:
            self.target.setCurrentIndex(i)
        if state.get("edit") and W.is_custom(state["edit"]):
            self.editor.load(edit_id=state["edit"])
            self.retitle()
