"""Monster traits that change attacks and damage in play, read from the stat block's own text.

    Martial Advantage, Sneak Attack     once per turn, extra damage when an ally stands next to the target (or with advantage)
    Charge, Pounce, Trampling Charge,   moved at least N feet straight toward the target this turn, then hit with the named
    Dive Attack                         attack: extra damage and/or a Strength save against being knocked prone
    Surprise Attack, Ambusher           the first round against a creature that hasn't had its turn yet (the battle's surprise)
    Blood Frenzy                        advantage on melee attacks against a creature missing hit points
    Reckless                            taken at the start of each of its turns: advantage on melee attacks, attacks against it too
    Relentless, ... Awakening           dropping to 0: 1 hit point (a boar, once), its hit points reset (a greatwyrm, once)
    Pounce, Trampling Charge, Rampage   a follow-up attack as a bonus action ("trait:follow_up" on the bar)
    Fey Step, Superior Invisibility     bonus actions from traits ("trait:teleport:<feet>", "trait:invisible")
    Imix's Blessing and kin             temporary hit points for dropping an enemy
    Lair actions                        lair_actions(): the lair text's bullets, on the bar once a round
    Read by wording, whatever the name  "advantage on melee attack rolls against any creature that doesn't have all its hit
                                        points" (Blood Frenzy), "...against any creature grappled by it" (Grappler), "While it is
                                        in bright light, attack rolls against it have disadvantage" (the map's light at its tiles)
    Counters                            "While it has at least one radiance, it has resistance to all damage. Each time it takes 15
                                        or more damage at once, it loses one" (a ward that wears off; the last one stuns it)
    Taking damage                       "The first time it is reduced to half its hit points or fewer, its X recharges"
    Leaving                             "At the end of its fourth turn, it steps through the portal and is gone": off the map, out

Movement for a charge is kept per turn in turn['run'] ({'from', 'to', 'tiles'}), extended by each walk that starts where the
last one ended; "straight toward" is read as: the run's start and end are at least N feet apart, no tile of it strays more
than a square off the line between them, and the end is nearer the target. charge.py runs such a line on purpose.
    Ends a run       "moves at least 20 feet in a straight line and ends within 5 feet of a Large or smaller creature, that
                     creature must succeed on a DC 14 Strength saving throw or..." (Headfirst Charge): when the walk ends
"""
import re
from typing import List, Optional

from ...rules.data import rules
from ..common import ServiceError
from . import combat_rules as CR
from . import conditions as K
from . import geometry as G
from . import modifiers as M
from . import sight as V

CHARGE_RE = re.compile(r"(?:moves|dives|rolls|flies|swims|charges) at least (\d+) feet (?:straight |in a straight line )?toward (?:a|an|the) "
                       r"(?:[\w-]+ )?(?:target|creature|enemy)[^.]*?hits?(?: it| that target| the target)?(?: with)? (?:an? |its |his |her )?"
                       r"([\w' -]+?)(?: attack)?(?: on the same turn|\.|,|$)", re.I)    # Charge, Pounce, Dive Attack, Rolling Charge, Terror Dive
RUN_HIT_RE = re.compile(r"\bmove[sd]? (?:at least )?(\d+)\+? (?:feet|ft\.?) (?:straight |in a straight line )?toward", re.I)   # in an attack's own hit
END_RE = re.compile(r"(?:moves|dives|flies|charges) at least (\d+) feet in a straight line[^.]*?(?:and|that) ends within 5 feet of[^.]*?"
                    r"must succeed on a DC \d+", re.I)                  # Headfirst Charge, Skewering Charge, an avoral's Dive Attack
FOLLOW_RE = re.compile(r"If the target is (?:knocked )?prone, [\w ]+? can make (?:one|another) (?:attack with its )?(\w+)(?: attack)?", re.I)
EXTRA_RE = re.compile(r"extra \d+ \((\d+d\d+(?: ?[+-] ?\d+)?)\)(?: (\w+))? damage|extra (\d+d\d+)(?: (\w+))? damage", re.I)
FRENZY_RE = re.compile(r"has advantage on melee attack rolls against any creature that doesn't have all its hit points")
GRAPPLER_RE = re.compile(r"has advantage on attack rolls against any creature grappled by (?:it|him|her)\b")
HAZE_RE = re.compile(r"^While (?:it|the [\w' -]+?) is in bright light, attack rolls against it have disadvantage")
NUMBERS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
           "first": 1, "second": 2, "third": 3, "fourth": 4, "fifth": 5, "sixth": 6, "seventh": 7, "eighth": 8}
COUNTER_RE = re.compile(r"While it has at least one (\w+), it has resistance to all damage\. Each time it takes (\d+) or more damage at once, "
                        r"it loses one \1")         # Humbaba's Seven Radiances
LEAVE_RE = re.compile(r"At the end of its (first|second|third|fourth|fifth|sixth|\d+)(?:st|nd|rd|th)? turn(?: in (?:a|the) (?:fight|battle))?, "
                      r"[^.]*?\b(?:steps through|escapes|vanishes|disappears|is gone)\b")
REFRESH_RE = re.compile(r"The first time (?:it|the [\w' -]+?) is reduced to half its hit points or fewer, its ([A-Z][\w' -]+?) recharges")


def _base(name: str) -> str:
    return re.sub(r"\s*\(.*?\)", "", name or "").strip().lower()


def lair_actions(m: Optional[dict]) -> list:
    """The stat block's lair actions as entries like its actions: [{'name': 'Lair: Magma erupts', 'text'}] from the bullets
    of its lair text (none when it has no lair actions)."""
    text = (m or {}).get("lair") or ""
    if not re.search(r"lair actions?", text, re.I):
        return []
    out = []
    for bullet in re.findall(r"•\s*([^\n•]+)", text):
        bullet = bullet.strip()
        if len(bullet) < 25:
            continue
        head = re.match(r"((?:[A-Z][\w'-]*\s){1,4})(?=(?:The|A|An|Each|One|Up|Until|[A-Z][a-z]+ (?:of|in|on)) )", bullet)  # "Chaotic Aura The faerie..."
        if head and len(head.group(1).split()) <= 4 and not re.match(r"(?:The|A|An|Each|One|Up|Until)\b", head.group(1)):
            name, body = head.group(1).strip(), bullet[head.end():].strip()
        else:
            name, body = f"action {len(out) + 1}", bullet      # untitled bullets: numbered, the text says what each does
        nm = f"Lair {name}" if name.startswith("action") else f"Lair: {name}"
        while any(o["name"] == nm for o in out):
            nm += "'"
        out.append({"name": nm, "text": body})
    return out


class TraitsMixin:
    def _traits(self, c: Optional[dict]) -> list:
        if not c or c["kind"] == "pc" or c.get("form"):
            return []
        return (self._monster(c) or {}).get("traits") or []

    def _lair_actions(self, c: Optional[dict]) -> list:
        if not c or c["kind"] == "pc" or c.get("form") or c.get("summoned_by") is not None:
            return []
        return lair_actions(self._monster(c))

    def _lair_why(self, c: dict, entry: Optional[str] = None) -> Optional[str]:
        """Lair actions: one a round (on initiative count 20, the DM's call when), only in a fight. An entry that casts a spell
        several times ("casts darkness four times") stays open for the rest of its casts."""
        if self.b.get("status") != "active":
            return "Only in a fight"
        more = c.get("lair_more") or {}
        if c.get("lair_round") == self.b.get("round") and not (more.get("round") == self.b.get("round") and more.get("left", 0) > 0
                                                              and entry in (None, more.get("entry"))):
            return "One lair action a round"
        if not self._alive(c):
            return "It's down"
        return None

    def _trait(self, c: Optional[dict], *names: str) -> Optional[dict]:
        return next((t for t in self._traits(c) if _base(t.get("name")) in names), None)

    def _worded(self, c: Optional[dict], rx) -> Optional[dict]:
        """The first trait whose text says it this way (whatever its name)."""
        return next((t for t in self._traits(c) if rx.search(t.get("text") or "")), None)

    def _once_per_turn(self, c: dict, key: str) -> bool:
        """True the first time this turn (and marks it used)."""
        mark = [self.b.get("round"), self.b.get("turn")]
        used = c.setdefault("trait_used", {})
        if used.get(key) == mark:
            return False
        used[key] = mark
        return True

    # ------------------------------------------------------------------ movement for a charge
    def _note_run(self, c: dict, start, end, tiles=None):
        """A finished walk: kept as this turn's run (joined to the last one when it carries on from where that ended)."""
        t = c.get("turn")
        if not start or not end:
            return
        tiles = [list(p) for p in tiles or (start, end)]
        if t is None:                                       # a legendary action before its first turn
            c["run_off"] = {"from": list(start), "to": list(end), "tiles": tiles}
            return
        run = t.get("run")
        if run and list(run.get("to") or []) == list(start):
            run["to"] = list(end)
            run["tiles"] = (run.get("tiles") or [run["from"]]) + tiles[1:]
        else:
            t["run"] = {"from": list(start), "to": list(end), "tiles": tiles}

    def _run_of(self, c: dict) -> Optional[dict]:
        return c.get("run_off") if c.get("turn") is None else c["turn"].get("run")

    @staticmethod
    def _run_straight(run: dict) -> bool:
        """No tile of the run more than a square off the line from its start to its end (an older run without its tiles: yes)."""
        (x0, y0), (x1, y1) = run["from"], run["to"]
        lx, ly = x1 - x0, y1 - y0
        ln = (lx * lx + ly * ly) ** .5
        if not ln:
            return False
        return all(abs((x - x0) * ly - (y - y0) * lx) / ln <= 1.0 for x, y in run.get("tiles") or ())

    def _run_ft(self, c: dict) -> int:
        """How far this turn's run has gone in a straight line (0 when it bent)."""
        run = self._run_of(c)
        if not run or not self._run_straight(run):
            return 0
        return G.distance_ft(run["from"], 1, run["to"], 1)

    def _run_end_strikes(self, c: dict) -> list:
        """A run that ends next to a foe: Headfirst Charge, Skewering Charge, an avoral's Dive Attack ("moves at least 30 feet in a
        straight line toward a creature and ends within 5 feet of it, that creature must succeed on a DC 17 Strength saving throw or
        take 14 (4d6) bludgeoning damage and have the prone condition"). Once a turn each. Strikes to run (built, not run)."""
        from .standard import SIZES
        run = self._run_of(c)
        if not run or not c.get("pos") or self.b.get("status") != "active":
            return []
        out = []
        for t in self._traits(c):
            text = t.get("text") or ""
            m = END_RE.search(text)
            if not m or not self._form_ok(c, t["name"]) or self._run_ft(c) < int(m.group(1)):
                continue
            if re.search(r"\bis flying\b", text[:m.end()]) and not self._speeds(c).get("fly"):
                continue
            size = re.search(r"\b(Tiny|Small|Medium|Large|Huge) or smaller\b", m.group(0))
            span = c.get("span") or 1
            foes = [o for o in self.b["combatants"] if o is not c and o.get("pos") and not self._is_out(o) and self._hostile(c, o)
                    and self._dist(c, o) <= 5 and not (size and SIZES.index(self._size_of(o)) > SIZES.index(size.group(1)))]
            foes.sort(key=lambda o: (G.distance_ft(run["to"], span, o["pos"], o.get("span") or 1)
                                     >= G.distance_ft(run["from"], span, o["pos"], o.get("span") or 1), self._dist(c, o)))
            if not foes or G.distance_ft(run["to"], span, foes[0]["pos"], foes[0].get("span") or 1) \
                    >= G.distance_ft(run["from"], span, foes[0]["pos"], foes[0].get("span") or 1):
                continue                                    # it ran past or away from them
            _pre, post, sv = CR.split_save(text)
            if not sv or not self._once_per_turn(c, "run_end:" + t["name"]):
                continue
            terms = self._save_terms(post)
            out.append(self._strike(c, re.sub(r"\s*\(.*?\)", "", t["name"]), [foes[0]["id"]], mode="save", magical=False,
                                    parts=CR.save_damage(post), sv=dict(terms, ab=sv[0], dc=sv[1] or self._spell_dc(c), half=False)))
        return out

    _SPACE_ENTRY = re.compile(r"(?:When [\w' -]+? enters any enemy's space for the first time on a turn|The first time on a turn that [\w' -]+? enters a "
                              r"creature's space[^.,]*), (?:the enemy|the creature) must succeed on a DC (\d+) (Strength|Dexterity|Constitution) saving "
                              r"throw or be knocked prone")

    def _space_entry_strikes(self, c: dict, after) -> list:
        """Duke Zalto's Tackle, an unspeakable horror's Relentless Stride: the first foe whose space the mover enters on a turn makes a
        saving throw or falls prone. Strikes to run (built, not run)."""
        out = []
        if not c.get("pos"):
            return out
        for t in self._traits(c):
            m = self._SPACE_ENTRY.search(t.get("text") or "")
            if not m or not self._form_ok(c, t["name"]):
                continue
            foes = [o for o in self.b["combatants"] if o is not c and o.get("pos") and not self._is_out(o) and self._hostile(c, o)
                    and G.footprint(o["pos"], o.get("span") or 1) & after]
            if foes and self._once_per_turn(c, "space_entry:" + t["name"]):
                out.append(self._strike(c, t["name"], [foes[0]["id"]], mode="save", parts=[], magical=False,
                                        sv={"ab": CR.ABILITIES[m.group(2).lower()], "dc": int(m.group(1)), "half": False, "conds": ["Prone"]}))
        return out

    def _charged(self, att: dict, tgt: dict, feet: int) -> bool:
        run = self._run_of(att)
        if not run or not tgt.get("pos") or not self._run_straight(run):
            return False
        span, tspan = att.get("span") or 1, tgt.get("span") or 1
        moved = G.distance_ft(run["from"], 1, run["to"], 1)    # how far its corner travelled (a Large lion's boxes overlap after 20 ft)
        return moved >= feet and G.distance_ft(run["to"], span, tgt["pos"], tspan) < G.distance_ft(run["from"], span, tgt["pos"], tspan)

    # ------------------------------------------------------------------ attack rolls
    def _trait_modes(self, att: dict, tgt: dict, a: dict) -> list:
        """[(mode, why)] the attacker's or target's traits add to an attack roll."""
        out = []
        frenzy = self._trait(att, "blood frenzy") or self._worded(att, FRENZY_RE)       # a drowner's Corpse Frenzy
        if a.get("melee") and frenzy and self._hp_of(tgt) < self._max_hp(tgt):
            out.append(("adv", _base(frenzy["name"]).title()))
        if self._trait(att, "ambusher", "assassinate") and self.b.get("round") == 1 and not tgt.get("had_turn"):
            out.append(("adv", "Ambusher" if self._trait(att, "ambusher") else "Assassinate"))
        grip = self._trait(att, "grappler") or self._worded(att, GRAPPLER_RE)            # the Butcher's Grip
        if grip and any((e.get("mods") or {}).get("grappler") == att["id"] for e in tgt.get("effects") or []):
            out.append(("adv", re.sub(r"\s*\(.*?\)", "", grip["name"])))
        haze = self._worded(tgt, HAZE_RE)                       # a noonwraith's Noonday Haze: the map's light where it floats
        if haze and tgt.get("pos") and any(V.light_at(self._terrain(), t, self.b.get("map", {}).get("light", "bright"), self._live_zones()) == "bright"
                                           for t in G.footprint(tgt["pos"], tgt.get("span") or 1)):
            out.append(("dis", re.sub(r"\s*\(.*?\)", "", haze["name"])))
        wf = self._trait(att, "wounded fury")              # a quaggoth at 10 hit points or fewer
        g = re.search(r"has (\d+) hit points or fewer", (wf or {}).get("text") or "")
        if wf and g and self._hp_of(att) <= int(g.group(1)):
            out.append(("adv", "Wounded Fury"))
        if self._trait(att, "draconic devotion") and any(o is not att and not self._hostile(o, att) and self._alive(o)
                                                         and str((self._monster(o) or {}).get("type") or "").lower() == "dragon" and self._sees(att, o)
                                                         for o in self.b["combatants"]):
            out.append(("adv", "Draconic Devotion"))         # it can see a friendly dragon
        dis = self._trait(tgt, "displacement")              # a displacer beast's illusion, off for a while after a hit
        if dis and not K.incapacitated(self._conds(tgt)) and (self.b.get("round") or 0) > tgt.get("displaced_hit", -9) + 1:
            out.append(("dis", "Displacement"))
        return out

    # ------------------------------------------------------------------ damage on a hit
    _AMMO_WORDS = {"half-dozen": 6, "dozen": 12, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "ten": 10}

    def _slaying_ammo(self, att: dict, tgt: dict, R: dict, t: dict) -> list:
        """A trait with a few bolts that slay one kind of creature: "has a half-dozen bolts of undead slaying. If he strikes an Undead
        creature with one of these magic bolts, it must make a DC 17 Constitution saving throw, taking an extra 33 (6d10) piercing damage
        on a failed save, or half as much extra damage on a successful one." Each hit on that kind spends a bolt. Damage parts."""
        text = t.get("text") or ""
        m = re.search(r"strikes an? (\w+) creature with one of these magic (?:bolts|arrows), it must make a DC (\d+) (\w+) saving throw, taking an extra "
                      r"(?:\d+ \()?(\d+d\d+)\)? (\w+) damage on a failed save, or half as much", text)
        if not m:
            return []
        kind = "humanoid" if self._sheet(tgt) and not tgt.get("form") else str((self._monster(tgt) or {}).get("type") or "").lower()
        if m.group(1).lower() not in kind:
            return []
        n = re.search(r"has (?:an? )?(half-dozen|dozen|\d+|one|two|three|four|five|six|ten) (?:of )?(?:\w+ )?(?:bolts|arrows)", text)
        left = att.setdefault("ammo_left", {})
        if t["name"] not in left:
            left[t["name"]] = int(n.group(1)) if n and n.group(1).isdigit() else self._AMMO_WORDS.get(n.group(1) if n else "", 1)
        if left[t["name"]] <= 0:
            return []
        left[t["name"]] -= 1
        res = self._saving_throw(tgt, CR.ABILITIES[m.group(3).lower()], int(m.group(2)), label=t["name"])
        rolled = self._roll_parts([[m.group(4), m.group(5).lower()]], bool(R["cur"].get("crit")))
        out = [[amount if not res["ok"] else amount // 2, dtype] for amount, dtype in rolled]
        self._line(R, f"{t['name']}: {tgt['name']} {m.group(3).upper()[:3]} save {res['total']} vs DC {m.group(2)} - "
                      + ("half the extra damage" if res["ok"] else "the full extra damage") + f" ({left[t['name']]} bolts left)", t["name"])
        return out

    def _trait_hit_parts(self, att: dict, tgt: dict, R: dict) -> list:
        """Extra damage parts from the attacker's traits for this hit (the charge's save goes on as a rider)."""
        a = R["atk"]
        if self._trait(tgt, "displacement"):                 # hit: the illusion is off until the end of its next turn
            tgt["displaced_hit"] = self.b.get("round") or 0
        if not self._traits(att) or not a.get("parts"):
            return []
        dtype = a["parts"][0][1]
        out = []
        for t in self._traits(att):
            name, text = _base(t.get("name")), t.get("text") or ""
            if name == "martial advantage" and a.get("weapon"):
                ally = any(o is not att and o is not tgt and not self._hostile(o, att) and self._can_act(o) and o.get("pos")
                           and self._dist(o, tgt) <= 5 for o in self.b["combatants"])
                if ally and self._once_per_turn(att, "martial advantage"):
                    out += self._trait_extra(R, att, t, dtype)
            elif name == "sneak attack" and a.get("weapon") and R["cur"].get("mode") != "dis":
                ally = any(o is not att and o is not tgt and not self._hostile(o, att) and self._can_act(o) and o.get("pos")
                           and self._dist(o, tgt) <= 5 for o in self.b["combatants"])
                if (R["cur"].get("mode") == "adv" or ally) and self._once_per_turn(att, "sneak attack"):
                    out += self._trait_extra(R, att, t, dtype)
            elif name == "surprise attack" and self.b.get("round") == 1 and not tgt.get("had_turn") \
                    and self._once_per_turn(att, "surprise attack"):
                out += self._trait_extra(R, att, t, dtype)
            elif name == "wounded fury" and a.get("melee") and re.search(r"has (\d+) hit points or fewer", text) \
                    and self._hp_of(att) <= int(re.search(r"has (\d+) hit points or fewer", text).group(1)):
                out += self._trait_extra(R, att, t, dtype)     # "deals an extra 7 (2d6) damage to any target it hits with a melee attack"
            elif re.search(r"once per turn, if [\w ]+ makes a weapon attack with advantage on the attack roll and hits", text, re.I) \
                    and a.get("weapon") and R["cur"].get("mode") == "adv" and self._once_per_turn(att, name):
                out += self._trait_extra(R, att, t, dtype)          # a dragonclaw's Fanatic Advantage
            elif a.get("weapon") and not a.get("melee") and re.search(r"strikes an? \w+ creature with one of these magic (?:bolts|arrows)", text):
                out += self._slaying_ammo(att, tgt, R, t)          # Borivik's Bolts of Undead Slaying
            elif CHARGE_RE.search(text):
                m = CHARGE_RE.search(text)
                weapon = m.group(2).lower().replace("its ", "").strip()
                label = (R.get("label") or "").lower()
                fits = weapon in ("melee weapon", "weapon") and a.get("melee") or weapon.rstrip("s") in label or label.rstrip("s") in weapon
                if not fits or not self._charged(att, tgt, int(m.group(1))):
                    continue
                if ("dives" in m.group(0).lower() or re.search(r"\bis flying\b", text[:m.end()])) and not self._speeds(att).get("fly"):
                    continue
                if not self._once_per_turn(att, "charge"):
                    continue
                out += self._trait_extra(R, att, t, dtype)
                _pre, post, sv = CR.split_save(text)
                if sv and re.search(r"knocked prone|prone condition", post, re.I):
                    R.setdefault("smite_riders", []).append({"rider": {"ab": sv[0], "prone": True}, "name": t["name"], "target": tgt["id"],
                                                             "dc": sv[1] if sv[1] else self._spell_dc(att)})
                scare = re.search(r"the target is (frightened|stunned|blinded|deafened|poisoned|prone)\b([^.]*)", text[m.end():], re.I) if not sv else None
                if scare and self._alive(tgt):                 # a pterafolk's Terror Dive: "the target is frightened until the end of its next turn"
                    cond = scare.group(1).capitalize()
                    if cond == "Prone":
                        self._cond(tgt, "Prone", True)
                    else:
                        until = CR.until_of(scare.group(0))
                        self._effect_on(tgt, re.sub(r"\s*\(.*?\)", "", t["name"]), [cond], None, None, None, None if until else 1, att["name"], None,
                                        None, att["id"], until=self._until(until, att, tgt) if until else None)
                    self._line(R, f"{t['name']}: {tgt['name']} is {cond.lower()}", t["name"])
                f = FOLLOW_RE.search(text)
                if f and att.get("turn") is not None:          # Pounce: a bite at the prone target as a bonus action
                    att["turn"]["follow_up"] = {"attack": f.group(1), "target": tgt["id"], "prone": True, "why": re.sub(r"\s*\(.*?\)", "", t["name"])}
        return out

    def _trait_kill(self, by: Optional[dict], victim: dict):
        """A creature dropped to 0 by this monster on its turn: Rampage (half its speed and a bite as a bonus action),
        Imix's Blessing and its kin (temporary hit points)."""
        if not by or by is victim or self.b.get("turn") != by.get("id") or not self._hostile(by, victim):
            return
        for t in self._traits(by):
            text = t.get("text") or ""
            if re.search(r"reduces a creature to 0 hit points with a melee attack on its turn", text):
                f = re.search(r"make an? (\w+) attack", text)
                if f and by.get("turn") is not None:
                    by["turn"]["follow_up"] = {"attack": f.group(1), "target": None, "move": True, "why": re.sub(r"\s*\(.*?\)", "", t["name"])}
                    self._say(f"{by['name']}: {t['name']} - a bonus-action {f.group(1).lower()} attack is open")
            m = re.search(r"reduces an? (?:enemy|creature) to 0 hit points, [\w ]+ gains (\d+) temporary hit points", text)
            if m:
                self._give_temp(by, int(m.group(1)))
                self._say(f"{by['name']} gains {m.group(1)} temporary hit points ({t['name']})")

    def _war_magic(self, c: dict, sp: dict) -> None:
        """War Magic ("When the githyanki uses its action to cast a spell, it can make one weapon attack as a bonus action"; for
        Dralmorrer Borngray a cantrip): opens the weapon attack as this turn's bonus-action follow-up."""
        if c.get("turn") is None or c["turn"].get("follow_up"):
            return
        t = next((t for t in self._traits(c) if t.get("name", "").lower() == "war magic" and re.search(r"cast an? (?:cantrip|spell)", t.get("text") or "")), None)
        if not t or sp["level"] > 0 and re.search(r"cast a cantrip", t.get("text") or ""):
            return
        acts = [e for e in (self._monster(c) or {}).get("actions") or [] if re.search(r"Weapon Attack:", e.get("text") or "")]
        weapon = next((e for e in acts if re.search(r"Melee", e["text"])), acts[0] if acts else None)
        if weapon:
            c["turn"]["follow_up"] = {"attack": weapon["name"], "target": None, "why": "War Magic"}
            self._say(f"{c['name']}: War Magic - a bonus-action {weapon['name'].lower()} attack is open")

    def trait_options(self, c: dict) -> List[dict]:
        """Bar entries a monster's traits open: a Pounce or Rampage follow-up attack, Fey Step's teleport, Superior
        Invisibility: [{'id', 'name', 'cost', 'target', 'tip', 'range'}]."""
        out = []
        fu = (c.get("turn") or {}).get("follow_up")
        if fu:
            tgt = {"type": "fixed", "id": fu["target"]} if fu.get("target") else {"type": "creature", "count": 1, "enemies": True}
            out.append({"id": "trait:follow_up", "name": f"{fu['attack']} ({fu['why']})", "cost": "bonus", "target": tgt,
                        "tip": f"{fu['why']}: one {fu['attack'].lower()} attack as a bonus action", "range": None})
        lm = c.get("leg_move")
        if lm and lm.get("feet"):                              # a Wing Attack's flight, right after it
            out.append({"id": "trait:legmove", "name": f"Fly ({lm['name']})", "cost": "free", "target": {"type": "point", "teleport": lm["feet"]},
                        "tip": f"{lm['name']}: then fly up to {lm['feet']} ft", "range": lm["feet"]})
        for t in self._traits(c):
            text = t.get("text") or ""
            m = re.search(r"as a bonus action, (?:the |it )?[\w' -]*?can (?:magically )?teleport(?:,? along with any equipment (?:it is|he is|she is) wearing or carrying,)? "
                          r"up to (\d+) feet", text, re.I)
            m = m or re.search(r"as a bonus action, (?:the |it )?[\w' -]*?can step into a shadow within 5 feet of (?:it|itself) and magically appear in an "
                               r"unoccupied space within 5 feet of a second shadow that is up to (\d+) feet away", text, re.I)   # a shadow horror's Shadow Stride
            if m:
                out.append({"id": f"trait:teleport:{m.group(1)}", "name": re.sub(r"\s*\(.*?\)", "", t["name"]), "cost": "bonus",
                            "target": {"type": "point", "teleport": True}, "tip": text[:300], "range": int(m.group(1))})
            if re.search(r"as a bonus action, (?:the |it )?[\w' -]*?can magically turn invisible", text, re.I):
                out.append({"id": "trait:invisible", "name": re.sub(r"\s*\(.*?\)", "", t["name"]), "cost": "bonus", "target": {"type": "self"},
                            "tip": text[:300], "range": None})
        return out

    def use_trait(self, cid: int, key: str, target_id: Optional[int] = None, point=None, adv: Optional[str] = None) -> str:
        with self.lock:
            self._busy()
            c = self._find(cid)
            name = next((o["name"] for o in self.trait_options(c) if o["id"] == f"trait:{key}"), None)
            if not name:
                raise ServiceError("That isn't open now.")
            if key == "follow_up":
                fu = c["turn"]["follow_up"]
                tgt = self._target(fu.get("target") or target_id)
                if fu.get("prone") and "Prone" not in self._conds(tgt):
                    raise ServiceError(f"{tgt['name']} isn't prone.")
                _s, e = self._entry_section(c, fu["attack"])
                e = e or next((x for x in (self._monster(c) or {}).get("actions") or [] if x["name"].lower().startswith(fu["attack"].lower())), None)
                if not e:
                    raise ServiceError(f"{c['name']} has no {fu['attack']} attack.")
                S = self._monster_strike(c, tgt, e["name"], e["text"], adv=adv, label=f"{e['name']} ({fu['why']})")
                if c.get("pos") and tgt.get("pos"):
                    try:
                        S["atk"] = self._check_reach(c, tgt, S["atk"])
                    except ServiceError:
                        if not fu.get("move"):
                            raise
                        # Rampage: "move up to half its speed and make a bite attack" - walk there first, then bite
                        mv = {"feet": self._speed(c) // 2, "free": False,
                              "atks": [{"entry": e["name"], "each": False, "adv": adv == "adv", "extra": [], "noncrit": False}]}
                        out = self._move_attack_do(c, fu["why"], "bonus_actions", fu["why"], mv, None, tgt["id"], None, None)
                        c["turn"].pop("follow_up", None)
                        return out
                self._pay(c, "bonus", name)
                c["turn"].pop("follow_up", None)
                out = self._run_r(S)
                self._commit()
                return out
            if key.startswith("teleport:"):
                if not point:
                    raise ServiceError("Pick where to appear.")
                x, y = int(point[0]), int(point[1])
                if c.get("pos") and G.distance_to_tile(c["pos"], c.get("span") or 1, (x, y)) > int(key.split(":")[1]):
                    raise ServiceError("That's too far.")
                self._pay(c, "bonus", name)
                self.teleport(cid, x, y)
                line = f"{c['name']} steps through the Feywild ({name})" if "fey" in name.lower() else f"{c['name']} teleports ({name})"
                self._commit(line)
                return line
            if key == "legmove":
                lm = c["leg_move"]
                plan = self._move_plan(c, lm["feet"], point, lm["free"], lm["name"])
                c.pop("leg_move", None)
                self._move_walk(c, lm["name"], plan)
                self._commit(f"{c['name']} flies off ({lm['name']})")
                return f"{c['name']} flies off ({lm['name']})"
            if key == "invisible":
                self._pay(c, "bonus", name)
                self._effect_on(c, name, ["Invisible"], None, None, None, None, c["name"], {"ends_on": ["attack", "cast"]}, None, c["id"])
                self._commit(f"{c['name']} turns invisible ({name})")
                return f"{c['name']} turns invisible"
            raise ServiceError("That isn't open now.")

    def _trait_extra(self, R: dict, att: dict, t: dict, dtype: str) -> list:
        m = EXTRA_RE.search(t.get("text") or "")
        name = re.sub(r"\s*\(.*?\)", "", t["name"])
        self._line(R, f"{att['name']}: {name}", name)
        if not m:
            return []
        dice = (m.group(1) or m.group(3)).replace(" ", "")
        return [[dice, (m.group(2) or m.group(4) or dtype or "").lower()]]

    _USES_BUT = re.compile(r"(?:With an? [a-z ]+, )?(?:the [a-z' -]{1,30}|[A-Z][\w']{0,30}) uses [A-Z][\w' -]+?, but on a failed save, ", re.I)

    def _referenced_action(self, c: dict, name: str, text: str) -> Optional[dict]:
        """A legendary (or other) action that only points at another entry: "The dragon makes a tail attack", "Auril uses
        Touch of Frost", "makes one attack with its hooves": that entry (with 'n', how many attacks), or None."""
        if re.search(r"[+-]\d+ to hit|saving throw|\d+d\d+", text) and not self._USES_BUT.match(text):
            return None                                     # it says itself what it does (a Curse of the Evil Eye: "uses Evil Eye, but on a failed save...")
        m = self._monster(c) or {}
        pool = [e for sec in ("actions", "bonus_actions", "reactions") for e in m.get(sec) or []]
        if re.search(r"makes (?:one|an?) (?:melee |ranged )?(?:weapon )?attack\b", text, re.I):     # "makes one weapon attack": its first
            first = next((e for e in pool if re.search(r"Weapon Attack:", e.get("text") or "")), None)
            if first:
                return dict(first, n=1)
        wants = []
        for g in re.finditer(r"makes (one|a|an|two|three|four|five|six) (?:melee |ranged )?(?:attack with (?:its|her|his) )?([\w' -]+?)(?: weapon)?(?: attacks?)?"
                             r"(?:[.,;(]| against| or| and| with| that| using|$)", text, re.I):
            wants.append((g.group(2), {"two": 2, "three": 3, "four": 4, "five": 5, "six": 6}.get(g.group(1).lower(), 1)))
        for g in re.finditer(r"\buses (?:its |her |his |their )?([A-Z][\w' -]+?)(?: action)?(?:[.,;]| or| and| on|$)", text):
            wants.append((g.group(1), 1))
        for g in re.finditer(r"\brecharges (?:its |her |his |their )?([A-Z][\w' -]+?) and uses it", text):    # "recharges its Mind Blast and uses it"
            wants.append((g.group(1), 1))
        for want, n in wants:
            w = want.lower().strip()
            w1 = w.rstrip("s")
            e = next((e for e in pool if _base(e.get("name")) == w), None) or \
                next((e for e in pool if _base(e.get("name")).rstrip("s") == w1 or _base(e.get("name")).startswith(w1)), None) or \
                next((e for e in pool if w1 and w1 in _base(e.get("name"))), None)
            if e and not _base(e.get("name")) == "multiattack":
                return dict(e, n=n)
        return None

    def _spell_immune(self, tgt: dict, R: dict) -> Optional[str]:
        """Limited Magic Immunity (spells of 6th level or lower don't touch a rakshasa), Spell Immunity (a helmed horror's
        listed spells): the line saying so, or None."""
        if not R.get("spell") or not self._traits(tgt):
            return None
        sp = rules.spell(re.sub(r" \([^)]*\)$", "", R.get("label") or ""))
        if not sp:
            return None
        for t in self._traits(tgt):
            text = t.get("text") or ""
            m = re.search(r"can't be affected or detected by spells of (\d)(?:st|nd|rd|th) level or lower", text)
            if m and max(sp["level"], int(R.get("slot_level") or 0)) <= int(m.group(1)):
                return f"{tgt['name']} is untouched by {sp['name']} ({t['name']})"
            m = re.search(r"is immune to ([\w ,']+?)(?:\.|$)", text) if _base(t.get("name")) == "spell immunity" else None
            if m and sp["name"].lower() in [x.strip().lower() for x in re.split(r",\s*(?:and\s+)?|\s+and\s+", m.group(1))]:
                return f"{tgt['name']} is immune to {sp['name']} ({t['name']})"
        return None

    # ------------------------------------------------------------------ turn start, dropping to 0
    def _trait_turn_start(self, c: dict):
        """Reckless: a monster always takes it (advantage on its melee attacks, attacks against it too) until its next turn.
        A hero's Holy Avenger aura is renewed here too."""
        self._item_auras(c)
        if self._trait(c, "reckless") and self._alive(c):
            self._effect_on(c, "Reckless", [], None, None, None, None, c["name"], {"str_melee_adv": True, "attacks_against": "adv"}, None,
                            c["id"], until={"start": c["id"]})
        for t in self._traits(c):                               # Whispering Aura: its own turn starts, those around it save
            text = t.get("text") or ""
            m = re.match(r"At the start of each of (?:the )?[\w' -]+?'s turns, each creature (?:of its choice )?within (\d+) feet of (?:it|the [\w ]+?) "
                         r"must succeed on a", text)
            hurt = None if m else re.search(r"each creature within (\d+) feet of (?:it|her|him|itself|[\w' -]+?) takes (\d+(?: \(\d+d\d+(?: ?[+-] ?\d+)?\))?) (\w+) damage", text)
            if hurt and re.search(r"start of each of (?:its|her|his|[\w' -]+?'s) turns", text) and c.get("pos") and self._can_act(c) \
                    and re.fullmatch(CR._TYPES, hurt.group(3).lower()):       # Frigid Aura, Fire Aura: no save, they just burn
                ids = [o["id"] for o in self.b["combatants"] if o is not c and o.get("pos") and self._hostile(o, c) and not self._is_out(o)
                       and self._dist(o, c) <= int(hurt.group(1))]
                if ids:
                    dice = re.search(r"\((\d+d\d+(?: ?[+-] ?\d+)?)\)", hurt.group(2))
                    S = self._strike(c, re.sub(r"\s*\(.*?\)", "", t["name"]), ids, mode="auto",
                                     parts=[[(dice.group(1) if dice else hurt.group(2)).replace(" ", ""), hurt.group(3).lower()]], magical=True)
                    self._run_items(c, [S], t["name"])
                continue
            if not m or not c.get("pos") or not self._can_act(c):
                continue
            _pre, post, sv = CR.split_save(text)
            if not sv:
                continue
            ids = [o["id"] for o in self.b["combatants"] if o is not c and o.get("pos") and self._hostile(o, c) and not self._is_out(o)
                   and self._dist(o, c) <= int(m.group(1))]
            if ids:
                S = self._strike(c, re.sub(r"\s*\(.*?\)", "", t["name"]), ids, mode="save",
                                 sv={"ab": sv[0], "dc": sv[1] or self._spell_dc(c), "half": "half as much" in post.lower(),
                                     "conds": CR.conditions_in(post)}, parts=CR.damage_parts(post), magical=True)
                self._run_items(c, [S], t["name"])

    def _enduring_response(self, c: dict, types):
        """Borivik's Enduring Response (a reaction): taking acid, cold, fire, lightning or thunder damage gives it immunity to that type until
        the start of its next turn, and its first Shortsword hit on that turn takes an extra 3d6 of the type."""
        if c["kind"] == "pc" or c.get("form") or not types:
            return
        r = next((x for x in (self._monster(c) or {}).get("reactions") or []
                  if re.search(r"gains immunity to that damage type until the start of (?:his|her|its) next turn", x.get("text") or "")), None)
        if not r or any(e["name"] == r["name"] for e in c.get("effects") or []) or not self._may_react(c) or self._react_mode(c, "enduring_response") == "never":
            return
        m = re.match(r"When [\w' -]+ takes ([\w, ]+?) damage,", r["text"])
        pick = next((t for t in sorted(types) if m and re.search(r"\b%s\b" % t, m.group(1))), None)
        if not pick:
            return
        self._spend_reaction(c, r["name"])
        self._effect_on(c, r["name"], [], None, None, None, None, c["name"], {"immune": [pick]}, None, c["id"], until={"start": c["id"]})
        bonus = re.search(r"first time (?:he|she|it) hits with an? (\w+) attack on (?:his|her|its) next turn, the target takes an extra (?:\d+ \()?(\d+d\d+)\)? of the triggering",
                          r["text"])
        if bonus:
            self._effect_on(c, f"{r['name']} ({bonus.group(1)})", [], None, None, None, None, c["name"],
                            {"dmg": (bonus.group(2), pick), "once": True, "melee_only": True}, None, c["id"],
                            until={"end": c["id"], "skip": 1 if self.b.get("turn") == c["id"] else 0})
        self._say(f"{c['name']} reacts ({r['name']}): immune to {pick} until the start of its next turn")

    def _trait_hurt(self, c: dict, types, taken: int = 0):
        """Aversion to Fire: fire damage gives the monster disadvantage on attack rolls until the end of its next turn.
        `taken`: what it just lost (a counter ward's big hit, _trait_wounds)."""
        self._enduring_response(c, types)
        self._trait_wounds(c, taken)
        for t in self._traits(c):
            m = re.search(r"If [\w ]+ takes (\w+) damage, it has disadvantage on attack rolls", t.get("text") or "")
            if m and m.group(1) in types and not any(e["name"] == t["name"] for e in c.get("effects") or []):
                self._effect_on(c, t["name"], [], None, None, None, None, c["name"], {"attacks_with": "dis"}, None, c["id"],
                                until={"end": c["id"], "skip": 1 if self.b.get("turn") == c["id"] else 0})
            s = re.search(r"If [\w ]+ takes (\w+) damage, it (?:suffers|has|is) [^:.]*?until the end of its next turn:? ?(.*)", t.get("text") or "", re.S)
            if s and s.group(1) in types and not any(e["name"] == t["name"] for e in c.get("effects") or []):
                body, mods = s.group(2).lower(), {}             # a froghemoth's Shock Susceptibility: lightning slows it
                if "speed is halved" in body:
                    mods["speed_mult"] = .5
                pen = re.search(r"[−-](\d+) penalty to ac and (strength|dexterity|constitution|intelligence|wisdom|charisma) saving throws", body)
                if pen:
                    mods["ac"] = -int(pen.group(1))
                    mods["save_ab"] = {CR.ABILITIES[pen.group(2)]: -int(pen.group(1))}
                dis = re.search(r"disadvantage on (strength|dexterity|constitution|intelligence|wisdom|charisma) saving throws", body)
                if dis:
                    mods["save_dis"] = [CR.ABILITIES[dis.group(1)]]
                if re.search(r"can't (?:use|take) reactions", body):
                    mods["no_reactions"] = True
                if re.search(r"can't use multiattack|either an action or a bonus action, not both", body):
                    mods["one_action"] = True
                if mods:
                    self._effect_on(c, t["name"], [], None, None, None, None, c["name"], mods, None, c["id"],
                                    until={"end": c["id"], "skip": 1 if self.b.get("turn") == c["id"] else 0})
                    self._say(f"{c['name']}: {t['name']} - slowed until the end of its next turn")

    # ------------------------------------------------------------------ wounds, counters, leaving at a set turn
    def _trait_wounds(self, c: dict, taken: int):
        """A hit read against its own traits: Flaring Eye ("The first time the bies is reduced to half its hit points or fewer,
        its Hypnotic Eye recharges") and a counter ward (Seven Radiances: 15 or more damage at once strips one; when the last
        goes it is stunned until the end of its next turn, if the text says so)."""
        for t in self._traits(c):
            text = t.get("text") or ""
            rf = REFRESH_RE.search(text)
            if rf and not c.get("bloodied_once") and 0 < self._hp_of(c) <= self._max_hp(c) // 2:
                c["bloodied_once"] = True
                key = next((k for k in (c.get("spent") or {}) if k.lower() == rf.group(1).lower()), None)
                if key:
                    c["spent"].pop(key)
                self._say(f"{c['name']} is bloodied: {rf.group(1)} " + ("recharges" if key else "is ready") + f" ({t['name']})")
            ct = COUNTER_RE.search(text)
            if not ct or taken < int(ct.group(2)) or self._hp_of(c) <= 0 or self._counter_left(c, t) <= 0:
                continue
            lost = c.setdefault("counter_lost", {})
            lost[t["name"]] = int(lost.get(t["name"]) or 0) + 1
            left, word = self._counter_left(c, t), ct.group(1)
            if left:
                self._say(f"{c['name']} loses a {word} ({t['name']}): {left} left")
                continue
            self._say(f"{c['name']} loses its last {word} ({t['name']}): no more resistance")
            if re.search(r"loses its last \w+, it is stunned until the end of its next turn", text):
                self._effect_on(c, f"{t['name']} lost", ["Stunned"], None, None, None, None, c["name"], None, None, c["id"],
                                until={"end": c["id"], "skip": 1 if self.b.get("turn") == c["id"] else 0})
                self._say(f"{c['name']} is stunned until the end of its next turn ({t['name']})")

    def _counter_left(self, c: dict, t: dict) -> int:
        """How many of a counter ward's pieces are left: "cloaked in seven radiances" less those lost."""
        ct = COUNTER_RE.search(t.get("text") or "")
        if not ct:
            return 0
        n = re.search(r"\b(one|two|three|four|five|six|seven|eight|nine|ten|\d+) %ss\b" % re.escape(ct.group(1)), t["text"])
        total = (int(n.group(1)) if n.group(1).isdigit() else NUMBERS[n.group(1)]) if n else 1
        return max(0, total - int((c.get("counter_lost") or {}).get(t["name"]) or 0))

    def _trait_counters(self, c: dict) -> list:
        """A counter ward's resistance to all damage while any piece is left, as an effect-like entry (profile._gather_effects):
        'Seven Radiances (5 left)'."""
        out = []
        for t in self._traits(c):
            if "at least one" in (t.get("text") or "") and COUNTER_RE.search(t["text"]):
                left = self._counter_left(c, t)
                if left > 0:
                    out.append({"name": f"{_base(t['name']).title()} ({left} left)", "mods": {"resist": list(M.TYPES)},
                                "conditions": [], "trait": True})
        return out

    def _trait_turn_end(self, c: dict):
        """The end of a monster's own turn, counted: "At the end of its fourth turn, it steps through the portal and is gone"
        takes it off the map and out of the fight (no XP; its grapples and concentration end); any other "At the end of its
        third turn, ..." is said in the log for the DM."""
        if c["kind"] == "pc" or c.get("form") or self.b.get("status") != "active" or self._is_out(c) or self._fx(c, "escaped"):
            return
        said = [t for t in self._traits(c) if re.search(r"At the end of its \w+ turn", t.get("text") or "")]
        if not said:
            return
        n = c["turns_taken"] = int(c.get("turns_taken") or 0) + 1
        for t in said:
            for sent in re.split(r"(?<=\.)\s+", t["text"]):
                g = re.match(r"At the end of its (first|second|third|fourth|fifth|sixth|seventh|eighth|\d+)(?:st|nd|rd|th)? turn", sent)
                if not g or (int(g.group(1)) if g.group(1).isdigit() else NUMBERS[g.group(1)]) != n:
                    continue
                if not LEAVE_RE.match(sent):
                    self._say(f"{c['name']} ({t['name']}): {sent[g.end():].lstrip(' ,')}")
                    continue
                if c.get("concentrating"):
                    self._drop_conc(c, "left the battle")
                for o in self.b["combatants"]:
                    for e in [e for e in o.get("effects") or [] if (e.get("mods") or {}).get("grappler") == c["id"]]:
                        self._effect_off(o, e, f"{c['name']} is gone")
                self._vfx("blink", id=c["id"], at=c.get("pos"), to=c.get("pos"))
                c["pos"] = None
                self._effect_on(c, t["name"], [], None, None, None, None, c["name"], {"banished": True, "untargetable": True, "escaped": True},
                                None, c["id"])
                self._say(f"{c['name']} is gone ({t['name']}): it has left the battle")
                return

    def _trait_zero_hp(self, c: dict, dealt: int) -> bool:
        """Relentless (a boar: 1 hit point after a small enough blow, once) or a greatwyrm's Awakening (its hit points reset,
        its breath recharges, once). True when it stays up."""
        for t in self._traits(c):
            name, text = _base(t.get("name")), t.get("text") or ""
            used = c.setdefault("trait_spent", [])
            if name in used:
                continue
            m = re.search(r"takes (\d+) damage or less that would reduce it to 0 hit points, it is reduced to 1 hit point", text)
            if m and dealt <= int(m.group(1)):
                used.append(name)
                self._set_hp(c, 1)
                self._say(f"{c['name']} shrugs off the blow: 1 hit point ({t['name']})")
                return True
            if re.search(r"drops to 0 hit points[^.]*?transforms into a cloud of mist[^.]*?instead of falling unconscious", text):
                if (c.get("shape") or "").lower() == "mist":    # a vampire's Misty Escape: already mist, "if it can't transform, it is destroyed"
                    continue                                    # (no sunlight or running water on the map: it always can)
                used.append(name)
                self._set_hp(c, 1)                              # 1 hit point in its mist, free to float away
                self._utility_do(c, t["name"], {"kind": "shape", "to": "Mist"})
                self._say(f"{c['name']} dissolves into mist instead of falling ({t['name']}): 1 hit point")
                return True
            m = re.search(r"would be reduced to 0 hit points, its current hit point total instead resets to (\d+) hit points", text)
            if m:
                used.append(name)
                self._set_hp(c, min(int(m.group(1)), c.get("max_hp") or int(m.group(1))))
                if "recharges its Breath Weapon" in text:
                    for k in list((c.get("spent") or {}).keys()):
                        if "breath" in k.lower():
                            c["spent"].pop(k, None)
                self._say(f"{c['name']} awakens: back to {self._hp_of(c)} hit points ({t['name']})")
                return True
        return False
