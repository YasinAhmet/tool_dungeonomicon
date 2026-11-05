"""The creation choices of an existing character (alignment, race, ability scores, background) for RESET ALL: the
creation wizard's own steps, filled from the character. Changing them makes the character again from level 0.

    ed = OriginEditor(origin, on_change)     # origin: levelup_flow.reset_start(name)["origin"]
    ed.check() -> problem text or None       ed.origin() -> the choices       ed.touched() -> changed since opened
"""
import json
from typing import Callable, Optional

from PySide6.QtWidgets import QWidget

from ....core.i18n import tr
from ....services.characters import creation_flow as CF
from ...widgets.common import col, combo, label, row, stretch, title
from .wizard import BackgroundStep, RaceStep, ScoresStep


class OriginEditor(QWidget):
    """Stands in for the creation wizard (lists, spec(), changed()) towards the steps it shows."""

    def __init__(self, origin: dict, on_change: Callable[[], None], parent=None):
        super().__init__(parent)
        self.lists = CF.lists()
        self._on_change = on_change
        self._quiet = True                              # the steps redrawing themselves isn't a change
        self.align = combo([(tr("—"), "")] + [(tr(a), a) for a in self.lists["alignments"]], current=origin.get("alignment") or "",
                           on_change=lambda _v: self.changed())
        self.steps = (RaceStep(self), ScoresStep(self), BackgroundStep(self))
        race, scores, background = self.steps
        race.load(origin)
        scores.load(origin.get("scores_method") or "manual", origin.get("scores") or {})
        background.load(origin)
        parts = [row(label(tr("Alignment")), self.align, stretch())]
        for st in self.steps:
            parts += [title(st.heading()), st]
        self.setLayout(col(*parts, spacing=6))
        self.check()
        self._start = self._key()
        self._quiet = False

    def spec(self) -> dict:
        out: dict = {"alignment": self.align.currentData() or ""}
        for st in self.steps:
            out.update(st.collect())
        return out

    def changed(self):
        if not self._quiet:
            self._on_change()

    def check(self) -> Optional[str]:
        """Bring the steps up to date with each other; the first problem (with its step), or None."""
        quiet, self._quiet = self._quiet, True
        try:
            for st in self.steps:
                st.ensure(self.spec())
        finally:
            self._quiet = quiet
        spec = self.spec()
        for st in self.steps:
            p = st.problem(spec)
            if p:
                return f"{st.heading()}: {tr(p)}"
        return None

    def _key(self) -> str:
        return json.dumps(self.spec(), sort_keys=True, default=str)

    def touched(self) -> bool:
        return self._key() != self._start

    def origin(self) -> dict:
        return self.spec()
