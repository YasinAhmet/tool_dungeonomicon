"""What can be done to a character from any character window (roster, players, sheet): open its sheet, rename, move
to another player, archive, export, import HTML sheets, award XP, and the hand-offs to the creation and level-up
wizards. `character_menu()` puts the common ones in a right-click menu.
"""
import inspect
import os
from typing import Iterable, List, Optional

from PySide6.QtWidgets import QApplication, QFileDialog, QMenu, QWidget

from ....core.i18n import tr
from ....core.runtime import rt
from ....rules import export
from ....services import table
from ... import dialogs, notify
from ...errors import guard
from .portrait import edit_portrait

UNASSIGNED = 0          # the players tree's id for "nobody"


# ---------------------------------------------------------------------- windows
def host_of(widget: Optional[QWidget]):
    """The main window's dock host (None in a bare test)."""
    w = widget.window() if widget is not None else None
    if w is not None and hasattr(w, "host"):
        return w.host
    for top in QApplication.topLevelWidgets():
        if hasattr(top, "host"):
            return top.host
    return None


def open_sheet(widget: QWidget, name: str):
    """Select the character and show its full sheet in the Inspector (brought forward, opened when it isn't open)."""
    rt().select_character(name)
    from ..workspace.inspector import inspect_character
    inspect_character(widget, name)


def _call_optional(fn, *args, **options):
    """Call fn with the keyword options it accepts (another window's function may not take them all)."""
    try:
        params = inspect.signature(fn).parameters
        if not any(p.kind == p.VAR_KEYWORD for p in params.values()):
            options = {k: v for k, v in options.items() if k in params}
    except (TypeError, ValueError):
        options = {}
    return fn(*args, **options)


def new_character(parent: QWidget, owner_id: Optional[int] = None, owner_name: Optional[str] = None) -> Optional[str]:
    try:
        from .wizard import open_creation_wizard
    except ImportError:
        notify.warn(tr("The character creation window isn't available yet."))
        return None
    name = guard(open_creation_wizard, parent, owner_id=owner_id, owner_name=owner_name)
    if name:
        rt().select_character(name)
    return name


def quick_character(parent: QWidget, owner_id: Optional[int] = None, owner_name: Optional[str] = None) -> Optional[str]:
    """A ready-made adventurer of any level (race, class, level; the rest decided for it)."""
    from .quick import open_quick_creation
    name = guard(open_quick_creation, parent, owner_id=owner_id, owner_name=owner_name)
    if name:
        rt().select_character(name)
    return name


def level_up(parent: QWidget, name: str, **options):
    """Open the level-up window. options (cls, prev, replay, title) are for re-doing a level in Edit levels."""
    try:
        from .levelup import open_level_up
    except ImportError:
        notify.warn(tr("The level-up window isn't available yet."))
        return None
    return guard(_call_optional, open_level_up, parent, name, **options)


def reset_levels(parent: QWidget, name: str):
    try:
        from .levelup import open_reset_levels
    except ImportError:
        notify.warn(tr("The level-up window isn't available yet."))
        return None
    return guard(open_reset_levels, parent, name)


def edit_creation(parent: QWidget, name: str):
    """RESET ALL with the creation choices (race, ability scores, background) unfolded."""
    try:
        from .levelup import open_reset_levels
    except ImportError:
        notify.warn(tr("The level-up window isn't available yet."))
        return None
    return guard(open_reset_levels, parent, name, True)


# ---------------------------------------------------------------------- roster changes
def rename(parent: QWidget, name: str) -> Optional[str]:
    new = dialogs.ask_text(parent, tr("Rename character"), tr("New name"), name)
    if not new or new == name:
        return None
    was_selected = rt().selected_name == name
    char = guard(rt().characters.rename, name, new)
    if char is None:
        return None
    if was_selected:
        rt().select_character(char.name)
    return char.name


def player_choices() -> List[tuple]:
    """(label, id) for every known player of the selected server, Unassigned first."""
    people = guard(table.players) or {"players": []}
    return [(tr("Unassigned"), UNASSIGNED)] + [(f"{p['name']} ({p['id']})", p["id"]) for p in people["players"]]


def move_to_player(parent: QWidget, name: str) -> bool:
    current = rt().players.owner_of(name) or UNASSIGNED
    got = dialogs.form(parent, tr("Move {0}", name), [
        {"key": "to", "label": tr("Player"), "kind": "select", "options": player_choices(), "value": current}], tr("Move"))
    if got is None:
        return False
    return set_owner(name, got["to"])


def set_owner(name: str, owner_id: Optional[int]) -> bool:
    if not owner_id:
        ok = guard(rt().characters.set_owner, name, None) is not None
        if ok:
            notify.good(tr("{0} → {1}", name, tr("Unassigned")))
        return ok
    owner_name = rt().players.name_of(owner_id)
    ok = guard(rt().characters.set_owner, name, owner_id, owner_name) is not None
    if ok:
        notify.good(tr("{0} → {1}", name, owner_name or str(owner_id)))
    return ok


def archive(parent: QWidget, name: str) -> bool:
    if not dialogs.confirm(parent, tr("Delete {0}? (It will be archived.)", name), tr("Delete")):
        return False
    was_selected = rt().selected_name == name
    if not guard(lambda: rt().characters.archive(name) or True):
        return False
    if was_selected:
        rt().select_character(None)
    notify.info(tr("Archived {0}", name))
    return True


def award_xp(parent: QWidget, names: Iterable[str]) -> bool:
    names = [n for n in names if n]
    if not names:
        return False
    who = names[0] if len(names) == 1 else tr("{0} characters", len(names))
    amount = dialogs.ask_int(parent, tr("Award XP"), tr("XP for {0} (negative takes it away)", who), 0, -10 ** 6, 10 ** 6)
    if not amount:
        return False
    for n in names:
        guard(rt().characters.add_xp, n, amount)
    notify.good(tr("{0} XP → {1}", amount, ", ".join(names)))
    return True


def set_milestone(name: str, on: bool):
    guard(rt().characters.set_milestone, name, on)


# ---------------------------------------------------------------------- files
def export_to(name: str, fmt: str, path: str) -> str:
    """Write the character's sheet in an export format (a key of rules.export.FORMATS). Returns the path."""
    from ....rules.character import Character
    from ....rules.sheet_html import ExportError
    from ....services.common import ServiceError
    char = Character.load(name)
    if not char:
        raise ServiceError(f"Character '{name}' not found.")
    _label, _ext, render = export.FORMATS[fmt]
    try:
        if fmt == "pdf":
            render(char, path)
        else:
            with open(path, "w", encoding="utf-8") as fh:
                fh.write(render(char))
    except ExportError as e:
        raise ServiceError(str(e))
    return path


def export_dialog(parent: QWidget, name: str, fmt: str) -> Optional[str]:
    label, ext, _render = export.FORMATS[fmt]
    folder = os.path.abspath("exports")
    os.makedirs(folder, exist_ok=True)
    path, _f = QFileDialog.getSaveFileName(parent, tr("Export {0}", name), os.path.join(folder, name + ext),
                                           f"{tr(label)} (*{ext})")
    if not path:
        return None
    done = guard(export_to, name, fmt, path)
    if done:
        notify.good(tr("Exported {0} to {1}", name, done))
    return done


def export_menu(parent: QWidget, name_of, menu: Optional[QMenu] = None) -> QMenu:
    """A menu with one entry per export format; name_of() gives the character when an entry is picked."""
    menu = menu or QMenu(parent)
    for fmt, (label, ext, _r) in export.FORMATS.items():
        menu.addAction(f"{tr(label)}  ({ext})", lambda f=fmt: name_of() and export_dialog(parent, name_of(), f))
    return menu


def import_files(paths: Iterable[str]) -> Optional[dict]:
    """Bring exported HTML sheets back in; reports what happened. Returns the service's result."""
    files = []
    for p in paths:
        try:
            with open(p, encoding="utf-8", errors="replace") as fh:
                files.append({"file": os.path.basename(p), "html": fh.read()})
        except OSError as e:
            notify.error(tr("{0}: {1}", os.path.basename(p), str(e)))
    if not files:
        return None
    res = guard(rt().characters.import_html, files)
    if not res:
        return None
    if res["updated"]:
        notify.good(tr("Updated {0}: {1}. Old versions backed up to {2}", len(res["updated"]), ", ".join(res["updated"]),
                       res["backup"]))
    if res["created"]:
        notify.good(tr("New characters: {0}", ", ".join(res["created"])))
    for f in res["failed"]:
        notify.error(tr("{0}: {1}", f["file"], tr(f["error"])))
    first = (res["updated"] or res["created"] or [None])[0]
    if first:
        rt().select_character(first)
    return res


def import_dialog(parent: QWidget) -> Optional[dict]:
    paths, _f = QFileDialog.getOpenFileNames(parent, tr("Import HTML sheets"), os.path.abspath("exports"),
                                             tr("Character sheets (*.html *.htm)"))
    return import_files(paths) if paths else None


# ---------------------------------------------------------------------- levels
def edit_levels(parent: QWidget, name: str):
    """Pick an earlier level and redo it (the level-up feature's Edit levels window, with RESET ALL)."""
    try:
        from .levelup import open_edit_levels
    except ImportError:
        notify.warn(tr("The level-up window isn't available yet."))
        return None
    return guard(open_edit_levels, parent, name)


def revert_level(parent: QWidget, name: str, to: str):
    if dialogs.confirm(parent, tr("Undo the last level-up of {0}? It goes back to {1}.", name, to), tr("Undo level-up")):
        guard(rt().characters.revert_level, name)


# ---------------------------------------------------------------------- menus
def character_menu(parent: QWidget, name: str, menu: Optional[QMenu] = None, sheet: bool = True) -> QMenu:
    """The usual right-click entries for one character."""
    menu = menu or QMenu(parent)
    if sheet:
        menu.addAction(tr("Open sheet"), lambda: open_sheet(parent, name))
        menu.addSeparator()
    menu.addAction(tr("Rename…"), lambda: rename(parent, name))
    menu.addAction(tr("Portrait…"), lambda: edit_portrait(parent, name))
    menu.addAction(tr("Move to player…"), lambda: move_to_player(parent, name))
    menu.addAction(tr("Award XP…"), lambda: award_xp(parent, [name]))
    char = guard(rt().characters.get, name)
    if char is not None:
        act = menu.addAction(tr("Milestone leveling"))
        act.setCheckable(True)
        act.setChecked(bool(char.d["choices"].get("milestone")))
        act.toggled.connect(lambda on: set_milestone(name, on))
    export_menu(parent, lambda: name, menu.addMenu(tr("Export")))
    menu.addSeparator()
    menu.addAction(tr("Delete…"), lambda: archive(parent, name))
    return menu
