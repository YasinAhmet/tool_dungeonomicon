"""The feature library of the creature generator: every trait and action of the bestiary, folded by CR and creature
family. Hover or select to read; double-click (or Add) borrows it, adapted to the creature being edited."""
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QSplitter, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget

from ....core.i18n import tr
from ....rules import monster_gen as G
from ....services import monster_workshop as W
from ... import notify
from ...dialogs import Dialog
from ...errors import guard
from ...theme import COLORS
from ...widgets.common import button, combo, label, line_edit, row, stretch
from ...widgets.text import TextView

KIND = {"traits": "trait", "actions": "action", "bonus_actions": "bonus action", "reactions": "reaction",
        "legendary": "legendary action"}
KINDS = {"traits": "traits", "actions": "actions", "bonus_actions": "bonus actions", "reactions": "reactions",
         "legendary": "legendary actions"}
INDEX, FILL = Qt.UserRole, Qt.UserRole + 1


class FeatureLibrary(Dialog):
    def __init__(self, editor, want: str = ""):
        super().__init__(editor, tr("Feature library"), 1000, 680)
        self.editor = editor
        spec = editor.spec
        self.open = {spec["cr"], f"{spec['cr']}|{W.family_of(spec['type'])}"}
        self.added: set = set()
        self.tips: dict = {}
        self.query = line_edit(placeholder=tr("search features or creatures…"))
        self._debounce = QTimer(self, singleShot=True, interval=200)
        self._debounce.timeout.connect(self.draw)
        self.query.textChanged.connect(lambda _t: self._debounce.start())
        self.section = combo([(tr("all kinds"), "")] + [(tr(v), k) for k, v in KINDS.items()], want, on_change=lambda _v: self.draw())
        self.count = label("", role="dim")
        self.body.addLayout(row(self.query, self.section, self.count))
        self.body.addWidget(label(tr("Every trait and action of the bestiary, by CR and creature family. Select to read, "
                                     "double-click to add: attack bonuses, save DCs, damage and the creature's name are "
                                     "adapted to {0} (CR {1}).", spec["name"] or tr("this creature"), spec["cr"]),
                                  role="dim", wrap=True))
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels([tr("Feature"), tr("Kind · creature")])
        self.tree.setColumnWidth(0, 300)
        self.tree.setUniformRowHeights(True)
        self.tree.setMouseTracking(True)
        self.tree.itemExpanded.connect(self._expanded)
        self.tree.itemCollapsed.connect(lambda it: self.open.discard(it.data(0, FILL)[0]) if it.data(0, FILL) else None)
        self.tree.itemClicked.connect(self._clicked)
        self.tree.itemDoubleClicked.connect(lambda it, _c: self.add(it.data(0, INDEX)) if it.data(0, INDEX) is not None else None)
        self.tree.itemEntered.connect(self._hover)
        self.tree.currentItemChanged.connect(lambda cur, _p: self._read(cur))
        self.text = TextView(heading_first_line=True)
        self.text.setPlaceholderText(tr("Select a feature to read it."))
        self.add_btn = button(tr("Add to the creature"), lambda: self.add(self._current()), kind="primary")
        self.add_btn.setEnabled(False)
        side = QWidget()
        sl = QVBoxLayout(side)
        sl.setContentsMargins(0, 0, 0, 0)
        sl.addWidget(self.text, 1)
        sl.addLayout(row(stretch(), self.add_btn))
        split = QSplitter(Qt.Horizontal)
        split.addWidget(self.tree)
        split.addWidget(side)
        split.setStretchFactor(0, 3)
        split.setStretchFactor(1, 2)
        self.body.addWidget(split, 1)
        self.add_button(tr("Done"), self.accept, kind="primary", default=False)
        self.draw()
        self.query.setFocus()

    # ------------------------------------------------------------------ the tree
    def draw(self):
        needle = self.query.text().strip()
        n, tree = W.feature_tree(needle, self.section.currentData() or "")
        self.count.setText(tr("{0} features", f"{n:,}"))
        cr_now = self.editor.spec["cr"]
        t = self.tree
        t.setUpdatesEnabled(False)
        t.blockSignals(True)
        t.clear()
        for cr, fams in tree:
            total = sum(len(ix) for _f, ix in fams)
            top = self._folder([tr("CR {0}", cr) + (f"  ({tr('this creature')})" if cr == cr_now else ""), str(total)])
            if cr == cr_now:
                top.setForeground(0, self.palette().link())
            t.addTopLevelItem(top)
            for fam, ix in fams:
                key = f"{cr}|{fam}"
                f = self._folder([tr(fam), str(len(ix))])
                f.setData(0, FILL, (key, ix))
                f.addChild(QTreeWidgetItem([""]))          # filled when opened
                top.addChild(f)
                if key in self.open or (needle and n <= 120):
                    f.setExpanded(True)
                    self._fill(f)
            top.setData(0, FILL, (cr, None))
            top.setExpanded(cr in self.open or bool(needle and n <= 300))
        if not tree:
            t.addTopLevelItem(QTreeWidgetItem([tr("Nothing matches.")]))
        t.blockSignals(False)
        t.setUpdatesEnabled(True)

    def _folder(self, cols) -> QTreeWidgetItem:
        it = QTreeWidgetItem(cols)
        f = it.font(0)
        f.setBold(True)
        it.setFont(0, f)
        return it

    def _fill(self, folder: QTreeWidgetItem):
        key, ix = folder.data(0, FILL)
        if ix is None or (folder.childCount() and folder.child(0).data(0, INDEX) is not None):
            return
        folder.takeChildren()
        for i in ix[:400]:
            name, sec, _cr, _fam, mon = W.feature_row(i)
            it = QTreeWidgetItem([("✓ " if i in self.added else "") + name, f"{tr(KIND[sec])} · {mon}"])
            it.setData(0, INDEX, i)
            if i in self.added:
                it.setForeground(0, QColor(COLORS["good"]))
            folder.addChild(it)

    def _expanded(self, it: QTreeWidgetItem):
        data = it.data(0, FILL)
        if data:
            self.open.add(data[0])
            self._fill(it)

    def _clicked(self, it: QTreeWidgetItem, _col: int):
        if it.data(0, FILL):
            it.setExpanded(not it.isExpanded())

    def _current(self):
        it = self.tree.currentItem()
        return it.data(0, INDEX) if it else None

    def _tip(self, i: int) -> str:
        if i not in self.tips:
            self.tips[i] = guard(G.feature_text, i) or ""
        return self.tips[i]

    def _hover(self, it: QTreeWidgetItem, _col: int):
        i = it.data(0, INDEX)
        if i is not None and not it.toolTip(0):
            it.setToolTip(0, f"{W.feature_row(i)[0]}\n{tr(self._tip(i))}"[:1500])

    def _read(self, it):
        i = it.data(0, INDEX) if it else None
        self.add_btn.setEnabled(i is not None)
        if i is not None:
            self.text.set_text(f"{W.feature_row(i)[0]}\n{tr(self._tip(i))}")

    # ------------------------------------------------------------------ adding
    def add(self, i):
        if i is None:
            return
        r = guard(G.adapt_feature, i, self.editor.spec)
        if not r:
            return
        self.editor.add_entry(r["sec"], {"name": r["name"], "text": r["text"]})
        self.added.add(i)
        it = self.tree.currentItem()
        if it and it.data(0, INDEX) == i:
            it.setText(0, "✓ " + W.feature_row(i)[0])
            it.setForeground(0, QColor(COLORS["good"]))
        notify.good(tr("Added {0} ({1}), adapted to CR {2}.", r["name"], tr(KIND[r["sec"]]), self.editor.spec["cr"]))
