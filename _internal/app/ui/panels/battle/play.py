"""Play mode of the Battle map: the DM plays whoever's turn it is (a monster, an ally, a player character) the way
players play theirs on the portal - who is played with their hit points and state and the creature's action bar, in
the initiative band under the map (under the row of tokens); what happens goes to the battle log (Enter ▸ Battle). And the overlays both modes share: the aim bar and the reaction popup floating on
the map.

By default it follows the turn; pick a creature (or double-click its token) to play it instead - for a legendary
action, a reaction or a summoned ally between turns."""
import html
from typing import Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QCheckBox, QFrame, QHBoxLayout, QScrollArea, QSizePolicy, QVBoxLayout, QWidget

from ....core.i18n import tr
from ....core.runtime import rt
from ....services.battle import icons, view as V
from ....services.battle.icons import BADGES
from ...errors import guard
from ...widgets.common import button, clear_layout, combo, label, row, set_items
from ...widgets.icons import AdvSwitch
from .actionbar import ActionBar
from .common import HpBar, aim_count, needs_click, next_turn, side_color



class MapHost(QWidget):
    """The map with the aim bar and the reaction popup floating on it."""

    def __init__(self, canvas: QWidget, parent=None):
        super().__init__(parent)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(canvas)
        self.aimbar = QFrame(self)
        self.aimbar.setObjectName("card")
        self.aimbar.setStyleSheet("#card { background: rgba(22, 26, 33, 235); border: 1px solid #7c8cff; border-radius: 6px; }")
        self.aimbar.setLayout(QHBoxLayout())
        self.aimbar.layout().setContentsMargins(8, 4, 8, 4)
        self.aimbar.hide()
        self.popup = QFrame(self)
        self.popup.setObjectName("card")
        self.popup.setStyleSheet("#card { background: #161a21; border: 2px solid #fbbf24; border-radius: 8px; }")
        self.popup.setLayout(QVBoxLayout())
        self.popup.layout().setContentsMargins(12, 10, 12, 10)
        self.popup.hide()

    def place(self):
        w = self.width()
        self.aimbar.setGeometry(8, 8, max(200, w - 16), self.aimbar.sizeHint().height())
        self.popup.adjustSize()
        pw = min(460, w - 20)
        self.popup.setFixedWidth(pw)
        self.popup.adjustSize()
        self.popup.move(int((w - pw) / 2), int(max(10, (self.height() - self.popup.height()) / 2)))
        self.aimbar.raise_()
        self.popup.raise_()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.place()


class _FitScroll(QScrollArea):
    """A scroll area that tells its owner when its width changes (the action bar's rows wrap anew)."""

    def __init__(self, content: QWidget, on_width):
        super().__init__()
        self.setWidgetResizable(True)
        self.setFrameShape(QFrame.NoFrame)
        self.setWidget(content)
        self.on_width = on_width

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if e.oldSize().width() != e.size().width():
            QTimer.singleShot(0, self, self.on_width)


class PlayDeck:
    """The play-mode widgets around the map: `top` (who is played, advantage, next turn, hit points and state) and
    `bottom` (the action bar)."""

    def __init__(self, owner):
        self.owner = owner                    # the Battle map window
        self.playing = None                   # a creature picked to play (None: whoever's turn it is)
        self.prefs = {"adv": None}
        self.bar = None
        self.bar_cid = None
        self.who = label("")
        self.who.setTextFormat(Qt.RichText)
        f = self.who.font()
        f.setPointSize(f.pointSize() + 2)
        self.who.setFont(f)
        self.pick = combo([], on_change=lambda v: self.play(v or None),
                          tip=tr("Whose turn to play: follow the turn, or a creature of your choice (double-click a token)"))
        self.pick.setMinimumWidth(110)
        self.adv = AdvSwitch(on_change=lambda v: self.prefs.__setitem__("adv", v),
                             tip=tr("For the next attack or spell (back to Normal after it)"))
        self.next_btn = button(tr("⏭ Next turn"), lambda: next_turn(owner), kind="primary", tip=tr("End this turn (Ctrl+Space)"))
        self.hp = HpBar(7)
        self.status = label("", role="dim", wrap=True)
        self.status.setTextFormat(Qt.RichText)
        self.top = QWidget()
        lay = QVBoxLayout(self.top)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        self.who.setWordWrap(True)
        self.who.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self.pick.setMaximumWidth(200)
        head = row(self.who, self.pick, self.adv, self.next_btn)   # one line for who, one for their hit points and state
        head.setStretchFactor(self.who, 1)
        lay.addLayout(head)
        self.hp.setFixedWidth(140)
        line = row(self.hp, self.status, spacing=8)
        line.setStretchFactor(self.status, 1)
        lay.addLayout(line)
        self.bar_host = QWidget()
        self.bar_box = QVBoxLayout(self.bar_host)
        self.bar_box.setContentsMargins(4, 4, 4, 4)
        self.bar_scroll = _FitScroll(self.bar_host, self.fit_bar)
        self.bar_scroll.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.bar_scroll.setMinimumHeight(60)
        self.bottom = QWidget()
        lay = QVBoxLayout(self.bottom)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(2)
        lay.addWidget(self.bar_scroll, 1)

    # ------------------------------------------------------------------ who is played
    def playing_id(self) -> Optional[int]:
        v = self.owner.canvas.view or {}
        if self.playing and V.find(v, self.playing):
            return self.playing
        return v.get("turn")

    def play(self, cid: Optional[int]):
        self.playing = cid
        self.owner.cancel_aim()
        guard(self.owner.refresh)

    # ------------------------------------------------------------------ showing it
    def refresh(self, v: dict):
        if self.playing and not V.find(v, self.playing):
            self.playing = None
        cid = self.playing_id()
        c = V.find(v, cid)
        set_items(self.pick, [(tr("Follow the turn"), 0)] + [(x["name"], x["id"]) for x in v["combatants"]], self.playing or 0)
        self.adv.blockSignals(True)
        self.adv.setCurrentIndex(max(0, self.adv.findData(self.prefs.get("adv"))))
        self.adv.blockSignals(False)
        self.next_btn.setEnabled(v["status"] == "active")
        if not c:
            self.who.setText(html.escape(tr("No creature to play")) + " <span style='color:#8b93a3'>"
                             + html.escape(tr("(pick one under Playing, or start the battle in the initiative order under the map)")) + "</span>")
            self.hp.set_hp(0, 1)
            self.status.setText("")
            self._bar(None)
            return
        mine = v.get("turn") == cid
        tag = tr("out of combat: any action, any time") if v["status"] != "active" else \
            tr("their turn") if mine else tr("not their turn: reactions and legendary actions only")
        self.who.setText(f"<b style='color:{side_color(c)}'>{html.escape(c['name'])}</b> "
                         f"<span style='color:#8b93a3'>{html.escape(tr(c.get('sub') or ''))} · {html.escape(tag)}</span>")
        self.hp.set_hp(c["hp"], c["max_hp"])
        esc = html.escape
        bits = [esc(tr("{0}/{1} HP", c["hp"], c["max_hp"]) + (f" +{c['temp_hp']}" if c.get("temp_hp") else "")), esc(tr("AC {0}", c["ac"]))]
        for name, extra in [(x, "") for x in c.get("conditions") or []] + \
                [(e["name"], f" ({e['rounds']})" if e.get("rounds") else "") for e in c.get("effects") or [] if not e.get("_tmp")]:
            look = BADGES.get(name)                          # a condition or effect with a picture: it shows, in its colour
            pic = look and icons.path(look[0])
            bits.append((f"<img src='{esc(pic)}' width='13' height='13'> <span style='color:{look[1]}'>" if pic else "<span>")
                        + esc(tr(name) + extra) + "</span>")
        if c.get("concentrating"):
            bits.append(esc("◎ " + tr(c["concentrating"]["spell"])))
        if not c.get("pos"):
            bits.append(esc(tr("not on the map")))
        tgt = [t for t in (V.find(v, i) for i in v.get("picked") or []) if t]
        if tgt:
            bits.append(esc("🎯 " + ", ".join(t["name"] for t in tgt)))
        self.status.setText(" · ".join(bits))
        self._bar(cid)

    def _bar(self, cid):
        if cid != self.bar_cid:
            clear_layout(self.bar_box)
            self.bar, self.bar_cid = None, cid
            if cid:
                self.bar = ActionBar(cid, self.prefs, on_pick=self.owner.pick_item, fold_spells=True, hotkeys=True)
                self.bar.on_fold = lambda: QTimer.singleShot(0, self.bar_scroll, self.fit_bar)
                self.bar_box.addWidget(self.bar)
                self.bar_box.addStretch(1)
        elif self.bar is not None:
            self.bar.refresh()
        QTimer.singleShot(0, self.bar_scroll, self.fit_bar)

    def fit_bar(self):
        """The bar's box at least as tall as its rows (up to 260 px): no row hides behind a scroll bar while there is room."""
        host = self.bar_host
        width = self.bar_scroll.viewport().width()
        need = host.heightForWidth(width) if host.hasHeightForWidth() else host.sizeHint().height()
        if need > 0:
            self.bar_scroll.setMinimumHeight(max(60, min(260, need + 2)))

    def hotkey(self, n: int) -> bool:
        """Number key n on the map: the n-th action of the bar (as clicked). False when there is none."""
        items = self.bar.hotkeys if self.bar is not None else []
        if not 1 <= n <= len(items):
            return False
        self.bar._go(items[n - 1])
        return True

    def set_aiming(self, item_id):
        if self.bar:
            self.bar.set_aiming(item_id)

    def used_adv(self):
        """Advantage is for one roll: back to Normal once it was used."""
        if self.prefs.get("adv"):
            self.prefs["adv"] = None
            self.adv.blockSignals(True)
            self.adv.setCurrentIndex(0)
            self.adv.blockSignals(False)

    def show_result(self, text):
        """A battle call's answer: the same line went to the battle log, read there (Enter ▸ Battle)."""


def render_aimbar(owner):
    """The aim bar on the map: what to click, the slot / damage type / option / Metamagic, Confirm and Cancel."""
    bar = owner.host.aimbar
    lay = bar.layout()
    clear_layout(lay)
    a = owner.aim
    if not a:
        bar.hide()
        return
    item = a["item"]
    t = item.get("target") or {}
    need = {"creature": tr("click {0} creature(s) ({1}/{0})", aim_count(a), len(a["targets"])),
            "split": tr("click a target for each of {0} ({1}/{0}) - the same creature more than once is fine", aim_count(a), len(a["targets"])),
            "point": tr("click where to go (up to {0} ft)", t["teleport"]) if t.get("teleport") else tr("click a point within {0} ft", item.get("range")),
            "self_area": tr("click the direction to aim")}.get(t.get("type"), tr("confirm to use it"))
    who = V.find(owner.canvas.view or {}, a["cid"])
    head = label(f"<b>🎯 {html.escape(tr(item['name']))}</b>" + (f" <span style='color:#8b93a3'>· {html.escape(who['name'])}</span>" if who else ""))
    head.setTextFormat(Qt.RichText)
    lay.addWidget(head)
    lay.addWidget(label(need, role="dim"))
    if item.get("kind") == "spell" and item.get("level"):
        a_ = guard(rt().battle.available_actions, a["cid"]) or {}
        levels = [(g["level"], (g.get("slots") or {}).get("left")) for g in a_.get("spells") or []
                  if g["level"] >= item["level"] and (g.get("slots") or {}).get("left")]
        if len(levels) > 1:
            lay.addWidget(combo([(tr("Level {0} slot ({1} left)", lv, n), lv) for lv, n in levels], current=a.get("slot"),
                                on_change=lambda v: (a.__setitem__("slot", v), render_aimbar(owner))))
        elif levels:
            lay.addWidget(label(tr("uses a level {0} slot ({1} left)", levels[0][0], levels[0][1]), role="dim"))
    if item.get("types"):
        lay.addWidget(combo([(tr(x.capitalize()), x) for x in item["types"]], current=a.get("dtype"),
                            on_change=lambda v: a.__setitem__("dtype", v)))
    if a.get("options"):
        lay.addWidget(combo([(tr(o["label"]), o["value"]) for o in a["options"]], current=a.get("option"),
                            on_change=lambda v: a.__setitem__("option", v)))
    if item.get("metamagic"):
        lay.addWidget(combo([(tr("No Metamagic"), "")] + [(f"{tr(m['name'])} ({m['cost']} SP)", m["name"]) for m in item["metamagic"]],
                            current=a.get("metamagic") or "", on_change=lambda v: a.__setitem__("metamagic", v or None)))
    adv = AdvSwitch(on_change=lambda v: a.__setitem__("adv", v), tip=tr("For this roll"))
    adv.setCurrentIndex(adv.findData(a.get("adv")))
    lay.addWidget(adv)
    lay.addStretch(1)
    pick = _target_in_reach(owner, a, who) if t.get("type") in ("creature", "split") and not a["targets"] else None
    a["pick"] = pick["id"] if pick else None              # the DM's target, in reach: one click (or Enter), as on the portal
    if pick:
        lay.addWidget(button(tr("Pick {0}", pick["name"]), lambda: pick_target(owner, a, pick["id"]), kind="primary", tip=tr("Enter")))
    if not needs_click(item) or (t.get("type") in ("creature", "split") and a["targets"]):
        lay.addWidget(button(tr("Confirm"), lambda: owner.commit(a), kind="primary", tip=tr("Enter")))
    lay.addWidget(button(tr("Cancel"), owner.cancel_aim, tip=tr("Esc / right-click")))
    bar.show()
    owner.host.place()


def _target_in_reach(owner, a: dict, me: Optional[dict]) -> Optional[dict]:
    """The battle's target when this aim could take it: not the one acting, on the map and within the action's range."""
    from ....services.battle import geometry as G
    v = owner.canvas.view or {}
    tgt = V.find(v, v.get("target")) if v.get("target") else None
    if not tgt or tgt["id"] == a["cid"] or not tgt.get("pos") or not me or not me.get("pos"):
        return None
    reach = a["item"].get("range")
    far = G.distance_ft(me["pos"], V.span(me), tgt["pos"], V.span(tgt))
    return tgt if reach is None or far <= max(5, reach) else None


def pick_target(owner, a: dict, cid: int):
    """The aim takes this creature, as a click on its token would."""
    if cid not in a["targets"]:
        a["targets"].append(cid)
    if len(a["targets"]) >= aim_count(a):
        owner.commit(a)
    else:
        owner.canvas.update()
        render_aimbar(owner)


def render_pending(owner) -> bool:
    """The reaction the battle waits for, as a popup on the map (both modes). True when one is shown."""
    p = rt().battle.pending()
    key = (p["rid"], p["text"], tuple(o["key"] for o in p["options"])) if p else None
    if key == owner.pending_key:
        return bool(p)
    owner.pending_key = key
    box = owner.host.popup
    lay = box.layout()
    clear_layout(lay)
    if not p:
        box.hide()
        return False
    who = tr("player - also asked on the portal") if p.get("kind") == "pc" else tr("monster")
    head = label(f"<b style='color:#fbbf24'>⚡ {html.escape(tr('Reaction'))} · {html.escape(p['reactor_name'])}</b> "
                 f"<span style='color:#8b93a3'>({html.escape(who)})</span>", wrap=True)
    head.setTextFormat(Qt.RichText)
    lay.addWidget(head)
    text = label(tr(p["text"]), wrap=True)
    f = text.font()
    f.setPointSize(f.pointSize() + 1)
    text.setFont(f)
    lay.addWidget(text)
    remember = QCheckBox(tr("Don't ask again for this creature (do what I pick from now on)"))
    family = lambda key: (key or p["options"][0]["key"]).split(":")[0]  # noqa: E731

    def answer(key):
        for b in box.findChildren(QWidget):
            b.setEnabled(False)                       # one answer: a second click would find nothing waiting
        if remember.isChecked():
            guard(rt().battle.set_reaction_mode, p["reactor"], family(key), "always" if key else "never")
        owner.show_result(guard(rt().battle.react, p["rid"], key))
        if rt().battle.pending():                     # it didn't go through: ask again
            owner.pending_key = None
            render_pending(owner)
    groups = {}                                       # a smite's slot levels: one button and a level dropdown
    for o in p["options"]:
        if o.get("group"):
            groups.setdefault(o["group"], []).append(o)
    for o in p["options"]:
        if o.get("group"):
            opts = groups.pop(o["group"], None)
            if opts:
                pick = combo([(tr(x["choice"]), x["key"]) for x in opts])
                b = button(tr(o["group"]), lambda c=pick: answer(c.currentData()), kind="primary")
                b.setStyleSheet("text-align: left; padding: 6px 10px;")
                line = row(b, pick)
                line.setStretch(0, 1)
                lay.addLayout(line)
            continue
        b = button(tr(o["label"]) + (f"  ({tr(o['detail'])})" if o.get("detail") else ""), lambda k=o["key"]: answer(k), kind="primary")
        b.setStyleSheet("text-align: left; padding: 6px 10px;")
        lay.addWidget(b)
    lay.addWidget(button(tr("Don't react"), lambda: answer(None)))
    lay.addWidget(remember)
    lay.addWidget(label(tr("The battle waits for this answer.") if p.get("kind") != "pc" else
                        tr("The battle waits for this answer: the player can answer on the portal, or you answer for them."),
                        role="dim", wrap=True))
    if p.get("deadline"):
        import time
        lay.addWidget(label(tr("Skipped by itself at {0} if nobody answers.", time.strftime("%H:%M:%S", time.localtime(p["deadline"]))),
                            role="warn"))
    box.show()
    owner.host.place()
    box.raise_()
    return True
