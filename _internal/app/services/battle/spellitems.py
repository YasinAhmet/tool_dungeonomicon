"""Items that work through spells being cast, in a fight: Tasha's wizard spellbooks and sorcerer shards; and a few one-off magic items
whose powers the generic readers of wondrous.py had no pattern for (a Jester's Mask, a Ring of Spell Storing, a Dragon Vessel...).

Wizard books (TCE: Fulminating Treatise, Heart Weaver's Primer, Duplicitous Manuscript, Astromancy Archive, Atlas of Endless
Horizons, Protective Verses) hold 3 charges that come back at dawn (the sheet's long rest). Read from the item's own text
(`tome_powers`); their reactions are asked through wondrous.ITEM_FAMILIES ("item_tome", "item_tome_free"):
    atlas   "when you are hit by an attack, you can use your reaction to expend 1 charge to teleport up to 10 feet ... if your new
            position is out of range of the attack, it misses you" (offered when such a space exists)
    ward    "when you cast an abjuration spell, you can expend 1 charge to grant a creature within 30 feet 2d10 temporary hit points"
    strike  "when one creature you can see takes damage from an evocation spell you cast, you can use your reaction and expend
            1 charge to deal an extra 2d6 force damage and knock it prone if it is Large or smaller" (offered after the spell's
            damage, `_spell_after_damage`)
    curse   "when you cast an enchantment spell, you can expend 1 charge to impose disadvantage on the first saving throw one
            target makes against the spell" / the illusion book's reaction version for any target (offered before the save)
    d4      "when a creature you can see within 30 feet makes an attack roll, an ability check or a saving throw, you can use
            your reaction to expend 1 charge and force it to roll a d4 and apply it as a bonus or penalty" (Astromancy Archive:
            offered when that roll would be flipped by it)
Essence shards (TCE: Elemental / Outer / Shadowfell / Far Realm): "when you use a Metamagic option on a spell while holding or
wearing the shard" the shard's property happens, read from its text (`shard_power`): Fire (a target burns for 2d10 at the
start of its next turn), Water (a 10-ft wave: 2d6 cold, DC Strength or pushed and prone), Earth (resistance to a damage type
until your next turn: the type the foes deal most), Chaotic (disadvantage on attacks and checks), Evil (+3d6 necrotic), Good
(3d6 temporary hit points for you or the hurt ally), Lawful (an ally's or your own charmed, blinded, deafened, frightened,
poisoned or stunned ends), Shadowfell (disadvantage on checks and saves of the target's best ability), Far Realm (a tentacle:
DC Charisma or 3d6 psychic and frightened), Air (60 ft more movement this turn without opportunity attacks: the flight has no destination
to ask for), Astral (a teleport to the space in reach farthest from the foes).
Also here:
    a Jester's Mask: Marvelous Escape (a reaction: the hit does nothing, blink up to 30 ft away) and Topsy-Turvy (a natural 1 counts
        as a 20, once a day; resolve._d20_roll), both once until the next dawn;
    a Ring of Spell Storing: the spells inside it (pack entry `stored`, or its note "Fireball 3, Hold Person") are on the bar like a
        wand's, cast with the original caster's numbers and then gone (items.use_wand);
    a Dragon Vessel (a potion of the day, put in the pack), a Veteran's Cane (becomes its longsword), a Talisman of Pure Good or
        Ultimate Evil (the fissure) - `more_activations` read by wondrous.activations, played by `_wonder_craft`;
    a Nature's Mantle (Hide as a bonus action in dim light or haze), a Butcher's Bib (slashing weapons crit on 19-20), a Battle Standard
        of Infernal Power (allies' weapon attacks within 300 ft count as magical), a Dwarven Plate (a reaction cuts forced movement by 10 ft),
        a Planecaller's Codex (a charge: the one creature a conjuration summons attacks with advantage), a Potion of Maximum Power
        (the first damage spell's dice are maximised), a Scroll of Protection (wondrous.BUFFS: that kind of creature can't hit the reader);
    FTD dragon items whose family the item doesn't say (the pack entry's note names it: "Chromatic", "Gem", "Metallic", or a dragon's
        colour): a Dragon-Touched Focus (Chromatic +1d6 on a damage roll, Gem blinks 15 ft after a slot spell, Metallic gives a creature
        advantage on a save) and a Wakened or Ascendant Scaled Ornament (no damage of the breath's type, healed instead, once a day).
"""
import re
from collections import Counter
from typing import List, Optional

from ...rules.data import rules
from ...rules.dice import roll_dice
from ..common import ServiceError
from . import geometry as G
from . import sight as V
from .wondrous import TYPES, _clean

SIZE_SPAN = {"tiny": 1, "small": 1, "medium": 1, "large": 2, "huge": 3, "gargantuan": 4}
SHARD_CONDS = ["Charmed", "Blinded", "Deafened", "Frightened", "Poisoned", "Stunned"]
ABILITIES = ["str", "dex", "con", "int", "wis", "cha"]


def tome_powers(item: Optional[dict]) -> List[dict]:
    """The spell-linked powers of a wizard's spellbook item: [{'key', 'school', 'cost' ('reaction' | 'free'), ...}]."""
    if not item or not item.get("charges"):
        return []
    text = _clean(item.get("text"))
    out = []
    m = re.search(r"takes damage from an? (\w+) spell you cast, you can use your reaction and expend 1 charge to deal an extra (\d+d\d+) (\w+) "
                  r"damage to the creature and knock the creature prone if it is (\w+) or smaller", text, re.I)
    if m:
        out.append({"key": "strike", "school": m.group(1).lower(), "dice": m.group(2), "type": m.group(3).lower(), "size": m.group(4).lower(),
                    "cost": "reaction"})
    m = re.search(r"When you cast an? (\w+) spell, you can expend 1 charge to impose disadvantage on the first saving throw one target makes "
                  r"against the spell", text, re.I)
    if m:
        out.append({"key": "curse", "school": m.group(1).lower(), "cost": "free", "first": True})
    m = re.search(r"makes a saving throw against an? (\w+) spell you cast, you can use your reaction and expend 1 charge to impose "
                  r"disadvantage on the roll", text, re.I)
    if m:
        out.append({"key": "curse", "school": m.group(1).lower(), "cost": "reaction", "first": False})
    m = re.search(r"When you are hit by an attack, you can use your reaction to expend 1 charge to teleport up to (\d+) feet to an unoccupied space "
                  r"you can see\. If your new position is out of range of the attack, it misses you", text, re.I)
    if m:
        out.append({"key": "atlas", "ft": int(m.group(1)), "cost": "reaction"})
    m = re.search(r"When you cast an? (\w+) spell, you can expend 1 charge to grant a creature you can see within (\d+) feet of you (\d+d\d+) temporary "
                  r"hit points", text, re.I)
    if m:
        out.append({"key": "ward", "school": m.group(1).lower(), "ft": int(m.group(2)), "dice": m.group(3), "cost": "free"})
    m = re.search(r"When you cast an? (\w+) spell that summons or creates one creature, you can expend 1 charge to grant that creature advantage on "
                  r"attack rolls for 1 minute", text, re.I)
    if m:
        out.append({"key": "summon_adv", "school": m.group(1).lower(), "cost": "free"})
    if re.search(r"you can use your reaction to expend 1 charge and force the creature to roll a d4 and apply the number rolled as a bonus or "
                 r"penalty", text, re.I):
        out.append({"key": "d4", "cost": "reaction", "range": 30})
    return out


def shard_power(item: Optional[dict]) -> Optional[dict]:
    """What an essence shard does when its wearer uses Metamagic: {'key', ...numbers} or None."""
    if not item or not re.search(r"Metamagic option on a spell while you are holding or wearing the shard", item.get("text") or ""):
        return None
    t = _clean(item.get("text"))
    m = re.search(r"catches fire\. The burning target takes (\d+d\d+) fire damage at the start of its next turn", t)
    if m:
        return {"key": "fire", "dice": m.group(1)}
    m = re.search(r"(\d+)-foot radius\. Each creature of your choice that you can see in that area takes (\d+d\d+) cold damage and must succeed "
                  r"on a Strength saving throw against your spell save DC or be pushed (\d+) feet away from you and fall prone", t)
    if m:
        return {"key": "water", "ft": int(m.group(1)), "dice": m.group(2), "push": int(m.group(3))}
    if re.search(r"gain resistance to a damage type of your choice until the start of your next turn", t):
        return {"key": "earth"}
    m = re.search(r"immediately fly up to (\d+) feet without provoking opportunity attacks", t)
    if m:
        return {"key": "air", "ft": int(m.group(1))}
    m = re.search(r"immediately after casting the spell you can teleport to an unoccupied space you can see within (\d+) feet", t)
    if m:
        return {"key": "astral", "ft": int(m.group(1))}
    if re.search(r"disadvantage on attack rolls and ability checks made before the start of your next turn", t):
        return {"key": "chaotic"}
    m = re.search(r"takes an extra (\d+d\d+) (\w+) damage", t)
    if m:
        return {"key": "evil", "dice": m.group(1), "type": m.group(2).lower()}
    m = re.search(r"gains (\d+d\d+) temporary hit points", t)
    if m:
        return {"key": "good", "dice": m.group(1)}
    if re.search(r"end one of the following conditions affecting yourself", t):
        return {"key": "lawful"}
    if re.search(r"curse one creature targeted by the spell; choose one ability score", t):
        return {"key": "shadow"}
    m = re.search(r"strike one creature you can see within (\d+) feet of you\. The creature must succeed on a Charisma saving throw against your "
                  r"spell save DC or take (\d+d\d+) psychic damage and become frightened of you until the start of your next turn", t)
    if m:
        return {"key": "farrealm", "ft": int(m.group(1)), "dice": m.group(2)}
    return None


# ---------------------------------------------------------------------- more activations (read by wondrous.activations)
FILL_RE = re.compile(r"fill the vessel with one of the following \(your choice\): ([^.]+)\.", re.I)
CANE_RE = re.compile(r"use a bonus action to speak the command word, it transforms into an ordinary ([\w' -]+?) and ceases to be magical", re.I)
FISSURE_RE = re.compile(r"If the target is of (evil|good) alignment, a flaming fissure opens under it\. The target must succeed on a DC (\d+) "
                        r"Dexterity saving throw or fall into the fissure and be destroyed", re.I)


def more_activations(body: str, cost: str, limit, key: str, name: str) -> Optional[dict]:
    """One bar entry for the wondrous items wondrous.activations has no pattern for, or None: a Dragon Vessel's potion ('fill' a
    flask of one of the potions it lists), a Veteran's Cane turning into its longsword, a Talisman's fissure under an evil
    (Pure Good) or good (Ultimate Evil) creature."""
    low = _clean(body)
    m = FILL_RE.search(low)
    if m:
        opts = []
        for part in re.split(r",\s*(?:or\s+)?|\s+or\s+", m.group(1)):
            nm = re.sub(r"^an?\s+", "", part.strip())
            data = rules.item(nm)
            if data and data.get("type") == "P":
                opts.append({"value": data["name"], "label": data["name"]})
        if opts:
            return {"key": key, "name": "Fill the vessel", "cost": cost, "kind": "vessel", "limit": limit,
                    "options": opts, "target": {"type": "self"},
                    "tip": "Fill the empty vessel with one of its potions (then drink it with Use an Object). It loses its magic after 24 hours."}
    m = CANE_RE.search(low)
    if m:
        return {"key": key, "name": "Transform", "cost": cost, "kind": "transform", "into": m.group(1).strip().title(), "limit": None,
                "target": {"type": "self"}, "tip": f"The cane becomes an ordinary {m.group(1)} and stops being magical."}
    m = FISSURE_RE.search(low)
    if m:
        return {"key": key, "name": "Flaming fissure", "cost": cost, "kind": "talisman", "align": m.group(1).lower(), "dc": int(m.group(2)),
                "limit": limit if isinstance(limit, tuple) else ("charges", 1), "range": 120,
                "target": {"type": "creature", "count": 1, "enemies": True},
                "tip": f"A creature of {m.group(1)} alignment within 120 ft: DC {m.group(2)} Dexterity save or it falls in and is destroyed. 1 charge."}
    return None


STORED_RE = re.compile(r"^\s*(?P<name>[A-Za-z'/ -]+?)\s*(?:[(\[]?\s*(?:level\s*)?(?P<lv>\d)(?:st|nd|rd|th)?\s*[)\]]?)?\s*$", re.I)


def stored_spells(entry: dict) -> List[dict]:
    """The spells inside a Ring of Spell Storing or a spell gem, in `item_spells`' shape (the ring's spells use the original caster's numbers: the stored
    spell's own 'dc', 'atk' and 'mod', else DC 15, +7, +4): from the pack entry's `stored` list [{'spell', 'level', 'dc', 'atk', 'mod'}] or,
    failing that, its note ("Fireball 3, Shield 1": a spell and the slot level it was cast with)."""
    items = list(entry.get("stored") or [])
    if "stored" not in entry:                                    # first read: the note becomes the list (so a cast spell stays gone)
        for part in re.split(r"[,;\n]+", str(entry.get("note") or "")):
            m = STORED_RE.match(part)
            if m and rules.spell(m.group("name").strip()):
                items.append({"spell": rules.spell(m.group("name").strip())["name"], "level": int(m.group("lv")) if m.group("lv") else None})
        entry["stored"] = [dict(x) for x in items]
    out = []
    gem = str(entry.get("name") or "").startswith("Spell Gem (")      # an Out of the Abyss spell gem: its own top level, DC and attack bonus
    text = (rules.item(entry.get("name") or "") or {}).get("text") or ""
    top = int((re.search(r"store up to (\d)(?:st|nd|rd|th) level", text) or [0, 1])[1]) if gem else 5
    g_dc = re.search(r"save DC of (\d+) and an attack bonus of \+(\d+)", text) if gem else None
    for x in items:
        sp = rules.spell(str(x.get("spell")))
        if not sp or sp["level"] > top or (sp["level"] < 1 and not gem):
            continue
        dc = int(x.get("dc") or (g_dc.group(1) if g_dc else 15))
        atk = int(x.get("atk") or (g_dc.group(2) if g_dc else 7))
        out.append({"spell": sp, "cost": 0, "level": max(sp["level"], min(top, int(x.get("level") or sp["level"]))), "more": False,
                    "dc": dc, "atk": atk, "mod": int(x.get("mod") or (dc - 10 if gem else 4)), "daily": False, "at_will": False, "stored": True})
    return out


class SpellItemsMixin:
    # ------------------------------------------------------------------ the books
    def _tome_items(self, c: Optional[dict]) -> list:
        """[(pack entry, item, power)] of the hero's worn or held spellbooks that still have a charge."""
        char = self._sheet(c) if c and not c.get("form") else None
        out = []
        for e, d in (char._active_items() if char else []):
            if self._charges_left(e) <= 0:
                continue
            out += [(e, d, p) for p in tome_powers(d)]
        return out

    @staticmethod
    def _offer(out: list, reactor_id: int, cost: str, options: list, text: str):
        """One question per reactor and cost in a window (the answer clears the reactor's others): join the one already asked."""
        same = next((q for q in out if q["reactor"] == reactor_id and q.get("cost") == cost and not q.get("window")), None)
        if same is not None:
            same["options"] = list(same["options"]) + options
        else:
            out.append({"reactor": reactor_id, "cost": cost, "options": options, "text": text})

    def _tome_eligible(self, out: list, window: str, R: dict, att: Optional[dict], tgt: Optional[dict], ctx: dict):
        """The books' offers at a window of a resolution (wondrous._wonder_eligible calls this first)."""
        cur = R.get("cur") or {}
        if window == "hit" and tgt and att and self._jester(tgt) and self._may_react(tgt):
            self._offer(out, tgt["id"], "reaction", [{"key": "item_jester:escape", "label": "Marvelous Escape: no damage, blink 30 ft (once a day)",
                                                      "detail": ""}], f"{att['name']} hits {tgt['name']} ({cur.get('total')} vs AC {cur.get('ac')}). Marvelous Escape?")
        if window == "hit" and tgt and att and cur.get("hit") is not False:             # an Atlas of Endless Horizons: step out of the attack's range
            for e, d, p in self._tome_items(tgt):
                if p["key"] == "atlas" and self._atlas_tile(tgt, att, R.get("atk") or {}, p["ft"]) is not None:
                    self._offer(out, tgt["id"], "reaction", [{"key": f"item_tome:{d['name']}|atlas", "label": f"{d['name']}: teleport {p['ft']} ft, "
                                                                f"out of the attack's range (1 charge)", "detail": ""}],
                                f"{att['name']} hits {tgt['name']} ({cur.get('total')} vs AC {cur.get('ac')}). Use the {d['name']}?")
        if window == "cast" and att and R.get("spell"):                                  # Protective Verses: temporary hit points for an abjuration
            sp = rules.spell(R.get("label") or "")
            for e, d, p in self._tome_items(att):
                if p["key"] == "ward" and sp is not None and str(sp.get("school") or "").lower() == p["school"]:
                    self._offer(out, att["id"], "free", [{"key": f"item_tome_free:{d['name']}|ward", "label": f"{d['name']}: {p['dice']} temporary hit points "
                                                          f"for an ally (1 charge)", "detail": ""}], f"{att['name']} casts {R['label']}. {d['name']}: {p['dice']} temporary HP?")
        if window == "damage" and tgt:                                                   # a Scaled Ornament: its dragon's breath type does nothing
            orn = self._ornament(tgt)
            if orn is not None and orn[1] in {t for n, t in cur.get("dmg") or [] if n}:
                self._offer(out, tgt["id"], "reaction", [{"key": "item_ornament:ward", "label": f"{orn[0]['name']}: no {orn[1]} damage, heal that much "
                                                          f"(once a day)", "detail": ""}], f"{tgt['name']} is about to take {orn[1]} damage. Use the ornament?")
        if window == "before_save" and tgt and tgt.get("pos"):                          # a Metallic Dragon-Touched Focus: advantage on a save
            for o in self.b["combatants"]:
                if o.get("pos") and not self._hostile(o, tgt) and self._dist(o, tgt) <= 30 and self._sees(o, tgt) and self._may_react(o)                         and self._focus(o, "metallic") is not None:
                    self._offer(out, o["id"], "reaction", [{"key": "item_focus:advantage", "label": f"Dragon-Touched Focus: advantage on {tgt['name']}'s save",
                                                            "detail": ""}], f"{tgt['name']} must save against {R.get('label')}. Give advantage with the focus?")
        if window == "before_save" and tgt and R.get("spell"):
            caster = self._find_or_none(R.get("actor"))
            sp = rules.spell(R.get("label") or "")
            if caster is None or sp is None or not self._hostile(caster, tgt):
                return
            for e, d, p in self._tome_items(caster):
                if p["key"] != "curse" or p["school"] != str(sp.get("school") or "").lower() or (p["first"] and R.get("tome_curse")):
                    continue
                if p["first"]:
                    R["tome_curse"] = True                          # "the first saving throw one target makes": asked once a cast
                fam = "item_tome" if p["cost"] == "reaction" else "item_tome_free"
                self._offer(out, caster["id"], p["cost"], [{"key": f"{fam}:{d['name']}|curse", "label": f"{d['name']}: disadvantage on {tgt['name']}'s save",
                                                            "detail": ""}], f"{tgt['name']} must save against {R['label']}. {d['name']}: "
                                                                          f"impose disadvantage (1 charge, {self._charges_left(e)} left)?")
        if window in ("hit", "missed", "save_failed", "save_ok") and tgt and not cur.get("auto"):
            roller = att if window in ("hit", "missed") else tgt
            total, kept = cur.get("total"), cur.get("kept")
            if roller is None or total is None:
                return
            target_number = cur.get("ac") if window in ("hit", "missed") else (R.get("sv") or {}).get("dc")
            if target_number is None:
                return
            gap = int(total) - int(target_number)
            for o in self.b["combatants"]:
                if o is roller or not o.get("pos") or not roller.get("pos") or self._dist(o, roller) > 30 or not self._sees(o, roller):
                    continue
                for e, d, p in self._tome_items(o):
                    if p["key"] != "d4":
                        continue
                    friendly = not self._hostile(o, roller)
                    if window in ("missed", "save_failed") and friendly and gap < 0 and -gap <= 4 and kept not in (1,):
                        label = f"{d['name']}: +1d4 to {roller['name']}'s roll"
                    elif window in ("hit", "save_ok") and not friendly and gap >= 0 and gap <= 3 and kept not in (20,):
                        label = f"{d['name']}: -1d4 to {roller['name']}'s roll"
                    else:
                        continue
                    self._offer(out, o["id"], "reaction", [{"key": f"item_tome:{d['name']}|d4", "label": label, "detail": ""}],
                                f"{roller['name']} rolled {total} against {target_number}. {label.split(': ')[0]}: use a charge?")

    def _spell_after_damage(self, R: dict, att: dict, tgt: dict):
        """A spell of the caster's has just damaged `tgt`: a Fulminating Treatise's reaction (offered as a child of this strike)."""
        sp = rules.spell(R.get("label") or "")
        if sp is None or not self._alive(tgt) or att is tgt or not self._sees(att, tgt):
            return
        for e, d, p in self._tome_items(att):
            if p["key"] != "strike" or p["school"] != str(sp.get("school") or "").lower() or not self._may_react(att):
                continue
            item = {"reactor": att["id"], "cost": "reaction", "window": "after_damage",
                    "text": f"{R['label']} hurt {tgt['name']}. {d['name']}: {p['dice']} {p['type']} and prone (1 charge)?",
                    "options": [{"key": f"item_tome:{d['name']}|strike|{tgt['id']}", "label": f"{d['name']}: +{p['dice']} {p['type']} on {tgt['name']}", "detail": ""}]}
            R.setdefault("follow", []).append(self._new_r("offer", tgt, "reaction", item=item, attacker=tgt["id"]))

    def _tome_react(self, window: str, R: dict, reactor: dict, fam: str, arg: str, ctx: dict):
        """What a book's reaction does (arg 'item|power[|creature id]'); a Jester's Mask's Marvelous Escape."""
        if fam == "item_jester":
            self._jester_escape(R, reactor)
            return
        if fam == "item_ornament":                              # no damage of the breath type; the hit points come back instead
            orn = self._ornament(reactor)
            if orn is None:
                return
            cur = R.setdefault("cur", {})
            took = sum(int(n) for n, t in cur.get("dmg") or [] if t == orn[1])
            cur["dmg"] = [[0 if t == orn[1] else n, t] for n, t in cur.get("dmg") or []]
            char = self._sheet(reactor)
            char.d["resources"][f"item:{orn[0]['name']}:ornament"] = 1
            char.save()
            self._heal(reactor, took)
            self._line(R, f"{reactor['name']}'s {orn[0]['name']} drinks the {orn[1]}: no damage, +{took} HP", orn[0]["name"])
            return
        if fam == "item_focus":                                 # a Metallic Dragon-Touched Focus: the creature saves with advantage
            R.setdefault("cur", {})["presave_adv"] = "adv"
            self._line(R, f"{reactor['name']}'s Dragon-Touched Focus gives the creature advantage on its save", "Dragon-Touched Focus")
            return
        name, _s, rest = arg.partition("|")
        power, _s, extra = rest.partition("|")
        char = self._sheet(reactor)
        e = char.find_item(name) if char else None
        d = rules.item(name) if e else None
        p = next((x for x in tome_powers(d) if x["key"] == power), None)
        if not p or self._charges_left(e) <= 0:
            return
        e["charges_left"] = self._charges_left(e) - 1
        char.save()
        left = f"{e['charges_left']} charges left"
        cur = R.setdefault("cur", {})
        if power == "curse":
            cur["presave_dis"] = True
            self._line(R, f"{reactor['name']} spends a charge of {d['name']}: disadvantage on the save ({left})", d["name"])
        elif power == "strike":
            victim = self._find_or_none(int(extra)) if extra.isdigit() else self._find_or_none(ctx.get("attacker"))
            if victim is None:
                return
            line = self._deal_rolled(victim, [[int(roll_dice(p["dice"]).total), p["type"]]], by=reactor, label=d["name"], spell=True)
            if max(1, int(victim.get("span") or 1)) <= SIZE_SPAN.get(p["size"], 2) and "Prone" not in self._conds(victim):
                self._cond(victim, "Prone", True)
                line += f"; {victim['name']} is knocked prone"
            self._line(R, f"{reactor['name']} spends a charge of {d['name']} ({left}): {line}", d["name"])
        elif power == "atlas":
            att = self._find_or_none(ctx.get("attacker"))
            tile = self._atlas_tile(reactor, att, R.get("atk") or {}, p["ft"]) if att is not None else None
            if tile is not None:
                self._vfx("blink", id=reactor["id"], at=reactor.get("pos"), to=tile)
                reactor["pos"] = tile
                cur.update(total=int(cur.get("ac") or 10) - 1, kept=min(int(cur.get("kept") or 2), 19), crit=False)
            self._line(R, f"{reactor['name']} spends a charge of {d['name']} and steps out of range: the attack misses ({left})", d["name"])
        elif power == "ward":
            pals = [o for o in self.b["combatants"] if o is reactor or (self._alive(o) and not self._hostile(reactor, o) and o.get("pos") and reactor.get("pos")
                                                                        and self._dist(reactor, o) <= p["ft"] and self._sees(reactor, o))]
            pals.sort(key=lambda o: self._hp_of(o) / max(1, o.get("max_hp") or (self._sheet(o).max_hp if self._sheet(o) else 1)))
            n = int(roll_dice(p["dice"]).total)
            self._give_temp(pals[0], n)
            self._line(R, f"{reactor['name']} spends a charge of {d['name']}: {pals[0]['name']} gains {n} temporary hit points ({left})", d["name"])
        elif power == "d4":
            n = int(roll_dice("1d4").total)
            roller = self._find_or_none(ctx.get("attacker") if window in ("hit", "missed") else ctx.get("target"))
            friendly = roller is not None and not self._hostile(reactor, roller)
            cur["total"] = int(cur.get("total") or 0) + (n if friendly else -n)
            if window in ("save_failed", "save_ok"):
                cur["ok"] = cur["total"] >= int((R.get("sv") or {}).get("dc") or 0)
            self._line(R, f"{reactor['name']} spends a charge of {d['name']}: {'+' if friendly else '-'}{n} to {roller['name'] if roller else 'the'} roll "
                          f"({cur['total']}; {left})", d["name"])

    # ------------------------------------------------------------------ the shards
    def _shard_effects(self, R: dict, att: dict, sp: dict):
        """A spell cast with Metamagic by a hero with an essence shard: the shard's property (appended as strikes after the spell's own)."""
        char = self._sheet(att) if not att.get("form") else None
        if not char:
            return
        if sp["level"] > 0 and self._focus(att, "gem") is not None and att.get("pos"):      # a Gem Dragon-Touched Focus: a 15-ft blink after a slot spell
            spot = self._far_tile(att, 15)
            if spot:
                self._vfx("blink", id=att["id"], at=att.get("pos"), to=spot)
                att["pos"] = spot
                self._line(R, f"{att['name']}'s Dragon-Touched Focus: teleports away (gem)", "Dragon-Touched Focus")
        if not R.get("mm"):
            return
        ids = list(dict.fromkeys(R.get("targets") or []))
        foes = [o for o in (self._find_or_none(i) for i in ids) if o is not None and self._alive(o) and self._hostile(att, o)]
        for _e, d in char._active_items():
            p = shard_power(d)
            if not p:
                continue
            k, dc = p["key"], int(R.get("dc") or self._spell_dc(att))
            foe = foes[0] if foes else None
            if k == "fire" and foe is not None:
                self._dot_on(foe, d["name"], {"dice": p["dice"], "type": "fire", "when": "start", "times": 1}, None, None, 2, att["name"], None, att["id"])
                self._line(R, f"{d['name']}: {foe['name']} catches fire ({p['dice']} fire at the start of its next turn)", d["name"])
            elif k == "water":
                near = [o for o in self.b["combatants"] if o is not att and self._alive(o) and self._hostile(att, o) and o.get("pos") and att.get("pos")
                        and self._dist(att, o) <= p["ft"] and self._sees(att, o)]
                if near:
                    self._stack().append(self._strike(att, f"{d['name']} (wave)", [o["id"] for o in near], mode="save", spell=True, magical=True,
                                                      sv={"ab": "str", "dc": dc, "half": False, "full": True, "prone": True, "push": p["push"]},
                                                      parts=[[p["dice"], "cold"]]))
            elif k == "air" and att.get("turn") is not None:       # the flight has no destination to ask for: that much more movement, no opportunity attacks
                att["turn"]["move"] = int(att["turn"].get("move", 0)) + p["ft"]
                att["turn"]["disengaged"] = True
                self._line(R, f"{d['name']}: {att['name']} may fly {p['ft']} ft more without provoking opportunity attacks", d["name"])
            elif k == "astral":                                     # a teleport with no destination given: the safest space in reach
                spot = self._far_tile(att, p["ft"])
                if spot:
                    self._vfx("blink", id=att["id"], at=att.get("pos"), to=spot)
                    att["pos"] = spot
                    self._line(R, f"{d['name']}: {att['name']} teleports away", d["name"])
            elif k == "earth":
                seen = Counter()
                for o in self.b["combatants"]:
                    if self._hostile(att, o) and self._alive(o):
                        txt = " ".join(str(a.get("text") or "") for a in (self._monster(o) or {}).get("actions") or [])
                        seen.update(t for t in re.findall(r"(\w+) damage", txt.lower()) if t in TYPES)
                t = seen.most_common(1)[0][0] if seen else "slashing"
                self._effect_on(att, d["name"], [], None, None, None, None, att["name"], {"resist": [t]}, None, att["id"], until={"start": att["id"]})
                self._line(R, f"{d['name']}: {att['name']} resists {t} until the start of its next turn", d["name"])
            elif k == "chaotic" and foe is not None:
                self._effect_on(foe, d["name"], [], None, None, None, None, att["name"], {"attacks_with": "dis", "check_dis": list(ABILITIES)},
                                None, att["id"], until=self._until("caster_start", att, foe))
                self._line(R, f"{d['name']}: {foe['name']} has disadvantage on attacks and checks until {att['name']}'s next turn", d["name"])
            elif k == "evil" and foe is not None:
                self._line(R, f"{d['name']}: " + self._deal_rolled(foe, [[int(roll_dice(p["dice"]).total), p["type"]]], by=att, label=d["name"], spell=True), d["name"])
            elif k == "good":
                pals = [o for o in self.b["combatants"] if o is att or (self._alive(o) and not self._hostile(att, o) and o.get("pos") and att.get("pos")
                                                                        and self._dist(att, o) <= 30)]
                pals.sort(key=lambda o: self._hp_of(o) / max(1, o.get("max_hp") or (self._sheet(o).max_hp if self._sheet(o) else 1)))
                who = pals[0]
                n = int(roll_dice(p["dice"]).total)
                self._give_temp(who, n)
                self._line(R, f"{d['name']}: {who['name']} gains {n} temporary hit points", d["name"])
            elif k == "lawful":
                for who in [att] + [o for o in self.b["combatants"] if o is not att and self._alive(o) and not self._hostile(att, o)
                                    and o.get("pos") and att.get("pos") and self._dist(att, o) <= 30]:
                    gone = next((c for c in SHARD_CONDS if c in self._conds(who)), None)
                    if gone:
                        for eff in [x for x in who.get("effects") or [] if gone in (x.get("conditions") or [])]:
                            self._effect_off(who, eff, d["name"])
                        self._cond(who, gone, False)
                        self._line(R, f"{d['name']}: {who['name']} is no longer {gone.lower()}", d["name"])
                        break
            elif k == "shadow" and foe is not None:
                best = max(ABILITIES, key=lambda a: self._ability(foe, a))
                self._effect_on(foe, d["name"], [], None, None, None, None, att["name"], {"save_dis": [best], "check_dis": [best]},
                                None, att["id"], until=self._until("caster_end_next", att, foe))
                self._line(R, f"{d['name']}: {foe['name']} has disadvantage on {best.upper()} checks and saves until the end of {att['name']}'s next turn", d["name"])
            elif k == "farrealm":
                near = [o for o in self.b["combatants"] if o is not att and self._alive(o) and self._hostile(att, o) and o.get("pos") and att.get("pos")
                        and self._dist(att, o) <= p["ft"] and self._sees(att, o)]
                near.sort(key=lambda o: (o["id"] not in ids, self._dist(att, o)))
                if near:
                    self._stack().append(self._strike(att, f"{d['name']} (tentacle)", [near[0]["id"]], mode="save", spell=True, magical=True,
                                                      sv={"ab": "cha", "dc": dc, "half": False, "conds": ["Frightened"], "until": "caster_start"}, parts=[[p["dice"], "psychic"]]))

    def _wonder_craft(self, c: dict, char, entry: dict, data: dict, p: dict, option, targets):
        """A Dragon Vessel's potion, a Veteran's Cane's sword, a Talisman's fissure (use_wonder dispatches here)."""
        if p["kind"] == "vessel":
            pick = next((o["value"] for o in p["options"] if str(option or "").lower() in (o["value"].lower(), o["label"].lower())), None)
            if not pick:
                raise ServiceError("Choose which potion to fill the vessel with.")
            self._pay(c, p["cost"], data["name"])
            note = self._wonder_spend(c, char, entry, data, p)
            self.chars.add_item(char.name, pick, 1)
            line = f"{c['name']} fills the {data['name']} with {pick}{note}"
        elif p["kind"] == "transform":
            self._pay(c, p["cost"], data["name"])
            char.save()
            self.chars.remove_item(char.name, entry["name"], 1)
            self.chars.add_item(char.name, p["into"], 1)
            char = self._sheet(c)
            e = char.find_item(p["into"])
            if e is not None:
                e["equipped"] = True
                char.save()
            line = f"{c['name']}'s {data['name']} becomes a {p['into'].lower()}"
        else:                                                   # a Talisman of Pure Good / Ultimate Evil
            tgt = self._target((targets or [None])[0])
            if c.get("pos") and tgt.get("pos") and self._dist(c, tgt) > p["range"]:
                raise ServiceError(f"{tgt['name']} is out of range ({p['range']} ft).")
            if tgt.get("flying"):
                raise ServiceError("The fissure opens only under a creature on the ground.")
            self._pay(c, p["cost"], data["name"])
            note = self._wonder_spend(c, char, entry, data, p)
            kind = str((self._sheet(tgt).d.get("alignment") if self._sheet(tgt) else (self._monster(tgt) or {}).get("alignment")) or "").lower()
            line = f"{c['name']} raises the {data['name']} at {tgt['name']}{note}"
            if p["align"] not in re.findall(r"\w+", kind):
                line += f": {tgt['name']} isn't {p['align']}, nothing happens"
            else:
                res = self._saving_throw(tgt, "dex", p["dc"], spell=True, source=c, label=data["name"])
                line += f": a flaming fissure opens - DEX save {res['total']} vs DC {p['dc']} " + ("succeeds" if res["ok"] else "fails")
                if not res["ok"]:
                    line += f"; {tgt['name']} is destroyed: " + self._deal_rolled(tgt, [[self._hp_of(tgt) + 1000, ""]], by=c, label=data["name"])
            left = self._wonder_left(entry, data, p, char)
            if left <= 0 and entry["name"] in [x["name"] for x in self._sheet(c).inventory]:
                self.chars.remove_item(char.name, entry["name"], 1)
                line += f"; the {data['name']} disperses into motes of light"
        self._commit(line)
        return line

    # ------------------------------------------------------------------ Nature's Mantle
    def _mantle_hide(self, c: Optional[dict]) -> bool:
        """Is the hero wearing a Nature's Mantle ("in an area that is lightly obscured, you can Hide as a bonus action even if you are
        being directly observed")?"""
        char = self._sheet(c) if c and not c.get("form") else None
        return bool(char and any(re.search(r"you can Hide as a bonus action even if you are being directly observed", d.get("text") or "")
                                 for _e, d in char._active_items()))

    def _lightly_obscured(self, c: dict) -> bool:
        """Dim light, darkness or a haze on one of the creature's tiles (the same test the Hide check makes)."""
        if not c.get("pos"):
            return False
        ter, base, zones = self._terrain(), self.b.get("map", {}).get("light", "bright"), self._live_zones()
        tiles = G.footprint(c["pos"], c.get("span") or 1)
        return any(V.light_at(ter, t, base, zones) in ("dim", "dark") or V.obscured(t, zones) == "light" for t in tiles)

    # ------------------------------------------------------------------ Jester's Mask (BMT)
    def _jester(self, c: Optional[dict]) -> Optional[dict]:
        """The Jester's Mask worn by this hero while its once-a-day powers are still unspent (the item), or None."""
        char = self._sheet(c) if c and not c.get("form") else None
        return next((d for _e, d in char._active_items() if "Marvelous Escape" in (d.get("text") or "")
                     and not char.d["resources"].get(f"item:{d['name']}:escape")), None) if char else None

    def _jester_escape(self, R: dict, c: dict):
        """Marvelous Escape: the attack that hit takes no damage and the wearer teleports to the unoccupied space within 30 ft that is
        farthest from the foes."""
        d = self._jester(c)
        if d is None:
            return
        char = self._sheet(c)
        char.d["resources"][f"item:{d['name']}:escape"] = 1
        char.save()
        cur = R.setdefault("cur", {})
        cur.update(total=int(cur.get("ac") or 10) - 1, kept=min(int(cur.get("kept") or 2), 19), crit=False)
        best = self._far_tile(c, 30)
        if best:
            self._vfx("blink", id=c["id"], at=c.get("pos"), to=best)
            c["pos"] = best
        self._line(R, f"{c['name']} vanishes in a puff of smoke ({d['name']}): the hit does nothing" + (", reappearing elsewhere" if best else ""), d["name"])

    def _topsy_turvy(self, c: Optional[dict]) -> bool:
        """A natural 1 the Jester's Mask turns into a 20 (once until the next dawn)."""
        char = self._sheet(c) if c and not c.get("form") else None
        d = next((d for _e, d in char._active_items() if "Topsy-Turvy" in (d.get("text") or "")
                  and not char.d["resources"].get(f"item:{d['name']}:topsy")), None) if char else None
        if d is None:
            return False
        char.d["resources"][f"item:{d['name']}:topsy"] = 1
        char.save()
        self._say(f"{c['name']} rolled a 1: {d['name']} makes it a 20 (Topsy-Turvy)")
        return True

    def _tome_families(self, c: dict) -> List[str]:
        """The reaction families a hero's wizard books and Jester's Mask add (menu.reactions' ask/always/never settings)."""
        out = {"item_tome" if p["cost"] == "reaction" else "item_tome_free" for _e, _d, p in self._tome_items(c)}
        if self._jester(c):
            out.add("item_jester")
        if self._focus(c, "metallic") is not None:
            out.add("item_focus")
        if self._ornament(c) is not None:
            out.add("item_ornament")
        return sorted(out)

    # ------------------------------------------------------------------ worn items that change a weapon attack
    def _worn_weapon_flags(self, att: dict, w: dict) -> dict:
        """Attack flags a worn item gives a weapon attack (standard._weapon_atk, through itemextras._weapon_flags): a Butcher's Bib's
        slashing weapons crit on 19 or 20; a Battle Standard of Infernal Power's holder makes the weapon attacks of the allies within 300
        feet (and his own) magical."""
        out = {}
        char = self._sheet(att) if not att.get("form") else None
        for _e, d in (char._active_items() if char else []):
            m = re.search(r"Your weapon attacks that deal (\w+) damage score a critical hit on a roll of 19 or 20", d.get("text") or "")
            if m and str(w.get("type") or "").lower() == m.group(1).lower():
                out["crit_at"] = 19
        for o in self.b["combatants"]:
            och = self._sheet(o) if o.get("kind") == "pc" and not o.get("form") else None
            if och is None or self._hostile(o, att):
                continue
            for _e, d in och._active_items():
                m = re.search(r"your weapon attacks and those of all allied creatures within (\d+) feet of you count as magical", d.get("text") or "")
                if m and (o is att or not o.get("pos") or not att.get("pos") or self._dist(o, att) <= int(m.group(1))):
                    out["magical"] = True
        return out

    def _atlas_tile(self, c: dict, att: dict, a: dict, ft: int) -> Optional[list]:
        """A free space within `ft` of the hero that is out of the attack's reach (or range): where an Atlas of Endless Horizons lets it
        dodge a hit; None when no such space exists."""
        if not c.get("pos") or not att.get("pos"):
            return None
        reach = int(a.get("reach") or 5) if a.get("melee", True) else int(a.get("long") or a.get("normal") or 9999)
        x0, y0 = c["pos"]
        step = max(1, ft // 5)
        best = None
        for dx in range(-step, step + 1):
            for dy in range(-step, step + 1):
                x, y = x0 + dx, y0 + dy
                if (dx or dy) and self._tile_ok(c, x, y) and G.distance_ft([x, y], c.get("span") or 1, att["pos"], att.get("span") or 1) > reach \
                        and self._sees(c, dict(c, pos=[x, y])):
                    far = G.distance_ft([x, y], c.get("span") or 1, att["pos"], att.get("span") or 1)
                    if best is None or far < best[0]:
                        best = (far, [x, y])
        return best[1] if best else None

    def _forced_move_cut(self, c: dict, feet: int) -> int:
        """Dwarven Plate ("if an effect moves you against your will along the ground, you can use your reaction to reduce the distance you are
        moved by up to 10 feet"): the wearer uses its reaction (when it has one) and is moved less; returns the distance left, with its sign."""
        char = self._sheet(c) if c.get("kind") == "pc" and not c.get("form") else None
        plate = next((d for _e, d in char._active_items() if "reduce the distance you are moved by up to" in (d.get("text") or "")), None) if char else None
        if plate is None or not self._may_react(c):
            return feet
        cut = int(re.search(r"reduce the distance you are moved by up to (\d+) feet", plate["text"]).group(1))
        self._spend_reaction(c, plate["name"])
        left = max(0, abs(feet) - cut)
        self._say(f"{c['name']}'s {plate['name']}: reaction, moved {abs(feet) - left} ft less")
        return left if feet > 0 else -left

    def _tome_summoned(self, att: dict, sp: dict, made: list):
        """A Planecaller's Codex: a conjuration spell that summons one creature costs a charge and gives that creature advantage on its attack
        rolls for a minute (spent whenever the book has a charge: the summon is made at once, there is no moment to ask)."""
        if len(made) != 1 or str(sp.get("school") or "").lower() != "conjuration":
            return
        for e, d, p in self._tome_items(att):
            if p["key"] != "summon_adv" or p["school"] != "conjuration":
                continue
            char = self._sheet(att)
            e = char.find_item(e["name"])
            e["charges_left"] = self._charges_left(e) - 1
            char.save()
            self._effect_on(made[0], d["name"], [], None, None, None, 10, att["name"], {"attacks_with": "adv"}, None, att["id"])
            self._say(f"{att['name']} spends a charge of {d['name']}: {made[0]['name']} has advantage on its attack rolls for a minute "
                      f"({e['charges_left']} charges left)")
            return

    def _far_tile(self, c: dict, ft: int) -> Optional[list]:
        """The unoccupied space within `ft` feet that is farthest from the foes (where a blink takes a hero that has nowhere in mind)."""
        if not c.get("pos"):
            return None
        foes = [o for o in self.b["combatants"] if self._hostile(c, o) and o.get("pos") and self._alive(o)]
        best, far = None, -1
        x0, y0 = c["pos"]
        step = max(1, ft // 5)
        for dx in range(-step, step + 1):
            for dy in range(-step, step + 1):
                x, y = x0 + dx, y0 + dy
                if (dx or dy) and self._tile_ok(c, x, y) and G.distance_to_point(c["pos"], c.get("span") or 1, [x + .5, y + .5]) <= ft:
                    d_far = min([G.distance_ft([x, y], c.get("span") or 1, o["pos"], o.get("span") or 1) for o in foes] or [99])
                    if d_far > far:
                        best, far = [x, y], d_far
        return best

    def _spell_maximize(self, R: dict, att: Optional[dict], rolled: list) -> list:
        """What the caster's items do to a spell's damage dice, as they are rolled: a Potion of Maximum Power (the first damage-dealing spell of
        4th level or lower within the minute does the most each die can: the dice are replaced, flat bonuses stay; the potion is spent) and a
        Chromatic Dragon-Touched Focus (+1d6 to one damage roll of a slot spell dealing acid, cold, fire, lightning or poison damage)."""
        if att is None or not R.get("spell") or not rolled:
            return rolled
        sp = rules.spell(R.get("label") or "")
        if sp is None:
            return rolled
        hit = next(((e, v) for e, v in self._fxs(att, "max_spell")), None)
        if hit is not None and int(R.get("slot_level") or sp["level"]) <= int(hit[1]):
            out = []
            for (expr, typ), got in zip(R["parts"], rolled):
                m = re.fullmatch(r"(\d+)d(\d+)\s*(?:([+-])\s*(\d+))?", str(expr).replace(" ", ""))
                top = int(m.group(1)) * int(m.group(2)) + (int(m.group(4)) * (1 if m.group(3) != "-" else -1) if m.group(4) else 0) if m else got[0]
                out.append([max(got[0], top), got[1]])
            rolled = out
            self._use_once(att, "max_spell")
            self._line(R, f"{att['name']}'s Potion of Maximum Power: the highest number on every die", "Maximum Power")
        focus = self._focus(att, "chromatic")
        if focus is not None and sp["level"] > 0:
            pick = next((p for p in rolled if p[1] in ("acid", "cold", "fire", "lightning", "poison")), None)
            if pick is not None:
                n = int(roll_dice("1d6").total)
                pick[0] = int(pick[0]) + n
                self._line(R, f"{att['name']}'s {focus['name']}: +{n} {pick[1]} (chromatic)", focus["name"])
        return rolled

    def _focus(self, c: Optional[dict], family: str) -> Optional[dict]:
        """The Dragon-Touched Focus the hero holds when its pack entry's note names the dragon family (Chromatic, Gem, Metallic): the family
        the hoard made it is not on the item, so the note carries it."""
        char = self._sheet(c) if c and not c.get("form") else None
        for e, d in (char._active_items() if char else []):
            if "Dragon-Touched Focus" in d["name"] and family in str(e.get("note") or "").lower():
                return d
        return None

    DRAGON_BREATH = {"black": "acid", "blue": "lightning", "green": "poison", "red": "fire", "white": "cold", "brass": "fire", "bronze": "lightning",
                     "copper": "acid", "gold": "fire", "silver": "cold"}

    def _ornament(self, c: Optional[dict]) -> Optional[tuple]:
        """(item, damage type) of the Wakened or Ascendant Scaled Ornament the hero wears while its once-a-day ward is unspent; the type is the
        breath of the dragon colour its pack entry's note names (a hoard's colour is not on the item)."""
        char = self._sheet(c) if c and not c.get("form") else None
        for e, d in (char._active_items() if char else []):
            if "Scaled Ornament" in d["name"] and "use your reaction to take no damage instead" in (d.get("text") or "")                     and not char.d["resources"].get(f"item:{d['name']}:ornament"):
                low = str(e.get("note") or "").lower()
                kind = next((self.DRAGON_BREATH[k] for k in self.DRAGON_BREATH if k in low), None) or next((t for t in TYPES if t in low), None)
                if kind:
                    return d, kind
        return None

