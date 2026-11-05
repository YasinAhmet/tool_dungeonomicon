"""Content modules: what an installed module holds and how it joins the rules data (app.core.packages finds, installs
and exports them). Two kinds, set by module.json "kind":

"module" (the default) - a sourcebook of its own, like a custom rulebook that can't be edited:
    module.json         {"id": "LGR", "name": "...", "description": "...", "credits": "...", "version": "1.0"}
    spells.json         [spell records, the shape of rules/data/spells.json]
    items.json          [item records, the shape of rules/data/items.json]
    monsters.json       [bestiary records, the shape of rules/data/monsters.json]
                        (races.json, feats.json... any kind of app.rules.homebrew.KINDS the same way)
    <kind>_<part>.json  more records of that kind, so several people can write one kind at once (monsters_summons.json:
                        the creatures the module's spells summon)
    tokens/<Name>.webp  a creature's token (or the file its record names in "token")
    icons/<slug>.webp   white-on-transparent 48 px pictures like the "game-icons" module: a spell's or item's "icon": "<slug>"
  Its id is listed in rules.sources (group "module"), so it is switched on and off in the Sourcebooks window like a
  book; every record gets source = the module's id and "module": True, and its content is merged with the custom
  rulebooks' (app.rules.data._homebrew).

"book" - published content, exactly as the program's own data (app/rules/data/*.json) holds it: records keep their
  own "source", so a module can bring whole books back (the parts of the Player's Handbook beyond the SRD, the
  supplements, the adventures). module.json adds
    "sources": {"XGE": {"name": "Xanathar's Guide to Everything", "group": "supplement"}, ...}
  - the books it brings (an entry for a book the program has replaces it: the full name of a book whose SRD part
  ships). Any of BOOK_KINDS may be a file; lore.json holds {monster id: description}; order.json {kind: [record
  keys]} the order the merged lists take (record_key). In the records:
    "replaces": ["Arcane Hand"]   this record stands in for those (the SRD name of a Player's Handbook spell): they
                                  leave the lists and their names still find this one
    "_patch": true                not a record of its own but more of one already there (the same name; a subclass
                                  also by class, a creature by id): its lists (subraces, features...) are added to that
                                  record's, its other fields replace that record's; "_order": {field: [keys]} puts a
                                  list back in the order the whole book has it.

Both kinds may carry locale/*.csv (translations) and img/ (pictures: bestiary/tokens/<book>/<Name>.webp,
bestiary/<book>/<Name>.webp, races/<book>/<Race>.webp), read by app.core.i18n and app.core.assets.
"""
import json
import os
from functools import lru_cache
from typing import Dict, List, Optional

from ..core import packages

ROOT = packages.BUNDLED
BOOK_KINDS = ("classes", "subclasses", "races", "backgrounds", "feats", "optional_features", "skills", "conditions",
              "languages", "spells", "items", "item_properties", "monsters")


def _read(path: str, default):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def _rows_of(folder: str, files: List[str], kind: str) -> List[dict]:
    rows = _read(os.path.join(folder, f"{kind}.json"), [])
    rows = rows if isinstance(rows, list) else []
    for more in (f for f in files if f.startswith(kind + "_") and f.endswith(".json")):
        extra = _read(os.path.join(folder, more), [])      # monsters_summons.json...: another author's part of the kind
        rows = rows + (extra if isinstance(extra, list) else [])
    return [r for r in rows if isinstance(r, dict) and r.get("name")]


@lru_cache(maxsize=1)
def modules() -> List[dict]:
    """Every enabled module: its module.json plus 'folder', 'kind' and 'content' ({kind: [records]})."""
    from .homebrew import KINDS
    out = []
    for meta in packages.enabled():
        folder = meta["folder"]
        if meta.get("kind") == "assets":               # pictures and sounds only: app.core.assets reads them
            continue
        try:
            files = sorted(os.listdir(folder))
        except OSError:
            continue
        kind = "book" if meta.get("kind") == "book" else "module"
        content = {}
        if kind == "book":
            for k in BOOK_KINDS:
                content[k] = [dict(r) for r in _rows_of(folder, files, k)]
        else:
            for k in KINDS:
                content[k] = [_prepare(k, dict(r), meta["id"], folder) for r in _rows_of(folder, files, k)]
        out.append({**meta, "kind": kind, "description": meta.get("description", ""), "content": content})
    return out


def _prepare(kind: str, r: dict, source: str, folder: str) -> dict:
    r.update(source=source, module=True)
    if kind == "monsters":
        r["id"] = f"{r['name']}|{source}"
        token = os.path.join(folder, "tokens", r.get("token") or f"{r['name']}.webp")
        if os.path.isfile(token):                     # what portraits.of_monster draws
            r["portrait"] = {"file": token, "framed": bool(r.get("token_framed"))}
    return r


def reset() -> None:
    """Read the modules again (after one was installed, removed, switched on or off)."""
    modules.cache_clear()
    icon_names.cache_clear()
    _lore.cache_clear()
    _orders.cache_clear()
    aliases.cache_clear()


# ====================================================================== "module" modules: books of their own
def entries(kind: str) -> List[dict]:
    return [e for m in modules() if m["kind"] == "module" for e in m["content"].get(kind, [])]


def source_entries() -> Dict[str, dict]:
    """The books the modules bring: a "module" module is one; a "book" module lists its own (they may replace the
    program's entry for a book, e.g. the full name of a book whose SRD part ships)."""
    out: Dict[str, dict] = {}
    for m in modules():
        if m["kind"] == "module":
            out[m["id"]] = {"name": m["name"], "group": "module", "module": True, "description": m["description"],
                            "pack": m["id"]}
        else:
            for sid, s in (m.get("sources") or {}).items():
                if isinstance(s, dict) and s.get("name"):
                    out[sid] = {**s, "pack": m["id"]}
    return out


# ====================================================================== "book" modules: published content
def _key(kind: str, r: dict):
    if kind == "monsters":
        return r.get("id") or f"{r['name']}|{r.get('source', '')}"
    if kind == "subclasses":
        return (r.get("class"), r["name"])
    if kind == "languages":
        return (r["name"], r.get("source"))
    return r["name"].lower()


def order_key(x) -> str:
    """What a member of a record's list is known by in "_order" (a feature by name and level, a subrace by name and
    book...)."""
    if isinstance(x, dict):
        return json.dumps([x.get("name"), x.get("source"), x.get("level"), x.get("class")])
    return json.dumps(x, sort_keys=True)


def _patch(base: dict, patch: dict) -> dict:
    out = dict(base)
    order = patch.get("_order") or {}
    for k, v in patch.items():
        if k in ("_patch", "_order", "name", "source", "class", "id", "pack"):
            continue
        if isinstance(v, list) and isinstance(out.get(k), list):
            have = {order_key(x) for x in out[k]}
            merged = out[k] + [x for x in v if order_key(x) not in have]
            if k in order:
                rank = {key: i for i, key in enumerate(order[k])}
                merged = sorted(merged, key=lambda x: rank.get(order_key(x), len(rank)))
            out[k] = merged
        elif isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = {**out[k], **v}
        else:
            out[k] = v
    return out


def record_key(kind: str, r: dict) -> str:
    """What a record is known by in a module's order.json."""
    k = _key(kind, r)
    return json.dumps(list(k) if isinstance(k, tuple) else k)


@lru_cache(maxsize=1)
def _orders() -> Dict[str, Dict[str, int]]:
    """{kind: {record key: place}} - the order the whole books have their records in (a "book" module's order.json),
    so the lists read as they did before the content was split (the first option offered stays the first)."""
    out: Dict[str, Dict[str, int]] = {}
    for m in modules():
        if m["kind"] != "book":
            continue
        got = _read(os.path.join(m["folder"], "order.json"), {})
        for kind, keys in (got.items() if isinstance(got, dict) else []):
            if kind not in out and isinstance(keys, list):
                out[kind] = {k: i for i, k in enumerate(keys)}
    return out


def book_rows(kind: str) -> List[dict]:
    return [r for m in modules() if m["kind"] == "book" for r in m["content"].get(kind, [])]


def merge(kind: str, base: List[dict]) -> List[dict]:
    """The program's records of one kind with the "book" modules' added: whole records join (or replace one of the
    same name), "_patch" records add to one, "replaces" take the place of others."""
    rows = book_rows(kind)
    if not rows:
        return base
    out = list(base)
    at = {_key(kind, r): i for i, r in enumerate(out)}
    gone = set()
    for r in rows:
        if r.get("_patch"):
            i = at.get(_key(kind, r))
            if i is not None:
                out[i] = _patch(out[i], r)
            continue
        for name in r.get("replaces") or []:
            gone.add(name.lower())
        k = _key(kind, r)
        if k in at:
            out[at[k]] = r
        else:
            at[k] = len(out)
            out.append(r)
    if gone:
        out = [r for r in out if r["name"].lower() not in gone or r.get("replaces")]
    rank = _orders().get(kind)
    if rank:
        last = len(rank)
        out = [r for _i, r in sorted(enumerate(out), key=lambda p: (rank.get(record_key(kind, p[1]), last), p[0]))]
    return out


@lru_cache(maxsize=1)
def aliases() -> Dict[str, Dict[str, str]]:
    """{kind: {another name (lower case): the record's name}} - "aka" names of the program's records and the names a
    module record "replaces", so a character that knows a spell by either name still finds it."""
    from .data import _load
    out: Dict[str, Dict[str, str]] = {}
    for kind in ("spells", "items", "monsters", "races", "feats", "backgrounds", "optional_features"):
        table: Dict[str, str] = {}
        try:
            base = _load(f"{kind}.json")
        except FileNotFoundError:
            base = []
        for r in base:
            for other in r.get("aka") or []:
                table[other.lower()] = r["name"]
        for r in book_rows(kind):
            for other in r.get("replaces") or []:
                table[other.lower()] = r["name"]
        if table:
            out[kind] = table
    return out


@lru_cache(maxsize=1)
def _lore() -> Dict[str, str]:
    out: Dict[str, str] = {}
    for m in modules():
        if m["kind"] == "book":
            got = _read(os.path.join(m["folder"], "lore.json"), {})
            if isinstance(got, dict):
                out.update(got)
    return out


def lore() -> Dict[str, str]:
    """{monster id: description} from the "book" modules' lore.json."""
    return _lore()


# ====================================================================== pictures
@lru_cache(maxsize=1)
def icon_names() -> Dict[str, str]:
    """{spell or item name (lower case): its picture's slug} for the modules' records that name one."""
    return {e["name"].lower(): e["icon"] for m in modules() for kind in ("spells", "items")
            for e in m["content"].get(kind, []) if e.get("icon")}


def icon_path(slug: str) -> Optional[str]:
    """A module's own picture (icons/<slug>.webp), None when no module has it."""
    for m in modules():
        full = os.path.join(m["folder"], "icons", f"{slug}.webp")
        if os.path.isfile(full):
            return full
    return None


def summary(meta: dict) -> Dict[str, int]:
    """{kind: number of records} of one module (enabled or not), for the Installations window."""
    folder = meta["folder"]
    try:
        files = sorted(os.listdir(folder))
    except OSError:
        return {}
    from .homebrew import KINDS
    if meta.get("kind") == "assets":
        return asset_summary(folder)
    kinds = BOOK_KINDS if meta.get("kind") == "book" else KINDS
    out = {k: sum(1 for r in _rows_of(folder, files, k) if not r.get("_patch")) for k in kinds}
    out = {k: n for k, n in out.items() if n}
    lore_n = len(_read(os.path.join(folder, "lore.json"), {}) or {})
    if lore_n:
        out["lore"] = lore_n
    pics = 0
    for sub in ("img", "tokens", "icons"):
        for _root, _dirs, fs in os.walk(os.path.join(folder, sub)):
            pics += len(fs)
    if pics:
        out["pictures"] = pics
    langs = os.path.join(folder, "locale")
    if os.path.isdir(langs):
        out["translations"] = len([f for f in os.listdir(langs) if f.endswith(".csv")])
    return out


ASSET_FILES = {"icons": (".webp",), "items": (".png",), "props": (".webp",), "sounds": (".ogg", ".wav", ".flac", ".mp3"),
               "worldart": None, "portraits": None}


def asset_summary(folder: str) -> Dict[str, int]:
    """{asset kind: how many} of an "assets" module (app.core.assets.KINDS): its icons, sprites, props, sounds, world
    map stamps and portraits."""
    out = {}
    for kind, exts in ASSET_FILES.items():
        base = os.path.join(folder, "assets", kind)
        if not os.path.isdir(base):
            continue
        if kind == "portraits":
            n = len((_read(os.path.join(base, "index.json"), {}) or {}).get("portraits") or [])
        elif kind == "worldart":
            n = sum(len(_read(os.path.join(base, *rel.split("/")), []) or [])
                    for rel in ("catalog.json", "ink.json", "painted/painted.json"))
        else:
            n = sum(1 for _r, _d, fs in os.walk(base) for f in fs if f.lower().endswith(exts))
        if n:
            out["sprites" if kind == "items" else kind] = n
    pics = sum(len(fs) for _r, _d, fs in os.walk(os.path.join(folder, "img")))
    if pics:
        out["pictures"] = pics
    return out
