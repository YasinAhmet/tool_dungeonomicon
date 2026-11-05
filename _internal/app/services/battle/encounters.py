"""Saved encounters: a prepared setup (the creatures, where they stand, the map with its drawings, pictures and props,
the light and the battle rules) kept in encounters/<name>.json next to battle.json, to be loaded into a fresh battle."""
import copy
import os
import time
from typing import List

from ...core.storage import list_json_names, read_json, write_json
from ..common import ServiceError, valid_name
from .constants import ACTIVE, blank_battle, faction_of
from .props import upgrade as upgrade_props

DROP = ("turn", "readied", "spent", "lr_used", "form", "took_types", "spell_actions", "extra_turns", "react_used",
        "temp_hp", "exhaustion", "subd")             # the fight so far: not part of a prepared setup


class EncountersMixin:
    def _encounter_dir(self) -> str:
        return os.path.join(os.path.dirname(self.path) or ".", "encounters")

    def _encounter_path(self, name: str) -> str:
        return os.path.join(self._encounter_dir(), valid_name(name, "Encounter name") + ".json")

    def save_encounter(self, name: str) -> str:
        """Keep the current setup as an encounter: every creature that isn't a player character or a summon (full
        hit points, initiative cleared, place on the map, faction, notes), the map with its drawings, pictures,
        props and the items on the ground, the light, the battle rules and the battle's name. Overwrites one of the same name. Returns the name."""
        with self.lock:
            path = self._encounter_path(name)
            rows = []
            for c in self.b["combatants"]:
                if c["kind"] == "pc" or c.get("summoned_by"):
                    continue
                c = copy.deepcopy(c)
                for k in DROP:
                    c.pop(k, None)
                c.update(id=None, init=None, hp=c["max_hp"], effects=[], concentrating=None, summon_conc=None)
                rows.append(c)
            data = {"name": os.path.splitext(os.path.basename(path))[0], "battle": self.b["name"], "saved": time.time(),
                    "combatants": rows, "map": copy.deepcopy(self.b["map"]), "drawings": copy.deepcopy(self.b.get("drawings") or []),
                    "draw_next": self.b.get("draw_next", 1), "ground": copy.deepcopy(self.b.get("ground") or []),
                    "rules": copy.deepcopy(self.b.get("rules") or {}),
                    "reveal_hp": bool(self.b.get("reveal_hp"))}
            write_json(path, data)
            self.h.log(f"[BATTLE] Saved the encounter {data['name']}")
            return data["name"]

    def encounters(self) -> List[dict]:
        """Saved encounters: [{name, enemies, xp, saved}] ('enemies' counts the creatures that aren't allies, 'xp'
        their experience points, 'saved' the epoch time it was saved), by name."""
        out = []
        for n in list_json_names(self._encounter_dir()):
            data = read_json(os.path.join(self._encounter_dir(), n + ".json"), None)
            if not isinstance(data, dict):
                continue
            foes = [c for c in data.get("combatants") or [] if c.get("kind") == "enemy" and faction_of(c) != 1]
            out.append({"name": n, "enemies": len(foes), "xp": sum(int(c.get("xp") or 0) for c in foes),
                        "saved": data.get("saved")})
        return sorted(out, key=lambda e: e["name"].lower())

    def load_encounter(self, name: str, keep_party: bool = True) -> str:
        """Start a fresh battle (in setup) with a saved encounter, keeping the player characters already in the battle
        (where they stood, if that tile is still free; else on the west side) when `keep_party`. One undo step."""
        with self.lock:
            if self.b["status"] == ACTIVE:
                raise ServiceError("A battle is in progress. End it first.")
            path = self._encounter_path(name)
            data = read_json(path, None)
            if not isinstance(data, dict):
                raise ServiceError(f"There is no saved encounter called {name.strip()}.")
            party = [c for c in self.b["combatants"] if c["kind"] == "pc"] if keep_party else []
            colors = self.b.get("faction_colors")
            self.b = blank_battle(data.get("battle") or self.b["name"])
            if colors:
                self.b["faction_colors"] = colors
            if isinstance(data.get("map"), dict):
                self.b["map"] = copy.deepcopy(data["map"])
            self.b["drawings"] = upgrade_props(copy.deepcopy(data.get("drawings") or []))
            self.b["draw_next"] = max([int(data.get("draw_next") or 1)] + [d.get("id", 0) + 1 for d in self.b["drawings"]])
            self.b["ground"] = copy.deepcopy(data.get("ground") or [])
            self.b["ground_next"] = max([1] + [g.get("id", 0) + 1 for g in self.b["ground"]])
            if data.get("rules"):
                self.b["rules"] = copy.deepcopy(data["rules"])
            self.b["reveal_hp"] = bool(data.get("reveal_hp"))
            for c in data.get("combatants") or []:
                c = {**self._new("enemy", "?", 1, 1, 10, 0), **c, "id": None, "init": None}
                if c.get("pos") and not self._tile_ok(c, *c["pos"]):
                    c["pos"] = None
                self._add(c)
            stray = []
            for p in party:
                c = self._add(dict(p, init=None, id=None, effects=[], concentrating=None, turn=None))
                if c.get("pos") and not self._tile_ok(c, *c["pos"]):
                    c["pos"] = None
                    stray.append(c)
            self._auto_place(stray)
            label = data.get("name") or os.path.splitext(os.path.basename(path))[0]
            self._commit(f"Loaded the encounter {label}")
            return label

    def delete_encounter(self, name: str):
        """Throw a saved encounter away."""
        path = self._encounter_path(name)
        if not os.path.isfile(path):
            raise ServiceError(f"There is no saved encounter called {name.strip()}.")
        try:
            os.remove(path)
        except OSError as e:
            raise ServiceError(f"Couldn't delete the encounter: {e}")
        self.h.log(f"[BATTLE] Deleted the encounter {name.strip()}")
