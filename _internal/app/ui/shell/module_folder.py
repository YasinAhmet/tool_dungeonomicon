"""Watches the modules folder next to the program while the editor runs: a .dmmod file dropped in is unpacked and its
module shows up everywhere (Sourcebooks, Library, Installations) without a restart; a file taken out takes its module
with it. The unpacking runs on a thread; the rules are read again on the main thread when it is done.

A file still being copied in can't be read yet: it is tried again every few seconds until it can (or, unreadable for a
while without changing, it is reported once).
"""
import os
import threading

from PySide6.QtCore import QFileSystemWatcher, QObject, QTimer, Signal

from ...core import packages
from ...core.i18n import tr
from ...services import modules as svc
from .. import notify

QUIET_MS = 1500                                          # a burst of changes (a copy of many files) is read once
RETRY_MS = 3000                                          # a file still being copied in is looked at again


class ModuleFolderWatch(QObject):
    unpacking = Signal(str)
    done = Signal(object)

    def __init__(self, parent):
        super().__init__(parent)
        self.folder = packages.program_folder()
        try:
            os.makedirs(self.folder, exist_ok=True)
        except OSError:
            pass
        self.watcher = QFileSystemWatcher(self)
        if os.path.isdir(self.folder):
            self.watcher.addPath(self.folder)
        self.watcher.directoryChanged.connect(self.poke)
        self.timer = QTimer(self, singleShot=True, interval=QUIET_MS)
        self.timer.timeout.connect(self._run)
        self.unpacking.connect(lambda name: notify.info(tr("Unpacking {0} from the modules folder…", name)))
        self.done.connect(self._finish)
        self.running = self.again = False
        self.told = set()                                # (file, why) already shown: said once
        self.timer.start(RETRY_MS)                       # once after start-up: shows what the start-up check couldn't read

    def poke(self, *_):
        self.timer.start()

    def _run(self):
        if self.running:
            self.again = True
            return
        self.running = True
        started = set()

        def progress(name, _n, _t):
            if name not in started:
                started.add(name)
                self.unpacking.emit(name)

        def work():
            try:
                result = svc.read_folder(progress)
            except Exception as e:                       # noqa: BLE001 - shown, and tried again on the next change
                result = {"failed": str(e)}
            self.done.emit(result)
        threading.Thread(target=work, daemon=True, name="modules-folder").start()

    def _finish(self, result: dict):
        self.running = False
        if result.get("failed"):
            notify.error(tr("The modules folder could not be read: {0}", result["failed"]))
        else:
            new = svc.folder_read(result)
            if new:
                notify.good(tr("New in the modules folder: {0}", ", ".join(tr(m["name"]) for m in new)))
            elif result.get("changed"):
                notify.info(tr("The modules folder changed: the modules list is up to date."))
            for name, why in (result.get("errors") or {}).items():
                if (name, why) not in self.told:
                    self.told.add((name, why))
                    notify.warn(tr("{0} in the modules folder was skipped: {1}", name, tr(why)))
        if not self.watcher.directories() and os.path.isdir(self.folder):
            self.watcher.addPath(self.folder)            # the folder was made (or made again) meanwhile
        if self.again or result.get("waiting"):
            self.again = False
            self.timer.start(RETRY_MS if result.get("waiting") else 0)
