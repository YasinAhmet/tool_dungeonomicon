"""The Monsters and Items pages of the Library window: the faceted searches over the enabled books (and the custom creatures), with
grouping folders; hovering an entry shows its text, and the selected one shows in the Inspector."""
from ....core import events
from ....core.i18n import tr
from ....rules.describe import describe
from ....services import library
from ... import dialogs, notify
from ...panel import Panel
from ...widgets.common import button, spin
from ...widgets.search import SearchPanel


def open_generator(parent, **kw) -> bool:
    """The creature generator (another window's feature); a warning when it isn't there."""
    try:
        from ..monsters.generator import open_monster_generator
    except ImportError:
        notify.warn(tr("The creature generator isn't available."))
        return False
    open_monster_generator(parent, **kw)
    return True


class _SearchWindow(Panel):
    search: SearchPanel

    def save_state(self) -> dict:
        return self.search.save_state()

    def restore_state(self, state: dict):
        self.search.restore_state(state)


class MonstersPanel(_SearchWindow):
    def build(self):
        self.count = spin(1, 1, 40, width=38, tip=tr("How many to add"))
        self.search = SearchPanel(
            "monsters",
            columns=[("name", tr("Name"), 0), ("cr", tr("CR"), 46), ("type", tr("Type"), 120), ("size", tr("Size"), 70),
                     ("hp", tr("HP"), 46), ("ac", tr("AC"), 40), ("src", tr("Book"), 64)],
            sorts=["cr", "name", "hp", "ac", "type", "book"], default_sort="cr",
            groups={tr("CR"): "cr", tr("Type"): "type", tr("Size"): "size", tr("Book"): "src"}, default_group="cr",
            subgroup="kind", pinned=lambda r: r["src"] == library.CUSTOM_BOOK, pinned_label="CUSTOMS",
            actions=self._actions, on_double=lambda r: self._add(r), show_detail=False, hover_detail=True,
            draggable=lambda r: {"kind": "monster", "id": r["id"]})
        self.layout().addWidget(self.search, 1)

    def _actions(self, bar, selected):
        bar.addWidget(self.count)
        bar.addWidget(button(tr("Add to battle"), lambda: self._add(selected()), kind="primary",
                             tip=tr("Add the selected creature to the battle (double-click does the same)")))
        bar.addStretch(1)
        bar.addWidget(button(tr("✨ New creature…"), lambda: open_generator(self, on_saved=self._saved),
                             tip=tr("Make a creature in the generator; it is saved under CUSTOMS.")))
        bar.addWidget(button(tr("Edit…"), lambda: self._edit(selected()),
                             tip=tr("A custom creature: edit it. A book creature: start a custom copy of it.")))
        bar.addWidget(button(tr("Delete"), lambda: self._delete(selected()), kind="danger",
                             tip=tr("Delete the selected custom creature")))

    def _add(self, r):
        if not r:
            return notify.warn(tr("Pick a creature first."))
        if self.run(self.rt.battle.add_enemy, r["id"], self.count.value(), None, "average", None, True) is not None:
            notify.good(tr("Added {0}× {1}", self.count.value(), tr(r["name"])))

    def _edit(self, r):
        if not r:
            return notify.warn(tr("Pick a creature first."))
        d = self.run(describe, "monsters", r["id"])
        if not d:
            return
        if r["src"] == library.CUSTOM_BOOK:
            open_generator(self, edit_id=r["id"], on_saved=self._saved)
        elif d["homebrew"]:
            open_generator(self, edit_id=r["id"], book=d["src"], on_saved=self._saved)
        else:
            open_generator(self, copy_id=r["id"], on_saved=self._saved)

    def _delete(self, r):
        if not r:
            return notify.warn(tr("Pick a creature first."))
        d = self.run(describe, "monsters", r["id"])
        if not d:
            return
        if r["src"] != library.CUSTOM_BOOK and not d["homebrew"]:
            return notify.warn(tr("Only your own creatures can be deleted."))
        if dialogs.confirm(self, tr("Delete {0}?", tr(r["name"])), yes=tr("Delete")):
            self.run(library.delete_creature, r["id"])

    def _saved(self, ident=None, add=False):
        self.search.reload()
        if ident and add:
            self.run(self.rt.battle.add_enemy, ident, 1, None, "average", None, True)


class ItemsPanel(_SearchWindow):
    def build(self):
        self.qty = spin(1, 1, 999, width=40, tip=tr("How many to give"))
        self.give = button("", lambda: self._give(self.search.selected()), kind="primary")
        self.search = SearchPanel(
            "items",
            columns=[("name", tr("Name"), 0), ("type", tr("Type"), 130), ("rarity", tr("Rarity"), 90),
                     ("cost", tr("Cost"), 80), ("wt", tr("Wt"), 46), ("src", tr("Book"), 64)],
            sorts=["name", "rarity", "cost", "weight", "type", "book"], default_sort="name",
            groups={tr("Category"): "cat", tr("Type"): "type", tr("Rarity"): "rarity", tr("Book"): "src"},
            default_group="none", actions=self._actions, show_detail=False, hover_detail=True,
            draggable=lambda r: {"kind": "item", "id": r["id"], "name": r["name"]})
        self.layout().addWidget(self.search, 1)
        self.on(events.SELECTION, self.refresh)
        self.on(events.CHARACTERS, self.refresh)

    def _actions(self, bar, _selected):
        bar.addWidget(self.qty)
        bar.addWidget(self.give)
        bar.addStretch(1)

    def refresh(self):
        who = self.rt.selected_name
        self.give.setText(tr("Give to {0}", who) if who else tr("Give to…"))
        self.give.setEnabled(bool(who))
        self.give.setToolTip(tr("Add the selected item to the selected character's inventory") if who
                             else tr("Select a character first"))

    def _give(self, r):
        who = self.rt.selected_name
        if not r:
            return notify.warn(tr("Pick an item first."))
        if who and self.run(self.rt.characters.add_item, who, r["name"], self.qty.value()) is not None:
            notify.good(tr("Added {0}× {1}", self.qty.value(), tr(r["name"])))
