"""Subclass features, batch D (Paladin, Ranger, Rogue, Sorcerer, Warlock, Wizard, Artificer; the bar's items are added to
features.ACTIVE below; subfeats.py hands over, profile.py asks for the passives, and a few windows call the _subd_ hooks):

    Paladin     Oathbreaker (Supernatural Resistance, Dread Lord), Crown (Champion Challenge, Unyielding Spirit, Exalted Champion,
                Divine Allegiance), Redemption (Protective Spirit, Emissary), Watchers (Aura of the Sentinel, Vigilant Rebuke,
                Mortal Bulwark)
    Ranger      Beast Master (Exceptional Training, Bestial Fury: summon_stats.class_bonuses), Horizon Walker (Ethereal Step, Distant
                Strike), Drakewarden (Draconic Essence, Bond of Fang and Scale, Drake's Breath, Reflexive Resistance), Fey Wanderer
                (Beguiling Twist), Swarmkeeper (Swarming Dispersal), Gloom Stalker (Umbral Sight)
    Rogue       Thief (Fast Hands, Supreme Sneak, Thief's Reflexes), Inquisitive (Steady Eye, Unerring Eye, Eye for Weakness), Scout
                (Sudden Strike), Mastermind (Misdirection), Swashbuckler (Panache, Elegant Maneuver), Arcane Trickster (Magical Ambush,
                Spell Thief), Phantom (Tokens of the Departed, Ghost Walk, Death's Friend), Soulknife (Rend Mind)
    Sorcerer    Draconic (Dragon Ancestor), Wild Magic (Spell Bombardment), Divine Soul (Empowered Healing), Shadow Magic (Hound of Ill
                Omen, Shadow Walk), Aberrant Mind (Revelation in Flesh, Warping Implosion), Clockwork Soul (Bastion of Law, Trance of
                Order, Cavalcade), Lunar Sorcery (Lunar Empowerment, Waxing and Waning, Lunar Phenomenon)
    Warlock     Fiend (Fiendish Resilience), Great Old One (Create Thrall), Celestial (Celestial Resilience, Searing Vengeance),
                Hexblade (Master of Hexes), Undying (Among the Dead, Defy Death), Undead (Grave Touched, Necrotic Husk, Spirit
                Projection), Fathomless (Grasping Tentacles)
    Wizard      Conjuration (Focused Conjuration), Necromancy (Command Undead), Transmutation (Transmuter's Stone, Master Transmuter),
                War Magic (Durable Magic, Power Surge, Deflecting Shroud), Chronurgy (Temporal Awareness, Chronal Shift, Momentary
                Stasis, Convergent Future), Graviturgy (Adjust Density, Gravity Well, Violent Attraction, Event Horizon)
    Artificer   Artillerist (Fortified Position: two cannons, cover: subfeats_b.py), Battle Smith (Improved Defender)
State that has to outlive a hook is kept in the combatant's "subd" dict (power surges, soul trinkets, the lunar phase...).
"""
from typing import List, Optional

from ...rules import spellcasting as SC
from ...rules.data import rules
from ..common import ServiceError
from . import combat_rules as CR
from . import conditions as K
from . import economy as EC
from . import features as F
from . import geometry as G
from .constants import faction_of
from .modifiers import TYPES
from .resolve import roll

SUB_D_FAMILIES = {"allegiance": "Divine Allegiance", "vigilant_rebuke": "Vigilant Rebuke", "twist": "Beguiling Twist", "chronal": "Chronal Shift",
                  "convergent": "Convergent Future", "bastion_ward": "Bastion of Law (ward)", "violent": "Violent Attraction",
                  "dispersal": "Swarming Dispersal", "misdirection": "Misdirection", "spell_thief": "Spell Thief", "reflexive": "Reflexive Resistance"}
SUB_D_FREE = {"bastion_ward"}



def _sub_d_active() -> dict:
    oath = lambda cls, sub, n: (lambda c: F.sub_at(c, cls, sub, n))
    return {
        # ---- Warlock
        "fiendish_resilience": {"name": "Fiendish Resilience", "cost": "free", "resource": None, "target": "self", "needs": oath("Warlock", "The Fiend", 10),
                                "options": lambda c: [{"value": t, "label": t.capitalize()} for t in TYPES],
                                "text": "Choose a damage type: you have resistance to it until you choose another (the exception for magical and silvered "
                                        "weapons is not tracked)."},
        # ---- Paladin
        "champion_challenge": {"name": "Champion Challenge", "cost": "bonus", "resource": "Channel Divinity (Paladin)", "target": "self",
                               "needs": oath("Paladin", "Oath of the Crown", 3),
                               "text": "Creatures of your choice you can see within 30 ft make a Wisdom save or can't willingly move more than 30 ft away from "
                                       "you for a minute (it ends if you are incapacitated)."},
        "exalted_champion": {"name": "Exalted Champion", "cost": "action", "resource": None, "per": "long", "uses": 1, "target": "self",
                             "needs": oath("Paladin", "Oath of the Crown", 20),
                             "text": "For an hour: resistance to nonmagical bludgeoning, piercing and slashing; you and your allies within 30 ft have "
                                     "advantage on Wisdom saves, and your allies on death saves. Once a long rest."},
        "dread_lord": {"name": "Dread Lord", "cost": "action", "resource": None, "per": "long", "uses": 1, "target": "self",
                       "needs": oath("Paladin", "Oathbreaker", 20),
                       "text": "A minute of gloom in 30 ft: a foe frightened by you takes 4d10 psychic damage when it starts its turn there, attacks against "
                               "you and your allies there have disadvantage. Once a long rest."},
        "dread_shadows": {"name": "Dread Lord: shadows attack", "cost": "bonus", "resource": None, "target": "enemy", "range": 30,
                          "needs": oath("Paladin", "Oathbreaker", 20),
                          "text": "While the aura lasts: a melee spell attack on a creature in it, 3d10 + Charisma modifier necrotic damage."},
        "mortal_bulwark": {"name": "Mortal Bulwark", "cost": "bonus", "resource": None, "per": "long", "uses": 1, "target": "self",
                           "needs": oath("Paladin", "Oath of the Watchers", 20),
                           "text": "For a minute: truesight 120 ft, advantage on attacks against aberrations, celestials, elementals, fey and fiends, and a "
                                   "hit may banish one (Charisma save). Once a long rest."},
        "mortal_bulwark_slot": {"name": "Mortal Bulwark (5th-level slot)", "cost": "bonus", "resource": None, "target": "self",
                                "needs": oath("Paladin", "Oath of the Watchers", 20),
                                "text": "Use Mortal Bulwark again by expending a spell slot of 5th level or higher."},
        # ---- Wizard
        "momentary_stasis": {"name": "Momentary Stasis", "cost": "action", "resource": None, "per": "long", "target": "enemy", "range": 60,
                             "uses": lambda c: max(1, c.mod("int")), "needs": oath("Wizard", "Chronurgy Magic", 6),
                             "text": "A Large or smaller creature within 60 ft makes a Constitution save or is encased until the end of your next turn "
                                     "(incapacitated, speed 0; it ends if the creature takes damage). Intelligence modifier uses a long rest."},
        "adjust_density": {"name": "Adjust Density", "cost": "action", "resource": None, "target": "enemy", "range": 30,
                           "options": lambda c: [{"value": "light", "label": "Halve the weight (+10 ft speed, disadvantage on Strength)"},
                                                 {"value": "heavy", "label": "Double the weight (-10 ft speed, advantage on Strength)"}],
                           "needs": oath("Wizard", "Graviturgy Magic", 2),
                           "text": "Concentration, a minute: a creature's weight is halved or doubled."},
        "event_horizon": {"name": "Event Horizon", "cost": "action", "resource": None, "per": "long", "uses": 1, "target": "self",
                          "needs": oath("Wizard", "Graviturgy Magic", 14),
                          "text": "Concentration, a minute: a foe that starts its turn within 30 ft makes a Strength save or takes 2d10 force and has speed 0 "
                                  "(half and half the movement on a success). Once a long rest."},
        "event_horizon_slot": {"name": "Event Horizon (spell slot)", "cost": "action", "resource": None, "target": "self",
                               "needs": oath("Wizard", "Graviturgy Magic", 14),
                               "text": "Use Event Horizon again by expending a spell slot of 3rd level or higher."},
        # ---- Sorcerer
        "revelation_flesh": {"name": "Revelation in Flesh", "cost": "bonus", "resource": None, "target": "self",
                             "options": lambda c: [{"value": "fly", "label": "Flying speed equal to your walking speed"},
                                                   {"value": "see", "label": "See invisible creatures within 60 ft"},
                                                   {"value": "swim", "label": "Swimming speed, breathe underwater"},
                                                   {"value": "slime", "label": "Slimy body: escape grapples and restraints"}],
                             "needs": oath("Sorcerer", "Aberrant Mind", 14),
                             "text": "Spend 1 or more sorcery points: for 10 minutes one benefit per point (pick one now; use again for more)."},
        "warping_implosion": {"name": "Warping Implosion", "cost": "action", "resource": None, "per": "long", "uses": 1, "target": "point", "range": 120,
                              "needs": oath("Sorcerer", "Aberrant Mind", 18),
                              "text": "Teleport up to 120 ft; creatures within 30 ft of where you were make a Strength save or take 3d10 force and are pulled "
                                      "to that space (half and not pulled on a success). Once a long rest."},
        "warping_implosion_sp": {"name": "Warping Implosion (5 sorcery points)", "cost": "action", "resource": None, "target": "point", "range": 120,
                                 "needs": oath("Sorcerer", "Aberrant Mind", 18),
                                 "text": "Use Warping Implosion again by spending 5 sorcery points."},
        "bastion_of_law": {"name": "Bastion of Law", "cost": "action", "resource": None, "target": "ally", "range": 30,
                           "options": lambda c: [{"value": str(n), "label": f"{n} sorcery point{'s' if n > 1 else ''}: {n}d8 ward"} for n in range(1, 6)],
                           "needs": oath("Sorcerer", "Clockwork Soul", 6),
                           "text": "Spend 1 to 5 sorcery points: a ward of that many d8s on you or a creature within 30 ft. When it takes damage it may "
                                   "spend dice to reduce the damage."},
        "trance_of_order": {"name": "Trance of Order", "cost": "bonus", "resource": None, "per": "long", "uses": 1, "target": "self",
                            "needs": oath("Sorcerer", "Clockwork Soul", 14),
                            "text": "For a minute attacks against you can't have advantage and a 9 or lower on your d20 counts as 10. Once a long rest."},
        "trance_of_order_sp": {"name": "Trance of Order (5 sorcery points)", "cost": "bonus", "resource": None, "target": "self",
                               "needs": oath("Sorcerer", "Clockwork Soul", 14),
                               "text": "Use Trance of Order again by spending 5 sorcery points."},
        "clockwork_cavalcade": {"name": "Clockwork Cavalcade", "cost": "action", "resource": None, "per": "long", "uses": 1, "target": "self",
                                "needs": oath("Sorcerer", "Clockwork Soul", 18),
                                "text": "Spirits restore up to 100 hit points among creatures you choose within 30 ft and end spells of 6th level or lower on "
                                        "them (the most hurt first). Once a long rest."},
        "clockwork_cavalcade_sp": {"name": "Clockwork Cavalcade (7 sorcery points)", "cost": "action", "resource": None, "target": "self",
                                   "needs": oath("Sorcerer", "Clockwork Soul", 18),
                                   "text": "Use Clockwork Cavalcade again by spending 7 sorcery points."},
        "shadow_walk": {"name": "Shadow Walk", "cost": "bonus", "resource": None, "target": "point", "range": 120, "needs": oath("Sorcerer", "Shadow Magic", 14),
                        "text": "From dim light or darkness, teleport up to 120 ft to an unoccupied space you can see that is also in dim light or darkness."},
        "hound_of_ill_omen": {"name": "Hound of Ill Omen", "cost": "bonus", "resource": None, "target": "enemy", "range": 120, "needs": oath("Sorcerer", "Shadow Magic", 6),
                              "text": "Spend 3 sorcery points: a hound (dire wolf statistics, Medium) appears near a creature you can see within 120 ft, with half "
                                      "your sorcerer level in temporary hit points; while it is within 5 ft of its target, the target has disadvantage on saves "
                                      "against your spells. It goes when it or its target drops."},
        "ghost_walk": {"name": "Ghost Walk", "cost": "bonus", "resource": None, "per": "long", "uses": 1, "target": "self", "needs": oath("Rogue", "Phantom", 13),
                       "text": "A spectral form for 10 minutes: flying speed 10 ft, hover, attacks against you have disadvantage. Once a long rest."},
        "ghost_walk_trinket": {"name": "Ghost Walk (soul trinket)", "cost": "bonus", "resource": None, "target": "self", "needs": oath("Rogue", "Phantom", 13),
                               "text": "Use Ghost Walk again by destroying one of your soul trinkets."},
        "ethereal_step": {"name": "Ethereal Step", "cost": "bonus", "resource": None, "per": "short", "uses": 1, "target": "self",
                          "needs": oath("Ranger", "Horizon Walker", 7),
                          "text": "Step into the Ethereal Plane until the end of your turn (etherealness): foes can't target you. Once a short or long rest."},
        "distant_strike_extra": {"name": "Distant Strike: third creature", "cost": "free", "resource": None, "target": "enemy", "needs": oath("Ranger", "Horizon Walker", 11),
                                 "when": "attacked", "text": "After attacking two different creatures with the Attack action, one additional attack against a third creature."},
        "distant_strike": {"name": "Distant Strike: teleport", "cost": "free", "resource": None, "target": "point", "range": 10, "needs": oath("Ranger", "Horizon Walker", 11),
                           "when": "attacked", "text": "Before each attack of the Attack action, teleport up to 10 ft to an unoccupied space you can see."},
        "sudden_strike": {"name": "Sudden Strike", "cost": "bonus", "resource": None, "target": "enemy", "needs": oath("Rogue", "Scout", 17), "when": "attacked",
                          "text": "After the Attack action: one more weapon attack as a bonus action; it can Sneak Attack even if you did already this turn, "
                                  "but not the same target twice."},
        "drakes_breath": {"name": "Drake's Breath", "cost": "action", "resource": None, "per": "long", "uses": 1, "target": "area",
                          "area": {"shape": "cone", "size": 30, "origin": "caster"}, "needs": oath("Ranger", "Drakewarden", 11),
                          "options": lambda c: [{"value": t, "label": t.capitalize()} for t in ("acid", "cold", "fire", "lightning", "poison")],
                          "text": "A 30-ft cone of breath (Dexterity save against your spell save DC): 8d6, 10d6 at 15th level. Once a long rest."},
        "drakes_breath_slot": {"name": "Drake's Breath (spell slot)", "cost": "action", "resource": None, "target": "area",
                               "area": {"shape": "cone", "size": 30, "origin": "caster"}, "needs": oath("Ranger", "Drakewarden", 11),
                               "options": lambda c: [{"value": t, "label": t.capitalize()} for t in ("acid", "cold", "fire", "lightning", "poison")],
                               "text": "Use Drake's Breath again by expending a spell slot of 3rd level or higher."},
        "command_undead": {"name": "Command Undead", "cost": "action", "resource": None, "target": "enemy", "range": 60, "needs": oath("Wizard", "School of Necromancy", 14),
                           "text": "An undead you can see within 60 ft makes a Charisma save (advantage with Intelligence 8 or more) or becomes friendly and "
                                   "obeys you until you use this again. If it succeeds you can't use this on it again."},
        "create_thrall": {"name": "Create Thrall", "cost": "action", "resource": None, "target": "enemy", "range": 5, "needs": oath("Warlock", "The Great Old One", 14),
                          "text": "Touch an incapacitated humanoid: it is charmed by you until a remove curse spell, or until you use this again."},
        "transmuters_stone": {"name": "Transmuter's Stone", "cost": "free", "resource": None, "target": "ally", "range": 5, "needs": oath("Wizard", "School of Transmutation", 6),
                              "options": lambda c: [{"value": "darkvision", "label": "Darkvision 60 ft"}, {"value": "speed", "label": "+10 ft speed"},
                                                    {"value": "con", "label": "Constitution save proficiency"}]
                              + [{"value": t, "label": f"Resistance to {t}"} for t in ("acid", "cold", "fire", "lightning", "thunder")],
                              "text": "Give the stone to yourself or a creature within 5 ft with a benefit of your choice (it can be changed when you cast a "
                                      "transmutation spell). Only one stone works at a time."},
        "master_transmuter": {"name": "Master Transmuter", "cost": "action", "resource": None, "per": "long", "uses": 1, "target": "ally", "range": 5,
                              "needs": oath("Wizard", "School of Transmutation", 14),
                              "options": lambda c: [{"value": "panacea", "label": "Panacea: all hit points back, poisons and curses gone"},
                                                    {"value": "raise", "label": "Restore Life: raise dead on a creature you touch"}],
                              "text": "Consume the transmuter's stone in one burst. Once a long rest."},
        "gravity_well": {"name": "Gravity Well", "cost": "free", "resource": None, "target": "enemy", "range": 60, "needs": oath("Wizard", "Graviturgy Magic", 6),
                         "when": "spell", "text": "After you cast a spell on a creature: move it 5 ft to a free space (it must be willing, or hit by the spell, or fail the save)."},
        "waxing_waning": {"name": "Waxing and Waning", "cost": "bonus", "resource": None, "target": "self", "needs": oath("Sorcerer", "Lunar Sorcery", 6),
                          "options": lambda c: [{"value": p, "label": p} for p in ("Full Moon", "New Moon", "Crescent Moon")],
                          "text": "Spend 1 sorcery point: change your lunar phase."},
        "lunar_phenomenon": {"name": "Lunar Phenomenon", "cost": "bonus", "resource": None, "target": "point", "range": 60, "needs": oath("Sorcerer", "Lunar Sorcery", 18),
                             "text": "Use the power of your current phase: Full Moon (blind foes, heal), New Moon (gloom, necrotic, invisible), Crescent Moon "
                                     "(teleport 60 ft, resist all). Once a long rest per phase, or 5 sorcery points."},
        "grasping_tentacles": {"name": "Grasping Tentacles", "cost": "action", "resource": None, "per": "long", "uses": 1, "target": "point", "range": 90,
                               "needs": oath("Warlock", "The Fathomless", 10),
                               "text": "Cast Evard's black tentacles once without a spell slot: you gain your warlock level in temporary hit points, and "
                                       "damage can't break your concentration on it. Once a long rest."},
        "spirit_projection": {"name": "Spirit Projection", "cost": "action", "resource": None, "per": "long", "uses": 1, "target": "self",
                              "needs": oath("Warlock", "The Undead", 14),
                              "text": "Project your spirit for an hour (concentration): resistance to bludgeoning, piercing and slashing, a flying speed, and "
                                      "under Form of Dread you regain half the necrotic damage you deal. (Your body is not left behind on the map.)"},
        "elegant_maneuver": {"name": "Elegant Maneuver", "cost": "bonus", "resource": None, "target": "self", "needs": oath("Rogue", "Swashbuckler", 13),
                             "text": "Advantage on the next Acrobatics or Athletics check you make this turn."},
        "unerring_eye": {"name": "Unerring Eye", "cost": "action", "resource": None, "per": "long", "target": "self", "uses": lambda c: max(1, c.mod("wis")),
                         "needs": oath("Rogue", "Inquisitive", 13),
                         "text": "Sense illusions, shapechangers not in their true form and other deceptions within 30 ft (not blinded or deafened)."},
        "panache": {"name": "Panache", "cost": "action", "resource": None, "target": "enemy", "range": 60, "needs": oath("Rogue", "Swashbuckler", 9),
                    "text": "A Charisma (Persuasion) check against its Wisdom (Insight): a hostile creature has disadvantage on attacks against anyone but you "
                            "for a minute; one that isn't hostile is charmed."},
    }


class SubFeatsDMixin:
    # ------------------------------------------------------------------ small helpers
    @staticmethod
    def _subd_slot(char, low: int = 1) -> Optional[int]:
        """The lowest spell slot level of at least `low` that is left (None: none)."""
        left = SC.slots_remaining(char)
        levels = sorted(int(k) for k, v in left.items() if k != SC.PACT_KEY and v > 0 and int(k) >= low)
        return levels[0] if levels else None

    def _subd_spend_slot(self, char, low: int) -> int:
        fresh = self._char(char.name) or char                  # (sheets are loaded afresh: save what another step just wrote, not an old copy)
        lvl = self._subd_slot(fresh, low)
        used = fresh.d["slots_used"]
        used[str(lvl)] = int(used.get(str(lvl)) or 0) + 1
        fresh.save()
        return lvl

    def _subd_state(self, c: dict) -> dict:
        return c.setdefault("subd", {})

    def _subd_start_conc(self, c: dict, name: str, classes) -> None:
        if c.get("concentrating"):
            self._drop_conc(c, name)
        c["concentrating"] = {"spell": name, "rounds": 10, "src": self._magic_source(c, {"classes": list(classes)})}

    def _subd_fx_named(self, c: dict, name: str) -> Optional[dict]:
        return next((e for e in c.get("effects") or [] if e["name"] == name), None)

    def _subd_families(self, char) -> List[str]:
        out = []
        if F.sub_at(char, "Paladin", "Oath of the Crown", 7):
            out.append("allegiance")
        if F.sub_at(char, "Paladin", "Oath of the Watchers", 15):
            out.append("vigilant_rebuke")
        if F.sub_at(char, "Ranger", "Fey Wanderer", 7):
            out.append("twist")
        if F.sub_at(char, "Wizard", "Chronurgy Magic", 2):
            out.append("chronal")
        if F.sub_at(char, "Wizard", "Chronurgy Magic", 14):
            out.append("convergent")
        if F.sub_at(char, "Sorcerer", "Clockwork Soul", 6):
            out.append("bastion_ward")
        if F.sub_at(char, "Wizard", "Graviturgy Magic", 10):
            out.append("violent")
        if F.sub_at(char, "Ranger", "Swarmkeeper", 15):
            out.append("dispersal")
        if F.sub_at(char, "Rogue", "Mastermind", 13):
            out.append("misdirection")
        if F.sub_at(char, "Rogue", "Arcane Trickster", 17):
            out.append("spell_thief")
        if F.sub_at(char, "Ranger", "Drakewarden", 15):
            out.append("reflexive")
        return out

    # ------------------------------------------------------------------ passives
    def _subd_passives(self, c: dict, char) -> list:
        """Always-on features as effect-like entries (profile._all_effects)."""
        out = []

        def add(name, **mods):
            out.append({"name": name, "mods": mods, "conditions": [], "feature": True})

        if F.sub_at(char, "Ranger", "Gloom Stalker", 3):          # Umbral Sight: darkvision 60 ft, or 30 ft more with it already
            add("Umbral Sight", senses={"darkvision": (char.darkvision + 30) if char.darkvision else 60})
        if F.sub_at(char, "Paladin", "Oathbreaker", 15):
            add("Supernatural Resistance", resist=["nonmagical"])
        if F.sub_at(char, "Paladin", "Oath of the Crown", 15):
            add("Unyielding Spirit", cond_save_adv=["Paralyzed", "Stunned"])
        if F.sub_at(char, "Ranger", "Fey Wanderer", 7):
            add("Beguiling Twist", cond_save_adv=["Charmed", "Frightened"])
        if F.sub_at(char, "Warlock", "The Undead", 10):
            if any(e["name"] == "Form of Dread" for e in c.get("effects") or []):
                add("Necrotic Husk", immune=["necrotic"])
            else:
                add("Necrotic Husk", resist=["necrotic"])
        if c.get("concentrating") and F.sub_at(char, "Wizard", "War Magic", 10):
            add("Durable Magic", ac=2, save="2")
        if int((c.get("subd") or {}).get("trinkets") or 0) > 0 and F.sub_at(char, "Rogue", "Phantom", 9):
            add("Soul trinket", dsave_adv=True, save_adv=["con"])
        t = c.get("turn")
        if t and c.get("pos") and (F.sub_at(char, "Rogue", "Thief", 9) or F.sub_at(char, "Rogue", "Inquisitive", 9)):
            if int(t.get("speed") or 0) and int(t.get("move") or 0) >= int(t["speed"]) // 2:          # no more than half the speed moved this turn
                if F.sub_at(char, "Rogue", "Thief", 9):
                    add("Supreme Sneak", skill_adv=["Stealth"])
                if F.sub_at(char, "Rogue", "Inquisitive", 9):
                    add("Steady Eye", skill_adv=["Perception", "Investigation"])
        return out

    # ------------------------------------------------------------------ the bar
    def _subd_why(self, c: dict, char, key: str, f: dict, tgt: Optional[dict], option, menu: bool, point) -> Optional[str]:
        """Why one of these features can't be used now (None: it can, or it isn't one of these)."""
        st = self._subd_state(c)
        if key == "fiendish_resilience" and not menu and option not in TYPES:
            return "Pick a damage type."
        if key == "exalted_champion" and self._subd_fx_named(c, "Exalted Champion"):
            return "Already active"
        if key == "dread_lord" and self._subd_fx_named(c, "Dread Lord"):
            return "Already active"
        if key == "dread_shadows":
            if not self._subd_fx_named(c, "Dread Lord"):
                return "Only while the Dread Lord aura lasts"
            if not menu and (tgt is None or tgt is c or not self._hostile(c, tgt) or not self._within(c, tgt, 30)):
                return "Pick a foe in the aura."
        if key in ("mortal_bulwark", "mortal_bulwark_slot"):
            if self._subd_fx_named(c, "Mortal Bulwark"):
                return "Already active"
            if key == "mortal_bulwark_slot":
                if self._cf_left(c, "Mortal Bulwark", 1) > 0:
                    return "Use it free of charge first"
                if not self._subd_slot(char, 5):
                    return "No spell slot of 5th level or higher left"
        if key == "momentary_stasis" and not menu:
            if tgt is None or tgt is c or not self._hostile(c, tgt):
                return "Pick a foe first."
            from .standard import SIZES
            if SIZES.index(self._size_of(tgt)) > SIZES.index("Large"):
                return f"{tgt['name']} is too big (Large or smaller)"
        if key == "adjust_density" and not menu:
            if tgt is None:
                return "Pick a creature first."
            if option not in ("light", "heavy"):
                return "Pick halved or doubled weight."
            if c.get("pos") and tgt.get("pos") and self._dist(c, tgt) > 30:
                return "Too far (30 ft)"
        if key in ("event_horizon", "event_horizon_slot"):
            if self._subd_fx_named(c, "Event Horizon"):
                return "Already active"
            if key == "event_horizon_slot":
                if self._cf_left(c, "Event Horizon", 1) > 0:
                    return "Use it free of charge first"
                if not self._subd_slot(char, 3):
                    return "No spell slot of 3rd level or higher left"
        if key == "revelation_flesh":
            if self._resource_left(c, "Sorcery Points") < 1:
                return "No sorcery points left"
            if not menu and option not in ("fly", "see", "swim", "slime"):
                return "Pick a benefit."
        if key in ("warping_implosion", "warping_implosion_sp"):
            if key == "warping_implosion_sp":
                if self._cf_left(c, "Warping Implosion", 1) > 0:
                    return "Use it free of charge first"
                if self._resource_left(c, "Sorcery Points") < 5:
                    return "Needs 5 sorcery points"
            if not menu:
                return self._cf_landing(c, point, 120)
        if key == "bastion_of_law":
            if not menu and option not in ["1", "2", "3", "4", "5"]:
                return "Pick how many sorcery points."
            if self._resource_left(c, "Sorcery Points") < (int(option) if str(option or "").isdigit() else 1):
                return "Not enough sorcery points"
            if not menu and tgt is not None and (self._hostile(c, tgt) or (c.get("pos") and tgt.get("pos") and self._dist(c, tgt) > 30)):
                return "Pick yourself or an ally within 30 ft."
        if key in ("trance_of_order", "trance_of_order_sp"):
            if self._subd_fx_named(c, "Trance of Order"):
                return "Already active"
            if key == "trance_of_order_sp":
                if self._cf_left(c, "Trance of Order", 1) > 0:
                    return "Use it free of charge first"
                if self._resource_left(c, "Sorcery Points") < 5:
                    return "Needs 5 sorcery points"
        if key in ("clockwork_cavalcade", "clockwork_cavalcade_sp"):
            if key == "clockwork_cavalcade_sp":
                if self._cf_left(c, "Clockwork Cavalcade", 1) > 0:
                    return "Use it free of charge first"
                if self._resource_left(c, "Sorcery Points") < 7:
                    return "Needs 7 sorcery points"
        if key == "shadow_walk" and not menu:
            return self._cf_landing(c, point, 120, True)
        if key == "shadow_walk" and menu and c.get("pos") and not self._cf_dark(G.footprint(c["pos"], c.get("span") or 1)):
            return "Stand in dim light or darkness first"
        if key == "hound_of_ill_omen":
            if self._resource_left(c, "Sorcery Points") < 3:
                return "Needs 3 sorcery points"
            if not menu and (tgt is None or tgt is c or not self._hostile(c, tgt) or (c.get("pos") and tgt.get("pos") and self._dist(c, tgt) > 120) or not self._sees(c, tgt)):
                return "Pick a foe you can see within 120 ft."
        if key in ("ghost_walk", "ghost_walk_trinket"):
            if self._subd_fx_named(c, "Ghost Walk"):
                return "Already active"
            if key == "ghost_walk_trinket":
                if self._cf_left(c, "Ghost Walk", 1) > 0:
                    return "Use it free of charge first"
                if int(st.get("trinkets") or 0) < 1:
                    return "No soul trinket on you"
        if key == "ethereal_step" and self._subd_fx_named(c, "Ethereal Step"):
            return "Already active"
        if key == "distant_strike" and not menu:
            return self._cf_landing(c, point, 10)
        if key == "distant_strike_extra":
            seen = (st.get("ds") or {}).get(f"{self.b.get('round')}:{self.b.get('turn')}") or []
            if not self._cf_turn_free(c, "ds_extra"):
                return "Once a turn"
            if len(seen) < 2:
                return "Attack two different creatures first"
            if not menu and (tgt is None or tgt is c or not self._hostile(c, tgt) or tgt["id"] in seen):
                return "Pick a third creature."
        if key == "sudden_strike" and not menu:
            if tgt is None or tgt is c or not self._hostile(c, tgt):
                return "Pick a foe first."
            try:
                self._cf_weapon(c, char, tgt)
            except ServiceError as e:
                return str(e)
        if key == "panache" and not menu and (tgt is None or tgt is c):
            return "Pick a creature first."
        if key in ("drakes_breath", "drakes_breath_slot"):
            if key == "drakes_breath_slot":
                if self._cf_left(c, "Drake's Breath", 1) > 0:
                    return "Use it free of charge first"
                if not self._subd_slot(char, 3):
                    return "No spell slot of 3rd level or higher left"
            if not menu and option not in ("acid", "cold", "fire", "lightning", "poison"):
                return "Pick the damage type."
        if key == "command_undead":
            if not menu:
                if tgt is None or tgt is c or not self._hostile(c, tgt):
                    return "Pick an undead foe."
                if not str((self._monster(tgt) or {}).get("type") or "").lower().startswith("undead"):
                    return f"{tgt['name']} isn't undead"
                if c["id"] in (tgt.get("subd") or {}).get("cu_immune", []):
                    return "It already resisted you"
                if c.get("pos") and tgt.get("pos") and (self._dist(c, tgt) > 60 or not self._sees(c, tgt)):
                    return "Too far or out of sight (60 ft)"
        if key == "create_thrall" and not menu:
            if tgt is None or tgt is c or not K.incapacitated(self._conds(tgt)):
                return "Pick an incapacitated humanoid."
            if not str((self._monster(tgt) or {}).get("type") or "humanoid").lower().startswith("humanoid") and not self._sheet(tgt):
                return f"{tgt['name']} isn't a humanoid"
            if c.get("pos") and tgt.get("pos") and self._dist(c, tgt) > 5:
                return "Too far (touch)"
        if key == "transmuters_stone" and not menu:
            if option not in ("darkvision", "speed", "con") and option not in ("acid", "cold", "fire", "lightning", "thunder"):
                return "Pick a benefit."
            if tgt is not None and tgt is not c and (self._hostile(c, tgt) or (c.get("pos") and tgt.get("pos") and self._dist(c, tgt) > 5)):
                return "Pick yourself or an ally within 5 ft."
        if key == "master_transmuter" and not menu:
            if option not in ("panacea", "raise"):
                return "Pick an effect."
            if tgt is not None and tgt is not c and c.get("pos") and tgt.get("pos") and self._dist(c, tgt) > 5:
                return "Too far (touch)"
            if option == "raise" and (tgt is None or not self._dead(tgt)):
                return "Pick a dead creature."
        if key == "gravity_well" and not menu:
            if tgt is None or tgt is c or not tgt.get("pos"):
                return "Pick the creature to move."
            if not point:
                return "Pick the free tile (5 ft from it) to move it to."
            if G.distance_ft(tgt["pos"], tgt.get("span") or 1, [int(point[0]), int(point[1])], tgt.get("span") or 1) > 5:
                return "Only 5 ft"
            if not self._tile_ok(tgt, int(point[0]), int(point[1])):
                return "That tile is taken or off the map."
        if key == "waxing_waning":
            if self._resource_left(c, "Sorcery Points") < 1:
                return "No sorcery points left"
            if not menu and option not in ("Full Moon", "New Moon", "Crescent Moon"):
                return "Pick a phase."
        if key == "lunar_phenomenon":
            phase = self._subd_phase(c, char)
            if self._cf_left(c, f"Lunar Phenomenon ({phase})", 1) <= 0 and self._resource_left(c, "Sorcery Points") < 5:
                return "Used already (5 sorcery points to use it again)"
            if phase == "Crescent Moon" and not menu:
                return self._cf_landing(c, point, 60)
        return None

    def _subd_feature(self, c: dict, char, key: str, f: dict, tgt: Optional[dict], option, point) -> Optional[str]:
        """Plays one of these features (None: not one of these, or it only noted something)."""
        name = c["name"]
        if key == "fiendish_resilience":
            for e in [e for e in c.get("effects") or [] if e["name"] == "Fiendish Resilience"]:
                self._effect_off(c, e, "a new choice")
            self._effect_on(c, "Fiendish Resilience", [], None, None, None, None, name, {"resist": [option]}, None, c["id"])
            return self._out(f"{name} turns aside {option} damage (Fiendish Resilience)")
        if key == "champion_challenge":
            ids = [o["id"] for o in self._cf_hostiles(c, 30) if self._sees(c, o)]
            return self._run_r(self._strike(c, "Champion Challenge", ids, mode="save", magical=True, parts=[],
                                            sv={"ab": "wis", "dc": self._spell_dc(c), "half": False, "rounds": 10, "effect_name": "Champion Challenge",
                                                "mods": {"leash": c["id"], "leash_ft": 30}, "note": "can't willingly leave the champion"}))
        if key == "exalted_champion":
            self._effect_on(c, "Exalted Champion", [], None, None, None, 600, name, {"resist": ["nonmagical"]}, None, c["id"])
            self._effect_on(c, "Exalted Champion (aura)", [], None, None, None, 600, name, {"save_adv": ["wis"], "dsave_adv": True, "aura_ft": 30}, None, c["id"])
            return self._out(f"{name} stands as an Exalted Champion: resistance to nonmagical weapons, allies within 30 ft steadied")
        if key == "dread_lord":
            self._effect_on(c, "Dread Lord", [], None, None, None, 10, name, {"dread_lord": 30}, None, c["id"])
            self._effect_on(c, "Dread Lord (shadow)", [], None, None, None, 10, name, {"attacks_against": "dis", "aura_ft": 30}, None, c["id"])
            return self._out(f"{name} wraps the field in gloom: frightened foes within 30 ft take 4d10 psychic damage each turn")
        if key == "dread_shadows":
            mod = char.mod("cha")                                # a melee spell attack, the shadows reach 30 ft
            atk = {"bonus": char.proficiency_bonus + mod, "n": 1, "melee": True, "spell": True, "reach": 30, "normal": None, "long": None,
                   "parts": [[f"3d10{mod:+d}" if mod else "3d10", "necrotic"]]}
            return self._run_r(self._strike(c, "Dread Lord (shadows)", [tgt["id"]], mode="attack", atk=atk, magical=True, spell=True))
        if key in ("mortal_bulwark", "mortal_bulwark_slot"):
            if key == "mortal_bulwark_slot":
                self._subd_spend_slot(char, 5)
            self._effect_on(c, "Mortal Bulwark", [], None, None, None, 10, name, {"senses": {"truesight": 120}, "bulwark": True}, None, c["id"])
            return self._out(f"{name} manifests a spark of divine power: truesight 120 ft, advantage against extraplanar creatures (Mortal Bulwark)")
        if key == "momentary_stasis":
            dc = self._spell_dc(c)
            until = {"end": c["id"], "skip": 1 if self.b.get("turn") == c["id"] else 0}
            return self._run_r(self._strike(c, "Momentary Stasis", [tgt["id"]], mode="save", magical=True, parts=[],
                                            sv={"ab": "con", "dc": dc, "half": False, "conds": ["Incapacitated"], "until": until,
                                                "mods": {"speed_set": 0, "ends_on": ["damage"]}, "effect_name": "Momentary Stasis", "note": "frozen in time"}))
        if key == "adjust_density":
            light = option == "light"
            self._subd_start_conc(c, "Adjust Density", ["Wizard"])
            for o in self.b["combatants"]:
                for e in [e for e in o.get("effects") or [] if e["name"] == "Adjust Density" and e.get("source_id") == c["id"]]:
                    self._effect_off(o, e, "a new weight")
            mods = {"speed": 10, "save_dis": ["str"], "check_dis": ["str"]} if light else {"speed": -10, "save_adv": ["str"], "check_adv": ["str"]}
            self._effect_on(tgt, "Adjust Density", [], None, None, None, 10, name, mods, c["id"], c["id"])
            return self._out(f"{name} makes {tgt['name']} {'light' if light else 'heavy'} (Adjust Density: {'+10' if light else '-10'} ft speed)")
        if key in ("event_horizon", "event_horizon_slot"):
            if key == "event_horizon_slot":
                self._subd_spend_slot(char, 3)
            self._subd_start_conc(c, "Event Horizon", ["Wizard"])
            self._effect_on(c, "Event Horizon", [], None, None, None, 10, name, {"event_horizon": self._spell_dc(c)}, c["id"], c["id"])
            return self._out(f"{name} emits a field of gravity: foes starting their turn within 30 ft save or are crushed")
        if key == "revelation_flesh":
            self._use_resource(c, "Sorcery Points", 1)
            mods = {"fly": {"fly": char.speed}, "see": {"senses": {"see_invisible": True}}, "swim": {"swim": 2 * char.speed},
                    "slime": {"slimy": True}}[option]
            self._effect_on(c, f"Revelation in Flesh ({option})", [], None, None, None, 100, name, mods, None, c["id"])
            what = {"fly": f"a flying speed of {char.speed} ft", "see": "sight of invisible creatures within 60 ft",
                    "swim": "a swimming speed and gills", "slime": "a slimy, pliable body"}[option]
            return self._out(f"{name}'s body warps: {what} (Revelation in Flesh)")
        if key in ("warping_implosion", "warping_implosion_sp"):
            if key == "warping_implosion_sp":
                self._use_resource(c, "Sorcery Points", 5)
            return self._warping_implosion(c, char, point)
        if key == "bastion_of_law":
            n = int(option)
            self._use_resource(c, "Sorcery Points", n)
            who = tgt or c
            for o in self.b["combatants"]:
                for e in [e for e in o.get("effects") or [] if e["name"] == "Bastion of Law" and e.get("source_id") == c["id"]]:
                    self._effect_off(o, e, "a new ward")
            self._effect_on(who, "Bastion of Law", [], None, None, None, None, name, {"bastion": n}, None, c["id"])
            return self._out(f"{name} wards {who['name'] if who is not c else 'themselves'} with {n}d8 of order (Bastion of Law)")
        if key in ("trance_of_order", "trance_of_order_sp"):
            if key == "trance_of_order_sp":
                self._use_resource(c, "Sorcery Points", 5)
            self._effect_on(c, "Trance of Order", [], None, None, None, 10, name, {"no_adv_against": True, "trance": True}, None, c["id"])
            return self._out(f"{name} aligns with Mechanus: no advantage against them, d20 rolls of 9 or lower count as 10")
        if key in ("clockwork_cavalcade", "clockwork_cavalcade_sp"):
            if key == "clockwork_cavalcade_sp":
                self._use_resource(c, "Sorcery Points", 7)
            return self._cavalcade(c)
        if key == "shadow_walk":
            self._cf_teleport(c, point)
            return self._out(f"{name} steps from shadow to shadow, to {self._tile_label(c['pos'])} (Shadow Walk)")
        if key == "hound_of_ill_omen":
            return self._hound(c, char, tgt)
        if key in ("ghost_walk", "ghost_walk_trinket"):
            if key == "ghost_walk_trinket":
                self._subd_state(c)["trinkets"] = max(0, int(self._subd_state(c).get("trinkets") or 0) - 1)
            self._effect_on(c, "Ghost Walk", [], None, None, None, 100, name, {"fly": 10, "attacks_against": "dis"}, None, c["id"])
            return self._out(f"{name} slips partly into the realm of the dead: flying 10 ft, attacks against them have disadvantage (Ghost Walk)")
        if key == "ethereal_step":
            self._effect_on(c, "Ethereal Step", [], None, None, None, None, name, {"untargetable": True}, None, c["id"], until={"end": c["id"], "skip": 0})
            return self._out(f"{name} steps into the Ethereal Plane until the end of the turn (Ethereal Step)")
        if key == "distant_strike":
            self._cf_teleport(c, point)
            return self._out(f"{name} blinks across planes to {self._tile_label(c['pos'])} (Distant Strike)")
        if key == "distant_strike_extra":
            self._once_per_turn(c, "ds_extra")
            return self._cf_weapon_strike(c, char, tgt, "Distant Strike")
        if key == "sudden_strike":
            w, atk = None, None
            for cand in sorted((x for x in char.attacks() if "unarmed" not in (x.get("props") or [])),     # a finesse or ranged weapon: it can Sneak Attack
                               key=lambda x: (not ("finesse" in (x.get("props") or []) or x.get("ranged")), -x["attack"])):
                try:
                    w, atk = cand, self._feat_attack(c, cand, self._check_reach(c, tgt, self._weapon_atk(c, cand)))
                    break
                except ServiceError:
                    continue
            if w is None:
                w, atk = self._cf_weapon(c, char, tgt)
            R = self._strike(c, f"{w['name']} (Sudden Strike)", [tgt["id"]], mode="attack", atk=atk, magical=atk.get("magical", False))
            R["sudden"] = True
            return self._run_r(R)
        if key in ("drakes_breath", "drakes_breath_slot"):
            if key == "drakes_breath_slot":
                self._subd_spend_slot(char, 3)
            if not c.get("pos"):
                raise ServiceError("Not on the map.")
            parts = [[f"{10 if char.class_level('Ranger') >= 15 else 8}d6", option]]
            aim = point or self.b.get("aim") or (list(G.centre(tgt["pos"], tgt.get("span") or 1)) if tgt and tgt.get("pos") else None)
            tiles = G.area_for(f["area"], c["pos"], c.get("span") or 1, tuple(aim) if aim else None, *self._bounds())
            ids = [o["id"] for o in G.creatures_in(tiles, self.b["combatants"]) if o is not c and not self._is_out(o)]
            self._area_vfx(c, tiles, parts, "cone", aim)
            return self._run_r(self._strike(c, "Drake's Breath", ids, mode="save", magical=True, parts=parts, summary_targets=None,
                                            sv={"ab": "dex", "dc": self._spell_dc(c), "half": True}))
        if key == "panache":
            mine, theirs = self._check(c, "Persuasion"), self._check(tgt, "Insight")
            self._say(f"{name} Persuasion {mine} vs {tgt['name']}'s Insight {theirs} (Panache)")
            if mine <= theirs:
                return self._out(f"{tgt['name']} isn't swayed by {name}'s charm")
            if self._hostile(c, tgt):
                self._effect_on(tgt, "Panache", [], None, None, None, 10, name, {"duel": True}, None, c["id"])
                return self._out(f"{tgt['name']} can't take its eyes off {name}: disadvantage on attacks against anyone else (Panache)")
            self._effect_on(tgt, "Charmed (Panache)", ["Charmed"], None, None, None, 10, name, {"charmed_by": c["id"]}, None, c["id"])
            return self._out(f"{tgt['name']} is charmed by {name}'s panache")
        if key == "spirit_projection":
            self._subd_start_conc(c, "Spirit Projection", ["Warlock"])
            self._effect_on(c, "Spirit Projection", [], None, None, None, 600, name, {"resist": ["bludgeoning", "piercing", "slashing"], "fly": char.speed,
                                                                                    "spirit": True}, c["id"], c["id"])
            return self._out(f"{name} slips out of their body: resistance to physical damage, flying {char.speed} ft (Spirit Projection)")
        if key == "elegant_maneuver":
            self._effect_on(c, "Elegant Maneuver", [], None, None, None, None, name, {"skill_adv": ["Acrobatics", "Athletics"]}, None, c["id"],
                            until={"end": c["id"], "skip": 0})
            return self._out(f"{name} gathers their poise: advantage on Acrobatics and Athletics this turn (Elegant Maneuver)")
        if key == "unerring_eye":
            if {"Blinded", "Deafened"} & set(self._conds(c)):
                return self._out(f"{name} can't sense deceptions while blinded or deafened")
            found = [o["name"] for o in self.b["combatants"] if o is not c and o.get("pos") and self._within(c, o, 30)
                     and ("Invisible" in self._conds(o) or o.get("shape") or self._fx(o, "hidden") or o.get("form"))]
            return self._out(f"{name} senses deceit nearby (Unerring Eye): " + (", ".join(found) if found else "nothing amiss"))
        if key == "command_undead":
            for o in self.b["combatants"]:
                if (o.get("subd") or {}).get("commanded_by") == c["id"]:
                    o["faction"] = o["subd"].pop("was_faction", 2)
                    o["subd"].pop("commanded_by", None)
                    self._say(f"{o['name']} slips free of {name}'s command")
            m = self._monster(tgt) or {}
            dc = self._spell_dc(c)
            smart = int((m.get("abilities") or {}).get("int") or 10)
            res = self._saving_throw(tgt, "cha", dc, spell=True, source=c, label="Command Undead", adv="adv" if smart >= 8 else False)
            if res["ok"]:
                self._subd_state(tgt).setdefault("cu_immune", []).append(c["id"])
                return self._out(f"{tgt['name']} CHA {res['total']} vs DC {dc}: resists {name}'s command (Command Undead)")
            self._subd_state(tgt).update(commanded_by=c["id"], was_faction=faction_of(tgt))
            tgt["faction"] = self._side(c)
            return self._out(f"{tgt['name']} CHA {res['total']} vs DC {dc}: bends to {name}'s will, friendly and obedient (Command Undead)")
        if key == "create_thrall":
            for o in self.b["combatants"]:
                for e in [e for e in o.get("effects") or [] if e["name"] == "Create Thrall" and e.get("source_id") == c["id"]]:
                    self._effect_off(o, e, "a new thrall")
            self._effect_on(tgt, "Create Thrall", ["Charmed"], None, None, None, None, name, {"thrall_of": c["id"]}, None, c["id"])
            return self._out(f"{name} touches {tgt['name']}'s mind with alien magic: charmed, a thrall (Create Thrall)")
        if key == "transmuters_stone":
            who = tgt or c
            for o in self.b["combatants"]:
                for e in [e for e in o.get("effects") or [] if e["name"] == "Transmuter's Stone" and e.get("source_id") == c["id"]]:
                    self._effect_off(o, e, "a new stone")
            mods = {"darkvision": {"senses": {"darkvision": 60}}, "speed": {"speed": 10}, "con": {"save_prof": ["con"]}}.get(option) or {"resist": [option]}
            self._effect_on(who, "Transmuter's Stone", [], None, None, None, None, name, mods, None, c["id"])
            return self._out(f"{name} charges a transmuter's stone for {who['name'] if who is not c else 'themselves'}: {option}")
        if key == "master_transmuter":
            who = tgt or c
            if option == "raise":
                sp = rules.spell("Raise Dead")
                ab = char.mod("int")
                return self._cast_on(c, sp, who, slot_level=5, caster_level=char.total_level, mod=ab, attack_bonus=char.proficiency_bonus + ab,
                                     dc=self._spell_dc(c), adv=None, paid=True)
            self._heal(who, max(1, self._max_hp(who) - self._hp_of(who)))
            self._clear_conditions(who, ["Poisoned"])
            for e in [e for e in who.get("effects") or [] if "curse" in e["name"].lower() or e["name"].startswith("Hex")]:
                self._effect_off(who, e, "Panacea")
            return self._out(f"{c['name']} bursts the transmuter's stone over {who['name']} (Master Transmuter: Panacea): hit points whole, poison and curses gone")
        if key == "gravity_well":
            before = list(tgt["pos"])
            self._vfx("blink", id=tgt["id"], at=before, to=[int(point[0]), int(point[1])])
            tgt["pos"] = [int(point[0]), int(point[1])]
            self._follow_zones(tgt)
            return self._out(f"{name} tugs {tgt['name']} with gravity to {self._tile_label(tgt['pos'])} (Gravity Well)")
        if key == "waxing_waning":
            self._use_resource(c, "Sorcery Points", 1)
            self._subd_state(c)["phase"] = option
            self._subd_phase_effects(c, char)
            return self._out(f"{name}'s magic turns to the {option} (Waxing and Waning)")
        if key == "lunar_phenomenon":
            return self._lunar_phenomenon(c, char, point)
        if key == "grasping_tentacles":
            sp = rules.spell("Evard's Black Tentacles")
            if not sp:
                raise ServiceError("No Evard's black tentacles in the spell list.")
            ab = char.mod("cha")
            EC.refund(c.get("turn"), "action")                  # the spell pays its own casting time
            self._give_temp(c, char.class_level("Warlock"))
            out = self._cast_on(c, sp, None, slot_level=4, caster_level=char.total_level, mod=ab, attack_bonus=char.proficiency_bonus + ab,
                                dc=self._spell_dc(c), adv=None, targets=[], point=point, paid=True)
            self._subd_state(c)["tentacles"] = True
            return out
        return None

    # ---- Lunar Sorcery
    def _subd_phase(self, c: dict, char) -> str:
        from ...rules import combat_feats as CF
        return self._subd_state(c).get("phase") or CF.is_on(char, "lunar_phase") or "Full Moon"

    def _subd_phase_effects(self, c: dict, char):
        """Lunar Empowerment: the Crescent Moon's resistance to necrotic and radiant damage (the other phases need light, which isn't tracked)."""
        for e in [e for e in c.get("effects") or [] if e["name"] == "Lunar Empowerment"]:
            self._effect_off(c, e, "a new phase")
        if F.sub_at(char, "Sorcerer", "Lunar Sorcery", 14) and self._subd_phase(c, char) == "Crescent Moon":
            self._effect_on(c, "Lunar Empowerment", [], None, None, None, None, c["name"], {"resist": ["necrotic", "radiant"]}, None, c["id"])

    def _lunar_phenomenon(self, c: dict, char, point) -> str:
        phase = self._subd_phase(c, char)
        name = c["name"]
        key = f"Lunar Phenomenon ({phase})"
        if self._cf_left(c, key, 1) > 0:
            self._cf_use(c, key)
        else:
            self._use_resource(c, "Sorcery Points", 5)
        dc = self._spell_dc(c)
        near = self._cf_hostiles(c, 30)
        if phase == "Full Moon":
            allies = [o for o in self.b["combatants"] if not self._hostile(c, o) and o.get("pos") and self._alive(o) and self._within(c, o, 30) and not o.get("conjured")]
            hurt = min(allies, key=lambda o: self._hp_of(o) / max(1, self._max_hp(o)), default=None)
            bits = []
            if hurt:
                n = roll("3d8")
                self._heal(hurt, n)
                bits.append(f"{hurt['name']} regains {n} HP")
            until = {"end": c["id"], "skip": 1}
            R = self._strike(c, "Lunar Phenomenon (Full Moon)", [o["id"] for o in near], mode="save", magical=True, parts=[],
                             sv={"ab": "con", "dc": dc, "half": False, "conds": ["Blinded"], "until": until})
            line = self._run_r(R) if near else ""
            return self._out(f"{name} radiates moonlight" + (": " + ", ".join(bits) if bits else "") + (f". {line}" if line else ""))
        if phase == "New Moon":
            R = self._strike(c, "Lunar Phenomenon (New Moon)", [o["id"] for o in near], mode="save", magical=True, parts=[["3d10", "necrotic"]],
                             sv={"ab": "dex", "dc": dc, "half": False, "mods": {"speed_set": 0}, "effect_name": "Gloom",
                                 "until": {"end": c["id"], "skip": 1}, "note": "speed 0"})
            self._effect_on(c, "Lunar Gloom", ["Invisible"], None, None, None, None, name, {"ends_on": ["attack", "cast"]}, None, c["id"],
                            until={"end": c["id"], "skip": 1})
            line = self._run_r(R) if near else ""
            return self._out(f"{name} emanates gloom and fades from sight" + (f". {line}" if line else ""))
        self._cf_teleport(c, point)
        for e in [e for e in c.get("effects") or [] if e["name"] == "Lunar Phenomenon (Crescent Moon)"]:
            self._effect_off(c, e, "again")
        self._effect_on(c, "Lunar Phenomenon (Crescent Moon)", [], None, None, None, None, name, {"resist": list(TYPES)}, None, c["id"], until={"start": c["id"]})
        return self._out(f"{name} slips through the crescent to {self._tile_label(c['pos'])}: resistance to all damage until their next turn")

    # ---- Shadow Magic
    def _hound(self, c: dict, char, tgt: dict) -> str:
        from ...rules.monsters import bestiary
        self._use_resource(c, "Sorcery Points", 3)
        mid = next((m["id"] for m in bestiary.all if m["name"] == "Dire Wolf" and m.get("source") == "MM"), None) or next((m["id"] for m in bestiary.all if m["name"] == "Dire Wolf"), None)
        if mid is None:
            raise ServiceError("No dire wolf stat block in the bestiary.")
        for old in [o for o in self.b["combatants"] if o.get("summon_spell") == "Hound of Ill Omen" and o.get("summoned_by") == c["id"]]:
            self._vfx_unsummon(old)
            self.remove(old["id"])
        made = self._add_summons(c, mid, 1, "Hound of Ill Omen", 1, None, None, None, None, "Hound of Ill Omen")
        for h in made:
            h["span"] = 1
            h["hound_of"] = tgt["id"]
            self._give_temp(h, max(1, char.class_level("Sorcerer") // 2))
            if tgt.get("pos"):
                spot = self._free_near(h, *tgt["pos"])
                if spot:
                    h["pos"] = spot
            self._effect_on(tgt, "Hound of Ill Omen", [], None, None, None, 50, c["name"], {"hound": h["id"]}, None, c["id"])
        return self._out(f"{c['name']} calls a hound of ill omen to harry {tgt['name']} (3 sorcery points; it can only chase and bite its target)")

    def _subd_leash(self, c: dict, x: int, y: int) -> Optional[str]:
        """Champion Challenge: a creature under it can't willingly end a move more than 30 ft from the paladin (nor farther than it is now)."""
        for e in c.get("effects") or []:
            lid = (e.get("mods") or {}).get("leash")
            src = self._find_or_none(lid) if lid is not None else None
            if src is None or not src.get("pos") or not c.get("pos") or K.incapacitated(self._conds(src)) or not self._alive(src):
                continue
            ft = int(e["mods"].get("leash_ft") or 30)
            span = c.get("span") or 1
            new = G.distance_ft([x, y], span, src["pos"], src.get("span") or 1)
            if new > ft and new > self._dist(c, src):
                return f"{c['name']} can't willingly move more than {ft} ft from {src['name']} (Champion Challenge)"
        return None

    # ---- companions
    def _subd_summon_ctx(self, char, cls: str) -> dict:
        """What a companion's stat block takes from its owner's subclass (summon_stats.class_bonuses)."""
        extra = {}
        if cls == "Ranger":
            if F.sub_at(char, "Ranger", "Beast Master", 7):
                extra["magic"] = True                            # Exceptional Training: its attacks count as magical
            if F.sub_at(char, "Ranger", "Beast Master", 11):
                extra["fury"] = True                             # Bestial Fury: two attacks
            if F.sub_at(char, "Ranger", "Drakewarden", 3):
                from ...rules import combat_feats as CF
                extra["essence"] = CF.is_on(char, "drake_essence") or "fire"
                extra["bond"] = 2 if F.sub_at(char, "Ranger", "Drakewarden", 15) else 1 if F.sub_at(char, "Ranger", "Drakewarden", 7) else 0
        if cls == "Artificer" and F.sub_at(char, "Artificer", "Battle Smith", 15):
            extra["bonus_ac"] = 2                                # Improved Defender
        return extra

    def _subd_companion(self, owner: dict, pet: dict, ctx: dict):
        """A drake grown Large takes up four tiles; the drakewarden shares its resistance (Bond of Fang and Scale)."""
        if ctx.get("bond", 0) >= 2:
            pet["span"] = 2
        if ctx.get("bond", 0) >= 1 and ctx.get("essence"):
            for e in [e for e in owner.get("effects") or [] if e["name"] == "Drake Bond"]:
                self._effect_off(owner, e, "a new drake")
            self._effect_on(owner, "Drake Bond", [], None, None, None, None, owner["name"], {"resist": [ctx["essence"]]}, None, owner["id"])

    def _subd_use_cost(self, c: dict) -> str:
        """Fast Hands: a Thief takes the Use an Object action as a bonus action (when it is still free)."""
        char = self._sheet(c)
        if char and not c.get("form") and F.sub_at(char, "Rogue", "Thief", 3) and (not self._economy_on() or not EC.why_not(c.get("turn"), "bonus")):
            return "bonus"
        return "action"

    # ---- Aberrant Mind
    def _warping_implosion(self, c: dict, char, point) -> str:
        origin = list(c["pos"])
        span = c.get("span") or 1
        near = [o for o in self.b["combatants"] if o is not c and o.get("pos") and not self._is_out(o) and not o.get("conjured")
                and G.distance_ft(origin, span, o["pos"], o.get("span") or 1) <= 30]
        self._cf_teleport(c, point)
        dc = self._spell_dc(c)
        total = roll("3d10")
        lines = []
        ghost = {"pos": origin, "span": span, "id": -1, "name": "the warp"}
        for o in near:
            res = self._saving_throw(o, "str", dc, spell=True, source=c, label="Warping Implosion")
            amount = total if not res["ok"] else total // 2
            lines.append(self._deal(o, [[amount, "force"]], by=c, label="Warping Implosion", magical=True, spell=True)
                         + ("" if res["ok"] else " and is pulled in"))
            if not res["ok"] and self._alive(o):
                self._push(o, ghost, -30)
        return self._out(f"{c['name']} folds space and reappears at {self._tile_label(c['pos'])} (Warping Implosion, DC {dc}): "
                         + ("; ".join(lines) if lines else "nobody near the old space"))

    # ---- Clockwork Soul
    def _cavalcade(self, c: dict) -> str:
        near = [o for o in self.b["combatants"] if (o is c or (not self._hostile(c, o) and not o.get("conjured")))
                and o.get("pos") and self._within(c, o, 30) and not self._dead(o)]
        near.sort(key=lambda o: self._hp_of(o) / max(1, self._max_hp(o)))      # the most hurt first
        pool, bits = 100, []
        for o in near:
            need = max(0, self._max_hp(o) - self._hp_of(o))
            if need and pool:
                n = min(need, pool)
                self._heal(o, n, revive=self._hp_of(o) <= 0)
                pool -= n
                bits.append(f"{o['name']} +{n}")
            ended = 0
            for e in [e for e in o.get("effects") or [] if e.get("conc_by") is not None and self._hostile(self._find_or_none(e.get("source_id")) or o, o)]:
                self._effect_off(o, e, "the Clockwork Cavalcade")
                ended += 1
            if ended:
                bits.append(f"{ended} hostile spell(s) end on {o['name']}")
        return self._out(f"{c['name']}'s spirits of order mend the field: " + (", ".join(bits) or "nobody needed it"))

    # ------------------------------------------------------------------ initiative, battle start, turns
    def _subd_initiative(self, c: dict) -> int:
        """Bonuses to an initiative roll: Temporal Awareness (+ Intelligence), Aura of the Sentinel (+ proficiency, allies near the paladin)."""
        total = 0
        char = self._sheet(c)
        if char and not c.get("form") and F.sub_at(char, "Wizard", "Chronurgy Magic", 2):
            total += char.mod("int")
        for o in self.b["combatants"]:
            oc = self._sheet(o)
            if not oc or o.get("form") or not F.sub_at(oc, "Paladin", "Oath of the Watchers", 7) or self._hostile(o, c) or not self._can_act(o):
                continue
            reach = 30 if oc.class_level("Paladin") >= 18 else 10
            if o is c or (o.get("pos") and c.get("pos") and self._within(o, c, reach)):
                total += oc.proficiency_bonus
                self._say(f"{c['name']} is alert (Aura of the Sentinel: +{oc.proficiency_bonus} initiative)")
                break
        return total

    def _subd_battle_start(self):
        """Celestial Resilience: a celestial warlock begins the fight with temporary hit points (and five allies with half). Also the
        start of the fight for the power surges, the lunar phase's resistance and Thief's Reflexes (not when a battle ends)."""
        if self.b.get("status") != "active":
            return
        self.b.pop("reflex_back", None)
        for c in self.b["combatants"]:
            char = self._sheet(c)
            if char and not c.get("form") and F.sub_at(char, "Wizard", "War Magic", 6):
                self._subd_state(c)["surges"] = 1                # a long rest resets the power surges to one
            if char and not c.get("form") and F.sub_at(char, "Sorcerer", "Lunar Sorcery", 14):
                self._subd_phase_effects(c, char)
            if char and not c.get("form") and F.sub_at(char, "Rogue", "Thief", 17):
                self._subd_state(c)["reflex"] = True              # Thief's Reflexes: the second turn of the first round is still to come
            if not char or c.get("form") or not F.sub_at(char, "Warlock", "The Celestial", 10):
                continue
            lv, cha = char.class_level("Warlock"), char.mod("cha")
            self._give_temp(c, max(1, lv + cha))
            allies = [o for o in self.b["combatants"] if o is not c and not self._hostile(c, o) and o.get("pos") and self._alive(o) and not o.get("conjured")]
            allies = sorted(allies, key=lambda o: self._dist(c, o) if c.get("pos") else 0)[:5]
            for o in allies:
                self._give_temp(o, max(1, lv // 2 + cha))
            self._say(f"{c['name']} is bolstered by the Celestial Resilience: {max(1, lv + cha)} temporary HP"
                      + (f" ({max(1, lv // 2 + cha)} each for " + ", ".join(o["name"] for o in allies) + ")" if allies else ""))

    def _subd_turn_start(self, c: dict):
        """Event Horizon and the Dread Lord's gloom hurt what starts its turn near them."""
        if not c.get("pos") or not self._alive(c):
            return
        for o in self.b["combatants"]:
            if o is c or not o.get("pos") or not self._can_act(o):
                continue
            hz = self._subd_fx_named(o, "Event Horizon")
            if hz and self._hostile(o, c) and self._within(o, c, 30):
                dc = int(hz["mods"]["event_horizon"])
                res = self._saving_throw(c, "str", dc, spell=True, source=o, label="Event Horizon")
                half = res["ok"]
                dmg = roll("2d10")
                line = self._deal(c, [[dmg // 2 if half else dmg, "force"]], by=o, label="Event Horizon", magical=True, spell=True)
                t = c.get("turn")
                if t is not None:
                    t["move"] = int(t.get("move", 0)) // 2 if half else 0
                self._say(f"{o['name']}'s Event Horizon drags at {c['name']}: STR {res['total']} vs DC {dc} — "
                          + ("half damage and slowed" if half else "crushed, speed 0") + f" ({line})")
            dl = self._subd_fx_named(o, "Dread Lord")
            if dl and self._hostile(o, c) and self._within(o, c, 30) and any(
                    "Frightened" in (e.get("conditions") or []) and e.get("source_id") == o["id"] for e in c.get("effects") or []):
                self._say(f"{o['name']}'s Dread Lord gloom: " + self._deal(c, [[roll("4d10"), "psychic"]], by=o, label="Dread Lord", magical=True))

    def _subd_turn_end(self, c: dict):
        """Protective Spirit: a Redemption paladin that ends its turn under half its hit points heals."""
        char = self._sheet(c)
        if not char or c.get("form") or not self._alive(c) or not F.sub_at(char, "Paladin", "Oath of Redemption", 15):
            return
        if 0 < self._hp_of(c) * 2 < self._max_hp(c) + 0 and not K.incapacitated(self._conds(c)):
            n = roll("1d6") + char.class_level("Paladin") // 2
            self._heal(c, n)
            self._say(f"{c['name']} is mended by a holy presence: +{n} HP (Protective Spirit)")


    # ------------------------------------------------------------------ reactions
    def _subd_near(self, o: dict, x: dict, feet: int, sight: bool = True) -> bool:
        return bool(o.get("pos") and x.get("pos") and self._dist(o, x) <= feet and (not sight or self._sees(o, x)))

    def _subd_eligible(self, out: list, window: str, R: dict, att: Optional[dict], tgt: Optional[dict], ctx: dict):
        cur = R.get("cur") or {}
        a = R.get("atk") or {}
        combat = self.b["combatants"]
        if window == "declared" and att is not None and tgt is not None and self._hostile(att, tgt):
            ac_ = self._sheet(att)
            if ac_ and not att.get("form") and F.sub_at(ac_, "Ranger", "Horizon Walker", 11) and self.b.get("turn") == att["id"]:
                key = f"{self.b.get('round')}:{self.b.get('turn')}"
                ds = self._subd_state(att).setdefault("ds", {})
                for k in [k for k in ds if k != key]:
                    ds.pop(k)
                if tgt["id"] not in ds.setdefault(key, []):
                    ds[key].append(tgt["id"])                    # Distant Strike: the creatures attacked this turn
        if window == "damage" and tgt:
            total = sum(n for n, _t in cur.get("dmg") or [])
            if total <= 0:
                return
            for o in combat:
                oc = self._sheet(o)
                if not oc or o.get("form") or not self._alive(o):
                    continue
                if o is not tgt and F.sub_at(oc, "Paladin", "Oath of the Crown", 7) and self._may_react(o) and not self._hostile(o, tgt) \
                        and self._subd_near(o, tgt, 5, False):
                    self._cf_offer(out, o, "reaction", [{"key": "allegiance", "label": f"Divine Allegiance: take {tgt['name']}'s {total} damage instead", "detail": ""}],
                                   f"{tgt['name']} is about to take {total} damage. {o['name']}: take it instead?")
                if att is not None and o is not att and o is not tgt and R.get("mode") == "attack" and a.get("weapon") and F.sub_at(oc, "Wizard", "Graviturgy Magic", 10) \
                        and self._may_react(o) and not self._hostile(o, att) and self._hostile(o, tgt) and self._subd_near(o, att, 60) \
                        and self._cf_left(o, "Violent Attraction", max(1, oc.mod("int"))) > 0:
                    self._cf_offer(out, o, "reaction", [{"key": "violent", "label": f"Violent Attraction: +1d10 to {att['name']}'s hit", "detail": ""}],
                                   f"{att['name']} hits {tgt['name']}. {o['name']}: add velocity?")
            for o in combat:                                     # Reflexive Resistance: the drakewarden or its drake, within 30 ft of each other
                oc = self._sheet(o)
                if not oc or o.get("form") or not F.sub_at(oc, "Ranger", "Drakewarden", 15) or not self._may_react(o) or not self._alive(o):
                    continue
                mine = tgt is o or (tgt.get("summoned_by") == o["id"] and "Drake Companion" in str(tgt.get("monster") or ""))
                other = tgt if tgt is not o else next((x for x in combat if x.get("summoned_by") == o["id"] and "Drake Companion" in str(x.get("monster") or "")), None)
                if mine and (tgt is o or self._subd_near(o, tgt, 30, False)) and self._cf_left(o, "Reflexive Resistance", oc.proficiency_bonus) > 0 \
                        and (other is None or tgt is o or self._subd_near(o, other, 30, False)):
                    self._cf_offer(out, o, "reaction", [{"key": "reflexive", "label": f"Reflexive Resistance: resist {tgt['name']}'s {total} damage", "detail": ""}],
                                   f"{tgt['name']} is about to take {total} damage. React?")
            tc = self._sheet(tgt)
            ward = next((e for e in tgt.get("effects") or [] if (e.get("mods") or {}).get("bastion")), None)
            if ward is not None:
                self._cf_offer(out, tgt, "free", [{"key": "bastion_ward", "label": f"Bastion of Law: spend {ward['mods']['bastion']}d8 ward dice", "detail": ""}],
                               f"{tgt['name']} is about to take {total} damage. Use the ward?")
            if tc and not tgt.get("form") and F.sub_at(tc, "Ranger", "Swarmkeeper", 15) and self._may_react(tgt) and self._alive(tgt) \
                    and self._cf_left(tgt, "Swarming Dispersal", tc.proficiency_bonus) > 0:
                self._cf_offer(out, tgt, "reaction", [{"key": "dispersal", "label": "Swarming Dispersal (resist the damage, teleport 30 ft)", "detail": ""}],
                               f"{tgt['name']} is about to take {total} damage. React?")
        elif window in ("save_ok", "save_failed", "hit", "missed", "before_save") and tgt is not None:
            self._subd_luck(out, window, R, att, tgt)
            sv = R.get("sv") or {}
            if window == "save_ok" and att is not None:
                for o in combat:
                    oc = self._sheet(o)
                    if not oc or o.get("form") or not self._alive(o) or not self._may_react(o):
                        continue
                    if F.sub_at(oc, "Paladin", "Oath of the Watchers", 15) and sv.get("ab") in ("int", "wis", "cha") and att is not o and self._hostile(o, att) \
                            and (o is tgt or (not self._hostile(o, tgt) and self._subd_near(o, tgt, 30))) and att.get("pos"):
                        self._cf_offer(out, o, "reaction", [{"key": "vigilant_rebuke", "label": f"Vigilant Rebuke: 2d8 + Cha force on {att['name']}", "detail": ""}],
                                       f"{tgt['name']} resisted {R.get('label')}. {o['name']}: chastise {att['name']}?")
                    conds = set(sv.get("conds") or [])
                    if F.sub_at(oc, "Ranger", "Fey Wanderer", 7) and conds & {"Charmed", "Frightened"} and (o is tgt or self._subd_near(o, tgt, 120)) \
                            and (o is tgt or self._sees(o, tgt)) and self._subd_twist_victim(o, tgt) is not None:
                        self._cf_offer(out, o, "reaction", [{"key": f"twist:{k}", "label": f"Beguiling Twist: {k.lower()} a foe (Wisdom save)", "detail": ""}
                                                           for k in ("Charmed", "Frightened") if k in conds],
                                       f"{tgt['name']} shrugged off {R.get('label')}. {o['name']}: twist the magic against someone else?")
        elif window == "cast" and att is not None:
            for o in combat:
                oc = self._sheet(o)
                if oc and o is not att and not o.get("form") and F.sub_at(oc, "Rogue", "Arcane Trickster", 17) and self._hostile(o, att) and self._alive(o) \
                        and self._may_react(o) and o["id"] in (R.get("targets") or []) and self._cf_left(o, "Spell Thief", 1) > 0:
                    self._cf_offer(out, o, "reaction", [{"key": "spell_thief", "label": f"Spell Thief: negate {R.get('label')} against you and steal it", "detail": ""}],
                                   f"{att['name']} casts {R.get('label')} at {o['name']}. Spell Thief?")
        elif window == "declared" and att and tgt and self._hostile(att, tgt):
            tc = self._sheet(tgt)
            if tc and not tgt.get("form") and F.sub_at(tc, "Rogue", "Mastermind", 13) and self._may_react(tgt) and self._subd_cover_giver(att, tgt) is not None:
                self._cf_offer(out, tgt, "reaction", [{"key": "misdirection", "label": f"Misdirection: the attack hits {self._subd_cover_giver(att, tgt)['name']} instead", "detail": ""}],
                               f"{att['name']} attacks {tgt['name']} past a neighbour. Misdirection?")

    def _subd_luck(self, out: list, window: str, R: dict, att: Optional[dict], tgt: dict):
        """Chronal Shift (a roll made again) and Convergent Future (the roll set to the edge), for a Chronurgy wizard."""
        cur = R.get("cur") or {}
        if window == "before_save":
            return
        for o in self.b["combatants"]:
            oc = self._sheet(o)
            if not oc or o.get("form") or not self._alive(o) or not o.get("pos") or not F.sub_at(oc, "Wizard", "Chronurgy Magic", 2):
                continue
            # who rolled, and would the wizard like the result changed?
            if window in ("hit", "missed"):
                roller = att
                if roller is None or (window == "hit") != self._hostile(o, roller):
                    continue
                if window == "hit" and self._hostile(o, tgt):
                    continue
                if window == "missed" and (self._hostile(o, roller) or not self._hostile(o, tgt)):
                    continue
            else:
                roller = tgt
                if window == "save_ok" and not self._hostile(o, roller):
                    continue
                if window == "save_failed" and self._hostile(o, roller):
                    continue
            if not self._may_react(o):
                continue
            opts = []
            if self._cf_left(o, "Chronal Shift", 2) > 0 and self._subd_near(o, roller, 30):
                opts.append({"key": "chronal", "label": f"Chronal Shift: {roller['name']} rolls again", "detail": ""})
            if F.sub_at(oc, "Wizard", "Chronurgy Magic", 14) and self._subd_near(o, roller, 60):
                opts.append({"key": "convergent", "label": "Convergent Future: decide the roll (1 level of exhaustion)", "detail": ""})
            if opts:
                self._cf_offer(out, o, "reaction", opts, f"{roller['name']} rolled {cur.get('total')} ({R.get('label')}). {o['name']}: warp time?")

    def _subd_twist_victim(self, o: dict, saver: dict) -> Optional[dict]:
        """The foe Beguiling Twist would work on: the nearest one (not the creature that saved) within 120 ft."""
        foes = [x for x in self.b["combatants"] if x is not saver and x is not o and self._hostile(o, x) and self._alive(x) and self._subd_near(o, x, 120)]
        return min(foes, key=lambda x: self._dist(o, x), default=None)

    def _subd_cover_giver(self, att: dict, tgt: dict) -> Optional[dict]:
        """A creature within 5 ft of the target that stands in the way of the attack (nearer to the attacker, not behind the target)."""
        if not att.get("pos") or not tgt.get("pos"):
            return None
        best = None
        for o in self.b["combatants"]:
            if o is att or o is tgt or not o.get("pos") or not self._alive(o) or self._is_out(o) or o.get("conjured") or self._dist(o, tgt) > 5:
                continue
            if self._dist(att, o) >= self._dist(att, tgt):
                continue
            if best is None or self._dist(att, o) < self._dist(att, best):
                best = o
        return best

    def _subd_react(self, window: str, R: dict, reactor: dict, fam: str, arg: str, ctx: dict) -> bool:
        """What these features' reactions do (False: not one of them)."""
        if fam not in SUB_D_FAMILIES:
            if fam == "deflection":                              # Deflecting Shroud rides on Arcane Deflection (the usual handler goes on)
                self._subd_shroud(reactor)
            return False
        cur = R.setdefault("cur", {})
        char = self._sheet(reactor)
        name = reactor["name"]
        att = self._find_or_none(ctx.get("attacker") or R.get("actor"))
        tgt = self._find_or_none(ctx.get("target"))
        if fam == "allegiance" and tgt is not None:
            amounts = [list(p) for p in cur.get("dmg") or []]
            cur["dmg"] = []
            self._line(R, f"{name} takes {tgt['name']}'s hurt on their own flesh (Divine Allegiance): "
                          + self._deal_rolled(reactor, amounts, by=att, label="Divine Allegiance", ignore_resist=list(TYPES) + ["immune"]), "Divine Allegiance")
            return True
        if fam == "reflexive":
            self._cf_use(reactor, "Reflexive Resistance")
            cur["dmg"] = [[n // 2, t] for n, t in cur.get("dmg") or []]
            self._line(R, f"{name} turns the blow aside with the drake's bond: resistance to that damage (Reflexive Resistance)", "Reflexive Resistance")
            return True
        if fam == "violent":
            self._cf_use(reactor, "Violent Attraction")
            dtype = ((R.get("atk") or {}).get("parts") or [["", ""]])[0][1] or ""
            n = roll("1d10")
            cur.setdefault("dmg", []).append([n, dtype])
            self._line(R, f"{name} gives the blow velocity: +{n} {dtype} (Violent Attraction)", "Violent Attraction")
            return True
        if fam == "bastion_ward":
            ward = next((e for e in reactor.get("effects") or [] if (e.get("mods") or {}).get("bastion")), None)
            if ward is None:
                return True
            total = sum(n for n, _t in cur.get("dmg") or [])
            dice = int(ward["mods"]["bastion"])
            used, cut = 0, 0
            while used < dice and cut < total:
                cut += roll("1d8")
                used += 1
            left = [list(p) for p in cur.get("dmg") or []]
            rest = cut
            for p in left:
                take = min(p[0], rest)
                p[0] -= take
                rest -= take
            cur["dmg"] = left
            if used >= dice:
                self._effect_off(reactor, ward, "spent")
            else:
                ward["mods"]["bastion"] = dice - used
            self._line(R, f"{name}'s ward of order absorbs {min(cut, total)} damage ({used}d8; {dice - used} left)", "Bastion of Law")
            return True
        if fam == "dispersal":
            self._cf_use(reactor, "Swarming Dispersal")
            cur["dmg"] = [[n // 2, t] for n, t in cur.get("dmg") or []]
            foes = [o for o in self.b["combatants"] if self._hostile(reactor, o) and o.get("pos") and self._alive(o)]
            span = reactor.get("span") or 1
            best, score = None, -1
            r0 = reactor["pos"]
            for dx in range(-6, 7):
                for dy in range(-6, 7):
                    x, y = r0[0] + dx, r0[1] + dy
                    if (dx or dy) and self._tile_ok(reactor, x, y) and G.distance_ft(r0, span, [x, y], span) <= 30:
                        s = min([G.distance_ft([x, y], span, o["pos"], o.get("span") or 1) for o in foes] or [0])
                        if s > score:
                            best, score = [x, y], s
            if best:
                self._cf_teleport(reactor, best)
            self._line(R, f"{name} scatters into the swarm: resistance to the damage" + (f", reappearing at {self._tile_label(best)}" if best else ""), "Swarming Dispersal")
            return True
        if fam == "spell_thief" and att is not None:
            self._cf_use(reactor, "Spell Thief")
            dc = self._spell_dc(reactor)
            if self._sheet(att):
                ab = (rules.spell(R.get("label") or "") or {}).get("ability") or "int"
            else:                                                # a monster casts with its best of Intelligence, Wisdom and Charisma
                scores = (self._monster(att) or {}).get("abilities") or {}
                ab = max(("int", "wis", "cha"), key=lambda a: int(scores.get(a) or 10))
            res = self._saving_throw(att, ab, dc, spell=True, source=reactor, label="Spell Thief")
            self._line(R, f"{name} reaches for {att['name']}'s magic (Spell Thief): {ab.upper()} {res['total']} vs DC {dc} — " + ("fails to take it" if res["ok"] else "the spell goes wrong"),
                       "Spell Thief")
            if not res["ok"]:
                R["targets"] = [t for t in R.get("targets") or [] if t != reactor["id"]]
                sp = rules.spell(R.get("label") or "")
                if sp and int(sp.get("level") or 0) >= 1:
                    self._subd_state(reactor)["stolen"] = sp["name"]
                    self._line(R, f"{name} commits {sp['name']} to memory for 8 hours (it can't be cast by {att['name']} meanwhile)", "Spell Thief")
            return True
        if fam == "misdirection" and att is not None:
            who = self._subd_cover_giver(att, reactor)
            if who is not None and R.get("ti", 0) < len(R.get("targets") or []):
                R["targets"][R["ti"]] = who["id"]
                self._line(R, f"{name} ducks behind {who['name']}: the attack is made against them (Misdirection)", "Misdirection")
            return True
        if fam == "vigilant_rebuke" and att is not None:
            n = roll("2d8") + max(0, char.mod("cha"))
            self._line(R, f"{name}'s Vigilant Rebuke: " + self._deal(att, [[n, "force"]], by=reactor, label="Vigilant Rebuke", magical=True), "Vigilant Rebuke")
            return True
        if fam == "twist" and tgt is not None:
            victim = self._subd_twist_victim(reactor, tgt)
            if victim is None:
                return True
            dc = self._spell_dc(reactor)
            res = self._saving_throw(victim, "wis", dc, spell=True, source=reactor, conds=[arg], label="Beguiling Twist")
            ok = res["ok"]
            self._line(R, f"{name}'s Beguiling Twist: {victim['name']} WIS {res['total']} vs DC {dc} — " + ("holds" if ok else arg.lower()), "Beguiling Twist")
            if not ok:
                self._effect_on(victim, f"{arg} (Beguiling Twist)", [arg], "wis", dc, "end", 10, name, {}, None, reactor["id"])
            return True
        if fam in ("chronal", "convergent"):
            if fam == "chronal":
                self._cf_use(reactor, "Chronal Shift")
            else:
                self._exhaust(reactor, 1)
            again = self.rng.randint(1, 20)
            if window in ("save_ok", "save_failed"):
                dc = int((R.get("sv") or {}).get("dc") or 10)
                if fam == "chronal":
                    total = cur["total"] - cur["kept"] + again
                    cur.update(total=total, kept=again, ok=total >= dc)
                    self._line(R, f"{name} bends time: {self._find_or_none(ctx.get('target'))['name']} rolls again ({again}) → {total}" + (" — success" if cur["ok"] else " — failed"), "Chronal Shift")
                else:
                    want_ok = window == "save_failed"
                    cur.update(total=dc if want_ok else dc - 1, kept=10, ok=want_ok)
                    self._line(R, f"{name} pulls a future into being: the save {'succeeds' if want_ok else 'fails'} (Convergent Future)", "Convergent Future")
            else:
                ac = int(cur.get("ac") or 0) + int(cur.get("ac_extra") or 0)
                if fam == "chronal":
                    cur["total"] = cur["total"] - cur["kept"] + again
                    cur["kept"] = again
                    cur["crit"] = again == 20
                    self._line(R, f"{name} bends time: the attack is rolled again ({again}) → {cur['total']}", "Chronal Shift")
                else:
                    hit = window == "missed"
                    cur.update(total=ac if hit else ac - 1, kept=10, crit=False)
                    self._line(R, f"{name} pulls a future into being: the attack {'hits' if hit else 'misses'} (Convergent Future)", "Convergent Future")
            return True
        return False

    # ------------------------------------------------------------------ attack and damage hooks
    EXTRAPLANAR = ("aberration", "celestial", "elemental", "fey", "fiend")

    def _subd_modes(self, att: dict, tgt: dict, a: dict) -> list:
        """[(mode, why)] added to an attack roll: Mortal Bulwark's advantage against extraplanar creatures."""
        if any(e["name"] == "Mortal Bulwark" for e in att.get("effects") or []):
            kind = str((self._monster(tgt) or {}).get("type") or "").lower()
            if any(kind.startswith(k) for k in self.EXTRAPLANAR):
                return [("adv", "Mortal Bulwark")]
        return []

    def _subd_hit(self, att: dict, tgt: dict, R: dict, char) -> list:
        """[(dice, type, label)] a hit adds (and the riders that need a hit): Mortal Bulwark's banishing, Rend Mind's stun."""
        a = R.get("atk") or {}
        out = []
        if char is None or att.get("form") or tgt is att:
            return out
        if a.get("weapon") and any(e["name"] == "Mortal Bulwark" for e in att.get("effects") or []):
            kind = str((self._monster(tgt) or {}).get("type") or "").lower()
            st = self._subd_state(tgt)
            if any(kind.startswith(k) for k in self.EXTRAPLANAR) and not st.get("bulwark_immune") and self._alive(tgt):
                dc = self._spell_dc(att)
                res = self._saving_throw(tgt, "cha", dc, spell=True, source=att, label="Mortal Bulwark")
                if res["ok"]:
                    st["bulwark_immune"] = True
                    self._say(f"{tgt['name']} CHA save vs Mortal Bulwark: {res['total']} vs DC {dc} — holds (immune to it for a day)")
                else:
                    self._effect_on(tgt, "Banished (Mortal Bulwark)", ["Incapacitated"], None, None, None, None, att["name"], {"banished": True, "untargetable": True},
                                    None, att["id"])
                    self._say(f"{tgt['name']} CHA save vs Mortal Bulwark: {res['total']} vs DC {dc} — banished to its native plane")
        if (R.get("cur") or {}).get("sneaked") and a.get("psychic_blade") and F.sub_at(char, "Rogue", "Soulknife", 17) and self._alive(tgt) \
                and self._cf_left(att, "Rend Mind", 1) > 0:
            dc = 8 + char.proficiency_bonus + char.mod("dex")
            self._cf_use(att, "Rend Mind")
            res = self._saving_throw(tgt, "wis", dc, source=att, label="Rend Mind")
            self._say(f"{att['name']} sweeps a psychic blade through {tgt['name']}'s mind (Rend Mind): WIS {res['total']} vs DC {dc} — "
                      + ("shrugs it off" if res["ok"] else "stunned"))
            if not res["ok"]:
                self._effect_on(tgt, "Rend Mind", ["Stunned"], "wis", dc, "end", 10, att["name"], {}, None, att["id"])
        return out

    def _subd_damage(self, R: dict, att: Optional[dict], tgt: dict, rolled: list, parts: list) -> list:
        """Rolled damage of an attack, changed by Grave Touched (necrotic instead), Spell Bombardment and Power Surge."""
        char = self._sheet(att) if att else None
        if char is None or att.get("form") or not rolled:
            return rolled
        a = R.get("atk") or {}
        cur = R.get("cur") or {}
        if a.get("weapon") and F.sub_at(char, "Warlock", "The Undead", 6) and self._cf_turn_free(att, "grave_touched") and self.b.get("turn") == att["id"]:
            d = self._defenses(tgt)
            old = rolled[0][1]
            if not ({"necrotic"} & (set(d["immune"]) | set(d["resist"]))) or old in d["immune"] or old in d["resist"]:
                self._once_per_turn(att, "grave_touched")
                rolled[0][1] = "necrotic"
                import re as _re
                m = _re.match(r"^\d*d(\d+)", str(parts[0][0]).replace(" ", "")) if parts else None
                if m and any(e["name"] == "Form of Dread" for e in att.get("effects") or []):
                    rolled[0][0] += roll("1d" + m.group(1))
                self._say(f"{att['name']}'s grave-touched strike: necrotic instead of {old or 'weapon'} damage (Grave Touched)")
        if R.get("spell") and a.get("spell"):
            rolled = self._subd_spell_damage(R, att, char, tgt, rolled, parts, bool(cur.get("crit")))
        return rolled

    def _subd_rolled(self, R: dict, att: Optional[dict], rolled: list) -> list:
        """The damage of a save or automatic spell, rolled once (Spell Bombardment; Power Surge on a single target)."""
        char = self._sheet(att) if att else None
        if char is None or att.get("form") or not rolled or not R.get("spell"):
            return rolled
        tgts = [self._find_or_none(i) for i in R.get("targets") or []]
        tgt = tgts[0] if len(tgts) == 1 else None
        return self._subd_spell_damage(R, att, char, tgt, rolled, R.get("parts") or [], False)

    def _subd_spell_damage(self, R: dict, att: dict, char, tgt: Optional[dict], rolled: list, parts: list, crit: bool) -> list:
        import re as _re
        if F.sub_at(char, "Sorcerer", "Wild Magic", 18) and self._cf_turn_free(att, "bombard") and len(rolled) <= len(parts):
            for i, (dice, _t) in enumerate(parts[:len(rolled)]):
                m = _re.match(r"^(\d*)d(\d+)\s*([+-]\s*\d+)?$", str(dice).replace(" ", ""))
                if not m:
                    continue
                n, sides = int(m.group(1) or 1) * (2 if crit else 1), int(m.group(2))
                if sides > 1 and any(self.rng.randint(1, sides) == sides for _ in range(n)):
                    again = self.rng.randint(1, sides)
                    self._once_per_turn(att, "bombard")
                    rolled[i][0] += again
                    self._say(f"{att['name']}'s spell crackles with a maximum roll: +{again} (Spell Bombardment)")
                    break
        st = self._subd_state(att)
        if tgt is not None and F.sub_at(char, "Wizard", "War Magic", 6) and int(st.get("surges", 0)) > 0 and self._cf_turn_free(att, "power_surge") \
                and self.b.get("turn") == att["id"] and tgt is not att and self._hostile(att, tgt):
            st["surges"] = int(st["surges"]) - 1
            self._once_per_turn(att, "power_surge")
            n = max(1, char.class_level("Wizard") // 2)
            rolled.append([n, "force"])
            self._say(f"{att['name']} releases a stored Power Surge: +{n} force ({st['surges']} left)")
        return rolled

    def _subd_defense(self, tgt: dict, by: Optional[dict], d: dict, amounts, label: str) -> dict:
        """Emissary of Redemption: resistance to everything other creatures deal, until the paladin turns on that creature."""
        if by is None:
            return d
        if label not in ("Emissary of Redemption",):
            bc = self._sheet(by)
            if bc and not by.get("form") and by is not tgt and F.sub_at(bc, "Paladin", "Oath of Redemption", 20):
                off = self._subd_state(by).setdefault("emissary_off", [])
                if tgt["id"] not in off:
                    off.append(tgt["id"])                        # it attacked this creature: the benefits stop working against it
        tc = self._sheet(tgt)
        if tc and not tgt.get("form") and by is not tgt and F.sub_at(tc, "Paladin", "Oath of Redemption", 20) \
                and by["id"] not in self._subd_state(tgt).get("emissary_off", []):
            d = dict(d, resist=set(d["resist"]) | {t for _a, t in amounts if t})
        return d

    def _subd_dealt(self, tgt: dict, by: Optional[dict], types, taken: int, label: str, spell: bool):
        """Emissary of Redemption: a creature that hits the paladin takes radiant damage equal to half what the paladin took."""
        bc = self._sheet(by) if by is not None else None
        if bc and by is not tgt and taken > 0 and "necrotic" in types and not by.get("form") and F.sub_at(bc, "Warlock", "The Undead", 14) \
                and self._subd_fx_named(by, "Spirit Projection") and self._subd_fx_named(by, "Form of Dread") and self._once_per_turn(by, "projection_heal"):
            self._heal(by, max(1, taken // 2))
            self._say(f"{by['name']} drinks the necrotic damage: +{max(1, taken // 2)} HP (Spirit Projection)")
        tc = self._sheet(tgt)
        if by is None or by is tgt or taken <= 0 or spell or not tc or tgt.get("form") or label == "Emissary of Redemption" \
                or not F.sub_at(tc, "Paladin", "Oath of Redemption", 20) or by["id"] in self._subd_state(tgt).get("emissary_off", []) or not self._alive(by):
            return
        self._say(f"{tgt['name']}'s Emissary of Redemption: " + self._deal(by, [[max(1, taken // 2), "radiant"]], by=tgt, label="Emissary of Redemption", magical=True))

    def _subd_kill(self, by: Optional[dict], c: dict):
        """Master of Hexes: when the creature cursed by the Hexblade's Curse dies, the curse passes to another creature within 30 ft.
        Tokens of the Departed: a Phantom within 30 ft takes a soul trinket from the dying. A hound of ill omen goes when its target does."""
        for h in [h for h in self.b["combatants"] if h.get("hound_of") == c["id"] or (h is c and h.get("hound_of") is not None)]:
            if h is not c:
                self._vfx_unsummon(h)
                self._take_out(h)
                self._say(f"{h['name']} fades: its quarry has fallen")
        for o in self.b["combatants"]:
            oc = self._sheet(o)
            if oc and o is not c and not o.get("form") and self._alive(o) and F.sub_at(oc, "Rogue", "Phantom", 9) and self._may_react(o) and c.get("pos") \
                    and o.get("pos") and self._dist(o, c) <= 30 and self._sees(o, c) and int(self._subd_state(o).get("trinkets") or 0) < oc.proficiency_bonus \
                    and not c.get("conjured"):
                self._spend_reaction(o, "Tokens of the Departed")
                self._subd_state(o)["trinkets"] = int(self._subd_state(o).get("trinkets") or 0) + 1
                self._say(f"{o['name']} snatches a soul trinket from {c['name']} ({self._subd_state(o)['trinkets']}/{oc.proficiency_bonus}; Tokens of the Departed)")
        for o in self.b["combatants"]:
            oc = self._sheet(o)
            if not oc or o.get("form") or not F.sub_at(oc, "Warlock", "The Hexblade", 14) or not self._alive(o) or K.incapacitated(self._conds(o)):
                continue
            curse = next((e for e in c.get("effects") or [] if (e.get("mods") or {}).get("hex_curse") == o["id"]), None)
            if curse is None:
                continue
            foes = [x for x in self._cf_hostiles(o, 30) if x is not c and self._sees(o, x) and not any((e.get("mods") or {}).get("hex_curse") == o["id"] for e in x.get("effects") or [])]
            if not foes:
                continue
            nxt = min(foes, key=lambda x: (self._hp_of(x), self._dist(o, x)))
            mods = dict(curse["mods"])
            self._effect_on(nxt, curse["name"], [], None, None, None, curse.get("rounds"), o["name"], mods, None, o["id"])
            self._effect_off(c, curse, "the curse moved on")      # (so the usual hit points for a cursed creature's death are not paid)
            self._say(f"{o['name']} spreads the Hexblade's Curse from {c['name']} to {nxt['name']} (Master of Hexes)")

    def _subd_empowered_heal(self, att: Optional[dict], plan: dict, n: int, mod: int) -> int:
        """Empowered Healing: a Divine Soul sorcerer (or an ally within 5 ft of them) casting a healing spell may spend 1 sorcery point to
        roll the dice again, once a turn; the better total is kept."""
        if att is None:
            return n
        for o in self.b["combatants"]:
            oc = self._sheet(o)
            if not oc or o.get("form") or not F.sub_at(oc, "Sorcerer", "Divine Soul", 6) or not self._can_act(o) or not self._cf_turn_free(o, "empowered_heal") \
                    or not (o is att or (o.get("pos") and att.get("pos") and self._dist(o, att) <= 5)) or self._resource_left(o, "Sorcery Points") < 1:
                continue
            again = sum(roll(d) for d, _t in plan["parts"]) + mod + (roll(plan["heal_extra"]) if plan.get("heal_extra") else 0)
            if again > n:
                self._use_resource(o, "Sorcery Points", 1)
                self._once_per_turn(o, "empowered_heal")
                self._say(f"{o['name']} spends a sorcery point to reroll the healing: {n} → {again} (Empowered Healing)")
                n = again
                break
        return n

    def _subd_reflex(self, cur: Optional[dict]) -> bool:
        """Thief's Reflexes: in the first round a Thief takes a second turn at initiative minus 10 (True: the turn was chosen here).
        Called when `cur`'s turn has ended, instead of stepping on to the next creature."""
        b = self.b
        back = b.get("reflex_back")
        if back and cur is not None and cur["id"] == back["thief"]:     # the second turn is over: on to the creature it cut in front of
            b.pop("reflex_back")
            b["turn"] = back["resume"]
            if back.get("wrap"):
                b["round"] += 1
                self._tick_rounds()
            return True
        if back or b.get("round") != 1 or cur is None:
            return False
        rows = b["combatants"]
        thieves = [t for t in rows if (t.get("subd") or {}).get("reflex") and t.get("init") is not None and not self._skips_turn(t)]
        if not thieves:
            return False
        idx = rows.index(cur)
        nxt = next((r for r in rows[idx + 1:] if not self._skips_turn(r)), None)
        thief = max(thieves, key=lambda t: t["init"])
        if nxt is not None and (nxt.get("init") is None or nxt["init"] > thief["init"] - 10):
            return False
        thief["subd"]["reflex"] = False
        resume = nxt or next((r for r in rows if not self._skips_turn(r)), None)
        if resume is None:
            return False
        b["reflex_back"] = {"thief": thief["id"], "resume": resume["id"], "wrap": nxt is None}
        b["turn"] = thief["id"]
        for k in ("sneak_used", "strike_used", "trait_used"):       # a fresh turn: once-a-turn features come back
            thief.pop(k, None)
        self._say(f"{thief['name']} takes a second turn at initiative {thief['init'] - 10} (Thief's Reflexes)")
        return True

    DRAGON_TYPES = {"Black": "acid", "Blue": "lightning", "Brass": "fire", "Bronze": "lightning", "Copper": "acid", "Gold": "fire", "Green": "poison",
                    "Red": "fire", "Silver": "cold", "White": "cold"}

    def _subd_dragon_type(self, char) -> Optional[str]:
        """Dragon Ancestor: the damage type of a Draconic sorcerer's ancestor (the one picked on the sheet)."""
        from ...rules import combat_feats as CF
        pick = CF.is_on(char, "dragon_ancestor") if F.sub_at(char, "Sorcerer", "Draconic Bloodline", 1) else None
        return self.DRAGON_TYPES.get(pick) if pick else None

    def _subd_surge(self, c: Optional[dict]):
        """Power Surge: a War Magic wizard that ends a spell with dispel magic or counterspell gains a surge (up to Intelligence modifier, at least one)."""
        char = self._sheet(c) if c else None
        if not char or c.get("form") or not F.sub_at(char, "Wizard", "War Magic", 6):
            return
        st = self._subd_state(c)
        top = max(1, char.mod("int"))
        if int(st.get("surges", 0)) < top and self._once_per_turn(c, "surge_gain"):
            st["surges"] = int(st.get("surges", 0)) + 1
            self._say(f"{c['name']} steals magic from the foiled spell: a power surge stored ({st['surges']}/{top})")

    def _subd_deflect(self, pet: dict, R: dict, att: Optional[dict]):
        """Improved Defender: whenever the steel defender uses Deflect Attack the attacker takes 1d4 + Intelligence modifier force damage."""
        ctx = pet.get("summon") or {}
        if att is not None and ctx.get("bonus_ac") and self._alive(att) and "Steel Defender" in str(pet.get("monster") or ""):
            n = roll("1d4") + max(0, int(ctx.get("int") or 0))
            self._line(R, f"{pet['name']}'s Improved Defender: " + self._deal(att, [[n, "force"]], by=pet, label="Improved Defender", magical=True), "Improved Defender")

    def _subd_cast_note(self, att: dict):
        """Magical Ambush: a spell cast while hidden (called before the casting hides nothing any more)."""
        char = self._sheet(att)
        if char and not att.get("form") and F.sub_at(char, "Rogue", "Arcane Trickster", 9) and self._fx(att, "hidden"):
            self._subd_state(att)["ambush"] = [self.b.get("round"), self.b.get("turn")]

    def _subd_save_modes(self, c: dict, source: Optional[dict], spell: bool, modes: set, why: list):
        """Saves against a spell: Magical Ambush (the caster was hidden), a hound of ill omen beside the target."""
        if not spell or source is None or source is c:
            return
        st = source.get("subd") or {}
        if st.get("ambush") == [self.b.get("round"), self.b.get("turn")] and self._hostile(source, c):
            modes.add("dis")
            why.append("Magical Ambush")
        for e in c.get("effects") or []:
            if e["name"] == "Hound of Ill Omen" and e.get("source_id") == source["id"]:
                h = self._find_or_none((e.get("mods") or {}).get("hound"))
                if h is not None and self._alive(h) and c.get("pos") and h.get("pos") and self._dist(h, c) <= 5:
                    modes.add("dis")
                    why.append("Hound of Ill Omen")

    def _subd_trinket_wails(self, att: dict, pb: int) -> bool:
        """Wails from the Grave with a soul trinket instead of a use (True: it was paid with a trinket)."""
        if self._cf_left(att, "Wails from the Grave", pb) > 0:
            return False
        st = self._subd_state(att)
        st["trinkets"] = max(0, int(st.get("trinkets") or 0) - 1)
        return True

    def _subd_zero_hp(self, c: dict, dealt: int, types, crit: bool) -> bool:
        """Necrotic Husk: dropped to 0, an Undead warlock rises at 1 HP in a burst of deathly energy (a reaction; exhaustion follows)."""
        char = self._sheet(c)
        t = c.get("turn")
        if not char or c.get("form") or self._dead(c) or not F.sub_at(char, "Warlock", "The Undead", 10) \
                or (t is not None and self.b.get("status") == "active" and t.get("reaction", 1) <= 0) \
                or K.incapacitated([x for x in self._conds(c) if x not in ("Unconscious", "Prone")]) or not self._cf_left(c, "Necrotic Husk", 1):
            return False
        self._cf_use(c, "Necrotic Husk")
        self._spend_reaction(c, "Necrotic Husk")
        self._set_hp(c, 1)
        n = roll("2d10") + char.class_level("Warlock")
        foes = [o for o in self.b["combatants"] if o is not c and self._hostile(c, o) and o.get("pos") and self._alive(o) and c.get("pos") and self._within(c, o, 30)]
        bits = [self._deal(o, [[n, "necrotic"]], by=c, label="Necrotic Husk", magical=True) for o in foes]
        self._exhaust(c, 1)
        self._say(f"{c['name']}'s husk bursts with deathly energy and stays at 1 HP (Necrotic Husk, {n} necrotic, one level of exhaustion)"
                  + (": " + "; ".join(bits) if bits else ""))
        return True

    def _subd_dsave(self, c: dict, char, R: dict) -> bool:
        """Searing Vengeance: a Celestial warlock that must make a death save springs up instead, half its hit points back, radiance all around."""
        if c.get("form") or not F.sub_at(char, "Warlock", "The Celestial", 14) or not self._cf_left(c, "Searing Vengeance", 1) or self._dead(c):
            return False
        self._cf_use(c, "Searing Vengeance")
        fresh = self._sheet(c)
        fresh.d["death_saves"] = {"success": 0, "failure": 0}
        fresh.save()
        n = max(1, fresh.max_hp // 2)
        self._heal(c, n, revive=True)
        if "Unconscious" in self._conds(c):
            self._cond(c, "Unconscious", False)
        if "Prone" in self._conds(c):
            self._cond(c, "Prone", False)
        dc = 2
        foes = self._cf_hostiles(c, 30)
        bits = []
        for o in foes:
            bits.append(self._deal(o, [[roll("2d8") + max(0, char.mod("cha")), "radiant"]], by=c, label="Searing Vengeance", magical=True))
            self._effect_on(o, "Blinded (Searing Vengeance)", ["Blinded"], None, None, None, None, c["name"], {}, None, c["id"], until={"end": c["id"], "skip": 0})
        del dc
        self._say(f"{c['name']} springs back to their feet in a burst of radiance: {n} HP (Searing Vengeance)" + (": " + "; ".join(bits) if bits else ""))
        return True

    def _subd_dsave_done(self, c: dict, char, ok_roll: int):
        """Defy Death: a death save made (10 or more) gives an Undying warlock 1d8 + Constitution modifier hit points back, once a long rest."""
        if ok_roll >= 10 and char and not c.get("form") and F.sub_at(char, "Warlock", "The Undying", 6) and self._cf_left(c, "Defy Death", 1) > 0:
            self._cf_use(c, "Defy Death")
            n = max(1, roll("1d8") + char.mod("con"))
            self._heal(c, n)
            self._say(f"{c['name']} cheats death: +{n} HP (Defy Death)")

    def _subd_conc_safe(self, c: dict) -> bool:
        """Focused Conjuration: damage can't break the concentration on a conjuration spell."""
        char = self._sheet(c)
        st = c.get("concentrating")
        if char and not c.get("form") and st and CR.norm(st.get("spell") or "") == "evard's black tentacles" and F.sub_at(char, "Warlock", "The Fathomless", 10):
            return True                                          # Grasping Tentacles: damage can't break it
        if not char or c.get("form") or not st or not F.sub_at(char, "Wizard", "School of Conjuration", 10):
            return False
        from ...rules.data import rules
        sp = rules.spell(st["spell"])
        return bool(sp) and str(sp.get("school") or "").lower().startswith("conj")

    def _subd_sneak_again(self, att: dict, tgt: dict, R: dict) -> bool:
        """Sudden Strike's bonus attack may Sneak Attack even after one this turn, but not the same target twice."""
        char = self._sheet(att)
        return bool(char) and bool(R.get("sudden")) and F.sub_at(char, "Rogue", "Scout", 17) \
            and tgt["id"] not in (self._subd_state(att).get("sneak_on") or {}).get(f"{self.b.get('round')}:{self.b.get('turn')}", [])

    def _subd_sneak_note(self, att: dict, tgt: dict, R: dict):
        st = self._subd_state(att)
        key = f"{self.b.get('round')}:{self.b.get('turn')}"
        st["sneak_on"] = {key: (st.get("sneak_on") or {}).get(key, []) + [tgt["id"]]}
        (R.get("cur") or {}).update(sneaked=True)

    def _subd_sneak_extra(self, att: dict, tgt: dict, R: dict) -> list:
        """Eye for Weakness: +3d6 Sneak Attack damage against a creature Insightful Fighting applies to."""
        char = self._sheet(att)
        if char and F.sub_at(char, "Rogue", "Inquisitive", 17) and any((e.get("mods") or {}).get("insight_vs") == tgt["id"] for e in att.get("effects") or []):
            self._line(R, "Eye for Weakness (+3d6)", "Eye for Weakness")
            return [["3d6", ((R.get("atk") or {}).get("parts") or [["", ""]])[0][1]]]
        return []

    def _subd_may_target(self, att: dict, tgt: dict, R: dict) -> Optional[str]:
        """Among the Dead: an undead that targets an Undying warlock directly makes a Wisdom save or wastes the attack (once a day per undead)."""
        char = self._sheet(tgt)
        if char is None or tgt.get("form") or att is tgt or not F.sub_at(char, "Warlock", "The Undying", 1) \
                or not (R.get("mode") == "attack" or len(R.get("targets") or []) == 1):
            return None
        if not str((self._monster(att) or {}).get("type") or "").lower().startswith("undead"):
            return None
        done = self._subd_state(att).setdefault("among_dead", [])
        if tgt["id"] in done:
            return None
        done.append(tgt["id"])
        dc = self._spell_dc(tgt)
        res = self._saving_throw(att, "wis", dc, spell=True, source=tgt, label="Among the Dead")
        self._say(f"{att['name']} WIS save vs {tgt['name']}'s Among the Dead: {res['total']} vs DC {dc} — " + ("pushes through (immune for a day)" if res["ok"] else "turns away"))
        return None if res["ok"] else f"{att['name']} can't bring itself to strike {tgt['name']} (Among the Dead)"

    def _subd_shroud(self, reactor: dict):
        """Deflecting Shroud: Arcane Deflection also arcs force damage (half the wizard level) to up to three creatures within 60 ft."""
        char = self._sheet(reactor)
        if not char or not F.sub_at(char, "Wizard", "War Magic", 14):
            return
        foes = sorted((o for o in self._cf_hostiles(reactor, 60) if self._sees(reactor, o)), key=lambda o: self._dist(reactor, o))[:3]
        n = max(1, char.class_level("Wizard") // 2)
        if foes:
            self._say(f"{reactor['name']}'s Deflecting Shroud arcs force: " + "; ".join(
                self._deal(o, [[n, "force"]], by=reactor, label="Deflecting Shroud", magical=True) for o in foes))


F.ACTIVE.update(_sub_d_active())
