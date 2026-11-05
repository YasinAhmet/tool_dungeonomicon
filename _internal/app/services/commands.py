import re
from datetime import datetime
from typing import Callable, Dict, List, Optional

from ..rules import engine as E
from ..rules import sheet
from ..rules.character import Character
from ..rules.dice import DiceError
from .common import ServiceError, positive_int

NO_CHARACTER_HINT = "No character selected or owned. Use `/listchars` to see available characters."

HELP_TEXT = (
    "📚 **Available Commands**\n\n"
    "**🎲 Rolls**\n"
    "`/roll <expr>` – Roll dice (e.g., `/roll 2d6+3`)\n"
    "`/check <skill|ability>` – Ability or skill check (add `adv` or `dis`)\n"
    "`/save <ability>` – Saving throw\n"
    "`/initiative` – Roll initiative\n"
    "`/attack <weapon>` – Attack with an equipped weapon\n\n"
    "**👤 Your character**\n"
    "`/sheet` – Open your private interactive character sheet (the GUI prints a text sheet)\n"
    "`/hp` – Show hit points · `/damagechar <n>` · `/healchar <n>`\n"
    "`/rest short|long` – Take a rest · `/hitdie` – Spend a hit die on a short rest\n"
    "`/features` – List class, race and feat features\n"
    "`/inventory` · `/additem <item> [amount]` · `/removeitem <item> [amount]`\n"
    "`/equip <item>` · `/unequip <item>` · `/attune <item>`\n"
    "`/senditem <item> <amount> <target>` · `/buyitem <item> <amount> <goldcost> [char]`\n"
    "`/addnote <text>` · `/removenote <id>` · `/notes`\n\n"
    "**✨ Spells**\n"
    "`/spells` – Known/prepared spells · `/slots` – Spell slots\n"
    "`/cast <spell> [slot level]` – Cast a spell (use `ritual` to cast as a ritual)\n\n"
    "**🧙 Roster**\n"
    "`/listchars` – List unassigned characters\n"
    "`/assigncharacter <name>` – Add a free character to your characters\n"
    "`/unassigncharacter [name]` – Release one of your characters\n"
    "`/mychars` – List your characters · `/usecharacter <name>` – Choose the active one\n\n"
    "**⚙️ Admin**\n"
    "`/sync` – Clear and resync Discord slash commands\n\n"
    "Tip: put item names with spaces in quotes: `/additem \"Potion of Healing\" 2`"
)

_TOKEN = re.compile(r'"([^"]*)"|(\S+)')


def split_command(text: str) -> List[str]:
    """Split on spaces, keeping "quoted phrases" together."""
    return [m.group(1) if m.group(1) is not None else m.group(2) for m in _TOKEN.finditer(text)]


class CommandProcessor:
    """Runs text commands coming from the GUI command line (user_id=None) or Discord.

    Discord users only ever act on the character they own (their active one); the GUI acts on the
    character selected in the Characters tab. May be called from any thread.
    """

    def __init__(self, app):
        self.app = app
        self.chars = app.characters
        self._handlers: Dict[str, Callable[[List[str], Optional[int]], str]] = {
            "/roll": self._roll, "/check": self._check, "/save": self._save, "/initiative": self._initiative,
            "/attack": self._attack, "/sheet": self._sheet, "/currentstate": self._sheet, "/hp": self._hp,
            "/damagechar": self._damagechar, "/healchar": self._healchar, "/rest": self._rest,
            "/hitdie": self._hitdie, "/features": self._features, "/inventory": self._inventory,
            "/additem": self._additem, "/removeitem": self._removeitem, "/equip": self._equip,
            "/unequip": self._unequip, "/attune": self._attune, "/senditem": self._senditem,
            "/buyitem": self._buyitem, "/addnote": self._addnote, "/removenote": self._removenote,
            "/notes": self._notes, "/spells": self._spells, "/slots": self._slots, "/cast": self._cast,
            "/listchars": self._listchars, "/assigncharacter": self._assigncharacter,
            "/unassigncharacter": self._unassigncharacter, "/mychars": self._mychars,
            "/usecharacter": self._usecharacter, "/help": lambda args, uid: HELP_TEXT, "/sync": self._sync,
        }

    def commands(self) -> List[str]:
        """Every command name, for completion."""
        return sorted(self._handlers)

    # ---- entry point ----
    def process(self, cmd: str, user_id: int = None, user_name: Optional[str] = None) -> Optional[str]:
        if user_id is not None:
            self.chars.players.ensure(user_id, user_name)  # remember who is talking to the bot
        parts = split_command(cmd)
        if not parts:
            return None
        command, args = parts[0].lower(), parts[1:]
        handler = self._handlers.get(command)
        if handler is None:
            return f"❌ Unknown command: {command}. Type /help for list."
        try:
            return handler(args, user_id)
        except (ServiceError, DiceError) as e:
            return f"❌ {e}"

    # ---- helpers ----
    def _actor(self, user_id: Optional[int]) -> Character:
        """The character a command acts on."""
        char = self.chars.active_for(user_id) if user_id is not None else self.app.selected_char
        if not char:
            raise ServiceError(NO_CHARACTER_HINT if user_id is not None
                               else "No character selected. Please select one in the Character tab.")
        return char

    @staticmethod
    def _need(args: List[str], count: int, usage: str):
        if len(args) < count:
            raise ServiceError(f"Usage: {usage}")

    @staticmethod
    def _who(user_id: Optional[int]) -> str:
        return "GUI" if user_id is None else f"User {user_id}"

    @staticmethod
    def _advantage(args: List[str]):
        """Split a trailing adv/dis flag from the arguments."""
        if args and args[-1].lower() in ("adv", "advantage", "dis", "disadvantage"):
            return args[:-1], "adv" if args[-1].lower().startswith("adv") else "dis"
        return args, None

    # ---- rolls ----
    def _roll(self, args, user_id):
        self._need(args, 1, "/roll <expression>")
        expr = " ".join(args)
        announce_as = None                              # a player's roll goes to the log channel; the GM's console rolls stay private
        if user_id is not None:
            char = self.chars.active_for(user_id)
            announce_as = char.name if char else self.chars.players.name_of(user_id) or self._who(user_id)
        result = self.app.dice.roll(expr, self._who(user_id), announce_as)
        return f"🎲 {expr} => {result.total}"

    def _check(self, args, user_id):
        args, adv = self._advantage(args)
        self._need(args, 1, "/check <skill or ability> [adv|dis]")
        char = self._actor(user_id)
        return self.chars.roll_check(char.name, " ".join(args), adv, self._who(user_id)).text

    def _save(self, args, user_id):
        args, adv = self._advantage(args)
        self._need(args, 1, "/save <ability> [adv|dis]")
        return self.chars.roll_save(self._actor(user_id).name, args[0], adv, self._who(user_id)).text

    def _initiative(self, args, user_id):
        args, adv = self._advantage(args)
        return self.chars.roll_check(self._actor(user_id).name, "initiative", adv, self._who(user_id)).text

    def _attack(self, args, user_id):
        args, adv = self._advantage(args)
        self._need(args, 1, "/attack <weapon> [adv|dis]")
        return self.chars.roll_attack(self._actor(user_id).name, " ".join(args), adv, self._who(user_id)).text

    # ---- character info ----
    def _listchars(self, args, user_id):
        free = self.chars.players.unassigned(self.chars.names())
        if not free:
            return "No free characters available."
        return "📋 Free characters:\n" + "\n".join(f"• {n} — {sheet.title(self.chars.get(n))}" for n in free)

    def _sheet(self, args, user_id):
        return sheet.sheet_text(self._actor(user_id))

    def _hp(self, args, user_id):
        c = self._actor(user_id)
        v = sheet.vitals(c)
        return (f"❤️ {c.name}: {v['hp']}/{v['max_hp']}" + (f" (+{v['temp_hp']} temp)" if v["temp_hp"] else "")
                + f"  {sheet.hp_bar(c)}  Hit dice: {v['hit_dice']}")

    def _features(self, args, user_id):
        c = self._actor(user_id)
        groups = sheet.feature_groups(c)
        return f"📜 **{c.name}'s features**\n" + "\n".join(f"**{src}:** {', '.join(names)}" for src, names in groups.items())

    def _inventory(self, args, user_id):
        c = self._actor(user_id)
        lines = sheet.inventory_lines(c)
        if not lines:
            return f"Inventory is empty. 💰 {sheet.money_text(c)}"
        return (f"🎒 **Inventory** ({c.carried_weight:g}/{c.carrying_capacity} lb, {c.encumbrance})\n"
                + "\n".join(f"• {l}" for l in lines) + f"\n💰 {sheet.money_text(c)}\n*E = equipped, A = attuned*")

    def _notes(self, args, user_id):
        notes = self._actor(user_id).notes
        if not notes:
            return "No notes."
        lines = [f"[{datetime.fromtimestamp(n['timestamp']).strftime('%Y-%m-%d %H:%M')}] #{n['id']}: {n['text']}"
                 for n in notes]
        return "📝 Notes:\n" + "\n".join(lines)

    # ---- hp & rests ----
    def _damagechar(self, args, user_id):
        self._need(args, 1, "/damagechar <amount>")
        taken, char = self.chars.damage(self._actor(user_id).name, args[0])
        return f"⚔️ Took {taken} damage (HP: {char.current_hp}/{char.max_hp})."

    def _healchar(self, args, user_id):
        self._need(args, 1, "/healchar <amount>")
        healed, char = self.chars.heal(self._actor(user_id).name, args[0])
        return f"💚 Healed {healed} (HP: {char.current_hp}/{char.max_hp})."

    def _rest(self, args, user_id):
        self._need(args, 1, "/rest short|long")
        name = self._actor(user_id).name
        kind = args[0].lower()
        if kind == "short":
            self.chars.short_rest(name)
            return "🏕️ Short rest taken: short-rest features and pact slots recharged. Use `/hitdie` to heal."
        if kind == "long":
            self.chars.long_rest(name)
            return "🛌 Long rest taken: HP, spell slots, hit dice and features restored."
        raise ServiceError("Usage: /rest short|long")

    def _hitdie(self, args, user_id):
        roll, healed = self.chars.spend_hit_die(self._actor(user_id).name)
        return f"🎲 Spent a hit die: rolled {roll}, healed {healed}."

    # ---- inventory ----
    def _additem(self, args, user_id):
        self._need(args, 1, '/additem <item> [amount]  (quote names with spaces)')
        char = self._actor(user_id)
        amount = positive_int(args[1], "Amount") if len(args) > 1 else 1
        self.chars.add_item(char.name, args[0], amount)
        return f"✅ Added {amount}× '{args[0]}'."

    def _removeitem(self, args, user_id):
        self._need(args, 1, '/removeitem <item> [amount]  (quote names with spaces)')
        char = self._actor(user_id)
        amount = positive_int(args[1], "Amount") if len(args) > 1 else 1
        self.chars.remove_item(char.name, args[0], amount)
        return f"✅ Removed {amount}× '{args[0]}'."

    def _equip(self, args, user_id):
        self._need(args, 1, "/equip <item>")
        self.chars.set_equipped(self._actor(user_id).name, " ".join(args), True)
        return f"✅ Equipped {' '.join(args)}."

    def _unequip(self, args, user_id):
        self._need(args, 1, "/unequip <item>")
        self.chars.set_equipped(self._actor(user_id).name, " ".join(args), False)
        return f"✅ Unequipped {' '.join(args)}."

    def _attune(self, args, user_id):
        self._need(args, 1, "/attune <item>")
        self.chars.set_attuned(self._actor(user_id).name, " ".join(args), True)
        return f"✅ Attuned to {' '.join(args)}."

    def _senditem(self, args, user_id):
        self._need(args, 3, "/senditem <item> <amount> <target_character>")
        amount = positive_int(args[1], "Amount")
        sender = self._actor(user_id)
        self.chars.send_item(sender.name, args[2], args[0], amount)
        return f"✅ Sent {amount}× '{args[0]}' to {args[2]}."

    def _buyitem(self, args, user_id):
        self._need(args, 3, "/buyitem <item> <amount> <goldcost> [charactername]")
        amount = positive_int(args[1], "Amount")
        buyer = self.chars.get(args[3]) if len(args) >= 4 else self._actor(user_id)
        purse = self.chars.buy_item(buyer.name, args[0], amount, args[2])
        return f"✅ Purchased {amount}× '{args[0]}' for {args[2]} gp.\n   Remaining: {purse}"

    # ---- notes ----
    def _addnote(self, args, user_id):
        self._need(args, 1, "/addnote <note_text>")
        char = self._actor(user_id)
        note_id = self.chars.add_note(char.name, " ".join(args))
        return f"✅ Added note #{note_id} to {char.name}"

    def _removenote(self, args, user_id):
        self._need(args, 1, "/removenote <note_id>")
        char = self._actor(user_id)
        try:
            note_id = int(args[0])
        except ValueError:
            raise ServiceError("Invalid note ID.")
        self.chars.remove_note(char.name, note_id)
        return f"✅ Removed note #{note_id}"

    # ---- spells ----
    def _spells(self, args, user_id):
        c = self._actor(user_id)
        by_level = sheet.spells_by_level(c)
        if not by_level:
            return f"{c.name} has no spells."
        lines = [f"✨ **{c.name}'s spells** (r = ritual, c = concentration)"]
        for level in sorted(by_level):
            lines.append(f"**{'Cantrips' if level == 0 else E.ordinal(level) + ' level'}:** {', '.join(by_level[level])}")
        return "\n".join(lines) + f"\nSlots: {sheet.slots_text(c)}"

    def _slots(self, args, user_id):
        return f"✨ Spell slots: {sheet.slots_text(self._actor(user_id))}"

    def _cast(self, args, user_id):
        ritual = bool(args) and args[-1].lower() == "ritual"
        if ritual:
            args = args[:-1]
        slot = None
        if len(args) > 1 and args[-1].lower() in ("pact", *[str(i) for i in range(1, 10)]):
            slot = "pact" if args[-1].lower() == "pact" else int(args[-1])
            args = args[:-1]
        self._need(args, 1, "/cast <spell> [slot level|pact] [ritual]")
        return self.chars.cast_spell(self._actor(user_id).name, " ".join(args), slot, ritual)["text"]

    # ---- roster (Discord only) ----
    @staticmethod
    def _discord_only(user_id):
        if user_id is None:
            raise ServiceError("This command must be used from Discord (not GUI).")

    def _assigncharacter(self, args, user_id):
        self._discord_only(user_id)
        self._need(args, 1, "/assigncharacter <name>")
        char = self.chars.claim(user_id, " ".join(args), self.chars.players.name_of(user_id))
        return f"✅ Character '{char.name}' added to your characters."

    def _unassigncharacter(self, args, user_id):
        self._discord_only(user_id)
        char = self.chars.release(user_id, " ".join(args) if args else None)
        return f"✅ Character '{char.name}' unassigned (now free)."

    def _mychars(self, args, user_id):
        self._discord_only(user_id)
        names = self.chars.characters_of(user_id)
        if not names:
            return "You have no characters. Ask the GM to create one, then use /assigncharacter."
        active = self.chars.players.active_of(user_id)
        return "👥 Your characters:\n" + "\n".join(
            f"• {n} — {sheet.title(self.chars.get(n))}" + (" ⭐ active" if n == active else "") for n in names)

    def _usecharacter(self, args, user_id):
        self._discord_only(user_id)
        self._need(args, 1, "/usecharacter <name>")
        return f"✅ {self.chars.use(user_id, ' '.join(args)).name} is now your active character."

    # ---- admin ----
    def _sync(self, args, user_id):
        if user_id is not None:
            return "⚠️ This command can only be run from the GUI, not from Discord."
        return self.app.bot_manager.sync_commands_from_gui()
