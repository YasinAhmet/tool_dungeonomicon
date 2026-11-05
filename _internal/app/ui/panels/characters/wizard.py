"""New character: a step-by-step wizard (who, race, ability scores, background, class, equipment, details, review).

Changing an earlier step re-evaluates what depends on it (racial bonuses, skill pools, class choices, starting
equipment) and keeps the picks that are still valid. Every step is checked by the rules (creation_flow.validate);
the step list marks what still needs work and the review lists every problem and warning, each one leading back to
its step.

    name = open_creation_wizard(parent, owner_id=None, owner_name=None)     # modal; the new character's name or None
"""
import json
from typing import Dict, List, Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QComboBox, QDialog, QGridLayout, QLabel, QListWidget,
                               QListWidgetItem, QPlainTextEdit, QRadioButton, QSpinBox, QSplitter, QStackedWidget, QVBoxLayout,
                               QWidget)

from ....core import portraits
from ....core.i18n import tr
from ....core.runtime import rt
from ....rules import engine as E
from ....services.characters import creation_flow as CF
from ... import errors, notify
from ...dialogs import Dialog
from ...registry import action
from ...widgets.common import (Combo, button, clear_layout, col, combo, label, line_edit, row, scroll, set_items, spin, stretch,
                               title, widget)
from ...widgets.pickers import FoldSelect
from ...widgets.text import TextView
from .background_builder import open_background_builder
from .choices import ChoicesPanel, FeatPicker, attempt, describe_text, detail_of, picks, radios, section, sync_taken
from .portrait import open_portrait_editor, portrait_pixmap, render

ABILITIES = [(a, E.ABILITY_NAMES[a]) for a in E.ABILITIES]
TRAITS = lambda: [("personality", tr("Personality trait")), ("ideal", tr("Ideal")), ("bond", tr("Bond")), ("flaw", tr("Flaw"))]
LOOKS = lambda: [("age", tr("Age")), ("height", tr("Height")), ("weight", tr("Weight")), ("eyes", tr("Eyes")), ("hair", tr("Hair")),
                 ("skin", tr("Skin")), ("deity", tr("Deity"))]
ICON = {"error": "❌", "warn": "⚠", "info": "ℹ"}


def _key(spec: dict, *keys) -> str:
    return json.dumps({k: spec.get(k) for k in keys}, sort_keys=True, default=str)


def _info_view(height: int = 120) -> TextView:
    t = TextView()
    t.setMaximumHeight(height)
    return t


# ---------------------------------------------------------------------- the steps
class Step(QWidget):
    """One page of the wizard. ensure(spec) redraws it when the earlier steps it depends on changed."""
    key = ""

    def heading(self) -> str:
        return ""

    def __init__(self, wiz: "CreationWizard"):
        super().__init__()
        self.wiz = wiz
        self.box = QVBoxLayout(self)
        self.box.setContentsMargins(4, 2, 8, 2)
        self.box.setSpacing(8)
        self._deps: Optional[str] = None

    def deps(self, spec: dict) -> str:
        return ""

    def ensure(self, spec: dict):
        k = self.deps(spec)
        if k != self._deps:
            self._deps = k
            self.redraw(spec)

    def redraw(self, spec: dict):
        """Rebuild what depends on the earlier steps."""

    def collect(self) -> dict:
        return {}

    def problem(self, spec: dict) -> Optional[str]:
        return None

    def changed(self):
        self.wiz.changed()


class ConceptStep(Step):
    key = "concept"

    def heading(self) -> str:
        return tr("Who")

    def __init__(self, wiz):
        super().__init__(wiz)
        self.name = line_edit(placeholder=tr("Character name"))
        self.name.textChanged.connect(lambda _t: self.changed())
        self.align = combo([(tr("—"), "")] + [(tr(a), a) for a in wiz.lists["alignments"]], on_change=lambda _v: self.changed())
        grid = QGridLayout()
        grid.addWidget(label(tr("Name")), 0, 0)
        grid.addWidget(self.name, 0, 1)
        grid.addWidget(label(tr("Alignment")), 1, 0)
        grid.addWidget(self.align, 1, 1)
        grid.setColumnStretch(1, 1)
        self.box.addLayout(grid)
        if wiz.owner_name:
            self.box.addWidget(label(tr("The character will belong to {0}.", wiz.owner_name), role="dim"))
        self.box.addWidget(label(tr("Work through the steps on the left in any order; each one is checked by the rules. "
                                    "Nothing is saved until you press Create character."), role="dim", wrap=True))
        self.box.addStretch(1)

    def collect(self):
        return {"name": self.name.text().strip(), "alignment": self.align.currentData() or ""}

    def problem(self, spec):
        n = self.name.text().strip()
        if not n:
            return tr("Give the character a name.")
        if n in rt().characters.names():
            return tr("'{0}' already exists.", n)
        return None


class RaceStep(Step):
    key = "race"

    def heading(self) -> str:
        return tr("Race")

    def __init__(self, wiz):
        super().__init__(wiz)
        races = wiz.lists["races"]
        self.race = next((r["name"] for r in races if r["name"] == "Human"), races[0]["name"])
        self.sub, self.anc, self.req = "", "", None
        self.w: Dict[str, object] = {}
        self.race_sel = FoldSelect(CF.book_groups(races), self.race, on_change=self._race, detail=detail_of("races"))
        self.sub_box = combo(on_change=self._sub)
        self.anc_box = combo(on_change=self._anc)
        self.anc_label = label(tr("Ancestry"))
        self.race_sel.setFixedWidth(260)
        self.sub_box.setMinimumWidth(170)
        self.box.addLayout(row(label(tr("Race")), self.race_sel, 12, label(tr("Subrace")), self.sub_box, 12, self.anc_label,
                               self.anc_box, stretch()))
        self.info = _info_view(150)
        self.box.addWidget(self.info)
        self.choices = QVBoxLayout()
        self.choices.setSpacing(8)
        self.box.addLayout(self.choices)
        self.box.addStretch(1)
        self.draw()
        self._deps = ""

    def _race(self, v):
        self.race, self.sub, self.anc = v, "", ""
        self.draw(drop=("ability", "skills", "tools"))
        self.changed()

    def _sub(self, v):
        self.sub = v or ""
        self.draw()
        self.changed()

    def _anc(self, v):
        self.anc = v or ""
        self.draw()
        self.changed()

    def load(self, spec: dict):
        """Show a race chosen earlier with its choices (editing an existing character)."""
        self.race, self.sub, self.anc = spec.get("race") or self.race, spec.get("subrace") or "", spec.get("ancestry") or ""
        self.race_sel.set_value(self.race)
        self.draw(prev=spec.get("race_choices") or {})

    def draw(self, drop=(), prev: Optional[dict] = None):
        if prev is None:
            prev = {k: v for k, v in self.collect_choices().items() if k not in drop}
        ask = lambda: errors.guard(CF.race_step, {"race": self.race, "subrace": self.sub, "ancestry": self.anc})
        req = ask()
        if not req:
            return
        if req["subrace_required"] and not self.sub and req["subraces"]:
            self.sub = req["subraces"][0]
            req = ask() or req
        elif self.sub and self.sub not in req["subraces"]:
            self.sub = ""
            req = ask() or req
        if req["ancestries"] and self.anc not in req["ancestries"]:
            self.anc = req["ancestries"][0]
        self.req = req
        subs = ([] if req["subrace_required"] else [(tr("—"), "")]) + [(tr(s), s) for s in req["subraces"]]
        set_items(self.sub_box, subs, self.sub)
        for i in range(self.sub_box.count()):
            v = self.sub_box.itemData(i)
            if v:
                self.sub_box.setItemData(i, describe_text("races", f"{self.race}::{v}"), Qt.ToolTipRole)
        self.sub_box.setEnabled(bool(req["subraces"]))
        set_items(self.anc_box, [(tr(a), a) for a in req["ancestries"]], self.anc)
        self.anc_box.setVisible(bool(req["ancestries"]))
        self.anc_label.setVisible(bool(req["ancestries"]))
        self.info.set_text(tr(req["info"]))

        clear_layout(self.choices)
        self.w = {}
        add = lambda heading, key, w: (self.w.__setitem__(key, w), self.choices.addWidget(section(heading, "", w)))
        if req["ability_choose"]:
            a = req["ability_choose"]
            add(tr("Increase {0} abilities by {1}", a["count"], a["amount"]), "ability",
                picks([{"value": k, "label": E.ABILITY_NAMES[k]} for k in a["from"]], a["count"], prev.get("ability"), self.changed))
        if req["languages_any"]:
            add(tr("Extra languages (choose {0})", req["languages_any"]), "languages",
                picks(CF.language_options(req["languages_pool"]), req["languages_any"], prev.get("languages"), self.changed))
        if req["skills_any"]:
            add(tr("Skill proficiencies (choose {0})", req["skills_any"]), "skills",
                picks(req["skills_pool"], req["skills_any"], prev.get("skills"), self.changed))
        if req["tool"] and req["tool"]["from"]:
            add(tr("Tool proficiency"), "tools", picks(req["tool"]["from"], req["tool"]["count"], prev.get("tools"), self.changed))
        if req["cantrip_choice"]:
            add(tr("Racial cantrip (choose {0})", req["cantrip_choice"]), "cantrips",
                picks(req["cantrip_pool"], req["cantrip_choice"], prev.get("cantrips"), self.changed))
        if req["spell_ability"]:
            c = combo([(tr(E.ABILITY_NAMES[k]), k) for k in req["spell_ability"]], current=prev.get("spell_ability"),
                      on_change=lambda _v: self.changed())
            self.w["spell_ability"] = c
            self.choices.addLayout(row(label(tr("Spellcasting ability for racial spells")), c, stretch()))
        if req["feats"]:
            f = FeatPicker(self.wiz.lists["feats"], None, prev.get("feat") or "", prev.get("feat_choices"))
            f.changed.connect(self.changed)
            add(tr("Feat"), "feat", f)
        self._sync()

    def changed(self):
        self._sync()
        super().changed()

    def _sync(self):
        """A racial feat (Skilled, Magic Initiate) can't take what the race's own picks already took, and back."""
        f = self.w.get("feat")
        fp = lambda k: f.pick(k) if f else None
        sync_taken([self.w.get("skills"), fp("proficiencies")], [self.w.get("tools"), fp("proficiencies")],
                   [self.w.get("cantrips"), fp("cantrips"), fp("spell")])

    def collect_choices(self) -> dict:
        out = {}
        for k, w in self.w.items():
            if k == "spell_ability":
                out[k] = w.currentData()
            elif k == "feat":
                out["feat"] = w.value()
                out["feat_choices"] = w.choices()
            else:
                out[k] = w.chosen()
        return out

    def collect(self):
        return {"race": self.race, "subrace": self.sub or None, "ancestry": self.anc or None,
                "race_choices": self.collect_choices()}

    def problem(self, spec):
        if "feat" in self.w and not self.w["feat"].done():
            return tr("Choose the feat and its options.")
        r = CF.validate(spec, "race")
        return None if r["ok"] else r["problem"]


class ScoresStep(Step):
    key = "scores"

    def heading(self) -> str:
        return tr("Ability scores")

    def hint_text(self) -> str:
        if self.method == "point_buy":
            return tr("Spend up to {0} points; scores 8–15 before racial bonuses.", self.wiz.lists["point_buy_budget"])
        if self.method == "rolled":
            return tr("Roll 4d6 six times (drop the lowest), then assign each result once.")
        if self.method == "manual":
            return tr("Type any score from 1 to 20 before racial bonuses (rolled at the table, or set by the DM).")
        return tr("Assign 15, 14, 13, 12, 10 and 8, one each.")

    def __init__(self, wiz):
        super().__init__(wiz)
        self.method, self.vals, self.rolled, self.racial, self.roll_text = "standard_array", {}, [], {}, ""
        lay, self.method_buttons = radios([(tr("Standard array"), "standard_array"), (tr("Point buy"), "point_buy"),
                                           (tr("Roll 4d6"), "rolled"), (tr("Enter scores"), "manual")], self.method, self._method)
        self.box.addWidget(lay)
        self.hint = label("", role="dim", wrap=True)
        self.box.addWidget(self.hint)
        grid = QGridLayout()
        grid.setHorizontalSpacing(12)
        grid.setVerticalSpacing(3)
        for c, t in enumerate((tr("Ability"), tr("Score"), tr("Racial"), tr("Total"))):
            grid.addWidget(title(t), 0, c)
        self.inputs: Dict[str, tuple] = {}
        for i, (k, n) in enumerate(ABILITIES, start=1):
            box = combo(on_change=lambda v, k=k: self._set(k, v), width=80)
            sp = spin(8, 8, 15, on_change=lambda v, k=k: self._set(k, v), width=80)
            sp.setButtonSymbols(QSpinBox.UpDownArrows)
            bonus, total = label("", role="dim"), label("")
            f = total.font()
            f.setBold(True)
            total.setFont(f)
            grid.addWidget(label(tr(n)), i, 0)
            grid.addWidget(box, i, 1)
            grid.addWidget(sp, i, 1)
            grid.addWidget(bonus, i, 2)
            grid.addWidget(total, i, 3)
            self.inputs[k] = (box, sp, bonus, total)
        grid.setColumnStretch(4, 1)
        self.box.addLayout(grid)
        self.spent = label("")
        self.roll_btn = button(tr("🎲 Roll 4d6 ×6"), self.roll)
        self.box.addLayout(row(self.roll_btn, self.spent, stretch()))
        self.box.addStretch(1)
        self.draw()

    def deps(self, spec):
        return _key(spec, "race", "subrace", "ancestry", "race_choices")

    def redraw(self, spec):
        self.racial = errors.guard(CF.racial_bonuses, spec) or {}
        self.draw()

    def _method(self, m: str):
        self.method = m
        self.vals = {k: 8 for k in E.ABILITIES} if m == "point_buy" else \
            {k: self.vals.get(k) or 10 for k in E.ABILITIES} if m == "manual" else {}
        self.roll_text = ""
        self.draw()
        self.changed()

    def load(self, method: str, scores: dict):
        """Show scores chosen earlier (editing an existing character). Rolled scores become the values to assign."""
        self.method = method if method in self.method_buttons else "manual"
        self.vals = {k: scores.get(k) for k in E.ABILITIES}
        self.rolled = sorted((v for v in self.vals.values() if v), reverse=True) if self.method == "rolled" else []
        self.roll_text = tr("Rolled: {0} — assign each value once.", ", ".join(map(str, self.rolled))) if self.rolled else ""
        b = self.method_buttons[self.method]
        b.blockSignals(True)
        b.setChecked(True)
        b.blockSignals(False)
        self.draw()

    def _set(self, k: str, v):
        self.vals[k] = int(v) if v not in (None, "") else None
        self.draw()
        self.changed()

    def available(self, k: str) -> List[int]:
        """Each value of the array / the rolls can be used once: what the other abilities haven't taken."""
        pool = list(self.wiz.lists["standard_array"] if self.method == "standard_array" else self.rolled)
        for other in E.ABILITIES:
            if other != k and self.vals.get(other) in pool:
                pool.remove(self.vals[other])
        if self.vals.get(k) is not None and self.vals[k] not in pool:
            pool.append(self.vals[k])
        return sorted(pool, reverse=True)

    def draw(self):
        L = self.wiz.lists
        self.hint.setText(self.roll_text or self.hint_text())
        self.roll_btn.setVisible(self.method == "rolled")
        buy = self.method == "point_buy"
        typed = buy or self.method == "manual"
        for k, (box, sp, bonus, total) in self.inputs.items():
            box.setVisible(not typed)
            sp.setVisible(typed)
            if typed:
                sp.blockSignals(True)
                sp.setRange(*((8, 15) if buy else (1, 20)))
                sp.setValue(self.vals.get(k) or (8 if buy else 10))
                sp.blockSignals(False)
            else:
                set_items(box, [(tr("—"), "")] + [(str(v), v) for v in self.available(k)], self.vals.get(k) or "")
            v = self.vals.get(k)
            bonus.setText(f"+{self.racial[k]}" if self.racial.get(k) else "")
            total.setText(str(min(E.MAX_ABILITY, v + self.racial.get(k, 0))) if v else "?")
        if buy:
            spent = CF.point_buy_spent(self.vals)
            self.spent.setText(tr("Points spent: {0} / {1}", spent, L["point_buy_budget"]))
            self.spent.setProperty("role", "good" if spent <= L["point_buy_budget"] else "bad")
            self.spent.style().polish(self.spent)
        else:
            self.spent.setText("")

    def roll(self):
        r = E.roll_ability_scores()
        self.rolled = sorted((t for t, _d in r), reverse=True)
        self.vals = {}
        self.roll_text = tr("Rolled: {0} — assign each value once.",
                            ", ".join(f"{t} ({'+'.join(map(str, sorted(d, reverse=True)))})" for t, d in r))
        self.draw()
        self.changed()

    def collect(self):
        return {"scores_method": self.method, "scores": {k: self.vals.get(k) for k in E.ABILITIES}}

    def problem(self, spec):
        return CF.scores_problem(self.method, self.collect()["scores"], self.rolled)


class BackgroundStep(Step):
    key = "background"

    def heading(self) -> str:
        return tr("Background")

    def __init__(self, wiz):
        super().__init__(wiz)
        self.bg = wiz.lists["backgrounds"][0]["name"]
        self.w: Dict[str, object] = {}
        self._prev: Optional[dict] = None              # choices to show at the next redraw (load)
        self.bg_sel = FoldSelect(CF.book_groups(wiz.lists["backgrounds"]), self.bg, on_change=self._bg, detail=detail_of("backgrounds"))
        self.bg_sel.setFixedWidth(260)
        self.box.addLayout(row(label(tr("Background")), self.bg_sel,
                               button(tr("Generator…"), self.generator, tip=tr("Build a custom background from chosen proficiencies (with presets)")),
                               stretch()))
        self.info = _info_view(130)
        self.box.addWidget(self.info)
        self.dyn = QVBoxLayout()
        self.dyn.setSpacing(8)
        self.box.addLayout(self.dyn)
        self.traits: Dict[str, QComboBox] = {}
        grid = QGridLayout()
        for i, (k, t) in enumerate(TRAITS()):
            c = Combo()
            c.setEditable(True)
            c.setInsertPolicy(QComboBox.NoInsert)
            c.setSizeAdjustPolicy(QComboBox.AdjustToMinimumContentsLengthWithIcon)
            c.setMinimumContentsLength(24)
            c.view().setMinimumWidth(620)
            c.lineEdit().setPlaceholderText(t)
            c.view().setTextElideMode(Qt.ElideNone)
            self.traits[k] = c
            grid.addWidget(label(t), i, 0)
            grid.addWidget(c, i, 1)
        grid.setColumnStretch(1, 1)
        self.box.addWidget(section(tr("Characteristics"), tr("Pick a suggestion or write your own (optional)."), widget(grid)))
        self.box.addStretch(1)

    def deps(self, spec):
        return _key(spec, "race", "subrace", "ancestry", "race_choices") + "|" + self.bg

    def _bg(self, v):
        self.bg = v
        self.w = {}
        self.ensure(self.wiz.spec())
        self.changed()

    def generator(self):
        name = open_background_builder(self)
        if not name:
            return
        self.wiz.lists = CF.lists()
        self.bg_sel.set_groups(CF.book_groups(self.wiz.lists["backgrounds"]))
        self.bg_sel.set_value(name)
        self._bg(name)

    def load(self, spec: dict):
        """Show a background chosen earlier with its choices and characteristics (editing an existing character)."""
        self.bg = spec.get("background") or self.bg
        self.bg_sel.set_value(self.bg)
        self._prev = spec.get("background_choices") or {}
        for k, c in self.traits.items():
            c.setEditText((spec.get("details") or {}).get(k, ""))

    def redraw(self, spec):
        prev = self._prev if self._prev is not None else self.collect()["background_choices"]
        self._prev = None
        req = errors.guard(CF.background_step, {**spec, "background": self.bg})
        if not req:
            return
        self.info.set_text(tr(req["info"]))
        clear_layout(self.dyn)
        self.w = {}

        def mk(heading, key, opts, n):
            self.w[key] = picks(opts, n, prev.get(key), self.changed)
            self.dyn.addWidget(section(heading, "", self.w[key]))
        if req["skills_wanted"]:
            mk(tr("Replacement skill proficiencies (choose {0})", req["skills_wanted"]) if req["duplicates"]
               else tr("Skills (choose {0})", req["skills_wanted"]), "skills", req["skills_pool"], req["skills_wanted"])
        if req["languages_any"]:
            mk(tr("Languages (choose {0})", req["languages_any"]), "languages", CF.language_options(req["languages_pool"]), req["languages_any"])
        if req["tools_count"]:
            mk(tr("Tool proficiencies (choose {0})", req["tools_count"]), "tools", req["tools_pool"], req["tools_count"])
        for k, c in self.traits.items():
            keep = c.currentText()
            c.blockSignals(True)
            c.clear()
            c.addItems([tr(x) for x in req["characteristics"].get(k) or []])
            c.setEditText(keep)
            c.blockSignals(False)

    def collect(self):
        return {"background": self.bg, "background_choices": {k: p.chosen() for k, p in self.w.items()},
                "details": {k: c.currentText().strip() for k, c in self.traits.items()}}

    def problem(self, spec):
        r = CF.validate(spec, "background")
        return None if r["ok"] else r["problem"]


class ClassStep(Step):
    key = "class"

    def heading(self) -> str:
        return tr("Class")

    def __init__(self, wiz):
        super().__init__(wiz)
        classes = wiz.lists["classes"]
        self.cls = classes[0]["name"]
        self.sub, self.panel, self.panel_cls = "", None, None
        self.cls_sel = FoldSelect([{"title": "", "items": [c["name"] for c in classes]}], self.cls, on_change=self._cls,
                                  detail=detail_of("classes"))
        self.cls_sel.setFixedWidth(260)
        self.box.addLayout(row(label(tr("Class")), self.cls_sel, stretch()))
        self.info = _info_view(110)
        self.box.addWidget(self.info)
        self.holder = QVBoxLayout()
        self.box.addLayout(self.holder, 1)

    def deps(self, spec):
        return _key(spec, "race", "subrace", "ancestry", "race_choices", "scores", "background", "background_choices")

    def _cls(self, v):
        self.cls, self.sub = v, ""
        self.redraw(self.wiz.spec())
        self.changed()

    def _sub(self, s):
        self.sub = s
        self.redraw(self.wiz.spec())
        self.changed()

    def redraw(self, spec):
        prev = self.panel.collect() if self.panel and self.panel_cls == self.cls else {}
        r = errors.guard(CF.class_step, {**spec, "class": self.cls}, self.sub)
        if not r:
            return
        self.info.set_text(tr(r["info"]))
        clear_layout(self.holder)
        self.panel = ChoicesPanel(r["plan"], None, self.sub, prev, on_change=self.changed, on_subclass=self._sub)
        self.panel_cls = self.cls
        self.holder.addWidget(self.panel)

    def collect(self):
        return {"class": self.cls, "class_choices": self.panel.collect() if self.panel else {}}

    def problem(self, spec):
        if not self.panel:
            return tr("Choose a class.")
        pend = self.panel.pending()
        if pend:
            return tr("Still to choose: {0}", ", ".join(pend))
        r = CF.validate(spec, "class")
        return None if r["ok"] else r["problem"]


class EquipmentStep(Step):
    key = "equipment"

    def heading(self) -> str:
        return tr("Equipment")

    def __init__(self, wiz):
        super().__init__(wiz)
        self.data, self.state_key = None, ""
        self.picked: Dict[str, list] = {"class": [], "background": []}
        self.use_gold = QCheckBox()
        self.use_gold.toggled.connect(lambda _on: (self._toggle(), self.changed()))
        self.gold = line_edit(placeholder=tr("gp"), width=80)
        self.gold.textChanged.connect(lambda _t: self.changed())
        self.box.addLayout(row(self.use_gold, self.gold, button("🎲", self.roll_gold, kind="flat", tip=tr("Roll the starting gold"), width=30), stretch()))
        self.groups = QWidget()
        self.groups_box = QVBoxLayout(self.groups)
        self.groups_box.setContentsMargins(0, 0, 0, 0)
        self.groups_box.setSpacing(6)
        self.box.addWidget(self.groups)
        self.box.addStretch(1)
        self._toggle()

    def deps(self, spec):
        return _key(spec, "class", "background")

    def _toggle(self):
        self.gold.setEnabled(self.use_gold.isChecked())
        self.groups.setEnabled(not self.use_gold.isChecked())

    def roll_gold(self):
        if not self.data:
            return
        g = errors.guard(E.roll_starting_gold, self.data["gold"])
        if g is not None:
            self.gold.setText(str(g))
            self.use_gold.setChecked(True)

    def redraw(self, spec):
        if not spec.get("class") or not spec.get("background"):
            return
        key = f"{spec['class']}|{spec['background']}"
        if key != self.state_key:
            self.picked, self.state_key = {"class": [], "background": []}, key
        data = errors.guard(CF.equipment_step, spec)
        if not data:
            return
        self.data = data
        self.use_gold.setText(tr("Take starting gold instead of equipment ({0})", data["gold"]))
        clear_layout(self.groups_box)
        for which, heading in (("class", tr("Class equipment")), ("background", tr("{0} background", tr(spec["background"])))):
            self.groups_box.addWidget(title(heading))
            hints = (data.get("text") or []) if which == "class" else []
            for gi, g in enumerate(data[which]):
                if gi < len(hints) and "fixed" not in g:
                    self.groups_box.addWidget(label(tr(hints[gi]), role="dim", wrap=True))
                self.groups_box.addWidget(self._group(which, gi, g))
            self.groups_box.addSpacing(6)

    @staticmethod
    def _text(it: dict) -> str:
        qty = it.get("qty")
        name = it.get("label") or it.get("item") or it.get("special") or (f"{it.get('gp')} gp" if it.get("gp") else "")
        return (f"{qty}× " if qty and qty != 1 else "") + tr(str(name).replace("|", " "))

    def _state(self, which: str, gi: int, g: dict) -> dict:
        lst = self.picked[which]
        while len(lst) <= gi:
            lst.append(None)
        if lst[gi] is None:
            lst[gi] = {"option": "_" if "fixed" in g else "a", "vals": {}}
        return lst[gi]

    def _group(self, which: str, gi: int, g: dict) -> QWidget:
        st = self._state(which, gi, g)
        keys = ["fixed"] if "fixed" in g else sorted(k for k in g if k != "fixed")
        host = QWidget()
        lay = QVBoxLayout(host)
        lay.setContentsMargins(8, 0, 0, 0)
        lay.setSpacing(2)
        group = QButtonGroup(host)
        for k in keys:
            line = row()
            if k != "fixed":
                rb = QRadioButton(f"({k})")
                rb.setChecked(st["option"] == k)
                rb.toggled.connect(lambda on, k=k: on and (st.__setitem__("option", k), self.changed()))
                group.addButton(rb)
                line.addWidget(rb)
            else:
                line.addWidget(label("•"))
            text = [self._text(it) for it in g[k] if not it.get("type")]
            if text:
                line.addWidget(label(", ".join(text), wrap=True), 1)
            slot = 0
            for it in g[k]:
                if it.get("type"):
                    vals = st["vals"].setdefault(k, [])
                    while len(vals) <= slot:
                        vals.append("")
                    c = combo([(tr("— pick —"), "")] + [(tr(o), o) for o in it.get("options") or []], current=vals[slot],
                              on_change=lambda v, vals=vals, i=slot, k=k: (vals.__setitem__(i, v or ""), self._choose(st, k)))
                    c.setMinimumWidth(150)
                    line.addWidget(c)
                    slot += 1
            if not text:
                line.addStretch(1)
            lay.addLayout(line)
        return host

    def _choose(self, st: dict, k: str):
        if k != "fixed" and st["option"] != k:          # picking an item of an option also selects that option
            st["option"] = k
            self.redraw(self.wiz.spec())
        self.changed()

    def collect(self):
        if not self.data:
            return {"equipment": {}}
        if self.use_gold.isChecked():
            t = self.gold.text().strip()
            return {"equipment": {"gold": int(t) if t.isdigit() else -1}}

        def one(which, gi, g):
            st = self._state(which, gi, g)
            o = "a" if st["option"] == "_" else st["option"]
            k = "fixed" if "fixed" in g else o
            n = sum(1 for it in g.get(k) or [] if it.get("type"))
            vals = st["vals"].get(k) or []
            return {"option": o, "picks": [vals[i] if i < len(vals) else "" for i in range(n)]}
        return {"equipment": {"gold": None, **{w: [one(w, i, g) for i, g in enumerate(self.data[w])] for w in ("class", "background")}}}

    def problem(self, spec):
        if not self.data or self.wiz.problems.get("class"):
            return None
        p = CF.equipment_problem(self.collect()["equipment"])
        if p:
            return p
        r = CF.validate(spec, "equipment")
        return None if r["ok"] else r["problem"]


class DetailsStep(Step):
    key = "details"

    def heading(self) -> str:
        return tr("Details")

    def __init__(self, wiz):
        super().__init__(wiz)
        self.portrait: Optional[dict] = None              # from the portrait editor; None: the automatic one
        self.race, self.cls = "", ""
        self.face = label()
        self.face_note = label("", role="dim", wrap=True)
        self.box.addLayout(row(self.face, col(title(tr("Portrait")), self.face_note,
                                              row(button(tr("Choose portrait…"), self._choose,
                                                         tip=tr("A portrait from the library or a picture of your own, "
                                                                "cut round and given a token border")),
                                                  button(tr("Automatic"), lambda: self._set(None)), stretch())),
                               spacing=10))
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        self.fields = {}
        for i, (k, t) in enumerate(LOOKS()):
            e = line_edit()
            self.fields[k] = e
            grid.addWidget(label(t), i // 2, (i % 2) * 2)
            grid.addWidget(e, i // 2, (i % 2) * 2 + 1)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)
        self.box.addLayout(grid)
        self.appearance, self.backstory = QPlainTextEdit(), QPlainTextEdit()
        for e in (self.appearance, self.backstory):
            e.setMinimumHeight(90)
        self.box.addWidget(label(tr("Appearance")))
        self.box.addWidget(self.appearance)
        self.box.addWidget(label(tr("Backstory")))
        self.box.addWidget(self.backstory, 1)

    def deps(self, spec):
        return _key(spec, "race", "subrace", "class")

    def redraw(self, spec):
        self.race, self.cls = spec.get("race") or "", spec.get("class") or ""
        self._set(self.portrait)

    def _set(self, portrait: Optional[dict]):
        self.portrait = portrait
        if portrait:
            img = QImage.fromData(portrait["png"])
            pm = QPixmap.fromImage(img.scaled(72, 72, Qt.KeepAspectRatio, Qt.SmoothTransformation) if portrait["framed"]
                                   else render(img, {"style": "side"}, 72))
            self.face_note.setText(tr("A portrait of its own."))
        else:
            pm = portrait_pixmap(portraits.of({"race": self.race})[0], False, 72)
            self.face_note.setText(tr("Automatic: the picture of its race. Choose a portrait from the library or a "
                                      "picture of your own; it is the character's token on the battle maps."))
        self.face.setPixmap(pm)

    def _choose(self):
        current = {"image": QImage.fromData(self.portrait["inner"]), "border": self.portrait["border"]} if self.portrait else {}
        choice = open_portrait_editor(self, self.race, self.cls, current)
        if choice is not None:
            self._set(choice or None)

    def collect(self):
        d = {k: e.text().strip() for k, e in self.fields.items()}
        d.update(appearance=self.appearance.toPlainText().strip(), backstory=self.backstory.toPlainText().strip())
        return {"details": d}


class _Issue(QLabel):
    """One checklist line; clicking it opens the step it is about."""

    def __init__(self, text: str, level: str, on_click=None):
        super().__init__(text)
        self.setWordWrap(True)
        self.setProperty("role", {"error": "bad", "warn": "warn"}.get(level, ""))
        self.on_click = on_click
        if on_click:
            self.setCursor(Qt.PointingHandCursor)
            self.setToolTip(tr("Go to this step"))

    def mouseReleaseEvent(self, event):
        if self.on_click:
            self.on_click()
        super().mouseReleaseEvent(event)


class ReviewStep(Step):
    key = "review"

    def heading(self) -> str:
        return tr("Review")

    def __init__(self, wiz):
        super().__init__(wiz)
        self.counts = label("", role="dim")
        self.box.addLayout(row(title(tr("Checklist")), stretch(), self.counts))
        self.list_box = QVBoxLayout()
        self.list_box.setSpacing(3)
        host = widget(col(self.list_box, stretch(), margins=4))
        self.preview = TextView()
        self.preview.setPlaceholderText(tr("Fix the errors in the checklist to see the character preview."))
        split = QSplitter(Qt.Vertical)
        split.addWidget(scroll(host))
        split.addWidget(widget(col(title(tr("Preview")), self.preview)))
        split.setSizes([220, 400])
        self.box.addWidget(split, 1)
        self.lines: List[_Issue] = []

    def show_issues(self, issues: List[dict], preview: str):
        clear_layout(self.list_box)
        n = {lvl: sum(1 for i in issues if i["level"] == lvl) for lvl in ICON}
        self.counts.setText(f"❌ {n['error']}   ⚠ {n['warn']}   ℹ {n['info']}")
        rank = {"error": 0, "warn": 1, "info": 2}
        self.lines = []
        for i in sorted(issues, key=lambda i: rank[i["level"]]):
            sec = i.get("section")
            line = _Issue(f"{ICON[i['level']]}  {i['text']}", i["level"], (lambda s=sec: self.wiz.go_to(s)) if sec else None)
            self.lines.append(line)
            self.list_box.addWidget(line)
        if not issues:
            self.list_box.addWidget(label("✅ " + tr("Nothing missing."), role="good"))
        self.preview.set_text(preview)


# ---------------------------------------------------------------------- the window
class CreationWizard(Dialog):
    ORDER = (ConceptStep, RaceStep, ScoresStep, BackgroundStep, ClassStep, EquipmentStep, DetailsStep, ReviewStep)

    def __init__(self, parent=None, owner_id: Optional[int] = None, owner_name: Optional[str] = None):
        super().__init__(parent, tr("New character") + (tr(" for {0}", owner_name) if owner_name else ""), 1060, 720)
        self.owner_id, self.owner_name = owner_id, owner_name
        self.created: Optional[str] = None
        self.lists = CF.lists()
        self.problems: Dict[str, str] = {}
        self.issues: List[dict] = []
        self.visited = {0}
        self._timer = QTimer(self, singleShot=True, interval=350)
        self._timer.timeout.connect(lambda: errors.guard(self.evaluate))
        self._ready = False

        self.step_list = QListWidget()
        self.step_list.setFixedWidth(170)
        self.step_list.currentRowChanged.connect(lambda i: i >= 0 and self._ready and self.go(i))
        self.stack = QStackedWidget()
        self.steps: List[Step] = []
        for cls in self.ORDER:
            st = cls(self)
            self.steps.append(st)
            self.stack.addWidget(st if cls is ReviewStep else scroll(st))
            self.step_list.addItem(QListWidgetItem(st.heading()))
        self.heading = label("", role="accent")
        f = self.heading.font()
        f.setPointSize(f.pointSize() + 2)
        f.setBold(True)
        self.heading.setFont(f)
        self.body.addLayout(row(self.step_list, col(self.heading, self.stack, spacing=6), spacing=10), 1)

        self.todo = label("")
        self.buttons.insertWidget(0, self.todo, 1)
        self.add_button(tr("Cancel"), self.reject)
        self.back_btn = self.add_button(tr("◀ Back"), lambda: self.go(self.current() - 1))
        self.next_btn = self.add_button(tr("Next ▶"), self.next)
        self.create_btn = self.add_button(tr("Create character"), self.submit, kind="primary")
        self.create_btn.setEnabled(False)
        self._ready = True
        self.go(0)

    # ------------------------------------------------------------------ navigation
    def current(self) -> int:
        return self.stack.currentIndex()

    def step(self, key: str) -> Step:
        return next(s for s in self.steps if s.key == key)

    def go(self, i: int):
        i = max(0, min(i, len(self.steps) - 1))
        self.visited.add(i)
        self.stack.setCurrentIndex(i)
        self.step_list.blockSignals(True)
        self.step_list.setCurrentRow(i)
        self.step_list.blockSignals(False)
        self.heading.setText(self.steps[i].heading())
        self.back_btn.setEnabled(i > 0)
        self.next_btn.setVisible(i < len(self.steps) - 1)
        self.next_btn.setDefault(i < len(self.steps) - 1)
        self.create_btn.setDefault(i == len(self.steps) - 1)
        errors.guard(self.evaluate)

    def go_to(self, key: str):
        self.go(next(i for i, s in enumerate(self.steps) if s.key == key))

    def next(self):
        self.evaluate()
        p = self.problems.get(self.steps[self.current()].key)
        if p:
            self.show_problem(tr(p))
            return
        self.go(self.current() + 1)

    # ------------------------------------------------------------------ state
    def spec(self) -> dict:
        out: dict = {"details": {}}
        for st in self.steps:
            c = dict(st.collect())
            out["details"].update(c.pop("details", None) or {})
            out.update(c)
        return out

    def changed(self):
        if self._ready:
            self._timer.start()

    def evaluate(self):
        """Bring every step up to date with the ones before it, check them all, and show the result."""
        self._timer.stop()
        for st in self.steps:
            st.ensure(self.spec())
        spec = self.spec()
        self.problems, issues = {}, []
        for st in self.steps:
            p = st.problem(spec)
            if p:
                self.problems[st.key] = p
                issues.append({"level": "error", "text": f"{st.heading()}: {tr(p)}", "section": st.key})
        if spec["scores_method"] == "point_buy":
            left = self.lists["point_buy_budget"] - CF.point_buy_spent(spec["scores"])
            if 0 < left <= self.lists["point_buy_budget"]:
                issues.append({"level": "warn", "text": tr("{0} point-buy point(s) are still unspent.", left), "section": "scores"})
        preview = ""
        if not issues or all(i["level"] != "error" for i in issues):
            r = errors.guard(CF.review, spec)
            if r and r["ok"]:
                preview = r["text"]
                issues += [{**n, "text": tr(n["text"])} for n in r.get("notes") or []]
            elif r:
                issues.append({"level": "error", "text": tr(r["problem"])})
                preview = "⚠ " + tr(r["problem"])
        else:
            issues.append({"level": "info", "text": tr("Warnings and tips appear once the errors are fixed.")})
        self.issues = issues
        self.step(ReviewStep.key).show_issues(issues, tr(preview) if preview else "")
        self._draw_status()

    def _draw_status(self):
        warned = {i.get("section") for i in self.issues if i["level"] == "warn"}
        for i, st in enumerate(self.steps):
            it = self.step_list.item(i)
            if st.key == "review":
                mark = "📋"
            elif st.key in self.problems:
                mark = "❌" if i in self.visited else "○"
            elif st.key in warned:
                mark = "⚠"
            else:
                mark = "✔"
            it.setText(f"{mark}  {st.heading()}")
            it.setToolTip(tr(self.problems[st.key]) if st.key in self.problems else "")
        cur = self.steps[self.current()].key
        self.show_problem(tr(self.problems[cur]) if cur in self.problems else "")
        errs = sum(1 for i in self.issues if i["level"] == "error")
        warns = sum(1 for i in self.issues if i["level"] == "warn")
        self.create_btn.setEnabled(errs == 0)
        if errs:
            self.todo.setText(tr("❌ {0} to fix before creating", errs))
        elif warns:
            self.todo.setText(tr("Ready — ⚠ {0} warning(s)", warns))
        else:
            self.todo.setText(tr("Ready to create."))
        self.todo.setProperty("role", "bad" if errs else "warn" if warns else "good")
        self.todo.style().polish(self.todo)

    def submit(self):
        self.evaluate()
        if any(i["level"] == "error" for i in self.issues):
            return
        ok, char = attempt(self, rt().characters.create_from_spec, self.spec(), self.owner_id, self.owner_name)
        if ok:
            portrait = self.step(DetailsStep.key).portrait
            if portrait:
                errors.guard(rt().characters.set_portrait, char.name, portrait)
            self.created = char.name
            notify.good(tr("Created {0}.", char.name))
            self.accept()


def open_creation_wizard(parent=None, owner_id: Optional[int] = None, owner_name: Optional[str] = None) -> Optional[str]:
    """Modal. Returns the new character's name, or None when cancelled."""
    d = errors.guard(CreationWizard, parent, owner_id, owner_name)
    if d is None:
        return None
    return d.created if d.exec() == QDialog.Accepted else None


@action("characters.new", "New character…", menu="Characters", shortcut="Ctrl+N")
def new_character(window):
    name = open_creation_wizard(window)
    if name:
        rt().select_character(name)
