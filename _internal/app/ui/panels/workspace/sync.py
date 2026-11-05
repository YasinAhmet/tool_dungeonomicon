"""Settings ▸ Export everything… / Import everything…: the whole personal state in one .dmstate file (services/sync).

Export saves what the editor still holds (the arrangement in use, the settings) and writes the file. Import checks the
file, says what it holds, then stages it and restarts: the state is replaced at the start, before anything reads it.
"""
import os
import time

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QFileDialog

from ....core import userdata
from ....core.i18n import tr
from ....core.runtime import rt
from ....services import sync
from ... import dialogs, notify
from ...errors import guard
from ...registry import action
from ...shell import layouts


def _size(n: int) -> str:
    return f"{n / 1024 ** 2:.1f} MB" if n >= 1024 ** 2 else f"{max(1, n // 1024)} KB"


def _busy(fn, *args, **kwargs):
    QApplication.setOverrideCursor(Qt.WaitCursor)
    try:
        return guard(fn, *args, **kwargs)
    finally:
        QApplication.restoreOverrideCursor()


def save_open_state(window) -> None:
    """What lives only in the editor until it closes: on disk now, so the file has it."""
    if getattr(window, "host", None) is not None:
        guard(layouts.save, layouts.LAST, window.host.save())
    rt().save_config()


@action("workspace.export_state", "Export everything…", menu="Settings", order=900)
def export_everything(window):
    values = dialogs.form(window, tr("Export everything"), [
        {"key": "logs", "label": tr("Session logs"), "kind": "check", "value": True,
         "tip": tr("Each run's rolls and log lines (data\\logs).")},
    ], tr("Choose file…"))
    if values is None:
        return
    default = os.path.join(userdata.documents(), f"Dungeonomicon {time.strftime('%Y-%m-%d')}{sync.EXTENSION}")
    path, _f = QFileDialog.getSaveFileName(window, tr("Export everything"), default, tr("Dungeonomicon state (*.dmstate)"))
    if not path:
        return
    if not path.lower().endswith(sync.EXTENSION):
        path += sync.EXTENSION
    save_open_state(window)
    parts = [p for p in sync.DEFAULT_PARTS if values["logs"] or p != "session_logs"]
    manifest = _busy(sync.export_state, path, parts)
    if manifest is None:
        return
    total = sum(p["bytes"] for p in manifest["parts"].values())
    dialogs.info(window, tr("Saved {0} ({1}).", path, _size(total)) + "\n\n" + tr(
        "Open it on another computer with Settings ▸ Import everything…. It holds your bot token and the players' "
        "access keys: keep it private.") + "\n\n" + tr(
        "Content modules are not in it: copy the modules folder next to the program too."), tr("Export everything"))


def describe(manifest: dict) -> str:
    """What a state file holds, for the confirmation."""
    lines = [tr("Made on {0}, {1}.", manifest.get("computer") or "?", str(manifest.get("created", "")).replace("T", " "))]
    for part, info in manifest["parts"].items():
        lines.append(f"• {tr(sync.PART_NAMES[part])} ({tr('{0} files', info.get('files', 0))})")
    missing = [m.get("name") or m.get("id") for m in manifest.get("missing_modules") or []]
    if missing:
        lines.append("")
        lines.append(tr("Switched on there but not in this computer's modules folder: {0}", ", ".join(missing)))
    return "\n".join(lines)


@action("workspace.import_state", "Import everything…", menu="Settings", order=901)
def import_everything(window):
    waiting = sync.pending()
    if waiting is not None:
        if dialogs.confirm(window, tr("An import is already waiting for the next start:") + "\n\n" + describe(waiting)
                           + "\n\n" + tr("Cancel it?"), tr("Import everything"), tr("Cancel the import")):
            guard(sync.cancel_pending)
            notify.info(tr("The waiting import was cancelled."))
        return
    path, _f = QFileDialog.getOpenFileName(window, tr("Import everything"), userdata.documents(), tr("Dungeonomicon state (*.dmstate)"))
    if not path:
        return
    manifest = _busy(sync.inspect, path)
    if manifest is None:
        return
    text = describe(manifest) + "\n\n" + tr(
        "Replace these on this computer with the file's? What is here now is kept first in backups\\sync (a file you "
        "can import to undo it). Dungeonomicon restarts to do it.")
    if not dialogs.confirm(window, text, tr("Import everything"), tr("Replace")):
        return
    if _busy(sync.stage_import, path) is None:
        return
    if dialogs.confirm(window, tr("Restart Dungeonomicon now to finish the import?"), tr("Import everything"),
                       tr("Restart now")):
        sync.restart_after_exit = True
        window.close()
        QApplication.instance().quit()
    else:
        notify.info(tr("The import is done the next time Dungeonomicon starts."))
