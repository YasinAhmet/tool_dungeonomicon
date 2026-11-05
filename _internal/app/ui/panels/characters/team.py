"""The Team inventory (a section of the Party window): the pack the characters playing this session share, and the group's
supplies - its food is the food the World map's travel column counts (a day's meals are eaten from here).

Who shares it, as chips (drop a row on one: handed to that character); the supplies (meals, how long they last, more
rations); a quick entry line (a name, a description, how many: anything, not only the item list's) beside the item
search; a filter; and the items in groups (supplies, magic items, weapons and armor, gear, custom), each row with its
picture, amount and description and its buttons (one fewer or more, change it, give it, take it out). Players move
items in and out, write in and change their own entries on the portal. Drop an item here from a sheet's inventory to
move it in (or from the item search to add it); drag a row onto the Battle map to lay it on a tile (onto a creature: it
is handed over). Moving more than one asks how many."""
import json

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QGridLayout, QVBoxLayout

from ....core import events
from ....core.i18n import tr
from ....core.runtime import rt
from ....rules.data import rules
from ....rules.document import _item_tip
from ... import dialogs, notify
from ...errors import guard, guard_ok
from ...panel import Panel
from ...widgets.common import button, clear_layout, label, line_edit, row, scroll, stretch, widget
from ...widgets.search import DRAG_MIME
from .sheet_inventory import AddItemDialog, QuickEntry, _ItemDrag, edit_form, item_text, with_note
from .sheet_widgets import Chip, bare, flow, rich_tip, section

GROUPS = (("food", "🍖 Supplies"), ("magic", "✦ Magic items"), ("arms", "⚔ Weapons and armor"), ("gear", "🎒 Gear"),
          ("custom", "📝 Custom"))
ARMS = ("M", "R", "LA", "MA", "HA", "S")


def how_many(parent, item: str, qty: int, verb: str = "") -> int:
    """1 when there is one; otherwise ask (0: cancelled)."""
    if qty <= 1:
        return 1
    got = dialogs.form(parent, verb or tr("Move {0}", tr(item)), [
        {"key": "n", "label": tr("How many (of {0})", qty), "kind": "int", "value": qty, "min": 1, "max": qty}], tr("OK"))
    return int(got["n"]) if got else 0


def group_of(e: dict) -> str:
    if e.get("food"):
        return "food"
    data = rules.item(e["name"])
    if not data:
        return "custom"
    if data.get("rarity") not in (None, "none"):
        return "magic"
    return "arms" if data.get("weapon") or str(data.get("type") or "").split("|")[0] in ARMS else "gear"


def _payload(e):
    if not e.mimeData().hasFormat(DRAG_MIME):
        return None
    try:
        return json.loads(bytes(e.mimeData().data(DRAG_MIME)).decode())
    except ValueError:
        return None


class _Member(Chip):
    """A character sharing the pack: drop a team row here to hand it over."""
    def __init__(self, panel, name: str):
        super().__init__(name, tip=tr("Drop an item from the list here to give it to {0}", name))
        self.panel, self.name = panel, name
        self.setAcceptDrops(True)

    def dragEnterEvent(self, e):
        if (_payload(e) or {}).get("kind") == "team_item":
            e.acceptProposedAction()

    def dropEvent(self, e):
        p = _payload(e) or {}
        if p.get("kind") != "team_item":
            return
        e.acceptProposedAction()
        n = how_many(self.panel, p["item"], int(p.get("qty") or 1), tr("Give {0} to {1}", tr(p["item"]), self.name))
        if n and guard_ok(rt().team.take, p["item"], n, self.name):
            notify.good(tr("Gave {0}× {1} to {2}", n, tr(p["item"]), self.name))


class TeamPanel(Panel):
    def build(self):
        self.setAcceptDrops(True)
        lay = self.layout()
        # ---- who shares it
        self.chips = QVBoxLayout()
        self.chips.setContentsMargins(0, 0, 0, 0)
        lay.addLayout(self.chips)
        # ---- the supplies: the World map's food
        self.food = label("", wrap=True)
        self.food.setTextFormat(Qt.RichText)
        lay.addWidget(section(tr("Supplies"), self.food, extra=bare(widget(row(
            button(tr("+ Rations…"), self.add_rations, tip=tr("Rations bought, hunted or found (the World map's food)")),
            button(tr("Spend…"), self.spend, tip=tr("Food spent on something (horses, a feast, a bribe…)")))))))
        # ---- writing items in
        self.quick = QuickEntry(lambda name, n, desc: guard_ok(rt().team.add, name, n, desc))
        self.filter = line_edit(placeholder=tr("Filter"), width=150)
        self.filter.textChanged.connect(lambda _t: self.refresh())
        lay.addWidget(section(tr("Put something in"), self.quick, extra=bare(widget(row(
            button(tr("Search…"), lambda: AddItemDialog(self, "", team=True).exec(),
                   tip=tr("Put loot in from the item list (or a custom name)")))))))
        # ---- the items
        lay.addLayout(row(label(tr("In the pack"), role="title"), stretch(), self.filter))
        self.list = QVBoxLayout()
        self.list.setContentsMargins(0, 0, 0, 0)
        self.list.setSpacing(4)
        box = bare(widget(self.list))
        lay.addWidget(scroll(box), 1)
        lay.addWidget(label(tr("Drop items here from a sheet or the item search; drag a row onto a character above or "
                               "onto the Battle map."), role="dim", wrap=True))
        self.on(events.TEAM, self.refresh)
        self.on(events.CHARACTERS, self.refresh)
        self.on(events.WORLD, self._supplies)                # (the day, who eats: not the list - the map's brush strokes)

    def refresh(self):
        team = rt().team
        members = team.members()
        clear_layout(self.chips)
        chips = [label(tr("Shared by"), role="dim")] + [_Member(self, n) for n in members] if members else \
            [label(tr("No one plays this session yet: tick who plays in the Party tab."), role="dim")]
        self.chips.addWidget(flow(*chips, spacing=4))
        self._supplies()
        self._items(team.items())

    def _supplies(self):
        f = rt().world.food()
        bits = [f"<span style='font-size:15px; font-weight:600'>{tr('🍖 {0} meals', f['meals'])}</span>",
                tr("{0} eat each day", f["mouths"])]
        if f["days_left"] is not None:
            last = tr("lasts about {0} days", f"{f['days_left']:g}")
            bits.append(f"<span style='color:#f87171'>{last}</span>" if f["days_left"] < 2 else last)
        bits.append(tr("Day {0}", f["day"]))
        self.food.setText(" · ".join(bits) + "<br><span style='color:#8b93a3'>" +
                          tr("The food in this pack is the group's food on the World map: each day's meals are eaten "
                             "from it, rations first.") + "</span>")

    def _items(self, items):
        clear_layout(self.list)
        want = self.filter.text().strip().lower()
        if want:
            items = [e for e in items if want in e["name"].lower() or want in tr(e["name"]).lower() or want in e["note"].lower()]
        groups = {}
        for e in sorted(items, key=lambda e: tr(e["name"]).lower()):
            groups.setdefault(group_of(e), []).append(e)
        for key, heading in GROUPS:
            if key not in groups:
                continue
            grid = QGridLayout()
            grid.setHorizontalSpacing(3)
            grid.setVerticalSpacing(1)
            grid.setColumnStretch(0, 1)
            for r, e in enumerate(groups[key]):
                self._row(grid, r, e)
            count = sum(e["qty"] for e in groups[key])
            self.list.addWidget(section(f"{tr(heading)}  <span style='color:#8b93a3'>{count}</span>", bare(widget(grid))))
        if not items:
            self.list.addWidget(label(tr("Nothing matches.") if want else tr("Nothing in the team inventory."), role="dim"))
        self.list.addStretch(1)

    def _row(self, grid, r: int, e: dict):
        team = rt().team
        name, qty = e["name"], e["qty"]
        w = label(item_text(e), tip=rich_tip(with_note(_item_tip(None, e), e)), wrap=True)
        _ItemDrag(w, {"kind": "team_item", "item": name, "qty": qty})
        grid.addWidget(w, r, 0)
        acts = [button("−", lambda: guard(team.set_qty, name, qty - 1) if qty > 1 else self.remove(name, qty),
                       tip=tr("One fewer"), width=26),
                button("+", lambda: guard(team.set_qty, name, qty + 1), tip=tr("One more"), width=26),
                button("✎", lambda: self.edit(e), tip=tr("Change its name, amount or description"), width=26),
                button("➜", lambda: self.give(name, qty), tip=tr("Give to a character"), width=28),
                button("✕", lambda: self.remove(name, qty), kind="danger", tip=tr("Take it out"), width=26)]
        grid.addWidget(bare(widget(row(*acts, spacing=2))), r, 1, Qt.AlignRight | Qt.AlignTop)

    # ------------------------------------------------------------------ actions
    def edit(self, e: dict):
        got = edit_form(self, e)
        if got:
            guard(rt().team.edit, e["name"], got["qty"], got["note"], got["name"])

    def give(self, item: str, qty: int):
        names = rt().team.members() or rt().characters.names()
        if not names:
            notify.warn(tr("There is no character to give it to."))
            return
        got = dialogs.form(self, tr("Give {0}", tr(item)), [
            {"key": "to", "label": tr("To"), "kind": "select", "options": names},
            {"key": "n", "label": tr("How many"), "kind": "int", "value": qty, "min": 1, "max": max(1, qty)}], tr("Give"))
        if got and guard_ok(rt().team.take, item, got["n"], got["to"]):
            notify.good(tr("Gave {0}× {1} to {2}", got["n"], tr(item), got["to"]))

    def remove(self, item: str, qty: int):
        if qty == 1 or dialogs.confirm(self, tr("Take all {0}× {1} out of the team inventory?", qty, tr(item)), tr("Remove item")):
            guard(rt().team.remove, item)

    def add_rations(self):
        got = dialogs.form(self, tr("Add food"), [
            {"key": "n", "label": tr("Meals"), "kind": "int", "value": 5, "min": 1, "max": 9999},
            {"key": "why", "label": tr("From"), "value": "", "tip": tr("Bought, hunted, foraged… (optional)")}], tr("Add"))
        if got:
            guard(rt().world.add_food, got["n"], got["why"])

    def spend(self):
        got = dialogs.form(self, tr("Spend food"), [
            {"key": "n", "label": tr("Meals"), "kind": "int", "value": 1, "min": 1, "max": 9999},
            {"key": "why", "label": tr("On"), "value": ""}], tr("Spend"))
        if got:
            guard(rt().world.spend_food, got["n"], got["why"])

    # ------------------------------------------------------------------ drops: from a sheet (moved in) or the item search (added)
    @staticmethod
    def _accepts(e):
        p = _payload(e)
        return p if p and p.get("kind") in ("inv_item", "item") else None

    def dragEnterEvent(self, e):
        if self._accepts(e):
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        if self._accepts(e):
            e.acceptProposedAction()

    def dropEvent(self, e):
        p = self._accepts(e)
        if not p:
            return
        e.acceptProposedAction()
        item = p.get("item") or p.get("name") or ""
        if p["kind"] == "item":
            guard(rt().team.add, item, max(1, int(p.get("qty") or 1)))
            return
        n = how_many(self, item, int(p.get("qty") or 1), tr("Into the team inventory: {0}", tr(item)))
        if n:
            guard(rt().team.put, p["character"], item, n)
