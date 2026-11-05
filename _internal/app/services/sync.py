"""Everything personal in one file: export it, bring it to another computer (or keep it as a backup), import it there.

    sync.export_state("D:/me.dmstate")          # -> the manifest written into it
    sync.inspect("D:/me.dmstate")               # -> its manifest, checked (what it holds, modules it wants)
    sync.import_state("D:/me.dmstate")          # replace this computer's state with it now (nothing running reads it)
    sync.stage_import("D:/me.dmstate")          # the editor: replaced at the next start, before anything is read

A .dmstate file is a zip: `manifest.json` plus the files of each part at their place under the data folder
(Documents\\Dungeonomicon, the working folder after userdata.settle()):

    settings      config.json (every setting, the bot token, the sourcebooks switched on, the language...)
    data          data\\ - characters, players, battle and its pictures, encounters, world maps, homebrew rulebooks,
                  custom items / monsters / backgrounds, portraits, player access keys, team inventory and notes,
                  dice history, table feed... - without data\\cache (pictures fetched again) and data\\logs
    session_logs  data\\logs (each run's rolls and log lines)
    layouts       layouts\\ (saved arrangements, and _last.json: the one in use)
    archive       archive\\ (characters taken off the roster)
    modules       modules\\_state.json: which content modules are switched off, which this computer has seen

Not in it: backups\\, cache\\, exports\\ (sheets and modules written out on purpose), logs\\app.log, tools\\
(cloudflared, downloaded again) and the modules themselves - they live in the modules folder next to the program;
the manifest lists the ones that were switched on, so an import can say which are missing here.

An import replaces only the parts the file holds. It checks the file first (only known parts, no path outside the
folder, no programs), keeps the state it replaces as backups\\sync\\before-import-<time>.dmstate (itself importable)
and puts that back if the replacing fails half-way. The running editor's services keep their state in memory and
save it again at exit, so the editor stages the file (pending_import.dmstate) and restarts: main.py applies it right
after start-up, before the runtime reads anything (apply_pending()).
"""
import json
import os
import platform
import shutil
import sys
import tempfile
import time
import zipfile
from typing import Callable, Dict, List, Optional

from ..core import storage
from .common import ServiceError

FORMAT = "dungeonomicon-state"
FORMAT_VERSION = 1
EXTENSION = ".dmstate"
MANIFEST = "manifest.json"
PENDING = "pending_import.dmstate"
BACKUP_FOLDER = os.path.join("backups", "sync")
BACKUP_KEEP = 10
MAX_BYTES = 20 * 1024 ** 3                              # an import never unpacks more than this (a zip bomb)
MODULE_STATE = "_state.json"

# part -> (path under the data folder, file or folder, children of a folder that are not part of it)
PARTS: Dict[str, tuple] = {
    "settings": ("config.json", "file", ()),
    "data": ("data", "dir", ("cache", "logs")),
    "session_logs": ("data/logs", "dir", ()),
    "layouts": ("layouts", "dir", ()),
    "archive": ("archive", "dir", ()),
    "modules": ("modules/" + MODULE_STATE, "file", ()),
}
DEFAULT_PARTS = tuple(PARTS)
PART_NAMES = {"settings": "Settings", "data": "Characters, battle, world, homebrew and the rest of the data folder",
              "session_logs": "Session logs", "layouts": "Window layouts", "archive": "Archived characters",
              "modules": "Which modules are switched on"}
NEVER = (".exe", ".dll", ".bat", ".cmd", ".com", ".ps1", ".vbs", ".scr", ".msi", ".py", ".pyw", ".pyc", ".lnk")

MESSAGES = {
    "not_zip": "This is not a Dungeonomicon state file.",
    "no_manifest": "This file has no manifest: it is not a Dungeonomicon state file.",
    "newer": "This file was made by a newer Dungeonomicon (format {0}): update the program first.",
    "bad_entry": "The file holds something that can't be imported: {0}",
    "too_big": "The file unpacks to more than {0} GB: refused.",
    "nothing": "Nothing to export: the data folder is empty.",
    "write": "Could not write {0}: {1}",
    "read": "Could not read {0}: {1}",
    "failed": "The import failed and the earlier state was put back: {0}",
}


# ====================================================================== where
def _root(root: Optional[str]) -> str:
    return os.path.abspath(root or ".")                  # the data folder: the working folder after userdata.settle()


def _modules_state_file() -> str:
    from ..core import packages                            # (read only: where the switch state lives)
    return os.path.join(packages.installed_dir(), MODULE_STATE)


def _target(part: str, root: str) -> str:
    """Where a part lives on this computer."""
    if part == "modules":
        return _modules_state_file()
    return os.path.join(root, *PARTS[part][0].split("/"))


def _skip_file(rel: str) -> bool:
    """Files never exported: half-written ones, leftovers, pictures made again from the data."""
    name = rel.rsplit("/", 1)[-1]
    if name.endswith((".tmp", EXTENSION)) or name == ".control.json" or name.lower().endswith(NEVER):
        return True
    parts = rel.split("/")
    return len(parts) >= 4 and parts[:2] == ["world", "maps"] and name.startswith("view_") and name.endswith(".png")


def _files(part: str, root: str) -> List[tuple]:
    """[(path on disk, name in the zip)] of a part as it is now."""
    where, kind, skip = PARTS[part]
    path = _target(part, root)
    if kind == "file":
        return [(path, where)] if os.path.isfile(path) else []
    out = []
    if not os.path.isdir(path):
        return out
    for dirpath, dirs, files in os.walk(path):
        rel_dir = os.path.relpath(dirpath, path).replace(os.sep, "/")
        rel_dir = "" if rel_dir == "." else rel_dir + "/"
        if not rel_dir:
            dirs[:] = [d for d in dirs if d not in skip]
        dirs.sort()
        for f in sorted(files):
            rel = rel_dir + f
            if not _skip_file(rel) and not os.path.islink(os.path.join(dirpath, f)):
                out.append((os.path.join(dirpath, f), f"{where}/{rel}"))
    return out


def part_of(name: str) -> Optional[str]:
    """Which part a name in the zip belongs to (the most specific: data/logs/... is session_logs)."""
    best = None
    for part, (where, kind, _skip) in PARTS.items():
        if (name == where if kind == "file" else name.startswith(where + "/")):
            if best is None or len(where) > len(PARTS[best][0]):
                best = part
    return best


# ====================================================================== export
def _modules_on() -> List[dict]:
    try:
        from ..core import packages
        return [{"id": m["id"], "name": m["name"], "version": str(m.get("version") or "")} for m in packages.enabled()]
    except Exception:                                    # noqa: BLE001 - a list for the manifest, never in the way
        return []


def _app_build() -> str:
    if getattr(sys, "frozen", False):
        try:
            return time.strftime("%Y-%m-%d %H:%M", time.localtime(os.path.getmtime(sys.executable)))
        except OSError:
            pass
    return "source"


def export_state(path: str, parts=DEFAULT_PARTS, root: Optional[str] = None,
                 progress: Optional[Callable[[int, int], None]] = None) -> dict:
    """Write the chosen parts into one .dmstate file at `path`; returns the manifest."""
    root = _root(root)
    storage.flush()                                       # the battle, the dice... saved in the background: on disk first
    chosen = [p for p in parts if p in PARTS]
    files = {p: _files(p, root) for p in chosen}
    total = sum(len(v) for v in files.values())
    if not total:
        raise ServiceError(MESSAGES["nothing"])
    manifest = {
        "format": FORMAT, "version": FORMAT_VERSION, "app": "Dungeonomicon", "build": _app_build(),
        "created": time.strftime("%Y-%m-%dT%H:%M:%S"), "computer": platform.node(),
        "parts": {p: {"files": len(files[p]), "bytes": sum(_size(f) for f, _n in files[p])} for p in chosen if files[p]},
        "modules_on": _modules_on(),
    }
    dest = os.path.abspath(path)
    os.makedirs(os.path.dirname(dest), exist_ok=True)
    tmp = dest + ".tmp"
    done = 0
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=6) as z:
            z.writestr(MANIFEST, json.dumps(manifest, indent=2, ensure_ascii=False))
            for p in chosen:
                for src, name in files[p]:
                    try:
                        z.write(src, name)
                    except FileNotFoundError:            # gone meanwhile (an old picture replaced): not needed
                        pass
                    done += 1
                    if progress:
                        progress(done, total)
        os.replace(tmp, dest)
    except OSError as e:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise ServiceError(MESSAGES["write"].format(dest, e))
    return manifest


def _size(path: str) -> int:
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


# ====================================================================== checking a file
def _safe_name(name: str) -> bool:
    if not name or "\\" in name or name.startswith("/") or ":" in name or "\0" in name:
        return False
    bits = name.split("/")
    return all(b not in ("", ".", "..") for b in bits)


def inspect(path: str) -> dict:
    """The manifest of a .dmstate file, checked entry by entry; adds 'missing_modules' (switched on there, not found
    here). Raises ServiceError when the file can't be imported."""
    try:
        with zipfile.ZipFile(path) as z:
            return _check(z)
    except zipfile.BadZipFile:
        raise ServiceError(MESSAGES["not_zip"])
    except OSError as e:
        raise ServiceError(MESSAGES["read"].format(path, e))


def _check(z: zipfile.ZipFile) -> dict:
    try:
        manifest = json.loads(z.read(MANIFEST).decode("utf-8"))
    except KeyError:
        raise ServiceError(MESSAGES["no_manifest"])
    except (ValueError, UnicodeError):
        raise ServiceError(MESSAGES["not_zip"])
    if not isinstance(manifest, dict) or manifest.get("format") != FORMAT:
        raise ServiceError(MESSAGES["not_zip"])
    if not isinstance(manifest.get("version"), int) or manifest["version"] > FORMAT_VERSION:
        raise ServiceError(MESSAGES["newer"].format(manifest.get("version")))
    parts = manifest.get("parts")
    if not isinstance(parts, dict) or not all(p in PARTS for p in parts):
        raise ServiceError(MESSAGES["bad_entry"].format(", ".join(str(p) for p in (parts or {}) if p not in PARTS)
                                                       or MANIFEST))
    total = 0
    for info in z.infolist():
        name = info.filename
        if name == MANIFEST or (info.is_dir() and _safe_name(name.rstrip("/"))):
            continue
        mode = (info.external_attr >> 16) & 0o170000
        if (not _safe_name(name) or mode == 0o120000 or part_of(name) not in parts
                or name.lower().endswith(NEVER)):           # a symbolic link, a program, outside the parts it names
            raise ServiceError(MESSAGES["bad_entry"].format(name))
        total += info.file_size
    if total > MAX_BYTES:
        raise ServiceError(MESSAGES["too_big"].format(MAX_BYTES // 1024 ** 3))
    have = {m["id"] for m in _modules_on_or_off()}
    wanted = manifest.get("modules_on") if isinstance(manifest.get("modules_on"), list) else []
    manifest["missing_modules"] = [m for m in wanted if isinstance(m, dict) and m.get("id") not in have]
    manifest["bytes"] = total
    return manifest


def _modules_on_or_off() -> List[dict]:
    try:
        from ..core import packages
        return packages.all_modules()
    except Exception:                                    # noqa: BLE001
        return []


# ====================================================================== import
def import_state(path: str, root: Optional[str] = None, backup: bool = True) -> dict:
    """Replace this computer's state with the file's, part by part, now. Only safe while nothing running holds the
    state (the editor stages the file instead: stage_import). Returns {"manifest", "backup", "parts"}."""
    root = _root(root)
    path = os.path.abspath(path)
    storage.flush()
    try:
        z = zipfile.ZipFile(path)
    except zipfile.BadZipFile:
        raise ServiceError(MESSAGES["not_zip"])
    except OSError as e:
        raise ServiceError(MESSAGES["read"].format(path, e))
    with z:
        manifest = _check(z)
        parts = list(manifest["parts"])
        incoming = tempfile.mkdtemp(prefix=".sync-in-", dir=root)
        try:
            try:
                for info in z.infolist():                # unpacked beside the folder first: a broken file changes nothing
                    if info.filename == MANIFEST or info.is_dir():
                        continue
                    out = os.path.join(incoming, *info.filename.split("/"))
                    os.makedirs(os.path.dirname(out), exist_ok=True)
                    with z.open(info) as src, open(out, "wb") as f:
                        shutil.copyfileobj(src, f, 1 << 20)
            except (OSError, zipfile.BadZipFile, EOFError) as e:
                raise ServiceError(MESSAGES["read"].format(path, e))
            saved = _backup(root, parts) if backup else None
            try:
                for p in parts:
                    _replace(p, root, incoming)
            except Exception as e:                       # noqa: BLE001 - put the earlier state back, then say why
                if saved:
                    import_state(saved, root, backup=False)
                raise ServiceError(MESSAGES["failed"].format(e))
        finally:
            shutil.rmtree(incoming, ignore_errors=True)
    from ..core import packages
    try:
        packages.forget()                                # the switch state is read again
    except Exception:                                    # noqa: BLE001
        pass
    return {"manifest": manifest, "backup": saved, "parts": parts}


def _backup(root: str, parts: List[str]) -> Optional[str]:
    """The state the import replaces, as a .dmstate of its own in backups/sync (the newest BACKUP_KEEP kept)."""
    folder = os.path.join(root, BACKUP_FOLDER)
    dest = os.path.join(folder, f"before-import-{time.strftime('%Y-%m-%d_%H-%M-%S')}{EXTENSION}")
    try:
        export_state(dest, parts, root)
    except ServiceError as e:
        if str(e) == MESSAGES["nothing"]:                # a fresh computer: nothing to keep
            return None
        raise
    olds = sorted(f for f in os.listdir(folder) if f.startswith("before-import-") and f.endswith(EXTENSION))
    for f in olds[:-BACKUP_KEEP]:
        try:
            os.remove(os.path.join(folder, f))
        except OSError:
            pass
    return dest


def _replace(part: str, root: str, incoming: str) -> None:
    """The part's files on disk go (all of them, also those export leaves out); the file's take their place."""
    where, kind, skip = PARTS[part]
    target = _target(part, root)
    src = os.path.join(incoming, *where.split("/"))
    if kind == "file":
        if os.path.isfile(src):
            os.makedirs(os.path.dirname(target), exist_ok=True)
            os.replace(src, target)
        elif os.path.isfile(target):
            os.remove(target)
        return
    if os.path.isdir(target):
        for name in os.listdir(target):
            if name in skip:
                continue
            p = os.path.join(target, name)
            (shutil.rmtree if os.path.isdir(p) and not os.path.islink(p) else os.remove)(p)
    os.makedirs(target, exist_ok=True)
    if not os.path.isdir(src):
        return
    for name in os.listdir(src):
        if name in skip:                                 # data/logs comes as its own part
            continue
        os.replace(os.path.join(src, name), os.path.join(target, name))


# ====================================================================== the editor: at the next start
restart_after_exit = False                               # set by the editor: main.py starts the program again at exit


def pending_file(root: Optional[str] = None) -> str:
    return os.path.join(_root(root), PENDING)


def pending(root: Optional[str] = None) -> Optional[dict]:
    """The manifest of the import waiting for the next start, None when there is none."""
    path = pending_file(root)
    if not os.path.isfile(path):
        return None
    try:
        return inspect(path)
    except ServiceError:
        return None


def stage_import(path: str, root: Optional[str] = None) -> dict:
    """Check the file and keep a copy to import at the next start; returns its manifest."""
    manifest = inspect(path)
    dest = pending_file(root)
    try:
        shutil.copyfile(path, dest + ".tmp")
        os.replace(dest + ".tmp", dest)
    except OSError as e:
        raise ServiceError(MESSAGES["write"].format(dest, e))
    return manifest


def cancel_pending(root: Optional[str] = None) -> bool:
    path = pending_file(root)
    if os.path.isfile(path):
        os.remove(path)
        return True
    return False


def apply_pending(root: Optional[str] = None) -> Optional[dict]:
    """At start-up, before the runtime reads anything: import the staged file, if there is one. Returns the import's
    result ({"error": text} when it failed - the state is then as it was); the staged file goes either way."""
    path = pending_file(root)
    if not os.path.isfile(path):
        return None
    try:
        return import_state(path, root)
    except ServiceError as e:
        return {"error": str(e)}
    except Exception as e:                               # noqa: BLE001 - the editor still opens
        return {"error": f"{type(e).__name__}: {e}"}
    finally:
        try:
            os.remove(path)
        except OSError:
            pass
