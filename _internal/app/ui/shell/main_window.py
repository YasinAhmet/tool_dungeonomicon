"""The editor window: menus and toolbar built from the registry, the dock area, notifications and the status bar.

Window ▸ lists every registered panel by category. Layout ▸ switches between presets and saved layouts; the
arrangement in use when the editor closes comes back at the next start.
"""
import base64
import re
import time
from typing import Dict

from PySide6.QtCore import QByteArray, QObject, QPoint, Qt, QTimer, Signal
from PySide6.QtGui import QAction, QKeySequence
from PySide6.QtWidgets import (QApplication, QFileDialog, QFrame, QLabel, QMainWindow, QMenu, QSizePolicy, QToolBar,
                               QToolButton, QVBoxLayout, QWidget)

from ...core import events, userdata
from ...core.i18n import i18n, tr
from ...core.runtime import rt
from .. import dialogs, notify, registry
from ..errors import guard
from . import layouts
from .docking import DockHost
from .ghostlog import GhostLog, typing_in
from .module_folder import ModuleFolderWatch

APP_TITLE = "Dungeonomicon"


class _Relay(QObject):
    """Carries calls from any thread onto the UI thread."""
    wake = Signal()
    toast = Signal(str, str)


class Toasts(QWidget):
    """Short messages stacked in the bottom-right corner; each fades after a few seconds."""

    def __init__(self, parent: QWidget):
        super().__init__(parent)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self.box = QVBoxLayout(self)
        self.box.setContentsMargins(0, 0, 0, 0)
        self.box.setSpacing(6)
        self.box.addStretch(1)
        self.setFixedWidth(340)

    def show_message(self, message: str, kind: str):
        f = QFrame(self)
        f.setObjectName("toast")
        f.setProperty("kind", kind)
        lay = QVBoxLayout(f)
        lay.setContentsMargins(10, 6, 10, 6)
        lab = QLabel(message)
        lab.setWordWrap(True)
        lay.addWidget(lab)
        f.mousePressEvent = lambda _e: f.deleteLater()
        f.destroyed.connect(lambda *_: QTimer.singleShot(0, self._tidy))
        self.box.addWidget(f)
        while self.box.count() > 6:                      # keep the newest few
            old = self.box.itemAt(1).widget()
            if old:
                old.deleteLater()
            self.box.removeWidget(old)
        QTimer.singleShot(6500 if kind == "error" else 4000, f, f.deleteLater)
        self.show()
        self.reposition()
        QTimer.singleShot(0, self.reposition)                # again once the new message is laid out and has its height
        self.raise_()

    def _tidy(self):
        """A message went: shrink to the ones left, or get out of the way (an empty box over the corner ate the clicks
        meant for the windows under it)."""
        if self.findChildren(QFrame, "toast"):
            self.reposition()
        else:
            self.hide()

    def reposition(self):
        p = self.parentWidget()
        frames = [f for f in self.findChildren(QFrame, "toast") if not f.isHidden()]
        need = sum(max(f.heightForWidth(self.width()), f.sizeHint().height()) for f in frames) + self.box.spacing() * max(0, len(frames) - 1)
        h = max(1, min(420, p.height() - 80, need))          # only as tall as the messages
        self.setGeometry(p.width() - self.width() - 14, p.height() - h - 34, self.width(), h)


class MainWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle(APP_TITLE)
        self.resize(1500, 900)
        self.relay = _Relay()
        self.relay.wake.connect(rt().bus.drain, Qt.QueuedConnection)
        self.relay.toast.connect(self._show_toast, Qt.QueuedConnection)
        rt().bus.attach(self.relay.wake.emit)
        notify.set_sink(self.relay.toast.emit)
        rt().report_hook = lambda message, kind: self.relay.toast.emit(tr(message), kind)
        self.toasts = Toasts(self)
        self.module_watch = ModuleFolderWatch(self)          # .dmmod files dropped next to the program show up at once
        self.host = DockHost(self)
        self.ghost = GhostLog(self)                          # the log, chat and dice over the map: Enter opens it
        self._unsub = [rt().bus.subscribe(events.LANGUAGE, self.rebuild),
                       rt().bus.subscribe(events.LOG, self._log_line)]
        self._seen_log = rt().log_count
        self.status = QLabel("")
        self.status.setProperty("role", "dim")
        self.statusBar().addWidget(self.status, 1)
        self.history = []                                    # (time, kind, message) of the toasts shown
        self.history_btn = QToolButton()
        self.history_btn.setText("🕘")
        self.history_btn.setAutoRaise(True)
        self.history_btn.setToolTip(tr("The last messages (they fade after a few seconds)"))
        self.history_btn.clicked.connect(self._history_menu)
        self.statusBar().addPermanentWidget(self.history_btn)
        self._build_chrome()
        self._restore_window()
        for fn in registry.start_hooks():
            QTimer.singleShot(800, self, lambda fn=fn: guard(fn, self))
        for module, trace in registry.failures.items():
            rt().log(f"[ERROR] The windows in {module} couldn't load:\n{trace}")
            notify.error(tr("Some windows couldn't load ({0}); see the Console.", module.rsplit(".", 2)[-2]))

    # ------------------------------------------------------------------ chrome
    def _build_chrome(self):
        self.menuBar().clear()
        self._build_menus()
        for tb in self.findChildren(QToolBar):
            self.removeToolBar(tb)
            tb.deleteLater()
        tb = QToolBar(tr("Toolbar"))
        tb.setObjectName("main-toolbar")
        tb.setMovable(False)
        self.addToolBar(Qt.TopToolBarArea, tb)
        for a in registry.actions():
            if a.toolbar:
                tb.addAction(self._action(a))
        right = False
        for t in registry.toolbar_widgets():
            if t.side == "right" and not right:
                spacer = QWidget()
                spacer.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
                tb.addWidget(spacer)
                right = True
            w = guard(t.factory, self)
            if w is not None:
                tb.addWidget(w)

    def _action(self, a: registry.ActionSpec) -> QAction:
        act = QAction(f"{a.icon} {tr(a.title)}".strip(), self)
        if a.shortcut:                                       # "Ctrl+Space|F8": either key; they work in floating windows too
            act.setShortcuts([QKeySequence(k.strip()) for k in a.shortcut.split("|")])
            act.setShortcutContext(Qt.ApplicationShortcut)
        act.triggered.connect(lambda _c=False, a=a: guard(a.run, self))
        return act

    def _build_menus(self):
        mb = self.menuBar()
        file = mb.addMenu(tr("File"))
        file.addAction(tr("Open data folder"), lambda: self._open_folder(userdata.home()))
        file.addSeparator()
        file.addAction(tr("Quit"), self.close, QKeySequence("Ctrl+Q"))
        shell_menus = ("File", "Window", "Layout", "Settings", "Help")
        menus: Dict[str, QMenu] = {"File": file}
        for a in registry.actions():                         # actions name their menu; new menus appear on their own
            if a.menu not in menus and a.menu not in shell_menus:
                menus[a.menu] = mb.addMenu(tr(a.menu))
        win = mb.addMenu(tr("Window"))
        win.aboutToShow.connect(lambda: self._fill_window_menu(win))
        lay = mb.addMenu(tr("Layout"))
        lay.aboutToShow.connect(lambda: self._fill_layout_menu(lay))
        settings = menus["Settings"] = mb.addMenu(tr("Settings"))
        lang = settings.addMenu(tr("Language"))
        for code, name in i18n.languages():
            act = lang.addAction(name, lambda c=code: guard(rt().set_language, c))
            act.setCheckable(True)
            act.setChecked(code == i18n.language)
        help_ = menus["Help"] = mb.addMenu(tr("Help"))
        for a in registry.actions():
            if a.menu in ("Window", "Layout"):              # those two are rebuilt each time they open
                continue
            menus[a.menu].addAction(self._action(a))
        help_.addAction(tr("Keyboard shortcuts"), self._shortcuts, QKeySequence("F1"))
        help_.addAction(tr("About"), lambda: dialogs.info(self, tr(
            "Dungeonomicon - an all-in-one Dungeon Master helper for D&D 5e with Discord bot support.\n\n"
            "Open windows from the Window menu and drag their tabs to dock them anywhere: beside another window, "
            "as a tab, floating, or pinned to a side bar. Save arrangements under Layout."), APP_TITLE))

    def _fill_window_menu(self, menu: QMenu):
        menu.clear()
        by: Dict[str, list] = {}
        for p in registry.panels():
            by.setdefault(p.category, []).append(p)
        for cat, specs in by.items():
            menu.addSection(tr(cat))
            for p in specs:
                open_now = self.host.open_instances(p.id)
                text = f"{p.icon} {tr(p.title)}".strip()
                if p.multi:
                    act = menu.addAction(tr("{0} (new)", text), lambda pid=p.id: self.host.open(pid))
                else:
                    act = menu.addAction(text, lambda pid=p.id: self._toggle(pid))
                    act.setCheckable(True)
                    act.setChecked(any(self.host.shown(i) for i in open_now))
                if p.description:
                    act.setToolTip(tr(p.description))
        menu.setToolTipsVisible(True)

    def _toggle(self, panel_id: str):
        if any(self.host.shown(i) for i in self.host.open_instances(panel_id)):      # (a tucked one: brought back)
            self.host.close(panel_id)
        else:
            self.host.open(panel_id)

    def _fill_layout_menu(self, menu: QMenu):
        menu.clear()
        menu.addSection(tr("Presets"))
        for name, p in layouts.PRESETS.items():
            act = menu.addAction(tr(name), lambda n=name: self.apply_preset(n))
            act.setToolTip(tr(p["description"]))
        mine = layouts.saved()
        if mine:
            menu.addSection(tr("My layouts"))
            for name in mine:
                menu.addAction(name, lambda n=name: self.apply_saved(n))
        menu.addSeparator()
        menu.addAction(tr("Save layout as…"), self.save_layout_as)
        if mine:
            dele = menu.addMenu(tr("Delete layout"))
            for name in mine:
                dele.addAction(name, lambda n=name: self._delete_layout(n))
        menu.addSeparator()
        menu.addAction(tr("Export layout…"), self._export_layout)
        menu.addAction(tr("Import layout…"), self._import_layout)
        menu.addSeparator()
        menu.addAction(tr("Close all windows"), self.host.close_all)
        menu.setToolTipsVisible(True)

    # ------------------------------------------------------------------ layouts
    def apply_preset(self, name: str):
        self.host.build(layouts.PRESETS[name]["steps"])
        self.statusBar().showMessage(tr("Layout: {0}", tr(name)), 3000)

    def apply_saved(self, name: str):
        data = layouts.load(name)
        if not data or not self.host.restore(data):
            notify.warn(tr("The layout '{0}' couldn't be opened.", name))
            return
        self.statusBar().showMessage(tr("Layout: {0}", name), 3000)

    def save_layout_as(self):
        name = dialogs.ask_text(self, tr("Save layout"), tr("Name of this layout"))
        if name:
            layouts.save(name, self.host.save())
            notify.good(tr("Layout '{0}' saved.", name))

    def _delete_layout(self, name: str):
        if dialogs.confirm(self, tr("Delete the layout '{0}'?", name)):
            layouts.delete(name)

    def _export_layout(self):
        path, _ = QFileDialog.getSaveFileName(self, tr("Export layout"), "layout.json", "JSON (*.json)")
        if path:
            layouts.export_to(path, "Exported", self.host.save())

    def _import_layout(self):
        path, _ = QFileDialog.getOpenFileName(self, tr("Import layout"), "", "JSON (*.json)")
        if path:
            name = guard(layouts.import_from, path)
            if name:
                self.apply_saved(name)

    def _restore_window(self):
        geo = rt().settings.get("window", {}).get("geometry")
        if geo:
            self.restoreGeometry(QByteArray(base64.b64decode(geo)))
        last = layouts.load(layouts.LAST)
        if not (last and self.host.restore(last)):
            self.apply_preset(layouts.DEFAULT)

    def rebuild(self):
        """Make every window again (after the language changed), keeping the arrangement."""
        state = self.host.save()
        self._build_chrome()
        self.host.restore(state)
        self.ghost.deleteLater()                             # (its words in the new language)
        self.ghost = GhostLog(self)

    def _shortcuts(self):
        keys = [(a.shortcut.replace("|", " / "), tr(a.title)) for a in registry.actions() if a.shortcut]
        keys += [("Ctrl+Q", tr("Quit")), ("F1", tr("Keyboard shortcuts"))]
        battle = [("Ctrl+E", tr("Battle map: switch between Edit and Play")),
                  ("D / H", tr("Battle map: damage or heal the selected token (Enter: damage · Shift+Enter: heal)")),
                  ("Enter", tr("The log, chat and dice over the map: say something to the table, roll (2d6+3) or "
                               "type a /command; Esc closes it")),
                  ("Enter / Esc", tr("Battle map: confirm or cancel aiming; Enter first takes the target the aim bar offers "
                                     "(right-click cancels too)")),
                  ("1 … 9", tr("Battle map (Play): the play bar's first nine actions, in their order")),
                  ("Del", tr("Battle map: remove the selected creature, drawing or spell area")),
                  ("R / Shift+R", tr("Battle map: turn the selected symbol or picture")),
                  ("O", tr("Battle map: open or close the selected door")),
                  ("Page Up / Down", tr("Battle map: move the selected picture up or down its layer")),
                  (tr("Double-click"), tr("Battle map: a token's damage box (Edit) or play it (Play)")),
                  (tr("Right-click"), tr("A token or a row of the order: its menu (several rows: for all of them)"))]
        rows = "".join(f"<tr><td style='padding:2px 14px 2px 0'><b>{k}</b></td><td>{t}</td></tr>" for k, t in keys + battle)
        d = dialogs.Dialog(self, tr("Keyboard shortcuts"), 620)
        lab = QLabel(f"<table>{rows}</table>")
        lab.setWordWrap(True)
        d.body.addWidget(lab)
        d.add_button(tr("Close"), d.accept, kind="primary", default=True)
        d.exec()

    # ------------------------------------------------------------------ messages
    def _show_toast(self, message: str, kind: str):
        self.history.append((time.strftime("%H:%M:%S"), kind, message))
        del self.history[:-60]
        self.history_btn.setText(f"🕘 {len(self.history)}")
        if kind == "error":
            self.history_btn.setProperty("role", "bad")
            self.history_btn.style().polish(self.history_btn)
        self.toasts.show_message(message, kind)

    def _history_menu(self):
        """The messages that went by (toasts fade after a few seconds): newest first; a click copies one."""
        m = QMenu(self)
        if not self.history:
            m.addAction(tr("No messages yet.")).setEnabled(False)
        mark = {"error": "❌", "warn": "⚠", "good": "✅"}
        for when, kind, text in reversed(self.history[-30:]):
            short = text.replace("\n", " ")
            m.addAction(f"{when}  {mark.get(kind, 'ℹ')}  " + (short[:110] + "…" if len(short) > 110 else short),
                        lambda t=text: QApplication.clipboard().setText(t))
        m.addSeparator()
        m.addAction(tr("Open the log"), lambda: self.ghost.open_log("console"))
        self.history_btn.setProperty("role", "")
        self.history_btn.style().polish(self.history_btn)
        m.exec(self.history_btn.mapToGlobal(self.history_btn.rect().topLeft()) - QPoint(0, m.sizeHint().height()))

    def _log_line(self):
        lines = rt().log_since(self._seen_log)
        self._seen_log = rt().log_count
        for line in reversed(lines):                         # the latest that isn't a debug note, without its [TAGS]
            if line.startswith("[DEBUG]"):
                continue
            tags = re.match(r"(?:\[[A-Z]+\]\s*)+", line)
            text = line[tags.end():] if tags else line
            bad = bool(tags) and any(t in tags.group(0) for t in ("ERROR", "WARN"))
            self.status.setText(("⚠ " if bad else "") + tr(text.replace("\n", " "))[:200])
            self.status.setToolTip(line)                     # the whole line, tags and all
            break

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self.toasts.reposition()
        if self.ghost.isVisible():
            self.ghost.place()

    def keyPressEvent(self, e):
        """Enter that nothing else took (no text box has the keyboard, the map isn't aiming): the ghost log opens."""
        if e.key() in (Qt.Key_Return, Qt.Key_Enter) and not e.modifiers() and not typing_in(QApplication.focusWidget()):
            self.ghost.open_log()
            return
        super().keyPressEvent(e)

    @staticmethod
    def _open_folder(path: str):
        import os
        guard(os.startfile, path)

    # ------------------------------------------------------------------ closing
    def closeEvent(self, e):
        guard(layouts.save, layouts.LAST, self.host.save())
        rt().settings.setdefault("window", {})["geometry"] = base64.b64encode(bytes(self.saveGeometry())).decode("ascii")
        for u in self._unsub:
            u()
        rt().bus.attach(None)
        notify.set_sink(None)
        self.host.close_all()
        super().closeEvent(e)
