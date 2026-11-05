"""The Battle menu: the keys that run a fight from anywhere in the editor (next turn, back, undo, switching the Battle
map between Edit and Play), prepared encounters and placing tokens."""
from ....core.i18n import tr
from ....core.runtime import rt
from ... import notify
from ...errors import guard
from ...registry import action
from .common import next_turn, undo


@action("battle.next", "Next turn", menu="Battle", shortcut="Ctrl+Space|F8", order=10)
def next_(window):
    if rt().battle.state().get("status") == "active":
        next_turn(window)


@action("battle.back", "Previous turn", menu="Battle", shortcut="Ctrl+Shift+Space|Shift+F8", order=11)
def back(window):
    if rt().battle.state().get("status") == "active":
        guard(rt().battle.previous_turn)


@action("battle.undo", "Undo", menu="Battle", shortcut="Ctrl+Z", order=20)
def undo_(_window):
    undo()


@action("battle.redo", "Redo", menu="Battle", shortcut="Ctrl+Y|Ctrl+Shift+Z", order=21)
def redo(_window):
    if not rt().battle.redo_label():
        notify.info(tr("Nothing to redo."))
        return
    what = guard(rt().battle.redo)
    if what:
        notify.good(tr("Redone: {0}", tr(what)))


@action("battle.mode", "Battle map: Edit / Play", menu="Battle", shortcut="Ctrl+E", order=30)
def mode(window):
    dock = window.host.open("battle.map")
    if dock is not None:
        dock.panel.toggle_mode()


@action("battle.place", "Place everyone on the map", menu="Battle", order=31)
def place(_window):
    n = guard(rt().battle.place_unplaced)
    if n is not None:
        notify.good(tr("{0} placed on the map.", n)) if n else notify.info(tr("Everyone is already on the map."))
