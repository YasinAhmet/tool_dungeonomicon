"""Character portraits: the ones imported for a character (data/portraits), and the portrait library to pick them from.

A character's `d["portrait"]` is {} (automatic: the picture of its race, core/assets.race_token) or
{"file": "data/portraits/<id>.png", "framed": bool}. A framed portrait is a finished round token with its own border,
drawn as it is; any other picture is cut round inside a ring of its side's colour.

The portrait library is the portrait modules' (asset modules with assets/portraits, core/assets.py), joined: e.g. the
Baldur's Gate portraits built by tools/fetch_portrait_library.py, or a module of the DM's own made by
app.services.portrait_packs (export / import). Each portrait is tagged with its race, class, folk, creature and pack
('race:dwarf', 'creature:lich', 'pack:ppe'), the companions by name. The editor sorts them into a few kinds
(KINDS: adventurers, warriors, ... monsters) and filters them by race and gender.

A portrait module's assets/portraits:
    index.json          {"packs": {key: {"title", "url"}},
                         "portraits": [{"id", "tags": ["race:dwarf", ...], "gender": "f" | "m" | "", "name"}]}
    pics/<id>.webp      the portrait (any size; tall, the face in its upper part: FACE)
    thumbs/<id>.webp    a 96 px square round its face, for the editor's gallery

    path, framed = portraits.of(char.d)            # what the battle map draws for the character
    path, framed = portraits.of_monster(m)         # a custom creature's own picture (m['portrait']), else its token
    for p in portraits.library(): p["path"], p["thumb"], p["tags"], p["gender"], p["name"], p["kinds"], p["module"]
    portraits.library_race("Hill Dwarf")           # 'dwarf' ('' when the library has none)
"""
import json
import os
import re
import uuid
from typing import List, Optional, Tuple

from . import assets

FOLDER = os.path.join("data", "portraits")
FACE = .36                                                         # a portrait's face, as a fraction of its height
KINDS = (("adventurers", "Adventurers"), ("warriors", "Warriors"), ("casters", "Spellcasters"), ("rogues", "Rogues"),
         ("townsfolk", "Townsfolk"), ("monsters", "Monsters"), ("undead", "Undead"), ("others", "Other characters"))
WARRIORS = {"class:fighter", "class:paladin", "class:ranger", "class:barbarian", "class:monk", "folk:knight", "folk:soldier"}
CASTERS = {"class:wizard", "class:sorcerer", "class:warlock", "class:cleric", "class:druid", "class:bard"}
TOWNSFOLK = {"folk:commoner", "folk:bartender", "folk:beggar", "folk:child", "folk:courtesan", "folk:merchant",
             "folk:noble", "folk:sailor", "folk:scholar"}
# races the library has no portraits of, shown as their nearest kin
KIN = {"eladrin": "elf", "shadar-kai": "elf", "sea elf": "elf", "duergar": "dwarf", "svirfneblin": "gnome",
       "deep gnome": "gnome"}
_library: dict = {}


def main_class(d: dict) -> str:
    """The class a character has most levels in (the first one on a tie)."""
    cls = d.get("classes") or []
    return max(cls, key=lambda c: c.get("level", 0))["name"] if cls else ""


def custom_path(d: dict) -> Optional[str]:
    """The character's own picture, when it has one that is still there."""
    p = d.get("portrait") or {}
    file = p.get("file") if isinstance(p, dict) else None
    return file if file and os.path.isfile(file) else None


def of(d: dict) -> Tuple[Optional[str], bool]:
    """(picture path or None, framed) for a character's data: its own picture, else the picture of its race."""
    file = custom_path(d)
    if file:
        return file, bool(d["portrait"].get("framed"))
    return assets.race_token(d.get("race") or ""), False


def of_monster(m: dict) -> Tuple[Optional[str], bool]:
    """(picture path or None, framed) for a bestiary record: a custom creature's own picture, else its token."""
    file = custom_path(m)
    if file:
        return file, bool(m["portrait"].get("framed"))
    return assets.monster_token(m.get("name") or "", m.get("source") or "", m.get("type") or ""), False


def save_choice(choice: dict) -> dict:
    """The portrait editor's choice ({'png', 'framed', 'inner', 'border'}) kept in data/portraits, as d['portrait']."""
    file = save(choice["png"])
    inner = save(choice["inner"]) if choice.get("framed") and choice.get("inner") else file
    return {"file": file, "framed": bool(choice.get("framed")), "inner": inner, "border": dict(choice.get("border") or {})}


def kinds(tags) -> List[str]:
    """The KINDS a portrait with these tags is shown under ('others' when none fits)."""
    tags = set(tags)
    folk = tags & TOWNSFOLK
    creature = any(t.startswith("creature:") for t in tags)
    out = []
    if tags & {"folk:hero", "folk:companion"} or not folk and not creature and \
            any(t.startswith(("race:", "class:")) for t in tags):
        out.append("adventurers")
    if tags & WARRIORS:
        out.append("warriors")
    if tags & CASTERS:
        out.append("casters")
    if "class:rogue" in tags:
        out.append("rogues")
    if folk:
        out.append("townsfolk")
    if creature and "creature:undead" not in tags:
        out.append("monsters")
    if "creature:undead" in tags:
        out.append("undead")
    return out or ["others"]


def library() -> List[dict]:
    """The portrait library's portraits: [{'id' (unique in the library: '<module>/<id>' after the first module's),
    'tags', 'gender' ('f', 'm' or ''), 'name' (a companion's, else ''), 'kinds', 'path', 'thumb', 'module' (the
    module folder's assets/portraits)}], [] without a portrait module. Read again when a module changed."""
    folders = assets.dirs("portraits")
    stamp = []
    for folder in folders:
        try:
            stamp.append((folder, os.path.getmtime(os.path.join(folder, "index.json"))))
        except OSError:
            pass
    if _library.get("stamp") == stamp:
        return _library["items"]
    packs, items, ids = {}, [], set()
    for folder in (f for f, _t in stamp):
        try:
            with open(os.path.join(folder, "index.json"), encoding="utf-8") as f:
                data = json.load(f)
            packs.update({k: v for k, v in (data.get("packs") or {}).items() if k not in packs})
            for p in data.get("portraits") or []:
                pid, tags = str(p["id"]), [str(t) for t in p.get("tags") or []]
                if not re.fullmatch(r"[\w.\-]+", pid):
                    continue
                uid = pid if pid not in ids else f"{os.path.basename(os.path.dirname(os.path.dirname(folder)))}/{pid}"
                ids.add(uid)
                thumb = os.path.join(folder, "thumbs", pid + ".webp")
                pic = os.path.join(folder, "pics", pid + ".webp")
                items.append(dict(p, id=uid, tags=tags, gender=p.get("gender") or "", name=p.get("name") or "",
                                  kinds=kinds(tags), path=pic, thumb=thumb if os.path.isfile(thumb) else pic, module=folder))
        except (OSError, ValueError, KeyError, TypeError, AttributeError):
            continue
    _library.clear()
    _library.update(stamp=stamp, packs=packs, items=items)
    return items


def forget() -> None:
    """The portrait modules changed: read them again."""
    _library.clear()


def library_races() -> List[Tuple[str, int]]:
    """The races the library has portraits of, with how many: [('dwarf', 45), ...]."""
    count: dict = {}
    for p in library():
        for t in p["tags"]:
            if t.startswith("race:"):
                count[t[5:]] = count.get(t[5:], 0) + 1
    return sorted(count.items())


def library_race(race: str) -> str:
    """'Hill Dwarf' -> 'dwarf', 'Half-Elf' -> 'half-elf', 'Eladrin' -> 'elf'; '' when the library has no such portraits."""
    r = re.sub(r"\s*\(.*?\)", "", race or "").strip().lower()
    have = {k for k, _n in library_races()}
    for cand in (r, r.split(",")[0].strip(), r.split(" ")[-1], r.split(" ")[0]):
        cand = KIN.get(cand, cand)
        if cand in have:
            return cand
    return ""


def tag_label(tag: str) -> str:
    """'race:half-elf' -> 'Half-Elf', 'pack:ppe' -> the pack's title."""
    kind, _c, value = tag.partition(":")
    if kind == "pack":
        return (_library.get("packs") or {}).get(value, {}).get("title") or value
    return value.title()


def save(png: bytes) -> str:
    """Keep an imported picture (PNG bytes) in data/portraits; returns its path for d['portrait']['file']."""
    os.makedirs(FOLDER, exist_ok=True)
    path = os.path.join(FOLDER, uuid.uuid4().hex[:12] + ".png").replace("\\", "/")
    with open(path, "wb") as f:
        f.write(png)
    return path
