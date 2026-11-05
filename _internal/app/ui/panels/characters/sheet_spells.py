"""The sheet's spells: each casting class (save DC, attack, Prepare / Copy into the spellbook), the spell slots with
manual corrections, and every spell as a chip - click to cast, right-click for ritual casting, damage and the text."""
from PySide6.QtCore import QSize
from PySide6.QtWidgets import QMenu

from ....core.i18n import tr
from ....services.battle.icons import for_spell
from ....services.characters import view
from ... import dialogs
from ...errors import guard
from ...selection import show_content
from ...widgets.common import button, label, row, stretch
from ...widgets.icons import game_icon
from .sheet_widgets import Chip, flow, pips, rich_tip, section, sign


def build(sheet, d: dict, lay, compact: bool = False):
    doc = d["doc"]
    if not (doc["casting"] or doc["spells"]):
        if not compact:
            lay.addWidget(label(tr("{0} doesn't cast spells.", d["name"]), role="dim"))
        return
    lines = []
    for i, c in enumerate(doc["casting"]):
        caster = d["casters"][i] if i < len(d["casters"]) else {}
        extra = []
        if not compact and caster.get("spellbook"):
            extra.append(button(tr("Copy"), lambda cls=c["class"]: copy_spell(sheet, cls),
                                tip=tr("Copy a spell into the spellbook")))
        if not compact and caster.get("prepared") is not None:
            extra.append(button(tr("Prepare"), lambda cls=c["class"]: prepare(sheet, cls),
                                tip=tr("Choose the prepared spells (up to {0})", caster["prepared"])))
        lines.append(row(label(f"<b>{tr(c['class'])}</b> · " + tr("DC {0} · {1} to hit", c["dc"], sign(c["attack"])),
                               tip=rich_tip(c["tip"])), stretch(), *extra))
    slots = {key: (name, most, left) for key, name, most, left in doc["slot_rows"]}

    def slot_pips(key: str) -> list:                         # a pip per slot: a full one marks it used, an empty one gives it back
        name, most, left = slots.pop(key)
        used = most - left
        return [*pips(left, most, lambda k=key, u=used, m=most: sheet.call("set_slot_used", k, min(m, u + 1)),
                      lambda k=key, u=used: sheet.call("set_slot_used", k, max(0, u - 1)), tr("{0} slots", tr(name))),
                label(f"{left}/{most}", role="dim")]
    levels = []                                              # a level's slots sit on its heading; the rest (pact) get a row
    for g in doc["spells"]:
        key = str(g["level"])
        levels.append(row(label(tr(g["title"]), role="accent"), stretch(), *(slot_pips(key) if key in slots else []), spacing=1))
        levels.append(flow(*[_chip(sheet, s) for s in g["spells"]]))
    for key in list(slots):
        lines.append(row(label(tr(slots[key][0]), role="dim"), *slot_pips(key), stretch(), spacing=1))
    lines += levels
    lay.addWidget(section(tr("Spellcasting"), *lines))


def _chip(sheet, s: dict) -> Chip:
    text = tr(s["name"]) + (" (R)" if s["ritual"] else "") + (" (C)" if s["concentration"] else "")
    if s["uses"]:
        text += f"  · {s['uses']}"
    hint = tr("Click to cast; right-click for more.") if not s["ritual"] else tr("Click to cast; right-click for ritual casting.")
    chip = Chip(text, lambda: sheet.cast(s["name"]), tip=s["tip"] + "\n\n" + hint, kind="primary" if s["uses"] else "")
    icon = game_icon(for_spell(s["name"]), 14, "#c4b5fd")         # the action bar's picture of the spell
    if not icon.isNull():
        chip.setIcon(icon)
        chip.setIconSize(QSize(14, 14))
    chip.right_clicked.connect(lambda: _menu(sheet, s, chip))
    chip.hovered.connect(lambda on: sheet.spell_hovered.emit(s["name"] if on else ""))
    return chip


def _menu(sheet, s: dict, chip: Chip):
    m = QMenu(chip)
    m.addAction(tr("Cast"), lambda: sheet.cast(s["name"]))
    if s["ritual"]:
        m.addAction(tr("Cast as a ritual (no slot)"), lambda: sheet.cast(s["name"], ritual=True))
    m.addAction(tr("Roll damage"), lambda: _damage(sheet, s["name"], False))
    m.addAction(tr("Roll critical damage"), lambda: _damage(sheet, s["name"], True))
    m.addSeparator()
    m.addAction(tr("Read the description"), lambda: show_content("spells", s["name"]))
    m.exec(chip.mapToGlobal(chip.rect().bottomLeft()))


def _damage(sheet, spell: str, crit: bool):
    r = sheet.call("spell_damage", spell, sheet.slot.currentData(), crit)
    if r is not None:
        sheet.say(r.text)


def prepare(sheet, cls: str):
    pool = guard(view.spell_pool, sheet.name, cls, "prepare")
    if not pool:
        return
    picked = dialogs.pick(sheet, tr("Prepare {0} spells", tr(cls)), pool["pool"], count=pool["count"] or 0,
                          selected=pool["selected"], exact=False,
                          prompt=tr("Choose up to {0} spells. You can change this after a long rest.", pool["count"]))
    if picked is not None:
        sheet.call("set_prepared", cls, picked)


def copy_spell(sheet, cls: str):
    pool = guard(view.spell_pool, sheet.name, cls, "copy")
    if not pool:
        return
    picked = dialogs.pick(sheet, tr("Copy a spell into the spellbook"), pool["pool"], count=1, exact=False,
                          prompt=tr("Copying takes 2 hours and 50 gp per spell level (track the cost yourself)."))
    if picked:
        sheet.call("add_spellbook_spell", picked[0])
