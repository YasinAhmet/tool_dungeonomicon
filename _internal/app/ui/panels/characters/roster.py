"""Whole-party character actions in the Characters menu: short and long rests for the party (this session's
characters, or those in the battle), importing HTML sheets and exporting the selected character. The Party list itself
is app.ui.panels.characters.players."""
from ....core.i18n import tr
from ....core.runtime import rt
from ....rules import export
from ....services.characters import view
from ... import dialogs, notify
from ...errors import guard_ok
from ...registry import action
from . import char_actions as A


def party_rest(parent, names, kind: str):
    """A short or long rest for several characters at once (the whole party after a fight)."""
    if not names:
        notify.info(tr("No party yet: add characters to the battle or give them to players."))
        return
    if kind == "long_rest" and not dialogs.confirm(parent, tr("Restore {0} fully (HP, spell slots, features)?", ", ".join(names)),
                                                   tr("Long rest")):
        return
    done = [n for n in names if guard_ok(getattr(rt().characters, kind), n)]
    if done:
        notify.good((tr("Short rest: {0}", ", ".join(done)) if kind == "short_rest" else tr("Long rest: {0}", ", ".join(done))))


@action("characters.party_short_rest", "Short rest for the party", menu="Characters", order=50)
def party_short(window):
    party_rest(window, _party(), "short_rest")


@action("characters.party_long_rest", "Long rest for the party…", menu="Characters", order=51)
def party_long(window):
    party_rest(window, _party(), "long_rest")


def _party():
    """The characters in the battle, or else this session's characters, or else every character that has a player."""
    in_battle = [c["character"] for c in rt().battle.view()["combatants"] if c["kind"] == "pc" and c.get("character")]
    names = {c["name"] for c in view.roster()}
    session = [n for n in rt().players.session_party() if n in names]
    return in_battle or session or [c["name"] for c in view.roster() if c.get("owner")]


@action("characters.import_html", "Import HTML sheets…", menu="Characters", order=60)
def import_html(window):
    A.import_dialog(window)


@action("characters.export", "Export selected character…", menu="Characters", order=61)
def export_selected(window):
    name = rt().selected_name
    if not name:
        notify.warn(tr("Select a character first."))
        return
    fmt = dialogs.choose_one(window, tr("Export {0}", name), [(tr(v[0]), k) for k, v in export.FORMATS.items()])
    if fmt:
        A.export_dialog(window, name, fmt)
