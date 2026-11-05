"""A search line that lists what it can find while you type (like an editor's code completion).

    box = LookupBox(lambda: [{"name": "Fireball", "kind": "Spell", "meta": "3rd level", "key": ("spells", "Fireball")}, ...])
    box.picked.connect(lambda entry: ...)

The list under the line ranks the names that start with what was typed first, then the ones with a word that does,
then the ones that hold it anywhere. Up / Down move through it, Enter or a click picks the highlighted one - or, with
none highlighted, the best match (so typing part of a name and pressing Enter is enough); Tab completes the line to
the highlighted name; Escape closes the list. `entries` is called the first time the list is needed and again after
`forget()`.
"""
from typing import Callable, List, Optional

from PySide6.QtCore import QEvent, QPoint, Qt, QTimer, Signal
from PySide6.QtWidgets import QLineEdit, QListWidget, QListWidgetItem

from ...core.i18n import tr
from ..theme import COLORS

SHOWN = 40


def rank(needle: str, name: str) -> Optional[int]:
    """How well `name` matches what was typed (lower is better), None when it doesn't."""
    n, s = needle.lower().strip(), name.lower()
    if not n:
        return None
    if s == n:
        return 0
    if s.startswith(n):
        return 1
    words = s.replace("-", " ").replace("(", " ").replace("/", " ").split()
    if any(w.startswith(n) for w in words):
        return 2
    if n in s:
        return 3
    parts = n.split()
    if len(parts) > 1 and all(any(w.startswith(p) for w in words) for p in parts):
        return 4
    return None


class LookupBox(QLineEdit):
    picked = Signal(object)                 # the chosen entry (one of the dicts `entries` gave)

    def __init__(self, entries: Callable[[], List[dict]], placeholder: str = "", parent=None):
        super().__init__(parent)
        self.entries_fn = entries
        self._entries: Optional[List[dict]] = None
        self.found: List[dict] = []
        if placeholder:
            self.setPlaceholderText(placeholder)
        self.setClearButtonEnabled(True)
        self.popup = QListWidget(self)                     # (its own small window, made and deleted with the line)
        self.popup.setWindowFlags(Qt.ToolTip | Qt.FramelessWindowHint)
        self.popup.setAttribute(Qt.WA_ShowWithoutActivating)
        self.popup.setFocusPolicy(Qt.NoFocus)
        self.popup.setUniformItemSizes(True)
        self.popup.setStyleSheet(f"QListWidget {{ border: 1px solid {COLORS['accent']}; }}")
        self.popup.itemClicked.connect(lambda it: self._pick(self.popup.row(it)))
        self.textEdited.connect(lambda _t: self._suggest())
        self.returnPressed.connect(self._enter)

    # ------------------------------------------------------------------ the entries
    def forget(self):
        """The entries changed (a book switched on, a character made): ask again the next time."""
        self._entries = None

    def entries(self) -> List[dict]:
        if self._entries is None:
            self._entries = list(self.entries_fn() or [])
            for e in self._entries:
                e.setdefault("shown", tr(e["name"]))
        return self._entries

    def matches(self, text: str) -> List[dict]:
        scored = []
        for i, e in enumerate(self.entries()):
            r = rank(text, e["shown"])
            if r is None and e["shown"] != e["name"]:
                r = rank(text, e["name"])
            if r is not None:
                scored.append((r, len(e["name"]), i, e))
        scored.sort(key=lambda t: t[:3])
        return [t[3] for t in scored[:SHOWN]]

    # ------------------------------------------------------------------ the list
    def _suggest(self):
        text = self.text().strip()
        self.found = self.matches(text) if text else []
        self.popup.clear()
        if not self.found:
            self.popup.hide()
            return
        for e in self.found:
            extra = " · ".join(x for x in (tr(e.get("kind") or ""), tr(e.get("meta") or "")) if x)
            it = QListWidgetItem(f"{e['shown']}   —   {extra}" if extra else e["shown"])
            if e.get("icon") is not None:
                it.setIcon(e["icon"])
            self.popup.addItem(it)
        self.popup.setCurrentRow(-1)
        self._place()

    def _place(self):
        rows = min(len(self.found), 12)
        h = self.popup.sizeHintForRow(0) * rows + 6 if rows else 0
        w = max(self.width(), 320)
        self.popup.setFixedSize(w, h)
        self.popup.move(self.mapToGlobal(QPoint(0, self.height())))
        self.popup.show()
        self.popup.raise_()

    def close_list(self):
        self.popup.hide()

    def _pick(self, i: int):
        if not 0 <= i < len(self.found):
            return
        e = self.found[i]
        self.close_list()
        self.setText(e["shown"])
        self.selectAll()
        self.picked.emit(e)

    def _enter(self):
        if not self.popup.isVisible():
            self._suggest()
            self.popup.hide()
        if self.found:
            self._pick(max(0, self.popup.currentRow()))

    def keyPressEvent(self, e):
        key = e.key()
        if self.popup.isVisible() and self.found:
            row = self.popup.currentRow()
            if key in (Qt.Key_Down, Qt.Key_Up, Qt.Key_PageDown, Qt.Key_PageUp):
                step = {Qt.Key_Down: 1, Qt.Key_Up: -1, Qt.Key_PageDown: 10, Qt.Key_PageUp: -10}[key]
                self.popup.setCurrentRow(max(0, min(len(self.found) - 1, row + step)))
                return
            if key == Qt.Key_Escape:
                self.close_list()
                return
            if key == Qt.Key_Tab:
                e2 = self.found[max(0, row)]
                self.setText(e2["shown"])
                self._suggest()
                return
        elif key == Qt.Key_Down and self.text().strip():
            self._suggest()
            return
        super().keyPressEvent(e)

    def event(self, e):
        if e.type() == QEvent.KeyPress and e.key() == Qt.Key_Tab and self.popup.isVisible():
            self.keyPressEvent(e)                          # (Tab would move the focus before keyPressEvent sees it)
            return True
        return super().event(e)

    def focusOutEvent(self, e):
        super().focusOutEvent(e)
        QTimer.singleShot(200, self, lambda: None if self.hasFocus() else self.close_list())   # (a click on the list first)

    def hideEvent(self, e):
        super().hideEvent(e)
        self.close_list()

    def moveEvent(self, e):
        super().moveEvent(e)
        if self.popup.isVisible():
            self._place()
