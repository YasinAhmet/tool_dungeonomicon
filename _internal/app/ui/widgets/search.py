"""A faceted search over monsters or items (app.services.library.search): query, sort, grouping folders, facet
check boxes, number ranges, a results tree and the selected entry's text.

    SearchPanel("monsters",
        columns=[("name", tr("Name"), 0), ("cr", tr("CR"), 46), ("type", tr("Type"), 90)],
        sorts=["cr", "name", "hp"], default_sort="cr",
        groups={tr("CR"): "cr", tr("Type"): "type"}, default_group="cr", subgroup="kind",
        compact=True,                       # filters fold away behind a button
        pinned=lambda r: r["src"] == "Custom", pinned_label="CUSTOMS",
        remember="workshop",                # every folder starts folded; which are open is kept in the settings
        actions=lambda bar, selected: bar.addWidget(button(tr("Add"), lambda: add(selected()))),
        on_double=lambda r: add(r), draggable=lambda r: {"kind": "monster", "id": r["id"]})

Selecting a row also shows the entry in the Inspector window (app.ui.selection). Dragged rows carry JSON under
the MIME type DRAG_MIME.
"""
import json
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from PySide6.QtCore import QMimeData, Qt, QTimer
from PySide6.QtGui import QDrag
from PySide6.QtWidgets import (QCheckBox, QComboBox, QGridLayout, QLineEdit, QMenu, QScrollArea, QSplitter, QToolButton,
                               QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from ...core import events
from ...core.i18n import tr
from ...core.runtime import rt
from ...rules.describe import describe
from ...services import library
from ...services.battle.icons import CREATURES, ITEM_CATS, for_item
from ..errors import guard
from ..theme import COLORS
from .common import Combo, FlowLayout, amp, button, clear_layout, label, line_edit, row
from .icons import game_icon, icon_button
from .text import TextView, entry_tip

DRAG_MIME = "application/x-dungeonomicon"
SORT_LABELS = {"cr": "CR", "hp": "HP", "ac": "AC", "xp": "XP", "gp": "Cost", "wt": "Weight", "src": "Book", "book": "Book"}
TOP, MORE = 12, 80


class _Results(QTreeWidget):
    def __init__(self, owner: "SearchPanel"):
        super().__init__()
        self.owner = owner

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.owner._fit_columns()

    def startDrag(self, actions):
        it = self.currentItem()
        r = it and it.data(0, Qt.UserRole)
        if not r or not self.owner.draggable:
            return
        mime = QMimeData()
        mime.setData(DRAG_MIME, json.dumps(self.owner.draggable(r)).encode())
        mime.setText(r.get("name", ""))
        drag = QDrag(self)
        drag.setMimeData(mime)
        drag.exec(Qt.CopyAction)


class SearchPanel(QWidget):
    def __init__(self, kind: str, columns: Sequence[Tuple[str, str, int]], sorts: Sequence[str] = ("name",),
                 default_sort: str = "name", groups: Optional[Dict[str, str]] = None, default_group: str = "none",
                 subgroup: Optional[str] = None, compact: bool = False, hover_detail: bool = False,
                 pinned: Optional[Callable[[dict], bool]] = None, pinned_label: str = "PINNED",
                 actions: Optional[Callable] = None, on_double: Optional[Callable[[dict], None]] = None,
                 on_select: Optional[Callable[[dict], None]] = None, draggable: Optional[Callable[[dict], dict]] = None,
                 show_detail: bool = True, remember: str = "", parent=None):
        super().__init__(parent)
        self.kind, self.columns = kind, list(columns)
        self.groups = groups or {}
        self.subgroup, self.pinned, self.pinned_label = subgroup, pinned, pinned_label
        self.on_double, self.on_select, self.draggable = on_double, on_select, draggable
        self.hover_detail = hover_detail
        self.q, self.sort, self.group = "", default_sort, default_group if default_group in self.groups.values() else "none"
        self.sets: Dict[str, set] = {}
        self.ranges: Dict[str, List] = {}
        self.open_facets: Dict[str, bool] = {}
        self.more: set = set()
        self.facet_filter: Dict[str, str] = {}
        self.folded: set = set()             # folders the user closed (pinned, open by default) or opened (the rest)
        self.remember = remember                # a settings key: all folded by default, and the open ones kept per grouping
        self.pinned_open = not remember
        if remember:
            kept = self._kept()
            self.group = kept.get("group") if kept.get("group") in self.groups.values() else self.group
            self.folded = set((kept.get("open") or {}).get(self.group) or [])
        self.data: Optional[dict] = None
        self._selected: Optional[dict] = None
        self._tips: Dict[str, str] = {}

        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(4)
        self.query = line_edit(placeholder=tr("search…"), tip=tr(library.SEARCH_SYNTAX))
        self._debounce = QTimer(self, singleShot=True, interval=200)
        self._debounce.timeout.connect(self._query_changed)
        self.query.textChanged.connect(lambda _t: self._debounce.start())
        self.sort_box = Combo()
        for s in sorts:
            shown = tr(SORT_LABELS.get(s, s.title()))
            self.sort_box.addItem(shown, s)
            self.sort_box.addItem("↓ " + shown, "-" + s)
        self.sort_box.setCurrentIndex(max(0, self.sort_box.findData(default_sort)))
        self.sort_box.currentIndexChanged.connect(lambda _i: self._set_sort(self.sort_box.currentData()))
        self.group_box = Combo()
        self.group_box.addItem(tr("no group"), "none")
        for lab, key in self.groups.items():
            self.group_box.addItem(tr("group: {0}", lab), key)
        self.group_box.setCurrentIndex(max(0, self.group_box.findData(self.group)))
        self.group_box.currentIndexChanged.connect(lambda _i: self._set_group(self.group_box.currentData()))
        self.group_box.setVisible(bool(self.groups))
        self.compact = compact
        self.count = label("", role="dim")
        if compact:                       # a narrow drawer: sort, group, filters and reset as pictures, their words on hover
            self.filters_btn = icon_button("filter", self._toggle_side, tr("Filters: narrow the list (type, size, book…)"),
                                           checked=False, color=COLORS["accent"])
            self.sort_btn = self._choice_button("⇅", self.sort_box, tr("Sort"))
            self.group_btn = self._choice_button("▤", self.group_box, tr("Group"))
            self.group_btn.setVisible(bool(self.groups))
            self.sort_box.setVisible(False)
            self.group_box.setVisible(False)
            box.addLayout(row(self.query, self.sort_box, self.group_box, self.sort_btn, self.group_btn, self.filters_btn,
                              icon_button("reset", self.reset, tr("Reset: clear the search and the filters")), self.count, spacing=1))
        else:
            self.filters_btn = button(tr("Filters"), self._toggle_side, checkable=True)
            self.filters_btn.setVisible(False)
            box.addLayout(row(self.query, self.sort_box, self.group_box, self.filters_btn,
                              button(tr("Reset"), self.reset), self.count))
        self.chips_host = QWidget()
        self.chips = FlowLayout(self.chips_host)
        box.addWidget(self.chips_host)

        self.facets_host = QWidget()
        self.facets = QVBoxLayout(self.facets_host)
        self.facets.setContentsMargins(0, 0, 4, 0)
        self.facets.setSpacing(2)
        self.facet_scroll = QScrollArea()
        self.facet_scroll.setWidgetResizable(True)
        self.facet_scroll.setWidget(self.facets_host)
        self.facet_scroll.setMinimumWidth(190)
        self.facet_scroll.setVisible(not compact)

        self.results = _Results(self)
        self.results.setColumnCount(len(self.columns))
        self.results.setHeaderLabels([c[1] for c in self.columns])
        self.results.setRootIsDecorated(bool(self.groups) or bool(pinned))
        self.results.setAlternatingRowColors(True)
        self.results.setUniformRowHeights(True)
        self.results.setMouseTracking(True)
        self.results.setDragEnabled(bool(draggable))
        for i, (_k, _l, w) in enumerate(self.columns):
            if w:
                self.results.setColumnWidth(i, w)
        self.results.header().setStretchLastSection(False)
        self.results.header().setSectionResizeMode(0, self.results.header().ResizeMode.Stretch)
        self.results.currentItemChanged.connect(lambda cur, _prev: self._pick(cur))
        self.results.itemDoubleClicked.connect(self._double)
        self.results.itemEntered.connect(self._hover)
        self.results.itemExpanded.connect(lambda it: self._fold(it, True))
        self.results.itemCollapsed.connect(lambda it: self._fold(it, False))

        top = QSplitter(Qt.Vertical if compact else Qt.Horizontal)     # narrow: the filters fold out above the list
        top.addWidget(self.facet_scroll)
        top.addWidget(self.results)
        top.setStretchFactor(1, 1)
        top.setSizes([220, 600])
        self.action_bar = row()
        if actions:
            actions(self.action_bar, self.selected)
        self.detail = TextView(heading_first_line=True)
        self.detail.setPlaceholderText(tr("Select an entry to read it."))
        detail_box = QWidget()
        dl = QVBoxLayout(detail_box)
        dl.setContentsMargins(0, 0, 0, 0)
        dl.addLayout(self.action_bar)
        dl.addWidget(self.detail)
        self.reads = show_detail and not hover_detail       # the text below the list: shown once an entry is picked (no empty pane)
        self.detail.setVisible(False)
        if compact:
            self.detail.setMaximumHeight(160)
        main = QSplitter(Qt.Vertical)
        main.addWidget(top)
        main.addWidget(detail_box)
        main.setStretchFactor(0, 3)
        main.setStretchFactor(1, 1)
        box.addWidget(main, 1)
        unsub = rt().bus.subscribe(events.RULES, lambda: guard(self.reload))
        self.destroyed.connect(lambda *_: unsub())
        self.reload()

    # ------------------------------------------------------------------ api
    def selected(self) -> Optional[dict]:
        return self._selected

    def set_query(self, q: str):
        self.query.setText(q)
        self._query_changed()

    def reload(self):
        many = self.group != "none"
        self.data = library.search(self.kind, self.q, self.sets, {k: tuple(v) for k, v in self.ranges.items()},
                                   self.sort, limit=4000 if many else 400)
        self._render_all()

    def save_state(self) -> dict:
        """What a window remembers of its search in a layout."""
        return {"q": self.q, "sort": self.sort, "group": self.group, "sets": {k: sorted(v) for k, v in self.sets.items()},
                "ranges": dict(self.ranges)}

    def restore_state(self, state: dict):
        self.q = state.get("q", "")
        self.query.blockSignals(True)
        self.query.setText(self.q)
        self.query.blockSignals(False)
        self.sort = state.get("sort", self.sort)
        self.sort_box.blockSignals(True)
        self.sort_box.setCurrentIndex(max(0, self.sort_box.findData(self.sort)))
        self.sort_box.blockSignals(False)
        self.group = state.get("group", self.group)
        if self.remember:
            self.folded = set((self._kept().get("open") or {}).get(self.group) or [])
        self.group_box.blockSignals(True)
        self.group_box.setCurrentIndex(max(0, self.group_box.findData(self.group)))
        self.group_box.blockSignals(False)
        self.sets = {k: set(v) for k, v in (state.get("sets") or {}).items()}
        self.ranges = {k: list(v) for k, v in (state.get("ranges") or {}).items()}
        guard(self.reload)

    def reset(self):
        self.q = ""
        self.query.blockSignals(True)
        self.query.clear()
        self.query.blockSignals(False)
        self.sets, self.ranges, self.facet_filter = {}, {}, {}
        self.folded.clear()
        self._keep()
        guard(self.reload)

    # ------------------------------------------------------------------ changes
    def _query_changed(self):
        self.q = self.query.text()
        guard(self.reload)

    def _set_sort(self, s):
        self.sort = s
        guard(self.reload)

    def _set_group(self, g):
        self.group = g
        self.folded = set((self._kept().get("open") or {}).get(g) or []) if self.remember else set()
        self._keep()
        guard(self.reload)

    def _toggle(self, key: str, value: str):
        s = self.sets.setdefault(key, set())
        s.symmetric_difference_update({value})
        if not s:
            del self.sets[key]
        guard(self.reload)

    def _set_range(self, key: str, i: int, text: str):
        cur = self.ranges.get(key, ["", ""])
        cur[i] = text.strip()
        if not cur[0] and not cur[1]:
            self.ranges.pop(key, None)
        else:
            self.ranges[key] = cur
        guard(self.reload)

    def _toggle_side(self):
        self.facet_scroll.setVisible(not self.facet_scroll.isVisible())
        self.filters_btn.setChecked(self.facet_scroll.isVisible())

    def _choice_button(self, glyph: str, box: QComboBox, what: str) -> QToolButton:
        """A small button with a menu of a combo box's choices (the combo stays, hidden, holding the value)."""
        b = QToolButton()
        b.setText(glyph)
        b.setProperty("kind", "flat")
        b.setAutoRaise(True)
        b.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(b)

        def fill():
            menu.clear()
            for i in range(box.count()):
                a = menu.addAction(box.itemText(i), lambda i=i: box.setCurrentIndex(i))
                a.setCheckable(True)
                a.setChecked(i == box.currentIndex())
        menu.aboutToShow.connect(fill)
        b.setMenu(menu)
        tip = lambda: b.setToolTip(f"{what}: {box.currentText()}")     # noqa: E731
        box.currentIndexChanged.connect(lambda _i: tip())
        tip()
        return b

    # Columns a narrow list drops first (the name keeps at least NAME_ROOM px)
    DROP_FIRST, NAME_ROOM = ("src", "type", "size", "book"), 110

    def _fit_columns(self):
        """A narrow list hides columns (the book, the type, then from the right) rather than squeezing the names away."""
        tree = self.results
        fixed = [(i, k, w) for i, (k, _l, w) in enumerate(self.columns) if w]
        order = sorted(fixed, key=lambda c: (c[1] not in self.DROP_FIRST, -c[0]))
        hidden, room = set(), tree.viewport().width() - sum(w for _i, _k, w in fixed)
        for i, _k, w in order:
            if room >= self.NAME_ROOM:
                break
            hidden.add(i)
            room += w
        for i, _k, _w in fixed:
            if tree.isColumnHidden(i) != (i in hidden):
                tree.setColumnHidden(i, i in hidden)

    # ------------------------------------------------------------------ drawing
    def _render_all(self):
        d = self.data
        words = tr("{0} {1}", f"{d['total']:,}", tr(self.kind)) + \
            (tr(" · showing {0}", len(d["rows"])) if d["total"] > len(d["rows"]) else "")
        self.count.setText(f"{d['total']:,}" if self.compact else words)
        self.count.setToolTip(words)
        self._render_chips()
        self._render_facets()
        self._render_rows()

    def _render_chips(self):
        clear_layout(self.chips)
        labels = {f["key"]: (f["title"], {v[0]: v[2] for v in f["values"]}) for f in self.data["facets"]}
        for key, vals in self.sets.items():
            title, names = labels.get(key, (key, {}))
            for v in sorted(vals):
                self.chips.addWidget(button(f"{tr(title)}: {tr(names.get(v, v))} ×", lambda k=key, v=v: self._toggle(k, v), kind="flat"))
        for key, (lo, hi) in self.ranges.items():
            self.chips.addWidget(button(f"{key}: {lo}–{hi} ×", lambda k=key: (self.ranges.pop(k, None), guard(self.reload)), kind="flat"))
        self.chips_host.setVisible(self.chips.count() > 0)

    def _render_facets(self):
        pos = self.facet_scroll.verticalScrollBar().value()
        clear_layout(self.facets)
        grid = QGridLayout()
        grid.setSpacing(3)
        for i, n in enumerate(self.data["numbers"]):
            cur = self.ranges.get(n["key"], ["", ""])
            grid.addWidget(label(tr(n["title"])), i, 0)
            for j in (0, 1):
                e = QLineEdit(str(cur[j] or ""))
                e.setPlaceholderText(tr("max") if j else tr("min"))
                e.setFixedWidth(52)
                e.editingFinished.connect(lambda k=n["key"], j=j, e=e: self._set_range(k, j, e.text()))
                grid.addWidget(e, i, 1 + j)
        self.facets.addLayout(grid)
        for f in self.data["facets"]:
            opened = self.open_facets.get(f["key"], f["open"]) or bool(f["chosen"])
            live = sum(1 for v in f["values"] if v[1] > 0)
            head = QToolButton()
            head.setText(amp(("▾ " if opened else "▸ ") + tr(f["title"])) + (f"  ({len(f['chosen'])})" if f["chosen"] else "") + f"   {live}")
            head.setProperty("kind", "flat")
            head.setToolButtonStyle(Qt.ToolButtonTextOnly)
            head.setStyleSheet("text-align: left;")
            head.clicked.connect(lambda _c=False, k=f["key"], o=opened: (self.open_facets.__setitem__(k, not o), self._render_facets()))
            self.facets.addWidget(head)
            if not opened:
                continue
            vals = f["values"]
            if len(vals) > 14 and f["sorted_by_count"]:
                fs = line_edit(self.facet_filter.get(f["key"], ""), tr("filter…"))
                fs.editingFinished.connect(lambda k=f["key"], fs=fs: (self.facet_filter.__setitem__(k, fs.text()), self._render_facets()))
                self.facets.addWidget(fs)
                needle = self.facet_filter.get(f["key"], "").lower()
                if needle:
                    vals = [v for v in vals if needle in str(v[2]).lower() or v[0] in f["chosen"]]
            limit = MORE if f["key"] in self.more or self.facet_filter.get(f["key"]) else TOP
            for value, n, lab in vals[:limit]:
                cb = QCheckBox(amp(f"{tr(str(lab))}  ({n})"))
                pic = (CREATURES.get(str(value).lower()) if self.kind == "monsters" and f["key"] == "type"
                       else ITEM_CATS.get(str(value)) if self.kind == "items" and f["key"] == "cat" else None)
                if pic:                                         # the same pictures as the folders
                    cb.setIcon(game_icon(pic, 14, "#cbd5e1"))
                cb.setChecked(value in f["chosen"])
                cb.toggled.connect(lambda _on, k=f["key"], v=value: self._toggle(k, v))
                self.facets.addWidget(cb)
            if len(vals) > limit:
                self.facets.addWidget(button(tr("+{0} more", len(vals) - limit),
                                             lambda k=f["key"]: (self.more.add(k), self._render_facets()), kind="flat"))
        self.facets.addStretch(1)
        bar = self.facet_scroll.verticalScrollBar()
        QTimer.singleShot(0, bar, lambda: bar.setValue(pos))       # (bar as context: skipped if the window closed)

    def _render_rows(self):
        tree = self.results
        tree.blockSignals(True)
        tree.clear()
        rows = self.data["rows"]
        pinned = [r for r in rows if self.pinned and self.pinned(r)]
        rest = [r for r in rows if not (self.pinned and self.pinned(r))]
        searching = bool(self.q.strip())
        if pinned:
            folder = self._folder(f"{tr(self.pinned_label)}  ({len(pinned)})", "#pinned")
            tree.addTopLevelItem(folder)
            for r in pinned:
                folder.addChild(self._row(r))
            folder.setExpanded(searching or self._open("#pinned"))
        if self.group != "none":
            by: Dict[str, List[dict]] = {}
            for r in rest:
                by.setdefault(str(r.get(self.group)), []).append(r)
            for k, items in by.items():
                folder = self._folder(f"{'CR ' if self.group == 'cr' else ''}{tr(k)}  ({len(items)})", k)
                pic = ITEM_CATS.get(k) if self.kind == "items" else CREATURES.get(k.lower()) if self.kind == "monsters" else None
                if pic:                                         # Weapon, Potion... / Undead, Beast...: their picture
                    folder.setIcon(0, game_icon(pic, 14, "#cbd5e1"))
                tree.addTopLevelItem(folder)
                if self.subgroup and self.group == "cr":
                    subs: Dict[str, List[dict]] = {}
                    for r in items:
                        subs.setdefault(str(r.get(self.subgroup)), []).append(r)
                    for sk in sorted(subs):
                        sub = self._folder(f"{tr(sk)}  ({len(subs[sk])})", f"{k}|{sk}")
                        pic = CREATURES.get(sk.lower()) if self.kind == "monsters" else None
                        if pic:                                 # Animal, Undead...: their picture
                            sub.setIcon(0, game_icon(pic, 14, "#cbd5e1"))
                        folder.addChild(sub)
                        for r in subs[sk]:
                            sub.addChild(self._row(r, icon=False))      # (the folder shows the kind)
                        sub.setExpanded(searching or self._open(f"{k}|{sk}"))
                else:
                    for r in items:
                        folder.addChild(self._row(r))
                folder.setExpanded(searching or self._open(k))
        else:
            for r in rest:
                tree.addTopLevelItem(self._row(r))
        tree.blockSignals(False)

    def _folder(self, text: str, key: str) -> QTreeWidgetItem:
        it = QTreeWidgetItem([text])
        it.setData(0, Qt.UserRole + 1, key)
        it.setFirstColumnSpanned(True)
        it.setFlags(Qt.ItemIsEnabled)
        f = it.font(0)
        f.setBold(True)
        it.setFont(0, f)
        return it

    def _row(self, r: dict, icon: bool = True) -> QTreeWidgetItem:
        it = QTreeWidgetItem([tr(str(r.get(k, ""))) if k in ("type", "rarity", "kind", "cat") else str(r.get(k, ""))
                              for k, _l, _w in self.columns])
        it.setData(0, Qt.UserRole, r)
        if icon and self.kind in ("items", "monsters"):            # what kind of thing it is, at a glance
            slug = for_item(r.get("name", "")) if self.kind == "items" else CREATURES.get(str(r.get("type") or "").lower())
            if slug:
                it.setIcon(0, game_icon(slug, 14, "#cbd5e1"))
        flags = Qt.ItemIsEnabled | Qt.ItemIsSelectable
        if self.draggable:
            flags |= Qt.ItemIsDragEnabled
        it.setFlags(flags)
        if self._selected and self._selected.get("id") == r.get("id"):
            self.results.setCurrentItem(it)
        return it

    def _open(self, key: str) -> bool:
        if key == "#pinned" and self.pinned_open:       # the pinned folder is open unless closed
            return key not in self.folded
        return key in self.folded

    def _fold(self, it: QTreeWidgetItem, opened: bool):
        key = it.data(0, Qt.UserRole + 1)
        if key is None or self.q.strip():               # folders opened by a search aren't the user's choice
            return
        if key == "#pinned" and self.pinned_open:
            (self.folded.discard if opened else self.folded.add)(key)
        else:
            (self.folded.add if opened else self.folded.discard)(key)
        self._keep()

    def _kept(self) -> dict:
        kept = (rt().settings.get("search_folds") or {}).get(self.remember) if self.remember else None
        return kept if isinstance(kept, dict) else {}

    def _keep(self):
        """With `remember`: the grouping and its open folders into the settings, saved a moment later."""
        if not self.remember:
            return
        kept = self._kept()
        opened = dict(kept.get("open") or {})
        opened[self.group] = sorted(self.folded)
        rt().settings.setdefault("search_folds", {})[self.remember] = {"group": self.group, "open": opened}
        if not hasattr(self, "_saver"):
            self._saver = QTimer(self, singleShot=True, interval=800)
            self._saver.timeout.connect(lambda: guard(rt().save_config))
        self._saver.start()

    # ------------------------------------------------------------------ rows
    def _text(self, r: dict) -> str:
        if r["id"] not in self._tips:
            try:
                d = describe(self.kind, r["id"])
                self._tips[r["id"]] = f"{d['title']}\n{d['text']}"
            except ValueError as e:
                self._tips[r["id"]] = str(e)
        return self._tips[r["id"]]

    def _pick(self, it: Optional[QTreeWidgetItem]):
        r = it and it.data(0, Qt.UserRole)
        if not r:
            return
        self._selected = r
        if self.reads:
            self.detail.set_text(tr(self._text(r)))
            self.detail.show()
        from ..selection import show_content
        show_content(self.kind, r["id"])
        if self.on_select:
            guard(self.on_select, r)

    def _double(self, it: QTreeWidgetItem, _col: int):
        r = it.data(0, Qt.UserRole)
        if r and self.on_double:
            guard(self.on_double, r)

    def _hover(self, it: QTreeWidgetItem, _col: int):
        r = it.data(0, Qt.UserRole)
        if r and self.hover_detail and not it.toolTip(0):
            tip = entry_tip(self.kind, r["id"]) or tr(self._text(r))[:2000]
            for c in range(self.results.columnCount()):          # (the whole row: the name, its CR, its book...)
                it.setToolTip(c, tip)
