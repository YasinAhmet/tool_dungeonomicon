"""Small modal windows: confirm, ask for text or a number, a quick form, choose one of a few or of many.

    if dialogs.confirm(self, tr("Delete {0}?", name)): ...
    name = dialogs.ask_text(self, tr("Rename"), tr("New name"), old)        # None when cancelled
    values = dialogs.form(self, tr("Custom enemy"), [
        {"key": "name", "label": tr("Name"), "required": True},
        {"key": "hp", "label": tr("Hit points"), "kind": "int", "value": 10, "min": 1, "max": 999},
        {"key": "type", "label": tr("Type"), "kind": "select", "options": [(tr("Melee"), "melee"), ...]},
        {"key": "notes", "label": tr("Notes"), "kind": "multiline"},
        {"key": "hidden", "label": tr("Hidden"), "kind": "check"}])
    dmg = dialogs.choose_one(self, tr("Damage type"), ["fire", "cold"])
    summon = dialogs.choose_from(self, tr("Summon"), [(label, value), ...])     # a searchable list
    picked = dialogs.pick(self, tr("Choose two"), pool, count=2)                 # PickList in a window

Dialog is the base for bigger windows (the level-up and creation wizards): it gives a body layout and a button row.
"""
from typing import Dict, List, Optional, Sequence

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout, QLineEdit, QListWidget,
                               QListWidgetItem, QPlainTextEdit, QPushButton, QSpinBox, QVBoxLayout, QWidget)

from ..core.i18n import tr
from .widgets.common import Combo, label
from ..rules.describe import describe_name
from .widgets.pickers import PickList


class Dialog(QDialog):
    """A titled window with a body (self.body, a QVBoxLayout) and a button row (add_button)."""

    def __init__(self, parent: Optional[QWidget], title: str, width: int = 380, height: int = 0):
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        self.resize(width, height or 10)
        outer = QVBoxLayout(self)
        outer.setContentsMargins(10, 10, 10, 8)
        outer.setSpacing(8)
        self.body = QVBoxLayout()
        self.body.setSpacing(6)
        outer.addLayout(self.body, 1)
        self.problem = label("", role="bad", wrap=True)
        self.problem.hide()
        outer.addWidget(self.problem)
        self.buttons = QHBoxLayout()
        self.buttons.addStretch(1)
        outer.addLayout(self.buttons)

    def add_button(self, text: str, slot=None, kind: str = "", default: bool = False) -> QPushButton:
        b = QPushButton(text)
        if kind:
            b.setProperty("kind", kind)
        b.clicked.connect(slot or self.reject)
        if default:
            b.setDefault(True)
        self.buttons.addWidget(b)
        return b

    def ok_cancel(self, ok_text: str = "", on_ok=None):
        self.add_button(tr("Cancel"), self.reject)
        return self.add_button(ok_text or tr("OK"), on_ok or self.accept, kind="primary", default=True)

    def show_problem(self, text: str):
        self.problem.setText(text)
        self.problem.setVisible(bool(text))


def confirm(parent, message: str, title: str = "", yes: str = "") -> bool:
    d = Dialog(parent, title or tr("Are you sure?"), 380)
    d.body.addWidget(label(message, wrap=True))
    d.ok_cancel(yes or tr("Yes"))
    return d.exec() == QDialog.Accepted


def info(parent, message: str, title: str = ""):
    d = Dialog(parent, title or tr("Information"), 420)
    d.body.addWidget(label(message, wrap=True, selectable=True))
    d.add_button(tr("OK"), d.accept, kind="primary", default=True)
    d.exec()


def ask_text(parent, title: str, prompt: str, initial: str = "", multiline: bool = False) -> Optional[str]:
    d = Dialog(parent, title, 380 if not multiline else 480)
    d.body.addWidget(label(prompt))
    edit = QPlainTextEdit(initial) if multiline else QLineEdit(initial)
    d.body.addWidget(edit)
    d.ok_cancel()
    edit.setFocus()
    if d.exec() != QDialog.Accepted:
        return None
    return (edit.toPlainText() if multiline else edit.text()).strip()


def ask_int(parent, title: str, prompt: str, value: int = 0, low: int = 0, high: int = 10 ** 6) -> Optional[int]:
    got = form(parent, title, [{"key": "n", "label": prompt, "kind": "int", "value": value, "min": low, "max": high}])
    return None if got is None else got["n"]


def form(parent, title: str, fields: List[Dict], ok_text: str = "", submit=None) -> Optional[Dict]:
    """fields: [{key, label, kind: text|int|select|check|multiline, value, options: [label | (label, value)], required,
    min, max}]. Returns {key: value} or None when cancelled.

    submit(values) runs on OK (e.g. the save itself): if it raises a user error, the message shows in the window and
    it stays open; whatever it returns is ignored."""
    d = Dialog(parent, title, 400)
    grid = QFormLayout()
    grid.setLabelAlignment(Qt.AlignRight)
    inputs: Dict[str, QWidget] = {}
    for f in fields:
        kind = f.get("kind", "text")
        if kind == "int":
            w = QSpinBox()
            w.setRange(f.get("min", -10 ** 6), f.get("max", 10 ** 6))
            w.setValue(int(f.get("value") or 0))
        elif kind == "select":
            w = Combo()
            for o in f.get("options", []):
                lab, val = o if isinstance(o, tuple) else (o, o)
                w.addItem(str(lab), val)
            if f.get("value") is not None:
                w.setCurrentIndex(max(0, w.findData(f["value"])))
        elif kind == "check":
            w = QCheckBox()
            w.setChecked(bool(f.get("value")))
        elif kind == "multiline":
            w = QPlainTextEdit(str(f.get("value") or ""))
            w.setFixedHeight(80)
        else:
            w = QLineEdit(str(f.get("value") or ""))
        if f.get("tip"):
            w.setToolTip(f["tip"])
        inputs[f["key"]] = w
        grid.addRow(f["label"] + (" *" if f.get("required") else ""), w)
    d.body.addLayout(grid)
    out: Dict = {}

    def ok():
        for f in fields:
            w = inputs[f["key"]]
            if isinstance(w, QSpinBox):
                v = w.value()
            elif isinstance(w, QComboBox):
                v = w.currentData()
            elif isinstance(w, QCheckBox):
                v = w.isChecked()
            elif isinstance(w, QPlainTextEdit):
                v = w.toPlainText().strip()
            else:
                v = w.text().strip()
            if f.get("required") and v in ("", None):
                d.show_problem(tr("{0} is required.", f["label"]))
                return
            out[f["key"]] = v
        if submit is not None:
            from .errors import user_errors
            try:
                submit(dict(out))
            except user_errors() as e:
                d.show_problem(tr(str(e)))
                return
        d.accept()

    d.ok_cancel(ok_text, ok)
    if fields:
        inputs[fields[0]["key"]].setFocus()
    return out if d.exec() == QDialog.Accepted else None


def choose_one(parent, title: str, options: Sequence) -> Optional[object]:
    """A few big buttons; options are names or (label, value). Returns the value or None."""
    d = Dialog(parent, title, 300)
    picked = []
    for o in options:
        lab, val = o if isinstance(o, tuple) else (str(o)[:1].upper() + str(o)[1:], o)
        b = QPushButton(lab)
        b.clicked.connect(lambda _c=False, v=val: (picked.append(v), d.accept()))
        d.body.addWidget(b)
    d.add_button(tr("Cancel"), d.reject)
    return picked[0] if d.exec() == QDialog.Accepted and picked else None


def choose_from(parent, title: str, options: Sequence, prompt: str = "") -> Optional[object]:
    """A searchable list; options are names or (label, value). Double-click or OK picks. Returns the value or None."""
    d = Dialog(parent, title, 380, 460)
    if prompt:
        d.body.addWidget(label(prompt, wrap=True))
    q = QLineEdit()
    q.setPlaceholderText(tr("search…"))
    lst = QListWidget()
    rows = [(o if isinstance(o, tuple) else (o, o)) for o in options]

    def draw():
        needle = q.text().strip().lower()
        lst.clear()
        for lab, val in rows:
            if not needle or needle in str(lab).lower():
                it = QListWidgetItem(str(lab))
                it.setData(Qt.UserRole, val)
                lst.addItem(it)
        if lst.count():
            lst.setCurrentRow(0)
    q.textChanged.connect(draw)
    q.returnPressed.connect(d.accept)
    lst.itemDoubleClicked.connect(lambda _i: d.accept())
    d.body.addWidget(q)
    d.body.addWidget(lst)
    d.ok_cancel()
    draw()
    q.setFocus()
    if d.exec() != QDialog.Accepted or not lst.currentItem():
        return None
    return lst.currentItem().data(Qt.UserRole)


def pick(parent, title: str, options: Sequence, count: int = 1, selected: Sequence = (), prompt: str = "",
         exact: bool = True, detail=describe_name) -> Optional[list]:
    """A PickList in a window. With exact=True, OK needs exactly `count` picks; `detail` gives hover descriptions
    (None for none). Returns the chosen values or None."""
    d = Dialog(parent, title, 420, 480)
    if prompt:
        d.body.addWidget(label(prompt, wrap=True))
    pl = PickList(options, count=count, selected=selected, detail=detail)
    d.body.addWidget(pl)

    def ok():
        if exact and not pl.done():
            d.show_problem(tr("Choose {0}.", count))
            return
        d.accept()
    d.ok_cancel(on_ok=ok)
    return pl.chosen() if d.exec() == QDialog.Accepted else None
