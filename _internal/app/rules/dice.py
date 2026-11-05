"""Dice expressions: '1d20+3', '2d6+1d4-2'. The one dice roller every part of the app uses."""
import re
import random

class DiceError(Exception):
    pass

class DiceResult:
    def __init__(self, total, breakdown, plain=False):
        self.total = total
        self.breakdown = breakdown      # the dice and bonuses, e.g. "2d6 [3, 5] +3" (no total)
        self.plain = plain              # one die and nothing else: the breakdown only repeats the total

def roll_dice(expr: str) -> DiceResult:
    """Parse and roll expressions like '1d20+3' or '2d6+1d4-2'."""
    expr = expr.replace(" ", "")
    if not expr:
        raise DiceError("Empty expression")

    tokens = re.findall(r'([+-]?\d*d\d+|[+-]?\d+)', expr)
    if not tokens:
        raise DiceError("No valid dice or numbers found")

    total = 0
    parts = []
    for tok in tokens:
        if 'd' in tok:
            sign = 1
            if tok.startswith('-'):
                sign = -1
                tok = tok[1:]
            elif tok.startswith('+'):
                tok = tok[1:]
            try:
                count, sides = tok.split('d')
                count = int(count) if count else 1
                sides = int(sides)
            except ValueError:
                raise DiceError(f"Invalid dice format: {tok}")
            if count < 1 or sides < 1:
                raise DiceError("Dice must have positive sides and count")
            rolls = [random.randint(1, sides) for _ in range(count)]
            total += sum(rolls) * sign
            dice = f"{count if count > 1 else ''}d{sides} [{', '.join(map(str, rolls))}]"
            parts.append(("-" if not parts else "- ") + dice if sign < 0 else ("+ " if parts else "") + dice)
        else:
            val = int(tok)
            total += val
            parts.append(f"{val:+d}" if parts else str(val))
    plain = len(tokens) == 1 and 'd' in tokens[0] and not tokens[0].startswith('-') and len(rolls) == 1
    return DiceResult(total, " ".join(parts), plain)