"""Item sprites: a small coloured picture for every kind of item, drawn on the battle maps for the items lying on the ground
and for a thing in flight when it is thrown (the editor's vfx.py, the portal).

    sprite_for("+1 Longsword")    # 'longsword'
    sprite_for("Potion of Healing")  # 'potion_red'
    path("longsword")             # .../assets/items/longsword.png of an asset module, or None

The pictures are 32 px pixel art from Dungeon Crawl Stone Soup (CC0, credited in their CREDITS.md), in an asset module's
assets/items ("item-sprites", core/assets.py), fetched by tools/fetch_item_sprites.py into the project's assets/items from the table below: one per weapon, per armour, per kind of jewellery, potion, scroll...
A weapon is matched by its name (a magic one names its base weapon: "Flame Tongue Longsword"), the rest by words in the
name, then by the item's type.
"""
import re
from functools import lru_cache
from typing import Optional

GENERIC = "sack"
R = "item/weapon/ranged/"
W = "item/weapon/"
A = "item/armour/"

# key: the picture's file in the DCSS tiles (crawl-ref/source/rltiles/...)
SPRITES = {
    # weapons
    "dagger": W + "dagger.png", "shortsword": W + "short_sword1.png", "longsword": W + "long_sword1.png",
    "greatsword": W + "greatsword1.png", "rapier": W + "rapier1.png", "scimitar": W + "scimitar1.png",
    "double_scimitar": W + "double_sword.png", "sickle": W + "falchion1.png", "handaxe": W + "hand_axe1.png",
    "battleaxe": W + "war_axe1.png", "greataxe": W + "executioner_axe1.png", "club": W + "club.png",
    "greatclub": W + "giant_club.png", "mace": W + "mace1.png", "morningstar": W + "morningstar1.png",
    "flail": W + "flail1.png", "warhammer": W + "hammer1.png", "light_hammer": W + "hammer2.png", "maul": W + "mace_large1.png",
    "war_pick": W + "hammer3.png", "quarterstaff": W + "quarterstaff.png", "spear": W + "spear1.png",
    "javelin": R + "javelin1.png", "trident": W + "trident1.png", "pike": W + "partisan1.png", "lance": W + "spear3.png",
    "halberd": W + "halberd1.png", "glaive": W + "glaive1.png", "whip": W + "bullwhip.png", "scythe": W + "scythe1.png",
    "dart": R + "dart1.png", "sling": R + "sling1.png", "shortbow": R + "shortbow1.png", "longbow": R + "longbow1.png",
    "hand_crossbow": "UNUSED/weapons/hand_crossbow.png", "crossbow": R + "arbalest1.png", "heavy_crossbow": R + "arbalest2.png",
    "repeating_crossbow": R + "triple_crossbow.png", "blowgun": R + "blowgun1.png", "net": R + "throwing_net.png",
    "pistol": R + "hand_cannon.png", "rifle": R + "hand_cannon2.png", "rock": R + "rock.png", "boomerang": R + "boomerang1.png",
    # ammunition
    "arrow": R + "arrow1.png", "bolt": R + "crossbow_bolt1.png", "bullet": R + "sling_bullet1.png", "needle": "UNUSED/weapons/needle1.png",
    # armour and shields
    "padded": A + "robe2.png", "leather": A + "leather_armour1.png", "studded_leather": A + "leather_armour2.png",
    "hide": A + "animal_skin1.png", "chain_shirt": A + "ring_mail2.png", "ring_mail": A + "ring_mail1.png",
    "scale_mail": A + "scale_mail1.png", "breastplate": A + "plate2.png", "half_plate": A + "plate3.png",
    "chain_mail": A + "chain_mail1.png", "splint": A + "chain_mail3.png", "plate": A + "plate1.png",
    "dragon_scale": A + "fire_dragon_armour.png", "robe": A + "robe1.png", "shield": A + "shields/kite_shield1.png",
    # worn things
    "helmet": A + "headgear/helmet1.png", "hat": A + "headgear/hat1.png", "wizard_hat": A + "headgear/wizard_hat.png",
    "crown": A + "artefact/urand_crown_of_vainglory.png", "cloak": A + "cloak1_leather.png", "gloves": A + "glove1.png",
    "gauntlets": "UNUSED/armour/gauntlet1.png", "boots": A + "boots1.png", "scarf": A + "scarf1.png",
    # jewellery
    "ring": "item/ring/gold.png", "amulet": "item/amulet/golden.png", "necklace": "item/amulet/pearl.png",
    "brooch": "item/amulet/cameo.png", "talisman": "item/amulet/bone.png",
    # potions and flasks, by colour
    "potion_red": "item/potion/ruby.png", "potion_blue": "item/potion/brilliant_blue.png", "potion_green": "item/potion/emerald.png",
    "potion_orange": "item/potion/orange.png", "potion_white": "item/potion/white.png", "potion_brown": "item/potion/brown.png",
    "potion_purple": "item/potion/magenta.png", "potion_gold": "item/potion/golden.png", "potion_murky": "item/potion/murky.png",
    "bomb": "item/potion/black.png",
    # magic things
    "scroll": "item/scroll/scroll.png", "spell_scroll": "item/scroll/scroll-purple.png", "wand": "item/wand/gem_wood.png",
    "rod": "item/rod/rod00.png", "staff": "item/staff/staff00.png", "book": "item/book/leather.png", "spellbook": "item/book/purple.png",
    "orb": "item/misc/misc_crystal.png", "stone": "item/misc/misc_stone.png", "deck": "UNUSED/other/misc_deck.png",
    "figurine": "item/misc/misc_zigfig.png", "mirror": "item/misc/misc_phantom_mirror.png", "fan": "item/misc/misc_fan.png",
    "horn": "item/misc/misc_horn.png", "lamp": "UNUSED/other/magic_lamp.png", "box": "item/misc/misc_box_of_beasts_inert.png",
    # gear, treasure, food
    "lantern": "item/misc/misc_lamp.png", "bottle": "item/misc/misc_bottle.png", "sack": "item/misc/misc_sack_inert.png",
    "instrument": "item/misc/misc_tambourine.png", "tools": "item/gizmo/gizmo0.png", "coins": "item/gold/16.png",
    "gem": "item/gem/dungeon_found_whole.png", "art": "item/amulet/filigree.png", "food": "item/food/bread_ration.png",
    "meat": "item/food/meat_ration.png", "fruit": "item/food/apple.png", "cheese": "item/food/cheese.png", "bone": "item/food/bone1.png",
}

# thrown, these fly point first: how far their tip points up from the right in the picture (degrees)
POINT_FIRST = {"javelin": 11, "spear": 45, "dart": 25, "trident": 45, "pike": 45, "lance": 45, "arrow": 20, "bolt": 20, "needle": 23}

# words in a weapon's name -> its picture, the longer names first ("greatsword" before "sword")
WEAPON_WORDS = [
    (r"hand crossbow", "hand_crossbow"), (r"heavy crossbow", "heavy_crossbow"), (r"repeating crossbow", "repeating_crossbow"),
    (r"crossbow", "crossbow"), (r"longbow", "longbow"), (r"shortbow|\bbow\b", "shortbow"), (r"blowgun", "blowgun"),
    (r"\bsling\b", "sling"), (r"\bnet\b", "net"), (r"pistol|revolver", "pistol"), (r"rifle|musket|shotgun", "rifle"),
    (r"greatsword|great sword|claymore|zweihander", "greatsword"), (r"double-bladed scimitar|double scimitar", "double_scimitar"),
    (r"shortsword|short sword", "shortsword"), (r"rapier", "rapier"), (r"scimitar|cutlass|sabre|saber|khopesh", "scimitar"),
    (r"longsword|long sword", "longsword"), (r"dagger|knife|kukri|athame|stiletto|dirk", "dagger"),
    (r"sickle", "sickle"), (r"scythe", "scythe"), (r"greataxe|great axe", "greataxe"), (r"handaxe|hand axe|tomahawk", "handaxe"),
    (r"battleaxe|battle axe|\baxe\b", "battleaxe"), (r"greatclub|great club", "greatclub"), (r"warhammer|war hammer", "warhammer"),
    (r"light hammer|\bhammer\b", "light_hammer"), (r"\bmaul\b", "maul"), (r"war pick|\bpick\b", "war_pick"),
    (r"morningstar|morning star", "morningstar"), (r"flail", "flail"), (r"\bmace\b", "mace"), (r"\bclub\b|cudgel|shillelagh", "club"),
    (r"quarterstaff|hoopak|\bstaff\b", "quarterstaff"), (r"javelin", "javelin"), (r"trident", "trident"), (r"\bpike\b", "pike"),
    (r"\blance\b", "lance"), (r"halberd", "halberd"), (r"glaive", "glaive"), (r"spear|yklwa|harpoon", "spear"),
    (r"\bwhip\b|\blash\b", "whip"), (r"\bdarts?\b", "dart"), (r"boomerang", "boomerang"), (r"iron ball|\brock\b|boulder", "rock"),
    (r"sword|blade|katana|brand\b", "longsword"),                   # a sword by any other name, after the others ("shortspear armblade")
]
# words in any other item's name -> its picture (first match wins)
ITEM_WORDS = [
    (r"alchemist's fire|\bfire\b.*flask|flask.*\bfire\b", "potion_orange"), (r"\bacid\b", "potion_green"),
    (r"holy water", "potion_white"), (r"\boil\b", "potion_brown"), (r"antitoxin", "potion_blue"), (r"\bpoison\b", "potion_murky"),
    (r"potion of (greater |superior |supreme )?healing|healing potion|\bhealing\b", "potion_red"),
    (r"potion of (giant strength|heroism|speed|growth)", "potion_gold"), (r"potion of (invisibility|mind|clairvoyance|gaseous)", "potion_purple"),
    (r"potion|elixir|philter|draught|tonic", "potion_blue"),
    (r"bomb|grenade|dynamite|smoke powder|gunpowder|keg", "bomb"),
    (r"spell scroll", "spell_scroll"), (r"scroll|parchment", "scroll"), (r"spellbook|grimoire|tome|manual of|codex", "spellbook"),
    (r"\bbook\b|journal|diary|ledger", "book"),
    (r"\bwand\b", "wand"), (r"\brod\b|sceptre|scepter", "rod"), (r"\bstaff\b", "staff"),
    (r"\bring\b", "ring"), (r"amulet|periapt|medallion|scarab", "amulet"), (r"necklace|pendant|beads|choker|\btorc\b", "necklace"),
    (r"brooch|\bpin\b|badge|insignia|\bmedal\b|trophy", "brooch"), (r"talisman|holy symbol|emblem|reliquary|\btotem\b|mistletoe", "talisman"),
    (r"crown|tiara|circlet|diadem", "crown"), (r"helm|helmet", "helmet"), (r"wizard.*hat|\bhat\b.*wizard", "wizard_hat"),
    (r"\bhat\b|\bcap\b|\bhood\b|headband|cowl|mask", "hat"),
    (r"cloak|cape|mantle|wings of", "cloak"), (r"\brobe\b|vestments|clothes|garb|costume|\bcoat\b", "robe"),
    (r"gauntlets|bracers?\b|bracelet|vambraces", "gauntlets"), (r"gloves|glove", "gloves"), (r"boots|slippers|shoes|sandals|greaves", "boots"),
    (r"belt|girdle|sash|scarf|shawl", "scarf"),
    (r"\borb\b|crystal ball|crystal|sphere|\bglobe\b", "orb"), (r"ioun stone|stone\b|pebble", "stone"),
    (r"\bdeck\b|\bcards?\b|\bdie\b|dice|chess|dragonchess|playing", "deck"), (r"figurine|statuette|idol|\bdoll\b|keyrune|mascot", "figurine"),
    (r"mirror", "mirror"), (r"\bfan\b", "fan"), (r"horn\b|trumpet|bugle|conch", "horn"),
    (r"lute|lyre|harp|drum|flute|pipes|viol|dulcimer|shawm|bagpipes|instrument|tambourine|cittern|bell|chime|concertina|bandore", "instrument"),
    (r"lantern|lanthorn|\btorch\b|candle", "lantern"), (r"\blamp\b", "lamp"),
    (r"flask|bottle|vial|decanter|jug|\bwine\b|\bale\b|waterskin|pitcher|tankard|\bmug\b|\bjar\b|\burn\b|\bbowl\b|\bpot\b|censer|"
     r"brazier|vessel|\bcup\b|goblet|chalice|cauldron", "bottle"),
    (r"\bbag\b|sack|pouch|haversack|backpack|quiver|purse|satchel", "sack"),
    (r"chest|\bbox\b|\bcase\b|coffer|casket|\bcube\b|cage|\bkit\b", "box"),
    (r"tools|supplies|\btool\b|lockpick|\bkey\b|\block\b|crowbar|hammer|piton|shovel|chain|manacles|caltrops|ball bearings|grappling|"
     r"\brope\b|scissors|gavel|pigments|\bglue\b", "tools"),
    (r"arrow", "arrow"), (r"\bbolt", "bolt"), (r"bullet|\bshot\b|shells?\b", "bullet"), (r"needle", "needle"),
    (r"\bcoins?\b|\bgold\b|\bsilver\b|\bcopper\b|platinum|\(gp\)|\(sp\)|\(cp\)|\(pp\)|\(ep\)", "coins"),
    (r"\bgem\b|jewel|diamond|ruby|emerald|sapphire|pearl|opal|topaz|garnet|amethyst|jade|onyx|agate|quartz|jasper|spinel|"
     r"turquoise|moonstone|tourmaline|zircon|beryl|chrysoberyl|bloodstone|carnelian|citrine|coral|jet\b|obsidian|peridot|malachite", "gem"),
    (r"meat|jerky|sausage|ham\b|fish", "meat"), (r"apple|fruit|berr", "fruit"), (r"cheese", "cheese"),
    (r"ration|\bfood\b|bread|meal|feast|cake|pie\b", "food"), (r"bone|skull", "bone"),
]
ARMOUR_WORDS = [
    (r"dragon scale|dragon hide|dragonhide", "dragon_scale"), (r"half plate", "half_plate"), (r"breastplate", "breastplate"),
    (r"\bplate\b", "plate"), (r"splint", "splint"), (r"chain shirt", "chain_shirt"), (r"chain mail|chainmail|\bmail\b.*chain", "chain_mail"),
    (r"ring mail", "ring_mail"), (r"scale", "scale_mail"), (r"studded", "studded_leather"), (r"\bhide\b|\bfur\b|pelt", "hide"),
    (r"padded|quilted", "padded"), (r"leather", "leather"), (r"\bmail\b", "chain_mail"), (r"robe", "robe"),
]
# by the item's type code (rules data): when the name says nothing
TYPES = {"LA": "leather", "MA": "chain_shirt", "HA": "plate", "S": "shield", "P": "potion_blue", "SC": "scroll", "RG": "ring",
         "WD": "wand", "RD": "rod", "A": "arrow", "AF": "bullet", "INS": "instrument", "AT": "tools", "T": "tools", "GS": "deck",
         "G": "sack", "$G": "gem", "$A": "art", "$C": "coins", "SCF": "orb", "FD": "food", "TG": "sack", "EXP": "bomb",
         "TAH": "sack", "OTH": "box", "M": "longsword", "R": "shortbow"}


def _first(rules_list, text: str) -> Optional[str]:
    for rx, key in rules_list:
        if re.search(rx, text):
            return key
    return None


@lru_cache(maxsize=4096)
def sprite_for(name: str) -> str:
    """The sprite key of an item (by name; unknown names by their words): never empty - the sack when nothing fits."""
    from ...rules.data import rules
    low = (name or "").strip().lower()
    item = rules.items.get(low) or {}
    kind = str(item.get("type") or "").split("|")[0]
    if item.get("armor") or kind in ("LA", "MA", "HA"):
        return _first(ARMOUR_WORDS, low) or TYPES.get(kind) or "chain_mail"
    if kind == "S" or (re.search(r"\bshield\b", low) and not item.get("weapon")):
        return "shield"
    if item.get("weapon") or kind in ("M", "R"):
        tags = " ".join(item.get("tags") or [])
        if item.get("magic") and re.search(r"^staff\b|\bstaff of\b", low):     # a magic staff (Staff of Fire), not a plain one
            return "staff"
        return _first(WEAPON_WORDS, low) or _first(WEAPON_WORDS, tags) or TYPES.get(kind) or "longsword"
    key = _first(ITEM_WORDS, low)
    if key:
        return key
    if not item:
        key = _first(WEAPON_WORDS, low) or _first(ARMOUR_WORDS, low)
    return key or TYPES.get(kind) or GENERIC


@lru_cache(maxsize=256)
def path(key: str) -> Optional[str]:
    """The sprite's file, or None when it isn't there."""
    if key not in SPRITES:
        return None
    from ...core import assets
    return assets.asset("items", f"{key}.png")


def forget():
    """The item list changed (homebrew): look the sprites up again."""
    sprite_for.cache_clear()
