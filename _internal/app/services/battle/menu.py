"""Everything a creature can do right now, the way the action bar shows it, and one call to do any of it.

available_actions(cid) -> {
    'turn': the budget left ('action', 'bonus', 'reaction', 'move', 'speed', 'legendary'...), 'economy': enforced?,
    'groups': [{'key': 'action'|'bonus'|'reaction'|'free'|'legendary', 'title', 'items': [item, ...]}],
    'spells': [{'level', 'title', 'slots', 'items': [item, ...]}],
    'reactions': [{'family', 'label', 'mode'}], 'concentrating', 'pending'}
item = {'id', 'kind', 'name', 'cost', 'ok', 'why', 'target' (aiming spec), 'range', 'tip', 'uses', 'level', 'readied' (a smite waiting for the next hit)}
act(cid, item_id, targets=[...], point=[x, y], slot=, dtype=, option=, adv=) plays the item.
"""
import copy
import re
import time
from typing import List, Optional

from ...core.storage import clone
from ...rules import combat_feats as CF
from ...rules.character import saves as character_saves
from ...rules import spellcasting as SC
from ...rules.data import rules
from ..common import ServiceError
from . import economy as EC
from . import features as F
from . import icons
from . import info as INFO
from . import spellbook as SB
from .items import SCROLL_NUMBERS
from .constants import ACTIVE
from .reactions import FAMILIES, UNCANNY_STAT
from .standard import BONUS_STD, STANDARD

GROUPS = [("action", "Actions"), ("bonus", "Bonus actions"), ("reaction", "Reactions"), ("legendary", "Legendary actions"), ("free", "Free")]


def _group_of(cost: str) -> str:
    k = EC.parse(cost)[0]
    if k in ("attack", "multi", "action", "long"):
        return "action"
    if k in ("move", "object"):
        return "free"
    return k if k in ("bonus", "reaction", "legendary", "free") else "action"


class MenuMixin:
    def available_actions(self, cid: int, shared: bool = False) -> dict:
        """Built once per change of the battle or of a saved sheet: the editor's bar and every player's page share it.
        It is built from a copy of the battle, outside the lock: a player's page never holds up the DM's screen.
        shared: the kept menu itself (a reader that never changes anything in it), else a copy."""
        memo = getattr(self, "_menus", None)               # built already: no need to wait for the battle
        if memo is not None and memo[0] == (id(self.b), self.version, character_saves()) and cid in memo[1]:
            return memo[1][cid] if shared else clone(memo[1][cid])
        with self.lock:
            key = (id(self.b), self.version, character_saves())
            memo = getattr(self, "_menus", None)
            if memo is None or memo[0] != key:
                snap = copy.copy(self)                             # one frozen copy per change, for every menu of it
                snap.b = clone(self.b)
                snap.lock = type(self.lock)()
                snap.line_sinks, snap.listeners = [], []
                snap._char_memo = {}                               # each sheet read once
                snap._frozen = {}                                  # nothing changes in it: effects gathered once (profile.py)
                memo = self._menus = (key, {}, snap)
            if cid in memo[1]:
                return memo[1][cid] if shared else clone(memo[1][cid])
            snap = memo[2]
        out = snap._available_actions(cid)
        memo[1][cid] = out
        return out if shared else clone(out)

    def cached_actions(self, cid: int) -> Optional[dict]:
        """available_actions(cid) when it is already built for the battle as it is now, else None (nothing is built)."""
        memo = getattr(self, "_menus", None)
        if memo is None or memo[0] != (id(self.b), self.version, character_saves()) or cid not in memo[1]:
            return None
        return clone(memo[1][cid])

    def _available_actions(self, cid: int) -> dict:
        with self.lock:
            c = self._find(cid)
            items: List[dict] = []
            spells: List[dict] = []
            char = self._sheet(c)
            m = self._monster(c)

            def add(item_id, kind, name, cost, target, tip="", rng=None, uses=None, why=None, extra=None):
                if why is None:
                    why = self._pay(c, cost, name, check_only=True)
                it = {"id": item_id, "kind": kind, "name": name, "cost": cost, "ok": why is None, "why": why, "target": target,
                      "range": rng, "tip": tip, "uses": uses}
                if extra:
                    it.update(extra)
                items.append(it)
                return it

            # ---- weapons and monster actions
            if char and not c.get("form"):
                lights = []
                for w in char.attacks():
                    atk = self._weapon_atk(c, w)
                    rng = atk["long"] if not atk["melee"] else (atk["reach"] if not atk.get("thrown") else atk["long"])
                    add(f"attack:{w['name']}", "attack", w["name"], "attack", {"type": "creature", "count": 1, "enemies": True},
                        f"{w['attack']:+d} to hit, {w['damage']}" + (f" · range {w['range']}" if w.get("range") else ""), rng,
                        extra={"melee": atk["melee"], "reach": atk["reach"], "info": INFO.weapon(w)})
                    if "light" in (w.get("props") or []) and not w.get("ranged"):
                        lights.append(w)
                if len(lights) >= 2 or (lights and len([w for w in char.attacks() if "light" in (w.get("props") or [])]) >= 2):
                    for w in lights[1:] or lights:
                        why = None if (c.get("turn") or {}).get("attacked") or not self._economy_on() else "Attack with a light weapon first"
                        add(f"offhand:{w['name']}", "offhand", f"{w['name']} (off-hand)", "bonus", {"type": "creature", "count": 1, "enemies": True},
                            "Two-weapon fighting", 5, why=why or self._pay(c, "bonus", w["name"], check_only=True))
            if m:
                multi = any(e.get("name", "").lower() == "multiattack" for e in m.get("actions") or [])
                for sec, default in (("actions", "action"), ("bonus_actions", "bonus"), ("reactions", "reaction"), ("legendary", "legendary")):
                    for e in m.get(sec) or []:
                        name = e.get("name", "")
                        text = e.get("text", "")
                        if sec == "bonus_actions" and BONUS_STD.search(text):
                            continue                            # Shadow Stealth...: on the bar as "Hide (bonus action)"
                        if sec == "legendary" and self._legendary_spells(c, e) and not re.search(r"\battack\b|\buses (?!Spellcasting)", text):
                            continue                            # "The sphinx casts a spell": its spells, listed below at this cost
                        base = re.sub(r"\s*\((?:Recharge|\d+/Day|Costs)[^)]*\)", "", name).strip()
                        mv = self._move_attack(c, text) if sec in ("actions", "bonus_actions", "legendary") else None   # "moves, then attacks": aimed at a tile
                        ref = self._referenced_action(c, base, text) if (sec != "actions" or (not base.lower().startswith("multiattack") and self._SELF_REF.match(text))) and not mv else None   # Flurry of Claws: "makes six Claw attacks"
                        if ref:                                 # a legendary "makes a tail attack": aimed like the tail
                            text = ref["text"]
                        hit = re.search(r"([+-]\d+) to hit", text)
                        cost = default
                        if sec == "legendary":
                            c2 = re.search(r"Costs (\d) Actions", name, re.I)
                            cost = f"legendary:{c2.group(1) if c2 else 1}"
                        elif sec == "actions" and hit and multi and not ref:
                            cost = "multi"
                        elif sec == "actions" and multi and self._in_multiattack(c, base):
                            cost = "free"                       # part of the Multiattack already under way
                        bopts = self._breath_options(text) if not hit else []     # Fire Breath or Sleep Breath: aimed like the first
                        area = self._action_area(bopts[0][1] if bopts else text) if not hit else None
                        tgt = {"type": "self_area", "aim": area["shape"] != "emanation", "area": area} if area else \
                            ({"type": "creature", "count": 1, "enemies": True} if hit or re.search(r"DC \d+ \w+(?: or \w+)? saving throw|Attack: automatic hit|uses (?:one|a) random (?:magical )?eye ray|"
                                                                                                    r"attack against an? [\w ]*?(?:target|creature)|"
                                                                                                    r"(?:hurls|shoots|fires|launches|throws|sweeps)[^.]*?\b(?:at|through) (?:a|an|one|the) [\w ]*?(?:creature|target)\b|"
                                                                                                    r"\b(?:dart|spear|javelin|ray|bolt)s? (?:hits?|strikes?|unerringly strikes?) (?:a|one) creature", text)
                             else {"type": "none"})
                        if base.lower() == "multiattack":
                            tgt = {"type": "none"}               # it only opens the attacks; each one is aimed on its own
                        ut = {"target": {"type": "point", "teleport": mv["feet"]}, "range": mv["feet"]} if mv else \
                            self._utility_target(c, text) if (tgt["type"] == "none" or self._ORDER.search(text)) and not hit and base.lower() != "multiattack" else None
                        lk = re.search(self._LINKED, text) if tgt["type"] == "none" and not ut and not hit and base.lower() != "multiattack" else None
                        if lk:                                  # an elder brain's Break Concentration, Psychic Pulse: one creature within reach of its mind
                            ut = {"target": {"type": "creature", "count": 1, "enemies": True}, "range": int(lk.group(1))}
                        if ut:                                  # a teleport, a heal, a summons (standard._utility_plan)
                            tgt = ut["target"]
                        many = re.search(r"(?:chooses|targets) up to (two|three|four|five|six) (?:creatures|targets)", text)
                        if many and tgt["type"] == "creature":  # an allip's Whispers: up to three of them
                            tgt = dict(tgt, count=["two", "three", "four", "five", "six"].index(many.group(1)) + 2)
                        why = None
                        if (c.get("spent") or {}).get(base):
                            why = "Not recharged"
                        per_day = re.search(r"\((\d+)/Day", name, re.I) or (re.match(r"(1)", "1") if re.search(r"\(Recharges? after", name, re.I) else None)
                        if per_day and (c.get("uses_day") or {}).get(base, 0) >= int(per_day.group(1)) and not (c.get("shape") and self._SHAPE.search(text)):
                            why = "No uses left today" if "/Day" in name else "Used until a rest"
                        if sec == "reactions":
                            why = why or "Used when it's triggered"
                        if not self._form_ok(c, name):
                            why = f"Not in {(c.get('shape') or 'its true').lower()} form"
                        reach = re.search(r"reach (\d+) ft", text) or re.search(r"within (\d+) feet of (?:itself|it)\b(?=.*?melee spell attack)", text, re.I | re.S)
                        rng = re.search(r"range (\d+)(?:/(\d+))? ft", text)
                        add(f"monster:{name}", "monster", base, cost, tgt, text[:400],
                            max(5, int(reach.group(1))) if reach else (int(rng.group(2) or rng.group(1)) if rng else (ut or {}).get("range")),
                            why=why or self._pay(c, cost, base, check_only=True),
                            extra={"area": area, "text": text, "entry": name, "info": INFO.stat_block(name, text),
                                   **({"options": ut["options"]} if (ut or {}).get("options") else {}),
                                   **({"options": [{"value": lbl, "label": lbl} for lbl, _t in bopts]} if bopts else {})})
                for o in self.trait_options(c):                  # Pounce's bite, Fey Step, Superior Invisibility
                    add(o["id"], "monster", o["name"], o["cost"], o["target"], o["tip"], o.get("range"))
                for t in m.get("traits") or []:                  # a Shapechanger trait: "can use its action to polymorph into..."
                    tsec = self._entry_section(c, t.get("name", ""))[0]
                    if tsec in ("actions", "bonus_actions") and not any(e.get("name") == t.get("name") for sec in ("actions", "bonus_actions") for e in m.get(sec) or []):
                        ut = self._utility_target(c, t.get("text") or "") or {"target": {"type": "none"}, "range": None}     # a rage trait: no aim
                        used = re.search(r"\(Recharges? after", t["name"], re.I) and (c.get("uses_day") or {}).get(
                            re.sub(r"\s*\((?:Recharge|\d+/Day|Costs|Recharges)[^)]*\)", "", t["name"]).strip(), 0) >= 1
                        add(f"monster:{t['name']}", "monster", t["name"], "bonus" if tsec == "bonus_actions" else "action", ut["target"], (t.get("text") or "")[:400],
                            why="Used until a rest" if used else None,
                            extra={"text": t.get("text"), "entry": t["name"], "info": INFO.stat_block(t["name"], t.get("text") or ""),
                                   **({"options": ut["options"]} if ut.get("options") else {})})
                for e in self._lair_actions(c):                  # in its lair: one a round, on initiative count 20
                    if self._lair_spells(c, e["text"]):
                        continue                                 # it casts: its spells are listed below, free of cost
                    ref = self._referenced_action(c, e["name"], e["text"])      # "uses its Hypnosis action": aimed like that action
                    aim_text = ref["text"] if ref else e["text"]
                    area = self._action_area(aim_text)
                    tgt = {"type": "self_area", "aim": area["shape"] != "emanation", "area": area} if area else \
                        ({"type": "creature", "count": 1, "enemies": True} if re.search(r"saving throw|targets? (?:one|a) creature", aim_text) else {"type": "none"})
                    add(f"monster:{e['name']}", "monster", e["name"], "free", tgt, e["text"][:400], 120, why=self._lair_why(c, e["name"]),
                        extra={"area": area, "text": e["text"], "entry": e["name"], "info": INFO.stat_block(e["name"], e["text"]), "lair": True})
                book = self._monster_book(c) if not char else {}
                for sname, e in sorted(book.items(), key=lambda kv: (kv[1]["level"], kv[0])):
                    sp = rules.spell(sname)
                    if not sp:
                        continue
                    spec = self._subc_spec(c, sp, SB.spec(sp))      # a Multiattack that lets a spell replace an attack (subfeats_c.py)
                    lim = e["limit"]
                    uses = None
                    if lim:
                        used = (c.get("spell_uses") or {}).get(f"slot:{e['level']}" if lim[0] == "slot" else sname, 0)
                        uses = f"{lim[1] - used}/{lim[1]}"
                    why = None if self._monster_can_cast(c, sname) else "No uses left"
                    if spec["kind"] in ("reaction_only",) or spec["cost"] == "reaction":
                        why = "Cast as a reaction when it applies"
                    if spec["cost"] == "long" and self._economy_on():
                        why = why or f"Takes {sp.get('casting_time')}"
                    it = {"id": f"mspell:{sp['name']}", "kind": "spell", "name": sp["name"], "cost": spec["cost"],
                          "target": spec["target"], "area": spec["area"], "range": spec["range"], "level": e["level"] or sp["level"],
                          "uses": uses, "tip": sp.get("text", "")[:500], "types": spec["types"], "concentration": spec["concentration"],
                          "dc": e["dc"], "attack": e["attack"], "caster_level": e["caster_level"],
                          "readied": (c.get("on_hit_spell") or {}).get("spell") == sp["name"]}
                    it["why"] = why or self._pay(c, spec["cost"] if spec["cost"] != "long" else "action", sp["name"], check_only=True) \
                        or EC.spell_rule(c.get("turn"), spec["cost"], sp["level"])
                    it["ok"] = it["why"] is None
                    it["icon"] = icons.for_spell(sp["name"], sp.get("school", ""), spec["kind"], sp.get("damage"))
                    it["info"] = INFO.spell(sp, spec, dc=e["dc"], attack=e["attack"], level=e["level"] or sp["level"],
                                            caster_level=e["caster_level"])
                    spells.append(it)
                mine = {s["name"]: s for s in spells}
                for le in (m or {}).get("legendary") or [] if book else []:   # "Cast a Spell (Costs 3 Actions)": a book spell for that cost
                    for sname, lcost in self._legendary_spells(c, le):
                        if sname not in mine:
                            continue
                        it = dict(mine[sname], id=f"lspell:{le['name']}|{sname}", name=f"{sname} ({le['name']})", cost=lcost, readied=False)
                        it["why"] = (None if self._monster_can_cast(c, sname) else "No uses left") or self._pay(c, lcost, sname, check_only=True)
                        it["ok"] = it["why"] is None
                        spells.append(it)
                for le in self._lair_actions(c):                 # "The morkoth casts darkness, dispel magic, or misty step": free, no slot
                    for sname in self._lair_spells(c, le["text"]):
                        sp = rules.spell(sname)
                        spec = SB.spec(sp)
                        terms = self._lair_terms(c, sp, le["text"])
                        it = {"id": f"lairspell:{le['name']}|{sp['name']}", "kind": "spell", "name": f"{sp['name']} ({le['name']})", "cost": "free",
                              "target": spec["target"], "area": spec["area"], "range": spec["range"], "level": terms["level"], "uses": None,
                              "tip": sp.get("text", "")[:500], "types": spec["types"], "concentration": spec["concentration"], "dc": terms["dc"],
                              "attack": terms["attack"], "caster_level": terms["caster_level"], "readied": False, "lair": True,
                              "why": self._lair_why(c, le["name"])}
                        more = c.get("lair_more") or {}
                        if more.get("entry") == le["name"] and more.get("round") == self.b.get("round") and more.get("left"):
                            it["name"] += f" - {more['left']} more"          # "casts X four times": the casts still to make
                        it["ok"] = it["why"] is None
                        it["icon"] = icons.for_spell(sp["name"], sp.get("school", ""), spec["kind"], sp.get("damage"))
                        it["info"] = INFO.spell(sp, spec, dc=terms["dc"], attack=terms["attack"], level=terms["level"], caster_level=terms["caster_level"])
                        spells.append(it)
            # ---- spells of a character
            if char:
                left = SC.slots_remaining(char)
                for sp in SC.spell_known_or_prepared(char):
                    spec = self._subc_spec(c, sp, SB.spec(sp))      # Circle of Mortality (subfeats_c.py)
                    lvl = sp["level"]
                    why = None
                    if lvl > 0 and not sp.get("uses"):
                        ok_slot = any(int(k) >= lvl and v > 0 for k, v in left.items() if k != SC.PACT_KEY) or \
                            (left.get(SC.PACT_KEY) and (SC.spell_slots(char).get("pact") or {}).get("level", 0) >= lvl)
                        if not ok_slot:
                            why = "No spell slot left"
                    if spec["kind"] == "reaction_only" or spec["cost"] == "reaction":     # Shield, Feather Fall: only when triggered
                        why = "Cast as a reaction when it applies"
                    if spec["cost"] == "long" and self._economy_on():
                        why = why or f"Takes {sp.get('casting_time')}"
                    why = why or self._pay(c, spec["cost"] if spec["cost"] != "long" else "action", sp["name"], check_only=True) \
                        or EC.spell_rule(c.get("turn"), spec["cost"], lvl)
                    tgt = dict(spec["target"])
                    if tgt.get("type") == "split":
                        tgt["count"] = SB.projectiles(sp, max(1, lvl), char.total_level)
                    sab = char.mod(sp.get("ability") or "int")
                    spells.append({"id": f"spell:{sp['name']}", "kind": "spell", "name": sp["name"], "cost": spec["cost"], "ok": why is None,
                                   "why": why, "target": tgt, "area": spec["area"], "range": spec["range"], "level": lvl,
                                   "ritual": bool(sp.get("ritual")), "tip": sp.get("text", "")[:500], "types": spec["types"],
                                   "concentration": spec["concentration"], "uses": sp.get("uses"),
                                   "readied": (c.get("on_hit_spell") or {}).get("spell") == sp["name"],
                                   "metamagic": F.metamagic(char) if lvl >= 0 and (char.class_level("Sorcerer") >= 3
                                                                                     or "Metamagic Adept" in char.d["feats"]) else [],
                                   "icon": icons.for_spell(sp["name"], sp.get("school", ""), spec["kind"], sp.get("damage")),
                                   "info": INFO.spell(sp, spec, dc=8 + char.proficiency_bonus + sab, attack=char.proficiency_bonus + sab,
                                                      level=lvl, caster_level=char.total_level, mod=sab)})
                for s in self.scroll_items(c):              # spell scrolls: cast with the scroll's numbers, no slot
                    sp = s["spell"]
                    spec = SB.spec(sp)
                    lvl = sp["level"]
                    why = s["why"] or (f"Takes {sp.get('casting_time')}" if spec["cost"] == "long" and self._economy_on() else None)
                    if spec["kind"] == "reaction_only" or spec["cost"] == "reaction":
                        why = why or "Read as a reaction when it applies"
                    why = why or self._pay(c, spec["cost"] if spec["cost"] != "long" else "action", sp["name"], check_only=True) \
                            or EC.spell_rule(c.get("turn"), spec["cost"], lvl)
                    opts = (self.spell_info(sp["name"], lvl).get("options") or []) if spec["kind"] == "summon" or spec["special"].get("transform") else []
                    spells.append({"id": f"scroll:{s['item']}", "kind": "scroll", "name": f"{sp['name']} (scroll)", "cost": spec["cost"],
                                   "options": opts,
                                   "ok": why is None, "why": why, "target": dict(spec["target"]), "area": spec["area"], "range": spec["range"],
                                   "level": lvl, "tip": f"Read {s['item']}: {sp['name']} with the scroll's save DC and attack bonus, no "
                                   "slot spent. It crumbles to dust.", "types": spec["types"], "concentration": spec["concentration"],
                                   "icon": icons.for_spell(sp["name"], sp.get("school", ""), spec["kind"], sp.get("damage")),
                                   "info": INFO.spell(sp, spec, dc=SCROLL_NUMBERS[min(9, lvl)][1], attack=SCROLL_NUMBERS[min(9, lvl)][2],
                                                      level=lvl, caster_level=char.total_level, mod=0)})
                for w in self.charged_items(c):             # wands and staffs: their spells for charges, an action each
                    sp = w["spell"]
                    spec = SB.spec(sp)
                    why = w["why"] or self._pay(c, "action", sp["name"], check_only=True) or EC.spell_rule(c.get("turn"), "action", w["level"])
                    spells.append({"id": f"wand:{w['item']}|{sp['name']}", "kind": "wand", "name": f"{sp['name']} ({w['item']})", "cost": "action",
                                   "options": [{"value": str(n), "label": f"{n} charge{'s' if n > 1 else ''}: level {min(9, w['level'] + n - w['cost'])}"}
                                               for n in range(w["cost"], w["left"] + 1)] if w["more"] and w["left"] > w["cost"] else [],
                                   "ok": why is None, "why": why, "target": dict(spec["target"]), "area": spec["area"], "range": spec["range"],
                                   "level": w["level"], "uses": "once" if w.get("tattoo") else f"{w['left']} charges", "types": spec["types"], "concentration": spec["concentration"],
                                   "tip": (f"{w['item']}: {sp['name']}, once: the tattoo is gone after" if w.get("tattoo") else
                                           f"{w['item']}: {sp['name']} for {w['cost']} charge{'s' if w['cost'] > 1 else ''} ({w['left']} left)"),
                                   "icon": icons.for_spell(sp["name"], sp.get("school", ""), spec["kind"], sp.get("damage")),
                                   "info": INFO.spell(sp, spec, dc=w["dc"] or 13, attack=w["atk"] or 5, level=w["level"],
                                                      caster_level=char.total_level, mod=0)})
                spells += self._discipline_items(c)         # a Four Elements monk's disciplines: spells for ki (classfeats.py)
                for p in self.item_power_options(c):        # Flame Tongue's flames, a Scimitar of Speed's bonus attack...
                    add(p["id"], "item_power", p["name"], p["cost"], p["target"], p["tip"], p.get("range"),
                        why=p["why"] or self._pay(c, p["cost"], p["name"], check_only=True), extra=p.get("extra"))
                for p in self.wonder_options(c):            # Boots of Speed, a Horn of Blasting, a Bead of Force... (wondrous.py)
                    add(p["id"], "item_power", p["name"], p["cost"], p["target"], p["tip"], p.get("range"), p.get("uses"),
                        why=p["why"] or self._pay(c, p["cost"], p["name"], check_only=True), extra=p.get("extra"))
                for key in F.available(char):
                    f = F.ACTIVE[key]
                    res = f.get("resource")
                    uses = None
                    why = None
                    if res:
                        n = self._resource_left(c, res)
                        uses = str(n)
                        if n <= 0:
                            why = f"No {res} left"
                    left = F.per_left(f, char)
                    if left is not None:
                        uses = uses or str(left)
                        if left <= 0:
                            if f.get("alt_ki") and self._resource_left(c, "Ki Points") >= int(f["alt_ki"]):
                                uses = f"{f['alt_ki']} ki"                  # Breath of the Dragon, Aspect of the Wyrm: ki for one more
                            else:
                                why = f"Used until a {F.per_of(f, char)} rest"
                    if key in ("martial_arts", "flurry") and self._economy_on() and not (c.get("turn") or {}).get("attacked"):
                        why = why or "Take the Attack action first"
                    why = why or self._feature_why(c, char, key, f, None, None, menu=True)    # classfeats.py: raging, after a cantrip...
                    tg = {"type": {"self": "self", "enemy": "creature", "ally": "creature", "none": "none", "area": "self_area", "point": "point"}[f["target"]],
                          "count": 1, "allies": f["target"] == "ally", "enemies": f["target"] == "enemy"}
                    if f.get("teleport"):                       # Fey Step, Shadow Step: a tile to land on
                        tg["teleport"] = f["teleport"](char) if callable(f["teleport"]) else f["teleport"]
                    if f.get("area"):                           # Searing Sunburst: an aimed area
                        tg = {"type": "self_area", "aim": True, "area": dict(f["area"])}
                    extra = None
                    if key == "breath_weapon":
                        b = F.breath(char)
                        tg = {"type": "self_area", "aim": True, "area": b["area"] if b else None}
                    if f.get("options"):
                        extra = {"options": f["options"](char)}
                    if key in ("wild_shape", "combat_wild_shape"):
                        from .spells import beast_options
                        lv = char.class_level("Druid")
                        moon = "moon" in ((char.class_entry("Druid") or {}).get("subclass") or "").lower()
                        top = max(1, lv // 3) if moon and lv >= 6 else (1 if moon else 1 if lv >= 8 else .5 if lv >= 4 else .25)
                        extra = {"options": beast_options(top, swim=lv >= 4, fly=lv >= 8)}
                    add(f"feature:{key}", "feature", f["name"], f["cost"], tg, f["text"], f.get("range") or self._feature_range(c, char, key),
                        uses, why=why or self._pay(c, f["cost"], f["name"], check_only=True), extra=extra)
            # ---- what feats unlock
            if char:
                for o in self._feat_bonus_options(c):
                    cost = "bonus"
                    why = o.get("why") or self._pay(c, cost, o["name"], check_only=True)
                    tg = {"type": "self"} if o.get("self") else {"type": "creature", "count": 1, "enemies": True}
                    add(f"featact:{o['key']}", "feat", o["name"], cost, tg, CF.FEATS.get({"gwm": "great_weapon_master", "polearm": "polearm_master",
                                                                                         "crossbow": "crossbow_expert", "shield_shove": "shield_master",
                                                                                         "brawl_grapple": "tavern_brawler", "chromatic": "gift_chromatic"}
                                                                                        .get(o["key"], o["key"]), {}).get("does", ""),
                        o.get("range") or 5, why=why, extra={"options": [{"value": x, "label": x.capitalize()} for x in o["options"]]} if o.get("options") else None)
                if CF.has(char, "healer"):
                    add("featact:healer", "feat", "Healer's kit", "action", {"type": "creature", "count": 1, "allies": True},
                        CF.FEATS["healer"]["does"], 5)
                if char.has_option("Maddening Hex") and not any(a.get("def", {}).get("maddening") for a in c.get("spell_actions") or []):
                    add("maddening:", "feat", "Maddening Hex", "bonus", {"type": "none"},        # Hexblade's Curse alone (with Hex: its spell action)
                        "Psychic damage (Charisma modifier) to the creature you cursed and foes within 5 ft of it.", 30,
                        why=("Nobody is cursed" if not self._hexed_by(c) else None) or self._pay(c, "bonus", "Maddening Hex", check_only=True))
            # ---- charges: a straight run at a foe and its blow (charge.py)
            for o in self.charge_options(c):
                add(f"charge:{o['key']}", "charge", o["name"], o["cost"], {"type": "creature", "count": 1, "enemies": True}, o["tip"], o["range"],
                    why=o["why"] or self._pay(c, o["cost"], o["name"], check_only=True),
                    extra={"options": o["options"]} if o.get("options") else None)
            # ---- spells still running
            for a in c.get("spell_actions") or []:
                d = a["def"]
                tg = {"type": "creature", "count": 1} if (d.get("atk") or d.get("save") or d.get("auto") or d.get("break_ench")) and not d.get("area") else \
                    {"type": "point", "area": d.get("area")} if d.get("area") else {"type": "point", "teleport": d["teleport"]} if d.get("teleport") else {"type": "self"}
                if d.get("move_mark"):
                    tg = {"type": "creature", "count": 1, "enemies": True}
                if a.get("target"):
                    tg = {"type": "fixed", "id": a["target"]}
                tok = self._find_or_none(a.get("token")) if a.get("token") else None
                if tok:                                          # Spiritual Weapon: it moves, then strikes beside itself
                    add(f"sa:{a['id']}", "spell_action", a["name"], a["cost"], tg, f"From {a['spell']}: {tok['name']} moves up to "
                        f"{tok['conjured'].get('move', 0)} ft, then strikes", tok["conjured"].get("move", 0) + 5, extra={"from_token": tok["id"]})
                else:
                    add(f"sa:{a['id']}", "spell_action", a["name"], a["cost"], tg, f"From {a['spell']}", d.get("range"))
            for z in self.b.get("zones") or []:
                if z.get("owner") == c["id"] and z.get("move"):
                    add(f"zone:{z['id']}", "zone_move", f"Move {z['name']}", z["move"]["cost"], {"type": "point", "area": z.get("area")},
                        f"Move it up to {z['move']['feet']} ft", z["move"]["feet"])
            for key in self.bonus_standard(c):                  # Nimble Escape and the like
                add(f"bonusstd:{key}", "standard", f"{STANDARD[key][0]} (bonus action)", "bonus", {"type": "self"}, STANDARD[key][2])
            # ---- what everyone can do
            for key, (name, cost, tip) in STANDARD.items():
                if key == "stand_up" and "Prone" not in self._conds(c):
                    continue
                if key == "drop_prone" and "Prone" in self._conds(c):
                    continue
                if key == "escape" and not {"Grappled", "Restrained"} & set(self._conds(c)) \
                        and not any((e.get("mods") or {}).get("attached") for e in c.get("effects") or []):
                    continue                                    # (a darkmantle on its head can be pulled off too)
                if key == "escape" and not any(({"Grappled", "Restrained"} & set(e.get("conditions") or []) or (e.get("mods") or {}).get("attached"))
                                               and not (e.get("mods") or {}).get("swallowed_by") for e in c.get("effects") or []) \
                        and any((e.get("mods") or {}).get("swallowed_by") for e in c.get("effects") or []):
                    continue                                    # swallowed: no check gets it out (_escape)
                if key == "douse" and not self._fxs(c, "douse"):
                    continue
                tg = {"type": "creature", "count": 1, "enemies": True} if key in ("grapple", "shove", "help") else {"type": "self"}
                why = None
                c2 = cost
                if key == "stand_up":
                    c2 = f"move:{5 if self._subc_leap(c) else max(5, self._speed(c) // 2)}"      # Leap to Your Feet (subfeats_c.py)
                extra = None
                if key == "use_object":
                    uses = self.use_options(c)
                    extra = {"options": uses} if uses else None
                if key == "shove":                              # the PHB's two shoves
                    extra = {"options": [{"value": "prone", "label": "Knock it prone"}, {"value": "push", "label": "Push it 5 ft away"}]}
                add(f"standard:{key}", "standard", name, c2, tg, tip, 5 if key in ("grapple", "shove", "help") else None, why=why, extra=extra)
            throwable = self.throw_options(c)
            if throwable:
                add("throw", "throw", "Throw", "attack", {"type": "creature", "count": 1, "enemies": True},
                    "Throw a weapon, anything in your pack, an item on the ground or a prop beside you. Thrown weapons deal "
                    "their damage, other weapons half, anything else 1d4 (a prop: its own). It lands by the target.", 60,
                    extra={"options": throwable})
            nearby = self.pickup_options(c)
            if nearby:
                add("pickup", "pickup", "Pick up", "object", {"type": "self"}, "Take an item lying within 5 ft of you.",
                    extra={"options": nearby})
            if c.get("concentrating"):
                add("free:end_concentration", "free", f"End concentration ({c['concentrating']['spell']})", "free", {"type": "self"}, "", why=None)
            if c.get("form"):
                add("free:end_form", "free", f"Leave {c['form']['name']} form", "free", {"type": "self"}, "", why=None)
            for e in self._own_toggles(c):                      # Shell Defense: "It can emerge from its shell as a bonus action"
                add(f"unbuff:{e['name']}", "free", f"End {e['name']}", e["cost"], {"type": "self"}, e["tip"])
            if c.get("possessing"):                             # a ghost lets go of the body as a bonus action
                add("unpossess:", "free", "End possession", "bonus", {"type": "self"}, "Leave the possessed body (it reappears beside it).")
            gagged = "Silenced" in self._conds(c)
            raging = bool(self._fx(c, "rage"))
            beast = bool(c.get("form")) and not self._beast_spells(c)
            if gagged or raging or beast or self._in_silence(c):    # no words: no verbal spells; none in a rage or a beast's shape
                for s in spells:
                    sp = rules.spell(re.sub(r" \([^)]*\)$", "", s["name"]))       # "Fireball (scroll)", "Fireball (Wand of Fireballs)"
                    if s["ok"] and sp and (gagged or raging or beast or SB.spec(sp).get("verbal")):
                        s["ok"], s["why"] = False, ("Not while raging" if raging else "Not in beast shape" if beast
                                                    else f"{c['name']} can't speak" if gagged else "In magical silence")
            if self._fx(c, "no_spells"):                        # Gaseous Form, Feeblemind: what spells._precheck refuses
                for s in spells:
                    if s["ok"]:
                        s["ok"], s["why"] = False, "Can't cast spells now"
            for it in items:
                it.setdefault("icon", icons.icon_for(it))
                it.setdefault("info", INFO.plain(it.get("tip") or ""))
            groups = []
            for key, title in GROUPS:
                g = [i for i in items if _group_of(i["cost"]) == key]
                if g:
                    groups.append({"key": key, "title": title, "items": g})
            sp_groups = []
            for lvl in sorted({s["level"] for s in spells}):
                title = "Cantrips" if lvl == 0 else f"Level {lvl}"
                slots = None
                if char and lvl > 0:
                    left = SC.slots_remaining(char)
                    total = SC.spell_slots(char)["slots"]
                    slots = {"left": left.get(str(lvl), 0), "total": total[lvl - 1] if lvl - 1 < len(total) else 0}
                sp_groups.append({"level": lvl, "title": title, "slots": slots, "items": [s for s in spells if s["level"] == lvl]})
            fams = self._reaction_families(c)
            fight = self.b["status"] == ACTIVE
            t = c.get("turn") if fight and c.get("turn") else EC.new_turn(self._speed(c), self._legendary_max(c))
            return {"id": c["id"], "name": c["name"], "turn": t, "economy": self._economy_on(), "in_combat": fight,
                    "is_turn": self.b.get("turn") == c["id"] or not fight,
                    "toggles": CF.state(char) if char else [], "character": c.get("character"),
                    "groups": groups, "spells": sp_groups, "speed": self._speed(c),
                    "reactions": [{"family": f, "label": FAMILIES.get(f, f), "mode": self._react_mode(c, f), "icon": icons.for_reaction(f)}
                                  for f in fams],
                    "concentrating": (c.get("concentrating") or {}).get("spell"), "pending": self.pending(),
                    "conditions": self._conds(c), "effects": [{"name": e["name"], "rounds": e.get("rounds")} for e in c.get("effects") or []]}

    def _reaction_families(self, c: dict) -> List[str]:
        out = ["opportunity"]
        if self._reaction_spell(c, "Shield") is not None or self._sheet(c) and any(s["name"] == "Shield" for s in SC.spell_known_or_prepared(self._sheet(c))):
            out.append("shield")
        char = self._sheet(c)
        for spell, fam in (("Counterspell", "counterspell"), ("Absorb Elements", "absorb"), ("Hellish Rebuke", "rebuke"), ("Silvery Barbs", "barbs"),
                           ("Temporal Shunt", "shunt")):
            if char and any(s["name"] == spell for s in SC.spell_known_or_prepared(char)) or not char and spell.lower() in self._monster_book(c) \
                    or char and self._reaction_scroll(c, spell.lower()):
                out.append(fam)
        if char and char.has_option("Tomb of Levistus"):
            out.append("tomb")
        if char:
            for fam, key in (("sentinel", "sentinel"), ("polearm", "polearm_master"), ("mage_slayer", "mage_slayer"), ("warcaster", "war_caster"),
                             ("lucky", "lucky"), ("second_chance", "second_chance"), ("fade_away", "fade_away"), ("orcish_fury", "orcish_fury"),
                             ("reactive_resistance", "gift_chromatic"), ("wings", "gift_metallic"), ("reprisal", "gift_gem"),
                             ("duelist", "defensive_duelist")):
                if CF.has(char, key):
                    out.append(fam)
            if char.has_feature("Uncanny Dodge"):
                out.append("uncanny")
            if char.class_level("Paladin") >= 2:
                out.append("smite")
            if any(SB.spec(s)["cost"] == "on_hit" for s in SC.spell_known_or_prepared(char)):
                out.append("readied")
            if char.class_level("Monk") >= 5:
                out.append("stun")
            if char.class_level("Monk") >= 3:
                out.append("deflect")
        if self._parry_bonus(c):
            out.append("parry")
        if not char:                                         # a monster's own Uncanny Dodge, Deflect Missile, retaliations
            if self._stat_reaction(c, UNCANNY_STAT) and "uncanny" not in out:
                out.append("uncanny")
            if self._stat_deflect(c) and "deflect" not in out:
                out.append("deflect")
            if self._stat_cut(c) and "cut" not in out:
                out.append("cut")
            if self._stat_reaction(c, self._INSIGHT):                    # a Precognitive Mage: advantage or disadvantage on a roll
                out.append("insight")
            if any(re.match(r"(?:When|Whenever|Immediately after|In response to|After)\b", e.get("text") or "")
                   for e in (self._monster(c) or {}).get("reactions") or []):
                out.append("mreact")
            for fam, rx in (("entrystrike", r"(?:enters?|entering|moving into) (?:a space )?(?:within \d+|its reach)"),
                            ("guard", r"is hit instead|hit instead|bonus to (?:its|their) AC"), ("protect", r"imposes? disadvantage on the attack roll"),
                            ("redirect", r"chooses another \w+ within"), ("reversal", r"reduces the damage to 0 and regains")):
                if fam not in out and self._stat_reaction(c, rx):       # reactions.py: before the roll, for a neighbour, as it comes in
                    out.append(fam)
        out += [f for f in self._class_families(c) if f not in out]     # classfeats.py: Warding Flare, Interception...
        out += self._wonder_families(c)                                  # wondrous.py: Ring of Evasion, Guardian Emblem...
        return out

    # ------------------------------------------------------------------ doing it
    def act(self, cid: int, item_id: str, targets: Optional[List[int]] = None, point=None, slot=None, dtype: Optional[str] = None,
            option: Optional[str] = None, adv: Optional[str] = None, ritual: bool = False, metamagic: Optional[str] = None) -> str:
        """Play one item of available_actions(). `option`: the creature to summon or turn into, a beast form, an amount...
        `metamagic`: a sorcerer's Metamagic for a spell. A refusal is logged with what the creature had spent this turn."""
        try:
            return self._play(cid, item_id, targets, point, slot, dtype, option, adv, ritual, metamagic)
        except ServiceError as e:
            with self.lock:
                c = self._find_or_none(cid)
                t = (c or {}).get("turn") or {}
                left = ", ".join(f"{k} {t[k]}" for k in ("action", "bonus", "reaction", "move", "attacks") if k in t)
                self.h.log(f"[BATTLE] {c['name'] if c else cid}: {item_id} refused ({e}) — left: {left or '?'}; "
                           f"used this turn: {', '.join(map(str, t.get('used') or [])) or 'nothing'}; turn of "
                           f"{self._name_of(self.b.get('turn')) if self.b.get('turn') is not None else 'nobody'}, round {self.b.get('round')}")
            raise

    def _play(self, cid: int, item_id: str, targets, point, slot, dtype, option, adv, ritual, metamagic) -> str:
        kind, _, arg = str(item_id).partition(":")
        tid = (targets or [None])[0]
        if kind == "attack":
            return self.pc_attack(cid, arg, adv, tid, two_handed=option == "two_handed")
        if kind == "offhand":
            return self.offhand_attack(cid, arg, tid, adv)
        if kind == "spell":
            return self.pc_spell(cid, arg, slot, ritual, adv, None, dtype or option, targets=targets, point=point, metamagic=metamagic)
        if kind == "mspell":
            with self.lock:
                c = self._find(cid)
                e = self._monster_book(c).get(arg.lower()) or {}
            return self.monster_cast(cid, arg, e.get("dc", 13), e.get("attack"), e.get("caster_level", 1), adv, None, dtype or option,
                                     targets=targets, point=point, slot=slot)
        if kind == "lairspell":                                 # a spell a lair action casts: "<entry>|<spell>"
            entry, _, sname = arg.partition("|")
            return self.lair_cast(cid, entry, sname, adv, tid, targets=targets, point=point, slot=slot, dtype=dtype or option)
        if kind == "lspell":                                    # a book spell cast as a legendary action: "<entry>|<spell>"
            entry, _, sname = arg.partition("|")
            with self.lock:
                c = self._find(cid)
                e = self._monster_book(c).get(sname.lower()) or {}
                lcost = dict(self._legendary_spells(c, self._entry_section(c, entry)[1] or {})).get(rules.spell(sname)["name"] if rules.spell(sname) else sname)
            if not lcost:
                raise ServiceError(f"{entry} can't cast {sname}.")
            return self.monster_cast(cid, sname, e.get("dc", 13), e.get("attack"), e.get("caster_level", 1), adv, None, dtype or option,
                                     targets=targets, point=point, slot=slot, cost=lcost)
        if kind == "monster":
            with self.lock:
                c = self._find(cid)
                _sec, e = self._entry_section(c, arg)
            if not e:
                raise ServiceError("That action isn't on the stat block.")
            return self.use_action(cid, e["name"], e.get("text", ""), adv, tid, targets=targets, point=point, option=option)
        if kind == "feature":
            return self.use_feature(cid, arg, tid, option, point)
        if kind == "maddening":
            return self.maddening_hex(cid)
        if kind == "featact":
            return self.feat_action(cid, arg, tid, option, adv)
        if kind == "standard":
            return self.standard_action(cid, arg, tid, option)
        if kind == "bonusstd":
            return self.standard_action(cid, arg, tid, option, as_bonus=True)
        if kind == "throw":
            return self.throw(cid, option or "", tid, adv)
        if kind == "scroll":
            return self.read_scroll(cid, arg, targets, point, dtype or option, adv)
        if kind == "discipline":
            return self.use_discipline(cid, arg, targets, point, dtype or option, adv)
        if kind == "wand":
            item, _sep, spell = arg.partition("|")
            return self.use_wand(cid, item, spell, int(option) if str(option or "").isdigit() else None, targets, point, dtype, adv)
        if kind == "trait":
            return self.use_trait(cid, arg, tid, point, adv)
        if kind == "charge":
            return self.charge(cid, arg, tid, option, adv)
        if kind == "ipower":
            item, _sep, key = arg.partition("|")
            return self.use_item_power(cid, item, key, tid, adv, point, option)
        if kind == "wonder":
            item, _sep, key = arg.partition("|")
            return self.use_wonder(cid, item, key, targets, point, option, adv)
        if kind == "pickup":
            if not str(option or "").isdigit():
                raise ServiceError("Pick what to pick up.")
            return self.pick_up(cid, int(option))
        if kind == "sa":
            return self.use_spell_action(cid, int(arg), targets, point, adv)
        if kind == "zone":
            if point is None:
                raise ServiceError("Pick where to move it.")
            return self.move_zone(cid, int(arg), point)
        if kind == "free" and arg == "end_concentration":
            with self.lock:
                c = self._find(cid)
                self._drop_conc(c, "ended")
                self._commit()
            return f"{c['name']} ends concentration"
        if kind == "free" and arg == "end_form":
            self.end_form(cid)
            return "Back to normal"
        if kind == "unbuff":
            return self.end_own_toggle(cid, arg)
        if kind == "unpossess":
            return self.end_possession(cid)
        raise ServiceError("Unknown action.")

    def set_rule(self, key: str, value):
        """Battle rules: economy (bool), pc_reactions / npc_reactions ('ask'|'always'|'never'), auto_death_saves (bool),
        async_rolls (bool: players' d20s roll on every screen and the action waits for them), roll_seconds (0.5 - 5),
        react_timeout (seconds a player has to answer a reaction question before it passes by itself; 0 = no limit)."""
        with self.lock:
            if key not in ("economy", "pc_reactions", "npc_reactions", "auto_death_saves", "light", "async_rolls", "roll_seconds",
                           "react_timeout"):
                raise ServiceError(f"Unknown rule '{key}'.")
            if key == "roll_seconds":
                value = round(max(0.5, min(5.0, float(value))), 2)
            if key == "react_timeout":
                try:
                    value = int(max(0, min(3600, float(value or 0))))
                except (TypeError, ValueError):
                    raise ServiceError("The reaction time limit is a number of seconds (0 = no limit).")
            if key == "light":
                if value not in ("bright", "dim", "dark"):
                    raise ServiceError("Light is bright, dim or dark.")
                self.b["map"]["light"] = value
            else:
                self.b.setdefault("rules", {})[key] = value
            if key == "react_timeout":
                for R in self._stack():
                    if R.get("wait"):
                        R["wait"].setdefault("since", time.time())
                        self._react_clock(R)                # a question already waiting gets the limit too
            self._commit()

    def rules_view(self) -> dict:
        r = {"economy": True, "pc_reactions": "ask", "npc_reactions": "always", "auto_death_saves": True,
             "async_rolls": False, "roll_seconds": 1.8, "react_timeout": 0}
        r.update(self.b.get("rules") or {})
        r["light"] = self.b.get("map", {}).get("light", "bright")
        return r

    def refund(self, cid: int, cost: str):
        """The DM gives a spent action, bonus action, reaction or movement back."""
        with self.lock:
            c = self._find(cid)
            t = c.setdefault("turn", EC.new_turn(self._speed(c)))
            if cost == "move":
                t["move"] = t.get("speed", 30)
            else:
                EC.refund(t, cost)
            self._commit(f"{c['name']} gets its {EC.LABEL.get(cost, cost).lower()} back")

    TURN_POINTS = {"action": "actions", "bonus": "bonus actions", "reaction": "reactions", "move": "movement (ft)",
                   "attacks": "attacks left of the Attack action", "legendary": "legendary actions"}

    def set_turn_points(self, cid: int, key: str, n: int):
        """The DM sets what a creature has left this turn: actions, bonus actions, reactions, feet of movement, the
        attacks left of its Attack action (Extra Attack), legendary actions."""
        if key not in self.TURN_POINTS:
            raise ServiceError("Unknown turn point.")
        with self.lock:
            c = self._find(cid)
            t = c.setdefault("turn", EC.new_turn(self._speed(c), self._legendary_max(c)))
            n = max(0, int(n))
            t[key] = n
            if key == "action":
                t["haste"] = min(t.get("haste", 0), n)          # Haste's extra action is the last one left
            elif key == "legendary":
                t["legendary_max"] = max(t.get("legendary_max", 0), n)
            self._commit(f"DM sets {c['name']}'s {self.TURN_POINTS[key]} to {n}")

    def fresh_turn_points(self, cid: int):
        """The DM gives a creature a full turn's budget again (action, bonus action, reaction, movement...)."""
        with self.lock:
            c = self._find(cid)
            self._fresh_turn(c)
            self._commit(f"DM gives {c['name']} a full turn's actions and movement again")
