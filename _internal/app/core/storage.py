"""Small JSON/file helpers shared by every persistence module."""
import atexit
import copy
import json
import os
import pickle
import tempfile
import threading
import time
from typing import Any, Dict, List, Optional, Set


def clone(data: Any) -> Any:
    """A deep copy of plain data (what JSON holds), about three times quicker than copy.deepcopy: the battle's views
    are copied for every window after every change."""
    try:
        return pickle.loads(pickle.dumps(data, pickle.HIGHEST_PROTOCOL))
    except Exception:
        return copy.deepcopy(data)


def read_json(path: str, default: Any = None) -> Any:
    """Read a JSON file; return `default` if it is missing or unreadable. A write of it still on its way (write_json_soon)
    lands first."""
    flush(path)
    if not os.path.exists(path):
        return default
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def write_json(path: str, data: Any) -> None:
    """Write JSON atomically so a crash mid-write never corrupts the file."""
    write_text(path, json.dumps(data, indent=2, ensure_ascii=False))


def write_text(path: str, text: str) -> None:
    """Write a text file atomically (what write_json writes, already made)."""
    flush(path)                                        # an older write still queued must not land after this one
    _write_text(path, text)


def _write_text(path: str, text: str) -> None:
    folder = os.path.dirname(path) or "."
    os.makedirs(folder, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=folder, suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


# ---------------------------------------------------------------------- writing in the background
# Saving a file costs a few milliseconds on Windows, sometimes tens (the virus scanner looks at every new file): the
# battle is saved after every change, on whatever thread made it - often the editor's screen. write_json_soon turns
# the data into text right away (so later changes can't slip in) and a writer thread saves it; only the newest text of
# a file is written. read_json, write_json and flush() wait for a file's queued write, and everything lands at exit.
_queued: Dict[str, str] = {}                           # absolute path -> the newest text to write
_busy: Set[str] = set()                                # being written now
_cv = threading.Condition()
_writer: List[threading.Thread] = []


def write_json_soon(path: str, data: Any) -> None:
    """write_json, done by a background thread: returns at once."""
    text = json.dumps(data, indent=2, ensure_ascii=False)
    with _cv:
        _queued[os.path.abspath(path)] = text
        if not _writer:
            t = threading.Thread(target=_write_loop, daemon=True, name="json-writer")
            _writer.append(t)
            t.start()
        _cv.notify_all()


def flush(path: Optional[str] = None) -> None:
    """Wait until the queued write of `path` (None: of every file) is on disk."""
    with _cv:
        if not _queued and not _busy:
            return
        key = os.path.abspath(path) if path else None
        while (key in _queued or key in _busy) if key else (_queued or _busy):
            if not (_writer and _writer[0].is_alive()):      # no writer (it died): write it here
                for k in [key] if key else list(_queued):
                    if k in _queued:
                        _write_text(k, _queued.pop(k))
                return
            _cv.wait(0.5)


def _write_loop():
    while True:
        with _cv:
            while not _queued:
                _cv.wait()
            key, text = next(iter(_queued.items()))
            del _queued[key]
            _busy.add(key)
        try:
            for attempt in range(5):                     # the scanner may hold the file a moment
                try:
                    _write_text(key, text)
                    break
                except PermissionError:
                    time.sleep(0.05 * (attempt + 1))
            else:
                _write_text(key, text)
        except Exception as e:
            print(f"[ERROR] could not save {key}: {e}")
        finally:
            with _cv:
                _busy.discard(key)
                _cv.notify_all()


atexit.register(flush)


def list_json_names(folder: str) -> List[str]:
    """Sorted base names of every *.json file in `folder` (created if missing)."""
    os.makedirs(folder, exist_ok=True)
    return sorted(f[:-5] for f in os.listdir(folder) if f.endswith(".json"))


_INVALID_NAME_CHARS = set('\\/:*?"<>|')


def validate_name(name: str, what: str = "Name") -> str:
    """Strip and validate a user supplied name that becomes a file name."""
    name = (name or "").strip()
    if not name:
        raise ValueError(f"{what} cannot be empty.")
    if name in (".", "..") or _INVALID_NAME_CHARS & set(name):
        raise ValueError(f"{what} cannot contain any of: \\ / : * ? \" < > |")
    return name
