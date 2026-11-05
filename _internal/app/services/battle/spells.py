"""Casting spells in battle, BG3 style: pick the spell, aim it (creatures, a point or a direction), and the battle checks
range, sight and the action economy, spends the slot, lets foes Counterspell, then plays it out.

    pc_spell(cid, 'Fireball', slot=3, point=[10.0, 6.0])           # a point (tile units)
    pc_spell(cid, 'Bless', targets=[4, 5, 6])                      # creatures
    pc_spell(cid, 'Magic Missile', targets=[4, 4, 7])              # darts: one id per dart
    pc_spell(cid, 'Burning Hands', point=[12.5, 5.5])              # a cone aimed at a point
    monster_cast(cid, 'Hold Person', dc=15, targets=[2])
    cast_check(cid, 'Fireball', 3, None, [10.0, 6.0])  -> {'ok', 'why', 'targets', 'tiles'}   (the aiming preview)
"""
import re
from typing import List, Optional

from ...rules import spellcasting as SC
from ...rules.data import rules
from ...rules.dice import roll_dice
from ..common import ServiceError
from . import combat_rules as CR
from . import conditions as K
from . import economy as EC
from . import geometry as G
from . import sight as V
from . import spell_effects as X
from . import spellbook as SB
from .constants import ACTIVE
from .resolve import DONE, NEXT, roll

ABILITY_NAMES = {"str": "Strength", "dex": "Dexterity", "con": "Constitution", "int": "Intelligence", "wis": "Wisdom", "cha": "Charisma"}

# "does so with advantage if you or your companions are fighting it" (Charm Person, Dominate Person, Modify Memory...)
_FIGHTING = re.compile(r"\bfighting (?:it|the creature|a creature)\b[^.]*advantage|advantage[^.]*\bfighting (?:it|the creature)\b", re.I)


def _max_dice(expr: str) -> int:
    """'2d8+3' at its highest: 19."""
    total = 0
    for sign, n, die, flat in re.findall(r"([+-]?)\s*(?:(\d*)d(\d+)|(\d+))", str(expr)):
        v = (int(n or 1) * int(die)) if die else int(flat)
        total += -v if sign == "-" else v
    return total


# the colour of a casting circle comes from the class giving the spell (any other: arcane)
MAGIC_SOURCE = {"Cleric": "divine", "Paladin": "divine", "Druid": "primal", "Ranger": "primal", "Bard": "song", "Monk": "ki"}

# spells that only work on some kinds of creature (PHB texts)
ONLY_ON = {"hold person": {"types": ["humanoid"]}, "charm person": {"types": ["humanoid"]}, "dominate person": {"types": ["humanoid"]},
           "crown of madness": {"types": ["humanoid"]}, "calm emotions": {"types": ["humanoid"]},
           "animal friendship": {"types": ["beast"], "max_int": 3}, "dominate beast": {"types": ["beast"]},
           "hold monster": {"not": ["undead"], "label": "Hold Monster"},
           "blight": {"not": ["undead", "construct"], "label": "Blight"},
           "abi-dalzim's horrid wilting": {"not": ["undead", "construct"], "label": "Abi-Dalzim's Horrid Wilting"},
           "phantasmal force": {"not": ["undead", "construct"], "label": "Phantasmal Force"},
           "sleep": {"not": ["undead"], "label": "Sleep"},
           "cause fear": {"not": ["construct", "undead"], "label": "Cause Fear"}, "command": {"not": ["undead"], "label": "Command"},
           "tasha's hideous laughter": {"min_int": 5, "label": "Tasha's Hideous Laughter"},     # Intelligence 4 or less: not affected
           "synaptic static": {"min_int": 3, "label": "Synaptic Static"}, "psychic scream": {"min_int": 3, "label": "Psychic Scream"}}

POTENT = ("Light Domain", "Knowledge Domain", "Arcana Domain", "Grave Domain", "Peace Domain")     # cantrips + Wisdom at 8th
HASTE_ACTIONS = ("Dash", "Disengage", "Hide", "Use an Object")   # what Haste's extra action may be (and the Attack action)

class SpellsMixin:
    # ---- small helpers shared with the old flows
    def _give_temp(self, c: dict, amount: int):
        amount += self._nf_temp_bonus(c) if amount > 0 else 0     # Boon of Bountiful Health: 5 more (newfeats.py)
        if c["kind"] == "pc":
            self.chars.set_temp_hp(c["character"], amount)
        else:
            c["temp_hp"] = max(c.get("temp_hp") or 0, amount)

    def _heal(self, c: dict, amount: int, revive: bool = False) -> bool:
        """Hit points back (False when nothing could be healed)."""
        if self._fx(c, "no_heal"):
            self._say(f"{c['name']} can't regain hit points right now")
            return False
        deathly = next((z for z in self._zones_at(c) if z.get("no_heal") and self._zone_affects(z, c)), None)
        if deathly is not None:                                # Dirge: no healing inside the emanation
            self._say(f"{c['name']} can't regain hit points inside {deathly['name']}")
            return False
        if self._dead(c) and not revive:                       # only a spell that raises the dead (Revivify...) helps now
            self._say(f"{c['name']} is dead: healing does nothing")
            return False
        if c["kind"] == "pc":
            self.chars.heal(c["character"], str(amount))
        else:
            c["hp"] = min(c["max_hp"], c["hp"] + amount)
        self._vfx("heal", id=c["id"], amt=int(amount))
        for e in [e for e, v in self._fxs(c, "ends_on") if "heal" in (v or []) and amount > 0]:
            if e in (c.get("effects") or []):
                self._effect_off(c, e, "healed")          # caltrops in the foot: until it regains hit points
        return True

    def _clear_conditions(self, c: dict, conds):
        for cond in list(self._conds(c)) if conds == "all" else conds:
            if conds == "all" or cond in conds:
                for eff in list(c.get("effects") or []):
                    if cond in eff["conditions"]:
                        self._effect_off(c, eff, "cured")
                self._cond(c, cond, False)

    WARDED_KINDS = ("celestial", "elemental", "fey", "fiend", "undead")

    def _warded_kind(self, c: dict) -> bool:
        """A celestial, elemental, fey, fiend or undead (Dispel Evil and Good)."""
        kind = str((self._monster(c) or {}).get("type") or "").lower() if not self._sheet(c) or c.get("form") else ""
        return any(k in kind for k in self.WARDED_KINDS)

    def _enchantments_of(self, c: dict) -> list:
        """The charms, frights and possessions on a creature that a celestial, elemental, fey, fiend or undead put there."""
        out = []
        for e in c.get("effects") or []:
            src = self._find_or_none(e.get("source_id"))
            if src is None or src is c or not self._warded_kind(src):
                continue
            if {"Charmed", "Frightened"} & set(e.get("conditions") or []) or (e.get("mods") or {}).get("possessed_by") is not None:
                out.append(e)
        return out

    def _end_dispel(self, c: dict, a: dict):
        """Using Break Enchantment or Dismissal ends Dispel Evil and Good."""
        c["spell_actions"] = [x for x in c.get("spell_actions") or [] if x.get("spell") != a["spell"]]
        if (c.get("concentrating") or {}).get("spell") == a["spell"]:
            self._drop_conc(c, f"{a['name']} used")

    def _until(self, spec: Optional[str], caster: dict, target: dict) -> Optional[dict]:
        if not spec:
            return None
        now = self.b.get("turn")
        if spec == "caster_start":
            return {"start": caster["id"]}
        if spec == "target_start":
            return {"start": target["id"]}
        if spec == "caster_end_next":
            return {"end": caster["id"], "skip": 1 if now == caster["id"] else 0}
        if spec == "target_end_next":
            return {"end": target["id"], "skip": 1 if now == target["id"] else 0}
        return None

    # ------------------------------------------------------------------ monsters' spell lists
    def _monster_book(self, c: dict) -> dict:
        """{spell name lower: {'level', 'limit', 'line', 'dc', 'attack', 'caster_level'}} from the stat block's Spellcasting."""
        from .view import _spell_lines
        m = self._monster(c)
        out = {}
        for e in (m or {}).get("spellcasting") or []:
            text = e.get("text", "")
            dc = re.search(r"(?i)\bsave DC (\d+)", text)       # "(spell save DC 14", "(save DC 17, +9 to hit", "(Spell save DC 11"
            atk = re.search(r"([+-]\d+) to hit with spell attacks", text)
            lvl = re.search(r"(\d+)(?:st|nd|rd|th)-level spellcaster", text)
            lines = _spell_lines(text)
            if not lines:                                       # "Maegera casts fireball (spell save DC 19)", "The behir casts color spray or sleep"
                cast = re.search(r"\bcasts? ([a-z][a-z' /-]*?(?:,? or [a-z][a-z' /-]*?)*)(?= \(| at |,| requiring|\.)", text)
                names = [rules.spell(n)["name"] for n in re.split(r",? or ", cast.group(1)) if rules.spell(n)] if cast else []
                label = e.get("name") or ""
                if re.search(r"Recharges? after", label, re.I):
                    label += " 1/day"                           # once until a rest: once this fight
                lines = [{"label": label, "spells": names}] if names else []
            for ln in lines:
                label = ln["label"].lower()
                limit = None
                slot_level = None
                m1 = re.search(r"(\d+)/day", label)
                if m1:
                    limit = ("day", int(m1.group(1)))
                m2 = re.search(r"(?:level (\d+)|(\d+)(?:st|nd|rd|th) level) \((\d+) slots?\)", label)
                if m2:
                    slot_level = int(m2.group(1) or m2.group(2))
                    limit = ("slot", int(m2.group(3)))
                for n in ln["spells"]:
                    sp = rules.spell(n)
                    out[n.lower()] = {"level": slot_level if slot_level is not None else (sp["level"] if sp else 0), "limit": limit,
                                      "line": ln["label"], "dc": int(dc.group(1)) if dc else 13,
                                      "attack": int(atk.group(1)) if atk else None, "caster_level": int(lvl.group(1)) if lvl else 1}
        return out

    def _legendary_spells(self, c: dict, entry: dict) -> list:
        """A legendary action that casts from the creature's book ("The sphinx casts a spell", "uses Spellcasting", "casts a
        cantrip", "makes a hoof attack or casts sacred flame"): [(spell name, cost 'legendary:N')] it may cast with it."""
        text, name = entry.get("text") or "", entry.get("name") or ""
        if not re.search(r"\bcasts?\b|\bSpellcasting\b", text):
            return []
        book = self._monster_book(c)
        named = [n for n in book if re.search(r"\bcasts? (?:the )?%s\b|\bto cast %s\b" % (re.escape(n), re.escape(n)), text, re.I)]
        if not named and re.search(r"\bcasts? (?:a|one of its) cantrips?\b", text, re.I):
            named = [n for n, e in book.items() if not e["level"]]
        elif not named and re.search(r"\bcasts? a spell\b|\bSpellcasting\b|\bcasts? a \d\w*-", text, re.I):
            named = list(book)
        c2 = re.search(r"Costs (\d) Actions", name, re.I)
        per_level = re.search(r"per level of the spell", text, re.I)
        out = []
        for n in named:
            sp = rules.spell(n)
            if not sp or SB.spec(sp)["cost"] not in ("action", "bonus"):
                continue
            out.append((sp["name"], f"legendary:{max(1, book[n]['level'] or 1) if per_level else (c2.group(1) if c2 else 1)}"))
        return out

    _LAIR_STOP = {"spell", "spells", "on", "at", "as", "using", "requiring", "instead", "affecting", "but", "except", "four", "without",
                  "targeting", "that", "which", "from", "once", "twice"}

    def _lair_spells(self, c: dict, text: str) -> list:
        """Spells a lair action casts: "The elder brain casts wall of force", "casts darkness, dispel magic, or misty step",
        "creates fog as though it had cast the fog cloud spell", "uses Spellcasting to cast detect thoughts": [spell names]."""
        m = re.search(r"\b(?:casts?|to cast)\b ([^.]*)", text or "")
        if not m:
            return []
        words = []
        for w in re.findall(r"[A-Za-z']+", m.group(1)):
            if w.lower() in self._LAIR_STOP:
                break
            words.append(w.lower())
        out, i = [], 0
        while i < len(words):
            for n in (4, 3, 2, 1):
                sp = rules.spell(" ".join(words[i:i + n])) if i + n <= len(words) else None
                if sp:
                    out.append(sp["name"])
                    i += n
                    break
            else:
                i += 1
        return list(dict.fromkeys(out))

    @staticmethod
    def _lair_times(text: str) -> int:
        """How many times a lair action casts its spell: "casts major image four times at its lowest level" 4, else 1."""
        m = re.search(r"\bcasts?\b[^.]*?\b(twice|thrice|two|three|four|five|six|\d+) times?\b", text or "")
        if not m:
            return 1
        return {"twice": 2, "thrice": 3, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6}.get(m.group(1)) or int(m.group(1))

    def _lair_terms(self, c: dict, sp: dict, text: str) -> dict:
        """What a lair action's spell is cast with: the DC in its text ("spell save DC 16"), else the monster's spell DC; the level
        ("at 5th level", "as a 9th-level spell"), else the spell's own."""
        book = self._monster_book(c)
        mine = book.get(sp["name"].lower()) or next(iter(book.values()), None)
        dc = re.search(r"spell save DC (\d+)", text or "")
        lv = re.search(r"(?:at|as an?) (\d+)(?:st|nd|rd|th)[- ]level", text or "")
        dc = int(dc.group(1)) if dc else (mine["dc"] if mine else self._spell_dc(c))
        return {"dc": dc, "level": int(lv.group(1)) if lv else sp["level"], "attack": (mine or {}).get("attack"),
                "caster_level": (mine or {}).get("caster_level", 1)}

    def _monster_can_cast(self, c: dict, name: str) -> bool:
        e = self._monster_book(c).get(name.lower())
        if not e:
            return True
        lim = e["limit"]
        if not lim:
            return True
        used = (c.get("spell_uses") or {})
        if lim[0] == "slot":
            return used.get(f"slot:{e['level']}", 0) < lim[1]
        return used.get(name.lower(), 0) < lim[1]

    def _monster_spend(self, c: dict, name: str):
        e = self._monster_book(c).get(name.lower())
        if not e or not e["limit"]:
            return
        used = c.setdefault("spell_uses", {})
        key = f"slot:{e['level']}" if e["limit"][0] == "slot" else name.lower()
        used[key] = used.get(key, 0) + 1

    # ------------------------------------------------------------------ paying
    def _economy_on(self) -> bool:
        return self.b.get("status") == ACTIVE and (self.b.get("rules") or {}).get("economy", True)

    def _pay(self, c: dict, cost: str, what: str, *, check_only: bool = False) -> Optional[str]:
        """Spend `cost` from the creature's turn (when the battle enforces the action economy). Returns the reason it can't,
        with check_only; otherwise raises."""
        why = None
        if self._economy_on():
            kind = EC.parse(cost)[0]
            t = c.setdefault("turn", EC.new_turn(self._speed(c)))
            if kind not in ("free",) and self._hp_of(c) <= 0:
                why = f"{c['name']} is down"
            elif kind in ("action", "bonus", "reaction", "attack", "multi", "legendary") and not self._can_act(c):
                why = f"{c['name']} can't act (incapacitated)"
            elif kind in ("action", "bonus", "attack", "move", "object", "multi") and self.b.get("turn") != c["id"]:
                why = f"It isn't {c['name']}'s turn"
            elif kind == "legendary" and self.b.get("status") == ACTIVE and self.b.get("turn") == c["id"]:
                why = "Legendary actions are taken at the end of another creature's turn"
            elif kind == "multi":
                why = None if t.get("multi", 0) > 0 or t.get("action", 0) > 0 else "No action left"
            else:
                why = EC.why_not(t, cost)
            if not why and kind in ("action", "bonus", "reaction", "attack", "multi", "legendary") and not str(what).startswith("End ") \
                    and self._fx(c, "shell_locked"):
                why = f"{c['name']} is in its shell: it can only emerge"          # Shell Defense
            if not why and kind == "action" and EC.haste_only(t) and what not in HASTE_ACTIONS and not str(what).startswith(("Use ", "throw ", "Attack: ")):
                why = "Haste's extra action only Attacks (one attack), Dashes, Disengages, Hides or Uses an Object"
            if not why and kind in ("action", "bonus", "attack", "multi") and self._fx(c, "confused") and self.b.get("turn") == c["id"]:
                why = self._confusion(c, t, kind)
            if not why and kind in ("action", "bonus", "attack", "multi") and self._fx(c, "one_action"):     # Slow, Tasha's Mind Whip
                if kind == "bonus" and t.get("action", 1) < 1 or kind != "bonus" and t.get("bonus", 1) < 1:
                    why = "Only an action or a bonus action this turn, not both"
                elif kind == "multi" and t.get("action", 1) < 1 and t.get("multi", 0) < self._multiattack_count(c):
                    why = "Only one attack this turn"
        if check_only:
            return why
        if why:
            raise ServiceError(why)
        if EC.parse(cost)[0] == "legendary" and self.b.get("status") == ACTIVE:
            self._vfx("legendary", id=c["id"], name=str(what))  # a crown flashes over it on the maps
        if self.b.get("status") != ACTIVE:
            self._fresh_turn(c)                             # out of combat: anything, any time, with a full budget each time
        if self._economy_on():
            t = c["turn"]
            kind = EC.parse(cost)[0]
            if kind == "multi":
                if t.get("multi", 0) > 0:
                    t["multi"] -= 1
                else:
                    one = EC.haste_only(t)                  # Haste's action: one weapon attack
                    t["action"] -= 1
                    t["multi"] = 0 if one else max(0, self._multiattack_count(c) - 1)
                    t["haste"] = min(t.get("haste", 0), t["action"])
                t.setdefault("used", []).append(what)
            else:
                EC.spend(t, cost, what)
        return None

    def _hexed_by(self, c: dict) -> Optional[dict]:
        """The creature c has cursed with Hex or Hexblade's Curse (Maddening Hex's target), or None."""
        return next((o for o in self.b["combatants"] if not self._is_out(o) and any(
            e.get("source_id") == c["id"] and e["name"] in ("Hex", "Hexblade's Curse") for e in o.get("effects") or [])), None)

    def _maddening_hex(self, c: dict) -> str:
        """Maddening Hex (bonus action): psychic damage equal to the Charisma modifier to the cursed creature and foes within 5 ft of it."""
        hexed = self._hexed_by(c)
        if hexed is None:
            raise ServiceError("Nobody is cursed by your Hex or Hexblade's Curse")
        if c.get("pos") and hexed.get("pos") and self._dist(c, hexed) > 30:
            raise ServiceError(f"{hexed['name']} is out of range (30 ft)")
        self._pay(c, "bonus", "Maddening Hex")
        char = self._sheet(c)
        n = max(1, char.mod("cha") if char else 1)
        ids = [hexed["id"]] + [o["id"] for o in self.b["combatants"] if o is not hexed and o.get("pos") and hexed.get("pos")
                               and not self._is_out(o) and self._hostile(c, o) and self._dist(o, hexed) <= 5]
        out = self._run_r(self._strike(c, "Maddening Hex", ids, mode="auto", parts=[[str(n), "psychic"]]))
        self._commit()
        return out

    def maddening_hex(self, cid: int) -> str:
        """The bar's Maddening Hex when only Hexblade's Curse marks the target (with Hex it's one of Hex's spell actions)."""
        with self.lock:
            self._busy()
            return self._maddening_hex(self._find(cid))

    def _trail_strikes(self, c: dict) -> list:
        """Ashardalon's Stride: a creature the mover comes within 5 ft of takes the fire (once a turn each). Strikes to run."""
        out = []
        for e, v in self._fxs(c, "trail"):
            if not c.get("pos") or e not in (c.get("effects") or []):
                continue
            key = f"{self.b.get('round')}:{self.b.get('turn')}"
            hit = e.setdefault("trail_hits", {})
            for o in self.b["combatants"]:
                if o is c or not o.get("pos") or self._is_out(o) or hit.get(str(o["id"])) == key or self._dist(c, o) > 5:
                    continue
                hit[str(o["id"])] = key
                out.append(self._strike(c, e["name"], [o["id"]], mode="auto", parts=[[v[0], v[1]]], spell=True))
        return out

    def _spell_turn_items(self, c: dict) -> list:
        """Strikes a lasting spell makes as its caster's turn starts (built, not run): Storm of Vengeance's rounds 2 to 10 - acid
        rain, six lightning bolts, hail, then freezing rain and gusts."""
        out = []
        for z in [z for z in self.b.get("zones") or [] if z.get("storm") and z.get("owner") == c["id"]]:
            z["n"] = n = int(z.get("n") or 1) + 1
            under = [o for o in G.creatures_in({tuple(t) for t in z["tiles"]}, self.b["combatants"]) if not self._is_out(o)]
            if not under:
                continue
            if n == 2:
                out.append(self._strike(c, f"{z['name']}: acid rain", [o["id"] for o in under], mode="auto", parts=[["1d6", "acid"]], spell=True))
            elif n == 3:
                foes = sorted([o for o in under if self._hostile(c, o)], key=self._hp_of)[:6]
                if foes:
                    out.append(self._strike(c, f"{z['name']}: lightning", [o["id"] for o in foes], mode="save", parts=[["10d6", "lightning"]],
                                            sv={"ab": "dex", "dc": int(z.get("dc") or 13), "half": True}, spell=True,
                                            origin=z.get("point") or [0, 0]))      # from the sky: no cover
            elif n == 4:
                out.append(self._strike(c, f"{z['name']}: hail", [o["id"] for o in under], mode="auto", parts=[["2d6", "bludgeoning"]], spell=True))
            else:
                z.update(difficult=True, ranged_dis=True, obscure="heavy")       # gusts and freezing rain
                out.append(self._strike(c, f"{z['name']}: freezing rain", [o["id"] for o in under], mode="auto", parts=[["1d6", "cold"]], spell=True))
        return out

    def _spell_turn_start(self, c: dict):
        """Spells that do something as a creature's turn starts: Confusion's d10 (a 1 sends it wandering), Aura of Life's 1 hit point."""
        if self._fx(c, "confused") and not self._is_out(c):
            t = c.setdefault("turn", {})
            t.pop("confusion", None)
            self._confusion(c, t, "action")
            if t["confusion"] == 1 and c.get("pos"):           # all its movement in a random direction
                dx, dy = [(1, 0), (-1, 0), (0, 1), (0, -1)][roll("1d4") - 1]
                self._push(c, {"pos": [c["pos"][0] - dx, c["pos"][1] - dy], "span": 1}, max(0, self._speed(c)))
                t["move"] = 0
        if self._fx(c, "commanded") and not self._is_out(c):    # Command: Approach, Drop, Flee
            self._command_turn(c)
        for e, _v in self._fxs(c, "transfixed"):                # Transfix: it walks to the caster by the most direct route, trying to get within 5 ft
            src, t = self._find_or_none(e.get("source_id")), c.get("turn")
            if src is not None and t is not None and src.get("pos") and c.get("pos") and not self._is_out(c) and self._dist(c, src) > 5:
                self._push(c, src, -max(0, self._speed(c)))
                t["move"] = 0
                self._say(f"{c['name']} is drawn towards {src['name']} ({e['name']})")
        for o in self.b["combatants"]:                          # Spirit Shroud: a foe starting its turn within 10 ft loses 10 ft of speed until its next turn
            for e in o.get("effects") or []:
                ft = (e.get("mods") or {}).get("slow_aura")
                if not ft or o is c or e.get("source_id") != o["id"] or self._is_out(o) or self._is_out(c) or not self._hostile(o, c) \
                        or not o.get("pos") or not c.get("pos") or self._dist(o, c) > int(ft) or not self._sees(o, c):
                    continue
                self._effect_on(c, f"{e['name']} (slowed)", [], None, None, None, None, o["name"], {"speed": -int(ft)}, None, o["id"], until={"start": c["id"]})
                t = c.setdefault("turn", {})
                for k in ("move", "speed"):
                    t[k] = max(0, int(t.get(k, 0)) - int(ft))
                self._say(f"{c['name']} starts its turn within {ft} ft of {o['name']}'s {e['name']}: speed down {ft} ft")
        for e, _v in self._fxs(c, "waste_turn"):                # Bestow Curse (wasted turns): a Wisdom save each turn or its action is lost
            if self._is_out(c) or not self._can_act(c):
                continue
            res = self._saving_throw(c, e.get("ability") or "wis", int(e.get("dc") or 13), spell=True, label=e["name"])
            self._say(f"{c['name']} WIS save against {e['name']}: d20 {res['kept']}{res['note']} = {res['total']} vs DC {e.get('dc') or 13} — "
                      + ("keeps its wits" if res["ok"] else "wastes its action"))
            if not res["ok"]:
                t = c.setdefault("turn", {})
                t["action"] = 0
                t["multi"] = 0
        if (c.get("form") or {}).get("keeps_hp") and not self._can_act(c):      # a monster's Change Shape ends when it is incapacitated
            self._revert_shape(c)
            self._say(f"{c['name']} reverts to its true form")
        for z in list(self.b.get("zones") or []):              # Ravenous Void: starting a turn within 100 ft, a Strength save or pulled in
            if not z.get("pull_to") or not z.get("point") or not c.get("pos") or self._is_out(c):
                continue
            d = G.distance_to_point(c["pos"], c.get("span") or 1, tuple(z["point"]))
            if G.footprint(c["pos"], c.get("span") or 1) & {tuple(t) for t in z["tiles"]} or d > z["pull_to"]:
                continue
            res = self._saving_throw(c, "str", int(z.get("dc") or 13), spell=True, label=z["name"])
            self._say(f"{c['name']} STR save against {z['name']}'s pull: d20 {res['kept']} = {res['total']} vs DC {z.get('dc')} — "
                      + ("holds on" if res["ok"] else "pulled in"))
            if not res["ok"]:
                self._push(c, {"pos": [int(z["point"][0]), int(z["point"][1])], "span": 1}, -int(d))
        mt = c.get("maintain")                                  # a spell kept up with the caster's action each turn (Crown of Madness)
        if mt and (c.get("concentrating") or {}).get("spell") == mt.get("spell"):
            if mt.get("due") and not mt.get("kept"):
                self._drop_conc(c, f"{mt['spell']} not maintained")
                c.pop("maintain", None)
            else:
                mt.update(due=True, kept=False)
        elif mt:
            c.pop("maintain", None)
        for e, _v in self._fxs(c, "crowned"):                  # Crown of Madness: the caster picks whom it attacks first
            caster = self._find_or_none(e.get("source_id"))
            near = [o for o in self.b["combatants"] if caster and o is not c and o.get("pos") and c.get("pos") and self._alive(o)
                    and self._hostile(caster, o) and self._dist(c, o) <= max(5, self._reach(c))]
            if near and self._can_act(c):
                victim = min(near, key=lambda o: self._hp_of(o))
                c.setdefault("turn", {})["crown_victim"] = victim["id"]
                self._say(f"Crown of Madness: {c['name']} must make a melee attack against {victim['name']} before anything else")
        if c["kind"] == "pc" and self._hp_of(c) <= 0 and not self._dead(c) and self._fx(c, "life_1"):
            if self._heal(c, 1, revive=True):
                self._say(f"Aura of Life: {c['name']} regains 1 hit point")
        if self._fx(c, "no_bonus") and c.get("turn") is not None:     # Song of Sinking, buried to the waist: no bonus actions
            c["turn"]["bonus"] = 0

    # ------------------------------------------------------------------ Legends Reforged (the LGR module's spells)
    def _spell_turn_end_items(self, c: dict) -> list:
        """Strikes a lasting spell makes as its caster's turn ends (built, not run): Storm Call's bolts, each on a creature
        picked at random within range (friend or foe, never the caster), a save and its own damage roll each."""
        out = []
        for e, v in self._fxs(c, "random_bolts"):
            if e not in (c.get("effects") or []) or not c.get("pos") or self._is_out(c):
                continue
            near = [o for o in self.b["combatants"] if o is not c and o.get("pos") and not self._is_out(o) and not o.get("conjured")
                    and self._dist(c, o) <= int(v.get("ft") or 120)]
            for o in self.rng.sample(near, min(len(near), int(v.get("n") or 1))):
                self._say(f"{e['name']}: lightning strikes at {o['name']}")
                out.append(self._strike(c, e["name"], [o["id"]], mode="save", sv={"ab": v.get("save") or "dex", "dc": int(v.get("dc") or 13),
                                                                                   "half": bool(v.get("half"))},
                                        parts=v["parts"], spell=True, origin=list(G.centre(o["pos"], o.get("span") or 1))))     # from the sky: no cover
        return out

    def _hit_ward(self, R: dict, tgt: dict) -> bool:
        """Quen: an attack that hits deals the shielded creature no damage; the shield shatters after its last hit (one, or more
        from a higher slot). True when it took this hit (resolve.py, as the damage is rolled)."""
        for e, _n in self._fxs(tgt, "hit_ward"):
            n = int((e.get("mods") or {}).get("hit_ward") or 0)  # (the effect's own count: it drops hit by hit)
            if e not in (tgt.get("effects") or []) or n <= 0:
                continue
            left = n - 1
            e["mods"]["hit_ward"] = left
            R["cur"]["dmg"] = []
            self._line(R, f"{tgt['name']}'s {e['name']} takes the hit: no damage" + (f" ({left} more)" if left else " - the shield shatters"),
                       f"{e['name']}: no damage")
            if left <= 0:
                self._effect_off(tgt, e, "the shield shatters")
            return True
        return False

    def _bomb_burst(self, c: dict) -> None:
        """Walking Bomb: a creature that drops to 0 hit points under it bursts - a save for everyone within the radius (resolve._zero_hp)."""
        for e, b in list(self._fxs(c, "death_burst")):
            if e not in (c.get("effects") or []) or not isinstance(b, dict):
                continue
            self._effect_off(c, e, "it bursts")
            src = self._find_or_none(e.get("source_id"))
            if not c.get("pos"):
                continue
            ids = [o["id"] for o in self.b["combatants"] if o is not c and o.get("pos") and not self._is_out(o) and not o.get("conjured")
                   and self._dist(o, c) <= int(b.get("radius") or 20)]
            tiles = G.area_tiles("emanation", int(b.get("radius") or 20), origin=G.centre(c["pos"], c.get("span") or 1),
                                 caster_box=G.box(c["pos"], c.get("span") or 1), **self._bounds_kw())
            self._area_vfx(src, tiles, b["parts"], "burst", G.centre(c["pos"], c.get("span") or 1))
            self._say(f"{c['name']} bursts ({e['name']})")
            if not ids:
                continue
            S = self._strike(src, f"{e['name']} (burst)", ids, mode="save", sv={"ab": b.get("save") or "dex", "dc": int(b.get("dc") or 13),
                                                                               "half": bool(b.get("half"))},
                             parts=b["parts"], spell=True, origin=list(G.centre(c["pos"], c.get("span") or 1)))
            if self._stack():
                self._stack().append(S)                         # inside an action: it goes off next
            else:
                self._run_r(S)

    def _worsen(self, c: dict, eff: dict) -> None:
        """Song of Sinking: a failed repeated save takes the effect to its next stage (more mods, more conditions)."""
        stages = (eff.get("mods") or {}).get("worsen") or []
        n = int(eff.get("worse_n") or 0)
        if n >= len(stages):
            return
        st = stages[n]
        eff["worse_n"] = n + 1
        eff["mods"] = dict(eff["mods"], **(st.get("mods") or {}))
        immune = self._defenses(c).get("immune_cond", set())
        for cond in st.get("conds") or []:
            if cond not in eff["conditions"] and cond not in immune:
                eff["conditions"].append(cond)
                self._cond(c, cond, True)
        self._say(f"{c['name']}: {eff['name']} - {st.get('note') or 'worse'}")

    def _weave_offers(self, window: str, R: dict, att: Optional[dict], tgt: Optional[dict]) -> list:
        """Norns' Weave: whoever holds recorded d20s may swap one in, with its reaction, for an attack roll or a save it can see within
        60 ft (its own too) - offered only when that turns the outcome: a friend's miss or failed save, a foe's hit or successful save."""
        cur = R.get("cur") or {}
        if window not in ("hit", "missed", "save_failed", "save_ok") or tgt is None or cur.get("auto") or cur.get("total") is None:
            return []
        attack = window in ("hit", "missed")
        roller = att if attack else tgt
        if roller is None or not roller.get("pos"):
            return []
        kept, total = int(cur.get("kept") or 0), int(cur["total"])
        line = int(cur.get("ac") or 0) + int(cur.get("ac_extra") or 0) if attack else int((R.get("sv") or {}).get("dc") or 0)
        out = []
        for o in self.b["combatants"]:
            dice = next((list(e["mods"]["fate_dice"]) for e in o.get("effects") or [] if (e.get("mods") or {}).get("fate_dice")), None)
            if not dice or not o.get("pos") or (o is not roller and (self._dist(o, roller) > 60 or not self._sees(o, roller))):
                continue
            friendly = not self._hostile(o, roller)
            if friendly != (window in ("missed", "save_failed")):
                continue
            if attack:
                works = (lambda d: d == 20 or d != 1 and total - kept + d >= line) if friendly else (lambda d: d == 1 or d != 20 and total - kept + d < line)
            else:
                works = (lambda d: total - kept + d >= line) if friendly else (lambda d: total - kept + d < line)
            good = [d for d in dice if works(d)]
            if not good:
                continue
            d = max(good) if friendly else min(good)
            label = f"Norns' Weave: {roller['name']}'s d20 becomes {d}"
            out.append({"reactor": o["id"], "cost": "reaction", "options": [{"key": f"weave:{d}", "label": label, "detail": f"{total} vs {line}"}],
                        "text": f"{roller['name']} rolled {total} against {line}. {label}?"})
        return out

    def _weave_apply(self, window: str, R: dict, reactor: dict, d: int) -> None:
        """Norns' Weave: the recorded number replaces the d20 (and is used up; the spell ends with the last one)."""
        eff = next((e for e in reactor.get("effects") or [] if d in ((e.get("mods") or {}).get("fate_dice") or [])), None)
        if eff is None:
            return
        eff["mods"]["fate_dice"] = list(eff["mods"]["fate_dice"])
        eff["mods"]["fate_dice"].remove(d)
        cur = R.setdefault("cur", {})
        cur["total"] = int(cur.get("total") or 0) - int(cur.get("kept") or 0) + d
        cur["kept"] = d
        if window in ("hit", "missed"):
            cur["crit"] = d == 20
            if d == 20:                                         # a natural 20 hits whatever the numbers say
                cur["total"] = max(cur["total"], int(cur.get("ac") or 0) + int(cur.get("ac_extra") or 0) + 5)
        else:
            cur["ok"] = cur["total"] >= int(R["sv"]["dc"])
        left = eff["mods"]["fate_dice"]
        self._line(R, f"{reactor['name']} weaves fate: the d20 becomes {d} → {cur['total']}" + (f" ({', '.join(map(str, left))} left)" if left else ""),
                   "Norns' Weave")
        if not left:
            self._effect_off(reactor, eff, "every thread is spent")

    @staticmethod
    def _command_word(sv: dict, word: str) -> None:
        """Command's one-word order, as the save's effect: grovel (prone, its turn ends), halt (no move, no action), approach / flee
        (_command_turn walks it at the start of its next turn) or drop (what it holds falls). Lasts to the end of its next turn."""
        keep = {"keeps_conc": True}
        if word == "halt":
            sv.update(conds=["Incapacitated"], prone=None, mods=dict(keep, speed_set=0), note="halted: no move, no action")
        elif word in ("approach", "flee", "drop"):
            note = {"approach": "compelled to approach the caster", "flee": "compelled to flee the caster",
                    "drop": "dropping what it holds"}[word]
            sv.update(conds=[], prone=None, mods=dict(keep, commanded=word), note=note)

    def _command_turn(self, c: dict) -> None:
        """Command, as its target's turn starts: Approach walks it straight at the caster (and ends its turn within 5 ft), Flee
        spends the whole turn moving away at double speed (Dash), Drop lets go of what it holds."""
        t = c.get("turn")
        if t is None:
            return
        for e, word in self._fxs(c, "commanded"):
            src = self._find_or_none(e.get("source_id"))
            if word == "drop":
                self._say(f"Command: {c['name']} drops what it is holding")
            elif word in ("approach", "flee") and src and src.get("pos") and c.get("pos") and self._can_act(c):
                speed = max(0, self._speed(c))
                if word == "approach" and self._dist(c, src) > 5:
                    self._push(c, src, -speed)
                elif word == "flee":
                    self._push(c, src, 2 * speed)
                t["move"] = 0
                if word == "flee" or self._dist(c, src) <= 5:
                    t["action"] = t["bonus"] = 0
                    t["dashed"] = 1 if word == "flee" else t.get("dashed", 0)
                self._say(f"Command: {c['name']} {'approaches' if word == 'approach' else 'flees from'} {src['name']}"
                          + (" and its turn ends" if t.get("action") == 0 else ""))

    def _confusion(self, c: dict, t: dict, kind: str) -> Optional[str]:
        """Confusion's d10, rolled the first time the creature tries something on its turn: what it may still do (None: anything)."""
        if "confusion" not in t:
            n = roll("1d10")
            t["confusion"] = n
            if n == 1:
                what = "wanders off in a random direction (no action)"
            elif n <= 6:
                what = "doesn't move or act this turn"
                t["move"] = 0
            elif n <= 8:
                near = [o for o in self.b["combatants"] if o is not c and o.get("pos") and c.get("pos") and not self._is_out(o)
                        and self._dist(c, o) <= max(5, self._reach(c))]
                pick = near[roll(f"1d{len(near)}") - 1]["name"] if near else None
                what = f"lashes out at {pick} (one melee attack, no move)" if pick else "lashes out, but nobody is in reach (no action)"
                t["move"] = 0
                if not pick:
                    t["confusion"] = 6                          # nobody to hit: it does nothing this turn
            else:
                what = "acts normally this turn"
            self._say(f"{c['name']} is confused: d10 {n} — {what}")
        n = t["confusion"]
        if n <= 6 or kind == "bonus" and n <= 8:
            return "Confused: no action this turn"
        return None

    # ------------------------------------------------------------------ aiming
    def _resolve_aim(self, att: dict, spec: dict, slot: int, caster_level: int, targets: Optional[List[int]], point,
                     more_targets: int = 0, range_mult: int = 1) -> dict:
        """Who and where a cast goes: {'targets': [ids], 'tiles': [...], 'point', 'why'} - why is the reason it can't."""
        tg = spec["target"]
        typ = tg["type"]
        out = {"targets": [], "tiles": [], "point": None, "why": None}
        picked = list(targets) if targets is not None else list(self.b.get("targets") or ([self.b["target"]] if self.b.get("target") else []))
        aim = point if point is not None else self.b.get("aim")
        more_aim = []
        if aim and isinstance(aim[0], (list, tuple)):             # Meteor Swarm: a list of points
            aim, more_aim = aim[0], [list(p) for p in aim[1:]]
        if spec.get("kind") == "attack" and self._feat(att, "spell_sniper"):     # Spell Sniper: attack-roll spells reach twice as far
            range_mult *= 2
        rng = spec["range"] * range_mult if spec["range"] > 5 or range_mult == 1 else 30
        ter = self._terrain()
        if typ == "self":
            out["targets"] = [att["id"]]
            return out
        if typ == "none":
            out["targets"] = picked[:1]
            return out
        if typ in ("creature", "split"):
            if not picked:
                out["why"] = "Pick a target"
                return out
            limit = SB.projectiles(rules.spell(spec["name"]), slot, caster_level) if typ == "split" else SB.target_count(spec, slot) + more_targets
            ids = picked if typ == "split" else list(dict.fromkeys(picked))
            if typ == "split" and len(ids) < limit:
                ids = (ids * limit)[:limit] if len(set(ids)) == 1 else ids
            if len(ids) > limit:
                ids = ids[:limit]
            for i in dict.fromkeys(ids):
                t = self._find_or_none(i)
                if not t:
                    out["why"] = "That creature isn't in the battle"
                    return out
                if t.get("pos") and att.get("pos") and t is not att:
                    d = self._dist(att, t)
                    if d > max(rng, 5):
                        out["why"] = f"{t['name']} is out of range ({d} ft, range {rng} ft)"
                        return out
                    if not V.line_of_sight(ter, att["pos"], att.get("span") or 1, t["pos"], t.get("span") or 1):
                        out["why"] = f"No line of sight to {t['name']}"
                        return out
                if self._fx(t, "untargetable") and t is not att:
                    out["why"] = f"{t['name']} can't be targeted"
                    return out
                why = self._wrong_kind(spec.get("key", ""), t)
                if why:
                    out["why"] = why
                    return out
            near = tg.get("near")
            if near and len(set(ids)) > 1:
                rows = [self._find(i) for i in dict.fromkeys(ids)]
                if any(self._dist(a, b) > near for k, a in enumerate(rows) for b in rows[k + 1:]):
                    out["why"] = f"The targets must be within {near} ft of each other"
                    return out
            out["targets"] = ids
            return out
        area = spec.get("area")
        if typ == "point" and not area:
            if aim is None and picked:
                t = self._find_or_none(picked[0])
                aim = list(G.centre(t["pos"], t.get("span") or 1)) if t and t.get("pos") else None
            if aim is None:
                if not tg.get("optional"):
                    out["why"] = "Pick a point on the map"
                return out
            out["point"] = [float(aim[0]), float(aim[1])]
            reach = int(tg.get("teleport") or rng)
            if att.get("pos") and G.distance_to_point(att["pos"], att.get("span") or 1, aim) > reach:
                out["why"] = f"That point is out of range ({reach} ft)"
            elif tg.get("teleport") and att.get("pos") and V.wall_blocks(ter, G.centre(att["pos"], att.get("span") or 1),
                                                                        (int(aim[0]) + .5, int(aim[1]) + .5)):
                out["why"] = "You can't see that spot (a wall is in the way)"     # Misty Step: a space you can see
            return out
        if typ in ("point", "self_area") and area:
            if aim is None and picked:
                t = self._find_or_none(picked[0])
                if t and t.get("pos"):
                    aim = list(G.centre(t["pos"], t.get("span") or 1))
            if typ == "point" and aim is None:
                out["why"] = "Pick a point on the map"
                return out
            if typ == "point" and att.get("pos") and G.distance_to_point(att["pos"], att.get("span") or 1, aim) > rng:
                out["why"] = f"That point is out of range ({rng} ft)"
                return out
            if not att.get("pos"):
                out["targets"] = picked[:1]
                return out
            size = area["size"] + (int(spec["special"].get("grow", 0)) * max(0, slot - spec["level"]))
            area = dict(area, size=size)
            if area.get("origin") == "point" and aim:
                aim = self._near_side(ter, G.centre(att["pos"], att.get("span") or 1), aim)
            tiles = G.area_for(area, att["pos"], att.get("span") or 1, tuple(aim) if aim else None, *self._bounds())
            origin = tuple(aim) if area.get("origin") == "point" and aim else G.centre(att["pos"], att.get("span") or 1)
            tiles = V.filter_area(ter, origin, tiles)
            n_more = int(spec["special"].get("spheres") or 1) - 1
            if n_more > 0 and aim:                               # Meteor Swarm: more bursts - at the points given, else on the picked creatures
                for t in picked:
                    o = self._find_or_none(t)
                    if len(more_aim) < n_more and o and o.get("pos") and list(G.centre(o["pos"], o.get("span") or 1)) != list(aim):
                        more_aim.append(list(G.centre(o["pos"], o.get("span") or 1)))
                for p in more_aim[:n_more]:
                    if G.distance_to_point(att["pos"], att.get("span") or 1, p) > rng:
                        out["why"] = f"A burst's point is out of range ({rng} ft)"
                        return out
                    p = self._near_side(ter, G.centre(att["pos"], att.get("span") or 1), p)
                    more = G.area_for(area, att["pos"], att.get("span") or 1, tuple(p), *self._bounds())
                    tiles = set(tiles) | set(V.filter_area(ter, tuple(p), more))
            out["tiles"] = sorted(tiles)
            out["point"] = [float(aim[0]), float(aim[1])] if aim else None
            hit = [c for c in G.creatures_in(tiles, self.b["combatants"]) if not self._is_out(c) and not self._fx(c, "untargetable")]
            if area.get("origin") == "caster":
                hit = [c for c in hit if c is not att]
            cap = tg.get("max")
            if spec["kind"] == "heal":                               # Mass Cure Wounds: up to six creatures of your choice
                hit = [c for c in hit if not self._hostile(c, att)]
                cap = cap or 6
            elif cap or spec["special"].get("foes_only"):            # Slow, Destructive Wave: creatures of your choice - the caster's foes
                hit = [c for c in hit if self._hostile(c, att)]
            hit = [c for c in hit if not self._wrong_kind(spec.get("key", ""), c)]      # Calm Emotions: humanoids only
            if cap:
                hit = hit[:cap]
            out["targets"] = [c["id"] for c in hit]
            return out
        out["targets"] = picked[:1]
        return out

    def cast_check(self, caster_id: int, spell_name: str, slot=None, targets: Optional[List[int]] = None, point=None) -> dict:
        """The aiming preview: would this cast work, whom it reaches, which tiles it covers (nothing is spent)."""
        with self.lock:
            att = self._find(caster_id)
            sp = rules.spell(spell_name)
            if not sp:
                return {"ok": False, "why": "Unknown spell", "targets": [], "tiles": []}
            spec = self._subc_spec(att, sp, SB.spec(sp))               # Circle of Mortality (subfeats_c.py)
            level = int(slot) if str(slot or "").isdigit() else sp["level"]
            aim = self._resolve_aim(att, spec, level, self._caster_level(att), targets, point)
            why = aim["why"] or self._pay(att, spec["cost"] if spec["cost"] != "long" else "action", sp["name"], check_only=True)
            if not why and spec["cost"] == "long" and self._economy_on():
                why = "Casting it takes longer than a turn"
            return {"ok": not why, "why": why, "targets": aim["targets"], "tiles": [list(t) for t in aim["tiles"]],
                    "point": aim["point"], "spec": _public(spec)}

    def _caster_level(self, c: dict) -> int:
        char = self._sheet(c)
        if char:
            return char.total_level
        e = next(iter(self._monster_book(c).values()), None)
        return e["caster_level"] if e else 1

    # ------------------------------------------------------------------ casting
    def pc_spell(self, attacker_id: int, spell_name: str, slot=None, ritual: bool = False, adv: Optional[str] = None,
                 target_id: Optional[int] = None, dtype: Optional[str] = None, targets: Optional[List[int]] = None, point=None,
                 metamagic: Optional[str] = None) -> str:
        """Cast a spell from a player character's sheet (spends the slot) and play it out. `metamagic`: a sorcerer's
        Quickened / Twinned / Heightened / Distant / Careful / Extended / Subtle / Empowered Spell (spends sorcery points)."""
        with self.lock:
            self._busy()
            att = self._find(attacker_id)
            char = self._char(att["character"])
            if not char:
                raise ServiceError("That character can't be loaded.")
            known = {s["name"].lower(): s for s in SC.spell_known_or_prepared(char)}
            sp0 = known.get(spell_name.strip().lower())
            if not sp0:
                raise ServiceError(f"{char.name} doesn't have {spell_name} known or prepared.")
            if targets is None and target_id:
                targets = [target_id] + [t for t in (self.b.get("targets") or []) if t != target_id]
            spec = self._subc_spec(att, sp0, SB.spec(sp0))           # Circle of Mortality (subfeats_c.py)
            att.pop("nf_cast_bonus", None)
            if spec.get("nf_bonus"):
                att["nf_cast_bonus"] = spec["nf_bonus"]             # a bonus-action Resistance or Sacred Flame spends one of its uses (newfeats.py)
            level = int(slot) if str(slot or "").isdigit() else sp0["level"]
            if spec["cost"] == "on_hit":
                return self._toggle_readied(att, sp0, slot)
            mm = self._metamagic(att, char, sp0, spec, level, metamagic)
            if mm.get("cost_override"):
                spec = dict(spec, cost=mm["cost_override"])
            self._precheck(att, sp0, spec, level, targets, point, ritual, mm)
            gone = self._spell_ward(att, sp0)
            if gone:                                             # Spellfire Storm: the spell dissipates, the action is wasted, the slot is kept
                if self._economy_on():
                    self._pay(att, spec["cost"] if spec["cost"] != "long" else "free", sp0["name"])
                msg = f"{att['name']}'s {sp0['name']} dissipates inside {gone}: no effect, and no slot is spent"
                self._commit(msg)
                return msg
            if mm.get("sp"):
                self._use_resource(att, "Sorcery Points", mm["sp"])
            res = self.chars.cast_spell(att["character"], spell_name, slot, ritual)
            sp = res["spell"]
            att["last_cast_free"] = res["slot"] is None and sp["level"] > 0     # cast without a slot: an innate or a feat's free cast (newfeats.py)
            if res["slot"] == SC.PACT_KEY:
                level = (SC.spell_slots(char).get("pact") or {}).get("level", sp["level"])
            elif isinstance(res["slot"], str) and res["slot"].isdigit():
                level = int(res["slot"])
            else:
                level = sp["level"]
            ab = sp["ability"]
            i_atk = sum(i.get("bonus_spell_attack") or 0 for _e, i in char._active_items())     # a Wand of the War Mage, a Rod of the Pact Keeper
            i_dc = sum(i.get("bonus_spell_dc") or 0 for _e, i in char._active_items())
            out = self._cast_on(att, sp, None, slot_level=level, caster_level=char.total_level, mod=char.mod(ab),
                                attack_bonus=char.proficiency_bonus + char.mod(ab) + i_atk, dc=8 + char.proficiency_bonus + char.mod(ab) + i_dc,
                                adv=adv, dtype=dtype, targets=targets, point=point, paid=True, mm=mm)
            return out

    def _toggle_readied(self, att: dict, sp: dict, slot=None) -> str:
        """A smite or a ranger's arrow spell isn't cast up front: picking it readies it (nothing is spent) and the next weapon
        hit it fits asks whether to cast it then. Picking it again while it's readied lets it go."""
        r = att.get("on_hit_spell")
        if r and r["spell"] == sp["name"]:
            att.pop("on_hit_spell")
            msg = f"{att['name']} lets {sp['name']} go"
        else:
            if (self._reaction_spell(att, sp["name"]) is None) if self._sheet(att) else not self._monster_can_cast(att, sp["name"]):
                raise ServiceError(f"{att['name']} has no way left to cast {sp['name']}.")
            if str(slot or "").isdigit() and self._sheet(att) and not self._has_slot(att, int(slot)) and \
                    (SC.spell_slots(self._sheet(att)).get("pact") or {}).get("level") != int(slot):
                raise ServiceError(f"No level {slot} slot left.")
            att["on_hit_spell"] = {"spell": sp["name"], "slot": int(slot) if str(slot or "").isdigit() else None}
            key = SB.spec(sp)["key"]
            weapon = "ranged weapon" if X.BUFFS[key]["mods"].get("ranged_only") else "melee weapon" if key.endswith("smite") else "weapon"
            msg = f"{att['name']} readies {sp['name']}: the next {weapon} hit asks whether to cast it"
        self._commit(msg)
        return msg

    def _metamagic(self, att: dict, char, sp: dict, spec: dict, level: int, name: Optional[str]) -> dict:
        if not name:
            return {}
        from . import features as F
        if not char.has_option(name):
            raise ServiceError(f"{char.name} doesn't know {name}.")
        cost = F.METAMAGIC.get(name, 1)
        cost = max(1, level) if cost == "level" else int(cost)
        if self._resource_left(att, "Sorcery Points") < cost:
            raise ServiceError(f"{name} needs {cost} sorcery points.")
        out = {"name": name, "sp": cost}
        if name == "Quickened Spell":
            if spec["cost"] != "action":
                raise ServiceError("Only a spell with a casting time of 1 action can be quickened.")
            out["cost_override"] = "bonus"
        elif name == "Twinned Spell":
            t = spec["target"]
            at_level = int(t.get("count") or 1) + int(t.get("per_level") or 0) * max(0, level - int(t.get("base_level") or sp["level"]))
            if t.get("type") != "creature" or at_level > 1 or spec.get("area"):       # one creature at the level it's cast at (XGE/TCE)
                raise ServiceError("Twinned Spell needs a spell that targets only one creature at this level.")
            out["more_targets"] = 1
        elif name == "Distant Spell":
            out["range_mult"] = 2
        return out

    def monster_cast(self, attacker_id: int, spell_name: str, dc: int = 13, attack_bonus: Optional[int] = None, level: int = 1,
                     adv: Optional[str] = None, target_id: Optional[int] = None, dtype: Optional[str] = None,
                     targets: Optional[List[int]] = None, point=None, slot=None, cost: Optional[str] = None) -> str:
        """A creature casts a spell from its stat block (DC, attack bonus and caster level read from its Spellcasting text).
        `cost`: what it pays instead of the spell's casting time (a legendary action: 'legendary:2')."""
        with self.lock:
            self._busy()
            att = self._find(attacker_id)
            sp = rules.spell(spell_name)
            if not sp:
                self._commit(f"{att['name']} casts {spell_name}")
                return f"{att['name']} casts {spell_name}"
            if targets is None and target_id:
                targets = [target_id] + [t for t in (self.b.get("targets") or []) if t != target_id]
            book = self._monster_book(att).get(sp["name"].lower())
            if book and not self._monster_can_cast(att, sp["name"]):
                raise ServiceError(f"{att['name']} has no uses of {sp['name']} left.")
            spec = self._subc_spec(att, sp, SB.spec(sp))      # Circle of Mortality (subfeats_c.py)
            slot_level = int(slot) if str(slot or "").isdigit() else (book["level"] if book and book["level"] else sp["level"])
            if cost:                                            # cast as a legendary action
                spec = dict(spec, cost=cost)
            if spec["cost"] == "on_hit":
                return self._toggle_readied(att, sp, slot)
            self._precheck(att, sp, spec, slot_level, targets, point, False)
            gone = self._spell_ward(att, sp)
            if gone:                                             # Spellfire Storm (see pc_spell)
                if self._economy_on():
                    self._pay(att, spec["cost"] if spec["cost"] != "long" else "free", sp["name"])
                msg = f"{att['name']}'s {sp['name']} dissipates inside {gone}: no effect"
                self._commit(msg)
                return msg
            if book:
                self._monster_spend(att, sp["name"])
            dc = int(dc)
            bonus = int(attack_bonus) if attack_bonus is not None else dc - 8
            return self._cast_on(att, sp, None, slot_level=slot_level or None, caster_level=int(level) or 1, mod=max(0, dc - 8 - self._prof(att)),
                                 attack_bonus=bonus, dc=dc, adv=adv, dtype=dtype, targets=targets, point=point, paid=True,
                                 mm={"cost_override": cost} if cost else None)

    def lair_cast(self, cid: int, entry: str, spell_name: str, adv: Optional[str] = None, target_id: Optional[int] = None,
                  targets: Optional[List[int]] = None, point=None, slot=None, dtype: Optional[str] = None) -> str:
        """A lair action that casts a spell: no action, no slot, one lair action a round (the DC and level come from the lair text)."""
        with self.lock:
            self._busy()
            att = self._find(cid)
            sec, e = self._entry_section(att, entry)
            if sec != "lair":
                raise ServiceError("That isn't one of its lair actions.")
            why = self._lair_why(att, e["name"])
            if why:
                raise ServiceError(why)
            sp = rules.spell(spell_name)
            if not sp or sp["name"] not in self._lair_spells(att, e.get("text") or ""):
                raise ServiceError(f"{entry} doesn't cast {spell_name}.")
            if targets is None and target_id:
                targets = [target_id] + [t for t in (self.b.get("targets") or []) if t != target_id]
            terms = self._lair_terms(att, sp, e.get("text") or "")
            level = int(slot) if str(slot or "").isdigit() else terms["level"]
            spec = dict(SB.spec(sp), cost="free")
            self._precheck(att, sp, spec, level, targets, point, False)
            att["lair_round"] = self.b.get("round")             # one lair action a round
            more = att.get("lair_more") or {}
            if more.get("entry") == e["name"] and more.get("round") == self.b.get("round") and more.get("left", 0) > 0:
                more["left"] -= 1                               # one of the casts of "casts darkness four times"
            else:
                times = self._lair_times(e.get("text") or "")
                att["lair_more"] = {"entry": e["name"], "round": self.b.get("round"), "left": times - 1} if times > 1 else None
            if not (att.get("lair_more") or {}).get("left"):
                att.pop("lair_more", None)
            return self._cast_on(att, sp, None, slot_level=level or None, caster_level=int(terms["caster_level"]) or 1,
                                 mod=max(0, terms["dc"] - 8 - self._prof(att)),
                                 attack_bonus=int(terms["attack"]) if terms["attack"] is not None else terms["dc"] - 8, dc=terms["dc"], adv=adv,
                                 dtype=dtype, targets=targets, point=point, paid=True, mm={"cost_override": "free", "lair": True})

    def _precheck(self, att: dict, sp: dict, spec: dict, level: int, targets, point, ritual: bool, mm: Optional[dict] = None):
        mm = mm or {}
        if spec["kind"] in ("reaction_only",):
            raise ServiceError(f"{sp['name']} is cast as a reaction: it's offered when it applies.")
        if self._economy_on():
            if spec["cost"] == "long" and not ritual:
                raise ServiceError(f"{sp['name']} takes {sp.get('casting_time')} to cast - not in the middle of a fight.")
            if ritual:
                raise ServiceError("Rituals take 10 minutes longer - not in the middle of a fight.")
            why = self._pay(att, spec["cost"], sp["name"], check_only=True) or EC.spell_rule(att.get("turn"), spec["cost"], sp["level"])
            if why:
                raise ServiceError(why)
        if spec.get("verbal") and self._in_silence(att) and mm.get("name") != "Subtle Spell":
            raise ServiceError(f"{att['name']} is in magical silence: no spells with a verbal component.")
        if "Silenced" in self._conds(att):
            raise ServiceError(f"{att['name']} can't speak.")
        if self._fx(att, "no_spells"):                          # Feeblemind, Tenser's Transformation, Gaseous Form
            raise ServiceError(f"{att['name']} can't cast spells now.")
        if self._fx(att, "rage"):
            raise ServiceError(f"{att['name']} can't cast spells while raging.")
        if att.get("form") and not self._beast_spells(att):
            raise ServiceError(f"{att['name']} can't cast spells in {att['form']['name'].lower()} form.")
        if spec["kind"] == "weapon_spell" and self._sheet(att) and not self._blade_weapons(self._sheet(att)):
            raise ServiceError(f"{sp['name']} needs a melee weapon in hand.")
        if spec["kind"] == "heal" and targets:
            rows = [self._find_or_none(t) for t in targets]
            if rows and all(r is not None and self._dead(r) for r in rows):
                raise ServiceError(f"{rows[0]['name']} is dead: healing can't help now (Revivify can).")
        aim = self._resolve_aim(att, spec, level, self._caster_level(att), targets, point, mm.get("more_targets", 0), mm.get("range_mult", 1))
        if aim["why"] and att.get("pos") and spec["target"]["type"] != "none":
            raise ServiceError(aim["why"])

    def _wrong_kind(self, key: str, t: dict) -> Optional[str]:
        """Spells that only work on some creatures (Hold Person: a humanoid; Animal Friendship: a beast of Int 3 or less)."""
        rule = ONLY_ON.get(key)
        if not rule:
            return None
        m = self._monster(t) if not self._sheet(t) else None
        kind = "humanoid" if self._sheet(t) and not t.get("form") else str((m or {}).get("type") or "").lower()
        if rule.get("types") and kind not in rule["types"]:
            return f"{t['name']} isn't {' or '.join(('an ' if k[0] in 'aeiou' else 'a ') + k for k in rule['types'])}"
        if kind in rule.get("not", ()):
            return f"{CR.shown(rule['label'])} has no effect on {kind}s"
        smart = int(((m or {}).get("abilities") or {}).get("int") or 10)
        if rule.get("max_int") is not None and m and smart > rule["max_int"]:
            return f"{t['name']} is too clever for it (Intelligence {smart})"
        if rule.get("min_int") is not None and m and smart < rule["min_int"]:
            return f"{CR.shown(rule['label'])} has no effect on {t['name']} (Intelligence {smart})"
        return None

    @staticmethod
    def _near_side(ter, start, aim) -> list:
        """PHB "A Clear Path to the Target": a point behind a wall puts the area's origin on the near side of the wall."""
        if not V.wall_blocks(ter, start, tuple(aim)):
            return list(aim)
        dx, dy = aim[0] - start[0], aim[1] - start[1]
        steps = max(1, int(max(abs(dx), abs(dy)) * 4))
        last = list(start)
        for k in range(1, steps + 1):
            p = (start[0] + dx * k / steps, start[1] + dy * k / steps)
            if V.wall_blocks(ter, start, p):
                break
            last = [p[0], p[1]]
        return [int(last[0]) + .5, int(last[1]) + .5] if not V.wall_blocks(ter, start, (int(last[0]) + .5, int(last[1]) + .5)) else last

    def _beast_spells(self, c: dict) -> bool:
        """A druid of 18th level casts in Wild Shape (Beast Spells); anyone else in a beast's shape can't."""
        char = self._sheet(c)
        return bool(char and char.class_level("Druid") >= 18 and not (c.get("form") or {}).get("conc_by"))

    def _in_silence(self, c: dict) -> bool:
        if not c.get("pos"):
            return False
        mine = G.footprint(c["pos"], c.get("span") or 1)
        return any(z.get("silence") and mine & z["_tiles"] for z in self._live_zones())

    def _cast_on(self, att: dict, sp: dict, tgt: Optional[dict], *, slot_level: Optional[int], caster_level: int, mod: int,
                 attack_bonus: int, dc: int, adv: Optional[str], dtype: Optional[str] = None, targets=None, point=None,
                 paid: bool = False, mm: Optional[dict] = None) -> str:
        """Play a spell out (the slot is already spent): the economy, the Counterspell window, then its effect."""
        mm = mm or {}
        spec = self._subc_spec(att, sp, SB.spec(sp))      # Circle of Mortality (subfeats_c.py)
        if mm.get("cost_override"):
            spec = dict(spec, cost=mm["cost_override"])
        level = slot_level or sp["level"]
        if tgt is not None and targets is None:
            targets = [tgt["id"]]
        aim = self._resolve_aim(att, spec, level, caster_level, targets, point, mm.get("more_targets", 0), mm.get("range_mult", 1))
        pair = sp["name"] == "Plane Shift" and any(re.search(r"plane shift \(only self and up to one incapacitated", e.get("text") or "", re.I)
                                                    for e in (self._monster(att) or {}).get("spellcasting") or [])
        if pair:                                                # a retriever's Plane Shift: itself and one incapacitated creature, willing
            others = [self._find_or_none(i) for i in dict.fromkeys(aim["targets"]) if i != att["id"]]
            if len(others) > 1 or any(o is None or not K.incapacitated(self._conds(o)) for o in others):
                raise ServiceError(f"{att['name']}'s Plane Shift takes only itself and one incapacitated creature.")
        if mm.get("name"):
            self._say(f"{att['name']} uses {mm['name']} ({mm['sp']} sorcery points)")
        if mm.get("name") == "Heightened Spell" and aim["targets"]:
            first = self._find_or_none(aim["targets"][0])
            if first:
                self._effect_on(first, "Heightened Spell", [], None, None, None, 1, att["name"], {"save_dis": ["all"], "once": True}, None, att["id"])
        if self._economy_on():
            cost = spec["cost"] if spec["cost"] != "long" else "free"
            self._pay(att, cost, sp["name"])
            if cost == "multi" and att.get("turn") is not None:
                att["turn"]["multi_spell"] = int(att["turn"].get("multi_spell") or 0) + 1       # a spell in place of one of the Multiattack's attacks
            EC.note_spell(att.get("turn"), spec["cost"], sp["level"])
            if sp["level"] == 0 and att.get("turn") is not None and spec["cost"] == "action":
                att["turn"]["last_cantrip"] = sp["name"]          # Illusionist's Bracers: it may come again as a bonus action (wondrous.py)
            if spec["cost"] == "action" and not self._sheet(att):
                self._war_magic(att, sp)                          # a monster's War Magic: a weapon attack as a bonus action (traits.py)
        self._subd_cast_note(att)                               # Magical Ambush: cast while hidden (subfeats_d.py)
        for e, v in self._fxs(att, "ends_on"):
            if "cast" in (v or []) and e in (att.get("effects") or []):
                self._effect_off(att, e, "cast a spell")
        self._arcane_ward(att, sp, level)
        self._synosto(att, sp, level)                           # Simbul's Synostodweomer: hit dice for the slot
        self._class_cast(att, sp, level)                        # a wild mage's surge (classfeats.py)
        self._nf_cast(att, sp, level)                           # Protective Ward, Life Manipulation, bonus-action cantrips (newfeats.py)
        R = self._new_r("spell", att, sp["name"], spell=sp["name"], slot_level=level, caster_level=caster_level, mod=mod,
                        attack_bonus=attack_bonus, dc=dc, adv=adv, dtype=dtype, targets=aim["targets"], tiles=[list(t) for t in aim["tiles"]],
                        point=aim["point"], summary_targets=None, mm=mm.get("name"), spec_cost=spec["cost"], lair=bool(mm.get("lair")), pair=pair)
        out = self._run_r(R)
        self._commit()
        return out

    def _step_spell(self, R: dict) -> str:
        att = self._find_or_none(R["actor"])
        sp = rules.spell(R["spell"])
        if R["stage"] == "start":
            R["stage"] = "counter"
            if att and att.get("pos") and R.get("mm") != "Subtle Spell":    # a subtle spell has no show: no circle either
                level = R["slot_level"] or sp["level"]
                self._vfx("glyph", id=att["id"], spell=sp["name"], tier=CR.vfx_tier(level),
                          src=self._magic_source(att, sp))
                return NEXT
            R["stage"] = "effect"
            return NEXT
        if R["stage"] == "counter":
            return self._window(R, "cast", "effect", attacker=R["actor"])
        if R["stage"] == "effect":
            R["stage"] = "done"
            if R.get("countered"):
                self._line(R, f"{att['name']}'s {sp['name']} is countered", "countered")
                return NEXT
            if sp["name"] != "Antimagic Field" and self._antimagic_blocks(att, R):
                self._line(R, f"{att['name']}'s {sp['name']} is suppressed by the Antimagic Field", "suppressed")
                return NEXT
            spec = SB.spec(sp)
            kind = (spec["area"] or {}).get("shape", "")
            sx = spec["special"]
            try:                                             # the damage it deals, for the colour of its effect
                parts = SB.fill(sx["parts"], R["mod"], R.get("dtype")) if "parts" in sx else \
                    CR.spell_plan(sp, R["slot_level"] or sp["level"], R["caster_level"], R["mod"], R.get("dtype"))["parts"]
            except Exception:  # noqa: BLE001 - only a colour is at stake
                parts = []
            parts = [p for p in parts or [] if p[1]] or [[0, R.get("dtype") or ""]]
            if R.get("tiles"):
                self._area_vfx(att, R["tiles"], parts, kind, R.get("point"))
            elif att is not None:
                self._vfx("cast", by=att["id"], ids=list(dict.fromkeys(R.get("targets") or [])), dtype=parts[0][1] or "",
                          src=self._magic_source(att, sp))
            child = self._apply_spell(R, att, sp)
            self._subc_spell_done(R, att, sp)                   # Voice of Authority: its attack comes after the spell's own (subfeats_c.py)
            if att is not None:
                self._shard_effects(R, att, sp)                 # an essence shard's property after Metamagic, a gem focus's blink (spellitems.py)
            if child:
                if R.get("mm") == "Careful Spell":
                    child["careful"] = True
                ch = self._sheet(att) if att else None
                if ch and sp.get("school") == "Evocation" and ch.class_level("Wizard") >= 2 \
                        and (ch.class_entry("Wizard") or {}).get("subclass") == "School of Evocation":
                    child["sculpt"] = 1 + (R["slot_level"] or sp["level"])         # Sculpt Spells: allies spared
                if R.get("mm") == "Empowered Spell":
                    child["empowered"] = True
                self._stack().append(child)
            if R.get("mm") == "Extended Spell" and att.get("concentrating"):
                c_ = att["concentrating"]
                if c_.get("rounds"):
                    c_["rounds"] = min(14400, c_["rounds"] * 2)
            return NEXT
        if R["stage"] == "done":
            names = ", ".join(self._find_or_none(t)["name"] for t in dict.fromkeys(R.get("targets") or []) if self._find_or_none(t))
            R["summary_targets"] = names or (f"{len(R.get('tiles') or [])} tiles" if R.get("tiles") else "—")
            return DONE
        return DONE

    def _magic_source(self, c: dict, sp: dict) -> str:
        """Where a caster's magic comes from, for the colour of its casting circle: the class that gives it the spell
        (its highest class otherwise), or a monster's kind."""
        ch = self._sheet(c)
        if ch:
            classes = sorted(ch.classes, key=lambda e: -int(e.get("level") or 0))
            given = next((e["name"] for e in classes if e["name"] in (sp.get("classes") or [])), classes[0]["name"] if classes else "")
            return MAGIC_SOURCE.get(given, "arcane")
        kind = str((self._monster(c) or {}).get("type") or "").lower()
        return "divine" if kind == "celestial" else "primal" if kind in ("fey", "beast", "plant") else "arcane"

    # ------------------------------------------------------------------ what a spell does
    def _apply_spell(self, R: dict, att: dict, sp: dict) -> Optional[dict]:
        """Play the spell's effect. Returns a strike record to run next (attacks and saves), or None."""
        spec = SB.spec(sp)
        if R.get("lair"):                                       # a lair action's spell: no concentration, over at the next round's count 20
            spec = dict(spec, duration=1)
        sx = spec["special"]
        key = spec["key"]
        level = R["slot_level"] or sp["level"]
        extra = max(0, level - sp["level"])
        mod, dc, dtype = R["mod"], R["dc"], R["dtype"]
        caster_level = R["caster_level"]
        caster = att["name"]
        label = sp["name"]
        kind = spec["kind"]
        ids = R["targets"]
        targets = [self._find_or_none(i) for i in dict.fromkeys(ids)]
        targets = [t for t in targets if t]
        conc = att["id"] if sp.get("concentration") and not R.get("lair") else None
        if sp.get("concentration") and not R.get("lair"):
            self._start_conc(att, sp)
        plan = CR.spell_plan(sp, level, caster_level, mod, dtype)
        buff = CR.buff_for(sp["name"]) or {}
        tok = self._conjure_token(att, sp, X.TOKENS[key], R, targets, conc) if key in X.TOKENS else None
        if sx.get("action"):
            a_def = (sx.get("action_options") or {}).get((dtype or "").lower()) or sx["action"]     # Bound Weapon: the weapon picked
            entry = self._grant_spell_action(att, sp, a_def, R, conc, targets, mod, dc, R["attack_bonus"], dtype or (spec["types"] or [None])[0], level)
            if sx["action"].get("near_targets"):                # Steel Wind Strike: the teleport after the attacks, beside one of the targets
                entry["def"]["near_ids"] = [t["id"] for t in targets]
                entry["rounds"] = 2
            if tok:                                             # the weapon strikes from where it floats
                entry["token"] = tok["id"]
                tok["conjured"]["sa"] = entry["id"]
        for a2 in sx.get("more_actions") or []:                 # Bigby's Hand: its other commands
            e2 = self._grant_spell_action(att, sp, a2, R, conc, targets, mod, dc, R["attack_bonus"], dtype or (spec["types"] or [None])[0], level)
            if tok:
                e2["token"] = tok["id"]
        if kind == "token":
            self._line(R, f"{caster} casts {label}: {tok['name'] if tok else label} appears", "appears")
            return None
        if sx.get("maintain"):                                  # kept up with an action on each later turn (spells._spell_turn_start)
            att["maintain"] = {"spell": sp["name"], "due": False, "kept": False}
        if key == "hex" and self._sheet(att) and self._sheet(att).has_option("Maddening Hex"):     # the invocation rides on the curse
            self._grant_spell_action(att, sp, {"name": "Maddening Hex", "cost": "bonus", "maddening": True, "range": 30}, R, conc, [], mod, dc,
                                     R["attack_bonus"], dtype, level)
        if sx.get("grant") and targets:
            for t in targets:
                g = dict(sx["grant"])
                g["parts"] = SB.fill(g.get("parts") or [], mod, dtype or (spec["types"] or ["fire"])[0])
                self._grant_spell_action(t, sp, g, R, conc, [], mod, dc, R["attack_bonus"], dtype, level, owner_of=att)
        if kind == "slots_back":                                # Mordenkainen's Lucubration: up to two spent slots of level 2 or lower (3, then 4, upcast)
            cap = 2 if level < 6 else 3 if level < 8 else 4
            char = self._sheet(att)
            back = []
            if char:
                used = char.d.get("slots_used") or {}
                for lv in range(cap, 0, -1):
                    while len(back) < 2 and int(used.get(str(lv)) or 0) > 0:
                        used[str(lv)] = int(used[str(lv)]) - 1
                        back.append(lv)
                char.save()
            txt = ("regains a level " + " and a level ".join(str(b) for b in back) + " spell slot") if back else "has no spent slot to recover"
            self._line(R, f"{caster} casts {label}: {txt}", txt)
            return None
        if sx.get("ward_option") and (dtype or "").lower() == "orderly ward":     # Conjure Constructs: temporary hit points instead of force damage
            for t in targets[:1]:
                n = max(0, roll(f"{1 + extra}d6") + mod)
                self._give_temp(t, n)
                self._line(R, f"{caster} casts {label}: Orderly Ward gives {t['name']} {n} temporary hit points", f"{t['name']}: {n} temp HP")
            return None
        if kind in ("utility", "summon_image", "self_transform", "buff_reaction") and not sx.get("effect"):
            if kind == "buff_reaction" and key == "shield":
                self._effect_on(att, "Shield", [], None, None, None, None, caster, {"ac": 5, "mm_immune": True}, None, att["id"],
                                until={"start": att["id"]})
                self._line(R, f"{caster} casts Shield: +5 AC until its next turn", "+5 AC")
                return None
            self._line(R, f"{caster} casts {label}" + (f" on {', '.join(t['name'] for t in targets)}" if targets else "") + " (no battle effect)",
                       "no battle effect")
            return None
        if kind == "summon":
            tgt = targets[0] if targets else None
            if R.get("point"):
                att = dict(att)
                self._summon_point = [int(R["point"][0]), int(R["point"][1])]
            line = self._summon(self._find(R["actor"]), sp, level, R["dtype"], tgt, attack=R["attack_bonus"], dc=R["dc"])
            self._summon_point = None
            self._line(R, line, line)
            return None
        if kind == "teleport":
            return self._spell_teleport(R, att, sp, sx, level, dc, mod)
        if kind == "time_stop":
            n = roll("1d4+1")
            att["extra_turns"] = n - 1
            self._line(R, f"{caster} stops time: {n} turns in a row", f"{n} turns")
            return None
        if kind == "zone":
            return self._spell_zone(R, att, sp, spec, level, dc, mod, conc, dtype)
        if kind == "weapon_spell":
            return self._weapon_spell(R, att, sp, sx, caster_level, mod)
        if kind in ("prismatic", "surge"):
            return self._random_rays(att, label, kind, targets, dc, conc)
        if kind == "life_transference":                         # the caster pays in necrotic damage; the target heals twice that
            n = roll(f"{4 + extra}d8")
            line = self._deal_rolled(att, [[n, "necrotic"]], label=label)
            for t in targets[:1]:
                self._heal(t, 2 * n)
                line += f"; {t['name']} regains {2 * n} hit points"
            self._line(R, f"{caster} casts {label}: {line}", line)
            return None
        if kind == "pool":
            dice, more, cond, rounds = X.POOLS[key]
            n, d = dice.split("d")
            pool = int(roll_dice(f"{int(n) + (int(more.split('d')[0]) * extra)}d{d}").total)
            hit = []
            for c in sorted(targets, key=self._hp_of):
                hp = self._hp_of(c)
                if cond in self._conds(c) or hp > pool or self._is_out(c) or hp <= 0:
                    continue
                if key == "sleep" and "Charmed" in self._defenses(c).get("immune_cond", set()):      # "creatures immune to being charmed aren't affected"
                    continue
                pool -= hp
                self._effect_on(c, label, [cond], None, None, None, rounds, caster, {"ends_on": ["damage"]} if cond == "Unconscious" else None,
                                None, att["id"])
                hit.append(c["name"])
            self._line(R, f"{caster} casts {label}: " + (", ".join(hit) + f" now {cond.lower()}" if hit else "no effect"),
                       (", ".join(hit) + f" {cond.lower()}") if hit else "no effect")
            return None
        if kind == "power_word":
            if key in X.POWER_WORDS:
                what, limit = X.POWER_WORDS[key]
            else:
                what, limit = "pain", sx.get("limit", 100)
            for tgt in targets[:1]:
                hp = self._hp_of(tgt)
                if hp > limit:
                    self._line(R, f"{caster} casts {label} on {tgt['name']}: too healthy ({hp} > {limit}), no effect", "no effect")
                    continue
                if what == "kill":                                  # the creature dies: no death saves
                    self._line(R, self._kill(tgt, att, label), "dies")
                elif what == "stun":
                    self._effect_on(tgt, label, ["Stunned"], "con", dc, "end", None, caster, None, None, att["id"])
                    self._line(R, f"{caster} casts {label} on {tgt['name']}: stunned", "stunned")
                else:
                    e = sx.get("effect") or {}
                    self._effect_on(tgt, label, [], "con", dc, "end", None, caster, e.get("mods"), None, att["id"])
                    self._line(R, f"{caster} casts {label} on {tgt['name']}: {e.get('note', '')}", e.get("note", ""))
            return None
        if kind == "divine_word":                                 # PHB: by current hit points after a failed CHA save
            for c in targets:
                res = self._saving_throw(c, "cha", dc, spell=True, source=att, label=label)
                self._line(R, f"{c['name']} CHA save: d20 {res['kept']}{self._save_mode_note(res)} = {res['total']} vs DC {dc} — "
                           + ("success" if res["ok"] else "failed"))
                if res["ok"]:
                    continue
                hp = self._hp_of(c)
                kind_of = str((self._monster(c) or {}).get("type") or "").lower()
                if kind_of in ("celestial", "elemental", "fey", "fiend"):
                    self._line(R, f"{c['name']} is banished to its home plane", "banished")
                    self._take_out(c)
                elif hp <= 20:
                    self._deal_rolled(c, [[hp + (self._sheet(c).max_hp if self._sheet(c) else 0), "force"]], by=att, label=label)
                    if self._sheet(c):
                        self._sheet(c).d["death_saves"] = {"success": 0, "failure": 3}
                        self._sheet(c).save()
                    self._line(R, f"{c['name']} is killed by the word", "killed")
                else:
                    conds, rounds = ((["Blinded", "Deafened", "Stunned"], 600) if hp <= 30 else (["Blinded", "Deafened"], 100) if hp <= 40
                                     else (["Deafened"], 10) if hp <= 50 else ([], None))
                    if conds:
                        self._effect_on(c, label, conds, None, None, None, rounds, caster, None, None, att["id"])
                        self._line(R, f"{c['name']} is {', '.join(x.lower() for x in conds)}", ", ".join(x.lower() for x in conds))
            return None
        if kind == "revive":
            names = []
            for c in targets:
                if key == "spare the dying":                      # a dying creature becomes stable at 0 HP
                    char = self._sheet(c)
                    if char and self._hp_of(c) <= 0 and not self._dead(c):
                        char.d["death_saves"] = {"success": 3, "failure": 0}
                        char.save()
                        names.append(c["name"])
                    continue
                if self._hp_of(c) <= 0:
                    self._heal(c, 1 if key == "revivify" else max(1, self._max_hp(c)), revive=True)
                    names.append(c["name"])
            self._line(R, f"{caster} casts {label}: " + (", ".join(names) + " back on their feet" if names else "nobody to revive"),
                       "revived" if names else "no effect")
            return None
        if kind == "cleanse":
            conds = X.CLEANSES[key]
            for c in targets:
                if conds == "all":                              # Dispel Magic: the spells on the target, not those it keeps up elsewhere
                    own = False
                    for eff in list(c.get("effects") or []):
                        if not eff.get("feature") and not eff.get("trait"):
                            if self._dispel_fails(att, R, eff["name"], level):
                                continue
                            own = own or eff.get("conc_by") == c["id"]
                            self._effect_off(c, eff, "dispelled")
                            self._spell_left(eff)
                            self._subd_surge(att)               # Power Surge: magic stolen from a dispelled spell (subfeats_d.py)
                    for z in [z for z in self.b.get("zones") or [] if z.get("owner") == c["id"]]:
                        if self._dispel_fails(att, R, z["name"], level):
                            continue
                        own = True
                        self._zone_off(z, "dispelled")
                    if own and c.get("concentrating"):
                        self._drop_conc(c, "dispelled")
                    keeper = self._find_or_none(c.get("summon_conc")) if c.get("summon_conc") is not None else None
                    if keeper is not None and (keeper.get("concentrating") or {}).get("spell") == c.get("summon_spell"):
                        self._drop_conc(keeper, f"{c['name']} dispelled")      # a conjured creature: the conjuring ends
                elif key in X.HEALS and (self._monster(c) or {}).get("type") in ("undead", "construct"):
                    continue                                    # Heal, Power Word Heal: no effect on undead or constructs
                else:
                    self._clear_conditions(c, [x for x in conds if x in self._conds(c)][:1] if key in X.ONE_ONLY else conds)
            if key not in X.HEALS:
                self._line(R, f"{caster} casts {label} on {', '.join(c['name'] for c in targets) or 'nobody'}", "cured")
                return None
        if kind == "heal" or (plan["kind"] == "heal" and kind != "buff") or key in X.HEALS:      # (a buff worded with "regains": Alustriel's Mooncloak)
            lines = []
            for c in sorted(targets, key=lambda x: self._hp_of(x) - self._max_hp(x)) if key == "mass heal" else targets:
                if (self._monster(c) or {}).get("type") in ("undead", "construct") and key != "regenerate":
                    lines.append(f"{c['name']} (no effect on {self._monster(c)['type']})")
                    continue
                life = self._sheet(att) if att else None
                life = life if life and life.has_feature("Disciple of Life") and sp["level"] > 0 else None
                if key == "mass heal":                          # 700 hit points shared out, the most hurt first
                    pool = R.setdefault("heal_pool", 700)
                    n = min(pool, max(0, self._max_hp(c) - self._hp_of(c)))
                    R["heal_pool"] = pool - n
                elif "fixed" in plan:
                    n = (plan["fixed"] if isinstance(plan["fixed"], int) else roll(plan["fixed"])) + plan["per_level"]
                else:
                    supreme = life is not None and life.has_feature("Supreme Healing")       # Life 17: dice at their maximum
                    supreme = supreme or bool(self._fx(c, "max_heal"))                    # Beacon of Hope
                    supreme = supreme or self._subc_max_heal(att, c)                      # Circle of Mortality (subfeats_c.py)
                    n = sum(_max_dice(d) if supreme else roll(d) for d, _t in plan["parts"]) + mod
                    if plan.get("heal_extra"):
                        n += _max_dice(plan["heal_extra"]) if supreme else roll(plan["heal_extra"])
                    if not supreme:
                        n = self._subd_empowered_heal(att, plan, n, mod)      # Empowered Healing (subfeats_d.py)
                if life is not None:
                    n += 2 + level                              # Life domain: Disciple of Life
                n += self._subc_focus_heal(R, att, sp)          # Spiritual Focus: +1d6 on one healing roll (subfeats_c.py)
                n = max(0, n)
                if self._heal(c, n):                         # (no line for a heal that did nothing)
                    char = self._sheet(c) if c["kind"] == "pc" else None         # the HP after it, as on damage lines
                    now = f"{char.current_hp}/{char.max_hp} HP" if char else f"{c['hp']}/{c['max_hp']} HP"
                    self._roll_line(att, "💚", f"{label} healing → {c['name']}", n, now)
                if key in X.CLEANSES and X.CLEANSES[key] != "all":
                    self._clear_conditions(c, X.CLEANSES[key])
                lines.append(f"{c['name']} +{n}" if n < 9000 else f"{c['name']} fully healed")
            lines += self._class_healed(att, targets, sp, level)     # Blessed Healer, Starry Form's chalice (classfeats.py)
            self._line(R, f"{caster} casts {label}: heals " + ", ".join(lines), ", ".join(lines))
            return None
        if sx.get("action") and sx["action"].get("move_mark") and kind == "buff":
            pass
        if kind in ("buff", "self_effect") or (buff and not buff.get("on_fail") and kind not in ("save", "attack", "auto")):
            return self._spell_buff(R, att, sp, spec, buff, targets, level, extra, mod, conc, dtype)
        if key == "plane shift" and R.get("pair"):                # itself and the one it holds: no roll, they go together
            gone = [att] + [t for t in targets if t is not att][:1]
            for t in gone:
                self._take_out(t)
            self._line(R, f"{caster} casts {label}: {' and '.join(t['name'] for t in gone)} shift to another plane", "shifted away")
            return None
        if key == "levitate":                                     # a willing creature (you, a friend) is lifted without a save; a foe saves
            willing = [t for t in targets if t is att or not self._hostile(att, t)]
            for t in willing:
                self._effect_on(t, label, [], None, None, None, 100, caster, {"speed_set": 0, "fly_set": 0, "levitating": True}, conc, att["id"])
                self._line(R, f"{t['name']} rises into the air (levitating, no save): it can't walk, only drift up and down 20 ft", "levitating")
            targets = [t for t in targets if t not in willing]
            if not targets:
                return None
        # ---- attacks, saves, automatic damage
        parts = SB.fill(sx["parts"], mod, dtype or (spec["types"] or [None])[0]) if "parts" in sx else plan["parts"]
        if "parts" in sx and sx.get("up"):
            parts = SB.upcast(parts, sx["up"], extra, sx.get("up_every", 1))
        if key == "toll the dead" and targets and self._hp_of(targets[0]) < self._max_hp(targets[0]) and parts:
            parts = [[str(parts[0][0]).replace("d8", "d12"), parts[0][1]]]
        char = self._sheet(att)
        if parts and char and mod > 0 and (
                sp["level"] == 0 and char.class_level("Cleric") >= 8 and char.class_entry("Cleric").get("subclass") in POTENT
                or sp.get("school") == "Evocation" and char.class_level("Wizard") >= 10
                and char.class_entry("Wizard").get("subclass") == "School of Evocation"):
            parts = [list(p) for p in parts] + [[str(mod), parts[0][1]]]     # Potent Spellcasting, Empowered Evocation
        if parts and att.get("effects"):
            parts = self._subb_overchannel(att, sp, parts, level)       # Evocation 14: maximum damage (subfeats_b.py)
        parts = self._subc_focus_parts(R, att, sp, parts)               # Spiritual Focus: +1d6 on one damage roll (subfeats_c.py)
        if kind == "attack" or (plan["kind"] == "attack" and kind not in ("save", "auto")):
            atk = {"bonus": R["attack_bonus"], "n": 1, "melee": spec["atk_type"] == "melee", "spell": True, "magical": True,
                   "parts": parts, "adv": R["adv"]}
            if self._feat(att, "spell_sniper") or sx.get("ignore_cover"):    # and ignore half and three-quarters cover (total cover still blocks)
                atk["ignore_cover"] = True                      # (Spellfire Flare: "no benefit from Half Cover or Three-Quarters Cover")
            if sx.get("crit"):                                  # Blade of Disaster: a crit on 18-20, 8d12 more
                atk.update(crit_any=True, crit_at=int(sx["crit"]), crit_bonus=sx.get("crit_bonus"))
            char = self._sheet(att)
            for _e, _it in (char._active_items() if char else []):     # a Staff of the Ivory Claw: a spell attack's critical hit adds 3d6 radiant
                _m = re.search(r"critical hit with a spell attack, the target takes an extra (\d+d\d+) (\w+) damage", _it.get("text") or "")
                if _m:
                    atk["crit_bonus"] = list(atk.get("crit_bonus") or []) + [[_m.group(1), _m.group(2)]]
            if sp["name"] == "Eldritch Blast" and char and char.has_option("Agonizing Blast") and parts:
                parts = [[f"{parts[0][0]}+{max(0, char.mod('cha'))}", parts[0][1]]] + parts[1:]
                atk["parts"] = parts
            if spec["target"]["type"] == "split":
                counts = {}
                for i in R["targets"]:
                    counts[i] = counts.get(i, 0) + 1
                order = list(dict.fromkeys(R["targets"]))
                strikes = []
                for i in order:
                    a = dict(atk, n=counts[i])
                    if sp["name"] == "Scorching Ray" and parts:
                        a["parts"] = [parts[0]]
                    S_ = self._strike(att, label, [i], mode="attack", atk=a, spell=True, conc=conc)
                    if sp["name"] == "Eldritch Blast" and char:      # invocations riding on a beam that hits
                        S_["spell_extra"] = {"push": 10 if char.has_option("Repelling Blast") else None,
                                             "grasp": char.has_option("Grasp of Hadar"), "lance": char.has_option("Lance of Lethargy")}
                    strikes.append(S_)
                first = strikes[0] if strikes else None
                if first:
                    first["follow"] = strikes[1:]
                return first
            if sx.get("n"):
                atk["n"] = sx["n"]
            on_hit = None
            if sx.get("on_hit") and (sx["on_hit"].get("mods") or sx["on_hit"].get("conds")):
                oh_mods = sx["on_hit"].get("mods")
                disease = (sx.get("options") or {}).get((dtype or (spec["types"] or [""])[0]).lower())      # Contagion: the disease three failed saves bring on
                if disease:
                    oh_mods = dict(oh_mods or {}, fail_effect=disease)
                on_hit = {"name": label, "mods": oh_mods, "conds": sx["on_hit"].get("conds"), "note": sx["on_hit"].get("note"), "rounds": None,
                          "until": self._until(sx["on_hit"].get("until"), att, targets[0]) if targets else None,
                          "repeat_ab": sx["on_hit"].get("repeat_ab"), "dc": dc}       # Ray of Enfeeblement: a save at the end of each turn
            rider = None
            if sx.get("rider"):
                rider = dict(sx["rider"], dc=dc, spell=True)
            S = self._strike(att, label, [t["id"] for t in targets], mode="attack", atk=atk, spell=True, on_hit=on_hit, rider=rider, conc=conc)
            S["spell_extra"] = {"pull": (sx.get("on_hit") or {}).get("pull"), "drain": sx.get("drain"), "dot": sx.get("dot"), "level": level,
                                "extra": extra, "miss_half": sx.get("miss_half"), "explode": sx.get("explode"), "mod": mod, "dc": dc,
                                "plane_shift": sx.get("plane_shift"), "leap": sx.get("leap"), "self_cost": sx.get("self_cost")}
            return S
        if sx.get("bloom") and R.get("tiles"):                 # Wither and Bloom: one friend in the area heals (a hit die + your modifier)
            friends = [o for o in G.creatures_in({tuple(t) for t in R["tiles"]}, self.b["combatants"])
                       if not self._hostile(att, o) and self._alive(o) and self._hp_of(o) < self._max_hp(o)]
            if friends:
                f = min(friends, key=lambda o: self._hp_of(o) - self._max_hp(o))
                n = max(0, roll(f"{1 + extra}d8") + mod)
                if self._heal(f, n):
                    self._line(R, f"{f['name']} regains {n} hit points ({label})", f"+{n} HP")
        if sx.get("undead_temp"):                               # Negative Energy Flood on an undead: no save, temporary HP instead
            for t in [t for t in targets if str((self._monster(t) or {}).get("type") or "").lower().startswith("undead")]:
                n = roll(sx["undead_temp"]) // 2
                self._give_temp(t, n)
                self._line(R, f"{t['name']} drinks the negative energy: {n} temporary hit points", f"+{n} temp HP")
                targets = [x for x in targets if x is not t]
                if not targets:
                    return None
        if sx.get("calm"):                                      # Calm Emotions: friends' charm and fear are suppressed; foes turn indifferent
            friends = [t for t in targets if t is att or not self._hostile(att, t)]
            for t in friends:
                self._clear_conditions(t, ["Charmed", "Frightened"])
            if friends:
                self._line(R, f"{caster} calms {', '.join(t['name'] for t in friends)}: no longer charmed or frightened", "calmed")
            targets = [t for t in targets if t not in friends]
        if sx.get("kill_below"):                                # Wail of the Banshee: 50 hit points or fewer dies; those who can't hear are spared
            rest = []
            for t in targets:
                if "Deafened" in self._conds(t) or self._is_out(t):
                    self._line(R, f"{t['name']} can't hear the wail: unaffected", "unaffected")
                elif self._hp_of(t) <= int(sx["kill_below"]):
                    self._line(R, self._kill(t, att, label), "dies")
                else:
                    rest.append(t)
            targets = rest
            if not targets:
                return None
        save_ab = sx.get("save") or plan.get("save") or ((sp.get("save") or [""])[0][:3].lower() if sp.get("save") else None)
        if (kind == "save" or plan["kind"] == "save" or save_ab) and sx.get("kind") != "auto":     # Heat Metal: the save isn't for the damage
            conds = sx["conds"] if "conds" in sx else plan["conds"]
            if key in X.CONDS and "conds" not in sx:
                conds, rep, rounds = X.CONDS[key]
            else:
                rep, rounds = sx.get("repeat", plan["repeat"]), sx.get("rounds", plan["rounds"] or spec["duration"])
            eff = sx.get("effect") or ({"mods": dict(buff["mods"]), "note": buff.get("note")} if buff.get("on_fail") else None)
            pick = (dtype or (spec["types"] or [""])[0]).lower()
            opt = (sx.get("options") or {}).get(pick) or {}      # Eyebite's three effects, Blindness/Deafness, Bestow Curse: the one picked replaces the rest
            if opt.get("min_level") and level < int(opt["min_level"]):
                opt = {}                                        # Axii's Puppet: only from a 3rd-level slot
            if opt:
                conds, rep, rounds = opt.get("conds", conds), opt.get("repeat", rep), opt.get("rounds", rounds)
                eff = opt.get("effect", eff)
            mods = {k: ((v[0], pick) if isinstance(v, tuple) and len(v) == 2 and v[1] == "$type" else v)      # Elemental Bane's type
                    for k, v in ((eff or {}).get("mods") or {}).items()} if eff and eff.get("mods") is not None else None
            if mods and isinstance(mods.get("death_burst"), dict):     # Walking Bomb: the burst's DC, and more dice from a higher slot
                db = mods["death_burst"]
                mods["death_burst"] = dict(db, dc=dc, parts=SB.upcast(db["parts"], db.get("up"), extra))
            if sx.get("disperse") and R.get("tiles"):            # Aard: the blast blows the clouds in its area away
                self._disperse(R["tiles"])
            sv = {"ab": save_ab or "con", "dc": dc, "half": sx.get("half", plan["half"]), "conds": conds, "repeat": rep,
                  "rounds": rounds if (conds or eff) else None, "mods": mods, "note": (eff or {}).get("note"),
                  "until": (eff or {}).get("until"), "push": sx.get("push"), "push_size": sx.get("push_size"), "prone": sx.get("prone"),
                  "ends_on": opt.get("ends_on", sx.get("ends_on")),
                  "full": sx.get("full"), "adv_hostile": bool(_FIGHTING.search(sp.get("text", ""))),
                  "no_cover": bool(re.search(r"no benefit from cover", sp.get("text", ""), re.I)), "no_save": sx.get("auto_hit"),
                  "dis_types": sx.get("dis_types"), "drop_conc": sx.get("drop_conc"), "auto_pass_types": sx.get("auto_pass_types"),
                  "exhaust": sx.get("exhaust"), "exhaust_cap": sx.get("exhaust_cap"), "ends_on_ok": sx.get("ends_on_ok")}
            if sx.get("pull"):
                sv["pull"] = sx["pull"]
            if key == "command":
                self._command_word(sv, pick)
            S = self._strike(att, label, [t["id"] for t in targets], mode="save", sv=sv, parts=parts, spell=True, conc=conc,
                             origin=R.get("point"))
            S["spell_extra"] = {"transform": (R.get("dtype") or "Giant Toad|MM") if sx.get("transform") else None, "dot": sx.get("dot"), "min_hp": sx.get("min_hp"),
                                "dust": sx.get("dust"), "level": level,
                                "extra": extra, "drain": sx.get("drain"), "teleport_target": sx.get("teleport_target"), "dc": dc,
                                "sink": sx.get("sink") and R.get("point"), "max_cut": sx.get("max_cut"), "antagonize": sx.get("antagonize"),
                                "tether": sx.get("tether"), "jostle": sx.get("jostle"), "explode": sx.get("explode")}
            if sx.get("leave_zone") and R.get("tiles"):
                self._add_zone(att, label, R["tiles"], dict(sx["leave_zone"]), rounds=sx["leave_zone"].get("rounds"), conc=None, dc=dc)
            if sx.get("storm") and R.get("tiles"):              # Storm of Vengeance: the cloud stays; rounds 2-10 in _spell_turn_items
                self._add_zone(att, label, R["tiles"], {"storm": True}, rounds=spec["duration"], conc=conc, dc=dc, point=R.get("point"))
            if sx.get("fissure") and R.get("tiles"):            # Gravity Fissure: those within 10 ft of the line save or are hurt and pulled in
                line = {tuple(t) for t in R["tiles"]}
                ring, to = [], {}
                for o in self.b["combatants"]:
                    if o is att or not o.get("pos") or self._is_out(o) or G.footprint(o["pos"], o.get("span") or 1) & line:
                        continue
                    near = min(line, key=lambda t: (G.distance_to_tile(o["pos"], o.get("span") or 1, t),
                                                    abs(t[0] - o["pos"][0]) + abs(t[1] - o["pos"][1])))     # straight across
                    if G.distance_to_tile(o["pos"], o.get("span") or 1, near) <= 10:
                        ring.append(o["id"])
                        to[str(o["id"])] = [near[0] + .5, near[1] + .5]
                if ring:
                    S2 = self._strike(att, f"{label} (pull)", ring, mode="save", sv={"ab": "con", "dc": dc, "half": False}, parts=parts, spell=True, conc=conc)
                    S2["spell_extra"] = {"sink_to": to}
                    S.setdefault("follow", []).append(S2)
            if sx.get("self_effect"):                           # Draconic Transformation: the caster changes as well
                self._effect_on(att, label, [], None, None, None, spec["duration"], caster, dict(sx["self_effect"]["mods"]), conc, att["id"])
                self._line(R, f"{caster}: {sx['self_effect']['note']}", sx["self_effect"]["note"])
            return S
        if parts:
            if sp["name"] == "Magic Missile":
                counts = {}
                for i in R["targets"]:
                    counts[i] = counts.get(i, 0) + 1
                per = {i: [["1d4+1", "force"]] * n for i, n in counts.items()}
                return self._strike(att, label, list(counts), mode="auto", per_target=per, spell=True, conc=conc)
            S = self._strike(att, label, [t["id"] for t in targets], mode="auto", parts=parts, spell=True, conc=conc)
            S["spell_extra"] = {"drain": sx.get("drain"), "hamper": sx.get("hamper")}
            return S
        self._line(R, f"{caster} casts {label}" + (f" on {', '.join(t['name'] for t in targets)}" if targets else ""), "")
        return None

    def _max_hp(self, c: dict) -> int:
        char = self._sheet(c)
        return char.max_hp if char else c["max_hp"]

    def _spell_buff(self, R, att, sp, spec, buff, targets, level, extra, mod, conc, dtype) -> None:
        sx = spec["special"]
        caster, label = att["name"], sp["name"]
        if spec["target"]["type"] == "self" or buff.get("self"):
            targets = [att]
        if sx.get("effect"):
            e = sx["effect"]
            e = (sx.get("options") or {}).get((dtype or (spec["types"] or [None])[0] or "").lower()) or e     # Guardian of Nature's form, Enhance Ability's ability
            mods = {k: (list(v) if isinstance(v, list) else v) for k, v in (e.get("mods") or {}).items()}
            for lv, more in sorted((sx.get("slot_mods") or {}).items()):     # Magic Weapon +2 from a 4th-level slot...
                if level >= lv:
                    mods.update(more)
            pick = (dtype or (spec["types"] or [None])[0] or "").lower()
            other = {"fire": "cold", "cold": "fire"}.get(pick, pick)
            for k, v in list(mods.items()):
                if v == ["$other"]:
                    mods[k] = [other]
                elif isinstance(v, tuple) and len(v) == 2 and v[1] == "$type":
                    mods[k] = (v[0], pick)
            if mods.get("resist") == "ALL_BUT_PSYCHIC":
                from .modifiers import TYPES
                mods["resist"] = [t for t in TYPES if t != "psychic"]
            if isinstance(mods.get("lantern"), dict):           # Spirit Lantern: as many soul fragments as the caster's spellcasting modifier
                mods["lantern"] = dict(mods["lantern"], frags=0, max=max(0, mod))
            if mods.get("synosto") == "MOD":                    # Simbul's Synostodweomer: the caster's modifier rides on the healing
                mods["synosto"] = max(0, mod)
            if isinstance(mods.get("random_bolts"), dict):      # Storm Call: the caster's DC; one more bolt for each slot level above
                mods["random_bolts"] = dict(mods["random_bolts"], dc=R["dc"], n=int(mods["random_bolts"]["n"]) + extra)
            if mods.get("fate_n"):                              # Norns' Weave: the d20s, rolled and recorded as it is cast
                mods["fate_dice"] = [self.rng.randint(1, 20) for _ in range(int(mods.pop("fate_n")))]
                self._say(f"{caster} spins the threads of fate: {', '.join(map(str, mods['fate_dice']))}")
            rounds = sx.get("rounds") or spec["duration"]
        else:
            mods = {k: (list(v) if isinstance(v, list) else v) for k, v in buff.get("mods", {}).items()}
            if buff.get("choose"):
                pick = (dtype or buff["choose"][0]).lower()
                mods = {k: ([pick] if v == ["$type"] else v) for k, v in mods.items()}
            if buff.get("once"):
                mods["once"] = True
            rounds = buff.get("rounds") or spec["duration"]
            e = {"note": buff.get("note", "")}
        up, every = sx.get("up") or buff.get("up"), sx.get("up_every") or buff.get("up_every") or 1
        if up and extra and isinstance(mods.get("dmg"), tuple) and str(mods["dmg"][0]) not in ("0", ""):    # Searing Smite, Spirit Shroud
            mods["dmg"] = (SB.upcast([[mods["dmg"][0], ""]], up, extra, every)[0][0], mods["dmg"][1])
        if up and extra and isinstance(mods.get("trail"), tuple):        # Ashardalon's Stride: hotter and faster when upcast
            mods["trail"] = (SB.upcast([[mods["trail"][0], ""]], up, extra)[0][0], mods["trail"][1])
            mods["speed"] = int(mods.get("speed") or 0) + int(sx.get("speed_up") or 0) * extra
        if buff.get("up_rider") and extra and mods.get("rider"):           # Hail of Thorns' burst, Ensnaring Strike's thorns
            rd = dict(mods["rider"])
            if rd.get("parts"):
                rd["parts"] = SB.upcast(rd["parts"], buff["up_rider"], extra)
            if rd.get("dot"):
                rd["dot"] = dict(rd["dot"], dice=SB.upcast([[rd["dot"]["dice"], ""]], buff["up_rider"], extra)[0][0])
            mods["rider"] = rd
        lines = []
        for c in targets:
            if sx.get("reduce") and c is not att and self._hostile(att, c):     # Enlarge/Reduce on a foe: a Con save, then it shrinks
                res = self._apply_save(dict(R, conc=conc), att, c, {"ab": "con", "dc": R["dc"], "spell": True, "rounds": rounds,
                                                                    "mods": dict(sx["reduce"]["mods"]), "note": sx["reduce"]["note"]})
                lines.append(f"{c['name']}: " + ("resists" if res["ok"] else "reduced"))
                continue
            temp = e.get("temp") or buff.get("temp") or sx.get("temp")
            if temp:
                t = mod if temp == "MOD" else roll(temp) + (buff.get("temp_per_level") or sx.get("temp_per_level") or 0) * extra
                if buff.get("max_up"):                          # Aid: the maximum and current hit points go up (not temporary)
                    more = max(0, t - int(c.get("aided") or 0))  # two Aids don't add up: the bigger one counts
                    c["aided"] = max(t, int(c.get("aided") or 0))
                    char = self._sheet(c)
                    if char and more:
                        char.d["hp"]["drain"] = int(char.d["hp"].get("drain") or 0) - more     # a negative drain: gone after a long rest
                        char.save()
                        self._heal(c, more, revive=True)        # (a dying friend is back up)
                    elif more and c["hp"] > 0:
                        c["max_hp"] += more
                        c["hp"] += more
                    lines.append(f"{c['name']}: +{more} hit points (maximum too)")
                else:
                    self._give_temp(c, max(0, t))
                    lines.append(f"{c['name']}: {t} temporary HP")
            if sx.get("cure"):                                  # Protection from Poison: the poison it already suffers is neutralized
                self._clear_conditions(c, sx["cure"])
            conds = [x for x in sx.get("conds_on") or []]
            if mods or conds or not temp:
                self._effect_on(c, label, conds, None, None, None, rounds, caster, dict(mods), conc if (mods or conds) else None, att["id"])
                lines.append(f"{c['name']}: {e.get('note') or buff.get('note') or label}")
            if sx.get("dash"):
                from . import economy as EC2
                EC2.dash(c.get("turn"))
        if sx.get("ground") and att.get("pos"):                 # Investiture of Ice: the ground around the caster, wherever it goes
            area = {"shape": "emanation", "size": int(sx["ground"]["size"]), "origin": "caster"}
            tiles = G.area_for(area, att["pos"], att.get("span") or 1, None, *self._bounds())
            self._add_zone(att, f"{label}: icy ground", tiles, {"follow": True, "difficult": "others"}, rounds=rounds, conc=conc, dc=R["dc"], area=area)
            lines.append("the ground around it is icy difficult terrain")
        self._line(R, f"{caster} casts {label}: " + "; ".join(lines), "; ".join(lines))

    def _grant_spell_action(self, owner: dict, sp: dict, a: dict, R: dict, conc, targets, mod, dc, attack_bonus, dtype, level, owner_of=None, **kw):
        extra = max(0, level - sp["level"])
        entry = {"id": self.b.get("sa_next", 1), "name": CR.shown(a["name"]), "spell": sp["name"], "cost": a.get("cost", "action"),
                 "conc_by": conc, "rounds": a["rounds"] if "rounds" in a else SB.spec(sp)["duration"], "def": dict(a), "mod": mod, "dc": dc, "attack": attack_bonus,
                 "level": level, "target": targets[0]["id"] if targets and a.get("same_target") else None, "zone": None,
                 "parts": SB.upcast(SB.fill(a.get("parts") or a.get("auto") or [], mod, dtype),
                                    a["up"] if "up" in a else SB.spec(sp)["special"].get("up"), extra,      # Witch Bolt's arcs: no upcast
                                    SB.spec(sp)["special"].get("up_every", 1), SB.spec(sp)["special"].get("up_offset", 0)),   # Spiritual Weapon: every two levels
                 "uses": a["uses"] + int(a.get("uses_up") or 0) * extra if a.get("uses") is not None else None}     # more motes / meteors upcast
        self.b["sa_next"] = entry["id"] + 1
        owner.setdefault("spell_actions", []).append(entry)
        return entry

    def _weapon_spell(self, R, att, sp, sx, caster_level, mod):
        """Green-Flame Blade, Booming Blade: a melee weapon attack with the spell's extra effect."""
        char = self._sheet(att)
        tid = (R["targets"] or [None])[0]
        tgt = self._find_or_none(tid)
        if not tgt:
            return None
        if char:
            weapons = self._blade_weapons(char)
            w = max(weapons, key=lambda x: x["attack"]) if weapons else None
            if not w:
                return None
            atk = self._weapon_atk(att, w)
        else:
            atk = {"bonus": R["attack_bonus"], "n": 1, "melee": True, "weapon": True, "parts": [["1d6", "slashing"]]}
        atk["n"] = 1
        bonus = SB.cantrip_die(sx["cantrip_parts"], caster_level)
        if bonus and bonus != "0":
            atk["parts"] = list(atk["parts"]) + [[bonus, sx["type"]]]
        S = self._strike(att, sp["name"], [tgt["id"]], mode="attack", atk=atk, magical=True)
        S["spell_extra"] = {"splash": sx.get("splash"), "mark": sx.get("mark"), "caster_level": caster_level, "mod": mod}
        return S

    RAYS = {1: ("red", "fire"), 2: ("orange", "acid"), 3: ("yellow", "lightning"), 4: ("green", "poison"), 5: ("blue", "cold"),
            6: ("indigo", ["Restrained"]), 7: ("violet", ["Blinded"])}
    SURGES = {1: ("apple pie", "wis", ["Charmed"]), 2: ("flowers", "dex", ["Blinded"]), 3: ("giggles", "wis", ["Incapacitated"]), 4: ("sludge", None, [])}

    def _random_rays(self, att, label, kind, targets, dc, conc):
        """Prismatic Spray: a d8 ray for each creature (an 8 is two rays); Nathair's Mischief: one d4 surge for the whole cube."""
        def sv(ab, half, conds, rounds=None, repeat=None):
            return {"ab": ab, "dc": dc, "half": half, "conds": conds, "repeat": repeat, "rounds": rounds, "mods": None, "note": None,
                    "until": None, "push": None, "prone": None, "ends_on": None}
        strikes = []
        if kind == "surge":
            what, ab, conds = self.SURGES[int(roll("1d4"))]
            if not ab or not targets:
                self._say(f"{att['name']} casts {label}: {what} - the ground turns to sludge (difficult terrain)")
                return None
            self._say(f"{att['name']} casts {label}: {what}")
            return self._strike(att, f"{label} ({what})", [t["id"] for t in targets], mode="save", sv=sv(ab, False, conds, rounds=1),
                                spell=True, conc=conc)
        for t in targets:
            n = int(roll("1d8"))
            rays = [n] if n < 8 else [int(roll("1d7")), int(roll("1d7"))]
            for r in rays:
                colour, what = self.RAYS[r]
                if isinstance(what, str):
                    S = self._strike(att, f"{label} ({colour})", [t["id"]], mode="save", sv=sv("dex", True, []), parts=[["10d6", what]], spell=True)
                else:
                    S = self._strike(att, f"{label} ({colour})", [t["id"]], mode="save", sv=sv("dex", False, what, rounds=10, repeat="end"), spell=True)
                strikes.append(S)
        if not strikes:
            return None
        strikes[0]["follow"] = strikes[1:]
        return strikes[0]

    def _arcane_ward(self, att: dict, sp: dict, level: int):
        """School of Abjuration: an abjuration spell of 1st level or higher raises the Arcane Ward (2 x wizard level + Int
        hit points) or, when it is already up, restores 2 x the spell's level to it."""
        char = self._sheet(att)
        if not char or sp.get("school") != "Abjuration" or not sp.get("level") or char.class_level("Wizard") < 2 \
                or (char.class_entry("Wizard") or {}).get("subclass") != "School of Abjuration":
            return
        top = 2 * char.class_level("Wizard") + char.mod("int")
        ward = att.get("ward")
        if not ward:
            att["ward"] = {"hp": top, "max": top}
            self._say(f"{att['name']}'s Arcane Ward rises ({top} HP)")
        else:
            ward["hp"] = min(ward["max"], ward["hp"] + 2 * level)
            self._say(f"{att['name']}'s Arcane Ward recovers to {ward['hp']}/{ward['max']}")

    def _kill(self, tgt: dict, att: Optional[dict], label: str, dust: bool = False) -> str:
        """Power Word Kill, Disintegrate: dead, not dying (a hero's three death saves are failed)."""
        char = self._sheet(tgt)
        if char:
            char.d["death_saves"] = {"success": 0, "failure": 3}
            char.save()
            if self._hp_of(tgt) > 0:
                self.chars.damage(tgt["character"], str(self._hp_of(tgt)))
            self._cond(tgt, "Unconscious", True)
            return f"{tgt['name']} " + ("is turned to dust" if dust else "dies")
        if self._hp_of(tgt) > 0:
            return self._deal_rolled(tgt, [[self._hp_of(tgt), ""]], by=att, label=label)
        return f"{tgt['name']} " + ("is turned to dust" if dust else "dies")

    def _missed_spell(self, att: dict, label: str):
        """Witch Bolt, Ray of Enfeeblement: a concentration spell whose attack missed has nothing left to hold on to."""
        if (att.get("concentrating") or {}).get("spell") != label:
            return
        att["spell_actions"] = [a for a in att.get("spell_actions") or []
                                if not (a.get("spell") == label and (a.get("def") or {}).get("same_target"))]
        if any(e.get("conc_by") == att["id"] for o in self.b["combatants"] for e in o.get("effects") or []) \
                or any(z.get("conc_by") == att["id"] for z in self.b.get("zones") or []) \
                or any(o.get("summon_conc") == att["id"] for o in self.b["combatants"]) \
                or any(a.get("conc_by") == att["id"] for a in att.get("spell_actions") or []) \
                or any((o.get("conjured") or {}).get("conc") == att["id"] for o in self.b["combatants"]):
            return
        self._drop_conc(att, "the spell missed")

    def _dispel_fails(self, att: dict, R: dict, name: str, slot: int) -> bool:
        """Dispel Magic: a spell of a higher level than the slot used ends only on a spellcasting ability check, DC 10 + its level."""
        sp = rules.spell(name)
        lvl = int(sp["level"]) if sp else 0
        if lvl <= int(slot or 0):
            return False
        die = self.rng.randint(1, 20)
        total = die + int(R["mod"])
        if total >= 10 + lvl:
            return False
        self._line(R, f"{att['name']}'s Dispel Magic fails against {name}: d20 {die} + {int(R['mod'])} = {total} vs DC {10 + lvl}", "holds")
        return True

    def _spell_left(self, eff: dict):
        """After Dispel Magic took a concentration spell off one creature: with nothing of it left anywhere (no other
        creature under it, no area, no summons) the spell has ended, and so does the concentration."""
        k = self._find_or_none(eff.get("conc_by"))
        if k is None or (k.get("concentrating") or {}).get("spell") != eff["name"]:
            return
        if any(e.get("conc_by") == k["id"] and e["name"] == eff["name"] for o in self.b["combatants"] for e in o.get("effects") or []):
            return
        if any(z.get("conc_by") == k["id"] for z in self.b.get("zones") or []) or any(o.get("summon_conc") == k["id"] for o in self.b["combatants"]):
            return
        self._drop_conc(k, "its spell was dispelled")

    @staticmethod
    def _blade_weapons(char) -> list:
        """The melee weapons Green-Flame Blade and Booming Blade can swing: an unarmed strike isn't one."""
        return [w for w in char.attacks() if not w.get("ranged") and "unarmed" not in (w.get("props") or [])]

    def _spell_teleport(self, R, att, sp, sx, level, dc, mod):
        p = R.get("point")
        if not p or not att.get("pos"):
            self._line(R, f"{att['name']} casts {sp['name']}", "")
            return None
        start = list(att["pos"])
        dest = [int(p[0]), int(p[1])]
        if not self._tile_ok(att, *dest):
            spot = self._free_near(att, *dest)
            dest = spot or start
        if G.distance_to_tile(start, att.get("span") or 1, tuple(dest)) > int(sx.get("teleport", 30)):
            raise ServiceError("That's too far to teleport.")
        self._vfx("blink", id=att["id"], at=start, to=dest)
        att["pos"] = dest
        self._line(R, f"{att['name']} teleports to {self._tile_label(dest)}", "teleport")
        boom = sx.get("boom")
        if boom:
            extra = max(0, level - sp["level"])
            tiles = G.area_tiles("emanation", boom["radius"], origin=G.centre(start, 1), caster_box=G.box(start, att.get("span") or 1),
                                 **self._bounds_kw()) | G.footprint(start, att.get("span") or 1)
            hit = [c["id"] for c in G.creatures_in(tiles, self.b["combatants"]) if c is not att and not self._is_out(c)]
            self._area_vfx(att, tiles, boom["parts"], "burst", G.centre(start, 1))
            return self._strike(att, sp["name"], hit, mode="save", sv={"ab": boom["save"], "dc": dc, "half": boom.get("half")},
                                parts=SB.upcast(boom["parts"], boom.get("up"), extra), spell=True)
        return None

    def _tile_label(self, pos) -> str:
        from .battlemap import tile_name
        return tile_name(*pos)

    def _spell_zone(self, R, att, sp, spec, level, dc, mod, conc, dtype):
        sx = spec["special"]
        z = dict(sx["zone"])
        extra = max(0, level - sp["level"])
        dtype = dtype or (spec["types"] or [None])[0]            # the caster's pick (Songal's Elemental Suffusion), else the first
        parts = z.get("parts") or []
        if parts == "CANTRIP":
            parts = CR.spell_plan(sp, level, R["caster_level"], mod, dtype)["parts"]
        elif parts:
            parts = SB.upcast(SB.fill(parts, mod, dtype), z.get("up"), extra)
            if spec.get("types") and dtype:
                parts = [[d, dtype] for d, _t in parts]
        z["parts"] = parts
        if z.get("heal"):
            z["heal"] = z["heal"] + (f"+{extra}d6" if extra and z.get("up_heal") else "")
            z["uses_left"] = 1 + max(0, mod)
        if z.get("trap"):                                       # Fire Rune: the burst it keeps for whoever comes near - fire, frost or shock
            tr = dict(z["trap"])
            opt = (tr.pop("options", None) or {}).get((dtype or "").lower()) or {}
            tr["parts"] = [[d, opt.get("type") or t] for d, t in SB.upcast(SB.fill(tr["parts"], mod), tr.get("up"), extra)]
            tr.update({k: v for k, v in opt.items() if k != "type"})
            z["trap"] = tr
            z["parts"] = tr["parts"]                            # (its colour on the maps: it doesn't strike by itself)
        area = spec.get("area")
        if area and sx.get("grow") and extra:                   # Yrden, Helm of Awe: a wider area from a higher slot
            area = dict(area, size=int(area["size"]) + int(sx["grow"]) * extra)
        tiles = R.get("tiles") or []
        if not tiles and att.get("pos") and area:
            tiles = [list(t) for t in G.area_for(area, att["pos"], att.get("span") or 1, tuple(R["point"]) if R.get("point") else None,
                                                  *self._bounds())]
        zone = self._add_zone(att, sp["name"], tiles, z, rounds=spec["duration"], conc=conc, dc=dc, area=area, point=R.get("point"))
        self._line(R, f"{att['name']} casts {sp['name']}: a lasting area of {len(tiles)} tiles", f"{len(tiles)} tiles")
        se = sx.get("self_effect")
        if se:                                                  # Cacophonic Shield, Songal's Elemental Suffusion: the caster's own benefits
            pick = (dtype or "").lower()
            mods = {k: ([pick if x == "$type" else x for x in v] if isinstance(v, list) else v) for k, v in se["mods"].items()}
            self._effect_on(att, sp["name"], [], None, None, None, spec["duration"], att["name"], mods, conc, att["id"])
            self._line(R, f"{att['name']}: {se['note']}", se["note"])
        if z.get("duel_ground"):                                # Dueling Ground: two willing creatures (one more per slot level above 2nd) are the duellists
            inside = [c for c in G.creatures_in({tuple(t) for t in tiles}, self.b["combatants"]) if not self._is_out(c)]
            picked = [c for c in inside if c["id"] in (self.b.get("targets") or [])]
            duelists = (picked + [c for c in inside if c not in picked])[:2 + extra]
            zone["duel_ids"] = [c["id"] for c in duelists]
            self._line(R, "Duellists: " + (", ".join(c["name"] for c in duelists) or "nobody"), "duellists")
        if z.get("ally_boost"):
            self._zone_boost(zone)
        if z.get("on_cast"):
            return self._zone_strike(zone, [c["id"] for c in G.creatures_in({tuple(t) for t in tiles}, self.b["combatants"])
                                            if not self._is_out(c) and self._zone_affects(zone, c)], "cast")
        return None

    def _synosto(self, att: dict, sp: dict, level: int) -> None:
        """Simbul's Synostodweomer: whenever its target casts a spell with a slot, it rolls as many unspent Hit Dice as the slot's level
        and regains the total plus the caster's modifier (those dice are spent)."""
        char = self._sheet(att)
        if not sp.get("level") or not char:
            return
        for e, mod in self._fxs(att, "synosto"):
            if e not in (att.get("effects") or []):
                continue
            total = n = 0
            for _ in range(int(level)):
                avail = [(k, d) for k, d in char.hit_dice().items() if d["used"] < d["total"]]
                if not avail:
                    break
                k, d = max(avail, key=lambda x: x[1]["die"])
                char.d["hit_dice_used"][k] = int(char.d["hit_dice_used"].get(k, 0)) + 1
                total += roll(f"1d{d['die']}")
                n += 1
            if n:
                char.save()
                healed = total + int(mod)
                self._heal(att, healed)
                self._say(f"{e['name']}: {att['name']} spends {n} Hit {'Die' if n == 1 else 'Dice'} and regains {healed} hit points")

    def _lantern_souls(self, c: dict) -> None:
        """Spirit Lantern: an enemy that dies within the lantern's dim light (60 ft) gives it a soul fragment, up to what it can hold."""
        if c["kind"] == "pc" or not c.get("pos"):
            return
        for o in self.b["combatants"]:
            for e in o.get("effects") or []:
                lt = (e.get("mods") or {}).get("lantern")
                if lt and e.get("source_id") == o["id"] and o.get("pos") and self._hostile(o, c) and self._dist(o, c) <= int(lt.get("ft") or 60) \
                        and int(lt["frags"]) < int(lt["max"]):
                    lt["frags"] = int(lt["frags"]) + 1
                    self._say(f"A fragment of {c['name']}'s soul flies into {o['name']}'s lantern ({lt['frags']}/{lt['max']})")

    def _zone_boost(self, z: dict) -> None:
        """Distorted Distance's Shortened Space: the owner's friends in the sphere get +20 ft of speed until the end of their next turn."""
        owner = self._find_or_none(z.get("owner"))
        if owner is None:
            return
        for o in G.creatures_in({tuple(t) for t in z["tiles"]}, self.b["combatants"]):
            if self._is_out(o) or self._hostile(owner, o):
                continue
            self._effect_on(o, f"{z['name']} (shortened space)", [], None, None, None, None, owner["name"], {"speed": int(z["ally_boost"])}, None,
                            owner["id"], until=self._until("target_end_next", owner, o))

    def _zone_drift(self, z: dict) -> Optional[dict]:
        """Doomtide: at the start of each of its caster's turns the sphere moves 10 ft away from the caster; the strike for those it now covers."""
        import math
        owner = self._find_or_none(z.get("owner"))
        if owner is None or not owner.get("pos") or not z.get("point") or not z.get("area"):
            return None
        cx, cy = G.centre(owner["pos"], owner.get("span") or 1)
        px, py = z["point"]
        dx, dy = px - cx, py - cy
        n = math.hypot(dx, dy)
        ux, uy = (dx / n, dy / n) if n else (1.0, 0.0)
        step = int(z["drift"]) / 5
        w, h = self._bounds()[:2]
        nx, ny = min(max(.5, px + ux * step), w - .5), min(max(.5, py + uy * step), h - .5)
        tiles = G.area_for(z["area"], owner["pos"], owner.get("span") or 1, (nx, ny), *self._bounds())
        z["tiles"] = [list(t) for t in sorted(tiles)]
        z["point"] = [nx, ny]
        self._zone_vfx("move", z, d=[nx - px, ny - py])
        self._say(f"{z['name']} drifts 10 ft away from {owner['name']}")
        key = self._turn_key()
        ids = [o["id"] for o in G.creatures_in({tuple(t) for t in tiles}, self.b["combatants"])
               if not self._is_out(o) and self._zone_affects(z, o) and z["hits"].get(str(o["id"])) != key]
        for i in ids:
            z["hits"][str(i)] = key
        return self._zone_strike(z, ids, "drift")

    def _spell_ward(self, att: dict, sp: dict) -> Optional[str]:
        """Spellfire Storm: a creature inside it that casts a spell makes a save or the spell dissipates (the area that stopped it, else None)."""
        if not att.get("pos"):
            return None
        mine = G.footprint(att["pos"], att.get("span") or 1)
        for z in list(self._zones()):
            if z.get("spell_save") and mine & {tuple(t) for t in z["tiles"]} and self._zone_affects(z, att):
                res = self._saving_throw(att, z["spell_save"], int(z.get("dc") or 13), spell=True, label=z["name"])
                self._say(f"{att['name']} {z['spell_save'].upper()} save to cast {sp['name']} inside {z['name']}: {res['total']} vs DC {z.get('dc')} — "
                          + ("success" if res["ok"] else "failed"))
                if not res["ok"]:
                    return z["name"]
        return None

    def _duel_zero(self, c: dict) -> bool:
        """Dueling Ground: a duellist dropped to 0 hit points inside it is stable and teleported to the nearest free space outside it."""
        if not c.get("pos"):
            return False
        mine = G.footprint(c["pos"], c.get("span") or 1)
        for z in self._zones():
            tiles = {tuple(t) for t in z["tiles"]}
            if not z.get("duel_ground") or c["id"] not in (z.get("duel_ids") or []) or not mine & tiles:
                continue
            w, h = self._bounds()[:2]
            spots = sorted(((x, y) for x in range(w) for y in range(h) if (x, y) not in tiles and self._tile_ok(c, x, y)),
                           key=lambda p: (p[0] - c["pos"][0]) ** 2 + (p[1] - c["pos"][1]) ** 2)
            char = self._sheet(c)
            if char:
                char.d["death_saves"] = {"success": 3, "failure": 0}
                char.save()
            if spots:
                c["pos"] = list(spots[0])
                self._follow_zones(c)
            self._say(f"{c['name']} is stable and is whisked out of the {z['name']}")
            return True
        return False

    # ------------------------------------------------------------------ spell actions on later turns
    def use_spell_action(self, cid: int, action_id: int, targets: Optional[List[int]] = None, point=None, adv: Optional[str] = None) -> str:
        """Use what a lasting spell lets its caster do again (Spiritual Weapon's attack, Witch Bolt's arc, moving Moonbeam...)."""
        with self.lock:
            self._busy()
            c = self._find(cid)
            a = next((x for x in c.get("spell_actions") or [] if x["id"] == int(action_id)), None)
            if not a:
                raise ServiceError("That spell isn't active any more.")
            d = a["def"]
            ids = list(targets) if targets is not None else ([a["target"]] if a.get("target") else list(self.b.get("targets") or []))
            tok = None
            if a.get("token"):
                tok = self._find_or_none(a["token"])
                if not tok:
                    c["spell_actions"] = [x for x in c["spell_actions"] if x["id"] != a["id"]]
                    raise ServiceError(f"{a['spell']} is gone.")
                if point is not None and not ids:               # only moving it
                    self._move_token(tok, point)
                    self._pay(c, a["cost"], a["name"])
                    self._commit(f"{c['name']} moves {tok['name']}")
                    return f"{tok['name']} moves to {self._tile_label(tok['pos'])}"
                if ids:
                    self._token_reach(tok, self._find(ids[0]))  # moves it next to the target first if it can get there
            if d.get("maddening"):
                return self._maddening_hex(c)
            if d.get("maintain"):                               # Crown of Madness: the caster's action keeps it going
                self._pay(c, a["cost"], a["name"])
                c["maintain"] = dict(c.get("maintain") or {}, spell=a["spell"], kept=True)
                self._commit(f"{c['name']} maintains {a['spell']}")
                return f"{c['name']} maintains {a['spell']}"
            if d.get("near_ids"):                               # Steel Wind Strike: only to a space within 5 ft of one of the creatures it struck
                if point is None:
                    raise ServiceError("Pick a space within 5 ft of one of the creatures the spell struck.")
                spot = (int(point[0]), int(point[1]))
                if not any(o is not None and o.get("pos") and G.distance_to_tile(o["pos"], o.get("span") or 1, spot) <= 5
                           for o in (self._find_or_none(i) for i in d["near_ids"])):
                    raise ServiceError("That space isn't within 5 ft of a creature the spell struck.")
            if d.get("break_ench") or d.get("dismiss"):         # Dispel Evil and Good: touch / reach, and the right kind of creature
                t0 = self._find_or_none(ids[0]) if ids else None
                if t0 is None:
                    raise ServiceError("Pick a target")
                if c.get("pos") and t0.get("pos") and self._dist(c, t0) > 5:
                    raise ServiceError(f"{t0['name']} is out of reach (5 ft)")
                if d.get("dismiss") and not self._warded_kind(t0):
                    raise ServiceError(f"{t0['name']} isn't a celestial, elemental, fey, fiend or undead")
                if d.get("break_ench") and not self._enchantments_of(t0):
                    raise ServiceError(f"Nothing on {t0['name']} to break: no charm, fear or possession from a celestial, elemental, fey, fiend or undead")
            lantern = None
            if d.get("frag"):                                   # Spirit Lantern: each use spends a soul fragment
                lantern = next((e for e, _v in self._fxs(c, "lantern") if e in (c.get("effects") or [])), None)
                if lantern is None or int(lantern["mods"]["lantern"].get("frags") or 0) <= 0:
                    raise ServiceError("No soul fragment in the lantern: an enemy has to die within its light first.")
            self._pay(c, a["cost"], a["name"])
            label = a["name"]
            if lantern is not None:
                lantern["mods"]["lantern"]["frags"] = int(lantern["mods"]["lantern"]["frags"]) - 1
            if a.get("uses") is not None:
                a["uses"] -= 1
                if a["uses"] <= 0:
                    c["spell_actions"] = [x for x in c["spell_actions"] if x["id"] != a["id"]]
                    if d.get("ends_when_spent") or (rules.spell(a["spell"]) and SB.spec(rules.spell(a["spell"]))["special"].get("ends_when_spent")):    # Elminster's Effulgent Spheres: no spheres left, no spell
                        for e in [e for e in c.get("effects") or [] if e["name"] == a["spell"]]:
                            self._effect_off(c, e, "all used")
            if d.get("break_ench"):                             # Break Enchantment: ends the charm, fear or possession - and the spell
                t0 = self._find(ids[0])
                for e in self._enchantments_of(t0):
                    if (e.get("mods") or {}).get("possessed_by") is not None:
                        ghost = self._find_or_none(e["mods"]["possessed_by"])
                        if ghost is not None and ghost.get("possessing") == t0["id"]:
                            self._say(self._release_possession(ghost, "driven out") or "")
                        elif e in t0.get("effects", []):
                            self._effect_off(t0, e, label)
                    else:
                        self._effect_off(t0, e, label)
                self._end_dispel(c, a)
                self._commit(f"{c['name']} breaks the enchantment on {t0['name']}")
                return f"{c['name']} breaks the enchantment on {t0['name']}"
            if d.get("move_mark"):
                if not ids:
                    raise ServiceError("Pick the new target")
                new = self._find(ids[0])
                moved = None
                for o in self.b["combatants"]:
                    for e in list(o.get("effects") or []):
                        if e["name"] == a["spell"] and e.get("source_id") == c["id"]:
                            moved = e
                            o["effects"].remove(e)
                if not moved:                                   # its creature dropped (or left): the mark goes on fresh
                    buff = CR.buff_for(a["spell"]) or {}
                    if not buff.get("mods"):
                        raise ServiceError(f"{a['spell']} isn't on anyone right now.")
                    self._effect_on(new, a["spell"], [], None, None, None, None, c["name"], dict(buff["mods"]), a.get("conc_by"), c["id"])
                else:
                    new.setdefault("effects", []).append(moved)
                self._commit(f"{c['name']} moves {a['spell']} to {new['name']}")
                return f"{a['spell']} now marks {new['name']}"
            if d.get("dash"):
                EC.dash(c.get("turn"))
                self._commit(f"{c['name']} dashes ({label})")
                return f"{c['name']} dashes"
            if d.get("teleport"):
                fake = {"name": label, "key": "", "special": {"teleport": d["teleport"]}}
                R = self._new_r("spell", c, label, spell=a["spell"], slot_level=a["level"], caster_level=1, mod=a["mod"], attack_bonus=a["attack"],
                                dc=a["dc"], adv=adv, dtype=None, targets=[], tiles=[], point=point)
                self._spell_teleport(R, c, rules.spell(a["spell"]), fake["special"], a["level"], a["dc"], a["mod"])
                self._commit()
                return "\n".join(R["lines"])
            if d.get("weapon"):
                return self._swift_quiver(c, d, ids, adv)
            if d.get("ward") or d.get("temp"):                  # Spirit Lantern's Ward Ally; Conjure Constructs' Orderly Ward
                t = self._find(ids[0]) if ids else c
                if d.get("ward"):
                    self._effect_on(t, label, [], None, None, None, None, c["name"], {"attacks_against": "dis"}, None, c["id"],
                                    until=self._until("caster_start", c, t))
                    self._commit(f"{c['name']}: {label} on {t['name']}")
                    return f"{t['name']}: other creatures have disadvantage on attack rolls against it until {c['name']}'s next turn"
                n = max(0, roll(SB.upcast(SB.fill([[d["temp"], ""]], a["mod"]), d.get("up"), max(0, a["level"] - (rules.spell(a["spell"]) or {"level": a["level"]})["level"]))[0][0]))
                self._give_temp(t, n)
                self._commit(f"{c['name']}: {label} gives {t['name']} {n} temporary hit points")
                return f"{t['name']} +{n} temporary hit points"
            if d.get("heal"):
                t = self._find(ids[0]) if ids else c
                if d.get("range") and c.get("pos") and t.get("pos") and t is not c and self._dist(c, t) > d["range"]:
                    raise ServiceError(f"{t['name']} is out of range ({d['range']} ft)")
                if d.get("undead_only") and str((self._monster(t) or {}).get("type") or "").lower() != "undead":
                    raise ServiceError(f"{t['name']} isn't an Undead creature")
                n = roll(SB.fill([[d["heal"], ""]], a["mod"])[0][0])
                self._heal(t, n)
                if d.get("ends_spell"):                         # Alustriel's Mooncloak: the Respite ends the spell
                    self._end_dispel(c, {"spell": a["spell"], "name": label})
                    for e in [e for e in c.get("effects") or [] if e["name"] == a["spell"]]:
                        self._effect_off(c, e, f"{label} used")
                self._commit(f"{c['name']}: {label} heals {t['name']} for {n}")
                return f"{t['name']} +{n}"
            if d.get("area"):
                aim = point or self.b.get("aim")
                if aim is None and ids:
                    t = self._find(ids[0])
                    aim = list(G.centre(t["pos"], t.get("span") or 1)) if t.get("pos") else None
                tiles = G.area_for(d["area"], c["pos"], c.get("span") or 1, tuple(aim) if aim else None, *self._bounds()) if c.get("pos") else set()
                hit = [x["id"] for x in G.creatures_in(tiles, self.b["combatants"]) if x is not c and not self._is_out(x)]
                self._area_vfx(c, tiles, a["parts"], d["area"].get("shape", ""), aim)
                S = self._strike(c, label, hit, mode="save", sv={"ab": d["save"], "dc": a["dc"], "half": d.get("half"), "conds": d.get("conds") or [],
                                                                 "rounds": 1 if d.get("conds") else None, "prone": d.get("prone"), "push": d.get("push"),
                                                                 "mods": d.get("fail_mods"), "until": d.get("until"), "note": d.get("note"),
                                                                 "exhaust": d.get("exhaust"), "exhaust_cap": d.get("exhaust_cap")},
                                 parts=a["parts"], spell=True, conc=a.get("conc_by") if d.get("exhaust") else None)     # (Waves of Exhaustion's levels go with the spell)
                out = self._run_r(S)
                if d.get("ends_spell"):
                    c["spell_actions"] = [x for x in c["spell_actions"] if x["id"] != a["id"]]
                    if c.get("concentrating"):
                        self._drop_conc(c, f"{label} used")
                self._commit()
                return out
            if not ids:
                raise ServiceError("Pick a target")
            tgt = self._find(ids[0])
            if not tok and d.get("range") and c.get("pos") and tgt.get("pos") and self._dist(c, tgt) > d["range"]:
                raise ServiceError(f"{tgt['name']} is out of range ({d['range']} ft)")
            if d.get("atk"):
                atk = {"bonus": a["attack"], "n": d.get("n", 1), "melee": d["atk"] == "melee", "spell": True, "magical": True, "parts": a["parts"],
                       "adv": adv, "ignore_cover": False}
                if d.get("crit"):
                    atk.update(crit_any=True, crit_at=int(d["crit"]), crit_bonus=d.get("crit_bonus"))
                oh = d.get("on_hit")                            # Sylune's Viper's bite: poisoned (and so incapacitated) until your next turn
                S = self._strike(c, label, [tgt["id"]], mode="attack", atk=atk, spell=True,
                                 on_hit={"name": label, "conds": list(oh.get("conds") or []), "mods": oh.get("mods"), "note": oh.get("note"), "rounds": None,
                                         "until": self._until(oh.get("until"), c, tgt)} if oh else None)
                S["spell_extra"] = {"drain": d.get("drain"), "dismiss": {"dc": a["dc"]} if d.get("dismiss") else None}
            elif d.get("save"):
                self._say(f"{c['name']} uses {label} on {tgt['name']}")       # Fire Breath, Dragon's Breath...: who does what
                sp = rules.spell(a["spell"])                    # a potion's Fire Breath has no spell behind it
                extra = max(0, a["level"] - sp["level"]) if sp else 0
                S = self._strike(c, label, [tgt["id"]], mode="save", sv={"ab": d["save"], "dc": a["dc"], "half": d.get("half"),
                                                                         "conds": d.get("conds") or [], "rounds": 10 if d.get("conds") else None,
                                                                         "mods": d.get("mods"), "note": d.get("note")},
                                 parts=a["parts"], spell=True, conc=a.get("conc_by") if d.get("mods") else None)
                if d.get("dot"):                                # Transfix: the psychic damage when it ends its turn next to you
                    S["spell_extra"] = {"dot": d["dot"], "level": a["level"], "extra": extra, "dc": a["dc"]}
                if d.get("pull"):
                    S["sv"]["pull"] = d["pull"]
            else:
                S = self._strike(c, label, [tgt["id"]], mode="auto", parts=a["parts"], spell=True)
                S["spell_extra"] = {"drain": d.get("drain"), "hamper": d.get("hamper")}
            out = self._run_r(S)
            self._commit()
            return out

    def _swift_quiver(self, c, d, ids, adv) -> str:
        char = self._sheet(c)
        if not char or not ids:
            raise ServiceError("Pick a target")
        weapons = [w for w in char.attacks() if w.get("ranged")]
        if not weapons:
            raise ServiceError("No ranged weapon equipped.")
        w = max(weapons, key=lambda x: x["attack"])
        atk = self._weapon_atk(c, w)
        atk["n"] = d.get("n", 2)
        atk["adv"] = adv
        out = self._run_r(self._strike(c, f"Swift Quiver ({w['name']})", [ids[0]], mode="attack", atk=atk, magical=w.get("magic", False)))
        self._commit()
        return out

    # ------------------------------------------------------------------ after a spell's strike: its extra parts
    def _spell_after_strike(self, R: dict):
        ex = R.get("spell_extra") or {}
        att = self._find_or_none(R["actor"])
        if att and R.get("mode") == "attack" and R.get("conc") is not None and R.get("hits") is not None and not any(R["hits"].values()):
            self._missed_spell(att, R["label"])
        if not ex or not att:
            return
        if ex.get("self_cost") and self._alive(att):             # Death Spark: hit or miss, the caster pays for it (nothing reduces it)
            n = sum(roll(d) for d, _t in ex["self_cost"])
            self._line(R, f"The spark burns {att['name']}: " + self._deal_rolled(att, [[n, ""]], label=R["label"]), self._short)
        if ex.get("dismiss"):                                   # Dispel Evil and Good's Dismissal: on a hit a Charisma save or banished; the spell ends either way
            for tid in dict.fromkeys(R["targets"]):
                tgt = self._find_or_none(tid)
                if tgt is None or not R["hits"].get(str(tid)) or not self._alive(tgt):
                    continue
                res = self._saving_throw(tgt, "cha", int(ex["dismiss"]["dc"]), spell=True, label=R["label"])
                self._line(R, f"{tgt['name']} CHA save against {R['label']}: d20 {res['kept']}{res['note']} = {res['total']} vs DC {ex['dismiss']['dc']} — "
                              + ("holds fast" if res["ok"] else "driven back to its home plane"), "saved" if res["ok"] else "banished")
                if not res["ok"]:
                    self._effect_on(tgt, R["label"], ["Incapacitated"], None, None, None, None, att["name"], {"banished": True, "untargetable": True},
                                    None, att["id"])
            self._end_dispel(att, {"spell": "Dispel Evil and Good", "name": R["label"]})
        pair = [self._find_or_none(i) for i in dict.fromkeys(R["targets"])]
        if ex.get("tether") and len(pair) == 2 and all(pair) and not any(R.get("saved", {}).get(str(o["id"])) for o in pair):
            for o, other in (pair, pair[::-1]):                 # Tether Essence: both failed - linked for the duration
                self._effect_on(o, R["label"], [], None, None, None, None, att["name"], {"tether": other["id"]}, R.get("conc"), att["id"])
            self._line(R, f"{pair[0]['name']} and {pair[1]['name']} are tethered: damage to one hurts the other", "tethered")
        for tid in dict.fromkeys(R["targets"]):
            tgt = self._find_or_none(tid)
            if not tgt:
                continue
            hit = R["hits"].get(str(tid))
            if ex.get("hamper") and R.get("dealt", {}).get(str(tid)) and self._alive(tgt):    # Heat Metal: holding the hot metal
                self._effect_on(tgt, R["label"], [], None, None, None, None, att["name"], {"attacks_with": "dis", "check_dis": True}, None, att["id"],
                                until=self._until("caster_start", att, tgt))
                self._line(R, f"{tgt['name']}: disadvantage on attacks and checks until {att['name']}'s next turn", "hampered")
            if ex.get("drain") and (hit or R["mode"] != "attack") and R.get("dealt", {}).get(str(tid)):     # Enervation: on a save too
                n = int(R["dealt"][str(tid)] * ex["drain"])
                self._heal(att, n)
                self._line(R, f"{att['name']} regains {n} hit points", f"+{n} HP")
            if ex.get("dust") and self._hp_of(tgt) <= 0 and not self._dead(tgt):    # Disintegrate: reduced to 0, it's dust
                self._line(R, self._kill(tgt, att, R["label"], dust=True), "dust")
            if ex.get("pull") and hit:
                self._push(tgt, att, -int(ex["pull"]), R)
            if ex.get("push") and hit:
                self._push(tgt, att, int(ex["push"]), R)
            turn = att.get("turn") if att.get("turn") is not None else {}
            if ex.get("grasp") and hit and self._alive(tgt) and not turn.get("grasp_of_hadar"):     # once a turn: pulled 10 ft closer
                turn["grasp_of_hadar"] = True
                self._push(tgt, att, -10, R)
            if ex.get("lance") and hit and self._alive(tgt) and not turn.get("lance_of_lethargy"):  # once a turn: speed -10 ft
                turn["lance_of_lethargy"] = True
                self._effect_on(tgt, "Lance of Lethargy", [], None, None, None, None, att["name"], {"speed": -10}, None, att["id"],
                                until=self._until("caster_end_next", att, tgt))
                self._line(R, f"{tgt['name']}: speed -10 ft (Lance of Lethargy)", "slowed")
            if ex.get("dot") and (hit or R["mode"] == "save" and not R.get("saved", {}).get(str(tid))):
                dot = dict(ex["dot"])
                if dot.get("up") and ex.get("extra"):
                    dot["dice"] = SB.upcast([[dot["dice"], dot["type"]]], dot["up"], ex["extra"])[0][0]
                self._dot_on(tgt, R["label"], dot, dot.get("save"), ex.get("dc"), None, att["name"], R.get("conc"), att["id"])
            if ex.get("miss_half") and R["mode"] == "attack" and not hit and self._alive(tgt):
                parts = R["atk"].get("parts") or []
                self._line(R, f"{R['label']} misses but still splashes: " + self._deal(tgt, parts, factor=.5, by=att, label=R["label"]), self._short)
            if ex.get("explode"):
                e = ex["explode"]
                tiles = G.area_tiles("emanation", e["radius"], origin=G.centre(tgt["pos"], tgt.get("span") or 1), caster_box=G.box(tgt["pos"], tgt.get("span") or 1),
                                     **self._bounds_kw()) | G.footprint(tgt["pos"], tgt.get("span") or 1) if tgt.get("pos") else {(-1, -1)}
                hit_ids = [c["id"] for c in G.creatures_in(tiles, self.b["combatants"]) if not self._is_out(c)
                           and not (e.get("skip_target") and c is tgt)
                           and not (e.get("foes_only") and not self._hostile(att, c))] or ([] if e.get("skip_target") else [tgt["id"]])     # Fist of the Heavens: creatures of your choice
                self._area_vfx(att, tiles, e["parts"], "burst", G.centre(tgt["pos"], tgt.get("span") or 1) if tgt.get("pos") else None)
                if hit_ids:                                     # Detonate: the blast leaves out the target, halves on a save, and is harder to dodge if the target fell
                    child = self._strike(att, f"{R['label']} (explosion)", hit_ids, mode="save",
                                         sv={"ab": e["save"], "dc": ex.get("dc", 13), "half": bool(e.get("half")),
                                             "force_dis": bool(e.get("dis_if_down") and self._hp_of(tgt) <= 0), "dis_types": e.get("dis_types")},
                                         parts=SB.upcast(e["parts"], e.get("up"), ex.get("extra", 0)), spell=True)
                    R.setdefault("follow", []).append(child)
            if ex.get("splash") and hit and tgt.get("pos"):
                near = [c for c in self.b["combatants"] if c is not tgt and c is not att and c.get("pos") and not self._is_out(c)
                        and self._dist(c, tgt) <= 5 and self._hostile(c, att)]
                if near:
                    dice = SB.cantrip_die(ex["splash"]["dice"], ex.get("caster_level", 1)).replace("MOD", str(ex.get("mod", 0)))
                    self._line(R, "Flames leap: " + self._deal(near[0], [[dice, ex["splash"]["type"]]], by=att, label=R["label"]), self._short)
            if ex.get("mark") and hit:
                dice = SB.cantrip_die(ex["mark"]["dice"], ex.get("caster_level", 1))
                self._effect_on(tgt, "Booming Blade", [], None, None, None, None, att["name"], {"on_move": (dice, "thunder")}, None, att["id"],
                                until={"start": att["id"]})
            if ex.get("transform") and R["mode"] == "save" and not R.get("saved", {}).get(str(tid)):
                self._transform(tgt, ex["transform"], R)
            if ex.get("teleport_target") and R["mode"] == "save" and not R.get("saved", {}).get(str(tid)):
                self._teleport_away(R, att, tgt, ex["teleport_target"])
            if ex.get("antagonize") and R["mode"] == "save" and not R.get("saved", {}).get(str(tid)) and self._can_act(tgt):
                near = [o for o in self.b["combatants"] if o is not tgt and o.get("pos") and tgt.get("pos") and self._alive(o)
                        and self._hostile(att, o) and self._dist(tgt, o) <= max(5, self._reach(tgt))]
                S2 = self._opportunity_strike(tgt, min(near, key=self._hp_of)) if near else None
                if S2:                                          # Antagonize: its reaction goes on a melee attack you pick
                    S2["label"] = f"a forced attack ({R['label']})"
                    R.setdefault("follow", []).append(S2)
                else:                                           # nobody to hit: disadvantage on its next attack instead
                    self._effect_on(tgt, R["label"], [], None, None, None, 10, att["name"], {"attacks_with": "dis", "once": True}, None, att["id"])
            if ex.get("jostle") and R["mode"] == "save" and not R.get("saved", {}).get(str(tid)) and self._alive(tgt) and tgt.get("pos"):
                dx, dy = [(0, -1), (0, 1), (1, 0), (-1, 0)][roll("1d4") - 1]      # Infestation: 5 ft north, south, east or west
                self._push(tgt, {"pos": [tgt["pos"][0] - dx, tgt["pos"][1] - dy], "span": 1}, int(ex["jostle"]), R)
            sink = (ex.get("sink_to") or {}).get(str(tid)) or ex.get("sink")      # Gravity Fissure: towards the nearest bit of the line
            if sink and R["mode"] == "save" and not R.get("saved", {}).get(str(tid)) and self._alive(tgt):
                centre = {"pos": [int(sink[0]), int(sink[1])], "span": 1}     # Gravity Sinkhole: dragged to the centre
                self._push(tgt, centre, -20, R)
            if ex.get("min_hp") and self._hp_of(tgt) < ex["min_hp"] and tgt["kind"] != "pc":
                tgt["hp"] = ex["min_hp"]
            cut = int((R.get("dealt") or {}).get(str(tid), 0)) if ex.get("max_cut") and R["mode"] == "save" and not R.get("saved", {}).get(str(tid)) else 0
            if cut > 0 and self._alive(tgt):                    # Harm: the hit point maximum drops by the damage taken (an hour)
                char = self._sheet(tgt)
                if char:
                    char.d["hp"]["drain"] = int(char.d["hp"].get("drain") or 0) + cut
                    char.current_hp = min(char.current_hp, max(1, char.max_hp))
                    char.save()
                    self._line(R, f"{tgt['name']}'s hit point maximum drops by {cut} to {char.max_hp}", f"max HP -{cut}")
                else:
                    tgt["max_hp"] = max(1, tgt["max_hp"] - cut)
                    tgt["hp"] = min(tgt["hp"], tgt["max_hp"])
                    self._line(R, f"{tgt['name']}'s hit point maximum drops by {cut} ({tgt['max_hp']})", f"max HP -{cut}")
            if ex.get("leap") and hit and tgt.get("pos") and roll("1d8") == roll("1d8"):     # Chaos Bolt: doubles on the d8s - it leaps on
                done = list(ex.get("chain") or []) + [tid]
                near = [o for o in self.b["combatants"] if o["id"] not in done and o is not att and o.get("pos") and self._alive(o)
                        and self._hostile(att, o) and self._dist(o, tgt) <= 30]
                if near:
                    nxt = min(near, key=lambda o: self._dist(o, tgt))
                    self._line(R, f"The chaotic energy leaps from {tgt['name']} to {nxt['name']}", "leaps")
                    S2 = self._strike(att, R["label"], [nxt["id"]], mode="attack", atk=dict(R["atk"]), spell=True)
                    S2["spell_extra"] = dict(ex, chain=done)
                    R.setdefault("follow", []).append(S2)
            if ex.get("plane_shift") and hit and self._alive(tgt):     # Plane Shift's touch: a failed Charisma save sends it away
                if not self._apply_save(R, att, tgt, {"ab": "cha", "dc": ex.get("dc", 13), "spell": True})["ok"]:
                    self._line(R, f"{tgt['name']} is shifted to another plane", "shifted away")
                    self._take_out(tgt)

    def _teleport_away(self, R: dict, att: Optional[dict], tgt: dict, feet: int):
        """Vortex Warp, Scatter: the creature lands near the aimed point, or else as far as the spell allows straight away
        from the caster (the DM can still drag it elsewhere)."""
        if not tgt.get("pos"):
            return
        if R.get("origin"):
            want = [int(R["origin"][0]), int(R["origin"][1])]
        else:
            ax, ay = att["pos"] if att and att.get("pos") else tgt["pos"]
            dx, dy = tgt["pos"][0] - ax, tgt["pos"][1] - ay
            n = max(abs(dx), abs(dy)) or 1
            tiles = feet // 5
            want = [tgt["pos"][0] + round(dx / n * tiles), tgt["pos"][1] + round(dy / n * tiles)]
        m = self.b["map"]
        want = [max(0, min(m["w"] - 1, want[0])), max(0, min(m["h"] - 1, want[1]))]
        spot = self._free_near(tgt, *want)
        if not spot:
            self._line(R, f"{tgt['name']} is teleported (move its token up to {feet} ft)", "teleported")
            return
        self._vfx("blink", id=tgt["id"], at=tgt.get("pos"), to=spot)
        tgt["pos"] = spot
        self._follow_zones(tgt)
        self._line(R, f"{tgt['name']} is teleported to {self._tile_label(spot)}", "teleported")

    def _transform(self, tgt: dict, monster_id: Optional[str], R: dict):
        """Polymorph: the creature turns into a beast; its hit points become the beast's until they run out."""
        from ...rules.monsters import bestiary
        beast = bestiary.get(monster_id or "Giant Toad|MM") or bestiary.get("Frog|MM")
        if not beast:
            return
        tgt["form"] = {"monster": beast["id"], "hp": beast["hp"], "max_hp": beast["hp"], "name": beast["name"],
                       "prev_monster": tgt.get("monster"), "prev_ac": tgt.get("ac"), "conc_by": R.get("conc")}
        kind = beast["name"].lower()
        self._line(R, f"{tgt['name']} turns into {'an' if kind[:1] in 'aeiou' else 'a'} {kind}", f"→ {beast['name']}")

    # ------------------------------------------------------------------ the screen's questions
    def spell_info(self, spell_name: str, slot_level: Optional[int] = None) -> dict:
        """What the screen needs before a cast: damage types to choose from, the area, the targeting, concentration."""
        sp = rules.spell(spell_name)
        if not sp:
            return {"types": [], "area": None, "concentration": False}
        spec = SB.spec(sp)
        kind = spec["kind"]
        options = self.summon_options(spell_name, slot_level) if kind == "summon" else []
        if spec["special"].get("transform"):
            options = beast_options(8)
        types = spec["types"]
        if types and set(types) <= set(ABILITY_NAMES):                  # Hex: an ability to pick, not a damage type
            options, types = [{"label": ABILITY_NAMES[a], "value": a} for a in types], []
        return {"types": types, "area": spec["area"], "concentration": spec["concentration"], "kind": kind,
                "options": options, "spec": _public(spec)}

    def area_preview(self, spell_name: str, caster_id: Optional[int] = None, target_id: Optional[int] = None, point=None) -> dict:
        """The tiles an area spell would cover, cast by the turn owner at the target or point (for the hover preview)."""
        with self.lock:
            sp = rules.spell(spell_name)
            spec = SB.spec(sp) if sp else None
            caster = self._find_or_none(caster_id or self.b.get("turn"))
            if not spec or not caster or not spec.get("area"):
                return {"tiles": [], "ids": [], "area": spec.get("area") if spec else None}
            tid = target_id or self.b.get("target")
            aim = self._resolve_aim(caster, spec, sp["level"], self._caster_level(caster), [tid] if tid and point is None else ([] if point else None), point)
            return {"tiles": [list(t) for t in aim["tiles"]], "ids": aim["targets"] if aim["tiles"] else [], "area": spec["area"]}


def beast_options(max_cr: float, swim: bool = True, fly: bool = True) -> list:
    """Beasts to turn into (Polymorph, Wild Shape): [{'value': monster id, 'label'}], strongest first."""
    from ...rules.monsters import bestiary
    seen, out = set(), []
    for m in sorted(bestiary.offered() or bestiary.all, key=lambda m: (-float(m.get("cr_num") or 0), m["name"])):
        if m.get("type") != "beast" or float(m.get("cr_num") or 0) > max_cr or m["name"] in seen or m.get("source") not in ("MM", "VGM", "MPMM"):
            continue
        if not fly and "fly" in (m.get("speed") or ""):
            continue
        if not swim and "swim" in (m.get("speed") or "") and "walk" not in (m.get("speed") or ""):
            pass
        seen.add(m["name"])
        out.append({"value": m["id"], "label": f"{m['name']} (CR {m['cr']}, {m['hp']} HP)"})
    return out


def _public(spec: dict) -> dict:
    """The part of a spell's spec the screens use (no functions, no tables)."""
    return {k: spec[k] for k in ("name", "level", "cost", "range", "range_kind", "target", "area", "kind", "atk_type", "concentration", "types")}
