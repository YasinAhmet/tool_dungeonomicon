"""Pictures and sounds: battle map tokens (monsters from img/bestiary/tokens, characters from their race in img/races),
the asset modules' icons, item sprites, props, sounds, world art and portraits (dirs(), asset(), catalogues() below),
and remote images such as Discord server icons (downloaded once into data/cache/images).

Every function returns a full file path (or None), ready for QPixmap.

The `img` folders are those of the switched-on modules (<module>/img: the art packs, app.core.packages) - never a loose
img folder (the project's 5etools pictures, one next to the exe): book art comes only from modules. The one exception is
a build of your own made with --token-pack, which carries its pictures inside.
"""
import os
import re
import sys
from typing import Dict, List, Optional

_index: Dict[str, Dict[str, List[str]]] = {}


def roots() -> List[str]:
    out = []
    if getattr(sys, "frozen", False) and getattr(sys, "_MEIPASS", None):
        out.append(os.path.join(sys._MEIPASS, "img"))     # only in a build made with --token-pack (tools/build_exe.py)
    from . import packages
    out += packages.folders("img")                       # the modules' pictures (the art packs)
    seen, uniq = set(), []
    for r in out:
        if r not in seen and os.path.isdir(r):
            seen.add(r)
            uniq.append(r)
    return uniq


def find(rel: str) -> Optional[str]:
    """Full path of 'bestiary/tokens/MM/Goblin.webp' inside the first img folder that has it (None if it climbs out)."""
    rel = rel.replace("\\", "/").lstrip("/")
    for root in roots():
        full = os.path.normpath(os.path.join(root, rel))
        if full.startswith(os.path.normpath(root) + os.sep) and os.path.isfile(full):
            return full
    return None


def _names(kind: str) -> Dict[str, List[str]]:
    """lower-case picture name -> ['bestiary/tokens/MM/Goblin.webp', ...] (the order of the books: core rules first)."""
    if kind in _index:
        return _index[kind]
    base = {"tokens": "bestiary/tokens", "art": "bestiary", "races": "races"}[kind]
    out: Dict[str, List[str]] = {}
    for root in roots():
        top = os.path.join(root, *base.split("/"))
        if not os.path.isdir(top):
            continue
        for src in sorted(os.listdir(top), key=lambda s: (s not in ("MM", "PHB", "MPMM"), s)):
            folder = os.path.join(top, src)
            if src == "tokens" or not os.path.isdir(folder):
                continue
            for f in os.listdir(folder):
                if f.lower().endswith((".webp", ".png", ".jpg")):
                    hits = out.setdefault(os.path.splitext(f)[0].lower(), [])
                    if f"{base}/{src}/{f}" not in hits:
                        hits.append(f"{base}/{src}/{f}")
    _index[kind] = out
    return out


def monster_token(name: str, source: str, mtype: str = "") -> Optional[str]:
    """A monster's token (its own book first), else any book's token of that name, else its artwork,
    else the picture of its creature type ('undead' -> img/types/undead.webp)."""
    for kind in ("tokens", "art"):
        hits = _names(kind).get(name.lower(), [])
        mine = [h for h in hits if f"/{source}/" in h]
        if mine or hits:
            return find((mine or hits)[0])
    typ = re.split(r"[\s/(,]", (mtype or "").strip().lower(), maxsplit=1)[0]
    return find(f"types/{typ}.webp") if typ else None


def race_token(race: str) -> Optional[str]:
    """A player character's picture: the picture of its race ('Hill Dwarf' -> Dwarf, 'Human (Variant)' -> Human)."""
    names = _names("races")
    r = re.sub(r"\s*\(.*?\)", "", race or "").strip().lower()
    for cand in (r, r.split(",")[0], r.split(" ")[-1], r.split(" ")[0]):
        if cand in names:
            return find(names[cand][0])
    return None


def reset():
    _index.clear()
    _kind_dirs.clear()


# ---------------------------------------------------------------------- asset modules
# Everything the program draws or plays comes from modules ("kind": "assets", app.core.packages), each holding
# assets/<kind>/... with the layout below. The source of the ones we ship is the project's assets/ folder (not shipped:
# tools/build_asset_modules.py packs it into dist/modules/*.dmmod; the tools that make the pictures and sounds write there).
#     icons/       <slug>.webp (48 px, white on transparent), icon_map.json {"spells": {name: slug}}, CREDITS.md
#     items/       <key>.png  32 px item sprites (app.services.battle.itemsprites)
#     props/       <key>.webp / sym_<key>.webp  battle map props and symbols (app.services.battle.props)
#     sounds/      sounds.json {"loops": [...], "oneshots": [...]} + the .ogg files it names (app.services.sound)
#     worldart/    catalog.json, ink.json, painted/painted.json + pictures: world map stamps (app.services.world.stamps)
#     portraits/   index.json, pics/<id>.webp, thumbs/<id>.webp: the portrait library (app.core.portraits)
# Several modules may hold the same kind: a file is taken from the first module that has it (module order), the
# catalogues (sounds.json, worldart, portraits) are joined.
KINDS = ("icons", "items", "props", "sounds", "worldart", "portraits")
SOURCE = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "assets")
_kind_dirs: Dict[str, List[str]] = {}


def source_dir(kind: str) -> str:
    """The project's own source of an asset kind (assets/<kind>): where the tools write, never read by the program."""
    return os.path.join(SOURCE, kind)


def dirs(kind: str) -> List[str]:
    """The enabled modules' assets/<kind> folders, in module order (DUNGEONOMICON_ASSETS: an extra folder laid out like
    assets/, read first - for tools)."""
    if kind not in _kind_dirs:
        from . import packages
        out = []
        extra = os.environ.get("DUNGEONOMICON_ASSETS")
        if extra and os.path.isdir(os.path.join(extra, kind)):
            out.append(os.path.join(extra, kind))
        out += packages.folders(os.path.join("assets", kind))
        _kind_dirs[kind] = out
    return list(_kind_dirs[kind])


def asset(kind: str, rel: str) -> Optional[str]:
    """Full path of a file of an asset kind ('icons', 'fireball.webp') in the first module that has it, else None
    (None too for a path that would climb out of the folder)."""
    rel = (rel or "").replace("\\", "/").lstrip("/")
    if not rel:
        return None
    for root in dirs(kind):
        full = os.path.normpath(os.path.join(root, rel))
        if full.startswith(os.path.normpath(root) + os.sep) and os.path.isfile(full):
            return full
    return None


def catalogues(kind: str, rel: str) -> List[tuple]:
    """[(folder, parsed JSON)] of a catalogue file (sounds.json, worldart/catalog.json...) in every module that has
    one, in module order; unreadable ones are left out."""
    import json
    out = []
    for root in dirs(kind):
        path = os.path.join(root, *rel.split("/"))
        try:
            with open(path, encoding="utf-8") as f:
                out.append((os.path.dirname(path), json.load(f)))
        except (OSError, ValueError):
            pass
    return out


CACHE = os.path.join("data", "cache", "images")


def remote_image(url: str, timeout: float = 4.0) -> Optional[str]:
    """A picture from the web (e.g. a Discord server icon), downloaded the first time and kept in data/cache/images."""
    if not url:
        return None
    import hashlib
    path = os.path.join(CACHE, hashlib.sha1(url.encode()).hexdigest()[:20] + ".png")
    if os.path.isfile(path):
        return path
    try:
        import urllib.request
        with urllib.request.urlopen(url, timeout=timeout) as r:
            data = r.read()
        os.makedirs(CACHE, exist_ok=True)
        with open(path, "wb") as f:
            f.write(data)
        return path
    except (OSError, ValueError):
        return None
