"""Level up: pick the class (own classes first, multiclass options with their requirements), make the level's
choices, and see what changes before applying it. The window opens maximized with the choices, a Details pane (what
is under the mouse) and the preview side by side. Also Edit levels: go back to an earlier level, choose again and
replay the levels after it.

    open_level_up(parent, name) -> bool                 # True when a level was gained
    open_edit_levels(parent, name) -> bool              # the list of levels to edit (and RESET ALL)
    open_edit_level(parent, name, index) -> bool        # redo the level at `index` (0 = level 2) and replay the rest
    open_reset_levels(parent, name) -> bool             # RESET ALL (reset_levels.py)
"""
from typing import Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QDialog, QGridLayout, QSplitter, QVBoxLayout

from ....core.i18n import tr
from ....core.runtime import rt
from ....services.characters import levelup_flow as LF
from ... import dialogs, errors, notify
from ...dialogs import Dialog
from ...registry import action
from ...widgets.common import button, clear_layout, col, combo, label, row, scroll, stretch, title as heading, widget
from ...widgets.pickers import PickList
from ...widgets.text import TextView
from .choices import ChoicesPanel, attempt, describe_text
from .reset_levels import open_reset_levels

__all__ = ["open_level_up", "open_edit_levels", "open_edit_level", "open_reset_levels"]


def preview_text(p: dict) -> str:
    """What a level gives, for the preview pane."""
    out = ["**" + tr("What you gain") + "**"]
    out += [f"{tr(s[0])}: {s[1]} → {s[2]}" for s in p["stats"]]
    if p["proficiencies"]:
        out += ["", "**" + tr("Proficiencies") + "**"] + [tr(x) for x in p["proficiencies"]]
    if p["spells"]:
        out += ["", "**" + tr("Spells") + "**", ", ".join(tr(s) for s in p["spells"])]
    for f in p["features"]:
        text = tr(f.get("text") or "")
        out += ["", f"**{tr(f['name'])}**", text[:2500] + ("…" if len(text) > 2500 else "")]
    return "\n".join(out)


class LevelUpDialog(Dialog):
    """Opens maximized: the choices on the left, the description of the entry under the mouse in the middle, and
    what the level gives on the right."""

    def __init__(self, parent, name: str, cls: Optional[str] = None, prev: Optional[dict] = None, replay: bool = False,
                 title: str = ""):
        super().__init__(parent, title or tr("Level up — {0}", name), 1300, 860)
        self.setWindowFlag(Qt.WindowMaximizeButtonHint, True)
        self.setWindowState(self.windowState() | Qt.WindowMaximized)
        self.name, self.prev_cls, self.prev, self.replay = name, cls, prev, replay
        self.applied = False
        self.panel: Optional[ChoicesPanel] = None
        self.subclass = (prev or {}).get("subclass") or ""
        self.options = LF.options(name)
        items = [(tr(o["label"]) + ("" if o["ok"] else f"  ({tr(o['note'])})"), o["class"]) for o in self.options]
        self.cls = combo(items, current=cls or self.options[0]["class"], on_change=lambda _v: self._class_changed())
        for i, o in enumerate(self.options):
            self.cls.setItemData(i, describe_text("classes", o["class"]), Qt.ToolTipRole)
        self.cls.setMinimumWidth(360)
        self.body.addLayout(row(label(tr("Class")), self.cls,
                                button(tr("About this class"), self._show_class, kind="flat"), stretch()))
        self.holder_w = widget(QVBoxLayout())
        self.holder = self.holder_w.layout()
        self.holder.setContentsMargins(0, 0, 12, 0)
        self.detail = TextView(heading_first_line=True)
        self.detail.setPlaceholderText(tr("Point at a spell, skill, feat or option to read about it here."))
        self.gain = TextView()
        self.gain.setPlaceholderText(tr("Make the choices to see what this level gives."))
        split = QSplitter(Qt.Horizontal)
        split.addWidget(widget(col(heading(tr("Choices")), scroll(self.holder_w))))
        split.addWidget(widget(col(heading(tr("Details")), self.detail)))
        split.addWidget(widget(col(heading(tr("Preview")), self.gain)))
        split.setStretchFactor(0, 5)
        split.setStretchFactor(1, 4)
        split.setStretchFactor(2, 3)
        split.setSizes([620, 460, 360])
        self.body.addWidget(split, 1)
        self.summary = label("", wrap=True)
        self.buttons.insertWidget(0, self.summary, 1)
        self.add_button(tr("Cancel"), self.reject)
        self.go = self.add_button(tr("Level up"), self.submit, kind="primary", default=True)
        self.go.setEnabled(False)
        self._timer = QTimer(self, singleShot=True, interval=250)
        self._timer.timeout.connect(lambda: errors.guard(self.update_preview))
        self.load_plan()

    def _class_changed(self):
        self.subclass = (self.prev or {}).get("subclass", "") if self.cls.currentData() == self.prev_cls else ""
        self.load_plan()

    def _set_subclass(self, sub: str):
        self.subclass = sub
        self.load_plan()

    def load_plan(self):
        self.go.setEnabled(False)
        cls = self.cls.currentData()
        keep = self.panel.collect() if self.panel and self.panel.plan["class"] == cls else None
        clear_layout(self.holder)
        self.panel = None
        try:
            plan = LF.plan(self.name, cls, self.subclass or None)
        except errors.user_errors() as e:
            self.holder.addWidget(label(tr(str(e)), role="bad", wrap=True))
            self.holder.addStretch(1)
            self._say(tr(str(e)), "bad")
            self.gain.set_text("")
            return
        prev = keep if keep is not None else (self.prev if cls == self.prev_cls else None)
        self.panel = ChoicesPanel(plan, self.name, self.subclass, prev, on_change=self._changed, on_subclass=self._set_subclass,
                                  rows=14)
        self.holder.addWidget(self.panel)
        self._hook_details()
        sub = self.panel.subclass() if plan.get("subclass") else ""
        self.detail.set_text(sub and describe_text("subclasses", f"{cls}::{sub}", 6000) or describe_text("classes", cls, 6000) or tr(cls))
        self.update_preview()

    def _changed(self):
        self._hook_details()                            # a feat's form brings new lists
        self._timer.start()

    def _hook_details(self):
        """Every pick list of the panel tells the Details pane what is under the mouse."""
        for p in self.panel.findChildren(PickList) if self.panel else []:
            if not p.property("detail_hooked"):
                p.setProperty("detail_hooked", True)
                p.hovered.connect(self._show_detail)

    def _show_detail(self, value: str, text: str):
        self.detail.set_text(text or tr(value))         # a description starts with its name, the heading

    def _show_class(self):
        cls = self.cls.currentData()
        self.detail.set_text(describe_text("classes", cls, 6000) or tr(cls))

    def _say(self, text: str, role: str):
        self.summary.setText(text)
        self.summary.setProperty("role", role)
        self.summary.style().polish(self.summary)

    def update_preview(self):
        self._timer.stop()
        if not self.panel:
            return
        pending = self.panel.pending()
        if pending:
            self._say(tr("Still to choose: {0}", ", ".join(pending)), "warn")
            self.gain.set_text("")
            self.go.setEnabled(False)
            return
        p = LF.preview_level(self.name, self.cls.currentData(), self.panel.collect())
        if not p["ok"]:
            self._say(tr(p["problem"]), "warn")
            self.gain.set_text("⚠ " + tr(p["problem"]))
            self.go.setEnabled(False)
            return
        bits = [f"{tr(s[0])} {s[1]}→{s[2]}" for s in p["stats"] if s[0] in ("Hit points", "Proficiency bonus")]
        bits += [tr(f["name"]) for f in p["features"][:4]]
        if p["spells"]:
            bits.append(tr("spells: {0}", ", ".join(tr(s) for s in p["spells"][:4]) + ("…" if len(p["spells"]) > 4 else "")))
        self._say("  ·  ".join(bits) or tr("Ready."), "good")
        self.gain.set_text(preview_text(p))
        self.go.setEnabled(True)

    def submit(self):
        self.update_preview()
        if not self.go.isEnabled():
            return
        ok, _char = attempt(self, rt().characters.level_up, self.name, self.cls.currentData(), self.panel.collect(), self.replay)
        if ok:
            self.applied = True
            if not self.replay:
                notify.good(tr("{0} gained a level!", self.name))
            self.accept()


def open_level_up(parent, name: str, cls: Optional[str] = None, prev: Optional[dict] = None, replay: bool = False,
                  title: str = "") -> bool:
    """Modal. cls/prev prefill the class and the earlier choices (editing a level); replay skips the XP check.
    Returns True when the level was applied."""
    d = errors.guard(LevelUpDialog, parent, name, cls, prev, replay, title)
    if d is None:
        return False
    d.exec()
    return d.applied


# ---------------------------------------------------------------------- edit levels
class EditLevelsDialog(Dialog):
    """Pick the level to change. The character goes back to just before it, you choose again, and every later level
    is replayed with the choices made then."""

    def __init__(self, parent, name: str):
        super().__init__(parent, tr("Edit levels — {0}", name), 600, 420)
        self.name = name
        self.picked: Optional[int] = None
        self.reset = False
        self.body.addWidget(label(tr("Pick the level to change. The character goes back to just before it, you choose again, "
                                     "and every later level is replayed with the choices made then (you are asked again only "
                                     "where one no longer fits). Level 1 comes from character creation."), role="dim", wrap=True))
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        rows = LF.level_history(name)
        for i, e in enumerate(rows):
            grid.addWidget(label(tr("Level {0}", e["level"])), i, 0)
            grid.addWidget(label(tr("{0} · from {1}", tr(e.get("class") or "?"), e["before"]), role="dim"), i, 1)
            if not e["recorded"]:
                grid.addWidget(label(tr("rebuilt from sheet"), role="warn",
                                     tip=tr("No record of what was chosen here, so the picks shown are rebuilt from the character sheet. Check them before applying.")), i, 2)
            grid.addWidget(button(tr("Edit from here"), lambda idx=e["index"]: self._pick(idx), kind="primary"), i, 3)
        grid.setColumnStretch(1, 1)
        grid.setRowStretch(len(rows), 1)
        if not rows:
            self.body.addWidget(label(tr("{0} has no level after the first to edit.", name), role="dim"))
        box = widget(grid)
        self.body.addWidget(scroll(box), 1)
        self.buttons.insertWidget(0, button(tr("RESET ALL…"), self._reset, kind="danger",
                                            tip=tr("Every level from the first to the last on one page, all choices editable.")))
        self.add_button(tr("Close"), self.reject)

    def _pick(self, index: int):
        self.picked = index
        self.accept()

    def _reset(self):
        self.reset = True
        self.accept()


def open_edit_levels(parent, name: str) -> bool:
    """The Edit levels window; runs the chosen edit (or RESET ALL). True when the character changed."""
    d = errors.guard(EditLevelsDialog, parent, name)
    if d is None or d.exec() != QDialog.Accepted:
        return False
    if d.reset:
        return open_reset_levels(parent, name)
    return d.picked is not None and open_edit_level(parent, name, d.picked)


def open_edit_level(parent, name: str, index: int) -> bool:
    """Redo the level at `index` (0 = level 2): the character goes back to before it, the level-up window asks for it
    again, and the later levels are replayed quietly when their recorded choices still fit (asked again otherwise).
    Cancelling offers to restore the character exactly as it was. Returns True when the edit was finished."""
    chars = rt().characters
    begin = errors.guard(chars.begin_edit, name, index)
    if not begin:
        return False
    queue = begin["queue"]
    i = 0
    while i < len(queue):
        q = queue[i]
        ok = False
        if i > 0 and q.get("class") and q.get("choices"):
            try:                                        # replay quietly when the recorded choices still fit
                chars.level_up(name, q["class"], q["choices"], True)
                ok = True
            except errors.user_errors():
                ok = False                              # no longer fits: ask for this level below
        if not ok:
            done = open_level_up(parent, name, q.get("class"), q.get("choices") or None, True,
                                 tr("Edit levels — {0} (level {1})", name, q["level"]))
            if not done:
                if dialogs.confirm(parent, tr("Cancel the edit? The character goes back exactly as it was before."),
                                   tr("Edit levels"), tr("Restore original")):
                    errors.guard(chars.cancel_edit, name)
                    notify.warn(tr("Edit cancelled - original restored."))
                    return False
                continue                                # keep editing this level
        i += 1
    errors.guard(chars.finish_edit, name)
    notify.good(tr("{0} was rebuilt from level {1}.", name, queue[0]["level"]))
    return True


# ---------------------------------------------------------------------- menu actions
def _selected() -> Optional[str]:
    name = rt().selected_name
    if not name:
        notify.warn(tr("Select a character first."))
    return name


@action("characters.level_up", "Level up selected character…", menu="Characters")
def level_up_selected(window):
    name = _selected()
    if name:
        open_level_up(window, name)


@action("characters.edit_levels", "Edit levels of selected character…", menu="Characters")
def edit_levels_selected(window):
    name = _selected()
    if name:
        open_edit_levels(window, name)
