"""Magic items that aren't weapons, in a fight: wondrous items, rings, armour, shields (DMG chapter 7, Xanathar's,
Tasha's, Fizban's, the Book of Many Things...). Weapons are itempowers.py; potions, scrolls, wands and staffs' spells
are items.py; Tasha's wizard books and essence shards, a Jester's Mask, a Ring of Spell Storing and a few more one-offs are spellitems.py.

Worn (passives): what an item's text promises while it's equipped (and attuned when it needs it), read as effect-like
entries that profile._all_effects merges with the creature's own (`item_mods`):
    resistance, immunity and vulnerability (the curse of the Armor of Vulnerability) to damage types, condition
    immunities ("can't be charmed or frightened", Ring of Free Action), advantage on saves (an ability, against spells,
    to avoid a condition), darkvision (Goggles of Night add 60 ft to the one you have), truesight, blindsight, seeing
    the invisible (Robe of Eyes), a flying speed (Winged Boots: your walking speed), more speed, advantage on
    initiative, +N to ability checks (Stone of Good Luck), a base AC without armour (Robe of the Archmagi, the Barrier
    Tattoos), +AC against ranged attacks (Arrow-Catching Shield), spell attacks at disadvantage (Spellguard Shield),
    critical hits turned into normal hits (adamantine armour), Magic Missile doing nothing (Brooch of Shielding),
    attacks against you at disadvantage until you take damage (Cloak of Displacement: back at the start of your turn,
    off while incapacitated, restrained or grappled), stabilising at 0 hit points (Periapt of Wound Closure), advantage on
    death saves (Powered Armor) and hit points at the start of each turn while at half or fewer (Excalibur's scabbard), dropping
    to 1 hit point instead of 0 once a day (Lifewell Tattoo), advantage on one skill's checks (Cloak of Elvenkind:
    Stealth), advantage on saves against one thing (Dragon Scale Mail: a dragon's breath and Frightful Presence),
    flying in dim light (Cloak of the Bat), a walking speed of at least 30 (Boots of Striding and Springing).
Used (activations, on the action bar as "wonder:<item>|<key>", `activations`):
    a saving throw for one creature or everyone in an area, read from the item's text the way a stat block is (Horn of
    Blasting, Bead of Force, Wand of Paralysis, Pipes of Haunting, Gem of Brightness, the Book of Many Things' cards...),
    a spell attack or an attack roll (Ring of the Ram, Card Sharp's Deck, Tentacle Rod, Iron Bands of Bilarro), bolts
    that just hit (Crown of Whirling Comets), a Necklace of Fireballs' beads (a fireball, a level higher for each bead
    beyond the first), healing (Keoghtom's Ointment, a Platinum Scarf's scale), what an item switches on (BUFFS: Boots
    of Speed, Cloak and Ring of Invisibility, Wings of Flying, a Broom or Carpet of Flying, Armor of Invulnerability,
    Gem of Seeing, a Rod of Alertness's aura, the Fates and Star Cards, Dust of Disappearance...), a spent resource
    back (REGAIN: Pearl of Power, Rod of the Pact Keeper...; "regain one expended spell slot of 2nd level or lower", then the
    damage it costs: Atonement), creatures on the user's side (SUMMONS: Figurines of
    Wondrous Power, Bags of Tricks, Elemental Gems, Horns of Valhalla...) and the Eversmoking Bottle's cloud.
    What it costs comes from the text: charges (kept on the pack entry like a wand's), once until the next dawn (the
    sheet's resources, "item:<name>:<key>", cleared by a long rest), a few uses a day ("item:<name>:uses") or the item
    itself (a bead, a pinch of dust).
    Also: blinks (Kagonesti Forest Shroud, Nimbus Coronet, Amulet of the Black Skull), the Wand of Wonder's d100 table,
    a Staff of the Adder's bite, a Bracer of Flying Daggers' throws.
Reactions (ITEM_FAMILIES, asked through reactions.py like any other): Ring of Evasion, Scarab of Protection, Absorbing
    Tattoos, Shadowfell Brand Tattoo, Gloves of Missile Snaring, Guardian Emblem, Sapphire Buckler, Rod of Retribution,
    a Sword of Answering's riposte, Eberron's orbs of shielding, the Ioun stones of absorption; and, free after a weapon
    hit, charges poured into it (Staff of Striking, Staff of Power, Staff of Withering, Blood Fury Tattoo: `charge_hit`).
Spells cast through an Eberron imbued wood focus get +1 on one damage roll of its type (_wonder_strike_start).
The 2024-worded items of Arcana Unleashed, Eberron: Forge of the Artificer, Heroes of Faerun... ("a Magic action", "(4d8) Necrotic damage",
"a 30-foot Emanation") are read by the same code (USE_RE, HAS_ACTION, _clean, _area); what it can't read is itemmore.py's (`adjust`
merges its bar entries, `_more_eligible` / `_more_react` are its reactions: Dazzling weapons, a Repulsion Shield, Chattering skulls...).
Switched-on items are effects on the creature carrying the item's name in their mods (`wonder`).
"""
import re
from functools import lru_cache
from typing import List, Optional

from ...rules.data import rules
from ...rules.dice import roll_dice
from ..common import ServiceError
from . import combat_rules as CR
from . import conditions as K
from . import geometry as G
from . import sight as V
from . import itemmore as MORE
from . import weaponlore as LORE
from .itemmore import ItemMoreMixin

TYPES =["acid", "bludgeoning", "cold", "fire", "force", "lightning", "necrotic", "piercing", "poison", "psychic", "radiant",
         "slashing", "thunder"]
ABIL = {"strength": "str", "dexterity": "dex", "constitution": "con", "intelligence": "int", "wisdom": "wis", "charisma": "cha"}
CONDS = ["blinded", "charmed", "deafened", "frightened", "grappled", "incapacitated", "paralyzed", "petrified", "poisoned", "prone",
         "restrained", "stunned", "unconscious"]
COND_RX = "|".join(CONDS)
NUM = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "1": 1, "2": 2, "3": 3, "4": 4, "5": 5, "6": 6}

# a sentence that is about using the item, not about wearing it
ACTIVE = re.compile(r"\b(?:bonus action|magic action|an action|your action|as an action|reaction|expends?|spend|charges?|for (?:the next )?\d+ "
                    r"(?:minutes?|hours?|rounds?)|for 1 minute|until the (?:start|end)|cursed?\b|when you\b|whenever|if you (?:fail|take|would|are hit)"
                    r"|once (?:this|used)|polymorph|each creature|a creature|creatures? of your choice|for the duration)", re.I)
NOT_WORN = re.compile(r"^Deck of|Elemental Command$|^Dream Weaver$")     # a deck's cards act when drawn; a ring's extra powers need a slain elemental
SOMETIMES = re.compile(r"\b(?:inside|while in\b|in an environment|underwater|no gravity|dim light|darkness|in the area|on its roof|"
                       r"dealt by|caused by|breath weapon|the painted|the wearer's allies|made to swim|checks to climb)", re.I)   # only somewhere, or not the wearer


def _clean(text: str) -> str:
    """Item text without 5etools tags: '{@spell fireball}' -> 'fireball', '{@variantrule Cover|XPHB|half cover}' -> 'half cover'."""
    def tag(m):
        bits = m.group(1).split("|")
        return bits[2] if len(bits) > 2 and bits[2] else bits[0]
    text = re.sub(r"\{@\w+ ([^}]+)\}", tag, text or "").replace("{#itemEntry ", "").replace("’", "'")
    return re.sub(r"\((\d+d\d+(?: ?[+-] ?\d+)?)\)", r"\1", text)     # 2024 stat style: "(4d8) Necrotic damage" -> "4d8 Necrotic damage"


def _types(words: str) -> List[str]:
    if re.search(r"\ball\b", words) and "all but" not in words:
        return list(TYPES)
    return [t for t in TYPES if re.search(r"\b%s\b" % t, words)]


def _conds(words: str) -> List[str]:
    return [c.capitalize() for c in CONDS if re.search(r"\b%s\w*" % c[:-2], words)]


def _paragraphs(text: str) -> List[tuple]:
    """[(paragraph, intro)]: the item's text in paragraphs and bullets; `intro` is the activation a bullet hangs under
    ("you can use an action to speak one of three command words to cause one of the following effects:", "For the
    duration, you gain the following benefits:"), None for the others."""
    out, under = [], None
    for p in re.split(r"\n+|\s*•\s*", _clean(text)):
        p = p.strip()
        if not p or "|" in p:                               # tables (a Deck of Wonder's cards): never the wearer's own
            continue
        if under is not None and re.match(r"[A-Z][\w' ]{0,40}\.\s", p) and not re.search(r"one of the following|following effects", under):
            under = None                                    # a new titled property: the list is over (not a Platinum Scarf's choices)
        out.append((p, under))
        if p.rstrip().endswith(":"):
            last = re.split(r"(?<=[.!])\s+", p)[-1]
            under = p if ACTIVE.search(last) else None
    return out


@lru_cache(maxsize=None)
def _mods_of(name: str) -> tuple:
    item = rules.item(name)
    return tuple(sorted(item_mods(item).items())) if item else ()


def item_mods(item: Optional[dict]) -> dict:
    """What wearing the item gives, as effect mods (the battle's keys, modifiers.py) plus a few of this module's own:
    'fly_walk' (a flying speed equal to the walking speed), 'fly_dim', 'speed_floor', 'darkvision_plus', 'ac_unarmored'
    (base, Dex cap), 'ranged_ac', 'spell_against', 'no_crit', 'displacement', 'auto_stable', 'life_ward',
    'immune_spell', 'save_adv_vs' ({'labels', 'type'}), 'skill_adv' (skills)."""
    if not item or NOT_WORN.search(item["name"]):
        return {}
    text = _clean(item.get("text"))
    low = text.lower()
    mods: dict = {}

    def add(key, vals):
        cur = mods.setdefault(key, [])
        cur += [v for v in vals if v not in cur]

    if "critical hit against you becomes a normal hit" in low:
        mods["no_crit"] = True
    if re.search(r"(?m)^[^|\n]*you have advantage on death saving throws", low):
        mods["dsave_adv"] = True                           # Excalibur's scabbard, Powered Armor (not a table's row)
    m = re.search(r"at the start of each of your turns,? you regain (\d+) hit points if you have no more than half of your hit points left", low)
    if m:
        mods["regen_low"] = int(m.group(1))                # (weaponlore._lore_turn_start)
    if "magical effect that allows you to make a strength or constitution saving throw to take only half damage, you instead take no damage" in low:
        mods["half_none"] = ["str", "con"]                 # Mizzium armour: evasion for Strength and Constitution saves against magic
    if re.search(r"causing any creature to have disadvantage on attack rolls against you", low):
        mods["displacement"] = True
    if "you stabilize whenever you are dying" in low or "magically stabilizes you with a touch" in low:     # Ghost Lantern too
        mods["auto_stable"] = True
    if re.search(r"when you would be reduced to 0 hit points, you drop to 1 hit point instead", low):
        mods["life_ward"] = True
    m = re.search(r"immunity to damage from the ([\w' ]+?) spell", low)
    if m:
        mods["immune_spell"] = [m.group(1).strip()]
    if re.search(r"advantage on saving throws against the frightful presence and breath weapons of dragons", low):
        mods["save_adv_vs"] = {"labels": ["frightful presence", "breath"], "type": "dragon"}     # Dragon Scale Mail
    if re.search(r"you ignore (?:half )?cover when making a spell attack", low):
        mods["spell_ignore_cover"] = True                  # Wand of the War Mage
    if "advantage on saving throws made against harmful gases and vapors" in low:          # Necklace of Adaptation
        mods["save_adv_vs"] = {"labels": ["cloudkill", "stinking cloud", "poison breath", "incendiary cloud"]}
    m = re.search(r"in an area of dim light or darkness, you can grip the edges of the cloak with both hands and use it to fly at a speed of (\d+) feet", low)
    if m:
        mods["fly_dim"] = int(m.group(1))                  # Cloak of the Bat
    m = re.search(r"your walking speed becomes (\d+) feet, unless your walking speed is higher", low)
    if m:
        mods["speed_floor"] = int(m.group(1))              # Boots of Striding and Springing
    m = re.search(r"(?:while cursed,? |curse[^.]*?)you have vulnerability to ([a-z ,]+?) damage", low)
    if m and item.get("attune") is not None:
        add("vuln", _types(m.group(1)))
    if item.get("curse") and item.get("attune") is not None and "your speed is halved" in low:
        mods["speed_mult"] = .5                            # the Shield of the Tortoise's curse
    m = re.search(r"(?:you're|you are) (?:also )?vulnerable to (\w+) damage", low)
    if m and item.get("attune") is not None and m.group(1) in TYPES:
        add("vuln", [m.group(1)])                          # a Canian Fork's curse: radiant
    m = re.search(r"your unarmed strikes? deals? an additional (\d+d\d+) (\w+) damage on a hit", low)
    if m:
        mods["dmg"] = (m.group(1), m.group(2))             # Wyrmreaver Gauntlets: +1d6 force on unarmed strikes only
        mods["unarmed_only"] = True
    for para, intro in _paragraphs(text):
        if intro is not None:
            continue
        for s in re.split(r"(?<=[.!])\s+", para):
            sl = s.lower()
            m = re.search(r"if you aren't wearing armor, your base armor class is (\d+) \+ your dexterity modifier", sl)
            if m:
                mods["ac_unarmored"] = (int(m.group(1)), None)
            m = re.search(r"while you aren't wearing armor, the tattoo grants you an armor class of (\d+)(?: \+ your dexterity (?:modifier|bonus)"
                          r"( \(maximum of \+2\))?)?", sl)
            if m:
                mods["ac_unarmored"] = (int(m.group(1)), 2 if m.group(2) else None if "dexterity" in sl else 0)
            m = re.search(r"\+(\d) bonus to ac against ranged attacks", sl)
            if m:
                mods["ranged_ac"] = int(m.group(1))
            if re.search(r"spell attacks (?:have disadvantage against you|against you have disadvantage)", sl):
                mods["spell_against"] = "dis"
            if ACTIVE.search(s) or SOMETIMES.search(s) or not re.search(r"\byou\b|\byour\b|\b(?:its|the) (?:intended )?(?:wearer|wielder|bearer)\b", sl):
                continue                                   # (Mind Carapace: "To its intended wearer, the armor grants...")
            sl = re.sub(r"\b(?:makes |grants )?(?:its|the) (?:intended )?(?:wearer|wielder|bearer)\b", "you", sl)    # the wearer is you
            m = re.search(r"\byou (?:have|gain) resistance to ([a-z ,]+?) damage( from nonmagical attacks)?\b(?! from)", sl)
            if m and not re.search(r"resistance to damage from", sl):
                if m.group(2) or "nonmagical" in m.group(1):
                    add("resist", ["nonmagical"])
                else:
                    add("resist", _types(m.group(1)))
            for m in re.finditer(r"\b(?:you are|you're|you have|and have|and are) (?:immune|immunity) to ([a-z ,]+?) damage\b", sl):
                add("immune", _types(m.group(1)) or (["nonmagical"] if "nonmagical" in m.group(1) else []))
            for m in re.finditer(r"immun(?:e|ity) to (?:the )?((?:%s)(?:(?:,| or| and)+ (?:the )?(?:%s))*)(?: conditions?)?" % (COND_RX, COND_RX), sl):
                add("immune_cond", _conds(m.group(1)))
            for m in re.finditer(r"\byou can't be ((?:%s)(?:(?:,| or)+ (?:%s))*)" % (COND_RX, COND_RX), sl):
                add("immune_cond", _conds(m.group(1)))
            m = re.search(r"(?:cause you to be|can't make you) ((?:%s)(?: or (?:%s))*)" % (COND_RX, COND_RX), sl)
            if m:
                add("immune_cond", _conds(m.group(1)))
            for m in re.finditer(r"advantage on ((?:strength|dexterity|constitution|intelligence|wisdom|charisma)"
                                 r"(?:(?:,| and| or)+ (?:strength|dexterity|constitution|intelligence|wisdom|charisma))*) saving throws", sl):
                add("save_adv", [ABIL[a] for a in ABIL if a in m.group(1)])
            if re.search(r"advantage on (?:all )?saving throws against (?:any )?spells?\b", sl):
                add("save_adv", ["spells"])
            m = re.search(r"advantage on saving throws (?:you make )?(?:to avoid or end|to avoid being|against being|against) ([a-z ,]+?)(?: conditions?)?"
                          r"(?: on yourself)?(?:\.|$| and| or to| while)", sl)
            if m and _conds(m.group(1)):
                add("cond_save_adv", _conds(m.group(1)))
            m = re.search(r"advantage on saving throws against poison", sl)
            if m:
                add("cond_save_adv", ["Poisoned"])
            m = re.search(r"darkvision (?:out )?(?:to a range of|with a range of|within a range of|to|of) (\d+) feet", sl)
            if m:
                mods.setdefault("senses", {})["darkvision"] = int(m.group(1))
                if re.search(r"increases (?:its|your darkvision's) range by", low):
                    mods["darkvision_plus"] = int(m.group(1))
            for sense in ("truesight", "blindsight", "tremorsense"):
                m = re.search(r"\b%s (?:out )?(?:to a range of |with a range of |within a range of |to |of )?(\d+) feet" % sense, sl)
                if m:
                    mods.setdefault("senses", {})[sense] = int(m.group(1))
            if re.search(r"you can see invisible creatures", sl):
                mods.setdefault("senses", {})["see_invisible"] = True
            if re.search(r"flying speed equal to your walking speed", sl):
                mods["fly_walk"] = True
            m = re.search(r"you have a (?:flying|fly) speed of (\d+) feet", sl)
            if m:
                mods["fly"] = int(m.group(1))
            m = re.search(r"your (?:walking )?speed increases by (\d+) feet", sl)
            if m:
                mods["speed"] = int(m.group(1))
            if re.search(r"advantage on (?:initiative rolls|rolls for initiative|[\w ()]+ and on rolls for initiative|initiative rolls and)", sl):
                mods["init_adv"] = True
            m = re.search(r"\+(\d) bonus to ability checks", sl)
            if m:
                mods["check"] = m.group(1)
            for m in re.finditer(r"(?<!dis)advantage on ([^.;]*?checks)", sl):     # Stealth (Cloak of Elvenkind), Perception (Sentinel Shield)
                add("skill_adv", [s.title().replace(" Of ", " of ") for s in re.findall(r"\(([a-z ]+)\)", m.group(1))])
    if re.search(r"Advantage on Charisma \(Intimidation\) checks made while holding the staff", text):
        mods["skill_adv"] = list(mods.get("skill_adv") or []) + ["Intimidation"]     # a Staff of Skulls (AU): its glow sits in the same sentence
    if item.get("resist"):                                  # the item's own list already counts (profile._defenses)
        rest = [t for t in mods.get("resist") or [] if t not in item["resist"]]
        if rest:
            mods["resist"] = rest
        else:
            mods.pop("resist", None)
    if item.get("bonus_ac_ranged"):
        mods["ranged_ac"] = int(item["bonus_ac_ranged"])
    return {k: v for k, v in mods.items() if v not in ([], {}, None)}


# ---------------------------------------------------------------------- activations
# items whose use switches something on (or off): {name pattern: spec}
#   cost, mods / conds (on the user, or `who` 'ally' / 'area'), rounds, ends_on, toggle (the same again turns it off;
#   off_cost), limit 'daily' | ('charges', n) | 'consume', worn (must be equipped), until 'start' (of the user's next turn)
BUFFS = [
    (r"^Boots of Speed$", {"key": "heels", "name": "Click heels", "cost": "bonus", "mods": {"speed_mult": 2, "oa_against": "dis"},
                           "toggle": True, "worn": True, "tip": "Double walking speed; opportunity attacks against you have disadvantage."}),
    (r"^Cloak of Invisibility$", {"key": "hood", "name": "Hood up / down", "cost": "action", "conds": ["Invisible"], "toggle": True, "worn": True,
                                  "tip": "Invisible while the hood is up (up to 2 hours a day)."}),
    (r"^Ring of Invisibility$", {"key": "vanish", "name": "Turn invisible", "cost": "action", "conds": ["Invisible"], "ends_on": ["attack", "cast"],
                                 "toggle": True, "off_cost": "bonus", "worn": True,
                                 "tip": "Invisible until you attack or cast a spell (a bonus action makes you visible again)."}),
    (r"^Wings of Flying$", {"key": "wings", "name": "Wings", "cost": "action", "mods": {"fly": 60}, "rounds": 600, "toggle": True, "worn": True,
                            "limit": "daily", "tip": "Flying speed 60 ft for an hour; afterwards not again for 1d12 hours."}),
    (r"^Armor of Invulnerability$", {"key": "invulnerable", "name": "Invulnerability", "cost": "action", "mods": {"immune": ["nonmagical"]},
                                     "rounds": 100, "limit": "daily", "worn": True,
                                     "tip": "Immune to nonmagical damage for 10 minutes. Once a day."}),
    (r"^Gem of Seeing$", {"key": "truesight", "name": "Truesight", "cost": "action", "mods": {"senses": {"truesight": 120}}, "rounds": 100,
                          "limit": ("charges", 1), "tip": "Truesight out to 120 ft for 10 minutes (1 charge)."}),
    (r"^Ring of Puzzler's Wit$", {"key": "wit", "name": "Puzzler's Wit", "cost": "free", "mods": {"check_adv": ["int"], "once": True}, "rounds": 10,
                                  "limit": ("charges", 1), "worn": True,
                                  "tip": "Advantage on your next Intelligence check (1 charge)."}),
    (r"^Rod of Alertness$", {"key": "aura", "name": "Protective aura", "cost": "action", "mods": {"ac": 1, "save": "1", "aura_ft": 60},
                             "rounds": 100, "limit": "daily", "tip": "You and friendly creatures within 60 ft: +1 AC and saving throws for 10 minutes. Once a day."}),
    (r"^Fates Card$", {"key": "fates", "name": "Glimpse of the future", "cost": "bonus", "who": "ally", "range": 30, "until": "start",
                       "mods": {"attacks_with": "adv", "check_adv": True, "save_adv": ["all"], "attacks_against": "dis"}, "limit": "daily",
                       "tip": "A willing creature within 30 ft: advantage on attacks, checks and saves, attacks against it at disadvantage, "
                              "until the start of your next turn. Once a day."}),
    (r"^Dust of Disappearance$", {"key": "dust", "name": "Throw the dust", "cost": "action", "who": "area", "size": 10, "conds": ["Invisible"],
                                  "ends_on": ["attack", "cast"], "rounds": "2d4*10", "limit": "consume",
                                  "tip": "You and everyone within 10 ft turn invisible for 2d4 minutes (until they attack or cast a spell)."}),
    (r"^Ghost Step Tattoo$", {"key": "ghost", "name": "Ghostly form", "cost": "bonus", "until": "end",
                              "mods": {"resist": ["nonmagical"], "immune_cond": ["Grappled", "Restrained"], "incorporeal": True},
                              "limit": ("charges", 1), "tip": "Incorporeal until the end of your next turn: resistance to nonmagical "
                                                              "weapon damage, can't be grappled or restrained (1 charge)."}),
    (r"^Eldritch Claw Tattoo$", {"key": "maul", "name": "Eldritch Maul", "cost": "bonus", "mods": {"dmg": ("1d6", "force"), "melee_only": True},
                                 "rounds": 10, "limit": "daily", "tip": "For 1 minute your melee attacks deal an extra 1d6 force damage. Once a day."}),
    (r"^(?:Amethyst Lodestone|Crown of Whirling Comets)$", {"key": "flight", "name": "Flight", "cost": "bonus", "mods": {"fly_walk": True},
                                                            "rounds": 100, "limit": ("charges", 1),
                                                            "tip": "A flying speed equal to your walking speed for 10 minutes (1 charge)."}),
    (r"^Moon Card$", {"key": "moon", "name": "Wolflike form", "cost": "action", "rounds": 10, "limit": "daily",
                      "mods": {"resist": ["bludgeoning", "piercing", "slashing"], "dmg": ("1d6", "force")},
                      "tip": "For 1 minute: resistance to bludgeoning, piercing and slashing damage, +1d6 force on weapon hits. Once a day."}),
    (r"^Gauntlets of Flaming Fury$", {"key": "fury", "name": "Flaming weapons", "cost": "bonus", "mods": {"dmg": ("1d6", "fire"), "melee_only": True},
                                      "limit": "daily", "worn": True, "tip": "Your melee weapons burst into flame: +1d6 fire on a hit. Once a day."}),
    (r"^Wingwear$", {"key": "glide", "name": "Glide", "cost": "bonus", "mods": {"fly": 30}, "toggle": True, "limit": ("charges", 1), "worn": True,
                     "tip": "A flying speed of 30 ft until you land (1 charge)."}),
    (r"^Pixie Dust$", {"key": "sprinkle", "name": "Sprinkle", "cost": "action", "who": "ally", "range": 5, "mods": {"fly": 30}, "rounds": 10,
                       "limit": "consume", "tip": "You or a creature within 5 ft: a flying speed of 30 ft (hover) for 1 minute."}),
    (r"^Ring of Red Fury$", {"key": "rage", "name": "Ruidium rage", "cost": "bonus", "rounds": 10, "limit": "daily", "worn": True,
                             "mods": {"save_adv": ["str"], "skill_adv": ["Athletics"], "dmg": ("PB", ""), "immune_cond": ["Paralyzed", "Restrained"]},
                             "tip": "1 minute: advantage on Strength checks and saves, + proficiency bonus to damage, immune to paralyzed and restrained."}),
    (r"^Cape of Enlargement$", {"key": "enlarge", "name": "Enlarge", "cost": "bonus", "rounds": 100, "limit": ("charges", 1), "worn": True,
                                "mods": {"save_adv": ["str"], "skill_adv": ["Athletics"], "dmg": ("PB", "")},
                                "tip": "10 minutes: advantage on Strength checks and saves, + proficiency bonus to weapon damage (1 charge)."}),
    (r"^Lantern of Revealing$", {"key": "light", "name": "Light / hood", "cost": "action", "mods": {"reveal_ft": 30}, "toggle": True,
                                 "tip": "While lit: invisible creatures within 30 ft (its bright light) can be seen."}),
    (r"^Devotee's Censer$", {"key": "incense", "name": "Incense", "cost": "bonus", "rounds": 10, "limit": "daily",
                             "mods": {"regen": "1d4", "aura_ft": 10},
                             "tip": "A cloud of incense 10 ft round you for 1 minute: you and the creatures in it regain 1d4 HP each turn. Once a day."}),
    (r"^Vanquisher's Banner$", {"key": "rally", "name": "Rally an ally", "cost": "bonus", "who": "ally", "range": 60, "rounds": 100,
                                "mods": {"attacks_with": "adv", "once": True}, "tip": "An ally has advantage on its next attack roll."}),
    (r"^Star Card$", {"key": "star", "name": "Hold the card aloft", "cost": "bonus", "mods": {"save_adv": ["all"]}, "rounds": 100, "limit": "daily",
                      "tip": "Advantage on all saving throws for 10 minutes. Once a day."}),
    (r"^(?:Broom|Carpet) of Flying", {"key": "ride", "name": "Fly", "cost": "action", "mods": {"fly": "TEXT"}, "toggle": True,
                                      "tip": "Ride it through the air (its flying speed); land to stop."}),
    (r"^Helm of Brilliance$", {"key": "blaze", "name": "Flaming weapon", "cost": "action", "mods": {"dmg": ("1d6", "fire")}, "toggle": True,
                               "off_cost": "bonus", "worn": True, "tip": "Your weapon bursts into flames: +1d6 fire on its hits (a fire opal must be left)."}),
    (r"^Plate Armor of Etherealness$", {"key": "ethereal", "name": "Etherealness", "cost": "action", "mods": {"untargetable": True, "incorporeal": True},
                                        "rounds": 100, "toggle": True, "worn": True, "limit": "daily",
                                        "tip": "On the Ethereal Plane for 10 minutes (out of reach, through walls). Once a day."}),
    (r"^Robe of Scintillating Colors$", {"key": "dazzle", "name": "Dazzling hues", "cost": "action", "until": "end", "worn": True,
                                         "mods": {"attacks_against": "dis"}, "limit": ("charges", 1),
                                         "tip": "Until the end of your next turn creatures that can see you have disadvantage on attacks against you (1 charge)."}),
]
for _kind in ("Aberration", "Beast", "Celestial", "Elemental", "Fey", "Fiend", "Plant", "Undead"):      # the DMG's scrolls of protection: 5 minutes
    BUFFS.append((rf"^Scroll of Protection from {_kind}s?$", {"key": "barrier", "name": "Read the scroll", "cost": "action", "limit": "consume",
                                                              "mods": {"barrier_kinds": [_kind.lower()]}, "rounds": 50,
                                                              "tip": f"A barrier round you for 5 minutes: {_kind.lower()}s can't make attacks against you. The scroll crumbles."}))

# items that win back a spent class resource (an action, once a day): {name pattern: spec} with `regain`
#   'slot3' (Pearl of Power: one spent slot, a 3rd-level one at most), 'pact' (one warlock slot), or (resource, amount | 'martial')
REGAIN = [
    (r"^Pearl of Power$", {"key": "pearl", "name": "Regain a spell slot", "regain": "slot3", "tip": "Regain one spent spell slot (up to 3rd level)."}),
    (r"Rod of the Pact Keeper$", {"key": "pact", "name": "Regain a warlock slot", "regain": "pact", "tip": "Regain one spent warlock spell slot."}),
    (r"Rhythm-Maker's Drum$", {"key": "drum", "name": "Regain Bardic Inspiration", "regain": ("Bardic Inspiration", 1),
                               "tip": "Regain one use of Bardic Inspiration."}),
    (r"Dragonhide Belt$", {"key": "ki", "name": "Regain ki", "regain": ("Ki Points", "martial"), "tip": "Regain ki points equal to a roll of your Martial Arts die."}),
]
# items that bring creatures (friendly, on the user's side, right after it in the order): {name pattern: (monster ids, count, limit)}
SUMMONS = [
    (r"Bronze Griffon$", (["Griffon|MM"], 1, "daily")), (r"Ebony Fly$", (["Giant Fly|DMG"], 1, "daily")),
    (r"Golden Lions$", (["Lion|MM"], 2, "daily")), (r"Ivory Goats$", (["Giant Goat|MM"], 1, "daily")),
    (r"Marble Elephant$", (["Elephant|MM"], 1, "daily")), (r"Obsidian Steed$", (["Nightmare|MM"], 1, "daily")),
    (r"Onyx Dog$", (["Mastiff|MM"], 1, "daily")), (r"Serpentine Owl$", (["Giant Owl|MM"], 1, "daily")), (r"Silver Raven$", (["Raven|MM"], 1, "daily")),
    (r"^Bag of Tricks, Gray$", (["Weasel|MM", "Giant Rat|MM", "Badger|MM", "Boar|MM", "Panther|MM", "Giant Badger|MM", "Dire Wolf|MM", "Giant Elk|MM"], 1, ("uses", 3))),
    (r"^Bag of Tricks, Rust$", (["Rat|MM", "Owl|MM", "Mastiff|MM", "Goat|MM", "Giant Goat|MM", "Giant Boar|MM", "Lion|MM", "Brown Bear|MM"], 1, ("uses", 3))),
    (r"^Bag of Tricks, Tan$", (["Jackal|MM", "Ape|MM", "Baboon|MM", "Axe Beak|MM", "Black Bear|MM", "Giant Weasel|MM", "Giant Hyena|MM", "Tiger|MM"], 1, ("uses", 3))),
    (r"^Elemental Gem, Blue Sapphire$", (["Air Elemental|MM"], 1, "consume")), (r"^Elemental Gem, Emerald$", (["Water Elemental|MM"], 1, "consume")),
    (r"^Elemental Gem, Red Corundum$", (["Fire Elemental|MM"], 1, "consume")), (r"^Elemental Gem, Yellow Diamond$", (["Earth Elemental|MM"], 1, "consume")),
    (r"^Censer of Controlling Air Elementals$", (["Air Elemental|MM"], 1, "daily")), (r"^Bowl of Commanding Water Elementals$", (["Water Elemental|MM"], 1, "daily")),
    (r"^Brazier of Commanding Fire Elementals$", (["Fire Elemental|MM"], 1, "daily")), (r"^Stone of Controlling Earth Elementals$", (["Earth Elemental|MM"], 1, "daily")),
    (r"^Horn of Valhalla, Silver$", (["Berserker|MM"], "2d4+2", "daily")), (r"^Horn of Valhalla, Brass$", (["Berserker|MM"], "3d4+3", "daily")),
    (r"^Horn of Valhalla, Bronze$", (["Berserker|MM"], "4d4+4", "daily")), (r"^Horn of Valhalla, Iron$", (["Berserker|MM"], "5d4+5", "daily")),
    (r"^Ring of Djinni Summoning$", (["Djinni|MM"], 1, "daily")), (r"^Plate of Knight's Fellowship$", (["Knight|MM"], 1, "daily", "bonus")),
    (r"^Staff of the Python$", (["Giant Constrictor Snake|MM"], 1, None)), (r"^Knight Card$", (["Deck Defender|BMT"], 1, "daily")),
    (r"^Gold Canary Figurine of Wondrous Power$", (["Giant Canary|FTD"], 1, "daily")),
    (r"Carnelian Triceratops$", (["Triceratops|MM"], 1, "daily")), (r"Jasper Tyrannosaurus Rex$", (["Tyrannosaurus Rex|MM"], 1, "daily")),
    (r"Kyanite Pteranodon$", (["Pteranodon|MM"], 1, "daily")), (r"Pyrite Plesiosaurus$", (["Plesiosaurus|MM"], 1, "daily")),
    (r"^Feather of Diatryma Summoning$", (["Diatryma|WDH"], 1, "daily")),
    (r"^Efreeti Bottle$", (["Efreeti|MM"], 1, "daily")),          # 01-10 on a d100: it attacks its freer instead
    (r"^Azorius Keyrune$", (["Giant Eagle|MM"], 1, "daily")), (r"^Boros Keyrune$", (["Veteran|MM"], 1, "daily")),
    (r"^Dimir Keyrune$", (["Intellect Devourer|MM"], 1, "daily")), (r"^Golgari Keyrune$", (["Giant Scorpion|MM"], 1, "daily")),
    (r"^Gruul Keyrune$", (["Rhinoceros|MM"], 1, "daily")), (r"^Izzet Keyrune$", (["Galvanice Weird|GGR"], 1, "daily")),
    (r"^Orzhov Keyrune$", (["Winged Thrull|GGR"], 1, "daily")), (r"^Rakdos Keyrune$", (["Cackler|GGR"], 1, "daily")),
    (r"^Selesnya Keyrune$", (["Dire Wolf|MM"], 1, "daily")), (r"^Simic Keyrune$", (["Category 1 Krasis|GGR"], 1, "daily")),
    (r"^Orc Stone$", (["Orc War Chief|MM"], 1, "daily")), (r"^Robe of Serpents$", (["Giant Poisonous Snake|MM"], 1, ("beads",), "bonus")),
]
SUMMONS.extend(MORE.SUMMONS)                                   # a Fork of Eddy Summoning, a Magen Handbell, Pipes of Pestilence... (itemmore.py)

CHARGES_RE = re.compile(r"(?:expends?|spend|using) (\d+|one|two|three|four|five|a|1 to \d|any number of|1 or more)(?: of (?:its|the [\w' ]+?'s|their))? "
                        r"(?:\d+ )?charges?", re.I)
DAILY_RE = re.compile(r"can't (?:be used|use this (?:property|action|bonus action)|cast \w+ (?:spell )?)?\s*(?:again )?until the next (?:dawn|dusk|sunset)"
                      r"|(?:once|1) (?:per|a) day|until the next dawn", re.I)
CONSUME_RE = re.compile(r"(?:is|are) (?:then )?(?:destroyed|consumed)|enough of it for one use|enough dust in each packet for one use|dust is consumed|the bead explodes|"
                        r"if you dump the bag's contents|single-use effect", re.I)
USE_RE = re.compile(r"(?:as an action|use an action|use your action|as a bonus action|use a bonus action|take a bonus action|"
                    r"can,? as an action|an action to|bonus action to|if you dump|magic action)", re.I)     # (2024 wording: "a Magic action")
HAS_ACTION = re.compile(r"\b(?:as an?|use an?|use your|take an?) (?:magic )?action\b|\bmagic action\b")


def _title(p: str) -> tuple:
    """('Petrifying Heraldry', rest) from a property paragraph that starts with its name."""
    m = re.match(r"([A-Z][\w']*(?: [A-Z\w'][\w']*){0,4})\.?\s+(?=(?:As|While|You|If|When|The|This|Once|Choose)\b)", p)
    if m and len(m.group(1).split()) <= 5 and m.group(1).split()[0] not in ("As", "While", "You", "If", "When", "The", "This"):
        return m.group(1), p[m.end():]
    return "", p


def _area(low: str) -> Optional[dict]:
    m = re.search(r"(\d+)-foot cone", low)
    if m:
        return {"shape": "cone", "size": int(m.group(1)), "origin": "caster"}
    m = re.search(r"(\d+)-foot line that is (\d+) feet wide", low) or re.search(r"line (\d+) feet long and (\d+) feet wide", low)
    if m:
        return {"shape": "line", "size": int(m.group(1)), "width": int(m.group(2)), "origin": "caster"}
    m = re.search(r"line that is (\d+) feet wide and (\d+) feet long", low)
    if m:
        return {"shape": "line", "size": int(m.group(2)), "width": int(m.group(1)), "origin": "caster"}
    m = re.search(r"(\d+)-foot[- ]radius sphere centered on (?:yourself|you)\b", low)
    if m:
        return {"shape": "emanation", "size": int(m.group(1)), "origin": "caster"}
    m = re.search(r"(\d+)-foot[- ]radius sphere centered on (?:a|that|the) point", low) or re.search(r"within a (\d+)-foot radius of where", low) \
        or re.search(r"(\d+)-foot[- ]radius (?:sphere|cylinder)", low)
    if m:
        if re.search(r"each creature of your choice within a \d+-foot radius of where", low):    # Gungnir: only the foes where it lands
            return {"shape": "sphere", "size": int(m.group(1)), "origin": "point", "choice": True}
        return {"shape": "sphere", "size": int(m.group(1)), "origin": "point"}
    m = re.search(r"(\d+)-foot cube originating from (?:that|a|the) point", low)
    if m:
        return {"shape": "cube", "size": int(m.group(1)), "origin": "point"}
    m = re.search(r"(\d+)-foot cube that extends out from you", low)
    if m:                                                  # Dust of Corrosion
        return {"shape": "cube", "size": int(m.group(1)), "origin": "caster"}
    m = re.search(r"(\d+)-foot emanation", low)
    if m:                                                  # 2024 wording: "a 30-foot Emanation originating from you"
        return {"shape": "emanation", "size": int(m.group(1)), "origin": "caster", "choice": "of your choice" in low}
    m = re.search(r"each creature (?:of your choice )?(?:you can see )?(?:that [\w ]+? )?within (\d+) feet of you", low) or \
        re.search(r"explode in a (\d+)-foot radius", low) or re.search(r"vampire spawn within (\d+) feet of the holy symbol", low)
    if m:
        return {"shape": "emanation", "size": int(m.group(1)), "origin": "caster", "choice": "your choice" in low or "aren't hostile" in low}
    return None


def _limit(chunk: str, whole: str, n_props: int) -> object:
    m = CHARGES_RE.search(chunk)
    if m:
        g = m.group(1).lower()
        if g.startswith("1 to") or g in ("any number of", "1 or more"):
            hi = int(g[-1]) if g.startswith("1 to") else 0
            return ("charges", 1, hi or 99)
        return ("charges", NUM.get(g, 1))
    m = re.search(r"once (two|three|four|five|\d) \w+ have been (?:pulled|used|removed|taken)", whole, re.I) or \
        re.search(r"this property can be used (two|three|four|five|\d) times", chunk, re.I)
    if m:
        return ("uses", NUM.get(m.group(1).lower(), 3))      # a Platinum Scarf: three scales a day, whichever power
    if DAILY_RE.search(chunk) or (n_props == 1 and DAILY_RE.search(whole)) or \
            re.search(r"when one of these properties is used, it can't be used again until the next dawn", whole, re.I):
        return "daily"
    if CONSUME_RE.search(chunk) or CONSUME_RE.search(whole) and (n_props == 1 or "single-use" in whole):
        return "consume"
    return None


def lim_is_range(lim) -> bool:
    """A price of '1 to 3 charges' (the user picks how many)."""
    return isinstance(lim, tuple) and len(lim) == 3


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")[:24] or "use"


@lru_cache(maxsize=None)
def _acts_of(name: str) -> tuple:
    return tuple(activations(rules.item(name)))


def activations(item: Optional[dict]) -> List[dict]:
    """What using the item does: [{'key', 'name', 'cost', 'kind' ('save'|'attack'|'buff'|'fireball'|...), 'target' (aiming
    spec for the bar), 'range', 'limit', 'tip', ...}]: what the text says (_base_activations), then itemmore.adjust's."""
    base = _base_activations(item)
    if not item or not item.get("magic") or item.get("type") in ("P", "SC", "A", "AF"):
        return base
    return MORE.adjust(item, base)


def _base_activations(item: Optional[dict]) -> List[dict]:
    scroll_of_protection = str((item or {}).get("name")).startswith("Scroll of Protection from")
    if not item or (item.get("type") in ("P", "SC", "A", "AF") and not scroll_of_protection) or not item.get("magic"):
        return []
    if item.get("weapon"):
        from .itempowers import activations as weapon_powers
        if weapon_powers(item):                            # a Mace of Terror's wave: the weapon's own (itempowers.py)
            return []
    out = []
    for rx, spec in BUFFS:
        if re.search(rx, item["name"]):
            spec = dict(spec, kind="buff")
            if (spec.get("mods") or {}).get("fly") == "TEXT":     # a carpet's speed is on it: 80 ft for the smallest
                m = re.search(r"(?:fly|flying) speed of (\d+) feet", item.get("text") or "")
                spec["mods"] = dict(spec["mods"], fly=int(m.group(1)) if m else 30)
            out.append(spec)
    for rx, spec in REGAIN:
        if re.search(rx, item["name"]):
            out.append(dict(spec, kind="regain", cost="action", limit="daily", target={"type": "self"}))
    if item["name"] == "Wand of Wonder":                    # a d100 roll on its table decides what comes out
        out.append({"key": "wonder", "name": "Wave the wand", "kind": "wand_of_wonder", "cost": "action", "limit": ("charges", 1), "range": 120,
                    "target": {"type": "creature", "count": 1, "enemies": True},
                    "tip": "Choose a creature (or point) within 120 ft and roll d100: Slow, Faerie Fire, Lightning Bolt, Fireball, Stinking Cloud, "
                           "Darkness, a blinding burst, a petrifying ray... or something harmless. 1 charge."})
    if item["name"] == "Staff of the Adder":                 # the head turned into a snake: a bite
        out.append({"key": "bite", "name": "Snake head", "kind": "attack", "cost": "action", "ability": "str", "bonus": None, "melee": True,
                    "parts": [["1d6", "piercing"]], "spell": False, "weapon": True, "range": 5, "limit": None,
                    "rider": {"ab": "con", "dc": 15, "parts": [["3d6", "poison"]], "half": False},
                    "target": {"type": "creature", "count": 1, "enemies": True},
                    "tip": "A melee attack with the snake head: 1d6 piercing, then DC 15 Con save or 3d6 poison."})
    if item["name"] == "Gnomengarde Grenade":               # thrown and gone off: fire, then thunder and stun, 60 ft round
        out.append({"key": "throw", "name": "Throw the grenade", "kind": "bomb", "cost": "action", "limit": "consume", "range": 120,
                    "blasts": [{"ab": "dex", "dc": 15, "parts": [["8d6", "fire"]]},
                               {"ab": "con", "dc": 15, "parts": [["8d6", "thunder"]], "conds": ["Stunned"], "until": "target_end_next"}],
                    "target": {"type": "self_area", "aim": True, "area": {"shape": "sphere", "size": 60, "origin": "point"}},
                    "tip": "Everyone within 60 ft of where it lands: DC 15 Dex (8d6 fire) and DC 15 Con (8d6 thunder, stunned)."})
    if item["name"] in ("Smokepowder", "Smokepowder (Keg)", "Keg of Smokepowder"):
        dice = "9d6" if "keg" in item["name"].lower() else "1d6"
        out.append({"key": "throw", "name": "Throw it into a fire", "kind": "bomb", "cost": "action", "limit": "consume", "range": 60,
                    "blasts": [{"ab": "dex", "dc": 12, "parts": [[dice, "fire"]]}],
                    "target": {"type": "self_area", "aim": True, "area": {"shape": "sphere", "size": 20, "origin": "point"}},
                    "tip": f"It explodes: {dice} fire to everyone within 20 ft (DC 12 Dex halves)."})
    if item["name"] == "Cube of Force":                     # a 15-ft barrier round you; the face decides what it stops
        out.append({"key": "face", "name": "Press a face", "kind": "cube", "cost": "action", "limit": None, "target": {"type": "self"},
                    "options": [{"value": "2", "label": "2: stops arrows and other objects (2 charges)"},
                                {"value": "3", "label": "3: stops living creatures (3 charges)"},
                                {"value": "4", "label": "4: stops spells (4 charges)"},
                                {"value": "5", "label": "5: stops everything (5 charges)"}, {"value": "6", "label": "6: switch it off"}],
                    "tip": "A barrier of force round you for 1 minute: what can't get through depends on the face pressed."})
    if item["name"] == "Mirror of Life Trapping":            # hung beside you: whoever sees it within 30 ft
        out.append({"key": "trap", "name": "Activate the mirror", "kind": "save", "cost": "action", "limit": None, "range": None,
                    "sv": {"ab": "cha", "dc": 15, "half": False, "conds": ["Incapacitated"], "mods": {"banished": True, "untargetable": True},
                           "rounds": 14400}, "parts": [], "self_too": False,
                    "area": {"shape": "emanation", "size": 30, "origin": "caster"},
                    "target": {"type": "self_area", "aim": False, "area": {"shape": "emanation", "size": 30, "origin": "caster"}},
                    "tip": "Every other creature within 30 ft that sees the mirror: DC 15 Cha save or trapped in it."})
    if item["name"] == "Sphere of Annihilation":             # placed by the DM's word, then steered with Arcana checks
        out.append({"key": "steer", "name": "Control the sphere", "kind": "sphere", "cost": "action", "limit": None, "range": 60,
                    "target": {"type": "point"}, "tip": "DC 25 Arcana: it floats 5 x your Int modifier ft where you point (on a failure it "
                                                       "drifts 10 ft toward you). A creature whose space it enters: DC 13 Dex or 4d10 force."})
    if item["name"] == "Talons Card":
        out.append({"key": "talons", "name": "Suppress magic items", "kind": "talons", "cost": "action", "limit": "daily", "range": 120,
                    "target": {"type": "creature", "count": 1, "enemies": True},
                    "tip": "A creature within 120 ft: what its worn magic items give is suppressed for 1 minute. Once a day."})
    if item["name"] == "Gem Card":                          # the 6th-level spell the DM stored in it
        six = sorted(s["name"] for s in rules.spells.values() if s.get("level") == 6 and (s.get("damage") or s.get("save")))
        out.append({"key": "gem", "name": "Cast the stored spell", "kind": "gem", "cost": "action", "limit": "daily", "range": 120,
                    "target": {"type": "creature", "count": 1, "enemies": True}, "options": [{"value": n, "label": n} for n in six],
                    "tip": "Cast its 6th-level spell (spell attack +9, save DC 17). Once a day."})
    if item["name"] == "Spindle of Fate":                   # Doom Foretold: +1d6 on your damage to the doomed creature
        out.append({"key": "doom", "name": "Doom Foretold", "kind": "doom", "cost": "action", "limit": ("charges", 2), "range": 30,
                    "target": {"type": "creature", "count": 1, "enemies": True},
                    "tip": "A creature within 30 ft is doomed for 1 hour: once a turn your hit on it deals 1d6 more. 2 charges."})
    if item["name"] == "Illusionist's Bracers":             # the cantrip cast with this turn's action, once more as a bonus action
        out.append({"key": "again", "name": "Cantrip again", "kind": "recast", "cost": "bonus", "limit": None, "worn": True,
                    "target": {"type": "creature", "count": 1, "enemies": True},
                    "tip": "After casting a cantrip with your action: cast that cantrip a second time as a bonus action."})
    if re.search(r"cast either a green-flamed fireball or a blue lightning bolt at random", item.get("text") or ""):
        out.append({"key": "blast", "name": "Fire it", "kind": "random_spell", "cost": "action", "limit": ("charges", 1, 9), "range": 150,
                    "spells": ["Fireball", "Lightning Bolt"], "dc": 15, "level": 3, "target": {"type": "creature", "count": 1, "enemies": True},
                    "tip": "A fireball or a lightning bolt at random (DC 15), level 3 + 1 for each charge beyond the first."})
    if item["name"] == "Puzzle Card":
        out.append({"key": "puzzle", "name": "Disable traps", "kind": "puzzle", "cost": "action", "limit": "daily", "target": {"type": "self"},
                    "tip": "Every trap within 60 ft that isn't behind cover is disabled. Once a day."})
    if item["name"] == "Clockwork Amulet":
        out.append({"key": "tick", "name": "Take a 10", "kind": "buff", "cost": "free", "limit": "daily", "mods": {"roll_10": True, "once": True},
                    "rounds": 10, "target": {"type": "self"}, "tip": "Your next attack roll counts the d20 as a 10. Once a day."})
    if re.match(r"Clockwork (?:Plate|Splint|Half Plate|Breastplate|Chain Mail|Scale Mail|Ring Mail|Studded Leather|Leather|Hide|Padded) ?(?:Armor)?\b",
                item["name"]) and re.search(r"change the number rolled to a 10", item.get("text") or ""):    # BMT's Mechanus armor
        out.append({"key": "tick", "name": "Take a 10", "kind": "buff", "cost": "free", "limit": ("charges", 1), "mods": {"roll_10": True, "once": True},
                    "rounds": 10, "target": {"type": "self"}, "tip": "Your next attack roll counts the d20 as a 10 (1 charge)."})
    if item["name"] == "Flames Card":                       # a devil bound to the card (CR 8 or lower)
        out.append({"key": "summon", "name": "Summon the devil", "kind": "summon", "cost": "action", "limit": "daily", "count": 1, "range": 30,
                    "monsters": ["Bearded Devil|MM", "Barbed Devil|MM", "Chain Devil|MM"], "target": {"type": "point"},
                    "tip": "A devil (CR 8 or lower) that obeys you while you hold the card, for 1 minute. Once a day."})
    if item["name"] == "Bracer of Flying Daggers":          # two magic daggers hurled at once (a ranged attack each)
        out.append({"key": "daggers", "name": "Hurl daggers", "kind": "attack", "cost": "action", "ability": "dex", "bonus": None, "n": 2,
                    "parts": [["1d4+DEX", "piercing"]], "spell": False, "weapon": True, "range": 60, "limit": None,
                    "target": {"type": "creature", "count": 1, "enemies": True}, "tip": "Two dagger throws (1d4 + Dex piercing each, 20/60 ft)."})
    if item["name"] == "Eversmoking Bottle":                # a lasting cloud round the bottle: heavily obscured
        out.append({"key": "smoke", "name": "Open / close", "kind": "zone", "cost": "action", "zone": {"obscure": "heavy", "parts": []}, "size": 60,
                    "target": {"type": "self"}, "limit": None, "tip": "Thick smoke pours out in a 60-foot radius (heavily obscured) until closed."})
    for rx, (mids, count, lim, *how) in SUMMONS:
        if re.search(rx, item["name"]):
            many = len(mids) > 1
            out.append({"key": "summon", "name": "Summon", "kind": "summon", "cost": how[0] if how else "action", "monsters": mids, "count": count,
                        "limit": lim, "worn": bool(re.search(r"^Ring|^Plate", item["name"])),
                        "target": {"type": "point"} if not many else {"type": "self"}, "range": 60 if not many else 20,
                        "tip": ("A random creature (d8): " if many else "") + ", ".join(m.split("|")[0] for m in mids)
                               + (f" ×{count}" if count != 1 else "") + ", friendly, acting right after you."})
            return out
    whole = _clean(item.get("text"))
    if re.search(r"detonates as a (\d)(?:st|nd|rd|th)-level fireball spell", whole):
        lv = int(re.search(r"detonates as a (\d)", whole).group(1))
        dc = re.search(r"save DC (\d+)", whole)
        out.append({"key": "bead", "name": "Throw a bead", "cost": "action", "kind": "fireball", "level": lv, "dc": int(dc.group(1)) if dc else 15,
                    "range": 60, "limit": ("beads",), "target": {"type": "self_area", "aim": True, "area": {"shape": "sphere", "size": 20, "origin": "point"}},
                    "tip": f"A bead bursts as a level {lv} fireball (DC {int(dc.group(1)) if dc else 15}); more beads at once raise its level."})
        return out
    paras = _paragraphs(whole)
    props = [(k, p, intro) for k, (p, intro) in enumerate(paras) if intro is not None or USE_RE.search(p)]
    last_sv = None
    for k, p, intro in props:
        title, body = _title(p)
        low = body.lower()
        nxt = next((j for j, _p, _i in props if j > k), len(paras))
        tail = " ".join(x for x, _i in paras[k + 1:nxt]).lower()     # the paragraphs that go on about it (Iron Bands: the attack)
        how = (intro or body).lower()                      # a bullet under "use an action to ... one of the following": that action
        if re.search(r"\bcast(?:s|ing)?\b", low) and not re.search(r"DC \d+ \w+ saving throw", body):
            continue                                       # a spell from the item: items.item_spells / the wand list
        if re.search(r"\bwhen you hit\b|\bon a hit with (?:this|the) weapon", low):
            continue                                       # what a weapon does on a hit: itempowers.py
        cost = "bonus" if re.search(r"bonus action", how) and not HAS_ACTION.search(how) else "action"
        if re.search(r"use your reaction|as a reaction|take a reaction", how) and not HAS_ACTION.search(how) and "bonus action" not in how:
            continue
        limit = _limit(body, whole, len(props))
        _pre, post, save = CR.split_save(body)
        if not save and last_sv and re.search(r"as if struck by|the same saving throw", low):
            save, post = last_sv
        area = _area(low)
        rng = re.search(r"(?:within|up to|range of) (\d+) feet", low)
        single = re.search(r"\b(?:one|a|at one|at a) (?:willing )?(?:creature|dragon|humanoid|fiend|undead|beast) (?:that )?(?:you can see )?"
                           r"within (\d+) feet", low) or \
            re.search(r"toward a creature you can see within (\d+) feet", low)
        nm = title or item["name"].split(",")[0]
        key = _slug(title or "use")
        if any(a["key"] == key for a in out):
            key = f"{key}{len(out) + 1}"
        hop = re.search(r"(?:teleport|transport yourself)[^.]*?(?:within|up to) (\d+) feet", low)
        if hop and not save:                               # Kagonesti Forest Shroud, Nimbus Coronet, Amulet of the Black Skull: a blink
            out.append({"key": key, "name": nm if title else "Teleport", "cost": cost, "kind": "teleport", "range": int(hop.group(1)),
                        "adv_after": bool(re.search(r"advantage on the (?:next|first) (?:melee )?attack", low)), "limit": limit,
                        "target": {"type": "point", "teleport": int(hop.group(1))}, "tip": body[:300]})
            continue
        slot = re.search(r"regain one expended spell slot of (\d)(?:st|nd|rd|th) level or lower", low)
        if slot and not save:                              # Atonement's Arcane Fever (Legends Reforged): a slot back, then the price in damage
            hurt = re.search(r"you then take (\d+d\d+) (\w+) damage", low)
            out.append({"key": key, "name": nm, "cost": cost, "kind": "regain", "regain": f"slot{slot.group(1)}", "limit": limit or "daily",
                        "self_damage": [[hurt.group(1), hurt.group(2)]] if hurt else [], "target": {"type": "self"}, "tip": body[:300]})
            continue
        from .spellitems import more_activations              # a Dragon Vessel's potion, a Veteran's Cane, a Talisman's fissure
        extra = more_activations(body, cost, limit, key, nm)
        if extra:
            out.append(extra)
            continue
        heal = re.search(r"regains? (\d+d\d+(?: ?\+ ?\d+)?) hit points", body)
        if heal and not save and "at the start of each of your turns" not in low:     # Keoghtom's Ointment: a dose you or another takes
            out.append({"key": key, "name": nm, "cost": cost, "kind": "heal", "dice": heal.group(1).replace(" ", ""),
                        "cure": ["Poisoned"] if "ceases to be poisoned" in low else [], "who": "touch", "range": 5,
                        "target": {"type": "creature", "count": 1, "allies": True}, "unit": "dose",
                        "limit": ("beads",) if re.search(r"\d+d\d+ \+ \d+ doses", whole) else limit, "tip": body[:300]})
            continue
        both = low + " " + tail
        bands = re.search(r"make a (ranged|melee) attack roll (?:against the target, )?with (?:an attack bonus equal to your (dexterity) modifier|"
                          r"a bonus equal to your (spellcasting) modifier[^.]*?) plus your proficiency bonus", both)
        if bands:                                          # Iron Bands of Bilarro, a Wand of Viscid Globs: what they hit is held fast
            hit = re.search(r"on a hit,? [^.]*\.", both[bands.end():])
            hit = hit.group(0) if hit else ""
            out.append({"key": key, "name": nm, "cost": cost, "kind": "attack", "melee": bands.group(1) == "melee", "bonus": None,
                        "ability": "dex" if bands.group(2) else "spell", "on_hit_rounds": CR.duration_rounds(hit),
                        "parts": [list(x) for x in CR.damage_parts(hit)], "spell": False, "on_hit": CR.conditions_in(hit),
                        "target": {"type": "creature", "count": 1, "enemies": True}, "range": int(rng.group(1)) if rng else 60, "limit": limit,
                        "tip": body[:300]})
            continue
        roll = re.search(r"makes? an? (melee|ranged) attack roll with a \+(\d+) bonus", low)
        if roll and (not save or roll.start() < low.find(post.lower()[:20])):
            parts = CR.damage_parts(low[roll.start():roll.start() + 200])
            many = re.search(r"\b(two|three|four) (?:\w+ )?(?:tentacles|rays|bolts|arms)\b", whole.lower())
            if parts:                                      # a Tentacle Rod: its tentacles' attacks (what all three hitting adds is left out)
                out.append({"key": key, "name": nm, "cost": cost, "kind": "attack", "melee": roll.group(1) == "melee", "bonus": int(roll.group(2)),
                            "n": NUM.get(many.group(1), 1) if many else 1, "parts": [list(x) for x in parts[:1]], "per_charge": False, "spell": False,
                            "target": {"type": "creature", "count": 1, "enemies": True}, "range": int(rng.group(1)) if rng else 5,
                            "limit": limit, "tip": body[:300]})
                continue
        if save:
            post = " ".join(s for s in re.split(r"(?<=\.)\s+", post) if not re.search(r"\binstead of\b|glass or crystal", s))
            terms = _save_terms(post)
            parts = CR.save_damage(post) or CR.damage_parts(body)
            push = re.search(r"pushed (?:up to )?(\d+) feet", post.lower())
            banish = re.search(r"\b(?:it vanishes|is banished|be banished|be trapped in)\b", post.lower())
            if banish:                                     # the Donjon Card, an Iron Flask: gone for a while (incapacitated, out of reach)
                terms = dict(terms, conds=["Incapacitated"], mods={"banished": True, "untargetable": True},
                             rounds=14400 if "until released" in low else CR.duration_rounds(post) or 10, repeat=None)
            if re.search(r"has disadvantage on all saving throws", post.lower()):        # the Fool Card
                terms = dict(terms, mods=dict(terms.get("mods") or {}, save_dis=["all"]), rounds=terms.get("rounds") or CR.duration_rounds(post) or 10)
            if re.search(r"gain vulnerability to all damage types", post.lower()):     # Claw of the Wyrm Rune's Wyrmslayer
                terms = dict(terms, mods={"vuln": list(TYPES)}, until=terms.get("until") or "caster_end_next")
            if re.search(r"turns? to stone", post.lower()):   # restrained now, stone after a second failed save (as a gaze)
                terms = dict(terms, conds=["Restrained"], repeat="end", rounds=None, until=None, mods={"stoning": True}, fail5=[])
            if not parts and not terms["conds"] and not terms["mods"] and not push and not terms["drop_to_0"]:
                continue
            last_sv = (save, post)
            sv = {"ab": save[0], "dc": save[1], "half": "half as much" in post.lower(), **terms}
            if push:
                sv["push"] = int(push.group(1))
            if lim_is_range(limit):
                limit = ("charges", 1)                     # one burst a use (a Ring of Shooting Stars' motes one at a time)
            if area:
                if area["origin"] == "point":
                    tgt = {"type": "self_area", "aim": True, "area": area}
                else:
                    tgt = {"type": "self_area", "aim": area["shape"] != "emanation", "area": area}
                r = int(rng.group(1)) if rng and area["origin"] == "point" else None
            elif single:
                tgt, r = {"type": "creature", "count": 1, "enemies": True}, int(single.group(1))
            elif re.search(r"up to (\w+) creatures you can see within (\d+) feet", low):     # the Void Card: three at once
                many = re.search(r"up to (\w+) creatures you can see within (\d+) feet", low)
                tgt, r = {"type": "creature", "count": NUM.get(many.group(1), 1), "enemies": True}, int(many.group(2))
            else:
                continue
            out.append({"key": key, "name": nm, "cost": cost, "kind": "save", "sv": sv, "parts": [list(x) for x in parts], "area": area,
                        "target": tgt, "range": r, "limit": limit, "self_too": bool(re.search(r"\byou and each creature|(?<!not )including you\b", low)),
                        "only": "ferrous" if re.search(r"made (?:wholly or partly )?(?:out )?of ferrous metal", low) else
                        "vampire" if "vampire spawn within" in low else None,
                        "drain": bool(re.search(r"you (?:then )?regain (?:a number of )?hit points equal to the \w+ damage", low)),
                        "tip": body[:300]})
            continue
        if re.search(r"automatically (?:strike|hit)", low) and CR.damage_parts(body):
            out.append({"key": key, "name": nm, "cost": cost, "kind": "auto", "parts": [list(x) for x in CR.damage_parts(body)],
                        "per_charge": bool(re.search(r"number of \w+ equal to the number of charges|for each charge", low)),
                        "target": {"type": "creature", "count": 1, "enemies": True}, "range": int(rng.group(1)) if rng else 60, "limit": limit,
                        "tip": body[:300]})
            continue
        m = re.search(r"(ranged|melee) spell attack", low)
        if m:
            parts = CR.damage_parts(body)
            if not parts:
                continue
            bonus = re.search(r"(?:with a|attack bonus of|bonus of) \+(\d+)|\+(\d+) (?:bonus|to hit)", low)
            ab = "dex" if "using dexterity" in low else None
            out.append({"key": key, "name": nm, "cost": cost, "kind": "attack", "melee": m.group(1) == "melee",
                        "bonus": int(bonus.group(1) or bonus.group(2)) if bonus else None, "ability": ab, "parts": [list(x) for x in parts],
                        "per_charge": bool(re.search(r"for each charge you spend", low)),
                        "target": {"type": "creature", "count": 1, "enemies": True}, "range": int(rng.group(1)) if rng else 60, "limit": limit,
                        "tip": body[:300]})
    names = [a["name"] for a in out]
    for a in out:                                          # a Gem of Brightness's beam and flare: told apart by their reach
        if names.count(a["name"]) > 1 and a.get("kind") == "save":
            ar = a.get("area")
            a["name"] += f" ({ar['size']}-ft {ar['shape']})" if ar else " (one creature)"
    return out


def _save_terms(post: str) -> dict:
    from .standard import StandardMixin
    return StandardMixin._save_terms(post)


# items that react (reactions.py asks through these families, like any other reaction)
ITEM_FAMILIES = {"item_evasion": "Ring of Evasion", "item_scarab": "Scarab of Protection", "item_absorb": "Absorbing Tattoo",
                 "item_shadow": "Shadowy Defense", "item_snare": "Gloves of Missile Snaring", "item_emblem": "Guardian Emblem",
                 "item_buckler": "Sapphire Buckler", "item_spell_sink": "Absorb a spell"}
REACTING = {"item_evasion": r"^Ring of Evasion$", "item_scarab": r"^Scarab of Protection$", "item_absorb": r"Absorbing Tattoo$",
            "item_shadow": r"^Shadowfell Brand Tattoo$", "item_snare": r"^Gloves of Missile Snaring$", "item_emblem": r"^Guardian Emblem$",
            "item_buckler": r"^Sapphire Buckler$", "item_spell_sink": r"^Ioun Stone, (?:Greater )?Absorption$|^Rod of Absorption$"}
SPELL_SINK = {"Ioun Stone, Absorption": (4, 20), "Ioun Stone, Greater Absorption": (8, 50), "Rod of Absorption": (9, 50)}   # (top level, levels it holds)
ITEM_FAMILIES["item_retribution"] = "Rod of Retribution"
REACTING["item_retribution"] = r"^Rod of Retribution$"
ITEM_FAMILIES["item_twist"] = "Twist of Fate"
REACTING["item_twist"] = r"^Spindle of Fate$"
ITEM_FAMILIES["item_answer"] = "Sword of Answering"
REACTING["item_answer"] = r"^Sword of Answering|^Demonbone "      # a Demonbone weapon strikes back too (no advantage)
ITEM_FAMILIES["item_orb"] = "Orb of shielding"
REACTING["item_orb"] = r"^(?:Fernian|Irian|Kythrian|Lamannian|Mabaran|Risian|Shavarran|Xorian|Daanvi|Dolurrh|Syrania|Thelanis) \w+ (?:Orb|Crystal|Rod|Staff|Wand)$"
ORB_RE = re.compile(r"when you take ([a-z]+)(?: or ([a-z]+))? damage, you can use your reaction to reduce the damage by (\d+d\d+)")
ITEM_FAMILIES["item_charge_hit"] = "Charged strike"        # Staff of Striking, Staff of Withering, Blood Fury Tattoo...: after a hit, free
ITEM_FAMILIES["item_hit_opt"] = "Weapon's after-hit power"  # a Ruinous Flail's sickness, the Lash of Shadows' poisons (itemextras.hit_choices)
ITEM_FAMILIES["item_luck"] = "Luck Blade"            # once a day, no action: reroll an attack roll or a save it dislikes (the new roll stands)
REACTING["item_luck"] = r"^Luck Blade "
ITEM_FAMILIES["item_treachery"] = "Ring of Treachery"   # a charge and a reaction: the damage it takes goes to a random creature within 60 ft
REACTING["item_treachery"] = r"^Ring of Treachery$"
ITEM_FAMILIES["item_possibility"] = "New Possibility"   # Staff of Dunamancy: a failed save against a spell that targets only you becomes a success
REACTING["item_possibility"] = r"^Staff of Dunamancy$"
ITEM_FAMILIES["item_tome"] = "Spellbook's charge"       # a Tasha's wizard book (spellitems.py): a reaction and a charge
ITEM_FAMILIES["item_tome_free"] = "Spellbook's charge (free)"     # Heart Weaver's Primer: a charge, no reaction
ITEM_FAMILIES["item_focus"] = "Dragon-Touched Focus (Metallic)"     # advantage on a creature's save, a reaction (the pack entry's note names the family)
ITEM_FAMILIES["item_ornament"] = "Scaled Ornament's breath ward"     # a Wakened or Ascendant Scaled Ornament: no damage of its dragon's breath type, healed instead
ITEM_FAMILIES["item_jester"] = "Marvelous Escape"       # a Jester's Mask: a reaction, a hit becomes a miss and the wearer blinks away
ITEM_FREE = {"item_charge_hit", "item_hit_opt", "item_luck", "item_possibility", "item_tome_free"} | MORE.FREE | LORE.FREE
ITEM_FAMILIES.update(LORE.FAMILIES)                      # weaponlore.py: a charge turns a miss into a hit
ITEM_FAMILIES.update(MORE.ITEM_FAMILIES)                 # itemmore.py: Dazzling weapons, a Repulsion Shield, Chattering skulls...
REACTING.update(MORE.REACTING)
CHARGE_HIT = re.compile(r"(?:when you hit (?:a creature )?with an? (?:melee |weapon )*attack[^.]*?|on a hit, it deals damage as a normal \w+), "
                        r"(?:and )?you can expend (?:up to (\d) of its charges|(?:a|one|1) charges?)"
                        r"[^.]*?(?:\.\s*For each charge you expend, the target takes an|to deal an?) extra (\d+d\d+) (\w+) damage", re.I)


def charge_hit(item: Optional[dict]) -> Optional[dict]:
    """A charged strike after a hit: {'max' (charges at most), 'dice', 'type', 'any_weapon' (not only this item's),
    'drain' (heal by it), 'save' (Staff of Withering: DC, rider)}, or None."""
    d = re.search(r"When you hit a target with a weapon attack while holding this card, you can deal an extra (\d+d\d+) (\w+) damage",
                  (item or {}).get("text") or "")
    if d:                                                   # the Rogue Card: once a day
        return {"max": 1, "dice": d.group(1), "type": d.group(2).lower(), "any_weapon": True, "drain": False, "save": None, "daily": True}
    b = re.search(r"Whenever you deal damage to a creature, you can expend 1 charge to deal an extra (\d+d\d+) (\w+) damage to the target and force it "
                  r"to make a DC (\d+) Constitution saving throw\. On a failed save, the target gains 1 Exhaustion level", (item or {}).get("text") or "")
    if b and (item or {}).get("charges"):                   # a Blood Amulet (AU): on any hit it can pay a charge for 2d10 necrotic and exhaustion
        return {"max": 1, "dice": b.group(1), "type": b.group(2).lower(), "any_weapon": True, "drain": False, "save": None, "exhaust": int(b.group(3))}
    m = CHARGE_HIT.search(_clean((item or {}).get("text")))
    if not m or not (item or {}).get("charges"):
        return None
    after = _clean(item["text"])[m.end():m.end() + 300]
    sv = re.search(r"DC (\d+) Constitution saving throw or have disadvantage", after)
    return {"max": int(m.group(1) or 1), "dice": m.group(2), "type": m.group(3).lower(), "any_weapon": not item.get("weapon"),
            "drain": bool(re.search(r"regain a number of hit points equal to the \w+ damage", after)), "save": int(sv.group(1)) if sv else None}


def _needs_wearing(item: dict) -> bool:
    return bool(re.search(r"\bwhile (?:you (?:are )?)?(?:wear|wearing)\b|\bwhile wielding\b|\bwhile holding this shield\b",
                          item.get("text") or "", re.I)) or item.get("type") in ("LA", "MA", "HA", "S", "RG")


class WondrousMixin(ItemMoreMixin):
    # ------------------------------------------------------------------ worn
    def _wonder_passives(self, c: dict, char) -> list:
        """Effect-like entries for what the hero's equipped (and attuned) items give while worn."""
        if c.get("form") or any((e.get("mods") or {}).get("items_suppressed") for e in c.get("effects") or []):
            return []                                         # beast shape melds the gear; the Talons Card silences it
        out = []
        armor = None
        for _e, item in char._active_items():
            mods = dict(_mods_of(item["name"]))
            if not mods:
                continue
            if "fly_walk" in mods:
                mods["fly"] = max(int(mods.get("fly") or 0), char.speed)
            if "fly_dim" in mods and (self.b.get("map") or {}).get("light", "bright") != "bright":
                mods["fly"] = max(int(mods.get("fly") or 0), mods["fly_dim"])
            if "speed_floor" in mods and char.speed < mods["speed_floor"]:
                mods["speed"] = mods["speed_floor"] - char.speed
            if "darkvision_plus" in mods and char.darkvision:
                mods["senses"] = dict(mods.get("senses") or {}, darkvision=char.darkvision + mods["darkvision_plus"])
            if "ac_unarmored" in mods:
                armor = armor if armor is not None else (char.equipped_armor() or False)
                base, cap = mods["ac_unarmored"]
                if not armor:                                 # the item's base AC, then the shield and rings, cloaks... on top
                    dex = char.mod("dex")
                    shield = char.equipped_shield()
                    on_top = (shield["ac"] + (shield.get("bonus_ac") or 0) if shield else 0) + \
                        sum(d.get("bonus_ac") or 0 for _x, d in char._active_items() if d["type"] not in ("LA", "MA", "HA", "S")
                            and not (d.get("unarmored_only") and shield))
                    mods["ac_min"] = base + (dex if cap is None else min(dex, cap)) + on_top
            if mods.get("displacement") and not self._displaced(c):
                mods.pop("displacement")
            if mods.get("displacement"):
                mods["attacks_against"] = "dis"
            if mods.get("life_ward") and char.d["resources"].get(f"item:{item['name']}:life_ward"):
                mods.pop("life_ward")
            out.append({"name": item["name"], "mods": mods, "conditions": [], "item": True})
        return out

    def _displaced(self, c: dict) -> bool:
        """Cloak of Displacement works: not after taking damage since the start of the wearer's turn, nor while it is
        incapacitated, restrained, grappled or held at speed 0."""
        conds = set(self._conds(c))
        if K.incapacitated(conds) or conds & {"Restrained", "Grappled"} or c.get("took_types"):
            return False
        return not any((e.get("mods") or {}).get("speed_set") == 0 for e in c.get("effects") or [])

    # hooks the attack roll calls (resolve._attack_check)
    def _wonder_modes(self, att: dict, tgt: dict, a: dict, modes: set, why: list):
        self._pick_special_ammo(att, tgt, a, modes, why)        # arrows of slaying, bloodseeker arrows... (itemextras.py)
        if a.get("spell"):
            for e, v in self._fxs(tgt, "spell_against"):        # Spellguard Shield
                modes.add(v)
                why.append(e["name"])
            if not a.get("ignore_partial_cover") and self._fxs(att, "spell_ignore_cover"):
                a["ignore_partial_cover"] = True                # Wand of the War Mage: half cover doesn't count
        if a.get("weapon") and a.get("melee", True) and re.search(r"\bLance\b", str(a.get("item") or "")) and not att.get("mount") \
                and att.get("pos") and tgt.get("pos") and self._dist(att, tgt) <= 5:
            modes.add("dis")                                    # a lance: disadvantage against a target within 5 feet
            why.append("Lance within 5 ft")
        dchar = self._sheet(att) if not att.get("form") else None
        if dchar and "demon" in str((self._monster(tgt) or {}).get("type") or "").lower() and \
                any("disadvantage on attack rolls against demons" in (d.get("text") or "") for _e, d in dchar._active_items()):
            modes.add("dis")                                    # Demon Armor's curse
            why.append("Demon Armor's curse")
        char = self._sheet(att) if a.get("weapon") and not att.get("form") else None
        for _e, d in (char._active_items() if char else []):    # a Sword of Vengeance's curse: other weapons at disadvantage
            if d.get("weapon") and d["name"] != a.get("item") and "disadvantage on attack rolls made with weapons other than this one" in \
                    (d.get("text") or "").replace("attack rolls with weapons", "attack rolls made with weapons"):
                modes.add("dis")
                why.append(f"{d['name']}'s curse")
                break
        stack = self._stack()
        if stack and str(stack[-1].get("label") or "").startswith("Opportunity attack"):
            for e, v in self._fxs(tgt, "oa_against"):           # Boots of Speed
                modes.add(v)
                why.append(e["name"])

    def _wonder_save_modes(self, c: dict, label: str, source: Optional[dict], modes: set, why: list):
        """Advantage on saves against one thing of one kind of creature: Dragon Scale Mail against a dragon's breath
        weapon or Frightful Presence (the save's label names it)."""
        low = (label or "").lower()
        for e, v in self._fxs(c, "save_adv_vs"):
            kind = str((self._monster(source) or {}).get("type") or "").lower() if source else ""
            if any(x in low for x in v.get("labels") or []) and (not v.get("type") or v["type"] in kind):
                modes.add("adv")
                why.append(e["name"])

    def _wonder_strike_start(self, R: dict, att: Optional[dict]):
        """An imbued wood focus (Eberron): a damage-dealing spell cast through it gets +1 on one damage roll of its type."""
        self._ones_as_twos(R, att)                              # Spell-Fueling armour: a 1 on a spell's damage die counts as a 2 (itemmore.py)
        char = self._sheet(att) if att and not att.get("form") else None
        if not char or not R.get("spell") or R.get("focus_done"):
            return
        R["focus_done"] = True
        parts = R.get("parts") or (R.get("atk") or {}).get("parts") or []
        for _e, d in char._active_items():
            m = re.search(r"\+1 bonus to one ([a-z]+)(?: or ([a-z]+))? damage roll of the spell", d.get("text") or "")
            hit = m and next((t for _d, t in parts if t in (m.group(1), m.group(2))), None)
            if hit:
                parts.append(["1", hit])
                self._line(R, f"{d['name']}: +1 {hit}", d["name"])
                return

    def _on_turn_start(self, creature: dict):
        """dispatch.py's turn_start event (this mixin is its only handler; another one would need to call this too)."""
        self._wonder_turn_start(creature)

    def _wonder_turn_start(self, c: dict):
        """A new turn: a Spindle of Fate's doom is ready again; a cursed weapon's berserker must swing at the nearest creature
        (the creature that hurt it, for a Sword of Vengeance) before anything else, like a Crown of Madness."""
        self._lore_turn_start(c)                                # a scabbard's hit points, a blazing sword's blinding (weaponlore.py)
        for o in self.b["combatants"]:
            for e in o.get("effects") or []:
                if e["name"] == "Doom Foretold" and e.get("source_id") == c["id"] and e.pop("doom_spent", None):
                    e["mods"]["extra_damage"] = ("1d6", "")
        hunger = next((e for e in c.get("effects") or [] if e["name"] == "Blackrazor's hunger"), None)
        if hunger is not None and self._sheet(c) and self._sheet(c).temp_hp <= 0:
            self._effect_off(c, hunger, "the stolen hit points are gone")      # its advantage lasts as long as those hit points
        rage = next((e for e in c.get("effects") or [] if e["name"].startswith("Berserk (")), None)
        if rage is None or not c.get("pos") or not self._can_act(c):
            return
        near = sorted((o for o in self.b["combatants"] if o is not c and o.get("pos") and self._alive(o) and not o.get("conjured")),
                      key=lambda o: self._dist(o, c))
        if not near or self._dist(near[0], c) > 60:            # nobody within 60 ft: the rage is over
            self._effect_off(c, rage, "nobody left to fight")
            return
        foe = self._find_or_none((rage.get("mods") or {}).get("berserk"))
        vengeance = "must attack the creature that damaged you" in ((rules.item(rage["name"][9:-1]) or {}).get("text") or "")
        victim = foe if vengeance and foe is not None and self._alive(foe) else near[0]
        c.setdefault("turn", {})["crown_victim"] = victim["id"]
        self._say(f"{c['name']} is berserk: its first attack must go at {victim['name']}")

    def _wonder_initiative(self, c: dict) -> int:
        """A Spindle of Fate's Battle Foreknowledge: + proficiency bonus to initiative for 1 charge (spent while 3 or more are left,
        so Doom Foretold stays possible)."""
        char = self._sheet(c)
        for e, d in (char._active_items() if char else []):
            if d["name"] == "Spindle of Fate" and self._charges_left(e) >= 3:
                e["charges_left"] = self._charges_left(e) - 1
                char.save()
                self._say(f"{c['name']}'s {d['name']}: Battle Foreknowledge (+{char.proficiency_bonus} initiative)")
                return char.proficiency_bonus
        return 0

    def _wonder_dsave(self, c: dict, r: int) -> int:
        """A Gambler's Blade's bet: its bonus comes off death saving throws (a natural 1 or 20 stays what it is)."""
        minus = sum(int((e.get("mods") or {}).get("dsave_minus") or 0) for e in c.get("effects") or [])
        return r if r in (1, 20) or not minus else max(2, r - minus)

    def _wonder_revealed(self, c: dict) -> bool:
        """In a lit Lantern of Revealing's bright light (30 ft), invisible creatures can be seen."""
        if not c.get("pos"):
            return False
        for o in self.b["combatants"]:
            for e in o.get("effects") or []:
                ft = (e.get("mods") or {}).get("reveal_ft")
                if ft and o.get("pos") and self._dist(o, c) <= ft:
                    return True
        return False

    def _wonder_roll(self, att: dict, total: int, kept: int):
        """A Clockwork Amulet switched on: this attack roll's d20 counts as a 10 (then the effect is gone)."""
        e = next((x for x in att.get("effects") or [] if (x.get("mods") or {}).get("roll_10")), None) if att else None
        if e is None:
            return total, kept
        self._effect_off(att, e, "used")
        return total - kept + 10, 10

    def _wonder_ac(self, tgt: dict, a: dict, att: Optional[dict] = None) -> int:
        kind = str((self._monster(att) or {}).get("type") or "").lower() if att is not None else ""
        if kind and any(kind.startswith(k) for _e, ks in self._fxs(tgt, "barrier_kinds") for k in ks):
            return 100                                          # a Scroll of Protection's barrier: that kind of creature can't hit
        bar = next((int(v) for _e, v in self._fxs(tgt, "barrier")), 0)       # a Cube of Force: what its face keeps out
        if bar and (bar == 5 or bar == 4 and a.get("spell") or bar == 3 and a.get("melee") or bar == 2 and not a.get("melee") and not a.get("spell")):
            return 100
        if a.get("melee", True):
            return 0
        return sum(int(v) for _e, v in self._fxs(tgt, "ranged_ac"))     # Arrow-Catching Shield

    def _wonder_no_crit(self, tgt: dict, why: list) -> bool:
        for e, _v in self._fxs(tgt, "no_crit"):                 # adamantine armour, a spore druid's Fungal Body (not while incapacitated)
            if e["name"] == "Fungal Body" and K.incapacitated(self._conds(tgt)):
                continue
            why.append(f"{e['name']}: no critical hit")
            return True
        return False

    def _wonder_immune_spell(self, tgt: dict, label: str) -> bool:
        """Brooch of Shielding: damage from the magic missile spell does nothing."""
        low = (label or "").lower()
        return any(low in [s.lower() for s in v] for _e, v in self._fxs(tgt, "immune_spell"))

    def _wonder_stabilize(self, c: dict) -> bool:
        """Periapt of Wound Closure: a dying wearer stabilises at the start of its turn (no death save)."""
        char = self._sheet(c)
        found = next((e for e, _v in self._fxs(c, "auto_stable")), None)
        if not char or found is None or char.current_hp > 0:
            return False
        char.d["death_saves"] = {"success": 3, "failure": int((char.d.get("death_saves") or {}).get("failure") or 0)}
        char.save()
        self._say(f"{c['name']} is stable ({found['name']})")
        return True

    def _ferrous(self, c: dict) -> bool:
        """Is the creature made wholly or partly of ferrous metal (Dust of Corrosion)? Constructs and the iron-and-steel kinds."""
        m = self._monster(c) or {}
        return str(m.get("type") or "").lower() == "construct" or bool(re.search(
            r"iron|steel|metal|armor|clockwork|gear|rust|blade|sword|knight|helm", (m.get("name") or "") + " " + " ".join(m.get("tags") or []), re.I))

    # ------------------------------------------------------------------ reactions (reactions.py asks, these answer)
    def _wonder_item(self, c: dict, fam: str):
        """(pack entry, item) of the hero's worn item behind a reaction family, when it can still be used now."""
        char = self._sheet(c) if c and not c.get("form") else None
        if not char or fam not in REACTING:
            return None, None
        items = char._active_items()
        if fam in ("item_luck", "item_foot"):                   # "if the sword is on your person": carried, not only wielded (a Lucky Foot too)
            items = [(e, char.item_data(e)) for e in char.inventory if char.item_data(e)]
        for e, d in items:
            if not re.search(REACTING[fam], d["name"]):
                continue
            if d.get("charges") and fam not in ("item_luck", "item_possibility") and self._charges_left(e) <= 0:
                continue                                        # (a Luck Blade's charges are for its Wish, not its luck)
            if (fam in ("item_absorb", "item_shadow", "item_luck", "item_possibility") or fam in MORE.DAILY) and char.d["resources"].get(f"item:{d['name']}:{fam}"):
                continue
            if fam == "item_spell_sink" and int(e.get("absorbed") or 0) >= SPELL_SINK.get(d["name"], (0, 0))[1]:
                continue                                    # burnt out
            return e, d
        return None, None

    def _wonder_families(self, c: dict) -> List[str]:
        return [f for f in ITEM_FAMILIES if self._wonder_item(c, f)[1]] + (["item_charge_hit"] if self._charge_hitters(c, None) else [])             + self._tome_families(c) + self._lore_families(c)     # spellitems.py: wizard books, a Jester's Mask; weaponlore.py

    def _charge_hitters(self, att: dict, a: Optional[dict]) -> list:
        """[(pack entry, item, charge_hit)] of the hero's items that can pour charges into this weapon hit (a None: any)."""
        char = self._sheet(att) if att and not att.get("form") else None
        out = []
        for e, d in (char._active_items() if char else []):
            ch = charge_hit(d)
            ready = not char.d["resources"].get(f"item:{d['name']}:hit") if ch and ch.get("daily") else ch and self._charges_left(e) > 0
            if ch and ready and (a is None or (ch["any_weapon"] or a.get("item") == e["name"])):
                out.append((e, d, ch))
        return out

    def _wonder_eligible(self, out: list, window: str, R: dict, att: Optional[dict], tgt: Optional[dict], ctx: dict):
        """The worn items' reactions at this point of a resolution (reactions._eligible)."""
        cur = R.get("cur") or {}
        a = R.get("atk") or {}
        self._tome_eligible(out, window, R, att, tgt, ctx)      # a Tasha's wizard book (spellitems.py)
        self._more_eligible(out, window, R, att, tgt, ctx)      # Dazzling weapons, a Repulsion Shield, Chattering skulls... (itemmore.py)
        self._lore_eligible(out, window, R, att, tgt, ctx)      # a miss turned into a hit, an attacker marked for penance (weaponlore.py)

        def put(reactor_id, cost, opts, text):                 # one question per reactor and window: join one already asked
            same = next((q for q in out if q["reactor"] == reactor_id and q.get("cost") == cost and not q.get("window")), None)
            if same is not None:
                same["options"] = list(same["options"]) + opts
            else:
                out.append({"reactor": reactor_id, "cost": cost, "options": opts, "text": text})

        def ask(reactor, fam, label, text):
            put(reactor["id"], "reaction", [{"key": fam, "label": label, "detail": ""}], text)

        if window == "missed" and att and not att.get("form") and self._wonder_item(att, "item_luck")[1]:
            put(att["id"], "free", [{"key": "item_luck", "label": "Luck Blade: reroll the attack (the new roll stands)", "detail": f"{cur.get('total')} vs AC {cur.get('ac')}"}],
                f"{att['name']} misses {tgt['name'] if tgt else 'it'} ({cur.get('total')} vs AC {cur.get('ac')}). Call on the Luck Blade?")
        if window == "save_failed" and tgt and not cur.get("auto") and self._wonder_item(tgt, "item_luck")[1]:
            put(tgt["id"], "free", [{"key": "item_luck", "label": "Luck Blade: reroll the save (the new roll stands)", "detail": ""}],
                f"{tgt['name']} failed its {(R.get('sv') or {}).get('ab', '').upper()} save ({cur.get('total')} vs DC {(R.get('sv') or {}).get('dc')}). Call on the Luck Blade?")
        if window == "save_failed" and tgt and not cur.get("auto") and R.get("spell") and len(set(R.get("targets") or [])) == 1 \
                and self._wonder_item(tgt, "item_possibility")[1]:        # a Staff of Dunamancy's New Possibility: a spell that targets only you
            put(tgt["id"], "free", [{"key": "item_possibility", "label": "Staff of Dunamancy: turn the failed save into a success (once until dawn)", "detail": ""}],
                f"{tgt['name']} failed its {(R.get('sv') or {}).get('ab', '').upper()} save against {R['label']}. Use New Possibility?")
        if window in ("save_failed", "save_ok", "hit", "missed") and tgt:   # a Spindle of Fate's Twist of Fate (3 charges): within 60 ft, flip it
            for o in self.b["combatants"]:
                e, d = self._wonder_item(o, "item_twist")
                if not d or self._charges_left(e) < 3 or not o.get("pos"):
                    continue
                if window == "save_failed" and not cur.get("auto") and not self._hostile(o, tgt) and self._dist(o, tgt) <= 60:
                    ask(o, "item_twist", "Twist of Fate: the save succeeds instead (3 charges)", f"{tgt['name']} failed a save. Twist its fate?")
                elif window == "save_ok" and not cur.get("auto") and self._hostile(o, tgt) and self._dist(o, tgt) <= 60:
                    ask(o, "item_twist", "Twist of Fate: the save fails instead (3 charges)", f"{tgt['name']} made its save. Twist its fate?")
                elif window == "hit" and att and self._hostile(o, att) and not self._hostile(o, tgt) and self._dist(o, att) <= 60:
                    ask(o, "item_twist", "Twist of Fate: the attack misses instead (3 charges)", f"{att['name']} hits {tgt['name']}. Twist its fate?")
                elif window == "missed" and att and not self._hostile(o, att) and self._dist(o, att) <= 60:
                    ask(o, "item_twist", "Twist of Fate: the attack hits instead (3 charges)", f"{att['name']} misses {tgt['name']}. Twist its fate?")
        if window == "damage" and att and tgt and R.get("mode") == "attack":    # Doom Foretold: its 1d6 once a turn
            for e in tgt.get("effects") or []:
                if e["name"] == "Doom Foretold" and e.get("source_id") == att["id"] and "extra_damage" in (e.get("mods") or {}):
                    e["mods"].pop("extra_damage")
                    e["doom_spent"] = True
        if window == "save_failed" and tgt and not cur.get("auto"):
            sv = R.get("sv") or {}
            e, d = self._wonder_item(tgt, "item_evasion")
            if d and sv.get("ab") == "dex":
                ask(tgt, "item_evasion", f"Ring of Evasion: succeed instead ({self._charges_left(e)} charges)",
                    f"{tgt['name']} failed a DEX save against {R['label']}. Use the Ring of Evasion?")
            e, d = self._wonder_item(tgt, "item_scarab")
            src = self._find_or_none(R.get("actor"))
            sp = rules.spell(R.get("label") or "") if R.get("spell") else None
            if d and ((sp and sp.get("school") == "Necromancy") or (src and "undead" in str((self._monster(src) or {}).get("type") or "").lower())):
                ask(tgt, "item_scarab", f"Scarab of Protection: succeed instead ({self._charges_left(e)} charges)",
                    f"{tgt['name']} failed a save against {R['label']}. Use the Scarab of Protection?")
        elif window == "damage" and tgt:
            char = self._sheet(tgt)
            if R.get("mode") == "attack" and a.get("weapon") and not a.get("melee") and char and not cur.get("missile_halved") and \
                    any(d["name"] == "Shield of Missile Attraction" for _e, d in char._active_items()):
                cur["missile_halved"] = True                    # not a reaction: the shield always takes the edge off arrows
                cur["dmg"] = [[n // 2, t] for n, t in cur.get("dmg") or []]
                self._line(R, f"{tgt['name']}'s Shield of Missile Attraction: half damage from the ranged attack", "Missile Attraction")
            types = {t for n, t in cur.get("dmg") or [] if n}
            e, d = self._wonder_item(tgt, "item_absorb")
            if d and set(d.get("resist") or []) & types:
                t = sorted(set(d["resist"]) & types)[0]
                ask(tgt, "item_absorb", f"{d['name']}: no {t} damage, heal half", f"{tgt['name']} is about to take {t} damage. Absorb it?")
            e, d = self._wonder_item(tgt, "item_shadow")
            if d and types:
                ask(tgt, "item_shadow", "Shadowy Defense: halve the damage", f"{tgt['name']} is about to take damage from {R['label']}. Turn insubstantial?")
            e, d = self._wonder_item(tgt, "item_treachery")
            if d and types and tgt.get("pos") and any(o is not tgt and o.get("pos") and self._alive(o) and self._dist(tgt, o) <= 60 for o in self.b["combatants"]):
                ask(tgt, "item_treachery", f"Ring of Treachery: pass the damage to a random creature within 60 ft ({self._charges_left(e)} charges)",
                    f"{tgt['name']} is about to take damage from {R['label']}. Use the Ring of Treachery?")
            for e, d in (char._active_items() if char and not tgt.get("form") else []):
                m = ORB_RE.search(d.get("text") or "")
                if m and types & {m.group(1), m.group(2)}:     # an orb of shielding: 1d4 off that damage
                    ask(tgt, f"item_orb:{d['name']}", f"{d['name']}: reduce the damage by {m.group(3)}", f"{tgt['name']} is about to take "
                        f"{'/'.join(sorted(types & {m.group(1), m.group(2)}))} damage. Use the {d['name']}?")
                    break
            e, d = self._wonder_item(tgt, "item_snare")
            if d and R.get("mode") == "attack" and a.get("weapon") and not a.get("melee"):
                ask(tgt, "item_snare", "Gloves of Missile Snaring: reduce the damage", f"A missile hits {tgt['name']}. Snare it?")
        elif window == "hit" and tgt and cur.get("crit"):
            for o in self.b["combatants"]:
                e, d = self._wonder_item(o, "item_emblem")
                if d and not self._hostile(o, tgt) and (o is tgt or self._dist(o, tgt) <= 30 and self._sees(o, tgt)):
                    ask(o, "item_emblem", f"Guardian Emblem: a normal hit instead ({self._charges_left(e)} charges)",
                        f"A critical hit on {tgt['name']}. Turn it into a normal hit?")
        elif window == "on_hit" and att and tgt and a.get("weapon"):
            for e, d, ch in self._charge_hitters(att, a):
                left = 1 if ch.get("daily") else self._charges_left(e)
                opts = [{"key": f"item_charge_hit:{e['name']}|{k}", "label": f"{d['name']}: {k} charge{'s' if k > 1 else ''} (+{k}×{ch['dice']} {ch['type']})",
                         "detail": f"{left} left"} for k in range(1, min(ch["max"], left) + 1)]
                if opts:
                    put(att["id"], "free", opts, f"{att['name']} hits {tgt['name']}. Spend {d['name']} charges?")
            from .itemextras import hit_choices
            wchar = self._sheet(att)
            witem = rules.item(a.get("item") or "") if wchar and a.get("item") else None
            opts = [{"key": f"item_hit_opt:{witem['name']}|{x['key']}", "label": x["label"], "detail": ""} for x in hit_choices(witem)
                    if not (x["daily"] and wchar.d["resources"].get(f"item:{witem['name']}:{x['key']}"))
                    and not (x.get("charge") and self._charges_left(wchar.find_item(witem["name"]) or {"name": witem["name"]}) < x["charge"])] if witem else []
            if opts:
                put(att["id"], "free", opts, f"{att['name']} hits {tgt['name']}. Use {witem['name']}'s power?")
        elif window == "cast" and att and not R.get("tiles") and len(set(R.get("targets") or [])) == 1:
            o = self._find_or_none((R.get("targets") or [None])[0])     # a spell aimed at one creature only (no area)
            e, d = self._wonder_item(o, "item_spell_sink") if o is not None and o is not att else (None, None)
            lv = int(R.get("slot_level") or 0)
            if d and lv <= SPELL_SINK[d["name"]][0] and int(e.get("absorbed") or 0) + lv <= SPELL_SINK[d["name"]][1] and self._sees(o, att):
                ask(o, "item_spell_sink", f"{d['name']}: cancel it", f"{att['name']} casts {R['label']} (level {lv}) at {o['name']} alone. Absorb it?")
        elif window == "after_damage" and att and tgt and att is not tgt and self._alive(tgt):
            tchar = self._sheet(tgt)
            rage = next((d for _e, d in (tchar._active_items() if tchar else []) if d.get("weapon") and re.search(
                r"DC 15 Wisdom saving throw (?:or go berserk|whenever you take damage in combat)", d.get("text") or "")), None)
            if rage and self._hostile(att, tgt) and not any(x["name"].startswith("Berserk") for x in tgt.get("effects") or []):
                res = self._saving_throw(tgt, "wis", 15, label=f"{rage['name']}'s curse")   # a cursed weapon's rage (no reaction: it just happens)
                if not res["ok"]:
                    self._effect_on(tgt, f"Berserk ({rage['name']})", [], None, None, None, 10, rage["name"], {"berserk": att["id"]}, None, tgt["id"])
                    self._line(R, f"{tgt['name']} goes berserk: it must attack {att['name']} ({rage['name']}'s curse)", "berserk")
            e, d = self._wonder_item(tgt, "item_buckler")
            if d and self._dist(att, tgt) <= 5:
                out.append({"reactor": tgt["id"], "cost": "reaction", "window": "after_damage",
                            "options": [{"key": "item_buckler", "label": f"Sapphire Buckler: 2d6 thunder to {att['name']}", "detail": ""}],
                            "text": f"{att['name']} hurt {tgt['name']}. Strike back with the Sapphire Buckler?"})
            e, d = self._wonder_item(tgt, "item_answer")
            if d and self._dist(att, tgt) <= self._reach(tgt) and any(w["name"] == e["name"] for w in self._sheet(tgt).attacks()):
                out.append({"reactor": tgt["id"], "cost": "reaction", "window": "after_damage",
                            "options": [{"key": "item_answer", "label": f"{d['name']}: strike back at {att['name']}", "detail": ""}],
                            "text": f"{att['name']} hurt {tgt['name']}. Answer with the sword?"})
            e, d = self._wonder_item(tgt, "item_retribution")
            if d and self._dist(att, tgt) <= 60 and self._sees(tgt, att):
                out.append({"reactor": tgt["id"], "cost": "reaction", "window": "after_damage",
                            "options": [{"key": "item_retribution", "label": f"Rod of Retribution: lightning at {att['name']} ({self._charges_left(e)} charges)",
                                         "detail": ""}],
                            "text": f"{att['name']} hurt {tgt['name']}. Answer with the Rod of Retribution?"})

    def _wonder_auto_pick(self, window: str, R: dict, reactor: dict, keys: List[str]) -> Optional[str]:
        """A reactor set to "always" uses its items' reactions whenever they are offered (the Gloves of Missile Snaring
        and a Shadowfell Brand only against more than a little damage)."""
        charged = [k for k in keys if k.startswith(("item_charge_hit:", "item_hit_opt:"))]
        if charged:                                             # charges into a critical hit only (the dice double)
            return charged[-1] if (R.get("cur") or {}).get("crit") else None
        mine = [k for k in keys if k.split(":")[0] in ITEM_FAMILIES]
        if not mine:
            return None
        total = sum(n for n, _t in (R.get("cur") or {}).get("dmg") or [])
        for k in mine:
            if k in ("item_shadow", "item_snare") and total < 8:
                continue
            return k
        return None

    def _wonder_react(self, window: str, R: dict, reactor: dict, fam: str, arg: str, ctx: dict):
        """What a worn item's reaction does."""
        cur = R.setdefault("cur", {})
        if fam in MORE.ITEM_FAMILIES:
            self._more_react(window, R, reactor, fam, arg, ctx)
            return
        if fam in LORE.FAMILIES:
            self._lore_react(window, R, reactor, fam, arg, ctx)
            return
        if fam in ("item_tome", "item_tome_free", "item_jester", "item_focus", "item_ornament"):
            self._tome_react(window, R, reactor, fam, arg, ctx)
            return
        if fam == "item_charge_hit":
            self._wonder_charge_hit(R, reactor, arg, ctx)
            return
        if fam == "item_hit_opt":
            self._extra_hit_choice(R, reactor, arg, ctx)
            return
        if fam == "item_luck":                                  # Luck Blade: once a day, a reroll that must be used
            e, d = self._wonder_item(reactor, fam)
            char = self._sheet(reactor)
            if not d or char is None:
                return
            char.d["resources"][f"item:{d['name']}:item_luck"] = 1
            char.save()
            again = self.rng.randint(1, 20)
            if window == "save_failed":
                total = cur["total"] - cur["kept"] + again
                cur.update(total=total, kept=again, ok=total >= int(R["sv"]["dc"]))
                self._line(R, f"{reactor['name']} calls on the {d['name']}: {again} → {total}" + (" — success" if cur["ok"] else " — still failed"), "Luck Blade")
            else:
                cur["total"] = cur["total"] - cur["kept"] + again
                cur.update(kept=again, crit=again == 20)
                self._line(R, f"{reactor['name']} calls on the {d['name']}: the attack is rerolled ({again}) → {cur['total']}", "Luck Blade")
            return
        if fam == "item_possibility":                           # a Staff of Dunamancy: the failed save is a success, once until dawn
            e, d = self._wonder_item(reactor, fam)
            char = self._sheet(reactor)
            if not d or char is None:
                return
            char.d["resources"][f"item:{d['name']}:item_possibility"] = 1
            char.save()
            cur["ok"] = True
            self._line(R, f"{reactor['name']} uses {d['name']}'s New Possibility: the save succeeds instead", "New Possibility")
            return
        if fam == "item_twist":                                 # Twist of Fate: 3 charges, the outcome turned round
            e, d = self._wonder_item(reactor, fam)
            char = self._sheet(reactor)
            if not d or self._charges_left(e) < 3:
                return
            e = char.find_item(e["name"])
            e["charges_left"] = self._charges_left(e) - 3
            char.save()
            if window == "save_failed":
                cur["ok"] = True
                what = "the save succeeds"
            elif window == "save_ok":
                cur["ok"] = False
                what = "the save fails"
            elif window == "hit":
                cur.update(total=int(cur.get("ac") or 10) - 1, kept=min(int(cur.get("kept") or 1), 19), crit=False)
                what = "the attack misses"
            else:
                cur.update(total=max(int(cur.get("total") or 0), int(cur.get("ac") or 10)), kept=max(int(cur.get("kept") or 2), 2))
                what = "the attack hits"
            self._line(R, f"{reactor['name']} twists fate with the {d['name']}: {what} ({e['charges_left']} charges left)", "Twist of Fate")
            return
        if fam == "item_orb":                                   # an orb of shielding takes 1d4 off damage of its planes' types
            m = ORB_RE.search((rules.item(arg) or {}).get("text") or "")
            if not m:
                return
            left = cut = int(roll_dice(m.group(3)).total)
            dmg = []
            for n, t in cur.get("dmg") or []:
                take = min(n, left) if t in (m.group(1), m.group(2)) else 0
                left -= take
                dmg.append([n - take, t])
            cur["dmg"] = dmg
            self._line(R, f"{reactor['name']}'s {arg}: -{cut - left} damage", arg)
            return
        e, d = self._wonder_item(reactor, fam)
        char = self._sheet(reactor)
        if not d or not char:
            return
        if d.get("charges"):
            e = char.find_item(e["name"])
            e["charges_left"] = self._charges_left(e) - 1
        if fam in ("item_absorb", "item_shadow"):
            char.d["resources"][f"item:{d['name']}:{fam}"] = 1
        if fam == "item_spell_sink":
            e = char.find_item(e["name"])
            e["absorbed"] = int(e.get("absorbed") or 0) + int(R.get("slot_level") or 0)
            R["countered"] = True
            self._line(R, f"{reactor['name']}'s {d['name']} swallows the spell ({e['absorbed']}/{SPELL_SINK[d['name']][1]} levels)", d["name"])
        char.save()
        if fam == "item_scarab" and e.get("charges_left") == 0:
            self.chars.remove_item(char.name, e["name"], 1)
            self._say(f"{d['name']} crumbles into powder")
        if fam in ("item_evasion", "item_scarab"):
            cur["ok"] = True
            self._line(R, f"{reactor['name']} uses the {d['name']}: the save succeeds instead", d["name"])
        elif fam == "item_absorb":
            t = sorted(set(d.get("resist") or []) & {x for _n, x in cur.get("dmg") or []})[0]
            back = sum(n for n, x in cur.get("dmg") or [] if x == t) // 4      # half of what it would take (it resists that type)
            cur["dmg"] = [[0 if x == t else n, x] for n, x in cur.get("dmg") or []]
            self._heal(reactor, back)
            self._line(R, f"{reactor['name']}'s {d['name']} drinks the {t}: no damage, +{back} HP", d["name"])
        elif fam == "item_treachery":
            near = [o for o in self.b["combatants"] if o is not reactor and o.get("pos") and reactor.get("pos") and self._alive(o) and self._dist(reactor, o) <= 60]
            if near:
                victim = near[self.rng.randint(0, len(near) - 1)]      # random: an ally may take it
                passed = [[n, x] for n, x in cur.get("dmg") or [] if n]
                cur["dmg"] = [[0, x] for _n, x in cur.get("dmg") or []]
                self._line(R, f"{reactor['name']}'s Ring of Treachery passes the damage to {victim['name']}: "
                           + self._deal_rolled(victim, passed, by=reactor, label=d["name"]), d["name"])
        elif fam == "item_shadow":
            cur["dmg"] = [[n // 2, x] for n, x in cur.get("dmg") or []]
            self._line(R, f"{reactor['name']} turns insubstantial: half damage (Shadowfell Brand Tattoo)", "Shadowy Defense")
        elif fam == "item_snare":
            cut = int(roll_dice("1d10").total) + char.mod("dex")
            left, out = cut, []
            for n, x in cur.get("dmg") or []:
                take = min(n, max(0, left))
                left -= take
                out.append([n - take, x])
            cur["dmg"] = out
            self._line(R, f"{reactor['name']} snares the missile: -{cut} damage", d["name"])
        elif fam == "item_emblem":
            cur["crit"] = False
            self._line(R, f"{reactor['name']}'s Guardian Emblem turns the critical hit into a normal hit", d["name"])
        elif fam == "item_buckler":
            att = self._find_or_none(ctx.get("attacker"))
            if att is not None:
                self._stack().append(self._strike(reactor, "Sapphire Buckler", [att["id"]], mode="auto", parts=[["2d6", "thunder"]], magical=True))
        elif fam == "item_answer":                              # one melee attack with advantage; resistance and immunity don't count
            att = self._find_or_none(ctx.get("attacker"))
            w = next((x for x in char.attacks() if x["name"] == e["name"]), None)
            if att is not None and w is not None:
                answering = d["name"].startswith("Sword of Answering")
                S = self._strike(reactor, f"{d['name']} (answer)", [att["id"]], mode="attack",
                                 atk=dict(self._weapon_atk(reactor, w), adv="adv" if answering else None), magical=True)
                if answering:                                   # resistance and immunity don't count against it
                    S["ignore_resist"] = list(TYPES) + ["immune"]
                self._stack().append(S)
        elif fam == "item_retribution":
            att = self._find_or_none(ctx.get("attacker"))
            if att is not None:
                self._stack().append(self._strike(reactor, "Rod of Retribution", [att["id"]], mode="save", sv={"ab": "dex", "dc": 13, "half": True},
                                                  parts=[["2d10", "lightning"]], magical=True))

    def _wonder_charge_hit(self, R: dict, att: dict, arg: str, ctx: dict):
        """Charges poured into a hit: extra dice (a Staff of Striking's 1d6 force each), a Staff of Withering's save, a Blood
        Fury Tattoo's healing."""
        name, _sep, k = arg.partition("|")
        char = self._sheet(att)
        e = char.find_item(name) if char else None
        d = rules.item(e["name"]) if e else None
        ch = charge_hit(d)
        if not ch:
            return
        if ch.get("daily"):                                     # the Rogue Card: once a day, no charges
            n = 1
            char.d["resources"][f"item:{d['name']}:hit"] = 1
        else:
            n = max(1, min(int(k) if k.isdigit() else 1, ch["max"], self._charges_left(e)))
            e["charges_left"] = self._charges_left(e) - n
        char.save()
        cur = R.setdefault("cur", {})
        if ch["drain"]:                                         # rolled now: the hero heals by what it deals
            got = int(roll_dice(ch["dice"]).total) * n
            cur.setdefault("bonus_parts", []).append([str(got), ch["type"]])
            self._heal(att, got)
            note = f"+{got} {ch['type']}, heals {got}"
        else:
            dice = f"{n * int(ch['dice'].split('d')[0] or 1)}d{ch['dice'].split('d')[1]}"
            cur.setdefault("bonus_parts", []).append([dice, ch["type"]])
            note = f"+{dice} {ch['type']}"
        self._line(R, f"{att['name']} spends {n} charge{'s' if n > 1 else ''} of {d['name']}: {note} ({'once a day' if ch.get('daily') else str(e.get('charges_left')) + ' left'})", d["name"])
        tgt = self._find_or_none(ctx.get("target"))
        if ch.get("exhaust") and tgt is not None and self._alive(tgt):      # a Blood Amulet: DC 15 Con or a level of exhaustion
            res = self._saving_throw(tgt, "con", ch["exhaust"], label=d["name"])
            self._line(R, f"{tgt['name']} CON save vs {d['name']}: {res['total']} vs DC {ch['exhaust']} — " + ("saved" if res["ok"] else "exhausted"), d["name"])
            if not res["ok"]:
                self._exhaust(tgt, 1)
        if ch["save"] and tgt is not None:                      # Staff of Withering: Strength and Constitution falter for an hour
            self._apply_save(R, att, tgt, {"ab": "con", "dc": ch["save"], "rounds": 600,
                                           "mods": {"save_dis": ["str", "con"], "check_dis": ["str", "con"]}, "note": "withered"})

    def _wonder_zero_hp(self, c: dict) -> bool:
        """Lifewell Tattoo: dropping to 0, the wearer drops to 1 hit point instead, once a day."""
        char = self._sheet(c)
        found = next((e for e, _v in self._fxs(c, "life_ward")), None) if char else None
        if found is None:
            return False
        char.d["resources"][f"item:{found['name']}:life_ward"] = 1
        char.save()
        self._set_hp(c, 1)
        self._say(f"{c['name']} drops to 1 hit point instead ({found['name']})")
        return True

    # ------------------------------------------------------------------ the bar
    def wonder_options(self, c: dict) -> List[dict]:
        """The non-weapon magic items this hero can use now: [{'id', 'name', 'cost', 'target', 'tip', 'why', 'range', 'extra'}]."""
        char = self._sheet(c)
        if not char or c.get("form"):
            return []
        out = []
        seen = set()
        for e in char.d.get("inventory") or []:
            item = rules.item(e.get("name") or "")
            if not item or item["name"] in seen:
                continue
            seen.add(item["name"])
            for p in _acts_of(item["name"]):
                why = self._wonder_why(c, char, e, item, p)
                name = f"{p['name']} ({e['name']})" if p["name"] != item["name"].split(",")[0] else e["name"]
                cost = p["cost"]
                on = self._wonder_on(c, item["name"]) if p["kind"] == "buff" else None
                if on is not None and p.get("toggle"):
                    name = f"End {p['name'].lower()} ({e['name']})"
                    cost = p.get("off_cost") or cost
                    why = None
                extra = None
                lim = p.get("limit")
                if isinstance(lim, tuple) and (lim[0] == "beads" or len(lim) == 3):
                    left = self._wonder_left(e, item, p, char)
                    top = min(left, lim[2] if len(lim) == 3 else left)
                    if top > 1:
                        label = p.get("unit", "bead") if lim[0] == "beads" else "charge"
                        extra = {"options": [{"value": str(n), "label": f"{n} {label}{'s' if n > 1 else ''}"} for n in range(1, top + 1)]}
                if p.get("options"):
                    extra = {"options": list(p["options"])}
                tgt = dict(p["target"]) if p.get("target") else {"type": "self"}
                if p["kind"] == "recast":                       # Illusionist's Bracers: aimed like the cantrip itself
                    turn = c.get("turn") or {}
                    sp = rules.spell(turn.get("last_cantrip") or "")
                    if sp:
                        from . import spellbook as SB
                        spec = SB.spec(sp)
                        tgt, name = dict(spec["target"]), f"{sp['name']} again ({e['name']})"
                        extra = dict(extra or {}, area=spec["area"])
                    why = why or ("Cast a cantrip with your action first" if not sp else "Once a turn" if turn.get("bracers_done") else None)
                if p.get("who") == "ally":
                    tgt = {"type": "creature", "count": 1, "allies": True}
                elif p.get("who") == "area":
                    tgt = {"type": "self"}
                out.append({"id": f"wonder:{e['name']}|{p['key']}", "name": name, "cost": cost, "target": tgt, "range": p.get("range"),
                            "tip": p.get("tip") or "", "why": why, "extra": extra,
                            "uses": f"{self._wonder_left(e, item, p, char)} left" if isinstance(lim, tuple) else None})
        return out

    def _wonder_on(self, c: dict, item_name: str) -> Optional[dict]:
        return next((x for x in c.get("effects") or [] if (x.get("mods") or {}).get("wonder") == item_name and x.get("source_id") == c["id"]), None)

    def _wonder_left(self, entry: dict, item: dict, p: dict, char=None) -> int:
        if p.get("limit") and p["limit"][0] == "uses":         # a Bag of Tricks: three times until the next dawn
            return max(0, p["limit"][1] - int((char.d["resources"] if char else {}).get(f"item:{item['name']}:uses") or 0))
        if p.get("limit") and p["limit"][0] == "beads":
            if entry.get("charges_left") is not None:
                return int(entry["charges_left"])
            m = re.search(r"(?:has|contains) (\d+)d(\d+) \+ (\d+) (?:beads|doses)", item.get("text") or "")
            return int(m.group(1)) * (int(m.group(2)) + 1) // 2 + int(m.group(3)) if m else 6     # the average, until counted
        return self._charges_left(entry)

    def _wonder_why(self, c: dict, char, entry: dict, item: dict, p: dict) -> Optional[str]:
        if item.get("attune") is not None and not entry.get("attuned"):
            return f"{entry['name']} needs attunement"
        if (p.get("worn") or _needs_wearing(item)) and not entry.get("equipped"):
            return f"Equip {entry['name']} first"
        if p.get("kind") == "summon" and any(o.get("summoned_by") == c["id"] and o.get("summon_spell") == item["name"] and self._alive(o)
                                             for o in self.b["combatants"]):
            return "Already summoned"
        if p.get("needs_on") and self._wonder_on(c, item["name"]) is None:
            return "Activate it first"                       # (Tramontane armour: the tendrils must be out)
        lim = p.get("limit")
        if lim == "daily" and char.d["resources"].get(f"item:{item['name']}:{p['key']}"):
            return "Used until the next dawn"
        if isinstance(lim, tuple) and self._wonder_left(entry, item, p, char) < (lim[1] if lim[0] == "charges" else 1):
            return {"beads": f"No {p.get('unit', 'bead')}s left", "uses": "No uses left until the next dawn"}.get(lim[0], "No charges left")
        return None

    def use_wonder(self, cid: int, item: str, key: str, targets: Optional[List[int]] = None, point=None, option: Optional[str] = None,
                   adv: Optional[str] = None) -> str:
        """Use a magic item's power from the bar (see activations)."""
        with self.lock:
            self._busy()
            c = self._find(cid)
            char = self._sheet(c)
            if c.get("form"):
                raise ServiceError(f"{c['name']} can't use that in {c['form']['name'].lower()} form.")
            entry = char.find_item(item) if char else None
            data = rules.item(entry["name"]) if entry else None
            p = next((x for x in _acts_of(data["name"]) if x["key"] == key), None) if data else None
            if not p:
                raise ServiceError(f"{item} can't do that.")
            if p["kind"] == "buff":
                return self._wonder_buff(c, char, entry, data, p, targets)
            why = self._wonder_why(c, char, entry, data, p)
            if why:
                raise ServiceError(why)
            lim = p.get("limit")
            n = 1
            if isinstance(lim, tuple) and (lim[0] == "beads" or len(lim) == 3) and str(option or "").isdigit():
                n = max(1, min(int(option), self._wonder_left(entry, data, p, char), lim[2] if len(lim) == 3 else 99))
            if p["kind"] == "fireball":
                return self._wonder_fireball(c, char, entry, data, p, n, targets, point)
            if p["kind"] in ("attack", "auto"):
                return self._wonder_attack(c, char, entry, data, p, n, targets, adv)
            if p["kind"] == "regain":
                return self._wonder_regain(c, char, entry, data, p)
            if p["kind"] == "heal":
                return self._wonder_heal(c, char, entry, data, p, targets)
            if p["kind"] == "zone":
                return self._wonder_zone(c, char, entry, data, p)
            if p["kind"] == "teleport":
                return self._wonder_teleport(c, char, entry, data, p, point)
            if p["kind"] == "wand_of_wonder":
                return self._wand_of_wonder(c, char, entry, data, p, targets, point)
            if p["kind"] == "bomb":
                return self._wonder_bomb(c, char, entry, data, p, targets, point)
            if p["kind"] == "cube":
                return self._wonder_cube(c, char, entry, data, p, option)
            if p["kind"] == "recast":
                turn = c.get("turn") or {}
                sp = rules.spell(turn.get("last_cantrip") or "")
                if not sp:
                    raise ServiceError("Cast a cantrip with your action first.")
                if turn.get("bracers_done"):
                    raise ServiceError("The bracers repeat one cantrip a turn.")
                from . import spellbook as SB
                spec = SB.spec(sp)
                self._precheck(c, dict(sp, ability="int"), dict(spec, cost="bonus"), 0, targets, point, False)
                turn["bracers_done"] = True
                mod = self._casting_mod(c)
                self._say(f"{c['name']}'s {data['name']}: {sp['name']} again")
                return self._cast_on(c, sp, None, slot_level=0, caster_level=char.total_level, mod=mod, attack_bonus=char.proficiency_bonus + mod,
                                     dc=self._spell_dc(c), adv=adv, targets=targets, point=point, paid=True, mm={"cost_override": "bonus"})
            if p["kind"] == "doom":
                tgt = self._target((targets or [None])[0])
                if c.get("pos") and tgt.get("pos") and self._dist(c, tgt) > 30:
                    raise ServiceError(f"{tgt['name']} is out of range (30 ft).")
                self._pay(c, p["cost"], data["name"])
                note = self._wonder_spend(c, char, entry, data, p)
                for o in self.b["combatants"]:                  # one doomed creature at a time
                    for e in [e for e in o.get("effects") or [] if e["name"] == "Doom Foretold" and e.get("source_id") == c["id"]]:
                        self._effect_off(o, e, "a new doom")
                self._effect_on(tgt, "Doom Foretold", [], None, None, None, 600, c["name"], {"extra_damage": ("1d6", "")}, None, c["id"])
                line = f"{c['name']} foretells {tgt['name']}'s doom{note}"
                self._commit(line)
                return line
            if p["kind"] == "random_spell":
                sp = rules.spell(self.rng.choice(p["spells"]))
                tgt = self._find_or_none((targets or [None])[0])
                aim = point or (list(G.centre(tgt["pos"], tgt.get("span") or 1)) if tgt and tgt.get("pos") else None)
                level = min(9, p["level"] + n - 1)
                from . import spellbook as SB
                self._precheck(c, dict(sp, ability="int"), dict(SB.spec(sp), cost="action"), level, targets, aim, False)
                note = self._wonder_spend(c, char, entry, data, p, n)
                self._say(f"{c['name']} fires the {data['name']}{note}: {sp['name']}")
                return self._cast_on(c, sp, None, slot_level=level, caster_level=char.total_level, mod=0, attack_bonus=5, dc=p["dc"], adv=None,
                                     targets=targets, point=aim, paid=True, mm={"cost_override": "action"})
            if p["kind"] in ("vessel", "transform", "talisman"):
                return self._wonder_craft(c, char, entry, data, p, option, targets)      # spellitems.py
            if p["kind"] in ("sphere", "talons", "gem", "puzzle"):
                return self._wonder_odd(c, char, entry, data, p, targets, point, option)
            if p["kind"] == "summon":
                return self._wonder_summon(c, char, entry, data, p, point)
            if p["kind"] == "more_zone":
                return self._more_zone(c, char, entry, data, p)
            if p["kind"] == "battery":
                return self._more_battery(c, char, entry, data, p)
            if p.get("dice_per_charge") or p.get("type_option"):
                p = self._more_prep(c, char, p, n, option)       # a Wand of Teeth's dice, an Orb of Damara's breath (itemmore.py)
            return self._wonder_save(c, char, entry, data, p, targets, point)

    def _wonder_regain(self, c: dict, char, entry: dict, data: dict, p: dict) -> str:
        """Pearl of Power, Rod of the Pact Keeper, Rhythm-Maker's Drum, Dragonhide Belt: a spent resource back."""
        from ...rules import spellcasting as SC
        what = p["regain"]
        used = char.d.setdefault("slots_used", {})
        if str(what).startswith("slot"):                       # "slot3": a Pearl of Power; "slot2": Atonement's Arcane Fever (no bigger one)
            top = int(what[4:])
            spent = sorted((int(k) for k, v in used.items() if k != SC.PACT_KEY and str(k).isdigit() and int(v or 0) > 0), reverse=True)
            low = [k for k in spent if k <= top]
            if not spent or (top != 3 and not low):
                raise ServiceError(f"{c['name']} has no spent spell slot" + (f" of level {top} or lower." if top != 3 else "."))
            key = str(low[0] if low else spent[-1])             # (a spent 4th-level slot or higher should come back as a 3rd-level one:
            got = f"a level {key} spell slot"                   # the sheet has no such slot to give, so that one comes back)
        elif what == "pact":
            if not int(used.get(SC.PACT_KEY) or 0):
                raise ServiceError(f"{c['name']} has no spent warlock slot.")
            key, got = SC.PACT_KEY, "a warlock spell slot"
        else:
            res, amount = what
            have = int(char.d["resources"].get(res) or 0)
            if have <= 0:
                raise ServiceError(f"{c['name']} has spent no {res}.")
            if amount == "martial":
                die = re.sub(r"^1?d", "1d", str(char.table_value("Monk", "Martial Arts") or "1d4"))
                amount = int(roll_dice(die).total)
            back = min(have, int(amount))
            char.d["resources"][res] = have - back
            key, got = None, f"{back} {res}"
        if key is not None:
            used[key] = max(0, int(used.get(key) or 0) - 1)
        self._pay(c, p["cost"], data["name"])
        note = self._wonder_spend(c, char, entry, data, p)
        line = f"{c['name']} uses {data['name']}{note}: regains {got}"
        if p.get("self_damage"):                                # the price: damage nothing reduces (Arcane Fever)
            self._say(line)
            line = self._deal_rolled(c, self._roll_parts(p["self_damage"]), label=data["name"], ignore_resist=list(TYPES) + ["immune"])
        self._commit(line)
        return line

    WAND_OF_WONDER = [(5, "spell", "Slow"), (10, "spell", "Faerie Fire"), (15, "stunned", None), (20, "spell", "Gust of Wind"),
                      (25, "nothing", "you sense the target's thoughts (Detect Thoughts)"), (30, "spell", "Stinking Cloud"),
                      (33, "nothing", "heavy rain falls in a 60-foot radius"), (36, "nothing", "an animal appears and runs off"),
                      (46, "spell", "Lightning Bolt"), (49, "zone", "a cloud of 600 oversized butterflies"),
                      (53, "nothing", "the target grows larger for a moment"), (58, "spell", "Darkness"), (62, "nothing", "grass sprouts all around"),
                      (65, "nothing", "an object vanishes"), (69, "nothing", "you shrink for a moment"), (79, "spell", "Fireball"),
                      (84, "self_spell", "Invisibility"), (87, "nothing", "leaves sprout from the target"), (90, "gems", None),
                      (95, "burst", None), (97, "nothing", "your skin turns bright blue"), (100, "stone", None)]

    def _wand_of_wonder(self, c: dict, char, entry: dict, data: dict, p: dict, targets, point) -> str:
        """The Wand of Wonder (DMG): a d100 on its table. Its spells use DC 15; the harmless results are told, not played."""
        tgt = self._find_or_none((targets or [None])[0])
        aim = point or (list(G.centre(tgt["pos"], tgt.get("span") or 1)) if tgt and tgt.get("pos") else None)
        if tgt and c.get("pos") and tgt.get("pos") and self._dist(c, tgt) > 120:
            raise ServiceError(f"{tgt['name']} is out of range (120 ft).")
        r = self.rng.randint(1, 100)
        kind, what = next((k, w) for top, k, w in self.WAND_OF_WONDER if r <= top)
        note = self._wonder_spend(c, char, entry, data, p)
        self._say(f"{c['name']} waves the {data['name']}{note}: d100 {r}")
        if kind in ("spell", "self_spell"):
            sp = rules.spell(what)
            if sp:
                ids = [c["id"]] if kind == "self_spell" else ([tgt["id"]] if tgt else None)
                return self._cast_on(c, sp, None, slot_level=sp["level"], caster_level=char.total_level, mod=0, attack_bonus=7, dc=15, adv=None,
                                     targets=ids, point=None if kind == "self_spell" else aim, paid=True, mm={"cost_override": "action"})
            kind = "nothing"
        self._pay(c, p["cost"], data["name"])
        S = None
        if kind == "stunned":
            self._effect_on(c, data["name"], ["Stunned"], None, None, None, None, c["name"], None, None, c["id"], until={"start": c["id"]})
            line = f"{c['name']} is stunned until the start of its next turn"
        elif kind == "zone" and aim and c.get("pos"):
            tiles = G.area_for({"shape": "sphere", "size": 30, "origin": "point"}, c["pos"], c.get("span") or 1, tuple(aim), *self._bounds())
            self._add_zone(c, "Butterflies (Wand of Wonder)", tiles, {"obscure": "heavy", "parts": []}, rounds=100, point=list(aim))
            line = f"{what}: the area is heavily obscured for 10 minutes"
        elif kind == "gems" and tgt:
            n = int(roll_dice("1d4").total) * 5
            S = self._strike(c, f"{data['name']} (gems)", [tgt["id"]], mode="auto", parts=[[str(n), "bludgeoning"]], magical=True)
            line = f"a stream of {n} gems pelts {tgt['name']}"
        elif kind == "burst" and c.get("pos"):
            ids = [o["id"] for o in self.b["combatants"] if not self._is_out(o) and o.get("pos") and self._dist(o, c) <= 30]
            S = self._strike(c, data["name"], ids, mode="save", sv={"ab": "con", "dc": 15, "half": False, "conds": ["Blinded"], "repeat": "end",
                                                                    "rounds": 10}, parts=[], magical=True)
            line = "a burst of colourful light (30 ft): Con saves or blinded"
        elif kind == "stone" and tgt:
            S = self._strike(c, data["name"], [tgt["id"]], mode="save", sv={"ab": "con", "dc": 15, "half": False, "conds": ["Restrained"],
                                                                            "repeat": "end", "mods": {"stoning": True}, "fail5": ["Petrified"]},
                             parts=[], magical=True)
            line = f"{tgt['name']} begins to turn to stone"
        else:
            line = what or "nothing happens"
        self._say(f"{data['name']}: {line}")
        out = self._run_r(S) if S else line
        self._commit()
        return out

    def _wonder_bomb(self, c: dict, char, entry: dict, data: dict, p: dict, targets, point) -> str:
        """A Gnomengarde Grenade, smokepowder: thrown, it bursts - each of its saves in turn for everyone in the blast."""
        if not c.get("pos"):
            raise ServiceError("Put the hero on the map to throw it.")
        tgt = self._find_or_none((targets or [None])[0])
        aim = point or (list(G.centre(tgt["pos"], tgt.get("span") or 1)) if tgt and tgt.get("pos") else None)
        if aim is None:
            raise ServiceError("Pick where to throw it.")
        if G.distance_to_point(c["pos"], c.get("span") or 1, aim) > p["range"]:
            raise ServiceError(f"That's out of range ({p['range']} ft).")
        area = p["target"]["area"]
        tiles = V.filter_area(self._terrain(), tuple(aim), G.area_for(area, c["pos"], c.get("span") or 1, tuple(aim), *self._bounds()))
        ids = [o["id"] for o in G.creatures_in(tiles, self.b["combatants"]) if not self._is_out(o)]
        self._pay(c, p["cost"], data["name"])
        note = self._wonder_spend(c, char, entry, data, p)
        self._area_vfx(c, tiles, p["blasts"][0]["parts"], "sphere", aim)
        self._say(f"{c['name']} throws {data['name']}{note}: it explodes")
        if not ids:
            self._commit(f"{data['name']} explodes: nobody in the blast")
            return f"{data['name']} explodes: nobody in the blast"
        strikes = [self._strike(c, data["name"], ids, mode="save", magical=True, origin=list(aim), parts=b["parts"],
                                sv={"ab": b["ab"], "dc": b["dc"], "half": True, "conds": list(b.get("conds") or []), "until": b.get("until")})
                   for b in p["blasts"]]
        first = strikes[0]
        first["follow"] = strikes[1:]
        out = self._run_r(first)
        self._commit()
        return out

    def _wonder_odd(self, c: dict, char, entry: dict, data: dict, p: dict, targets, point, option) -> str:
        """Sphere of Annihilation, and the Talons, Gem and Puzzle Cards."""
        kind = p["kind"]
        if kind == "gem":
            sp = rules.spell(str(option or "")) or rules.spell("Chain Lightning")
            from . import spellbook as SB
            self._precheck(c, dict(sp, ability="int"), dict(SB.spec(sp), cost="action"), 6, targets, point, False)
            note = self._wonder_spend(c, char, entry, data, p)
            self._say(f"{c['name']} brandishes the {data['name']}{note}: {sp['name']}")
            return self._cast_on(c, sp, None, slot_level=6, caster_level=char.total_level, mod=0, attack_bonus=9, dc=17, adv=None,
                                 targets=targets, point=point, paid=True, mm={"cost_override": "action"})
        if kind == "talons":
            tgt = self._target((targets or [None])[0])
            if c.get("pos") and tgt.get("pos") and self._dist(c, tgt) > 120:
                raise ServiceError(f"{tgt['name']} is out of range (120 ft).")
            self._pay(c, p["cost"], data["name"])
            note = self._wonder_spend(c, char, entry, data, p)
            self._effect_on(tgt, data["name"], [], None, None, None, 10, c["name"], {"items_suppressed": True}, None, c["id"])
            line = f"{c['name']} brandishes the {data['name']}{note}: {tgt['name']}'s magic items fall silent for 1 minute"
        elif kind == "puzzle":
            self._pay(c, p["cost"], data["name"])
            note = self._wonder_spend(c, char, entry, data, p)
            n = 0
            for dr in self.b.get("drawings") or []:            # the map's trap symbols within 60 ft
                if dr.get("sym") == "trap" and c.get("pos") and max(abs(dr.get("x", 0) - c["pos"][0]), abs(dr.get("y", 0) - c["pos"][1])) <= 12 \
                        and not dr.get("disabled"):
                    dr["disabled"] = True
                    n += 1
            line = f"{c['name']} holds up the {data['name']}{note}: {n} trap{'s' if n != 1 else ''} within 60 ft disabled"
        else:                                                   # the sphere
            if point is None or not c.get("pos"):
                raise ServiceError("Pick where the sphere goes.")
            z = next((x for x in self.b.get("zones") or [] if x.get("name") == data["name"]), None)
            to = [int(point[0]), int(point[1])]
            self._pay(c, p["cost"], data["name"])
            if z is None:                                       # first use: it is where the DM says (here: the point picked)
                z = self._add_zone(c, data["name"], [to], {"save": "dex", "half": False, "parts": [["4d10", "force"]], "enter": True, "conds": []},
                                   rounds=None, dc=13, point=[to[0] + .5, to[1] + .5])
                line = f"The {data['name']} hangs in the air"
            else:
                at = z["tiles"][0]
                if max(abs(at[0] - c["pos"][0]), abs(at[1] - c["pos"][1])) * 5 > 60:
                    raise ServiceError("The sphere is more than 60 ft away.")
                total = self._check(c, "Arcana")
                if total >= 25:
                    reach = max(5, 5 * char.mod("int")) // 5
                    dx, dy = to[0] - at[0], to[1] - at[1]
                    k = max(abs(dx), abs(dy)) or 1
                    step = min(k, reach)
                    new = [at[0] + round(dx / k * step), at[1] + round(dy / k * step)]
                    line = f"{c['name']} steers the sphere (Arcana {total} vs DC 25)"
                else:
                    dx, dy = c["pos"][0] - at[0], c["pos"][1] - at[1]
                    k = max(abs(dx), abs(dy)) or 1
                    new = [at[0] + round(dx / k * min(2, k)), at[1] + round(dy / k * min(2, k))]
                    line = f"The sphere drifts 10 ft toward {c['name']} (Arcana {total} vs DC 25)"
                z["tiles"] = [new]
                z["point"] = [new[0] + .5, new[1] + .5]
                self._zone_vfx("move", z, d=[new[0] - at[0], new[1] - at[1]])
            hit = [o["id"] for o in G.creatures_in({tuple(z["tiles"][0])}, self.b["combatants"]) if not self._is_out(o)]
            if hit:
                self._say(line)
                out = self._run_r(self._strike(c, data["name"], hit, mode="save", sv={"ab": "dex", "dc": 13, "half": False},
                                               parts=[["4d10", "force"]], magical=True))
                self._commit()
                return out
        self._commit(line)
        return line

    def _wonder_cube(self, c: dict, char, entry: dict, data: dict, p: dict, option) -> str:
        """A Cube of Force: a barrier round the user for a minute (the face's charges spent); face 6 ends it."""
        face = int(option) if str(option or "").isdigit() and 2 <= int(option) <= 6 else 5
        old = self._wonder_on(c, data["name"])
        if face != 6 and self._charges_left(entry) < face:
            raise ServiceError(f"{data['name']} has {self._charges_left(entry)} charges left.")
        self._pay(c, p["cost"], data["name"])
        if old is not None:
            self._effect_off(c, old, "another face" if face != 6 else "switched off")
        if face == 6:
            self._commit(f"{c['name']} switches the {data['name']} off")
            return f"{c['name']} switches the {data['name']} off"
        left = self._charges_left(entry)
        if left < face:
            raise ServiceError(f"{data['name']} has {left} charges left.")
        entry["charges_left"] = left - face
        char.save()
        self._effect_on(c, data["name"], [], None, None, None, 10, c["name"], {"barrier": face, "wonder": data["name"]}, None, c["id"])
        what = {2: "objects and missiles", 3: "living creatures", 4: "spells", 5: "everything"}[face]
        line = f"{c['name']} presses face {face} of the {data['name']}: a barrier that stops {what} ({entry['charges_left']} charges left)"
        self._commit(line)
        return line

    def _wonder_teleport(self, c: dict, char, entry: dict, data: dict, p: dict, point) -> str:
        """A blink to a free space within the item's reach (and, with a Kagonesti Forest Shroud, advantage on the next attack)."""
        if point is None or not c.get("pos"):
            raise ServiceError("Pick where to appear.")
        x, y = int(point[0]), int(point[1])
        if G.distance_to_point(c["pos"], c.get("span") or 1, point) > p["range"]:
            raise ServiceError(f"That's out of reach ({p['range']} ft).")
        if not self._tile_ok(c, x, y):
            raise ServiceError("That space is taken or off the map.")
        self._pay(c, p["cost"], data["name"])
        note = self._wonder_spend(c, char, entry, data, p)
        self._vfx("blink", id=c["id"], at=c.get("pos"), to=[x, y])
        c["pos"] = [x, y]
        if p.get("adv_after"):
            self._effect_on(c, data["name"], [], None, None, None, None, c["name"], {"attacks_with": "adv", "once": True}, None, c["id"],
                            until={"end": c["id"], "skip": 0})
        line = f"{c['name']} uses {data['name']}{note}: teleports"
        self._commit(line)
        return line

    def _wonder_zone(self, c: dict, char, entry: dict, data: dict, p: dict) -> str:
        """Eversmoking Bottle: opened, a cloud round the user (its tiles stay where it was opened); opened again: closed."""
        old = next((z for z in self.b.get("zones") or [] if z.get("owner") == c["id"] and z.get("name") == data["name"]), None)
        self._pay(c, p["cost"], data["name"])
        if old is not None:
            self._zone_off(old, "the bottle is closed")
            line = f"{c['name']} closes the {data['name']}"
        else:
            if not c.get("pos"):
                raise ServiceError("Put the hero on the map first.")
            tiles = G.area_for({"shape": "emanation", "size": p["size"], "origin": "caster", "exclude_self": False}, c["pos"], c.get("span") or 1,
                               None, *self._bounds())
            self._add_zone(c, data["name"], tiles, dict(p["zone"]), rounds=None, point=list(G.centre(c["pos"], c.get("span") or 1)))
            line = f"{c['name']} opens the {data['name']}: thick smoke fills {p['size']} ft around"
        self._commit(line)
        return line

    def _wonder_heal(self, c: dict, char, entry: dict, data: dict, p: dict, targets) -> str:
        """Keoghtom's Ointment: a dose swallowed or rubbed on (the user or a creature within reach)."""
        tgt = self._find((targets or [c["id"]])[0])
        if tgt is not c and c.get("pos") and tgt.get("pos") and self._dist(c, tgt) > (p.get("range") or 5):
            raise ServiceError(f"{tgt['name']} is too far away.")
        if self._dead(tgt):
            raise ServiceError(f"{tgt['name']} is dead.")
        self._pay(c, p["cost"], data["name"])
        each = int(data.get("charges") or 1) if str(data.get("charges") or "").isdigit() else 1      # (a stack of coins: drained one at a time)
        last = p.get("last_frees") and self._wonder_left(entry, data, p, char) - 1 <= each * (int(entry.get("qty") or 1) - 1)
        note = self._wonder_spend(c, char, entry, data, p)
        n = int(roll_dice(p["dice"]).total)
        if p.get("temp"):                                       # a Soul Coin's Drain Life: temporary hit points
            self._give_temp(tgt, n)
            if last:                                            # "expending all of the coin's charges" frees the soul: the coin is gone
                self.chars.remove_item(char.name, entry["name"], 1)
                note += f"; the soul is freed and {entry['name']} rusts away"
            line = f"{c['name']} uses {data['name']}{note}: {n} temporary hit points"
            self._commit(line)
            return line
        self._heal(tgt, n)
        for cond in p.get("cure") or []:
            for e in [e for e in tgt.get("effects") or [] if cond in (e.get("conditions") or [])]:
                self._effect_off(tgt, e, data["name"])
            if cond in self._conds(tgt):
                self._cond(tgt, cond, False)
        line = f"{c['name']} uses {data['name']}{note}" + (f" on {tgt['name']}" if tgt is not c else "") + f": +{n} HP"
        self._commit(line)
        return line

    def _wonder_summon(self, c: dict, char, entry: dict, data: dict, p: dict, point) -> str:
        """Figurines of Wondrous Power, Bags of Tricks, Elemental Gems, a Horn of Valhalla: creatures on the user's side."""
        mids = p["monsters"]
        mid = mids[self.rng.randint(0, len(mids) - 1)] if len(mids) > 1 else mids[0]
        count = p["count"] if isinstance(p["count"], int) else int(roll_dice(p["count"]).total)
        if point is not None and c.get("pos"):
            if G.distance_to_point(c["pos"], c.get("span") or 1, point) > (p.get("range") or 60):
                raise ServiceError(f"That point is out of range ({p.get('range') or 60} ft).")
            self._summon_point = (int(point[0]), int(point[1]))
        self._pay(c, p["cost"], data["name"])
        try:
            made = self._add_summons(c, mid, count, None, 1, None, None, None, None, data["name"])
        finally:
            self._summon_point = None
        note = self._wonder_spend(c, char, entry, data, p)
        if data["name"] == "Efreeti Bottle" and self.rng.randint(1, 100) <= 10:
            for m in made:                                      # the efreeti attacks the one who freed it
                m.update(faction=0, turned=True)
            note += " - the efreeti turns on you!"
        for m in made:
            self._vfx("summon", id=m["id"], type=str((self._monster(m) or {}).get("type") or "").lower(), src=None, tier=1)
        line = f"{c['name']} uses {data['name']}{note}: " + ", ".join(m["name"] for m in made) + " appear" + ("s" if len(made) == 1 else "")
        self._commit(line)
        return line

    def _wonder_spend(self, c: dict, char, entry: dict, data: dict, p: dict, n: int = 1) -> str:
        """Pay the item's price (charges, the day's use, the item itself); returns a note for the log."""
        n = p.get("spend_n") or n                               # a Wand of Teeth: the charges chosen (itemmore._more_prep)
        lim = p.get("limit")
        note, gone = "", False
        if lim == "daily":
            char.d["resources"][f"item:{data['name']}:{p['key']}"] = 1
            note = " (once a day)"
        elif isinstance(lim, tuple) and lim[0] == "uses":
            k = f"item:{data['name']}:uses"
            char.d["resources"][k] = int(char.d["resources"].get(k) or 0) + 1
            note = f" ({lim[1] - char.d['resources'][k]} uses left today)"
        elif isinstance(lim, tuple):
            spend = n * (lim[1] if lim[0] == "charges" else 1)
            left = self._wonder_left(entry, data, p, char) - spend
            entry["charges_left"] = max(0, left)
            note = f" ({spend} {p.get('unit', 'bead') if lim[0] == 'beads' else 'charge'}{'s' if spend != 1 else ''}, {max(0, left)} left)"
            if lim[0] == "charges" and left <= 0 and re.search(r"last charge, roll a d20\. On a 1", data.get("text") or ""):
                if int(roll_dice("1d20").total) == 1:
                    gone = True
                    note += f"; {entry['name']} crumbles to dust"
            gone = gone or (lim[0] == "beads" and left <= 0)
        elif lim == "consume":
            gone = True
        char.save()
        if gone:                                                # after the save: the pack is read again from the sheet
            self.chars.remove_item(char.name, entry["name"], 1)
        return note

    def _wonder_save(self, c: dict, char, entry: dict, data: dict, p: dict, targets, point) -> str:
        sv = dict(p["sv"])
        area = p.get("area")
        label = p["name"] if p["name"] != data["name"].split(",")[0] else data["name"]
        if area:
            if not c.get("pos"):
                raise ServiceError("Put the hero on the map to aim it.")
            aim = point or self.b.get("aim")
            ids = list(targets or self.b.get("targets") or [])
            if aim is None and ids:
                t = self._find(ids[0])
                aim = list(G.centre(t["pos"], t.get("span") or 1)) if t.get("pos") else None
            if area["origin"] == "point" and aim is None:
                raise ServiceError("Pick where to aim it.")
            if area["origin"] == "point" and p.get("range") and G.distance_to_point(c["pos"], c.get("span") or 1, aim) > p["range"]:
                raise ServiceError(f"That point is out of range ({p['range']} ft).")
            tiles = G.area_for(dict(area, exclude_self=not p.get("self_too")), c["pos"], c.get("span") or 1, tuple(aim) if aim else None,
                               *self._bounds())
            origin = G.centre(c["pos"], c.get("span") or 1) if area["origin"] == "caster" else tuple(aim)
            tiles = V.filter_area(self._terrain(), origin, tiles)
            hit = [o["id"] for o in G.creatures_in(tiles, self.b["combatants"]) if (o is not c or p.get("self_too")) and not self._is_out(o)
                   and (not area.get("choice") or self._hostile(o, c)) and (p.get("only") != "ferrous" or self._ferrous(o))
                   and (p.get("only") != "vampire" or "vampire" in str((self._monster(o) or {}).get("name") or "").lower())]
            self._pay(c, p["cost"], label)
            note = self._wonder_spend(c, char, entry, data, p)
            self._area_vfx(c, tiles, p["parts"], area.get("shape", ""), aim)
            self._say(f"{c['name']} uses {data['name']}{note}")
            if not hit:
                self._commit(f"{c['name']}'s {label}: nobody in the area")
                return f"{c['name']}'s {label}: nobody in the area"
            S = self._strike(c, label, hit, mode="save", sv=sv, parts=p["parts"], magical=True,
                             origin=list(origin) if area["origin"] == "point" else None)
        else:
            tgt = self._target((targets or [None])[0])
            if c.get("pos") and tgt.get("pos") and p.get("range") and self._dist(c, tgt) > p["range"]:
                raise ServiceError(f"{tgt['name']} is out of range ({p['range']} ft).")
            if p.get("target_cond") and not set(p["target_cond"]) & set(self._conds(tgt)):
                raise ServiceError(f"{tgt['name']} must be {' or '.join(x.lower() for x in p['target_cond'])}.")
            self._pay(c, p["cost"], label)
            note = self._wonder_spend(c, char, entry, data, p)
            self._say(f"{c['name']} uses {data['name']}{note}")
            ids = [tgt["id"]] + [t for t in dict.fromkeys(targets or []) if t != tgt["id"]][:max(0, int(p["target"].get("count") or 1) - 1)]
            S = self._strike(c, label, ids, mode="save", sv=sv, parts=p["parts"], magical=True)     # (a Void Card: up to three)
        out = self._run_r(S)
        if p.get("drain") and sum((S.get("dealt") or {}).values()) > 0 and self._alive(c):     # the Balance Card drinks what it drains
            n = sum(S["dealt"].values())
            self._heal(c, n)
            out += "\n" + f"{c['name']} regains {n} HP"
        if re.search(r"20 percent chance|20% chance of causing the horn to explode", data.get("text") or "") and self.rng.randint(1, 100) <= 20:
            out += "\n" + f"{data['name']} explodes: " + self._deal_rolled(c, self._roll_parts([["10d6", "fire"]]), label=data["name"])
            self.chars.remove_item(char.name, entry["name"], 1)       # the Horn of Blasting bursts in its blower's hands
        self._commit()
        return out

    def _wonder_attack(self, c: dict, char, entry: dict, data: dict, p: dict, n: int, targets, adv) -> str:
        tgt = self._target((targets or [None])[0])
        if c.get("pos") and tgt.get("pos") and p.get("range") and self._dist(c, tgt) > p["range"]:
            raise ServiceError(f"{tgt['name']} is out of range ({p['range']} ft).")
        ab = p.get("ability") or "dex"
        if ab == "spell":                                       # "your spellcasting modifier (or your Intelligence modifier...)"
            from ...rules import spellcasting as SC
            infos = SC.casters(char)
            ab = infos[0]["ability"] if infos else "int"
        bonus = p["bonus"] if p.get("bonus") is not None else char.proficiency_bonus + char.mod(ab)
        parts = [[str(d).replace("+DEX", f"{char.mod('dex'):+d}").replace("+STR", f"{char.mod('str'):+d}"), t] for d, t in p["parts"]]
        if p.get("per_charge") and n > 1:
            parts = [[f"{n * int(d.split('d')[0] or 1)}d{d.split('d')[1]}" if re.fullmatch(r"\d*d\d+", str(d)) else d, t] for d, t in parts]
        label = p["name"] if p["name"] != data["name"].split(",")[0] else data["name"]
        self._pay(c, p["cost"], label)
        note = self._wonder_spend(c, char, entry, data, p, n if p.get("per_charge") else 1)
        self._say(f"{c['name']} uses {data['name']}{note}")
        if p["kind"] == "auto":                                 # the Crown of Whirling Comets' bolts: they just hit
            out = self._run_r(self._strike(c, label, [tgt["id"]], mode="auto", parts=parts, magical=True))
            self._commit()
            return out
        atk = {"bonus": bonus, "n": int(p.get("n") or 1), "melee": p.get("melee", False), "spell": p.get("spell", True), "magical": True, "parts": parts,
               "weapon": bool(p.get("weapon")),
               "adv": adv, "normal": p.get("range"), "long": p.get("range"), "reach": p.get("range") or 5}
        on_hit = {"name": data["name"], "conds": list(p["on_hit"]), "rounds": p.get("on_hit_rounds"),
                  "mods": {"held": True} if p.get("on_hit_rounds") else None} if p.get("on_hit") else None     # Iron Bands: restrained
        out = self._run_r(self._strike(c, label, [tgt["id"]], mode="attack", atk=atk, magical=True, on_hit=on_hit,
                                       rider=dict(p["rider"]) if p.get("rider") else None))
        self._commit()
        return out

    def _wonder_fireball(self, c: dict, char, entry: dict, data: dict, p: dict, n: int, targets, point) -> str:
        from . import spellbook as SB
        sp = rules.spell("Fireball")
        if not sp:
            raise ServiceError("Fireball isn't in the rules.")
        level = min(9, p["level"] + n - 1)
        spec = SB.spec(sp)
        self._precheck(c, dict(sp, ability="int"), dict(spec, cost="action", range=p.get("range") or spec.get("range")), level, targets, point, False)
        note = self._wonder_spend(c, char, entry, data, p, n)
        self._say(f"{c['name']} hurls {n} bead{'s' if n > 1 else ''} from the {data['name']}{note}")
        return self._cast_on(c, sp, None, slot_level=level, caster_level=char.total_level, mod=0, attack_bonus=5, dc=p["dc"], adv=None,
                             targets=targets, point=point, paid=True, mm={"cost_override": "action"})

    def _wonder_buff(self, c: dict, char, entry: dict, data: dict, p: dict, targets) -> str:
        on = self._wonder_on(c, data["name"])
        if on is not None and p.get("toggle"):
            self._pay(c, p.get("off_cost") or p["cost"], f"{data['name']} off")
            self._effect_off(c, on, "switched off")
            line = f"{c['name']}'s {data['name']}: off"
            self._commit(line)
            return line
        why = self._wonder_why(c, char, entry, data, p)
        if why:
            raise ServiceError(why)
        who = [c]
        if p.get("who") == "ally":
            t = self._target((targets or [None])[0])
            if self._hostile(t, c):
                raise ServiceError(f"{t['name']} isn't willing.")
            if c.get("pos") and t.get("pos") and self._dist(c, t) > (p.get("range") or 30):
                raise ServiceError(f"{t['name']} is out of range ({p.get('range') or 30} ft).")
            who = [t]
        elif p.get("who") == "area":
            who = [o for o in self.b["combatants"] if not self._is_out(o) and (o is c or c.get("pos") and o.get("pos")
                                                                               and self._dist(c, o) <= p.get("size", 10)
                                                                               and (not p.get("allies") or not self._hostile(o, c)))]
        self._pay(c, p["cost"], data["name"])
        note = self._wonder_spend(c, char, entry, data, p)
        rounds = p.get("rounds")
        if isinstance(rounds, str):
            dice, _x, mult = rounds.partition("*")
            rounds = int(roll_dice(dice).total) * int(mult or 1)
        mods = dict(p.get("mods") or {}, wonder=data["name"])     # the item's name: the effect is found (and switched off) by it
        if mods.pop("fly_walk", None):
            mods["fly"] = char.speed
        if (mods.get("dmg") or ("",))[0] == "PB":              # + proficiency bonus to damage (Ring of Red Fury, Cape of Enlargement)
            mods["dmg"] = (str(char.proficiency_bonus), mods["dmg"][1])
        until = None
        if p.get("until") == "start":
            until = {"start": c["id"]}
        elif p.get("until") == "end":
            until = {"end": c["id"], "skip": 1 if self.b.get("turn") == c["id"] else 0}
        names = []
        for t in who:
            self._effect_on(t, data["name"], list(p.get("conds") or []), None, None, None, rounds, c["name"], mods, None, c["id"],
                            until=until, ends_on=p.get("ends_on"))
            names.append(t["name"])
        line = f"{c['name']} uses {data['name']}{note}: {p['name'].lower()}" + (f" on {', '.join(names)}" if who != [c] else "")
        self._commit(line)
        return line
