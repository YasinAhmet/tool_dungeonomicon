"""Background builder: make a custom background from chosen proficiencies. Presets fill the form and can be edited,
saved, deleted and reset.

    name = open_background_builder(parent)      # the new background's name, or None
"""
from typing import Optional

from PySide6.QtWidgets import QDialog, QGridLayout, QPlainTextEdit, QWidget

from ....core import events
from ....core.i18n import tr
from ....core.runtime import rt
from ....rules import custom_background as CB
from ....rules.data import rules
from ... import notify
from ...dialogs import Dialog
from ...widgets.common import FlowLayout, button, col, label, line_edit, row, spin, stretch
from .choices import attempt, picks, section


class BackgroundBuilder(Dialog):
    def __init__(self, parent=None):
        super().__init__(parent, tr("Background generator"), 900, 640)
        self.created: Optional[str] = None
        self.presets = CB.presets()
        self.current: Optional[str] = None
        self.skill_pool, self.tool_pool = list(rules.skills), CB.tool_pool()

        self.chips_host = QWidget()
        self.chips = FlowLayout(self.chips_host)
        self.body.addWidget(self.chips_host)
        self.name = line_edit(placeholder=tr("Background name"))
        self.skills = picks(self.skill_pool, 4, rows=10)
        self.tools = picks(self.tool_pool, 6, rows=10)
        self.tools_any = spin(0, 0, 4, width=48)
        self.langs_any = spin(0, 0, 4, width=48)
        self.gp = spin(10, 0, 100000, width=64)
        self.fname = line_edit(placeholder=tr("Feature name"))
        self.ftext = QPlainTextEdit()
        self.ftext.setPlaceholderText(tr("What the feature does…"))
        self.ftext.setFixedHeight(70)
        self.equip = QPlainTextEdit()
        self.equip.setPlaceholderText(tr("One item per line"))
        self.equip.setFixedHeight(90)

        grid = QGridLayout()
        grid.setHorizontalSpacing(14)
        grid.addLayout(col(label(tr("Name")), self.name,
                           section(tr("Skill proficiencies"), tr("The PHB suggests two."), self.skills),
                           row(label(tr("Extra tools (your choice)")), self.tools_any, label(tr("Extra languages")), self.langs_any,
                               label(tr("Pouch gp")), self.gp, stretch()), stretch()), 0, 0)
        grid.addLayout(col(section(tr("Fixed tool proficiencies"), "", self.tools),
                           label(tr("Feature")), self.fname, label(tr("Feature text")), self.ftext,
                           label(tr("Equipment")), self.equip, stretch()), 0, 1)
        grid.setColumnStretch(0, 1)
        grid.setColumnStretch(1, 1)
        self.body.addLayout(grid, 1)

        self.add_button(tr("Reset presets"), self.reset_presets)
        self.add_button(tr("Delete preset"), self.delete_preset, kind="danger")
        self.add_button(tr("Save as preset"), self.save_preset)
        self.add_button(tr("Cancel"), self.reject)
        self.add_button(tr("Use this background"), self.use, kind="primary", default=True)
        self.load(self.presets[0] if self.presets else None)

    # ------------------------------------------------------------------ the form
    def load(self, p: Optional[dict]):
        self.current = p["name"] if p else None
        self.name.setText(p["name"] if p else "")
        self.skills.set_options(self.skill_pool, p["skills"] if p else [])
        self.tools.set_options(self.tool_pool, p["tools"] if p else [])
        self.tools_any.setValue(p["tools_any"] if p else 0)
        self.langs_any.setValue(p["languages_any"] if p else 0)
        self.gp.setValue(p["gp"] if p else 10)
        self.fname.setText(p["feature_name"] if p else "")
        self.ftext.setPlainText(p["feature_text"] if p else "")
        self.equip.setPlainText("\n".join(p["equipment"]) if p else "")
        self.draw_presets()

    def draw_presets(self):
        while self.chips.count():
            it = self.chips.takeAt(0)
            if it.widget():
                it.widget().deleteLater()
        self.chips.addWidget(label(tr("Presets"), role="dim"))
        for p in self.presets:
            tip = "\n".join([p["name"], tr("Skills: {0}", ", ".join(p["skills"])),
                             tr("Tools: {0}", ", ".join(p["tools"]) or "—") + (tr(" +{0} of your choice", p["tools_any"]) if p["tools_any"] else ""),
                             tr("Languages: {0}", p["languages_any"])])
            b = button(p["name"], lambda p=p: self.load(p), tip=tip, checkable=True)
            b.setChecked(p["name"] == self.current)
            self.chips.addWidget(b)
        self.chips.addWidget(button(tr("+ blank"), lambda: self.load(None), kind="flat"))
        self.chips_host.updateGeometry()

    def spec(self) -> dict:
        return {"name": self.name.text().strip(), "skills": self.skills.chosen(), "tools": self.tools.chosen(),
                "tools_any": self.tools_any.value(), "languages_any": self.langs_any.value(),
                "feature_name": self.fname.text().strip(), "feature_text": self.ftext.toPlainText().strip(),
                "equipment": [x.strip() for x in self.equip.toPlainText().splitlines() if x.strip()], "gp": self.gp.value()}

    # ------------------------------------------------------------------ buttons
    def reset_presets(self):
        ok, got = attempt(self, CB.reset_presets)
        if ok:
            self.presets = got
            self.load(self.presets[0] if self.presets else None)

    def delete_preset(self):
        if not any(p["name"] == self.current for p in self.presets):
            notify.warn(tr("Pick a saved preset first."))
            return
        ok, got = attempt(self, CB.delete_preset, self.current)
        if ok:
            self.presets = got
            self.load(self.presets[0] if self.presets else None)

    def save_preset(self):
        ok, got = attempt(self, CB.save_preset, self.spec())
        if ok:
            self.presets = got
            self.current = self.spec()["name"]
            self.draw_presets()
            notify.good(tr("Preset saved."))

    def use(self):
        ok, name = attempt(self, CB.save_custom, self.spec())
        if ok:
            self.created = name
            rt().bus.emit(events.RULES)
            notify.good(tr("Background '{0}' created.", name))
            self.accept()


def open_background_builder(parent=None) -> Optional[str]:
    """Modal. Returns the name of the background that was created, or None."""
    d = BackgroundBuilder(parent)
    return d.created if d.exec() == QDialog.Accepted else None
