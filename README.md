# tool_dungeonomicon
A tool that allows many things for a DnD session. Combat management, map drawing, character creation and tracking, audio steering etc..

Everything began when I wanted to steer some background music to my players.
Then I kept adding more and more into it recently. It evolved into something actually useful. So I'm sharing it with you guys and gals.

I hope it's useful for you too!

Below this, you will find a guide prepared by AI, however feel free to come and ask stuff on Discord directly to me. Take care!

https://github.com/YasinAhmet/tool_dungeonomicon/raw/main/.github/demo.mp4

---

# Dungeonomicon guide

Dungeonomicon is a Dungeon Master desktop app for D&D 5e (2014 rules). It covers characters with a full rules engine,
battles on a map, a rules library with your own homebrew, a creature generator, dice, background music and sound, a
player portal in the browser, and a Discord bot. It all runs on your own PC.

## Getting started

1. Download **Dungeonomicon-v1.0.zip** from [Releases](../../releases) (Windows, 64-bit).
2. Unzip it anywhere, for example to your desktop.
3. Open the `Dungeonomicon` folder and double-click **`App.exe`**. Nothing needs installing.

A loading window shows while the rules library loads, then the editor opens. **Help ▸ Getting started** walks you
through the first steps, and **F1** lists the keyboard shortcuts.

Your characters, settings (including a Discord bot token), layouts, logs and backups are saved in
`Documents\Dungeonomicon`, never in the program folder. You can delete or replace the program folder, for example
with a new version, without losing anything.

## The rules content and modules

The program comes with the **System Reference Document 5.1** (the free 5e rules, CC BY 4.0): 12 classes with one
subclass each, 9 races, 319 spells, 322 creatures and about 1,000 items.

Other content comes as **modules**: `.dmmod` files that hold books, creatures, pictures, sounds or portraits.

* Put `.dmmod` files in the **`modules`** folder next to `App.exe` (it starts empty, apart from a read-me). Their
  books show up in **Settings ▸ Sourcebooks** at once, even while the app is running.
* Take a file out and its content goes with it. A character keeps what it already has, and shows the missing book
  by name.
* **Settings ▸ Installations** lists your modules. From there you can switch them off, remove them, export them, or
  turn one of your own homebrew rulebooks into a module to share.
* Only the books ticked in **Settings ▸ Sourcebooks** are offered anywhere in the app.
* The `modules` folder travels with the program: zip the whole `Dungeonomicon` folder and give it to a friend, and
  it starts on their PC with the same modules.

## The editor

Every tool is a window you can dock anywhere: beside another window, as a tab, floating on a second screen, or
pinned to a side bar.

* **Window** menu: open any window. The main ones are **Battle map**, **Party**, **Library**, **Audio** and
  **Inspector**.
* **Layout** menu: ready-made layouts (*Game night*, *Battle*, *Characters*, *Prep*, *Sound*) and your own saved
  ones. The layout you close the app with comes back next time.
* **Inspector**: shows whatever you picked last, such as a monster, item, spell, rules entry, a character's full
  sheet, or the battle map's selection. Type in its search line to look anything up.
* **Enter** (when you're not typing in a box): opens the log, chat and dice. Type to talk to the table, `2d6+3` or
  `d20 adv` to roll, or `/help` for the text commands. Esc closes it.
* **Settings ▸ Language**: choose the interface language.

## Characters

Characters follow the 2014 Player's Handbook rules, with every number worked out for you.

* **Creation wizard**: race and subrace, ability scores (standard array, 27-point buy, or 4d6 drop lowest),
  background, class with all its level 1 choices, and starting equipment or gold.
* **Levelling from 1 to 20**: hit points, subclass, ability score improvements or feats, spells, and every class
  choice. Use XP, or switch a character to milestone levelling.
* **Multiclassing**, with prerequisites, limited proficiencies and the multiclass spell slot table.
* **Everything derived**: saves, skills, passive Perception, initiative, AC, attack and damage numbers, spell DC and
  carrying capacity.
* **Items**: equipping, attunement (up to 3 items), magic item effects applied automatically, and coins with change.
* **Spells**: slots, upcasting, concentration, rituals, and prepared and always-prepared spells.
* **At the table**: damage and healing with temporary HP, death saves, short and long rests, hit dice, conditions,
  exhaustion, inspiration, and class resources such as Rage, Ki and Channel Divinity.

The **Party** window holds your players and their characters, who is playing this session, the team inventory and
team notes.

## Running a fight

1. Open the **Battle map** in **✏ Edit** mode. Drag creatures in from the drawer or the Library, draw walls, and drop
   props such as doors, stairs, windows and chests. Right-click a prop to pin it to the quick bar above the map.
2. **Add players…** in the initiative order puts this session's characters in with one click.
3. **💾 Encounters** saves the setup, so you can load it when the party gets there.
4. **▶ Start battle** switches to **▶ Play**. The creature whose turn it is gets an action bar: aim on the map and
   click to walk. Double-click any token to act for it instead, for a reaction or a legendary action.
5. Right-click a token or a row in the initiative order to deal damage of a type (resistances apply), apply
   conditions with a duration or a repeated save, change hit points, duplicate or remove. Select several rows with
   Ctrl or Shift to affect them all at once.

Shortcuts: **Ctrl+Space** ends the turn, **Ctrl+Z** undoes the last change, **Ctrl+E** switches between Edit and
Play, and **D** and **H** damage or heal the selected token.

**Drawing on the map:** ✏ draw turns rough strokes into straight walls along the grid (a stroke that ends near its
start becomes a room), 〰 draws free lines such as rivers and paths, and 🧽 erases. Map symbols (doors, secret doors,
stairs, traps, chests, pillars, fire, water, trees...) can be dragged onto a tile. With ✋ select, drag a symbol to
move it; **R** rotates it and **Del** removes it.

## The Library

The Library holds all the monsters, items, spells and rules entries from the books you have switched on, plus your
own homebrew. The **Creature workshop** and **Item workshop** let you make your own. The monster and item searches
can filter by almost anything, and they understand a short search syntax, for example `type:undead`, `cr:>=5`,
`cr:1/2-4`, `-env:forest`, `rarity:rare`, `cost:<=50`, `"exact phrase"` and `-excluded`.

## Player portal: the battle map in your players' browsers

The 🌐 button on the toolbar opens **Party ▸ Player portal**.

1. The first time, press **Download cloudflared**. This is one program from Cloudflare's official releases (about
   60 MB, saved to `Documents\Dungeonomicon\tools`). Its signature is checked, and nothing is installed.
2. Press **Share with players**. A free Cloudflare tunnel gives the page a public `https://….trycloudflare.com`
   address. There's no router setup and no open ports, and your IP stays hidden. The address changes each time you
   start sharing.
3. Every player who owns a character gets a **personal link** that logs them in. Copy it, or have the Discord bot
   send everyone their link. **New link** makes a player's old link stop working.

Players see the live battle map and initiative (enemy HP is shown in words unless you reveal it), their own character
sheet, and the table chat with every roll. They can roll checks, saves, attacks, damage, spells, initiative and death
saves. On their turn they can attack or cast on the target they pick and move their own token; you can switch both
off.

Players without Discord can be added as **manual** players, with just a name. Copy their link and send it yourself.

**This PC only** runs the page without a public address. Stopping sharing, or closing the app, takes the address
down.

## Discord bot (optional)

The bot gives your players interactive character sheets and slash commands in Discord, and plays the app's music and
sounds in a voice channel.

1. Create a bot in the [Discord Developer Portal](https://discord.com/developers/applications): **New Application ▸
   Bot**, then copy its **token**.
2. Under **Bot ▸ Privileged Gateway Intents**, switch on **Server Members Intent** so the app can list every member of
   your server. The bot still works without it, but then it only lists members it has seen.
3. Invite the bot to your server (**OAuth2 ▸ URL Generator**, with the `bot` and `applications.commands` scopes).
4. In Dungeonomicon, open **Window ▸ Discord**, paste the token and press **Start**. Pick your server in the toolbar,
   then its voice channel and a log channel.

In Discord, **`/sheet`** opens a character sheet that only that player can see, with buttons for checks and saves,
attacks, inventory, spells and rests. Every roll is made for you and also posted to the log channel. There are over 30
slash commands, such as `/check`, `/save`, `/attack`, `/cast`, `/rest`, `/hp`, `/inventory` and `/roll`; run `/help`
for the full list. You create characters in the app, and players claim theirs with `/assigncharacter`.

## Audio

The **Audio** window plays background music, ambient loops and sound effects, either on your PC or through the
Discord bot in your voice channel. The sounds come from the asset modules in the `modules` folder.

## Questions and problems

Ask me directly on Discord. If something goes wrong, the app's log is in `Documents\Dungeonomicon\logs\app.log`;
please send it along.

