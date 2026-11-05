"""Hit points and conditions dealt from the tracker (typed damage, several at once, condition timers), and the rolls
made from a combatant's card."""
import re
from typing import List, Optional

from ...rules import engine as E
from ...rules.dice import roll_dice
from ..common import ServiceError
from . import conditions as K
from . import modifiers as M
from .constants import ACTIVE, FACTIONS

ABILITIES = ("str", "dex", "con", "int", "wis", "cha")


class ActionsMixin:
    # ------------------------------------------------------------------ combat actions
    def damage_types(self) -> List[str]:
        """The damage types the engine knows, lower case (acid, bludgeoning, cold...)."""
        return list(M.TYPES)

    def _targets(self, ids) -> List[dict]:
        rows = [self._find(int(i)) for i in dict.fromkeys(ids or [])]
        if not rows:
            raise ServiceError("Pick at least one combatant.")
        return rows

    def _hurt(self, c: dict, amount: int, dtype: Optional[str], half: bool, magical: bool) -> str:
        """Damage typed in by the DM. With a type it lands like the engine's (resistances, immunities, temporary HP,
        concentration, dropping to 0); `half` halves it first (rounded down), as for a successful save."""
        if c.get("conjured"):
            raise ServiceError(f"{c['name']} is a spell's effect: it takes no damage.")
        amount = max(0, int(amount))
        if half:
            amount //= 2
        tag = " (halved)" if half else ""
        dtype = (dtype or "").strip().lower() or None
        if dtype:
            if dtype not in M.TYPES:
                raise ServiceError(f"Unknown damage type '{dtype}'.")
            text = self._deal_rolled(c, [[amount, dtype]], label="Damage", magical=magical)
            head, arrow, tail = text.partition(" → ")
            return head + tag + arrow + tail
        before = self._hp_of(c)
        if c["kind"] == "pc":
            if amount or not half:
                self.chars.damage(c["character"], str(amount))
        else:
            self._lose_hp(c, amount)
        self._vfx("dmg", id=c["id"], amt=amount, dtype="", crit=False)
        self._conc_check(c, amount)
        if amount > 0:
            self._trait_hurt(c, set(), amount)                 # Flaring Eye, Seven Radiances count the DM's plain damage too (traits.py)
        if before > 0 and self._hp_of(c) <= 0:
            self._zero_hp(c, None)                             # down: a summon vanishes, a magmin bursts...
        return f"{c['name']} takes {amount} damage{tag}" + (" and is defeated" if c["kind"] == "enemy" and c["hp"] <= 0 else "")

    def damage(self, cid: int, amount: int, dtype: Optional[str] = None, half: bool = False, magical: bool = True) -> str:
        """Hurt one combatant. `dtype` (see damage_types) applies its resistances, immunities and vulnerabilities;
        `half` halves the damage first (a successful save); `magical` False lets resistance to nonmagical weapons count."""
        with self.lock:
            c = self._find(cid)
            line = self._hurt(c, amount, dtype, half, magical)
            self._commit(line)
            return line

    def damage_many(self, ids: List[int], amount: int, dtype: Optional[str] = None, halved: Optional[List[int]] = None,
                    magical: bool = True) -> str:
        """The same damage to several combatants at once (one undo step); those in `halved` saved for half."""
        with self.lock:
            rows = [c for c in self._targets(ids) if not c.get("conjured")] or self._targets(ids)   # tokens take no damage
            half = {int(i) for i in halved or []}
            lines = []
            for c in rows:
                lines.append(self._hurt(c, amount, dtype, c["id"] in half, magical))
                self._say(lines[-1])
            kind = f" {dtype.strip().lower()}" if dtype and dtype.strip() else ""
            self._commit(label=f"{max(0, int(amount))}{kind} damage to " + ", ".join(c["name"] for c in rows))
            return "\n".join(lines)

    def _mend(self, c: dict, amount: int) -> str:
        amount = max(0, int(amount))
        if c["kind"] == "pc":
            self.chars.heal(c["character"], str(amount))
        else:
            c["hp"] = min(c["max_hp"], c["hp"] + amount)
        self._vfx("heal", id=c["id"], amt=amount)
        return f"{c['name']} heals {amount}"

    def heal(self, cid: int, amount: int) -> str:
        with self.lock:
            line = self._mend(self._find(cid), amount)
            self._commit(line)
            return line

    def heal_many(self, ids: List[int], amount: int) -> str:
        """Heal several combatants by the same amount (one undo step)."""
        with self.lock:
            rows = self._targets(ids)
            lines = []
            for c in rows:
                lines.append(self._mend(c, amount))
                self._say(lines[-1])
            self._commit(label=f"Heal {max(0, int(amount))}: " + ", ".join(c["name"] for c in rows))
            return "\n".join(lines)

    def set_condition(self, cid: int, condition: str, on: bool, rounds: Optional[int] = None, until: str = "end",
                      by: Optional[int] = None, save: Optional[dict] = None) -> str:
        """Put a condition on (or off). With `rounds` it ends by itself after that many rounds, at the end (or start,
        `until`='start') of the turn of combatant `by` (the creature itself by default). With `save`
        {'ability': 'wis', 'dc': 13} the creature repeats the save at the end of each of its turns, a success ends it.
        Turning a condition off (or setting it again) drops its earlier timer."""
        with self.lock:
            line = self._condition(self._find(cid), condition, on, rounds, until, by, save)
            self._commit(line)
            return line

    def set_condition_many(self, ids: List[int], condition: str, on: bool, **duration) -> str:
        """set_condition for several combatants at once (one undo step); `duration`: rounds, until, by, save."""
        with self.lock:
            rows = self._targets(ids)
            lines = []
            for c in rows:
                lines.append(self._condition(c, condition, on, **duration))
                self._say(lines[-1])
            self._commit(label=f"{condition} {'on' if on else 'off'}: " + ", ".join(c["name"] for c in rows))
            return "\n".join(lines)

    def _condition(self, c: dict, condition: str, on: bool, rounds: Optional[int] = None, until: str = "end",
                   by: Optional[int] = None, save: Optional[dict] = None) -> str:
        timer = self._timer_for(c, rounds, until, by, save) if on and (rounds or save) else None
        self._timer_off(c, condition)
        if c["kind"] == "pc":
            char = self._char(c["character"])
            have = bool(char) and condition in char.conditions
            self.chars.set_condition(c["character"], condition, on)
        else:
            have = condition in c["conditions"]
            if on and not have:
                c["conditions"].append(condition)
            elif not on and have:
                c["conditions"].remove(condition)
        if on != have:
            self._vfx("cond", id=c["id"], name=condition, on=on)
        if on and c.get("concentrating") and K.incapacitated([condition]):
            self._drop_conc(c, condition.lower())               # the DM paralyzes a caster: its spell ends
        line = f"{c['name']} {'is now' if on else 'is no longer'} {condition}"
        if timer:
            timer["condition"] = condition
            sv = timer["save"]
            c.setdefault("effects", []).append({"name": condition, "conditions": [condition], "ability": sv["ability"] if sv else None,
                                                "dc": sv["dc"] if sv else None, "repeat": "end" if sv else None, "rounds": None,
                                                "source": "DM", "mods": {}, "conc_by": None, "source_id": None, "until": None,
                                                "timer": timer})
            line += self._timer_text(timer)
        return line

    def _timer_for(self, c: dict, rounds, until: str, by, save) -> dict:
        if until not in ("end", "start"):
            raise ServiceError("A condition ends at the start or the end of a turn.")
        if rounds is not None:
            rounds = int(rounds)
            if not 1 <= rounds <= 1000:
                raise ServiceError("A condition lasts between 1 and 1000 rounds.")
        by = c["id"] if by is None else self._find(int(by))["id"]
        sv = None
        if save:
            ab = str(save.get("ability") or "").lower()[:3]
            if ab not in ABILITIES:
                raise ServiceError("Pick the ability of the saving throw.")
            try:
                dc = int(save.get("dc"))
            except (TypeError, ValueError):
                raise ServiceError("The save DC is a number.")
            sv = {"ability": ab, "dc": max(1, min(40, dc))}
        mine_now = self.b["status"] == ACTIVE and self.b.get("turn") == by
        return {"rounds": rounds, "until": until, "by": by, "save": sv, "grace": bool(rounds and until == "end" and mine_now)}

    def _timer_text(self, t: dict) -> str:
        bits = []
        if t["rounds"]:
            who = "its" if t["by"] is None else f"{self._name_of(t['by'])}'s"
            bits.append(f"for {t['rounds']} round{'s' if t['rounds'] != 1 else ''} (until the {t['until']} of {who} turn)")
        if t["save"]:
            bits.append(f"{t['save']['ability'].upper()} save DC {t['save']['dc']} at the end of each of its turns")
        return " " + "; ".join(bits) if bits else ""

    @staticmethod
    def _timer_off(c: dict, condition: str):
        """The DM's timer for this condition goes (silently): it was turned off or set again."""
        c["effects"] = [e for e in c.get("effects") or [] if (e.get("timer") or {}).get("condition") != condition]

    def _tick_timers(self, cid: int, when: str):
        """A turn of `cid` starts or ends: the DM's condition timers counting on it go down by a round."""
        for o in self.b["combatants"]:
            for eff in list(o.get("effects") or []):
                t = eff.get("timer")
                if not t or t.get("rounds") is None or t["by"] != cid or t["until"] != when:
                    continue
                if t.get("grace"):
                    t["grace"] = False
                    continue
                t["rounds"] -= 1
                if t["rounds"] <= 0:
                    self._effect_off(o, eff, "its time is up")

    @staticmethod
    def cond_timers(c: dict) -> dict:
        """{condition: {'rounds', 'until', 'by', 'save'}}: the DM's condition timers on a combatant (from the battle)."""
        out = {}
        for e in c.get("effects") or []:
            t = e.get("timer")
            if t and t.get("condition"):
                out[t["condition"]] = {"rounds": t["rounds"], "until": t["until"], "by": t["by"], "save": t["save"]}
        return out

    # ------------------------------------------------------------------ rolls made from a combatant's card
    def roll_d20(self, cid: int, label: str, modifier: int, adv: Optional[str] = None) -> str:
        """An attack, check or save for a combatant; written to the battle log. Bless, Guidance, Bane... change it."""
        with self.lock:
            c = self._find(cid)
            low = label.lower()
            key = "save" if "save" in low else "attack" if "attack" in low else "check"
            extra, note = self._mod_roll(c, key)
            adv = adv if adv in ("adv", "dis") else None
            if key == "check" and self._fx(c, "check_adv"):
                adv = None if adv == "dis" else "adv"
            if key == "save":
                ab = low.split()[0][:3]
                have = {"adv" for _e, v in self._fx(c, "save_adv") if ab in v or "all" in v} | {"dis" for _e, v in self._fx(c, "save_dis") if ab in v or "all" in v}
                if have == {"adv"}:
                    adv = None if adv == "dis" else "adv"
                elif have == {"dis"}:
                    adv = None if adv == "adv" else "dis"
            total, dice = E.roll_d20(int(modifier), adv, self.rng)
            shown = f"{dice[0]}" if len(dice) == 1 else f"{dice[0]}, {dice[1]} ({'adv' if adv == 'adv' else 'dis'})"
            kept = total - int(modifier)
            nat = " - natural 20!" if kept == 20 else " - natural 1" if kept == 1 else ""
            text = f"{c['name']} {label}: d20 [{shown}] {int(modifier):+d}{note} = {total + extra}{nat}"
            self._commit(text)
            self._roll_line(c, "🎲", label, total + extra, f"d20 [{shown}] {int(modifier):+d}{note}"
                           + (" · **NAT 20**" if kept == 20 else " · **NAT 1**" if kept == 1 else ""))
            return text

    def roll_damage(self, cid: int, label: str, parts: List[List[str]], crit: bool = False) -> str:
        """Roll damage parts [[expression, type], ...] (dice doubled on a critical hit)."""
        with self.lock:
            c = self._find(cid)
            rolled, total = [], 0
            for expr, kind in parts:
                r = roll_dice(E.double_dice(expr) if crit else expr)
                total += r.total
                rolled.append(f"{r.total} {kind}".strip())
            text = f"{c['name']} {label}{' (critical)' if crit else ''}: {' + '.join(rolled)}" + (f" = {total}" if len(rolled) > 1 else "")
            self._commit(text)
            self._roll_line(c, "💥", f"{label}{' (critical)' if crit else ''} damage", total, ", ".join(rolled))
            return text

    def announce(self, cid: int, text: str) -> str:
        """Put a line about a combatant's action (a spell cast, a recharge...) in the battle log."""
        with self.lock:
            line = f"{self._find(cid)['name']} {text}"
            self._commit(line)
            return line

    def set_note(self, cid: int, note: str):
        with self.lock:
            self._find(cid)["notes"] = note.strip()
            self._commit()

    def set_faction(self, ids: List[int], faction: int) -> str:
        """Put creatures in a faction (0 neutral - hostile to everyone - or 1 to 4); their summons go with them.
        Who is hostile to whom (opportunity attacks, reactions, auras, allies' help) follows the factions."""
        faction = int(faction)
        if faction not in FACTIONS:
            raise ServiceError("A faction is 0 (neutral) or 1 to 4.")
        with self.lock:
            cs = [self._find(cid) for cid in ids]
            moved = {c["id"] for c in cs}
            for c in cs:
                c["faction"] = faction
            for o in self.b["combatants"]:                      # a summon follows its summoner (unless it turned on them)
                if o["id"] not in moved and o.get("summoned_by") in moved and not o.get("turned"):
                    o["faction"] = faction
            who = ", ".join(c["name"] for c in cs)
            line = f"{who} {'is' if len(cs) == 1 else 'are'} now " + ("neutral (hostile to everyone)" if faction == 0 else f"in faction {faction}")
            self._commit(line)
            return line

    def set_faction_color(self, faction: int, color: Optional[str]):
        """A faction's token ring colour ('#rrggbb'), or None for its default."""
        faction = int(faction)
        if faction not in FACTIONS:
            raise ServiceError("A faction is 0 (neutral) or 1 to 4.")
        with self.lock:
            colors = self.b.setdefault("faction_colors", {})
            if color:
                if not re.fullmatch(r"#[0-9a-fA-F]{6}", color):
                    raise ServiceError("A colour is written #rrggbb.")
                colors[str(faction)] = color.lower()
            else:
                colors.pop(str(faction), None)
            self._commit()

    def reveal(self, cid: Optional[int] = None, on: bool = True):
        """Show an enemy's real hit points to the players (cid=None toggles it for every enemy)."""
        with self.lock:
            if cid is None:
                self.b["reveal_hp"] = on
            else:
                self._find(cid)["revealed"] = on
            self._commit()
