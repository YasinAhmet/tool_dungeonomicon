"""The sheet's inventory: coins, carried weight, one tight row per item with its description (equip, attune, use, more
or fewer, change its name, amount or description, send to another character, remove), a quick entry line (a name, a
description, how many) and the Add item window (the item search, a custom name, add or buy). An item's name can
be dragged onto the Battle map: it lies on that tile, or goes to the creature dropped on (Ctrl: just one)."""
import html
import json
from typing import Callable, List, Optional

from PySide6.QtCore import QEvent, QMimeData, QObject, Qt
from PySide6.QtGui import QDoubleValidator, QDrag
from PySide6.QtWidgets import QCompleter, QDialog, QGridLayout, QSpinBox, QWidget

from ....core.i18n import tr
from ....core.runtime import rt
from ....rules import engine as E
from ....services.battle import icons
from ....services.characters import view
from ... import dialogs, notify
from ...errors import guard, guard_ok
from ...widgets.common import button, label, line_edit, row, spin, stretch, widget
from ...widgets.search import DRAG_MIME, SearchPanel
from .sheet_widgets import bare, flow, rich_tip, section


def build(sheet, d: dict, lay):
    name = d["name"]
    coins = []
    boxes = {}
    for c in reversed(E.COINS):                         # pp gp ep sp cp
        s = spin(int(d["currency"].get(c) or 0), 0, 10 ** 9, width=64, tip=tr("{0} pieces", c.upper()))
        boxes[c] = s
        coins.append(bare(widget(row(label(c.upper(), role="dim"), s, spacing=3))))   # a coin and its box wrap together

    def save_coins():
        new = {c: b.value() for c, b in boxes.items()}
        if new != {c: int(d["currency"].get(c) or 0) for c in E.COINS}:
            sheet.call("set_currency", new)
    for b in boxes.values():
        b.editingFinished.connect(save_coins)
    lay.addWidget(section(tr("Coins"), flow(*coins, label(tr(d["doc"]["weight"]), role="dim"), spacing=8)))

    items = sorted(d["inventory"], key=lambda e: (not e["equipped"], e["name"].lower()))
    grid = QGridLayout()
    grid.setHorizontalSpacing(3)
    grid.setVerticalSpacing(1)
    for r, e in enumerate(items):
        name_label = label(item_text(e, bold=e["equipped"]), role="good" if e["equipped"] else "", tip=rich_tip(with_note(e["tip"], e)))
        _ItemDrag(name_label, {"kind": "inv_item", "character": name, "item": e["name"], "qty": e["qty"]})
        grid.addWidget(name_label, r, 0)
        tags = (["⚔"] if e["equipped"] else []) + (["✦"] if e.get("attuned") else [])
        grid.addWidget(label(" ".join(tags), role="accent"), r, 1)
        acts = []
        if e["wearable"]:
            b = button("⚔", lambda n=e["name"], on=not e["equipped"]: sheet.call("set_equipped", n, on),
                       tip=tr("Unequip") if e["equipped"] else tr("Equip"), checkable=True, width=28)
            b.setChecked(bool(e["equipped"]))
            acts.append(b)
        if e["attunable"]:
            b = button("✦", lambda n=e["name"], on=not e.get("attuned"): sheet.call("set_attuned", n, on),
                       tip=tr("Break attunement") if e.get("attuned") else tr("Attune"), checkable=True, width=28)
            b.setChecked(bool(e.get("attuned")))
            acts.append(b)
        if e.get("usable"):
            acts.append(button(tr("Use"), lambda n=e["name"]: _use(sheet, n), tip=tr("Use one up (potions heal by themselves)")))
        acts += [button("−", lambda n=e["name"]: sheet.call("remove_item", n, 1), tip=tr("One fewer"), width=26),
                 button("+", lambda n=e["name"]: sheet.call("add_item", n, 1), tip=tr("One more"), width=26),
                 button("✎", lambda x=e: _edit(sheet, x), tip=tr("Change its name, amount or description"), width=26),
                 button("➜", lambda n=e["name"], q=e["qty"]: send_item(sheet, n, q), tip=tr("Send to another character"),
                        width=28),
                 button("✕", lambda n=e["name"], q=e["qty"]: _remove_all(sheet, n, q), kind="danger", tip=tr("Remove"),
                        width=26)]
        grid.addWidget(bare(widget(row(*acts, spacing=2))), r, 2, Qt.AlignRight)
    grid.setColumnStretch(0, 1)
    body = bare(widget(grid)) if items else label(tr("Nothing yet."), role="dim")
    add = row(button(tr("Search…"), lambda: AddItemDialog(sheet, name).exec(), tip=tr("Pick an item from the item list")),
              button(tr("Buy…"), lambda: AddItemDialog(sheet, name, buy=True).exec(),
                     tip=tr("Add an item and pay for it from the coins")))
    quick = QuickEntry(lambda item, n, desc: sheet.call("add_item", item, n, desc=desc or None) is not None)
    lay.addWidget(section(tr("Inventory"), body, quick, extra=bare(widget(add))))


def item_text(e: dict, bold: bool = False) -> str:
    """An item's line: its picture, its name (×how many) and its description under it, small."""
    text = f"<b>{tr(e['name'])}</b>" if bold else tr(e["name"])
    pic = icons.path(icons.for_item(e["name"]) or "")                  # what kind of thing it is, at a glance
    if pic:
        text = f"<img src='{pic}' width='14' height='14'>&nbsp;" + text
    if e["qty"] != 1:
        text += f"  <span style='color:#8b93a3'>×{e['qty']}</span>"
    note = html.escape(e.get("note") or "")
    if note:
        short = note if len(note) <= 90 else note[:88].rstrip() + "…"
        text += f"<br><span style='color:#8b93a3; font-size:11px'>{short}</span>"
    return text


def with_note(tip: str, e: dict) -> str:
    return tip + (f"\n\n{e['note']}" if e.get("note") else "")


def edit_form(parent, e: dict) -> Optional[dict]:
    """An item's name, amount and description: {"name", "qty", "note"} (None: cancelled)."""
    return dialogs.form(parent, tr("Change {0}", tr(e["name"])), [
        {"key": "name", "label": tr("Name"), "value": e["name"], "required": True},
        {"key": "qty", "label": tr("How many"), "kind": "int", "value": e["qty"], "min": 1, "max": 99999},
        {"key": "note", "label": tr("Description"), "kind": "multiline", "value": e.get("note") or ""}], tr("Save"))


_NAMES: list = []                                       # [(books, item list) it was made for, names...]


def item_names() -> List[str]:
    """Every item of the item list, for the quick entry's suggestions (read once)."""
    from ....rules.data import rules
    key = (rules.active_sources, id(rules.items))       # (again after the books or the modules changed)
    if _NAMES[:1] != [key]:
        _NAMES[:] = [key] + sorted({e["name"] for e in rules.offered(rules.items.values()) if e.get("name")},
                                                    key=str.lower)
    return _NAMES[1:]


class QuickEntry(QWidget):
    """One line to write an item in: its name (the item list suggests), a description, how many, Enter or Add.
    on_add(name, qty, description) -> True when it went in (the line then empties)."""

    def __init__(self, on_add: Callable[[str, int, str], bool], placeholder: str = ""):
        super().__init__()
        self.on_add = on_add
        self.name = line_edit(placeholder=placeholder or tr("Item name"), on_enter=self.add,
                              tip=tr("Any name: the item list suggests as you type. Enter adds it."))
        comp = QCompleter(item_names(), self.name)
        comp.setCaseSensitivity(Qt.CaseInsensitive)
        comp.setFilterMode(Qt.MatchContains)
        self.name.setCompleter(comp)
        self.desc = line_edit(placeholder=tr("description (optional)"), on_enter=self.add)
        self.qty = spin(1, 1, 99999, width=52, tip=tr("How many"))
        self.qty.setButtonSymbols(QSpinBox.UpDownArrows)
        lay = row(self.name, self.desc, self.qty, button(tr("Add"), self.add, kind="primary"), spacing=3)
        lay.setStretch(0, 3)
        lay.setStretch(1, 4)
        self.setLayout(lay)

    def add(self):
        name = self.name.text().strip()
        if not name:
            self.name.setFocus()
            return
        if self.on_add(name, self.qty.value(), self.desc.text().strip()):
            self.name.clear()
            self.desc.clear()
            self.qty.setValue(1)
            self.name.setFocus()


class _ItemDrag(QObject):
    """Makes an item's name a drag source: drop it on the Battle map."""
    def __init__(self, w, payload: dict):
        super().__init__(w)
        self.payload, self.press = payload, None
        w.installEventFilter(self)
        w.setCursor(Qt.OpenHandCursor)

    def eventFilter(self, obj, e):
        if e.type() == QEvent.MouseButtonPress and e.button() == Qt.LeftButton:
            self.press = e.position()
        elif e.type() == QEvent.MouseButtonRelease:
            self.press = None
        elif e.type() == QEvent.MouseMove and self.press is not None and (e.position() - self.press).manhattanLength() > 6:
            self.press = None
            mime = QMimeData()
            mime.setData(DRAG_MIME, json.dumps(self.payload).encode())
            drag = QDrag(obj)
            drag.setMimeData(mime)
            drag.exec(Qt.MoveAction | Qt.CopyAction)
            return True
        return False


def _use(sheet, item: str):
    text = sheet.call("use_item", item)
    if text:
        sheet.say(text)


def _edit(sheet, e: dict):
    got = edit_form(sheet, e)
    if got:
        sheet.call("edit_item", e["name"], got["qty"], got["note"], got["name"])


def _remove_all(sheet, item: str, qty: int):
    if qty == 1 or dialogs.confirm(sheet, tr("Remove all {0}× {1}?", qty, item), tr("Remove item")):
        sheet.call("remove_all_of", item)


def send_item(sheet, item: str, qty: int):
    others = [n for n in rt().characters.names() if n != sheet.name]
    if not others:
        notify.warn(tr("There is no other character to send it to."))
        return
    got = dialogs.form(sheet, tr("Send {0}", item), [
        {"key": "to", "label": tr("To"), "kind": "select", "options": sorted(others, key=str.lower)},
        {"key": "n", "label": tr("How many"), "kind": "int", "value": 1, "min": 1, "max": max(1, qty)}], tr("Send"))
    if got and guard(lambda: rt().characters.send_item(sheet.name, got["to"], item, got["n"]) or True):
        notify.good(tr("Sent {0}× {1} to {2}", got["n"], item, got["to"]))


class AddItemDialog(dialogs.Dialog):
    """Pick an item with the item search (or type a custom name) and add it, or buy it with the character's coins.
    `team`: into the team inventory instead (no buying)."""

    def __init__(self, parent, name: str, buy: bool = False, team: bool = False):
        title = tr("Add item — {0}", tr("Team inventory")) if team else tr("Buy item — {0}", name) if buy else tr("Add item — {0}", name)
        super().__init__(parent, title, 1100, 680)
        self.name, self.team = name, team
        self.search = SearchPanel(
            "items", columns=[("name", tr("Name"), 0), ("type", tr("Type"), 120), ("rarity", tr("Rarity"), 90),
                              ("cost", tr("Cost"), 70), ("wt", tr("Wt"), 44), ("src", tr("Book"), 56)],
            sorts=["name", "rarity", "cost", "weight", "type", "book"], default_sort="name",
            groups={tr("Category"): "cat", tr("Type"): "type", tr("Rarity"): "rarity", tr("Book"): "src"},
            hover_detail=True, on_double=lambda _r: self.submit(buy), on_select=lambda r: self._picked(r))
        self.body.addWidget(self.search, 1)
        self.qty = QSpinBox()
        self.qty.setRange(1, 9999)
        self.qty.setValue(1)
        self.qty.setFixedWidth(60)
        self.qty.valueChanged.connect(lambda _v: self._price_hint())
        self.custom = line_edit(placeholder=tr("or a custom item"), width=220)
        self.price = line_edit(placeholder=tr("gp each"), width=70, tip=tr("Price of one, in gold pieces"))
        self.price.setValidator(QDoubleValidator(0, 10 ** 7, 2, self.price))
        self.price.textChanged.connect(lambda _t: self._price_hint())
        self.total = label("", role="dim")
        self.body.addLayout(row(label(tr("Quantity"), role="dim"), self.qty, self.custom, 10, label(tr("Price"), role="dim"),
                                self.price, self.total, stretch()))
        self.add_button(tr("Cancel"), self.reject)
        if not team:
            self.add_button(tr("Buy"), lambda: self.submit(True), kind="" if not buy else "primary", default=buy)
        self.add_button(tr("Add"), lambda: self.submit(False), kind="primary" if not buy else "", default=not buy)

    def item_name(self) -> str:
        r = self.search.selected()
        return self.custom.text().strip() or (r["name"] if r else "")

    def _picked(self, r: dict):
        if not self.custom.text().strip():
            each = view.item_price_gp(r["name"])
            self.price.setText(f"{each:g}" if each is not None else "")

    def _price_hint(self):
        try:
            each = float(self.price.text().replace(",", "."))
        except ValueError:
            self.total.setText("")
            return
        self.total.setText(tr("= {0} gp", f"{each * self.qty.value():g}"))

    def submit(self, buy: bool):
        item = self.item_name()
        if not item:
            self.show_problem(tr("Pick an item or type a custom name."))
            return
        n = self.qty.value()
        if buy:
            try:
                each = float(self.price.text().replace(",", ".") or (view.item_price_gp(item) or 0))
            except ValueError:
                self.show_problem(tr("The price must be a number."))
                return
            purse = guard(rt().characters.buy_item, self.name, item, n, each * n)
            if purse is None:
                return
            notify.good(tr("Bought {0}× {1} for {2} gp (left: {3})", n, item, f"{each * n:g}", purse))
        elif self.team:
            if not guard_ok(rt().team.add, item, n):
                return
            notify.good(tr("Added {0}× {1}", n, item))
        else:
            if guard(rt().characters.add_item, self.name, item, n) is None:
                return
            notify.good(tr("Added {0}× {1}", n, item))
        self.done(QDialog.Accepted)
