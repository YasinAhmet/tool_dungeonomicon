"""Items lying on the battle map, things creatures carry, and throwing.

    b.drop_item("Dagger", 1, 4, 2, character="Arin")   # out of Arin's pack onto a tile (no one: loot from nowhere)
    b.move_ground(gid, x, y, qty=None)     b.give_ground(gid, cid, qty=None)     b.erase_ground(gid)
    b.hand_item("Arin", "Dagger", 1, cid)  # from a pack straight to a creature
    b.pick_up(cid, gid)                    # a creature within 5 ft takes it (a free object interaction in a fight)
    b.set_throwable(did, True, "1d6")      # a prop (or map symbol) creatures may throw, and the damage it deals
    b.throw(cid, what, target_id)          # what: 'inv:<item>', 'carried:<item>', 'ground:<gid>', 'prop:<did>'

Ground items are stacks {'id', 'name', 'qty', 'x', 'y'} in b['ground']: the same item dropped where it already lies
joins that stack. Like the drawings they belong to the map: a new battle keeps them, saved encounters keep them. A
creature that isn't a player character carries what it is given in its 'items' ([{'name', 'qty'}]).

Throwing (PHB chapters 5 and 9): a weapon with the thrown property is a ranged weapon attack with its own range and
damage. Any other weapon is an improvised weapon (20/60 ft, Strength, no proficiency) dealing 1d4, and anything else -
a potion, a chair, a table - deals 1d4 bludgeoning (a prop: the damage the DM set). What was thrown lands at the
target's feet on a hit and a tile or two off on a miss.

Flasks (PHB chapter 5: Alchemist's Fire, Acid, Holy Water, Oil) take an action, fly 20 ft at most, are an improvised
ranged attack and shatter: no damage modifier, their own damage and type, Alchemist's Fire keeps burning (1d4 fire at
the start of each of the target's turns until it puts the flames out: an action and a DC 10 Dexterity check), Holy
Water only hurts fiends and undead, Oil makes the next fire damage within a minute 5 higher.
"""
import math
import re
from typing import List, Optional

from ...rules import combat_feats as CF
from ...rules.character import charges_taken, merge_charges, resize_charges, take_charges
from ...rules.data import rules
from ..common import ServiceError, positive_int
from . import features as F
from . import geometry as G
from .battlemap import tile_name
from .floors import floor_at
from .itemsprites import POINT_FIRST, sprite_for
from .props import PROPS, span, terrain

MAX_GROUND = 400
IMPROVISED = (20, 60)                                       # feet: normal / long range of something not made to be thrown
REACH = 5                                                   # feet: how far a creature reaches to pick up or grab
DICE = re.compile(r"\d*d\d+([+-]\d+)?|\d+")
FLASKS = {"alchemist's fire (flask)": {"dice": "1d4", "type": "fire", "burn": True},
          "acid (vial)": {"dice": "2d6", "type": "acid"},
          "holy water (flask)": {"dice": "2d6", "type": "radiant", "only": ("fiend", "undead")},
          "oil (flask)": {"oil": True}}


def default_throw_damage(sym: str) -> str:
    """The damage of a thrown prop by its heft: small things 1d4, cover-sized ones 1d6, heavy ones more."""
    r = terrain(sym) or {}
    if r.get("cover") == "total" or span(sym) > 1:
        return "2d6"
    if r.get("blocks"):
        return "1d8"
    return "1d6" if r.get("cover") else "1d4"


def _item_name(name: str) -> str:
    data = rules.item(name)
    return data["name"] if data else name.strip()


class GroundMixin:
    # ------------------------------------------------------------------ the ground
    def _ground(self) -> list:
        return self.b.setdefault("ground", [])

    def _ground_item(self, gid: int) -> dict:
        g = next((x for x in self._ground() if x["id"] == int(gid)), None)
        if g is None:
            raise ServiceError("That item isn't on the ground any more.")
        return g

    def _on_map(self, x: int, y: int) -> bool:
        m = self.b["map"]
        return floor_at(m, float(x)) is not None and 0 <= math.floor(float(y)) < m["h"]

    def _lay(self, name: str, qty: int, x, y, free: bool = False, charges: Optional[int] = None) -> dict:
        """Put `qty` of an item on a tile, joining the stack of the same item already lying there. `free`: (x, y) is the
        point where exactly it lies (`at`, tile units) - anywhere, a tile's corner too; it joins a stack lying right there.
        `charges`: what the items bring (a spent wand dropped: rules.character.charges_taken); None: full."""
        fx, fy = float(x), float(y)
        if free:
            m = self.b["map"]
            fx, fy = max(0.0, min(m["w"] - 0.01, fx)), max(0.0, min(m["h"] - 0.01, fy))
        at = [round(fx, 3), round(fy, 3)] if free else None
        x, y = math.floor(fx), math.floor(fy)
        if not self._on_map(x, y):
            raise ServiceError("Put it on a tile of the map.")
        for g in self._ground():
            near = (not at and not g.get("at")) or (at and g.get("at") and math.hypot(at[0] - g["at"][0], at[1] - g["at"][1]) < 0.3)
            if g["x"] == x and g["y"] == y and g["name"].lower() == name.lower() and near:
                g["qty"] += qty
                merge_charges(g, g["qty"] - qty, qty, charges)
                return g
        if len(self._ground()) >= MAX_GROUND:
            raise ServiceError("There are too many items on the ground; pick some up first.")
        g = {"id": self.b.get("ground_next", 1), "name": name, "qty": qty, "x": x, "y": y, "at": at}
        if charges is not None:
            g["charges_left"] = int(charges)
        self.b["ground_next"] = g["id"] + 1
        self._ground().append(g)
        return g

    def _lift(self, g: dict, qty: Optional[int]) -> int:
        """Take `qty` (None: all) off a stack; returns how many were taken."""
        return self._lift_c(g, qty)[0]

    def _lift_c(self, g: dict, qty: Optional[int]) -> tuple:
        """`_lift`: (how many were taken, the charges they carry - None when full)."""
        n = g["qty"] if qty is None else max(1, min(g["qty"], int(qty)))
        charges = take_charges(g, n)
        g["qty"] -= n
        if g["qty"] <= 0:
            self.b["ground"] = [x for x in self._ground() if x is not g]
        return n, charges

    def ground_items(self) -> List[dict]:
        with self.lock:
            return [dict(g) for g in self._ground()]

    def ground_at(self, x: int, y: int) -> List[dict]:
        """The stacks lying on a tile, the last dropped first."""
        with self.lock:
            return [dict(g) for g in reversed(self._ground()) if g["x"] == int(x) and g["y"] == int(y)]

    def _near(self, c: dict, x: int, y: int) -> bool:
        return not c.get("pos") or G.distance_to_tile(c["pos"], c.get("span") or 1, (int(x), int(y))) <= REACH

    # ------------------------------------------------------------------ carried by creatures without a sheet
    def _carry(self, c: dict, name: str, qty: int, charges: Optional[int] = None):
        items = c.setdefault("items", [])
        e = next((i for i in items if i["name"].lower() == name.lower()), None)
        if e:
            e["qty"] += qty
            merge_charges(e, e["qty"] - qty, qty, charges)
        else:
            items.append(dict({"name": name, "qty": qty}, **({"charges_left": int(charges)} if charges is not None else {})))

    def _uncarry(self, c: dict, name: str, qty: int) -> str:
        return self._uncarry_c(c, name, qty)[0]

    def _uncarry_c(self, c: dict, name: str, qty: int) -> tuple:
        """`_uncarry`: (its name, the charges the items taken carry - None when full)."""
        e = next((i for i in c.get("items") or [] if i["name"].lower() == name.lower()), None)
        if not e or e["qty"] < qty:
            raise ServiceError(f"{c['name']} doesn't carry {qty}× {name}.")
        charges = take_charges(e, qty)
        e["qty"] -= qty
        if e["qty"] <= 0:
            c["items"].remove(e)
        return e["name"], charges

    def _give(self, c: dict, name: str, qty: int, charges: Optional[int] = None):
        """Into a creature's hands: a player character's pack, or what a creature carries (`charges`: what they bring; None: full)."""
        char = self._sheet(c)
        if char:
            self.chars.add_item(char.name, name, qty, charges=charges)
        else:
            self._carry(c, name, qty, charges)

    # ------------------------------------------------------------------ the DM's (and the players') moves
    def drop_item(self, name: str, qty, x, y, character: Optional[str] = None, cid: Optional[int] = None, free: bool = False,
                  by: Optional[str] = None, charges: Optional[int] = None) -> dict:
        """Items onto a tile: out of a character's pack (`character`), out of what a creature carries (`cid`), or new
        loot from nowhere (`by`: who the log names, e.g. the team inventory); `free`: onto the point (x, y) itself.
        Returns the stack it went to."""
        qty = positive_int(qty, "Amount")
        with self.lock:
            if not self._on_map(x, y):
                raise ServiceError("Put it on a tile of the map.")
            who = by
            if character:
                char = self.chars.get(character)
                entry = char.find_item(name)
                if not entry:
                    raise ServiceError(f"{char.name} doesn't have '{name}'.")
                name = entry["name"]
                charges = charges_taken(entry, qty)                 # a spent wand lies there spent
                self.chars.remove_item(char.name, name, qty)
                who = char.name
            elif cid:
                c = self._find(cid)
                name, charges = self._uncarry_c(c, name, qty)
                who = c["name"]
            else:
                name = _item_name(name)
                if not name:
                    raise ServiceError("Item name cannot be empty.")
            g = self._lay(name, qty, x, y, free, charges)
            what = f"{qty}× {name}" if qty > 1 else name
            self._commit(f"{who} drops {what} at {tile_name(g['x'], g['y'])}" if who else f"{what} on the ground at {tile_name(g['x'], g['y'])}")
            return dict(g)

    def move_ground(self, gid: int, x, y, qty: Optional[int] = None, free: bool = False):
        """Move a stack (or `qty` of it) to another tile; it joins the same item lying there. `free`: to the point (x, y)."""
        with self.lock:
            g = self._ground_item(gid)
            if not self._on_map(x, y):
                raise ServiceError("Put it on a tile of the map.")
            if qty is None and free and not any(o is not g and o["name"].lower() == g["name"].lower() and o.get("at")
                                                and math.hypot(o["at"][0] - float(x), o["at"][1] - float(y)) < 0.3 for o in self._ground()):
                g.update(x=math.floor(float(x)), y=math.floor(float(y)), at=[round(float(x), 3), round(float(y), 3)])   # the same stack, elsewhere
                self._commit(label=f"Move {g['name']}")
                return
            if (g["x"], g["y"]) == (int(x), int(y)) and qty is None and not free:
                return
            n, charges = self._lift_c(g, qty)
            self._lay(g["name"], n, x, y, free, charges)
            self._commit(label=f"Move {g['name']}")

    def give_ground(self, gid: int, cid: int, qty: Optional[int] = None) -> str:
        """Hand a stack lying on the ground to a creature (the DM's drag onto a token)."""
        with self.lock:
            g = self._ground_item(gid)
            c = self._find(cid)
            n, charges = self._lift_c(g, qty)
            self._give(c, g["name"], n, charges)
            line = f"{c['name']} gets {n}× {g['name']}" if n > 1 else f"{c['name']} gets {g['name']}"
            self._commit(line)
            return line

    def hand_item(self, character: str, name: str, qty, cid: int) -> str:
        """From a character's pack straight into a creature's hands (an item dragged from a sheet onto a token)."""
        qty = positive_int(qty, "Amount")
        with self.lock:
            c = self._find(cid)
            if c.get("character") == character:
                raise ServiceError(f"{character} already has it.")
            char = self.chars.get(character)
            entry = char.find_item(name)
            if not entry:
                raise ServiceError(f"{char.name} doesn't have '{name}'.")
            other = self._sheet(c)
            if other:
                self.chars.send_item(char.name, other.name, entry["name"], qty)
            else:
                charges = charges_taken(entry, qty)
                self.chars.remove_item(char.name, entry["name"], qty)
                self._carry(c, entry["name"], qty, charges)
            line = f"{char.name} gives {qty}× {entry['name']} to {c['name']}" if qty > 1 else f"{char.name} gives {entry['name']} to {c['name']}"
            self._commit(line)
            return line

    def give_new(self, name: str, qty, cid: int, charges: Optional[int] = None) -> str:
        """A new item (from the library) into a creature's hands (`charges`: from the team inventory, a spent wand's)."""
        qty = positive_int(qty, "Amount")
        with self.lock:
            c = self._find(cid)
            name = _item_name(name)
            self._give(c, name, qty, charges)
            line = f"{c['name']} gets {qty}× {name}" if qty > 1 else f"{c['name']} gets {name}"
            self._commit(line)
            return line

    def drop_carried(self, cid: int) -> int:
        """Everything a creature carries falls at its feet. Returns how many stacks fell."""
        with self.lock:
            c = self._find(cid)
            items = c.get("items") or []
            if not items:
                return 0
            if not c.get("pos"):
                raise ServiceError(f"{c['name']} isn't on the map.")
            for e in items:
                self._lay(e["name"], e["qty"], *c["pos"], charges=e.get("charges_left"))
            n, c["items"] = len(items), []
            self._commit(f"{c['name']} drops what it carries")
            return n

    def set_ground_qty(self, gid: int, qty: int):
        with self.lock:
            g = self._ground_item(gid)
            old = g["qty"]
            g["qty"] = positive_int(qty, "Amount")
            resize_charges(g, old)
            self._commit(label=f"{g['name']}: amount")

    def erase_ground(self, gid: int):
        with self.lock:
            g = self._ground_item(gid)
            self.b["ground"] = [x for x in self._ground() if x is not g]
            self._commit(label=f"{g['name']} taken off the map")

    def pick_up(self, cid: int, gid: int, qty: Optional[int] = None) -> str:
        """A creature picks up a stack within 5 ft of it: a free object interaction in a fight."""
        with self.lock:
            self._busy()
            c = self._find(cid)
            g = self._ground_item(gid)
            if not self._near(c, g["x"], g["y"]):
                raise ServiceError(f"{g['name']} is out of reach.")
            self._pay(c, "object", f"pick up {g['name']}")
            n, charges = self._lift_c(g, qty)
            self._give(c, g["name"], n, charges)
            line = f"{c['name']} picks up {n}× {g['name']}" if n > 1 else f"{c['name']} picks up {g['name']}"
            self._commit(line)
            return line

    def pickup_options(self, c: dict) -> List[dict]:
        if not c.get("pos"):
            return []
        return [{"value": str(g["id"]), "label": f"{g['name']} ×{g['qty']}" if g["qty"] > 1 else g["name"]}
                for g in self._ground() if self._near(c, g["x"], g["y"])]

    # ------------------------------------------------------------------ throwable props
    def set_throwable(self, did: int, on: bool, damage: Optional[str] = None):
        """Let creatures throw this prop (or map symbol), and what it deals on a hit (bludgeoning)."""
        with self.lock:
            d = self._drawing(did)
            if d["type"] != "symbol":
                raise ServiceError("Only props and map symbols can be thrown.")
            d["throw"] = bool(on)
            if damage is not None:
                dmg = str(damage).replace(" ", "").lower()
                if dmg and not DICE.fullmatch(dmg):
                    raise ServiceError("Damage is dice like 1d6 or 2d4+1.")
                d["throw_dmg"] = dmg or None
            self._commit(label="Throwable prop" if on else "Prop no longer throwable")

    @staticmethod
    def _prop_label(d: dict) -> str:
        from .drawing import SYMBOLS
        p = PROPS.get(d.get("sym"))
        return p[0] if p else SYMBOLS.get(d.get("sym"), ("", d.get("sym") or "Prop"))[1]

    # ------------------------------------------------------------------ throwing
    def throw_options(self, c: dict) -> List[dict]:
        """What this creature could throw now: its pack (or what it carries), and the ground items and throwable props
        within its reach. [{'value', 'label'}], thrown weapons first. Nothing in beast shape."""
        if c.get("form") or not self._can_throw(c):
            return []
        out = []
        char = self._sheet(c)
        held = [(f"inv:{e['name']}", e["name"]) for e in char.inventory] if char else \
            [(f"carried:{e['name']}", e["name"]) for e in c.get("items") or []]
        for value, name in sorted(held, key=lambda v: (not self._is_thrown_weapon(v[1]), v[1].lower())):
            out.append({"value": value, "label": f"{name} · {self._throw_note(name, None)}"})
        if c.get("pos"):
            for g in self._ground():
                if self._near(c, g["x"], g["y"]):
                    out.append({"value": f"ground:{g['id']}", "label": f"{g['name']} (on the ground) · {self._throw_note(g['name'], None)}"})
            for d in self.b.get("drawings") or []:
                if d["type"] == "symbol" and d.get("throw") and self._near_prop(c, d):
                    out.append({"value": f"prop:{d['id']}", "label": f"{self._prop_label(d)} · {self._throw_note(None, d)}"})
        return out

    def _near_prop(self, c: dict, d: dict) -> bool:
        n = span(d.get("sym", "")) if d.get("sym") in PROPS else 1
        return any(self._near(c, d["x"] + i, d["y"] + j) for i in range(n) for j in range(n))

    def _can_throw(self, c: dict) -> bool:
        """Hands to throw with: not a beast, dragon, ooze or plant - unless its stat block throws something (an ape's rock)."""
        if self._sheet(c):
            return True
        m = self._monster(c) or {}
        if str(m.get("type") or "").lower() not in ("beast", "dragon", "ooze", "plant"):
            return True
        return any(re.search(r"(?<!saving )\bthrows?\b|\bRock\b", f"{e.get('name', '')} {e.get('text', '')}") for e in m.get("actions") or [])

    @staticmethod
    def _is_thrown_weapon(name: str) -> bool:
        data = rules.item(name or "")
        return bool(data and data.get("weapon") and "thrown" in (data.get("properties") or []))

    def _throw_note(self, name: Optional[str], d: Optional[dict]) -> str:
        if d is not None:
            return f"{d.get('throw_dmg') or default_throw_damage(d.get('sym', ''))} bludgeoning"
        fl = FLASKS.get(_item_name(name or "").lower())
        if fl:
            return ("20 ft, coats in oil" if fl.get("oil") else f"20 ft, {fl['dice']} {fl['type']}" + (" a turn" if fl.get("burn") else "")
                    + (f" ({' and '.join(fl['only'])} only)" if fl.get("only") else "")) + ", an action"
        data = rules.item(name or "")
        if data and data.get("weapon"):
            dmg = f"{data.get('dmg1') or '1'} {data.get('dmg_type') or ''}".strip()
            return f"thrown, {dmg}" if self._is_thrown_weapon(name) else "improvised, 1d4 bludgeoning"
        return "improvised, 1d4 bludgeoning"

    def _throw_atk(self, c: dict, name: Optional[str], d: Optional[dict]) -> dict:
        """The attack profile of throwing this thing: thrown weapon, improvised weapon (half damage) or object."""
        char = self._sheet(c)
        brawler = bool(char and CF.has(char, "tavern_brawler"))
        data = rules.item(name or "") if d is None else None
        props: list = []
        magic = 0
        fl = FLASKS.get(_item_name(name or "").lower()) if d is None else None
        if fl:                                               # a flask: its own damage, no modifier
            return {"bonus": self._ability(c, "dex") + (self._prof(c) if brawler else 0), "n": 1, "melee": False, "weapon": False,
                    "magical": False, "parts": [[fl["dice"], fl["type"]]] if fl.get("dice") else [], "finesse": False, "str_based": False,
                    "reach": 5, "normal": 20, "long": 20, "thrown": True, "light": False, "props": [], "factor": 1.0, "flask": fl}
        if data and data.get("weapon"):
            props = list(data.get("properties") or [])
            magic = int(data.get("bonus_weapon") or 0)
            if "thrown" in props:
                ability = "dex" if "finesse" in props and self._ability(c, "dex") >= self._ability(c, "str") else "str"
                nums = [int(n) for n in str(data.get("range") or "").replace("/", " ").split() if n.isdigit()]
                normal, long_ = (nums[0], nums[-1]) if nums else IMPROVISED
                proficient = char.weapon_proficient(data) if char else True
                dice, dtype = data.get("dmg1") or "1", data.get("dmg_type") or "bludgeoning"
            else:                                            # a melee weapon without the thrown property: 1d4 (PHB ch. 9)
                ability, (normal, long_), proficient = "str", IMPROVISED, brawler
                dice, dtype, magic = "1d4", "bludgeoning", 0
            factor = 1.0
        else:
            ability, (normal, long_), proficient, factor = "str", IMPROVISED, brawler, 1.0
            dice = (d.get("throw_dmg") or default_throw_damage(d.get("sym", ""))) if d is not None else "1d4"
            dtype = "bludgeoning"
        mod = self._ability(c, ability) + magic
        return {"bonus": mod + (self._prof(c) if proficient else 0), "n": 1, "melee": False, "weapon": bool(data and data.get("weapon")),
                "magical": bool(magic or (data or {}).get("magic")), "parts": [[f"{dice}{mod:+d}" if mod else dice, dtype]],
                "finesse": "finesse" in props, "str_based": ability == "str", "reach": 5, "normal": normal, "long": long_,
                "thrown": True, "light": False, "props": props, "factor": factor}

    def throw(self, cid: int, what: str, target_id: Optional[int] = None, adv: Optional[str] = None) -> str:
        """Throw something (see throw_options) at a creature: one attack of the Attack action."""
        with self.lock:
            self._busy()
            att, tgt = self._find(cid), self._target(target_id)
            if tgt is att:
                raise ServiceError("Throw it at someone else.")
            if att.get("form"):
                raise ServiceError(f"{att['name']} can't throw things in {att['form']['name'].lower()} form.")
            kind, _, arg = str(what or "").partition(":")
            if not arg:
                raise ServiceError("Pick what to throw.")
            d = None
            if kind == "inv":
                char = self._sheet(att)
                entry = char.find_item(arg) if char else None
                if not entry:
                    raise ServiceError(f"{att['name']} doesn't have '{arg}'.")
                name = entry["name"]
            elif kind == "carried":
                name = next((e["name"] for e in att.get("items") or [] if e["name"].lower() == arg.lower()), None)
                if not name:
                    raise ServiceError(f"{att['name']} doesn't carry '{arg}'.")
            elif kind == "ground":
                g = self._ground_item(int(arg))
                if not self._near(att, g["x"], g["y"]):
                    raise ServiceError(f"{g['name']} is out of reach.")
                name = g["name"]
            elif kind == "prop":
                d = self._drawing(int(arg))
                if d["type"] != "symbol" or not d.get("throw"):
                    raise ServiceError("That can't be thrown.")
                if not self._near_prop(att, d):
                    raise ServiceError(f"The {self._prop_label(d).lower()} is out of reach.")
                name = self._prop_label(d)
            else:
                raise ServiceError("Pick what to throw.")
            atk = self._check_reach(att, tgt, self._throw_atk(att, name if d is None else None, d))
            atk["adv"] = adv
            char = self._sheet(att)
            fl = atk.get("flask")
            if fl:
                kinds = {str((self._monster(tgt) or {}).get("type") or "").lower()}
                if fl.get("only") and not kinds & set(fl["only"]):
                    atk["parts"] = []                        # Holy Water on a living creature: wet, nothing more
                self._pay(att, "action", f"throw {name}")
            else:
                self._pay_attack(att, F.extra_attacks(char) if char else self._multiattack_count(att), f"throw {name}")
            charges = None
            if kind == "inv":                                # in the air: out of the hand it was in
                charges = charges_taken(char.find_item(name) or {}, 1)
                self.chars.remove_item(char.name, name, 1)
            elif kind == "carried":
                _n, charges = self._uncarry_c(att, name, 1)
            elif kind == "ground":
                _n, charges = self._lift_c(g, 1)
            R = self._strike(att, f"Throw {name}" if d is None else f"Throw the {name.lower()}", [tgt["id"]], mode="attack",
                             atk=atk, magical=atk["magical"])
            R["thrown"] = {"name": name, "prop": d["id"] if d else None, "from": list(att.get("pos") or []), "flask": fl, "charges": charges}
            R["thrown_look"] = self._thrown_look(R["thrown"])          # the attack's fx draws it in flight
            out = self._run_r(R)
            self._commit()
            return out

    def _thrown_look(self, th: dict) -> dict:
        """How the screens draw a thing in flight (the attack's fx 'item'): its sprite (itemsprites.py) or the prop's
        picture; 'point': it flies point first (a javelin, a dart: how far its tip points up in the picture, degrees),
        else (False) it turns over and over; 'shatter': a flask."""
        if th.get("prop"):
            d = next((x for x in self.b.get("drawings") or [] if x["id"] == th["prop"]), None)
            return {"prop": (d or {}).get("sym") or "", "point": False}
        key = sprite_for(th["name"])
        return {"sprite": key, "point": POINT_FIRST.get(key, False), "shatter": bool(th.get("flask"))}

    def _land_fx(self, R: dict, tgt: Optional[dict], hit: bool, to, gid=None, did=None, span_: int = 1):
        """The thrown thing drops from where it reached (the target, or past it on a miss) to where it lies: the screens
        keep the stack (or prop) hidden until it gets there."""
        th_look = R.get("thrown_look")
        if not th_look or not tgt or not tgt.get("pos"):
            return
        s = tgt.get("span") or 1
        cx, cy = tgt["pos"][0] + s / 2, tgt["pos"][1] + s / 2
        at = [cx, cy] if hit else [cx + .55, cy - .45]
        self._vfx("land", item=th_look, at=at, to=[to[0] + span_ / 2, to[1] + span_ / 2], gid=gid, did=did)

    def _land_thrown(self, R: dict):
        """A thrown thing comes down: at the target's feet on a hit, a tile or two away on a miss."""
        th = R.pop("thrown", None)
        if not th:
            return
        tid = (R.get("targets") or [None])[0]
        tgt = self._find_or_none(tid)
        hit = bool(R.get("hits", {}).get(str(tid)))
        fl = th.get("flask")
        if fl:                                               # a flask shatters where it lands
            att = self._find_or_none(R.get("actor"))
            who, src = (att["name"], att["id"]) if att else ("", None)
            if hit and tgt is not None and fl.get("burn") and self._hp_of(tgt) > 0:
                for e in [e for e in tgt.get("effects") or [] if e["name"] == "Burning (Alchemist's Fire)"]:
                    tgt["effects"].remove(e)                 # the same fire twice doesn't burn twice (same-named effects)
                self._effect_on(tgt, "Burning (Alchemist's Fire)", [], None, None, None, None, who,
                                {"dot": {"dice": fl["dice"], "type": fl["type"], "when": "start"}, "douse": 10}, None, src)
                self._line(R, f"{tgt['name']} is on fire (an action and a DC 10 Dexterity check put it out)")
            elif hit and tgt is not None and fl.get("oil"):
                self._effect_on(tgt, "Covered in oil", [], None, None, None, 10, who, {"oil": 5}, None, src)
                self._line(R, f"{tgt['name']} is covered in oil: the next fire damage is 5 higher")
            elif not hit:
                self._line(R, f"The {th['name'].split(' (')[0].lower()} shatters on the ground")
            return
        base = list(tgt["pos"]) if tgt and tgt.get("pos") else th.get("from")
        if not base:
            base = [0, 0]
        s = (tgt.get("span") or 1) if tgt and tgt.get("pos") else 1
        if hit:
            spots = [(base[0] + i, base[1] + j) for i in range(s) for j in range(s)]
        else:
            r = self.rng.choice((1, 1, 2))
            off = lambda k: max(-k, 0, k - s + 1)          # noqa: E731 - tiles between k and the footprint
            spots = [(base[0] + i, base[1] + j) for i in range(-r, s + r) for j in range(-r, s + r) if max(off(i), off(j)) == r]
        spots = [p for p in spots if self._on_map(*p)] or [tuple(base)]
        if th.get("prop"):
            d = next((x for x in self.b.get("drawings") or [] if x["id"] == th["prop"]), None)
            if d is None:
                return
            n = span(d.get("sym", "")) if d.get("sym") in PROPS else 1
            taken = {(x, y) for o in self.b["combatants"] if o.get("pos") for x, y in self._footprint(o, *o["pos"])}
            m = self.b["map"]

            def fits(p):
                cells = {(p[0] + i, p[1] + j) for i in range(n) for j in range(n)}
                return all(floor_at(m, cx) is not None and 0 <= cy < m["h"] for cx, cy in cells) and not cells & taken
            free = [p for p in spots if fits(p)]
            if not free:                                     # under the target: the nearest free ground around it
                ring = sorted(((base[0] + i, base[1] + j) for i in range(-3, s + 3) for j in range(-3, s + 3)),
                              key=lambda p: abs(p[0] - base[0]) + abs(p[1] - base[1]))
                free = [p for p in ring if fits(p)][:1]
            if free:
                p = free[0] if hit else self.rng.choice(free)
                d["x"], d["y"] = int(p[0]), int(p[1])
                self._land_fx(R, tgt, hit, p, did=d["id"], span_=n)
                self._line(R, f"The {th['name'].lower()} lands at {tile_name(*p)}")
            return
        p = spots[0] if hit and len(spots) == 1 else self.rng.choice(spots)
        g = self._lay(th["name"], 1, *p, charges=th.get("charges"))
        self._land_fx(R, tgt, hit, p, gid=g["id"])
        self._line(R, f"{th['name']} lands at {tile_name(*p)}")

