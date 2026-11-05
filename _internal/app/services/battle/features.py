"""Class, race and feat features in battle.

passives(char): the always-on ones as effect-like entries (Evasion, Danger Sense, Improved Critical, Fey Ancestry...).
ACTIVE: the ones a creature uses - each with its cost, the use counter it spends and what it does; the battle's
FeaturesMixin plays them out and the action bar lists them.
"""
import re
from typing import List, Optional

from ...rules.data import rules

ELEMENTS = ["acid", "cold", "fire", "lightning", "thunder"]


def _has(char, *names) -> bool:
    return any(char.has_feature(n) for n in names)


def _lvl(char, cls: str) -> int:
    return char.class_level(cls)


def _sub(char, cls: str) -> str:
    e = char.class_entry(cls) if hasattr(char, "class_entry") else None
    return (e or {}).get("subclass") or ""


def sub_at(char, cls: str, sub: str, level: int) -> bool:
    """The character has `cls` at `level` or more with this subclass (Hunter, Path of the Zealot...)."""
    return bool(char) and _lvl(char, cls) >= level and _sub(char, cls) == sub


def choice(char, key: str):
    """The option picked for a subclass's "choose one" feature (Hunter's Prey, Totem Spirit...: rules/combat_feats.py)."""
    from ...rules import combat_feats as CF
    return CF.is_on(char, key)


def mpmm(char) -> bool:
    """A Monsters of the Multiverse race (its traits count uses by proficiency bonus, per long rest)."""
    return "(MPMM)" in (char.d.get("race") or "") or (rules.races.get(char.race) or {}).get("source") == "MPMM"


def passives(char) -> List[dict]:
    out = []

    def add(name, **mods):
        out.append({"name": name, "mods": mods, "conditions": [], "feature": True})

    if _has(char, "Danger Sense"):
        add("Danger Sense", save_adv=["dex"])
    if _has(char, "Evasion"):
        add("Evasion", evasion=True)
    if _lvl(char, "Fighter") >= 3 and _sub(char, "Fighter") == "Champion":
        add("Improved Critical", crit=18 if _lvl(char, "Fighter") >= 15 else 19)
    if _has(char, "Fey Ancestry"):
        add("Fey Ancestry", cond_save_adv=["Charmed"])
    if _has(char, "Brave"):
        add("Brave", cond_save_adv=["Frightened"])
    if _has(char, "Dwarven Resilience"):
        add("Dwarven Resilience", cond_save_adv=["Poisoned"])
    if _has(char, "Gnome Cunning"):
        add("Gnome Cunning", save_adv_spells=["int", "wis", "cha"])
    if _has(char, "Lucky") and (char.d.get("race") or "").lower().startswith("halfling"):
        add("Lucky", lucky=True)
    if char.has_option("Devil's Sight"):
        add("Devil's Sight", senses={"devils_sight": 120})
    if char.has_option("Blind Fighting"):
        add("Blind Fighting", senses={"blindsight": 10})
    if _has(char, "Diamond Soul"):
        add("Diamond Soul", save_prof_all=True)
    if _lvl(char, "Paladin") >= 11:                         # Improved Divine Smite: every melee weapon hit
        add("Improved Divine Smite", dmg=("1d8", "radiant"), melee_only=True)
    if _lvl(char, "Rogue") >= 15:
        add("Slippery Mind", save_prof=["wis"])
    if _lvl(char, "Rogue") >= 18:
        add("Elusive", no_adv_against=True)
    if _lvl(char, "Rogue") >= 14 and _has(char, "Blindsense"):
        add("Blindsense", senses={"blindsight": 10})        # it knows where hidden and invisible creatures within 10 ft are
    if _lvl(char, "Ranger") >= 18 and _has(char, "Feral Senses"):
        add("Feral Senses", senses={"blindsight": 30})      # no disadvantage against creatures it can't see within 30 ft
    if _lvl(char, "Monk") >= 10:
        add("Purity of Body", immune=["poison"], immune_cond=["Poisoned"])
    if _has(char, "Aura of Courage"):
        add("Aura of Courage", immune_cond=["Frightened"])
    if _has(char, "Feral Instinct"):
        add("Feral Instinct", init_adv=True)
    from ...rules import combat_feats as CF
    if CF.is_on(char, "war_caster"):
        add("War Caster", conc_adv=True)
    if CF.is_on(char, "infernal_constitution"):
        add("Infernal Constitution", resist=["cold", "poison"], cond_save_adv=["Poisoned"])
    if _has(char, "Eldritch Mind"):
        add("Eldritch Mind", conc_adv=True)
    if _has(char, "Steel Will"):                            # Hunter 7 (the Defensive Tactics picked)
        add("Steel Will", cond_save_adv=["Frightened"])
    if sub_at(char, "Ranger", "Gloom Stalker", 7):
        add("Iron Mind", save_prof=["wis"] if "wis" not in char.d["proficiencies"]["saves"] else ["int"])
    if sub_at(char, "Cleric", "Forge Domain", 6):
        heavy = (char.equipped_armor() or {}).get("type") == "HA"
        add("Soul of the Forge", resist=["fire"], **({"ac": 1} if heavy else {}))
    if sub_at(char, "Warlock", "The Celestial", 6):
        add("Radiant Soul", resist=["radiant"])
    if sub_at(char, "Warlock", "The Fathomless", 6):
        add("Oceanic Soul", resist=["cold"])
    if sub_at(char, "Warlock", "The Fathomless", 1):
        add("Gift of the Sea", swim=40)                     # (the map has no water: noted for the sheet, breathes underwater)
    if sub_at(char, "Cleric", "Twilight Domain", 1):
        add("Eyes of Night", senses={"darkvision": 300})
    if sub_at(char, "Druid", "Circle of Spores", 14):
        add("Fungal Body", immune_cond=["Blinded", "Deafened", "Frightened", "Poisoned"], no_crit=True)
    if sub_at(char, "Druid", "Circle of the Land", 10):
        add("Nature's Ward", immune=["poison"], immune_cond=["Poisoned"])
    if sub_at(char, "Fighter", "Psi Warrior", 10):
        add("Guarded Mind", resist=["psychic"])
    if sub_at(char, "Paladin", "Oathbreaker", 7):
        add("Aura of Hate", dmg=(max(1, char.mod("cha")), ""), melee_only=True)
    if sub_at(char, "Druid", "Circle of the Land", 6):
        add("Land's Stride", free_move=True)                # difficult terrain costs no extra movement
    if sub_at(char, "Rogue", "Scout", 9):
        add("Superior Mobility", speed=10)
    if sub_at(char, "Rogue", "Scout", 13):
        add("Ambush Master", init_adv=True)
    if _has(char, "Stout Resilience"):
        add("Stout Resilience", cond_save_adv=["Poisoned"], resist=["poison"])
    if _has(char, "Gnomish Magic Resistance"):
        add("Gnomish Magic Resistance", save_adv_spells=["int", "wis", "cha"])
    if _has(char, "Mental Discipline"):
        add("Mental Discipline", cond_save_adv=["Charmed", "Frightened"])
    if _has(char, "Psychic Resilience"):
        add("Psychic Resilience", resist=["psychic"])
    if _has(char, "Celestial Resistance"):
        add("Celestial Resistance", resist=["necrotic", "radiant"])
    if _has(char, "Necrotic Resistance"):
        add("Necrotic Resistance", resist=["necrotic"])
    if _has(char, "Hellish Resistance"):
        add("Hellish Resistance", resist=["fire"])
    if _has(char, "Poison Resilience"):
        add("Poison Resilience", resist=["poison"], cond_save_adv=["Poisoned"])
    if _has(char, "Poison Immunity"):
        add("Poison Immunity", immune=["poison"], immune_cond=["Poisoned"])
    if _has(char, "Brittle Bones"):
        add("Brittle Bones", vuln=["bludgeoning"])
    if _has(char, "Undead Nature") and (char.d.get("race") or "") == "Skeleton":       # the DMG skeleton: no poison, no poisoned (exhaustion isn't played here)
        add("Undead Nature", immune=["poison"], immune_cond=["Poisoned"])
    if _has(char, "Mountain Born"):
        add("Mountain Born", resist=["cold"])
    if sub_at(char, "Warlock", "The Archfey", 10):
        add("Beguiling Defenses", immune_cond=["Charmed"])
    if sub_at(char, "Warlock", "The Great Old One", 10):
        add("Thought Shield", resist=["psychic"])
    if sub_at(char, "Druid", "Circle of the Moon", 6):
        add("Primal Strike", magic_attacks=True)            # beast-form attacks count as magical
    if sub_at(char, "Paladin", "Oath of Glory", 7):
        add("Aura of Alacrity", speed=10)
    if sub_at(char, "Barbarian", "Path of the Storm Herald", 6):
        add("Storm Soul", resist=[{"Desert": "fire", "Sea": "lightning", "Tundra": "cold"}.get(choice(char, "storm_aura"), "fire")])
    if sub_at(char, "Cleric", "War Domain", 17):
        add("Avatar of Battle", resist=["nonmagical"])
    if sub_at(char, "Cleric", "Forge Domain", 17):
        add("Saint of Forge and Fire", immune=["fire"], **({"resist": ["nonmagical"]} if (char.equipped_armor() or {}).get("type") == "HA" else {}))
    if sub_at(char, "Warlock", "The Genie", 6):
        from ...rules import combat_feats as CF2
        add("Elemental Gift", resist=[CF2.GENIE_TYPES.get(choice(char, "genie_kind"), "bludgeoning")])
    if sub_at(char, "Sorcerer", "Storm Sorcery", 18):
        add("Wind Soul", immune=["lightning", "thunder"], fly=60)
    elif sub_at(char, "Sorcerer", "Storm Sorcery", 6):
        add("Heart of the Storm", resist=["lightning", "thunder"])
    if sub_at(char, "Sorcerer", "Aberrant Mind", 6):
        add("Psychic Defenses", resist=["psychic"], cond_save_adv=["Charmed", "Frightened"])
    if sub_at(char, "Wizard", "School of Necromancy", 10):
        add("Inured to Undeath", resist=["necrotic"])
    if sub_at(char, "Wizard", "School of Abjuration", 14):
        add("Spell Resistance", save_adv=["spells"], resist=["spells"])
    if sub_at(char, "Artificer", "Armorer", 3) and choice(char, "armor_model") == "Infiltrator":
        add("Powered Steps", speed=5)
    if sub_at(char, "Artificer", "Alchemist", 15):
        add("Chemical Mastery", resist=["acid", "poison"], immune_cond=["Poisoned"])
    from .racefeats import passives as race_passives         # Loxodon Serenity, Leviathan Will, Dual Mind... (racefeats.py; imported late: it needs this module)
    return out + race_passives(char, {e["name"] for e in out})


def extra_attacks(char) -> int:
    """Attacks per Attack action."""
    f = _lvl(char, "Fighter")
    if f >= 20:
        return 4
    if f >= 11:
        return 3
    if f >= 5 or _has(char, "Extra Attack") or char.has_option("Thirsting Blade"):     # a pact of the blade warlock
        return 2
    return 1


DIVINE_STRIKE = {"Life Domain": "radiant", "Nature Domain": "cold", "Tempest Domain": "thunder", "Trickery Domain": "poison",
                 "War Domain": "", "Death Domain": "necrotic", "Forge Domain": "fire", "Order Domain": "psychic",
                 "Twilight Domain": "radiant"}                 # "" = the weapon's own damage type


def divine_strike(char) -> Optional[tuple]:
    """(dice, damage type) a cleric's Divine Strike adds once on each of its turns to a weapon hit (8th level; 2d8 at 14th)."""
    lv = _lvl(char, "Cleric")
    sub = _sub(char, "Cleric")
    if lv < 8 or sub not in DIVINE_STRIKE:
        return None
    return ("2d8" if lv >= 14 else "1d8", DIVINE_STRIKE[sub])


def sneak_dice(char) -> Optional[str]:
    lv = _lvl(char, "Rogue")
    return f"{(lv + 1) // 2}d6" if lv else None


def brutal_dice(char) -> int:
    lv = _lvl(char, "Barbarian")
    return 3 if lv >= 17 else 2 if lv >= 13 else 1 if lv >= 9 else 0


def savage(char) -> bool:
    return _has(char, "Savage Attacks")


def rage_damage(char) -> int:
    lv = _lvl(char, "Barbarian")
    return 4 if lv >= 16 else 3 if lv >= 9 else 2


def rage_extras(char) -> dict:
    """What a barbarian's path adds to its Rage: the Bear totem's resistances, the Elk's speed, Mindless Rage."""
    out = {}
    if sub_at(char, "Barbarian", "Path of the Totem Warrior", 3):
        heavy = (char.equipped_armor() or {}).get("type") == "HA"
        totem = choice(char, "totem_spirit")
        if totem == "Bear":
            from .modifiers import TYPES
            out["resist"] = [t for t in TYPES if t != "psychic"]
        elif totem == "Elk" and not heavy:
            out["speed"] = 15
    if sub_at(char, "Barbarian", "Path of the Berserker", 6):
        out["immune_cond"] = ["Charmed", "Frightened"]
    if sub_at(char, "Barbarian", "Path of the Giant", 3):         # Giant Stature: +5 ft reach (10 at 14th), Large (Huge at 14th if chosen)
        sizes = ["Tiny", "Small", "Medium", "Large", "Huge", "Gargantuan"]
        grand = sub_at(char, "Barbarian", "Path of the Giant", 14)
        big = "Huge" if grand and choice(char, "colossus_size") == "Huge" else "Large"
        out["size_step"] = max(0, sizes.index(big) - (sizes.index(char.size) if char.size in sizes else 2))
        out["giant_reach"] = 10 if grand else 5
    if sub_at(char, "Barbarian", "Path of the Giant", 6):         # Elemental Cleaver: the first weapon in hand is infused when the rage starts
        held = next((a for a in char.attacks() if "unarmed" not in (a.get("props") or [])), None)
        if held:
            out["cleaver"] = choice(char, "cleaver_element") or "fire"
            out["cleaver_weapon"] = held["name"]
            out["cleaver_dice"] = "2d6" if sub_at(char, "Barbarian", "Path of the Giant", 14) else "1d6"
    return out


def martial_die(char) -> Optional[str]:
    v = char.table_value("Monk", "Martial Arts")
    return str(v) if v else None


def bardic_die(char) -> str:
    """The Bardic Inspiration die by bard level: 1d6, 1d8 at 5th, 1d10 at 10th, 1d12 at 15th (the class table doesn't list it)."""
    lv = char.class_level("Bard")
    return "1d12" if lv >= 15 else "1d10" if lv >= 10 else "1d8" if lv >= 5 else "1d6"


def superiority_die(char) -> str:
    lv = _lvl(char, "Fighter")
    if not sub_at(char, "Fighter", "Battle Master", 3):
        return "d6"                                         # Martial Adept, Superior Technique
    return "d12" if lv >= 18 else "d10" if lv >= 10 else "d8"


METAMAGIC = {"Quickened Spell": 2, "Twinned Spell": "level", "Heightened Spell": 3, "Distant Spell": 1, "Careful Spell": 1,
             "Extended Spell": 1, "Subtle Spell": 1, "Empowered Spell": 1}


def metamagic(char) -> List[dict]:
    """[{'name', 'cost'}] - the Metamagic options the sorcerer knows."""
    return [{"name": n, "cost": c} for n, c in METAMAGIC.items() if char.has_option(n)]


def ki_dc(char) -> int:
    return 8 + char.proficiency_bonus + char.mod("wis")


def smite_dice(slot: int, undead: bool = False) -> str:
    n = min(5, 1 + slot) + (1 if undead else 0)
    return f"{n}d8"


# ---------------------------------------------------------------------- active features
# key: {name, cost, resource (use counter in rules/resources.py, or None), per: uses per rest when there is no counter,
#       needs: fn(char) -> bool, target: 'self' | 'creature' | 'ally' | 'enemy' | 'none', range (feet), text}
ACTIVE = {
    "second_wind": {"name": "Second Wind", "cost": "bonus", "resource": "Second Wind", "target": "self",
                    "needs": lambda c: _lvl(c, "Fighter") >= 1, "text": "Regain 1d10 + fighter level hit points."},
    "action_surge": {"name": "Action Surge", "cost": "free", "resource": "Action Surge", "target": "self",
                     "needs": lambda c: _lvl(c, "Fighter") >= 2, "text": "Take one additional action this turn."},
    "rage": {"name": "Rage", "cost": "bonus", "resource": "Rage", "target": "self", "needs": lambda c: _lvl(c, "Barbarian") >= 1,
             "text": "Advantage on Strength checks and saves, +rage damage on Strength melee hits, resistance to bludgeoning, piercing and slashing."},
    "reckless": {"name": "Reckless Attack", "cost": "free", "resource": None, "target": "self", "needs": lambda c: _lvl(c, "Barbarian") >= 2,
                 "text": "Advantage on your Strength melee attacks this turn; attacks against you have advantage until your next turn."},
    "cunning_dash": {"name": "Cunning Action: Dash", "cost": "bonus", "resource": None, "target": "self", "needs": lambda c: _lvl(c, "Rogue") >= 2,
                     "text": "Dash as a bonus action."},
    "cunning_disengage": {"name": "Cunning Action: Disengage", "cost": "bonus", "resource": None, "target": "self",
                          "needs": lambda c: _lvl(c, "Rogue") >= 2, "text": "Disengage as a bonus action."},
    "cunning_hide": {"name": "Cunning Action: Hide", "cost": "bonus", "resource": None, "target": "self", "needs": lambda c: _lvl(c, "Rogue") >= 2,
                     "text": "Hide as a bonus action."},
    "steady_aim": {"name": "Steady Aim", "cost": "bonus", "resource": None, "target": "self", "needs": lambda c: _has(c, "Steady Aim"),
                   "text": "Advantage on your next attack this turn; you can't move this turn."},
    "martial_arts": {"name": "Martial Arts strike", "cost": "bonus", "resource": None, "target": "enemy", "range": 5,
                     "needs": lambda c: _lvl(c, "Monk") >= 1, "text": "One unarmed strike as a bonus action after the Attack action."},
    "flurry": {"name": "Flurry of Blows", "cost": "bonus", "resource": "Ki Points", "target": "enemy", "range": 5,
               "needs": lambda c: _lvl(c, "Monk") >= 2, "text": "Spend 1 ki: two unarmed strikes as a bonus action."},
    "patient_defense": {"name": "Patient Defense", "cost": "bonus", "resource": "Ki Points", "target": "self",
                        "needs": lambda c: _lvl(c, "Monk") >= 2, "text": "Spend 1 ki: Dodge as a bonus action."},
    "step_of_the_wind": {"name": "Step of the Wind", "cost": "bonus", "resource": "Ki Points", "target": "self",
                         "needs": lambda c: _lvl(c, "Monk") >= 2, "text": "Spend 1 ki: Dash or Disengage as a bonus action."},
    "stunning_strike": {"name": "Stunning Strike", "cost": "free", "resource": "Ki Points", "target": "enemy", "range": 5, "passive": True,
                        "needs": lambda c: _lvl(c, "Monk") >= 5, "text": "After a melee hit: spend 1 ki, the target makes a Con save or is stunned until the end of your next turn."},
    "lay_on_hands": {"name": "Lay on Hands", "cost": "action", "resource": "Lay on Hands (HP pool)", "target": "ally", "range": 5,
                     "needs": lambda c: _lvl(c, "Paladin") >= 1, "text": "Restore hit points from your pool."},
    "divine_smite": {"name": "Divine Smite", "cost": "free", "resource": None, "target": "enemy", "range": 5, "passive": True,
                     "needs": lambda c: _lvl(c, "Paladin") >= 2, "text": "After a melee hit: spend a spell slot for 2d8 radiant (+1d8 per level above 1st, +1d8 vs undead or fiends)."},
    "bardic_inspiration": {"name": "Bardic Inspiration", "cost": "bonus", "resource": "Bardic Inspiration", "target": "ally", "range": 60,
                           "needs": lambda c: _lvl(c, "Bard") >= 1, "text": "An ally gains an inspiration die to add to one attack, check or save."},
    "bladesong": {"name": "Bladesong", "cost": "bonus", "resource": "Bladesong", "target": "self",
                  "needs": lambda c: _lvl(c, "Wizard") >= 2 and _sub(c, "Wizard") == "Bladesinging",
                  "text": "For a minute: + Intelligence to AC and concentration saves, +10 ft speed (no medium or heavy armour, shield or two-handed weapon)."},
    "vow_of_enmity": {"name": "Vow of Enmity", "cost": "bonus", "resource": "Channel Divinity (Paladin)", "target": "enemy", "range": 10,
                      "needs": lambda c: _lvl(c, "Paladin") >= 3 and _sub(c, "Paladin") == "Oath of Vengeance",
                      "text": "Advantage on your attacks against one creature within 10 ft for 1 minute."},
    "sacred_weapon": {"name": "Sacred Weapon", "cost": "action", "resource": "Channel Divinity (Paladin)", "target": "self",
                      "needs": lambda c: _lvl(c, "Paladin") >= 3 and _sub(c, "Paladin") == "Oath of Devotion",
                      "text": "Add your Charisma modifier (at least +1) to weapon attack rolls for 1 minute."},
    "preserve_life": {"name": "Preserve Life", "cost": "action", "resource": "Channel Divinity (Cleric)", "target": "none",
                      "needs": lambda c: _lvl(c, "Cleric") >= 2 and _sub(c, "Cleric") == "Life Domain",
                      "text": "Share 5 x cleric level hit points among creatures within 30 ft, none above half its maximum."},
    "turn_undead": {"name": "Turn Undead", "cost": "action", "resource": "Channel Divinity (Cleric)", "target": "none",
                    "needs": lambda c: _lvl(c, "Cleric") >= 2, "text": "Undead within 30 ft make a Wisdom save or are turned for 1 minute (destroyed at low CR)."},
    "breath_weapon": {"name": "Breath Weapon", "cost": "action", "resource": None, "per": lambda c: "long" if _ftd_breath(c) else "short",
                      "uses": lambda c: c.proficiency_bonus if _ftd_breath(c) else 1, "target": "area",
                      "needs": lambda c: breath(c) is not None, "text": "Exhale destructive energy (Dex or Con save)."},
    "healing_hands": {"name": "Healing Hands", "cost": "action", "resource": None, "per": "long", "target": "ally", "range": 5,
                      "needs": lambda c: _has(c, "Healing Hands"), "text": "Touch a creature: it regains hit points equal to your level."},
    "relentless_endurance": {"name": "Relentless Endurance", "cost": "free", "resource": None, "per": "long", "target": "self", "passive": True,
                             "needs": lambda c: _has(c, "Relentless Endurance"), "text": "When reduced to 0 hit points, drop to 1 instead (once per long rest)."},
    "wild_shape": {"name": "Wild Shape", "cost": "action", "resource": "Wild Shape", "target": "self",
                   "needs": lambda c: _lvl(c, "Druid") >= 2 and _sub(c, "Druid") != "Circle of the Moon",
                   "text": "Turn into a beast (pick its stat block); its hit points take damage first."},
    # ---- subclasses, races (classfeats.py plays these: _class_feature)
    # extra keys: 'per' / 'uses' may be functions of the character; 'options' fn(char) -> [{'value', 'label'}];
    # 'when' 'raging' | 'attacked' (after the Attack action) | 'cantrip' (after an action cantrip) | 'starry'; 'ki' (points it costs)
    "combat_wild_shape": {"name": "Combat Wild Shape", "cost": "bonus", "resource": "Wild Shape", "target": "self",
                          "needs": lambda c: sub_at(c, "Druid", "Circle of the Moon", 2),
                          "text": "Wild Shape as a bonus action (Circle of the Moon): turn into a beast; its hit points take damage first."},
    "harness_cleric": {"name": "Harness Divine Power", "cost": "bonus", "resource": "Channel Divinity (Cleric)", "target": "self", "per": "long",
                       "uses": lambda c: 3 if _lvl(c, "Cleric") >= 18 else 2 if _lvl(c, "Cleric") >= 6 else 1,
                       "needs": lambda c: _lvl(c, "Cleric") >= 2 and _has(c, "Channel Divinity: Harness Divine Power"), "options": lambda c: harness_options(c),
                       "text": "Spend a Channel Divinity: regain one expended spell slot of up to half your proficiency bonus (rounded up)."},
    "harness_paladin": {"name": "Harness Divine Power", "cost": "bonus", "resource": "Channel Divinity (Paladin)", "target": "self", "per": "long",
                        "uses": lambda c: 3 if _lvl(c, "Paladin") >= 15 else 2 if _lvl(c, "Paladin") >= 7 else 1,
                        "needs": lambda c: _lvl(c, "Paladin") >= 3 and _lvl(c, "Cleric") < 2 and _has(c, "Channel Divinity: Harness Divine Power"),
                        "options": lambda c: harness_options(c),
                        "text": "Spend a Channel Divinity: regain one expended spell slot of up to half your proficiency bonus (rounded up)."},
    "turn_unholy": {"name": "Turn the Unholy", "cost": "action", "resource": "Channel Divinity (Paladin)", "target": "none",
                    "needs": lambda c: sub_at(c, "Paladin", "Oath of Devotion", 3),
                    "text": "Fiends and undead within 30 ft make a Wisdom save or are turned for 1 minute (or until they take damage)."},
    "turn_faithless": {"name": "Turn the Faithless", "cost": "action", "resource": "Channel Divinity (Paladin)", "target": "none",
                       "needs": lambda c: sub_at(c, "Paladin", "Oath of the Ancients", 3),
                       "text": "Fey and fiends within 30 ft make a Wisdom save or are turned for 1 minute (or until they take damage)."},
    "abjure_enemy": {"name": "Abjure Enemy", "cost": "action", "resource": "Channel Divinity (Paladin)", "target": "enemy", "range": 60,
                     "needs": lambda c: sub_at(c, "Paladin", "Oath of Vengeance", 3),
                     "text": "A creature within 60 ft makes a Wisdom save (fiends and undead with disadvantage): frightened with speed 0 for "
                             "1 minute; on a success its speed is halved."},
    "natures_wrath": {"name": "Nature's Wrath", "cost": "action", "resource": "Channel Divinity (Paladin)", "target": "enemy", "range": 10,
                      "needs": lambda c: sub_at(c, "Paladin", "Oath of the Ancients", 3),
                      "text": "Spectral vines: a creature within 10 ft makes a Strength or Dexterity save (its choice) or is restrained; it "
                              "repeats the save at the end of each of its turns."},
    "conquering_presence": {"name": "Conquering Presence", "cost": "action", "resource": "Channel Divinity (Paladin)", "target": "none",
                            "needs": lambda c: sub_at(c, "Paladin", "Oath of Conquest", 3),
                            "text": "Each foe within 30 ft makes a Wisdom save or is frightened for 1 minute (save again at the end of each of its turns)."},
    "radiance_of_the_dawn": {"name": "Radiance of the Dawn", "cost": "action", "resource": "Channel Divinity (Cleric)", "target": "none",
                             "needs": lambda c: sub_at(c, "Cleric", "Light Domain", 2),
                             "text": "Each foe within 30 ft makes a Constitution save: 2d10 + cleric level radiant damage, half on a success."},
    "twilight_sanctuary": {"name": "Twilight Sanctuary", "cost": "action", "resource": "Channel Divinity (Cleric)", "target": "self",
                           "needs": lambda c: sub_at(c, "Cleric", "Twilight Domain", 2),
                           "text": "For a minute, you and your allies within 30 ft gain 1d6 + cleric level temporary hit points on each turn "
                                   "(a charmed or frightened one shakes that off instead)."},
    "path_to_the_grave": {"name": "Path to the Grave", "cost": "action", "resource": "Channel Divinity (Cleric)", "target": "enemy", "range": 30,
                          "needs": lambda c: sub_at(c, "Cleric", "Grave Domain", 2),
                          "text": "Curse a creature within 30 ft: it is vulnerable to all the damage of the next hit against it."},
    "orders_demand": {"name": "Order's Demand", "cost": "action", "resource": "Channel Divinity (Cleric)", "target": "none",
                      "needs": lambda c: sub_at(c, "Cleric", "Order Domain", 2),
                      "text": "Each foe within 30 ft makes a Wisdom save or is charmed by you until the end of your next turn."},
    "war_priest": {"name": "War Priest attack", "cost": "bonus", "resource": None, "per": "long", "uses": lambda c: max(1, c.mod("wis")),
                   "target": "enemy", "when": "attacked", "needs": lambda c: sub_at(c, "Cleric", "War Domain", 1),
                   "text": "After the Attack action: one weapon attack as a bonus action (Wisdom modifier times per long rest)."},
    "intimidating_presence": {"name": "Intimidating Presence", "cost": "action", "resource": None, "target": "enemy", "range": 30,
                              "needs": lambda c: sub_at(c, "Barbarian", "Path of the Berserker", 10),
                              "text": "A creature within 30 ft makes a Wisdom save or is frightened of you until the end of your next turn."},
    "eagle_dash": {"name": "Eagle spirit: Dash", "cost": "bonus", "resource": None, "target": "self", "when": "raging",
                   "needs": lambda c: sub_at(c, "Barbarian", "Path of the Totem Warrior", 3) and choice(c, "totem_spirit") == "Eagle",
                   "text": "While raging (and not in heavy armour): Dash as a bonus action."},
    "wholeness_of_body": {"name": "Wholeness of Body", "cost": "action", "resource": None, "per": "long", "target": "self",
                          "needs": lambda c: sub_at(c, "Monk", "Way of the Open Hand", 6),
                          "text": "Regain hit points equal to three times your monk level (once per long rest)."},
    "stillness_of_mind": {"name": "Stillness of Mind", "cost": "action", "resource": None, "target": "self", "needs": lambda c: _lvl(c, "Monk") >= 7,
                          "text": "End one effect on you that makes you charmed or frightened."},
    "quickened_healing": {"name": "Quickened Healing", "cost": "action", "resource": "Ki Points", "ki": 2, "target": "self",
                          "needs": lambda c: _lvl(c, "Monk") >= 4 and _has(c, "Quickened Healing"),
                          "text": "Spend 2 ki: regain a Martial Arts die roll + your proficiency bonus in hit points."},
    "empty_body": {"name": "Empty Body", "cost": "action", "resource": "Ki Points", "ki": 4, "target": "self", "needs": lambda c: _lvl(c, "Monk") >= 18,
                   "text": "Spend 4 ki: invisible for 1 minute, with resistance to all damage but force."},
    "radiant_sun_bolt": {"name": "Radiant Sun Bolt", "cost": "attack", "resource": None, "target": "enemy", "range": 30,
                         "needs": lambda c: sub_at(c, "Monk", "Way of the Sun Soul", 3),
                         "text": "In place of an attack of the Attack action: a ranged spell attack (30 ft), Martial Arts die + Dexterity radiant."},
    "hand_of_healing": {"name": "Hand of Healing", "cost": "action", "resource": "Ki Points", "target": "ally", "range": 5,
                        "needs": lambda c: sub_at(c, "Monk", "Way of Mercy", 3),
                        "text": "Spend 1 ki: a creature you touch regains a Martial Arts die roll + your Wisdom modifier in hit points."},
    "feinting_attack": {"name": "Feinting Attack", "cost": "bonus", "resource": "Superiority Dice", "target": "enemy", "range": 5,
                        "needs": lambda c: c.has_option("Feinting Attack"),
                        "text": "Advantage on your next attack against a creature within 5 ft this turn; a hit adds the superiority die to the damage."},
    "companion": {"name": "Call companion", "cost": "free", "resource": None, "target": "self", "needs": lambda c: companions(c) != [],
                  "options": lambda c: [{"value": m, "label": m.split("|")[0]} for m in companions(c)],
                  "text": "Bring your class companion onto the map beside you (Primal Companion, Steel Defender, Drake Companion, "
                          "Homunculus Servant); it acts on your initiative."},
    "wildfire_spirit": {"name": "Summon Wildfire Spirit", "cost": "action", "resource": "Wild Shape", "target": "self",
                        "needs": lambda c: sub_at(c, "Druid", "Circle of Wildfire", 2),
                        "text": "Spend a Wild Shape: a wildfire spirit appears; creatures within 10 ft of it (other than you) make a Dexterity "
                                "save or take 2d6 fire damage."},
    "fey_step": {"name": "Fey Step", "cost": "bonus", "resource": None, "per": lambda c: "long" if mpmm(c) else "short",
                 "uses": lambda c: c.proficiency_bonus if mpmm(c) else 1, "target": "point", "teleport": 30, "needs": lambda c: _has(c, "Fey Step"),
                 "text": "Teleport up to 30 ft to an unoccupied space you can see."},
    "shadow_step": {"name": "Shadow Step", "cost": "bonus", "resource": None, "target": "point", "teleport": 60,
                    "needs": lambda c: sub_at(c, "Monk", "Way of Shadow", 6),
                    "text": "From dim light or darkness, teleport up to 60 ft to another dim or dark space; advantage on your next melee "
                            "attack this turn."},
    "benign_transposition": {"name": "Benign Transposition", "cost": "action", "resource": None, "per": "long", "target": "point", "teleport": 30,
                             "needs": lambda c: sub_at(c, "Wizard", "School of Conjuration", 6),
                             "text": "Teleport up to 30 ft to an unoccupied space you can see."},
    "rabbit_hop": {"name": "Rabbit Hop", "cost": "bonus", "resource": None, "per": "long", "uses": lambda c: c.proficiency_bonus,
                   "target": "point", "teleport": lambda c: 5 * c.proficiency_bonus, "needs": lambda c: _has(c, "Rabbit Hop"),
                   "text": "Jump up to 5 x your proficiency bonus in feet without provoking opportunity attacks."},
    "raven_queen": {"name": "Blessing of the Raven Queen", "cost": "bonus", "resource": None, "per": "long", "uses": lambda c: c.proficiency_bonus,
                    "target": "point", "teleport": 30, "needs": lambda c: _has(c, "Blessing of the Raven Queen"),
                    "text": "Teleport up to 30 ft; from 3rd level you resist all damage until the start of your next turn."},
    "gem_flight": {"name": "Gem Flight", "cost": "bonus", "resource": None, "per": "long", "target": "self",
                   "needs": lambda c: c.total_level >= 5 and _has(c, "Gem Flight"),
                   "text": "Spectral wings for 1 minute: a flying speed equal to your walking speed."},
    "metallic_breath": {"name": "Metallic Breath Weapon", "cost": "action", "resource": None, "per": "long", "target": "none",
                        "needs": lambda c: c.total_level >= 5 and _has(c, "Metallic Breath Weapon"),
                        "options": lambda c: [{"value": "enervating", "label": "Enervating (Con save or incapacitated)"},
                                              {"value": "repulsion", "label": "Repulsion (Str save or pushed 20 ft, prone)"}],
                        "text": "A 15-ft cone: Enervating breath (Con save or incapacitated until the start of your next turn) or Repulsion "
                                "breath (Str save or pushed 20 ft and knocked prone)."},
    "goring_rush": {"name": "Goring Rush", "cost": "bonus", "resource": None, "target": "enemy", "range": 5, "when": "dashed",
                    "needs": lambda c: _has(c, "Goring Rush"), "text": "After you Dash and move 20 ft: a horns attack as a bonus action."},
    "hammering_horns": {"name": "Hammering Horns", "cost": "bonus", "resource": None, "target": "enemy", "range": 5, "when": "attacked",
                        "needs": lambda c: _has(c, "Hammering Horns"),
                        "text": "After hitting with a melee attack in the Attack action: shove the creature 10 ft (Strength save)."},
    "nimble_escape": {"name": "Nimble Escape", "cost": "bonus", "resource": None, "target": "self", "needs": lambda c: _has(c, "Nimble Escape"),
                      "options": lambda c: [{"value": "disengage", "label": "Disengage"}, {"value": "hide", "label": "Hide"}],
                      "text": "Disengage or Hide as a bonus action."},
    "aggressive": {"name": "Aggressive", "cost": "bonus", "resource": None, "target": "self", "needs": lambda c: _has(c, "Aggressive"),
                   "text": "Move up to your speed toward a hostile creature you can see (a Dash as a bonus action)."},
    "vanish": {"name": "Vanish: Hide", "cost": "bonus", "resource": None, "target": "self",
               "needs": lambda c: _lvl(c, "Ranger") >= 14 and _has(c, "Vanish"), "text": "Hide as a bonus action."},
    "cleansing_touch": {"name": "Cleansing Touch", "cost": "action", "resource": None, "per": "long", "uses": lambda c: max(1, c.mod("cha")),
                        "target": "ally", "range": 5, "needs": lambda c: _lvl(c, "Paladin") >= 14,
                        "text": "End one spell on yourself or a willing creature you touch."},
    "inspiring_leader": {"name": "Inspiring Leader", "cost": "action", "resource": None, "per": "short", "target": "none",
                         "needs": lambda c: "Inspiring Leader" in (c.d.get("feats") or []),
                         "text": "A rousing speech (10 minutes, so before the fight): up to six allies within 30 ft gain temporary hit points "
                                 "equal to your level + Charisma modifier."},
    "emboldening_bond": {"name": "Emboldening Bond", "cost": "action", "resource": None, "per": "long", "uses": lambda c: c.proficiency_bonus,
                         "target": "none", "needs": lambda c: sub_at(c, "Cleric", "Peace Domain", 1),
                         "text": "Bond yourself and allies within 30 ft (your proficiency bonus in creatures) for 10 minutes: once a turn, near "
                                 "another bonded creature, one may add 1d4 to an attack roll or save it just missed or failed."},
    "quivering_palm": {"name": "Quivering Palm: end the vibrations", "cost": "action", "resource": None, "target": "enemy",
                       "needs": lambda c: sub_at(c, "Monk", "Way of the Open Hand", 17),
                       "text": "A creature you set vibrating (3 ki on an unarmed hit) makes a Constitution save: it drops to 0 hit points on a "
                               "failure, takes 10d10 necrotic on a success."},
    "water_whip": {"name": "Water Whip", "cost": "action", "resource": "Ki Points", "ki": 2, "target": "enemy", "range": 30,
                   "needs": lambda c: sub_at(c, "Monk", "Way of the Four Elements", 3) and c.has_option("Water Whip"),
                   "text": "Spend 2 ki: a creature within 30 ft makes a Dexterity save: 3d10 bludgeoning and knocked prone, half damage on a success."},
    "unbroken_air": {"name": "Fist of Unbroken Air", "cost": "action", "resource": "Ki Points", "ki": 2, "target": "enemy", "range": 30,
                     "needs": lambda c: sub_at(c, "Monk", "Way of the Four Elements", 3) and c.has_option("Unbroken Air"),
                     "text": "Spend 2 ki: a creature within 30 ft makes a Strength save: 3d10 bludgeoning, pushed 20 ft and knocked prone; half "
                             "damage on a success."},
    "fangs_fire_snake": {"name": "Fangs of the Fire Snake", "cost": "free", "resource": "Ki Points", "target": "self", "when": "attacked",
                         "needs": lambda c: sub_at(c, "Monk", "Way of the Four Elements", 3) and c.has_option("Fangs of the Fire Snake"),
                         "text": "Spend 1 ki with the Attack action: your unarmed strikes reach 10 ft farther and deal fire damage this turn."},
    "astral_arms": {"name": "Arms of the Astral Self", "cost": "bonus", "resource": "Ki Points", "target": "self",
                    "needs": lambda c: sub_at(c, "Monk", "Way of the Astral Self", 3),
                    "text": "Spend 1 ki: spectral arms for 10 minutes. Foes within 10 ft make a Dexterity save or take two Martial Arts dice of "
                            "force damage; your unarmed strikes use Wisdom, reach 5 ft farther and deal force damage."},
    "evasive_footwork": {"name": "Evasive Footwork", "cost": "free", "resource": "Superiority Dice", "target": "self",
                         "needs": lambda c: c.has_option("Evasive Footwork"),
                         "text": "As you move: add a superiority die roll to your AC until the end of your turn."},
    "master_of_tactics": {"name": "Master of Tactics: Help", "cost": "bonus", "resource": None, "target": "enemy", "range": 30,
                          "needs": lambda c: sub_at(c, "Rogue", "Mastermind", 3) or _has(c, "Fey Gift"),
                          "text": "The Help action as a bonus action: the next attack an ally makes against a creature within 30 ft of you has advantage."},
    "unearthly_recovery": {"name": "Unearthly Recovery", "cost": "bonus", "resource": None, "per": "long", "target": "self",
                           "needs": lambda c: sub_at(c, "Sorcerer", "Divine Soul", 18),
                           "text": "Below half your hit points: regain hit points equal to half your hit point maximum."},
    "umbral_form": {"name": "Umbral Form", "cost": "bonus", "resource": "Sorcery Points", "ki": 6, "target": "self",
                    "needs": lambda c: sub_at(c, "Sorcerer", "Shadow Magic", 18),
                    "text": "Spend 6 sorcery points: a shadowy form for 1 minute; resistance to all damage but force and radiant."},
    "draconic_presence": {"name": "Draconic Presence", "cost": "action", "resource": "Sorcery Points", "ki": 5, "target": "none",
                          "needs": lambda c: sub_at(c, "Sorcerer", "Draconic Bloodline", 18),
                          "options": lambda c: [{"value": "fear", "label": "Fear (frightened)"}, {"value": "awe", "label": "Awe (charmed)"}],
                          "text": "Spend 5 sorcery points: foes within 60 ft make a Wisdom save or are frightened (or charmed) for 1 minute."},
    "paladin_capstone": {"name": "Sacred Oath capstone", "cost": "action", "resource": None, "per": "long", "target": "self",
                         "needs": lambda c: _lvl(c, "Paladin") >= 20 and _sub(c, "Paladin") in CAPSTONES,
                         "text": "Holy Nimbus (foes starting a turn within 30 ft take 10 radiant), Avenging Angel (fly 60 ft, frightening "
                                 "aura), Elder Champion (regain 10 HP a turn), Invincible Conqueror (resist all damage, crit on 19-20) or "
                                 "Living Legend (once a turn a miss becomes a hit): 1 minute."},
    "hidden_paths": {"name": "Hidden Paths", "cost": "bonus", "resource": None, "per": "long", "uses": lambda c: max(1, c.mod("wis")),
                     "target": "point", "teleport": 60, "needs": lambda c: sub_at(c, "Druid", "Circle of Dreams", 10),
                     "text": "Teleport up to 60 ft to an unoccupied space you can see."},
    "tentacle": {"name": "Tentacle of the Deeps", "cost": "bonus", "resource": None, "per": "long", "uses": lambda c: c.proficiency_bonus,
                 "target": "enemy", "range": 60, "needs": lambda c: sub_at(c, "Warlock", "The Fathomless", 1),
                 "text": "Summon a spectral tentacle for 1 minute and strike: a melee spell attack, 1d8 cold (2d8 from 10th level) and -10 ft "
                         "speed. While it lasts, strike again as a bonus action (Tentacle strike)."},
    "tentacle_strike": {"name": "Tentacle strike", "cost": "bonus", "resource": None, "target": "enemy", "range": 60, "when": "tentacle",
                        "needs": lambda c: sub_at(c, "Warlock", "The Fathomless", 1),
                        "text": "Your tentacle of the deeps strikes again: 1d8 cold (2d8 from 10th level), -10 ft speed."},
    "elemental_gift": {"name": "Elemental Gift: flight", "cost": "bonus", "resource": None, "per": "long", "uses": lambda c: c.proficiency_bonus,
                       "target": "self", "needs": lambda c: sub_at(c, "Warlock", "The Genie", 6),
                       "text": "A flying speed of 30 ft for 10 minutes."},
    "corona_of_light": {"name": "Corona of Light", "cost": "action", "resource": None, "target": "self",
                        "needs": lambda c: sub_at(c, "Cleric", "Light Domain", 17),
                        "text": "For 1 minute: foes within 60 ft have disadvantage on saves against your fire and radiant spells."},
    "steps_of_night": {"name": "Steps of Night", "cost": "bonus", "resource": None, "per": "long", "uses": lambda c: c.proficiency_bonus,
                       "target": "self", "needs": lambda c: sub_at(c, "Cleric", "Twilight Domain", 6),
                       "text": "In dim light or darkness: a flying speed equal to your walking speed for 1 minute."},
    "charm_animals": {"name": "Charm Animals and Plants", "cost": "action", "resource": "Channel Divinity (Cleric)", "target": "none",
                      "needs": lambda c: sub_at(c, "Cleric", "Nature Domain", 2),
                      "text": "Beasts and plants within 30 ft make a Wisdom save or are charmed by you for 1 minute (until they take damage)."},
    "searing_sunburst": {"name": "Searing Sunburst", "cost": "action", "resource": None, "target": "area", "range": 150,
                         "area": {"shape": "sphere", "size": 20, "origin": "point"}, "needs": lambda c: sub_at(c, "Monk", "Way of the Sun Soul", 11),
                         "options": lambda c: [{"value": str(n), "label": f"{n} ki: {2 + 2 * n}d6"} for n in range(0, 4)],
                         "text": "A 20-ft-radius orb of light within 150 ft: Constitution save or 2d6 radiant (+2d6 for each ki spent, up to 3)."},
    "invoke_duplicity": {"name": "Invoke Duplicity", "cost": "action", "resource": "Channel Divinity (Cleric)", "target": "point", "teleport": 30,
                         "needs": lambda c: sub_at(c, "Cleric", "Trickery Domain", 2),
                         "text": "An illusory double on a tile within 30 ft for 1 minute (concentration): advantage on attacks against a "
                                 "creature when both you and the illusion are within 5 ft of it."},
    "move_duplicate": {"name": "Move your duplicate", "cost": "bonus", "resource": None, "target": "point", "when": "duplicate",
                       "needs": lambda c: sub_at(c, "Cleric", "Trickery Domain", 2),
                       "text": "Move the illusion of Invoke Duplicity up to 30 ft."},
    "mantle_of_majesty": {"name": "Mantle of Majesty", "cost": "bonus", "resource": None, "per": "long", "target": "self",
                          "needs": lambda c: sub_at(c, "Bard", "College of Glamour", 6),
                          "text": "For 1 minute (concentration): a Command each turn as a bonus action (Majestic Command); charmed "
                                  "creatures fail the save."},
    "majestic_command": {"name": "Majestic Command", "cost": "bonus", "resource": None, "target": "enemy", "range": 60, "when": "majesty",
                         "needs": lambda c: sub_at(c, "Bard", "College of Glamour", 6),
                         "options": lambda c: [{"value": "grovel", "label": "Grovel (prone)"}, {"value": "halt", "label": "Halt (speed 0)"},
                                               {"value": "flee", "label": "Flee (frightened)"}],
                         "text": "Command a creature within 60 ft: Wisdom save (a charmed one fails) or it obeys on its next turn."},
    "unbreakable_majesty": {"name": "Unbreakable Majesty", "cost": "bonus", "resource": None, "per": "short", "target": "self",
                            "needs": lambda c: sub_at(c, "Bard", "College of Glamour", 14),
                            "text": "For 1 minute: the first time each turn a creature attacks you it makes a Charisma save or the attack "
                                    "fails; on a success it has disadvantage on saves against your spells until your next turn ends."},
    "unwavering_strike": {"name": "Unwavering Mark strike", "cost": "bonus", "resource": None, "per": "long",
                          "uses": lambda c: max(1, c.mod("str")), "target": "enemy", "when": "marked",
                          "needs": lambda c: sub_at(c, "Fighter", "Cavalier", 3),
                          "text": "A marked creature hurt someone else: a weapon attack against it with advantage, + half your fighter level damage."},
    "countercharm": {"name": "Countercharm", "cost": "action", "resource": None, "target": "self", "needs": lambda c: _lvl(c, "Bard") >= 6,
                     "text": "Until the end of your next turn, you and allies within 30 ft have advantage on saves against being frightened or charmed."},
    "cloak_of_flies": {"name": "Cloak of Flies", "cost": "bonus", "resource": None, "per": "short", "target": "self",
                       "needs": lambda c: c.has_option("Cloak of Flies"),
                       "text": "A 5-ft aura of buzzing flies until you're incapacitated or dismiss it: a creature starting its turn in it takes "
                               "poison damage equal to your Charisma modifier."},
    "hill_rune": {"name": "Hill Rune", "cost": "bonus", "resource": None, "per": "short", "target": "self", "needs": lambda c: c.has_option("Hill Rune"),
                  "text": "For 1 minute: resistance to bludgeoning, piercing and slashing damage."},
    "frost_rune": {"name": "Frost Rune", "cost": "bonus", "resource": None, "per": "short", "target": "self", "needs": lambda c: c.has_option("Frost Rune"),
                   "text": "For 10 minutes: +2 to Strength and Constitution checks and saves."},
    "storm_rune": {"name": "Storm Rune", "cost": "bonus", "resource": None, "per": "short", "target": "self", "needs": lambda c: c.has_option("Storm Rune"),
                   "text": "For 1 minute: as a reaction, give advantage or disadvantage to an attack or save you see within 60 ft."},
    "ki_fueled_attack": {"name": "Ki-Fueled Attack", "cost": "bonus", "resource": None, "target": "enemy", "range": 5, "when": "ki_action",
                         "needs": lambda c: _lvl(c, "Monk") >= 3 and _has(c, "Ki-Fueled Attack"),
                         "text": "After spending ki as part of your action: one unarmed strike (or monk weapon attack) as a bonus action."},
    "divine_sense": {"name": "Divine Sense", "cost": "action", "resource": "Divine Sense", "target": "self", "needs": lambda c: _lvl(c, "Paladin") >= 1,
                     "text": "Until the end of your next turn you know where every celestial, fiend and undead within 60 ft is (not behind total cover)."},
    "divine_intervention": {"name": "Divine Intervention", "cost": "action", "resource": "Divine Intervention", "target": "none",
                            "needs": lambda c: _lvl(c, "Cleric") >= 10,
                            "text": "Implore your deity: on a d100 roll up to your cleric level (always at 20th) it intervenes - the DM decides how."},
    "chef_treat": {"name": "Chef's treat", "cost": "bonus", "resource": None, "per": "long", "uses": lambda c: c.proficiency_bonus,
                   "target": "self", "needs": lambda c: "Chef" in (c.d.get("feats") or []),
                   "text": "Eat one of your special treats: temporary hit points equal to your proficiency bonus."},
    "grappling_strike": {"name": "Grappling Strike", "cost": "bonus", "resource": "Superiority Dice", "target": "enemy", "range": 5,
                         "when": "attacked", "needs": lambda c: c.has_option("Grappling Strike"),
                         "text": "After a melee hit in the Attack action: grapple the creature, adding the superiority die to your Athletics."},
    "bait_and_switch": {"name": "Bait and Switch", "cost": "free", "resource": "Superiority Dice", "target": "ally", "range": 5,
                        "needs": lambda c: c.has_option("Bait and Switch"),
                        "text": "Swap places with a willing creature within 5 ft (5 ft of movement); one of you gains the superiority die "
                                "to AC until the start of your next turn."},
    "maddening_hex": {"name": "Maddening Hex", "cost": "bonus", "resource": None, "target": "enemy", "range": 30,
                      "needs": lambda c: c.has_option("Maddening Hex"),
                      "text": "A creature you cursed (Hex, Hexblade's Curse) and foes within 5 ft of it take psychic damage equal to your "
                              "Charisma modifier."},
    "relentless_hex": {"name": "Relentless Hex", "cost": "bonus", "resource": None, "target": "point", "teleport": 30,
                       "needs": lambda c: c.has_option("Relentless Hex"),
                       "text": "Teleport up to 30 ft to a space within 30 ft of a creature you cursed (Hex, Hexblade's Curse)."},
    "kensei_shot": {"name": "Kensei's Shot", "cost": "bonus", "resource": "Ki Points", "target": "self",
                    "needs": lambda c: sub_at(c, "Monk", "Way of the Kensei", 3),
                    "text": "Spend 1 ki: your ranged weapon hits deal 1d4 more damage this turn."},
    "quick_toss": {"name": "Quick Toss", "cost": "bonus", "resource": "Superiority Dice", "target": "enemy",
                   "needs": lambda c: c.has_option("Quick Toss"),
                   "text": "Draw and throw a thrown weapon as a bonus action; a hit adds the superiority die to its damage."},
    "hypnotic_gaze": {"name": "Hypnotic Gaze", "cost": "action", "resource": None, "target": "enemy", "range": 5,
                      "needs": lambda c: sub_at(c, "Wizard", "School of Enchantment", 2),
                      "text": "A creature within 5 ft that can see or hear you makes a Wisdom save or is charmed and incapacitated (speed 0) "
                              "until the end of your next turn."},
    "battle_magic": {"name": "Battle Magic attack", "cost": "bonus", "resource": None, "target": "enemy", "when": "spell",
                     "needs": lambda c: sub_at(c, "Bard", "College of Valor", 14),
                     "text": "After casting a bard spell with your action: one weapon attack as a bonus action."},
    "balm_of_peace": {"name": "Balm of Peace", "cost": "action", "resource": "Channel Divinity (Cleric)", "target": "none",
                      "needs": lambda c: sub_at(c, "Cleric", "Peace Domain", 2),
                      "text": "Move without provoking and heal each creature you pass within 5 ft: 2d6 + Wisdom modifier (here: allies within 5 ft)."},
    "storm_aura": {"name": "Storm Aura", "cost": "bonus", "resource": None, "target": "enemy", "range": 10, "when": "raging",
                   "needs": lambda c: sub_at(c, "Barbarian", "Path of the Storm Herald", 3),
                   "text": "While raging, your 10-ft aura: Desert - every other creature in it takes fire damage; Sea - the target makes a Dex "
                           "save against lightning damage; Tundra - your allies in it gain temporary hit points."},
    "rally": {"name": "Rally", "cost": "bonus", "resource": "Superiority Dice", "target": "ally", "range": 60,
              "needs": lambda c: c.has_option("Rally"),
              "text": "An ally who can hear you gains temporary hit points: your superiority die + Charisma modifier."},
    "commanders_strike": {"name": "Commander's Strike", "cost": "attack", "resource": "Superiority Dice", "target": "ally", "range": 120,
                          "needs": lambda c: c.has_option("Commander's Strike"),
                          "text": "Give up one attack and a bonus action: an ally uses its reaction to make a weapon attack (+ your superiority "
                                  "die to its damage) against the nearest foe in its reach."},
    "fighting_spirit": {"name": "Fighting Spirit", "cost": "bonus", "resource": None, "per": "long", "uses": 3, "target": "self",
                        "needs": lambda c: sub_at(c, "Fighter", "Samurai", 3),
                        "text": "Advantage on your weapon attacks this turn and 5 temporary hit points (10 at 10th level, 15 at 15th)."},
    "giants_might": {"name": "Giant's Might", "cost": "bonus", "resource": None, "per": "long", "uses": lambda c: c.proficiency_bonus, "target": "self",
                     "needs": lambda c: sub_at(c, "Fighter", "Rune Knight", 3),
                     "text": "For a minute: advantage on Strength checks and saves, and once on each turn a weapon hit deals 1d6 more "
                             "(1d8 at 10th level, 1d10 at 18th)."},
    "war_magic": {"name": "War Magic attack", "cost": "bonus", "resource": None, "target": "enemy", "when": "cantrip",
                  "needs": lambda c: sub_at(c, "Fighter", "Eldritch Knight", 7),
                  "text": "After casting a cantrip with your action: one weapon attack as a bonus action."},
    "favored_foe": {"name": "Favored Foe", "cost": "free", "resource": None, "per": "long", "uses": lambda c: c.proficiency_bonus, "target": "enemy",
                    "needs": lambda c: _lvl(c, "Ranger") >= 1 and _has(c, "Favored Foe"),
                    "text": "Mark a creature (concentration, 1 minute): the first time you hit it on each of your turns it takes 1d4 more "
                            "(1d6 at 6th level, 1d8 at 14th)."},
    "slayers_prey": {"name": "Slayer's Prey", "cost": "bonus", "resource": None, "target": "enemy", "range": 60,
                     "needs": lambda c: sub_at(c, "Ranger", "Monster Slayer", 3),
                     "text": "Mark a creature within 60 ft: the first time each turn you hit it with a weapon it takes 1d6 more."},
    "planar_warrior": {"name": "Planar Warrior", "cost": "bonus", "resource": None, "target": "enemy", "range": 30,
                       "needs": lambda c: sub_at(c, "Ranger", "Horizon Walker", 3),
                       "text": "Your next weapon hit on a creature within 30 ft this turn deals 1d8 more force damage (2d8 at 11th level)."},
    "horde_breaker": {"name": "Horde Breaker", "cost": "free", "resource": None, "target": "enemy", "when": "attacked",
                      "needs": lambda c: sub_at(c, "Ranger", "Hunter", 3) and choice(c, "hunters_prey") == "Horde Breaker",
                      "text": "Once on each of your turns: another weapon attack against a different creature within 5 ft of the first one."},
    "dread_ambusher": {"name": "Dread Ambusher attack", "cost": "free", "resource": None, "target": "enemy", "when": "attacked",
                       "needs": lambda c: sub_at(c, "Ranger", "Gloom Stalker", 3),
                       "text": "Your first turn of the battle: one more weapon attack with the Attack action (its first hit deals 1d8 more)."},
    "whirlwind_attack": {"name": "Whirlwind Attack", "cost": "action", "resource": None, "target": "none",
                         "needs": lambda c: sub_at(c, "Ranger", "Hunter", 11) and choice(c, "hunter_multiattack") == "Whirlwind Attack",
                         "text": "A melee weapon attack against every foe within 5 ft, each with its own attack roll."},
    "volley": {"name": "Volley", "cost": "action", "resource": None, "target": "enemy",
               "needs": lambda c: sub_at(c, "Ranger", "Hunter", 11) and choice(c, "hunter_multiattack") == "Volley",
               "text": "A ranged weapon attack against the target and every other foe within 10 ft of it, each with its own attack roll."},
    "hexblades_curse": {"name": "Hexblade's Curse", "cost": "bonus", "resource": None, "per": "short", "target": "enemy", "range": 30,
                        "needs": lambda c: sub_at(c, "Warlock", "The Hexblade", 1),
                        "text": "Curse a creature within 30 ft for 1 minute: + proficiency bonus to your damage against it, critical hits on "
                                "19 or 20, and you regain hit points when it dies."},
    "fey_presence": {"name": "Fey Presence", "cost": "action", "resource": None, "per": "short", "target": "none",
                     "needs": lambda c: sub_at(c, "Warlock", "The Archfey", 1),
                     "options": lambda c: [{"value": "charmed", "label": "Charmed"}, {"value": "frightened", "label": "Frightened"}],
                     "text": "Each foe within 10 ft makes a Wisdom save or is charmed or frightened (your choice) until the end of your next turn."},
    "healing_light": {"name": "Healing Light", "cost": "bonus", "resource": None, "per": "long", "uses": lambda c: 1 + _lvl(c, "Warlock"),
                      "target": "ally", "range": 60, "needs": lambda c: sub_at(c, "Warlock", "The Celestial", 1),
                      "options": lambda c: [{"value": str(n), "label": f"{n}d6"} for n in range(1, max(1, c.mod("cha")) + 1)],
                      "text": "Spend d6s from your pool (1 + warlock level): a creature within 60 ft regains that many d6 in hit points "
                              "(at most your Charisma modifier dice at once)."},
    "tides_of_chaos": {"name": "Tides of Chaos", "cost": "free", "resource": None, "per": "long", "target": "self",
                       "needs": lambda c: sub_at(c, "Sorcerer", "Wild Magic", 1), "text": "Advantage on your next attack roll or saving throw."},
    "flexible_casting": {"name": "Flexible Casting", "cost": "bonus", "resource": None, "target": "self", "needs": lambda c: _lvl(c, "Sorcerer") >= 2,
                         "options": lambda c: flexible_options(c),
                         "text": "Turn sorcery points into a spell slot (2/3/5/6/7 points for levels 1-5), or a spell slot into sorcery points."},
    "unsettling_words": {"name": "Unsettling Words", "cost": "bonus", "resource": "Bardic Inspiration", "target": "enemy", "range": 60,
                         "needs": lambda c: sub_at(c, "Bard", "College of Eloquence", 3),
                         "text": "A creature within 60 ft subtracts a roll of your Bardic Inspiration die from its next saving throw before your next turn."},
    "mantle_of_inspiration": {"name": "Mantle of Inspiration", "cost": "bonus", "resource": "Bardic Inspiration", "target": "none",
                              "needs": lambda c: sub_at(c, "Bard", "College of Glamour", 3),
                              "text": "Up to your Charisma modifier allies within 60 ft gain 5 temporary hit points (8 at 5th level, 11 at 10th, 14 at 15th)."},
    "symbiotic_entity": {"name": "Symbiotic Entity", "cost": "action", "resource": "Wild Shape", "target": "self",
                         "needs": lambda c: sub_at(c, "Druid", "Circle of Spores", 2),
                         "text": "Spend a Wild Shape: 4 temporary hit points per druid level; while they last your Halo of Spores dice double "
                                 "and your melee weapon hits deal 1d6 more necrotic damage (10 minutes)."},
    "starry_form": {"name": "Starry Form", "cost": "bonus", "resource": "Wild Shape", "target": "self",
                    "needs": lambda c: sub_at(c, "Druid", "Circle of Stars", 2),
                    "options": lambda c: [{"value": "archer", "label": "Archer"}, {"value": "chalice", "label": "Chalice"},
                                          {"value": "dragon", "label": "Dragon"}],
                    "text": "Spend a Wild Shape: a starry form for 10 minutes. Archer: a luminous arrow (1d8 + Wisdom radiant) as a bonus action; "
                            "Chalice: your healing spells heal someone near for 1d8 + Wisdom more; Dragon: concentration saves of 9 or lower count as 10."},
    "luminous_arrow": {"name": "Luminous Arrow", "cost": "bonus", "resource": None, "target": "enemy", "range": 60, "when": "starry",
                       "needs": lambda c: sub_at(c, "Druid", "Circle of Stars", 2),
                       "text": "Starry Form (Archer): a ranged spell attack within 60 ft, 1d8 + Wisdom radiant (2d8 from 10th level)."},
    "hidden_step": {"name": "Hidden Step", "cost": "bonus", "resource": None, "per": lambda c: "long" if mpmm(c) else "short",
                    "uses": lambda c: c.proficiency_bonus if mpmm(c) else 1, "target": "self", "needs": lambda c: _has(c, "Hidden Step"),
                    "text": "Turn invisible until the start of your next turn or until you attack or cast a spell."},
    "shifting": {"name": "Shifting", "cost": "bonus", "resource": None, "per": lambda c: "long" if mpmm(c) else "short",
                 "uses": lambda c: c.proficiency_bonus if mpmm(c) else 1, "target": "self", "needs": lambda c: _has(c, "Shifting"),
                 "text": "Shift for a minute: temporary hit points (2 x proficiency bonus, or level + Constitution modifier)."},
    "adrenaline_rush": {"name": "Adrenaline Rush", "cost": "bonus", "resource": None, "per": "long", "uses": lambda c: c.proficiency_bonus,
                        "target": "self", "needs": lambda c: _has(c, "Adrenaline Rush"),
                        "text": "Dash as a bonus action and gain temporary hit points equal to your proficiency bonus."},
    "hungry_jaws": {"name": "Hungry Jaws", "cost": "bonus", "resource": None, "per": lambda c: "long" if mpmm(c) else "short",
                    "uses": lambda c: c.proficiency_bonus if mpmm(c) else 1, "target": "enemy", "range": 5, "needs": lambda c: _has(c, "Hungry Jaws"),
                    "text": "A bite attack (1d6 + Strength piercing); a hit gives you temporary hit points."},
    "celestial_revelation": {"name": "Celestial Revelation", "cost": "bonus", "resource": None, "per": "long", "target": "self",
                             "needs": lambda c: c.total_level >= 3 and revelation_kinds(c) != [],
                             "options": lambda c: [{"value": k, "label": k} for k in revelation_kinds(c)],
                             "text": "Transform for a minute: once on each of your turns, extra radiant (or necrotic) damage equal to your "
                                     "proficiency bonus (your level for older aasimar) when you deal damage with an attack."},
    "destructive_wrath": {"name": "Destructive Wrath", "cost": "free", "resource": "Channel Divinity (Cleric)", "target": "self",
                          "needs": lambda c: sub_at(c, "Cleric", "Tempest Domain", 2),
                          "text": "Your next lightning or thunder spell deals its maximum damage instead of rolling."},
    "inspiring_smite": {"name": "Inspiring Smite", "cost": "bonus", "resource": "Channel Divinity (Paladin)", "target": "none", "when": "attacked",
                        "needs": lambda c: sub_at(c, "Paladin", "Oath of Glory", 3),
                        "text": "After your Divine Smite: 2d8 + paladin level temporary hit points shared among creatures of your choice within 30 ft."},
    "watchers_will": {"name": "Watcher's Will", "cost": "action", "resource": "Channel Divinity (Paladin)", "target": "none",
                      "needs": lambda c: sub_at(c, "Paladin", "Oath of the Watchers", 3),
                      "text": "You and up to your Charisma modifier allies within 30 ft have advantage on Intelligence, Wisdom and Charisma saves for 1 minute."},
    "abjure_extraplanar": {"name": "Abjure the Extraplanar", "cost": "action", "resource": "Channel Divinity (Paladin)", "target": "none",
                           "needs": lambda c: sub_at(c, "Paladin", "Oath of the Watchers", 3),
                           "text": "Aberrations, celestials, elementals, fey and fiends within 30 ft make a Wisdom save or are turned for 1 minute."},
    "insightful_fighting": {"name": "Insightful Fighting", "cost": "bonus", "resource": None, "target": "enemy",
                            "needs": lambda c: sub_at(c, "Rogue", "Inquisitive", 3),
                            "text": "Your Insight against the creature's Deception: on a win, Sneak Attack works against it without advantage for 1 minute."},
    "psychic_blade": {"name": "Psychic Blade", "cost": "attack", "resource": None, "target": "enemy", "range": 60,
                      "needs": lambda c: sub_at(c, "Rogue", "Soulknife", 3),
                      "text": "A blade of psychic energy: melee or thrown (60 ft), 1d6 + Dexterity psychic, finesse (Sneak Attack)."},
    "psychic_blade_bonus": {"name": "Psychic Blade (bonus)", "cost": "bonus", "resource": None, "target": "enemy", "range": 60, "when": "attacked",
                            "needs": lambda c: sub_at(c, "Rogue", "Soulknife", 3),
                            "text": "After the Attack action: a second psychic blade as a bonus action, 1d4 + Dexterity psychic."},
    "shell_defense": {"name": "Shell Defense", "cost": "action", "resource": None, "target": "self", "needs": lambda c: _has(c, "Shell Defense"),
                      "text": "Withdraw into your shell: +4 AC, advantage on Strength and Constitution saves, prone and speed 0 until you come out "
                              "(Leave it: end the effect, a bonus action)."},
    "chromatic_warding": {"name": "Chromatic Warding", "cost": "action", "resource": None, "per": "long", "target": "self",
                          "needs": lambda c: c.total_level >= 5 and _has(c, "Chromatic Warding"),
                          "text": "For 1 minute you are immune to your draconic ancestry's damage type."},
    "spirit_totem": {"name": "Spirit Totem (Bear)", "cost": "bonus", "resource": None, "per": "short", "target": "self",
                     "needs": lambda c: sub_at(c, "Druid", "Circle of the Shepherd", 2),
                     "text": "A bear spirit for 1 minute: you and allies within 30 ft gain 5 + druid level temporary hit points and advantage on "
                             "Strength checks and saves while in the aura."},
    "balm_of_summer": {"name": "Balm of the Summer Court", "cost": "bonus", "resource": None, "per": "long", "uses": lambda c: _lvl(c, "Druid"),
                       "target": "ally", "range": 120, "needs": lambda c: sub_at(c, "Druid", "Circle of Dreams", 2),
                       "options": lambda c: [{"value": str(n), "label": f"{n}d6"} for n in range(1, max(1, _lvl(c, "Druid") // 2) + 1)],
                       "text": "Spend d6s from your pool (druid level): a creature within 120 ft regains that many d6 in hit points and gains "
                               "1 temporary hit point per die (at most half your druid level dice at once)."},
    "dragon_wings": {"name": "Dragon Wings", "cost": "bonus", "resource": None, "target": "self",
                     "needs": lambda c: sub_at(c, "Sorcerer", "Draconic Bloodline", 14),
                     "text": "Sprout dragon wings: a flying speed equal to your walking speed."},
    "natures_veil": {"name": "Nature's Veil", "cost": "bonus", "resource": None, "per": "long", "uses": lambda c: c.proficiency_bonus,
                     "target": "self", "needs": lambda c: _lvl(c, "Ranger") >= 10 and _has(c, "Nature's Veil"),
                     "text": "Become invisible until the start of your next turn."},
    "dragon_fear": {"name": "Dragon Fear", "cost": "action", "resource": None, "per": "short", "target": "none",
                    "needs": lambda c: "Dragon Fear" in (c.d.get("feats") or []) and breath(c) is not None,
                    "text": "Instead of your breath weapon: each creature of your choice within 30 ft makes a Wisdom save or is frightened for 1 minute."},
    "zealous_presence": {"name": "Zealous Presence", "cost": "bonus", "resource": None, "per": "long", "target": "none",
                         "needs": lambda c: sub_at(c, "Barbarian", "Path of the Zealot", 10),
                         "text": "Up to ten allies within 60 ft have advantage on attack rolls and saving throws until the start of your next turn."},
    "beast_bite": {"name": "Form of the Beast: Bite", "cost": "attack", "resource": None, "target": "enemy", "range": 5, "when": "raging",
                   "needs": lambda c: sub_at(c, "Barbarian", "Path of the Beast", 3),
                   "text": "While raging: a bite, 1d8 + Strength piercing; once a turn, below half your hit points, a hit heals you your proficiency bonus."},
    "beast_claws": {"name": "Form of the Beast: Claws", "cost": "attack", "resource": None, "target": "enemy", "range": 5, "when": "raging",
                    "needs": lambda c: sub_at(c, "Barbarian", "Path of the Beast", 3),
                    "text": "While raging: a claw, 1d6 + Strength slashing; once a turn the Attack action gets one more claw attack."},
    "beast_tail": {"name": "Form of the Beast: Tail", "cost": "attack", "resource": None, "target": "enemy", "range": 10, "when": "raging",
                   "needs": lambda c: sub_at(c, "Barbarian", "Path of the Beast", 3),
                   "text": "While raging: a tail with reach 10 ft, 1d8 + Strength piercing."},
    "otherworldly_wings": {"name": "Otherworldly Wings", "cost": "bonus", "resource": None, "target": "self",
                           "needs": lambda c: sub_at(c, "Sorcerer", "Divine Soul", 14), "text": "Spectral wings: a flying speed of 30 ft."},
    "thunder_gauntlets": {"name": "Thunder Gauntlets", "cost": "attack", "resource": None, "target": "enemy", "range": 5,
                          "needs": lambda c: sub_at(c, "Artificer", "Armorer", 3) and choice(c, "armor_model") == "Guardian",
                          "text": "Armorer (Guardian): 1d8 + Intelligence thunder; a creature hit has disadvantage on attacks against anyone "
                                  "but you until the start of your next turn."},
    "lightning_launcher": {"name": "Lightning Launcher", "cost": "attack", "resource": None, "target": "enemy", "range": 300,
                           "needs": lambda c: sub_at(c, "Artificer", "Armorer", 3) and choice(c, "armor_model") == "Infiltrator",
                           "text": "Armorer (Infiltrator): a ranged attack (90/300 ft), 1d6 + Intelligence lightning; once a turn a hit deals 1d6 more."},
    "defensive_field": {"name": "Defensive Field", "cost": "bonus", "resource": None, "per": "long", "uses": lambda c: c.proficiency_bonus,
                        "target": "self", "needs": lambda c: sub_at(c, "Artificer", "Armorer", 3) and choice(c, "armor_model") == "Guardian",
                        "text": "Temporary hit points equal to your artificer level."},
    "draconic_cry": {"name": "Draconic Cry", "cost": "bonus", "resource": None, "per": "long", "uses": lambda c: c.proficiency_bonus,
                     "target": "none", "needs": lambda c: _has(c, "Draconic Cry"),
                     "text": "Foes within 10 ft: you and your allies have advantage on attacks against them until the start of your next turn."},
}


CAPSTONES = {"Oath of Devotion": "Holy Nimbus", "Oath of Vengeance": "Avenging Angel", "Oath of the Ancients": "Elder Champion",
             "Oath of Conquest": "Invincible Conqueror", "Oath of Glory": "Living Legend"}


def companions(char) -> List[str]:
    """The class companions (bestiary ids) the character can call: a beast master's primal beast, a battle smith's steel
    defender, a drakewarden's drake, an artificer's homunculus."""
    out = []
    if sub_at(char, "Ranger", "Beast Master", 3):
        out += ["Beast of the Land|TCE", "Beast of the Sea|TCE", "Beast of the Sky|TCE"]
    if sub_at(char, "Ranger", "Drakewarden", 3):
        out.append("Drake Companion|FTD")
    if sub_at(char, "Artificer", "Battle Smith", 3):
        out.append("Steel Defender|TCE")
    if char.has_option("Homunculus Servant"):
        out.append("Homunculus Servant|TCE")
    if sub_at(char, "Artificer", "Reanimator", 3):
        out.append("Reanimated Companion|RHW")
    return out


def harness_options(char) -> List[dict]:
    """Harness Divine Power: the expended slots it can bring back (up to half the proficiency bonus, rounded up)."""
    cap = (char.proficiency_bonus + 1) // 2
    used = char.d.get("slots_used") or {}
    return [{"value": str(n), "label": f"Level {n} slot"} for n in range(1, cap + 1) if int(used.get(str(n)) or 0) > 0]


FLEX_COST = {1: 2, 2: 3, 3: 5, 4: 6, 5: 7}                    # sorcery points for a spell slot (PHB Flexible Casting)


def flexible_options(char) -> List[dict]:
    from ...rules import spellcasting as SC
    out = []
    used = char.d.get("slots_used") or {}
    for n, cost in FLEX_COST.items():
        if int(used.get(str(n)) or 0) > 0:
            out.append({"value": f"slot:{n}", "label": f"Level {n} slot for {cost} sorcery points"})
    left = SC.slots_remaining(char)
    for k in sorted((k for k in left if k != SC.PACT_KEY and left[k] > 0), key=int):
        out.append({"value": f"points:{k}", "label": f"Level {k} slot into {k} sorcery points"})
    return out


def revelation_kinds(char) -> List[str]:
    """An aasimar's transformations: the MPMM choice of three, or the older subrace's one."""
    if not (char.d.get("race") or "").startswith("Aasimar"):
        return []
    if _has(char, "Celestial Revelation"):
        text = next((t["text"] for t in (char.race_data() or {}).get("traits") or [] if t["name"] == "Celestial Revelation"), "")
        named = [n for n in ("Heavenly Wings", "Inner Radiance", "Radiant Soul", "Radiant Consumption", "Necrotic Shroud") if n in text]
        return named or ["Heavenly Wings", "Inner Radiance", "Necrotic Shroud"]      # (the book's own names; the sheet's text may use the older ones)
    return [n for n in ("Radiant Soul", "Radiant Consumption", "Necrotic Shroud") if _has(char, n)]


def per_of(f: dict, char) -> Optional[str]:
    p = f.get("per")
    return p(char) if callable(p) else p


def per_key(f: dict, char) -> str:
    """Where a per-rest feature counts its uses in the character's resources (a short rest clears 'short:...')."""
    return f"{'short' if per_of(f, char) == 'short' else 'feature'}:{f.get('per_name') or f['name']}"      # per_name: one pool for two items


def per_left(f: dict, char) -> Optional[int]:
    """Uses left until the rest (None: the feature has no per-rest limit)."""
    if not per_of(f, char):
        return None
    u = f.get("uses")
    top = int(u(char)) if callable(u) else int(u or 1)
    return max(0, top - int(char.d["resources"].get(per_key(f, char)) or 0))


def available(char) -> List[str]:
    return [k for k, f in ACTIVE.items() if not f.get("passive") and _safe(f["needs"], char)]


def _safe(fn, char) -> bool:
    try:
        return bool(fn(char))
    except Exception:  # noqa: BLE001 - a feature check must never break the action list
        return False


def _ftd_breath(char) -> bool:
    """A Fizban's dragonborn (chromatic, gem, metallic): the breath weapon is used proficiency bonus times, back after a long rest."""
    race = rules.races.get(char.race) if char.race else None
    anc = next((a for a in (race or {}).get("ancestries") or [] if a["name"] == char.ancestry), None) if race else None
    return bool(anc) and anc.get("dice") == "ftd"


def breath(char) -> Optional[dict]:
    """The dragonborn breath weapon: {'type', 'area': {...}, 'save', 'dice'}."""
    race = rules.races.get(char.race) if char.race else None
    anc = next((a for a in (race or {}).get("ancestries") or [] if a["name"] == char.ancestry), None) if race else None
    if not anc:
        return None
    area = (anc.get("area") or "5 by 30 ft. line").lower()
    m = re.search(r"(\d+)\s*ft\.?\s*cone", area)
    shape = {"shape": "cone", "size": int(m.group(1)), "origin": "caster"} if m else {"shape": "line", "size": 30, "width": 5, "origin": "caster"}
    lv = char.total_level
    if anc.get("dice") == "ftd":                       # Fizban's: 1d10, more at 5th, 11th and 17th level
        dice = "4d10" if lv >= 17 else "3d10" if lv >= 11 else "2d10" if lv >= 5 else "1d10"
    else:
        dice = "5d6" if lv >= 16 else "4d6" if lv >= 11 else "3d6" if lv >= 6 else "2d6"
    save = {"dexterity": "dex", "constitution": "con"}.get(str(anc.get("save", "dex")).lower(), str(anc.get("save", "dex"))[:3].lower())
    return {"type": anc["damage"], "area": shape, "save": save, "dice": dice, "dc": 8 + char.mod("con") + char.proficiency_bonus}


# ---------------------------------------------------------------------- more subclass features (subfeats.py plays them)
# 'alt_ki': when the per-rest uses are gone, this many ki points pay for one more use (Breath of the Dragon, Aspect of the Wyrm).
DRAGON_TYPES = ["acid", "cold", "fire", "lightning", "poison"]
ELIXIRS = {1: "Healing", 2: "Swiftness", 3: "Resilience", 4: "Boldness", 5: "Flight", 6: "Transformation"}


def psionic_dice(char) -> int:
    """The Soulknife's pool of Psionic Energy dice: twice the proficiency bonus."""
    return 2 * char.proficiency_bonus


def psionic_die(char) -> str:
    lv = _lvl(char, "Rogue")
    return "d12" if lv >= 17 else "d10" if lv >= 11 else "d8" if lv >= 5 else "d6"


def elixir_count(char) -> int:
    """Experimental elixirs made at the end of a long rest: one, two at 6th level, three at 15th."""
    lv = _lvl(char, "Artificer")
    return 3 if lv >= 15 else 2 if lv >= 6 else 1


def elixir_options(char) -> List[dict]:
    """What Drink / administer an elixir can pick: one made at the rest (rolled as it is drunk) and the flasks made with spell slots."""
    out = []
    used = int(char.d["resources"].get("feature:Experimental Elixir") or 0)
    if used < elixir_count(char):
        out.append({"value": "rest", "label": f"Made at the rest (random; {elixir_count(char) - used} left)"})
    for i, fx in enumerate(char.d.get("elixirs") or []):
        out.append({"value": f"flask:{i}", "label": f"Flask: {fx}"})
    return out


def _new_active() -> dict:
    ek = lambda c: sub_at(c, "Fighter", "Echo Knight", 3)
    dragon = lambda c: sub_at(c, "Monk", "Way of the Ascendant Dragon", 3)
    alch = lambda n: (lambda c: sub_at(c, "Artificer", "Alchemist", n))
    breath_opts = lambda c: [{"value": t, "label": t.capitalize()} for t in DRAGON_TYPES]
    return {
        # ---- Fighter: Echo Knight
        "manifest_echo": {"name": "Manifest Echo", "cost": "bonus", "resource": None, "target": "point", "teleport": 15, "needs": ek,
                          "text": "Manifest an echo of yourself within 15 ft (AC 14 + proficiency bonus, 1 hit point, same size). It moves 30 ft on "
                                  "your turn, you can attack from its space and swap places with it. It is destroyed if it is more than 30 ft from "
                                  "you at the end of your turn."},
        "echo_move": {"name": "Move the echo", "cost": "free", "resource": None, "target": "point", "range": 60, "when": "echo", "needs": ek,
                      "text": "Mentally command the echo to move up to 30 ft from where it stands, once a turn (no action)."},
        "echo_swap": {"name": "Swap places with the echo", "cost": "bonus", "resource": None, "target": "self", "when": "echo", "needs": ek,
                      "text": "Teleport, swapping places with your echo, at a cost of 15 ft of your movement."},
        "echo_attack": {"name": "Attack from the echo", "cost": "attack", "resource": None, "target": "enemy", "when": "echo", "needs": ek,
                        "text": "One attack of the Attack action made from the echo's space instead of yours (your best weapon that reaches)."},
        "unleash_incarnation": {"name": "Unleash Incarnation", "cost": "free", "resource": None, "per": "long", "target": "enemy", "when": "echo",
                                "uses": lambda c: max(1, c.mod("con")), "needs": ek,
                                "text": "With the Attack action: one additional melee attack from the echo's position (Constitution modifier uses)."},
        "echo_dismiss": {"name": "Dismiss the echo", "cost": "bonus", "resource": None, "target": "self", "when": "echo", "needs": ek,
                         "text": "End your echo."},
        # ---- Barbarian: Path of the Giant
        "cleaver_type": {"name": "Elemental Cleaver: change type", "cost": "bonus", "resource": None, "target": "self", "when": "raging",
                         "needs": lambda c: sub_at(c, "Barbarian", "Path of the Giant", 6),
                         "options": lambda c: [{"value": t, "label": t.capitalize()} for t in ELEMENTS],
                         "text": "While raging and holding the infused weapon: change its damage type to acid, cold, fire, lightning or thunder."},
        "mighty_impel": {"name": "Mighty Impel", "cost": "bonus", "resource": None, "target": "point", "range": 30, "when": "raging",
                         "needs": lambda c: sub_at(c, "Barbarian", "Path of the Giant", 10),
                         "text": "While raging, pick a Medium or smaller creature within your reach (Large at 14th level) and move it to an unoccupied "
                                 "space you can see within 30 ft (an unwilling creature: Strength save). Select the creature first, then the tile."},
        # ---- Rogue: Soulknife
        "psychic_teleport": {"name": "Psychic Teleportation", "cost": "bonus", "resource": None, "target": "point", "range": 120,
                             "needs": lambda c: sub_at(c, "Rogue", "Soulknife", 9),
                             "text": "Expend and roll a Psionic Energy die: teleport to an unoccupied space you can see up to 10 ft times the roll away."},
        "psionic_regain": {"name": "Regain a Psionic Energy die", "cost": "bonus", "resource": None, "per": "short", "target": "self",
                           "needs": lambda c: sub_at(c, "Rogue", "Soulknife", 3),
                           "text": "Regain one expended Psionic Energy die (once per short or long rest)."},
        # ---- Monk: Way of the Ascendant Dragon
        "dragon_breath_cone": {"name": "Breath of the Dragon (cone)", "cost": "attack", "resource": None, "per": "long", "alt_ki": 2, "target": "area",
                               "area": {"shape": "cone", "size": 20, "origin": "caster"}, "per_name": "Breath of the Dragon", "uses": lambda c: c.proficiency_bonus, "needs": dragon,
                               "options": breath_opts,
                               "text": "Replace one attack with a 20-ft cone of draconic energy (Dexterity save against your ki DC): two Martial Arts "
                                       "dice, three at 11th level. When the uses are gone, 2 ki pays for one more."},
        "dragon_breath_line": {"name": "Breath of the Dragon (line)", "cost": "attack", "resource": None, "per": "long", "alt_ki": 2, "target": "area",
                               "area": {"shape": "line", "size": 30, "width": 5, "origin": "caster"}, "per_name": "Breath of the Dragon", "uses": lambda c: c.proficiency_bonus,
                               "needs": dragon, "options": breath_opts,
                               "text": "Replace one attack with a 30-ft line of draconic energy (Dexterity save against your ki DC): two Martial Arts "
                                       "dice, three at 11th level. When the uses are gone, 2 ki pays for one more."},
        "wings_unfurled": {"name": "Wings Unfurled", "cost": "free", "resource": None, "per": "long", "target": "self", "when": "step_wind",
                           "uses": lambda c: c.proficiency_bonus, "needs": lambda c: sub_at(c, "Monk", "Way of the Ascendant Dragon", 6),
                           "text": "With Step of the Wind: spectral wings give you a flying speed equal to your walking speed until the end of your turn."},
        "aspect_wyrm": {"name": "Aspect of the Wyrm", "cost": "bonus", "resource": None, "per": "long", "alt_ki": 3, "target": "self",
                        "needs": lambda c: sub_at(c, "Monk", "Way of the Ascendant Dragon", 11),
                        "options": lambda c: [{"value": "fright", "label": "Frightful Presence"}] + [{"value": t, "label": f"Resistance: {t}"} for t in DRAGON_TYPES],
                        "text": "A 10-ft aura for a minute: Frightful Presence (a Wisdom save or frightened) or resistance to a chosen type for you and "
                                "your allies in it. Once per long rest, or 3 ki."},
        "wyrm_fright": {"name": "Frightful Presence (aura)", "cost": "bonus", "resource": None, "target": "enemy", "range": 10, "when": "wyrm",
                        "needs": lambda c: sub_at(c, "Monk", "Way of the Ascendant Dragon", 11),
                        "text": "Your Aspect of the Wyrm: a creature in the aura makes a Wisdom save or is frightened of you."},
        # ---- Artificer: Alchemist
        "elixir_drink": {"name": "Experimental Elixir", "cost": "action", "resource": None, "target": "ally", "range": 5, "needs": alch(3),
                         "options": lambda c: elixir_options(c),
                         "text": "Drink an experimental elixir or administer it to a creature you touch. An elixir made at the rest is rolled on the "
                                 "table (Healing, Swiftness, Resilience, Boldness, Flight, Transformation) as it is drunk."},
        "elixir_make": {"name": "Create an elixir (spell slot)", "cost": "action", "resource": None, "target": "self", "needs": alch(3),
                        "options": lambda c: [{"value": n, "label": n} for n in list(ELIXIRS.values())],
                        "text": "Spend a spell slot of 1st level or higher to create an experimental elixir of the effect you choose in an empty flask."},
        "reagent_lesser": {"name": "Lesser Restoration (Restorative Reagents)", "cost": "action", "resource": None, "per": "long", "target": "ally",
                           "range": 5, "uses": lambda c: max(1, c.mod("int")), "needs": alch(9),
                           "text": "Cast lesser restoration without a slot, using alchemist's supplies (Intelligence modifier uses)."},
        "mastery_greater": {"name": "Greater Restoration (Chemical Mastery)", "cost": "action", "resource": None, "per": "long", "target": "ally",
                            "range": 5, "needs": alch(15), "text": "Cast greater restoration without a slot or components, once per long rest."},
        "mastery_heal": {"name": "Heal (Chemical Mastery)", "cost": "action", "resource": None, "per": "long", "target": "ally", "range": 60,
                         "needs": alch(15), "text": "Cast heal without a slot or components, once per long rest."},
        # ---- Sorcerer: Storm Sorcery
        "tempestuous_magic": {"name": "Tempestuous Magic", "cost": "bonus", "resource": None, "target": "self", "when": "leveled_spell",
                              "needs": lambda c: sub_at(c, "Sorcerer", "Storm Sorcery", 1),
                              "text": "After casting a spell of 1st level or higher: gusts of air let you fly up to 10 ft without provoking opportunity attacks."},
    }


ACTIVE.update(_new_active())
