"""Situational combat feats: the switches a character has on its sheet and next to its actions.

Each feat the character has shows as a toggle. What "on" means depends on the kind:
    power      a choice made for every attack (Great Weapon Master's and Sharpshooter's -5 to hit / +10 damage) - off by default
    auto       a rule the battle applies by itself (Savage Attacker's reroll, Crusher's push...) - on by default; off skips it
    reaction   something the battle offers when it is triggered (Sentinel, Mage Slayer, Lucky...) - on by default;
               off means it is never offered (the reaction's Ask / Always / Never mode decides the rest)
    option     like auto, with a choice (Elemental Adept's damage type)
The state lives on the character (d['toggles']), so it is the same on the editor's sheet, the portal and in every battle.
"""
from typing import Dict, List, Optional

from .data import rules

ELEMENTS = ["acid", "cold", "fire", "lightning", "thunder"]

# key: (feat name, kind, short label, what the battle does with it)
FEATS: Dict[str, dict] = {
    "great_weapon_master": {"feat": "Great Weapon Master", "kind": "power", "label": "GWM −5 / +10",
                            "does": "On: melee attacks with a heavy weapon you're proficient with take -5 to hit and deal +10 damage. "
                                    "Always: a critical hit or a kill with a melee weapon gives a bonus-action weapon attack."},
    "sharpshooter": {"feat": "Sharpshooter", "kind": "power", "label": "Sharpshooter −5 / +10",
                     "does": "On: ranged weapon attacks take -5 to hit and deal +10 damage. Always: no disadvantage at long range, "
                             "half and three-quarters cover are ignored."},
    "sentinel": {"feat": "Sentinel", "kind": "reaction", "label": "Sentinel",
                 "does": "Opportunity attacks you hit drop the target's speed to 0, and Disengage doesn't stop them. When a creature "
                         "within 5 ft of you attacks someone else, you are offered a reaction attack against it."},
    "polearm_master": {"feat": "Polearm Master", "kind": "reaction", "label": "Polearm Master",
                       "does": "After the Attack action with a glaive, halberd, quarterstaff or spear: a bonus-action butt-end attack (1d4). "
                               "You are offered an opportunity attack when a creature enters your reach."},
    "mage_slayer": {"feat": "Mage Slayer", "kind": "reaction", "label": "Mage Slayer",
                    "does": "When a creature within 5 ft casts a spell, you are offered a reaction weapon attack. Creatures you hurt make "
                            "their concentration saves with disadvantage. Advantage on saves against spells cast within 5 ft of you."},
    "war_caster": {"feat": "War Caster", "kind": "reaction", "label": "War Caster",
                   "does": "Advantage on concentration saves. Your opportunity attack can be a damaging cantrip instead of a weapon attack."},
    "lucky": {"feat": "Lucky", "kind": "reaction", "label": "Lucky",
              "does": "3 luck points per long rest. You are offered a reroll when your attack misses, your saving throw fails, "
                      "or an attack hits you."},
    "savage_attacker": {"feat": "Savage Attacker", "kind": "auto", "label": "Savage Attacker",
                        "does": "Once per turn, a melee weapon hit rolls its damage twice and keeps the higher."},
    "crossbow_expert": {"feat": "Crossbow Expert", "kind": "auto", "label": "Crossbow Expert",
                        "does": "No disadvantage on ranged attacks with a foe next to you. After the Attack action: a bonus-action attack "
                                "with a hand crossbow."},
    "shield_master": {"feat": "Shield Master", "kind": "auto", "label": "Shield Master",
                      "does": "After the Attack action, with a shield: a bonus-action shove. +2 to Dexterity saves; a successful Dexterity "
                              "save for half damage takes none (your reaction)."},
    "mobile": {"feat": "Mobile", "kind": "auto", "label": "Mobile",
               "does": "+10 ft speed. Creatures you made a melee attack against this turn don't get opportunity attacks against you."},
    "dual_wielder": {"feat": "Dual Wielder", "kind": "auto", "label": "Dual Wielder",
                     "does": "+1 AC while you hold a melee weapon in each hand; two-weapon fighting with weapons that aren't light."},
    "heavy_armor_master": {"feat": "Heavy Armor Master", "kind": "auto", "label": "Heavy Armor Master",
                           "does": "In heavy armour, bludgeoning, piercing and slashing damage from nonmagical attacks is reduced by 3."},
    "elemental_adept": {"feat": "Elemental Adept", "kind": "option", "label": "Elemental Adept", "options": ELEMENTS,
                        "does": "Your spells ignore resistance to the chosen damage type."},
    "spell_sniper": {"feat": "Spell Sniper", "kind": "auto", "label": "Spell Sniper",
                     "does": "Spells with an attack roll have double range and ignore half and three-quarters cover."},
    "alert": {"feat": "Alert", "kind": "auto", "label": "Alert",
              "does": "+5 initiative; creatures you can't see don't get advantage on attacks against you."},
    "skulker": {"feat": "Skulker", "kind": "auto", "label": "Skulker",
                "does": "Missing with a ranged attack while hidden doesn't reveal you."},
    "grappler": {"feat": "Grappler", "kind": "auto", "label": "Grappler",
                 "does": "Advantage on attacks against a creature you are grappling."},
    "tavern_brawler": {"feat": "Tavern Brawler", "kind": "auto", "label": "Tavern Brawler",
                       "does": "Unarmed strikes deal 1d4. After hitting with an unarmed strike: a bonus-action grapple."},
    "charger": {"feat": "Charger", "kind": "auto", "label": "Charger",
                "does": "After the Dash action: a bonus-action melee weapon attack with +5 damage."},
    "crusher": {"feat": "Crusher", "kind": "auto", "label": "Crusher",
                "does": "Once per turn a bludgeoning hit pushes the target 5 ft. A critical hit gives attacks against it advantage "
                        "until your next turn."},
    "piercer": {"feat": "Piercer", "kind": "auto", "label": "Piercer",
                "does": "Once per turn a piercing hit rerolls its lowest damage die. A critical hit adds one more damage die."},
    "slasher": {"feat": "Slasher", "kind": "auto", "label": "Slasher",
                "does": "Once per turn a slashing hit cuts the target's speed by 10 ft. A critical hit gives it disadvantage on "
                        "attacks until your next turn."},
    "gunner": {"feat": "Gunner", "kind": "auto", "label": "Gunner",
               "does": "No disadvantage on ranged attacks with a foe next to you."},
    "elven_accuracy": {"feat": "Elven Accuracy", "kind": "auto", "label": "Elven Accuracy",
                       "does": "Advantage on an attack using Dexterity, Intelligence, Wisdom or Charisma rolls three dice."},
    "poisoner": {"feat": "Poisoner", "kind": "auto", "label": "Poisoner",
                 "does": "Your damage ignores resistance to poison."},
    "infernal_constitution": {"feat": "Infernal Constitution", "kind": "auto", "label": "Infernal Constitution",
                              "does": "Resistance to cold and poison damage."},
    "squat_nimbleness": {"feat": "Squat Nimbleness", "kind": "auto", "label": "Squat Nimbleness",
                         "does": "Advantage on checks to escape a grapple."},
    "dwarven_fortitude": {"feat": "Dwarven Fortitude", "kind": "auto", "label": "Dwarven Fortitude",
                          "does": "Taking the Dodge action also spends a Hit Die to heal."},
    "healer": {"feat": "Healer", "kind": "auto", "label": "Healer",
               "does": "An action: a healer's kit restores 1d6 + 4 + the creature's Hit Dice (once per creature per rest), or stabilizes."},
    "telekinetic": {"feat": "Telekinetic", "kind": "auto", "label": "Telekinetic",
                    "does": "A bonus action: shove a creature within 30 ft 5 ft (Strength save)."},
    "second_chance": {"feat": "Second Chance", "kind": "reaction", "label": "Second Chance",
                      "does": "When an attack hits you, you are offered to make the attacker reroll (once per short rest)."},
    "fade_away": {"feat": "Fade Away", "kind": "reaction", "label": "Fade Away",
                  "does": "After you take damage, you are offered to turn invisible until the end of your next turn (once per short rest)."},
    "orcish_fury": {"feat": "Orcish Fury", "kind": "reaction", "label": "Orcish Fury",
                    "does": "After a weapon hit you are offered one extra weapon damage die (once per short rest)."},
    "gift_chromatic": {"feat": "Gift of the Chromatic Dragon", "kind": "reaction", "label": "Chromatic Dragon",
                       "does": "Chromatic Infusion: a bonus action that adds 1d4 of an element to a weapon for a minute. Reactive "
                               "Resistance: offered when elemental damage is about to hit you."},
    "gift_metallic": {"feat": "Gift of the Metallic Dragon", "kind": "reaction", "label": "Metallic Dragon",
                      "does": "Protective Wings: offered when an attack would hit you or an ally within 5 ft (+proficiency bonus to AC)."},
    "gift_gem": {"feat": "Gift of the Gem Dragon", "kind": "reaction", "label": "Gem Dragon",
                 "does": "Telekinetic Reprisal: offered when a creature within 10 ft hurts you (2d8 force, Strength save or pushed 10 ft)."},
    "defensive_duelist": {"feat": "Defensive Duelist", "kind": "reaction", "label": "Defensive Duelist",
                          "does": "Offered when a melee attack would hit you: +proficiency bonus to AC with a finesse weapon."},
    "strike_giants": {"feat": "Strike of the Giants", "kind": "option", "label": "Strike of the Giants", "options": ["Cloud", "Fire", "Frost", "Hill", "Stone"],
                      "does": "The giant you took after: once a turn a melee or thrown weapon hit adds Cloud (1d4 thunder, Wis save or you vanish from it), Fire "
                              "(1d10), Frost (1d6 cold, Con save or speed 0), Hill (1d6, Str save or prone) or Stone (1d6 force)."},
    # subclass features that say "choose one" (the sheet lists every option; the battle uses the picked one).
    # 'feature': (class, subclass, level) instead of a feat.
    "hunters_prey": {"feat": "Hunter's Prey", "kind": "option", "label": "Hunter's Prey", "feature": ("Ranger", "Hunter", 3),
                     "options": ["Colossus Slayer", "Giant Killer", "Horde Breaker"],
                     "does": "Colossus Slayer: +1d8 once a turn against a creature below its hit point maximum. Giant Killer: a reaction "
                             "attack on a Large or larger creature that attacks you from 5 ft. Horde Breaker: one more attack a turn on another creature."},
    "defensive_tactics": {"feat": "Defensive Tactics", "kind": "option", "label": "Defensive Tactics", "feature": ("Ranger", "Hunter", 7),
                          "options": ["Escape the Horde", "Multiattack Defense", "Steel Will"],
                          "does": "Escape the Horde: opportunity attacks against you have disadvantage. Multiattack Defense: +4 AC against a "
                                  "creature's later attacks the turn it hits you. Steel Will: advantage on saves against being frightened."},
    "hunter_multiattack": {"feat": "Multiattack", "kind": "option", "label": "Hunter's Multiattack", "feature": ("Ranger", "Hunter", 11),
                           "options": ["Volley", "Whirlwind Attack"],
                           "does": "Volley: a ranged attack on every foe within 10 ft of the target. Whirlwind Attack: a melee attack on every foe within 5 ft."},
    "superior_defense": {"feat": "Superior Hunter's Defense", "kind": "option", "label": "Superior Hunter's Defense",
                         "feature": ("Ranger", "Hunter", 15), "options": ["Evasion", "Stand Against the Tide", "Uncanny Dodge"],
                         "does": "Evasion against area damage, or Uncanny Dodge (a reaction that halves an attack's damage)."},
    "totem_spirit": {"feat": "Totem Spirit", "kind": "option", "label": "Totem Spirit", "feature": ("Barbarian", "Path of the Totem Warrior", 3),
                     "options": ["Bear", "Eagle", "Elk", "Tiger", "Wolf"],
                     "does": "While raging - Bear: resistance to all damage but psychic. Eagle: opportunity attacks against you have "
                             "disadvantage, Dash as a bonus action. Elk: +15 ft speed. Wolf: allies have advantage on melee attacks "
                             "against foes within 5 ft of you."},
    "totem_attunement": {"feat": "Totemic Attunement", "kind": "option", "label": "Totemic Attunement",
                         "feature": ("Barbarian", "Path of the Totem Warrior", 14), "options": ["Bear", "Eagle", "Elk", "Tiger", "Wolf"],
                         "does": "Bear: while you rage, foes within 5 ft of you have disadvantage on attacks against anyone else."},
    "divine_fury": {"feat": "Divine Fury", "kind": "option", "label": "Divine Fury", "feature": ("Barbarian", "Path of the Zealot", 3),
                    "options": ["radiant", "necrotic"],
                    "does": "While raging, the first weapon hit on each of your turns deals 1d6 + half your barbarian level more of this type."},
    "genie_kind": {"feat": "Genie Kind", "kind": "option", "label": "Genie patron", "feature": ("Warlock", "The Genie", 1),
                   "options": ["Dao", "Djinni", "Efreeti", "Marid"],
                   "does": "Genie's Wrath: once on each of your turns an attack hit deals + proficiency bonus damage (Dao bludgeoning, "
                           "Djinni thunder, Efreeti fire, Marid cold)."},
    "gathered_swarm": {"feat": "Gathered Swarm", "kind": "option", "label": "Gathered Swarm", "feature": ("Ranger", "Swarmkeeper", 3),
                       "options": ["Damage", "Push 15 ft", "Move 5 ft"],
                       "does": "Once on each of your turns a hit also: Damage - 1d6 piercing (1d8 at 11th level); Push 15 ft - the target makes a "
                               "Strength save or is pushed 15 ft (and knocked prone at 11th level); Move 5 ft - you move 5 ft without provoking."},
    "dragon_ancestor": {"feat": "Dragon Ancestor", "kind": "option", "label": "Dragon ancestor", "feature": ("Sorcerer", "Draconic Bloodline", 1),
                        "options": ["Black", "Blue", "Brass", "Bronze", "Copper", "Gold", "Green", "Red", "Silver", "White"],
                        "does": "Your draconic ancestor: the damage type of Elemental Affinity (Black and Copper acid, Blue and Bronze lightning, Brass, Gold and "
                                "Red fire, Green poison, Silver and White cold)."},
    "lunar_phase": {"feat": "Lunar Embodiment", "kind": "option", "label": "Lunar phase", "feature": ("Sorcerer", "Lunar Sorcery", 1),
                    "options": ["Full Moon", "New Moon", "Crescent Moon"],
                    "does": "The phase chosen after your last long rest (Lunar Empowerment and Lunar Phenomenon follow it; Waxing and Waning changes it)."},
    "drake_essence": {"feat": "Draconic Essence", "kind": "option", "label": "Draconic Essence", "feature": ("Ranger", "Drakewarden", 3),
                      "options": ["fire", "cold", "lightning", "acid", "poison"],
                      "does": "The damage type of your drake: its immunity and (at 7th level) its Magic Fang and your own resistance."},
    "storm_aura": {"feat": "Storm Aura", "kind": "option", "label": "Storm Aura", "feature": ("Barbarian", "Path of the Storm Herald", 3),
                   "options": ["Desert", "Sea", "Tundra"],
                   "does": "The environment of your storm aura: Desert (fire), Sea (lightning), Tundra (cold); Storm Soul's resistance follows it."},
    "cleaver_element": {"feat": "Elemental Cleaver", "kind": "option", "label": "Elemental Cleaver", "feature": ("Barbarian", "Path of the Giant", 6),
                        "options": ["fire", "cold", "lightning", "thunder", "acid"],
                        "does": "The damage type your rage infuses the weapon in your hand with (a bonus action changes it while you rage)."},
    "colossus_size": {"feat": "Demiurgic Colossus", "kind": "option", "label": "Demiurgic Colossus", "feature": ("Barbarian", "Path of the Giant", 14),
                      "options": ["Large", "Huge"],
                      "does": "The size Giant Stature makes you while you rage: Large or Huge."},
    "draconic_strike": {"feat": "Draconic Disciple", "kind": "option", "label": "Draconic Strike", "feature": ("Monk", "Way of the Ascendant Dragon", 3),
                        "options": ["bludgeoning", "acid", "cold", "fire", "lightning", "poison"],
                        "does": "The damage type your unarmed strikes deal (Draconic Strike): bludgeoning, or acid, cold, fire, lightning, poison."},
    "armor_model": {"feat": "Armor Model", "kind": "option", "label": "Armor Model", "feature": ("Artificer", "Armorer", 3),
                    "options": ["Guardian", "Infiltrator"],
                    "does": "Guardian: Thunder Gauntlets (1d8 thunder, the target has disadvantage against others) and Defensive Field. "
                            "Infiltrator: Lightning Launcher (1d6 lightning at range, +1d6 once a turn)."},
}

GENIE_TYPES = {"Dao": "bludgeoning", "Djinni": "thunder", "Efreeti": "fire", "Marid": "cold"}
# lower-cased option name -> the choice keys that offer it (Character.has_feature asks: picked or not?)
CHOICE_NAMES: Dict[str, List[str]] = {}
for _k, _f in FEATS.items():
    if _f.get("feature"):
        for _o in _f["options"]:
            CHOICE_NAMES.setdefault(_o.lower(), []).append(_k)


def _feature_has(char, f: dict) -> bool:
    cls, sub, lv = f["feature"]
    return char.class_level(cls) >= lv and (char.class_entry(cls) or {}).get("subclass") == sub


def unpicked(char, low: str) -> bool:
    """A subclass option the character didn't pick (a Hunter's Uncanny Dodge when Evasion was chosen), unless another
    class or race gives it too."""
    keys = CHOICE_NAMES.get(low)
    if not keys:
        return False
    for key in keys:
        f = FEATS[key]
        if not _feature_has(char, f) or str(is_on(char, key)).lower() == low:
            continue
        sub = f["feature"][1]
        return not any(x["name"].lower() == low and not x["source"].endswith(sub) for x in char.features())
    return False


def has(char, key: str) -> bool:
    f = FEATS.get(key)
    if f and f.get("feature"):
        return _feature_has(char, f)
    return bool(f) and f["feat"] in (char.d.get("feats") or [])


def is_on(char, key: str):
    """The switch's state: False/True, or the chosen option (Elemental Adept). Feats the character lacks are off."""
    if not char or not has(char, key):
        return False
    f = FEATS[key]
    saved = (char.d.get("toggles") or {}).get(key)
    if saved is None:
        if f["kind"] == "power":
            return False
        if f["kind"] == "option":
            return f["options"][0]
        return True
    return saved


def state(char) -> List[dict]:
    """The toggles of a character's situational feats: [{'key', 'feat', 'label', 'kind', 'on', 'options', 'does', 'text'}]."""
    out = []
    for key, f in FEATS.items():
        if not has(char, key):
            continue
        feat = rules.feats.get(f["feat"]) or {}
        if f.get("feature"):                                    # a subclass's "choose one": its own text
            sub = rules.subclass(f["feature"][0], f["feature"][1]) or {}
            feat = next((x for x in sub.get("features") or [] if x["name"] == f["feat"]), None) or {}
        out.append({"key": key, "feat": f["feat"], "label": f["label"], "kind": f["kind"], "on": is_on(char, key),
                    "options": f.get("options") or [], "does": f["does"], "text": feat.get("text", "")})
    return out


def set_toggle(char, key: str, value) -> None:
    if key not in FEATS or not has(char, key):
        raise KeyError(key)
    f = FEATS[key]
    if f["kind"] == "option" and value not in (False, None) and value not in f["options"]:
        raise ValueError(f"Choose one of {', '.join(f['options'])}.")
    char.d.setdefault("toggles", {})[key] = value if f["kind"] == "option" else bool(value)


def feat_key(feat_name: str) -> Optional[str]:
    return next((k for k, f in FEATS.items() if f["feat"] == feat_name), None)
