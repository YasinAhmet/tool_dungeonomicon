"""What magic weapons do in a fight beyond their +N, read from the item's own text (DMG chapter 7 and later books).

On a hit (weapon_hits):
    extra dice always (Frost Brand 1d6 cold), against a kind of creature (Dragon Slayer 3d6 against dragons, Holy Avenger
    2d10 radiant against fiends and undead), with a ranged attack only (Dwarven Thrower), on a roll of 20 (Vicious Weapon,
    Sword of Sharpness, Sword of Life Stealing with its temporary hit points), while switched on (Flame Tongue ablaze).
    After the damage: Giant Slayer's Strength save or prone, Mace of Disruption destroying a fiend or undead at 25 hit
    points or fewer, a Vorpal Sword's beheading, a Nine Lives Stealer's critical, a Dagger of Venom's coat of poison.
Activations (on the action bar as "ipower:<item>|<key>"):
    flame      Flame Tongue: a bonus action lights the blade (or puts it out)
    speed      Scimitar of Speed: one attack with it as a bonus action
    venom      Dagger of Venom: an action coats the blade, once a day (the next hit: DC 15 Con, 2d10 poison and poisoned)
    terror     Mace of Terror: an action and a charge, everyone of the wielder's choice within 30 ft: DC 15 Wis or frightened
    lightning  Javelin of Lightning: a 5-ft line of lightning to the target (DC 13 Dex, 4d6), then its attack with 4d6 more
    cone       a Dragon's Wrath weapon's or the Flail of Tiamat's cone (its DC and dice from the text), once a day
    dance      a dancing sword's bonus-action strike up to 30 ft away; after the fourth it returns
Also: a Sword of Wounding's stacking wounds (a damage-over-time effect, DC 15 Con at the end of its turns), a Holy
Avenger's aura (advantage on saves against spells for its friends nearby), an Oathbow's sworn enemy.
A day's use is kept in the sheet's resources ("item:<name>:<key>", cleared by a long rest).
More weapons' powers: itemextras.py (one of a kind) and weaponlore.py (worded for any weapon: a building charge, souls, a chaos staff...).
"""
import re
from typing import List, Optional

from ...rules.data import rules
from ..common import ServiceError
from .weaponlore import CLAIMED as LORE_CLAIMED

KINDS = ("aberration", "beast", "celestial", "construct", "dragon", "elemental", "fey", "fiend", "giant", "humanoid", "monstrosity",
         "ooze", "plant", "undead")
EXTRA = re.compile(r"extra (\d+d\d+|\d+)(?: (acid|bludgeoning|cold|fire|force|lightning|necrotic|piercing|poison|psychic|radiant|"
                   r"slashing|thunder))? damage", re.I)
ALSO = re.compile(r"that attack also deals (\d+d\d+|\d+) (acid|bludgeoning|cold|fire|force|lightning|necrotic|piercing|poison|psychic|radiant|"
                  r"slashing|thunder) damage", re.I)      # Ebonbane (2024 wording): "When you hit a Celestial or a Humanoid with it, that attack also deals 3d6 Necrotic damage"


def _sentences(text: str) -> List[str]:
    text = re.sub(r"\{@note[^}]*\}|Note: According to the SRD[^\n]*", "", text or "").replace("{=dmgType} ", "")
    return [s for s in re.split(r"(?<=[.!])\s+|\n+", text) if s.strip()]


def weapon_hits(item: Optional[dict]) -> List[dict]:
    """The weapon's extra damage on a hit: [{'dice', 'type' (None: the weapon's), 'vs' (creature types or None), 'ranged',
    'crit' (a roll of 20), 'toggle' (needs switching on), 'not_vs', 'temp', 'big_vs' {type: dice}, 'save'}]."""
    if not item or not (item.get("weapon") or item.get("type") in ("M", "R")):
        return []
    out = []
    for s in _sentences(item.get("text")):
        low = s.lower()
        if not re.search(r"\bhits?\b|roll a 20|\bon a hit\b", low) or ("extra" not in low and "also deals" not in low):
            continue
        if re.search(r"each creature of your choice within 5 feet of the target|you can expend|charge", low) or LORE_CLAIMED.search(low):
            continue                                       # a Dragon's Wrath splash, Baba Yaga's charges, a target at half its hit points (weaponlore.py): not every hit
        m = EXTRA.search(s) or ALSO.search(s)
        if not m:
            continue
        p = {"dice": m.group(1), "type": (m.group(2) or "").lower() or None, "vs": None, "ranged": "ranged attack" in low,
             "crit": "roll a 20" in low, "toggle": "ablaze" in low, "not_vs": [], "temp": 0, "big_vs": {}, "save": None}
        if "of the type dealt by the dragon" in low or "your choice of one of the following damage types" in low or "same type as the breath" in low:
            p["type"] = "fire"                              # the hoard's breath, Tiamat's heads: fire unless the DM says otherwise
        head = low[:m.start()]
        kinds = [k for k in KINDS if re.search(r"\b(?:an? |hit an? |hit a )?%ss?\b" % k, head)]
        if kinds and re.search(r"when you hit (?:an? |a )|against (?:an? )?|if (?:the target|it) is an? ", head):
            p["vs"] = kinds
        if re.search(r"if it isn't an? (\w+) or an? (\w+)", low):
            p["not_vs"] = list(re.search(r"if it isn't an? (\w+) or an? (\w+)", low).groups())
        t = re.search(r"gain (\d+) temporary hit points", item.get("text") or "")
        if p["crit"] and t and "life stealing" in item["name"].lower():
            p["temp"] = int(t.group(1))
        big = re.search(r"or, if the target is an? (\w+), (\d+d\d+)", low) or re.search(r"or an extra (\d+) \w+ damage if it's an? (\w+)", low)
        if big:
            a, b = big.groups()
            p["big_vs"] = {a: b} if a in KINDS else {b: a}
        p["sworn"] = "sworn enemy" in low                     # the Oathbow: only against the creature it swore at
        sv = re.search(r"must succeed on a dc (\d+) (strength|dexterity|constitution|wisdom) saving throw or (?:fall|be knocked) prone", low)
        if sv:
            p["save"] = {"ab": sv.group(2)[:3], "dc": int(sv.group(1)), "prone": True}
        out.append(p)
    return out


def activations(item: Optional[dict]) -> List[dict]:
    """The weapon's powers used from the bar: [{'key', 'name', 'cost', 'target', 'tip'}]."""
    if not item:
        return []
    text = item.get("text") or ""
    out = []
    if re.search(r"bonus action to speak this magic sword's command word, causing flames", text):
        out.append({"key": "flame", "name": "Ignite / douse", "cost": "bonus", "target": {"type": "self"},
                    "tip": "Flames burst from the blade: +2d6 fire on every hit until you douse it."})
    if re.search(r"make one (?:additional )?attack with it as a bonus action", text):     # (a Canian Fork: "one additional attack")
        out.append({"key": "speed", "name": "Bonus attack", "cost": "bonus", "target": {"type": "creature", "count": 1, "enemies": True},
                    "tip": "One attack with this weapon as a bonus action."})
    if re.search(r"use an action to cause thick, black poison to coat the blade", text):
        out.append({"key": "venom", "name": "Coat with poison", "cost": "action", "target": {"type": "self"}, "daily": True,
                    "tip": "The next hit within a minute: DC 15 Con save or 2d10 poison and poisoned for 1 minute. Once a day."})
    m = re.search(r"Bonus Action to magically coat the blade of this \w+ with poison.*?DC (\d+) Constitution saving throw or take (\d+d\d+) Poison damage",
                  text, re.S)
    if m:                                                      # a Poison Soaked Kukri: the same, a bonus action, DC 13 and 2d8
        out.append({"key": "venom", "name": "Coat with poison", "cost": "bonus", "target": {"type": "self"}, "daily": True,
                    "venom": {"dc": int(m.group(1)), "dice": m.group(2)},
                    "tip": f"The next hit within a minute: DC {m.group(1)} Con save or {m.group(2)} poison and poisoned for 1 minute. Once a day."})
    if re.search(r"When you hurl it and speak its command word, it transforms into a bolt of lightning", text):
        out.append({"key": "lightning", "name": "Lightning bolt", "cost": "attack", "daily": True, "range": 120,
                    "target": {"type": "creature", "count": 1, "enemies": True},
                    "tip": "Hurl it as a bolt: each creature in the 5-ft line to the target, DC 13 Dex save or 4d6 lightning (half on a "
                           "success); then a ranged attack, +4d6 lightning on a hit. Once a day."})
    m = re.search(r"(?:unleash|breathe)[^.]*? in an? (\d+)-foot cone|unleash an? (\d+)-foot cone", text)
    sv = re.search(r"DC (\d+) (Strength|Dexterity|Constitution|Wisdom) saving throw[,.]? (?:taking|On a failed save, it takes) (\d+d\d+) "
                   r"(?:(acid|cold|fire|lightning|poison|thunder|necrotic|radiant|force) )?damage", text)
    if m and sv:
        size = int(m.group(1) or m.group(2))
        out.append({"key": "cone", "name": f"{size}-ft cone", "cost": "action", "daily": True,
                    "cone": {"size": size, "dc": int(sv.group(1)), "ab": sv.group(2)[:3].lower(), "dice": sv.group(3), "type": sv.group(4) or "fire"},
                    "target": {"type": "self_area", "aim": True, "area": {"shape": "cone", "size": size, "origin": "caster"}},
                    "tip": f"Each creature in a {size}-ft cone: DC {sv.group(1)} {sv.group(2)} save, {sv.group(3)} damage (half on a success). Once a day."})
    if re.search(r"bonus action to toss this magic sword into the air", text):
        out.append({"key": "dance", "name": "Dancing strike", "cost": "bonus", "range": 30,
                    "target": {"type": "creature", "count": 1, "enemies": True},
                    "tip": "The sword flies up to 30 ft and attacks a creature with your attack roll; after its fourth attack it returns."})
    if re.search(r"transfer some or all of the sword's bonus to your Armor Class", text) and item.get("bonus_weapon"):
        n = int(item["bonus_weapon"])
        out.append({"key": "defend", "name": "Shift bonus to AC", "cost": "free", "target": {"type": "self"},
                    "options": [{"value": str(k), "label": f"+{k} AC, +{n - k} attack and damage"} for k in range(1, n + 1)],
                    "tip": f"Before your first attack this turn: move some of the sword's +{n} to your AC until the start of your next turn."})
    if re.search(r"expend 1 charge to release a wave of terror", text):
        out.append({"key": "terror", "name": "Wave of terror", "cost": "action", "charge": 1,
                    "target": {"type": "self_area", "aim": False, "area": {"shape": "emanation", "size": 30, "origin": "caster", "choice": True}},
                    "tip": "Each creature of your choice within 30 ft: DC 15 Wisdom save or frightened of you for 1 minute."})
    from .itemextras import extra_activations
    return out + extra_activations(item)                   # Fool's Feint, Starshot constellations... (itemextras.py)


class ItemPowersMixin:
    def _weapon_item(self, att: dict, a: dict) -> Optional[dict]:
        char = self._sheet(att)
        if not char or not a.get("item") or att.get("form"):
            return None
        entry = char.find_item(a["item"])
        return rules.item(entry["name"]) if entry else None

    def _kind(self, c: dict) -> str:
        if self._sheet(c) and not c.get("form"):
            return "humanoid"
        return str((self._monster(c) or {}).get("type") or "").lower()

    def _item_hit_parts(self, att: dict, tgt: dict, R: dict) -> list:
        """Extra damage parts of the magic weapon in use, and what it does after the damage (as riders)."""
        a = R["atk"]
        item = self._weapon_item(att, a) if a.get("weapon") else None
        if not item:
            return []
        out = []
        cur = R["cur"]
        nat20 = cur.get("kept") == 20
        kind = self._kind(tgt)
        wtype = (a.get("parts") or [["", ""]])[0][1]
        on = (att.get("item_state") or {}).get(a["item"]) or {}
        for p in weapon_hits(item):
            if p["crit"] and not nat20 or p["ranged"] and a.get("melee") or p["toggle"] and not on.get("flame"):
                continue
            if p["vs"] and kind not in p["vs"] or kind in p["not_vs"]:
                continue
            if p.get("sworn"):
                foe = self._find_or_none(att.get("sworn_enemy"))
                if foe is None or not self._alive(foe):          # the first creature it shoots at becomes the sworn enemy
                    att["sworn_enemy"] = tgt["id"]
                    self._line(R, f"{tgt['name']} is {att['name']}'s sworn enemy", "sworn enemy")
                elif foe is not tgt:
                    continue
            dice = p["big_vs"].get(kind, p["dice"])
            out.append([dice, p["type"] or wtype])
            self._line(R, f"{item['name']}: +{dice} {p['type'] or wtype}", item["name"])
            if p["temp"]:
                self._give_temp(att, p["temp"])
            if p["save"]:
                R.setdefault("smite_riders", []).append({"rider": dict(p["save"]), "name": item["name"], "target": tgt["id"], "dc": p["save"]["dc"]})
        low = item["name"].lower()
        ig = re.search(r"ignores resistance to (\w+) damage", item.get("text") or "")
        if ig:                                              # a Vorpal Sword's slashing
            R["ignore_resist"] = [ig.group(1).lower()]
        if " of wounding" in low and self._alive(tgt) and self._once_per_turn(att, "wounding"):
            name = f"Wounded ({item['name']})"                # 1d4 necrotic a wound at the start of its turns, DC 15 Con ends them all
            have = next((e for e in tgt.get("effects") or [] if e["name"] == name), None)
            if have:
                n = int(str(have["mods"]["dot"]["dice"]).split("d")[0]) + 1
                have["mods"]["dot"]["dice"] = f"{n}d4"
            else:
                self._effect_on(tgt, name, [], "con", 15, "end", None, att["name"], {"dot": {"when": "start", "dice": "1d4", "type": "necrotic"}},
                                None, att["id"])
            self._line(R, f"{tgt['name']} is wounded", "wounded")
        if on.get("venom"):                                 # the poison: a save after the hit, 2d10 and poisoned on a failure
            v = on.pop("venom")                             # (a Poison Soaked Kukri: DC 13, 2d8)
            dc, dice = (v["dc"], v["dice"]) if isinstance(v, dict) else (15, "2d10")
            R.setdefault("follow", []).append(self._strike(att, item["name"] if isinstance(v, dict) else "Dagger of Venom", [tgt["id"]], mode="save",
                                                           sv={"ab": "con", "dc": dc, "half": False, "conds": ["Poisoned"], "rounds": 10},
                                                           parts=[[dice, "poison"]]))
        out += self._extra_hit(att, tgt, R, item)           # Wave, Medusa, Baleful Talon, Ruinous Flail... (itemextras.py)
        sp = re.search(r"roll a 20 on your attack roll[^.]*?each creature of your choice within 5 feet of the target takes (\d+) damage",
                       (item.get("text") or "").replace("\n", " "), re.I)
        if sp and nat20:                                    # a Dragon's Wrath weapon: the hoard's breath splashes the target's neighbours
            for o in self.b["combatants"]:
                if o is not tgt and o is not att and o.get("pos") and self._alive(o) and self._hostile(o, att) and self._dist(o, tgt) <= 5:
                    self._line(R, self._deal(o, [[sp.group(1), "fire"]], by=att, label=item["name"]), item["name"])
        tp = re.search(r"roll a 20 on the attack roll, you gain (\d+) temporary hit points", (item.get("text") or "").replace("\n", " "))
        if tp and nat20:                                    # Reaper's Scream (its necrotic retaliation while they last isn't played)
            self._give_temp(att, int(tp.group(1)))
            self._line(R, f"{item['name']}: {att['name']} gains {tp.group(1)} temporary hit points", item["name"])
        R.setdefault("item_after", []).append({"item": item["name"], "target": tgt["id"], "nat20": nat20, "kind": kind,
                                               "crit": bool(cur.get("crit")), "low": low})
        return out

    def _item_after_hit(self, R: dict, att: dict, tgt: dict):
        """After a magic weapon's damage: destroying, beheading, slaying."""
        self._extra_after_hit(R, att, tgt)                  # Agonizing Paralysis, a Polymorph Blade (itemextras.py)
        for x in R.get("item_after") or []:
            if x["low"].startswith("crystal ") and x["target"] == tgt["id"]:
                self._crystal_heal(R, att, x)
        for x in R.pop("item_after", None) or []:
            if x["target"] != tgt["id"] or not self._alive(tgt) or tgt["kind"] == "pc":
                continue                                    # a hero's head or life: the DM's call, not the battle's
            low, kind = x["low"], x["kind"]
            if "of disruption" in low and kind in ("fiend", "undead") and self._hp_of(tgt) <= 25:
                res = self._saving_throw(tgt, "wis", 15, label=x["item"])
                if not res["ok"]:
                    self._set_hp(tgt, 0)
                    self._line(R, f"{tgt['name']} is destroyed by the {x['item']} (WIS {res['total']} vs DC 15)", "destroyed")
                    self._zero_hp(tgt, att)
                else:
                    self._effect_on(tgt, "Frightened (Mace of Disruption)", ["Frightened"], None, None, None, None, att["name"], None, None,
                                    att["id"], until={"end": att["id"], "skip": 1})
                    self._line(R, f"{tgt['name']} is frightened of {att['name']}", "frightened")
            if "of smiting" in low and x["nat20"] and kind == "construct" and self._hp_of(tgt) <= 25:
                self._set_hp(tgt, 0)
                self._line(R, f"{tgt['name']} is shattered by the {x['item']}", "destroyed")
                self._zero_hp(tgt, att)
            if low.startswith("vorpal") and x["nat20"]:
                m = self._monster(tgt) or {}
                immune = "slashing" in self._defenses(tgt)["immune"] or m.get("legendary") or kind in ("ooze", "plant", "elemental")
                if immune:
                    self._line(R, self._deal(tgt, [["6d8", "slashing"]], by=att, label="Vorpal"), "Vorpal")
                else:
                    self._set_hp(tgt, 0)
                    self._line(R, f"{att['name']}'s vorpal blade cuts off {tgt['name']}'s head", "beheaded")
                    self._zero_hp(tgt, att)
            if low.startswith("nine lives stealer") and x["crit"] and kind not in ("construct", "undead") and 0 < self._hp_of(tgt) < 100:
                entry = (self._sheet(att) and self._sheet(att).find_item(x["item"])) or {}
                left = self._charges_left(entry) if entry else 0
                if left > 0:
                    res = self._saving_throw(tgt, "con", 15, label=x["item"])
                    if not res["ok"]:
                        entry["charges_left"] = left - 1
                        self._sheet(att).save()
                        self._set_hp(tgt, 0)
                        self._line(R, f"{x['item']} tears {tgt['name']}'s life away ({left - 1} charges left)", "slain")
                        self._zero_hp(tgt, att)

    def _crystal_heal(self, R: dict, att: dict, x: dict):
        """A Crystal Rapier or Scimitar's hit: while the wielder is hurt, a charge heals it by the extra radiant damage just dealt."""
        char = self._sheet(att)
        entry = char.find_item(x["item"]) if char else None
        radiant = sum(int(n) for n, t in (R.get("cur") or {}).get("dmg") or [] if str(t).lower() == "radiant")
        if not entry or radiant <= 0 or self._charges_left(entry) < 1 or self._hp_of(att) >= self._max_hp(att) or not self._alive(att):
            return
        entry["charges_left"] = self._charges_left(entry) - 1
        char.save()
        if self._heal(att, radiant):
            self._line(R, f"{x['item']}: a charge heals {att['name']} for {radiant} ({entry['charges_left']} charges left)", f"+{radiant} HP")

    def _item_auras(self, c: dict):
        """A Holy Avenger held: it and its friends within 10 ft (30 ft for a 17th-level paladin) have advantage on saves
        against spells. Kept as an aura effect on the wielder, renewed at the start of its turns."""
        char = self._sheet(c)
        if not char or c.get("form"):
            return
        holy = any(a["name"].lower().startswith("holy avenger") for a in char.attacks())
        have = next((e for e in c.get("effects") or [] if e["name"] == "Holy Avenger aura"), None)
        if holy and not have:
            ft = 30 if char.class_level("Paladin") >= 17 else 10
            self._effect_on(c, "Holy Avenger aura", [], None, None, None, None, c["name"], {"save_adv": ["spells"], "aura_ft": ft}, None, c["id"])
            self.b["aura_fx"] = True
        elif have and not holy:
            self._effect_off(c, have, "sheathed")

    # ------------------------------------------------------------------ the bar
    def item_power_options(self, c: dict) -> List[dict]:
        """The activations of the magic weapons this hero has in hand: [{'id', 'name', 'cost', 'target', 'tip', 'why'}]."""
        char = self._sheet(c)
        if not char or c.get("form"):
            return []
        out = []
        for w in char.attacks():
            item = rules.item(w["name"])
            for p in activations(item):
                why = None
                if p.get("daily") and char.d["resources"].get(f"item:{item['name']}:{p['key']}"):
                    why = "Used until the next dawn"
                if p.get("charge"):
                    entry = char.find_item(w["name"])
                    if entry and self._charges_left(entry) < p["charge"]:
                        why = "No charges left"
                if p.get("lore"):                               # a rest's use, a soul to spend (weaponlore.py)
                    why = why or self._lore_why(c, char, char.find_item(w["name"]), item, p)
                name = f"{p['name']} ({w['name']})"
                if p["key"] == "flame":
                    lit = ((c.get("item_state") or {}).get(w["name"]) or {}).get("flame")
                    name = f"{'Douse' if lit else 'Ignite'} {w['name']}"
                if p["key"] == "defend" and (c.get("turn") or {}).get("attacked") and self._economy_on():
                    why = "Only before your first attack this turn"
                out.append({"id": f"ipower:{w['name']}|{p['key']}", "name": name, "cost": p["cost"], "target": p["target"], "tip": p["tip"],
                            "why": why, "range": p.get("range", 5 if p["key"] == "speed" else None),
                            "extra": {"options": p["options"]} if p.get("options") else None})
        return out

    def _item_strike(self, c: dict, char, entry: dict, data: dict, p: dict, target_id, adv) -> str:
        """Javelin of Lightning's bolt (the line first, then the javelin's attack with 4d6 lightning more) or a dancing
        sword's strike (up to 30 ft away, four of them before it comes back)."""
        from . import features as F
        from . import geometry as G
        tgt = self._target(target_id)
        w = next(a for a in char.attacks() if a["name"] == entry["name"])
        atk = dict(self._weapon_atk(c, w), adv=adv)
        state = c.setdefault("item_state", {}).setdefault(entry["name"], {})
        if c.get("pos") and tgt.get("pos") and self._dist(c, tgt) > p["range"]:
            raise ServiceError(f"{tgt['name']} is too far away ({self._dist(c, tgt)} ft, up to {p['range']}).")
        if p["key"] == "dance":
            atk.update(melee=True, reach=p["range"], normal=None, long=None)
            self._pay(c, "bonus", f"{entry['name']} dances")
            state["dances"] = state.get("dances", 0) + 1
            label = f"{entry['name']} (dancing)"
            if state["dances"] >= 4:
                state["dances"] = 0
                self._say(f"{entry['name']} has struck four times and flies back to {c['name']}'s hand")
            out = self._run_r(self._strike(c, label, [tgt["id"]], mode="attack", atk=atk, magical=True))
            self._commit()
            return out
        atk.update(melee=False, normal=p["range"], long=p["range"], parts=list(atk["parts"]) + [["4d6", "lightning"]])
        self._pay_attack(c, F.extra_attacks(char), entry["name"])
        char.d["resources"][f"item:{data['name']}:lightning"] = 1
        char.save()
        follow = []
        if c.get("pos") and tgt.get("pos"):
            tiles = G.area_tiles("line", self._dist(c, tgt), origin=G.centre(c["pos"], c.get("span") or 1),
                                 toward=G.centre(tgt["pos"], tgt.get("span") or 1), width=5, caster_box=G.box(c["pos"], c.get("span") or 1),
                                 **self._bounds_kw())
            ids = [o["id"] for o in G.creatures_in(tiles, self.b["combatants"]) if o is not c and o is not tgt and not self._is_out(o)]
            self._area_vfx(c, tiles, [["4d6", "lightning"]], "line", list(G.centre(tgt["pos"], tgt.get("span") or 1)))
            if ids:
                follow.append(self._strike(c, "Javelin of Lightning (bolt)", ids, mode="save", sv={"ab": "dex", "dc": 13, "half": True},
                                           parts=[["4d6", "lightning"]], magical=True))
        self._say(f"{c['name']} hurls {entry['name']}: it becomes a bolt of lightning")
        out = self._run_r(self._strike(c, f"{entry['name']} (lightning)", [tgt["id"]], mode="attack", atk=atk, magical=True, follow=follow))
        self._commit()
        return out

    def _item_cone(self, c: dict, char, entry: dict, data: dict, p: dict, point) -> str:
        """A Dragon's Wrath weapon's or the Flail of Tiamat's cone of breath, once a day."""
        from . import geometry as G
        if not c.get("pos"):
            raise ServiceError("Put the hero on the map to aim it.")
        cone = p["cone"]
        aim = point or self.b.get("aim")
        if aim is None:
            raise ServiceError("Pick where to aim the cone.")
        tiles = G.area_for(p["target"]["area"], c["pos"], c.get("span") or 1, tuple(aim), *self._bounds())
        ids = [o["id"] for o in G.creatures_in(tiles, self.b["combatants"]) if o is not c and not self._is_out(o)]
        self._pay(c, "action", f"{entry['name']}: {p['name']}")
        char.d["resources"][f"item:{data['name']}:cone"] = 1
        char.save()
        self._area_vfx(c, tiles, [[cone["dice"], cone["type"]]], "cone", aim)
        out = self._run_r(self._strike(c, entry["name"], ids, mode="save", sv={"ab": cone["ab"], "dc": cone["dc"], "half": True},
                                       parts=[[cone["dice"], cone["type"]]], magical=True))
        self._commit()
        return out

    def use_item_power(self, cid: int, item: str, key: str, target_id: Optional[int] = None, adv: Optional[str] = None, point=None,
                       option: Optional[str] = None) -> str:
        with self.lock:
            self._busy()
            c = self._find(cid)
            char = self._sheet(c)
            entry = char.find_item(item) if char else None
            data = rules.item(entry["name"]) if entry else None
            p = next((x for x in activations(data) if x["key"] == key), None)
            if not p:
                raise ServiceError(f"{item} can't do that.")
            state = c.setdefault("item_state", {}).setdefault(entry["name"], {})
            if key == "speed":
                tgt = self._target(target_id)
                w = next(a for a in char.attacks() if a["name"] == entry["name"])
                atk = self._check_reach(c, tgt, dict(self._weapon_atk(c, w), adv=adv))
                self._pay(c, "bonus", f"{entry['name']} (bonus attack)")
                out = self._run_r(self._strike(c, f"{entry['name']} (bonus attack)", [tgt["id"]], mode="attack", atk=atk, magical=True))
                self._commit()
                return out
            if p.get("daily") and char.d["resources"].get(f"item:{data['name']}:{key}"):
                raise ServiceError(f"{entry['name']} can't do that again until the next dawn.")
            if p.get("charge"):
                left = self._charges_left(entry)
                if left < p["charge"]:
                    raise ServiceError(f"{entry['name']} has no charges left.")
            if key in ("lightning", "dance"):
                return self._item_strike(c, char, entry, data, p, target_id, adv)
            if key == "cone":
                return self._item_cone(c, char, entry, data, p, point)
            got = self._extra_use(c, char, entry, data, p, key, target_id, point, option)     # itemextras.py's powers
            if got is not None:
                return got
            if key == "defend":                                 # a Defender: some of its bonus to AC until the start of the next turn
                if (c.get("turn") or {}).get("attacked") and self._economy_on():
                    raise ServiceError("The bonus moves only before your first attack this turn.")
                n = max(1, min(int(data.get("bonus_weapon") or 0), int(option) if str(option or "").isdigit() else 1))
                self._effect_on(c, f"{entry['name']} (defending)", [], None, None, None, None, c["name"],
                                {"ac": n, "defender": {entry["name"]: n}}, None, c["id"], until={"start": c["id"]})
                line = f"{c['name']} moves +{n} of {entry['name']}'s bonus to AC"
                self._commit(line)
                return line
            self._pay(c, p["cost"], f"{entry['name']}: {p['name']}")
            if key == "flame":
                state["flame"] = not state.get("flame")
                line = f"{c['name']}'s {entry['name']} " + ("bursts into flame" if state["flame"] else "goes out")
            elif key == "venom":
                state["venom"] = p.get("venom") or True
                char.d["resources"][f"item:{data['name']}:{key}"] = 1
                char.save()
                line = f"{c['name']} coats {entry['name']} with black poison"
            elif key == "terror":
                entry["charges_left"] = self._charges_left(entry) - p["charge"]
                char.save()
                ids = [o["id"] for o in self.b["combatants"] if o is not c and o.get("pos") and c.get("pos") and self._hostile(o, c)
                       and not self._is_out(o) and self._dist(o, c) <= 30]
                self._say(f"{c['name']} raises {entry['name']}: a wave of terror ({entry['charges_left']} charges left)")
                S = self._strike(c, entry["name"], ids, mode="save", sv={"ab": "wis", "dc": 15, "half": False, "conds": ["Frightened"],
                                                                         "repeat": "end", "rounds": 10}, parts=[], magical=True)
                out = self._run_r(S) if ids else f"{c['name']}'s wave of terror reaches nobody"
                self._commit()
                return out
            else:
                raise ServiceError(f"{item} can't do that.")
            self._commit(line)
            return line
