"""A creature's card (in the Inspector, or a creature window of its own), with the target the rolls resolve on above it: a monster's stat
block with one-click attacks, saves and spells, a player character's weapons, spells and sheet."""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QVBoxLayout, QWidget

from ....core import events
from ....core.i18n import tr
from ....services.battle import view as V
from ...errors import guard
from ...panel import Panel
from ...widgets.common import button, clear_layout, label, row, scroll
from .card import make_card, target_text
from .common import preview_area


class CardPanel(Panel):
    def build(self):
        self.focus = None            # the creature shown (None: none)
        self.prefs = {}              # choices kept from card to card: advantage, each character's spell
        self.card = None
        self.key = None
        self.target = label("", wrap=True)
        self.target.setTextFormat(Qt.RichText)
        self.clear_target = button("×", lambda: self.run(self.rt.battle.set_target, None), kind="flat", tip=tr("Clear the target"))
        self.clear_target.setStyleSheet("padding: 0 5px;")
        bar = row(self.target, self.clear_target)
        bar.setStretchFactor(self.target, 1)
        self.layout().setContentsMargins(0, 0, 0, 0)
        self.layout().addLayout(bar)
        self.body = QWidget()
        self.inner = QVBoxLayout(self.body)
        self.inner.setContentsMargins(0, 0, 6, 0)
        self.inner.setSpacing(4)
        self.area = scroll(self.body)
        self.layout().addWidget(self.area, 1)
        self.on(events.BATTLE, self.refresh)
        self.on(events.CHARACTERS, self.refresh)

    def show_creature(self, cid):
        """Show this creature's card (None: none)."""
        if cid != self.focus or self.card is None:
            self.focus = cid
            guard(self.refresh)

    def refresh(self):
        v = V.battle_view()
        c = V.find(v, self.focus) if self.focus else None
        tt = target_text(v)
        self.target.setText(tt or "")                       # (the how-to is on the Inspector's heading: no line of its own)
        self.target.setVisible(bool(tt))
        self.clear_target.setVisible(bool(tt))
        key = (c["id"], c["kind"], c.get("monster"), c.get("character"), tuple(v.get("picked") or []), v["status"],
               self.prefs.get("_no_bar") == c["id"]) if c else None
        if key == self.key and self.card is not None:
            self.card.update_live(c, v)
            return
        same = self.key is not None and key is not None and self.key[0] == key[0]
        pos = self.area.verticalScrollBar().value() if same else 0
        self.key = key
        if not same:
            preview_area(None)
        clear_layout(self.inner)
        self.card = None
        if c:
            self.card = make_card(c, v, self.prefs)
            self.inner.addWidget(self.card)
        self.inner.addStretch(1)
        QTimer.singleShot(0, self.area, lambda: self.area.verticalScrollBar().setValue(pos))
