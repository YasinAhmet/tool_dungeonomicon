"""Class, subclass and race features inside a resolution (features.ACTIVE lists the ones on the action bar).

    _class_feature        the bar's subclass and race features: Channel Divinity options, Hexblade's Curse, Favored Foe...
    _feature_why          why one can't be used now (not raging, no Attack action yet, no target...)
    _class_hit_parts      extra damage on a hit: Colossus Slayer, Divine Fury, Favored Foe, Hexblade's Curse, Dreadful Strikes,
                          Genie's Wrath, Giant's Might, Lifedrinker, Thrown Weapon Fighting...
    _class_modes          advantage / disadvantage: Wolf and Bear totems, Ancestral Protectors, Escape the Horde, Feinting Attack
    _class_ac_vs          AC against one attacker (Multiattack Defense); _class_crit_vs: Hexblade's Curse crits on 19
    _class_damage         rolled damage changed: Great Weapon Fighting rerolls 1s and 2s
    _class_strike_start   a spell's damage: Elemental Affinity, Radiant Soul
    _class_zero_hp        Relentless Rage, Strength of the Grave; _class_kill: Dark One's Blessing, Hexblade's Curse
    _class_turn_start     Twilight Sanctuary, Halo of Spores, Dread Ambusher
    _class_eligible / _class_react    reactions and on-hit choices: Warding Flare, Protection, Interception, Guided Strike,
                          Eldritch Smite, Open Hand Technique, Stone's Endurance... (reactions.py asks, these answer)

A feature's "choose one" (Hunter's Prey, Totem Spirit, Divine Fury's type) is a switch in rules/combat_feats.py.
"""
import re
from typing import List, Optional

from ...rules import combat_feats as CF
from ...rules import spellcasting as SC
from ...rules.data import rules
from ...rules.monsters import ability_mod, bestiary
from ..common import ServiceError
from . import economy as EC
from . import features as F
from . import geometry as G
from . import modifiers as M
from . import sight as V
from . import summon_stats as SS
from .constants import SPANS
from .resolve import roll
from .standard import SIZES
from .subfeats import SUB_FAMILIES, SUB_FREE, SubFeatsMixin

# reaction families (the reaction settings and the log name them); CLASS_FREE ones cost no reaction
CLASS_FAMILIES = {
    "flare": "Warding Flare", "protection": "Protection", "interception": "Interception", "deflection": "Arcane Deflection",
    "illusory_self": "Illusory Self", "entropic_ward": "Entropic Ward", "shadowy_dodge": "Shadowy Dodge",
    "death_door": "Sentinel at Death's Door", "guided_strike": "Guided Strike", "favored_gods": "Favored by the Gods",
    "giant_killer": "Giant Killer", "storm_wrath": "Wrath of the Storm", "stones_endurance": "Stone's Endurance",
    "song_defense": "Song of Defense", "spirit_shield": "Spirit Shield", "fanatical_focus": "Fanatical Focus",
    "dark_luck": "Dark One's Own Luck", "diamond_soul": "Diamond Soul", "eldritch_smite": "Eldritch Smite",
    "psychic_blades": "Psychic Blades", "hand_of_harm": "Hand of Harm", "open_hand": "Open Hand Technique",
    "fury_small": "Fury of the Small", "sweep": "Sweeping Attack", "halo": "Halo of Spores",
    "arcane_shot": "Arcane Shot", "psionic_strike": "Psionic Strike", "flourish": "Blade Flourish", "protective_field": "Protective Field",
    "projected_ward": "Projected Ward", "misty_escape": "Misty Escape", "armor_of_hexes": "Armor of Hexes", "lucky_footwork": "Lucky Footwork",
    "saving_face": "Saving Face", "arcane_jolt": "Arcane Jolt", "flash": "Flash of Genius", "valor": "Combat Inspiration",
    "valor_ac": "Combat Inspiration (AC)", "war_god": "War God's Blessing", "runic_shield": "Runic Shield", "glorious_defense": "Glorious Defense",
    "bm_parry": "Parry (maneuver)", "dampen": "Dampen Elements", "rebuke_violent": "Rebuke the Violent", "guardian": "Aura of the Guardian",
    "focused_aim": "Focused Aim", "seeking_spell": "Seeking Spell", "stroke_of_luck": "Stroke of Luck", "tomb": "Tomb of Levistus",
    "talisman_rebuke": "Rebuke of the Talisman", "talisman_protect": "Protection of the Talisman", "storm_rune": "Storm Rune",
    "fire_rune": "Fire Rune", "vigilant": "Vigilant Guardian", "tail": "Beast Tail",
    "legend": "Living Legend", "legend_save": "Living Legend (save)", "stalkers_flurry": "Stalker's Flurry", "master_duelist": "Master Duelist", "warding_maneuver": "Warding Maneuver",
    "backlash": "Unstable Backlash", "wolf_prone": "Wolf totem (prone)", "infectious_fury": "Infectious Fury", "balance": "Restore Balance", "vengeful": "Vengeful Assault", "shield_master": "Shield Master (Dex saves)", "skirmisher": "Skirmisher", "brace": "Brace", "quivering": "Quivering Palm", "portent": "Portent", "bend_luck": "Bend Luck", "omen": "Cosmic Omen", "bond": "Emboldening Bond", "bountiful": "Bountiful Luck",
}
CLASS_FREE = {"guided_strike", "favored_gods", "fanatical_focus", "dark_luck", "diamond_soul", "eldritch_smite", "psychic_blades",
              "hand_of_harm", "open_hand", "fury_small", "sweep", "arcane_shot", "psionic_strike", "flourish", "saving_face", "arcane_jolt", "valor",
              "portent", "bond", "quivering", "stalkers_flurry", "legend", "master_duelist", "wolf_prone", "infectious_fury",
              "focused_aim", "seeking_spell", "stroke_of_luck", "talisman_protect", "fire_rune"}
TARGETED = {"abjure_enemy", "natures_wrath", "path_to_the_grave", "war_priest", "intimidating_presence", "radiant_sun_bolt",
            "feinting_attack", "war_magic", "favored_foe", "slayers_prey", "planar_warrior", "horde_breaker", "volley",
            "hexblades_curse", "unsettling_words", "luminous_arrow", "hungry_jaws", "dread_ambusher", "insightful_fighting",
            "psychic_blade", "psychic_blade_bonus", "commanders_strike", "master_of_tactics", "tentacle", "tentacle_strike",
            "majestic_command", "unwavering_strike", "ki_fueled_attack", "grappling_strike", "bait_and_switch", "maddening_hex", "water_whip", "unbroken_air", "goring_rush", "hammering_horns", "quick_toss", "hypnotic_gaze", "battle_magic", "beast_bite", "beast_claws", "beast_tail", "thunder_gauntlets", "lightning_launcher"}
NOT_FORCE = [t for t in M.TYPES if t != "force"]
ARCANE_SHOTS = {"Banishing Arrow": "Cha save or banished until the end of its next turn", "Beguiling Arrow": "2d6 psychic, Wis save or charmed",
                "Bursting Arrow": "2d6 force to it and everyone within 10 ft", "Enfeebling Arrow": "2d6 necrotic, Con save or its weapon damage is halved",
                "Grasping Arrow": "2d6 poison, speed -10", "Shadow Arrow": "2d6 psychic, Wis save or it can't see beyond 5 ft"}


# Way of the Four Elements: discipline -> (spell it casts, ki, monk level it needs)
DISCIPLINES = {"Fist of Four Thunders": ("Thunderwave", 2, 3), "Rush of the Gale Spirits": ("Gust of Wind", 2, 3),
               "Sweeping Cinder Strike": ("Burning Hands", 2, 3), "Clench of the North Wind": ("Hold Person", 3, 6),
               "Gong of the Summit": ("Shatter", 3, 6), "Flames of the Phoenix": ("Fireball", 4, 11), "Mist Stance": ("Gaseous Form", 4, 11),
               "Ride the Wind": ("Fly", 4, 11), "Breath of Winter": ("Cone of Cold", 6, 17), "Eternal Mountain Defense": ("Stoneskin", 5, 17),
               "River of Hungry Flame": ("Wall of Fire", 5, 17), "Wave of Rolling Earth": ("Wall of Stone", 6, 17)}
# other monks' spells for ki: name -> (subclass, monk level, spell, ki, casting cost or None for the spell's own)
KI_SPELLS = {"Shadow Arts: Darkness": ("Way of Shadow", 3, "Darkness", 2, None),
             "Shadow Arts: Silence": ("Way of Shadow", 3, "Silence", 2, None),
             "Shadow Arts: Pass without Trace": ("Way of Shadow", 3, "Pass without Trace", 2, None),
             "Searing Arc Strike": ("Way of the Sun Soul", 6, "Burning Hands", 2, "bonus")}
# Eldritch Invocations that cast a spell: name -> (spell, 'will' (at will, no slot) or 'slot' (once per long rest, a warlock slot))
INVOCATION_SPELLS = {"Armor of Shadows": ("Mage Armor", "will"), "Fiendish Vigor": ("False Life", "will"), "Ascendant Step": ("Levitate", "will"),
                     "Otherworldly Leap": ("Jump", "will"), "Shroud of Shadow": ("Invisibility", "will"), "Misty Visions": ("Silent Image", "will"),
                     "Chains of Carceri": ("Hold Monster", "will"), "Dreadful Word": ("Confusion", "slot"), "Mire the Mind": ("Slow", "slot"),
                     "Sign of Ill Omen": ("Bestow Curse", "slot"), "Thief of Five Fates": ("Bane", "slot"),
                     "Bewitching Whispers": ("Compulsion", "slot"), "Minions of Chaos": ("Conjure Elemental", "slot"),
                     "Sculptor of Flesh": ("Polymorph", "slot"), "Trickster's Escape": ("Freedom of Movement", "long")}
# Path of Wild Magic, Wild Surge (d8)
WILD_SURGE = {1: "Shadowy Tendrils", 2: "Teleport", 3: "Exploding Spirit", 4: "Infused Weapon", 5: "Retribution", 6: "Protective Lights",
              7: "Flowers and Vines", 8: "Bolt of Light"}


CLASS_FAMILIES.update(SUB_FAMILIES)                                  # Shadow Martyr, Homing Strikes, Storm's Fury (subfeats.py)
CLASS_FREE |= SUB_FREE


def _bigger(a: str, b: str) -> bool:
    return SIZES.index(a) > SIZES.index(b) if a in SIZES and b in SIZES else False


class ClassFeatsMixin(SubFeatsMixin):
    # ------------------------------------------------------------------ small helpers
    def _cf_left(self, c: dict, name: str, n: int, rest: str = "long") -> int:
        """Uses of a per-rest feature left (counted in the character's resources like the bar's 'per' features)."""
        char = self._sheet(c)
        if not char:
            return 0
        return max(0, int(n) - int(char.d["resources"].get(("short:" if rest == "short" else "feature:") + name) or 0))

    def _cf_use(self, c: dict, name: str, rest: str = "long"):
        char = self._sheet(c)
        if char:
            key = ("short:" if rest == "short" else "feature:") + name
            char.d["resources"][key] = int(char.d["resources"].get(key) or 0) + 1
            char.save()

    def _cf_turn_free(self, c: dict, key: str) -> bool:
        """Not used yet this turn (without marking it, unlike _once_per_turn)."""
        return (c.get("trait_used") or {}).get(key) != [self.b.get("round"), self.b.get("turn")]

    def _raging(self, c: Optional[dict]) -> bool:
        return bool(c) and bool(self._fx(c, "rage"))

    def _cf_hostiles(self, c: dict, feet: int) -> List[dict]:
        return [o for o in self.b["combatants"] if o is not c and self._hostile(c, o) and o.get("pos") and not self._is_out(o)
                and self._alive(o) and self._within(c, o, feet)]

    def _cf_dc(self, char, ab: str) -> int:
        return 8 + char.proficiency_bonus + char.mod(ab)

    def _swarm_step(self, att: dict, tgt: dict, R: dict, melee: bool):
        """Gathered Swarm's 'move yourself 5 ft' (no opportunity attacks): a melee hitter shifts to another free tile that
        still touches the target, a ranged one backs off from it. Stays put when nothing is free."""
        blocked = self._blocked_tiles()
        hostile, other = self._occupied(att)
        span = att.get("span") or 1
        here = tuple(att["pos"])
        best = None
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                nxt = (here[0] + dx, here[1] + dy)
                if (dx, dy) == (0, 0) or not self._step_ok(att, here, nxt, blocked, hostile | other):
                    continue
                if G.footprint(nxt, span) & other:
                    continue
                d = G.distance_ft(nxt, span, tgt["pos"], tgt.get("span") or 1)
                if melee and d > 5:
                    continue
                score = (d if not melee else 0, -abs(dx) - abs(dy))
                if best is None or score > best[0]:
                    best = (score, nxt)
        if best is None:
            self._line(R, "Gathered Swarm: nowhere to move", "Gathered Swarm")
            return
        att["pos"] = list(best[1])
        self._vfx("step", id=att["id"], to=list(best[1]))
        self._follow_zones(att)
        self._line(R, f"Gathered Swarm: {att['name']} moves 5 ft", "Gathered Swarm")

    @staticmethod
    def _ctype(o_monster: Optional[dict]) -> str:
        return str((o_monster or {}).get("type") or "").lower()

    def _cf_weapon(self, c: dict, char, tgt: dict, ranged: Optional[bool] = None):
        """(weapon, atk) of the best weapon that reaches the target (raises when none does)."""
        ws = [w for w in char.attacks() if "unarmed" not in (w.get("props") or [])] or char.attacks()
        if ranged is not None:
            ws = [w for w in ws if bool(w.get("ranged")) == ranged]
        why = "No weapon for that"
        close = bool(c.get("pos") and tgt.get("pos")) and self._dist(c, tgt) <= 5
        for w in sorted(ws, key=lambda x: (close and bool(x.get("ranged")), -x["attack"])):    # beside it: a melee weapon first
            try:
                return w, self._feat_attack(c, w, self._check_reach(c, tgt, self._weapon_atk(c, w)))
            except ServiceError as e:
                why = str(e)
        raise ServiceError(why)

    def _cf_weapon_strike(self, c: dict, char, tgt: Optional[dict], label: str, ranged: Optional[bool] = None) -> str:
        if not tgt or tgt is c:
            raise ServiceError("Pick a target first.")
        w, atk = self._cf_weapon(c, char, tgt, ranged)
        return self._run_r(self._strike(c, f"{w['name']} ({label})", [tgt["id"]], mode="attack", atk=atk, magical=atk.get("magical", False)))

    def _cf_spell_attack(self, c: dict, char, tgt: dict, label: str, ab: str, dice: str, dtype: str, feet: int) -> str:
        mod = char.mod(ab)
        atk = {"bonus": char.proficiency_bonus + mod, "n": 1, "melee": False, "spell": True, "normal": feet, "long": feet,
               "parts": [[f"{dice}{mod:+d}" if mod else dice, dtype]]}
        return self._run_r(self._strike(c, label, [tgt["id"]], mode="attack", atk=atk, magical=True))

    def _cf_dark(self, tiles) -> bool:
        ter, base, zones = self._terrain(), self.b.get("map", {}).get("light", "bright"), self._live_zones()
        return all(V.light_at(ter, tuple(t), base, zones) in ("dim", "dark") for t in tiles)

    def _cf_landing(self, c: dict, point, feet: int, shadows: bool = False) -> Optional[str]:
        """Why the creature can't teleport to this tile (None: it can)."""
        if not c.get("pos"):
            return "Not on the map."
        if not point or len(point) < 2:
            return "Pick where to land."
        x, y = int(point[0]), int(point[1])
        if G.distance_ft(c["pos"], c.get("span") or 1, [x, y], c.get("span") or 1) > feet:
            return f"Too far (up to {feet} ft)"
        if not self._tile_ok(c, x, y):
            return "That tile is taken or off the map."
        if shadows and not (self._cf_dark(G.footprint(c["pos"], c.get("span") or 1)) and self._cf_dark(G.footprint([x, y], c.get("span") or 1))):
            return "Both where you are and where you land must be in dim light or darkness"
        return None

    def _cf_teleport(self, c: dict, point) -> list:
        x, y = int(point[0]), int(point[1])
        self._vfx("blink", id=c["id"], at=c.get("pos"), to=[x, y])
        c["pos"] = [x, y]
        self._follow_zones(c)
        return [x, y]

    def _cf_offer(self, out: list, reactor: dict, cost: str, opts: list, text: str, window: Optional[str] = None):
        """Add options to the reactor's question in this window (one question per reactor and cost)."""
        if not opts:
            return
        for item in out:
            if item["reactor"] == reactor["id"] and item["cost"] == cost and item.get("window") == window:
                item["options"] += opts
                return
        item = {"reactor": reactor["id"], "cost": cost, "options": opts, "text": text}
        if window:
            item["window"] = window
        out.append(item)

    # ------------------------------------------------------------------ the action bar
    def _feature_range(self, c: dict, char, key: str) -> Optional[int]:
        """The reach shown on the bar for the features that attack with a weapon."""
        if key not in ("war_priest", "war_magic", "horde_breaker", "volley", "dread_ambusher", "battle_magic", "quick_toss"):
            return None
        best = 5
        for w in char.attacks():
            atk = self._weapon_atk(c, w)
            if key == "volley" and atk["melee"]:
                continue
            best = max(best, atk["reach"] if atk["melee"] else (atk.get("long") or 5))
        return best

    def _feature_why(self, c: dict, char, key: str, f: dict, tgt: Optional[dict], option, menu: bool = False, point=None) -> Optional[str]:
        t = c.get("turn") or {}
        econ = self._economy_on()
        if f.get("teleport") and not menu:
            feet = f["teleport"](char) if callable(f["teleport"]) else f["teleport"]
            why = self._cf_landing(c, point, feet, key == "shadow_step")
            if why:
                return why
        if menu and key == "shadow_step" and c.get("pos") and not self._cf_dark(G.footprint(c["pos"], c.get("span") or 1)):
            return "Stand in dim light or darkness first"          # greyed out on the bar in bright light
        why = self._sub_why(c, char, key, f, tgt, option, menu, point)       # Echo Knight, Giant, Soulknife... (subfeats.py)
        if why:
            return why
        when = f.get("when")
        if when == "raging" and not self._raging(c):
            return "Only while raging"
        if when == "attacked" and econ and not t.get("attacked"):
            return "Take the Attack action first"
        any_spell = key == "war_magic" and F.sub_at(char, "Fighter", "Eldritch Knight", 18)     # Improved War Magic: after any spell
        if when == "cantrip" and econ and not any(cost == "action" and (any_spell or int(lv) == 0) for cost, lv in t.get("spells") or []):
            return "Cast a cantrip with your action first"
        if key in ("maddening_hex", "relentless_hex"):
            cursed = [o for o in self.b["combatants"] if self._cf_cursed(c, o) and self._alive(o)]
            if not cursed:
                return "No creature carries your hex or curse"
            if not menu and key == "maddening_hex" and not self._cf_cursed(c, tgt):
                return "Pick the hexed or cursed creature."
            if not menu and key == "relentless_hex" and point and not any(
                    o.get("pos") and G.distance_ft([int(point[0]), int(point[1])], c.get("span") or 1, o["pos"], o.get("span") or 1) <= 30 for o in cursed):
                return "Land within 30 ft of the cursed creature."
        if when == "duplicate":
            tok = self._cf_duplicate(c, point)
            if tok is None:
                return "No duplicate on the map"
            if not menu:
                if not point:
                    return "Pick where it goes."
                x, y = int(point[0]), int(point[1])
                if tok.get("pos") and max(abs(x - tok["pos"][0]), abs(y - tok["pos"][1])) * 5 > 30:
                    return "It moves up to 30 ft."
                if not self._tile_ok(tok, x, y):
                    return "That tile is taken or off the map."
        if when == "majesty" and not self._fx(c, "majesty_mantle"):
            return "Only under the Mantle of Majesty"
        if when == "marked":
            mark = self._find_or_none(c.get("mark_strike"))
            if mark is None or not self._alive(mark):
                return "No marked creature has hurt someone else"
            if not menu and tgt is not mark:
                return f"Pick {mark['name']}, the marked creature."
        if key == "searing_sunburst" and not menu:
            aim = point or self.b.get("aim")
            if not aim or not c.get("pos"):
                return "Pick where the sunburst lands."
            if G.distance_ft(c["pos"], c.get("span") or 1, [int(aim[0]), int(aim[1])], 1) > 150:
                return "Too far (150 ft)"
        if key in ("invoke_duplicity", "mantle_of_majesty", "unbreakable_majesty") and any(
                e["name"] == f["name"] for e in c.get("effects") or []):
            return "Already active"
        if key == "steps_of_night" and c.get("pos") and not self._cf_dark(G.footprint(c["pos"], c.get("span") or 1)):
            return "Stand in dim light or darkness first"
        if when == "tentacle" and not self._fx(c, "tentacle"):
            return "Summon the tentacle first"
        if key == "tentacle" and self._fx(c, "tentacle"):
            return "Already there: use Tentacle strike"
        if when == "ki_action" and econ and not t.get("ki_action"):
            return "Spend ki in your action first"
        if when == "dashed" and econ and not t.get("dashed"):
            return "Take the Dash action first"
        if key == "goring_rush" and econ and int(t.get("speed", 0)) * (1 + int(t.get("dashed") or 0)) - int(t.get("move", 0)) < 20:
            return "Move at least 20 ft after the Dash first"     # "Immediately after you use the Dash action on your turn and move at least 20 feet"
        if when == "spell" and econ and not any(cost == "action" for cost, _lv in t.get("spells") or []):
            return "Cast a spell with your action first"
        if when == "starry" and not any(v == "archer" for _e, v in self._fx(c, "starry")):
            return "Only in Starry Form (Archer)"
        if key in ("harness_cleric", "harness_paladin") and not F.harness_options(char):
            return "No spent spell slot it can bring back"
        if key == "flexible_casting":
            opts = F.flexible_options(char)
            if not opts:
                return "Nothing to convert"
            if option and str(option).startswith("slot:"):
                n = int(str(option).split(":")[1])
                if self._resource_left(c, "Sorcery Points") < F.FLEX_COST.get(n, 99):
                    return "Not enough sorcery points"
        if key == "vanish" or key == "nimble_escape" and option == "hide":
            try:
                self._check_can_hide(c)
            except ServiceError as e:
                return str(e)
        if key == "commanders_strike" and econ and EC.why_not(t, "bonus"):
            return "Needs your bonus action too"
        if key == "unearthly_recovery" and self._hp_of(c) >= self._max_hp(c) // 2:
            return "Only below half your hit points"
        if key == "quivering_palm":
            shaking = [o for o in self.b["combatants"] if any((e.get("mods") or {}).get("quivering") == c["id"] for e in o.get("effects") or [])]
            if not shaking:
                return "No creature is vibrating (3 ki on an unarmed hit first)"
            if not menu and tgt not in shaking:
                return f"Pick the vibrating creature: {', '.join(o['name'] for o in shaking)}"
        if key == "horde_breaker" and t.get("horde_breaker"):
            return "Once a turn"
        if key == "dread_ambusher" and (self.b.get("round") != 1 or c.get("dread_attack")):
            return "Only on your first turn of the battle"
        armor = (char.equipped_armor() or {}).get("type")
        if key in ("eagle_dash", "rage") and armor == "HA":
            return "Not in heavy armour"
        if key == "bladesong" and (armor in ("MA", "HA") or char.equipped_shield()):
            return "Not in medium or heavy armour, or with a shield"
        res = char.d["resources"]
        if key == "dragon_fear" and res.get("short:Breath Weapon") or key == "breath_weapon" and res.get("short:Dragon Fear"):
            return "The breath weapon is spent until a short rest"
        if key in ("dragon_wings", "symbiotic_entity", "starry_form", "twilight_sanctuary", "giants_might", "astral_arms") and any(
                e["name"].startswith(f["name"].split(" (")[0]) for e in c.get("effects") or []):
            return "Already active"
        if not menu and key in TARGETED and (not tgt or tgt is c):
            return "Pick a target first."
        if not menu and key in ("abjure_enemy", "natures_wrath", "path_to_the_grave", "intimidating_presence", "hexblades_curse",
                                "slayers_prey", "planar_warrior", "favored_foe", "unsettling_words") and not self._hostile(c, tgt):
            return f"Pick a foe, not {tgt['name']}."
        return None

    def _class_feature(self, c: dict, char, key: str, f: dict, tgt: Optional[dict], option, point) -> Optional[str]:
        """Plays a subclass or race feature of the bar (None: not one of these - abilities.py has it)."""
        name = c["name"]
        t = c.get("turn")
        done = self._sub_feature(c, char, key, f, tgt, option, point)       # subfeats.py
        if done is not None:
            return done
        if key in ("harness_cleric", "harness_paladin"):
            opts = [int(o["value"]) for o in F.harness_options(char)]
            lvl = int(option) if str(option or "").isdigit() and int(option) in opts else max(opts)
            used = char.d["slots_used"]
            used[str(lvl)] = max(0, int(used.get(str(lvl)) or 0) - 1)
            if not used[str(lvl)]:
                used.pop(str(lvl))
            char.save()
            return self._out(f"{name} harnesses divine power: a level {lvl} spell slot comes back")
        if key in ("turn_unholy", "turn_faithless"):
            kinds = ("fiend", "undead") if key == "turn_unholy" else ("fey", "fiend")
            near = [o for o in self._cf_hostiles(c, 30) if any(k in self._ctype(self._monster(o)) for k in kinds)]
            if not near:
                return self._out(f"{name} uses {f['name']}: no {' or '.join(kinds)} within 30 ft")
            return self._run_r(self._strike(c, f["name"], [o["id"] for o in near], mode="save",
                                            sv={"ab": "wis", "dc": self._cf_dc(char, "cha"), "half": False, "conds": ["Frightened"], "rounds": 10,
                                                "ends_on": ["damage"], "note": "turned: flees", "mods": {"turned": True}}, parts=[]))
        if key == "abjure_enemy":
            if any(k in self._ctype(self._monster(tgt)) for k in ("fiend", "undead")):
                self._effect_on(tgt, "Abjure Enemy (disadvantage)", [], None, None, None, None, name, {"save_dis": ["wis"], "once": True}, None, c["id"])
            return self._run_r(self._strike(c, "Abjure Enemy", [tgt["id"]], mode="save",
                                            sv={"ab": "wis", "dc": self._cf_dc(char, "cha"), "half": False, "conds": ["Frightened"], "rounds": 10,
                                                "mods": {"speed_set": 0}, "ends_on": ["damage"], "note": "speed 0",
                                                "on_save": {"rounds": 10, "mods": {"speed_mult": 0.5}}}, parts=[]))
        if key == "natures_wrath":
            ab = "str" if self._save_bonus(tgt, "str") >= self._save_bonus(tgt, "dex") else "dex"
            return self._run_r(self._strike(c, "Nature's Wrath", [tgt["id"]], mode="save",
                                            sv={"ab": ab, "dc": self._cf_dc(char, "cha"), "half": False, "conds": ["Restrained"], "repeat": "end",
                                                "rounds": 10}, parts=[]))
        if key in ("conquering_presence", "orders_demand", "fey_presence"):
            feet = 10 if key == "fey_presence" else 30
            near = self._cf_hostiles(c, feet)
            if not near:
                return self._out(f"{name} uses {f['name']}: no foe within {feet} ft")
            if key == "conquering_presence":
                sv = {"ab": "wis", "dc": self._cf_dc(char, "cha"), "half": False, "conds": ["Frightened"], "repeat": "end", "rounds": 10}
            else:
                cond = "Frightened" if key == "fey_presence" and option == "frightened" else "Charmed"
                sv = {"ab": "wis", "dc": self._cf_dc(char, "wis" if key == "orders_demand" else "cha"), "half": False, "conds": [cond],
                      "until": "caster_end_next"}
            return self._run_r(self._strike(c, f["name"], [o["id"] for o in near], mode="save", sv=sv, parts=[]))
        if key == "radiance_of_the_dawn":
            near = self._cf_hostiles(c, 30)
            lv = char.class_level("Cleric")
            if not near:
                return self._out(f"{name} uses Radiance of the Dawn: no foe within 30 ft")
            return self._run_r(self._strike(c, "Radiance of the Dawn", [o["id"] for o in near], mode="save",
                                            sv={"ab": "con", "dc": self._cf_dc(char, "wis"), "half": True}, parts=[[f"2d10+{lv}", "radiant"]]))
        if key == "twilight_sanctuary":
            self._effect_on(c, "Twilight Sanctuary", [], None, None, None, 10, name,
                            {"twilight": f"1d6+{char.class_level('Cleric')}", "aura_ft": 30,
                             **({"twilight_cover": True} if F.sub_at(char, "Cleric", "Twilight Domain", 17) else {})}, None, c["id"])    # Twilight Shroud
            return self._out(f"{name} fills the area with twilight: allies within 30 ft gain temporary hit points each turn")
        if key == "path_to_the_grave":
            self._effect_on(tgt, "Path to the Grave", [], None, None, None, None, name, {"vuln": list(M.TYPES), "ends_on": ["damage"]}, None,
                            c["id"], until={"end": c["id"], "skip": 1 if self.b.get("turn") == c["id"] else 0})
            return self._out(f"{name} curses {tgt['name']}: vulnerable to all the damage of the next hit")
        if key in ("war_priest", "war_magic"):
            return self._cf_weapon_strike(c, char, tgt, f["name"].replace(" attack", ""))
        if key == "horde_breaker":
            if t is not None:
                t["horde_breaker"] = True
            return self._cf_weapon_strike(c, char, tgt, "Horde Breaker")
        if key == "dread_ambusher":
            c["dread_attack"] = True
            return self._cf_weapon_strike(c, char, tgt, "Dread Ambusher")
        if key == "intimidating_presence":
            return self._run_r(self._strike(c, "Intimidating Presence", [tgt["id"]], mode="save",
                                            sv={"ab": "wis", "dc": self._cf_dc(char, "cha"), "half": False, "conds": ["Frightened"],
                                                "until": "caster_end_next"}, parts=[]))
        if key == "eagle_dash":
            EC.dash(t)
            return self._out(f"{name} dashes on eagle's wings")
        if key == "wholeness_of_body":
            n = 3 * char.class_level("Monk")
            self._heal(c, n)
            return self._out(f"{name} uses Wholeness of Body: +{n} HP")
        if key == "stillness_of_mind":
            had = [x for x in ("Charmed", "Frightened") if x in self._conds(c)]
            self._clear_conditions(c, had[:1])
            return self._out(f"{name} stills the mind" + (f": no longer {had[0].lower()}" if had else ""))
        if key in ("quickened_healing", "hand_of_healing"):
            target = tgt if key == "hand_of_healing" and tgt else c
            n = roll(F.martial_die(char) or "1d4") + (char.proficiency_bonus if key == "quickened_healing" else max(0, char.mod("wis")))
            self._heal(target, n)
            return self._out(f"{name} uses {f['name']}: {target['name']} +{n} HP")
        if key == "empty_body":
            self._effect_on(c, "Empty Body", ["Invisible"], None, None, None, 10, name, {"resist": NOT_FORCE}, None, c["id"])
            return self._out(f"{name} becomes invisible and resists all damage but force (Empty Body)")
        if key == "radiant_sun_bolt":
            self._pay_attack(c, F.extra_attacks(char), f["name"])
            return self._cf_spell_attack(c, char, tgt, "Radiant Sun Bolt", "dex", F.martial_die(char) or "1d4", "radiant", 30)
        if key == "luminous_arrow":
            return self._cf_spell_attack(c, char, tgt, "Luminous Arrow", "wis", "2d8" if char.class_level("Druid") >= 10 else "1d8", "radiant", 60)
        if key == "feinting_attack":
            self._effect_on(c, f"Feinting Attack ({tgt['name']})", [], None, None, None, None, name,
                            {"feint": tgt["id"], "feint_die": "1" + F.superiority_die(char)}, None, c["id"], until={"end": c["id"], "skip": 0})
            return self._out(f"{name} feints at {tgt['name']}: advantage on the next attack")
        if key == "fighting_spirit":
            lv = char.class_level("Fighter")
            n = 15 if lv >= 15 else 10 if lv >= 10 else 5
            self._effect_on(c, "Fighting Spirit", [], None, None, None, None, name, {"attacks_with": "adv"}, None, c["id"],
                            until={"end": c["id"], "skip": 0})
            self._give_temp(c, n)
            return self._out(f"{name} summons a fighting spirit: advantage on attacks this turn, {n} temporary HP")
        if key == "giants_might":
            lv = char.class_level("Fighter")
            die = "1d10" if lv >= 18 else "1d8" if lv >= 10 else "1d6"
            self._effect_on(c, "Giant's Might", [], None, None, None, 10, name, {"giants_might": die, "save_adv": ["str"], "check_adv": ["str"]},
                            None, c["id"])
            return self._out(f"{name} grows with Giant's Might (+{die} once a turn, advantage on Strength)")
        if key == "favored_foe":
            if c.get("concentrating"):
                self._drop_conc(c, "Favored Foe")
            c["concentrating"] = {"spell": "Favored Foe", "rounds": 10, "src": self._magic_source(c, {"classes": ["Ranger"]})}
            self._effect_on(tgt, "Favored Foe", [], None, None, None, 10, name, {"favored_by": c["id"]}, c["id"], c["id"])
            return self._out(f"{name} marks {tgt['name']} as a favored foe")
        if key == "slayers_prey":
            for o in self.b["combatants"]:
                for e in [e for e in o.get("effects") or [] if (e.get("mods") or {}).get("slayers_prey") == c["id"]]:
                    self._effect_off(o, e, "a new prey")
            self._effect_on(tgt, "Slayer's Prey", [], None, None, None, None, name, {"slayers_prey": c["id"]}, None, c["id"])
            return self._out(f"{name} names {tgt['name']} as its prey")
        if key == "planar_warrior":
            self._effect_on(c, "Planar Warrior", [], None, None, None, None, name, {"planar": tgt["id"]}, None, c["id"],
                            until={"end": c["id"], "skip": 0})
            return self._out(f"{name} draws on planar energy against {tgt['name']}")
        if key == "whirlwind_attack":
            near = [o for o in self._cf_hostiles(c, 5)]
            if not near:
                raise ServiceError("No foe within 5 ft.")
            w, atk = self._cf_weapon(c, char, near[0], ranged=False)
            return self._run_r(self._strike(c, f"{w['name']} (Whirlwind Attack)", [o["id"] for o in near], mode="attack", atk=atk,
                                            magical=atk.get("magical", False)))
        if key == "volley":
            w, atk = self._cf_weapon(c, char, tgt, ranged=True)
            ids = [tgt["id"]] + [o["id"] for o in self.b["combatants"] if o is not tgt and o is not c and o.get("pos") and tgt.get("pos")
                                 and self._hostile(c, o) and self._alive(o) and self._dist(o, tgt) <= 10]
            return self._run_r(self._strike(c, f"{w['name']} (Volley)", ids, mode="attack", atk=atk, magical=atk.get("magical", False)))
        if key == "hexblades_curse":
            self._effect_on(tgt, "Hexblade's Curse", [], None, None, None, 10, name, {"hex_curse": c["id"]}, None, c["id"])
            return self._out(f"{name} curses {tgt['name']} (+{char.proficiency_bonus} damage, critical hits on 19-20)")
        if key == "healing_light":
            target = tgt or c
            left = (F.per_left(f, char) or 0) + 1                  # one die was counted already
            n = max(1, min(int(option) if str(option or "").isdigit() else 1, max(1, char.mod("cha")), left))
            if n > 1:
                k = F.per_key(f, char)
                char.d["resources"][k] = int(char.d["resources"].get(k) or 0) + n - 1
                char.save()
            hp = roll(f"{n}d6")
            self._heal(target, hp)
            return self._out(f"{name} channels Healing Light: {target['name']} +{hp} HP ({n}d6)")
        if key == "tides_of_chaos":
            self._effect_on(c, "Tides of Chaos", [], None, None, None, None, name, {"attacks_with": "adv", "once": True}, None, c["id"])
            return self._out(f"{name} bends the tides of chaos: advantage on the next attack")
        if key == "flexible_casting":
            opt = str(option or F.flexible_options(char)[0]["value"])
            kind, _, n = opt.partition(":")
            n = int(n)
            used = char.d["slots_used"]
            if kind == "slot":
                cost = F.FLEX_COST[n]
                self._use_resource(c, "Sorcery Points", cost)
                used[str(n)] = max(0, int(used.get(str(n)) or 0) - 1)
                char.save()
                return self._out(f"{name} shapes {cost} sorcery points into a level {n} spell slot")
            used[str(n)] = int(used.get(str(n)) or 0) + 1
            char.d["resources"]["Sorcery Points"] = max(0, int(char.d["resources"].get("Sorcery Points") or 0) - n)
            char.save()
            return self._out(f"{name} turns a level {n} spell slot into {n} sorcery points")
        if key == "unsettling_words":
            die = F.bardic_die(char)
            self._effect_on(tgt, "Unsettling Words", [], None, None, None, None, name, {"save": f"-{die}", "once": True}, None, c["id"],
                            until={"start": c["id"]})
            return self._out(f"{name} unsettles {tgt['name']}: -{die} on its next saving throw")
        if key == "mantle_of_inspiration":
            lv = char.class_level("Bard")
            n = 14 if lv >= 15 else 11 if lv >= 10 else 8 if lv >= 5 else 5
            allies = sorted((o for o in self.b["combatants"] if o is not c and not self._hostile(c, o) and self._alive(o) and self._within(c, o, 60)),
                            key=lambda o: self._dist(c, o))[:max(1, char.mod("cha"))]
            for o in allies:
                self._give_temp(o, n)
            return self._out(f"{name} wraps allies in a mantle of inspiration: " + (", ".join(o["name"] for o in allies) or "nobody near")
                             + f" (+{n} temporary HP)")
        if key == "symbiotic_entity":
            n = 4 * char.class_level("Druid")
            self._give_temp(c, n)
            self._effect_on(c, "Symbiotic Entity", [], None, None, None, 100, name, {"symbiotic": True, "dmg": ("1d6", "necrotic"), "melee_only": True},
                            None, c["id"])
            return self._out(f"{name} awakens the spores: {n} temporary HP, +1d6 necrotic on melee weapon hits")
        if key == "starry_form":
            form = option if option in ("archer", "chalice", "dragon") else "archer"
            self._effect_on(c, f"Starry Form ({form.capitalize()})", [], None, None, None, 100, name,
                            {"starry": form, **({"resist": ["bludgeoning", "piercing", "slashing"]} if F.sub_at(char, "Druid", "Circle of Stars", 14) else {}),
                             **({"fly": 20} if form == "dragon" and F.sub_at(char, "Druid", "Circle of Stars", 10) else {})},      # Twinkling Constellations
                            None, c["id"])                      # Full of Stars
            line = self._out(f"{name} takes a starry form: the {form}")
            if form == "archer" and tgt is not None and tgt is not c and self._hostile(c, tgt) and tgt.get("pos") and c.get("pos") \
                    and self._dist(c, tgt) <= 60:               # "When you activate this form ... you can make a ranged spell attack": a target picked
                line += "; " + self._cf_spell_attack(c, char, tgt, "Luminous Arrow", "wis", "2d8" if char.class_level("Druid") >= 10 else "1d8", "radiant", 60)
            return line
        if key == "hidden_step":
            self._effect_on(c, "Hidden Step", ["Invisible"], None, None, None, None, name, {"ends_on": ["attack", "cast"]}, None, c["id"],
                            until={"start": c["id"]})
            return self._out(f"{name} steps out of sight (invisible)")
        if key in ("shifting", "adrenaline_rush"):
            n = (2 * char.proficiency_bonus if F.mpmm(char) else char.total_level + char.mod("con")) if key == "shifting" else char.proficiency_bonus
            self._give_temp(c, max(1, n))
            if key == "adrenaline_rush":
                EC.dash(t)
            return self._out(f"{name} uses {f['name']}: {max(1, n)} temporary HP" + (" and dashes" if key == "adrenaline_rush" else ""))
        if key == "hungry_jaws":
            mod = char.mod("str")
            atk = {"bonus": char.proficiency_bonus + mod, "n": 1, "melee": True, "weapon": True, "reach": 5, "str_based": True,
                   "parts": [[f"1d6{mod:+d}" if mod else "1d6", "piercing"]], "props": []}
            atk = self._check_reach(c, tgt, atk)
            R = self._strike(c, "Hungry Jaws", [tgt["id"]], mode="attack", atk=atk, magical=False)
            out = self._run_r(R)
            if R.get("hits"):
                n = max(1, char.proficiency_bonus if F.mpmm(char) else char.mod("con"))
                self._give_temp(c, n)
                out += f"; {name} gains {n} temporary HP"
            return out
        if key == "celestial_revelation":
            kinds = F.revelation_kinds(char)
            kind = option if option in kinds else kinds[0]
            n = char.proficiency_bonus if F.mpmm(char) else char.total_level
            dtype = "necrotic" if kind == "Necrotic Shroud" else "radiant"
            mods = {"revelation": [n, dtype]}
            if kind in ("Heavenly Wings", "Radiant Soul"):
                mods["fly"] = 30
            self._effect_on(c, kind, [], None, None, None, 10, name, mods, None, c["id"])
            line = f"{name} reveals its celestial nature: {kind} (+{n} {dtype} once a turn)"
            if kind == "Necrotic Shroud":
                near = self._cf_hostiles(c, 10)
                if near:
                    self._say(line)
                    return self._run_r(self._strike(c, "Necrotic Shroud", [o["id"] for o in near], mode="save",
                                                    sv={"ab": "cha", "dc": self._cf_dc(char, "cha"), "half": False, "conds": ["Frightened"],
                                                        "until": "caster_end_next"}, parts=[]))
            return self._out(line)
        if key == "draconic_cry":
            near = self._cf_hostiles(c, 10)
            for o in near:
                self._effect_on(o, "Draconic Cry", [], None, None, None, None, name, {"attacks_against": "adv"}, None, c["id"],
                                until={"start": c["id"]})
            return self._out(f"{name} lets out a draconic cry: " + (", ".join(o["name"] for o in near) or "no foe within 10 ft"))
        if key == "destructive_wrath":
            self._effect_on(c, "Destructive Wrath", [], None, None, None, None, name, {"max_types": ["lightning", "thunder"]}, None, c["id"],
                            until={"end": c["id"], "skip": 0})
            return self._out(f"{name} channels destructive wrath: the next lightning or thunder spell deals maximum damage")
        if key == "abjure_extraplanar":
            kinds = ("aberration", "celestial", "elemental", "fey", "fiend")
            near = [o for o in self._cf_hostiles(c, 30) if any(k in self._ctype(self._monster(o)) for k in kinds)]
            if not near:
                return self._out(f"{name} uses Abjure the Extraplanar: no extraplanar creature within 30 ft")
            return self._run_r(self._strike(c, f["name"], [o["id"] for o in near], mode="save",
                                            sv={"ab": "wis", "dc": self._cf_dc(char, "cha"), "half": False, "conds": ["Frightened"], "rounds": 10,
                                                "ends_on": ["damage"], "note": "turned: flees", "mods": {"turned": True}}, parts=[]))
        if key == "insightful_fighting":
            mine, theirs = self._check(c, "Insight"), self._check(tgt, "Deception")
            if mine >= theirs:
                self._effect_on(c, f"Insightful Fighting ({tgt['name']})", [], None, None, None, 10, name, {"insight_vs": tgt["id"]}, None, c["id"])
            return self._out(f"{name} reads {tgt['name']} (Insight {mine} vs Deception {theirs}): "
                             + ("Sneak Attack works against it for a minute" if mine >= theirs else "no opening"))
        if key in ("psychic_blade", "psychic_blade_bonus"):
            ab = "dex" if char.mod("dex") >= char.mod("str") else "str"
            mod = char.mod(ab)
            die = "1d6" if key == "psychic_blade" else "1d4"
            atk = {"bonus": char.proficiency_bonus + mod, "n": 1, "melee": True, "weapon": True, "finesse": True, "thrown": True, "reach": 5,
                   "normal": 60, "long": 60, "props": ["finesse", "thrown"], "ability": ab, "psychic_blade": True, "parts": [[f"{die}{mod:+d}" if mod else die, "psychic"]]}
            atk = self._check_reach(c, tgt, atk)
            if key == "psychic_blade":
                self._pay_attack(c, F.extra_attacks(char), f["name"])
            return self._run_r(self._strike(c, f["name"], [tgt["id"]], mode="attack", atk=atk, magical=True))
        if key == "shell_defense":
            shell = next((e for e in c.get("effects") or [] if e["name"] == "Shell Defense"), None)
            if shell:
                self._effect_off(c, shell, "comes out of its shell")
                self._cond(c, "Prone", False)
                return self._out(f"{name} comes out of its shell")
            self._effect_on(c, "Shell Defense", ["Prone"], None, None, None, None, name,
                            {"ac": 4, "save_adv": ["str", "con"], "save_dis": ["dex"], "speed_set": 0}, None, c["id"])
            return self._out(f"{name} withdraws into its shell (+4 AC)")
        if key == "chromatic_warding":
            dtype = ((char.race_data() or {}).get("resist") or ["fire"])[-1]
            self._effect_on(c, "Chromatic Warding", [], None, None, None, 10, name, {"immune": [dtype]}, None, c["id"])
            return self._out(f"{name} is immune to {dtype} damage for a minute (Chromatic Warding)")
        if key == "spirit_totem":
            n = 5 + char.class_level("Druid")
            allies = [o for o in self.b["combatants"] if not self._hostile(c, o) and self._alive(o) and self._within(c, o, 30)]
            for o in allies:
                self._give_temp(o, n)
            self._effect_on(c, "Spirit Totem (Bear)", [], None, None, None, 10, name, {"aura_ft": 30, "check_adv": ["str"], "save_adv": ["str"]},
                            None, c["id"])
            return self._out(f"{name} summons a bear spirit: {len(allies)} creature(s) gain {n} temporary HP")
        if key == "balm_of_summer":
            target = tgt or c
            left = (F.per_left(f, char) or 0) + 1
            n = max(1, min(int(option) if str(option or "").isdigit() else 1, max(1, char.class_level("Druid") // 2), left))
            if n > 1:
                k = F.per_key(f, char)
                char.d["resources"][k] = int(char.d["resources"].get(k) or 0) + n - 1
                char.save()
            hp = roll(f"{n}d6")
            self._heal(target, hp)
            self._give_temp(target, n)
            return self._out(f"{name} soothes {target['name']} with the Balm of the Summer Court: +{hp} HP, {n} temporary HP")
        if key == "dragon_wings":
            self._effect_on(c, "Dragon Wings", [], None, None, None, None, name, {"fly": char.speed}, None, c["id"])
            return self._out(f"{name} spreads dragon wings (fly {char.speed} ft)")
        if key == "natures_veil":
            self._effect_on(c, "Nature's Veil", ["Invisible"], None, None, None, None, name, None, None, c["id"], until={"start": c["id"]})
            return self._out(f"{name} vanishes behind nature's veil (invisible)")
        if key == "zealous_presence":
            allies = sorted((o for o in self.b["combatants"] if not self._hostile(c, o) and self._alive(o) and self._within(c, o, 60)),
                            key=lambda o: self._dist(c, o))[:10]
            for o in allies:
                self._effect_on(o, "Zealous Presence", [], None, None, None, None, name, {"attacks_with": "adv", "save_adv": ["all"]}, None,
                                c["id"], until={"start": c["id"]})
            return self._out(f"{name} unleashes a battle cry: {len(allies)} allies have advantage on attacks and saves")
        if key in ("beast_bite", "beast_claws", "beast_tail", "thunder_gauntlets", "lightning_launcher"):
            beast = key.startswith("beast_")
            ab = "str" if beast else "int"
            mod = char.mod(ab)
            die, dtype, reach = {"beast_bite": ("1d8", "piercing", 5), "beast_claws": ("1d6", "slashing", 5), "beast_tail": ("1d8", "piercing", 10),
                                 "thunder_gauntlets": ("1d8", "thunder", 5), "lightning_launcher": ("1d6", "lightning", 5)}[key]
            ranged = key == "lightning_launcher"
            atk = {"bonus": char.proficiency_bonus + mod, "n": 1, "melee": not ranged, "weapon": True, "reach": reach, "str_based": beast,
                   "magical": not beast or char.class_level("Barbarian") >= 6, "props": [], "ability": ab,
                   "normal": 90 if ranged else None, "long": 300 if ranged else None, "parts": [[f"{die}{mod:+d}" if mod else die, dtype]]}
            if ranged and self._cf_turn_free(c, "launcher"):
                atk["parts"].append(["1d6", "lightning"])
                self._once_per_turn(c, "launcher")
            atk = self._check_reach(c, tgt, atk)
            self._pay_attack(c, F.extra_attacks(char), f["name"])
            if key == "beast_claws" and t is not None and self._economy_on() and self._once_per_turn(c, "beast_claws"):
                t["attacks"] = t.get("attacks", 0) + 1            # one more claw attack with this Attack action
            on_hit = {"name": "Thunder Gauntlets", "mods": {"protector": c["id"]}, "until": {"start": c["id"]}} \
                if key == "thunder_gauntlets" else None
            R = self._strike(c, f["name"].replace("Form of the Beast: ", ""), [tgt["id"]], mode="attack", atk=atk, magical=atk["magical"], on_hit=on_hit)
            out = self._run_r(R)
            if key == "beast_bite" and R.get("hits") and 0 < self._hp_of(c) < self._max_hp(c) // 2 and self._once_per_turn(c, "beast_bite"):
                self._heal(c, char.proficiency_bonus)
                out += f"; {name} regains {char.proficiency_bonus} HP"
            return out
        if key in ("nimble_escape", "aggressive", "vanish"):
            if key == "aggressive":
                EC.dash(t)
                return self._out(f"{name} charges forward (Aggressive)")
            if key == "nimble_escape" and option != "hide":
                if t is not None:
                    t["disengaged"] = True
                return self._out(f"{name} slips away (Nimble Escape: Disengage)")
            return self._out(self._hide_now(c))
        if key == "cleansing_touch":
            target = tgt or c
            def foes(e):                                    # a spell a foe put on it (Hold Person, Bestow Curse...)
                src = self._find_or_none(e.get("conc_by") if e.get("conc_by") is not None else e.get("source_id"))
                return src is not None and src is not target and self._hostile(src, target)
            spell = next((e for e in target.get("effects") or [] if foes(e)), None)
            if spell is None:
                return self._out(f"{name} touches {target['name']}: no spell to end")
            self._effect_off(target, spell, "Cleansing Touch")
            return self._out(f"{name} ends {spell['name']} on {target['name']} (Cleansing Touch)")
        if key in ("companion", "wildfire_spirit"):
            mid = "Wildfire Spirit|TCE" if key == "wildfire_spirit" else (option if option in F.companions(char) else F.companions(char)[0])
            for old in [o for o in self.b["combatants"] if o.get("summoned_by") == c["id"] and SS.owner_class(bestiary.get(o.get("monster") or "") or {})
                        and (o.get("monster") == "Wildfire Spirit|TCE") == (key == "wildfire_spirit")]:
                self._vfx_unsummon(old)                         # one companion at a time: the new one replaces the old
                self.remove(old["id"])
            m = bestiary.get(mid)
            ctx = self._summoner_ctx(c, cls=SS.owner_class(m))
            hp = SS.hp(m, ctx) or m["hp"] or 1
            pet = self._new("enemy", self._label(m["name"], False), hp, hp, SS.fill(mid, ctx)["ac"], ability_mod(m, "dex"), monster=mid, xp=0,
                            span=SPANS.get(m.get("size"), 1), faction=self._side(c), summoned_by=c["id"], tiny=(m.get("size") or "").startswith("Tiny"))
            pet["summon"] = ctx
            self._subd_companion(c, pet, ctx)                   # a Large drake, the drakewarden's resistance (subfeats_d.py)
            self._add(pet, self.b["combatants"].index(c) + 1)
            if c.get("pos"):
                spot = self._free_near(pet, *c["pos"])
                if spot:
                    pet["pos"] = spot
            self._vfx("summon", id=pet["id"], type=str(m.get("type") or "").lower(), src=self._magic_source(c, {"classes": [SS.owner_class(m)]}), tier=1)
            line = self._out(f"{name} calls {pet['name']} ({hp} HP)")
            if key == "wildfire_spirit" and pet.get("pos"):
                near = [o["id"] for o in self.b["combatants"] if o is not c and o is not pet and o.get("pos") and self._alive(o)
                        and self._dist(o, pet) <= 10]
                if near:
                    return self._run_r(self._strike(c, "Summon Wildfire Spirit", near, mode="save",
                                                    sv={"ab": "dex", "dc": self._cf_dc(char, "wis"), "half": False}, parts=[["2d6", "fire"]]))
            return line
        if key == "flurry" and F.sub_at(char, "Monk", "Way of the Drunken Master", 3) and t is not None:
            t["disengaged"] = True                              # Drunken Technique: Disengage and +10 ft with the flurry
            t["move"] = t.get("move", 0) + 10
            return None
        if key == "emboldening_bond":
            allies = sorted((o for o in self.b["combatants"] if not self._hostile(c, o) and self._alive(o) and self._within(c, o, 30)),
                            key=lambda o: (o is not c, self._dist(c, o)))[:max(2, char.proficiency_bonus)]
            for o in allies:
                self._effect_on(o, "Emboldening Bond", [], None, None, None, 100, name, {"bond": True}, None, c["id"])
            return self._out(f"{name} binds {', '.join(o['name'] for o in allies)} together (Emboldening Bond)")
        if key == "quivering_palm":
            eff = next(e for e in tgt.get("effects") or [] if (e.get("mods") or {}).get("quivering") == c["id"])
            self._effect_off(tgt, eff, "Quivering Palm")
            return self._run_r(self._strike(c, "Quivering Palm", [tgt["id"]], mode="save",
                                            sv={"ab": "con", "dc": F.ki_dc(char), "half": False, "drop_to_0": True}, parts=[["10d10", "necrotic"]]))
        if key in ("water_whip", "unbroken_air"):
            whip = key == "water_whip"
            return self._run_r(self._strike(c, f["name"], [tgt["id"]], mode="save", magical=True,
                                            sv={"ab": "dex" if whip else "str", "dc": F.ki_dc(char), "half": True, "prone": True,
                                                **({} if whip else {"push": 20})}, parts=[["3d10", "bludgeoning"]]))
        if key == "fangs_fire_snake":
            self._effect_on(c, "Fangs of the Fire Snake", [], None, None, None, None, name, {"fangs": True}, None, c["id"],
                            until={"end": c["id"], "skip": 0})
            return self._out(f"{name}'s fists burst into flame: unarmed strikes reach 10 ft farther and burn")
        if key == "astral_arms":
            self._effect_on(c, "Arms of the Astral Self", [], None, None, None, 100, name, {"astral_arms": True}, None, c["id"])
            near = self._cf_hostiles(c, 10)
            line = self._out(f"{name} summons the arms of the astral self")
            if near:
                die = F.martial_die(char) or "1d4"
                n = int(die.split("d")[0] or 1) * 2
                return self._run_r(self._strike(c, "Arms of the Astral Self", [o["id"] for o in near], mode="save", magical=True,
                                                sv={"ab": "dex", "dc": F.ki_dc(char), "half": False}, parts=[[f"{n}d{die.split('d')[1]}", "force"]]))
            return line
        if key == "evasive_footwork":
            n = roll("1" + F.superiority_die(char))
            self._effect_on(c, "Evasive Footwork", [], None, None, None, None, name, {"ac": n}, None, c["id"], until={"end": c["id"], "skip": 0})
            return self._out(f"{name} moves evasively: +{n} AC this turn")
        if key == "divine_sense":
            found = [o for o in self.b["combatants"] if o is not c and o.get("pos") and c.get("pos") and self._dist(c, o) <= 60
                     and any(k in self._ctype(self._monster(o)) for k in ("celestial", "fiend", "undead"))
                     and self._cover_between(c, o) < V.TOTAL]
            return self._out(f"{name}'s Divine Sense: " + (", ".join(f"{o['name']} ({self._ctype(self._monster(o)).split()[0]}) at "
                                                                    f"{self._tile_label(o['pos'])}" for o in found)
                                                           or "no celestial, fiend or undead within 60 ft"))
        if key == "divine_intervention":
            lv = char.class_level("Cleric")
            r = self.rng.randint(1, 100)
            ok = lv >= 20 or r <= lv
            if not ok:
                char.d["resources"]["Divine Intervention"] = 0     # a failure doesn't spend it (only a success waits 7 days)
                char.save()
            return self._out(f"{name} implores its deity (d100 {r} vs {lv}): " + ("the deity intervenes - the DM decides how" if ok else "no answer"))
        if key == "ki_fueled_attack":
            w = next((a for a in char.attacks() if "unarmed" in (a.get("props") or [])), None)
            atk = self._check_reach(c, tgt, self._weapon_atk(c, w))
            return self._run_r(self._strike(c, "Ki-Fueled Attack", [tgt["id"]], mode="attack", atk=atk, magical=atk.get("magical", False)))
        if key == "chef_treat":
            self._give_temp(c, char.proficiency_bonus)
            return self._out(f"{name} eats a treat: {char.proficiency_bonus} temporary HP")
        if key == "grappling_strike":
            n = roll("1" + F.superiority_die(char))
            mine = self._check(c, "Athletics") + n
            theirs = max(self._check(tgt, "Athletics"), self._check(tgt, "Acrobatics")) if self._can_act(tgt) else 0
            if mine >= theirs:
                self._effect_on(tgt, f"Grappled by {name}", ["Grappled"], None, None, None, None, name, {"grappler": c["id"]}, None, c["id"])
            return self._out(f"{name} grapples {tgt['name']} (Athletics {mine} incl. +{n} vs {theirs}): " + ("held" if mine >= theirs else "slips free"))
        if key == "bait_and_switch":
            n = roll("1" + F.superiority_die(char))
            if c.get("pos") and tgt.get("pos"):
                a, b_ = list(c["pos"]), list(tgt["pos"])
                c["pos"], tgt["pos"] = b_, a
                self._vfx("blink", id=c["id"], at=a, to=b_)
                self._vfx("blink", id=tgt["id"], at=b_, to=a)
                if c.get("turn") is not None:
                    c["turn"]["move"] = max(0, c["turn"].get("move", 0) - 5)
            self._effect_on(tgt, "Bait and Switch", [], None, None, None, None, name, {"ac": n}, None, c["id"], until={"start": c["id"]})
            return self._out(f"{name} switches places with {tgt['name']}: +{n} AC for {tgt['name']}")
        if key == "maddening_hex":
            cursed = self._cf_cursed(c, tgt)
            n = max(1, char.mod("cha"))
            hit = [cursed] + [o for o in self.b["combatants"] if o is not cursed and o.get("pos") and cursed.get("pos") and self._hostile(c, o)
                              and self._alive(o) and self._dist(o, cursed) <= 5]
            for o in hit:
                self._say("Maddening Hex: " + self._deal(o, [[n, "psychic"]], by=c, label="Maddening Hex"))
            return self._out(f"{name} unleashes a maddening hex on {len(hit)} creature(s)")
        if key == "relentless_hex":
            spot = self._cf_teleport(c, point)
            return self._out(f"{name} follows its curse to {self._tile_label(spot)}")
        if key == "countercharm":
            allies = [o for o in self.b["combatants"] if not self._hostile(c, o) and self._alive(o) and self._within(c, o, 30)]
            for o in allies:
                self._effect_on(o, "Countercharm", [], None, None, None, None, name, {"cond_save_adv": ["Frightened", "Charmed"]}, None, c["id"],
                                until={"end": c["id"], "skip": 1 if self.b.get("turn") == c["id"] else 0})
            return self._out(f"{name} plays a countercharm: {len(allies)} creature(s) steeled against fear and charms")
        if key in ("cloak_of_flies", "hill_rune", "frost_rune", "storm_rune"):
            mods = {"cloak_of_flies": {"flies": max(0, char.mod("cha"))}, "hill_rune": {"resist": ["bludgeoning", "piercing", "slashing"]},
                    "frost_rune": {"frost_rune": 2}, "storm_rune": {"storm_rune": True}}[key]
            rounds = {"cloak_of_flies": None, "hill_rune": 10, "frost_rune": 100, "storm_rune": 10}[key]
            self._effect_on(c, f["name"], [], None, None, None, rounds, name, mods, None, c["id"])
            return self._out(f"{name} invokes the {f['name']}")
        if key == "searing_sunburst":
            extra = min(3, int(option) if str(option or "").isdigit() else 0, self._resource_left(c, "Ki Points"))
            if extra:
                self._use_resource(c, "Ki Points", extra)
            aim = point or self.b.get("aim")
            tiles = G.area_for(f["area"], c["pos"], c.get("span") or 1, tuple(aim) if aim else None, *self._bounds())
            parts = [[f"{2 + 2 * extra}d6", "radiant"]]
            ids = [o["id"] for o in G.creatures_in(tiles, self.b["combatants"]) if not self._is_out(o)]
            self._area_vfx(c, tiles, parts, "sphere", aim)
            return self._run_r(self._strike(c, "Searing Sunburst", ids, mode="save", magical=True, parts=parts,
                                            sv={"ab": "con", "dc": F.ki_dc(char), "half": False}))
        if key in ("invoke_duplicity", "mantle_of_majesty"):
            if c.get("concentrating"):
                self._drop_conc(c, f["name"])
            c["concentrating"] = {"spell": f["name"], "rounds": 10, "src": self._magic_source(c, {"classes": ["Cleric" if key == "invoke_duplicity" else "Bard"]})}
            mod = {"invoke_duplicity": {"duplicity": True}, "mantle_of_majesty": {"majesty_mantle": True}}[key]
            self._effect_on(c, f["name"], [], None, None, None, 10, name, mod, c["id"], c["id"])
            if key == "invoke_duplicity":                       # the illusion: a token that can't be hurt, moved with a bonus action
                sp = {"name": "Invoke Duplicity", "duration": "Concentration, up to 1 minute", "level": 1, "classes": ["Cleric"]}
                tok = self._conjure_token(c, sp, {"name": "Duplicate", "move": 30}, {"point": point}, [], c["id"])
                self._subc_more_duplicates(c, char, sp, tok)        # Improved Duplicity: four of them (subfeats_c.py)
                return self._out(f"{name} invokes a duplicate at {self._tile_label(tok['pos']) if tok.get('pos') else 'its side'}")
            return self._out(f"{name} uses {f['name']}: a fey majesty")
        if key == "move_duplicate":
            tok = self._cf_duplicate(c, point)
            self._move_token(tok, point)
            return self._out(f"{name} moves its duplicate to {self._tile_label(tok['pos'])}")
        if key == "majestic_command":
            cmd = option if option in ("grovel", "halt", "flee") else "grovel"
            sv = {"grovel": {"conds": ["Prone"]}, "halt": {"mods": {"speed_set": 0}, "note": "halts"},
                  "flee": {"conds": ["Frightened"], "note": "flees"}}[cmd]
            if "Charmed" in self._conds(tgt):                 # charmed: it fails
                self._effect_on(tgt, f"Command ({cmd})", sv.get("conds") or [], None, None, None, None, name, sv.get("mods"), None, c["id"],
                                until={"end": tgt["id"], "skip": 1 if self.b.get("turn") == tgt["id"] else 0})
                return self._out(f"{name} commands the charmed {tgt['name']}: {cmd}")
            return self._run_r(self._strike(c, f"Command ({cmd})", [tgt["id"]], mode="save", magical=True, spell=True, parts=[],
                                            sv=dict(sv, ab="wis", dc=self._spell_dc(c), half=False, until="target_end_next")))
        if key == "unbreakable_majesty":
            self._effect_on(c, "Unbreakable Majesty", [], None, None, None, 10, name, {"majesty": self._spell_dc(c)}, None, c["id"])
            return self._out(f"{name} takes on an unbreakable majesty")
        if key == "unwavering_strike":
            w, atk = self._cf_weapon(c, char, tgt, ranged=False)
            atk["adv"] = "adv"
            atk["parts"] = list(atk["parts"]) + [[char.class_level("Fighter") // 2, atk["parts"][0][1]]]
            c.pop("mark_strike", None)
            return self._run_r(self._strike(c, f"{w['name']} (Unwavering Mark)", [tgt["id"]], mode="attack", atk=atk,
                                            magical=atk.get("magical", False)))
        if key == "corona_of_light":
            self._effect_on(c, "Corona of Light", [], None, None, None, 10, name, {"corona": True}, None, c["id"])
            return self._out(f"{name} blazes with a corona of light: foes have disadvantage on saves against its fire and radiant spells")
        if key == "steps_of_night":
            self._effect_on(c, "Steps of Night", [], None, None, None, 10, name, {"fly": char.speed}, None, c["id"])
            return self._out(f"{name} walks the night sky (fly {char.speed} ft)")
        if key == "charm_animals":
            near = [o for o in self._cf_hostiles(c, 30) if any(k in self._ctype(self._monster(o)) for k in ("beast", "plant"))]
            if not near:
                return self._out(f"{name} calls to nature: no beast or plant within 30 ft")
            return self._run_r(self._strike(c, f["name"], [o["id"] for o in near], mode="save", parts=[],
                                            sv={"ab": "wis", "dc": self._cf_dc(char, "wis"), "half": False, "conds": ["Charmed"], "rounds": 10,
                                                "ends_on": ["damage"]}))
        if key in ("tentacle", "tentacle_strike"):
            if key == "tentacle":
                self._effect_on(c, "Tentacle of the Deeps", [], None, None, None, 10, name, {"tentacle": True}, None, c["id"])
            dice = "2d8" if char.class_level("Warlock") >= 10 else "1d8"
            mod = char.mod("cha")
            atk = {"bonus": char.proficiency_bonus + mod, "n": 1, "melee": True, "spell": True, "reach": 60, "parts": [[dice, "cold"]]}
            return self._run_r(self._strike(c, "Tentacle of the Deeps", [tgt["id"]], mode="attack", atk=atk, magical=True, spell=True,
                                            on_hit={"name": "Tentacle of the Deeps", "mods": {"speed": -10}, "until": {"start": c["id"]}}))
        if key == "elemental_gift":
            self._effect_on(c, "Elemental Gift", [], None, None, None, 100, name, {"fly": 30}, None, c["id"])
            return self._out(f"{name} takes to the air (fly 30 ft)")
        if key == "hidden_paths":
            spot = self._cf_teleport(c, point)
            return self._out(f"{name} walks a hidden path to {self._tile_label(spot)}")
        if key == "paladin_capstone":
            kind = F.CAPSTONES[(char.class_entry("Paladin") or {}).get("subclass")]
            mods = {"Holy Nimbus": {"nimbus": 10}, "Avenging Angel": {"fly": 60, "menace": self._cf_dc(char, "cha")},
                    "Elder Champion": {"regen": "10"}, "Invincible Conqueror": {"resist": list(M.TYPES), "crit": 19},
                    "Living Legend": {"legend": True, "check_adv": ["cha"]}}[kind]
            self._effect_on(c, kind, [], None, None, None, 10, name, mods, None, c["id"])
            return self._out(f"{name} takes on the {kind} for a minute")
        if key == "master_of_tactics":
            self._effect_on(tgt, f"Helped against ({name})", [], None, None, None, None, name, {"attacks_against": "adv", "once": True}, None,
                            c["id"], until={"start": c["id"]})
            return self._out(f"{name} points out an opening: the next attack on {tgt['name']} has advantage")
        if key == "unearthly_recovery":
            n = self._max_hp(c) // 2
            self._heal(c, n)
            return self._out(f"{name} recovers: +{n} HP (Unearthly Recovery)")
        if key == "umbral_form":
            self._effect_on(c, "Umbral Form", [], None, None, None, 10, name,
                            {"resist": [t for t in M.TYPES if t not in ("force", "radiant")]}, None, c["id"])
            return self._out(f"{name} takes an umbral form (resists all damage but force and radiant)")
        if key == "draconic_presence":
            near = self._cf_hostiles(c, 60)
            if not near:
                return self._out(f"{name} radiates draconic presence: no foe within 60 ft")
            cond = "Charmed" if option == "awe" else "Frightened"
            return self._run_r(self._strike(c, f"Draconic Presence ({cond.lower()})", [o["id"] for o in near], mode="save", magical=True,
                                            sv={"ab": "wis", "dc": self._spell_dc(c), "half": False, "conds": [cond], "rounds": 10}, parts=[]))
        if key == "kensei_shot":
            self._effect_on(c, "Kensei's Shot", [], None, None, None, None, name, {"dmg": ("1d4", ""), "ranged_only": True}, None, c["id"],
                            until={"end": c["id"], "skip": 0})
            return self._out(f"{name} steadies the shot: +1d4 on ranged weapon hits this turn")
        if key == "gem_flight":
            self._effect_on(c, "Gem Flight", [], None, None, None, 10, name, {"fly": char.speed}, None, c["id"])
            return self._out(f"{name} takes wing (fly {char.speed} ft)")
        if key == "metallic_breath":
            near = [o for o in self._cf_hostiles(c, 15)]
            rep = option == "repulsion"
            if not near:
                return self._out(f"{name} exhales {'repulsion' if rep else 'enervating'} breath: nobody within 15 ft")
            sv = {"ab": "str", "push": 20, "prone": True} if rep else {"ab": "con", "conds": ["Incapacitated"], "until": "caster_start"}
            return self._run_r(self._strike(c, "Metallic Breath Weapon", [o["id"] for o in near], mode="save", magical=True,
                                            sv=dict(sv, dc=8 + char.proficiency_bonus + char.mod("con"), half=False), parts=[]))
        if key in ("goring_rush", "hammering_horns"):
            if key == "hammering_horns":
                res = self._saving_throw(tgt, "str", self._cf_dc(char, "str"), label="Hammering Horns")
                if not res["ok"]:
                    self._push(tgt, c, 10)
                return self._out(f"{name} butts {tgt['name']}: " + ("pushed 10 ft" if not res["ok"] else "it holds its ground"))
            mod = char.mod("str")
            atk = self._check_reach(c, tgt, {"bonus": char.proficiency_bonus + mod, "n": 1, "melee": True, "weapon": True, "reach": 5,
                                             "str_based": True, "props": [], "parts": [[f"1d6{mod:+d}" if mod else "1d6", "piercing"]]})
            return self._run_r(self._strike(c, "Goring Rush (horns)", [tgt["id"]], mode="attack", atk=atk))
        if key in ("fey_step", "shadow_step", "benign_transposition", "rabbit_hop", "raven_queen"):
            spot = self._cf_teleport(c, point)
            if key == "raven_queen" and char.total_level >= 3:
                self._effect_on(c, "Blessing of the Raven Queen", [], None, None, None, None, name, {"resist": list(M.TYPES)}, None, c["id"],
                                until={"start": c["id"]})
            if key == "shadow_step":
                self._effect_on(c, "Shadow Step", [], None, None, None, None, name, {"attacks_with": "adv", "once": True}, None, c["id"],
                                until={"end": c["id"], "skip": 0})
            return self._out(f"{name} uses {f['name']}: teleports to {self._tile_label(spot)}")
        if key == "quick_toss":
            ws = [w for w in char.attacks() if "thrown" in (w.get("props") or [])]
            if not ws:
                raise ServiceError("No thrown weapon to draw.")
            w = max(ws, key=lambda x: x["attack"])
            atk = self._feat_attack(c, w, self._check_reach(c, tgt, self._weapon_atk(c, w)))
            atk["parts"] = list(atk["parts"]) + [["1" + F.superiority_die(char), atk["parts"][0][1]]]
            return self._run_r(self._strike(c, f"{w['name']} (Quick Toss)", [tgt["id"]], mode="attack", atk=atk, magical=atk.get("magical", False)))
        if key == "hypnotic_gaze":
            return self._run_r(self._strike(c, "Hypnotic Gaze", [tgt["id"]], mode="save",
                                            sv={"ab": "wis", "dc": self._cf_dc(char, "int"), "half": False, "conds": ["Charmed", "Incapacitated"],
                                                "mods": {"speed_set": 0}, "until": "caster_end_next"}, parts=[]))
        if key == "battle_magic":
            return self._cf_weapon_strike(c, char, tgt, "Battle Magic")
        if key == "balm_of_peace":
            healed = []
            for o in self.b["combatants"]:
                if o is not c and not self._hostile(c, o) and self._alive(o) and self._within(c, o, 5):
                    n = max(1, roll("2d6") + char.mod("wis"))
                    self._heal(o, n)
                    healed.append(f"{o['name']} +{n}")
            return self._out(f"{name} spreads the Balm of Peace: " + (", ".join(healed) or "nobody within 5 ft"))
        if key == "storm_aura":
            lv = char.class_level("Barbarian")
            env = CF.is_on(char, "storm_aura") or "Desert"
            near = [o for o in self.b["combatants"] if o is not c and o.get("pos") and self._alive(o) and self._within(c, o, 10)]
            step = 6 if lv >= 20 else 5 if lv >= 15 else 4 if lv >= 10 else 3 if lv >= 5 else 2
            if env == "Desert":
                foes = [o for o in near if self._hostile(c, o)]
                for o in foes:
                    self._say(self._deal(o, [[step, "fire"]], by=c, label="Storm Aura (Desert)"))
                return self._out(f"{name}'s desert storm scorches {len(foes)} creature(s)")
            if env == "Tundra":
                allies = [o for o in near if not self._hostile(c, o)] + [c]
                for o in allies:
                    self._give_temp(o, step)
                return self._out(f"{name}'s tundra storm: {', '.join(o['name'] for o in allies)} gain {step} temporary HP")
            if not tgt or tgt is c or not self._hostile(c, tgt):
                raise ServiceError("Pick a foe in your aura.")
            dice = f"{lv // 5}d6" if lv >= 10 else "1d6"            # 2d6 at 10th level, 3d6 at 15th, 4d6 at 20th
            return self._run_r(self._strike(c, "Storm Aura (Sea)", [tgt["id"]], mode="save",
                                            sv={"ab": "dex", "dc": self._cf_dc(char, "con"), "half": True}, parts=[[dice, "lightning"]]))
        if key == "inspiring_leader":
            n = max(1, char.total_level + char.mod("cha"))
            allies = sorted((o for o in self.b["combatants"] if not self._hostile(c, o) and self._alive(o) and self._within(c, o, 30)),
                            key=lambda o: (o is not c, self._dist(c, o)))[:6]
            for o in allies:
                self._give_temp(o, n)
            return self._out(f"{name} inspires {', '.join(o['name'] for o in allies)}: {n} temporary HP each")
        if key == "rally":
            target = tgt if tgt and not self._hostile(c, tgt) else c
            n = max(1, roll("1" + F.superiority_die(char)) + char.mod("cha"))
            self._give_temp(target, n)
            return self._out(f"{name} rallies {target['name']}: {n} temporary HP")
        if key == "commanders_strike":
            if not tgt or tgt is c or self._hostile(c, tgt):
                raise ServiceError("Pick an ally to strike.")
            self._pay_attack(c, F.extra_attacks(char), f["name"])
            self._pay(c, "bonus", f["name"])
            foe = min((o for o in self._cf_hostiles(tgt, 30) if self._dist(tgt, o) <= max(5, self._reach(tgt))),
                      key=lambda o: self._dist(tgt, o), default=None)
            if foe is None or not self._may_react(tgt):
                return self._out(f"{name} commands {tgt['name']}, but it has no foe in reach (or no reaction)")
            child = self._opportunity_strike(tgt, foe)
            if not child:
                return self._out(f"{tgt['name']} has no melee attack to make")
            self._spend_reaction(tgt, "Commander's Strike")
            child["label"] = f"Commander's Strike ({tgt['name']})"
            child["atk"]["parts"] = list(child["atk"].get("parts") or []) + [["1" + F.superiority_die(char), (child["atk"].get("parts") or [["", ""]])[0][1]]]
            return self._run_r(child)
        if key == "inspiring_smite":
            n = roll(f"2d8+{char.class_level('Paladin')}")
            allies = [o for o in self.b["combatants"] if not self._hostile(c, o) and self._alive(o) and self._within(c, o, 30)]
            hurt = sorted(allies, key=lambda o: self._hp_of(o) / max(1, self._max_hp(o)))[:max(1, len(allies))]
            share = max(1, n // max(1, len(hurt)))
            for o in hurt:
                self._give_temp(o, share)
            return self._out(f"{name}'s Inspiring Smite: {', '.join(o['name'] for o in hurt)} gain {share} temporary HP each")
        if key == "watchers_will":
            allies = sorted((o for o in self.b["combatants"] if not self._hostile(c, o) and self._alive(o) and self._within(c, o, 30)),
                            key=lambda o: (o is not c, self._dist(c, o)))[:1 + max(1, char.mod("cha"))]
            for o in allies:
                self._effect_on(o, "Watcher's Will", [], None, None, None, 10, name, {"save_adv": ["int", "wis", "cha"]}, None, c["id"])
            return self._out(f"{name} keeps watch: {', '.join(o['name'] for o in allies)} have advantage on Int, Wis and Cha saves")
        if key == "otherworldly_wings":
            self._effect_on(c, "Otherworldly Wings", [], None, None, None, None, name, {"fly": 30}, None, c["id"])
            return self._out(f"{name} spreads spectral wings (fly 30 ft)")
        if key == "defensive_field":
            n = char.class_level("Artificer")
            self._give_temp(c, n)
            return self._out(f"{name} raises a defensive field: {n} temporary HP")
        if key == "dragon_fear":
            char.d["resources"]["short:Breath Weapon"] = 1      # it spends the breath weapon
            char.save()
            near = self._cf_hostiles(c, 30)
            if not near:
                return self._out(f"{name} roars: no foe within 30 ft")
            return self._run_r(self._strike(c, "Dragon Fear", [o["id"] for o in near], mode="save",
                                            sv={"ab": "wis", "dc": self._cf_dc(char, "cha"), "half": False, "conds": ["Frightened"],
                                                "repeat": "end", "rounds": 10}, parts=[]))
        return None

    # ------------------------------------------------------------------ hits and damage
    def _class_hit_parts(self, att: dict, tgt: dict, R: dict) -> list:
        """Extra damage features add to a hit (rolled with it, doubled dice on a critical)."""
        a = R.get("atk") or {}
        tchar = self._sheet(tgt)
        if tchar and not tgt.get("form") and tchar.has_feature("Multiattack Defense"):
            tgt["mad"] = [self.b.get("round"), self.b.get("turn"), att["id"]]       # +4 AC against this one's next attacks this turn
        for e in list(att.get("effects") or []):                # Unwavering Mark: the marked creature hurts someone else
            src = (e.get("mods") or {}).get("protector")
            if e["name"] == "Unwavering Mark" and src is not None and src != tgt["id"]:
                cav = self._find_or_none(src)
                if cav is not None:
                    cav["mark_strike"] = att["id"]
        early = []
        for e in list(tgt.get("effects") or []):                # Order's Wrath: the cursed creature's next hit by an ally of the cleric
            src = (e.get("mods") or {}).get("order_wrath")
            if src is not None and src != att["id"]:
                cleric = self._find_or_none(src)
                if cleric is not None and not self._hostile(cleric, att):
                    early.append(["2d8", "psychic"])
                    self._effect_off(tgt, e, "Order's Wrath")
                    self._line(R, f"Order's Wrath: +2d8 psychic on {tgt['name']}", "")
        char = self._sheet(att)
        if not char or att.get("form"):
            return early
        if F.sub_at(char, "Cleric", "Order Domain", 17) and att.get("strike_used") == [self.b.get("round"), self.b.get("turn")] \
                and self._once_per_turn(att, "order_wrath"):
            self._effect_on(tgt, "Order's Wrath", [], None, None, None, None, att["name"], {"order_wrath": att["id"]}, None, att["id"],
                            until={"end": att["id"], "skip": 1})
        out, names = list(early), []                            # (Order's Wrath has its own line)

        def add(dice, kind, label):
            out.append([dice, kind])
            names.append(f"{label} +{dice}" + (f" {kind}" if kind and kind != dtype else ""))
        dtype = (a.get("parts") or [["", ""]])[0][1] or ""
        weapon = bool(a.get("weapon"))
        mine = self.b.get("turn") == att["id"]
        pb = char.proficiency_bonus
        for e in list(tgt.get("effects") or []):
            m = e.get("mods") or {}
            if m.get("favored_by") == att["id"] and mine and self._once_per_turn(att, "favored_foe"):
                lv = char.class_level("Ranger")
                add("1d8" if lv >= 14 else "1d6" if lv >= 6 else "1d4", dtype, "Favored Foe")
            if m.get("hex_curse") == att["id"]:
                add(pb, dtype, "Hexblade's Curse")
            if m.get("slayers_prey") == att["id"] and weapon and self._once_per_turn(att, "slayers_prey"):
                add("1d6", dtype, "Slayer's Prey")
        for e in list(att.get("effects") or []):
            m = e.get("mods") or {}
            if m.get("planar") == tgt["id"] and weapon:
                add("2d8" if char.class_level("Ranger") >= 11 else "1d8", "force", "Planar Warrior")
                self._effect_off(att, e, "used")
            if m.get("giants_might") and weapon and self._once_per_turn(att, "giants_might"):
                add(m["giants_might"], dtype, "Giant's Might")
            if m.get("revelation") and self._once_per_turn(att, "revelation"):
                add(m["revelation"][0], m["revelation"][1], e["name"])
        if a.get("feint_die"):
            add(a.pop("feint_die"), dtype, "Feinting Attack")
        if weapon and CF.is_on(char, "hunters_prey") == "Colossus Slayer" and CF.has(char, "hunters_prey") \
                and 0 < self._hp_of(tgt) < self._max_hp(tgt) and self._once_per_turn(att, "colossus"):
            add("1d8", dtype, "Colossus Slayer")
        if weapon and mine and F.sub_at(char, "Barbarian", "Path of the Zealot", 3) and self._raging(att) and self._once_per_turn(att, "divine_fury"):
            add(f"1d6+{char.class_level('Barbarian') // 2}", CF.is_on(char, "divine_fury") or "radiant", "Divine Fury")
        if weapon and F.sub_at(char, "Ranger", "Fey Wanderer", 3) and self._once_per_turn(att, f"dreadful:{tgt['id']}"):
            add("1d6" if char.class_level("Ranger") >= 11 else "1d4", "psychic", "Dreadful Strikes")
        if F.sub_at(char, "Ranger", "Swarmkeeper", 3) and self._once_per_turn(att, "swarm"):
            swarm = CF.is_on(char, "gathered_swarm") or "Damage"
            if swarm == "Push 15 ft" and tgt.get("pos") and att.get("pos"):
                res = self._saving_throw(tgt, "str", self._cf_dc(char, "wis"), label="Gathered Swarm")
                if res["ok"]:
                    self._line(R, f"Gathered Swarm: {tgt['name']} STR save {res['total']} holds its ground", "Gathered Swarm")
                else:
                    self._line(R, f"Gathered Swarm: {tgt['name']} STR save {res['total']} fails", "Gathered Swarm")
                    self._push(tgt, att, 15, R)
                    if char.class_level("Ranger") >= 11 and self._size_of(tgt) != "Gargantuan":
                        self._cond(tgt, "Prone", True)
                        self._line(R, f"Mighty Swarm: {tgt['name']} falls prone", "prone")
            elif swarm == "Move 5 ft" and tgt.get("pos") and att.get("pos"):
                self._swarm_step(att, tgt, R, bool(a.get("melee")))
            else:
                add("1d8" if char.class_level("Ranger") >= 11 else "1d6", "piercing", "Gathered Swarm")
        if mine and F.sub_at(char, "Warlock", "The Genie", 1) and self._once_per_turn(att, "genie"):
            add(pb, CF.GENIE_TYPES.get(CF.is_on(char, "genie_kind")) or "bludgeoning", "Genie's Wrath")
        if weapon and a.get("melee") and char.has_option("Lifedrinker"):
            add(max(1, char.mod("cha")), "necrotic", "Lifedrinker")
        if weapon and mine and self.b.get("round") == 1 and F.sub_at(char, "Ranger", "Gloom Stalker", 3) and not att.get("dread_used"):
            att["dread_used"] = True
            add("1d8", dtype, "Dread Ambusher")
        if weapon and char.class_level("Ranger") >= 20 and char.has_feature("Foe Slayer") and self._once_per_turn(att, "foe_slayer"):
            add(max(0, char.mod("wis")), dtype, "Foe Slayer")
        if weapon and not a.get("melee") and "thrown" in (a.get("props") or []) and char.has_option("Thrown Weapon Fighting"):
            add(2, dtype, "Thrown Weapon Fighting")
        if weapon and a.get("melee") and F.sub_at(char, "Wizard", "Bladesinging", 14) and any(e["name"] == "Bladesong" for e in att.get("effects") or []):
            add(max(1, char.mod("int")), dtype, "Song of Victory")
        if mine and F.sub_at(char, "Barbarian", "Path of the Ancestral Guardian", 3) and self._raging(att) and self._once_per_turn(att, "protectors"):
            self._effect_on(tgt, "Ancestral Protectors", [], None, None, None, None, att["name"], {"protector": att["id"]}, None, att["id"],
                            until={"start": att["id"]})
        if weapon and a.get("melee") and F.sub_at(char, "Fighter", "Cavalier", 3):          # Unwavering Mark
            self._effect_on(tgt, "Unwavering Mark", [], None, None, None, None, att["name"], {"protector": att["id"]}, None, att["id"],
                            until={"end": att["id"], "skip": 1 if mine else 0})
        if F.sub_at(char, "Rogue", "Phantom", 3) and att.get("sneak_used") == [self.b.get("round"), self.b.get("turn")] \
                and self._cf_turn_free(att, "wails") and (self._cf_left(att, "Wails from the Grave", pb) or int((att.get("subd") or {}).get("trinkets") or 0) > 0):
            other = next((o for o in self.b["combatants"] if o is not tgt and o is not att and o.get("pos") and tgt.get("pos")
                          and self._hostile(att, o) and self._alive(o) and self._dist(o, tgt) <= 30), None)
            if other:
                self._once_per_turn(att, "wails")
                if not self._subd_trinket_wails(att, pb):               # a soul trinket pays for it when no use is left (subfeats_d.py)
                    self._cf_use(att, "Wails from the Grave")
                n = ((char.class_level("Rogue") + 1) // 2 + 1) // 2          # half the Sneak Attack dice, rounded up
                dmg = roll(f"{n}d6")
                self._line(R, "Wails from the Grave: " + self._deal(other, [[dmg, "necrotic"]], by=att, label="Wails from the Grave"), "")
                if F.sub_at(char, "Rogue", "Phantom", 17) and self._alive(tgt):          # Death's Friend: the first creature takes it too
                    self._line(R, "Death's Friend: " + self._deal(tgt, [[dmg, "necrotic"]], by=att, label="Death's Friend"), "")
        if weapon and F.sub_at(char, "Fighter", "Eldritch Knight", 10):
            self._effect_on(tgt, "Eldritch Strike", [], None, None, None, None, att["name"], {"save_dis": ["spells"], "once": True}, None, att["id"],
                            until={"end": att["id"], "skip": 1 if mine else 0})
        for dice, kind, label in self._sub_hit_parts(att, tgt, R, char):     # Crushing Throw (subfeats.py)
            add(dice, kind, label)
        if names:
            self._line(R, f"{att['name']}: " + ", ".join(names), names[0].split(" +")[0])
        return out

    def _class_modes(self, att: dict, tgt: dict, a: dict) -> list:
        """[(mode, why)] features add to an attack roll."""
        out = []
        for e in list(att.get("effects") or []):
            m = e.get("mods") or {}
            if m.get("feint") == tgt["id"]:
                out.append(("adv", "Feinting Attack"))
                a["feint_die"] = m.get("feint_die")
                self._effect_off(att, e, "used")
            if m.get("protector") is not None and m["protector"] != tgt["id"]:
                prot = self._find_or_none(m["protector"])        # Unwavering Mark: only while the marked one is within 5 ft of the knight
                if e["name"] != "Unwavering Mark" or (prot and att.get("pos") and prot.get("pos") and self._dist(prot, att) <= 5):
                    out.append(("dis", e["name"]))              # Ancestral Protectors, Thunder Gauntlets
            if m.get("duplicity") and att.get("pos") and tgt.get("pos") and self._dist(att, tgt) <= 5:
                tok = self._cf_duplicate(att, tgt)               # both the cleric and its illusion beside the target
                if tok is not None and tok.get("pos") and self._dist(tok, tgt) <= 5:
                    out.append(("adv", "Invoke Duplicity"))
        tchar = self._sheet(tgt)
        if a.get("opportunity") and tchar and not tgt.get("form"):
            if tchar.has_feature("Escape the Horde"):
                out.append(("dis", "Escape the Horde"))
            elif self._raging(tgt) and F.sub_at(tchar, "Barbarian", "Path of the Totem Warrior", 3) and CF.is_on(tchar, "totem_spirit") == "Eagle" \
                    and (tchar.equipped_armor() or {}).get("type") != "HA":
                out.append(("dis", "Eagle totem"))
        for o in self.b["combatants"]:
            if o is att or o.get("kind") != "pc" or not o.get("pos") or not self._raging(o) or not att.get("pos") or not tgt.get("pos"):
                continue
            oc = self._sheet(o)
            if not oc or not F.sub_at(oc, "Barbarian", "Path of the Totem Warrior", 3):
                continue
            if a.get("melee") and not self._hostile(o, att) and self._hostile(o, tgt) and CF.is_on(oc, "totem_spirit") == "Wolf" \
                    and self._dist(o, tgt) <= 5:
                out.append(("adv", "Wolf totem"))
            if self._hostile(o, att) and tgt is not o and oc.class_level("Barbarian") >= 14 and CF.is_on(oc, "totem_attunement") == "Bear" \
                    and self._dist(o, att) <= 5:
                out.append(("dis", "Bear totem"))
        out += self._subd_modes(att, tgt, a)                     # Mortal Bulwark (subfeats_d.py)
        out += self._race_modes(att, tgt, a)                     # a dhampir's bite at half hit points (racefeats.py)
        return out

    def _class_ac_vs(self, att: dict, tgt: dict) -> int:
        """AC a creature has against this attacker only: Multiattack Defense after it was hit by it this turn."""
        return 4 if tgt.get("mad") == [self.b.get("round"), self.b.get("turn"), att["id"]] else 0

    def _class_crit_vs(self, att: dict, tgt: dict) -> int:
        """The lowest natural roll that crits against this target: 19 for a hexblade against its cursed foe."""
        return 19 if any((e.get("mods") or {}).get("hex_curse") == att["id"] for e in tgt.get("effects") or []) else 20

    def _class_damage(self, R: dict, att: dict, tgt: dict, rolled: list, parts: list) -> list:
        """Great Weapon Fighting: the weapon's 1s and 2s are rolled again (two-handed or versatile in two hands)."""
        a = R.get("atk") or {}
        rolled = self._subd_damage(R, att, tgt, rolled, parts)       # Grave Touched, Spell Bombardment, Power Surge (subfeats_d.py)
        rolled = self._nf_damage(R, att, tgt, rolled, parts)         # Perfect Poisoner, Exploit Opening (newfeats.py)
        if a.get("weapon") and self._fx(att, "enfeebled"):          # an Enfeebling Arrow: half damage with weapons
            for p in rolled:
                p[0] = p[0] // 2
        if any(e["name"] == "Ancestral Protectors" and (e.get("mods") or {}).get("protector") not in (None, tgt["id"])
               for e in att.get("effects") or []):                   # the spirits: its damage to others is resisted
            for p in rolled:
                p[0] = p[0] // 2
            self._line(R, f"Ancestral Protectors: {tgt['name']} resists the damage", "")
        char = self._sheet(att)
        if char and not att.get("form") and a.get("weapon") and rolled and F.sub_at(char, "Rogue", "Assassin", 17) \
                and self.b.get("round") == 1 and not tgt.get("had_turn") and self._alive(tgt):     # Death Strike: a surprised creature
            dc = 8 + char.proficiency_bonus + char.mod("dex")
            res = self._saving_throw(tgt, "con", dc, label="Death Strike")
            if not res["ok"]:
                for p in rolled:
                    p[0] *= 2
            self._line(R, f"Death Strike: {tgt['name']} CON {res['total']} vs DC {dc} — " + ("saved" if res["ok"] else "damage doubled"), "")
        if not char or att.get("form") or not a.get("weapon") or not a.get("melee") or not rolled or not parts:
            return rolled
        if not char.has_option("Great Weapon Fighting") or not (a.get("two_handed") or "two-handed" in (a.get("props") or [])):
            return rolled
        m = re.match(r"^(\d*)d(\d+)\s*([+-]\s*\d+)?$", str(parts[0][0]).replace(" ", ""))
        if not m:
            return rolled
        n = int(m.group(1) or 1) * (2 if (R.get("cur") or {}).get("crit") else 1)
        sides = int(m.group(2))
        total = 0
        for _ in range(n):
            d = self.rng.randint(1, sides)
            total += self.rng.randint(1, sides) if d <= 2 else d
        rolled[0][0] = total + (int(m.group(3)) if m.group(3) else 0)
        return rolled

    def _class_strike_start(self, R: dict, att: Optional[dict]):
        """A spell's damage before it is rolled: Elemental Affinity and Radiant Soul add the Charisma modifier to one roll."""
        char = self._sheet(att) if att else None
        if not char or not R.get("spell") or R.get("cf_start") or att.get("form"):
            return
        R["cf_start"] = True
        parts = R["parts"] if R["mode"] in ("save", "auto") else ((R.get("atk") or {}).get("parts") if int((R.get("atk") or {}).get("n", 1)) == 1 else None)
        if not parts:
            return
        types = [str(t or "").lower() for _d, t in parts]
        want = []
        if F.sub_at(char, "Sorcerer", "Draconic Bloodline", 6):
            race = char.race_data() or {}
            anc = self._subd_dragon_type(char) or ((race.get("resist") or [None])[-1] if char.ancestry else None)     # Dragon Ancestor (subfeats_d.py)
            want.append(str(anc or "").lower())
        if F.sub_at(char, "Warlock", "The Celestial", 6):
            want += ["radiant", "fire"]
        hit = next((t for t in want if t and t in types), None)
        if hit and char.mod("cha") > 0:
            parts.append([char.mod("cha"), hit])
            self._line(R, f"{att['name']} adds +{char.mod('cha')} {hit} ({'Elemental Affinity' if hit not in ('radiant', 'fire') or not F.sub_at(char, 'Warlock', 'The Celestial', 6) else 'Radiant Soul'})", "")
        one = self._find_or_none(R["targets"][0]) if len(set(R["targets"])) == 1 else None
        if one and any((e.get("mods") or {}).get("hex_curse") == att["id"] for e in one.get("effects") or []) and R["mode"] != "attack":
            parts.append([char.proficiency_bonus, types[0]])                        # Hexblade's Curse: any damage roll against it
            self._line(R, f"{att['name']}: Hexblade's Curse +{char.proficiency_bonus}", "")
        if F.sub_at(char, "Artificer", "Alchemist", 5) and char.mod("int") > 0:      # Alchemical Savant
            t = next((t for t in ("acid", "fire", "necrotic", "poison") if t in types), None)
            if t:
                parts.append([char.mod("int"), t])
                self._line(R, f"{att['name']} adds +{char.mod('int')} {t} (Alchemical Savant)", "")
        if F.sub_at(char, "Druid", "Circle of Wildfire", 6) and "fire" in types and any(
                o.get("summoned_by") == att["id"] and o.get("monster") == "Wildfire Spirit|TCE" and self._alive(o) for o in self.b["combatants"]):
            parts.append(["1d8", "fire"])                                           # Enhanced Bond
            self._line(R, f"{att['name']}'s Enhanced Bond adds +1d8 fire", "")
        if F.sub_at(char, "Artificer", "Artillerist", 5):                            # Arcane Firearm
            parts.append(["1d8", types[0]])
            self._line(R, f"{att['name']}'s Arcane Firearm adds +1d8", "")
        for e, v in self._fx(att, "max_types"):                  # Destructive Wrath: lightning and thunder at their maximum
            if any(t in v for t in types):
                for p in parts:
                    m = re.fullmatch(r"(\d*)d(\d+)([+-]\d+)?", str(p[0]).replace(" ", ""))
                    if m and str(p[1]).lower() in v:
                        p[0] = int(m.group(1) or 1) * int(m.group(2)) + int(m.group(3) or 0)
                self._line(R, f"{att['name']}'s Destructive Wrath: maximum {'/'.join(v)} damage", "Destructive Wrath")
                if e in (att.get("effects") or []):
                    self._effect_off(att, e, "used")
                break
        if R["mode"] == "save" and self._fx(att, "corona") and {"fire", "radiant"} & set(types):     # Corona of Light
            for tid in R["targets"]:
                o = self._find_or_none(tid)
                if o and self._hostile(att, o) and self._within(att, o, 60):
                    self._effect_on(o, "Corona of Light", [], None, None, None, None, att["name"], {"save_dis": ["all"], "once": True}, None, att["id"],
                                    until={"end": att["id"], "skip": 0})
        if R["mode"] == "save" and F.sub_at(char, "Wizard", "School of Evocation", 6) and not R["sv"].get("half"):
            sp = rules.spell(re.sub(r"\s*\(.*\)$", "", str(R.get("label") or "")))
            if sp and sp.get("level") == 0:
                R["sv"]["half"] = True                          # Potent Cantrip: half damage on a successful save
        if "fire" in types and "Flames of Phlegethos" in (char.d.get("feats") or []):
            self._effect_on(att, "Flames of Phlegethos", [], None, None, None, None, att["name"], {"retaliate": ("1d4", "fire")}, None, att["id"],
                            until={"end": att["id"], "skip": 1 if self.b.get("turn") == att["id"] else 0})

    def _class_healed(self, att: Optional[dict], targets: list, sp: dict, level: int) -> List[str]:
        """After a healing spell: Blessed Healer (the cleric heals 2 + the spell's level when it healed someone else), the
        Starry Form chalice (1d8 + Wisdom to the most hurt ally within 30 ft). Returns lines for the cast's summary."""
        char = self._sheet(att) if att else None
        if not char or att.get("form") or not sp.get("level"):
            return []
        out = self._subc_healed(att, targets, sp, level)        # Spell Breaker (subfeats_c.py)
        if F.sub_at(char, "Cleric", "Life Domain", 6) and any(t is not att for t in targets) and self._alive(att):
            n = 2 + int(level or sp["level"])
            if self._heal(att, n):
                out.append(f"{att['name']} +{n} (Blessed Healer)")
        if any(v == "chalice" for _e, v in self._fx(att, "starry")):
            near = [o for o in self.b["combatants"] if not self._hostile(att, o) and self._alive(o) and self._within(att, o, 30)
                    and self._hp_of(o) < self._max_hp(o)]
            if near:
                o = min(near, key=lambda x: self._hp_of(x) / max(1, self._max_hp(x)))
                n = roll("2d8" if char.class_level("Druid") >= 10 else "1d8") + char.mod("wis")      # Twinkling Constellations: 2d8
                if self._heal(o, max(1, n)):
                    out.append(f"{o['name']} +{max(1, n)} (Starry chalice)")
        return out

    # ------------------------------------------------------------------ Four Elements disciplines, astral arms, wild surges, skirmishing
    def _discipline_items(self, c: dict) -> List[dict]:
        """The spell disciplines a Way of the Four Elements monk knows, as spell items of the bar (cast for ki, no slot)."""
        from . import icons
        from . import info as INFO
        from . import spellbook as SB
        char = self._sheet(c)
        if not char or c.get("form"):
            return []
        out = self._invocation_items(c, char)
        if char.class_level("Monk") < 3:
            return out
        wis = char.mod("wis")
        for name, (spell, ki, lv, cost_as) in self._ki_spells(char).items():
            sp = rules.spell(spell)
            if not sp:
                continue
            spec = SB.spec(sp)
            cost = cost_as or (spec["cost"] if spec["cost"] != "long" else "action")
            after = cost_as == "bonus" and self._economy_on() and not (c.get("turn") or {}).get("attacked")     # Searing Arc Strike
            why = (f"Needs {ki} ki" if self._resource_left(c, "Ki Points") < ki else "Take the Attack action first" if after else None) \
                or self._pay(c, cost, sp["name"], check_only=True) \
                or EC.spell_rule(c.get("turn"), cost, sp["level"])
            out.append({"id": f"discipline:{name}", "kind": "discipline", "name": f"{sp['name']} ({name})", "cost": cost, "options": [],
                        "ok": why is None, "why": why, "target": dict(spec["target"]), "area": spec["area"], "range": spec["range"],
                        "level": sp["level"], "uses": f"{ki} ki", "types": spec["types"], "concentration": spec["concentration"],
                        "tip": f"{name}: spend {ki} ki to cast {sp['name']} (ki save DC {F.ki_dc(char)}).",
                        "icon": icons.for_spell(sp["name"], sp.get("school", ""), spec["kind"], sp.get("damage")),
                        "info": INFO.spell(sp, spec, dc=F.ki_dc(char), attack=char.proficiency_bonus + wis, level=sp["level"],
                                           caster_level=char.total_level, mod=wis)})
        return out

    def use_discipline(self, cid: int, name: str, targets=None, point=None, dtype: Optional[str] = None, adv: Optional[str] = None) -> str:
        """Cast a Four Elements discipline's spell: ki instead of a slot, the monk's ki save DC and Wisdom."""
        with self.lock:
            self._busy()
            c = self._find(cid)
            char = self._sheet(c)
            if char and name in INVOCATION_SPELLS and char.has_option(name) and not c.get("form"):
                return self._use_invocation(c, char, name, targets, point, dtype, adv)
            d = self._ki_spells(char).get(name) if char else None
            if not d or c.get("form"):
                raise ServiceError("That discipline isn't available.")
            spell, ki, _lv, cost_as = d
            if cost_as == "bonus" and self._economy_on() and not (c.get("turn") or {}).get("attacked"):
                raise ServiceError("Take the Attack action first.")
            if self._resource_left(c, "Ki Points") < ki:
                raise ServiceError(f"Not enough ki for {name} ({ki} needed).")
            sp = rules.spell(spell)
            wis = char.mod("wis")
            self._say(f"{c['name']} channels {name} ({ki} ki)")
            out = self._cast_on(c, sp, None, slot_level=sp["level"], caster_level=char.total_level, mod=wis,
                                attack_bonus=char.proficiency_bonus + wis, dc=F.ki_dc(char), adv=adv, dtype=dtype, targets=targets, point=point,
                                paid=True, mm={"cost_override": cost_as} if cost_as else None)
            self._use_resource(c, "Ki Points", ki)
            if c.get("turn") is not None and cost_as != "bonus":
                c["turn"]["ki_action"] = True                   # Ki-Fueled Attack
            return out

    def _invocation_why(self, c: dict, char, name: str) -> Optional[str]:
        kind = INVOCATION_SPELLS[name][1]
        if kind in ("slot", "long") and int(char.d["resources"].get(f"feature:{name}") or 0):
            return "Used until a long rest"
        if kind == "slot" and not SC.slots_remaining(char).get(SC.PACT_KEY):
            return "No warlock spell slot left"
        return None

    def _invocation_items(self, c: dict, char) -> List[dict]:
        """Eldritch Invocations that cast a spell (Armor of Shadows, Sign of Ill Omen...), as spell items of the bar."""
        from . import icons
        from . import info as INFO
        from . import spellbook as SB
        out = []
        cha = char.mod("cha")
        for name, (spell, kind) in INVOCATION_SPELLS.items():
            sp = rules.spell(spell)
            if not sp or not char.has_option(name):
                continue
            spec = SB.spec(sp)
            cost = spec["cost"] if spec["cost"] != "long" else "action"
            why = self._invocation_why(c, char, name) or self._pay(c, cost, sp["name"], check_only=True) \
                or EC.spell_rule(c.get("turn"), cost, sp["level"])
            level = (SC.spell_slots(char).get("pact") or {}).get("level", sp["level"]) if kind == "slot" else sp["level"]
            out.append({"id": f"discipline:{name}", "kind": "discipline", "name": f"{sp['name']} ({name})", "cost": cost, "options": [],
                        "ok": why is None, "why": why, "target": dict(spec["target"]), "area": spec["area"], "range": spec["range"],
                        "level": sp["level"], "uses": {"will": "at will", "slot": "a warlock slot, once a day", "long": "once a day"}[kind],
                        "types": spec["types"], "concentration": spec["concentration"],
                        "tip": f"{name}: cast {sp['name']}" + (" at will, without a slot" if kind == "will" else " once per long rest"),
                        "icon": icons.for_spell(sp["name"], sp.get("school", ""), spec["kind"], sp.get("damage")),
                        "info": INFO.spell(sp, spec, dc=self._spell_dc(c), attack=char.proficiency_bonus + cha, level=level,
                                           caster_level=char.total_level, mod=cha)})
        return out

    def _use_invocation(self, c: dict, char, name: str, targets, point, dtype, adv) -> str:
        spell, kind = INVOCATION_SPELLS[name]
        why = self._invocation_why(c, char, name)
        if why:
            raise ServiceError(why)
        sp = rules.spell(spell)
        level = sp["level"]
        if kind == "slot":
            level = (SC.spell_slots(char).get("pact") or {}).get("level", level)
        cha = char.mod("cha")
        self._say(f"{c['name']} invokes {name}")
        out = self._cast_on(c, sp, None, slot_level=level, caster_level=char.total_level, mod=cha, attack_bonus=char.proficiency_bonus + cha,
                            dc=self._spell_dc(c), adv=adv, dtype=dtype, targets=targets, point=point, paid=True)
        if kind in ("slot", "long"):
            char.d["resources"][f"feature:{name}"] = 1
            if kind == "slot":
                used = char.d["slots_used"]
                used[SC.PACT_KEY] = int(used.get(SC.PACT_KEY) or 0) + 1
            char.save()
        return out

    @staticmethod
    def _ki_spells(char) -> dict:
        """{name: (spell, ki, monk level, cost or None)}: the Four Elements disciplines the monk knows, Shadow Arts, Searing Arc Strike."""
        out = {}
        lv = char.class_level("Monk")
        if F.sub_at(char, "Monk", "Way of the Four Elements", 3):
            out.update({n: (s, k, need, None) for n, (s, k, need) in DISCIPLINES.items() if char.has_option(n) and lv >= need})
        for n, (sub, need, s, k, cost) in KI_SPELLS.items():
            if F.sub_at(char, "Monk", sub, need):
                out[n] = (s, k, need, cost)
        return out

    def _class_weapon_atk(self, att: dict, w: dict, atk: dict) -> dict:
        """A monk's unarmed strike changed: Arms of the Astral Self (Wisdom, force, +5 ft reach), Fangs of the Fire Snake (+10 ft, fire)."""
        atk = self._sub_weapon_atk(att, w, atk)                 # Giant Stature, Elemental Cleaver, Draconic Strike (subfeats.py)
        if "unarmed" not in (w.get("props") or []) or att.get("form"):
            return atk
        char = self._sheet(att)
        if not char:
            return atk
        if self._fx(att, "astral_arms"):
            wis = char.mod("wis")
            die = F.martial_die(char) or "1d4"
            if wis > char.mod(w.get("ability") or "str"):
                atk["bonus"] = char.proficiency_bonus + wis
                atk["parts"] = [[f"{die}{wis:+d}" if wis else die, "force"]]
                atk["str_based"] = False
            else:
                atk["parts"] = [[atk["parts"][0][0], "force"]]
            atk["reach"] = atk.get("reach", 5) + 5
            atk["magical"] = True
        if self._fx(att, "fangs"):
            atk["reach"] = atk.get("reach", 5) + 10
            atk["parts"] = [[atk["parts"][0][0], "fire"]] + atk["parts"][1:]
        return atk

    def _class_after_rage(self, c: dict, char) -> Optional[str]:
        """Instinctive Pounce (move half your speed as you rage); Path of Wild Magic: a Wild Surge (d8) when the rage starts."""
        t = c.get("turn")
        self._subc_after_rage(c, char)                          # Call the Hunt, Shielding Storm (subfeats_c.py)
        if char.class_level("Barbarian") >= 7 and char.has_feature("Instinctive Pounce") and t is not None and self.b.get("turn") == c["id"]:
            t["move"] = t.get("move", 0) + self._speed(c) // 2
        if not F.sub_at(char, "Barbarian", "Path of Wild Magic", 3):
            return None
        r = self.rng.randint(1, 8)
        kind = WILD_SURGE[r]
        lv = char.class_level("Barbarian")
        dc = self._cf_dc(char, "con")
        self._say(f"{c['name']}'s Wild Surge ({r}): {kind}")
        if kind == "Shadowy Tendrils":
            n = roll("1d12")
            self._give_temp(c, n)
            near = self._cf_hostiles(c, 30)
            if near:
                self._run_r(self._strike(c, "Wild Surge: Shadowy Tendrils", [o["id"] for o in near], mode="save",
                                         sv={"ab": "con", "dc": dc, "half": False}, parts=[["1d12", "necrotic"]], magical=True))
            return f"shadowy tendrils lash out ({n} temporary HP)"
        if kind == "Exploding Spirit":
            near = self._cf_hostiles(c, 30)
            if near:
                hit = [o["id"] for o in self.b["combatants"] if o.get("pos") and self._alive(o) and self._dist(o, near[0]) <= 5]
                self._run_r(self._strike(c, "Wild Surge: Exploding Spirit", hit, mode="save", sv={"ab": "dex", "dc": dc, "half": False},
                                         parts=[["1d6", "force"]], magical=True))
            return "an intangible spirit bursts"
        if kind == "Retribution":
            self._effect_on(c, "Wild Surge: Retribution", [], None, None, None, 10, c["name"], {"retaliate": ("1d6", "force")}, None, c["id"])
            return "creatures that hit it take 1d6 force"
        if kind == "Protective Lights":
            for o in [o for o in self.b["combatants"] if not self._hostile(c, o) and self._alive(o) and self._within(c, o, 10)]:
                self._effect_on(o, "Wild Surge: Protective Lights", [], None, None, None, 10, c["name"], {"ac": 1}, None, c["id"])
            return "protective lights: +1 AC to it and allies within 10 ft"
        if kind == "Bolt of Light":
            near = self._cf_hostiles(c, 30)
            if near:
                self._run_r(self._strike(c, "Wild Surge: Bolt of Light", [near[0]["id"]], mode="save",
                                         sv={"ab": "con", "dc": dc, "half": False, "conds": ["Blinded"], "until": "caster_start"},
                                         parts=[["1d6", "radiant"]], magical=True))
            return "a bolt of light"
        if kind == "Infused Weapon":
            return "its weapon turns to force, light and thrown (it returns to its hand)"
        return f"{kind.lower()} (barbarian level {lv}: the DM places it on the map)"

    def _class_cast(self, att: dict, sp: dict, level: int):
        """Wild Magic sorcerer: after a spell of 1st level or higher, a d20; on a 1 (or when Tides of Chaos is spent, which
        it then gets back) a Wild Magic Surge (d100 table)."""
        char = self._sheet(att)
        if not char or att.get("form") or not sp.get("level"):
            return
        kinds = [t for t in ("lightning", "thunder") if t in [str(x).lower() for x in sp.get("damage") or []]]
        if kinds and F.sub_at(char, "Sorcerer", "Storm Sorcery", 6) and att.get("pos"):     # Heart of the Storm
            n = max(1, char.class_level("Sorcerer") // 2)
            for o in self._cf_hostiles(att, 10):
                self._say("Heart of the Storm: " + self._deal(o, [[n, kinds[0]]], by=att, label="Heart of the Storm"))
        if not F.sub_at(char, "Sorcerer", "Wild Magic", 1):
            return
        tides = int(char.d["resources"].get("feature:Tides of Chaos") or 0) > 0
        r = self.rng.randint(1, 20)
        if r != 1 and not tides:
            return
        if tides:
            char.d["resources"].pop("feature:Tides of Chaos", None)     # the surge brings Tides of Chaos back
            char.save()
        self._wild_surge(att, char)

    def _wild_surge(self, c: dict, char):
        d = self.rng.randint(1, 100)
        k = (d - 1) // 2                                         # 50 two-number bands
        name = c["name"]
        lv = char.class_level("Sorcerer")
        near = lambda feet: [o for o in self.b["combatants"] if o is not c and o.get("pos") and self._alive(o) and self._within(c, o, feet)]
        line = None
        if k == 1:
            self._effect_on(c, "Wild Surge: see invisibility", [], None, None, None, 10, name, {"senses": {"see_invisible": True}}, None, c["id"])
            line = "it can see invisible creatures for a minute"
        elif k == 3:
            hit = [o["id"] for o in near(20)] + [c["id"]]
            self._run_r(self._strike(c, "Wild Surge: Fireball", hit, mode="save", magical=True, spell=True,
                                              sv={"ab": "dex", "dc": self._spell_dc(c), "half": True}, parts=[["8d6", "fire"]]))
            line = "a fireball bursts centred on itself"
        elif k == 7:
            self._effect_on(c, "Wild Surge: regeneration", [], None, None, None, 10, name, {"regen": "5"}, None, c["id"])
            line = "it regains 5 hit points each turn for a minute"
        elif k == 15:
            self._effect_on(c, "Wild Surge: astral", ["Incapacitated"], None, None, None, None, name, {"untargetable": True, "banished": True},
                            None, c["id"], until={"end": c["id"], "skip": 1})
            line = "it vanishes to the Astral Plane until the end of its next turn"
        elif k == 16:
            self._effect_on(c, "Wild Surge: maximized", [], None, None, None, 10, name, {"max_types": list(M.TYPES)}, None, c["id"])
            line = "its next damaging spell deals maximum damage"
        elif k == 19:
            n = roll("2d10")
            self._heal(c, n)
            line = f"it regains {n} hit points"
        elif k == 25:
            self._effect_on(c, "Wild Surge: spectral shield", [], None, None, None, 10, name, {"ac": 2, "mm_immune": True}, None, c["id"])
            line = "a spectral shield: +2 AC and immune to magic missile for a minute"
        elif k == 29:
            used = char.d["slots_used"]
            low = min((int(x) for x, v in used.items() if x.isdigit() and v), default=None)
            if low:
                used[str(low)] -= 1
                char.save()
            line = f"it regains its lowest expended spell slot ({low or 'none spent'})"
        elif k == 32:
            foes = sorted((o for o in near(30) if self._hostile(c, o)), key=lambda o: self._dist(c, o))[:3]
            if foes:
                self._run_r(self._strike(c, "Wild Surge: lightning", [o["id"] for o in foes], mode="auto", magical=True, spell=True,
                                                  parts=[["4d10", "lightning"]]))
            line = "lightning strikes up to three creatures"
        elif k == 33:
            self._effect_on(c, "Wild Surge: fear", ["Frightened"], None, None, None, None, name, None, None, c["id"],
                            until={"end": c["id"], "skip": 1 if self.b.get("turn") == c["id"] else 0})
            line = "it is frightened of the nearest creature until the end of its next turn"
        elif k == 35:
            self._effect_on(c, "Wild Surge: resistance", [], None, None, None, 10, name, {"resist": list(M.TYPES)}, None, c["id"])
            line = "it resists all damage for a minute"
        elif k == 36:
            others = near(60)
            if others:
                o = self.rng.choice(others)
                self._effect_on(o, "Wild Surge: poisoned", ["Poisoned"], None, None, None, 100, name, None, None, c["id"])
                line = f"{o['name']} is poisoned"
        elif k == 40:
            t = c.get("turn")
            if t is not None:
                t["action"] = t.get("action", 0) + 1
            line = "it can take one more action now"
        elif k == 41:
            total = 0
            for o in near(30):
                before = self._hp_of(o)
                self._say(self._deal(o, [["1d10", "necrotic"]], by=c, label="Wild Surge"))
                total += max(0, before - self._hp_of(o))
            self._heal(c, total)
            line = f"necrotic energy drains everyone within 30 ft; it regains {total} HP"
        elif k == 42:
            self._effect_on(c, "Wild Surge: mirror image", [], None, None, None, 10, name, {"images": 3}, None, c["id"])
            line = "three illusory duplicates appear (mirror image)"
        elif k == 43:
            self._effect_on(c, "Wild Surge: fly", [], None, None, None, 10, name, {"fly": 60}, None, c["id"])
            line = "it can fly 60 ft for a minute"
        elif k == 44:
            self._effect_on(c, "Wild Surge: invisible", ["Invisible"], None, None, None, 10, name, None, None, c["id"])
            line = "it turns invisible for a minute"
        elif k == 47:
            for o in near(30) + [c]:
                self._effect_on(o, "Wild Surge: vulnerable", [], None, None, None, 10, name, {"vuln": ["piercing"]}, None, c["id"])
            line = "it and every creature within 30 ft are vulnerable to piercing damage for a minute"
        elif k == 49:
            char.d["resources"].pop("Sorcery Points", None)
            char.save()
            line = "it regains all its sorcery points"
        self._say(f"{name}'s Wild Magic Surge ({d:02d}): " + (line or f"a harmless or odd effect (d100 {d}: the DM reads the table)")
                  + (f" — sorcerer level {lv}" if not line else ""))

    def _class_turn_end(self, c: dict):
        """Skirmisher (Scout 3): an enemy ending its turn within 5 ft of a scout, the scout slips away half its speed (a reaction,
        no opportunity attacks)."""
        self._sub_turn_end(c)                                   # an Echo Knight's echo that is too far away (subfeats.py)
        if not c.get("pos") or not self._alive(c):
            return
        for o in self.b["combatants"]:
            oc = self._sheet(o)
            if not oc or o.get("form") or not F.sub_at(oc, "Rogue", "Scout", 3) or not self._hostile(o, c) or not o.get("pos"):
                continue
            if self._dist(o, c) > 5 or not self._may_react(o) or self._react_mode(o, "skirmisher") == "never":
                continue
            feet = (self._speed(o) // 2) // 5 * 5
            if feet <= 0:
                continue
            self._spend_reaction(o, "Skirmisher")
            before = list(o["pos"])
            self._push(o, c, feet)
            self._say(f"{o['name']} skirmishes away from {c['name']}" + ("" if o["pos"] != before else " (nowhere to go)"))

    def _class_summoned(self, att: dict, sp: dict, made: list):
        """A wizard's creatures: Durable Summons (Conjuration 14: 30 temporary HP for conjured ones), Undead Thralls
        (Necromancy 6: animated undead get + wizard level HP and + proficiency bonus to weapon damage)."""
        char = self._sheet(att)
        if not char or att.get("form") or not made:
            return
        self._subc_summoned(att, sp, made)                      # Mighty Summoner (subfeats_c.py)
        self._nf_summoned(att, sp, made)                        # Fortified, Elemental and Otherworldly Familiar (newfeats.py)
        if F.sub_at(char, "Wizard", "School of Conjuration", 14) and sp.get("school") == "Conjuration":
            for c in made:
                self._give_temp(c, 30)
            self._say(f"{att['name']}'s Durable Summons: {', '.join(c['name'] for c in made)} gain 30 temporary HP")
        if F.sub_at(char, "Wizard", "School of Necromancy", 6) and sp["name"] in ("Animate Dead", "Create Undead"):
            lv = char.class_level("Wizard")
            if sp["name"] == "Animate Dead" and made[0].get("monster"):              # one more zombie or skeleton
                made += self._add_summons(att, made[0]["monster"], 1, None, sp["level"], None, None, made[0].get("summon_conc"),
                                          made[0].get("summon"), sp["name"])
            for c in made:
                c["max_hp"] = int(c.get("max_hp") or 0) + lv
                c["hp"] = int(c.get("hp") or 0) + lv
                self._effect_on(c, "Undead Thralls", [], None, None, None, None, att["name"], {"dmg": (char.proficiency_bonus, "")}, None, att["id"])
            self._say(f"{att['name']}'s Undead Thralls: +{lv} HP and +{char.proficiency_bonus} weapon damage")

    def _cf_cursed(self, c: dict, o: Optional[dict]) -> Optional[dict]:
        """`o` when the warlock's Hex or Hexblade's Curse is on it, else None."""
        if not o:
            return None
        return o if any(e.get("source_id") == c["id"] and (e["name"].startswith("Hex") or (e.get("mods") or {}).get("hex_curse") == c["id"])
                        for e in o.get("effects") or []) else None

    def _cf_duplicate(self, c: dict, near=None) -> Optional[dict]:
        """The illusory double of a trickery cleric's Invoke Duplicity, while it lasts (Improved Duplicity: four of them; the one nearest `near`,
        a tile or a creature)."""
        dups = [o for o in self.b["combatants"] if (o.get("conjured") or {}).get("spell") == "Invoke Duplicity" and o["conjured"].get("owner") == c["id"]]
        if len(dups) > 1 and near is not None:
            spot = near.get("pos") if isinstance(near, dict) else near
            if spot:
                dups.sort(key=lambda o: G.distance_ft(o["pos"], 1, [int(spot[0]), int(spot[1])], 1) if o.get("pos") else 10 ** 6)
        return dups[0] if dups else None

    def _class_may_target(self, att: dict, tgt: dict) -> Optional[str]:
        """Unbreakable Majesty: the first time each turn a creature attacks the bard, a Charisma save or it can't."""
        why = self._subc_may_target(att, tgt)                   # Nature's Sanctuary (subfeats_c.py)
        if why:
            return why
        for e, dc in self._fx(tgt, "majesty"):
            key = f"majesty:{tgt['id']}"
            if not self._cf_turn_free(att, key):
                return None
            self._once_per_turn(att, key)
            res = self._saving_throw(att, "cha", int(dc), spell=True, label="Unbreakable Majesty")
            if not res["ok"]:
                return f"{att['name']} can't bring itself to attack {tgt['name']} (Unbreakable Majesty, CHA {res['total']} vs DC {dc})"
            self._effect_on(att, "Unbreakable Majesty (shaken)", [], None, None, None, None, tgt["name"], {"save_dis": ["spells"]}, None, tgt["id"],
                            until={"end": tgt["id"], "skip": 1 if self.b.get("turn") == tgt["id"] else 0})
            return None
        return None

    def _shield_master_dodge(self, c: dict) -> bool:
        """Shield Master: a successful Dex save for half damage, with a shield and a reaction to spare: no damage at all."""
        char = self._sheet(c)
        if not char or c.get("form") or not self._feat(c, "shield_master") or not char.equipped_shield() or not self._may_react(c) \
                or self._react_mode(c, "shield_master") == "never":
            return False
        self._spend_reaction(c, "Shield Master")
        self._say(f"{c['name']} interposes the shield: no damage (Shield Master)")
        return True

    def _brace_ok(self, c: dict) -> bool:
        """The Brace maneuver: a reaction attack on a creature that moves into reach (a superiority die to spend)."""
        char = self._sheet(c)
        return bool(char) and not c.get("form") and char.has_option("Brace") and self._resource_left(c, "Superiority Dice") > 0 \
            and self._may_react(c) and self._melee_weapon_of(c) is not None

    def _fancy_footwork(self, c: dict) -> bool:
        """Swashbuckler 3: creatures it made a melee attack against this turn get no opportunity attacks on it (like Mobile)."""
        char = self._sheet(c)
        return bool(char) and not c.get("form") and F.sub_at(char, "Rogue", "Swashbuckler", 3)

    def _class_sneak_ok(self, att: dict, tgt: dict) -> bool:
        """Sneak Attack without an ally beside the target: Rakish Audacity (nobody else within 5 ft of you), Insightful Fighting."""
        char = self._sheet(att)
        if not char:
            return False
        if any((e.get("mods") or {}).get("insight_vs") == tgt["id"] for e in att.get("effects") or []):
            return True
        if F.sub_at(char, "Rogue", "Swashbuckler", 3) and att.get("pos") and tgt.get("pos") and self._dist(att, tgt) <= 5:
            return not any(o is not att and o is not tgt and o.get("pos") and self._alive(o) and self._dist(o, att) <= 5
                           for o in self.b["combatants"])
        return False

    # ------------------------------------------------------------------ dropping, kills, turns
    def _class_zero_hp(self, c: dict, dealt: int, types, crit: bool) -> bool:
        """Relentless Rage (a raging barbarian's Constitution save), Strength of the Grave: True when it stays at 1 HP."""
        char = self._sheet(c)
        if not char or c.get("form") or self._dead(c):
            return False
        if self._subb_zero_hp(c, dealt, types, crit):          # Undying Sentinel (subfeats_b.py)
            return True
        if self._subc_zero_hp(c, dealt, types, crit):          # Rage beyond Death, Faithful Summons (subfeats_c.py)
            return True
        if self._subd_zero_hp(c, dealt, types, crit):          # Necrotic Husk (subfeats_d.py)
            return True
        if self._nf_zero_hp(c, dealt, types, crit):            # Boon of Misty Escape (newfeats.py)
            return True
        if char.class_level("Barbarian") >= 11 and self._raging(c):
            dc = 10 + 5 * int(c.get("rr_n") or 0)
            c["rr_n"] = int(c.get("rr_n") or 0) + 1
            res = self._saving_throw(c, "con", dc, label="Relentless Rage")
            self._say(f"{c['name']} Relentless Rage: CON save {res['total']} vs DC {dc} — " + ("drops to 1 HP instead" if res["ok"] else "falls"))
            if res["ok"]:
                self._set_hp(c, 1)
                return True
        if F.sub_at(char, "Sorcerer", "Shadow Magic", 1) and not crit and "radiant" not in types and self._cf_left(c, "Strength of the Grave", 1):
            res = self._saving_throw(c, "cha", 5 + int(dealt), label="Strength of the Grave")
            self._say(f"{c['name']} Strength of the Grave: CHA save {res['total']} vs DC {5 + int(dealt)} — "
                      + ("drops to 1 HP instead" if res["ok"] else "falls"))
            if res["ok"]:
                self._cf_use(c, "Strength of the Grave")
                self._set_hp(c, 1)
                return True
        return False

    def _class_kill(self, by: Optional[dict], c: dict):
        """A creature dropped to 0: Dark One's Blessing (temporary hit points), a hexblade's curse paying back."""
        self._sub_killed(c)                                     # an echo destroyed: Reclaim Potential (subfeats.py)
        self._subb_kill(by, c)                                  # Touch of Death (subfeats_b.py)
        self._subd_kill(by, c)                                  # Master of Hexes (subfeats_d.py)
        self._nf_kill(by, c)                                    # Killer's Fortune, Siphon Life (newfeats.py)
        for e in list(c.get("effects") or []):
            hid = (e.get("mods") or {}).get("hex_curse")
            h = self._find_or_none(hid) if hid is not None else None
            hc = self._sheet(h) if h else None
            if hc and self._alive(h):
                n = max(1, hc.class_level("Warlock") + hc.mod("cha"))
                self._heal(h, n)
                self._say(f"{h['name']} regains {n} HP as the cursed {c['name']} falls (Hexblade's Curse)")
        m = self._monster(c) if c.get("kind") != "pc" else None
        if m and c.get("pos"):                                  # Keeper of Souls (Grave 17): a foe dies near the cleric
            for o in self.b["combatants"]:
                oc = self._sheet(o)
                if oc and F.sub_at(oc, "Cleric", "Grave Domain", 17) and self._hostile(o, c) and self._can_act(o) and self._within(o, c, 60) \
                        and self._cf_turn_free(o, "keeper"):
                    self._once_per_turn(o, "keeper")
                    hd = int((re.match(r"(\d+)", str(m.get("hp_formula") or "1")) or [0, 1])[1])
                    allies = [x for x in self.b["combatants"] if not self._hostile(o, x) and self._alive(x) and self._within(o, x, 60)]
                    if allies and hd:
                        x = min(allies, key=lambda a: self._hp_of(a) / max(1, self._max_hp(a)))
                        self._heal(x, hd)
                        self._say(f"{o['name']}'s Keeper of Souls: {x['name']} regains {hd} HP")
                    break
        char = self._sheet(by) if by else None
        if char and not by.get("form") and self._hostile(by, c) and F.sub_at(char, "Warlock", "The Hexblade", 6) and m \
                and "humanoid" in self._ctype(m) and self._cf_left(by, "Accursed Specter", 1) and bestiary.get("Specter|MM"):
            self._cf_use(by, "Accursed Specter")                # the slain humanoid rises as a specter that serves the hexblade
            sm = bestiary.get("Specter|MM")
            sp = self._new("enemy", self._label(f"Specter ({by['name']})", False), sm["hp"], sm["hp"], sm["ac"], ability_mod(sm, "dex"),
                           monster="Specter|MM", xp=0, faction=self._side(by), summoned_by=by["id"])
            self._add(sp, self.b["combatants"].index(by) + 1)
            if c.get("pos"):
                spot = self._free_near(sp, *c["pos"])
                if spot:
                    sp["pos"] = spot
            self._give_temp(sp, max(1, char.class_level("Warlock") // 2))
            self._say(f"{c['name']} rises as a specter in {by['name']}'s service (Accursed Specter)")
        if char and not by.get("form") and self._hostile(by, c) and F.sub_at(char, "Warlock", "The Fiend", 1):
            n = max(1, char.mod("cha") + char.class_level("Warlock"))
            self._give_temp(by, n)
            self._say(f"{by['name']} gains {n} temporary HP (Dark One's Blessing)")
        if char and not by.get("form") and F.sub_at(char, "Wizard", "School of Necromancy", 2) and by is not c \
                and self._ctype(self._monster(c)) not in ("undead", "construct") and self._cf_turn_free(by, "grim_harvest"):
            R = next((r for r in reversed(self._stack()) if r.get("kind") == "strike" and r.get("spell") and r.get("actor") == by["id"]), None)
            sp = rules.spell(re.sub(r"\s*\(.*\)$", "", str((R or {}).get("label") or ""))) if R else None
            if sp and sp.get("level"):                          # Grim Harvest: once a turn, a spell of 1st level or higher
                self._once_per_turn(by, "grim_harvest")
                n = (3 if sp.get("school") == "Necromancy" else 2) * int(R.get("slot_level") or sp["level"])
                self._heal(by, n)
                self._say(f"{by['name']} reaps {n} HP (Grim Harvest)")

    def _class_turn_start(self, c: dict):
        """Twilight Sanctuary's temporary hit points, a spore druid's Halo of Spores, a gloom stalker's first turn."""
        if not self._alive(c):
            return
        self._subd_turn_start(c)                                # Event Horizon, Dread Lord (subfeats_d.py)
        self._nf_turn_start(c)                                  # Fortifying Light (newfeats.py)
        for e, v in self._fx(c, "twilight"):
            src = self._find_or_none(e.get("source_id"))
            if src is None or self._hostile(src, c):
                continue
            had = [x for x in ("Charmed", "Frightened") if x in self._conds(c)]
            if had:
                self._clear_conditions(c, had[:1])
                self._say(f"{c['name']} shakes off being {had[0].lower()} (Twilight Sanctuary)")
            else:
                n = roll(v)
                self._give_temp(c, n)
                self._say(f"{c['name']} gains {n} temporary HP (Twilight Sanctuary)")
            break
        char = self._sheet(c)
        if char and self.b.get("round") == 1 and F.sub_at(char, "Ranger", "Gloom Stalker", 3) and not c.get("form"):
            self._effect_on(c, "Dread Ambusher", [], None, None, None, None, c["name"], {"speed": 10}, None, c["id"], until={"end": c["id"], "skip": 0})
            t = c.get("turn")
            if t is not None:
                t["move"] = t.get("move", 0) + 10
        if not c.get("pos"):
            return
        if char and self.b.get("round") == 1 and char.class_level("Monk") >= 20 and self._resource_left(c, "Ki Points") == 0:
            char.d["resources"]["Ki Points"] = max(0, int(char.d["resources"].get("Ki Points") or 0) - 4)     # Perfect Self
            char.save()
            self._say(f"{c['name']} regains 4 ki (Perfect Self)")
        if char and self.b.get("round") == 1 and char.class_level("Bard") >= 20 and self._resource_left(c, "Bardic Inspiration") == 0:
            char.d["resources"]["Bardic Inspiration"] = max(0, int(char.d["resources"].get("Bardic Inspiration") or 0) - 1)
            char.save()
            self._say(f"{c['name']} regains a Bardic Inspiration (Superior Inspiration)")
        for o in self.b["combatants"]:
            if o.get("pos") and self._hostile(o, c) and self._dist(o, c) <= 5 and self._can_act(o):
                for e, n in self._fx(o, "flies"):                   # Cloak of Flies
                    if int(n) > 0:
                        self._say(f"{o['name']}'s Cloak of Flies: " + self._deal(c, [[int(n), "poison"]], by=o, label="Cloak of Flies"))
            if o.get("pos") and self._hostile(o, c) and self._can_act(o) and self._dist(o, c) <= 30:
                for e, n in self._fx(o, "nimbus"):                  # Holy Nimbus
                    self._say(f"{o['name']}'s Holy Nimbus: " + self._deal(c, [[int(n), "radiant"]], by=o, label="Holy Nimbus"))
                for e, dc in self._fx(o, "menace"):                 # Avenging Angel: the aura of menace, once per creature
                    key = f"menace:{o['id']}"
                    if key not in (c.get("aura_immune") or []):
                        c.setdefault("aura_immune", []).append(key)
                        res = self._saving_throw(c, "wis", int(dc), label="Avenging Angel")
                        if not res["ok"]:
                            self._effect_on(c, "Avenging Angel (frightened)", ["Frightened"], None, None, None, 10, o["name"], {"attacks_against": "adv"},
                                            None, o["id"], ends_on=["damage"])
                        self._say(f"{c['name']} WIS save vs the Avenging Angel: {res['total']} vs DC {dc} — " + ("steady" if res["ok"] else "frightened"))
            oc = self._sheet(o)
            if oc and "Frightened" in self._conds(c) and F.sub_at(oc, "Paladin", "Oath of Conquest", 7) and self._hostile(o, c) \
                    and o.get("pos") and self._can_act(o) and self._dist(o, c) <= (30 if oc.class_level("Paladin") >= 18 else 10):
                self._say(f"{o['name']}'s Aura of Conquest: " + self._deal(c, [[oc.class_level("Paladin") // 2, "psychic"]], by=o,
                                                                           label="Aura of Conquest"))
            if not oc or o.get("form") or not F.sub_at(oc, "Druid", "Circle of Spores", 2) or not self._hostile(o, c) or not o.get("pos"):
                continue
            if self._dist(o, c) > 10 or not self._may_react(o) or self._react_mode(o, "halo") == "never" or not self._sees(o, c) \
                    or self._spores_cube(o):                    # Spreading Spores (subfeats_b.py) stops the Halo
                continue
            lv = oc.class_level("Druid")
            die = 10 if lv >= 14 else 8 if lv >= 10 else 6 if lv >= 6 else 4
            n = 2 if self._fx(o, "symbiotic") else 1
            self._spend_reaction(o, "Halo of Spores")
            res = self._saving_throw(c, "con", self._cf_dc(oc, "wis"), label="Halo of Spores")
            if res["ok"]:
                self._say(f"{o['name']}'s Halo of Spores: {c['name']} resists (CON {res['total']})")
            else:
                self._say(f"{o['name']}'s Halo of Spores: " + self._deal(c, [[f"{n}d{die}", "necrotic"]], by=o, label="Halo of Spores"))

    # ------------------------------------------------------------------ reactions and on-hit choices
    def _class_families(self, c: dict) -> List[str]:
        char = self._sheet(c)
        if not char:
            return []
        out = []

        def fam(key, ok):
            if ok:
                out.append(key)
        fam("flare", F.sub_at(char, "Cleric", "Light Domain", 1))
        fam("protection", char.has_option("Protection"))
        fam("interception", char.has_option("Interception"))
        fam("deflection", F.sub_at(char, "Wizard", "War Magic", 2))
        fam("illusory_self", F.sub_at(char, "Wizard", "School of Illusion", 10))
        fam("entropic_ward", F.sub_at(char, "Warlock", "The Great Old One", 6))
        fam("shadowy_dodge", F.sub_at(char, "Ranger", "Gloom Stalker", 15))
        fam("death_door", F.sub_at(char, "Cleric", "Grave Domain", 6))
        fam("guided_strike", F.sub_at(char, "Cleric", "War Domain", 2) or F.sub_at(char, "Paladin", "Oath of Conquest", 3))
        fam("favored_gods", F.sub_at(char, "Sorcerer", "Divine Soul", 1))
        fam("giant_killer", CF.has(char, "hunters_prey") and CF.is_on(char, "hunters_prey") == "Giant Killer")
        fam("storm_wrath", F.sub_at(char, "Cleric", "Tempest Domain", 1))
        fam("stones_endurance", char.has_feature("Stone's Endurance"))
        fam("song_defense", F.sub_at(char, "Wizard", "Bladesinging", 10))
        fam("spirit_shield", F.sub_at(char, "Barbarian", "Path of the Ancestral Guardian", 6))
        fam("fanatical_focus", F.sub_at(char, "Barbarian", "Path of the Zealot", 6))
        fam("dark_luck", F.sub_at(char, "Warlock", "The Fiend", 6))
        fam("diamond_soul", char.class_level("Monk") >= 14)
        fam("eldritch_smite", char.has_option("Eldritch Smite"))
        fam("psychic_blades", F.sub_at(char, "Bard", "College of Whispers", 3))
        fam("hand_of_harm", F.sub_at(char, "Monk", "Way of Mercy", 3))
        fam("open_hand", F.sub_at(char, "Monk", "Way of the Open Hand", 3))
        fam("fury_small", char.has_feature("Fury of the Small"))
        fam("sweep", char.has_option("Sweeping Attack"))
        fam("halo", F.sub_at(char, "Druid", "Circle of Spores", 2))
        fam("arcane_shot", F.sub_at(char, "Fighter", "Arcane Archer", 3))
        fam("psionic_strike", F.sub_at(char, "Fighter", "Psi Warrior", 3))
        fam("protective_field", F.sub_at(char, "Fighter", "Psi Warrior", 3))
        fam("flourish", F.sub_at(char, "Bard", "College of Swords", 3))
        fam("projected_ward", F.sub_at(char, "Wizard", "School of Abjuration", 6))
        fam("misty_escape", F.sub_at(char, "Warlock", "The Archfey", 6))
        fam("armor_of_hexes", F.sub_at(char, "Warlock", "The Hexblade", 10))
        fam("lucky_footwork", char.has_feature("Lucky Footwork"))
        fam("saving_face", char.has_feature("Saving Face") or char.has_feature("Fortune from the Many"))
        fam("arcane_jolt", F.sub_at(char, "Artificer", "Battle Smith", 9))
        fam("flash", char.class_level("Artificer") >= 7)
        fam("war_god", F.sub_at(char, "Cleric", "War Domain", 6))
        fam("runic_shield", F.sub_at(char, "Fighter", "Rune Knight", 7))
        fam("glorious_defense", F.sub_at(char, "Paladin", "Oath of Glory", 15))
        fam("tail", F.sub_at(char, "Barbarian", "Path of the Beast", 3))
        fam("bm_parry", char.has_option("Parry"))
        fam("portent", F.sub_at(char, "Wizard", "School of Divination", 2))
        fam("bend_luck", F.sub_at(char, "Sorcerer", "Wild Magic", 6))
        fam("omen", F.sub_at(char, "Druid", "Circle of Stars", 6))
        fam("bountiful", "Bountiful Luck" in (char.d.get("feats") or []))
        fam("quivering", F.sub_at(char, "Monk", "Way of the Open Hand", 17))
        fam("brace", char.has_option("Brace"))
        fam("skirmisher", F.sub_at(char, "Rogue", "Scout", 3))
        fam("shield_master", CF.has(char, "shield_master"))
        fam("vengeful", char.has_feature("Vengeful Assault"))
        fam("balance", F.sub_at(char, "Sorcerer", "Clockwork Soul", 1))
        fam("focused_aim", char.class_level("Monk") >= 5 and char.has_feature("Focused Aim"))
        fam("seeking_spell", char.has_option("Seeking Spell"))
        fam("stroke_of_luck", char.class_level("Rogue") >= 20)
        fam("tomb", char.has_option("Tomb of Levistus"))
        fam("talisman_rebuke", char.has_option("Rebuke of the Talisman"))
        fam("talisman_protect", char.has_option("Protection of the Talisman"))
        fam("storm_rune", char.has_option("Storm Rune"))
        fam("fire_rune", char.has_option("Fire Rune"))
        fam("vigilant", char.has_feature("Vigilant Guardian"))
        fam("stalkers_flurry", F.sub_at(char, "Ranger", "Gloom Stalker", 11))
        fam("master_duelist", F.sub_at(char, "Rogue", "Swashbuckler", 17))
        fam("warding_maneuver", F.sub_at(char, "Fighter", "Cavalier", 7))
        fam("backlash", F.sub_at(char, "Barbarian", "Path of Wild Magic", 10))
        fam("wolf_prone", F.sub_at(char, "Barbarian", "Path of the Totem Warrior", 14))
        fam("infectious_fury", F.sub_at(char, "Barbarian", "Path of the Beast", 10))
        out += self._sub_families(char)                         # Shadow Martyr, Homing Strikes, Storm's Fury (subfeats.py)
        if self._fx(c, "bond"):
            out.append("bond")
        if self._fx(c, "legend"):
            out += ["legend", "legend_save"]
        fam("rebuke_violent", F.sub_at(char, "Paladin", "Oath of Redemption", 3))
        fam("guardian", F.sub_at(char, "Paladin", "Oath of Redemption", 7))
        fam("dampen", F.sub_at(char, "Cleric", "Nature Domain", 6))
        if self._fx(c, "valor"):
            out += ["valor", "valor_ac"]
        return out

    @staticmethod
    def _cf_psi_die(char) -> str:
        lv = char.class_level("Fighter")
        return "1d12" if lv >= 17 else "1d10" if lv >= 11 else "1d8" if lv >= 5 else "1d6"

    def _cf_face(self, c: dict) -> int:
        """Saving Face / Fortune from the Many: +1 for each ally within 30 ft that the hobgoblin can see (at most 5)."""
        return min(5, sum(1 for o in self.b["combatants"] if o is not c and not self._hostile(c, o) and self._alive(o)
                          and self._within(c, o, 30) and self._sees(c, o)))

    def _cf_face_ok(self, c: dict, char) -> bool:
        if char.has_feature("Fortune from the Many"):
            return bool(self._cf_left(c, "Fortune from the Many", char.proficiency_bonus)) and self._cf_face(c) > 0
        return char.has_feature("Saving Face") and bool(self._cf_left(c, "Saving Face", 1, "short")) and self._cf_face(c) > 0

    def _cf_wis_uses(self, c: dict, name: str) -> int:
        char = self._sheet(c)
        return self._cf_left(c, name, max(1, char.mod("wis"))) if char else 0

    def _class_eligible(self, out: list, window: str, R: dict, att: Optional[dict], tgt: Optional[dict], ctx: dict):
        """Adds the class features' options to the window's questions (reactions._eligible)."""
        cur = R.get("cur") or {}
        a = R.get("atk") or {}
        self._cf_luck(out, window, R, att, tgt)                 # Portent, Bend Luck, Cosmic Omen
        self._sub_eligible(out, window, R, att, tgt, ctx)       # Shadow Martyr, Homing Strikes, Storm's Fury (subfeats.py)
        if window == "hit" and att and tgt:
            tc = self._sheet(tgt)
            if tc and not tgt.get("form") and self._may_react(tgt):
                opts = []
                if F.sub_at(tc, "Wizard", "War Magic", 2):
                    opts.append({"key": "deflection", "label": "Arcane Deflection (+2 AC)", "detail": ""})
                if F.sub_at(tc, "Wizard", "School of Illusion", 10) and self._cf_left(tgt, "Illusory Self", 1, "short"):
                    opts.append({"key": "illusory_self", "label": "Illusory Self (the attack misses)", "detail": ""})
                if F.sub_at(tc, "Warlock", "The Great Old One", 6) and self._cf_left(tgt, "Entropic Ward", 1, "short"):
                    opts.append({"key": "entropic_ward", "label": "Entropic Ward (the attacker rerolls, keeps the lower)", "detail": ""})
                if F.sub_at(tc, "Ranger", "Gloom Stalker", 15) and cur.get("mode") != "adv":
                    opts.append({"key": "shadowy_dodge", "label": "Shadowy Dodge (the attacker rerolls, keeps the lower)", "detail": ""})
                if F.sub_at(tc, "Warlock", "The Hexblade", 10) and any((e.get("mods") or {}).get("hex_curse") == tgt["id"] for e in att.get("effects") or []):
                    opts.append({"key": "armor_of_hexes", "label": "Armor of Hexes (d6: 4 or more and it misses)", "detail": ""})
                for _e, die in self._fx(tgt, "valor")[:1]:
                    opts.append({"key": "valor_ac", "label": f"Combat Inspiration: +{die} AC", "detail": ""})
                if F.sub_at(tc, "Barbarian", "Path of the Beast", 3) and self._raging(tgt) and self._dist(att, tgt) <= 10 and self._sees(tgt, att):
                    opts.append({"key": "tail", "label": "Beast Tail (+1d8 AC against this attack)", "detail": ""})
                self._cf_offer(out, tgt, "reaction", opts, f"{att['name']} hits {tgt['name']} ({cur.get('total')} vs AC {cur.get('ac')}). React?")
            for o in self.b["combatants"]:
                oc = self._sheet(o)
                if not oc or o.get("form") or self._hostile(o, tgt) or not o.get("pos") or not self._may_react(o):
                    continue
                opts = []
                if F.sub_at(oc, "Cleric", "Light Domain", 1) and (o is tgt or oc.class_level("Cleric") >= 6) and self._cf_wis_uses(o, "Warding Flare") \
                        and self._dist(o, att) <= 30 and self._sees(o, att):
                    opts.append({"key": "flare", "label": f"Warding Flare on {att['name']} (reroll, keep the lower)", "detail": ""})
                if o is not tgt and oc.has_option("Protection") and oc.equipped_shield() and self._dist(o, tgt) <= 5 and self._sees(o, att):
                    opts.append({"key": "protection", "label": f"Protection: shield {tgt['name']} (reroll, keep the lower)", "detail": ""})
                if cur.get("crit") and F.sub_at(oc, "Cleric", "Grave Domain", 6) and self._dist(o, tgt) <= 30 and self._cf_wis_uses(o, "Sentinel at Death's Door"):
                    opts.append({"key": "death_door", "label": "Sentinel at Death's Door (the critical becomes a normal hit)", "detail": ""})
                if o is not tgt and oc.has_feature("Vigilant Guardian") and self._dist(o, tgt) <= 5 and self._cf_left(o, "Vigilant Guardian", 1):
                    opts.append({"key": "vigilant", "label": f"Vigilant Guardian: swap places, take the hit for {tgt['name']}", "detail": ""})
                if o is not tgt and F.sub_at(oc, "Fighter", "Rune Knight", 7) and self._dist(o, tgt) <= 60 and self._sees(o, att) \
                        and self._cf_left(o, "Runic Shield", oc.proficiency_bonus):
                    opts.append({"key": "runic_shield", "label": f"Runic Shield: {att['name']} rerolls (the new roll stands)", "detail": ""})
                if F.sub_at(oc, "Fighter", "Cavalier", 7) and self._dist(o, tgt) <= 5 and self._cf_left(o, "Warding Maneuver", max(1, oc.mod("con"))) \
                        and self._melee_weapon_of(o):
                    opts.append({"key": "warding_maneuver", "label": f"Warding Maneuver (+1d8 AC for {tgt['name']})", "detail": ""})
                if F.sub_at(oc, "Paladin", "Oath of Glory", 15) and self._dist(o, tgt) <= 10 and self._cf_left(o, "Glorious Defense", max(1, oc.mod("cha"))):
                    opts.append({"key": "glorious_defense", "label": f"Glorious Defense (+{max(1, oc.mod('cha'))} AC for {tgt['name']})", "detail": ""})
                self._cf_offer(out, o, "reaction", opts, f"{att['name']} hits {tgt['name']} ({cur.get('total')} vs AC {cur.get('ac')}). {o['name']}: react?")
        elif window == "missed" and att and tgt:
            ac_ = self._sheet(att)
            need = cur.get("ac", 0) - cur.get("total", 0)
            if ac_ and not att.get("form"):
                opts = []
                if 0 < need <= 10 and (F.sub_at(ac_, "Cleric", "War Domain", 2) and self._resource_left(att, "Channel Divinity (Cleric)")
                                       or F.sub_at(ac_, "Paladin", "Oath of Conquest", 3) and self._resource_left(att, "Channel Divinity (Paladin)")):
                    opts.append({"key": "guided_strike", "label": "Guided Strike (+10, a Channel Divinity)", "detail": f"{cur.get('total')} vs AC {cur.get('ac')}"})
                if 0 < need <= 8 and F.sub_at(ac_, "Sorcerer", "Divine Soul", 1) and self._cf_left(att, "Favored by the Gods", 1, "short"):
                    opts.append({"key": "favored_gods", "label": "Favored by the Gods (+2d4)", "detail": f"{cur.get('total')} vs AC {cur.get('ac')}"})
                if 0 < need <= 5 and self._cf_face_ok(att, ac_) and need <= self._cf_face(att):
                    opts.append({"key": "saving_face", "label": f"Saving Face (+{self._cf_face(att)})", "detail": f"{cur.get('total')} vs AC {cur.get('ac')}"})
                for _e, die in self._fx(att, "valor")[:1]:
                    opts.append({"key": "valor:attack", "label": f"Combat Inspiration: +{die} to the attack", "detail": f"{cur.get('total')} vs AC {cur.get('ac')}"})
                if F.sub_at(ac_, "Rogue", "Swashbuckler", 17) and cur.get("mode") != "dis" and self._cf_left(att, "Master Duelist", 1, "short"):
                    opts.append({"key": "master_duelist", "label": "Master Duelist: reroll with advantage", "detail": ""})
                if ac_.class_level("Monk") >= 5 and ac_.has_feature("Focused Aim") and 0 < need <= 6 and self._resource_left(att, "Ki Points") >= (need + 1) // 2:
                    k = (need + 1) // 2
                    opts.append({"key": f"focused_aim:{k}", "label": f"Focused Aim ({k} ki: +{2 * k})", "detail": ""})
                if ac_.class_level("Rogue") >= 20 and self._cf_left(att, "Stroke of Luck", 1, "short"):
                    opts.append({"key": "stroke_of_luck", "label": "Stroke of Luck: the miss becomes a hit", "detail": ""})
                if a.get("spell") and ac_.has_option("Seeking Spell") and self._resource_left(att, "Sorcery Points") >= 2:
                    opts.append({"key": "seeking_spell", "label": "Seeking Spell: reroll the spell attack (2 sorcery points)", "detail": ""})
                if self._fx(att, "legend") and self._cf_turn_free(att, "legend"):
                    opts.append({"key": "legend", "label": "Living Legend: the miss becomes a hit", "detail": ""})
                if a.get("weapon") and F.sub_at(ac_, "Ranger", "Gloom Stalker", 11) and self.b.get("turn") == att["id"] \
                        and self._cf_turn_free(att, "stalkers_flurry"):
                    opts.append({"key": "stalkers_flurry", "label": "Stalker's Flurry: attack again", "detail": ""})
                self._cf_offer(out, att, "free", opts, f"{att['name']} misses {tgt['name']} ({cur.get('total')} vs AC {cur.get('ac')}). Add something?")
            if 0 < need <= 10:
                for o in self.b["combatants"]:
                    oc = self._sheet(o)
                    if o is att or not oc or o.get("form") or self._hostile(o, att) or not F.sub_at(oc, "Cleric", "War Domain", 6) \
                            or not self._may_react(o) or self._dist(o, att) > 30 or not self._resource_left(o, "Channel Divinity (Cleric)"):
                        continue
                    self._cf_offer(out, o, "reaction", [{"key": "war_god", "label": f"War God's Blessing: +10 to {att['name']}'s attack",
                                                         "detail": f"{cur.get('total')} vs AC {cur.get('ac')}"}],
                                   f"{att['name']} misses {tgt['name']} ({cur.get('total')} vs AC {cur.get('ac')}). {o['name']}: bless the strike?")
            self._cf_giant_killer(out, att, tgt, None)
        elif window == "after_damage" and att and tgt and tgt is not att:
            tc = self._sheet(tgt)
            if tc and not tgt.get("form") and self._alive(tgt) and self._may_react(tgt):
                if F.sub_at(tc, "Cleric", "Tempest Domain", 1) and self._dist(tgt, att) <= 5 and self._cf_wis_uses(tgt, "Wrath of the Storm"):
                    self._cf_offer(out, tgt, "reaction", [{"key": "storm_wrath", "label": f"Wrath of the Storm on {att['name']} (2d8)", "detail": ""}],
                                   f"{att['name']} hit {tgt['name']}. Wrath of the Storm?", "after_damage")
                self._cf_giant_killer(out, att, tgt, "after_damage")
                if tc.has_option("Rebuke of the Talisman") and R.get("mode") == "attack" and self._dist(tgt, att) <= 30:
                    self._cf_offer(out, tgt, "reaction", [{"key": "talisman_rebuke", "label": f"Rebuke of the Talisman ({tc.proficiency_bonus} "
                                                                                              f"psychic, pushed 10 ft)", "detail": ""}],
                                   f"{att['name']} hit {tgt['name']}. Rebuke of the Talisman?", "after_damage")
                if F.sub_at(tc, "Barbarian", "Path of Wild Magic", 10) and self._raging(tgt):
                    self._cf_offer(out, tgt, "reaction", [{"key": "backlash", "label": "Unstable Backlash (a new Wild Surge)", "detail": ""}],
                                   f"{att['name']} hurt {tgt['name']}. Unstable Backlash?", "after_damage")
                if tc.has_feature("Vengeful Assault") and self._dist(tgt, att) <= 5 and self._cf_left(tgt, "Vengeful Assault", 1, "short") \
                        and self._melee_weapon_of(tgt):
                    self._cf_offer(out, tgt, "reaction", [{"key": "vengeful", "label": f"Vengeful Assault: attack {att['name']}", "detail": ""}],
                                   f"{att['name']} hurt {tgt['name']}. Strike back?", "after_damage")
                if F.sub_at(tc, "Warlock", "The Archfey", 6) and self._cf_left(tgt, "Misty Escape", 1, "short"):
                    self._cf_offer(out, tgt, "reaction", [{"key": "misty_escape", "label": "Misty Escape (turn invisible)", "detail": ""}],
                                   f"{att['name']} hurt {tgt['name']}. Misty Escape?", "after_damage")
            dealt = int((R.get("dealt") or {}).get(str(tgt["id"])) or 0)
            for o in self.b["combatants"] if dealt > 0 else ():
                oc = self._sheet(o)
                if o is tgt or o is att or not oc or o.get("form") or not F.sub_at(oc, "Paladin", "Oath of Redemption", 3) or self._hostile(o, tgt) \
                        or not o.get("pos") or not att.get("pos") or self._dist(o, att) > 30 or not self._may_react(o) \
                        or not self._resource_left(o, "Channel Divinity (Paladin)") or not self._sees(o, att):
                    continue
                self._cf_offer(out, o, "reaction", [{"key": f"rebuke_violent:{dealt}", "label": f"Rebuke the Violent ({att['name']}: {dealt} radiant, Wis save half)",
                                                     "detail": ""}], f"{att['name']} hurt {tgt['name']}. {o['name']}: Rebuke the Violent?", "after_damage")
        elif window == "damage" and tgt:
            total = sum(n for n, _t in cur.get("dmg") or [])
            if total <= 0:
                return
            tc = self._sheet(tgt)
            if tc and not tgt.get("form") and self._may_react(tgt):
                opts = []
                if tc.has_feature("Stone's Endurance") and self._cf_left(tgt, "Stone's Endurance", tc.proficiency_bonus if F.mpmm(tc) else 1,
                                                                          "long" if F.mpmm(tc) else "short"):
                    opts.append({"key": "stones_endurance", "label": f"Stone's Endurance (-1d12{tc.mod('con'):+d})", "detail": ""})
                if F.sub_at(tc, "Wizard", "Bladesinging", 10) and self._fx(tgt, "conc_bonus"):
                    left = SC.slots_remaining(tc)
                    for k in sorted((k for k in left if k != SC.PACT_KEY and left[k] > 0), key=int)[:3]:
                        opts.append({"key": f"song_defense:{k}", "label": f"Song of Defense, level {k} slot (-{5 * int(k)})", "detail": ""})
                if F.sub_at(tc, "Fighter", "Psi Warrior", 3) and self._cf_left(tgt, "Psionic Energy", 2 * tc.proficiency_bonus):
                    opts.append({"key": "protective_field", "label": f"Protective Field (-{self._cf_psi_die(tc)}{tc.mod('int'):+d})", "detail": ""})
                if tc.has_option("Tomb of Levistus") and self._cf_left(tgt, "Tomb of Levistus", 1, "short"):
                    opts.append({"key": "tomb", "label": f"Tomb of Levistus ({10 * tc.class_level('Warlock')} temporary HP, then encased in ice)",
                                 "detail": ""})
                if R.get("mode") == "attack" and (R.get("atk") or {}).get("melee") and tc.has_option("Parry") and self._resource_left(tgt, "Superiority Dice"):
                    opts.append({"key": "bm_parry", "label": f"Parry (-1{F.superiority_die(tc)}{tc.mod('dex'):+d})", "detail": ""})
                mine = sorted({t for _n, t in cur.get("dmg") or []} & {"acid", "cold", "fire", "lightning", "thunder"})
                if mine and F.sub_at(tc, "Cleric", "Nature Domain", 6):
                    opts.append({"key": "dampen", "label": f"Dampen Elements (resist {mine[0]})", "detail": ""})
                self._cf_offer(out, tgt, "reaction", opts, f"{tgt['name']} is about to take {total} damage from {R['label']}. React?")
            for o in self.b["combatants"]:
                oc = self._sheet(o)
                if o is tgt or not oc or o.get("form") or self._hostile(o, tgt) or not o.get("pos") or not tgt.get("pos") or not self._may_react(o):
                    continue
                opts = []
                if R.get("mode") == "attack" and oc.has_option("Interception") and self._dist(o, tgt) <= 5 \
                        and (oc.equipped_shield() or any("unarmed" not in (w.get("props") or []) and not w.get("ranged") for w in oc.attacks())):
                    opts.append({"key": "interception", "label": f"Interception (-1d10{oc.proficiency_bonus:+d} to {tgt['name']}'s damage)", "detail": ""})
                if F.sub_at(oc, "Barbarian", "Path of the Ancestral Guardian", 6) and self._raging(o) and self._dist(o, tgt) <= 30:
                    lv = oc.class_level("Barbarian")
                    opts.append({"key": "spirit_shield", "label": f"Spirit Shield (-{'4d6' if lv >= 14 else '3d6' if lv >= 10 else '2d6'} to {tgt['name']}'s damage)",
                                 "detail": ""})
                if F.sub_at(oc, "Fighter", "Psi Warrior", 3) and self._dist(o, tgt) <= 30 and self._cf_left(o, "Psionic Energy", 2 * oc.proficiency_bonus):
                    opts.append({"key": "protective_field", "label": f"Protective Field (-{self._cf_psi_die(oc)}{oc.mod('int'):+d} to {tgt['name']}'s damage)",
                                 "detail": ""})
                if F.sub_at(oc, "Paladin", "Oath of Redemption", 7) and self._dist(o, tgt) <= (30 if oc.class_level("Paladin") >= 18 else 10):
                    opts.append({"key": "guardian", "label": f"Aura of the Guardian (take {tgt['name']}'s {total} damage)", "detail": ""})
                elems = sorted({t for _n, t in cur.get("dmg") or []} & {"acid", "cold", "fire", "lightning", "thunder"})
                if elems and F.sub_at(oc, "Cleric", "Nature Domain", 6) and self._dist(o, tgt) <= 30:
                    opts.append({"key": "dampen", "label": f"Dampen Elements ({tgt['name']} resists {elems[0]})", "detail": ""})
                if F.sub_at(oc, "Wizard", "School of Abjuration", 6) and (o.get("ward") or {}).get("hp", 0) > 0 and self._dist(o, tgt) <= 30:
                    opts.append({"key": "projected_ward", "label": f"Projected Ward (your Arcane Ward takes it: {o['ward']['hp']} HP)", "detail": ""})
                self._cf_offer(out, o, "reaction", opts, f"{tgt['name']} is about to take {total} damage. {o['name']}: react?")
        elif window == "save_failed" and tgt:
            tc = self._sheet(tgt)
            if not tc or tgt.get("form") or cur.get("auto"):
                return
            short = int(R["sv"]["dc"]) - int(cur.get("total") or 0)
            opts = []
            if F.sub_at(tc, "Wizard", "War Magic", 2) and short <= 4 and self._may_react(tgt):
                opts.append({"key": "deflection", "label": "Arcane Deflection (+4 to the save; a reaction)", "detail": ""})
            if F.sub_at(tc, "Barbarian", "Path of the Zealot", 6) and self._raging(tgt):
                rage = next((e for e, _v in self._fx(tgt, "rage")), None)
                if rage is not None and not rage.get("focus_used"):
                    opts.append({"key": "fanatical_focus", "label": "Fanatical Focus: reroll the save", "detail": ""})
            if F.sub_at(tc, "Warlock", "The Fiend", 6) and short <= 10 and self._cf_left(tgt, "Dark One's Own Luck", 1, "short"):
                opts.append({"key": "dark_luck", "label": "Dark One's Own Luck (+1d10)", "detail": ""})
            if F.sub_at(tc, "Sorcerer", "Divine Soul", 1) and short <= 8 and self._cf_left(tgt, "Favored by the Gods", 1, "short"):
                opts.append({"key": "favored_gods", "label": "Favored by the Gods (+2d4)", "detail": ""})
            if tc.class_level("Monk") >= 14 and self._resource_left(tgt, "Ki Points") >= 1:
                opts.append({"key": "diamond_soul", "label": "Diamond Soul: reroll the save (1 ki)", "detail": ""})
            if self._fx(tgt, "legend") and self._may_react(tgt):
                opts.append({"key": "legend_save", "label": "Living Legend: reroll the save (a reaction)", "detail": ""})
            if tc.has_option("Protection of the Talisman") and short <= 4 and self._cf_left(tgt, "Protection of the Talisman", tc.proficiency_bonus):
                opts.append({"key": "talisman_protect", "label": "Protection of the Talisman (+1d4)", "detail": ""})
            if R["sv"].get("ab") == "dex" and short <= 4 and tc.has_feature("Lucky Footwork") and self._may_react(tgt):
                opts.append({"key": "lucky_footwork", "label": "Lucky Footwork (+1d4; a reaction)", "detail": ""})
            if short <= 5 and self._cf_face_ok(tgt, tc) and short <= self._cf_face(tgt):
                opts.append({"key": "saving_face", "label": f"Saving Face (+{self._cf_face(tgt)})", "detail": ""})
            self._cf_offer(out, tgt, "free", opts, f"{tgt['name']} failed its {R['sv']['ab'].upper()} save ({cur.get('total')} vs DC {R['sv']['dc']}). Reroll it?")
            for o in self.b["combatants"]:
                oc = self._sheet(o)
                if not oc or o.get("form") or oc.class_level("Artificer") < 7 or self._hostile(o, tgt) or not self._may_react(o):
                    continue
                n = max(1, oc.mod("int"))
                if short <= n and self._dist(o, tgt) <= 30 and self._cf_left(o, "Flash of Genius", n):
                    self._cf_offer(out, o, "reaction", [{"key": "flash", "label": f"Flash of Genius (+{n} to {tgt['name']}'s save)", "detail": ""}],
                                   f"{tgt['name']} failed a save by {short}. {o['name']}: Flash of Genius?")
        elif window == "on_hit" and att and tgt:
            ac_ = self._sheet(att)
            if not ac_ or att.get("form"):
                return
            opts = []
            weapon = bool(a.get("weapon"))
            if weapon and ac_.has_option("Eldritch Smite") and SC.slots_remaining(ac_).get(SC.PACT_KEY) and self._cf_turn_free(att, "eldritch_smite"):
                lvl = (SC.spell_slots(ac_).get("pact") or {}).get("level", 1)
                opts.append({"key": "eldritch_smite", "label": f"Eldritch Smite (pact slot: +{1 + lvl}d8 force, prone)", "detail": ""})
            if weapon and F.sub_at(ac_, "Bard", "College of Whispers", 3) and self._resource_left(att, "Bardic Inspiration") \
                    and self._cf_turn_free(att, "psychic_blades"):
                opts.append({"key": "psychic_blades", "label": f"Psychic Blades (+{self._cf_blades(ac_)} psychic, a Bardic Inspiration)", "detail": ""})
            if (a.get("unarmed") or "unarmed" in (a.get("props") or [])) and F.sub_at(ac_, "Monk", "Way of Mercy", 3) \
                    and self._resource_left(att, "Ki Points") and self._cf_turn_free(att, "hand_of_harm"):
                opts.append({"key": "hand_of_harm", "label": f"Hand of Harm (1 ki: +{F.martial_die(ac_)}{ac_.mod('wis'):+d} necrotic)", "detail": ""})
            if a.get("melee") and weapon and self._raging(att) and F.sub_at(ac_, "Barbarian", "Path of the Totem Warrior", 14) \
                    and CF.is_on(ac_, "totem_attunement") == "Wolf" and (att.get("turn") or {}).get("bonus", 0) > 0 and self.b.get("turn") == att["id"]:
                opts.append({"key": "wolf_prone", "label": "Wolf totem: knock it prone (bonus action)", "detail": ""})
            if weapon and self._raging(att) and F.sub_at(ac_, "Barbarian", "Path of the Beast", 10) and self._cf_turn_free(att, "infectious_fury") \
                    and self._cf_left(att, "Infectious Fury", ac_.proficiency_bonus):
                opts.append({"key": "infectious_fury", "label": "Infectious Fury (Wis save or 2d12 psychic)", "detail": ""})
            if (a.get("unarmed") or "unarmed" in (a.get("props") or [])) and F.sub_at(ac_, "Monk", "Way of the Open Hand", 17) \
                    and self._resource_left(att, "Ki Points") >= 3:
                opts.append({"key": "quivering", "label": "Quivering Palm (3 ki: set it vibrating)", "detail": ""})
            if str(R.get("label", "")).startswith("Flurry of Blows") and F.sub_at(ac_, "Monk", "Way of the Open Hand", 3):
                opts += [{"key": "open_hand:prone", "label": "Open Hand: Dex save or prone", "detail": ""},
                         {"key": "open_hand:push", "label": "Open Hand: Str save or pushed 15 ft", "detail": ""},
                         {"key": "open_hand:noreact", "label": "Open Hand: no reactions until your next turn", "detail": ""}]
            if ac_.has_feature("Fury of the Small") and _bigger(self._size_of(tgt), self._size_of(att)) \
                    and self._cf_left(att, "Fury of the Small", ac_.proficiency_bonus if F.mpmm(ac_) else 1, "long" if F.mpmm(ac_) else "short"):
                opts.append({"key": "fury_small", "label": f"Fury of the Small (+{self._cf_fury(ac_)})", "detail": ""})
            if weapon and self._resource_left(att, "Superiority Dice"):
                die = F.superiority_die(ac_)
                if a.get("melee") and ac_.has_option("Sweeping Attack") and self._cf_sweep_target(att, tgt):
                    opts.append({"key": "sweep", "label": f"Sweeping Attack (+{die} to another foe beside it)", "detail": ""})
                for nm in ("Lunging Attack", "Maneuvering Attack"):
                    if ac_.has_option(nm) and (nm != "Lunging Attack" or a.get("melee")):
                        opts.append({"key": f"maneuver:{nm}", "label": f"{nm} (+{die})", "detail": ""})
            if weapon and not a.get("melee") and F.sub_at(ac_, "Fighter", "Arcane Archer", 3) and self._cf_left(att, "Arcane Shot", 2, "short") \
                    and self._cf_turn_free(att, "arcane_shot"):
                for nm in ARCANE_SHOTS:
                    if ac_.has_option(nm):
                        opts.append({"key": f"arcane_shot:{nm}", "label": f"Arcane Shot: {nm}", "detail": ARCANE_SHOTS[nm]})
            if weapon and ac_.has_option("Fire Rune") and self._cf_left(att, "Fire Rune", 1, "short"):
                opts.append({"key": "fire_rune", "label": "Fire Rune (2d6 fire; Str save or restrained in burning shackles)", "detail": ""})
            if weapon and F.sub_at(ac_, "Fighter", "Psi Warrior", 3) and self._cf_turn_free(att, "psionic_strike") \
                    and self._cf_left(att, "Psionic Energy", 2 * ac_.proficiency_bonus):
                opts.append({"key": "psionic_strike", "label": f"Psionic Strike (+{self._cf_psi_die(ac_)}{ac_.mod('int'):+d} force)", "detail": ""})
            for _e, die in self._fx(att, "valor")[:1]:
                if weapon:
                    opts.append({"key": "valor:dmg", "label": f"Combat Inspiration: +{die} damage", "detail": ""})
            if weapon and a.get("magical") and F.sub_at(ac_, "Artificer", "Battle Smith", 9) and self._cf_turn_free(att, "arcane_jolt") \
                    and self._cf_left(att, "Arcane Jolt", max(1, ac_.mod("int"))):
                opts.append({"key": "arcane_jolt", "label": f"Arcane Jolt (+{'4d6' if ac_.class_level('Artificer') >= 15 else '2d6'} force)", "detail": ""})
            master = F.sub_at(ac_, "Bard", "College of Swords", 14)           # Master's Flourish: a d6 when no die is left
            if weapon and F.sub_at(ac_, "Bard", "College of Swords", 3) and (self._resource_left(att, "Bardic Inspiration") or master) \
                    and self._cf_turn_free(att, "flourish"):
                d = F.bardic_die(ac_) if self._resource_left(att, "Bardic Inspiration") else "1d6"
                opts += [{"key": "flourish:defensive", "label": f"Defensive Flourish (+{d} damage and AC)", "detail": ""},
                         {"key": "flourish:slashing", "label": f"Slashing Flourish (+{d} to it and another foe within 5 ft)", "detail": ""},
                         {"key": "flourish:mobile", "label": f"Mobile Flourish (+{d}, push 5 ft + the roll)", "detail": ""}]
            if opts:
                for item in out:
                    if item["reactor"] == att["id"] and item["cost"] == "free":
                        item["options"] += opts
                        return
                out.append({"reactor": att["id"], "cost": "free", "options": opts,
                            "text": f"{att['name']} hits {tgt['name']}" + (" (critical!)" if cur.get("crit") else "") + ". Add something?"})

    def _cf_portent(self, o: dict, oc) -> list:
        """A diviner's Portent dice, rolled when the battle first needs them (2, 3 from 14th level)."""
        if "portent" not in o:
            o["portent"] = [self.rng.randint(1, 20) for _ in range(3 if oc.class_level("Wizard") >= 14 else 2)]
            self._say(f"{o['name']}'s Portent dice: {', '.join(map(str, o['portent']))}")
        return o["portent"]

    def _cf_luck(self, out: list, window: str, R: dict, att: Optional[dict], tgt: Optional[dict]):
        """Rolls others make that a diviner, a wild mage or a stars druid can bend: an attack that hit (make it miss), an
        attack that missed or a save that failed (make it succeed). Portent replaces the d20; Bend Luck and Cosmic Omen add
        or take a die."""
        if window not in ("hit", "missed", "save_failed") or not tgt or (window != "save_failed" and not att):
            return
        cur = R.get("cur") or {}
        if cur.get("auto"):
            return
        roller = tgt if window == "save_failed" else att
        if window == "save_failed":
            need = int(R["sv"]["dc"]) - int(cur.get("total") or 0)            # it must rise by this
        elif window == "missed":
            need = cur.get("ac", 0) + cur.get("ac_extra", 0) - cur.get("total", 0)
        else:
            need = cur.get("total", 0) - cur.get("ac", 0) - cur.get("ac_extra", 0) + 1   # it must fall by this
        if need <= 0 or cur.get("crit") and window == "hit":
            return
        kept = int(cur.get("kept") or 0)
        if window != "hit" and need <= 4 and self._fx(roller, "bond") and self._cf_turn_free(roller, "bond") and roller.get("pos") \
                and any(o is not roller and o.get("pos") and self._fx(o, "bond") and self._dist(o, roller) <= self._subc_bond_ft(o) for o in self.b["combatants"]):
            self._cf_offer(out, roller, "free", [{"key": "bond", "label": "Emboldening Bond (+1d4)", "detail": ""}],
                           f"{roller['name']}'s roll ({cur.get('total')}). Add the bond's 1d4?")
        for o in self.b["combatants"]:
            oc = self._sheet(o)
            if not oc or o.get("form") or not o.get("pos") or not self._can_act(o) or not roller.get("pos") or not self._sees(o, roller):
                continue
            helps = window != "hit"                             # help an ally's roll, or spoil a foe's hit
            if helps == self._hostile(o, roller):
                continue
            opts, react = [], []
            if helps and kept == 1 and o is not roller and "Bountiful Luck" in (oc.d.get("feats") or []) and self._may_react(o) \
                    and self._dist(o, roller) <= 30:
                react.append({"key": "bountiful", "label": f"Bountiful Luck: {roller['name']} rerolls the 1", "detail": ""})
            if F.sub_at(oc, "Wizard", "School of Divination", 2):
                dice = self._cf_portent(o, oc)
                good = [d for d in dice if (d - kept >= need if helps else kept - d >= need)]
                if good:
                    d = max(good) if helps else min(good)
                    opts.append({"key": f"portent:{d}", "label": f"Portent: {roller['name']}'s d20 becomes {d}", "detail": ""})
            if self._may_react(o) and self._dist(o, roller) <= 60 and need <= 4 and F.sub_at(oc, "Sorcerer", "Wild Magic", 6) \
                    and self._resource_left(o, "Sorcery Points") >= 2:
                react.append({"key": "bend_luck", "label": f"Bend Luck ({'+' if helps else '-'}1d4, 2 sorcery points)", "detail": ""})
            dice = cur.get("dice") or []
            if self._may_react(o) and len(dice) >= 2 and cur.get("mode") == ("adv" if not helps else "dis") and self._dist(o, roller) <= 60 \
                    and F.sub_at(oc, "Sorcerer", "Clockwork Soul", 1) and self._cf_left(o, "Restore Balance", oc.proficiency_bonus):
                alt = max(dice) if helps else min(dice)
                if (alt - kept >= need) if helps else (kept - alt >= need):
                    react.append({"key": f"balance:{alt}", "label": f"Restore Balance (no {'disadvantage' if helps else 'advantage'}: {alt})",
                                  "detail": ""})
            if self._may_react(o) and self._dist(o, roller) <= 60 and self._fx(o, "storm_rune") and len(dice) <= 1 and need <= 10:
                react.append({"key": "storm_rune", "label": f"Storm Rune ({'advantage' if helps else 'disadvantage'}: roll again)", "detail": ""})
            if self._may_react(o) and self._dist(o, roller) <= 30 and need <= 6 and F.sub_at(oc, "Druid", "Circle of Stars", 6) \
                    and self._cf_left(o, "Cosmic Omen", oc.proficiency_bonus):
                if "omen" not in o:
                    o["omen"] = "weal" if self.rng.randint(1, 6) % 2 == 0 else "woe"
                if (o["omen"] == "weal") == helps:
                    react.append({"key": "omen", "label": f"Cosmic Omen ({o['omen']}: {'+' if helps else '-'}1d6)", "detail": ""})
            text = f"{roller['name']}'s roll ({cur.get('total')}) — {o['name']}: change it?"
            self._cf_offer(out, o, "free", opts, text)
            self._cf_offer(out, o, "reaction", react, text)

    def _cf_giant_killer(self, out: list, att: dict, tgt: dict, window: Optional[str]):
        tc = self._sheet(tgt)
        if not tc or tgt.get("form") or not CF.has(tc, "hunters_prey") or CF.is_on(tc, "hunters_prey") != "Giant Killer":
            return
        if not _bigger(self._size_of(att), "Medium") or not self._alive(tgt) or not self._may_react(tgt) or self._dist(att, tgt) > 5:
            return
        self._cf_offer(out, tgt, "reaction", [{"key": "giant_killer", "label": f"Giant Killer: attack {att['name']}", "detail": ""}],
                       f"{att['name']} attacked {tgt['name']}. Giant Killer?", window)

    @staticmethod
    def _cf_blades(char) -> str:
        lv = char.class_level("Bard")
        return "8d6" if lv >= 15 else "5d6" if lv >= 10 else "3d6" if lv >= 5 else "2d6"

    @staticmethod
    def _cf_fury(char) -> int:
        return char.proficiency_bonus if F.mpmm(char) else char.total_level

    def _cf_sweep_target(self, att: dict, tgt: dict) -> Optional[dict]:
        if not att.get("pos") or not tgt.get("pos"):
            return None
        return next((o for o in self.b["combatants"] if o is not tgt and o is not att and o.get("pos") and self._hostile(att, o)
                     and self._alive(o) and self._dist(o, tgt) <= 5 and self._dist(o, att) <= self._reach(att)), None)

    def _class_auto_pick(self, window: str, R: dict, reactor: dict, keys: List[str]) -> Optional[str]:
        """What a reactor set to "always" picks among the class features' options (None: leave it to the usual choice)."""
        cur = R.get("cur") or {}
        mine = [k for k in keys if k.split(":")[0] in CLASS_FAMILIES]
        if not mine:
            return None
        pick = self._nf_auto_pick(window, R, reactor, mine, cur)    # the later feats (newfeats.py): '' = none of them
        if pick is not None:
            return pick or None
        own = next((k for k in mine if k.split(":")[0] in ("deft_strike", "tipsy_sway", "curving_shot", "sun_shield", "deflect_energy", "protective_bond",
                                                          "vigil_oa")), None)
        if own:
            return own                                           # subfeats_c.py: Deft Strike, Redirect Attack, Sun Shield...
        luck = [k for k in mine if k.split(":")[0] in ("portent", "omen", "bend_luck", "balance", "bountiful", "bond")]
        if luck and window in ("hit", "missed", "save_failed"):
            return luck[0]                                       # offered only when it changes the outcome
        if window == "hit":
            if cur.get("crit") and "death_door" in mine:
                return "death_door"
            need = cur.get("total", 0) - cur.get("ac", 0)
            if "deflection" in mine and need < 2:
                return "deflection"
            for k in ("flare", "protection", "entropic_ward", "shadowy_dodge", "armor_of_hexes"):
                if k in mine:
                    return k
            return "illusory_self" if "illusory_self" in mine and cur.get("crit") else None
        if window == "missed":
            for k in ("guided_strike", "saving_face", "favored_gods", "giant_killer", "homing_strikes", "built_for_success"):
                if k in mine:
                    return k
            return None
        if window == "save_failed":
            short = int((R.get("sv") or {}).get("dc") or 0) - int(cur.get("total") or 0)
            if "deflection" in mine and short <= 4:
                return "deflection"
            for k in ("fanatical_focus", "diamond_soul", "lucky_footwork", "saving_face", "favored_gods", "dark_luck", "built_for_success"):
                if k in mine:
                    return k
            return None
        if window == "on_hit":
            for k in ("hand_of_harm", "open_hand:prone", "fury_small", "sweep", "psionic_strike", "astral_spark"):
                if k in mine:
                    return k
            if cur.get("crit"):
                for k in ("eldritch_smite", "psychic_blades"):
                    if k in mine:
                        return k
            return None
        return mine[0]

    def _class_react(self, window: str, R: dict, reactor: dict, fam: str, arg: str, ctx: dict):
        """What a class feature's reaction (or free on-hit choice) does."""
        cur = R.setdefault("cur", {})
        char = self._sheet(reactor)
        name = reactor["name"]
        att = self._find_or_none(ctx.get("attacker") or R.get("actor"))
        tgt = self._find_or_none(ctx.get("target"))
        if self._sub_react(window, R, reactor, fam, arg, ctx):  # subfeats.py
            return
        if fam in ("flare", "entropic_ward", "shadowy_dodge", "protection"):
            if fam == "flare":
                self._cf_use(reactor, "Warding Flare")
            elif fam == "entropic_ward":
                self._cf_use(reactor, "Entropic Ward", "short")
            again = self.rng.randint(1, 20)
            if again < cur.get("kept", 20):
                cur["total"] = cur.get("total", 0) - (cur["kept"] - again)
                cur["kept"] = again
                cur["crit"] = False
            self._line(R, f"{name} uses {CLASS_FAMILIES[fam]}: the attacker rolls again ({again}) → {cur.get('total')}", CLASS_FAMILIES[fam])
            if fam == "entropic_ward" and cur.get("total", 0) < cur.get("ac", 0) + cur.get("ac_extra", 0):
                self._effect_on(reactor, "Entropic Ward", [], None, None, None, None, name, {"attacks_with": "adv", "once": True}, None,
                                reactor["id"], until={"end": reactor["id"], "skip": 1 if self.b.get("turn") == reactor["id"] else 0})
        elif fam == "deflection":
            if window == "save_failed":
                cur["total"] = int(cur.get("total") or 0) + 4
                cur["ok"] = cur["total"] >= int(R["sv"]["dc"])
                self._line(R, f"{name} uses Arcane Deflection: +4 → {cur['total']}" + (" — success" if cur["ok"] else ""), "Arcane Deflection")
            else:
                cur["ac_extra"] = cur.get("ac_extra", 0) + 2
                self._line(R, f"{name} uses Arcane Deflection: +2 AC against this attack", "Arcane Deflection")
        elif fam == "illusory_self":
            self._cf_use(reactor, "Illusory Self", "short")
            cur.update(total=0, kept=0, crit=False, saved_by="Illusory Self")
            self._line(R, f"{name} leaves an illusory duplicate: the attack misses", "Illusory Self")
        elif fam == "death_door":
            self._cf_use(reactor, "Sentinel at Death's Door")
            cur["crit"] = False
            self._line(R, f"{name} turns the critical hit into a normal hit (Sentinel at Death's Door)", "no critical")
        elif fam == "guided_strike":
            res = "Channel Divinity (Cleric)" if F.sub_at(char, "Cleric", "War Domain", 2) and self._resource_left(reactor, "Channel Divinity (Cleric)") \
                else "Channel Divinity (Paladin)"
            if not self._use_resource(reactor, res):
                return
            cur["total"] = cur.get("total", 0) + 10
            self._line(R, f"{name} uses Guided Strike: +10 → {cur['total']}", "Guided Strike")
        elif fam == "favored_gods":
            self._cf_use(reactor, "Favored by the Gods", "short")
            n = roll("2d4")
            cur["total"] = int(cur.get("total") or 0) + n
            if window == "save_failed":
                cur["ok"] = cur["total"] >= int(R["sv"]["dc"])
            self._line(R, f"{name} is favored by the gods: +{n} → {cur['total']}", "Favored by the Gods")
        elif fam == "dark_luck":
            self._cf_use(reactor, "Dark One's Own Luck", "short")
            n = roll("1d10")
            cur["total"] = int(cur.get("total") or 0) + n
            cur["ok"] = cur["total"] >= int(R["sv"]["dc"])
            self._line(R, f"{name} calls on the Dark One's luck: +{n} → {cur['total']}" + (" — success" if cur["ok"] else ""), "Dark One's Own Luck")
        elif fam in ("fanatical_focus", "diamond_soul", "legend_save"):
            if fam == "fanatical_focus":
                rage = next((e for e, _v in self._fx(reactor, "rage")), None)
                if rage is not None:
                    rage["focus_used"] = True
            elif fam == "diamond_soul" and not self._use_resource(reactor, "Ki Points"):
                return
            again = self.rng.randint(1, 20)
            total = int(cur.get("total") or 0) - int(cur.get("kept") or 0) + again       # the new roll stands
            cur.update(total=total, kept=again, ok=total >= int(R["sv"]["dc"]))
            self._line(R, f"{name} uses {CLASS_FAMILIES[fam]}: {again} → {total}" + (" — success" if cur["ok"] else " — still failed"), CLASS_FAMILIES[fam])
        elif fam == "master_duelist":
            self._cf_use(reactor, "Master Duelist", "short")
            again = max(self.rng.randint(1, 20), self.rng.randint(1, 20))
            cur.update(total=int(cur.get("total") or 0) - int(cur.get("kept") or 0) + again, kept=again, crit=again == 20)
            self._line(R, f"{name}'s Master Duelist: rerolled with advantage {again} → {cur['total']}", "Master Duelist")
        elif fam == "tail":
            n = roll("1d8")
            cur["ac_extra"] = cur.get("ac_extra", 0) + n
            self._line(R, f"{name}'s tail swats the blow: +{n} AC (Form of the Beast)", "Beast Tail")
        elif fam == "warding_maneuver":
            self._cf_use(reactor, "Warding Maneuver")
            n = roll("1d8")
            cur["ac_extra"] = cur.get("ac_extra", 0) + n
            self._line(R, f"{name}'s Warding Maneuver: +{n} AC", "Warding Maneuver")
        elif fam == "backlash":
            surge = self._class_after_rage(reactor, char)       # (the reaction is spent by _apply_reaction)
            if surge:
                self._line(R, f"{name}'s Unstable Backlash: {surge}", "Unstable Backlash")
        elif fam == "wolf_prone" and tgt:
            t = reactor.get("turn")
            if t is not None:
                t["bonus"] = max(0, t.get("bonus", 1) - 1)
            if self._size_of(tgt) not in ("Huge", "Gargantuan"):
                self._cond(tgt, "Prone", True)
                self._line(R, f"{name} knocks {tgt['name']} prone (Wolf totem)", "prone")
        elif fam == "infectious_fury" and tgt:
            self._cf_use(reactor, "Infectious Fury")
            R.setdefault("follow", []).append(self._strike(reactor, "Infectious Fury", [tgt["id"]], mode="save", magical=True,
                                                           sv={"ab": "wis", "dc": self._cf_dc(char, "con"), "half": False}, parts=[["2d12", "psychic"]]))
        elif fam == "vigilant" and tgt:
            self._cf_use(reactor, "Vigilant Guardian")
            if reactor.get("pos") and tgt.get("pos"):
                a_, b_ = list(reactor["pos"]), list(tgt["pos"])
                reactor["pos"], tgt["pos"] = b_, a_
                self._vfx("blink", id=reactor["id"], at=a_, to=b_)
                self._vfx("blink", id=tgt["id"], at=b_, to=a_)
            if tgt["id"] in R.get("targets") or []:
                R["targets"][R["ti"]] = reactor["id"]            # the guardian is hit instead
            cur["ac_extra"] = cur.get("ac_extra", 0) - 999
            self._line(R, f"{name} swaps places with {tgt['name']} and takes the hit (Vigilant Guardian)", "Vigilant Guardian")
        elif fam == "tomb":
            self._cf_use(reactor, "Tomb of Levistus", "short")
            n = 10 * char.class_level("Warlock")
            self._give_temp(reactor, n)
            self._effect_on(reactor, "Tomb of Levistus", ["Incapacitated"], None, None, None, None, name,
                            {"vuln": ["fire"], "speed_set": 0}, None, reactor["id"], until={"end": reactor["id"], "skip": 0})
            self._line(R, f"{name} is encased in ice: {n} temporary HP (incapacitated, vulnerable to fire until its turn ends)", "Tomb of Levistus")
        elif fam == "talisman_rebuke" and att:
            self._line(R, "Rebuke of the Talisman: " + self._deal(att, [[char.proficiency_bonus, "psychic"]], by=reactor, label="Rebuke of the Talisman"), "")
            self._push(att, reactor, 10, R)
        elif fam == "talisman_protect":
            self._cf_use(reactor, "Protection of the Talisman")
            n = roll("1d4")
            cur["total"] = int(cur.get("total") or 0) + n
            cur["ok"] = cur["total"] >= int(R["sv"]["dc"])
            self._line(R, f"{name}'s talisman: +{n} → {cur['total']}" + (" — success" if cur["ok"] else ""), "Protection of the Talisman")
        elif fam == "fire_rune" and tgt:
            self._cf_use(reactor, "Fire Rune", "short")
            cur.setdefault("bonus_parts", []).append(["2d6", "fire"])
            dc = 8 + char.proficiency_bonus + char.mod("con")
            self._apply_save(R, reactor, tgt, {"ab": "str", "dc": dc, "conds": ["Restrained"], "rounds": 10,     # the shackles burn each turn;
                                               "mods": {"dot": {"dice": "2d6", "type": "fire", "when": "start", "save": "str"}}})   # a save frees it
        elif fam == "focused_aim":
            k = int(arg or 1)
            if not self._use_resource(reactor, "Ki Points", k):
                return
            cur["total"] = int(cur.get("total") or 0) + 2 * k
            self._line(R, f"{name} focuses its aim ({k} ki): +{2 * k} → {cur['total']}", "Focused Aim")
        elif fam == "seeking_spell":
            if not self._use_resource(reactor, "Sorcery Points", 2):
                return
            again = self.rng.randint(1, 20)
            cur.update(total=int(cur.get("total") or 0) - int(cur.get("kept") or 0) + again, kept=again, crit=again == 20)
            self._line(R, f"{name}'s Seeking Spell: rerolled {again} → {cur['total']}", "Seeking Spell")
        elif fam == "stroke_of_luck":
            self._cf_use(reactor, "Stroke of Luck", "short")
            cur["total"] = max(int(cur.get("total") or 0), int(cur.get("ac") or 0) + int(cur.get("ac_extra") or 0))
            if cur.get("kept") == 1:
                cur["kept"] = 2
            self._line(R, f"{name}'s Stroke of Luck: the miss becomes a hit", "Stroke of Luck")
        elif fam == "legend":
            self._once_per_turn(reactor, "legend")
            cur["total"] = max(int(cur.get("total") or 0), int(cur.get("ac") or 0) + int(cur.get("ac_extra") or 0))
            if cur.get("kept") == 1:
                cur["kept"] = 2                                 # a natural 1 still misses unless it is changed
            self._line(R, f"{name} is a living legend: the miss becomes a hit", "Living Legend")
        elif fam == "stalkers_flurry" and tgt:
            self._once_per_turn(reactor, "stalkers_flurry")
            try:
                w, atk = self._cf_weapon(reactor, char, tgt)
            except ServiceError:
                return
            atk["n"] = 1
            self._stack().append(self._strike(reactor, f"{w['name']} (Stalker's Flurry)", [tgt["id"]], mode="attack", atk=atk,
                                              magical=atk.get("magical", False)))
        elif fam in ("giant_killer", "vengeful"):
            if fam == "vengeful":
                self._cf_use(reactor, "Vengeful Assault", "short")
            if att:
                child = self._opportunity_strike(reactor, att)
                if child:
                    child["label"] = CLASS_FAMILIES[fam]
                    self._stack().append(child)
        elif fam == "storm_wrath":
            self._cf_use(reactor, "Wrath of the Storm")
            if att:
                self._stack().append(self._strike(reactor, "Wrath of the Storm", [att["id"]], mode="save",
                                                  sv={"ab": "dex", "dc": self._cf_dc(char, "wis"), "half": True}, parts=[["2d8", "lightning"]]))
        elif fam in ("stones_endurance", "song_defense", "interception", "spirit_shield"):
            if fam == "stones_endurance":
                self._cf_use(reactor, "Stone's Endurance", "long" if F.mpmm(char) else "short")
                cut = roll("1d12") + char.mod("con")
            elif fam == "song_defense":
                lvl = int(arg or 1)
                used = char.d["slots_used"]
                used[str(lvl)] = int(used.get(str(lvl)) or 0) + 1
                char.save()
                cut = 5 * lvl
            elif fam == "interception":
                cut = roll("1d10") + char.proficiency_bonus
            else:
                lv = char.class_level("Barbarian")
                cut = roll("4d6" if lv >= 14 else "3d6" if lv >= 10 else "2d6")
                if lv >= 14 and att is not None and att is not reactor:      # Vengeful Ancestors: the blocked damage hits back
                    self._line(R, "Vengeful Ancestors: " + self._deal(att, [[cut, "force"]], by=reactor, label="Vengeful Ancestors"), "")
            left, after = max(0, cut), []
            for n, t in cur.get("dmg") or []:
                take = min(n, left)
                left -= take
                after.append([n - take, t])
            cur["dmg"] = after
            self._line(R, f"{name} uses {CLASS_FAMILIES[fam]}: -{cut} damage", CLASS_FAMILIES[fam])
        elif fam == "eldritch_smite":
            used = char.d["slots_used"]
            if not SC.slots_remaining(char).get(SC.PACT_KEY):
                return
            used[SC.PACT_KEY] = int(used.get(SC.PACT_KEY) or 0) + 1
            char.save()
            self._once_per_turn(reactor, "eldritch_smite")
            lvl = (SC.spell_slots(char).get("pact") or {}).get("level", 1)
            cur.setdefault("bonus_parts", []).append([f"{1 + lvl}d8", "force"])
            self._line(R, f"{name} uses Eldritch Smite (+{1 + lvl}d8 force)", "Eldritch Smite")
            if tgt and self._size_of(tgt) != "Gargantuan" and "Prone" not in self._conds(tgt):
                self._cond(tgt, "Prone", True)
                self._line(R, f"{tgt['name']} is knocked prone", "prone")
        elif fam == "psychic_blades":
            if not self._use_resource(reactor, "Bardic Inspiration"):
                return
            self._once_per_turn(reactor, "psychic_blades")
            cur.setdefault("bonus_parts", []).append([self._cf_blades(char), "psychic"])
            self._line(R, f"{name} uses Psychic Blades (+{self._cf_blades(char)} psychic)", "Psychic Blades")
        elif fam == "hand_of_harm":
            if not self._use_resource(reactor, "Ki Points"):
                return
            self._once_per_turn(reactor, "hand_of_harm")
            wis = char.mod("wis")
            die = F.martial_die(char) or "1d4"
            cur.setdefault("bonus_parts", []).append([f"{die}{wis:+d}" if wis else die, "necrotic"])
            self._line(R, f"{name} uses Hand of Harm", "Hand of Harm")
        elif fam == "open_hand" and tgt:
            dc = F.ki_dc(char)
            if arg == "prone":
                self._apply_save(R, reactor, tgt, {"ab": "dex", "dc": dc, "conds": ["Prone"]})
            elif arg == "push":
                res = self._saving_throw(tgt, "str", dc, label="Open Hand Technique")
                if not res["ok"]:
                    self._push(tgt, reactor, 15, R)
                self._line(R, f"{tgt['name']} STR save {res['total']} vs DC {dc} — " + ("holds its ground" if res["ok"] else "pushed 15 ft"), "")
            else:
                self._effect_on(tgt, "Open Hand Technique", [], None, None, None, None, name, {"no_reactions": True}, None, reactor["id"],
                                until={"end": reactor["id"], "skip": 1 if self.b.get("turn") == reactor["id"] else 0})
                self._line(R, f"{tgt['name']} can't take reactions until the end of {name}'s next turn", "no reactions")
        elif fam == "fury_small":
            self._cf_use(reactor, "Fury of the Small", "long" if F.mpmm(char) else "short")
            n = self._cf_fury(char)
            cur.setdefault("bonus_parts", []).append([n, ((R.get("atk") or {}).get("parts") or [["", ""]])[0][1]])
            self._line(R, f"{name} unleashes the Fury of the Small (+{n})", "Fury of the Small")
        elif fam in ("valor", "valor_ac"):
            eff = next((e for e, _v in self._fx(reactor, "valor")), None)
            if eff is None:
                return
            n = roll(eff["mods"]["valor"])
            if eff in (reactor.get("effects") or []):
                self._effect_off(reactor, eff, "used")
            if fam == "valor_ac":
                cur["ac_extra"] = cur.get("ac_extra", 0) + n
                self._line(R, f"{name} uses Combat Inspiration: +{n} AC", "Combat Inspiration")
            elif arg == "dmg":
                cur.setdefault("bonus_parts", []).append([n, ((R.get("atk") or {}).get("parts") or [["", ""]])[0][1]])
                self._line(R, f"{name} uses Combat Inspiration: +{n} damage", "Combat Inspiration")
            else:
                cur["total"] = cur.get("total", 0) + n
                self._line(R, f"{name} uses Combat Inspiration: +{n} → {cur['total']}", "Combat Inspiration")
        elif fam == "war_god":
            if not self._use_resource(reactor, "Channel Divinity (Cleric)"):
                return
            cur["total"] = cur.get("total", 0) + 10
            self._line(R, f"{name} grants War God's Blessing: +10 → {cur['total']}", "War God's Blessing")
        elif fam == "runic_shield":
            self._cf_use(reactor, "Runic Shield")
            again = self.rng.randint(1, 20)
            cur["total"] = cur.get("total", 0) - cur.get("kept", 0) + again
            cur["kept"] = again
            cur["crit"] = again == 20
            self._line(R, f"{name}'s Runic Shield: the attacker rerolls {again} → {cur['total']}", "Runic Shield")
        elif fam == "glorious_defense":
            self._cf_use(reactor, "Glorious Defense")
            n = max(1, char.mod("cha"))
            cur["ac_extra"] = cur.get("ac_extra", 0) + n
            self._line(R, f"{name}'s Glorious Defense: +{n} AC", "Glorious Defense")
        elif fam == "arcane_jolt":
            self._cf_use(reactor, "Arcane Jolt")
            self._once_per_turn(reactor, "arcane_jolt")
            cur.setdefault("bonus_parts", []).append(["4d6" if char.class_level("Artificer") >= 15 else "2d6", "force"])
            self._line(R, f"{name} channels an Arcane Jolt", "Arcane Jolt")
        elif fam == "flash":
            n = max(1, char.mod("int"))
            self._cf_use(reactor, "Flash of Genius")
            cur["total"] = int(cur.get("total") or 0) + n
            cur["ok"] = cur["total"] >= int(R["sv"]["dc"])
            self._line(R, f"{name}'s Flash of Genius: +{n} → {cur['total']}" + (" — success" if cur["ok"] else ""), "Flash of Genius")
        elif fam == "armor_of_hexes":
            r = roll("1d6")
            if r >= 4:
                cur.update(total=0, kept=0, crit=False, saved_by="Armor of Hexes")
            self._line(R, f"{name}'s Armor of Hexes: {r}" + (" — the attack misses" if r >= 4 else " — it still hits"), "Armor of Hexes")
        elif fam == "misty_escape":
            self._cf_use(reactor, "Misty Escape", "short")
            self._effect_on(reactor, "Misty Escape", ["Invisible"], None, None, None, None, name, {"ends_on": ["attack", "cast"]}, None,
                            reactor["id"], until={"start": reactor["id"]})
            self._line(R, f"{name} vanishes in a puff of mist (invisible)", "Misty Escape")
        elif fam == "lucky_footwork":
            n = roll("1d4")
            cur["total"] = int(cur.get("total") or 0) + n
            cur["ok"] = cur["total"] >= int(R["sv"]["dc"])
            self._line(R, f"{name}'s Lucky Footwork: +{n} → {cur['total']}" + (" — success" if cur["ok"] else ""), "Lucky Footwork")
        elif fam == "saving_face":
            n = self._cf_face(reactor)
            if char.has_feature("Fortune from the Many"):
                self._cf_use(reactor, "Fortune from the Many")
            else:
                self._cf_use(reactor, "Saving Face", "short")
            cur["total"] = int(cur.get("total") or 0) + n
            if window == "save_failed":
                cur["ok"] = cur["total"] >= int(R["sv"]["dc"])
            self._line(R, f"{name} won't lose face: +{n} → {cur['total']}", "Saving Face")
        elif fam in ("portent", "bend_luck", "omen", "bond", "bountiful", "balance", "storm_rune"):
            kept, total = int(cur.get("kept") or 0), int(cur.get("total") or 0)
            if fam == "storm_rune":
                d = self.rng.randint(1, 20)
                keep = min(kept, d) if window == "hit" else max(kept, d)
                cur.update(total=total - kept + keep, kept=keep, crit=keep == 20 and window != "save_failed")
                self._line(R, f"{name}'s Storm Rune: rolled again ({d}) → {cur['total']}", "Storm Rune")
            elif fam == "balance":
                self._cf_use(reactor, "Restore Balance")
                d = int(arg)
                cur.update(total=total - kept + d, kept=d, mode=None, crit=d == 20 and window != "save_failed")
                self._line(R, f"{name} restores balance: the roll is {d} → {cur['total']}", "Restore Balance")
            elif fam == "bountiful":
                d = self.rng.randint(1, 20)
                cur.update(total=total - kept + d, kept=d, crit=d == 20 and window == "missed")
                self._line(R, f"{name}'s Bountiful Luck: rerolled {d} → {cur['total']}", "Bountiful Luck")
            elif fam == "bond":
                self._once_per_turn(reactor, "bond")
                n = roll("1d4")
                cur["total"] = total + n
                self._line(R, f"{name}'s Emboldening Bond: +{n} → {cur['total']}", "Emboldening Bond")
            elif fam == "portent":
                d = int(arg)
                if d in (reactor.get("portent") or []):
                    reactor["portent"].remove(d)
                cur.update(total=total - kept + d, kept=d, crit=d == 20 and window != "save_failed")
                self._line(R, f"{name}'s Portent: the d20 becomes {d} → {cur['total']}", "Portent")
            else:
                if fam == "bend_luck":
                    if not self._use_resource(reactor, "Sorcery Points", 2):
                        return
                    n = roll("1d4")
                else:
                    self._cf_use(reactor, "Cosmic Omen")
                    n = roll("1d6")
                n = -n if window == "hit" else n
                cur["total"] = total + n
                self._line(R, f"{name} uses {CLASS_FAMILIES[fam]}: {n:+d} → {cur['total']}", CLASS_FAMILIES[fam])
            if window == "save_failed":
                cur["ok"] = cur["total"] >= int(R["sv"]["dc"])
        elif fam == "brace":
            mover = self._find_or_none(ctx.get("mover"))
            if not mover or not self._use_resource(reactor, "Superiority Dice"):
                return
            child = self._opportunity_strike(reactor, mover)
            if child:
                child["label"] = "Brace"
                child["atk"]["parts"] = list(child["atk"].get("parts") or []) + [["1" + F.superiority_die(char),
                                                                                    (child["atk"].get("parts") or [["", ""]])[0][1]]]
                self._stack().append(child)
        elif fam == "quivering" and tgt:
            if not self._use_resource(reactor, "Ki Points", 3):
                return
            for o in self.b["combatants"]:                      # one creature vibrates at a time
                for e in [e for e in o.get("effects") or [] if (e.get("mods") or {}).get("quivering") == reactor["id"]]:
                    self._effect_off(o, e, "new vibrations")
            self._effect_on(tgt, "Quivering Palm", [], None, None, None, None, name, {"quivering": reactor["id"]}, None, reactor["id"])
            self._line(R, f"{name} sets {tgt['name']} vibrating (Quivering Palm)", "Quivering Palm")
        elif fam == "rebuke_violent":
            dealt = int(arg) if str(arg or "").isdigit() else 0
            if att and dealt > 0 and self._use_resource(reactor, "Channel Divinity (Paladin)"):
                self._stack().append(self._strike(reactor, "Rebuke the Violent", [att["id"]], mode="save",
                                                  sv={"ab": "wis", "dc": self._cf_dc(char, "cha"), "half": True}, parts=[[dealt, "radiant"]]))
        elif fam == "guardian":
            tgt_ = self._find_or_none(ctx.get("target"))
            moved = [list(p) for p in cur.get("dmg") or []]
            cur["dmg"] = []
            self._line(R, f"{name} takes the blow for {tgt_['name'] if tgt_ else 'an ally'}: "
                       + self._deal_rolled(reactor, moved, by=att, label="Aura of the Guardian"), "Aura of the Guardian")
        elif fam == "dampen":
            elems = {"acid", "cold", "fire", "lightning", "thunder"}
            t0 = sorted({t for _n, t in cur.get("dmg") or []} & elems)[:1]
            cur["dmg"] = [[n // 2 if t in t0 else n, t] for n, t in cur.get("dmg") or []]
            self._line(R, f"{name} dampens the elements: half the {''.join(t0)} damage", "Dampen Elements")
        elif fam in ("protective_field", "projected_ward", "bm_parry"):
            if fam == "protective_field":
                self._cf_use(reactor, "Psionic Energy")
                cut = roll(self._cf_psi_die(char)) + char.mod("int")
            elif fam == "bm_parry":
                if not self._use_resource(reactor, "Superiority Dice"):
                    return
                cut = roll("1" + F.superiority_die(char)) + char.mod("dex")
            else:
                ward = reactor.get("ward") or {}
                total = sum(n for n, _t in cur.get("dmg") or [])
                cut = min(total, int(ward.get("hp") or 0))
                ward["hp"] = int(ward.get("hp") or 0) - cut
            left, after = max(0, cut), []
            for n, t in cur.get("dmg") or []:
                take = min(n, left)
                left -= take
                after.append([n - take, t])
            cur["dmg"] = after
            self._line(R, f"{name} uses {CLASS_FAMILIES[fam]}: -{cut} damage", CLASS_FAMILIES[fam])
        elif fam == "psionic_strike":
            self._cf_use(reactor, "Psionic Energy")
            self._once_per_turn(reactor, "psionic_strike")
            mod = char.mod("int")
            die = self._cf_psi_die(char)
            cur.setdefault("bonus_parts", []).append([f"{die}{mod:+d}" if mod else die, "force"])
            self._line(R, f"{name} uses Psionic Strike", "Psionic Strike")
            if tgt and char.class_level("Fighter") >= 7 and self._size_of(tgt) not in ("Huge", "Gargantuan") and self._alive(tgt):
                self._apply_save(R, reactor, tgt, {"ab": "str", "dc": self._cf_dc(char, "int"), "conds": ["Prone"]})   # Telekinetic Thrust
        elif fam == "arcane_shot" and tgt:
            self._cf_use(reactor, "Arcane Shot", "short")
            self._once_per_turn(reactor, "arcane_shot")
            dc = self._cf_dc(char, "int")
            dice = "4d6" if char.class_level("Fighter") >= 18 else "2d6"
            self._line(R, f"{name} looses an Arcane Shot: {arg}", arg)
            if arg == "Banishing Arrow":
                if char.class_level("Fighter") >= 18:
                    cur.setdefault("bonus_parts", []).append(["2d6", "force"])
                self._apply_save(R, reactor, tgt, {"ab": "cha", "dc": dc, "conds": ["Incapacitated"], "mods": {"banished": True, "untargetable": True},
                                                   "until": {"end": tgt["id"], "skip": 1 if self.b.get("turn") == tgt["id"] else 0},
                                                   "note": "banished to the Feywild"})
            elif arg == "Bursting Arrow":
                near = [o["id"] for o in self.b["combatants"] if o is not reactor and o.get("pos") and tgt.get("pos") and self._alive(o)
                        and self._dist(o, tgt) <= 10]
                R.setdefault("follow", []).append(self._strike(reactor, "Bursting Arrow", near, mode="auto", parts=[[dice, "force"]]))
            else:
                kind = {"Beguiling Arrow": "psychic", "Enfeebling Arrow": "necrotic", "Grasping Arrow": "poison", "Shadow Arrow": "psychic"}.get(arg, "force")
                cur.setdefault("bonus_parts", []).append([dice, kind])
                if arg == "Beguiling Arrow":
                    self._apply_save(R, reactor, tgt, {"ab": "wis", "dc": dc, "conds": ["Charmed"], "until": {"start": reactor["id"]}})
                elif arg == "Enfeebling Arrow":
                    self._apply_save(R, reactor, tgt, {"ab": "con", "dc": dc, "mods": {"enfeebled": True},
                                                       "until": {"start": reactor["id"]}, "note": "its weapon damage is halved"})
                elif arg == "Grasping Arrow":
                    self._effect_on(tgt, "Grasping Arrow", [], None, None, None, 10, name, {"speed": -10}, None, reactor["id"])
                elif arg == "Shadow Arrow":
                    self._apply_save(R, reactor, tgt, {"ab": "wis", "dc": dc, "conds": ["Blinded"], "until": {"start": reactor["id"]},
                                                       "note": "can't see beyond 5 ft"})
        elif fam == "flourish" and tgt:
            fdie = F.bardic_die(char)
            if not self._use_resource(reactor, "Bardic Inspiration"):
                if not F.sub_at(char, "Bard", "College of Swords", 14):
                    return
                fdie = "1d6"                                    # Master's Flourish: a d6 instead of expending a die
            self._once_per_turn(reactor, "flourish")
            n = roll(fdie)
            dtype = ((R.get("atk") or {}).get("parts") or [["", "slashing"]])[0][1]
            cur.setdefault("bonus_parts", []).append([n, dtype])
            if arg == "defensive":
                self._effect_on(reactor, "Defensive Flourish", [], None, None, None, None, name, {"ac": n}, None, reactor["id"],
                                until={"start": reactor["id"]})
                self._line(R, f"{name} flourishes defensively: +{n} damage, +{n} AC", "Defensive Flourish")
            elif arg == "slashing":
                other = self._cf_sweep_target(reactor, tgt)
                self._line(R, f"{name}'s Slashing Flourish: +{n}" + (f"; {self._deal(other, [[n, dtype]], by=reactor, label='Slashing Flourish')}"
                                                                     if other else ""), "Slashing Flourish")
            else:
                self._push(tgt, reactor, 5 + n - n % 5, R)
                self._line(R, f"{name}'s Mobile Flourish: +{n}, pushed {5 + n - n % 5} ft", "Mobile Flourish")
        elif fam == "sweep" and tgt:
            other = self._cf_sweep_target(reactor, tgt)
            if not other or not self._use_resource(reactor, "Superiority Dice"):
                return
            die = "1" + F.superiority_die(char)
            dtype = ((R.get("atk") or {}).get("parts") or [["", "slashing"]])[0][1]
            if cur.get("total", 0) >= self._ac_of(other):
                self._line(R, f"{name} sweeps into {other['name']}: " + self._deal(other, [[die, dtype]], by=reactor, label="Sweeping Attack",
                                                                                   magical=R.get("magical", False)), "Sweeping Attack")
            else:
                self._line(R, f"{name}'s sweep misses {other['name']} ({cur.get('total')} vs AC {self._ac_of(other)})", "Sweeping Attack")
