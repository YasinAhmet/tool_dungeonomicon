"""The battle's event dispatcher: things that happen (a creature drops to 0, a turn starts, a spell is cast...) are raised
here, and whoever cares reacts. Built-in handlers are `_on_<event>` methods; other parts of the app can add their own
with on_event(name, fn) - fn(battle, **ctx) is called after the built-in one.

Events: zero_hp (creature, by), turn_start (creature), turn_end (creature), cast (caster, spell), moved (creature).
"""
from typing import Callable, Dict, List


class DispatchMixin:
    def on_event(self, name: str, fn: Callable):
        self.__dict__.setdefault("_event_hooks", {}).setdefault(name, []).append(fn)

    def _raise(self, name: str, **ctx):
        own = getattr(self, f"_on_{name}", None)
        if own:
            own(**ctx)
        hooks: Dict[str, List[Callable]] = self.__dict__.get("_event_hooks", {})
        for fn in hooks.get(name, []):
            try:
                fn(self, **ctx)
            except Exception as e:  # noqa: BLE001 - an add-on must not break the battle
                self.h.log(f"[BATTLE] event hook for {name} failed: {e}")

    def _on_zero_hp(self, creature: dict, by=None):
        """A creature drops: its summons go if they were bound to it, those it dominated are free, its zones that
        need it end."""
        cid = creature["id"]
        for o in self.b["combatants"]:
            for e in list(o.get("effects") or []):
                if e.get("source_id") == cid and (e.get("mods") or {}).get("dominated"):
                    self._effect_off(o, e, f"{creature['name']} is down")
        for z in [z for z in self.b.get("zones") or [] if z.get("owner") == cid and z.get("follow")]:
            self._zone_off(z, f"{creature['name']} is down")
        if creature["kind"] != "pc":
            self._death_burst(creature)
        if creature.get("summoned_by") is not None and creature in self.b["combatants"]:
            self.b.setdefault("vanish", []).append(cid)          # a summoned creature at 0 HP vanishes once the action is told

    def _flush_vanished(self):
        for cid in self.b.pop("vanish", None) or []:
            c = self._find_or_none(cid)
            if c is not None:
                self._vfx_unsummon(c)
                self._take_out(c)
                self._say(f"{c['name']} disappears")
