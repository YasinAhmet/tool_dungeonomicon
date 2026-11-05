"""The world map's stamps: pictures the DM sets on the map like marks - castles, houses, trees, old engraved hills and
towns, compass roses. They come from free cartography packs (an asset module's assets/worldart - "world-art",
core/assets.py - made by tools/build_world_art.py into the project's assets/worldart; see CREDITS.md there), the painted
set seen from the side (worldart/painted, made by tools/build_painted_art.py) and from
the DM's own pictures: PNG or WebP files in data/world/stamps/ (a folder in it: a group of its own).

    stamps.catalog()      -> {key: {"key", "group", "name", "h", "anchor", "file"}}   (h: its height on the map, map pixels)
                             the ink set's are vectors instead: {"vector": True, "w", "p", "i"} - SVG path data of the
                             paper it covers and of its ink, in map pixels round its point (tools/build_ink_art.py)
    stamps.groups()       -> ["Castles and towers", ...]   (the packs' first, then the DM's)
    stamps.path(key)      -> the picture's file, or None
    stamps.reload()       (after the DM put new pictures in the folder)

A stamp on the map is a mark {"kind": "art", "art": key, "x", "y", "s", "name"}: it stands on its point (anchor "b")
or lies around it ("c"), h × s map pixels tall.
"""
import os
import re
import threading
from typing import Dict, List, Optional

USER = "data/world/stamps"
USER_H = 24.0                                   # a picture of the DM's own: this tall on the map (map pixels) to start with
PICTURES = (".png", ".webp")

_lock = threading.Lock()
_catalog: Optional[Dict[str, dict]] = None


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", s.lower()).strip("_")[:40] or "x"


def _pictures(out: Dict[str, dict], rel: str):
    """Every world art module's stamps listed in `rel` (their pictures next to it); the first module's key wins."""
    from ...core import assets
    for folder, rows in assets.catalogues("worldart", rel):
        for e in rows if isinstance(rows, list) else []:
            if isinstance(e, dict) and isinstance(e.get("key"), str) and e["key"] not in out:
                out[e["key"]] = dict(e, file=os.path.join(folder, e["key"] + ".webp"))


def _load() -> Dict[str, dict]:
    from ...core import assets
    out: Dict[str, dict] = {}
    _pictures(out, "painted/painted.json")                      # the painted set, seen from the side (tools/build_painted_art.py)
    for _folder, rows in assets.catalogues("worldart", "ink.json"):     # the black-and-white ink set: vectors ("p", "i")
        for e in rows if isinstance(rows, list) else []:
            if isinstance(e, dict) and isinstance(e.get("key"), str) and e["key"] not in out:
                out[e["key"]] = dict(e, file=None, vector=True)
    _pictures(out, "catalog.json")                              # the top-down set
    if os.path.isdir(USER):                                     # the DM's own: loose files, or a folder a group
        for root, _dirs, files in sorted(os.walk(USER)):
            rel = os.path.relpath(root, USER)
            group = "My stamps" if rel == "." else "My stamps: " + rel.replace(os.sep, " / ")
            for name in sorted(files):
                stem, ext = os.path.splitext(name)
                if ext.lower() not in PICTURES:
                    continue
                key = "my_" + ("" if rel == "." else _slug(rel) + "_") + _slug(stem)
                out.setdefault(key, {"key": key, "group": group, "name": stem.replace("_", " "), "h": USER_H, "anchor": "b",
                                     "file": os.path.join(root, name)})
    return out


def catalog() -> Dict[str, dict]:
    global _catalog
    with _lock:
        if _catalog is None:
            _catalog = _load()
        return _catalog


def reload():
    global _catalog
    with _lock:
        _catalog = None


def groups() -> List[str]:
    seen = []
    for e in catalog().values():
        if e["group"] not in seen:
            seen.append(e["group"])
    return seen


def in_group(group: str) -> List[dict]:
    return [e for e in catalog().values() if e["group"] == group]


def get(key: str) -> Optional[dict]:
    return catalog().get(key or "")


TERRAIN_ART = {   # the painted look draws the sprayed terrain marks with these (kind: (pictures, about how tall))
    "mountain": (("pt_mountain_1", "pt_mountain_2", "pt_mountain_3", "pt_mountain_7", "pt_mountain_8", "pt_mountain_4"), 20.0),
    "hills": (("pt_hills_1", "pt_hills_3", "pt_hills_6", "pt_hills_2"), 10.0),
    "forest": (("pt_tree_1", "pt_tree_2", "pt_tree_3", "pt_pine_1", "pt_tree_1", "pt_pine_2"), 9.0),
}


SETTLEMENT_ART = {   # ...and the settlement marks with these (kind: (pictures, how tall))
    "capital": (("pt_city_1", "pt_city_2"), 30.0), "city": (("pt_town_1", "pt_town_2"), 24.0),
    "town": (("pt_village_1", "pt_village_2", "pt_village_3"), 16.0), "village": (("pt_village_2", "pt_village_3"), 12.0),
    "fort": (("pt_castle_1", "pt_castle_2", "pt_castle_3"), 18.0), "ruin": (("pt_ruins_1",), 14.0),
}


def terrain_art(m: dict) -> Optional[tuple]:
    """(picture key, scale) a sprayed mountain, hill or tree, or a settlement mark, is drawn with on the painted looks;
    None: no such picture."""
    town = m.get("kind") in SETTLEMENT_ART
    got = SETTLEMENT_ART.get(m.get("kind")) if town else TERRAIN_ART.get(m.get("kind"))
    if not got:
        return None
    v = int(m.get("id") if town else m.get("v") or 0)
    e = get(got[0][v % len(got[0])])
    if not e:
        return None
    return e["key"], got[1] * float(m.get("s") or 1) * (1.0 if town else 0.88 + (v % 7) * 0.04) / float(e["h"])


def path(key: str) -> Optional[str]:
    """A picture stamp's file (None for an ink stamp: it is drawn from its shapes)."""
    e = get(key)
    return e["file"] if e and e.get("file") and os.path.isfile(e["file"]) else None
