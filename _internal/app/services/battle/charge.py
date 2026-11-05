"""Charging: a straight run at a foe, then the blow the run sets up, as one entry on the bar ("charge:<key>").

    charge_options(c)   one entry for each way the creature can charge: [{'key', 'name', 'need', 'cost', 'tip', 'why', 'options'}]
        monster   a trait that pays off a run (Charge, Pounce, Trampling Charge, Dive Attack, Rolling Charge, Terror Dive:
                  "moves at least 20 feet straight toward a target and then hits it with a gore attack"): the run, then that
                  attack; an attack whose own hit says it (a ceratops' Gore: "If the ceratops moved at least 20 feet in a straight
                  line toward the target immediately before the hit"); a trait that goes off where the run ends (Headfirst
                  Charge, Skewering Charge): the run alone
        hero      Charger: Dash, the run, a bonus-action attack (+5 damage) or a shove (pushed 10 ft); a centaur's Charge: the
                  run and a melee weapon attack (its hooves then open on the bar); the Cavalier's Ferocious Charger: the run and
                  an attack; the Tiger totem (raging): the run, an attack and a bonus-action attack; Goring Rush: Dash, the run,
                  the horns
    charge(cid, key, target_id, option, adv)   plays one

The run (_charge_line) goes from where the charger stands to a square from which the foe is in reach, every step on the
straight line between: a wall or a creature in the way, a run shorter than the charge needs, or too little movement, and
that square is out. It is walked like any move (movement spent, opportunity attacks, zones and reactions on the way); the
blow comes after, if the charger is still up and still has the foe in reach. What a charge pays off is read where the hit
lands (traits.py _charged: the run kept in turn['run'] is straight, long enough and ended nearer the foe).
"""
import math
import re
from typing import List, Optional

from ...rules import combat_feats as CF
from ..common import ServiceError
from . import conditions as K
from . import economy as EC
from . import features as F
from . import geometry as G
from .resolve import DONE, NEXT
from .traits import CHARGE_RE, END_RE, RUN_HIT_RE

_ENEMY = {"type": "creature", "count": 1, "enemies": True}


def _line(a, b) -> List[tuple]:
    """The squares on the straight line from a to b, a and b included: each one a step (straight or diagonal) from the last."""
    n = max(abs(b[0] - a[0]), abs(b[1] - a[1]))
    if not n:
        return [tuple(a)]
    return [(a[0] + math.floor((b[0] - a[0]) * k / n + .5), a[1] + math.floor((b[1] - a[1]) * k / n + .5)) for k in range(n + 1)]


def _plain(name: str) -> str:
    return re.sub(r"\s*\(.*?\)", "", name or "").strip()


class ChargeMixin:
    # ------------------------------------------------------------------ what can charge
    def _charge_sources(self, c: dict) -> List[dict]:
        """Each way `c` can charge: {'key', 'name', 'need' (feet of run), 'then', 'dash', 'fly', 'size', 'tip'}.
        'then': {'do': 'monster', 'entry'} | {'do': 'weapon', 'bonus'} | {'do': 'charger'} | {'do': 'horns'} | {'do': 'run'}."""
        out = []
        char = self._sheet(c)
        if char and not c.get("form"):
            if self._feat(c, "charger"):
                out.append({"key": "charger", "name": "Charger", "need": 10, "dash": True, "then": {"do": "charger"},
                            "tip": "Dash, run at least 10 ft straight at the foe, then a bonus-action melee attack (+5 damage) or a shove "
                                   "that pushes it 10 ft (Charger)."})
            if char.has_feature("Charge") and (char.d.get("race") or "").startswith("Centaur"):
                out.append({"key": "centaur", "name": "Charge (centaur)", "need": 30, "then": {"do": "weapon"},
                            "tip": "Run at least 30 ft straight at the foe and attack it with a melee weapon; on a hit your hooves "
                                   "follow as a bonus action (Charge (hooves) on the bar)."})
            if F.sub_at(char, "Fighter", "Cavalier", 15):
                out.append({"key": "cavalier", "name": "Ferocious Charger", "need": 10, "then": {"do": "weapon"},
                            "tip": "Run at least 10 ft straight at the foe and attack it: a hit makes it save (Strength) or fall prone, "
                                   "once a turn (Ferocious Charger)."})
            if F.sub_at(char, "Barbarian", "Path of the Totem Warrior", 14) and CF.is_on(char, "totem_attunement") == "Tiger":
                out.append({"key": "tiger", "name": "Tiger's charge", "need": 20, "size": "Large", "raging": True,
                            "then": {"do": "weapon", "bonus": True},
                            "tip": "Raging: run at least 20 ft straight at a Large or smaller foe, attack it, then a bonus-action melee "
                                   "weapon attack against it (Totemic Attunement: Tiger)."})
            if char.has_feature("Goring Rush"):
                out.append({"key": "goring", "name": "Goring Rush", "need": 20, "dash": True, "then": {"do": "horns"},
                            "tip": "Dash, run at least 20 ft at the foe, then a bonus-action attack with your horns (Goring Rush)."})
            return out
        m = self._monster(c) or {}
        acts = [e for sec in ("actions", "bonus_actions") for e in m.get(sec) or [] if re.search(r"[+-]\d+ to hit", e.get("text") or "")
                and re.search(r"Melee", e.get("text") or "", re.I) and self._form_ok(c, e.get("name", ""))]
        for t in self._traits(c):
            text = t.get("text") or ""
            if not self._form_ok(c, t.get("name", "")):
                continue
            g = CHARGE_RE.search(text)
            if g:
                weapon = g.group(2).lower().replace("its ", "").strip()
                if weapon in ("melee weapon", "weapon", "melee"):
                    e = acts[0] if acts else None
                else:
                    e = next((x for x in acts if _plain(x["name"]).lower().rstrip("s") == weapon.rstrip("s")), None) or \
                        next((x for x in acts if _plain(x["name"]).lower().startswith(weapon.rstrip("s")) or weapon.startswith(_plain(x["name"]).lower().rstrip("s"))), None)
                if e:
                    out.append({"key": f"t:{t['name']}", "name": f"{_plain(t['name'])} ({_plain(e['name'])})", "need": int(g.group(1)),
                                "fly": "dives" in g.group(0).lower() or bool(re.search(r"\bis flying\b", text[:g.end()])),
                                "then": {"do": "monster", "entry": e["name"]}, "tip": text[:400]})
                continue
            g = END_RE.search(text)
            if g:
                size = re.search(r"\b(Tiny|Small|Medium|Large|Huge) or smaller\b", g.group(0))
                out.append({"key": f"e:{t['name']}", "name": _plain(t["name"]), "need": int(g.group(1)), "size": size.group(1) if size else None,
                            "fly": bool(re.search(r"\bis flying\b|\bdives\b", text[:g.end()])), "then": {"do": "run"}, "tip": text[:400]})
        for e in acts:                                       # a Gore whose own hit pays off the run
            hit = (e.get("text") or "").partition("Hit:")[2]
            g = RUN_HIT_RE.search(hit)
            if g and not any(s["then"].get("entry") == e["name"] for s in out):
                out.append({"key": f"a:{e['name']}", "name": f"Charge ({_plain(e['name'])})", "need": int(g.group(1)),
                            "then": {"do": "monster", "entry": e["name"]}, "tip": e["text"][:400]})
        return out

    def _charge_weapons(self, c: dict) -> list:
        char = self._sheet(c)
        ws = [w for w in (char.attacks() if char else []) if not w.get("ranged")]
        return sorted(ws, key=lambda w: "unarmed" in (w.get("props") or []) or "unarmed" in w["name"].lower())   # a weapon in hand first

    def _charge_cost(self, c: dict, src: dict) -> str:
        """What the blow at the end costs (the bar's group): its stat block entry's cost, the Attack action, or a bonus action."""
        do = src["then"]["do"]
        if do == "monster":
            sec, _e = self._entry_section(c, src["then"]["entry"])
            if sec == "bonus_actions":
                return "bonus"
            return "multi" if self._entry_section(c, "Multiattack")[1] else "action"
        if do == "weapon":
            return "attack"
        if do in ("charger", "horns"):
            return "action" if src.get("dash") and not (c.get("turn") or {}).get("dashed") and self._economy_on() else "bonus"
        return "move:5"

    def _charge_budget(self, c: dict, src: dict) -> int:
        """The feet the run may take: what movement is left, with the Dash this charge takes first."""
        t = c.get("turn") or {}
        dash = src.get("dash") and not t.get("dashed")
        if self._economy_on():
            return int(t.get("move", 0)) + (self._speed(c) if dash else 0)
        return self._speed(c) * (2 if dash else 1)

    def _charge_why(self, c: dict, src: dict, tgt: Optional[dict] = None) -> Optional[str]:
        """Why this charge can't be made now (None: it can). With no target: only what the bar can tell beforehand."""
        t = c.get("turn") or {}
        econ = self._economy_on()
        if econ and self.b.get("turn") != c["id"]:
            return f"It isn't {c['name']}'s turn"
        if not c.get("pos"):
            return "Put it on the map first"
        if not K.can_move(self._conds(c), self._exhaustion(c)) or self._speed(c) <= 0:
            return f"{c['name']} can't move"
        if "Prone" in self._conds(c):
            return "Stand up first"
        if src.get("fly") and not self._speeds(c).get("fly"):
            return "Only while it can fly"
        if src.get("raging") and not self._raging(c):
            return "Only while raging"
        if src.get("dash") and self._fx(c, "no_dash") and not t.get("dashed"):
            return f"{c['name']} can't take the Dash action"
        do = src["then"]["do"]
        if do == "monster":
            name = src["then"]["entry"]
            why = self._pay(c, self._charge_cost(c, src), f"Attack: {_plain(name)}", check_only=True)
            if why:
                return why
            if (c.get("spent") or {}).get(_plain(name)):
                return "Not recharged"
        elif do == "weapon":
            if not self._charge_weapons(c):
                return "No melee weapon in hand"
            why = self._pay(c, "attack", "Charge", check_only=True)
            if why:
                return why
            if src["then"].get("bonus") and econ and t.get("bonus", 1) < 1:
                return "Bonus action already used"
        elif do in ("charger", "horns"):
            if do == "charger" and not self._charge_weapons(c):
                return "No melee weapon in hand"
            if src.get("dash") and not t.get("dashed"):
                why = self._pay(c, "action", "Dash", check_only=True)
                if why:
                    return why
            if econ and t.get("bonus", 1) < 1:
                return "Bonus action already used"
        if self._charge_budget(c, src) < src["need"]:
            return f"Needs a run of {src['need']} ft"
        if tgt is not None:
            if tgt is c or not self._hostile(c, tgt):
                return "Pick a foe to charge"
            if not tgt.get("pos"):
                return f"{tgt['name']} isn't on the map"
            if src.get("size"):
                from .standard import SIZES
                if SIZES.index(self._size_of(tgt)) > SIZES.index(src["size"]):
                    return f"{tgt['name']} is too big (only {src['size']} or smaller)"
        return None

    def charge_options(self, c: dict) -> List[dict]:
        """The bar's charges (see the module's doc)."""
        out = []
        for src in self._charge_sources(c):
            ent = {k: src[k] for k in ("key", "name", "need", "tip")}
            ent["cost"] = self._charge_cost(c, src)
            ent["why"] = self._charge_why(c, src)
            reach = 5
            if src["then"]["do"] == "monster":
                _s, e = self._entry_section(c, src["then"]["entry"])
                rch = re.search(r"reach (\d+) ft", (e or {}).get("text") or "")
                reach = max(5, int(rch.group(1))) if rch else 5
            ent["range"] = self._charge_budget(c, src) + reach
            if src["then"]["do"] in ("weapon", "charger"):
                ws = self._charge_weapons(c)
                opts = [{"value": f"w:{w['name']}", "label": w["name"]} for w in ws]
                if src["then"]["do"] == "charger":
                    opts.append({"value": "shove", "label": "Shove (push 10 ft)"})
                if len(opts) > 1:
                    ent["options"] = opts
            out.append(ent)
        return out

    # ------------------------------------------------------------------ the run
    def _charge_reach(self, c: dict, src: dict, weapon: Optional[dict]) -> int:
        if src["then"]["do"] == "monster":
            _s, e = self._entry_section(c, src["then"]["entry"])
            rch = re.search(r"reach (\d+) ft", (e or {}).get("text") or "")
            return max(5, int(rch.group(1))) if rch else 5
        if weapon is not None and src["then"]["do"] in ("weapon", "charger"):
            return max(5, int(self._weapon_atk(c, weapon).get("reach") or 5))
        return 5

    def _charge_line(self, c: dict, tgt: dict, reach: int, need: int, budget: int):
        """(path, cost) of the cheapest straight run of at least `need` feet that ends with `tgt` in reach; raises why not."""
        span, tspan = c.get("span") or 1, tgt.get("span") or 1
        start = tuple(c["pos"])
        fb = G.box(tgt["pos"], tspan)
        blocked = self._blocked_tiles()
        hostile, other = self._occupied(c)
        rough = self._difficult_tiles(c) | other
        drag = self._drag_factor(c)
        before = G.distance_ft(start, span, tgt["pos"], tspan)
        best, why = None, None
        r = reach // 5
        for x in range(fb[0] - r - span, fb[2] + r + 2):
            for y in range(fb[1] - r - span, fb[3] + r + 2):
                if 5 * G.gap(G.box((x, y), span), fb) > reach or not self._tile_ok(c, x, y):
                    continue
                if G.distance_ft(start, 1, (x, y), 1) < need or G.distance_ft((x, y), span, tgt["pos"], tspan) >= before:
                    why = why or f"Too close to {tgt['name']} for a run of {need} ft"
                    continue
                way = _line(start, (x, y))
                cost, ok = 0, True
                for a, b in zip(way, way[1:]):
                    if not self._step_ok(c, a, b, blocked, hostile):
                        ok = False
                        break
                    cost += 5 * (2 if G.footprint(b, span) & rough else 1) * drag
                if not ok:
                    why = f"Something is in the way of a straight run at {tgt['name']}"
                    continue
                if cost > budget:
                    why = f"Not enough movement for the run ({cost} ft, {budget} ft left)"
                    continue
                (ex, ey), (tx, ty) = G.centre((x, y), span), G.centre(tgt["pos"], tspan)
                rank = (cost, G.gap(G.box((x, y), span), fb), math.hypot(ex - tx, ey - ty))     # cheapest, then head-on
                if best is None or rank < best[0]:
                    best = (rank, [list(p) for p in way], cost)
        if best is None:
            raise ServiceError(why or f"No straight run at {tgt['name']} from here")
        end = best[1][-1]
        for e in c.get("effects") or []:                      # frightened: never closer to what it fears
            src = self._find_or_none(e.get("source_id"))
            if "Frightened" in (e.get("conditions") or []) and src and src.get("pos") and src is not c \
                    and G.distance_ft(end, span, src["pos"], src.get("span") or 1) < self._dist(c, src):
                raise ServiceError(f"{c['name']} is too frightened of {src['name']} to move closer")
        leash = self._subd_leash(c, end[0], end[1])           # Champion Challenge (subfeats_d.py)
        if leash:
            raise ServiceError(leash)
        return best[1], best[2]

    # ------------------------------------------------------------------ playing one
    def charge(self, cid: int, key: str, target_id: Optional[int] = None, option: Optional[str] = None, adv: Optional[str] = None) -> str:
        with self.lock:
            self._busy()
            c = self._find(cid)
            src = next((s for s in self._charge_sources(c) if s["key"] == key), None)
            if not src:
                raise ServiceError(f"{c['name']} has no such charge.")
            tgt = self._find_or_none(target_id or self.b.get("target"))
            if tgt is None:
                raise ServiceError("Pick the foe to charge.")
            why = self._charge_why(c, src, tgt)
            if why:
                raise ServiceError(why)
            weapon = None
            if src["then"]["do"] in ("weapon", "charger"):
                ws = self._charge_weapons(c)
                pick = str(option or "")
                weapon = next((w for w in ws if pick == f"w:{w['name']}"), ws[0] if ws else None)
            path, cost = self._charge_line(c, tgt, self._charge_reach(c, src, weapon), src["need"], self._charge_budget(c, src))
            t = c.get("turn")
            if src.get("dash") and not (t or {}).get("dashed"):       # Charger, Goring Rush: the Dash first
                self._pay(c, "action", "Dash")
                if t is not None:
                    EC.dash(c["turn"])
            if c.get("turn") is not None:
                c["turn"].pop("run", None)                    # the charge's run starts here
            c.pop("run_off", None)
            self._vfx("action", id=c["id"], key="charge", name=src["name"], other=tgt["id"])
            then = dict(src["then"], weapon=weapon["name"] if weapon else None, shove=option == "shove", adv=adv)
            R = self._new_r("charge", c, src["name"], summary_targets="", path=path, cost=cost, target=tgt["id"], then=then, need=src["need"])
            out = self._run_r(R)
            self._commit()
            return out

    def _step_charge(self, R: dict) -> str:
        """The run (a walk), then the blow at the foe if it is still in reach."""
        c = self._find_or_none(R["actor"])
        tgt = self._find_or_none(R.get("target"))
        if c is None or not c.get("pos"):
            return DONE
        if R["stage"] == "start":
            R["stage"] = "hit"
            self._line(R, f"{c['name']} charges at {tgt['name'] if tgt else 'its foe'} ({R['label']})")
            if len(R["path"]) >= 2:
                self._stack().append(self._new_r("walk", c, "move", path=R["path"], i=0, cost=R["cost"], summary_targets=""))
            return NEXT
        if R["stage"] != "hit":
            return DONE
        R["stage"] = "end"
        then = R["then"]
        if then["do"] == "run" or tgt is None or not self._alive(c) or K.incapacitated(self._conds(c)):
            return DONE
        if self._is_out(tgt) or not tgt.get("pos"):
            self._line(R, f"{c['name']}'s charge finds nobody to hit")
            return DONE
        if self._run_ft(c) < R["need"]:
            self._line(R, f"{c['name']}'s run was cut short: no charge")
        try:
            strikes = self._charge_strikes(c, tgt, then, R)
        except ServiceError as e:
            self._line(R, f"{c['name']}: {e}")
            return DONE
        for S in reversed(strikes):
            self._stack().append(S)
        return NEXT if strikes else DONE

    def _charge_strikes(self, c: dict, tgt: dict, then: dict, R: dict) -> list:
        """The blow (built, not run), paid for now."""
        do = then["do"]
        adv = then.get("adv")
        if do == "monster":
            _sec, e = self._entry_section(c, then["entry"])
            if not e:
                return []
            base = _plain(e["name"])
            S = self._monster_strike(c, tgt, base, e["text"], adv=adv)
            S["atk"] = self._check_reach(c, tgt, S["atk"])
            self._pay(c, self._charge_cost(c, {"then": then}), f"Attack: {base}")
            return [S]
        char = self._sheet(c)
        if do == "horns":
            mod = char.mod("str")
            atk = self._check_reach(c, tgt, {"bonus": char.proficiency_bonus + mod, "n": 1, "melee": True, "weapon": True, "reach": 5,
                                             "str_based": True, "props": [], "parts": [[f"1d6{mod:+d}" if mod else "1d6", "piercing"]]})
            atk["adv"] = adv
            self._pay(c, "bonus", "Goring Rush")
            return [self._strike(c, "Goring Rush (horns)", [tgt["id"]], mode="attack", atk=atk)]
        if do == "charger" and then.get("shove"):            # Athletics against Athletics or Acrobatics; the run makes it 10 ft
            if self._dist(c, tgt) > 5:
                raise ServiceError(f"{tgt['name']} is too far away to shove")
            self._pay(c, "bonus", "Charger")
            mine = self._check(c, "Athletics")
            theirs = max(self._check(tgt, "Athletics"), self._check(tgt, "Acrobatics")) if self._can_act(tgt) else 0
            if mine < theirs:
                self._line(R, f"{c['name']} fails to shove {tgt['name']} ({mine} vs {theirs})")
            else:
                feet = 10 if self._run_ft(c) >= 10 else 5
                self._line(R, f"{c['name']} slams into {tgt['name']} ({mine} vs {theirs})")
                self._push(tgt, c, feet, R)
            return []
        w = next((a for a in char.attacks() if a["name"] == then.get("weapon")), None)
        if not w:
            raise ServiceError("No melee weapon in hand")
        atk = self._feat_attack(c, w, self._check_reach(c, tgt, self._weapon_atk(c, w)))
        atk["adv"] = adv
        if do == "charger":
            label = w["name"]
            if self._run_ft(c) >= 10:
                atk["parts"] = list(atk["parts"]) + [["5", atk["parts"][0][1]]]
                label = f"{w['name']} (charge)"
            self._pay(c, "bonus", "Charger")
            return [self._strike(c, self._feat_attack_label(atk, label), [tgt["id"]], mode="attack", atk=atk, magical=atk.get("magical", False))]
        self._pay_attack(c, F.extra_attacks(char), w["name"])
        out = [self._strike(c, self._feat_attack_label(atk, w["name"]), [tgt["id"]], mode="attack", atk=atk, magical=atk.get("magical", False))]
        if then.get("bonus") and self._charged(c, tgt, 20):  # the Tiger: a second blow as a bonus action
            atk2 = dict(atk, adv=adv)
            self._pay(c, "bonus", "Tiger totem")
            out.append(self._strike(c, self._feat_attack_label(atk2, f"{w['name']} (Tiger)"), [tgt["id"]], mode="attack", atk=atk2,
                                    magical=atk.get("magical", False)))
        return out
