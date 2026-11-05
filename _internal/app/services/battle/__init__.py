"""The battle tracker (`rt().battle`): one battle at a time, assembled from focused parts.

    base.py        load/save, the battle log, views          setup.py       adding and removing combatants
    board.py       the battle map                            initiative.py  initiative order
    drawing.py     lines, rooms and symbols drawn on the map (shapes.py snaps rough strokes to the grid)
    floors.py      the floors of a building side by side on the map, stairs between them
    flow.py        start/end, turns, rounds, XP              actions.py     damage/heal/conditions, card rolls
    targeting.py   targets, changed numbers, concentration   effects.py     effects and automatic resolution
    areas.py       areas of effect                           summons.py     summoned creatures
    spells.py      casting in battle                         durations.py   turn start/end bookkeeping
    profile.py     a creature right now (sheet + effects)    resolve.py     attacks/saves/damage, reaction windows
    reactions.py   who may react and what it does            zones.py       lasting areas on the map
    movement.py    paths, opportunity attacks, push/pull     standard.py    weapon attacks, stat block actions, core actions
    abilities.py   class / race features                     menu.py        the action bar: what can be done, act()
    feats.py       situational feats (GWM, Sentinel, Lucky...; switches in rules/combat_feats.py)
    dispatch.py    battle events and their hooks
    history.py     undo / redo of every committed change      editing.py     the DM's edits: HP, temp HP, names, copies
    encounters.py  saved encounters (encounters/<name>.json next to battle.json)
    ground.py      items on the map's ground, what creatures carry, throwing things (props the DM marks throwable, flasks)
    items.py       using what a hero carries: potions (Use an Object), spell scrolls, wands and staffs (charges), caltrops
    itempowers.py  magic weapons' powers: extra damage on a hit (Flame Tongue, Dragon Slayer...), activations on the bar
    itemextras.py  more weapons' one-of-a-kind powers (Medusa, Polymorph Blade, Agonizing Paralysis, Starshot, Fool's...)
    wondrous.py    other magic items: what worn ones give (Cloak of Displacement, adamantine...), used ones (Horn of Blasting...)
    itemmore.py    the 2024-worded items (Arcana Unleashed, Eberron, Faerun): Dazzling weapons, Tramontane armour, Wand of Teeth...
    traits.py      monster traits in play: Martial Advantage, Sneak Attack, Charge / Pounce, Blood Frenzy, Reckless, Relentless
    charge.py      charging: a straight run at a foe and the blow it sets up, one bar entry (monster charges, Charger, Centaur...)
    classfeats.py  subclass and race features in play: extra damage on hits, Channel Divinity options, Warding Flare...
    racefeats.py   race and lineage traits in play: Daunting Roar, Feline Agility, Astral Spark, Hadozee Dodge, shifter lineages...

Pure rules (no battle state, tested on their own in tests/test_engine.py): geometry.py (grid, distances, areas),
sight.py (walls, cover, light, who sees whom), conditions.py, modifiers.py (resistances, buffs, nerfs), economy.py
(action economy), spellbook.py (each spell compiled: aiming and effect), features.py (class and race features).
combat_rules.py reads rules text, spell_effects.py holds spell tables and battlemap.py draws the map for Discord.
A new battle mechanic gets its own mixin module, added below.
"""
from .abilities import AbilitiesMixin
from .actions import ActionsMixin
from .base import BattleBase
from .board import BoardMixin
from .charge import ChargeMixin
from .classfeats import ClassFeatsMixin
from .drawing import DrawingMixin
from .constants import ACTIVE, ENDED, SETUP, blank_battle, health_word
from .dispatch import DispatchMixin
from .durations import DurationsMixin
from .editing import EditingMixin
from .effects import EffectsMixin
from .encounters import EncountersMixin
from .feats import FeatsMixin
from .floors import FloorsMixin
from .flow import FlowMixin
from .ground import GroundMixin
from .history import HistoryMixin
from .initiative import InitiativeMixin
from .itemextras import ItemExtrasMixin
from .itempowers import ItemPowersMixin
from .items import ItemsMixin
from .menu import MenuMixin
from .movement import MovementMixin
from .profile import ProfileMixin
from .racefeats import RaceFeatsMixin
from .reactions import ReactionsMixin
from .resolve import ResolveMixin
from .setup import SetupMixin
from .spellitems import SpellItemsMixin
from .spells import SpellsMixin
from .standard import StandardMixin
from .summons import SummonsMixin
from .targeting import TargetingMixin
from .traits import TraitsMixin
from .wondrous import WondrousMixin
from .zones import ZonesMixin


class BattleService(SetupMixin, BoardMixin, DrawingMixin, InitiativeMixin, FlowMixin, ActionsMixin, TargetingMixin, EffectsMixin,
                    SummonsMixin, SpellsMixin, DurationsMixin, StandardMixin, AbilitiesMixin, FeatsMixin, MovementMixin, ZonesMixin,
                    ReactionsMixin, ResolveMixin, MenuMixin, DispatchMixin, ProfileMixin, EditingMixin, EncountersMixin,
                    GroundMixin, ItemsMixin, ItemPowersMixin, ItemExtrasMixin, WondrousMixin, SpellItemsMixin, FloorsMixin, TraitsMixin, ChargeMixin, ClassFeatsMixin, RaceFeatsMixin, HistoryMixin,
                    BattleBase):
    """Combatants, initiative, turns, hit points, effects and the battle log of the one current battle."""


__all__ = ["BattleService", "ACTIVE", "ENDED", "SETUP", "blank_battle", "health_word"]
