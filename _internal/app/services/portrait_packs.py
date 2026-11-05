"""Portrait modules: the DM's portraits shared as a module, and portraits brought in from one (or from a folder of
pictures). A portrait module is an asset module (app.core.assets) holding assets/portraits; once it is in the modules
folder its portraits join the portrait library the portrait editor picks from (app.core.portraits.library).

    own_portraits()                         the characters' and custom creatures' own pictures: [{path, name, tags, gender, of}]
    library_entries(ids)                    portraits of the library as entries to export again
    pictures_in(folder)                     the pictures of a folder as entries (a subfolder's name becomes a tag)
    export(entries, dest, name, ...)        a portrait module (.dmmod) made of those entries; returns its path
    import_path(path, name="")              a .dmmod file or module folder: installed; a folder of pictures (or picture
                                            files): made into a portrait module first, then installed. Returns its module.json

An entry is {'path': picture file, 'name': '' or a name to find it by, 'tags': ['race:dwarf', 'class:fighter', ...],
'gender': 'f' | 'm' | ''}. Pictures are kept as WebP, at most MAX_SIDE pixels; each gets a THUMB px thumbnail round its
face (portraits.FACE of its height for a tall picture).
"""
import io
import json
import os
import re
import shutil
import tempfile
import time
from typing import Callable, Iterable, List, Optional

from ..core import packages, portraits
from .common import ServiceError

PICTURES = (".png", ".webp", ".jpg", ".jpeg", ".bmp", ".gif")
MAX_SIDE = 512
THUMB = 96
ORDER = 70                                               # module.json "order": after the art packs


def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (s or "").lower()).strip("-")[:40]


def _race_tag(race: str) -> str:
    """'Hill Dwarf' -> 'race:dwarf' (the library's own word when it has one), 'Half-Elf' -> 'race:half-elf'."""
    base = re.sub(r"\s*\(.*?\)", "", race or "").strip().lower()
    if not base:
        return ""
    known = portraits.library_race(base)
    return "race:" + (known or base.split(",")[0].strip().split(" ")[-1])


# ====================================================================== what can be exported
def own_portraits() -> List[dict]:
    """The pictures the DM gave characters and custom creatures (data/portraits), as entries to export; 'of' says
    whose it is ('character' / 'creature'). The picture without its border when it has one ('inner')."""
    from ..rules.character import Character
    from ..rules.monsters import bestiary
    out, seen = [], set()

    def add(d: dict, name: str, tags: List[str], gender: str, of: str):
        file = portraits.custom_path(d)
        if not file:
            return
        inner = (d.get("portrait") or {}).get("inner")
        path = inner if inner and os.path.isfile(inner) else file
        if os.path.normcase(os.path.abspath(path)) in seen:
            return
        seen.add(os.path.normcase(os.path.abspath(path)))
        out.append({"path": path, "name": name, "tags": [t for t in tags if t], "gender": gender, "of": of})

    for name in Character.list_characters():
        char = Character.load(name)
        if not char:
            continue
        d = char.d
        g = str((d.get("details") or {}).get("gender") or "").strip().lower()[:1]
        main = portraits.main_class(d)
        add(d, name, ["folk:hero", _race_tag(d.get("race") or ""), "class:" + main.lower() if main else ""],
            g if g in ("f", "m") else "", "character")
    for m in bestiary.custom():
        typ = re.split(r"[\s/(,]", str(m.get("type") or "").strip().lower(), maxsplit=1)[0]
        add(m, m.get("name") or "", ["creature:" + typ if typ else "creature:monster"], "", "creature")
    return out


def library_entries(ids: Iterable[str]) -> List[dict]:
    """Portraits of the library (by their library id) as entries, to make a module of a choice of them."""
    want = set(ids)
    return [{"path": p["path"], "name": p["name"], "tags": list(p["tags"]), "gender": p["gender"]}
            for p in portraits.library() if p["id"] in want]


def pictures_in(folder: str) -> List[dict]:
    """Every picture in a folder (and its subfolders) as an entry. A subfolder named like a tag ('race-dwarf',
    'class fighter', 'creature_undead') tags its pictures so; 'female'/'male' sets their gender; any other subfolder
    name becomes a 'folk:' tag. A picture named 'f_...' or 'm_...' is a woman's or a man's."""
    out = []
    for root, dirs, files in os.walk(folder):
        dirs[:] = sorted(d for d in dirs if not d.startswith("."))
        rel = os.path.relpath(root, folder)
        tags, gender = [], ""
        for part in ([] if rel == "." else rel.split(os.sep)):
            low = part.strip().lower()
            m = re.fullmatch(r"(race|class|folk|creature)[\s_:-]+(.+)", low)
            if m:
                tags.append(f"{m.group(1)}:{_slug(m.group(2))}")
            elif low in ("female", "women", "woman", "f"):
                gender = "f"
            elif low in ("male", "men", "man", "m"):
                gender = "m"
            elif _slug(low):
                tags.append("folk:" + _slug(low))
        for f in sorted(files):
            stem, ext = os.path.splitext(f)
            if ext.lower() not in PICTURES or f.startswith("."):
                continue
            g = gender or ({"f": "f", "m": "m"}.get(stem[:2].lower().rstrip("_-")) if re.match(r"^[fm][_-]", stem, re.I)
                           else "")
            out.append({"path": os.path.join(root, f), "name": "", "tags": list(tags), "gender": g or ""})
    return out


# ====================================================================== making a module
def _image(path: str):
    try:
        from PIL import Image
    except ImportError:
        raise ServiceError("Making portrait modules needs the Pillow package (py -m pip install pillow).")
    try:
        img = Image.open(path)
        img.load()
    except (OSError, ValueError) as e:
        raise ServiceError(f"{os.path.basename(path)} isn't a picture that can be read ({e}).")
    return img.convert("RGBA")


def _write_webp(img, path: str) -> None:
    buf = io.BytesIO()
    img.save(buf, "WEBP", quality=86, method=4)
    with open(path, "wb") as f:
        f.write(buf.getvalue())


def _thumb(img):
    """A THUMB px square round the face: for a tall portrait the face is FACE of the way down."""
    from PIL import Image
    w, h = img.size
    side = min(w, h)
    left = (w - side) // 2
    top = max(0, min(h - side, int(h * portraits.FACE - side / 2))) if h > w else (h - side) // 2
    return img.crop((left, top, left + side, top + side)).resize((THUMB, THUMB), Image.LANCZOS)


def write_module(folder: str, entries: List[dict], name: str, version: str = "1.0", author: str = "",
                 description: str = "", module_id: str = "",
                 progress: Optional[Callable[[int, int], None]] = None) -> dict:
    """Write a portrait module folder (module.json + assets/portraits) from entries; returns its module.json."""
    from PIL import Image
    entries = [e for e in entries if e.get("path") and os.path.isfile(e["path"])]
    if not entries:
        raise ServiceError("There are no portraits to put in the module.")
    name = (name or "").strip() or "My portraits"
    mid = module_id or "portraits-" + (_slug(name) or "mine")
    if not packages.ID_RX.match(mid):
        raise ServiceError(f"'{mid}' can't be a module's id.")
    base = os.path.join(folder, "assets", "portraits")
    os.makedirs(os.path.join(base, "pics"), exist_ok=True)
    os.makedirs(os.path.join(base, "thumbs"), exist_ok=True)
    pack = _slug(mid) or "mine"
    rows = []
    for n, e in enumerate(entries, 1):
        img = _image(e["path"])
        if max(img.size) > MAX_SIDE:
            k = MAX_SIDE / max(img.size)
            img = img.resize((max(1, round(img.width * k)), max(1, round(img.height * k))), Image.LANCZOS)
        pid = f"{pack}-{n:04d}"
        _write_webp(img, os.path.join(base, "pics", pid + ".webp"))
        _write_webp(_thumb(img), os.path.join(base, "thumbs", pid + ".webp"))
        tags = [t for t in dict.fromkeys(str(t) for t in e.get("tags") or []) if ":" in t and not t.startswith("pack:")]
        rows.append({"id": pid, "tags": tags + [f"pack:{pack}"], "gender": e.get("gender") or "",
                     "name": e.get("name") or ""})
        if progress:
            progress(n, len(entries))
    with open(os.path.join(base, "index.json"), "w", encoding="utf-8") as f:
        json.dump({"packs": {pack: {"title": name, "url": ""}}, "portraits": rows}, f, ensure_ascii=False, indent=1)
    meta = {"id": mid, "name": name, "version": str(version or "1.0"), "kind": "assets", "format": packages.FORMAT,
            "order": ORDER, "description": description or f"{len(rows)} portraits for the portrait library.",
            "credits": author or "", "license": ""}
    with open(os.path.join(folder, "module.json"), "w", encoding="utf-8") as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    return meta


def export(entries: List[dict], dest: str, name: str, version: str = "1.0", author: str = "", description: str = "",
           progress: Optional[Callable[[int, int], None]] = None) -> str:
    """Make a portrait module (.dmmod) of these entries at dest (a file, or a folder to put '<id>-<version>.dmmod' in);
    returns the file's path."""
    work = tempfile.mkdtemp(prefix="portraits-")
    try:
        write_module(work, entries, name, version, author, description, progress=progress)
        try:
            return packages.pack_folder(work, dest)
        except packages.PackageError as e:
            raise ServiceError(str(e))
    finally:
        shutil.rmtree(work, ignore_errors=True)


def import_path(path: str, name: str = "", progress: Optional[Callable[[int, int], None]] = None) -> dict:
    """Bring portraits in: a .dmmod file or a module folder is installed as it is; a folder of pictures (or one
    picture) becomes a portrait module named `name` (else after the folder) first. Returns the module.json."""
    from . import modules
    if os.path.isfile(path) and path.lower().endswith(packages.EXTENSIONS) or \
            os.path.isdir(path) and os.path.isfile(os.path.join(path, "module.json")):
        return modules.install(path, progress)
    if os.path.isdir(path):
        entries = pictures_in(path)
        title = name or os.path.basename(os.path.normpath(path))
    elif os.path.isfile(path) and path.lower().endswith(PICTURES):
        entries = [{"path": path, "name": "", "tags": [], "gender": ""}]
        title = name or os.path.splitext(os.path.basename(path))[0]
    else:
        raise ServiceError("That is neither a module nor a picture or a folder of pictures.")
    if not entries:
        raise ServiceError("There are no pictures in that folder.")
    work = tempfile.mkdtemp(prefix="portraits-")
    try:
        mid = "portraits-" + (_slug(title) or "imported")
        taken = {m["id"] for m in packages.all_modules()}
        if mid in taken:                                  # a folder of the same name brought in before: a module of its own
            mid = f"{mid[:50]}-{int(time.time()) % 100000}"
        write_module(os.path.join(work, mid), entries, title, module_id=mid, progress=progress)
        file = packages.pack_folder(os.path.join(work, mid), work)
        return modules.install(file)
    finally:
        shutil.rmtree(work, ignore_errors=True)
