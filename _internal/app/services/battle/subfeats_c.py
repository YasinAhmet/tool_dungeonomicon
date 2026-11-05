"""Subclass features, batch C (the bar's items are added to features.ACTIVE below; subfeats.py hands over to this):

    Cleric, Trickery         Blessing of the Trickster (advantage on Stealth), Channel Divinity: Cloak of Shadows, Improved Duplicity (four duplicates)
    Cleric, Forge            Blessing of the Forge (+1 AC or +1 to the weapon, set when the battle begins)
    Cleric, Tempest          Stormborn (a flying speed)
    Cleric, Grave            Circle of Mortality (healing dice at their maximum for a creature at 0 HP; spare the dying as a bonus action, 30 ft)
    Cleric, Knowledge        Channel Divinity: Read Thoughts (and the suggestion that ends it)
    Cleric, Order            Voice of Authority (an ally's reaction attack after a spell cast on it)
    Cleric, Peace            Protective Bond (a reaction: step in and take the damage), Expansive Bond (60 ft, resistance)
    Cleric, Arcana           Channel Divinity: Arcane Abjuration (turned, or banished by CR), Spell Breaker
    Cleric, Death            Inescapable Destruction (necrotic damage ignores resistance)
    Druid, Land              Nature's Sanctuary (beasts and plants save before they attack)
    Druid, Shepherd          Mighty Summoner, Guardian Spirit, Faithful Summons
    Druid, Wildfire          Cauterizing Flames (spectral flames where creatures fall), Blazing Revival
    Druid, Stars             Twinkling Constellations (2d8 chalice, a flying dragon)
    Monk, Shadow             Cloak of Shadows (invisible in dim light or darkness)
    Monk, Kensei             One with the Blade (magical kensei weapons, Deft Strike), Agile Parry
    Monk, Sun Soul           Sun Shield (a reaction: radiant damage to a melee attacker)
    Monk, Astral Self        Visage, Body (Deflect Energy, Empowered Arms), Awakened Astral Self (+2 AC, Astral Barrage)
    Monk, Long Death         Touch of the Long Death
    Monk, Mercy              Physician's Touch, Hand of Ultimate Mercy
    Monk, Drunken Master     Leap to Your Feet, Tipsy Sway (Redirect Attack), Drunkard's Luck, Intoxicated Frenzy
    Monk, Ascendant Dragon   Ascendant Aspect (blindsight, Explosive Fury, Augment Breath)
    Barbarian                Storm Herald's Shielding Storm, Zealot's Rage beyond Death, Battlerager (armor, Reckless Abandon, Charge, Spiked Retribution),
                             Wild Magic's Bolstering Magic, Beast's Call the Hunt
    Fighter                  Arcane Archer's Curving Shot and Ever-Ready Shot, Cavalier's Ferocious Charger and Vigilant Defender, Samurai's Rapid Strike and
                             Strength before Death, Banneret's Rallying Cry and Inspiring Surge, Psi Warrior's Telekinetic Master, Echo Knight's
                             Legion of One (the Unleash Incarnation use back at initiative)
    Bard                     Whispers' Shadow Lore, Spirits' Tales from Beyond and Spiritual Focus, Creation's Mote of Potential and Animating
                             Performance, Eloquence's Unfailing and Infectious Inspiration
Not played (nothing to do on a battle map): Master of Nature, Mantle of Whispers, Echo Avatar, Know Your Enemy, Weapon Bond; Embodiment of the Law and
Blessed Strikes (optional replacements) are left out.
"""
import re
from typing import List, Optional

from ...rules.monsters import bestiary
from . import conditions as K
from . import features as F
from . import geometry as G
from .resolve import roll

SUB_C_FAMILIES = {"deft_strike": "Deft Strike", "tipsy_sway": "Redirect Attack", "sun_shield": "Sun Shield", "deflect_energy": "Deflect Energy",
                  "curving_shot": "Curving Shot", "vigil_oa": "Vigilant Defender", "protective_bond": "Protective Bond"}
SUB_C_FREE = {"deft_strike", "vigil_oa", "curving_shot"}
CONDS_PHYSICIAN = ["Blinded", "Deafened", "Paralyzed", "Poisoned", "Stunned"]
ENERGY = {"acid", "cold", "fire", "force", "lightning", "thunder"}
TALES = {1: ("Clever Animal", "+ the die on Intelligence, Wisdom and Charisma checks"), 2: ("Renowned Duelist", "a melee spell attack, two dice + Charisma force"),
         3: ("Beloved Friends", "temporary hit points for two creatures"), 4: ("Runaway", "a reaction teleport, no opportunity attacks"),
         5: ("Avenger", "melee attackers take force damage"), 6: ("Traveler", "temporary hit points, +10 ft speed and +1 AC"),
         7: ("Beguiler", "Wisdom save or psychic damage and incapacitated"), 8: ("Phantom", "invisible, a hit deals necrotic damage"),
         9: ("Brute", "Strength save or thunder damage and prone"), 10: ("Dragon", "a 30-ft cone of fire from the target"),
         11: ("Angel", "healing and a condition ended"), 12: ("Mind-Bender", "Intelligence save or psychic damage and stunned")}
BANISH_CR = {5: .5, 8: 1, 11: 2, 14: 3, 17: 4}


def _sub_c_active() -> dict:
    cleric = lambda sub, n: (lambda c: F.sub_at(c, "Cleric", sub, n))
    monk = lambda sub, n: (lambda c: F.sub_at(c, "Monk", sub, n))
    barb = lambda sub, n: (lambda c: F.sub_at(c, "Barbarian", sub, n))
    return {
        # ---- Cleric: Trickery
        "blessing_trickster": {"name": "Blessing of the Trickster", "cost": "action", "resource": None, "target": "ally", "range": 5,
                               "needs": cleric("Trickery Domain", 1),
                               "text": "Touch a willing creature other than yourself: advantage on Dexterity (Stealth) checks for an hour, or until you use this again."},
        "cloak_shadows_cd": {"name": "Channel Divinity: Cloak of Shadows", "cost": "action", "resource": "Channel Divinity (Cleric)", "target": "self",
                             "needs": cleric("Trickery Domain", 6),
                             "text": "Become invisible until the end of your next turn. You become visible if you attack or cast a spell."},
        # ---- Cleric: Knowledge
        "read_thoughts": {"name": "Channel Divinity: Read Thoughts", "cost": "action", "resource": "Channel Divinity (Cleric)", "target": "enemy", "range": 60,
                          "needs": cleric("Knowledge Domain", 6),
                          "text": "A creature you can see within 60 ft makes a Wisdom save or you read its surface thoughts for a minute (a success: you can't try "
                                  "it on that creature again before a long rest)."},
        "read_thoughts_suggest": {"name": "Read Thoughts: suggestion", "cost": "action", "resource": None, "target": "enemy", "range": 60,
                                  "needs": cleric("Knowledge Domain", 6),
                                  "text": "End Read Thoughts on a creature to cast suggestion on it without a spell slot: it automatically fails its save."},
        # ---- Monk: Way of Shadow
        "cloak_shadows_monk": {"name": "Cloak of Shadows", "cost": "action", "resource": None, "target": "self", "needs": monk("Way of Shadow", 11),
                               "text": "In dim light or darkness: become invisible until you attack, cast a spell or stand in bright light."},
        # ---- Monk: Astral Self
        "visage_astral": {"name": "Visage of the Astral Self", "cost": "free", "resource": "Ki Points", "target": "self", "needs": monk("Way of the Astral Self", 6),
                          "text": "Spend 1 ki (a bonus action, or part of the one that summons the arms): for 10 minutes you see in darkness to 120 ft and have "
                                  "advantage on Insight and Intimidation checks. With the arms (and at 11th level) the body of the astral self appears too: "
                                  "Deflect Energy and Empowered Arms."},
        "awakened_astral": {"name": "Awakened Astral Self", "cost": "bonus", "resource": "Ki Points", "ki": 5, "target": "self",
                            "needs": monk("Way of the Astral Self", 17),
                            "text": "Spend 5 ki: the arms, visage and body of your astral self for 10 minutes, +2 AC, and three attacks with Extra Attack when "
                                    "they are all made with the astral arms."},
        # ---- Monk: Way of the Ascendant Dragon (Augment Breath)
        "breath_aug_cone": {"name": "Breath of the Dragon (augmented cone)", "cost": "attack", "resource": None, "per": "long", "alt_ki": 2, "target": "area",
                            "area": {"shape": "cone", "size": 60, "origin": "caster"}, "per_name": "Breath of the Dragon", "uses": lambda c: c.proficiency_bonus,
                            "needs": monk("Way of the Ascendant Dragon", 17),
                            "options": lambda c: [{"value": t, "label": t.capitalize()} for t in F.DRAGON_TYPES],
                            "text": "Augment Breath: 1 more ki makes the breath a 60-ft cone, four Martial Arts dice (Dexterity save against your ki DC)."},
        "breath_aug_line": {"name": "Breath of the Dragon (augmented line)", "cost": "attack", "resource": None, "per": "long", "alt_ki": 2, "target": "area",
                            "area": {"shape": "line", "size": 90, "width": 5, "origin": "caster"}, "per_name": "Breath of the Dragon",
                            "uses": lambda c: c.proficiency_bonus, "needs": monk("Way of the Ascendant Dragon", 17),
                            "options": lambda c: [{"value": t, "label": t.capitalize()} for t in F.DRAGON_TYPES],
                            "text": "Augment Breath: 1 more ki makes the breath a 90-ft line, four Martial Arts dice (Dexterity save against your ki DC)."},
        # ---- Monk: Way of the Long Death, Way of Mercy
        "touch_long_death": {"name": "Touch of the Long Death", "cost": "action", "resource": None, "target": "enemy", "range": 5,
                             "needs": monk("Way of the Long Death", 17),
                             "options": lambda c: [{"value": str(n), "label": f"{n} ki: {2 * n}d10 necrotic"} for n in range(1, 11)],
                             "text": "Touch a creature within 5 ft and spend 1 to 10 ki: a Constitution save (your ki DC), 2d10 necrotic damage per ki "
                                     "point on a failed save, half as much on a success."},
        "flurry_healing": {"name": "Flurry of Healing", "cost": "bonus", "resource": "Ki Points", "target": "ally", "range": 5,
                           "needs": monk("Way of Mercy", 11),
                           "text": "Spend 1 ki on a Flurry of Blows after the Attack action, with Hand of Healing in place of both strikes (no ki for the "
                                   "healing): a creature you touch regains two Martial Arts dice + Wisdom modifier each."},
        "hand_ultimate_mercy": {"name": "Hand of Ultimate Mercy", "cost": "action", "resource": "Ki Points", "ki": 5, "per": "long", "uses": 1,
                                "target": "ally", "range": 5, "needs": monk("Way of Mercy", 17),
                                "text": "Touch the corpse of a creature that died in the last 24 hours and spend 5 ki: it returns to life with 4d10 + Wisdom "
                                        "modifier hit points. Once a long rest."},
        # ---- Monk: Way of the Drunken Master
        "intoxicated_frenzy": {"name": "Intoxicated Frenzy", "cost": "bonus", "resource": "Ki Points", "target": "enemy", "range": 5,
                               "needs": monk("Way of the Drunken Master", 17),
                               "text": "Flurry of Blows for 1 ki with up to five attacks, each at a different creature within reach (the one you picked "
                                       "first), with Drunken Technique's Disengage and +10 ft."},
        # ---- Barbarian
        "bolstering_magic": {"name": "Bolstering Magic", "cost": "action", "resource": None, "per": "long", "uses": lambda c: c.proficiency_bonus,
                             "target": "ally", "range": 5, "needs": barb("Path of Wild Magic", 6),
                             "options": lambda c: [{"value": "d3", "label": "A d3 on attack rolls and checks (10 minutes)"},
                                                   {"value": "slot", "label": "Regain a spell slot of the level of a d3 or lower"}],
                             "text": "Touch a creature (or yourself): for 10 minutes it adds a d3 to its attack rolls and ability checks, or it regains an "
                                     "expended spell slot of the level of a d3 or lower (once a long rest for a creature)."},
        "battlerager_armor": {"name": "Spiked Armor strike", "cost": "bonus", "resource": None, "target": "enemy", "range": 5, "when": "raging",
                              "needs": barb("Path of the Battlerager", 3),
                              "text": "While raging in spiked armor: a melee attack with the armor spikes, 1d4 piercing + Strength."},
        "battlerager_charge": {"name": "Battlerager Charge", "cost": "bonus", "resource": None, "target": "self", "when": "raging",
                               "needs": barb("Path of the Battlerager", 10), "text": "Take the Dash action as a bonus action while you are raging."},
        # ---- Bard: College of Whispers
        "shadow_lore": {"name": "Shadow Lore", "cost": "action", "resource": None, "per": "long", "uses": 1, "target": "enemy", "range": 30,
                        "needs": lambda c: F.sub_at(c, "Bard", "College of Whispers", 14),
                        "text": "Whisper to a creature within 30 ft: a Wisdom save (your spell save DC) or it is charmed for 8 hours, until you or your allies "
                                "attack it, damage it or force a save. Once a long rest."},
        # ---- Bard: College of Spirits
        "tales_beyond": {"name": "Tales from Beyond", "cost": "bonus", "resource": "Bardic Inspiration", "target": "self",
                         "needs": lambda c: F.sub_at(c, "Bard", "College of Spirits", 3),
                         "text": "While holding your spiritual focus: expend a Bardic Inspiration die and roll it on the Spirit Tales table. You keep the tale "
                                 "in mind until you bestow it (next item) or roll again."},
        "tale_bestow": {"name": "Tell the tale", "cost": "action", "resource": None, "target": "ally", "range": 30,
                        "needs": lambda c: F.sub_at(c, "Bard", "College of Spirits", 3),
                        "text": "Choose a creature you can see within 30 ft (you too) as the target of the tale's effect."},
        # ---- Cleric: Arcana, Druid: Wildfire
        "arcane_abjuration": {"name": "Channel Divinity: Arcane Abjuration", "cost": "action", "resource": "Channel Divinity (Cleric)", "target": "none",
                              "needs": cleric("Arcana Domain", 2),
                              "text": "A celestial, elemental, fey or fiend within 30 ft makes a Wisdom save or is turned for a minute (from 5th level one of a "
                                      "low enough challenge rating is banished instead)."},
        "cauterizing_flames": {"name": "Cauterizing Flames", "cost": "reaction", "resource": None, "per": "long", "uses": lambda c: c.proficiency_bonus,
                               "target": "ally", "range": 30, "needs": lambda c: F.sub_at(c, "Druid", "Circle of Wildfire", 10),
                               "text": "Where a Small or larger creature died near you or your spirit a spectral flame burns for a minute. A creature that steps in "
                                       "it (you pick one within 5 ft of the flame) is healed, or burned if it is a foe, for 2d10 + Wisdom modifier."},
        # ---- Bard: College of Creation
        "animating_performance": {"name": "Animating Performance", "cost": "action", "resource": None, "per": "long", "uses": 1, "target": "point", "range": 30,
                                  "needs": lambda c: F.sub_at(c, "Bard", "College of Creation", 6),
                                  "text": "Animate a Large or smaller object within 30 ft as a Dancing Item for an hour: it shares your initiative, acts right after "
                                          "you and fights for you. Once a long rest (a 3rd-level slot or higher buys another); one item at a time."},
        "animating_performance_slot": {"name": "Animating Performance (spell slot)", "cost": "action", "resource": None, "target": "point", "range": 30,
                                       "needs": lambda c: F.sub_at(c, "Bard", "College of Creation", 6),
                                       "text": "Animate the item again by expending a spell slot of 3rd level or higher."},
        # ---- Fighter: Psi Warrior
        "telekinetic_master": {"name": "Telekinetic Master", "cost": "action", "resource": None, "per": "long", "uses": 1, "target": "ally", "range": 60,
                               "needs": lambda c: F.sub_at(c, "Fighter", "Psi Warrior", 18),
                               "text": "Cast telekinesis without components (Intelligence): while you concentrate on it you can make one weapon attack as a bonus "
                                       "action each turn. Once a long rest, or a Psionic Energy die for another."},
        "telekinetic_master_die": {"name": "Telekinetic Master (Psionic Energy die)", "cost": "action", "resource": None, "target": "ally", "range": 60,
                                   "needs": lambda c: F.sub_at(c, "Fighter", "Psi Warrior", 18),
                                   "text": "Cast telekinesis again by expending a Psionic Energy die."},
        "telekinetic_attack": {"name": "Telekinetic Master: weapon attack", "cost": "bonus", "resource": None, "target": "enemy",
                               "needs": lambda c: F.sub_at(c, "Fighter", "Psi Warrior", 18),
                               "text": "While you concentrate on telekinesis: one weapon attack as a bonus action."},
        # ---- Fighter: Samurai
        "rapid_strike": {"name": "Rapid Strike", "cost": "free", "resource": None, "target": "enemy", "range": 5, "when": "attacked",
                         "needs": lambda c: F.sub_at(c, "Fighter", "Samurai", 15),
                         "text": "After the Attack action: forgo the advantage on one attack roll to make an additional weapon attack against the same target "
                                 "(the advantage the Fighting Spirit gave is used up). Once a turn."},
    }


class SubFeatsCMixin:
    # ------------------------------------------------------------------ small helpers
    def _subc_families(self, char) -> List[str]:
        out = []
        if F.sub_at(char, "Monk", "Way of the Kensei", 6):
            out.append("deft_strike")
        if F.sub_at(char, "Monk", "Way of the Drunken Master", 6):
            out.append("tipsy_sway")
        if F.sub_at(char, "Monk", "Way of the Sun Soul", 17):
            out.append("sun_shield")
        if F.sub_at(char, "Monk", "Way of the Astral Self", 11):
            out.append("deflect_energy")
        if F.sub_at(char, "Fighter", "Arcane Archer", 7):
            out.append("curving_shot")
        if F.sub_at(char, "Fighter", "Cavalier", 18):
            out.append("vigil_oa")
        if F.sub_at(char, "Cleric", "Peace Domain", 6):
            out.append("protective_bond")
        return out

    def _subc_feet(self, c: dict):
        return G.footprint(c["pos"], c.get("span") or 1)

    def _subc_has(self, c: dict, name: str) -> bool:
        return any(e["name"] == name for e in c.get("effects") or [])

    def _subc_own_end(self, c: dict) -> dict:
        return {"end": c["id"], "skip": 1 if self.b.get("turn") == c["id"] else 0}

    def _subc_kensei(self, att: dict, atk: dict) -> bool:
        """A kensei monk's weapon attack (a kensei weapon: any simple or martial weapon without the heavy or special property)."""
        char = self._sheet(att)
        props = [str(p).lower() for p in atk.get("props") or []]
        return bool(char) and not att.get("form") and F.sub_at(char, "Monk", "Way of the Kensei", 3) and bool(atk.get("weapon")) \
            and "unarmed" not in props and "heavy" not in props and "special" not in props

    def _subc_astral_body(self, c: dict) -> bool:
        char = self._sheet(c)
        return bool(char) and not c.get("form") and F.sub_at(char, "Monk", "Way of the Astral Self", 11) \
            and self._subc_has(c, "Arms of the Astral Self") and self._subc_has(c, "Visage of the Astral Self")

    @staticmethod
    def _subc_spiked(char) -> bool:
        return "spiked" in str((char.equipped_armor() or {}).get("name") or "").lower()

    # ------------------------------------------------------------------ the bar
    def _subc_why(self, c: dict, char, key: str, f: dict, tgt: Optional[dict], option, menu: bool, point) -> Optional[str]:
        """Why one of these features can't be used now (None: it can, or it isn't one of these)."""
        t = c.get("turn") or {}
        if key == "blessing_trickster" and not menu and (tgt is None or tgt is c):
            return "Touch a willing creature other than yourself."
        if key in ("cloak_shadows_cd", "cloak_shadows_monk", "visage_astral", "awakened_astral") and any(e["name"].startswith(f["name"].split(":")[-1].strip()) for e in c.get("effects") or []):
            return "Already active"
        if key == "visage_astral" and self._economy_on() and "Arms of the Astral Self" not in (t.get("used") or []) and not menu:
            from . import economy as EC
            return EC.why_not(t, "bonus")
        if key == "cloak_shadows_monk" and c.get("pos") and not self._cf_dark(self._subc_feet(c)):
            return "Stand in dim light or darkness first"
        if key == "read_thoughts":
            if not menu and (tgt is None or tgt is c or not self._hostile(c, tgt)):
                return "Pick a foe to read."
            if not menu and tgt and tgt["id"] in (c.get("thoughts_safe") or []):
                return f"{tgt['name']} shrugged you off already (until a long rest)"
        if key in ("breath_aug_cone", "breath_aug_line"):
            if self._resource_left(c, "Ki Points") < 1:
                return "Augment Breath costs 1 ki"
            if not menu and self._economy_on():
                return self._pay(c, "attack", f["name"], check_only=True)
        if key == "read_thoughts_suggest" and not menu and (tgt is None or not any((e.get("mods") or {}).get("thoughts_read") == c["id"] for e in tgt.get("effects") or [])):
            return "Pick a creature whose thoughts you are reading."
        if key == "touch_long_death" and not menu:
            if tgt is None or tgt is c or not self._hostile(c, tgt):
                return "Pick a foe within 5 ft."
            if self._resource_left(c, "Ki Points") < (int(option) if str(option or "").isdigit() else 1):
                return "Not enough ki"
        if key == "hand_ultimate_mercy" and not menu and (tgt is None or tgt is c or not (self._dead(tgt) or (tgt["kind"] != "pc" and self._hp_of(tgt) <= 0))):
            return "Pick the corpse of a creature that died."
        if key in ("intoxicated_frenzy", "flurry_healing") and self._economy_on() and not t.get("attacked"):
            return "Take the Attack action first"
        if key == "battlerager_armor" and not self._subc_spiked(char):
            return "You need spiked armor on"
        if key == "bolstering_magic" and not menu:
            who = tgt or c
            if option == "slot" and (self._cf_left(who, "Bolstering slot", 1) <= 0 or not self._subc_used_slots(who)):
                return f"{who['name']} has no spent slot to regain (or already received it)"
        if key == "shadow_lore" and not menu and (tgt is None or tgt is c or not self._hostile(c, tgt)):
            return "Pick a foe first."
        if key == "tale_bestow" and not c.get("tale"):
            return "No tale in mind: use Tales from Beyond first"
        if key == "cauterizing_flames":
            flames = self._subc_flames(c)
            if not flames:
                return "No spectral flame burns near a fallen creature"
            if not menu and (tgt is None or not tgt.get("pos") or not any(G.distance_ft(fl["pos"], 1, tgt["pos"], tgt.get("span") or 1) <= 5 for fl in flames)):
                return "Pick a creature at a spectral flame."
        if key in ("animating_performance", "animating_performance_slot"):
            if key == "animating_performance_slot" and not self._subc_slot(char, 3):
                return "No spell slot of 3rd level or higher left"
            if key == "animating_performance_slot" and self._cf_left(c, "Animating Performance", 1) > 0:
                return "Use the free animation first"
            if not menu:
                if not point or not c.get("pos"):
                    return "Pick the spot of the object."
                x, y = int(point[0]), int(point[1])
                if G.distance_ft(c["pos"], c.get("span") or 1, [x, y], 1) > 30:
                    return "Too far (up to 30 ft)"
                if not self._tile_ok({"id": -1, "span": 1}, x, y):
                    return "That tile is taken or off the map."
        if key in ("telekinetic_master", "telekinetic_master_die") and not menu and (tgt is None or tgt is c):
            return "Pick a creature or object to seize."
        if key == "telekinetic_master_die" and not self._psi_left(c, char):
            return "No Psionic Energy die left"
        if key == "telekinetic_master_die" and self._cf_left(c, "Telekinetic Master", 1) > 0:
            return "Use the free casting first"
        if key == "telekinetic_attack" and (c.get("concentrating") or {}).get("spell") != "Telekinesis":
            return "Only while you concentrate on telekinesis"
        if key == "telekinetic_attack" and not menu and (tgt is None or tgt is c or not self._hostile(c, tgt)):
            return "Pick a foe first."
        if key == "rapid_strike":
            if not self._cf_turn_free(c, "rapid_strike"):
                return "Once a turn"
            if not menu and (tgt is None or tgt is c or not self._hostile(c, tgt)):
                return "Pick the creature to strike."
        return None

    def _subc_used_slots(self, who: dict) -> bool:
        """A spell slot spent that Bolstering Magic could bring back."""
        char = self._sheet(who)
        return bool(char) and any(int(v or 0) > 0 for v in (char.d.get("slots_used") or {}).values())

    def _subc_feature(self, c: dict, char, key: str, f: dict, tgt: Optional[dict], option, point) -> Optional[str]:
        """Plays one of these features (None: not one of these, or it only noted something)."""
        name = c["name"]
        t = c.get("turn")
        own_end = self._subc_own_end(c)
        if key == "blessing_trickster":
            for o in self.b["combatants"]:
                for e in [e for e in o.get("effects") or [] if e["name"] == "Blessing of the Trickster" and e.get("source_id") == c["id"]]:
                    self._effect_off(o, e, "a new blessing")
            self._effect_on(tgt, "Blessing of the Trickster", [], None, None, None, 600, name, {"skill_adv": ["Stealth"]}, None, c["id"])
            return self._out(f"{name} touches {tgt['name']}: advantage on Stealth for an hour (Blessing of the Trickster)")
        if key == "cloak_shadows_cd":
            self._effect_on(c, "Cloak of Shadows", ["Invisible"], None, None, None, None, name, {"ends_on": ["attack", "cast"]}, None, c["id"], until=own_end)
            return self._out(f"{name} vanishes into shadow: invisible until the end of the next turn (Cloak of Shadows)")
        if key == "cloak_shadows_monk":
            self._effect_on(c, "Cloak of Shadows (Shadow)", ["Invisible"], None, None, None, None, name, {"ends_on": ["attack", "cast"], "shadow_cloak": True}, None, c["id"])
            return self._out(f"{name} becomes one with the shadows: invisible until an attack, a spell or bright light (Cloak of Shadows)")
        if key == "read_thoughts":
            dc = self._cf_dc(char, "wis")
            res = self._saving_throw(tgt, "wis", dc, spell=True, source=c, label="Read Thoughts")
            if res["ok"]:
                c.setdefault("thoughts_safe", []).append(tgt["id"])
                return self._out(f"{tgt['name']} WIS save vs Read Thoughts: {res['total']} vs DC {dc} - the mind stays shut")
            self._effect_on(tgt, "Read Thoughts", [], None, None, None, 10, name, {"thoughts_read": c["id"]}, None, c["id"])
            return self._out(f"{tgt['name']} WIS save vs Read Thoughts: {res['total']} vs DC {dc} - {name} reads its surface thoughts for a minute")
        if key == "read_thoughts_suggest":
            for e in [e for e in tgt.get("effects") or [] if (e.get("mods") or {}).get("thoughts_read") == c["id"]]:
                self._effect_off(tgt, e, "the mind is commanded")
            self._effect_on(tgt, "Suggestion (Read Thoughts)", [], None, None, None, 4800, name, {}, None, c["id"], ends_on=["damage"])
            return self._out(f"{name} slips a suggestion into {tgt['name']}'s mind: it follows the course the cleric proposed (Read Thoughts; the DM plays it out)")
        if key == "visage_astral":
            if self._economy_on() and "Arms of the Astral Self" not in ((t or {}).get("used") or []):
                self._pay(c, "bonus", f["name"])
            self._effect_on(c, "Visage of the Astral Self", [], None, None, None, 100, name,
                            {"senses": {"darkvision": 120}, "skill_adv": ["Insight", "Intimidation"]}, None, c["id"])
            body = self._subc_astral_body(c)
            return self._out(f"{name} summons the visage of the astral self" + (": the body of the astral self joins it (Deflect Energy, Empowered Arms)" if body else ""))
        if key == "awakened_astral":
            for nm, mods in (("Arms of the Astral Self", {"astral_arms": True}), ("Visage of the Astral Self", {"senses": {"darkvision": 120}, "skill_adv": ["Insight", "Intimidation"]})):
                if not self._subc_has(c, nm):
                    self._effect_on(c, nm, [], None, None, None, 100, name, mods, None, c["id"])
            self._effect_on(c, "Awakened Astral Self", [], None, None, None, 100, name, {"ac": 2, "attack_floor": 3}, None, c["id"])
            return self._out(f"{name} awakens the astral self: arms, visage and body, +2 AC, three attacks with the astral arms")
        if key in ("breath_aug_cone", "breath_aug_line"):
            self._use_resource(c, "Ki Points", 1)
            dtype = option if option in F.DRAGON_TYPES else "fire"
            die = F.martial_die(char) or "1d4"
            parts = [[f"4d{die.split('d')[1]}", dtype]]
            self._pay_attack(c, F.extra_attacks(char), f["name"])
            aim = point or self.b.get("aim") or (list(G.centre(tgt["pos"], tgt.get("span") or 1)) if tgt and tgt.get("pos") else None)
            tiles = G.area_for(f["area"], c["pos"], c.get("span") or 1, tuple(aim) if aim else None, *self._bounds())
            ids = [o["id"] for o in G.creatures_in(tiles, self.b["combatants"]) if o is not c and not self._is_out(o)]
            self._area_vfx(c, tiles, parts, f["area"].get("shape", ""), aim)
            return self._run_r(self._strike(c, "Breath of the Dragon (augmented)", ids, mode="save", magical=True, parts=parts, summary_targets=None,
                                            sv={"ab": "dex", "dc": F.ki_dc(char), "half": True}))
        if key == "touch_long_death":
            n = max(1, min(10, int(option))) if str(option or "").isdigit() else 1
            self._use_resource(c, "Ki Points", n)
            return self._run_r(self._strike(c, "Touch of the Long Death", [tgt["id"]], mode="save", magical=True, parts=[[f"{2 * n}d10", "necrotic"]],
                                            sv={"ab": "con", "dc": F.ki_dc(char), "half": True}))
        if key == "flurry_healing":
            who = tgt or c
            die = F.martial_die(char) or "1d4"
            got = [roll(die) + max(0, char.mod("wis")) for _ in range(2)]
            for n in got:
                self._heal(who, n)
            gone = next((x for x in CONDS_PHYSICIAN if x in self._conds(who)), None)      # Physician's Touch: with a use of Hand of Healing
            if gone:
                self._clear_conditions(who, [gone])
            return self._out(f"{name} flows through a Flurry of Healing: {who['name']} +{got[0]} and +{got[1]} HP"
                             + (f", no longer {gone.lower()}" if gone else ""))
        if key == "hand_ultimate_mercy":
            n = max(1, roll("4d10") + char.mod("wis"))
            self._clear_conditions(tgt, CONDS_PHYSICIAN)
            self._heal(tgt, n, revive=True)
            if tgt["kind"] == "pc":
                tc = self._sheet(tgt)
                if tc:
                    tc.d["death_saves"] = {"success": 0, "failure": 0}
                    tc.save()
            return self._out(f"{name} grants the ultimate mercy: {tgt['name']} returns to life with {n} hit points (Hand of Ultimate Mercy)")
        if key == "hand_of_healing" and F.sub_at(char, "Monk", "Way of Mercy", 6) and (tgt or c):
            who = tgt or c
            gone = next((x for x in CONDS_PHYSICIAN if x in self._conds(who)), None)
            if gone:
                self._clear_conditions(who, [gone])
                self._say(f"{name}'s Physician's Touch ends {who['name']}'s {gone.lower()} condition")
            return None
        if key == "intoxicated_frenzy":
            near = [tgt] + [o for o in self._cf_hostiles(c, 5) if o is not tgt] if tgt else self._cf_hostiles(c, 5)
            ids = [o["id"] for o in near[:5]]
            if len(ids) < 2:
                ids = ids * 2                                       # a lone foe: the ordinary two blows
            w = next((a for a in char.attacks() if "unarmed" in (a.get("props") or [])), None)
            atk = self._check_reach(c, tgt, self._weapon_atk(c, w))
            atk["n"] = 1
            if t is not None:
                t["disengaged"] = True                              # Drunken Technique
                t["move"] = t.get("move", 0) + 10
            return self._run_r(self._strike(c, f["name"], ids, mode="attack", atk=atk))
        if key == "battlerager_armor":
            mod = char.mod("str")
            atk = {"bonus": char.proficiency_bonus + mod, "n": 1, "melee": True, "weapon": True, "reach": 5, "str_based": True, "props": [],
                   "ability": "str", "parts": [[f"1d4{mod:+d}" if mod else "1d4", "piercing"]], "magical": False}
            atk = self._check_reach(c, tgt, atk)
            return self._run_r(self._strike(c, "Spiked Armor", [tgt["id"]], mode="attack", atk=atk, magical=False))
        if key == "battlerager_charge":
            if t is not None:
                from . import economy as EC
                EC.dash(t)
            return self._out(f"{name} charges: Dash as a bonus action (Battlerager Charge)")
        if key == "reckless" and F.sub_at(char, "Barbarian", "Path of the Battlerager", 6) and self._raging(c):
            n = max(1, char.mod("con"))
            self._give_temp(c, n)
            self._say(f"{name} gains {n} temporary hit points (Reckless Abandon)")
            return None
        if key == "storm_aura" and F.sub_at(char, "Barbarian", "Path of the Storm Herald", 10):
            self._shielding_storm(c, char)
            return None
        if key == "bolstering_magic":
            who = tgt or c
            if option == "slot":
                got = self._subc_regain_slot(who, roll("1d3"))
                self._cf_use(who, "Bolstering slot")
                return self._out(f"{name} bolsters {who['name']}: " + (f"a level {got} spell slot comes back" if got else "no spent slot of that level"))
            self._effect_on(who, "Bolstering Magic", [], None, None, None, 100, name, {"attack": "1d3", "check": "1d3"}, None, c["id"])
            return self._out(f"{name} bolsters {who['name']}: +1d3 to attack rolls and ability checks for 10 minutes")
        if key == "shadow_lore":
            dc = self._spell_dc(c)
            return self._run_r(self._strike(c, "Shadow Lore", [tgt["id"]], mode="save", magical=True, spell=True, parts=[],
                                            sv={"ab": "wis", "dc": dc, "half": False, "conds": ["Charmed"], "rounds": 4800, "ends_on": ["damage"]}))
        if key == "second_wind" and F.sub_at(char, "Fighter", "Purple Dragon Knight (Banneret)", 3):
            lv = char.class_level("Fighter")
            allies = [o for o in self.b["combatants"] if o is not c and not self._hostile(c, o) and self._alive(o) and o.get("pos") and c.get("pos")
                      and self._dist(c, o) <= 60 and not o.get("conjured") and self._hp_of(o) < self._max_hp(o)]
            allies = sorted(allies, key=lambda o: self._hp_of(o) / max(1, self._max_hp(o)))[:3]
            for o in allies:
                self._heal(o, lv)
            if allies:
                self._say(f"{name}'s Rallying Cry: {', '.join(o['name'] for o in allies)} regain {lv} hit points")
            return None
        if key == "action_surge" and F.sub_at(char, "Fighter", "Purple Dragon Knight (Banneret)", 10):
            self._inspiring_surge(c, char)
            return None
        if key in ("animating_performance", "animating_performance_slot"):
            if key == "animating_performance_slot":
                lvl = self._subc_slot(char, 3)
                used = char.d["slots_used"]
                used[str(lvl)] = int(used.get(str(lvl)) or 0) + 1
                char.save()
            return self._animate(c, char, point)
        if key == "aspect_wyrm" and F.sub_at(char, "Monk", "Way of the Ascendant Dragon", 17):
            kind = option if option in F.DRAGON_TYPES else "fire"
            ids = [o["id"] for o in self._cf_hostiles(c, 10) if self._sees(c, o)]
            if ids:
                self._run_r(self._strike(c, "Explosive Fury", ids, mode="save", magical=True, parts=[["3d10", kind]],
                                         sv={"ab": "dex", "dc": F.ki_dc(char), "half": False}))
            return None
        if key in ("telekinetic_master", "telekinetic_master_die"):
            from ...rules.data import rules
            from . import economy as EC
            if key == "telekinetic_master_die":
                self._cf_use(c, "Psionic Energy")
            sp = rules.spell("Telekinesis")
            EC.refund(t, "action")                              # the spell pays its own casting time
            ab = char.mod("int")
            self._say(f"{name} reaches out with a psionic mind (Telekinetic Master)")
            return self._cast_on(c, sp, tgt, slot_level=sp["level"], caster_level=char.total_level, mod=ab,
                                 attack_bonus=char.proficiency_bonus + ab, dc=8 + char.proficiency_bonus + ab, adv=None, paid=True)
        if key == "telekinetic_attack":
            return self._cf_weapon_strike(c, char, tgt, "Telekinetic Master")
        if key == "tales_beyond":
            n = roll(F.bardic_die(char))
            c["tale"] = n
            return self._out(f"{name} tells a tale from beyond ({F.bardic_die(char)} -> {n}): {TALES[n][0]}")
        if key == "tale_bestow":
            return self._tale(c, char, tgt or c)
        if key == "arcane_abjuration":
            return self._abjuration(c, char)
        if key == "cauterizing_flames":
            flames = [fl for fl in self._subc_flames(c) if G.distance_ft(fl["pos"], 1, tgt["pos"], tgt.get("span") or 1) <= 5]
            self.b["flames"].remove(flames[0])
            n = max(1, roll("2d10") + char.mod("wis"))
            if self._hostile(c, tgt):
                return self._out(f"{name} snuffs the spectral flame at {tgt['name']}: " + self._deal(tgt, [[n, "fire"]], by=c, label="Cauterizing Flames"))
            self._heal(tgt, n)
            return self._out(f"{name} snuffs the spectral flame at {tgt['name']}: +{n} HP (Cauterizing Flames)")
        if key == "rapid_strike":
            self._once_per_turn(c, "rapid_strike")
            for e in [e for e in c.get("effects") or [] if (e.get("mods") or {}).get("attacks_with") == "adv"]:
                self._effect_off(c, e, "forgone for Rapid Strike")
            return self._cf_weapon_strike(c, char, tgt, "Rapid Strike")
        return None

    @staticmethod
    def _subc_slot(char, at_least: int) -> Optional[int]:
        """The lowest spell slot of the level or higher that is left."""
        from ...rules import spellcasting as SC
        left = SC.slots_remaining(char)
        levels = sorted(int(k) for k, v in left.items() if k != SC.PACT_KEY and v > 0 and int(k) >= at_least)
        return levels[0] if levels else None

    def _animate(self, c: dict, char, point) -> str:
        """Animating Performance: a Dancing Item (the TCE stat block with the bard's numbers) stands up where the object lay."""
        mid = "Dancing Item|TCE"
        for old in [o for o in self.b["combatants"] if o.get("summoned_by") == c["id"] and o.get("monster") == mid]:
            self._vfx_unsummon(old)                             # one at a time: the first becomes inanimate
            self.remove(old["id"])
        ctx = self._summoner_ctx(c, cls="Bard")
        before = getattr(self, "_summon_point", None)
        self._summon_point = [int(point[0]), int(point[1])]
        try:
            made = self._add_summons(c, mid, 1, None, 1, None, None, None, ctx, "Animating Performance")
        finally:
            self._summon_point = before
        return self._out(f"{c['name']}'s performance animates an object at {self._tile_label(made[0]['pos']) if made and made[0].get('pos') else 'their side'}: "
                         f"a Dancing Item fights for them")

    def _subc_focus_parts(self, R: dict, att: dict, sp: dict, parts: list) -> list:
        """Spiritual Focus (College of Spirits, 6th level): a bard spell that deals damage adds 1d6 to one damage roll."""
        char = self._sheet(att)
        if not parts or not char or att.get("form") or not F.sub_at(char, "Bard", "College of Spirits", 6) or "Bard" not in (sp.get("classes") or []) \
                or R.get("focus_used"):
            return parts
        R["focus_used"] = True
        self._say(f"{att['name']}'s spiritual focus lends the spell +1d6 (Spiritual Focus)")
        return [list(p) for p in parts] + [["1d6", parts[0][1]]]

    def _subc_focus_heal(self, R: dict, att: Optional[dict], sp: dict) -> int:
        char = self._sheet(att) if att else None
        if not char or att.get("form") or not F.sub_at(char, "Bard", "College of Spirits", 6) or "Bard" not in (sp.get("classes") or []) or R.get("focus_used"):
            return 0
        R["focus_used"] = True
        return roll("1d6")

    def _subc_regain_slot(self, who: dict, top: int) -> Optional[int]:
        char = self._sheet(who)
        if not char:
            return None
        used = char.d.get("slots_used") or {}
        lvls = sorted((int(k) for k, v in used.items() if str(k).isdigit() and int(v or 0) > 0 and int(k) <= top), reverse=True)
        if not lvls:
            return None
        used[str(lvls[0])] = int(used[str(lvls[0])]) - 1
        char.save()
        return lvls[0]

    def _shielding_storm(self, c: dict, char):
        kind = {"Desert": "fire", "Sea": "lightning", "Tundra": "cold"}.get(F.choice(char, "storm_aura"), "fire")
        for e in [e for e in c.get("effects") or [] if e["name"] == "Shielding Storm"]:
            self._effect_off(c, e, "renewed")
        self._effect_on(c, "Shielding Storm", [], None, None, None, 10, c["name"], {"resist": [kind], "aura_ft": 10}, None, c["id"])
        self._say(f"{c['name']}'s storm shields the allies within 10 ft: resistance to {kind} (Shielding Storm)")

    def _inspiring_surge(self, c: dict, char):
        """Inspiring Surge: allies within 60 ft that can see or hear the banneret make a weapon attack with their reaction."""
        n = 2 if char.class_level("Fighter") >= 18 else 1
        done = 0
        for o in self.b["combatants"]:
            if done >= n:
                break
            if o is c or self._hostile(c, o) or not self._alive(o) or not o.get("pos") or not c.get("pos") or self._dist(c, o) > 60 \
                    or o.get("conjured") or not self._may_react(o):
                continue
            foe = next(iter(sorted(self._cf_hostiles(o, 5), key=lambda x: self._dist(o, x))), None)
            child = self._opportunity_strike(o, foe) if foe else None
            if child is None:
                continue
            self._spend_reaction(o, "Inspiring Surge")
            child["label"] = "Inspiring Surge"
            self._say(f"{c['name']}'s Inspiring Surge: {o['name']} attacks {foe['name']}")
            self._run_r(child)
            done += 1

    # ------------------------------------------------------------------ battle start, turns
    def _subc_battle_start(self):
        """Blessing of the Forge and Stormborn: what the long rest set up is on from the first round."""
        for c in self.b["combatants"]:
            char = self._sheet(c)
            if not char or c.get("form"):
                continue
            have = {e["name"] for e in c.get("effects") or []}
            if F.sub_at(char, "Cleric", "Forge Domain", 1) and "Blessing of the Forge" not in have:
                armor = char.equipped_armor()
                if armor:
                    self._effect_on(c, "Blessing of the Forge", [], None, None, None, None, c["name"], {"ac": 1}, None, c["id"])
                    self._say(f"{c['name']}'s {armor.get('name', 'armour')} glows with the Blessing of the Forge (+1 AC)")
                else:
                    self._effect_on(c, "Blessing of the Forge", [], None, None, None, None, c["name"], {"weapon_attack": 1, "dmg": (1, "")}, None, c["id"])
                    self._say(f"{c['name']}'s weapon glows with the Blessing of the Forge (+1 to attack and damage)")
            if F.sub_at(char, "Cleric", "Tempest Domain", 17) and "Stormborn" not in have:
                self._effect_on(c, "Stormborn", [], None, None, None, None, c["name"], {"fly": char.speed}, None, c["id"])
                self._say(f"{c['name']} rides the storm: a flying speed of {char.speed} ft (Stormborn)")
            if F.sub_at(char, "Monk", "Way of the Ascendant Dragon", 17) and "Ascendant Aspect" not in have:
                self._effect_on(c, "Ascendant Aspect", [], None, None, None, None, c["name"], {"senses": {"blindsight": 10}}, None, c["id"])

    def _subc_initiative(self, c: dict):
        """Ever-Ready Shot (Arcane Archer 15) and Legion of One (Echo Knight 18): a use back when the fighter rolls initiative with none left."""
        char = self._sheet(c)
        if not char or c.get("form"):
            return
        if F.sub_at(char, "Fighter", "Arcane Archer", 15) and self._cf_left(c, "Arcane Shot", 2, "short") <= 0:
            res = char.d["resources"]
            res["short:Arcane Shot"] = max(0, int(res.get("short:Arcane Shot") or 0) - 1)
            char.save()
            self._say(f"{c['name']} regains a use of Arcane Shot (Ever-Ready Shot)")
        if F.sub_at(char, "Fighter", "Echo Knight", 18) and self._cf_left(c, "Unleash Incarnation", max(1, char.mod("con"))) <= 0:
            res = char.d["resources"]
            res["feature:Unleash Incarnation"] = max(0, int(res.get("feature:Unleash Incarnation") or 0) - 1)
            char.save()
            self._say(f"{c['name']} regains a use of Unleash Incarnation (Legion of One)")

    def _subc_after_rage(self, c: dict, char):
        """What a rage begins with: Call the Hunt (a Beast barbarian's allies hit harder), Shielding Storm."""
        if F.sub_at(char, "Barbarian", "Path of the Storm Herald", 10):
            self._shielding_storm(c, char)
        if F.sub_at(char, "Barbarian", "Path of the Beast", 14) and self._cf_left(c, "Call the Hunt", char.proficiency_bonus) > 0:
            near = [o for o in self.b["combatants"] if o is not c and not self._hostile(c, o) and self._alive(o) and o.get("pos") and c.get("pos")
                    and self._dist(c, o) <= 30 and self._sees(c, o) and not o.get("conjured")][:max(1, char.mod("con"))]
            if near:
                self._cf_use(c, "Call the Hunt")
                self._give_temp(c, 5 * len(near))
                for o in near:
                    self._effect_on(o, "Call the Hunt", [], None, None, None, 10, c["name"], {"hunt_die": True}, None, c["id"])
                self._say(f"{c['name']} calls the hunt: {', '.join(o['name'] for o in near)} join in ({5 * len(near)} temporary HP; +1d6 damage once a turn)")

    def _subc_turn_end(self, c: dict):
        """A Shadow monk's cloak ends in bright light; a Zealot's rage ends: death comes if the fatal blow was held off; Guardian Spirit heals."""
        for e in [e for e in c.get("effects") or [] if (e.get("mods") or {}).get("shadow_cloak")]:
            if c.get("pos") and not self._cf_dark(self._subc_feet(c)):
                self._effect_off(c, e, "bright light")
        self._subc_rbd_check(c)
        for o in self.b["combatants"]:                          # Strength before Death: the extra turn ends with the turn it interrupted
            if o.get("sbd") and o is not c:
                o.pop("sbd", None)
                oc_ = self._sheet(o)
                if oc_ and oc_.current_hp <= 0 and "Unconscious" not in oc_.d.get("conditions", []):
                    oc_.d.setdefault("conditions", []).append("Unconscious")
                    oc_.save()
                    self._say(f"{o['name']}'s extra turn is over: they fall unconscious")
        owner = self._find_or_none(c.get("summoned_by")) if c.get("summoned_by") is not None else None
        oc = self._sheet(owner) if owner is not None else None
        if oc and owner is not c and F.sub_at(oc, "Druid", "Circle of the Shepherd", 10) and self._alive(c) and self._alive(owner) and c.get("pos") and owner.get("pos") \
                and self._dist(owner, c) <= 30 and self._subc_has(owner, "Spirit Totem (Bear)") \
                and any(k in self._ctype(self._monster(c)) for k in ("beast", "fey")):
            n = max(1, oc.class_level("Druid") // 2)
            self._heal(c, n)
            self._say(f"{c['name']} is mended by the spirit totem: +{n} HP (Guardian Spirit)")

    # ------------------------------------------------------------------ Rage beyond Death, Faithful Summons
    def _subc_zero_hp(self, c: dict, dealt: int, types, crit: bool) -> bool:
        """Dropped to 0: Rage beyond Death (a raging Zealot stays on its feet), Faithful Summons (a Shepherd's four beasts). True: stays at 1 HP."""
        char = self._sheet(c)
        if not char or c.get("form"):
            return False
        if F.sub_at(char, "Barbarian", "Path of the Zealot", 14) and self._raging(c):
            c["rbd"] = True
            if "Unconscious" in char.d.get("conditions", []):
                char.d["conditions"].remove("Unconscious")
                char.save()
            self._say(f"{c['name']}'s rage refuses to let go: still up at 0 hit points (Rage beyond Death)")
        if F.sub_at(char, "Fighter", "Samurai", 18) and self._cf_left(c, "Strength before Death", 1) > 0 and (c.get("turn") or {}).get("reaction", 0) > 0 and not c.get("sbd"):
            self._cf_use(c, "Strength before Death")
            self._spend_reaction(c, "Strength before Death")
            c["sbd"] = True
            if "Unconscious" in char.d.get("conditions", []):
                char.d["conditions"].remove("Unconscious")
                char.save()
            self._fresh_turn(c)                                 # the extra turn: a whole new budget, right now
            c["turn"]["reaction"] = 0
            self._say(f"{c['name']}'s fighting spirit delays the fall: an extra turn at 0 hit points, then down (Strength before Death)")
        if F.sub_at(char, "Druid", "Circle of the Shepherd", 14) and self._cf_left(c, "Faithful Summons", 1) > 0:
            self._faithful_summons(c)
        if F.sub_at(char, "Druid", "Circle of Wildfire", 14) and self._cf_left(c, "Blazing Revival", 1) > 0:
            spirit = next((o for o in self.b["combatants"] if o.get("summoned_by") == c["id"] and o.get("monster") == "Wildfire Spirit|TCE" and o.get("pos")
                           and self._hp_of(o) > 0 and c.get("pos") and self._dist(c, o) <= 120), None)
            if spirit is not None:
                self._cf_use(c, "Blazing Revival")
                self._say(f"{c['name']}'s wildfire spirit gives itself up: " + self._deal(spirit, [[self._hp_of(spirit), ""]], by=c, label="Blazing Revival"))
                self._set_hp(c, max(1, self._max_hp(c) // 2))
                self._say(f"{c['name']} rises with {self._hp_of(c)} hit points (Blazing Revival)")
                return True
        return False

    def _faithful_summons(self, c: dict):
        pick = next((m["id"] for n in ("Saber-Toothed Tiger", "Giant Boar", "Polar Bear", "Wolf") for m in bestiary.all
                     if m["name"] == n and m.get("source") in ("MM", "PHB")), None)
        if pick is None:
            return
        self._cf_use(c, "Faithful Summons")
        made = self._add_summons(c, pick, 4, None, 9, None, None, None, None, "Faithful Summons")
        self._say(f"{c['name']}'s nature spirits answer: {len(made)} beasts appear to protect them (Faithful Summons)")

    def _subc_rbd_check(self, c: dict):
        if not c.get("rbd"):
            return
        char = self._sheet(c)
        if not char:
            c.pop("rbd", None)
            return
        raging = bool(self._fx(c, "rage"))
        ds = char.d.get("death_saves") or {}
        if char.current_hp > 0:
            c.pop("rbd", None)
            c.pop("rbd_dead", None)
        elif raging and int(ds.get("failure") or 0) >= 3:
            ds["failure"] = 2
            c["rbd_dead"] = True
            char.save()
            self._say(f"{c['name']}'s rage holds death off until it ends (Rage beyond Death)")
        elif not raging:
            c.pop("rbd", None)
            if c.pop("rbd_dead", None):
                ds["failure"] = 3
            if "Unconscious" not in char.d.get("conditions", []):
                char.d.setdefault("conditions", []).append("Unconscious")
            char.save()
            self._say(f"{c['name']}'s rage ends: " + ("death takes them" if ds.get("failure", 0) >= 3 else "they fall unconscious"))

    def _subc_dsave_done(self, c: dict, char, roll_: int):
        """A death save rolled while Rage beyond Death keeps the Zealot up: a third failure waits for the end of the rage."""
        if c.get("rbd") and self._fx(c, "rage"):
            self._subc_rbd_check(c)

    def _subc_dealt(self, tgt: dict, by: Optional[dict], types, taken: int):
        if tgt.get("rbd") and taken > 0:
            self._subc_rbd_check(tgt)

    def _subc_keeps_rage(self, c: dict) -> bool:
        return bool(c.get("rbd"))

    # ------------------------------------------------------------------ rolls and spells
    def _subc_mode(self, c: dict, mode, why: list):
        """Drunkard's Luck: 2 ki cancel the disadvantage on an attack roll or a saving throw."""
        if mode != "dis":
            return mode
        char = self._sheet(c)
        if char and not c.get("form") and F.sub_at(char, "Monk", "Way of the Drunken Master", 11) and self._resource_left(c, "Ki Points") >= 2:
            self._use_resource(c, "Ki Points", 2)
            why.append("Drunkard's Luck")
            self._say(f"{c['name']} spends 2 ki: a lucky bounce cancels the disadvantage (Drunkard's Luck)")
            return None
        return mode

    def _subc_leap(self, c: dict) -> bool:
        """Leap to Your Feet: a Drunken Master stands up for 5 ft of movement."""
        char = self._sheet(c)
        return bool(char) and not c.get("form") and (F.sub_at(char, "Monk", "Way of the Drunken Master", 6) or self._nf_leap(c))

    def _subc_max_heal(self, att: Optional[dict], tgt: dict) -> bool:
        """Circle of Mortality: a healing spell's dice count at their maximum for a creature at 0 hit points."""
        char = self._sheet(att) if att is not None else None
        return bool(char) and not att.get("form") and F.sub_at(char, "Cleric", "Grave Domain", 1) and self._hp_of(tgt) <= 0

    def _subc_spec(self, att: dict, sp: dict, spec: dict) -> dict:
        """Circle of Mortality: spare the dying is a bonus action with a range of 30 feet."""
        char = self._sheet(att)
        if char and not att.get("form") and sp["name"].lower() == "spare the dying" and F.sub_at(char, "Cleric", "Grave Domain", 1):
            return dict(spec, cost="bonus", range=30, range_kind="ranged")
        if not char and spec.get("cost") == "action" and self._economy_on():
            _s, multi = self._entry_section(att, "Multiattack")        # "The professor can replace one of the attacks with a use of Spellcasting"
            rep = re.search(r"replace (one|two|three|up to two|up to three|any number of)\b[^.]*?\bwith (?:a use of |casting )?(?:its |their |her |his )?(?:the )?spellcasting",
                            multi.get("text", ""), re.I) if multi else None
            allowed = {"one": 1, "two": 2, "up to two": 2, "three": 3, "up to three": 3}.get((rep.group(1) if rep else "").lower(), 9)
            if rep and int((att.get("turn") or {}).get("multi_spell") or 0) < allowed:
                return dict(spec, cost="multi")
        if char and not att.get("form"):
            return self._nf_bonus_cost(att, sp, spec)               # Arcane Safeguard's Resistance, Spellfire Flame (newfeats.py)
        return spec

    def _subc_attack_floor(self, c: dict, attacks: int) -> int:
        for _e, n in self._fxs(c, "attack_floor"):
            attacks = max(attacks, int(n))
        return attacks

    # ------------------------------------------------------------------ weapon and hit hooks
    def _subc_weapon_atk(self, att: dict, w: dict, atk: dict) -> dict:
        """One with the Blade (kensei weapons are magical), the astral arms marked for Empowered Arms."""
        char = self._sheet(att)
        if not char or att.get("form"):
            return atk
        if F.sub_at(char, "Monk", "Way of the Kensei", 6) and self._subc_kensei(att, atk):
            atk["magical"] = True
        if "unarmed" in (w.get("props") or []) and self._fx(att, "astral_arms"):
            atk["astral"] = True
        return atk

    def _subc_hit_parts(self, att: dict, tgt: dict, R: dict, char) -> list:
        """[(dice, type, label)] added to a hit: Empowered Arms, Call the Hunt; Ferocious Charger knocks the target prone."""
        a = R.get("atk") or {}
        out = []
        if a.get("astral") and self._subc_astral_body(att) and self._once_per_turn(att, "empowered_arms"):
            out.append((F.martial_die(char) or "1d4", "force", "Empowered Arms"))
        if a.get("weapon") and any((e.get("mods") or {}).get("hunt_die") for e in att.get("effects") or []) and self._once_per_turn(att, "call_the_hunt"):
            out.append(("1d6", (a.get("parts") or [["", ""]])[0][1] or "", "Call the Hunt"))
        if char and F.sub_at(char, "Fighter", "Cavalier", 15) and a.get("weapon") and a.get("melee") and tgt is not att and self._alive(tgt) \
                and self.b.get("turn") == att["id"] and self._charged(att, tgt, 10) and self._once_per_turn(att, "ferocious_charger"):
            self._apply_save(R, att, tgt, {"ab": "str", "dc": self._cf_dc(char, "str"), "conds": ["Prone"]})
        return out

    def _subc_may_target(self, att: dict, tgt: dict) -> Optional[str]:
        """Nature's Sanctuary: a beast or plant that attacks a Land druid makes a Wisdom save or looks for another target (once a day each)."""
        char = self._sheet(tgt)
        if not char or tgt.get("form") or not F.sub_at(char, "Druid", "Circle of the Land", 14) or K.incapacitated(self._conds(tgt)):
            return None
        if not any(k in self._ctype(self._monster(att)) for k in ("beast", "plant")) or self._sheet(att):
            return None
        done = att.setdefault("nat_sanct", [])
        if tgt["id"] in done:
            return None
        dc = self._spell_dc(tgt)
        res = self._saving_throw(att, "wis", dc, spell=True, source=tgt, label="Nature's Sanctuary")
        if res["ok"]:
            done.append(tgt["id"])                                  # a success: immune for 24 hours
            return None
        return f"{att['name']} can't bring itself to attack {tgt['name']} (Nature's Sanctuary, WIS {res['total']} vs DC {dc})"

    def _subc_summoned(self, att: dict, sp: dict, made: list):
        """Mighty Summoner: beasts and fey the Shepherd conjures have 2 more hit points per Hit Die and magical natural weapons."""
        char = self._sheet(att)
        if not char or att.get("form") or not made or not F.sub_at(char, "Druid", "Circle of the Shepherd", 6):
            return
        done = []
        for o in made:
            m = self._monster(o) or {}
            if not any(k in str(m.get("type") or "").lower() for k in ("beast", "fey")):
                continue
            try:
                dice = int(str(m.get("hp_formula") or "1d8").split("d")[0])
            except ValueError:
                dice = 1
            o["max_hp"] = int(o.get("max_hp") or 0) + 2 * dice
            o["hp"] = int(o.get("hp") or 0) + 2 * dice
            self._effect_on(o, "Mighty Summoner", [], None, None, None, None, att["name"], {"magic_attacks": True}, None, att["id"])
            done.append(o["name"])
        if done:
            self._say(f"{att['name']}'s Mighty Summoner: {', '.join(done)} are sturdier and strike with magic")

    def _subc_after_hit(self, R: dict, att: Optional[dict], tgt: dict):
        """Spiked Retribution: a creature within 5 ft that hits a raging Battlerager in spiked armor takes 3 piercing damage."""
        a = R.get("atk") or {}
        char = self._sheet(tgt)
        if att is None or att is tgt or not char or tgt.get("form") or not a.get("melee") or not self._raging(tgt) or not self._alive(att) \
                or not F.sub_at(char, "Barbarian", "Path of the Battlerager", 14) or not self._subc_spiked(char) \
                or K.incapacitated(self._conds(tgt)) or (att.get("pos") and tgt.get("pos") and self._dist(att, tgt) > 5):
            return
        self._say(f"{tgt['name']}'s Spiked Retribution: " + self._deal(att, [[3, "piercing"]], by=tgt, label="Spiked Retribution"))

    # ------------------------------------------------------------------ reactions
    def _subc_vigil_ok(self, o: dict) -> bool:
        """Vigilant Defender: the special reaction for an opportunity attack, once on every other creature's turn, not on the turn the normal reaction goes."""
        char = self._sheet(o)
        if not char or o.get("form") or not F.sub_at(char, "Fighter", "Cavalier", 18) or self.b.get("turn") == o["id"] or not self._can_act(o):
            return False
        now = [self.b.get("round"), self.b.get("turn")]
        t = o.get("turn") or {}
        return o.get("vigil_at") != now and t.get("react_at") != now

    def _subc_eligible(self, out: list, window: str, R: dict, att: Optional[dict], tgt: Optional[dict], ctx: dict):
        cur = R.get("cur") or {}
        a = R.get("atk") or {}
        if window == "declared" and att and tgt and R.get("mode") == "attack":
            ac_ = self._sheet(att)
            if ac_ and not att.get("form") and "unarmed" in (a.get("props") or []) and F.sub_at(ac_, "Monk", "Way of the Kensei", 3) \
                    and not self._subc_has(att, "Agile Parry") and any(w for w in ac_.attacks() if "unarmed" not in (w.get("props") or []) and not w.get("ranged")
                                                                       and "heavy" not in (w.get("props") or [])):
                self._effect_on(att, "Agile Parry", [], None, None, None, None, att["name"], {"ac": 2}, None, att["id"], until={"start": att["id"]})
                self._say(f"{att['name']} defends with the kensei weapon: +2 AC until the next turn (Agile Parry)")
        elif window == "on_hit" and att and tgt and tgt is not att and self._alive(tgt) and R.get("mode") == "attack":
            ac_ = self._sheet(att)
            if ac_ and F.sub_at(ac_, "Monk", "Way of the Kensei", 6) and self._subc_kensei(att, a) and self._cf_turn_free(att, "deft_strike") \
                    and self._resource_left(att, "Ki Points") >= 1:
                self._cf_offer(out, att, "free", [{"key": "deft_strike", "label": f"Deft Strike (1 ki: +{F.martial_die(ac_) or '1d4'})", "detail": ""}],
                               f"{att['name']} hits {tgt['name']}. Add something?")
        elif window == "missed" and att and tgt and tgt is not att and R.get("mode") == "attack":
            tc = self._sheet(tgt)
            if tc and not tgt.get("form") and a.get("melee") and F.sub_at(tc, "Monk", "Way of the Drunken Master", 6) and self._may_react(tgt) \
                    and self._resource_left(tgt, "Ki Points") >= 1 and tgt.get("pos"):
                near = [o for o in self.b["combatants"] if o is not tgt and o is not att and o.get("pos") and self._alive(o) and self._hostile(tgt, o)
                        and self._dist(tgt, o) <= 5][:3]
                opts = [{"key": f"tipsy_sway:{o['id']}", "label": f"Redirect Attack (1 ki): the blow hits {o['name']}", "detail": ""} for o in near]
                self._cf_offer(out, tgt, "reaction", opts, f"{att['name']} misses {tgt['name']}. Redirect the attack?", "missed")
            ac_ = self._sheet(att)
            if ac_ and not att.get("form") and F.sub_at(ac_, "Fighter", "Arcane Archer", 7) and not a.get("melee") and a.get("weapon") \
                    and self._cf_left(att, "Arcane Shot", 2, "short") > 0 and self._may_react(att, "bonus") and self.b.get("turn") == att["id"]:
                if [o for o in self.b["combatants"] if o is not att and o is not tgt and o.get("pos") and tgt.get("pos") and self._alive(o)
                        and self._hostile(att, o) and self._dist(o, tgt) <= 60]:
                    self._cf_offer(out, att, "free", [{"key": "curving_shot", "label": "Curving Shot: reroll the attack against another foe within 60 ft of it", "detail": ""}],
                                   f"{att['name']} misses {tgt['name']}. Add something?", "missed")
        elif window == "after_damage" and att and tgt and tgt is not att and self._alive(att) and R.get("mode") == "attack" and a.get("melee"):
            tc = self._sheet(tgt)
            if tc and not tgt.get("form") and F.sub_at(tc, "Monk", "Way of the Sun Soul", 17) and self._may_react(tgt) and att.get("pos") and tgt.get("pos") \
                    and self._dist(att, tgt) <= 5:
                self._cf_offer(out, tgt, "reaction", [{"key": "sun_shield", "label": f"Sun Shield: {5 + tc.mod('wis')} radiant damage to {att['name']}", "detail": ""}],
                               f"{att['name']} hit {tgt['name']} in melee. Sun Shield?", "after_damage")
        elif window == "damage" and tgt:
            tc = self._sheet(tgt)
            total = sum(n for n, _t in cur.get("dmg") or [])
            for e, _v in self._fx(tgt, "bond") if total > 0 else []:
                src = self._find_or_none(e.get("source_id"))
                sc = self._sheet(src) if src else None
                if not sc or not F.sub_at(sc, "Cleric", "Peace Domain", 6):
                    continue
                far = 60 if F.sub_at(sc, "Cleric", "Peace Domain", 17) else 30
                for o in self.b["combatants"]:
                    if o is tgt or not o.get("pos") or not tgt.get("pos") or not self._alive(o) or not self._may_react(o) or self._dist(o, tgt) > far \
                            or not any(x.get("source_id") == e.get("source_id") for x, _vv in self._fx(o, "bond")) or self._ek_spot(o, tgt) is None:
                        continue
                    self._cf_offer(out, o, "reaction", [{"key": "protective_bond", "label": f"Protective Bond: step in and take {tgt['name']}'s damage", "detail": ""}],
                                   f"{tgt['name']} is about to take {total} damage. {o['name']}: take it instead?")
                break
            hit = sum(n for n, t_ in cur.get("dmg") or [] if t_ in ENERGY)
            if tc and hit > 0 and not tgt.get("form") and self._subc_astral_body(tgt) and self._may_react(tgt):
                self._cf_offer(out, tgt, "reaction", [{"key": "deflect_energy", "label": f"Deflect Energy (-1d10{tc.mod('wis'):+d} of that damage)", "detail": ""}],
                               f"{tgt['name']} is about to take {hit} energy damage from {R['label']}. React?")
        elif window == "leave":
            mover = self._find_or_none(ctx.get("mover"))
            for oid in ctx.get("threats") or []:
                o = self._find_or_none(oid)
                if mover and o and self._subc_vigil_ok(o) and not self._may_react(o):
                    self._cf_offer(out, o, "free", [{"key": "vigil_oa", "label": f"Vigilant Defender: opportunity attack on {mover['name']}", "detail": ""}],
                                   f"{mover['name']} is leaving {o['name']}'s reach. Vigilant Defender?")

    def _subc_react(self, window: str, R: dict, reactor: dict, fam: str, arg: str, ctx: dict) -> bool:
        """What these features' reactions do (False: not one of them)."""
        cur = R.setdefault("cur", {})
        char = self._sheet(reactor)
        name = reactor["name"]
        att = self._find_or_none(ctx.get("attacker") or R.get("actor"))
        if fam == "hand_of_harm" and char and F.sub_at(char, "Monk", "Way of Mercy", 6):
            tgt = self._find_or_none(ctx.get("target"))
            if tgt is not None:
                self._effect_on(tgt, "Poisoned (Hand of Harm)", ["Poisoned"], None, None, None, None, name, {}, None, reactor["id"], until=self._subc_own_end(reactor))
                self._line(R, f"{tgt['name']} is poisoned until the end of {name}'s next turn (Physician's Touch)", "poisoned")
            return False
        if fam == "deft_strike":
            self._use_resource(reactor, "Ki Points", 1)
            self._once_per_turn(reactor, "deft_strike")
            cur.setdefault("bonus_parts", []).append([F.martial_die(char) or "1d4", ((R.get("atk") or {}).get("parts") or [["", ""]])[0][1] or ""])
            self._line(R, f"{name} spends 1 ki: the weapon bites deeper (Deft Strike)", "Deft Strike")
            return True
        if fam == "tipsy_sway":
            new = self._find_or_none(int(arg)) if str(arg or "").isdigit() else None
            if new is None or att is None:
                return True
            self._use_resource(reactor, "Ki Points", 1)
            ac = self._ac_of(new)
            cur.update(total=max(int(cur.get("total") or 0), ac), kept=max(2, int(cur.get("kept") or 2)), crit=False)
            if R.get("ti", 0) < len(R.get("targets") or []):
                R["targets"][R["ti"]] = new["id"]
            self._line(R, f"{name} sways aside: {att['name']}'s blow lands on {new['name']} instead (Redirect Attack)", "Redirect Attack")
            return True
        if fam == "sun_shield" and att:
            self._line(R, "Sun Shield: " + self._deal(att, [[5 + max(-4, char.mod("wis")), "radiant"]], by=reactor, label="Sun Shield"), "Sun Shield")
            return True
        if fam == "deflect_energy":
            cut = max(1, roll("1d10") + char.mod("wis"))
            left, after = cut, []
            for n, t_ in cur.get("dmg") or []:
                take = min(n, left) if t_ in ENERGY else 0
                left -= take
                after.append([n - take, t_])
            cur["dmg"] = after
            self._line(R, f"{name} deflects the energy: -{cut - left} damage (Deflect Energy)", "Deflect Energy")
            return True
        if fam == "curving_shot":
            foes = [o for o in self.b["combatants"] if o is not reactor and o.get("pos") and self._alive(o) and self._hostile(reactor, o)]
            tgt = self._find_or_none(ctx.get("target"))
            foes = [o for o in foes if o is not tgt and tgt and tgt.get("pos") and self._dist(o, tgt) <= 60]
            if not foes:
                return True
            self._pay(reactor, "bonus", "Curving Shot")
            new = min(foes, key=lambda o: self._dist(reactor, o))
            a = R.get("atk") or {}
            try:
                res = self._attack_check(reactor, new, a)
            except Exception:  # noqa: BLE001 - out of range: nothing happens
                return True
            R["targets"][R["ti"]] = new["id"]
            cur.update(total=res["total"], kept=res["kept"], crit=res["crit"], hit=res["hit"], ac=res["ac"])
            self._line(R, f"{name} bends the shot toward {new['name']}: {res['total']} vs AC {res['ac']} (Curving Shot)", "Curving Shot")
            return True
        if fam == "protective_bond":
            tgt = self._find_or_none(ctx.get("target"))
            spot = self._ek_spot(reactor, tgt) if tgt else None
            if tgt is None or spot is None:
                return True
            self._cf_teleport(reactor, spot)
            if R.get("ti", 0) < len(R.get("targets") or []):
                R["targets"][R["ti"]] = reactor["id"]
            e = next((e for e, _v in self._fx(reactor, "bond")), None)
            src = self._find_or_none(e.get("source_id")) if e else None
            sc = self._sheet(src) if src else None
            if sc and F.sub_at(sc, "Cleric", "Peace Domain", 17):
                cur["dmg"] = [[n // 2, t_] for n, t_ in cur.get("dmg") or []]
            self._line(R, f"{name} bursts across the bond and takes the blow meant for {tgt['name']} (Protective Bond)", "Protective Bond")
            if R.get("win"):
                R["win"]["queue"] = []                              # one creature takes the damage, not two
            return True
        if fam == "vigil_oa":
            mover = self._find_or_none(ctx.get("mover"))
            if mover is None:
                return True
            reactor["vigil_at"] = [self.b.get("round"), self.b.get("turn")]
            child = self._opportunity_strike(reactor, mover)
            if child is not None:
                child["atk"]["opportunity"] = True
                child["label"] = "Vigilant Defender"
                self._stack().append(child)
            return True
        return False

    # ------------------------------------------------------------------ Cleric: Arcana, Order, Death; Druid: Wildfire
    def _abjuration(self, c: dict, char) -> str:
        """Arcane Abjuration: celestials, elementals, fey and fiends within 30 ft are turned; those of a low enough CR are banished (5th level)."""
        lv = char.class_level("Cleric")
        top = max((cr for n, cr in BANISH_CR.items() if lv >= n), default=None)
        near = [o for o in self._cf_hostiles(c, 30) if any(k in self._ctype(self._monster(o)) for k in ("celestial", "elemental", "fey", "fiend"))
                and self._sees(o, c)]
        if not near:
            return self._out(f"{c['name']} presents a holy symbol: nothing otherworldly within 30 ft that can see it")
        dc = self._cf_dc(char, "wis")
        gone = [o for o in near if top is not None and float((self._monster(o) or {}).get("cr_num") or 0) <= top]
        turned = [o for o in near if o not in gone]
        out = f"{c['name']} abjures the otherworldly"
        if turned:
            out = self._run_r(self._strike(c, "Arcane Abjuration", [o["id"] for o in turned], mode="save", magical=True, parts=[],
                                           sv={"ab": "wis", "dc": dc, "half": False, "conds": ["Frightened"], "rounds": 10, "ends_on": ["damage"],
                                               "note": "turned: flees", "mods": {"turned": True}}))
        if gone:
            out = self._run_r(self._strike(c, "Arcane Banishment", [o["id"] for o in gone], mode="save", magical=True, parts=[],
                                           sv={"ab": "wis", "dc": dc, "half": False, "conds": ["Incapacitated"], "rounds": 10, "note": "banished",
                                               "mods": {"banished": True, "untargetable": True}}))
        return out

    def _subc_healed(self, att: Optional[dict], targets: list, sp: dict, level: int) -> List[str]:
        """Spell Breaker: a healing spell of 1st level or higher also ends one spell of the slot's level or lower on the creature it heals."""
        from ...rules.data import rules
        char = self._sheet(att) if att else None
        if not char or att.get("form") or not F.sub_at(char, "Cleric", "Arcana Domain", 6) or not sp.get("level"):
            return []
        out = []
        for t in targets:
            for e in list(t.get("effects") or []):
                spell = rules.spell(re.sub(r"\s*\(.*\)$", "", e["name"])) if not e.get("feature") and not e.get("trait") else None
                if spell and 1 <= int(spell.get("level") or 0) <= int(level or sp["level"]) and e.get("source_id") != att["id"]:
                    self._effect_off(t, e, "Spell Breaker")
                    out.append(f"{t['name']} sheds {e['name']} (Spell Breaker)")
                    break
        return out

    def _subc_spell_done(self, R: dict, att: Optional[dict], sp: dict):
        """Voice of Authority: an ally a 1st-level-or-higher spell was cast on makes a weapon attack with its reaction, at a creature the cleric sees."""
        char = self._sheet(att) if att else None
        if not char or att.get("form") or not F.sub_at(char, "Cleric", "Order Domain", 1) or not sp.get("level") or int(R.get("slot_level") or 0) < 1:
            return
        for tid in dict.fromkeys(R.get("targets") or []):
            o = self._find_or_none(tid)
            if o is None or o is att or self._hostile(att, o) or not self._alive(o) or not o.get("pos") or not self._may_react(o) or o.get("conjured"):
                continue
            oc = self._sheet(o)
            for foe in sorted([x for x in self._cf_hostiles(att, 120) if self._sees(att, x)], key=lambda x: self._dist(o, x)):
                child = None
                try:
                    if oc and not o.get("form"):
                        w, atk = self._cf_weapon(o, oc, foe)
                        atk["n"] = 1
                        child = self._strike(o, f"{w['name']} (Voice of Authority)", [foe["id"]], mode="attack", atk=atk, magical=atk.get("magical", False))
                    elif self._dist(o, foe) <= 5:
                        child = self._opportunity_strike(o, foe)
                except Exception:  # noqa: BLE001 - nothing within that ally's reach
                    child = None
                if child is not None:
                    self._spend_reaction(o, "Voice of Authority")
                    self._say(f"{att['name']}'s Voice of Authority: {o['name']} attacks {foe['name']}")
                    self._stack().append(child)
                    return

    def _subc_pierce(self, by: Optional[dict], spell: bool, label: str) -> bool:
        """Inescapable Destruction: necrotic damage from a Death cleric's spells and Channel Divinity ignores resistance."""
        char = self._sheet(by) if by is not None else None
        return bool(char) and not by.get("form") and F.sub_at(char, "Cleric", "Death Domain", 6) and (spell or label in ("Touch of Death",))

    def _subc_bond_ft(self, o: dict) -> int:
        """How far apart bonded creatures can be: 30 ft, 60 ft with Expansive Bond."""
        for e, _v in self._fx(o, "bond"):
            src = self._find_or_none(e.get("source_id"))
            if src and F.sub_at(self._sheet(src), "Cleric", "Peace Domain", 17):
                return 60
        return 30

    def _subc_more_duplicates(self, c: dict, char, sp: dict, first: dict):
        """Improved Duplicity (Trickery 17): Invoke Duplicity makes four duplicates, not one."""
        if not F.sub_at(char, "Cleric", "Trickery Domain", 17) or not first.get("pos"):
            return
        made = 1
        x0, y0 = first["pos"]
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1), (1, 1), (-1, -1), (1, -1), (-1, 1), (2, 0), (-2, 0)):
            if made >= 4:
                break
            x, y = x0 + dx, y0 + dy
            if self._tile_ok({"id": -1, "span": 1}, x, y):
                self._conjure_token(c, sp, {"name": "Duplicate", "move": 30}, {"point": [x, y]}, [], c["id"])
                made += 1
        self._say(f"{c['name']}'s Improved Duplicity: {made} duplicates stand ready (move them one at a time with the bonus action)")

    def _subc_flames(self, c: dict) -> list:
        now = int(self.b.get("round") or 1)
        return [fl for fl in self.b.get("flames") or [] if fl.get("owner") == c["id"] and fl["round"] + 10 >= now and fl.get("pos")]

    def _subc_killed(self, c: dict):
        """Cauterizing Flames: a Small or larger creature that dies within 30 ft of a Wildfire druid or its spirit leaves a spectral flame."""
        if not c.get("pos") or (self._monster(c) or {}).get("size") == "Tiny" or c.get("conjured"):
            return
        for d in self.b["combatants"]:
            dc = self._sheet(d)
            if not dc or d.get("form") or d is c or not F.sub_at(dc, "Druid", "Circle of Wildfire", 10) or not self._alive(d):
                continue
            spirit = next((o for o in self.b["combatants"] if o.get("summoned_by") == d["id"] and o.get("monster") == "Wildfire Spirit|TCE" and o.get("pos")), None)
            if (d.get("pos") and self._dist(d, c) <= 30) or (spirit and self._dist(spirit, c) <= 30):
                self.b.setdefault("flames", []).append({"owner": d["id"], "pos": list(c["pos"]), "round": int(self.b.get("round") or 1)})
                self._say(f"A spectral flame flickers where {c['name']} fell (Cauterizing Flames)")

    # ------------------------------------------------------------------ Bard: Spirits, Eloquence, Creation
    def _tale(self, c: dict, char, tgt: dict) -> str:
        """Bestow the tale the bard keeps in mind on a creature (the Spirit Tales table)."""
        n = int(c.pop("tale"))
        die = F.bardic_die(char)
        d = die[1:]
        cha = char.mod("cha")
        name = c["name"]
        title = TALES[n][0]
        dc = self._spell_dc(c)
        until_next = {"end": tgt["id"], "skip": 1 if self.b.get("turn") == tgt["id"] else 0}
        say = lambda txt: self._out(f"{name}'s Tale of the {title}: {txt}")
        if n == 1:
            self._effect_on(tgt, "Tale of the Clever Animal", [], None, None, None, 100, name, {"check": die}, None, c["id"])
            return say(f"{tgt['name']} adds {die} to its checks for 10 minutes")
        if n == 2:
            atk = {"bonus": char.proficiency_bonus + cha, "n": 1, "melee": True, "spell": True, "reach": 5, "magical": True,
                   "parts": [[f"2{d}{cha:+d}" if cha else f"2{d}", "force"]]}
            atk = self._check_reach(c, tgt, atk)
            return self._run_r(self._strike(c, "Tale of the Renowned Duelist", [tgt["id"]], mode="attack", atk=atk, magical=True))
        if n == 3:
            pals = [o for o in self.b["combatants"] if o is not tgt and not self._hostile(tgt, o) and self._alive(o) and o.get("pos") and tgt.get("pos")
                    and self._dist(o, tgt) <= 5][:1]
            amount = max(1, roll(die) + cha)
            for o in [tgt] + pals:
                self._give_temp(o, amount)
            return say(f"{amount} temporary hit points for {', '.join(o['name'] for o in [tgt] + pals)}")
        if n == 4:
            self._effect_on(tgt, "Tale of the Runaway", [], None, None, None, None, name, {"no_opportunity": True}, None, c["id"], until=until_next)
            t = tgt.get("turn")
            if t is not None:
                t["move"] = int(t.get("move", 0)) + 30
            return say(f"{tgt['name']} slips away: 30 ft more movement, no opportunity attacks")
        if n == 5:
            self._effect_on(tgt, "Tale of the Avenger", [], None, None, None, 10, name, {"retaliate": (die, "force")}, None, c["id"])
            return say(f"melee attackers on {tgt['name']} take {die} force damage for a minute")
        if n == 6:
            amount = max(1, roll(die) + char.class_level("Bard"))
            self._give_temp(tgt, amount)
            self._effect_on(tgt, "Tale of the Traveler", [], None, None, None, None, name, {"speed": 10, "ac": 1, "temp_ends": True}, None, c["id"])
            return say(f"{tgt['name']} has {amount} temporary hit points, +10 ft speed and +1 AC")
        if n in (7, 12):
            cond, ab, times = (["Incapacitated"], "wis", 2) if n == 7 else (["Stunned"], "int", 3)
            return self._run_r(self._strike(c, f"Tale of the {title}", [tgt["id"]], mode="save", magical=True, spell=True, parts=[[f"{times}{d}", "psychic"]],
                                            sv={"ab": ab, "dc": dc, "half": False, "conds": cond, "until": "target_end_next"}))
        if n == 8:
            self._effect_on(tgt, "Tale of the Phantom", ["Invisible"], None, None, None, None, name, {"ends_on": ["attack"], "dmg": (die, "necrotic"), "once": True},
                            None, c["id"], until=until_next)
            return say(f"{tgt['name']} fades from sight until its next turn ends or it strikes")
        if n == 9:
            ids = [o["id"] for o in self.b["combatants"] if self._hostile(tgt, o) and o.get("pos") and tgt.get("pos") and self._alive(o) and self._dist(o, tgt) <= 30
                   and self._sees(tgt, o)]
            return self._run_r(self._strike(c, "Tale of the Brute", ids, mode="save", magical=True, spell=True, parts=[[f"3{d}", "thunder"]],
                                            sv={"ab": "str", "dc": dc, "half": True, "conds": ["Prone"]}))
        if n == 10:
            foe = next(iter(sorted([o for o in self.b["combatants"] if self._hostile(tgt, o) and o.get("pos") and self._alive(o)], key=lambda o: self._dist(tgt, o))), None)
            if foe is None or not tgt.get("pos"):
                return say(f"{tgt['name']} has nobody to breathe on")
            aim = G.centre(foe["pos"], foe.get("span") or 1)
            tiles = G.area_for({"shape": "cone", "size": 30, "origin": "caster"}, tgt["pos"], tgt.get("span") or 1, tuple(aim), *self._bounds())
            ids = [o["id"] for o in G.creatures_in(tiles, self.b["combatants"]) if o is not tgt and not self._is_out(o)]
            self._area_vfx(tgt, tiles, [[f"4{d}", "fire"]], "cone", aim)
            return self._run_r(self._strike(c, "Tale of the Dragon", ids, mode="save", magical=True, spell=True, parts=[[f"4{d}", "fire"]],
                                            sv={"ab": "dex", "dc": dc, "half": True}))
        amount = max(1, roll(f"2{d}") + cha)                                  # 11: the Angel
        self._heal(tgt, amount)
        gone = next((x for x in ("Blinded", "Deafened", "Paralyzed", "Petrified", "Poisoned") if x in self._conds(tgt)), None)
        if gone:
            self._clear_conditions(tgt, [gone])
        return say(f"{tgt['name']} regains {amount} hit points" + (f" and is no longer {gone.lower()}" if gone else ""))

    def _subc_bi_used(self, c: dict, e: dict, key: str, tgt: Optional[dict], failed: bool) -> bool:
        """A Bardic Inspiration die is spent on a roll: Unfailing Inspiration keeps it when the roll fails, Infectious Inspiration passes one on when it
        succeeds, the Mote of Potential bursts (a foe takes thunder damage; temporary hit points on a save). True: the die is kept."""
        bard = self._find_or_none(e.get("source_id"))
        bc = self._sheet(bard) if bard else None
        if not bc or bard.get("form"):
            return False
        die = (e.get("mods") or {}).get("attack") or (e.get("mods") or {}).get("save") or F.bardic_die(bc)
        if failed and F.sub_at(bc, "Bard", "College of Eloquence", 6):
            self._say(f"{c['name']} keeps the inspiration die: the roll failed (Unfailing Inspiration)")
            return True
        if F.sub_at(bc, "Bard", "College of Creation", 3):
            n = roll(str(die))
            if key == "attack" and tgt is not None and tgt.get("pos"):
                dc = self._spell_dc(bard)
                for o in [tgt] + [x for x in self.b["combatants"] if x is not tgt and x.get("pos") and tgt.get("pos") and self._alive(x) and self._hostile(bard, x)
                                  and self._dist(x, tgt) <= 5]:
                    res = self._saving_throw(o, "con", dc, spell=True, source=bard, label="Mote of Potential")
                    if not res["ok"]:
                        self._say(f"{bard['name']}'s Mote of Potential shatters: " + self._deal(o, [[n, "thunder"]], by=bard, label="Mote of Potential", spell=True))
            elif key == "save":
                tmp = max(1, n + bc.mod("cha"))
                self._give_temp(c, tmp)
                self._say(f"{bard['name']}'s Mote of Potential gives {c['name']} {tmp} temporary hit points")
        if not failed and F.sub_at(bc, "Bard", "College of Eloquence", 14) and self._alive(bard) and bard.get("pos") and self._may_react(bard) \
                and self._cf_left(bard, "Infectious Inspiration", max(1, bc.mod("cha"))) > 0 and c.get("pos") and self._dist(bard, c) <= 60:
            pal = next((o for o in sorted(self.b["combatants"], key=lambda x: self._dist(bard, x)) if o is not bard and o is not c and not self._hostile(bard, o)
                        and self._alive(o) and o.get("pos") and self._dist(bard, o) <= 60 and not o.get("conjured")
                        and not any(x["name"] == "Bardic Inspiration" for x in o.get("effects") or [])), None)
            if pal is not None:
                self._cf_use(bard, "Infectious Inspiration")
                self._spend_reaction(bard, "Infectious Inspiration")
                self._effect_on(pal, "Bardic Inspiration", [], None, None, None, 100, bard["name"], dict(e.get("mods") or {}), None, bard["id"])
                self._say(f"{bard['name']}'s Infectious Inspiration: {pal['name']} is inspired too")
        return False


F.ACTIVE.update(_sub_c_active())
