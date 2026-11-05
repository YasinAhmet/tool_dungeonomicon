"""The Props page of the Battle map's drawer: the map symbols (doors, stairs, windows, traps...) and top-down pictures
to dress the battle map - trees, rocks, chests, barrels, tables, campfires... Drag one onto a tile of the Battle map, or
click it and then click a tile; right-click pins it to the quick bar above the map. Props count as terrain (cover,
blocked tiles, difficult ground, light) and the players see them on the portal too."""
from PySide6.QtCore import QEvent
from PySide6.QtWidgets import QGridLayout, QWidget

from ....core.i18n import tr
from ....services.battle import props as P
from ....services.battle.drawing import SYMBOLS
from ...panel import Panel
from ...widgets.common import label, line_edit, scroll
from .assets import AssetButton, name

BUTTON_W, GAP = 86, 4


class PropsPanel(Panel):
    def build(self):
        self.search = line_edit(placeholder=tr("Search props…"))
        self.search.textChanged.connect(lambda _t: self.refresh())
        self.layout().addWidget(self.search)
        self.body = QWidget()
        self.grid = QGridLayout(self.body)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(GAP)
        self.area = scroll(self.body)
        self.area.viewport().installEventFilter(self)
        self.layout().addWidget(self.area, 1)
        self.layout().addWidget(label(tr(P.credits()), role="dim", wrap=True))
        self.groups, self.cols = [], 0

    def refresh(self):
        for head, buttons in self.groups:
            for w in [head] + buttons:
                w.setParent(None)
                w.deleteLater()
        want = self.search.text().strip().lower()
        cats = {}
        for key, cat in [(k, "Map symbols") for k in SYMBOLS] + [(c["key"], c["category"]) for c in P.catalog()]:
            if want and want not in name(key).lower() and want not in key and want not in tr(cat).lower():
                continue
            cats.setdefault(cat, []).append(key)
        self.groups = [(label(tr(cat), role="accent"), [AssetButton(key, compact=False) for key in keys]) for cat, keys in cats.items()]
        self.cols = 0
        self._lay_out()

    def eventFilter(self, obj, e):
        if obj is self.area.viewport() and e.type() == QEvent.Resize:
            self._lay_out()
        return super().eventFilter(obj, e)

    def _lay_out(self):
        """The buttons in as many columns as the window is wide: a plain grid, so the scroll area always knows its
        full height (a wrapping layout lost its last row under the next heading at some widths)."""
        cols = max(1, (self.area.viewport().width() + GAP) // (BUTTON_W + GAP))
        if cols == self.cols:
            return
        self.cols = cols
        while self.grid.count():
            self.grid.takeAt(0)
        for c in range(self.grid.columnCount()):
            self.grid.setColumnStretch(c, 0)
        for r in range(self.grid.rowCount()):
            self.grid.setRowStretch(r, 0)
        row = 0
        for head, buttons in self.groups:
            self.grid.addWidget(head, row, 0, 1, cols)
            row += 1
            for i, b in enumerate(buttons):
                self.grid.addWidget(b, row + i // cols, i % cols)
            row += (len(buttons) + cols - 1) // cols
        self.grid.setColumnStretch(cols, 1)                  # spare width and height go to the right and the bottom
        self.grid.setRowStretch(row, 1)
