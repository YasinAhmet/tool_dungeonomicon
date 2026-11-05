"""What every service shares: the user-facing error, the side-effect hooks, input checks and roll results.

Every change to the game state goes through a service (app.services.*) so that logging, the Discord log channel and
the windows' refreshes happen the same way whoever made it - a click in the editor, a slash command or a button.
"""
import re
from dataclasses import dataclass
from typing import Callable, Optional

from ..core.storage import validate_name
from ..rules.leveling import RulesError
from ..rules.dice import DiceResult, roll_dice

ARCHIVE_FOLDER = "archive/characters"


class ServiceError(Exception):
    """A user-facing failure (bad input, missing record, broken rule...). The message is safe to show."""


class Busy(ServiceError):
    """Not a failure: the battle is waiting (dice still rolling, a reaction to answer). Show it as information."""


def _noop(*_a, **_k):
    return None


@dataclass
class Hooks:
    """Side effects the services trigger; the App wires these to the real thing."""
    log: Callable[[str], None] = _noop                      # admin log line
    notify: Callable[[str], None] = _noop                   # emit a UiBus topic
    discord_log: Callable[[str, str], None] = _noop         # (message, log kind) to the Discord log channel
    session: object = None                                  # SessionLogger (optional)
    user_name: Callable[[int], Optional[str]] = _noop       # Discord user ID -> display name, if found


def valid_name(name: str, what: str) -> str:
    try:
        return validate_name(name, what)
    except ValueError as e:
        raise ServiceError(str(e))


def positive_int(value, what: str) -> int:
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        raise ServiceError(f"{what} must be a whole number.")
    if number <= 0:
        raise ServiceError(f"{what} must be positive.")
    return number


def whole_int(value, what: str, low: int = 0, high: int = 10 ** 9) -> int:
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        raise ServiceError(f"{what} must be a whole number.")
    if not low <= number <= high:
        raise ServiceError(f"{what} must be between {low} and {high}.")
    return number


def rules_errors(fn):
    """Turn rule violations from the rules engine into ServiceErrors."""
    def wrapper(*args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except RulesError as e:
            raise ServiceError(str(e))
    wrapper.__name__ = fn.__name__
    wrapper.__doc__ = fn.__doc__
    return wrapper


def plain_text(text: str) -> str:
    return re.sub(r"\*\*|\*|__|`", "", text)


def roll_damage_expression(expr: str) -> DiceResult:
    try:
        return roll_dice(expr)
    except Exception as e:                      # DiceError and friends
        raise ServiceError(f"Can't roll '{expr}': {e}")


@dataclass
class RollResult:
    total: int
    text: str
    natural: Optional[int] = None
