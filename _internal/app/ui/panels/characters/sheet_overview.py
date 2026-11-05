"""The sheet's Overview: the status band (HP, damage and healing, hit dice, rests, death saves, conditions, exhaustion,
inspiration, XP and levels), the vitals and ability tiles, skills, attacks, class resources and proficiencies; the
condensed version for the battle turn card; the Features tab; the proficiency editor."""
from typing import Dict, List

from PySide6.QtCore import QSize, Qt
from PySide6.QtGui import QIntValidator
from PySide6.QtWidgets import QCompleter, QGridLayout, QSplitter, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget

from ....core.i18n import tr
from ....services.battle import icons
from ....services.characters import view
from ... import dialogs, notify
from ...errors import guard, report
from ...widgets.common import (Columns, EvenGrid, FlowLayout, button, card, check, clear_layout, col, combo, label, line_edit,
                               row, stretch, widget)
from ...widgets.text import TextView
from .sheet_widgets import Chip, bare, clickable, flow, pips, rich_tip, section, sign, tile

SAVE_HINT = "Click the number for a check, the line below for a saving throw."


# ---------------------------------------------------------------------- the whole tab
def build_overview(sheet, d: dict, lay):
    build_overview_head(sheet, d, lay)
    lay.addWidget(overview_body(sheet, d))


def build_overview_head(sheet, d: dict, lay):
    """What a hit or a heal changes: the hit points band and the tiles."""
    lay.addWidget(status(sheet, d))
    lay.addWidget(tiles(sheet, d))
    extra = [x for x in d["doc"]["vitals_extra"]                # (conditions, exhaustion and inspiration light up above)
             if not x.startswith(("Conditions:", "Exhaustion", "Inspiration"))]
    if extra:
        lay.addWidget(label(" · ".join(tr(x) for x in extra), role="dim", wrap=True))


def overview_body(sheet, d: dict) -> QWidget:
    """Skills, attacks, combat options, resources and proficiencies (the sheet keeps it while they stay the same)."""
    left = col(skills(sheet, d), stretch(), spacing=5)
    right = col(attacks(sheet, d), combat_options(sheet, d), resources(sheet, d), proficiencies(sheet, d), stretch(), spacing=5)
    return Columns(widget(left), widget(right), stretches=(2, 3))   # stacked in a narrow window


def build_compact(sheet, d: dict, lay):
    build_compact_head(sheet, d, lay)
    compact_body(sheet, d, lay)


def build_compact_head(sheet, d: dict, lay):
    """What a hit or a heal changes in the compact sheet: the hit points band (out of a battle card) and the tiles."""
    if not getattr(sheet, "in_card", False) or d["vitals"]["hp"] == 0:   # a battle card has its own HP row (not the death saves)
        lay.addWidget(status(sheet, d, compact=True))
    lay.addWidget(tiles(sheet, d, compact=True))


def compact_body(sheet, d: dict, lay):
    lay.addWidget(_SkillsFit(sheet, d))
    lay.addWidget(attacks(sheet, d))
    opts = combat_options(sheet, d)
    if opts is not None:
        lay.addWidget(opts)
    res = resources(sheet, d)
    if res is not None:
        lay.addWidget(res)


# ---------------------------------------------------------------------- status band
def _amount_box(sheet):
    box = line_edit(placeholder=tr("amt"), width=52, tip=tr("Amount of damage, healing or temporary HP"))
    box.setValidator(QIntValidator(0, 999999, box))

    def hp(kind: str):
        text = box.text().strip()
        if not text:
            notify.warn(tr("Enter the amount first."))
            return
        if kind != "temp" and sheet.hp_hook and guard(sheet.hp_hook, sheet.name, kind, int(text)):
            box.clear()                                  # the battle dealt it (concentration checks and the battle log)
            return
        method = {"damage": "damage", "heal": "heal", "temp": "set_temp_hp"}[kind]
        result = sheet.call(method, int(text))
        if result is not None:
            box.clear()
    box.returnPressed.connect(lambda: hp("damage"))
    return box, hp


def status(sheet, d: dict, compact: bool = False):
    v, name = d["vitals"], d["name"]
    hp_text = f"HP {v['hp']}/{v['max_hp']}" + (f" (+{v['temp_hp']})" if v["temp_hp"] else "")
    hp_label = label(f"<b>{hp_text}</b>", tip=rich_tip(tr("Hit points") + "\n" + tr("AC: {0}", v["ac_note"])))
    f = hp_label.font()
    f.setPointSize(f.pointSize() + 2)
    hp_label.setFont(f)
    amount, hp = _amount_box(sheet)
    rows = []
    from ...theme import COLORS
    from ...widgets.icons import icon_button
    first = [hp_label, amount,
             icon_button("damage", lambda: hp("damage"), tr("Damage: take the amount off the hit points (Enter)"), color=COLORS["bad"]),
             icon_button("heal", lambda: hp("heal"), tr("Heal the amount"), color=COLORS["good"]),
             icon_button("temp_hp", lambda: hp("temp"), tr("Set temporary hit points (they don't stack: the larger pool stays)"),
                         color="#7dd3fc")]
    if not compact:
        first.append(icon_button("max_hp", lambda: _max_hp(sheet, d), tr("Adjust max HP by a flat amount")
                                 + (f"\n{tr('Now')}: {sign(d['hp_bonus'])}" if d.get("hp_bonus") else ""),
                                 color=COLORS["warn"] if d.get("hp_bonus") else COLORS["dim"]))
        rest = [stretch()]                               # hit dice and rests: on the right, or under it in a narrow window
        for cls, hd in d["hit_dice"].items():
            left = hd["total"] - hd["used"]
            rest.append(icon_button("hit_die", lambda c=cls: _hit_die(sheet, c),
                                    tr("Spend a {0} hit die", tr(cls)) + f" (d{hd['die']})\n" + tr("{0} of {1} left", left, hd["total"]),
                                    color=COLORS["text"] if left else COLORS["dim"], text=f"d{hd['die']} {left}/{hd['total']}"))
        rest.append(icon_button("short_rest", lambda: sheet.call("short_rest"),
                                tr("Short rest") + "\n" + tr("Recover the features that come back on a short rest; spend hit dice to heal."),
                                color=COLORS["warn"]))
        rest.append(icon_button("long_rest", lambda: _long_rest(sheet, name),
                                tr("Long rest") + "\n" + tr("Restore HP, spell slots, hit dice and features."), color=COLORS["accent"]))
        rows.append(Columns(bare(widget(row(*first, stretch()))), bare(widget(row(*rest))), stretches=(1, 0)))
    else:
        first.append(stretch())
        rows.append(row(*first))
    if v["hp"] == 0:
        s = d["death_saves"]
        dots = lambda n: "●" * n + "○" * max(0, 3 - n)
        adjust = lambda kind, n: sheet.call("adjust_death_save", kind, n)
        rows.append(row(label(f"<b>{tr('Death saves')}</b>", role="warn"),
                        button("🎲", lambda: _death_save(sheet, None), kind="primary", tip=tr("Roll a death saving throw")),
                        8, label(f"<b>✔ {dots(s['success'])}</b>", role="warn"),
                        button("−", lambda: adjust("success", -1), width=26, tip=tr("Remove a success")),
                        button("+", lambda: adjust("success", 1), width=26, tip=tr("Record a success")),
                        8, label(f"<b>✘ {dots(s['failure'])}</b>", role="warn"),
                        button("−", lambda: adjust("failure", -1), width=26, tip=tr("Remove a failure")),
                        button("+", lambda: adjust("failure", 1), kind="danger", width=26, tip=tr("Record a failure")),
                        stretch()))
    if not compact:
        rows.append(conditions(sheet, d))
        rows.append(experience(sheet, d))
    return card(*rows, spacing=4)


def condition_tip(name: str, on: bool) -> str:
    """A condition's hover text: its name, the rules, and what a click does."""
    from ....rules.data import rules
    text = (rules.conditions.get(name) or {}).get("text", "")
    return f"**{tr(name)}**" + (f"\n{tr(text)}" if text else "") + "\n\n" + (tr("Click to end it.") if on else tr("Click to apply it."))


def conditions(sheet, d: dict):
    """The conditions as a row of pictures - lit and coloured when on, the rules on hover - then exhaustion and
    inspiration."""
    from ....services.battle.icons import CONDITIONS
    from ...theme import COLORS
    from ...widgets.icons import icon_button
    host = bare(QWidget())
    lay = FlowLayout(host, spacing=1)
    lay.addWidget(label(tr("Conditions"), role="dim"))
    for c in d["all_conditions"]:
        if c == "Exhaustion":
            continue
        on = c in d["conditions"]
        lay.addWidget(icon_button(c, lambda c=c, on=on: sheet.call("set_condition", c, not on), condition_tip(c, on),
                                  color=CONDITIONS.get(c, ("", COLORS["warn"]))[1], checked=on, fallback=tr(c)[:2]))
    on_now = [tr(c) for c in d["all_conditions"] if c in d["conditions"] and c != "Exhaustion"]
    if on_now:
        lay.addWidget(label(" · ".join(on_now), role="warn"))
    exh = combo([(str(i), i) for i in range(7)], current=d["exhaustion"], width=40,
                on_change=lambda n: sheet.call("set_exhaustion", n), tip=tr("Exhaustion level (0-6)"))
    tired = icon_button("exhaustion", None, tr("Exhaustion level (0-6)"), color=COLORS["warn"] if d["exhaustion"] else COLORS["dim"])
    tired.setEnabled(True)
    insp = icon_button("inspiration", lambda: sheet.call("toggle_inspiration"),
                       tr("Inspiration") + "\n" + (tr("Click to spend it.") if d["inspiration"] else tr("Click to give it.")),
                       color=COLORS["warn"], checked=bool(d["inspiration"]))
    lay.addWidget(bare(widget(row(8, tired, exh, 4, insp, spacing=1))))
    return host


def experience(sheet, d: dict):
    xp = line_edit(placeholder=tr("xp"), width=60, tip=tr("XP to add (negative takes it away)"))
    xp.setValidator(QIntValidator(-10 ** 9, 10 ** 9, xp))

    def add():
        if xp.text().strip() and sheet.call("add_xp", int(xp.text())) is not None:
            xp.clear()
    xp.returnPressed.connect(add)
    text = tr("{0} XP", d["xp"]) + (" · " + tr("next level at {0}", d["next_xp"]) if d["next_xp"] else " · " + tr("max level"))
    # (editing the levels or the creation and undoing a level-up live in the header's ⋯ menu)
    return row(label(text, role="dim"), xp, button(tr("+XP"), add),
               check(tr("Milestone"), bool(d["milestone"]), lambda on: sheet.call("set_milestone", on),
                     tip=tr("Milestone leveling: level up without XP")),
               stretch())


def _max_hp(sheet, d):
    n = dialogs.ask_int(sheet, tr("Max HP adjustment"), tr("Flat bonus or penalty to max HP"), d["hp_bonus"], -1000, 1000)
    if n is not None:
        sheet.call("set_hp_adjustment", n)


def _hit_die(sheet, cls: str):
    r = sheet.call("spend_hit_die", cls)
    if r is not None:
        sheet.say(tr("Spent a hit die: rolled {0}, healed {1}", r[0], r[1]))


def _long_rest(sheet, name: str):
    if dialogs.confirm(sheet, tr("Restore {0} fully (HP, spell slots, features)?", name), tr("Long rest")):
        sheet.call("long_rest")


def _death_save(sheet, result):
    if result is None and sheet.name:                    # in a battle with async rolling, it rolls on every screen
        from ....core.runtime import rt
        try:
            out = rt().battle.roll_death_save(sheet.name)
        except Exception as e:  # noqa: BLE001 - shown like any other failed call
            report(e)
            return
        if out is not None:
            sheet.say(out, "warn")
            return
    r = sheet.call("death_save", result)
    if r is not None:
        sheet.say(r.text, "warn")


# ---------------------------------------------------------------------- tiles, skills, attacks
def tiles(sheet, d: dict, compact: bool = False) -> QWidget:
    doc = d["doc"]
    host, abil = QWidget(), QWidget()                   # the abilities wrap as their own row, not after whatever fits
    lay = FlowLayout(host, spacing=4)
    abil_lay = FlowLayout(abil, spacing=4)
    boxes = []
    for t in doc["vitals"]:
        if compact and t["label"] not in ("Armor Class", "Initiative", "Speed", "Passive Perception"):
            continue
        caption = tr(t["label"]).replace(tr("Passive Perception"), tr("Passive Perc."))
        short = {"Armor Class": "AC", "Initiative": "Init", "Passive Perception": "Passive"}.get(t["label"]) if compact else None
        box = tile(tr(short) if short else caption, t["value"],                  # (compact: the four fit a narrow card's row)
                   f"**{tr(t['label'])}**\n{t['tip']}" if short and t["tip"] else t["tip"])
        if compact:
            box.setMinimumWidth(52)                          # (four of them in a ~250 px card, "Pasif" too)
        lay.addWidget(box)
    for a in doc["abilities"]:
        mod = clickable(sign(a["mod"]), lambda k=a["key"]: sheet.roll("roll_check", k),
                        tip=tr("{0} check", tr(a["name"])), big=True)
        gap = "·" if compact else f" · {tr('save')} "      # compact (the battle card): the six fit a row; "save" is on hover
        save = clickable(f"{a['score']}{gap}{sign(a['save'])}{'●' if a['save_prof'] else ''}",
                         lambda k=a["key"]: sheet.roll("roll_save", k), tip=a["save_tip"])
        cap = label(tr(a["short"]), role="dim")
        cap.setAlignment(Qt.AlignCenter)
        box = card(cap, mod, save, spacing=0)
        box.layout().setContentsMargins(4, 2, 4, 2)
        if compact:                                     # a narrow card: 6 in a row, or 3 + 3 (EvenGrid) - never cut
            box.setFixedWidth(46)
            box.layout().setContentsMargins(1, 2, 1, 2)
            save.setStyleSheet("QPushButton { padding: 0; border: 0; font-size: 8pt; }")
        box.layout().setAlignment(mod, Qt.AlignHCenter)
        box.layout().setAlignment(save, Qt.AlignHCenter)
        box.setToolTip(rich_tip(a["tip"] + "\n\n" + tr(SAVE_HINT)))
        boxes.append(box)
    if compact:
        abil = EvenGrid(*boxes)
    else:
        for box in boxes:
            abil_lay.addWidget(box)
    return widget(col(host, abil, spacing=4))


def skills(sheet, d: dict, columns: int = 1):
    grid = QGridLayout()
    grid.setHorizontalSpacing(4)
    grid.setVerticalSpacing(0)
    rows = d["doc"]["skills"]
    per = (len(rows) + columns - 1) // columns
    for i, s in enumerate(rows):
        r, c = i % per, (i // per) * 4
        tip = s["tip"] + "\n\n" + tr("Click to roll.")
        mark = label(s["marker"], role="accent" if s["marker"] != "○" else "dim", tip=rich_tip(tip))
        name = clickable(tr(s["name"]), lambda n=s["name"]: sheet.roll("roll_check", n), tip=tip)
        bonus = clickable(sign(s["bonus"]), lambda n=s["name"]: sheet.roll("roll_check", n), tip=tip)
        grid.addWidget(mark, r, c)
        grid.addWidget(name, r, c + 1)
        grid.addWidget(label(tr(s["ability"]), role="dim"), r, c + 2)
        grid.addWidget(bonus, r, c + 3, Qt.AlignRight)
        grid.setColumnStretch(c + 1, 1)
    return section(tr("Skills"), grid)


class _SkillsFit(QWidget):
    """The skills in two columns while they fit, else in one (a narrow battle card): never wider than one column."""

    def __init__(self, sheet, d: dict):
        super().__init__()
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        self.two, self.one = skills(sheet, d, columns=2), skills(sheet, d, columns=1)
        lay.addWidget(self.two)
        lay.addWidget(self.one)
        self.one.hide()

    def minimumSizeHint(self) -> QSize:
        return QSize(self.one.minimumSizeHint().width(), super().minimumSizeHint().height())

    def resizeEvent(self, e):
        two = e.size().width() >= self.two.minimumSizeHint().width()
        if self.two.isHidden() == two:
            self.two.setVisible(two)
            self.one.setVisible(not two)
            self.updateGeometry()                         # a column more or less: the sheet makes room for it
        super().resizeEvent(e)


def attacks(sheet, d: dict):
    doc = d["doc"]
    lines = []
    for a in doc["attacks"]:
        tip = a["tip"] + ("\n" + a["notes"] if a["notes"] else "")
        pic = icons.path(icons.for_attack(a["weapon"] or a["name"]) or "")      # the weapon's picture
        img = f"<img src='{pic}' width='14' height='14'>&nbsp;" if pic else ""
        lines.append(row(label(f"{img}<b>{tr(a['name'])}</b>", tip=rich_tip(tip)), stretch(),
                         label(f"{sign(a['attack'])} · {a['damage']}", role="dim", tip=rich_tip(tip), wrap=True),   # (wraps in a narrow card)
                         button(tr("Attack"), lambda w=a["weapon"]: sheet.attack(w),
                                tip=tr("Roll the attack, then the damage (doubled dice on a natural 20)"))))
    if not lines:
        lines.append(label(tr("No attacks."), role="dim"))
    for n in doc["defense_notes"]:
        lines.append(label(tr(n), role="warn" if n.startswith("Not proficient") else "dim", wrap=True))
    return section(tr("Attacks"), *lines)


def toggle_tip(t: dict) -> str:
    """The hover text of a feat switch: what it does in battle, then the feat's own text."""
    kind = {"power": "Click to turn it on for your attacks.", "auto": "On: the battle applies it by itself.",
            "reaction": "On: it is offered when it applies.", "option": "Pick the damage type."}[t["kind"]]
    return f"{tr(t['feat'])}\n{tr(t['does'])}\n\n{tr(kind)}" + (f"\n\n{tr(t['text'])}" if t.get("text") else "")


def combat_options(sheet, d: dict):
    """Situational feats as switches (Great Weapon Master's power attack, Sentinel, Lucky...)."""
    toggles = d.get("toggles") or []
    if not toggles:
        return None
    chips = []
    for t in toggles:
        if t["kind"] == "option":
            chips.append(combo([(tr("{0}: off", tr(t["label"])), "")] + [(f"{tr(t['label'])}: {tr(o)}", o) for o in t["options"]],
                               current=t["on"] or "", on_change=lambda v, k=t["key"]: sheet.call("set_toggle", k, v or False),
                               tip=rich_tip(toggle_tip(t))))
            continue
        chips.append(Chip(("● " if t["on"] else "○ ") + tr(t["label"]), lambda k=t["key"], on=t["on"]: sheet.call("set_toggle", k, not on),
                          tip=toggle_tip(t), checked=bool(t["on"])))
    return section(tr("Combat options"), flow(*chips))


def resources(sheet, d: dict):
    rows = d["doc"]["resource_rows"]
    if not rows:
        return None
    from ...theme import COLORS
    from ...widgets.icons import game_pixmap
    lines = []
    for r in rows:                  # a pip per use (click a full one to use it, an empty one to get it back); big pools as numbers
        n, short = r["name"], r["recharge"] == "short"
        use = lambda n=n: sheet.call("use_resource", n, 1)          # noqa: E731
        back = lambda n=n: sheet.call("use_resource", n, -1)        # noqa: E731
        rest = label("", tip=tr("Comes back on a short rest") if short else tr("Comes back on a long rest"))
        pm = game_pixmap("short_rest" if short else "long_rest", 14, COLORS["warn"] if short else COLORS["accent"])
        if pm:                                                      # (no picture without the icon module)
            rest.setPixmap(pm)
        else:
            rest.setText("☾" if not short else "◔")
        bits = [label(tr(n)), rest, stretch()]
        if r["max"] is not None and r["max"] <= 10:
            bits += pips(r["max"] - r["used"], r["max"], use, back, tr(n))
        else:
            left = "∞" if r["max"] is None else r["max"] - r["used"]
            most = "∞" if r["max"] is None else r["max"]
            bits += [label(f"{left}/{most}", role="dim"),
                     button("−", use, kind="flat", width=22, tip=tr("Use one")), button("+", back, kind="flat", width=22, tip=tr("Give back one use"))]
        lines.append(row(*bits, spacing=1))
    return section(tr("Resources"), *lines)


def proficiencies(sheet, d: dict):
    groups = d["doc"]["proficiency_list"]
    lines = []
    for g in groups:
        chips = [Chip(tr(p["name"]), tip=f"{p['name']}\n" + tr("From {0}", p["origin"]),
                      kind="primary" if "by hand" in p["origin"] else "flat") for p in g["items"]]
        lines.append(label(tr(g["title"]) + (":" if chips else ": —"), role="dim"))
        if chips:
            lines.append(flow(*chips))
    edit = button(tr("Edit"), lambda: ProficiencyDialog(sheet, d["name"], groups).exec(),
                  tip=tr("Edit proficiencies: swap or remove what the race, background or class gave, or add your own."))
    return section(tr("Proficiencies"), *lines, extra=edit)


# ---------------------------------------------------------------------- the proficiency editor
class ProficiencyDialog(dialogs.Dialog):
    """Change a character's armor, weapon, tool and language proficiencies; each entry shows where it came from."""

    def __init__(self, parent, name: str, groups: List[dict]):
        super().__init__(parent, tr("Proficiencies — {0}", name), 600)
        self.name, self.groups = name, groups
        self.lists: Dict[str, List[dict]] = {g["kind"]: [dict(i) for i in g["items"]] for g in groups}
        self.options = guard(view.proficiency_options) or {}
        self.body.addWidget(label(tr("Hover an entry for its origin. Removing one granted by the race or background "
                                     "and adding another is how you swap it (a racial language, say)."), role="dim", wrap=True))
        self.sections = col(spacing=6)
        self.body.addLayout(self.sections)
        self.ok_cancel(tr("Save"), self.save)
        self.draw()

    def draw(self):
        clear_layout(self.sections)
        for g in self.groups:
            kind = g["kind"]
            have = {i["name"].lower() for i in self.lists[kind]}
            chips = [Chip(tr(p["name"]) + "  ✕", lambda k=kind, i=i: self.remove(k, i),
                          tip=f"{p['name']}\n" + tr("From {0}", p["origin"]) + "\n\n" + tr("Click to remove."),
                          kind="primary" if "by hand" in p["origin"] else "")
                     for i, p in enumerate(self.lists[kind])]
            entry = line_edit(placeholder=tr("add {0}…", tr(g["title"]).lower()))
            comp = QCompleter([o for o in self.options.get(kind, []) if o.lower() not in have], entry)
            comp.setCaseSensitivity(Qt.CaseInsensitive)
            comp.setFilterMode(Qt.MatchContains)
            entry.setCompleter(comp)
            entry.returnPressed.connect(lambda k=kind, e=entry: self.add(k, e.text()))
            self.sections.addWidget(card(label(f"<b>{tr(g['title'])}</b>"),
                                         flow(*chips) if chips else label(tr("none"), role="dim"),
                                         row(entry, button(tr("Add"), lambda k=kind, e=entry: self.add(k, e.text()))),
                                         spacing=3))

    def add(self, kind: str, text: str):
        text = text.strip()
        if text and text.lower() not in {i["name"].lower() for i in self.lists[kind]}:
            self.lists[kind].append({"name": text, "origin": "added by hand"})
            self.draw()

    def remove(self, kind: str, index: int):
        self.lists[kind].pop(index)
        self.draw()

    def save(self):
        from ....core.runtime import rt
        for g in self.groups:
            now = [i["name"] for i in self.lists[g["kind"]]]
            if now != [i["name"] for i in g["items"]]:
                if guard(rt().characters.set_proficiencies, self.name, g["kind"], now) is None:
                    return
        notify.good(tr("Proficiencies saved."))
        self.accept()


# ---------------------------------------------------------------------- features
class FeaturesTab(QSplitter):
    """Features and traits by where they come from; the selected one's full text below."""

    def __init__(self, parent=None):
        super().__init__(Qt.Vertical, parent)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels([tr("Feature"), tr("Level"), tr("Book")])
        self.tree.setColumnWidth(0, 260)
        self.tree.setColumnWidth(1, 44)
        self.tree.setUniformRowHeights(True)
        self.tree.currentItemChanged.connect(lambda cur, _p: self._show(cur))
        self.text = TextView(heading_first_line=True)
        self.text.setPlaceholderText(tr("Select a feature to read it."))
        self.addWidget(self.tree)
        self.addWidget(self.text)
        self.setStretchFactor(0, 3)
        self.setStretchFactor(1, 2)
        self.text.hide()                                      # no empty reading pane: it opens with a feature (hover reads too)
        self._name = None

    def set_data(self, d: dict):
        current = self.tree.currentItem()
        keep = current.data(0, Qt.UserRole + 1) if current is not None else None
        closed = {self.tree.topLevelItem(i).text(0) for i in range(self.tree.topLevelItemCount())
                  if not self.tree.topLevelItem(i).isExpanded()} if self._name == d["name"] else set()
        self._name = d["name"]
        self.tree.blockSignals(True)
        self.tree.clear()
        select = None
        for g in d["doc"]["features"]:
            head = QTreeWidgetItem([tr(g["source"])])
            head.setFirstColumnSpanned(True)
            f = head.font(0)
            f.setBold(True)
            head.setFont(0, f)
            self.tree.addTopLevelItem(head)
            for feat in g["items"]:
                it = QTreeWidgetItem([tr(feat["name"]), str(feat["level"]) if feat["level"] else "", feat["book"] or ""])
                it.setData(0, Qt.UserRole, f"{tr(feat['name'])}\n{tr(feat['text'])}")
                it.setData(0, Qt.UserRole + 1, f"{g['source']}|{feat['name']}")
                it.setToolTip(0, rich_tip(feat["tip"])[:3000])
                head.addChild(it)
                if it.data(0, Qt.UserRole + 1) == keep:
                    select = it
            head.setExpanded(tr(g["source"]) not in closed)
        self.tree.blockSignals(False)
        if select is not None:
            self.tree.setCurrentItem(select)
        elif not d["doc"]["features"]:
            self.text.set_text(tr("No features yet."))
            self.text.show()
        else:
            self.text.hide()                                  # (another character: nothing picked yet)

    def _show(self, it):
        text = it.data(0, Qt.UserRole) if it is not None else None
        if text:
            self.text.set_text(text)
            self.text.show()
