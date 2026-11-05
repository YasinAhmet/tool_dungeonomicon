"""Loading and saving the one battle, the battle log, and the views other parts read."""
import random
import threading
from typing import Callable, List, Optional

from ...core import events
from ...core.storage import clone, read_json, write_json_soon
from ...rules.character import Character
from ..characters.base import CharacterServiceBase
from ..common import ServiceError
from .constants import ACTIVE, BATTLE_FILE, MAP_DEFAULT, MAX_LOG, blank_battle, faction_colors
from .props import upgrade as upgrade_props


class _Lock:
    """The battle's re-entrant lock, counting how deep the thread holding it is (an action made of smaller actions
    becomes one undo step: only the outermost one records it)."""
    def __init__(self):
        self._l = threading.RLock()
        self.depth = 0

    def acquire(self, *a, **k) -> bool:
        ok = self._l.acquire(*a, **k)
        if ok:
            self.depth += 1
        return ok

    def release(self):
        self.depth -= 1
        self._l.release()

    def __enter__(self):
        self.acquire()
        return self

    def __exit__(self, *_exc):
        self.release()


class BattleBase:
    def __init__(self, hooks, characters, rng: random.Random = random, path: str = BATTLE_FILE, persist: bool = True):
        self.h = hooks
        self.chars = characters
        self.rng = rng
        self.path = path                                    # (its folder also keeps the map pictures and saved encounters)
        self.persist = persist                              # False: never read from or saved to `path` (the duel)
        self.lock = _Lock()
        self.version = 0                                    # goes up with every commit (the windows' view cache)
        self._char_memo = None
        data = read_json(path, None) if persist else None
        self.b: dict = data if isinstance(data, dict) and "combatants" in data else blank_battle()
        self.b.setdefault("map", {"w": MAP_DEFAULT[0], "h": MAP_DEFAULT[1]})
        self.b.setdefault("target", None)
        self.b.setdefault("targets", [])
        self.b.setdefault("events", [])
        upgrade_props(self.b.get("drawings"))
        self.line_sinks: List[Callable[[str], None]] = []   # e.g. the Discord log
        self.listeners: List[Callable[[], None]] = []      # e.g. the Discord live messages
        self._removed: List[tuple] = []                     # (battle, combatant, index, turn, round) for undo_remove
        self._history_reset()

    # ------------------------------------------------------------------ plumbing
    def _event(self, text: str):
        """One line per thing that happened (a whole attack with its damage is one event); /battlemap shows the last five."""
        self.b.setdefault("events", []).append(text)
        del self.b["events"][:-40]

    def _say(self, line: str, event: bool = True):
        """A line for the battle log (and the Discord channel) without saving yet."""
        if event:
            self._event(line)
        self._since.append(line)                            # the next undo step's name comes from these
        del self._since[:-20]
        self.b["log"].append(f"R{self.b['round']}: {line}" if self.b["status"] == ACTIVE else line)
        del self.b["log"][:-MAX_LOG]
        self.h.log(f"[BATTLE] {line}")
        for sink in list(self.line_sinks):
            try:
                sink(line)
            except Exception as e:
                self.h.log(f"[BATTLE] could not send the line: {e}")

    def _vfx(self, kind: str, **data):
        """Something for the screens to play - a step, a hit, a miss, a burst of fire...: kept briefly in b['fx'], numbered."""
        n = self.b.get("fx_n", 0) + 1
        self.b["fx_n"] = n
        fx = self.b.setdefault("fx", [])
        fx.append({**data, "n": n, "k": kind})
        del fx[:-80]

    def _area_vfx(self, by: Optional[dict], tiles, parts=(), shape: str = "", at=None):
        """An area going off (a fireball, a breath, a burst...): its tiles flash in the colour of its damage."""
        dtype = next((str(t).lower() for _d, t in parts or () if t), "")
        cells = sorted([int(x), int(y)] for x, y in tiles if x >= 0 and y >= 0)
        if cells:
            self._vfx("area", by=by["id"] if by else None, tiles=cells, dtype=dtype, shape=shape, at=list(at) if at else None)

    def _npc_roll(self, c: Optional[dict], icon: str, label: str, total, detail: str = ""):
        """One compact line in the Discord log for a roll made by a non-player creature (if the GM allows NPC rolls)."""
        if c is not None and c["kind"] != "pc":
            self._roll_line(c, icon, label, total, detail)

    def _roll_line(self, c: Optional[dict], icon: str, label: str, total, detail: str = ""):
        """A roll in battle for the table feed and the Discord log: a monster's as an NPC roll (if the GM allows NPC
        rolls), a character's as a player roll - so everyone reads a player's attack too, not just the DM's Battle log."""
        if c is not None:
            self.h.discord_log(f"{icon} **{c['name']}** · {label} · **{total}**" + (f" · {detail}" if detail else ""),
                               "player_rolls" if c["kind"] == "pc" else "npc_rolls")

    def _commit(self, line: Optional[str] = None, label: Optional[str] = None):
        """Log `line`, record the undo step (named `label`, else `line`), save battle.json and tell every screen."""
        if line:
            self._say(line)
        if self.b.get("vanish"):
            self._flush_vanished()
        self._loose_grapples()
        self._loose_concentration()
        self.version += 1
        self._history_step(label or line)
        if self.persist:
            write_json_soon(self.path, self.b)              # saved by a writer thread: the screen doesn't wait for the disk
        self.h.notify(events.BATTLE)
        for fn in list(self.listeners):
            try:
                fn()
            except Exception as e:                                   # a dead Discord message must not break the tracker
                self.h.log(f"[BATTLE] listener failed: {e}")

    def _find(self, cid: int) -> dict:
        for c in self.b["combatants"]:
            if c["id"] == cid:
                return c
        raise ServiceError("That combatant is no longer in the battle.")

    # ------------------------------------------------------------------ views
    def state(self) -> dict:
        with self.lock:
            return clone(self.b)

    def log_lines(self) -> list:
        """The battle log (a copy), oldest first - cheaper than view() for who only wants the lines."""
        with self.lock:
            return list(self.b.get("log") or [])

    def view(self) -> dict:
        """The battle with live hit points / AC / conditions of the player characters filled in."""
        with self.lock:
            data = clone(self.b)
            data["faction_colors"] = {str(k): v for k, v in faction_colors(self.b).items()}
            for c in data["combatants"]:
                self._live(c)
            return data

    def _live(self, c: dict):
        """Fill a copied combatant with its live numbers (view())."""
        if c["kind"] == "pc":
            char = self._char(c["character"])
            if char:
                if getattr(char, "_frozen", None) is None:
                    char._frozen = {}                   # only read here: its items and scores worked out once
                c.update(hp=char.current_hp, max_hp=char.max_hp, ac=char.armor_class()[0],
                         conditions=list(char.conditions), temp_hp=char.temp_hp,
                         init_bonus=char.initiative, defeated=False)
                c["downed"] = char.current_hp <= 0
                ds = char.d.get("death_saves") or {}
                c["dead"] = c["downed"] and ds.get("failure", 0) >= 3
                c["stable"] = c["downed"] and not c["dead"] and ds.get("success", 0) >= 3
                c["dsaves"] = [int(ds.get("success") or 0), int(ds.get("failure") or 0)] if c["downed"] else None   # its pips
            else:
                c["missing"] = True
        else:
            c["defeated"] = c["hp"] <= 0
        c["faction"] = self._side(c)                    # the side it fights for now (dominated: its master's) and its colour
        c["faction_color"] = faction_colors(self.b).get(c["faction"], "#e0524d")
        timers = self.cond_timers(c)                    # the DM's condition timers, for countdowns
        c["cond_timers"] = {k: v for k, v in timers.items() if k in (c.get("conditions") or [])}

    def _char(self, name: Optional[str]):
        memo = getattr(self, "_char_memo", None)       # {name: Character} on a frozen copy of the battle (battle.menu)
        if memo is not None and name:
            if name not in memo:
                memo[name] = char = self._load_char(name)
                if char is not None:
                    char._frozen = {}                   # read-only while menus are built (rules/character.py)
            return memo[name]
        return self._load_char(name)

    def _peek(self, c: Optional[dict]):
        """A player character's sheet only to read - never to change or save: the same object for every reader while
        its file is unchanged (HP checks, "is it down", feats: a battle action asks hundreds of times)."""
        if not c or c.get("kind") != "pc" or not c.get("character"):
            return None
        if getattr(self, "_char_memo", None) is not None or not isinstance(self.chars, CharacterServiceBase):
            return self._char(c["character"])              # (a frozen copy of the battle, or a stand-in roster)
        return Character.peek(c["character"])

    def _load_char(self, name: Optional[str]):
        try:
            return self.chars.get(name) if name else None
        except ServiceError:
            return None

    def current(self) -> Optional[dict]:
        with self.lock:                                 # only that creature copied and filled in, not the whole battle
            cid = self.b["turn"]
            c = next((x for x in self.b["combatants"] if x["id"] == cid), None) if cid else None
            if c is None:
                return None
            c = clone(c)
            self._live(c)
            return c

    def turn_of_user(self, user_id: int) -> Optional[str]:
        """Name of this player's character whose turn it is, or None."""
        cur = self.current()
        if cur and cur["kind"] == "pc" and cur["character"] in self.chars.characters_of(user_id):
            return cur["character"]
        return None

    def user_combatants(self, user_id: int) -> List[dict]:
        names = set(self.chars.characters_of(user_id))
        return [c for c in self.view()["combatants"] if c["kind"] == "pc" and c["character"] in names]
