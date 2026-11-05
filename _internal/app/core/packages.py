"""Content modules on disk: where they live, installing, exporting, removing and switching them off. No game rules here:
app.rules.modules reads what a module holds, app.services.modules keeps everything in step after a change.

A module is a folder with a module.json; shared as one file, it is that folder zipped (a .dmmod file):

    <id>/
        module.json       {"id", "name", "version", "description", "credits", "license",
                           "kind": "module" | "book" | "assets", ...}
        <kind>.json       content (spells.json, monsters.json...; see app.rules.modules)
        lore.json         {monster id: description} (book modules)
        locale/*.csv      translations, the shape of app/locale/content/*.csv (key,<language>...)
        img/...           pictures, the layout of the project's img folder (bestiary/tokens/MM/Goblin.webp...)
        tokens/ icons/ art/   a module's own creature tokens and spell/item icons
        assets/<kind>/    the program's pictures and sounds: icons, items, props, sounds, worldart, portraits
                          (app.core.assets). An "assets" module holds only these (and img/): no rules content, no book.

Modules are read from (a later one replaces an earlier one of the same id):
    app/rules/data/modules/            the ones that come with the program (none now; read-only, they can be switched off)
    DUNGEONOMICON_MODULES              only when that is set (tests, tools/split_content.py --verify): a folder of
                                       unpacked modules, installed there by install(). Documents\\Dungeonomicon\\modules
                                       is NOT read: installs made there before the modules folder are left alone. It
                                       holds the modules' state file only (switched off, seen).
    <program>/modules/                the modules folder next to App.exe: .dmmod files (or module folders) dropped in
                                       there. It travels with the program folder - a copy of that folder given to someone
                                       else brings its modules along. Its .dmmod files are unpacked into
                                       <home>/cache/modules/<file name>/ to be read (sync_folder(), at start-up and
                                       whenever the folder changes); a file taken out takes its module with it.

Modules are data only - JSON, CSV, text, pictures and sounds. Nothing in one is ever run, so a module from anywhere is safe to
install: the zip is checked for paths that climb out of its folder and for any other kind of file.
"""
import json
import os
import re
import shutil
import sys
import threading
import time
import zipfile
from typing import Callable, Dict, List, Optional

EXTENSION = ".dmmod"
EXTENSIONS = (EXTENSION, ".dpmod")                    # .dpmod: modules from before the rename, installed the same
FORMAT = 1                                            # module.json "format": what this program reads
ID_RX = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.\-]{0,63}$")
ALLOWED = {".json", ".csv", ".md", ".txt", ".webp", ".png", ".jpg", ".jpeg", ".gif", ".ogg", ".wav", ".flac", ".mp3"}
STORED = {".webp", ".png", ".jpg", ".jpeg", ".gif", ".ogg", ".flac", ".mp3"}      # already compressed: zipped as they are
MAX_FILES = 200_000
MAX_BYTES = 8 * 1024 ** 3
STATE = "_state.json"
STAMP = ".source.json"                                # in an unpacked copy: the size and time of the file it came from
SETTLE = 10                                           # seconds a dropped file must stay unreadable before it is an error
BUNDLED =os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "rules", "data", "modules")

_lock = threading.RLock()
_cache: Optional[List[dict]] = None
_listeners: List[Callable[[], None]] = []
_unreadable: Dict[str, tuple] = {}                     # dropped file -> ((size, time), first failure, message)
_sync_lock = threading.RLock()                         # one unpacking of the modules folder at a time


class PackageError(Exception):
    """A module can't be installed, exported or removed; the message says why (English, translated where shown)."""


# ====================================================================== where
def installed_dir() -> str:
    """Where install() unpacks to and the state file lives. Its modules are read only when DUNGEONOMICON_MODULES
    names it (read_installed())."""
    env = os.environ.get("DUNGEONOMICON_MODULES")
    if env:
        return os.path.abspath(env)
    from .userdata import home
    return os.path.join(home(), "modules")


def read_installed() -> bool:
    """Are installed_dir()'s modules read? Only when DUNGEONOMICON_MODULES is set: the program's modules come from the
    modules folder alone."""
    return bool(os.environ.get("DUNGEONOMICON_MODULES"))


def program_folder() -> str:
    """The modules folder next to the program (App.exe's folder; the project folder when run from source).
    DUNGEONOMICON_FOLDER overrides it."""
    env = os.environ.get("DUNGEONOMICON_FOLDER")
    if env:
        return os.path.abspath(env)
    if getattr(sys, "frozen", False):
        base = os.path.dirname(sys.executable)
    else:
        base = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return os.path.join(base, "modules")


def unpacked_dir() -> str:
    """Where the modules folder's .dmmod files are unpacked to be read: a cache, made again from the files when gone."""
    from .userdata import home
    return os.path.join(home(), "cache", "modules")


def folder_writable() -> bool:
    """Can installs go into the modules folder? (Not when the program sits somewhere read-only, like Program Files.)"""
    folder = program_folder()
    try:
        os.makedirs(folder, exist_ok=True)
        probe = os.path.join(folder, f".probe-{os.getpid()}")
        with open(probe, "w"):
            pass
        os.remove(probe)
        return True
    except OSError:
        return False


def _is_pack(name: str) -> bool:
    return name.lower().endswith(EXTENSIONS) and not name.startswith((".", "_"))


def _stamp_of(path: str) -> dict:
    st = os.stat(path)
    return {"size": st.st_size, "mtime": int(st.st_mtime)}


def _fresh(path: str, folder: str) -> bool:
    """Is `folder` the unpacked copy of the file at `path` as it is now?"""
    try:
        return _read(os.path.join(folder, STAMP)) == _stamp_of(path)
    except OSError:
        return False


def _read(path: str, default=None):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _state() -> dict:
    s = _read(os.path.join(installed_dir(), STATE), {})
    return s if isinstance(s, dict) else {}


def _save_state(s: dict) -> None:
    from .storage import write_json
    write_json(os.path.join(installed_dir(), STATE), s)


def valid_meta(meta) -> bool:
    return isinstance(meta, dict) and isinstance(meta.get("id"), str) and bool(ID_RX.match(meta["id"])) \
        and isinstance(meta.get("name"), str) and bool(meta["name"].strip())


# ====================================================================== reading
def _folder_entries() -> List[tuple]:
    """[(source, folder)] for the modules folder: a module folder is read where it is; a .dmmod file through its
    unpacked copy, once there is one that matches the file."""
    root, cache = program_folder(), unpacked_dir()
    out = []
    try:
        names = sorted(os.listdir(root))
    except OSError:
        return out
    for name in names:
        path = os.path.join(root, name)
        if name.startswith((".", "_")):
            continue
        if os.path.isdir(path):
            out.append((path, path))
        elif _is_pack(name) and _fresh(path, os.path.join(cache, name)):
            out.append((path, os.path.join(cache, name)))
    return out


def _scan() -> List[dict]:
    disabled = set(_state().get("disabled") or [])
    found: Dict[str, dict] = {}

    def add(origin, source, folder):
        meta = _read(os.path.join(folder, "module.json"))
        if not valid_meta(meta):
            return
        shadows = found.get(meta["id"], {}).get("folder") if origin != "bundled" else None
        found[meta["id"]] = {**meta, "folder": folder, "source": source, "origin": origin, "shadows": shadows,
                             "enabled": meta["id"] not in disabled}

    for origin, root in (("bundled", BUNDLED), ("installed", installed_dir() if read_installed() else "")):
        if not os.path.isdir(root):
            continue
        for name in sorted(os.listdir(root)):
            folder = os.path.join(root, name)
            if not name.startswith((".", "_")) and os.path.isdir(folder):
                add(origin, folder, folder)
    for source, folder in _folder_entries():
        add("folder", source, folder)
    return sorted(found.values(), key=lambda m: (m.get("order", 50), m["name"].lower()))


def all_modules() -> List[dict]:
    """Every module found, enabled or not: its module.json plus 'folder' (where it is read from), 'source' (the
    .dmmod file or folder it came from), 'origin' ('bundled' | 'installed' | 'folder'), 'enabled' and 'shadows' (the
    folder of a module of the same id it replaces). Sorted by name."""
    global _cache
    with _lock:
        if _cache is None:
            _cache = _scan()
        return list(_cache)


def enabled() -> List[dict]:
    return [m for m in all_modules() if m["enabled"]]


def get(module_id: str) -> dict:
    m = next((m for m in all_modules() if m["id"] == module_id), None)
    if not m:
        raise PackageError(f"There is no module '{module_id}'.")
    return m


def folders(sub: str = "") -> List[str]:
    """The folders of the enabled modules (or their `sub` folder: 'img', 'locale'), those that exist."""
    out = []
    for m in enabled():
        p = os.path.join(m["folder"], sub) if sub else m["folder"]
        if os.path.isdir(p):
            out.append(p)
    return out


def size_of(folder: str) -> int:
    total = 0
    for root, _dirs, files in os.walk(folder):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total


# ====================================================================== keeping in step
def on_change(fn: Callable[[], None]) -> None:
    """Call fn() after a module is installed, removed, switched on or off (app.services.modules re-reads the rules)."""
    if fn not in _listeners:
        _listeners.append(fn)


def forget() -> None:
    """Read the module folders again next time (a change made outside the program)."""
    global _cache
    with _lock:
        _cache = None


def _changed() -> None:
    forget()
    for fn in list(_listeners):
        fn()


def set_enabled(module_id: str, on: bool) -> None:
    get(module_id)
    with _lock:
        s = _state()
        off = [i for i in (s.get("disabled") or []) if i != module_id]
        s["disabled"] = off if on else off + [module_id]
        _save_state(s)
    _changed()


# ====================================================================== installing
def _check_name(rel: str) -> str:
    """A path inside a module, '/'-separated; refuses anything that could land outside its folder or isn't data."""
    rel = rel.replace("\\", "/")
    parts = [p for p in rel.split("/") if p not in ("", ".")]
    if not parts or rel.startswith("/") or any(p == ".." or ":" in p for p in parts):
        raise PackageError(f"The module holds a file outside its folder ({rel}).")
    ext = os.path.splitext(parts[-1])[1].lower()
    if ext not in ALLOWED:
        raise PackageError(f"The module holds a file of a kind modules can't have ({parts[-1]}).")
    return "/".join(parts)


def peek(path: str) -> dict:
    """module.json of a .dmmod file or a module folder, without installing it; adds 'files' and 'bytes'."""
    if os.path.isdir(path):
        meta = _read(os.path.join(path, "module.json"))
        if not valid_meta(meta):
            raise PackageError("That folder isn't a module (no valid module.json in it).")
        n = sum(len(f) for _r, _d, f in os.walk(path))
        return {**meta, "files": n, "bytes": size_of(path)}
    try:
        with zipfile.ZipFile(path) as z:
            prefix, members = _members(z)
            meta = json.loads(z.read(prefix + "module.json").decode("utf-8"))
    except (OSError, zipfile.BadZipFile, KeyError, ValueError, UnicodeDecodeError):
        raise PackageError("That file isn't a module (a .dmmod file with a module.json).")
    if not valid_meta(meta):
        raise PackageError("The module's module.json has no valid id and name.")
    return {**meta, "files": len(members), "bytes": sum(i.file_size for i in members)}


def _members(z: zipfile.ZipFile):
    """(prefix, [file entries]): module.json at the top, or inside one top folder ('<id>/module.json')."""
    files = [i for i in z.infolist() if not i.is_dir()]
    names = {i.filename.replace("\\", "/") for i in files}
    if "module.json" in names:
        prefix = ""
    else:
        tops = {n.split("/", 1)[0] for n in names}
        prefix = next(iter(tops)) + "/" if len(tops) == 1 and next(iter(tops)) + "/module.json" in names else None
        if prefix is None:
            raise KeyError("module.json")
    return prefix, [i for i in files if i.filename.replace("\\", "/").startswith(prefix)]


def install(path: str, progress: Optional[Callable[[int, int], None]] = None) -> dict:
    """Unpack a .dmmod file or a module folder into installed_dir() (replacing one of the same id there): for tests and
    tools, which set DUNGEONOMICON_MODULES - without it the program doesn't read what this installs (the program's
    installs go into the modules folder: add_to_folder()). Returns its module.json plus 'replaced' (the version it
    replaced, or None)."""
    meta = peek(path)
    if int(meta.get("format", 1) or 1) > FORMAT:
        raise PackageError(f"'{meta['name']}' was made for a newer version of the program.")
    if meta["files"] > MAX_FILES or meta["bytes"] > MAX_BYTES:
        raise PackageError(f"'{meta['name']}' is too big to be a module.")
    root = installed_dir()
    os.makedirs(root, exist_ok=True)
    mid = meta["id"]
    incoming = os.path.join(root, f".incoming-{mid}-{int(time.time() * 1000)}")
    try:
        if os.path.isdir(path):
            if os.path.normcase(os.path.abspath(path)) == os.path.normcase(os.path.join(root, mid)):
                raise PackageError(f"'{meta['name']}' is already installed from there.")
            _copy_folder(path, incoming, progress)
        else:
            _unzip(path, incoming, progress)
        with _lock:
            old = next((m for m in all_modules() if m["id"] == mid and m["origin"] == "installed"), None)
            target = os.path.join(root, mid)
            if old and os.path.normcase(old["folder"]) != os.path.normcase(target):
                target = old["folder"]                                   # an older install under another folder name
            trash = None
            if os.path.exists(target):
                trash = os.path.join(root, f".old-{mid}-{int(time.time() * 1000)}")
                os.replace(target, trash)
            os.replace(incoming, target)
            if trash:
                shutil.rmtree(trash, ignore_errors=True)
    finally:
        if os.path.exists(incoming):
            shutil.rmtree(incoming, ignore_errors=True)
    _changed()
    return {**meta, "replaced": (old or {}).get("version", "?") if old else None}


def _unzip(path: str, dst: str, progress) -> None:
    with zipfile.ZipFile(path) as z:
        prefix, members = _members(z)
        total = len(members)
        for n, info in enumerate(members, 1):
            rel = _check_name(info.filename.replace("\\", "/")[len(prefix):])
            out = os.path.join(dst, *rel.split("/"))
            os.makedirs(os.path.dirname(out), exist_ok=True)
            with z.open(info) as src, open(out, "wb") as f:
                shutil.copyfileobj(src, f, 1 << 20)
            if progress and (n % 200 == 0 or n == total):
                progress(n, total)


def unzip_to(path: str, dst: str) -> None:
    """Unpack a .dmmod file into a folder (checked like an install)."""
    _unzip(path, dst, None)


def _files_of(folder: str) -> List[str]:
    out = []
    for root, dirs, files in os.walk(folder):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d != "__pycache__"]
        for f in files:
            rel = os.path.relpath(os.path.join(root, f), folder).replace(os.sep, "/")
            if not f.startswith(".") and rel != STATE:
                out.append(rel)
    return sorted(out)


def _copy_folder(src: str, dst: str, progress) -> None:
    files = _files_of(src)
    for rel in files:
        _check_name(rel)
    for n, rel in enumerate(files, 1):
        out = os.path.join(dst, *rel.split("/"))
        os.makedirs(os.path.dirname(out), exist_ok=True)
        shutil.copy2(os.path.join(src, *rel.split("/")), out)
        if progress and (n % 200 == 0 or n == len(files)):
            progress(n, len(files))


def uninstall(module_id: str) -> dict:
    """Remove an installed module, or take one out of the modules folder (a bundled one can only be switched off).
    Returns its module.json."""
    m = get(module_id)
    if m["origin"] == "bundled":
        raise PackageError(f"'{m['name']}' comes with the program: switch it off instead.")
    if m["origin"] == "folder":                       # its file (or folder) leaves the modules folder, its copy goes too
        with _sync_lock:
            _remove_path(m["source"])
            if os.path.normcase(m["folder"]) != os.path.normcase(m["source"]):
                _remove_path(m["folder"])
    else:
        root = installed_dir()
        trash = os.path.join(root, f".old-{module_id}-{int(time.time() * 1000)}")
        os.replace(m["folder"], trash)                # gone from the list at once, even if deleting the files takes a while
        shutil.rmtree(trash, ignore_errors=True)
    with _lock:
        s = _state()
        if module_id in (s.get("disabled") or []):
            s["disabled"] = [i for i in s["disabled"] if i != module_id]
            _save_state(s)
    _changed()
    return m


# ====================================================================== the modules folder
def _check_pack(path: str) -> dict:
    """peek() plus every check an install makes, without unpacking anything."""
    meta = peek(path)
    if int(meta.get("format", 1) or 1) > FORMAT:
        raise PackageError(f"'{meta['name']}' was made for a newer version of the program.")
    if meta["files"] > MAX_FILES or meta["bytes"] > MAX_BYTES:
        raise PackageError(f"'{meta['name']}' is too big to be a module.")
    if os.path.isdir(path):
        for rel in _files_of(path):
            _check_name(rel)
    else:
        with zipfile.ZipFile(path) as z:
            prefix, members = _members(z)
            for info in members:
                _check_name(info.filename.replace("\\", "/")[len(prefix):])
    return meta


def _unpack_into_cache(path: str, progress) -> dict:
    """Unpack one file of the modules folder into its cached copy (replacing an older copy). Returns its module.json."""
    meta = _check_pack(path)
    cache = unpacked_dir()
    os.makedirs(cache, exist_ok=True)
    stamp = _stamp_of(path)
    incoming = os.path.join(cache, f".incoming-{int(time.time() * 1000)}")
    target = os.path.join(cache, os.path.basename(path))
    try:
        _unzip(path, incoming, progress)
        with open(os.path.join(incoming, STAMP), "w", encoding="utf-8") as f:
            json.dump(stamp, f)
        trash = None
        if os.path.exists(target):
            trash = os.path.join(cache, f".old-{int(time.time() * 1000)}")
            os.replace(target, trash)
        os.replace(incoming, target)
        if trash:
            shutil.rmtree(trash, ignore_errors=True)
    finally:
        if os.path.exists(incoming):
            shutil.rmtree(incoming, ignore_errors=True)
    return meta


def sync_folder(progress: Optional[Callable[[str, int, int], None]] = None) -> dict:
    """Bring the unpacked copies in step with the modules folder: unpack its new or changed .dmmod files, drop the
    copies of files taken out. progress(file name, files done, files in it). Returns {'changed': the module list is
    different now, 'unpacked': [module.json], 'dropped': [file names], 'waiting': [files still being copied in],
    'errors': {file name: why it can't be read}}. Doesn't tell the listeners: the caller does (on its own thread)."""
    out = {"changed": False, "unpacked": [], "dropped": [], "waiting": [], "errors": {}}
    with _sync_lock:
        before = all_modules()                            # what the program shows now (a file taken out is still in it)
        root, cache = program_folder(), unpacked_dir()
        try:
            os.makedirs(root, exist_ok=True)
        except OSError:
            pass
        try:
            names = os.listdir(root)
        except OSError:
            names = []
        files = {n: os.path.join(root, n) for n in names if _is_pack(n) and os.path.isfile(os.path.join(root, n))}
        for n in names:                                   # what an interrupted install or removal left
            if n.startswith((".incoming-", ".old-")):
                _remove_left(os.path.join(root, n))
        for name, path in sorted(files.items()):
            if _fresh(path, os.path.join(cache, name)):
                _unreadable.pop(path, None)
                continue
            try:
                stamp = tuple(_stamp_of(path).values())
            except OSError:
                continue
            seen = _unreadable.get(path)
            if seen and seen[0] == stamp and seen[2]:             # unreadable as it is: said once, not tried again
                out["errors"][name] = seen[2]
                continue
            try:
                out["unpacked"].append(_unpack_into_cache(path, (lambda n, t, name=name: progress(name, n, t)) if progress else None))
                _unreadable.pop(path, None)
            except (PackageError, OSError, zipfile.BadZipFile, ValueError) as e:
                # A file still being copied in can't be read yet: wait while it keeps changing, or for SETTLE seconds.
                first = seen[1] if seen and seen[0] == stamp else time.time()
                if time.time() - first < SETTLE:
                    _unreadable[path] = (stamp, first, "")
                    out["waiting"].append(name)
                else:
                    msg = str(e) if isinstance(e, PackageError) else f"{name} isn't a module file that can be read ({e})."
                    _unreadable[path] = (stamp, first, msg)
                    out["errors"][name] = msg
        if os.path.isdir(cache):
            for name in os.listdir(cache):
                full = os.path.join(cache, name)
                if name.startswith("."):                          # what an interrupted unpacking left
                    shutil.rmtree(full, ignore_errors=True)
                elif name not in files:
                    shutil.rmtree(full, ignore_errors=True)
                    out["dropped"].append(name)
        after = _scan()
        key = lambda ms: [(m["id"], str(m.get("version")), m["folder"], m["origin"]) for m in ms]   # noqa: E731
        out["changed"] = key(before) != key(after)
    return out


def take_new_from_folder() -> List[dict]:
    """The modules of the modules folder this computer hasn't had before (each is told once), so the caller can
    switch their books on - as an install does. One that stands in for a copy already installed here isn't new."""
    with _lock:
        s = _state()
        seen = set(s.get("seen") or [])
        new = [m for m in all_modules() if m["origin"] == "folder" and m["id"] not in seen]
        if new:
            s["seen"] = sorted(seen | {m["id"] for m in new})
            _save_state(s)
        return [m for m in new if not m["shadows"]]


def add_to_folder(path: str, progress: Optional[Callable[[int, int], None]] = None) -> dict:
    """Install a .dmmod file or a module folder by copying it into the modules folder (so it travels with the
    program); a module of the same id there (or in DUNGEONOMICON_MODULES) gives way to it. Returns its module.json plus
    'replaced' (the version it replaced, or None)."""
    meta = _check_pack(path)
    root = program_folder()
    os.makedirs(root, exist_ok=True)
    mid = meta["id"]
    name = os.path.basename(os.path.normpath(path)) if os.path.isfile(path) else mid
    if os.path.isfile(path) and not name.lower().endswith(EXTENSIONS):
        name += EXTENSION
    dest = os.path.join(root, name)
    if os.path.normcase(os.path.abspath(path)) == os.path.normcase(os.path.abspath(dest)):
        raise PackageError(f"'{meta['name']}' is already in the modules folder.")
    with _sync_lock:
        old = [m for m in all_modules() if m["id"] == mid and m["origin"] in ("folder", "installed")]
        part = os.path.join(root, f".incoming-{int(time.time() * 1000)}")
        try:
            if os.path.isdir(path):
                _copy_folder(path, part, progress)
            else:
                _copy_file(path, part, progress)
            for m in old:                                  # the same module under another name, or in Documents
                if os.path.normcase(m["source"]) != os.path.normcase(dest):
                    _remove_path(m["source"])
            if os.path.exists(dest):
                _remove_path(dest)
            os.replace(part, dest)
        finally:
            if os.path.exists(part):
                _remove_left(part)
        if os.path.isfile(dest):
            _unpack_into_cache(dest, progress)
    _changed()
    return {**meta, "replaced": str(old[0].get("version") or "1") if old else None}


def _copy_file(src: str, dst: str, progress) -> None:
    total, done = os.path.getsize(src), 0
    with open(src, "rb") as a, open(dst, "wb") as b:
        while True:
            chunk = a.read(8 << 20)
            if not chunk:
                break
            b.write(chunk)
            done += len(chunk)
            if progress:
                progress(done >> 20, max(total >> 20, 1))       # in MB: the bar moves for a big file too
    shutil.copystat(src, dst)


def _remove_left(path: str) -> None:
    if os.path.isdir(path):
        shutil.rmtree(path, ignore_errors=True)
    else:
        try:
            os.remove(path)
        except OSError:
            pass


def _remove_path(path: str) -> None:
    if os.path.isdir(path):
        trash = os.path.join(os.path.dirname(path), f".old-{os.path.basename(path)}-{int(time.time() * 1000)}")
        os.replace(path, trash)                          # gone from the list at once, even if deleting takes a while
        shutil.rmtree(trash, ignore_errors=True)
    elif os.path.exists(path):
        os.remove(path)


# ====================================================================== exporting
def export(module_id: str, dest: str, progress: Optional[Callable[[int, int], None]] = None) -> str:
    """Zip a module into a .dmmod file (dest: a file path, or a folder to put '<id>-<version>.dmmod' in)."""
    m = get(module_id)
    return pack_folder(m["folder"], dest, progress)


def pack_folder(folder: str, dest: str, progress: Optional[Callable[[int, int], None]] = None) -> str:
    """Zip a module folder into a .dmmod file; returns the file's path."""
    meta = _read(os.path.join(folder, "module.json"))
    if not valid_meta(meta):
        raise PackageError("That folder isn't a module (no valid module.json in it).")
    if os.path.isdir(dest) or not os.path.splitext(dest)[1] and not os.path.exists(dest):     # a folder to put it in
        os.makedirs(dest, exist_ok=True)
        version = re.sub(r"[^\w.\-]", "_", str(meta.get("version") or "1"))
        dest = os.path.join(dest, f"{meta['id']}-{version}{EXTENSION}")
    elif not dest.lower().endswith(EXTENSION):
        dest += EXTENSION
    files = _files_of(folder)
    for rel in files:
        _check_name(rel)
    os.makedirs(os.path.dirname(os.path.abspath(dest)), exist_ok=True)
    tmp = dest + ".part"
    try:
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_DEFLATED, compresslevel=6, allowZip64=True) as z:
            for n, rel in enumerate(files, 1):
                kind = zipfile.ZIP_STORED if os.path.splitext(rel)[1].lower() in STORED else zipfile.ZIP_DEFLATED
                z.write(os.path.join(folder, *rel.split("/")), rel, compress_type=kind)
                if progress and (n % 200 == 0 or n == len(files)):
                    progress(n, len(files))
        os.replace(tmp, dest)
    finally:
        if os.path.exists(tmp):
            os.remove(tmp)
    return dest


def write_module(folder: str, meta: dict, content: Dict[str, list]) -> str:
    """Write a module folder from its module.json and {kind: [records]} (a custom rulebook being exported)."""
    if not valid_meta(meta):
        raise PackageError("A module needs an id and a name.")
    from .storage import write_json
    os.makedirs(folder, exist_ok=True)
    write_json(os.path.join(folder, "module.json"), meta)
    for kind, rows in content.items():
        if rows:
            write_json(os.path.join(folder, f"{kind}.json"), rows)
    return folder
