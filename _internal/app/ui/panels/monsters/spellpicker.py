"""The creature generator's spell picker: any spell of the library (no class or level limits), as prepared spells
with slots or as innate spells cast at will or a few times a day. `entry` is the stat block entry after Apply."""
from typing import Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QSplitter, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget

from ....core.i18n import tr
from ....rules import monster_gen as G
from ....rules.describe import spell_detail
from ....services import monster_workshop as W
from ...dialogs import Dialog
from ...errors import guard
from ...theme import COLORS
from ...widgets.common import (check, clear_layout, col, combo, label, line_edit, row, scroll, spin, stretch, title,
                               tool_button, widget)
from ...widgets.text import TextView

LEVEL = lambda lv: tr("Cantrips") if lv == 0 else tr("Level {0}", lv)  # noqa: E731


class SpellPicker(Dialog):
    def __init__(self, parent, setup: dict, spec: dict):
        super().__init__(parent, tr("Choose spells"), 1150, 700)
        self.spec = spec
        self.st = {"mode": setup.get("mode") or "slots", "ability": setup.get("ability") or "int",
                   "level": setup.get("level") or 0, "class_name": setup.get("class_name") or "",
                   "spells": [dict(x) for x in setup.get("spells") or []]}
        self.entry: Optional[dict] = None
        self.levels = W.spell_levels()
        self.open = {self.levels.get(x["name"], 0) for x in self.st["spells"]}
        self.tips: dict = {}

        # settings
        self.mode = combo([(tr("Spell slots (prepared)"), "slots"), (tr("Innate (at will / per day)"), "innate")],
                          self.st["mode"], on_change=self._set_mode)
        self.ability = combo([(tr(G.ABILITY_NAMES[a]), a) for a in W.CASTING], self.st["ability"],
                             on_change=lambda v: self._set("ability", v))
        self.level = spin(self.st["level"], 0, 20, on_change=lambda v: self._set("level", v), width=60)
        self.class_name = line_edit(self.st["class_name"], tr("e.g. wizard"), width=120)
        self.class_name.textEdited.connect(lambda t: self._set("class_name", t))
        self.slot_fields = [widget(col(label(tr("Caster level (0 = auto)"), role="dim"), self.level, spacing=1)),
                            widget(col(label(tr("Spell list name (optional)"), role="dim"), self.class_name, spacing=1))]
        self.body.addLayout(row(col(label(tr("Kind"), role="dim"), self.mode, spacing=1),
                                col(label(tr("Spellcasting ability"), role="dim"), self.ability, spacing=1),
                                *self.slot_fields, stretch(), spacing=10))

        # the library
        self.query = line_edit(placeholder=tr("search spells…"))
        self._debounce = QTimer(self, singleShot=True, interval=150)
        self._debounce.timeout.connect(self.draw_library)
        self.query.textChanged.connect(lambda _t: self._debounce.start())
        self.level_filter = combo([(tr("any level"), None)] + [(LEVEL(lv), lv) for lv in range(10)],
                                  on_change=lambda _v: self.draw_library())
        self.class_filter = combo([(tr("any class"), "")] + [(tr(c), c) for c in W.spell_classes()],
                                  on_change=lambda _v: self.draw_library())
        self.damage = check(tr("deals damage"), False, lambda _on: self.draw_library())
        self.count = label("", role="dim")
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels([tr("Spell"), tr("School · book")])
        self.tree.setColumnWidth(0, 300)
        self.tree.setUniformRowHeights(True)
        self.tree.setMouseTracking(True)
        self.tree.itemClicked.connect(self._clicked)
        self.tree.itemEntered.connect(self._hover)
        self.tree.itemExpanded.connect(lambda it: self._folded(it, True))
        self.tree.itemCollapsed.connect(lambda it: self._folded(it, False))
        left = QWidget()
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.addLayout(row(self.query, self.level_filter, self.class_filter, self.damage, self.count))
        ll.addWidget(label(tr("Every spell in the library - any class, any level. Hover to read, click to add or remove. "
                              "© = concentration."), role="dim", wrap=True))
        ll.addWidget(self.tree, 1)

        # the chosen spells and the text they make
        self.chosen = QVBoxLayout()
        self.chosen.setContentsMargins(0, 0, 4, 0)
        self.chosen.setSpacing(1)
        chosen_host = QWidget()
        chosen_host.setLayout(self.chosen)
        self.preview = TextView()
        self.preview.setMaximumHeight(220)
        self.preview.setMinimumHeight(90)
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(title(tr("Chosen spells")))
        rl.addWidget(scroll(chosen_host), 1)
        rl.addWidget(title(tr("Stat block text")))
        rl.addWidget(self.preview)
        split = QSplitter(Qt.Horizontal)
        split.addWidget(left)
        split.addWidget(right)
        split.setStretchFactor(0, 8)
        split.setStretchFactor(1, 5)
        self.body.addWidget(split, 1)
        self.ok_cancel(tr("Apply"), self.apply)
        self._show_slot_fields()
        self.draw_library()
        self.draw_chosen()
        self.query.setFocus()

    # ------------------------------------------------------------------ settings
    def _set(self, key: str, value):
        self.st[key] = value
        self.refresh()

    def _set_mode(self, mode: str):
        self.st["mode"] = mode
        self._show_slot_fields()
        self.draw_chosen()

    def _show_slot_fields(self):
        for w in self.slot_fields:
            w.setVisible(self.st["mode"] == "slots")

    def has(self, name: str) -> bool:
        return any(x["name"] == name for x in self.st["spells"])

    def toggle(self, name: str):
        if self.has(name):
            self.st["spells"] = [x for x in self.st["spells"] if x["name"] != name]
        else:
            self.st["spells"].append({"name": name, "uses": W.default_uses(self.levels.get(name, 0))})
        self.draw_library()
        self.draw_chosen()

    # ------------------------------------------------------------------ the library
    def draw_library(self):
        needle = self.query.text().strip()
        lv_only = self.level_filter.currentData()
        shown = W.find_spells(needle, lv_only, self.class_filter.currentData() or "", self.damage.isChecked())
        self.count.setText(tr("{0} of {1} spells", len(shown), len(self.levels)))
        t = self.tree
        pos = t.verticalScrollBar().value()
        t.setUpdatesEnabled(False)
        t.blockSignals(True)
        t.clear()
        on_color = QColor(COLORS["accent"])
        for lv in range(10):
            items = [x for x in shown if x["level"] == lv]
            if not items:
                continue
            picked = sum(1 for x in items if self.has(x["name"]))
            head = QTreeWidgetItem([LEVEL(lv) + (f"   ·  {tr('{0} chosen', picked)}" if picked else ""), str(len(items))])
            f = head.font(0)
            f.setBold(True)
            head.setFont(0, f)
            head.setData(0, Qt.UserRole + 1, lv)
            t.addTopLevelItem(head)
            for x in items:
                on = self.has(x["name"])
                it = QTreeWidgetItem([("✓ " if on else "    ") + x["name"] + (" ©" if x["conc"] else ""),
                                      f"{tr(x['school'])[:5]} · {x['source']}"])
                it.setData(0, Qt.UserRole, x["name"])
                if on:
                    it.setForeground(0, on_color)
                head.addChild(it)
            head.setExpanded(lv in self.open or bool(needle) or lv_only is not None)
        if not t.topLevelItemCount():
            t.addTopLevelItem(QTreeWidgetItem([tr("No spell matches.")]))
        t.blockSignals(False)
        t.setUpdatesEnabled(True)
        QTimer.singleShot(0, t, lambda: t.verticalScrollBar().setValue(pos))

    def _folded(self, it: QTreeWidgetItem, opened: bool):
        lv = it.data(0, Qt.UserRole + 1)
        if lv is not None:
            (self.open.add if opened else self.open.discard)(lv)

    def _clicked(self, it: QTreeWidgetItem, _col: int):
        name = it.data(0, Qt.UserRole)
        if name:
            self.toggle(name)
        elif it.data(0, Qt.UserRole + 1) is not None:
            it.setExpanded(not it.isExpanded())

    def _hover(self, it: QTreeWidgetItem, _col: int):
        name = it.data(0, Qt.UserRole)
        if name and not it.toolTip(0):
            if name not in self.tips:
                self.tips[name] = guard(spell_detail, name) or ""
            it.setToolTip(0, f"{name}\n{tr(self.tips[name])}"[:1500])

    # ------------------------------------------------------------------ chosen spells
    def draw_chosen(self):
        clear_layout(self.chosen)
        innate = self.st["mode"] == "innate"
        if innate:
            groups = [(tr(u), [x for x in self.st["spells"] if x["uses"] == u]) for u in G.INNATE_USES]
        else:
            groups = [(LEVEL(lv), [x for x in self.st["spells"] if self.levels.get(x["name"], 0) == lv]) for lv in range(10)]
        any_ = False
        for name, lst in groups:
            if not lst:
                continue
            any_ = True
            self.chosen.addWidget(label(name, role="dim"))
            for x in lst:
                uses = combo([(tr(u), u) for u in G.INNATE_USES], x["uses"],
                             on_change=lambda v, x=x: (x.__setitem__("uses", v), self.draw_chosen())) if innate else None
                self.chosen.addLayout(row(label(x["name"]), stretch(), uses,
                                          tool_button("✕", lambda n=x["name"]: self.toggle(n), tip=tr("Remove"))))
            self.chosen.addSpacing(4)
        if not any_:
            self.chosen.addWidget(label(tr("Click spells on the left to add them."), role="dim"))
        self.chosen.addStretch(1)
        self.refresh()

    def refresh(self):
        entry = guard(G.spellcasting_entry, self.spec, self.st)
        if entry:
            self.entry = entry
            self.preview.set_text(entry["text"])

    def apply(self):
        entry = guard(G.spellcasting_entry, self.spec, self.st)     # the latest choices
        if entry:
            self.entry = entry
            self.accept()
