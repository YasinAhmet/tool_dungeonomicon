"""What the battle windows share: the battle-wide signals (area preview), round token pictures, the side colours,
hit point bars and the small flows several windows run (casting a spell, adding players, damage or heal)."""
from typing import Dict, List, Optional, Sequence, Tuple

from PySide6.QtCore import QObject, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap
from PySide6.QtWidgets import QDialog, QMenu, QProgressBar, QPushButton

from ....core.i18n import tr
from ....core.runtime import rt
from ... import dialogs, notify
from ...errors import guard
from ...theme import COLORS
from ...widgets.common import label
from ...widgets.icons import IconChoice
from ...widgets.pickers import PickList

SIDE = {"pc": "#4f8cff", "ally": "#2fb59a", "enemy": "#e0524d", "out": "#6b7280"}
TURN, SELECTED, TARGET, AREA = "#ffd24a", "#ffffff", "#ff5c5c", "#ff8c28"


class BattleHub(QObject):
    """Signals between the battle windows (the focused combatant travels on app.ui.selection.hub().combatant)."""
    area = Signal(object)            # an area preview {'tiles', 'ids'} for the map, or None
    aim = Signal(object)             # aiming an action on the map {'cid', 'item', 'slot', 'dtype', 'option', 'adv'}, or None
    place = Signal(str)              # a map symbol or prop to place with the next click on the Battle map
    quick = Signal()                 # the quick bar's pinned symbols and props changed


_hub: Optional[BattleHub] = None


def battle_hub() -> BattleHub:
    global _hub
    if _hub is None:
        _hub = BattleHub()
    return _hub


def side_color(c: dict) -> str:
    """Its faction's colour (the battle view fills it in), grey when it is out of the fight."""
    if c.get("out"):
        return SIDE["out"]
    return c.get("faction_color") or (SIDE["pc"] if c["kind"] == "pc" else SIDE["ally"] if c.get("ally") else SIDE["enemy"])


def initials(name: str) -> str:
    words = [w for w in name.replace("(", " ").split() if w[:1].isalpha()]
    if not words:
        return name[:2]
    return (words[0][0] + (words[1][0] if len(words) > 1 else words[0][1:2])).upper()


# ---------------------------------------------------------------------- pictures
_pictures: Dict[str, Optional[QPixmap]] = {}
_tokens: Dict[Tuple, QPixmap] = {}


def picture(path: Optional[str]) -> Optional[QPixmap]:
    """The token picture of a file path (loaded once), or None when there is none or it can't be read."""
    if not path:
        return None
    if path not in _pictures:
        pm = QPixmap(path)
        _pictures[path] = None if pm.isNull() else pm
    return _pictures[path]


def token(c: dict, size: int) -> QPixmap:
    """A round token: the picture cut to a circle inside a ring of its faction's colour, or its initials. A framed
    portrait (a character's own token, border and all) is drawn as it is inside a thin faction ring, faded when the
    character is down."""
    size = max(8, int(size))
    key = (c.get("token"), bool(c.get("framed")), bool(c.get("framed") and c.get("out")), c["name"], side_color(c), size)
    if key in _tokens:
        return _tokens[key]
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    img = picture(c.get("token"))
    if img and c.get("framed"):
        p.setOpacity(0.45 if c.get("out") else 1.0)
        ring = max(2, size // 20)
        inner = size - 2 * ring
        p.drawPixmap(ring, ring, img.scaled(inner, inner, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        p.setOpacity(1.0)
        p.setPen(QPen(QColor(side_color(c)), ring))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QRectF(ring / 2, ring / 2, size - ring, size - ring))
        p.end()
        _tokens[key] = pm
        return pm
    col = QColor(side_color(c))
    p.setPen(Qt.NoPen)
    p.setBrush(col)
    p.drawEllipse(QRectF(1, 1, size - 2, size - 2))
    ring = max(2, size // 14)
    if img:
        inner = QRectF(1 + ring, 1 + ring, size - 2 - 2 * ring, size - 2 - 2 * ring)
        clip = QPainterPath()
        clip.addEllipse(inner)
        p.setClipPath(clip)
        scaled = img.scaled(int(inner.width()) + 1, int(inner.height()) + 1, Qt.KeepAspectRatioByExpanding, Qt.SmoothTransformation)
        p.drawPixmap(int(inner.x() + (inner.width() - scaled.width()) / 2), int(inner.y() + (inner.height() - scaled.height()) / 2), scaled)
        p.setClipping(False)
    else:
        p.setPen(QColor("#ffffff"))
        f = p.font()
        f.setBold(True)
        f.setPixelSize(max(7, int(size * 0.38)))
        p.setFont(f)
        p.drawText(QRectF(0, 0, size, size), Qt.AlignCenter, initials(c["name"]))
    p.setClipping(False)
    p.setPen(QPen(QColor(0, 0, 0, 120), 1))
    p.setBrush(Qt.NoBrush)
    p.drawEllipse(QRectF(0.5, 0.5, size - 1, size - 1))
    p.end()
    if len(_tokens) > 600:
        _tokens.clear()
    _tokens[key] = pm
    return pm


# ---------------------------------------------------------------------- widgets
def hp_color(fraction: float) -> str:
    return COLORS["bad"] if fraction <= 0.25 else COLORS["warn"] if fraction <= 0.5 else COLORS["good"]


class HpBar(QProgressBar):
    """A thin hit point bar coloured by how hurt the creature is."""

    def __init__(self, height: int = 8):
        super().__init__()
        self.setTextVisible(False)
        self.setFixedHeight(height)
        self.setRange(0, 1000)

    def set_hp(self, hp: int, max_hp: int):
        f = max(0.0, min(1.0, hp / max_hp)) if max_hp else 0.0
        self.setValue(int(f * 1000))
        self.setStyleSheet(f"QProgressBar::chunk {{ background: {hp_color(f)}; border-radius: 3px; }}")


class HoverButton(QPushButton):
    """A button that says when the pointer comes and goes (spell chips preview their area on the map)."""

    def __init__(self, text: str, on_click=None, on_enter=None, on_leave=None):
        super().__init__(text)
        self._enter, self._leave = on_enter, on_leave
        if on_click:
            self.clicked.connect(lambda *_: on_click())

    def enterEvent(self, e):
        if self._enter:
            guard(self._enter)
        super().enterEvent(e)

    def leaveEvent(self, e):
        if self._leave:
            guard(self._leave)
        super().leaveEvent(e)


# ---------------------------------------------------------------------- flows
def attempt(fn, *args) -> bool:
    """Call a service (failures become a notification); True when it went through."""
    return guard(lambda: (fn(*args), True)[1]) is True


def say(result):
    """Show what a battle call reported (the full line also went to the battle log)."""
    if result:
        notify.good(tr(str(result)))


def preview_area(spell: Optional[str]):
    """Show on the map the tiles `spell` would cover, cast by whoever's turn it is at the target."""
    b = rt().battle
    st = b.state()
    if not spell or not st.get("turn") or not st.get("target"):
        battle_hub().area.emit(None)
        return
    r = b.area_preview(spell, st["turn"], st["target"])
    battle_hub().area.emit(r if r and r.get("tiles") else None)


def spell_choice(parent, spell: str, slot_level=None) -> Tuple[bool, Optional[str]]:
    """Before a cast: pick a damage type or a summoned creature when the spell asks for one. (ok, choice)."""
    info = rt().battle.spell_info(spell, slot_level if isinstance(slot_level, int) else None) or {}
    if info.get("options"):
        got = dialogs.choose_from(parent, tr("{0}: choose", spell), [(tr(o["label"]), o["value"]) for o in info["options"]])
        return got is not None, got
    if info.get("types"):
        damage = set(info["types"]) <= set(damage_types())
        title = tr("{0}: damage type", spell) if damage else tr("{0}: choose", spell)   # Eyebite's, Contagion's picks aren't damage types
        got = dialogs.choose_one(parent, title, [(tr(str(t).capitalize()), t) for t in info["types"]])
        return got is not None, got
    return True, None


def add_players(parent, free):
    """Ask which characters join, folded by player (none ticked; Add active chars takes this session's party), and add
    them, rolling their initiative."""
    if not free:
        notify.info(tr("Everyone is already in."))
        return
    free = list(free)
    session = set(rt().players.session_party())
    owners = {}
    for uid, p in sorted(rt().players.all().items(), key=lambda kv: (kv[1]["name"] or "").lower()):
        for n in p["characters"]:
            owners.setdefault(n, p["name"] or str(uid))
    rank = {o: i for i, o in enumerate(dict.fromkeys(owners.values()))}
    free.sort(key=lambda n: (rank.get(owners.get(n), len(rank)), n.lower()))
    options = [{"value": n, "label": ("● " if n in session else "") + n, "group": owners.get(n) or tr("Unassigned")} for n in free]
    d = dialogs.Dialog(parent, tr("Add players"), 420, 500)
    d.body.addWidget(label(tr("Who joins the battle? ● marks this session's characters (right-click a character in Party "
                              "to mark it)."), role="dim", wrap=True))
    pl = PickList(options, count=len(free), selected=[], detail=None, sort_groups=False)
    pl.expand_all(True)
    d.body.addWidget(pl)
    active = [n for n in free if n in session]

    def take_active():
        pl.set_chosen(pl.chosen() + [n for n in active if n not in pl.chosen()])
        d.accept()
    btn = QPushButton(tr("Add active chars") + (f" ({len(active)})" if active else ""))
    btn.setToolTip(tr("Add every character marked as playing this session (Party ▸ right-click ▸ Active session char), "
                      "with any you ticked") if active else
                   tr("No character here is marked as playing this session: right-click characters in Party to mark them."))
    btn.setEnabled(bool(active))
    btn.clicked.connect(take_active)
    d.buttons.insertWidget(0, btn)
    d.ok_cancel()
    if d.exec() != QDialog.Accepted:
        return
    for n in pl.chosen():
        guard(rt().battle.add_player, n, None, True)


DAMAGE_TYPES = ("acid", "bludgeoning", "cold", "fire", "force", "lightning", "necrotic", "piercing", "poison", "psychic",
                "radiant", "slashing", "thunder")
ABILITY_NAMES = (("str", "Strength"), ("dex", "Dexterity"), ("con", "Constitution"), ("int", "Intelligence"),
                 ("wis", "Wisdom"), ("cha", "Charisma"))


def damage_types() -> List[str]:
    fn = getattr(rt().battle, "damage_types", None)
    return list((guard(fn) if fn else None) or DAMAGE_TYPES)


def type_items() -> List[tuple]:
    return [(tr("Untyped"), "")] + [(tr(t.capitalize()), t) for t in damage_types()]


def type_choice() -> IconChoice:
    """The damage type as a square: the type's picture in its map colour (a dot: untyped), the types in its menu."""
    from ....services.battle.icons import DAMAGE as PICTURES
    from .vfx import DAMAGE as COLOURS
    items = [(tr("Untyped"), "", None, None)] + [(tr(t.capitalize()), t, PICTURES.get(t), COLOURS.get(t)) for t in damage_types()]
    return IconChoice(items, tr("Damage type: resistance, immunity and vulnerability apply"))


def _names(cids: Sequence[int]) -> Dict[int, str]:
    return {c["id"]: c["name"] for c in rt().battle.view()["combatants"] if c["id"] in cids}


def hp_change(parent, cids, kind: str, name: str = ""):
    """Ask how much damage (its type, and who saved for half) or healing, for one creature or several, and apply it."""
    cids = [cids] if isinstance(cids, int) else list(cids)
    names = _names(cids)
    who = name or ", ".join(names.get(i, "?") for i in cids[:4]) + ("…" if len(cids) > 4 else "")
    fields = [{"key": "n", "label": tr("How much damage does {0} take?", who) if kind == "damage" else tr("How much does {0} heal?", who),
               "kind": "int", "value": 0, "min": 0, "max": 9999}]
    if kind == "damage":
        fields.append({"key": "dtype", "label": tr("Damage type"), "kind": "select", "options": type_items(), "value": "",
                       "tip": tr("Resistance, immunity and vulnerability apply")})
        if len(cids) == 1:
            fields.append({"key": "half", "label": tr("Saved: half damage"), "kind": "check"})
        else:
            fields += [{"key": f"s{i}", "label": tr("{0} saved (half)", names.get(i, "?")), "kind": "check"} for i in cids]
    got = dialogs.form(parent, tr("Damage") if kind == "damage" else tr("Heal"), fields)
    if not got or not got["n"]:
        return
    apply_hp(cids, kind, got["n"], got.get("dtype") or None, [i for i in cids if got.get("half") or got.get(f"s{i}")])


def apply_hp(cids: List[int], kind: str, n: int, dtype: Optional[str] = None, halved: Sequence[int] = ()):
    """Damage (typed, some halved) or heal one creature or several; one undo step for several."""
    b = rt().battle
    if kind == "heal":
        say(b.heal(cids[0], n) if len(cids) == 1 else b.heal_many(cids, n))
    elif len(cids) == 1:
        say(b.damage(cids[0], n, dtype, cids[0] in halved))
    else:
        say(b.damage_many(cids, n, dtype, list(halved)))


def set_conditions(cids: List[int], condition: str, on: bool, **duration):
    b = rt().battle
    if len(cids) == 1:
        b.set_condition(cids[0], condition, on, **duration)
    else:
        b.set_condition_many(cids, condition, on, **duration)


def timer_text(t: Optional[dict]) -> str:
    """'3 rds', 'save DC 13 WIS' - a condition's countdown in the menus and the order."""
    if not t:
        return ""
    bits = [tr("{0} rds", t["rounds"])] if t.get("rounds") else []
    if t.get("save"):
        bits.append(tr("save DC {0} {1}", t["save"].get("dc"), str(t["save"].get("ability", "")).upper()))
    return ", ".join(bits)


def token_card(view: dict, c: dict) -> str:
    """A creature's hover card on the battle map (rich text): name and kind, HP and AC, its conditions and effects with
    their pictures and countdowns, what it concentrates on, where it stands and what it carries."""
    import html
    from ....services.battle import view as V
    from ....services.battle.icons import BADGES, path as icon_path
    esc = html.escape
    dim = COLORS["dim"]
    out = [f"<b>{esc(c['name'])}</b>" + (f" <span style='color:{dim}'>{esc(tr(c['sub']))}</span>" if c.get("sub") else "")]
    hp = f"{c['hp']}/{c['max_hp']} " + tr("HP") + (f" +{c['temp_hp']}" if c.get("temp_hp") else "")
    out.append(hp + f" · {tr('AC')} {c['ac']}" + ("" if c.get("hp_shown", True) else f" <span style='color:{dim}'>({esc(tr('players see: {0}', tr(c.get('health') or '')))})</span>"))
    timers = c.get("cond_timers") or {}
    marks = []
    for k in list(c.get("conditions") or []) + [e["name"] for e in c.get("effects") or []]:
        pic = BADGES.get(k) and icon_path(BADGES[k][0])
        img = f"<img src='{esc(pic)}' width='14' height='14'> " if pic else ""
        colour = BADGES[k][1] if k in BADGES else COLORS["warn"]
        rounds = next((e.get("rounds") for e in c.get("effects") or [] if e["name"] == k and e.get("rounds")), None)
        extra = timer_text(timers[k]) if k in timers else tr("{0} rds", rounds) if rounds else ""
        marks.append(f"{img}<span style='color:{colour}'>{esc(tr(k))}</span>" + (f" <span style='color:{dim}'>({esc(extra)})</span>" if extra else ""))
    if marks:
        out.append("<br>".join(marks))
    if c.get("concentrating"):
        out.append(f"<span style='color:{COLORS['warn']}'>◎ {esc(tr('Concentrating on {0}', c['concentrating']['spell']))}</span>")
    if c.get("pos"):
        out.append(f"<span style='color:{dim}'>{esc(V.tile_name(*c['pos']))}</span>")
    carried = ", ".join(f"{i['name']} ×{i['qty']}" if i["qty"] > 1 else i["name"] for i in c.get("items") or [])
    if carried:
        out.append(esc(tr("Carries: {0}", carried)))
    return "<qt>" + "<br>".join(out) + "</qt>"


def condition_dialog(parent, cids: List[int], condition: Optional[str] = None):
    """A condition with an end: a number of rounds (ending at the start or end of someone's turn) and/or a save
    repeated at the end of each of the creature's turns."""
    from ....rules.character import CONDITIONS
    v = rt().battle.view()
    got = dialogs.form(parent, tr("Condition with a duration"), [
        {"key": "cond", "label": tr("Condition"), "kind": "select", "options": [(tr(k), k) for k in CONDITIONS], "value": condition},
        {"key": "rounds", "label": tr("Rounds (0: until it is removed or saved)"), "kind": "int", "value": 1, "min": 0, "max": 1000},
        {"key": "until", "label": tr("Ends at"), "kind": "select", "value": "end",
         "options": [(tr("the end of a turn"), "end"), (tr("the start of a turn"), "start")]},
        {"key": "by", "label": tr("Whose turn"), "kind": "select", "value": 0,
         "options": [(tr("The creature's own"), 0)] + [(c["name"], c["id"]) for c in v["combatants"]]},
        {"key": "ability", "label": tr("Save at the end of its turns"), "kind": "select", "value": "",
         "options": [(tr("No save"), "")] + [(tr(n), k) for k, n in ABILITY_NAMES]},
        {"key": "dc", "label": tr("Save DC"), "kind": "int", "value": 13, "min": 1, "max": 40}], tr("Apply"))
    if not got:
        return
    if not got["rounds"] and not got["ability"]:
        set_conditions(cids, got["cond"], True)
        return
    set_conditions(cids, got["cond"], True, rounds=got["rounds"] or None, until=got["until"], by=got["by"] or None,
                   save={"ability": got["ability"], "dc": got["dc"]} if got["ability"] else None)


def next_turn(parent):
    """End the turn; a reaction still waiting for an answer is skipped only when the DM says so."""
    b = rt().battle
    p = b.pending()
    if p and not dialogs.confirm(parent, tr("{0}'s reaction is still waiting for an answer. Skip it and end the turn?", p["reactor_name"]),
                                 tr("Next turn"), tr("Skip it")):
        return
    guard(b.next_turn)


def undo():
    """Take back the last change to the battle (damage, a move, a turn, a removal...)."""
    b = rt().battle
    if not b.undo_label():
        notify.info(tr("Nothing to undo."))
        return
    what = guard(b.undo)
    if what:
        notify.good(tr("Undone: {0}", tr(what)))


def combatant_menu(parent, cs: List[dict], on_play=None) -> QMenu:
    """The right-click menu of one creature or several (from the map or the initiative order)."""
    from ....rules.character import CONDITIONS
    from ...selection import hub
    b = rt().battle
    ids = [c["id"] for c in cs]
    one = cs[0] if len(cs) == 1 else None
    m = QMenu(parent)
    if not one:
        m.addSection(tr("{0} creatures", len(cs)))
    from ....services.battle.icons import BADGES
    from ...widgets.icons import game_icon
    m.addAction(game_icon("damage", 16, COLORS["bad"]), tr("Damage…"), lambda: guard(hp_change, parent, ids, "damage"))
    m.addAction(game_icon("heal", 16, COLORS["good"]), tr("Heal…"), lambda: guard(hp_change, parent, ids, "heal"))
    conds = m.addMenu(tr("Conditions"))
    timers = (one or {}).get("cond_timers") or {}
    for k in CONDITIONS:                                     # its picture: in its badge's colour when on, dim when off
        on = all(k in (c.get("conditions") or []) for c in cs)
        a = conds.addAction(game_icon("exhaustion" if k == "Exhaustion" else k, 16,
                                      (BADGES.get(k) or ("", COLORS["warn"]))[1] if on else "#4b5263"),
                            ("✓ " if on else "") + tr(k) + (f"  ({timer_text(timers.get(k))})" if timers.get(k) else ""))
        a.setCheckable(True)
        a.setChecked(on)
        a.toggled.connect(lambda on, k=k: guard(set_conditions, ids, k, on))
    conds.addSeparator()
    conds.addAction(tr("With a duration or a save…"), lambda: guard(condition_dialog, parent, ids))
    _faction_menu(m.addMenu(tr("Faction")), parent, cs)
    if one:
        c = one
        m.addSeparator()
        m.addAction(tr("Set hit points…"), lambda: _ask_then(parent, tr("Hit points of {0}", c["name"]), c["hp"], b.set_hp, c["id"]))
        m.addAction(tr("Temporary hit points…"), lambda: _ask_then(parent, tr("Temporary hit points of {0}", c["name"]),
                                                                   c.get("temp_hp") or 0, b.set_temp_hp, c["id"]))
        m.addAction(tr("Set initiative…"), lambda: _ask_then(parent, tr("Initiative of {0}", c["name"]), c["init"] or 0,
                                                             b.set_initiative, c["id"], low=-10))
        if c.get("turn") is not None:
            _turn_points_menu(m.addMenu(tr("Turn points")), parent, c)
        if c["kind"] == "enemy":
            m.addAction(tr("Rename…"), lambda: _rename(parent, c))
            m.addAction(tr("Duplicate"), lambda: guard(b.duplicate, c["id"]))
            m.addAction(tr("Hide exact HP from players") if c.get("revealed") else tr("Reveal exact HP to players"),
                        lambda: guard(b.reveal, c["id"], not c.get("revealed")))
        if c.get("items") and c.get("pos"):
            carried = ", ".join(f"{tr(i['name'])} ×{i['qty']}" if i["qty"] > 1 else tr(i["name"]) for i in c["items"])
            m.addAction(tr("Drop what it carries ({0})", carried), lambda: guard(b.drop_carried, c["id"]))
        m.addSeparator()
        m.addAction(tr("Show its card"), lambda: hub().combatant.emit(c["id"]))
        if on_play:
            m.addAction(tr("▶ Play it now"), lambda: on_play(c["id"]))
    if any(c.get("pos") for c in cs):
        m.addAction(tr("Take off the map"), lambda: [guard(b.unplace, c["id"]) for c in cs if c.get("pos")])
    m.addSeparator()
    m.addAction(tr("Remove from the battle"), lambda: _remove(cs))
    return m


def faction_name(f: int) -> str:
    return {0: tr("Neutral (hostile to everyone)"), 1: tr("Faction 1 (players)"), 2: tr("Faction 2 (monsters)")}.get(f) \
        or tr("Faction {0}", f)


def _swatch(color: str) -> QIcon:
    pm = QPixmap(16, 16)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    p.setPen(QPen(QColor(0, 0, 0, 140), 1))
    p.setBrush(QColor(color))
    p.drawEllipse(QRectF(1.5, 1.5, 13, 13))
    p.end()
    return QIcon(pm)


def _faction_menu(m: QMenu, parent, cs: List[dict]):
    """Put the creatures in a faction (who is hostile to whom, the ring of their tokens), and each faction's colour."""
    from ....services.battle.constants import FACTIONS
    from ....services.battle.view import battle_view
    b = rt().battle
    ids = [c["id"] for c in cs]
    colors = {int(k): v for k, v in (battle_view(shared=True).get("faction_colors") or {}).items()}
    for f in FACTIONS:
        a = m.addAction(_swatch(colors.get(f, SIDE["out"])), faction_name(f), lambda f=f: guard(b.set_faction, ids, f))
        a.setCheckable(True)
        a.setChecked(all(c.get("faction") == f for c in cs))
    m.addSeparator()
    sub = m.addMenu(tr("Faction colours"))
    for f in FACTIONS:
        sub.addAction(_swatch(colors.get(f, SIDE["out"])), faction_name(f) + "…", lambda f=f: _pick_faction_color(parent, f, colors.get(f)))
    sub.addSeparator()
    sub.addAction(tr("Default colours"), lambda: [guard(b.set_faction_color, f, None) for f in FACTIONS])


def _pick_faction_color(parent, f: int, now: Optional[str]):
    from PySide6.QtWidgets import QColorDialog
    col = QColorDialog.getColor(QColor(now or SIDE["out"]), parent, tr("Colour of {0}", faction_name(f)))
    if col.isValid():
        guard(rt().battle.set_faction_color, f, col.name())


def _turn_points_menu(m: QMenu, parent, c: dict):
    """Set what the creature has left this turn - like setting its hit points."""
    b = rt().battle
    t = c["turn"]
    rows = [("action", tr("Actions: {0}…", t.get("action", 0))), ("bonus", tr("Bonus actions: {0}…", t.get("bonus", 0))),
            ("reaction", tr("Reactions: {0}…", t.get("reaction", 0))), ("move", tr("Movement: {0} ft…", t.get("move", 0))),
            ("attacks", tr("Attacks left of the Attack action: {0}…", t.get("attacks", 0)))]
    if t.get("legendary_max"):
        rows.append(("legendary", tr("Legendary actions: {0}…", t.get("legendary", 0))))
    for key, text in rows:
        m.addAction(text, lambda key=key: _ask_then(parent, tr("Turn points of {0}", c["name"]), t.get(key, 0),
                                                     lambda cid, n: b.set_turn_points(cid, key, n), c["id"]))
    m.addSeparator()
    m.addAction(tr("Full turn again"), lambda: guard(b.fresh_turn_points, c["id"]))


def _ask_then(parent, title_: str, value: int, fn, cid: int, low: int = 0):
    n = dialogs.ask_int(parent, title_, title_, int(value or 0), low, 9999)
    if n is not None:
        guard(fn, cid, n)


def _rename(parent, c: dict):
    n = dialogs.ask_text(parent, tr("Rename"), tr("Name"), c["name"])
    if n:
        guard(rt().battle.rename_combatant, c["id"], n)


def _remove(cs: List[dict]):
    gone = [c["name"] for c in cs if attempt(rt().battle.remove, c["id"])]
    if gone:
        notify.info(tr("{0} removed. Ctrl+Z brings it back.", ", ".join(gone)))


# ---------------------------------------------------------------------- aiming an action (BG3 style)
def needs_click(item: dict) -> bool:
    t = item.get("target") or {}
    return t.get("type") in ("creature", "split", "point") or (t.get("type") == "self_area" and t.get("aim", True))


def start_aim(parent, cid: int, item: dict, slot=None, adv=None):
    """Pick an action or spell from the action bar: ask what the spell needs (damage type, creature to summon), then
    either do it at once (self, no target) or hand it to the map to aim (creatures, a point, a direction)."""
    if not item.get("ok", True):
        notify.warn(tr(item.get("why") or "Not now"))
        return
    aim = {"cid": cid, "item": item, "slot": slot, "dtype": None, "option": None, "adv": adv, "targets": [], "point": None}
    if item.get("kind") == "spell":
        lvl = slot if isinstance(slot, int) else item.get("level")
        ok, choice = spell_choice(parent, item["name"], lvl)
        if not ok:
            return
        if choice is not None:
            info = rt().battle.spell_info(item["name"], lvl if isinstance(lvl, int) else None) or {}
            aim["option" if info.get("options") else "dtype"] = choice
    if item.get("options"):
        got = dialogs.choose_from(parent, tr("{0}: choose", tr(item["name"])), [(tr(o["label"]), o["value"]) for o in item["options"]])
        if got is None:
            return
        aim["option"] = got
    if item.get("metamagic"):
        mm = dialogs.choose_one(parent, tr("{0}: Metamagic", tr(item["name"])),
                                [(tr("No Metamagic"), "")] + [(f"{tr(m['name'])} ({m['cost']} SP)", m["name"]) for m in item["metamagic"]])
        if mm is None:
            return
        aim["metamagic"] = mm or None
    t = item.get("target") or {}
    if t.get("type") == "fixed":
        aim["targets"] = [t["id"]]
        return commit_aim(aim)
    if not needs_click(item):
        return commit_aim(aim)
    battle_hub().aim.emit(aim)


def commit_aim(aim: dict):
    battle_hub().aim.emit(None)
    item = aim["item"]
    slot = aim.get("slot")
    say(guard(rt().battle.act, aim["cid"], item["id"], aim.get("targets") or None, aim.get("point"), slot,
              aim.get("dtype"), aim.get("option"), aim.get("adv"), False, aim.get("metamagic")))


def aim_count(aim: dict) -> int:
    item = aim["item"]
    t = item.get("target") or {}
    lvl = item.get("level") or 0
    slot = aim.get("slot") if isinstance(aim.get("slot"), int) else lvl
    base = t.get("base_level", lvl) or 0
    return int(t.get("count") or 1) + int(t.get("per_level") or 0) * max(0, (slot or 0) - base)
