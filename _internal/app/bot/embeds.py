"""Discord embeds for a character sheet. Pure functions over the rules model (no discord I/O)."""

import discord

from ..services.battle import combat_rules as CR
from ..rules import engine as E
from ..rules import sheet
from ..rules import spellcasting as SC
from ..rules.character import Character

COLOR_INFO = 0x5865F2
COLOR_PLAIN = 0x2b2d31
COLOR_SPELL = 0x9b59b6
FIELD_LIMIT = 1000   # Discord allows 1024 characters per field value


def _clip(text: str, limit: int = FIELD_LIMIT) -> str:
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _player(owner_id) -> str:
    """A Discord player as a mention; a player added by hand (a negative id) by their name."""
    if not owner_id:
        return "Unassigned"
    if int(owner_id) > 0:
        return f"<@{owner_id}>"
    from ..core.runtime import rt
    return rt().players.name_of(owner_id) or "Unassigned"


def info_embed(char: Character, owner_id) -> discord.Embed:
    v = sheet.vitals(char)
    embed = discord.Embed(title=f"👤 {char.name}", color=COLOR_INFO,
                          description=f"{sheet.title(char)}\n{sheet.class_line(char)}")
    hp = f"{v['hp']}/{v['max_hp']}" + (f" (+{v['temp_hp']} temp)" if v["temp_hp"] else "")
    embed.add_field(name="❤️ Hit Points", value=f"{hp}\n`{sheet.hp_bar(char)}`", inline=True)
    embed.add_field(name="🛡️ Armor Class", value=f"**{v['ac']}**\n{v['ac_note']}", inline=True)
    embed.add_field(name="⚡ Combat", value=f"Initiative {sheet.signed(v['initiative'])}\nSpeed {v['speed']} ft\n"
                                           f"Proficiency {sheet.signed(v['proficiency'])}", inline=True)
    rows = []
    for abbr, score, mod, save, prof in sheet.abilities(char):
        rows.append(f"**{abbr}** {score} ({sheet.signed(mod)})  save {sheet.signed(save)}{' ●' if prof else ''}")
    embed.add_field(name="Abilities", value="\n".join(rows), inline=True)
    extra = [f"Passive Perception **{v['passive_perception']}**", f"Hit dice {v['hit_dice']}",
             f"XP {v['xp']}" + (f" / {v['next_xp']}" if v["next_xp"] else "")]
    if v["darkvision"]:
        extra.append(f"Darkvision {v['darkvision']} ft")
    if v["inspiration"]:
        extra.append("✨ Inspiration")
    embed.add_field(name="Details", value="\n".join(extra), inline=True)
    status = v["conditions"] + ([f"Exhaustion {v['exhaustion']}"] if v["exhaustion"] else [])
    embed.add_field(name="⚠️ Conditions", value=", ".join(status) or "None", inline=False)
    embed.add_field(name="Player", value=_player(owner_id), inline=True)
    resources = sheet.resources_text(char)
    if resources:
        embed.add_field(name="Class Resources", value=_clip("\n".join(resources)), inline=False)
    notes = char.notes
    if notes:
        embed.add_field(name="Notes", value=_clip("\n".join(f"#{n['id']}: {n['text']}" for n in notes)), inline=False)
    return embed


def inventory_embed(char: Character) -> discord.Embed:
    embed = discord.Embed(title="🎒 Inventory", color=COLOR_PLAIN)
    lines = [f"• {l}" for l in sheet.inventory_lines(char)] or ["Empty"]
    chunk, part = "", 1
    for line in lines:
        if len(chunk) + len(line) + 1 > FIELD_LIMIT:
            embed.add_field(name="Items" if part == 1 else "Items (cont.)", value=chunk, inline=False)
            chunk, part = "", part + 1
        chunk += ("\n" if chunk else "") + line
    embed.add_field(name="Items" if part == 1 else "Items (cont.)", value=chunk, inline=False)
    embed.add_field(name="💰 Money", value=sheet.money_text(char), inline=True)
    embed.add_field(name="Weight", value=f"{char.carried_weight:g} / {char.carrying_capacity} lb\n{char.encumbrance}", inline=True)
    embed.set_footer(text="E = equipped · A = attuned")
    return embed


def skills_embed(char: Character) -> discord.Embed:
    embed = discord.Embed(title="🎯 Skills", color=COLOR_PLAIN)
    rows = [f"{marker} **{name}** {sheet.signed(bonus)} *({abbr})*" for name, abbr, bonus, marker in sheet.skills(char)]
    half = (len(rows) + 1) // 2
    embed.add_field(name="​", value="\n".join(rows[:half]), inline=True)
    embed.add_field(name="​", value="\n".join(rows[half:]), inline=True)
    embed.set_footer(text="◆ expertise · ● proficient · ○ not proficient")
    profs = char.d["proficiencies"]
    for label, key in (("Languages", "languages"), ("Tools", "tools"), ("Armor", "armor"), ("Weapons", "weapons")):
        if profs[key]:
            embed.add_field(name=label, value=_clip(", ".join(profs[key])), inline=False)
    return embed


def features_embed(char: Character) -> discord.Embed:
    embed = discord.Embed(title="📜 Features & Traits", color=COLOR_PLAIN)
    for source, names in list(sheet.feature_groups(char).items())[:24]:
        embed.add_field(name=_clip(source, 250), value=_clip(", ".join(names)), inline=False)
    return embed


def spells_embed(char: Character) -> discord.Embed:
    embed = discord.Embed(title="📖 Spellbook", color=COLOR_SPELL)
    infos = SC.casters(char)
    if infos:
        embed.description = "\n".join(
            f"**{i['class']}** — spell save DC **{i['dc']}**, spell attack **{sheet.signed(i['attack'])}**"
            + (f", prepared {len(SC.class_spells(char, i['class'])['prepared'])}/{i['prepared']}" if i["prepared"] is not None else "")
            for i in infos)
    embed.add_field(name="Spell Slots", value=sheet.slots_text(char), inline=False)
    castable, other = {}, {}
    for sp in SC.spell_known_or_prepared(char):
        label = sp["name"] + (" (r)" if sp["ritual"] else "") + (" (c)" if sp["concentration"] else "")
        (castable if CR.rolls_dice(sp) else other).setdefault(sp["level"], []).append(label)
    for title, group in (("🎲 Castable here (attack or damage rolls)", castable), ("📖 Also known - not used from Discord", other)):
        if group:
            embed.add_field(name=title, value=_clip("\n".join(f"**{'Cantrips' if lv == 0 else E.ordinal(lv) + ' level'}:** {', '.join(group[lv])}"
                                                           for lv in sorted(group))), inline=False)
    if not castable and not other:
        embed.add_field(name="Spells", value="No spells known or prepared.", inline=False)
    embed.set_footer(text="(r) ritual · (c) concentration")
    return embed


def combat_embed(char: Character) -> discord.Embed:
    from ..rules.resources import resource_list
    ac, why = char.armor_class()
    embed = discord.Embed(title="⚔️ Combat", color=0xe74c3c,
                          description=f"**AC {ac}** — {why}\nInitiative {sheet.signed(char.initiative)} · "
                                      f"Speed {char.speed} ft · Proficiency {sheet.signed(char.proficiency_bonus)}")
    attacks = char.attacks()
    lines = []
    for a in attacks:
        notes = f" *({', '.join(a['notes'])})*" if a["notes"] else ""
        lines.append(f"**{a['name']}** — {sheet.signed(a['attack'])} to hit, {a['damage']}{notes}")
    embed.add_field(name="Attacks", value=_clip("\n".join(lines)), inline=False)
    resources = resource_list(char)
    if resources:
        embed.add_field(name="Class Resources", value=_clip("\n".join(sheet.resources_text(char))), inline=False)
    if char.current_hp == 0:
        s = char.d["death_saves"]
        embed.add_field(name="☠️ Death saves", value=f"Successes {s['success']}/3 · Failures {s['failure']}/3", inline=False)
    return embed
