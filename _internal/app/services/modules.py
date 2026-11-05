"""Installed content modules, for the Installations window: listing them, installing from a .dmmod file or a folder,
exporting, removing, switching on and off, and turning a custom rulebook into a module (and back). After any change
every cached view of the rules data is dropped, so the new content shows up everywhere at once.

The files themselves are handled by app.core.packages; what a module holds is read by app.rules.modules.
"""
import os
import re
import sys
import tempfile
import shutil
from typing import Callable, Dict, List, Optional

from ..core import events, packages
from ..core.runtime import rt
from ..rules import homebrew as HB
from ..rules import modules as MOD
from ..rules.data import rules
from .common import ServiceError

KIND_TITLES = {"classes": "classes", "subclasses": "subclasses", "races": "races", "backgrounds": "backgrounds",
               "feats": "feats", "optional_features": "class options", "skills": "skills", "conditions": "conditions",
               "languages": "languages", "spells": "spells", "items": "items", "item_properties": "item properties",
               "monsters": "creatures", "lore": "creature descriptions", "pictures": "pictures",
               "translations": "translations", "icons": "icons", "sprites": "item sprites", "props": "map props",
               "sounds": "sounds", "worldart": "world map stamps", "portraits": "portraits"}
ONE = {"classes": "class", "subclasses": "subclass", "races": "race", "backgrounds": "background", "feats": "feat",
       "optional_features": "class option", "skills": "skill", "conditions": "condition", "languages": "language",
       "spells": "spell", "items": "item", "item_properties": "item property", "monsters": "creature",
       "lore": "creature description", "pictures": "picture", "translations": "translation", "icons": "icon",
       "sprites": "item sprite",
       "props": "map prop", "sounds": "sound", "worldart": "world map stamp", "portraits": "portrait"}


def _err(fn, *args, **kwargs):
    try:
        return fn(*args, **kwargs)
    except packages.PackageError as e:
        raise ServiceError(str(e))
    except OSError as e:
        raise ServiceError(f"The files couldn't be read or written ({e.strerror or e}).")


# ====================================================================== keeping everything in step
def reload_content() -> None:
    """Forget every cached view of the rules data, the pictures and the translations (a module came or went)."""
    from ..core import assets, portraits
    from ..core.i18n import i18n
    from . import sound
    from .world import stamps
    from ..rules import monster_gen, search
    from ..rules.monsters import bestiary
    packages.forget()
    MOD.reset()
    for key in [k for k, v in type(rules).__dict__.items() if hasattr(v, "attrname")]:      # every cached_property
        rules.__dict__.pop(key, None)
    bestiary.reload()
    HB.refresh()
    search.monster_index = search.item_index = None
    monster_gen.invalidate()
    assets.reset()
    portraits.forget()
    sound.forget()
    stamps.reload()
    i18n.reload()
    for name, mod in list(sys.modules.items()):              # the engine's lookups by name (spell specs, item pictures...)
        if mod is None or not name.startswith(("app.rules", "app.services")):
            continue
        for value in list(vars(mod).values()):
            clear = getattr(value, "cache_clear", None)
            if callable(clear) and getattr(value, "__module__", None) == name:
                clear()


def _announce(text: str) -> None:
    r = rt()
    r.log_action(text)
    r.bus.emit(events.RULES)
    r.bus.emit(events.CHARACTERS)


packages.on_change(reload_content)


# ====================================================================== reading
def installed() -> List[dict]:
    """[{id, name, version, description, credits, license, kind, origin, enabled, folder, counts: {kind: n},
    summary: '120 spells · 40 creatures', books: [names], bytes}] for every module found."""
    out = []
    for m in packages.all_modules():
        counts = MOD.summary(m)
        books = [s.get("name", k) for k, s in (m.get("sources") or {}).items() if isinstance(s, dict)]
        out.append({**{k: v for k, v in m.items() if k not in ("sources",)},
                    "kind": m.get("kind") if m.get("kind") in ("book", "assets") else "module",
                    "version": str(m.get("version") or "1"), "counts": counts, "books": books,
                    "summary": " · ".join(f"{n} {(ONE if n == 1 else KIND_TITLES).get(k, k)}" for k, n in counts.items())})
    return out


def size(module_id: str) -> int:
    """Bytes the module takes on disk."""
    return packages.size_of(_err(packages.get, module_id)["folder"])


def peek(path: str) -> dict:
    """What a .dmmod file (or module folder) holds, before installing it; 'installed': the version already here."""
    meta = _err(packages.peek, path)
    have = next((m for m in packages.all_modules() if m["id"] == meta["id"]), None)
    return {**meta, "installed": str(have.get("version") or "1") if have else None,
            "installed_origin": have["origin"] if have else None}


def default_folder() -> str:
    """Where Export… suggests saving: Documents\\Dungeonomicon\\exports\\modules."""
    from ..core.userdata import home
    return os.path.join(home(), "exports", "modules")


# ====================================================================== changing
def _switch_on_books(metas: List[dict]) -> None:
    """Tick the books new modules bring in the Sourcebooks window (not the adventures: their races and items stay out
    of character creation until ticked there)."""
    new = []
    for meta in metas:
        if meta.get("kind") == "assets":                  # pictures and sounds: no book to tick
            continue
        if meta.get("kind") != "book":
            new.append(meta["id"])
        else:
            new += [b for b, s in (meta.get("sources") or {}).items() if not (isinstance(s, dict) and s.get("adventure"))]
    new = [b for b in dict.fromkeys(new) if b not in rules.active_sources]
    if new:
        rt().set_sources(list(rules.active_sources) + new)


def install(path: str, progress: Optional[Callable[[int, int], None]] = None) -> dict:
    """Install a .dmmod file or a module folder: copied into the modules folder next to the program (the only place
    modules are read from, so it travels with it). The books it brings are switched on when it is new here."""
    if not packages.folder_writable():
        raise ServiceError("The modules folder can't be written: move the program to a folder you can write to.")
    meta = _err(packages.add_to_folder, path, progress)
    packages.take_new_from_folder()                    # (known now: the folder check won't switch its books on again)
    if not meta.get("replaced"):
        _switch_on_books([meta])
    _announce(f"Module installed: {meta['name']} {meta.get('version') or ''}".strip())
    return meta


def read_folder(progress: Optional[Callable[[str, int, int], None]] = None) -> dict:
    """Unpack what was dropped into the modules folder, forget what was taken out (any thread; slow for a big new
    file). Hand the result to folder_read() on the main thread."""
    return packages.sync_folder(progress)


def folder_read(result: dict) -> List[dict]:
    """After read_folder(): when the modules changed, every view of the rules is read again; the books of modules new
    to this computer are switched on. Returns the new modules."""
    if result.get("changed"):
        packages._changed()
    new = packages.take_new_from_folder()
    _switch_on_books(new)
    if result.get("changed") or new:
        names = ", ".join(f"{m['name']} {m.get('version') or ''}".strip() for m in new)
        _announce(f"Modules folder: {names} added" if new else "Modules folder changed")
    for name, why in (result.get("errors") or {}).items():
        rt().log_action(f"Modules folder: {name} skipped - {why}")
    return new


def install_many(paths: List[str], progress: Optional[Callable[[str, int, int], None]] = None) -> List[dict]:
    """Install several files one after another; stops at the first that fails (those before it stay installed)."""
    out = []
    for p in paths:
        out.append(install(p, (lambda n, t, p=p: progress(os.path.basename(p), n, t)) if progress else None))
    return out


def export(module_id: str, dest: str, progress: Optional[Callable[[int, int], None]] = None) -> str:
    path = _err(packages.export, module_id, dest, progress)
    rt().log_action(f"Module exported: {module_id} -> {path}")
    return path


def uninstall(module_id: str) -> dict:
    m = _err(packages.uninstall, module_id)
    _announce(f"Module removed: {m['name']}")
    return m


def set_enabled(module_id: str, on: bool) -> None:
    m = _err(packages.get, module_id)
    _err(packages.set_enabled, module_id, on)
    _announce(f"Module {'switched on' if on else 'switched off'}: {m['name']}")


# ====================================================================== custom rulebooks <-> modules
def _module_id(book_id: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.\-]", "_", book_id)[:64] or "BOOK"


def export_rulebook(book_id: str, dest: str, version: str = "1.0", author: str = "") -> str:
    """A custom rulebook of the Rules tab saved as a .dmmod file, to be installed (read-only, as a module) on another
    computer - or imported back as a rulebook to edit (import_as_rulebook)."""
    try:
        b = HB.book(book_id)
    except Exception as e:
        raise ServiceError(str(e))
    meta = {"id": _module_id(b["id"]), "name": b["name"], "description": b.get("description", ""), "version": version,
            "credits": author, "kind": "module", "format": packages.FORMAT, "rulebook": True}
    content = {}
    for kind, rows in b["content"].items():
        clean = []
        for r in rows:
            r = {k: v for k, v in r.items() if k not in ("homebrew", "source", "module")}
            if kind == "monsters":
                r.pop("id", None)
            clean.append(r)
        content[kind] = clean
    tmp = tempfile.mkdtemp(prefix="dmmod_")
    try:
        folder = _err(packages.write_module, os.path.join(tmp, meta["id"]), meta, content)
        path = _err(packages.pack_folder, folder, dest)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    rt().log_action(f"Rulebook exported as a module: {b['name']} -> {path}")
    return path


def import_as_rulebook(path: str) -> dict:
    """A module (.dmmod or folder) of the "module" kind brought in as a custom rulebook, to edit in the Rules tab.
    Returns the new rulebook plus 'added' and 'skipped' (['name: why'])."""
    meta = _err(packages.peek, path)
    if meta.get("kind") == "book":
        raise ServiceError("This module holds published books; install it instead.")
    tmp = tempfile.mkdtemp(prefix="dmmod_")
    try:
        folder = path if os.path.isdir(path) else tmp
        if folder == tmp:
            _err(packages.unzip_to, path, tmp)
        files = sorted(os.listdir(folder))
        content: Dict[str, list] = {k: MOD._rows_of(folder, files, k) for k in HB.KINDS}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    name = meta["name"]
    taken = {b["name"].lower() for b in HB.books()} | {v["name"].lower() for v in rules.sources.values()}
    n, final = 1, name
    while final.lower() in taken:
        n += 1
        final = f"{name} ({n})"
    try:
        b = HB.save_book(final, meta.get("description", ""))
        added, skipped = HB.import_entries(b["id"], content)
    except Exception as e:
        raise ServiceError(str(e))
    if b["id"] not in rules.active_sources:
        rt().set_sources(list(rules.active_sources) + [b["id"]])
    _announce(f"Module imported as a rulebook: {final} ({added} entries)")
    return {**HB.book(b["id"]), "added": added, "skipped": skipped}
