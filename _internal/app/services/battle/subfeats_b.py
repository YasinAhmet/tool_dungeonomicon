"""Subclass features, batch B (the bar's items are added to features.ACTIVE below; subfeats.py hands over to this):

    Ranger, Monster Slayer   Hunter's Sense, Supernatural Defense (+1d6 to saves against the prey), Magic-User's Nemesis (a reaction
                             to a spell being cast), Slayer's Counter (a weapon attack before a save the prey forces)
    Cleric, Twilight         Vigilant Blessing (advantage on the next initiative roll), Eyes of Night shared with allies,
                             Twilight Shroud (half cover in the sanctuary: profile._cover_between)
    Druid, Spores            Fungal Infestation (a corpse rises as a zombie), Spreading Spores (a lasting cube)
    Paladin, Vengeance       Relentless Avenger (half the speed after an opportunity attack hits), Soul of Vengeance (a reaction
                             to an attack by the creature under the Vow of Enmity)
    Warlock, Fathomless      Guardian Coil (a reaction that cuts the damage near the tentacle)
    Monk, Open Hand          Tranquility (a Sanctuary on the monk when the battle begins)
"""
from typing import List, Optional

from ...rules import spellcasting as SC
from ...rules.monsters import bestiary
from ..common import ServiceError
from . import conditions as K
from . import features as F
from . import geometry as G
from .resolve import roll
from .standard import SIZES

SUB_B_FAMILIES = {"slayers_counter": "Slayer's Counter", "nemesis": "Magic-User's Nemesis", "soul_vengeance": "Soul of Vengeance",
                  "guardian_coil": "Guardian Coil", "spectral_defense": "Spectral Defense", "opportunist": "Opportunist",
                  "unerring_accuracy": "Unerring Accuracy", "hurl_hell": "Hurl Through Hell"}
SUB_B_FREE = {"unerring_accuracy", "hurl_hell"}
ZOMBIE = "Zombie"
CANNON = "Eldritch Cannon"
CANNONS = ["Flamethrower", "Force Ballista", "Protector"]
ALL_CONDITIONS = ["Blinded", "Charmed", "Deafened", "Frightened", "Grappled", "Incapacitated", "Paralyzed", "Petrified", "Poisoned", "Prone",
                  "Restrained", "Stunned", "Unconscious"]
SPORES = "Spreading Spores"


def _sub_b_active() -> dict:
    slayer = lambda n: (lambda c: F.sub_at(c, "Ranger", "Monster Slayer", n))
    spores = lambda n: (lambda c: F.sub_at(c, "Druid", "Circle of Spores", n))
    twilight = lambda c: F.sub_at(c, "Cleric", "Twilight Domain", 1)
    art = lambda n: (lambda c: F.sub_at(c, "Artificer", "Artillerist", n))
    cannon_kinds = lambda c: [{"value": k, "label": k} for k in CANNONS]
    pair = lambda key, base, die_text: {key + "_die": dict(base, name=base["name"] + " (Psionic Energy die)", per=None, uses=None, per_name=None,
                                                          text=die_text)}
    psi = lambda n: (lambda c: F.sub_at(c, "Fighter", "Psi Warrior", n))
    leap = {"name": "Psi-Powered Leap", "cost": "bonus", "resource": None, "per": "short", "uses": 1, "target": "self", "needs": psi(7),
            "text": "A flying speed of twice your walking speed until the end of the turn. Once a short or long rest."}
    bulwark = {"name": "Bulwark of Force", "cost": "bonus", "resource": None, "per": "long", "uses": 1, "target": "self", "needs": psi(15),
               "text": "Up to your Intelligence modifier of creatures you can see within 30 ft (you too) are protected by half cover for a minute. "
                       "Once a long rest."}
    veil = {"name": "Psychic Veil", "cost": "action", "resource": None, "per": "long", "uses": 1, "target": "self",
            "needs": lambda c: F.sub_at(c, "Rogue", "Soulknife", 13),
            "text": "Become invisible for an hour; it ends when you deal damage or force a save. Once a long rest."}
    return {
        **pair("psi_leap", leap, "Take Psi-Powered Leap again by expending a Psionic Energy die."), "psi_leap": leap,
        **pair("bulwark_force", bulwark, "Take Bulwark of Force again by expending a Psionic Energy die."), "bulwark_force": bulwark,
        **pair("psychic_veil", veil, "Use Psychic Veil again by expending a Psionic Energy die."), "psychic_veil": veil,
        # ---- Ranger: Swarmkeeper
        "writhing_tide": {"name": "Writhing Tide", "cost": "bonus", "resource": None, "per": "long", "uses": lambda c: c.proficiency_bonus, "target": "self",
                          "needs": lambda c: F.sub_at(c, "Ranger", "Swarmkeeper", 7),
                          "text": "A flying speed of 10 ft and hovering for a minute (proficiency bonus uses a long rest)."},
        # ---- Warlock: Undying, Archfey, Undead
        "indestructible_life": {"name": "Indestructible Life", "cost": "bonus", "resource": None, "per": "short", "uses": 1, "target": "self",
                                "needs": lambda c: F.sub_at(c, "Warlock", "The Undying", 14),
                                "text": "Regain 1d8 + your warlock level hit points. Once a short or long rest."},
        "dark_delirium": {"name": "Dark Delirium", "cost": "action", "resource": None, "per": "short", "uses": 1, "target": "enemy", "range": 60,
                          "options": lambda c: [{"value": "Charmed", "label": "Charmed"}, {"value": "Frightened", "label": "Frightened"}],
                          "needs": lambda c: F.sub_at(c, "Warlock", "The Archfey", 14),
                          "text": "A creature you can see within 60 ft makes a Wisdom save or is charmed or frightened by you for a minute (it ends if it takes damage)."},
        "form_of_dread": {"name": "Form of Dread", "cost": "bonus", "resource": None, "per": "long", "uses": lambda c: c.proficiency_bonus, "target": "self",
                          "needs": lambda c: F.sub_at(c, "Warlock", "The Undead", 1),
                          "text": "For a minute: 1d10 + warlock level temporary hit points, immunity to frightened, and once a turn a hit forces a Wisdom "
                                  "save or the target is frightened until the end of your next turn."},
        # ---- Monk: Way of the Long Death
        "hour_reaping": {"name": "Hour of Reaping", "cost": "action", "resource": None, "target": "self", "needs": lambda c: F.sub_at(c, "Monk", "Way of the Long Death", 6),
                         "text": "Each creature within 30 ft that can see you makes a Wisdom save (your ki DC) or is frightened until the end of your next turn."},
        # ---- Paladin: Crown, Oathbreaker
        "turn_the_tide": {"name": "Turn the Tide", "cost": "bonus", "resource": "Channel Divinity (Paladin)", "target": "self",
                          "needs": lambda c: F.sub_at(c, "Paladin", "Oath of the Crown", 3),
                          "text": "Creatures of your choice within 30 ft with half their hit points or fewer regain 1d6 + Charisma modifier."},
        "dreadful_aspect": {"name": "Dreadful Aspect", "cost": "action", "resource": "Channel Divinity (Paladin)", "target": "self",
                            "needs": lambda c: F.sub_at(c, "Paladin", "Oathbreaker", 3),
                            "text": "Each foe within 30 ft that can see you makes a Wisdom save or is frightened of you for a minute."},
        "combat_shape_heal": {"name": "Combat Wild Shape: heal", "cost": "bonus", "resource": None, "target": "self",
                              "needs": lambda c: F.sub_at(c, "Druid", "Circle of the Moon", 2),
                              "options": lambda c: [{"value": str(k), "label": f"Level {k} slot ({k}d8)"} for k in sorted(
                                  int(k) for k, v in SC.slots_remaining(c).items() if str(k).isdigit() and v > 0)],
                              "text": "While in a beast shape: expend a spell slot to regain 1d8 hit points per level of the slot."},
        "warrior_of_the_gods": {"name": "Warrior of the Gods", "cost": "bonus", "resource": None, "per": "long", "target": "self",
                                "uses": lambda c: 4 if c.class_level("Barbarian") < 6 else 5 if c.class_level("Barbarian") < 12 else 6 if c.class_level("Barbarian") < 17 else 7,
                                "needs": lambda c: F.sub_at(c, "Barbarian", "Path of the Zealot", 3),
                                "options": lambda c: [{"value": str(n), "label": f"{n}d12"} for n in range(1, 8)],
                                "text": "Spend d12s from a pool (4, 5 at 6th level, 6 at 12th, 7 at 17th): roll them and regain that many hit points "
                                        "(a long rest refills the pool)."},
        "control_undead": {"name": "Control Undead", "cost": "action", "resource": "Channel Divinity (Paladin)", "target": "enemy", "range": 30,
                           "needs": lambda c: F.sub_at(c, "Paladin", "Oathbreaker", 3),
                           "text": "An undead within 30 ft whose challenge rating is below your paladin level makes a Wisdom save or obeys you for 24 hours "
                                   "(or until you use this again)."},
        # ---- Ranger: Monster Slayer
        "hunters_sense": {"name": "Hunter's Sense", "cost": "action", "resource": None, "per": "long", "target": "enemy", "range": 60,
                          "uses": lambda c: max(1, c.mod("wis")), "needs": slayer(3),
                          "text": "Choose a creature you can see within 60 ft: you learn its damage immunities, resistances and vulnerabilities "
                                  "(Wisdom modifier uses a long rest)."},
        # ---- Cleric: Twilight
        "vigilant_blessing": {"name": "Vigilant Blessing", "cost": "action", "resource": None, "target": "ally", "range": 5, "needs": twilight,
                              "text": "Touch a creature (or yourself): it has advantage on the next initiative roll it makes. It ends with the roll, "
                                      "or if you use this again."},
        "eyes_share": {"name": "Eyes of Night: share", "cost": "action", "resource": None, "per": "long", "per_name": "Eyes of Night", "uses": 1,
                       "target": "self", "needs": twilight,
                       "text": "Share your 300 ft darkvision for an hour with willing creatures within 10 ft that you can see (up to your Wisdom "
                               "modifier of them)."},
        "eyes_share_slot": {"name": "Eyes of Night: share again (spell slot)", "cost": "action", "resource": None, "target": "self", "needs": twilight,
                            "text": "Share your darkvision again before a rest by spending a spell slot of any level."},
        # ---- Druid: Circle of Spores
        "fungal_infestation": {"name": "Fungal Infestation", "cost": "reaction", "resource": None, "per": "long", "target": "none",
                               "uses": lambda c: max(1, c.mod("wis")), "needs": spores(6),
                               "text": "A Small or Medium beast or humanoid that died within 10 ft of you stands up as a zombie with 1 hit point. Its "
                                       "turn comes right after yours; it takes only the Attack action (one melee attack). The nearest fitting "
                                       "corpse is used."},
        "spreading_spores": {"name": "Spreading Spores", "cost": "bonus", "resource": None, "target": "point", "range": 30, "needs": spores(10),
                             "text": "While Symbiotic Entity lasts: a 10-ft cube of spores up to 30 ft away for a minute. A creature that enters it or "
                                     "starts its turn there takes your Halo of Spores damage unless it passes a Constitution save. You can't use Halo of "
                                     "Spores while it lasts."},
        # ---- Paladin: Oath of Vengeance
        "relentless_avenger": {"name": "Relentless Avenger", "cost": "free", "resource": None, "target": "point", "range": 60,
                               "needs": lambda c: F.sub_at(c, "Paladin", "Oath of Vengeance", 7),
                               "text": "Right after an opportunity attack hits: move up to half your speed without provoking opportunity attacks."},
        # ---- Artificer: Artillerist
        "eldritch_cannon": {"name": "Eldritch Cannon", "cost": "action", "resource": None, "per": "long", "per_name": "Eldritch Cannon", "uses": 1,
                            "target": "point", "range": 5, "needs": art(3), "options": cannon_kinds,
                            "text": "Create a Small cannon in an unoccupied space within 5 ft (AC 18, 5 hit points per artificer level, a minute): a "
                                    "Flamethrower, a Force Ballista or a Protector. One at a time; once per long rest."},
        "eldritch_cannon_slot": {"name": "Eldritch Cannon (spell slot)", "cost": "action", "resource": None, "target": "point", "range": 5, "needs": art(3),
                                 "options": cannon_kinds,
                                 "text": "Create the cannon again by expending a spell slot of any level (the old cannon is gone)."},
        "cannon_fire": {"name": "Cannon: fire", "cost": "bonus", "resource": None, "target": "enemy", "range": 120, "needs": art(3),
                        "text": "Command your cannon: a Flamethrower breathes a 15-ft cone (Dexterity save, 2d8 fire); a Force Ballista makes a ranged spell "
                                "attack from its space (120 ft, 2d8 force). Explosive Cannon adds 1d8."},
        "cannon_protect": {"name": "Cannon: protect", "cost": "bonus", "resource": None, "target": "self", "needs": art(3),
                           "text": "Command your Protector: everyone friendly within 10 ft of it gains 1d8 + Intelligence modifier temporary hit points."},
        "cannon_detonate": {"name": "Detonate the cannon", "cost": "action", "resource": None, "target": "self", "needs": art(9),
                            "text": "Destroy your cannon: creatures within 20 ft of it make a Dexterity save or take 3d8 force damage (half on a success)."},
        # ---- Monk: Way of the Kensei
        "sharpen_blade": {"name": "Sharpen the Blade", "cost": "bonus", "resource": None, "target": "self",
                          "needs": lambda c: F.sub_at(c, "Monk", "Way of the Kensei", 11),
                          "options": lambda c: [{"value": str(n), "label": f"{n} ki: +{n} to attack and damage"} for n in (1, 2, 3)],
                          "text": "Spend up to 3 ki: a bonus to attack and damage rolls with your weapons equal to the ki, for a minute or until you use this again."},
        # ---- Rogue: Arcane Trickster
        "versatile_trickster": {"name": "Versatile Trickster", "cost": "bonus", "resource": None, "target": "enemy", "range": 35,
                                "needs": lambda c: F.sub_at(c, "Rogue", "Arcane Trickster", 13),
                                "text": "Distract a creature with your mage hand: advantage on attack rolls against it until the end of the turn."},
        # ---- Wizard: School of Evocation
        "overchannel": {"name": "Overchannel", "cost": "free", "resource": None, "per": "long", "uses": 99, "target": "self",
                        "needs": lambda c: F.sub_at(c, "Wizard", "School of Evocation", 14),
                        "text": "Your next wizard spell of 1st to 5th level that deals damage deals maximum damage. Used again before a long rest, you take "
                                "2d12 necrotic per spell level (+1d12 for each use after that)."},
    }


class SubFeatsBMixin:
    # ------------------------------------------------------------------ the bar
    def _subb_why(self, c: dict, char, key: str, f: dict, tgt: Optional[dict], option, menu: bool, point) -> Optional[str]:
        """Why one of these features can't be used now (None: it can, or it isn't one of these)."""
        if key == "hunters_sense" and not menu and (tgt is None or tgt is c):
            return "Pick a creature to study first."
        if key == "combat_shape_heal":
            if not c.get("form"):
                return "Only while in a beast shape"
            if not self._subb_slot(char):
                return "No spell slot left"
        if key == "control_undead" and not menu:
            m = self._monster(tgt) if tgt is not None else None
            if tgt is None or tgt is c or not m or not str(m.get("type") or "").lower().startswith("undead"):
                return "Pick an undead creature."
            if float(m.get("cr_num") or 0) >= char.class_level("Paladin"):
                return f"{tgt['name']}'s challenge rating is too high: it is immune."
        if key == "eyes_share_slot":
            if self._cf_left(c, "Eyes of Night", 1) > 0:
                return "Share it free of charge first"
            if not self._subb_slot(char):
                return "No spell slot left"
        if key == "fungal_infestation" and self._fi_corpse(c) is None:
            return "No Small or Medium beast or humanoid corpse within 10 ft"
        if key == "spreading_spores":
            if not self._fx(c, "symbiotic"):
                return "Only while Symbiotic Entity lasts"
            if not menu:
                if not point or not c.get("pos"):
                    return "Pick the centre of the cube."
                x, y = int(point[0]), int(point[1])
                if G.distance_ft(c["pos"], c.get("span") or 1, [x, y], 1) > 30:
                    return "Too far (up to 30 ft)"
        if key in ("eldritch_cannon", "eldritch_cannon_slot"):
            if key == "eldritch_cannon_slot" and not self._subb_slot(char):
                return "No spell slot left"
            if not menu:
                if option not in CANNONS:
                    return "Pick the kind of cannon."
                if not point or not c.get("pos"):
                    return "Pick where it stands."
                x, y = int(point[0]), int(point[1])
                if G.distance_ft(c["pos"], c.get("span") or 1, [x, y], 1) > 5:
                    return "Too far (up to 5 ft)"
                if not self._tile_ok({"id": -1, "span": 1}, x, y):
                    return "That tile is taken or off the map."
        if key in ("cannon_fire", "cannon_protect", "cannon_detonate"):
            toks = self._cannons(c)
            tok = toks[0] if toks else None
            if tok is None:
                return "No cannon on the map"
            if key == "cannon_fire":
                if all(t["cannon"] == "Protector" for t in toks):
                    return "Your cannon is a Protector"
                if not menu:
                    if tgt is None or not self._hostile(c, tgt):
                        return "Pick a foe for the cannon."
                    if not any(t["cannon"] != "Protector" and self._dist(t, tgt) <= (15 if t["cannon"] == "Flamethrower" else 120) for t in toks):
                        return "Out of the cannon's range (flamethrower 15 ft, ballista 120 ft)"
            if key == "cannon_protect" and all(t["cannon"] != "Protector" for t in toks):
                return "Your cannon is not a Protector"
        if key in ("psi_leap_die", "bulwark_force_die", "psychic_veil_die") and not self._psi_left(c, char):
            return "No Psionic Energy die left"
        if key == "dark_delirium" and not menu and (tgt is None or tgt is c or not self._hostile(c, tgt)):
            return "Pick a foe first."
        if key == "form_of_dread" and any(e["name"] == "Form of Dread" for e in c.get("effects") or []):
            return "Already active"
        if key == "sharpen_blade" and self._resource_left(c, "Ki Points") < (int(option) if str(option or "").isdigit() else 1):
            return "Not enough ki"
        if key == "versatile_trickster":
            from ...rules import spellcasting as SC
            if not any(sp["name"] == "Mage Hand" for sp in SC.spell_known_or_prepared(char)):
                return "You need the mage hand spell"
            if not menu and (tgt is None or tgt is c or not self._hostile(c, tgt)):
                return "Pick a foe for the hand to distract."
        if key == "relentless_avenger":
            if (c.get("relentless") or [None, None]) != [self.b.get("round"), self.b.get("turn")]:
                return "Only right after your opportunity attack hits"
            if not menu:
                half = self._speed(c) // 2
                if not point or not c.get("pos"):
                    return "Pick where to move."
                x, y = int(point[0]), int(point[1])
                if G.distance_ft(c["pos"], c.get("span") or 1, [x, y], c.get("span") or 1) > half:
                    return f"Too far (up to {half} ft: half your speed)"
                if not self._tile_ok(c, x, y):
                    return "That tile is taken or off the map."
        return None

    def _psi_left(self, c: dict, char) -> int:
        """Psionic Energy dice left (a Soulknife's, or a Psi Warrior's 2 x proficiency)."""
        top = F.psionic_dice(char) if F.sub_at(char, "Rogue", "Soulknife", 3) else 2 * char.proficiency_bonus
        return self._cf_left(c, "Psionic Energy", top)

    @staticmethod
    def _subb_slot(char) -> Optional[int]:
        from ...rules import spellcasting as SC
        left = SC.slots_remaining(char)
        levels = sorted(int(k) for k, v in left.items() if k != SC.PACT_KEY and v > 0)
        return levels[0] if levels else None

    def _subb_feature(self, c: dict, char, key: str, f: dict, tgt: Optional[dict], option, point) -> Optional[str]:
        """Plays one of these features (None: not one of these, or it only noted something)."""
        name = c["name"]
        if key in ("tentacle", "tentacle_strike") and tgt is not None and tgt.get("pos"):
            c["tentacle_at"] = list(tgt["pos"])                  # where Guardian Coil finds the tentacle
            return None
        if key == "hunters_sense":
            d = self._defenses(tgt)
            bits = []
            for label, plain, nonmagical in (("immune to", "immune", "nonmagical_immune"), ("resistant to", "resist", "nonmagical_resist")):
                kinds = sorted(d[plain]) + [f"nonmagical {t}" for t in sorted(d[nonmagical])]
                if kinds:
                    bits.append(f"{label} {', '.join(kinds)}")
            if d["vuln"]:
                bits.append(f"vulnerable to {', '.join(sorted(d['vuln']))}")
            return self._out(f"{name} studies {tgt['name']} (Hunter's Sense): " + ("; ".join(bits) if bits else "no damage immunities, resistances or vulnerabilities"))
        if key == "vigilant_blessing":
            who = tgt or c
            for o in self.b["combatants"]:
                for e in [e for e in o.get("effects") or [] if e["name"] == "Vigilant Blessing" and e.get("source_id") == c["id"]]:
                    self._effect_off(o, e, "a new blessing")
            self._effect_on(who, "Vigilant Blessing", [], None, None, None, None, name, {"init_adv": True}, None, c["id"])
            return self._out(f"{name} touches {who['name'] if who is not c else 'themselves'}: advantage on the next initiative roll (Vigilant Blessing)")
        if key in ("eyes_share", "eyes_share_slot"):
            if key == "eyes_share_slot":
                lvl = self._subb_slot(char)
                used = char.d["slots_used"]
                used[str(lvl)] = int(used.get(str(lvl)) or 0) + 1
                char.save()
            near = [o for o in self.b["combatants"] if o is not c and not self._hostile(c, o) and self._alive(o) and not self._is_out(o)
                    and self._within(c, o, 10) and self._sees(c, o)][:max(1, char.mod("wis"))]
            for o in near:
                self._effect_on(o, "Eyes of Night (shared)", [], None, None, None, 600, name, {"senses": {"darkvision": 300}}, None, c["id"])
            return self._out(f"{name} shares the Eyes of Night with " + (", ".join(o["name"] for o in near) if near else "nobody in reach"))
        if key.endswith("_die") and key[:-4] in ("psi_leap", "bulwark_force", "psychic_veil"):
            self._cf_use(c, "Psionic Energy")
            key = key[:-4]
        if key == "psi_leap":
            self._effect_on(c, "Psi-Powered Leap", [], None, None, None, None, name, {"fly": 2 * char.speed}, None, c["id"], until={"end": c["id"], "skip": 0})
            return self._out(f"{name} leaps on a psionic current: a flying speed of {2 * char.speed} ft until the end of the turn")
        if key == "bulwark_force":
            near = [c] + [o for o in self.b["combatants"] if o is not c and o.get("pos") and self._alive(o) and self._within(c, o, 30) and self._sees(c, o)
                          and not self._hostile(c, o)]
            near = near[:max(1, char.mod("int"))]
            for o in near:
                self._effect_on(o, "Bulwark of Force", [], None, None, None, 10, name, {"twilight_cover": True}, None, c["id"])
            return self._out(f"{name} raises telekinetic cover over " + ", ".join(o["name"] for o in near) + " (Bulwark of Force)")
        if key == "psychic_veil":
            self._effect_on(c, "Psychic Veil", ["Invisible"], None, None, None, 600, name, {"ends_on": ["attack", "cast"]}, None, c["id"])
            return self._out(f"{name} weaves a veil of psychic static: invisible (Psychic Veil)")
        if key == "writhing_tide":
            self._effect_on(c, "Writhing Tide", [], None, None, None, 10, name, {"fly": 10}, None, c["id"])
            return self._out(f"{name}'s swarm lifts them up: a flying speed of 10 ft (Writhing Tide)")
        if key == "indestructible_life":
            n = roll("1d8") + char.class_level("Warlock")
            self._heal(c, n)
            return self._out(f"{name} draws on the Undying: +{n} HP (Indestructible Life)")
        if key == "dark_delirium":
            cond = option if option in ("Charmed", "Frightened") else "Frightened"
            return self._run_r(self._strike(c, "Dark Delirium", [tgt["id"]], mode="save", magical=True, parts=[],
                                            sv={"ab": "wis", "dc": self._spell_dc(c), "half": False, "conds": [cond], "rounds": 10, "ends_on": ["damage"]}))
        if key == "form_of_dread":
            n = roll("1d10") + char.class_level("Warlock")
            self._give_temp(c, n)
            self._effect_on(c, "Form of Dread", [], None, None, None, 10, name, {"immune_cond": ["Frightened"]}, None, c["id"])
            return self._out(f"{name} takes on a dreadful form: {n} temporary HP, immune to fear (Form of Dread)")
        if key == "hour_reaping":
            ids = [o["id"] for o in self._cf_hostiles(c, 30) if self._sees(o, c)]
            return self._run_r(self._strike(c, "Hour of Reaping", ids, mode="save", parts=[],
                                            sv={"ab": "wis", "dc": F.ki_dc(char), "half": False, "conds": ["Frightened"], "rounds": 2}))
        if key == "combat_shape_heal":
            lvl = int(option) if str(option or "").isdigit() else self._subb_slot(char)
            if not lvl or int(SC.slots_remaining(char).get(str(lvl)) or 0) <= 0:
                raise ServiceError("No spell slot of that level left.")
            used = char.d["slots_used"]
            used[str(lvl)] = int(used.get(str(lvl)) or 0) + 1
            char.save()
            n = roll(f"{lvl}d8")
            form = c["form"]
            form["hp"] = min(form.get("max_hp") or form["hp"], form["hp"] + n)
            self._vfx("heal", id=c["id"], amt=n)
            return self._out(f"{name} feeds a level {lvl} slot to the beast shape: +{n} HP ({form['hp']}/{form.get('max_hp')})")
        if key == "warrior_of_the_gods":
            left = (F.per_left(f, char) or 0) + 1                # one die was counted already
            n = max(1, min(int(option) if str(option or "").isdigit() else 1, left))
            if n > 1:
                k = F.per_key(f, char)
                char.d["resources"][k] = int(char.d["resources"].get(k) or 0) + n - 1
                char.save()
            hp = roll(f"{n}d12")
            self._heal(c, hp)
            return self._out(f"{name} calls on the gods: +{hp} HP ({n}d12, {left - n} dice left)")
        if key == "control_undead":
            for o in self.b["combatants"]:                      # "until you use this Channel Divinity option again": the old thrall goes free
                for e in [e for e in o.get("effects") or [] if e["name"] == "Control Undead" and e.get("source_id") == c["id"]]:
                    self._effect_off(o, e, "a new command")
            return self._run_r(self._strike(c, "Control Undead", [tgt["id"]], mode="save", magical=True, parts=[],
                                            sv={"ab": "wis", "dc": 8 + char.proficiency_bonus + char.mod("cha"), "half": False, "conds": ["Charmed"],
                                                "rounds": 14400, "mods": {"dominated": True}, "note": "obeys the paladin"}))
        if key == "dreadful_aspect":
            ids = [o["id"] for o in self._cf_hostiles(c, 30) if self._sees(o, c)]
            return self._run_r(self._strike(c, "Dreadful Aspect", ids, mode="save", magical=True, parts=[],
                                            sv={"ab": "wis", "dc": 8 + char.proficiency_bonus + char.mod("cha"), "half": False, "conds": ["Frightened"], "rounds": 10}))
        if key == "turn_the_tide":
            n = roll("1d6") + max(1, char.mod("cha"))
            hurt = [o for o in self.b["combatants"] if o.get("pos") and self._alive(o) and not self._hostile(c, o) and self._within(c, o, 30)
                    and not o.get("conjured") and self._hp_of(o) * 2 <= self._max_hp(o)]
            for o in hurt:
                self._heal(o, n)
            return self._out(f"{name} rallies the wounded (Turn the Tide): +{n} HP for " + (", ".join(o["name"] for o in hurt) or "nobody"))
        if key in ("eldritch_cannon", "eldritch_cannon_slot"):
            if key == "eldritch_cannon_slot":
                lvl = self._subb_slot(char)
                used = char.d["slots_used"]
                used[str(lvl)] = int(used.get(str(lvl)) or 0) + 1
                char.save()
            return self._cannon_make(c, char, option, point)
        if key in ("cannon_fire", "cannon_protect", "cannon_detonate"):
            return self._cannon_command(c, char, key, tgt)
        if key == "sharpen_blade":
            n = max(1, min(3, int(option))) if str(option or "").isdigit() else 1
            self._use_resource(c, "Ki Points", n)
            for e in [e for e in c.get("effects") or [] if e["name"] == "Sharpen the Blade"]:
                self._effect_off(c, e, "sharpened again")
            self._effect_on(c, "Sharpen the Blade", [], None, None, None, 10, name, {"weapon_attack": n, "dmg": (n, "")}, None, c["id"])
            return self._out(f"{name} sharpens their weapons with ki: +{n} to attack and damage for a minute")
        if key == "versatile_trickster":
            self._effect_on(c, "Versatile Trickster", [], None, None, None, None, name, {"adv_vs": tgt["id"]}, None, c["id"], until={"end": c["id"], "skip": 0})
            return self._out(f"{name}'s mage hand distracts {tgt['name']}: advantage on attacks against it this turn")
        if key == "overchannel":
            prior = int(char.d["resources"].get("feature:Overchannel") or 1) - 1      # the bar counted this use already
            for e in [e for e in c.get("effects") or [] if e["name"] == "Overchannel"]:
                self._effect_off(c, e, "a new Overchannel")
            self._effect_on(c, "Overchannel", [], None, None, None, None, name, {"overchannel": prior}, None, c["id"])
            return self._out(f"{name} gathers power: the next wizard spell (level 1-5) deals maximum damage"
                             + (f" ({prior + 1}d12 necrotic per spell level will follow)" if prior else ""))
        if key == "fungal_infestation":
            return self._fi_raise(c, char, self._fi_corpse(c))
        if key == "spreading_spores":
            return self._spores(c, char, point)
        if key == "relentless_avenger":
            self._cf_teleport(c, point)
            c.pop("relentless", None)
            return self._out(f"{name} presses the attack, moving to {self._tile_label(c['pos'])} (Relentless Avenger: no opportunity attacks)")
        return None

    # ---- Artillerist
    def _cannon_all(self, c: dict) -> List[dict]:
        return [o for o in self.b["combatants"] if (o.get("conjured") or {}).get("spell") == CANNON and o["conjured"].get("owner") == c["id"]]

    def _cannon_of(self, c: dict) -> Optional[dict]:
        return next((o for o in self._cannon_all(c) if o["hp"] > 0 and o.get("pos")), None)

    def _cannon_end(self, tok: dict, line: str):
        self._vfx_unsummon(tok)
        if tok in self.b["combatants"]:
            self._take_out(tok)
        self._say(line)

    def _cannons(self, c: dict) -> List[dict]:
        return [o for o in self._cannon_all(c) if o["hp"] > 0 and o.get("pos")]

    def _cannon_make(self, c: dict, char, kind: str, point) -> str:
        limit = 2 if F.sub_at(char, "Artificer", "Artillerist", 15) else 1         # Fortified Position: two cannons at once
        olds = self._cannon_all(c)
        while len(olds) >= limit:
            self._cannon_end(olds.pop(0), f"{c['name']}'s old cannon is dismantled")
        lv = char.class_level("Artificer")
        sp = {"name": CANNON, "duration": "1 hour", "level": 1, "classes": ["Artificer"]}
        tdef = {"name": kind, "move": 0, "hp": 5 * lv, "ac": 18, "span": 1}
        tok = self._conjure_token(c, sp, tdef, {"point": [int(point[0]), int(point[1])], "attack_bonus": char.proficiency_bonus + char.mod("int")}, [], None)
        tok["cannon"] = kind
        self._effect_on(tok, "Eldritch Cannon", [], None, None, None, None, c["name"], {"immune": ["poison", "psychic"], "immune_cond": list(ALL_CONDITIONS)}, None, c["id"])
        if F.sub_at(char, "Artificer", "Artillerist", 15):      # Fortified Position: you and your allies within 10 ft have cover
            self._effect_on(tok, "Fortified Position", [], None, None, None, None, c["name"], {"twilight_cover": True, "aura_ft": 10}, None, c["id"])
        return self._out(f"{c['name']} sets up an eldritch cannon, a {kind.lower()}, at {self._tile_label(tok['pos'])} (AC 18, {5 * lv} HP)")

    def _cannon_command(self, c: dict, char, key: str, tgt: Optional[dict]) -> str:
        """One bonus action commands every cannon (Fortified Position: both); a detonation takes the nearest one."""
        toks = self._cannons(c)
        if key == "cannon_detonate":
            return self._cannon_command_one(c, char, key, tgt, min(toks, key=lambda t: self._dist(c, t) if c.get("pos") else 0))
        outs = []
        for tok in toks:
            if key == "cannon_protect" and tok["cannon"] != "Protector" or key == "cannon_fire" and (
                    tok["cannon"] == "Protector" or tgt is None or self._dist(tok, tgt) > (15 if tok["cannon"] == "Flamethrower" else 120)):
                continue
            outs.append(self._cannon_command_one(c, char, key, tgt, tok))
        return "; ".join(o for o in outs if o)

    def _cannon_command_one(self, c: dict, char, key: str, tgt: Optional[dict], tok: dict) -> str:
        name = c["name"]
        dc = self._cf_dc(char, "int")
        boom = F.sub_at(char, "Artificer", "Artillerist", 9)
        if key == "cannon_protect":
            n = roll("1d8") + max(1, char.mod("int"))
            near = [o for o in self.b["combatants"] if o["hp"] > 0 and not self._hostile(c, o) and o.get("pos") and self._alive(o)
                    and not o.get("conjured") and self._dist(tok, o) <= 10]
            for o in near:
                self._give_temp(o, n)
            return self._out(f"{name}'s protector pulses: {n} temporary HP for " + (", ".join(o["name"] for o in near) or "nobody"))
        if key == "cannon_detonate":
            ids = [o["id"] for o in self.b["combatants"] if o is not tok and o.get("pos") and not self._is_out(o) and not o.get("conjured")
                   and self._dist(tok, o) <= 20]
            R = self._strike(c, "Eldritch Cannon (detonation)", ids, mode="save", magical=True, parts=[["3d8", "force"]], sv={"ab": "dex", "dc": dc, "half": True})
            self._cannon_end(tok, f"{name} detonates the cannon")
            return self._run_r(R)
        dice = "3d8" if boom else "2d8"                           # Explosive Cannon: +1d8
        if tok["cannon"] == "Flamethrower":
            aim = G.centre(tgt["pos"], tgt.get("span") or 1)
            tiles = G.area_for({"shape": "cone", "size": 15, "origin": "caster"}, tok["pos"], 1, tuple(aim), *self._bounds())
            ids = [o["id"] for o in G.creatures_in(tiles, self.b["combatants"]) if o is not tok and not self._is_out(o)]
            self._area_vfx(tok, tiles, [[dice, "fire"]], "cone", aim)
            return self._run_r(self._strike(c, "Eldritch Cannon (flamethrower)", ids, mode="save", magical=True, parts=[[dice, "fire"]],
                                            sv={"ab": "dex", "dc": dc, "half": True}))
        home = list(c["pos"])
        c["pos"] = list(tok["pos"])                               # the ballista fires from the cannon's space
        try:
            atk = {"bonus": char.proficiency_bonus + char.mod("int"), "n": 1, "melee": False, "spell": True, "magical": True,
                   "normal": 120, "long": 120, "parts": [[dice, "force"]]}
            R = self._strike(c, "Eldritch Cannon (force ballista)", [tgt["id"]], mode="attack", atk=atk, magical=True, spell=True)
            R["echo_home"] = home                                 # resolve.py puts the artificer back when the shot is over
            return self._run_r(R)
        except Exception:
            c["pos"] = home
            raise

    # ---- Circle of Spores
    def _fi_corpse(self, c: dict) -> Optional[dict]:
        """The nearest Small or Medium beast or humanoid that lies dead within 10 ft."""
        best = None
        for o in self.b["combatants"]:
            if o is c or o["kind"] != "enemy" or not o.get("pos") or o.get("animated") or o.get("conjured") or o.get("summoned_by") is not None \
                    or o["hp"] > 0 or not self._within(c, o, 10):
                continue
            kind = str((self._monster(o) or {}).get("type") or "").lower()
            if not (kind.startswith("beast") or kind.startswith("humanoid")) or self._size_of(o) not in ("Small", "Medium"):
                continue
            if best is None or self._dist(c, o) < self._dist(c, best):
                best = o
        return best

    def _fi_raise(self, c: dict, char, corpse: dict) -> str:
        mid = next((m["id"] for m in bestiary.all if m["name"] == ZOMBIE and m.get("source") == "MM"), None) \
            or next((m["id"] for m in bestiary.all if m["name"] == ZOMBIE), None)
        if mid is None:
            raise ServiceError("No zombie stat block in the bestiary.")
        where = list(corpse["pos"])
        corpse["animated"] = True
        corpse["pos"] = None                                    # the body stands up as the zombie
        old = getattr(self, "_summon_point", None)
        self._summon_point = where
        try:
            made = self._add_summons(c, mid, 1, None, 1, None, None, None, None, "Fungal Infestation")
        finally:
            self._summon_point = old
        for z in made:
            z["hp"] = 1
            z["fungal"] = True
        return self._out(f"{c['name']}'s spores animate {corpse['name']}: a zombie rises with 1 hit point (Fungal Infestation; it takes "
                         f"one melee attack a turn)")

    def _halo_dice(self, c: dict, char) -> str:
        lv = char.class_level("Druid")
        die = 10 if lv >= 14 else 8 if lv >= 10 else 6 if lv >= 6 else 4
        return f"{2 if self._fx(c, 'symbiotic') else 1}d{die}"

    def _spores(self, c: dict, char, point) -> str:
        for z in [z for z in self._zones() if z.get("owner") == c["id"] and z["name"] == SPORES]:
            self._zone_off(z, "new spores")
        x, y = int(point[0]), int(point[1])
        bx = self._bounds()
        tiles = [[x + dx, y + dy] for dx in (0, 1) for dy in (0, 1)]
        tiles = [t for t in tiles if 0 <= t[0] < bx[0] and 0 <= t[1] < bx[1]]
        self._add_zone(c, SPORES, tiles, {"enter": True, "start": True, "save": "con", "half": False, "parts": [[self._halo_dice(c, char), "necrotic"]]},
                       rounds=10, dc=self._cf_dc(char, "wis"), point=[x, y])
        return self._out(f"{c['name']} hurls spores to {self._tile_label([x, y])}: a 10-ft cube for a minute ({self._halo_dice(c, char)} necrotic, "
                         f"Constitution save)")

    def _spores_cube(self, c: dict) -> bool:
        """The druid's Spreading Spores are in the field (its Halo of Spores reaction is off)."""
        return any(z.get("owner") == c["id"] and z["name"] == SPORES for z in self._zones())

    # ------------------------------------------------------------------ battle start
    def _subb_battle_start(self):
        """Tranquility: a monk of the Open Hand begins the fight under a Sanctuary (the long rest's effect)."""
        for c in self.b["combatants"]:
            char = self._sheet(c)
            if not char or c.get("form") or not F.sub_at(char, "Monk", "Way of the Open Hand", 11) or any(e["name"] == "Tranquility" for e in c.get("effects") or []):
                continue
            dc = 8 + char.mod("wis") + char.proficiency_bonus
            self._effect_on(c, "Tranquility", [], "wis", dc, None, None, c["name"], {"sanctuary": True, "ends_on": ["attack", "cast_hostile"]}, None, c["id"])
            self._say(f"{c['name']} is wrapped in an aura of peace (Tranquility: Sanctuary, DC {dc})")

    def _subb_initiative(self, c: dict):
        """Tireless Spirit: a samurai that rolls initiative with no Fighting Spirit left regains one use."""
        char = self._sheet(c)
        if char and not c.get("form") and F.sub_at(char, "Fighter", "Samurai", 10) and self._cf_left(c, "Fighting Spirit", 3) <= 0:
            char.d["resources"]["feature:Fighting Spirit"] = max(0, int(char.d["resources"].get("feature:Fighting Spirit") or 0) - 1)
            char.save()
            self._say(f"{c['name']} regains a use of Fighting Spirit (Tireless Spirit)")

    def _subb_kill(self, by: Optional[dict], c: dict):
        """Touch of Death: a Long Death monk that drops a creature within 5 ft gains Wisdom + monk level temporary hit points."""
        char = self._sheet(by) if by is not None else None
        if char and by is not c and not by.get("form") and F.sub_at(char, "Monk", "Way of the Long Death", 3) and self._alive(by) \
                and (not by.get("pos") or not c.get("pos") or self._dist(by, c) <= 5):
            n = max(1, char.mod("wis") + char.class_level("Monk"))
            self._give_temp(by, n)
            self._say(f"{by['name']} drinks in the fading life: {n} temporary HP (Touch of Death)")

    def _subb_zero_hp(self, c: dict, dealt: int, types, crit: bool) -> bool:
        """Undying Sentinel: dropped to 0 (not killed outright), a paladin of the Ancients stays at 1 HP, once a long rest."""
        char = self._sheet(c)
        if char and not c.get("form") and not self._dead(c) and F.sub_at(char, "Monk", "Way of the Long Death", 11) and self._resource_left(c, "Ki Points") >= 1:
            self._use_resource(c, "Ki Points", 1)
            self._set_hp(c, 1)
            self._say(f"{c['name']} cheats death with 1 ki: 1 hit point (Mastery of Death)")
            return True
        if not char or c.get("form") or self._dead(c) or not F.sub_at(char, "Paladin", "Oath of the Ancients", 15) or not self._cf_left(c, "Undying Sentinel", 1):
            return False
        self._cf_use(c, "Undying Sentinel")
        self._set_hp(c, 1)
        self._say(f"{c['name']} refuses to fall: 1 hit point (Undying Sentinel)")
        return True

    def _subb_dealt(self, tgt: dict, by: Optional[dict], types, taken: int):
        """Thunderbolt Strike: lightning damage from a Tempest cleric to a Large or smaller creature pushes it 10 ft."""
        char = self._sheet(by) if by is not None else None
        if not char or by is tgt or taken <= 0 or "lightning" not in types or not F.sub_at(char, "Cleric", "Tempest Domain", 6) or by.get("form"):
            return
        if self._alive(tgt) and tgt.get("pos") and by.get("pos") and SIZES.index(self._size_of(tgt)) <= SIZES.index("Large"):
            before = list(tgt["pos"])
            self._push(tgt, by, 10)
            if tgt["pos"] != before:
                self._say(f"{by['name']}'s Thunderbolt Strike hurls {tgt['name']} back")

    def _subb_after_hit(self, att: Optional[dict], tgt: dict):
        """Scornful Rebuke: a creature that hits a Conquest paladin takes psychic damage equal to its Charisma modifier."""
        tc = self._sheet(tgt)
        if att is None or att is tgt or not tc or tgt.get("form") or not F.sub_at(tc, "Paladin", "Oath of Conquest", 15) or not self._alive(att) \
                or K.incapacitated(self._conds(tgt)):
            return
        self._say(f"{tgt['name']}'s Scornful Rebuke: " + self._deal(att, [[max(1, tc.mod("cha")), "psychic"]], by=tgt, label="Scornful Rebuke"))

    def _subb_overchannel(self, att: dict, sp: dict, parts: list, level) -> list:
        """Overchannel: a wizard spell of 1st to 5th level deals its maximum (a repeat use costs necrotic damage afterwards)."""
        eff = next((e for e in att.get("effects") or [] if e["name"] == "Overchannel"), None)
        char = self._sheet(att)
        if eff is None or not char or not 1 <= int(sp.get("level") or 0) <= 5 or "Wizard" not in (sp.get("classes") or []):
            return parts
        from .spells import _max_dice
        self._effect_off(att, eff, "used")
        prior = int(eff["mods"].get("overchannel") or 0)
        self._say(f"{att['name']} overchannels {sp['name']}: maximum damage")
        if prior:
            lvl = int(level or sp["level"])
            self._say(f"{att['name']} pays for Overchannel: " + self._deal(att, [[roll(f"{(prior + 1) * lvl}d12"), "necrotic"]], by=att, label="Overchannel"))
        return [[str(_max_dice(d)), t] for d, t in parts]

    # ------------------------------------------------------------------ saves and hits
    def _subb_save_extra(self, c: dict, source: Optional[dict]):
        """Supernatural Defense: +1d6 on a save forced by the prey of a Monster Slayer (None: nothing)."""
        if source is None or source is c or c.get("form"):
            return None
        char = self._sheet(c)
        if not char or not F.sub_at(char, "Ranger", "Monster Slayer", 7) or not any(v == c["id"] for _e, v in self._fxs(source, "slayers_prey")):
            return None
        n = roll("1d6")
        return n, f" (+{n} Supernatural Defense)", ["Supernatural Defense", n]

    def _subb_hit(self, att: dict, tgt: dict, R: dict, char):
        """Slayer's Counter hit: the save that follows succeeds. Relentless Avenger: the opportunity attack hit, the paladin may move."""
        if R.get("slayers_counter"):
            att["counter_ok"] = True
        a = R.get("atk") or {}
        if char and a.get("weapon") and tgt is not att and any(e["name"] == "Form of Dread" for e in att.get("effects") or []) and self._once_per_turn(att, "form_dread"):
            dc = 8 + char.proficiency_bonus + char.mod("cha")
            res = self._saving_throw(tgt, "wis", dc, spell=True, source=att, conds=["Frightened"], label="Form of Dread")
            self._say(f"{tgt['name']} WIS save vs Form of Dread: {res['total']} vs DC {dc} - " + ("steady" if res["ok"] else "frightened"))
            if not res["ok"]:
                self._effect_on(tgt, "Frightened (Form of Dread)", ["Frightened"], None, None, None, None, att["name"], {}, None, att["id"],
                                until={"end": att["id"], "skip": 1 if self.b.get("turn") == att["id"] else 0}, ends_on=None)
        if a.get("opportunity") and char and F.sub_at(char, "Paladin", "Oath of Vengeance", 7):
            att["relentless"] = [self.b.get("round"), self.b.get("turn")]
            self._say(f"{att['name']} may move up to half its speed (Relentless Avenger)")

    # ------------------------------------------------------------------ reactions
    def _subb_families(self, char) -> List[str]:
        out = []
        if F.sub_at(char, "Ranger", "Monster Slayer", 15):
            out.append("slayers_counter")
        if F.sub_at(char, "Ranger", "Monster Slayer", 11):
            out.append("nemesis")
        if F.sub_at(char, "Paladin", "Oath of Vengeance", 15):
            out.append("soul_vengeance")
        if F.sub_at(char, "Warlock", "The Fathomless", 6):
            out.append("guardian_coil")
        if F.sub_at(char, "Ranger", "Horizon Walker", 15):
            out.append("spectral_defense")
        if F.sub_at(char, "Monk", "Way of Shadow", 17):
            out.append("opportunist")
        if F.sub_at(char, "Monk", "Way of the Kensei", 17):
            out.append("unerring_accuracy")
        if F.sub_at(char, "Warlock", "The Fiend", 14):
            out.append("hurl_hell")
        return out

    def _subb_weapon(self, o: dict, oc, foe: dict, melee: bool = False):
        """The weapon (and its attack) that reaches the foe, or None."""
        try:
            return self._cf_weapon(o, oc, foe, False if melee else None)
        except ServiceError:
            return None

    def _subb_eligible(self, out: list, window: str, R: dict, att: Optional[dict], tgt: Optional[dict], ctx: dict):
        cur = R.get("cur") or {}
        if window == "before_save" and att and tgt and tgt is not att:
            tc = self._sheet(tgt)
            if tc and not tgt.get("form") and F.sub_at(tc, "Ranger", "Monster Slayer", 15) and self._may_react(tgt) and self._alive(tgt) \
                    and any(v == tgt["id"] for _e, v in self._fxs(att, "slayers_prey")) and self._subb_weapon(tgt, tc, att):
                self._cf_offer(out, tgt, "reaction", [{"key": "slayers_counter", "label": f"Slayer's Counter: attack {att['name']} (a hit makes the save succeed)",
                                                       "detail": ""}], f"{att['name']} forces {tgt['name']} to save against {R.get('label')}. Counterattack?")
        elif window == "cast" and att:
            for o in self.b["combatants"]:
                oc = self._sheet(o)
                if not oc or o is att or o.get("form") or not F.sub_at(oc, "Ranger", "Monster Slayer", 11) or not self._hostile(o, att) \
                        or not self._may_react(o) or not self._alive(o) or not o.get("pos") or not att.get("pos") or self._dist(o, att) > 60 \
                        or not self._sees(o, att) or not self._cf_left(o, "Magic-User's Nemesis", 1, "short"):
                    continue
                self._cf_offer(out, o, "reaction", [{"key": "nemesis", "label": f"Magic-User's Nemesis: foil {R.get('label')} (Wisdom save)", "detail": ""}],
                               f"{att['name']} is casting {R.get('label')}. {o['name']}: try to foil it?")
        elif window == "declared" and att and tgt:
            for o in self.b["combatants"]:
                oc = self._sheet(o)
                if not oc or o is att or o.get("form") or not F.sub_at(oc, "Paladin", "Oath of Vengeance", 15) or not self._hostile(o, att) \
                        or not self._may_react(o) or not self._alive(o) or not o.get("pos") or not att.get("pos") \
                        or not any(e["name"].startswith("Vow of Enmity") and (e.get("mods") or {}).get("adv_vs") == att["id"] for e in o.get("effects") or []) \
                        or not self._subb_weapon(o, oc, att, melee=True):
                    continue
                self._cf_offer(out, o, "reaction", [{"key": "soul_vengeance", "label": f"Soul of Vengeance: melee attack on {att['name']}", "detail": ""}],
                               f"{att['name']}, under {o['name']}'s Vow of Enmity, is making an attack. Strike it?")
        elif window == "on_hit" and att and tgt and tgt is not att and self._alive(tgt):
            ac_ = self._sheet(att)
            if ac_ and not att.get("form") and F.sub_at(ac_, "Warlock", "The Fiend", 14) and self._cf_left(att, "Hurl Through Hell", 1) \
                    and (R.get("atk") or {}).get("weapon") is not None:
                self._cf_offer(out, att, "free", [{"key": "hurl_hell", "label": f"Hurl Through Hell: send {tgt['name']} through the lower planes (10d10 psychic)", "detail": ""}],
                               f"{att['name']} hits {tgt['name']}. Add something?")
        elif window == "missed" and att and tgt and R.get("mode") == "attack":
            ac_ = self._sheet(att)
            a = R.get("atk") or {}
            if ac_ and not att.get("form") and (a.get("weapon") or a.get("unarmed")) and F.sub_at(ac_, "Monk", "Way of the Kensei", 17) \
                    and self.b.get("turn") == att["id"] and self._cf_turn_free(att, "unerring"):
                self._cf_offer(out, att, "free", [{"key": "unerring_accuracy", "label": "Unerring Accuracy: reroll the attack", "detail": ""}],
                               f"{att['name']} misses {tgt['name']} ({cur.get('total')} vs AC {cur.get('ac')}). Add something?")
        elif window == "after_damage" and att and tgt and tgt is not att and self._alive(tgt) and R.get("mode") == "attack":
            for o in self.b["combatants"]:
                oc = self._sheet(o)
                if not oc or o.get("form") or o is att or o is tgt or not F.sub_at(oc, "Monk", "Way of Shadow", 17) or not self._hostile(o, tgt) \
                        or not self._may_react(o) or not self._alive(o) or not o.get("pos") or not tgt.get("pos") or self._dist(o, tgt) > 5 \
                        or not self._melee_weapon_of(o):
                    continue
                self._cf_offer(out, o, "reaction", [{"key": f"opportunist:{tgt['id']}", "label": f"Opportunist: melee attack on {tgt['name']}", "detail": ""}],
                               f"{att['name']} hit {tgt['name']}, who is next to {o['name']}. Opportunist?", "after_damage")
        elif window == "damage" and tgt:
            total = sum(n for n, _t in cur.get("dmg") or [])
            if total <= 0:
                return
            tc = self._sheet(tgt)
            if tc and not tgt.get("form") and R.get("mode") == "attack" and F.sub_at(tc, "Ranger", "Horizon Walker", 15) and self._may_react(tgt):
                self._cf_offer(out, tgt, "reaction", [{"key": "spectral_defense", "label": "Spectral Defense (resistance to all of that attack's damage)", "detail": ""}],
                               f"{tgt['name']} is about to take {total} damage from {R['label']}. React?")
            for o in self.b["combatants"]:
                oc = self._sheet(o)
                if not oc or o.get("form") or not F.sub_at(oc, "Warlock", "The Fathomless", 6) or not self._fx(o, "tentacle") or not self._may_react(o) \
                        or not self._alive(o) or self._hostile(o, tgt) or not o.get("pos") or not tgt.get("pos") or (tgt is not o and not self._sees(o, tgt)):
                    continue
                spot = o.get("tentacle_at") or o["pos"]
                if G.distance_ft(spot, 1, tgt["pos"], tgt.get("span") or 1) > 10:
                    continue
                dice = "2d8" if oc.class_level("Warlock") >= 10 else "1d8"
                self._cf_offer(out, o, "reaction", [{"key": "guardian_coil", "label": f"Guardian Coil (-{dice} to {tgt['name']}'s damage)", "detail": ""}],
                               f"{tgt['name']} is about to take {total} damage near {o['name']}'s tentacle. Guardian Coil?")

    def _subb_react(self, window: str, R: dict, reactor: dict, fam: str, arg: str, ctx: dict) -> bool:
        """What these features' reactions do (False: not one of them)."""
        cur = R.setdefault("cur", {})
        char = self._sheet(reactor)
        name = reactor["name"]
        att = self._find_or_none(ctx.get("attacker") or R.get("actor"))
        if fam == "slayers_counter" and att:
            hit = self._subb_weapon(reactor, char, att)
            if hit:
                w, atk = hit
                atk["n"] = 1
                child = self._strike(reactor, f"{w['name']} (Slayer's Counter)", [att["id"]], mode="attack", atk=atk, magical=atk.get("magical", False))
                child["slayers_counter"] = True
                self._stack().append(child)
            return True
        if fam == "nemesis" and att:
            self._cf_use(reactor, "Magic-User's Nemesis", "short")
            dc = self._spell_dc(reactor)
            res = self._saving_throw(att, "wis", dc, spell=True, source=reactor, label="Magic-User's Nemesis")
            self._line(R, f"{name} foils magic: {att['name']} WIS save {res['total']} vs DC {dc} — " + ("holds" if res["ok"] else "the spell fails"),
                       "Magic-User's Nemesis")
            if not res["ok"]:
                R["countered"] = True
            return True
        if fam == "soul_vengeance" and att:
            child = self._opportunity_strike(reactor, att)
            if child:
                child["label"] = "Soul of Vengeance"
                self._stack().append(child)
            return True
        if fam == "hurl_hell":
            tgt = self._find_or_none(ctx.get("target"))
            if tgt is None:
                return True
            self._cf_use(reactor, "Hurl Through Hell")
            kind = str((self._monster(tgt) or {}).get("type") or "").lower()
            self._effect_on(tgt, "Hurled Through Hell", ["Incapacitated"], None, None, None, None, name, {"banished": True, "untargetable": True}, None, reactor["id"],
                            until={"end": reactor["id"], "skip": 1 if self.b.get("turn") == reactor["id"] else 0})
            line = f"{name} hurls {tgt['name']} through the lower planes"
            if "fiend" not in kind:
                line += ": " + self._deal(tgt, [[roll("10d10"), "psychic"]], by=reactor, label="Hurl Through Hell")
            self._line(R, line, "Hurl Through Hell")
            return True
        if fam == "unerring_accuracy":
            self._once_per_turn(reactor, "unerring")
            again = self.rng.randint(1, 20)
            cur.update(total=int(cur.get("total") or 0) - int(cur.get("kept") or 0) + again, kept=again, crit=again == 20)
            self._line(R, f"{name}'s Unerring Accuracy: rerolled {again} → {cur['total']}", "Unerring Accuracy")
            return True
        if fam == "spectral_defense":
            cur["dmg"] = [[n // 2, t] for n, t in cur.get("dmg") or []]
            self._line(R, f"{name} slips between planes: resistance to all of that attack's damage (Spectral Defense)", "Spectral Defense")
            return True
        if fam == "opportunist":
            victim = self._find_or_none(int(arg)) if str(arg or "").isdigit() else None
            child = self._opportunity_strike(reactor, victim) if victim else None
            if child:
                child["label"] = "Opportunist"
                self._stack().append(child)
            return True
        if fam == "guardian_coil":
            dice = "2d8" if char.class_level("Warlock") >= 10 else "1d8"
            cut = roll(dice)
            left, after = max(0, cut), []
            for n, t in cur.get("dmg") or []:
                take = min(n, left)
                left -= take
                after.append([n - take, t])
            cur["dmg"] = after
            self._line(R, f"{name}'s tentacle shields: -{cut} damage", "Guardian Coil")
            return True
        return False


F.ACTIVE.update(_sub_b_active())
