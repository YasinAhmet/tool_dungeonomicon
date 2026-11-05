"""Choosing from long lists: PickList (pick up to N, with folders and search) and FoldSelect (a grouped dropdown).

Every entry can show a description on hover; by default rules.describe.describe_name (skills, languages, items,
spells, feats...). Options are names, or dicts {'value', 'label', 'group'}; a group may be a path of folders
(['1st level', 'Evocation']).

    pl = PickList(options=pool, count=2, selected=[...], on_change=lambda chosen: ...)
    pl.chosen(); pl.done(); pl.set_options(new_pool)
    pl.set_taken({"Stealth"})        # chosen in another list: shown greyed out, can't be picked here
    pl.expand_all(False)             # fold every folder
    pl.hovered.connect(lambda value, text: ...)    # the entry under the mouse and its description

    fs = FoldSelect(groups=[{"title": "PHB", "items": ["Elf", "Dwarf"]}], value="Elf", on_change=...)
    fs.value(); fs.set_value("Dwarf")
"""
from typing import Callable, Dict, List, Optional, Sequence, Union

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QFrame, QLineEdit, QListWidget, QListWidgetItem, QPushButton, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)

from ...core.i18n import tr
from ...rules.describe import describe_name
from .common import label, row
from .icons import game_icon

Option = Union[str, Dict]
GROUP_ORDER = ["Standard", "Exotic", "Secret", "Rare", "Other"]


def norm(o: Option) -> Dict:
    return {"value": o, "label": o} if isinstance(o, str) else {"label": str(o.get("value")), **o}


def _cached(fn: Callable[[str], str]) -> Callable[[str], str]:
    cache: Dict[str, str] = {}

    def get(name: str) -> str:
        if name not in cache:
            try:
                cache[name] = fn(name) or ""
            except Exception:
                cache[name] = ""
        return cache[name]
    return get


def _path(o: Dict) -> tuple:
    g = o.get("group") or "Other"
    return tuple(g) if isinstance(g, (list, tuple)) else (g,)


class PickList(QWidget):
    """Pick up to `count` entries. Clicking a chosen entry unpicks it; picking past `count` drops the oldest.
    sort_groups=False keeps the folders in the order their first entry comes in."""
    changed = Signal(list)
    hovered = Signal(str, str)

    def __init__(self, options: Sequence[Option] = (), count: int = 1, selected: Sequence = (),
                 on_change: Optional[Callable[[list], None]] = None, detail: Optional[Callable[[str], str]] = describe_name,
                 search: bool = True, sort_groups: bool = True, parent=None):
        super().__init__(parent)
        self.count = count
        self._detail = _cached(detail) if detail else None
        self._sort_groups = sort_groups
        self._opts: List[Dict] = []
        self._chosen: List = []
        self._taken: set = set()
        self._open: set = set()
        self._closed: set = set()
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(3)
        self.query = QLineEdit()
        self.query.setPlaceholderText(tr("search…"))
        self.query.textChanged.connect(self._render)
        self.counter = label("", role="dim")
        self.top = row(self.query, self.counter)
        box.addLayout(self.top)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.setRootIsDecorated(False)
        self.tree.setIndentation(14)
        self.tree.setMouseTracking(True)
        self.tree.itemClicked.connect(self._clicked)
        self.tree.itemEntered.connect(self._hover)
        self.tree.itemExpanded.connect(lambda it: self._folded(it, True))
        self.tree.itemCollapsed.connect(lambda it: self._folded(it, False))
        box.addWidget(self.tree)
        self._search = search
        if on_change:
            self.changed.connect(on_change)
        self.set_options(options, selected)

    # ------------------------------------------------------------------ api
    def chosen(self) -> list:
        return list(self._chosen)

    def done(self) -> bool:
        return len(self._chosen) == self.count

    def set_options(self, options: Sequence[Option], selected: Optional[Sequence] = None):
        self._opts = [norm(o) for o in options]
        values = {o["value"] for o in self._opts}
        keep = self._chosen if selected is None else list(selected)
        self._chosen = [v for v in keep if v in values][: self.count]
        self.query.setVisible(self._search and len(self._opts) > 8)
        self._render()

    def set_chosen(self, values: Sequence, emit: bool = True):
        """Choose these values (those on offer, up to `count`)."""
        offered = {o["value"] for o in self._opts}
        self._chosen = [v for v in values if v in offered][: self.count]
        self._render()
        if emit:
            self.changed.emit(self.chosen())

    def set_taken(self, values):
        """Values another list already holds: greyed out and not pickable (a pick this list holds stays unpickable)."""
        values = set(values)
        if values != self._taken:
            self._taken = values
            self._render()

    def set_count(self, count: int):
        self.count = count
        self._chosen = self._chosen[-count:] if count else []
        self._render()

    def expand_all(self, on: bool = True):
        """Unfold (or fold) every folder, the ones holding a pick too."""
        keys = {p[:i] for p in (_path(o) for o in self._opts if o.get("group")) for i in range(1, len(p) + 1)}
        self._open, self._closed = (keys, set()) if on else (set(), keys)
        self._render()

    # ------------------------------------------------------------------ internals
    def _render(self):
        needle = self.query.text().strip().lower()
        shown = [o for o in self._opts if not needle or needle in o["label"].lower()]
        self.tree.blockSignals(True)                   # folders opened here aren't the user's doing
        self.tree.clear()
        grouped = any(o.get("group") for o in self._opts)
        self.tree.setRootIsDecorated(grouped)
        if grouped:
            self._fill(self.tree.invisibleRootItem(), shown, (), needle)
        else:
            for o in shown:
                self.tree.addTopLevelItem(self._item(o))
        self.tree.blockSignals(False)
        n = len(self._chosen)
        self.counter.setText(("✓ " if n == self.count else "") + f"{n}/{self.count}")     # the words on hover: the row stays short
        self.counter.setToolTip(tr("{0}/{1} chosen", n, self.count))
        self.counter.setProperty("role", "good" if n == self.count else "dim")
        self.counter.style().polish(self.counter)

    def _fill(self, parent: QTreeWidgetItem, opts: List[Dict], key: tuple, needle: str):
        """The folders at depth len(key) under `parent` (each filled the same way), then the entries that end here."""
        groups: Dict[str, List[Dict]] = {}
        leaves = []
        for o in opts:
            p = _path(o)
            if len(p) > len(key):
                groups.setdefault(p[len(key)], []).append(o)
            else:
                leaves.append(o)
        names = list(groups)
        if self._sort_groups:
            rank = lambda g: GROUP_ORDER.index(g) if g in GROUP_ORDER else len(GROUP_ORDER)
            names.sort(key=lambda g: (rank(g), g))
        for g in names:
            items, k = groups[g], key + (g,)
            picked = sum(1 for o in items if o["value"] in self._chosen)
            head = QTreeWidgetItem([f"{tr(g)} ({len(items)})" + (f"  ·  {tr('{0} chosen', picked)}" if picked else "")])
            head.setData(0, Qt.UserRole, ("group", k))
            head.setFlags(Qt.ItemIsEnabled)
            parent.addChild(head)
            self._fill(head, items, k, needle)
            head.setExpanded(bool(needle) or k in self._open or (picked > 0 and k not in self._closed))
        for o in leaves:
            parent.addChild(self._item(o))

    def _folded(self, item: QTreeWidgetItem, opened: bool):
        kind, key = item.data(0, Qt.UserRole)
        if kind == "group":
            (self._open if opened else self._closed).add(key)
            (self._closed if opened else self._open).discard(key)

    def _item(self, o: Dict) -> QTreeWidgetItem:
        chosen = o["value"] in self._chosen
        taken = not chosen and o["value"] in self._taken
        it = QTreeWidgetItem([("✔ " if chosen else "    ") + tr(o["label"]) + ("  — " + tr("already chosen") if taken else "")])
        it.setData(0, Qt.UserRole, ("taken" if taken else "value", o["value"]))
        if chosen:
            it.setForeground(0, self.palette().link())
        if o.get("icon"):                              # a spell's action bar picture
            it.setIcon(0, game_icon(o["icon"], 14, "#c4b5fd"))
        if taken:
            it.setFlags(it.flags() & ~Qt.ItemIsEnabled)
        return it

    def _clicked(self, item: QTreeWidgetItem, _col: int):
        kind, value = item.data(0, Qt.UserRole)
        if kind == "group":
            item.setExpanded(not item.isExpanded())    # _folded remembers it
            return
        if kind == "taken":
            return
        if value in self._chosen:
            self._chosen.remove(value)
        else:
            self._chosen.append(value)
            while len(self._chosen) > self.count:
                self._chosen.pop(0)
        self._render()
        self.changed.emit(self.chosen())

    def _hover(self, item: QTreeWidgetItem, _col: int):
        kind, value = item.data(0, Qt.UserRole)
        if kind == "group":
            return
        text = tr(self._detail(str(value))) if self._detail else ""
        self.hovered.emit(str(value), text)
        if kind == "value" and text and not item.toolTip(0):
            item.setToolTip(0, f"{value}\n{text}"[:1500])


class FoldSelect(QPushButton):
    """A dropdown whose entries sit in foldable folders (races by book...), with a search box and hover descriptions.

    groups: [{'title': 'Player's Handbook', 'items': [name | {'value', 'label'}]}]; an untitled group is a plain list."""
    changed = Signal(object)

    def __init__(self, groups: Sequence[Dict] = (), value=None, on_change: Optional[Callable] = None,
                 detail: Optional[Callable[[str], str]] = describe_name, placeholder: str = "", parent=None):
        super().__init__(parent)
        self._placeholder = placeholder
        self._groups: List[Dict] = []
        self._value = value
        self._detail = _cached(detail) if detail else None
        self.setStyleSheet("text-align: left; padding-left: 6px;")
        self.clicked.connect(self._open_popup)
        if on_change:
            self.changed.connect(on_change)
        self.set_groups(groups)

    def value(self):
        return self._value

    def set_value(self, value, emit: bool = False):
        self._value = value
        self.setText(f"{tr(self._label_of(value)) if value not in (None, '') else (self._placeholder or tr('Choose…'))}  ▾")
        if emit:
            self.changed.emit(value)

    def set_groups(self, groups: Sequence[Dict]):
        self._groups = [{"title": g.get("title", ""), "items": [norm(i) for i in g["items"]]} for g in groups]
        self.set_value(self._value)

    def _label_of(self, value) -> str:
        for g in self._groups:
            for i in g["items"]:
                if i["value"] == value:
                    return i["label"]
        return str(value)

    def _open_popup(self):
        pop = _FoldPopup(self)
        pop.move(self.mapToGlobal(self.rect().bottomLeft()))
        pop.show()
        pop.query.setFocus()


class _FoldPopup(QFrame):
    def __init__(self, owner: FoldSelect):
        super().__init__(owner, Qt.Popup)
        self.owner = owner
        self.setObjectName("card")
        self.setMinimumWidth(max(owner.width(), 360))
        self.setMaximumHeight(520)
        box = QVBoxLayout(self)
        box.setContentsMargins(6, 6, 6, 6)
        self.query = QLineEdit()
        self.query.setPlaceholderText(tr("search…"))
        self.query.textChanged.connect(self._render)
        box.addWidget(self.query)
        self.list = QTreeWidget()
        self.list.setHeaderHidden(True)
        self.list.setMouseTracking(True)
        self.list.itemClicked.connect(self._clicked)
        self.list.itemEntered.connect(self._hover)
        box.addWidget(self.list)
        self.resize(self.minimumWidth(), 420)
        self._render()

    def _render(self):
        needle = self.query.text().strip().lower()
        self.list.clear()
        for g in self.owner._groups:
            items = [i for i in g["items"] if not needle or needle in i["label"].lower()]
            if not items:
                continue
            parent = None
            if g["title"]:
                parent = QTreeWidgetItem([f"{tr(g['title'])}  ({len(items)})"])
                parent.setFlags(Qt.ItemIsEnabled)
                parent.setData(0, Qt.UserRole, None)
                self.list.addTopLevelItem(parent)
            for i in items:
                it = QTreeWidgetItem([tr(i["label"])])
                it.setData(0, Qt.UserRole, ("value", i["value"]))
                (parent.addChild(it) if parent else self.list.addTopLevelItem(it))
                if i["value"] == self.owner._value:
                    self.list.setCurrentItem(it)
            if parent:
                parent.setExpanded(bool(needle) or any(i["value"] == self.owner._value for i in items) or len(self.owner._groups) <= 2)

    def _clicked(self, item, _col):
        data = item.data(0, Qt.UserRole)
        if not data:
            item.setExpanded(not item.isExpanded())
            return
        self.owner.set_value(data[1], emit=True)
        self.close()

    def _hover(self, item, _col):
        data = item.data(0, Qt.UserRole)
        if data and self.owner._detail and not item.toolTip(0):
            text = self.owner._detail(str(data[1]))
            if text:
                item.setToolTip(0, f"{data[1]}\n{tr(text)}"[:1500])


class SimpleList(QListWidget):
    """A plain list of (label, value) rows with the value kept on each row."""

    def set_rows(self, rows: Sequence, current=None):
        self.blockSignals(True)
        self.clear()
        for r in rows:
            lab, val = r if isinstance(r, tuple) else (r, r)
            it = QListWidgetItem(str(lab))
            it.setData(Qt.UserRole, val)
            self.addItem(it)
            if val == current:
                self.setCurrentItem(it)
        self.blockSignals(False)

    def value(self):
        it = self.currentItem()
        return it.data(Qt.UserRole) if it else None
