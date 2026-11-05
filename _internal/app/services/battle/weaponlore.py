"""Magic weapons' signature powers in wordings any item can use, read from the item's own text like itempowers.py's (written for the
Legends Reforged weapons: Excalibur, Mjölnir, Aerondight, the Wabbajack...).

On a hit (_lore_hit, from itemextras._extra_hit):
    extra dice against a creature that has half its hit points or fewer, that hasn't taken a turn in this combat yet, or that hit the
        wielder with an attack since the end of the wielder's last turn ("the first time on each of your turns": once a turn), with
        temporary hit points equal to them when the text says so;
    a saving throw after the hit, on any hit, a ranged one or a critical one ("the target must succeed on a DC 16 Constitution saving
        throw, or its speed is halved..."): conditions, mods, damage, a push (only a Large or smaller target when it says so), and the
        wielder's temporary hit points;
    barbs or a bleeding wound: damage at the start of each of the target's turns until it saves at the end of one (or regains hit
        points, when it says so);
    a building charge: each hit adds one (to a maximum), worth +1 damage each; the hit made with all of them is a critical hit and
        spends them, and they fade when the wielder finishes a turn without a hit (an effect on the wielder);
    a death-cast throw (the bar's): its hit is a critical hit.
After the damage (_lore_after_hit, from itemextras._extra_after_hit): the riders above land on a target still standing; a creature
    dropped to 0 hit points gives the weapon its soul (kept on the pack entry, up to a maximum), or sets off a burst against the slain
    one's kind around it (a save, damage, turned), once until a short or long rest or until dawn.
Reactions (FAMILIES, asked through reactions.py via wondrous._wonder_eligible): after a miss, a charge turns it into a hit (no
    reaction spent); a hero hit by an attack marks the attacker for the extra dice above.
After-hit choices (lore_hit_choices, merged into itemextras.hit_choices): a charge for a save ("force it to make a DC 16 Constitution
    saving throw. On a failed save, the target is paralyzed..."), a charge for a second shot at a creature near the target.
The bar (lore_activations, merged into itemextras.extra_activations; played by _lore_use):
    aura      a blaze for a while: hostile creatures that start their turn near the wielder save or suffer (_lore_turn_start)
    soul      a trapped soul spent: hit points, or extra dice on the next weapon hit
    wave      in place of one attack, a line or cone of force (a save)
    volley    one attack against each of up to three creatures near a point
    deathcast one throw with advantage whose hit is a critical hit
    chaos     a die on the item's table ("1: The target turns into a rat for 1 minute..."), a save for the low rows
Limits: charges (the pack entry's), "until the next dawn" (resources "item:<name>:<key>"), "until you finish a short or long rest"
    (resources "short:item:<name>:<key>", cleared by both rests).
Worn (wondrous.item_mods reads them): advantage on death saves; hit points back at the start of each turn while at half or fewer
    (`regen_low`, _lore_turn_start).
"""
import re
from typing import List, Optional

from ...rules.data import rules
from ...rules.dice import roll_dice
from ..common import ServiceError
from . import combat_rules as CR
from . import geometry as G
from .constants import ACTIVE

SIZES = ("Tiny", "Small", "Medium", "Large", "Huge", "Gargantuan")
NUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6}
FAMILIES = {"item_sure": "Turn a miss into a hit"}
FREE = {"item_sure"}
# the sentences of this module that itempowers.weapon_hits must leave alone (extra damage only now and then, not on every hit)
CLAIMED = re.compile(r"half its hit points or fewer|hasn't taken a turn in this combat|hit you with an attack since", re.I)

_HOW = r"(the first time on each of your turns that you|when you)"
COND_EXTRA = re.compile(_HOW + r" hit a creature that (has half its hit points or fewer|hasn't taken a turn in this combat yet|hit you with an attack since "
                        r"the end of your last turn)[^,]*, (?:it|the target) takes an extra (\d+d\d+) (\w+) damage(, and you gain temporary hit points "
                        r"equal to)?", re.I)
HIT_SAVE = re.compile(_HOW + r" (hit a creature|score a critical hit) with (?:a (ranged) attack using )?(?:this|the|it)\b[^,]*?, (?:you gain (\d+d\d+) "
                      r"temporary hit points, and )?the target must succeed on (a DC \d+ \w+ saving throw[^\n]*)", re.I)
BLEED = re.compile(r"when you (hit a creature|score a critical hit) with (?:a (ranged) attack using )?(?:this|the|it)\b[^,]*?, [^.]*?(?:at the start of "
                   r"each of its turns, the target takes|it takes) (\d+d\d+) (\w+) damage(?: at the start of each of its turns)?\. At the end of each "
                   r"of its turns, the target can make a DC (\d+) (\w+) saving throw, ending the effect on itself on a success\.( The effect also "
                   r"ends if the target regains hit points)?", re.I)
BUILD = re.compile(r"each time you hit a creature with this \w+, the \w+ gains a charge, to a maximum of (\d+) charges", re.I)
SOULS = re.compile(r"when you reduce a creature that isn't an? (\w+) or an? (\w+) to 0 hit points with this \w+, the \w+ traps its soul\. The \w+ can "
                   r"hold up to (\d+) souls", re.I)
BURST = re.compile(r"when you reduce an? (\w+) to 0 hit points with this \w+, [^:]*: each other (\w+) within (\d+) feet of it must make (a DC \d+ \w+ "
                   r"saving throw[^\n]*)", re.I)
SURE = re.compile(r"when you miss with an attack using this \w+, you can expend (\d+) charges? to turn the miss into a hit", re.I)
GRIP = re.compile(r"when you hit a creature with this \w+, you can expend (\d+) charges? to force it to make (a DC \d+ \w+ saving throw)\. On a "
                  r"failed save, the target (?:is|has) ([^.]*)\.", re.I)
TWIN = re.compile(r"when you hit a creature with this \w+, you can expend (\d+) charges? to fire a second (\w+) at a different creature within "
                  r"(\d+) feet of the target", re.I)
AURA = re.compile(r"(as a bonus action|as an action), you can [^.]*? for (\d+) (minute|round)s?\.[^\n]*?any hostile creature that starts its turn "
                  r"within (\d+) feet of you must succeed on (a DC \d+ \w+ saving throw[^.]*\.)", re.I)
SPEND = re.compile(r"(as a bonus action|as an action), you can release one soul trapped in the \w+ to regain (\d+d\d+) hit points, or to [^:]*: "
                   r"[^.]*? deals an additional (\d+d\d+) (\w+) damage", re.I)
WAVE = re.compile(r"replace one of your attacks by expending (\d+) charges? to ([^.]*?)\.\s*(Each creature in the (?:line|cone|area) must make a DC "
                  r"\d+ \w+ saving throw[^\n]*)", re.I)
VOLLEY = re.compile(r"as an action, you can expend (\d+) charges? to [^:]*: make one (ranged|melee) attack with this \w+ against each of up to (\w+) "
                    r"creatures (?:of your choice )?within (\d+) feet of a point", re.I)
DEATH = re.compile(r"when you make a ranged attack with this \w+, you can [^:]*: you have advantage on the attack roll, and if the attack hits, "
                   r"it is a critical hit", re.I)
CHAOS = re.compile(r"as an action, you can expend (\d+) charges? and point the \w+ at a creature you can see within (\d+) feet of you, then roll "
                   r"a d(\d+)", re.I)
CHAOS_SAVE = re.compile(r"On a 1 to (\d+), the target must make a DC (\d+) (\w+) saving throw", re.I)


def _text(item: Optional[dict]) -> str:
    from .wondrous import _clean
    return _clean((item or {}).get("text"))


def _para(text: str, at: int) -> str:
    """The paragraph of `text` around position `at`."""
    start = text.rfind("\n", 0, at) + 1
    end = text.find("\n", at)
    return text[start:end if end >= 0 else len(text)]


def _title(text: str, at: int, fallback: str) -> str:
    """The name of the titled property ("Thirty Torches. As a bonus action...") the text at `at` belongs to."""
    m = re.match(r"([A-Z][^.!:\n]{0,40}?)([.!])\s+[A-Z]", _para(text, at))
    if m and len(m.group(1).split()) <= 5 and m.group(1).split()[0] not in ("You", "The", "This", "It", "When", "As", "While", "If", "Each"):
        return m.group(1) + ("!" if m.group(2) == "!" else "")
    return fallback


def _limit(para: str) -> dict:
    """What a use costs: {'daily': True} (until the next dawn), {'short': True} (until a short or long rest), {'charge': n}."""
    low = para.lower()
    if "until you finish a short or long rest" in low:
        return {"short": True}
    if re.search(r"until the next dawn|once per day", low):
        return {"daily": True}
    m = re.search(r"expend(?:ing)? (\d+) charges?", low)
    return {"charge": int(m.group(1))} if m else {}


def _save_of(chunk: str) -> Optional[dict]:
    """{'sv', 'parts', 'cap'} of a saving throw's wording ("a DC 16 Constitution saving throw, or its speed is halved...")."""
    from .standard import StandardMixin
    _pre, post, save = CR.split_save(chunk)
    if not save:
        return None
    low = post.lower()
    sv = {"ab": save[0], "dc": save[1], "half": "half as much" in low, **StandardMixin._save_terms(post)}
    push = re.search(r"pushed (?:up to )?(\d+) feet", low)
    if push:
        sv["push"] = int(push.group(1))
    if re.search(r"\bis turned\b", low):                    # turned: frightened and fleeing, until it takes damage (like Turn Undead)
        sv.update(conds=sorted(set(sv.get("conds") or []) | {"Frightened"}), mods=dict(sv.get("mods") or {}, turned=True), ends_on=["damage"],
                  note="turned: flees")
    cap = re.search(r"\b(tiny|small|medium|large|huge) or smaller\b", low)
    return {"sv": sv, "parts": [list(p) for p in CR.save_damage(post)], "cap": cap.group(1).capitalize() if cap else None}


def lore_hits(item: Optional[dict]) -> List[dict]:
    """What the weapon's hits do beyond itempowers.weapon_hits: [{'kind': 'extra'|'save'|'bleed'|'build', ...}] (see the module's text)."""
    if not item or not item.get("weapon"):
        return []
    text = _text(item)
    out = []
    m = BUILD.search(text)
    if m and re.search(r"the hit is a critical hit and the \w+ loses all its charges", text):
        out.append({"kind": "build", "top": int(m.group(1))})
    for m in COND_EXTRA.finditer(text):
        when = "half" if "half its" in m.group(2) else "fresh" if "hasn't" in m.group(2) else "hurt_me"
        out.append({"kind": "extra", "when": when, "once": m.group(1).lower().startswith("the first"), "dice": m.group(3), "type": m.group(4).lower(),
                    "temp_equal": bool(m.group(5))})
    for m in HIT_SAVE.finditer(text):
        s = _save_of(m.group(5))
        if s:
            out.append({"kind": "save", "trigger": "crit" if "critical" in m.group(2).lower() else "ranged" if m.group(3) else "hit",
                        "once": m.group(1).lower().startswith("the first"), "temp": m.group(4), **s})
    for m in BLEED.finditer(text):
        out.append({"kind": "bleed", "trigger": "crit" if "critical" in m.group(1).lower() else "ranged" if m.group(2) else "hit",
                    "dice": m.group(3), "type": m.group(4).lower(), "dc": int(m.group(5)), "ab": m.group(6)[:3].lower(), "heal_ends": bool(m.group(7))})
    return out


def lore_kills(item: Optional[dict]) -> List[dict]:
    """What the weapon does when it drops a creature to 0 hit points: [{'kind': 'souls'|'burst', ...}]."""
    if not item or not item.get("weapon"):
        return []
    text = _text(item)
    out = []
    m = SOULS.search(text)
    if m:
        out.append({"kind": "souls", "not": [m.group(1).lower(), m.group(2).lower()], "top": int(m.group(3))})
    m = BURST.search(text)
    if m:
        s = _save_of(m.group(4))
        if s:
            out.append({"kind": "burst", "vs": m.group(1).lower(), "who": m.group(2).lower(), "ft": int(m.group(3)), **s,
                        **_limit(_para(text, m.start()))})
    return out


def lore_sure(item: Optional[dict]) -> int:
    """The charges a miss turned into a hit costs (0: the weapon can't)."""
    m = SURE.search(_text(item)) if item and item.get("weapon") else None
    return int(m.group(1)) if m else 0


def lore_hit_choices(item: Optional[dict]) -> List[dict]:
    """After-hit choices (itemextras.hit_choices' shape): a charge for a save, a charge for a second shot."""
    if not item or not item.get("weapon"):
        return []
    text = _text(item)
    out = []
    m = GRIP.search(text)
    if m:
        s = _save_of(m.group(2) + ". On a failed save, the target is " + m.group(3) + ".")
        name = _title(text, m.start(), "Charged strike")
        if s and (s["sv"].get("conds") or s["sv"].get("mods") or s["parts"]):
            conds = ", ".join(c.lower() for c in s["sv"].get("conds") or []) or "hindered"
            out.append({"key": "grip", "label": f"{name}: {m.group(1)} charge, DC {s['sv']['dc']} {s['sv']['ab'].title()} or {conds}", "daily": False,
                        "charge": int(m.group(1)), "parts": s["parts"], "sv": s["sv"]})
    m = TWIN.search(text)
    if m:
        name = _title(text, m.start(), "Second shot")
        out.append({"key": "twin", "label": f"{name}: {m.group(1)} charge, a second {m.group(2)} at a creature within {m.group(3)} ft of the target",
                    "daily": False, "charge": int(m.group(1)), "parts": [], "sv": None, "lore": "twin", "reach": int(m.group(3))})
    return out


def _chaos_rows(text: str) -> dict:
    """{roll: {'kind': 'form'|'size'|'heal'|'swap'|'hurt', ...}} from the table's "1: The target turns into a rat..." lines."""
    from .standard import StandardMixin
    rows = {}
    for n, row in re.findall(r"^(\d+): (.+)$", text, re.M):
        low = row.lower()
        spec = {"text": row.strip()}
        form = re.search(r"turns into an? (\w+) for (\d+) (minute|round)s?", low)
        heal = re.search(r"regains (\d+d\d+) hit points", low)
        if form:
            spec.update(kind="form", beast=form.group(1).title(), rounds=int(form.group(2)) * (10 if form.group(3) == "minute" else 1))
        elif "enlarge/reduce" in low or "grows or shrinks" in low:
            spec.update(kind="size", rounds=CR.duration_rounds(row) or 10)
        elif heal:
            spec.update(kind="heal", dice=heal.group(1))
        elif "swap places" in low:
            spec.update(kind="swap")
        else:
            terms = StandardMixin._save_terms(row)
            spec.update(kind="hurt", parts=[list(p) for p in CR.damage_parts(row)], **{k: terms[k] for k in ("conds", "repeat", "rounds", "until", "mods")})
        rows[int(n)] = spec
    return rows


def lore_activations(item: Optional[dict]) -> List[dict]:
    """The weapon's bar entries this module plays (itempowers.activations' shape, with 'lore': True)."""
    if not item or not item.get("weapon"):
        return []
    text = _text(item)
    out = []

    def put(key, m, fallback, cost, **kw):
        para = _para(text, m.start())
        out.append(dict({"key": key, "name": _title(text, m.start(), fallback), "cost": cost, "lore": True, "tip": para[:300]}, **{**_limit(para), **kw}))

    m = AURA.search(text)
    s = _save_of(m.group(5)) if m else None
    if m and s:
        rounds = int(m.group(2)) * (10 if m.group(3).lower() == "minute" else 1)
        put("aura", m, "Blaze", "bonus" if "bonus" in m.group(1).lower() else "action", target={"type": "self"}, rounds=rounds,
            aura={"ft": int(m.group(4)), "ab": s["sv"]["ab"], "dc": s["sv"]["dc"], "conds": list(s["sv"].get("conds") or []),
                  "until": s["sv"].get("until"), "rounds": s["sv"].get("rounds"), "mods": s["sv"].get("mods")})
    m = SPEND.search(text)
    if m and SOULS.search(text):
        put("soul", m, "Spend a soul", "bonus" if "bonus" in m.group(1).lower() else "action", target={"type": "self"}, heal=m.group(2),
            shadow=[m.group(3), m.group(4).lower()],
            options=[{"value": "heal", "label": f"Regain {m.group(2)} hit points"},
                     {"value": "shadow", "label": f"+{m.group(3)} {m.group(4).lower()} on your next weapon hit"}])
    m = WAVE.search(text)
    if m:
        from .wondrous import _area
        area = _area(m.group(2).lower())
        s = _save_of(m.group(3))
        if area and s:
            put("wave", m, "Wave", "attack", charge=int(m.group(1)), area=area, sv=s["sv"], parts=s["parts"],
                target={"type": "self_area", "aim": True, "area": area})
    m = VOLLEY.search(text)
    if m:
        rng = re.findall(r"\d+", str(item.get("range") or ""))
        area = {"shape": "sphere", "size": int(m.group(4)), "origin": "point"}
        put("volley", m, "Volley", "action", charge=int(m.group(1)), count=NUM.get(m.group(3).lower(), 3), range=int(rng[0]) if rng else 60,
            target={"type": "self_area", "aim": True, "area": area})
    m = DEATH.search(text)
    if m:
        rng = re.findall(r"\d+", str(item.get("range") or ""))
        put("deathcast", m, "Mighty throw", "attack", range=int(rng[-1]) if rng else 60, target={"type": "creature", "count": 1, "enemies": True})
    m = CHAOS.search(text)
    if m:
        sv = CHAOS_SAVE.search(text)
        put("chaos", m, "Chaos", "action", charge=int(m.group(1)), range=int(m.group(2)), die=int(m.group(3)), rows=_chaos_rows(text),
            save={"upto": int(sv.group(1)), "dc": int(sv.group(2)), "ab": sv.group(3)[:3].lower()} if sv else None,
            target={"type": "creature", "count": 1})
    return out


class WeaponLoreMixin:
    # ------------------------------------------------------------------ hits
    def _lore_hit(self, att: dict, tgt: dict, R: dict, item: dict) -> list:
        """Extra damage parts of this module's powers; the riders that follow the damage are kept in R['lore_after']."""
        a, cur = R["atk"], R["cur"]
        out = []
        if a.get("lore_crit") and not cur.get("crit"):         # a death-cast throw
            cur["crit"] = True
            self._line(R, f"{item['name']}: the throw strikes true - a critical hit", "critical hit")
        specs = lore_hits(item)
        if not specs:
            return out
        wtype = (a.get("parts") or [["", "bludgeoning"]])[0][1]
        after = R.setdefault("lore_after", [])
        mine = self.b.get("status") != ACTIVE or self.b.get("turn") == att["id"]     # "the first time on each of your turns": not a reaction's hit
        for p in specs:
            if p["kind"] == "build":                          # Aerondight: +1 a charge, the full charge's hit is a critical one
                name = f"{item['name']} (charge)"
                eff = next((e for e in att.get("effects") or [] if e["name"] == name and e.get("source_id") == att["id"]), None)
                n = int(((eff or {}).get("mods") or {}).get("lore_charge") or 0)
                if n >= p["top"]:
                    cur["crit"] = True
                    self._effect_off(att, eff, "released")
                    self._line(R, f"{item['name']} releases its {n} charges: a critical hit", "charge released")
                else:
                    if n:
                        out.append([str(n), wtype])
                        self._line(R, f"{item['name']}: +{n} ({n} charge{'s' if n > 1 else ''})", item["name"])
                    after.append({"target": tgt["id"], "build": name, "n": n + 1, "item": item["name"]})
        for p in specs:
            if p["kind"] == "extra":
                if not self._lore_fits(att, tgt, p) or p["once"] and (not mine or not self._once_per_turn(att, f"lore:{item['name']}:{p['when']}")):
                    continue
                n = sum(int(roll_dice(p["dice"]).total) for _ in range(2 if cur.get("crit") else 1))    # rolled now: the hero gains what it deals
                out.append([str(n), p["type"] or wtype])
                self._line(R, f"{item['name']}: +{n} {p['type']}", item["name"])
                if p["temp_equal"] and n > 0:
                    self._give_temp(att, n)
                    self._line(R, f"{att['name']} gains {n} temporary hit points ({item['name']})", f"+{n} temp HP")
            elif p["kind"] in ("save", "bleed"):
                if p["trigger"] == "crit" and not cur.get("crit") or p["trigger"] == "ranged" and a.get("melee"):
                    continue
                if p["kind"] == "save" and p.get("cap") and SIZES.index(self._size_of(tgt)) > SIZES.index(p["cap"]) and \
                        not (p["sv"].get("conds") or p["sv"].get("mods") or p["parts"]):
                    continue                                   # too big to push, and the push is all it does
                if p.get("once") and (not mine or not self._once_per_turn(att, f"lore:{item['name']}:{p['kind']}")):
                    continue
                if p.get("temp"):
                    n = int(roll_dice(p["temp"]).total)
                    self._give_temp(att, n)
                    self._line(R, f"{att['name']} gains {n} temporary hit points ({item['name']})", f"+{n} temp HP")
                after.append(dict(p, target=tgt["id"], item=item["name"]))
        return out

    def _lore_fits(self, att: dict, tgt: dict, p: dict) -> bool:
        """Does the target meet the condition of a conditional extra (half its hit points, no turn yet, hit the wielder)?"""
        if p["when"] == "half":
            return self._hp_of(tgt) <= self._max_hp(tgt) // 2
        if p["when"] == "fresh":
            return self.b.get("status") == ACTIVE and not tgt.get("had_turn")
        return any((e.get("mods") or {}).get("lore_hurt") == att["id"] for e in tgt.get("effects") or [])

    def _lore_after_hit(self, R: dict, att: dict, tgt: dict):
        """After the damage: the hit's riders on a target still standing, the charge gained; a kill's soul or burst."""
        rest = []
        for x in R.pop("lore_after", None) or []:
            if x["target"] != tgt["id"]:
                rest.append(x)
            elif x.get("build"):
                self._effect_on(att, x["build"], [], None, None, None, None, att["name"], {"lore_charge": x["n"]}, None, att["id"],
                                until=self._until("caster_end_next", att, att))
                self._line(R, f"{x['item']} gains a charge ({x['n']})", f"charge {x['n']}")
            elif not self._alive(tgt):
                continue
            elif x["kind"] == "bleed":                        # one wound per weapon: a new one replaces it
                self._effect_on(tgt, f"{x['item']} (bleeding)", [], x["ab"], x["dc"], "end", None, att["name"],
                                {"dot": {"when": "start", "dice": x["dice"], "type": x["type"]}}, None, att["id"],
                                ends_on=["heal"] if x["heal_ends"] else None)
                self._line(R, f"{tgt['name']} is bleeding: {x['dice']} {x['type']} at the start of its turns (DC {x['dc']} {x['ab'].upper()} ends it)",
                           "bleeding")
            else:
                sv = dict(x["sv"])
                if x.get("cap") and SIZES.index(self._size_of(tgt)) > SIZES.index(x["cap"]):
                    sv.pop("push", None)
                R.setdefault("follow", []).append(self._strike(att, x["item"], [tgt["id"]], mode="save", sv=sv, parts=[list(p) for p in x["parts"]],
                                                               magical=True))
        if rest:
            R["lore_after"] = rest
        a = R.get("atk") or {}
        item = self._weapon_item(att, a) if a.get("weapon") else None
        if item is None or self._hp_of(tgt) > 0 or R.get(f"lore_kill:{tgt['id']}"):
            return
        R[f"lore_kill:{tgt['id']}"] = True
        char = self._sheet(att)
        kind = self._kind(tgt)
        for k in lore_kills(item):
            if k["kind"] == "souls" and kind not in k["not"] and char:
                entry = char.find_item(item["name"])
                if entry is None:
                    continue
                n = int(entry.get("souls") or 0)
                if n >= k["top"]:
                    self._line(R, f"{item['name']} can hold no more souls ({n})", "full")
                    continue
                entry["souls"] = n + 1
                char.save()
                self._line(R, f"{item['name']} traps {tgt['name']}'s soul ({n + 1}/{k['top']})", "soul trapped")
            elif k["kind"] == "burst" and kind == k["vs"] and char and tgt.get("pos"):
                key = f"{'short:' if k.get('short') else ''}item:{item['name']}:burst"
                if char.d["resources"].get(key):
                    continue
                ids = [o["id"] for o in self.b["combatants"] if o is not tgt and o is not att and o.get("pos") and self._alive(o)
                       and self._kind(o) == k["who"] and self._dist(o, tgt) <= k["ft"]]
                if not ids:
                    continue
                char.d["resources"][key] = 1
                char.save()
                self._line(R, f"{tgt['name']} bursts with holy light ({item['name']})", "burst")
                R.setdefault("follow", []).append(self._strike(att, f"{item['name']} (burst)", ids, mode="save", sv=dict(k["sv"]),
                                                               parts=[list(p) for p in k["parts"]], magical=True))

    # ------------------------------------------------------------------ reactions
    def _lore_families(self, c: dict) -> List[str]:
        """This module's reaction families the hero has (for the reaction settings)."""
        char = self._sheet(c) if c and not c.get("form") else None
        return ["item_sure"] if char and any(lore_sure(d) for _e, d in char._active_items()) else []

    def _lore_eligible(self, out: list, window: str, R: dict, att: Optional[dict], tgt: Optional[dict], ctx: dict):
        cur = R.get("cur") or {}
        a = R.get("atk") or {}
        if window == "after_damage" and att and tgt and att is not tgt and R.get("mode") == "attack":
            tchar = self._sheet(tgt) if not tgt.get("form") else None   # a hero hit: the attacker is marked for its penance
            item = next((d for _e, d in (tchar._active_items() if tchar else []) if any(p["kind"] == "extra" and p["when"] == "hurt_me"
                                                                                       for p in lore_hits(d))), None)
            if item is not None:
                self._effect_on(att, f"Marked by {item['name']} ({tgt['name']})", [], None, None, None, None, tgt["name"], {"lore_hurt": tgt["id"]},
                                None, tgt["id"], until={"end": tgt["id"], "skip": 1 if self.b.get("turn") == tgt["id"] else 0})
        if window == "missed" and att and tgt and not att.get("form") and a.get("weapon") and a.get("item"):
            char = self._sheet(att)
            e = char.find_item(a["item"]) if char else None
            d = rules.item(e["name"]) if e else None
            n = lore_sure(d)
            if n and any(x is e for x, _d in char._active_items()) and self._charges_left(e) >= n:
                out.append({"reactor": att["id"], "cost": "free",
                            "options": [{"key": "item_sure", "label": f"{d['name']}: the miss becomes a hit ({n} charge, {self._charges_left(e)} left)",
                                         "detail": f"{cur.get('total')} vs AC {cur.get('ac')}"}],
                            "text": f"{att['name']} misses {tgt['name']} ({cur.get('total')} vs AC {cur.get('ac')}). Use {d['name']}?"})

    def _lore_react(self, window: str, R: dict, reactor: dict, fam: str, arg: str, ctx: dict):
        cur = R.setdefault("cur", {})
        a = R.get("atk") or {}
        char = self._sheet(reactor)
        e = char.find_item(a.get("item") or "") if char else None
        d = rules.item(e["name"]) if e else None
        n = lore_sure(d)
        if fam != "item_sure" or not n or self._charges_left(e) < n:
            return
        e["charges_left"] = self._charges_left(e) - n
        char.save()
        cur.update(total=max(int(cur.get("total") or 0), int(cur.get("ac") or 10)), kept=max(int(cur.get("kept") or 2), 2))
        self._line(R, f"{reactor['name']}'s {d['name']} never misses: the attack hits ({e['charges_left']} charges left)", d["name"])

    # ------------------------------------------------------------------ turns
    def _lore_turn_start(self, c: dict):
        """A turn starts: a worn scabbard's hit points (at half or fewer); the blazes of hostile wielders nearby (a save)."""
        for e, v in self._fxs(c, "regen_low"):
            if 0 < self._hp_of(c) <= self._max_hp(c) // 2 and self._heal(c, int(v)):
                self._say(f"{c['name']} regains {int(v)} HP ({e['name']})")
            break
        if not c.get("pos") or not self._alive(c):
            return
        for o in self.b["combatants"]:
            if o is c or not o.get("pos") or not self._alive(o) or not self._hostile(o, c):
                continue
            for e in list(o.get("effects") or []):
                au = (e.get("mods") or {}).get("lore_aura")
                if not au or self._dist(o, c) > int(au["ft"]):
                    continue
                res = self._saving_throw(c, au["ab"], int(au["dc"]), conds=au.get("conds") or [], source=o, label=e["name"])
                self._say(f"{c['name']} {au['ab'].upper()} save against {o['name']}'s {e['name']}: d20 {res['kept']}{res['note']} = {res['total']} "
                          f"vs DC {au['dc']} — " + ("success" if res["ok"] else "failed"))
                if not res["ok"] and (au.get("conds") or au.get("mods")):
                    self._effect_on(c, e["name"], list(au.get("conds") or []), None, None, None, au.get("rounds"), o["name"], au.get("mods"), None,
                                    o["id"], until=self._until(au["until"], o, c) if au.get("until") else None)
                    self._say(f"{c['name']} is now {', '.join(x.lower() for x in au.get('conds') or []) or 'hindered'} ({e['name']})")

    # ------------------------------------------------------------------ the bar
    def _lore_why(self, c: dict, char, entry: Optional[dict], item: dict, p: dict) -> Optional[str]:
        """Why this module's bar entry can't be used now (None: it can)."""
        if p.get("short") and char.d["resources"].get(f"short:item:{item['name']}:{p['key']}"):
            return "Used until you finish a short or long rest"
        if p["key"] == "soul" and int((entry or {}).get("souls") or 0) < 1:
            return "No souls trapped"
        return None

    def _lore_spend(self, char, entry: dict, data: dict, p: dict) -> str:
        """Pay a use (the day's, the rest's, charges); a note for the log."""
        note = ""
        if p.get("daily"):
            char.d["resources"][f"item:{data['name']}:{p['key']}"] = 1
            note = " (once a day)"
        if p.get("short"):
            char.d["resources"][f"short:item:{data['name']}:{p['key']}"] = 1
            note = " (until a rest)"
        if p.get("charge"):
            entry["charges_left"] = self._charges_left(entry) - p["charge"]
            note = f" ({p['charge']} charge{'s' if p['charge'] > 1 else ''}, {entry['charges_left']} left)"
        char.save()
        return note

    def _lore_use(self, c: dict, char, entry: dict, data: dict, p: dict, key: str, target_id, point=None, option=None) -> str:
        """Play one of lore_activations' powers (the cost is paid here)."""
        from . import features as F
        why = self._lore_why(c, char, entry, data, p)
        if why:
            raise ServiceError(f"{entry['name']}: {why.lower()}.")
        label = f"{entry['name']} ({p['name']})"
        if key == "aura":
            self._pay(c, p["cost"], label)
            note = self._lore_spend(char, entry, data, p)
            self._effect_on(c, f"{entry['name']} ({p['name']})", [], None, None, None, p["rounds"], c["name"], {"lore_aura": dict(p["aura"])}, None, c["id"])
            line = f"{c['name']}'s {entry['name']} blazes{note}: hostile creatures that start their turn within {p['aura']['ft']} ft must save"
            self._commit(line)
            return line
        if key == "soul":
            self._pay(c, p["cost"], label)
            entry["souls"] = int(entry.get("souls") or 0) - 1
            char.save()
            left = f"{entry['souls']} soul{'s' if entry['souls'] != 1 else ''} left"
            if option == "shadow":
                self._effect_on(c, f"{entry['name']} (shadow)", [], None, None, None, None, c["name"], {"dmg": tuple(p["shadow"]), "once": True}, None,
                                c["id"], until=self._until("caster_end_next", c, c))
                line = f"{c['name']} releases a soul into {entry['name']}: +{p['shadow'][0]} {p['shadow'][1]} on the next weapon hit ({left})"
            else:
                n = int(roll_dice(p["heal"]).total)
                self._heal(c, n)
                line = f"{c['name']} releases a soul from {entry['name']}: regains {n} HP ({left})"
            self._commit(line)
            return line
        w = next((x for x in char.attacks() if x["name"] == entry["name"]), None)
        if w is None:
            raise ServiceError(f"Wield {entry['name']} first.")
        if key == "wave":
            tgt = self._find_or_none(target_id)
            aim = point or self.b.get("aim") or (list(G.centre(tgt["pos"], tgt.get("span") or 1)) if tgt and tgt.get("pos") else None)
            if not c.get("pos") or aim is None:
                raise ServiceError("Pick where to send the wave.")
            self._pay_attack(c, F.extra_attacks(char), label)
            note = self._lore_spend(char, entry, data, p)
            tiles = G.area_for(p["area"], c["pos"], c.get("span") or 1, tuple(aim), *self._bounds())
            ids = [o["id"] for o in G.creatures_in(tiles, self.b["combatants"]) if o is not c and not self._is_out(o)]
            self._area_vfx(c, tiles, p["parts"], p["area"]["shape"], aim)
            self._say(f"{c['name']} releases {p['name']} from {entry['name']}{note}")
            out = self._run_r(self._strike(c, label, ids, mode="save", sv=dict(p["sv"]), parts=[list(x) for x in p["parts"]], magical=True)) \
                if ids else f"{c['name']}'s {p['name']} reaches nobody"
            self._commit()
            return out
        if key == "volley":
            tgt = self._find_or_none(target_id)
            aim = point or (list(G.centre(tgt["pos"], tgt.get("span") or 1)) if tgt and tgt.get("pos") else None)
            if not c.get("pos") or aim is None:
                raise ServiceError("Pick the point to shoot at.")
            if G.distance_to_point(c["pos"], c.get("span") or 1, aim) > p["range"]:
                raise ServiceError(f"That point is out of range ({p['range']} ft).")
            size = p["target"]["area"]["size"]
            near = sorted((o for o in self.b["combatants"] if o is not c and o.get("pos") and self._alive(o) and not self._is_out(o) and self._hostile(o, c)
                           and G.distance_to_point(o["pos"], o.get("span") or 1, aim) <= size and self._sees(c, o)),
                          key=lambda o: G.distance_to_point(o["pos"], o.get("span") or 1, aim))[:p["count"]]
            if not near:
                raise ServiceError(f"No foe within {size} ft of that point.")
            self._pay(c, p["cost"], label)
            note = self._lore_spend(char, entry, data, p)
            self._say(f"{c['name']} looses {p['name']} from {entry['name']}{note}: " + ", ".join(o["name"] for o in near))
            out = self._run_r(self._strike(c, label, [o["id"] for o in near], mode="attack", atk=dict(self._weapon_atk(c, w)), magical=True))
            self._commit()
            return out
        if key == "deathcast":
            tgt = self._target(target_id)
            atk = self._check_reach(c, tgt, dict(self._weapon_atk(c, w), melee=False, adv="adv", lore_crit=True))     # range, total cover
            self._pay_attack(c, F.extra_attacks(char), label)
            note = self._lore_spend(char, entry, data, p)
            self._say(f"{c['name']} hurls {entry['name']} with all its strength{note}")
            out = self._run_r(self._strike(c, label, [tgt["id"]], mode="attack", atk=atk, magical=True))
            self._commit()
            return out
        if key == "chaos":
            return self._lore_chaos(c, char, entry, data, p, target_id)
        raise ServiceError(f"{entry['name']} can't do that.")

    def _lore_chaos(self, c: dict, char, entry: dict, data: dict, p: dict, target_id) -> str:
        """A die on the item's table: the low rows need a failed save, the high ones just happen."""
        tgt = self._target(target_id)
        if c.get("pos") and tgt.get("pos") and self._dist(c, tgt) > p["range"]:
            raise ServiceError(f"{tgt['name']} is out of range ({p['range']} ft).")
        self._pay(c, p["cost"], data["name"])
        note = self._lore_spend(char, entry, data, p)
        r = self.rng.randint(1, p["die"])
        row = p["rows"].get(r) or {"kind": "hurt", "parts": [], "text": "nothing happens"}
        label = f"{entry['name']} ({r})"
        self._say(f"{c['name']} points {entry['name']} at {tgt['name']}{note}: d{p['die']} {r} - {row['text']}")
        sv = p.get("save") if p.get("save") and r <= p["save"]["upto"] else None
        if row["kind"] == "hurt":                              # fire, lightning, stone, fear: a save for them (the strike's own)
            if sv:
                S = self._strike(c, label, [tgt["id"]], mode="save", parts=row["parts"], magical=True,
                                 sv={"ab": sv["ab"], "dc": sv["dc"], "half": False, "conds": list(row.get("conds") or []), "repeat": row.get("repeat"),
                                     "rounds": row.get("rounds"), "until": row.get("until"), "mods": row.get("mods")})
            else:
                S = self._strike(c, label, [tgt["id"]], mode="auto", parts=row["parts"], magical=True)
            out = self._run_r(S)
            self._commit()
            return out
        if sv:
            res = self._saving_throw(tgt, sv["ab"], sv["dc"], label=data["name"])
            self._say(f"{tgt['name']} {sv['ab'].upper()} save against {data['name']}: d20 {res['kept']}{res['note']} = {res['total']} vs DC {sv['dc']} — "
                      + ("success: nothing happens" if res["ok"] else "failed"))
            if res["ok"]:
                self._commit()
                return f"{tgt['name']} resists the {data['name']}"
        line = row["text"]
        if row["kind"] == "form":
            from ...rules.monsters import bestiary
            beast = next((m for m in sorted(bestiary.search(row["beast"], types=["beast"]), key=lambda m: m.get("source") != "MM")
                          if m["name"].lower() == row["beast"].lower()), None)
            if beast is not None and not (self._monster(tgt) or {}).get("legendary"):
                R = self._new_r("seq", c, data["name"], items=[], i=0)
                self._transform(tgt, beast["id"], R)
                self._effect_on(tgt, f"{data['name']} ({row['beast'].lower()})", [], None, None, None, row["rounds"], c["name"], {"ends_form": beast["name"]},
                                None, c["id"])
                line = f"{tgt['name']} is a {row['beast'].lower()} for a while"
            else:
                line = f"{tgt['name']} shimmers, but keeps its shape"
        elif row["kind"] == "size":
            grow = self.rng.randint(0, 1) == 1
            mods = {"dmg": ("1d4", ""), "save_adv": ["str"], "check_adv": ["str"], "size_step": 1} if grow else \
                {"dmg_minus": "1d4", "save_dis": ["str"], "check_dis": ["str"], "size_step": -1}
            self._effect_on(tgt, f"{data['name']} ({'enlarged' if grow else 'reduced'})", [], None, None, None, row["rounds"], c["name"], mods, None, c["id"])
            line = f"{tgt['name']} {'grows' if grow else 'shrinks'} for 1 minute"
        elif row["kind"] == "heal":
            n = int(roll_dice(row["dice"]).total)
            self._heal(tgt, n)
            line = f"{tgt['name']} regains {n} HP"
        elif row["kind"] == "swap" and c.get("pos") and tgt.get("pos") and (c.get("span") or 1) == (tgt.get("span") or 1):
            a_, b_ = list(c["pos"]), list(tgt["pos"])
            c["pos"], tgt["pos"] = b_, a_
            self._vfx("blink", id=c["id"], at=a_, to=b_)
            self._vfx("blink", id=tgt["id"], at=b_, to=a_)
            line = f"{c['name']} and {tgt['name']} swap places"
        self._commit(line)
        return line

    def _lore_choice(self, R: dict, att: dict, item: dict, ch: dict, tgt: dict):
        """A chosen after-hit power of this module: a second shot at another creature near the target (a charge)."""
        char = self._sheet(att)
        entry = char.find_item(item["name"]) if char else None
        w = next((x for x in char.attacks() if x["name"] == entry["name"]), None) if entry else None
        if not entry or w is None or self._charges_left(entry) < ch["charge"]:
            return
        atk = dict(self._weapon_atk(att, w))
        far = atk.get("long") or atk.get("reach") or 5
        near = sorted((o for o in self.b["combatants"] if o is not tgt and o is not att and o.get("pos") and tgt.get("pos") and self._alive(o)
                       and not self._is_out(o) and self._hostile(o, att) and self._dist(o, tgt) <= ch["reach"] and self._dist(o, att) <= far
                       and self._sees(att, o)), key=lambda o: self._dist(o, tgt))
        if not near:
            self._line(R, f"{item['name']}: no other foe within {ch['reach']} ft of {tgt['name']}", "no second target")
            return
        entry["charges_left"] = self._charges_left(entry) - ch["charge"]
        char.save()
        self._line(R, f"{att['name']} fires a second bolt from {item['name']} at {near[0]['name']} ({entry['charges_left']} charges left)", item["name"])
        R.setdefault("follow", []).append(self._strike(att, f"{item['name']} (second bolt)", [near[0]["id"]], mode="attack", atk=atk, magical=True))
