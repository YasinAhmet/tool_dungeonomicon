"""Attacks and the actions everyone has (PHB chapter 9, DMG options), and a monster's stat block actions.

    pc_attack(cid, 'Longsword', target_id=4)          the Attack action (Extra Attack: the next attacks are free)
    offhand_attack(cid, 'Dagger', target_id=4)        two-weapon fighting, a bonus action
    use_action(cid, 'Bite', text, target_id=4)        a stat block entry: attack, save, area (breath), Multiattack...
    standard_action(cid, 'dodge')                     dash, disengage, dodge, help, hide, search, ready, use_object,
                                                      grapple, shove, escape, stand_up, drop_prone
"""
import re
from typing import List, Optional

from ...rules.data import rules
from ...rules.monsters import bestiary
from ..common import ServiceError
from . import combat_rules as CR
from . import conditions as K
from . import economy as EC
from . import features as F
from . import geometry as G
from . import modifiers as M
from . import sight as V
from .constants import ACTIVE, faction_of
from .resolve import DONE, NEXT, roll
from .traits import RUN_HIT_RE

DTYPES = set(CR._TYPES.strip("()").split("|"))
WORDS = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6}
SIZES = ["Tiny", "Small", "Medium", "Large", "Huge", "Gargantuan"]
LINGER = {"Stunned", "Blinded", "Deafened", "Incapacitated", "Unconscious", "Charmed", "Frightened", "Paralyzed", "Poisoned"}
FORM_ONLY = re.compile(r"\s*\([^)]*\bForms? Only\)", re.I)     # "Bite (Bat or Vampire Form Only)"
BONUS_STD = re.compile(r"take the ((?:Dash|Disengage|Hide)(?:,? (?:or )?(?:Dash|Disengage|Hide))*) action as a bonus action"
                       r"|bonus action to take the ((?:Dash|Disengage|Hide)(?:,? (?:or )?(?:Dash|Disengage|Hide))*) action"    # Cunning Action
                       r"|^(?:While [^,.]+, )?[\w' -]+? takes? the ((?:Dash|Disengage|Hide)(?:,? (?:or )?(?:Dash|Disengage|Hide))*) action\.?\s*$")
                                                       # an MPMM bonus action: "The xvart takes the Disengage action."
STANDARD = {
    "dash": ("Dash", "action", "Double your movement this turn."),
    "disengage": ("Disengage", "action", "Your movement doesn't provoke opportunity attacks this turn."),
    "dodge": ("Dodge", "action", "Attacks against you have disadvantage and you make Dex saves with advantage until your next turn."),
    "help": ("Help", "action", "The next attack an ally makes against the target (within 5 ft of you) has advantage."),
    "hide": ("Hide", "action", "Stealth check against the foes' passive Perception: unseen until you attack."),
    "search": ("Search", "action", "Perception check: find hidden creatures."),
    "ready": ("Ready", "action", "Hold an action for a trigger; it uses your reaction."),
    "use_object": ("Use an Object", "action", "Drink a potion, pull a lever..."),
    "grapple": ("Grapple", "attack", "Athletics against the target's Athletics or Acrobatics: grappled."),
    "shove": ("Shove", "attack", "Athletics contest: knock the target prone or push it 5 ft."),
    "escape": ("Escape", "action", "Break free of a grapple or restraint (Athletics / Acrobatics, or the effect's check)."),
    "stand_up": ("Stand up", "move", "Stand from prone: costs half your speed."),
    "stabilize": ("Stabilize", "action", "Medicine check (DC 10) on a dying creature within 5 ft."),
    "douse": ("Put out the flames", "action", "Dexterity check (DC 10): stop burning (Alchemist's Fire)."),
    "drop_prone": ("Drop prone", "free", "Fall prone (ranged attacks against you have disadvantage)."),
}


class StandardMixin:
    # ------------------------------------------------------------------ weapons
    def _weapon_atk(self, att: dict, w: dict, two_handed: bool = False) -> dict:
        props = w.get("props") or []
        rng = re.findall(r"\d+", str(w.get("range") or ""))
        normal, long_ = (int(rng[0]), int(rng[1]) if len(rng) > 1 else int(rng[0])) if rng else (None, None)
        dice = w.get("versatile") if two_handed and w.get("versatile") else w.get("dice")
        bonus = w.get("bonus") or 0
        if two_handed and w.get("versatile") and w.get("dueling"):    # Dueling is one-handed only
            bonus -= 2
        lift = 0
        char = self._sheet(att)
        if char and w.get("ability") in ("str", "dex"):              # a Giant Strength potion: the new Strength counts
            lift = max(0, self._ability(att, w["ability"]) - char.mod(w["ability"]))
        magic = bool(w.get("magic"))
        if char and w.get("ability") in ("str", "dex") and self._fx(att, "shillelagh") and re.search(r"club|quarterstaff", str(w.get("name")).lower()):
            sp_ab = (rules.spell("Shillelagh") or {}).get("ability") or "wis"      # Shillelagh: a d8, the casting ability, magical
            dice, magic = "1d8", True
            lift += max(0, char.mod(sp_ab) - char.mod(w["ability"]))
        shift = self._weapon_shift(att, w)                            # a Defender's bonus moved to AC, a Gambler's Blade's (itemextras.py)
        bonus += lift - shift
        expr = f"{dice}{bonus:+d}" if dice and bonus else (dice or str(max(1, bonus)))
        atk = {"bonus": w["attack"] + lift - shift, "n": 1, "melee": not w.get("ranged"), "weapon": True, "magical": magic,
               "parts": [[expr, w.get("type") or "bludgeoning"]], "finesse": "finesse" in props, "str_based": w.get("ability") == "str",
               "reach": 10 if "reach" in props else 5, "normal": normal, "long": long_, "thrown": "thrown" in props,
               "light": "light" in props, "props": props, "item": w.get("name"),
               "two_handed": "two-handed" in props or bool(two_handed and w.get("versatile"))}     # Great Weapon Fighting
        atk.update(self._weapon_flags(w, att))                        # Ephixis' 19s, magic arrows (itemextras.py)
        return self._class_weapon_atk(att, w, atk)              # Arms of the Astral Self, Fangs of the Fire Snake (classfeats.py)

    def _check_reach(self, att: dict, tgt: dict, atk: dict) -> dict:
        """Melee within reach, or a ranged/thrown attack within its long range; raises otherwise. Returns the atk to use."""
        if not att.get("pos") or not tgt.get("pos"):
            return atk
        d = self._dist(att, tgt)
        if atk["melee"]:
            if d <= atk.get("reach", 5):
                return atk
            if not (atk.get("thrown") and atk.get("long") and d <= atk["long"]):
                raise ServiceError(f"{tgt['name']} is out of reach ({d} ft)")
            atk = dict(atk, melee=False)                    # a dagger or javelin thrown: a ranged attack, and walls stop it
        if atk.get("long") and d > atk["long"]:
            raise ServiceError(f"{tgt['name']} is out of range ({d} ft, range {atk['normal']}/{atk['long']})")
        if self._cover_between(att, tgt) >= V.TOTAL:
            raise ServiceError(f"{tgt['name']} has total cover")
        return atk

    def _pay_attack(self, c: dict, attacks: int, what: str):
        """One attack of the Attack action: the first spends the action, Extra Attack leaves the rest to make."""
        if self._fx(c, "two_attacks"):                          # Tenser's Transformation, Tasha's Otherworldly Guise
            attacks = max(attacks, 2)
        attacks = self._subc_attack_floor(c, attacks)           # Awakened Astral Self (subfeats_c.py)
        if not self._economy_on():
            if self.b.get("status") != ACTIVE:
                self._fresh_turn(c)
            return
        why = self._pay(c, "attack", what, check_only=True)
        if why:
            raise ServiceError(why)
        t = c.setdefault("turn", EC.new_turn(self._speed(c)))
        if t.get("attacks", 0) > 0:
            t["attacks"] -= 1
            t.setdefault("used", []).append(what)
        else:
            EC.start_attack_action(t, attacks)
            t.setdefault("used", []).append(what)
            t["attacked"] = True

    def pc_attack(self, attacker_id: int, weapon: str, adv: Optional[str] = None, target_id: Optional[int] = None,
                  two_handed: bool = False) -> str:
        """A player character's weapon attack on the target: attack roll, then damage (doubled dice on a natural 20)."""
        with self.lock:
            self._busy()
            att, tgt = self._find(attacker_id), self._target(target_id)
            char = self._char(att["character"])
            low = weapon.strip().lower()
            w = next((a for a in char.attacks() if a["name"].lower() == low or low in a["name"].lower()), None) if char else None
            if not w:
                raise ServiceError(f"{att['name']} has no equipped weapon matching '{weapon}'.")
            atk = self._feat_attack(att, w, self._check_reach(att, tgt, self._weapon_atk(att, w, two_handed)))
            atk["adv"] = adv
            t = att.get("turn") or {}
            net = (w.get("weapon_name") or w["name"]).lower() == "net"
            loading = ("loading" in (w.get("props") or []) and not self._feat(att, "crossbow_expert") and not self._race_firearm(att, w)) or net
            if loading and self._economy_on() and t.get("attacks", 0) > 0 and t.get("loaded_shot"):
                raise ServiceError(f"{w['name']}: one attack per action" + (" (Loading)." if not net else " with a net."))
            rider = None
            if net:                                             # PHB: no damage; a Large or smaller creature is restrained
                atk["parts"] = []
                if self._size_of(tgt) in ("Tiny", "Small", "Medium", "Large"):
                    rider = {"conds": ["Restrained"], "escape": 10}
            fresh = not t.get("attacks")                    # this attack starts a new Attack action
            self._pay_attack(att, F.extra_attacks(char), w["name"])
            self._hurl_spend(att, w, atk)                       # a Hammer of Thunderbolts thrown: a charge (itemextras.py)
            if att.get("turn") is not None:
                att["turn"]["loaded_shot"] = loading or (att["turn"].get("loaded_shot", False) and not fresh)
            out = self._run_r(self._strike(att, self._feat_attack_label(atk, w["name"]), [tgt["id"]], mode="attack", atk=atk,
                                           magical=atk["magical"], rider=rider))
            self._commit()
            return out

    def offhand_attack(self, attacker_id: int, weapon: str, target_id: Optional[int] = None, adv: Optional[str] = None) -> str:
        """Two-weapon fighting: after attacking with a light melee weapon, a bonus-action attack with another light one
        (no ability modifier to the damage unless the Two-Weapon Fighting style)."""
        with self.lock:
            self._busy()
            att, tgt = self._find(attacker_id), self._target(target_id)
            char = self._sheet(att)
            if not char:
                raise ServiceError("Only characters fight with two weapons here.")
            low = weapon.strip().lower()
            w = next((a for a in char.attacks() if a["name"].lower() == low), None)
            dual = self._feat(att, "dual_wielder")
            if not w or w.get("ranged") or ("light" not in (w.get("props") or []) and not dual):
                raise ServiceError("The off-hand weapon must be a light melee weapon" + (" (or any one-handed melee weapon)" if dual else "") + ".")
            if self._economy_on() and not (att.get("turn") or {}).get("attacked"):
                raise ServiceError("Take the Attack action with a light weapon first.")
            atk = self._feat_attack(att, w, self._check_reach(att, tgt, self._weapon_atk(att, w)))
            if not char.has_option("Two-Weapon Fighting"):
                mod = char.mod(w.get("ability") or "str")
                if mod > 0:
                    d = atk["parts"][0][0]
                    atk["parts"] = [[re.sub(r"[+-]\d+$", "", str(d)) or "1", atk["parts"][0][1]]]
            atk["adv"] = adv
            self._pay(att, "bonus", f"off-hand {w['name']}")
            out = self._run_r(self._strike(att, f"{w['name']} (off-hand)", [tgt["id"]], mode="attack", atk=atk, magical=atk["magical"]))
            self._commit()
            return out

    # ------------------------------------------------------------------ monsters' stat block actions
    def _entry_section(self, c: dict, name: str):
        """(section, entry) of a stat block entry by name: actions / bonus_actions / reactions / legendary."""
        m = self._monster(c)
        for loose in (False, True):                          # then "Multiattack (Vampire Form Only)" for "Multiattack"
            for sec in ("actions", "bonus_actions", "reactions", "legendary"):
                for e in (m or {}).get(sec) or []:
                    n = e.get("name", "")
                    if (FORM_ONLY.sub("", n) if loose else n).lower() == name.lower():
                        return sec, e
        e = next((x for x in self._lair_actions(c) if x["name"].lower() == name.lower()), None)
        if not e:                                            # a Shapechanger trait used as its action (a vampire, a werewolf)
            t = next((x for x in (m or {}).get("traits") or [] if x.get("name", "").lower() == name.lower()
                      and self._SHAPE.search(x.get("text") or "") and re.search(r"(?:use|uses) its action", x.get("text") or "")), None)
            if t:
                return "actions", t
            r = next((x for x in (m or {}).get("traits") or [] if x.get("name", "").lower() == name.lower()
                      and re.match(r"As a bonus action, [\w' -]+? can enter a rage\b", x.get("text") or "")), None)
            return ("bonus_actions", r) if r else (None, None)         # Torogar's, a frost giant everlasting one's rage: a trait used as a bonus action
        return ("lair", e)

    def _in_multiattack(self, c: dict, base: str) -> bool:
        """An action the Multiattack names besides its attacks, still unused while the Multiattack's attacks are open."""
        t = c.get("turn") or {}
        if not self._economy_on() or t.get("multi", 0) <= 0 or base in (t.get("multi_extra") or []):
            return False
        _s, e = self._entry_section(c, "Multiattack")
        return bool(e) and bool(re.search(r"\buses? (?:its |their |his |her )?" + re.escape(base.lower()) + r"\b", e.get("text", "").lower()))

    def _multiattack_count(self, c: dict) -> int:
        _s, e = self._entry_section(c, "Multiattack")
        if not e:
            return 1
        t = e.get("text", "").lower()
        if "as many bite attacks as it has heads" in t:         # the hydra: five heads to start with
            return 5
        n = self._count_attacks(t)
        if n:
            return n
        m = re.search(r"makes (one|two|three|four|five|six|\d+) (?:[\w-]+ ){0,3}?attacks", t)
        if m:
            return WORDS.get(m.group(1), int(m.group(1)) if m.group(1).isdigit() else 2)
        n = sum(WORDS.get(x, 1) for x in re.findall(r"\b(one|two|three|four) (?:with|attack)", t))
        return max(2, n) if n else 2

    @staticmethod
    def _count_attacks(t: str) -> int:
        """Attacks a Multiattack text adds up to: "one Bite attack and two Claw attacks" 3, "two fist attacks or two javelin
        attacks" 2 (the larger choice, unless it has an "if"), "makes three attacks: one with its bite and two with its claws" 3,
        "uses Fear Gaze once and makes one oar attack" 1, "...If that attack hits, ... one beak attack" one more. 0: no idea."""
        num = r"(?<![+\w-])(one|two|three|four|five|six|\d+)"
        best = more = 0
        for sent in re.split(r"(?<=[.;])\s+", re.sub(r"\s+", " ", t)):
            cond = re.match(r"(?:if|when|while)\b", sent)
            follow = re.match(r"if (?:that|this|the) attack hits", sent) or re.search(r"\balso\b", sent) and not cond
            if cond and not follow or not re.search(r"\bmakes?\b|attacks (?:twice|thrice)", sent):
                continue                                       # "It can replace one of those attacks with...": no more of them
            alts = []
            for j, alt in enumerate(re.split(r"(?:,? |—)or (?=(?:it )?(?:makes )?(?:up to )?(?:one|two|three|four|five|six|\d+)\b)", sent)):
                if j and re.search(r"\bif (?:it|its|the|he|she|they)\b", alt):
                    continue                                   # "or four claw attacks if it has fewer than half of its hit points"
                comb = re.search(r"makes? (?:any|a) combination of " + num + r"\b", alt) or \
                    (re.search(r"in any combination\.?\s*$", alt) and re.search(r"makes? " + num + r"\b", alt))     # "any combination of three Bite, ... attacks"
                if comb:
                    alts.append(WORDS.get(comb.group(1)) or int(comb.group(1)))
                    continue
                total = re.search(r"makes? (?:either )?" + num + r" (?:[\w-]+ ){0,2}?attacks\b", alt)
                if total and not re.search(r"\battack\b", alt[:total.start()]):    # "makes three attacks: one with its bite and..."
                    alts.append(WORDS.get(total.group(1)) or int(total.group(1)))
                    continue
                n = sum(WORDS.get(g, 0) or (int(g) if g.isdigit() else 0)
                        for g in re.findall(r"\b" + num + r" (?:[\w'+-]+ ){0,4}?(?:attacks?|strikes?)\b", alt))
                n += len(re.findall(r"\b(?:makes?|and) an? (?:[\w'+-]+ ){0,2}?attack\b", alt))
                n += 2 * len(re.findall(r"attacks twice", alt)) + 3 * len(re.findall(r"attacks thrice", alt))
                if n:
                    alts.append(n)
            if follow:
                more += max(alts) if alts else 0               # "If that attack hits, ... can make one beak attack"
            else:
                best = max([best] + alts)                      # "Or it makes two ranged attacks", "In hybrid form...": a choice
        return best + more if best else 0

    @staticmethod
    def _clean_attack_text(text: str) -> str:
        """Drop alternative damage ('or 8 (1d10 + 3) slashing damage if used with two hands') so it isn't added."""
        text = re.sub(r",?\s+or\s+\d+\s*\([^)]*\)\s*\w+\s+damage\s+plus\s+\d+\s*\([^)]*\)\s*\w+\s+damage\s+(?:if|while|when|in|with)[^.,]*", "", text)
        return re.sub(r",?\s+or\s+\d+\s*\([^)]*\)\s*\w+\s+damage\s+(?:if|while|when|in|with)[^.,]*", "", text)    # "... with shillelagh"; an eladrin's two-handed "plus 4 fire" too

    def _monster_strike(self, att: dict, tgt: dict, name: str, text: str, *, adv: Optional[str] = None, label: Optional[str] = None) -> dict:
        if self._fx(att, "enlarged"):                          # "or 11 (2d8 + 2) piercing damage while enlarged": that one now
            text = re.sub(r"\d+ \([^)]*\) (\w+) damage,? or (\d+ \([^)]*\) \w+ damage) while enlarged", r"\2", text)
        if "Bloodied" in text:                                 # a swarm's lesser bite, a knight's extra necrotic damage, while at half its hit points or fewer
            blo = 0 < self._hp_of(att) <= self._max_hp(att) // 2
            dmg = r"(?:\d+ \([^)]*\)|\d+d\d+(?: ?[+-] ?\d+)?|\d+)"
            text = re.sub(r"(%s \w+ damage),? or (%s \w+ damage) if (?:the|it) [\w ]+? is Bloodied" % (dmg, dmg),
                          lambda g: g.group(2) if blo else g.group(1), text)
            text = re.sub(r"—plus (%s \w+ damage) if (?:the|it) [\w ]+? is Bloodied—?" % dmg, (r" plus \1 " if blo else " "), text)
        text = self._clean_attack_text(text)
        alt = re.search(r"((?:\d+ \([^)]*\)|\d+) \w+ damage) in ([\w ]+?) forms?,? or ((?:\d+ \([^)]*\)|\d+) \w+ damage) in ([\w ]+?) forms?", text)
        if alt:                                                # "1 piercing damage in raven form, or 4 (1d4 + 2) piercing damage in hybrid form"
            mine = (att.get("shape") or "").lower() or next(iter(self._true_forms(att)), "")
            keep = alt.group(1) if mine and mine in alt.group(2).lower() else alt.group(3)
            text = text[:alt.start()] + keep + text[alt.end():]
        pre, post, save = CR.split_save(text)
        hit = re.search(r"([+-]\d+) to hit", pre)
        reach = re.search(r"reach (\d+) ft", pre)
        conjured = None if reach else re.search(r"within (\d+) feet of (?:itself|it)\b.*?melee spell attack", pre, re.I | re.S)
        rng = re.search(r"range (\d+)(?:/(\d+))? ft", pre)
        melee_kw = re.search(r"Melee", pre, re.I)
        atk = {"bonus": int(hit.group(1)) if hit else 0, "n": 1, "weapon": bool(re.search(r"Weapon Attack", pre, re.I)), "adv": adv,
               "melee": bool(melee_kw), "reach": max(5, int(reach.group(1))) if reach else    # a swarm's "reach 0 ft.": the next tile
               (int(conjured.group(1)) + 5 if conjured else 5),                     # a conjured blade (Spectral Dagger) strikes where it floats
               "normal": int(rng.group(1)) if rng else None, "long": int(rng.group(2) or rng.group(1)) if rng else None,
               "parts": [list(p) for p in self._hit_parts(att, tgt, pre)], "magical": bool(self._fx(att, "magic_attacks")) or "magical" in pre.lower() or bool((att.get("summon") or {}).get("magic")),
               "str_based": True}
        atk["adv_parts"] = [list(p) for p in getattr(self, "_adv_parts", [])]
        self._adv_parts = []
        wide = re.search(r"scores a critical hit on a roll of (\d+)", text)
        if wide:                                               # a gashadokuro's Head Bite: "on a roll of 18-20"
            atk["crit_at"] = int(wide.group(1))
        if melee_kw and rng and att.get("pos") and tgt.get("pos") and self._dist(att, tgt) > atk["reach"]:
            atk["melee"] = False
        rider = None
        on_hit = pre.split("Hit:", 1)[1] if "Hit:" in pre else pre     # not the targeting line ("a creature grappled by the vampire")
        if re.search(r"\bswallow|\btrapped (?:inside|in this way)", on_hit):     # "A swallowed creature is blinded and restrained": the Swallowed effect's
            on_hit = " ".join(s for s in re.split(r"(?<=\.)\s+", on_hit) if not re.search(r"\bswallow|\btrapped (?:inside|in this way)", s))
        grab = [c for c in CR.conditions_in(on_hit) if c in ("Grappled", "Restrained", "Prone")]
        cap = re.search(r"\b(Tiny|Small|Medium|Large|Huge) or smaller\b[^.]*?\b(?:grappled|prone|restrained)\b|\b(?:grappled|prone|restrained)\b[^.]*?"
                        r"\b(Tiny|Small|Medium|Large|Huge) or smaller\b", on_hit, re.I)
        if grab and cap and SIZES.index(self._size_of(tgt)) > SIZES.index((cap.group(1) or cap.group(2)).capitalize()):
            grab = []                                          # "If the target is Medium or smaller, it is grappled": too big
        keep = " ".join(s for s in re.split(r"(?<=\.)\s+", on_hit) if not re.match(r"(?:If|While|When|Whenever|A creature that|Any creature that)\b", s)
                        or re.match(r"If the target is (?:a |an )?(?:(?:Tiny|Small|Medium|Large|Huge) or smaller )?creature,", s)
                        or re.match(r"While (?:the|that) (?:creature|target) is cursed,", s))      # a jade statue's curse
        opt = re.search(r"Once on each of (?:his|her|its|their) turns,[^.]*?\bcan (?:also )?cause[^.]*\.\s+If (?:he|she|it|they) does so, ([^.]*\.)", on_hit)
        if opt:                                                # Strongheart's gleam: the foe is blinded, once on each of his turns (gated at the hit)
            keep = (keep + " " + opt.group(1)).strip()
        plain = [c for c in CR.conditions_in(keep) if c not in ("Grappled", "Restrained", "Prone")]
        hmods = CR.text_mods(keep)                           # "it has disadvantage on attack rolls until the start of its next turn"
        esc = re.search(r"escape DC (\d+)|DC (\d+) Strength check", on_hit)    # a grapple's escape, a net's Strength check
        if save:
            rider = {"ab": save[0], "dc": save[1], "parts": CR.save_damage(post), "half": "half as much" in post.lower(),
                     **self._save_terms(post)}
            if re.search(r"can't regain hit points", post):        # mummy rot and its kin: a curse that stops healing
                rider["mods"] = {"no_heal": True}
            if grab:                                                # the mind flayer's tentacles: grappled, and a save against the stun
                rider.update(grab=grab, escape=int(esc.group(1) or esc.group(2)) if esc else None,
                             with_grapple=bool(re.search(r"until (?:this|the) grapple ends", post)))
        elif grab:
            rider = {"conds": grab, "escape": int(esc.group(1) or esc.group(2)) if esc else None}
        lead = re.split(r"(?<=[.:])\s+", pre.strip())[-1] if save else ""
        sz = re.search(r"\b(Tiny|Small|Medium|Large|Huge) or smaller\b", lead, re.I)
        if rider and rider.get("ab") and sz and SIZES.index(self._size_of(tgt)) > SIZES.index(sz.group(1).capitalize()):
            rider = None                                       # "If the target is Large or smaller, it must succeed...": too big for it
        if rider and rider.get("ab") and re.search(r"\b(?:after|for) (?:\d+|an?) (?:hour|day)s?\b|\bwhen the (?:hour|day) ends\b", lead, re.I):
            rider = None                                       # "If the target remains Poisoned in this way after 1 hour, it must make a DC 11...": not now
        tm = re.match(r"If the target is (?:a |an )?(aberration|beast|celestial|construct|dragon|elemental|fey|fiend|giant|humanoid|monstrosity|ooze|plant|undead)\b",
                      lead, re.I)
        if rider and rider.get("ab") and tm:                   # "If the target is a Humanoid, it must succeed ... or be cursed": a beast shrugs it off
            kind = "humanoid" if self._sheet(tgt) and not tgt.get("form") else str((self._monster(tgt) or {}).get("type") or "").lower()
            if tm.group(1).lower() not in kind:
                rider = None
        if rider and rider.get("ab") and re.search(r"critical hit", lead, re.I):
            rider["crit_only"] = True                          # the dullahan's beheading: "If the dullahan scores a critical hit..., the target must succeed"
        if rider and rider.get("ab") and re.search(r"\bwas invisible before (?:it|he|she) attacked", lead) and "Invisible" not in self._conds(att) \
                and not self._fx(att, "invisible"):
            rider = None                                       # a grinning cat's Claws: the Strength save only when it struck from unseen
        if rider and rider.get("ab") and re.search(r"move \d+ rounds? forward in time", post):      # a githzerai's Temporal Strike, like Temporal Shunt
            rider.update(conds=["Incapacitated"], mods={"banished": True, "untargetable": True}, until="target_start", rounds=None, repeat=None,
                         note="vanishes for a round")
        if rider and rider.get("ab") and re.search(r"can be freed if the [\w ]+ is destroyed", post):
            ac = re.search(r"object with AC (\d+)", post)      # Flesh Entomb: no repeated save; breaking out is a Strength check against the flesh's AC
            rider.update(repeat=None, escape=int(ac.group(1)) if ac else 10, mods={"entombed": True})
        prev = (re.split(r"(?<=[.:])\s+", pre.strip()) + [""])[-3] if save and len(re.split(r"(?<=[.:])\s+", pre.strip())) > 1 else ""
        run = RUN_HIT_RE.search(lead) or re.match(r"If the target is", lead) and RUN_HIT_RE.search(prev)
        if rider and rider.get("ab") and run and not self._charged(att, tgt, int(run.group(1))):
            rider = None                                       # the charge's shove: only after the run up
        S = self._strike(att, label or name, [tgt["id"]], mode="attack", atk=atk, rider=rider, magical=atk["magical"])
        if plain or hmods:                                     # no save: "the creature is poisoned until the start of the troll's next turn"
            tied = bool(re.search(r"until (?:this|the) grapple ends", on_hit, re.I))
            until = CR.until_of(on_hit)
            S["on_hit"] = {"name": label or name, "conds": plain, "until": self._until(until, att, tgt) if until else None,
                           "rounds": None if until or tied else (CR.duration_rounds(keep) or 10),
                           "mods": dict(hmods, **({"with_grapple": att["id"]} if tied else {})) or None}
            if opt:
                S["on_hit"]["once"] = f"opt_rider:{name}"       # "once on each of his turns": the first hit that lands
        cling = re.search(r"(?:If (?:the target is (Tiny|Small|Medium|Large|Huge) or smaller and )?(?:the [\w ]+ )?ha[sd] advantage (?:on the attack roll|against "
                          r"the target)[^.]*?attaches[^.]*?(?:the target is (?:also )?blinded))", on_hit)
        if cling and not S.get("on_hit") and not (cling.group(1) and SIZES.index(self._size_of(tgt)) > SIZES.index(cling.group(1))):
            esc2 = re.search(r"detach [^.]*?DC (\d+) Strength check", text)    # a darkmantle, a cloaker: over the head, with advantage
            S["on_hit"] = {"name": f"{att['name']} attached", "conds": ["Blinded"], "need_adv": True, "rounds": None,
                           "mods": {"attached": att["id"], "escape_dc": int(esc2.group(1)) if esc2 else None}}
        S["stat_extra"] = self._stat_extra(text)               # a drain, a push, a swallow...
        if rider and rider.get("ab") and (S["stat_extra"] or {}).get("swallow"):
            rider.update(conds=[], fail5=[], rounds=None)      # blinded and restrained come with the Swallowed effect
        return S

    @staticmethod
    def _breath_options(text: str) -> list:
        """[(name, text)] of a metallic or gem dragon's "uses one of the following breath weapons" (Fire Breath, Sleep Breath...),
        or a draugr's "uses one of the following shouts", one entry per bullet; [] for anything else."""
        if not re.search(r"uses? one of the following (?:breath weapons|shouts)", text or "", re.I):
            return []
        out = []
        for part in re.split(r"\n+\s*[^\w\s]\s*", text)[1:]:
            g = re.match(r"(.{1,40}?) (?=The \w+ )", part.strip(), re.S) or \
                re.match(r"((?:[\w'-]+ ){0,3}?(?:Breath|Weapon)) (?=[A-Z][\w'’-]+(?: [A-Z][\w'’-]+){0,2} (?:exhales|breathes|spits|releases|emits|expels|belches)\b)",
                         part.strip(), re.S)         # a named dragon's: "Acid Breath Burney exhales acid in a 90-foot line"
            if g:
                out.append((g.group(1).strip(), part.strip()[g.end():]))
        return out

    def _action_area(self, text: str) -> Optional[dict]:
        t = text.lower()
        m = re.search(r"(\d+)-foot cone", t)
        if m:
            return {"shape": "cone", "size": int(m.group(1)), "origin": "caster"}
        m = re.search(r"(\d+)-foot line that is (\d+) feet wide", t)
        if m:
            return {"shape": "line", "size": int(m.group(1)), "width": int(m.group(2)), "origin": "caster"}
        m = re.search(r"(\d+)-foot-radius sphere centered on a point", t)
        if m:
            return {"shape": "sphere", "size": int(m.group(1)), "origin": "point"}
        m = re.search(r"(\d+)-foot-radius (?!around)", t)
        if m and re.search(r"\ba point\b", t):                # a lair's geyser "from a point ... 5-foot-radius"
            return {"shape": "sphere", "size": int(m.group(1)), "origin": "point"}
        m = re.search(r"each creature of (?:the [\w ]+?|its)'?s? choice (?:that is |that's )?within (\d+) (?:feet|foot) of (?:it|the [\w ]+?|itself)\b", t)
        if m:                                                 # Frightful Presence: everyone it picks around it (its foes)
            return {"shape": "emanation", "size": int(m.group(1)), "origin": "caster", "choice": True}
        m = re.search(r"each (?:other )?creature (?:with)?in (\d+) (?:feet|foot) of (?:it|the \w+|itself)", t)
        if m:
            return {"shape": "emanation", "size": int(m.group(1)), "origin": "caster"}
        m = re.search(r"(\d+)-foot (?:radius|emanation)", t)
        if m and "each creature" in t:
            return {"shape": "emanation", "size": int(m.group(1)), "origin": "caster"}
        m = re.search(r"line that is (\d+) feet long and (\d+) feet wide|(\d+)-foot-wide, (\d+)-foot line", t)
        if m:                                                 # the ankheg's Acid Spray
            return {"shape": "line", "size": int(m.group(1) or m.group(4)), "width": int(m.group(2) or m.group(3)), "origin": "caster"}
        m = re.search(r"(\d+)-foot cube", t)
        if m and re.search(r"each creature in (?:that|the|a)", t):    # the bard's Cacophony, a maw demon's Disgorge
            return {"shape": "cube", "size": int(m.group(1)), "origin": "caster"}
        m = re.search(r"(\d+)-foot[- ]radius (?:sphere )?(?:centered on (?:itself|it|him|her)\b|of [\w ,-]+? extends|extends)", t)
        if m and re.search(r"each (?:other )?creature|any creature|a creature", t):   # a dretch's Fetid Cloud, a warbler's Calming Mist
            return {"shape": "emanation", "size": int(m.group(1)), "origin": "caster"}
        m = re.search(r"each (?:other )?creature [^.]{0,40}?within (\d+) (?:feet|foot) of (?:it|itself|the [\w -]+?)\b(?<!the target)", t)
        if m:                                                 # "Each creature in contact with the ground within 15 feet of the scout"
            return {"shape": "emanation", "size": int(m.group(1)), "origin": "caster"}
        m = re.search(r"\bcreatures within (\d+) feet that can see (?:it|him|her|itself)\b", t)
        if m:                                                 # Baalzebul's Heart of Pestilence: the foes around it that see it
            return {"shape": "emanation", "size": int(m.group(1)), "origin": "caster", "choice": True}
        m = re.search(r"\beach creature within (\d+) (?:feet|foot) of [\w' ,-]{1,30}? takes? \d", t)
        if m:                                                 # Auril's Ice Flurry, Yan-C-Bin's Peal of Thunder: named, no roll
            return {"shape": "emanation", "size": int(m.group(1)), "origin": "caster"}
        return None

    def use_action(self, attacker_id: int, name: str, text: str, adv: Optional[str] = None, target_id: Optional[int] = None,
                   targets: Optional[List[int]] = None, point=None, option: Optional[str] = None) -> str:
        """A creature's stat block entry used now: what it costs (action, bonus action, reaction, legendary action,
        Multiattack's attacks, a recharge), then its attack, saving throw or area played out."""
        with self.lock:
            self._busy()
            att = self._find(attacker_id)
            sec, entry = self._entry_section(att, name)
            if entry and not self._form_ok(att, entry.get("name", "")):
                raise ServiceError(f"{att['name']} isn't in a form that can use {entry['name']} (now: {(att.get('shape') or 'its true').lower()} form).")
            base = FORM_ONLY.sub("", re.sub(r"\s*\((?:Recharge|\d+/Day|Costs)[^)]*\)", "", name)).strip()
            recharge = re.search(r"\(Recharge\s*(\d)", name, re.I)
            per_day = re.search(r"\((\d+)/Day", name, re.I)
            if not per_day and re.search(r"\(Recharges? after", name, re.I):
                per_day = re.match(r"(1)", "1")                 # "Recharges after a Short or Long Rest": once this fight
            spent = att.setdefault("spent", {})
            if recharge and spent.get(base):
                raise ServiceError(f"{base} hasn't recharged yet.")
            if per_day and (att.get("uses_day") or {}).get(base, 0) >= int(per_day.group(1)) and not (att.get("shape") and self._SHAPE.search(text)):
                raise ServiceError(f"{base} has no uses left today.")
            if re.match(r"While (?:it is )?bloodied, ", text, re.I) and not 0 < self._hp_of(att) <= self._max_hp(att) // 2:
                raise ServiceError(f"{att['name']} can use {base} only while bloodied.")     # a spriggan's Fade and Mend
            mx = re.match(r"The [\w' -]+? uses Multiattack\.\s+Each attack that hits deals an extra (?:\d+ \()?(\d+d\d+(?: ?[+-] ?\d+)?)\)? (\w+) damage", text)
            if mx and sec == "actions" and self._entry_section(att, "Multiattack")[1]:      # a myrmidon's Fiery Strikes: the Multiattack, each hit hotter
                self._mark_used(att, base, recharge, per_day)
                self._effect_on(att, base, [], None, None, None, 1, att["name"], {"dmg": (mx.group(1).replace(" ", ""), mx.group(2).lower()), "any_attack": True},
                                None, att["id"], until={"end": att["id"], "skip": 0})
                multi = self._entry_section(att, "Multiattack")[1]
                return self.use_action(attacker_id, multi.get("name") or "Multiattack", multi.get("text") or "")
            if base.lower() == "multiattack":
                self._pay(att, "action", "Multiattack")
                n = self._multiattack_count(att)
                if att.get("turn") is not None and self._economy_on():
                    att["turn"]["multi"] = n
                self._vfx("multi", id=att["id"], n=n)              # "×3" over it: the attacks to come
                self._commit(f"{att['name']} uses Multiattack ({n} attacks)")
                return f"{att['name']} uses Multiattack: {n} attacks"
            mv = self._move_attack(att, text) if sec in ("actions", "bonus_actions", "legendary") else None
            if mv:                                              # "moves up to its speed and makes one Gore attack": the walk, then the attack
                return self._move_attack_do(att, base, sec, name, mv, point, target_id or (targets or [None])[0], recharge, per_day)
            ref = self._referenced_action(att, base, text) if sec not in (None, "actions") or (
                sec == "actions" and not base.lower().startswith("multiattack") and self._SELF_REF.match(text)) else None
            if ref:                                             # "The dragon makes a tail attack": that attack, for this cost
                rbase = re.sub(r"\s*\((?:Recharge|\d+/Day|Costs)[^)]*\)", "", ref["name"]).strip()
                if re.search(r"\brecharges (?:its |her |his |their )?[A-Z][\w' -]+? and uses it", text):
                    spent.pop(rbase, None)                      # "recharges its Mind Blast and uses it"
                if re.search(r"\(Recharge", ref["name"], re.I) and spent.get(rbase):
                    raise ServiceError(f"{rbase} hasn't recharged yet.")
                curse = self._USES_BUT.match(text)
                tail = text[curse.end():] if curse else ""
                text = ref["text"]
                if curse:                                       # "uses Evil Eye, but on a failed save, the creature is also cursed ...": its save, then the curse
                    text = text.rstrip() + " On a failed save, " + tail
            text = re.sub(r"(\d+ \(\d+d\d+(?: ?[+-] ?\d+)?\)) damage of a type (?:chosen by|of) [^:.]*?: (acid|cold|fire|lightning|poison|"
                          r"necrotic|radiant|thunder|psychic|force)\b", r"\1 \2 damage", text)    # a dracohydra's breath: its first type
            text = re.sub(r"\n[^\n]*\bdrops? to 0 hit points and doesn't die outright[^\n]*", "", text)    # Minsc's fury: a survival save, not an attack
            bopts = self._breath_options(text)
            if bopts:                                           # a gold dragon's Fire Breath or Weakening Breath: the one picked (the first)
                text = next((t for lbl, t in bopts if lbl.lower() == str(option or "").lower()), bopts[0][1])
            rays = self._eye_rays(att, text)
            if rays:                                            # a gazer's, a spectator's, a beholder's eye rays: some at random
                return self._shoot_rays(att, base, sec, name, rays, target_id, targets, recharge, per_day)
            hit = re.search(r"([+-]\d+) to hit", text)
            cost = {"bonus_actions": "bonus", "reactions": "reaction"}.get(sec, "action")
            if sec == "legendary":
                c2 = re.search(r"Costs (\d) Actions", name, re.I)
                cost = f"legendary:{c2.group(1) if c2 else 1}"
            elif sec == "lair":
                why = self._lair_why(att, entry["name"])
                if why:
                    raise ServiceError(why)
                cost = "free"
                lsp = self._lair_spells(att, text)
                if lsp:                                         # "The morkoth casts darkness, dispel magic, or misty step": one of them
                    pick = next((x for x in lsp if x.lower() == str(option or "").lower()), lsp[0])
                    return self.lair_cast(attacker_id, entry["name"], pick, adv, target_id, targets=targets, point=point)
            elif sec in (None, "actions") and hit and not ref and self._entry_section(att, "Multiattack")[1]:
                cost = "multi"
            elif sec in (None, "actions") and self._in_multiattack(att, base):
                cost = "free"                                   # "can use its Frightful Presence. It then makes three attacks"
                att["turn"].setdefault("multi_extra", []).append(base)
            if not hit:
                engulfed = self._engulf(att, base, text, target_id or (targets or [None])[0], cost, recharge, per_day)
                if engulfed:
                    return engulfed
            area = self._action_area(text) if not hit else None
            pre, post, save = CR.split_save(text)
            if area and save:
                if not att.get("pos"):
                    raise ServiceError("Put the creature on the map to aim an area.")
                aim = point or self.b.get("aim")
                ids = targets or ([target_id] if target_id else list(self.b.get("targets") or []))
                if aim is None and ids:
                    t = self._find(ids[0])
                    aim = list(G.centre(t["pos"], t.get("span") or 1)) if t.get("pos") else None
                tiles = G.area_for(area, att["pos"], att.get("span") or 1, tuple(aim) if aim else None, *self._bounds())
                tiles = V.filter_area(self._terrain(), G.centre(att["pos"], att.get("span") or 1), tiles)
                shrug = f"{att['id']}:{base}"                   # saved against its Frightful Presence: immune for a day
                hit_ids = [c["id"] for c in G.creatures_in(tiles, self.b["combatants"]) if c is not att and not self._is_out(c)
                           and (not area.get("choice") or self._hostile(c, att))
                           and not any((e.get("mods") or {}).get("immune_action") == shrug for e in c.get("effects") or [])]
                if area.get("shape") in ("cone", "line"):            # a breath: it draws in first (the telegraph)
                    self._vfx("inhale", id=att["id"], at=list(aim) if aim else None,
                              dtype=next((str(t).lower() for _d, t in CR.damage_parts(post) or CR.damage_parts(text) or [] if t), ""))
                self._area_vfx(att, tiles, CR.damage_parts(post) or CR.damage_parts(text), area.get("shape", ""), aim)
                self._pay(att, cost, base)
                self._mark_used(att, base, recharge, per_day)
                sv = {"ab": save[0], "dc": save[1], "half": "half as much" in post.lower(), **self._save_terms(post)}
                if re.search(r"is immune to [^.]*?for the next 24 hours", post):
                    sv["on_save"] = {"mods": {"immune_action": shrug}}
                S = self._strike(att, base, hit_ids, mode="save", sv=sv, parts=CR.save_damage(post) or CR.damage_parts(text),
                                 magical=True, origin=list(G.centre(att["pos"], att.get("span") or 1)))
                S["stat_extra"] = self._stat_extra(text)       # pushed away from it, its drain...
                two = re.search(r"followed by a DC (\d+) (Strength|Dexterity|Constitution|Intelligence|Wisdom|Charisma) saving throw", post)
                if two:                                        # Heart of Pestilence: a second save for the same creatures, its own effect
                    S["follow"] = S.get("follow", []) + [self._strike(
                        att, f"{base} ({two.group(2)})", hit_ids, mode="save", magical=True, parts=[],
                        sv={"ab": CR.ABILITIES[two.group(2).lower()], "dc": int(two.group(1)), "half": False, "conds": [], "repeat": None,
                            "rounds": CR.duration_rounds(post) or 10, "note": "weakened: half damage on melee attacks",
                            "mods": {"enfeebled": True} if re.search(r"half damage on melee attacks", post) else None},
                        origin=list(G.centre(att["pos"], att.get("span") or 1)))]
                if self._MOVE_AFTER.search(text) and att.get("pos"):     # Wing Attack: "can then fly up to half its flying speed"
                    att["leg_move"] = {"feet": self._move_feet(att, text), "name": base, "free": bool(self._NO_OA.search(text))}
                if not hit_ids:
                    self._commit(f"{att['name']} uses {base}: nobody in the area")
                    return f"{att['name']} uses {base}: nobody in the area"
                out = self._run_r(S)
                self._commit()
                return out
            if area and not hit and not save and CR.damage_parts(text, now_only=True):     # a pulse of damage around it, no roll (Peal of Thunder)
                if not att.get("pos"):
                    raise ServiceError("Put the creature on the map to aim an area.")
                aim = point or self.b.get("aim")
                tiles = G.area_for(area, att["pos"], att.get("span") or 1, tuple(aim) if aim else None, *self._bounds())
                tiles = V.filter_area(self._terrain(), G.centre(att["pos"], att.get("span") or 1), tiles)
                hit_ids = [c["id"] for c in G.creatures_in(tiles, self.b["combatants"]) if c is not att and not self._is_out(c)
                           and (not area.get("choice") or self._hostile(c, att))]
                self._area_vfx(att, tiles, CR.damage_parts(text), area.get("shape", ""), aim)
                self._pay(att, cost, base)
                self._mark_used(att, base, recharge, per_day)
                if not hit_ids:
                    self._commit(f"{att['name']} uses {base}: nobody in the area")
                    return f"{att['name']} uses {base}: nobody in the area"
                S = self._strike(att, base, hit_ids, mode="auto", parts=CR.damage_parts(text, now_only=True), magical=True,
                                 origin=list(G.centre(att["pos"], att.get("span") or 1)))
                S["stat_extra"] = self._stat_extra(text)
                out = self._run_r(S)
                self._commit()
                return out
            if not hit and not save and not area and self._PULSE.search(text):      # an elder brain's Psychic Pulse: the creature and the foes around it
                centre = self._target(target_id)
                lk = self._LINKED.search(text)
                if lk and att.get("pos") and centre.get("pos") and self._dist(att, centre) > int(lk.group(1)):
                    raise ServiceError(f"{centre['name']} is too far away ({lk.group(1)} ft).")
                ids = self._pulse_targets(att, centre, text)
                self._pay(att, cost, base)
                self._mark_used(att, base, recharge, per_day)
                if not ids:
                    self._commit(f"{att['name']} uses {base}: nobody hurt")
                    return f"{att['name']} uses {base}: nobody hurt"
                S = self._strike(att, base, ids, mode="auto", parts=CR.damage_parts(text, now_only=True), magical=True)
                out = self._run_r(S)
                self._commit()
                return out
            if not hit and not save and not area and self._LINKED.search(text):     # an elder brain's Break Concentration, Sever Psychic Link
                tgt = self._target(target_id)
                if att.get("pos") and tgt.get("pos") and self._dist(att, tgt) > int(self._LINKED.search(text).group(1)):
                    raise ServiceError(f"{tgt['name']} is too far away ({self._LINKED.search(text).group(1)} ft).")
                self._pay(att, cost, base)
                self._mark_used(att, base, recharge, per_day)
                bits = []
                if re.search(r"breaks the creature's concentration", text):
                    st = tgt.get("concentrating")
                    lvl = int((rules.spell(st["spell"]) or {}).get("level") or 0) if st else 0
                    dm = re.search(r"(\d+d\d+)\)? psychic damage per level", text)
                    if st:
                        self._drop_conc(tgt, f"{att['name']} broke it")
                        bits.append(f"{tgt['name']}'s concentration on {st['spell']} breaks")
                    else:
                        bits.append(f"{tgt['name']} isn't concentrating")
                    if dm and lvl:
                        dice = dm.group(1).split("d")
                        bits.append(self._deal(tgt, [[f"{int(dice[0]) * lvl}d{dice[1]}", "psychic"]], by=att, label=base))
                mods = CR.text_mods(text) if re.search(r"\bends the link\b", text) else {}
                if mods:
                    until = "target_end_next" if re.search(r"until the end of the creature's next turn", text) else CR.until_of(text)
                    self._effect_on(tgt, base, [], None, None, None, None if until else 10, att["name"], mods, None, att["id"],
                                    until=self._until(until, att, tgt) if until else None)
                    bits.append(f"{tgt['name']} has disadvantage on checks, attacks and saves until the end of its next turn")
                line = f"{att['name']} uses {base} on {tgt['name']}" + (": " + "; ".join(bits) if bits else "")
                self._commit(line)
                return line
            held = self._held_targets(att, text, target_id, targets) if not hit and not save and not area else None
            if held:                                            # "One creature the aboleth has charmed takes 10 psychic damage", a crush on what it grapples
                self._pay(att, cost, base)
                self._mark_used(att, base, recharge, per_day)
                S = self._strike(att, base, held, mode="auto", parts=CR.damage_parts(self._clean_attack_text(text), now_only=True) or
                                 CR.damage_parts(text, now_only=True), magical=True)      # not a tick's "or 17 (4d6 + 3) if a Giant" too
                S["stat_extra"] = self._stat_extra(text)
                out = self._run_r(S)
                self._commit()
                return out
            if not hit and not save and (not CR.damage_parts(text) or re.search(r"attempts to (?:magically )?summon", text)):
                if self._INVIS.search(text) and "Invisible" in (att.get("conditions") or []):
                    raise ServiceError(f"{att['name']} is already invisible.")
                plan = self._utility_plan(att, text, target_id or (targets or [None])[0], point, option)   # a teleport, a heal, a summons
                self._pay(att, cost, base)
                if not (plan and plan["kind"] == "shape" and plan["to"] is None):    # changing back costs no use
                    self._mark_used(att, base, recharge, per_day)
                if plan:
                    line = self._utility_do(att, base, plan)
                    if plan["kind"] == "heal" and self._INVIS.search(text):    # a spriggan's Fade and Mend: it heals and vanishes
                        until = CR.until_of(text)
                        self._effect_on(att, base, ["Invisible"], None, None, None, None if until else CR.duration_rounds(text) or 1, att["name"],
                                        {"ends_on": ["attack", "cast"]}, None, att["id"], until=self._until(until, att, att) if until else None)
                        line += f"; {att['name']} turns invisible"
                    self._commit(line)
                    return line
                if self._INVIS.search(text):                    # a quasit's, an imp's, a will-o'-wisp's Invisibility; a shadow's Cloak of Shadows
                    self._effect_on(att, base, ["Invisible"], None, None, None, CR.duration_rounds(text) or None, att["name"],
                                    {"ends_on": ["attack", "cast"]}, None, att["id"])
                    self._commit(f"{att['name']} turns invisible")
                    return f"{att['name']} turns invisible"
                tid = target_id or self.b.get("target")
                who = self._find_or_none(tid)
                line = f"{att['name']} uses {base}" + (f" on {who['name']}" if who else "")
                self._commit(line)
                return line
            tgt = self._target(target_id)
            why = self._target_rule(att, tgt, text)
            if why:
                raise ServiceError(why)
            if hit:
                S = self._monster_strike(att, tgt, base, text, adv=adv)
                if ref and ref.get("n", 1) > 1:
                    S["atk"]["n"] = ref["n"]                    # "makes two claw attacks"
                if att.get("pos") and tgt.get("pos"):
                    S["atk"] = self._check_reach(att, tgt, S["atk"])
            else:
                swallow = self._swallow_bite(att, tgt, text)    # a behir's Swallow: its save is the later regurgitation's, the bite comes first
                sv = {"ab": save[0], "dc": save[1], "half": "half as much" in post.lower(), **self._save_terms(post)} if save and not swallow else None
                if sv:
                    many = re.search(r"(?:chooses|targets) up to (two|three|four|five|six) (?:creatures|targets)", text)
                    ids = [tgt["id"]] + [t for t in (targets or [])[1:WORDS[many.group(1)]] if t != tgt["id"]] if many else [tgt["id"]]
                    S = self._strike(att, base, ids, mode="save", sv=sv, parts=CR.save_damage(post), magical=True)
                    S["stat_extra"] = self._stat_extra(text)
                    if ((S["stat_extra"] or {}).get("ability") or {}).get("stun"):   # stunned only when the 3d6 take its Intelligence
                        sv["conds"] = [x for x in sv.get("conds") or [] if x != "Stunned"]
                    lead = re.search(r"takes (?:\d+ \()?(\d+d\d+(?: ?[+-] ?\d+)?)\)? (\w+) damage,? and (?:it |the target |the creature )?must (?:succeed on|make) an? $", pre)
                    if lead and not CR.save_damage(post) and lead.group(2).lower() in DTYPES:      # "The target takes 14 (4d6) psychic damage, and it must make a DC 16 Intelligence saving throw"
                        S = self._strike(att, base, ids, mode="auto", parts=[[lead.group(1).replace(" ", ""), lead.group(2).lower()]], magical=True,
                                         follow=[S])        # the damage comes first, then the save: Steal Memory, Glimpse the Temporal Flood
                elif swallow:                                   # a giant toad's, a behir's Swallow: one bite at what it holds
                    S = self._monster_strike(att, tgt, base, swallow["text"], adv=adv)
                    S["stat_extra"] = dict(S.get("stat_extra") or {}, **(self._stat_extra(text, gate="hit") or {}))
                    if att.get("pos") and tgt.get("pos"):
                        S["atk"] = self._check_reach(att, tgt, S["atk"])
                else:
                    if re.search(r"Attack: automatic hit", text) and att.get("pos") and tgt.get("pos"):   # the Marut's Unerring Slam
                        reach = re.search(r"reach (\d+) ft", text)
                        self._check_reach(att, tgt, {"melee": True, "reach": int(reach.group(1)) if reach else 5})
                    now = CR.damage_parts(self._clean_attack_text(text), now_only=True)    # not the "or 17 (4d6 + 3) ... if" variant
                    if not now:                                 # all its damage comes later (a giant toad's Swallow): say what it did
                        self._pay(att, cost, base)
                        self._mark_used(att, base, recharge, per_day)
                        line = f"{att['name']} uses {base} on {tgt['name']}"
                        self._commit(line)
                        return line
                    S = self._strike(att, base, [tgt["id"]], mode="auto", parts=now, magical=True)
                    S["stat_extra"] = self._stat_extra(text)   # a giant tick drinks what it dealt
            self._pay(att, cost, f"Attack: {base}" if re.search(r"Weapon Attack:", text) else base)    # a weapon attack: Haste allows it
            self._mark_used(att, base, recharge, per_day)
            out = self._run_r(S)
            self._commit()
            return out

    @staticmethod
    def _save_terms(post: str) -> dict:
        """What a stat block's saving throw does beyond damage: conditions (those for failing by 5 or more apart), when the
        target saves again, how long it lasts ("until the end of the mummy's next turn"), dropping to 0 hit points."""
        five, until = CR.fail_by_five(post), CR.until_of(post)
        if not until and re.search(r"until the (?:light|glow|song|sound) ends", post):
            until = "caster_end_next"                          # the flail snail's shell: its light lasts to its next turn's end
        main = CR.main_sentences(post)                         # not "If the worm takes 30 damage ... which fall prone"
        mods = CR.text_mods(main)
        conds = [x for x in CR.conditions_in(main) if x not in five]
        repeat, rounds = CR.repeat_save(post), None if until else CR.duration_rounds(post)
        if not (until or rounds or repeat) and set(conds) & LINGER and not re.search(r"until (?:this|the) grapple ends", post):
            rounds = 10                                        # no end given ("until the light ends"...): a minute, not for ever
        then, ends_by = None, bool(re.search(r"\buntil [\w' -]+? deals damage to it\b", post))
        nx = re.search(r"When the (\w+) ends, the (?:target|creature) (?:is|becomes) (\w+)(?: of [\w' -]+?)? for (\d+) (minute|round)s?", post)
        if nx and nx.group(2).capitalize() in CR.CONDITIONS and nx.group(2).capitalize() in conds:
            cond2 = nx.group(2).capitalize()                   # Sir Godfrey's glare: paralyzed first, frightened when that ends
            again = re.search(r"can repeat the saving throw at the end of each of its turns", post)
            then = {"name": cond2, "conds": [cond2], "repeat": "end" if again else None, "rounds": int(nx.group(3)) * (10 if nx.group(4) == "minute" else 1)}
            conds = [x for x in conds if x != cond2]
            repeat = None if again else repeat
        if re.search(r"has the Petrified condition instead of the Restrained condition", post):    # a medusa's gaze: restrained, a second failure turns it to stone
            conds, five, repeat, rounds, until, mods = ["Restrained"], [], "end", None, None, dict(mods or {}, stoning=True)
        return {"conds": conds, "fail5": five, "repeat": repeat, "rounds": rounds, "until": until, "mods": mods or None,
                "then": then, "ends_on_by": ends_by,
                "drop_to_0": bool(re.search(r"(?:saving throw[^.]*?\bor|on a fail(?:ure|ed save),(?: a creature| the target| it)?) drops? to 0 hit points",
                                            post, re.I))}                                # not "the possession lasts until the body drops to 0"

    @staticmethod
    def _stat_extra(text: str, gate: Optional[str] = None) -> Optional[dict]:
        """What a stat block hit or failed save does besides damage and conditions: the attacker drinks what it dealt
        ("regains hit points equal to that amount"), heals a set amount, cuts the target's hit point maximum, pushes or
        pulls it, swallows it, or hurts it each turn while the grapple lasts. Each comes with its gate: 'hit' or 'fail'
        (a failed save). `gate` forces one ("If the attack hits, the target is swallowed")."""
        pre, post, _save = CR.split_save(text)
        out = {}
        pieces = [(gate, text)] if gate else [("hit", pre.split("Hit:", 1)[1] if "Hit:" in pre else "" if _save or re.search(r"[+-]\d+ to hit", pre)
                                                   else pre), ("fail", post)]    # no roll at all (a giant tick's Blood Drain): it just happens
        for g, part in pieces:
            for sent in re.split(r"(?<=\.)\s+", part):
                low = sent.lower()
                if re.match(r"(?:if|while|when|whenever|each time|the target dies)\b", low) and not re.match(
                        r"if the target is (?:a |an )?(?:(?:tiny|small|medium|large|huge) or smaller )?creature\b|if the target is "
                        r"(?:tiny|small|medium|large|huge) or smaller|if the attack hits", low):
                    continue                                   # "If the target is wearing armor...": the board can't tell
                size = re.search(r"\b(tiny|small|medium|large|huge) or smaller\b", low)
                cap = size.group(1).capitalize() if size else None
                d = re.search(r"regains? (?:a number of )?hit points equal to (half )?(?:that amount|the (?:amount of )?(?:\w+ )?damage "
                              r"(?:dealt|taken)|the damage (?:the \w+ )?takes)|regains (half) as many hit points", low)
                if d and "drain" not in out:
                    typed = re.search(r"equal to (?:half )?the (?:amount of )?(\w+) damage", low)
                    out["drain"] = {"gate": g, "frac": .5 if (d.group(1) or d.group(2)) else 1.0,
                                    "type": typed.group(1) if typed and typed.group(1) in DTYPES else None}
                elif "heal" not in out:
                    h = re.search(r"\bregains? (\d+)(?: \((\d+d\d+(?: ?[+-] ?\d+)?)\))? hit points", sent)
                    if h and not re.search(r"\bthe target regains|\bit regains consciousness", low):
                        out["heal"] = {"gate": g, "dice": (h.group(2) or h.group(1)).replace(" ", "")}
                tp = re.search(r"\bgains? (?:(\d+)(?: \((\d+d\d+(?: ?[+-] ?\d+)?)\))? temporary hit points|temporary hit points equal to "
                               r"(half )?(?:the|that) (?:\w+ )?damage)", low)
                if tp and "temp" not in out and not re.search(r"\b(?:the target|each creature|allies)\b[^,.]*\bgains? ", low):
                    out["temp"] = {"gate": g, "dice": (tp.group(2) or tp.group(1) or "").replace(" ", ""),
                                   "frac": (.5 if tp.group(3) else 1.0) if not tp.group(1) else None}   # Drain Potential, Life Leech
                mx = re.search(r"(?:hit point maximum (?:is |is also )?reduced by|reduces? (?:its|the target's|their) hit point maximum by) (an amount equal to (?:half )?the (?:amount of )?(?:(\w+) )?damage "
                               r"(?:taken|dealt|it takes)|(\d+)(?: \((\d+d\d+(?: ?[+-] ?\d+)?)\))?)", low)
                if mx and "max_hp" not in out:
                    out["max_hp"] = {"gate": g, "dealt": bool(mx.group(1).startswith("an amount")), "half": "equal to half" in mx.group(1),
                                     "type": mx.group(2) if mx.group(2) in DTYPES else None,
                                     "dice": (mx.group(4) or mx.group(3) or "").replace(" ", ""),
                                     "temp_equal": bool(re.search(r"an equal number of temporary hit points", low))}   # the nabassu's gaze
                p = re.search(r"(?<!isn't )(?<!not )(?:pushed|push(?:es)? (?:the target|it|that creature)|moved) (?:horizontally )?(?:up to )?(\d+) (?:feet|ft)"
                              r"(?! in any direction)(?! toward)", low)    # a gazer's ray: "moved up to 30 feet directly away"
                if p and "push" not in out:
                    out["push"] = {"gate": g, "feet": int(p.group(1)), "cap": cap}
                p = re.search(r"(?<!isn't )(?<!not )(?:pulled|pulls (?:the target|it|that creature)) (?:up to )?(\d+) (?:feet|ft)", low) or \
                    re.search(r"(?<!isn't )(?<!not )pulled (?:in)?to (?:an unoccupied space )?within (\d+) feet of", low)
                if p and "pull" not in out:                    # a cave fisher's Filament: reeled in next to it
                    out["pull"] = {"gate": g, "feet": int(p.group(1)) if "within" not in p.group(0) else 120, "cap": cap}
                if re.search(r"\bswallowed\b|\bis trapped inside\b", low) and "swallow" not in out and not re.search(r"swallowed creature|while swallowed|"
                                                                                                r"is swallowed by|been swallowed", low[:40]):   # (a mantrap's jaws too)
                    out["swallow"] = {"gate": g, "cap": cap}
            sp = re.search(r"reduces (?:the target|a creature|it) to 0 hit points, (?:the target|that creature|it) is stable but poisoned for (\d+) (hour|minute)s?"
                           r"[^.]*paralyzed while poisoned", part)
            if sp and "stable_poison" not in out:              # a giant wolf spider's, a giant wasp's venom
                out["stable_poison"] = {"gate": g, "rounds": int(sp.group(1)) * (600 if sp.group(2) == "hour" else 10)}
            if re.search(r"\bor be possessed by\b|\bbe possessed by\b", part) and "possess" not in out:
                out["possess"] = {"gate": g}                   # a ghost: it vanishes into the body until the body drops
            ab = re.search(r"(strength|dexterity|constitution|intelligence|wisdom|charisma) score is reduced by (\d+d\d+|\d+)", part, re.I)
            if ab and "ability" not in out:                    # a shadow's Strength Drain
                out["ability"] = {"gate": g, "ab": CR.ABILITIES[ab.group(1).lower()], "dice": ab.group(2),
                                  "dies": bool(re.search(r"dies if this reduces its \w+ to 0", part))}
            ab = re.search(r"roll (\d+d\d+)[:.,]? if the total equals or exceeds the target's (\w+) score, that score is reduced to 0", part, re.I)
            if ab and "ability" not in out:                    # an intellect devourer's Devour Intellect
                out["ability"] = {"gate": g, "ab": CR.ABILITIES.get(ab.group(2).lower(), "int"), "zero_if": ab.group(1),
                                  "stun": bool(re.search(r"stunned until it regains", part))}
            dot = re.search(r"(?:(?:takes|taking) |Hit: )(?:\d+ \((\d+d\d+(?: ?[+-] ?\d+)?)\)|(\d+)) (\w+) damage at the start of each of "
                            r"(?:the )?([\w' -]+?)(?:'s?)? turns", ("Hit: " if g == "hit" else "") + part.strip())
            if dot and dot.group(3).lower() in DTYPES:
                spec = {"dice": (dot.group(1) or dot.group(2)).replace(" ", ""), "type": dot.group(3).lower(),
                        "when": "start" if dot.group(4).lower() in ("its", "their", "his", "her", "the target", "target") else "source_start"}
                if "swallow" in out and "dot" not in out["swallow"]:
                    out["swallow"]["dot"] = spec               # the acid inside the worm
                elif re.search(r"grapple ends", part) and g == "hit" and "grab_dot" not in out:
                    out["grab_dot"] = spec                     # "...at the start of each of its turns until the grapple ends"
                elif g in ("hit", "fail") and "dot" not in out:          # alchemist's fire, an icy web: it keeps burning; Flesh Entomb after a failed save
                    ext = re.search(r"DC (\d+) (?:Dexterity|Strength) check", part)
                    out["dot"] = dict(spec, gate=g, douse=int(ext.group(1)) if ext and re.search(r"extinguish|put out", part) else None)
        return out or None

    def _stat_after_strike(self, R: dict):
        """A stat block hit or failed save played out (_stat_extra): the drain, heal, cut maximum, push, pull, swallow."""
        mx = R.get("stat_extra") or {}
        att = self._find_or_none(R["actor"])
        if not mx or att is None:
            return
        healed = False
        for tid in dict.fromkeys(R["targets"]):
            tgt = self._find_or_none(tid)
            if not tgt:
                continue
            k = str(tid)
            hit = bool((R.get("hits") or {}).get(k)) if R["mode"] == "attack" else R["mode"] == "auto"
            failed = (R.get("rider_failed") or {}).get(k) if R["mode"] == "attack" else R["mode"] == "save" and (R.get("saved") or {}).get(k) is False

            def on(x):
                return bool(x) and (hit if x["gate"] == "hit" else bool(failed)) and \
                    (not x.get("cap") or SIZES.index(self._size_of(tgt)) <= SIZES.index(x["cap"]))
            dealt = int((R.get("dealt") or {}).get(k, 0))
            rolled = [p for p in (R.get("cur") or {}).get("dmg") or [] if p[0]]

            def share(dtype):                                  # "equal to the necrotic damage taken": that part of it
                if not dtype or not rolled:
                    return dealt
                total = sum(n for n, _t in rolled) or 1
                return int(dealt * sum(n for n, t in rolled if str(t).lower() == dtype) / total)
            if on(mx.get("drain")) and dealt:
                n = int(share(mx["drain"].get("type")) * mx["drain"]["frac"])
                if n > 0 and self._heal(att, n):
                    self._line(R, f"{att['name']} regains {n} hit points", f"+{n} HP")
            if on(mx.get("heal")) and not healed:
                healed = True
                n = roll(mx["heal"]["dice"])
                if n > 0 and self._heal(att, n):
                    self._line(R, f"{att['name']} regains {n} hit points", f"+{n} HP")
            if on(mx.get("temp")):                             # "and Galsariad gains 5 temporary hit points"
                n = int(dealt * mx["temp"]["frac"]) if mx["temp"].get("frac") else roll(mx["temp"]["dice"] or "0")
                if n > 0:
                    self._give_temp(att, n)
                    self._line(R, f"{att['name']} gains {n} temporary hit points", f"+{n} temp HP")
            if on(mx.get("max_hp")) and self._alive(tgt):
                cut = share(mx["max_hp"].get("type")) if mx["max_hp"]["dealt"] else roll(mx["max_hp"]["dice"] or "0")
                if mx["max_hp"].get("half"):                   # Titivilus, Geryon's Stinger: half the damage it takes
                    cut //= 2
                if cut > 0 and mx["max_hp"].get("temp_equal"):
                    self._give_temp(att, cut)
                    self._line(R, f"{att['name']} gains {cut} temporary hit points", f"+{cut} temp HP")
                if cut > 0 and tgt["kind"] != "pc":
                    tgt["max_hp"] = max(0, tgt["max_hp"] - cut)
                    tgt["hp"] = min(tgt["hp"], tgt["max_hp"])
                    self._line(R, f"{tgt['name']}'s hit point maximum drops by {cut} ({tgt['max_hp']})", f"max HP -{cut}")
                    if tgt["max_hp"] <= 0 and self._hp_of(tgt) > 0:
                        self._line(R, f"{tgt['name']} dies: " + self._deal_rolled(tgt, [[self._hp_of(tgt), ""]], by=att, label=R["label"]), "dies")
                elif cut > 0 and self._sheet(tgt):                 # a character: on the sheet until its next long rest
                    char = self._sheet(tgt)
                    char.d["hp"]["drain"] = int(char.d["hp"].get("drain") or 0) + cut
                    char.current_hp = min(char.current_hp, char.max_hp)
                    char.save()
                    self._line(R, f"{tgt['name']}'s hit point maximum drops by {cut} to {char.max_hp} until a long rest", f"max HP -{cut}")
            if on(mx.get("stable_poison")) and self._hp_of(tgt) <= 0 and self._sheet(tgt) and not self._dead(tgt):
                char = self._sheet(tgt)                        # dropped by the venom: stable, but poisoned and paralyzed for an hour
                char.d["death_saves"] = {"success": 3, "failure": 0}
                char.save()
                self._effect_on(tgt, R["label"], ["Poisoned", "Paralyzed"], None, None, None, mx["stable_poison"]["rounds"], att["name"], None, None, att["id"])
                self._line(R, f"{tgt['name']} is stable but poisoned and paralyzed ({R['label']})", "stable, paralyzed")
            if on(mx.get("possess")) and self._alive(tgt) and att.get("pos"):
                for e in [e for e in tgt.get("effects") or [] if e.get("source_id") == att["id"] and e["name"] == R["label"]]:
                    e.update(rounds=None, until=None)
                    e["mods"] = dict(e.get("mods") or {}, possessed_by=att["id"])
                    if "Incapacitated" not in e["conditions"]:
                        e["conditions"].append("Incapacitated")
                        self._cond(tgt, "Incapacitated", True)
                att["possessing"] = tgt["id"]
                att["pos"] = None                              # "the ghost then disappears": back when the body drops
                self._line(R, f"{att['name']} possesses {tgt['name']} and vanishes into it", "possessed")
            if on(mx.get("ability")) and not self._dead(tgt):     # a dying character is still drained
                self._drain_ability(R, att, tgt, mx["ability"])
            if not tgt.get("pos") or not self._alive(tgt):
                continue
            if on(mx.get("swallow")):
                for e in [e for e in tgt.get("effects") or [] if (e.get("mods") or {}).get("grappler") == att["id"]]:
                    self._effect_off(tgt, e, "swallowed")      # "...is swallowed, and the grapple ends"
                mods = {"swallowed_by": att["id"], "untargetable": True}
                if mx["swallow"].get("dot"):
                    mods["dot"] = dict(mx["swallow"]["dot"])
                self._effect_on(tgt, f"Swallowed by {att['name']}", ["Blinded", "Restrained"], None, None, None, None, att["name"], mods, None, att["id"])
                self._line(R, f"{att['name']} swallows {tgt['name']} (blinded, restrained, out of reach)", "swallowed")
                continue
            if mx.get("grab_dot") and hit:
                held = [e for e in tgt.get("effects") or [] if (e.get("mods") or {}).get("grappler") == att["id"]]
                if held:
                    held[-1]["mods"]["dot"] = dict(mx["grab_dot"])   # it ends with the grapple
            if mx.get("dot") and (hit if mx["dot"].get("gate", "hit") == "hit" else failed):   # tied to the hold its hit made (an icy web), else its own effect
                dot = {k: v for k, v in mx["dot"].items() if k not in ("douse", "gate")}
                held = [e for e in tgt.get("effects") or [] if e.get("source_id") == att["id"] and e["name"].startswith(R["label"])
                        and {"Grappled", "Restrained"} & set(e.get("conditions") or [])]
                if held:
                    held[-1]["mods"]["dot"] = dot
                else:
                    self._effect_on(tgt, R["label"], [], None, None, None, None, att["name"],
                                    dict({"dot": dot}, **({"douse": mx["dot"]["douse"]} if mx["dot"].get("douse") else {})), None, att["id"])
                    self._line(R, f"{tgt['name']} keeps taking {dot['dice']} {dot['type']} damage each turn", "burning")
            if on(mx.get("push")):
                self._push(tgt, att, int(mx["push"]["feet"]), R)
            elif on(mx.get("pull")):
                self._push(tgt, att, -int(mx["pull"]["feet"]), R)

    def _drain_ability(self, R: dict, att: dict, tgt: dict, ad: dict) -> None:
        """An ability score cut (until a long rest on a character's sheet): a shadow's 1d4 Strength, an intellect devourer
        taking Intelligence to 0 when its 3d6 beat the score. At 0 the target dies (Shadow) or is stunned (Devour Intellect)."""
        ab = ad["ab"]
        char = self._sheet(tgt)
        m = None if char else self._monster(tgt)
        drained = (char.d.get("ability_drain") if char else tgt.get("ability_drain")) or {}
        score = char.ability_score(ab) if char else max(0, int(((m or {}).get("abilities") or {}).get(ab, 10)) - int(drained.get(ab, 0)))
        if ad.get("zero_if"):
            n = roll(ad["zero_if"])
            if n < score:
                self._line(R, f"{R['label']}: {n} vs {tgt['name']}'s {ab.upper()} {score}: no effect", "resists")
                return
            cut = score
        else:
            cut = min(score, roll(ad["dice"]))
        drained = dict(drained, **{ab: int(drained.get(ab, 0)) + cut})
        if char:
            char.d["ability_drain"] = drained
            char.save()
        else:
            tgt["ability_drain"] = drained
        left = score - cut
        self._line(R, f"{tgt['name']}'s {ab.upper()} drops by {cut} to {left}" + (" until a long rest" if char else ""), f"{ab.upper()} -{cut}")
        if left <= 0 and ad.get("dies") and self._hp_of(tgt) > 0:
            if char:
                char.d["death_saves"] = {"success": 0, "failure": 3}
                char.save()
            self._line(R, f"{tgt['name']} dies: " + self._deal_rolled(tgt, [[self._hp_of(tgt) + (char.max_hp if char else 0), ""]], by=att,
                                                                   label=R["label"]), "dies")
        elif left <= 0 and ad.get("stun"):
            self._effect_on(tgt, R["label"], ["Stunned"], None, None, None, None, att["name"], {"drained": ab}, None, att["id"])
            self._line(R, f"{tgt['name']} is stunned until it regains {ab.upper()}", "stunned")

    def _turn_spell(self, R: dict, caster: dict, tgt: dict) -> None:
        """A single-target spell saved against by a creature with Spell Turning ("the spell ... instead targets the caster") or
        Spell Reflection ("can choose another creature (including the spellcaster)"): the caster makes the save now."""
        if self._fxs(tgt, "deflect_spell") and not R.get("tiles") and int(R.get("slot_level") or 0) <= 7 and self._may_react(tgt):
            t = tgt.get("turn")                                  # Holy Star of Mystra: a reaction deflects the spell back; the caster saves with its own DC
            if t is not None and self.b.get("status") == ACTIVE:
                t["reaction"] = max(0, t.get("reaction", 1) - 1)
            sv = dict(R["sv"], dc=self._spell_dc(caster))
            child = self._strike(caster, f"{R['label']} (deflected)", [caster["id"]], mode="save", sv=sv, parts=R.get("parts") or [],
                                 magical=True, spell=True)
            child["rolled"] = R.get("rolled")
            R.setdefault("follow", []).append(child)
            self._line(R, f"{tgt['name']} deflects {R['label']} back at {caster['name']} (Holy Star of Mystra)", "deflected")
            return
        m = None if self._sheet(tgt) else self._monster(tgt)
        e = next((x for sec in ("traits", "reactions") for x in (m or {}).get(sec) or []
                  if re.search(r"saving throw succeeds[^.]*instead targets the caster|successful saving throw against a spell[^.]*choose another creature",
                               x.get("text") or "")), None)
        if not e:
            return
        lvl = re.search(r"spell is of (\d+)\w* level or lower", e.get("text") or "")
        if lvl and int(R.get("slot_level") or 0) > int(lvl.group(1)):
            return
        if e in ((m or {}).get("reactions") or []):
            if not self._may_react(tgt):
                return
            t = tgt.get("turn")
            if t is not None and self.b.get("status") == ACTIVE:
                t["reaction"] = max(0, t.get("reaction", 1) - 1)
        child = self._strike(caster, f"{R['label']} (turned back)", [caster["id"]], mode="save", sv=dict(R["sv"]), parts=R.get("parts") or [],
                             magical=True, spell=True)
        child["rolled"] = R.get("rolled")
        R.setdefault("follow", []).append(child)
        self._line(R, f"{tgt['name']} turns {R['label']} back at {caster['name']} ({re.sub(r' *[(].*', '', e['name'])})", "turned back")

    def _release_possession(self, ghost: dict, why: str) -> Optional[str]:
        """A ghost (or an intellect devourer) leaves the body it possesses and reappears next to it."""
        body = self._find_or_none(ghost.get("possessing"))
        ghost.pop("possessing", None)
        if body is None:
            return None
        for e in [e for e in body.get("effects") or [] if (e.get("mods") or {}).get("possessed_by") == ghost["id"]]:
            self._effect_off(body, e, why)
        if body.get("pos"):
            ghost["pos"] = self._free_near(ghost, *body["pos"]) or None
        return f"{ghost['name']} leaves {body['name']}'s body ({why})"

    def end_possession(self, cid: int) -> str:
        """The possessor ends it as a bonus action (a ghost's Possession)."""
        with self.lock:
            self._busy()
            c = self._find(cid)
            if not c.get("possessing"):
                raise ServiceError(f"{c['name']} isn't possessing anyone.")
            self._pay(c, "bonus", "End possession")
            line = self._release_possession(c, "it lets go") or f"{c['name']} ends the possession"
            self._commit(line)
            return line

    def _own_toggles(self, c: dict) -> List[dict]:
        """Effects the creature put on itself with a stat block entry and ends when it chooses (Shell Defense, Superior
        Invisibility...): [{'name', 'cost', 'tip'}] - "as a bonus action" in the entry's text, else free. Also the spells that
        run without concentration and may be dismissed at will (Mirror Image), for a hero too."""
        out = [{"name": e["name"], "cost": "free", "tip": "Dismiss it: the spell ends."} for e in c.get("effects") or []
               if e.get("source_id") == c["id"] and e.get("conc_by") is None and e["name"] in ("Mirror Image",)]
        if self._sheet(c):
            return out
        m = self._monster(c) or {}
        entries = {re.sub(r"\s*\(.*?\)", "", e.get("name", "")): e.get("text") or "" for sec in ("actions", "bonus_actions") for e in m.get(sec) or []}
        for e in c.get("effects") or []:
            if e.get("source_id") == c["id"] and e.get("rounds") is None and not e.get("until") and e["name"] in entries:
                text = entries[e["name"]]
                cost = "bonus" if re.search(r"(?:emerge|end it|revert)[^.]*as a bonus action|bonus action to (?:end|emerge)", text) else "free"
                out.append({"name": e["name"], "cost": cost, "tip": "Ends the effect it put on itself."})
        return out

    def end_own_toggle(self, cid: int, name: str) -> str:
        with self.lock:
            self._busy()
            c = self._find(cid)
            hit = next((t for t in self._own_toggles(c) if t["name"] == name), None)
            if not hit:
                raise ServiceError("Nothing to end.")
            self._pay(c, hit["cost"], f"End {name}")
            for e in [e for e in c.get("effects") or [] if e["name"] == name and e.get("source_id") == c["id"]]:
                self._effect_off(c, e, "ended")
            self._commit(f"{c['name']} ends {name}")
            return f"{c['name']} ends {name}"

    def _death_triggers(self, c: dict, by: Optional[dict]) -> None:
        """Stat blocks that answer a creature dropping to 0 hit points: Feed on Death (temporary hit points when one drops
        within 30 feet), Grim Harvest (the killer regains hit points), Vengeful Strike (a gnoll falls: the witherling strikes).
        A possessed body dropping lets its ghost out next to it."""
        for e in [e for e in c.get("effects") or [] if (e.get("mods") or {}).get("possessed_by") is not None]:
            ghost = self._find_or_none(e["mods"]["possessed_by"])
            self._effect_off(c, e, "the body drops")
            if ghost is not None and ghost.get("possessing") == c["id"] and c.get("pos"):
                ghost.pop("possessing", None)
                ghost["pos"] = self._free_near(ghost, *c["pos"]) or None
                self._say(f"{ghost['name']} leaves {c['name']}'s body")
        if by is not None and c["kind"] == "enemy" and c.get("pos") and not c.get("conjured") and not c.get("summoned_by") \
                and str((self._monster(c) or {}).get("type") or "").lower().startswith("humanoid") \
                and any(R.get("label") == "Finger of Death" and R.get("actor") == by["id"] for R in self._stack()):
            zid = next((m["id"] for m in bestiary.all if m["name"] == "Zombie" and m.get("source") == "MM"), None)
            if zid:                                             # Finger of Death: a humanoid it kills rises as the caster's zombie (at once)
                old, self._summon_point = getattr(self, "_summon_point", None), list(c["pos"])
                try:
                    made = self._add_summons(by, zid, 1, None, 1, None, None, None, None, None)
                finally:
                    self._summon_point = old
                if made:
                    self._say(f"{c['name']} rises as a zombie under {by['name']}'s control (Finger of Death)")
        for o in self.b["combatants"]:
            if o is c or self._sheet(o) or not o.get("pos") or not c.get("pos") or self._hp_of(o) <= 0:
                continue
            m = self._monster(o) or {}
            for sec in ("traits", "reactions"):
                for e in m.get(sec) or []:
                    text, name = e.get("text") or "", re.sub(r"\s*\(.*?\)", "", e.get("name", ""))
                    react = sec == "reactions"
                    if react and not self._may_react(o):
                        continue
                    fired = False
                    g = re.search(r"creature within (\d+) feet of [^,]+? drops to 0 hit points, [^.]*?gains (\d+)(?: \((\d+d\d+(?: ?[+-] ?\d+)?)\))? "
                                  r"temporary hit points", text)
                    h = re.search(r"regains (\d+)(?: \((\d+d\d+(?: ?[+-] ?\d+)?)\))? hit points", text)
                    v = re.search(r"In response to an? (\w+) being reduced to 0 hit points within (\d+) feet", text)
                    if g and self._dist(o, c) <= int(g.group(1)):
                        n = roll((g.group(3) or g.group(2)).replace(" ", ""))
                        self._give_temp(o, n)
                        self._say(f"{o['name']}: {name} - {n} temporary hit points")
                        fired = True
                    elif re.search(r"When [\w' -]+ kills a creature", text) and by is o and h:
                        n = roll((h.group(2) or h.group(1)).replace(" ", ""))
                        self._heal(o, n)
                        self._say(f"{o['name']}: {name} - regains {n} hit points")
                        fired = True
                    elif v and v.group(1).lower() in ((self._monster(c) or {}).get("name") or "").lower() and by is not None \
                            and self._dist(o, c) <= int(v.group(2)) and self._hostile(o, by) and by.get("pos"):
                        ref = self._retaliation_attack(o, e)
                        if ref and self._dist(o, by) <= max(5, self._reach(o)):
                            self._stack().append(self._monster_strike(o, by, ref["name"], ref["text"], label=name))
                            self._say(f"{o['name']} avenges {c['name']} ({name})")
                            fired = True
                    if react and fired:
                        t = o.get("turn")
                        if t is not None and self.b.get("status") == ACTIVE:
                            t["reaction"] = max(0, t.get("reaction", 1) - 1)

    def _damage_transfer(self, c: dict, amounts, by: Optional[dict], label: str):
        """Damage Transfer: while it grapples a creature, the rug takes half the damage and the held creature the other half."""
        if self._sheet(c) or not amounts or label == "Damage Transfer":
            return amounts
        t = next((x for x in (self._monster(c) or {}).get("traits") or [] if re.search(r"takes only ha[lI]f the damage dealt to it.{0,60}?takes the other half",
                                                                                      x.get("text") or "", re.S)), None)     # a cloaker's "attached", a tracker's typo
        held = [o for o in self.b["combatants"] if t and any(c["id"] in ((e.get("mods") or {}).get("grappler"), (e.get("mods") or {}).get("attached"))
                                                             for e in o.get("effects") or [])]
        if not held:
            return amounts
        mine = [[int(a) - int(a) // 2, ty] for a, ty in amounts]
        other = [[int(a) // 2, ty] for a, ty in amounts]
        if any(a for a, _t in other):
            self._say(f"{t['name']}: " + self._deal_rolled(held[0], other, by=by, label="Damage Transfer"))
        return mine

    def _stat_split(self, c: dict, types) -> None:
        """Split (an ochre jelly, a black pudding): hurt by lightning or slashing while Medium or larger with 10+ hit points
        left, it becomes two, each with half its hit points (its reaction)."""
        if self._sheet(c) or not c.get("pos") or self._hp_of(c) < 10 or SIZES.index(self._size_of(c)) < 2:
            return
        e = next((x for x in (self._monster(c) or {}).get("reactions") or [] if re.search(r"it splits into two", x.get("text") or "")), None)
        trig = re.search(r"subjected to (\w+) or (\w+) damage", (e or {}).get("text") or "")
        if not trig or not set(types) & {trig.group(1).lower(), trig.group(2).lower()} or not self._may_react(c):
            return
        half = self._hp_of(c) // 2
        made = self._add_summons(c, c["monster"], 1, re.sub(r" \d+$", "", c["name"]), 1, None, None, None)
        if not made:
            return
        new = made[0]
        new.pop("summoned_by", None)
        new.update(hp=half, max_hp=half, ac=c["ac"], faction=faction_of(c), init=c.get("init"), xp=0)
        c["hp"], c["max_hp"] = self._hp_of(c) - half, max(1, self._hp_of(c) - half)
        if c.get("turn") is not None and self.b.get("status") == ACTIVE:
            c["turn"]["reaction"] = max(0, c["turn"].get("reaction", 1) - 1)
        self._vfx("summon", id=new["id"], type="ooze", src=None, tier=1)
        self._say(f"{c['name']} splits in two: {new['name']} ({half} HP)")

    def _source_dots(self, c: dict) -> list:
        """Damage at the start of each of `c`'s turns to the creatures it holds (a swallowed creature's acid bath)."""
        out = []
        for o in self.b["combatants"]:
            for e in o.get("effects") or []:
                dot = (e.get("mods") or {}).get("dot")
                if dot and dot.get("when") == "source_start" and e.get("source_id") == c["id"] and not self._is_out(o):
                    if dot.get("save"):                    # an engulfing mound: a save each time, the hold stays either way
                        out.append(self._strike(c, e["name"], [o["id"]], mode="save", sv={"ab": dot["save"], "dc": int(dot.get("dc") or 13),
                                                                                         "half": False}, parts=[[dot["dice"], dot["type"]]]))
                    else:
                        out.append(self._strike(c, e["name"], [o["id"]], mode="auto", parts=[[dot["dice"], dot["type"]]]))
        return out

    def _engulf(self, att: dict, base: str, text: str, target_id, cost: str, recharge, per_day) -> Optional[str]:
        """Engulf (a shambling mound, a boneless's Crushing Embrace): a creature it grapples is taken in - blinded, restrained,
        out of reach, moving with it - and saves at the start of each of its turns against the damage. None if not one."""
        m = re.search(r"(?:engulfs|wraps its body around) (?:a|one) (?:(Tiny|Small|Medium|Large|Huge) or smaller )?creature grappled by it", text)
        if not m:
            return None
        tgt = self._target(target_id)
        if not any((e.get("mods") or {}).get("grappler") == att["id"] for e in tgt.get("effects") or []):
            raise ServiceError(f"{att['name']} must be grappling {tgt['name']} first.")
        if m.group(1) and SIZES.index(self._size_of(tgt)) > SIZES.index(m.group(1)):
            raise ServiceError(f"{tgt['name']} is too big ({m.group(1)} or smaller).")
        _pre, post, save = CR.split_save(text)
        parts = CR.damage_parts(post)
        self._pay(att, cost, base)
        self._mark_used(att, base, recharge, per_day)
        for e in [e for e in tgt.get("effects") or [] if (e.get("mods") or {}).get("grappler") == att["id"]]:
            self._effect_off(tgt, e, "engulfed")
        mods = {"swallowed_by": att["id"], "untargetable": True}
        if parts:
            mods["dot"] = {"dice": parts[0][0], "type": parts[0][1], "when": "source_start", "save": save[0] if save else None,
                           "dc": save[1] if save else None}
        conds = [c for c in ("Blinded", "Restrained") if re.search(r"\b" + c.lower() + r"\b", _pre if save else text, re.I)] or ["Restrained"]
        self._effect_on(tgt, f"Engulfed by {att['name']}", conds, None, None, None, None, att["name"], mods, None, att["id"])
        line = f"{att['name']} uses {base}: {tgt['name']} is engulfed ({', '.join(c.lower() for c in conds)})"
        self._commit(line)
        return line

    def _hit_parts(self, att: dict, tgt: dict, pre: str) -> list:
        """The damage of a stat block hit. Sentences that only apply sometimes ("If the target is a creature against which the
        revenant has sworn vengeance...", a charge, damage at the start of each turn) are left out, except those the board
        can answer: the target's size, a grapple by this attacker. "If it has advantage" damage is kept apart (adv_parts)."""
        _head, sep, hit = pre.partition("Hit:")
        if not sep:
            return CR.damage_parts(pre)
        parts, self._adv_parts = [], []
        for i, sent in enumerate(re.split(r"(?<=\.)\s+", hit)):
            if i == 0 or not re.match(r"(?:If|While|When|Against|At the start)\b", sent):
                parts += CR.damage_parts(sent, now_only=True)
                odd_even = re.search(r"\d+ \((\d+d\d+)\) damage that is (\w+) if the d\d+ roll is an even number and (\w+) if it's odd", sent)
                if odd_even and odd_even.group(2).lower() in DTYPES and odd_even.group(3).lower() in DTYPES:
                    parts.append([odd_even.group(1), f"{odd_even.group(2).lower()}/{odd_even.group(3).lower()}"])   # a riffler's card: radiant on even, necrotic on odd
                continue
            already = re.match(r"If the target (?:already has the (\w+) condition|is already (\w+))\b", sent)
            if already:                                        # "If the target is already Frightened, it instead takes 10 (3d6) Psychic damage"
                if (already.group(1) or already.group(2)).capitalize() in self._conds(tgt):
                    parts += CR.damage_parts(sent)
                continue
            if re.search(r"ha[sd] advantage on the attack roll|attack roll has advantage", sent):
                self._adv_parts += CR.damage_parts(sent)
            elif re.search(r"Large or (?:bigger|larger)", sent) and SIZES.index(self._size_of(tgt)) >= 3 \
                    or re.search(r"Huge or (?:bigger|larger)", sent) and SIZES.index(self._size_of(tgt)) >= 4:
                parts += CR.damage_parts(sent)
            elif re.search(r"already grappled by", sent) and any((e.get("mods") or {}).get("grappler") == att["id"] for e in tgt.get("effects") or []):
                parts += CR.damage_parts(sent)
            elif RUN_HIT_RE.search(sent) and self._charged(att, tgt, int(RUN_HIT_RE.search(sent).group(1))):
                parts += CR.damage_parts(sent)                 # a charge written into the hit (the MPMM's Gore, Ram...)
        return parts

    def _target_rule(self, att: dict, tgt: dict, text: str) -> Optional[str]:
        """Stat-block targeting limits: the vampire bites a creature it grapples (or one incapacitated or restrained), the
        mind flayer extracts the brain of an incapacitated creature it grapples."""
        head = text.split("Hit:", 1)[0]
        held = any((e.get("mods") or {}).get("grappler") == att["id"] for e in tgt.get("effects") or [])
        conds = set(self._conds(tgt))
        if re.search(r"a creature that is grappled by (?:the )?[\w ]+?, incapacitated, or restrained", head, re.I):
            if not (held or K.incapacitated(conds) or "Restrained" in conds or not self._hostile(att, tgt)):
                return f"{tgt['name']} must be grappled by {att['name']}, incapacitated or restrained first."
        elif re.search(r"one incapacitated [\w ]+? grappled by ", head, re.I):
            if not (held and K.incapacitated(conds)):
                return f"{tgt['name']} must be grappled by {att['name']} and incapacitated first."
        elif re.search(r"to hit, (?:reach|range)[^,]*, one (?:\w+ )?prone (?:creature|target)", head, re.I) and "Prone" not in conds:
            return f"{tgt['name']} must be prone first ({att['name']}'s attack is against a prone creature)."      # an elephant's Stomp, an elk's Hooves
        return None

    def _eye_rays(self, att: dict, text: str) -> Optional[dict]:
        """{'n', 'rays': [(name, text)]} for "shoots two of the following magical eye rays at random" (or a legendary "uses one
        random eye ray": its Eye Rays action's list), else None. Rays whose text the data lost are left out."""
        if re.search(r"uses (?:one|a) random (?:magical )?eye ray", text):
            src = next((e.get("text") or "" for sec in ("actions", "bonus_actions") for e in (self._monster(att) or {}).get(sec) or []
                        if re.search(r"eye rays at random", e.get("text") or "")), "")
            n = 1
        else:
            src = text
            g = re.search(r"shoots (one|two|three|four|five|six|\d+) of the following [\w ]*?rays at random", text)
            if not g:
                return None
            n = WORDS.get(g.group(1)) or int(g.group(1))
        rays = []
        for bit in re.split(r"\n?•\s*", src)[1:]:
            m = re.match(r"(?:\d+[:.]\s*)?([A-Z][\w' -]*?Ray)\.?\s+(.+)", bit.strip(), re.S)
            if m and (CR.split_save(m.group(2))[2] or CR.damage_parts(m.group(2))):
                rays.append((m.group(1), m.group(2).split("\n\n")[0]))
        return {"n": n, "rays": rays} if rays else None

    def _shoot_rays(self, att: dict, base: str, sec, name: str, rays: dict, target_id, targets, recharge, per_day) -> str:
        """The rays picked at random, each a save (or damage) against one of the chosen targets, one after another."""
        ids = [t for t in (targets or ([target_id] if target_id else [])) if t] or [self._target(None)["id"]]
        cost = {"bonus_actions": "bonus", "reactions": "reaction"}.get(sec, "action")
        if sec == "legendary":
            c2 = re.search(r"Costs (\d) Actions", name, re.I)
            cost = f"legendary:{c2.group(1) if c2 else 1}"
        picks = self.rng.sample(rays["rays"], min(rays["n"], len(rays["rays"])))
        strikes = []
        for i, (rname, rtext) in enumerate(picks):
            tgt = self._find(ids[i % len(ids)])
            pre, post, save = CR.split_save(rtext)
            cap = re.search(r"\b(Tiny|Small|Medium|Large|Huge) or smaller\b", pre)
            if cap and SIZES.index(self._size_of(tgt)) > SIZES.index(cap.group(1)):
                continue
            if save:
                sv = {"ab": save[0], "dc": save[1], "half": "half as much" in post.lower(), **self._save_terms(post)}
                S = self._strike(att, rname, [tgt["id"]], mode="save", sv=sv, parts=CR.save_damage(post), magical=True)
                S["stat_extra"] = self._stat_extra(rtext)
            else:
                S = self._strike(att, rname, [tgt["id"]], mode="auto", parts=CR.damage_parts(rtext, now_only=True), magical=True)
            strikes.append(S)
        self._pay(att, cost, base)
        self._mark_used(att, base, recharge, per_day)
        self._say(f"{att['name']} uses {base}: " + ", ".join(r for r, _t in picks))
        if not strikes:
            self._commit()
            return f"{att['name']} uses {base}: no ray takes"
        strikes[0]["follow"] = strikes[1:]
        out = self._run_r(strikes[0])
        self._commit()
        return out

    def _swallow_bite(self, att: dict, tgt: dict, text: str) -> Optional[dict]:
        """A Swallow action ("makes one bite attack against a Medium or smaller target it is grappling. If the attack hits,
        the target is swallowed"): the bite entry to roll, after checking the target is held and small enough. None if
        the text isn't one."""
        m = re.search(r"makes one ([\w' -]+?) attack against an? (?:(Tiny|Small|Medium|Large|Huge) or smaller )?(?:target|creature)"
                      r"(?: it is grappling| grappled by it)?", text)
        if not m or not re.search(r"\bswallowed\b", text):
            return None
        want = m.group(1).lower().rstrip("s")
        pool = [e for sec in ("actions", "bonus_actions") for e in (self._monster(att) or {}).get(sec) or []
                if re.search(r"[+-]\d+ to hit", e.get("text") or "")]
        bite = next((e for e in pool if FORM_ONLY.sub("", e.get("name", "")).lower().rstrip("s") == want), None) or \
            next((e for e in pool if want in e.get("name", "").lower()), None)
        if not bite:
            return None
        if m.group(2) and SIZES.index(self._size_of(tgt)) > SIZES.index(m.group(2)):
            raise ServiceError(f"{tgt['name']} is too big to swallow ({m.group(2)} or smaller).")
        if "grappl" in m.group(0) and not any((e.get("mods") or {}).get("grappler") == att["id"] for e in tgt.get("effects") or []):
            raise ServiceError(f"{att['name']} must be grappling {tgt['name']} first.")
        return bite

    # ------------------------------------------------------------------ stat block actions with no roll: teleports, heals, summons
    _TELEPORT = re.compile(r"^(?:While [^,.]+, )?(?!The target|Each|One creature)[^.]*?\b(?:magically )?(?:teleports|can teleport|it is grappling teleport)"
                           r"(?:,? along with [^.]*?(?:carrying|grappling|grappled),?)? "     # also "Glasstaff magically teleports..."
                           r"(?:up to (\d+) feet|to an unoccupied space (?:(?:that|which) )?(?:(?:it|he|she|they) can see )?within (\d+) feet)")
    _MOVE = re.compile(r"\b(?:moves|flies|swims|flies or swims)\b(?: up to| without provoking)", re.I)    # a legendary "Move"
    _MOVE_AFTER = re.compile(r"\bcan then (?:fly|move|swim) up to\b", re.I)          # a Wing Attack's "can then fly up to half its flying speed"
    _SELF_REF = re.compile(r"(?:With a [a-z ]+, )?(?:the [a-z' -]{1,30}|[A-Z][\w']{0,30}) (?:makes|uses) ", re.I)   # an action that only points at another entry
    _MOVE_TO = re.compile(r"\b(?:can move up to|leaps up to|jumps (?:a distance )?up to)\b", re.I)   # Aggressive, a thri-kreen's Leap
    _NO_OA = re.compile(r"without provoking|(?:doesn't|does not) provoke", re.I)

    def _is_move(self, text: str) -> bool:
        """A stat block entry that only moves the creature ("The vampire moves up to its speed without provoking opportunity
        attacks"): its first sentence says so and nothing in it attacks, hurts, teleports or changes shape."""
        first = re.split(r"(?<=\.)\s+", (text or "").strip())[0]
        rest = re.sub(r"opportunity attacks?", "", text or "", flags=re.I)
        return bool(self._MOVE.search(first) or self._MOVE_TO.search(first)) and not re.search(r"\battacks?\b|damage|saving throw|teleport|transform|polymorph", rest, re.I)

    def _move_feet(self, att: dict, text: str) -> int:
        """Feet a movement sentence allows: "up to 20 feet", "up to its speed", "up to half its flying speed", a bare "moves"."""
        sent = next((s for s in re.split(r"(?<=\.)\s+", text or "") if self._MOVE.search(s) or self._MOVE_AFTER.search(s) or self._MOVE_TO.search(s)), text or "")
        base = self._speed(att)
        sp = self._speeds(att)
        n = re.search(r"up to (\d+) (?:feet|ft)", sent)
        if n:
            return min(int(n.group(1)), base) // 5 * 5
        if re.search(r"flying speed", sent) and sp.get("fly"):
            base = base * sp["fly"] // max(1, sp.get("walk", 0), sp["fly"])
        return (base // 2 if re.search(r"\bhalf\b", sent) else base) // 5 * 5

    def _move_plan(self, att: dict, feet: int, point, free: bool, base: str) -> dict:
        """The walk a movement entry makes to `point` within `feet` (raises when it can't): {'kind': 'move', 'path', 'cost', 'free'}."""
        if feet <= 0 or not K.can_move(self._conds(att), self._exhaustion(att)):
            raise ServiceError(f"{att['name']} can't move.")
        if not att.get("pos"):
            raise ServiceError("Put the creature on the map first.")
        if not point:
            raise ServiceError("Pick where to go.")
        path, cost = self._find_path(att, (int(point[0]), int(point[1])), feet)
        if path is None:
            raise ServiceError(cost)
        if cost * self._drag_factor(att) > feet:
            raise ServiceError(f"{base}: needs {cost * self._drag_factor(att)} ft, {feet} ft allowed")
        return {"kind": "move", "path": path, "cost": cost, "free": free}

    def _move_walk(self, att: dict, base: str, plan: dict) -> str:
        """Walk off its own turn (a legendary action): no movement taken from its turn, no opportunity attacks if the entry says so."""
        if len(plan["path"]) < 2:
            return f"{att['name']} uses {base}"
        R = self._new_r("walk", att, "move", path=plan["path"], i=0, cost=plan["cost"], summary_targets="", free_move=True, no_oa=plan["free"])
        self._run_r(R)
        return f"{att['name']} uses {base}"

    _MOVE_ATK_START = re.compile(r"(?:After|When|Whenever|If|While)\b")

    def _move_attack(self, att: dict, text: str) -> Optional[dict]:
        """A stat block entry that moves first and then attacks ("The phoenix moves up to its speed and makes one Fiery Talons
        attack", "...then makes one gore attack", "...one Claws attack against each creature it moves past"):
        {'feet', 'free', 'atks': [{'entry', 'each', 'adv', 'extra', 'noncrit'}]}, or None for any other text."""
        sents = [x for x in re.split(r"(?<=\.)\s+", (text or "").strip()) if x]
        if not sents or self._MOVE_ATK_START.match(sents[0]) or not self._MOVE.search(sents[0]) or re.search(r"teleport", text, re.I):
            return None
        m = self._monster(att) or {}
        pool = [e for sec in ("actions", "bonus_actions") for e in m.get(sec) or [] if e.get("name", "").lower() != "multiattack"]
        atks = []
        for i, sent in enumerate(sents):
            found = []
            for g in re.finditer(r"\b(?:makes?|attacks?|or) (?:one|a|an) ([\w' -]+?) attack\b|\battacks? with (?:his|her|its|their) ([\w' -]+?)(?=[.,;]|$| and\b| against\b)",
                                 sent, re.I):
                nm = (g.group(1) or g.group(2)).strip().lower()
                e = next((x for x in pool if re.sub(r"\s*\([^)]*\)", "", x["name"]).strip().lower() == nm), None) \
                    or next((x for x in pool if re.sub(r"\s*\([^)]*\)", "", x["name"]).strip().lower().startswith(nm)), None)
                if e and e not in found and self._form_ok(att, e["name"]):
                    found.append(e)
            if not found:
                continue
            if len(found) > 1 and not att.get("shape"):          # "a Claws attack (hybrid only) or a Longsword attack (humanoid only)": its own form first
                found.sort(key=lambda x: not re.search(r"(?:humanoid|human)", x["name"], re.I))
            extra = next((x for x in sents[i + 1:i + 2] if re.match(r"If the attack hits", x) and re.search(r"\bextra\b", x)), "")
            atks.append({"entry": found[0]["name"], "each": bool(re.search(r"against each creature|each creature (?:it|he|she) (?:moves|passes)", sent, re.I)),
                         "adv": bool(re.search(r"with advantage", sent, re.I)), "extra": [list(p) for p in CR.damage_parts(extra)] if extra else [],
                         "noncrit": bool(re.search(r"not a critical", extra, re.I))})
        if not atks:
            return None
        return {"feet": max(5, self._move_feet(att, text)), "free": bool(self._NO_OA.search(text)), "atks": atks}

    def _move_attack_dest(self, att: dict, mv: dict, point, target_id) -> tuple:
        """(tile to walk to, the creature it goes for or None): a click on a hostile creature walks to the nearest free tile
        within reach of it, a click on an empty tile walks there."""
        foe = None
        if point:
            tile = (int(point[0]), int(point[1]))
            foe = next((o for o in self.b["combatants"] if o is not att and o.get("pos") and self._hostile(o, att) and not self._is_out(o)
                        and tile in G.footprint(o["pos"], o.get("span") or 1)), None)
            if foe is None:
                tgt = self._find_or_none(target_id)
                return tile, tgt if tgt is not None and tgt is not att and self._hostile(tgt, att) else None
        else:
            foe = self._find_or_none(target_id)
            if foe is None or foe is att or not foe.get("pos") or not self._hostile(foe, att):
                raise ServiceError("Pick where to go.")
        _sec, ent = self._entry_section(att, mv["atks"][0]["entry"])
        rch = re.search(r"reach (\d+) ft", (ent or {}).get("text") or "")
        reach = max(5, int(rch.group(1))) if rch else 5
        span, fb = att.get("span") or 1, G.box(foe["pos"], foe.get("span") or 1)
        best = None
        for x in range(fb[0] - reach // 5 - span, fb[2] + reach // 5 + 2):
            for y in range(fb[1] - reach // 5 - span, fb[3] + reach // 5 + 2):
                if G.gap(G.box((x, y), span), fb) * 5 > reach or not self._tile_ok(att, x, y) \
                        or G.distance_to_tile(att["pos"], span, (x, y)) > mv["feet"] + 5:
                    continue
                path, cost = self._find_path(att, (x, y), mv["feet"])
                if path is not None and (best is None or cost < best[0]):
                    best = (cost, (x, y))
        if best is None:
            raise ServiceError(f"{foe['name']} is out of reach of a move of {mv['feet']} ft.")
        return best[1], foe

    def _move_attack_do(self, att: dict, base: str, sec: Optional[str], name: str, mv: dict, point, target_id, recharge, per_day) -> str:
        """Play a move-then-attack entry: the walk (point), then its attacks on whom it reached."""
        if not att.get("pos"):
            raise ServiceError("Put the creature on the map first.")
        cost = {"bonus_actions": "bonus", "reactions": "reaction"}.get(sec, "action")
        if sec == "legendary":
            c2 = re.search(r"Costs (\d) Actions", name, re.I)
            cost = f"legendary:{c2.group(1) if c2 else 1}"
        dest, foe = self._move_attack_dest(att, mv, point, target_id)
        plan = self._move_plan(att, mv["feet"], dest, mv["free"], base)
        self._pay(att, cost, base)
        self._mark_used(att, base, recharge, per_day)
        R = self._new_r("mvatk", att, base, summary_targets="", path=plan["path"], cost=plan["cost"], no_oa=plan["free"], atks=mv["atks"],
                        foe=foe["id"] if foe else None)
        out = self._run_r(R)
        self._commit()
        return out

    def _step_mvatk(self, R: dict) -> str:
        """A move-then-attack entry: walk first, then each attack at the creatures in reach of where it ended (or, for "each
        creature it moves past", of any tile it crossed)."""
        att = self._find_or_none(R["actor"])
        if att is None or not att.get("pos"):
            return DONE
        if R["stage"] == "start":
            R["stage"] = "hit"
            self._line(R, f"{att['name']} uses {R['label']}")
            if len(R["path"]) >= 2:
                self._stack().append(self._new_r("walk", att, "move", path=R["path"], i=0, cost=R["cost"], summary_targets="", free_move=True,
                                                 no_oa=R["no_oa"]))
            return NEXT
        if R["stage"] != "hit" or not self._alive(att) or K.incapacitated(self._conds(att)):
            return DONE
        R["stage"] = "end"
        here = [list(t) for t in R["path"]]
        walked = here[:here.index(list(att["pos"])) + 1] if list(att["pos"]) in here else here
        span = att.get("span") or 1
        strikes = []
        for a in R["atks"]:
            _sec, ent = self._entry_section(att, a["entry"])
            if not ent:
                continue
            rch = re.search(r"reach (\d+) ft", ent.get("text") or "")
            reach = max(5, int(rch.group(1))) if rch else 5
            foes = [o for o in self.b["combatants"] if o is not att and o.get("pos") and self._hostile(o, att) and not self._is_out(o)]
            if a["each"]:
                picks = [o for o in foes if any(5 * G.gap(G.box(t, span), G.box(o["pos"], o.get("span") or 1)) <= reach for t in walked)]
            else:
                near = sorted((o for o in foes if self._dist(att, o) <= reach), key=lambda o: (o["id"] != R.get("foe"), self._dist(att, o)))
                picks = near[:1]
            if not picks:
                self._line(R, f"{att['name']}: nobody in reach of {ent['name']}")
            for tgt in picks:
                S = self._monster_strike(att, tgt, ent["name"], ent["text"], adv="adv" if a["adv"] else None, label=f"{ent['name']} ({R['label']})")
                if a["extra"]:
                    key = "noncrit_parts" if a["noncrit"] else "parts"
                    S["atk"][key] = [list(p) for p in S["atk"].get(key) or []] + [list(p) for p in a["extra"]]
                if not a["each"]:                                  # one it ends next to: reach and cover count; one it passed was in reach then
                    try:
                        S["atk"] = self._check_reach(att, tgt, S["atk"])
                    except ServiceError as e:
                        self._line(R, f"{att['name']}: {e}")
                        continue
                strikes.append(S)
        for S in reversed(strikes):
            self._stack().append(S)
        return NEXT if strikes else DONE

    _HEAL = re.compile(r"(?:regains?|regaining|heals?) (?:up to )?(\d+(?:d\d+(?: ?[+-] ?\d+)?)?)(?: \((\d+d\d+(?: ?[+-] ?\d+)?)\))? hit points")   # also "regains 2d4 + 2 hit points"
    _TEMP = re.compile(r"gains? (\d+)(?: \((\d+d\d+(?: ?[+-] ?\d+)?)\))? temporary hit points")
    _CALL = re.compile(r"(?:magically )?(?:summons|calls|conjures|regurgitates|chance of (?:magically )?summoning|attempts to (?:magically )?summon)(?: up to)? (.+?)"
                       r"(?:\.|, provided|,? in (?:an )?unoccupied| into an? (?:empty|unoccupied)| that | which | to its aid| \(see| \(as | and loses | with an? (?!\d))")

    def _summon_choices(self, att: dict, text: str) -> list:
        """What a summoning action can bring: [{'value', 'label', 'monster', 'count', 'chance'}] ("magically summons five
        skeletons or zombies", "a quasit, or attempts to summon a shadow demon with a 50% chance of success")."""
        chains = re.match(r"Up to (\w+) chains [\w' ]+? can see within \d+ feet of [\w' ]+? magically sprout razor-edged barbs and animate", text)
        if chains:                                           # a chain devil's Animate Chains: its chains as objects (AC 20, 20 hit points)
            n = str(WORDS.get(chains.group(1).lower(), 4))
            mon = bestiary.get("Animated Object (Small)|PHB")
            return [{"value": mon["id"], "label": f"{n} × Animated Chain", "monster": mon["id"], "count": n, "chance": None, "name": "Animated Chain",
                     "stats": {"hp": 20, "ac": 20, "mods": {"resist": ["piercing"], "immune": ["psychic", "thunder"]}}}] if mon else []
        die = re.search(r"\brolls an? d(\d+)\.", text)
        if die:                                              # a kelubar's Summon Demodand: "A result of 1-2 summons in two allied farastu stalkers, ..."
            out = []
            src = (self._monster(att) or {}).get("source")
            for lo, hi, cnt, nm in re.findall(r"a result of (\d+)(?:-(\d+))? summons? in (an?|one|two|three|four|five|six|\d+) (?:allied |friendly )?([\w' -]+?)(?=,|\.|$)", text, re.I):
                low = nm.strip().lower()
                pool = [x for x in bestiary.all if x["name"].lower() in (low, re.sub(r"s$", "", low))]
                mon = next((x for x in pool if x["source"] == src), None) or next((x for x in pool if x["source"] == "MM"), None) or (pool[0] if pool else None)
                if mon:
                    out.append({"value": mon["id"], "label": f"{lo}{'-' + hi if hi else ''}: {cnt} × {mon['name']}", "monster": mon["id"], "count": cnt,
                                "chance": None, "roll": [int(lo), int(hi or lo)], "die": int(die.group(1))})
            if out:
                return out
        cr = re.search(r"\bsummons an? (\w+) of challenge rating (\d+(?:/\d+)?) or (?:lower|less)\b", text)
        if cr:                                               # Drivvin's "a demon of challenge rating 6 or lower": the DM picks one that fits
            num, _, den = cr.group(2).partition("/")
            top, kind, seen, out = int(num) / int(den or 1), cr.group(1).lower(), set(), []
            for x in sorted(bestiary.offered() or bestiary.all, key=lambda e: (-float(e.get("cr_num") or 0), e["name"], e["source"] != "MM")):
                if x["source"] in ("MM", "MPMM", "MTF", "VGM") and float(x.get("cr_num") or 0) <= top and "," not in x["name"] and x["name"] not in seen \
                        and (kind in [str(t).lower() for t in x.get("tags") or []] or str(x.get("type") or "").lower() == kind) \
                        and not any(re.search(r"\bsummon", e.get("text") or "", re.I) for e in x.get("actions") or []):
                    seen.add(x["name"])
                    out.append({"value": x["id"], "label": f"{x['name']} (CR {x['cr']}, {x['hp']} HP)", "monster": x["id"], "count": "1", "chance": None})
            if out:
                return out[:14]
        g = self._CALL.search(text)
        tree = re.search(r"animates (one or two|one|two|up to \w+) \w+ [^.]*\.\s+(?:These \w+ have the same statistics as an?|A boulder has statistics like those of an?) "
                         r"([\w ]+?)(?: \(|[,.])", text)           # a treant's trees, a galeb duhr's boulders
        if tree:                                             # a treant's Animate Trees: copies of itself
            mon = next((x for x in bestiary.all if x["name"].lower() == tree.group(2).lower()), None)
            n = "2" if "two" in tree.group(1) else "1"
            return [{"value": mon["id"], "label": f"{n} × {mon['name']}", "monster": mon["id"], "count": n, "chance": None}] if mon else []
        use = re.search(r"\b(?:summons|creates) (one or two|\d+d\d+(?: ?\+ ?\d+)?|\d+|one|two|three|four|five|a|an) [\w' -]+?[ ,]+(?:made of \w+ )?"
                        r"(?:\(|called [\w' -]+ \()use the ([\w' -]+?) stat block", text)
        if use:                                              # "summons 1d4 wolves made of ice (use the winter wolf stat block ...)", a lornling's maker
            pool = [x for x in bestiary.all if x["name"].lower() == use.group(2).lower()]
            src = (self._monster(att) or {}).get("source")
            mon = next((x for x in pool if x["source"] == src), None) or next((x for x in pool if x["source"] == "MM"), None) or (pool[0] if pool else None)
            if mon:
                n = {"one or two": "1d2"}.get(use.group(1), use.group(1).replace(" ", ""))
                return [{"value": mon["id"], "label": f"{'1' if n in ('a', 'an', 'one') else n} × {mon['name']}", "monster": mon["id"], "count": n, "chance": None}]
        body = g.group(1) if g else None
        if body is None:                                     # "Up to five skeletons or zombies appear in unoccupied spaces", "1d6 shadows arise"
            ap = re.search(r"^Up to (\w+) ([\w ]+?) appear\b|; (\d+d\d+) ([\w ]+?) (?:\([^)]*\) )?arise\b", text)
            if ap:
                body = f"{ap.group(1) or ap.group(3)} {ap.group(2) or ap.group(4)}"
        if body is None:
            return []
        chance = re.search(r"(\d+)(?:%| percent) chance", text)
        out, count, prefix = [], None, ""
        for bit in re.split(r",? or |, ", body):
            m = re.match(r"(?:attempts to summon )?(an?|one|two|three|four|five|six|\d+d\d+(?: ?\+ ?\d+)?|\d+)?\s*([\w' -]+?)(?: with an? (\d+)% chance[\w ]*)?$",
                         bit.strip(" ,"))
            if not m:
                continue
            count = (m.group(1) or count or "1").replace(" ", "")
            name = re.sub(r"^(?:allied|friendly) ", "", m.group(2).strip())     # "summons an allied horned devil"
            if name.lower().startswith("swarms of "):
                prefix = "swarm of "
            elif prefix and " " not in name:
                name = prefix + name                        # "2d4 swarms of bats or rats"
            low = name.lower()
            cands = [low, re.sub(r"^swarms of", "swarm of", low), re.sub(r"ves$", "f", low), re.sub(r"es$", "", low), re.sub(r"s$", "", low),
                     re.sub(r"i$", "", low)]                # slaadi
            pool = [x for x in bestiary.all if x["name"].lower() in cands]
            if not pool:
                continue
            src = (self._monster(att) or {}).get("source")
            mon = next((x for x in pool if x["source"] == src), None) or next((x for x in pool if x["source"] == "MM"), None) or pool[0]
            pct = int(m.group(3)) if m.group(3) else (int(chance.group(1)) if chance and not re.search(r"\d+%", body) else None)
            shown = "1" if count in ("a", "an", "one") else count
            out.append({"value": mon["id"], "label": f"{shown} × {mon['name']}" + (f" ({pct}%)" if pct else ""), "monster": mon["id"],
                        "count": count, "chance": pct})
        return out

    _SHAPE = re.compile(r"\b(?:magically )?(?:polymorphs?|transforms?|changes) (?:itself )?(?:into|from its true form)|back into (?:its|her|his) "
                        r"(?:true|\w+) form", re.I)

    def _true_forms(self, c: dict) -> List[str]:
        """Its own form's names, lower case: a tag word in its name or type or tags ('vampire', 'humanoid', 'elf'), or the
        "back into its human form" of its shape-change text."""
        m = self._monster(c) or {}
        words = {str(m.get("type") or "").lower(), "true"} | {str(t).lower() for t in m.get("tags") or []}
        out = [f.lower() for f in self._forms(c) if re.search(r"\b" + re.escape(f) + r"\b", m.get("name") or "", re.I) or f.lower() in words]
        for sec in ("traits", "actions", "bonus_actions"):
            for e in m.get(sec) or []:
                g = re.search(r"back into (?:its|her|his) (\w+) form", e.get("text") or "", re.I)
                if g and g.group(1).lower() != "true":
                    out.append(g.group(1).lower())
                g = re.search(r"reverts to (?:its|her|his|their) (\w+) form|true form, which (?:appears|is) (\w+)", e.get("text") or "", re.I)
                word = ((g.group(1) or g.group(2)) if g else "").lower()      # a wererat boss: "He reverts to his humanoid form if he dies"
                if word and word not in out and word in [f.lower() for f in self._forms(c)]:     # only a form the entries' tags name
                    out.append(word)
        return out

    def _revert_shape(self, c: dict):
        """A shapechanger forced back into its true form (Moonbeam): the shape and the AC that went with it."""
        if (c.get("form") or {}).get("keeps_hp"):
            c.pop("form", None)
        m = self._monster(c) or {}
        if re.search(r"\bin (?:humanoid|human|elf|true) form", m.get("ac_note") or "", re.I) and c.get("true_ac") is not None:
            c["ac"] = c["true_ac"]
        c["shape"] = None

    def _forms(self, c: dict) -> List[str]:
        """The forms its stat block's "(Wolf or Hybrid Form Only)" entries name ('Wolf', 'Hybrid', ...)."""
        out = []
        for sec in ("traits", "actions", "bonus_actions", "reactions", "legendary"):
            for e in (self._monster(c) or {}).get(sec) or []:
                for g in re.findall(r"\(([^)]*?) Forms? Only\)", e.get("name", "")):
                    out += [x.strip() for x in re.split(r",|\bor\b", g) if x.strip() and x.strip() not in out]
        return out

    def _form_ok(self, c: dict, name: str) -> bool:
        """May this entry be used in the creature's current shape? (Every entry while it is in its own form.)"""
        tag = re.search(r"\(([^)]*?) Forms? Only\)", name or "")
        if (c.get("shape") or "").lower() == "mist":         # "While in mist form, the vampire can't take any actions": change back or move
            etext = next((e.get("text") or "" for sec in ("actions", "traits", "legendary") for e in (self._monster(c) or {}).get(sec) or []
                          if e.get("name") == name), "")
            if not (self._SHAPE.search(etext) or re.search(r"\bmoves up to\b", etext)):
                return False
        if not tag:
            return True
        ok = [x.strip().lower() for x in re.split(r",|\bor\b", tag.group(1))]
        shape = c.get("shape")
        if shape:
            return shape.lower() in ok
        true = self._true_forms(c)                       # in its own form: what that form's tag allows ("Spear (Humanoid Form Only)")
        return not true or any(t in ok for t in true)

    _COMMAND = re.compile(r"(?:can|to) (?:immediately |each )?use (?:its|their) reactions?(?:, if available,)? to (?:each )?make (?:one|a) "
                          r"(?:melee |weapon |melee weapon |ranged )?attack|can make one (?:melee )?(?:weapon )?attack (?:using its reaction|as a reaction)")

    def _command_strikes(self, att: dict, base: str, ids: List[int], adv: bool) -> List[dict]:
        """Allies told to strike: each spends its reaction on its first weapon attack at the nearest foe it can reach."""
        out = []
        for oid in ids:
            o = self._find_or_none(oid)
            m = None if o is None or self._sheet(o) else self._monster(o)
            atk = next((e for e in (m or {}).get("actions") or [] if re.search(r"Weapon Attack:", e.get("text") or "")), None)
            if not atk or not o.get("pos"):
                continue
            foes = sorted((f for f in self.b["combatants"] if f.get("pos") and f is not att and self._hostile(f, o) and self._alive(f)),
                          key=lambda f: self._dist(o, f))                    # (a charmed creature can't strike its charmer)
            reach = re.search(r"reach (\d+) ft", atk["text"])
            rng = re.search(r"range (\d+)", atk["text"])
            foe = next((f for f in foes if self._dist(o, f) <= (int(reach.group(1)) if reach else int(rng.group(1)) if rng else 5)), None)
            if not foe:
                continue
            t = o.get("turn")
            if t is not None and self.b.get("status") == ACTIVE:
                t["reaction"] = max(0, t.get("reaction", 1) - 1)
            out.append(self._monster_strike(o, foe, atk["name"], atk["text"], adv="adv" if adv else None, label=f"{atk['name']} ({base})"))
        return out

    def _order_plan(self, att: dict, text: str, target_id, option) -> dict:
        """Reposition, Exert Will, Dance My Puppet, Sadistic Revelry: who obeys (an ally, or a creature charmed by it, with a reaction
        left) and what it does: 'move' toward the nearest foe, 'attack' (a weapon attack at the nearest foe in its reach) or
        'revelry' (half its speed toward the closest creature, then a melee attack)."""
        near = re.search(r"within (\d+) feet", text)
        cap = int(near.group(1)) if near else None

        def mine(o):
            return o is not att and o.get("pos") and self._alive(o) and not self._is_out(o) and (
                not self._hostile(o, att) or any("Charmed" in (e.get("conditions") or []) and e.get("source_id") == att["id"] for e in o.get("effects") or []))
        if re.match(r"\s*Each creature", text):
            ids = [o["id"] for o in self.b["combatants"] if mine(o) and att.get("pos") and self._dist(att, o) <= (cap or 60) and self._may_react(o)]
            if not ids:
                raise ServiceError(f"Nothing to order: no ally or charmed creature near {att['name']} has a reaction.")
            return {"kind": "order", "ids": ids, "mode": "revelry", "half": True, "free": False}
        tgt = self._target(target_id)
        if not mine(tgt):
            raise ServiceError("Pick a creature charmed by " + att["name"] + "." if "charmed by" in text else "Pick an ally of " + att["name"] + ".")
        if cap and att.get("pos") and self._dist(att, tgt) > cap:
            raise ServiceError(f"{tgt['name']} is too far away.")
        if not self._may_react(tgt):
            raise ServiceError(f"{tgt['name']} has no reaction left.")
        atk = option == "attack" and re.search(r"or to make (?:a|one) weapon attack", text)
        return {"kind": "order", "ids": [tgt["id"]], "mode": "attack" if atk else "move", "half": False, "free": bool(self._NO_OA.search(text))}

    def _march(self, o: dict, foe: dict, feet: int) -> Optional[tuple]:
        """(path, cost) of the walk that brings `o` as close to `foe` as `feet` of movement allow, or None when it can't get closer."""
        span, fb = o.get("span") or 1, G.box(foe["pos"], foe.get("span") or 1)
        x0, y0 = o["pos"]
        r = max(0, feet // 5)
        fx_, fy_ = (fb[0] + fb[2]) / 2, (fb[1] + fb[3]) / 2
        cands = sorted((G.gap(G.box((x, y), span), fb), (x - fx_) ** 2 + (y - fy_) ** 2, (x, y))
                       for x in range(x0 - r, x0 + r + 1) for y in range(y0 - r, y0 + r + 1) if (x, y) == (x0, y0) or self._tile_ok(o, x, y))
        for _gap, _d, tile in cands[:60]:
            path, cost = self._find_path(o, tile, feet)
            if path is not None:
                return (path, cost) if len(path) > 1 else None
        return None

    def _order_runs(self, att: dict, base: str, plan: dict) -> List[dict]:
        """The resolutions an order sets going, one per creature that obeys (each spends its reaction)."""
        runs = []
        for oid in plan["ids"]:
            o = self._find_or_none(oid)
            if o is None or not o.get("pos") or not self._may_react(o):
                continue
            if plan["mode"] == "attack":
                runs += self._command_strikes(att, base, [oid], False)       # it spends the reaction itself
                continue
            t = o.get("turn")
            if t is not None and self.b.get("status") == ACTIVE:
                t["reaction"] = max(0, t.get("reaction", 1) - 1)
            if plan["mode"] == "revelry":                     # the creature closest to it that it can see (one it could attack)
                pool = [f for f in self.b["combatants"] if f is not o and f.get("pos") and self._alive(f) and not self._is_out(f) and self._hostile(o, f)]
            else:
                pool = [f for f in self.b["combatants"] if f is not o and f.get("pos") and self._alive(f) and not self._is_out(f) and self._hostile(att, f)
                        and f is not att]
            foe = min(pool, key=lambda f: self._dist(o, f), default=None)
            feet = self._speed(o) // (2 if plan["half"] else 1) // 5 * 5
            if foe is None or not K.can_move(self._conds(o), self._exhaustion(o)):
                self._say(f"{o['name']} obeys {base}: nowhere to go")
                continue
            m = (self._monster(o) or {}) if not self._sheet(o) else {}
            atk = next((e for e in m.get("actions") or [] if re.search(r"Melee Weapon Attack:", e.get("text") or "")), None) if plan["mode"] == "revelry" else None
            go = None if self._dist(o, foe) <= 5 else self._march(o, foe, feet)
            if go is None and not atk:
                self._say(f"{o['name']} obeys {base}: already as close as it can get" if self._dist(o, foe) > 5 else f"{o['name']} obeys {base}: already beside {foe['name']}")
                continue
            path, cost = go if go else ([list(o["pos"])], 0)
            runs.append(self._new_r("mvatk", o, f"{base}", summary_targets="", path=path, cost=cost, no_oa=plan["free"],
                                    atks=[{"entry": atk["name"], "each": False, "adv": False, "extra": [], "noncrit": False}] if atk else [], foe=foe["id"]))
        return runs

    _CONTEST = re.compile(r"initiates an?(Intelligence|Wisdom|Charisma|Strength) contest with an? incapacitated (\w+) within (\d+) feet[^.]*\.[^.]*"
                          r"If it wins(?: the contest)?, [^.]*?(?:takes control of|controls) the target's body")

    _MARK = re.compile(r"\b(?:designates one creature [^.]*? as (?:his|her|its|their) prey|focuses on a single creature|sizes up a creature|"
                       r"(?:to )?mark prey that (?:it|he|she) has damaged|(?:magically )?marks one creature (?:it|he|she) can see)", re.I)      # Kivan's Mark, Prey, Assess Weakness, Relentless Hunter, Mark of Tharashk

    _ORDER = re.compile(r"\bissues orders to one ally\b[^.]*\.\s*If the target[^.]*?\bspend its reaction to move up to its speed|"
                        r"\bOne creature charmed by [^.]*? must use its reaction,? (?:if a? ?available,? )?to move up to its speed|"
                        r"\bEach creature within \d+ feet of [^.]*? that is (?:his|her|its) ally or is charmed by (?:him|her|it) must use its reaction to move", re.I)

    _FINISH = re.compile(r"The [\w' -]+? attacks a creature that has been marked by its (\w[\w' -]*?) ability\. If this attack hits and the creature has less than "
                         r"(\d+) hit points remaining after the attack, the creature is reduced to 0 hit points", re.I)

    _RAISE = re.compile(r"\btargets one dead (\w+) or (\w+) it can see within (\d+) feet[^.]*\.\s*The target is revived with all its hit points", re.I)   # Raise Ghoul

    _LINKED = re.compile(r"\btargets (?:one|a) creature within (\d+) feet of (?:it|itself) with which it has a psychic link")
    _PULSE = re.compile(r"(The target and )?[Ee]nemies of (?:the|its) [\w' -]+? within (\d+) feet of (?:that creature|the target|target)[^.]*?\btake\b")

    def _pulse_targets(self, att: dict, tgt: dict, text: str) -> Optional[list]:
        """An elder brain's Psychic Pulse: the creature it picks (when the text says so, or when it is a foe anyway) and the foes
        of the brain within 10 / 30 feet of it. None for any other text."""
        m = self._PULSE.search(text)
        if not m or not CR.damage_parts(text, now_only=True) or not tgt.get("pos"):
            return None
        ids = [tgt["id"]] if m.group(1) or self._hostile(att, tgt) else []
        for o in self.b["combatants"]:
            if o is att or o is tgt or not o.get("pos") or self._is_out(o) or not self._alive(o) or not self._hostile(att, o):
                continue
            if self._dist(tgt, o) <= int(m.group(2)):
                ids.append(o["id"])
        return ids

    def _shape_beasts(self, text: str) -> List[dict]:
        """The named forms a Change Shape offers: the beasts (and elementals) up to its challenge rating, and any monster it names
        ("or into an owlbear (see the Monster Manual)"): [{'value': monster id, 'label'}]."""
        from .spells import beast_options
        out = []
        for m in re.finditer(r"into an? (?:(?:tiny|small|medium|large|huge) )?([a-z]+) \(see the Monster Manual\)", text, re.I):
            mon = bestiary.get(f"{m.group(1).capitalize()}|MM")
            if mon:
                out.append({"value": mon["id"], "label": f"{mon['name']} (CR {mon['cr']}, {mon['hp']} HP)"})
        cr = re.search(r"\b(?:beast|elemental)s?\b[^.]*? with a challenge rating of (\d+(?:/\d+)?) or less", text, re.I)
        if cr:
            num, _, den = cr.group(1).partition("/")
            top = int(num) / int(den or 1)
            out += [o for o in beast_options(top) if o["value"] not in {x["value"] for x in out}]
            if re.search(r"\belemental\b", text, re.I):
                out += [{"value": e["id"], "label": f"{e['name']} (CR {e['cr']}, {e['hp']} HP)"}
                        for e in sorted(bestiary.offered() or bestiary.all, key=lambda e: (-float(e.get("cr_num") or 0), e["name"]))
                        if e.get("type") == "elemental" and e.get("source") == "MM" and float(e.get("cr_num") or 0) <= top]
        return out

    def _utility_target(self, att: dict, text: str) -> Optional[dict]:
        """How the bar aims an entry _utility_plan plays: {'target', 'range', 'options'}, or None."""
        if self._SHAPE.search(text):                     # Change Shape: which form (and back)
            forms = self._forms(att) + [w.capitalize() for w in re.findall(r"\binto (?:a |an )?(?:tiny |small |medium |large |huge )?([a-z]+)\b(?= or|,|\.)",
                                                                             text, re.I) if w.lower() not in ("its", "one", "the", "humanoid")] \
                + (["Mist"] if re.search(r"cloud of mist", text, re.I) else [])     # a vampire's mist form
            true = self._true_forms(att)
            opts = self._shape_beasts(text) + [{"value": f, "label": f"{f} form"} for f in dict.fromkeys(forms)
                                               if f.lower() not in true and f.lower() != (att.get("shape") or "").lower()]
            return {"target": {"type": "none"}, "range": None,
                    "options": (opts or ([] if att.get("shape") else [{"value": "other", "label": "Other form"}]))
                    + ([{"value": "true", "label": "True form"}] if att.get("shape") else [])}
        tp = self._TELEPORT.search(text)
        if tp:
            return {"target": {"type": "point", "teleport": True}, "range": int(tp.group(1) or tp.group(2))}
        if self._is_move(text):                          # a legendary "Move": walk up to its speed on someone else's turn
            feet = max(5, self._move_feet(att, text))
            return {"target": {"type": "point", "teleport": feet}, "range": feet}
        if re.search(r"(?:bestows|grants|gives) \d+[^.]*? temporary hit points (?:on|to) (?:another|one|a) creature", text):
            near = re.search(r"within (\d+) feet", text)       # temporary hit points for an ally
            return {"target": {"type": "creature", "count": 1, "allies": True}, "range": int(near.group(1)) if near else 30}
        if self._CONTEST.search(text):                   # Body Thief: one incapacitated humanoid next to it
            return {"target": {"type": "creature", "count": 1, "enemies": True}, "range": int(self._CONTEST.search(text).group(3))}
        if self._MARK.search(text):                      # Kivan's Mark, Assess Weakness: the creature it marks
            near = re.search(r"within (\d+) feet", text)
            return {"target": {"type": "creature", "count": 1, "enemies": True}, "range": int(near.group(1)) if near else None}
        rz = self._RAISE.search(text)
        if rz:                                           # Raise Ghoul: a dead ghoul or ghast within reach
            return {"target": {"type": "creature", "count": 1}, "range": int(rz.group(3))}
        if self._ORDER.search(text):                     # Reposition, Exert Will, Dance, My Puppet: the ally or charmed creature it orders
            if re.match(r"\s*Each creature", text):      # Sadistic Revelry: everyone near it
                return {"target": {"type": "none"}, "range": None}
            near = re.search(r"within (\d+) feet", text)
            return {"target": {"type": "creature", "count": 1, "allies": True}, "range": int(near.group(1)) if near else None,
                    **({"options": [{"value": "move", "label": "Move"}, {"value": "attack", "label": "Weapon attack"}]}
                       if re.search(r"or to make (?:a|one) weapon attack", text) else {})}
        if self._HEAL.search(text) and re.search(r"\b(?:the target|another creature|one creature|a creature)\b[^.]*\bregains|"
                                                 r"touches (?:another|one) creature\. (?:That|The) (?:creature|target) regains", text, re.I):
            near = re.search(r"within (\d+) feet", text)
            return {"target": {"type": "creature", "count": 1, "allies": True}, "range": int(near.group(1)) if near else 5}
        kinds = self._strike_types(text)
        if kinds:                                        # Giant's Strikes: which type of extra damage
            return {"target": {"type": "none"}, "range": None, "options": [{"value": t, "label": t.capitalize()} for t in kinds]}
        kinds = self._resist_choice(text)
        if kinds:                                        # Chromatic Resistance, Adaptive Skin: which type
            return {"target": {"type": "none"}, "range": None, "options": [{"value": t, "label": t.capitalize()} for t in kinds]}
        opts = self._summon_choices(att, text)
        if opts:
            return {"target": {"type": "none"}, "range": None,
                    "options": [] if opts[0].get("roll") else [{"value": o["value"], "label": o["label"]} for o in opts]}      # a table is rolled, not picked
        return None

    def _utility_plan(self, att: dict, text: str, target_id=None, point=None, option=None) -> Optional[dict]:
        """A stat block entry with no attack or save that still does something: teleport itself ("magically teleports ...
        up to 40 feet to an unoccupied space it can see"), heal itself or another ("The unicorn magically regains 11 (2d8 +
        2) hit points"), gain temporary hit points, summon creatures. Checks what it needs (raises), else None."""
        ut = self._utility_target(att, text)
        if self._SHAPE.search(text):
            opts = [o["value"] for o in ut["options"]]
            pick = option if option in opts else (opts[0] if opts else "true")
            mon = bestiary.get(pick) if pick not in ("true", "other") else None     # a named form: its stat block takes over (profile._monster)
            return {"kind": "shape", "to": None if pick == "true" else mon["name"] if mon else pick, "monster": mon["id"] if mon else None}
        if re.search(r"magically increases in size", text) and re.search(r"While enlarged", text):    # a duergar's Enlarge
            return {"kind": "buff", "conds": [], "until": None, "rounds": CR.duration_rounds(text) or 10,
                    "mods": {"enlarged": True, "size_step": 1, "save_adv": ["str"]} if re.search(r"Strength saving throws with advantage", text)
                    else {"enlarged": True, "size_step": 1}}
        dk = re.search(r"(\d+)-foot radius of magical darkness extends out from", text)
        if dk:                                           # a darkmantle's Darkness Aura: the Darkness spell's zone, round it, kept up by concentration
            return {"kind": "darkness_aura", "feet": int(dk.group(1))}
        if re.search(r"enters the Ethereal Plane from the Material Plane, or vice versa", text):
            return {"kind": "ethereal"}                     # a phantom warrior's Etherealness: there and back
        ct = self._CONTEST.search(text)
        if ct:
            tgt = self._target(target_id)
            if not K.incapacitated(self._conds(tgt)) or (ct.group(2).lower() == "humanoid" and str((self._monster(tgt) or {}).get("type") or
                                                                                                   ("humanoid" if self._sheet(tgt) else "")).lower() != "humanoid"):
                raise ServiceError(f"{tgt['name']} must be an incapacitated {ct.group(2).lower()}.")
            if att.get("pos") and tgt.get("pos") and self._dist(att, tgt) > int(ct.group(3)):
                raise ServiceError(f"{tgt['name']} is too far away.")
            return {"kind": "contest", "who": tgt["id"], "ab": ct.group(1)}
        if self._MARK.search(text):                        # prey: the extra damage / advantage counts against this creature only
            tgt = self._target(target_id)
            near = re.search(r"within (\d+) feet", text)
            if not self._hostile(att, tgt):
                raise ServiceError("Pick an enemy to mark.")
            if near and att.get("pos") and tgt.get("pos") and self._dist(att, tgt) > int(near.group(1)):
                raise ServiceError(f"{tgt['name']} is too far away.")
            mods = {}
            ex = re.search(r"(?:an )?(?:extra|additional) (?:\d+ \()?(\d+d\d+(?: ?[+-] ?\d+)?)\)? damage", text)
            if ex:
                mods["extra_damage"] = (ex.group(1).replace(" ", ""), "")
                mods["weapon_only"] = bool(re.search(r"with a weapon attack|damage from the weapon", text))
                mods["once_turn"] = bool(re.search(r"first time each turn", text))
            if re.search(r"has advantage on (?:all )?attack rolls against (?:it|the creature|that creature|the target)", text):
                mods["adv_by_source"] = True
            until = CR.until_of(text)
            return {"kind": "mark", "who": tgt["id"], "mods": mods, "until": until, "rounds": None if until else CR.duration_rounds(text)}
        fin = self._FINISH.match(text)
        if fin:                                            # Bhaal's Finish: an attack on its Prey; a hurt one is finished off
            mark = fin.group(1)
            tgt = next((o for o in self.b["combatants"] if o is not att and self._alive(o) and any(
                e.get("name") == mark and e.get("source_id") == att["id"] for e in o.get("effects") or [])), None)
            if tgt is None:
                raise ServiceError(f"Nothing to finish: {att['name']} has no {mark} marked.")
            atk = next((e for e in (self._monster(att) or {}).get("actions") or [] if re.search(r"Melee Weapon Attack:", e.get("text") or "")), None)
            if atk is None:
                raise ServiceError(f"{att['name']} has no melee attack.")
            rch = re.search(r"reach (\d+) ft", atk["text"])
            if att.get("pos") and tgt.get("pos") and self._dist(att, tgt) > (int(rch.group(1)) if rch else 5):
                raise ServiceError(f"{tgt['name']} is too far away to finish.")
            return {"kind": "execute", "who": tgt["id"], "limit": int(fin.group(2)), "entry": atk["name"], "text": atk["text"]}
        rz = self._RAISE.search(text)
        if rz:                                             # Raise Ghoul: it gets up again with all its hit points
            tgt = self._find_or_none(target_id or self.b.get("target"))
            if tgt is None:
                raise ServiceError("Pick the dead creature.")
            kind = str((self._monster(tgt) or {}).get("name") or "").lower()
            if tgt["kind"] == "pc" or tgt["hp"] > 0 or kind not in (rz.group(1).lower(), rz.group(2).lower()):
                raise ServiceError(f"{tgt['name']} isn't a dead {rz.group(1).lower()} or {rz.group(2).lower()}.")
            if att.get("pos") and tgt.get("pos") and self._dist(att, tgt) > int(rz.group(3)):
                raise ServiceError(f"{tgt['name']} is too far away.")
            return {"kind": "raise", "who": tgt["id"]}
        if self._ORDER.search(text):                       # an ally or a charmed creature spends its reaction to move (or strike) as it directs
            return self._order_plan(att, text, target_id, option)
        more = self._utility_more(att, text)               # reel in what it holds, a rally that ends conditions
        if more:
            return more
        tp = self._TELEPORT.search(text)
        if tp:
            if not point:
                raise ServiceError("Pick where to appear.")
            x, y = int(point[0]), int(point[1])
            if att.get("pos") and G.distance_to_tile(att["pos"], att.get("span") or 1, (x, y)) > int(tp.group(1) or tp.group(2)):
                raise ServiceError("That's too far.")
            if not self._tile_ok(att, x, y):
                raise ServiceError("That tile is taken or off the map.")
            return {"kind": "teleport", "to": (x, y), "carry": bool(re.search(r"creatures? it (?:has grappled|is grappling)", text))}
        if self._is_move(text):
            return self._move_plan(att, self._move_feet(att, text), point, bool(self._NO_OA.search(text)), "Move")
        h = self._HEAL.search(text)
        if h:
            dice = (h.group(2) or h.group(1)).replace(" ", "")
            if ut and ut["target"].get("allies"):
                who = self._find_or_none(target_id) or att
                if who is not att and att.get("pos") and who.get("pos") and self._dist(att, who) > max(5, ut["range"]):
                    raise ServiceError(f"{who['name']} is too far away.")
                return {"kind": "heal", "who": who["id"], "dice": dice}
            if re.search(r"^[^.]*?\bregain(?:s|ing)\b|(?<=\. )(?:It|He|She) regains|^[A-Z][\w' ]*? heals \d", text) \
                    and not re.search(r"\bif\b[^.]*regains|\btarget\b[^.]*regains", text, re.I):   # "Elkhorn regains 12", "Tiax heals 70", Zaratan's Revitalize
                return {"kind": "heal", "who": att["id"], "dice": dice}
        give = re.search(r"(?:bestows|grants|gives) (\d+)(?: \((\d+d\d+(?: ?[+-] ?\d+)?)\))? temporary hit points (?:on|to) (?:another|one|a) creature", text)
        if give:                                            # Trostani's Voice of Life: on another creature
            who = self._find_or_none(target_id) or att
            return {"kind": "temp", "dice": (give.group(2) or give.group(1)).replace(" ", ""), "who": who["id"]}
        neg = re.search(r"Creatures within (\d+) feet of [^,]+?,[^.]*?can't regain hit points until", text)
        if neg:                                             # a mummy lord's Channel Negative Energy
            return {"kind": "no_heal_area", "feet": int(neg.group(1)), "until": CR.until_of(text)}
        t = self._TEMP.search(text)
        if t and not re.search(r"equal to", text[t.start():t.end() + 30]):
            return {"kind": "temp", "dice": (t.group(2) or t.group(1)).replace(" ", "")}
        kinds = self._resist_choice(text)
        if kinds:                                           # "gains resistance to one damage type of its choice ... until the start of its next turn"
            until = CR.until_of(text)
            return {"kind": "buff", "mods": {"resist": [option if option in kinds else kinds[0]]}, "conds": [], "until": until,
                    "rounds": None if until else (CR.duration_rounds(text) or 1)}
        opts = self._summon_choices(att, text)
        if opts:
            rolled = None
            if opts[0].get("roll"):                          # a d6 table: the row the roll lands in (none: nothing comes)
                rolled = self.rng.randint(1, opts[0]["die"])
                pick = next((o for o in opts if o["roll"][0] <= rolled <= o["roll"][1]), None)
                if pick is None:
                    return {"kind": "summon_none", "rolled": rolled}
            else:
                pick = next((o for o in opts if o["value"] == option), opts[0])
            lose = re.search(r"loses (\d+) hit points for each", text)            # an elemental prince's Summon Elementals
            fail = re.search(r"If the attempt fails, [\w' -]+? takes (?:\d+ \()?(\d+d\d+(?: ?[+-] ?\d+)?)\)? (\w+) damage", text)     # a drow priestess's Summon Demon
            return {"kind": "summon", **pick, "rolled": rolled, "loses": int(lose.group(1)) if lose else 0,
                    "fail": [fail.group(1).replace(" ", ""), fail.group(2).lower()] if fail else None}
        cmd = self._COMMAND.search(text)
        if cmd:                                             # Command Allies, Ilneval's Command: allies strike with their reactions
            n = WORDS.get((re.search(r"up to (\w+) (?:allied |other )?(?:creatures|allies|\w+s)\b", text) or re.match("(one)", "one")).group(1), 1)
            near = re.search(r"within (\d+) feet", text)
            pool = [o for o in self.b["combatants"] if o is not att and o.get("pos") and att.get("pos") and not self._hostile(o, att)
                    and self._alive(o) and self._dist(att, o) <= (int(near.group(1)) if near else 60) and self._may_react(o)]
            pick = [o for o in pool if o["id"] == target_id] + [o for o in pool if o["id"] != target_id]    # the one aimed at first
            return {"kind": "command", "ids": [o["id"] for o in pick[:n]], "adv": bool(re.search(r"with advantage", text))}
        near = re.search(r"(?:nonhostile creature|creatures? of (?:its|the [\w' -]+?'s) choice|allies|each ally of [\w' -]+?|up to \w+ other creatures)"
                         r"[^.]*?within (\d+) feet", text, re.I)
        if near:                                            # Leadership's d4, a war chief's Battle Cry: its side, around it
            mods = {"attack": "1d4", "save": "1d4"} if re.search(r"add a d4", text) else \
                {"attacks_with": "adv"} if re.search(r"(?:advantage on|makes) attack rolls(?: with advantage)?", text) else {}
            immune = [c for c in ("Charmed", "Frightened") if re.search(r"can't be (?:charmed or )?" + c.lower() + r"|can't be charmed or frightened" if c == "Charmed"
                                                                        else r"can't be (?:charmed or )?frightened", text)]
            if immune:                                      # Infernal Command, Incite Fanaticism
                mods["immune_cond"] = immune
            if mods:
                until = CR.until_of(text)
                return {"kind": "rally", "feet": int(near.group(1)), "mods": mods, "self": "nonhostile" not in text,
                        "until": until, "rounds": None if until else (CR.duration_rounds(text) or 10)}
        au = re.search(r"fills a (\d+)-foot-radius sphere centered on itself\. While this aura is active, ([^.]*)\.", text)
        if au:                                              # a spirit champion's Aura of Fury / Resilience / Deception: it and its allies within the aura
            eff, mods = au.group(2).lower(), {"aura_ft": int(au.group(1))}
            if re.search(r"advantage on saving throws", eff):
                mods["save_adv"] = ["all"]
            if re.search(r"advantage on attack rolls", eff):
                mods["attacks_with"] = "adv"
            if re.search(r"disadvantage on attack rolls against", eff):
                mods["attacks_against"] = "dis"
            if len(mods) > 1:
                return {"kind": "buff", "mods": mods, "conds": [], "until": None, "rounds": CR.duration_rounds(text) or 10}
        low = text.lower()
        if re.search(r"giving (?:itself|himself|herself) the prone condition", low):      # a gibberling's Burrow
            return {"kind": "buff", "mods": {}, "conds": ["Prone"], "until": None, "rounds": None}
        if not re.search(r"\beach creature|\ballies\b|\ba creature\b", low):     # a self-buff: Shell Defense, a golem's Haste, Frenzy
            mods = {}
            ac = re.search(r"(?:gains?|gaining|has) an? \+(\d+)(?: bonus)? to (?:its |her |his )?(?:ac|armor class)", low)
            if ac:
                mods["ac"] = int(ac.group(1))
            if re.search(r"attack rolls? (?:made )?against (?:it|[\w' -]+?) (?:have|has) disadvantage", low):
                mods["attacks_against"] = "dis"                # Squirming Dodge, a professor's Contract
            if re.search(r"advantage on the next attack roll", low):
                mods["attacks_with"], mods["ends_on"] = "adv", ["attack"]      # Feint
            sp = re.search(r"\bspeed increases by (\d+) feet", low)
            if sp:
                mods["speed"] = int(sp.group(1))               # a gnoll's Sudden Rush
            rs = re.search(r"\bresistance to ((?:all|[a-z]+)(?:,? (?:and )?[a-z]+)*) damage", low)
            if rs and re.search(r"\b(?:has|gains?) resistance", low):
                kinds = list(M.TYPES) if rs.group(1).startswith("all") else [t for t in M.TYPES if re.search(r"\b%s\b" % t, rs.group(1))]
                if kinds:
                    mods["resist"] = kinds                     # Phase, a zaratan's Retract
            if re.search(r"\bhas advantage on attack rolls\b(?! against)", low):
                mods["attacks_with"] = "adv"
            sv = re.search(r"advantage on ((?:(?:strength|dexterity|constitution|intelligence|wisdom|charisma)(?:,? (?:and |or )?)?)+) saving throws", low)
            if sv:
                mods["save_adv"] = [CR.ABILITIES[a] for a in re.findall(r"strength|dexterity|constitution|intelligence|wisdom|charisma", sv.group(1))]
            sc = re.search(r"advantage on (strength|dexterity|constitution|intelligence|wisdom|charisma) checks and \1 saving throws", low)
            if sc:                                             # Rage, Vaprak's Rage, Overdrive: Strength checks and saves
                mods["check_adv"] = mods["save_adv"] = [CR.ABILITIES[sc.group(1)]]
            dm = re.search(r"gains? an? \+(\d+) bonus to (?:the )?damage|deals an extra (\d+) damage when (?:he|she|it) hits a target with a melee weapon attack", low)
            if dm:                                             # Rage, Overdrive: +4 on its melee weapon damage
                mods["dmg"] = (dm.group(1) or dm.group(2), "")
                mods["melee_only"] = True
            ex = re.search(r"melee attacks? each deal an extra (?:\d+ \()?(\d+d\d+)\)? damage of a type determined", low)
            if ex:                                             # Giant's Strikes: the type is the pick (_utility_target)
                sk = self._strike_types(text)
                mods["dmg"] = (ex.group(1), option if option in sk else (sk[0] if sk else ""))
                mods["melee_only"] = True
            ts = re.search(r"\b(?:speed|movement) increases to (\d+)", low)
            if ts and int(ts.group(1)) > self._speeds(att).get("walk", 30):        # Overdrive, Bladesong
                mods["speed"] = int(ts.group(1)) - self._speeds(att).get("walk", 30)
            fl = re.search(r"gains? a flying speed of (\d+) feet", low)
            if fl:
                mods["fly"] = int(fl.group(1))                 # Abyssal Visage
            ig = re.search(r"\bis immune to (\w+) damage and the (\w+) condition", low)
            if ig and ig.group(1) in M.TYPES:
                mods["immune"], mods["immune_cond"] = [ig.group(1)], [ig.group(2).capitalize()]
            tr = re.search(r"gains truesight within (\d+) feet", low)
            if tr:
                mods["senses"] = {"truesight": int(tr.group(1))}      # Silver Fire
            if re.search(r"advantage on attack rolls against any creature that doesn't have all its hit points", low):
                mods["adv_vs_hurt"] = True                     # Abyssal Visage: a hurt creature (resolve._attack_check)
            im = re.search(r"creates (two|three|four) illusory duplicates of itself", low)
            if im:
                mods["images"] = WORDS[im.group(1)]            # a noonwraith's Noonday Mirage: Mirror Image's duplicates (resolve._mirror_image)
            if re.search(r"speed is 0", low):
                mods["speed_set"] = 0
            if re.search(r"the only actions? (?:it|he|she) can take is|can't take any other actions", low):
                mods["shell_locked"] = True                    # a tortle's Shell Defense: nothing but emerging (spells.py _pay)
            if re.search(r"can't take (?:any )?(?:other )?reactions|actions or reactions", low):
                mods["no_reactions"] = True
            if mods:
                conds = [c for c, rx in (("Prone", r"falls prone|is prone"), ("Restrained", r"and is restrained")) if re.search(rx, low)]
                until = CR.until_of(text)
                this_turn = bool(re.search(r"until the end of (?:its|his|her|the \w+'s) turn", low))      # Giant's Strikes
                return {"kind": "buff", "mods": mods, "conds": conds, "until": until, "until_end": this_turn,
                        "conc": bool(re.search(r"maintains concentration", low)),
                        "rounds": None if until or this_turn or re.search(r"until (?:it|she|he) (?:emerges|takes its emerge action)", low)
                        else (10 if "maintains concentration" in low else CR.duration_rounds(text) or 1)}
        return None

    def _utility_do(self, att: dict, base: str, plan: dict) -> str:
        if plan["kind"] in ("reel", "cleanse", "leave"):
            return self._utility_more_do(att, base, plan)
        if plan["kind"] == "command":
            strikes = self._command_strikes(att, base, plan["ids"], plan["adv"])
            if not strikes:
                return f"{att['name']} uses {base}: no ally can strike"
            strikes[0]["follow"] = strikes[1:]
            self._say(f"{att['name']} uses {base}")
            return self._run_r(strikes[0])
        if plan["kind"] == "ethereal":
            gone = [e for e in att.get("effects") or [] if e.get("name") == "Ethereal" and e.get("source_id") == att["id"]]
            for e in gone:
                self._effect_off(att, e, "back on the Material Plane")
            if gone:
                return f"{att['name']} uses {base}: back on the Material Plane"
            self._effect_on(att, "Ethereal", [], None, None, None, None, att["name"], {"untargetable": True, "banished": False}, None, att["id"])
            return f"{att['name']} uses {base}: on the Ethereal Plane (can't affect or be affected)"
        if plan["kind"] == "execute":                        # Finish: one attack at the Prey; if it hit and left it under the limit, it drops
            tgt = self._find(plan["who"])
            hp0 = self._hp_of(tgt)
            S = self._monster_strike(att, tgt, plan["entry"], plan["text"], label=f"{plan['entry']} ({base})")
            if att.get("pos") and tgt.get("pos"):
                S["atk"] = self._check_reach(att, tgt, S["atk"])
            self._say(f"{att['name']} uses {base} on {tgt['name']}")
            out = self._run_r(S)
            if not self.pending() and self._hp_of(tgt) < hp0 and 0 < self._hp_of(tgt) < plan["limit"]:
                self._say(f"{tgt['name']} is finished: " + self._deal_rolled(tgt, [[self._hp_of(tgt), ""]], by=att, label=base))
            return out
        if plan["kind"] == "raise":                          # Raise Ghoul
            who = self._find(plan["who"])
            who["hp"] = who["max_hp"]
            for cond in [x for x in self._conds(who) if x in ("Unconscious", "Prone", "Paralyzed")]:
                self._cond(who, cond, False)
            who.pop("downed", None)
            who.pop("dead", None)
            self._vfx("heal", id=who["id"], amt=int(who["max_hp"]))
            return f"{att['name']} uses {base}: {who['name']} rises again with {who['max_hp']} hit points"
        if plan["kind"] == "order":                          # Reposition, Exert Will, Dance My Puppet, Sadistic Revelry
            runs = self._order_runs(att, base, plan)
            if not runs:
                return f"{att['name']} uses {base}: nobody could obey"
            runs[0]["follow"] = runs[1:]
            self._say(f"{att['name']} uses {base}")
            return self._run_r(runs[0])
        if plan["kind"] == "mark":                           # one prey at a time: a new mark takes the old one off
            tgt = self._find(plan["who"])
            for o in self.b["combatants"]:
                for e in [e for e in o.get("effects") or [] if e.get("name") == base and e.get("source_id") == att["id"] and o is not tgt]:
                    self._effect_off(o, e, "a new prey")
            self._effect_on(tgt, base, [], None, None, None, plan["rounds"], att["name"], dict(plan["mods"]), None, att["id"],
                            until=self._until(plan["until"], att, tgt) if plan["until"] else None)
            ex = plan["mods"].get("extra_damage")
            bits = ([f"+{ex[0]} damage on its first hit each turn" if plan["mods"].get("once_turn") else f"+{ex[0]} damage on its hits"] if ex else []) + \
                (["advantage on attacks against it"] if plan["mods"].get("adv_by_source") else [])
            return f"{att['name']} uses {base} on {tgt['name']}" + (f": {'; '.join(bits)}" if bits else "")
        if plan["kind"] == "contest":                        # Body Thief: an Intelligence contest, then it rides the body
            tgt = self._find(plan["who"])
            mine, theirs = self._check(att, plan["ab"]), self._check(tgt, plan["ab"])
            if mine <= theirs:
                return f"{att['name']} uses {base} on {tgt['name']}: fails ({mine} vs {theirs})"
            self._effect_on(tgt, base, ["Incapacitated"], None, None, None, None, att["name"], {"possessed_by": att["id"]}, None, att["id"])
            att["possessing"], att["pos"] = tgt["id"], None
            return f"{att['name']} uses {base}: wins ({mine} vs {theirs}) and takes over {tgt['name']}'s body"
        if plan["kind"] == "shape":                          # its form's entries come on the bar, the others go
            m = self._monster(att) or {}
            att.setdefault("true_ac", att["ac"])
            if re.search(r"\bin (?:humanoid|human|elf|true) form", m.get("ac_note") or "", re.I):
                att["ac"] = att["true_ac"] + (1 if plan["to"] else 0)   # MM lycanthropes: 11 as a human, 12 (natural armor) otherwise
            att["shape"] = plan["to"]
            if plan.get("monster"):                          # Doric's owlbear: attacks, AC and speed from that stat block, her own hit points
                att["form"] = {"monster": plan["monster"], "hp": 0, "max_hp": 0, "name": plan["to"], "keeps_hp": True}
            else:
                att.pop("form", None)
            for e in [e for e in att.get("effects") or [] if e.get("name") == "Mist form"]:
                self._effect_off(att, e, "solid again")
            mist = next((t.get("text") or "" for t in m.get("traits") or [] if re.search(r"While in mist form", t.get("text") or "")), "")
            if plan["to"] == "Mist" and mist:                  # weightless, hard to hurt, no actions but moving
                mods = {"resist": ["nonmagical"]} if re.search(r"immune to all nonmagical damage|resistance to nonmagical", mist) else {}
                sv = re.search(r"advantage on ((?:(?:strength|dexterity|constitution)(?:,? (?:and )?)?)+) saving throws", mist, re.I)
                if sv:
                    mods["save_adv"] = [CR.ABILITIES[a.lower()] for a in re.findall(r"strength|dexterity|constitution", sv.group(1), re.I)]
                self._effect_on(att, "Mist form", [], None, None, None, None, att["name"], mods or {"mist": True}, None, att["id"])
            self._vfx("blink", id=att["id"], at=att.get("pos"), to=att.get("pos"))
            return f"{att['name']} uses {base}: " + (f"now in {plan['to'].lower()} form" if plan["to"] and plan["to"] != "other"
                                                     else "changes shape" if plan["to"] else "back in its true form")
        if plan["kind"] == "teleport":
            held = [o for o in self.b["combatants"] if plan.get("carry")
                    and any((e.get("mods") or {}).get("grappler") == att["id"] for e in o.get("effects") or [])]
            self.teleport(att["id"], *plan["to"])
            for o in held:                                  # a balhannoth takes what it holds along
                spot = self._free_near(o, *plan["to"])
                if spot:
                    o["pos"] = list(spot)
            return f"{att['name']} teleports ({base})" + (f" with {', '.join(o['name'] for o in held)}" if held else "")
        if plan["kind"] == "move":
            return self._move_walk(att, base, plan)
        if plan["kind"] == "heal":
            who = self._find(plan["who"])
            n = roll(plan["dice"])
            self._heal(who, n)
            return f"{att['name']} uses {base}: {who['name']} regains {n} hit points"
        if plan["kind"] == "temp":
            n = roll(plan["dice"])
            who = self._find_or_none(plan.get("who")) or att
            self._give_temp(who, n)
            return f"{att['name']} uses {base}: " + (f"{who['name']} gains " if who is not att else "") + f"{n} temporary hit points"
        if plan["kind"] == "no_heal_area":
            hit = [o for o in self.b["combatants"] if o is not att and o.get("pos") and att.get("pos") and self._dist(att, o) <= plan["feet"]
                   and not self._is_out(o)]
            for o in hit:
                self._effect_on(o, base, [], None, None, None, None if plan["until"] else 1, att["name"], {"no_heal": True}, None, att["id"],
                                until=self._until(plan["until"], att, o) if plan["until"] else None)
            return f"{att['name']} uses {base}: " + (", ".join(o["name"] for o in hit) or "nobody") + " can't regain hit points"
        if plan["kind"] == "buff":                           # until it emerges: the DM ends it (or its own end)
            if plan.get("conc"):                             # Phase: kept up by concentration
                self._start_conc(att, {"name": base, "duration": "Concentration, up to 1 minute"})
            self._effect_on(att, base, plan["conds"], None, None, None, plan["rounds"], att["name"], dict(plan["mods"]), att["id"] if plan.get("conc") else None,
                            att["id"], until=self._until(plan["until"], att, att) if plan["until"] else
                            {"end": att["id"], "skip": 0} if plan.get("until_end") else None)
            bits = ([f"+{plan['mods']['ac']} AC"] if plan["mods"].get("ac") else []) + \
                (["advantage on attacks"] if plan["mods"].get("attacks_with") else []) + [c.lower() for c in plan["conds"]] + \
                ([f"+{plan['mods']['dmg'][0]}{' ' + plan['mods']['dmg'][1] if plan['mods']['dmg'][1] else ''} melee damage"] if plan["mods"].get("dmg") else []) + \
                (["advantage on attacks against hurt creatures"] if plan["mods"].get("adv_vs_hurt") else []) + \
                ([f"{plan['mods']['aura_ft']}-ft aura for it and its allies"] if plan["mods"].get("aura_ft") else []) + \
                (["advantage on saves"] if plan["mods"].get("save_adv") == ["all"] else []) + \
                ([f"{k} {v} ft" for k, v in (("fly", plan["mods"].get("fly")), ("truesight", (plan["mods"].get("senses") or {}).get("truesight"))) if v]) + \
                (["attacks against it have disadvantage"] if plan["mods"].get("attacks_against") == "dis" else []) + \
                ([f"{plan['mods']['images']} illusory duplicates"] if plan["mods"].get("images") else []) + \
                ([f"+{plan['mods']['speed']} ft speed"] if plan["mods"].get("speed") else []) + \
                (["resistance to " + ("all damage" if len(plan["mods"]["resist"]) >= len(M.TYPES) else ", ".join(plan["mods"]["resist"]))]
                 if plan["mods"].get("resist") else [])
            return f"{att['name']} uses {base}" + (f": {', '.join(bits)}" if bits else "")
        if plan["kind"] == "darkness_aura":
            if not att.get("pos"):
                return f"{att['name']} uses {base}"
            self._start_conc(att, {"name": base, "duration": "Concentration, up to 10 minutes"})
            area = {"shape": "emanation", "size": plan["feet"], "origin": "caster"}
            tiles = G.area_for(area, att["pos"], att.get("span") or 1, None, *self._bounds())
            self._add_zone(att, base, sorted(tiles), {"darkness": True, "follow": True}, rounds=100, conc=att["id"], area=area)
            return f"{att['name']} uses {base}: magical darkness {plan['feet']} ft around it, moving with it (concentration)"
        if plan["kind"] == "rally":
            who =[o for o in self.b["combatants"] if o.get("pos") and att.get("pos") and not self._hostile(o, att) and self._alive(o)
                   and (o is not att or plan["self"]) and self._dist(att, o) <= plan["feet"]]
            for o in who:
                self._effect_on(o, base, [], None, None, None, plan["rounds"], att["name"], dict(plan["mods"]), None, att["id"],
                                until=self._until(plan["until"], att, o) if plan["until"] else None)
            bits = (["+1d4 to attacks and saves"] if "save" in plan["mods"] else []) + (["advantage on attacks"] if plan["mods"].get("attacks_with") else []) \
                + ([f"can't be {' or '.join(x.lower() for x in plan['mods']['immune_cond'])}"] if plan["mods"].get("immune_cond") else [])
            return f"{att['name']} uses {base}: " + (", ".join(o["name"] for o in who) or "nobody near") + (f" ({'; '.join(bits)})" if bits else "")
        if plan["kind"] == "summon_none":                    # a table row with no creature
            return f"{att['name']} uses {base}: rolls {plan['rolled']}, nothing answers"
        if plan.get("chance") and self.rng.randint(1, 100) > int(plan["chance"]):
            if plan.get("fail"):                              # "If the attempt fails, the drow takes 5 (1d10) psychic damage"
                self._say(f"{att['name']} uses {base}: the summoning fails")
                return self._run_r(self._strike(att, base, [att["id"]], mode="auto", parts=[tuple(plan["fail"])], magical=True))
            return f"{att['name']} uses {base}: the summoning fails"
        cnt = plan["count"]
        n = WORDS.get(cnt, 1) if not re.search(r"\d", cnt) else (roll(cnt) if "d" in cnt else int(cnt))
        made = self._add_summons(att, plan["monster"], max(1, min(10, n)), plan.get("name"), 1, None, None, None)
        for c in made:
            c["faction"] = self._side(att)
            st = plan.get("stats")
            if st:                                           # Animate Chains: objects with their own AC, hit points and defences
                c["hp"] = c["max_hp"] = st["hp"]
                c["ac"] = st["ac"]
                self._effect_on(c, plan.get("name") or base, [], None, None, None, None, att["name"], dict(st["mods"]), None, att["id"])
            self._vfx("summon", id=c["id"], type=str((bestiary.get(c.get("monster")) or {}).get("type") or "").lower(), src=None, tier=1)
        cost = plan.get("loses", 0) * len(made)
        if cost and att["kind"] != "pc":                   # "loses 30 hit points for each elemental she summons"
            att["hp"] = max(1, att["hp"] - cost)
        return f"{att['name']} uses {base}" + (f" (rolls {plan['rolled']})" if plan.get("rolled") else "") + ": " + ", ".join(c["name"] for c in made) + \
            " appear" + (f" ({cost} hit points lost)" if cost else "")

    # ---- more entries with no roll: reeling in what it holds, ending conditions, going invisible
    _INVIS = re.compile(r"magically (?:turns?|becomes?) invisible|(?:now )?has the invisible condition|\bbecomes? invisible\b(?! to\b)|"
                        r"\bcan become invisible\b", re.I)
    def _held_targets(self, att: dict, text: str, target_id=None, targets=None) -> Optional[list]:
        """An entry with no roll that hurts what it holds: "One creature that Olhydra is grappling is crushed for 21 (3d10 + 5)
        damage", "One creature charmed by the aboleth takes 10 (3d6) psychic damage", "Each creature restrained by Arasta's Web of
        Hair takes ...", a tick's Blood Drain on what it is attached to, a hertilod's gullet. The ids it works on (the one picked,
        when it names one creature), None for any other text, a refusal when it holds no one."""
        if not CR.damage_parts(text, now_only=True):
            return None
        head = ""
        for sent in re.split(r"(?<=\.)\s+", text):          # up to the end of the first sentence that says damage
            head += sent + " "
            if re.search(r"\bdamage\b", sent):
                break
        kinds = [k for k, rx in (("grappler", r"grappl(?:ed|ing)"), ("attached", r"\battached to\b"), ("swallowed_by", r"\bgullet\b"),
                                 ("Restrained", r"\brestrained by\b"), ("Charmed", r"\bcharmed by\b")) if re.search(rx, head)]
        if not kinds or re.search(r"\bfling|\bswallows\b", text, re.I):
            return None
        held = []
        for o in self.b["combatants"]:
            if o is att or self._is_out(o):
                continue
            for e in o.get("effects") or []:
                mods = e.get("mods") or {}
                if any(mods.get(k) == att["id"] if k in ("grappler", "attached", "swallowed_by") else
                       (k in (e.get("conditions") or []) and e.get("source_id") == att["id"]) for k in kinds):
                    held.append(o["id"])
                    break
        if not held:
            raise ServiceError(f"{att['name']} has nobody that fits ({' / '.join(k.lower() for k in kinds)}).")
        if re.search(r"\b(?:each|any number of|all) creatures?\b", head, re.I):
            return held
        want = [t for t in (targets or [target_id] or []) if t in held]
        return want[:1] or held[:1]

    @staticmethod
    def _strike_types(text: str) -> list:
        """The damage types a Giant's Strikes picks from ("cold (frost giant), fire (fire giant), ... or thunder (cloud giant)"), or []."""
        m = re.search(r"extra (?:\d+ \()?\d+d\d+\)? damage of a type determined by [^:]*:(.{0,260}?)(?:\.|$)", text, re.I | re.S)
        return [t for t in M.TYPES if m and re.search(r"\b%s\b" % t, m.group(1), re.I)]

    @staticmethod
    def _resist_choice(text: str) -> list:
        """The damage types an entry lets it pick one resistance from ("gains resistance to one damage type of its choice: acid, fire,
        lightning, or thunder"), or []."""
        m = re.search(r"gains resistance to one damage type of (?:his|her|its|their) choice(.{0,120}?)(?:until|$)", text, re.I | re.S)
        return [t for t in M.TYPES if m and re.search(r"\b%s\b" % t, m.group(1), re.I)]

    _REEL = re.compile(r"\bpulls? (?:each creature|the target|the creature)\b[^.]*?\bgrappled\b[^.]*?\bup to (\d+) feet", re.I)
    _CLEANSE = re.compile(r"\bends (?:any effects? causing )?the ([a-z, ]+?) conditions? on (?:itself|herself|himself)", re.I)

    def _utility_more(self, att: dict, text: str) -> Optional[dict]:
        """Reel ("pulls each creature grappled by it up to 25 feet straight toward it"), a rally ("ends the charmed and
        frightened conditions on itself and each creature of its choice within 30 feet"): the plan, or None."""
        rl = self._REEL.search(text)
        if rl:
            held = [o["id"] for o in self.b["combatants"] if o is not att and any((e.get("mods") or {}).get("grappler") == att["id"]
                                                                                    for e in o.get("effects") or [])]
            if not held:
                raise ServiceError(f"{att['name']} isn't holding anyone.")
            return {"kind": "reel", "ids": held, "feet": int(rl.group(1))}
        lv = re.search(r"\bteleports itself(?: and up to (\w+) willing creatures it can see within (\d+) feet of it)?[^.]*?\bup to \d+ miles? away", text)
        if lv:                                              # a unicorn's Teleport: to somewhere far off the map, with up to three companions
            near = int(lv.group(2)) if lv.group(2) else 0
            pool = [o for o in self.b["combatants"] if near and o is not att and o.get("pos") and att.get("pos") and not self._hostile(o, att)
                    and self._alive(o) and self._dist(att, o) <= near]
            return {"kind": "leave", "ids": [o["id"] for o in pool[:WORDS.get(lv.group(1), 0)]]}
        cl = self._CLEANSE.search(text)
        if cl:
            conds = [c.capitalize() for c in re.findall(r"[a-z]+", cl.group(1)) if c.capitalize() in K.ALL]
            near = re.search(r"within (\d+) feet", text)
            if conds:
                allies = bool(re.search(r"\beach creature|\bany number of allies|\ballies\b", text)) and near
                return {"kind": "cleanse", "conds": conds, "feet": int(near.group(1)) if allies else 0}
        return None

    def _utility_more_do(self, att: dict, base: str, plan: dict) -> str:
        if plan["kind"] == "leave":                          # off the map (the DM can put it back with a click)
            gone = [att] + [o for o in (self._find_or_none(i) for i in plan["ids"]) if o is not None]
            for o in gone:
                self._vfx("blink", id=o["id"], at=o.get("pos"), to=o.get("pos"))
                o["pos"] = None
            return f"{att['name']} teleports away" + (f" with {', '.join(o['name'] for o in gone[1:])}" if len(gone) > 1 else "") + " (off the map)"
        if plan["kind"] == "reel":
            for oid in plan["ids"]:
                o = self._find_or_none(oid)
                if o is not None:
                    self._push(o, att, -plan["feet"])
            return f"{att['name']} uses {base}: " + ", ".join(self._find(i)["name"] for i in plan["ids"] if self._find_or_none(i)) + " reeled in"
        who = [att] + [o for o in self.b["combatants"] if o is not att and plan["feet"] and o.get("pos") and att.get("pos")
                       and not self._hostile(o, att) and self._alive(o) and self._dist(att, o) <= plan["feet"]]
        freed = []
        for o in who:
            had = [c for c in plan["conds"] if c in self._conds(o)]
            if had:
                self._clear_conditions(o, had)
                freed.append(o["name"])
        return f"{att['name']} uses {base}: " + (f"{', '.join(freed)} freed of {' and '.join(c.lower() for c in plan['conds'])}" if freed else "nobody was affected")

    def _mark_used(self, c: dict, base: str, recharge, per_day):
        if base.startswith("Lair") and any(e["name"] == base for e in self._lair_actions(c)):
            c["lair_round"] = self.b.get("round")               # one lair action a round
        if recharge:
            c.setdefault("spent", {})[base] = int(recharge.group(1))
        if per_day:
            u = c.setdefault("uses_day", {})
            u[base] = u.get(base, 0) + 1

    def _recharge_roll(self, c: dict):
        """At the start of its turn a monster rolls for each spent Recharge ability."""
        for name, need in list((c.get("spent") or {}).items()):
            r = self.rng.randint(1, 6)
            if r >= int(need):
                del c["spent"][name]
                self._vfx("recharge", id=c["id"], name=name)  # it glints: ready again
                self._say(f"{c['name']}: {name} recharges ({r})")
            else:
                self._npc_roll(c, "🎲", f"{name} recharge", r, f"needs {need}+")

    # ------------------------------------------------------------------ checks and contests
    def _check(self, c: dict, skill: str, mode: Optional[str] = None, dc: Optional[int] = None) -> int:
        char = self._sheet(c)
        if char:
            bonus = char.skill_bonus(skill)["bonus"] if skill in rules.skills else char.mod(skill[:3].lower())
        else:
            m = self._monster(c)
            g = re.search(skill + r"\s*([+-]\d+)", (m or {}).get("skills", "") or "", re.I)
            ab = {"Athletics": "str", "Acrobatics": "dex", "Stealth": "dex", "Perception": "wis"}.get(skill, skill[:3].lower()
                                                                                                    if skill[:3].lower() in ("str", "dex", "con", "int", "wis", "cha") else "str")
            bonus = int(g.group(1)) if g else self._ability(c, ab)
        cm = K.check_mode(self._conds(c), self._exhaustion(c))
        modes = {x for x in (mode, cm) if x}
        abil = (rules.skills.get(skill) or {}).get("ability") or skill[:3].lower()
        helping = [e for e, v in self._fx(c, "check_adv") if M.abilities_hit(v, abil)]      # a list: only those abilities (Puzzler's Wit: Intelligence)
        if helping or any(skill in v for _e, v in self._fx(c, "skill_adv")):     # skill_adv: Cloak of Elvenkind (wondrous.py)
            modes.add("adv")
            for e in helping:
                if (e.get("mods") or {}).get("once") and e in (c.get("effects") or []):
                    self._effect_off(c, e, "used")
        total, kept, _d = self._d20_roll(c, bonus, K.combine(modes))
        if char and kept < 10 and char.class_level("Rogue") >= 11 and skill in char.d["proficiencies"]["skills"]:
            total += 10 - kept                                  # Reliable Talent: a 9 or lower on a proficient check counts as 10
        extra, _n = self._mod_roll(c, "check")
        extra += self._nf_check_bonus(c, skill)                 # the d4 of the Marks and Arcane Eloquence (newfeats.py)
        self._use_once(c, "check")
        if dc is not None and total + extra < dc:
            extra += self._sub_check_boost(c, skill, total + extra, dc)       # Psi-Bolstered Knack (subfeats.py)
        return total + extra

    def _passive(self, c: dict) -> int:
        char = self._sheet(c)
        if char:
            return char.passive_perception
        m = self._monster(c)
        return int((m or {}).get("passive") or 10)

    def bonus_standard(self, c: dict) -> List[str]:
        """Dash / Disengage / Hide that a monster may take as a bonus action (a goblin's Nimble Escape)."""
        m = None if self._sheet(c) else self._monster(c)
        out: List[str] = ["hide"] if self._mantle_hide(c) and self._lightly_obscured(c) else []     # Nature's Mantle (spellitems.py)
        for e in ((m or {}).get("traits") or []) + ((m or {}).get("bonus_actions") or []):
            g = BONUS_STD.search(e.get("text") or "")
            if g and (g.group(1) or g.group(2) or e in ((m or {}).get("bonus_actions") or [])):     # the bare wording only as a bonus action
                out += [w.lower() for w in re.findall(r"Dash|Disengage|Hide", g.group(1) or g.group(2) or g.group(3)) if w.lower() not in out]
            elif re.search(r"bonus action, the [\w -]+ can move up to its speed toward a hostile creature", e.get("text") or "") \
                    and "dash" not in out:
                out.append("dash")                              # an orc's Aggressive: a bonus-action dash at the foe
        return out

    def standard_action(self, cid: int, key: str, target_id: Optional[int] = None, option: Optional[str] = None,
                        as_bonus: bool = False) -> str:
        if key == "use_object" and option:                  # a potion, caltrops...: its own action (and its own undo step)
            with self.lock:
                has = any(o["value"].lower() == str(option).lower() for o in self.use_options(self._find(cid)))
            if has:
                return self.use_item(cid, option, target_id if target_id not in (None, cid) else None)
        with self.lock:
            self._busy()
            if key not in STANDARD:
                raise ServiceError("Unknown action.")
            c = self._find(cid)
            name, cost, _t = STANDARD[key]
            if as_bonus:
                if key not in self.bonus_standard(c):
                    raise ServiceError(f"{c['name']} can't {name.lower()} as a bonus action.")
                cost = "bonus"
            tgt = self._find_or_none(target_id or self.b.get("target"))
            if key == "stabilize":
                if not tgt or tgt["kind"] != "pc" or self._hp_of(tgt) > 0:
                    raise ServiceError("Pick a dying character next to you.")
            if key in ("help", "grapple", "shove", "stabilize") and not tgt:
                raise ServiceError("Pick a target first.")
            far = 30 if key == "help" and tgt and self._hostile(c, tgt) and self._nf_has(c, "Harper Agent") else max(5, self._reach(c))   # Distracting Melody
            if key in ("help", "grapple", "shove") and tgt and c.get("pos") and tgt.get("pos") and self._dist(c, tgt) > far:
                raise ServiceError(f"{tgt['name']} is too far away")
            if key == "hide":
                self._check_can_hide(c)
            if key == "dash" and self._fx(c, "no_dash"):          # Uncertain Footing: illusory obstacles
                raise ServiceError(f"{c['name']} can't take the Dash action.")
            if key == "stand_up":
                if "Prone" not in self._conds(c):
                    raise ServiceError(f"{c['name']} isn't prone.")
                cost = f"move:{5 if self._subc_leap(c) else max(5, self._speed(c) // 2)}"      # Leap to Your Feet (subfeats_c.py)
            if key in ("grapple", "shove"):
                char = self._sheet(c)
                self._pay_attack(c, F.extra_attacks(char) if char else self._multiattack_count(c), name)
            else:
                self._pay(c, cost, name)
            self._vfx("action", id=c["id"], key=key, name=name, other=tgt["id"] if tgt and tgt is not c else None)   # its look on the maps
            t = c.get("turn")
            line = f"{c['name']} takes the {name} action"
            if key == "dash":
                EC.dash(t)
                line = f"{c['name']} dashes" + (f" ({t['move']} ft of movement left)" if t else "")
            elif key == "disengage":
                if t is not None:
                    t["disengaged"] = True
                line = f"{c['name']} disengages"
            elif key == "dodge":
                self._effect_on(c, "Dodge", [], None, None, None, None, c["name"], {"attacks_against": "dis", "save_adv": ["dex"]}, None, c["id"],
                                until={"start": c["id"]})
                line = f"{c['name']} dodges"
                char = self._sheet(c)
                if self._feat(c, "dwarven_fortitude") and char:
                    die = next((k for k, hd in char.hit_dice().items() if hd["used"] < hd["total"]), None)
                    if die:
                        _roll, healed = self.chars.spend_hit_die(char.name, die)
                        line += f" and spends a Hit Die (+{healed} HP, Dwarven Fortitude)"
            elif key == "help":
                self._effect_on(tgt, f"Helped against ({c['name']})", [], None, None, None, None, c["name"], {"attacks_against": "adv", "once": True},
                                None, c["id"], until={"start": c["id"]})
                line = f"{c['name']} helps: the next attack on {tgt['name']} has advantage"
                self._nf_help(c, tgt)                           # Withering Wordplay (newfeats.py)
            elif key == "hide":
                seers = [o for o in self.b["combatants"] if self._hostile(o, c) and o.get("pos") and self._alive(o)]
                best = max([self._passive(o) for o in seers] or [0])
                total = self._check(c, "Stealth", dc=best)
                if total >= best:
                    self._effect_on(c, "Hidden", [], None, None, None, None, c["name"], {"hidden": total, "attacks_with": "adv", "ends_on": ["attack", "cast"]},
                                    None, c["id"])
                    line = f"{c['name']} hides (Stealth {total})"
                else:
                    line = f"{c['name']} tries to hide but is spotted (Stealth {total} vs {best})"
            elif key == "search":
                sharp = self._nf_search_mode(c)                 # Sharp Eye: advantage, a use spent only when the check succeeds (newfeats.py)
                total = self._check(c, "Perception", sharp)
                if sharp and total >= 10:
                    self._cf_use(c, "Sharp Eye")
                found = []
                for o in self.b["combatants"]:
                    for e, v in self._fxs(o, "hidden"):
                        if self._hostile(o, c) and int(v) <= total and e in (o.get("effects") or []):
                            self._effect_off(o, e, f"found by {c['name']}")
                            found.append(o["name"])
                line = f"{c['name']} searches (Perception {total})" + (": finds " + ", ".join(found) if found else ": nothing")
            elif key == "ready":
                c["readied"] = option or "an action"
                line = f"{c['name']} readies {c['readied']}"
                self._nf_ready(c)                               # Vigilant (newfeats.py)
            elif key == "use_object":
                line = f"{c['name']} uses an object" + (f" ({option})" if option else "")
            elif key in ("grapple", "shove"):
                if SIZES.index(self._size_of(tgt)) > SIZES.index(self._size_of(c)) + 1:
                    raise ServiceError(f"{tgt['name']} is too big to {key}.")
                mine = self._check(c, "Athletics")
                theirs = max(self._check(tgt, "Athletics"), self._check(tgt, "Acrobatics")) if self._can_act(tgt) else 0
                if mine >= theirs and not (K.incapacitated(self._conds(tgt)) and False):
                    if key == "grapple":
                        self._effect_on(tgt, f"Grappled by {c['name']}", ["Grappled"], None, None, None, None, c["name"],
                                        {"grappler": c["id"]}, None, c["id"])
                        line = f"{c['name']} grapples {tgt['name']} ({mine} vs {theirs})"
                    elif option == "push":
                        self._push(tgt, c, 5)
                        line = f"{c['name']} shoves {tgt['name']} away ({mine} vs {theirs})"
                    else:
                        self._cond(tgt, "Prone", True)
                        line = f"{c['name']} knocks {tgt['name']} prone ({mine} vs {theirs})"
                else:
                    line = f"{c['name']} fails to {key} {tgt['name']} ({mine} vs {theirs})"
            elif key == "escape":
                line = self._escape(c)
            elif key == "douse":
                fires = [e for e, _v in self._fxs(c, "douse")]
                if not fires:
                    raise ServiceError(f"{c['name']} isn't burning.")
                dc = int(fires[0]["mods"]["douse"])
                total = self._check(c, "Dexterity", dc=dc)
                if total >= dc:
                    for e in fires:
                        self._effect_off(c, e, "put out")
                    line = f"{c['name']} puts out the flames (Dexterity {total} vs DC {dc})"
                else:
                    line = f"{c['name']} fails to put out the flames (Dexterity {total} vs DC {dc})"
            elif key == "stabilize":
                total = self._check(c, "Medicine", dc=10)
                if total >= 10:
                    char = self._sheet(tgt)
                    char.d["death_saves"] = {"success": 3, "failure": 0}
                    char.save()
                    line = f"{c['name']} stabilizes {tgt['name']} (Medicine {total})"
                else:
                    line = f"{c['name']} fails to stabilize {tgt['name']} (Medicine {total})"
            elif key == "stand_up":
                self._cond(c, "Prone", False)
                for e in list(c.get("effects") or []):
                    if "Prone" in e["conditions"]:
                        e["conditions"].remove("Prone")
                line = f"{c['name']} stands up"
            elif key == "drop_prone":
                self._cond(c, "Prone", True)
                line = f"{c['name']} drops prone"
            self._commit(line)
            return line

    def _size_of(self, c: dict) -> str:
        char = self._sheet(c)
        if char:
            s = char.size if char.size in SIZES else "Medium"
        else:
            m = self._monster(c)
            s = ((m or {}).get("size") or "Medium").split("/")[-1]
            s = s if s in SIZES else "Medium"
        step = sum(int(v) for _e, v in self._fxs(c, "size_step"))    # Enlarge/Reduce: one size up or down
        return SIZES[max(0, min(len(SIZES) - 1, SIZES.index(s) + step))] if step else s

    def _escape(self, c: dict) -> str:
        holds = [e for e in c.get("effects") or [] if ({"Grappled", "Restrained"} & set(e.get("conditions") or []) or (e.get("mods") or {}).get("attached"))
                 and not (e.get("mods") or {}).get("swallowed_by")]       # a darkmantle on its head: a Strength check pulls it off
        if not holds and any((e.get("mods") or {}).get("swallowed_by") for e in c.get("effects") or []):
            raise ServiceError(f"{c['name']} is swallowed: no check gets it out (hurt the swallower from inside).")
        if not holds:
            for cond in ("Grappled", "Restrained"):
                if cond in self._conds(c):
                    self._cond(c, cond, False)
                    return f"{c['name']} breaks free"
            raise ServiceError(f"{c['name']} isn't held.")
        e = holds[0]
        mode = "adv" if self._feat(c, "squat_nimbleness") and "Grappled" in (e.get("conditions") or []) else None
        mine = max(self._check(c, "Athletics", mode), self._check(c, "Acrobatics", mode))
        grappler = self._find_or_none((e.get("mods") or {}).get("grappler"))
        dc = e.get("escape") or e.get("dc") or (e.get("mods") or {}).get("escape_dc") or (self._check(grappler, "Athletics") if grappler else 10)
        if mine >= dc:
            self._effect_off(c, e, "escaped")
            for cond in e["conditions"]:
                self._cond(c, cond, False)
            return f"{c['name']} escapes ({mine} vs {dc})"
        return f"{c['name']} fails to escape ({mine} vs {dc})"
