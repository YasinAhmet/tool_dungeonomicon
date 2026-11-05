"""Start the editor: settle the data folder, make the runtime, show the main window, run until it closes.

A loading window (ui/splash.py) shows from the first moment: it follows the start-up - the modules folder, the rules
library, the editor - and gives way to the editor once all of it is ready. The player portal server and its Cloudflare
tunnel come up after that, in the background (the toolbar's 🌐 follows them). When the editor closes, everything it
started stops with it: the portal server, its Cloudflare tunnel, the Discord bot.

The built exe (App.exe) starts the player portal by default (--no-portal leaves it off); from source it's --portal.
"""
import os
import sys
import threading
import traceback

FROZEN = getattr(sys, "frozen", False)                # running as the built .exe
RESTARTED = "--restarted"                              # started again by the program itself (after an import)
EXIT_GRACE = 15                                        # seconds the shutdown may take before the process is ended anyway


def program_dir() -> str:
    return os.path.dirname(sys.executable) if FROZEN else os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def main(argv=None) -> int:
    root = program_dir()
    os.chdir(root)
    from .core import userdata
    home = userdata.settle(root)                       # characters, config, layouts and backups: Documents\Dungeonomicon
    log_path = os.path.join(home, "logs", "app.log")
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    if sys.stdout is None or sys.stderr is None:      # pythonw / the exe: no console, so write to a log file
        sys.stdout = sys.stderr = open(log_path, "a", encoding="utf-8", buffering=1)

    from PySide6.QtCore import QLockFile
    from PySide6.QtWidgets import QApplication
    app = QApplication(argv if argv is not None else sys.argv)
    sys.setswitchinterval(0.001)       # the screen gets Python back within 1 ms while the portal or a worker computes
    app.setApplicationName("Dungeonomicon")
    if FROZEN:                                         # the windows and the taskbar wear the exe's icon
        from PySide6.QtCore import QFileInfo
        from PySide6.QtWidgets import QFileIconProvider
        app.setWindowIcon(QFileIconProvider().icon(QFileInfo(sys.executable)))
    lock = QLockFile(os.path.join(home, ".running.lock"))
    if not lock.tryLock(60000 if RESTARTED in sys.argv else 100):     # (restarted: the old one may still be closing)
        from PySide6.QtWidgets import QMessageBox
        QMessageBox.information(None, "Dungeonomicon", "Dungeonomicon is already running.")
        return 0

    from .ui.splash import Splash
    splash = Splash()
    splash.show()
    from .services import sync
    imported = sync.apply_pending()                    # Settings ▸ Import everything…: before anything reads the state
    args = app.arguments()
    want_portal = "--portal" in args or (FROZEN and "--no-portal" not in args)
    started = False
    try:
        splash.step(4, "Loading the interface...")
        from .ui import errors, theme
        theme.apply(app)
        errors.install()
        splash.step(10, "Starting the engine...")
        from .core.runtime import rt
        rt().capture_errors()
        started = True

        _read_modules_folder(splash)

        splash.step(18, "Reading the rules library...", "Spells, items, monsters")
        from .rules.data import rules
        warm = threading.Thread(target=rules.warm, daemon=True, name="warm-rules")   # the first battle action: no wait
        warm.start()
        splash.wait(lambda: not warm.is_alive(), 120, "", 40)

        splash.step(42, "Building the editor...", "Windows and layouts")
        from .ui.shell.main_window import MainWindow
        splash.step(55, "Building the editor...", "Windows and layouts")
        window = MainWindow()

        splash.step(100, "Ready.")
        window.show()
        window.raise_()
        window.activateWindow()
        splash.close()
        if imported:
            _report_import(imported)
        if want_portal:                                 # in the background: the toolbar's 🌐 shows it coming up
            threading.Thread(target=_start_portal, daemon=True, name="portal-autostart").start()
        rt().autostart()
        return app.exec()
    finally:
        splash.close()
        if started:
            rt().shutdown()                             # the portal server, its tunnel and the bot stop here
        lock.unlock()
        if sync.restart_after_exit:
            _relaunch()
        _exit_watchdog()


def _report_import(result: dict):
    """Say how the import staged before the restart went."""
    from .core.i18n import tr
    from .core.runtime import rt
    if result.get("error"):
        rt().report(tr("The import failed; nothing was changed: {0}", tr(result["error"])), "error")
        return
    m = result["manifest"]
    rt().report(tr("Imported everything from {0} ({1}).", m.get("computer") or "?", m.get("created", "").replace("T", " ")), "good")
    missing = [x.get("name") or x.get("id") for x in m.get("missing_modules") or []]
    if missing:
        rt().report(tr("Switched on there but not in this computer's modules folder: {0}", ", ".join(missing)), "warn")


def _relaunch():
    """Start the program again (after an import was staged), once this one has let go of the lock."""
    import subprocess
    args = [a for a in sys.argv[1:] if a != RESTARTED] + [RESTARTED]
    cmd = [sys.executable] + args if FROZEN else [sys.executable, os.path.abspath(sys.argv[0])] + args
    flags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(subprocess, "CREATE_NEW_PROCESS_GROUP", 0)
    try:
        subprocess.Popen(cmd, cwd=program_dir(), close_fds=True, creationflags=flags)
    except OSError as e:
        print(f"Could not start the program again: {e}", file=sys.stderr)


def _read_modules_folder(splash):
    """The modules folder next to the program: unpack the .dmmod files new there (the first start on a computer may
    take a while for big ones), switch on the books of modules new here. Its window then watches it for changes."""
    from .core.runtime import rt
    from .services import modules as module_svc
    result, now = {}, {"text": ""}

    def read():
        try:
            result.update(module_svc.read_folder(lambda name, n, t: now.update(text=f"{name}: {n} / {t} files")))
        except Exception as e:                          # noqa: BLE001 - the editor still opens without them
            rt().report(f"The modules folder could not be read: {e}", "warn")
    t = threading.Thread(target=read, daemon=True, name="modules-folder")
    t.start()
    splash.wait(lambda: not t.is_alive(), 3600, "Reading the modules folder...", 16, lambda: now["text"])
    if result:
        module_svc.folder_read(result)                  # (a file it can't read is shown by the folder's watcher)


def _start_portal():
    """Serve the player portal, once the editor is open: public through the Cloudflare tunnel when cloudflared is
    already downloaded, else on this PC only (Party ▸ Player portal downloads it and switches to public). The toolbar's
    🌐 follows it; a message says when the players' link is ready."""
    import time
    from .core.runtime import rt
    from .services.portal import tunnel
    from .services.portal.controller import portal
    try:
        portal.start(public=tunnel.find() is not None)
    except Exception as e:                              # the editor is open anyway; the Player portal window can retry
        rt().report(f"The player portal did not start: {e}", "warn")
        return
    if not portal.public:
        return
    deadline = time.monotonic() + 60
    while portal.tunnel.running and not portal.tunnel.url and time.monotonic() < deadline:
        time.sleep(0.25)
    if portal.tunnel.url:
        rt().report("The players' link is ready.", "good")
    elif portal.running and portal.public:
        rt().report("The players' link didn't open: see Party ▸ Player portal.", "warn")


def _exit_watchdog():
    """The editor is closed and the services told to stop: if anything still keeps the process alive after
    EXIT_GRACE seconds (a thread that won't end), end it, so nothing keeps serving in the background."""
    def force():
        os._exit(0)
    t = threading.Timer(EXIT_GRACE, force)
    t.daemon = True                                     # a normal exit doesn't wait for it
    t.start()


def run():
    try:
        sys.exit(main())
    except Exception:
        try:
            from .core import userdata
            path = os.path.join(userdata.home(), "logs", "app.log")
            with open(path, "a", encoding="utf-8") as f:
                traceback.print_exc(file=f)
        except OSError:
            pass
        raise
