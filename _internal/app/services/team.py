"""The team inventory: one shared pack for the characters playing this session - a place to pass items through, and
the group's supplies: the food in it is the food the World map's travel column counts (a day's meals are eaten from
here, rations first).

    team.items()                                # [{'name', 'qty', 'note', 'food'}]
    team.add("Rope", 2)                         # the DM puts loot in (a library item or any name)
    team.add("Odd idol", 1, "Hums at night", by="Arin")   # a custom entry with its description (here a player's)
    team.edit("Rope", qty=3, note="Knotted")    # its amount, description or name
    team.put("Arin", "Rope", 1)                 # out of a character's pack into the team's
    team.take("Rope", 1, "Bela", by="Arin")     # out of the team's into a character's pack (Arin hands it to Bela)
    team.remove("Rope", 1)                      # gone
    team.drop("Rope", 1, x, y, by="Arin")       # onto a tile of the battle map
    team.hand("Rope", 1, cid, by="Arin")        # into the hands of a creature on the battle map
    team.meals() / team.stock(5) / team.eat(2)  # the food in it: the travel column's meals

Who shares it (members): the session party (the characters the DM ticked for this session); with no one ticked, every
character a player owns. It lives in data/team_inventory.json; every change emits events.TEAM.
"""
import threading
from typing import List, Optional

from ..core import events
from ..core.storage import read_json, write_json
from ..rules.character import charges_taken, merge_charges, resize_charges, take_charges
from ..rules.data import rules
from .common import Hooks, ServiceError, positive_int

TEAM_FILE = "data/team_inventory.json"
MAX_STACKS = 200
NAME_MAX = 120
NOTE_MAX = 500
RATIONS = "Rations (1 day)"
DRINKS = ("ale", "wine", "mead", "tej", "beer", "water", "spirits", "rum")


def is_food(name: str) -> bool:
    """A ration, or a food (not a drink) from the item list."""
    low = (name or "").lower()
    if "ration" in low:
        return True
    data = rules.item(name)
    kind = str((data or {}).get("type") or "").split("|")[0]
    return kind == "FD" and not any(w in low for w in DRINKS)


def food_order(name: str):
    """Rations are eaten (and handed out) first."""
    return 0 if "ration" in name.lower() else 1, name.lower()


def clean_note(note) -> str:
    return str(note or "").strip()[:NOTE_MAX]


def item_name(name) -> str:
    """A name as it is kept: the item list's spelling when it is one of its items."""
    name = str(name or "").strip()[:NAME_MAX]
    if not name:
        raise ServiceError("Item name cannot be empty.")
    data = rules.item(name)
    return data["name"] if data else name


class TeamInventory:
    def __init__(self, hooks: Hooks, characters, players, battle):
        self.h, self.chars, self.players, self.battle = hooks, characters, players, battle
        self.lock = threading.RLock()
        data = read_json(TEAM_FILE, [])
        self._items: List[dict] = [{"name": str(e["name"]), "qty": max(1, int(e.get("qty") or 1)), "note": clean_note(e.get("note"))}
                                   for e in data if isinstance(e, dict) and e.get("name")] if isinstance(data, list) else []

    # ------------------------------------------------------------------ reading
    def items(self) -> List[dict]:
        """Each stack, with `food`: whether the group eats it on the road."""
        with self.lock:
            return [dict(e, food=is_food(e["name"])) for e in self._items]

    def food(self) -> List[dict]:
        """The food stacks, in the order they are eaten."""
        with self.lock:
            return sorted((dict(e) for e in self._items if is_food(e["name"])), key=lambda e: food_order(e["name"]))

    def meals(self) -> int:
        return sum(e["qty"] for e in self.food())

    def members(self) -> List[str]:
        """The characters sharing the pack: the session party, or (none ticked) every character a player owns."""
        names = set(self.chars.names())
        party = [n for n in self.players.session_party() if n in names]
        if party:
            return party
        owned = [c for p in self.players.all().values() for c in p["characters"] if c in names]
        return sorted(dict.fromkeys(owned), key=str.lower)

    def _find(self, name: str) -> Optional[dict]:
        key = (name or "").strip().lower()
        return next((e for e in self._items if e["name"].lower() == key), None)

    def _get(self, name: str) -> dict:
        e = self._find(name)
        if not e:
            raise ServiceError(f"The team inventory doesn't have '{name}'.")
        return e

    # ------------------------------------------------------------------ changing
    def _save(self, line: Optional[str] = None, discord: bool = True):
        write_json(TEAM_FILE, self._items)
        if line:
            self.h.log(line)
            if discord:
                self.h.discord_log("📦 " + line, "xp")
        self.h.notify(events.TEAM)

    def _in(self, name: str, qty: int, note: str = "", charges: Optional[int] = None):
        """`charges`: what the items bring (a spent wand: rules.character.charges_taken); None: full."""
        e = self._find(name)
        if e:
            e["qty"] += qty
            merge_charges(e, e["qty"] - qty, qty, charges)
            e["note"] = e["note"] or note
            return
        if len(self._items) >= MAX_STACKS:
            raise ServiceError("The team inventory is full; take some items out first.")
        self._items.append(dict({"name": name, "qty": qty, "note": note}, **({"charges_left": int(charges)} if charges is not None else {})))

    def _out(self, name: str, qty: int) -> str:
        return self._out_with(name, qty)[0]

    def _out_with(self, name: str, qty: int) -> tuple:
        """(its name, the charges the items taken carry: None when full)."""
        e = self._find(name)
        if not e or e["qty"] < qty:
            raise ServiceError(f"The team inventory doesn't have {qty}× '{name}'. (Has: {e['qty'] if e else 0})")
        charges = take_charges(e, qty)
        e["qty"] -= qty
        if e["qty"] <= 0:
            self._items.remove(e)
        return e["name"], charges

    @staticmethod
    def _what(name: str, qty: int) -> str:
        return f"{qty}× {name}" if qty > 1 else name

    def add(self, name: str, qty=1, note: str = "", by: Optional[str] = None):
        """New items into the pack (the DM's loot, or anything a player writes in). `note`: its description (a stack
        already there keeps its own unless it has none)."""
        qty = positive_int(qty, "Amount")
        name = item_name(name)
        with self.lock:
            self._in(name, qty, clean_note(note))
            self._save(f"{by or 'The DM'} puts {self._what(name, qty)} in the team inventory")

    def set_qty(self, name: str, qty):
        with self.lock:
            e = self._get(name)
            old = e["qty"]
            e["qty"] = positive_int(qty, "Amount")
            resize_charges(e, old)
            self._save()

    def edit(self, name: str, qty=None, note: Optional[str] = None, new_name: Optional[str] = None, by: Optional[str] = None):
        """Change a stack's amount, description or name (renamed to one already in the pack: the two become one)."""
        with self.lock:
            e = self._get(name)
            old = dict(e)
            if qty is not None:
                e["qty"] = positive_int(qty, "Amount")
                resize_charges(e, old["qty"])
            if note is not None:
                e["note"] = clean_note(note)
            if new_name is not None and new_name.strip() and new_name.strip() != e["name"]:
                new_name = item_name(new_name)
                other = self._find(new_name)
                if other is not None and other is not e:
                    other["qty"] += e["qty"]
                    merge_charges(other, other["qty"] - e["qty"], e["qty"], e.get("charges_left"))
                    other["note"] = other["note"] or e["note"]
                    self._items.remove(e)
                    e = other
                else:
                    e["name"] = new_name
            if e == old:
                return
            what = [f"{old['qty']} → {e['qty']}" if e["qty"] != old["qty"] else "",
                    f"now {e['name']}" if e["name"] != old["name"] else "",
                    "new description" if e["note"] != old["note"] else ""]
            self._save(f"{by or 'The DM'} changes {old['name']} in the team inventory ({', '.join(w for w in what if w)})",
                       discord=False)

    def remove(self, name: str, qty=None, by: Optional[str] = None):
        """Take items out of the pack for good (all of them without `qty`): used up, sold, lost."""
        with self.lock:
            e = self._get(name)
            n = e["qty"] if qty is None else positive_int(qty, "Amount")
            name = self._out(e["name"], n)
            line = f"{by} takes {self._what(name, n)} out of the team inventory" if by else \
                f"{self._what(name, n)} taken out of the team inventory"
            self._save(line, discord=False)

    def put(self, character: str, name: str, qty=1):
        """From a character's pack into the team's (its description goes along)."""
        qty = positive_int(qty, "Amount")
        with self.lock:
            char = self.chars.get(character)
            entry = char.find_item(name)
            if not entry:
                raise ServiceError(f"{char.name} doesn't have '{name}'.")
            if entry["qty"] < qty:
                raise ServiceError(f"{char.name} has only {entry['qty']}× '{entry['name']}'.")
            line = f"{char.name} puts {self._what(entry['name'], qty)} in the team inventory"
            self._in(entry["name"], qty, clean_note(entry.get("note")), charges_taken(entry, qty))    # a spent wand stays spent
            try:
                self.chars.remove_item(char.name, entry["name"], qty, note=line)
            except ServiceError:
                self._out(entry["name"], qty)
                raise
            self._save()

    def take(self, name: str, qty, character: str, by: Optional[str] = None):
        """From the team's pack into a character's (`by`: who passed it on, when it isn't that character)."""
        qty = positive_int(qty, "Amount")
        with self.lock:
            char = self.chars.get(character)
            note = (self._find(name) or {}).get("note") or ""
            name, charges = self._out_with(name, qty)
            line = (f"{by} gives {self._what(name, qty)} from the team inventory to {char.name}" if by and by != char.name
                    else f"{char.name} takes {self._what(name, qty)} from the team inventory")
            try:
                self.chars.add_item(char.name, name, qty, note=line, desc=note or None, charges=charges)
            except ServiceError:
                self._in(name, qty, note, charges)
                raise
            self._save()

    def drop(self, name: str, qty, x, y, by: Optional[str] = None, free: bool = False) -> dict:
        """Onto the battle map: it lies on that tile (`free`: on that very point)."""
        qty = positive_int(qty, "Amount")
        with self.lock:
            name, charges = self._out_with(name, qty)
            try:
                g = self.battle.drop_item(name, qty, x, y, free=free, by=f"{by} (team inventory)" if by else "Team inventory", charges=charges)
            except ServiceError:
                self._in(name, qty, charges=charges)
                raise
            self._save()
            return g

    def hand(self, name: str, qty, cid: int, by: Optional[str] = None) -> str:
        """Into the hands of a creature on the battle map (a player character: into its pack)."""
        qty = positive_int(qty, "Amount")
        with self.lock:
            name, charges = self._out_with(name, qty)
            try:
                line = self.battle.give_new(name, qty, cid, charges=charges)
            except ServiceError:
                self._in(name, qty, charges=charges)
                raise
            self._save(f"{by or 'The DM'} hands {self._what(name, qty)} from the team inventory on the battle map", discord=False)
            return line

    # ------------------------------------------------------------------ the group's food (the World map says why)
    def stock(self, n, name: str = RATIONS, note: str = ""):
        """Food in, quietly (the travel log says what for)."""
        n = positive_int(n, "Meals")
        with self.lock:
            self._in(item_name(name), n, clean_note(note))
            self._save()

    def eat(self, n: int) -> List[dict]:
        """Up to `n` meals out of the pack, rations first, quietly: [{'name', 'qty', 'note'}] of what went."""
        with self.lock:
            went = []
            for e in self.food():
                if n <= 0:
                    break
                k = min(n, e["qty"])
                self._out(e["name"], k)
                went.append({"name": e["name"], "qty": k, "note": e["note"]})
                n -= k
            if went:
                self._save()
            return went
