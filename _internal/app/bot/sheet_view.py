"""The interactive /sheet: a private (ephemeral) message with tabs. Dice are rolled automatically."""
import asyncio
from typing import Callable, List, Optional

import discord
from discord.ui import Button, Select, View

from ..services.battle import combat_rules as CR
from ..services.common import ServiceError
from ..rules import engine as E
from ..rules import sheet
from ..rules import spellcasting as SC
from ..rules.character import Character
from ..rules.data import rules
from . import embeds

TABS = (("overview", "Overview"), ("combat", "Combat"), ("inventory", "Inventory"), ("spells", "Spellbook"),
        ("features", "Features"))
VIEW_TIMEOUT = 14 * 60          # ephemeral messages can be edited for 15 minutes
MAX_OPTIONS = 25


class SheetView(View):
    """One player's character sheet. Only the player who opened it can use it."""

    def __init__(self, bot_manager, user_id: int, char_name: str):
        super().__init__(timeout=VIEW_TIMEOUT)
        self.bm = bot_manager
        self.app = bot_manager.app
        self.user_id = user_id
        self.char_name = char_name
        self.tab = "overview"
        self.weapon = 0                 # selected attack on the Combat tab
        self.item: Optional[str] = None  # selected consumable on the Inventory tab
        self.last: Optional[str] = None  # result of the last action, shown at the top
        self.pending: Optional[dict] = None   # a roll waiting for "did it hit?" before damage is rolled
        self._build()

    # ------------------------------------------------------------------ data
    def char(self) -> Optional[Character]:
        return Character.load(self.char_name)

    def embed(self) -> discord.Embed:
        char = self.char()
        if not char:
            return discord.Embed(title="Character not found", description=f"{self.char_name} no longer exists.")
        builders = {"overview": lambda: embeds.info_embed(char, self.user_id), "combat": lambda: embeds.combat_embed(char),
                    "inventory": lambda: embeds.inventory_embed(char), "spells": lambda: embeds.spells_embed(char),
                    "features": lambda: embeds.features_embed(char)}
        embed = builders[self.tab]()
        if self.last:
            embed.insert_field_at(0, name="🎲 Last action", value=self.last[:1000], inline=False)
        return embed

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ This sheet belongs to someone else.", ephemeral=True)
            return False
        return True

    async def on_error(self, interaction: discord.Interaction, error: Exception, item):
        self.last = f"❌ {error}"
        await self._redraw(interaction)

    # ------------------------------------------------------------------ building the components
    def _build(self):
        self.clear_items()
        if self.pending:
            self._build_hit_prompt()
            return
        char = self.char()
        for key, title in TABS:
            button = Button(label=title, row=0, style=discord.ButtonStyle.primary if key == self.tab
                            else discord.ButtonStyle.secondary, disabled=key == self.tab)
            button.callback = self._go(key)
            self.add_item(button)
        if not char:
            return
        getattr(self, f"_build_{self.tab}")(char)

    def _go(self, tab: str):
        async def callback(interaction: discord.Interaction):
            self.tab = tab
            self.last = None
            await self._redraw(interaction)
        return callback

    def _button(self, label: str, row: int, action: Callable, style=discord.ButtonStyle.secondary,
                disabled: bool = False) -> Button:
        button = Button(label=label[:80], row=row, style=style, disabled=disabled)
        button.callback = action
        self.add_item(button)
        return button

    def _select(self, placeholder: str, row: int, options: List[discord.SelectOption], action: Callable) -> Select:
        select = Select(placeholder=placeholder[:150], row=row, options=options[:MAX_OPTIONS])
        select.callback = lambda interaction, s=select: action(interaction, s.values[0])
        self.add_item(select)
        return select

    # ---- overview ----
    def _build_overview(self, char: Character):
        svc = self.app.characters
        self._button("🏕️ Short rest", 1, self._run(lambda: self._rest(short=True)))
        self._button("🛌 Long rest", 1, self._run(lambda: self._rest(short=False)), discord.ButtonStyle.success)
        dice = char.hit_dice()
        left = sum(d["total"] - d["used"] for d in dice.values())
        self._button(f"🎲 Hit die ({left})", 1, self._run(lambda: self._hit_die()), disabled=left == 0 or
                     char.current_hp >= char.max_hp)
        self._button(f"⚡ Initiative {sheet.signed(char.initiative)}", 1, self._roll(lambda: svc.roll_check(self.char_name, "initiative")),
                     discord.ButtonStyle.danger)
        if char.current_hp == 0:
            self._button("☠️ Death save", 1, self._roll(lambda: svc.death_save(self.char_name)), discord.ButtonStyle.danger)
        checks = [discord.SelectOption(label=f"{E.ABILITY_NAMES[a]} {sheet.signed(char.mod(a))}", value=E.ABILITY_NAMES[a],
                                       description="Ability check") for a in E.ABILITIES]
        for name, abbr, bonus, marker in sheet.skills(char):
            checks.append(discord.SelectOption(label=f"{name} {sheet.signed(bonus)}", value=name,
                                               description=f"{abbr} {'(expertise)' if marker == '◆' else '(proficient)' if marker == '●' else ''}".strip()))
        self._select("🎯 Roll an ability or skill check", 2, checks,
                     lambda i, v: self._do_roll(i, lambda: svc.roll_check(self.char_name, v)))
        saves = char.saving_throws()
        self._select("🛡️ Roll a saving throw", 3, [
            discord.SelectOption(label=f"{E.ABILITY_NAMES[a]} save {sheet.signed(saves[a]['bonus'])}",
                                 value=E.ABILITY_NAMES[a], description="Proficient" if saves[a]["proficient"] else "")
            for a in E.ABILITIES], lambda i, v: self._do_roll(i, lambda: svc.roll_save(self.char_name, v)))
        mine = self.app.characters.characters_of(self.user_id)
        if len(mine) > 1:
            self._select("🔁 Switch character", 4, [discord.SelectOption(label=n, value=n, default=n == self.char_name)
                                                    for n in mine], self._switch)

    def _rest(self, short: bool) -> str:
        if short:
            self.app.characters.short_rest(self.char_name)
            return "🏕️ Short rest taken. Pact slots and short-rest features recharged."
        self.app.characters.long_rest(self.char_name)
        return "🛌 Long rest taken. HP, spell slots, hit dice and features restored."

    def _hit_die(self) -> str:
        roll, healed = self.app.characters.spend_hit_die(self.char_name)
        return f"🎲 Spent a hit die: rolled {roll}, healed **{healed}** HP."

    async def _switch(self, interaction: discord.Interaction, name: str):
        self.app.characters.use(self.user_id, name)
        self.char_name, self.weapon, self.item, self.last = name, 0, None, None
        await self._redraw(interaction)

    # ---- combat ----
    def _build_combat(self, char: Character):
        svc = self.app.characters
        attacks = char.attacks()
        self.weapon = min(self.weapon, len(attacks) - 1)
        current = attacks[self.weapon]
        self._select("⚔️ Weapon", 1, [discord.SelectOption(
            label=f"{a['name']} {sheet.signed(a['attack'])}", value=str(i), default=i == self.weapon,
            description=a["damage"][:100]) for i, a in enumerate(attacks)], self._pick_weapon)
        weapon = current["name"].split(" (")[0]
        self._button("🎯 Attack", 2, self._attack(weapon), discord.ButtonStyle.danger)
        self._button("Advantage", 2, self._attack(weapon, "adv"))
        self._button("Disadvantage", 2, self._attack(weapon, "dis"))
        self._button("💥 Damage", 3, self._roll(lambda: svc.roll_damage(self.char_name, weapon)), discord.ButtonStyle.primary)
        self._button("💥 Critical", 3, self._roll(lambda: svc.roll_damage(self.char_name, weapon, crit=True)))
        if current["versatile"]:
            self._button(f"Two-handed {current['versatile']}", 3,
                         self._roll(lambda: svc.roll_damage(self.char_name, weapon, two_handed=True)))
        if char.current_hp == 0:
            self._button("☠️ Death save", 4, self._roll(lambda: svc.death_save(self.char_name)), discord.ButtonStyle.danger)

    # ---- "did it hit?" -> damage ----
    def _attack(self, weapon: str, advantage=None):
        async def callback(interaction: discord.Interaction):
            await self._do_run(interaction, lambda: self._attack_roll(weapon, advantage))
        return callback

    def _attack_roll(self, weapon: str, advantage) -> str:
        res = self.app.characters.roll_attack(self.char_name, weapon, advantage)
        text = res.text
        if res.natural == 1:
            return text + "\n💨 Natural 1 - automatic miss."
        crit = res.natural == 20
        self.pending = {"kind": "weapon", "weapon": weapon, "crit": crit}
        return text + ("\n🎯 **Natural 20!** " if crit else "\n") + "**Did it hit?**"

    def _cast(self, spell_name: str) -> str:
        spell = rules.spell(spell_name)
        if spell and not CR.rolls_dice(spell):
            raise ServiceError(f"{spell_name} has no attack or damage roll - it isn't used from Discord.")
        svc = self.app.characters
        out = svc.cast_spell(self.char_name, spell_name)
        found = svc.spell_damage_expr(out["char"], out["spell"], out["slot"])
        if found:
            self.pending = {"kind": "spell", "spell": out["spell"]["name"], "slot": out["slot"], "crit": False}
            return out["text"] + f"\n**Did {out['spell']['name']} hit / affect the target?** ({found[0]} {found[1]})"
        return out["text"]

    def _build_hit_prompt(self):
        crit = self.pending["crit"]
        self._button("Yes - roll critical damage" if crit else "Yes - roll damage", 0, self._damage_answer(True),
                     discord.ButtonStyle.success)
        if self.pending["kind"] == "weapon" and not crit:
            self._button("Yes - critical", 0, self._damage_answer(True, force_crit=True))
        self._button("No - it missed", 0, self._damage_answer(False), discord.ButtonStyle.danger)

    def _damage_answer(self, hit: bool, force_crit: bool = False):
        async def callback(interaction: discord.Interaction):
            pending, self.pending = self.pending, None
            if not hit:
                self.last = "❌ Missed - no damage."
                await self._redraw(interaction)
                return
            svc = self.app.characters
            crit = pending["crit"] or force_crit
            if pending["kind"] == "weapon":
                fn = lambda: svc.roll_damage(self.char_name, pending["weapon"], crit=crit).text
            else:
                fn = lambda: svc.spell_damage(self.char_name, pending["spell"], pending["slot"], crit).text
            await self._do_run(interaction, fn)
        return callback

    async def _pick_weapon(self, interaction: discord.Interaction, value: str):
        self.weapon = int(value)
        await self._redraw(interaction)

    # ---- inventory ----
    def _build_inventory(self, char: Character):
        items = sheet.consumables(char)
        if not items:
            return
        names = [e["name"] for e in items]
        if self.item not in names:
            self.item = names[0]
        self._select("🧪 Consumable", 1, [discord.SelectOption(
            label=f"{e['name']} ×{e['qty']}"[:100], value=e["name"], default=e["name"] == self.item) for e in items],
            self._pick_item)
        self._button(f"Use {self.item}"[:80], 2, self._run(lambda: self.app.characters.use_item(self.char_name, self.item)),
                     discord.ButtonStyle.success)

    async def _pick_item(self, interaction: discord.Interaction, value: str):
        self.item = value
        await self._redraw(interaction)

    # ---- spellbook ----
    def _build_spells(self, char: Character):
        spells = [x for x in SC.spell_known_or_prepared(char) if CR.rolls_dice(x)]      # only spells with attack or damage rolls
        if spells:
            self._select("✨ Cast a spell (lowest slot that works)", 1, [
                discord.SelectOption(label=s["name"][:100], value=s["name"],
                                     description=f"{'Cantrip' if s['level'] == 0 else E.ordinal(s['level']) + ' level'} {s['school']}")
                for s in spells], lambda i, v: self._do_run(i, lambda: self._cast(v)))
        total = SC.spell_slots(char)
        remaining = SC.slots_remaining(char)
        slots = [(str(i + 1), f"{E.ordinal(i + 1)}", n) for i, n in enumerate(total["slots"]) if n]
        if total["pact"]:
            slots.append((SC.PACT_KEY, f"Pact L{total['pact']['level']}", total["pact"]["slots"]))
        for index, (key, title, maximum) in enumerate(slots[:10]):
            left = remaining.get(key, 0)
            self._button(f"{title} {left}/{maximum}", 2 + index // 5,
                         self._run(lambda k=key: self._spend(k)), discord.ButtonStyle.primary if left else
                         discord.ButtonStyle.secondary, disabled=left == 0)
        used = [(k, t) for k, t, m in slots if remaining.get(k, 0) < m]
        if used:
            self._select("↩️ Recover a spent slot", 4, [discord.SelectOption(label=f"{t} slot", value=k) for k, t in used],
                         lambda i, v: self._do_run(i, lambda: self._restore(v)))

    def _spend(self, key: str) -> str:
        self.app.characters.use_slot(self.char_name, key)
        return f"✨ Spent a {'pact' if key == SC.PACT_KEY else E.ordinal(int(key)) + '-level'} spell slot."

    def _restore(self, key: str) -> str:
        self.app.characters.restore_slot(self.char_name, key)
        return f"↩️ Recovered a {'pact' if key == SC.PACT_KEY else E.ordinal(int(key)) + '-level'} spell slot."

    def _build_features(self, char: Character):
        pass

    # ------------------------------------------------------------------ running actions
    def _roll(self, fn: Callable):
        """A button callback that rolls via the service (result has .text)."""
        async def callback(interaction: discord.Interaction):
            await self._do_roll(interaction, fn)
        return callback

    def _run(self, fn: Callable[[], str]):
        async def callback(interaction: discord.Interaction):
            await self._do_run(interaction, fn)
        return callback

    async def _do_roll(self, interaction: discord.Interaction, fn: Callable):
        await self._do_run(interaction, lambda: fn().text)

    async def _do_run(self, interaction: discord.Interaction, fn: Callable[[], str]):
        """Run an action; the services post each roll to the log channel themselves, one compact line per roll."""
        try:
            self.last = await asyncio.to_thread(fn)
        except ServiceError as e:
            self.last = f"❌ {e}"
        await self._redraw(interaction)

    async def _redraw(self, interaction: discord.Interaction):
        self._build()
        embed = self.embed()
        if interaction.response.is_done():
            await interaction.edit_original_response(embed=embed, view=self)
        else:
            await interaction.response.edit_message(embed=embed, view=self)


async def open_sheet(bot_manager, interaction: discord.Interaction):
    """Handler of /sheet: show the player's active character, visible only to them."""
    app = bot_manager.app
    if app is None:
        await interaction.response.send_message("❌ Bot not fully initialized.", ephemeral=True)
        return
    char = await asyncio.to_thread(app.characters.active_for, interaction.user.id)
    if not char:
        await interaction.response.send_message(
            "You don't have a character yet. Ask the GM for one, then use `/assigncharacter`.", ephemeral=True)
        return
    view = SheetView(bot_manager, interaction.user.id, char.name)
    await interaction.response.send_message(embed=view.embed(), view=view, ephemeral=True)
