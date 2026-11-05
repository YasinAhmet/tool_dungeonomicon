"""Pure 5e rules math: no I/O, no UI. Everything here is deterministic or takes an RNG."""
import random
import re
from typing import Dict, Iterable, List, Optional, Tuple

ABILITIES = ["str", "dex", "con", "int", "wis", "cha"]
ABILITY_NAMES = {"str": "Strength", "dex": "Dexterity", "con": "Constitution",
                 "int": "Intelligence", "wis": "Wisdom", "cha": "Charisma"}
ABILITY_SHORT = {k: k.capitalize() for k in ABILITIES}
NAME_TO_ABILITY = {v.lower(): k for k, v in ABILITY_NAMES.items()}

ALIGNMENTS = ["Lawful Good", "Neutral Good", "Chaotic Good", "Lawful Neutral", "True Neutral", "Chaotic Neutral",
              "Lawful Evil", "Neutral Evil", "Chaotic Evil", "Unaligned"]

XP_THRESHOLDS = [0, 300, 900, 2700, 6500, 14000, 23000, 34000, 48000, 64000, 85000, 100000, 120000, 140000,
                 165000, 195000, 225000, 265000, 305000, 355000]
MAX_LEVEL = 20
MAX_ABILITY = 20

POINT_BUY_COST = {8: 0, 9: 1, 10: 2, 11: 3, 12: 4, 13: 5, 14: 7, 15: 9}
POINT_BUY_BUDGET = 27
STANDARD_ARRAY = [15, 14, 13, 12, 10, 8]

COINS = ("cp", "sp", "ep", "gp", "pp")
COIN_IN_CP = {"cp": 1, "sp": 10, "ep": 50, "gp": 100, "pp": 1000}

# PHB p.165 - Multiclass Spellcaster: Spell Slots per Spell Level (index = caster level - 1)
MULTICLASS_SLOTS = [
    [2], [3], [4, 2], [4, 3], [4, 3, 2], [4, 3, 3], [4, 3, 3, 1], [4, 3, 3, 2], [4, 3, 3, 3, 1],
    [4, 3, 3, 3, 2], [4, 3, 3, 3, 2, 1], [4, 3, 3, 3, 2, 1], [4, 3, 3, 3, 2, 1, 1], [4, 3, 3, 3, 2, 1, 1],
    [4, 3, 3, 3, 2, 1, 1, 1], [4, 3, 3, 3, 2, 1, 1, 1], [4, 3, 3, 3, 2, 1, 1, 1, 1],
    [4, 3, 3, 3, 3, 1, 1, 1, 1], [4, 3, 3, 3, 3, 2, 1, 1, 1], [4, 3, 3, 3, 3, 2, 2, 1, 1],
]


# ---------------------------------------------------------------- abilities
def modifier(score: int) -> int:
    return (score - 10) // 2


def proficiency_bonus(level: int) -> int:
    return 2 + (max(level, 1) - 1) // 4


def level_for_xp(xp: int) -> int:
    level = 1
    for i, threshold in enumerate(XP_THRESHOLDS, start=1):
        if xp >= threshold:
            level = i
    return level


def xp_for_next_level(level: int) -> Optional[int]:
    return XP_THRESHOLDS[level] if level < MAX_LEVEL else None


# ---------------------------------------------------------------- ability score generation
def point_buy_total(scores: Dict[str, int]) -> int:
    """Points spent. Raises ValueError for scores outside the 8-15 point-buy range."""
    total = 0
    for ability in ABILITIES:
        score = scores[ability]
        if score not in POINT_BUY_COST:
            raise ValueError(f"{ABILITY_NAMES[ability]} must be between 8 and 15 for point buy.")
        total += POINT_BUY_COST[score]
    return total


def validate_point_buy(scores: Dict[str, int]) -> None:
    spent = point_buy_total(scores)
    if spent > POINT_BUY_BUDGET:
        raise ValueError(f"Point buy spends {spent} points; the limit is {POINT_BUY_BUDGET}.")


def validate_standard_array(scores: Dict[str, int]) -> None:
    if sorted(scores[a] for a in ABILITIES) != sorted(STANDARD_ARRAY):
        raise ValueError(f"Standard array scores must be exactly {', '.join(map(str, STANDARD_ARRAY))}.")


def roll_ability_score(rng: random.Random = random) -> Tuple[int, List[int]]:
    """4d6, drop the lowest. Returns (score, the four dice)."""
    dice = [rng.randint(1, 6) for _ in range(4)]
    return sum(dice) - min(dice), dice


def roll_ability_scores(rng: random.Random = random) -> List[Tuple[int, List[int]]]:
    return [roll_ability_score(rng) for _ in range(6)]


# ---------------------------------------------------------------- hit points
def average_hp(hit_die: int) -> int:
    """The fixed hit point gain per level: half the die + 1."""
    return hit_die // 2 + 1


def roll_hit_die(hit_die: int, rng: random.Random = random) -> int:
    return rng.randint(1, hit_die)


# ---------------------------------------------------------------- spell slots
def caster_levels(classes: Iterable[Tuple[str, int, Optional[str]]]) -> int:
    """Multiclass caster level. `classes` = (class name, level, caster progression).

    Progression: 'full' (bard, cleric, druid, sorcerer, wizard), '1/2' (paladin, ranger),
    '1/3' (eldritch knight, arcane trickster). Warlocks use pact magic and don't count.
    """
    total = 0
    for _name, level, progression in classes:
        if progression == "full":
            total += level
        elif progression == "1/2":
            total += level // 2
        elif progression == "1/3":
            total += level // 3
        elif progression == "artificer":      # half, rounded up
            total += (level + 1) // 2
    return total


def multiclass_slots(caster_level: int) -> List[int]:
    if caster_level <= 0:
        return [0] * 9
    row = MULTICLASS_SLOTS[min(caster_level, 20) - 1]
    return row + [0] * (9 - len(row))


# ---------------------------------------------------------------- money & weight
def to_copper(coins: Dict[str, int]) -> int:
    return sum(coins.get(c, 0) * COIN_IN_CP[c] for c in COINS)


def parse_gold_roll(text: str) -> Tuple[int, int, int]:
    """'4d4 × 10' -> (4, 4, 10): number of dice, sides, multiplier."""
    m = re.search(r"(\d+)d(\d+)\s*[×x*]\s*(\d+)", text)
    if not m:
        raise ValueError(f"Cannot read starting gold '{text}'.")
    return int(m.group(1)), int(m.group(2)), int(m.group(3))


def roll_starting_gold(text: str, rng: random.Random = random) -> int:
    n, sides, mult = parse_gold_roll(text)
    return sum(rng.randint(1, sides) for _ in range(n)) * mult


SIZE_CAPACITY_MULTIPLIER = {"Tiny": 0.5, "Small": 1, "Medium": 1, "Large": 2, "Huge": 4, "Gargantuan": 8}


def carrying_capacity(strength: int, size: str = "Medium") -> int:
    """PHB: carrying capacity = Strength x 15 lb; push/drag/lift = x30."""
    return int(strength * 15 * SIZE_CAPACITY_MULTIPLIER.get(size, 1))


def encumbrance_status(weight: float, strength: int, size: str = "Medium") -> str:
    """Variant encumbrance rule (PHB ch.7): > STR x5 encumbered, > STR x10 heavily encumbered."""
    mult = SIZE_CAPACITY_MULTIPLIER.get(size, 1)
    if weight > carrying_capacity(strength, size):
        return "Over capacity"
    if weight > strength * 10 * mult:
        return "Heavily encumbered"
    if weight > strength * 5 * mult:
        return "Encumbered"
    return "Unencumbered"


# ---------------------------------------------------------------- formulas from class data
def eval_prepared_formula(formula: str, level: int, mods: Dict[str, int]) -> int:
    """Class 'preparedSpells' strings, e.g. '<$level$> + <$wis_mod$>' or '<$level$> / 2 + <$cha_mod$>'."""
    expr = formula.replace("<$level$>", str(level))
    for key, value in mods.items():
        expr = expr.replace("<$" + key + "_mod$>", str(value))
    expr = re.sub(r"(\d+)\s*/\s*(\d+)", r"(\1//\2)", expr)
    if not re.fullmatch(r"[\d\s+\-*/()]+", expr):
        raise ValueError(f"Unsupported prepared-spells formula: {formula}")
    return max(1, eval(expr, {"__builtins__": {}}))  # digits and operators only (checked above)


def ordinal(n: int) -> str:
    suffix = "th" if 10 <= n % 100 <= 20 else {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
    return f"{n}{suffix}"


def pay_coins(coins: Dict[str, int], cost_cp: int) -> Dict[str, int]:
    """Pay `cost_cp` copper from a purse, spending the smallest coins first and making change.

    Returns the new purse. Raises ValueError if the character can't afford it.
    """
    if to_copper(coins) < cost_cp:
        raise ValueError("Not enough money.")
    purse = {c: coins.get(c, 0) for c in COINS}
    remaining = cost_cp
    for coin in ("cp", "sp", "gp", "ep", "pp"):          # smallest to largest (electrum is rarely used)
        value = COIN_IN_CP[coin]
        use = min(purse[coin], -(-remaining // value))   # ceil: may overpay with a bigger coin
        purse[coin] -= use
        remaining -= use * value
        if remaining <= 0:
            break
    change = -remaining                                  # overpaid copper comes back as change
    for coin in ("pp", "gp", "sp", "cp"):
        value = COIN_IN_CP[coin]
        purse[coin] += change // value
        change %= value
    return purse


def roll_d20(modifier_: int, advantage: Optional[str] = None, rng: random.Random = random) -> Tuple[int, List[int]]:
    """Roll d20 + modifier. advantage: 'adv', 'dis' or None. Returns (total, kept/rolled dice)."""
    rolls = [rng.randint(1, 20)]
    if advantage in ("adv", "dis"):
        rolls.append(rng.randint(1, 20))
    kept = max(rolls) if advantage == "adv" else min(rolls) if advantage == "dis" else rolls[0]
    return kept + modifier_, rolls


def double_dice(expression: str) -> str:
    """Critical hit: roll the damage dice twice. '2d6' -> '4d6'; flat modifiers are not doubled."""
    return re.sub(r"(\d*)d(\d+)", lambda m: f"{2 * int(m.group(1) or 1)}d{m.group(2)}", expression)
