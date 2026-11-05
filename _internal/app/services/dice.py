"""Free dice rolls (the Dice window, /roll, the console) and their history."""
import threading
from datetime import datetime
from typing import List, Optional

from ..core import events
from ..core.storage import read_json, write_json, write_json_soon
from ..rules.dice import DiceError, DiceResult, roll_dice

DICE_HISTORY_FILE = "data/dice_history.json"
DICE_HISTORY_LIMIT = 100
__all__ = ["DiceService", "DiceError", "DiceResult"]


class DiceService:
    def __init__(self, hooks):
        self.h = hooks
        self._lock = threading.Lock()
        history = read_json(DICE_HISTORY_FILE, [])
        self.history: List[dict] = history[-DICE_HISTORY_LIMIT:]

    def roll(self, expression: str, who: str = "GUI", announce_as: Optional[str] = None) -> DiceResult:
        """Roll, record in history/session log and notify. Raises DiceError on bad input.

        `announce_as` (a player's name) also posts the roll to the Discord log channel."""
        result = roll_dice(expression)
        shown = str(result.total) if result.plain else f"{result.total} ({result.breakdown})"
        entry = {"timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"), "expression": expression,
                 "result": shown, "user": who}
        with self._lock:
            self.history.append(entry)
            self.history = self.history[-DICE_HISTORY_LIMIT:]
            write_json_soon(DICE_HISTORY_FILE, self.history)     # every roll: saved by the writer thread
        if self.h.session:
            self.h.session.log_dice_roll(who, expression, shown)
        self.h.log(f"{who} rolled {expression} => {result.total}")
        if announce_as:
            self.h.discord_log(f"🎲 **{announce_as}** · {expression} · **{result.total}**"
                               + ("" if result.plain else f" · {result.breakdown}"), "player_rolls")
        self.h.notify(events.DICE)
        return result

    def clear(self):
        with self._lock:
            self.history = []
            write_json(DICE_HISTORY_FILE, self.history)
        self.h.notify(events.DICE)
