"""Reading the rules text of an attack, an action or a spell so a battle can play it out: what to roll, against what, and what it does.

Everything here is a pure function over text (the monster stat blocks and spell descriptions use fixed wording), so it is easy to test.
"""
import functools
import math
import re
from typing import List, Optional, Tuple

ABILITIES = {"strength": "str", "dexterity": "dex", "constitution": "con", "intelligence": "int", "wisdom": "wis", "charisma": "cha"}
CONDITIONS = ["Blinded", "Charmed", "Deafened", "Frightened", "Grappled", "Incapacitated", "Paralyzed", "Petrified", "Poisoned",
              "Prone", "Restrained", "Stunned", "Unconscious"]
_COND_RE = {c: re.compile(r"\b(?:(?:be|is|are|becomes?|knocked|falls?|falling)\s+(?:also\s+)?(?:\w+ly\s+)?|(?:has|have|gains?) the\s+"
                          r"|\band\s+(?:is\s+)?)(?:%s)\b" % ("prone" if c == "Prone" else c.lower()), re.I)
            for c in CONDITIONS}       # "be magically charmed", "it has the grappled condition", "is blinded and restrained"
_SAVE_RE = re.compile(r"DC (\d+) (Strength|Dexterity|Constitution|Intelligence|Wisdom|Charisma)"
                      r"(?: or (?:Strength|Dexterity|Constitution|Intelligence|Wisdom|Charisma))? saving throw", re.I)   # the bulette's "Strength or Dexterity"
_TYPES = r"(acid|bludgeoning|cold|fire|force|lightning|necrotic|piercing|poison|psychic|radiant|slashing|thunder)"
_DICE = r"(\d*d\d+(?:\s*[+-]\s*\d+)?)"
_OR_TYPE = r"(?:\s+or\s+(?:acid|bludgeoning|cold|fire|force|lightning|necrotic|piercing|poison|psychic|radiant|slashing|thunder))?"
_DAMAGE_RE = re.compile(r"(?:\d+\s*\(\s*" + _DICE + r"\s*\)|\b" + _DICE + r")\s+" + _TYPES + _OR_TYPE + r"\s+damage", re.I)   # "piercing or slashing": the first
_FLAT_RE = re.compile(r"\b(\d+)\s+(acid|bludgeoning|cold|fire|force|lightning|necrotic|piercing|poison|psychic|radiant|slashing|thunder)\s+damage", re.I)


def split_save(text: str) -> Tuple[str, str, Optional[Tuple[str, int]]]:
    """(text before the saving throw, text from it on, (ability, DC)) - damage in front of it belongs to an attack roll."""
    m = _SAVE_RE.search(text)
    if not m:
        return text, "", None
    return text[:m.start()], text[m.start():], (ABILITIES[m.group(2).lower()], int(m.group(1)))


def damage_parts(text: str, now_only: bool = False) -> List[Tuple[str, str]]:
    """[('2d6+4', 'piercing'), ...] from '7 (2d6 + 4) piercing damage' and '5 fire damage'. now_only: leave out damage that
    comes later, every turn ("takes 21 (6d6) acid damage at the start of each of the cube's turns")."""
    later = re.compile(r"\s*(?:at the (?:start|end) of each|each round|on each of)", re.I)
    out = [(re.sub(r"\s+", "", m.group(1) or m.group(2)), m.group(3).lower()) for m in _DAMAGE_RE.finditer(text)
           if not (now_only and later.match(text, m.end()))]
    if not out:
        out = [(m.group(1), m.group(2).lower()) for m in _FLAT_RE.finditer(text)]
    return out


_ONLY_IF = re.compile(r"\b(?:unless|if|while|when|whether|until|after|before)\b[^.,;]*$", re.I)
_ANY_TARGET = re.compile(r"\bif (?:the target|it) is (?:a |an )?(?:(?:tiny|small|medium|large|huge)(?: or (?:smaller|larger))? )?creature\b", re.I)


def conditions_in(text: str) -> List[str]:
    """The conditions a text inflicts - not those it only mentions in passing ("unless the creature is incapacitated").
    "If the target is a Medium or smaller creature it is grappled" still grapples."""
    return list(_conditions_in(text))


@functools.lru_cache(maxsize=4096)                     # the same spell and attack texts, read for every action menu
def _conditions_in(text: str) -> tuple:
    out = []
    text = re.sub(r"at which point [^.]*\.", "", text)             # an oblex's memory drain: "...until the die becomes a d20, at which point the target becomes unconscious"
    for c, rx in _COND_RE.items():
        if any(not _ONLY_IF.search(_ANY_TARGET.sub("", text[max(0, m.start() - 60):m.start()]))
               and not re.search(r"immun\w* to (?:being )?[\w ,]*$", text[max(0, m.start() - 40):m.start()], re.I)   # "immunity to being charmed and frightened"
               for m in rx.finditer(text)):
            out.append(c)
    return tuple(out)


_LATER = re.compile(r"(?:If|While|When|Whenever|Until|A creature that|Any creature that|At the (?:start|end))\b")


def save_damage(post: str) -> List[Tuple[str, str]]:
    """The damage of a stat block's saving throw: from the save's own sentences, not from what may happen later ("If a
    section is destroyed, ... takes 17 (5d6) cold damage", "A creature that moves through the wall ...")."""
    sents = re.split(r"(?<=\.)\s+", post)
    keep = [x for i, x in enumerate(sents) if i == 0 or not _LATER.match(x)]
    return damage_parts(" ".join(keep), now_only=True)


_SIDE_NOTE = re.compile(r"(?:If|Whenever|A creature that|Any creature that)\b")


def main_sentences(text: str) -> str:
    """A stat block text without the sentences about what may happen later (the first sentence always stays)."""
    sents = re.split(r"(?<=\.)\s+", text)
    return " ".join(x for i, x in enumerate(sents) if i == 0 or not _SIDE_NOTE.match(x))


def text_mods(post: str) -> dict:
    """Effects a stat block words without condition names (a stone golem's Slow)."""
    t = post.lower()
    mods = {}
    if re.search(r"\bspeed (?:is )?halved", t):                # also "has its speed halved" (a fomorian's curse)
        mods["speed_mult"] = .5
    if re.search(r"deals? only half damage with weapon attacks that use strength", t):    # a babau's Weakening Gaze
        mods["enfeebled"] = True
    if re.search(r"speed (?:is reduced to|becomes|reduced to) 0", t):
        mods["speed_set"] = 0
    if re.search(r"can't (?:use|take) reactions", t):
        mods["no_reactions"] = True
    m = re.search(r"speed (?:is )?reduced by (\d+) feet", t)
    if m:                                                      # a gnoll hunter's longbow, Ray of Frost
        mods["speed"] = -int(m.group(1))
    if re.search(r"can't regain hit points|preventing it from regaining hit points", t):   # Chill Touch-like bolts, a nosferatu's Blood Disgorge, a curse of Bhaal
        mods["no_heal"] = True
    if re.search(r"\bhalving its speed\b", t):                 # Wersten Kern's thorned curse
        mods["speed_mult"] = .5
    m = re.search(r"roll an? (\d*d\d+) and subtract the number rolled from (?:each|any) ability check or attack roll", t)
    if m:                                                      # a carrionette's Silver Needle curse, an oblex's memory drain
        mods["attack"] = mods["check"] = "-" + m.group(1)
    if re.search(r"the [\w ]+ has advantage on (?:all|its) attacks? against (?:it|the creature|the target)", t):
        mods["adv_by_source"] = True                           # a vampiric jade statue's curse: only the statue
    dis = re.search(r"(?:has|have|with|imposing) disadvantage on ([^.]*?)(?= until| for \d|\.|$)", t)
    if dis:                                                    # a kender's Taunt, a bard's: "on ability checks, attack rolls, and saving throws"
        if re.search(r"\bability checks?\b(?! that| made| involving| using| to )", dis.group(1)):
            mods["check_dis"] = True                           # a lamia's touch, a thorned curse
        if re.search(r"\battack rolls?\b|\battacks based on\b", dis.group(1)):
            mods["attacks_with"] = "dis"                       # "attacks based on Strength or Dexterity": nearly all weapon attacks
            if re.search(r"\bnext attack roll\b", dis.group(1)):    # Vicious Mockery's wording: only the next roll
                mods["once"] = True
        sd = re.search(r"(?:(strength|dexterity|constitution|intelligence|wisdom|charisma) )?saving throws", dis.group(1))
        if sd:
            mods["save_dis"] = [ABILITIES[sd.group(1)]] if sd.group(1) else "all"
    if re.search(r"attack rolls (?:made )?against (?:it|the target|that creature|the creature) have advantage", t):
        mods["attacks_against"] = "adv"
    return mods


def repeat_save(text: str) -> Optional[str]:
    """When the target may try the saving throw again: 'end' / 'start' of each of its turns."""
    t = text.lower()
    if re.search(r"(?:at the )?end of each of (?:its|their|the target's) turns?", t) or "at the end of each of its turns" in t:
        return "end"
    if re.search(r"start of each of (?:its|their|the target's) turns?", t):
        return "start"
    return None


_BY_FIVE = re.compile(r"[^.]*\bby 5 or more\b,?([^.]*)\.?", re.I)


def fail_by_five(text: str) -> List[str]:
    """Conditions that only come with a save failed by 5 or more ("If the target fails the saving throw by 5 or more, it is
    also paralyzed for the same duration": the mummy's glare; "... poisoned for 5 minutes and unconscious": a homunculus)
    - those of that sentence the rest of the text doesn't give anyway."""
    m = _BY_FIVE.search(text)
    if not m:
        return []
    rest = conditions_in(text[:m.start()] + text[m.end():])
    return [c for c in conditions_in(m.group(1)) if c not in rest]


def until_of(text: str) -> Optional[str]:
    """'stunned until the end of the otyugh's next turn' -> 'caster_end_next'; '... of its next turn' -> 'target_end_next';
    the same with 'start'. None when the text sets no such limit."""
    m = re.search(r"(?:until|before) the (end|start) of (?:the )?([\w' -]{1,40}?)(?:'s)? next turn", text, re.I)
    if not m:
        return None
    who = m.group(2).lower().strip()
    whose = "target" if who in ("its", "their", "target", "the target", "that creature", "his", "her") else "caster"
    return f"{whose}_end_next" if m.group(1).lower() == "end" else f"{whose}_start"


def duration_rounds(text: str) -> Optional[int]:
    """'1 minute' -> 10 rounds. None when the text gives no fixed length."""
    m = re.search(r"(?:for|up to|,)?\s*(\d+)\s+(round|minute|hour)s?", text, re.I)
    if not m:
        return None
    n = int(m.group(1))
    return n * {"round": 1, "minute": 10, "hour": 600}[m.group(2).lower()]


def monster_save(saves: str, ability: str, score_mod: int) -> int:
    """The save bonus from a stat block's 'Dex +5, Con +3' list, else the plain ability modifier."""
    m = re.search(r"\b%s\s*([+-]\d+)" % ability, saves or "", re.I)
    return int(m.group(1)) if m else score_mod


def reduction(dtype: str, resist: str, immune: str, vulnerable: str) -> Tuple[float, str]:
    """(multiplier, note) for a damage type against a creature's resistances / immunities / vulnerabilities."""
    d = dtype.lower()
    has = lambda s: bool(re.search(r"\b%s\b" % d, (s or "").lower()))
    if has(immune):
        return 0, "immune"
    if has(vulnerable):
        return 2, "vulnerable"
    if has(resist):
        return 0.5, "resistant"
    return 1, ""


# ---------------------------------------------------------------------- spells
_UPCAST_RE = re.compile(r"(\d+)d(\d+)\s+(?:\w+\s+)?(?:damage\s+|hit points\s+)?for (?:each|every) (?:spell )?(?:slot )?level above", re.I)
_UPCAST_RE2 = re.compile(r"increases? by (\d+)d(\d+) for (?:each|every) (?:spell )?slot level above", re.I)
_HEAL_RE = re.compile(r"regains?\s+(?:a number of\s+)?hit points", re.I)
_HALF_RE = re.compile(r"half as much|takes? (?:only )?half (?:the (?:initial )?)?damage", re.I)     # "takes half damage" (Arms of Hadar)


def spell_plan(sp: dict, slot_level: Optional[int] = None, caster_level: int = 1, mod: int = 0, dtype: Optional[str] = None) -> dict:
    """What a spell does to its target, read from its description.

    kind: 'attack' (spell attack roll), 'save' (the target saves), 'auto' (no roll: Magic Missile), 'heal' or 'none'.
    parts: [(dice, damage type)], attacks: how many attack rolls (Scorching Ray, Eldritch Blast), plus half / conds / repeat / rounds.
    """
    text, low = sp.get("text", ""), sp.get("text", "").lower()
    level = sp.get("level", 0)
    slot = slot_level or level
    extra = max(0, slot - level)
    parts = damage_parts(text)
    scaling = sp.get("scaling_dice")
    if not parts and sp.get("damage"):                         # 'deals 1d8 + your spellcasting modifier force damage', 'damage of a type you choose'
        m = re.search(r"(?:damage equal to |deals? )(\d+d\d+)(\s*\+\s*your (?:spellcasting )?(?:ability )?modifier)?|(\d+d\d+)(\s*\+\s*your (?:spellcasting )?(?:ability )?modifier)?[^.]{0,60}?damage", text, re.I)
        if m:
            parts = [((m.group(1) or m.group(3)) + (f"{mod:+d}" if (m.group(2) or m.group(4)) else ""), sp["damage"][0])]
    scaling = scaling[0] if isinstance(scaling, list) and scaling else scaling
    if scaling and parts and level == 0:
        steps = [(int(k), v) for k, v in scaling["scaling"].items() if int(k) <= caster_level]
        if steps:
            parts = [(max(steps)[1], (sp.get("damage") or [parts[0][1]])[0])]
    hl = sp.get("higher_level", "") or ""
    up = _UPCAST_RE2.search(hl) or _UPCAST_RE.search(hl)
    if up and parts and extra:
        parts = parts[:1] + [(f"{int(up.group(1)) * extra}d{up.group(2)}", parts[0][1])] + parts[1:]
    if dtype:                                                  # the damage type the caster picked
        parts = [(d, dtype.lower()) for d, _t in parts]
    key = norm(sp.get("name", ""))
    if not parts and key in X.PARTS:
        parts = list(X.PARTS[key])
    plan = {"kind": "none", "parts": parts, "attacks": 1, "half": bool(_HALF_RE.search(text + " " + hl)),
            "conds": [], "repeat": None, "rounds": None, "save": None, "note": ""}
    name = sp.get("name", "")
    if name == "Magic Missile":
        plan.update(kind="auto", parts=[("1d4+1", "force")] * (3 + extra))
        return plan
    if name == "Eldritch Blast":
        plan["attacks"] = 1 + (caster_level >= 5) + (caster_level >= 11) + (caster_level >= 17)
    if name == "Scorching Ray":
        plan["attacks"] = 3 + extra
        if parts:
            plan["parts"] = [parts[0]]
    if key in X.HEALS:
        fixed, per = X.HEALS[key]
        plan.update(kind="heal", parts=[], fixed=int(fixed) if fixed.isdigit() else fixed, heal_extra=None, per_level=per * extra)
        return plan
    if _HEAL_RE.search(text) and not parts:
        dice = re.search(r"(\d+d\d+)", text)
        bonus = re.search(r"(\d+)d(\d+)\s+for each", hl) or _UPCAST_RE2.search(hl)
        plan.update(kind="heal", parts=[(dice.group(1), "healing")] if dice else [],
                    heal_extra=(f"{int(bonus.group(1)) * extra}d{bonus.group(2)}" if bonus and extra else None))
        return plan
    if "spell attack" in low:
        plan["kind"] = "attack"
    elif sp.get("save"):
        plan.update(kind="save", save=ABILITIES.get(sp["save"][0].lower()), conds=conditions_in(text),
                    repeat=repeat_save(text), rounds=duration_rounds(sp.get("duration", "")))
        if key in X.CONDS:
            plan["conds"], plan["repeat"], plan["rounds"] = X.CONDS[key]
    elif parts:
        plan["kind"] = "auto"
    return plan


def type_choices(sp: dict) -> List[str]:
    """The damage types a spell lets its caster pick from (Chromatic Orb...), or [] when the type is fixed."""
    types = [t.lower() for t in sp.get("damage") or []]
    if len(types) < 2:
        return []
    parts = spell_plan(sp, sp.get("level") or None, 1)["parts"]
    if parts and len({t for _d, t in parts}) == 1 and re.search(r"choose|your choice|type of", sp.get("text", ""), re.I):
        return types
    return []


# ---------------------------------------------------------------------- areas of effect
_AREAS = [
    (re.compile(r"(\d+)[- ]foot[- ]radius", re.I), "sphere"),
    (re.compile(r"(\d+)[- ]foot cone", re.I), "cone"),
    (re.compile(r"(\d+)[- ]foot cube", re.I), "cube"),
    (re.compile(r"(\d+)[- ](?:foot|feet)[- ]long,? (\d+)[- ]foot[- ]wide line|(\d+) feet long and (\d+) feet wide", re.I), "line"),
]


def area_of(sp: dict) -> Optional[dict]:
    """{'shape': 'sphere'|'cone'|'cube'|'line', 'size': feet, 'width': feet, 'origin': 'caster'|'target'} for an area spell, else None."""
    rng, text = sp.get("range", "") or "", sp.get("text", "")
    self_range = rng.lower().startswith("self")
    probe = rng + " " + text
    m = re.search(r"Self \((\d+) feet (cone|cube|line|radius|sphere)", rng, re.I)
    if m:
        shape = {"radius": "sphere", "sphere": "sphere", "cone": "cone", "cube": "cube", "line": "line"}[m.group(2).lower()]
        wide = re.search(r"(\d+)[- ]foot[- ]wide", text)
        return {"shape": shape, "size": int(m.group(1)), "width": int(wide.group(1)) if wide else 5, "origin": "caster"}
    found = sorted(((m.start(), shape, m) for rx, shape in _AREAS for m in [rx.search(probe)] if m), key=lambda t: t[0])
    for _pos, shape, m in found[:1]:
        if m:
            if shape == "line":
                size = int(m.group(1) or m.group(3)); width = int(m.group(2) or m.group(4))
            else:
                size, width = int(m.group(1)), 5
            if shape == "sphere" and not re.search(r"each creature|creatures? (?:in|within|of your choice)|in the area|in that area|in a ", text, re.I) and not sp.get("save"):
                return None
            return {"shape": shape, "size": size, "width": width, "origin": "caster" if self_range or shape in ("cone", "line") else "target"}
    return None


def tiles_in_area(area: dict, caster: Tuple[int, int], target: Tuple[int, int], w: int, h: int) -> List[Tuple[int, int]]:
    """Map tiles (5 ft each) an area covers, from the caster's tile and the target's tile (tile centres decide)."""
    cx, cy = caster[0] + .5, caster[1] + .5
    tx, ty = target[0] + .5, target[1] + .5
    dx, dy = tx - cx, ty - cy
    norm = math.hypot(dx, dy)
    ux, uy = (dx / norm, dy / norm) if norm else (1.0, 0.0)
    n = area["size"] / 5
    out = []
    for x in range(w):
        for y in range(h):
            px, py = x + .5, y + .5
            shape = area["shape"]
            if shape == "sphere":
                ox, oy = (cx, cy) if area["origin"] == "caster" else (tx, ty)
                ok = math.hypot(px - ox, py - oy) <= n + 1e-6
            elif shape == "cone":
                vx, vy = px - cx, py - cy
                d = math.hypot(vx, vy)
                ok = 0 < d <= n + 1e-6 and (vx * ux + vy * uy) / d >= math.cos(math.atan(.5)) - 1e-6
            elif shape == "line":
                vx, vy = px - cx, py - cy
                along, side = vx * ux + vy * uy, abs(-vx * uy + vy * ux)
                ok = 0 < along <= n + 1e-6 and side <= max(area["width"] / 10, .5) + 1e-6
            else:                                              # cube: centred on the target, or growing away from the caster
                ox, oy = (tx, ty) if area["origin"] == "target" else (cx + ux * (n / 2 + .5), cy + uy * (n / 2 + .5))
                half = n / 2 + 1e-6
                ok = abs(px - ox) <= half and abs(py - oy) <= half
            if ok and (x, y) != tuple(caster):
                out.append((x, y))
    if area["origin"] == "target" and tuple(target) not in out and tuple(target) != tuple(caster):
        out.append(tuple(target))
    return out


# ---------------------------------------------------------------------- spells that change a creature instead of rolling
from . import spell_effects as X  # noqa: E402
from ...rules import srd as SRD  # noqa: E402


def norm(name: str) -> str:
    """A spell's key in the engine's tables: lower case, by its books' name (the SRD's 'Arcane Hand' is 'bigby's hand',
    app.rules.srd)."""
    return SRD.book_name(re.sub(r"[’`]", "'", name))


def shown(text: str) -> str:
    """Engine text that starts with a spell's books' name, with the name the installed content gives it ('Bigby's Hand:
    fist' -> 'Arcane Hand: fist' when only the SRD is installed)."""
    low = text.lower()
    for book in SRD.SPELLS:
        if low.startswith(book.lower()):
            return SRD.current_name(book) + text[len(book):]
    return text


def vfx_tier(level: int) -> int:
    """How big a spell's show is on the maps (casting circle, summoning circle): 0 cantrip, 1 for slots 1-2, 2 for 3-5, 3 above."""
    return 0 if not level else 1 if level <= 2 else 2 if level <= 5 else 3


def buff_for(name: str) -> Optional[dict]:
    return X.BUFFS.get(norm(name))


def classify(sp: dict) -> str:
    """Where a spell is handled: attack / save / auto / heal (read from its text), buff, pool, cleanse, revive, power_word, summon,
    utility - or 'unclassified' (a spell nobody has gone through; tests/test_battle.py fails on it)."""
    n = norm(sp["name"])
    plan = spell_plan(sp, sp.get("level") or None, 5, 3)
    if n in X.BUFFS:
        return "save" if X.BUFFS[n].get("on_fail") and sp.get("save") else "buff"      # Bane, Compelled Duel: only on a failed save
    if n in X.POOLS:
        return "pool"
    if n in X.POWER_WORDS:
        return "power_word"
    if n in X.REVIVES:
        return "revive"
    if n in X.CLEANSES:
        return "cleanse"
    if n in X.HEALS or plan["kind"] == "heal":
        return "heal"
    if plan["kind"] in ("attack", "auto"):
        return plan["kind"]
    if plan["kind"] == "save" and (plan["parts"] or plan["conds"] or n in X.CONDS):
        return "save"
    if n in X.SPIRITS or n in X.CHOICES or n in X.LADDERS or n == "simulacrum":
        return "summon"
    if n in {norm(x) for x in X.UTILITY}:
        return "utility"
    from . import spellbook as SB                          # a rule of its own, written by hand in spellbook.SPECIAL
    return SB.SPECIAL.get(n, {}).get("kind") or "unclassified"


def rolls_dice(sp: dict) -> bool:
    """A spell with an attack roll or damage dice: the ones the Discord sheet can cast. The rest are only listed there."""
    kind = classify(sp)
    return kind in ("attack", "auto") or (kind == "save" and bool(spell_plan(sp, sp.get("level") or None, 5, 3)["parts"]))


def spirit_hp(formula: str, variant: str, level: int) -> int:
    """Hit points of a summoned spirit from its stat block text: '40 + 10 for each spell level above 4th', or
    '20 (Air only) or 30 (Land and Water only) + 5 for each spell level above 2nd'."""
    base = None
    for m in re.finditer(r"(\d+)\s*\(([^)]*?) only\)", formula):
        if variant and variant.lower() in m.group(2).lower().replace(" and ", ",").replace(" ", ""):
            base = int(m.group(1))
    if base is None:
        m = re.search(r"(\d+)\s*\(([^)]*?) only\)", formula)
        base = int(m.group(1)) if m and variant and variant.lower() in m.group(2).lower() else None
    if base is None:
        nums = re.findall(r"(\d+)(?:\s*\([^)]*\))?", formula)
        base = int(nums[0]) if nums else 10
        # a variant not named in any "(X only)" takes the last, unqualified base ("or 20 (Skeletal only)" -> try each)
        for m in re.finditer(r"(\d+)\s*\(([^)]*?)\)", formula):
            if variant and variant.lower() in m.group(2).lower():
                base = int(m.group(1))
    per = re.search(r"\+\s*(\d+)\s+for each spell level above\s+(\d+)", formula)
    return base + (int(per.group(1)) * max(0, level - int(per.group(2))) if per else 0)
