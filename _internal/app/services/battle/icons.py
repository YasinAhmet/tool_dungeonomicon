"""Icons for the action bar: every action, spell and feature gets a small picture (game-icons.net, CC BY 3.0 - the
authors are listed in the icons' CREDITS.md).

The pictures are 48 px WebP files in an asset module's assets/icons (core/assets.py; the "game-icons" module), made by
tools/build_icons.py into the project's assets/icons from the game-icons SVGs: only
the ones these tables and the spell map (icon_map.json, also written by the tool) use. icon_for(item) picks one:
spells by name (the tool matched every spell), the rest by these tables, then by keywords in the name.
"""
import re
from functools import lru_cache
from typing import Optional

GENERIC = "magic-swirl"

STANDARD = {"dash": "sprint", "disengage": "exit-door", "dodge": "dodging", "help": "help", "hide": "hidden",
            "search": "magnifying-glass", "ready": "hourglass", "use_object": "potion-ball", "grapple": "grab", "shove": "push",
            "escape": "breaking-chain", "stand_up": "body-height", "drop_prone": "fall-down", "stabilize": "bandage-roll"}
FEATURES = {"second_wind": "health-increase", "action_surge": "fast-forward-button", "rage": "enrage", "reckless": "angry-eyes",
            "cunning_dash": "running-ninja", "cunning_disengage": "exit-door", "cunning_hide": "hooded-assassin", "steady_aim": "on-target",
            "martial_arts": "punch", "flurry": "high-punch", "patient_defense": "dodging", "step_of_the_wind": "wind-slap",
            "stunning_strike": "stun-grenade", "lay_on_hands": "hand-of-god", "divine_smite": "sun", "bardic_inspiration": "inspiration",
            "turn_undead": "holy-symbol", "vow_of_enmity": "crossed-swords", "bladesong": "sword-brandish", "sacred_weapon": "sun", "preserve_life": "healing",
            "breath_weapon": "dragon-breath", "healing_hands": "healing", "wild_shape": "wolf-head",
            "relentless_endurance": "bleeding-heart"}
FEAT_ACTIONS = {"gwm": "two-handed-sword", "polearm": "halberd", "crossbow": "crossbow", "charger": "charging-bull",
                "shield_shove": "shield-bash", "brawl_grapple": "grab", "telekinetic": "psychic-waves", "chromatic": "dragon-head",
                "healer": "first-aid-kit"}
FREE = {"end_concentration": "concentration-orb", "end_form": "transform"}
# reaction settings (ask / always / never) by family; the spell ones use their spell's picture
REACTIONS = {"opportunity": "sword-clash", "parry": "cross-shield", "duelist": "sword-brandish", "cutting": "sound-waves",
             "smite": "sun", "stun": "stun-grenade", "uncanny": "dodging", "deflect": "arrow-cluster", "legendary_resistance": "crown",
             "lucky": "dice-twenty-faces-twenty", "sentinel": "eye-target", "polearm": "halberd", "mage_slayer": "magic-axe",
             "warcaster": "wizard-staff", "second_chance": "cycle", "fade_away": "invisible", "orcish_fury": "enrage",
             "reactive_resistance": "electrical-resistance", "wings": "angel-wings", "reprisal": "psychic-waves", "readied": "hourglass",
             "indomitable": "mighty-force"}
REACTION_SPELLS = {"shield": "Shield", "absorb": "Absorb Elements", "counterspell": "Counterspell", "barbs": "Silvery Barbs",
                   "rebuke": "Hellish Rebuke"}
# conditions as badges over the tokens on the maps (vfx.py, the portal): picture and colour
CONDITIONS = {"Blinded": ("blindfold", "#cbd5e1"), "Charmed": ("charm", "#f472b6"), "Deafened": ("sound-off", "#94a3b8"),
              "Frightened": ("terror", "#a78bfa"), "Grappled": ("grab", "#d6c3a1"), "Incapacitated": ("halt", "#9aa3b2"),
              "Invisible": ("invisible", "#bae6fd"), "Paralyzed": ("frozen-body", "#7dd3fc"), "Petrified": ("stone-bust", "#a8a29e"),
              "Poisoned": ("poison", "#4ade80"), "Prone": ("fall-down", "#d6c3a1"), "Restrained": ("manacles", "#84cc16"),
              "Stunned": ("knocked-out-stars", "#fde047"), "Unconscious": ("night-sleep", "#64748b")}
# lasting effects that get a badge too, after the conditions: it blinks when the effect changes a number
EFFECTS = {"Bless": ("holy-symbol", "#fcd34d"), "Rage": ("enrage", "#ef4444"), "Hunter's Mark": ("on-target", "#86efac"),
           "Hex": ("cursed-star", "#a78bfa")}
BADGES = {**CONDITIONS, **EFFECTS}
VFX_ICONS = ("crown",)                                  # pictures the map effects draw (a legendary action's crown)
# the sound board's one-shot effects (the sound modules' sounds.json keys)
SOUNDS = {"door_creak": "door", "door_open_close": "exit-door", "door_slam": "closed-doors", "knock": "door-ring-handle",
          "jail_door": "cage", "unlock": "unlocking", "chest": "chest", "trap": "wolf-trap", "sword_draw": "sword-brandish",
          "sword_clash": "sword-clash", "arrows": "arrow-cluster", "punch": "punch", "explosion": "bright-explosion",
          "fireball": "fireball", "magic": "magic-swirl", "scream": "screaming", "war_horn": "hunting-horn", "glass": "shattered-glass",
          "coins": "two-coins", "splash": "water-splash", "bell": "ringing-bell", "gong": "gong", "thunder": "thunder-struck",
          "crowd_cheer": "three-friends", "evil_laugh": "imp-laugh", "wolf_howl": "wolf-howl", "monster_roar": "monster-grasp",
          "dragon_roar": "dragon-head", "growl": "fangs-circle", "crow": "raven", "owl": "owl", "horse_neigh": "horse-head"}
# creature types (the bestiary's rows)
CREATURES = {"aberration": "tentacle-strike", "beast": "wolf-head", "celestial": "angel-wings", "construct": "golem-head",
             "dragon": "dragon-head", "elemental": "tornado", "fey": "fairy", "fiend": "horned-skull", "giant": "giant",
             "humanoid": "person", "monstrosity": "monster-grasp", "ooze": "slime", "plant": "tree-face", "undead": "raise-zombie",
             "animal": "wolf-head", "elemental & planar": "tornado", "fey & plant": "fairy"}     # (the bestiary's kinds)
# inventory items (for_item): by type, and wondrous ones by words in their name
ITEM_TYPES = {"LA": "armor-vest", "MA": "armor-vest", "HA": "armor-vest", "S": "shield", "P": "potion-ball", "SC": "scroll-unfurled",
              "RG": "diamond-ring", "WD": "fairy-wand", "RD": "crystal-wand", "A": "quiver", "AF": "ammo-box", "INS": "lyre",
              "AT": "toolbox", "T": "toolbox", "GS": "rolling-dices", "G": "backpack", "$G": "emerald", "$A": "gem-pendant",
              "$C": "two-coins", "SCF": "crystal-ball", "FD": "meal", "TG": "swap-bag", "MNT": "horse-head", "TAH": "saddle",
              "SHP": "sailboat", "EXP": "bright-explosion"}
ITEM_WORDS = [(r"\bring\b", "diamond-ring"), (r"\bwand\b", "fairy-wand"), (r"\bstaff\b", "wizard-staff"), (r"\brod\b", "crystal-wand"),
              (r"boots|slippers", "leather-boot"), (r"cloak|cape|mantle|robe", "cloak"), (r"gloves|gauntlets|bracers", "gauntlet"),
              (r"belt|girdle", "belt"), (r"helm|\bhat\b|circlet|headband", "visored-helm"), (r"crown|tiara", "crown"),
              (r"amulet|necklace|periapt|medallion|brooch|talisman|pendant", "gem-pendant"), (r"\bbag\b|sack|pouch|haversack|backpack", "knapsack"),
              (r"potion|elixir|philter|\boil\b", "potion-ball"), (r"scroll", "scroll-unfurled"), (r"\bbook\b|tome|manual|grimoire", "spell-book"),
              (r"lantern|\blamp\b", "lantern"), (r"torch", "torch"), (r"\bkey\b", "key"), (r"\borb\b|crystal|sphere", "crystal-ball"),
              (r"\bhorn\b", "hunting-horn"), (r"\bdrum\b", "drum"), (r"flute|pipes", "flute"), (r"harp|lyre|lute", "lyre"),
              (r"flask|bottle|vial|decanter|jug", "round-bottom-flask"), (r"\bgem\b|jewel|diamond|ruby|emerald|sapphire", "emerald"),
              (r"\bcoin", "two-coins"), (r"ration|\bfood\b|bread|cheese", "meal"), (r"\bfire\b", "flame"), (r"armor|armour|\bmail\b|plate", "armor-vest"), (r"shield", "shield")]
# the item search's category folders (rules/search.py item_category)
ITEM_CATS = {"Weapon": "crossed-swords", "Ammunition & explosives": "ammo-box", "Armor & shield": "armor-vest", "Rod": "crystal-wand",
             "Wand": "fairy-wand", "Adventuring gear": "backpack", "Mounts, vehicles & trade": "saddle", "Tools & instruments": "toolbox",
             "Wondrous item": "sparkles", "Treasure": "chest", "Potion": "potion-ball", "Magic item (other)": "magic-swirl",
             "Ring": "diamond-ring", "Scroll": "scroll-unfurled", "Other": "knapsack"}
# the editor's and the portal's own buttons (icon_button in app/ui/widgets/icons.py, ui_icon() in portal.js)
UI = {"damage": "heart-minus", "heal": "heart-plus", "temp_hp": "heart-shield", "max_hp": "health-increase",
      "short_rest": "campfire", "long_rest": "night-sleep", "hit_die": "rolling-dices", "inspiration": "inspiration",
      "exhaustion": "tired-eye", "next_turn": "next-button", "previous_turn": "previous-button", "roll": "rolling-dices",
      "add_players": "three-friends", "place": "position-marker", "rules": "cog", "end_battle": "checkered-flag",
      "start_battle": "crossed-swords", "encounters": "scroll-unfurled", "clear": "trash-can", "award": "laurels-trophy",
      "async_dice": "dice-twenty-faces-twenty", "generator": "anvil", "edit": "quill-ink", "filter": "funnel", "reset": "cycle",
      "level_up": "upgrade", "ping": "position-marker", "coins": "two-coins", "backpack": "backpack",
      "export": "paper-arrow", "import": "box-unpacking", "warning": "halt",
      "view_map": "treasure-map", "view_sheet": "person", "view_feed": "chat-bubble", "reveal": "surrounded-eye",
      "undo": "anticlockwise-rotation"}


def badge_keys(conditions, effects) -> list:
    """What a creature's badges show, in order: its conditions, then its effects that have a badge (each once)."""
    return [x for x in conditions or [] if x in CONDITIONS] + \
        list(dict.fromkeys(e["name"] for e in effects or [] if e.get("name") in EFFECTS))
DAMAGE = {"fire": "flame", "cold": "ice-bolt", "lightning": "lightning-arc", "thunder": "thunder-struck", "acid": "acid",
          "poison": "poison-cloud", "necrotic": "death-skull", "radiant": "sunbeams", "psychic": "psychic-waves", "force": "mighty-force",
          "bludgeoning": "hammer-drop", "piercing": "thrown-spear", "slashing": "claw-slashes"}
KIND = {"heal": "healing", "buff": "beams-aura", "self_effect": "aura", "summon": "pentacle", "teleport": "teleport", "zone": "magic-portal",
        "cleanse": "health-normal", "revive": "angel-wings", "power_word": "screaming", "pool": "night-sleep", "time_stop": "sands-of-time",
        "reaction_only": "magic-shield", "utility": "spell-book", "weapon_spell": "sword-brandish", "life_transference": "healing", "prismatic": "sunbeams", "surge": "magic-swirl"}
SCHOOL = {"abjuration": "magic-shield", "conjuration": "magic-portal", "divination": "third-eye", "enchantment": "charm",
          "evocation": "fire-spell-cast", "illusion": "invisible", "necromancy": "death-skull", "transmutation": "magic-swirl"}
# words in a weapon's or a stat block action's name -> picture (first match wins)
KEYWORDS = [
    (r"multiattack", "crossed-swords"), (r"fire breath|flame breath", "fire-breath"), (r"breath", "dragon-breath"),
    (r"frightful presence|terrif|horrif|fear", "terror"), (r"spellcasting|spell", "spell-book"), (r"teleport|misty|blink", "teleport"),
    (r"change shape|shapechang|transform", "transform"), (r"web", "spider-web"), (r"spit|spray", "web-spit"),
    (r"bite|jaws|maw", "fangs"), (r"claw|talon|rake", "claws"), (r"tail", "spiked-tail"), (r"sting|stinger", "wasp-sting"),
    (r"tentacle", "tentacle-strike"), (r"gore|horn|butt|ram\b", "bull-horns"), (r"hoove|hoof|stomp|trample", "hoof"),
    (r"slam|fist|unarmed|punch|pummel|smash", "fist"), (r"crossbow", "crossbow"), (r"longbow|shortbow|\bbow\b", "bow-arrow"),
    (r"sling", "sling"), (r"dart|javelin|spear|trident|pike|lance", "thrown-spear"), (r"dagger|knife", "plain-dagger"),
    (r"greatsword|great sword", "two-handed-sword"), (r"rapier|scimitar|sword|blade|sabre|saber", "broadsword"),
    (r"greataxe|axe", "battle-axe"), (r"glaive", "glaive"), (r"halberd", "halberd"), (r"maul|warhammer|hammer", "warhammer"),
    (r"mace|morningstar|flail|club|cudgel", "spiked-mace"), (r"quarterstaff|staff", "wizard-staff"), (r"whip", "whip"),
    (r"rock|boulder", "falling-rocks"), (r"touch|grasp|grab|engulf|constrict|swallow", "grab"), (r"parry", "sword-clash"),
    (r"heal|cure", "healing"), (r"roar|shriek|scream|howl", "screaming"), (r"wing", "angel-wings"), (r"gaze|eye|ray", "eye-target"),
    (r"leadership|command", "inspiration"), (r"detect|perception|search", "magnifying-glass"), (r"move|fly|dash|leap|jump", "sprint"),
    (r"poison|venom", "poison"), (r"drain|life", "bleeding-heart"),
]


@lru_cache(maxsize=1)
def _spell_map() -> dict:
    from ...core import assets
    from ...rules import modules
    out: dict = {}
    for _folder, data in reversed(assets.catalogues("icons", "icon_map.json")):     # the first module's word wins
        out.update(data.get("spells") or {} if isinstance(data, dict) else {})
    return {**out, **modules.icon_names()}                 # a module's spells and weapons name their own pictures


@lru_cache(maxsize=4096)
def available(slug: Optional[str]) -> bool:
    return path(slug) is not None


@lru_cache(maxsize=4096)
def path(slug: str) -> Optional[str]:
    """The picture's file (None when it isn't there): an asset module's icons, else a content module's own icons."""
    from ...core import assets
    from ...rules import modules
    if not slug or not re.fullmatch(r"[a-z0-9-]+", slug):
        return None
    return assets.asset("icons", f"{slug}.webp") or modules.icon_path(slug)


@lru_cache(maxsize=8192)                               # dozens of patterns per name: every sheet, menu and page asks
def by_keywords(text: str) -> Optional[str]:
    low = (text or "").lower()
    for rx, slug in KEYWORDS:
        if re.search(rx, low):
            return slug
    return None


def for_spell(name: str, school: str = "", kind: str = "", damage: Optional[list] = None) -> str:
    slug = _spell_map().get((name or "").lower())
    if available(slug):
        return slug
    for t in damage or []:
        if available(DAMAGE.get(str(t).lower())):
            return DAMAGE[str(t).lower()]
    for s in (KIND.get(kind), SCHOOL.get((school or "").lower())):
        if available(s):
            return s
    return GENERIC


@lru_cache(maxsize=8192)
def for_item(name: str) -> Optional[str]:
    """The picture of an inventory item: a weapon by its name, a wondrous item by words in it, the rest by type.
    Kept per name (forget() after the item list changes)."""
    from ...rules.data import rules
    low = (name or "").lower()
    item = rules.items.get(low) or {}
    kind = str(item.get("type") or "").split("|")[0]
    if available(item.get("icon")):                       # a module's item with a picture of its own
        return item["icon"]
    if item.get("weapon") or kind in ("M", "R"):
        slug = by_keywords(low)
        return slug if available(slug) and slug not in ("sprint", "magnifying-glass", "inspiration") else "crossed-swords"
    for rx, slug in ITEM_WORDS:
        if re.search(rx, low) and available(slug):
            return slug
    slug = ITEM_TYPES.get(kind)
    return slug if available(slug) else None


def forget():
    """The item list changed (homebrew): look the items' pictures up again."""
    for_item.cache_clear()


def for_attack(name: str) -> Optional[str]:
    """A sheet attack's picture: its weapon's, or by words in it (Unarmed Strike: a fist)."""
    slug = for_item(name) or by_keywords(name)
    return slug if available(slug) else None


def for_reaction(family: str) -> Optional[str]:
    """A reaction setting's picture: its spell's (Shield), or its own (an opportunity attack: crossed blades)."""
    if family in REACTION_SPELLS:
        return for_spell(REACTION_SPELLS[family])
    slug = REACTIONS.get(family)
    return slug if available(slug) else None


def icon_for(item: dict) -> str:
    """The picture for an action bar entry (see battle/menu.py)."""
    kind, _, arg = str(item.get("id") or "").partition(":")
    slug = None
    if kind in ("spell", "mspell"):
        return for_spell(item.get("name", ""), item.get("school", ""), item.get("spell_kind", ""), item.get("damage"))
    if kind == "standard":
        slug = STANDARD.get(arg)
    elif kind == "feature":
        slug = FEATURES.get(arg)
    elif kind == "featact":
        slug = FEAT_ACTIONS.get(arg)
    elif kind == "free":
        slug = FREE.get(arg)
    elif kind == "charge":
        slug = "charging-bull"
    elif kind in ("throw", "pickup"):
        slug = {"throw": "thrown-daggers", "pickup": "hand"}[kind]
    elif kind in ("sa", "zone"):
        src = item.get("spell") or re.sub(r"^Move |:.*$", "", item.get("name", ""))
        slug = _spell_map().get(src.lower()) or by_keywords(item.get("name", ""))
    if not available(slug):
        slug = by_keywords(" ".join(str(item.get(k) or "") for k in ("weapon_name", "name")))
    if not available(slug) and item.get("text"):
        slug = by_keywords(item["text"][:120])
    return slug if available(slug) else GENERIC
