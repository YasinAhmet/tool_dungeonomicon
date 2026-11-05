"""The monster library behind the Battle page: loading, searching, filtering, stat block text and HP rolls."""
import json
import os
import random
import re
from typing import Dict, Iterable, List, Optional

from . import engine as E
from .data import DATA_DIR, rules
from .monster_text import modernize

CR_STEPS = ["0", "1/8", "1/4", "1/2"] + [str(i) for i in range(1, 31)]
CUSTOM_DIR = os.path.join("data", "custom_monsters")         # the generator's creatures, one JSON file each (source "Custom")


class Bestiary:
    def __init__(self):
        self._monsters: Optional[List[dict]] = None
        self._by_id: Dict[str, dict] = {}

    # ------------------------------------------------------------------ loading
    @property
    def all(self) -> List[dict]:
        if self._monsters is None:                               # built whole, then shown: another thread never sees half
            path = DATA_DIR / "monsters.json"
            try:
                with open(path, encoding="utf-8") as f:
                    monsters = json.load(f)
            except (OSError, ValueError):
                monsters = []
            from . import modules
            monsters = modules.merge("monsters", monsters)               # the installed books' creatures (modules.py)
            for m in monsters:
                modernize(m)                                     # 2024-style entries read back into the 2014 wording (monster_text.py)
            monsters += self._load_custom() + self._load_homebrew()
            self._by_id = {m["id"]: m for m in monsters}
            self._monsters = monsters
        return self._monsters

    @staticmethod
    def _load_custom() -> List[dict]:
        out = []
        if os.path.isdir(CUSTOM_DIR):
            for f in sorted(os.listdir(CUSTOM_DIR)):
                if f.endswith(".json"):
                    try:
                        with open(os.path.join(CUSTOM_DIR, f), encoding="utf-8") as fh:
                            m = json.load(fh)
                        if isinstance(m, dict) and m.get("id"):
                            out.append(m)
                    except (OSError, ValueError):
                        pass
        return out

    @staticmethod
    def _load_homebrew() -> List[dict]:
        from .data import _homebrew
        return _homebrew("monsters")

    def reload_custom(self):
        """Re-read the custom monsters folder and the custom rulebooks (after a creature was saved or deleted)."""
        self.all
        self._monsters = ([m for m in self._monsters if m.get("source") != "Custom" and not m.get("homebrew") and not m.get("module")]
                           + self._load_custom() + self._load_homebrew())
        self._by_id = {m["id"]: m for m in self._monsters}

    def offered(self) -> List[dict]:
        """The creatures of the books ticked in the Sourcebooks window (and those made in the app)."""
        every = self.all
        hit = getattr(self, "_offered", None)
        if hit is None or hit[0] is not every or hit[1] != rules.active_sources:
            hit = self._offered = (every, rules.active_sources, [m for m in every if rules.shown(m)])
        return hit[2]

    def custom(self) -> List[dict]:
        return [m for m in self.all if m.get("source") == "Custom"]

    def lore(self, monster_id: str) -> str:
        """The monster's description text (monster_lore.json, from tools/import_bestiary_fluff.py, and the installed
        modules' lore.json), or ''."""
        if not hasattr(self, "_lore"):
            try:
                with open(DATA_DIR / "monster_lore.json", encoding="utf-8") as f:
                    lore = json.load(f)
            except (OSError, ValueError):
                lore = {}
            from . import modules
            self._lore = {**lore, **modules.lore()}
        return self._lore.get(monster_id) or (self.get(monster_id) or {}).get("description", "")

    def reload(self):
        """Read everything again (after a module was installed, removed, switched on or off)."""
        self._monsters = None
        self._by_id = {}
        self.__dict__.pop("_lore", None)

    def get(self, monster_id: str) -> Optional[dict]:
        self.all
        return self._by_id.get(monster_id)

    # ------------------------------------------------------------------ facets for the filter widgets
    def types(self) -> List[str]:
        return sorted({m["type"] for m in self.all})

    def sizes(self) -> List[str]:
        order = ["Tiny", "Small", "Medium", "Large", "Huge", "Gargantuan"]
        found = {s for m in self.all for s in m["size"].split("/")}
        return [s for s in order if s in found]

    def environments(self) -> List[str]:
        return sorted({e for m in self.all for e in m["environment"]})

    def sources(self) -> List[str]:
        return sorted({m["source"] for m in self.all})

    def source_name(self, source: str) -> str:
        return (rules.sources.get(source) or {}).get("name", source)

    # ------------------------------------------------------------------ searching
    def search(self, query: str = "", cr_min: str = "", cr_max: str = "", types: Iterable[str] = (),
               sizes: Iterable[str] = (), source: str = "", environment: str = "", flags: Iterable[str] = (),
               sort: str = "cr", limit: Optional[int] = None) -> List[dict]:
        """Filter the library. `query` matches names, types, tags and traits (all words must match)."""
        words = [w for w in re.split(r"\s+", query.lower().strip()) if w]
        lo = _cr(cr_min) if cr_min else None
        hi = _cr(cr_max) if cr_max else None
        types, sizes, flags = set(types), set(sizes), set(flags)
        out = []
        for m in self.all:
            if lo is not None and m["cr_num"] < lo or hi is not None and m["cr_num"] > hi:
                continue
            if types and m["type"] not in types:
                continue
            if sizes and not (sizes & set(m["size"].split("/"))):
                continue
            if source and m["source"] != source:
                continue
            if environment and environment not in m["environment"]:
                continue
            if flags and not flags <= set(m["flags"]):
                continue
            if words:
                hay = f"{m['name']} {m['type']} {' '.join(m['tags'])} {m['alignment']} {m['source']}".lower()
                if not all(w in hay for w in words):
                    # fall back to trait/action names so "pack tactics" or "breath" finds creatures
                    extra = " ".join(t["name"] for t in m["traits"] + m["actions"] + m["legendary"]).lower()
                    if not all(w in hay or w in extra for w in words):
                        continue
            out.append(m)
        keys = {"cr": lambda m: (m["cr_num"], m["name"].lower()), "name": lambda m: m["name"].lower(),
                "hp": lambda m: (m["hp"], m["name"].lower()), "ac": lambda m: (m["ac"], m["name"].lower()),
                "type": lambda m: (m["type"], m["cr_num"], m["name"].lower())}
        out.sort(key=keys.get(sort.lstrip("-"), keys["cr"]), reverse=sort.startswith("-"))
        return out[:limit] if limit else out


def _cr(text: str) -> float:
    if "/" in text:
        a, b = text.split("/")
        return int(a) / int(b)
    return float(text)


bestiary = Bestiary()


# ---------------------------------------------------------------------- helpers
BROAD_TYPES = {"humanoid": "Humanoid", "beast": "Animal", "monstrosity": "Monstrosity", "aberration": "Monstrosity", "dragon": "Monstrosity",
               "giant": "Monstrosity", "ooze": "Monstrosity", "undead": "Undead", "fey": "Fey & Plant", "plant": "Fey & Plant",
               "elemental": "Elemental & Planar", "celestial": "Elemental & Planar", "fiend": "Elemental & Planar", "construct": "Construct"}


def broad_type(kind: str) -> str:
    """The general family of a creature type: Humanoid, Animal, Monstrosity..."""
    return BROAD_TYPES.get(kind.split("/")[0].lower(), "Other")


def ability_mod(monster: dict, ability: str) -> int:
    return E.modifier(monster["abilities"][ability])


def roll_hp(formula: str, average: int, rng: random.Random = random) -> int:
    """Roll '28d8 + 84' (falls back to the average when the formula can't be read)."""
    m = re.fullmatch(r"\s*(\d+)d(\d+)\s*(?:([+-])\s*(\d+))?\s*", formula or "")
    if not m:
        return average
    n, die = int(m.group(1)), int(m.group(2))
    bonus = int(m.group(4) or 0) * (-1 if m.group(3) == "-" else 1)
    return max(1, sum(rng.randint(1, die) for _ in range(n)) + bonus)


def statblock(m: dict) -> str:
    """A plain-text stat block."""
    ab = m["abilities"]
    lines = [f"{m['name']}  ({m['source']})",
             f"{m['size']} {m['type']}{' (' + ', '.join(m['tags']) + ')' if m['tags'] else ''}, {m['alignment']}",
             f"Armor Class {m['ac']}" + (f" ({m['ac_note']})" if m["ac_note"] else ""),
             f"Hit Points {m['hp']}" + (f" ({m['hp_formula']})" if m["hp_formula"] else ""),
             f"Speed {m['speed']}", "",
             "   ".join(f"{a.upper()} {ab[a]} ({E.modifier(ab[a]):+d})" for a in E.ABILITIES), ""]
    for label, key in (("Saving Throws", "saves"), ("Skills", "skills"), ("Damage Vulnerabilities", "vulnerable"),
                       ("Damage Resistances", "resist"), ("Damage Immunities", "immune"),
                       ("Condition Immunities", "condition_immune")):
        if m[key]:
            lines.append(f"{label} {m[key]}")
    lines += [f"Senses {m['senses'] + ', ' if m['senses'] else ''}passive Perception {m['passive']}",
              f"Languages {m['languages']}", f"Challenge {m['cr']} ({m['xp']:,} XP)", ""]
    for title, key in (("", "traits"), ("", "spellcasting"), ("ACTIONS", "actions"), ("BONUS ACTIONS", "bonus_actions"),
                       ("REACTIONS", "reactions"), ("LEGENDARY ACTIONS", "legendary")):
        if m[key]:
            if title:
                lines += ["", title]
                if key == "legendary" and m["legendary_note"]:
                    lines.append(m["legendary_note"])
            for e in m[key]:
                lines.append(f"{e['name']}\n{e['text']}" if e["name"] else e["text"])
                lines.append("")
    if m["lair"]:
        lines += ["LAIR ACTIONS", m["lair"]]
    lore = m.get("description", "") if m.get("source") == "Custom" or m.get("homebrew") or m.get("module") else bestiary.lore(m["id"])
    if lore:
        shown, size = [], 0
        for para in (p for p in lore.split("\n") if p.strip()):          # whole paragraphs, so the translation finds them
            if shown and size + len(para) > 700:
                shown.append("…")
                break
            shown.append(para)
            size += len(para)
        lines += ["", "DESCRIPTION", "\n".join(shown)]
    return "\n".join(lines).rstrip()


# ---------------------------------------------------------------------- encounter difficulty (DMG ch. 13)
THRESHOLDS = [(25, 50, 75, 100), (50, 100, 150, 200), (75, 150, 225, 400), (125, 250, 375, 500), (250, 500, 750, 1100),
              (300, 600, 900, 1400), (350, 750, 1100, 1700), (450, 900, 1400, 2100), (550, 1100, 1600, 2400),
              (600, 1200, 1900, 2800), (800, 1600, 2400, 3600), (1000, 2000, 3000, 4500), (1100, 2200, 3400, 5100),
              (1250, 2500, 3800, 5700), (1400, 2800, 4300, 6400), (1600, 3200, 4800, 7200), (2000, 3900, 5900, 8800),
              (2100, 4200, 6300, 9500), (2400, 4900, 7300, 10900), (2800, 5700, 8500, 12700)]
MULTIPLIERS = [0.5, 1, 1.5, 2, 2.5, 3, 4]          # index 1 = a single monster


def encounter_difficulty(party_levels: List[int], enemy_xp: List[int]) -> Dict[str, object]:
    """Easy/Medium/Hard/Deadly rating of a fight. Returns {'rating', 'xp', 'adjusted', 'thresholds'} (rating None if no party)."""
    xp = sum(enemy_xp)
    n = len(enemy_xp)
    if not party_levels or not n:
        return {"rating": None, "xp": xp, "adjusted": xp, "thresholds": None}
    step = 1 if n == 1 else 2 if n == 2 else 3 if n <= 6 else 4 if n <= 10 else 5 if n <= 14 else 6
    if len(party_levels) < 3:
        step = min(6, step + 1)
    elif len(party_levels) >= 6:
        step = max(0, step - 1)
    adjusted = int(xp * MULTIPLIERS[step])
    totals = [sum(THRESHOLDS[max(1, min(20, lv)) - 1][i] for lv in party_levels) for i in range(4)]
    rating = "Trivial"
    for name, limit in zip(("Easy", "Medium", "Hard", "Deadly"), totals):
        if adjusted >= limit:
            rating = name
    return {"rating": rating, "xp": xp, "adjusted": adjusted, "thresholds": dict(zip(("Easy", "Medium", "Hard", "Deadly"), totals))}
