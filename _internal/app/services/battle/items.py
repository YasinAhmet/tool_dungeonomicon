"""Using what a hero carries in a fight: potions (drunk, or poured into a creature within reach), spell scrolls, caltrops.

    b.use_options(c)                          -> [{'value': item name, 'label'}] for the Use an Object action
    b.use_item(cid, 'Potion of Speed', tid)   drink it (or give it to tid within 5 ft); an action
    b.read_scroll(cid, 'Spell Scroll (Fireball)', targets=, point=)

Potions (DMG chapter 7): healing ones heal; the ones that matter in a fight put on an effect for their duration
(Potion of Speed is Haste without concentration, Giant Strength sets Strength, Fire Breath gives three bonus-action
breaths). Spell scrolls (DMG chapter 7): the spell must be on one of the reader's class lists; one higher than the
reader can cast takes an ability check (DC 10 + its level) or the scroll is wasted. The scroll's own save DC and attack
bonus are used, no slot is spent, the scroll crumbles. A scroll is named after its spell: "Spell Scroll (Fireball)",
"Scroll of Fireball" or "Spell Scroll: Fireball".

Wands and staffs (DMG chapter 7) cast the spells their text names for charges, as an action: a Wand of Fireballs with
its own DC 15, a Staff of Fire with the wielder's own DC. More charges raise the spell's level where the wand allows it.
The charges left are kept on the item in the pack; a wand whose last charge is spent may crumble (a 1 on a d20).

    b.charged_items(c)                        -> [{'item', 'spell', 'cost', 'level', 'left', 'more', 'dc', 'atk', 'why'}]
    b.use_wand(cid, 'Wand of Fireballs', 'Fireball', charges=2, point=)
"""
import re
from typing import List, Optional

from ...rules import spellcasting as SC
from ...rules.data import rules
from ...rules.character import fresh_charges
from ...rules.dice import roll_dice
from ..common import ServiceError
from . import spellbook as SB

SCROLL_RE = re.compile(r"^(?:spell\s+)?scroll\b(?:\s+of\s+|\s*[:(\-–]\s*)(.+?)\)?$", re.I)
SCROLL_NUMBERS = [(0, 13, 5), (1, 13, 5), (2, 13, 5), (3, 15, 7), (4, 15, 7), (5, 17, 9), (6, 17, 9), (7, 18, 10), (8, 18, 10), (9, 19, 11)]
GIANTS = {"hill": 21, "stone": 23, "frost": 23, "fire": 25, "cloud": 27, "storm": 29}
# combat potions: the effect they put on the drinker (rounds: 10 = 1 minute, 600 = 1 hour)
POTIONS = {
    "potion of speed": {"name": "Haste (Potion of Speed)", "mods": {"ac": 2, "save_adv": ["dex"], "speed_mult": 2, "extra_action": 1}, "rounds": 10},
    "potion of invisibility": {"name": "Invisible (potion)", "conds": ["Invisible"], "mods": {"ends_on": ["attack", "cast"]}, "rounds": 600},
    "potion of heroism": {"name": "Bless (Potion of Heroism)", "mods": {"attack": "1d4", "save": "1d4"}, "temp": 10, "rounds": 600},
    "potion of invulnerability": {"name": "Invulnerable (potion)", "mods": {"resist": ["acid", "bludgeoning", "cold", "fire", "force", "lightning",
                                                                                    "necrotic", "piercing", "poison", "psychic", "radiant",
                                                                                    "slashing", "thunder"]}, "rounds": 10},
    "potion of growth": {"name": "Enlarge/Reduce (Potion of Growth)", "mods": {"dmg": ("1d4", ""), "save_adv": ["str"]}, "rounds": 100},
    "potion of flying": {"name": "Flying (potion)", "mods": {"fly": 30}, "rounds": 600},
    "potion of fire breath": {"name": "Fire Breath (potion)", "mods": {}, "rounds": 600,
                              "grant": {"name": "Fire Breath", "cost": "bonus", "save": "dex", "half": True, "range": 30, "dc": 13,
                                        "parts": [["4d6", "fire"]], "uses": 3}},
    "potion of dragon's breath": {"name": "Dragon's Breath (potion)", "mods": {}, "rounds": 10, "dtype": True,       # AU: the colour of the potion (its note) sets the type
                                  "grant": {"name": "Dragon's Breath", "cost": "action", "area": {"shape": "cone", "size": 15, "origin": "caster"},
                                            "save": "dex", "half": True, "dc": 13, "parts": [["3d6", "fire"]]}},
    "potion of gaseous form": {"name": "Gaseous Form (potion)", "mods": {"resist": ["nonmagical"], "save_adv": ["str", "dex", "con"], "fly": 10,
                                                                         "speed_set": 10, "incorporeal": True}, "rounds": 600},
    "potion of diminution": {"name": "Enlarge/Reduce (Potion of Diminution)", "mods": {"save_dis": ["str"], "check_dis": ["str"]}, "rounds": 1500},
    "potion of poison": {"name": "Poisoned (Potion of Poison)", "conds": ["Poisoned"], "rounds": 600,      # 3d6 a turn until a DC 13 Con save
                         "mods": {"dot": {"dice": "3d6", "type": "poison", "when": "start", "save": "con"}}},
    "potion of climbing": {"name": "Climbing (potion)", "mods": {"climb_walk": True}, "rounds": 600},
    "potion of water breathing": {"name": "Water Breathing (potion)", "mods": {"water_breathing": True}, "rounds": 600},
    "oil of etherealness": {"name": "Etherealness (oil)", "mods": {"untargetable": True, "incorporeal": True}, "rounds": 600},
    "oil of sharpness": {"name": "Oil of Sharpness", "mods": {"weapon_attack": "3", "dmg": ("3", "")}, "rounds": 600},
    "oil of slipperiness": {"name": "Freedom of Movement (Oil of Slipperiness)", "mods": {"immune_cond": ["Paralyzed", "Restrained", "Grappled"]},
                            "rounds": 4800},
    "potion of psionic fortitude": {"name": "Psionic Fortitude (potion)", "mods": {"cond_save_adv": ["Charmed", "Stunned"]}, "rounds": 600},
    "potion of maximum power": {"name": "Maximum Power (potion)", "mods": {"max_spell": 4, "once": True}, "rounds": 10},    # the next damage spell of 4th level or lower
    "potion of advantage": {"name": "Advantage (potion)", "mods": {"attacks_with": "adv", "once": True}, "rounds": 600},     # the next attack roll
    "potion of giant size": {"name": "Giant Size (potion)", "str": 25, "rounds": 14400},           # Strength 25 (Huge size and HP not modelled)
    "potion of dragon's majesty": {"name": "Dragon's Majesty (potion)", "form": [f"Adult {k} Dragon|MM" for k in (
        "Black", "Blue", "Green", "Red", "White", "Brass", "Bronze", "Copper", "Gold", "Silver")], "rounds": 600},
    "potion of aqueous form": {"name": "Aqueous Form (potion)", "mods": {"resist": ["nonmagical"], "incorporeal": True}, "rounds": 100},
}
for _kind, _str in GIANTS.items():
    POTIONS[f"potion of {_kind} giant strength"] = {"name": f"{_kind.title()} Giant Strength (potion)", "str": _str, "rounds": 600}
for _t in ("acid", "cold", "fire", "force", "lightning", "necrotic", "poison", "psychic", "radiant", "thunder"):
    POTIONS[f"potion of {_t} resistance"] = {"name": f"{_t.title()} resistance (potion)", "mods": {"resist": [_t]}, "rounds": 600}
POTIONS["potion of resistance"] = {"name": "Resistance (potion)", "choose": True, "rounds": 600}
SPREAD = {"caltrops (bag of 20)": {"name": "Caltrops", "size": 1, "dc": 15, "save": "dex", "parts": [["1", "piercing"]],
                                   "fail_mods": {"speed": -10, "stop_move": True, "ends_on": ["heal"]}},
          "ball bearings (bag of 1,000)": {"name": "Ball bearings", "size": 2, "dc": 10, "save": "dex", "prone": True}}


WAND_ONE = re.compile(r"expend (?:1|one)( or more)? of its charges to cast the ([a-z' /-]+?) spell(?: \(save DC (\d+)"
                      r"(?:, \+(\d+) to hit with spell attacks)?\))? from it", re.I)
WAND_BASE = re.compile(r"For 1 charge, you cast the (\d)(?:st|nd|rd|th)-level version", re.I)
STAFF = re.compile(r"cast one of the following spells from it[^:]*:\s*(.+?)\.\s*(?:\n|$)", re.I | re.S)    # to the paragraph's end
STAFF_SPELL = re.compile(r"(?:,\s*|^|\bor\s+)([a-z' /-]+?) \((\d+) charges?[^)]*\)", re.I)


def charged_spells(item_name: str) -> List[dict]:
    """The spells a wand or staff casts from its charges: [{'spell', 'cost', 'level', 'more', 'dc', 'atk'}] (dc None: the
    wielder's own)."""
    data = rules.item(item_name) or {}
    text = data.get("text") or ""
    if not data.get("charges"):
        return []
    out = []
    m = WAND_ONE.search(text)
    if m:
        sp = rules.spell(m.group(2).strip())
        if sp:
            base = WAND_BASE.search(text)
            out.append({"spell": sp, "cost": 1, "level": int(base.group(1)) if base else sp["level"], "more": bool(m.group(1)) and bool(base),
                        "dc": int(m.group(3)) if m.group(3) else None, "atk": int(m.group(4)) if m.group(4) else None})
    st = STAFF.search(text)
    if st:
        for name, cost in STAFF_SPELL.findall(st.group(1)):
            sp = rules.spell(re.sub(r"^or\s+", "", name.strip(), flags=re.I))
            if sp:
                out.append({"spell": sp, "cost": int(cost), "level": sp["level"], "more": False, "dc": None, "atk": None})
    return out


TATTOO_RE = re.compile(r"^Spellwrought Tattoo \((?:(\d)(?:st|nd|rd|th) Level|Cantrip)\)$", re.I)
TATTOO_NUMS = re.compile(r"ability modifier for this spell is \+(\d+); the save DC is (\d+) and the attack bonus is \+(\d+)", re.I)


def tattoo_spell(entry: dict) -> Optional[dict]:
    """A Spellwrought Tattoo's one spell (TCE): the item only says its level, so the spell is the one named in the pack
    entry's `spell` field or its note ('Fireball'). Cast once, then the tattoo is gone. Uses the item table's DC, attack
    bonus and ability modifier. Returns the same dict as `item_spells` plus 'tattoo' and 'mod', or None."""
    if (entry.get("name") or "").strip() == "Thayan Spell Tattoo":      # (FRHoF) the tattoo's creator chose a level 1-3 spell: the pack entry's note names it
        for field in (entry.get("spell"), entry.get("note")):
            for part in re.split(r"[,;:/\n]+", str(field or "")):
                sp = rules.spell(part.strip())
                if sp and 1 <= sp["level"] <= 3:                        # (a caster's own DC and modifier; without them DC 13 and +5, use_wand)
                    return {"spell": sp, "cost": 0, "level": sp["level"], "more": False, "dc": None, "atk": None, "daily": False, "at_will": False,
                            "tattoo": True, "mod": None}
        return None
    m = TATTOO_RE.match((entry.get("name") or "").strip())
    if not m:
        return None
    level = int(m.group(1) or 0)
    text = (rules.item(entry["name"]) or {}).get("text") or ""
    n = TATTOO_NUMS.search(text)
    mod, dc, atk = (int(n.group(1)), int(n.group(2)), int(n.group(3))) if n else (3, 13, 5)
    for field in (entry.get("spell"), entry.get("note")):
        for part in re.split(r"[,;:/\n]+", str(field or "")):
            sp = rules.spell(part.strip())
            if sp and sp["level"] == level:
                return {"spell": sp, "cost": 0, "level": level, "more": False, "dc": dc, "atk": atk, "daily": False, "at_will": False,
                        "tattoo": True, "mod": mod}
    return None


CURES = {"elixir of health": ["Blinded", "Deafened", "Paralyzed", "Poisoned"], "potion of vitality": ["Poisoned", "exhaustion"]}
NUM = {"a": 1, "an": 1, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5}
LIST_RE = re.compile(r"cast (?:one of the following|these) spells(?P<head>[^:]*?):\s*(?P<list>[^\n]+)", re.I)
DAILY_SENT = re.compile(r"until (?:the next )?(?:dawn|dusk|sunset)|once (?:per|a) day|1/day|can't (?:be )?(?:cast|used?|activated)[^.]*again|"
                        r"can be used (?:two|three|four|five|six|\d+) times", re.I)       # (a Harp of Gilded Plenty's five uses a day: once, as before)
SPELLS_ONCE = re.compile(r"one of these (?:properties|powers|abilities|spells) is used[^.]*can't|can't be used to cast that spell again|"
                         r"can't cast that spell again", re.I)    # Dissuader, an Instrument of the Bards: every spell of it, once until dawn
AFTER_RE = re.compile(r"(?: spell)?(?: as an? (?P<lv1>\d)(?:st|nd|rd|th)-level spell| at (?P<lv2>\d)(?:st|nd|rd|th) level)?"
                      r"(?: \((?:spell )?(?:save DC (?P<dc>\d+)|\+(?P<atk>\d+) to hit))?", re.I)     # what follows the spell's name


def item_spells(item_name: str) -> List[dict]:
    """The spells any magic item casts beyond a wand's or staff's usual wording ('cast one of the following spells (save
    DC 16): Command (1 charge)...', 'expend 1 charge to cast dominate beast (save DC 15)', 'use an action to cast the
    disintegrate spell (save DC 18). ... until the next dawn', 'cast the levitate spell on yourself at will'):
    [{'spell', 'cost' (charges; 0 = a day's use or at will), 'level', 'more', 'dc', 'atk', 'daily', 'at_will'}]."""
    data = rules.item(item_name) or {}
    text = re.sub(r"\{@\w+ ([^}|]+)[^}]*\}", r"\1", data.get("text") or "")
    text = re.sub(r"(following spells[^:\n]*:)[ \t]*\n+((?:[ \t]*•[^\n]+\n?)+)",          # a bulleted list (Ring of Animal Influence): one line
                  lambda m: m.group(1) + " " + ", ".join(x.strip(" \t•") for x in m.group(2).splitlines() if x.strip()) + "\n", text)
    if not data.get("magic") or data.get("type") in ("P", "SC") or not re.search(r"\bcast\b", text) or re.search(r"\bd100\b", text):
        return []                                         # a Wand of Wonder's table: its spells aren't the wielder's pick
    charged = bool(data.get("charges"))
    out, seen = [], set()
    paras = [[x for x in re.split(r"(?<=[.])\s+", p) if x.strip()] for p in text.split("\n") if p.strip()]
    once_each = any(SPELLS_ONCE.search(p) for p in text.split("\n"))

    def named(sent):
        """The spell a sentence says is cast ('...used to cast Plant Growth, it can't...'), or None."""
        for st in re.finditer(r"\bcast (?:the )?", sent, re.I):
            words = re.findall(r"[A-Za-z'/-]+", sent[st.end():st.end() + 60])
            for k in range(min(5, len(words)), 0, -1):
                sp2 = rules.spell(" ".join(words[:k]))
                if sp2:
                    return sp2["name"]
        return None

    def daily_for(sp, sentence):
        """Is this spell limited to once until the next dawn? A limit counts when it is in the cast's own paragraph and isn't
        about another spell there (a rod's Druidcraft is free though its Plant Growth is not), or when the item says every
        one of its properties is once a day."""
        if once_each:
            return True
        for k, ps in enumerate(paras):
            if sentence in ps:
                after = paras[k + 1][:1] if k + 1 < len(paras) and re.match(r"Once\b", paras[k + 1][0]) else []     # "Once the weapon has been used..."
                for t in ps + after:
                    if DAILY_SENT.search(t) and named(t) in (None, sp["name"]):
                        return True
        return False

    def put(sp, cost, level, dc, atk, sentence, at_will=None, once=False):
        if not sp or sp["name"] in seen:
            return
        low = sentence.lower()
        if re.search(r"as if you had cast|can't cast|cast into it|stores spells|when you cast|if you cast|the efreeti|you can try to cast|"
                     r"on a successful check|gain the ability|granted the ability to cast|when i cast|you cast the clone spell|must cast the wish spell", low):
            return                                      # summons by command word, spell storage, other things that aren't casting
        seen.add(sp["name"])
        at_will = "at will" in low if at_will is None else at_will
        daily = not at_will and not cost and (once or daily_for(sp, sentence))
        if not cost and not at_will and not daily and charged:
            cost = 1
        out.append({"spell": sp, "cost": cost, "level": int(level) if level else sp["level"], "more": False,
                    "dc": int(dc) if dc else None, "atk": int(atk) if atk else None, "daily": daily, "at_will": at_will})

    tbl = re.search(r"^Spell \| Charge Cost\s*$", text, re.M)
    if tbl:                                                  # a table of the spells and what each costs (Diamond Staff, Orb of Damara, Wand of Slumber)
        dcm = re.search(r"spell save DC (\d+)", text)
        atkm = re.search(r"\+(\d+) spell attack", text)
        for name, cost in re.findall(r"^([^|\n]+?)\s*\|\s*(\d+)\s*$", text[tbl.end():], re.M):
            lv = re.search(r"level (\d)", name)
            rdc = re.search(r"save DC (\d+)", name)
            sp = rules.spell(re.sub(r"\s*\(.*$", "", name).strip())
            if sp and sp["name"] not in seen:
                seen.add(sp["name"])
                out.append({"spell": sp, "cost": int(cost), "level": int(lv.group(1)) if lv else sp["level"], "more": False,
                            "dc": int(rdc.group(1)) if rdc else int(dcm.group(1)) if dcm else None,
                            "atk": int(atkm.group(1)) if atkm else None, "daily": False, "at_will": not int(cost)})
    if re.search(r"\|\s*Spell\s*$", text, re.M):               # Necklace of Prayer Beads: a table of beads and the spell of each
        for row in re.findall(r"^[^|\n]+\|[^|\n]+\|\s*([^|\n]+)$", text, re.M):
            for part in re.split(r"\s+or\s+", row.strip()):
                lv = re.search(r"\((\d)(?:st|nd|rd|th) level\)", part)
                put(rules.spell(re.sub(r"\s*\(.*$", "", part).strip()), 0, lv.group(1) if lv else None, None, None, "a bead's spell",
                    once=bool(DAILY_SENT.search(text)))             # (each bead: once until the next dawn)
    for s in re.split(r"(?<=[.])\s+|\n+", text):
        if not re.search(r"\bcast\b", s):
            continue
        m = LIST_RE.search(s)
        if m:
            dc = re.search(r"save DC (\d+)|save (\d+)\)", m.group("head") + s)
            dcv = (dc.group(1) or dc.group(2)) if dc else None
            each = re.search(r"expend (\d|one|1) (?:of its )?charges? to cast one", s, re.I)
            parts = []
            for chunk in re.split(r",\s*(?:(?:and|or)\s+)?", m.group("list").rstrip(".")):    # ("Create or Destroy Water" is one spell)
                parts += [chunk] if rules.spell(re.sub(r"\s*\([^)]*\)", "", chunk).strip(" .")) else re.split(r"\s+or\s+", chunk)
            for part in parts:
                nm = re.sub(r"\s*\(.*$", "", part).strip(" .")
                cm = re.search(r"(\d+) charges?", part)        # "(2 charges)", "(5th-level version, 5 charges)"
                lv = re.search(r"(\d)(?:st|nd|rd|th)-level version", part)
                cost = int(cm.group(1)) if cm else (NUM.get(each.group(1).lower(), 1) if each and not each.group(1).isdigit() else int(each.group(1)) if each else 0)
                put(rules.spell(nm), cost, lv.group(1) if lv else None, dcv, None, s, True if "these spells" in s.lower() and not charged else None)
            continue
        either = re.search(r"\bcast either ([A-Za-z' /-]+?)(?: \((?:spell )?save DC (\d+)\))? or ([A-Za-z' /-]+?)(?: \((?:spell )?save DC (\d+)\))?"
                           r"(?: from|[.,]|$)", s)
        if either:                                           # a Staff of the Lost: "expend 1 charge to cast either Maze (save DC 18) or Teleport from it"
            cm = re.search(r"expend (\d|one|a|two|three) (?:of its )?(?:\d+ )?charges?", s, re.I)
            n = (int(cm.group(1)) if cm.group(1).isdigit() else NUM.get(cm.group(1).lower(), 1)) if cm else 0
            def lead(txt):                                   # "speak with plants with the staff": the longest start that is a spell
                w = txt.split()
                return next((rules.spell(" ".join(w[:k])) for k in range(len(w), 0, -1) if rules.spell(" ".join(w[:k]))), None)
            put(lead(either.group(1).strip()), n, None, either.group(2) or either.group(4), None, s)
            put(lead(either.group(3).strip()), n, None, either.group(4) or either.group(2), None, s)
            continue
        for start in re.finditer(r"\bcast (?:the |either )?", s, re.I):
            words = re.findall(r"[A-Za-z'/-]+", s[start.end():start.end() + 60])
            sp, tail, i = None, "", 0
            for k in range(min(5, len(words)), 0, -1):         # the longest name that is a spell ("gust of wind", not "gust")
                sp = rules.spell(" ".join(words[:k]))
                if sp:
                    i = start.end() + s[start.end():].lower().find(words[k - 1].lower()) + len(words[k - 1])
                    tail = s[i:i + 80]
                    break
            if not sp:
                continue
            m = AFTER_RE.match(tail)
            cm = re.search(r"expend (\d|one|a|two|three) (?:of its )?(?:\d+ )?charges?|spend (\d) charges", s, re.I)
            cost = 0
            if cm:
                g = cm.group(1) or cm.group(2)
                cost = int(g) if g.isdigit() else NUM.get(g.lower(), 1)
            dc = m.group("dc") or (re.search(r"save DC for (?:these|this|the) spells? is (\d+)", text) or [None, None])[1]   # Mastix: in the next sentence
            own = re.match(r" \((?:expending )?(\d+) charges?", tail)      # Hazirawn's "detect thoughts (2 charges)"
            daily = daily_for(sp, s)
            put(sp, int(own.group(1)) if own else cost, m.group("lv1") or m.group("lv2"), dc, m.group("atk"), s)
            while True:                                      # "cast charm person, command, or comprehend languages from it": each one
                nx = re.match(r"(?: \([^)]*\)?)?(?:,\s*(?:or\s+|and\s+)?|\s+or\s+)", s[i:])
                words = re.findall(r"[A-Za-z'/-]+", s[i + nx.end():i + nx.end() + 60]) if nx else []
                k = next((k for k in range(min(5, len(words)), 0, -1) if rules.spell(" ".join(words[:k]))), 0)
                if not k:
                    break
                i += nx.end() + s[i + nx.end():].lower().find(words[k - 1].lower()) + len(words[k - 1])
                m = AFTER_RE.match(s[i:i + 80])
                own = re.match(r" \((?:expending )?(\d+) charges?", s[i:i + 30])
                put(rules.spell(" ".join(words[:k])), int(own.group(1)) if own else cost, m.group("lv1") or m.group("lv2"), m.group("dc") or dc,
                    m.group("atk"), s, once=daily)           # (the Lyre of Building: each of them once until dawn, like the first)
    return out


def scroll_spell(item_name: str) -> Optional[dict]:
    """The spell a scroll holds, read from its name ('Spell Scroll (Fireball)'), or None."""
    m = SCROLL_RE.match((item_name or "").strip())
    if not m:
        return None
    name = m.group(1).strip()
    if re.match(r"\d+(st|nd|rd|th) level|cantrip", name, re.I):
        return None
    return rules.spell(name)


class ItemsMixin:
    def use_options(self, c: dict) -> List[dict]:
        """What this creature could use from its pack (a monster: what it carries) with the Use an Object action: potions
        and spread-out gear."""
        char = self._sheet(c)
        if c.get("form"):                                      # a wolf (Wild Shape, Polymorph) has no hands for a potion
            return []
        out = []
        for e in (char.d.get("inventory") or []) if char else (c.get("items") or []):
            nm = e.get("name") or ""
            low = nm.lower()
            data = rules.item(nm)
            if low in SPREAD or (data and data.get("type") == "P") or low in POTIONS or re.search(r"regain \d+d\d+", (data or {}).get("text") or ""):
                out.append({"value": nm, "label": nm + (f" ×{e['qty']}" if int(e.get("qty") or 1) > 1 else "")})
        return out

    def scroll_items(self, c: dict) -> List[dict]:
        """The spell scrolls in this hero's pack: [{'item', 'spell', 'why' (None when it can be read)}]."""
        char = self._sheet(c)
        if not char or c.get("form"):                          # no reading in beast shape
            return []
        out = []
        for e in char.d.get("inventory") or []:
            sp = scroll_spell(e.get("name") or "")
            if sp:
                out.append({"item": e["name"], "spell": sp, "why": self._scroll_why(char, sp)})
        return out

    @staticmethod
    def _scroll_why(char, sp: dict) -> Optional[str]:
        mine = {i["class"] for i in SC.casters(char)}
        if not mine & set(sp.get("classes") or []):
            return f"{sp['name']} isn't on {char.name}'s spell lists"
        return None

    def charged_items(self, c: dict) -> List[dict]:
        """The wands and staffs in this hero's pack and the spells their charges cast."""
        char = self._sheet(c)
        if not char or c.get("form"):
            return []
        out = []
        for e in char.d.get("inventory") or []:
            for o in self._item_spell_list(e.get("name") or "", e):
                left = self._charges_left(e)
                why = None if left >= o["cost"] else f"{e['name']} has {left} charges left"
                data = rules.item(e["name"]) or {}
                if data.get("attune") is not None and not e.get("attuned"):
                    why = f"{e['name']} needs attunement"
                elif o.get("daily") and char.d["resources"].get(f"item:{data.get('name')}:{o['spell']['name']}"):
                    why = "Used until the next dawn"
                out.append(dict(o, item=e["name"], left=left, why=why))
        return out

    @staticmethod
    def _item_spell_list(name: str, entry: Optional[dict] = None) -> List[dict]:
        """A wand's or staff's spells, then whatever else the item's text says it casts (each spell once). A Spellwrought
        Tattoo (the pack entry given) casts the one spell its entry names."""
        tat = tattoo_spell(entry or {"name": name})
        if tat:
            return [tat]
        if name == "Ring of Spell Storing" or name.startswith("Spell Gem ("):    # the spells inside it (spellitems.stored_spells): cast once, then gone
            from .spellitems import stored_spells
            return stored_spells(entry or {})
        out = charged_spells(name)
        have = {o["spell"]["name"] for o in out}
        return out + [o for o in item_spells(name) if o["spell"]["name"] not in have]

    @staticmethod
    def _charges_left(entry: dict) -> int:
        if entry.get("charges_left") is not None:
            return int(entry["charges_left"])
        n = (rules.item(entry["name"]) or {}).get("charges") or 0
        qty = max(1, int(entry.get("qty") or 1))                # a stack of 2 wands: both wands' charges (character.fresh_charges)
        if isinstance(n, str) and not n.isdigit():              # a Luck Blade's "1d4 - 1", a Stonemaker War Pick's "1d6 + 1": rolled the first time
            n = fresh_charges(entry["name"], qty)
            entry["charges_left"] = n                           # (kept on the pack entry; the next save writes it)
            return n
        return int(n) * qty

    def use_wand(self, cid: int, item: str, spell: str, charges: Optional[int] = None, targets: Optional[List[int]] = None, point=None,
                 dtype: Optional[str] = None, adv: Optional[str] = None) -> str:
        """Cast a spell from a wand or staff: an action, its charges spent (more of them for a higher level where allowed)."""
        with self.lock:
            self._busy()
            att = self._find(cid)
            char = self._sheet(att)
            if att.get("form"):
                raise ServiceError(f"{att['name']} can't use that in {att['form']['name'].lower()} form.")
            entry = char.find_item(item) if char else None
            if not entry:
                raise ServiceError(f"{att['name']} doesn't have '{item}'.")
            o = next((x for x in self._item_spell_list(entry["name"], entry) if x["spell"]["name"].lower() == str(spell).lower()), None)
            if not o:
                raise ServiceError(f"{entry['name']} doesn't cast {spell}.")
            data = rules.item(entry["name"]) or {}
            if data.get("attune") is not None and not entry.get("attuned"):
                raise ServiceError(f"{entry['name']} needs attunement first.")
            day_key = f"item:{data.get('name')}:{o['spell']['name']}"
            if o.get("daily") and char.d["resources"].get(day_key):
                raise ServiceError(f"{entry['name']} can't cast {o['spell']['name']} again until the next dawn.")
            left = self._charges_left(entry)
            spend = max(o["cost"], int(charges or o["cost"])) if o["more"] else o["cost"]
            if spend > left:
                raise ServiceError(f"{entry['name']} has {left} charge{'s' if left != 1 else ''} left.")
            sp = o["spell"]
            level = min(9, o["level"] + (spend - o["cost"]))
            infos = SC.casters(char)
            ab = infos[0]["ability"] if infos else "int"
            own_dc, own_atk = 8 + char.proficiency_bonus + char.mod(ab), char.proficiency_bonus + char.mod(ab)
            dc, atk = o["dc"] or (own_dc if infos else 13), o["atk"] or (own_atk if infos else 5)
            cast_mod = o["mod"] if (o.get("tattoo") or o.get("stored")) and o.get("mod") is not None else char.mod(ab)   # a Spellwrought Tattoo's table gives its own numbers
            spec = SB.spec(sp)
            self._precheck(att, dict(sp, ability=ab), dict(spec, cost="action"), level, targets, point, False)
            if o.get("daily"):
                char.d["resources"][day_key] = 1
            if spend:
                entry["charges_left"] = left - spend
            char.save()
            if o.get("stored"):                                 # a Ring of Spell Storing: that spell is no longer stored in it
                gone = next((x for x in entry.get("stored") or [] if str(x.get("spell")).lower() == sp["name"].lower()), None)
                if gone is not None:
                    entry["stored"].remove(gone)
                    char.save()
            if o.get("tattoo"):                                 # one casting, then the tattoo is gone
                self.chars.remove_item(char.name, entry["name"], 1)
            self._say(f"{att['name']} uses {entry['name']}" + (f" ({spend} charge{'s' if spend > 1 else ''}, {left - spend} left)" if spend else
                                                               " (once a day)" if o.get("daily") else ""))
            if spend and left - spend == 0 and re.search(r"last charge, roll a d20\. On a 1", (rules.item(entry["name"]) or {}).get("text") or ""):
                if int(roll_dice("1d20").total) == 1:
                    self.chars.remove_item(char.name, entry["name"], 1)
                    self._say(f"{entry['name']} crumbles into ashes")
            return self._cast_on(att, sp, None, slot_level=level, caster_level=char.total_level, mod=cast_mod, attack_bonus=atk, dc=dc,
                                 adv=adv, dtype=dtype, targets=targets, point=point, paid=True, mm={"cost_override": "action"})

    # ---- potions and gear
    def use_item(self, cid: int, item: str, target_id: Optional[int] = None) -> str:
        """Use an Object: drink a potion (or pour it into a creature within 5 ft), spread caltrops at the feet."""
        with self.lock:
            self._busy()
            c = self._find(cid)
            char = self._sheet(c)
            if c.get("form"):
                raise ServiceError(f"{c['name']} can't use that in {c['form']['name'].lower()} form.")
            entry = char.find_item(item) if char else next((e for e in c.get("items") or [] if e["name"].lower() == str(item).lower()), None)
            if not entry:
                raise ServiceError(f"{c['name']} doesn't have '{item}'.")
            name = entry["name"]
            low = name.lower()
            tgt = self._find(target_id) if target_id is not None else c
            if tgt is not c and c.get("pos") and tgt.get("pos") and self._dist(c, tgt) > 5:
                raise ServiceError(f"{tgt['name']} is too far away to give the potion to.")
            if low in SPREAD:
                self._pay(c, self._subd_use_cost(c), f"Use {name}")
                line = self._spread(c, name, SPREAD[low])
                self._use_up(c, char, name)
                self._commit(line)
                return line
            if low.startswith("spell scroll") or scroll_spell(name):
                raise ServiceError("Read a scroll from the action bar's scroll entry.")
            data = rules.item(name)
            if not (data and data.get("type") == "P") and low not in POTIONS:
                raise ServiceError(f"{name} can't be used in a fight.")
            self._pay(c, self._subd_use_cost(c), f"Use {name}")
            line = self._drink(c, tgt, name, data)
            self._use_up(c, char, name)
            self._commit(line)
            return line

    def _use_up(self, c: dict, char, name: str):
        if char:
            self.chars.remove_item(char.name, name, 1)
        else:
            self._uncarry(c, name, 1)

    def _drink(self, c: dict, tgt: dict, name: str, data: Optional[dict]) -> str:
        who = tgt["name"]
        lead = f"{c['name']} drinks {name}" if tgt is c else f"{c['name']} gives {name} to {who}"
        low = name.lower()
        m = re.search(r"regain (\d+d\d+(?: ?\+ ?\d+)?) hit points", (data or {}).get("text") or "")
        if m:
            if self._dead(tgt):
                return lead + f": {who} is dead - nothing happens"
            n = roll_dice(m.group(1).replace(" ", "")).total
            self._heal(tgt, n)
            return lead + f": +{n} HP ({self._hp_of(tgt)}/{tgt['max_hp'] if tgt['kind'] != 'pc' else self._sheet(tgt).max_hp})"
        cure = CURES.get(low)
        if cure:                                              # Elixir of Health, Potion of Vitality: conditions washed away
            gone = [x for x in cure if x in self._conds(tgt)]
            for e in list(tgt.get("effects") or []):
                if set(e.get("conditions") or []) & set(cure) or (e.get("mods") or {}).get("dot", {}).get("type") == "poison":
                    self._effect_off(tgt, e, name)
            for x in gone:
                self._cond(tgt, x, False)
            if "exhaustion" in cure and self._exhaustion(tgt):
                sheet = self._sheet(tgt)
                if sheet:
                    sheet.d["exhaustion"] = 0
                    sheet.save()
                else:
                    tgt["exhaustion"] = 0
                gone.append("exhaustion")
            return lead + (f": no longer {', '.join(x.lower() for x in gone)}" if gone else ": nothing to cure")
        p = POTIONS.get(low)
        if not p:
            return lead + " (no battle effect)"
        if p.get("form"):                                     # Potion of Dragon's Majesty: an adult dragon (the scale's kind: random here)
            from ...rules.monsters import bestiary
            beast = bestiary.get(self.rng.choice(p["form"]))
            if beast:
                tgt["form"] = {"monster": beast["id"], "hp": beast["hp"], "max_hp": beast["hp"], "name": beast["name"]}
                return lead + f": {who} becomes an {beast['name'].lower()} ({beast['hp']} HP)"
        rounds = p.get("rounds")
        mods = dict(p.get("mods") or {})
        if "str" in p:
            now = self._ability(tgt, "str")
            want = (p["str"] - 10) // 2
            if want <= now:
                return lead + f": {who} is already that strong - no effect"
            mods.update(ability_set={"str": p["str"]})
        if p.get("choose"):
            t = self.rng.choice(["acid", "cold", "fire", "force", "lightning", "necrotic", "poison", "psychic", "radiant", "thunder"])
            mods["resist"] = [t]
        self._effect_on(tgt, p["name"], list(p.get("conds") or []), None, None, None, rounds, c["name"], mods, None, c["id"])
        if p.get("temp"):
            self._give_temp(tgt, int(p["temp"]))
        if p.get("grant"):
            g = dict(p["grant"])
            if p.get("dtype"):                                # Black acid, Blue lightning, Green poison, Red fire, White cold (the pack entry's note names the colour)
                sheet = self._sheet(c)
                note = str(((sheet.find_item(name) if sheet else None) or {}).get("note") or "").lower()
                kind = next((t for col, t in (("black", "acid"), ("blue", "lightning"), ("green", "poison"), ("white", "cold"), ("red", "fire"))
                             if col in note or t in note), "fire")
                g["parts"] = [[d, kind] for d, _t in g["parts"]]
            entry = {"id": self.b.get("sa_next", 1), "name": g["name"], "spell": name, "cost": g["cost"], "conc_by": None, "rounds": rounds,
                     "def": g, "mod": 0, "dc": g.get("dc", 13), "attack": 0, "level": 0, "target": None, "zone": None,
                     "parts": [list(x) for x in g["parts"]], "uses": g.get("uses")}
            self.b["sa_next"] = entry["id"] + 1
            tgt.setdefault("spell_actions", []).append(entry)
        return lead + f": {p['name']}" + (f" for {rounds // 10} minute{'s' if rounds > 10 else ''}" if rounds and rounds < 600 else
                                          " for an hour" if rounds else "")

    def _spread(self, c: dict, name: str, s: dict) -> str:
        """Caltrops / ball bearings: a small lasting area at the hero's feet (or the tiles in front)."""
        if not c.get("pos"):
            raise ServiceError(f"{c['name']} isn't on the map.")
        x, y = c["pos"]
        tiles = {(x + i, y + j) for i in range(-1, 2) for j in range(-1, 2)} - set(map(tuple, self._footprint(c, x, y)))
        tiles = {t for t in tiles if 0 <= t[0] < self.b["map"]["w"] and 0 <= t[1] < self.b["map"]["h"]}
        free = sorted(t for t in tiles if not any(t in set(map(tuple, self._footprint(o, *o["pos"]))) for o in self.b["combatants"] if o.get("pos")))
        pick = set(free[:1] if s["size"] == 1 else free[:4])
        if not pick:
            raise ServiceError("No free ground beside you to spread it on.")
        z = {"save": s["save"], "half": False, "parts": s.get("parts") or [], "enter": True, "conds": [], "prone": bool(s.get("prone")),
             "fail_mods": s.get("fail_mods")}
        self._add_zone(c, s["name"], pick, z, rounds=None, conc=None, dc=s["dc"])
        return f"{c['name']} spreads {s['name'].lower()} on the ground"

    # ---- scrolls
    def read_scroll(self, cid: int, item: str, targets: Optional[List[int]] = None, point=None, dtype: Optional[str] = None,
                    adv: Optional[str] = None) -> str:
        with self.lock:
            self._busy()
            att = self._find(cid)
            char = self._sheet(att)
            if att.get("form"):
                raise ServiceError(f"{att['name']} can't read in {att['form']['name'].lower()} form.")
            entry = char.find_item(item) if char else None
            if not entry:
                raise ServiceError(f"{att['name']} doesn't have '{item}'.")
            sp = scroll_spell(entry["name"])
            if not sp:
                raise ServiceError(f"{entry['name']} isn't a spell scroll.")
            why = self._scroll_why(char, sp)
            if why:
                raise ServiceError(why + ": the scroll is gibberish to them.")
            infos = SC.casters(char)
            info = next((i for i in infos if i["class"] in (sp.get("classes") or [])), infos[0])
            ab = info["ability"]
            level = sp["level"]
            _l, dc, atk = SCROLL_NUMBERS[min(9, level)]
            spec = SB.spec(sp)
            self._precheck(att, dict(sp, ability=ab), spec, level, targets, point, False)
            self.chars.remove_item(char.name, entry["name"], 1)
            top = max([i.get("max_spell_level") or 0 for i in infos] + [0])
            if level > top and level > 0:
                total = self._d20(char.mod(ab) if char else 0)[0]
                if total < 10 + level:
                    self._pay(att, spec["cost"] if spec["cost"] != "long" else "action", sp["name"])
                    line = f"{att['name']} reads {entry['name']} but fumbles the words ({ab.upper()} check {total} vs DC {10 + level}): the scroll crumbles"
                    self._commit(line)
                    return line
                self._say(f"{att['name']} masters the scroll ({ab.upper()} check {total} vs DC {10 + level})")
            self._say(f"{att['name']} reads {entry['name']} (DC {dc}, +{atk} to hit)")
            return self._cast_on(att, sp, None, slot_level=level, caster_level=char.total_level, mod=char.mod(ab), attack_bonus=atk, dc=dc,
                                 adv=adv, dtype=dtype, targets=targets, point=point, paid=True)
