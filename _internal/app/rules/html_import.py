"""Turn an exported HTML character sheet (export.to_html) back into a character.

Sheets exported by this version carry the full character data in a hidden <script id="character-data"> block, so they
come back exactly. Older sheets only have what they show; `from_html` rebuilds the character from that: race, classes,
ability scores (from the score breakdowns), proficiencies, spells, equipment, coins, hit points, resources, details and
notes. Anything a sheet doesn't show (milestone leveling, the level history, death saves...) is taken from `previous`,
the character of the same name that already exists, when there is one.
"""
import copy
import json
import re
import time
from html.parser import HTMLParser
from typing import Dict, List, Optional

from . import engine as E
from . import spellcasting as SC
from .character import SKILLS, Character, blank
from .data import rules

DATA_ID = "character-data"
_SHORT = {v: k for k, v in E.ABILITY_SHORT.items()}           # 'STR' -> 'str'


class SheetImportError(ValueError):
    pass


# ---------------------------------------------------------------------- a tiny DOM
class _Node:
    __slots__ = ("tag", "attrs", "children", "parent")

    def __init__(self, tag: str, attrs: dict, parent=None):
        self.tag, self.attrs, self.children, self.parent = tag, attrs, [], parent

    @property
    def cls(self) -> str:
        return self.attrs.get("class") or ""

    @property
    def tip(self) -> str:
        return self.attrs.get("data-tip") or ""

    def text(self) -> str:
        return "".join(c if isinstance(c, str) else c.text() for c in self.children)

    def own_text(self) -> str:
        """Text outside child elements."""
        return "".join(c for c in self.children if isinstance(c, str))

    def elements(self) -> List["_Node"]:
        return [c for c in self.children if isinstance(c, _Node)]

    def find_all(self, tag: str = None, cls: str = None) -> List["_Node"]:
        out = []
        for c in self.elements():
            if (tag is None or c.tag == tag) and (cls is None or cls in c.cls.split()):
                out.append(c)
            out += c.find_all(tag, cls)
        return out

    def find(self, tag: str = None, cls: str = None) -> Optional["_Node"]:
        found = self.find_all(tag, cls)
        return found[0] if found else None


class _Builder(HTMLParser):
    VOID = {"meta", "br", "hr", "img", "link", "input"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = _Node("#root", {})
        self.cur = self.root

    def handle_starttag(self, tag, attrs):
        node = _Node(tag, dict(attrs), self.cur)
        self.cur.children.append(node)
        if tag not in self.VOID:
            self.cur = node

    def handle_endtag(self, tag):
        node = self.cur
        while node is not self.root and node.tag != tag:      # tolerate unclosed tags
            node = node.parent
        if node is not self.root:
            self.cur = node.parent

    def handle_data(self, data):
        self.cur.children.append(data)


def _parse(html: str) -> _Node:
    b = _Builder()
    b.feed(html)
    b.close()
    return b.root


# ---------------------------------------------------------------------- embedded data
def embedded_data(html: str) -> Optional[dict]:
    """The character dict hidden in sheets exported by this version (None for older sheets)."""
    m = re.search(r'<script[^>]*id=["\']' + DATA_ID + r'["\'][^>]*>(.*?)</script>', html, re.S)
    if not m:
        return None
    try:
        data = json.loads(m.group(1).replace("<\\/", "</"))
    except ValueError:
        return None
    return data if isinstance(data, dict) and data.get("name") else None


def embed(char: Character) -> str:
    """The <script> block export.to_html puts at the end of the sheet."""
    raw = json.dumps(char.to_dict(), ensure_ascii=False, default=str).replace("</", "<\\/")
    return f"<script type='application/json' id='{DATA_ID}'>{raw}</script>"


# ---------------------------------------------------------------------- helpers
def _num(text: str, default: int = 0) -> int:
    m = re.search(r"[+-]?\d+", text or "")
    return int(m.group()) if m else default


def _resolve_race(display: str):
    """'Mountain Dwarf' -> ('Dwarf', 'Mountain'); 'Bugbear (ERLW)' -> ('Bugbear (ERLW)', None)."""
    display = display.strip()
    if display in ("", "No race"):
        return None, None
    if display in rules.races:
        return display, None
    for name, race in rules.races.items():
        if display == f"Variant {name}":
            return name, "Variant"
        for sub in race.get("subraces") or []:
            if display == f"{sub['name']} {name}":
                return name, sub["name"]
    return display, None                                       # unknown to the rules data: keep the name


def _class_line(line: str) -> List[dict]:
    """'Level 5 — Wizard 3 (School of Evocation) / Fighter 2' -> class entries."""
    if "—" not in line:
        return []
    out = []
    for part in line.split("—", 1)[1].split(" / "):
        m = re.match(r"\s*(.+?) (\d+)(?: \((.+)\))?\s*$", part)
        if m:
            out.append({"name": m.group(1), "level": int(m.group(2)), "subclass": m.group(3)})
    return out


def _pairs(text: str, sep: str) -> Dict[str, str]:
    out = {}
    for part in text.split(sep):
        if ":" in part:
            k, v = part.split(":", 1)
            out[k.strip()] = v.strip()
    return out


def _chip_name(chip: _Node) -> str:
    return chip.own_text().strip()


def _sections(page: _Node) -> Dict[str, List[_Node]]:
    """Everything after each <h2>, keyed by the heading, inside the three sheet columns."""
    out: Dict[str, List[_Node]] = {}
    cols = page.find("div", "cols")
    for col in (cols.elements() if cols else []):
        key = None
        for el in col.elements():
            if el.tag == "h2":
                key = el.text().strip().lower()
                out.setdefault(key, [])
            elif key:
                out[key].append(el)
    return out


# ---------------------------------------------------------------------- the visible sheet
def _from_sheet(root: _Node, previous: Optional[Character]) -> dict:
    page = root.find("div", "page") or root
    h1 = page.find("h1")
    if not h1 or not h1.text().strip():
        raise SheetImportError("This HTML file isn't a character sheet exported by the panel.")
    old = copy.deepcopy(previous.d) if previous else None
    d = blank(h1.text().strip())

    header = page.find("header")
    spans = [s for s in header.elements() if s.tag == "span"] if header else []
    title = spans[0].text() if spans else ""
    parts = [p.strip() for p in title.split("·")]
    d["race"], d["subrace"] = _resolve_race(parts[0] if parts and not parts[0].startswith("Level") else "")
    line = next((p for p in parts if p.startswith("Level ")), "")
    d["classes"] = _class_line(line)
    for c in d["classes"]:
        if c["name"] not in rules.classes:
            raise SheetImportError(f"Unknown class '{c['name']}' on the sheet.")
    info = _pairs(spans[1].text(), "·") if len(spans) > 1 else {}
    d["background"] = info.get("Background") or None
    d["alignment"] = info.get("Alignment", "")
    d["xp"] = _num(info.get("Experience", "0"))
    if info.get("Sources"):
        d["sources"] = [s.strip() for s in info["Sources"].split(",") if s.strip()]

    # ---- the band: six vitals, then the six abilities
    tiles = page.find_all("div", "tile")
    vitals = {(t.find("em").text() if t.find("em") else ""): t for t in tiles}
    ab = d["abilities"]
    for t in tiles:
        short = t.find("em").text().strip() if t.find("em") else ""
        a = _SHORT.get(short)
        if not a:
            continue
        tip, extra = t.tip, (t.find("i").text() if t.find("i") else "")
        m = re.search(r"^Base score (\d+)(?: \((.+?)\))?$", tip, re.M)
        if m:
            ab["base"][a] = int(m.group(1))
            if m.group(2):
                d["ability_method"] = m.group(2)
            for key, pattern in (("racial", r"^Race \(.*\) ([+-]\d+)$"), ("improvement", r"^Ability Score Improvements ([+-]\d+)$"),
                                 ("feat", r"^Feats ([+-]\d+)")):
                m = re.search(pattern, tip, re.M)
                if m:
                    ab[key][a] = int(m.group(1))
        else:                                                  # no breakdown: the final score is the base
            ab["base"][a] = _num(extra.split("·")[0], 10)
        if "●" in extra:
            d["proficiencies"]["saves"].append(a)

    hp_tile = vitals.get("Hit Points")
    if hp_tile:
        m = re.match(r"\s*(-?\d+)/(\d+)(?: \(\+(\d+)\))?", hp_tile.find("b").text())
        if m:
            d["hp"]["current"], d["hp"]["temp"] = int(m.group(1)), int(m.group(3) or 0)
        tip = hp_tile.tip
        total_gain = re.search(r"^Hit die results (-?\d+)$", tip, re.M)
        bonus = re.search(r"^Manual adjustment ([+-]\d+)$", tip, re.M)
        d["hp"]["bonus"] = int(bonus.group(1)) if bonus else 0
        d["hp"]["gains"] = _gains(d["classes"], int(total_gain.group(1)) if total_gain else None, old)

    extra = page.find("div", "dim")
    for item in (extra.text().split("  ·  ") if extra and extra.parent is page else []):
        item = item.strip()
        if item.startswith("Hit dice:"):
            for c, part in zip(d["classes"], item[9:].split(",")):
                m = re.match(r"\s*(\d+)/(\d+)d", part)
                if m and int(m.group(2)) - int(m.group(1)):
                    d["hit_dice_used"][c["name"]] = int(m.group(2)) - int(m.group(1))
        elif item.startswith("Conditions:"):
            d["conditions"] = [x.strip() for x in item[11:].split(",") if x.strip()]
        elif item.startswith("Exhaustion"):
            d["exhaustion"] = _num(item)
        elif item == "Inspiration":
            d["inspiration"] = True

    sec = _sections(page)
    prof = d["proficiencies"]
    for row in sec.get("skills", []):
        if "row" not in row.cls:
            continue
        label = row.find("span").own_text().strip()
        marker, _, name = label.partition(" ")
        if name in SKILLS and marker in ("●", "◆"):
            prof["skills"].append(name)
            if marker == "◆":
                prof["expertise"].append(name)
    keys = {"Armor": "armor", "Weapons": "weapons", "Tools": "tools", "Languages": "languages"}
    for p in sec.get("proficiencies", []):
        b = p.find("b")
        key = keys.get(b.text().rstrip(":").strip()) if b else None
        if key:
            value = p.own_text().strip()
            prof[key] = [] if value in ("—", "") else [x.strip() for x in value.split(",") if x.strip()]

    # ---- features: feats and chosen options have their own groups
    source = ""
    for el in sec.get("features & traits", []):
        if el.tag == "p" and el.find("b"):
            source = el.find("b").text().strip()
        elif "chips" in el.cls and source in ("Feat", "Choice"):
            d["feats" if source == "Feat" else "options"] += [_chip_name(c) for c in el.find_all("span", "chip")]
    _character_section(d, sec.get("character", []))

    # ---- spells, slots and resources
    spell_chips: List[tuple] = []
    for el in sec.get("spellcasting", []):
        if el.tag == "p" and el.text().startswith("Slots:"):
            for part in el.text()[6:].split("·"):
                m = re.match(r"\s*(?:(\d+)\w*|Pact \(lvl \d+\)): (\d+)/(\d+)", part)
                if m and int(m.group(3)) - int(m.group(2)):
                    d["slots_used"][m.group(1) or SC.PACT_KEY] = int(m.group(3)) - int(m.group(2))
        elif "chips" in el.cls:
            for chip in el.find_all("span", "chip"):
                name = re.sub(r" \((R|C)\)", "", _chip_name(chip)).strip()
                m = re.search(r"^Source: (.+?) spell list(?: \(.*?\))?(?: - innate (.+))?$", chip.tip, re.M)
                spell = rules.spell(name)
                if spell:
                    spell_chips.append((spell, m.group(1) if m else "", (m.group(2) if m else "") or ""))
    for p in sec.get("resources", []):
        m = re.match(r"(.+): (\d+|∞)/(\d+|∞) \(", p.text())
        if m and m.group(3) != "∞" and int(m.group(3)) - int(m.group(2)):
            d["resources"][m.group(1)] = int(m.group(3)) - int(m.group(2))

    # ---- equipment and coins
    for el in sec.get("equipment", []):
        if "chips" in el.cls:
            for chip in el.find_all("span", "chip"):
                small = chip.find("small")
                marks = small.text() if small else ""
                m = re.match(r"(.+?)(?: ×(\d+))?$", _chip_name(chip))
                d["inventory"].append({"name": m.group(1), "qty": int(m.group(2) or 1), "equipped": "⚔" in marks,
                                       "attuned": "✦" in marks, "note": ""})
        elif el.tag == "p":
            coins = el.text().split("·")[0]
            for n, coin in re.findall(r"(\d+) (\w\w)\b", coins):
                if coin in d["currency"]:
                    d["currency"][coin] = int(n)

    if old:
        _keep_hidden(d, old)
    _place_spells(d, spell_chips, old)
    if d["options"] and not d["choices"].get("groups"):
        _option_groups(d)
    if not info.get("Sources") and not (old and old.get("sources")):
        d["sources"] = _guess_sources(d, [s for s, _c, _u in spell_chips])
    return d


def _gains(classes: List[dict], total: Optional[int], old: Optional[dict]) -> List[int]:
    """Hit die results per level: the old ones when they still add up, else max at level 1 and averages after."""
    level = sum(c["level"] for c in classes)
    if old and len(old["hp"]["gains"]) == level and (total is None or sum(old["hp"]["gains"]) == total):
        return list(old["hp"]["gains"])
    gains = []
    for i, c in enumerate(classes):
        die = rules.classes[c["name"]]["hit_die"]
        gains += [die if i == 0 and n == 0 else die // 2 + 1 for n in range(c["level"])]
    if gains and total is not None:
        gains[-1] += total - sum(gains)
    return gains


def _character_section(d: dict, els: List[_Node]):
    det = d["details"]
    for el in els:
        if el.tag == "p":
            for k, v in _pairs(el.text(), "  ·  ").items():
                if k.lower() in det:
                    det[k.lower()] = v
        elif "chips" in el.cls:
            for chip in el.find_all("span", "chip"):
                head, _, body = chip.tip.partition("\n\n")
                if head == "Note":
                    d["notes"].append({"id": d["next_note_id"], "timestamp": int(time.time()), "text": body})
                    d["next_note_id"] += 1
                elif head.lower() in det:
                    det[head.lower()] = body


def _keep_hidden(d: dict, old: dict):
    """What a sheet doesn't show comes from the character being replaced."""
    for key in ("ancestry", "death_saves", "sources", "ability_method"):
        if old.get(key) and not (key == "ability_method" and d.get(key)):
            d[key] = copy.deepcopy(old[key])
    if d["race"] == old.get("race") and d["subrace"] == old.get("subrace"):
        d["racial_spells"] = copy.deepcopy(old.get("racial_spells") or [])
    same_build = [(c["name"], c["level"]) for c in d["classes"]] == [(c["name"], c["level"]) for c in old.get("classes", [])]
    choices = copy.deepcopy(old.get("choices") or {})
    if not same_build:                                          # the level choices no longer describe this build
        choices = {k: v for k, v in choices.items() if k == "milestone"}
    else:
        if old.get("level_history"):
            d["level_history"] = copy.deepcopy(old["level_history"])
    d["choices"] = choices
    notes = {n.get("text"): n for n in old.get("notes", []) if isinstance(n, dict)}
    for i, n in enumerate(d["notes"]):                          # unchanged notes stay as they were
        if n["text"] in notes:
            d["notes"][i] = copy.deepcopy(notes[n["text"]])
    d["next_note_id"] = max([old.get("next_note_id", 1)] + [n["id"] + 1 for n in d["notes"]])
    for item in d["inventory"]:
        prev = next((e for e in old.get("inventory", []) if e["name"] == item["name"]), None)
        if prev and prev.get("note"):
            item["note"] = prev["note"]


def _place_spells(d: dict, chips: List[tuple], old: Optional[dict]):
    """Put each listed spell where it belongs: cantrips / known / prepared per class, or innate (racial) spells."""
    char = Character(d)
    racial = [s for s, cls, _u in chips if cls == "Racial"]
    have = {r["name"] for r in d["racial_spells"]}
    if racial and {s["name"] for s in racial} != have:
        prev = {r["name"]: r for r in ((old or {}).get("racial_spells") or [])}
        d["racial_spells"] = []
        for spell, cls, uses in chips:
            if cls != "Racial":
                continue
            entry = copy.deepcopy(prev.get(spell["name"])) or {"name": spell["name"], "level_req": 1,
                                                               "ability": _racial_ability(d), "source": "Race"}
            if uses:
                entry["uses"] = uses
            d["racial_spells"].append(entry)
    elif not racial:
        d["racial_spells"] = [r for r in d["racial_spells"] if r.get("level_req", 1) > char.total_level]
    d["spells"] = {}
    infos = {i["class"]: i for i in SC.casters(char)}
    for spell, cls, _u in chips:
        if cls not in infos:
            continue
        sp = SC.class_spells(char, cls)
        bonus = d["choices"].get("bonus_cantrips", {}).get(cls, [])
        if spell["level"] == 0:
            if spell["name"] not in bonus and spell["name"] not in sp["cantrips"]:
                sp["cantrips"].append(spell["name"])
        elif spell["name"] in SC.always_prepared(char, cls):
            continue
        elif infos[cls]["prepared"] is None:
            sp["known"].append(spell["name"])
        else:
            sp["prepared"].append(spell["name"])
    for cls, sp in d["spells"].items():
        if infos[cls]["spellbook"]:
            before = (((old or {}).get("spells") or {}).get(cls) or {}).get("spellbook", [])
            sp["spellbook"] = list(dict.fromkeys(before + sp["prepared"]))


def _racial_ability(d: dict) -> str:
    from .creation import _spell_blocks
    race = rules.races.get(d["race"] or "")
    sub = next((s for s in (race or {}).get("subraces") or [] if s["name"] == d["subrace"]), None)
    for block in _spell_blocks(race, sub) if race else []:
        ability = block.get("ability", "cha")
        if isinstance(ability, str):
            return ability
        char = Character(copy.deepcopy(d))                      # a choice: the best of the allowed scores
        return max(ability.get("choose") or ["cha"], key=char.ability_score)
    return "cha"


def _option_groups(d: dict):
    """Which class option group (Fighting Style, Eldritch Invocations...) each chosen option fills."""
    from .leveling import option_groups
    char = Character(d)
    types = {o["name"]: set(o["types"]) for o in rules.optional_features.values()}
    left = [o for o in d["options"] if o in types]
    groups = d["choices"].setdefault("groups", {})
    for c in d["classes"]:
        for g in option_groups(char, c["name"], c["level"], c.get("subclass")):
            picks = [o for o in left if types[o] & set(g["types"])][:g["total"]]
            if picks:
                groups[g["key"]] = picks
                left = [o for o in left if o not in picks]


def _guess_sources(d: dict, spells: List[dict]) -> List[str]:
    """PHB plus every book the race, subclasses, feats, spells and items come from."""
    found = ["PHB"]
    race = rules.races.get(d["race"] or "")
    if race:
        found.append(race.get("source"))
        sub = next((s for s in race.get("subraces") or [] if s["name"] == d["subrace"]), None)
        if sub:
            found.append(sub.get("source"))
    for c in d["classes"]:
        sub = rules.subclass(c["name"], c["subclass"]) if c.get("subclass") else None
        if sub:
            found.append(sub.get("source"))
    found += [(rules.feats.get(f) or {}).get("source") for f in d["feats"]]
    found += [s.get("source") for s in spells]
    found += [(rules.item(e["name"]) or {}).get("source") for e in d["inventory"]]
    return [s for s in dict.fromkeys(found) if s and s not in ("DMG", "MM")] or ["PHB"]


# ---------------------------------------------------------------------- entry point
def from_html(html: str, previous: Optional[Character] = None) -> Character:
    """The character in an exported HTML sheet. `previous`: the existing character of that name, if any."""
    data = embedded_data(html)
    if data is not None:
        return Character.from_dict(data)
    return Character(_from_sheet(_parse(html), previous))


def name_in(html: str) -> str:
    """The character name an exported sheet is for ('' if it isn't one)."""
    data = embedded_data(html)
    if data:
        return str(data["name"])
    h1 = _parse(html).find("h1")
    return h1.text().strip() if h1 else ""
