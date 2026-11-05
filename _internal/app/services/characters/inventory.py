"""Items, equipping, attunement, coins, trading and buying."""
from typing import Dict, Optional

from ...rules import engine as E
from ...rules.character import Character, charges_taken, merge_charges, resize_charges
from ...rules.data import rules
from ..common import ServiceError, positive_int, whole_int
from ..team import NAME_MAX, NOTE_MAX


class InventoryMixin:
    # ---- inventory & money ----
    def add_item(self, name: str, item: str, amount=1, note: Optional[str] = None, desc: Optional[str] = None,
                 charges: Optional[int] = None) -> Character:
        """`note`: the log line instead of the plain one (e.g. "Arin takes it from the team inventory"). `desc`: the
        item's description (kept in its entry's "note"; one already there stays). `charges`: what the items bring
        (a spent wand from the team inventory or the ground: rules.character.charges_taken); None: full."""
        item = (item or "").strip()[:NAME_MAX]
        if not item:
            raise ServiceError("Item name cannot be empty.")
        amount = positive_int(amount, "Amount")
        with self.lock:
            char = self.get(name)
            data = rules.item(item)
            canonical = data["name"] if data else item
            existing = char.find_item(canonical)
            entry = char.add_item(existing["name"] if existing else canonical, amount, charges=charges)
            if desc and not entry.get("note"):
                entry["note"] = str(desc).strip()[:NOTE_MAX]
            self._commit(char, note or f"Added {amount}× '{entry['name']}' to {char.name}",
                         f"📦 {note}" if note else f"Added {amount}× `{entry['name']}` to **{char.name}**")
        return char

    def remove_item(self, name: str, item: str, amount=1, note: Optional[str] = None) -> Character:
        amount = positive_int(amount, "Amount")
        with self.lock:
            char = self.get(name)
            entry = char.find_item(item)
            if not entry or entry["qty"] < amount:
                raise ServiceError(f"Not enough '{item}'. (Have: {entry['qty'] if entry else 0})")
            char.remove_item(entry["name"], amount)
            self._commit(char, note or f"Removed {amount}× '{entry['name']}' from {char.name}",
                         f"📦 {note}" if note else f"Removed {amount}× `{entry['name']}` from **{char.name}**")
        return char

    def edit_item(self, name: str, item: str, qty=None, desc: Optional[str] = None, new_name: Optional[str] = None) -> Character:
        """An item's amount, description or name (renamed to one the character already has: the two become one)."""
        with self.lock:
            char = self.get(name)
            entry = char.find_item(item)
            if not entry:
                raise ServiceError(f"{char.name} doesn't have '{item}'.")
            old = dict(entry)
            if qty is not None:
                entry["qty"] = positive_int(qty, "Amount")
                resize_charges(entry, old["qty"])                 # more wands come with their charges; fewer keep what they hold
            if desc is not None:
                entry["note"] = str(desc).strip()[:NOTE_MAX]
            new_name = (new_name or "").strip()[:NAME_MAX]
            if new_name and new_name != entry["name"]:
                data = rules.item(new_name)
                new_name = data["name"] if data else new_name
                other = char.find_item(new_name)
                if other is not None and other is not entry:
                    other["qty"] += entry["qty"]
                    merge_charges(other, other["qty"] - entry["qty"], entry["qty"], entry.get("charges_left"))
                    other["note"] = other.get("note") or entry.get("note") or ""
                    char.inventory.remove(entry)
                else:
                    entry["name"] = new_name
            if entry == old:
                return char
            self._commit(char, f"{char.name} changes {old['name']}" + (f" (now {new_name})" if new_name and new_name != old["name"] else ""))
        return char

    def remove_all_of(self, name: str, item: str) -> int:
        with self.lock:
            char = self.get(name)
            entry = char.find_item(item)
            count = entry["qty"] if entry else 0
            if count:
                self.remove_item(name, item, count)
        return count

    def set_equipped(self, name: str, item: str, equipped: bool) -> Character:
        """Wear/wield an item. Only one suit of armor and one shield can be worn at a time."""
        with self.lock:
            char = self.get(name)
            entry = char.find_item(item)
            if not entry:
                raise ServiceError(f"{char.name} doesn't have '{item}'.")
            data = rules.item(entry["name"])
            if equipped and data:
                if data["type"] in ("LA", "MA", "HA"):
                    for e in char.inventory:
                        d = rules.item(e["name"])
                        if e is not entry and d and d["type"] in ("LA", "MA", "HA") and e["equipped"]:
                            e["equipped"] = False
                elif data["type"] == "S":
                    for e in char.inventory:
                        d = rules.item(e["name"])
                        if e is not entry and d and d["type"] == "S" and e["equipped"]:
                            e["equipped"] = False
            entry["equipped"] = equipped
            if not equipped:
                entry["attuned"] = False
            self._commit(char, f"{char.name} {'equipped' if equipped else 'unequipped'} {entry['name']}")
        return char

    def set_attuned(self, name: str, item: str, attuned: bool) -> Character:
        """PHB/DMG: attune to at most three magic items at a time."""
        with self.lock:
            char = self.get(name)
            entry = char.find_item(item)
            data = rules.item(entry["name"]) if entry else None
            if not entry:
                raise ServiceError(f"{char.name} doesn't have '{item}'.")
            if attuned:
                if not data or data.get("attune") is None:
                    raise ServiceError(f"{entry['name']} doesn't require attunement.")
                if not entry["attuned"] and char.attuned_count >= 3:
                    raise ServiceError("You can be attuned to at most three magic items.")
                if data["attune"]:
                    self.h.log(f"Attunement requirement for {entry['name']}: {data['attune']}")
            entry["attuned"] = attuned
            if attuned:
                entry["equipped"] = True
            self._commit(char, f"{char.name} {'attuned to' if attuned else 'ended attunement with'} {entry['name']}")
        return char

    def set_currency(self, name: str, coins: Dict[str, object]) -> Character:
        with self.lock:
            char = self.get(name)
            char.d["currency"] = {c: whole_int(coins.get(c, 0), f"{c.upper()}", 0, 10 ** 9) for c in E.COINS}
            self._commit(char, f"{char.name} money set to {char.wealth_gp:g} gp equivalent")
        return char

    def adjust_currency(self, name: str, **delta: int) -> Character:
        with self.lock:
            char = self.get(name)
            new = dict(char.currency)
            for coin, n in delta.items():
                if coin not in E.COINS:
                    raise ServiceError(f"Unknown coin '{coin}'.")
                new[coin] = new.get(coin, 0) + n
                if new[coin] < 0:
                    raise ServiceError(f"Not enough {coin}.")
            char.d["currency"] = new
            self._commit(char, f"{char.name} money changed {delta}")
        return char

    def send_item(self, from_name: str, to_name: str, item: str, amount) -> None:
        amount = positive_int(amount, "Amount")
        with self.lock:
            sender = self.get(from_name)
            entry = sender.find_item(item)
            have = entry["qty"] if entry else 0
            if have < amount:
                raise ServiceError(f"You don't have {amount}× '{item}'. (Have: {have})")
            target = self.get(to_name)
            charges = charges_taken(entry, amount)                     # a spent wand stays spent in the new hands
            sender.remove_item(entry["name"], amount)
            got = target.add_item(entry["name"], amount, charges=charges)
            got["note"] = got.get("note") or entry.get("note") or ""            # its description goes along
            target.save()
            self._commit(sender, f"Sent {amount}× '{entry['name']}' from {sender.name} to {target.name}",
                         f"📦 Sent {amount}× `{entry['name']}` from **{sender.name}** to **{target.name}**")

    def buy_item(self, name: str, item: str, amount, cost_gp) -> str:
        """Buy `amount` of `item` for a total of `cost_gp` gold (may be fractional). Returns the purse summary."""
        amount = positive_int(amount, "Amount")
        try:
            cost_cp = round(float(cost_gp) * 100)
        except (TypeError, ValueError):
            raise ServiceError("Gold cost must be a number.")
        if cost_cp < 0:
            raise ServiceError("Gold cost can't be negative.")
        with self.lock:
            char = self.get(name)
            try:
                char.d["currency"] = E.pay_coins(char.currency, cost_cp)
            except ValueError:
                raise ServiceError(f"{char.name} has only {char.wealth_gp:g} gp, need {cost_cp / 100:g}.")
            data = rules.item(item)
            char.add_item(data["name"] if data else item, amount)
            purse = ", ".join(f"{n} {c}" for c, n in char.currency.items() if n) or "no coins"
            self._commit(char, f"Bought {amount}× '{item}' for {char.name} costing {cost_cp / 100:g} gp",
                         f"🛒 **{char.name}** bought {amount}× `{item}` for {cost_cp / 100:g} gp (left: {purse})")
        return purse
