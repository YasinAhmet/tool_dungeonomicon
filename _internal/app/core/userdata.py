"""Where characters, settings and backups live: Documents\\Dungeonomicon (DUNGEONOMICON_HOME overrides it).

    Dungeonomicon\\
        config.json            settings (and the bot token)
        data\\                  characters, players, battle, logs...
        exports\\               sheets exported from the desktop window
        logs\\                  the web panel's log
        backups\\
            characters\\<name>\\  earlier versions of each character (one at most every 10 minutes, the last 40 kept)
            daily\\              a zip of data\\ and config.json, one per day (the last 30 kept)
            imports\\<time>\\     characters as they were before an HTML import replaced them
            deleted\\            characters as they were when deleted

`settle()` runs at start-up: it makes the folder, copies in what the program folder still has (once, never overwriting),
makes it the working folder (every module's relative "data/..." path then lands there) and takes the daily backup.
"""
import os
import shutil
import sys
import time
import zipfile
from typing import Optional

APP_FOLDER = "Dungeonomicon"
OLD_FOLDER = "DungeonPanel"                            # the folder under the program's earlier name, moved over once
MOVE = ("data", "config.json", "exports")             # what used to live next to the program
MOVED_MARK = "_moved_to_documents.txt"
BACKUPS = "backups"
CHARACTER_EVERY, CHARACTER_KEEP, DAILY_KEEP = 600, 40, 30
_last_backup: dict = {}                                # backup folder -> time of its newest copy (seen or taken here)
_settled: Optional[str] = None                         # the folder settle() chose (the old one while it can't be renamed)


def documents() -> str:
    """The user's Documents folder (wherever Windows has it)."""
    if os.name == "nt":
        try:
            import ctypes
            from ctypes import wintypes
            buf = ctypes.create_unicode_buffer(wintypes.MAX_PATH)
            if ctypes.windll.shell32.SHGetFolderPathW(None, 5, None, 0, buf) == 0 and buf.value:   # 5 = CSIDL_PERSONAL
                return buf.value
        except Exception:
            pass
    return os.path.join(os.path.expanduser("~"), "Documents")


def home() -> str:
    if _settled:
        return _settled
    return os.path.abspath(os.environ.get("DUNGEONOMICON_HOME") or os.path.join(documents(), APP_FOLDER))


def _copy_missing(src: str, dst: str) -> int:
    """Copy `src` (file or folder) into `dst`, skipping whatever is already there. Returns files copied."""
    if os.path.isfile(src):
        if os.path.exists(dst):
            return 0
        os.makedirs(os.path.dirname(dst), exist_ok=True)
        shutil.copy2(src, dst)
        return 1
    n = 0
    for name in os.listdir(src):
        if name not in (MOVED_MARK, ".control.json"):
            n += _copy_missing(os.path.join(src, name), os.path.join(dst, name))
    return n


def migrate(program_dir: str, target: str) -> int:
    """Bring the program folder's characters and settings over (once per program folder)."""
    if os.path.normcase(os.path.abspath(program_dir)) == os.path.normcase(target):
        return 0
    mark = os.path.join(program_dir, "data", MOVED_MARK)
    if os.path.exists(mark) or not any(os.path.exists(os.path.join(program_dir, n)) for n in MOVE):
        return 0
    n = sum(_copy_missing(os.path.join(program_dir, name), os.path.join(target, name))
            for name in MOVE if os.path.exists(os.path.join(program_dir, name)))
    os.makedirs(os.path.dirname(mark), exist_ok=True)
    with open(mark, "w", encoding="utf-8") as f:
        f.write(f"Characters and settings now live in {target}\n"
                f"(copied {time.strftime('%Y-%m-%d %H:%M')}). This folder is left as it was, as an extra backup;\n"
                "the program no longer reads it. Delete this file to copy anything missing over again.\n")
    return n


def rename_old(target: str) -> str:
    """Documents\\DungeonPanel (the program's earlier name) becomes Documents\\Dungeonomicon, once. Returns the folder
    to use: the old one while it can't be renamed (the old program still running holds it)."""
    old = os.path.join(documents(), OLD_FOLDER)
    if os.environ.get("DUNGEONOMICON_HOME") or os.path.exists(target) or not os.path.isdir(old):
        return target
    try:
        os.rename(old, target)
        return target
    except OSError as e:
        print(f"Could not rename {old} to {target} ({e}); using {old} this time.", file=sys.stderr)
        return old


def settle(program_dir: str) -> str:
    """Make the Documents folder the working folder; falls back to the program folder if it can't be used."""
    global _settled
    target = _settled = rename_old(home())
    try:
        os.makedirs(target, exist_ok=True)
        migrate(program_dir, target)
        os.chdir(target)
    except OSError as e:
        print(f"Could not use {target} ({e}); keeping data next to the program.", file=sys.stderr)
        os.chdir(program_dir)
        return program_dir
    try:
        daily_snapshot()
    except OSError as e:
        print(f"Daily backup failed: {e}", file=sys.stderr)
    return target


# ---------------------------------------------------------------------- backups
def _stamp() -> str:
    return time.strftime("%Y-%m-%d_%H-%M-%S")


def _prune(folder: str, keep: int) -> None:
    entries = sorted(os.listdir(folder))
    for name in entries[:-keep] if keep else []:
        path = os.path.join(folder, name)
        (shutil.rmtree if os.path.isdir(path) else os.remove)(path)


def backup_character(path: str) -> Optional[str]:
    """Keep the current file of a character before it is overwritten (at most one copy per 10 minutes)."""
    if not os.path.isfile(path):
        return None
    folder = os.path.join(BACKUPS, "characters", os.path.splitext(os.path.basename(path))[0])
    if time.time() - _last_backup.get(os.path.abspath(folder), 0) < CHARACTER_EVERY:
        return None                                    # taken a moment ago (a battle saves a sheet at every hit)
    try:
        os.makedirs(folder, exist_ok=True)
        latest = max((os.path.getmtime(os.path.join(folder, f)) for f in os.listdir(folder)), default=0)
        _last_backup[os.path.abspath(folder)] = latest
        if time.time() - latest < CHARACTER_EVERY:
            return None
        dst = os.path.join(folder, _stamp() + ".json")
        shutil.copy2(path, dst)
        os.utime(dst)                                  # the copy's time is when it was taken
        _last_backup[os.path.abspath(folder)] = time.time()
        _prune(folder, CHARACTER_KEEP)
        return dst
    except OSError:
        return None                                    # a failed backup never stops a save


def keep_copy(path: str, group: str, stamp: Optional[str] = None) -> Optional[str]:
    """Always keep a copy of `path` in backups/<group>/<stamp>/ (before an import replaces it, or a delete)."""
    if not os.path.isfile(path):
        return None
    folder = os.path.join(BACKUPS, group, stamp or _stamp())
    os.makedirs(folder, exist_ok=True)
    dst = os.path.join(folder, os.path.basename(path))
    if not os.path.exists(dst):                        # the same file twice in one go: the first (oldest) copy stays
        shutil.copy2(path, dst)
    return dst


def daily_snapshot(force: bool = False) -> Optional[str]:
    """Zip data/ and config.json into backups/daily/<date>.zip once a day."""
    folder = os.path.join(BACKUPS, "daily")
    os.makedirs(folder, exist_ok=True)
    dst = os.path.join(folder, time.strftime("%Y-%m-%d") + ".zip")
    if (os.path.exists(dst) and not force) or not (os.path.isdir("data") or os.path.isfile("config.json")):
        return None
    tmp = dst + ".tmp"
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED) as z:
        if os.path.isfile("config.json"):
            z.write("config.json")
        for root, dirs, files in os.walk("data"):
            dirs[:] = [d for d in dirs if d != "cache"]
            for f in files:
                if f != ".control.json" and not f.endswith(".tmp"):
                    z.write(os.path.join(root, f))
    os.replace(tmp, dst)
    _prune(folder, DAILY_KEEP)
    return dst
