"""Dynamic modifiers: resistances, buffs and nerfs from every source, merged one way.

A creature's numbers come from its stat block or character sheet, then from what changes them now: effects (spells,
features, items in use), conditions and passive traits. Effects keep their `mods` dict (keys below); the battle asks
this module for the merged answer.

Effect mod keys
    attack / save / check     dice or number added to those rolls (a leading '-' subtracts: Bane)
    weapon_attack             added to weapon attack rolls only (Magic Weapon, Elemental Weapon)
    save_spells               dice added to saves against spells only
    ac / ac_min / ac_base     added AC, an AC floor, a base AC (Mage Armor: 13 + Dex)
    attacks_against / attacks_with   'adv' or 'dis'
    melee_against / ranged_against   'adv' or 'dis' for melee / ranged attacks made against it
    extra_damage (dice, type) the effect's caster adds to its hits on this creature (Hex, Hunter's Mark)
    dmg (dice, type)          added to this creature's weapon hits; 'once' removes the effect after one hit (smites)
    resist / immune / vuln    damage types; 'nonmagical' = bludgeoning, piercing, slashing from nonmagical attacks
    immune_cond               conditions it can't get
    save_adv / save_dis       abilities, 'all' or 'spells'
    save_ab {ability: n}      a flat number added to saves of that ability (a froghemoth's -2 on Dexterity saves)
    adv_by_source             the effect's caster attacks it with advantage (a vampiric jade statue's curse, a bebilith's Relentless Hunter)
    adv_vs_hurt               advantage on its attacks against a creature that doesn't have all its hit points (Abyssal Visage)
    once_turn                 with extra_damage: only the caster's first hit each turn (Kivan's Mark, Bhaal's Prey)
    check_adv / check_dis     True, or a list of abilities
    regen                     dice healed at the start of its turn
    speed (+feet) speed_set (feet) speed_mult (factor) fly (feet)
    crit                      lowest natural roll that crits (19 for Improved Critical)
    no_reactions / no_heal    can't take reactions / can't regain hit points
    shell_locked              no action, bonus action or reaction but ending it (a tortle's Shell Defense)
    extra_action              actions added to its turn (Haste)
    senses {'darkvision'|'blindsight'|'truesight': feet, 'see_invisible': True}
    ends_on ['attack', 'cast', 'damage']   the effect ends when the creature does that (Invisibility, Sanctuary)
    retaliate (dice, type)    damage a creature takes when it hits this one with a melee attack (Fire Shield)
    death_ward                drops to 1 hit point instead of 0, once
    evasion                   Dex saves for half damage take none, failed ones half
    duel                      disadvantage on attacks against anyone but the effect's caster (Compelled Duel)
    warded_from [types]       creatures of those types attack it at disadvantage (Protection from Evil and Good)
    enfeebled                 half damage with Strength weapon attacks (Ray of Enfeeblement)
    elemental_bane (dice, type)  no resistance to the type, the dice added the first time each turn it takes it
    spells (spells.py, spell_effects.py)  one_action (an action or a bonus action, one attack: Slow), confused (Confusion's d10),
                              crowned, size_step (+1/-1), dmg_minus (dice off its weapon hits), no_spells, temp_ends (its temporary
                              hit points go with it), max_heal (Beacon of Hope), bond / tether (damage shared), trail (dice, type: Ashardalon's
                              Stride), holy_blind, life_1 (Aura of Life), shun (type: disadvantage against the caster), weapon_only
                              (extra_damage on weapon hits only), free_move (no difficult terrain), two_attacks, half_cover,
                              save_on_damage (a save with advantage when hurt), unseen_only (repeat save only out of the caster's sight)
    AU / FRHoF / EFA spells conc_dis (disadvantage on concentration saves), no_dash, no_exhaust, temp_gone (the effect ends with its temporary
                              hit points), ends_actions (spell name: its spell actions go with it), lantern {frags, max, ft} (Spirit Lantern),
                              synosto (Simbul's Synostodweomer), transfixed, cover34 (three-quarters cover), deflect_spell (Holy Star of Mystra),
                              aura_active (an aura that does nothing for the incapacitated), retaliate_once, exh_given (exhaustion the spell gave)
    Legends Reforged (LGR)    hit_ward (attack hits that deal it no damage: Quen), death_burst {radius, save, dc, parts} (it bursts at 0 HP:
                              Walking Bomb), worsen [stages] (Song of Sinking), no_bonus, fate_dice [d20s] (Norns' Weave), random_bolts
                              (Storm Call), solid (no incorporeal movement) and unresist [types] (resistances it loses: Yrden)
    magic items (wondrous.py) ranged_ac (+AC against ranged attacks), spell_against / oa_against ('dis' for spell attacks /
                              opportunity attacks against it), no_crit, skill_adv [skills], save_adv_vs {'labels', 'type'},
                              immune_spell [spell names], auto_stable, life_ward
"""
import re
from functools import lru_cache
from typing import Dict, Iterable, List, Optional, Set, Tuple

TYPES = ["acid", "bludgeoning", "cold", "fire", "force", "lightning", "necrotic", "piercing", "poison", "psychic", "radiant",
         "slashing", "thunder"]
BPS = {"bludgeoning", "piercing", "slashing"}
ABILITY_NAMES = {"strength": "str", "dexterity": "dex", "constitution": "con", "intelligence": "int", "wisdom": "wis",
                 "charisma": "cha"}


def parse_damage_list(text: str) -> Tuple[Set[str], Set[str]]:
    """'cold; bludgeoning; piercing; slashing from nonmagical attacks that aren't silvered' ->
    ({'cold'}, {'bludgeoning', 'piercing', 'slashing'}): plain types, and B/P/S only from nonmagical attacks."""
    plain, nonmagical = set(), set()
    low = (text or "").lower()
    if not low.strip():
        return plain, nonmagical
    m = re.search(r"((?:(?:bludgeoning|piercing|slashing)[;,]?\s*(?:and\s+)?)+)(?:damage\s+)?from nonmagical", low)
    if m:
        nonmagical = {t for t in BPS if t in m.group(1)}
        low = low[:m.start()] + low[m.end():]
    m = re.search(r"nonmagical\s+((?:(?:bludgeoning|piercing|slashing)[;,]?\s*(?:and\s+)?)+)", low)
    if m:
        nonmagical |= {t for t in BPS if t in m.group(1)}
        low = low[:m.start()] + low[m.end():]
    for t in TYPES:
        if re.search(r"\b%s\b" % t, low):
            plain.add(t)
    if "damage from spells" in low:
        plain.add("spells")
    return plain, nonmagical


SPELL_OF = re.compile(r"\s*\([^)]*\)$")
PER_SOURCE = {"extra_damage"}                           # Hex, Hunter's Mark: each caster's mark counts for that caster


def effect_list(effects: Optional[list], key: str) -> List[tuple]:
    """[(effect, value)] for every effect that has `key` in its mods. The same spell from two casters doesn't combine
    (PHB "Combining Magical Effects"): two Blesses give one +1d4, two Hastes double the speed once."""
    out, seen = [], set()
    for e in effects or []:
        if key not in (e.get("mods") or {}):
            continue
        if not e.get("feature") and not e.get("trait") and key not in PER_SOURCE:
            nm = SPELL_OF.sub("", e.get("name") or "")         # "Haste (Potion of Speed)" is Haste too
            if nm in seen:
                continue
            seen.add(nm)
        out.append((e, e["mods"][key]))
    return out


def defenses(*, monster: Optional[dict] = None, race_resist: Iterable[str] = (), item_resist: Iterable[str] = (),
             effects: Optional[list] = None, conditions: Iterable[str] = (), extra: Optional[dict] = None) -> Dict[str, set]:
    """{'resist', 'immune', 'vuln', 'nonmagical_resist', 'nonmagical_immune', 'immune_cond'} merged from every source."""
    d = {k: set() for k in ("resist", "immune", "vuln", "nonmagical_resist", "nonmagical_immune", "immune_cond")}
    if monster:
        p, n = parse_damage_list(monster.get("resist", ""))
        d["resist"] |= p
        d["nonmagical_resist"] |= n
        p, n = parse_damage_list(monster.get("immune", ""))
        d["immune"] |= p
        d["nonmagical_immune"] |= n
        d["vuln"] |= parse_damage_list(monster.get("vulnerable", ""))[0]
        d["immune_cond"] |= {c.strip().capitalize() for c in re.split(r"[;,]", monster.get("condition_immune", "") or "") if c.strip()}
    d["resist"] |= {t.lower() for t in race_resist if isinstance(t, str)}
    d["resist"] |= {t.lower() for t in item_resist if isinstance(t, str)}
    for key, into in (("resist", "resist"), ("immune", "immune"), ("vuln", "vuln"), ("immune_cond", "immune_cond")):
        for _e, v in effect_list(effects, key):
            for t in v if isinstance(v, (list, tuple, set)) else [v]:
                if t == "nonmagical":
                    d["nonmagical_" + ("immune" if key == "immune" else "resist")] |= BPS
                else:
                    d[into].add(t if key == "immune_cond" else str(t).lower())
    for _e, v in effect_list(effects, "unresist"):            # Yrden: an incorporeal creature pulled into solid form loses these
        d["resist"] -= set(v)
        d["nonmagical_resist"] -= set(v)
    if "Petrified" in set(conditions or ()):
        d["resist"] |= set(TYPES)
        d["immune"].add("poison")
    for k, v in (extra or {}).items():
        d.setdefault(k, set()).update(v)
    return d


def multiplier(dtype: str, d: Dict[str, set], *, magical: bool = True, silvered: bool = False, spell: bool = False) -> Tuple[float, str]:
    """(factor, note) for one damage part of this type against these defenses. Immunity wins; resistance and
    vulnerability of the same part cancel each other (PHB)."""
    t = (dtype or "").lower()
    if not t or t == "healing":
        return 1.0, ""
    immune = t in d["immune"] or (not magical and not silvered and t in d.get("nonmagical_immune", set()))
    if immune:
        return 0.0, "immune"
    resist = t in d["resist"] or (not magical and not silvered and t in d.get("nonmagical_resist", set())) or (spell and "spells" in d["resist"])
    vuln = t in d["vuln"]
    if resist and vuln:
        return 1.0, "resistant and vulnerable"
    if resist:
        return 0.5, "resistant"
    if vuln:
        return 2.0, "vulnerable"
    return 1.0, ""


def mode_from(effects, key: str) -> Set[str]:
    return {v for _e, v in effect_list(effects, key) if v in ("adv", "dis")}


def abilities_hit(value, ability: str, against_spell: bool = False) -> bool:
    """Does a save_adv / save_dis / check_adv value cover this ability (or a spell)?"""
    if value is True:
        return True
    vals = value if isinstance(value, (list, tuple, set)) else [value]
    return ability in vals or "all" in vals or (against_spell and "spells" in vals)


def speed_of(base: int, effects, conds_factor: float = 1.0) -> int:
    for _e, v in effect_list(effects, "speed_set"):
        base = int(v)
    base += sum(int(v) for _e, v in effect_list(effects, "speed"))
    for _e, v in effect_list(effects, "speed_mult"):
        base = int(base * float(v))
    return max(0, int(base * conds_factor))


def crit_range(effects, base: int = 20) -> int:
    lows = [int(v) for _e, v in effect_list(effects, "crit")]
    return min([base] + lows)


def monster_senses(text: str) -> Dict[str, int]:
    """'blindsight 60 ft. (blind beyond this radius), darkvision 120 ft.' -> {'blindsight': 60, 'darkvision': 120}."""
    out = {}
    for name in ("darkvision", "blindsight", "truesight", "tremorsense"):
        m = re.search(name + r"\s+(\d+)\s*ft", text or "", re.I)
        if m:
            out[name] = int(m.group(1))
    return out


def monster_speeds(text: str) -> Dict[str, int]:
    """'30 ft., fly 60 ft. (hover), swim 30 ft.' -> {'walk': 30, 'fly': 60, 'swim': 30, 'hover': 1}."""
    out = {}
    t = text or ""
    m = re.match(r"\s*(\d+)\s*ft", t)
    if m:
        out["walk"] = int(m.group(1))
    for kind in ("fly", "swim", "climb", "burrow"):
        m = re.search(kind + r"\s+(\d+)\s*ft", t, re.I)
        if m:
            out[kind] = int(m.group(1))
    if "hover" in t.lower():
        out["hover"] = 1
    out.setdefault("walk", 30 if not out else 0)
    return out


def form_speeds(text: str, shape: Optional[str]) -> Dict[str, int]:
    """monster_speeds for a shapechanger: '30 ft. (40 ft. in wolf form)', '30 ft. (fly 50 ft. in raven and hybrid forms)',
    '60 ft. (30 ft. in goblin form)' - the bracket's speeds only in the forms it names (`shape`; None: its true form)."""
    t = text or ""
    if not re.search(r"\bin [\w ,]+? forms?\b", t, re.I):
        return monster_speeds(t)
    base = monster_speeds(re.sub(r"\([^)]*\bforms?\b[^)]*\)", "", t))
    for bracket in re.findall(r"\(([^)]*\bforms?\b[^)]*)\)", t):
        for part in re.split(r";", bracket):
            names = re.search(r"\bin ([\w ,]+?) forms?\b", part, re.I)
            if not names or not shape or shape.lower() not in re.split(r",|\band\b|\bor\b|\s+", names.group(1).lower()):
                continue
            sp = monster_speeds(part[:names.start()])
            if not re.match(r"\s*\d+\s*ft", part):
                sp.pop("walk", None)                         # "fly 50 ft. in raven form": the walk stays
            base.update(sp)
    return base


# ---------------------------------------------------------------------- monster traits that change rolls
TRAIT_MODS = {
    "magic resistance": {"save_adv": ["spells"]},
    "fey ancestry": {"cond_save_adv": ["Charmed"]},
    "brave": {"cond_save_adv": ["Frightened"]},
    "devil's sight": {"senses": {"devils_sight": 120}},
    "magic weapons": {"magic_attacks": True},
    "evasion": {"evasion": True},
    "avoidance": {"evasion": True},
    "mimicry": {},
    "flyby": {"no_opportunity": True},                  # on a flat map a flier is taken to be flying
}


def trait_mods(traits: Iterable[dict]) -> List[dict]:
    """Effects-like entries for passive monster traits the engine applies by itself."""
    out = []
    for t in traits or []:
        name = re.sub(r"\s*\(.*?\)", "", t.get("name", "")).strip().lower()
        if name in TRAIT_MODS and TRAIT_MODS[name]:
            out.append({"name": t["name"], "mods": dict(TRAIT_MODS[name]), "conditions": [], "trait": True})
        elif name.endswith("regeneration"):                # Belial's Fiendish Regeneration too
            m = re.search(r"regains (\d+) hit points", t.get("text", ""))
            stop = re.findall(r"\b(acid|cold|fire|force|lightning|necrotic|radiant|thunder|poison|psychic) damage", t.get("text", ""))
            if m:
                out.append({"name": t["name"], "mods": {"regen": m.group(1), "regen_stop": stop}, "conditions": [], "trait": True})
        elif name == "pack tactics":
            out.append({"name": t["name"], "mods": {"pack_tactics": True}, "conditions": [], "trait": True})
        elif name.startswith("legendary resistance"):
            m = re.search(r"(\d+)/day", t.get("name", ""), re.I)
            out.append({"name": t["name"], "mods": {"legendary_resistance": int(m.group(1)) if m else 3}, "conditions": [], "trait": True})
        elif name == "sunlight sensitivity":
            out.append({"name": t["name"], "mods": {"sunlight_sensitive": True}, "conditions": [], "trait": True})
        elif name in ("incorporeal movement",):
            out.append({"name": t["name"], "mods": {"incorporeal": True}, "conditions": [], "trait": True})
        else:
            mods = text_trait_mods(t.get("text") or "")
            if mods:
                out.append({"name": t["name"], "mods": mods, "conditions": [], "trait": True})
    return out


def bloodied_mods(traits: Iterable[dict]) -> List[dict]:
    """Effects-like entries for traits that only work "While Bloodied, ..." (at half its hit points or fewer): advantage on attacks
    or saves, resistance, condition immunity, a flying speed. Added by profile._all_effects while the creature is Bloodied."""
    out = []
    for t in traits or []:
        text = t.get("text") or ""
        if not re.match(r"While Bloodied, ", text, re.I):
            continue
        low, mods = text.lower(), {}
        if re.search(r"has advantage on attack rolls", low):
            mods["attacks_with"] = "adv"
        if re.search(r"has advantage on saving throws", low):
            mods["save_adv"] = ["all"]
        res = re.search(r"has resistance to ([\w ,]+?) damage", low)
        if res:
            mods["resist"] = [x for x in TYPES if re.search(r"\b" + x + r"\b", res.group(1))]
        imm = re.search(r"has immunity to the ([\w ,]+?) conditions?", low)
        if imm:
            mods["immune_cond"] = [c.capitalize() for c in CONDS if re.search(r"\b" + c + r"\b", imm.group(1))]
        fly = re.search(r"fly speed of (\d+) feet", low)
        if fly:
            mods["fly"] = int(fly.group(1))
        if mods:
            out.append({"name": f"{t['name']} (Bloodied)", "mods": mods, "conditions": [], "trait": True})
    return out


@lru_cache(maxsize=4096)
def has_trait_aura(monster_id: Optional[str]) -> bool:
    """Does this stat block have a trait aura for others (Aura of Command, Aura of Murder)? Cached: asked on every look."""
    from ...rules.monsters import bestiary
    m = bestiary.get(monster_id) if monster_id else None
    return bool(m) and any(t["mods"].get("ally_aura") or t["mods"].get("foe_aura") for t in trait_mods(m.get("traits")))


CONDS = ["blinded", "charmed", "deafened", "frightened", "grappled", "paralyzed", "petrified", "poisoned", "prone", "restrained",
         "stunned", "unconscious"]
COND_ADV = re.compile(r"advantage on saving throws (?:made )?against ([^.;]{1,120})", re.I)


def text_trait_mods(text: str) -> dict:
    """Mods read from a trait's wording when its name isn't one the engine knows: save advantages against conditions
    (Dark Devotion, Duergar Resilience, Two Heads), damage to whoever hits it in melee (Heated Body, Fire Form), damage
    of a type that heals it instead (Fire Absorption, Lightning Absorption). Read once per wording (asked on every look)."""
    return dict(_text_trait_mods(text))


@lru_cache(maxsize=4096)
def _text_trait_mods(text: str) -> tuple:
    mods = {}
    low = text.lower()
    m = COND_ADV.search(low)
    if m:
        what = m.group(1)
        conds = [c.capitalize() for c in CONDS if re.search(r"\b" + c[:-2] + r"\w*\b", what)]
        if "poison" in what and "Poisoned" not in conds:
            conds.append("Poisoned")
        if "knocked unconscious" in what or "put to sleep" in what:
            conds.append("Unconscious")
        if conds:
            mods["cond_save_adv"] = list(dict.fromkeys(conds))
        if re.search(r"\bspells\b|\bany spell\b", what):    # (Spell Turning: "against any spell that targets only the cat")
            mods["save_adv"] = ["spells"]
    m = re.search(r"advantage on ((?:(?:strength|dexterity|constitution|intelligence|wisdom|charisma),? (?:and )?)+)saving throws against "
                  r"(?:spells|magic)", low)
    if m:                                              # Gnome Cunning: Int, Wis and Cha saves against magic
        mods["save_adv_spells"] = [ABILITY_NAMES[a] for a in re.findall(r"strength|dexterity|constitution|intelligence|wisdom|charisma", m.group(1))]
    foe = re.search(r"hostile creatures within (\d+) feet of it gain vulnerability to (\w+) damage", low)
    if foe:                                            # a night blade's Aura of Murder (profile._all_effects hands it out)
        mods["foe_aura"] = {"ft": int(foe.group(1)), "mods": {"vuln": [foe.group(2)]}, "unless_resist": foe.group(2)}
    ally = re.search(r"allies within (\d+) feet of [^.]*?are immune to the charmed and frightened conditions|radiates [^.]*?in a (\d+)-foot-radius "
                     r"sphere centered on itself", low)
    if ally:                                           # Aura of Command: its side near it can't be charmed (or frightened)
        am = {}
        if re.search(r"immune to the charmed and frightened|can't be charmed", low):
            am["immune_cond"] = ["Charmed"] + (["Frightened"] if "charmed and frightened conditions" in low else [])
        if re.search(r"advantage on saving throws made to avoid or end the frightened", low):
            am["cond_save_adv"] = ["Frightened"]
        if am:
            mods["ally_aura"] = {"ft": int(ally.group(1) or ally.group(2)), "mods": am}
    em = re.search(r"(?:in an? (\d+)-foot emanation originating from|within (\d+) feet of [\w' -]+?(?= have\b|,))", low)
    if em and "ally_aura" not in mods and "foe_aura" not in mods:      # the 2024 auras: Marshal Undead, Aura of Authority, Inspiring Presence, Aura of Dread
        am = {}
        if re.search(r"advantage on attack rolls and saving throws", low):
            am.update(attacks_with="adv", save_adv=["all"])
        elif re.search(r"have advantage on attack rolls", low):
            am["attacks_with"] = "adv"
        if re.search(r"advantage on saving throws to avoid or end the charmed or frightened", low):
            am["cond_save_adv"] = ["Charmed", "Frightened"]
        if am:
            mods["ally_aura"] = {"ft": int(em.group(1) or em.group(2)), "mods": am, "only_type": "undead" if low.startswith("undead creatures") else None,
                                 "self_too": bool(re.search(r"the \w+ and its allies", low))}
        elif re.search(r"creatures (?:in an? \d+-foot emanation originating from|within \d+ feet of) [\w' ]+ have their speeds? halved", low):
            mods["foe_aura"] = {"ft": int(em.group(1) or em.group(2)), "mods": {"speed_mult": .5}}
    if re.search(r"has advantage on all ability checks and saving throws", low):     # Tactical Discipline
        mods["save_adv"], mods["check_adv"] = ["all"], True
    if re.search(r"^attack rolls against (?:it|the [\w -]+?) (?:are made with|have) disadvantage", low):
        mods["attacks_against"] = "dis"                # an eidolon's Blurred Form
    if re.search(r"(?:weapon |slam |melee )?attacks are (?:treated as )?magical", low):
        mods["magic_attacks"] = True                   # Angelic Weapons, Empowered Attacks
    if re.search(r"\brerolls? a (?:failed )?saving throw|can reroll a saving throw that it fails", low):
        mods["reroll_save"] = True                     # a champion's Indomitable
    if re.search(r"effects? that turns? undead", low):
        mods["turn_immune" if "immune" in low else "turn_resist"] = True
    m = re.search(r"(?:touches|hits) (?:it|the [\w ]+?) with a melee attack while within 5 (?:feet|ft\.?) of it,? takes \d+ \((\d+d\d+)\) (\w+) damage", low)
    if m:
        mods["retaliate"] = (m.group(1), m.group(2))
    m = re.search(r"subjected to (\w+) damage, it takes no damage and (?:instead )?regains a number of hit points equal to (half )?the \w+ damage", low)
    if m:
        mods["absorb"] = {m.group(1): .5 if m.group(2) else 1.0}
    return tuple(mods.items())
