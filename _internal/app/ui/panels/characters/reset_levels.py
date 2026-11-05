"""RESET ALL: the creation choices (alignment, race, ability scores, background) and every level of the character from
the first to the last on one scrollable page, all editable. The choices start from the character as it is now;
changing the creation choices re-checks every level, changing a level re-checks the levels after it. Nothing is saved
until Apply.

    open_reset_levels(parent, name, creation=False) -> bool    # True when the character was rebuilt; creation=True
                                                               # opens with the creation choices unfolded
"""
import json
from typing import List, Optional

from PySide6.QtCore import QTimer
from PySide6.QtWidgets import QVBoxLayout

from ....core.i18n import tr
from ....core.runtime import rt
from ....services.characters import levelup_flow as LF
from ... import errors, notify
from ...dialogs import Dialog
from ...widgets.common import clear_layout, col, combo, hline, label, row, scroll, stretch, tool_button, widget
from .choices import ChoicesPanel, attempt
from .origin import OriginEditor


class _Origin:
    """The creation choices above the levels: a heading line (fold button, status) and the editor."""

    def __init__(self, owner: "ResetLevelsDialog", origin: dict, opened: bool):
        self.editor = OriginEditor(origin, lambda: owner.schedule(0))
        self.fold = tool_button("▸", self.toggle, tip=tr("Show or hide the creation choices"))
        head = label(tr("Creation — race, ability scores, background"), role="accent")
        f = head.font()
        f.setBold(True)
        head.setFont(f)
        self.status = label("", wrap=True)
        self.body = widget(QVBoxLayout())
        self.body.layout().setContentsMargins(22, 0, 0, 6)
        self.body.layout().addWidget(self.editor)
        self.card = widget(col(row(self.fold, head, self.status, stretch()), self.body, spacing=4))
        self.show_body(opened)

    def toggle(self):
        self.show_body(not self.body.isVisible())

    def show_body(self, on: bool):
        self.body.setVisible(on)
        self.fold.setText("▾" if on else "▸")

    def say(self, text: str, role: str):
        self.status.setText(text)
        self.status.setProperty("role", role)
        self.status.style().polish(self.status)
        if role == "warn":
            self.show_body(True)


class _Level:
    """One level: a heading line (fold button, level, class, status) and its choices (folded away once complete)."""

    def __init__(self, owner: "ResetLevelsDialog", i: int):
        self.i = i
        self.panel: Optional[ChoicesPanel] = None
        self.plan_key: Optional[str] = None
        self.opened: Optional[bool] = None             # None: open while it needs choices
        self.fold = tool_button("▸", self.toggle, tip=tr("Show or hide this level's choices"))
        head = label(tr("Level {0}", i + 1), role="accent")
        f = head.font()
        f.setBold(True)
        head.setFont(f)
        self.cls = combo([(tr(c), c) for c in owner.classes], current=owner.entries[i]["class"],
                         on_change=lambda v: owner.class_changed(i, v))
        self.status = label("", wrap=True)
        self.body = widget(QVBoxLayout())
        self.body.layout().setContentsMargins(22, 0, 0, 6)
        self.holder = self.body.layout()
        self.card = widget(col(hline(), row(self.fold, head, self.cls, self.status, stretch()), self.body, spacing=4))

    def toggle(self):
        self.opened = not self.body.isVisible()
        self.show_body(self.opened)

    def show_body(self, on: bool):
        self.body.setVisible(on)
        self.fold.setText("▾" if on else "▸")

    def say(self, text: str, role: str):
        self.status.setText(text)
        self.status.setProperty("role", role)
        self.status.style().polish(self.status)
        self.show_body(self.opened if self.opened is not None else role != "good")


class ResetLevelsDialog(Dialog):
    def __init__(self, parent, name: str, creation: bool = False):
        super().__init__(parent, tr("RESET ALL — {0}", name), 980, 760)
        self.name = name
        self.applied = False
        start = LF.reset_start(name)
        self.origin: Optional[dict] = None             # the last valid creation choices once changed, else None
        self.origin_problem: Optional[str] = None
        self.classes = start["classes"]
        self.entries: List[dict] = [{"class": e["class"], "choices": e.get("choices"),
                                     "subclass": (e.get("choices") or {}).get("subclass") or ""} for e in start["entries"]]
        for e in self.entries:
            if e["class"] not in self.classes:
                self.classes.append(e["class"])
        self.body.addWidget(label(tr("The creation choices, then every level from the first to the last, all rebuilt from the character "
                                     "as it is now. Change anything; what comes after re-checks itself. Gear, notes and the "
                                     "portrait stay. Nothing is saved until you press Apply."),
                                  role="dim", wrap=True))
        self.creation = _Origin(self, start["origin"], creation)
        self.levels = [_Level(self, i) for i in range(len(self.entries))]
        page = widget(col(self.creation.card, *[lv.card for lv in self.levels], stretch(), spacing=2))
        page.layout().setContentsMargins(0, 0, 8, 0)
        self.body.addWidget(scroll(page), 1)
        self.status = label("")
        self.buttons.insertWidget(0, self.status, 1)
        self.add_button(tr("Cancel"), self.reject)
        self.apply_btn = self.add_button(tr("Apply — rebuild the character"), self.submit, kind="danger")
        self.apply_btn.setEnabled(False)
        self._from = 0
        self._timer = QTimer(self, singleShot=True, interval=200)
        self._timer.timeout.connect(lambda: errors.guard(self.refresh))
        self.refresh()

    # ------------------------------------------------------------------ changes
    def schedule(self, start: int):
        self._from = min(self._from, start)
        self._timer.start()

    def class_changed(self, i: int, cls: str):
        self.entries[i] = {"class": cls, "choices": None, "subclass": ""}
        self.levels[i].plan_key = None
        self.schedule(i)

    def subclass_changed(self, i: int, sub: str):
        self.entries[i]["subclass"] = sub
        self.entries[i]["choices"] = None
        self.levels[i].plan_key = None
        self.schedule(i)

    def choices_changed(self, i: int):
        p = self.levels[i].panel
        if p is None:
            return
        self.entries[i]["choices"] = None if p.pending() else p.collect()
        self.entries[i]["subclass"] = p.subclass() or self.entries[i]["subclass"]
        self.schedule(i + 1)

    # ------------------------------------------------------------------ drawing
    def check_origin(self):
        """Re-check the creation choices. While they have a problem the levels keep standing on the last valid ones;
        a problem of choices left as they were (a character made by hand) only matters once they are changed."""
        ed = self.creation.editor
        problem, touched = ed.check(), ed.touched()
        self.origin_problem = problem if touched else None
        if not touched:
            self.origin = None
        elif not problem:
            self.origin = ed.origin()
        if self.origin_problem:
            self.creation.say(self.origin_problem, "warn")
        elif self.origin:
            self.creation.say("✔ " + tr("changed — the levels below follow the new choices"), "good")
        else:
            self.creation.say(tr("unchanged") + (f" ({problem})" if problem else ""), "dim")

    def refresh(self):
        self._timer.stop()
        start, self._from = self._from, len(self.entries)
        if start == 0:
            self.check_origin()
        for _round in range(len(self.entries) + 1):     # a level that turns out complete re-checks the ones after it
            chain = LF.reset_chain(self.name, [{"class": e["class"], "choices": e["choices"], "subclass": e["subclass"]}
                                               for e in self.entries], self.origin)
            filled = next((i for i, r in enumerate(chain) if i >= start and self.draw_level(i, r)), None)
            if filled is None:
                break
            start = filled + 1
        for i, r in enumerate(chain):
            self.levels[i].say(tr(r["problem"]) if r["problem"] else "✔ " + tr("complete"), "warn" if r["problem"] else "good")
        done = all(r["plan"] and not r["problem"] and self.entries[i]["choices"] for i, r in enumerate(chain))
        self.apply_btn.setEnabled(done and not self.origin_problem)
        open_at = next((i for i, r in enumerate(chain) if not r["plan"] or r["problem"] or not self.entries[i]["choices"]), -1)
        self.status.setText(tr("Fix the creation choices first.") if self.origin_problem and done
                            else tr("All {0} levels are complete.", len(self.entries)) if done
                            else tr("Level {0} still needs choices.", open_at + 1))
        self.status.setProperty("role", "good" if done and not self.origin_problem else "warn")
        self.status.style().polish(self.status)

    def draw_level(self, i: int, r: dict) -> bool:
        """Show a level's plan. True when its choices turned out complete just now (the later levels need a re-check)."""
        lv, e = self.levels[i], self.entries[i]
        if not r["plan"]:
            lv.panel, lv.plan_key = None, None
            clear_layout(lv.holder)
            lv.holder.addWidget(label(tr(r["problem"]) if r["problem"] else tr("Waiting for the previous levels…"), role="dim", wrap=True))
            return False
        key = json.dumps(r["plan"], sort_keys=True, default=str)
        if key != lv.plan_key:                          # the plan changed: rebuild its choices (keeping what still fits)
            lv.plan_key = key
            clear_layout(lv.holder)
            lv.panel = ChoicesPanel(r["plan"], self.name, e["subclass"], e["choices"] or None,
                                    on_change=lambda i=i: self.choices_changed(i),
                                    on_subclass=lambda sub, i=i: self.subclass_changed(i, sub))
            lv.holder.addWidget(lv.panel)
        if not e["choices"] and not lv.panel.pending():
            e["choices"] = lv.panel.collect()
            return True
        return False

    def submit(self):
        self.refresh()
        if not self.apply_btn.isEnabled():
            return
        ok, _c = attempt(self, rt().characters.reset_levels, self.name,
                         [{"class": e["class"], "choices": e["choices"]} for e in self.entries], self.origin)
        if ok:
            self.applied = True
            notify.good(tr("{0} was rebuilt level by level.", self.name))
            self.accept()


def open_reset_levels(parent, name: str, creation: bool = False) -> bool:
    """Modal RESET ALL (creation=True: the creation choices unfolded). Returns True when the character was rebuilt."""
    d = errors.guard(ResetLevelsDialog, parent, name, creation)
    if d is None:
        return False
    d.exec()
    return d.applied
