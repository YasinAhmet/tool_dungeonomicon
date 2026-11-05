"""The "add content" window of a custom rulebook: one form per kind (race, subclass, spell, item, feat...), made from
the field definitions in app.services.library.content_fields. The window only collects the form; the service turns it
into a rules entry and checks it (a problem keeps the window open with the message).

    content_form(self, "spells", tr("New spell - {0}", book_name),
                 save=lambda form: library.save_entry(book_id, "spells", form))     # -> what save returned, or None
    FormBody("items", initial)          # the fields alone, to sit in another window (the Item workshop); .values()
"""
import copy
from typing import Callable, Dict, List, Optional

from PySide6.QtCore import QLocale, Qt, Signal
from PySide6.QtGui import QDoubleValidator, QIntValidator
from PySide6.QtWidgets import (QCheckBox, QFrame, QLineEdit, QPlainTextEdit, QPushButton, QScrollArea,
                               QVBoxLayout, QWidget)

from ....core.i18n import tr
from ....services import library
from ...dialogs import Dialog
from ...errors import report, user_errors
from ...widgets.common import FlowLayout, button, col, combo, label, line_edit, row, scroll, spin, stretch, widget

TALL = ("spells", "items", "races", "backgrounds", "feats", "subclasses")
GROWS = ("text", "textarea", "multi", "entries", "abilities")


def _int(value, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


class _FlowScroll(QScrollArea):
    """A scroll box around a FlowLayout that is as tall as its chips (up to max_height), then scrolls."""

    def __init__(self, host: QWidget, flow: FlowLayout, max_height: int = 120):
        super().__init__()
        self.host, self.flow, self.max_height = host, flow, max_height
        self.setWidgetResizable(True)
        self.setWidget(host)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.fit()

    def fit(self):
        h = max(22, self.flow.heightForWidth(max(40, self.viewport().width() - 6)) + 6)
        self.host.setMinimumHeight(h)
        self.setFixedHeight(min(self.max_height, h + 2 * self.frameWidth()))


class Chips(QWidget):
    """Tick any number of options; with search=True a box narrows them down (ticked ones always stay)."""

    def __init__(self, options, chosen, search: bool = False):
        super().__init__()
        self.options = [(v, str(lab)) for v, lab in options]
        picked = {str(c) for c in chosen or []}
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(2)
        self.query: Optional[QLineEdit] = None
        if search:
            self.query = line_edit(placeholder=tr("search…"))
            self.query.textChanged.connect(lambda _t: self._filter())
            box.addWidget(self.query)
        host = QWidget()
        self.flow = FlowLayout(host, spacing=3)
        self.flow.setContentsMargins(3, 3, 3, 3)
        self.buttons: Dict[object, QPushButton] = {}
        for v, lab in self.options:
            b = QPushButton(tr(lab))
            b.setCheckable(True)
            b.setChecked(str(v) in picked)
            b.setStyleSheet("padding: 1px 7px;")
            self.buttons[v] = b
            self.flow.addWidget(b)
        self.area = _FlowScroll(host, self.flow)
        box.addWidget(self.area)

    def value(self) -> list:
        return [v for v, _l in self.options if self.buttons[v].isChecked()]

    def _filter(self):
        needle = self.query.text().strip().lower() if self.query else ""
        while self.flow.count():
            self.flow.takeAt(0)
        for v, lab in self.options:
            b = self.buttons[v]
            shown = not needle or b.isChecked() or needle in lab.lower() or needle in b.text().lower()
            b.setVisible(shown)
            if shown:
                self.flow.addWidget(b)
        self.flow.invalidate()
        self.area.fit()


class Entries(QWidget):
    """A list of named entries (a race's traits; with level=True a subclass's features and the level granting each)."""

    def __init__(self, rows: List[dict], level: bool = False):
        super().__init__()
        self.level = level
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(4)
        self.list = QVBoxLayout()
        self.list.setSpacing(4)
        box.addLayout(self.list)
        box.addLayout(row(button(tr("+ Add feature") if level else tr("+ Add trait"), self._add), stretch()))
        self.rows: List[tuple] = []
        for r in rows or [{}]:
            self._append(r)

    def _append(self, r: dict):
        frame = QFrame()
        frame.setObjectName("card")
        lv = spin(_int(r.get("level"), 3), 1, 20, width=40, tip=tr("Class level")) if self.level else None
        name = line_edit(str(r.get("name") or ""), tr("Name"))
        text = QPlainTextEdit(str(r.get("text") or ""))
        text.setPlaceholderText(tr("What it does"))
        text.setFixedHeight(62)
        entry = (frame, lv, name, text)
        rm = button("✕", lambda: self._remove(entry), kind="danger", width=26, tip=tr("Remove"))
        frame.setLayout(col(row(label(tr("Level")) if lv else None, lv, name, rm), text, margins=5))
        self.list.addWidget(frame)
        self.rows.append(entry)

    def _remove(self, entry: tuple):
        self.rows.remove(entry)
        entry[0].setParent(None)
        entry[0].deleteLater()

    def _add(self):
        last = self.rows[-1][1].value() if self.level and self.rows else 3
        self._append({"level": last})
        self.rows[-1][2].setFocus()

    def value(self) -> List[dict]:
        out = []
        for _f, lv, name, text in self.rows:
            e = {"name": name.text().strip(), "text": text.toPlainText().strip()}
            if lv is not None:
                e["level"] = lv.value()
            out.append(e)
        return out


class FormBody(QWidget):
    """The fields of one kind's form, laid out in rows (the Item workshop shows it inline; ContentForm in a window).
    `changed` fires on every edit."""
    changed = Signal()

    def __init__(self, kind: str, initial: Optional[dict] = None, parent=None):
        super().__init__(parent)
        self.kind = kind
        self.fields = library.content_fields(kind)
        self.form = {**library.blank_form(kind), **copy.deepcopy(initial or {})}
        self.abilities = library.options()["abilities"]
        self.getters: List[Callable[[], dict]] = []
        self.boxes: Dict[str, tuple] = {}             # key -> (field, its box) for fields that come and go
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 8, 0)
        lay.setSpacing(8)
        for fields in self.fields:
            lay.addLayout(self._row(fields))
        lay.addStretch(1)
        self._visibility()

    # ------------------------------------------------------------------ building
    def _row(self, fields: List[dict]):
        boxes = []
        mixed = any(f["type"] != "check" for f in fields)
        for f in fields:
            box = self._field(f, mixed)
            boxes.append((box, 1 if f["type"] in GROWS else 0))
            if f.get("show") or f.get("hide"):
                self.boxes[f["key"]] = (f, box)
        lay = row(spacing=10)
        for box, grow in boxes:
            lay.addWidget(box, grow, Qt.AlignTop)
        if not any(grow for _b, grow in boxes):
            lay.addStretch(1)
        return lay

    def _field(self, f: dict, mixed: bool) -> QWidget:
        key, kind, value = f["key"], f["type"], self.form.get(f["key"])
        caption = tr(f["label"]) + (" *" if f.get("required") else "")
        if kind == "check":
            w = QCheckBox(caption)
            w.setChecked(bool(value))
            w.toggled.connect(lambda _on: self._visibility())
            self.getters.append(lambda w=w: {key: w.isChecked()})
            return widget(col(label(" ") if mixed else None, w))
        if kind == "text":
            w = line_edit(str(value if value is not None else ""))
            w.textEdited.connect(lambda _t: self.changed.emit())
            self.getters.append(lambda w=w: {key: w.text().strip()})
        elif kind == "textarea":
            w = QPlainTextEdit(str(value or ""))
            w.setFixedHeight(f.get("rows", 4) * 16 + 12)
            w.textChanged.connect(self.changed.emit)
            self.getters.append(lambda w=w: {key: w.toPlainText().strip()})
        elif kind == "number":
            w = line_edit(str(value if value not in (None, "") else ""), width=96)
            v = QDoubleValidator(-10 ** 6, 10 ** 6, 2, w) if f.get("decimal") else QIntValidator(-10 ** 6, 10 ** 6, w)
            v.setLocale(QLocale.c())
            w.setValidator(v)
            w.textEdited.connect(lambda _t: self.changed.emit())
            self.getters.append(lambda w=w: {key: w.text().strip()})
        elif kind == "select":
            w = combo([(tr(str(lab)), val) for val, lab in f["options"]])
            for i in range(w.count()):
                if str(w.itemData(i)) == str(value):
                    w.setCurrentIndex(i)
            w.setMinimumWidth(130)
            w.currentIndexChanged.connect(lambda _i: self._visibility())
            self.getters.append(lambda w=w: {key: w.currentData()})
        elif kind == "multi":
            w = Chips(f["options"], value, search=bool(f.get("search")))
            for b in w.buttons.values():
                b.toggled.connect(lambda _on: self.changed.emit())
            self.getters.append(lambda w=w: {key: w.value()})
        elif kind == "entries":
            w = Entries(value or [], level=bool(f.get("level")))
            self.getters.append(lambda w=w: {key: w.value()})
        elif kind == "abilities":
            spins = {a["key"]: spin(_int(self.form.get(key + a["key"])), -4, 4, width=40, tip=tr(a["name"]))
                     for a in self.abilities}
            w = widget(row(*[col(label(a["key"].upper(), role="dim"), spins[a["key"]], spacing=1) for a in self.abilities],
                           stretch(), spacing=8))
            self.getters.append(lambda s=spins: {key + a: sp.value() for a, sp in s.items()})
        else:
            raise ValueError(f"Unknown field type '{kind}'.")
        parts = [label(caption, role="dim"), w]
        if f.get("hint"):
            parts.append(label(tr(f["hint"]), role="dim", wrap=True))
        return widget(col(*parts, spacing=2))

    # ------------------------------------------------------------------ values
    def values(self) -> dict:
        out = dict(self.form)
        for get in self.getters:
            out.update(get())
        return out

    def _visibility(self):
        if self.boxes:
            form = self.values()
            for f, box in self.boxes.values():
                box.setVisible(library.field_shown(f, form))
        self.changed.emit()


class ContentForm(Dialog):
    def __init__(self, parent, kind: str, title: str, save: Callable[[dict], object], initial: Optional[dict] = None):
        super().__init__(parent, title, 760)
        self.kind, self.save, self.result_value = kind, save, None
        self.body_form = FormBody(kind, initial)
        self.body.addWidget(scroll(self.body_form), 1)
        self.ok_cancel(tr("Save"), self._ok)
        h = 720 if kind in TALL else self.body_form.sizeHint().height() + 110
        self.resize(760, min(720, h))

    def values(self) -> dict:
        return self.body_form.values()

    def _ok(self):
        form = self.values()
        missing = library.missing_field(self.kind, form)
        if missing:
            self.show_problem(tr("{0} is required.", tr(missing)))
            return
        try:
            self.result_value = self.save(form)
        except user_errors() as e:
            self.show_problem(tr(str(e.args[0] if isinstance(e, KeyError) and e.args else e)))
            return
        except Exception as e:                          # a bug: logged and reported like everywhere else
            report(e)
            return
        self.accept()


def content_form(parent, kind: str, title: str, save: Callable[[dict], object], initial: Optional[dict] = None):
    """Open the form of `kind`; save(form) stores it (raising a ServiceError keeps the window open with the message).
    Returns what save returned, or None when cancelled."""
    d = ContentForm(parent, kind, title, save, initial)
    return d.result_value if d.exec() == Dialog.Accepted else None
