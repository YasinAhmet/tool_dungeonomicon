"""Lazy access to the D&D 5e rules data imported by tools/import_5etools.py."""
import json
from functools import cached_property
from pathlib import Path
from typing import Dict, List, Optional

DATA_DIR = Path(__file__).resolve().parent / "data"

# Sourcebooks offered when nothing else is configured (the 2014 Player's Handbook).
CHARACTER_SOURCES = ("PHB", "DMG", "MM")        # the core rules: new installs and "reset" start from these


def _homebrew(kind: str) -> list:
    """Content of the modules that come with the app (app.rules.modules) and of the custom rulebooks written in the
    Rules tab (app.rules.homebrew); 'custom_items': the Item workshop's CUSTOMS items."""
    try:
        from . import homebrew, modules
        return homebrew.custom_items() if kind == "custom_items" else modules.entries(kind) + homebrew.entries(kind)
    except Exception:
        return []


NOT_INSTALLED = "Its book isn't installed: it comes back when the module with that book is (the Installations window)."


class Missing(dict):
    """Records by name that answer a name they don't have with a stand-in (a record marked "missing") instead of a
    KeyError: a character keeps a class whose module was removed. `in`, get() and the lists see only real records."""

    def __init__(self, data, stub):
        super().__init__(data)
        self._stub = stub

    def __missing__(self, key):
        return self._stub(key)


def missing_class(name: str) -> dict:
    """A class whose book isn't installed: nothing but its name (a d8 hit die, no features, no spellcasting)."""
    return {"name": name, "source": "", "missing": True, "hit_die": 8, "saves": [], "skills": {"choose": [], "count": 0},
            "armor": [], "weapons": [], "tools": [], "tool_choice": [], "spellcasting": None,
            "equipment": {"text": [], "choices": [], "gold_alternative": ""},
            "multiclass": {"requirements": {}, "gained": {}}, "subclass_title": "", "subclass_levels": [],
            "optional_progression": [], "table": {"cols": [], "rows": [[] for _ in range(20)]}, "features": []}


def _load(name: str):
    """The program's own records of one file (the SRD), nothing from the modules."""
    path = DATA_DIR / name
    if not path.exists():
        raise FileNotFoundError(
            f"Missing rules data '{name}'. Run: py tools/import_5etools.py <5etools>/data")
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def _all(kind: str) -> list:
    """The program's records of one kind plus those of the installed "book" modules (app.rules.modules.merge)."""
    from . import modules
    return modules.merge(kind, _load(f"{kind}.json"))


class Rules:
    """All imported game content, keyed for fast lookup. Names are matched case-insensitively.

    Content from every imported sourcebook is available by name; the *pick lists* (races, backgrounds, spells,
    feats, subclasses...) only offer books listed in `active_sources`, which the app sets from its settings.
    """

    active_sources: tuple = CHARACTER_SOURCES

    def set_active_sources(self, sources) -> None:
        self.active_sources = tuple(sources) or CHARACTER_SOURCES

    def _src(self, sources):
        return self.active_sources if sources is None else sources

    def shown(self, rec: dict) -> bool:
        """Is this record offered anywhere - from a book ticked in the Sourcebooks window, or made in the app? (Records
        of other books are still found by name: what a character already has keeps working.)"""
        s = rec.get("source")
        return s in self.active_sources or s == "Custom"

    def offered(self, rows) -> list:
        """The records of `rows` from ticked books (shown())."""
        return [r for r in rows if self.shown(r)]

    @cached_property
    def sources(self) -> Dict[str, dict]:
        """{source id: {'name', 'group'}} for every imported sourcebook."""
        from . import homebrew, modules
        return {**_load("sources.json"), **modules.source_entries(), **homebrew.source_entries()}

    @cached_property
    def classes(self) -> Dict[str, dict]:
        return Missing({c["name"]: c for c in _all("classes")}, missing_class)

    @cached_property
    def _subclasses(self) -> List[dict]:
        return _all("subclasses") + _homebrew("subclasses")

    @cached_property
    def races(self) -> Dict[str, dict]:
        return {r["name"]: r for r in _all("races") + _homebrew("races")}

    @cached_property
    def backgrounds(self) -> Dict[str, dict]:
        out = {b["name"]: b for b in _all("backgrounds") + _homebrew("backgrounds")}
        from ..core.storage import read_json             # backgrounds made in the generator live next to the characters
        custom = read_json("data/custom_backgrounds.json", {})
        out.update(custom if isinstance(custom, dict) else {})
        return out

    @cached_property
    def feats(self) -> Dict[str, dict]:
        return {f["name"]: f for f in _all("feats") + _homebrew("feats")}

    @cached_property
    def optional_features(self) -> Dict[str, dict]:
        return {o["name"]: o for o in _all("optional_features") + _homebrew("optional_features")}

    @cached_property
    def skills(self) -> Dict[str, dict]:
        return {s["name"]: s for s in _all("skills")}

    @cached_property
    def conditions(self) -> Dict[str, dict]:
        return {c["name"]: c for c in _all("conditions")}

    @cached_property
    def languages(self) -> List[dict]:
        return _all("languages") + _homebrew("languages")

    @cached_property
    def spells(self) -> Dict[str, dict]:
        return {s["name"].lower(): s for s in _all("spells") + _homebrew("spells")}

    @cached_property
    def items(self) -> Dict[str, dict]:
        out = {i["name"].lower(): i for i in _all("items") + _homebrew("items") + _homebrew("custom_items")}
        from .item_fixes import fix_item
        for i in out.values():                    # named magic weapons (Scimitar of Speed, Oathbow...) come without the flag
            if i.get("type") in ("M", "R") and i.get("dmg1") and not i.get("weapon"):
                i["weapon"] = True
            fix_item(i)                           # staffs as weapons, mis-read bonuses (item_fixes.py)
        return out

    @cached_property
    def item_properties(self) -> List[dict]:
        return _all("item_properties")

    # ---- lookups ----
    def subclasses_of(self, class_name: str) -> List[dict]:
        return [s for s in self._subclasses if s["class"] == class_name]

    def subclass(self, class_name: str, name: str) -> Optional[dict]:
        return next((s for s in self.subclasses_of(class_name) if s["name"] == name), None)

    def spell(self, name: str) -> Optional[dict]:
        low = name.lower()
        if "|" in low and low not in self.spells:
            low = low.split("|")[0]                                    # "faerie fire|xphb": a 5etools reference
        return self.spells.get(low) or self.spells.get(self.alias("spells", low).lower())

    def item(self, name: str) -> Optional[dict]:
        low = name.lower()
        return self.items.get(low) or self.items.get(self.alias("items", low).lower())

    @staticmethod
    def alias(kind: str, name: str) -> str:
        """The name a record goes by now, for another name of it: the SRD's 'Arcane Hand' when only the SRD is
        installed, the Player's Handbook's 'Bigby's Hand' when its module is (app.rules.modules.aliases); else `name`."""
        from . import modules
        return modules.aliases().get(kind, {}).get(name.lower(), name)

    def skill_name(self, text: str) -> str:
        """'sleight of hand' -> 'Sleight of Hand'."""
        for name in self.skills:
            if name.lower() == text.lower():
                return name
        raise KeyError(f"Unknown skill '{text}'")

    def class_spell_list(self, class_name: str, level: Optional[int] = None, max_level: Optional[int] = None,
                         sources=None) -> List[dict]:
        """Spells on a class's list (from the given sourcebooks), sorted by level then name."""
        sources = self._src(sources)
        out = [s for s in self.spells.values() if class_name in s["classes"] and s["source"] in sources]
        if level is not None:
            out = [s for s in out if s["level"] == level]
        if max_level is not None:
            out = [s for s in out if s["level"] <= max_level]
        return sorted(out, key=lambda s: (s["level"], s["name"]))

    def class_list(self, sources=None) -> List[dict]:
        sources = self._src(sources)
        return [c for c in self.classes.values() if c["source"] in sources]

    def race_list(self, sources=None) -> List[dict]:
        sources = self._src(sources)
        return [r for r in self.races.values() if r["source"] in sources]

    def background_list(self, sources=None) -> List[dict]:
        sources = self._src(sources)
        return [b for b in self.backgrounds.values() if b["source"] in sources or b["source"] == "Custom"]

    def feat_list(self, sources=None) -> List[dict]:
        sources = self._src(sources)
        return [f for f in self.feats.values() if f["source"] in sources]

    def option_list(self, sources=None) -> List[dict]:
        sources = self._src(sources)
        return [o for o in self.optional_features.values() if o["source"] in sources]

    def standard_languages(self, sources=None) -> List[str]:
        sources = self._src(sources)
        return [l["name"] for l in self.languages if l["type"] == "standard" and l["source"] in sources]

    def all_languages(self, sources=None) -> List[str]:
        sources = self._src(sources)
        return list(dict.fromkeys(l["name"] for l in self.languages
                                  if l["type"] in ("standard", "exotic") and l["source"] in sources))

    def weapons(self, category: Optional[str] = None) -> List[dict]:
        return [i for i in self.items.values() if i.get("weapon") and not i["magic"]
                and i["source"] == "PHB" and (category is None or i.get("category") == category)]

    def armors(self) -> List[dict]:
        return [i for i in self.items.values() if i["type"] in ("LA", "MA", "HA", "S") and not i["magic"]
                and i["source"] == "PHB"]

    def warm(self):
        """Read every list now (a background thread at start-up), so the first action of a battle - and six player
        pages asking about it at once - doesn't wait for the spells, items and monsters to load."""
        for name in ("sources", "classes", "_subclasses", "races", "backgrounds", "feats", "optional_features", "skills",
                     "conditions", "languages", "spells", "items", "item_properties"):
            getattr(self, name)
        from .monsters import bestiary
        bestiary.all
        bestiary.lore("")                                # (the monster card's descriptions)
        from ..services.battle import icons
        icons.for_spell("fire bolt")                     # (the spell picture map)


rules = Rules()
