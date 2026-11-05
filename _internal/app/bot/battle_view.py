"""/initiative: a private, live-updating view of the battle for one player. It warns when it is their turn."""
import asyncio
import time
from typing import Optional

import discord
from discord.ui import Button, View

from ..services.battle import battlemap
from ..services.battle import ACTIVE, ENDED, SETUP, health_word
from ..services.common import ServiceError

LIFETIME = 14 * 60            # ephemeral messages can be edited for 15 minutes
COLOR_TURN = 0xED4245
COLOR_NEXT = 0xFEE75C
COLOR_PLAIN = 0x5865F2
MAX_LINES = 40


def bar(hp: int, max_hp: int, width: int = 8) -> str:
    filled = round(width * max(0, hp) / max_hp) if max_hp else 0
    return "█" * filled + "░" * (width - filled)


class InitiativeView(View):
    def __init__(self, bot_manager, user_id: int):
        super().__init__(timeout=LIFETIME)
        self.bm = bot_manager
        self.battle = bot_manager.app.battle
        self.user_id = user_id
        self.interaction: Optional[discord.Interaction] = None
        self.created = time.time()
        self.last: Optional[str] = None
        self._build()

    # ------------------------------------------------------------------ content
    def lines_and_flags(self, view: dict):
        mine = {c["character"] for c in view["combatants"] if c["kind"] == "pc"
                and c["character"] in self.bm.app.characters.characters_of(self.user_id)}
        order = view["combatants"]
        turn_index = next((i for i, c in enumerate(order) if c["id"] == view["turn"]), None)
        lines = []
        for c in order:
            current = c["id"] == view["turn"]
            init = "—" if c["init"] is None else str(c["init"])
            marker = "▶" if current else "▫️"
            if c["kind"] == "pc":
                you = " **(you)**" if c["character"] in mine else ""
                health = f"❤️ {c['hp']}/{c['max_hp']} `{bar(c['hp'], c['max_hp'])}`" + (" 💀 **down**" if c.get("downed") else "")
                text = f"{marker} `{init:>2}` **{c['name']}**{you} — {health} · AC {c['ac']}"
            else:
                if c["hp"] <= 0:
                    text = f"{marker} `{init:>2}` ~~{c['name']}~~ — 💀 defeated"
                elif view["reveal_hp"] or c["revealed"]:
                    text = f"{marker} `{init:>2}` **{c['name']}** — ❤️ {c['hp']}/{c['max_hp']} `{bar(c['hp'], c['max_hp'])}`"
                else:
                    text = f"{marker} `{init:>2}` **{c['name']}** — {health_word(c['hp'], c['max_hp'])}"
            if c["conditions"]:
                text += f" · ⚠️ {', '.join(c['conditions'])}"
            lines.append(text)
        return lines, mine, turn_index

    def embed(self) -> discord.Embed:
        view = self.battle.view()
        if view["status"] == SETUP and not view["combatants"] or (view["status"] == ENDED and not view["summary"]):
            return discord.Embed(title="⚔️ No battle in progress", description="The GM hasn't started a battle yet.",
                                 color=COLOR_PLAIN)
        lines, mine, turn_index = self.lines_and_flags(view)
        order = view["combatants"]
        turn = next((c for c in order if c["id"] == view["turn"]), None)
        warning, color = "", COLOR_PLAIN
        if view["status"] == ACTIVE and turn:
            if turn["kind"] == "pc" and turn["character"] in mine:
                warning = f"## ⚠️ YOUR TURN, {turn['character']}!\n"
                color = COLOR_TURN
            else:
                nxt = None
                for step in range(1, len(order) + 1):
                    cand = order[(turn_index + step) % len(order)]
                    if not (cand["kind"] == "enemy" and cand["hp"] <= 0):
                        nxt = cand
                        break
                if nxt and nxt["kind"] == "pc" and nxt["character"] in mine:
                    warning = f"⏭️ **You're up next, {nxt['character']}!** Get ready.\n"
                    color = COLOR_NEXT
        if view["status"] == SETUP:
            head = "🎲 **Rolling for initiative** — the battle starts soon."
        elif view["status"] == ACTIVE:
            head = f"**Round {view['round']}** · it's **{turn['name'] if turn else '?'}**'s turn"
        else:
            s = view["summary"] or {}
            head = f"🏁 **Battle over** after {s.get('rounds', 0)} round(s)."
        body = "\n".join(lines[:MAX_LINES]) + (f"\n… and {len(lines) - MAX_LINES} more" if len(lines) > MAX_LINES else "")
        embed = discord.Embed(title=f"⚔️ {view['name']}", description=f"{warning}{head}\n\n{body}", color=color)
        if self.last:
            embed.add_field(name="🎲 Last action", value=self.last[:1000], inline=False)
        embed.set_footer(text="Updates live · enemy health is shown in words unless the GM reveals it")
        return embed

    # ------------------------------------------------------------------ components
    def _build(self):
        self.clear_items()
        view = self.battle.view()
        refresh = Button(label="Refresh", emoji="🔄", style=discord.ButtonStyle.secondary, row=0)
        refresh.callback = self._refresh
        self.add_item(refresh)
        mine = [c for c in view["combatants"] if c["kind"] == "pc" and c["character"]
                in self.bm.app.characters.characters_of(self.user_id)]
        can_roll = [c for c in mine if c["init"] is None] and view["status"] in (SETUP, ACTIVE)
        if can_roll:
            roll = Button(label="Roll my initiative", emoji="🎲", style=discord.ButtonStyle.primary, row=0)
            roll.callback = self._roll
            self.add_item(roll)

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.user_id:
            await interaction.response.send_message("❌ This view belongs to someone else. Use `/initiative` yourself.", ephemeral=True)
            return False
        return True

    async def _refresh(self, interaction: discord.Interaction):
        self._build()
        await interaction.response.edit_message(embed=self.embed(), view=self)

    async def _roll(self, interaction: discord.Interaction):
        todo = [c for c in self.battle.view()["combatants"] if c["kind"] == "pc" and c["init"] is None
                and c["character"] in self.bm.app.characters.characters_of(self.user_id)]
        notes = []
        for c in todo:
            try:
                total = await asyncio.to_thread(self.battle.roll_for_character, c["character"])
                notes.append(f"{c['character']} rolled **{total}**")
            except ServiceError as e:
                notes.append(f"❌ {e}")
        self.last = "\n".join(notes) or "Nothing to roll."
        self._build()
        await interaction.response.edit_message(embed=self.embed(), view=self)

    async def on_timeout(self):
        self.bm.unregister_initiative(self)

    # ------------------------------------------------------------------ live updates
    @property
    def expired(self) -> bool:
        return time.time() - self.created > LIFETIME

    async def push(self):
        """Edit the message the player already has open (called when the battle changes)."""
        if self.interaction is None or self.expired:
            self.bm.unregister_initiative(self)
            return
        self._build()
        try:
            await self.interaction.edit_original_response(embed=self.embed(), view=self)
        except discord.HTTPException:
            self.bm.unregister_initiative(self)


async def open_initiative(bot_manager, interaction: discord.Interaction):
    """Handler of /initiative: show the battle privately and keep it up to date."""
    app = bot_manager.app
    if app is None:
        await interaction.response.send_message("❌ Bot not fully initialized.", ephemeral=True)
        return
    view = InitiativeView(bot_manager, interaction.user.id)
    await interaction.response.send_message(embed=view.embed(), view=view, ephemeral=True)
    view.interaction = interaction
    bot_manager.register_initiative(view)


class BattleMapView(View):
    """/battlemap: the map as text. It follows the battle (turn changes, moves, damage) like /initiative does."""

    def __init__(self, bot_manager):
        super().__init__(timeout=LIFETIME)
        self.bm = bot_manager
        self.battle = bot_manager.app.battle
        self.interaction: Optional[discord.Interaction] = None
        self.created = time.time()
        self.shown: Optional[str] = None
        button = Button(label="Refresh", emoji="🔄", style=discord.ButtonStyle.secondary)
        button.callback = self._refresh
        self.add_item(button)

    def content(self) -> str:
        view = self.battle.view()
        if not view["combatants"]:
            text = "⚔️ No battle in progress."
        else:
            text = "```\n" + battlemap.render(view)[:1900] + "\n```"
        self.shown = text
        return text

    async def _refresh(self, interaction: discord.Interaction):
        await interaction.response.edit_message(content=self.content(), view=self)

    async def on_timeout(self):
        self.bm.unregister_initiative(self)

    async def push(self):
        """Called whenever the battle changes: edit the open message when the map or the list is different."""
        if self.interaction is None or time.time() - self.created > LIFETIME:
            self.bm.unregister_initiative(self)
            return
        before = self.shown
        text = self.content()
        if text == before:
            return
        try:
            await self.interaction.edit_original_response(content=text, view=self)
        except discord.HTTPException:
            self.bm.unregister_initiative(self)


async def open_battlemap(bot_manager, interaction: discord.Interaction, public: bool = False):
    """Handler of /battlemap: the battle map as an ASCII grid with the initiative list under it."""
    if bot_manager.app is None:
        await interaction.response.send_message("❌ Bot not fully initialized.", ephemeral=True)
        return
    view = BattleMapView(bot_manager)
    await interaction.response.send_message(content=view.content(), view=view, ephemeral=not public)
    view.interaction = interaction
    bot_manager.register_initiative(view)
