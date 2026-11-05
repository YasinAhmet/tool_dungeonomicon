"""Map props: small top-down pictures the DM drops on the battle map - trees, rocks, chests, barrels, tables, a
campfire... Each is a map symbol (drawing type 'symbol', `sym` = the prop's key) with terrain rules the battle uses
(cover, blocking, difficult terrain, light), like the built-in symbols in sight.py.

The look is ink on parchment, the old-school dungeon module look: Mark Gosbell's Classic Dungeon Map Symbols (CC0),
128 px per tile (tools/build_classic_props.py), drawn smoothed; keys start with ink_. Maps saved with the props of the
packs since dropped get the nearest one on loading (LEGACY, upgrade()).

The built-in symbols (drawing.SYMBOLS: door, stairs, trap...) get pictures too (sym_<key>.webp), so path() answers for
them as well.
"""
import re
from functools import lru_cache
from typing import Optional

HALF = {"cover": "half", "blocks": True}
TOTAL = {"cover": "total", "blocks": True}

CREDITS_LINE = "Props: Classic Dungeon Map Symbols by Mark Gosbell, CC0."

# key: (label, category, (pack, picture file in the pack[, tiles across]), terrain rules) - the gosbell pictures are
# 300 px a tile
CLASSIC = {
    # ---- Classic Dungeon Map Symbols (Mark Gosbell)
    "ink_door": ("Door", "Classic doors and walls", ("gosbell", "Door1x1"), {}),
    "ink_double_door": ("Double door", "Classic doors and walls", ("gosbell", "DoorDouble1x1"), {}),
    "ink_locked_door": ("Locked door", "Classic doors and walls", ("gosbell", "DoorLocked1x1"), {}),
    "ink_secret_door": ("Secret door", "Classic doors and walls", ("gosbell", "DoorSecret1x1"), {}),
    "ink_concealed_door": ("Concealed door", "Classic doors and walls", ("gosbell", "DoorConcealed1x1"), {}),
    "ink_false_door": ("False door", "Classic doors and walls", ("gosbell", "DoorFalse1x1"), {}),
    "ink_magic_door": ("Magic door", "Classic doors and walls", ("gosbell", "DoorMagic1x1"), {}),
    "ink_sliding_door": ("Sliding door", "Classic doors and walls", ("gosbell", "DoorSlides1x1"), {}),
    "ink_revolving_door": ("Revolving door", "Classic doors and walls", ("gosbell", "DoorRevolving1x1"), {}),
    "ink_archway": ("Archway", "Classic doors and walls", ("gosbell", "DoorArchway1x1"), {}),
    "ink_gate": ("Gate", "Classic doors and walls", ("gosbell", "DoorGate1x1"), {"blocks": True}),
    "ink_portcullis": ("Portcullis", "Classic doors and walls", ("gosbell", "DoorPortcullis1x1"), {"blocks": True}),
    "ink_curtain": ("Curtain", "Classic doors and walls", ("gosbell", "Curtain1x1"), {"cover": "total"}),
    "ink_window": ("Window", "Classic doors and walls", ("gosbell", "Window1x1"), {"blocks": True}),
    "ink_railing": ("Railing", "Classic doors and walls", ("gosbell", "Railing1x1"), HALF),
    # ---- stairs, ladders, pits and trapdoors
    "ink_stairs": ("Stairs", "Classic stairs and pits", ("gosbell", "Stairs1x1_01"), {}),
    "ink_stairs_up": ("Spiral stairs up", "Classic stairs and pits", ("gosbell", "StairSpiralCircleUp1x1"), {}),
    "ink_stairs_down": ("Spiral stairs down", "Classic stairs and pits", ("gosbell", "StairSpiralCircleDown1x1"), {}),
    "ink_spiral_stair": ("Great spiral stair", "Classic stairs and pits", ("gosbell", "StairSpiralCircleBig2x2", 2), {}),
    "ink_square_spiral_stair": ("Square spiral stair", "Classic stairs and pits", ("gosbell", "StairSpiralSquareBig2x2", 2), {}),
    "ink_ladder_up": ("Ladder up", "Classic stairs and pits", ("gosbell", "LadderUp1x1"), {}),
    "ink_ladder_down": ("Ladder down", "Classic stairs and pits", ("gosbell", "LadderDown1x1"), {}),
    "ink_pit": ("Open pit", "Classic stairs and pits", ("gosbell", "PitSquare1x1"), {"blocks": True}),
    "ink_round_pit": ("Round pit", "Classic stairs and pits", ("gosbell", "PitCircle1x1"), {"blocks": True}),
    "ink_covered_pit": ("Covered pit", "Classic stairs and pits", ("gosbell", "PitClosedSquare1x1"), {}),
    "ink_trapdoor": ("Trapdoor", "Classic stairs and pits", ("gosbell", "TrapdoorFloor1x1"), {}),
    "ink_secret_trapdoor": ("Secret trapdoor", "Classic stairs and pits", ("gosbell", "TrapdoorSecret1x1"), {}),
    # ---- furniture
    "ink_altar": ("Altar", "Classic furniture", ("gosbell", "Altar1x1"), HALF),
    "ink_bed": ("Bed", "Classic furniture", ("gosbell", "Bed1x1"), {"blocks": True}),
    "ink_double_bed": ("Double bed", "Classic furniture", ("gosbell", "BedDouble1x1"), {"blocks": True}),
    "ink_bench": ("Bench", "Classic furniture", ("gosbell", "Bench1x1"), {}),
    "ink_bookcase": ("Bookcase", "Classic furniture", ("gosbell", "Bookcase1x1"), TOTAL),
    "ink_chair": ("Chair", "Classic furniture", ("gosbell", "Chair1x1"), {}),
    "ink_stool": ("Stool", "Classic furniture", ("gosbell", "Stool1x1"), {}),
    "ink_throne": ("Throne", "Classic furniture", ("gosbell", "Throne1x1"), HALF),
    "ink_couch": ("Couch", "Classic furniture", ("gosbell", "Lounge1x1"), {}),
    "ink_table": ("Table", "Classic furniture", ("gosbell", "TableSquare1x1"), HALF),
    "ink_round_table": ("Round table", "Classic furniture", ("gosbell", "TableRound1x1"), HALF),
    "ink_table_chairs": ("Table and chairs", "Classic furniture", ("gosbell", "TableSetSquare1x1"), HALF),
    "ink_round_table_chairs": ("Round table and chairs", "Classic furniture", ("gosbell", "TableSetCircle1x1"), HALF),
    "ink_fireplace": ("Fireplace", "Classic furniture", ("gosbell", "Fireplace1x1"), {"blocks": True, "light": (10, 10)}),
    "ink_cask": ("Cask", "Classic furniture", ("gosbell", "Cask1x1"), HALF),
    "ink_chest": ("Chest", "Classic furniture", ("gosbell", "Chest1x1"), HALF),
    # ---- the dungeon
    "ink_statue": ("Statue", "Classic dungeon", ("gosbell", "Statue1x1"), TOTAL),
    "ink_small_statue": ("Small statue", "Classic dungeon", ("gosbell", "StatueSmall1x1"), HALF),
    "ink_pillar": ("Pillar", "Classic dungeon", ("gosbell", "CircleFilled1x1"), TOTAL),
    "ink_square_pillar": ("Square pillar", "Classic dungeon", ("gosbell", "SquareFilled1x1"), TOTAL),
    "ink_fountain": ("Fountain", "Classic dungeon", ("gosbell", "Fountain1x1"), HALF),
    "ink_well": ("Well", "Classic dungeon", ("gosbell", "WellCircle1x1"), HALF),
    "ink_square_well": ("Square well", "Classic dungeon", ("gosbell", "WellSquare1x1"), HALF),
    "ink_grave": ("Grave", "Classic dungeon", ("gosbell", "Grave1x1"), HALF),
    "ink_coffin": ("Coffin", "Classic dungeon", ("gosbell", "CoffinClosed1x1"), HALF),
    "ink_open_coffin": ("Open coffin", "Classic dungeon", ("gosbell", "CoffinOpen1x1"), HALF),
    "ink_cage": ("Cage", "Classic dungeon", ("gosbell", "Cage1x1"), {"blocks": True}),
    "ink_campfire": ("Campfire", "Classic dungeon", ("gosbell", "FireCamp1x1"), {"light": (20, 20)}),
    "ink_fire": ("Fire", "Classic dungeon", ("gosbell", "Fire1x1"), {"light": (20, 20)}),
    "ink_light": ("Torch or lamp", "Classic dungeon", ("gosbell", "Light1x1"), {"light": (20, 20)}),
    "ink_trap": ("Trap", "Classic dungeon", ("gosbell", "Trap1x1"), {}),
    "ink_trigger": ("Trigger", "Classic dungeon", ("gosbell", "Trigger1x1"), {}),
    "ink_danger": ("Danger", "Classic dungeon", ("gosbell", "Danger1x1"), {}),
    "ink_illusion": ("Illusion", "Classic dungeon", ("gosbell", "Illusion1x1"), {}),
    "ink_unknown": ("Unknown", "Classic dungeon", ("gosbell", "Unknown1x1"), {}),
    "ink_loot": ("Treasure", "Classic dungeon", ("gosbell", "Loot1x1"), {}),
    "ink_key": ("Key", "Classic dungeon", ("gosbell", "Key1x1"), {}),
    "ink_arrow": ("Arrow", "Classic dungeon", ("gosbell", "Arrow1x1"), {}),
    "ink_arrowhead": ("Arrowhead", "Classic dungeon", ("gosbell", "TriangleArrowhead1x1"), {}),
    "ink_cross": ("Cross", "Classic dungeon", ("gosbell", "Cross1x1"), {}),
}
PROPS = dict(CLASSIC)

# pictures for the built-in map symbols (drawing.SYMBOLS), saved as sym_<key>.webp; door_open is how an opened door
# looks. tree, rock and water have no picture: they keep their glyph.
SYMBOL_PICTURES = {
    "door": ("gosbell", "Door1x1"), "door_open": ("gosbell", "DoorArchway1x1"),
    "locked_door": ("gosbell", "DoorLocked1x1"), "secret_door": ("gosbell", "DoorSecret1x1"),
    "stairs_up": ("gosbell", "StairSpiralCircleUp1x1"), "stairs_down": ("gosbell", "StairSpiralCircleDown1x1"),
    "window": ("gosbell", "Window1x1"), "trap": ("gosbell", "Trap1x1"), "pillar": ("gosbell", "CircleFilled1x1"),
    "statue": ("gosbell", "Statue1x1"), "fire": ("gosbell", "FireCamp1x1"), "chest": ("gosbell", "Chest1x1"),
    "altar": ("gosbell", "Altar1x1"), "lever": ("gosbell", "Trigger1x1"),
}
DOOR_SYMBOLS = ("door", "locked_door", "secret_door")       # as sight.DOORS: they open and close
# props that open and close too (O, right-click): a door prop shut fills its tile (total cover, nobody passes); a
# window, gate or portcullis shut can't be walked through. Open, they stand aside: an archway's picture, the leaf swung.
DOOR_PROPS = ("ink_door", "ink_double_door", "ink_locked_door", "ink_secret_door", "ink_concealed_door", "ink_magic_door",
              "ink_sliding_door", "ink_revolving_door")
HATCHES = ("window", "ink_window", "ink_gate", "ink_portcullis")
OPENS = DOOR_SYMBOLS + DOOR_PROPS + HATCHES


# props of the dropped packs (old maps keep them) -> the nearest prop or built-in symbol; the ones not listed are left off
LEGACY = {
    **dict.fromkeys(("autumn_tree", "pine", "autumn_pine", "dead_tree", "oak", "dark_pine", "fruit_tree", "bush",
                     "berry_bush", "hedge", "cactus", "ink_tree", "ink_plants"), "tree"),
    **dict.fromkeys(("rubble", "ore", "stump", "mossy_rock", "stalagmite", "mossy_stalagmite", "broken_pillar",
                     "loose_stones", "ink_rubble"), "rock"),
    **dict.fromkeys(("boulder", "stone_pillar"), "ink_pillar"),
    **dict.fromkeys(("tomb", "gravestone", "grave_cross"), "ink_grave"),
    **dict.fromkeys(("iron_chest", "crate", "veg_crate", "cabbage_crate", "supply_box", "small_crate", "ink_crate",
                     "ink_small_crate"), "ink_chest"),
    **dict.fromkeys(("barrel", "water_barrel", "grain_sack", "ink_barrel", "ink_barrels", "ink_stacked_barrels"), "ink_cask"),
    **dict.fromkeys(("gold", "coins", "gold_nuggets", "sack", "dungeon_sack"), "ink_loot"),
    **dict.fromkeys(("torch", "candelabra", "candle", "chandelier"), "ink_light"),
    **dict.fromkeys(("forge", "hearth"), "ink_fireplace"),
    **dict.fromkeys(("bookshelf", "dresser", "cupboard"), "ink_bookcase"),
    **dict.fromkeys(("bed", "small_bed"), "ink_bed"),
    **dict.fromkeys(("chair", "armchair"), "ink_chair"),
    **dict.fromkeys(("skull", "bones", "skull_bones", "skeleton"), "ink_danger"),
    "fountain": "ink_fountain", "campfire": "ink_campfire", "brazier": "ink_fire", "table": "ink_table",
    "round_table": "ink_round_table", "stool": "ink_stool", "ladder": "ink_ladder_up", "fence": "ink_railing",
    "gate": "ink_gate", "ink_puddle": "water",
}


def upgrade(drawings) -> list:
    """The map's drawings with every prop of a dropped pack swapped for its LEGACY stand-in (or left off), in place."""
    from .drawing import SYMBOLS
    if not drawings:
        return drawings or []
    out = []
    for d in drawings or []:
        if d.get("type") == "symbol" and d.get("sym") not in PROPS and d.get("sym") not in SYMBOLS:
            if d.get("sym") not in LEGACY:
                continue
            d["sym"] = LEGACY[d["sym"]]
        out.append(d)
    drawings[:] = out
    return drawings


def where(key: str) -> tuple:
    """(pack, picture file, 0, tiles across) of a prop."""
    pos = PROPS[key][2]
    return pos[0], pos[1], 0, pos[2] if len(pos) > 2 else 1


def terrain(key: str) -> Optional[dict]:
    p = PROPS.get(key)
    return p[3] if p else None


def span(key: str) -> int:
    return where(key)[3] if key in PROPS else 1


def style(key: str) -> str:
    """'classic' (hand-drawn ink): the only look left."""
    return "classic"


def smooth(key: str) -> bool:
    """Scale the picture with smoothing? Yes: they are all hand-drawn."""
    return True


def shown(key: str, is_open: bool = False) -> str:
    """The picture key a symbol shows: an opened door, window or gate shows door_open (an archway: the wall's gap)."""
    return "door_open" if is_open and key in OPENS and path("door_open") else key


def file_name(key: str) -> str:
    """The picture's file in an asset module's assets/props: <key>.webp for a prop, sym_<key>.webp for a built-in symbol."""
    return f"{key}.webp" if key in PROPS else f"sym_{key}.webp"


def path(key: str) -> Optional[str]:
    """The picture of a prop or of a built-in map symbol (when it has one), or None."""
    if not re.fullmatch(r"[a-z0-9_]+", key or "") or (key not in PROPS and key not in SYMBOL_PICTURES):
        return None
    from ...core import assets
    return assets.asset("props", file_name(key))


@lru_cache(maxsize=1)
def portal_view() -> dict:
    """How the players' page draws the pictures: {'props': {key: tiles across} of every prop and every built-in symbol
    that has a picture (door_open too), 'smooth': [keys drawn smoothed]}."""
    keys = list(PROPS) + [k for k in SYMBOL_PICTURES if k not in PROPS and path(k)]
    return {"props": {k: span(k) for k in keys}, "smooth": [k for k in keys if smooth(k)]}


def credits() -> str:
    """One line crediting every pack the pictures come from (the props window shows it)."""
    return CREDITS_LINE


def catalog() -> list:
    """[{'key', 'label', 'category', 'tip', 'span', 'style', 'smooth'}] for the props window, in category order."""
    out = []
    for key, (label, cat, _pos, rules) in PROPS.items():
        bits = []
        if rules.get("cover"):
            bits.append(f"{rules['cover']} cover")
        if rules.get("blocks"):
            bits.append("blocks the tile")
        if rules.get("difficult"):
            bits.append("difficult terrain")
        if rules.get("light"):
            bits.append(f"light {rules['light'][0]} ft")
        out.append({"key": key, "label": label, "category": cat, "tip": ", ".join(bits) or "decoration", "span": span(key),
                    "style": style(key), "smooth": smooth(key)})
    return out
