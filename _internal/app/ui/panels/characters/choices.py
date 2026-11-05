"""The choices a level asks for (a level-up, or the first level of a new character), shared by the creation wizard,
the level-up window and RESET ALL. Mirrors the rules engine's plan_level_up() output (plus levelup_flow.plan_extras).

    panel = ChoicesPanel(plan, name="Ilya", subclass="", prev={...}, on_change=..., on_subclass=lambda s: ...)
    panel.collect()      # the choices dict apply_level_up expects
    panel.pending()      # titles of what is still to choose
"""
from typing import Callable, Dict, List, Optional, Sequence

from PySide6.QtCore import Signal
from PySide6.QtWidgets import QComboBox, QRadioButton, QSizePolicy, QVBoxLayout, QWidget

from ....core.i18n import tr
from ....rules import engine as E
from ....rules.describe import UnknownContent, describe
from ....services.battle.icons import for_spell
from ....services.characters import creation_flow as CF, levelup_flow as LF
from ... import errors
from ...widgets.common import button, clear_layout, col, combo, label, row, set_items, spin, stretch, title, widget
from ...widgets.pickers import FoldSelect, PickList, norm

ABILITIES = [(E.ABILITY_NAMES[a], a) for a in E.ABILITIES]


# ---------------------------------------------------------------------- small shared helpers
def detail_of(kind: str) -> Callable[[str], str]:
    """Hover text for a FoldSelect of races, classes, backgrounds, feats..."""
    return lambda ident: describe(kind, ident)["text"]


def describe_text(kind: str, ident: str, limit: int = 1500) -> str:
    """An entry's text, translated, for a tooltip ('' when it isn't in the rules)."""
    try:
        return tr(describe(kind, ident)["text"])[:limit]
    except UnknownContent:
        return ""


def section(heading: str, hint: str = "", *kids) -> QWidget:
    """A titled block: a small heading, an optional hint line, then the widgets."""
    w = widget(col(title(heading), label(hint, role="dim", wrap=True) if hint else None, *kids, spacing=3))
    return w


class SpellPicks(PickList):
    """A PickList of spells folded by spell level, then school (or school, then level; the last choice is kept for
    the next list). A list of one spell level is folded by school only. Option groups (Magical Secrets...) stay the
    outer folders."""
    last_order = "level"

    def __init__(self, options: Sequence = (), count: int = 1, selected: Sequence = ()):
        self._raw: List[dict] = []
        self._order = SpellPicks.last_order
        super().__init__(options, count=count, selected=selected, sort_groups=False)
        self.fold_by = combo([(tr("Level › school"), "level"), (tr("School › level"), "school")], current=self._order,
                             on_change=self._regroup, tip=tr("How the spells are folded"))
        self.top.insertWidget(1, self.fold_by)
        for i, (glyph, text, on) in enumerate((("⊞", tr("Unfold all"), True), ("⊟", tr("Fold all"), False))):
            b = button(glyph, lambda _c=False, on=on: self.expand_all(on), kind="flat", width=24, tip=text)
            b.setSizePolicy(QSizePolicy.Maximum, QSizePolicy.Fixed)
            self.top.insertWidget(2 + i, b)
        self.fold_by.setVisible(self._levels > 1)

    def set_options(self, options: Sequence, selected: Optional[Sequence] = None):
        self._raw = [norm(o) for o in options]
        facts = LF.spell_facts([o["value"] for o in self._raw])
        self._levels = len({f["level"] for f in facts.values()})
        outer = list(dict.fromkeys(o.get("group") or "" for o in self._raw))
        rows = []
        for o in self._raw:
            f = facts.get(o["value"])
            lvl = (tr("Cantrips") if f["level"] == 0 else tr("Level {0}", f["level"])) if f else tr("Other")
            school, n = (f["school"], f["level"]) if f else ("Other", 99)
            by_level = self._order == "level"
            path = (school,) if self._levels <= 1 else (lvl, school) if by_level else (school, lvl)
            sort = (n, school) if by_level else (school, n)
            rows.append(((outer.index(o.get("group") or ""),) + sort + (o["label"],),
                         {**o, "group": ((o["group"],) if o.get("group") else ()) + path, "icon": for_spell(o["value"])}))
        super().set_options([o for _k, o in sorted(rows, key=lambda r: r[0])], selected)

    def _regroup(self, order: str):
        self._order = SpellPicks.last_order = order
        self._open, self._closed = set(), set()
        self.set_options(self._raw)


def picks(options: Sequence, count: int, selected: Optional[Sequence] = None, on_change: Optional[Callable] = None,
          rows: int = 9, spells: bool = False) -> PickList:
    """A PickList sized to its content (a short list doesn't leave a tall empty box). spells=True folds the list by
    spell level and school (SpellPicks)."""
    pl = (SpellPicks if spells else PickList)(options, count=count, selected=list(selected or []))
    if on_change:
        pl.changed.connect(lambda _v: on_change())
    n = len(options)
    line = pl.tree.sizeHintForRow(0) if pl.tree.topLevelItemCount() else 0
    pl.tree.setFixedHeight(min(max(n, 1), rows) * max(line, pl.tree.fontMetrics().height() + 2) + 6)
    return pl


def sync_taken(*groups: Sequence[Optional[PickList]]):
    """Pick lists of one kind (skills, tools, spells...) may not share a pick: what one list of a group holds is
    greyed out in the others. A list may sit in several groups (Skilled picks skills and tools)."""
    taken: Dict[PickList, set] = {}
    for lists in groups:
        lists = [p for p in lists if p is not None]
        for p in lists:
            taken.setdefault(p, set()).update(v for o in lists if o is not p for v in o.chosen())
    for p, values in taken.items():
        p.set_taken(values)


def attempt(dialog, fn, *args, **kwargs):
    """Call a service; a rules/service problem is shown in the dialog's problem line (translated) instead of a toast.
    Returns (True, result) or (False, None)."""
    try:
        result = fn(*args, **kwargs)
    except errors.user_errors() as e:
        text = e.args[0] if isinstance(e, KeyError) and e.args else str(e)
        dialog.show_problem(tr(str(text)))
        return False, None
    except Exception as e:                       # noqa: BLE001 - a bug: logged and reported like everywhere else
        errors.report(e)
        return False, None
    dialog.show_problem("")
    return True, result


def radios(options: Sequence, current, on_change: Callable[[object], None]) -> tuple:
    """Radio buttons for (label, value) pairs in a row of their own (so they exclude each other).
    Returns (widget, {value: button}); more widgets can go in widget.layout()."""
    box = widget(row())
    buttons = {}
    for lab, val in options:
        b = QRadioButton(lab)
        b.setChecked(val == current)
        b.toggled.connect(lambda on, v=val: on and on_change(v))
        buttons[val] = b
        box.layout().addWidget(b)
    box.layout().addStretch(1)
    return box, buttons


# ---------------------------------------------------------------------- feats
class FeatForm(QWidget):
    """The extra decisions a feat needs (creation_flow.feat_form): ability, spell list, spells, weapons..."""
    changed = Signal()

    def __init__(self, char_name: Optional[str] = None, parent=None):
        super().__init__(parent)
        self.char_name = char_name
        self.feat = ""
        self.fields: Dict[str, tuple] = {}
        self.box = QVBoxLayout(self)
        self.box.setContentsMargins(0, 0, 0, 0)
        self.box.setSpacing(3)

    def set_feat(self, feat: str, values: Optional[dict] = None, mi_class: Optional[str] = None):
        values = dict(values or {})
        if mi_class is None and values.get("class"):
            mi_class = values["class"]
        self.feat = feat or ""
        self.fields = {}
        clear_layout(self.box)
        if not self.feat:
            return
        d = errors.guard(CF.feat_form, self.feat, self.char_name, mi_class)
        if not d:
            return
        self.box.addWidget(label(tr(d["text"])[:900], role="dim", wrap=True))
        if d.get("warning"):
            self.box.addWidget(label("⚠ " + tr(d["warning"]), role="warn", wrap=True))
        for f in d["fields"]:
            if f["kind"] == "select":
                opts = [(tr(o["label"]), o["value"]) for o in f["options"]]
                cur = values.get(f["key"]) or (mi_class if f.get("reload") else None)
                c = combo(opts, current=cur)
                c.currentIndexChanged.connect(lambda _i, f=f, c=c: self._select(f, c))
                self.fields[f["key"]] = ("select", c, f)
                self.box.addLayout(row(label(tr(f["label"])), c, stretch()))
            else:
                sel = values.get(f["key"])
                sel = [sel] if isinstance(sel, str) else (sel or [])
                opts = list(f["options"]) + [v for v in sel if v not in f["options"]]     # an earlier pick stays visible
                p = picks(opts, f["count"], sel, self.changed.emit, rows=7, spells=f["key"] in ("cantrips", "spell"))
                self.fields[f["key"]] = ("pick", p, f)
                self.box.addWidget(section(tr(f["label"]), "", p))
        self.changed.emit()

    def _select(self, f: dict, c: QComboBox):
        if f.get("reload"):
            keep = {k: (w.currentData() if kind == "select" else None) for k, (kind, w, _f) in self.fields.items()}
            keep = {k: v for k, v in keep.items() if v is not None}
            self.set_feat(self.feat, keep, c.currentData())
        else:
            self.changed.emit()

    def get(self) -> dict:
        out = {}
        for k, (kind, w, f) in self.fields.items():
            if kind == "select":
                out[k] = w.currentData()
            else:
                out[k] = (w.chosen()[0] if w.chosen() else "") if f.get("single") else w.chosen()
        return out

    def done(self) -> bool:
        return all(w.done() for kind, w, _f in self.fields.values() if kind == "pick")

    def pick(self, key: str) -> Optional[PickList]:
        """The pick list of a field ('cantrips', 'proficiencies'...), if this feat has one."""
        kind, w, _f = self.fields.get(key) or (None, None, None)
        return w if kind == "pick" else None


class FeatPicker(QWidget):
    """Choose a feat (searchable, with its text on hover) and make its extra decisions."""
    changed = Signal()

    def __init__(self, feats: Sequence[str], char_name: Optional[str] = None, value: str = "",
                 values: Optional[dict] = None, parent=None):
        super().__init__(parent)
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(3)
        self.select = FoldSelect([{"title": "", "items": list(feats)}], value or None, detail=detail_of("feats"))
        self.select.setText(self.select.text() if value else tr("— choose a feat —") + "  ▾")
        self.form = FeatForm(char_name)
        self.form.changed.connect(self.changed.emit)
        self.select.changed.connect(lambda v: (self.form.set_feat(v), self.changed.emit()))
        box.addWidget(self.select)
        box.addWidget(self.form)
        if value:
            self.form.set_feat(value, values)

    def value(self) -> str:
        return self.select.value() or ""

    def set_value(self, feat: str, values: Optional[dict] = None):
        self.select.set_value(feat)
        self.form.set_feat(feat, values)
        self.changed.emit()

    def choices(self) -> dict:
        return self.form.get()

    def done(self) -> bool:
        return bool(self.value()) and self.form.done()

    def pick(self, key: str) -> Optional[PickList]:
        return self.form.pick(key)


# ---------------------------------------------------------------------- the plan
def grant_title(key: str) -> str:
    return {"skills": tr("Bonus skill proficiencies"), "expertise_skills": tr("Skills with double proficiency"),
            "languages": tr("Bonus languages"), "cantrip": tr("Bonus cantrip"), "tools": tr("Bonus tool proficiency"),
            "kensei_melee": tr("Kensei melee weapon"), "kensei_ranged": tr("Kensei ranged weapon"),
            "bladesinging_weapon": tr("One-handed melee weapon proficiency")}.get(key, key)


class ChoicesPanel(QWidget):
    """Every decision of one level, from a plan. on_change() fires on any change; on_subclass(name) when the
    subclass changes (the caller asks for a new plan with it)."""

    def __init__(self, plan: dict, name: Optional[str] = None, subclass: str = "", prev: Optional[dict] = None,
                 on_change: Optional[Callable] = None, on_subclass: Optional[Callable[[str], None]] = None,
                 heading: bool = True, rows: int = 9, parent=None):
        super().__init__(parent)
        self.plan, self.name, self.rows = plan, name, rows
        self._on_change, self._on_subclass = on_change, on_subclass
        self.w: Dict[str, object] = {}
        self._pending: List[tuple] = []
        self._subclass = subclass or ""
        P = prev or {}
        box = QVBoxLayout(self)
        box.setContentsMargins(0, 0, 0, 0)
        box.setSpacing(8)
        self.box = box
        if heading:
            head = label(tr("{0} level {1} · d{2} hit die", tr(plan["class"]), plan["level"], plan["hit_die"]), role="accent")
            f = head.font()
            f.setBold(True)
            f.setPointSize(f.pointSize() + 1)
            head.setFont(f)
            box.addWidget(head)
        self._hit_points(P)
        self._subclass_choice()
        self._grants(P)
        self._skills_tools(P)
        self._asi(P)
        self._expertise(P)
        self._options(P)
        self._spells(P)
        if plan.get("features"):
            names = ", ".join(tr(f["name"]) for f in plan["features"])
            box.addWidget(label(tr("Features at this level: {0}", names), role="dim", wrap=True))
        box.addStretch(1)
        self._sync()

    def changed(self):
        self._sync()
        if self._on_change:
            self._on_change()

    def _sync(self):
        """The same skill, tool or spell can't be picked in two lists of this level (class and subclass, a feat...)."""
        g = self.w.get("grants") or {}
        feat = self.feat if self.plan.get("asi") and self.asi_mode == "feat" else None
        fp = lambda k: feat.pick(k) if feat else None
        sync_taken([self.w.get("skills"), g.get("skills"), g.get("expertise_skills"), fp("proficiencies")],
                   [self.w.get("tools"), g.get("tools"), fp("proficiencies")],
                   [self.w.get("cantrips"), g.get("cantrip"), fp("cantrips"), self.w.get("spells"), self.w.get("spellbook"),
                    fp("spell")])
        if hasattr(self, "asi_b"):                       # the second +1 can't go to the first ability
            a = self.asi_a.currentData()
            set_items(self.asi_b, [(tr("(+2 to the first)"), "")] + [(tr(n), k) for n, k in ABILITIES if k != a],
                      self.asi_b.currentData() if self.asi_b.currentData() != a else "")

    # ------------------------------------------------------------------ parts
    def _hit_points(self, P: dict):
        plan = self.plan
        hd = plan["hit_die"]
        if plan["first_ever"]:
            self.box.addWidget(section(tr("Hit points"), tr("At 1st level you get the maximum of your hit die: {0} + Constitution modifier.", hd)))
            return
        mode = P.get("hp", "average")
        rolled = P.get("hp_roll") or 0
        if isinstance(mode, int):
            mode, rolled = "roll", mode
        if mode == "roll" and rolled == hd:
            mode = "max"
        self.hp_mode = mode if mode in ("average", "roll", "max") else "average"
        self.hp_roll = spin(rolled if 1 <= int(rolled or 0) <= hd else 0, 0, hd, on_change=lambda _v: self._hp("roll"), width=44,
                            tip=tr("The hit die you rolled"))
        lay, self.hp_buttons = radios([(tr("Average ({0})", plan["hp"]["average"]), "average"), (tr("Roll d{0}", hd), "roll"),
                                       (tr("Take max ({0})", hd), "max")], self.hp_mode, self._hp)
        lay.layout().insertWidget(2, self.hp_roll)
        lay.layout().insertWidget(3, button("🎲", self._roll_hp, kind="flat", tip=tr("Roll the hit die"), width=28))
        self.box.addWidget(section(tr("Hit points"), tr("Take the fixed average or roll your hit die."), lay))
        self._pending.append((tr("Hit points"), lambda: self.hp_mode in ("average", "max") or self.hp_roll.value() >= 1))

    def _hp(self, mode: str):
        self.hp_mode = mode
        if mode == "roll" and not self.hp_buttons["roll"].isChecked():
            self.hp_buttons["roll"].setChecked(True)
        self.changed()

    def _roll_hp(self):
        self.hp_roll.blockSignals(True)
        self.hp_roll.setValue(E.roll_hit_die(self.plan["hit_die"]))
        self.hp_roll.blockSignals(False)
        self._hp("roll")

    def _subclass_choice(self):
        sc = self.plan.get("subclass")
        if not sc:
            return
        blurbs = sc.get("blurbs") or {}

        def blurb(o: str) -> str:
            return "\n\n".join(tr("{0} (level {1}): {2}…", tr(f["name"]), f["level"], tr(f["text"])) for f in blurbs.get(o, []))
        sel = FoldSelect([{"title": "", "items": list(sc["options"])}], self._subclass or None, detail=blurb)
        if not self._subclass:
            sel.setText(tr("— choose —") + "  ▾")
        sel.changed.connect(self._pick_subclass)
        self.w["subclass"] = sel
        self.box.addWidget(section(tr(sc["title"]), tr("Your choice grants features now and at higher levels. Hover an entry to read what it gives."), sel))
        self._pending.append((tr(sc["title"]), lambda: bool(self._subclass)))

    def _pick_subclass(self, value):
        self._subclass = value or ""
        if self._on_subclass:
            self._on_subclass(self._subclass)
        else:
            self.changed()

    def _grants(self, P: dict):
        grants = self.plan.get("subclass_grants")
        if not grants:
            return
        self.w["grants"] = {}
        prev = P.get("subclass_choices") or {}
        for key, spec in grants.items():
            if not isinstance(spec, dict):
                continue
            opts = CF.language_options(spec["from"]) if key == "languages" else spec["from"]
            p = picks(opts, spec["count"], prev.get(key), self.changed, self.rows, spells=key == "cantrip")
            self.w["grants"][key] = p
            t = grant_title(key)
            self.box.addWidget(section(t, tr("Choose {0}.", spec["count"]), p))
            self._pending.append((t, p.done))

    def _skills_tools(self, P: dict):
        plan = self.plan
        if plan.get("skills"):
            p = picks(plan["skills"]["from"], plan["skills"]["count"], P.get("skills"), self._skills_changed, self.rows)
            self.w["skills"] = p
            self.box.addWidget(section(tr("Skill proficiencies"), tr("Choose {0}.", plan["skills"]["count"]), p))
            self._pending.append((tr("Skills"), p.done))
        tools = plan.get("tools")
        if tools and tools.get("count"):
            p = picks(tools["from"], tools["count"], P.get("tools"), self.changed, self.rows)
            self.w["tools"] = p
            self.box.addWidget(section(tr("Tool proficiencies"), tr("Choose {0}.", tools["count"]), p))
            self._pending.append((tr("Tools"), p.done))

    def _skills_changed(self):
        if "expertise" in self.w:
            self.w["expertise"].set_options(LF.expertise_pool(self.plan, self.w["skills"].chosen()))
        self.changed()

    def _asi(self, P: dict):
        if not self.plan.get("asi"):
            return
        prev = P.get("asi") or {}
        self.asi_mode = "feat" if prev.get("feat") else "asi"
        ab = prev.get("abilities") or {}
        first = next((a for a, n in ab.items() if n), E.ABILITIES[0])
        second = next((a for a, n in ab.items() if n == 1 and a != first), "")
        self.asi_a = combo([(tr(n), k) for n, k in ABILITIES], current=first, on_change=lambda _v: self.changed())
        self.asi_b = combo([(tr("(+2 to the first)"), "")] + [(tr(n), k) for n, k in ABILITIES], current=second,
                           on_change=lambda _v: self.changed())
        self.asi_row = widget(row(label(tr("+1 to")), self.asi_a, label(tr("and +1 to")), self.asi_b, stretch()))
        self.feat = FeatPicker(self.plan.get("feat_pool") or [], self.name, prev.get("feat") or "", prev.get("feat_choices"))
        self.feat.changed.connect(self.changed)
        lay, self.asi_buttons = radios([(tr("Increase ability scores"), "asi"), (tr("Take a feat"), "feat")], self.asi_mode, self._asi_mode)
        self.box.addWidget(section(tr("Ability Score Improvement"),
                                   tr("Increase one ability by 2, or two abilities by 1 (max 20) — or take a feat instead."),
                                   lay, self.asi_row, self.feat))
        self._show_asi()
        self._pending.append((tr("Ability Score Improvement"), lambda: self.asi_mode == "asi" or self.feat.done()))

    def _asi_mode(self, mode: str):
        self.asi_mode = mode
        self._show_asi()
        self.changed()

    def _show_asi(self):
        self.asi_row.setVisible(self.asi_mode == "asi")
        self.feat.setVisible(self.asi_mode == "feat")

    def _expertise(self, P: dict):
        ex = self.plan.get("expertise")
        if not ex:
            return
        pool = LF.expertise_pool(self.plan, self.w["skills"].chosen() if "skills" in self.w else [])
        p = picks(pool, ex["count"], P.get("expertise"), self.changed, self.rows)
        self.w["expertise"] = p
        self.box.addWidget(section(tr("Expertise"), tr("Your proficiency bonus is doubled for the choices."), p))
        self._pending.append((tr("Expertise"), p.done))

    def _options(self, P: dict):
        self.w["options"] = {}
        prev = P.get("options") or {}
        for o in self.plan.get("options") or []:
            p = picks(o["pool"], o["count"], prev.get(o["key"]), self.changed, self.rows)
            self.w["options"][o["key"]] = p
            self.box.addWidget(section(tr(o["name"]), tr("Choose {0}.", o["count"]), p))
            self._pending.append((tr(o["name"]), p.done))

    def _spells(self, P: dict):
        sp = self.plan.get("spells")
        if not sp:
            return
        state = self.plan.get("spell_state") or {}
        info = tr("Spellcasting ability: {0}. Highest spell level: {1}.", tr(E.ABILITY_NAMES.get(sp["ability"], sp["ability"])), sp["max_spell_level"])
        if sp.get("restricted_schools"):
            info += " " + tr("Most spells must be {0}.", tr(" or ").join(tr(s) for s in sp["restricted_schools"]))
        always = sp.get("always_prepared") or []
        self.box.addWidget(section(tr("Spells"), info, label(tr("Always prepared: {0}", ", ".join(always)), role="dim", wrap=True) if always else None))
        if sp.get("cantrips"):
            p = picks(sp["cantrip_pool"], sp["cantrips"], P.get("cantrips"), self.changed, self.rows + 4, spells=True)
            self.w["cantrips"] = p
            self.box.addWidget(section(tr("Cantrips (choose {0})", sp["cantrips"]), "", p))
            self._pending.append((tr("Cantrips"), p.done))
        if sp.get("spellbook"):
            p = picks(sp["spell_pool"], sp["spellbook"], P.get("spellbook"), self._spellbook_changed, self.rows + 4, spells=True)
            self.w["spellbook"] = p
            self.box.addWidget(section(tr("Spellbook (choose {0})", sp["spellbook"]), tr("Your spellbook holds the spells you can prepare."), p))
            self._pending.append((tr("Spellbook"), p.done))
        if sp.get("known"):
            pool: List = list(sp["spell_pool"])
            extra = [n for n in sp.get("any_class_pool") or [] if n not in pool] if sp.get("magic_secrets") else []
            hint = ""
            if extra:
                pool = [{"value": n, "label": n, "group": tr("Class spells")} for n in pool] + \
                       [{"value": n, "label": n, "group": tr("Magical Secrets")} for n in extra]
                hint = tr("Up to {0} may come from any class (Magical Secrets).", sp["magic_secrets"])
            p = picks(pool, sp["known"], P.get("spells"), self.changed, self.rows + 4, spells=True)
            self.w["spells"] = p
            self.box.addWidget(section(tr("Spells known (choose {0})", sp["known"]), hint, p))
            self._pending.append((tr("Spells known"), p.done))
        if sp.get("prepared") is not None:
            if sp.get("spellbook") is not None:
                pool = list(state.get("spellbook") or []) + (self.w["spellbook"].chosen() if "spellbook" in self.w else [])
            else:
                pool = [n for n in sp["spell_pool"] if n not in always]
            selected = P.get("prepared") if P.get("prepared") is not None else state.get("prepared") or []
            p = picks(pool, sp["prepared"], selected, self.changed, self.rows + 4, spells=True)
            self.w["prepared"] = p
            self.box.addWidget(section(tr("Prepared spells (up to {0})", sp["prepared"]),
                                       tr("You can change this list after every long rest. Domain/oath spells are free."), p))

    def _spellbook_changed(self):
        if "prepared" in self.w:
            book = list((self.plan.get("spell_state") or {}).get("spellbook") or [])
            self.w["prepared"].set_options(list(dict.fromkeys(book + self.w["spellbook"].chosen())))
        self.changed()

    # ------------------------------------------------------------------ api
    def collect(self) -> dict:
        out: dict = {}
        if hasattr(self, "hp_mode"):
            if self.hp_mode == "max":
                out["hp"], out["hp_roll"] = "roll", self.plan["hit_die"]
            elif self.hp_mode == "roll":
                out["hp"], out["hp_roll"] = "roll", self.hp_roll.value()
            else:
                out["hp"] = "average"
        if self.plan.get("subclass"):
            out["subclass"] = self._subclass
        if self.w.get("grants"):
            out["subclass_choices"] = {k: p.chosen() for k, p in self.w["grants"].items()}
        for k in ("skills", "tools", "expertise", "cantrips", "spells", "spellbook", "prepared"):
            if k in self.w:
                out[k] = self.w[k].chosen()
        if self.w["options"]:
            out["options"] = {k: p.chosen() for k, p in self.w["options"].items()}
        if self.plan.get("asi"):
            if self.asi_mode == "feat":
                out["asi"] = {"feat": self.feat.value(), "feat_choices": self.feat.choices()}
            else:
                a, b = self.asi_a.currentData(), self.asi_b.currentData()
                out["asi"] = {"abilities": {a: 2} if not b or b == a else {a: 1, b: 1}}
        return out

    def pending(self) -> List[str]:
        return [t for t, ok in self._pending if not ok()]

    def subclass(self) -> str:
        return self._subclass

