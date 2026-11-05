"""Quick adventurers: a ready-to-play character of any level from a race, a class and a level. Every other decision
(ability scores, background, skills, subclass, spells, feats, equipment, name, personality) is made the way a
sensible player would make it for that class, through the same rules as the creation wizard and the level-up window,
so the result is an ordinary character: its creation choices can be edited and each level is recorded.

    char = quickgen.generate({"race": "Dwarf", "class": "Fighter", "level": 5})     # a Character (not saved)
    for a in quickgen.archetypes(): a["key"], a["title"], a["race"], a["class"], a["blurb"]
    char = quickgen.generate(quickgen.archetype_options("dwarf-fighter", level=3, name="Brog"))

Options: race, subrace, class, subclass, level (1-20), background, alignment, name, gender ('male', 'female', ''
for either), seed; an archetype adds abilities (priority order), weapons, equipment, feats, skills, appearance.
"""
import copy
import random
from typing import Dict, List, Optional

from . import engine as E
from . import spellcasting as SC
from .character import SKILLS, Character
from .creation import (apply_background, apply_race, background_requirements, background_tool_pool, choose_pool,
                       create_character, race_requirements, type_options)
from .data import rules
from .srd import book_name
from .leveling import RulesError, apply_feat, apply_level_up, autolevel, plan_level_up, thieves_tools_open

# ---------------------------------------------------------------- how each class is usually built
# abilities: the standard array goes to them in this order. skills/expertise: preferred picks, best first.
PROFILES: Dict[str, dict] = {
    "Barbarian": {"abilities": "str con dex wis cha int", "background": "Outlander", "alignment": "Chaotic Neutral",
                  "skills": ["Athletics", "Perception", "Survival", "Intimidation", "Animal Handling", "Nature"],
                  "subclass": ["Path of the Totem Warrior", "Path of the Berserker"], "equipment": ["a", "a"],
                  "feats": ["Great Weapon Master", "Sentinel", "Tough", "Alert"]},
    "Bard": {"abilities": "cha dex con wis int str", "background": "Entertainer", "alignment": "Chaotic Good",
             "skills": ["Persuasion", "Deception", "Performance", "Insight", "Perception", "Stealth", "Acrobatics", "Arcana"],
             "expertise": ["Persuasion", "Perception", "Deception", "Stealth"],
             "subclass": ["College of Lore", "College of Valor"], "equipment": ["a", "b", "a"],
             "feats": ["War Caster", "Resilient", "Alert", "Lucky"]},
    "Cleric": {"abilities": "wis con str dex cha int", "background": "Acolyte", "alignment": "Lawful Good",
               "skills": ["Insight", "Medicine", "Persuasion", "Religion", "History"],
               "subclass": ["Life Domain", "War Domain", "Light Domain", "Tempest Domain"], "equipment": ["a", "a", "a", "a"],
               "feats": ["War Caster", "Resilient", "Alert", "Tough"]},
    "Druid": {"abilities": "wis con dex int cha str", "background": "Hermit", "alignment": "Neutral",
              "skills": ["Perception", "Nature", "Animal Handling", "Insight", "Survival", "Medicine", "Arcana"],
              "subclass": ["Circle of the Moon", "Circle of the Land"], "equipment": ["a", "a"],
              "feats": ["War Caster", "Resilient", "Alert", "Tough"]},
    "Fighter": {"abilities": "str con dex wis cha int", "background": "Soldier", "alignment": "Lawful Neutral",
                "skills": ["Athletics", "Perception", "Intimidation", "Survival", "Insight", "Acrobatics"],
                "subclass": ["Battle Master", "Champion", "Eldritch Knight"], "equipment": ["a", "a", "a", "a"],
                "feats": ["Great Weapon Master", "Sentinel", "Polearm Master", "Tough", "Alert"]},
    "Monk": {"abilities": "dex wis con str int cha", "background": "Hermit", "alignment": "Lawful Neutral",
             "skills": ["Acrobatics", "Stealth", "Insight", "Athletics", "Perception"],
             "subclass": ["Way of the Open Hand", "Way of Shadow", "Way of the Four Elements"], "equipment": ["a", "b"],
             "feats": ["Mobile", "Alert", "Tough", "Resilient"]},
    "Paladin": {"abilities": "str cha con wis dex int", "background": "Noble", "alignment": "Lawful Good",
                "skills": ["Athletics", "Persuasion", "Insight", "Intimidation", "Religion", "Medicine"],
                "subclass": ["Oath of Devotion", "Oath of Vengeance", "Oath of the Ancients"], "equipment": ["a", "a", "a"],
                "feats": ["Sentinel", "Great Weapon Master", "Polearm Master", "Tough", "Alert"]},
    "Ranger": {"abilities": "dex wis con str int cha", "background": "Outlander", "alignment": "Neutral Good",
               "skills": ["Perception", "Stealth", "Survival", "Nature", "Athletics", "Animal Handling", "Insight"],
               "subclass": ["Hunter", "Beast Master"], "equipment": ["b", "a", "b"], "fighting_style": ["Archery"],
               "feats": ["Sharpshooter", "Alert", "Mobile", "Tough"]},
    "Rogue": {"abilities": "dex con int wis cha str", "background": "Criminal", "alignment": "Chaotic Neutral",
              "skills": ["Stealth", "Perception", "Acrobatics", "Sleight of Hand", "Deception", "Investigation", "Insight",
                         "Persuasion"], "expertise": ["Stealth", "Perception", "Thieves' Tools", "Acrobatics", "Deception"],
              "subclass": ["Thief", "Assassin", "Arcane Trickster"], "equipment": ["a", "a", "a"],
              "feats": ["Alert", "Mobile", "Sharpshooter", "Lucky"]},
    "Sorcerer": {"abilities": "cha con dex wis int str", "background": "Sage", "alignment": "Chaotic Good",
                 "skills": ["Arcana", "Persuasion", "Insight", "Deception", "Intimidation"],
                 "subclass": ["Draconic Bloodline", "Wild Magic"], "equipment": ["a", "b", "b"],
                 "feats": ["War Caster", "Resilient", "Alert", "Lucky"]},
    "Warlock": {"abilities": "cha con dex wis int str", "background": "Charlatan", "alignment": "Chaotic Neutral",
                "skills": ["Deception", "Intimidation", "Arcana", "Investigation", "History"],
                "subclass": ["The Fiend", "The Great Old One", "The Archfey"], "equipment": ["a", "b", "b"],
                "feats": ["War Caster", "Resilient", "Alert", "Lucky"]},
    "Wizard": {"abilities": "int con dex wis cha str", "background": "Sage", "alignment": "Neutral Good",
               "skills": ["Arcana", "Investigation", "History", "Insight", "Religion"],
               "subclass": ["School of Evocation", "School of Abjuration", "School of Divination"], "equipment": ["a", "b", "a"],
               "feats": ["War Caster", "Resilient", "Alert", "Lucky"]},
}
# fighting styles, invocations, metamagic, maneuvers, pacts..., best first; what isn't listed comes after
OPTION_PREFS = ["Defense", "Great Weapon Fighting", "Dueling", "Archery", "Protection",
                "Agonizing Blast", "Pact of the Tome", "Pact of the Blade", "Devil's Sight", "Repelling Blast", "Book of Ancient Secrets",
                "Thirsting Blade", "Mask of Many Faces", "Eldritch Sight", "Misty Visions", "Lifedrinker", "Eldritch Spear",
                "Quickened Spell", "Twinned Spell", "Careful Spell", "Subtle Spell", "Extended Spell", "Empowered Spell",
                "Precision Attack", "Trip Attack", "Riposte", "Menacing Attack", "Pushing Attack", "Disarming Attack",
                "Goading Attack", "Commander's Strike",
                "Fangs of the Fire Snake", "Water Whip", "Fist of Four Thunders", "Sweeping Cinder Strike"]
CANTRIP_PREFS = ["Eldritch Blast", "Fire Bolt", "Sacred Flame", "Toll the Dead", "Vicious Mockery", "Produce Flame", "Guidance",
                 "Shillelagh", "Mage Hand", "Ray of Frost", "Minor Illusion", "Light", "Prestidigitation", "Spare the Dying",
                 "Thaumaturgy", "Shocking Grasp", "Chill Touch", "Mind Sliver", "Thorn Whip", "Druidcraft", "Message", "Mending"]
SPELL_PREFS = [
    # 1st
    "Shield", "Healing Word", "Bless", "Magic Missile", "Sleep", "Cure Wounds", "Guiding Bolt", "Faerie Fire", "Hunter's Mark",
    "Hex", "Mage Armor", "Thunderwave", "Burning Hands", "Entangle", "Goodberry", "Detect Magic", "Find Familiar", "Command",
    "Shield of Faith", "Dissonant Whispers", "Tasha's Hideous Laughter", "Charm Person", "Feather Fall", "Absorb Elements",
    "Chromatic Orb", "Divine Favor", "Wrathful Smite", "Thunderous Smite", "Searing Smite", "Protection from Evil and Good",
    "Inflict Wounds", "Armor of Agathys", "Hellish Rebuke", "Ensnaring Strike", "Hail of Thorns", "Fog Cloud", "Longstrider",
    "Heroism", "Sanctuary", "Identify", "Disguise Self", "Comprehend Languages",
    # 2nd
    "Misty Step", "Spiritual Weapon", "Hold Person", "Web", "Scorching Ray", "Shatter", "Invisibility", "Moonbeam",
    "Pass without Trace", "Lesser Restoration", "Aid", "Mirror Image", "Heat Metal", "Spike Growth", "Suggestion", "Darkness",
    "Blur", "Prayer of Healing", "Find Steed", "Magic Weapon", "Silence", "Branding Smite", "Flaming Sphere", "Barkskin",
    "Enhance Ability", "Cloud of Daggers", "Detect Thoughts", "See Invisibility",
    # 3rd
    "Fireball", "Counterspell", "Spirit Guardians", "Hypnotic Pattern", "Haste", "Revivify", "Fly", "Lightning Bolt",
    "Dispel Magic", "Mass Healing Word", "Call Lightning", "Conjure Animals", "Hunger of Hadar", "Slow", "Fear",
    "Lightning Arrow", "Plant Growth", "Crusader's Mantle", "Beacon of Hope", "Aura of Vitality", "Bestow Curse",
    "Vampiric Touch", "Sleet Storm", "Stinking Cloud", "Animate Dead", "Remove Curse",
    # 4th
    "Polymorph", "Banishment", "Greater Invisibility", "Wall of Fire", "Dimension Door", "Guardian of Faith", "Death Ward",
    "Confusion", "Ice Storm", "Freedom of Movement", "Blight", "Conjure Woodland Beings", "Stoneskin", "Phantasmal Killer",
    "Evard's Black Tentacles", "Locate Creature", "Aura of Purity", "Staggering Smite", "Compulsion",
    # 5th
    "Wall of Force", "Animate Objects", "Cone of Cold", "Greater Restoration", "Mass Cure Wounds", "Hold Monster", "Raise Dead",
    "Flame Strike", "Insect Plague", "Telekinesis", "Dominate Person", "Bigby's Hand", "Scrying", "Wall of Stone",
    "Banishing Smite", "Destructive Wave", "Circle of Power", "Swift Quiver", "Conjure Elemental", "Teleportation Circle", "Geas",
    # 6th
    "Heal", "Disintegrate", "Chain Lightning", "Mass Suggestion", "Globe of Invulnerability", "Sunbeam", "Heroes' Feast",
    "Blade Barrier", "True Seeing", "Otto's Irresistible Dance", "Wall of Ice", "Circle of Death", "Harm", "Eyebite",
    "Word of Recall", "Transport via Plants", "Arcane Gate", "Contingency",
    # 7th
    "Forcecage", "Plane Shift", "Teleport", "Regenerate", "Fire Storm", "Resurrection", "Finger of Death", "Reverse Gravity",
    "Simulacrum", "Delayed Blast Fireball", "Etherealness", "Prismatic Spray", "Divine Word",
    # 8th
    "Feeblemind", "Maze", "Sunburst", "Power Word Stun", "Dominate Monster", "Holy Aura", "Earthquake", "Incendiary Cloud",
    "Antimagic Field", "Mind Blank", "Animal Shapes", "Glibness",
    # 9th
    "Wish", "True Polymorph", "Meteor Swarm", "Mass Heal", "Foresight", "Time Stop", "Shapechange", "Gate", "Power Word Kill",
    "True Resurrection", "Storm of Vengeance", "Prismatic Wall", "Astral Projection"]
LANGUAGE_PREFS = ["Elvish", "Dwarvish", "Draconic", "Goblin", "Orc", "Giant", "Halfling", "Gnomish", "Sylvan", "Infernal",
                  "Celestial", "Abyssal", "Undercommon", "Primordial", "Deep Speech"]
# what an 'any ... weapon/focus' equipment slot takes, best first (otherwise the first on offer)
TYPE_PREFS = {"weaponMartial": ["Longsword", "Battleaxe", "Warhammer", "Rapier"],
              "weaponMartialMelee": ["Greatsword", "Greataxe", "Longsword", "Battleaxe"],
              "weaponSimple": ["Spear", "Mace", "Quarterstaff", "Handaxe", "Light Crossbow"],
              "weaponSimpleMelee": ["Spear", "Mace", "Quarterstaff", "Handaxe"],
              "focusSpellcastingArcane": ["Staff", "Wand", "Orb"], "focusSpellcastingHoly": ["Amulet", "Emblem"],
              "focusSpellcastingDruidic": ["Wooden Staff", "Totem"], "instrumentMusical": ["Lute", "Flute", "Lyre"]}
USEFUL_SKILLS = ["Perception", "Insight", "Athletics", "Stealth", "Persuasion", "Acrobatics", "Survival", "Investigation",
                 "Arcana", "Medicine", "Deception", "Intimidation"]
GENERIC_FEATS = ["Tough", "Alert", "Lucky", "Resilient", "Observant"]

# ---------------------------------------------------------------- pre-made concepts
ARCHETYPES: List[dict] = [
    {"key": "dwarf-fighter", "title": "Dwarven Fighter", "race": "Dwarf", "subrace": "Mountain", "class": "Fighter",
     "subclass": "Champion", "background": "Soldier", "alignment": "Lawful Good", "weapons": {"weaponMartial": ["Battleaxe"]},
     "blurb": "A stout shield-wall veteran with an axe and a long memory for grudges.",
     "appearance": "Broad and weathered, braided beard, dented plate and a well-loved battleaxe."},
    {"key": "human-paladin", "title": "Human Paladin", "race": "Human", "class": "Paladin", "subclass": "Oath of Devotion",
     "background": "Acolyte", "alignment": "Lawful Good",
     "blurb": "A sworn knight of a temple order: sword, shield and an unbending oath.",
     "appearance": "Polished mail under a temple tabard, a holy symbol on a chain, steady eyes."},
    {"key": "elf-wizard", "title": "Elven Wizard", "race": "Elf", "subrace": "High", "class": "Wizard",
     "subclass": "School of Evocation", "background": "Sage", "alignment": "Neutral Good",
     "blurb": "A centuries-young scholar of the arcane who solves most problems with fire.",
     "appearance": "Slender, ink-stained fingers, robes embroidered with sigils, a staff of pale wood."},
    {"key": "halfling-rogue", "title": "Halfling Rogue", "race": "Halfling", "subrace": "Lightfoot", "class": "Rogue",
     "subclass": "Thief", "background": "Criminal", "alignment": "Chaotic Good",
     "blurb": "A cheerful lockpick with quick hands, quicker feet and a heart of (mostly) gold.",
     "appearance": "Curly hair, a disarming grin, a dark cloak with far too many pockets."},
    {"key": "half-orc-barbarian", "title": "Half-Orc Barbarian", "race": "Half-Orc", "class": "Barbarian",
     "subclass": "Path of the Berserker", "background": "Outlander", "alignment": "Chaotic Neutral",
     "blurb": "A towering warrior from the wild frontier whose rage is as famous as their appetite.",
     "appearance": "Scarred grey-green skin, tusks capped with iron rings, a greataxe nearly as tall as they are."},
    {"key": "dwarf-cleric", "title": "Dwarven Cleric", "race": "Dwarf", "subrace": "Hill", "class": "Cleric",
     "subclass": "Life Domain", "background": "Acolyte", "alignment": "Lawful Good",
     "blurb": "A tireless healer of the forge-god who mends wounds and cracks skulls with equal care.",
     "appearance": "Soot-dark beard, heavy mail, a hammer-shaped holy symbol at the belt."},
    {"key": "elf-ranger", "title": "Wood Elf Ranger", "race": "Elf", "subrace": "Wood", "class": "Ranger",
     "subclass": "Hunter", "background": "Outlander", "alignment": "Neutral Good",
     "blurb": "A silent forest scout and peerless archer who has walked every trail in the old woods.",
     "appearance": "Green and brown leathers, a longbow across the back, leaves caught in the hair."},
    {"key": "tiefling-warlock", "title": "Tiefling Warlock", "race": "Tiefling", "class": "Warlock", "subclass": "The Fiend",
     "background": "Charlatan", "alignment": "Chaotic Neutral",
     "blurb": "A silver-tongued dealmaker who traded something important for infernal power.",
     "appearance": "Curling horns, a restless tail, fine but slightly singed clothes."},
    {"key": "half-elf-bard", "title": "Half-Elf Bard", "race": "Half-Elf", "class": "Bard", "subclass": "College of Lore",
     "background": "Entertainer", "alignment": "Chaotic Good",
     "blurb": "A travelling minstrel who collects stories, secrets and admirers in every town.",
     "appearance": "Bright travelling clothes, a lute with a cracked but lucky neck, an easy smile."},
    {"key": "dragonborn-sorcerer", "title": "Dragonborn Sorcerer", "race": "Dragonborn", "class": "Sorcerer",
     "subclass": "Draconic Bloodline", "background": "Sage", "alignment": "Lawful Neutral",
     "blurb": "Draconic blood runs hot in their veins; magic comes as naturally as breathing fire.",
     "appearance": "Gleaming scales, smouldering eyes, scholar's robes cut to show a proud crest."},
    {"key": "elf-druid", "title": "Wood Elf Druid", "race": "Elf", "subrace": "Wood", "class": "Druid",
     "subclass": "Circle of the Moon", "background": "Hermit", "alignment": "Neutral",
     "blurb": "A keeper of the deep woods who would rather be a bear than talk to you.",
     "appearance": "Bark-brown skin, antler charms, a cloak of moss and feathers."},
    {"key": "human-monk", "title": "Human Monk", "race": "Human", "class": "Monk", "subclass": "Way of the Open Hand",
     "background": "Hermit", "alignment": "Lawful Neutral",
     "blurb": "A disciplined wanderer from a mountain monastery, calm as still water until it isn't.",
     "appearance": "Shaved head, simple wrapped robes, bare feet hardened by years on stone."},
    {"key": "human-fighter", "title": "Human Fighter", "race": "Human", "class": "Fighter", "subclass": "Battle Master",
     "background": "Soldier", "alignment": "Neutral Good",
     "blurb": "A former sergeant who knows a hundred tricks for staying alive on a battlefield.",
     "appearance": "Close-cropped hair, a soldier's posture, a longsword and a battered shield."},
    {"key": "gnome-wizard", "title": "Gnome Illusionist", "race": "Gnome", "subrace": "Rock", "class": "Wizard",
     "subclass": "School of Illusion", "background": "Sage", "alignment": "Chaotic Good",
     "blurb": "A tinkering trickster whose illusions are almost as convincing as their excuses.",
     "appearance": "Wild white hair, goggles on the brow, sleeves full of gadgets."},
    {"key": "halfling-cleric", "title": "Halfling Cleric", "race": "Halfling", "subrace": "Stout", "class": "Cleric",
     "subclass": "Light Domain", "background": "Acolyte", "alignment": "Neutral Good",
     "blurb": "A small hearth-priest with a big lantern, bringing light (and soup) wherever it is needed.",
     "appearance": "Rosy cheeks, a sun-embroidered vestment, a shield painted with a rising sun."},
    {"key": "dragonborn-paladin", "title": "Dragonborn Paladin", "race": "Dragonborn", "class": "Paladin",
     "subclass": "Oath of Vengeance", "background": "Soldier", "alignment": "Lawful Neutral",
     "blurb": "An honour-bound champion sworn to hunt down a great evil, whatever it costs.",
     "appearance": "Plate armour etched with clan markings, a greatsword, scales like hammered bronze.",
     "weapons": {"weaponMartial": ["Greatsword"]}, "equipment": ["b", "a", "b"]},
]


def archetypes(sources=None) -> List[dict]:
    """The pre-made concepts whose race, class and subclass are all in the enabled books."""
    races = {r["name"] for r in rules.race_list(sources)}
    classes = {c["name"] for c in rules.class_list(sources)}
    return [a for a in ARCHETYPES if a["race"] in races and a["class"] in classes]


def archetype(key: str) -> Optional[dict]:
    return next((a for a in ARCHETYPES if a["key"] == key), None)


def archetype_options(key: str, **overrides) -> dict:
    """An archetype as generate() options; overrides (level, name, gender...) win."""
    a = archetype(key)
    if not a:
        raise RulesError(f"Unknown archetype '{key}'.")
    out = {k: v for k, v in a.items() if k not in ("key", "title", "blurb")}
    out.update({k: v for k, v in overrides.items() if v not in (None, "")})
    return out


# ---------------------------------------------------------------- names
_NAMES = {
    # family: (male first parts, female first parts, endings m, endings f, surname parts A, surname parts B)
    "dwarf": (["Thor", "Bal", "Dur", "Gim", "Bro", "Har", "Ror", "Thra", "Ulf", "Kaz", "Mor", "Dag"],
              ["Hel", "Dag", "Ama", "Bryn", "Gun", "Ilde", "Kat", "Ris", "Tor", "Vis", "Eld", "Sann"],
              ["in", "ek", "ak", "rim", "ur", "gar", "dun", "ni", "grim"], ["a", "hild", "ra", "dis", "wynn", "ja", "unn"],
              ["Iron", "Stone", "Battle", "Fire", "Gold", "Deep", "Oak", "Anvil", "Frost", "Granite"],
              ["fist", "beard", "hammer", "forge", "delve", "shield", "helm", "brow", "mantle"]),
    "elf": (["Aer", "Thal", "Ela", "Fae", "Gal", "Ilph", "Lue", "Syl", "Tae", "Var", "Ery", "Ael"],
            ["Ara", "Shan", "Lia", "Nai", "Sye", "Ilen", "Mia", "Thia", "Vala", "Eli", "Kea", "Ysol"],
            ["dan", "ion", "ras", "thor", "vian", "rel", "mir", "nis"], ["wyn", "lia", "rie", "nara", "thiel", "sa", "lee"],
            ["Moon", "Star", "Silver", "Leaf", "Dawn", "Wind", "Night", "Amber", "Mist"],
            ["whisper", "bloom", "song", "shade", "brook", "glade", "petal", "fall"]),
    "halfling": (["Mer", "Pip", "Cor", "Os", "Wel", "Rosc", "Fin", "Mil", "Tob", "Ned", "Bram"],
                 ["Rosi", "Ly", "Mer", "Cal", "Ver", "Bree", "Seraph", "Kith", "Tansy", "Poll", "Dai"],
                 ["ric", "in", "do", "by", "o", "bert", "wick"], ["e", "la", "ry", "na", "ie", "ra", "sy"],
                 ["Tea", "Under", "Brush", "Good", "High", "Green", "Tumble", "Thistle", "Apple"],
                 ["leaf", "hill", "gather", "barrel", "foot", "bottle", "bough", "wood"]),
    "gnome": (["Al", "Bod", "Fon", "Gim", "Orr", "Wren", "Zook", "Bim", "Dim", "Fizz", "Nack"],
              ["Bree", "Ella", "Lilli", "Nis", "Orla", "Zan", "Tana", "Rox", "Quil", "Wil"],
              ["ston", "kin", "dle", "bo", "wick", "ryn", "ble"], ["wyn", "ra", "bi", "na", "lie", "pip", "dy"],
              ["Copper", "Cog", "Spark", "Fiddle", "Tinker", "Bright", "Gear", "Whistle"],
              ["sprocket", "wick", "pocket", "nose", "bell", "spring", "fuse"]),
    "orc": (["Dench", "Gor", "Hol", "Kru", "Mhur", "Ront", "Thok", "Grum", "Ug", "Brak", "Dorn"],
            ["Bagh", "Emen", "Engo", "Kans", "Myev", "Neg", "Ovak", "Sutha", "Vola", "Yev", "Shau"],
            ["sh", "g", "ar", "uk", "ash", "rak", "ug"], ["a", "ga", "ra", "i", "ka", "ah"],
            ["Skull", "Blood", "Iron", "Bone", "Ash", "Red", "Broken"], ["splitter", "tusk", "fang", "maw", "hand", "eye"]),
    "dragonborn": (["Arj", "Bal", "Don", "Ghe", "Kriv", "Med", "Nad", "Pand", "Rhog", "Shed", "Tar", "Tor"],
                   ["Akra", "Bir", "Dar", "Far", "Hari", "Kava", "Kor", "Mis", "Nala", "Sor", "Thav", "Uad"],
                   ["han", "asar", "rash", "ar", "inn", "jed", "inx", "ash"], ["ann", "ideth", "ra", "ithra", "jit", "ys", "ira"],
                   ["Kerrh", "Myas", "Norix", "Ophin", "Shest", "Yarj", "Clethtinth", "Daar", "Delmir", "Kimbat"], [""]),
    "tiefling": (["Ak", "Ama", "Bar", "Dam", "Ek", "Ias", "Kal", "Leu", "Mor", "Pel", "Ska", "Zar"],
                 ["Akta", "Bry", "Cri", "Dam", "Ea", "Kal", "Lera", "Mak", "Nem", "Orian", "Ri", "Ze"],
                 ["menos", "akas", "ai", "akos", "mon", "cis", "thos", "zar"], ["seis", "ia", "ella", "aia", "nia", "ma", "ys"],
                 [], []),
    "human": (["Al", "Bran", "Cor", "Dar", "Ed", "Gar", "Hal", "Jor", "Mar", "Ran", "Ste", "Tom", "Wil", "Ad"],
              ["Ada", "Bri", "Cel", "Ela", "Ger", "Hel", "Isa", "Jes", "Mar", "Nan", "Ros", "Syl", "Tess", "Wen"],
              ["ric", "an", "ton", "en", "win", "mund", "ard", "vin", "o"], ["a", "ine", "da", "ra", "wyn", "ette", "lin"],
              ["Ash", "Black", "Bright", "Dun", "Fair", "Green", "Hawk", "Marsh", "Rook", "Stone", "Thorn", "Wood"],
              ["wood", "ford", "well", "wick", "more", "brook", "field", "ley", "son", "dale"]),
    "goblin": (["Snig", "Grik", "Nob", "Zat", "Krag", "Pug", "Skab", "Rikk"], ["Snee", "Grix", "Nib", "Zaz", "Kri", "Pip"],
               ["", "le", "nik", "gle"], ["", "a", "ka", "zy"], [], []),
}
_FAMILY = (("half-orc", "orc"), ("orc", "orc"), ("half-elf", "elf"), ("elf", "elf"), ("eladrin", "elf"), ("drow", "elf"),
           ("dwarf", "dwarf"), ("duergar", "dwarf"), ("halfling", "halfling"), ("gnome", "gnome"), ("dragonborn", "dragonborn"),
           ("tiefling", "tiefling"), ("goblin", "goblin"), ("kobold", "goblin"), ("hobgoblin", "orc"), ("bugbear", "orc"))
# (adult age, old age) by name family
_AGES = {"dwarf": (50, 200), "elf": (100, 500), "gnome": (40, 300), "halfling": (20, 110), "orc": (14, 50),
         "dragonborn": (15, 60), "human": (17, 60), "tiefling": (18, 70), "goblin": (8, 40)}


def name_family(race: str) -> str:
    r = (race or "").lower()
    for key, fam in _FAMILY:
        if key in r:
            return fam
    return "human"


def random_name(race: str, gender: str = "", rnd: Optional[random.Random] = None) -> str:
    """A fantasy name in the style of the race: 'Thorgrim Ironfist', 'Aerion Moonwhisper', 'Pip Underbarrel'."""
    rnd = rnd or random.Random()
    fam = name_family(race)
    if race and "half-elf" in race.lower():
        fam = rnd.choice(["elf", "human"])
    m_first, f_first, m_end, f_end, sur_a, sur_b = _NAMES[fam]
    female = gender == "female" or (gender not in ("male", "female") and rnd.random() < .5)
    first = rnd.choice(f_first if female else m_first) + rnd.choice(f_end if female else m_end)
    first = first[:1].upper() + first[1:]
    if not sur_a:
        return first
    return f"{first} {rnd.choice(sur_a)}{rnd.choice(sur_b)}"


# ---------------------------------------------------------------- picking helpers
def _ranked(pool, prefs) -> List[str]:
    """The pool with the preferred names first (in preference order), the rest after in their own order."""
    order: Dict[str, int] = {}
    for i, p in enumerate(prefs or []):
        order.setdefault(p.lower(), i)                          # a name listed twice keeps its better place
    pool = list(pool)
    return sorted(pool, key=lambda n: (order.get(book_name(_plain(n)), len(order)), pool.index(n)))


def _plain(n) -> str:
    return n.get("value") if isinstance(n, dict) else n


def _pick(pool, count: int, prefs=(), avoid=()) -> List[str]:
    avoid = {a.lower() for a in avoid}
    return [_plain(n) for n in _ranked(pool, prefs) if _plain(n).lower() not in avoid][:count]


def _profile(class_name: str) -> dict:
    """The class's usual build, for a class without one (another book's) made from its saves and spellcasting."""
    if class_name in PROFILES:
        return PROFILES[class_name]
    cls = rules.classes[class_name]
    casting = (cls.get("spellcasting") or {}).get("ability") if isinstance(cls.get("spellcasting"), dict) else None
    first = [casting] if casting in E.ABILITIES else []
    order = first + [a for a in cls["saves"] if a not in first] + ["con", "dex", "wis", "str", "int", "cha"]
    return {"abilities": " ".join(dict.fromkeys(order)), "background": "Sage" if casting else "Soldier", "alignment": "Neutral",
            "skills": [], "subclass": [], "equipment": [], "feats": ["War Caster"] if casting else []}


class _Build:
    """The decisions for one character: its options laid over the class profile."""

    def __init__(self, opts: dict, rnd: random.Random):
        self.o, self.rnd = opts, rnd
        self.cls = opts["class"]
        prof = dict(_profile(self.cls))
        for key in ("abilities", "background", "alignment", "skills", "expertise", "equipment", "feats", "fighting_style"):
            if opts.get(key):
                prof[key] = opts[key]
        self.p = prof
        order = prof["abilities"].split() if isinstance(prof["abilities"], str) else list(prof["abilities"])
        self.priority = list(dict.fromkeys(order + list(E.ABILITIES)))
        self.skill_prefs = list(prof.get("skills") or [])
        own = {rules.skill_name(x) for x in rules.classes[self.cls]["skills"]["choose"]}
        # race and background picks leave the class's own skills to the class (its list may be short)
        self.free_skill_prefs = [x for x in self.skill_prefs + USEFUL_SKILLS if x not in own] + self.skill_prefs
        self.weapons = {**TYPE_PREFS, **(opts.get("weapons") or {})}

    # ---- ability scores
    def scores(self) -> Dict[str, int]:
        """The standard array, highest score to the first ability of the priority list."""
        return {a: v for a, v in zip(self.priority, sorted(E.STANDARD_ARRAY, reverse=True))}

    def race_abilities(self, pick: dict, fixed: Dict[str, int]) -> List[str]:
        """Free racial increases: the best abilities that the race doesn't already raise."""
        pool = [a for a in self.priority if a in pick["from"]]
        pool = [a for a in pool if a not in fixed] + [a for a in pool if a in fixed]
        return pool[: pick["count"]]

    # ---- feats
    def feat(self, char: Character, extra=()) -> Optional[tuple]:
        """(name, choices) of the first preferred feat the character can take, or None."""
        for name in list(extra) + list(self.p.get("feats") or []) + GENERIC_FEATS:
            feat = rules.feats.get(name)
            if not feat:
                continue
            choices: dict = {}
            if name == "Resilient":
                choices["ability"] = next((a for a in ("con", "wis", "dex") if a not in char.d["proficiencies"]["saves"]), "cha")
            elif feat["ability"]["choose"]:
                choices["ability"] = next((a for a in self.priority if a in feat["ability"]["choose"]["from"]
                                           and char.ability_score(a) < E.MAX_ABILITY), feat["ability"]["choose"]["from"][0])
            trial = Character.from_dict(copy.deepcopy(char.d))
            try:
                apply_feat(trial, name, choices)
            except (RulesError, KeyError, ValueError, TypeError):
                continue
            return name, choices
        return None

    def asi(self, char: Character) -> dict:
        """+2 to the main ability (+1 and +1 to another while it is odd); a feat once it is 20."""
        score = {a: char.ability_score(a) for a in E.ABILITIES}
        first = self.priority[0]
        if score[first] <= E.MAX_ABILITY - 2 and score[first] % 2 == 0:
            return {"abilities": {first: 2}}
        if score[first] < E.MAX_ABILITY:
            other = next((a for a in self.priority[1:] if score[a] < E.MAX_ABILITY and score[a] % 2), None) or \
                next((a for a in self.priority[1:] if score[a] < E.MAX_ABILITY), None)
            if other:
                return {"abilities": {first: 1, other: 1}}
        feat = self.feat(char)
        if feat:
            return {"feat": feat[0], "feat_choices": feat[1]}
        for a in self.priority:
            if score[a] <= E.MAX_ABILITY - 2:
                return {"abilities": {a: 2}}
        a, b = [x for x in self.priority if score[x] < E.MAX_ABILITY][:2]
        return {"abilities": {a: 1, b: 1}}

    # ---- spells
    def spells(self, pool: List[str], count: int, max_level: int, schools=None) -> List[str]:
        """The best `count` spells to learn: the highest level on offer first, then by preference."""
        order = {p.lower(): i for i, p in enumerate(SPELL_PREFS)}
        def key(n):
            sp = rules.spell(n) or {"level": 0, "school": ""}
            return (bool(schools) and sp.get("school") not in schools, sp["level"] != max_level,
                    order.get(book_name(n), len(order)), -sp["level"], n)
        return sorted(pool, key=key)[:count]

    def prepared(self, pool: List[str], count: int) -> List[str]:
        """The best of each spell level in turn, highest level first, so every slot level has something to cast."""
        by_level: Dict[int, List[str]] = {}
        for n in _ranked(sorted(pool), SPELL_PREFS):
            by_level.setdefault((rules.spell(n) or {"level": 0})["level"], []).append(n)
        out: List[str] = []
        while len(out) < count and any(by_level.values()):
            for lvl in sorted(by_level, reverse=True):
                if by_level[lvl] and len(out) < count:
                    out.append(by_level[lvl].pop(0))
        return out


# ---------------------------------------------------------------- the level choices
def level_choices(char: Character, b: _Build, subclass: Optional[str]) -> dict:
    """Choices for the next level in b.cls, as apply_level_up takes them."""
    cls = b.cls
    plan = plan_level_up(char, cls, None)
    ch: dict = {"hp": "average"}
    if plan["subclass"]:
        options = plan["subclass"]["options"]
        sub = subclass if subclass in options else next((s for s in b.p.get("subclass") or [] if s in options), options[0])
        ch["subclass"] = sub
        plan = plan_level_up(char, cls, sub)
        grants = plan.get("subclass_grants") or {}
        picks = {}
        for key, spec in grants.items():
            if not isinstance(spec, dict) or spec.get("from") is None:
                continue
            prefs = b.skill_prefs if key in ("skills", "expertise_skills") else LANGUAGE_PREFS if key == "languages" \
                else CANTRIP_PREFS if key == "cantrip" else b.weapons.get("weaponMartial", [])
            picks[key] = _pick(spec["from"], spec["count"], prefs)
        ch["subclass_choices"] = picks
    granted = {n.lower() for v in (ch.get("subclass_choices") or {}).values() for n in v}
    new_skills: List[str] = []
    if plan["skills"]:
        new_skills = _pick(plan["skills"]["from"], plan["skills"]["count"], b.skill_prefs, granted)
        ch["skills"] = new_skills
    if plan["tools"] and plan["tools"]["count"]:
        ch["tools"] = _pick(plan["tools"]["from"], plan["tools"]["count"], b.weapons.get("instrumentMusical", []), granted)
    if plan["asi"]:
        ch["asi"] = b.asi(char)
    if plan["expertise"]:
        profs = char.d["proficiencies"]
        pool = [s for s in profs["skills"] + new_skills if s not in profs["expertise"]]
        if plan["expertise"]["tools"] and thieves_tools_open(profs):
            pool.append("Thieves' Tools")
        ch["expertise"] = _pick(pool, plan["expertise"]["count"], (b.p.get("expertise") or []) + b.skill_prefs)
    if plan["options"]:
        ch["options"] = {o["key"]: _pick(o["pool"], o["count"], (b.p.get("fighting_style") or []) + OPTION_PREFS)
                         for o in plan["options"]}
    sp = plan["spells"]
    if sp:
        if sp["cantrips"]:
            ch["cantrips"] = _pick(sp["cantrip_pool"], sp["cantrips"], CANTRIP_PREFS, granted)
        if sp["known"]:
            ch["spells"] = b.spells([n for n in sp["spell_pool"] if n.lower() not in granted], sp["known"],
                                    sp["max_spell_level"], sp["restricted_schools"])
        if sp["spellbook"]:
            ch["spellbook"] = b.spells(sp["spell_pool"], sp["spellbook"], sp["max_spell_level"])
        if sp["prepared"] is not None:
            always = set(sp.get("always_prepared") or [])
            if sp["spellbook"] is not None and (sp["spellbook"] or SC.class_spells(char, cls)["spellbook"]):
                pool = SC.class_spells(char, cls)["spellbook"] + ch.get("spellbook", [])
            else:
                pool = sp["spell_pool"]
            pool = [n for n in pool if n not in always and (rules.spell(n) or {"level": 99})["level"] <= sp["max_spell_level"]]
            ch["prepared"] = b.prepared(pool, sp["prepared"])
    return ch


def _level_up(char: Character, b: _Build, subclass: Optional[str]) -> None:
    """Gain a level with the build's choices, recorded so the level can be edited later. Should a choice not fit the
    rules (an option this module doesn't know), the level is made with the first valid option for everything instead."""
    ch = None
    try:
        ch = level_choices(char, b, subclass)
        apply_level_up(Character.from_dict(copy.deepcopy(char.d)), b.cls, ch)
    except (RulesError, KeyError, ValueError, TypeError, IndexError):
        trial = Character.from_dict(copy.deepcopy(char.d))
        ch = autolevel(trial, b.cls, subclass=(ch or {}).get("subclass") or subclass)
    char.snapshot_level(b.cls, ch)
    apply_level_up(char, b.cls, ch)


# ---------------------------------------------------------------- creation (level 1)
def _race_choices(char: Character, b: _Build, race: str, subrace: Optional[str]) -> dict:
    req = race_requirements(race, subrace)
    out: dict = {}
    data = rules.races[race]
    sub = next((s for s in data["subraces"] if s["name"] == subrace), None)
    if req["ability_choose"]:
        from .creation import racial_fixed
        out["ability"] = b.race_abilities(req["ability_choose"], racial_fixed(data, sub))
    if req["languages_any"]:
        from .creation import racial_languages
        have = racial_languages(data, sub)
        out["languages"] = _pick([l for l in rules.all_languages() if l not in have], req["languages_any"], LANGUAGE_PREFS)
    if req["skills_any"]:
        out["skills"] = _pick(SKILLS, req["skills_any"], b.free_skill_prefs)
    if req["tool"] and req["tool"]["from"]:
        out["tools"] = list(req["tool"]["from"][: req["tool"]["count"]])
    if req["cantrip_choice"]:
        out["cantrips"] = _pick(choose_pool("level=0|class=Wizard"), req["cantrip_choice"], CANTRIP_PREFS)
    if req["spell_ability"]:
        out["spell_ability"] = next((a for a in b.priority if a in req["spell_ability"]), req["spell_ability"][0])
    if req["feats"]:
        probe = Character.from_dict(copy.deepcopy(char.d))
        feat = b.feat(probe)
        if feat:
            out["feat"], out["feat_choices"] = feat
    return out


def _background_choices(char: Character, b: _Build, name: str) -> dict:
    req = background_requirements(name)
    bg = rules.backgrounds[name]
    profs = char.d["proficiencies"]
    fixed = [rules.skill_name(x) for x in bg.get("skills", {}).get("fixed", [])]
    wanted = req["skills_any"] + sum(1 for x in fixed if x in profs["skills"])
    out: dict = {}
    if wanted:
        out["skills"] = _pick([s for s in SKILLS if s not in profs["skills"] and s not in fixed], wanted,
                              b.free_skill_prefs)
    if req["tools_count"]:
        have = {t.lower() for t in profs["tools"]}
        out["tools"] = _pick([t for t in background_tool_pool(req) if t.lower() not in have], req["tools_count"],
                             ["Thieves' Tools", "Herbalism Kit", "Smith's Tools", "Lute"])
    if req["languages_any"]:
        out["languages"] = _pick([l for l in rules.all_languages() if l not in profs["languages"]], req["languages_any"],
                                 LANGUAGE_PREFS)
    return out


def _equipment(b: _Build, background: str) -> dict:
    """Starting equipment: the profile's option for each class group, preferred items for every 'any ...' slot."""
    return {"gold": None, "class": _equipment_picks(b, rules.classes[b.cls]["equipment"]["choices"], b.p.get("equipment")),
            "background": _equipment_picks(b, rules.backgrounds[background]["equipment"], ())}


def _equipment_picks(b: _Build, groups: List[dict], letters) -> List[dict]:
    letters = list(letters or [])
    picks = []
    i = 0
    for g in groups:
        if "fixed" in g:
            option, items = "a", g["fixed"]
        else:
            option = letters[i] if i < len(letters) and letters[i] in g else "a"
            i += 1
            items = g[option]
        chosen = []
        for it in items:
            if isinstance(it, dict) and it.get("type"):
                offer = type_options(it["type"])
                chosen.append(_pick(offer, 1, b.weapons.get(it["type"], []))[0] if offer else "")
        picks.append({"option": option, "picks": chosen})
    return picks


def _details(b: _Build, race: str, background: str, gender: str, level: int) -> dict:
    rnd = b.rnd
    traits = rules.backgrounds[background]["characteristics"] if background in rules.backgrounds else {}
    pick = lambda key: rnd.choice(traits[key]) if traits.get(key) else ""
    adult, old = _AGES.get(name_family(race), _AGES["human"])
    age = adult + int((old - adult) * min(.6, .05 + level * .025 + rnd.random() * .15))
    return {"personality": pick("personality"), "ideal": pick("ideal"), "bond": pick("bond"), "flaw": pick("flaw"),
            "gender": gender.capitalize(), "age": str(age), "appearance": b.o.get("appearance") or "",
            "backstory": b.o.get("backstory") or ""}


def _subrace(race: str, wanted: Optional[str], rnd: random.Random) -> Optional[str]:
    req = race_requirements(race)
    if wanted and wanted in req["subraces"]:
        return wanted
    if req["subrace_required"] and req["subraces"]:
        phb = [s for s in rules.races[race]["subraces"] if s["name"] in req["subraces"] and s.get("source", "PHB") == "PHB"]
        return (phb[0]["name"] if phb else req["subraces"][0])
    return None


def generate(opts: dict, sources=None) -> Character:
    """A finished character from the options (see the module help). Raises RulesError for a bad race, class or level."""
    race, cls = opts.get("race"), opts.get("class")
    if race not in rules.races:
        raise RulesError(f"Unknown race '{race}'.")
    if cls not in rules.classes:
        raise RulesError(f"Unknown class '{cls}'.")
    level = int(opts.get("level") or 1)
    if not 1 <= level <= E.MAX_LEVEL:
        raise RulesError(f"Level must be 1-{E.MAX_LEVEL}.")
    rnd = random.Random(opts.get("seed"))
    b = _Build(opts, rnd)
    gender = opts.get("gender") if opts.get("gender") in ("male", "female") else rnd.choice(["male", "female"])
    subrace = _subrace(race, opts.get("subrace"), rnd)
    req = race_requirements(race, subrace)
    ancestry = opts.get("ancestry") if opts.get("ancestry") in req["ancestries"] else \
        (rnd.choice(req["ancestries"]) if req["ancestries"] else None)
    background = opts.get("background") or b.p["background"]
    if background not in rules.backgrounds:
        background = next((x["name"] for x in rules.background_list()), background)
    alignment = opts.get("alignment") or b.p.get("alignment") or ""
    name = (opts.get("name") or "").strip() or random_name(race, gender, rnd)

    work = Character.create_blank(name)
    scores = b.scores()
    work.d["abilities"]["base"] = dict(scores)
    race_ch = _race_choices(work, b, race, subrace)
    apply_race(work, race, subrace, ancestry, race_ch)
    bg_ch = _background_choices(work, b, background)
    apply_background(work, background, bg_ch)
    spec = {"name": name, "alignment": alignment if alignment in E.ALIGNMENTS else "", "race": race, "subrace": subrace,
            "ancestry": ancestry, "race_choices": race_ch, "background": background, "background_choices": bg_ch,
            "scores_method": "standard_array", "scores": scores, "class": cls, "equipment": _equipment(b, background),
            "details": _details(b, race, background, gender, level)}
    try:
        spec["class_choices"] = level_choices(work, b, opts.get("subclass"))
        char = create_character(spec, sources)
    except RulesError:
        spec["class_choices"] = autolevel(Character.from_dict(copy.deepcopy(work.d)), cls, sources, opts.get("subclass"))
        char = create_character(spec, sources)
    for _ in range(level - 1):
        _level_up(char, b, opts.get("subclass"))
    char.current_hp = char.max_hp
    return char


def subclass_level(class_name: str) -> Optional[int]:
    """The class level at which the subclass is chosen (None for a class without one)."""
    levels = rules.classes[class_name]["subclass_levels"] if class_name in rules.classes else []
    return levels[0] if levels else None


def preview_text(char: Character) -> str:
    """The plain-text sheet with what was decided: background, saves, skills, feats, attacks, spells, gear, personality."""
    from . import sheet
    lines = [sheet.sheet_text(char).replace("**", ""), ""]
    sub = ", ".join(f"{c['name']}: {c['subclass']}" for c in char.classes if c.get("subclass"))
    lines.append(f"Background: {char.d.get('background') or '-'} · {char.alignment or 'no alignment'}" + (f" · {sub}" if sub else ""))
    lines.append("Saves: " + ", ".join(f"{a} {sheet.signed(b)}" for a, _s, _m, b, p in sheet.abilities(char) if p))
    lines.append("Skills: " + ", ".join(f"{n} {sheet.signed(b)}" + (" ◆" if m == "◆" else "")
                                        for n, _a, b, m in sheet.skills(char) if m != "○"))
    picks = char.d["feats"] + char.d["options"]
    if picks:
        lines.append("Feats & options: " + ", ".join(picks))
    attacks = char.attacks()
    if attacks:
        lines.append("Attacks: " + "; ".join(f"{a['name']} {sheet.signed(a['attack'])} ({a['damage']})" for a in attacks[:4]))
    for lvl, names in sorted(sheet.spells_by_level(char).items()):
        lines.append(("Cantrips" if lvl == 0 else f"{E.ordinal(lvl)} level") + ": " + ", ".join(names))
    gear = [e["name"] for e in char.inventory if e.get("equipped")]
    if gear:
        lines.append("Equipped: " + ", ".join(gear))
    d = char.details
    if d.get("personality"):
        lines += ["", f"Personality: {d['personality']}", f"Ideal: {d['ideal']}", f"Bond: {d['bond']}", f"Flaw: {d['flaw']}"]
    if d.get("appearance"):
        lines.append(f"Appearance: {d['appearance']}")
    return "\n".join(lines)


def summary(char: Character) -> str:
    """'Level 5 Mountain Dwarf Fighter (Champion): HP 49, AC 18' - a one-line description for previews."""
    ac = char.armor_class()[0]
    return f"Level {char.total_level} {char.race_display} {char.class_summary}: HP {char.max_hp}, AC {ac}"
