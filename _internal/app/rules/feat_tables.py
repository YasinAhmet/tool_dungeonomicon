"""Data for the feats that grant spells, resistances, speed, proficiencies and languages (rules/feat_extras.py applies it).

SPELLS     feat -> what spells it gives:
              ability   'pick' (the feat has no ability to raise: the form asks Int, Wis or Cha), 'choose' (the ability the feat raises
                        is the casting one), or a fixed ability
              fixed     [(spell, uses, character level needed)]: uses None = a cantrip, "1/long rest" = once free
              slots     True: "you can also cast it with spell slots": once the free cast is spent the spell is cast with a slot
              ritual    True: it can be cast as a ritual even by a non-caster
              cantrip   a cantrip to pick   pick  a leveled spell to pick   adept {slot level: [spells]}: always prepared once a slot of
                        that level exists (the Adept feats)
RESIST_PICKS / RESIST_FIXED / SPEED / GRANTS: see feat_extras.apply.
"""
from typing import Dict

ABILITY_PICK = ("int", "wis", "cha")
FREE = "1/long rest"

SPELLS: Dict[str, dict] = {
    # ---- Astarion's Book of Hungers
    "Cloying Mists": {"ability": "choose", "slots": True, "fixed": [("Fog Cloud", FREE, 1)]},
    "Treacherous Allure": {"ability": "choose", "slots": True, "fixed": [("Charm Person", FREE, 1)]},
    "Vampire Touched": {"ability": "choose", "slots": True, "fixed": [("Spider Climb", FREE, 1)],
                        "pick": {"label": "Choose a 1st-level enchantment or illusion spell", "schools": ("Enchantment", "Illusion"), "uses": FREE}},
    "Light Bringer": {"ability": "choose", "cantrip_fixed": "Light", "cantrip_alt": {"label": "You know Light: choose another cleric cantrip", "class": "Cleric"}},
    # ---- Heroes of Faerun
    "Cold Caster": {"ability": "choose", "cantrip_fixed": "Ray of Frost",
                    "cantrip_alt": {"label": "You know Ray of Frost: choose another wizard cantrip", "class": "Wizard"}},
    "Emerald Enclave Fledgling": {"ability": "pick", "ritual": True, "fixed": [("Speak with Animals", None, 1)]},
    "Enclave Magic": {"ability": "choose", "slots": True, "fixed": [("Beast Sense", FREE, 1)]},
    "Genie Magic": {"ability": "choose", "pick": {"label": "Wish Magic: choose a 1st-level sorcerer spell with a casting time of an action",
                                                   "class": "Sorcerer", "action": True, "uses": FREE}},
    "Spellfire Spark": {"ability": "pick", "fixed": [("Sacred Flame", None, 1)]},
    "Boon of Revelry": {"ability": "choose", "slots": True, "fixed": [("Otto's Irresistible Dance", FREE, 1)]},
    # ---- Lorwyn
    "Child of the Sun": {"ability": "pick", "slots": True, "fixed": [("Faerie Fire", FREE, 1)]},
    "Shadowmoor Hexer": {"ability": "pick", "slots": True, "fixed": [("Hex", FREE, 1)]},
    # ---- Eberron: the dragonmarks
    "Mark of Detection": {"ability": "pick", "slots": True, "fixed": [("Detect Magic", FREE, 1), ("Detect Poison and Disease", FREE, 1), ("See Invisibility", FREE, 3)]},
    "Mark of Finding": {"ability": "pick", "slots": True, "fixed": [("Hunter's Mark", FREE, 1), ("Locate Object", FREE, 3)]},
    "Mark of Handling": {"ability": "pick", "slots": True, "fixed": [("Animal Friendship", FREE, 1), ("Speak with Animals", FREE, 1)]},
    "Mark of Healing": {"ability": "pick", "slots": True, "fixed": [("Cure Wounds", FREE, 1), ("Lesser Restoration", FREE, 3)]},
    "Mark of Hospitality": {"ability": "pick", "slots": True, "fixed": [("Purify Food and Drink", FREE, 1), ("Unseen Servant", FREE, 1), ("Calm Emotions", FREE, 3)]},
    "Mark of Making": {"ability": "pick", "slots": True, "fixed": [("Mending", None, 1), ("Magic Weapon", FREE, 1)]},
    "Mark of Passage": {"ability": "pick", "slots": True, "fixed": [("Misty Step", FREE, 1)]},
    "Mark of Scribing": {"ability": "pick", "slots": True, "fixed": [("Message", None, 1), ("Comprehend Languages", FREE, 1), ("Magic Mouth", FREE, 3)]},
    "Mark of Sentinel": {"ability": "pick", "slots": True, "fixed": [("Shield", FREE, 1)]},
    "Mark of Shadow": {"ability": "pick", "slots": True, "fixed": [("Minor Illusion", None, 1), ("Invisibility", FREE, 1)]},
    "Mark of Storm": {"ability": "pick", "slots": True, "fixed": [("Thunderclap", None, 1), ("Gust of Wind", FREE, 3)]},
    "Mark of Warding": {"ability": "pick", "slots": True, "fixed": [("Alarm", FREE, 1), ("Mage Armor", FREE, 1), ("Arcane Lock", FREE, 3)]},
    "Boon of Siberys": {"ability": "pick", "slots": True, "pick_extra": True,
                        "pick": {"label": "Aberrant Magic: choose a spell of level 8 or lower from the sorcerer list, or one of the Siberys spells",
                                 "class": "Sorcerer", "max": 8, "uses": "1/short rest",
                                 "extra": ["Animal Shapes", "Control Weather", "Demiplane", "Heroes' Feast", "Maze", "Mind Blank", "Plane Shift",
                                           "Project Image", "Regenerate", "Symbol", "Teleport", "True Seeing"]}},
    # ---- Ravenloft: the Horrors Within
    "Gathered Whispers": {"ability": "pick", "slots": True, "fixed": [("Message", None, 1), ("Augury", FREE, 1)]},
    "Living Shadow": {"ability": "pick", "fixed": [("Mage Hand", None, 1)]},
    "Second Skin": {"ability": "pick", "slots": True, "fixed": [("Alter Self", FREE, 1)]},
    "Touch of Death": {"ability": "pick", "fixed": [("Chill Touch", None, 1)]},
    "Watchers": {"ability": "pick", "slots": True, "fixed": [("Beast Sense", FREE, 1), ("Speak with Animals", FREE, 1)]},
    # ---- Arcana Unleashed
    "Arcane Artist": {"ability": "pick", "fixed": [("Minor Illusion", None, 1)]},
    "Arcane Eloquence": {"ability": "pick", "fixed": [("Vicious Mockery", None, 1)]},
    "Arcane Infiltrator": {"ability": "pick", "fixed": [("Friends", None, 1)]},
    "Arcane Omens": {"ability": "pick", "fixed": [("Guidance", None, 1)]},
    "Arcane Overload": {"ability": "pick", "fixed": [("Fire Bolt", None, 1)]},
    "Arcane Safeguard": {"ability": "pick", "fixed": [("Resistance", None, 1)]},
    "Arcane Undertaker": {"ability": "pick", "cantrip": {"label": "Choose a necromancy cantrip from the cleric or wizard list", "class": ("Cleric", "Wizard"),
                                                         "schools": ("Necromancy",)}},
    "Arcane Warrior": {"ability": "pick", "cantrip": {"label": "Choose two wizard cantrips (Mage Hand and Ray of Frost are recommended)", "class": "Wizard", "count": 2}},
    "Familiar Friend": {"ability": "pick", "slots": True, "fixed": [("Find Familiar", FREE, 1)]},
    "Warlike Familiar": {"ability": "familiar", "slots": True, "fixed": [("Battle Familiar", FREE, 1)]},
    "Magic Connoisseur": {"ability": "connoisseur", "slots": True},
    "Boon of Magic School Mastery": {"ability": "choose", "school_mastery": True},
}

# the Adept feats: always prepared once the character has a slot of that level (the spell is cast with slots)
ADEPT = {
    "Abjuration Adept": {1: "Shield", 2: "Lesser Restoration", 3: "Protection from Energy", 4: "Banishment", 5: "Mass Cure Wounds"},
    "Conjuration Adept": {1: "Entangle", 2: "Misty Step", 3: "Conjure Animals", 4: "Dimension Door", 5: "Conjure Elemental"},
    "Divination Adept": {1: "Detect Evil and Good", 2: "Mind Spike", 3: "Clairvoyance", 4: "Divination", 5: "Scrying"},
    "Enchantment Adept": {1: "Dissonant Whispers", 2: "Enthrall", 3: "Hold Person", 4: "Dominate Beast", 5: "Modify Memory"},
    "Evocation Adept": {1: "Chromatic Orb", 2: "Shatter", 3: "Fireball", 4: "Vitriolic Sphere", 5: "Wall of Force"},
    "Illusion Adept": {1: "Silent Image", 2: "Phantasmal Force", 3: "Major Image", 4: "Hallucinatory Terrain", 5: "Seeming"},
    "Necromancy Adept": {1: "Inflict Wounds", 2: "Ray of Enfeeblement", 3: "Vampiric Touch", 4: "Blight", 5: "Raise Dead"},
    "Transmutation Adept": {1: "Jump", 2: "Spider Climb", 3: "Slow", 4: "Polymorph", 5: "Animate Objects"},
}

# Spells of the Mark: the spells Potent Dragonmark keeps prepared (spell level -> spells)
MARK_SPELLS = {
    "Mark of Detection": {1: ["Detect Evil and Good", "Identify"], 2: ["Detect Thoughts", "Find Traps"], 3: ["Clairvoyance", "Nondetection"],
                          4: ["Arcane Eye", "Divination"], 5: ["Legend Lore"]},
    "Mark of Finding": {1: ["Faerie Fire", "Longstrider"], 2: ["Locate Animals or Plants", "Mind Spike"], 3: ["Clairvoyance", "Speak with Plants"],
                        4: ["Divination", "Locate Creature"], 5: ["Commune with Nature"]},
    "Mark of Handling": {1: ["Command", "Find Familiar"], 2: ["Beast Sense", "Calm Emotions"], 3: ["Beacon of Hope", "Conjure Animals"],
                         4: ["Aura of Life", "Dominate Beast"], 5: ["Awaken"]},
    "Mark of Healing": {1: ["False Life", "Healing Word"], 2: ["Arcane Vigor", "Prayer of Healing"], 3: ["Aura of Vitality", "Mass Healing Word"],
                        4: ["Aura of Life", "Aura of Purity"], 5: ["Greater Restoration"]},
    "Mark of Hospitality": {1: ["Goodberry", "Sleep"], 2: ["Aid", "Enhance Ability"], 3: ["Create Food and Water", "Leomund's Tiny Hut"],
                            4: ["Aura of Purity", "Mordenkainen's Private Sanctum"], 5: ["Hallow"]},
    "Mark of Making": {1: ["Identify", "Tenser's Floating Disk"], 2: ["Continual Flame", "Spiritual Weapon"], 3: ["Conjure Barrage", "Elemental Weapon"],
                       4: ["Fabricate", "Stone Shape"], 5: ["Creation"]},
    "Mark of Passage": {1: ["Expeditious Retreat", "Jump"], 2: ["Find Steed", "Pass without Trace"], 3: ["Blink", "Phantom Steed"],
                        4: ["Dimension Door", "Freedom of Movement"], 5: ["Teleportation Circle"]},
    "Mark of Scribing": {1: ["Command", "Illusory Script"], 2: ["Animal Messenger", "Silence"], 3: ["Sending", "Tongues"],
                         4: ["Arcane Eye", "Confusion"], 5: ["Dream"]},
    "Mark of Sentinel": {1: ["Compelled Duel", "Shield of Faith"], 2: ["Warding Bond", "Zone of Truth"], 3: ["Counterspell", "Protection from Energy"],
                         4: ["Death Ward", "Guardian of Faith"], 5: ["Bigby's Hand"]},
    "Mark of Shadow": {1: ["Disguise Self", "Silent Image"], 2: ["Darkness", "Pass without Trace"], 3: ["Clairvoyance", "Major Image"],
                       4: ["Greater Invisibility", "Hallucinatory Terrain"], 5: ["Mislead"]},
    "Mark of Storm": {1: ["Feather Fall", "Fog Cloud"], 2: ["Levitate", "Shatter"], 3: ["Sleet Storm", "Wind Wall"],
                      4: ["Conjure Minor Elementals", "Control Water"], 5: ["Conjure Elemental"]},
    "Mark of Warding": {1: ["Armor of Agathys", "Sanctuary"], 2: ["Knock", "Nystul's Magic Aura"], 3: ["Glyph of Warding", "Magic Circle"],
                        4: ["Leomund's Secret Chest", "Mordenkainen's Faithful Hound"], 5: ["Antilife Shell"]},
}

# damage resistance the feat picks when it is taken
RESIST_PICKS = {"Dragonscarred": ("acid", "cold", "fire", "lightning", "poison"),
                "Portal Jumper": ("necrotic", "psychic", "radiant"),
                "Spell Resistant": ("necrotic", "psychic", "radiant", "thunder")}
# the damage type a familiar is imbued with (Find Familiar): picked with the feat
FAMILIAR_PICKS = {"Elemental Familiar": ("acid", "cold", "fire", "lightning", "thunder"),
                  "Otherworldly Familiar": ("necrotic", "poison", "psychic", "radiant", "thunder")}
RESIST_FIXED = {"Mark of Storm": ["lightning"], "Boon of the Soul Drinker": ["cold", "necrotic"], "Boon of the Furious Storm": ["lightning", "thunder"]}
SPEED = {"Mark of Passage": 5, "Transmuted Anatomy": 5}

MIND_SKILLS = ["Arcana", "Deception", "History", "Intimidation", "Insight", "Investigation", "Nature", "Religion", "Perception", "Persuasion"]
# proficiencies, expertise and languages a feat grants: expert = proficiency (if lacking) and expertise; skills_from = (pool, count);
# skills_any = any skills; expertise_pick = expertise in a skill you have; language_any = a language of your choice
GRANTS = {
    "Boon of Terror": {"expert": ["Intimidation"]},
    "Aberrant Anatomy": {"expert": ["Perception"]},
    "Harper Agent": {"languages_fixed": ["Thieves' Cant"], "instrument": 1},
    "Purple Dragon Rook": {"skills_from": (["Insight", "Performance", "Persuasion"], 1)},
    "Echoing Soul": {"skills_any": 2, "expertise_pick": 1, "language_any": 1},
    "Symbiotic Being": {"skills_from": (MIND_SKILLS, 1), "language_any": 1},
    "Cult of the Dragon Initiate": {"draconic": True},
    "Zhentarim Tactics": {"expertise_pick": 1},
}
