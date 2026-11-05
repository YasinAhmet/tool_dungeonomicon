"""The action economy: what a creature may still do this turn. Pure functions over the combatant's 'turn' dict.

    turn = {'action': 1, 'bonus': 1, 'reaction': 1, 'move': 30, 'speed': 30, 'object': 1, 'attacks': 0,
            'legendary': 0, 'legendary_max': 0, 'spells': [[cost, level], ...], 'dashed': 0, 'disengaged': False,
            'dodging': False}

Haste's extra action is counted in 'haste' (also in 'action'): while only that one is left it can't cast a spell and
the Attack action makes one weapon attack (PHB Haste: Attack (one weapon attack only), Dash, Disengage, Hide, Use an Object).

Costs are 'action', 'bonus', 'reaction', 'object', 'free', 'legendary:N', 'move:FEET', 'long' (casting times of a
minute or more: not in battle) or 'on_hit' (a smite: readied for free, cast when a weapon hit lands). 'attacks' counts the attacks the Attack action still has (Extra Attack): the first
attack spends the action and sets it, the rest spend it.
"""
import re
from typing import Optional, Tuple

COSTS = ("action", "bonus", "reaction", "object", "free", "long", "on_hit")
LABEL = {"action": "Action", "bonus": "Bonus action", "reaction": "Reaction", "object": "Free object interaction",
         "free": "Free", "long": "Takes longer than a turn", "on_hit": "On hit"}


def new_turn(speed: int, legendary_max: int = 0, extra_actions: int = 0) -> dict:
    return {"action": 1 + extra_actions, "haste": extra_actions, "bonus": 1, "reaction": 1, "move": max(0, int(speed)), "speed": max(0, int(speed)),
            "object": 1, "attacks": 0, "legendary": legendary_max, "legendary_max": legendary_max, "spells": [],
            "dashed": 0, "disengaged": False, "dodging": False, "used": []}


def casting_cost(casting_time: str) -> str:
    """'1 action' -> 'action', '1 bonus action' (or '1 bonus') -> 'bonus', '1 reaction, which you take...' -> 'reaction', '1 minute' -> 'long'."""
    t = (casting_time or "").lower()
    if re.search(r"\bbonus\b", t):
        return "bonus"
    if "reaction" in t:
        return "reaction"
    if re.search(r"\b1 action\b|^action", t):
        return "action"
    if re.search(r"minute|hour|day", t):
        return "long"
    return "action"


def parse(cost: str) -> Tuple[str, int]:
    """'legendary:2' -> ('legendary', 2); 'move:15' -> ('move', 15); 'action' -> ('action', 1)."""
    kind, _, n = (cost or "free").partition(":")
    return kind, int(n) if n.isdigit() else 1


def why_not(turn: Optional[dict], cost: str) -> Optional[str]:
    """None when the cost can be paid, else the reason (shown on the greyed-out button)."""
    if turn is None:
        return None
    kind, n = parse(cost)
    if kind in ("free", "on_hit"):
        return None
    if kind == "long":
        return "Casting it takes longer than a turn"
    if kind == "move":
        return None if turn.get("move", 0) >= n else f"Only {turn.get('move', 0)} ft of movement left"
    if kind == "legendary":
        return None if turn.get("legendary", 0) >= n else "No legendary actions left"
    if kind == "attack":                                  # one attack of the Attack action (or the action itself)
        return None if turn.get("attacks", 0) > 0 or turn.get("action", 0) > 0 else "No action left"
    have = turn.get(kind, 0)
    if have >= n:
        return None
    return {"action": "No action left", "bonus": "Bonus action already used", "reaction": "Reaction already used",
            "object": "Free object interaction already used"}.get(kind, "Not available")


def spend(turn: Optional[dict], cost: str, what: str = "") -> None:
    if turn is None:
        return
    kind, n = parse(cost)
    if kind in ("free", "long", "on_hit"):
        return
    if kind == "move":
        turn["move"] = max(0, turn.get("move", 0) - n)
    elif kind == "attack":
        if turn.get("attacks", 0) > 0:
            turn["attacks"] -= 1
        else:
            turn["action"] = max(0, turn.get("action", 0) - 1)
    else:
        turn[kind] = max(0, turn.get(kind, 0) - n)
    _haste_left(turn)
    if what:
        turn.setdefault("used", []).append(what)


def haste_only(turn: Optional[dict]) -> bool:
    """Only Haste's limited extra action is left this turn."""
    return bool(turn) and turn.get("haste", 0) > 0 and turn.get("action", 0) <= turn.get("haste", 0)


def _haste_left(turn: dict) -> None:
    """The ordinary action is spent first; Haste's action is the last one left."""
    turn["haste"] = min(turn.get("haste", 0), turn.get("action", 0))


def refund(turn: Optional[dict], cost: str) -> None:
    if turn is None:
        return
    kind, n = parse(cost)
    if kind == "move":
        turn["move"] = turn.get("move", 0) + n
    elif kind in ("action", "bonus", "reaction", "object", "legendary"):
        turn[kind] = turn.get(kind, 0) + n


def start_attack_action(turn: Optional[dict], attacks: int) -> None:
    """The Attack action was taken for the first attack: the remaining attacks of Extra Attack are free to make."""
    if turn is None:
        return
    if turn.get("attacks", 0) > 0:
        turn["attacks"] -= 1
    else:
        one = haste_only(turn)                              # Haste's action: one weapon attack, no Extra Attack
        turn["action"] = max(0, turn.get("action", 0) - 1)
        turn["attacks"] = 0 if one else max(0, attacks - 1)
        _haste_left(turn)


def spell_rule(turn: Optional[dict], cost: str, level: int) -> Optional[str]:
    """PHB: after a bonus-action spell, the only other spell that turn is a cantrip with a casting time of 1 action
    (and the other way round)."""
    if turn is None or cost not in ("action", "bonus"):
        return None
    if cost == "action" and haste_only(turn):
        return "Haste's extra action can't cast a spell"
    cast = turn.get("spells") or []
    if cost == "bonus" and any(c == "action" and lvl > 0 for c, lvl in cast):
        return "You already cast a leveled spell this turn; a bonus-action spell isn't allowed"
    if any(c == "bonus" for c, _l in cast):
        if cost == "bonus":
            return "You already cast a bonus-action spell this turn"
        if level > 0:
            return "After a bonus-action spell only a cantrip can be cast this turn"
    return None


def note_spell(turn: Optional[dict], cost: str, level: int) -> None:
    if turn is not None and cost in ("action", "bonus"):
        turn.setdefault("spells", []).append([cost, int(level)])


def dash(turn: Optional[dict]) -> None:
    if turn is not None:
        turn["move"] = turn.get("move", 0) + turn.get("speed", 0)
        turn["dashed"] = turn.get("dashed", 0) + 1
