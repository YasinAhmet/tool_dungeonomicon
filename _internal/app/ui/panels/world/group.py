"""The group's column beside the World map: where the party is and where it heads, its food (meals, the day's
spending on average, how many days it lasts - the food in the team inventory, so the two always agree), the day
counter, and the food in each character's pack - a meal from a pack into the group's food in one click (players do it
themselves on the portal)."""
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QGridLayout, QVBoxLayout, QWidget

from ....core import events
from ....core.i18n import tr
from ....core.runtime import rt
from ... import dialogs
from ...errors import guard
from ...widgets.common import button, clear_layout, label, row, stretch


def _days(n) -> str:
    return tr("{0} day", n) if n == 1 else tr("{0} days", n)


class GroupColumn(QWidget):
    def __init__(self, panel):
        super().__init__()
        self.panel = panel
        box = QVBoxLayout(self)
        box.setContentsMargins(6, 4, 6, 4)
        box.setSpacing(5)
        # ---- the party
        box.addWidget(label(tr("THE PARTY"), role="title"))
        self.where = label("", wrap=True)
        self.route = label("", role="dim", wrap=True)
        box.addWidget(self.where)
        box.addWidget(self.route)
        self.take_back = button(tr("↩ Take back the move"), lambda: panel.canvas.take_back(), kind="flat",
                                tip=tr("The party goes back where it was: the days the trip took turn back and the meals "
                                       "eaten on the way go back into the group's food (Ctrl+Z with 🚩)"))
        box.addLayout(row(self.take_back, stretch()))
        box.addLayout(row(button(tr("Clear route"), lambda: guard(rt().world.set_route, []), kind="flat",
                                 tip=tr("Forget where the party is heading")),
                          button(tr("Clear trail"), lambda: guard(rt().world.clear_trail), kind="flat",
                                 tip=tr("Wipe the dotted line of where the party has been")),
                          stretch()))
        box.addWidget(self._line())
        # ---- food
        head = row(label(tr("FOOD"), role="title"), stretch())
        self.day = label("", role="dim")
        head.addWidget(self.day)
        box.addLayout(head)
        self.meals = label("")
        self.meals.setStyleSheet("font-size: 22px; font-weight: 600;")
        self.rate = label("", role="dim", wrap=True)
        self.stock = label("", role="dim", wrap=True)
        box.addWidget(self.meals)
        box.addWidget(self.rate)
        box.addWidget(self.stock)
        box.addLayout(row(button("−1", lambda: guard(rt().world.spend_food, 1, "Spent"), width=34, tip=tr("Spend a meal")),
                          button("+1", lambda: guard(rt().world.add_food, 1), width=34, tip=tr("Add a meal")),
                          button(tr("Add…"), self.add_many, tip=tr("Add food bought, hunted or found")),
                          button(tr("Spend…"), self.spend_many, tip=tr("Spend food on something (horses, a feast, a bribe…)")),
                          stretch()))
        box.addLayout(row(button(tr("🌙 End the day"), self.end_day, kind="primary",
                                 tip=tr("The day ends: everyone eats a meal from the group's food and the day counter goes on")),
                          button(tr("Eaters…"), self.eaters, kind="flat",
                                 tip=tr("How many eat each day (normally everyone sharing the team inventory)")),
                          stretch()))
        box.addWidget(self._line())
        box.addWidget(label(tr("IN THEIR PACKS"), role="title"))
        self.who = label("", role="dim", wrap=True)
        box.addWidget(self.who)
        self.packs = QGridLayout()
        self.packs.setHorizontalSpacing(4)
        self.packs.setVerticalSpacing(2)
        self.packs.setColumnStretch(0, 1)
        box.addLayout(self.packs)
        box.addWidget(label(tr("Players add their own meals to the group from the portal's World map."), role="dim", wrap=True))
        box.addWidget(self._line())
        box.addWidget(label(tr("LATELY"), role="title"))
        self.log = label("", role="dim", wrap=True)
        self.log.setTextFormat(Qt.RichText)
        box.addWidget(self.log)
        box.addStretch(1)
        self._packs_key = None
        panel.on(events.CHARACTERS, self.refresh)           # (events.WORLD: the window refreshes this column)
        panel.on(events.TEAM, self.refresh)

    @staticmethod
    def _line():
        f = QFrame()
        f.setFrameShape(QFrame.HLine)
        f.setStyleSheet("color: #262c37;")
        return f

    def refresh(self):
        w = rt().world
        p = w.party()
        if p["pos"]:
            near = w.nearest(*p["pos"])
            if near and near["here"]:
                self.where.setText(tr("📍 At {0}", near["name"]))
            elif near:
                self.where.setText(tr("📍 {0} mi from {1}", round(near["miles"]), near["name"]))
            else:
                self.where.setText(tr("📍 Out in the wilds"))
        else:
            self.where.setText(tr("Not on the map yet: pick 🚩 and click where they are."))
        self.take_back.setEnabled(bool(w.moves_back()))
        ri = w.route_info()
        self.route.setText(tr("🧭 Heading on: {0} mi, about {1} at a {2} pace", round(ri["miles"]), _days(ri["days"]),
                              tr(w.settings()["pace"])) if ri["miles"] else tr("No route: pick 🧭 and click the way."))
        f = w.food()
        self.day.setText(tr("Day {0}", f["day"]))
        self.meals.setText(tr("🍖 {0} meals", f["meals"]))
        bits = [tr("{0} eat each day", f["mouths"])]
        if f["average"]:
            bits.append(tr("{0} spent a day on average", f["average"]))
        if f["days_left"] is not None:
            bits.append(tr("lasts about {0}", _days(f["days_left"])))
        self.rate.setText(" · ".join(bits))
        self.rate.setStyleSheet("color: #f87171;" if f["days_left"] is not None and f["days_left"] < 2 else "")
        self.stock.setText(tr("🎒 In the team inventory: {0}", ", ".join(f"{e['qty']}× {tr(e['name'])}" for e in f["stock"]))
                           if f["stock"] else tr("🎒 The team inventory holds no food."))
        self.stock.setToolTip(tr("The group's food is the food in the team inventory (Party window): the two always agree."))
        names = set(rt().characters.names())
        ticked = [n for n in rt().players.session_party() if n in names]
        self.who.setText(tr("The characters ticked as playing in the Party window.") if ticked else
                         tr("No one is ticked as playing this session, so every character with a player counts: tick who "
                            "plays in the Party window."))
        members = w.member_food()
        key = repr((members, f["meals"]))
        if key != self._packs_key:                          # rebuilt only when it changed (not on every brush stroke)
            self._packs_key = key
            self._fill_packs(members, f["meals"])
        lines = []
        for e in reversed(f["log"][-6:]):
            n = e["n"]
            sign = f"<span style='color:#4ade80'>+{n}</span>" if n > 0 else f"<span style='color:#f87171'>{n}</span>"
            who = f" · {e['by']}" if e.get("by") else ""
            lines.append(f"{tr('Day {0}', e['day'])}: {sign} {tr(e['why'])}{who}")
        self.log.setText("<br>".join(lines) or tr("Nothing yet."))

    def _fill_packs(self, members, meals):
        clear_layout(self.packs)
        if not members:
            self.packs.addWidget(label(tr("No one plays this session yet."), role="dim"), 0, 0)
        for r, m in enumerate(members):
            tip = "\n".join(f"{e['qty']}× {tr(e['name'])}" for e in m["items"]) or tr("No food")
            name = label(m["character"], tip=tip)
            self.packs.addWidget(name, r, 0)
            self.packs.addWidget(label(f"🍖 {m['meals']}", role="" if m["meals"] else "dim", tip=tip), r, 1)
            b = button(tr("➜ group"), lambda n=m["character"]: guard(rt().world.give_meal, n, by="The DM"), kind="flat",
                       tip=tr("Move one meal from {0}'s pack into the group's food", m["character"]))
            b.setEnabled(m["meals"] > 0)
            self.packs.addWidget(b, r, 2)
            g = button("➜", lambda n=m["character"]: guard(rt().world.take_meal, n), kind="flat", width=28,
                       tip=tr("Give {0} a ration from the group's food", m["character"]))
            g.setEnabled(meals > 0)
            self.packs.addWidget(g, r, 3)

    # ------------------------------------------------------------------ actions
    def add_many(self):
        got = dialogs.form(self, tr("Add food"), [
            {"key": "n", "label": tr("Meals"), "kind": "int", "value": 5, "min": 1, "max": 9999},
            {"key": "why", "label": tr("From"), "value": "", "tip": tr("Bought, hunted, foraged… (optional)")}], tr("Add"))
        if got:
            guard(rt().world.add_food, got["n"], got["why"])

    def spend_many(self):
        got = dialogs.form(self, tr("Spend food"), [
            {"key": "n", "label": tr("Meals"), "kind": "int", "value": 1, "min": 1, "max": 9999},
            {"key": "why", "label": tr("On"), "value": ""}], tr("Spend"))
        if got:
            guard(rt().world.spend_food, got["n"], got["why"])

    def end_day(self):
        got = guard(rt().world.end_day)
        if got and got["hungry"]:
            dialogs.info(self, tr("Not enough food: {0} went hungry today.", got["hungry"]), tr("Day {0}", got["day"] - 1))

    def eaters(self):
        w = rt().world
        f = w.food()
        got = dialogs.form(self, tr("Who eats"), [
            {"key": "n", "label": tr("Meals a day (0: everyone sharing the team inventory)"), "kind": "int",
             "value": f["mouths_set"] or 0, "min": 0, "max": 99},
            {"key": "day", "label": tr("Day"), "kind": "int", "value": f["day"], "min": 1, "max": 99999}], tr("OK"))
        if got:
            guard(w.set_mouths, got["n"] or None)
            guard(w.set_day, got["day"])
