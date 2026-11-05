"""The combatant card: hit points, damage / heal, conditions, notes, and then for a monster its whole stat block with a
button for every attack, damage roll, recharge, save and spell; for a player character its weapons and spells in
battle, then the compact character sheet."""
import html
from typing import Callable, List, Optional

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QCheckBox, QFrame, QPushButton, QVBoxLayout, QWidget

from ....core.i18n import tr
from ....core.runtime import rt
from ....rules.character import CONDITIONS
from ....services.battle import view as V
from ....services.battle.icons import BADGES
from ... import dialogs, notify
from ...errors import guard, guard_ok
from ...theme import COLORS
from ...widgets.common import ElideLabel, EvenGrid, FlowLayout, button, col, label, line_edit, row, spin, stretch
from ...widgets.icons import AdvSwitch, game_icon, icon_button
from ...widgets.text import to_html
from .common import HoverButton, HpBar, apply_hp, preview_area, say, spell_choice, start_aim, timer_text, type_choice



def flow(*widgets: QWidget, spacing: Optional[int] = None) -> QWidget:
    host = QWidget()
    lay = FlowLayout(host) if spacing is None else FlowLayout(host, spacing=spacing)
    for w in widgets:
        if w is not None:
            lay.addWidget(w)
    return host


def small(rich: str, role: str = "") -> QWidget:
    """A small wrapped label of rich text (escape plain text with to_html)."""
    lab = label(rich, role=role, wrap=True)
    lab.setTextFormat(Qt.RichText)
    f = lab.font()
    f.setPointSize(f.pointSize() - 1)
    lab.setFont(f)
    return lab


def line(name: str, text: str) -> QWidget:
    return small(f"<span style='color:#8b93a3'>{html.escape(tr(name))}</span> {to_html(tr(text))}")


class CombatCard(QWidget):
    """One combatant's card. `prefs` are the panel's choices kept from card to card (advantage, the spell of each
    character)."""

    def __init__(self, c: dict, view: dict, prefs: dict, parent=None):
        super().__init__(parent)
        self.cid = c["id"]
        self.kind = c["kind"]
        self.prefs = prefs
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(4)
        self.box = box
        self.name = label(c["name"])
        f = self.name.font()
        f.setPointSize(f.pointSize() + 2)
        f.setBold(True)
        self.name.setFont(f)
        self.hp_text = label("")
        self.reveal = icon_button("reveal", self._reveal, "", checked=False, color=COLORS["warn"]) if c["kind"] == "enemy" else None
        box.addLayout(row(self.name, ElideLabel(tr(c.get("sub") or ""), role="dim"), stretch(), self.hp_text, self.reveal,
                          icon_button("clear", self._remove, tr("Remove") + "\n" + tr("Take it out of the battle (Undo brings it back)"),
                                      color=COLORS["bad"])))     # (beside the HP: the row below fits a ~250 px Inspector)
        self.bar = HpBar()
        box.addWidget(self.bar)
        self.amount = spin(0, 0, 9999, width=54, tip=tr("Amount (Enter: damage)"))
        self.amount.lineEdit().returnPressed.connect(lambda: self._hp("damage"))
        self.dtype = type_choice()                           # (a picture, not an 86 px box)
        self.half = QCheckBox("½")
        self.half.setToolTip(tr("Saved: half damage"))
        box.addLayout(row(self.amount, self.dtype, self.half,
                          icon_button("damage", lambda: self._hp("damage"), tr("Damage") + "\n" + tr("Amount (Enter: damage)"), color=COLORS["bad"]),
                          icon_button("heal", lambda: self._hp("heal"), tr("Heal"), color=COLORS["good"]),
                          icon_button("temp_hp", self._temp, tr("Set temporary hit points (they don't stack: the larger pool stays)"),
                                      color="#7dd3fc"), stretch(), spacing=2))
        self.conds = {}                                       # pictures, lit in their colour when on; the rules on hover
        for k in CONDITIONS:
            pic = "exhaustion" if k == "Exhaustion" else k
            b = icon_button(pic, None, "", color=(BADGES.get(k) or ("", COLORS["warn"]))[1], checked=False, fallback=tr(k)[:2])
            b.toggled.connect(lambda on, k=k: guard(rt().battle.set_condition, self.cid, k, on))
            self.conds[k] = b
        box.addWidget(flow(*self.conds.values()))
        self.note = line_edit(c.get("notes") or "", tr("Notes…"))
        self.note.editingFinished.connect(self._note)
        box.addWidget(self.note)
        self.extra = small("", role="warn")
        box.addWidget(self.extra)
        self.actions = None
        if (view.get("status") == "active" or c.get("pos")) and prefs.get("_no_bar") != c["id"]:   # (not twice: the map's play bar has it)
            from .actionbar import ActionBar
            self.actions = ActionBar(c["id"], prefs)
            box.addWidget(self.actions)
        self.update_live(c, view)

    # ------------------------------------------------------------------ the numbers that change
    def update_live(self, c: dict, view: dict):
        self.hp_text.setText(f"<b>{c['hp']}/{c['max_hp']}</b>" + (f" +{c['temp_hp']}" if c.get("temp_hp") else "")
                             + " " + tr("HP · AC {0}", c["ac"]))
        self.bar.set_hp(c["hp"], c["max_hp"])
        from ..characters.sheet_overview import condition_tip
        from ..characters.sheet_widgets import rich_tip
        timers = c.get("cond_timers") or {}
        for k, b in self.conds.items():
            on = k in c["conditions"]
            b.blockSignals(True)
            b.setChecked(on)
            b.blockSignals(False)
            b.setToolTip(rich_tip(condition_tip(k, on) + (f"\n({timer_text(timers[k])})" if on and k in timers else "")))
        if self.reveal:
            self.reveal.blockSignals(True)
            self.reveal.setChecked(bool(c.get("revealed")))
            self.reveal.blockSignals(False)
            seen = tr("players see the exact HP") if c["hp_shown"] else tr("players see: {0}", tr(c["health"]))
            self.reveal.setToolTip(rich_tip((tr("Hide exact HP from players") if c.get("revealed") else tr("Reveal exact HP to players"))
                                            + "\n" + seen))
        if not self.note.hasFocus():
            self.note.setText(c.get("notes") or "")
        effects = [f"{e['name']}" + (f" ({e['rounds']} rds)" if e.get("rounds") else "") for e in c.get("effects") or []]
        conc = [tr("Concentrating on {0}", c["concentrating"]["spell"])] if c.get("concentrating") else []
        self.extra.setText(html.escape(" · ".join([tr(x) for x in effects] + conc)))
        self.extra.setVisible(bool(effects or conc))
        if getattr(self, "actions", None) is not None:
            self.actions.refresh()

    # ------------------------------------------------------------------ actions
    def adv_value(self):
        return self.prefs.get("adv")

    def _hp(self, kind: str):
        n = self.amount.value()
        if not n:
            notify.warn(tr("Enter the amount first."))
            return
        if guard(lambda: (apply_hp([self.cid], kind, n, self.dtype.currentData() or None, [self.cid] if self.half.isChecked() else []), True)[1]):
            self.amount.setValue(0)
            self.half.setChecked(False)

    def _temp(self):
        n = self.amount.value()
        if not n:
            notify.warn(tr("Enter the amount first."))
            return
        out = guard(rt().battle.set_temp_hp, self.cid, n)
        if out is not None:
            say(out)
            self.amount.setValue(0)

    def _reveal(self):
        c = V.find(rt().battle.view(), self.cid)
        if c:
            guard(rt().battle.reveal, self.cid, not c.get("revealed"))

    def _note(self):
        guard(rt().battle.set_note, self.cid, self.note.text())

    def _remove(self):
        if dialogs.confirm(self, tr("Remove {0} from the battle?", self.name.text()), tr("Remove")):
            guard(rt().battle.remove, self.cid)

    def adv_box(self) -> QWidget:
        box = AdvSwitch(on_change=lambda v: self.prefs.__setitem__("adv", v), tip=tr("For the rolls below"))
        box.setCurrentIndex(box.findData(self.prefs.get("adv")))
        return box


class MonsterCard(CombatCard):
    def __init__(self, c: dict, view: dict, prefs: dict, parent=None):
        super().__init__(c, view, prefs, parent)
        m = V.monster_card(c["monster"]) if c.get("monster") else None
        if not m:
            return
        self.target = V.find(view, view.get("target"))
        self.menu_items = _menu_items(c["id"])
        b = self.box
        rule = QFrame()
        rule.setFrameShape(QFrame.HLine)
        b.addWidget(rule)
        b.addWidget(small(to_html(tr(m["head"])), role="dim"))
        for k, t in m["lines"]:
            b.addWidget(line(k, t))
        tiles = []
        for a in m["abilities"]:
            ab = a["key"].upper()
            tile = QFrame()
            tile.setObjectName("card")
            tile.setToolTip(tr("{0} {1} - the modifier rolls a check, the line below a saving throw.", ab, a["score"]))
            tile.setLayout(col(label(f"{tr(ab)} {a['score']}", role="dim"),
                               button(f"{a['mod']:+d}", lambda a=a, ab=ab: self._d20(f"{ab} check", a["mod"]), kind="flat",
                                      tip=tr("{0} check", ab)),
                               button(tr("save {0}", f"{a['save']:+d}"), lambda a=a, ab=ab: self._d20(f"{ab} save", a["save"]),
                                      kind="flat", tip=tr("{0} saving throw", ab)), spacing=0, margins=2))
            tile.setFixedWidth(50)                          # 6 in a row, or 3 + 3 in a narrow Inspector (EvenGrid): never cut
            for btn_ in tile.findChildren(QPushButton):
                btn_.setStyleSheet("padding: 1px 0;")
            tile.findChildren(QPushButton)[-1].setStyleSheet("padding: 1px 0; border: 0; font-size: 8pt;")   # the save line
            tiles.append(tile)
        b.addLayout(row(label(tr("Roll"), role="dim"), self.adv_box(), stretch()))
        b.addWidget(EvenGrid(*tiles))
        for k, t in m["more"]:
            b.addWidget(line(k, t))
        for sec in m["sections"]:
            if sec["title"]:
                head = label(tr(sec["title"]), role="accent")
                f = head.font()
                f.setBold(True)
                head.setFont(f)
                b.addWidget(head)
            if sec["note"]:
                b.addWidget(small(to_html(tr(sec["note"])), role="dim"))
            for e in sec["entries"]:
                self._entry(e)
        for heading, text in ((tr("Description"), m["lore"]), (tr("Lair actions"), m["lair"])):
            if text:
                b.addWidget(label(heading, role="accent"))
                b.addWidget(small(to_html(tr(text)), role="dim" if heading == tr("Description") else ""))

    def _entry(self, e: dict):
        name = f"<b>{html.escape(tr(e['name']))}.</b> " if e["name"] else ""
        self.box.addWidget(small(name + to_html(tr(e["text"]))))
        bar: List[QWidget] = []
        if e["kind"] == "spell":
            sp = e["spell"]
            if e["to_hit"] is not None:
                bar.append(button(tr("Spell attack {0}", f"{e['to_hit']:+d}"), lambda: self._d20("spell attack", e["to_hit"])))
            if sp["has_dc"]:
                bar.append(label(tr("Save DC {0}", sp["dc"]), role="dim"))
            if bar:
                self.box.addWidget(flow(*bar))
            for ln in sp["lines"]:
                chips = [label(tr(ln["label"]) + ":", role="dim")]
                for n in ln["spells"]:
                    chip = HoverButton(tr(n), lambda n=n: self._cast(n, sp), on_leave=lambda: preview_area(None))
                    chip._enter = lambda n=n, chip=chip: self._hover(chip, n)
                    chip.setProperty("kind", "flat")
                    chip.setStyleSheet("color: #c4a7ff;")
                    chips.append(chip)
                self.box.addWidget(flow(*chips))
            return
        item = self.menu_items.get(f"monster:{e['name']}") if e["kind"] == "action" else None
        if item and (e["to_hit"] is not None or e["save"]):
            use = button(tr("Use"), lambda: start_aim(self, self.cid, item, None, self.adv_value()), kind="primary",
                         tip=tr("Aim it on the map: the attack or saving throw, damage and conditions are played out"))
            pic = game_icon(item.get("icon") or "", 16)            # the action bar's picture of it
            if not pic.isNull():
                use.setIcon(pic)
            bar.append(use)
        else:
            if e["to_hit"] is not None:
                bar.append(button(tr("Attack {0}", f"{e['to_hit']:+d}"), lambda: self._d20(f"{e['name'] or 'attack'} attack", e["to_hit"])))
            if e["parts"]:
                text = " + ".join(f"{d} {tr(t)}" for d, t in e["parts"])
                bar.append(button(tr("Damage {0}", text), lambda: self._damage(f"{e['name']} damage", e["parts"], False)))
                if e["to_hit"] is not None:
                    bar.append(button(tr("Crit"), lambda: self._damage(f"{e['name']} damage", e["parts"], True),
                                      tip=tr("Critical hit: the damage dice are doubled")))
            if e["announce"]:
                bar.append(button(tr("Use"), lambda: say(guard(rt().battle.announce, self.cid, f"uses {e['name']}")), kind="flat",
                                  tip=tr("Note in the battle log that it uses this")))
        if e["recharge"]:
            bar.append(button(tr("Recharge"), lambda: self._damage(f"{e['recharge']} recharge", [["1d6", ""]], False),
                              tip=tr("Roll a d6 for the recharge")))
        if bar:
            self.box.addWidget(flow(*bar))

    # ---- rolls
    def _d20(self, label_: str, modifier: int):
        say(guard(rt().battle.roll_d20, self.cid, label_, modifier, self.adv_value()))

    def _damage(self, label_: str, parts, crit: bool):
        say(guard(rt().battle.roll_damage, self.cid, label_, parts, crit))

    def _use(self, e: dict, target: int):
        say(guard(rt().battle.use_action, self.cid, e["name"] or "attack", e["text"], self.adv_value(), target))

    def _hover(self, chip: QWidget, spell: str):
        if not chip.toolTip():
            chip.setToolTip(tr("{0} - click to cast", spell) + "\n\n" + tr(V.spell_tip(spell))[:1500])
        preview_area(spell)

    def _cast(self, spell: str, sp: dict):
        item = _menu_item(self.cid, f"mspell:{spell}")
        if item:
            start_aim(self, self.cid, item, None, self.adv_value())
            preview_area(None)
            return
        ok, choice = spell_choice(self, spell)
        if not ok:
            return
        b = rt().battle
        say(guard(b.monster_cast, self.cid, spell, sp["dc"], sp["attack"], sp["level"], self.adv_value(),
                  b.state().get("target"), choice))
        preview_area(None)


class PlayerCard(CombatCard):
    def __init__(self, c: dict, view: dict, prefs: dict, parent=None):
        super().__init__(c, view, prefs, parent)
        self.character = c.get("character")
        if not self.character:
            return
        self.box.addWidget(self._sheet())        # (the Inspector names the target above the card; the sheet has the roll switch)

    def _sheet(self) -> QWidget:
        try:
            from ..characters.sheet import CharacterSheet
            sheet = CharacterSheet(self.character, compact=True, in_card=True)
        except Exception as e:                       # noqa: BLE001 - the sheet window is another feature; fall back to text
            rt().log(f"[DEBUG] battle card: the character sheet couldn't load ({type(e).__name__}: {e}); showing text")
            from ....rules.sheet import sheet_text
            from ...widgets.text import TextView
            char = guard(rt().characters.get, self.character)
            view = TextView(sheet_text(char) if char else "")
            view.setMinimumHeight(160)
            return view
        sheet.attack_hook = lambda _n, weapon, adv: self._attack(weapon, adv)      # the sheet's buttons act in the battle
        sheet.cast_hook = lambda _n, spell, slot, ritual, adv: self._cast(spell, slot, ritual, adv)
        sheet.hp_hook = lambda _n, kind, amount: guard_ok(getattr(rt().battle, kind), self.cid, amount)
        sheet.spell_hovered.connect(lambda spell: preview_area(spell or None))
        return sheet

    def _attack(self, weapon: str, adv=None) -> bool:
        item = _menu_item(self.cid, f"attack:{weapon}")
        if item and not rt().battle.state().get("target"):
            start_aim(self, self.cid, item, None, adv or self.adv_value())
            return True
        say(guard(rt().battle.pc_attack, self.cid, weapon, adv or self.adv_value(), None))
        return True

    def _cast(self, spell: str, slot, ritual: bool, adv=None) -> bool:
        item = _menu_item(self.cid, f"spell:{spell}") if not ritual else None
        if item:
            start_aim(self, self.cid, item, int(slot) if str(slot or "").isdigit() else item.get("level"), adv or self.adv_value())
            preview_area(None)
            return True
        ok, choice = spell_choice(self, spell, slot)
        if ok:
            say(guard(rt().battle.pc_spell, self.cid, spell, slot, ritual, adv or self.adv_value(), None, choice))
        preview_area(None)
        return True


def _menu_items(cid: int) -> dict:
    """{item id: action bar entry} of a creature, when the battle is running."""
    b = rt().battle
    if b.state().get("status") != "active":
        return {}
    a = guard(b.available_actions, cid) or {}
    return {i["id"]: i for g in (a.get("groups") or []) + (a.get("spells") or []) for i in g["items"]}


def _menu_item(cid: int, item_id: str) -> Optional[dict]:
    """The action bar's entry for an attack or spell (with its aiming spec), when the battle is running."""
    b = rt().battle
    if b.state().get("status") != "active":
        return None
    a = guard(b.available_actions, cid) or {}
    for g in (a.get("groups") or []) + (a.get("spells") or []):
        for i in g["items"]:
            if i["id"] == item_id:
                return i
    return None


def make_card(c: dict, view: dict, prefs: dict, parent=None) -> CombatCard:
    cls: Callable = PlayerCard if c["kind"] == "pc" else MonsterCard
    return cls(c, view, prefs, parent)


def target_text(view: dict) -> Optional[str]:
    """'🎯 Target: Goblin 1 (7/7 HP · AC 15)' as rich text, or None when nobody is targeted."""
    ts = [V.find(view, i) for i in view.get("picked") or []]
    ts = [t for t in ts if t]
    if not ts:
        return None
    names = ", ".join(f"<b>{html.escape(t['name'])}</b>" for t in ts)
    one = ts[0]
    more = f" <span style='color:#8b93a3'>{html.escape(tr('{0}/{1} HP · AC {2}', one['hp'], one['max_hp'], one['ac']))}</span>" if len(ts) == 1 else ""
    return f"<span style='color:#f87171'>🎯 {html.escape(tr('Target:'))}</span> {names}{more}"
