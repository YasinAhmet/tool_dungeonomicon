"""More magic weapons in a fight, beyond itempowers.py's table: the ones whose powers are one of a kind.

On a hit (_extra_hit, called from itempowers._item_hit_parts):
    Wave's critical (necrotic equal to half the target's hit point maximum), a Storm Boomerang's thunder and stun,
    a Baleful Talon's 19-20 (DC 15 Con, 6d6 necrotic), a Sword of the Medusa's 20 (restrained, then stone), a Polymorph
    Blade's 20 (DC 15 Wis or a random beast), a Sling of Giant Felling against giants (DC 18 Con or prone), a Ruinous
    Flail once a day (DC 15 Con: poisoned, 2d4 necrotic a turn), a Staff of the Rooted Hills' first hit of the turn
    (DC 12 Str or restrained), a Double-Bladed Scimitar of Certain Death (no healing until the wielder's next turn), a
    Bloodshed blade's Constitution modifier, a Bow of Melodies' reverberation (+ Charisma modifier thunder).
After the damage (_extra_after_hit, before itempowers' own): a Weapon of Agonizing Paralysis leaves the creature it
    drops at 1 hit point and paralyzed instead; a Blood Spear's kill gives 2d6 temporary hit points.
Hurled for a charge (_weapon_flags, _hurl_spend): a Hammer of Thunderbolts or Azuredge thrown at its text's range, a charge hit or
    miss; the hammer's hit is a thunderclap (DC 17 Con or stunned, the target and everyone within 30 ft of it).
On the bar (extra_activations, merged into itempowers.activations): Fool's Feint, an Acheron Blade's Dark Blessing,
    a Hammer of Runic Focus's circle, a Starshot Crossbow's constellations (Flames, Rogue), a Staff of Fate's d4.
Cursed weapons that hinder other weapons (Vengeance, Retribution, Berserker, Demonbone) are wondrous._wonder_modes.
Powers worded for any weapon (extra dice against a target at half its hit points, a building charge, trapped souls, a miss turned into a
hit, a chaos staff's table...) are weaponlore.py's, this mixin's base.
"""
import re
from typing import List, Optional

from ...rules.dice import roll_dice
from ..common import ServiceError
from .weaponlore import WeaponLoreMixin, lore_activations, lore_hit_choices

POLYMORPH_TABLE = ["Tyrannosaurus Rex|MM", "Giant Ape|MM", "Elephant|MM", "Giant Scorpion|MM", "Rhinoceros|MM", "Polar Bear|MM", "Giant Toad|MM",
                   "Giant Eagle|MM", "Black Bear|MM", "Crocodile|MM", "Wolf|MM", "Riding Horse|MM", "Ox|VGM", "Giant Frog|MM",
                   "Poisonous Snake|MM", "Hawk|MM", "Octopus|MM", "Cat|MM", "Rat|MM", "Rat|MM"]


HURL_RE = re.compile(r"expend (\d+) charges? and make a ranged (?:weapon )?attack with the \w+, hurling it as if it had the thrown property with a normal "
                     r"range of (\d+) feet and a long range of (\d+) feet", re.I)
CLAP_RE = re.compile(r"every creature within (\d+) feet of it must succeed on a DC (\d+) (Strength|Dexterity|Constitution|Intelligence|Wisdom|Charisma) "
                     r"saving throw or be (stunned|deafened|frightened|blinded|incapacitated|prone) until the end of your next turn", re.I)


def hit_choices(item: Optional[dict]) -> List[dict]:
    """What the wielder may add after a hit with this weapon (asked like a smite): [{'key', 'label', 'daily', 'sv', 'parts'}].
    A Ruinous Flail's sickness (once a day), the Lash of Shadows' poisons."""
    text = (item or {}).get("text") or ""
    out = []
    if "you can force the creature to make a DC 15 Constitution saving throw. On a failed save, the creature has the poisoned condition" in text:
        out.append({"key": "ruin", "label": "Ruin: DC 15 Con or poisoned, 2d4 necrotic a turn (once a day)", "daily": True, "parts": [],
                    "sv": {"ab": "con", "dc": 15, "half": False, "conds": ["Poisoned"], "repeat": "end", "rounds": 10,
                           "mods": {"dot": {"dice": "2d4", "type": "necrotic", "when": "start"}}}})
    if re.search(r"you can expend 1 charge to regain a number of hit points equal to the damage dealt by the weapon", text):
        out.append({"key": "vampiric", "label": "Vampiric Strike: 1 charge, heal the damage dealt", "daily": False, "charge": 1, "parts": [],
                    "sv": None})                         # a Gulthias Staff (then a DC 12 Wis save against madness)
    m = re.search(r"Stunning Hit\. When you hit with a melee attack using the staff, you can expend (\d) charges, and the target must succeed on a "
                  r"DC (\d+) Constitution saving throw or have the Stunned condition until the end of your next turn", text)
    if m:                                                    # a Diamond Staff (AU)
        out.append({"key": "stun_hit", "label": f"Stunning Hit: {m.group(1)} charges, DC {m.group(2)} Con or stunned", "daily": False,
                    "charge": int(m.group(1)), "parts": [],
                    "sv": {"ab": "con", "dc": int(m.group(2)), "half": False, "conds": ["Stunned"], "until": "caster_end_next"}})
    m = re.search(r"Trip\. When you make a melee attack with this weapon, you can expend 1 charge to give yourself Advantage on the attack roll\. "
                  r"If the attack hits, the target makes a DC (\d+) Strength saving throw\. On a failed save, the target has the Prone condition", text)
    if m:                                                    # a Martialist's Quarterstaff (AU): the advantage can't be taken after the roll, the trip can
        out.append({"key": "trip", "label": f"Trip: 1 charge, DC {m.group(1)} Str or prone", "daily": False, "charge": 1, "parts": [],
                    "sv": {"ab": "str", "dc": int(m.group(1)), "half": False, "prone": True}})
    if "Named Target. When you hit a creature with an attack roll using this weapon" in text:
        out.append({"key": "named", "label": "Named Target: turn the hit into a critical hit (once a day)", "daily": True, "parts": [], "sv": None})
    m = re.search(r"attempt to poison any creature that is hit by the whip\. The creature must succeed on a DC (\d+)", text)
    if m:
        dc = int(m.group(1))
        out.append({"key": "venom", "label": f"Serpent Venom: DC {dc} Con, 3d6 poison", "daily": False, "parts": [["3d6", "poison"]],
                    "sv": {"ab": "con", "dc": dc, "half": True}})
        out.append({"key": "eyes", "label": f"Dead Eyes: DC {dc} Con or poisoned and blinded for an hour (once a day)", "daily": True, "parts": [],
                    "sv": {"ab": "con", "dc": dc, "half": False, "conds": ["Poisoned", "Blinded"], "rounds": 600}})
        if "Ghoul's Blood" in text:
            out.append({"key": "ghoul", "label": f"Ghoul's Blood: DC {dc} Con or poisoned and paralyzed (once a day)", "daily": True, "parts": [],
                        "sv": {"ab": "con", "dc": dc, "half": False, "conds": ["Poisoned", "Paralyzed"], "repeat": "end", "rounds": 10}})
    return out + lore_hit_choices(item)                     # a charge for a save or a second shot (weaponlore.py)


def extra_activations(item: Optional[dict]) -> List[dict]:
    """The weapon's own bar entries that itempowers.activations doesn't read: [{'key', 'name', 'cost', 'target', 'tip', ...}]."""
    text = (item or {}).get("text") or ""
    out = []
    if re.search(r"Fool's Feint", text):
        out.append({"key": "feint", "name": "Fool's Feint", "cost": "bonus", "daily": True, "range": 5,
                    "target": {"type": "creature", "count": 1, "enemies": True},
                    "tip": "A creature within 5 ft: advantage on your attacks against it until the start of your next turn. Once a day."})
    if re.search(r"Dark Blessing\. While holding the sword, you can use an action to give yourself 1d4 \+ 4 temporary hit points", text):
        out.append({"key": "blessing", "name": "Dark Blessing", "cost": "action", "daily": True, "target": {"type": "self"},
                    "tip": "1d4 + 4 temporary hit points. Once until the next dusk."})
    if re.search(r"slam this hammer on the ground, creating a 15-foot-radius circle of glowing runes", text):
        out.append({"key": "runes", "name": "Rune circle", "cost": "bonus", "charge": 1, "target": {"type": "self"},
                    "tip": "For 1 minute (while you stay in the circle): +3 to attack and damage rolls with this hammer. 1 charge."})
    if re.search(r"Altered Outcome\. The staff has \d+ charges\. As a bonus action, you can expend 1 of the staff's charges", text):
        out.append({"key": "fate", "name": "Altered Outcome", "cost": "bonus", "charge": 1, "range": 60,
                    "target": {"type": "creature", "count": 1, "allies": True},
                    "tip": "You or a creature you can see: +1d4 on its next attack roll, check or save before the start of your next turn. 1 charge."})
    if re.search(r"Choose a magical bonus of \+1 to \+3\. This sword gains that bonus", text):
        out.append({"key": "gamble", "name": "Choose the bonus", "cost": "free", "daily": True, "target": {"type": "self"},
                    "options": [{"value": str(k), "label": f"+{k} (death saves -{k})"} for k in (1, 2, 3)],
                    "tip": "A +1 to +3 bonus to attack and damage rolls until the next dawn; the same penalty to your death saves."})
    if re.search(r"slice through an unoccupied space within 5 feet of yourself, creating a rift", text):
        out.append({"key": "rift", "name": "Open a planar rift", "cost": "action", "daily": True, "target": {"type": "self"},
                    "tip": "A 10-ft rift to another plane beside you for 1 minute: whatever enters it is gone (to that plane). Once a day."})
    if re.search(r"enable one creature within 60 feet of you to use its reaction to make one weapon attack", text):
        out.append({"key": "rally", "name": "Rally an ally's attack", "cost": "free", "range": 60,
                    "target": {"type": "creature", "count": 1, "allies": True},
                    "tip": "After you attack with the sword: a creature within 60 ft uses its reaction to make one weapon attack. Once a turn."})
    if re.search(r'whisper the word "seek" and hurl this dart', text):
        out.append({"key": "seek", "name": "Seek", "cost": "action", "range": 120, "target": {"type": "creature", "count": 1, "enemies": True},
                    "tip": "The dart finds a creature within 120 ft (no sight needed): DC 16 Dex or 1d4 piercing and 3d4 lightning. Then it's an ordinary dart."})
    if re.search(r"Staff to Snake\. You throw the staff", text):
        out.append({"key": "orb", "name": "Orb of Lightning", "cost": "action", "daily": True, "range": 60,
                    "target": {"type": "self_area", "aim": True, "area": {"shape": "sphere", "size": 20, "origin": "point"}},
                    "tip": "An orb of lightning bursts (20-ft sphere): DC 15 Dex, 6d6 lightning (half on a success). Once a day."})
        out.append({"key": "snake", "name": "Staff to Snake", "cost": "action", "daily": True, "range": 10, "target": {"type": "self"},
                    "tip": "The staff becomes a giant poisonous snake under your command. Once a day."})
    if re.search(r"tap one of the constellations to invoke it", text):
        out.append({"key": "flames", "name": "Constellation: Flames", "cost": "bonus", "charge": 1, "target": {"type": "self"},
                    "tip": "Until the end of your next turn your hits with this crossbow deal 2d8 fire more. 1 charge."})
        out.append({"key": "rogue", "name": "Constellation: Rogue", "cost": "bonus", "charge": 1, "target": {"type": "self"},
                    "tip": "Invisible until the end of your next turn. 1 charge."})
    return out + lore_activations(item)                     # a blaze, a soul, a wave, a volley, a death-cast, a chaos staff (weaponlore.py)


class ItemExtrasMixin(WeaponLoreMixin):
    def _extra_use(self, c: dict, char, entry: dict, data: dict, p: dict, key: str, target_id, point=None, option=None) -> Optional[str]:
        """Plays one of extra_activations' powers (None: not one of them). The cost is paid here."""
        if p.get("lore"):
            return self._lore_use(c, char, entry, data, p, key, target_id, point, option)
        if key in ("gamble", "rift", "rally", "seek", "orb", "snake"):
            return self._extra_use2(c, char, entry, data, p, key, target_id, point, option)
        if key not in ("feint", "blessing", "runes", "flames", "rogue", "fate"):
            return None
        tgt = self._target(target_id) if key in ("feint", "fate") else c
        if key == "feint" and c.get("pos") and tgt.get("pos") and self._dist(c, tgt) > 5:
            raise ServiceError(f"{tgt['name']} is too far away (5 ft).")
        self._pay(c, p["cost"], f"{entry['name']}: {p['name']}")
        if p.get("daily"):
            char.d["resources"][f"item:{data['name']}:{key}"] = 1
        if p.get("charge"):
            entry["charges_left"] = self._charges_left(entry) - p["charge"]
        char.save()
        until_end = {"end": c["id"], "skip": 1 if self.b.get("turn") == c["id"] else 0}
        if key == "feint":
            self._effect_on(c, f"Fool's Feint ({tgt['name']})", [], None, None, None, None, c["name"], {"adv_vs": tgt["id"]}, None, c["id"],
                            until={"start": c["id"]})
            line = f"{c['name']} feints at {tgt['name']}: advantage on attacks against it until the start of the next turn"
        elif key == "fate":
            self._effect_on(tgt, f"Altered Outcome ({entry['name']})", [], None, None, None, None, c["name"],
                            {"attack": "1d4", "save": "1d4", "check": "1d4", "once": True}, None, c["id"], until={"start": c["id"]})
            line = f"{c['name']} alters {tgt['name']}'s fate: +1d4 on its next roll"
        elif key == "blessing":
            n = int(roll_dice("1d4+4").total)
            self._give_temp(c, n)
            line = f"{c['name']}'s {entry['name']}: {n} temporary hit points"
        elif key == "runes":
            self._effect_on(c, f"{entry['name']} (rune circle)", [], None, None, None, 10, c["name"],
                            {"weapon_attack": "3", "dmg": ("3", ""), "melee_only": True}, None, c["id"])
            line = f"{c['name']} slams {entry['name']} down: a circle of runes (+3 attack and damage)"
        elif key == "flames":
            self._effect_on(c, f"{entry['name']} (Flames)", [], None, None, None, None, c["name"], {"dmg": ("2d8", "fire"), "ranged_only": True},
                            None, c["id"], until=until_end)
            line = f"{c['name']} invokes the Flames on {entry['name']}"
        else:
            self._effect_on(c, f"{entry['name']} (Rogue)", ["Invisible"], None, None, None, None, c["name"], {"rogue": True}, None, c["id"],
                            until=until_end)
            line = f"{c['name']} invokes the Rogue on {entry['name']}: invisible"
        self._commit(line)
        return line

    def _extra_use2(self, c: dict, char, entry: dict, data: dict, p: dict, key: str, target_id, point, option) -> str:
        from . import geometry as G
        if key == "rally":                                      # Sword of the Paruns: an ally's reaction attack on the nearest foe it reaches
            if self._economy_on() and not (c.get("turn") or {}).get("attacked"):
                raise ServiceError("Attack with the sword first.")
            if not self._once_per_turn(c, "paruns"):
                raise ServiceError("Once on each of your turns.")
            ally = self._target(target_id)
            if c.get("pos") and ally.get("pos") and self._dist(c, ally) > 60:
                raise ServiceError(f"{ally['name']} is too far away (60 ft).")
            if not self._may_react(ally):
                raise ServiceError(f"{ally['name']} can't react now.")
            foes = sorted((o for o in self.b["combatants"] if self._hostile(o, ally) and self._alive(o) and o.get("pos") and ally.get("pos")
                           and self._dist(o, ally) <= max(5, self._reach(ally))), key=lambda o: self._dist(o, ally))
            S = self._opportunity_strike(ally, foes[0]) if foes else None
            if S is None:
                raise ServiceError(f"{ally['name']} has nobody in reach to attack.")
            self._spend_reaction(ally, data["name"])
            S["label"] = f"{data['name']}: {ally['name']} attacks"
            out = self._run_r(S)
            self._commit()
            return out
        if key == "gamble":
            n = int(option) if str(option or "") in ("1", "2", "3") else 1
            self._effect_on(c, f"{entry['name']} (+{n})", [], None, None, None, None, c["name"], {"gambler": {entry["name"]: n}, "dsave_minus": n},
                            None, c["id"])
            char.d["resources"][f"item:{data['name']}:gamble"] = 1
            char.save()
            line = f"{c['name']} bets +{n} on {entry['name']} (death saves -{n})"
            self._commit(line)
            return line
        self._pay(c, p["cost"], f"{entry['name']}: {p['name']}")
        if p.get("daily"):
            char.d["resources"][f"item:{data['name']}:{key}"] = 1
            char.save()
        if key == "rift":
            if not c.get("pos"):
                raise ServiceError("Put the hero on the map first.")
            spot = self._free_near(c, c["pos"][0] + 1, c["pos"][1])
            self._add_zone(c, f"Planar rift ({entry['name']})", [spot] if spot else [], {"parts": [], "rift": True}, rounds=10)
            line = f"{c['name']} slices open a rift to another plane"
        elif key == "seek":
            tgt = self._target(target_id)
            if c.get("pos") and tgt.get("pos") and self._dist(c, tgt) > 120:
                raise ServiceError(f"{tgt['name']} is out of range (120 ft).")
            self.chars.remove_item(char.name, entry["name"], 1)       # its magic spent: an ordinary dart now
            self.chars.add_item(char.name, "Dart", 1)
            out = self._run_r(self._strike(c, entry["name"], [tgt["id"]], mode="save", sv={"ab": "dex", "dc": 16, "half": False},
                                           parts=[["1d4", "piercing"], ["3d4", "lightning"]], magical=True))
            self._commit()
            return out
        elif key == "orb":
            if point is None or not c.get("pos"):
                raise ServiceError("Pick where the orb goes.")
            area = p["target"]["area"]
            tiles = G.area_for(area, c["pos"], c.get("span") or 1, tuple(point), *self._bounds())
            ids = [o["id"] for o in G.creatures_in(tiles, self.b["combatants"]) if not self._is_out(o)]
            self._area_vfx(c, tiles, [["6d6", "lightning"]], "sphere", point)
            out = self._run_r(self._strike(c, "Orb of Lightning", ids, mode="save", sv={"ab": "dex", "dc": 15, "half": True},
                                           parts=[["6d6", "lightning"]], magical=True, origin=list(point))) if ids else "The orb bursts over nobody"
            self._commit()
            return out
        else:                                                   # snake
            made = self._add_summons(c, "Giant Poisonous Snake|MM", 1, None, 1, None, None, None, None, data["name"])
            line = f"{c['name']} throws down {entry['name']}: " + ", ".join(m["name"] for m in made)
        self._commit(line)
        return line

    def _weapon_shift(self, att: dict, w: dict) -> int:
        """What comes off a weapon's attack and damage bonus: a Defender's share moved to AC, minus a Gambler's Blade's bet
        and the best magic ammunition the hero carries for it (+1 arrows...)."""
        out = 0
        for e in att.get("effects") or []:
            m = e.get("mods") or {}
            out += int((m.get("defender") or {}).get(w.get("name"), 0)) - int((m.get("gambler") or {}).get(w.get("name"), 0))
        ammo = self._best_ammo(att, w)
        return out - (ammo[2] if ammo else 0)

    def _best_ammo(self, att: dict, w: dict):
        """(pack entry, item, bonus) of the best +N ammunition in the pack that this ranged weapon shoots, or None."""
        from ...rules.data import rules
        char = self._sheet(att) if w.get("ranged") and not att.get("form") else None
        kind = ((rules.item(w.get("weapon_name") or w.get("name") or "") or {}).get("ammo_type") or "").split("|")[0].lower()
        if not char or not kind:
            return None
        best = None
        for e in char.d.get("inventory") or []:
            d = rules.item(e.get("name") or "")
            if d and d.get("type") in ("A", "AF") and d.get("bonus_weapon") and kind in d["name"].lower() and int(e.get("qty") or 1) > 0:
                if best is None or int(d["bonus_weapon"]) > best[2]:
                    best = (e, d, int(d["bonus_weapon"]))
        return best

    SPECIAL_AMMO = ("of slaying", "bloodseeker", "walloping", "winged", "goading", "dispelling")       # the order a shot reaches for them

    def _pick_special_ammo(self, att: dict, tgt: dict, a: dict, modes: set, why: list):
        """A ranged weapon shot with special ammunition from the pack, chosen now the target is known: an arrow of slaying
        for its kind of creature (the kind is in the pack note, e.g. "dragon"; no note: any), a bloodseeker arrow at a
        wounded target (advantage), a walloping arrow, a winged arrow (half cover doesn't count)."""
        from ...rules.data import rules
        a.pop("ammo_special", None)
        if a.get("melee") or not a.get("weapon") or not a.get("item"):
            return
        char = self._sheet(att) if not att.get("form") else None
        kind = ((rules.item((char.find_item(a["item"]) or {}).get("name") or a["item"]) if char else None) or {}).get("ammo_type") or ""
        kind = kind.split("|")[0].lower()
        if not char or not kind:
            return
        tkind = self._kind(tgt)
        for want in self.SPECIAL_AMMO:
            for e in char.d.get("inventory") or []:
                d = rules.item(e.get("name") or "")
                low = (d or {}).get("name", "").lower()
                if not d or d.get("type") not in ("A", "AF") or want not in low or kind not in low:
                    continue
                note = (e.get("note") or "").lower()
                if want == "of slaying" and any(k in note for k in ("dragon", "giant", "undead", "fiend", "beast", "humanoid", "construct",
                                                                   "elemental", "fey", "monstrosity", "aberration", "celestial", "ooze",
                                                                   "plant")) and tkind not in note:
                    continue
                if want == "bloodseeker":
                    if self._hp_of(tgt) >= self._max_hp(tgt):
                        continue
                    modes.add("adv")
                    why.append(d["name"])
                if want == "winged":
                    a["ignore_partial_cover"] = True
                a["ammo_special"] = e["name"]
                return

    def _special_ammo_hit(self, att: dict, tgt: dict, R: dict) -> bool:
        """The special arrow hit: its effect follows (slaying 6d10, walloping prone) and it is spent. True when one was used."""
        name = (R.get("atk") or {}).get("ammo_special")
        char = self._sheet(att)
        e = char.find_item(name) if char and name else None
        if not e:
            return False
        low = e["name"].lower()
        if "of slaying" in low:
            R.setdefault("follow", []).append(self._strike(att, e["name"], [tgt["id"]], mode="save", sv={"ab": "con", "dc": 17, "half": True},
                                                           parts=[["6d10", "piercing"]], magical=True))
        if "walloping" in low:
            R.setdefault("follow", []).append(self._strike(att, e["name"], [tgt["id"]], mode="save",
                                                           sv={"ab": "str", "dc": 10, "half": False, "prone": True}, parts=[], magical=True))
        if "goading" in low:                                    # Goading ammunition (AU): DC 13 Cha or no reactions until its next turn starts
            R.setdefault("follow", []).append(self._strike(att, e["name"], [tgt["id"]], mode="save", magical=True, parts=[],
                                                           sv={"ab": "cha", "dc": 13, "half": False, "mods": {"no_reactions": True}, "until": "target_start"}))
        if "dispelling" in low:                                 # Dispelling ammunition (AU): the spells of level 3 or lower on it end
            self._dispel_low(tgt, R, 3)
        m = re.search(r"\((\d+)\)", e["name"])
        left = int(e.get("shots_left") if e.get("shots_left") is not None else (m.group(1) if m else 1)) - 1
        self._line(R, f"{e['name']} (spent)", e["name"])
        if left > 0 and m:
            e["shots_left"] = left
            char.save()
        else:
            self.chars.remove_item(char.name, e["name"], 1)
        return True

    def _spend_ammo(self, att: dict, item: dict, R: dict):
        """A hit with magic ammunition: that piece is no longer magical (one off a bundle of 20, or the item)."""
        ammo = self._best_ammo(att, {"ranged": True, "name": item["name"], "weapon_name": item["name"]})
        if not ammo:
            return
        char = self._sheet(att)
        e, d, n = ammo
        e = char.find_item(e["name"])
        m = re.search(r"\((\d+)\)", d["name"])
        left = int(e.get("shots_left") if e.get("shots_left") is not None else (m.group(1) if m else 1)) - 1
        self._line(R, f"{d['name']}: +{n} (one piece spent)", d["name"])
        if left > 0 and m:
            e["shots_left"] = left
            char.save()
        else:
            self.chars.remove_item(char.name, e["name"], 1)

    def _weapon_flags(self, w: dict, att: Optional[dict] = None) -> dict:
        """Attack flags from a weapon's own text: Ephixis crits on 19-20 and has no long-range disadvantage; a bow shooting
        magic arrows makes a magical attack."""
        from ...rules.data import rules
        text = (rules.item(w.get("weapon_name") or w.get("name") or "") or rules.item(w.get("name") or "") or {}).get("text") or ""
        out = {"magical": True} if att is not None and self._best_ammo(att, w) else {}
        if re.search(r"scores a critical hit on a d20 roll of 19 or 20", text):
            out["crit_at"] = 19
        if re.search(r"no disadvantage when attacking at the weapon's long range", text):
            out["no_long_dis"] = True
        if re.search(r"Attacks with this weapon ignore half cover and three-quarters cover", text):
            out["ignore_partial_cover"] = True                  # Gungnir (Legends Reforged)
        if att is not None:
            out.update(self._worn_weapon_flags(att, w))         # a Butcher's Bib's 19s, a Battle Standard's magic (spellitems.py)
        hurl = HURL_RE.search(text) if att is not None and "thrown" not in (w.get("props") or []) else None
        if hurl:                                                # a Hammer of Thunderbolts, Azuredge: thrown for a charge (_hurl_spend)
            char = self._sheet(att)
            entry = char.find_item(w["name"]) if char else None
            if entry and self._charges_left(entry) >= int(hurl.group(1)):
                out.update(thrown=True, normal=int(hurl.group(2)), long=int(hurl.group(3)), hurl=int(hurl.group(1)))
        return out

    def _hurl_spend(self, att: dict, w: dict, atk: dict):
        """A weapon hurled for a charge (a Hammer of Thunderbolts, Azuredge): the charge is spent, hit or miss. Nothing when it is swung."""
        if not atk.get("hurl") or atk.get("melee"):
            return
        char = self._sheet(att)
        entry = char.find_item(w["name"]) if char else None
        if entry:
            entry["charges_left"] = max(0, self._charges_left(entry) - atk["hurl"])
            char.save()
            self._say(f"{att['name']} hurls {entry['name']} ({entry['charges_left']} charge{'s' if entry['charges_left'] != 1 else ''} left)")

    def _extra_hit_choice(self, R: dict, att: dict, arg: str, ctx: dict):
        """A chosen after-hit power (hit_choices): a Ruinous Flail's sickness, a Lash of Shadows' poison."""
        from ...rules.data import rules
        name, _sep, key = arg.partition("|")
        item = rules.item(name)
        ch = next((x for x in hit_choices(item) if x["key"] == key), None)
        tgt = self._find_or_none(ctx.get("target"))
        char = self._sheet(att)
        if not ch or tgt is None:
            return
        if ch.get("lore"):                                      # a second bolt at another foe (weaponlore.py)
            self._lore_choice(R, att, item, ch, tgt)
            return
        if ch["daily"] and char:
            char.d["resources"][f"item:{item['name']}:{key}"] = 1
            char.save()
        if key == "named":                                      # a Namer's Needle: the name called out, the hit is a critical hit
            R.setdefault("cur", {})["crit"] = True
            self._line(R, f"{att['name']} calls out {tgt['name']}'s name: the hit with {item['name']} is a critical hit", item["name"])
            return
        if key == "vampiric":                                   # healed by what this hit deals (after the damage), madness save now
            entry = char.find_item(name) if char else None
            if not entry or self._charges_left(entry) < 1:
                return
            entry["charges_left"] = self._charges_left(entry) - 1
            char.save()
            R["vampiric"] = att["id"]
            res = self._saving_throw(att, "wis", 12, label=item["name"])
            self._line(R, f"{att['name']} drinks through {item['name']}" + ("" if res["ok"] else " - and is gripped by short-term madness"),
                       item["name"])
            return
        if ch.get("charge"):                                    # a Diamond Staff's stun, a Martialist's trip: charges spent
            entry = char.find_item(name) if char else None
            if not entry or self._charges_left(entry) < ch["charge"]:
                return
            entry["charges_left"] = self._charges_left(entry) - ch["charge"]
            char.save()
        R.setdefault("follow", []).append(self._strike(att, f"{item['name']} ({ch['label'].split(':')[0]})", [tgt["id"]], mode="save",
                                                       sv=dict(ch["sv"]), parts=[list(x) for x in ch["parts"]], magical=True))
        self._line(R, f"{att['name']} uses {item['name']}: {ch['label'].split(':')[0]}", item["name"])

    def _extra_hit(self, att: dict, tgt: dict, R: dict, item: dict) -> list:
        """Extra damage parts and follow-up saves of the weapons this module knows (see the module's text)."""
        a, cur = R["atk"], R["cur"]
        text, low = item.get("text") or "", item["name"].lower()
        kept = int(cur.get("kept") or 0)
        kind = self._kind(tgt)
        out = []

        def follow(label, sv, parts=()):
            R.setdefault("follow", []).append(self._strike(att, label, [tgt["id"]], mode="save", sv=sv, parts=list(parts), magical=True))

        if not a.get("melee") and not self._special_ammo_hit(att, tgt, R):
            self._spend_ammo(att, item, R)                     # +1 arrows and their kin: spent when they hit
        clap = CLAP_RE.search(text) if a.get("hurl") and not a.get("melee") and tgt.get("pos") else None
        if clap:                                                # a Hammer of Thunderbolts hurled: the target and everyone within 30 ft of it
            near = [o["id"] for o in self.b["combatants"] if o is tgt or (o.get("pos") and not self._is_out(o) and self._dist(tgt, o) <= int(clap.group(1)))]
            R.setdefault("follow", []).append(self._strike(att, f"{item['name']} (thunderclap)", near, mode="save", parts=[], magical=True,
                                                           sv={"ab": clap.group(3).lower()[:3], "dc": int(clap.group(2)), "half": False,
                                                               "conds": [clap.group(4).title()], "until": "caster_end_next"}))
        if low == "wave" and cur.get("crit"):
            out.append([str(max(1, self._max_hp(tgt) // 2)), "necrotic"])
            self._line(R, f"Wave: +{max(1, self._max_hp(tgt) // 2)} necrotic", "Wave")
        if low.startswith("storm boomerang"):
            out.append(["3d4", "thunder"])
            follow("Storm Boomerang", {"ab": "con", "dc": 10, "half": False, "conds": ["Stunned"], "until": "target_end_next"})
        if "roll a 19 or 20 on the attack roll" in text and kept >= 19:
            follow(item["name"], {"ab": "con", "dc": 15, "half": True}, [["6d6", "necrotic"]])
        if " of the medusa" in low and kept == 20:
            follow(item["name"], {"ab": "con", "dc": 15, "half": False, "conds": ["Restrained"], "repeat": "end",
                                  "mods": {"stoning": True, "stone_need": 3}})          # three saves to shake it off, three failures: stone
        if "polymorph blade" in low and kept == 20 and self._alive(tgt) and not (self._monster(tgt) or {}).get("legendary"):
            R.setdefault("item_extra_after", []).append({"polymorph": tgt["id"]})
        if "giant felling" in low and kind == "giant" and not a.get("melee"):
            follow(item["name"], {"ab": "con", "dc": 18, "half": False, "prone": True})
        if "first time you hit any creature with the staff on your turn" in text and self._once_per_turn(att, "rooted"):
            follow(item["name"], {"ab": "str", "dc": 12, "half": False, "conds": ["Restrained"], "until": "caster_start"})
        if "add your Constitution modifier" in text and "to the damage rolls of attacks made with this weapon" in text:
            out.append([str(max(1, self._ability(att, "con"))), (a.get("parts") or [["", "slashing"]])[0][1]])     # a Bloodshed blade
        if "Melody of Reverberation" in text and not a.get("melee") and self._ability(att, "cha") > 0:
            out.append([str(self._ability(att, "cha")), "thunder"])                 # a Longbow of Melodies (the reverberating tune)
        if "target can't regain hit points until the start of your next turn" in text:
            self._effect_on(tgt, f"{item['name']} (no healing)", [], None, None, None, None, att["name"], {"no_heal": True}, None, att["id"],
                            until={"start": att["id"]})
        return out + self._lore_hit(att, tgt, R, item)         # a target at half its hit points, a building charge, bleeding... (weaponlore.py)

    def _extra_after_hit(self, R: dict, att: dict, tgt: dict):
        """A Weapon of Agonizing Paralysis keeps what it drops alive (1 HP, paralyzed); a Polymorph Blade's 20 transforms."""
        for x in R.pop("item_extra_after", None) or []:
            if x.get("polymorph") == tgt["id"] and self._alive(tgt):
                res = self._saving_throw(tgt, "wis", 15, label="Polymorph Blade")
                if not res["ok"]:
                    self._transform(tgt, POLYMORPH_TABLE[self.rng.randint(0, 19)], R)
        self._lore_after_hit(R, att, tgt)                       # riders on a target still standing, a soul trapped (weaponlore.py)
        a = R.get("atk") or {}
        item = self._weapon_item(att, a) if a.get("weapon") else None
        if R.pop("vampiric", None) == att["id"]:                # a Gulthias Staff's Vampiric Strike
            n = int((R.get("dealt") or {}).get(str(tgt["id"])) or 0)
            if n:
                self._heal(att, n)
                self._line(R, f"{att['name']} regains {n} HP", "vampiric")
        if item and "reduce the target to 0 hit points, you gain 2d6 temporary hit points" in (item.get("text") or "") and self._hp_of(tgt) <= 0 \
                and a.get("melee") and not R.get("blood_spear"):
            R["blood_spear"] = True                         # the Blood Spear drinks what it kills
            n = int(roll_dice("2d6").total)
            self._give_temp(att, n)
            self._line(R, f"{att['name']} gains {n} temporary hit points ({item['name']})", "Blood Spear")
        if item and "Devour Soul. Whenever you use it to reduce a creature to 0 hit points" in (item.get("text") or "") and self._hp_of(tgt) <= 0 \
                and self._kind(tgt) not in ("construct", "undead") and not R.get("devoured"):
            R["devoured"] = True                            # Blackrazor feeds: the slain one's hit point maximum, and advantage while it lasts
            n = self._max_hp(tgt)
            self._give_temp(att, n)
            self._effect_on(att, "Blackrazor's hunger", [], None, None, None, 14400, att["name"],
                            {"attacks_with": "adv", "save_adv": ["all"], "check_adv": True}, None, att["id"])
            self._line(R, f"Blackrazor devours {tgt['name']}'s soul: {att['name']} gains {n} temporary hit points", "soul devoured")
        if item and "soul funneled into the River Styx" in (item.get("text") or "") and self._hp_of(tgt) <= 0 and self._kind(tgt) == "humanoid" \
                and not R.get("styx"):
            R["styx"] = True                                # a Hellfire weapon: the soul goes to the Styx, a lemure is born
            self._line(R, f"{tgt['name']}'s soul is dragged into the River Styx: it is reborn as a lemure", "soul taken")
        if item and "of agonizing paralysis" in item["name"].lower() and self._hp_of(tgt) <= 0 and tgt["kind"] != "pc" and not tgt.get("conjured"):
            self._set_hp(tgt, 1)
            self._effect_on(tgt, f"Agonizing Paralysis ({item['name']})", ["Paralyzed"], None, None, None, None, att["name"],
                            {"agonized": True}, None, att["id"])
            self._line(R, f"{tgt['name']} doesn't die: infernal runes paralyze it at 1 hit point", "paralyzed")
