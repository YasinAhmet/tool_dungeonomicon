"""Installations (a tab of the Library window): the content modules this program has - install them from .dmmod files (or folders),
export them to share, switch them off or remove them - and custom rulebooks turned into modules and back.

The program itself carries only the SRD 5.1; the books beyond it, monster descriptions and art come as modules."""
import os
import threading
from typing import List, Optional

from PySide6.QtCore import QObject, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFileDialog, QProgressBar, QTreeWidget, QTreeWidgetItem, QWidget

from ....core import events, packages
from ....core.i18n import tr
from ....rules import homebrew as HB
from ....services import modules as svc
from ... import dialogs, notify
from ...errors import guard
from ...panel import Panel
from ...registry import action
from ...widgets.common import FlowLayout, button, card, label, row, stretch, title

FILTER = "Dungeonomicon modules (*.dmmod *.dpmod);;All files (*)"


class _Signals(QObject):
    progress = Signal(str, int, int)
    done = Signal(object, str)                           # (result, error)


def _wrap(*widgets) -> QWidget:
    host = QWidget()
    lay = FlowLayout(host, spacing=4)
    for w in widgets:
        lay.addWidget(w)
    return host


def _size(n: int) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if n < 1024 or unit == "GB":
            return f"{n:.0f} {unit}" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return str(n)


class InstallationsPanel(Panel):
    def build(self):
        lay = self.layout()
        self.setAcceptDrops(True)
        self.sig = _Signals()
        self.sig.progress.connect(self._progress)
        self.sig.done.connect(self._finished)
        self._after = None
        self.busy = False
        self._sizes = {}

        intro = label(tr("The program comes with the SRD 5.1 rules only. Everything else - the rest of the books, "
                         "monster descriptions, tokens and art - is a module: a .dmmod file in the modules folder next "
                         "to the program. Drop files into that folder (or here, or install them below); they travel "
                         "with the program's folder, so a copy of it given to someone brings its modules along."),
                      role="dim", wrap=True)
        self.install_btn = button(tr("Install from file…"), self._install_files, kind="primary",
                                  tip=tr("One or more .dmmod files"))
        self.folder_btn = button(tr("Install from folder…"), self._install_folder,
                                 tip=tr("A module folder (with its module.json)"))
        self.open_btn = button(tr("Open modules folder"), lambda: self._reveal(packages.program_folder()),
                               tip=tr("The modules folder next to the program: drop .dmmod files into it"))
        self.bar = QProgressBar()
        self.bar.hide()
        self.bar_text = label("", role="dim")
        lay.addWidget(card(title(tr("Installations")), intro, _wrap(self.install_btn, self.folder_btn, self.open_btn),
                           self.bar_text, self.bar))

        self.tree = QTreeWidget()
        self.tree.setHeaderLabels([tr("Module"), tr("Version"), tr("Contents"), tr("Status")])
        self.tree.setRootIsDecorated(False)
        self.tree.setColumnWidth(0, 220)
        self.tree.setColumnWidth(1, 60)
        self.tree.setColumnWidth(2, 260)
        self.tree.itemSelectionChanged.connect(self._show)
        self.detail = label("", wrap=True, selectable=True)
        self.toggle_btn = button(tr("Switch off"), self._toggle)
        self.export_btn = button(tr("Export…"), self._export, tip=tr("Save the module as a .dmmod file to keep or share"))
        self.remove_btn = button(tr("Remove"), self._remove, kind="danger")
        self.reveal_btn = button(tr("Show files"), self._reveal_current)
        lay.addWidget(card(title(tr("Modules")), self.tree, self.detail,
                           _wrap(self.toggle_btn, self.export_btn, self.remove_btn, self.reveal_btn)), 1)

        lay.addWidget(card(title(tr("Your rulebooks as modules")),
                           label(tr("A rulebook written in the Library's Books tab can be saved as a module and installed on "
                                    "another computer; a module can come in as a rulebook to edit."), role="dim", wrap=True),
                           _wrap(button(tr("Export a rulebook…"), self._export_book),
                                 button(tr("Import as a rulebook…"), self._import_book))))
        self.on(events.RULES, self.refresh)

    # ------------------------------------------------------------------ showing
    def refresh(self):
        keep = (self._current() or {}).get("id")
        self._sizes = {}
        self.rows = guard(svc.installed) or []
        self.tree.clear()
        for m in self.rows:
            status = tr("on") if m["enabled"] else tr("off")
            if m["origin"] == "bundled":
                status += " · " + tr("comes with the program")
            it = QTreeWidgetItem([tr(m["name"]), m["version"], m["summary"] or "-", status])
            it.setData(0, Qt.UserRole, m["id"])
            it.setToolTip(0, m.get("description") or "")
            if not m["enabled"]:
                for c in range(4):
                    it.setForeground(c, self.palette().placeholderText())
            self.tree.addTopLevelItem(it)
            if m["id"] == keep:
                it.setSelected(True)
        if not self.rows:
            self.detail.setText(tr("No modules yet: install one from a .dmmod file."))
        elif not self.tree.selectedItems():
            self.tree.topLevelItem(0).setSelected(True)
        self._show()

    def _current(self) -> Optional[dict]:
        items = self.tree.selectedItems() if hasattr(self, "tree") else []
        if not items:
            return None
        mid = items[0].data(0, Qt.UserRole)
        return next((m for m in getattr(self, "rows", []) if m["id"] == mid), None)

    def _show(self):
        m = self._current()
        for b in (self.toggle_btn, self.export_btn, self.remove_btn, self.reveal_btn):
            b.setEnabled(bool(m) and not self.busy)
        if not m:
            if getattr(self, "rows", None):
                self.detail.setText(tr("Select a module to see what it holds."))
            return
        self.toggle_btn.setText(tr("Switch off") if m["enabled"] else tr("Switch on"))
        self.remove_btn.setEnabled(m["origin"] != "bundled" and not self.busy)
        lines = [f"<b>{tr(m['name'])}</b> ({m['id']}, {tr('version')} {m['version']})"]
        if m.get("description"):
            lines.append(tr(m["description"]))
        if m["books"]:
            lines.append(tr("Books: {0}", ", ".join(m["books"][:12]) + (" …" if len(m["books"]) > 12 else "")))
        if m["summary"]:
            lines.append(tr("Holds: {0}", m["summary"]))
        if m.get("credits"):
            lines.append(tr("Credits: {0}", m["credits"]))
        if m.get("license"):
            lines.append(tr("License: {0}", m["license"]))
        if m["id"] not in self._sizes:
            self._sizes[m["id"]] = guard(svc.size, m["id"]) or 0
        where = m["source"] if m["origin"] == "folder" else m["folder"]
        lines.append(tr("Folder: {0}", where) + f" ({_size(self._sizes[m['id']])})")
        self.detail.setText("<br>".join(lines))

    # ------------------------------------------------------------------ work in the background
    def _start(self, what: str, work, after=None):
        if self.busy:
            notify.warn(tr("Wait for the module work under way to finish."))
            return
        self.busy = True
        self._after = after
        for b in (self.install_btn, self.folder_btn):
            b.setEnabled(False)
        self._show()
        self.bar.setRange(0, 0)
        self.bar.show()
        self.bar_text.setText(what)

        def run():
            try:
                self.sig.done.emit(work(), "")
            except Exception as e:                    # noqa: BLE001 - shown in the window
                self.sig.done.emit(None, str(e))
        threading.Thread(target=run, daemon=True, name="modules").start()

    def _progress(self, what: str, done: int, total: int):
        if what:
            self.bar_text.setText(what)
        if total:
            self.bar.setRange(0, total)
            self.bar.setValue(done)

    def _finished(self, result, error: str):
        self.busy = False
        self.bar.hide()
        self.bar_text.setText("")
        for b in (self.install_btn, self.folder_btn):
            b.setEnabled(True)
        after, self._after = self._after, None
        if error:
            notify.error(tr(error))
        elif after:
            after(result)
        self.refresh()

    # ------------------------------------------------------------------ installing
    def _install_files(self):
        paths, _f = QFileDialog.getOpenFileNames(self, tr("Install modules"), svc.default_folder(), tr(FILTER))
        if paths:
            self.install(paths)

    def _install_folder(self):
        path = QFileDialog.getExistingDirectory(self, tr("Install a module folder"), svc.default_folder())
        if path:
            self.install([path])

    def install(self, paths: List[str]):
        metas = []
        for p in paths:
            meta = guard(svc.peek, p)
            if meta is None:
                return
            metas.append(meta)
        replacing = [m for m in metas if m["installed"]]
        if replacing:
            text = "\n".join(tr("{0}: version {1} is installed, this is {2}", m["name"], m["installed"], m.get("version") or "1")
                             for m in replacing)
            if not dialogs.confirm(self, text + "\n\n" + tr("Replace them?"), tr("Install modules"), tr("Replace")):
                return
        total = sum(m["bytes"] for m in metas)

        def work():
            return svc.install_many(paths, lambda name, n, t: self.sig.progress.emit(tr("Installing {0}… ({1}/{2} files)", name, n, t), n, t))

        def after(done):
            notify.good(tr("Installed: {0}", ", ".join(f"{m['name']} {m.get('version') or ''}".strip() for m in done)))
        self._start(tr("Installing {0} module(s), {1}…", len(paths), _size(total)), work, after)

    def dragEnterEvent(self, e):                          # noqa: N802 - Qt
        if e.mimeData().hasUrls() and any(u.toLocalFile().lower().endswith(packages.EXTENSIONS) or os.path.isdir(u.toLocalFile())
                                          for u in e.mimeData().urls()):
            e.acceptProposedAction()

    def dropEvent(self, e):                               # noqa: N802 - Qt
        paths = [u.toLocalFile() for u in e.mimeData().urls()
                 if u.toLocalFile().lower().endswith(packages.EXTENSIONS) or os.path.isdir(u.toLocalFile())]
        if paths:
            e.acceptProposedAction()
            self.install(paths)

    # ------------------------------------------------------------------ one module
    def _toggle(self):
        m = self._current()
        if m:
            on = not m["enabled"]
            self._start(tr("Switching {0} on…", tr(m["name"])) if on else tr("Switching {0} off…", tr(m["name"])),
                        lambda: svc.set_enabled(m["id"], on))

    def _export(self):
        m = self._current()
        if not m:
            return
        folder = svc.default_folder()
        os.makedirs(folder, exist_ok=True)
        suggested = os.path.join(folder, f"{m['id']}-{m['version']}{packages.EXTENSION}")
        dest, _f = QFileDialog.getSaveFileName(self, tr("Export {0}", tr(m["name"])), suggested, tr(FILTER))
        if not dest:
            return

        def work():
            return svc.export(m["id"], dest, lambda n, t: self.sig.progress.emit(tr("Exporting… ({0}/{1} files)", n, t), n, t))
        self._start(tr("Exporting {0}…", tr(m["name"])), work,
                    lambda path: notify.good(tr("Saved {0}", os.path.basename(path))))

    def _remove(self):
        m = self._current()
        if not m:
            return
        if m["origin"] == "folder":
            text = tr("Remove {0}? {1} is deleted from the modules folder; its content leaves every list; characters "
                      "keep what they have.", tr(m["name"]), os.path.basename(m["source"]))
        else:
            text = tr("Remove {0}? Its content leaves every list; characters keep what they have. "
                      "Keep a .dmmod file of it to install it again.", tr(m["name"]))
        if not dialogs.confirm(self, text, tr("Remove module"), tr("Remove")):
            return
        self._start(tr("Removing {0}…", tr(m["name"])), lambda: svc.uninstall(m["id"]),
                    lambda _r: notify.good(tr("Removed {0}.", tr(m["name"]))))

    def _reveal_current(self):
        m = self._current() or {}
        source = m.get("source") or m.get("folder")
        self._reveal(os.path.dirname(source) if source and os.path.isfile(source) else m.get("folder"))

    def _reveal(self, folder: Optional[str]):
        if folder:
            os.makedirs(folder, exist_ok=True)
            QDesktopServices.openUrl(QUrl.fromLocalFile(folder))

    # ------------------------------------------------------------------ rulebooks
    def _export_book(self):
        books = guard(HB.books) or []
        if not books:
            notify.info(tr("You have no rulebooks yet: write one in the Library's Books tab."))
            return
        b = dialogs.choose_one(self, tr("Export a rulebook"), [(bk["name"], bk) for bk in books]) if len(books) > 1 else books[0]
        if not b:
            return
        values = dialogs.form(self, tr("Export {0}", b["name"]), [
            {"key": "version", "label": tr("Version"), "value": "1.0"},
            {"key": "author", "label": tr("Credits"), "value": ""}])
        if values is None:
            return
        folder = svc.default_folder()
        os.makedirs(folder, exist_ok=True)
        dest, _f = QFileDialog.getSaveFileName(self, tr("Export {0}", b["name"]),
                                               os.path.join(folder, f"{svc._module_id(b['id'])}{packages.EXTENSION}"), tr(FILTER))
        if not dest:
            return
        path = guard(svc.export_rulebook, b["id"], dest, values.get("version") or "1.0", values.get("author") or "")
        if path:
            notify.good(tr("Saved {0}", os.path.basename(path)))

    def _import_book(self):
        path, _f = QFileDialog.getOpenFileName(self, tr("Import as a rulebook"), svc.default_folder(), tr(FILTER))
        if not path:
            return
        got = guard(svc.import_as_rulebook, path)
        if got:
            text = tr("{0}: {1} entries added.", got["name"], got["added"])
            if got["skipped"]:
                text += "\n" + tr("Left out:") + "\n" + "\n".join(got["skipped"][:20])
                dialogs.info(self, text, tr("Import as a rulebook"))
            else:
                notify.good(text)


@action("library.installations", "Installations…", menu="Settings")
def installations_action(window):
    window.host.open_page("library.rules", "installations")


SRD_NOTICE = ("This work includes material taken from the System Reference Document 5.1 (\"SRD 5.1\") by Wizards of the "
              "Coast LLC and available at https://dnd.wizards.com/resources/systems-reference-document. The SRD 5.1 is "
              "licensed under the Creative Commons Attribution 4.0 International License available at "
              "https://creativecommons.org/licenses/by/4.0/legalcode.")


@action("help.content", "Rules content and licenses…", menu="Help", order=40)
def content_notice(window):
    """What the rules content is and where it comes from: the SRD's attribution, and each installed module's terms."""
    d = dialogs.Dialog(window, tr("Rules content and licenses"), 560)
    d.body.addWidget(label(tr("The program comes with the SRD 5.1 rules only; everything else is a module you install "
                              "(Settings ▸ Installations)."), wrap=True))
    d.body.addWidget(label(SRD_NOTICE, role="dim", wrap=True, selectable=True))
    for m in guard(svc.installed) or []:
        terms = " · ".join(x for x in (m.get("credits"), m.get("license")) if x)
        d.body.addWidget(label(f"<b>{tr(m['name'])}</b> {m['version']}" + (f"<br>{terms}" if terms else ""), wrap=True,
                               selectable=True))
    d.add_button(tr("Installations…"), lambda: (d.accept(), window.host.open_page("library.rules", "installations")))
    d.add_button(tr("Close"), d.accept, default=True)
    d.exec()
