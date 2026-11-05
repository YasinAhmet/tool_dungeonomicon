"""The creature generator and editor: quick generation from a few choices, a full manual editor (every stat, trait and
action), the feature library, the spell picker, a live stat block with the DMG's CR check, and saving into CUSTOMS
or a custom rulebook.

    open_monster_generator(parent)                                  # a new creature
    open_monster_generator(parent, edit_id="Thorn Brute|Custom")    # edit a custom creature (CUSTOMS or a rulebook's)
    open_monster_generator(parent, copy_id="Goblin|MM", on_saved=lambda id, add: ...)

CreatureEditor is the editor itself; the window here and the Creature workshop (workshop.py) both embed it.
"""
import math
from typing import Callable, Dict, List, Optional

from PySide6.QtCore import QEvent, QObject, QSize, Qt, QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (QAbstractSpinBox, QComboBox, QDialog, QFrame, QGridLayout, QLabel, QPlainTextEdit, QToolButton,
                               QVBoxLayout, QWidget)

from ....core import portraits
from ....core.i18n import tr
from ....rules import engine as E
from ....rules import monster_gen as G
from ....services import library
from ....services import monster_workshop as W
from ... import dialogs, notify
from ...errors import guard, user_errors
from ...selection import show_content
from ...theme import COLORS
from ...widgets.common import (Combo, FlipSplitter, FlowLayout, button, check, clear_layout, col, combo, label, line_edit, row,
                               scroll, spin, stretch, title, tool_button)
from ...widgets.text import TextView
from ..battle.common import SIDE
from ..characters.portrait import open_portrait_editor, portrait_pixmap

SECS = [("traits", "Traits"), ("spellcasting", "Spellcasting"), ("actions", "Actions"), ("bonus_actions", "Bonus actions"),
        ("reactions", "Reactions"), ("legendary", "Legendary actions")]
SPEEDS = ("walk", "burrow", "climb", "fly", "swim")


def _polish(w: QWidget, role: str):
    w.setProperty("role", role)
    w.style().polish(w)


def _field(text: str, w):
    return col(label(text, role="dim"), w, spacing=1)


class _WheelGuard(QObject):
    """Number boxes and dropdowns inside the scrolling editor only take the mouse wheel once clicked into;
    otherwise the wheel scrolls the editor."""

    def __init__(self, area):
        super().__init__(area)
        self.area = area

    def eventFilter(self, obj, ev):
        if ev.type() == QEvent.Wheel and not obj.hasFocus():
            bar = self.area.verticalScrollBar()
            bar.setValue(bar.value() - ev.angleDelta().y() // 2)
            return True
        return False


class _GrowingText(QPlainTextEdit):
    """A text box as tall as its text (between `rows` and 12 lines)."""

    def __init__(self, text: str, rows: int = 2):
        super().__init__(text)
        self.rows = rows
        self.setTabChangesFocus(True)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.document().documentLayout().documentSizeChanged.connect(lambda *_: self._fit())
        self._fit()

    def _fit(self):
        n = int(self.document().documentLayout().documentSize().height())
        self.setVerticalScrollBarPolicy(Qt.ScrollBarAsNeeded if n > 12 else Qt.ScrollBarAlwaysOff)
        self.setFixedHeight(self.fontMetrics().lineSpacing() * max(self.rows, min(12, n)) + 14)

    def resizeEvent(self, ev):
        super().resizeEvent(ev)
        self._fit()


class CreatureEditor(QWidget):
    """The whole generator. on_saved(id, add_to_battle) runs after a save; on_close (a window's) adds a Cancel button;
    battle=True adds "Save and add to battle"."""

    def __init__(self, parent=None, on_saved: Optional[Callable[[str, bool], None]] = None,
                 on_close: Optional[Callable[[], None]] = None, battle: bool = False):
        super().__init__(parent)
        self.on_saved, self.on_close = on_saved, on_close
        self.opts = W.options()
        self.spec, self.original, self.book = G.blank_spec("1"), None, None
        self.fold: Dict[str, bool] = {}
        self.last: Optional[dict] = None           # the latest preview (HP, CR check)
        self.dirty = False
        self._rendering = False
        self._hp: Optional[QLabel] = None
        self._timer = QTimer(self, singleShot=True, interval=250)
        self._timer.timeout.connect(self._preview)

        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(6)
        box.addWidget(self._quick_strip())

        self.sections = QVBoxLayout()
        self.sections.setContentsMargins(0, 0, 6, 0)
        self.sections.setSpacing(6)
        host = QWidget()
        host.setLayout(self.sections)
        self.scroller = scroll(host)
        self._wheel = _WheelGuard(self.scroller)

        self.check = label("")
        self.check_detail = label("", role="dim", wrap=True)
        self.set_cr_btn = button("", lambda: self.set_cr(self.last["check"]["suggested"]))
        self.set_cr_btn.hide()
        self.preview = TextView(heading_first_line=True)
        right = QWidget()
        rl = QVBoxLayout(right)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.addWidget(title(tr("Stat block")))
        rl.addLayout(row(self.check, stretch(), self.set_cr_btn))
        rl.addWidget(self.check_detail)
        rl.addWidget(self.preview, 1)
        split = FlipSplitter(Qt.Horizontal)                  # the stat block goes under the form when narrow
        split.addWidget(self.scroller)
        split.addWidget(right)
        split.setStretchFactor(0, 5)
        split.setStretchFactor(1, 4)
        split.setChildrenCollapsible(False)
        split.setSizes([5000, 4000])
        self.scroller.setMinimumWidth(440)
        self.scroller.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        right.setMinimumWidth(300)
        box.addWidget(split, 1)

        self.problem = label("", role="bad", wrap=True)
        self.delete_btn = button(tr("Delete"), self.delete, kind="danger")
        self.save_btn = button("", lambda: self.save(False), kind="primary")
        foot = row(self.problem, stretch(), self.delete_btn,
                   button(tr("Cancel"), on_close) if on_close else None, self.save_btn,
                   button(tr("Save and add to battle"), lambda: self.save(True), kind="primary") if battle else None)
        box.addLayout(foot)
        self._render()

    # ------------------------------------------------------------------ loading
    def load(self, edit_id: Optional[str] = None, copy_id: Optional[str] = None, book: Optional[str] = None) -> bool:
        got = guard(W.start, edit_id, copy_id, book)
        if not got:
            return False
        self.spec, self.original, self.book = got
        self.dirty = False
        self.fold = {}
        self.last = None
        self._render()
        self.dirty = False
        return True

    def heading(self) -> str:
        """The window title for what is being edited."""
        where = tr(W.book_name(self.book)) if self.book else ""
        text = tr("Edit {0}", self.spec["name"]) if self.original else tr("Creature generator")
        return text + (f"  ·  {where}" if where else "")

    # ------------------------------------------------------------------ the quick generator
    def _quick_strip(self) -> QFrame:
        o = self.opts
        roles = o["roles"]
        self.q = {
            "name": line_edit(placeholder=tr("random name"), width=150),
            "cr": combo(o["crs"], "1", width=60),
            "type": combo([(tr("auto"), "auto")] + [(tr(t), t) for t in o["types"]]),
            "role": combo([(tr("auto"), "auto")] + [(tr(v.split(" - ")[0]), k) for k, v in roles.items()],
                          tip=tr("Role") + "\n" + "\n".join(tr(v) for v in roles.values())),
            "size": combo([(tr("auto"), "auto")] + [(tr(s), s) for s in o["sizes"]]),
            "theme": combo([(tr("no element") if t == "none" else tr(t), t) for t in o["themes"]]),
            "mobility": combo([(tr("auto movement") if m == "auto" else tr(m), m) for m in o["mobility"]]),
            "environment": combo([(tr("any place"), "")] + [(tr(e), e) for e in o["environments"]]),
        }
        names = {"name": tr("Name"), "cr": tr("CR"), "type": tr("Type"), "role": tr("Role"), "size": tr("Size"),
                 "theme": tr("Element"), "mobility": tr("Movement"), "environment": tr("Environment")}
        host = QWidget()
        flow = FlowLayout(host, spacing=8)
        head = label("🎲 " + tr("Quick generate") + " ⓘ", tip=tr("Generate fills in everything below from the choices; then change "
                                                              "anything by hand. Every number follows the DMG's monster-by-CR guidelines."))
        f = head.font()
        f.setBold(True)
        head.setFont(f)
        flow.addWidget(head)
        for k, w in self.q.items():
            flow.addWidget(self._wrap(_field(names[k], w)))
        flow.addWidget(self._wrap(col(stretch(), row(button(tr("Generate"), self.generate, kind="primary"),
                                                    button(tr("Blank"), self.blank, tip=tr("Start from an empty stat block"))))))
        card = QFrame()
        card.setObjectName("card")
        cl = QVBoxLayout(card)
        cl.setContentsMargins(8, 6, 8, 6)
        cl.setSpacing(3)
        cl.addWidget(host)                                   # (how it works: on the title's hover)
        return card

    @staticmethod
    def _wrap(layout) -> QWidget:
        w = QWidget()
        w.setLayout(layout)
        return w

    def generate(self):
        choices = {k: (w.text() if k == "name" else w.currentData()) for k, w in self.q.items()}
        spec = guard(G.generate, choices)
        if spec:
            self.spec = spec
            self.last = None
            self._render()
            self.dirty = True
            notify.good(tr("Generated {0}.", spec["name"]))

    def blank(self):
        self.spec = G.blank_spec(self.spec["cr"])
        self._render()
        self.dirty = True

    # ------------------------------------------------------------------ changes
    def changed(self):
        if not self._rendering:
            self.dirty = True
        self._timer.start()

    def _set(self, obj: dict, key: str, value):
        obj[key] = value
        self.changed()

    def set_cr(self, cr: str):
        old = self.spec["cr"]
        if cr == old:
            return
        spec = guard(W.set_cr, self.spec, cr)
        if spec:
            self.spec = spec
            self.dirty = True
            self._render()
            notify.good(tr("Rescaled attacks, DCs and damage from CR {0} to CR {1}.", old, cr))

    def _rename(self, old: str):
        if self._rendering or not old or old == self.spec["name"]:
            return
        spec = guard(W.renamed, self.spec, old)
        if spec:
            self.spec = spec
            self._render()

    def fit_hp(self):
        n = guard(W.fit_hit_dice, self.spec)
        if n:
            self.spec["hit_dice"] = n
            self.dirty = True
            self._render()

    def add_entry(self, key: str, entry: dict, first: bool = False):
        self.spec[key].insert(0 if first else len(self.spec[key]), entry)
        self.fold[key] = False
        self.dirty = True
        self._render()

    def _move(self, key: str, i: int, d: int):
        lst, j = self.spec[key], i + d
        if 0 <= j < len(lst):
            lst[i], lst[j] = lst[j], lst[i]
            self.dirty = True
            self._render()

    def _remove(self, key: str, i: int):
        if 0 <= i < len(self.spec[key]):
            self.spec[key].pop(i)
            self.dirty = True
            self._render()

    # ------------------------------------------------------------------ the preview and the CR check
    def _preview(self):
        try:
            last = library.creature_preview(self.spec)
        except user_errors() as e:                  # a half-typed stat block: say why instead of a toast per key
            self.preview.set_text(tr(str(e)))
            return
        self.last = last
        bar = self.preview.verticalScrollBar()
        pos = bar.value()
        self.preview.set_text(last["text"])
        bar.setValue(pos)
        c, cr = last["check"], self.spec["cr"]
        ok = c["suggested"] == cr
        self.check.setText(("✓ " if ok else "⚠ ") + tr("Plays like CR {0}", c["suggested"]))
        _polish(self.check, "good" if ok else "warn")
        self.check.setToolTip("\n".join([
            tr("CR check (DMG chapter 9)"),
            tr("Defensive CR {0}: effective HP {1}, AC {2}", c["defensive"], c["ehp"], self.spec["ac"]),
            tr("Offensive CR {0}: about {1} damage per round", c["offensive"], c["dpr"]),
            tr("Typical HP at CR {0}: {1}", cr, round(last["target_hp"]))]))
        self.check_detail.setText(tr("defense {0}, offense {1} · {2} dmg/round · {3} XP · proficiency +{4}",
                                     c["defensive"], c["offensive"], c["dpr"], f"{last['xp']:,}", last["prof"]))
        self.set_cr_btn.setText(tr("Set CR to {0}", c["suggested"]))
        self.set_cr_btn.setVisible(not ok)
        if self._hp is not None:
            self._hp.setText(tr("= {0} HP ({1})", last["hp"], last["hp_formula"]))

    # ------------------------------------------------------------------ saving
    def save(self, add: bool = False):
        self.problem.setText("")
        try:
            r = W.save(self.spec, self.original, self.book)
        except user_errors() as e:
            self.problem.setText(tr(str(e)))
            return
        notify.good(tr("{0} saved to {1}.", r["name"], tr(W.book_name(self.book))))
        self.original, self.dirty = r["id"], False
        self._render()
        if self.on_saved:
            self.on_saved(r["id"], add)

    def delete(self):
        if not self.original:
            return
        name = self.spec["name"]
        text = (tr("Delete {0} from {1}?", name, W.book_name(self.book)) if self.book
                else tr("Delete {0} from CUSTOMS? This removes its file.", name))
        if not dialogs.confirm(self, text, tr("Delete creature"), tr("Delete")):
            return
        guard(library.delete_creature, self.original)
        if W.is_custom(self.original):              # still there: the failure was reported
            return
        notify.good(tr("Deleted."))
        self.after_delete()

    def after_delete(self):
        """The workshop starts a new creature; the window closes."""
        if self.on_close:
            self.on_close()
        else:
            self.load(book=self.book)

    # ------------------------------------------------------------------ drawing the editor
    def _render(self):
        bar = self.scroller.verticalScrollBar()
        pos = bar.value()
        self._rendering = True
        try:
            clear_layout(self.sections)
            self._hp = None
            s = self.spec
            self.sections.addWidget(self._section("who", tr("Identity"), self._identity))
            self.sections.addWidget(self._section("def", tr("Armor, hit points & speed"), self._defense))
            self.sections.addWidget(self._section("abil", tr("Ability scores & proficiencies"), self._abilities))
            self.sections.addWidget(self._section("dmg", tr("Damage & condition immunities"), self._damage))
            self.sections.addWidget(self._section("sense", tr("Senses & languages"), self._senses))
            for key, name in SECS:
                self.sections.addWidget(self._section(key, tr("{0} ({1})", tr(name), len(s[key])), lambda k=key: self._entries(k),
                                                      tr("the spell list text") if key == "spellcasting" else ""))
            self.sections.addWidget(self._section("lore", tr("Description & lair"), self._lore))
            self.sections.addStretch(1)
            for kind in (QComboBox, QAbstractSpinBox):
                for w in self.sections.parentWidget().findChildren(kind):
                    w.setFocusPolicy(Qt.StrongFocus)
                    w.installEventFilter(self._wheel)
        finally:
            self._rendering = False
        has = bool(self.original)
        self.delete_btn.setVisible(has)
        self.save_btn.setText(tr("Save to {0}", tr(W.book_name(self.book))))
        QTimer.singleShot(0, bar, lambda: bar.setValue(pos))
        self._timer.start(0)

    def _section(self, key: str, text: str, build: Callable, hint: str = "") -> QFrame:
        shut = self.fold.get(key, False)
        frame = QFrame()
        frame.setObjectName("mgsect")
        frame.setStyleSheet(f"QFrame#mgsect {{ border: 1px solid {COLORS['border']}; border-radius: 5px; }}")
        v = QVBoxLayout(frame)
        v.setContentsMargins(8, 4, 8, 6)
        v.setSpacing(4)
        head = QToolButton()
        head.setText(("▸ " if shut else "▾ ") + text.replace("&", "&&"))
        head.setProperty("kind", "flat")
        head.setStyleSheet(f"color: {COLORS['accent']}; font-weight: 600; text-align: left;")
        head.clicked.connect(lambda *_: (self.fold.__setitem__(key, not shut), self._render()))
        v.addLayout(row(head, label(hint, role="dim") if hint else None, stretch()))
        if not shut:
            content = build()
            (v.addLayout if not isinstance(content, QWidget) else v.addWidget)(content)
        return frame

    # bound inputs
    def _num(self, obj: dict, key: str, low: int = 0, high: int = 999, width: int = 56):
        return spin(int(obj.get(key) or 0), low, high, on_change=lambda v: self._set(obj, key, v), width=width)

    def _txt(self, obj: dict, key: str, placeholder: str = ""):
        e = line_edit(str(obj.get(key) or ""), placeholder)
        e.textEdited.connect(lambda t: self._set(obj, key, t))
        return e

    def _textbox(self, text: str, on_change: Callable[[str], None], placeholder: str = "", rows: int = 2) -> QPlainTextEdit:
        t = _GrowingText(text, rows)
        t.setPlaceholderText(placeholder)
        t.textChanged.connect(lambda: on_change(t.toPlainText()))
        return t

    def _toggles(self, values: List[str], lst: List[str]) -> QWidget:
        host = QWidget()
        flow = FlowLayout(host, spacing=3)
        for v in values:
            b = button(tr(v), checkable=True)
            b.setChecked(v in lst)
            b.setStyleSheet("padding: 1px 7px;")
            b.toggled.connect(lambda on, v=v: self._toggle(lst, v, on))
            flow.addWidget(b)
        return host

    def _toggle(self, lst: List[str], v: str, on: bool):
        if on and v not in lst:
            lst.append(v)
        elif not on and v in lst:
            lst.remove(v)
        self.changed()

    # sections
    def _identity(self):
        s, o = self.spec, self.opts
        name = line_edit(s["name"], tr("Creature name"))
        f = name.font()
        f.setBold(True)
        name.setFont(f)
        old = s["name"]
        name.textEdited.connect(lambda t: self._set(s, "name", t))
        name.editingFinished.connect(lambda: self._rename(old))
        cr = combo(o["crs"], s["cr"], on_change=self.set_cr, width=70)
        size = combo([(tr(z), z) for z in o["sizes"]], s["size"], on_change=lambda v: (self._set(s, "size", v), self._render()))
        kind = Combo()
        kind.setEditable(True)
        kind.addItems(o["types"])
        kind.setCurrentText(s["type"])
        kind.editTextChanged.connect(lambda t: self._set(s, "type", t))
        env = line_edit(", ".join(s["environment"]))
        env.textEdited.connect(lambda t: self._set(s, "environment", [x.strip() for x in t.split(",") if x.strip()]))
        grid = QGridLayout()
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(4)
        grid.addLayout(_field(tr("Name"), name), 0, 0, 1, 2)
        grid.addLayout(_field(tr("Challenge rating"), cr), 0, 2)
        grid.addLayout(_field(tr("Size"), size), 0, 3)
        grid.addLayout(_field(tr("Type"), kind), 1, 0)
        grid.addLayout(_field(tr("Tags"), self._txt(s, "tags", tr("e.g. goblinoid"))), 1, 1)
        grid.addLayout(_field(tr("Alignment"), self._txt(s, "alignment")), 1, 2, 1, 2)
        grid.addLayout(_field(tr("Environments (comma separated)"), env), 2, 0, 1, 4)
        grid.addLayout(col(self._portrait_button(), stretch(), spacing=1), 0, 4, 3, 1)
        grid.setColumnStretch(0, 2)
        grid.setColumnStretch(1, 2)
        return grid

    def _portrait_button(self) -> QToolButton:
        s = self.spec
        path, framed = portraits.of_monster({"name": s["name"], "source": "Custom", "type": s["type"],
                                            "portrait": s.get("portrait")})
        b = tool_button("", self.choose_portrait, tip=tr("Portrait: its token on the battle maps. Choose one from the "
                                                         "library or a picture of your own."))
        b.setIcon(QIcon(portrait_pixmap(path, framed, 72, SIDE["enemy"])))
        b.setIconSize(QSize(72, 72))
        return b

    def choose_portrait(self):
        choice = open_portrait_editor(self, "", "", self.spec.get("portrait"), kind="monsters")
        if choice is None:
            return
        if choice:                                       # kept in data/portraits now; the creature's file on saving
            choice = guard(portraits.save_choice, choice)
            if not choice:
                return
        self.spec["portrait"] = choice
        self.dirty = True
        self._render()

    def _defense(self):
        s = self.spec
        sp = s["speed"]
        self._hp = label(tr("= {0} HP ({1})", self.last["hp"], self.last["hp_formula"]) if self.last else "", role="accent")
        top = row(_field(tr("AC"), self._num(s, "ac", 1, 40)),
                  _field(tr("AC note"), self._txt(s, "ac_note", tr("natural armor"))),
                  _field(tr("Hit dice (d{0})", self.opts["hit_die"][s["size"]]), self._num(s, "hit_dice", 1, 99)),
                  col(stretch(), self._hp),
                  col(stretch(), button(tr("Fit HP to CR"), self.fit_hp,
                                        tip=tr("Hit dice that give the typical HP of this CR (from the printed monsters)"))),
                  spacing=8)
        hover = check(tr("hover"), bool(sp.get("hover")), lambda on: self._set(sp, "hover", on))
        speeds = row(*[_field(tr("{0} ft.", tr(k)), self._num(sp, k, 0, 300, 52)) for k in SPEEDS],
                     col(stretch(), hover), stretch(), spacing=8)
        return col(top, speeds)

    def _abilities(self):
        s = self.spec
        ab = s["abilities"]
        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(2)
        for c, a in enumerate(E.ABILITIES):
            out = label(G.signed(G.mod(ab[a])), role="dim")
            box = spin(ab[a], 1, 30, width=52)
            box.setAlignment(Qt.AlignCenter)
            box.valueChanged.connect(lambda v, a=a, out=out: (out.setText(G.signed(G.mod(v))), self._set(ab, a, v)))
            save = check(tr("save"), a in s["save_profs"], tip=tr("Proficient saving throw"))
            save.toggled.connect(lambda on, a=a: self._set(s, "save_profs", [x for x in E.ABILITIES
                                                                              if (x in s["save_profs"] or x == a) and (on or x != a)]))
            grid.addWidget(label(a.upper(), role="title"), 0, c, Qt.AlignCenter)
            grid.addWidget(box, 1, c, Qt.AlignCenter)
            grid.addWidget(out, 2, c, Qt.AlignCenter)
            grid.addWidget(save, 3, c, Qt.AlignCenter)
        grid.setColumnStretch(len(E.ABILITIES), 1)
        skills = QGridLayout()
        skills.setHorizontalSpacing(14)
        skills.setVerticalSpacing(2)
        per = math.ceil(len(self.opts["skills"]) / 3)
        for i, sk in enumerate(self.opts["skills"]):
            state = "expert" if sk in s["skill_expert"] else "prof" if sk in s["skill_profs"] else ""
            pick = combo([("—", ""), ("✓", "prof"), ("★", "expert")], state, width=50,
                         on_change=lambda v, sk=sk: self._skill(sk, v))
            skills.addLayout(row(label(tr(sk)), stretch(), pick), i % per, i // per)
        return col(grid, label(tr("Skills: ✓ proficient, ★ expertise (double proficiency)"), role="dim"), skills)

    def _skill(self, sk: str, state: str):
        s = self.spec
        s["skill_profs"] = [x for x in s["skill_profs"] if x != sk] + ([sk] if state else [])
        s["skill_expert"] = [x for x in s["skill_expert"] if x != sk] + ([sk] if state == "expert" else [])
        self.changed()

    def _damage(self):
        s, o = self.spec, self.opts
        nonmagical = check(tr("bludgeoning / piercing / slashing only from nonmagical attacks"), s["nonmagical"],
                           lambda on: self._set(s, "nonmagical", on))
        return col(label(tr("Resistances"), role="dim"), self._toggles(o["damage"], s["resist"]),
                   label(tr("Immunities"), role="dim"), self._toggles(o["damage"], s["immune"]),
                   label(tr("Vulnerabilities"), role="dim"), self._toggles(o["damage"], s["vulnerable"]),
                   nonmagical,
                   label(tr("Condition immunities"), role="dim"), self._toggles(o["conditions"], s["condition_immune"]))

    def _senses(self):
        s = self.spec
        se = s["senses"]
        return col(row(*[_field(tr("{0} ft.", tr(k)), self._num(se, k, 0, 1000, 60)) for k in se], stretch(), spacing=8),
                   _field(tr("Languages"), self._txt(s, "languages")))

    def _lore(self):
        s = self.spec
        return col(_field(tr("Description (shown under the stat block)"),
                          self._textbox(s["description"], lambda t: self._set(s, "description", t), rows=3)),
                   _field(tr("Lair actions"), self._textbox(s["lair"], lambda t: self._set(s, "lair", t), rows=2)))

    # ------------------------------------------------------------------ traits, actions, spellcasting
    def _entries(self, key: str):
        box = col(spacing=5)
        for i, e in enumerate(self.spec[key]):
            box.addWidget(self._spell_row(i, e) if key == "spellcasting" else self._entry_row(key, i, e))
        host = QWidget()
        flow = FlowLayout(host, spacing=4)
        if key == "spellcasting":
            adders = [button(tr("+ Spellcasting (slots)…"), lambda: self.choose_spells(None, "slots"), kind="primary",
                             tip=tr("Pick any spells from the spell library; the slots, save DC and attack bonus are worked out")),
                      button(tr("+ Innate spellcasting…"), lambda: self.choose_spells(None, "innate"), kind="primary",
                             tip=tr("Spells cast at will or a few times a day, no slots")),
                      button(tr("+ Blank"), lambda: self.add_entry(key, {"name": "Spellcasting", "text": ""}),
                             tip=tr("Write the spellcasting text by hand"))]
        else:
            adders = [button(tr("+ Blank"), lambda: self.add_entry(key, {"name": "", "text": ""})),
                      button(tr("+ From library…"), lambda: self.feature_library(key), kind="primary",
                             tip=tr("Borrow a trait or action from any creature, by CR and creature family. Its bonuses, "
                                    "DCs, damage and name are adapted to this one."))]
        if key in ("actions", "bonus_actions", "reactions", "legendary"):
            adders.append(button(tr("+ Attack…"), lambda: self.attack_builder(key)))
        if key == "actions":
            adders.append(button(tr("+ Multiattack"), lambda: self.add_entry(key, W.multiattack(self.spec), first=True)))
        for b in adders:
            flow.addWidget(b)
        if key == "legendary":
            flow.addWidget(self._wrap(row(label(tr("Legendary actions per round")),
                                          self._num(self.spec, "legendary_count", 1, 5, 40))))
        box.addWidget(host)
        return box

    def _tools(self, key: str, i: int) -> list:
        return [tool_button("↑", lambda: self._move(key, i, -1), tip=tr("Move up")),
                tool_button("↓", lambda: self._move(key, i, 1), tip=tr("Move down")),
                tool_button("✕", lambda: self._remove(key, i), tip=tr("Remove"))]

    def _name_edit(self, e: dict) -> QWidget:
        name = line_edit(e["name"], tr("Name"))
        f = name.font()
        f.setBold(True)
        name.setFont(f)
        name.textEdited.connect(lambda t: self._set(e, "name", t))
        return name

    def _entry_row(self, key: str, i: int, e: dict) -> QFrame:
        card = QFrame()
        card.setObjectName("card")
        v = QVBoxLayout(card)
        v.setContentsMargins(5, 5, 5, 5)
        v.setSpacing(3)
        v.addLayout(row(self._name_edit(e), *self._tools(key, i)))
        v.addWidget(self._textbox(e["text"], lambda t: self._set(e, "text", t)))
        return card

    def _spell_row(self, i: int, e: dict) -> QFrame:
        card = QFrame()
        card.setObjectName("card")
        v = QVBoxLayout(card)
        v.setContentsMargins(5, 5, 5, 5)
        v.setSpacing(3)
        choose = button(tr("Choose spells…"), lambda: self.choose_spells(i), kind="primary")
        st = e.get("setup")
        if not st:
            v.addLayout(row(self._name_edit(e), choose, *self._tools("spellcasting", i)))
            v.addWidget(self._textbox(e["text"], lambda t: self._set(e, "text", t), tr('Spellcasting text, or press "Choose spells…"')))
            return card
        innate = st.get("mode") == "innate"
        n = len(st.get("spells") or [])
        head = label(tr("Innate Spellcasting") if innate else tr("Spellcasting"))
        f = head.font()
        f.setBold(True)
        head.setFont(f)
        detail = tr("{0} · {1} spells", tr(G.ABILITY_NAMES.get(st.get("ability"), "Intelligence")), n)
        if not innate:
            detail += " · " + tr("caster level {0}", st.get("level") or tr("auto"))
        by_hand = button(tr("Edit text by hand"), lambda: self._by_hand(i),
                         tip=tr("Turn this into plain text (the spell list stops following the stats)"))
        v.addLayout(row(head, label(detail, role="dim"), stretch(), by_hand, choose, *self._tools("spellcasting", i)))
        for group, names in W.spellcasting_groups(st):
            host = QWidget()
            host.setObjectName("chips")
            host.setStyleSheet("QWidget#chips { background: transparent; }")
            flow = FlowLayout(host, spacing=3)
            for nm in names:
                b = tool_button(nm, lambda nm=nm: show_content("spells", nm), tip=tr("Show {0} in the Inspector", nm), kind="")
                flow.addWidget(b)
            lab = label(tr(group), role="dim")
            lab.setFixedWidth(70)
            v.addLayout(row(col(lab, stretch()), host))
        v.addWidget(label(tr("Save DC and attack bonus follow the ability scores and CR - see the stat block."), role="dim"))
        return card

    def _by_hand(self, i: int):
        self.spec["spellcasting"][i].pop("setup", None)
        self.dirty = True
        self._render()

    def choose_spells(self, i: Optional[int] = None, mode: str = "slots"):
        from .spellpicker import SpellPicker
        entry = None if i is None else self.spec["spellcasting"][i]
        setup = guard(W.spell_setup, self.spec, entry, mode)
        if setup is None:
            return
        picker = SpellPicker(self, setup, self.spec)
        if picker.exec() == QDialog.Accepted and picker.entry:
            self.apply_spells(i, picker.entry)

    def apply_spells(self, i: Optional[int], entry: dict):
        if i is None:
            self.spec["spellcasting"].append(entry)
        else:
            self.spec["spellcasting"][i] = entry
        self.fold["spellcasting"] = False
        self.dirty = True
        self._render()

    def attack_builder(self, key: str):
        a = W.attack_defaults(self.spec)
        o = self.opts
        fields = [
            {"key": "name", "label": tr("Name"), "value": a["name"], "required": True},
            {"key": "kind", "label": tr("Kind"), "kind": "select", "options": [(tr(k), k) for k in W.ATTACK_KINDS], "value": a["kind"]},
            {"key": "ability", "label": tr("Ability"), "kind": "select",
             "options": [(tr(G.ABILITY_NAMES[x]), x) for x in E.ABILITIES], "value": a["ability"]},
            {"key": "dice", "label": tr("Damage dice (how many)"), "kind": "int", "value": a["dice"], "min": 1, "max": 40},
            {"key": "die", "label": tr("Die"), "kind": "select", "options": [("d" + d, d) for d in W.DICE], "value": a["die"]},
            {"key": "dtype", "label": tr("Damage type"), "kind": "select", "options": [(tr(d), d) for d in o["damage"]], "value": a["dtype"]},
            {"key": "reach", "label": tr("Reach (ft.)"), "kind": "int", "value": a["reach"], "min": 5, "max": 60},
            {"key": "range", "label": tr("Range (ft.)"), "value": a["range"]},
            {"key": "extra_n", "label": tr("Extra damage dice (0 = none)"), "kind": "int", "value": a["extra_n"], "min": 0, "max": 40},
            {"key": "extra_die", "label": tr("Extra die"), "kind": "select", "options": [("d" + d, d) for d in W.DICE], "value": a["extra_die"]},
            {"key": "extra_type", "label": tr("Extra damage type"), "kind": "select", "options": [(tr(d), d) for d in o["damage"]],
             "value": a["extra_type"]},
            {"key": "text", "label": tr("Rider (e.g. \"the target is grappled (escape DC 13).\")"), "value": a["text"]}]
        values = dialogs.form(self, tr("New attack"), fields, tr("Add attack"))
        if values:
            self.add_attack(key, values)

    def add_attack(self, key: str, values: dict):
        entry = guard(G.attack_entry, self.spec, values)
        if entry:
            self.add_entry(key, entry)

    def feature_library(self, want: str = ""):
        from .features import FeatureLibrary
        FeatureLibrary(self, want).exec()


# ====================================================================== the window
_windows: set = set()


class GeneratorWindow(QDialog):
    def __init__(self, parent, on_saved: Optional[Callable[[str, bool], None]] = None):
        super().__init__(parent)
        self.setAttribute(Qt.WA_DeleteOnClose)
        self.setWindowFlag(Qt.WindowContextHelpButtonHint, False)
        self.setWindowFlag(Qt.WindowMaximizeButtonHint, True)
        self.user_saved = on_saved
        self.editor = CreatureEditor(self, on_saved=self._saved, on_close=self.close, battle=bool(on_saved))
        box = QVBoxLayout(self)
        box.setContentsMargins(10, 10, 10, 8)
        box.addWidget(self.editor)
        self.resize(1320, 860)

    def _saved(self, ident: str, add: bool):
        self.close()
        if self.user_saved:
            self.user_saved(ident, add)


def open_monster_generator(parent, edit_id: Optional[str] = None, copy_id: Optional[str] = None,
                           book: Optional[str] = None, on_saved: Optional[Callable[[str, bool], None]] = None) -> None:
    """Open the generator window (non-modal). on_saved(id, add_to_battle) runs after a save; with on_saved the
    window also offers "Save and add to battle"."""
    win = GeneratorWindow(parent, on_saved)
    if not win.editor.load(edit_id, copy_id, book):
        win.deleteLater()
        return None
    win.setWindowTitle(win.editor.heading())
    _windows.add(win)
    win.destroyed.connect(lambda *_: _windows.discard(win))
    win.show()
    win.raise_()
    return None
