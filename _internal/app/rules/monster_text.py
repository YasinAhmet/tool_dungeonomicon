"""Stat blocks written for the 2024 rules (the books since the 2024 Player's Handbook), read back into the 2014 wording the battle
engine parses.

The importer drops the 5etools action tags ({@atkr m}, {@actSave dex}, {@actSaveFail}, {@actTrigger}...), so such an entry reads
"m +5, reach 5 ft. Hit: ..." or "dex DC 13, each creature in a 15-foot Cone.  14 (4d6) Fire damage.  Half damage." (the double
spaces are where "Failure:", "Success:", "Response:" were). `modernize(monster)` rewrites those entries in place when the
bestiary loads: "Melee Weapon Attack: +5 to hit, reach 5 ft., one target. Hit: ...", "Each creature in a 15-foot cone must make a
DC 13 Dexterity saving throw. 14 (4d6) Fire damage. A creature takes half as much damage on a successful save.". An entry that
is already in the 2014 wording matches none of the patterns and stays as it is.
"""
import re

_AB = {"str": "Strength", "dex": "Dexterity", "con": "Constitution", "int": "Intelligence", "wis": "Wisdom", "cha": "Charisma"}
_AB_TOK = r"(?:d?(?:str|dex|con|int|wis|cha)|Strength|Dexterity|Constitution|Intelligence|Wisdom|Charisma)(?: [Ss]aving [Tt]hrow)?"
_PHYSICAL = {"bludgeoning", "piercing", "slashing"}

# "m +5, reach 5 ft. Hit:" / "m,r +3, reach 5 ft. or range 20/60 ft. Hit:" / "r +4, range 30/90 ft. Hit:"
_ATK = re.compile(r"^(m,r|m|r) (?:\+(\d+)(?: to hit)?|Bonus equals your spell attack modifier)(?: \(([^)]*)\))?, ((?:[Rr]each|[Rr]ange)[^\n]*?)\s+Hit(?: or Miss)?:")
# "dex DC 13, each creature in a 15-foot Cone.  " (the rest is what a failed save does)
_HEAD = re.compile(r"(?P<ab>" + _AB_TOK + r") DC (?P<dc>\d+|equals ?)(?: \((?P<par>[^)]*)\))?(?P<spec>,\s*[^\n]*?)?\.\s{2}(?=\S)")
_INLINE = re.compile(r"\b(?:is|are) (?:also )?(?:subjected to|targeted once by) the following effect[.:]\s+"
                     r"(?P<ab>" + _AB_TOK + r") DC (?P<dc>\d+)(?: \((?P<par>[^)]*)\))?\.\s+")
_HALF = re.compile(r"^Half damage(?: only)?\.?$", re.I)
_SIZE_IF = re.compile(r"If the target is (?:a |an )?((?:Tiny|Small|Medium|Large|Huge)(?: or (?:smaller|larger))?) creature, it has the (\w+) condition")


def _ability(tok: str) -> str:
    t = re.sub(r" [Ss]aving [Tt]hrow$", "", tok).lower()
    if t in _AB:
        return _AB[t]
    if len(t) == 4 and t[1:] in _AB:                  # "dstr", "dcon": a typo in the book data
        return _AB[t[1:]]
    return t.capitalize()


def _lower_first(s: str) -> str:
    return re.sub(r"^(The|A|An|Each|One) ", lambda m: m.group(1).lower() + " ", s, count=1)


def _spec(spec: str) -> str:
    """The targets of a save in the 2014 wordings the area parser knows."""
    s = spec.strip().rstrip(".")
    s = re.sub(r"(\d+)-foot-long,? (\d+)-foot-wide [Ll]ine", r"\1-foot line that is \2 feet wide", s)
    s = re.sub(r"(\d+)-foot (?:[Ee]manation|[Cc]ube|[Cc]one|[Ll]ine|[Ss]phere|[Cc]ylinder)", lambda m: m.group(0).lower(), s)
    s = re.sub(r"\bin an? (\d+)-foot emanation originating from [\w' -]+", r"within \1 feet of itself", s)
    s = re.sub(r"\bof (?!its\b|the )[\w' -]+?'s? choice\b", "of its choice", s)
    s = re.sub(r"(each creature(?: of [\w' ]+? choice)?(?: that [\w' ]+?)? within \d+ feet)$", r"\1 of itself", s)
    return s[:1].upper() + s[1:]


def _effects(eff: str) -> str:
    """What a save does, from the text after the header: the failure first, then "Half damage" for a success."""
    segs = [x.strip() for x in re.split(r" {2,}", eff.strip()) if x.strip()]
    if not segs:
        return ""
    out, half = [segs[0]], False
    for x in segs[1:]:
        if _HALF.match(x):
            half = True
        else:
            out.append(x)
    out[0] = _SIZE_IF.sub(r"A \1 creature also has the \2 condition", out[0])       # not an "If ..." side note to the engine
    if half:
        out.insert(1, "A creature takes half as much damage on a successful save.")
    return " ".join(out)


_TWO_FAILS = re.compile(r" 1 (The target [^\n]*?) 2 (The target has the Petrified condition instead of[^\n]*)$")


def _saves(text: str) -> str:
    """Saving throws written "ab DC N, targets.  failure.  success." in the 2014 wording (per line: a bulleted list has several)."""
    if not re.search(_AB_TOK + r" DC (?:\d+|equals)", text):
        return text
    out = []
    for line in text.split("\n"):
        two = _TWO_FAILS.search(line)
        if two:                                         # a medusa's gaze: "1 ... Restrained ... 2 ... Petrified instead" (the first and second failure)
            line = line[:two.start()] + " " + two.group(1) + " On a second failed save, " + two.group(2)[:1].lower() + two.group(2)[1:]
            line = re.sub(r"^((?:%s) DC \d+(?:, [^.\n]*?)?)\. " % _AB_TOK, r"\1.  ", line, count=1)
        line = _INLINE.sub(lambda m: "must make a DC %s %s saving throw%s. " % (
            m.group("dc"), _ability(m.group("ab")), f" ({m.group('par')})" if m.group("par") else ""), line)
        m = _HEAD.search(line)
        if m:
            rest = line[m.end():]
            spec = m.group("spec")
            par = f" ({m.group('par')})" if m.group("par") else ""
            head = line[:m.start()]
            who = _spec(spec[1:]) if spec else "The target"
            if m.group("dc").isdigit():
                sent = f"{who} must make a DC {m.group('dc')} {_ability(m.group('ab'))} saving throw{par}."
            else:                                       # "DC equals , each creature": the summoner's save DC (summon_stats fills it in)
                sent = f"{who} must make a {_ability(m.group('ab'))} saving throw against your spell save DC{par}."
            line = (head + (" " if head and not head.endswith((" ", "•")) else "") + sent + " " + _effects(rest)).strip()
        out.append(line)
    return "\n".join(out)


def _attack(text: str) -> str:
    m = _ATK.match(text)
    if not m:
        return text
    kind, bonus, cond, rng = m.group(1), m.group(2), m.group(3), m.group(4).strip()
    rng = re.sub(r"[Rr]each (\d+/\d+ ft)", r"range \1", rng).replace("Reach", "reach").replace("Range", "range")
    rest = text[m.end():]
    rng = re.sub(r",\s*one (?:target|creature)\b.*$", "", rng)
    types = {t.lower() for t in re.findall(r"\b(acid|bludgeoning|cold|fire|force|lightning|necrotic|piercing|poison|psychic|radiant|slashing|thunder) damage",
                                           rest[:300], re.I)}
    spell = bool(types) and not (types & _PHYSICAL)
    label = {"m": "Melee", "r": "Ranged", "m,r": "Melee or Ranged"}[kind] + (" Spell" if spell else " Weapon") + " Attack:"
    roll = f"+{bonus} to hit" if bonus else "your spell attack modifier to hit"
    extra = f" ({cond})" if cond else ""
    return f"{label} {roll}, {rng.rstrip('.')}., one target{extra}. Hit:{rest}"


_REACT = re.compile(r"^(?P<trig>[^\n]*?[a-z)])\.\s{2}(?P<resp>\S.*)$", re.S)
_WHEN = re.compile(r"(?:When|Whenever|Immediately after|In response to|After|As a reaction to)\b")


def _reaction(text: str) -> str:
    """"Trigger.  Response." -> "When trigger, response." with the common responses in their 2014 words."""
    m = _REACT.match(text)
    if not m or _WHEN.match(text):
        return text
    trig, resp = m.group("trig").strip(), m.group("resp").strip()
    melee = bool(re.search(r"\bmelee attack roll\b", trig))
    ac = re.match(r"(.+?) adds (\d+) to (its|his|her|their) AC against that attack(?:, (?:possibly|potentially) causing[^.]*)?\.?(.*)$", resp, re.S)
    if ac:                                              # Parry
        who = _lower_first(ac.group(1))
        pron = {"its": "it", "their": "them"}.get(ac.group(3), ac.group(3))
        wield = " and be wielding a melee weapon" if re.search(r"while holding a weapon", trig) else ""
        return (f"{ac.group(1)} adds {ac.group(2)} to {ac.group(3)} AC against one {'melee ' if melee else ''}attack that would hit {pron}. "
                f"To do so, {who} must see the attacker{wield}.{ac.group(4)}").strip()
    resp = re.sub(r"halves the damage \(round down\) (it|he|she|they) takes? from that attack", r"halves the damage that \1 takes from an attack that hits it",
                  resp)                                # Uncanny Dodge
    return f"When {_lower_first(trig)}, {_lower_first(resp)}"


_VOCAB = re.compile(r"\b(Temporary Hit Points?|Hit Points?|Hit Dice|Advantage|Disadvantage|Bonus Actions?|Reactions?|Opportunity Attacks?|"
                    r"Difficult Terrain|Half Cover|Three-Quarters Cover|Total Cover|Bright Light|Dim Light|Critical Hits?|"
                    r"(?:Fly |Burrow |Swim |Climb )?Speeds?)\b")
_SAVE_WORD = re.compile(r"\b(DC \d+ (?:Strength|Dexterity|Constitution|Intelligence|Wisdom|Charisma)) save\b(?! ?ing)")


def _vocab(text: str) -> str:
    """The 2024 books capitalise the game's terms ("Hit Points", "Advantage", "Bonus Action"); the engine's patterns are lower case."""
    def low(m):
        before = text[:m.start()].rstrip()
        if not before or before[-1] in ".:!?•" or text[max(0, m.start() - 1)] == "\n":
            return m.group(0)                           # the start of a sentence stays
        return m.group(0).lower()
    return _SAVE_WORD.sub(r"\1 saving throw", _VOCAB.sub(low, text))


_EMAN = re.compile(r"\bin an? (\d+)-foot [Ee]manation originating from ([\w' -]+?)(?=[,.;]| (?:is|are|have|has|takes|gains|and|can|when|at)\b|$)")


def _emanation(text: str) -> str:
    """"in a 10-foot Emanation originating from Cthulhu ... starts its turn in the Emanation" -> "within 10 feet of Cthulhu ... within 10 feet of Cthulhu"."""
    m = _EMAN.search(text)
    if not m:
        return text
    where = f"within {m.group(1)} feet of {m.group(2)}"
    return re.sub(r"\bin (?:the|this) [Ee]manation\b", where, text[:m.start()] + where + text[m.end():])


def _text(sec: str, text: str) -> str:
    if not text:
        return text
    if sec in ("actions", "bonus_actions", "legendary", "traits", "spellcasting") and _ATK.match(text):
        text = _attack(text)
    if "DC" in text:
        text = _saves(text)
    if sec == "reactions" and "  " in text:
        text = _reaction(text)
    if "manation" in text:
        text = _emanation(text)
    return _vocab(text)


def modernize(m: dict) -> dict:
    """Rewrite a monster's 2024-style entries in place (and return it)."""
    for sec in ("traits", "actions", "bonus_actions", "reactions", "legendary", "spellcasting"):
        for e in m.get(sec) or []:
            t = e.get("text")
            if t:
                new = _text(sec, t)
                if new != t:
                    e["text"] = new
    return m
