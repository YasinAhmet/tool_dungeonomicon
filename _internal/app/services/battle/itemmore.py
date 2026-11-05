"""Magic items of Arcana Unleashed, Eberron: Forge of the Artificer, Heroes of Faerun, Adventures in Faerun, Wild Beyond the Witchlight and the
books around them (written in the 2024 wording: "a Magic action", "(4d8) Necrotic damage", "a 30-foot Emanation"), in a fight.

The generic readers of wondrous.py, items.py and itempowers.py take most of their text (wondrous._USE_RE knows "Magic action"; items.item_spells
reads "Spell | Charge Cost" tables and "cast these spells" lists). What those can't read is here:

Bar entries (`adjust`, merged by wondrous.activations):
    Tramontane armour       Grasping Tendrils: a Magic action switches them on (once a day, a minute), then each bonus action Strength-saves
                            everyone of your choice within 20 ft (Grappled, pulled up to 20 ft toward you)
    Wand of Teeth           up to 3 charges: that many d8 of piercing, DC 15 Dex (half), Poisoned until the start of your next turn
    Orb of Damara           Dragon's Breath: a 15-ft cone of 6d6 of the type you choose, DC 18 Dex (half)
    Calimemnon Crystal      Damage Rays: DC 18 Dex, 6d6 + 6 radiant (half), up to six creatures, once a day (the healing rays aren't played)
    Pulverizing Staff of Skulls   10d8 necrotic and prone, DC 17 Con (half and not prone), once a day
    Staff of the Spirit Aegis     Aura of Haunted Power: you and your friends within 30 ft resist cold, necrotic and psychic damage (and
                            have advantage against being frightened) for an hour, once a day
    Cap of Vanishing        invisible for 10 minutes (a charge), until you attack, cast or deal damage
    Mythallar Bracelet / Cloak   a bead: advantage on Athletics for a minute / a charge: flying 30 ft and +1d4 radiant on your hits for a minute
    Hat of Vortexes         a charge: a vortex of difficult terrain round you for an hour
    Mage's Manacle          DC 15 Dex or Restrained, against a Grappled or Incapacitated creature within 5 ft, once a day
    Orb of Sorcery, Spell-Refueling Ring, Honed Mind rods   a spent spell slot or two Sorcery Points back
    Arcane Battery          1d4 + 1 charges back on another item (it then loses its magic)
    Lost Crown of Besilmer  a bonus action and a charge: one creature within 60 ft adds a d6 to one roll before the end of your next turn
    Soul Coin               Drain Life: an action and a charge, 1d10 temporary hit points; the last charge frees the soul (the coin is gone)
Battering Shield: its holder's push from within reach spends a charge for 10 ft more and prone (_battering_push, from movement._push).
Reactions (ITEM_FAMILIES, asked through reactions.py like any other):
    Dazzling weapons        after you are hit by an attack roll, a charge: DC 15 Con or the attacker is Blinded until the end of its next turn
    Repulsion Shield        a Large or smaller creature hits you in melee: a charge, it is pushed 15 ft away
    Chattering / Pulverizing Staff of Skulls   a creature within 30 ft makes an attack roll: disadvantage on it
    Crystal Ball of Ominous Portent   an enemy within 60 ft succeeds on an attack roll or a save: it counts as a 1, once a day
    Mind Sharpener, Ring of Dedicated Focus, Scholar's Anchoring Bangle   a failed concentration save (_conc_rescue)
After a hit: Mage Breaker (_conc_disadvantage: disadvantage on the target's concentration save), Blood Amulet (a charge: +2d10 necrotic,
    DC 15 Con or a level of exhaustion; wondrous.charge_hit), Namer's Needle's Named Target (itemextras.hit_choices: a hit becomes a critical
    hit, once a day), the Dispelling and Goading ammunition (itemextras._special_ammo_hit, _dispel_low), a Many Keyholes Dagger's reroll of
    a miss (once a day, a family above).
Passive: spells' damage dice that come up 1 count as 2 (Spell-Fueling armour, Robe of Thayan Arcana): added as a number rolled for the 1s
    (`_wonder_strike_start`); +N to one skill (Eyes of Deceit, Ring of Candor: item_fixes `bonus_skill`).
"""
import re
from functools import lru_cache
from typing import List, Optional

from ...rules.dice import roll_dice
from ..common import ServiceError
from . import geometry as G

ITEM_FAMILIES = {"item_dazzle": "Dazzling weapon", "item_repulse": "Repulsion Shield", "item_chatter": "Chattering skulls",
                 "item_portent": "Ominous Portent", "item_reroll": "Keyhole reroll", "item_repel": "Repel", "item_elements": "Brooch of the Elements",
                 "item_foot": "Lucky Foot", "item_batter": "Battering Shield"}
REACTING = {"item_dazzle": r"^Dazzling ", "item_repulse": r"^Repulsion Shield$", "item_chatter": r"^(?:Chattering|Pulverizing) Staff of Skulls$",
            "item_portent": r"^Crystal Ball of Ominous Portent$", "item_reroll": r"^Many Keyholes Dagger$", "item_repel": r"^Dissuader$",
            "item_elements": r"^Brooch of the Elements$", "item_foot": r"^Lucky Foot$", "item_batter": r"^Battering Shield$"}
DAILY = {"item_portent", "item_reroll", "item_repel"}   # once until the next dawn (the sheet's resources)
FREE = {"item_reroll", "item_foot", "item_batter"}       # no reaction spent (a Battering Shield's push: _battering_push, no question asked)
ELEMENTS = ["acid", "cold", "fire", "lightning", "poison", "thunder"]

# creatures the items bring (wondrous.SUMMONS: {name pattern: (monster ids, count, limit)}); a Mechanical Wonder's minute of winding isn't played
SUMMONS = [(r"^Fork of Eddy Summoning$", (["Eldritch Eddy|NF"], 1, "daily")), (r"^Magen Handbell$", (["Terran Magen|NF"], 1, "daily")),
           (r"^Pipes of Pestilence$", (["Swarm of Corrupted Rats|WttHC"], 1, "daily")),
           (r"^Mechanical Wonder \(Domestic\)$", (["Domestic Wonder|FRAiF"], 1, "daily")), (r"^Mechanical Wonder \(Flying\)$", (["Flying Wonder|FRAiF"], 1, "daily"))]

DAMAGE_TYPES = ["acid", "cold", "fire", "lightning", "poison"]
ONES_AS_TWOS = re.compile(r"treat any 1 on a damage die as a 2")


def _area(shape, size, **kw):
    return dict({"shape": shape, "size": size, "origin": "caster"}, **kw)


def adjust(item: dict, acts: List[dict]) -> List[dict]:
    """The item's bar entries after the generic reader's: some replaced, some added (see the module's text)."""
    name = item.get("name") or ""
    if name.startswith("Tramontane "):
        cone = _area("emanation", 20, choice=True)
        return [{"key": "tendrils", "name": "Grasping Tendrils", "kind": "buff", "cost": "action", "limit": "daily", "worn": True, "toggle": True,
                 "mods": {"tendrils": True}, "rounds": 10, "target": {"type": "self"},
                 "tip": "The sleeves and hem turn to ribbonlike tendrils for 1 minute (once a day). Then a bonus action each turn pulls in your foes."},
                {"key": "pull", "name": "Tendrils: pull", "kind": "save", "cost": "bonus", "limit": None, "worn": True, "needs_on": True, "range": None,
                 "sv": {"ab": "str", "dc": 15, "half": False, "conds": ["Grappled"], "pull": 20, "fail5": [], "repeat": None, "rounds": None,
                        "until": None, "mods": None, "then": None, "ends_on_by": False, "drop_to_0": False},
                 "parts": [], "area": cone, "self_too": False, "target": {"type": "self_area", "aim": False, "area": cone},
                 "tip": "Each creature of your choice within 20 ft: DC 15 Strength save or Grappled and pulled up to 20 ft toward you."}]
    if name == "Wand of Teeth":
        cone = _area("cone", 30)
        return [{"key": "teeth", "name": "Spray of teeth", "kind": "save", "cost": "action", "limit": ("charges", 1, 3), "dice_per_charge": "d8",
                 "sv": {"ab": "dex", "dc": 15, "half": True, "conds": ["Poisoned"], "until": "caster_start", "fail5": [], "repeat": None,
                        "rounds": None, "mods": None, "then": None, "ends_on_by": False, "drop_to_0": False},
                 "parts": [["1d8", "piercing"]], "area": cone, "self_too": False, "range": None,
                 "target": {"type": "self_area", "aim": True, "area": cone},
                 "tip": "Up to 3 charges: that many d8 of piercing damage in a 30-ft cone (DC 15 Dex halves); on a failure also poisoned until your next turn."}]
    out = list(acts)
    if name == "Orb of Damara":
        cone = _area("cone", 15)
        out.append({"key": "breath", "name": "Dragon's Breath", "kind": "save", "cost": "action", "limit": None, "range": None,
                    "sv": {"ab": "dex", "dc": 18, "half": True, "conds": [], "fail5": [], "repeat": None, "rounds": None, "until": None, "mods": None,
                           "then": None, "ends_on_by": False, "drop_to_0": False},
                    "parts": [["6d6", "fire"]], "area": cone, "self_too": False, "type_option": True,
                    "options": [{"value": t, "label": t.title()} for t in DAMAGE_TYPES], "target": {"type": "self_area", "aim": True, "area": cone},
                    "tip": "A 15-ft cone of acid, cold, fire, lightning or poison: DC 18 Dex save, 6d6 damage (half on a success)."})
    if name == "Calimemnon Crystal":
        out.append({"key": "rays", "name": "Damage rays", "kind": "save", "cost": "action", "limit": "daily", "range": 60,
                    "sv": {"ab": "dex", "dc": 18, "half": True, "conds": [], "fail5": [], "repeat": None, "rounds": None, "until": None, "mods": None,
                           "then": None, "ends_on_by": False, "drop_to_0": False},
                    "parts": [["6d6+6", "radiant"]], "area": None, "self_too": False, "target": {"type": "creature", "count": 6, "enemies": True},
                    "tip": "Six rays of volatile energy at creatures within 60 ft (one each): DC 18 Dex, 6d6 + 6 radiant (half on a success). Once a day."})
    if name == "Pulverizing Staff of Skulls":
        out.append({"key": "pulverize", "name": "Pulverizing", "kind": "save", "cost": "action", "limit": "daily", "range": 60,
                    "sv": {"ab": "con", "dc": 17, "half": True, "conds": [], "prone": True, "fail5": [], "repeat": None, "rounds": None, "until": None,
                           "mods": None, "then": None, "ends_on_by": False, "drop_to_0": False},
                    "parts": [["10d8", "necrotic"]], "area": None, "self_too": False, "target": {"type": "creature", "count": 1, "enemies": True},
                    "tip": "Point the staff at a Humanoid you can see: DC 17 Con save, 10d8 necrotic and prone (half and not prone on a success). Once a day."})
    if name == "Staff of the Spirit Aegis":
        out.append({"key": "aura", "name": "Aura of Haunted Power", "kind": "buff", "cost": "action", "limit": "daily", "who": "area", "size": 30,
                    "allies": True, "rounds": 600, "mods": {"resist": ["cold", "necrotic", "psychic"], "cond_save_adv": ["Frightened"]},
                    "target": {"type": "self"},
                    "tip": "You and your friends within 30 ft: resistance to cold, necrotic and psychic damage and advantage on saves against being "
                           "frightened, for an hour. Once a day."})
    if name == "Cap of Vanishing":
        out.append({"key": "vanish", "name": "Vanish", "kind": "buff", "cost": "action", "limit": ("charges", 1), "conds": ["Invisible"],
                    "ends_on": ["attack", "cast", "damage"], "rounds": 100, "worn": True, "toggle": True, "target": {"type": "self"},
                    "tip": "Invisible for 10 minutes (1 charge): it ends if you make an attack roll, deal damage or cast a spell."})
    if name == "Mythallar Bracelet":
        out.append({"key": "bead", "name": "Pluck a bead", "kind": "buff", "cost": "action", "limit": ("charges", 1), "mods": {"skill_adv": ["Athletics"]},
                    "rounds": 10, "target": {"type": "self"}, "tip": "Advantage on Strength (Athletics) checks for 1 minute (one of three beads)."})
    if name == "Mythallar Cloak":
        out.append({"key": "fly", "name": "Activate the cloak", "kind": "buff", "cost": "bonus", "limit": ("charges", 1), "worn": True,
                    "mods": {"fly": 30, "dmg": ("1d4", "radiant")}, "rounds": 10, "toggle": True, "target": {"type": "self"},
                    "tip": "For 1 minute: a flying speed of 30 ft (hover) and +1d4 radiant on your hits (1 charge)."})
    if name == "Lost Crown of Besilmer":
        out.append({"key": "inspire", "name": "Inspire", "kind": "buff", "cost": "bonus", "limit": ("charges", 1), "who": "ally", "range": 60,
                    "worn": True, "until": "end", "mods": {"attack": "1d6", "save": "1d6", "check": "1d6", "once": True},
                    "tip": "One creature within 60 ft that can see or hear you: once before the end of your next turn it adds a d6 to one "
                           "attack roll, ability check or saving throw (1 charge)."})
    if name == "Soul Coin":
        out.append({"key": "drain", "name": "Drain Life", "kind": "heal", "temp": True, "dice": "1d10", "cost": "action", "limit": ("charges", 1),
                    "range": 0, "target": {"type": "self"}, "unit": "charge", "last_frees": True,
                    "tip": "Siphon the bound soul's essence: 1d10 temporary hit points (1 charge). The last charge frees the soul and the coin rusts away."})
    if name == "Hat of Vortexes":
        out.append({"key": "vortex", "name": "Release a vortex", "kind": "more_zone", "cost": "action", "limit": ("charges", 1), "size": 10,
                    "zone": {"difficult": True, "parts": []}, "target": {"type": "self"},
                    "tip": "A vortex round you for an hour: its area is difficult terrain (1 charge)."})
    if name == "Spiked Shield":
        out.append({"key": "bash", "name": "Shield Bash", "kind": "attack", "cost": "attack", "ability": "str", "bonus": None, "melee": True,
                    "parts": [["2d6+STR", "piercing"]], "spell": False, "weapon": True, "range": 5, "limit": None, "worn": True,
                    "target": {"type": "creature", "count": 1, "enemies": True},
                    "tip": "One of the attacks of your Attack action, with the shield: proficiency bonus + Strength to hit, 2d6 + Strength piercing."})
    if name == "Spirit-Binding Censer":
        out.append({"key": "incense", "name": "Protective Incense", "kind": "buff", "cost": "action", "limit": "daily", "who": "area", "size": 30,
                    "allies": True, "rounds": 600, "mods": {"warded_from": ["aberration", "celestial", "elemental", "fey", "fiend", "undead"]},
                    "target": {"type": "self"},
                    "tip": "Smoke fills 30 ft round you for an hour: you and your friends in it have the benefits of Protection from Evil and Good "
                           "(aberrations, celestials, elementals, fey, fiends and undead attack at disadvantage). Once a day."})
    if name == "Mage's Manacle":
        out.append({"key": "bind", "name": "Spectral manacle", "kind": "save", "cost": "action", "limit": "daily", "range": 5, "worn": True,
                    "target_cond": ["Grappled", "Incapacitated"],
                    "sv": {"ab": "dex", "dc": 15, "half": False, "conds": ["Restrained"], "rounds": 4800, "fail5": [], "repeat": None, "until": None,
                           "mods": None, "then": None, "ends_on_by": False, "drop_to_0": False},
                    "parts": [], "area": None, "self_too": False, "target": {"type": "creature", "count": 1, "enemies": True},
                    "tip": "A Large or smaller Grappled or Incapacitated creature within 5 ft: DC 15 Dex save or Restrained, bound to you for 8 hours. Once a day."})
    if name == "Orb of Sorcery":
        out.append({"key": "reservoir", "name": "Sorcerous Reservoir", "kind": "regain", "cost": "action", "limit": "daily", "regain": ("Sorcery Points", 2),
                    "target": {"type": "self"}, "tip": "Regain up to 2 expended Sorcery Points. Once a day."})
    if name == "Spell-Refueling Ring":
        out.append({"key": "refuel", "name": "Recover a spell slot", "kind": "regain", "cost": "bonus", "limit": "daily", "regain": "slot3", "worn": True,
                    "target": {"type": "self"}, "tip": "Recover one expended spell slot of 3rd level or lower. Once a day."})
    if re.search(r"Rod of the Honed Mind$", name):
        out.append({"key": "slot", "name": "Regain a spell slot", "kind": "regain", "cost": "action", "limit": "daily", "regain": "pact",
                    "target": {"type": "self"}, "tip": "Regain one expended Warlock spell slot (once until a long rest)."})
    if name == "Arcane Battery":
        out.append({"key": "charge", "name": "Touch it to an item", "kind": "battery", "cost": "action", "limit": "consume", "target": {"type": "self"},
                    "tip": "Touch it to a magic item that recharges daily: it regains 1d4 + 1 charges (the battery then loses its magic)."})
    return out


@lru_cache(maxsize=None)
def _spell_names(item_name: str) -> frozenset:
    """The names (lower case) of the spells an item casts."""
    from .items import ItemsMixin
    return frozenset(o["spell"]["name"].lower() for o in ItemsMixin._item_spell_list(item_name))


class ItemMoreMixin:
    # ------------------------------------------------------------------ worn: dice that come up 1
    def _ones_as_twos(self, R: dict, att: dict):
        """Spell-Fueling armour, a Robe of Thayan Arcana: a 1 on a spell's damage die counts as a 2. The dice aren't kept apart once rolled,
        so the 1s that would have come up are drawn first (n dice of d sides: each a 1 in d) and added as a number."""
        char = self._sheet(att) if att and not att.get("form") else None
        if not char or not R.get("spell") or R.get("ones_done") or not any(ONES_AS_TWOS.search(d.get("text") or "") for _e, d in char._active_items()):
            return
        R["ones_done"] = True
        plus = {}
        for d, t in (R.get("atk") or {}).get("parts") or R.get("parts") or []:
            m = re.fullmatch(r"\s*(\d+)d(\d+)\s*(?:[+-]\s*\d+)?", str(d))
            if m and int(m.group(2)) > 1:
                n = sum(1 for _ in range(int(m.group(1))) if self.rng.randint(1, int(m.group(2))) == 1)
                if n:
                    plus[t] = plus.get(t, 0) + n
        if plus:
            tgt_parts = (R.get("atk") or {}).get("parts") if (R.get("atk") or {}).get("parts") else R.get("parts")
            for t, n in plus.items():
                tgt_parts.append([str(n), t])
            self._line(R, f"{att['name']}'s armour: {sum(plus.values())} die rolled as a 2 instead of a 1", "1s count as 2")

    # ------------------------------------------------------------------ reactions
    def _more_eligible(self, out: list, window: str, R: dict, att: Optional[dict], tgt: Optional[dict], ctx: dict):
        cur = R.get("cur") or {}
        a = R.get("atk") or {}

        def ask(reactor, fam, label, text, win=None):
            opt = {"reactor": reactor["id"], "cost": FAMILY_COST.get(fam, "reaction"), "options": [{"key": fam, "label": label, "detail": ""}], "text": text}
            if win:
                opt["window"] = win
            out.append(opt)

        if window == "after_damage" and att and tgt and att is not tgt and self._alive(tgt) and R.get("mode") == "attack" and self._may_react(tgt):
            e, d = self._wonder_item(tgt, "item_dazzle")
            if d and self._alive(att):
                ask(tgt, "item_dazzle", f"{d['name']}: dazzle {att['name']} (DC 15 Con or blinded; {self._charges_left(e)} charges)",
                    f"{att['name']} hit {tgt['name']}. Dazzle the attacker with the {d['name']}?", "after_damage")
            e, d = self._wonder_item(tgt, "item_repulse")
            if d and a.get("melee") and att.get("pos") and tgt.get("pos") and self._dist(att, tgt) <= 5 and self._alive(att) \
                    and self._size_of(att) in ("Tiny", "Small", "Medium", "Large"):
                ask(tgt, "item_repulse", f"Repulsion Shield: push {att['name']} 15 ft away ({self._charges_left(e)} charges)",
                    f"{att['name']} hit {tgt['name']} in melee. Push it away with the Repulsion Shield?", "after_damage")
        if window == "declared" and att and tgt and self._hostile(att, tgt) and att.get("pos"):
            for o in self.b["combatants"]:
                if o is att or not o.get("pos") or not self._hostile(o, att) or not self._can_act(o) or not self._may_react(o):
                    continue
                e, d = self._wonder_item(o, "item_chatter")
                if d and self._dist(o, att) <= 30 and self._sees(o, att):
                    ask(o, "item_chatter", f"{d['name']}: {att['name']} attacks with disadvantage", f"{att['name']} attacks {tgt['name']}. "
                        f"Rattle it with the skulls' chatter?")
        if window in ("hit", "save_ok") and tgt and not cur.get("auto"):
            roller = att if window == "hit" else tgt
            if roller and roller.get("pos"):
                for o in self.b["combatants"]:
                    if o is roller or not o.get("pos") or not self._hostile(o, roller) or not self._may_react(o):
                        continue
                    e, d = self._wonder_item(o, "item_portent")
                    if d and self._dist(o, roller) <= 60 and self._sees(o, roller):
                        ask(o, "item_portent", f"{d['name']}: {roller['name']}'s roll becomes a 1 (once a day)",
                            f"{roller['name']} succeeds ({'its attack hits ' + tgt['name'] if window == 'hit' else 'its save'}). Turn the roll into a 1?")
        if window == "enter":                                       # a Dissuader's Repel: a creature comes within 5 ft
            mover = self._find_or_none(ctx.get("mover"))
            for oid in ctx.get("threats") or []:
                o = self._find_or_none(oid)
                if o and mover and self._hostile(o, mover) and self._may_react(o):
                    e, d = self._wonder_item(o, "item_repel")
                    if d:
                        ask(o, "item_repel", "Repel: each foe within 30 ft, DC 15 Str or pushed 30 ft (once a day)",
                            f"{mover['name']} comes within reach of {o['name']}. Repel it?")
        if window == "save_failed" and tgt and not cur.get("auto") and int(cur.get("kept") or 0) == 1 and self._wonder_item(tgt, "item_foot")[1]:
            ask(tgt, "item_foot", "Lucky Foot: reroll the 1 (the foot crumbles)", f"{tgt['name']} rolled a 1 on its save. Use the Lucky Foot?", "save_failed")
        if window == "damage" and att and tgt and R.get("mode") == "attack" and self._hostile(att, tgt) and att.get("pos"):
            have = self._defenses(tgt)
            for o in self.b["combatants"]:
                if o.get("pos") and not self._hostile(o, att) and self._may_react(o) and self._dist(o, att) <= 60 and self._sees(o, att):
                    e, d = self._wonder_item(o, "item_elements")
                    swap = self._element_swap(tgt, cur.get("dmg") or [], have) if d else None
                    if swap:
                        ask(o, f"item_elements:{swap[0]}>{swap[1]}", f"{d['name']}: {swap[0]} damage becomes {swap[1]} ({self._charges_left(e)} charges)",
                            f"{att['name']} hits {tgt['name']} (it resists or shrugs off {swap[0]}). Change the damage type?")
        if window == "missed" and att and tgt and not att.get("form"):
            e, d = self._wonder_item(att, "item_reroll")
            if d and a.get("weapon") and a.get("item") == e["name"]:
                ask(att, "item_reroll", f"{d['name']}: reroll the miss (once a day; the new roll stands)", f"{att['name']} misses {tgt['name']} "
                    f"({cur.get('total')} vs AC {cur.get('ac')}). Reroll with the dagger?")

    def _more_react(self, window: str, R: dict, reactor: dict, fam: str, arg: str, ctx: dict):
        """What the reactions of this module do."""
        fam = fam.split(":")[0]
        e, d = self._wonder_item(reactor, fam)
        char = self._sheet(reactor)
        cur = R.setdefault("cur", {})
        if not d or not char:
            return
        e = char.find_item(e["name"])
        if fam in DAILY:
            char.d["resources"][f"item:{d['name']}:{fam}"] = 1
        elif d.get("charges") and fam in ("item_dazzle", "item_repulse", "item_elements"):
            e["charges_left"] = self._charges_left(e) - 1
        char.save()
        att = self._find_or_none(ctx.get("attacker"))
        tgt = self._find_or_none(ctx.get("target"))
        if fam == "item_dazzle" and att is not None:
            res = self._saving_throw(att, "con", 15, label=d["name"])
            self._line(R, f"{reactor['name']}'s {d['name']} flares: {att['name']} CON save {res['total']} vs DC 15 — " + ("saved" if res["ok"] else "blinded"),
                       d["name"])
            if not res["ok"]:
                self._effect_on(att, f"Blinded ({d['name']})", ["Blinded"], None, None, None, None, reactor["name"], None, None, reactor["id"],
                                until={"end": att["id"], "skip": 0 if self.b.get("turn") != att["id"] else 1})
        elif fam == "item_repulse" and att is not None:
            self._push(att, reactor, 15, R)
            self._line(R, f"{reactor['name']}'s Repulsion Shield pushes {att['name']} away ({e.get('charges_left')} charges left)", d["name"])
        elif fam == "item_chatter" and att is not None and tgt is not None:
            self._effect_on(tgt, f"Chattering skulls ({reactor['name']})", [], None, None, None, 1, reactor["name"],
                            {"attacks_against": "dis", "once": True}, None, reactor["id"])
            self._line(R, f"{reactor['name']}'s skulls chatter: {att['name']}'s attack has disadvantage", d["name"])
        elif fam == "item_portent":
            roller = att if window == "hit" else tgt
            if window == "hit":
                cur.update(total=int(cur.get("ac") or 10) - 1, kept=1, crit=False)
                what = f"{roller['name']}'s attack misses"
            else:
                total = int(cur.get("total") or 0) - int(cur.get("kept") or 0) + 1
                cur.update(total=total, kept=1, ok=total >= int((R.get("sv") or {}).get("dc") or 99))
                what = f"{roller['name']}'s save " + ("still succeeds" if cur["ok"] else "fails")
            self._line(R, f"{reactor['name']} turns the roll into a 1 with the {d['name']}: {what}", d["name"])
        elif fam == "item_repel":
            dc = re.search(r"Repel\..*?DC (\d+) Strength", d.get("text") or "", re.S)
            ids = [x["id"] for x in self.b["combatants"] if x is not reactor and x.get("pos") and reactor.get("pos") and self._hostile(x, reactor)
                   and not self._is_out(x) and self._dist(x, reactor) <= 30]
            if ids:
                self._stack().append(self._strike(reactor, f"{d['name']} (Repel)", ids, mode="save", magical=True, parts=[],
                                                  sv={"ab": "str", "dc": int(dc.group(1)) if dc else 15, "half": False, "push": 30}))
            self._line(R, f"{reactor['name']} unleashes a shock wave with the {d['name']}", d["name"])
        elif fam == "item_elements":
            old, _sep, new = arg.partition(">")
            cur["dmg"] = [[n, new if t == old else t] for n, t in cur.get("dmg") or []]
            self._line(R, f"{reactor['name']}'s {d['name']} turns the {old} damage into {new} ({e.get('charges_left')} charges left)", d["name"])
        elif fam == "item_foot" and tgt is not None:
            again = self.rng.randint(1, 20)
            total = int(cur.get("total") or 0) - int(cur.get("kept") or 0) + again
            cur.update(total=total, kept=again, ok=total >= int((R.get("sv") or {}).get("dc") or 99))
            self._line(R, f"{reactor['name']}'s Lucky Foot rerolls the 1: {again} -> {total} - " + ("success" if cur["ok"] else "still failed")
                       + "; the foot crumbles", d["name"])
            self.chars.remove_item(char.name, e["name"], 1)
        elif fam == "item_reroll":
            again = self.rng.randint(1, 20)
            cur["total"] = int(cur.get("total") or 0) - int(cur.get("kept") or 0) + again
            cur.update(kept=again, crit=again == 20)
            self._line(R, f"{reactor['name']} rerolls with the {d['name']}: {again} → {cur['total']}", d["name"])

    def _element_swap(self, tgt: dict, dmg: list, have: dict) -> Optional[tuple]:
        """A Brooch of the Elements: (type now, type to change it to) when one of the damage types the hit deals is resisted or shrugged off and
        one of acid, cold, fire, lightning, poison or thunder isn't (a vulnerability first), else None."""
        shut = set(have.get("resist") or ()) | set(have.get("immune") or ())
        vuln = set(have.get("vuln") or ())
        for n, t in sorted(dmg, key=lambda x: -x[0]):
            if n and t in shut:
                best = next((x for x in ELEMENTS if x in vuln and x != t), None) or next((x for x in ELEMENTS if x not in shut and x != t), None)
                if best:
                    return t, best
        return None

    def _reaction_item_spell(self, c: dict, low: str) -> Optional[dict]:
        """A reaction spell (Shield, Counterspell) the hero's magic items can cast now (a charge or the day's use left): the charged_items entry."""
        char = self._sheet(c) if not c.get("form") else None
        if not char or not any(low in _spell_names(e.get("name") or "") for e in char.d.get("inventory") or []):
            return None                                       # (the pack is read first: this is asked at every window)
        return next((o for o in self.charged_items(c) if o["spell"]["name"].lower() == low and not o["why"]), None)

    def _item_spell_spend(self, c: dict, o: dict) -> int:
        """The price of an item's spell cast as a reaction (its charges, or the day's use); the spell's level."""
        from ...rules.data import rules
        char = self._sheet(c)
        entry = char.find_item(o["item"])
        data = rules.item(entry["name"]) or {}
        if o.get("daily"):
            char.d["resources"][f"item:{data.get('name')}:{o['spell']['name']}"] = 1
        if o["cost"]:
            entry["charges_left"] = self._charges_left(entry) - o["cost"]
        char.save()
        self._say(f"{c['name']} casts {o['spell']['name']} from {entry['name']}")
        return int(o["level"])

    # ------------------------------------------------------------------ concentration
    def _conc_rescue(self, c: dict, res: dict, dc: int) -> dict:
        """A failed Constitution save to keep concentration, and an item that turns it round: a Mind Sharpener (a reaction and a charge),
        a Scholar's Anchoring Bangle (a reaction, once a day), a Ring of Dedicated Focus (up to two unspent Hit Dice added to the save)."""
        char = self._sheet(c) if not c.get("form") else None
        if not char:
            return res
        for e, d in char._active_items():
            text = d.get("text") or ""
            if "to maintain Concentration" not in text:
                continue
            if "roll up to two of your unexpended Hit Dice" in text:
                dice = [(k, v) for k, v in char.hit_dice().items() if v["used"] < v["total"]]
                rolled, used = 0, []
                for k, v in dice:
                    for _ in range(v["total"] - v["used"]):
                        if len(used) >= 2 or res["total"] + rolled >= dc:
                            break
                        rolled += int(roll_dice(f"1d{v['die']}").total)
                        used.append(k)
                if not used:
                    continue
                for k in used:
                    char.d["hit_dice_used"][k] = int(char.d["hit_dice_used"].get(k) or 0) + 1
                char.save()
                total = res["total"] + rolled
                self._say(f"{c['name']}'s {d['name']}: {len(used)} Hit {'Die' if len(used) == 1 else 'Dice'} added (+{rolled}) → {total}")
                return dict(res, total=total, ok=total >= dc)
            daily = "can't be used again until the next dawn" in text
            if daily and char.d["resources"].get(f"item:{d['name']}:conc"):
                continue
            if d.get("charges") and self._charges_left(e) < 1:
                continue
            if not self._may_react(c):
                continue
            if daily:
                char.d["resources"][f"item:{d['name']}:conc"] = 1
            if d.get("charges"):
                e["charges_left"] = self._charges_left(e) - 1
            char.save()
            self._spend_reaction(c, d["name"])
            self._say(f"{c['name']} uses its {d['name']}: the concentration save succeeds instead")
            return dict(res, ok=True)
        return res

    def _conc_disadvantage(self, by: Optional[dict]) -> Optional[str]:
        """Mage Breaker: a creature hit by this weapon has disadvantage on the saving throw to keep its concentration (the item's name)."""
        if by is None or by.get("form"):
            return None
        stack = self._stack()
        item = ((stack[-1].get("atk") or {}).get("item") if stack else None)
        char = self._sheet(by)
        entry = char.find_item(item) if char and item else None
        from ...rules.data import rules
        data = rules.item(entry["name"]) if entry else None
        if data and re.search(r"Disadvantage on the saving throw it makes to maintain Concentration", data.get("text") or ""):
            return data["name"]
        return None

    def _dispel_low(self, tgt: dict, R: dict, level: int):
        """Dispelling ammunition: every ongoing spell of this level or lower on the target ends."""
        from ...rules.data import rules
        gone = []
        for eff in list(tgt.get("effects") or []):
            sp = rules.spell(str(eff.get("name") or ""))
            if sp and not eff.get("feature") and not eff.get("trait") and int(sp["level"]) <= level:
                self._effect_off(tgt, eff, "dispelled")
                gone.append(sp["name"])
        if gone:
            self._line(R, f"{tgt['name']}: {', '.join(gone)} dispelled", "dispelled")

    # ------------------------------------------------------------------ the bar's kinds
    def _more_prep(self, c: dict, char, p: dict, n: int, option: Optional[str]) -> dict:
        """What a use needs decided before the generic readers play it: dice for the charges spent (a Wand of Teeth), the damage type chosen
        (an Orb of Damara's breath), how many charges are spent."""
        p = dict(p, spend_n=n)
        if p.get("dice_per_charge"):
            p["parts"] = [[f"{n}{p['dice_per_charge']}", t] for _d, t in p["parts"]]
        if p.get("type_option") and option in DAMAGE_TYPES:
            p["parts"] = [[d, option] for d, _t in p["parts"]]
        return p

    def _more_zone(self, c: dict, char, entry: dict, data: dict, p: dict) -> str:
        """A Hat of Vortexes: a lasting area round the user (difficult terrain)."""
        if not c.get("pos"):
            raise ServiceError("Put the hero on the map first.")
        self._pay(c, p["cost"], data["name"])
        note = self._wonder_spend(c, char, entry, data, p)
        tiles = G.area_for({"shape": "emanation", "size": p["size"], "origin": "caster", "exclude_self": False}, c["pos"], c.get("span") or 1,
                           None, *self._bounds())
        self._add_zone(c, data["name"], tiles, dict(p["zone"]), rounds=600, point=list(G.centre(c["pos"], c.get("span") or 1)))
        line = f"{c['name']} uses the {data['name']}{note}: a vortex of difficult terrain fills {p['size']} ft around"
        self._commit(line)
        return line

    def _battering_push(self, tgt: dict, src: dict, R: Optional[dict] = None):
        """A Battering Shield: its holder pushed a creature from within reach at least 5 ft, so a charge pushes it 10 ft more and knocks
        it prone (movement._push). Off when the hero's own 'item_batter' toggle is set to never (not a reaction: no reaction spent)."""
        e, d = self._wonder_item(src, "item_batter")
        if not d or getattr(self, "_battering", False) or not self._alive(tgt) or (src.get("react") or {}).get("item_batter") == "never":
            return
        char = self._sheet(src)                                 # (each read is a fresh copy: the entry of the one saved)
        e = char.find_item(e["name"])
        e["charges_left"] = self._charges_left(e) - 1
        char.save()
        line = f"{src['name']}'s {d['name']} slams {tgt['name']} ({e['charges_left']} charge{'s' if e['charges_left'] != 1 else ''} left)"
        self._line(R, line, d["name"]) if R is not None else self._say(line)
        self._battering = True
        try:
            self._push(tgt, src, 10, R)
        finally:
            self._battering = False
        self._cond(tgt, "Prone", True)

    def _more_battery(self, c: dict, char, entry: dict, data: dict, p: dict) -> str:
        """An Arcane Battery: 1d4 + 1 charges on the first of the pack's items that recharges daily and has spent some."""
        from ...rules.data import rules
        for e in char.d.get("inventory") or []:
            d = rules.item(e.get("name") or "")
            if not d or d is data or not d.get("charges") or not d.get("recharge"):
                continue
            top = d["charges"] * max(1, int(e.get("qty") or 1)) if isinstance(d["charges"], int) else None    # (a stack: all of their charges)
            left = self._charges_left(e)
            if top is None or left >= top:
                continue
            n = int(roll_dice("1d4+1").total)
            e["charges_left"] = min(top, left + n)
            self._pay(c, p["cost"], data["name"])
            note = self._wonder_spend(c, char, entry, data, p)
            line = f"{c['name']} touches the {data['name']} to {e['name']}{note}: +{e['charges_left'] - left} charges ({e['charges_left']}/{top})"
            self._commit(line)
            return line
        raise ServiceError("No magic item in the pack has spent charges to give back.")


FAMILY_COST = {"item_reroll": "free"}
