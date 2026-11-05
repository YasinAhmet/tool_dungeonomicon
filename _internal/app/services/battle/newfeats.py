"""Feats of Heroes of Faerun, Arcana Unleashed, Eberron: Forge of the Artificer, Astarion's Book of Hungers, Ravenloft: The Horrors
Within and Lorwyn, played in battle (rules/feat_extras.py puts the spells, skills, resistances and speed on the sheet; racefeats.py
hands over to the _nf_ hooks below, the bar's items are added to features.ACTIVE).

    bar          Dodge as a bonus action (Boon of Looming Shadows, Arcane Infiltrator), Timely Retreat, Sun's Healing, Love Bites, Standard
                 Bearer, Encourage Ally, Dragon's Terror, Subdue Animal, Mark of Inspiration, Portal Step, Flee Fools!, Daylight
                 Presence, Spell Subterfuge, Lengthened Strike, Shapechanger
    passives     immunities and senses, Bloodied resistances, Child of the Sun's aura, Stronger Together, Persistent Conjuration
    on a hit     Sanguine Feast, Blazing Strike, Flustering Strike, Power from Pain; Putrefy, Rebuke, Frostbite, Fueled Spellfire and Evocation,
                 Power Surge, Spell Overload, Powerful Radiance (offered where the damage is about to land)
    reactions    Unearthly Scream, Vigilant Guardian, Improved Warding, Mythal Ward, Retaliate, Mist Walk, Delicious Pain, Vitality Ward,
                 Magic Absorption, Siphon Life; on a failed save: Fortune's Favor, Steel Yourself, Magic Resistant, Helpful Premonition,
                 Resilient Anatomy, Sustained Symbiosis
    rolls        a 1 on a D20 Test (the Ravenloft feats' drawbacks), the d4 of the Marks and Arcane Eloquence on checks, Hypervigilance
"""
import re
from typing import List, Optional

from ...rules.data import rules
from ..common import ServiceError
from . import combat_rules as CR
from . import economy as EC
from . import features as F
from . import geometry as G
from . import sight as V
from .resolve import roll

MARKS = ["Detection", "Finding", "Handling", "Healing", "Hospitality", "Making", "Passage", "Scribing", "Sentinel", "Shadow", "Storm", "Warding"]
# the d4 of the Marks (a d6 with the Greater Mark): feat -> skills, tool-ish words in the check's name
MARK_SKILLS = {"Detection": ["Investigation", "Insight"], "Finding": ["Perception", "Survival"], "Handling": ["Nature", "Animal Handling"],
               "Healing": ["Medicine"], "Hospitality": ["Persuasion"], "Making": ["Arcana"], "Passage": ["Athletics", "Acrobatics"],
               "Scribing": ["History"], "Sentinel": ["Insight", "Perception"], "Shadow": ["Stealth", "Performance"], "Storm": ["Acrobatics"],
               "Warding": ["Investigation"]}
OTHER_D4 = {"Arcane Eloquence": ["Deception", "Intimidation", "Persuasion"], "Arcane Undertaker": ["History", "Medicine"]}

NF_FAMILIES = {
    "nf_scream": "Unearthly Scream", "nf_guardian": "Vigilant Guardian", "nf_warding": "Improved Warding", "nf_prescient": "Prescient Intervention",
    "nf_mythal": "Mythal Ward", "nf_retaliate": "Retaliate", "nf_mistwalk": "Mist Walk", "nf_toughened": "Toughened Flesh",
    "nf_vitality": "Vitality Ward", "nf_absorb": "Magic Absorption", "nf_siphon": "Siphon Life", "nf_fortune": "Saving Throw Reroll",
    "nf_steel": "Steel Yourself", "nf_magres": "Magic Resistant", "nf_omens": "Helpful Premonition", "nf_resilient": "Resilient Anatomy",
    "nf_symbiosis": "Sustained Symbiosis", "nf_feast": "Sanguine Feast", "nf_blazing": "Blazing Strike", "nf_flustering": "Flustering Strike",
    "nf_putrefy": "Putrefy", "nf_rebuke": "Rebuke (Radiant Strike)", "nf_frostbite": "Frostbite", "nf_fueled": "Fueled Spellfire", "nf_surge": "Power Surge",
    "nf_overload": "Spell Overload", "nf_radiance": "Powerful Radiance",
}
NF_FREE = {"nf_fortune", "nf_magres", "nf_feast", "nf_blazing", "nf_flustering", "nf_putrefy", "nf_rebuke", "nf_frostbite", "nf_fueled", "nf_surge",
           "nf_overload", "nf_radiance", "nf_absorb"}

# always-on benefits of a feat: feat -> {trait name: mods (modifiers.py)}
STATIC = {
    "Boon of Blazing Dawn": {"Beloved of the Sun": {"immune": ["radiant"]}},
    "Boon of Poison Mastery": {"Antitoxic": {"immune": ["poison"], "immune_cond": ["Poisoned"]}},
    "Boon of Terror": {"Fearless": {"immune_cond": ["Frightened"]}},
    "Aberrant Anatomy": {"Extrasensory Perception": {"senses": {"blindsight": 15}}},
}


def _f(*names):
    return lambda c: any(n in (c.d.get("feats") or []) for n in names)


def _pb(c) -> int:
    return c.proficiency_bonus


def _opt(*pairs):
    return lambda c: [{"value": v, "label": lbl} for v, lbl in pairs]


NF_ACTIVE = {
    "looming_dodge": {"name": "Dancing Silhouette (Dodge)", "cost": "bonus", "resource": None, "target": "self", "needs": _f("Boon of Looming Shadows"),
                      "text": "Take the Dodge action as a bonus action: attacks against you have disadvantage and you have advantage on Dexterity saves until your next turn."},
    "cunning_diversion": {"name": "Cunning Diversion (Dodge)", "cost": "bonus", "resource": None, "per": "long", "uses": _pb, "target": "self",
                          "needs": _f("Arcane Infiltrator"), "text": "Take the Dodge action as a bonus action, proficiency bonus times per long rest."},
    "timely_retreat": {"name": "Timely Retreat", "cost": "bonus", "resource": None, "per": "long", "uses": _pb, "target": "self", "needs": _f("Vampire's Plaything"),
                       "options": _opt(("dash", "Dash"), ("disengage", "Disengage")),
                       "text": "Take the Dash or the Disengage action as a bonus action, proficiency bonus times per long rest."},
    "sun_healing": {"name": "Sun's Healing", "cost": "bonus", "resource": None, "per": "short", "uses": 1, "target": "self", "needs": _f("Light Bringer"),
                    "text": "In sunlight (bright light here): expend a Hit Die, roll it and regain that many hit points. Once per short or long rest."},
    "love_bites": {"name": "Love Bites", "cost": "bonus", "resource": None, "per": "short", "uses": 1, "target": "enemy", "range": 60, "needs": _f("Love Bites"),
                   "text": "Right after you damage a creature with a melee weapon or an unarmed strike: it is charmed until the start of your next turn or until "
                           "it takes damage. Once per short or long rest."},
    "standard_bearer": {"name": "Standard Bearer", "cost": "bonus", "resource": None, "per": "long", "uses": 1, "target": "none", "needs": _f("Lordly Resolve"),
                        "text": "Up to three creatures within 60 ft that see you stand up (a reaction, unless their speed is 0) and for a minute can't be "
                                "charmed or frightened (advantage on new saves against what already grips them). Once per long rest."},
    "encourage_ally": {"name": "Encourage Ally", "cost": "bonus", "resource": None, "per": "long", "uses": _pb, "target": "ally", "range": 30,
                       "needs": _f("Purple Dragon Commandant"), "text": "An ally you see within 30 ft (or you) gains 2d6 + the feat's ability modifier temporary hit points."},
    "dragons_terror": {"name": "Dragon's Terror", "cost": "action", "resource": None, "target": "enemy", "range": 30,
                       "needs": _f("Cult of the Dragon Initiate"),
                       "text": "A creature you see within 30 ft makes a Wisdom save (8 + Wisdom + proficiency) or is frightened until the end of your next turn. "
                               "It is then immune to the effect for 24 hours."},
    "dragons_terror_bonus": {"name": "Fearsome Power (Dragon's Terror)", "cost": "bonus", "resource": None, "target": "enemy", "range": 30,
                             "needs": _f("Dragonscarred"), "text": "After you damage a creature with the Attack or Magic action: Dragon's Terror as a bonus action."},
    "subdue_animal": {"name": "Subdue Animal", "cost": "action", "resource": None, "per": "long", "uses": _pb, "target": "enemy", "range": 30,
                      "needs": _f("Greater Mark of Handling"),
                      "text": "A Beast or Monstrosity you see within 30 ft makes a Wisdom save (8 + Wisdom + proficiency) or is frightened until the start of your next turn."},
    "mark_inspiration": {"name": "Mark of Inspiration", "cost": "free", "resource": None, "per": "long", "uses": _pb, "target": "enemy", "range": 30,
                         "needs": _f("Greater Aberrant Mark"), "options": _opt(("1", "Roll one Hit Die"), ("2", "Roll two Hit Dice")),
                         "text": "After casting a cantrip: roll one or two unexpended Hit Dice. You gain that many + your Constitution modifier temporary hit points "
                                 "and a creature within 30 ft takes force damage equal to the number rolled."},
    "portal_step": {"name": "Portal Step", "cost": "move:15", "resource": None, "per": "long", "uses": _pb, "target": "point", "teleport": 15,
                    "needs": _f("Portal Jumper"), "text": "Spend 15 ft of movement to teleport to an unoccupied space you see within 15 ft. Once a turn."},
    "flee_fools": {"name": "Flee, Fools!", "cost": "reaction", "resource": None, "per": "short", "uses": 1, "target": "enemy", "range": 60,
                   "needs": _f("Boon of Terror"),
                   "text": "A frightened creature that starts its turn within 60 ft makes a Wisdom save (8 + Charisma + proficiency) or spends its turn moving away from you."},
    "daylight_presence": {"name": "Daylight Presence", "cost": "bonus", "resource": None, "target": "self", "needs": _f("Boon of the Bright Sun"),
                          "text": "A 30-ft emanation of sunlight. While it lasts, at the start of each of your turns you and allies you see in it gain 10 temporary hit points."},
    "spell_subterfuge": {"name": "Shrouding Spells", "cost": "bonus", "resource": None, "per": "long", "uses": lambda c: max(1, c.mod("int") if "int" in _ab(c, "Spell Subterfuge") else max(c.mod("wis"), c.mod("cha"))),
                         "target": "self", "needs": _f("Spell Subterfuge"),
                         "text": "After you cast a spell with a casting time of an action using a spell slot: Dash and Hide as one bonus action."},
    "lengthened_strike": {"name": "Lengthened Strike", "cost": "free", "resource": None, "per": "long", "uses": _pb, "target": "self", "needs": _f("Living Shadow"),
                          "text": "Your reach for melee attacks is 10 ft longer until the end of the turn (use it before the attack)."},
    "portal_jump": {"name": "Portal Jump", "cost": "free", "resource": None, "target": "point", "teleport": 10,
                    "needs": lambda c: F.sub_at(c, "Artificer", "Cartographer", 3),
                    "text": "Spend half your speed in movement to teleport to an unoccupied space you see within 10 ft (or within 5 ft of a map holder within 30 ft: "
                            "only the 10 ft here)."},
    "shapechanger": {"name": "Shapechanger", "cost": "action", "resource": None, "per": "long", "uses": 1, "target": "self", "needs": _f("Boon of Fluid Forms"),
                     "options": lambda c: _beasts(),
                     "text": "Shape-shift into a Beast of CR 10 or less for an hour (the form's hit points act as temporary hit points; ends when they are gone). Beasts only here."},
}


def _beasts() -> list:
    from .spells import beast_options
    return beast_options(10)


def _ab(char, feat: str) -> List[str]:
    """The abilities this feat's spells use (its stored pick, else the best of Int, Wis, Cha)."""
    from ...rules import feat_extras as FE
    pick = FE.picks(char, feat).get("spell_ability")
    return [pick] if pick else ["int", "wis", "cha"]


def _dmax(expr) -> int:
    """The highest a dice expression can roll ('2d6+3' -> 15)."""
    expr = str(expr)
    top = sum(int(n or 1) * int(s) for n, s in re.findall(r"(\d*)d(\d+)", expr))
    flat = sum(int(x.replace(" ", "")) for x in re.findall(r"(?<![d\d])[+-]\s*\d+(?![d\d])", expr))
    if re.fullmatch(r"\s*\d+\s*", expr):
        flat = int(expr)
    return top + flat


def _floor3(expr) -> int:
    """Roll a dice expression treating every 1 or 2 as a 3 (Spell Overload)."""
    from .resolve import roll as r
    total = 0
    for n, s in re.findall(r"(\d*)d(\d+)", str(expr)):
        for _ in range(int(n or 1)):
            total += max(3, r(f"1d{s}"))
    total += sum(int(x.replace(" ", "")) for x in re.findall(r"(?<![d\d])[+-]\s*\d+(?![d\d])", str(expr)))
    return total


class NewFeatsMixin:
    # ------------------------------------------------------------------ small helpers
    def _nf_char(self, c: Optional[dict]):
        char = self._sheet(c) if c else None
        return char if char and not c.get("form") else None

    def _nf_has(self, c: Optional[dict], *feats: str) -> bool:
        char = self._peek(c) if c and not c.get("form") else None           # (only its feats read)
        return bool(char) and any(f in (char.d.get("feats") or []) for f in feats)

    def _nf_bloodied(self, c: dict) -> bool:
        return self._hp_of(c) > 0 and self._hp_of(c) * 2 <= self._max_hp(c)

    def _nf_hd(self, c: dict, n: int = 1) -> List[int]:
        """Expend up to n Hit Dice (the biggest first) and roll them."""
        char = self._nf_char(c)
        out: List[int] = []
        if not char:
            return out
        for _ in range(n):
            pools = [(info["die"], cls) for cls, info in char.hit_dice().items() if info["used"] < info["total"]]
            if not pools:
                break
            die, cls = max(pools)
            char.d["hit_dice_used"][cls] = int(char.d["hit_dice_used"].get(cls) or 0) + 1
            out.append(self.rng.randint(1, die))
        char.save()
        return out

    def _nf_inspire(self, c: dict, feet: int, what: str) -> bool:
        """Heroic Inspiration (the sheet's inspiration) for an ally within `feet` that lacks it."""
        for o in self.b["combatants"]:
            oc = self._sheet(o)
            if oc and o is not c and not self._hostile(o, c) and self._alive(o) and not oc.d.get("inspiration") and self._within(c, o, feet):
                oc.d["inspiration"] = True
                oc.save()
                self._say(f"{c['name']}: {what}, {o['name']} gains Heroic Inspiration")
                return True
        return False

    def _nf_hd_left(self, c: dict) -> int:
        char = self._nf_char(c)
        return sum(i["total"] - i["used"] for i in char.hit_dice().values()) if char else 0

    def _nf_bright(self, c: dict) -> bool:
        if not c.get("pos"):
            return True
        ter, base, zones = self._terrain(), self.b.get("map", {}).get("light", "bright"), self._live_zones()
        return any(V.light_at(ter, t, base, zones) == "bright" for t in G.footprint(c["pos"], c.get("span") or 1))

    def _nf_turn(self, c: dict) -> dict:
        return c.setdefault("nf", {})

    def _nf_once(self, c: dict, key: str) -> bool:
        return self._once_per_turn(c, "nf:" + key)

    def _nf_free(self, c: dict, key: str) -> bool:
        return self._cf_turn_free(c, "nf:" + key)

    def _nf_dc(self, char, feat: str) -> int:
        from .racefeats import feat_mod
        return 8 + char.proficiency_bonus + feat_mod(char, feat)

    def _nf_mod(self, char, feat: str) -> int:
        from .racefeats import feat_mod
        return feat_mod(char, feat)

    def _nf_d4(self, char, mark: str = "") -> str:
        return "1d6" if f"Greater Mark of {mark}" in (char.d.get("feats") or []) else "1d4"

    # ------------------------------------------------------------------ passives
    def _nf_passives(self, c: dict, char) -> list:
        """Always-on benefits that depend on the battle: Bloodied resistances, Child of the Sun's aura, Stronger Together, concentration."""
        if c.get("form"):
            return []
        out = []
        feats = set(char.d.get("feats") or [])

        def add(name, **mods):
            out.append({"name": name, "mods": mods, "conditions": [], "feature": True})

        bloodied = self._nf_bloodied(c)
        if "Boon of Desperate Resilience" in feats and bloodied:
            add("Defense of Body and Mind", resist=[t for t in ("acid", "bludgeoning", "cold", "fire", "lightning", "necrotic", "piercing", "poison",
                                                                 "psychic", "radiant", "slashing", "thunder")])
        if "Boon of the Furious Storm" in feats and bloodied:
            add("Eye of the Storm (Bloodied)", immune=["lightning", "thunder"])
        near =[o for o in self.b["combatants"] if o is not c and o.get("pos") and c.get("pos") and self._alive(o) and not self._hostile(o, c)]
        if c.get("pos") and any(self._nf_has(o, "Child of the Sun") and self._dist(o, c) <= 10 and self._can_act(o) for o in near + [c]):
            add("Eyes of Eirdu", cond_save_adv=["Blinded"])
        if "Order's Resilience" in feats and self._can_act(c) and any(self._dist(o, c) <= 5 and self._can_act(o) for o in near):
            add("Stronger Together", save_adv=["str"])
        st = c.get("concentrating")
        if "Conjuration Adept" in feats and st:
            sp = rules.spell(st["spell"])
            if sp and str(sp.get("school") or "").lower().startswith("conj"):
                add("Persistent Conjuration", conc_bonus=max(0, self._nf_mod(char, "Conjuration Adept")))
        return out

    def _nf_conc_safe(self, c: dict) -> bool:
        """Boon of the Iron Mind (damage never breaks it) and Boon of Revelry's Otto's Irresistible Dance."""
        st = c.get("concentrating")
        if not st or not self._nf_char(c):
            return False
        if self._nf_has(c, "Boon of the Iron Mind"):
            return True
        if st["spell"] == "Faerie Fire" and F.sub_at(self._nf_char(c), "Artificer", "Cartographer", 5):
            return True                                      # Guided Precision
        return CR.norm(st["spell"]) == "otto's irresistible dance" and self._nf_has(c, "Boon of Revelry") \
            or bool(c.get("nf_free_conc")) and c["nf_free_conc"] == st["spell"]

    # ------------------------------------------------------------------ modes, reach, turn
    def _nf_modes(self, att: dict, tgt: dict, a: dict) -> list:
        out = []
        char = self._nf_char(att)
        if char:
            feats = set(char.d.get("feats") or [])
            if "Treacherous Allure" in feats and "Charmed" in self._conds(tgt):
                out.append(("adv", "Inevitable Betrayal (charmed target)"))
            if "Purple Dragon Commandant" in feats and self._nf_bloodied(att):
                out.append(("adv", "Last Stand (Bloodied)"))
        for o in self.b["combatants"]:                           # Street Justice: allies attack a creature the holder grapples with advantage
            if o is not att and self._nf_has(o, "Street Justice") and not self._hostile(o, att) and \
                    any((e.get("mods") or {}).get("grappler") == o["id"] for e in tgt.get("effects") or []):
                out.append(("adv", "Headlock (Street Justice)"))
                break
        return out

    def _nf_reach(self, c: dict, char) -> int:
        """Boon of Looming Shadows: reach for melee attacks is 10 ft longer on your own turn (the Attack action)."""
        return 10 if "Boon of Looming Shadows" in (char.d.get("feats") or []) and self.b.get("turn") == c["id"] else 0

    def _nf_leap(self, c: dict) -> bool:
        """Order's Resilience: standing up from prone costs 5 ft of movement."""
        return self._nf_has(c, "Order's Resilience")

    def _nf_bonus_cost(self, c: dict, sp: dict, spec: dict) -> dict:
        """Arcane Safeguard's Resistance and Spellfire Spark's Sacred Flame are a bonus action while their uses last."""
        char = self._nf_char(c)
        if not char:
            return spec
        pair = {"Resistance": ("Arcane Safeguard", "Arcane Safeguard"), "Sacred Flame": ("Spellfire Spark", "Spellfire Flame")}.get(sp.get("name"))
        if pair and pair[0] in (char.d.get("feats") or []) and spec.get("cost") == "action" and self._cf_left(c, pair[1], _pb(char)) > 0:
            return dict(spec, cost="bonus", nf_bonus=pair[1])
        return spec

    def _nf_cast(self, att: dict, sp: dict, level: int):
        """A spell was cast: the uses a bonus-action cast spends, Protective Ward, Life Manipulation, Magical Augmentation, no-concentration casts."""
        char = self._nf_char(att)
        if not char:
            return
        feats = set(char.d.get("feats") or [])
        name, school = sp.get("name"), str(sp.get("school") or "").lower()
        pair = {"Resistance": ("Arcane Safeguard", "Arcane Safeguard"), "Sacred Flame": ("Spellfire Spark", "Spellfire Flame")}.get(name)
        spec_cost = att.pop("nf_cast_bonus", None)
        if pair and spec_cost == pair[1]:
            self._cf_use(att, pair[1])
        free = bool(att.pop("last_cast_free", False))
        if free and att.get("concentrating") and ((name == "Beast Sense" and "Enclave Magic" in feats) or (name == "Faerie Fire" and "Child of the Sun" in feats)
                                                  or (name == "Alter Self" and "Second Skin" in feats)):
            att["nf_free_conc"] = name                      # damage can't break it (Child of the Sun) or no concentration at all
        if level and level >= 1:
            via_slot = not free
            if via_slot and "Abjuration Adept" in feats and school.startswith("abj"):
                who = att
                n = 2 * int(level)
                self._give_temp(who, n)
                self._say(f"{att['name']}: Protective Ward, {n} temporary HP")
            if via_slot and "Necromancy Adept" in feats and school.startswith("necro"):
                rolls = self._nf_hd(att, 2)
                if rolls:
                    n = sum(rolls) + int(level)
                    self._heal(att, n)
                    self._say(f"{att['name']}: Life Manipulation, {n} HP ({' + '.join(map(str, rolls))} + {level})")
            if via_slot and "Transmutation Adept" in feats and school.startswith("trans") and self.b.get("turn") == att["id"]:
                self._effect_on(att, "Magical Augmentation", [], None, None, None, None, att["name"], {"speed": 5 * int(level)}, None, att["id"],
                                until={"end": att["id"]})
                self._say(f"{att['name']}: Magical Augmentation, +{5 * int(level)} ft of speed this turn")
        if "Arcane Artist" in feats and school.startswith("illus") and self._cf_left(att, "Inspiring Magic", 1):
            if self._nf_inspire(att, 30, "Inspiring Magic"):
                self._cf_use(att, "Inspiring Magic")

    def _nf_turn_start(self, c: dict):
        """Fortifying Light: the start of the holder's turn gives temporary hit points to everyone in the sunlight."""
        char = self._nf_char(c)
        if not char or not any(e["name"] == "Daylight Presence" for e in c.get("effects") or []):
            return
        if not self._can_act(c):
            return
        for o in self.b["combatants"]:
            if self._alive(o) and (o is c or (not self._hostile(o, c) and o.get("pos") and c.get("pos") and self._dist(o, c) <= 30 and self._sees(c, o))):
                self._give_temp(o, 10)
        self._say(f"{c['name']}'s Daylight Presence: 10 temporary HP for allies in the light (Fortifying Light)")

    def _nf_turn_end(self, c: dict):
        pass

    def _nf_zero_hp(self, c: dict, dealt: int, types, crit: bool) -> bool:
        """Boon of Misty Escape: dropping to 0 becomes 1 hit point and Gaseous Form."""
        char = self._nf_char(c)
        if not char or "Boon of Misty Escape" not in (char.d.get("feats") or []) or not self._cf_left(c, "Boon of Misty Escape", 1):
            return False
        self._cf_use(c, "Boon of Misty Escape")
        self._set_hp(c, 1)
        self._effect_on(c, "Gaseous Form (Misty Escape)", [], None, None, None, 600, c["name"],
                        {"resist": ["nonmagical"], "save_adv": ["str", "dex", "con"], "no_spells": True, "fly": 20, "regen": "10"}, None, c["id"])
        self._say(f"{c['name']} drops to 1 hit point and turns to mist (Gaseous Form): flies 20 ft, regains 10 HP each turn")
        return True

    def _nf_kill(self, by: Optional[dict], c: dict):
        """An enemy fell: Killer's Fortune (advantage on the next attack, until the end of the next turn) and Siphon Life (a reaction, offered at the kill)."""
        if by is None or c is by or not self._hostile(by, c) or not self._nf_char(by):
            return
        if self._nf_has(by, "Boon of Bloodshed") and by.get("pos") and c.get("pos") and self._sees(by, c):
            self._effect_on(by, "Killer's Fortune", [], None, None, None, None, by["name"], {"attacks_with": "adv", "once": True}, None, by["id"],
                            until={"end": by["id"], "skip": 1 if self.b.get("turn") == by["id"] else 0})
            self._say(f"{by['name']}: Killer's Fortune, advantage on the next attack")
        for o in self.b["combatants"]:                           # Siphon Life: an enemy within 120 ft of the holder is reduced to 0
            if self._nf_has(o, "Boon of the Soul Drinker") and self._hostile(o, c) and o.get("pos") and c.get("pos") and self._dist(o, c) <= 120 \
                    and self._alive(o) and self._cf_left(o, "Siphon Life", 1, "short") and self._may_react(o):
                if self._react_mode(o, "nf_siphon") == "never":
                    continue
                self._cf_use(o, "Siphon Life", "short")
                self._spend_reaction(o, "Siphon Life")
                self._heal(o, 50)
                self._say(f"{o['name']} drinks the soul of {c['name']}: +50 HP (Siphon Life)")

    def _nf_initiative(self, c: dict, total: int, rolls) -> int:
        """Hypervigilance: reroll a 9 or lower on the initiative d20."""
        char = self._nf_char(c)
        if not char or "Survivor" not in (char.d.get("feats") or []):
            return total
        kept = total - int(c.get("init_bonus") or 0)
        if kept <= 9:
            again = self.rng.randint(1, 20)
            self._say(f"{c['name']}: Hypervigilance, initiative d20 {kept} rolled again: {again}")
            return total - kept + again
        return total

    # ------------------------------------------------------------------ rolls
    def _nf_check_bonus(self, c: dict, skill: str) -> int:
        """The d4 (d6) the Marks and Arcane Eloquence add to certain ability checks."""
        char = self._nf_char(c)
        if not char:
            return 0
        feats = set(char.d.get("feats") or [])
        dice = []
        for mark, skills in MARK_SKILLS.items():
            if f"Mark of {mark}" in feats and skill in skills:
                dice.append(self._nf_d4(char, mark))
        for feat, skills in OTHER_D4.items():
            if feat in feats and skill in skills:
                dice.append("1d4")
        return max((roll(d) for d in dice), default=0) if dice else 0

    def _nf_nat1(self, c: dict):
        """A 1 on a D20 Test: the Ravenloft feats' drawbacks (a saving throw against the aberrant influence...)."""
        char = self._nf_char(c)
        if not char or c.get("nf_busy") or not self._alive(c):
            return
        feats = set(char.d.get("feats") or [])
        todo = [f for f in ("Aberrant Anatomy", "Echoing Soul", "Gathered Whispers", "Living Shadow", "Watchers", "Symbiotic Being") if f in feats]
        if not todo:
            return
        c["nf_busy"] = True
        try:
            dc = 13 + char.proficiency_bonus
            for f in todo:
                ab = {"Aberrant Anatomy": "con", "Echoing Soul": "con", "Gathered Whispers": "wis", "Living Shadow": "wis", "Watchers": "wis",
                      "Symbiotic Being": "cha"}[f]
                res = self._saving_throw(c, ab, dc, label=f)
                if res["ok"]:
                    continue
                me = c["id"]
                if f == "Aberrant Anatomy":
                    self._effect_on(c, "Warping Flesh", ["Stunned"], None, None, None, None, c["name"], {}, None, me, until={"end": me, "skip": 1})
                    self._say(f"{c['name']}: Warping Flesh, stunned until the end of its next turn")
                elif f == "Echoing Soul":
                    self._effect_on(c, "Intrusive Echoes", ["Incapacitated"], None, None, None, None, c["name"], {"speed_mult": .5}, None, me,
                                    until={"end": me, "skip": 1})
                    self._say(f"{c['name']}: Intrusive Echoes, incapacitated with half speed until the end of its next turn")
                elif f == "Gathered Whispers":
                    self._effect_on(c, "Voices from Beyond", ["Deafened"], None, None, None, None, c["name"],
                                    {"attacks_with": "dis", "check_dis": True}, None, me, until={"end": me, "skip": 1})
                    self._say(f"{c['name']}: Voices from Beyond, deafened until the end of its next turn (disadvantage on checks and attacks)")
                elif f == "Living Shadow":
                    self._effect_on(c, "Ominous Will", ["Incapacitated"], None, None, None, None, c["name"], {}, None, me, until={"start": me})
                    self._say(f"{c['name']}: Ominous Will, incapacitated until the start of its next turn (then roll the Shadow's Will table)")
                elif f == "Watchers":
                    self._effect_on(c, "Incessant Watchers (paranoia)", [], "wis", dc, "end", 10, c["name"], {"attacks_with": "dis", "save_dis": ["all"]}, None, me)
                    self._say(f"{c['name']}: paranoia, disadvantage on D20 Tests for a minute (a Wisdom save ends it at the end of each turn)")
                else:
                    self._say(f"{c['name']}: Symbiotic Agenda, the symbiote tries to take control (charmed for hours: the DM decides)")
        finally:
            c.pop("nf_busy", None)

    def _nf_save_modes(self, c: dict, source: Optional[dict], spell: bool, label: str, modes: set, why: list):
        """Storm's Strength: disadvantage against the holder's lightning and thunder spells. Incessant Watchers: Scrying."""
        if spell and source is not None and self._nf_has(source, "Boon of the Furious Storm"):
            sp = rules.spell(label or "")
            if sp and re.search(r"lightning|thunder", str(sp.get("damage") or "") + " " + sp.get("text", "")[:900], re.I) and self._hostile(source, c):
                modes.add("dis")
                why.append("Storm's Strength")
        if spell and label == "Scrying" and self._nf_has(c, "Watchers"):
            modes.add("dis")
            why.append("Incessant Watchers")

    def _nf_dsave_dis(self, c: dict) -> bool:
        return self._nf_has(c, "Touch of Death")

    def _nf_temp_bonus(self, c: dict) -> int:
        """Boon of Bountiful Health: 5 more temporary hit points whenever you gain them."""
        return 5 if self._nf_has(c, "Boon of Bountiful Health") else 0

    def _nf_search_mode(self, c: dict) -> Optional[str]:
        """Sharp Eye (advantage on the Search action's check, a number of uses; kept if it fails) and Heightened Suspicion."""
        char = self._nf_char(c)
        if char and "Sharp Eye" in (char.d.get("feats") or []) and self._cf_left(c, "Sharp Eye", _pb(char)) > 0:
            return "adv"
        return None

    def _nf_search_done(self, c: dict, total: int):
        pass

    def _nf_help(self, c: dict, tgt: dict):
        """Harper Teamwork's Withering Wordplay: the enemy distracted also has disadvantage on its first save."""
        if self._nf_has(c, "Harper Teamwork") and self._hostile(c, tgt):
            self._effect_on(tgt, "Withering Wordplay", [], None, None, None, None, c["name"], {"save_dis": ["all"], "once": True}, None, c["id"],
                            until={"start": c["id"]})

    def _nf_ready(self, c: dict):
        """Tyro of the Gauntlet's Vigilant: the Ready action makes the next attack against you have disadvantage."""
        if self._nf_has(c, "Tyro of the Gauntlet"):
            self._effect_on(c, "Vigilant", [], None, None, None, None, c["name"], {"attacks_against": "dis", "once": True}, None, c["id"],
                            until={"start": c["id"]})

    # ------------------------------------------------------------------ extra damage
    def _nf_hit_parts(self, att: dict, tgt: dict, R: dict, char) -> list:
        """Power from Pain: once per turn, while Bloodied, an attack adds the proficiency bonus (the attack's own type)."""
        a = R.get("atk") or {}
        out = []
        if F.sub_at(char, "Artificer", "Cartographer", 5) and a.get("weapon") and any(e["name"] == "Faerie Fire" for e in tgt.get("effects") or []) \
                and self._nf_once(att, "guided"):
            out.append((max(0, char.mod("int")), (a.get("parts") or [["", ""]])[0][1] or "", "Guided Precision"))
        if "Boon of Bloodshed" in (char.d.get("feats") or []) and self._nf_bloodied(att) and a.get("weapon") and self._nf_once(att, "pain"):
            out.append((char.proficiency_bonus, (a.get("parts") or [["", ""]])[0][1] or "", "Power from Pain"))
        return out

    def _nf_pierce(self, by: Optional[dict], spell: bool, label: str) -> set:
        """Damage types whose resistance doesn't count: Searing Spellfire (radiant), Touch of Death's Chill Touch (necrotic)."""
        out = set()
        if by is not None and self._nf_char(by):
            if self._nf_has(by, "Spellfire Adept"):
                out.add("radiant")
            if self._nf_has(by, "Touch of Death") and str(label).startswith("Chill Touch"):
                out.add("necrotic")
        return out

    def _nf_damage(self, R: dict, att: dict, tgt: dict, rolled: list, parts: list) -> list:
        """Perfect Poisoner (the highest poison dice, once a turn); Exploit Opening (an opportunity attack's damage rolled twice)."""
        char = self._nf_char(att)
        if not char:
            return rolled
        feats = set(char.d.get("feats") or [])
        a = R.get("atk") or {}
        if R.get("spell") and rolled and F.sub_at(char, "Artificer", "Cartographer", 5) and self._nf_free(att, "guided"):
            from ...rules import spellcasting as SC            # Guided Precision: a spell from the Cartographer Spells list adds the Intelligence modifier
            if str(R.get("label") or "") in SC.always_prepared(char, "Artificer"):
                self._nf_once(att, "guided")
                rolled[0][0] += max(0, char.mod("int"))
                self._line(R, f"{att['name']}: Guided Precision, +{max(0, char.mod('int'))} damage", "Guided Precision")
        if "Boon of Poison Mastery" in feats and self._nf_free(att, "poison"):
            for i, (d, t) in enumerate(parts):
                if t == "poison" and i < len(rolled) and not isinstance(d, int):
                    self._nf_once(att, "poison")
                    top = _dmax(d)
                    if top > rolled[i][0]:
                        self._line(R, f"{att['name']}: Perfect Poisoner, the highest poison dice ({top} instead of {rolled[i][0]})", "Perfect Poisoner")
                        rolled[i][0] = top
                    break
        if "Zhentarim Ruffian" in feats and a.get("opportunity") and self._nf_once(att, "ruffian"):
            again = self._roll_parts(parts, (R.get("cur") or {}).get("crit"))
            if sum(n for n, _t in again) > sum(n for n, _t in rolled):
                self._line(R, f"{att['name']}: Exploit Opening, damage rolled twice: {sum(n for n, _t in again)} instead of {sum(n for n, _t in rolled)}", "Exploit Opening")
                rolled = again
        return rolled

    # ------------------------------------------------------------------ the bar
    def _nf_why(self, c: dict, char, key: str, f: dict, tgt: Optional[dict], option, menu: bool, point) -> Optional[str]:
        if key not in NF_ACTIVE:
            return None
        t = c.get("turn") or {}
        econ = self._economy_on()
        if key == "timely_retreat" and not menu and option not in ("dash", "disengage"):
            return "Pick Dash or Disengage."
        if key == "sun_healing":
            if not self._nf_hd_left(c):
                return "No Hit Die left"
            if not self._nf_bright(c):
                return "Only in sunlight (bright light)"
        if key == "love_bites":
            if not menu and (not tgt or tgt is c or not self._hostile(c, tgt)):
                return "Pick a foe you just hurt."
            if econ and not menu and tgt["id"] not in (t.get("nf_melee") or []):
                return "Damage it with a melee weapon or an unarmed strike first"
            if econ and menu and not t.get("nf_melee"):
                return "Damage a creature with a melee attack first"
        if key in ("dragons_terror", "dragons_terror_bonus", "subdue_animal", "flee_fools") and not menu and (not tgt or tgt is c or not self._hostile(c, tgt)):
            return "Pick a foe."
        if key in ("dragons_terror", "dragons_terror_bonus") and not menu and (tgt.get("nf_immune") or {}).get(f"terror{c['id']}"):
            return f"{tgt['name']} is immune to Dragon's Terror for 24 hours"
        if key == "dragons_terror_bonus" and econ and not (t.get("attacked") or t.get("spells")):
            return "Damage a creature with the Attack or Magic action first"
        if key == "subdue_animal" and not menu and not re.search(r"beast|monstrosity", self._ctype(self._monster(tgt))):
            return f"{tgt['name']} isn't a Beast or Monstrosity"
        if key == "encourage_ally" and not menu and tgt is not None and self._hostile(c, tgt):
            return f"Pick an ally, not {tgt['name']}."
        if key == "mark_inspiration":
            if econ and not any(int(lv) == 0 for _c, lv in t.get("spells") or []):
                return "Cast a cantrip first"
            if not self._nf_hd_left(c):
                return "No Hit Die left"
            if not menu and (not tgt or tgt is c):
                return "Pick a creature within 30 ft."
        if key == "portal_step":
            if not self._nf_free(c, "portal"):
                return "Once a turn"
            if econ and not menu:
                return EC.why_not(t, "move:15")
        if key == "flee_fools":
            if not menu and (not tgt or "Frightened" not in self._conds(tgt)):
                return "Pick a frightened creature within 60 ft."
            if not menu and not self._sees(c, tgt):
                return f"You can't see {tgt['name']}"
        if key == "daylight_presence" and any(e["name"] == "Daylight Presence" for e in c.get("effects") or []):
            return "Already shining"
        if key == "spell_subterfuge" and econ and not any(cost == "action" and int(lv) >= 1 for cost, lv in t.get("spells") or []):
            return "Cast a spell with a casting time of an action first (using a slot)"
        if key == "lengthened_strike" and any(e["name"] == "Lengthened Strike" for e in c.get("effects") or []):
            return "Already active"
        if key == "shapechanger" and not menu and not option:
            return "Pick a form."
        if key == "shapechanger" and c.get("form"):
            return "Already in another form"
        if key == "portal_jump":
            half = self._speed(c) // 2
            if half <= 0:
                return "Your speed is 0"
            if econ:
                return EC.why_not(t, f"move:{half}")
        return None

    def _nf_feature(self, c: dict, char, key: str, f: dict, tgt: Optional[dict], option, point) -> Optional[str]:
        if key not in NF_ACTIVE:
            return None
        name, t = c["name"], c.get("turn")
        pb = char.proficiency_bonus
        if key in ("looming_dodge", "cunning_diversion"):
            self._effect_on(c, "Dodge", [], None, None, None, None, name, {"attacks_against": "dis", "save_adv": ["dex"]}, None, c["id"], until={"start": c["id"]})
            return self._out(f"{name} dodges ({f['name'].split(' (')[0]})")
        if key == "timely_retreat":
            if option == "dash":
                EC.dash(t)
                return self._out(f"{name} dashes (Timely Retreat)")
            if t is not None:
                t["disengaged"] = True
            return self._out(f"{name} disengages (Timely Retreat)")
        if key == "sun_healing":
            (n,) = self._nf_hd(c, 1) or [0]
            self._heal(c, n)
            return self._out(f"{name} basks in the sun: +{n} HP (Sun's Healing)")
        if key == "love_bites":
            self._effect_on(tgt, "Love Bites", ["Charmed"], None, None, None, None, name, {}, None, c["id"], until={"start": c["id"]}, ends_on=["damage"])
            return self._out(f"{name} charms {tgt['name']} with a bite (until its next turn or until it takes damage)")
        if key == "standard_bearer":
            pool = [o for o in self.b["combatants"] if self._alive(o) and (o is c or not self._hostile(o, c)) and (o.get("pos") and c.get("pos") and self._dist(o, c) <= 60)
                    and (o is c or self._sees(o, c))]
            pool.sort(key=lambda o: -len({"Prone", "Charmed", "Frightened"} & set(self._conds(o))))
            names = []
            for o in pool[:3]:
                if "Prone" in self._conds(o) and self._speed(o) > 0:
                    self._cond(o, "Prone", False)
                    for e in list(o.get("effects") or []):
                        if "Prone" in e["conditions"]:
                            e["conditions"].remove("Prone")
                self._effect_on(o, "Bolstered (Standard Bearer)", [], None, None, None, 10, name, {"immune_cond": ["Charmed", "Frightened"]}, None, c["id"])
                names.append(o["name"])
            return self._out(f"{name} raises the standard: " + (", ".join(names) or "nobody") + " rise bolstered (no charm or fear for a minute)")
        if key == "encourage_ally":
            who = tgt or c
            n = roll("2d6") + self._nf_mod(char, "Purple Dragon Commandant")
            self._give_temp(who, max(1, n))
            return self._out(f"{name} encourages {who['name'] if who is not c else 'itself'}: {max(1, n)} temporary HP")
        if key in ("dragons_terror", "dragons_terror_bonus"):
            feat = "Cult of the Dragon Initiate" if "Cult of the Dragon Initiate" in (char.d.get("feats") or []) else "Dragonscarred"
            dc = 8 + pb + char.mod("wis")
            tgt.setdefault("nf_immune", {})[f"terror{c['id']}"] = True
            res = self._saving_throw(tgt, "wis", dc, label="Dragon's Terror")
            if res["ok"]:
                return self._out(f"{name} snarls at {tgt['name']}, who stands firm ({res['total']} vs DC {dc})")
            self._effect_on(tgt, "Dragon's Terror", ["Frightened"], None, None, None, None, name, {}, None, c["id"], until={"end": c["id"], "skip": 1})
            return self._out(f"{name} instils terror in {tgt['name']}: frightened until the end of {name}'s next turn ({res['total']} vs DC {dc}) ({feat})")
        if key == "subdue_animal":
            dc = 8 + pb + char.mod("wis")
            res = self._saving_throw(tgt, "wis", dc, label="Subdue Animal")
            if res["ok"]:
                return self._out(f"{name} commands {tgt['name']}, who resists ({res['total']} vs DC {dc})")
            self._effect_on(tgt, "Subdue Animal", ["Frightened"], None, None, None, None, name, {}, None, c["id"], until={"start": c["id"]})
            return self._out(f"{name} subdues {tgt['name']}: frightened until the start of its next turn ({res['total']} vs DC {dc})")
        if key == "mark_inspiration":
            rolls = self._nf_hd(c, int(option or 1))
            if not rolls:
                return self._out(f"{name} has no Hit Die to spend")
            n = sum(rolls)
            self._give_temp(c, n + char.mod("con"))
            line = f"{name}'s mark flares: {n + char.mod('con')} temporary HP; " + self._deal(tgt, [[n, "force"]], by=c, label="Mark of Inspiration")
            return self._out(line)
        if key == "portal_step":
            self._nf_once(c, "portal")
            spot = self._cf_teleport(c, point)
            return self._out(f"{name} steps through a portal to {self._tile_label(spot)}")
        if key == "flee_fools":
            dc = 8 + pb + char.mod("cha")
            res = self._saving_throw(tgt, "wis", dc, label="Flee, Fools!")
            if res["ok"]:
                return self._out(f"{tgt['name']} steels itself against {name}'s terror ({res['total']} vs DC {dc})")
            self._effect_on(tgt, "Flee, Fools!", [], None, None, None, None, name, {"commanded": "flee"}, None, c["id"], until={"end": tgt["id"], "skip": 0})
            if self.b.get("turn") == tgt["id"]:
                self._command_turn(tgt)
            return self._out(f"{name} stokes the terror of {tgt['name']}: it spends its turn fleeing ({res['total']} vs DC {dc})")
        if key == "daylight_presence":
            self._effect_on(c, "Daylight Presence", [], None, None, None, None, name, {"toggle": True}, None, c["id"])
            return self._out(f"{name} shines with sunlight (30-ft emanation, 10 temporary HP for allies each turn)")
        if key == "spell_subterfuge":
            EC.dash(t)
            return self._out(f"{name} slips away: " + self._hide_now(c) + " (Shrouding Spells: Dash and Hide)")
        if key == "lengthened_strike":
            self._effect_on(c, "Lengthened Strike", [], None, None, None, None, name, {"giant_reach": 10}, None, c["id"], until={"end": c["id"]})
            return self._out(f"{name}'s shadow stretches: +10 ft of reach this turn")
        if key == "portal_jump":
            if self._economy_on() and t is not None:
                EC.spend(t, f"move:{self._speed(c) // 2}", f["name"])
            spot = self._cf_teleport(c, point)
            return self._out(f"{name} jumps through a portal to {self._tile_label(spot)} (Portal Jump)")
        if key == "shapechanger":
            from ...rules.monsters import bestiary
            beast = bestiary.get(option or "") or bestiary.get("Wolf|MM")
            c["form"] = {"monster": beast["id"], "hp": beast["hp"], "max_hp": beast["hp"], "name": beast["name"]}
            kind = beast["name"].lower()
            return self._out(f"{name} shape-shifts into {'an' if kind[:1] in 'aeiou' else 'a'} {kind} ({beast['hp']} temporary HP)")
        return None

    # ------------------------------------------------------------------ reactions and on-hit choices
    def _nf_families(self, char) -> List[str]:
        feats = set(char.d.get("feats") or [])
        out = []
        pairs = {"nf_scream": "Gathered Whispers", "nf_guardian": "Mark of Sentinel", "nf_warding": "Greater Mark of Warding", "nf_prescient": "Divination Adept",
                 "nf_mythal": "Mythal Touched", "nf_retaliate": "Zhentarim Tactics", "nf_mistwalk": "Mist Walker", "nf_toughened": "Delicious Pain",
                 "nf_vitality": "Vampire Hunter", "nf_absorb": "Spellfire Spark", "nf_siphon": "Boon of the Soul Drinker", "nf_fortune": "Boon of Fortune's Favor",
                 "nf_steel": "Survivor", "nf_magres": "Spell Resistant", "nf_omens": "Arcane Omens", "nf_resilient": "Transmuted Anatomy",
                 "nf_symbiosis": "Symbiotic Being", "nf_feast": "Bloodlust", "nf_blazing": "Boon of Blazing Dawn", "nf_flustering": "Fairy Trickster",
                 "nf_putrefy": "Putrefy", "nf_rebuke": "Rebuke", "nf_frostbite": "Cold Caster", "nf_surge": "Arcane Overload", "nf_overload": "Boon of Erupting Spellpower",
                 "nf_radiance": "Boon of Exquisite Radiance"}
        out += [k for k, feat in pairs.items() if feat in feats]
        if "Spellfire Adept" in feats or "Evocation Adept" in feats:
            out.append("nf_fueled")
        return out

    def _nf_left(self, c: dict, name: str, n, rest: str = "long") -> int:
        return self._cf_left(c, name, n, rest)

    def _nf_offer(self, out: list, o: dict, cost: str, key: str, label: str, text: str, window: Optional[str] = None):
        """One option for the reactor. A reactor gets one question per window (answering it drops its others), so a reaction joins the
        question it already has - Indomitable's, Lucky's - rather than standing apart (the caller checked the reaction is there)."""
        opt = {"key": key, "label": label, "detail": ""}
        if cost == "reaction":
            for item in out:
                if item["reactor"] == o["id"] and item.get("window") == window:
                    item["options"].append(opt)
                    return
        self._cf_offer(out, o, cost, [opt], text, window)

    def _nf_eligible(self, out: list, window: str, R: dict, att: Optional[dict], tgt: Optional[dict], ctx: dict):
        cur = R.get("cur") or {}
        a = R.get("atk") or {}
        if window == "on_hit" and att and tgt:
            self._nf_on_hit(out, R, att, tgt, cur, a)
        elif window == "damage" and tgt:
            self._nf_on_damage(out, R, att, tgt, cur, a)
        elif window == "hit" and att and tgt:
            self._nf_on_hit_against(out, R, att, tgt, cur, a)
        elif window == "declared" and att and tgt and self._hostile(att, tgt):
            for o in self.b["combatants"]:
                oc = self._nf_char(o)
                if not oc or o is att or not o.get("pos") or not att.get("pos") or not self._may_react(o) or not self._sees(o, att):
                    continue
                feats = set(oc.d.get("feats") or [])
                if "Greater Mark of Warding" in feats and self._cf_left(o, "Improved Warding", _pb(oc)) and (o is tgt or self._dist(o, tgt) <= 30) \
                        and self._hostile(o, att):
                    self._nf_offer(out, o, "reaction", "nf_warding", f"Improved Warding (disadvantage on the attack against {tgt['name']})",
                                   f"{att['name']} attacks {tgt['name']}. Impose disadvantage?")
                if "Divination Adept" in feats and self._cf_left(o, "Prescient Intervention", 1) and self._dist(o, att) <= 60 and self._hostile(o, att):
                    self._nf_offer(out, o, "reaction", "nf_prescient", f"Prescient Intervention (disadvantage on {att['name']}'s roll)",
                                   f"{att['name']} is about to attack. Prescient Intervention?")
        elif window == "save_failed" and tgt:
            self._nf_on_save(out, R, att, tgt, cur)
        elif window == "after_damage" and att and tgt and tgt is not att:
            self._nf_after_damage(out, R, att, tgt, cur, a)

    def _nf_on_hit(self, out: list, R: dict, att: dict, tgt: dict, cur: dict, a: dict):
        char = self._nf_char(att)
        if not char:
            return
        feats = set(char.d.get("feats") or [])
        pb = char.proficiency_bonus
        t = att.get("turn")
        if a.get("melee") and t is not None and (a.get("weapon") or "unarmed" in (a.get("props") or [])):
            t.setdefault("nf_melee", []).append(tgt["id"])          # Love Bites: whom the holder just hurt in melee
        if cur.get("crit") and "Lords' Alliance Agent" in feats and self._nf_once(att, "inspiring_strike"):
            self._nf_inspire(att, 30, "Inspiring Strike")
        opts = []
        if "Bloodlust" in feats and a.get("weapon") is not None and self._nf_free(att, "feast") and self._nf_bloodied(tgt) \
                and not re.search(r"construct|undead", self._ctype(self._monster(tgt))) and self._cf_left(att, "Sanguine Feast", pb) and self._nf_hd_left(att):
            opts.append({"key": "nf_feast", "label": "Sanguine Feast (expend a Hit Die: heal d + Constitution)", "detail": ""})
        if "Boon of Blazing Dawn" in feats and a.get("weapon"):
            opts.append({"key": "nf_blazing", "label": "Blazing Strike (the damage is radiant)", "detail": ""})
        if "Fairy Trickster" in feats and self._cf_left(att, "Flustering Strike", pb):
            opts.append({"key": "nf_flustering", "label": "Flustering Strike (Wis save or disadvantage on saves)", "detail": ""})
        if opts:
            self._cf_offer(out, att, "free", opts, f"{att['name']} hits {tgt['name']}" + (" (critical!)" if cur.get("crit") else "") + ". Add something?")

    def _nf_on_damage(self, out: list, R: dict, att: Optional[dict], tgt: dict, cur: dict, a: dict):
        types = {t for _n, t in cur.get("dmg") or [] if _n > 0}
        total = sum(n for n, _t in cur.get("dmg") or [])
        if total <= 0:
            return
        if att is not None and self._nf_char(att):
            char = self._nf_char(att)
            feats = set(char.d.get("feats") or [])
            pb = char.proficiency_bonus
            opts = []
            if "Putrefy" in feats and "necrotic" in types and self._cf_left(att, "Putrefy", 1, "short"):
                opts.append({"key": "nf_putrefy", "label": "Putrefy (the target is poisoned until your next turn)", "detail": ""})
            if "Rebuke" in feats and "radiant" in types and self._cf_left(att, "Radiant Strike", 1, "short") and self._size_ok(tgt):
                opts.append({"key": "nf_rebuke", "label": "Radiant Strike (the target falls prone)", "detail": ""})
            if "Cold Caster" in feats and "cold" in types and R.get("mode") == "attack" and self._nf_free(att, "frostbite"):
                opts.append({"key": "nf_frostbite", "label": "Frostbite (-1d4 on its next save)", "detail": ""})
            if R.get("spell"):
                school = str((rules.spell(re.sub(r" \(.*\)$", "", R.get("label") or "")) or {}).get("school") or "").lower()
                if ("Spellfire Adept" in feats and "radiant" in types or "Evocation Adept" in feats and school.startswith("evoc")) \
                        and self._nf_free(att, "fueled") and self._nf_hd_left(att):
                    opts.append({"key": "nf_fueled", "label": "Fueled Spell (expend up to 2 Hit Dice, add them to a damage roll)", "detail": ""})
                if "Arcane Overload" in feats and school.startswith("evoc") and self._cf_left(att, "Power Surge", 1):
                    opts.append({"key": "nf_surge", "label": f"Power Surge (+{pb} damage)", "detail": ""})
                if "Boon of Erupting Spellpower" in feats and self._cf_left(att, "Spell Overload", 1) and (R.get("slot_level") or 0) >= 1:
                    opts.append({"key": "nf_overload", "label": "Spell Overload (1s and 2s count as 3; the targets fall prone)", "detail": ""})
            if "Boon of Exquisite Radiance" in feats and "radiant" in types and self._cf_left(att, "Powerful Radiance", 1):
                opts.append({"key": "nf_radiance", "label": "Powerful Radiance (the highest radiant dice)", "detail": ""})
            if opts:
                self._cf_offer(out, att, "free", opts, f"{att['name']} is about to deal {total} damage to {tgt['name']}. Add something?", "damage")
        tc = self._nf_char(tgt)
        if tc and self._may_react(tgt):
            feats = set(tc.d.get("feats") or [])
            pb = tc.proficiency_bonus
            if "Spellfire Spark" in feats and (R.get("spell") or R.get("magical")) and self._cf_turn_free(tgt, "nf:absorb"):
                self._nf_offer(out, tgt, "free", "nf_absorb", "Magic Absorption (-1d4 damage)", f"{tgt['name']} is about to take {total} damage from magic. Absorb some?", "damage")
            if "Vampire Hunter" in feats and "necrotic" in types and self._cf_left(tgt, "Vitality Ward", 1, "short"):
                self._nf_offer(out, tgt, "reaction", "nf_vitality", f"Vitality Ward (-{pb}d6 necrotic damage)", f"{tgt['name']} is about to take necrotic damage. React?", "damage")

    @staticmethod
    def _size_ok(tgt) -> bool:
        return True

    def _nf_on_hit_against(self, out: list, R: dict, att: dict, tgt: dict, cur: dict, a: dict):
        need = int(cur.get("total") or 0) - int(cur.get("ac") or 0) - int(cur.get("ac_extra") or 0)
        tc = self._nf_char(tgt)
        if tc and self._may_react(tgt):
            feats = set(tc.d.get("feats") or [])
            pb = tc.proficiency_bonus
            if "Gathered Whispers" in feats and self._cf_left(tgt, "Unearthly Scream", pb) and need < pb:
                self._nf_offer(out, tgt, "reaction", "nf_scream", f"Unearthly Scream (+{pb} AC)", f"{att['name']} hits {tgt['name']}. React?")
            if "Mythal Touched" in feats and R.get("spell") and a.get("spell") and self._cf_left(tgt, "Mythal Ward", pb):
                self._nf_offer(out, tgt, "reaction", "nf_mythal", "Mythal Ward (roll on the Mythal-Touched Magic table)", f"{att['name']}'s spell attack hits {tgt['name']}. Mythal Ward?")
        for o in self.b["combatants"]:                           # Vigilant Guardian: swap places with a creature that is about to be hit
            oc = self._nf_char(o)
            if not oc or o is tgt or o is att or not o.get("pos") or not tgt.get("pos") or not self._may_react(o):
                continue
            if "Mark of Sentinel" in (oc.d.get("feats") or []) and not self._hostile(o, tgt) and self._dist(o, tgt) <= 5 and self._sees(o, tgt) \
                    and self._cf_left(o, "Vigilant Guardian", _pb(oc)):
                self._nf_offer(out, o, "reaction", "nf_guardian", f"Vigilant Guardian (swap with {tgt['name']} and take the hit)",
                               f"{att['name']} hits {tgt['name']}. Take the hit instead?")

    def _nf_on_save(self, out: list, R: dict, att: Optional[dict], tgt: dict, cur: dict):
        sv = R.get("sv") or {}
        dc = int(sv.get("dc") or 0)
        short = dc - int(cur.get("total") or 0)
        if short <= 0 or cur.get("auto"):
            return
        spell = bool(R.get("spell"))
        conds = set(sv.get("conds") or [])
        for o in self.b["combatants"]:
            oc = self._nf_char(o)
            if not oc or not self._alive(o):
                continue
            feats = set(oc.d.get("feats") or [])
            pb = oc.proficiency_bonus
            me = o is tgt
            near = me or (o.get("pos") and tgt.get("pos") and self._dist(o, tgt) <= 30 and self._sees(o, tgt))
            if me and "Boon of Fortune's Favor" in feats and self._nf_free(o, "fortune"):
                self._nf_offer(out, o, "free", "nf_fortune", "Saving Throw Reroll (the new roll stands)", f"{tgt['name']} failed its save. Reroll it?")
            if me and "Spell Resistant" in feats and spell and short <= 6 and self._cf_left(o, "Magic Resistant", pb):
                self._nf_offer(out, o, "free", "nf_magres", "Magic Resistant (+1d6)", f"{tgt['name']} failed its save against magic. Add 1d6?")
            if near and "Arcane Omens" in feats and short <= 4 and self._cf_left(o, "Helpful Premonition", pb) and self._may_react(o):
                self._nf_offer(out, o, "reaction", "nf_omens", "Helpful Premonition (+1d4)", f"{tgt['name']} failed its save. Add 1d4?")
            if me and "Survivor" in feats and conds & {"Charmed", "Frightened"} and short <= pb and self._cf_left(o, "Steel Yourself", 1) and self._may_react(o):
                self._nf_offer(out, o, "reaction", "nf_steel", f"Steel Yourself (+{pb})", f"{tgt['name']} failed its save against fear or charm. Add +{pb}?")
            if me and "Transmuted Anatomy" in feats and sv.get("ab") == "con" and short <= 4 and self._cf_left(o, "Resilient Anatomy", pb) and self._may_react(o):
                self._nf_offer(out, o, "reaction", "nf_resilient", "Resilient Anatomy (+1d4)", f"{tgt['name']} failed its Constitution save. Add 1d4?")
            if me and "Symbiotic Being" in feats and self._cf_left(o, "Sustained Symbiosis", pb) and self._nf_hd_left(o) and self._may_react(o):
                self._nf_offer(out, o, "reaction", "nf_symbiosis", "Sustained Symbiosis (expend a Hit Die, add the roll)", f"{tgt['name']} failed its save. Add a Hit Die?")
            if me and "Mythal Touched" in feats and spell and att is not None and self._cf_left(o, "Mythal Ward", pb) and self._may_react(o):
                self._nf_offer(out, o, "reaction", "nf_mythal", "Mythal Ward (roll on the Mythal-Touched Magic table)", f"{tgt['name']} failed its save against {R.get('label')}. Mythal Ward?")

    def _nf_after_damage(self, out: list, R: dict, att: dict, tgt: dict, cur: dict, a: dict):
        types = {t for _n, t in (cur.get("dmg") or []) if _n > 0}
        tc = self._nf_char(tgt)
        if tc and self._alive(tgt):
            feats = set(tc.d.get("feats") or [])
            pb = tc.proficiency_bonus
            if "Shadowmoor Hexer" in feats and R.get("mode") == "attack" and self._nf_free_for(att, f"curse{tgt['id']}") \
                    and any(e["name"] == "Hex" and e.get("source_id") == tgt["id"] for e in att.get("effects") or []):
                self._nf_mark(att, f"curse{tgt['id']}")
                self._say("Curse Magic: " + self._deal(att, [[pb, "psychic"]], by=tgt, label="Curse Magic"))
            if self._may_react(tgt):
                if "Delicious Pain" in feats and types & {"bludgeoning", "piercing", "slashing"} and self._cf_left(tgt, "Toughened Flesh", 1, "short"):
                    self._nf_offer(out, tgt, "reaction", "nf_toughened", "Toughened Flesh (resist bludgeoning, piercing and slashing until your next turn)",
                                   f"{tgt['name']} was hurt. Toughened Flesh?", "after_damage")
                if "Zhentarim Tactics" in feats and R.get("mode") == "attack" and a.get("melee") and att.get("pos") and tgt.get("pos") and self._dist(att, tgt) <= 5 \
                        and self._alive(att):
                    self._nf_offer(out, tgt, "reaction", "nf_retaliate", f"Retaliate (opportunity attack on {att['name']})", f"{att['name']} hit {tgt['name']}. Retaliate?", "after_damage")
                if "Mist Walker" in feats and self._cf_left(tgt, "Mist Walk", pb) and self._mist_spot(tgt) is not None:
                    self._nf_offer(out, tgt, "reaction", "nf_mistwalk", "Mist Walk (teleport up to 15 ft)", f"{tgt['name']} was hurt. Mist Walk?", "after_damage")
        for o in self.b["combatants"]:                           # Reassert Honor: an ally of the holder, within 5 ft of it, was hurt by an enemy
            if o is not tgt and self._nf_has(o, "Lords' Alliance Agent") and not self._hostile(o, tgt) and self._hostile(o, att) and o.get("pos") and tgt.get("pos") \
                    and self._dist(o, tgt) <= 5 and self._sees(o, att) and self._alive(o):
                self._effect_on(o, "Reassert Honor", [], None, None, None, None, o["name"], {"adv_vs": att["id"]}, None, o["id"],
                                until={"end": o["id"], "skip": 1 if self.b.get("turn") == o["id"] else 0})
                self._say(f"{o['name']}: Reassert Honor, advantage on the next attack against {att['name']}")

    def _nf_free_for(self, c: dict, key: str) -> bool:
        return self._cf_turn_free(c, "nf:" + key)

    def _nf_mark(self, c: dict, key: str):
        self._once_per_turn(c, "nf:" + key)

    def _mist_spot(self, c: dict) -> Optional[list]:
        """A free tile within 15 ft, as far from the creatures hostile to `c` as possible."""
        if not c.get("pos"):
            return None
        foes = [o for o in self.b["combatants"] if self._hostile(c, o) and o.get("pos") and self._alive(o)]
        best, far = None, -1
        x0, y0 = c["pos"]
        for x in range(max(0, x0 - 3), x0 + 4):
            for y in range(max(0, y0 - 3), y0 + 4):
                if (x, y) != (x0, y0) and self._cf_landing(c, [x, y], 15) is None:
                    d = min([max(abs(x - o["pos"][0]), abs(y - o["pos"][1])) for o in foes] or [0])
                    if d > far:
                        best, far = [x, y], d
        return best

    def _nf_auto_pick(self, window: str, R: dict, reactor: dict, keys: List[str], cur: dict) -> Optional[str]:
        """What a reactor set to "always" picks among these feats' options ('' = none; None = not one of them)."""
        mine = [k for k in keys if k.split(":")[0] in NF_FAMILIES]
        if not mine:
            return None
        if window == "on_hit":
            for k in ("nf_feast", "nf_flustering"):
                if k in mine:
                    return k
            return ""
        if window == "damage":
            for k in ("nf_absorb", "nf_vitality", "nf_putrefy", "nf_rebuke", "nf_frostbite", "nf_fueled"):
                if k in mine:
                    return k
            return ""
        if window == "hit":
            need = int(cur.get("total") or 0) - int(cur.get("ac") or 0) - int(cur.get("ac_extra") or 0)
            if "nf_scream" in mine and need < self._prof(reactor):
                return "nf_scream"
            for k in ("nf_guardian", "nf_mythal"):
                if k in mine:
                    return k
            return ""
        if window == "save_failed":
            return mine[0]
        return mine[0]

    def _nf_react(self, window: str, R: dict, reactor: dict, fam: str, arg: str, ctx: dict) -> bool:
        if fam not in NF_FAMILIES:
            return False
        cur = R.setdefault("cur", {})
        char = self._sheet(reactor)
        name = reactor["name"]
        pb = char.proficiency_bonus
        att = self._find_or_none(ctx.get("attacker") or R.get("actor"))
        tgt = self._find_or_none(ctx.get("target")) or (self._find_or_none(R["targets"][R["ti"]]) if R.get("targets") and R.get("ti", 0) < len(R["targets"]) else None)

        def cut(n: int):
            left, after = n, []
            for d, t in cur.get("dmg") or []:
                take = min(d, left)
                left -= take
                after.append([d - take, t])
            cur["dmg"] = after

        def bonus(nm: str, die: str, who: dict, rest: str = "long", n: int = 1, extra: int = 0):
            roll_ = roll(die) + extra
            cur["total"] = int(cur.get("total") or 0) + roll_
            cur["ok"] = cur["total"] >= int((R.get("sv") or {}).get("dc") or 0)
            self._line(R, f"{name}'s {nm}: +{roll_} → {cur['total']}" + (" — success" if cur["ok"] else " — still failed"), nm)

        if fam == "nf_feast":
            self._cf_use(reactor, "Sanguine Feast")
            self._nf_once(reactor, "feast")
            rolls = self._nf_hd(reactor, 1)
            n = (rolls[0] if rolls else 0) + char.mod("con")
            self._heal(reactor, max(0, n))
            self._line(R, f"{name} feasts: +{max(0, n)} HP (Sanguine Feast)", "Sanguine Feast")
        elif fam == "nf_blazing":
            a = R.get("atk") or {}
            if a.get("parts"):
                a["parts"] = [[a["parts"][0][0], "radiant"]] + [list(p) for p in a["parts"][1:]]
            self._line(R, f"{name}'s weapon blazes: the damage is radiant (Blazing Strike)", "Blazing Strike")
        elif fam == "nf_flustering" and tgt:
            self._cf_use(reactor, "Flustering Strike")
            res = self._saving_throw(tgt, "wis", self._nf_dc(char, "Fairy Trickster"), label="Flustering Strike")
            if not res["ok"]:
                self._effect_on(tgt, "Flustered", [], None, None, None, None, name, {"save_dis": ["all"]}, None, reactor["id"],
                                until={"end": reactor["id"], "skip": 1 if self.b.get("turn") == reactor["id"] else 0})
                self._line(R, f"{tgt['name']} is flustered: disadvantage on saving throws (Flustering Strike)", "Flustering Strike")
            else:
                self._line(R, f"{tgt['name']} shrugs off the Flustering Strike", "Flustering Strike")
        elif fam == "nf_putrefy" and tgt:
            self._cf_use(reactor, "Putrefy", "short")
            self._effect_on(tgt, "Necrosis", ["Poisoned"], None, None, None, None, name, {}, None, reactor["id"], until={"start": reactor["id"]})
            self._line(R, f"{tgt['name']} is poisoned until {name}'s next turn (Putrefy)", "Putrefy")
        elif fam == "nf_rebuke" and tgt:
            self._cf_use(reactor, "Radiant Strike", "short")
            self._cond(tgt, "Prone", True)
            self._line(R, f"{tgt['name']} is knocked prone (Radiant Strike)", "Radiant Strike")
        elif fam == "nf_frostbite" and tgt:
            self._nf_once(reactor, "frostbite")
            self._effect_on(tgt, "Frostbite", [], None, None, None, None, name, {"save": "-1d4", "once": True}, None, reactor["id"],
                            until={"end": reactor["id"], "skip": 1 if self.b.get("turn") == reactor["id"] else 0})
            self._line(R, f"{tgt['name']}'s defenses falter: -1d4 on its next save (Frostbite)", "Frostbite")
        elif fam == "nf_fueled":
            self._nf_once(reactor, "fueled")
            rolls = self._nf_hd(reactor, 2)
            n = sum(rolls)
            if cur.get("dmg"):
                cur["dmg"][0][0] += n
            self._line(R, f"{name} burns {len(rolls)} Hit Dice: +{n} damage", "Fueled Spell")
        elif fam == "nf_surge":
            self._cf_use(reactor, "Power Surge")
            if cur.get("dmg"):
                cur["dmg"][0][0] += pb
            self._line(R, f"{name}'s power surges: +{pb} damage", "Power Surge")
        elif fam == "nf_overload":
            self._cf_use(reactor, "Spell Overload")
            parts = R.get("parts") or []
            if parts and R.get("mode") != "attack":
                new = [[_floor3(d) if not isinstance(d, int) else d, (t or "").lower()] for d, t in parts]
                if sum(n for n, _t in new) > sum(n for n, _t in cur.get("dmg") or []):
                    cur["dmg"] = new
            R["nf_overload"] = True
            self._line(R, f"{name}'s magic surges: 1s and 2s count as 3 (Spell Overload)", "Spell Overload")
        elif fam == "nf_radiance":
            self._cf_use(reactor, "Powerful Radiance")
            parts = R.get("parts") or (R.get("atk") or {}).get("parts") or []
            for i, (d, t) in enumerate(parts):
                if t == "radiant" and i < len(cur.get("dmg") or []) and not isinstance(d, int):
                    cur["dmg"][i][0] = max(cur["dmg"][i][0], _dmax(d))
            self._line(R, f"{name}'s radiance is at its brightest: the highest radiant dice (Powerful Radiance)", "Powerful Radiance")
        elif fam == "nf_absorb":
            self._nf_once(reactor, "absorb")
            n = roll("1d4")
            cut(n)
            self._line(R, f"{name} absorbs some of the magic: -{n} damage (Magic Absorption)", "Magic Absorption")
        elif fam == "nf_vitality":
            self._cf_use(reactor, "Vitality Ward", "short")
            n = roll(f"{pb}d6")
            left = n
            after = []
            for d, t in cur.get("dmg") or []:
                take = min(d, left) if t == "necrotic" else 0
                left -= take
                after.append([d - take, t])
            cur["dmg"] = after
            self._line(R, f"{name} wards off the death-chill: -{n - left} necrotic damage (Vitality Ward)", "Vitality Ward")
        elif fam == "nf_toughened":
            self._cf_use(reactor, "Toughened Flesh", "short")
            self._effect_on(reactor, "Toughened Flesh", [], None, None, None, None, name, {"resist": ["bludgeoning", "piercing", "slashing"]}, None, reactor["id"],
                            until={"start": reactor["id"]})
            self._line(R, f"{name} toughens its flesh: resists bludgeoning, piercing and slashing until its next turn", "Toughened Flesh")
        elif fam == "nf_scream":
            self._cf_use(reactor, "Unearthly Scream")
            cur["ac_extra"] = cur.get("ac_extra", 0) + pb
            self._line(R, f"{name} lets out an unearthly scream: +{pb} AC against this attack", "Unearthly Scream")
        elif fam == "nf_guardian" and att:
            self._cf_use(reactor, "Vigilant Guardian")
            victim = self._find_or_none(R["targets"][R["ti"]])
            if victim:
                reactor["pos"], victim["pos"] = victim["pos"], reactor["pos"]
                self._vfx("blink", id=reactor["id"], at=victim["pos"], to=reactor["pos"])
                R["targets"][R["ti"]] = reactor["id"]
                cur["total"] = max(int(cur.get("total") or 0), self._ac_of(reactor) + cur.get("ac_extra", 0))
                self._line(R, f"{name} swaps places with {victim['name']} and takes the hit (Vigilant Guardian)", "Vigilant Guardian")
                if char and "Greater Mark of Sentinel" in (char.d.get("feats") or []) and self._alive(att):
                    try:
                        w, atk = self._cf_weapon(reactor, char, att)
                        self._stack().append(self._strike(reactor, f"{w['name']} (Improved Sentinel)", [att["id"]], mode="attack", atk=atk, magical=atk.get("magical", False)))
                    except ServiceError:
                        pass
        elif fam == "nf_warding" and att and tgt:
            self._cf_use(reactor, "Improved Warding")
            self._effect_on(tgt, f"Warded by {name}", [], None, None, None, 1, name, {"attacks_against": "dis", "once": True}, None, reactor["id"])
            self._line(R, f"{name} wards {tgt['name'] if tgt is not reactor else 'itself'}: the attack has disadvantage (Improved Warding)", "Improved Warding")
        elif fam == "nf_prescient" and att:
            self._cf_use(reactor, "Prescient Intervention")
            self._effect_on(att, f"Prescient Intervention ({name})", [], None, None, None, 1, name, {"attacks_with": "dis", "once": True}, None, reactor["id"])
            self._line(R, f"{name} sees it coming: {att['name']} attacks with disadvantage (Prescient Intervention)", "Prescient Intervention")
        elif fam == "nf_mythal":
            self._cf_use(reactor, "Mythal Ward")
            self._mythal(R, reactor, char, att, tgt, window)
        elif fam == "nf_retaliate" and att:
            child = self._opportunity_strike(reactor, att)
            if child:
                child["label"] = f"Retaliate ({name})"
                self._stack().append(child)
        elif fam == "nf_mistwalk":
            self._cf_use(reactor, "Mist Walk")
            spot = self._mist_spot(reactor)
            if spot:
                self._cf_teleport(reactor, spot)
            self._line(R, f"{name} dissolves into mist and reappears at {self._tile_label(spot)} (Mist Walk)" if spot else f"{name} has nowhere to go", "Mist Walk")
        elif fam == "nf_fortune":
            self._nf_once(reactor, "fortune")
            again = self.rng.randint(1, 20)
            total = cur["total"] - cur["kept"] + again
            cur.update(total=total, kept=again, ok=total >= int(R["sv"]["dc"]))
            self._line(R, f"{name} rerolls the save (Saving Throw Reroll): {again} → {total}" + (" — success" if cur["ok"] else " — still failed"), "Saving Throw Reroll")
        elif fam == "nf_steel":
            self._cf_use(reactor, "Steel Yourself")
            cur["total"] = int(cur.get("total") or 0) + pb
            cur["ok"] = cur["total"] >= int(R["sv"]["dc"])
            self._line(R, f"{name} steels itself: +{pb} → {cur['total']}" + (" — success" if cur["ok"] else " — still failed"), "Steel Yourself")
        elif fam == "nf_magres":
            self._cf_use(reactor, "Magic Resistant")
            bonus("Magic Resistant", "1d6", reactor)
        elif fam == "nf_omens":
            self._cf_use(reactor, "Helpful Premonition")
            bonus("Helpful Premonition", "1d4", reactor)
        elif fam == "nf_resilient":
            self._cf_use(reactor, "Resilient Anatomy")
            bonus("Resilient Anatomy", "1d4", reactor)
        elif fam == "nf_symbiosis":
            self._cf_use(reactor, "Sustained Symbiosis")
            rolls = self._nf_hd(reactor, 1)
            n = rolls[0] if rolls else 0
            cur["total"] = int(cur.get("total") or 0) + n
            cur["ok"] = cur["total"] >= int(R["sv"]["dc"])
            self._line(R, f"{name}'s symbiote lends a Hit Die: +{n} → {cur['total']}" + (" — success" if cur["ok"] else " — still failed"), "Sustained Symbiosis")
        elif fam == "nf_siphon":
            pass
        return True

    def _mythal(self, R: dict, c: dict, char, att: Optional[dict], tgt: Optional[dict], window: str):
        """Mythal Ward: 1d20 on the Mythal-Touched Magic table (the triggering spell's level is the slot it was cast with)."""
        n = roll("1d20")
        name = c["name"]
        dc = self._nf_dc(char, "Mythal Touched")
        lvl = max(1, int(R.get("slot_level") or (rules.spell(re.sub(r" \(.*\)$", "", R.get("label") or "")) or {}).get("level") or 1))
        cur = R.setdefault("cur", {})
        if n <= 2:
            near = [o for o in self.b["combatants"] if o.get("pos") and c.get("pos") and self._alive(o) and (o is c or self._dist(o, c) <= 15)]
            self._line(R, f"Mythal Ward ({n}): a burst of force around {name}", "Mythal Ward")
            self._stack().append(self._strike(c, "Mythal Ward", [o["id"] for o in near], mode="save", magical=True,
                                              sv={"ab": "dex", "dc": dc, "half": True}, parts=[[f"{lvl}d8", "force"]]))
        elif n <= 7:
            self._line(R, f"Mythal Ward ({n}): {name} and {att['name'] if att else 'the caster'} share a telepathic link for an hour", "Mythal Ward")
        elif n <= 10:
            self._line(R, f"Mythal Ward ({n}): gravity reverses around {name} for a minute (Reverse Gravity; not played on this map)", "Mythal Ward")
        elif n <= 13:
            for o in (c, att):
                if o is not None:
                    res = self._saving_throw(o, "con", dc, label="Mythal Ward")
                    if not res["ok"]:
                        self._effect_on(o, "Mythal Ward (stunned)", ["Stunned"], None, None, None, None, name, {}, None, c["id"], until={"end": o["id"], "skip": 1 if self.b.get("turn") == o["id"] else 0})
            self._line(R, f"Mythal Ward ({n}): {name} and {att['name'] if att else 'the caster'} each make a Constitution save or are stunned", "Mythal Ward")
        elif n <= 17:
            self._effect_on(c, "Mythal Ward (+2 AC)", [], None, None, None, 10, name, {"ac": 2}, None, c["id"])
            if window == "hit":
                cur["ac_extra"] = cur.get("ac_extra", 0) + 2
            self._line(R, f"Mythal Ward ({n}): +2 AC for a minute", "Mythal Ward")
        elif n <= 19:
            self._line(R, f"Mythal Ward ({n}): flammable objects near {att['name'] if att else 'the caster'} burst into flame", "Mythal Ward")
        else:
            if window == "hit":
                cur.update(total=0, kept=0, crit=False, saved_by="Mythal Ward")
            else:
                cur.update(ok=True, total=int(R["sv"]["dc"]) + 99)
            self._line(R, "Mythal Ward (20): the spell dissipates with no effect", "Mythal Ward")

    def _nf_summoned(self, att: dict, sp: dict, made: list):
        """Fortified Familiar (+2 x level hit points), Elemental and Otherworldly Familiar (resistance to the picked type)."""
        char = self._nf_char(att)
        if not char or sp.get("name") != "Find Familiar":
            return
        from ...rules import feat_extras as FE
        feats = set(char.d.get("feats") or [])
        for fam in made:
            if "Familiar Friend" in feats:
                extra = 2 * char.total_level
                fam["hp"] = fam["max_hp"] = int(fam.get("max_hp") or fam.get("hp") or 1) + extra
            for feat in ("Elemental Familiar", "Otherworldly Familiar"):
                kind = FE.picks(char, feat).get("familiar")
                if feat in feats and kind:
                    self._effect_on(fam, feat, [], None, None, None, None, att["name"], {"resist": [kind]}, None, att["id"])
