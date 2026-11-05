"""The duels (`rt().duel`): side fights for fun, as many at once as the players like. The DM opens duel mode; then
anyone - a player on their page, or the DM in the editor - opens a lobby and others join it, each picking what they
fight as: a premade hero (a core class at level 1 to 12, with the spells they like), a random monster of a challenge
rating, or a copy of one of their own characters. The lobby's host (or the DM) starts it, it is fought out on a map
of its own, and any player may watch any lobby. Nothing of it stays: each lobby has a battle tracker of its own - the
same engine, so every tool of the battle windows works on it - that is never saved, its heroes' sheets live in memory
only (roster.py), and nothing is written to the logs, the table feed or Discord. Closing duel mode throws it all away.

    duel = rt().duel
    duel.set_open(True)                                  # players see the Duel tab
    room = duel.create(uid)                              # a lobby hosted by this player (None: the DM's)
    duel.join(uid, room.id, {"kind": "hero", "class": "Wizard", "level": 5, "spells": ["Fire Bolt", "Shield"]})
    duel.join(uid2, room.id, {"kind": "monster", "cr": "3"})          # (or "monster": an id from fighters.monsters(cr))
    duel.join(uid3, room.id, {"kind": "copy", "character": "Bram"})   # a copy of their own character: the real one untouched
    duel.watch(uid4, room.id)                            # someone else watches it
    duel.start(room.id, uid)                             # its host (None: the DM) - fighters made and placed, initiative rolled
    with duel.scope(room): rt().battle...                # this thread works on that duel (a player's duel request)
    duel.show(True, room.id)                             # the editor's battle windows show it (the UI thread only)
    duel.stop(room.id)                                   # back to its lobby: the fight and its fighters gone, the arena stays
    duel.close(room.id)                                  # the lobby gone
    duel.set_open(False)                                 # all of them gone

rt().battle is the campaign's battle everywhere except on a thread bound to a duel (scope()) and on the editor's UI
thread while the DM shows one there (show()). A duel's changes emit events.DUEL (and BATTLE while it is shown).
"""
import contextvars
import math
import os
import random
import re
import threading
from contextlib import contextmanager
from typing import Dict, List, Optional

from ...core import events
from ...core.storage import clone
from ...rules.character import Character, in_memory
from ...rules.monsters import bestiary
from ..battle import ACTIVE, BattleService
from ..battle import floors as FL
from ..battle.constants import FACTIONS, blank_battle
from ..common import Hooks, ServiceError
from . import fighters as F
from .roster import DuelRoster

_BOUND = contextvars.ContextVar("duel_bound", default=None)     # the duel battle this thread works on
_MAIN = threading.main_thread()
ARENA = (16, 12)                                       # a new arena's tiles
ARENA_KEYS = ("map", "drawings", "draw_next", "faction_colors", "rules", "reveal_hp", "name")   # what the next fight keeps
MAX_FIGHTERS = 8
MAX_ROOMS = 12


class Room:
    """One lobby and its duel: who joined it and as what, and its own battle tracker (in the lobby: the arena)."""

    def __init__(self, svc: "DuelService", rid: int, name: str, host: Optional[int]):
        self.svc, self.id, self.name = svc, rid, name
        self.host = host                               # a player's id - or None: the DM's lobby
        self.picks: Dict[int, dict] = {}               # player id -> what they fight as (in the order they joined)
        self.fighters: Dict[int, int] = {}             # player id -> their fighter's combatant id (while running)
        self.running = False                           # the fighters are made and fighting, until the duel is ended
        self.battle = self._new_battle()

    # ------------------------------------------------------------------ its battle
    def _new_battle(self, keep: Optional[dict] = None) -> BattleService:
        svc = self.svc
        hooks = Hooks(notify=lambda _topic: svc._changed(self))     # no log, no Discord, no session log: nothing is kept
        b = BattleService(hooks, DuelRoster(hooks, svc.players), rng=svc.rng, path=svc.campaign.path,
                          persist=False)               # (its folder: the map pictures and saved encounters are shared)
        b.b = blank_battle(self.name)
        b.b.update(map={"w": ARENA[0], "h": ARENA[1]}, reveal_hp=True, rules=clone(svc.campaign.b.get("rules") or {}))
        b.b.update(clone(keep or {}))
        b.b["duel"] = True                             # (a fight of heroes alone may start)
        b._history_reset()
        return b

    def _arena(self) -> dict:
        return {k: self.battle.b[k] for k in ARENA_KEYS if k in self.battle.b}

    def drop(self) -> None:
        """The fight and its fighters gone (their sheets let go)."""
        self.battle.chars.clear()
        self.fighters = {}
        self.running = False

    def use_campaign_map(self) -> None:
        """The campaign battle's map (its size, walls, drawings and pictures) becomes the arena."""
        if self.running:
            raise ServiceError("End the duel first: the fighters stand on this arena.")
        src = self.svc.campaign.state()
        self.battle = self._new_battle({k: src[k] for k in ("map", "drawings", "draw_next", "faction_colors") if k in src})

    def new_arena(self) -> None:
        if self.running:
            raise ServiceError("End the duel first: the fighters stand on this arena.")
        self.battle = self._new_battle()

    def start(self) -> str:
        """Make every joined player's fighter, put them around the arena (each on a side of their own), roll
        initiative and begin."""
        if self.running:
            raise ServiceError("The duel is already on. End it first.")
        if not self.picks:
            raise ServiceError("Nobody has joined the duel yet.")
        b = self.battle
        if b.b["status"] == ACTIVE:
            raise ServiceError("End the fight on the duel map first.")
        keep = self._arena()
        made = {}
        try:
            with b.lock:
                for uid, pick in self.picks.items():
                    made[uid] = self._make(b, uid, pick)
                self._place(b, list(made.values()))
                b.start(auto_roll=True)
            b._history_reset()                         # (undo goes back to the start of the fight, not before it)
        except Exception as e:                         # a fighter that couldn't be made: nothing half done stays
            b.chars.clear()
            self.battle = self._new_battle(keep)
            raise ServiceError(f"The duel couldn't start: {e}")
        self.fighters, self.running = made, True
        return f"The duel begins: {', '.join(p['player'] for p in self.picks.values())}"

    def stop(self) -> None:
        """End the duel: back to the lobby (the arena and who joined stay)."""
        keep = self._arena()
        self.drop()
        self.battle = self._new_battle(keep)

    # ------------------------------------------------------------------ making the fight
    def _name(self, b: BattleService, base: str) -> str:
        """A fighter's name: no real character's (its sheet would shadow theirs), no other combatant's, no other duel's."""
        base = re.sub(r"[\\/:*?\"<>|]", "-", base).strip() or "Fighter"
        taken = {c["name"] for c in b.b["combatants"]}
        name, n = base, 2
        while name in taken or in_memory(name) or os.path.exists(Character._path(name)):
            name, n = f"{base} {n}", n + 1
        return name

    def _make(self, b: BattleService, user_id: int, pick: dict) -> int:
        who = pick["player"]
        if pick["kind"] == "hero":
            char = F.hero(pick["class"], pick["level"], pick.get("spells") or [])
            char.name = self._name(b, f"{who} ({pick['class']})")
            b.chars.add(char, user_id)
            return b.add_player(char.name, place=False)
        if pick["kind"] == "copy":                     # their character as it is now, under a name of its own: whatever the
            char = Character.load(pick["character"])   # duel does to the copy, the real sheet is never written
            if char is None or char.transient:
                raise ServiceError(f"{pick['character']} isn't there any more.")
            char.name = self._name(b, f"{who} ({pick['character']})")
            b.chars.add(char, user_id)
            return b.add_player(char.name, place=False)
        mid = pick.get("monster") or F.random_monster(pick["cr"], self.svc.rng)
        return b.add_enemy(mid, 1, name=self._name(b, f"{who} ({bestiary.get(mid)['name']})"), place=False)[0]

    @staticmethod
    def _place(b: BattleService, ids: List[int]) -> None:
        """Each fighter on a side of their own (faction 1, 2, 3, 4, then neutral: hostile to all), spread around the
        arena's middle - two face each other from west and east."""
        m = b.b["map"]
        fw = FL.layout(m)[0]
        x0 = FL.left(m, 0)
        cx, cy = x0 + (fw - 1) / 2, (m["h"] - 1) / 2
        rx, ry = max(1.0, min(5.0, fw / 2 - 2)), max(1.0, min(4.0, m["h"] / 2 - 2))     # (about 50 ft apart)
        n = len(ids)
        for i, cid in enumerate(ids):
            c = b._find(cid)
            c["faction"] = FACTIONS[min(i, len(FACTIONS) - 1)]
            a = math.pi + 2 * math.pi * i / max(1, n)
            spot = b._free_near(c, int(round(cx + rx * math.cos(a))), int(round(cy + ry * math.sin(a))))
            if spot:
                c["pos"] = spot

    # ------------------------------------------------------------------ reading
    def fighter_of(self, user_id: int) -> Optional[int]:
        return self.fighters.get(user_id)

    def mine(self, user_id: int) -> set:
        """The combatants a player plays: their fighter and what it summoned."""
        cid = self.fighters.get(user_id)
        b = self.battle
        if cid is None:
            return set()
        with b.lock:
            by = {c["id"]: c for c in b.b["combatants"]}
            out = {cid}
            for c in by.values():
                x, seen = c, set()
                while x.get("summoned_by") is not None and not x.get("turned") and x["id"] not in seen:
                    seen.add(x["id"])
                    x = by.get(x["summoned_by"]) or {"id": None}
                    if x["id"] == cid:
                        out.add(c["id"])
                        break
            return out

    def host_name(self) -> Optional[str]:
        """The host's name (None: the DM's lobby)."""
        if self.host is None:
            return None
        p = self.picks.get(self.host)
        return p["player"] if p else self.svc.players.name_of(self.host) or f"Player {self.host}"

    def summary(self) -> dict:
        """A line of the lobby list: {id, name, host, host_name, n, running, status}."""
        return {"id": self.id, "name": self.name, "host": self.host, "host_name": self.host_name(), "n": len(self.picks),
                "running": self.running, "status": self.battle.b["status"]}

    def view(self) -> dict:
        """The lobby and its fight: the summary with {round, winner, shown, rows: [{uid, player, pick, cid, name, hp,
        max_hp, out}]}."""
        v = self.battle.view()
        by = {c["id"]: c for c in v["combatants"]}
        rows = []
        for uid, p in self.picks.items():
            c = by.get(self.fighters.get(uid))
            out = c is None or bool(c.get("downed") if c["kind"] == "pc" else c["hp"] <= 0)
            rows.append({"uid": uid, "player": p["player"], "pick": dict(p), "cid": c["id"] if c else None,
                         "name": c["name"] if c else None, "hp": c["hp"] if c else None,
                         "max_hp": c["max_hp"] if c else None, "out": self.running and out})
        standing = [r for r in rows if r["cid"] is not None and not r["out"]]
        winner = standing[0]["name"] if self.running and len(self.fighters) >= 2 and len(standing) == 1 else None
        return dict(self.summary(), status=v["status"], round=v["round"], winner=winner, rows=rows,
                    shown=self.svc.shown == self.id)


class DuelService:
    def __init__(self, emit, players, campaign: BattleService, rng=random):
        self._emit = emit                              # bus.emit
        self.players = players
        self.campaign = campaign                       # the campaign's battle: its rules, and its map can become an arena
        self.rng = rng
        self.lock = threading.RLock()
        self.open = False                              # players see the Duel tab
        self.rooms: Dict[int, Room] = {}               # the lobbies, in the order they were opened
        self.watching: Dict[int, int] = {}             # player id -> the lobby they look at
        self.shown: Optional[int] = None               # the lobby the editor's battle windows show
        self._next = 1

    # ------------------------------------------------------------------ which battle a thread works on
    def bound(self) -> Optional[BattleService]:
        """A duel's battle when this thread works on it (scope(), or the editor showing it), else None."""
        b = _BOUND.get()
        if b is not None:
            return b
        if self.shown is not None and threading.current_thread() is _MAIN:
            room = self.rooms.get(self.shown)
            return room.battle if room is not None else None
        return None

    @contextmanager
    def scope(self, room: Room):
        """rt().battle is this duel's on this thread meanwhile."""
        token = _BOUND.set(room.battle)
        try:
            yield room.battle
        finally:
            _BOUND.reset(token)

    @property
    def on_screen(self) -> bool:
        return self.shown is not None and self.shown in self.rooms

    def shown_room(self) -> Optional[Room]:
        return self.rooms.get(self.shown) if self.shown is not None else None

    def _changed(self, room: Optional[Room] = None):
        self._emit(events.DUEL)
        if self.shown is not None and (room is None or room.id == self.shown):
            self._emit(events.BATTLE)                  # the editor's battle windows show it

    # ------------------------------------------------------------------ lobbies
    def room(self, rid) -> Room:
        room = self.rooms.get(int(rid)) if str(rid).lstrip("-").isdigit() else None
        if room is None:
            raise ServiceError("That duel lobby is gone.")
        return room

    def rooms_list(self) -> List[dict]:
        with self.lock:
            return [r.summary() for r in self.rooms.values()]

    def room_of(self, user_id: int) -> Optional[Room]:
        """The lobby a player joined."""
        return next((r for r in self.rooms.values() if user_id in r.picks), None)

    def watched(self, user_id: int) -> Optional[Room]:
        """The lobby a player looks at: the one they picked, else the one they joined, else one fighting, else the first."""
        rooms = self.rooms
        room = rooms.get(self.watching.get(user_id, -1)) or self.room_of(user_id)
        return room or next((r for r in rooms.values() if r.running), None) or next(iter(rooms.values()), None)

    def watch(self, user_id: int, rid) -> None:
        with self.lock:
            self.watching[int(user_id)] = self.room(rid).id
        self._emit(events.DUEL)

    def create(self, user_id: Optional[int] = None, name: str = "") -> Room:
        """Open a lobby hosted by this player (None: the DM's)."""
        with self.lock:
            if not self.open:
                raise ServiceError("There is no duel open.")
            if len(self.rooms) >= MAX_ROOMS:
                raise ServiceError(f"There are {MAX_ROOMS} duel lobbies already: join one of them.")
            if user_id is not None:
                self._moving(user_id, None)
            rid, self._next = self._next, self._next + 1
            who = self.players.name_of(user_id) or f"Player {user_id}" if user_id is not None else None
            name = re.sub(r"\s+", " ", str(name or "")).strip()[:40] or (f"{who}'s duel" if who else f"Duel {rid}")
            room = self.rooms[rid] = Room(self, rid, name, user_id)
            if user_id is not None:
                self.watching[user_id] = rid
        self._emit(events.DUEL)
        return room

    def close(self, rid, by: Optional[int] = None) -> None:
        """Close a lobby (its host or the DM): its fight, if any, is thrown away."""
        with self.lock:
            room = self.room(rid)
            self._may(room, by)
            self._close(room)
        self._emit(events.DUEL)
        self._emit(events.BATTLE)

    def _close(self, room: Room):
        room.drop()
        self.rooms.pop(room.id, None)
        if self.shown == room.id:
            self.shown = None

    @staticmethod
    def _may(room: Room, by: Optional[int]):
        if by is not None and by != room.host:
            raise ServiceError("Only the lobby's host or the DM can do that.")

    # ------------------------------------------------------------------ the DM
    def set_open(self, on: bool) -> None:
        """Open duel mode (players see the Duel tab), or close it: every lobby and fight is gone."""
        with self.lock:
            if bool(on) == self.open:
                return
            if not on:
                for room in list(self.rooms.values()):
                    self._close(room)
                self.watching, self.shown = {}, None
            self.open = bool(on)
        self._emit(events.DUEL)
        self._emit(events.BATTLE)                      # (the editor may have been showing one)

    def show(self, on: bool, rid=None) -> None:
        """The editor's battle windows show a duel (this lobby's; none named: the one shown last, else one fighting,
        else the first) - or the campaign's battle again."""
        with self.lock:
            room = None
            if on:
                room = self.rooms.get(int(rid)) if rid is not None else (
                    self.shown_room() or next((r for r in self.rooms.values() if r.running), None) or next(iter(self.rooms.values()), None))
            shown = room.id if room is not None else None
            if shown == self.shown:
                return
            self.shown = shown
        self._emit(events.BATTLE)
        self._emit(events.DUEL)

    def use_campaign_map(self, rid) -> None:
        with self.lock:
            self.room(rid).use_campaign_map()
        self._changed(self.room(rid))

    def new_arena(self, rid) -> None:
        with self.lock:
            self.room(rid).new_arena()
        self._changed(self.room(rid))

    def start(self, rid, by: Optional[int] = None) -> str:
        """Begin a lobby's duel (its host, or the DM: by None). Its fighters look at it from now on."""
        with self.lock:
            room = self.room(rid)
            self._may(room, by)
            for uid in room.picks:                     # (not fighting anywhere else: one fight at a time)
                other = next((r for r in self.rooms.values() if r is not room and uid in r.fighters), None)
                if other is not None:
                    raise ServiceError(f"{room.picks[uid]['player']} is fighting in {other.name}.")
            try:
                text = room.start()
            except ServiceError:
                self._changed(room)                    # (its arena made anew)
                raise
            for uid in room.fighters:
                self.watching[uid] = room.id
        self._changed(room)
        return text

    def stop(self, rid, by: Optional[int] = None) -> None:
        """End a lobby's duel (its host or the DM): back to its lobby (the arena and who joined stay)."""
        with self.lock:
            room = self.room(rid)
            self._may(room, by)
            room.stop()
        self._changed(room)

    def kick(self, rid, user_id: int, by: Optional[int] = None) -> None:
        """Take a player out of a lobby (its host or the DM)."""
        with self.lock:
            room = self.room(rid)
            self._may(room, by)
            if room.running and user_id in room.fighters:
                raise ServiceError("They are fighting now: end the duel first (or take their token off the map).")
            self._leave(room, int(user_id))
        self._emit(events.DUEL)

    # ------------------------------------------------------------------ the players
    def join(self, user_id: int, rid, pick: dict) -> None:
        """Join a lobby (or change what you fight as; joining another lobby leaves the one you were in):
        {"kind": "hero", "class", "level", "spells": [...]}, {"kind": "monster", "cr"} or {"kind": "copy",
        "character"} - one of their own characters, copied."""
        p = self._pick(pick)
        if p["kind"] == "copy" and (p["character"] not in self.players.characters_of(user_id) or in_memory(p["character"])
                                    or Character.load(p["character"]) is None):
            raise ServiceError("That isn't one of your characters.")
        with self.lock:
            if not self.open:
                raise ServiceError("There is no duel open.")
            room = self.room(rid)
            if room.running:
                raise ServiceError("This duel has started - wait for the next one.")
            if user_id not in room.picks and len(room.picks) >= MAX_FIGHTERS:
                raise ServiceError(f"The duel is full ({MAX_FIGHTERS} fighters).")
            self._moving(user_id, room)
            p["player"] = self.players.name_of(user_id) or f"Player {user_id}"
            room.picks[int(user_id)] = p
            self.watching[int(user_id)] = room.id
        self._emit(events.DUEL)

    def leave(self, user_id: int) -> None:
        """Leave the lobby you joined."""
        with self.lock:
            room = self.room_of(user_id)
            if room is None:
                return
            if room.running and user_id in room.fighters:
                raise ServiceError("The duel has started: ask its host or the DM to end it.")
            self._leave(room, user_id)
        self._emit(events.DUEL)

    def _moving(self, user_id: int, to: Optional[Room]):
        """A player goes elsewhere (another lobby, or one of their own): out of the one they were in, and a lobby they
        host goes to the next one in it (or closes, empty)."""
        here = self.room_of(user_id)
        if here is not None and here is not to:
            if here.running and user_id in here.fighters:
                raise ServiceError("You are fighting in a duel: finish it first.")
            self._leave(here, user_id)
        for room in [r for r in self.rooms.values() if r is not to and r.host == user_id]:
            self._leave(room, user_id)

    def _leave(self, room: Room, user_id: int):
        """Out of the lobby; a host who leaves hands it to the next one in it, and a players' lobby left empty closes."""
        room.picks.pop(user_id, None)
        if room.host == user_id:
            room.host = next(iter(room.picks), None)
            if room.host is None and not room.running:
                self._close(room)

    @staticmethod
    def _pick(pick) -> dict:
        pick = pick if isinstance(pick, dict) else {}
        if pick.get("kind") == "hero":
            cls = str(pick.get("class") or "")
            if cls not in F.classes():
                raise ServiceError("Pick a class.")
            level = int(pick["level"]) if str(pick.get("level") or "").isdigit() else 0
            if level not in F.LEVELS:
                raise ServiceError(f"Pick a level from 1 to {F.LEVELS[-1]}.")
            spells = [str(s)[:80] for s in pick.get("spells") or [] if isinstance(s, str)][:60]
            return {"kind": "hero", "class": cls, "level": level, "spells": spells}
        if pick.get("kind") == "monster":                # one picked from the list, or a random one of a CR
            mid = str(pick.get("monster") or "")
            if mid:
                m = F.usable(mid)
                if m is None:
                    raise ServiceError("Pick a monster from the list.")
                return {"kind": "monster", "cr": m["cr"], "monster": m["id"], "name": m["name"]}
            cr = str(pick.get("cr") or "")
            if cr not in F.crs():
                raise ServiceError("Pick a challenge rating.")
            return {"kind": "monster", "cr": cr}
        if pick.get("kind") == "copy":
            name = str(pick.get("character") or "")
            if not name:
                raise ServiceError("Pick one of your characters.")
            return {"kind": "copy", "character": name}
        raise ServiceError("Pick a hero or a monster.")

    # ------------------------------------------------------------------ reading
    def view(self) -> dict:
        """Duel mode for the editor: {open, shown, rooms: [Room.view()]}."""
        with self.lock:
            return {"open": self.open, "shown": self.shown if self.on_screen else None,
                    "rooms": [r.view() for r in self.rooms.values()]}
