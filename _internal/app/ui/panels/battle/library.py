"""The Creatures page of the Battle map's drawer: the bestiary search to add creatures to the battle (a button, a
double-click, or a drag onto the map or the initiative order), quick custom enemies, and the monster generator for full
custom creatures."""
from ....core.i18n import tr
from ... import dialogs, notify
from ...errors import guard
from ...panel import Panel
from ...theme import COLORS
from ...widgets.common import button, spin
from ...widgets.icons import icon_button
from ...widgets.search import SearchPanel


class EnemiesPanel(Panel):
    def build(self):
        self.count = spin(1, 1, 40, width=34, tip=tr("How many to add"))
        self.roll_hp = icon_button("roll", None, tr("Roll their hit points (off: the average)"), checked=False, color=COLORS["warn"])
        self.search = SearchPanel(
            "monsters",
            columns=[("name", tr("Name"), 0), ("cr", tr("CR"), 40), ("type", tr("Type"), 80), ("hp", tr("HP"), 38),
                     ("ac", tr("AC"), 32), ("src", tr("Book"), 52)],
            sorts=["cr", "name", "hp", "ac", "type", "book"], default_sort="cr",
            groups={tr("CR"): "cr", tr("Type"): "type", tr("Size"): "size", tr("Book"): "src"}, default_group="cr",
            subgroup="kind", compact=True, hover_detail=True,
            pinned=lambda r: r.get("src") == "Custom", pinned_label="CUSTOMS",
            actions=self._actions, on_double=lambda r: self.add(r["id"]),
            draggable=lambda r: {"kind": "monster", "id": r["id"], "count": self.count.value(), "hp_mode": self.hp_mode()})
        self.layout().addWidget(self.search, 1)

    def _actions(self, bar, selected):
        self.selected = selected
        add = button(tr("＋ Add"), lambda: self.add(selected()["id"]) if selected() else notify.warn(tr("Pick a creature first.")),
                     kind="primary", tip=tr("Add the selected creature (or double-click it, or drag it onto the map)"))
        bar.setSpacing(1)
        for w in (self.count, self.roll_hp, add, 6,
                  icon_button("edit", self.custom, tr("Custom enemy") + "\n" + tr("A quick enemy with just a name, HP and AC (not saved)")),
                  icon_button("sparkles", lambda: self.generator(), tr("Generator") + "\n" +
                              tr("Make a full creature: quick generation from a CR, type and role, or build every stat, trait and "
                                 "action by hand. Saved under CUSTOMS."), color="#c084fc"),
                  icon_button("generator", self.edit, tr("Edit") + "\n" +
                              tr("A CUSTOMS creature: edit it. A book creature: start a custom copy of it."))):
            bar.addSpacing(w) if isinstance(w, int) else bar.addWidget(w)
        bar.addStretch(1)

    def hp_mode(self) -> str:
        return "roll" if self.roll_hp.isChecked() else "average"

    def add(self, monster_id: str):
        if guard(self.rt.battle.add_enemy, monster_id, self.count.value(), None, self.hp_mode(), None, True):
            notify.good(tr("Added to the battle."))

    def custom(self):
        f = dialogs.form(self, tr("Custom enemy"), [
            {"key": "name", "label": tr("Name"), "required": True},
            {"key": "hp", "label": tr("Hit points"), "kind": "int", "value": 10, "min": 1, "max": 9999},
            {"key": "ac", "label": tr("Armor Class"), "kind": "int", "value": 12, "min": 0, "max": 40},
            {"key": "init", "label": tr("Initiative bonus"), "kind": "int", "value": 0, "min": -10, "max": 20},
            {"key": "count", "label": tr("How many"), "kind": "int", "value": 1, "min": 1, "max": 40},
            {"key": "xp", "label": tr("XP each"), "kind": "int", "value": 0, "min": 0, "max": 1000000}], tr("Add"))
        if f and guard(self.rt.battle.add_custom, f["name"], f["hp"], f["ac"], f["init"], f["count"], None, f["xp"], True):
            notify.good(tr("Added to the battle."))

    def generator(self, **kw):
        try:
            from ..monsters.generator import open_monster_generator
        except ImportError as e:
            notify.warn(tr("The monster generator isn't available: {0}", str(e)))
            return
        guard(open_monster_generator, self, on_saved=self._saved, **kw)

    def _saved(self, monster_id, add_to_battle: bool = False):
        guard(self.search.reload)
        if monster_id and add_to_battle:
            self.add(monster_id)

    def edit(self):
        r = self.selected()
        if not r:
            notify.warn(tr("Pick a creature first."))
            return
        self.generator(**({"edit_id": r["id"]} if r.get("src") == "Custom" else {"copy_id": r["id"]}))

    def save_state(self) -> dict:
        return {"count": self.count.value(), "hp_mode": self.hp_mode()}

    def restore_state(self, state: dict):
        self.count.setValue(int(state.get("count") or 1))
        self.roll_hp.setChecked(state.get("hp_mode") == "roll")
