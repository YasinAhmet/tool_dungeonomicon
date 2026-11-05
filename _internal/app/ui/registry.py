"""What the editor offers: every window (panel) and every menu action registers itself here.

Adding a feature never touches the shell. A new package under app/ui/panels/ declares its windows and actions,
and they appear in the Window menu, the layouts and the toolbar on their own:

    from app.ui.registry import panel, action

    @panel("tools.names", "Name generator", "Tools", icon="🎲", area="right")
    class NamesPanel(Panel):
        ...

    @action("characters.new", "New character…", menu="Characters", shortcut="Ctrl+N")
    def new_character(window):
        ...

    @toolbar_widget("discord.servers", order=10)       # a widget on the main toolbar (made once per window)
    def server_picker(window) -> QWidget:
        ...
"""
import importlib
import pkgutil
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional

AREAS = ("left", "right", "top", "bottom", "center")
CATEGORY_ORDER = ["Session", "Characters", "Battle", "Library", "Tools", "Discord", "System"]


@dataclass(frozen=True)
class PanelSpec:
    id: str                      # 'battle.map' - also the window's saved name in layouts
    title: str                   # English; translated when shown
    category: str                # the Window menu group
    factory: Callable            # makes the widget (a Panel subclass)
    icon: str = ""               # an emoji shown before the title
    multi: bool = False          # may be opened several times (e.g. two character sheets side by side)
    area: str = "center"         # where it docks when opened from the menu
    description: str = ""


@dataclass(frozen=True)
class ActionSpec:
    id: str
    title: str
    run: Callable                # run(main_window)
    menu: str = "Tools"          # top-level menu it sits in
    shortcut: str = ""
    icon: str = ""
    toolbar: bool = False        # also a button on the main toolbar
    order: int = 100


@dataclass(frozen=True)
class ToolbarSpec:
    id: str
    factory: Callable            # factory(main_window) -> QWidget
    order: int = 100
    side: str = "left"           # "left" of the toolbar, or "right" (after a spacer)


_panels: Dict[str, PanelSpec] = {}
_actions: Dict[str, ActionSpec] = {}
_toolbar: Dict[str, ToolbarSpec] = {}
_starts: List[Callable] = []
_discovered = False
failures: Dict[str, str] = {}   # module -> traceback of window modules that failed to import (the rest still load)


def panel(id: str, title: str, category: str, *, icon: str = "", multi: bool = False, area: str = "center",
          description: str = ""):
    """Class decorator: register a Panel subclass as an openable window."""
    if area not in AREAS:
        raise ValueError(f"Unknown dock area '{area}'.")

    def deco(cls):
        if id in _panels and _panels[id].factory is not cls:
            raise ValueError(f"Panel id '{id}' is registered twice.")
        _panels[id] = PanelSpec(id, title, category, cls, icon, multi, area, description)
        cls.panel_id = id
        return cls
    return deco


def action(id: str, title: str, *, menu: str = "Tools", shortcut: str = "", icon: str = "", toolbar: bool = False,
           order: int = 100):
    """Function decorator: register `fn(main_window)` as a menu (and optionally toolbar) action."""
    def deco(fn):
        _actions[id] = ActionSpec(id, title, fn, menu, shortcut, icon, toolbar, order)
        return fn
    return deco


def toolbar_widget(id: str, *, order: int = 100, side: str = "left"):
    """Function decorator: `fn(main_window) -> QWidget` adds a widget to the main toolbar."""
    def deco(fn):
        _toolbar[id] = ToolbarSpec(id, fn, order, side)
        return fn
    return deco


def on_start(fn):
    """Function decorator: `fn(main_window)` runs once, shortly after the editor window first shows (a first-run tip)."""
    _starts.append(fn)
    return fn


def start_hooks() -> List[Callable]:
    discover()
    return list(_starts)


def toolbar_widgets() -> List[ToolbarSpec]:
    discover()
    return sorted(_toolbar.values(), key=lambda t: (t.side != "left", t.order, t.id))


def panels() -> List[PanelSpec]:
    discover()
    rank = {c: i for i, c in enumerate(CATEGORY_ORDER)}
    return sorted(_panels.values(), key=lambda p: (rank.get(p.category, 99), p.category, p.title))


def get_panel(panel_id: str) -> Optional[PanelSpec]:
    discover()
    return _panels.get(panel_id)


def actions() -> List[ActionSpec]:
    discover()
    return sorted(_actions.values(), key=lambda a: (a.menu, a.order, a.title))


def discover():
    """Import every module under app.ui.panels once, so their decorators run. A module that fails to import is
    skipped (listed in `failures`) so one broken feature never takes the editor down."""
    global _discovered
    if _discovered:
        return
    _discovered = True
    import traceback
    from . import panels as pkg
    for info in pkgutil.walk_packages(pkg.__path__, pkg.__name__ + ".", onerror=lambda name: failures.setdefault(name, traceback.format_exc())):
        try:
            importlib.import_module(info.name)
        except Exception:
            failures[info.name] = traceback.format_exc()
