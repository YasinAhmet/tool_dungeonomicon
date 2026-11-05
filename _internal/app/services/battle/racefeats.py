"""Race and lineage traits in battle (features.ACTIVE lists the bar's; classfeats.py and subfeats.py hand over here):

    passives(char)    always-on traits from a race's text: advantage on saves against conditions (Loxodon Serenity, Leviathan Will,
                      Mechanical Nature, Constructed Resilience...), Dual Mind, Vedalken Dispassion, Magic Resistance, Earth Walk
    Leonin            Daunting Roar              Astral Elf   Starlight Step           Tabaxi    Feline Agility
    Kobold (VGM)      Grovel, Cower, and Beg     Dhampir      Vampiric Bite            Shifter   the Shifting Feature of each lineage
    Giff              Astral Spark (on a hit)    Hadozee      Hadozee Dodge (reaction) Autognome Built for Success (a d4 on a roll)
    Bugbear           Long-Limbed (reach on its own turn)    Kender       Taunt             Centaur   Charge
    Feats (Bigby's giants, Dragonlance knights, Sigil's planar feats): Searing Ignition, Stone Throw, Maelstrom Aura, Bolstering and
                      Commanding Rally, Frigid Retaliation, Soothe Pain, Cloudy Escape, Strike of the Giants, Demoralizing Strike,
                      Stasis Strike, Grasp of Avarice

Resistances, speeds, natural armour (Tortle shell, Lizardfolk scales) and the Hare-Trigger initiative are on the character sheet
(rules/character.py), so the battle already has them.
"""
import re
from typing import List, Optional

from ...rules import combat_feats as CF
from ...rules.data import rules
from . import features as F
from .newfeats import NF_ACTIVE, NF_FAMILIES, NF_FREE, STATIC as NF_STATIC, NewFeatsMixin     # the feats of the later books (newfeats.py)
from .resolve import roll

# trait -> what it gives while the creature has it (effect-style mods, see modifiers.py)
SAVE_ADV = {"Dual Mind": ["wis"], "Vedalken Dispassion": ["int", "wis", "cha"]}
COND_ADV = {"Loxodon Serenity": ["Charmed", "Frightened"], "Leviathan Will": ["Charmed", "Frightened", "Paralyzed", "Poisoned", "Stunned"],
            "Fearless": ["Frightened"], "Mechanical Nature": ["Paralyzed", "Poisoned"], "Constructed Resilience": ["Poisoned"],
            "Deathless Nature": ["Poisoned"], "Natural Resilience": ["Poisoned"], "Duergar Resilience": ["Poisoned", "Charmed", "Paralyzed"],
            "Psionic Fortitude": ["Charmed", "Stunned"]}
SPELL_ADV = {"Magic Resistance"}                           # Yuan-ti: advantage on saves against spells and other magical effects


def passives(char, have: set) -> List[dict]:
    """Race traits that are always on, as effect-like entries (features.passives adds them; `have` = names it already made)."""
    out = []
    names = {t["name"] for t in (char.race_data() or {}).get("traits") or []}

    def add(name, **mods):
        if name not in have:
            out.append({"name": name, "mods": mods, "conditions": [], "feature": True})

    for name, abs_ in SAVE_ADV.items():
        if name in names:
            add(name, save_adv=list(abs_))
    for name, conds in COND_ADV.items():
        if name in names:
            add(name, cond_save_adv=list(conds))
    for name in SPELL_ADV:
        if name in names:
            add(name, save_adv=["spells"])
    if "Earth Walk" in names:
        add("Earth Walk", free_move=True)                  # difficult terrain costs no extra movement
    feats = set(char.d.get("feats") or [])
    if "Ember of the Fire Giant" in feats:
        add("Born of Flame", resist=["fire"])
    if "Fury of the Frost Giant" in feats:
        add("Born of Ice", resist=["cold"])
    for feat, traits in NF_STATIC.items():                 # Boon of Poison Mastery's immunities, Aberrant Anatomy's blindsight... (newfeats.py)
        if feat in feats:
            for tname, mods in traits.items():
                add(tname, **{k: (list(v) if isinstance(v, list) else dict(v) if isinstance(v, dict) else v) for k, v in mods.items()})
    return out


def _has(char, *names) -> bool:
    return any(char.has_feature(n) for n in names)


def _pb(c) -> int:
    return c.proficiency_bonus


def _long_or_short(c) -> str:
    return "long" if F.mpmm(c) else "short"


# ---------------------------------------------------------------------- the bar
RACE_ACTIVE = {
    "daunting_roar": {"name": "Daunting Roar", "cost": "bonus", "resource": None, "per": _long_or_short,
                      "uses": lambda c: _pb(c) if F.mpmm(c) else 1, "target": "none", "needs": lambda c: _has(c, "Daunting Roar"),
                      "text": "A menacing roar: foes within 10 ft that can hear you make a Wisdom save (8 + proficiency + Constitution) or are "
                              "frightened of you until the end of your next turn."},
    "starlight_step": {"name": "Starlight Step", "cost": "bonus", "resource": None, "per": "long", "uses": lambda c: _pb(c), "target": "point",
                       "teleport": 30, "needs": lambda c: _has(c, "Starlight Step"),
                       "text": "Teleport up to 30 ft to an unoccupied space you can see."},
    "feline_agility": {"name": "Feline Agility", "cost": "free", "resource": None, "target": "self", "needs": lambda c: _has(c, "Feline Agility"),
                       "text": "Double your speed until the end of the turn. You can't use it again until you move 0 feet on one of your turns."},
    "grovel": {"name": "Grovel, Cower, and Beg", "cost": "action", "resource": None, "per": "short", "target": "none",
               "needs": lambda c: _has(c, "Grovel, Cower, and Beg"),
               "text": "Until the end of your next turn, your allies have advantage on attack rolls against foes within 10 ft of you."},
    "vampiric_bite": {"name": "Vampiric Bite", "cost": "attack", "resource": None, "target": "enemy", "range": 5,
                      "needs": lambda c: _has(c, "Vampiric Bite"),
                      "text": "Your fanged bite: 1d4 + Constitution piercing, advantage while you are at half your hit points or less. On a hit "
                              "against a creature that isn't a Construct or Undead: regain hit points equal to the damage."},
    "shifting_bite": {"name": "Longtooth Bite", "cost": "bonus", "resource": None, "target": "enemy", "range": 5, "when": "shifted",
                      "needs": lambda c: _shifter(c) == "Longtooth",
                      "text": "While shifted: a bite as a bonus action, 1d6 + Strength piercing."},
}


def _feat(c, name: str) -> bool:
    return name in (c.d.get("feats") or [])


def feat_mod(char, feat: str) -> int:
    """The modifier of the ability a feat raised ("the modifier of the ability increased by this feat"); the best allowed one if unknown."""
    ab = (rules.feats.get(feat) or {}).get("ability") or {}
    cand = list(ab.get("fixed") or {}) + list((ab.get("choose") or {}).get("from") or []) or ["str"]
    raised = [a for a in cand if (char.d["abilities"].get("feat") or {}).get(a)]
    return max(char.mod(a) for a in (raised or cand))


def _once(f: str, name: str, **kw) -> dict:
    return {"name": name, "resource": None, "per": "long", "uses": lambda c: _pb(c), "needs": lambda c: _feat(c, f), **kw}


FEAT_ACTIVE = {
    "searing_ignition": _once("Ember of the Fire Giant", "Searing Ignition", cost="attack", target="none",
                              text="In place of an attack: a 15-ft burst of flame around you. Foes make a Dexterity save or take 1d8 + proficiency fire "
                                   "and are blinded until the start of your next turn (half and no blinding on a save). Once a turn."),
    "stone_throw": _once("Keenness of the Stone Giant", "Stone Throw", cost="bonus", target="enemy", range=60,
                         text="A magical rock: ranged spell attack within 60 ft, 1d10 force; on a hit a Strength save or prone."),
    "maelstrom_aura": _once("Soul of the Storm Giant", "Maelstrom Aura", cost="bonus", target="self",
                            text="Until your next turn: resistance to lightning and thunder, attacks against you have disadvantage."),
    "bolstering_rally": _once("Knight of the Rose", "Bolstering Rally", cost="bonus", target="ally", range=30,
                              text="A creature within 30 ft (or you) gains 1d8 + proficiency bonus + the feat's ability modifier temporary hit points."),
    "commanding_rally": _once("Knight of the Crown", "Commanding Rally", cost="bonus", target="ally", range=30,
                              text="An ally within 30 ft attacks as a reaction; a hit adds 1d8 damage."),
}
FEAT_OF = {"searing_ignition": "Ember of the Fire Giant", "stone_throw": "Keenness of the Stone Giant", "maelstrom_aura": "Soul of the Storm Giant",
           "bolstering_rally": "Knight of the Rose", "commanding_rally": "Knight of the Crown"}
RACE_ACTIVE.update(FEAT_ACTIVE)
RACE_ACTIVE.update(NF_ACTIVE)
RACE_ACTIVE["kender_taunt"] = {"name": "Taunt", "cost": "bonus", "resource": None, "per": "long", "uses": lambda c: _pb(c), "target": "enemy", "range": 60,
                               "needs": lambda c: _has(c, "Taunt"),
                               "text": "A foe within 60 ft that can hear you makes a Wisdom save or has disadvantage on attacks against anyone but you until "
                                       "the start of your next turn."}
RACE_ACTIVE["centaur_charge"] = {"name": "Charge (hooves)", "cost": "bonus", "resource": None, "target": "enemy", "range": 5,
                                 "needs": lambda c: _has(c, "Charge") and (c.d.get("race") or "").startswith("Centaur"),
                                 "text": "After moving at least 30 ft toward a foe and hitting it with a melee weapon attack: a hooves attack as a bonus action."}
F.ACTIVE.update(RACE_ACTIVE)

RACE_FAMILIES = {"astral_spark": "Astral Spark", "hadozee_dodge": "Hadozee Dodge", "built_for_success": "Built for Success",
                 "frigid": "Frigid Retaliation", "soothe_pain": "Soothe Pain", "cloudy_escape": "Cloudy Escape", "giant_strike": "Strike of the Giants",
                 "demoralizing": "Demoralizing Strike", "stasis_strike": "Stasis Strike", "avarice": "Grasp of Avarice"}
RACE_FREE = {"astral_spark", "built_for_success", "giant_strike", "demoralizing", "stasis_strike", "avarice"} | NF_FREE
RACE_FAMILIES.update(NF_FAMILIES)
TARGETED_RACE = {"vampiric_bite", "shifting_bite", "stone_throw", "kender_taunt", "centaur_charge"}


def is_firearm(item: Optional[dict]) -> bool:
    """A Dungeon Master's Guide firearm (pistol, musket...: renaissance or modern bullets)."""
    return "bullet" in str((item or {}).get("ammo_type") or "") and ("renaissance" in item["ammo_type"] or "modern" in item["ammo_type"])


def _shifter(char) -> str:
    """The Eberron shifter lineage (Beasthide, Longtooth, Swiftstride, Wildhunt), when the character is one."""
    return (char.d.get("subrace") or "") if (char.d.get("race") or "") == "Shifter" and char.has_feature("Shifting Feature") else ""


class RaceFeatsMixin(NewFeatsMixin):
    def _race_families(self, char) -> List[str]:
        out = []
        if char.has_feature("Astral Spark"):
            out.append("astral_spark")
        if char.has_feature("Hadozee Dodge"):
            out.append("hadozee_dodge")
        if char.has_feature("Built for Success"):
            out.append("built_for_success")
        feats = set(char.d.get("feats") or [])
        for feat, fam in (("Fury of the Frost Giant", "frigid"), ("Righteous Heritor", "soothe_pain"), ("Guile of the Cloud Giant", "cloudy_escape"),
                          ("Strike of the Giants", "giant_strike"), ("Knight of the Sword", "demoralizing"), ("Agent of Order", "stasis_strike"),
                          ("Baleful Scion", "avarice")):
            if feat in feats:
                out.append(fam)
        return out + self._nf_families(char)

    def _race_firearm(self, att: dict, w: dict) -> bool:
        """Gunner and a giff's Firearms Mastery: a firearm ignores Loading, and shooting beside a foe has no disadvantage."""
        char = self._sheet(att)
        if not char or att.get("form") or not is_firearm(rules.item(w.get("weapon_name") or w.get("name") or "")):
            return False
        return bool(self._feat(att, "gunner")) or char.has_feature("Firearms Mastery")

    # ------------------------------------------------------------------ reach and turns
    def _race_reach(self, c: dict, char) -> int:
        """Long-Limbed: +5 ft of reach for melee attacks on the bugbear's own turn."""
        return (5 if char.has_feature("Long-Limbed") and self.b.get("turn") == c["id"] else 0) + self._nf_reach(c, char)       # + Boon of Looming Shadows

    def _race_turn_end(self, c: dict):
        """Feline Agility comes back after a turn without moving; an aasimar's Radiant Consumption burns everyone near at the end of its turn."""
        char = self._sheet(c)
        if char and any(e["name"] in ("Radiant Consumption", "Inner Radiance") for e in c.get("effects") or []):
            new = F.mpmm(char)                                  # MPMM: proficiency bonus, not the aasimar; Volo's: half its level, rounded up, itself too
            n = char.proficiency_bonus if new else (char.total_level + 1) // 2
            for o in self.b["combatants"]:
                if o.get("pos") and c.get("pos") and self._alive(o) and (o is c and not new or o is not c and self._within(c, o, 10)):
                    self._say(f"{c['name']}'s searing light: " + self._deal(o, [[n, "radiant"]], by=c, label="Radiant Consumption"))
        t = c.get("turn")
        if c.get("feline_spent") and t and c.get("feline_turn") != [self.b.get("round"), c["id"]] \
                and t.get("move", 0) >= t.get("speed", 0) * (1 + int(t.get("dashed") or 0)):
            c["feline_spent"] = False

    def _race_dealt(self, tgt: dict, by: Optional[dict], total: int, label: str):
        """Vampiric Bite: a hit on a creature that isn't a Construct or Undead gives the dhampir hit points equal to the damage."""
        if by is None or total <= 0 or not str(label).startswith("Vampiric Bite") or by.get("form") or not self._alive(by)                 or re.search(r"construct|undead", self._ctype(self._monster(tgt))):
            return
        self._heal(by, total)
        self._say(f"{by['name']} drinks {total} hit points (Vampiric Bite)")

    def _race_modes(self, att: dict, tgt: dict, a: dict) -> list:
        """[(mode, why)] added to an attack roll: a dhampir's bite at half its hit points or less."""
        out = self._nf_modes(att, tgt, a)                                   # Inevitable Betrayal, Last Stand, Headlock (newfeats.py)
        if a.get("vampiric") and self._hp_of(att) * 2 <= self._max_hp(att):
            out.append(("adv", "Vampiric Bite (half hit points or less)"))
        return out

    # ------------------------------------------------------------------ the bar: why not, and what it does
    def _race_why(self, c: dict, char, key: str, f: dict, tgt: Optional[dict], option, menu: bool, point) -> Optional[str]:
        if key in NF_ACTIVE:
            return self._nf_why(c, char, key, f, tgt, option, menu, point)       # the later feats (newfeats.py)
        if key not in RACE_ACTIVE and key != "shifting":
            return None
        if key == "feline_agility":
            if self.b.get("turn") != c["id"] and self._economy_on():
                return "Only on your own turn"
            if c.get("feline_spent"):
                return "Move 0 feet on one of your turns to use it again"
        if f.get("when") == "shifted" and not self._fx(c, "shifted"):
            return "Only while shifted"
        if key == "shifting" and self._fx(c, "shifted"):
            return "Already shifted"
        if not menu and key in TARGETED_RACE and (not tgt or tgt is c):
            return "Pick a target first."
        if not menu and key in TARGETED_RACE and not self._hostile(c, tgt):
            return f"Pick a foe, not {tgt['name']}."
        if key in ("vampiric_bite", "searing_ignition") and not menu and self._economy_on():
            return self._pay(c, "attack", f["name"], check_only=True)
        if key == "searing_ignition" and not self._cf_turn_free(c, "searing_ignition"):
            return "Once a turn"
        if key == "centaur_charge" and self._economy_on():
            t = c.get("turn") or {}
            if not t.get("attacked"):
                return "Hit with a melee weapon attack first"
            if (self._run_ft(c) < 30 if menu or not tgt else not self._charged(c, tgt, 30)) \
                    or not menu and tgt and tgt["id"] not in (t.get("melee_targets") or [tgt["id"]]):
                return "Run at least 30 ft straight at the foe and hit it with a melee weapon first"
        if key in ("bolstering_rally", "commanding_rally") and not menu and tgt is not None and self._hostile(c, tgt):
            return f"Pick an ally, not {tgt['name']}."
        if key == "commanding_rally" and not menu and (tgt is None or tgt is c):
            return "Pick an ally to command."
        if key in ("bolstering_rally", "commanding_rally") and not menu and tgt is not None and tgt is not c and self._dist(c, tgt) > 30:
            return f"{tgt['name']} is out of range (30 ft)"
        return None

    def _race_feature(self, c: dict, char, key: str, f: dict, tgt: Optional[dict], option, point) -> Optional[str]:
        name = c["name"]
        t = c.get("turn")
        if key in NF_ACTIVE:
            return self._nf_feature(c, char, key, f, tgt, option, point)
        if key == "feline_agility":
            c["feline_spent"] = True
            c["feline_turn"] = [self.b.get("round"), c["id"]]
            if t is not None:
                t["move"] = int(t.get("move", 0)) + int(t.get("speed", 0))
            return self._out(f"{name} bursts into feline speed: speed doubled this turn")
        if key == "starlight_step":
            spot = self._cf_teleport(c, point)
            return self._out(f"{name} uses Starlight Step: teleports to {self._tile_label(spot)}")
        if key == "daunting_roar":
            near = self._cf_hostiles(c, 10)
            if not near:
                return self._out(f"{name} roars: no foe within 10 ft")
            return self._run_r(self._strike(c, "Daunting Roar", [o["id"] for o in near], mode="save", magical=False,
                                            sv={"ab": "wis", "dc": self._cf_dc(char, "con"), "half": False, "conds": ["Frightened"],
                                                "until": "caster_end_next"}, parts=[]))
        if key == "grovel":
            near = self._cf_hostiles(c, 10)
            for o in near:
                self._effect_on(o, "Grovel, Cower, and Beg", [], None, None, None, None, name, {"attacks_against": "adv"},
                                None, c["id"], until={"end": c["id"], "skip": 1})
            return self._out(f"{name} cowers pathetically: allies have advantage against " + (", ".join(o["name"] for o in near) or "nobody within 10 ft"))
        if key == "vampiric_bite":
            mod = char.mod("con")
            atk = {"bonus": char.proficiency_bonus + mod, "n": 1, "melee": True, "weapon": True, "reach": 5, "props": [], "ability": "con",
                   "parts": [[f"1d4{mod:+d}" if mod else "1d4", "piercing"]], "vampiric": True}
            atk = self._check_reach(c, tgt, atk)
            self._pay_attack(c, F.extra_attacks(char), f["name"])
            return self._run_r(self._strike(c, "Vampiric Bite", [tgt["id"]], mode="attack", atk=atk, magical=False))      # _race_dealt drinks
        if key == "centaur_charge":
            mod = char.mod("str")
            atk = {"bonus": char.proficiency_bonus + mod, "n": 1, "melee": True, "weapon": True, "reach": 5, "props": [], "ability": "str", "str_based": True,
                   "parts": [[f"1d6{mod:+d}" if mod else "1d6", "bludgeoning"]]}
            atk = self._check_reach(c, tgt, atk)
            return self._run_r(self._strike(c, "Charge (hooves)", [tgt["id"]], mode="attack", atk=atk, magical=False))
        if key == "shifting_bite":
            mod = char.mod("str")
            atk = {"bonus": char.proficiency_bonus + mod, "n": 1, "melee": True, "weapon": True, "reach": 5, "props": [], "ability": "str",
                   "parts": [[f"1d6{mod:+d}" if mod else "1d6", "piercing"]]}
            atk = self._check_reach(c, tgt, atk)
            return self._run_r(self._strike(c, "Longtooth Bite", [tgt["id"]], mode="attack", atk=atk, magical=False))
        if key in FEAT_ACTIVE:
            return self._race_feat_feature(c, char, key, f, tgt)
        if key == "kender_taunt":
            return self._kender_taunt(c, char, tgt)
        if key == "shifting" and _shifter(char):
            kind = _shifter(char)
            n = max(1, char.total_level + char.mod("con"))
            if kind == "Beasthide":
                n += roll("1d6")
            self._give_temp(c, n)
            mods = {"shifted": True}
            if kind == "Beasthide":
                mods["ac"] = 1
            elif kind == "Swiftstride":
                mods["speed"] = 10
            elif kind == "Wildhunt":
                mods.update(check_adv=["wis"], no_adv_against=True)
            self._effect_on(c, "Shifting", [], None, None, None, 10, name, mods, None, c["id"])
            more = {"Beasthide": ", +1 AC", "Longtooth": ", a bite as a bonus action", "Swiftstride": ", +10 ft speed",
                    "Wildhunt": ", nobody has advantage against it"}[kind]
            return self._out(f"{name} shifts: {n} temporary HP{more}")
        return None

    # ------------------------------------------------------------------ feats on the bar
    def _race_feat_feature(self, c: dict, char, key: str, f: dict, tgt: Optional[dict]) -> str:
        name = c["name"]
        feat = FEAT_OF[key]
        mod, pb = feat_mod(char, feat), char.proficiency_bonus
        dc = 8 + pb + mod
        if key == "searing_ignition":
            self._once_per_turn(c, "searing_ignition")
            self._pay_attack(c, F.extra_attacks(char), f["name"])
            near = self._cf_hostiles(c, 15)
            if not near:
                return self._out(f"{name} bursts into flame: no foe within 15 ft")
            return self._run_r(self._strike(c, "Searing Ignition", [o["id"] for o in near], mode="save", magical=True,
                                            sv={"ab": "dex", "dc": dc, "half": True, "conds": ["Blinded"], "until": "caster_start"},
                                            parts=[[f"1d8+{pb}", "fire"]]))
        if key == "stone_throw":
            atk = {"bonus": pb + mod, "n": 1, "melee": False, "spell": True, "normal": 60, "long": 60, "parts": [[f"1d10{mod:+d}" if mod else "1d10", "force"]]}
            R = self._strike(c, "Stone Throw", [tgt["id"]], mode="attack", atk=atk, magical=True)
            out = self._run_r(R)
            if R.get("hits") and self._alive(tgt) and not self._saving_throw(tgt, "str", dc, label="Stone Throw")["ok"]:
                self._cond(tgt, "Prone", True)
                out += f"; {tgt['name']} is knocked prone"
            return out
        if key == "maelstrom_aura":
            self._effect_on(c, "Maelstrom Aura", [], None, None, None, None, name, {"resist": ["lightning", "thunder"], "attacks_against": "dis"}, None,
                            c["id"], until={"start": c["id"]})
            return self._out(f"{name} wraps itself in wind and lightning: resists lightning and thunder, attacks against it have disadvantage")
        if key == "bolstering_rally":
            who = tgt or c
            n = roll("1d8") + pb + mod
            self._give_temp(who, n)
            return self._out(f"{name} rallies {who['name'] if who is not c else 'itself'}: {n} temporary HP")
        if key == "commanding_rally":
            foe = min((o for o in self._cf_hostiles(tgt, 30) if self._dist(tgt, o) <= max(5, self._reach(tgt))), key=lambda o: self._dist(tgt, o), default=None)
            if foe is None or not self._may_react(tgt):
                return self._out(f"{name} commands {tgt['name']}, but it has no foe in reach (or no reaction)")
            child = self._opportunity_strike(tgt, foe)
            if not child:
                return self._out(f"{tgt['name']} has no melee attack to make")
            self._spend_reaction(tgt, "Commanding Rally")
            child["label"] = f"Commanding Rally ({tgt['name']})"
            child["atk"]["parts"] = list(child["atk"].get("parts") or []) + [["1d8", (child["atk"].get("parts") or [["", ""]])[0][1]]]
            return self._run_r(child)
        return ""

    def _kender_taunt(self, c: dict, char, tgt: Optional[dict]) -> str:
        name = c["name"]
        dc = 8 + char.proficiency_bonus + max(char.mod("int"), char.mod("wis"), char.mod("cha"))
        if not self._saving_throw(tgt, "wis", dc, label="Taunt")["ok"]:
            self._effect_on(tgt, "Taunt", [], None, None, None, None, name, {"duel": True}, None, c["id"], until={"start": c["id"]})
            return self._out(f"{name} taunts {tgt['name']}: disadvantage on attacks against anyone else")
        return self._out(f"{name} taunts {tgt['name']}, who laughs it off")

    # ------------------------------------------------------------------ reactions and on-hit choices
    def _race_offer_free(self, out: list, att: dict, tgt: dict, cur: dict, opts: list):
        """Options on a hit, joined to the attacker's free question (or a new one)."""
        if not opts:
            return
        for item in out:
            if item["reactor"] == att["id"] and item["cost"] == "free":
                item["options"] += opts
                return
        out.append({"reactor": att["id"], "cost": "free", "options": opts,
                    "text": f"{att['name']} hits {tgt['name']}" + (" (critical!)" if cur.get("crit") else "") + ". Add something?"})

    def _race_on_hit(self, out: list, R: dict, att: dict, tgt: dict):
        cur = R.get("cur") or {}
        a = R.get("atk") or {}
        ac_ = self._sheet(att)
        if not ac_ or att.get("form") or not a.get("weapon"):
            return
        pb = ac_.proficiency_bonus
        feats = set(ac_.d.get("feats") or [])
        opts = []
        if ac_.has_feature("Astral Spark") and self._cf_turn_free(att, "astral_spark") and self._cf_left(att, "Astral Spark", pb):
            opts.append({"key": "astral_spark", "label": f"Astral Spark (+{pb} force)", "detail": ""})
        if "Strike of the Giants" in feats and self._cf_turn_free(att, "giant_strike") and (a.get("melee") or a.get("thrown")):
            kind = CF.is_on(ac_, "strike_giants") or "Cloud"
            opts.append({"key": "giant_strike", "label": f"{kind} Strike", "detail": ""})
        if "Knight of the Sword" in feats and self._cf_turn_free(att, "demoralizing") and self._cf_left(att, "Demoralizing Strike", pb):
            opts.append({"key": "demoralizing", "label": "Demoralizing Strike (Wis save or frightened)", "detail": ""})
        if "Agent of Order" in feats and self._cf_turn_free(att, "stasis_strike") and self._cf_left(att, "Stasis Strike", pb) \
                and self._dist(att, tgt) <= 60:
            opts.append({"key": "stasis_strike", "label": "Stasis Strike (+1d8 force, Wis save or restrained)", "detail": ""})
        if "Baleful Scion" in feats and self._cf_turn_free(att, "avarice") and self._cf_left(att, "Grasp of Avarice", pb) and self._dist(att, tgt) <= 60:
            opts.append({"key": "avarice", "label": f"Grasp of Avarice (+1d6+{pb} necrotic, you heal it)", "detail": ""})
        self._race_offer_free(out, att, tgt, cur, opts)

    def _race_eligible(self, out: list, window: str, R: dict, att: Optional[dict], tgt: Optional[dict], ctx: dict):
        self._nf_eligible(out, window, R, att, tgt, ctx)                    # the later feats (newfeats.py)
        cur = R.get("cur") or {}
        if window == "on_hit" and att and tgt:
            self._race_on_hit(out, R, att, tgt)
        elif window == "damage" and tgt:
            total = sum(n for n, _t in cur.get("dmg") or [])
            if total <= 0:
                return
            for o in self.b["combatants"]:
                oc = self._sheet(o)
                if not oc or o.get("form") or not self._may_react(o) or (o is not tgt and (self._hostile(o, tgt) or not o.get("pos") or not tgt.get("pos"))):
                    continue
                pb, feats, opts = oc.proficiency_bonus, set(oc.d.get("feats") or []), []
                if o is tgt and oc.has_feature("Hadozee Dodge") and self._cf_left(o, "Hadozee Dodge", pb):
                    opts.append({"key": "hadozee_dodge", "label": f"Hadozee Dodge (-1d6+{pb})", "detail": ""})
                if "Righteous Heritor" in feats and (o is tgt or self._dist(o, tgt) <= 30) and self._cf_left(o, "Soothe Pain", pb):
                    opts.append({"key": "soothe_pain", "label": f"Soothe Pain (-1d10+{pb}" + (f" to {tgt['name']}'s damage)" if o is not tgt else ")"), "detail": ""})
                if o is tgt and "Guile of the Cloud Giant" in feats and R.get("mode") == "attack" and self._cf_left(o, "Cloudy Escape", pb) \
                        and self._cloudy_spot(o, R) is not None:
                    opts.append({"key": "cloudy_escape", "label": "Cloudy Escape (resist this damage, then teleport 30 ft)", "detail": ""})
                self._cf_offer(out, o, "reaction", opts, f"{tgt['name']} is about to take {total} damage" + (f" from {R['label']}" if R.get("label") else "")
                               + ". React?", None)
        elif window == "after_damage" and att and tgt and tgt is not att and self._alive(att) and self._alive(tgt):
            tc = self._sheet(tgt)
            if tc and not tgt.get("form") and "Fury of the Frost Giant" in (tc.d.get("feats") or []) and self._may_react(tgt) \
                    and R.get("mode") == "attack" and att.get("pos") and tgt.get("pos") and self._dist(att, tgt) <= 30 and self._sees(tgt, att) \
                    and self._cf_left(tgt, "Frigid Retaliation", tc.proficiency_bonus):
                self._cf_offer(out, tgt, "reaction", [{"key": "frigid", "label": f"Frigid Retaliation on {att['name']} (1d8+{tc.proficiency_bonus} cold, speed 0)",
                                                       "detail": ""}], f"{att['name']} hurt {tgt['name']}. Frigid Retaliation?", "after_damage")
        elif window in ("missed", "save_failed") and tgt:
            who = att if window == "missed" else tgt
            wc = self._sheet(who) if who else None
            if wc and not who.get("form") and wc.has_feature("Built for Success") and self._cf_left(who, "Built for Success", wc.proficiency_bonus):
                if window == "missed":
                    need = cur.get("ac", 0) + cur.get("ac_extra", 0) - cur.get("total", 0)
                    ok = 0 < need <= 4
                else:
                    ok = 0 < int((R.get("sv") or {}).get("dc") or 0) - int(cur.get("total") or 0) <= 4
                if ok:
                    self._cf_offer(out, who, "free", [{"key": "built_for_success", "label": "Built for Success (+1d4)", "detail": ""}],
                                   f"{who['name']} just failed. Add a d4?")

    def _cloudy_spot(self, c: dict, R: dict) -> Optional[list]:
        """A free tile within 30 ft, as far from the creatures hostile to `c` as possible."""
        if not c.get("pos"):
            return None
        foes = [o for o in self.b["combatants"] if self._hostile(c, o) and o.get("pos") and self._alive(o)]
        best, far = None, -1
        x0, y0 = c["pos"]
        for x in range(max(0, x0 - 6), x0 + 7):
            for y in range(max(0, y0 - 6), y0 + 7):
                if (x, y) != (x0, y0) and self._cf_landing(c, [x, y], 30) is None:
                    d = min([max(abs(x - o["pos"][0]), abs(y - o["pos"][1])) for o in foes] or [0])
                    if d > far:
                        best, far = [x, y], d
        return best

    def _race_react(self, window: str, R: dict, reactor: dict, fam: str, arg: str, ctx: dict) -> bool:
        if fam in NF_FAMILIES:
            return self._nf_react(window, R, reactor, fam, arg, ctx)         # the later feats (newfeats.py)
        cur = R.setdefault("cur", {})
        char = self._sheet(reactor)
        name = reactor["name"]
        att = self._find_or_none(ctx.get("attacker") or R.get("actor"))
        tgt = self._find_or_none(ctx.get("target")) or (self._find_or_none(R["targets"][R["ti"]]) if R.get("targets") and R.get("ti", 0) < len(R["targets"]) else None)

        def cut(n: int):
            left, after = n, []
            for d, t in cur.get("dmg") or []:
                take = min(d, left)
                left -= take
                after.append([d - take, t])
            cur["dmg"] = after

        if fam == "astral_spark":
            self._cf_use(reactor, "Astral Spark")
            self._once_per_turn(reactor, "astral_spark")
            cur.setdefault("bonus_parts", []).append([str(char.proficiency_bonus), "force"])
            self._line(R, f"{name}'s Astral Spark: +{char.proficiency_bonus} force", "Astral Spark")
            return True
        if fam == "hadozee_dodge":
            self._cf_use(reactor, "Hadozee Dodge")
            n = roll("1d6") + char.proficiency_bonus
            cut(n)
            self._line(R, f"{name} uses Hadozee Dodge: -{n} damage", "Hadozee Dodge")
            return True
        if fam == "soothe_pain":
            self._cf_use(reactor, "Soothe Pain")
            n = roll("1d10") + char.proficiency_bonus
            cut(n)
            self._line(R, f"{name} soothes the pain" + (f" of {tgt['name']}" if tgt and tgt is not reactor else "") + f": -{n} damage", "Soothe Pain")
            return True
        if fam == "cloudy_escape":
            self._cf_use(reactor, "Cloudy Escape")
            cur["dmg"] = [[d // 2, t] for d, t in cur.get("dmg") or []]
            spot = self._cloudy_spot(reactor, R)
            if spot:
                self._cf_teleport(reactor, spot)
            self._line(R, f"{name} slips into the clouds: resists the damage" + (f" and teleports to {self._tile_label(spot)}" if spot else ""), "Cloudy Escape")
            return True
        if fam == "frigid" and att:
            self._cf_use(reactor, "Frigid Retaliation")
            pb = char.proficiency_bonus
            self._stack().append(self._strike(reactor, "Frigid Retaliation", [att["id"]], mode="save", magical=True,
                                              sv={"ab": "con", "dc": 8 + pb + feat_mod(char, "Fury of the Frost Giant"), "half": False,
                                                  "mods": {"speed_set": 0}, "until": "caster_end_next"}, parts=[[f"1d8+{pb}", "cold"]]))
            return True
        if fam in ("giant_strike", "demoralizing", "stasis_strike", "avarice"):
            self._race_hit_rider(R, reactor, char, fam, tgt, cur)
            return True
        if fam == "built_for_success":
            self._cf_use(reactor, "Built for Success")
            n = roll("1d4")
            cur["total"] = int(cur.get("total") or 0) + n
            if window == "save_failed":
                cur["ok"] = cur["total"] >= int((R.get("sv") or {}).get("dc") or 0)
            self._line(R, f"{name}'s Built for Success: +{n} → {cur['total']}", "Built for Success")
            return True
        return False

    def _race_hit_rider(self, R: dict, reactor: dict, char, fam: str, tgt: Optional[dict], cur: dict):
        """Strike of the Giants, Demoralizing Strike, Stasis Strike, Grasp of Avarice: what an on-hit choice adds."""
        name, pb = reactor["name"], char.proficiency_bonus
        self._once_per_turn(reactor, fam)
        extra = cur.setdefault("bonus_parts", [])
        if tgt is None:
            return
        if fam == "giant_strike":
            kind = CF.is_on(char, "strike_giants") or "Cloud"
            dc = 8 + pb + feat_mod(char, "Strike of the Giants")
            wtype = ((R.get("atk") or {}).get("parts") or [["", "slashing"]])[0][1] or "slashing"
            dice, dtype = {"Cloud": ("1d4", "thunder"), "Fire": ("1d10", "fire"), "Frost": ("1d6", "cold"), "Hill": ("1d6", wtype), "Stone": ("1d6", "force")}[kind]
            extra.append([dice, dtype])
            save = {"Cloud": "wis", "Frost": "con", "Hill": "str"}.get(kind)
            line = f"{name}'s {kind} Strike: +{dice} {dtype}"
            if save:
                res = self._saving_throw(tgt, save, dc, label=f"{kind} Strike")
                if not res["ok"]:
                    if kind == "Hill":
                        self._cond(tgt, "Prone", True)
                        line += f"; {tgt['name']} is knocked prone"
                    elif kind == "Frost":
                        self._effect_on(tgt, "Frost Strike", [], None, None, None, None, name, {"speed_set": 0}, None, reactor["id"], until={"start": reactor["id"]})
                        line += f"; {tgt['name']}'s speed drops to 0"
                    else:
                        line += f"; {tgt['name']} loses sight of {name}"
            self._line(R, line, f"{kind} Strike")
        elif fam == "demoralizing":
            self._cf_use(reactor, "Demoralizing Strike")
            res = self._saving_throw(tgt, "wis", 8 + pb + feat_mod(char, "Knight of the Sword"), label="Demoralizing Strike")
            if not res["ok"]:
                self._effect_on(tgt, "Demoralizing Strike", ["Frightened"], None, None, None, None, name, {}, None, reactor["id"],
                                until={"end": reactor["id"], "skip": 1})
                self._line(R, f"{tgt['name']} is frightened of {name} (Demoralizing Strike)", "Demoralizing Strike")
            else:
                self._effect_on(tgt, "Demoralized", [], None, None, None, None, name, {"attacks_with": "dis", "once": True}, None, reactor["id"],
                                until={"end": tgt["id"], "skip": 1})
                self._line(R, f"{tgt['name']} resists but is shaken: disadvantage on its next attack (Demoralizing Strike)", "Demoralizing Strike")
        elif fam == "stasis_strike":
            self._cf_use(reactor, "Stasis Strike")
            extra.append(["1d8", "force"])
            res = self._saving_throw(tgt, "wis", 8 + pb + feat_mod(char, "Agent of Order"), label="Stasis Strike")
            if not res["ok"]:
                self._effect_on(tgt, "Stasis Strike", ["Restrained"], None, None, None, None, name, {}, None, reactor["id"], until={"start": reactor["id"]})
            self._line(R, f"{name}'s Stasis Strike: +1d8 force" + ("" if res["ok"] else f"; {tgt['name']} is bound by spectral chains"), "Stasis Strike")
        elif fam == "avarice":
            self._cf_use(reactor, "Grasp of Avarice")
            n = roll("1d6") + pb
            self._line(R, f"{name}'s Grasp of Avarice: " + self._deal(tgt, [[n, "necrotic"]], by=reactor, label="Grasp of Avarice"), "Grasp of Avarice")
            self._heal(reactor, n)
