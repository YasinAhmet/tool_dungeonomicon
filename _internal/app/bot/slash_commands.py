"""Discord slash command definitions.

Almost every command is a thin wrapper: a small function builds the equivalent text
command (e.g. '/additem "Longsword" 2') and the shared CommandProcessor runs it, so
Discord and the GUI command line behave identically.
"""
import asyncio
import functools
from typing import Literal, Optional

import discord
from discord import app_commands

from ..core.i18n import i18n
from . import localize_patch
from .battle_view import open_battlemap, open_initiative
from .sheet_view import open_sheet

NOT_READY = "❌ Bot not fully initialized."
Advantage = Optional[Literal["adv", "dis"]]


def q(text: str) -> str:
    """Quote an argument for the text command parser."""
    return '"' + text.replace('"', "'") + '"'


def register_slash_commands(bm):
    """Register every slash command on bm.tree."""
    tree = bm.tree
    localize_patch.install()

    def passthrough(name: str, description: str, admin_only: bool = False, roll: bool = False):
        """Decorator: `build(interaction, **params)` returns the text command to run.

        `roll` commands are already posted to the Discord log, so when that log is on they send no reply
        of their own (only errors, privately)."""
        def decorator(build):
            @functools.wraps(build)
            async def callback(interaction: discord.Interaction, **params):
                if bm.app is None:
                    await interaction.response.send_message(NOT_READY, ephemeral=True)
                    return
                try:
                    command = build(interaction, **params)
                    quiet = roll and bm.app.logs_kind("player_rolls")
                    if quiet:
                        await interaction.response.defer(ephemeral=True, thinking=True)
                    result = await asyncio.to_thread(
                        bm.app.command_processor.process, command, interaction.user.id,
                        interaction.user.display_name)
                    if not quiet:
                        await interaction.response.send_message(result or "No result.")
                    elif result and result.startswith("❌"):
                        await interaction.edit_original_response(content=result)
                    else:
                        await interaction.delete_original_response()
                except Exception as e:
                    if interaction.response.is_done():
                        text = f"❌ Error: {e}"
                        await interaction.followup.send(i18n.t(text, i18n.player_language(interaction.user.id)), ephemeral=True)
                    else:
                        await interaction.response.send_message(f"❌ Error: {e}", ephemeral=True)
            if admin_only:
                callback = app_commands.default_permissions(administrator=True)(callback)
            return tree.command(name=name, description=description)(callback)
        return decorator

    def with_adv(command: str, advantage: Advantage) -> str:
        return f"{command} {advantage}" if advantage else command

    # ---- rolls ----
    @passthrough("roll", "Roll dice (e.g., 2d6+3)", roll=True)
    def roll(interaction, expression: str):
        return f"/roll {expression}"

    @passthrough("check", "Make an ability or skill check (e.g., Stealth or Strength)", roll=True)
    def check(interaction, what: str, advantage: Advantage = None):
        return with_adv(f"/check {q(what)}", advantage)

    @passthrough("save", "Make a saving throw (e.g., Dexterity)", roll=True)
    def save(interaction, ability: str, advantage: Advantage = None):
        return with_adv(f"/save {ability}", advantage)

    @tree.command(name="initiative", description="See the initiative order and battle state (only you can see it)")
    async def initiative(interaction: discord.Interaction):
        await open_initiative(bm, interaction)

    languages = i18n.languages()

    @tree.command(name="language", description="Choose the language of the bot's messages to you ("
                  + " or ".join(name for _code, name in languages) + ")")
    @app_commands.choices(language=[app_commands.Choice(name=name, value=code) for code, name in languages])
    async def language(interaction: discord.Interaction, language: app_commands.Choice[str]):
        i18n.set_player_language(interaction.user.id, language.value)
        await interaction.response.send_message(f"🌐 Language set to **{language.name}**.", ephemeral=True)

    @tree.command(name="battlemap", description="See the battle map as text: tiles, initiative numbers and who is up")
    async def battlemap(interaction: discord.Interaction, public: bool = False):
        await open_battlemap(bm, interaction, public)

    @passthrough("attack", "Attack with an equipped weapon", roll=True)
    def attack(interaction, weapon: str, advantage: Advantage = None):
        return with_adv(f"/attack {q(weapon)}", advantage)

    # ---- character ----
    @tree.command(name="sheet", description="Open your interactive character sheet (only you can see it)")
    async def sheet(interaction: discord.Interaction):
        await open_sheet(bm, interaction)

    @passthrough("hp", "Show your hit points and hit dice")
    def hp(interaction):
        return "/hp"

    @passthrough("damagechar", "Deal damage to your character")
    def damagechar(interaction, amount: int):
        return f"/damagechar {amount}"

    @passthrough("healchar", "Heal your character")
    def healchar(interaction, amount: int):
        return f"/healchar {amount}"

    @passthrough("rest", "Take a short or long rest")
    def rest(interaction, kind: Literal["short", "long"]):
        return f"/rest {kind}"

    @passthrough("hitdie", "Spend a hit die to heal during a short rest")
    def hitdie(interaction):
        return "/hitdie"

    @passthrough("features", "List your class, race and feat features")
    def features(interaction):
        return "/features"

    @passthrough("addnote", "Add a note to your character")
    def addnote(interaction, note: str):
        return f"/addnote {note}"

    @passthrough("removenote", "Remove a note from your character")
    def removenote(interaction, note_id: int):
        return f"/removenote {note_id}"

    @passthrough("notes", "Show your character's notes")
    def notes(interaction):
        return "/notes"

    # ---- inventory ----
    @passthrough("inventory", "Show your inventory and money")
    def inventory(interaction):
        return "/inventory"

    @passthrough("additem", "Add an item to your inventory")
    def additem(interaction, item: str, amount: Optional[int] = 1):
        return f"/additem {q(item)} {amount}"

    @passthrough("removeitem", "Remove an item from your inventory")
    def removeitem(interaction, item: str, amount: Optional[int] = 1):
        return f"/removeitem {q(item)} {amount}"

    @passthrough("equip", "Equip armor, a shield or a weapon")
    def equip(interaction, item: str):
        return f"/equip {q(item)}"

    @passthrough("unequip", "Take off or put away an item")
    def unequip(interaction, item: str):
        return f"/unequip {q(item)}"

    @passthrough("attune", "Attune to a magic item (max 3)")
    def attune(interaction, item: str):
        return f"/attune {q(item)}"

    @passthrough("senditem", "Give an item to another character")
    def senditem(interaction, item: str, amount: int, target: str):
        return f"/senditem {q(item)} {amount} {q(target)}"

    @passthrough("buyitem", "Buy items with your coins")
    def buyitem(interaction, item: str, amount: int, goldcost: float, character: Optional[str] = None):
        return f"/buyitem {q(item)} {amount} {goldcost}" + (f" {q(character)}" if character else "")

    # ---- spells ----
    @passthrough("spells", "List your known and prepared spells")
    def spells(interaction):
        return "/spells"

    @passthrough("slots", "Show your spell slots")
    def slots(interaction):
        return "/slots"

    @passthrough("cast", "Cast a spell, optionally at a higher slot level")
    def cast(interaction, spell: str, slot: Optional[int] = None, ritual: Optional[bool] = False):
        return f"/cast {q(spell)}" + (f" {slot}" if slot else "") + (" ritual" if ritual else "")

    # ---- roster ----
    @passthrough("listchars", "List unassigned characters")
    def listchars(interaction):
        return "/listchars"

    @passthrough("assigncharacter", "Add an unassigned character to your characters")
    def assigncharacter(interaction, name: str):
        return f"/assigncharacter {q(name)}"

    @passthrough("unassigncharacter", "Release one of your characters")
    def unassigncharacter(interaction, name: Optional[str] = None):
        return f"/unassigncharacter {q(name)}" if name else "/unassigncharacter"

    @passthrough("mychars", "List your characters")
    def mychars(interaction):
        return "/mychars"

    @passthrough("usecharacter", "Choose which of your characters commands act on")
    def usecharacter(interaction, name: str):
        return f"/usecharacter {q(name)}"

    @passthrough("help", "Show available commands")
    def help_(interaction):
        return "/help"

    # ---- admin ----
    @tree.command(name="sync", description="Clear and resync slash commands (admin only)")
    @app_commands.default_permissions(administrator=True)
    async def sync(interaction: discord.Interaction):
        if interaction.guild is None:
            await interaction.response.send_message("❌ Use this command inside a server.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        names = await bm.sync_guild_commands(interaction.guild)
        await interaction.followup.send(
            f"✅ Cleared old commands and synced current commands to {interaction.guild.name}\n"
            f"Commands: {', '.join(names)}", ephemeral=True)
