"""The base of every dockable window.

    @panel("tools.rolls", "Rolls", "Tools", icon="🎲", area="right")
    class RollsPanel(Panel):
        def build(self):                     # make the widgets (self.layout() is a compact QVBoxLayout)
            ...
            self.on(events.DICE, self.refresh)   # re-run refresh whenever dice history changes (unsubscribed on close)
        def refresh(self):                   # fill the widgets from the services; also runs once after build()
            ...
        def save_state(self) -> dict:        # optional: what this window remembers inside a saved layout
        def restore_state(self, state):

`self.rt` is the application runtime (characters, dice, battle, bot...). Service calls can go straight in: whatever
they raise is reported by app.ui.errors (see guard/guarded) instead of crashing the window.
"""
from typing import Callable, Dict, List, Optional, Tuple

from PySide6.QtCore import QEvent, QObject, QTimer
from PySide6.QtWidgets import QVBoxLayout, QWidget

from ..core.runtime import rt
from .errors import guard


class Panel(QWidget):
    panel_id = ""

    def __init__(self, parent=None, instance: str = ""):
        super().__init__(parent)
        self.instance = instance or self.panel_id
        self._unsubscribe: List[Callable[[], None]] = []
        box = QVBoxLayout(self)
        box.setContentsMargins(4, 4, 4, 4)
        box.setSpacing(4)
        subs = self._unsubscribe
        self.destroyed.connect(lambda *_: [u() for u in subs])
        self.build()
        guard(self.refresh)

    @property
    def rt(self):
        return rt()

    # ------------------------------------------------------------------ for subclasses
    def build(self):
        """Create the widgets."""

    def refresh(self):
        """Show the current data."""

    def save_state(self) -> dict:
        return {}

    def restore_state(self, state: dict):
        """Called after the window is made when a saved layout is restored."""

    def title_suffix(self) -> str:
        """Extra words after the window's title on its tab (e.g. the character a sheet shows)."""
        return ""

    # ------------------------------------------------------------------ helpers
    def on(self, topic: str, handler: Callable[[], None]):
        """Call handler (guarded) on the UI thread whenever `topic` is emitted; stops when the window closes. A refresh
        of a window out of sight (a tab behind another) waits until it is shown, and then runs once: a battle changes
        every few seconds, and a sheet or roster rebuilt behind the battle map would hold up the DM's screen."""
        if getattr(handler, "__name__", "") == "refresh":
            fn = lambda: self._refresh_when_seen(handler)            # noqa: E731
        else:
            fn = lambda: guard(handler)                              # noqa: E731
        self._unsubscribe.append(rt().bus.subscribe(topic, fn, key=handler))   # once a drain

    def _refresh_when_seen(self, handler):
        if self.isVisible():
            guard(handler)
            return
        if not hasattr(self, "_late"):
            self._late = []
            self.installEventFilter(_ShownWatch(self))
        if handler not in self._late:
            self._late.append(handler)

    def run(self, fn, *args, **kwargs):
        """Call a service; a failure becomes a notification. Returns the result (None on failure)."""
        return guard(fn, *args, **kwargs)

    def retitle(self):
        """Ask the dock to show title_suffix() again."""
        dock = self.parent()
        while dock is not None and not hasattr(dock, "refresh_title"):
            dock = dock.parent()
        if dock is not None:
            dock.refresh_title()


class _ShownWatch(QObject):
    """Runs a window's waiting refreshes when it is shown (Panel.on)."""
    def eventFilter(self, obj, e):
        if e.type() == QEvent.Show and getattr(obj, "_late", None):
            late, obj._late = list(obj._late), []
            QTimer.singleShot(0, obj, lambda: [guard(h) for h in late])
        return False


class TabbedPanel(Panel):
    """A window made of several pages as tabs (fewer windows to arrange). Each page is a Panel class, made the
    first time its tab is shown; its save_state is kept per page.

        class AudioHub(TabbedPanel):
            def pages(self):
                return [("sound", "🔊 " + tr("Sound"), AudioPanel), ("discord", "🤖 " + tr("Discord bot"), BotPanel)]
    """

    def pages(self) -> List[Tuple[str, str, Callable]]:
        return []

    def build(self):
        from PySide6.QtWidgets import QTabWidget
        self.tabs = QTabWidget()
        self.tabs.setDocumentMode(True)
        self.made: Dict[str, Panel] = {}
        self.waiting: Dict[str, dict] = {}       # saved state of pages not made yet
        self.keys: List[str] = []
        self.factories: Dict[str, Callable] = {}
        self.labels: List[str] = []
        for key, text, factory in self.pages():
            self.keys.append(key)
            self.factories[key] = factory
            self.labels.append(text)
            self.tabs.addTab(QWidget(), text)
        self.tabs.currentChanged.connect(lambda i: guard(self._make, i))
        self.layout().setContentsMargins(0, 2, 0, 0)
        self.layout().addWidget(self.tabs, 1)
        guard(self._make, self.tabs.currentIndex())

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._fit_tabs()

    def _fit_tabs(self):
        """In a narrow window the tabs show their pictures only, the words on hover - not a last tab cut in half."""
        fm = self.tabs.tabBar().fontMetrics()
        short = sum(fm.horizontalAdvance(t) + 30 for t in self.labels) > self.width()
        for i, text in enumerate(self.labels):
            pic, _, words = text.partition(" ")
            want = pic if short and words else text
            if self.tabs.tabText(i) != want:
                self.tabs.setTabText(i, want)
                self.tabs.setTabToolTip(i, words if want == pic else "")

    def _make(self, i: int):
        if not 0 <= i < len(self.keys) or self.keys[i] in self.made:
            return
        key = self.keys[i]
        page = self.factories[key](None, key)
        self.made[key] = page
        if self.waiting.get(key):
            guard(page.restore_state, self.waiting.pop(key))
        blocked = self.tabs.blockSignals(True)
        text, tip = self.tabs.tabText(i), self.tabs.tabToolTip(i)
        self.tabs.removeTab(i)
        self.tabs.insertTab(i, page, text)
        self.tabs.setTabToolTip(i, tip)
        self.tabs.setCurrentIndex(i)
        self.tabs.blockSignals(blocked)

    def page(self, key: str) -> Optional[Panel]:
        """Show a tab (making it if needed) and return its page."""
        if key in self.keys:
            self.tabs.setCurrentIndex(self.keys.index(key))
            guard(self._make, self.keys.index(key))
        return self.made.get(key)

    def save_state(self) -> dict:
        pages = {k: (guard(p.save_state) or {}) for k, p in self.made.items()}
        pages.update({k: v for k, v in self.waiting.items() if k not in pages})
        i = self.tabs.currentIndex()
        return {"tab": self.keys[i] if 0 <= i < len(self.keys) else None, "pages": pages}

    def restore_state(self, state: dict):
        for key, st in (state.get("pages") or {}).items():
            if key in self.made:
                guard(self.made[key].restore_state, st)
            elif key in self.keys and isinstance(st, dict):
                self.waiting[key] = st
        if state.get("tab") in self.keys:
            self.page(state["tab"])


class SectionedPanel(Panel):
    """A window made of several pages on one page, each under a header that folds it away. The first page (the main
    one) takes what the others leave; any other opens at the least height it needs (drag the line between two to share
    it otherwise). A page is made the first time it is unfolded.

        class PartyPanel(SectionedPanel):
            def pages(self):
                return [("party", "👥 " + tr("Party"), PartyListPanel), ("notes", "📝 " + tr("Team notes"), TeamNotesPanel)]
            opened = ("party",)                  # unfolded the first time the window opens
    """
    opened: Tuple[str, ...] = ()

    def pages(self) -> List[Tuple[str, str, Callable]]:
        return []

    def build(self):
        from PySide6.QtCore import Qt
        from PySide6.QtWidgets import QSplitter, QToolButton
        self.split = QSplitter(Qt.Vertical)
        self.split.setChildrenCollapsible(False)
        self.split.setHandleWidth(5)
        self.made: Dict[str, Panel] = {}
        self.waiting: Dict[str, dict] = {}
        self.keys: List[str] = []
        self.factories: Dict[str, Callable] = {}
        self.heads: Dict[str, QToolButton] = {}
        self.holders: Dict[str, QWidget] = {}
        self.open_keys = set(self.opened or ())
        self.last = None                                # the section unfolded last
        self.wraps: Dict[str, QWidget] = {}             # each page as shown (the side ones in a scroll area)
        for key, text, factory in self.pages():
            self.keys.append(key)
            self.factories[key] = factory
            holder = QWidget()
            box = QVBoxLayout(holder)
            box.setContentsMargins(0, 0, 0, 0)
            box.setSpacing(2)
            head = QToolButton()
            head.setText(text)
            head.setCheckable(True)
            head.setToolButtonStyle(Qt.ToolButtonTextBesideIcon)
            head.setArrowType(Qt.DownArrow)
            head.setAutoRaise(True)
            head.setSizePolicy(head.sizePolicy().Policy.Expanding, head.sizePolicy().Policy.Fixed)
            head.setStyleSheet("QToolButton { font-weight: 600; text-align: left; padding: 3px 4px; "
                               "border-bottom: 1px solid rgba(128,128,128,0.35); }")
            head.toggled.connect(lambda on, k=key: guard(self.fold, k, on))
            box.addWidget(head)
            self.heads[key] = head
            self.holders[key] = holder
            self.split.addWidget(holder)
        self.layout().setContentsMargins(0, 2, 0, 0)
        self.layout().addWidget(self.split, 1)
        self.layout().addStretch(0)                     # takes the room left under the headers when all are folded
        if not self.open_keys and self.keys:
            self.open_keys = {self.keys[0]}
        for key in self.keys:
            self._show(key, key in self.open_keys)

    def fold(self, key: str, opened: bool):
        """Unfold (making the page if needed) or fold one section."""
        if key not in self.keys:
            return
        if opened:
            self.open_keys.add(key)
            self.last = key
        else:
            self.open_keys.discard(key)
        self._show(key, opened)
        self._share()

    def _show(self, key: str, opened: bool):
        from PySide6.QtCore import Qt
        head, holder = self.heads[key], self.holders[key]
        blocked = head.blockSignals(True)
        head.setChecked(opened)
        head.setArrowType(Qt.DownArrow if opened else Qt.RightArrow)
        head.blockSignals(blocked)
        if opened and key not in self.made:
            page = guard(self.factories[key], None, key)
            if page is None:
                return
            self.made[key] = page
            from .widgets.common import scroll
            self.wraps[key] = scroll(page) if key != self.keys[0] else page    # (a side section scrolls in its room)
            holder.layout().addWidget(self.wraps[key], 1)
            if self.waiting.get(key):
                guard(page.restore_state, self.waiting.pop(key))
        if key in self.made:
            self.wraps[key].setVisible(opened)
        holder.setMaximumHeight(16777215 if opened else head.sizeHint().height())

    def _share(self):
        """Every open section but the first gets the least height it needs; the first (the window's main page) gets
        the rest - or, folded, the section opened last does."""
        heads = {k: self.heads[k].sizeHint().height() for k in self.keys}
        total = sum(self.split.sizes()) or self.split.height()
        if self.split.maximumHeight() < 16777215:       # was shrunk to its headers: the window's room is what to share
            m = self.layout().contentsMargins()
            total = max(total, self.height() - m.top() - m.bottom()
                        - self.split.handleWidth() * max(0, len(self.keys) - 1))
        opened = [k for k in self.keys if k in self.open_keys]
        side = [k for k in opened if k != self.keys[0]]
        cap = max(90, int(total * 0.5 / max(1, len(side))))      # the side sections together: half the height at most
        need = {}
        for k in self.keys:
            page = self.made.get(k)
            room = page.minimumSizeHint().height() + 6 if k in self.open_keys and page is not None else 0
            need[k] = heads[k] + (min(room, cap) if k in side else room)
        main = self.keys[0] if self.keys and self.keys[0] in self.open_keys else (self.last if self.last in opened else
                                                                                 (opened[-1] if opened else None))
        sizes = {k: need[k] for k in self.keys}
        if main is not None:
            sizes[main] = max(need[main], total - sum(v for k, v in sizes.items() if k != main))
        # all folded: the splitter shrinks to just the headers so they sit at the top (not centred in the window)
        self.split.setMaximumHeight(16777215 if opened else
                                    sum(heads.values()) + self.split.handleWidth() * max(0, len(self.keys) - 1))
        self.split.setSizes([sizes[k] for k in self.keys])

    def page(self, key: str) -> Optional[Panel]:
        """Unfold a section (making it if needed) and return its page."""
        if key in self.keys and key not in self.open_keys:
            self.fold(key, True)
        return self.made.get(key)

    def save_state(self) -> dict:
        pages = {k: (guard(p.save_state) or {}) for k, p in self.made.items()}
        pages.update({k: v for k, v in self.waiting.items() if k not in pages})
        return {"open": [k for k in self.keys if k in self.open_keys], "pages": pages}

    def restore_state(self, state: dict):
        for key, st in (state.get("pages") or {}).items():
            if key in self.made:
                guard(self.made[key].restore_state, st)
            elif key in self.keys and isinstance(st, dict):
                self.waiting[key] = st
        if isinstance(state.get("open"), list):
            self.open_keys = {k for k in state["open"] if k in self.keys}
            for key in self.keys:
                self._show(key, key in self.open_keys)
            self._share()
