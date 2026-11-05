"""Reactions: who may react at each point of a resolution, and what the reaction does.

Windows (see resolve.py):
    hit           an attack roll hits (target: Shield, Parry, Defensive Duelist; foes of the attacker: Silvery Barbs,
                  Cutting Words)
    on_hit        the attacker's own choices after hitting (Divine Smite, Stunning Strike) - free, not reactions
    damage        damage is rolled and about to land (target: Uncanny Dodge, Deflect Missiles, Absorb Elements,
                  Shield against Magic Missile)
    cast          a spell is being cast (foes within 60 ft: Counterspell)
    leave         a creature leaves another's reach (opportunity attack, Sentinel)
    after_damage  after being hurt by a creature (Hellish Rebuke)

Each candidate is {'reactor', 'cost', 'options': [{'key', 'label', 'detail'}], 'text'}; the option key's first part
('shield', 'smite:2' -> 'smite') is the reaction family whose ask/always/never setting applies.
"""
import re
from typing import List, Optional

from ...rules import spellcasting as SC
from ...rules.data import rules
from ..common import ServiceError
from . import combat_rules as CR
from . import features as F
from . import spell_effects as X
from . import spellbook as SB
from .classfeats import CLASS_FAMILIES, CLASS_FREE
from .resolve import DONE, roll
from .wondrous import ITEM_FAMILIES, ITEM_FREE

ELEMENTS = {"acid", "cold", "fire", "lightning", "thunder"}
# a stat block's own Uncanny Dodge, in all its wordings ("halves the damage that it takes from an attack", "...he takes...", "halves the attack's damage against it")
UNCANNY_STAT = r"halves? the damage (?:that )?(?:it|he|she|they) takes? from an attack|can halve the damage against it|halves the attack's damage against it"
FAMILIES = {**CLASS_FAMILIES, **ITEM_FAMILIES,              # Warding Flare... (classfeats.py), Ring of Evasion... (wondrous.py)
    "opportunity": "Opportunity attack", "shield": "Shield", "parry": "Parry", "duelist": "Defensive Duelist",
    "barbs": "Silvery Barbs", "cutting": "Cutting Words", "smite": "Divine Smite", "stun": "Stunning Strike",
    "uncanny": "Uncanny Dodge", "cut": "Reduce the damage (stat block)", "deflect": "Deflect Missiles", "absorb": "Absorb Elements", "counterspell": "Counterspell",
    "rebuke": "Hellish Rebuke", "legendary_resistance": "Legendary Resistance", "lucky": "Lucky", "sentinel": "Sentinel",
    "polearm": "Polearm Master", "mage_slayer": "Mage Slayer", "warcaster": "War Caster", "second_chance": "Second Chance",
    "fade_away": "Fade Away", "orcish_fury": "Orcish Fury", "reactive_resistance": "Reactive Resistance", "wings": "Protective Wings",
    "reprisal": "Telekinetic Reprisal", "readied": "Readied smite", "onhit": "Smite spell","indomitable": "Indomitable", "mreact": "Retaliation (stat block)",
    "redirect": "Redirect Attack", "icharm": "Instinctive Charm", "protect": "Protection", "rockcatch": "Rock Catching", "guard": "Guard an ally", "entrystrike": "Strike as it comes in", "reversal": "Reversal of Fortune", "boost": "Guided Strike", "feed": "Feed on Weakness", "reflect": "Spell Reflection",
    "tomb": "Tomb of Levistus", "presave_adv": "Encourage a save (stat block)", "shunt": "Temporal Shunt", "insight": "Precognitive Insight",
    "primordial": "Primordial Ward", "spellbacklash": "Backlash", "prescience": "Moment of Prescience", "reweave": "Reweave Fate",
    "spheres": "Effulgent Spheres", "liberation": "Alustriel's Mooncloak", "weave": "Norns' Weave",
}

# reactions that are spells: they get a casting circle on the maps too
def _per_day(name: str):
    """The '(3/Day)' of a stat block entry's name as a match (group 1: the uses); 'Recharges after a Short or Long Rest' is once."""
    return re.search(r"\((\d+)/Day", name, re.I) or (re.match(r"(1)", "1") if re.search(r"\(Recharges? after", name, re.I) else None)


SPELL_REACTIONS = {"shield": "Shield", "absorb": "Absorb Elements", "counterspell": "Counterspell", "barbs": "Silvery Barbs",
                   "rebuke": "Hellish Rebuke", "shunt": "Temporal Shunt", "spellbacklash": "Backlash", "prescience": "Moment of Prescience",
                   "reweave": "Reweave Fate"}


class ReactionsMixin:
    # ------------------------------------------------------------------ spells a creature could cast as a reaction
    def _reaction_spell(self, c: dict, name: str) -> Optional[int]:
        """The lowest spell level `c` can cast `name` at right now (0 for at-will), or None."""
        char = self._sheet(c)
        low = name.lower()
        if char:
            for sp in (s for s in SC.spell_known_or_prepared(char) if s["name"].lower() == low):
                if sp["level"] == 0:
                    return 0
                if sp.get("uses"):                       # innate (a tiefling's rebuke): its own uses, no slot
                    if not self.chars._innate_spent(char, sp):
                        return sp["level"]
                    continue
                left = SC.slots_remaining(char)
                levels = sorted(int(k) for k, v in left.items() if k != SC.PACT_KEY and v > 0 and int(k) >= sp["level"])
                pact = SC.spell_slots(char).get("pact")
                if left.get(SC.PACT_KEY) and pact and pact["level"] >= sp["level"]:
                    levels.append(pact["level"])
                if levels:
                    return min(levels)
            scroll = self._reaction_scroll(c, low)               # Shield or Counterspell read from a scroll
            if scroll:
                return scroll["spell"]["level"]
            item = self._reaction_item_spell(c, low)             # ... or cast from a magic item's charges (itemmore.py)
            return item["level"] if item else None
        book = self._monster_book(c)
        entry = book.get(low)
        if not entry and low == "counterspell":              # an alhoon's Negate Spell, a hexton's Counter Magic: as Counterspell
            e = self._stat_reaction(c, r"(?:is )?casting a spell\b[^.]*\.[^.]*?(?:3rd level or lower|level 3 or lower)[^.]*?(?:fails|no effect)")
            per_day = _per_day((e or {}).get("name", ""))
            base = re.sub(r"\s*\(.*?\)", "", (e or {}).get("name", ""))
            if e and not (per_day and (c.get("uses_day") or {}).get(base, 0) >= int(per_day.group(1)) or (c.get("spent") or {}).get(base)):
                return 3
        if not entry:
            return None
        return entry["level"] if self._monster_can_cast(c, low) else None

    def _reaction_scroll(self, c: dict, low: str) -> Optional[dict]:
        return next((s for s in self.scroll_items(c) if s["spell"]["name"].lower() == low and not s["why"]), None)

    def _spheres(self, c: dict) -> Optional[dict]:
        """The Elminster's Effulgent Spheres entry of `c` with a sphere left (its spell action holds the count), or None."""
        return next((a for a in c.get("spell_actions") or [] if a.get("spell") == "Elminster's Effulgent Spheres" and int(a.get("uses") or 0) > 0), None)

    def _reweave_offers(self, fc: Optional[dict], text: str) -> List[dict]:
        """Reweave Fate: whoever can see the creature that just failed a D20 Test (within 60 ft; not a foe of it) may cast it."""
        out = []
        if fc is None or not fc.get("pos"):
            return out
        for o in self.b["combatants"]:
            if not o.get("pos") or not self._alive(o) or not self._can_act(o) or not self._may_react(o) or self._hostile(o, fc):
                continue
            if o is not fc and (self._dist(o, fc) > 60 or not self._sees(o, fc)):
                continue
            if self._reaction_spell(o, "Reweave Fate") is not None:
                out.append({"reactor": o["id"], "cost": "reaction", "text": f"{text}. {o['name']}: Reweave Fate?",
                            "options": [{"key": "reweave", "label": f"Cast Reweave Fate: {fc['name']} rerolls with advantage", "detail": ""}]})
        return out

    def _spend_reaction_spell(self, c: dict, name: str, level: Optional[int]) -> int:
        char = self._sheet(c)
        if char:
            known = any(s["name"].lower() == name.lower() for s in SC.spell_known_or_prepared(char))
            scroll = self._reaction_scroll(c, name.lower())
            if scroll and (not known or not self._has_slot(c, level or scroll["spell"]["level"])):
                self.chars.remove_item(char.name, scroll["item"], 1)
                self._say(f"{c['name']} reads {scroll['item']}")
                return scroll["spell"]["level"]
            item = self._reaction_item_spell(c, name.lower())
            if item and (not known or not self._has_slot(c, level or item["level"])):
                return self._item_spell_spend(c, item)           # a Nightingale's Counterspell, a Staff of Defense's Shield (itemmore.py)
            res = self.chars.cast_spell(char.name, name, level if level else None, False)
            slot = res["slot"]
            if slot == SC.PACT_KEY:
                return (SC.spell_slots(char).get("pact") or {}).get("level", level or 1)
            return int(slot) if isinstance(slot, str) and slot.isdigit() else (level or res["spell"]["level"])
        self._monster_spend(c, name.lower())
        return level or 0

    def _spend_reaction(self, c: dict, what: str):
        t = c.get("turn")
        if t is not None:
            t["reaction"] = max(0, t.get("reaction", 1) - 1)
            t["react_at"] = [self.b.get("round"), self.b.get("turn")]      # when it went (Vigilant Defender, subfeats_c.py)
            t.setdefault("used", []).append(what)

    # ------------------------------------------------------------------ who may react
    def _eligible(self, window: str, R: dict, **ctx) -> List[dict]:
        att = self._find_or_none(ctx.get("attacker"))
        tgt = self._find_or_none(ctx.get("target"))
        out = []
        cur = R.get("cur") or {}
        a = R.get("atk") or {}
        if window == "hit" and att and tgt:
            opts = []
            lvl = self._reaction_spell(tgt, "Shield")
            if lvl is not None and lvl >= 0:
                opts.append({"key": "shield", "label": "Cast Shield (+5 AC)", "detail": f"{cur.get('total')} vs AC {cur.get('ac')}"})
            if self._reaction_spell(tgt, "Moment of Prescience") is not None and cur.get("kept") != 1:
                opts.append({"key": "prescience", "label": "Cast Moment of Prescience (the attack roll becomes a 1)", "detail": f"{cur.get('total')} vs AC {cur.get('ac')}"})
            parry, melee_only, pname = self._ac_reaction(tgt)
            if parry and (a.get("melee") or not melee_only):
                opts.append({"key": "parry", "label": f"{pname} (+{parry} AC)", "detail": ""})
            if self._feat(tgt, "lucky") and self._feat_uses_left(tgt, "Lucky"):
                opts.append({"key": "lucky", "label": f"Lucky: make it reroll ({self._feat_uses_left(tgt, 'Lucky')} left)", "detail": ""})
            if self._feat(tgt, "second_chance") and self._feat_uses_left(tgt, "Second Chance") and self._sees(tgt, att):
                opts.append({"key": "second_chance", "label": "Second Chance: make it reroll", "detail": ""})
            if self._feat(tgt, "gift_metallic") and self._feat_uses_left(tgt, "Protective Wings"):
                opts.append({"key": "wings", "label": f"Protective Wings (+{self._prof(tgt)} AC)", "detail": ""})
            char = self._sheet(tgt)
            if char and self._feat(tgt, "defensive_duelist") and a.get("melee") and \
                    any("finesse" in (w.get("props") or []) and not w.get("ranged") for w in char.attacks()):
                opts.append({"key": "duelist", "label": f"Defensive Duelist (+{char.proficiency_bonus} AC)", "detail": ""})
            if opts:
                out.append({"reactor": tgt["id"], "cost": "reaction", "options": opts,
                            "text": f"{att['name']} hits {tgt['name']} with {R['label']} ({cur.get('total')} vs AC {cur.get('ac')}). React?"})
            for o in self.b["combatants"]:
                if o is att or not self._hostile(o, att) or not o.get("pos") or not self._can_act(o):
                    continue
                opts = []
                if self._dist(o, att) <= 60 and self._sees(o, att) and self._reaction_spell(o, "Silvery Barbs") is not None:
                    opts.append({"key": "barbs", "label": "Cast Silvery Barbs (reroll, keep the lower)", "detail": ""})
                oc = self._sheet(o)
                if oc and oc.class_level("Bard") >= 3 and "lore" in ((oc.class_entry("Bard") or {}).get("subclass") or "").lower() \
                        and self._dist(o, tgt) <= 60 and self._sees(o, att) and self._resource_left(o, "Bardic Inspiration"):
                    opts.append({"key": "cutting", "label": "Cutting Words (subtract a Bardic Inspiration die)", "detail": ""})
                if opts:
                    out.append({"reactor": o["id"], "cost": "reaction", "options": opts,
                                "text": f"{att['name']} hits {tgt['name']} ({cur.get('total')} vs AC {cur.get('ac')}). {o['name']}: react?"})
            for o in self.b["combatants"]:                       # a neighbour's stat block: shield the target, or take the hit
                if o is tgt or o is att or not o.get("pos") or not tgt.get("pos") or self._hostile(o, tgt) or self._sheet(o) or not self._can_act(o):
                    continue
                guard = self._ally_guard(o, tgt)
                if guard:
                    out.append({"reactor": o["id"], "cost": "reaction", "options": [dict(guard, detail="")],
                                "text": f"{att['name']} hits {tgt['name']} ({cur.get('total')} vs AC {cur.get('ac')}). {o['name']}: {guard['label']}?"})
            for o in self.b["combatants"]:                       # Foster Peace: a creature it charmed can't land the hit
                fp = None if self._sheet(o) or o is att else self._stat_reaction(o, r"creature charmed by [^.]*hits with an attack roll[^.]*causes the attack to miss")
                if fp and o.get("pos") and att.get("pos") and self._dist(o, att) <= 60 and self._sees(o, att) and \
                        any("Charmed" in (e.get("conditions") or []) and e.get("source_id") == o["id"] for e in att.get("effects") or []):
                    out.append({"reactor": o["id"], "cost": "reaction", "options": [{"key": "guard:99:" + re.sub(r"\s*\(.*?\)", "", fp["name"]),
                                                                                     "label": re.sub(r"\s*\(.*?\)", "", fp["name"]), "detail": ""}],
                                "text": f"{att['name']} (charmed by {o['name']}) hits {tgt['name']}. Make it miss?"})
        elif window == "declared" and att and tgt and self._hostile(att, tgt):     # before the roll: stat block reactions
            for o in self.b["combatants"]:                       # Temporal Shunt: the attacker vanishes, the attack misses
                if o is not att and o.get("pos") and att.get("pos") and self._hostile(o, att) and self._dist(o, att) <= 120 \
                        and self._sees(o, att) and self._reaction_spell(o, "Temporal Shunt") is not None:
                    out.append({"reactor": o["id"], "cost": "reaction", "options": [{"key": "shunt", "label": "Cast Temporal Shunt", "detail": ""}],
                                "text": f"{att['name']} attacks {tgt['name']}. {o['name']}: shunt it out of time?"})
            if self._stat_reaction(tgt, r"targets (?:it|him|her) with an attack, (?:the )?[\w -]+ chooses another") and self._swap_partner(tgt, att):
                out.append({"reactor": tgt["id"], "cost": "reaction", "options": [{"key": "redirect", "label": "Redirect Attack", "detail": ""}],
                            "text": f"{att['name']} attacks {tgt['name']}. Redirect it to another ally?"})
            ch = self._stat_reaction(tgt, r"divert an attack|makes an attack roll against it, the [\w -]+ forces")
            if ch and tgt.get("pos") and att.get("pos") and self._dist(tgt, att) <= 30 and self._sees(tgt, att) and CR.split_save(ch["text"])[2]:
                out.append({"reactor": tgt["id"], "cost": "reaction", "options": [{"key": "icharm", "label": re.sub(r"\s*\(.*?\)", "", ch["name"]), "detail": ""}],
                            "text": f"{att['name']} attacks {tgt['name']}. Divert the attack?"})
            for o in self.b["combatants"]:                       # Protection: a neighbour of the target spoils the attack
                if o is tgt or o is att or not o.get("pos") or not tgt.get("pos") or self._hostile(o, tgt) or not self._can_act(o):
                    continue
                pr = self._stat_reaction(o, r"imposes? disadvantage on the attack roll")
                reach = re.search(r"within (\d+) feet of (?:the|him|her|it)", (pr or {}).get("text") or "")
                if pr and self._dist(o, tgt) <= (int(reach.group(1)) if reach else 5) and self._sees(o, att):
                    out.append({"reactor": o["id"], "cost": "reaction", "options": [{"key": "protect", "label": f"Protect {tgt['name']}", "detail": ""}],
                                "text": f"{att['name']} attacks {tgt['name']} next to {o['name']}. Impose disadvantage?"})
            out += self._insight_offers(att, f"{att['name']} attacks {tgt['name']}")
        elif window == "on_hit" and att and tgt:
            char = self._sheet(att)
            opts = []
            ready = self._readied_fits(att, a)
            if ready:
                opts.append({"key": f"readied:{ready['spell']}", "label": f"Cast {ready['spell']} (level {ready['level']} slot: {ready['note']})", "detail": ""})
            if char and char.class_level("Paladin") >= 2 and a.get("melee") and a.get("weapon"):
                left = SC.slots_remaining(char)
                undead = (self._monster(tgt) or {}).get("type") in ("undead", "fiend")
                for k in sorted((k for k in left if k != SC.PACT_KEY and left[k] > 0), key=int):
                    opts.append({"key": f"smite:{k}", "label": f"Divine Smite, level {k} slot (+{F.smite_dice(int(k), undead)} radiant)", "detail": "",
                                 "group": "Divine Smite", "choice": f"Level {k} slot (+{F.smite_dice(int(k), undead)} radiant)"})
            if char and a.get("weapon"):
                opts += self._on_hit_spell_options(att, a, ready)
            if char and a.get("weapon") and self._resource_left(att, "Superiority Dice"):
                die = F.superiority_die(char)
                for name in ("Trip Attack", "Pushing Attack", "Menacing Attack", "Disarming Attack", "Distracting Strike", "Goading Attack"):
                    if char.has_option(name):
                        opts.append({"key": f"maneuver:{name}", "label": f"{name} (+{die})", "detail": ""})
            if self._feat(att, "orcish_fury") and a.get("weapon") and self._feat_uses_left(att, "Orcish Fury"):
                opts.append({"key": "orcish_fury", "label": "Orcish Fury (+1 weapon die)", "detail": ""})
            if char and char.class_level("Monk") >= 5 and a.get("melee") and self._resource_left(att, "Ki Points"):
                opts.append({"key": "stun", "label": f"Stunning Strike (1 ki, DC {F.ki_dc(char)} Con save)", "detail": ""})
            if opts:
                out.append({"reactor": att["id"], "cost": "free", "options": opts,
                            "text": f"{att['name']} hits {tgt['name']}" + (" (critical!)" if cur.get("crit") else "") +
                                    (f". Cast the readied {ready['spell']} on this hit?" if ready else ". Add something?")})
        elif window == "missed" and att and tgt:
            if self._reaction_spell(att, "Moment of Prescience") is not None and self._may_react(att):
                out.append({"reactor": att["id"], "cost": "reaction", "options": [{"key": "prescience", "label": "Cast Moment of Prescience (the roll becomes a 20)",
                                                                                   "detail": f"{cur.get('total')} vs AC {cur.get('ac')}"}],
                            "text": f"{att['name']} misses {tgt['name']} ({cur.get('total')} vs AC {cur.get('ac')}). Turn the roll into a 20?"})
            out += self._reweave_offers(att, f"{att['name']} fails an attack roll against {tgt['name']} ({cur.get('total')} vs AC {cur.get('ac')})")
            if R.get("spell") and att is not tgt and self._stat_reaction(tgt, r"spell attack misses (?:it|the [\w ]+?), [^.]*?choose another creature"):
                out.append({"reactor": tgt["id"], "cost": "reaction", "options": [{"key": "reflect", "label": f"Spell Reflection: back at {att['name']}",
                                                                                   "detail": ""}],
                            "text": f"{R['label']} misses {tgt['name']}. Reflect it?"})
            for o in self.b["combatants"]:                       # a war priest's Guided Strike: +10 to its own or an ally's roll
                if self._sheet(o) or self._hostile(o, att) or not o.get("pos") or not att.get("pos") or not self._can_act(o):
                    continue
                e = self._stat_reaction(o, r"grants? a \+(\d+) bonus to (?:an|the) attack roll")
                name = re.sub(r"\s*\(.*?\)", "", (e or {}).get("name", ""))
                per_day = _per_day((e or {}).get("name", ""))
                if not e or per_day and (o.get("uses_day") or {}).get(name, 0) >= int(per_day.group(1)) or (o.get("spent") or {}).get(name):
                    continue
                near = re.search(r"within (\d+) feet", e["text"])
                bonus = int(re.search(r"\+(\d+) bonus", e["text"]).group(1))
                if (o is att or self._dist(o, att) <= (int(near.group(1)) if near else 30)) and cur.get("ac", 0) - cur.get("total", 0) <= bonus:
                    out.append({"reactor": o["id"], "cost": "reaction", "options": [{"key": f"boost:{bonus}:{name}", "label": f"{name} (+{bonus})", "detail": ""}],
                                "text": f"{att['name']} misses {tgt['name']} ({cur.get('total')} vs AC {cur.get('ac')}). {o['name']}: {name}?"})
            if self._feat(att, "lucky") and self._feat_uses_left(att, "Lucky"):
                out.append({"reactor": att["id"], "cost": "free", "options": [{"key": "lucky", "label": f"Lucky: reroll the attack ({self._feat_uses_left(att, 'Lucky')} left)",
                                                                                "detail": f"{cur.get('total')} vs AC {cur.get('ac')}"}],
                            "text": f"{att['name']} misses {tgt['name']} ({cur.get('total')} vs AC {cur.get('ac')}). Use a luck point?"})
            char = self._sheet(att)
            if char and char.has_option("Precision Attack") and self._resource_left(att, "Superiority Dice") and a.get("weapon"):
                out.append({"reactor": att["id"], "cost": "free", "options": [{"key": "precision", "label": f"Precision Attack (+{F.superiority_die(char)})",
                                                                                "detail": f"{cur.get('total')} vs AC {cur.get('ac')}"}],
                            "text": f"{att['name']} misses {tgt['name']} ({cur.get('total')} vs AC {cur.get('ac')}). Add a superiority die?"})
            tchar = self._sheet(tgt)
            if tchar and tchar.has_option("Riposte") and a.get("melee") and self._resource_left(tgt, "Superiority Dice") and self._may_react(tgt) \
                    and self._dist(att, tgt) <= self._reach(tgt):
                out.append({"reactor": tgt["id"], "cost": "reaction", "options": [{"key": "riposte", "label": "Riposte (attack back)", "detail": ""}],
                            "text": f"{att['name']} misses {tgt['name']}. Riposte?"})
        elif window == "before_save" and tgt:                    # an ally about to save: a stat block's "grants advantage on the roll"
            for o in self.b["combatants"]:
                if o is tgt or self._hostile(o, tgt) or not o.get("pos") or not tgt.get("pos") or not self._alive(o):
                    continue
                for e in (self._monster(o) or {}).get("reactions") or []:
                    m = re.search(r"ally within (\d+) feet of (?:the|it)\b[^.]*must make a saving throw[^.]*advantage", e.get("text") or "", re.I)
                    if m and self._dist(o, tgt) <= int(m.group(1)):
                        out.append({"reactor": o["id"], "cost": "reaction", "text": f"{tgt['name']} must save against {R.get('label')}. {e['name']}?",
                                    "options": [{"key": f"presave_adv:{e['name']}", "label": f"{e['name']}: advantage on {tgt['name']}'s save", "detail": ""}]})
                        break
            out += self._insight_offers(tgt, f"{tgt['name']} must save against {R.get('label')}")
        elif window == "damage" and tgt:
            opts = []
            types = {t for _n, t in cur.get("dmg") or []}
            if R.get("mode") == "attack" and att and self._fxs(tgt, "uncanny") or (att and R.get("mode") == "attack" and self._sheet(tgt)
                                                                                   and self._sheet(tgt).has_feature("Uncanny Dodge") and self._sees(tgt, att)):
                opts.append({"key": "uncanny", "label": "Uncanny Dodge (halve the damage)", "detail": ""})
            elif R.get("mode") == "attack" and att and self._stat_reaction(tgt, UNCANNY_STAT) and self._sees(tgt, att):
                opts.append({"key": "uncanny", "label": "Uncanny Dodge (halve the damage)", "detail": ""})    # a monster's own
            cut = None if self._sheet(tgt) or not att or R.get("mode") != "attack" else self._stat_cut(tgt)
            if cut and self._sees(tgt, att) and (a.get("melee") or not cut[2]):
                opts.append({"key": "cut", "label": f"{cut[1]} (-{cut[0]} damage)", "detail": ""})    # a vampire's Resilient Flesh, Deflect Blow
            if R.get("mode") == "attack" and not a.get("melee") and a.get("weapon") and (self._sheet(tgt) and self._sheet(tgt).class_level("Monk") >= 3
                                                                                      or self._stat_deflect(tgt)):
                opts.append({"key": "deflect", "label": "Deflect Missiles", "detail": ""})
            if R.get("mode") == "attack" and tgt.get("pos"):    # Shield Block: a neighbour halves the hit on its ally
                for o in self.b["combatants"]:
                    sb = None if o is tgt or self._sheet(o) or not o.get("pos") or self._hostile(o, tgt) else \
                        self._stat_reaction(o, r"ally within (\d+) feet of [^.]*is hit by an attack, [^.]*reduce that attack's damage by half")
                    if sb and self._dist(o, tgt) <= int(re.search(r"within (\d+) feet", sb["text"]).group(1)) and self._can_act(o):
                        out.append({"reactor": o["id"], "cost": "reaction", "options": [{"key": "uncanny", "label": f"{re.sub(r' *[(].*', '', sb['name'])} "
                                                                                         f"(halve the damage to {tgt['name']})", "detail": ""}],
                                    "text": f"{tgt['name']} is about to take damage next to {o['name']}. Block?"})
            rev = self._stat_reaction(tgt, r"reduces the damage (?:it takes from an attack )?to 0") if att is not None and att is not tgt else None
            if rev:                                             # a nilbog's Reversal of Fortune
                opts.append({"key": f"reversal:{re.sub(r' *[(].*', '', rev['name'])}", "label": re.sub(r"\s*\(.*?\)", "", rev["name"]), "detail": ""})
            if R.get("mode") == "attack" and not a.get("melee") and re.search(r"\brock|boulder", R.get("label") or "", re.I) \
                    and self._stat_reaction(tgt, r"rock or similar object is hurled at"):
                opts.append({"key": "rockcatch", "label": "Rock Catching (DC 10 Dexterity save)", "detail": ""})
            hit_types = types & ELEMENTS
            if hit_types and self._reaction_spell(tgt, "Absorb Elements") is not None:
                t = sorted(hit_types)[0]
                opts.append({"key": f"absorb:{t}", "label": f"Cast Absorb Elements (resist {t})", "detail": ""})
            if types and self._reaction_spell(tgt, "Backlash") is not None:
                opts.append({"key": "spellbacklash", "label": "Cast Backlash (cut the damage; the attacker saves or takes force damage)", "detail": ""})
            if hit_types and self._spheres(tgt) is not None:        # Elminster's Effulgent Spheres: one sphere gives resistance to the type
                opts.append({"key": f"spheres:{sorted(hit_types)[0]}", "label": f"Absorb Energy: spend a sphere (resist {sorted(hit_types)[0]})", "detail": ""})
            if hit_types and any(e["name"] == "Primordial Ward" for e in tgt.get("effects") or []):      # the ward's resistances become one immunity
                for t in sorted(hit_types):
                    opts.append({"key": f"primordial:{t}", "label": f"Primordial Ward (immune to {t}, then the spell ends)", "detail": ""})
            if hit_types and self._feat(tgt, "gift_chromatic") and self._feat_uses_left(tgt, "Reactive Resistance"):
                t = sorted(hit_types | (types & {"poison"}))[0]
                opts.append({"key": f"reactive_resistance:{t}", "label": f"Reactive Resistance ({t})", "detail": ""})
            if R.get("label") == "Magic Missile" and self._reaction_spell(tgt, "Shield") is not None:
                opts.append({"key": "shield", "label": "Cast Shield (blocks Magic Missile)", "detail": ""})
            ch = self._sheet(tgt)
            if ch and ch.has_option("Tomb of Levistus") and not ch.d.get("resources", {}).get("short:Tomb of Levistus"):     # once a short rest
                opts.append({"key": "tomb", "label": f"Tomb of Levistus (+{10 * ch.class_level('Warlock')} temporary HP, then encased in ice)", "detail": ""})
            if opts:
                total = sum(n for n, _t in cur.get("dmg") or [])
                out.append({"reactor": tgt["id"], "cost": "reaction", "options": opts,
                            "text": f"{tgt['name']} is about to take {total} damage from {R['label']}. React?"})
        elif window == "cast" and att:
            for o in self.b["combatants"]:
                if o is att or not self._hostile(o, att) or not o.get("pos") or not att.get("pos"):
                    continue
                if self._dist(o, att) > 60 or not self._sees(o, att):
                    continue
                if self._feat(o, "mage_slayer") and self._dist(o, att) <= 5 and self._melee_weapon_of(o):
                    out.append({"reactor": o["id"], "cost": "reaction",
                                "options": [{"key": "mage_slayer", "label": f"Mage Slayer: attack {att['name']}", "detail": ""}],
                                "text": f"{att['name']} casts {R['label']} right next to {o['name']}. Attack it?"})
                lvl = self._reaction_spell(o, "Counterspell")
                if lvl is not None:
                    out.append({"reactor": o["id"], "cost": "reaction",
                                "options": [{"key": "counterspell", "label": "Cast Counterspell", "detail": f"{R.get('label')} at level {R.get('slot_level')}"}],
                                "text": f"{att['name']} is casting {R['label']} (level {R.get('slot_level') or 0}). {o['name']}: counter it?"})
                if self._reaction_spell(o, "Temporal Shunt") is not None:
                    out.append({"reactor": o["id"], "cost": "reaction", "options": [{"key": "shunt", "label": "Cast Temporal Shunt", "detail": ""}],
                                "text": f"{att['name']} is casting {R['label']}. {o['name']}: shunt it out of time?"})
        elif window == "leave":
            mover = self._find_or_none(ctx.get("mover"))
            for oid in ctx.get("threats") or []:
                o = self._find_or_none(oid)
                if not o or not mover:
                    continue
                opts = [{"key": "opportunity", "label": f"Opportunity attack on {mover['name']}", "detail": ""}]
                if self._feat(o, "war_caster") and self._oa_cantrip(o):
                    opts.append({"key": "warcaster", "label": f"War Caster: cast {self._oa_cantrip(o)} at {mover['name']}", "detail": ""})
                out.append({"reactor": o["id"], "cost": "reaction", "options": opts,
                            "text": f"{mover['name']} is leaving {o['name']}'s reach. Opportunity attack?"})
        elif window == "enter":
            mover = self._find_or_none(ctx.get("mover"))
            for oid in ctx.get("threats") or []:
                o = self._find_or_none(oid)
                if o and mover:
                    w = self._melee_weapon_of(o) or {}
                    pole = any(p in (w.get("weapon_name") or w.get("name") or "").lower() for p in ("glaive", "halberd", "quarterstaff", "spear", "pike"))
                    opts = [{"key": "polearm", "label": f"Polearm Master: attack {mover['name']} as it comes in", "detail": ""}] \
                        if self._feat(o, "polearm_master") and pole else []
                    if self._brace_ok(o):                       # classfeats.py: the Brace maneuver
                        opts.append({"key": "brace", "label": f"Brace: attack {mover['name']} (+ superiority die)", "detail": ""})
                    er = None if self._sheet(o) else self._entry_reaction(o)
                    if er:                                      # a stat block's "when a creature enters ... it makes an attack"
                        opts.append({"key": f"entrystrike:{er[0]}", "label": f"{er[0]}: attack {mover['name']}", "detail": ""})
                    if opts:
                        out.append({"reactor": o["id"], "cost": "reaction", "options": opts,
                                    "text": f"{mover['name']} enters {o['name']}'s reach. Attack it?"})
        elif window == "attacked_other" and att:
            for o in self.b["combatants"]:
                if o is att or not self._feat(o, "sentinel") or not self._hostile(o, att) or not o.get("pos") or not att.get("pos"):
                    continue
                if o["id"] in (R.get("targets") or []) or self._dist(o, att) > 5 or not self._may_react(o) or not self._melee_weapon_of(o):
                    continue
                victims = [self._find_or_none(t) for t in R.get("targets") or []]
                if any(v and self._feat(v, "sentinel") for v in victims):
                    continue
                out.append({"reactor": o["id"], "cost": "reaction", "window": "attacked_other",
                            "options": [{"key": "sentinel", "label": f"Sentinel: attack {att['name']}", "detail": ""}],
                            "text": f"{att['name']} attacked someone else next to {o['name']}. Strike back (Sentinel)?"})
        elif window == "save_failed" and tgt:
            if not cur.get("auto") and self._may_react(tgt):
                if self._reaction_spell(tgt, "Moment of Prescience") is not None:
                    out.append({"reactor": tgt["id"], "cost": "reaction", "options": [{"key": "prescience", "label": "Cast Moment of Prescience (the save becomes a 20)",
                                                                                       "detail": f"{cur.get('total')} vs DC {R['sv']['dc']}"}],
                                "text": f"{tgt['name']} failed its {R['sv']['ab'].upper()} save ({cur.get('total')} vs DC {R['sv']['dc']}). Turn the roll into a 20?"})
                moon = next((e for e in tgt.get("effects") or [] if e["name"] == "Alustriel's Mooncloak" and e.get("source_id") == tgt["id"]), None)
                if moon and {"Frightened", "Grappled", "Restrained"} & set(R["sv"].get("conds") or []):
                    out.append({"reactor": tgt["id"], "cost": "reaction", "options": [{"key": "liberation", "label": "Liberation: succeed on the save instead (ends the spell)", "detail": ""}],
                                "text": f"{tgt['name']} failed its {R['sv']['ab'].upper()} save against {R.get('label')}. Alustriel's Mooncloak: succeed instead?"})
            if not cur.get("auto"):
                out += self._reweave_offers(tgt, f"{tgt['name']} fails a {R['sv']['ab'].upper()} save against {R.get('label')} ({cur.get('total')} vs DC {R['sv']['dc']})")
            opts = []
            if self._feat(tgt, "lucky") and self._feat_uses_left(tgt, "Lucky"):
                opts.append({"key": "lucky", "label": f"Lucky: reroll the save ({self._feat_uses_left(tgt, 'Lucky')} left)", "detail": ""})
            char = self._sheet(tgt)
            if char and char.class_level("Fighter") >= 9 and self._resource_left(tgt, "Indomitable") > 0:     # the new roll stands
                opts.append({"key": "indomitable", "label": f"Indomitable: reroll the save ({self._resource_left(tgt, 'Indomitable')} left)",
                             "detail": ""})
            if opts:
                out.append({"reactor": tgt["id"], "cost": "free", "options": opts,
                            "text": f"{tgt['name']} failed its {R['sv']['ab'].upper()} save ({cur.get('total')} vs DC {R['sv']['dc']}). Reroll it?"})
            for o in self.b["combatants"]:                       # a star spawn larva mage's Feed on Weakness
                if o is tgt or self._sheet(o) or not o.get("pos") or not tgt.get("pos") or not self._can_act(o):
                    continue
                e = self._stat_reaction(o, r"fails a saving throw, [^.]*gains (\d+) temporary hit points")
                near = re.search(r"within (\d+) feet", (e or {}).get("text") or "")
                if e and self._dist(o, tgt) <= (int(near.group(1)) if near else 30):
                    n = re.search(r"gains (\d+) temporary hit points", e["text"]).group(1)
                    out.append({"reactor": o["id"], "cost": "reaction", "options": [{"key": f"feed:{n}", "label": f"{re.sub(r' *[(].*', '', e['name'])} (+{n} temp HP)",
                                                                                     "detail": ""}], "text": f"{tgt['name']} failed a save near {o['name']}. Feed?"})
        elif window == "after_damage" and att and tgt:
            if tgt is not att and self._alive(tgt) and self._may_react(tgt):
                if self._feat(tgt, "gift_gem") and self._feat_uses_left(tgt, "Telekinetic Reprisal") and self._dist(tgt, att) <= 10:
                    out.append({"reactor": tgt["id"], "cost": "reaction", "window": "after_damage",
                                "options": [{"key": "reprisal", "label": f"Telekinetic Reprisal on {att['name']}", "detail": ""}],
                                "text": f"{att['name']} hurt {tgt['name']}. Telekinetic Reprisal?"})
                for e in self._retaliations(tgt, att, R):     # Unbridled Fury, Fiendish Rebuke, Frigid Rebuke...
                    out.append({"reactor": tgt["id"], "cost": "reaction", "window": "after_damage",
                                "options": [{"key": f"mreact:{e['name']}", "label": f"{e['name']} against {att['name']}", "detail": ""}],
                                "text": f"{att['name']} hurt {tgt['name']}. {e['name']}?"})
                if self._feat(tgt, "fade_away") and self._feat_uses_left(tgt, "Fade Away"):
                    out.append({"reactor": tgt["id"], "cost": "reaction", "window": "after_damage",
                                "options": [{"key": "fade_away", "label": "Fade Away (turn invisible)", "detail": ""}],
                                "text": f"{tgt['name']} was hurt. Fade Away?"})
            if tgt is not att and self._alive(tgt) and self._dist(tgt, att) <= 60 and self._sees(tgt, att) and self._may_react(tgt):
                if self._reaction_spell(tgt, "Hellish Rebuke") is not None:
                    out.append({"reactor": tgt["id"], "cost": "reaction", "window": "after_damage",
                                "options": [{"key": "rebuke", "label": f"Cast Hellish Rebuke on {att['name']}", "detail": ""}],
                                "text": f"{att['name']} hurt {tgt['name']}. Hellish Rebuke?"})
        out += self._weave_offers(window, R, att, tgt)           # spells.py: Norns' Weave's recorded d20s
        self._class_eligible(out, window, R, att, tgt, ctx)      # classfeats.py: Warding Flare, Guided Strike, Eldritch Smite...
        self._wonder_eligible(out, window, R, att, tgt, ctx)     # wondrous.py: Ring of Evasion, Absorbing Tattoo...
        return out

    def _still_ok(self, window: str, R: dict, reactor: dict, option: dict) -> bool:
        return True

    def _readied_fits(self, c: dict, a: dict) -> Optional[dict]:
        """The smite (or arrow spell) `c` readied, when this weapon attack can carry it and a slot is still there:
        {'spell', 'level', 'note'}."""
        r = c.get("on_hit_spell")
        if not r or not a.get("weapon"):
            return None
        key = r["spell"].lower()
        if key not in X.ON_HIT or not X.on_hit_fits(key, bool(a.get("melee"))):
            return None
        if self._sheet(c):
            low = self._reaction_spell(c, r["spell"])
        else:                                                # a monster: its stat block's level, or any the DM gives it
            book = self._monster_book(c).get(key)
            low = ((book or {}).get("level") or r.get("slot") or rules.spell(r["spell"])["level"]) if self._monster_can_cast(c, key) else None
        if low is None:
            return None
        lvl = r.get("slot") if r.get("slot") and self._has_slot(c, r["slot"]) else low
        return {"spell": r["spell"], "level": lvl, "note": X.BUFFS[key].get("note", "")}

    def _on_hit_spell_options(self, c: dict, a: dict, ready: Optional[dict]) -> List[dict]:
        """The smites (and arrow spells) `c` knows and can cast on this weapon hit without readying them first: one option
        per slot level left, grouped per spell (the popup shows a button with a level dropdown). A readied one is offered on its own."""
        char = self._sheet(c)
        left = SC.slots_remaining(char)
        pact = SC.spell_slots(char).get("pact") or {}
        out = []
        for sp in SC.spell_known_or_prepared(char):
            key = sp["name"].lower()
            if key not in X.ON_HIT or not X.on_hit_fits(key, bool(a.get("melee"))) or ready and ready["spell"].lower() == key:
                continue
            low = self._reaction_spell(c, sp["name"])
            if low is None or any(o["group"] == sp["name"] for o in out):
                continue
            lvls = {int(k) for k, v in left.items() if k != SC.PACT_KEY and v > 0 and int(k) >= low}
            if left.get(SC.PACT_KEY) and pact.get("level", 0) >= low:
                lvls.add(pact["level"])
            spec = SB.spec(rules.spell(sp["name"]) or sp)
            buff = spec["buff"]
            dice, dtype = buff["mods"]["dmg"]
            up, every = spec["special"].get("up") or buff.get("up"), spec["special"].get("up_every") or buff.get("up_every") or 1
            for lvl in sorted(lvls) or [low]:
                extra = max(0, lvl - sp["level"])
                d = SB.upcast([[dice, ""]], up, extra, every)[0][0] if up and extra else dice
                hint = f"+{d} {dtype}" if str(d) not in ("0", "") else buff.get("note", "")
                out.append({"key": f"onhit:{sp['name']}:{lvl}", "label": f"{sp['name']}, level {lvl} slot ({hint})", "detail": "",
                            "group": sp["name"], "choice": f"Level {lvl} slot ({hint})"})
        return out

    def _cast_on_hit(self, R: dict, c: dict, sp: dict, level: int):
        """Cast a smite (or arrow spell) as the weapon hit lands: its damage and rider ride this hit (roll_damage)."""
        lvl = self._spend_reaction_spell(c, sp["name"], level) or level
        spec = SB.spec(sp)
        conc = c["id"] if sp.get("concentration") else None
        if conc:
            self._start_conc(c, sp)
        self._spell_buff(R, c, sp, spec, spec["buff"], [c], lvl, max(0, lvl - sp["level"]), self._casting_mod(c), conc, None)

    def _parry_bonus(self, c: dict) -> int:
        return self._ac_reaction(c)[0]

    _INSIGHT = r"cause the roll to be made with advantage or disadvantage"

    def _insight_offers(self, roller: dict, what: str) -> List[dict]:
        """A Precognitive Mage's Insight (3/Day): when it or a creature it can see rolls an attack, a save or a check, it gives
        the roll advantage (its own side) or disadvantage (a foe). Reaction offers for the window before that roll."""
        out = []
        for o in self.b["combatants"]:
            e = None if self._sheet(o) or not self._alive(o) or not self._can_act(o) else self._stat_reaction(o, self._INSIGHT)
            if not e or not self._sees(o, roller):
                continue
            per_day = _per_day(e["name"])
            if per_day and (o.get("uses_day") or {}).get(re.sub(r"\s*\(.*?\)", "", e["name"]), 0) >= int(per_day.group(1)):
                continue
            foe = o is not roller and self._hostile(o, roller)
            out.append({"reactor": o["id"], "cost": "reaction", "text": f"{what}. {o['name']}: Precognitive Insight ({'disadvantage' if foe else 'advantage'})?",
                        "options": [{"key": "insight:" + ("dis" if foe else "adv"), "label": f"Precognitive Insight: {'disadvantage' if foe else 'advantage'} on {roller['name']}'s roll",
                                     "detail": ""}]})
        return out

    def _stat_reaction(self, c: dict, pattern: str) -> Optional[dict]:
        """A monster's stat block reaction whose text matches `pattern` (a monster's Uncanny Dodge...), or None."""
        m = None if self._sheet(c) else self._monster(c)
        return next((e for e in (m or {}).get("reactions") or [] if re.search(pattern, e.get("text") or "", re.I)), None)

    def _retaliations(self, c: dict, att: dict, R: dict) -> List[dict]:
        """Stat block reactions to being hit or hurt that strike back at the attacker: an attack ("In response to being hit
        by a melee attack, the tanarukk can make one melee weapon attack with advantage against the attacker") or a save
        ("When the eladrin takes damage from a creature ... within 60 feet of it, ... DC 16 Constitution saving throw")."""
        m = None if self._sheet(c) else self._monster(c)
        out = []
        for e in (m or {}).get("reactions") or []:
            text = e.get("text") or ""
            trigger = re.split(r"(?<=[.,])\s", text, 1)[0]
            if not re.match(r"(?:When|Whenever|Immediately after|In response to|After|As a reaction to)\b", text) or \
                    not re.search(r"\bhit(?:s|ting)?\b|damage[sd]?\b|\bbeing hit|takes? damage|taking damage", trigger) or \
                    re.search(r"another|an ally|allies|other than(?! its master)|reduced to|drops? to|\bfalls?\b|kills?|\bfails?\b|misses|"
                              r"random(?! creature within)|halves|"
                              r"\bAC\b|reduc|regains|Legendary|each creature", text, re.I):
                continue
            base = re.sub(r"\s*\(.*?\)", "", e.get("name", ""))
            per_day = _per_day(e.get("name", ""))
            if per_day and (c.get("uses_day") or {}).get(base, 0) >= int(per_day.group(1)) or (c.get("spent") or {}).get(base):
                continue
            if re.search(r"melee (?:weapon )?attack", trigger) and not (R.get("atk") or {}).get("melee"):
                continue
            near = re.search(r"within (\d+) (?:feet|ft)", trigger)
            if near and c.get("pos") and att.get("pos") and self._dist(c, att) > int(near.group(1)):
                continue
            if "can see" in text and not self._sees(c, att):
                continue
            if CR.split_save(text)[2] or self._retaliation_attack(c, e) or self._retort_damage(text) or \
                    re.search(r"\bteleports(?:,? along with [^.]*?carrying,)? up to \d+ feet", text):
                out.append(dict(e, name=re.sub(r"\s*\(.*?\)", "", e.get("name", ""))))
        return out

    def _entry_reaction(self, o: dict):
        """(name, feet or None for its reach) of a stat block reaction that strikes a creature coming close: "In response to a
        creature entering a space within 15 feet of it, the boneclaw makes one Piercing Claw attack", "When a creature
        enters a space within 5 feet of the ogre, the ogre makes a Bash attack". None when it has none (or it's used up)."""
        for e in (self._monster(o) or {}).get("reactions") or []:
            text = e.get("text") or ""
            g = re.search(r"(?:enters?|entering|moving into) (?:a space )?(?:within (\d+) (?:feet|ft\.?) of (?:it|the [\w -]+?)|its reach)\b", text)
            if not g or not self._retaliation_attack(o, e):
                continue
            name = re.sub(r"\s*\(.*?\)", "", e.get("name", ""))
            per_day = _per_day(e.get("name", ""))
            if per_day and (o.get("uses_day") or {}).get(name, 0) >= int(per_day.group(1)) or (o.get("spent") or {}).get(name):
                continue
            return name, int(g.group(1)) if g.group(1) else None
        return None

    def _ally_guard(self, o: dict, tgt: dict) -> Optional[dict]:
        """A stat block reaction of `o` that saves a hit neighbour: +N AC against the attack (Intercept Attack, Psionic Shield,
        Protective Shield) or taking the hit itself (Self-Sacrifice, Loyal Bodyguard). {'key', 'label'} or None."""
        for e in (self._monster(o) or {}).get("reactions") or []:
            text, name = e.get("text") or "", re.sub(r"\s*\(.*?\)", "", e.get("name", ""))
            per_day = _per_day(e.get("name", ""))
            if per_day and (o.get("uses_day") or {}).get(name, 0) >= int(per_day.group(1)) or (o.get("spent") or {}).get(name):
                continue
            near = re.search(r"within (\d+) feet of (?:it|him|her|the [\w -]+?)\b", text)
            if self._dist(o, tgt) > (int(near.group(1)) if near else 5):
                continue
            kind = re.search(r"another (\w+) within", text)
            if kind and kind.group(1).lower() not in ("creature", "ally") and kind.group(1).lower() != str((self._monster(tgt) or {}).get("type") or "").lower():
                continue                                     # Loyal Bodyguard: only for another fiend
            ac = re.search(r"(?:gives|grants?) (?:that creature|the target|it) a \+(\d+) bonus to (?:its|their) AC|target of the attack gains a \+(\d+) bonus to its AC", text)
            if ac and re.search(r"another creature|allies|a creature within|that creature", text):
                return {"key": f"guard:{ac.group(1) or ac.group(2)}:{name}", "label": f"{name} (+{ac.group(1) or ac.group(2)} AC)"}
            if re.search(r"is hit instead|causes itself to be hit instead", text):
                return {"key": f"guard:swap:{name}", "label": f"{name} (take the hit)"}
        return None

    def _swap_partner(self, c: dict, att: dict) -> Optional[dict]:
        """Redirect Attack: another creature of its kind (a goblin) within 5 feet of `c` to take the attack instead."""
        named = re.search(r"chooses another (\w+) within", (self._stat_reaction(c, r"chooses another \w+ within") or {}).get("text") or "")
        kind = named.group(1).lower() if named else ((self._monster(c) or {}).get("name") or "").split()[0].lower()    # Krenko: "another goblin"
        return next((o for o in self.b["combatants"] if o is not c and o is not att and o.get("pos") and c.get("pos") and self._alive(o)
                     and not self._hostile(o, c) and self._dist(o, c) <= 5 and kind in ((self._monster(o) or {}).get("name") or "").lower()), None)

    def _escape_tile(self, c: dict, feet: int):
        """A free tile within `feet` of `c` as far as it can get from its foes (a Misty Escape), or None."""
        if not c.get("pos"):
            return None
        foes = [o for o in self.b["combatants"] if o.get("pos") and self._hostile(o, c) and self._alive(o)]
        w, h, _fw = self._bounds()
        best, score = None, -1
        x0, y0 = c["pos"]
        r = feet // 5
        for x in range(max(0, x0 - r), min(w, x0 + r + 1)):
            for y in range(max(0, y0 - r), min(h, y0 + r + 1)):
                if [x, y] == list(c["pos"]) or max(abs(x - x0), abs(y - y0)) * 5 > feet or not self._tile_ok(c, x, y):
                    continue
                s = min((max(abs(x - o["pos"][0]), abs(y - o["pos"][1])) for o in foes), default=0)
                if s > score:
                    best, score = (x, y), s
        return best

    @staticmethod
    def _retort_damage(text: str):
        """[(dice, type)] of a reaction that simply deals damage to the attacker with no roll ("the statue deals 11 (2d10) piercing
        damage to the attacker"), else None."""
        g = re.search(r"\bdeals? (?:\d+ \()?(\d+d\d+(?: ?[+-] ?\d+)?)\)? (\w+) damage to the (?:attacker|creature)\b", text)
        return [(g.group(1).replace(" ", ""), g.group(2).lower())] if g and not CR.split_save(text)[2] and "for every" not in text else None

    def _retaliation_attack(self, c: dict, e: dict) -> Optional[dict]:
        """The attack a retaliation reaction makes: the action it names, else its first melee weapon attack."""
        text = e.get("text") or ""
        if re.search(r"[+-]\d+ to hit", text):
            return e                                         # it carries its own attack line (a Barbed Tail)
        ref = self._referenced_action(c, e.get("name", ""), text)
        if ref:
            return ref
        g = re.search(r"\bmakes? (?:one|a|an) (?:(?:melee )?(?:weapon )?attack|([\w' ]+?)(?: or [\w' ]+?)? attack)", text)
        if g:
            pool = [x for x in (self._monster(c) or {}).get("actions") or [] if re.search(r"[+-]\d+ to hit", x.get("text") or "")]
            want = (g.group(1) or "").lower().rstrip("s")
            return next((x for x in pool if want and x.get("name", "").lower().startswith(want)), None) or \
                next((x for x in pool if re.search(r"Melee Weapon Attack:", x.get("text") or "")), None)
        return None

    def _stat_deflect(self, c: dict) -> Optional[str]:
        """The dice a monster's Deflect Missile takes off a ranged weapon attack ("reduced by 7 (1d10 + 2)"), or None."""
        e = self._stat_reaction(c, r"ranged weapon attack")
        g = re.search(r"reduc\w* [^.]*?by (?:\d+ \((\d+d\d+(?: ?[+-] ?\d+)?)\)|(\d+d\d+(?: ?[+-] ?\d+)?))", (e or {}).get("text") or "")
        return (g.group(1) or g.group(2)).replace(" ", "") if g else None

    _CUT = r"(?:attack's damage is reduced by|reduces the damage (?:it|he|she|they) takes? from the attack by) (?:\d+ \()?(\d+d\d+(?: ?[+-] ?\d+)?)\)?"

    def _stat_cut(self, c: dict):
        """(dice, entry name, melee only) of a stat block reaction that takes dice off a hit on it ("the vampire reduces the damage it
        takes from the attack by 11 (2d6 + 4)", Deflect Blow's "the triggering attack's damage is reduced by 5 (1d10)"), or None."""
        e = self._stat_reaction(c, self._CUT)
        if not e or (c.get("spent") or {}).get(re.sub(r"\s*\(.*?\)", "", e["name"])):
            return None
        g = re.search(self._CUT, e.get("text") or "")
        return g.group(1).replace(" ", ""), re.sub(r"\s*\(.*?\)", "", e["name"]), bool(re.search(r"melee attack roll", e.get("text") or ""))

    def _ac_reaction(self, c: dict):
        """(AC bonus, melee only, name) of a stat block reaction that turns a hit into a miss: Parry ("adds 3 to its AC
        against one melee attack that would hit it"), Glyph of Shielding, a sage's Shield (+5), Warp Reality's +4...
        (0, False, '') when it has none."""
        m = None if self._sheet(c) else self._monster(c)
        for e in (m or {}).get("reactions") or []:
            name, text = re.sub(r"\s*\(.*?\)", "", e.get("name", "")), e.get("text", "")
            per_day = _per_day(e.get("name", ""))
            if per_day and (c.get("uses_day") or {}).get(name, 0) >= int(per_day.group(1)) or (c.get("spent") or {}).get(name):
                continue                                     # Magic Shield (3/Day) used up
            g = re.search(r"adds? \+?(\d+) to (?:its|his|her|their) AC(?:,? including)? against (?:one|an|the) ([\w ]*?)attack|"
                          r"(?:gains?|has|granting it|gives the target) a \+(\d+) bonus to (?:its|his|her) AC(?: against (?:the|that) (?:triggering )?attack| until)|"
                          r"increases? (?:its|his|her) AC by (\d+) against the attack", text)
            if name.lower().startswith("parry") or g and not re.search(r"another creature|an ally|one of its allies|a creature other", text):
                bonus = int(next((x for x in (g.group(1), g.group(3), g.group(4)) if x), 2)) if g else 2
                return bonus, bool(name.lower().startswith("parry") or g and "melee" in (g.group(2) or "")), name
        return 0, False, ""

    def _resource_left(self, c: dict, name: str) -> int:
        char = self._sheet(c)
        if not char:
            return 0
        from ...rules.resources import resource_list
        r = next((x for x in resource_list(char) if x["name"] == name), None)
        if not r:
            return 0
        return (r["max"] or 0) - r["used"] if r["max"] else 99

    def _use_resource(self, c: dict, name: str, n: int = 1) -> bool:
        char = self._sheet(c)
        if not char or self._resource_left(c, name) < n:
            return False
        char.d["resources"][name] = char.d["resources"].get(name, 0) + n
        char.save()
        return True

    # ------------------------------------------------------------------ choosing by itself ("always")
    def _auto_pick(self, window: str, R: dict, reactor: dict, options: List[dict], **ctx) -> Optional[str]:
        cur = R.get("cur") or {}
        keys = [o["key"] for o in options]
        own = self._class_auto_pick(window, R, reactor, keys) or self._wonder_auto_pick(window, R, reactor, keys)   # classfeats / wondrous
        if own:
            return own
        weave = next((k for k in keys if k.startswith("weave:")), None)
        if weave:                                               # Norns' Weave: offered only when it turns the roll
            return weave
        if window == "hit":
            if "prescience" in keys:                            # Moment of Prescience: the attack roll becomes a 1
                return "prescience"
            if cur.get("crit"):
                return "barbs" if "barbs" in keys else None
            need = cur.get("total", 0) - cur.get("ac", 0)
            if "shield" in keys and need < 5:
                return "shield"
            for k in keys:                                      # a neighbour's Intercept Attack when it turns the hit; a bodyguard always
                if k.startswith("guard:") and (k.split(":")[1] == "swap" or k.split(":")[1].isdigit() and need < int(k.split(":")[1])):
                    return k
            for k in ("parry", "duelist"):
                if k in keys:
                    bonus = self._parry_bonus(reactor) if k == "parry" else (self._sheet(reactor).proficiency_bonus if self._sheet(reactor) else 0)
                    if need < bonus:
                        return k
            if "wings" in keys and need < self._prof(reactor):
                return "wings"
            for k in ("lucky", "second_chance"):
                if k in keys:
                    return k
            if "barbs" in keys:
                return "barbs"
            return "cutting" if "cutting" in keys and need < 6 else None
        if window == "save_failed":
            for k in ("liberation", "prescience", "reweave"):     # (the spells that put a failed save right)
                if k in keys:
                    return k
            feed = next((k for k in keys if k.startswith("feed:")), None)
            if feed:                                            # a larva mage always feeds
                return feed
            if cur.get("auto"):
                return None
            return "lucky" if "lucky" in keys else "indomitable" if "indomitable" in keys else None
        if window in ("enter", "attacked_other"):
            return keys[0] if keys else None
        if window == "missed":
            for k in ("prescience", "reweave"):
                if k in keys:
                    return k
            if "lucky" in keys and cur.get("ac", 0) - cur.get("total", 0) <= 10:
                return "lucky"
            need = cur.get("ac", 0) - cur.get("total", 0)
            if "precision" in keys and 0 < need <= 6:
                return "precision"
            if "reflect" in keys:                               # a spectator sends the missed ray back
                return "reflect"
            boost = next((k for k in keys if k.startswith("boost:") and need <= int(k.split(":")[1])), None)
            if boost:                                           # Guided Strike turns the miss into a hit
                return boost
            return "riposte" if "riposte" in keys else None
        if window == "on_hit":
            ready = [k for k in keys if k.startswith("readied:")]
            if ready:
                return ready[0]
            if "stun" in keys:
                return "stun"
            if "orcish_fury" in keys and cur.get("crit"):
                return "orcish_fury"
            smites = [k for k in keys if k.startswith(("smite:", "onhit:"))]
            return smites[0] if smites and cur.get("crit") else None
        if window == "damage":
            for k in keys:
                if k.startswith(("absorb", "reversal", "primordial", "spheres")) or k in ("uncanny", "cut", "deflect", "shield", "rockcatch", "spellbacklash"):
                    return k
            return None
        return keys[0] if keys else None

    # ------------------------------------------------------------------ what a reaction does
    def _apply_reaction(self, window: str, R: dict, reactor: Optional[dict], key: str, **ctx):
        if reactor is None:
            return
        fam, _, arg = key.partition(":")
        cur = R.setdefault("cur", {})
        name = arg.rpartition(":")[0] if fam == "onhit" else FAMILIES.get(fam, fam)
        other =next((o for o in (ctx.get("mover"), ctx.get("attacker"), ctx.get("target"), R.get("actor")) if o is not None and o != reactor["id"]), None)
        spell = rules.spell(SPELL_REACTIONS[fam]) if fam in SPELL_REACTIONS else None
        self._vfx("react", id=reactor["id"], key=fam, name=name, other=other, arg=arg,    # the "!" and what it does, on the maps
                  src=self._magic_source(reactor, spell) if spell else None, tier=CR.vfx_tier(spell["level"]) if spell else None)
        if fam not in ("smite", "onhit", "stun", "maneuver", "precision", "lucky", "orcish_fury", "readied", "indomitable") and fam not in CLASS_FREE and fam not in ITEM_FREE:
            self._spend_reaction(reactor, name)
        if fam in CLASS_FAMILIES:
            self._class_react(window, R, reactor, fam, arg, ctx)
        elif fam in ITEM_FAMILIES:
            self._wonder_react(window, R, reactor, fam, arg, ctx)
        elif fam == "readied":
            ready = self._readied_fits(reactor, R.get("atk") or {})
            reactor.pop("on_hit_spell", None)
            sp = rules.spell(arg)
            if not ready or not sp:
                return
            self._cast_on_hit(R, reactor, sp, ready["level"])
        elif fam == "onhit":                                     # a smite picked straight from the hit's menu (not readied)
            spell_name, _, lvl = arg.rpartition(":")
            sp = rules.spell(spell_name)
            if not sp or self._reaction_spell(reactor, sp["name"]) is None:
                return
            self._cast_on_hit(R, reactor, sp, int(lvl))
        elif fam == "shield":
            self._spend_reaction_spell(reactor, "Shield", self._reaction_spell(reactor, "Shield"))
            self._effect_on(reactor, "Shield", [], None, None, None, None, reactor["name"], {"ac": 5, "mm_immune": True}, None,
                            reactor["id"], until={"start": reactor["id"]})
            self._line(R, f"{reactor['name']} casts Shield: +5 AC until its next turn", "Shield!")
            if window == "damage":
                cur["dmg"] = []
        elif fam in ("parry", "duelist"):
            bonus = self._parry_bonus(reactor) if fam == "parry" else self._sheet(reactor).proficiency_bonus
            name = (self._ac_reaction(reactor)[2] or name) if fam == "parry" else name     # Glyph of Shielding, Shield...
            full = next((e["name"] for e in (self._monster(reactor) or {}).get("reactions") or [] if fam == "parry"
                         and re.sub(r"\s*\(.*?\)", "", e.get("name", "")) == name), "")
            if full:
                self._mark_used(reactor, name, re.search(r"\(Recharge\s*(\d)", full, re.I), _per_day(full))
            cur["ac_extra"] = cur.get("ac_extra", 0) + bonus
            self._line(R, f"{reactor['name']} uses {name}: +{bonus} AC against this attack", name)
        elif fam == "barbs":
            self._spend_reaction_spell(reactor, "Silvery Barbs", self._reaction_spell(reactor, "Silvery Barbs"))
            again = self.rng.randint(1, 20)
            if again < cur.get("kept", 20):
                cur["total"] -= cur["kept"] - again
                cur["kept"] = again
                cur["crit"] = False
            self._line(R, f"{reactor['name']} casts Silvery Barbs: the attack is rerolled ({again}) → {cur['total']}", "Silvery Barbs")
        elif fam == "cutting":
            char = self._sheet(reactor)
            die = F.bardic_die(char) if char else "1d6"
            self._use_resource(reactor, "Bardic Inspiration")
            n = roll(die)
            cur["total"] -= n
            self._line(R, f"{reactor['name']} uses Cutting Words: -{n} → {cur['total']}", "Cutting Words")
        elif fam == "smite":
            lvl = int(arg)
            char = self._sheet(reactor)
            left = SC.slots_remaining(char)
            if left.get(str(lvl), 0) <= 0:
                return
            char.d["slots_used"][str(lvl)] = char.d["slots_used"].get(str(lvl), 0) + 1
            char.save()
            tgt = self._find_or_none(ctx.get("target"))
            undead = (self._monster(tgt) or {}).get("type") in ("undead", "fiend")
            cur.setdefault("bonus_parts", []).append([F.smite_dice(lvl, undead), "radiant"])
            self._line(R, f"{reactor['name']} smites with a level {lvl} slot (+{F.smite_dice(lvl, undead)} radiant)", "Divine Smite")
        elif fam == "stun":
            self._use_resource(reactor, "Ki Points")
            tgt = self._find_or_none(ctx.get("target"))
            char = self._sheet(reactor)
            if tgt:
                self._apply_save(R, reactor, tgt, {"ab": "con", "dc": F.ki_dc(char), "conds": ["Stunned"], "rounds": 1,
                                                   "note": "stunned until the end of the monk's next turn"})
        elif fam == "indomitable":
            if window != "save_failed" or not self._use_resource(reactor, "Indomitable"):
                return
            again = self.rng.randint(1, 20)
            total = cur["total"] - cur["kept"] + again                 # the new roll is used, even a worse one
            cur.update(total=total, kept=again, ok=total >= int(R["sv"]["dc"]))
            self._line(R, f"{reactor['name']} is indomitable: {again} → {total}" + (" — success" if cur["ok"] else " — still failed"), "Indomitable")
        elif fam == "lucky":
            if not self._feat_use(reactor, "Lucky"):
                return
            if window == "save_failed":
                tgt = self._find_or_none(ctx.get("target"))
                sv = R["sv"]
                again = self.rng.randint(1, 20)
                total = cur["total"] - cur["kept"] + again
                if total > cur["total"]:
                    cur.update(total=total, kept=again, ok=total >= int(sv["dc"]))
                self._line(R, f"{reactor['name']} uses a luck point: {again} → {cur['total']}" + (" — success" if cur.get("ok") else ""), "Lucky")
            elif reactor["id"] == ctx.get("attacker"):
                again = self.rng.randint(1, 20)
                if again > cur.get("kept", 0):
                    cur["total"] += again - cur["kept"]
                    cur["kept"] = again
                    if again == 20:
                        cur["crit"] = True
                self._line(R, f"{reactor['name']} uses a luck point: {again} → {cur['total']}", "Lucky")
            else:
                again = self.rng.randint(1, 20)
                if again < cur.get("kept", 20):
                    cur["total"] -= cur["kept"] - again
                    cur["kept"] = again
                    cur["crit"] = False
                self._line(R, f"{reactor['name']} uses a luck point: the attacker rolls {again} → {cur['total']}", "Lucky")
        elif fam == "second_chance":
            self._feat_use(reactor, "Second Chance")
            again = self.rng.randint(1, 20)
            cur["total"] = cur["total"] - cur["kept"] + again
            cur["kept"] = again
            cur["crit"] = again == 20
            self._line(R, f"{reactor['name']} uses Second Chance: the attacker rerolls {again} → {cur['total']}", "Second Chance")
        elif fam == "wings":
            self._feat_use(reactor, "Protective Wings")
            cur["ac_extra"] = cur.get("ac_extra", 0) + self._prof(reactor)
            self._line(R, f"{reactor['name']} spreads Protective Wings: +{self._prof(reactor)} AC", "Protective Wings")
        elif fam == "primordial":                               # Primordial Ward: immunity to that type (this blow too) to the end of its next turn, then the spell ends
            for e in [e for e in reactor.get("effects") or [] if e["name"] == "Primordial Ward"]:
                self._effect_off(reactor, e, "traded for immunity")
            self._effect_on(reactor, "Primordial Ward (immune)", [], None, None, None, None, reactor["name"], {"immune": [arg], "ends_spell": "Primordial Ward"},
                            reactor["id"], reactor["id"], until={"end": reactor["id"], "skip": 1 if self.b.get("turn") == reactor["id"] else 0})
            self._line(R, f"{reactor['name']} is immune to {arg} until the end of its next turn (Primordial Ward)", "Primordial Ward")
        elif fam == "reactive_resistance":
            self._feat_use(reactor, "Reactive Resistance")
            self._effect_on(reactor, "Reactive Resistance", [], None, None, None, None, reactor["name"], {"resist": [arg]}, None, reactor["id"],
                            until={"end": reactor["id"], "skip": 0})
            self._line(R, f"{reactor['name']} uses Reactive Resistance ({arg})", "Reactive Resistance")
        elif fam == "orcish_fury":
            self._feat_use(reactor, "Orcish Fury")
            d = ((R.get("atk") or {}).get("parts") or [["1d4", ""]])[0]
            m = re.match(r"\d*d(\d+)", str(d[0]))
            cur.setdefault("bonus_parts", []).append([f"1d{m.group(1) if m else 4}", d[1]])
            self._line(R, f"{reactor['name']} unleashes Orcish Fury (+1 weapon die)", "Orcish Fury")
        elif fam == "fade_away":
            self._feat_use(reactor, "Fade Away")
            self._effect_on(reactor, "Fade Away", ["Invisible"], None, None, None, None, reactor["name"], {"ends_on": ["attack", "cast"]}, None,
                            reactor["id"], until={"end": reactor["id"], "skip": 1 if self.b.get("turn") == reactor["id"] else 0})
            self._line(R, f"{reactor['name']} fades away (invisible)", "Fade Away")
        elif fam == "reprisal":
            self._feat_use(reactor, "Telekinetic Reprisal")
            target = self._find_or_none(ctx.get("attacker"))
            char = self._sheet(reactor)
            if target and char:
                ab = max(("int", "wis", "cha"), key=char.mod)
                child = self._strike(reactor, "Telekinetic Reprisal", [target["id"]], mode="save",
                                     sv={"ab": "str", "dc": 8 + char.proficiency_bonus + char.mod(ab), "half": True, "push": 10},
                                     parts=[["2d8", "force"]], magical=True)
                self._stack().append(child)
        elif fam in ("sentinel", "mage_slayer", "polearm"):
            target = self._find_or_none(ctx.get("attacker") if fam != "polearm" else ctx.get("mover"))
            if fam == "polearm":
                target = self._find_or_none(ctx.get("mover"))
            if target:
                child = self._opportunity_strike(reactor, target)
                if child:
                    child["label"] = f"{name} ({child['label'].split('(')[-1].rstrip(')')})"
                    self._stack().append(child)
        elif fam == "warcaster":
            mover = self._find_or_none(ctx.get("mover"))
            spell = self._oa_cantrip(reactor)
            if mover and spell:
                child = self._cantrip_strike(reactor, spell, mover)
                if child:
                    self._say(f"{reactor['name']} casts {spell} at {mover['name']} as it leaves (War Caster)")
                    self._stack().append(child)
        elif fam in ("maneuver", "precision", "riposte"):
            char = self._sheet(reactor)
            if not self._use_resource(reactor, "Superiority Dice"):
                return
            die = F.superiority_die(char)
            dc = 8 + char.proficiency_bonus + max(char.mod("str"), char.mod("dex"))
            tgt = self._find_or_none(ctx.get("target"))
            att = self._find_or_none(ctx.get("attacker"))
            if fam == "precision":
                n = roll("1" + die)
                cur["total"] = cur.get("total", 0) + n
                self._line(R, f"{reactor['name']} uses Precision Attack: +{n} → {cur['total']}", "Precision")
                return
            if fam == "riposte":
                child = self._opportunity_strike(reactor, att) if att else None
                if child:
                    child["label"] = "Riposte"
                    child["cur"] = {}
                    child["atk"]["parts"] = list(child["atk"].get("parts") or []) + [["1" + die, (child["atk"].get("parts") or [["", ""]])[0][1]]]
                    self._stack().append(child)
                return
            cur.setdefault("bonus_parts", []).append(["1" + die, ((R.get("atk") or {}).get("parts") or [["", ""]])[0][1]])
            self._line(R, f"{reactor['name']} uses {arg} (+{die})", arg)
            if tgt is None:
                return
            if arg in ("Trip Attack", "Pushing Attack") and self._size_of(tgt) in ("Huge", "Gargantuan"):
                self._line(R, f"{tgt['name']} is too big to {'trip' if arg == 'Trip Attack' else 'push'} (Large or smaller)", "too big")
                return
            if arg == "Trip Attack":
                self._apply_save(R, reactor, tgt, {"ab": "str", "dc": dc, "conds": ["Prone"]})
            elif arg == "Pushing Attack":
                res = self._saving_throw(tgt, "str", dc, label=arg)
                if not res["ok"]:
                    self._push(tgt, reactor, 15, R)
            elif arg == "Menacing Attack":
                self._apply_save(R, reactor, tgt, {"ab": "wis", "dc": dc, "conds": ["Frightened"], "rounds": 1})
            elif arg == "Goading Attack":
                self._apply_save(R, reactor, tgt, {"ab": "wis", "dc": dc, "mods": {"attacks_with": "dis"}, "rounds": 1,
                                                   "note": "disadvantage on attacks against others"})
            elif arg == "Distracting Strike":
                self._effect_on(tgt, "Distracted", [], None, None, None, None, reactor["name"], {"attacks_against": "adv", "once": True}, None,
                                reactor["id"], until={"start": reactor["id"]})
            elif arg == "Disarming Attack":
                res = self._saving_throw(tgt, "str", dc, label=arg)
                if not res["ok"]:
                    self._line(R, f"{tgt['name']} drops what it is holding", "disarmed")
        elif fam == "uncanny":
            cur["dmg"] = [[n // 2, t] for n, t in cur.get("dmg") or []]
            sb = self._stat_reaction(reactor, r"reduce that attack's damage by half") if reactor["id"] != ctx.get("target") else None
            label = re.sub(r"\s*\(.*?\)", "", sb["name"]) if sb else "Uncanny Dodge"   # a scaleshield's Shield Block for its neighbour
            self._line(R, f"{reactor['name']} uses {label}: half damage", label)
        elif fam == "cut":
            dice, label, _melee = self._stat_cut(reactor) or ("1d10", "Deflect Blow", False)
            cutn = roll(dice)
            left, out = cutn, []
            for n, t in cur.get("dmg") or []:
                take = min(n, left)
                left -= take
                out.append([n - take, t])
            cur["dmg"] = out
            self._line(R, f"{reactor['name']} uses {label}: -{cutn} damage", label)
        elif fam == "deflect":
            char = self._sheet(reactor)
            cut = roll("1d10") + char.mod("dex") + char.class_level("Monk") if char else roll(self._stat_deflect(reactor) or "1d10")
            left, out = cut, []
            for n, t in cur.get("dmg") or []:
                take = min(n, left)
                left -= take
                out.append([n - take, t])
            cur["dmg"] = out
            self._line(R, f"{reactor['name']} deflects the missile: -{cut} damage", "Deflect Missiles")
            att = self._find_or_none(ctx.get("attacker") or R.get("actor"))
            if not any(n for n, _t in out) and att and att.get("pos") and reactor.get("pos") and self._dist(reactor, att) <= 60 \
                    and self._resource_left(reactor, "Ki Points") >= 1:       # caught: thrown straight back for 1 ki (PHB)
                self._use_resource(reactor, "Ki Points", 1)
                part = ((R.get("atk") or {}).get("parts") or [["1d4", "piercing"]])[0]
                dice = re.sub(r"[+-]\d+$", "", str(part[0])) or "1d4"
                dex = char.mod("dex")
                back = self._strike(reactor, "Deflect Missiles (thrown back)", [att["id"]], mode="attack",
                                    atk={"bonus": char.proficiency_bonus + dex, "n": 1, "melee": False, "weapon": True,
                                         "parts": [[f"{dice}{dex:+d}", part[1] or "piercing"]], "normal": 20, "long": 60})
                th = R.pop("thrown", None)                      # in the monk's hand now, not on the floor
                if th and not th.get("prop") and not th.get("flask"):
                    back["thrown"] = dict(th, prop=None, **{"from": list(reactor["pos"])})
                self._line(R, f"{reactor['name']} catches it and throws it back (1 ki)", "caught")
                self._stack().append(back)
        elif fam == "shunt":                                    # Temporal Shunt: a Wisdom save or gone until its next turn starts
            att = self._find_or_none(ctx.get("attacker"))
            if not att:
                return
            self._spend_reaction_spell(reactor, "Temporal Shunt", self._reaction_spell(reactor, "Temporal Shunt"))
            dc = self._spell_dc(reactor)
            res = self._saving_throw(att, "wis", dc, spell=True, source=reactor, label="Temporal Shunt")
            self._line(R, f"{reactor['name']} casts Temporal Shunt: {att['name']} WIS save {res['total']} vs DC {dc} — "
                          + ("success" if res["ok"] else "failed"), "Temporal Shunt")
            if not res["ok"]:
                self._effect_on(att, "Temporal Shunt", ["Incapacitated"], None, None, None, None, reactor["name"],
                                {"banished": True, "untargetable": True}, None, reactor["id"], until={"start": att["id"]})
                if window == "cast":
                    R["countered"] = True                       # the spell is wasted
                else:
                    R["targets"][R["ti"]] = None                # the attack misses
                self._line(R, f"{att['name']} vanishes into another moment", "shunted")
        elif fam == "insight":                                  # Precognitive Insight: advantage or disadvantage on the coming roll
            e = self._stat_reaction(reactor, self._INSIGHT)
            if e:
                self._mark_used(reactor, re.sub(r"\s*\(.*?\)", "", e["name"]), None, _per_day(e["name"]))
            dis = arg == "dis"
            if window == "declared":
                tgt = self._find_or_none(ctx.get("target"))
                if tgt:
                    self._effect_on(tgt, f"Insight ({reactor['name']})", [], None, None, None, 1, reactor["name"],
                                    {"attacks_against": "dis" if dis else "adv", "once": True}, None, reactor["id"])
            elif dis:
                cur["presave_dis"] = True
            else:
                cur["presave_adv"] = "adv"
            self._line(R, f"{reactor['name']} foresees it: {'disadvantage' if dis else 'advantage'} on the roll", "Precognitive Insight")
        elif fam == "presave_adv":                              # Hold the Line: the coming save is made with advantage
            cur["presave_adv"] = arg or "encouraged"
            self._line(R, f"{reactor['name']} uses {arg or 'its reaction'}: advantage on the save", arg or "advantage")
        elif fam == "tomb":                                     # Tomb of Levistus: ice soaks the hit, then holds it until its next turn ends
            ch = self._sheet(reactor)
            n = 10 * (ch.class_level("Warlock") if ch else 1)
            if ch:
                ch.d.setdefault("resources", {})["short:Tomb of Levistus"] = 1      # back after a short rest
                ch.save()
            self._give_temp(reactor, n)
            self._effect_on(reactor, "Tomb of Levistus", ["Incapacitated"], None, None, None, None, reactor["name"],
                            {"vuln": ["fire"], "speed_set": 0, "keeps_conc": True, "temp_ends": True}, None, reactor["id"],
                            until={"end": reactor["id"], "skip": 1 if self.b.get("turn") == reactor["id"] else 0})
            self._line(R, f"{reactor['name']} is entombed in ice: {n} temporary hit points, incapacitated, vulnerable to fire", "Tomb of Levistus")
        elif fam == "absorb":
            lvl = self._spend_reaction_spell(reactor, "Absorb Elements", self._reaction_spell(reactor, "Absorb Elements"))
            self._effect_on(reactor, "Absorb Elements", [], None, None, None, None, reactor["name"],      # 1d6 per slot level
                            {"resist": [arg], "dmg": (f"{max(1, lvl or 1)}d6", arg), "once": True, "melee_only": True}, None, reactor["id"],
                            until={"start_next": reactor["id"]})
            self._line(R, f"{reactor['name']} casts Absorb Elements: resists {arg}", "Absorb Elements")
        elif fam == "spellbacklash":                                 # Backlash: 4d6 + the modifier off the damage; the attacker within 60 ft saves or takes 4d6 force
            lvl = self._spend_reaction_spell(reactor, "Backlash", self._reaction_spell(reactor, "Backlash")) or 4
            extra = max(0, lvl - 4)
            cut = roll(f"{4 + extra}d6") + self._casting_mod(reactor)
            left, kept = max(0, cut), []
            for n, t in cur.get("dmg") or []:
                take = min(n, left)
                left -= take
                kept.append([n - take, t])
            cur["dmg"] = kept
            self._line(R, f"{reactor['name']} casts Backlash: {max(0, cut)} damage is turned aside", "Backlash")
            foe = self._find_or_none(ctx.get("attacker") or R.get("actor"))
            if foe is not None and foe is not reactor and foe.get("pos") and reactor.get("pos") and self._dist(reactor, foe) <= 60 and self._alive(foe):
                self._stack().append(self._strike(reactor, "Backlash", [foe["id"]], mode="save", parts=[[f"{4 + extra}d6", "force"]], magical=True, spell=True,
                                                  sv={"ab": "con", "dc": self._spell_dc(reactor), "half": True}))
        elif fam == "prescience":                               # Moment of Prescience: a failed D20 Test becomes a 20, or the attack against you a 1
            self._spend_reaction_spell(reactor, "Moment of Prescience", self._reaction_spell(reactor, "Moment of Prescience"))
            if window == "hit":
                cur["total"] = cur.get("total", 0) - cur.get("kept", 1) + 1
                cur["kept"], cur["crit"] = 1, False
                self._line(R, f"{reactor['name']} casts Moment of Prescience: the attack roll becomes a 1", "Moment of Prescience")
            elif window == "missed":
                cur["total"] = max(cur.get("total", 0) - cur.get("kept", 1) + 20, cur.get("ac", 0) + 5)
                cur["kept"], cur["crit"] = 20, True
                self._line(R, f"{reactor['name']} casts Moment of Prescience: the attack roll becomes a 20", "Moment of Prescience")
            else:
                cur["total"] = cur.get("total", 0) - cur.get("kept", 0) + 20
                cur["kept"], cur["ok"] = 20, cur["total"] >= int(R["sv"]["dc"])
                self._line(R, f"{reactor['name']} casts Moment of Prescience: the save becomes a 20 → {cur['total']}" + (" — success" if cur["ok"] else ""),
                           "Moment of Prescience")
        elif fam == "reweave":                                  # Reweave Fate: the failed D20 Test is rerolled with advantage (the new roll stands); a success gives 6d10 temporary HP
            self._spend_reaction_spell(reactor, "Reweave Fate", self._reaction_spell(reactor, "Reweave Fate"))
            failer = self._find_or_none(ctx.get("attacker") if window == "missed" else ctx.get("target"))
            new = max(self.rng.randint(1, 20), self.rng.randint(1, 20))
            cur["total"] = cur.get("total", 0) - cur.get("kept", 0) + new
            if window == "missed":
                cur["kept"], cur["crit"] = new, new == 20
                won = new == 20 or (new != 1 and cur["total"] >= cur.get("ac", 0))
                if new == 20:
                    cur["total"] = max(cur["total"], cur.get("ac", 0) + 5)
            else:
                cur["kept"] = new
                cur["ok"] = won = cur["total"] >= int(R["sv"]["dc"])
            self._line(R, f"{reactor['name']} casts Reweave Fate: {failer['name'] if failer else 'it'} rerolls with advantage ({new}) → {cur['total']}"
                       + (" — success" if won else " — still fails"), "Reweave Fate")
            if won and failer is not None:
                n = roll("6d10")
                self._give_temp(failer, n)
                self._line(R, f"{failer['name']} gains {n} temporary hit points from its strengthened fate", f"+{n} temp HP")
        elif fam == "weave":                                    # Norns' Weave: a recorded d20 replaces the roll (spells.py)
            self._weave_apply(window, R, reactor, int(arg))
        elif fam == "spheres":                                  # Elminster's Effulgent Spheres: Absorb Energy
            sph = self._spheres(reactor)
            if sph is None:
                return
            sph["uses"] -= 1
            self._effect_on(reactor, "Effulgent Spheres (absorb)", [], None, None, None, None, reactor["name"], {"resist": [arg]}, None, reactor["id"],
                            until={"start": reactor["id"]})
            self._line(R, f"{reactor['name']} spends a sphere: resistance to {arg} until its next turn ({sph['uses']} left)", "Absorb Energy")
            if sph["uses"] <= 0:
                self._end_dispel(reactor, {"spell": sph["spell"], "name": "Absorb Energy"})
                for e in [e for e in reactor.get("effects") or [] if e["name"] == sph["spell"]]:
                    self._effect_off(reactor, e, "all spheres used")
        elif fam == "liberation":                               # Alustriel's Mooncloak: the failed save counts as a success, and the spell ends
            cur["ok"] = True
            cur["total"] = max(cur.get("total", 0), int(R["sv"]["dc"]))
            self._line(R, f"{reactor['name']} slips free (Alustriel's Mooncloak): the save succeeds instead", "Liberation")
            self._end_dispel(reactor, {"spell": "Alustriel's Mooncloak", "name": "Liberation"})
            for e in [e for e in reactor.get("effects") or [] if e["name"] == "Alustriel's Mooncloak"]:
                self._effect_off(reactor, e, "Liberation used")
        elif fam == "counterspell":
            lvl = self._reaction_spell(reactor, "Counterspell") or 3
            slot = R.get("slot_level") or 0
            use = max(lvl, min(9, slot)) if self._sheet(reactor) and self._has_slot(reactor, slot) else lvl
            used = self._spend_reaction_spell(reactor, "Counterspell", use) or use
            if not self._sheet(reactor) and "counterspell" not in self._monster_book(reactor):    # Negate Spell (3/Day): one use gone
                e = self._stat_reaction(reactor, r"(?:is )?casting a spell\b")
                if e:
                    self._mark_used(reactor, re.sub(r"\s*\(.*?\)", "", e["name"]), re.search(r"\(Recharge\s*(\d)", e["name"], re.I), _per_day(e["name"]))
            self._line(R, f"{reactor['name']} casts Counterspell (level {used})", "Counterspell")
            # a Counterspell is a spell too: its own cast window, where it can be countered in turn (PHB)
            self._stack().append(self._new_r("counter", reactor, "Counterspell", slot_level=used, against=slot, of=R["rid"]))
        elif fam == "opportunity":
            mover = self._find_or_none(ctx.get("mover"))
            if mover:
                child = self._opportunity_strike(reactor, mover)
                if child:
                    child["atk"]["opportunity"] = True          # Escape the Horde, the Eagle totem: disadvantage
                    self._stack().append(child)
        elif fam == "guard":                                    # a neighbour's Intercept Attack / Self-Sacrifice (_ally_guard)
            how, _, rname = arg.partition(":")
            e = next((x for x in (self._monster(reactor) or {}).get("reactions") or [] if re.sub(r"\s*\(.*?\)", "", x.get("name", "")) == rname), None)
            if e:
                self._mark_used(reactor, rname, re.search(r"\(Recharge\s*(\d)", e["name"], re.I), _per_day(e["name"]))
            tgt = self._find_or_none(R["targets"][R["ti"]]) if R.get("ti", 0) < len(R.get("targets") or []) else None
            if how == "swap" and tgt:
                if re.search(r"swaps places", (e or {}).get("text") or "") and tgt.get("pos") and reactor.get("pos"):
                    tgt["pos"], reactor["pos"] = reactor["pos"], tgt["pos"]
                R["targets"][R["ti"]] = reactor["id"]
                cur["ac_extra"] = cur.get("ac_extra", 0) - 100     # "is hit instead": the hit stands
                self._line(R, f"{reactor['name']} uses {rname}: it takes the hit instead of {tgt['name']}", rname)
            elif how.isdigit():
                cur["ac_extra"] = cur.get("ac_extra", 0) + int(how)
                self._line(R, f"{reactor['name']} uses {rname}: +{how} AC" + (f" for {tgt['name']}" if tgt else ""), rname)
        elif fam == "reflect":                                  # Spell Reflection: the missed spell attack goes at its caster
            caster = self._find_or_none(ctx.get("attacker"))
            if caster is not None:
                child = self._strike(caster, f"{R['label']} (reflected)", [caster["id"]], mode="attack", atk=dict(R.get("atk") or {}, n=1),
                                     magical=True, spell=True)
                self._line(R, f"{reactor['name']} reflects {R['label']} at {caster['name']}", "reflected")
                self._stack().append(child)
        elif fam == "feed":                                     # Feed on Weakness: temporary hit points from another's failed save
            self._give_temp(reactor, int(arg))
            self._line(R, f"{reactor['name']} feeds on the failure: {arg} temporary hit points", "feeds")
        elif fam == "boost":                                    # Guided Strike: the missed roll gets +N (window "missed")
            n, _, bname = arg.partition(":")
            e = self._stat_reaction(reactor, r"grants? a \+(\d+) bonus to (?:an|the) attack roll")
            if e:
                self._mark_used(reactor, bname, re.search(r"\(Recharge\s*(\d)", e["name"], re.I), _per_day(e["name"]))
            cur["total"] = cur.get("total", 0) + int(n)
            self._line(R, f"{reactor['name']} uses {bname}: +{n} → {cur['total']}", bname)
        elif fam == "reversal":                                 # Reversal of Fortune: no damage, and it heals
            e = self._stat_reaction(reactor, r"reduces the damage (?:it takes from an attack )?to 0")    # (Unstoppable: no heal)
            g = re.search(r"regains (?:\d+ \()?(\d+d\d+(?: ?[+-] ?\d+)?)", (e or {}).get("text") or "")
            cur["dmg"] = []
            n = roll(g.group(1).replace(" ", "")) if g else 0
            if n:
                self._heal(reactor, n)
            self._line(R, f"{reactor['name']} uses {arg}: no damage" + (f", regains {n} hit points" if n else ""), arg)
        elif fam == "entrystrike":                              # Deadly Reach, Block the Path (_entry_reaction)
            mover = self._find_or_none(ctx.get("mover"))
            e = next((x for x in (self._monster(reactor) or {}).get("reactions") or [] if re.sub(r"\s*\(.*?\)", "", x.get("name", "")) == arg), None)
            ref = self._retaliation_attack(reactor, e) if e else None
            if not mover or not ref:
                return
            self._mark_used(reactor, arg, re.search(r"\(Recharge\s*(\d)", e["name"], re.I), _per_day(e["name"]))
            try:
                child = self._monster_strike(reactor, mover, ref["name"], ref["text"], label=arg)   # it is stepping into reach now
                child["atk"]["melee"] = True
            except ServiceError as ex:
                self._line(R, f"{reactor['name']} can't use {arg}: {ex}", str(ex))
                return
            after = re.search(r"If the attack hits, ([^.]+)\.", e.get("text") or "")
            mods = CR.text_mods(after.group(1)) if after else {}
            if mods:                                            # "...the target's speed is reduced to 0 until the start of the ogre's next turn"
                until = CR.until_of(after.group(1))
                child["on_hit"] = {"name": arg, "conds": [], "mods": mods, "until": self._until(until, reactor, mover) if until else None,
                                   "rounds": None if until else 1}
            self._stack().append(child)
        elif fam == "rockcatch":                                # a stone giant catches the hurled rock
            g = re.search(r"DC (\d+) (\w+) saving throw", (self._stat_reaction(reactor, r"rock or similar object") or {}).get("text") or "")
            ab, dc = (CR.ABILITIES.get(g.group(2).lower(), "dex"), int(g.group(1))) if g else ("dex", 10)
            res = self._saving_throw(reactor, ab, dc, label="Rock Catching")
            if res["ok"]:
                cur["dmg"] = [[n, t] for n, t in cur.get("dmg") or [] if t != "bludgeoning"]
            self._line(R, f"{reactor['name']} " + ("catches the rock" if res["ok"] else "fails to catch the rock") + f" ({res['total']} vs DC {dc})",
                       "Rock Catching")
        elif fam in ("redirect", "icharm", "protect"):          # before the roll (window "declared")
            att = self._find_or_none(ctx.get("attacker"))
            tgt = self._find_or_none(ctx.get("target"))
            if not att or not tgt:
                return
            if fam == "protect":
                self._effect_on(tgt, f"Protected by {reactor['name']}", [], None, None, None, 1, reactor["name"],
                                {"attacks_against": "dis", "once": True}, None, reactor["id"])
                self._line(R, f"{reactor['name']} protects {tgt['name']}: the attack has disadvantage", "Protection")
                self._subd_deflect(reactor, R, att)             # Improved Defender: the attacker takes force damage (subfeats_d.py)
                return
            new = None
            if fam == "redirect":
                new = self._swap_partner(tgt, att)
                if new:
                    tgt["pos"], new["pos"] = new["pos"], tgt["pos"]
                    self._vfx("blink", id=tgt["id"], at=new["pos"], to=tgt["pos"])
            else:
                e = self._stat_reaction(reactor, r"divert an attack|makes an attack roll against it, the [\w -]+ forces")
                _pre, _post, save = CR.split_save(e["text"])
                res = self._saving_throw(att, save[0], save[1], label=e["name"])
                self._line(R, f"{att['name']} {save[0].upper()} save vs {re.sub(r' *[(].*', '', e['name'])}: {res['total']} vs DC {save[1]} — "
                           + ("success" if res["ok"] else "failed"), "save")
                self._mark_used(reactor, re.sub(r"\s*\(.*?\)", "", e["name"]), re.search(r"\(Recharge\s*(\d)", e["name"], re.I), _per_day(e["name"]))
                if re.search(r"disadvantage on that roll", e["text"]):      # a deathwolf's Imposing Slash: a spoiled roll, then a Claw strikes back
                    if not res["ok"]:
                        self._effect_on(tgt, re.sub(r"\s*\(.*?\)", "", e["name"]), [], None, None, None, 1, reactor["name"],
                                        {"attacks_against": "dis", "once": True}, None, reactor["id"])
                        self._line(R, f"{att['name']} has disadvantage on the attack roll", "Imposing Slash")
                    ref = self._retaliation_attack(reactor, e)
                    if ref and self._alive(att):
                        try:
                            child = self._monster_strike(reactor, att, ref["name"], ref["text"], label=re.sub(r"\s*\(.*?\)", "", e["name"]))
                            child["atk"]["melee"] = True
                            self._stack().append(child)
                        except ServiceError as ex:
                            self._line(R, f"{reactor['name']} can't strike back: {ex}", str(ex))
                    return
                if not res["ok"]:                               # it attacks the creature nearest to it instead
                    near = sorted((o for o in self.b["combatants"] if o is not att and o is not reactor and o.get("pos") and att.get("pos")
                                   and self._alive(o)), key=lambda o: self._dist(att, o))
                    new = near[0] if near and self._dist(att, near[0]) <= max(5, self._reach(att)) else None
                    if not new:
                        self._line(R, f"{att['name']}'s attack is diverted and goes nowhere", "diverted")
                        R["targets"][R["ti"]] = None             # the attack is spent on nothing
            if new:
                R["targets"][R["ti"]] = new["id"]
                self._line(R, f"{reactor['name']} uses {FAMILIES.get(fam, fam)}: {new['name']} becomes the target", FAMILIES.get(fam, fam))
        elif fam == "mreact":                                   # a stat block's retaliation (_retaliations)
            target = self._find_or_none(ctx.get("attacker"))
            e = next((x for x in (self._monster(reactor) or {}).get("reactions") or [] if re.sub(r"\s*\(.*?\)", "", x.get("name", "")) == arg), None)
            if not target or not e:
                return
            self._mark_used(reactor, arg, re.search(r"\(Recharge\s*(\d)", e["name"], re.I), _per_day(e["name"]))
            text = e.get("text") or ""
            pre, post, save = CR.split_save(text)
            blink = re.search(r"\bteleports(?:,? along with [^.]*?carrying,)? up to (\d+) feet", text)
            if blink and not save:                          # Misty Escape (unseen too), Evasive Footwork: away from its foes
                hide = bool(re.search(r"turns invisible and teleports", text))
                if hide:
                    self._effect_on(reactor, arg, ["Invisible"], None, None, None, None, reactor["name"], {"ends_on": ["attack", "cast"]}, None,
                                    reactor["id"], until={"start": reactor["id"]})
                spot = self._escape_tile(reactor, int(blink.group(1)))
                if spot:
                    self._vfx("blink", id=reactor["id"], at=reactor.get("pos"), to=list(spot))
                    reactor["pos"] = list(spot)
                    self._follow_zones(reactor)
                self._line(R, f"{reactor['name']} uses {arg}" + (": turns invisible" if hide else "") + (" and teleports away" if spot else ""), arg)
                return
            if save and not re.search(r"[+-]\d+ to hit", text):
                self._say(f"{reactor['name']} uses {arg} on {target['name']}")
                sv = {"ab": save[0], "dc": save[1], "half": "half as much" in post.lower(), **self._save_terms(post)}
                self._stack().append(self._strike(reactor, arg, [target["id"]], mode="save", sv=sv, parts=CR.save_damage(post), magical=True))
                return
            retort = None if re.search(r"[+-]\d+ to hit", text) else self._retort_damage(text)
            if retort:                                      # Flying Shards: it just deals the damage to the attacker
                self._say(f"{reactor['name']} uses {arg} on {target['name']}")
                self._stack().append(self._strike(reactor, arg, [target["id"]], mode="auto", parts=retort, magical=False))
                return
            ref = self._retaliation_attack(reactor, e)
            if not ref:
                return
            if re.search(r"random creature within", text) and reactor.get("pos"):    # Vicious Reprisal, Bloody Rampage: whoever is near
                rr = re.search(r"random creature within (\d+) feet", text)
                near = [o for o in self.b["combatants"] if o is not reactor and o.get("pos") and self._alive(o) and o["id"] != reactor.get("summoned_by")
                        and self._dist(reactor, o) <= (int(rr.group(1)) if rr else max(5, self._reach(reactor)))]
                if not near:
                    self._line(R, f"{reactor['name']} lashes out, but nobody is in reach ({arg})", arg)
                    return
                target = self.rng.choice(near)
            try:
                child = self._monster_strike(reactor, target, ref["name"], ref["text"], label=arg,
                                             adv="adv" if re.search(r"with advantage", text) else None)
                if reactor.get("pos") and target.get("pos"):
                    child["atk"] = self._check_reach(reactor, target, child["atk"])
            except ServiceError as ex:
                self._line(R, f"{reactor['name']} can't use {arg}: {ex}", str(ex))
                return
            self._stack().append(child)
        elif fam == "rebuke":
            lvl = self._reaction_spell(reactor, "Hellish Rebuke") or 1
            used = self._spend_reaction_spell(reactor, "Hellish Rebuke", lvl) or lvl
            target = self._find_or_none(ctx.get("attacker"))
            if target:
                dc = self._spell_dc(reactor)
                self._say(f"{reactor['name']} casts Hellish Rebuke at {target['name']}")
                child = self._strike(reactor, "Hellish Rebuke", [target["id"]], mode="save",
                                     sv={"ab": "dex", "dc": dc, "half": True}, parts=[[f"{1 + used}d10", "fire"]], spell=True)
                self._stack().append(child)

    def _step_counter(self, C: dict) -> str:
        """A Counterspell being cast: others may counter it; then it stops the spell it was aimed at (or fails to)."""
        me = self._find_or_none(C["actor"])
        if C["stage"] == "start":
            C["stage"] = "cast_win"
        if C["stage"] == "cast_win":
            return self._window(C, "cast", "resolve", attacker=C["actor"])
        target = next((r for r in self._stack() if r["rid"] == C["of"]), None)
        if C.get("countered"):
            self._line(C, f"{me['name'] if me else '?'}'s Counterspell is countered", "countered")
        elif target is not None and me is not None:
            used, slot = C["slot_level"], C["against"]
            ok = used >= slot
            note = f"automatic (level {used} vs {slot})"
            if not ok:
                total = self.rng.randint(1, 20) + self._casting_mod(me)
                ok = total >= 10 + slot
                note = f"check {total} vs DC {10 + slot}"
            target["countered"] = target.get("countered") or ok
            if ok:
                self._subd_surge(me)                            # Power Surge: magic stolen from a foiled spell (subfeats_d.py)
            self._vfx("countered", id=target["actor"], by=me["id"], ok=ok)     # the caster's circle breaks (or the counter's ray does)
            self._line(C, f"{me['name']}'s Counterspell: " + ("the spell fails" if ok else "the counter fails") + f" ({note})",
                       "COUNTERED" if ok else "counter failed")
        return DONE

    def _has_slot(self, c: dict, level: int) -> bool:
        char = self._sheet(c)
        if not char or level <= 0:
            return False
        left = SC.slots_remaining(char)
        pact = SC.spell_slots(char).get("pact")
        return left.get(str(level), 0) > 0 or bool(pact and pact["level"] == level and left.get(SC.PACT_KEY, 0) > 0)

    def _casting_mod(self, c: dict) -> int:
        char = self._sheet(c)
        if char:
            infos = SC.casters(char)
            return max([char.mod(i["ability"]) for i in infos] or [0])
        book = self._monster_book(c)
        return max(0, (next(iter(book.values()))["dc"] - 8 - self._prof(c)) if book else 0)

    def _spell_dc(self, c: dict) -> int:
        char = self._sheet(c)
        if char:
            return 8 + char.proficiency_bonus + self._casting_mod(c)
        book = self._monster_book(c)
        return next(iter(book.values()))["dc"] if book else 13

    def _melee_weapon_of(self, c: dict):
        char = self._sheet(c)
        if char and not c.get("form"):
            weapons = [w for w in char.attacks() if not w.get("ranged")]
            return max(weapons, key=lambda x: x["attack"]) if weapons else None
        m = self._monster(c)
        return next((e for e in (m or {}).get("actions") or [] if re.search(r"Melee (?:or Ranged )?Weapon Attack", e.get("text", ""), re.I)), None)

    def _oa_cantrip(self, c: dict) -> Optional[str]:
        """War Caster: the damaging single-target cantrip it would cast as an opportunity attack."""
        from . import spellbook as SB
        char = self._sheet(c)
        if not char:
            return None
        best = None
        for sp in SC.spell_known_or_prepared(char):
            if sp["level"] != 0:
                continue
            s = SB.spec(sp)
            if s["cost"] == "action" and s["target"]["type"] in ("creature", "split") and s["kind"] in ("attack", "save", "auto") and sp.get("damage"):
                best = best or sp["name"]
        return best

    def _cantrip_strike(self, c: dict, spell: str, tgt: dict) -> Optional[dict]:
        from ...rules.data import rules
        from . import combat_rules as CR
        sp = rules.spell(spell)
        char = self._sheet(c)
        if not sp or not char:
            return None
        info = next((s for s in SC.spell_known_or_prepared(char) if s["name"] == spell), None)
        ab = (info or {}).get("ability") or "int"
        mod = char.mod(ab)
        plan = CR.spell_plan(sp, None, char.total_level, mod)
        dc = 8 + char.proficiency_bonus + mod
        if plan["kind"] == "attack":
            return self._strike(c, f"{spell} (War Caster)", [tgt["id"]], mode="attack", spell=True,
                                atk={"bonus": char.proficiency_bonus + mod, "n": 1, "melee": False, "spell": True, "parts": plan["parts"], "ignore_cover": True})
        if plan["kind"] == "save":
            return self._strike(c, f"{spell} (War Caster)", [tgt["id"]], mode="save", spell=True,
                                sv={"ab": plan["save"] or "dex", "dc": dc, "half": plan["half"], "conds": plan["conds"]}, parts=plan["parts"])
        return self._strike(c, f"{spell} (War Caster)", [tgt["id"]], mode="auto", spell=True, parts=plan["parts"])

    def _opportunity_strike(self, att: dict, tgt: dict) -> Optional[dict]:
        """One melee attack: the character's best melee weapon, or the monster's first melee attack. Sentinel: a hit stops
        the target where it is."""
        char = self._sheet(att)
        if char and not att.get("form"):
            weapons = [w for w in char.attacks() if not w.get("ranged")]
            if not weapons:
                return None
            w = max(weapons, key=lambda x: x["attack"])
            atk = self._feat_attack(att, w, self._weapon_atk(att, w))
            atk["n"] = 1
            on_hit = None
            if self._feat(att, "sentinel"):
                on_hit = {"name": "Sentinel", "mods": {"speed_set": 0}, "note": "speed 0 (Sentinel)",
                          "until": {"end": self.b.get("turn") or tgt["id"], "skip": 0}}
            return self._strike(att, f"Opportunity attack ({w['name']})", [tgt["id"]], mode="attack", atk=atk,
                                magical=w.get("magic", False), on_hit=on_hit)
        m = self._monster(att)
        for e in (m or {}).get("actions") or []:
            text = e.get("text", "")
            if re.search(r"Melee (?:or Ranged )?Weapon Attack", text, re.I) and re.search(r"[+-]\d+ to hit", text):
                return self._monster_strike(att, tgt, e["name"], text, label=f"Opportunity attack ({e['name']})")
        return None
