"""Spells compiled for the battle: how each is aimed (the BG3-style targeting the UI shows) and what it does.

spec(sp) is the static part, cached per spell:
    cost            'action' | 'bonus' | 'reaction' | 'long'
    range           feet (self 0, touch 5, sight 9999)
    target          {'type': 'self' | 'creature' | 'split' | 'point' | 'self_area' | 'none',
                     'count', 'per_level' (more targets per slot level above), 'base_level', 'allies' (meant for friends),
                     'aim' (self_area: a direction is needed), 'teleport' (feet: a point to move to)}
    area            {'shape', 'size', 'width', 'origin': 'caster' | 'point'} for area spells
    kind            how it is played out (see spells.py): attack / save / auto / heal / buff / pool / cleanse / revive /
                    power_word / summon / zone / teleport / utility / special
    zone            a lasting area (see zones.py)
    action          what the caster can do again on later turns while the spell lasts (spell actions)
    on_hit, rider, push, effect, dot ...   special parts (SPECIAL table)
    choose_type + options   the caster's pick (a damage type, Eyebite's effect, Bestow Curse's ability, a form) and what it replaces: options[pick]
                            = {conds, repeat, rounds, effect, ends_on} on a failed save, or {effect|mods, temp} on a buff; cure: conditions a buff takes off
cast(sp, slot, caster_level, mod) adds the slot-dependent numbers: damage parts after upcasting, target count.
"""
import re
from functools import lru_cache
from typing import Optional, Tuple

from . import combat_rules as CR
from . import economy as EC
from . import spell_effects as X

NUM = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9,
       "ten": 10, "twelve": 12}


def parse_range(text: str) -> Tuple[int, str]:
    t = (text or "").strip().lower()
    if t.startswith("self"):
        return 0, "self"
    if t.startswith("touch"):
        return 5, "touch"
    if t.startswith("sight") or t.startswith("unlimited") or t.startswith("special"):
        return 9999, "sight"
    m = re.match(r"(\d+)\s*(feet|foot|miles?)", t)
    if m:
        n = int(m.group(1))
        return (n * 5280 if m.group(2).startswith("mile") else n), "ranged"
    return 60, "ranged"


def _count(text: str, hl: str) -> Tuple[int, int, bool]:
    """(creatures it can target, more per slot level, 'any number')."""
    t = text.lower()
    if re.search(r"any number of (?:willing )?creatures", t):
        return 99, 0, True
    m = re.search(r"(?:up to|choose|target|bless|curse) (one|two|three|four|five|six|seven|eight|nine|ten|twelve|\d+) (?:\w+ )?(?:creatures|targets|humanoids|beasts|willing creatures|allies)", t)
    n = int(NUM.get(m.group(1), m.group(1))) if m and not m.group(1).isdigit() else (int(m.group(1)) if m else 1)
    per = 0
    hm = re.search(r"(one|two|three) additional (?:creature|target|humanoid|beast|undead|willing creature)", (hl or "").lower())
    if hm:
        per = NUM[hm.group(1)]
    return n, per, False


# ---------------------------------------------------------------------- special cases, checked by hand
# Keys: see the module text. Damage 'parts' replace what the text reader found; 'up' is the extra dice per slot level.
SPECIAL = {
    # ---- fixes of misread spells
    "green-flame blade": {"kind": "weapon_spell", "target": {"type": "creature", "count": 1}, "range": 5,
                          "cantrip_parts": {1: "0", 5: "1d8", 11: "2d8", 17: "3d8"}, "splash": {"dice": {1: "MOD", 5: "1d8+MOD", 11: "2d8+MOD", 17: "3d8+MOD"}, "type": "fire"},
                          "type": "fire", "note": "a melee weapon attack; fire leaps to a creature within 5 ft of the target"},
    "booming blade": {"kind": "weapon_spell", "target": {"type": "creature", "count": 1}, "range": 5,
                      "cantrip_parts": {1: "0", 5: "1d8", 11: "2d8", 17: "3d8"}, "type": "thunder",
                      "mark": {"dice": {1: "1d8", 5: "2d8", 11: "3d8", 17: "4d8"}, "type": "thunder"},
                      "note": "a melee weapon attack; if the target moves before your next turn it takes thunder damage"},
    "polymorph": {"kind": "save", "save": "wis", "conds": [], "transform": True, "parts": []},
    "true polymorph": {"kind": "save", "save": "wis", "conds": [], "transform": True, "parts": []},
    "spirit guardians": {"kind": "zone", "area": {"shape": "emanation", "size": 15, "origin": "caster"}, "target": {"type": "self"},
                         "choose_type": ["radiant", "necrotic"],
                         "zone": {"follow": True, "enter": True, "start": True, "affects": "enemies", "save": "wis", "half": True,
                                  "parts": [["3d8", "radiant"]], "up": "1d8", "slow": True, "on_cast": False}},
    "witch bolt": {"kind": "attack", "parts": [["1d12", "lightning"]], "up": "1d12",
                   "action": {"name": "Witch Bolt (arc)", "cost": "action", "auto": [["1d12", "lightning"]], "same_target": True, "range": 30,
                              "up": None}},                     # only the initial damage grows when upcast
    "wall of fire": {"kind": "zone", "area": {"shape": "line", "size": 60, "width": 5, "origin": "point"}, "target": {"type": "point"},
                     "zone": {"enter": True, "end": True, "save": "dex", "half": True, "parts": [["5d8", "fire"]], "up": "1d8", "on_cast": True,
                              "opaque": True}},          # it burns only on its own tiles (what the maps draw), no hot side
    "web": {"kind": "zone", "area": {"shape": "cube", "size": 20, "origin": "point"},
            "zone": {"enter": True, "start": True, "save": "dex", "conds": ["Restrained"], "difficult": True, "obscure": "light",
                     "on_cast": True, "parts": [], "escape": "str", "burns": True}},
    "bestow curse": {"kind": "save", "save": "wis", "parts": [], "repeat": None,            # no save to shake it off: it lasts while you concentrate
                     "effect": {"mods": {"extra_damage": ("1d8", "necrotic")}, "note": "takes 1d8 necrotic more from your hits"},
                     "choose_type": ["damage", "strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma", "attacks", "wasted turns"],     # the curse: extra damage, disadvantage on one ability's checks and saves, on attacks against you, or a lost action
                     "options": dict({n: {"effect": {"mods": {"save_dis": [n[:3]], "check_dis": [n[:3]]}, "note": f"cursed: disadvantage on {n.capitalize()} checks and saving throws"}}
                                      for n in ("strength", "dexterity", "constitution", "intelligence", "wisdom", "charisma")},
                                     attacks={"effect": {"mods": {"shun": "*"}, "note": "cursed: disadvantage on attack rolls against the caster"}},
                                     **{"wasted turns": {"effect": {"mods": {"waste_turn": True}, "note": "cursed: a Wisdom save each turn or its action is wasted"}}})},
    "destructive wave": {"kind": "save", "save": "con", "foes_only": True, "conds": [], "prone": True, "choose_type": ["radiant", "necrotic"],
                         "parts": [["5d6", "thunder"], ["5d6", "$type"]]},
    "contagion": {"on_hit": {"conds": ["Poisoned"], "repeat_ab": "con", "mods": {"stone_need": 3},
                             "note": "poisoned: three failed saves bring the disease on, three successes end the spell"},
                  "choose_type": ["blinding sickness", "filth fever", "flesh rot", "mindfire", "seizure", "slimy doom"],
                  "options": {"blinding sickness": {"name": "Blinding Sickness", "conds": ["Blinded"], "mods": {"save_dis": ["wis"], "check_dis": ["wis"]}},
                              "filth fever": {"name": "Filth Fever", "mods": {"save_dis": ["str"], "check_dis": ["str"]}},
                              "flesh rot": {"name": "Flesh Rot", "mods": {"check_dis": ["cha"]}},
                              "mindfire": {"name": "Mindfire", "mods": {"save_dis": ["int"], "check_dis": ["int"], "confused": True}},
                              "seizure": {"name": "Seizure", "mods": {"save_dis": ["dex"], "check_dis": ["dex"]}},
                              "slimy doom": {"name": "Slimy Doom", "mods": {"save_dis": ["con"], "check_dis": ["con"]}}}},
    "enthrall": {"kind": "save", "save": "wis", "conds": [], "repeat": None, "target": {"type": "creature", "count": 99},     # creatures of your choice
                 "effect": {"mods": {"perception_dis": True}, "note": "enthralled: disadvantage on Perception to notice anyone else"}},
    "melf's acid arrow": {"kind": "attack", "parts": [["4d4", "acid"]], "up": "1d4", "miss_half": True,
                          "dot": {"dice": "2d4", "type": "acid", "when": "end", "times": 1, "up": "1d4"}},
    "meld into stone": {"kind": "self_effect", "effect": {"mods": {}, "note": "melded into stone"}, "parts": []},
    "create homunculus": {"kind": "utility", "parts": []},
    "contact other plane": {"kind": "utility", "parts": []},
    "dream": {"kind": "utility", "parts": []},
    "dispel evil and good": {"kind": "buff", "target": {"type": "self"}, "effect": {"mods": {"warded_from": ["celestial", "elemental", "fey", "fiend", "undead"]},
                                                                                         "note": "celestials, elementals, fey, fiends and undead have disadvantage against you"},
                             "action": {"name": "Break Enchantment", "cost": "action", "break_ench": True, "range": 5},     # touch: ends a charm, fear or possession by one of them; ends the spell
                             "more_actions": [{"name": "Dismissal", "cost": "action", "atk": "melee", "dismiss": True, "range": 5}]},     # a melee spell attack, then a Charisma save or banished; ends the spell
    "otto's irresistible dance": {"kind": "save", "save": "wis", "conds": [], "repeat": "end", "rounds": 10, "auto_hit": True,    # no save to resist it
                                  "effect": {"mods": {"speed_set": 0, "attacks_against": "adv", "attacks_with": "dis", "save_dis": ["dex"]}, "note": "dances: can't move, attacks against it have advantage"}},
    "phantasmal killer": {"kind": "save", "save": "wis", "conds": ["Frightened"], "repeat": None, "rounds": 10, "parts": [],     # the dot's save ends it
                          "dot": {"dice": "4d10", "type": "psychic", "when": "end", "save": "wis", "up": "1d10"}},
    "tasha's caustic brew": {"kind": "save", "save": "dex", "parts": [], "area": {"shape": "line", "size": 30, "width": 5, "origin": "caster"},
                             "dot": {"dice": "2d4", "type": "acid", "when": "start", "up": "2d4"}},
    "harm": {"kind": "save", "save": "con", "parts": [["14d6", "necrotic"]], "half": True, "min_hp": 1, "max_cut": True},
    "wind wall": {"kind": "zone", "area": {"shape": "line", "size": 50, "width": 5, "origin": "point"},
                  "zone": {"on_cast": True, "save": "str", "half": True, "parts": [["3d8", "bludgeoning"]], "ranged_block": True}},
    "ice knife": {"kind": "attack", "parts": [["1d10", "piercing"]], "explode": {"radius": 5, "save": "dex", "parts": [["2d6", "cold"]], "up": "1d6"}},
    "magic stone": {"kind": "attack", "range": 60, "parts": [["1d6+MOD", "bludgeoning"]]},
    "toll the dead": {"kind": "save", "save": "wis", "wounded_die": "d12"},
    # ---- riders on cantrips and attacks
    "ray of frost": {"on_hit": {"mods": {"speed": -10}, "until": "caster_start", "note": "speed -10 ft until your next turn"}},
    "chill touch": {"on_hit": {"mods": {"no_heal": True, "shun": "undead"}, "until": "caster_start",      # an undead also attacks you at disadvantage
                               "note": "can't regain hit points until your next turn"}},
    "shocking grasp": {"adv_vs_metal": True, "on_hit": {"mods": {"no_reactions": True}, "until": "target_start", "note": "can't take reactions"}},
    "guiding bolt": {"on_hit": {"mods": {"attacks_against": "adv", "once": True}, "until": "caster_end_next", "note": "the next attack against it has advantage"}},
    "ray of sickness": {"rider": {"ab": "con", "conds": ["Poisoned"], "rounds": 1}},
    "vicious mockery": {"effect": {"mods": {"attacks_with": "dis", "once": True}, "until": "target_end_next", "note": "disadvantage on its next attack"}},
    "mind sliver": {"effect": {"mods": {"save": "-1d4", "once": True}, "until": "caster_end_next", "note": "-1d4 on its next save"}},
    "frostbite": {"effect": {"mods": {"attacks_with": "dis", "once": True}, "until": "target_end_next", "note": "disadvantage on its next weapon attack"}},
    "sapping sting": {"prone": True},
    "thunderwave": {"push": 10},
    "lightning lure": {"pull": 10, "target": {"type": "creature", "count": 1}, "range": 15, "area": None},     # one creature, pulled towards you
    "earth tremor": {"area": {"shape": "emanation", "size": 10, "origin": "caster"}, "target": {"type": "self_area", "aim": False}, "range": 0},
    "thorn whip": {"on_hit": {"pull": 10}},
    "gust": {"kind": "save", "save": "str", "parts": [], "push": 5},
    "thunderclap": {"area": {"shape": "emanation", "size": 5, "origin": "caster"}, "target": {"type": "self_area", "aim": False}, "range": 0},
    "word of radiance": {"area": {"shape": "emanation", "size": 5, "origin": "caster"}, "target": {"type": "self_area", "aim": False}, "foes_only": True},
    "sword burst": {"area": {"shape": "emanation", "size": 5, "origin": "caster"}, "target": {"type": "self_area", "aim": False}},
    "acid splash": {"target": {"type": "creature", "count": 2, "near": 5}},
    "tasha's hideous laughter": {"kind": "save", "save": "wis", "conds": ["Prone", "Incapacitated"], "repeat": "end", "rounds": 10,
                                 "effect": {"mods": {"save_on_damage": True}, "note": "laughing helplessly"}},     # hurt: a save with advantage
    "hypnotic pattern": {"conds": ["Charmed", "Incapacitated"], "effect": {"mods": {"speed_set": 0}}, "ends_on": ["damage"], "rounds": 10},
    "fear": {"conds": ["Frightened"], "repeat": "end", "rounds": 10,                 # a save only where it can't see the caster
             "effect": {"mods": {"unseen_only": True}, "note": "fleeing in fear"}},
    "command": {"kind": "save", "save": "wis", "conds": ["Incapacitated"], "prone": True, "rounds": 0,      # grovel: prone, and its next turn is lost
                "choose_type": ["grovel", "approach", "drop", "flee", "halt"],                        # the caster's command word (spells._command_word)
                "effect": {"mods": {"speed_set": 0, "keeps_conc": True}, "until": "target_end_next", "note": "grovels (falls prone, ends its turn)"}},
    "blindness/deafness": {"conds": ["Blinded"], "repeat": "end", "rounds": 10, "choose_type": ["blinded", "deafened"],
                           "options": {"blinded": {"conds": ["Blinded"]}, "deafened": {"conds": ["Deafened"]}}},
    "faerie fire": {"kind": "save", "save": "dex", "area": {"shape": "cube", "size": 20, "origin": "point"},
                    "effect": {"mods": {"attacks_against": "adv", "outlined": True}, "note": "outlined: attacks against it have advantage, no hiding in invisibility"},
                    "rounds": 10, "conds": []},
    "entangle": {"kind": "zone", "area": {"shape": "square", "size": 20, "origin": "point"},
                 "zone": {"on_cast": True, "save": "str", "conds": ["Restrained"], "difficult": True, "parts": [], "escape": "str"}},
    "grease": {"kind": "zone", "area": {"shape": "square", "size": 10, "origin": "point"},
               "zone": {"on_cast": True, "enter": True, "end": True, "save": "dex", "prone": True, "difficult": True, "parts": []}},
    # ---- lasting zones
    "create bonfire": {"kind": "zone", "area": {"shape": "square", "size": 5, "origin": "point"},
                       "zone": {"on_cast": True, "enter": True, "end": True, "save": "dex", "parts": "CANTRIP", "light": "bright"}},
    "cloud of daggers": {"kind": "zone", "area": {"shape": "square", "size": 5, "origin": "point"},
                         "zone": {"enter": True, "start": True, "parts": [["4d4", "slashing"]], "up": "2d4"}},
    "moonbeam": {"kind": "zone", "area": {"shape": "cylinder", "size": 5, "origin": "point"},
                 "zone": {"enter": True, "start": True, "save": "con", "half": True, "parts": [["2d10", "radiant"]], "up": "1d10", "light": "dim",
                          "dis_types": ["shapechanger"], "revert_shape": True,       # a shapechanger saves with disadvantage; failing, it's its true self
                          "move": {"cost": "action", "feet": 60}}},
    "spike growth": {"kind": "zone", "area": {"shape": "sphere", "size": 20, "origin": "point"},
                     "zone": {"per_5ft": [["2d4", "piercing"]], "difficult": True}},
    "darkness": {"kind": "zone", "area": {"shape": "sphere", "size": 15, "origin": "point"}, "zone": {"darkness": True}},
    "fog cloud": {"kind": "zone", "area": {"shape": "sphere", "size": 20, "origin": "point"}, "zone": {"obscure": "heavy"}, "grow": 20},
    "silence": {"kind": "zone", "area": {"shape": "sphere", "size": 20, "origin": "point"}, "zone": {"silence": True}},
    "hunger of hadar": {"kind": "zone", "area": {"shape": "sphere", "size": 20, "origin": "point"},
                        "zone": {"darkness": True, "difficult": True, "start_auto": [["2d6", "cold"]], "end_save": {"save": "dex", "parts": [["2d6", "acid"]]}}},
    "sleet storm": {"kind": "zone", "area": {"shape": "cylinder", "size": 40, "origin": "point"},
                    "zone": {"obscure": "heavy", "difficult": True, "enter": True, "start": True, "save": "dex", "prone": True, "parts": [],
                             "conc_save": "con"}},
    "stinking cloud": {"kind": "zone", "area": {"shape": "sphere", "size": 20, "origin": "point"},
                       "zone": {"obscure": "heavy", "start": True, "save": "con", "conds": ["Incapacitated"], "cond_rounds": 1, "parts": []}},
    "evard's black tentacles": {"kind": "zone", "area": {"shape": "square", "size": 20, "origin": "point"},
                                "zone": {"on_cast": True, "enter": True, "start": True, "save": "dex", "parts": [["3d6", "bludgeoning"]],
                                         "conds": ["Restrained"], "difficult": True, "escape": "str"}},
    "insect plague": {"kind": "zone", "area": {"shape": "sphere", "size": 20, "origin": "point"},
                      "zone": {"on_cast": True, "enter": True, "end": True, "save": "con", "half": True, "parts": [["4d10", "piercing"]],
                               "up": "1d10", "obscure": "light", "difficult": True}},      # entering, or ending a turn there
    "cloudkill": {"kind": "zone", "area": {"shape": "sphere", "size": 20, "origin": "point"},
                  "zone": {"on_cast": True, "enter": True, "start": True, "save": "con", "half": True, "parts": [["5d8", "poison"]], "up": "1d8",
                           "obscure": "heavy"}},
    "incendiary cloud": {"kind": "zone", "area": {"shape": "sphere", "size": 20, "origin": "point"},
                         "zone": {"on_cast": True, "enter": True, "end": True, "save": "dex", "half": True, "parts": [["10d8", "fire"]], "obscure": "heavy"}},
    "sickening radiance": {"kind": "zone", "area": {"shape": "sphere", "size": 30, "origin": "point"},
                           "zone": {"enter": True, "start": True, "save": "con", "parts": [["4d10", "radiant"]], "exhaustion": True}},
    "wall of light": {"kind": "zone", "area": {"shape": "line", "size": 60, "width": 5, "origin": "point"},
                      "zone": {"on_cast": True, "enter": True, "save": "con", "half": True, "parts": [["4d8", "radiant"]], "up": "1d8", "conds": ["Blinded"],
                               "cond_rounds": 10, "repeat": "end", "opaque": True},
                      "action": {"name": "Wall of Light: beam", "cost": "action", "atk": "ranged", "parts": [["4d8", "radiant"]], "range": 60,
                                 "up": "1d8"}},
    "wall of thorns": {"kind": "zone", "area": {"shape": "line", "size": 60, "width": 5, "origin": "point"},
                       "zone": {"on_cast": True, "enter": True, "end": True, "save": "dex", "half": True, "parts": [["7d8", "piercing"]], "up": "1d8",
                                "difficult": True, "opaque": True}},
    "wall of ice": {"kind": "zone", "area": {"shape": "line", "size": 50, "width": 5, "origin": "point"},
                    "zone": {"on_cast": True, "save": "dex", "half": True, "parts": [["10d6", "cold"]], "up": "2d6", "blocks": True}},
    "blade barrier": {"kind": "zone", "area": {"shape": "line", "size": 100, "width": 5, "origin": "point"},
                      "zone": {"enter": True, "start": True, "save": "dex", "half": True, "parts": [["6d10", "slashing"]], "difficult": True}},
    "wall of stone": {"kind": "zone", "area": {"shape": "line", "size": 50, "width": 5, "origin": "point"}, "zone": {"blocks": True, "opaque": True}},
    "wall of force": {"kind": "zone", "area": {"shape": "line", "size": 50, "width": 5, "origin": "point"}, "zone": {"blocks": True}},
    "wall of sand": {"kind": "zone", "area": {"shape": "line", "size": 30, "width": 10, "origin": "point"}, "zone": {"obscure": "heavy", "difficult": True}},
    "wall of water": {"kind": "zone", "area": {"shape": "line", "size": 30, "width": 5, "origin": "point"}, "zone": {"difficult": True, "ranged_dis": True}},
    "forcecage": {"kind": "zone", "area": {"shape": "square", "size": 20, "origin": "point"}, "zone": {"cage": True}},
    "storm sphere": {"kind": "zone", "area": {"shape": "sphere", "size": 20, "origin": "point"},
                     "zone": {"on_cast": True, "end": True, "save": "str", "parts": [["2d6", "bludgeoning"]], "up": "1d6", "difficult": True},
                     "action": {"name": "Storm Sphere bolt", "cost": "bonus", "atk": "ranged", "parts": [["4d6", "lightning"]], "range": 60,
                                "up": "1d6"}},
    "maelstrom": {"kind": "zone", "area": {"shape": "cylinder", "size": 30, "origin": "point"},
                  "zone": {"start": True, "save": "str", "parts": [["6d6", "bludgeoning"]], "difficult": True, "pull": 10}},
    "dawn": {"kind": "zone", "area": {"shape": "cylinder", "size": 30, "origin": "point"},
             "zone": {"on_cast": True, "end": True, "save": "con", "half": True, "parts": [["4d10", "radiant"]], "light": "bright",   # ending a turn in it
                      "move": {"cost": "bonus", "feet": 60}}},
    "guardian of faith": {"kind": "zone", "area": {"shape": "emanation", "size": 10, "origin": "point"},
                          "zone": {"enter": True, "start": True, "affects": "enemies", "save": "dex", "half": True, "parts": [["20", "radiant"]], "cap": 60}},
    "healing spirit": {"kind": "zone", "area": {"shape": "square", "size": 5, "origin": "point"},
                       "zone": {"enter": True, "start": True, "affects": "allies", "heal": "1d6", "up_heal": "1d6", "uses": "1+MOD",
                                "move": {"cost": "bonus", "feet": 30}}},
    "dust devil": {"kind": "zone", "area": {"shape": "square", "size": 5, "origin": "point"},
                   "zone": {"end": True, "save": "str", "half": True, "parts": [["1d8", "bludgeoning"]], "up": "1d8", "push": 10, "move": {"cost": "bonus", "feet": 30}}},
    "flaming sphere": {"kind": "zone", "area": {"shape": "square", "size": 5, "origin": "point"},
                       "zone": {"end": True, "save": "dex", "half": True, "parts": [["2d6", "fire"]], "up": "1d6", "light": "bright",
                                "move": {"cost": "bonus", "feet": 30, "ram": True}}},
    "cordon of arrows": {"kind": "zone", "area": {"shape": "sphere", "size": 30, "origin": "point"},
                         "zone": {"enter": True, "affects": "enemies", "save": "dex", "parts": [["1d6", "piercing"]], "cap_hits": 4}},
    "ice storm": {"leave_zone": {"difficult": True, "rounds": 1}},
    "investiture of flame": {"kind": "buff", "target": {"type": "self"}, "effect": {"mods": {"immune": ["fire"], "resist": ["cold"]}, "note": "immune to fire"},
                             "aura": {"size": 5, "end": True, "parts": [["1d10", "fire"]]},
                             "action": {"name": "Investiture of Flame: line", "cost": "action", "area": {"shape": "line", "size": 15, "width": 5, "origin": "caster"},
                                        "save": "dex", "half": True, "parts": [["4d8", "fire"]]}},
    "aura of vitality": {"kind": "buff", "target": {"type": "self"}, "effect": {"mods": {}, "note": "can heal creatures within 30 ft"},
                         "action": {"name": "Aura of Vitality: heal", "cost": "bonus", "heal": "2d6", "range": 30}},
    # ---- spells cast again on later turns
    "spiritual weapon": {"kind": "attack", "atk_type": "melee", "range": 60, "parts": [["1d8+MOD", "force"]], "up_every": 2, "up": "1d8",
                         "action": {"name": "Spiritual Weapon", "cost": "bonus", "atk": "melee", "parts": [["1d8+MOD", "force"]], "range": 60}},
    "call lightning": {"kind": "save", "save": "dex", "half": True, "area": {"shape": "sphere", "size": 5, "origin": "point"},
                       "parts": [["3d10", "lightning"]], "up": "1d10",
                       "action": {"name": "Call Lightning bolt", "cost": "action", "area": {"shape": "sphere", "size": 5, "origin": "point"},
                                  "save": "dex", "half": True, "parts": [["3d10", "lightning"]], "range": 120}},
    "heat metal": {"kind": "auto", "parts": [["2d8", "fire"]], "up": "1d8", "hamper": True,
                   "action": {"name": "Heat Metal", "cost": "bonus", "auto": [["2d8", "fire"]], "same_target": True, "range": 60, "hamper": True}},
    "vampiric touch": {"kind": "attack", "atk_type": "melee", "parts": [["3d6", "necrotic"]], "up": "1d6", "drain": 0.5,
                       "action": {"name": "Vampiric Touch", "cost": "action", "atk": "melee", "parts": [["3d6", "necrotic"]], "drain": 0.5, "range": 5}},
    "protection from poison": {"kind": "buff", "cure": ["Poisoned"]},
    "flesh to stone": {"effect": {"mods": {"stone_need": 3, "stoning": True}, "note": "turning to stone: three failed saves petrify it, three successes end the spell"}},
    "enervation": {"kind": "save", "save": "dex", "parts": [["4d8", "necrotic"]], "half": True, "up": "1d8", "drain": 0.5,     # 2d8 on a success
                   "action": {"name": "Enervation", "cost": "action", "auto": [["4d8", "necrotic"]], "same_target": True, "drain": 0.5}},
    "eyebite": {"kind": "save", "save": "wis", "conds": ["Frightened"], "rounds": 10, "range": 60, "target": {"type": "creature", "count": 1},
                "choose_type": ["asleep", "panicked", "sickened"],           # no save to shake off the first two: damage wakes it, distance ends the fear
                "options": {"asleep": {"conds": ["Unconscious"], "repeat": None, "ends_on": ["damage"]},
                            "panicked": {"conds": ["Frightened"], "repeat": None},
                            "sickened": {"conds": [], "repeat": "end", "effect": {"mods": {"attacks_with": "dis", "check_dis": True},
                                                                                   "note": "sickened: disadvantage on attack rolls and ability checks"}}},
                "action": {"name": "Eyebite", "cost": "action", "save": "wis", "conds": ["Frightened"], "range": 60}},
    "melf's minute meteors": {"kind": "save", "save": "dex", "half": True, "area": {"shape": "sphere", "size": 5, "origin": "point"}, "range": 120,
                              "parts": [["2d6", "fire"]], "action": {"name": "Minute Meteor", "cost": "bonus", "area": {"shape": "sphere", "size": 5, "origin": "point"},
                                                                     "save": "dex", "half": True, "parts": [["2d6", "fire"]], "range": 120,
                                                                     "uses": 5, "uses_up": 2}},       # six meteors, one spent on casting
    "crown of stars": {"kind": "buff", "target": {"type": "self"}, "area": None, "effect": {"mods": {}, "note": "seven motes of starlight orbit you"},
                       "action": {"name": "Crown of Stars: mote", "cost": "bonus", "atk": "ranged", "parts": [["4d12", "radiant"]], "range": 120, "uses": 7, "uses_up": 2}},
    "chain lightning": {"target": {"type": "creature", "count": 4, "per_level": 1}},          # the first target and three bolts leaping from it
    "bones of the earth": {"area": {"shape": "square", "size": 5, "origin": "point"}},     # one 5-foot pillar
    "mordenkainen's sword": {"kind": "attack", "atk_type": "melee", "range": 60, "parts": [["3d10", "force"]],
                             "action": {"name": "Mordenkainen's Sword", "cost": "bonus", "atk": "melee", "parts": [["3d10", "force"]], "range": 60}},
    "bigby's hand": {"kind": "attack", "atk_type": "melee", "range": 120, "parts": [["4d8", "force"]], "up": "2d8",
                     "action": {"name": "Bigby's Hand: fist", "cost": "bonus", "atk": "melee", "parts": [["4d8", "force"]], "range": 120},
                     "more_actions": [                                  # (a Strength save stands in for the hand's contested checks)
                         {"name": "Bigby's Hand: shove", "cost": "bonus", "save": "str", "push": 20, "range": 120, "up": None},
                         {"name": "Bigby's Hand: grasp", "cost": "bonus", "save": "str", "conds": ["Grappled"], "range": 120, "up": None},
                         {"name": "Bigby's Hand: crush", "cost": "bonus", "auto": [["2d6+MOD", "bludgeoning"]], "range": 120, "up": "2d6"}]},
    "blade of disaster": {"kind": "attack", "atk_type": "melee", "range": 60, "parts": [["4d12", "force"]], "crit": 18, "n": 2,
                          "crit_bonus": [["4d12", "force"]],          # a crit deals 12d12 in all (doubled 8d12 + these)
                          "action": {"name": "Blade of Disaster", "cost": "bonus", "atk": "melee", "parts": [["4d12", "force"]], "n": 2, "crit": 18, "range": 30,
                                     "crit_bonus": [["4d12", "force"]]}},
    "dragon's breath": {"kind": "buff", "target": {"type": "creature", "count": 1, "allies": True}, "choose_type": ["acid", "cold", "fire", "lightning", "poison"], "up": "1d6",
                        "effect": {"mods": {}, "note": "can breathe as an action"},
                        "grant": {"name": "Dragon's Breath", "cost": "action", "area": {"shape": "cone", "size": 15, "origin": "caster"}, "save": "dex",
                                  "half": True, "parts": [["3d6", "$type"]]}},
    "holy weapon": {"action": {"name": "Holy Weapon burst", "cost": "bonus", "area": {"shape": "emanation", "size": 30, "origin": "caster"},
                               "save": "con", "half": True, "parts": [["4d6", "radiant"]], "conds": ["Blinded"], "ends_spell": True}},
    "crown of madness": {"kind": "save", "save": "wis", "conds": ["Charmed"], "repeat": "end", "rounds": 10,
                         "effect": {"mods": {"crowned": True}, "note": "crowned: attacks whom the caster chooses"}, "maintain": True,
                         "action": {"name": "Crown of Madness: maintain", "cost": "action", "maintain": True}},     # or the spell ends
    "swift quiver": {"kind": "buff", "target": {"type": "self"}, "effect": {"mods": {}, "note": "two weapon attacks as a bonus action each turn"},
                     "action": {"name": "Swift Quiver", "cost": "bonus", "weapon": "ranged", "n": 2}},
    "expeditious retreat": {"kind": "buff", "target": {"type": "self"}, "effect": {"mods": {}, "note": "Dash as a bonus action"}, "dash": True,
                            "action": {"name": "Expeditious Retreat: Dash", "cost": "bonus", "dash": True}},
    "far step": {"kind": "teleport", "target": {"type": "point", "teleport": 60}, "teleport": 60,
                 "action": {"name": "Far Step", "cost": "bonus", "teleport": 60}},
    # ---- movement
    "misty step": {"kind": "teleport", "target": {"type": "point", "teleport": 30}, "teleport": 30},
    "thunder step": {"kind": "teleport", "target": {"type": "point", "teleport": 90}, "teleport": 90,
                     "boom": {"radius": 10, "save": "con", "half": True, "parts": [["3d10", "thunder"]], "up": "1d10"}},
    "dimension door": {"kind": "teleport", "target": {"type": "point", "teleport": 500}, "teleport": 500},
    "ashardalon's stride": {"kind": "buff", "target": {"type": "self"}, "up": "1d6", "speed_up": 5,
                            "effect": {"mods": {"speed": 20, "no_opportunity": True, "trail": ("1d6", "fire")},
                                       "note": "+20 ft speed, no opportunity attacks, burns creatures it passes"}},
    "steel wind strike": {"kind": "steel_wind", "target": {"type": "creature", "count": 5}, "parts": [["6d10", "force"]], "atk_type": "melee", "range": 30,
                         "action": {"name": "Steel Wind Strike: teleport", "cost": "free", "teleport": 35, "uses": 1, "near_targets": True}},      # then a step to within 5 ft of one of the targets
    "vortex warp": {"kind": "save", "save": "con", "parts": [], "teleport_target": 90},
    "scatter": {"kind": "save", "save": "wis", "parts": [], "target": {"type": "creature", "count": 5}, "teleport_target": 120},
    "gust of wind": {"kind": "zone", "area": {"shape": "line", "size": 60, "width": 10, "origin": "caster"},       # blows for the whole minute
                     "target": {"type": "self_area", "aim": True}, "zone": {"start": True, "save": "str", "push": 15, "parts": []}},
    "maximilian's earthen grasp": {"kind": "save", "save": "str", "parts": [["2d6", "bludgeoning"]], "half": False, "conds": ["Restrained"], "repeat": None,
                                   "action": {"name": "Earthen Grasp (crush)", "cost": "action", "save": "str", "half": True,
                                              "parts": [["2d6", "bludgeoning"]], "range": 30}},
    "grasping vine": {"kind": "save", "save": "dex", "parts": [], "pull": 20, "action": {"name": "Grasping Vine", "cost": "bonus", "save": "dex", "pull": 20, "range": 30}},
    "earthbind": {"kind": "save", "save": "str", "parts": [], "effect": {"mods": {"fly_set": 0}, "note": "flying speed 0"}, "rounds": 10},
    "telekinesis": {"kind": "save", "save": "str", "parts": [], "conds": ["Restrained"], "rounds": 1,
                    "action": {"name": "Telekinesis: seize", "cost": "action", "save": "str", "conds": ["Restrained"], "range": 60}},   # again each round
    "otiluke's resilient sphere": {"kind": "save", "save": "dex", "parts": [], "effect": {"mods": {"untargetable": True, "speed_set": 0}, "note": "sealed in a sphere"}, "rounds": 10},
    "reverse gravity": {"kind": "save", "save": "dex", "parts": [], "area": {"shape": "cylinder", "size": 50, "origin": "point"}, "conds": ["Restrained"], "rounds": 10},
    # ---- effects on creatures that the text reader can't see
    "longstrider": {"kind": "buff", "effect": {"mods": {"speed": 10}, "note": "+10 ft speed"}, "rounds": 600},
    "fly": {"kind": "buff", "effect": {"mods": {"fly": 60}, "note": "flying speed 60 ft"}, "rounds": 100},
    "jump": {"kind": "buff", "effect": {"mods": {}, "note": "jump distance tripled"}, "rounds": 10},
    "spider climb": {"kind": "buff", "effect": {"mods": {"climb": True}, "note": "climbing speed"}, "rounds": 600},
    "darkvision": {"kind": "buff", "effect": {"mods": {"senses": {"darkvision": 60}}, "note": "darkvision 60 ft"}, "rounds": 4800},
    "see invisibility": {"kind": "buff", "target": {"type": "self"}, "effect": {"mods": {"senses": {"see_invisible": True}}, "note": "sees invisible creatures"}, "rounds": 600},
    "true seeing": {"kind": "buff", "effect": {"mods": {"senses": {"truesight": 120}}, "note": "truesight 120 ft"}, "rounds": 600},
    "death ward": {"kind": "buff", "effect": {"mods": {"death_ward": True}, "note": "drops to 1 HP instead of 0, once"}, "rounds": 4800},
    "invisibility": {"kind": "buff", "conds_on": ["Invisible"], "effect": {"mods": {"ends_on": ["attack", "cast"]}, "note": "invisible until it attacks or casts"}, "rounds": 600},
    "greater invisibility": {"kind": "buff", "conds_on": ["Invisible"], "effect": {"mods": {}, "note": "invisible"}, "rounds": 10},
    "haste": {"kind": "buff", "effect": {"mods": {"ac": 2, "save_adv": ["dex"], "speed_mult": 2, "extra_action": 1}, "note": "+2 AC, double speed, an extra action",
                                         "lethargy": True}, "rounds": 10},
    "blink": {"kind": "buff", "target": {"type": "self"}, "effect": {"mods": {"blink": True}, "note": "may vanish to the Ethereal Plane at the end of each turn"}, "rounds": 10},
    "mirror image": {"kind": "buff", "target": {"type": "self"}, "effect": {"mods": {"images": 3}, "note": "three duplicates"}, "rounds": 10},
    "sanctuary": {"kind": "buff", "effect": {"mods": {"sanctuary": True, "ends_on": ["attack", "cast_hostile"]}, "note": "attackers must save to target it"}, "rounds": 10},
    "fire shield": {"kind": "buff", "target": {"type": "self"}, "choose_type": ["fire", "cold"],
                    "effect": {"mods": {"resist": ["$other"], "retaliate": ("2d8", "$type")}, "note": "resists the element; melee attackers take 2d8"}, "rounds": 100},
    "armor of agathys": {"kind": "buff", "target": {"type": "self"}, "temp": "5", "temp_per_level": 5,
                         "effect": {"mods": {"retaliate": ("5", "cold"), "retaliate_while_temp": True}, "note": "melee attackers take cold damage"}, "rounds": 600},
    "fizban's platinum shield": {"kind": "buff", "effect": {"mods": {"ac": 2, "half_cover": True, "resist": ["acid", "cold", "fire", "lightning", "poison"],
                                                                     "evasion": True},
                                                            "note": "half cover, resists elements, evasion"}, "rounds": 10,
                                 "action": {"name": "Move Platinum Shield", "cost": "bonus", "move_mark": True}},     # to another creature
    "warding wind": {"kind": "buff", "target": {"type": "self"}, "effect": {"mods": {"ranged_against": "dis"}, "note": "ranged attacks against you have disadvantage"}, "rounds": 100},
    "slow": {"kind": "save", "save": "wis", "parts": [], "area": {"shape": "cube", "size": 40, "origin": "point"}, "repeat": "end", "rounds": 10,
             "target": {"type": "point", "max": 6},
             "effect": {"mods": {"ac": -2, "save_dis": ["dex"], "speed_mult": 0.5, "no_reactions": True, "one_action": True},
                        "note": "-2 AC, half speed, no reactions, an action or a bonus action"}},
    "enemies abound": {"kind": "save", "save": "int", "parts": [], "repeat": "damage", "rounds": 10, "effect": {"mods": {"enemies_abound": True}, "note": "can't tell friend from foe"}},
    "power word pain": {"kind": "power_word", "limit": 100, "effect": {"mods": {"speed_set": 10, "attacks_with": "dis", "check_dis": True, "save_dis": ["str", "dex", "con", "int", "wis", "cha"]},
                                                                     "note": "wracked with pain"}, "repeat": "end", "save": "con"},
    "divine word": {"kind": "divine_word", "save": "cha", "target": {"type": "creature", "count": 99}},
    "banishment": {"kind": "save", "save": "cha", "parts": [], "conds": ["Incapacitated"], "effect": {"mods": {"banished": True, "untargetable": True}, "note": "banished"}, "rounds": 10},
    "charm person": {"conds": ["Charmed"], "rounds": 600, "ends_on": ["damage"]},        # harming it ends the charm
    "charm monster": {"conds": ["Charmed"], "rounds": 600, "ends_on": ["damage"]},
    "animal friendship": {"ends_on": ["damage"]},
    "mass suggestion": {"ends_on": ["damage"]}, "incite greed": {"ends_on": ["damage"]},
    "watery sphere": {"kind": "zone", "area": {"shape": "sphere", "size": 5, "origin": "point"},        # engulfed; rolls along 30 ft an action
                      "zone": {"on_cast": True, "save": "str", "conds": ["Restrained"], "parts": [], "repeat": "end",
                               "move": {"cost": "action", "feet": 30, "carry": True}}},
    "sunburst": {"rounds": 10, "dis_types": ["undead", "ooze"]},       # blinded for 1 minute (saves at the end of each turn)
    "shatter": {"dis_types": ["construct"]},                           # made of stone, crystal or metal: disadvantage
    "blight": {"dis_types": ["plant"]}, "abi-dalzim's horrid wilting": {"dis_types": ["plant"]},
    "phantasmal force": {"area": None, "target": {"type": "creature", "count": 1}, "parts": [], "repeat": "end", "rounds": 10,
                         "effect": {"mods": {"phantasm": True}, "note": "haunted by a phantasm (1d6 psychic each turn)"},
                         "dot": {"dice": "1d6", "type": "psychic", "when": "start"}},
    "modify memory": {"ends_on": ["damage"]},
    "dominate person": {"kind": "save", "save": "wis", "conds": ["Charmed"], "rounds": 10, "repeat": "damage",      # a new save each time it's hurt
                        "effect": {"mods": {"dominated": True}, "note": "dominated: fights for the caster"}},
    "dominate monster": {"kind": "save", "save": "wis", "conds": ["Charmed"], "rounds": 600, "repeat": "damage",
                         "effect": {"mods": {"dominated": True}, "note": "dominated: fights for the caster"}},
    "dominate beast": {"kind": "save", "save": "wis", "conds": ["Charmed"], "rounds": 10, "repeat": "damage",
                       "effect": {"mods": {"dominated": True}, "note": "dominated: fights for the caster"}},
    "time stop": {"kind": "time_stop", "target": {"type": "self"}},
    "hex": {"action": {"name": "Move Hex", "cost": "bonus", "move_mark": True}},
    "hunter's mark": {"action": {"name": "Move Hunter's Mark", "cost": "bonus", "move_mark": True}},
    "dissonant whispers": {"push": 30,                                  # it flees with its reaction: that's spent until its next turn
                           "effect": {"mods": {"no_reactions": True}, "until": "target_start", "note": "fleeing (its reaction is spent)"}},
    "counterspell": {"kind": "reaction_only"},
    "absorb elements": {"kind": "reaction_only"}, "shield": {"kind": "buff_reaction"}, "hellish rebuke": {"kind": "reaction_only_or_target"},
    "silvery barbs": {"kind": "reaction_only"}, "feather fall": {"kind": "buff", "effect": {"mods": {}, "note": "falls gently"}, "rounds": 10},
    "conjure barrage": {"kind": "save", "save": "dex", "half": True, "area": {"shape": "cone", "size": 60, "origin": "caster"}, "parts": [["3d8", "piercing"]]},
    "conjure volley": {"kind": "save", "save": "dex", "half": True, "area": {"shape": "cylinder", "size": 40, "origin": "point"}, "parts": [["8d8", "piercing"]]},
    "antimagic field": {"kind": "zone", "area": {"shape": "emanation", "size": 10, "origin": "caster"}, "target": {"type": "self"}, "zone": {"follow": True, "antimagic": True}},
    "globe of invulnerability": {"kind": "zone", "area": {"shape": "emanation", "size": 10, "origin": "caster"}, "target": {"type": "self"},
                                 "zone": {"follow": True, "globe": 5}},
    "antilife shell": {"kind": "zone", "area": {"shape": "emanation", "size": 10, "origin": "caster"}, "target": {"type": "self"}, "zone": {"follow": True, "repel": True}},
    "light": {"kind": "zone", "area": {"shape": "sphere", "size": 20, "origin": "point"}, "target": {"type": "creature", "count": 1}, "zone": {"light": "bright", "follow_target": True}},
    "daylight": {"kind": "zone", "area": {"shape": "sphere", "size": 60, "origin": "point"}, "zone": {"light": "bright", "dispel_dark": True}},
    "dancing lights": {"kind": "zone", "area": {"shape": "sphere", "size": 10, "origin": "point"}, "zone": {"light": "dim"}},
    "continual flame": {"kind": "zone", "area": {"shape": "sphere", "size": 20, "origin": "point"}, "zone": {"light": "bright"}},
    "minor illusion": {"kind": "zone", "area": {"shape": "square", "size": 5, "origin": "point"}, "zone": {"illusion": True, "opaque": True}},
    "silent image": {"kind": "zone", "area": {"shape": "square", "size": 15, "origin": "point"}, "zone": {"illusion": True, "opaque": True}},
    "major image": {"kind": "zone", "area": {"shape": "square", "size": 20, "origin": "point"}, "zone": {"illusion": True, "opaque": True}},
    "plant growth": {"kind": "zone", "area": {"shape": "sphere", "size": 100, "origin": "point"}, "zone": {"difficult": True, "quarter": True}},
    "mold earth": {"kind": "zone", "area": {"shape": "square", "size": 5, "origin": "point"}, "zone": {"difficult": True}},
    "pass without trace": {"kind": "buff", "target": {"type": "self"}, "effect": {"mods": {"stealth": 10}, "note": "+10 to Stealth (allies within 30 ft)"}, "rounds": 600},
    "mislead": {"kind": "buff", "target": {"type": "self"}, "conds_on": ["Invisible"], "effect": {"mods": {}, "note": "invisible, with an illusory double"}, "rounds": 600},
    "etherealness": {"kind": "buff", "target": {"type": "self"}, "effect": {"mods": {"untargetable": True}, "note": "on the Ethereal Plane"}, "rounds": 4800},
    "project image": {"kind": "summon_image"},
    "animal shapes": {"kind": "utility"}, "mass polymorph": {"kind": "save", "save": "wis", "conds": [], "transform": True, "parts": [],
                                                              "target": {"type": "creature", "count": 10}},
    "shapechange": {"kind": "self_transform"},
    "gate": {"kind": "utility"}, "maze": {"kind": "save", "save": "int", "parts": [], "effect": {"mods": {"banished": True, "untargetable": True, "way_out": ["int", 20]},
                                                                                 "note": "lost in a maze"},
                                          "conds": ["Incapacitated"], "rounds": 100, "auto_hit": True},
    # ---- self-buffs whose damage dice are for later hits, not for the caster (the text reader took them as damage)
    "spirit shroud": {"kind": "buff", "target": {"type": "self"}, "choose_type": ["radiant", "necrotic", "cold"],
                      "effect": {"mods": {"dmg": ("1d8", "$type"), "any_attack": True, "rider": {"plain_mods": {"no_heal": True}}, "slow_aura": 10},
                                 "note": "+1d8 on hits within 10 ft; creatures it hits can't regain hit points until your next turn; foes starting a turn within 10 ft lose 10 ft of speed"}, "rounds": 10, "up": "1d8", "up_every": 2},
    "shadow blade": {"kind": "buff", "target": {"type": "self"}, "effect": {"mods": {}, "note": "a blade of shadow in hand"}, "rounds": 10, "up": "1d8", "up_every": 2, "up_offset": 1,
                     "action": {"name": "Shadow Blade", "cost": "action", "atk": "melee", "parts": [["2d8+MOD", "psychic"]], "range": 5}},
    "shadow of moil": {"kind": "buff", "target": {"type": "self"},
                       "effect": {"mods": {"resist": ["radiant"], "attacks_against": "dis", "retaliate": ("2d8", "necrotic")},
                                  "note": "wreathed in shadow; attackers within 10 ft take 2d8 necrotic"}, "rounds": 10},
    "zephyr strike": {"kind": "buff", "target": {"type": "self"},
                      "effect": {"mods": {"no_opportunity": True, "attacks_with": "adv", "dmg": ("1d8", "force"), "speed": 30, "once": True},
                                 "note": "no opportunity attacks; the next weapon attack has advantage and +1d8 force"}, "rounds": 10},
    "guardian of nature": {"kind": "buff", "target": {"type": "self"}, "choose_type": ["primal beast", "great tree"],
                           "effect": {"mods": {"dmg": ("1d6", "force"), "speed": 10, "senses": {"darkvision": 120}},
                                      "note": "Primal Beast: +1d6 force on weapon hits, +10 ft speed"},
                           "options": {"great tree": {"temp": "10", "mods": {"save_adv": ["con"]}, "note": "Great Tree: 10 temporary HP, advantage on Constitution saves"}},
                           "rounds": 10},
    "enhance ability": {"kind": "buff", "rounds": 600,
                        "choose_type": ["bear's endurance", "bull's strength", "cat's grace", "eagle's splendor", "fox's cunning", "owl's wisdom"],
                        "effect": {"mods": {"check_adv": ["con"]}, "temp": "2d6", "note": "Bear's Endurance: advantage on Constitution checks, 2d6 temporary hit points"},
                        "options": {"bull's strength": {"mods": {"check_adv": ["str"]}, "note": "Bull's Strength: advantage on Strength checks"},
                                    "cat's grace": {"mods": {"check_adv": ["dex"]}, "note": "Cat's Grace: advantage on Dexterity checks"},
                                    "eagle's splendor": {"mods": {"check_adv": ["cha"]}, "note": "Eagle's Splendor: advantage on Charisma checks"},
                                    "fox's cunning": {"mods": {"check_adv": ["int"]}, "note": "Fox's Cunning: advantage on Intelligence checks"},
                                    "owl's wisdom": {"mods": {"check_adv": ["wis"]}, "note": "Owl's Wisdom: advantage on Wisdom checks"}}},
    "tenser's transformation": {"kind": "buff", "target": {"type": "self"}, "temp": "50",
                                "effect": {"mods": {"attacks_with": "adv", "dmg": ("2d12", "force"), "save_adv": ["str", "con"], "no_spells": True,
                                                    "two_attacks": True,
                                                    "temp_ends": True},
                                           "note": "advantage on weapon attacks, +2d12 force on weapon hits, no spellcasting"}, "rounds": 100},
    "alter self": {"kind": "self_transform"}, "wish": {"kind": "utility"},
    # ---- conjured flames: one attack, then an attack on later turns (not everything in the light they shed)
    "produce flame": {"kind": "attack", "atk_type": "ranged", "area": None, "range": 30, "target": {"type": "creature", "count": 1}},
    "flame blade": {"kind": "buff", "area": None, "target": {"type": "self"}, "effect": {"mods": {}, "note": "a fiery blade in hand"}, "rounds": 100,
                    "up": "1d6", "up_every": 2,
                    "action": {"name": "Flame Blade", "cost": "action", "atk": "melee", "parts": [["3d6", "fire"]], "range": 5}},
    "investiture of stone": {"kind": "buff", "area": None, "target": {"type": "self"}, "rounds": 100,
                             "effect": {"mods": {"resist": ["nonmagical"]}, "note": "resists nonmagical weapon damage"},
                             "action": {"name": "Investiture of Stone: quake", "cost": "action", "area": {"shape": "emanation", "size": 15, "origin": "caster"},
                                        "save": "dex", "parts": [], "prone": True}},
    "investiture of wind": {"kind": "buff", "area": None, "target": {"type": "self"}, "rounds": 100,
                            "effect": {"mods": {"ranged_against": "dis", "fly": 60}, "note": "ranged attacks against you have disadvantage, flying speed 60 ft"},
                            "action": {"name": "Investiture of Wind: whirlwind", "cost": "action", "area": {"shape": "cube", "size": 15, "origin": "point"},
                                       "save": "con", "half": True, "parts": [["2d10", "bludgeoning"]], "push": 10, "range": 60}},
    "holy aura": {"kind": "buff", "area": None, "target": {"type": "self"},
                  "effect": {"mods": {"save_adv": ["str", "dex", "con", "int", "wis", "cha"], "attacks_against": "dis", "aura_ft": 30, "holy_blind": True},
                             "note": "advantage on saves, attacks against it have disadvantage (and allies within 30 ft)"}},
    "compulsion": {"kind": "save", "save": "wis", "conds": [], "repeat": "end", "rounds": 10, "target": {"type": "creature", "count": 99},
                   "effect": {"mods": {"compelled": True}, "note": "compelled: moves where the caster directs on its turn"}},
    "disintegrate": {"dust": True},
    "teleport": {"kind": "utility"},                                   # travel, not a battle effect
    "prismatic spray": {"kind": "prismatic"},
    "raulothim's psychic lance": {"effect": {"mods": {}, "until": "caster_start"}},          # incapacitated until your next turn
    "pyrotechnics": {"effect": {"mods": {}, "until": "caster_end_next"}, "area": {"shape": "sphere", "size": 10, "origin": "point"}},   # within 10 ft of the fire
    "sunbeam": {"rounds": 0, "effect": {"mods": {}, "until": "caster_start"}, "dis_types": ["undead", "ooze"],   # blinded until your next turn
                "action": {"name": "Sunbeam: new line", "cost": "action", "area": {"shape": "line", "size": 60, "width": 5, "origin": "caster"},
                           "save": "con", "half": True, "parts": [["6d8", "radiant"]], "conds": ["Blinded"]}},
    "rime's binding ice": {"effect": {"mods": {"speed_set": 0}, "note": "encased in ice: speed 0"}, "rounds": 10},
    "wrath of nature": {"kind": "zone", "area": {"shape": "cube", "size": 60, "origin": "point"}, "choose_type": [],   # the trees lash your enemies, every turn
                        "zone": {"on_cast": True, "caster_turn": True, "affects": "enemies", "save": "dex", "parts": [["4d6", "slashing"]],
                                 "difficult": "affected"},
                        "action": {"name": "Wrath of Nature: hurl a rock", "cost": "bonus", "atk": "ranged", "parts": [["3d8", "bludgeoning"]],
                                   "range": 120}},
    "nathair's mischief": {"kind": "surge"},
    "immolation": {"area": None, "target": {"type": "creature", "count": 1}, "parts": [["8d6", "fire"]], "half": True,
                   "dot": {"dice": "4d6", "type": "fire", "when": "end", "save": "dex"}},
    "life transference": {"kind": "life_transference", "target": {"type": "creature", "count": 1, "allies": True}},
    "flame arrows": {"kind": "buff", "target": {"type": "creature", "count": 1, "allies": True}, "range": 5, "area": None,     # a touched quiver
                     "effect": {"mods": {"dmg": ("1d6", "fire"), "ranged_only": True}, "note": "+1d6 fire on ranged weapon hits"}, "rounds": 600},
    "mental prison": {"parts": [["5d10", "psychic"]], "half": False, "full": True, "conds": ["Restrained"]},     # 5d10 on a success too
    "feeblemind": {"full": True, "rounds": None,                       # 4d6 whether or not it saves
                   "effect": {"mods": {"no_spells": True, "check_dis": ["int", "cha"]}, "note": "feebleminded: Intelligence and Charisma 1, no spells"}},
    "investiture of ice": {"kind": "buff", "area": None, "target": {"type": "self"},
                           "effect": {"mods": {"immune": ["cold"], "resist": ["fire"]}, "note": "immune to cold, resists fire"}, "rounds": 100,
                           "ground": {"size": 10},          # the icy ground around the caster, difficult terrain for everyone else (follows it)
                           "action": {"name": "Cone of cold wind", "cost": "action", "area": {"shape": "cone", "size": 15, "origin": "caster"},
                                      "save": "con", "half": True, "parts": [["4d6", "cold"]],
                                      "fail_mods": {"speed_mult": 0.5}, "until": "caster_start", "note": "speed halved"}},
    "animate objects": {"kind": "summon"}, "tiny servant": {"kind": "summon"},
    "mordenkainen's faithful hound": {"kind": "token", "target": {"type": "point"}}, "unseen servant": {"kind": "token", "target": {"type": "point"}},
    "magic jar": {"kind": "utility"}, "soul cage": {"kind": "utility"}, "feign death": {"kind": "buff", "conds_on": ["Unconscious"], "effect": {"mods": {"resist": "ALL_BUT_PSYCHIC"}, "note": "looks dead"}, "rounds": 600},
    # ---- what a failed save or a hit does beyond the dice (the text reader sees neither)
    "arms of hadar": {"effect": {"mods": {"no_reactions": True}, "until": "target_start", "note": "unable to take reactions until its next turn"}},
    "tasha's mind whip": {"effect": {"mods": {"no_reactions": True, "one_action": True}, "until": "target_end_next",
                                     "note": "unable to take reactions; an action or a bonus action next turn"}},
    "synaptic static": {"repeat": "end", "rounds": 10,
                        "effect": {"mods": {"attack": "-1d6", "check": "-1d6"}, "note": "muddled: -1d6 to attack rolls and ability checks"}},
    "elemental bane": {"parts": [], "choose_type": ["acid", "cold", "fire", "lightning", "thunder"], "rounds": 10,
                       "effect": {"mods": {"elemental_bane": ("2d6", "$type")}, "note": "baned: no resistance to the type, +2d6 the first time each turn it takes it"}},
    "ray of enfeeblement": {"on_hit": {"mods": {"enfeebled": True}, "repeat_ab": "con", "note": "half damage with Strength weapon attacks"}},
    "vitriolic sphere": {"parts": [["10d4", "acid"]], "half": True, "up": "2d4", "dot": {"dice": "5d4", "type": "acid", "when": "end", "times": 1}},
    "weird": {"parts": [], "conds": ["Frightened"], "repeat": None, "rounds": 10, "dot": {"dice": "4d10", "type": "psychic", "when": "end", "save": "wis"}},
    "chaos bolt": {"parts": [["2d8", "$type"], ["1d6", "$type"]], "up": "1d6", "leap": True,
                   "choose_type": ["acid", "cold", "fire", "force", "lightning", "poison", "psychic", "thunder"]},      # (rolled on a d8 at the table)
    "tidal wave": {"area": {"shape": "cube", "size": 15, "origin": "point"}},           # a wave up to 30 ft long and 10 ft wide
    "illusory dragon": {"parts": [], "conds": ["Frightened"], "rounds": 10, "foes_only": True,
                        "choose_type": ["acid", "cold", "fire", "lightning", "necrotic", "poison"],
                        "action": {"name": "Illusory Dragon: breath", "cost": "bonus", "area": {"shape": "cone", "size": 60, "origin": "caster"},
                                   "save": "int", "half": True, "parts": [["7d6", "$type"]]}},
    "erupting earth": {"leave_zone": {"difficult": True}},            # churned ground until cleared by hand
    "plane shift": {"kind": "attack", "atk_type": "melee", "range": 5, "target": {"type": "creature", "count": 1}, "plane_shift": True, "parts": []},     # the hostile use
    "control water": {"parts": [["2d8", "bludgeoning"]]},             # the whirlpool, once
    "gravity fissure": {"parts": [["8d8", "force"]], "up": "1d8", "fissure": True},     # and those within 10 ft of the line are pulled to it
    "storm of vengeance": {"parts": [["2d6", "thunder"]], "half": False, "conds": ["Deafened"], "rounds": 50, "storm": True, "target": {"type": "point"},
                           "area": {"shape": "sphere", "size": 360, "origin": "point"}},      # the first round: thunder for all under the cloud
    "jim's magic missile": {"kind": "attack", "parts": [["2d4", "force"]], "target": {"type": "split", "count": 3, "per_level": 1},
                            "crit": 20, "crit_bonus": [["1d4", "force"]]},       # a crit: 5d4 for that missile
    "prismatic wall": {"kind": "zone", "area": {"shape": "line", "size": 90, "width": 5, "origin": "point"}, "target": {"type": "point"},
                       "zone": {"enter": True, "opaque": True, "light": "bright", "save": "dex", "half": True,
                                "parts": [["10d6", "fire"], ["10d6", "acid"], ["10d6", "lightning"], ["10d6", "poison"], ["10d6", "cold"]]}},
    "maddening darkness": {"kind": "zone", "area": {"shape": "sphere", "size": 60, "origin": "point"},
                           "zone": {"darkness": True, "start": True, "save": "wis", "half": True, "parts": [["8d8", "psychic"]]}},
    "earthquake": {"kind": "zone", "area": {"shape": "sphere", "size": 100, "origin": "point"},
                   "zone": {"on_cast": True, "end": True, "save": "dex", "prone": True, "parts": [], "difficult": True, "conc_save": "con"}},
    "whirlwind": {"kind": "zone", "area": {"shape": "sphere", "size": 10, "origin": "point"},     # caught creatures are held; moved as an action
                  "zone": {"on_cast": True, "enter": True, "save": "dex", "half": True, "parts": [["10d6", "bludgeoning"]], "conds": ["Restrained"],
                           "escape": "str", "move": {"cost": "action", "feet": 30, "carry": True}}},
    "ravenous void": {"kind": "zone", "area": {"shape": "sphere", "size": 20, "origin": "point"},     # (the Strength save stands in for its pull)
                      "zone": {"on_cast": True, "enter": True, "start": True, "save": "str", "parts": [["5d10", "force"]], "conds": ["Restrained"],
                               "escape": "str", "difficult": True, "pull_to": 100}},
    "dark star": {"kind": "zone", "area": {"shape": "sphere", "size": 40, "origin": "point"},
                  "zone": {"darkness": True, "silence": True, "difficult": True, "enter": True, "start": True, "save": "con", "half": True,
                           "parts": [["8d10", "force"]]}},
    "magic weapon": {"kind": "buff", "effect": {"mods": {"weapon_attack": "1", "dmg": ("1", "")}, "note": "a magic weapon: bonus to attack and damage rolls"},
                     "slot_mods": {4: {"weapon_attack": "2", "dmg": ("2", "")}, 6: {"weapon_attack": "3", "dmg": ("3", "")}}},
    "elemental weapon": {"kind": "buff", "choose_type": ["acid", "cold", "fire", "lightning", "thunder"],
                         "effect": {"mods": {"weapon_attack": "1", "dmg": ("1d4", "$type")}, "note": "a magic weapon: bonus to attack, extra damage of the chosen type"},
                         "slot_mods": {5: {"weapon_attack": "2", "dmg": ("2d4", "$type")}, 7: {"weapon_attack": "3", "dmg": ("3d4", "$type")}}},
    "levitate": {"kind": "save", "save": "con", "parts": [], "conds": [], "rounds": 100,       # a foe hung in the air: out of the fight on foot
                 "effect": {"mods": {"speed_set": 0}, "note": "levitating: can only drift up and down"}},
    "kinetic jaunt": {"kind": "buff", "target": {"type": "self"}, "rounds": 10,
                      "effect": {"mods": {"speed": 10, "no_opportunity": True}, "note": "+10 ft speed, no opportunity attacks"}},
    "magnify gravity": {"effect": {"mods": {"speed_mult": .5}, "until": "target_end_next", "note": "speed halved"}},
    "spray of cards": {"effect": {"mods": {}, "until": "target_end_next"}},            # blinded until the end of its next turn
    "enlarge/reduce": {"target": {"type": "creature", "count": 1, "allies": False},          # a friend grows, a foe (Con save) shrinks
                       "reduce": {"mods": {"dmg_minus": "1d4", "save_dis": ["str"], "check_dis": ["str"], "size_step": -1},
                                  "note": "reduced: -1d4 weapon damage, disadvantage on Strength checks and saves"}},
    "confusion": {"grow": 5, "effect": {"mods": {"confused": True, "no_reactions": True}, "note": "confused: a d10 each turn decides what it does"}},
    "gravity sinkhole": {"sink": True},
    "temporal shunt": {"kind": "reaction_only"},
    "infestation": {"jostle": 5},
    "negative energy flood": {"undead_temp": "5d12"},                                    # the mites drive it 5 ft in a random direction                     # offered when a foe attacks or casts (reactions.py)
    "tether essence": {"kind": "save", "save": "con", "parts": [], "conds": [], "target": {"type": "creature", "count": 2, "near": None},
                       "rounds": 600, "tether": True, "effect": {"mods": {}, "note": "tethered"}},      # both fail: what hurts one hurts the other
    "time ravage": {"rounds": None, "effect": {"mods": {"attacks_with": "dis", "check_dis": True, "save_dis": ["all"], "speed_mult": .5},
                                               "note": "aged: disadvantage on attacks, checks and saves, half speed"}},
    "antagonize": {"antagonize": True, "effect": {"mods": {"no_reactions": True}, "until": "target_start",   # it spends its reaction lashing at an ally
                              "note": "antagonized: its reaction goes on an attack you pick"}},
    "calm emotions": {"calm": True, "ends_on": ["damage"],                # a foe that fails turns indifferent (charmed) until it's hurt
                      "effect": {"mods": {}, "note": "indifferent"}},
    "fire storm": {"area": {"shape": "cube", "size": 30, "origin": "point"}},     # up to ten 10-foot cubes: about a 30-foot block                                # pulled towards the centre on a failure
    "meteor swarm": {"spheres": 4},                                                    # four 40-ft spheres; a creature in several is hit once
    "pulse wave": {"push": 15, "parts": [["6d6", "force"]], "up": "1d6"},
    "catapult": {"parts": [["3d8", "bludgeoning"]], "up": "1d8"},
    "wither and bloom": {"parts": [["2d6", "necrotic"]], "up": "1d6", "foes_only": True, "bloom": True},       # creatures of your choice
    "delayed blast fireball": {"kind": "zone", "area": {"shape": "sphere", "size": 20, "origin": "point"},       # the bead: +1d6 at the end of each of
                               "zone": {"bead": True, "parts": [["12d6", "fire"]], "up": "1d6"}},          # the caster's turns; it erupts when concentration ends
    "reality break": {"parts": [], "conds": [], "repeat": "end", "rounds": 10, "dot": {"dice": "8d12", "type": "force", "when": "start"},   # the d10 table, averaged
                      "effect": {"mods": {"no_reactions": True}, "note": "torn between realities: no reactions, hurt at the start of each turn"}},
    "draconic transformation": {"self_effect": {"mods": {"fly": 60, "senses": {"blindsight": 30}}, "note": "draconic: blindsight, flying speed 60 ft"},
                                "action": {"name": "Draconic Transformation: breath", "cost": "bonus", "area": {"shape": "cone", "size": 60, "origin": "caster"},
                                           "save": "dex", "half": True, "parts": [["6d8", "force"]]}},
    # ---- Arcana Unleashed (AU), Forgotten Realms: Heroes of Faerun (FRHoF), Eberron: Forge of the Artificer (EFA): their text is the 2024 wording
    #      ("Magic action", "Emanation", "D20 Tests"); each is written out here
    "spellfire flare": {"kind": "attack", "target": {"type": "split", "count": 1, "per_level": 1}, "ignore_cover": True},     # one more blast per slot level
    "wardaway": {"kind": "save", "save": "con", "parts": [["2d4", "force"]], "up": "2d4", "half": True, "conds": [], "auto_pass_types": ["construct", "undead"],
                 "effect": {"mods": {"speed_mult": .5, "one_action": True}, "until": "caster_start",
                            "note": "speed halved; on its next turn only an action or a bonus action"}},
    "death armor": {"kind": "buff", "target": {"type": "creature", "count": 1, "allies": True}, "range": 5, "area": None, "rounds": 600,
                    "effect": {"mods": {"dsave_adv": True, "retaliate": ("2d4", "necrotic"), "retaliate_once": True},
                               "note": "advantage on death saves; the first creature to hit it in melee each turn takes 2d4 necrotic"}},
    "disruptive tune": {"kind": "save", "save": "con", "parts": [], "conds": [], "drop_conc": True, "repeat": None, "rounds": 10,
                        "effect": {"mods": {"conc_dis": True}, "note": "disadvantage on Constitution saves to keep concentration"}},
    "dueling ground": {"kind": "zone", "area": {"shape": "sphere", "size": 15, "origin": "point"}, "target": {"type": "point"},
                       "zone": {"duel_ground": True}},          # two duellists: a fall to 0 is stable and out of the ring; an outsider stepping in ends it
    "elminster's elusion": {"kind": "buff", "target": {"type": "self"}, "area": None,
                            "effect": {"mods": {"save_adv": ["spells"], "half_none": ["str", "dex", "con", "int", "wis", "cha"]},
                                       "note": "advantage on saves against spells and magical effects; a saved half-damage effect does none"}},
    "uncertain footing": {"kind": "save", "save": "int", "parts": [], "conds": [], "repeat": "end", "rounds": 10,
                          "effect": {"mods": {"speed_mult": .5, "no_dash": True}, "note": "illusory obstacles: speed halved, can't Dash"}},
    "cacophonic shield": {"kind": "zone", "area": {"shape": "emanation", "size": 10, "origin": "caster"}, "target": {"type": "self"}, "choose_type": [],
                          "zone": {"follow": True, "sweep": True, "enter": True, "end": True, "on_cast": True, "affects": "enemies", "save": "con", "half": True,
                                   "parts": [["3d6", "thunder"]], "up": "1d6", "conds": ["Deafened"], "cond_rounds": 1},
                          "self_effect": {"mods": {"resist": ["thunder"], "ranged_against": "dis"}, "note": "resists thunder; ranged attacks against it have disadvantage"}},
    "conjure constructs": {"kind": "save", "save": "dex", "parts": [["3d6", "force"]], "up": "1d6", "half": True, "conds": [], "area": None,
                           "target": {"type": "creature", "count": 1}, "choose_type": ["clockwork force", "orderly ward"], "ward_option": True,
                           "action": {"name": "Conjure Constructs: Clockwork Force", "cost": "action", "save": "dex", "half": True, "parts": [["3d6", "force"]], "up": "1d6"},
                           "more_actions": [{"name": "Conjure Constructs: Orderly Ward", "cost": "action", "temp": "1d6+MOD", "up": "1d6"}]},
    "inflict doubt": {"kind": "save", "save": "wis", "parts": [], "conds": [], "repeat": "end", "rounds": 10,
                      "effect": {"mods": {"attacks_with": "dis", "check_dis": True, "save_dis": ["all"]}, "note": "doubts itself: disadvantage on D20 Tests"}},
    "laeral's silver lance": {"kind": "save", "save": "str", "parts": [["3d10", "force"]], "up": "1d10", "half": True, "conds": [], "prone": True, "foes_only": True},
    "syluné's viper": {"kind": "buff", "target": {"type": "self"}, "area": None, "temp": "15", "temp_per_level": 5, "rounds": 600,
                           "effect": {"mods": {"climb": True, "temp_gone": True, "ends_actions": "Syluné's Viper"},
                                      "note": "15 temporary hit points (the spell ends without them), a climb speed; Venomous Bite as a Magic action"},
                           "action": {"name": "Venomous Bite", "cost": "action", "atk": "ranged", "parts": [["1d6", "force"]], "up": "1d6", "range": 50,
                                      "on_hit": {"conds": ["Poisoned", "Incapacitated"], "until": "caster_start", "note": "poisoned (and so incapacitated) until your next turn"}}},
    "backlash": {"kind": "reaction_only"},                  # reactions.py: the damage is cut by 4d6 + the modifier, the attacker saves or takes 4d6 force
    "distorted distance": {"kind": "zone", "area": {"shape": "sphere", "size": 60, "origin": "point"}, "target": {"type": "point"},
                           "zone": {"on_cast": True, "enter": True, "end": True, "affects": "enemies", "save": "int", "parts": [["2d10", "psychic"]],
                                    "fail_mods": {"speed_mult": .5}, "fail_until": "target_end_next", "ally_boost": 20}},        # Dizzying Elongation / Shortened Space
    "doomtide": {"kind": "zone", "area": {"shape": "sphere", "size": 20, "origin": "point"}, "target": {"type": "point"},
                 "zone": {"on_cast": True, "enter": True, "end": True, "darkness": True, "drift": 10, "save": "wis", "half": True, "parts": [["5d6", "psychic"]],
                          "fail_mods": {"save": "-1d6"}, "fail_until": "target_end_next"}},
    "festering blast": {"kind": "save", "save": "con", "parts": [["4d10", "necrotic"]], "up": "1d10", "half": False, "conds": ["Poisoned"], "repeat": "end",
                        "rounds": 10, "dot": {"dice": "2d10", "type": "poison", "when": "start"}},
    "spellfire storm": {"kind": "zone", "area": {"shape": "cylinder", "size": 20, "origin": "point"}, "target": {"type": "point"},
                        "zone": {"on_cast": True, "enter": True, "end": True, "affects": "enemies", "save": "con", "half": True, "parts": [["4d10", "radiant"]],
                                 "up": "1d10", "light": "bright", "spell_save": "con"}},
    "alustriel's mooncloak": {"kind": "buff", "target": {"type": "self"}, "area": None, "rounds": 10,
                              "effect": {"mods": {"resist": ["cold", "lightning", "radiant"], "half_cover": True, "aura_ft": 20},
                                         "note": "half cover and resistance to cold, lightning and radiant for it and its allies within 20 ft"},
                              "action": {"name": "Mooncloak: Respite", "cost": "action", "heal": "4d10+MOD", "range": 20, "ends_spell": True}},
    "grave ground": {"kind": "zone", "area": {"shape": "square", "size": 20, "origin": "point"}, "target": {"type": "point"},
                     "zone": {"on_cast": True, "enter": True, "end": True, "affects": "enemies", "save": "str", "parts": [["6d6", "necrotic"]], "up": "1d6",
                              "difficult": "affected", "fail_mods": {"dmg_minus": "1d6"}, "fail_until": "target_end_next"}},
    "mordenkainen's lucubration": {"kind": "slots_back", "target": {"type": "self"}},
    "songal's elemental suffusion": {"kind": "zone", "area": {"shape": "emanation", "size": 15, "origin": "caster"}, "target": {"type": "self"},
                                     "choose_type": ["acid", "cold", "fire", "lightning", "thunder"],
                                     "zone": {"follow": True, "on_cast": True, "caster_turn": True, "affects": "enemies", "save": "dex", "half": True,
                                              "parts": [["2d6", "$type"]], "prone": True},
                                     "self_effect": {"mods": {"resist": ["$type"], "fly": 30}, "note": "resists the chosen element, flying speed 30 ft"}},
    "spirit lantern": {"kind": "buff", "target": {"type": "self"}, "area": None, "rounds": 100,
                       "effect": {"mods": {"lantern": {"frags": 0, "max": 0, "ft": 60}}, "note": "a ghostly lantern: enemies dying within 60 ft leave soul fragments"},
                       "action": {"name": "Spirit Lantern: Drain Life", "cost": "bonus", "save": "con", "half": True, "parts": [["4d8+MOD", "necrotic"]], "range": 60, "frag": True},
                       "more_actions": [{"name": "Spirit Lantern: Repair Undead", "cost": "bonus", "heal": "4d8+MOD", "range": 60, "frag": True, "undead_only": True},
                                        {"name": "Spirit Lantern: Ward Ally", "cost": "bonus", "ward": True, "range": 60, "frag": True}]},
    "waves of exhaustion": {"kind": "buff", "target": {"type": "self"}, "area": None, "rounds": 10,
                            "effect": {"mods": {}, "note": "a nimbus of gray light: a Magic action sends out a wave of exhaustion"},
                            "action": {"name": "Waves of Exhaustion: wave", "cost": "action", "area": {"shape": "cone", "size": 60, "origin": "caster"},
                                       "save": "con", "parts": [], "exhaust": 1, "exhaust_cap": 4}},
    "dirge": {"kind": "zone", "area": {"shape": "emanation", "size": 60, "origin": "caster"}, "target": {"type": "self"},
              "zone": {"follow": True, "sweep": True, "enter": True, "end": True, "on_cast": True, "affects": "enemies", "save": "con", "half": True,
                       "parts": [["3d10", "necrotic"]], "prone": True, "exhaustion": True, "no_heal": True,
                       "on_save": {"rounds": 1, "mods": {"speed_mult": .5}}}},
    "elminster's effulgent spheres": {"kind": "buff", "target": {"type": "self"}, "area": None, "rounds": 600, "ends_when_spent": True,
                                      "choose_type": ["acid", "cold", "fire", "lightning", "thunder"],
                                      "effect": {"mods": {"ends_actions": "Elminster's Effulgent Spheres"}, "note": "six chromatic spheres orbit it (one more per slot level above 6th)"},
                                      "action": {"name": "Effulgent Spheres: Energy Blast", "cost": "bonus", "atk": "ranged", "parts": [["3d6", "$type"]], "range": 120,
                                                 "uses": 6, "uses_up": 1}},
    "aura of evasion": {"kind": "buff", "target": {"type": "self"}, "area": None, "rounds": 10,
                        "effect": {"mods": {"save_adv": ["dex"], "evasion": True, "aura_ft": 30, "aura_active": True},
                                   "note": "it and its allies within 30 ft: advantage on Dexterity saves, none or half damage (not while incapacitated)"}},
    "fractured awareness": {"kind": "save", "save": "int", "parts": [["12d10", "psychic"]], "half": True, "conds": [], "repeat": "end", "rounds": 10, "ends_on_ok": True,
                            "effect": {"mods": {"attacks_with": "dis", "check_dis": True, "save_dis": ["all"]}, "note": "conflicting futures: disadvantage on D20 Tests"}},
    "reweave fate": {"kind": "reaction_only"},              # reactions.py: a failed D20 Test is rerolled with advantage; a success gives 6d10 temporary HP
    "simbul's synostodweomer": {"kind": "buff", "target": {"type": "creature", "count": 1, "allies": True}, "range": 5, "area": None, "rounds": 600,
                                "effect": {"mods": {"synosto": "MOD"}, "note": "casting a spell with a slot lets it spend Hit Dice to heal"}},
    "transfix": {"kind": "save", "save": "cha", "parts": [], "conds": ["Charmed", "Incapacitated"], "repeat": None, "rounds": 10, "range": 60,
                 "target": {"type": "creature", "count": 1}, "area": None,
                 "effect": {"mods": {"transfixed": True}, "note": "transfixed: walks to the caster, hurt (4d8 psychic) if it ends its turn within 5 ft"},
                 "dot": {"dice": "4d8", "type": "psychic", "when": "end", "near": 5, "up": "1d8"},
                 "action": {"name": "Transfix: another creature", "cost": "action", "save": "cha", "conds": ["Charmed", "Incapacitated"], "range": 60, "parts": [],
                            "mods": {"transfixed": True}, "note": "transfixed", "dot": {"dice": "4d8", "type": "psychic", "when": "end", "near": 5, "up": "1d8"}}},
    "entrancing mirrors": {"kind": "save", "save": "int", "parts": [["7d6", "psychic"]], "half": True, "conds": ["Stunned"], "repeat": "end", "rounds": 10,
                           "effect": {"mods": {"speed_mult": .5}, "note": "dazzled by mirrors: stunned, speed halved"}},
    "holy star of mystra": {"kind": "buff", "target": {"type": "self"}, "area": None, "rounds": 10, "choose_type": ["force", "radiant"],
                            "effect": {"mods": {"cover34": True, "deflect_spell": True}, "note": "three-quarters cover; a saved single-target spell (level 7 or lower) can be deflected back"},
                            "action": {"name": "Holy Star: bolt", "cost": "bonus", "atk": "ranged", "parts": [["4d10+MOD", "$type"]], "range": 120},
                            "more_actions": [{"name": "Holy Star: bolt (as it is cast)", "cost": "free", "atk": "ranged", "parts": [["4d10+MOD", "$type"]], "range": 120,
                                              "uses": 1, "rounds": 1}]},
    "iron body": {"kind": "buff", "target": {"type": "creature", "count": 1, "allies": True}, "range": 5, "area": None, "rounds": 600, "cure": ["Paralyzed", "Petrified", "Poisoned"],
                  "effect": {"mods": {"resist": ["bludgeoning", "fire", "piercing", "slashing"], "immune": ["poison"], "immune_cond": ["Paralyzed", "Petrified", "Poisoned"],
                                      "no_exhaust": True},
                             "note": "living metal: resists bludgeoning, fire, piercing, slashing; immune to poison, paralysis, petrification; exhaustion can't rise"}},
    "lightning ring": {"kind": "zone", "area": {"shape": "emanation", "size": 10, "origin": "caster"}, "target": {"type": "self"}, "choose_type": [],
                       "zone": {"follow": True, "sweep": True, "enter": True, "end": True, "on_cast": True, "affects": "enemies", "save": "con", "half": True,
                                "parts": [["3d6", "lightning"], ["3d6", "thunder"]], "conds": ["Deafened"], "cond_rounds": 10},
                       "action": {"name": "Lightning Ring: line", "cost": "action", "area": {"shape": "line", "size": 60, "width": 5, "origin": "caster"},
                                  "save": "dex", "half": True, "parts": [["6d6", "lightning"]]}},
    "moment of prescience": {"kind": "reaction_only"},      # reactions.py: a failed D20 Test becomes a 20, or the attack roll against you a 1
    "detonate": {"kind": "save", "save": "con", "parts": [["10d10", "fire"]], "half": True, "conds": [], "area": None,
                 "explode": {"radius": 60, "save": "dex", "parts": [["10d10", "fire"]], "half": True, "skip_target": True, "dis_if_down": True}},
    "vision of elapsing eons": {"kind": "save", "save": "int", "parts": [["10d12", "psychic"]], "half": False, "conds": ["Paralyzed"], "repeat": "end", "rounds": 10,
                                "effect": {"mods": {"fail_exhaust": True}, "note": "watching itself crumble: paralyzed, a level of exhaustion for each failed save"}},
    "wail of the banshee": {"kind": "save", "save": "con", "parts": [["12d10", "psychic"]], "half": True, "conds": ["Deafened"], "repeat": None, "rounds": 600,
                            "kill_below": 50, "target": {"type": "creature", "count": 10}},
    # ---- Legends Reforged (the LGR content module, installed from LGR-*.dmmod): what its texts leave to the engine
    "death spark": {"self_cost": [["1d4", ""]]},            # hit or miss, the caster takes 1d4 necrotic that nothing reduces (typeless here)
    "aard": {"push": 10, "disperse": True,                  # blows away the clouds in the cone (zones._disperse)
             "effect": {"mods": {"no_reactions": True}, "until": "target_start", "note": "knocked off balance: no reactions until its next turn"}},
    "quen": {"kind": "buff", "target": {"type": "self"}, "rounds": 10,
             "effect": {"mods": {"hit_ward": 1}, "note": "an amber shield: the next hit deals it no damage"},
             "slot_mods": {3: {"hit_ward": 2}, 5: {"hit_ward": 3}, 7: {"hit_ward": 4}, 9: {"hit_ward": 5}}},     # one more hit per two slot levels
    "axii": {"kind": "save", "save": "wis", "parts": [], "conds": ["Charmed", "Incapacitated"], "repeat": "end", "rounds": 10, "ends_on": ["damage"],
             "effect": {"mods": {"speed_set": 0}, "note": "dazed: speed 0"}, "choose_type": ["daze", "puppet"],
             "options": {"puppet": {"conds": ["Charmed"], "min_level": 3, "effect": {"mods": {"dominated": True}, "note": "a puppet: fights for the caster"}}}},
    "bound weapon": {"kind": "buff", "target": {"type": "self"}, "area": None, "choose_type": ["sword", "battleaxe", "bow"], "up_every": 2,
                     "effect": {"mods": {}, "note": "a weapon of spectral force in hand"},
                     "action": {"name": "Bound Sword", "cost": "action", "atk": "melee", "parts": [["1d8+MOD", "force"]], "up": "1d8", "range": 5},
                     "action_options": {"battleaxe": {"name": "Bound Battleaxe", "cost": "action", "atk": "melee", "parts": [["1d12+MOD", "force"]], "up": "1d12",
                                                      "range": 5},
                                        "bow": {"name": "Bound Bow", "cost": "action", "atk": "ranged", "parts": [["1d8+MOD", "force"]], "up": "1d8", "range": 150}}},
    "glám dícenn": {"effect": {"mods": {"attacks_with": "dis", "once": True}, "until": "target_end_next", "note": "disadvantage on its next attack roll"}},
    "yrden": {"kind": "zone", "area": {"shape": "sphere", "size": 15, "origin": "point"}, "target": {"type": "point"}, "grow": 5,
              "zone": {"slow": True, "affects": "enemies", "inside": {"no_reactions": True}, "solidify": True}},      # (zones._zone_mods)
    "marked for death": {"kind": "save", "save": "con", "parts": [], "conds": [], "repeat": "end", "rounds": 10,
                         "effect": {"mods": {"ac": -2}, "note": "marked for death: AC -2, necrotic damage each turn"},
                         "dot": {"dice": "1d8", "type": "necrotic", "when": "start", "up": "1d8"}},
    "fire rune": {"kind": "zone", "area": {"shape": "square", "size": 15, "origin": "point"}, "target": {"type": "point"},    # the tiles within 5 ft of the rune
                  "choose_type": ["fire", "frost", "shock"],
                  "zone": {"trap": {"radius": 15, "save": "dex", "half": True, "parts": [["4d6", "fire"]], "up": "1d6",
                                    "options": {"frost": {"type": "cold", "fail_mods": {"speed": -10}, "fail_until": "target_end_next"},
                                                "shock": {"type": "lightning"}}}}},
    "unrelenting force": {"push": 20, "push_size": "Large", "prone": True, "conds": []},     # a Huge or larger creature isn't pushed
    "walking bomb": {"kind": "save", "save": "con", "parts": [], "conds": [], "repeat": "end", "rounds": 10,
                     "effect": {"mods": {"death_burst": {"radius": 20, "save": "dex", "half": True, "parts": [["6d6", "necrotic"]], "up": "1d6"}},
                                "note": "a walking bomb: necrotic damage each turn, it bursts if it drops to 0"},     # (spells._bomb_burst)
                     "dot": {"dice": "2d6", "type": "necrotic", "when": "start"}},
    "helm of awe": {"kind": "zone", "area": {"shape": "emanation", "size": 15, "origin": "caster"}, "target": {"type": "self"}, "grow": 5,
                    "zone": {"follow": True, "start": True, "affects": "enemies", "sees_owner": True, "save": "wis", "conds": ["Frightened"],
                             "fail_until": "target_start", "parts": [], "on_save": {"mods": {"zone_immune": True}}},      # a success: immune to this casting
                    "self_effect": {"mods": {"cond_save_adv": ["Frightened"]}, "note": "advantage on saves against being frightened"}},
    "song of sinking": {"kind": "save", "save": "str", "parts": [], "conds": ["Restrained"], "repeat": "end", "rounds": 10,
                        "effect": {"mods": {"worsen": [{"mods": {"no_reactions": True, "no_bonus": True}, "note": "buried to the waist: no reactions or bonus actions"},
                                                       {"conds": ["Incapacitated"], "note": "buried to the chin: incapacitated"}]},
                                   "note": "sinking: restrained"}},          # each failed save sinks it deeper (spells._worsen)
    "ice form": {"kind": "save", "save": "con", "conds": ["Restrained", "Incapacitated"], "repeat": "end", "rounds": 10, "ends_on": ["fire"],
                 "effect": {"mods": {}, "note": "frozen in a block of ice"}},        # fire damage melts it
    "fist of the heavens": {"parts": [["4d10", "lightning"]], "up": "1d10", "half": True,
                            "explode": {"radius": 15, "save": "dex", "half": True, "parts": [["2d8", "radiant"]], "skip_target": True, "foes_only": True,
                                        "dis_types": ["undead", "fiend"]}},
    "norns' weave": {"kind": "buff", "target": {"type": "self"}, "rounds": 600,      # reactions.py: a recorded d20 for a roll it can see within 60 ft
                     "effect": {"mods": {"fate_n": 3}, "note": "the threads of fate: recorded d20s to swap in"}, "slot_mods": {7: {"fate_n": 4}}},
    "slow time": {"kind": "zone", "area": {"shape": "emanation", "size": 30, "origin": "caster"}, "target": {"type": "self"},
                  "zone": {"follow": True, "sweep": True, "enter": True, "start": True, "affects": "enemies", "save": "wis", "parts": [],
                           "fail_mods": {"ac": -2, "save_ab": {"dex": -2}, "speed_mult": .5, "no_reactions": True, "one_action": True},
                           "fail_until": "target_start", "inside_allies": {"ranged_against": "dis"}}},
    "storm call": {"kind": "buff", "target": {"type": "self"}, "area": None, "rounds": 10,
                   "effect": {"mods": {"random_bolts": {"n": 2, "ft": 120, "save": "dex", "half": True, "parts": [["4d10", "lightning"]]}},
                              "note": "a storm overhead: lightning strikes two random creatures at the end of each of its turns"},     # (spells._spell_turn_end_items)
                   "action": {"name": "Storm Call: bolt", "cost": "action", "save": "dex", "half": True, "parts": [["4d10", "lightning"]], "range": 120, "up": None}},
    "comet azur": {"parts": [["10d8", "force"]], "up": "1d8", "half": True, "self_effect": {"mods": {"speed_set": 0}, "note": "pouring out the comet: speed 0"},
                   "action": {"name": "Comet Azur: fire again", "cost": "action", "area": {"shape": "line", "size": 120, "width": 10, "origin": "caster"},
                              "save": "dex", "half": True, "parts": [["10d8", "force"]]}},
}


def _norm(name: str) -> str:
    return CR.norm(name)


@lru_cache(maxsize=2048)
def _spec_cached(name: str) -> Optional[dict]:
    from ...rules.data import rules
    sp = rules.spell(name)
    return spec(sp) if sp else None


def spec_of(name: str) -> Optional[dict]:
    return _spec_cached(name)


def spec(sp: dict) -> dict:
    key = _norm(sp["name"])
    sx = SPECIAL.get(key, {})
    kind = sx.get("kind") or CR.classify(sp)
    rng, rkind = parse_range(sp.get("range", ""))
    if "range" in sx:
        rng = sx["range"]
    area = sx.get("area") if "area" in sx else _area(sp)
    buff = X.BUFFS.get(key) or {}
    text = sp.get("text", "")
    count, per, any_n = _count(text, sp.get("higher_level", ""))
    tg = {"type": "creature", "count": count, "per_level": per, "base_level": sp.get("level", 0)}
    if kind in ("utility", "reaction_only", "self_transform", "summon_image", "time_stop"):
        tg = {"type": "self" if rkind == "self" else "none"}
    elif kind == "summon":
        tg = {"type": "point", "optional": True}
    elif area and kind not in ("buff",):
        if area.get("origin") == "caster":
            tg = {"type": "self_area", "aim": area["shape"] in ("cone", "line", "cube", "square")}
        else:
            tg = {"type": "point"}
    elif buff.get("self") or (rkind == "self" and kind in ("buff", "self_effect")):
        tg = {"type": "self"}
    elif sp["name"] in ("Magic Missile", "Scorching Ray", "Eldritch Blast"):
        tg = {"type": "split", "count": 3 if sp["name"] != "Eldritch Blast" else 1, "per_level": 1, "base_level": sp["level"]}
    if kind in ("heal", "buff", "cleanse", "revive") and tg.get("type") == "creature":
        if buff.get("on_fail") or buff.get("marks"):              # curses and marks (Bane, Hex, Hunter's Mark...) go on foes
            tg["enemies"] = True
        else:
            tg["allies"] = True
    atk_type = sx.get("atk_type") or ("melee" if re.search(r"melee spell attack", text, re.I) else "ranged" if re.search(r"ranged spell attack", text, re.I) else None)
    if rkind == "self" and tg.get("type") == "creature" and "range" not in sx:
        if atk_type == "melee" or kind == "attack":
            rng = 5
        else:
            tg = {"type": "self"}
    if "target" in sx:
        tg = dict(tg, **sx["target"])
        tg.setdefault("base_level", sp.get("level", 0))
    near = re.search(r"within (\d+) feet of each other", text + " " + (sp.get("higher_level") or ""))
    if near and tg.get("type") == "creature" and "near" not in tg:     # Hold Person upcast: the targets within 30 ft of each other
        tg["near"] = int(near.group(1))
    if kind in ("attack", "save", "auto") and tg.get("type") == "self" and not area:
        kind = "utility"                                    # damage dice of a self-only spell are never the caster's own damage
    cost = "on_hit" if key in X.ON_HIT else EC.casting_cost(sp.get("casting_time", ""))
    out = {"name": sp["name"], "key": key, "level": sp.get("level", 0), "cost": cost,
           "range": rng, "range_kind": rkind, "target": tg, "area": area, "kind": kind, "atk_type": atk_type,
           "concentration": bool(sp.get("concentration")), "duration": CR.duration_rounds(sp.get("duration", "")),
           "school": sp.get("school", ""), "special": sx, "buff": buff,
           "verbal": bool((sp.get("components") or {}).get("v")) if isinstance(sp.get("components"), dict) else True,
           "types": sx["choose_type"] if "choose_type" in sx else buff.get("choose") or CR.type_choices(sp)}    # []: no choice
    return out


def _area(sp: dict) -> Optional[dict]:
    if sp["name"] == "Sleep":
        return {"shape": "sphere", "size": 20, "width": 5, "origin": "point"}
    a = CR.area_of(sp)
    if not a:
        return None
    a = dict(a)
    if a["origin"] == "target":
        a["origin"] = "point"
    if a["shape"] == "sphere" and a["origin"] == "caster":
        a["shape"] = "emanation"
    return a


def target_count(sp_spec: dict, slot: int) -> int:
    tg = sp_spec["target"]
    n = int(tg.get("count") or 1)
    per = int(tg.get("per_level") or 0)
    return n + per * max(0, slot - int(tg.get("base_level") or sp_spec["level"]))


def projectiles(sp: dict, slot: int, caster_level: int) -> int:
    if sp["name"] == "Eldritch Blast":
        return 1 + (caster_level >= 5) + (caster_level >= 11) + (caster_level >= 17)
    if sp["name"] in ("Magic Missile", "Jim's Magic Missile"):
        return 3 + max(0, slot - 1)
    if sp["name"] == "Scorching Ray":
        return 3 + max(0, slot - 2)
    if sp["name"] == "Spellfire Flare":                  # one more blast for each slot level above 1st
        return 1 + max(0, slot - 1)
    return 1


def cantrip_die(table: dict, caster_level: int) -> str:
    best = None
    for lv, v in sorted(table.items()):
        if caster_level >= int(lv):
            best = v
    return best or "0"


def upcast(parts, up: Optional[str], extra: int, every: int = 1, offset: int = 0):
    """Add `up` dice (e.g. '1d8') per `every` slot levels above the spell's level to the first part (`offset`: Shadow Blade's
    first step comes after one level, the next ones every two)."""
    if not up or extra <= 0 or not parts:
        return [list(p) for p in parts]
    steps = (extra + offset) // every
    if steps <= 0:
        return [list(p) for p in parts]
    n, _, die = up.partition("d")
    out = [list(p) for p in parts]
    out[0][0] = f"{out[0][0]}+{int(n or 1) * steps}d{die}"
    return out


def fill(parts, mod: int, dtype: Optional[str] = None):
    """Replace MOD in damage dice with the spellcasting modifier and $type with the picked damage type."""
    out = []
    for d, t in parts:
        d = str(d).replace("+MOD", f"{mod:+d}").replace("MOD", str(mod))
        d = d.replace("+-", "-")
        out.append([d, (dtype or "") if t == "$type" else t])
    return out
