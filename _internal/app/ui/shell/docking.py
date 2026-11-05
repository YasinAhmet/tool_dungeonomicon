"""The dock host: opens registered panels as dockable windows and saves/restores their arrangement.

Every window can be dragged anywhere: docked left/right/top/bottom of another, tabbed with it, floated as its own
window, or pinned to a side bar (auto-hide). The arrangement - which windows, where, their sizes and each window's
own state (Panel.save_state) - is a plain dict, so layouts are just JSON files.
"""
import base64
from typing import Dict, List, Optional

import PySide6QtAds as ads
from PySide6.QtCore import QByteArray
from PySide6.QtWidgets import QSplitter

from ...core.i18n import tr
from .. import registry
from ..errors import guard

AREA = {"left": ads.LeftDockWidgetArea, "right": ads.RightDockWidgetArea, "top": ads.TopDockWidgetArea,
        "bottom": ads.BottomDockWidgetArea, "center": ads.CenterDockWidgetArea}
LAYOUT_VERSION = 4                  # 4: Inspector + sheet, Library + installations, Party on one page, no Log window; older layouts don't fit


def configure():
    """Docking behaviour; must run before the first CDockManager is made."""
    M = ads.CDockManager
    for name in ("OpaqueSplitterResize", "FocusHighlighting", "DockAreaHasCloseButton", "DockAreaHasUndockButton",
                 "DockAreaHasTabsMenuButton", "AllTabsHaveCloseButton", "MiddleMouseButtonClosesTab",
                 "DockAreaDynamicTabsMenuButtonVisibility", "FloatingContainerHasWidgetTitle", "EqualSplitOnInsertion"):
        flag = getattr(M.eConfigFlag, name, None)
        if flag is not None:
            M.setConfigFlag(flag, True)
    for name in ("AutoHideFeatureEnabled", "DockAreaHasAutoHideButton", "AutoHideCloseButtonCollapsesDock",
                 "AutoHideCloseOnOutsideMouseClick"):
        flag = getattr(M.eAutoHideFlag, name, None)
        if flag is not None:
            M.setAutoHideConfigFlag(flag, True)


class PanelDock(ads.CDockWidget):
    """A dock holding one Panel; its tab shows the panel's icon, title and title_suffix()."""

    def __init__(self, manager, spec: registry.PanelSpec, panel, instance: str):
        super().__init__(manager, "")
        self.spec, self.panel, self.instance = spec, panel, instance
        self.tucked = False                                 # hidden for now (DockHost.tuck): still open, its place kept
        self.setObjectName(instance)
        mode = ads.CDockWidget.eInsertMode                  # a panel that fits itself (the map shrinks for its bar) gets no scroll area
        self.setWidget(panel, mode.ForceNoScrollArea if getattr(panel, "fits_itself", False) else mode.AutoScrollArea)
        self.setFeature(ads.CDockWidget.DockWidgetFeature.DockWidgetDeleteOnClose, True)
        self.setMinimumSizeHintMode(ads.CDockWidget.eMinimumSizeHintMode.MinimumSizeHintFromContent) \
            if hasattr(ads.CDockWidget, "eMinimumSizeHintMode") else None
        self.refresh_title()

    def refresh_title(self):
        suffix = ""
        try:
            suffix = self.panel.title_suffix()
        except Exception:
            pass
        text = f"{self.spec.icon} {tr(self.spec.title)}".strip() + (f" · {suffix}" if suffix else "")
        self.setWindowTitle(text)
        self.setTabToolTip(tr(self.spec.description) if self.spec.description else text)


class DockHost:
    def __init__(self, window):
        configure()
        self.window = window
        self.manager = ads.CDockManager(window)
        self.docks: Dict[str, PanelDock] = {}

    # ------------------------------------------------------------------ opening and closing
    def _instance(self, spec: registry.PanelSpec, wanted: Optional[str]) -> str:
        if wanted:
            return wanted
        if not spec.multi:
            return spec.id
        n = 1
        while f"{spec.id}#{n}" in self.docks:
            n += 1
        return f"{spec.id}#{n}"

    def open(self, panel_id: str, area: Optional[str] = None, near: Optional[str] = None, instance: Optional[str] = None,
             state: Optional[dict] = None, focus: bool = True, split: bool = False) -> Optional[PanelDock]:
        """Open a window (or bring a single-instance one forward). `near` is an open window's instance: the new one
        docks beside it (`area` left/right/top/bottom) or as a tab with it (`area` 'center'). With no `near` it becomes
        a tab of a window already open (see tab_target) instead of a new area - fewer areas, less clutter - unless
        `split` (a preset being built)."""
        spec = registry.get_panel(panel_id)
        if spec is None:
            return None
        if not spec.multi and spec.id in self.docks and not instance:
            dock = self.docks[spec.id]
            if focus:
                self.raise_dock(dock)
            return dock
        inst = self._instance(spec, instance)
        panel = guard(spec.factory, None, inst)
        if panel is None:
            return None
        if state:
            guard(panel.restore_state, state)
        dock = PanelDock(self.manager, spec, panel, inst)
        self.docks[inst] = dock
        forget = lambda *_a, i=inst, d=dock: self.docks.pop(i) if self.docks.get(i) is d else None
        dock.closed.connect(lambda *_a, d=dock: None if d.tucked else forget())   # (a tucked one stays open)
        dock.destroyed.connect(forget)                 # (a replaced dock's late signals leave its successor alone)
        dock.viewToggled.connect(lambda on, d=dock: setattr(d, "tucked", False) if on else None)
        target = self.docks.get(near) if near else None
        where = AREA.get(area or spec.area, ads.CenterDockWidgetArea)
        if target is None and not split and not instance:
            target = self.tab_target(spec, dock)
            if target is not None:
                where = ads.CenterDockWidgetArea
        if target is not None and target is not dock and target.dockAreaWidget() is not None:
            self.manager.addDockWidget(where, dock, target.dockAreaWidget())
        elif where == ads.CenterDockWidgetArea and self._center_area() is not None:
            self.manager.addDockWidget(where, dock, self._center_area())
        else:
            self.manager.addDockWidget(where, dock)
        if focus:
            self.raise_dock(dock)
        return dock

    def tab_target(self, spec: registry.PanelSpec, new=None) -> Optional[PanelDock]:
        """The open window a newly opened one joins as a tab: one that docks on the same side (the Duel joins the
        Inspector), else a side window (for a side window), else the widest window (for a centre one). None when there is
        no such window (a side window with nothing at the sides gets an area of its own)."""
        docked = [d for d in self.docks.values() if d is not new and d.dockAreaWidget() is not None and not d.isFloating()
                  and not d.isClosed()]
        same = [d for d in docked if d.spec.area == spec.area]
        if same:
            return same[-1]
        if spec.area == "center":
            area = self._center_area()
            return next((d for d in docked if d.dockAreaWidget() is area), None)
        sides = [d for d in docked if d.spec.area in ("right", "left")]
        return sides[-1] if sides else None

    def _center_area(self):
        """Where 'center' windows go when no neighbour is named: the area of the widest open window."""
        areas = [d.dockAreaWidget() for d in self.docks.values() if d.dockAreaWidget() is not None and not d.isFloating()
                 and not d.isClosed()]
        return max(areas, key=lambda a: a.width() * a.height(), default=None)

    def open_page(self, panel_id: str, page: str) -> Optional[PanelDock]:
        """Open a window made of tabs (TabbedPanel) on one of its pages."""
        dock = self.open(panel_id)
        if dock is not None and hasattr(dock.panel, "page"):
            dock.panel.page(page)
        return dock

    def raise_dock(self, dock: PanelDock):
        if dock.tucked or dock.isClosed() or (dock.isAutoHide() if hasattr(dock, "isAutoHide") else False):
            dock.tucked = False
            dock.toggleView(True)
        dock.setAsCurrentTab()
        dock.raise_()

    def tuck(self, dock: PanelDock) -> bool:
        """Hide a window for now (the Inspector when nothing is selected): its room goes to its neighbours, and it stays
        open - raise_dock brings it back where it was. Not a tab behind another or one pinned to a side bar (they take
        no room)."""
        if dock.tucked or dock.isClosed() or not dock.isCurrentTab() or (dock.isAutoHide() if hasattr(dock, "isAutoHide") else False):
            return False
        dock.tucked = True
        dock.toggleView(False)
        return True

    def shown(self, instance: str) -> bool:
        """Open and not tucked away."""
        dock = self.docks.get(instance)
        return dock is not None and not dock.tucked

    def close(self, instance: str):
        dock = self.docks.get(instance)
        if dock:
            dock.closeDockWidget()

    def close_all(self):
        for inst in list(self.docks):
            dock = self.docks.pop(inst, None)
            if dock is not None:
                self.manager.removeDockWidget(dock)
                dock.deleteLater()

    def open_instances(self, panel_id: str) -> List[str]:
        return [i for i, d in self.docks.items() if d.spec.id == panel_id]

    # ------------------------------------------------------------------ layouts
    def save(self) -> dict:
        return {"version": LAYOUT_VERSION,
                "docks": [{"instance": i, "panel": d.spec.id, "state": guard(d.panel.save_state) or {}, "tucked": d.tucked}
                          for i, d in self.docks.items()],
                "ads": base64.b64encode(bytes(self.manager.saveState())).decode("ascii")}

    def restore(self, layout: dict) -> bool:
        """Replace every open window with the layout's. False when it can't be used (then nothing is open)."""
        if not layout or layout.get("version") != LAYOUT_VERSION:
            return False
        self.close_all()
        for d in layout.get("docks", []):
            dock = self.open(d["panel"], instance=d["instance"], state=d.get("state"), focus=False)
            if dock is not None:
                dock.tucked = bool(d.get("tucked"))       # (hidden again by the state below: still open)
        try:
            ok = self.manager.restoreState(QByteArray(base64.b64decode(layout.get("ads", ""))))
        except (ValueError, TypeError):
            ok = False
        for dock in self.docks.values():
            if dock.tucked and not dock.isClosed():
                dock.tucked = False
        return bool(ok) and bool(self.docks)

    def build(self, steps: List[tuple]):
        """Open a preset's windows in order: (panel_id, area[, near_panel[, size]]). Missing panels are skipped;
        `size` is the share (0-1) of its splitter the window's area gets."""
        self.close_all()
        sized = []
        for step in steps:
            panel_id, area = step[0], step[1]
            near = step[2] if len(step) > 2 else None
            dock = self.open(panel_id, area, near if near in self.docks else None, focus=False, split=True)
            if dock is not None and len(step) > 3 and step[3]:
                sized.append((dock, step[3]))
        from PySide6.QtCore import QTimer                  # sizes only mean something once Qt has laid the docks out
        QTimer.singleShot(0, self.manager, lambda: self._apply_shares([(d, s) for d, s in sized if self.docks.get(d.instance) is d]))
        for dock in self.docks.values():                  # the first tab of each area is the one shown
            area = dock.dockAreaWidget()
            if area is not None and area.currentIndex() != 0 and area.dockWidget(0) is not None:
                area.setCurrentIndex(0)

    @staticmethod
    def _apply_shares(sized: List[tuple]):
        """Give each sized window's area its share of its splitter; the other areas split what is left."""
        by_splitter: Dict[int, tuple] = {}
        for dock, share in sized:
            area = dock.dockAreaWidget()
            child, parent = area, area.parentWidget() if area else None
            while parent is not None and not isinstance(parent, QSplitter):
                child, parent = parent, parent.parentWidget()
            if parent is None or parent.indexOf(child) < 0:
                continue
            by_splitter.setdefault(id(parent), (parent, {}))[1][parent.indexOf(child)] = share
        for splitter, shares in by_splitter.values():
            sizes = splitter.sizes()
            if len(sizes) < 2:
                continue
            total = sum(sizes) or 1000
            fixed = {i: int(total * min(0.9, s)) for i, s in shares.items()}
            rest_old = sum(v for i, v in enumerate(sizes) if i not in fixed) or 1
            left = max(0, total - sum(fixed.values()))
            splitter.setSizes([fixed[i] if i in fixed else int(left * v / rest_old) for i, v in enumerate(sizes)])
