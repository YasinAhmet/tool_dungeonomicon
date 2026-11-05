"""What spells do to creatures in a battle, beyond what their description's dice show.

Every spell of the rules data is in exactly one place: read from its text by combat_rules.spell_plan (damage, healing, saving
throws, conditions), listed in BUFFS (an effect on a creature), POOLS / CLEANSES / SPECIAL (a rule of its own), or in UTILITY
(no effect that a battle tracks: scouting, travel, summoning, rituals...). tests/test_battle.py checks that none is left out.

Durations are in rounds (1 minute = 10, 10 minutes = 100, 1 hour = 600, 8 hours = 4800).
mods: attack / save / check: dice (or a number) added to that creature's rolls · ac: added Armor Class · ac_min / ac_base · attacks_against /
attacks_with: 'adv' / 'dis' · warded_from: creature types that attack it at disadvantage · duel: disadvantage on attacks against all but
the effect's caster · extra_damage: (dice, type) the CASTER adds to hits on it · dmg: (dice, type) the creature adds to its own hits ·
once: the dmg goes away after one hit · resist / immune: damage types · immune_cond: conditions it can't get · save_adv / save_dis: abilities
(or 'all') · check_adv · regen: dice healed at the start of its turn.
up / up_rider: dice added per slot level above the spell's to the dmg / to the rider's parts or damage over time (smites, arrows).
"""
ALL_TYPES = ["acid", "bludgeoning", "cold", "fire", "force", "lightning", "necrotic", "piercing", "poison", "psychic", "radiant", "slashing", "thunder"]
BPS = ["bludgeoning", "piercing", "slashing"]
ELEMENTS = ["acid", "cold", "fire", "lightning", "thunder"]

BUFFS = {
    # --- cantrips
    "blade ward": {"mods": {"resist": BPS}, "rounds": 1, "self": True, "note": "resists weapon damage this round"},
    "guidance": {"mods": {"check": "1d4"}, "rounds": 10, "once": True, "note": "+1d4 to its next ability check"},
    "resistance": {"mods": {"save": "1d4"}, "rounds": 10, "once": True, "note": "+1d4 to its next saving throw"},
    "true strike": {"mods": {"attacks_with": "adv"}, "rounds": 1, "self": True, "note": "advantage on its next attack"},
    "shillelagh": {"mods": {"shillelagh": True}, "rounds": 10, "self": True, "note": "club hits for d8"},
    # --- 1st level
    "bless": {"mods": {"attack": "1d4", "save": "1d4"}, "rounds": 10, "note": "+1d4 to attacks and saves"},
    "shield": {"mods": {"ac": 5}, "rounds": 1, "self": True, "note": "+5 AC"},
    "shield of faith": {"mods": {"ac": 2}, "rounds": 100, "note": "+2 AC"},
    "mage armor": {"mods": {"ac_base": 13}, "rounds": 4800, "note": "AC 13 + Dex"},
    "absorb elements": {"mods": {"resist": ["$type"]}, "rounds": 1, "self": True, "choose": ELEMENTS, "note": "resists the element"},
    "divine favor": {"mods": {"dmg": ("1d4", "radiant")}, "rounds": 10, "self": True, "note": "+1d4 radiant on weapon hits"},
    "false life": {"temp": "1d4+4", "temp_per_level": 5, "rounds": 600, "self": True, "note": "temporary hit points"},
    "heroism": {"mods": {"immune_cond": ["Frightened"], "temp_each": "MOD", "temp_ends": True}, "temp": "MOD", "rounds": 10, "note": "immune to fear, temporary hit points each turn"},
    "protection from evil and good": {"mods": {"warded_from": ["aberration", "celestial", "elemental", "fey", "fiend", "undead"],
                                               "immune_cond": ["Charmed", "Frightened"]}, "rounds": 100,
                                      "note": "aberrations, celestials, elementals, fey, fiends and undead attack it at disadvantage; immune to charm and fear"},
    "sanctuary": {"mods": {"attacks_against": "dis"}, "rounds": 10, "note": "attackers are put off"},
    "compelled duel": {"mods": {"duel": True}, "rounds": 10, "on_fail": True, "note": "disadvantage on attacks against others"},
    "searing smite": {"mods": {"dmg": ("1d6", "fire"), "rider": {"dot": {"dice": "1d6", "type": "fire", "when": "start", "save": "con"}}},
                      "rounds": 10, "self": True, "once": True, "up": "1d6", "note": "next hit +1d6 fire and it burns"},
    "thunderous smite": {"mods": {"dmg": ("2d6", "thunder"), "rider": {"ab": "str", "push": 10, "prone": True}}, "rounds": 10, "self": True,
                         "once": True, "note": "next hit +2d6 thunder, pushed and prone"},
    "wrathful smite": {"mods": {"dmg": ("1d6", "psychic"), "rider": {"ab": "wis", "conds": ["Frightened"], "rounds": 10}}, "rounds": 10, "self": True,
                       "once": True, "note": "next hit +1d6 psychic and frightened"},
    "branding smite": {"mods": {"dmg": ("2d6", "radiant"), "rider": {"reveal": True}}, "rounds": 10, "self": True, "once": True, "up": "1d6",
                       "note": "next hit +2d6 radiant, can't be invisible"},
    "blinding smite": {"mods": {"dmg": ("3d8", "radiant"), "rider": {"ab": "con", "conds": ["Blinded"], "repeat": "end", "rounds": 10}}, "rounds": 10,
                       "self": True, "once": True, "note": "next hit +3d8 radiant and blinded"},
    "staggering smite": {"mods": {"dmg": ("4d6", "psychic"), "rider": {"ab": "wis", "mods": {"attacks_with": "dis", "check_dis": True, "no_reactions": True},
                                                                         "rounds": 1, "note": "staggered"}},
                         "rounds": 10, "self": True, "once": True, "note": "next hit +4d6 psychic, staggered"},
    "banishing smite": {"mods": {"dmg": ("5d10", "force"), "rider": {"banish_below": 50}}, "rounds": 10, "self": True, "once": True,
                        "note": "next hit +5d10 force, banished at 50 HP or less"},
    "hail of thorns": {"mods": {"dmg": ("1d10", "piercing"), "ranged_only": True, "rider": {"burst": 5, "ab": "dex", "parts": [["1d10", "piercing"]], "half": True}},
                       "rounds": 10, "self": True, "once": True, "up_rider": "1d10", "note": "next ranged hit: thorns burst around the target"},
    "lightning arrow": {"mods": {"dmg": ("4d8", "lightning"), "ranged_only": True, "rider": {"burst": 10, "ab": "dex", "parts": [["2d8", "lightning"]], "half": True}},
                        "rounds": 10, "self": True, "once": True, "up": "1d8", "up_rider": "1d8", "note": "next ranged hit +4d8 lightning, bolts around the target"},
    "ensnaring strike": {"mods": {"dmg": ("0", ""), "rider": {"ab": "str", "conds": ["Restrained"], "rounds": 10, "dot": {"dice": "1d6", "type": "piercing", "when": "start"}}},
                         "rounds": 10, "self": True, "once": True, "up_rider": "1d6", "note": "next hit: vines restrain the target"},
    "hunter's mark": {"mods": {"extra_damage": ("1d6", ""), "weapon_only": True}, "rounds": 600, "marks": True, "note": "+1d6 damage from the caster"},
    "hex": {"mods": {"extra_damage": ("1d6", "necrotic"), "check_dis": ["$type"]}, "rounds": 600, "marks": True,
            "choose": ["str", "dex", "con", "int", "wis", "cha"], "note": "+1d6 necrotic from the caster, disadvantage on checks of one ability"},
    "bane": {"mods": {"attack": "-1d4", "save": "-1d4"}, "rounds": 10, "on_fail": True, "note": "-1d4 to attacks and saves"},
    # --- 2nd level
    "aid": {"temp": "5", "temp_per_level": 5, "max_up": True, "rounds": 4800, "note": "+5 hit points"},
    "barkskin": {"mods": {"ac_min": 16}, "rounds": 600, "note": "AC at least 16"},
    "blur": {"mods": {"attacks_against": "dis"}, "rounds": 10, "self": True, "note": "attacks against it have disadvantage"},
    "enhance ability": {"mods": {"check_adv": True}, "rounds": 600, "note": "advantage on ability checks"},
    "enlarge/reduce": {"mods": {"dmg": ("1d4", ""), "save_adv": ["str"], "check_adv": ["str"], "size_step": 1}, "rounds": 10,
                       "note": "bigger: one size up, +1d4 damage, advantage on Strength"},
    "faerie fire": {"mods": {"attacks_against": "adv", "outlined": True}, "rounds": 10, "on_fail": True, "note": "attacks against it have advantage"},
    "invisibility": {"mods": {"attacks_against": "dis", "attacks_with": "adv"}, "rounds": 600, "note": "invisible"},
    "magic weapon": {"mods": {"weapon_attack": "1", "dmg": ("1", "")}, "rounds": 600, "note": "+1 to attack and damage"},
    "mirror image": {"mods": {"attacks_against": "dis"}, "rounds": 10, "self": True, "note": "duplicates make attacks miss (approximated)"},
    "protection from poison": {"mods": {"resist": ["poison"], "save_adv": ["con"]}, "rounds": 600, "note": "resists poison"},
    "slow": {"mods": {"ac": -2, "save_dis": ["dex"]}, "rounds": 10, "on_fail": True, "repeat": "end", "note": "-2 AC"},
    "warding bond": {"mods": {"ac": 1, "save": "1", "resist": ALL_TYPES, "bond": True}, "rounds": 600,
                     "note": "+1 AC and saves, resists all damage; the caster takes the same damage"},
    "healing spirit": {"mods": {"regen": "1d6"}, "rounds": 10, "note": "heals 1d6 each turn"},
    # --- 3rd level
    "aura of vitality": {"mods": {"regen": "2d6"}, "rounds": 10, "note": "heals 2d6 each turn"},
    "beacon of hope": {"mods": {"save_adv": ["wis"], "max_heal": True}, "rounds": 10, "note": "advantage on Wisdom saves, healing at its maximum"},
    "elemental weapon": {"mods": {"weapon_attack": "1", "dmg": ("1d4", "")}, "rounds": 600, "note": "+1 attack, +1d4 damage"},
    "gaseous form": {"mods": {"resist": ["nonmagical"], "save_adv": ["str", "dex", "con"], "no_spells": True, "fly": 10}, "rounds": 600,
                     "note": "resists weapon damage, advantage on Str/Dex/Con saves, flying speed 10 ft, can't cast spells"},
    "haste": {"mods": {"ac": 2, "save_adv": ["dex"]}, "rounds": 10, "note": "+2 AC, advantage on Dexterity saves, extra action"},
    "motivational speech": {"temp": "5", "rounds": 600, "note": "+5 temporary hit points"},
    "protection from energy": {"mods": {"resist": ["$type"]}, "rounds": 600, "choose": ELEMENTS, "note": "resists the element"},
    "crusader's mantle": {"mods": {"dmg": ("1d4", "radiant"), "aura_ft": 30}, "rounds": 10, "note": "+1d4 radiant on weapon hits (and allies within 30 ft)"},
    "holy weapon": {"mods": {"dmg": ("2d8", "radiant")}, "rounds": 600, "note": "+2d8 radiant on weapon hits"},
    # --- 4th level and up
    "aura of life": {"mods": {"resist": ["necrotic"], "aura_ft": 30, "life_1": True}, "rounds": 100,
                     "note": "resists necrotic, 1 HP at the start of a turn at 0 (and allies within 30 ft)"},
    "aura of purity": {"mods": {"aura_ft": 30, "resist": ["poison"], "cond_save_adv": ["Blinded", "Charmed", "Deafened", "Frightened", "Paralyzed", "Poisoned", "Stunned"]},
                       "rounds": 100, "note": "resists poison, advantage on saves against conditions (and allies within 30 ft)"},
    "fire shield": {"mods": {"resist": ["$type"]}, "rounds": 100, "choose": ["cold", "fire"], "note": "resists the element"},
    "freedom of movement": {"mods": {"immune_cond": ["Grappled", "Paralyzed", "Restrained"], "free_move": True}, "rounds": 600,
                            "note": "can't be held or paralyzed, ignores difficult terrain"},
    "greater invisibility": {"mods": {"attacks_against": "dis", "attacks_with": "adv"}, "rounds": 10, "note": "invisible"},
    "stoneskin": {"mods": {"resist": ["nonmagical"]}, "rounds": 600, "note": "resists nonmagical weapon damage"},
    "circle of power": {"mods": {"save_adv_spells": ["str", "dex", "con", "int", "wis", "cha"], "aura_ft": 30}, "rounds": 100,
                        "note": "advantage on saves against spells (and allies within 30 ft)"},
    "intellect fortress": {"mods": {"resist": ["psychic"], "save_adv": ["int", "wis", "cha"]}, "rounds": 600, "note": "resists psychic"},
    "tasha's otherworldly guise": {"mods": {"immune": ["fire", "poison"], "immune_cond": ["Poisoned"], "ac": 2, "fly": 40, "two_attacks": True},
                                   "rounds": 10, "self": True,
                                   "note": "immune to fire, poison and poisoning, +2 AC, flying speed 40 ft"},
    "primordial ward": {"mods": {"resist": ELEMENTS}, "rounds": 10, "self": True, "note": "resists the elements"},
    "mind blank": {"mods": {"immune_cond": ["Charmed"], "immune": ["psychic"]}, "rounds": 14400, "note": "immune to charm and psychic damage"},
    "foresight": {"mods": {"attacks_with": "adv", "attacks_against": "dis", "save_adv": ["all"]}, "rounds": 4800, "note": "advantage on everything"},
    "invulnerability": {"mods": {"immune": ALL_TYPES}, "rounds": 100, "self": True, "note": "immune to all damage"},
    "heroes' feast": {"mods": {"immune": ["poison"], "immune_cond": ["Frightened", "Poisoned"]}, "temp": "2d10", "rounds": 14400, "note": "immune to poison and fear"},
}

# spells that ride on the caster's next weapon hit (smites, a ranger's arrows): readied for free, cast when a hit lands
ON_HIT = {k for k, v in BUFFS.items() if v.get("self") and v.get("once") and "dmg" in v["mods"] and "rider" in v["mods"]}


def on_hit_fits(key: str, melee: bool) -> bool:
    """Whether a weapon hit (melee or ranged) can carry this readied spell: smites want a melee weapon, arrows a ranged one."""
    if BUFFS[key]["mods"].get("ranged_only"):
        return not melee
    return melee or not key.endswith("smite")


# spells whose save only matters for a condition the description words in a way the parser can't see
CONDS = {
    "blindness/deafness": (["Blinded"], "end", 10),
    "stinking cloud": (["Incapacitated"], None, 10),
    "confusion": ([], "end", 10),                       # no condition: a d10 each turn decides (spellbook, spells._confusion)
    "banishment": (["Incapacitated"], None, 10),             # no save to shake it off: it lasts while she concentrates
    "command": (["Incapacitated"], None, 1),
    "compulsion": ([], "end", 10),                      # no condition: the caster steers its movement (spellbook)
    "hold person": (["Paralyzed"], "end", 10),
    "hold monster": (["Paralyzed"], "end", 10),
}
PARTS = {"delayed blast fireball": [("12d6", "fire")]}

# healing the description words as "heals" or by points rather than dice
HEALS = {"heal": ("70", 10), "mass heal": ("9999", 0), "power word heal": ("9999", 0), "regenerate": ("4d8+15", 0)}

# creature pools: the dice are hit points; the spell goes through the lowest first
POOLS = {"sleep": ("5d8", "2d8", "Unconscious", 10), "color spray": ("6d10", "2d10", "Blinded", 1)}

# take conditions off a creature (and the effects that give them)
CLEANSES = {
    "lesser restoration": ["Blinded", "Deafened", "Paralyzed", "Poisoned"],
    "greater restoration": ["Charmed", "Petrified", "Blinded", "Deafened", "Paralyzed", "Poisoned", "Stunned"],
    "remove curse": [], "dispel magic": "all", "heroes' feast": [],
    "power word heal": ["Blinded", "Deafened", "Paralyzed", "Poisoned", "Stunned", "Charmed", "Frightened", "Prone"],
    "heal": ["Blinded", "Deafened", "Poisoned"],
}
ONE_ONLY = {"lesser restoration"}             # "end either one disease or one condition": the first of the listed ones the creature has
REVIVES = {"revivify", "raise dead", "resurrection", "true resurrection", "reincarnate", "clone", "spare the dying"}
# a creature with at most this many hit points: power word kill defeats it, power word stun stuns it
POWER_WORDS = {"power word kill": ("kill", 100), "power word stun": ("stun", 150)}


# --- summons: the creatures appear as tokens on the tile nearest the caster (allies of a player character, enemies of a monster).
# spirit: one stat block, the caster picks a variant (a pop-up); hp/ac come from the spell level.
# choices: the caster picks one creature (a pop-up) - [(monster id, how many, lowest spell level)].
# ladder: pick any creature of a type up to a challenge rating; weaker creatures come in greater numbers (CR -> number).
SPIRITS = {
    "summon beast": ("Bestial Spirit|TCE", ["Air", "Land", "Water"], 11),
    "summon aberration": ("Aberrant Spirit|TCE", ["Beholderkin", "Slaad", "Star Spawn"], 11),
    "summon celestial": ("Celestial Spirit|TCE", ["Avenger", "Defender"], 11),
    "summon construct": ("Construct Spirit|TCE", ["Clay", "Metal", "Stone"], 13),
    "summon draconic spirit": ("Draconic Spirit|FTD", ["Chromatic", "Gem", "Metallic"], 14),
    "summon elemental": ("Elemental Spirit|TCE", ["Air", "Earth", "Fire", "Water"], 11),
    "summon fey": ("Fey Spirit|TCE", ["Fuming", "Mirthful", "Tricksy"], 12),
    "summon fiend": ("Fiendish Spirit|TCE", ["Demon", "Devil", "Yugoloth"], 12),
    "summon shadowspawn": ("Shadow Spirit|TCE", ["Fury", "Despair", "Fear"], 11),
    "summon undead": ("Undead Spirit|TCE", ["Ghostly", "Putrid", "Skeletal"], 11),
    "spirit of death": ("Reaper Spirit|BMT", [], 11),
    "battle familiar": ("Battle Familiar|AU", ["Brute", "Flyer", "Stalker"], 11),       # Arcana Unleashed: AC 11 + level (13 + level for a Brute)
    "summon plant": ("Plant Spirit|AU", ["Fungus", "Tree", "Vine"], 11),
    "summon dinosaur": ("Dinosaur Spirit|AU", ["Ankylosaur", "Triceratops", "Tyrannosaur"], 11),
    "call of valor": ("Valor Spirit|LGR", [], None),        # Legends Reforged: one stat block, its own AC (monsters_summons.json)
}
SPIRIT_AC_BONUS = {"Defender": 2, "Brute": 2, "Tree": 2, "Ankylosaur": 2}      # "+ 2 (Defender only)" in the spirit's armor class
SPELL_HP = {"homunculus servant": (5, 5)}       # hit points of a conjured creature the data leaves to a formula: 5 + 5 per spell level
FAMILIARS = ["Bat", "Cat", "Crab", "Frog", "Hawk", "Lizard", "Octopus", "Owl", "Poisonous Snake", "Quipper", "Rat", "Raven", "Sea Horse", "Spider", "Weasel"]
CHOICES = {
    "find familiar": [(n + "|MM", 1, 1) for n in FAMILIARS],
    "flock of familiars": [(n + "|MM", 3, 1) for n in FAMILIARS],
    "find steed": [(n + "|MM", 1, 2) for n in ("Warhorse", "Pony", "Camel", "Elk", "Mastiff")],
    "find greater steed": [(n + "|MM", 1, 4) for n in ("Griffon", "Pegasus", "Peryton", "Dire Wolf", "Rhinoceros", "Saber-Toothed Tiger")],
    "animate dead": [("Skeleton|MM", 1, 3), ("Zombie|MM", 1, 3)],
    "danse macabre": [("Skeleton|MM", 5, 5), ("Zombie|MM", 5, 5)],
    "create undead": [("Ghoul|MM", 3, 6), ("Ghast|MM", 2, 7), ("Wight|MM", 2, 8), ("Mummy|MM", 1, 9)],
    "phantom steed": [("Riding Horse|MM", 1, 3)],
    "giant insect": [("Giant Centipede|MM", 10, 4), ("Giant Spider|MM", 3, 4), ("Giant Wasp|MM", 5, 4), ("Giant Scorpion|MM", 1, 4)],
    "animate objects": [("Animated Object (Tiny)|PHB", 10, 5), ("Animated Object (Small)|PHB", 10, 5), ("Animated Object (Medium)|PHB", 5, 5),
                        ("Animated Object (Large)|PHB", 2, 5), ("Animated Object (Huge)|PHB", 1, 5)],
    "tiny servant": [("Tiny Servant|XGE", 1, 3)],
    "homunculus servant": [("Homunculus Servant|TCE", 1, 2)],       # (the EFA spell's stat block isn't in the library: this one with the spell's numbers)
}
# Summons that don't vanish when the caster's concentration breaks: they stay and turn on their summoner's side.
TURN_ON_CONC_LOSS = {"conjure elemental", "conjure fey", "infernal calling"}
# Conjured things that stand on the map but act through their caster (no turn of their own): spell name -> token.
#   move: feet the caster's command moves it; span: tiles; tiny: shares tiles, stands anywhere (board.py);
#   hp: None (can't be harmed), a number, or "caster" (its max HP);
#   bite: damage it deals by itself at the start of its caster's turn to a foe within 5 ft (Faithful Hound)
TOKENS = {
    "spiritual weapon": {"name": "Spiritual Weapon", "move": 20, "tiny": True},
    "mordenkainen's sword": {"name": "Mordenkainen's Sword", "move": 20, "tiny": True},
    "blade of disaster": {"name": "Blade of Disaster", "move": 30, "tiny": True},
    "bigby's hand": {"name": "Bigby's Hand", "move": 60, "span": 2, "hp": "caster", "ac": 20},
    "mordenkainen's faithful hound": {"name": "Faithful Hound", "move": 0, "bite": [["4d8", "piercing"]]},
    "unseen servant": {"name": "Unseen Servant", "move": 30, "hp": 1, "ac": 10},
    "guardian of faith": {"name": "Guardian of Faith", "move": 0, "span": 2},
    "conjure constructs": {"name": "Spirit Constructs", "move": 30, "tiny": True},
}
LADDER = [(2, 1), (1, 2), (.5, 4), (.25, 8)]
LADDERS = {
    # name: (types, tag or None, ladder, highest CR (None = the ladder's), spell level the numbers are for, levels per doubling)
    "conjure animals": (["beast"], None, LADDER, None, 3, 2),
    "conjure woodland beings": (["fey"], None, LADDER, None, 4, 2),
    "conjure minor elementals": (["elemental"], None, LADDER, None, 4, 2),
    "summon lesser demons": (["fiend"], "demon", [(1, 2), (.5, 4), (.25, 8)], None, 3, 99),
    "conjure celestial": (["celestial"], None, [(4, 1)], None, 7, 99),
    "conjure elemental": (["elemental"], None, [(5, 1)], None, 5, 99),
    "conjure fey": (["fey"], None, [(6, 1)], None, 6, 99),
    "summon greater demon": (["fiend"], "demon", [(5, 1)], None, 4, 99),
    "infernal calling": (["fiend"], "devil", [(6, 1)], None, 5, 99),
    "planar ally": (["celestial", "elemental", "fiend"], None, [(10, 1)], None, 6, 99),
    "planar binding": (["celestial", "elemental", "fey", "fiend"], None, [(8, 1)], None, 5, 99),
}

# No effect a battle tracks: scouting, travel, light and sound, locks, rituals, messages, illusions, walls, terrain, food, portals...
UTILITY = [
    "Air Bubble",
    "Alarm",
    "Animal Messenger",
    "Animal Shapes",
    "Antilife Shell",
    "Antimagic Field",
    "Arcane Eye",
    "Arcane Gate",
    "Arcane Lock",
    "Astral Projection",
    "Augury",
    "Awaken",
    "Beast Bond",
    "Beast Sense",
    "Blink",
    "Borrowed Knowledge",
    "Catnap",
    "Ceremony",
    "Clairvoyance",
    "Commune",
    "Commune with Nature",
    "Comprehend Languages",
    "Conjure Barrage",
    "Conjure Volley",
    "Contingency",
    "Continual Flame",
    "Control Flames",
    "Control Weather",
    "Counterspell",
    "Create Food and Water",
    "Create Magen",
    "Create Spelljamming Helm",
    "Create or Destroy Water",
    "Creation",
    "Dancing Lights",
    "Darkness",
    "Darkvision",
    "Daylight",
    "Death Ward",
    "Demiplane",
    "Detect Evil and Good",
    "Detect Magic",
    "Detect Poison and Disease",
    "Detect Thoughts",
    "Deryan's Helpful Homunculi",        # spirits that halve a crafting time
    "Disguise Self",
    "Distort Value",
    "Divination",
    "Divine Word",
    "Drawmij's Instant Summons",
    "Dream of the Blue Veil",
    "Druid Grove",
    "Druidcraft",
    "Earthbind",
    "Encode Thoughts",
    "Enemies Abound",
    "Etherealness",
    "Expeditious Retreat",
    "Fabricate",
    "Far Step",
    "Feather Fall",
    "Feign Death",
    "Find Traps",
    "Find the Path",
    "Fizban's Platinum Shield",
    "Fly",
    "Fog Cloud",
    "Forcecage",
    "Fortune's Favor",
    "Friends",
    "Galder's Speedy Courier",
    "Galder's Tower",
    "Gate",
    "Gate Seal",
    "Gentle Repose",
    "Gift of Alacrity",
    "Gift of Gab",
    "Glibness",
    "Globe of Invulnerability",
    "Goodberry",
    "Grasping Vine",
    "Guards and Wards",
    "Gust",
    "Gust of Wind",
    "Hallucinatory Terrain",
    "Hindsight",                         # ten years of visions: scouting
    "Identify",
    "Illusory Script",
    "Immovable Object",
    "Jim's Glowing Coin",
    "Jump",
    "Knock",
    "Legend Lore",
    "Leomund's Secret Chest",
    "Leomund's Tiny Hut",
    "Levitate",
    "Light",
    "Linked Glyphs",
    "Locate Animals or Plants",
    "Locate Creature",
    "Locate Object",
    "Longstrider",
    "Mage Hand",
    "Magic Jar",
    "Magic Mouth",
    "Major Image",
    "Mass Polymorph",
    "Maze",
    "Mending",
    "Message",
    "Mighty Fortress",
    "Minor Illusion",
    "Mirage Arcane",
    "Mislead",
    "Misty Step",
    "Mold Earth",
    "Mordenkainen's Magnificent Mansion",
    "Mordenkainen's Private Sanctum",
    "Move Earth",
    "Nondetection",
    "Nystul's Magic Aura",
    "Otiluke's Resilient Sphere",
    "Pass without Trace",
    "Passwall",
    "Plant Growth",
    "Power Word Pain",
    "Prestidigitation",
    "Programmed Illusion",
    "Project Image",
    "Purify Food and Drink",
    "Rary's Telepathic Bond",
    "Reverse Gravity",
    "Rope Trick",
    "Scatter",
    "Scrying",
    "See Invisibility",
    "Seeming",
    "Sending",
    "Sequester",
    "Shape Water",
    "Shapechange",
    "Silence",
    "Silent Image",
    "Silvery Barbs",
    "Skill Empowerment",
    "Skywrite",
    "Soul Cage",
    "Speak with Animals",
    "Speak with Dead",
    "Speak with Plants",
    "Spider Climb",
    "Stone Shape",
    "Swift Quiver",
    "Telekinesis",
    "Telepathy",
    "Teleportation Circle",
    "Temporal Shunt",
    "Tenser's Floating Disk",
    "Tether Essence",
    "Thaumaturgy",
    "Time Stop",
    "Tongues",
    "Transport via Plants",
    "Tree Stride",
    "True Seeing",
    "Unseen Servant",                  # its token comes from spellbook.SPECIAL (kind "token")
    "Vortex Warp",
    "Wall of Force",
    "Wall of Sand",
    "Wall of Stone",
    "Wall of Water",
    "Warding Wind",
    "Warp Sense",
    "Water Breathing",
    "Water Walk",
    "Wind Walk",
    "Word of Recall",
    "Wristpocket",
    "Zone of Amicability",               # a bonus to influence checks in a 60-foot emanation: no battle effect
    "Zone of Truth"
]
