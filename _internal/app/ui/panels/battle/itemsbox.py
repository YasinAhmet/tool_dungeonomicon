"""The Items page of the Battle map's drawer: the item search over the enabled books (and your own items). Drag one onto
a tile of the Battle map to lay it on the ground (onto a creature: it is handed to it); the amount box sets how many."""
from ....core.i18n import tr
from ...panel import Panel
from ...widgets.common import label, spin
from ...widgets.search import SearchPanel


class ItemsDrawerPanel(Panel):
    def build(self):
        self.qty = spin(1, 1, 999, width=44, tip=tr("How many to drop"))
        self.search = SearchPanel(
            "items",
            columns=[("name", tr("Name"), 0), ("type", tr("Type"), 90), ("rarity", tr("Rarity"), 70)],
            sorts=["name", "rarity", "cost", "weight", "type", "book"], default_sort="name",
            groups={tr("Category"): "cat", tr("Type"): "type", tr("Rarity"): "rarity", tr("Book"): "src"},
            default_group="cat", compact=True, hover_detail=True, remember="drawer_items", actions=self._actions,
            pinned=lambda r: r["src"] == "Custom", pinned_label="CUSTOMS",
            draggable=lambda r: {"kind": "item", "id": r["id"], "name": r["name"], "qty": self.qty.value()})
        self.layout().addWidget(self.search, 1)

    def _actions(self, bar, _selected):
        bar.addWidget(label("×", role="dim", tip=tr("How many to drop")))
        bar.addWidget(self.qty)
        bar.addWidget(label("ⓘ", role="dim", tip=tr("Drag onto the map: it lies on the ground") + "\n"   # (the how-to on hover)
                            + tr("Onto a creature: it is handed to it")))
        bar.addStretch(1)

    def save_state(self) -> dict:
        return {"qty": self.qty.value(), "search": self.search.save_state()}

    def restore_state(self, state: dict):
        self.qty.setValue(int(state.get("qty") or 1))
        if isinstance(state.get("search"), dict):
            self.search.restore_state(state["search"])
