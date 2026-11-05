"""The D&D 5e character: persistent state plus every derived stat.

State lives in a plain dict (`Character.d`) so it saves as JSON; everything else
(modifiers, AC, saves, spell slots, attacks...) is computed from that state and
the imported rules data, so nothing can drift out of sync.
"""
import copy
import json
import os
import re
import threading
import time
import zlib
from typing import Dict, List, Optional, Tuple

from ..core.storage import clone, list_json_names, write_text
from ..core.userdata import backup_character, keep_copy
from . import engine as E
from . import feat_extras as FE
from .data import rules

CHARACTERS_FOLDER = "data/characters"
SCHEMA = 2

SKILLS = ["Acrobatics", "Animal Handling", "Arcana", "Athletics", "Deception", "History", "Insight",
          "Intimidation", "Investigation", "Medicine", "Nature", "Perception", "Performance", "Persuasion",
          "Religion", "Sleight of Hand", "Stealth", "Survival"]
CONDITIONS = ["Blinded", "Charmed", "Deafened", "Exhaustion", "Frightened", "Grappled", "Incapacitated",
              "Invisible", "Paralyzed", "Petrified", "Poisoned", "Prone", "Restrained", "Stunned", "Unconscious"]
MAX_ATTUNED = 3

# Class features that give HP per level / skill bonuses etc. are detected by name from the rules text.
HP_PER_LEVEL_FEATURES = {"Dwarven Toughness": 1, "Draconic Resilience": 1}


def blank(name: str) -> dict:
    return {
        "schema": SCHEMA, "name": name, "race": None, "subrace": None, "ancestry": None, "background": None,
        "alignment": "", "xp": 0, "classes": [],
        "abilities": {"base": {a: 10 for a in E.ABILITIES}, "racial": {}, "improvement": {}, "feat": {}},
        "hp": {"gains": [], "current": 0, "temp": 0, "bonus": 0},
        "hit_dice_used": {}, "death_saves": {"success": 0, "failure": 0},
        "proficiencies": {"skills": [], "expertise": [], "saves": [], "tools": [], "languages": [],
                          "armor": [], "weapons": []},
        "feats": [], "options": [], "racial_spells": [], "spells": {}, "slots_used": {},
        "inventory": [], "currency": {c: 0 for c in E.COINS},
        "conditions": [], "exhaustion": 0, "inspiration": False, "resources": {},
        "details": {"personality": "", "ideal": "", "bond": "", "flaw": "", "appearance": "", "backstory": "",
                    "gender": "", "age": "", "height": "", "weight": "", "eyes": "", "hair": "", "skin": "", "deity": ""},
        "choices": {}, "notes": [], "next_note_id": 1, "ability_method": "", "sources": ["PHB"],
        "portrait": {}, "origin": {},
    }


def _migrate(data: dict) -> dict:
    """Fill defaults for fields added after a character was saved."""
    base = blank(data.get("name", ""))
    for key, value in base.items():                    # blank() is new each call: its values need no copy
        data.setdefault(key, value)
    for key, value in base["abilities"].items():
        data["abilities"].setdefault(key, value)
    for key, value in base["proficiencies"].items():
        data["proficiencies"].setdefault(key, [])
    for key, value in base["details"].items():
        data["details"].setdefault(key, "")
    return data


_TEXTS: Dict[str, tuple] = {}                          # absolute path -> ((mtime_ns, size), file text)
_TEXTS_LOCK = threading.Lock()
_DATA: Dict[str, tuple] = {}                           # absolute path -> ((mtime_ns, size), the sheet as loaded and filled in)
_PEEKS: Dict[str, tuple] = {}                          # absolute path -> ((mtime_ns, size), a shared read-only Character, checked at)
_SAVES = [0]                                           # goes up whenever this program writes or deletes a character
_MEMORY: Dict[str, list] = {}                          # name -> [the sheet, a shared read-only Character or None, its save number]:
                                                       # sheets that live in memory only (a duel's fighters, services/duel)


def hold_in_memory(char: "Character") -> None:
    """Keep this character in memory only, under its name: from now on loading, peeking and saving it never touch the
    disk (nothing of it is ever written). forget_memory() lets it go."""
    with _TEXTS_LOCK:
        _SAVES[0] += 1
        _MEMORY[char.name] = [clone(char.d), None, _SAVES[0]]
    _STAMPS.pop(char.name, None)


def forget_memory(name: str) -> None:
    with _TEXTS_LOCK:
        if _MEMORY.pop(name, None) is not None:
            _SAVES[0] += 1
    _STAMPS.pop(name, None)


def in_memory(name) -> bool:
    """A sheet kept in memory only (hold_in_memory)."""
    return name in _MEMORY


def _forget(path: str):
    with _TEXTS_LOCK:
        _TEXTS.pop(os.path.abspath(path), None)
        _DATA.pop(os.path.abspath(path), None)
        _PEEKS.pop(os.path.abspath(path), None)
        _SAVES[0] += 1
    _STAMPS.clear()


def forget_kept():
    """The rules changed (homebrew items, sources): sheets read again (their worked-out numbers may differ)."""
    with _TEXTS_LOCK:
        _DATA.clear()
        _PEEKS.clear()
        for kept in _MEMORY.values():
            kept[1] = None
        _SAVES[0] += 1


def saves() -> int:
    """A number that changes whenever a character is saved or deleted here (screens keep views until it does)."""
    return _SAVES[0]


def file_stamp(name: str) -> Optional[tuple]:
    """(modified time, size) of a character's file, None when it has none: changes when the file is edited outside.
    Looked at again at most once a second (screens ask on every refresh; saves here change saves() at once)."""
    kept = _MEMORY.get(name)
    if kept is not None:                               # a sheet in memory: its save number
        return 0, kept[2]
    now = time.monotonic()
    hit = _STAMPS.get(name)
    if hit and now - hit[0] < 1.0:
        return hit[1]
    try:
        st = os.stat(Character._path(name))
        stamp = st.st_mtime_ns, st.st_size
    except (OSError, ValueError):
        stamp = None
    _STAMPS[name] = (now, stamp)
    return stamp


_STAMPS: Dict[str, tuple] = {}                         # name -> (checked at, file_stamp)
_LISTED: Dict[str, tuple] = {}                         # "kv" -> ((folder, its mtime, saves), names, checked at)


def revision(name: str) -> Optional[int]:
    """A checksum of the character's file as it is now (None: no file): a sheet window built from the same one needn't be
    built again. The text is the kept one while the file is unchanged."""
    kept = _MEMORY.get(name)
    if kept is not None:
        return kept[2]
    try:
        path = Character._path(name)
        st = os.stat(path)
    except (OSError, ValueError):
        return None
    stamp = (st.st_mtime_ns, st.st_size)
    with _TEXTS_LOCK:
        hit = _TEXTS.get(os.path.abspath(path))
    if hit and hit[0] == stamp:
        return zlib.crc32(hit[1].encode("utf-8"))
    try:
        with open(path, "rb") as f:
            return zlib.crc32(f.read())
    except OSError:
        return None


def _read_cached(path: str):
    """The parsed JSON of a character file, from the kept text while the file hasn't changed."""
    key = os.path.abspath(path)
    try:
        st = os.stat(path)
    except OSError:
        _forget(path)
        return None
    stamp = (st.st_mtime_ns, st.st_size)
    with _TEXTS_LOCK:
        hit = _TEXTS.get(key)
    if hit and hit[0] == stamp:
        text = hit[1]
    else:
        try:
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
        except OSError:
            return None
        with _TEXTS_LOCK:
            _TEXTS[key] = (stamp, text)
    try:
        return json.loads(text)
    except ValueError:
        return None


def _stem(name: str) -> frozenset:
    """'Crossbow, light' and 'light crossbows' both -> {'crossbow', 'light'}."""
    return frozenset(w[:-1] if w.endswith("s") and len(w) > 3 else w
                     for w in re.split(r"[ ,]+", name.lower()) if w)


# ---------------------------------------------------------------------- charges of a stack
# A pack entry of 2 Wands of Magic Missiles holds both wands' charges (14): the entry's `charges_left` is the stack's,
# each wand in it regains its own 1d6 + 1 at dawn, a wand added comes full and one taken away takes what the rest can't hold.
def fresh_charges(name: str, qty: int = 1) -> int:
    """The charges `qty` new copies of an item come with (a Luck Blade's "1d4 - 1": rolled for each)."""
    n = (rules.item(name) or {}).get("charges") or 0
    if isinstance(n, str) and not n.isdigit():
        from .dice import roll_dice
        return sum(max(0, int(roll_dice(re.sub(r"[−–]", "-", n).replace(" ", "")).total)) for _ in range(max(0, int(qty))))
    return int(n) * max(0, int(qty))


def charge_max(entry: dict) -> Optional[int]:
    """The most charges a pack entry can hold (the item's number times the stack), None when it is rolled (a Luck Blade)."""
    n = (rules.item(entry.get("name") or "") or {}).get("charges")
    return int(n) * max(1, int(entry.get("qty") or 1)) if str(n or "").isdigit() else None


def cap_charges(entry: dict) -> None:
    """After some of a stack are taken away: no more charges than the ones left can hold."""
    top = charge_max(entry)
    if top is not None and entry.get("charges_left") is not None and int(entry["charges_left"]) > top:
        entry["charges_left"] = top


def charges_taken(stack: dict, qty: int) -> Optional[int]:
    """The charges `qty` items taken off a stack (a pack entry, a ground stack, the team's) carry with them: what the ones staying
    can't hold, so no charge is made or lost on the way (None: never counted, so they are full). A rolled count (a Luck Blade's):
    their share."""
    left, n = stack.get("charges_left"), max(1, int(stack.get("qty") or 1))
    if left is None:
        return None
    if qty >= n:
        return int(left)
    top = charge_max(dict(stack, qty=n - qty))
    return max(0, int(left) - top) if top is not None else int(left) * qty // n


def take_charges(stack: dict, qty: int) -> Optional[int]:
    """`charges_taken`, and the stack keeps the rest (call it before the stack's qty goes down)."""
    taken = charges_taken(stack, qty)
    if taken is not None and qty < int(stack.get("qty") or 1):
        stack["charges_left"] = int(stack["charges_left"]) - taken
    return taken


def merge_charges(stack: dict, old_qty: int, qty: int, charges: Optional[int] = None) -> None:
    """`qty` items carrying `charges` (None: full) joined a stack of `old_qty` (its qty already raised): the stack's count after.
    Nothing is written while neither side was ever counted (both full)."""
    if charges is None and stack.get("charges_left") is None:
        return
    have = stack["charges_left"] if stack.get("charges_left") is not None else fresh_charges(stack["name"], old_qty)
    stack["charges_left"] = int(have) + (int(charges) if charges is not None else fresh_charges(stack["name"], qty))


def resize_charges(stack: dict, old_qty: int) -> None:
    """A stack's amount set by hand (the DM's editor): more items come full, fewer keep only what they can hold."""
    if stack.get("charges_left") is None:
        return
    if int(stack["qty"]) > old_qty:
        stack["charges_left"] = int(stack["charges_left"]) + fresh_charges(stack["name"], int(stack["qty"]) - old_qty)
    else:
        cap_charges(stack)


class Character:
    def __init__(self, data: dict):
        self.d = _migrate(data)
        from .leveling import catch_up_subclass_grants
        catch_up_subclass_grants(self)

    # ------------------------------------------------------------------ storage
    @staticmethod
    def _path(name: str) -> str:
        if name in (".", "..") or set(str(name)) & set("\\/:"):      # a name never climbs out of the folder
            raise ValueError(f"'{name}' isn't a valid character name.")
        return os.path.join(CHARACTERS_FOLDER, f"{name}.json")

    @classmethod
    def create_blank(cls, name: str) -> "Character":
        return cls(blank(name))

    def to_dict(self) -> dict:
        return self.d

    @classmethod
    def from_dict(cls, data: dict) -> "Character":
        return cls(copy.deepcopy(data))

    @property
    def transient(self) -> bool:
        """Kept in memory only (a duel's fighter): saving it writes nothing."""
        return self.d.get("name") in _MEMORY

    def save(self):
        if self.transient:
            with _TEXTS_LOCK:
                _SAVES[0] += 1
                _MEMORY[self.name] = [clone(self.d), None, _SAVES[0]]
            return
        path = self._path(self.name)
        backup_character(path)                         # the earlier version goes to backups/characters/<name>/
        _forget(path)
        text = json.dumps(self.d, indent=2, ensure_ascii=False)
        write_text(path, text)
        _forget(path)
        try:                                           # kept as written: the next load needn't open the file (on Windows the
            st = os.stat(path)                         # virus scanner checks a file just written: ~3 ms an open)
        except OSError:
            return
        with _TEXTS_LOCK:
            _TEXTS[os.path.abspath(path)] = ((st.st_mtime_ns, st.st_size), text)

    @classmethod
    def peek(cls, name: str) -> Optional["Character"]:
        """The character only to read - never change or save it: one shared object per version of the file (load()
        gives every caller its own). The battle's HP and "is it down" checks ask hundreds of times an action."""
        kept = _MEMORY.get(name)
        if kept is not None:
            if kept[1] is None:
                c = cls.__new__(cls)
                c.d = clone(kept[0])
                c._frozen = {}
                kept[1] = c
            return kept[1]
        now = time.monotonic()
        try:
            path = cls._path(name)
            key = os.path.abspath(path)
            hit = _PEEKS.get(key)
            if hit and now - hit[2] < 0.5:             # looked at just now (one action asks again and again): a save here
                return hit[1]                          # drops it at once, an edit outside is seen half a second later
            st = os.stat(path)
        except (ValueError, OSError):
            return None
        stamp = (st.st_mtime_ns, st.st_size)
        if hit and hit[0] == stamp:
            _PEEKS[key] = (stamp, hit[1], now)
            return hit[1]
        c = cls.load(name)
        if c is not None:
            c._frozen = {}
            _PEEKS[key] = (stamp, c, now)
        return c

    @classmethod
    def load(cls, name: str) -> Optional["Character"]:
        """A fresh Character read from its file. The file's text is kept while the file is unchanged (same time and
        size), so a busy battle screen doesn't read every sheet from disk again; every call still parses a new copy."""
        kept = _MEMORY.get(name)
        if kept is not None:                           # kept in memory only: a copy of it
            c = cls.__new__(cls)
            c.d = clone(kept[0])
            return c
        try:
            path = cls._path(name)
            st = os.stat(path)
        except ValueError:
            return None
        except OSError:
            _forget(path)
            return None
        stamp, key = (st.st_mtime_ns, st.st_size), os.path.abspath(path)
        hit = _DATA.get(key)
        if hit and hit[0] == stamp:                    # read and filled in already: a copy of that (a battle action loads
            c = cls.__new__(cls)                       # a sheet a hundred times; parsing each was most of its time)
            c.d = clone(hit[1])
            return c
        data = _read_cached(path)
        if not data:
            return None
        c = cls(data)
        _DATA[key] = (stamp, clone(c.d))
        return c

    @classmethod
    def delete(cls, name: str) -> bool:
        if name in _MEMORY:
            forget_memory(name)
            return True
        path = cls._path(name)
        _forget(path)
        if os.path.exists(path):
            keep_copy(path, "deleted")
            os.remove(path)
            return True
        return False

    @classmethod
    def list_characters(cls) -> List[str]:
        """Every character's name, read again only when the folder changed (a file added, removed or renamed). The
        folder is looked at once a second at most; a save or delete here is seen at once."""
        now = time.monotonic()
        hit = _LISTED.get("kv")
        folder = os.path.abspath(CHARACTERS_FOLDER)
        if hit and hit[0][0] == folder and hit[0][2] == _SAVES[0] and now - hit[2] < 1.0:
            return list(hit[1])
        try:
            st = os.stat(CHARACTERS_FOLDER)
        except OSError:
            return list_json_names(CHARACTERS_FOLDER)
        key = (folder, st.st_mtime_ns, _SAVES[0])
        names = hit[1] if hit and hit[0] == key else list_json_names(CHARACTERS_FOLDER)
        _LISTED["kv"] = (key, names, now)
        return list(names)

    @classmethod
    def load_all(cls) -> List["Character"]:
        return [c for c in (cls.load(n) for n in cls.list_characters()) if c]

    # ------------------------------------------------------------------ simple fields
    name = property(lambda s: s.d["name"], lambda s, v: s.d.__setitem__("name", v))
    race = property(lambda s: s.d["race"])
    subrace = property(lambda s: s.d["subrace"])
    ancestry = property(lambda s: s.d["ancestry"])
    background = property(lambda s: s.d["background"])
    alignment = property(lambda s: s.d["alignment"], lambda s, v: s.d.__setitem__("alignment", v))
    xp = property(lambda s: s.d["xp"], lambda s, v: s.d.__setitem__("xp", int(v)))
    classes = property(lambda s: s.d["classes"])
    inventory = property(lambda s: s.d["inventory"])
    notes = property(lambda s: s.d["notes"])
    details = property(lambda s: s.d["details"])
    currency = property(lambda s: s.d["currency"])
    conditions = property(lambda s: s.d["conditions"])
    current_hp = property(lambda s: s.d["hp"]["current"], lambda s, v: s.d["hp"].__setitem__("current", int(v)))
    temp_hp = property(lambda s: s.d["hp"]["temp"], lambda s, v: s.d["hp"].__setitem__("temp", max(0, int(v))))

    @property
    def sources(self) -> tuple:
        """Sourcebooks this character may draw new spells, feats and options from: the ones ticked in the Sourcebooks
        window (what it already has stays, whatever its book). Its own d["sources"] only records the books it was made
        with."""
        return tuple(rules.active_sources)

    @property
    def total_level(self) -> int:
        return sum(c["level"] for c in self.classes)

    @property
    def is_created(self) -> bool:
        return bool(self.classes)

    @property
    def class_summary(self) -> str:
        """'Wizard 3 / Fighter 1'."""
        parts = [f"{c['name']} {c['level']}" for c in self.classes]
        return " / ".join(parts) if parts else "No class"

    @property
    def race_display(self) -> str:
        if not self.race:
            return "No race"
        if self.subrace and self.subrace != "Variant":
            return f"{self.subrace} {self.race}"
        if self.subrace == "Variant":
            return f"Variant {self.race}"
        return self.race

    def class_level(self, name: str) -> int:
        return next((c["level"] for c in self.classes if c["name"] == name), 0)

    def class_entry(self, name: str) -> Optional[dict]:
        return next((c for c in self.classes if c["name"] == name), None)

    @property
    def level_from_xp(self) -> int:
        return E.level_for_xp(self.xp)

    @property
    def can_level_up(self) -> bool:
        return self.is_created and self.total_level < min(E.MAX_LEVEL, self.level_from_xp)

    # ------------------------------------------------------------------ race / feature sources
    def race_data(self) -> Optional[dict]:
        """The race merged with its subrace: speed, darkvision, traits, proficiencies, resistances."""
        race = rules.races.get(self.race) if self.race else None
        if not race:
            return None
        merged = {"speed": dict(race["speed"]), "darkvision": race["darkvision"], "size": race["size"],
                  "traits": list(race["traits"]), "resist": list(race.get("resist", [])),
                  "spells": list(race["spells"]), "feats": race.get("feats", 0)}
        sub = next((s for s in race["subraces"] if s["name"] == self.subrace), None)
        if sub:
            if sub["speed"]:
                merged["speed"].update(sub["speed"])
            merged["darkvision"] = max(merged["darkvision"], sub["darkvision"])
            overwritten = {t["overwrite"] for t in sub["traits"] if t.get("overwrite")}
            merged["traits"] = [t for t in merged["traits"] if t["name"] not in overwritten] + sub["traits"]
            merged["resist"] += sub.get("resist", [])
            merged["spells"] += sub["spells"]
            merged["feats"] += sub.get("feats", 0)
        if self.ancestry and race["ancestries"]:
            anc = next((a for a in race["ancestries"] if a["name"] == self.ancestry), None)
            if anc:
                merged["traits"] = [t for t in merged["traits"] if t["name"] not in ("Draconic Ancestry",)]
                merged["traits"].append({"name": f"Draconic Ancestry ({anc['name']})",
                                         "text": f"Damage type: {anc['damage']}. Breath weapon: {anc['area']} "
                                                 f"({anc['save']} save). Resistance: {anc['damage']}."})
                merged["resist"].append(anc["damage"])
        merged["resist"] += FE.resistances(self)                 # Dragonscarred's pick, Mark of Storm, Boon of the Soul Drinker... (feat_extras.py)
        return merged

    def features(self) -> List[dict]:
        """Everything the character can do, in reading order: race, background, class, subclass, feats, options."""
        out: List[dict] = []
        from .data import NOT_INSTALLED
        race = self.race_data()
        race_book = (rules.races.get(self.race) or {}).get("source", "")
        if self.race and not race:
            out.append({"source": f"Race: {self.race_display}", "name": self.race, "level": 1, "text": NOT_INSTALLED,
                        "book": "", "missing": True})
        if race:
            skip = {"Age", "Size", "Languages", "Speed", "Alignment"}
            for t in race["traits"]:
                if t["name"] not in skip:
                    out.append({"source": f"Race: {self.race_display}", "name": t["name"], "level": 1,
                                "text": t["text"], "book": race_book})
        bg = rules.backgrounds.get(self.background) if self.background else None
        if self.background and not bg:
            out.append({"source": f"Background: {self.background}", "name": self.background, "level": 1,
                        "text": NOT_INSTALLED, "book": "", "missing": True})
        if bg and bg.get("feature"):
            out.append({"source": f"Background: {bg['name']}", "name": bg["feature"]["name"], "level": 1,
                        "text": bg["feature"]["text"], "book": bg.get("source", "")})
        for entry in self.classes:
            cls = rules.classes[entry["name"]]
            title = cls.get("subclass_title") or ""
            if cls.get("missing"):
                out.append({"source": f"Class: {cls['name']}", "name": cls["name"], "level": 1, "text": NOT_INSTALLED,
                            "book": "", "missing": True})
            for f in cls["features"]:
                if f["level"] <= entry["level"] and f["name"] not in (title, f"{title} feature"):
                    out.append({"source": f"Class: {cls['name']}", "name": f["name"], "level": f["level"],
                                "text": f["text"], "book": cls.get("source", "")})
            sub = rules.subclass(cls["name"], entry["subclass"]) if entry.get("subclass") else None
            if entry.get("subclass") and not sub:
                out.append({"source": f"{title or 'Subclass'}: {entry['subclass']}", "name": entry["subclass"],
                            "level": 1, "text": NOT_INSTALLED, "book": "", "missing": True})
            if sub:
                for f in sub["features"]:
                    if f["level"] <= entry["level"]:
                        out.append({"source": f"{title or 'Subclass'}: {sub['name']}", "name": f["name"],
                                    "level": f["level"], "text": f["text"], "book": sub.get("source", "")})
        for name in self.d["feats"]:
            feat = rules.feats.get(name)
            out.append({"source": "Feat", "name": name, "level": 0, "text": feat["text"] if feat else NOT_INSTALLED,
                        "book": feat["source"] if feat else "", **({} if feat else {"missing": True})})
        for name in self.d["options"]:
            opt = rules.optional_features.get(name)
            out.append({"source": "Choice", "name": name, "level": 0, "text": opt["text"] if opt else NOT_INSTALLED,
                        "book": opt["source"] if opt else "", **({} if opt else {"missing": True})})
        return out

    def _feature_names(self) -> set:
        key = (self.d["race"], self.d["subrace"], self.d["ancestry"], self.d["background"],
               tuple((c["name"], c["level"], c.get("subclass")) for c in self.classes),
               tuple(self.d["feats"]), tuple(self.d["options"]))
        if getattr(self, "_fn_key", None) != key:
            self._fn_key = key
            self._fn_names = {f["name"].lower() for f in self.features()}
        return self._fn_names

    def has_feature(self, name: str) -> bool:
        low = name.lower()
        if low not in self._feature_names():
            return False
        from .combat_feats import unpicked              # a Hunter's Evasion when it picked Uncanny Dodge: not had
        return not unpicked(self, low)

    def has_option(self, name: str) -> bool:
        return name in self.d["options"]

    # ------------------------------------------------------------------ equipment lookups
    def item_data(self, entry: dict) -> Optional[dict]:
        return rules.item(entry["name"])

    def _active_items(self) -> List[Tuple[dict, dict]]:
        """Equipped items whose effects apply (attuned when required): [(inventory entry, item data)]. A sheet frozen for
        a battle menu (`_frozen`, nothing changes in it) works them out once."""
        fz = getattr(self, "_frozen", None)
        if fz is not None:
            if "items" not in fz:
                fz["items"] = self._find_active_items()
            return list(fz["items"])
        return self._find_active_items()

    def _find_active_items(self) -> List[Tuple[dict, dict]]:
        out = []
        for entry in self.inventory:
            data = self.item_data(entry)
            if not data or not entry.get("equipped"):
                continue
            if data.get("attune") is not None and not entry.get("attuned"):
                continue
            out.append((entry, data))
        return out

    def equipped_armor(self) -> Optional[dict]:
        return next((d for e, d in self._active_items() if d["type"] in ("LA", "MA", "HA")), None)

    def equipped_shield(self) -> Optional[dict]:
        return next((d for e, d in self._active_items() if d["type"] == "S"), None)

    @property
    def attuned_count(self) -> int:
        return sum(1 for e in self.inventory if e.get("attuned"))

    # ------------------------------------------------------------------ abilities
    def ability_base(self, ability: str) -> int:
        return self.d["abilities"]["base"][ability]

    def ability_score(self, ability: str) -> int:
        fz = getattr(self, "_frozen", None)
        if fz is not None:
            k = "ab:" + ability
            if k not in fz:
                fz[k] = self._ability_score(ability)
            return fz[k]
        return self._ability_score(ability)

    def _ability_score(self, ability: str) -> int:
        a = self.d["abilities"]
        score = (a["base"].get(ability, 10) + a["racial"].get(ability, 0) + a["improvement"].get(ability, 0)
                 + a["feat"].get(ability, 0))
        if ability in ("str", "con") and self.class_level("Barbarian") >= 20:   # Primal Champion: +4, up to 24
            score = min(score + 4, E.MAX_ABILITY + 4)
        else:
            score = min(score, E.MAX_ABILITY)
        items = self._active_items()
        for _entry, item in items:                 # Belt of Dwarvenkind, an Ioun stone: +2, up to a maximum (20 unless it says)
            up = (item.get("ability") or {}).get(ability)
            if isinstance(up, int) and not item.get("ability_permanent") and (not item.get("weapon") or item.get("ability_max")):    # (Volendrung: +2, to 22)
                score = max(score, min(score + up, item.get("ability_max") or E.MAX_ABILITY))
        for _entry, item in items:                 # e.g. Gauntlets of Ogre Power set Strength to 19
            static = (item.get("ability") or {}).get("static", {})
            if ability in static and static[ability] > score:
                score = static[ability]
        return max(0, score - int((self.d.get("ability_drain") or {}).get(ability, 0)))   # a shadow's Strength Drain

    def ability_scores(self) -> Dict[str, int]:
        return {a: self.ability_score(a) for a in E.ABILITIES}

    def mod(self, ability: str) -> int:
        return E.modifier(self.ability_score(ability))

    @property
    def proficiency_bonus(self) -> int:
        mastery = any(e.get("equipped") and e.get("attuned") and e.get("name") == "Ioun Stone, Mastery" for e in self.inventory)
        return E.proficiency_bonus(self.total_level or 1) + (1 if mastery else 0)       # an Ioun stone of mastery: +1

    # ------------------------------------------------------------------ skills & saves
    def _bonus_all_saves(self) -> int:
        bonus = sum(item.get("bonus_save") or 0 for _e, item in self._active_items())
        if self.has_feature("Aura of Protection") and self.current_hp > 0:
            bonus += max(1, self.mod("cha"))
        return bonus

    def save_proficient(self, ability: str) -> bool:
        return ability in self.d["proficiencies"]["saves"]

    def saving_throws(self) -> Dict[str, dict]:
        return {a: {"bonus": self.mod(a) + (self.proficiency_bonus if self.save_proficient(a) else 0)
                    + self._bonus_all_saves(), "proficient": self.save_proficient(a)} for a in E.ABILITIES}

    def skill_bonus(self, skill: str) -> dict:
        ability = rules.skills[skill]["ability"]
        prof = skill in self.d["proficiencies"]["skills"]
        expert = skill in self.d["proficiencies"]["expertise"]
        pb = self.proficiency_bonus
        bonus = self.mod(ability)
        if expert:
            bonus += 2 * pb
        elif prof:
            bonus += pb
        elif self.has_feature("Jack of All Trades"):
            bonus += pb // 2
        elif ability in ("str", "dex", "con") and self.has_feature("Remarkable Athlete"):
            bonus += (pb + 1) // 2
        bonus += sum((d.get("bonus_skill") or {}).get(skill, 0) for _e, d in self._active_items())     # Eyes of Deceit: +5 Deception (item_fixes.py)
        return {"ability": ability, "bonus": bonus, "proficient": prof, "expertise": expert}

    def skills(self) -> Dict[str, dict]:
        return {s: self.skill_bonus(s) for s in SKILLS}

    @property
    def passive_perception(self) -> int:
        return 10 + self.skill_bonus("Perception")["bonus"] + (5 if "Observant" in self.d["feats"] else 0)

    @property
    def initiative(self) -> int:
        bonus = self.mod("dex") + (5 if "Alert" in self.d["feats"] else 0)
        if self.has_feature("Jack of All Trades"):
            bonus += self.proficiency_bonus // 2
        if self.has_feature("Hare-Trigger"):                    # a harengon adds its proficiency bonus to initiative
            bonus += self.proficiency_bonus
        return bonus + sum(d.get("bonus_init") or 0 for _e, d in self._active_items())     # Scorpion Armor's +5

    # ------------------------------------------------------------------ movement
    @property
    def speed(self) -> int:
        race = self.race_data()
        speed = race["speed"].get("walk", 30) if race else 30
        armor = self.equipped_armor()
        if armor and armor.get("strength") and self.ability_score("str") < int(armor["strength"]):
            speed -= 10
        heavy = armor is not None and armor["type"] == "HA"
        if self.has_feature("Fast Movement") and not heavy and self.class_level("Barbarian") >= 5:
            speed += 10
        if self.has_feature("Unarmored Movement") and armor is None:
            speed += self.table_value("Monk", "Unarmored Movement", default=0, number=True)
        if "Mobile" in self.d["feats"]:
            speed += 10
        if "Squat Nimbleness" in self.d["feats"]:
            speed += 5
        return speed + FE.speed_bonus(self)                     # Mark of Passage, Transmuted Anatomy

    @property
    def darkvision(self) -> int:
        race = self.race_data()
        return race["darkvision"] if race else 0

    @property
    def size(self) -> str:
        race = self.race_data()
        return race["size"] if race else "Medium"

    def table_value(self, class_name: str, column: str, default=None, number: bool = False):
        """Current-level value of a class table column, e.g. ('Barbarian', 'Rages') -> '3'."""
        cls = rules.classes.get(class_name)
        level = self.class_level(class_name)
        if not cls or not level:
            return default
        cols = cls["table"]["cols"]
        if column not in cols:
            return default
        value = cls["table"]["rows"][level - 1][cols.index(column)]
        if number:
            m = re.search(r"-?\d+", str(value))
            return int(m.group()) if m else default
        return value

    # ------------------------------------------------------------------ hit points
    @property
    def hp_per_level_bonus(self) -> int:
        bonus = sum(v for name, v in HP_PER_LEVEL_FEATURES.items() if self.has_feature(name))
        if "Tough" in self.d["feats"]:
            bonus += 2
        return bonus + sum(d.get("hp_per_level") or 0 for _e, d in self._active_items())     # a Berserker Axe: +1 a level

    @property
    def max_hp(self) -> int:
        hp = self.d["hp"]
        level = self.total_level
        return max(1, sum(hp["gains"]) + self.mod("con") * level + self.hp_per_level_bonus * level + hp["bonus"]
                   - int(hp.get("drain") or 0))              # a wight's Life Drain: back after a long rest

    @property
    def hp_fraction(self) -> float:
        return max(0.0, min(1.0, self.current_hp / self.max_hp)) if self.max_hp > 0 else 0.0

    def hit_dice(self) -> Dict[str, dict]:
        """{'Wizard': {'die': 6, 'total': 3, 'used': 1}} - hit dice remaining = total - used."""
        out = {}
        for c in self.classes:
            out[c["name"]] = {"die": rules.classes[c["name"]]["hit_die"], "total": c["level"],
                              "used": min(self.d["hit_dice_used"].get(c["name"], 0), c["level"])}
        return out

    def damage(self, amount: int) -> int:
        """Damage hits temporary HP first. At 0 HP the character falls Unconscious (death saves are up to the table).
        Returns the total damage taken."""
        if amount <= 0:
            return 0
        absorbed = min(self.temp_hp, amount)
        self.temp_hp -= absorbed
        dealt = min(self.current_hp, amount - absorbed)
        self.current_hp -= dealt
        if self.current_hp == 0 and "Unconscious" not in self.d["conditions"]:
            self.d["conditions"].append("Unconscious")
        return absorbed + dealt

    def heal(self, amount: int) -> int:
        if amount <= 0:
            return 0
        before = self.current_hp
        self.current_hp = min(self.max_hp, before + amount)
        if before == 0 and self.current_hp > 0:
            self.d["death_saves"] = {"success": 0, "failure": 0}
            if "Unconscious" in self.d["conditions"]:
                self.d["conditions"].remove("Unconscious")
        return self.current_hp - before

    # ------------------------------------------------------------------ armor class
    def armor_class(self) -> Tuple[int, str]:
        """Returns (AC, explanation)."""
        dex = self.mod("dex")
        armor, shield = self.equipped_armor(), self.equipped_shield()
        parts: List[str] = []
        if armor:
            cap = 99 if armor.get("full_dex") else 3 if "Medium Armor Master" in self.d["feats"] else 2     # full_dex: Serpent Scale Armor
            dex_part = dex if armor["type"] == "LA" else min(dex, cap) if armor["type"] == "MA" else 0
            ac = armor["ac"] + dex_part + (armor.get("bonus_ac") or 0)
            parts.append(f"{armor['name']} {armor['ac']}" + (f" {dex_part:+d} Dex" if dex_part else ""))
            if armor.get("bonus_ac"):
                parts.append(f"{armor['bonus_ac']:+d} magic")
            if self.has_option("Defense"):
                ac += 1
                parts.append("+1 Defense")
        else:
            ac, label = 10 + dex, "10 + Dex"
            if self.has_feature("Unarmored Defense"):
                if self.class_level("Barbarian"):
                    ac, label = 10 + dex + self.mod("con"), "10 + Dex + Con"
                if self.class_level("Monk") and not shield and 10 + dex + self.mod("wis") > ac:
                    ac, label = 10 + dex + self.mod("wis"), "10 + Dex + Wis"
            if (self.has_feature("Draconic Resilience") or "Dragon Hide" in self.d["feats"]) and 13 + dex > ac:
                ac, label = 13 + dex, "13 + Dex"
            parts.append(label)
        nat = self._natural_ac(dex)
        if nat:
            ac, parts = self._with_natural(ac, parts, armor, nat)
        if "Revenant Blade" in self.d["feats"] and not shield and any(e.get("equipped") and "double-bladed scimitar" in e["name"].lower() for e in self.inventory):
            ac += 1                                     # a double-bladed scimitar held in both hands (no shield)
            parts.append("+1 Revenant Blade")
        if shield:
            ac += shield["ac"] + (shield.get("bonus_ac") or 0)
            parts.append(f"Shield +{shield['ac'] + (shield.get('bonus_ac') or 0)}")
        for _e, item in self._active_items():
            if item["type"] not in ("LA", "MA", "HA", "S") and item.get("bonus_ac") and not (item.get("unarmored_only") and (armor or shield)) \
                    and not (item.get("no_shield_only") and shield):
                ac += item["bonus_ac"]
                parts.append(f"{item['name']} {item['bonus_ac']:+d}")
        return ac, ", ".join(parts)

    NATURAL_AC = re.compile(r"(?:base (?:AC|Armor Class)|your AC)(?: is| of) (\d+)(?:\s*\+\s*(?:your\s+)?(\w+?)(?: modifier)?[\s.,(])?", re.I)

    def _natural_ac(self, dex: int) -> Optional[dict]:
        """A race's natural armour (Tortle, Lizardfolk, Loxodon, Locathah, Autognome, Thri-kreen, Warforged): {'base': an AC or None,
        'add': a flat bonus, 'name', 'replaces': it stands in for worn armour}. Read from the trait's text."""
        out = {"base": None, "add": 0, "name": "", "replaces": False}
        for t in (self.race_data() or {}).get("traits") or []:
            text = t["text"]
            if t["name"] in ("Natural Armor", "Armored Casing", "Chameleon Carapace"):
                m = self.NATURAL_AC.search(text)
                if m:
                    ab = {"dexterity": "dex", "constitution": "con", "strength": "str", "wisdom": "wis"}.get((m.group(2) or "").lower())
                    base = int(m.group(1)) + (self.mod(ab) if ab else 0)
                    if base > (out["base"] or 0):
                        out.update(base=base, name=t["name"], replaces="gain no benefit from wearing armor" in text or "can't wear light" in text
                                   or "no benefit from wearing armor" in text)
                    continue
            if t["name"] in ("Natural Armor", "Integrated Protection"):
                m = re.search(r"\+(\d+) bonus to (?:Armor Class|AC)", text)
                if m:
                    out["add"] += int(m.group(1))
                    out["name"] = out["name"] or t["name"]
        return out if out["base"] or out["add"] else None

    def _with_natural(self, ac: int, parts: List[str], armor: Optional[dict], nat: dict):
        """The AC with the race's natural armour: the better of it and the worn armour's (a Tortle's shell instead of any armour)."""
        if nat["base"]:
            if nat["base"] > ac or (armor is not None and nat["replaces"]):
                ac = nat["base"]
                parts = [x for x in parts if not (armor and armor["name"] in x)] if armor else parts[:-1]
                parts.append(f"{nat['name']} {nat['base']}")
        if nat["add"]:
            ac += nat["add"]
            parts.append(f"{nat['name']} +{nat['add']}")
        return ac, parts

    # ------------------------------------------------------------------ proficiencies
    def weapon_proficient(self, item: dict) -> bool:
        profs = self.d["proficiencies"]["weapons"]
        category = item.get("category")
        if category and category in profs:
            return True
        stems = _stem(item["name"])
        if "bullet" in str(item.get("ammo_type") or "") and re.search(r"renaissance|modern", item["ammo_type"]) \
                and ("Gunner" in self.d["feats"] or self.has_feature("Firearms Mastery")):
            return True                                 # Gunner and a giff: proficient with every firearm
        return any(_stem(p) == stems for p in profs)

    def armor_proficient(self, item: dict) -> bool:
        kind = {"LA": "light", "MA": "medium", "HA": "heavy", "S": "shield"}.get(item["type"])
        return kind in self.d["proficiencies"]["armor"]

    # ------------------------------------------------------------------ attacks
    def attacks(self) -> List[dict]:
        """One entry per equipped weapon, plus an unarmed strike."""
        out = []
        pb = self.proficiency_bonus
        weapons = [(e, d) for e, d in self._active_items() if d.get("weapon")]
        melee_one_handed_only = len([1 for _e, d in weapons if d["type"] == "M"]) == 1 and not self.equipped_shield_is_weapon()
        archery = any(d["name"] == "Bracers of Archery" for _e, d in self._active_items())    # longbows and shortbows: proficient, +2 damage
        for entry, item in weapons:
            props = item.get("properties", [])
            ranged = item["type"] == "R"
            finesse = "finesse" in props
            if finesse:
                ability = "dex" if self.mod("dex") >= self.mod("str") else "str"
            else:
                ability = "dex" if ranged else "str"
            if "two-handed" not in props and self.mod("cha") > self.mod(ability) and self.has_feature("Hex Warrior"):
                ability = "cha"                         # a hexblade's weapon: Charisma for its attack and damage rolls
            if item.get("magic") and self.mod("int") > self.mod(ability) and (self.has_feature("Battle Ready") or item.get("int_weapon")):
                ability = "int"                         # a battle smith with a magic weapon, a Moonlight Greatsword: Intelligence
            mod = self.mod(ability)
            magic = item.get("bonus_weapon") or 0
            attack = mod + magic + (item.get("bonus_attack") or 0)
            damage_bonus = mod + magic + (item.get("bonus_damage") or 0)
            notes: List[str] = []
            bow = archery and ranged and re.search(r"\b(?:long|short) ?bow\b", f"{item['name']} {entry['name']}", re.I)
            if self.weapon_proficient(item) or bow:
                attack += pb
            else:
                notes.append("not proficient")
            if ranged and self.has_option("Archery"):
                attack += 2
            if bow:
                damage_bonus += 2
            dueling = not ranged and "two-handed" not in props and melee_one_handed_only and self.has_option("Dueling")
            if dueling:                                 # a versatile weapon too, in one hand (the battle takes it off two-handed)
                damage_bonus += 2
            dmg = f"{item.get('dmg1', '1')}{damage_bonus:+d}" if damage_bonus else item.get("dmg1", "1")
            if "versatile" in props and item.get("dmg2"):
                notes.append(f"versatile {item['dmg2']}")
            if "finesse" in props:
                notes.append("finesse")
            if "thrown" in props:
                notes.append("thrown")
            if item.get("range"):
                notes.append(f"range {item['range']}")
            dtype = item.get("dmg_type", "")
            swap = re.search(r"(?:deals?|damage is) (acid|cold|fire|force|lightning|necrotic|poison|psychic|radiant|thunder)(?: damage)? instead of "
                             r"(?:piercing|slashing|bludgeoning)", item.get("text") or "") if item.get("magic") else None
            if swap:                                    # Reaper's Scream, a Thunderbuss, a Lucent Destroyer: the text changes the type the data keeps
                dtype = swap.group(1)
            out.append({"name": entry["name"], "attack": attack, "damage": f"{dmg} {dtype}".strip(),
                        "ability": ability, "notes": notes, "dice": item.get("dmg1", ""), "bonus": damage_bonus,
                        "type": dtype, "versatile": item.get("dmg2") if "versatile" in props else None,
                        "props": list(props), "ranged": ranged, "range": item.get("range") or "",
                        "magic": bool(item.get("magic") or magic), "weapon_name": item.get("name", entry["name"]), "dueling": dueling})
        str_mod = self.mod("str")
        martial = self.table_value("Monk", "Martial Arts")
        if martial:
            ability = "dex" if self.mod("dex") > str_mod else "str"
            mod = self.mod(ability)
            out.append({"name": "Unarmed Strike (Martial Arts)", "attack": mod + pb,
                        "damage": f"{martial}{mod:+d} bludgeoning", "ability": ability, "notes": [],
                        "dice": str(martial), "bonus": mod, "type": "bludgeoning", "versatile": None,
                        "props": ["unarmed"], "ranged": False, "range": "", "magic": self.class_level("Monk") >= 6,    # Ki-Empowered Strikes
                        "weapon_name": "Unarmed Strike"})
        elif self.has_option("Unarmed Fighting"):     # the fighting style: d6, d8 with no weapon or shield in hand
            die = "1d6" if weapons or self.equipped_shield() else "1d8"
            out.append({"name": "Unarmed Strike", "attack": str_mod + pb, "damage": f"{die}{str_mod:+d} bludgeoning",
                        "ability": "str", "notes": ["Unarmed Fighting"], "dice": die, "bonus": str_mod, "type": "bludgeoning",
                        "versatile": None, "props": ["unarmed"], "ranged": False, "range": "", "magic": False,
                        "weapon_name": "Unarmed Strike"})
        elif "Tavern Brawler" in self.d["feats"]:
            out.append({"name": "Unarmed Strike", "attack": str_mod + pb, "damage": f"1d4{str_mod:+d} bludgeoning",
                        "ability": "str", "notes": ["Tavern Brawler"], "dice": "1d4", "bonus": str_mod, "type": "bludgeoning",
                        "versatile": None, "props": ["unarmed"], "ranged": False, "range": "", "magic": False,
                        "weapon_name": "Unarmed Strike"})
        else:
            out.append({"name": "Unarmed Strike", "attack": str_mod + pb, "damage": f"{1 + str_mod} bludgeoning",
                        "ability": "str", "notes": [], "dice": "", "bonus": 1 + str_mod, "type": "bludgeoning",
                        "versatile": None, "props": ["unarmed"], "ranged": False, "range": "", "magic": False,
                        "weapon_name": "Unarmed Strike"})
        nat = next((t for t in (self.race_data() or {}).get("traits") or []
                    if t["name"] in ("Cat's Claws", "Talons", "Hooves", "Horns", "Claws", "Bite", "Ram")), None)
        if not nat and "Dragon Hide" in self.d["feats"]:     # the feat's retractable claws: 1d4 slashing unarmed strikes
            nat = {"name": "Dragon Hide claws", "text": "1d4 slashing"}
        m = re.search(r"(\d+d\d+)", nat["text"]) if nat else None
        u = out[-1]
        if m and not martial and int(m.group(1).split("d")[1]) > int((u["dice"] or "1d1").split("d")[-1]):
            kind = next((k for k in ("slashing", "piercing", "bludgeoning") if k in nat["text"]), "bludgeoning")   # a tabaxi's claws, a minotaur's horns
            u.update(name=f"Unarmed Strike ({nat['name']})", dice=m.group(1), bonus=str_mod, type=kind,
                     damage=f"{m.group(1)}{str_mod:+d} {kind}", notes=u["notes"] + [nat["name"]])
        ub = max([d.get("unarmed_bonus") or 0 for _e, d in self._active_items()] + [0])
        if ub:                                          # Wraps of Unarmed Prowess, an Eldritch Claw Tattoo: +N and magical
            u = out[-1]
            u.update(attack=u["attack"] + ub, bonus=u["bonus"] + ub, magic=True)
            u["damage"] = f"{u['dice']}{u['bonus']:+d} {u['type']}" if u["dice"] else f"{u['bonus']} {u['type']}"
        return out

    def equipped_shield_is_weapon(self) -> bool:
        return False

    # ------------------------------------------------------------------ inventory / weight
    def find_item(self, name: str) -> Optional[dict]:
        low = name.lower()
        return next((e for e in self.inventory if e["name"].lower() == low), None)

    def add_item(self, name: str, qty: int = 1, equipped: bool = False, charges: Optional[int] = None) -> dict:
        """`charges`: what the items bring (a spent wand handed over: charges_taken); None: full."""
        entry = self.find_item(name)
        if entry:
            entry["qty"] += qty
            merge_charges(entry, entry["qty"] - qty, qty, charges)      # a fresh wand on a stack of spent ones: it brings its own
        else:
            entry = {"name": name, "qty": qty, "equipped": equipped, "attuned": False, "note": ""}
            if charges is not None:
                entry["charges_left"] = int(charges)
            self.inventory.append(entry)
        return entry

    def remove_item(self, name: str, qty: int = 1) -> bool:
        entry = self.find_item(name)
        if not entry or entry["qty"] < qty:
            return False
        take_charges(entry, qty)                        # the ones staying keep what they can hold (charges_taken went with the rest)
        entry["qty"] -= qty
        if entry["qty"] <= 0:
            self.inventory.remove(entry)
        return True

    @property
    def carried_weight(self) -> float:
        total = 0.0
        for e in self.inventory:
            data = self.item_data(e)
            total += (data.get("weight", 0) if data else 0) * e["qty"]
        total += sum(self.currency.values()) / 50   # PHB: fifty coins weigh a pound
        return round(total, 2)

    @property
    def carrying_capacity(self) -> int:
        return E.carrying_capacity(self.ability_score("str"), self.size)

    @property
    def encumbrance(self) -> str:
        return E.encumbrance_status(self.carried_weight, self.ability_score("str"), self.size)

    @property
    def wealth_gp(self) -> float:
        return E.to_copper(self.currency) / 100

    # ------------------------------------------------------------------ resting / HP
    def long_rest(self) -> None:
        """PHB: regain all HP, up to half your total hit dice (min 1), all spell slots and uses; lose 1 exhaustion."""
        self.d["hp"].pop("drain", None)                    # a hit point maximum cut by a drain comes back
        self.d.pop("ability_drain", None)                  # and drained ability scores
        self.current_hp = self.max_hp
        self.temp_hp = 0
        self.d["death_saves"] = {"success": 0, "failure": 0}
        if "Unconscious" in self.d["conditions"]:
            self.d["conditions"].remove("Unconscious")
        recover = max(1, self.total_level // 2)
        for c in sorted(self.classes, key=lambda c: -rules.classes[c["name"]]["hit_die"]):
            used = self.d["hit_dice_used"].get(c["name"], 0)
            back = min(used, recover)
            self.d["hit_dice_used"][c["name"]] = used - back
            recover -= back
        self.d["slots_used"] = {}
        self.d["exhaustion"] = max(0, self.d["exhaustion"] - 1)
        self.d["resources"] = {}
        self.d.pop("elixirs", None)                     # an Alchemist's flasks last until the end of the next long rest
        for entry in self.inventory:                    # wands and staffs: "regains 1d6 + 1 expended charges daily at dawn"
            data = self.item_data(entry) or {}
            if entry.get("charges_left") is None or not str(data.get("charges") or "").isdigit():
                continue                                # a Nine Lives Stealer's 1d8 + 1 charges never come back
            text = data.get("text") or ""                # "regains 1d6 + 1 expended charges", "regains 1d3 charges", "regains 1 expended charge",
            m = re.search(r"regains? (all|\d+d\d+(?: ?[+\-−–] ?\d+)?|\d+)(?: of)?(?: its| the)?(?: expended| spent| expanded| used)? "
                          r"(?:charges?|uses)\b", text, re.I)          # "regains all its charges", "regains 1d4 - 1 expended charges"
            top = charge_max(entry)                     # (a stack of 2 wands: both wands' charges)
            if not data.get("recharge") and not (m and re.search(r"dawn|dusk|daily|nightfall|midnight|\brest\b", text[m.end():m.end() + 60], re.I)):
                continue                                # an Ivory Goat figurine's charges come back after 7 days, not overnight
            if not m or m.group(1).lower() == "all":
                entry["charges_left"] = max(entry["charges_left"], top)
            else:
                from .dice import roll_dice
                back = sum(max(0, roll_dice(re.sub(r"[−–]", "-", m.group(1)).replace(" ", "")).total)
                           for _ in range(max(1, int(entry.get("qty") or 1))))     # each one in the stack regains its own
                entry["charges_left"] = min(top, entry["charges_left"] + back)

    def short_rest(self) -> None:
        """Short rest: refresh short-rest features and Warlock pact slots (spend hit dice separately)."""
        from .resources import resource_list
        for res in resource_list(self):
            if res["recharge"] == "short":
                self.d["resources"].pop(res["name"], None)
        self.d["slots_used"].pop("pact", None)
        for key in [k for k in self.d["resources"] if k.startswith("short:")]:   # once-per-short-rest feats and traits
            self.d["resources"].pop(key, None)
        for spell in self.d["racial_spells"]:           # innate spells that recharge on a short rest
            if str(spell.get("uses", "")).endswith("short rest"):
                self.d["resources"].pop(f"spell:{spell['name']}", None)
        for _e, item in self._active_items():           # Spell-Fueling armour's Resurgent Power: spent slots worth 3 levels, once until dawn
            m = re.search(r"combined total equal to (\d+) or less", item.get("text") or "") if "Resurgent Power" in (item.get("text") or "") else None
            if m and not self.d["resources"].get(f"item:{item['name']}:resurgent"):
                room, used = int(m.group(1)), self.d["slots_used"]
                for lvl in (3, 2, 1):                   # (the biggest slots first)
                    while room >= lvl and int(used.get(str(lvl)) or 0) > 0:
                        used[str(lvl)] = int(used[str(lvl)]) - 1
                        room -= lvl
                if room < int(m.group(1)):
                    self.d["resources"][f"item:{item['name']}:resurgent"] = 1

    def spend_hit_die(self, class_name: str, roll: int) -> int:
        """Spend a hit die: heal `roll` + Con modifier (min 0). Returns HP healed."""
        hd = self.hit_dice().get(class_name)
        if not hd or hd["used"] >= hd["total"]:
            raise ValueError(f"No {class_name} hit dice left.")
        self.d["hit_dice_used"][class_name] = hd["used"] + 1
        return self.heal(max(0, roll + self.mod("con")))

    # ------------------------------------------------------------------ notes
    # ------------------------------------------------------------------ level-up history (for undo)
    LEVEL_KEYS = ("classes", "abilities", "proficiencies", "feats", "options", "spells", "choices", "racial_spells")

    def snapshot_level(self, class_name=None, choices=None) -> None:
        """Remember the build before a level is gained so the level-up can be undone."""
        import copy
        state = {k: copy.deepcopy(self.d[k]) for k in self.LEVEL_KEYS}
        state["hp_gains"] = list(self.d["hp"]["gains"])
        self.d.setdefault("level_history", []).append({"summary": self.class_summary, "level": self.total_level, "state": state,
                                                       "class": class_name, "choices": choices})

    @property
    def can_revert(self) -> bool:
        return bool(self.d.get("level_history"))

    def revert_level(self) -> str:
        """Undo the last level-up (class levels, choices, hit points gained). Returns the build it went back to."""
        import copy
        entry = self.d["level_history"].pop()
        for k in self.LEVEL_KEYS:
            self.d[k] = copy.deepcopy(entry["state"][k])
        self.d["hp"]["gains"] = list(entry["state"]["hp_gains"])
        self.d["hp"]["current"] = min(self.d["hp"]["current"], self.max_hp)
        total = SC_slots(self)
        for key in list(self.d["slots_used"]):
            maximum = total["pact"]["slots"] if key == "pact" and total["pact"] else                 (total["slots"][int(key) - 1] if key != "pact" and key.isdigit() and int(key) <= 9 else 0)
            self.d["slots_used"][key] = min(self.d["slots_used"][key], maximum)
        return entry["summary"]

    def add_note(self, text: str) -> int:
        note_id = self.d["next_note_id"]
        self.d["next_note_id"] += 1
        self.notes.append({"id": note_id, "timestamp": int(time.time()), "text": text})
        return note_id

    def remove_note(self, note_id: int) -> bool:
        for i, note in enumerate(self.notes):
            if note["id"] == note_id:
                del self.notes[i]
                return True
        return False


def SC_slots(char):
    from . import spellcasting
    return spellcasting.spell_slots(char)
