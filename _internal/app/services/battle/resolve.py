"""Playing an action out: attack rolls, saving throws, damage and what follows, as a resumable record.

A resolution ("R") is a plain dict kept on `b['pending']` (a stack) while it runs. It walks through stages; at a
reaction window (an attack that hits, damage about to land, a spell being cast, a creature leaving reach) it asks the
reactions catalog who may react. A reactor set to "always" reacts by itself, "never" doesn't, and "ask" pauses the
whole resolution until the player (portal) or the DM (editor) answers with react(). The record then picks up where it
stopped. A reaction that is itself an action (an opportunity attack, Hellish Rebuke) pushes its own resolution on top.

Kinds: 'strike' (attacks / saves / automatic damage against targets, the workhorse), 'spell' (a cast: counterspell
window, then its effect), 'walk' (movement step by step, see movement.py), 'zone' (a lasting area triggering),
'dsave' (a player's death saving throw).

Async rolling (the battle rule 'async_rolls'): a player's attack roll, saving throw or death save is shown as a d20
rolling on every screen (an fx 'roll'), and the resolution holds (R['dice']) until it has stopped - a timer, or the
next action if the timer was lost, lets it go on.
"""
import re
import threading
import time
from typing import List, Optional

from ...rules import engine as E
from ...rules.dice import roll_dice
from ..common import Busy, ServiceError
from . import combat_rules as CR
from . import conditions as K
from . import modifiers as M
from . import sight as V
from .constants import ACTIVE

WAIT, NEXT, DONE = "wait", "next", "done"
ROLL_SECONDS = 1.8                                          # how long the dice roll on screen (rule 'roll_seconds')
REVEAL = 0.8                                                # the result stays up this long before the action goes on


def held(R: dict) -> bool:
    """Is this resolution paused: a question to answer, or dice still rolling?"""
    return bool(R.get("wait") or R.get("dice"))


def roll(expr) -> int:
    if isinstance(expr, int):
        return expr
    expr = str(expr or "").replace(" ", "")
    if not expr:
        return 0
    try:
        return int(roll_dice(expr).total)
    except Exception:  # noqa: BLE001 - a broken dice text deals nothing rather than stopping the battle
        return 0


_SIZES = ("Tiny", "Small", "Medium", "Large", "Huge", "Gargantuan")


def _bigger_than(size: str, cap: str) -> bool:
    """'Huge' is bigger than 'Large' (an effect that stops at a size)."""
    return size in _SIZES and cap in _SIZES and _SIZES.index(size) > _SIZES.index(cap)


class ResolveMixin:
    # ------------------------------------------------------------------ the stack
    def _stack(self) -> list:
        return self.b.setdefault("pending", [])

    def _new_r(self, kind: str, actor: Optional[dict], label: str, **kw) -> dict:
        rid = self.b.get("rid_next", 1)
        self.b["rid_next"] = rid + 1
        return {"rid": rid, "kind": kind, "actor": actor["id"] if actor else None, "label": label, "stage": "start",
                "lines": [], "short": [], "wait": None, **kw}

    def _line(self, R: dict, text: str, short: Optional[str] = None):
        R["lines"].append(text)
        self._say(text, False)
        if short:
            R["short"].append(short)

    def _run_r(self, R: dict) -> str:
        """Start a resolution and drive it to its end, or until it waits for an answer. Returns what happened."""
        stack = self._stack()
        if stack and not any(held(r) for r in stack):
            stack.clear()                                   # left over from a failed call
        self._busy()
        stack.append(R)
        return self._drive()

    def _drive(self) -> str:
        stack = self._stack()
        outer = stack[0] if stack else None
        guard = 0
        while stack:
            guard += 1
            if guard > 5000:
                stack.clear()
                raise ServiceError("The action got stuck and was stopped.")
            R = stack[-1]
            if held(R):
                break
            got = getattr(self, f"_step_{R['kind']}")(R)
            if got == WAIT:
                break
            if got == DONE:
                stack.pop()
                if stack:
                    parent = stack[-1]
                    parent["lines"] += R["lines"]
                    parent["short"] += [x for x in R["short"] if x]
                else:
                    self._summary(R)
        if not outer:
            return ""
        text = "\n".join(outer["lines"])
        if stack and stack[-1].get("wait"):
            return (text + "\n" if text else "") + f"⏳ {stack[-1]['wait']['text']}"
        if stack and stack[-1].get("dice"):
            return (text + "\n" if text else "") + "🎲 …"
        return text

    # ------------------------------------------------------------------ async rolling
    def _dice(self, R: dict, c: Optional[dict], label: str, res: dict, vs: str, outcome: str) -> bool:
        """With async rolling on, show a player's d20 on every screen and hold R until it stops. True when held."""
        rules_ = self.b.get("rules") or {}
        if not rules_.get("async_rolls") or c is None or c["kind"] != "pc" or self.b.get("status") != "active":
            return False
        secs = max(0.5, min(5.0, float(rules_.get("roll_seconds") or ROLL_SECONDS)))
        kept = int(res.get("kept") or 0)
        self._vfx("roll", id=c["id"], who=c["name"], label=label, dice=[int(d) for d in res.get("dice") or [kept]], kept=kept,
                  bonus=int(res.get("total") or 0) - kept, total=int(res.get("total") or 0), vs=vs, res=outcome,
                  mode=res.get("mode") or "", dur=secs, chips=list(res.get("chips") or []))
        R["dice"] = {"until": time.time() + secs + REVEAL}
        self._commit()                                      # every screen starts rolling now
        timer = threading.Timer(secs + REVEAL, self._dice_timer)
        timer.daemon = True
        timer.start()
        return True

    def _dice_timer(self):
        try:
            self._dice_done()
        except Exception as e:  # noqa: BLE001 - a failing step must not kill the timer thread silently
            self.h.log(f"[BATTLE] the action after the dice failed: {e}")
            with self.lock:
                self._commit()

    def _dice_done(self, force: bool = False) -> str:
        """The dice stopped: the held resolution goes on. Too early (and not forced): nothing happens."""
        with self.lock:
            R = next((r for r in reversed(self._stack()) if r.get("dice")), None)
            if R is None or (not force and time.time() < R["dice"]["until"] - 0.05):
                return ""
            R["dice"] = None
            try:
                return self._drive()
            finally:
                self._commit()

    def _summary(self, R: dict):
        actor = self._find_or_none(R.get("actor"))
        who = actor["name"] if actor else "?"
        names = R.get("summary_targets")
        if names is None:
            names = ", ".join(self._find_or_none(t)["name"] for t in R.get("targets") or [] if self._find_or_none(t))
        tail = " | ".join(x for x in R["short"] if x)
        self._event(f"{who} → {names or '—'}: {R['label']}" + (f", {tail}" if tail else ""))

    def _find_or_none(self, cid) -> Optional[dict]:
        return next((c for c in self.b["combatants"] if c["id"] == cid), None) if cid else None

    # ------------------------------------------------------------------ answering a reaction
    def pending(self) -> Optional[dict]:
        """The question the battle is waiting on: {'rid', 'reactor', 'reactor_name', 'character', 'text', 'options',
        'window', 'since', 'deadline'} ('since' / 'deadline': epoch seconds; deadline None = no time limit).
        A player's question past the battle rule 'react_timeout' is let pass here first."""
        with self.lock:
            self._react_overdue()
            for R in reversed(self._stack()):
                if R.get("wait"):
                    w = R["wait"]
                    c = self._find_or_none(w["reactor"])
                    return {"rid": R["rid"], "reactor": w["reactor"], "reactor_name": c["name"] if c else "?",
                            "character": c.get("character") if c else None, "kind": c["kind"] if c else None,
                            "text": w["text"], "options": w["options"], "window": w["window"],
                            "since": w.get("since"), "deadline": self._react_deadline(R)}
            return None

    def pending_age(self) -> Optional[float]:
        """Seconds since the waiting reaction question was asked (None when nothing waits)."""
        p = self.pending()
        return max(0.0, time.time() - p["since"]) if p and p.get("since") else None

    def pending_deadline(self) -> Optional[float]:
        """When (epoch seconds) the waiting question passes by itself (rule 'react_timeout'), or None."""
        p = self.pending()
        return p["deadline"] if p else None

    def busy(self) -> Optional[str]:
        """Why the battle can't take an action now (dice rolling, a reaction to answer), or None."""
        with self.lock:
            try:
                self._busy()
            except ServiceError as e:
                return str(e)
            return None

    # ------------------------------------------------------------------ answering in time (rule 'react_timeout')
    def _react_deadline(self, R: dict) -> Optional[float]:
        w = R.get("wait") or {}
        secs = float((self.b.get("rules") or {}).get("react_timeout") or 0)
        c = self._find_or_none(w.get("reactor"))
        if secs <= 0 or not w.get("since") or not c or c["kind"] != "pc":
            return None
        return w["since"] + secs

    def _react_clock(self, R: dict):
        """A player's question with a time limit: a timer lets it pass when the time is up."""
        deadline = self._react_deadline(R)
        if deadline is None:
            return
        timer = threading.Timer(max(0.0, deadline - time.time()) + 0.05, self._react_timer)
        timer.daemon = True
        timer.start()

    def _react_timer(self):
        try:
            with self.lock:
                self._react_overdue()
        except Exception as e:  # noqa: BLE001 - a failing step must not kill the timer thread silently
            self.h.log(f"[BATTLE] letting a late reaction pass failed: {e}")

    def _react_overdue(self) -> bool:
        """Let every question whose time is up pass (logged), and go on with the action. True when one did."""
        late = False
        for _ in range(50):
            R = next((r for r in reversed(self._stack()) if r.get("wait") and (self._react_deadline(r) or 1e18) <= time.time()), None)
            if R is None:
                break
            late = True
            w = R["wait"]
            c = self._find_or_none(w["reactor"])
            self._say(f"{c['name'] if c else '?'} didn't answer in time: the reaction is skipped", False)
            R["answer"] = {"reactor": w["reactor"], "key": None}
            R["wait"] = None
            self._drive()
        if late:
            self._commit()
        return late

    def react(self, rid: int, choice: Optional[str]) -> str:
        """Answer the waiting reaction question: an option key, or None to let it pass."""
        with self.lock:
            stack = self._stack()
            R = next((r for r in stack if r["rid"] == int(rid)), None)
            if not R or not R.get("wait"):
                raise ServiceError("Nothing is waiting for that answer any more.")
            w = R["wait"]
            if choice is not None and choice not in [o["key"] for o in w["options"]]:
                raise ServiceError("That isn't one of the choices.")
            R["answer"] = {"reactor": w["reactor"], "key": choice}
            R["wait"] = None
            out = self._drive()
            self._commit()
            return out

    def _clear_pending(self, why: str = "skipped"):
        """Let every waiting question pass (the turn moved on): the resolutions finish without those reactions."""
        n = 0
        while any(held(r) for r in self._stack()) and n < 50:
            n += 1
            for R in reversed(self._stack()):
                if R.get("dice"):
                    R["dice"] = None
                    break
                if R.get("wait"):
                    c = self._find_or_none(R["wait"]["reactor"])
                    self._say(f"{c['name'] if c else '?'}'s reaction was skipped ({why})", False)
                    R["answer"] = {"reactor": R["wait"]["reactor"], "key": None}
                    R["wait"] = None
                    break
            self._drive()
        if self._stack() and not any(held(r) for r in self._stack()):
            self._stack().clear()

    def _busy(self):
        """Raise Busy while the dice roll or a reaction question waits (a late one is let pass first)."""
        if any(r.get("dice") for r in self._stack()):
            self._dice_done()                               # overdue (the timer was lost): go on now
            if any(r.get("dice") for r in self._stack()):
                raise Busy("The dice are still rolling.")
        if any(r.get("wait") for r in self._stack()):
            p = self.pending()
            if p:
                raise Busy(f"Waiting for {p['reactor_name']} to answer: {p['text']}")

    # ------------------------------------------------------------------ windows
    def _window(self, R: dict, name: str, next_stage: str, **ctx) -> str:
        """Ask everyone who may react at this point (reactions catalog), in order. Returns NEXT when all are done."""
        win = R.get("win")
        if not win or win.get("name") != name:
            R["win"] = win = {"name": name, "queue": self._eligible(name, R, **ctx), "ctx": {k: v for k, v in ctx.items()}}
        if R.get("answer"):
            ans = R.pop("answer")
            if ans["key"]:
                self._apply_reaction(name, R, self._find_or_none(ans["reactor"]), ans["key"], **win["ctx"])
            win["queue"] = [q for q in win["queue"] if q["reactor"] != ans["reactor"]]
            if ans["key"] == "counterspell":
                win["queue"] = []
        while win["queue"]:
            item = win["queue"][0]
            reactor = self._find_or_none(item["reactor"])
            if not reactor or not self._may_react(reactor, item.get("cost", "reaction")):
                win["queue"].pop(0)
                continue
            options = [o for o in item["options"] if self._still_ok(name, R, reactor, o)]
            if not options:
                win["queue"].pop(0)
                continue
            mode = self._react_mode(reactor, options[0]["key"].split(":")[0])
            if mode == "never":
                win["queue"].pop(0)
                continue
            if mode == "always":
                pick = self._auto_pick(name, R, reactor, options, **win["ctx"])
                win["queue"].pop(0)
                if pick:
                    self._apply_reaction(name, R, reactor, pick, **win["ctx"])
                    if pick == "counterspell":
                        win["queue"] = []
                continue
            R["wait"] = {"reactor": reactor["id"], "window": name, "options": options,
                         "text": item.get("text") or f"{reactor['name']}: react?", "since": time.time()}
            self._react_clock(R)
            return WAIT
        R.pop("win", None)
        R["stage"] = next_stage
        return NEXT

    def _react_mode(self, c: dict, family: str) -> str:
        own = (c.get("react") or {}).get(family)
        if own in ("always", "never", "ask"):
            return own
        rules_ = self.b.get("rules") or {}
        if c["kind"] == "pc":
            return rules_.get("pc_reactions", "ask")
        return rules_.get("npc_reactions", "always")

    def set_reaction_mode(self, cid: int, family: str, mode: str):
        """Per creature and reaction (BG3 style): 'ask', 'always' or 'never'."""
        with self.lock:
            if mode not in ("ask", "always", "never"):
                raise ServiceError("Choose ask, always or never.")
            self._find(cid).setdefault("react", {})[family] = mode
            self._commit()

    def _may_react(self, c: dict, cost: str = "reaction") -> bool:
        if not self._can_act(c) or self._fxs(c, "no_reactions"):
            return False
        t = c.get("turn")
        if cost == "free" or self.b.get("status") != ACTIVE:    # out of combat the budget refreshes itself
            return True
        return t is None or t.get(cost.split(":")[0], 0) > 0

    # ------------------------------------------------------------------ rolls
    def _d20_roll(self, c: Optional[dict], bonus: int, mode: Optional[str], triple: bool = False):
        """(total, kept, dice) with Halfling Luck rerolling ones; Elven Accuracy rolls three dice with advantage."""
        rng = self.rng
        dice = [rng.randint(1, 20)] + ([rng.randint(1, 20)] if mode in ("adv", "dis") else []) + ([rng.randint(1, 20)] if triple else [])
        if c is not None and self._fxs(c, "lucky"):
            dice = [rng.randint(1, 20) if d == 1 else d for d in dice]
        kept = max(dice) if mode == "adv" else min(dice) if mode == "dis" else dice[0]
        if c is not None and kept < 10 and self._fxs(c, "trance"):    # Trance of Order: a 9 or lower counts as 10
            kept = 10
        if c is not None and kept == 1 and self._topsy_turvy(c):    # a Jester's Mask: a 1 counts as a 20, once a day (spellitems.py)
            kept = 20
        if c is not None and kept == 1:
            self._nf_nat1(c)                                        # the Ravenloft feats' drawbacks after a 1 (newfeats.py)
        return kept + bonus, kept, dice

    def _use_once(self, c: dict, key: str, tgt: Optional[dict] = None, failed: bool = False):
        for e, _v in list(M.effect_list(c.get("effects"), key)):
            if e.get("mods", {}).get("once") or e.get("once_" + key):
                if e["name"] == "Bardic Inspiration" and key in ("attack", "save") and self._subc_bi_used(c, e, key, tgt, failed):
                    continue                                    # Unfailing Inspiration: the die is kept (subfeats_c.py)
                self._effect_off(c, e, "used")

    def _attack_check(self, att: dict, tgt: dict, a: dict) -> dict:
        """Roll one attack: {'total', 'kept', 'ac', 'hit', 'crit', 'mode', 'why', 'cover'}."""
        melee = a.get("melee", True)
        d = self._dist(att, tgt) if att.get("pos") and tgt.get("pos") else 5
        within5 = d <= 5
        modes = set()
        why = []
        if a.get("adv") in ("adv", "dis"):
            modes.add(a["adv"])
            why.append("chosen")
        for _e, v in self._fxs(att, "attacks_with"):
            modes.add(v)
            why.append(_e["name"])
        for _e, _v in self._fxs(att, "duel"):                  # Compelled Duel: disadvantage against anyone but the caster
            if _e.get("source_id") != tgt["id"]:
                modes.add("dis")
                why.append(_e["name"])
        for _e, v in self._fxs(att, "shun"):                   # Chill Touch on an undead: disadvantage against the caster
            if _e.get("source_id") == tgt["id"] and (v == "*" or str(v).lower() in str((self._monster(att) or {}).get("type") or "").lower()):
                modes.add("dis")
                why.append(_e["name"])
        for _e, v in self._fxs(tgt, "attacks_against"):
            modes.add(v)
            why.append(_e["name"])
        for _e, _v in self._fxs(tgt, "adv_by_source"):          # a vampiric jade statue's curse: advantage for the one who cursed it
            if _e.get("source_id") == att["id"]:
                modes.add("adv")
                why.append(_e["name"])
        for _e, _v in self._fxs(att, "adv_vs_hurt"):            # Abyssal Visage: a creature that doesn't have all its hit points
            if self._hp_of(tgt) < self._max_hp(tgt):
                modes.add("adv")
                why.append(_e["name"])
        for _e, v in self._fxs(tgt, "warded_from"):             # Protection from Evil and Good: only those kinds are put off
            kind_of = str((self._monster(att) or {}).get("type") or "").lower() if not self._sheet(att) or att.get("form") else ""
            if kind_of and any(k in kind_of for k in v):
                modes.add("dis")
                why.append(_e["name"])
        for _e, v in self._fxs(tgt, "melee_against" if melee else "ranged_against"):
            modes.add(v)
            why.append(_e["name"])
        if melee and a.get("str_based"):
            for _e, v in self._fxs(att, "str_melee_adv"):
                modes.add("adv")
                why.append(_e["name"])
        cm, cwhy = K.attack_modes(self._conds(att), self._conds(tgt), melee=melee, within_5=within5,
                                  att_exhaustion=self._exhaustion(att))
        modes |= cm
        why += cwhy
        if att.get("pos") and tgt.get("pos"):
            if not self._sees(att, tgt):
                modes.add("dis")
                why.append("can't see the target")
            if not self._sees(tgt, att) and not self._feat(tgt, "alert"):
                modes.add("adv")
                why.append("unseen attacker")
            if not melee:
                close = [o for o in self.b["combatants"] if o is not att and o.get("pos") and self._hostile(o, att)
                         and self._can_act(o) and self._dist(o, att) <= 5 and self._sees(o, att)]
                if close and not self._fxs(att, "no_ranged_penalty") and not a.get("no_melee_dis"):
                    modes.add("dis")
                    why.append("enemy within 5 ft")
                if a.get("normal") and d > a["normal"] and not a.get("no_long_dis"):
                    modes.add("dis")
                    why.append("long range")
            if self._fxs(att, "pack_tactics") and any(o is not att and not self._hostile(o, att) and self._can_act(o)
                                                     and o.get("pos") and self._dist(o, tgt) <= 5 for o in self.b["combatants"]):
                modes.add("adv")
                why.append("pack tactics")
        if a.get("weapon") and "heavy" in (a.get("props") or []) and self._size_of(att) in ("Tiny", "Small"):
            modes.add("dis")
            why.append("heavy weapon, small wielder")
        if self._feat(att, "grappler") and any((e.get("mods") or {}).get("grappler") == att["id"] for e in tgt.get("effects") or []):
            modes.add("adv")
            why.append("Grappler")
        for e_, v in self._fxs(att, "adv_vs"):                  # Vow of Enmity, Versatile Trickster
            if v == tgt["id"]:
                modes.add("adv")
                why.append(e_["name"].split(" (")[0])
                break
        for mode_, why_ in self._trait_modes(att, tgt, a) + self._class_modes(att, tgt, a):    # Blood Frenzy, Ambusher; Wolf totem...
            modes.add(mode_)
            why.append(why_)
        ach = self._sheet(att)
        if ach and ach.class_level("Rogue") >= 3 and (ach.class_entry("Rogue") or {}).get("subclass") == "Assassin" \
                and self.b.get("status") == ACTIVE and not tgt.get("had_turn"):
            modes.add("adv")                                    # Assassinate: a creature that hasn't taken a turn yet
            why.append("Assassinate")
        if "adv" in modes and self._fxs(tgt, "no_adv_against") and not K.incapacitated(self._conds(tgt)):
            modes.discard("adv")                                # Elusive: no attack roll has advantage against the rogue
            why.append("Elusive")
        self._wonder_modes(att, tgt, a, modes, why)             # Spellguard Shield, Boots of Speed (wondrous.py)
        mode = K.combine(modes)
        mode = self._subc_mode(att, mode, why)                  # Drunkard's Luck (subfeats_c.py)
        bonus = int(a.get("bonus") or 0)
        chips = []                                              # what effects add, for the d20 on screen
        extra, note = self._mod_roll(att, "attack", chips)
        if a.get("weapon"):                                     # Magic Weapon: the weapon's own +1, not spells or flasks
            e3, n3 = self._mod_roll(att, "weapon_attack", chips)
            extra, note = extra + e3, note + n3
        if a.get("spell"):
            e2, n2 = self._mod_roll(att, "spell_attack", chips)
            extra, note = extra + e2, note + n2
        triple = mode == "adv" and self._feat(att, "elven_accuracy") and (a.get("ability") in ("dex", "int", "wis", "cha") or a.get("spell"))
        total, kept, dice = self._d20_roll(att, bonus, mode, triple)
        total, kept = self._wonder_roll(att, total, kept)          # a Clockwork Amulet's 10 (wondrous.py)
        total += extra
        if melee and att.get("turn") is not None:
            att["turn"].setdefault("melee_targets", []).append(tgt["id"])
        cov = self._cover_between(att, tgt) if att.get("pos") and tgt.get("pos") and not a.get("ignore_cover") else V.NONE
        if a.get("ignore_partial_cover") and cov < V.TOTAL:
            cov = V.NONE
        ac = self._ac_of(tgt) + (cov if cov < V.TOTAL else 0) + self._wonder_ac(tgt, a, att)    # + an Arrow-Catching Shield's
        vs = self._class_ac_vs(att, tgt)                        # Multiattack Defense: against this attacker only
        ac += vs
        crit_at = M.crit_range(self._all_effects(att)) if a.get("weapon") or a.get("crit_any") else 20
        crit_at = min(crit_at, self._class_crit_vs(att, tgt), int(a.get("crit_at") or 20))   # Hexblade's Curse; Ephixis' 19
        if kept == 1:
            hit, crit = False, False
        elif kept >= crit_at:
            hit, crit = True, True
        else:
            hit, crit = total >= ac, False
        if hit and not crit and melee and K.auto_crit(self._conds(tgt), within5):
            crit = True
            why.append("target can't defend itself")
        if cov >= V.TOTAL:
            hit, crit = False, False
        if crit and self._wonder_no_crit(tgt, why):             # adamantine armour: a normal hit
            crit = False
        for key in ("attacks_with", "attack", "spell_attack"):
            self._use_once(att, key, tgt, not hit)
        self._use_once(tgt, "attacks_against")
        return {"total": total, "kept": kept, "dice": dice, "ac": ac, "hit": hit, "crit": crit, "mode": mode, "why": why,
                "cover": cov, "bonus": bonus, "note": note, "chips": chips, "ac_extra": vs}

    @staticmethod
    def _save_mode_note(res: dict) -> str:
        """' adv (Magic Resistance)' for a save line: rolled with advantage or disadvantage, and why."""
        if not res.get("mode"):
            return ""
        return f" {res['mode']}" + (f" ({', '.join(res['why'])})" if res.get("why") else "")

    def _saving_throw(self, c: dict, ab: str, dc: int, *, spell: bool = False, conds=(), source: Optional[dict] = None,
                      cover: int = 0, label: str = "", adv: bool = False) -> dict:
        """One saving throw with everything that changes it. {'total', 'kept', 'ok', 'auto', 'note', 'mode'}.
        adv: advantage of its own (a charm spell against a creature the caster is fighting), or 'dis' (Sunburst on undead)."""
        conds_now = self._conds(c)
        auto = K.save_mode(conds_now, ab, self._exhaustion(c))
        modes = set()
        why = []
        if adv:
            modes.add("dis" if adv == "dis" else "adv")
            why.append("its kind" if adv == "dis" else adv if isinstance(adv, str) else "fighting the caster")
        if auto == "fail":
            self._roll_line(c, "🛡️", f"{ab.upper()} save", 0, f"automatic failure vs DC {dc}")
            return {"total": 0, "kept": 0, "ok": False, "auto": True, "note": " (automatic failure)", "mode": None, "dc": dc}
        if auto == "dis":
            modes.add("dis")
        for e, v in self._fxs(c, "save_adv"):
            if M.abilities_hit(v, ab, spell):
                modes.add("adv")
                why.append(e["name"])
        for e, v in self._fxs(c, "save_dis"):
            if M.abilities_hit(v, ab, spell):
                modes.add("dis")
                why.append(e["name"])
        if spell:
            for e, v in self._fxs(c, "save_adv_spells"):
                if ab in v:
                    modes.add("adv")
                    why.append(e["name"])
        for e, v in self._fxs(c, "cond_save_adv"):
            if set(v) & set(conds or ()):
                modes.add("adv")
                why.append(e["name"])
        if label == "Turn Undead":                              # Turn Resistance, Turn Defiance
            for e, _v in self._fxs(c, "turn_resist"):
                modes.add("adv")
                why.append(e["name"])
        if spell and source is not None and self._feat(c, "mage_slayer") and self._within(c, source, 5) and source is not c:
            modes.add("adv")
            why.append("Mage Slayer")
        self._wonder_save_modes(c, label, source, modes, why)  # Dragon Scale Mail against a dragon's breath (wondrous.py)
        self._subd_save_modes(c, source, spell, modes, why)    # Magical Ambush, Hound of Ill Omen (subfeats_d.py)
        self._nf_save_modes(c, source, spell, label, modes, why)    # Storm's Strength, Incessant Watchers (newfeats.py)
        mode = K.combine(modes)
        mode = self._subc_mode(c, mode, why)                    # Drunkard's Luck (subfeats_c.py)
        bonus = self._save_bonus(c, ab)
        if ab == "dex" and self._feat(c, "shield_master") and self._sheet(c) and self._sheet(c).equipped_shield():
            bonus += 2
        if ab in ("str", "con"):
            bonus += sum(int(v) for _e, v in self._fxs(c, "frost_rune"))     # a rune knight's Frost Rune
        bonus += sum(int(v[ab]) for _e, v in self._fxs(c, "save_ab") if ab in v)     # a froghemoth's -2 on Dexterity saves
        chips = []                                              # what effects add, for the d20 on screen
        extra, note = self._mod_roll(c, "save", chips)
        if spell:
            e2, n2 = self._mod_roll(c, "save_spells", chips)
            extra, note = extra + e2, note + n2
        aura = self._aura_bonus(c)
        if aura:
            extra += aura
            note += f" (+{aura} aura)"
            chips.append(["Aura of Protection", aura])
        if cover and ab == "dex" and cover < V.TOTAL:
            extra += cover
            note += f" (+{cover} cover)"
        sd = self._subb_save_extra(c, source)                   # Supernatural Defense (subfeats_b.py)
        if sd:
            extra += sd[0]
            note += sd[1]
            chips.append(sd[2])
        countered = bool(c.pop("counter_ok", False))            # Slayer's Counter hit: the save succeeds
        total, kept, dice = self._d20_roll(c, bonus, mode)
        total += extra
        ok = total >= dc or countered
        if countered and total < dc:
            note += " (Slayer's Counter)"
        self._use_once(c, "save", None, not ok)
        self._use_once(c, "save_dis")
        rr = self._fxs(c, "reroll_save")
        per_day = re.search(r"(\d+)/Day", rr[0][0]["name"], re.I) if rr else None
        if not ok and rr and (not per_day or (c.get("rerolls_used") or 0) < int(per_day.group(1))):
            c["rerolls_used"] = (c.get("rerolls_used") or 0) + 1   # Indomitable: the failed save rolled again, the new roll stands
            total, kept, dice = self._d20_roll(c, bonus, mode)
            total += extra
            ok = total >= dc
            note += f" → rerolled ({rr[0][0]['name']})"
        if not ok:
            lr = [e for e, v in self._fxs(c, "legendary_resistance")]
            if lr:
                n = lr[0]["mods"]["legendary_resistance"]
                if (c.get("lr_used") or 0) < n and self._react_mode(c, "legendary_resistance") != "never":
                    c["lr_used"] = (c.get("lr_used") or 0) + 1
                    ok = True
                    note += f" → Legendary Resistance ({n - c['lr_used']} left)"
                    self._vfx("lres", id=c["id"], left=n - c["lr_used"])   # a gold shield bursts out of it and shatters
        self._roll_line(c, "🛡️", f"{ab.upper()} save" + (f" vs {label}" if label else ""), total,
                       f"d20 {kept}{' ' + mode if mode else ''} {bonus:+d}{note} vs DC {dc} — {'success' if ok else 'failed'}")
        return {"total": total, "kept": kept, "dice": dice, "ok": ok, "auto": False, "note": note, "mode": mode, "dc": dc, "bonus": bonus,
                "why": list(dict.fromkeys(why)), "chips": chips}

    OATH_AURAS = {"Oath of Devotion": "devotion", "Oath of the Ancients": "warding"}

    def _oath_auras(self, c: dict) -> set:
        """The 7th-level paladin auras that reach this creature from a conscious paladin on its side within 10 ft (30 ft at
        18th): Devotion (can't be charmed), Warding (resistance to spell damage)."""
        out = set()
        for o in self.b["combatants"]:
            if o.get("kind") != "pc" or self._hostile(o, c) or not self._can_act(o):
                continue
            char = self._sheet(o)
            lv = char.class_level("Paladin") if char else 0
            kind = self.OATH_AURAS.get((char.class_entry("Paladin") or {}).get("subclass")) if lv >= 7 else None
            if kind and self._within(o, c, 30 if lv >= 18 else 10):
                out.add(kind)
            if lv >= 10 and self._within(o, c, 30 if lv >= 18 else 10):
                out.add("courage")                          # Aura of Courage: allies near can't be frightened
        return out

    def _aura_bonus(self, c: dict) -> int:
        """Aura of Protection: + the paladin's Charisma modifier (min 1) to saves of allies within 10 ft (30 at 18th)."""
        best = 0
        for o in self.b["combatants"]:
            if o.get("kind") != "pc" or self._hostile(o, c) or not self._can_act(o):
                continue
            char = self._sheet(o)
            if not char or not char.has_feature("Aura of Protection") or o is c:
                continue
            reach = 30 if char.class_level("Paladin") >= 18 else 10
            if self._within(o, c, reach):
                best = max(best, max(1, char.mod("cha")))
        return best

    # ------------------------------------------------------------------ damage
    def _roll_parts(self, parts, crit: bool = False) -> List[list]:
        out = []
        for d, t in parts:
            expr = E.double_dice(str(d)) if crit and not isinstance(d, int) and "d" in str(d) else d
            n = roll(expr)
            t = (t or "").lower()
            if "/" in t:                                         # "radiant/necrotic": the first on an even roll, the second on an odd one
                even, odd = t.split("/", 1)
                t = even if n % 2 == 0 else odd
            out.append([n, t])
        return out

    def _deal_rolled(self, tgt: dict, amounts, *, by: Optional[dict] = None, label: str = "", crit: bool = False,
                     factor: float = 1.0, magical: bool = True, spell: bool = False, silvered: bool = False, ignore_resist=()) -> str:
        """Hurt the target with already rolled [[amount, type], ...]: resistances, temporary HP, concentration, 0 HP.
        `ignore_resist`: types whose resistance doesn't count (a Vorpal Sword's slashing)."""
        amounts = self._damage_transfer(tgt, amounts, by, label)     # a rug of smothering shares it with whom it holds (standard.py)
        d = self._defenses(tgt)
        if ignore_resist:
            d = dict(d, resist=set(d["resist"]) - set(ignore_resist), nonmagical_resist=set(d.get("nonmagical_resist", ())) - set(ignore_resist))
            if "immune" in ignore_resist:                       # a Sword of Answering's riposte: immunity doesn't count either
                d = dict(d, immune=set(d["immune"]) - set(ignore_resist), nonmagical_immune=set())
        if spell and "warding" in self._oath_auras(tgt):        # Aura of Warding: resistance to damage from spells
            d = dict(d, resist=set(d["resist"]) | {t for _a, t in amounts if t})
        if by is not None:
            ea = self._feat(by, "elemental_adept")
            if spell and isinstance(ea, str):
                d = dict(d, resist=set(d["resist"]) - {ea})
            if self._feat(by, "poisoner"):
                d = dict(d, resist=set(d["resist"]) - {"poison"})
            if self._subc_pierce(by, spell, label):             # Inescapable Destruction (subfeats_c.py)
                d = dict(d, resist=set(d["resist"]) - {"necrotic"})
            pierced = self._nf_pierce(by, spell, label)         # Searing Spellfire, Touch of Death's Chill Touch (newfeats.py)
            if pierced:
                d = dict(d, resist=set(d["resist"]) - pierced)
        d = self._subd_defense(tgt, by, d, amounts, label)       # Emissary of Redemption (subfeats_d.py)
        if spell and self._wonder_immune_spell(tgt, label):      # a Brooch of Shielding against Magic Missile (wondrous.py)
            d = dict(d, immune=set(d["immune"]) | {t for _a, t in amounts if t})
        if not magical and self._feat(tgt, "heavy_armor_master") and (self._sheet(tgt).equipped_armor() or {}).get("type") == "HA":
            cut = 3
            fixed = []
            for amount, dtype in amounts:
                if dtype in ("bludgeoning", "piercing", "slashing") and cut:
                    take = min(cut, amount)
                    amount, cut = amount - take, cut - take
                fixed.append([amount, dtype])
            if cut < 3:
                bits_note = f"Heavy Armor Master -{3 - cut}"
                self._say(f"{tgt['name']}: {bits_note}")
            amounts = fixed
        oil = next((e for e, _v in self._fxs(tgt, "oil") if any(t == "fire" and a > 0 for a, t in amounts)), None)
        if oil is not None and oil in (tgt.get("effects") or []):
            amounts = list(amounts) + [[int(oil["mods"]["oil"]), "fire"]]    # the oil catches fire
            self._effect_off(tgt, oil, "the oil burns")
        if any(z.get("silence") for z in self._zones_at(tgt)):
            d = dict(d, immune=set(d["immune"]) | {"thunder"})  # inside Silence (or Dark Star): no thunder damage
        for e, (dice, btype) in self._fxs(tgt, "elemental_bane"):     # no resistance to the type, +2d6 the first time each turn
            d = dict(d, resist=set(d["resist"]) - {btype})
            now = f"{self.b.get('round')}:{self.b.get('turn')}"
            if e.get("bane_turn") != now and any(t == btype and a > 0 for a, t in amounts):
                e["bane_turn"] = now
                amounts = list(amounts) + [[roll(dice), btype]]
        total, bits = 0, []
        absorb = {k: v for _e, a in self._fxs(tgt, "absorb") for k, v in a.items()}     # a flesh golem's Lightning Absorption
        for amount, dtype in amounts:
            if dtype in absorb and amount > 0:
                back = int(int(amount * factor) * absorb[dtype])
                self._heal(tgt, back)
                bits.append(f"0 {dtype} (absorbed: +{back} HP)")
                continue
            mult, note = M.multiplier(dtype, d, magical=magical, spell=spell, silvered=silvered)
            n = int(int(amount * factor) * mult)
            total += max(0, n)
            bits.append(f"{n} {dtype}".strip() + (f" ({note})" if note else ""))
        ward = tgt.get("ward")
        if ward and ward.get("hp", 0) > 0 and total > 0:    # an abjurer's Arcane Ward takes the damage first
            soak = min(total, ward["hp"])
            ward["hp"] -= soak
            total -= soak
            bits.append(f"Arcane Ward absorbs {soak} ({ward['hp']} left)")
        form = tgt.get("form")
        taken = total                                       # what the creature took, beast shape or not (concentration)
        if form and total > 0 and not form.get("keeps_hp"):      # (a monster's Change Shape keeps its own hit points)
            soak = min(total, form["hp"])
            form["hp"] -= soak
            bits.append(f"{form['name']} form absorbs {soak}")
            total -= soak
            if form["hp"] <= 0:
                tgt.pop("form", None)
                self._say(f"{tgt['name']} drops out of its {form['name'].lower()} form")
                caster = self._find_or_none(form.get("conc_by"))
                if caster is not None and caster.get("concentrating"):     # Polymorph ends with the form
                    self._drop_conc(caster, f"{tgt['name']}'s new form dropped")
        if total > 0 and any(t == "fire" and a > 0 for a, t in amounts):
            self._burn_webs(tgt)
        main = max(amounts, key=lambda p: p[0])[1] if amounts else ""
        hit_types = {t for a, t in amounts if a > 0}
        for e, types in self._fxs(tgt, "resist"):                # Rage, Stoneskin...: the effect that halved it blinks
            types = set(types) if isinstance(types, (list, tuple, set)) else {types}
            if hit_types & types & set(d["resist"]):
                self._vfx("tell", id=tgt["id"], name=e["name"], half=True)
        self._vfx("dmg", id=tgt["id"], amt=total, dtype=main or "", crit=bool(crit))
        before = self._hp_of(tgt)
        fate = ""
        if tgt["kind"] == "pc":
            char = self._sheet(tgt)
            if char and before <= 0 and total > 0 and not self._dead(tgt):
                ds = char.d["death_saves"]
                ds["success"] = 0                                   # a stable creature that takes damage is dying again
                if total >= char.max_hp:
                    ds["failure"] = 3
                else:
                    ds["failure"] = min(3, ds["failure"] + (2 if crit else 1))
                char.save()
                self._vfx("dsave", id=tgt["id"], s=0, f=ds["failure"], hit=True)   # hurt while dying: red pips fill
                fate = " - dies" if ds["failure"] >= 3 else f" - death save failed ({ds['failure']}/3)"
            elif char and before > 0 and total - min(total, char.temp_hp) - before >= char.max_hp:
                char.d["death_saves"] = {"success": 0, "failure": 3}      # massive damage: what's left over is its hit point maximum
                char.save()
                fate = " - killed outright (massive damage)"
            self.chars.damage(tgt["character"], str(total)) if total > 0 else None
        else:
            self._lose_hp(tgt, total)
        after = self._hp_of(tgt)
        if before > 0 and after <= 0 and (self._undead_fortitude(tgt, total, [t for _a, t in amounts], crit)
                                          or self._trait_zero_hp(tgt, total)
                                          or self._class_zero_hp(tgt, total, [t for _a, t in amounts], crit)):    # Relentless Rage
            after = self._hp_of(tgt)
        if before > 0 and after <= 0:
            self._zero_hp(tgt, by)
            after = self._hp_of(tgt)
        if tgt["kind"] == "pc":
            char = self._sheet(tgt)
            left = (f"{char.current_hp}/{char.max_hp} HP" if char else "") + fate
        else:
            left = "defeated" if tgt["hp"] <= 0 else f"{tgt['hp']}/{tgt['max_hp']} HP"
        text = " + ".join(bits) or "0"
        self._short = text + f" → {left}"
        self._roll_line(by, "💥", f"{label} damage → {tgt['name']}{' (critical)' if crit else ''}", total, f"{text} → {left}")
        self._stat_split(tgt, hit_types)                        # an ochre jelly's Split, even when immune (standard.py)
        self._subb_dealt(tgt, by, hit_types, total)             # Thunderbolt Strike (subfeats_b.py)
        self._subc_dealt(tgt, by, hit_types, total)             # Rage beyond Death (subfeats_c.py)
        self._subd_dealt(tgt, by, hit_types, total, label, spell)    # Emissary of Redemption (subfeats_d.py)
        self._race_dealt(tgt, by, total, label)                 # a dhampir's Vampiric Bite drinks (racefeats.py)
        if taken > 0:
            tgt.setdefault("took_types", [])
            tgt["took_types"] = sorted(set(tgt["took_types"]) | {t for _a, t in amounts if t})
            self._trait_hurt(tgt, hit_types, taken)             # Aversion to Fire; Seven Radiances (traits.py)
            self._conc_check(tgt, taken, by)
            for e, _v in self._fxs(tgt, "temp_gone"):           # Sylune's Viper, an empowered familiar: the spell ends with its temporary hit points
                left = self._sheet(tgt).temp_hp if self._sheet(tgt) else int(tgt.get("temp_hp") or 0)
                if left <= 0 and e in (tgt.get("effects") or []):
                    self._effect_off(tgt, e, "no temporary hit points left")
            for e in [e for e, v in self._fxs(tgt, "ends_on") if "damage" in (v or []) or hit_types & set(v or [])]:     # Ice Form: fire melts it
                if e in (tgt.get("effects") or []):
                    self._effect_off(tgt, e, "took damage")
            for e in [e for e, v in self._fxs(tgt, "ends_on_by") if by is not None and v == by.get("id")]:
                if e in (tgt.get("effects") or []):                 # Sir Godfrey's glare: until the knight deals damage to it
                    self._effect_off(tgt, e, "took damage from the one who cast it")
            for e in [e for e in tgt.get("effects") or [] if e.get("ability") and self._hp_of(tgt) > 0
                      and (e.get("repeat") == "damage" or (e.get("mods") or {}).get("save_on_damage"))]:
                res = self._saving_throw(tgt, e["ability"], int(e.get("dc") or 10), spell=True, label=e["name"],   # Enemies Abound,
                                         adv="hurt" if (e.get("mods") or {}).get("save_on_damage") else False)     # Hideous Laughter
                self._say(f"{tgt['name']} {e['ability'].upper()} save against {e['name']} (hurt): {res['total']} vs DC {e.get('dc')} — "
                          + ("success" if res["ok"] else "failed"))
                if res["ok"]:
                    self._effect_off(tgt, e, "saved")
            for e, _v in self._fxs(tgt, "bond"):                 # Warding Bond: its caster takes the same damage
                warden = self._find_or_none(e.get("source_id"))
                if warden is not None and warden is not tgt and self._hp_of(warden) > 0 and label != "Warding Bond":
                    self._say("Warding Bond: " + self._deal_rolled(warden, [[taken, ""]], label="Warding Bond"))
            for e, v in self._fxs(tgt, "tether"):                # Tether Essence: the linked creature takes the same damage
                other = self._find_or_none(v)
                if other is not None and other is not tgt and self._hp_of(other) > 0 and label != "Tether Essence":
                    self._say("Tether Essence: " + self._deal_rolled(other, [[taken, ""]], label="Tether Essence"))
        return f"{tgt['name']} takes {text}" + (" (critical)" if crit else "") + f" → {left}"

    def _undead_fortitude(self, c: dict, dealt: int, types, crit: bool) -> bool:
        """A zombie dropped to 0 by anything but radiant damage or a critical hit: CON save (DC 5 + the damage) to stay at 1 HP."""
        if c["kind"] == "pc" or crit or "radiant" in types:
            return False
        if not any(t.get("name") == "Undead Fortitude" for t in (self._monster(c) or {}).get("traits") or []):
            return False
        res = self._saving_throw(c, "con", 5 + dealt, label="Undead Fortitude")
        self._say(f"{c['name']} Undead Fortitude: CON save d20 {res['kept']} = {res['total']} vs DC {5 + dealt} — "
                  + ("drops to 1 HP instead" if res["ok"] else "failed"))
        if res["ok"]:
            self._set_hp(c, 1)
        return res["ok"]

    def _death_burst(self, c: dict):
        """Death Burst (magmin, mephits): exploding when it dies - a save for everyone around it."""
        tr = next((t for t in (self._monster(c) or {}).get("traits") or [] if t.get("name", "").startswith(("Death Burst", "Death Throes"))
                   or re.match(r"When [\w' -]*?(?:dies|is reduced to 0 hit points|drops to 0 hit points), "
                               r"(?=[^.]*(?:explod|burst|crumbl|pops|releases|overload))",     # a statue's Crumbling Colossus, a clown's pop
                               t.get("text") or "")
                   or re.match(r"The [\w' -]+? (?:bursts|explodes|erupts) when it (?:dies|drops to 0 hit points|is reduced to 0 hit points)", t.get("text") or "")), None)
        if not tr or not c.get("pos"):
            return
        text = tr.get("text") or ""
        _pre, post, sv = CR.split_save(text)
        r = re.search(r"within (\d+) feet", text) or re.search(r"(\d+)-foot-radius sphere centered on (?:itself|its space)", text)
        if not sv or not r:
            return
        near = [o["id"] for o in self.b["combatants"] if o is not c and o.get("pos") and not self._is_out(o) and self._dist(o, c) <= int(r.group(1))]
        if not near:
            self._say(f"{c['name']}: {tr['name']} - nobody close enough")
            return
        S = self._strike(c, tr["name"], near, mode="save", sv={"ab": sv[0], "dc": sv[1], "half": "half as much" in post.lower(),
                                                              "conds": CR.conditions_in(post), "rounds": CR.duration_rounds(post),
                                                              "until": CR.until_of(post)},
                         parts=CR.damage_parts(post))
        if self._stack():
            self._stack().append(S)                       # inside an action: it goes off next
        else:
            self._run_r(S)

    def _zero_hp(self, c: dict, by: Optional[dict]):
        """Dropping to 0: Death Ward, Relentless Endurance / Rage, then unconscious (PC) or defeated."""
        for e, _v in self._fxs(c, "death_ward"):
            if e in (c.get("effects") or []):
                self._set_hp(c, 1)
                self._effect_off(c, e, "Death Ward")
                self._say(f"{c['name']} drops to 1 hit point instead (Death Ward)")
                return
        if self._duel_zero(c):                                  # Dueling Ground: stable, whisked out (spells.py)
            return
        if self._wonder_zero_hp(c):                             # a Lifewell Tattoo, once a day (wondrous.py)
            return
        char = self._sheet(c)
        if char and char.has_feature("Relentless Endurance") and not char.d["resources"].get("feature:Relentless Endurance"):
            char.d["resources"]["feature:Relentless Endurance"] = 1
            char.save()
            self._set_hp(c, 1)
            self._vfx("feature", id=c["id"], key="relentless_endurance", name="Relentless Endurance")   # it refuses to fall
            self._say(f"{c['name']} refuses to fall: 1 hit point (Relentless Endurance)")
            return
        self._vfx("down", id=c["id"], pc=c["kind"] == "pc", type=str((self._monster(c) or {}).get("type") or "").lower(),
                  summoned=c.get("summoned_by") is not None)   # how it falls depends on what it is
        if c.get("concentrating"):
            self._drop_conc(c, "knocked out")
        for e in list(c.get("effects") or []):
            if e.get("mods", {}).get("rage") and not self._subc_keeps_rage(c):      # Rage beyond Death (subfeats_c.py)
                self._effect_off(c, e, "unconscious")
        self._trait_kill(by, c)                                 # Rampage, Imix's Blessing
        self._class_kill(by, c)                                 # Dark One's Blessing, Hexblade's Curse
        self._death_triggers(c, by)                             # Feed on Death, Grim Harvest, Vengeful Strike (standard.py)
        self._lantern_souls(c)                                  # Spirit Lantern (spells.py)
        self._bomb_burst(c)                                     # Walking Bomb (spells.py)
        if c["kind"] != "pc":
            self._raise("zero_hp", creature=c, by=by)

    def _exhaust(self, c: dict, n: int):
        if self._fx(c, "no_exhaust"):                          # Iron Body: its exhaustion can't increase
            return
        char = self._sheet(c)
        if char:
            char.d["exhaustion"] = min(6, int(char.d.get("exhaustion") or 0) + n)
            char.save()
        else:
            c["exhaustion"] = min(6, int(c.get("exhaustion") or 0) + n)
        self._say(f"{c['name']} gains a level of exhaustion")

    def _set_hp(self, c: dict, hp: int):
        if c["kind"] == "pc":
            char = self._sheet(c)
            if char:
                char.current_hp = hp
                if hp > 0 and "Unconscious" in char.d["conditions"]:
                    char.d["conditions"].remove("Unconscious")
                char.save()
        else:
            c["hp"] = hp

    # ------------------------------------------------------------------ strike: attacks, saves and automatic damage
    def _strike(self, actor: Optional[dict], label: str, targets: List[int], *, mode: str, atk: Optional[dict] = None,
                sv: Optional[dict] = None, parts=(), rider: Optional[dict] = None, on_hit: Optional[dict] = None,
                magical: bool = True, spell: bool = False, per_target: Optional[dict] = None, conc: Optional[int] = None,
                summary_targets: Optional[str] = None, origin: Optional[list] = None, follow=None) -> dict:
        """A strike record. mode 'attack' (atk: bonus, n, melee, weapon, parts...), 'save' (sv: ab, dc, half, conds...,
        damage `parts` rolled once for everyone) or 'auto' (`parts` dealt, `per_target` {id: parts} for split darts)."""
        R = self._new_r("strike", actor, label, targets=list(targets), ti=0, mode=mode, atk=atk or {}, sv=sv or {},
                        parts=[list(p) for p in parts], rider=rider, on_hit=on_hit, magical=magical, spell=spell,
                        per_target={str(k): v for k, v in (per_target or {}).items()}, conc=conc, origin=origin,
                        follow=list(follow or []), cur={}, hits={})
        if summary_targets is not None:
            R["summary_targets"] = summary_targets
        return R

    def _step_strike(self, R: dict) -> str:
        st = R["stage"]
        att = self._find_or_none(R["actor"])
        if st == "start":
            if not R["targets"] and R.get("spell"):                # an area that caught nobody still says the spell was cast
                line = f"{att['name'] if att else '?'} casts {R['label']}: nobody in the area"
                self._line(R, line, "nobody in the area")
            if R["targets"]:
                self._class_strike_start(R, att)                    # Elemental Affinity, Radiant Soul: + Charisma to the damage
                self._wonder_strike_start(R, att)                   # an imbued wood focus: +1 to one damage roll of its type
            if R["mode"] in ("save", "auto") and R["parts"] and not R.get("rolled"):
                R["rolled"] = self._roll_parts(R["parts"])
                if R.get("empowered"):
                    again = self._roll_parts(R["parts"])
                    if sum(n for n, _t in again) > sum(n for n, _t in R["rolled"]):
                        R["rolled"] = again
                R["rolled"] = self._subd_rolled(R, att, R["rolled"])     # Spell Bombardment, Power Surge (subfeats_d.py)
                if att is not None and R.get("spell"):
                    R["rolled"] = self._nf_damage(R, att, None, R["rolled"], R.get("parts") or [])     # Perfect Poisoner (newfeats.py)
                R["rolled"] = self._spell_maximize(R, att, R["rolled"])  # a Potion of Maximum Power (spellitems.py)
            R["stage"] = "target"
            return NEXT
        if st == "target":
            if R["ti"] >= len(R["targets"]):
                R["stage"] = "finish"
                return NEXT
            tgt = self._find_or_none(R["targets"][R["ti"]])
            if not tgt or (R["mode"] == "attack" and not self._alive(tgt) and (tgt["kind"] != "pc" or self._dead(tgt))):
                if tgt and self._dead(tgt):
                    self._line(R, f"{tgt['name']} is dead", "dead")
                R["ti"] += 1
                return NEXT
            R["cur"] = {"aj": 0}
            if att is not None and tgt is not att and self._hostile(att, tgt):
                why = self._may_target(att, tgt, R)
                if why:
                    self._line(R, why, why)
                    R["ti"] += 1
                    return NEXT
            R["stage"] = {"attack": "declare_win", "save": "save", "auto": "auto"}[R["mode"]]   # an attack: reactions before the roll first
            return NEXT
        tgt = self._find_or_none(R["targets"][R["ti"]]) if R["ti"] < len(R["targets"]) else None
        cur = R["cur"]
        a = R["atk"]
        if tgt is None and st not in ("attack", "next_attack", "next_target", "finish", "done"):
            R["stage"] = "next_target"                          # the target left the battle mid-strike (a summon sent away)
            return NEXT
        if st == "attack":
            if att is None or tgt is None:
                R["stage"] = "next_target"
                return NEXT
            image = self._mirror_image(att, tgt, a)
            if image:
                self._line(R, image, "duplicate")
                R["stage"] = "next_attack"
                return NEXT
            res = self._attack_check(att, tgt, a)
            cur.update(res)
            cur["ac_extra"] = cur.get("ac_extra", 0) + self._wonder_ac(tgt, a, att)     # kept when a reaction makes it look again
            tag = f" (attack {cur['aj'] + 1})" if a.get("n", 1) > 1 else ""
            cur["tag"] = tag
            R["stage"] = "hit_win" if res["hit"] else "missed_win"
            if self._dice(R, att, f"{R['label']}{tag} → {tgt['name']}", res, f"AC {res['ac']}",
                          "crit" if res["crit"] else "hit" if res["hit"] else "miss"):
                return WAIT
            return NEXT
        if st == "declare_win":                                  # Protection, Redirect Attack, Instinctive Charm (reactions.py)
            if att is None or tgt is None:
                R["stage"] = "attack"
                return NEXT
            return self._window(R, "declared", "attack", attacker=R["actor"], target=tgt["id"])
        if st == "missed_win":
            return self._window(R, "missed", "miss_check", attacker=R["actor"], target=tgt["id"])
        if st == "miss_check":
            ac = self._ac_of(tgt) + (cur.get("cover") if cur.get("cover", 0) < V.TOTAL else 0) + cur.get("ac_extra", 0)
            if cur.get("kept") != 1 and cur["total"] >= ac and cur.get("cover", 0) < V.TOTAL:
                cur["hit"] = True
                cur["ac"] = ac
                R["stage"] = "hit_win"
            else:
                R["stage"] = "miss"
            return NEXT
        if st == "hit_win":
            return self._window(R, "hit", "hit_check", attacker=R["actor"], target=tgt["id"])
        if st == "hit_check":
            if not cur.get("crit") and cur.get("kept") != 20:
                ac = self._ac_of(tgt) + (cur.get("cover") if cur.get("cover", 0) < V.TOTAL else 0) + cur.get("ac_extra", 0)
                if cur["total"] < ac or cur.get("kept") == 1:      # (a roll turned into a 1, Moment of Prescience, misses whatever the bonus)
                    cur["ac"] = ac
                    cur["hit"] = False
                    cur["saved_by"] = cur.get("saved_by") or "the reaction"
                    R["stage"] = "miss"
                    return NEXT
            R["stage"] = "attacker_win"
            self._log_attack(R, att, tgt)
            return NEXT
        if st == "miss":
            self._log_attack(R, att, tgt)
            skulk = self._feat(att, "skulker") and not a.get("melee")
            for e, v in self._fxs(att, "ends_on"):
                if "attack" in (v or []) and e in (att.get("effects") or []) and not (skulk and e["name"] == "Hidden"):
                    self._effect_off(att, e, "attacked")
            R["stage"] = "next_attack"
            return NEXT
        if st == "attacker_win":
            return self._window(R, "on_hit", "roll_damage", attacker=R["actor"], target=tgt["id"])
        if st == "roll_damage":
            parts = [list(p) for p in a.get("parts") or []]
            tells = []                                           # (part, who carries the effect, its name): its badge blinks
            if att is not None and parts:
                for e, (dice, dtype) in self._fxs(att, "dmg"):
                    if a.get("weapon") or e.get("mods", {}).get("any_attack"):
                        if e.get("mods", {}).get("melee_only") and not a.get("melee"):
                            continue
                        if e.get("mods", {}).get("ranged_only") and a.get("melee"):
                            continue
                        if e.get("mods", {}).get("unarmed_only") and "unarmed" not in (a.get("props") or []):
                            continue                                # Wyrmreaver Gauntlets: fists only
                        if str(dice) not in ("0", ""):
                            parts.append([dice, dtype or parts[0][1]])
                        if e.get("mods", {}).get("rider"):
                            R.setdefault("smite_riders", []).append({"rider": e["mods"]["rider"], "name": e["name"], "target": tgt["id"],
                                                                     "dc": e.get("dc") or self._spell_dc(att)})
                        if e.get("mods", {}).get("once") and e in (att.get("effects") or []):
                            self._effect_off(att, e, "used")
                for e, (dice, dtype) in self._fxs(tgt, "extra_damage"):
                    if e.get("source_id") == att["id"] and (a.get("weapon") or not e["mods"].get("weapon_only")) \
                            and (not e["mods"].get("once_turn") or self._once_per_turn(att, "prey:" + e["name"])):    # Hunter's Mark: weapons; Kivan's Mark: once a turn
                        parts.append([dice, dtype or parts[0][1]])
                        tells.append((len(parts) - 1, tgt["id"], e["name"]))     # Hex, Hunter's Mark: the mark on the target
                if a.get("weapon") and a.get("melee") and a.get("str_based"):
                    for e, v in self._fxs(att, "rage_damage"):
                        parts.append([int(v), parts[0][1]])
                        tells.append((len(parts) - 1, att["id"], e["name"]))
                parts += self._sneak_attack(att, tgt, R)
                parts += self._divine_strike(att, R)
                parts += self._trait_hit_parts(att, tgt, R)       # Martial Advantage, a charge...
                parts += self._item_hit_parts(att, tgt, R)        # Frost Brand, Dragon Slayer...
                parts += self._class_hit_parts(att, tgt, R)       # Colossus Slayer, Divine Fury, Hexblade's Curse...
            parts += [list(p) for p in cur.get("bonus_parts") or []]
            if cur.get("mode") == "adv":                         # "if it had advantage on the attack roll" (a skulk, a darkling)
                parts += [list(p) for p in a.get("adv_parts") or []]
            if not cur.get("crit"):                              # "If the attack hits, but is not a critical hit, ... an extra 27 (6d8)"
                parts += [list(p) for p in a.get("noncrit_parts") or []]
            rolled = self._roll_parts(parts, cur.get("crit"))
            if att is not None:
                rolled = self._feat_damage(R, att, tgt, rolled, parts)
                rolled = self._class_damage(R, att, tgt, rolled, parts)     # Great Weapon Fighting
            if R.get("empowered"):
                again = self._roll_parts(parts, cur.get("crit"))
                if sum(n for n, _t in again) > sum(n for n, _t in rolled):
                    rolled = again
            if cur.get("crit") and att is not None and a.get("weapon") and a.get("melee"):
                extra = self._crit_extra(att, a)
                if extra:
                    rolled.append([roll(extra), parts[0][1] if parts else ""])
            if cur.get("crit") and a.get("crit_bonus"):          # Blade of Disaster: 12d12 in all on a crit
                rolled += self._roll_parts(a["crit_bonus"])
            if att is not None and a.get("weapon") and a.get("str_based", a.get("melee")) and self._fx(att, "enfeebled"):
                rolled = [[n // 2, t] for n, t in rolled]       # Ray of Enfeeblement: half damage with Strength weapons
            for _e, v in self._fxs(att, "dmg_minus") if att is not None and a.get("weapon") and rolled else []:
                rolled[0] = [max(1, rolled[0][0] - roll(v)), rolled[0][1]]     # reduced: its weapons hit for 1d4 less (at least 1)
            for p in rolled:
                if p[0] < 0:
                    p[0] = 0
            cur["dmg"] = rolled
            cur["tells"] = [[who, name, rolled[i][0]] for i, who, name in tells if i < len(rolled)]
            R["stage"] = "apply_damage" if self._hit_ward(R, tgt) else "damage_win"     # Quen takes the whole hit (spells.py)
            return NEXT
        if st == "damage_win":
            return self._window(R, "damage", "apply_damage", attacker=R["actor"], target=tgt["id"])
        if st == "apply_damage":
            if cur.get("dmg"):
                hp0 = self._hp_of(tgt)
                for who, name, n in cur.get("tells") or []:
                    self._vfx("tell", id=who, name=name, amt=n)
                line = self._deal_rolled(tgt, cur["dmg"], by=att, label=R["label"], crit=cur.get("crit", False),
                                         factor=cur.get("factor", a.get("factor", 1.0)), magical=R.get("magical", True) or a.get("magical", False),
                                         spell=R.get("spell", False), ignore_resist=R.get("ignore_resist") or ())
                R.setdefault("dealt", {})[str(tgt["id"])] = R.get("dealt", {}).get(str(tgt["id"]), 0) + max(0, hp0 - self._hp_of(tgt))
                if R.get("zone"):
                    z = next((x for x in self.b.get("zones") or [] if x["id"] == R["zone"]), None)
                    if z is not None:
                        z["dealt"] = z.get("dealt", 0) + max(0, hp0 - self._hp_of(tgt))
                self._line(R, line, self._short)
                if R.get("spell") and att is not None:
                    self._spell_after_damage(R, att, tgt)       # a Fulminating Treatise's reaction (spellitems.py)
                if R["mode"] == "attack":
                    self._after_hit(R, att, tgt)
                    if att is not None:
                        self._feat_after_hit(R, att, tgt)
                        self._item_after_hit(R, att, tgt)
            if R["mode"] == "attack":
                R["hits"][str(tgt["id"])] = True
                R["stage"] = "rider" if R.get("rider") or R.get("on_hit") else "next_attack"
            elif R["mode"] == "save":
                R["stage"] = "save_effects"
            else:
                R["stage"] = "next_target"
            return NEXT
        if st == "rider" or (st == "next_attack" and R.get("smite_riders")):
            for sr in R.pop("smite_riders", None) or []:
                self._smite_rider(R, att, self._find_or_none(sr["target"]), sr)
            if st == "next_attack":
                return NEXT
        if st == "rider":
            if R.get("on_hit") and (not R["on_hit"].get("need_adv") or cur.get("mode") == "adv") \
                    and (not R["on_hit"].get("once") or att is None or self._once_per_turn(att, R["on_hit"]["once"])):   # a darkmantle: only with advantage; Strongheart's gleam: once a turn
                oh = R["on_hit"]
                self._effect_on(tgt, oh.get("name") or R["label"], oh.get("conds") or [], oh.get("repeat_ab"), oh.get("dc"),
                                "end" if oh.get("repeat_ab") else None, oh.get("rounds"),
                                att["name"] if att else "", oh.get("mods"), R.get("conc"), att["id"] if att else None,
                                until=oh.get("until"))
                if oh.get("note"):
                    self._line(R, f"{tgt['name']}: {oh['note']}", oh["note"])
            rd = R.get("rider")
            grab = (rd or {}).get("grab") or ((rd or {}).get("conds") if rd and not rd.get("ab") else None)
            if grab:
                held = "Grappled" in grab and att is not None
                had = {id(e) for e in tgt.get("effects") or []}      # a grapple renewed by a second hit replaces the first: the new one counts
                plain = not rd.get("ab")
                self._effect_on(tgt, R["label"] + ("" if plain else " (held)"), grab, None, None, rd.get("repeat") if plain else None,
                                rd.get("rounds") if plain else None, att["name"] if att else "",
                                {"grappler": att["id"]} if held else {"held": True} if rd.get("escape") else None,   # a net: no grappler, still a DC
                                R.get("conc"), att["id"] if att else None)
                if (held or rd.get("escape")) and tgt.get("effects") and id(tgt["effects"][-1]) not in had:
                    tgt["effects"][-1]["escape"] = rd.get("escape")    # the stat block's escape DC
                self._line(R, f"{tgt['name']} is now {', '.join(c.lower() for c in grab)}", "now " + ", ".join(c.lower() for c in grab))
            if rd and self._alive(tgt) and rd.get("ab") and (cur.get("crit") or not rd.get("crit_only")):     # the dullahan's head: only on a crit
                if rd.get("with_grapple") and att is not None:     # stunned until this grapple ends
                    rd = dict(rd, mods=dict(rd.get("mods") or {}, with_grapple=att["id"]))
                res = self._apply_save(R, att, tgt, rd, rolled=self._roll_parts(rd.get("parts") or []))
                R.setdefault("rider_failed", {})[str(tgt["id"])] = not res["ok"]    # a stat block's drain or swallow follows a failure
            R["stage"] = "next_attack"
            return NEXT
        if st == "next_attack":
            cur["aj"] = cur.get("aj", 0) + 1
            if R["mode"] == "attack" and cur["aj"] < int(a.get("n", 1)) and tgt and (self._alive(tgt) or tgt["kind"] == "pc"):
                keep = cur["aj"]
                R["cur"] = {"aj": keep}
                R["stage"] = "attack"
                return NEXT
            R["stage"] = "next_target"
            return NEXT
        if st == "next_target":
            R["ti"] += 1
            R["stage"] = "target"
            return NEXT
        if st == "save" and not cur.get("presave_done") and not R["sv"].get("no_save"):
            cur["presave_done"] = True                          # first, those who may react before the roll (a Kalaman soldier's Hold the Line)
            R["stage"] = "presave_win"
            return NEXT
        if st == "presave_win":
            return self._window(R, "before_save", "save", attacker=R["actor"], target=tgt["id"])
        if st == "save":
            sv = R["sv"]
            cov = self._cover_between(att, tgt) if att and sv.get("ab") == "dex" and R.get("origin") is None and not sv.get("no_cover") else 0    # Sacred Flame
            if sv.get("ab") == "dex" and not sv.get("no_cover") and self._fx(tgt, "half_cover"):
                cov = max(cov, V.HALF)                          # Fizban's Platinum Shield: cover wherever it stands
            if sv.get("no_save"):                               # Maze, Otto's Irresistible Dance: no save, it just happens
                res = {"total": 0, "kept": 0, "ok": False, "auto": True, "note": " (no save)", "mode": None, "dc": sv["dc"]}
            elif sv.get("auto_pass_types") and any(k in (str((self._monster(tgt) or {}).get("type") or "") + " "
                                                          + " ".join(map(str, (self._monster(tgt) or {}).get("tags") or []))).lower()
                                                   for k in sv["auto_pass_types"]):
                res = {"total": 99, "kept": 20, "ok": True, "auto": True, "note": " (automatic success)", "mode": None, "dc": sv["dc"]}    # Wardaway: constructs and undead
            else:
                adv = bool(sv.get("adv_hostile") and att is not None and self._hostile(att, tgt)) \
                    or ("dis" if any(k in (str((self._monster(tgt) or {}).get("type") or "") + " " + " ".join(map(str, (self._monster(tgt) or {}).get("tags") or []))).lower()
                                 for k in sv.get("dis_types") or ()) else False)
                if cur.get("presave_adv"):                      # granted by a reaction before the roll (adv and dis cancel)
                    adv = False if adv == "dis" else cur["presave_adv"]
                if cur.get("presave_dis"):                      # Precognitive Insight on a foe's save
                    adv = False if adv in (True, "adv") else "dis"
                if sv.get("force_dis"):                         # Detonate's blast when the target fell: disadvantage
                    adv = False if adv in (True, "adv") else "dis"
                res = self._saving_throw(tgt, sv["ab"], int(sv["dc"]), spell=R.get("spell", False), conds=sv.get("conds") or [],
                                         source=att, cover=cov, label=R["label"], adv=adv)     # Charm Person, Sunburst on undead
            cur.update(res)
            R["stage"] = "save_failed_win" if not res["ok"] and not sv.get("no_save") else "save_ok_win" if res["ok"] else "save_result"
            if not res.get("auto") and self._dice(R, tgt, f"{sv['ab'].upper()} save · {R['label']}", res, f"DC {sv['dc']}",
                                                  "saved" if res["ok"] else "failed"):
                return WAIT
            return NEXT
        if st == "save_failed_win":
            return self._window(R, "save_failed", "save_result", attacker=R["actor"], target=tgt["id"])
        if st == "save_ok_win":                                 # a save made: a Spindle of Fate's Twist of Fate may undo it
            return self._window(R, "save_ok", "save_result", attacker=R["actor"], target=tgt["id"])
        if st == "save_result":
            sv = R["sv"]
            res = {k: cur.get(k) for k in ("total", "kept", "ok", "auto", "note", "mode", "dc")}
            if R.get("careful") and att is not None and not self._hostile(att, tgt) and tgt is not att:
                res = dict(res, ok=True, note=res["note"] + " (Careful Spell)")
            sculpted = False
            if R.get("sculpt") and att is not None and not self._hostile(att, tgt) and R["sculpt"] > 0:
                R["sculpt"] -= 1                                 # Sculpt Spells: 1 + the spell's level creatures, no damage at all
                sculpted = True
                res = dict(res, ok=True, note=res["note"] + " (Sculpt Spells)")
            cur.update(res)
            R.setdefault("saved", {})[str(tgt["id"])] = res["ok"]
            if res["ok"] and R.get("spell") and att is not None and att is not tgt and len(R["targets"]) == 1:
                self._turn_spell(R, att, tgt)                    # Spell Turning / Spell Reflection: back at the caster (standard.py)
            self._vfx("save", id=tgt["id"], ok=bool(res["ok"]))
            if res["ok"] and sv.get("end_on_save"):
                for e in [e for e in tgt.get("effects") or [] if e["name"] == sv["end_on_save"]]:
                    self._effect_off(tgt, e, "saved")
            if not res["ok"] and R.get("exhaustion_on_fail"):
                self._exhaust(tgt, 1)
            factor = 1.0
            if res["ok"]:
                factor = .5 if sv.get("half") else 0.0
            if sv.get("drop_to_0"):                             # Banshee's Wail: the damage is for a success, a failure drops to 0
                factor = 1.0 if res["ok"] else 0.0
            if sv.get("full"):                                  # Feeblemind, Mental Prison: the damage comes either way
                factor = 1.0
            if sv.get("ab") == "dex" and self._fxs(tgt, "evasion") and not K.incapacitated(self._conds(tgt)) and sv.get("half"):
                factor = 0.0 if res["ok"] else .5
            elif res["ok"] and factor > 0 and sv.get("ab") == "dex" and sv.get("half") and self._shield_master_dodge(tgt):
                factor = 0.0                                    # Shield Master: the shield takes it (a reaction)
            elif res["ok"] and factor > 0 and sv.get("half") and R.get("magical", True) and any(sv.get("ab") in v for _e, v in self._fxs(tgt, "half_none")):
                factor = 0.0                                    # Mizzium armour: a Strength or Constitution save against magic takes none
            if sculpted:
                factor = 0.0
            cur["factor"] = factor
            rolled = R.get("rolled") or []
            cur["dmg"] = [list(p) for p in rolled] if factor > 0 else []
            keep = (R.get("spell_extra") or {}).get("min_hp")
            if keep and cur["dmg"] and tgt is not None:         # Harm: the damage can't take it below 1 hit point
                sheet = self._sheet(tgt)
                room = max(0, self._hp_of(tgt) + int(sheet.temp_hp if sheet else tgt.get("temp_hp") or 0) - int(keep))
                over = sum(int(n) for n, _t in cur["dmg"]) - int(room / factor)
                for p in reversed(cur["dmg"]):
                    if over <= 0:
                        break
                    cut = min(over, int(p[0]))
                    p[0] = int(p[0]) - cut
                    over -= cut
            if sv.get("no_save"):
                self._line(R, f"{tgt['name']} gets no save against {R['label']}", f"{tgt['name']}: no save")
            else:
                self._line(R, f"{tgt['name']} {sv['ab'].upper()} save vs {R['label']}: d20 {res['kept']}{self._save_mode_note(res)}{res['note']} = {res['total']} vs DC {sv['dc']} — "
                              + ("success" if res["ok"] else "failed"), f"{tgt['name']}: {sv['ab'].upper()} save {res['total']} vs DC {sv['dc']} — {'saved' if res['ok'] else 'failed'}")
            R["stage"] = "damage_win" if cur["dmg"] else "save_effects"
            return NEXT
        if st == "save_effects":
            if tgt is not None:                                 # a summon the damage just sent away is gone from the battle
                self._save_consequences(R, att, tgt)
            R["stage"] = "next_target"
            return NEXT
        if st == "auto":
            parts = R["per_target"].get(str(tgt["id"])) if R["per_target"] else None
            if parts is not None:
                cur["dmg"] = self._roll_parts(parts)
            else:
                cur["dmg"] = [list(p) for p in R.get("rolled") or []]
            R["stage"] = "damage_win"
            return NEXT
        if st == "finish":
            if R.get("echo_home") and att is not None:             # an attack from the Echo Knight's echo: back to its own space
                att["pos"] = R.pop("echo_home")
            if R["mode"] == "attack" and att is not None and not R.get("sentinel_done"):
                R["sentinel_done"] = True
                for item in self._eligible("attacked_other", R, attacker=att["id"]):
                    R.setdefault("follow", []).append(self._new_r("offer", self._find_or_none(item["reactor"]), "reaction", item=dict(item, window="attacked_other"),
                                                                  attacker=att["id"]))
            if R.get("spell_extra") and not R.get("extras_done"):
                R["extras_done"] = True
                self._spell_after_strike(R)
            if R.get("stat_extra") and not R.get("stat_done"):     # a stat block's drain, push, swallow (standard.py)
                R["stat_done"] = True
                self._stat_after_strike(R)
            if R.get("thrown"):                             # what was thrown comes down
                self._land_thrown(R)
            follow = R.pop("follow", None) or []
            R["follow"] = []
            R["stage"] = "done"
            if follow:
                for child in reversed(follow):
                    self._stack().append(child)
                return NEXT
            return DONE
        if st == "done":
            return DONE
        raise ServiceError(f"Unknown stage {st}")

    # ------------------------------------------------------------------ death saves
    def _step_dsave(self, R: dict) -> str:
        """A downed player's death saving throw: rolled (on screen with async rolling), then recorded on the sheet."""
        c = self._find_or_none(R["actor"])
        char = self._sheet(c) if c else None
        if R["stage"] == "start":
            ds = char.d["death_saves"] if char else {}
            if not char or char.current_hp > 0 or ds.get("failure", 0) >= 3 or ds.get("success", 0) >= 3:
                return DONE
            if self._wonder_stabilize(c):                       # a Periapt of Wound Closure: stable, no save (wondrous.py)
                return DONE
            if self._subd_dsave(c, char, R):                    # Searing Vengeance: back on their feet instead of a save (subfeats_d.py)
                return DONE
            r = self.rng.randint(1, 20)
            if self._fx(c, "max_heal") or self._fx(c, "dsave_adv"):    # Beacon of Hope, Exalted Champion: advantage on death saves
                r = max(r, self.rng.randint(1, 20))
            if self._nf_dsave_dis(c):                           # Touch of Death's Pull of the Grave: disadvantage (newfeats.py)
                r = min(r, self.rng.randint(1, 20))
            r = self._wonder_dsave(c, r)                        # a Gambler's Blade's bet comes off death saves (wondrous.py)
            R["roll"], R["stage"] = r, "apply"
            outcome = "back up" if r == 20 else "success" if r >= 10 else "two failures" if r == 1 else "failure"
            if self._dice(R, c, "Death save", {"dice": [r], "kept": r, "total": r}, "DC 10", outcome):
                return WAIT
            return NEXT
        if R["stage"] == "apply":
            try:
                res = self.chars.death_save(char.name, roll=R["roll"])
            except ServiceError:
                return DONE
            ds = self._sheet(c).d.get("death_saves") or {}
            self._vfx("dsave", id=c["id"], s=int(ds.get("success") or 0), f=int(ds.get("failure") or 0), nat=R["roll"],
                      up=self._hp_of(c) > 0)                    # a pip fills; three of a kind: stable, or dead
            self._line(R, f"{c['name']} death save: {res.text}", res.text)
            self._subd_dsave_done(c, self._sheet(c), int(R["roll"]))      # Defy Death (subfeats_d.py)
            self._subc_dsave_done(c, self._sheet(c), int(R["roll"]))      # Rage beyond Death (subfeats_c.py)
        return DONE

    def roll_death_save(self, name: str) -> Optional[str]:
        """A player's death save asked from the sheet or the portal. In a running battle with async rolling it rolls on
        every screen (and returns what happened so far); otherwise None - the character sheet rolls it as usual."""
        with self.lock:
            c = next((x for x in self.b["combatants"] if x["kind"] == "pc" and x.get("character") == name), None)
            if c is None or self.b.get("status") != "active" or not (self.b.get("rules") or {}).get("async_rolls"):
                return None
            char = self._sheet(c)
            if not char or char.current_hp > 0:
                raise ServiceError(f"{name} isn't at 0 HP.")
            out = self._run_r(self._new_r("dsave", c, "Death save", summary_targets=c["name"]))
            self._commit()
            return out

    def _smite_rider(self, R: dict, att: Optional[dict], tgt: Optional[dict], sr: dict):
        """What a smite or a ranger's arrow spell does after its extra damage: a save, a push, a burst around the target..."""
        rd = sr["rider"]
        if not tgt or att is None:
            return
        dc = int(sr["dc"])
        if rd.get("plain_mods"):                                # Spirit Shroud: no healing for the creature until the caster's next turn
            if self._alive(tgt):
                self._effect_on(tgt, sr["name"], [], None, None, None, None, att["name"], dict(rd["plain_mods"]), None, att["id"],
                                until=self._until("caster_start", att, tgt))
                self._line(R, f"{tgt['name']} can't regain hit points until {att['name']}'s next turn", "no healing")
            return
        if rd.get("reveal"):
            for e in list(tgt.get("effects") or []):
                if "Invisible" in (e.get("conditions") or []):
                    self._effect_off(tgt, e, sr["name"])
            return
        if rd.get("banish_below"):
            if self._hp_of(tgt) <= rd["banish_below"] and self._alive(tgt):
                self._effect_on(tgt, sr["name"], ["Incapacitated"], None, None, None, 10, att["name"], {"banished": True, "untargetable": True},
                                att.get("id") if att.get("concentrating") else None, att["id"])
                self._line(R, f"{tgt['name']} is banished", "banished")
            return
        if rd.get("burst"):
            from . import geometry as G
            if not tgt.get("pos"):
                return
            tiles = G.area_tiles("emanation", rd["burst"], origin=G.centre(tgt["pos"], tgt.get("span") or 1),
                                 caster_box=G.box(tgt["pos"], tgt.get("span") or 1), **self._bounds_kw()) | \
                G.footprint(tgt["pos"], tgt.get("span") or 1)
            ids = [c["id"] for c in G.creatures_in(tiles, self.b["combatants"]) if c is not att and not self._is_out(c)]
            self._area_vfx(att, tiles, rd["parts"], "burst", G.centre(tgt["pos"], tgt.get("span") or 1))
            R.setdefault("follow", []).append(self._strike(att, sr["name"], ids, mode="save", sv={"ab": rd["ab"], "dc": dc, "half": rd.get("half")},
                                                           parts=rd["parts"], spell=True))
            return
        conc = att["id"] if (att.get("concentrating") or {}).get("spell") == sr["name"] else None    # it lasts while the smite's spell does
        if rd.get("ab") and self._alive(tgt):
            res = self._apply_save(dict(R, conc=conc, label=sr["name"]), att, tgt,
                                   {"ab": rd["ab"], "dc": dc, "conds": rd.get("conds") or [], "repeat": rd.get("repeat"),
                                    "rounds": rd.get("rounds"), "mods": rd.get("mods"), "note": rd.get("note")})
            if not res["ok"]:
                if rd.get("push"):
                    self._push(tgt, att, int(rd["push"]), R)
                if rd.get("prone"):
                    self._cond(tgt, "Prone", True)
                    self._line(R, f"{tgt['name']} is knocked prone", "prone")
                if rd.get("dot"):
                    self._dot_on(tgt, sr["name"], dict(rd["dot"]), rd["dot"].get("save"), dc, 10, att["name"], conc, att["id"])
        elif rd.get("dot") and self._alive(tgt):
            self._dot_on(tgt, sr["name"], dict(rd["dot"]), rd["dot"].get("save"), dc, 10, att["name"], conc, att["id"])

    def _may_target(self, att: dict, tgt: dict, R: dict) -> Optional[str]:
        """Charm and Sanctuary can stop an attack or harmful spell before it is made (None: go ahead)."""
        why = self._subd_may_target(att, tgt, R)                # Among the Dead (subfeats_d.py)
        if why:
            return why
        for e in att.get("effects") or []:
            if "Charmed" in (e.get("conditions") or []) and e.get("source_id") == tgt["id"]:
                return f"{att['name']} is charmed by {tgt['name']} and can't harm it"
        crown = (att.get("turn") or {}).get("crown_victim")       # Crown of Madness: its first attack goes where the caster says
        if crown is not None and R["mode"] == "attack" and not att["turn"].get("crown_done"):
            if tgt["id"] != crown and self._find_or_none(crown) is not None and self._alive(self._find(crown)):
                return f"{att['name']} must attack {self._find(crown)['name']} first (Crown of Madness)"
            att["turn"]["crown_done"] = True
        inside = next((e for e in tgt.get("effects") or [] if (e.get("mods") or {}).get("swallowed_by") not in (None, att["id"])), None)
        if inside:                                                 # swallowed: total cover from everything outside
            return f"{tgt['name']} is inside {inside.get('source') or 'its swallower'}: out of reach"
        if R["mode"] == "attack" or len(R["targets"]) == 1:
            for e, _v in self._fxs(tgt, "sanctuary"):
                src = self._find_or_none(e.get("source_id"))
                dc = e.get("dc") or (self._spell_dc(src) if src else 13)
                res = self._saving_throw(att, "wis", int(dc), spell=True, label="Sanctuary")
                if not res["ok"]:
                    return f"{att['name']} can't bring itself to harm {tgt['name']} (Sanctuary, WIS {res['total']} vs DC {dc})"
        if R["mode"] == "attack":
            why = self._class_may_target(att, tgt)                 # Unbreakable Majesty (classfeats.py)
            if why:
                return why
        return self._spell_immune(tgt, R)                          # a rakshasa's Limited Magic Immunity

    def _mirror_image(self, att: dict, tgt: dict, a: dict) -> Optional[str]:
        """Mirror Image: the attack may go to a duplicate (AC 10 + Dex); a hit destroys it. Returns the line, or None."""
        imgs = [e for e, v in self._fxs(tgt, "images") if int(v) > 0]
        if not imgs or (att.get("pos") and tgt.get("pos") and not self._sees(att, tgt)):
            return None
        e = imgs[0]
        n = int(e["mods"]["images"])
        need = {3: 6, 2: 8}.get(n, 11)
        r = self.rng.randint(1, 20)
        if r < need:
            return None
        total, kept, _d = self._d20_roll(att, int(a.get("bonus") or 0), a.get("adv") if a.get("adv") in ("adv", "dis") else None)
        if kept != 1 and total >= 10 + self._ability(tgt, "dex"):
            e["mods"]["images"] = n - 1
            if n - 1 <= 0 and e in (tgt.get("effects") or []):
                self._effect_off(tgt, e, "the last duplicate is gone")
            return f"{att['name']}'s attack hits one of {tgt['name']}'s duplicates ({n - 1} left)"
        return f"{att['name']}'s attack misses one of {tgt['name']}'s duplicates"

    def _log_attack(self, R: dict, att: dict, tgt: dict):
        cur = R["cur"]
        if cur.get("logged"):
            return
        cur["logged"] = True
        mode = cur.get("mode")
        why = [w for w in cur.get("why") or [] if w != "chosen"]
        res = "CRITICAL HIT" if cur.get("crit") else "hit" if cur.get("hit") else "miss"
        if cur.get("saved_by") and not cur.get("hit"):
            res = f"miss ({cur['saved_by']})"
        cov = f", {V.COVER_NAME[cur['cover']]}" if cur.get("cover") else ""
        txt = (f"{att['name']} uses {R['label']}{cur.get('tag', '')} on {tgt['name']}: d20 {cur['kept']}{' ' + mode if mode else ''}"
               f"{' (' + ', '.join(why) + ')' if why and mode else ''} {cur.get('bonus', 0):+d}{cur.get('note', '')} = {cur['total']} "
               f"vs AC {cur['ac']}{cov} — {res}")
        self._line(R, txt, f"{cur['total']} vs AC {cur['ac']}: " + ("CRIT" if cur.get("crit") else "hit" if cur.get("hit") else "miss"))
        a = R.get("atk") or {}
        self._vfx("attack", by=att["id"], id=tgt["id"], res="crit" if cur.get("crit") else "hit" if cur.get("hit") else "miss",
                  melee=bool(a.get("melee")), dtype=next((str(t).lower() for _d, t in a.get("parts") or [] if t), ""),
                  **({"item": R["thrown_look"]} if R.get("thrown_look") else {}))      # a thrown thing: drawn turning in flight
        self._roll_line(att, "🎲", f"{R['label']} attack{cur.get('tag', '')} → {tgt['name']}", cur["total"],
                       f"d20 {cur['kept']}{' ' + mode if mode else ''} {cur.get('bonus', 0):+d}{cur.get('note', '')} vs AC {cur['ac']} — "
                       + ("**CRIT**" if cur.get("crit") else "hit" if cur.get("hit") else "miss"))

    def _apply_save(self, R: dict, att: Optional[dict], tgt: dict, sv: dict, rolled=None):
        """A save that comes with something else (an attack's rider): roll, damage, conditions - straight away."""
        res = self._saving_throw(tgt, sv["ab"], int(sv["dc"]), spell=sv.get("spell", False), conds=sv.get("conds") or [], label=R["label"])
        self._vfx("save", id=tgt["id"], ok=bool(res["ok"]))
        self._line(R, f"{tgt['name']} {sv['ab'].upper()} save vs {R['label']}: d20 {res['kept']}{self._save_mode_note(res)}{res['note']} = {res['total']} vs DC {sv['dc']} — "
                      + ("success" if res["ok"] else "failed"), f"{sv['ab'].upper()} save {res['total']} vs DC {sv['dc']}: " + ("saved" if res["ok"] else "failed"))
        if rolled:
            factor = (.5 if sv.get("half") else 0.0) if res["ok"] else 1.0
            if factor:
                self._line(R, self._deal_rolled(tgt, rolled, by=att, label=R["label"], factor=factor, magical=R.get("magical", True)), self._short)
        conds = list(sv.get("conds") or [])
        if not res["ok"] and sv.get("fail5") and int(sv["dc"]) - int(res["total"]) >= 5:
            conds += [c for c in sv["fail5"] if c not in conds]
        if not res["ok"] and (conds or sv.get("mods")):
            self._effect_on(tgt, R["label"], conds, sv["ab"], int(sv["dc"]), sv.get("repeat"), sv.get("rounds"),
                            att["name"] if att else "", sv.get("mods"), R.get("conc"), att["id"] if att else None,
                            until=self._until(sv["until"], att or tgt, tgt) if isinstance(sv.get("until"), str) else sv.get("until"))
            self._effect_tail(tgt, R["label"], sv, att)
            if sv.get("escape") and conds and tgt.get("effects"):      # Flesh Entomb: the Strength check that breaks out (standard._escape)
                tgt["effects"][-1]["escape"] = sv["escape"]
            now = [c.lower() for c in sv.get("conds") or []] + ([sv["note"]] if sv.get("note") else [])
            if now:
                self._line(R, f"{tgt['name']} is now {', '.join(now)}" + (f" (saves again at the {sv['repeat']} of its turn)" if sv.get("repeat") else ""),
                           "now " + ", ".join(now))
        return res

    def _save_consequences(self, R: dict, att: Optional[dict], tgt: dict):
        sv = R["sv"]
        cur = R["cur"]
        if cur.get("ok"):
            if sv.get("ends_on_ok") and att is not None and (att.get("concentrating") or {}).get("spell") == R["label"]:
                self._drop_conc(att, f"{tgt['name']} saved")       # Fractured Awareness: a successful save ends the spell
            if sv.get("on_save"):
                self._effect_on(tgt, R["label"], [], None, None, None, sv["on_save"].get("rounds"), att["name"] if att else "",
                                sv["on_save"].get("mods"), R.get("conc"), att["id"] if att else None)
            return
        conds = [c for c in sv.get("conds") or []]
        if sv.get("fail5") and int(sv["dc"]) - int(cur.get("total") or 0) >= 5:     # failed by 5 or more: paralyzed as well
            conds += [c for c in sv["fail5"] if c not in conds]
        mods = sv.get("mods")
        if conds or mods:
            self._effect_on(tgt, sv.get("effect_name") or R["label"], conds, sv["ab"], int(sv["dc"]), sv.get("repeat"),
                            sv.get("rounds"), att["name"] if att else "", mods, R.get("conc"), att["id"] if att else None,
                            until=self._until(sv["until"], att or tgt, tgt) if isinstance(sv.get("until"), str) else sv.get("until"),
                            ends_on=sv.get("ends_on"))
            self._effect_tail(tgt, sv.get("effect_name") or R["label"], sv, att)
            now = [c.lower() for c in conds] + ([sv["note"]] if sv.get("note") else [])
            if now:
                self._line(R, f"{tgt['name']} is now {', '.join(now)}" + (f" (saves again at the {sv['repeat']} of its turn)" if sv.get("repeat") else "")
                           + (f", {sv['rounds']} rounds" if sv.get("rounds") else ""), "now " + ", ".join(now))
        if sv.get("push") and att is not None and not (sv.get("push_size") and _bigger_than(self._size_of(tgt), sv["push_size"])):
            self._push(tgt, att, int(sv["push"]), R)            # (Unrelenting Force: "a Huge or larger creature isn't pushed")
        if sv.get("revert_shape") and tgt.get("shape"):          # Moonbeam: a shapechanger that fails is back in its true form
            self._revert_shape(tgt)
            self._line(R, f"{tgt['name']} reverts to its true form", "true form")
        if sv.get("drop_to_0") and self._hp_of(tgt) > 0:
            self._line(R, f"{tgt['name']} drops to 0 hit points: " + self._deal_rolled(tgt, [[self._hp_of(tgt), ""]], by=att, label=R["label"]), "0 HP")
        if sv.get("destroy_cr") is not None and self._hp_of(tgt) > 0:      # Destroy Undead
            m = self._monster(tgt) if not self._sheet(tgt) else None
            if m is not None and float(m.get("cr_num") or 0) <= float(sv["destroy_cr"]):
                self._line(R, f"{tgt['name']} is destroyed: " + self._deal_rolled(tgt, [[self._hp_of(tgt), ""]], by=att, label=R["label"]), "destroyed")
        if sv.get("pull_to_point") and R.get("origin") is not None and tgt.get("pos"):     # Maelstrom: dragged towards the centre of the area
            self._push(tgt, {"pos": [int(R["origin"][0]), int(R["origin"][1])], "span": 1}, -int(sv["pull_to_point"]), R)
        if sv.get("pull") and att is not None and att.get("pos"):        # Lightning Lure, Grasping Vine: dragged towards the caster
            self._push(tgt, att, -int(sv["pull"]), R)
        if sv.get("prone") and "Prone" not in self._conds(tgt):
            self._cond(tgt, "Prone", True)
            self._line(R, f"{tgt['name']} is knocked prone", "prone")
        if sv.get("drop_conc") and tgt.get("concentrating"):     # Disruptive Tune: it loses its Concentration
            self._drop_conc(tgt, f"{R['label']}")
        if sv.get("exhaust") and att is not None:                 # Waves of Exhaustion: a level (never above the cap), gone when the spell ends
            have = self._exhaustion(tgt)
            if have < int(sv.get("exhaust_cap") or 6) and not self._fx(tgt, "no_exhaust"):
                self._exhaust(tgt, 1)
                mark = next((e for e in tgt.get("effects") or [] if e["name"] == R["label"] + " (exhaustion)" and e.get("source_id") == att["id"]), None)
                if mark is None:
                    self._effect_on(tgt, R["label"] + " (exhaustion)", [], None, None, None, None, att["name"], {"exh_given": 1}, R.get("conc"), att["id"])
                else:
                    mark["mods"]["exh_given"] = int(mark["mods"].get("exh_given") or 0) + 1

    def _after_hit(self, R: dict, att: Optional[dict], tgt: dict):
        """After a hit lands: retaliation (Fire Shield), effects that end on attacking, the hit target's reactions later."""
        a = R["atk"]
        self._subb_after_hit(att, tgt)                          # Scornful Rebuke (subfeats_b.py)
        self._subc_after_hit(R, att, tgt)                       # Spiked Retribution (subfeats_c.py)
        if att is not None and a.get("melee") and self._dist(att, tgt) <= 5:
            for e, (dice, dtype) in self._fxs(tgt, "retaliate"):
                if e["mods"].get("retaliate_once"):               # Death Armor: once on each turn
                    if e.get("ret_used") == self._turn_key():
                        continue
                    e["ret_used"] = self._turn_key()
                self._line(R, f"{e['name']}: " + self._deal_rolled(att, [[roll(dice), dtype]], by=tgt, label=e["name"]), "")
        kind_of = str((self._monster(att) or {}).get("type") or "").lower() if att is not None and a.get("melee") else ""
        for e, v in self._fxs(tgt, "holy_blind") if any(k in kind_of for k in ("fiend", "undead")) and self._alive(att) else []:
            src = self._find_or_none(e.get("source_id")) or tgt   # Holy Aura: a fiend or undead that hits is blinded (Con save)
            conc = src["id"] if (src.get("concentrating") or {}).get("spell") == e["name"] else None
            self._apply_save(dict(R, conc=conc, label=e["name"]), src, att, {"ab": "con", "dc": self._spell_dc(src), "conds": ["Blinded"], "spell": True})
        if att is not None:
            for e, v in self._fxs(att, "ends_on"):
                if "attack" in (v or []) and e in (att.get("effects") or []):
                    self._effect_off(att, e, "attacked")
        if att is not None and self._alive(att):
            offers = self._eligible("after_damage", R, attacker=att["id"], target=tgt["id"])
            for item in offers:
                R.setdefault("after_offers", []).append(item)
            if R.get("after_offers"):
                R.setdefault("follow", [])
                for item in R.pop("after_offers"):
                    child = self._new_r("offer", tgt, "reaction", item=item, attacker=att["id"])
                    R["follow"].append(child)

    def _step_offer(self, R: dict) -> str:
        """A reaction offered after something happened (Hellish Rebuke): a window of one."""
        if R["stage"] == "start":
            R["stage"] = "ask"
        if R["stage"] == "ask":
            item = R["item"]
            if not R.get("win"):
                R["win"] = {"name": item["window"], "queue": [item], "ctx": {"attacker": R["attacker"], "target": item["reactor"]}}
            got = self._window(R, item["window"], "done", attacker=R["attacker"], target=item["reactor"])
            return got
        return DONE

    def _divine_strike(self, att: dict, R: dict) -> list:
        """A cleric's Divine Strike: once on each of its own turns, a weapon hit deals 1d8 (2d8) more of the domain's type."""
        from . import features as F
        char = self._sheet(att)
        ds = F.divine_strike(char) if char and R["atk"].get("weapon") else None
        key = [self.b.get("round"), self.b.get("turn")]
        if not ds or self.b.get("turn") != att["id"] or att.get("strike_used") == key:
            return []
        att["strike_used"] = key
        self._say(f"{att['name']}'s Divine Strike (+{ds[0]})")
        return [[ds[0], ds[1] or ((R["atk"].get("parts") or [["", ""]])[0][1])]]

    def _sneak_attack(self, att: dict, tgt: dict, R: dict) -> list:
        from . import features as F
        char = self._sheet(att)
        a = R["atk"]
        if not char or not a.get("weapon") or not (a.get("finesse") or not a.get("melee")):
            return []
        dice = F.sneak_dice(char)
        if not dice:
            return []
        key = [self.b.get("round"), self.b.get("turn")]
        if att.get("sneak_used") == key and not self._subd_sneak_again(att, tgt, R):     # Sudden Strike (subfeats_d.py)
            return []
        cur = R["cur"]
        if cur.get("mode") == "dis":
            return []
        ally = any(o is not att and o is not tgt and not self._hostile(o, att) and self._can_act(o) and o.get("pos")
                   and self._dist(o, tgt) <= 5 for o in self.b["combatants"])
        if cur.get("mode") == "adv" or ally or self._class_sneak_ok(att, tgt):     # Rakish Audacity, Insightful Fighting
            att["sneak_used"] = key
            self._subd_sneak_note(att, tgt, R)
            self._line(R, f"{att['name']} strikes where it hurts: Sneak Attack (+{dice})", "Sneak Attack")
            return [[dice, a["parts"][0][1] if a.get("parts") else ""]] + self._subd_sneak_extra(att, tgt, R)    # Eye for Weakness
        return []

    def _crit_extra(self, att: dict, a: dict) -> Optional[str]:
        from . import features as F
        char = self._sheet(att)
        if not char or not a.get("parts"):
            return None
        die = str(a["parts"][0][0])
        m = re.match(r"\d*d(\d+)", die)
        if not m:
            return None
        n = F.brutal_dice(char) + (1 if F.savage(char) else 0)
        return f"{n}d{m.group(1)}" if n else None
