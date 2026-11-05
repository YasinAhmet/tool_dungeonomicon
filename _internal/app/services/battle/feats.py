"""Situational feats in battle (rules/combat_feats.py holds the list and the switches).

The other parts call these hooks at the right moment: building a weapon attack (power attacks, Sharpshooter's and
Crossbow Expert's exemptions), rolling damage (Savage Attacker, Piercer), after a hit (Crusher, Slasher, Great Weapon
Master's bonus attack), taking damage (Heavy Armor Master), and the bonus actions some feats unlock (Polearm Master's
butt end, a hand crossbow shot, Shield Master's shove, Charger, Tavern Brawler, Telekinetic, Healer).
"""
import re
from typing import List, Optional

from ...rules import combat_feats as CF
from ..common import ServiceError
from .resolve import roll

POLEARMS = ("glaive", "halberd", "quarterstaff", "spear", "pike")
LIMITS = {"Lucky": (3, "long"), "Second Chance": (1, "short"), "Fade Away": (1, "short"), "Orcish Fury": (1, "short"),
          "Chromatic Infusion": (1, "long"), "Reactive Resistance": ("pb", "long"), "Protective Wings": ("pb", "long"),
          "Telekinetic Reprisal": ("pb", "long")}


class FeatsMixin:
    # ------------------------------------------------------------------ switches and use counters
    def _feat(self, c: Optional[dict], key: str):
        """The feat's switch for this creature (False for monsters and characters without the feat)."""
        if not c or c.get("form"):
            return False
        char = self._sheet(c)
        return CF.is_on(char, key) if char else False

    def _feat_uses_left(self, c: dict, name: str) -> int:
        char = self._sheet(c)
        if not char:
            return 0
        n, rest = LIMITS[name]
        n = char.proficiency_bonus if n == "pb" else n
        key = ("short:" if rest == "short" else "feat:") + name
        return max(0, n - int(char.d["resources"].get(key, 0)))

    def _feat_use(self, c: dict, name: str) -> bool:
        if self._feat_uses_left(c, name) <= 0:
            return False
        char = self._sheet(c)
        key = ("short:" if LIMITS[name][1] == "short" else "feat:") + name
        char.d["resources"][key] = int(char.d["resources"].get(key, 0)) + 1
        char.save()
        return True

    # ------------------------------------------------------------------ attacks
    def _feat_attack(self, att: dict, w: dict, atk: dict) -> dict:
        """A weapon attack as the attacker's feats change it."""
        char = self._sheet(att)
        if not char or att.get("form"):
            return atk
        props = w.get("props") or []
        name = (w.get("weapon_name") or w.get("name") or "").lower()
        dtype = atk["parts"][0][1] if atk.get("parts") else ""
        atk["ability"] = w.get("ability")
        if self._feat(att, "great_weapon_master") and atk["melee"] and "heavy" in props and "not proficient" not in (w.get("notes") or []):
            atk["bonus"] -= 5
            atk["parts"] = list(atk["parts"]) + [["10", dtype]]
            atk["power"] = "Great Weapon Master"
        if CF.has(char, "sharpshooter") and not atk["melee"]:
            atk["no_long_dis"] = True
            atk["ignore_partial_cover"] = True
            if self._feat(att, "sharpshooter"):
                atk["bonus"] -= 5
                atk["parts"] = list(atk["parts"]) + [["10", dtype]]
                atk["power"] = "Sharpshooter"
        if not atk["melee"] and (self._feat(att, "crossbow_expert") or self._race_firearm(att, w)):      # Gunner, a giff's Firearms Mastery (racefeats.py)
            atk["no_melee_dis"] = True
        if self._nf_has(att, "Bomber") and ("thrown" in props or atk.get("thrown")):
            atk["no_long_dis"] = True                       # Bomber's Long Shots (newfeats.py)
        if "unarmed" in props:
            atk["unarmed"] = True
        if any(p in name for p in POLEARMS):
            atk["polearm"] = True
        return atk

    def _feat_attack_label(self, atk: dict, label: str) -> str:
        return f"{label} ({atk['power']} −5 / +10)" if atk.get("power") else label

    def _feat_damage(self, R: dict, att: dict, tgt: dict, rolled: List[list], parts: List[list]) -> List[list]:
        """Savage Attacker and Piercer reroll damage once per turn."""
        a = R.get("atk") or {}
        if not a.get("weapon"):
            return rolled
        key = [self.b.get("round"), self.b.get("turn")]
        if self._feat(att, "savage_attacker") and a.get("melee") and att.get("savage_used") != key:
            again = self._roll_parts(parts, R["cur"].get("crit"))
            att["savage_used"] = key
            if sum(n for n, _t in again) > sum(n for n, _t in rolled):
                self._line(R, f"Savage Attacker: rerolled damage, {sum(n for n, _t in again)} instead of {sum(n for n, _t in rolled)}", "")
                rolled = again
        if self._feat(att, "piercer") and att.get("piercer_used") != key:
            for i, (d, t) in enumerate(parts):
                m = re.match(r"(\d*)d(\d+)", str(d))
                if t == "piercing" and m and i < len(rolled):
                    att["piercer_used"] = key
                    sides = int(m.group(2))
                    low = self.rng.randint(1, sides)
                    new = self.rng.randint(1, sides)
                    if new > low:
                        rolled[i][0] += new - low
                    if R["cur"].get("crit"):
                        rolled[i][0] += self.rng.randint(1, sides)
                    break
        return rolled

    def _feat_after_hit(self, R: dict, att: dict, tgt: dict):
        """After a weapon hit lands: Crusher, Slasher, and Great Weapon Master's bonus attack on a crit or a kill."""
        a = R.get("atk") or {}
        cur = R.get("cur") or {}
        if not a.get("weapon") or not self._sheet(att):
            return
        key = [self.b.get("round"), self.b.get("turn")]
        types = {t for _n, t in cur.get("dmg") or []}
        if self._feat(att, "crusher") and "bludgeoning" in types:
            if att.get("crusher_used") != key and self._alive(tgt):
                att["crusher_used"] = key
                self._push(tgt, att, 5, R)
            if cur.get("crit"):
                self._effect_on(tgt, "Crushed", [], None, None, None, None, att["name"], {"attacks_against": "adv"}, None, att["id"],
                                until={"start": att["id"]})
        if self._feat(att, "slasher") and "slashing" in types:
            if att.get("slasher_used") != key:
                att["slasher_used"] = key
                self._effect_on(tgt, "Slashed", [], None, None, None, None, att["name"], {"speed": -10}, None, att["id"], until={"start": att["id"]})
            if cur.get("crit"):
                self._effect_on(tgt, "Grievous wound", [], None, None, None, None, att["name"], {"attacks_with": "dis"}, None, att["id"],
                                until={"start": att["id"]})
        if a.get("melee") and CF.has(self._sheet(att), "great_weapon_master") and (cur.get("crit") or not self._alive(tgt)):
            t = att.get("turn")
            if t is not None and self.b.get("turn") == att["id"]:
                t["gwm_bonus"] = True
                self._line(R, f"{att['name']} can make a bonus-action attack (Great Weapon Master)", "")
        if a.get("unarmed") and self._feat(att, "tavern_brawler") and att.get("turn") is not None:
            att["turn"]["brawl_grapple"] = tgt["id"]

    # ------------------------------------------------------------------ the bonus actions feats unlock
    def _feat_bonus_options(self, c: dict) -> List[dict]:
        """[{'key', 'name', 'weapon', 'target', 'tip', 'why'}] for the action bar."""
        char = self._sheet(c)
        if not char or c.get("form"):
            return []
        t = c.get("turn") or {}
        out = []
        weapons = char.attacks()
        attacked = t.get("attacked") or not self._economy_on()
        if t.get("gwm_bonus") or not self._economy_on() and CF.has(char, "great_weapon_master"):
            for w in weapons:
                if not w.get("ranged") and "unarmed" not in (w.get("props") or []):
                    out.append({"key": "gwm", "name": f"GWM bonus attack ({w['name']})", "weapon": w["name"],
                                "why": None if t.get("gwm_bonus") or not self._economy_on() else "Needs a critical hit or a kill first"})
                    break
        if self._feat(c, "polearm_master"):
            pole = next((w for w in weapons if any(p in (w.get("weapon_name") or w["name"]).lower() for p in POLEARMS)), None)
            if pole:
                out.append({"key": "polearm", "name": f"Polearm butt end ({pole['name']})", "weapon": pole["name"],
                            "why": None if attacked else "Take the Attack action first"})
        if self._feat(c, "crossbow_expert"):
            hc = next((w for w in weapons if "hand crossbow" in (w.get("weapon_name") or w["name"]).lower()), None)
            if hc:
                out.append({"key": "crossbow", "name": f"Hand crossbow shot ({hc['name']})", "weapon": hc["name"],
                            "why": None if attacked else "Take the Attack action first"})
        if self._feat(c, "charger"):
            mw = next((w for w in weapons if not w.get("ranged")), None)
            if mw:
                out.append({"key": "charger", "name": f"Charger ({mw['name']})", "weapon": mw["name"], "options": ["attack", "shove"],
                            "why": None if t.get("dashed") or not self._economy_on() else "Take the Dash action first"})
        if self._feat(c, "shield_master") and char.equipped_shield():
            out.append({"key": "shield_shove", "name": "Shield Master shove", "weapon": None, "shove": True, "options": ["prone", "push"],
                        "why": None if attacked else "Take the Attack action first"})
        if self._feat(c, "tavern_brawler"):
            out.append({"key": "brawl_grapple", "name": "Tavern Brawler grapple", "weapon": None, "grapple": True,
                        "why": None if t.get("brawl_grapple") or not self._economy_on() else "Hit with an unarmed strike first"})
        if self._feat(c, "telekinetic"):
            out.append({"key": "telekinetic", "name": "Telekinetic shove", "weapon": None, "range": 30, "why": None})
        if self._feat(c, "gift_chromatic"):
            out.append({"key": "chromatic", "name": "Chromatic Infusion", "weapon": None, "self": True, "options": CF.ELEMENTS + ["poison"],
                        "why": None if self._feat_uses_left(c, "Chromatic Infusion") else "Used until a long rest"})
        return out

    def feat_action(self, cid: int, key: str, target_id: Optional[int] = None, option: Optional[str] = None, adv: Optional[str] = None) -> str:
        """A bonus action a feat unlocks (see _feat_bonus_options), or the Healer feat's action."""
        with self.lock:
            self._busy()
            c = self._find(cid)
            char = self._sheet(c)
            if not char:
                raise ServiceError("Only characters have feats here.")
            if key == "healer":
                tgt = self._find(target_id or self.b.get("target") or cid)
                if not CF.has(char, "healer"):
                    raise ServiceError(f"{c['name']} doesn't have the Healer feat.")
                if c.get("pos") and tgt.get("pos") and self._dist(c, tgt) > 5:
                    raise ServiceError(f"{tgt['name']} is too far away")
                used = c.setdefault("healed_by_kit", [])
                self._pay(c, "action", "Healer")
                if self._hp_of(tgt) <= 0:
                    tc = self._sheet(tgt)
                    if tc:
                        tc.d["death_saves"] = {"success": 3, "failure": 0}
                        tc.save()
                    self._commit(f"{c['name']} stabilizes {tgt['name']} with a healer's kit")
                    return f"{tgt['name']} is stable"
                if tgt["id"] in used:
                    raise ServiceError(f"{tgt['name']} was already treated (once per rest).")
                tc = self._sheet(tgt)
                hd = tc.total_level if tc else max(1, int(re.match(r"(\d+)", (self._monster(tgt) or {}).get("hp_formula", "1") or "1").group(1)))
                n = roll("1d6") + 4 + hd
                self._heal(tgt, n)
                used.append(tgt["id"])
                self._commit(f"{c['name']} treats {tgt['name']} with a healer's kit: +{n} HP")
                return f"{tgt['name']} +{n} HP"
            opt = next((o for o in self._feat_bonus_options(c) if o["key"] == key), None)
            if not opt:
                raise ServiceError("That isn't available now.")
            if opt.get("why"):
                raise ServiceError(opt["why"])
            if key == "chromatic":
                element = option if option in (CF.ELEMENTS + ["poison"]) else "fire"
                self._pay(c, "bonus", opt["name"])
                self._feat_use(c, "Chromatic Infusion")
                self._effect_on(c, "Chromatic Infusion", [], None, None, None, 10, c["name"], {"dmg": ("1d4", element)}, None, c["id"])
                self._commit(f"{c['name']} infuses its weapon with {element}")
                return f"Weapon hits deal +1d4 {element}"
            tgt = self._target(target_id)
            if key == "charger" and option == "shove":           # Charger's shove: after a 10-foot straight run it pushes 10 ft
                if c.get("pos") and tgt.get("pos") and self._dist(c, tgt) > 5:
                    raise ServiceError(f"{tgt['name']} is too far away")
                ran = self._run_ft(c) >= 10
                return self._feat_contest(c, tgt, "shove", "push", opt["name"], push=10 if ran else 5)
            if opt.get("shove") or key == "telekinetic":
                if key == "telekinetic":
                    if c.get("pos") and tgt.get("pos") and self._dist(c, tgt) > 30:
                        raise ServiceError(f"{tgt['name']} is out of range (30 ft)")
                    self._pay(c, "bonus", opt["name"])
                    ab = max(("int", "wis", "cha"), key=char.mod)
                    res = self._saving_throw(tgt, "str", 8 + char.proficiency_bonus + char.mod(ab), label="Telekinetic")
                    if not res["ok"]:
                        self._push(tgt, c, 5)
                    self._commit(f"{c['name']} shoves {tgt['name']} with the mind: " + ("pushed 5 ft" if not res["ok"] else "resisted"))
                    return "pushed" if not res["ok"] else "resisted"
                return self._feat_contest(c, tgt, "shove", option, opt["name"])
            if opt.get("grapple"):
                return self._feat_contest(c, tgt, "grapple", option, opt["name"])
            w = next(a for a in char.attacks() if a["name"] == opt["weapon"])
            atk = self._feat_attack(c, w, self._check_reach(c, tgt, self._weapon_atk(c, w)))
            atk["adv"] = adv
            label = w["name"]
            if key == "polearm":
                mod = char.mod(w.get("ability") or "str")
                atk["parts"] = [[f"1d4{mod:+d}" if mod else "1d4", "bludgeoning"]] + [p for p in atk["parts"][1:] if atk.get("power")]
                label = f"{w['name']} (butt end)"
            if key == "charger" and self._run_ft(c) >= 10:      # "If you move at least 10 feet in a straight line immediately before"
                atk["parts"] = list(atk["parts"]) + [["5", atk["parts"][0][1]]]
                label = f"{w['name']} (charge)"
            self._pay(c, "bonus", opt["name"])
            if key == "gwm" and c.get("turn"):
                c["turn"]["gwm_bonus"] = False
            out = self._run_r(self._strike(c, self._feat_attack_label(atk, label), [tgt["id"]], mode="attack", atk=atk,
                                           magical=atk.get("magical", False)))
            self._commit()
            return out

    def _feat_contest(self, c: dict, tgt: dict, kind: str, option: Optional[str], name: str, push: int = 5) -> str:
        """A bonus-action shove or grapple: Athletics against the target's Athletics or Acrobatics."""
        self._pay(c, "bonus", name)
        mine = self._check(c, "Athletics")
        theirs = max(self._check(tgt, "Athletics"), self._check(tgt, "Acrobatics")) if self._can_act(tgt) else 0
        if mine < theirs:
            line = f"{c['name']} fails to {kind} {tgt['name']} ({mine} vs {theirs})"
        elif kind == "grapple":
            self._effect_on(tgt, f"Grappled by {c['name']}", ["Grappled"], None, None, None, None, c["name"], {"grappler": c["id"]}, None, c["id"])
            line = f"{c['name']} grapples {tgt['name']} ({mine} vs {theirs})"
        elif option == "push":
            self._push(tgt, c, push)
            line = f"{c['name']} shoves {tgt['name']} away{f' {push} ft' if push != 5 else ''} ({mine} vs {theirs})"
        else:
            self._cond(tgt, "Prone", True)
            line = f"{c['name']} knocks {tgt['name']} prone ({mine} vs {theirs})"
        self._commit(line)
        return line
