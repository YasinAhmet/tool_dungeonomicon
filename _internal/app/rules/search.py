"""A small faceted search engine for the monster and item libraries.

Every entry is described by *facets* (category, type, tags, rarity, CR...). A search combines free text, query
fields (`type:undead cr:>=5 -goblin "pack tactics"`), ticked facet values (OR inside a facet, AND between facets)
and numeric ranges. `counts()` reports how many results each facet value would give, for the filter sidebar.
"""
import re
from collections import Counter
from dataclasses import dataclass, field
from typing import Callable, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from .data import rules
from .monsters import bestiary


@dataclass
class Facet:
    key: str
    title: str
    values: Callable[[dict], Iterable[str]]
    order: Optional[Sequence[str]] = None            # fixed display order (otherwise by count)
    aliases: Tuple[str, ...] = ()
    label: Callable[[str], str] = lambda v: v
    open: bool = False                                # expanded in the sidebar by default


@dataclass
class NumericField:
    key: str
    title: str
    value: Callable[[dict], Optional[float]]
    aliases: Tuple[str, ...] = ()
    parse: Callable[[str], float] = float


@dataclass
class Filters:
    sets: Dict[str, Set[str]] = field(default_factory=dict)          # facet key -> chosen values
    ranges: Dict[str, Tuple[Optional[float], Optional[float]]] = field(default_factory=dict)

    def active(self) -> bool:
        return any(self.sets.values()) or any(lo is not None or hi is not None for lo, hi in self.ranges.values())

    def toggle(self, key: str, value: str):
        chosen = self.sets.setdefault(key, set())
        chosen.symmetric_difference_update({value})
        if not chosen:
            del self.sets[key]

    def copy(self) -> "Filters":
        return Filters({k: set(v) for k, v in self.sets.items()}, dict(self.ranges))


_FIELD = re.compile(r'(-?)(\w+):(?:"([^"]*)"|(\S+))')
_TOKEN = re.compile(r'(-?)"([^"]+)"|(-?)(\S+)')
_OP = re.compile(r"^(>=|<=|>|<|=)?(.+?)(?:-(.+))?$")


# Where a name appears in several books the earliest listed here wins; unlisted books come after, in file order.
SOURCE_PREFERENCE = ["MPMM", "MM", "PHB", "DMG", "XGE", "TCE", "VGM", "MTF", "FTD", "BGG", "MOT", "EGW", "ERLW", "GGR", "SCC", "VRGR", "BMT", "AAG"]


def _source_rank(source) -> int:
    return SOURCE_PREFERENCE.index(source) if source in SOURCE_PREFERENCE else len(SOURCE_PREFERENCE)


class Index:
    def __init__(self, entries: List[dict], facets: List[Facet], numbers: List[NumericField],
                 haystack: Callable[[dict], str], sorts: Dict[str, Callable[[dict], object]]):
        self.entries = entries
        self.facets = {f.key: f for f in facets}
        self.facet_list = facets
        self.numbers = {n.key: n for n in numbers}
        self.number_list = numbers
        self.sorts = sorts
        self._hay = [haystack(e).lower() for e in entries]
        self._vals = [{f.key: set(v for v in f.values(e) if v) for f in facets} for e in entries]
        self._nums = [{n.key: n.value(e) for n in numbers} for e in entries]

    # ------------------------------------------------------------------ query parsing
    def parse(self, query: str) -> Tuple[List[str], List[str], List[tuple]]:
        """-> (required words, excluded words, field tests [(key, negate, op, a, b)])."""
        fields: List[tuple] = []

        def take(m):
            neg, key, quoted, plain = m.group(1) == "-", m.group(2).lower(), m.group(3), m.group(4)
            target = self._resolve(key)
            if not target:
                return m.group(0)
            fields.append((target, neg, quoted if quoted is not None else plain))
            return " "
        rest = _FIELD.sub(take, query)
        words, excluded = [], []
        for m in _TOKEN.finditer(rest):
            neg = (m.group(1) or m.group(3)) == "-"
            word = (m.group(2) or m.group(4) or "").lower()
            if word:
                (excluded if neg else words).append(word)
        return words, excluded, fields

    def _resolve(self, key: str) -> Optional[Tuple[str, str]]:
        for f in self.facet_list:
            if key == f.key or key in f.aliases:
                return ("set", f.key)
        for n in self.number_list:
            if key == n.key or key in n.aliases:
                return ("num", n.key)
        return None

    def _exact(self, key: str, spec: str) -> bool:
        """True when `spec` is a whole value of that facet somewhere (so 'rare' doesn't also match 'very rare')."""
        cache = self.__dict__.setdefault("_exact_cache", {})
        if key not in cache:
            cache[key] = {v.lower() for vals in self._vals for v in vals[key]}
        return spec.lower() in cache[key]

    def _num_ok(self, key: str, spec: str, value: Optional[float]) -> bool:
        if value is None:
            return False
        m = _OP.match(spec.strip())
        if not m:
            return False
        op, a, b = m.group(1) or "=", m.group(2), m.group(3)
        try:
            lo = self.numbers[key].parse(a)
            if b is not None:
                return lo <= value <= self.numbers[key].parse(b)
            hi = lo
        except ValueError:
            return False
        return {">=": value >= lo, "<=": value <= hi, ">": value > lo, "<": value < hi, "=": value == lo}[op]

    # ------------------------------------------------------------------ matching
    def _text_ok(self, i: int, words, excluded, fields) -> bool:
        hay = self._hay[i]
        if any(w not in hay for w in words) or any(w in hay for w in excluded):
            return False
        for (kind, key), neg, spec in fields:
            if kind == "set":
                low = [v.lower() for v in self._vals[i][key]]
                hit = spec.lower() in low or (not self._exact(key, spec) and any(spec.lower() in v for v in low))
            else:
                hit = self._num_ok(key, spec, self._nums[i][key])
            if hit == neg:
                return False
        return True

    def _filter_ok(self, i: int, flt: Filters, skip: Optional[str] = None) -> bool:
        for key, chosen in flt.sets.items():
            if key != skip and chosen and not (chosen & self._vals[i][key]):
                return False
        for key, (lo, hi) in flt.ranges.items():
            if key == skip:
                continue
            v = self._nums[i][key]
            if (lo is not None or hi is not None) and v is None:
                return False
            if lo is not None and v < lo or hi is not None and v > hi:
                return False
        return True

    def _candidates(self, query: str) -> List[int]:
        """Entries matching the text, limited to the enabled sourcebooks (Rules menu) - everywhere the engine is used."""
        words, excluded, fields = self.parse(query)
        allowed = set(rules.active_sources) | {"Custom"}
        hits = [i for i in range(len(self.entries)) if self.entries[i].get("source") in allowed and self._text_ok(i, words, excluded, fields)]
        return self._best_versions(hits)

    def _best_versions(self, hits: List[int]) -> List[int]:
        """Reprints share a name: keep only the one from the preferred book (Monsters of the Multiverse first)."""
        best: Dict[str, int] = {}
        for i in hits:
            e = self.entries[i]
            k = str(e.get("name", "")).lower() + ("|custom" if e.get("source") == "Custom" else "|" + e["source"] if e.get("homebrew") else "")  # custom content never hides behind a book's
            if k not in best or _source_rank(e.get("source")) < _source_rank(self.entries[best[k]].get("source")):
                best[k] = i
        keep = set(best.values())
        return [i for i in hits if i in keep]

    def search(self, query: str = "", flt: Optional[Filters] = None, sort: Optional[str] = None) -> List[dict]:
        flt = flt or Filters()
        rows = [self.entries[i] for i in self._candidates(query) if self._filter_ok(i, flt)]
        if sort:
            key = self.sorts.get(sort.lstrip("-"))
            if key:
                rows.sort(key=key, reverse=sort.startswith("-"))
        return rows

    def counts(self, query: str = "", flt: Optional[Filters] = None) -> Dict[str, Counter]:
        """For each facet: how many results every value would give (that facet's own filter is ignored)."""
        flt = flt or Filters()
        base = self._candidates(query)
        out: Dict[str, Counter] = {}
        for f in self.facet_list:
            c: Counter = Counter()
            for i in base:
                if self._filter_ok(i, flt, skip=f.key):
                    c.update(self._vals[i][f.key])
            out[f.key] = c
        return out

    def number_bounds(self, key: str) -> Tuple[float, float]:
        vals = [n[key] for n in self._nums if n[key] is not None]
        return (min(vals), max(vals)) if vals else (0, 0)

    def values_of(self, entry_index: int, key: str) -> Set[str]:
        return self._vals[entry_index][key]


# ====================================================================== monsters
DAMAGE_TYPES = ["acid", "bludgeoning", "cold", "fire", "force", "lightning", "necrotic", "piercing", "poison", "psychic",
                "radiant", "slashing", "thunder"]
CONDITIONS = ["blinded", "charmed", "deafened", "exhaustion", "frightened", "grappled", "incapacitated", "paralyzed",
              "petrified", "poisoned", "prone", "restrained", "stunned", "unconscious"]
SENSES = ["blindsight", "darkvision", "tremorsense", "truesight"]
SIZES = ["Tiny", "Small", "Medium", "Large", "Huge", "Gargantuan"]
BUCKETS = [("0-1/2", 0, 0.5), ("1-4", 1, 4), ("5-10", 5, 10), ("11-16", 11, 16), ("17+", 17, 99)]


def _cr_value(text: str) -> float:
    if "/" in text:
        a, b = text.split("/")
        return int(a) / int(b)
    return float(text)


def _words(text: str, vocabulary: List[str]) -> List[str]:
    low = (text or "").lower()
    return [w for w in vocabulary if w in low]


def _alignment(m: dict) -> List[str]:
    text = m["alignment"].lower()
    out = [w.title() for w in ("lawful", "neutral", "chaotic", "good", "evil", "unaligned") if re.search(rf"\b{w}\b", text)]
    if "any" in text:
        out.append("Any")
    return out or ["Unaligned"]


def _speeds(m: dict) -> List[str]:
    text = m["speed"].lower()
    return [w for w in ("fly", "swim", "climb", "burrow") if w in text] + (["hover"] if "hover" in text else [])


def _cr_bucket(m: dict) -> List[str]:
    return [name for name, lo, hi in BUCKETS if lo <= m["cr_num"] <= hi]


def build_monster_index() -> Index:
    sources = bestiary.source_name
    facets = [
        Facet("type", "Type", lambda m: [m["type"].title()], aliases=("t",), open=True),
        Facet("tag", "Tags", lambda m: [t.title() for t in m["tags"]], aliases=("tags",)),
        Facet("size", "Size", lambda m: m["size"].split("/"), order=SIZES),
        Facet("crb", "Challenge", _cr_bucket, order=[b[0] for b in BUCKETS], aliases=("challenge",), open=True),
        Facet("env", "Environment", lambda m: m["environment"] or ["Unspecified"], aliases=("environment",)),
        Facet("align", "Alignment", _alignment, aliases=("alignment",)),
        Facet("has", "Features", lambda m: [f.title() for f in m["flags"]] + (["Lair actions"] if m["lair"] else []), aliases=("flag",)),
        Facet("move", "Movement", _speeds, aliases=("speed",)),
        Facet("sense", "Senses", lambda m: _words(m["senses"], SENSES)),
        Facet("res", "Resists", lambda m: _words(m["resist"], DAMAGE_TYPES), aliases=("resist", "resistance")),
        Facet("imm", "Immune to", lambda m: _words(m["immune"], DAMAGE_TYPES), aliases=("immune",)),
        Facet("vul", "Vulnerable to", lambda m: _words(m["vulnerable"], DAMAGE_TYPES), aliases=("vulnerable",)),
        Facet("cimm", "Condition immunity", lambda m: _words(m["condition_immune"], CONDITIONS), aliases=("conditionimmune",)),
        Facet("trait", "Traits", lambda m: [t["name"].split(" (")[0] for t in m["traits"] if t["name"]]),
        Facet("book", "Book", lambda m: [m["source"]], aliases=("source", "src"), label=lambda v: f"{v} - {sources(v)}"),
    ]
    numbers = [
        NumericField("cr", "CR", lambda m: m["cr_num"], aliases=("challenge",), parse=_cr_value),
        NumericField("hp", "HP", lambda m: float(m["hp"])), NumericField("ac", "AC", lambda m: float(m["ac"])),
        NumericField("xp", "XP", lambda m: float(m["xp"])),
    ]
    sorts = {"cr": lambda m: (m["cr_num"], m["name"].lower()), "name": lambda m: m["name"].lower(),
             "hp": lambda m: (m["hp"], m["name"].lower()), "ac": lambda m: (m["ac"], m["name"].lower()),
             "type": lambda m: (m["type"], m["cr_num"], m["name"].lower()), "book": lambda m: (m["source"], m["name"].lower())}
    hay = lambda m: f"{m['name']} {m['type']} {' '.join(m['tags'])} {m['alignment']} {m['source']} " \
                    f"{' '.join(t['name'] for t in m['traits'] + m['actions'] + m['legendary'])}"
    return Index(bestiary.all, facets, numbers, hay, sorts)


# ====================================================================== items
ITEM_TYPES = {
    "M": "Melee weapon", "R": "Ranged weapon", "A": "Ammunition", "AF": "Ammunition", "LA": "Light armor", "MA": "Medium armor",
    "HA": "Heavy armor", "S": "Shield", "G": "Adventuring gear", "SCF": "Spellcasting focus", "RG": "Ring", "P": "Potion",
    "SC": "Scroll", "WD": "Wand", "RD": "Rod", "AT": "Artisan's tools", "T": "Tools", "GS": "Gaming set", "INS": "Instrument",
    "$G": "Gemstone", "$A": "Art object", "$C": "Coinage", "TG": "Trade good", "MNT": "Mount", "TAH": "Tack & harness",
    "VEH": "Vehicle", "SHP": "Ship", "AIR": "Airship", "FD": "Food & drink", "EXP": "Explosive", "SPC": "Special",
    "OTH": "Other", "": "Miscellaneous",
}
RARITY_ORDER = ["none", "common", "uncommon", "rare", "very rare", "legendary", "artifact", "varies", "unknown", "unknown (magic)"]


def item_category(i: dict) -> str:
    t = i["type"]
    if i.get("wondrous"):
        return "Wondrous item"
    if t in ("M", "R"):
        return "Weapon"
    if t in ("A", "AF", "EXP"):
        return "Ammunition & explosives"
    if t in ("LA", "MA", "HA", "S"):
        return "Armor & shield"
    if t in ("P", "SC", "RG", "WD", "RD"):
        return {"P": "Potion", "SC": "Scroll", "RG": "Ring", "WD": "Wand", "RD": "Rod"}[t]
    if t in ("AT", "T", "GS", "INS"):
        return "Tools & instruments"
    if t in ("$G", "$A", "$C"):
        return "Treasure"
    if t in ("TG", "MNT", "TAH", "VEH", "SHP", "AIR", "FD"):
        return "Mounts, vehicles & trade"
    if i.get("magic"):
        return "Magic item (other)"
    return "Adventuring gear" if t in ("G", "SCF") else "Other"


def _cost_bucket(i: dict) -> List[str]:
    gp = (i["value"] or 0) / 100
    if gp <= 0:
        return ["No listed price"]
    return ["Under 1 gp"] if gp < 1 else ["1-10 gp"] if gp <= 10 else ["11-100 gp"] if gp <= 100 else \
        ["101-1,000 gp"] if gp <= 1000 else ["Over 1,000 gp"]


def build_item_index() -> Index:
    sources = bestiary.source_name
    facets = [
        Facet("cat", "Category", lambda i: [item_category(i)], aliases=("category",), open=True),
        Facet("type", "Type", lambda i: [ITEM_TYPES.get(i["type"], i["type"])], aliases=("t",)),
        Facet("rarity", "Rarity", lambda i: [i["rarity"].title() if i["rarity"] != "none" else "Mundane"],
              order=[r.title() if r != "none" else "Mundane" for r in RARITY_ORDER], open=True),
        Facet("magic", "Magic", lambda i: ["Magic" if i["magic"] else "Mundane"]),
        Facet("attune", "Attunement", lambda i: ["Requires attunement"] if i.get("attune") is not None else ["No attunement"]),
        Facet("prop", "Weapon properties", lambda i: [p.split("|")[0].title() for p in i.get("properties", [])], aliases=("property",)),
        Facet("dmg", "Damage type", lambda i: [i["dmg_type"].title()] if i.get("dmg_type") else [], aliases=("damage",)),
        Facet("wcat", "Weapon class", lambda i: [i["category"].title()] if i.get("weapon") and i.get("category") else []),
        Facet("price", "Price", _cost_bucket, order=["No listed price", "Under 1 gp", "1-10 gp", "11-100 gp", "101-1,000 gp", "Over 1,000 gp"]),
        Facet("flag", "Features", lambda i: [t for t, on in (("Cursed", i.get("curse")), ("Sentient", i.get("sentient")),
                                                              ("Has charges", i.get("charges")), ("Grants resistance", i.get("resist")),
                                                              ("Stealth disadvantage", i.get("stealth_disadvantage"))) if on]),
        Facet("book", "Book", lambda i: [i["source"]], aliases=("source", "src"), label=lambda v: f"{v} - {sources(v)}"),
    ]
    numbers = [
        NumericField("ac", "AC", lambda i: float(i["ac"]) if i.get("ac") else None),
        NumericField("gp", "Cost (gp)", lambda i: (i["value"] or 0) / 100 if i["value"] else None, aliases=("cost", "price")),
        NumericField("weight", "Weight (lb)", lambda i: float(i["weight"]) if i.get("weight") else None, aliases=("lb",)),
    ]
    sorts = {"name": lambda i: i["name"].lower(), "rarity": lambda i: (RARITY_ORDER.index(i["rarity"]) if i["rarity"] in RARITY_ORDER else 99, i["name"].lower()),
             "cost": lambda i: ((i["value"] or 0), i["name"].lower()), "weight": lambda i: (i.get("weight") or 0, i["name"].lower()),
             "type": lambda i: (ITEM_TYPES.get(i["type"], i["type"]), i["name"].lower()), "book": lambda i: (i["source"], i["name"].lower())}
    hay = lambda i: f"{i['name']} {ITEM_TYPES.get(i['type'], '')} {item_category(i)} {i['rarity']} {i['source']} " \
                    f"{' '.join(i.get('properties', []))} {i.get('dmg_type', '')} {i.get('text', '')[:400]}"
    return Index(list(rules.items.values()), facets, numbers, hay, sorts)


def item_text(i: dict) -> str:
    """Readable item card."""
    bits = [i["name"], f"{item_category(i)} - {ITEM_TYPES.get(i['type'], i['type'])}"
            + (f", {i['rarity']}" if i["rarity"] not in ("none", "") else "") + (" (requires attunement)" if i.get("attune") is not None else "")]
    line = []
    if i.get("ac"):
        line.append(f"AC {i['ac']}" + (f" (min Str {i['strength']})" if i.get("strength") else ""))
    if i.get("dmg1"):
        line.append(f"{i['dmg1']} {i.get('dmg_type', '')}" + (f" (versatile {i['dmg2']})" if i.get("dmg2") else ""))
    if i.get("range"):
        line.append(f"range {i['range']}")
    if i.get("properties"):
        line.append(", ".join(p.split("|")[0] for p in i["properties"]))
    if line:
        bits.append("; ".join(line))
    bits.append(f"{i.get('weight') or 0:g} lb - {(i['value'] or 0) / 100:g} gp - {i['source']}")
    if i.get("text"):
        bits += ["", i["text"]]
    return "\n".join(bits)


monster_index: Optional[Index] = None
item_index: Optional[Index] = None


def monsters() -> Index:
    global monster_index
    if monster_index is None:
        monster_index = build_monster_index()
    return monster_index


def items() -> Index:
    global item_index
    if item_index is None:
        item_index = build_item_index()
    return item_index
