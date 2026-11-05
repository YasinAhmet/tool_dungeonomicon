"""Small building blocks so every window is built the same way (and stays compact).

    row(button(tr("Roll"), self.roll, kind="primary"), stretch(), label(tr("Total"), role="dim"))
    col(title(tr("Hit points")), self.hp_bar)
    card(title(tr("Saves")), grid)                 # a raised box
    combo([(tr("Average HP"), "average"), (tr("Roll HP"), "roll")], on_change=self.set_mode)

Text passed in is shown as it is: translate it with tr() where you call these.
"""
from typing import Callable, Iterable, List, Optional, Sequence, Tuple, Union

from PySide6.QtCore import QEvent, QRect, QSize, Qt, QPoint, QTimer
from PySide6.QtGui import QAction
from PySide6.QtWidgets import (QBoxLayout, QCheckBox, QComboBox, QFrame, QGridLayout, QHBoxLayout, QLabel, QLayout, QLineEdit,
                               QMenu, QPushButton, QScrollArea, QSizePolicy, QSpinBox, QSplitter, QToolButton, QVBoxLayout,
                               QWidget, QWidgetAction, QWidgetItem)

from ...core.i18n import tr

Child = Union[QWidget, QLayout, None, int]          # an int is a fixed spacing; None is skipped


def _fill(box, children: Iterable[Child]):
    for c in children:
        if c is None:
            continue
        if isinstance(c, int):
            box.addSpacing(c)
        elif isinstance(c, QLayout):
            box.addLayout(c)
        elif isinstance(c, _Stretch):
            box.addStretch(c.factor)
        else:
            box.addWidget(c)
    return box


class _Stretch:
    def __init__(self, factor: int = 1):
        self.factor = factor


def stretch(factor: int = 1) -> _Stretch:
    return _Stretch(factor)


def row(*children: Child, spacing: int = 4, margins: int = 0) -> QHBoxLayout:
    box = QHBoxLayout()
    box.setSpacing(spacing)
    box.setContentsMargins(margins, margins, margins, margins)
    return _fill(box, children)


def col(*children: Child, spacing: int = 4, margins: int = 0) -> QVBoxLayout:
    box = QVBoxLayout()
    box.setSpacing(spacing)
    box.setContentsMargins(margins, margins, margins, margins)
    return _fill(box, children)


def widget(layout: QLayout) -> QWidget:
    w = QWidget()
    w.setLayout(layout)
    return w


def card(*children: Child, spacing: int = 4) -> QFrame:
    f = QFrame()
    f.setObjectName("card")
    f.setLayout(col(*children, spacing=spacing, margins=6))
    return f


def label(text: str = "", role: str = "", tip: str = "", wrap: bool = False, selectable: bool = False) -> QLabel:
    lab = QLabel(text)
    if role:
        lab.setProperty("role", role)
    if tip:
        lab.setToolTip(tip)
    if wrap:
        lab.setWordWrap(True)
    if selectable:
        lab.setTextInteractionFlags(Qt.TextSelectableByMouse)
    return lab


def title(text: str) -> QLabel:
    """A small upper-case section heading."""
    return label(text.upper(), role="title")


def amp(text: str) -> str:
    """Button and check box texts treat '&' as a shortcut marker: 'Armor & shield' must be written 'Armor && shield'."""
    return text.replace("&", "&&")


def button(text: str, on_click: Optional[Callable] = None, kind: str = "", tip: str = "", checkable: bool = False,
           width: int = 0) -> QPushButton:
    b = QPushButton(amp(text))
    if kind:
        b.setProperty("kind", kind)
    if tip:
        b.setToolTip(tip)
    if checkable:
        b.setCheckable(True)
    if width:
        b.setFixedWidth(width)
        if width <= 34:                                  # icon-sized buttons: the theme's padding would clip the text
            b.setStyleSheet("padding: 2px 0;")
    if on_click:
        b.clicked.connect(lambda *_: on_click())
    return b


def tool_button(text: str, on_click: Optional[Callable] = None, tip: str = "", kind: str = "flat") -> QToolButton:
    b = QToolButton()
    b.setText(amp(text))
    b.setProperty("kind", kind)
    b.setAutoRaise(True)
    if tip:
        b.setToolTip(tip)
    if on_click:
        b.clicked.connect(lambda *_: on_click())
    return b


def line_edit(text: str = "", placeholder: str = "", on_enter: Optional[Callable] = None, tip: str = "",
              width: int = 0) -> QLineEdit:
    e = QLineEdit(text)
    if placeholder:
        e.setPlaceholderText(placeholder)
    if tip:
        e.setToolTip(tip)
    if width:
        e.setFixedWidth(width)
    if on_enter:
        e.returnPressed.connect(lambda: on_enter())
    return e


def spin(value: int = 0, low: int = 0, high: int = 999, on_change: Optional[Callable[[int], None]] = None,
         width: int = 56, tip: str = "") -> QSpinBox:
    s = QSpinBox()
    s.setRange(low, high)
    s.setValue(value)
    s.setFixedWidth(width)
    s.setButtonSymbols(QSpinBox.NoButtons)
    if tip:
        s.setToolTip(tip)
    if on_change:
        s.valueChanged.connect(on_change)
    return s


def check(text: str, checked: bool = False, on_change: Optional[Callable[[bool], None]] = None, tip: str = "") -> QCheckBox:
    c = QCheckBox(amp(text))
    c.setChecked(checked)
    if tip:
        c.setToolTip(tip)
    if on_change:
        c.toggled.connect(on_change)
    return c


GROUP_ROLE = Qt.UserRole + 41          # a combo entry's folder (its sourcebook...), set by 3-tuple items
MENU_AT = 20                           # a dropdown longer than this opens as a menu of folders that unfold on hover
FOLDER_AT = 30                         # a folder longer than this is split again (A – F, G – M...)
SEARCH_SHOWN = 40                      # search results listed at most
MAX_FOLDERS = 12                       # more folders than this: the ones of one or two entries share an 'Others' folder
OTHERS = object()


class Combo(QComboBox):
    """A dropdown that stays short: past MENU_AT entries it opens as a menu with a search line and folders that unfold
    on hover - by the entries' groups (sourcebooks: items given as (label, value, group)), by the greyed heading lines
    of the list, or else in runs (A – C, D – F... for an alphabetical list, '0 – 2', '3 – 8'... for any other).
    Entries before the first folder that stand for 'nothing chosen' (Automatic, — none —, any class) stay on top."""

    def showPopup(self):
        if self.count() <= MENU_AT:
            return super().showPopup()
        _ComboMenu(self).exec(self.mapToGlobal(QPoint(0, self.height())))

    def pick(self, i: int):
        if i != self.currentIndex():
            self.setCurrentIndex(i)
        self.activated.emit(i)
        self.textActivated.emit(self.itemText(i))


class _Entry:
    __slots__ = ("index", "text", "group", "tip")

    def __init__(self, index: int, text: str, group: str, tip: str):
        self.index, self.text, self.group, self.tip = index, text, group, tip


def _runs(entries: List[_Entry], per: int) -> List[Tuple[str, List[_Entry]]]:
    """Split a long list into folders of about `per`: by first letter when it is alphabetical (a letter is never cut
    in two), else in order, each named by its first and last entry."""
    keys = [e.text.strip().lower() for e in entries]
    out: List[Tuple[str, List[_Entry]]] = []
    if keys == sorted(keys):
        letters: dict = {}
        for e, k in zip(entries, keys):
            letters.setdefault((k[:1] or "?").upper(), []).append(e)
        cur, first, last = [], "", ""
        for letter, es in letters.items():
            if cur and len(cur) + len(es) > per and len(cur) >= per // 2:
                out.append((first if first == last else f"{first} – {last}", cur))
                cur = []
            if not cur:
                first = letter
            cur += es
            last = letter
        if cur:
            out.append((first if first == last else f"{first} – {last}", cur))
        if len(out) > 1:
            return out
        out = []                                              # all under one letter: in order instead
    short = lambda t: t if len(t) <= 18 else t[:17].rstrip() + "…"
    n = max(1, -(-len(entries) // per))
    size = -(-len(entries) // n)
    for i in range(0, len(entries), size):
        part = entries[i:i + size]
        name = short(part[0].text) if len(part) == 1 else f"{short(part[0].text)} – {short(part[-1].text)}"
        out.append((name, part))
    return out


class _ComboMenu(QMenu):
    def __init__(self, box: Combo):
        super().__init__(box)
        self.box = box
        self.setToolTipsVisible(True)
        self.setMinimumWidth(box.width())
        model = box.model()
        heading = ""
        top: List[_Entry] = []
        folders: dict = {}                                     # group -> entries, in the order they first come
        for i in range(box.count()):
            text, data = box.itemText(i), box.itemData(i)
            enabled = bool(model.flags(model.index(i, box.modelColumn())) & Qt.ItemIsEnabled)
            if not enabled and data is None:                   # a greyed heading line ('— Voice channels —')
                heading = text.strip("—- ").strip()
                continue
            e = _Entry(i, text, str(box.itemData(i, GROUP_ROLE) or heading or ""), str(box.itemData(i, Qt.ToolTipRole) or ""))
            if e.group:
                folders.setdefault(e.group, []).append(e)
            elif not folders and not data:                     # 'Automatic', '— none —', 'any level'...
                top.append(e)
            else:
                folders.setdefault("", []).append(e)
        self.entries = top + [e for es in folders.values() for e in es]
        if len([g for g in folders if g]) < 2:                 # no real folders: cut the list in runs
            rest = [e for es in folders.values() for e in es]
            folders = dict(_runs(rest, max(12, -(-len(rest) // 10))))
        else:
            if "" in folders:                                  # a few loose entries among folders: on top as well
                top += folders.pop("")
            if len(folders) > MAX_FOLDERS:                     # the books with a race or two each: one folder of them
                small = [g for g, es in folders.items() if len(es) < 3]
                if len(small) > 1:
                    others = sorted((e for g in small for e in folders.pop(g)), key=lambda e: e.text.lower())
                    folders[OTHERS] = others

        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("search…"))
        self.search.setClearButtonEnabled(True)
        self.search.textChanged.connect(self._filter)
        self.search.installEventFilter(self)
        holder = QWidget()
        holder.setLayout(row(self.search, margins=3))
        field = QWidgetAction(self)
        field.setDefaultWidget(holder)
        self.addAction(field)
        self.browse: List[QAction] = [self.addSeparator()]
        for e in top:
            self.browse.append(self._entry_action(e, self))
        if top and folders:
            self.browse.append(self.addSeparator())
        for name, es in folders.items():
            self.browse.append(self._folder(tr("Others") if name is OTHERS else name, es, self, tagged=name is OTHERS))
        self.results: List[QAction] = []
        QTimer.singleShot(0, self.search.setFocus)

    def _entry_action(self, e: _Entry, menu: QMenu, suffix: str = "") -> QAction:
        a = menu.addAction(self.box.itemIcon(e.index), amp(e.text) + suffix)
        if e.tip:
            a.setToolTip(e.tip)
        if e.index == self.box.currentIndex():
            f = a.font()
            f.setBold(True)
            a.setFont(f)
        a.triggered.connect(lambda _=False, i=e.index: (self.close(), self.box.pick(i)))
        return a

    def _folder(self, name: str, entries: List[_Entry], parent: QMenu, tagged: bool = False) -> QAction:
        """A submenu of entries; `tagged` shows each one's own group on its right (the Others folder)."""
        sub = QMenu(f"{amp(name)}  ({len(entries)})", parent)
        sub.setToolTipsVisible(True)
        if len(entries) > FOLDER_AT:
            for part, es in _runs(entries, max(12, -(-len(entries) // 6))):
                self._folder(part, es, sub, tagged)
        else:
            for e in entries:
                self._entry_action(e, sub, f"\t{amp(e.group)}" if tagged and e.group else "")
        a = parent.addMenu(sub)
        if any(e.index == self.box.currentIndex() for e in entries):
            f = a.font()
            f.setBold(True)
            a.setFont(f)
        return a

    def _filter(self, text: str):
        needle = text.strip().lower()
        for a in self.results:
            self.removeAction(a)
        self.results = []
        for a in self.browse:
            a.setVisible(not needle)
        if not needle:
            return
        found = [e for e in self.entries if needle in e.text.lower() or needle in e.group.lower()]
        found.sort(key=lambda e: (e.text.lower() != needle, not e.text.lower().startswith(needle)))   # the name, then names starting with it
        self.results.append(self.addSeparator())
        for e in found[:SEARCH_SHOWN]:
            self.results.append(self._entry_action(e, self, f"\t{amp(e.group)}" if e.group else ""))
        if len(found) > SEARCH_SHOWN:
            more = self.addAction(tr("… {0} more, type more of the name", len(found) - SEARCH_SHOWN))
            more.setEnabled(False)
            self.results.append(more)
        if not found:
            none = self.addAction(tr("Nothing matches"))
            none.setEnabled(False)
            self.results.append(none)
        if found:
            self.setActiveAction(self.results[1])

    def eventFilter(self, obj, ev):
        if obj is self.search and ev.type() == QEvent.KeyPress and ev.key() in (Qt.Key_Return, Qt.Key_Enter):
            act = self.activeAction()
            if act is None or act not in self.results or not act.isEnabled():
                act = next((a for a in self.results if a.isEnabled() and not a.isSeparator()), None)
            if act is not None:
                act.trigger()
            return True
        return super().eventFilter(obj, ev)


def combo(items: Sequence[Union[str, Tuple]] = (), current=None,
          on_change: Optional[Callable[[object], None]] = None, tip: str = "", width: int = 0) -> QComboBox:
    """items: labels, (label, value) pairs or (label, value, group) - a long list opens in folders by group (Combo).
    on_change gets the value."""
    c = Combo()
    set_items(c, items, current)
    if tip:
        c.setToolTip(tip)
    if width:
        c.setFixedWidth(width)
    if on_change:
        c.currentIndexChanged.connect(lambda _i: on_change(c.currentData()))
    return c


def book_items(records: Iterable[dict], label: Callable[[dict], str] = lambda r: r["name"],
               value: Callable[[dict], object] = lambda r: r["name"]) -> List[Tuple[str, object, str]]:
    """(label, value, book) for records with a 'source', in book order (the Player's Handbook, then things made in the
    app, then the other books by name; by label inside a book): a long dropdown of them opens in folders by book."""
    from ...rules.data import rules
    names = {k: (v or {}).get("name", k) for k, v in rules.sources.items()}
    book = lambda r: tr("Made in the app") if r.get("source") == "Custom" else names.get(r.get("source"), r.get("source") or "")
    rank = lambda r: 0 if r.get("source") == "PHB" else 1 if r.get("source") == "Custom" else 2
    out = [(label(r), value(r), book(r), rank(r)) for r in records]
    out.sort(key=lambda x: (x[3], x[2].lower(), str(x[0]).lower()))
    return [x[:3] for x in out]


def set_items(c: QComboBox, items: Sequence[Union[str, Tuple]], current=None):
    """Refill a combo box without firing its change signal; keeps `current` (a value) selected if present.
    items: labels, (label, value) pairs or (label, value, group)."""
    c.blockSignals(True)
    c.clear()
    for it in items:
        lab, val, group = (it + (None,))[:3] if isinstance(it, tuple) else (it, it, None)
        c.addItem(str(lab), val)
        if group:
            c.setItemData(c.count() - 1, group, GROUP_ROLE)
    if current is not None:
        i = c.findData(current)
        if i >= 0:
            c.setCurrentIndex(i)
    c.blockSignals(False)


def scroll(content: QWidget) -> QScrollArea:
    s = QScrollArea()
    s.setWidgetResizable(True)
    s.setFrameShape(QFrame.NoFrame)
    s.setWidget(content)
    return s


def hline() -> QFrame:
    f = QFrame()
    f.setFrameShape(QFrame.HLine)
    f.setStyleSheet("color: #262c37;")
    return f


def clear_layout(layout: QLayout):
    """Remove and delete everything in a layout (to rebuild it)."""
    while layout.count():
        item = layout.takeAt(0)
        w = item.widget()
        if w is not None:
            w.hide()                                    # (a widget just added is queued to show: hidden, it stays hidden)
            w.deleteLater()                             # (not unparented first: that alone was ~8 ms a section of a sheet)
        elif item.layout() is not None:
            clear_layout(item.layout())


def expanding(w: QWidget) -> QWidget:
    w.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
    return w


class FlowLayout(QLayout):
    """Lays children out left to right and wraps them like words (chips, tags, condition toggles)."""

    def __init__(self, parent=None, spacing: int = 4):
        super().__init__(parent)
        self._items: List[QWidgetItem] = []
        self.setSpacing(spacing)
        self.setContentsMargins(0, 0, 0, 0)
        if isinstance(parent, QWidget):                 # the host grows sideways and wraps, instead of one column
            policy = QSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
            policy.setHeightForWidth(True)
            parent.setSizePolicy(policy)

    def addItem(self, item):
        self._items.append(item)

    def count(self):
        return len(self._items)

    def itemAt(self, i):
        return self._items[i] if 0 <= i < len(self._items) else None

    def takeAt(self, i):
        return self._items.pop(i) if 0 <= i < len(self._items) else None

    def expandingDirections(self):
        return Qt.Orientations(0)

    def hasHeightForWidth(self):
        return True

    def heightForWidth(self, width):
        return self._place(QRect(0, 0, width, 0), apply=False)

    def setGeometry(self, rect):
        super().setGeometry(rect)
        self._place(rect, apply=True)

    def sizeHint(self):
        width = sum(it.sizeHint().width() + self.spacing() for it in self._items
                    if not (it.widget() is not None and it.widget().isHidden()))
        return QSize(width, self.heightForWidth(max(width, 1)))

    def minimumSize(self):
        size = QSize()
        for it in self._items:
            size = size.expandedTo(it.minimumSize())
        return size

    def _place(self, rect: QRect, apply: bool) -> int:
        x, y, line = rect.x(), rect.y(), 0
        gap = self.spacing()
        for it in self._items:
            if it.widget() is not None and it.widget().isHidden():     # hidden chips take no room
                continue
            hint = it.sizeHint()
            if x + hint.width() > rect.right() and line > 0:
                x, y, line = rect.x(), y + line + gap, 0
            if apply:
                it.setGeometry(QRect(QPoint(x, y), hint))
            x += hint.width() + gap
            line = max(line, hint.height())
        return y + line - rect.y()


class ElideLabel(QLabel):
    """One line that ends in … when it is narrower than its text (all of it on hover); never widens its window."""

    def __init__(self, text: str = "", role: str = ""):
        super().__init__()
        if role:
            self.setProperty("role", role)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Preferred)
        self._full = ""
        self.setText(text)

    def setText(self, text: str):
        self._full = text or ""
        self.setToolTip(self._full)
        self._elide()

    def text(self) -> str:
        return self._full

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._elide()

    def _elide(self):
        QLabel.setText(self, self.fontMetrics().elidedText(self._full, Qt.ElideRight, max(0, self.width())))


class Columns(QWidget):
    """Widgets side by side while they fit, one under the other when the window is narrower than that - instead of a
    sideways scroll bar.   Columns(skills_card, attacks_card, stretches=(2, 3))"""

    def __init__(self, *widgets: QWidget, stretches: Sequence[int] = (), spacing: int = 5):
        super().__init__()
        self.parts = [w for w in widgets if w is not None]
        self.box = QBoxLayout(QBoxLayout.LeftToRight, self)
        self.box.setContentsMargins(0, 0, 0, 0)
        self.box.setSpacing(spacing)
        for i, w in enumerate(self.parts):
            self.box.addWidget(w, stretches[i] if i < len(stretches) else 0)

    def _side_by_side(self) -> int:
        return sum(w.minimumSizeHint().width() for w in self.parts) + self.box.spacing() * max(0, len(self.parts) - 1)

    def minimumSizeHint(self) -> QSize:
        hint = super().minimumSizeHint()
        return QSize(max([w.minimumSizeHint().width() for w in self.parts] or [0]), hint.height())

    def resizeEvent(self, e):
        want = QBoxLayout.LeftToRight if e.size().width() >= self._side_by_side() else QBoxLayout.TopToBottom
        if self.box.direction() != want:
            self.box.setDirection(want)
        super().resizeEvent(e)


class EvenGrid(QWidget):
    """Same-size boxes in even rows: all in one row while they fit, else two rows of half (six ability tiles: 6 or
    3 + 3, never 5 + 1 as a flow would wrap them)."""

    def __init__(self, *widgets: QWidget, spacing: int = 2):
        super().__init__()
        self.parts = [w for w in widgets if w is not None]
        self.grid = QGridLayout(self)
        self.grid.setContentsMargins(0, 0, 0, 0)
        self.grid.setSpacing(spacing)
        self.cols = 0
        self._place(len(self.parts))

    def _need(self, cols: int) -> int:
        w = max([max(p.minimumWidth(), p.minimumSizeHint().width()) for p in self.parts] or [0])
        return cols * w + self.grid.spacing() * max(0, cols - 1)

    def _place(self, cols: int):
        if cols == self.cols or not cols:
            return
        self.cols = cols
        for p in self.parts:
            self.grid.removeWidget(p)
        for i, p in enumerate(self.parts):
            self.grid.addWidget(p, i // cols, i % cols)
        self.updateGeometry()

    def minimumSizeHint(self) -> QSize:
        return QSize(self._need((len(self.parts) + 1) // 2), super().minimumSizeHint().height())

    def resizeEvent(self, e):
        n = len(self.parts)
        self._place(n if e.size().width() >= self._need(n) else (n + 1) // 2)
        super().resizeEvent(e)


class FlipSplitter(QSplitter):
    """A splitter like Columns: its parts side by side while they fit (their minimum widths), one under the other
    when narrower - so a window asks for its widest part only, not for all of them at once."""

    def _side_by_side(self) -> int:
        parts = [self.widget(i) for i in range(self.count())]
        return sum(max(w.minimumWidth(), w.minimumSizeHint().width()) for w in parts) + self.handleWidth() * max(0, len(parts) - 1)

    def minimumSizeHint(self) -> QSize:
        parts = [self.widget(i) for i in range(self.count())]
        return QSize(max([max(w.minimumWidth(), w.minimumSizeHint().width()) for w in parts] or [0]),
                     super().minimumSizeHint().height())

    def resizeEvent(self, e):
        want = Qt.Horizontal if e.size().width() >= self._side_by_side() else Qt.Vertical
        if self.orientation() != want:
            self.setOrientation(want)
        super().resizeEvent(e)
