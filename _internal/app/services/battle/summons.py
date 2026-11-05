"""Summoning creatures with spells, class companions, and the tokens of conjured things (Spiritual Weapon, Bigby's Hand).

A summon is a combatant with `summoned_by` (its caster), `summon_conc` (the caster whose concentration keeps it) and
`summon` - the caster's numbers its stat block uses (summon_stats.py). Losing concentration sends most summons away;
the ones in spell_effects.TURN_ON_CONC_LOSS (Conjure Elemental...) stay and change sides.
"""
from typing import Optional, Tuple

from ...rules.data import rules
from ...rules.monsters import ability_mod, bestiary
from ..common import ServiceError
from . import combat_rules as CR
from . import geometry as G
from . import spell_effects as X
from . import summon_stats as SS
from .constants import SPANS

ONLY_ONE = {"find familiar", "find steed", "find greater steed", "battle familiar"}     # "you can't have more than one ... at a time"


class SummonsMixin:
    # ---- summoning
    def _summon_options(self, key: str, level: int) -> list:
        """What the caster can pick from: [{'value', 'label', 'monster', 'count', 'variant'}], or [] when nothing needs choosing."""
        if key in X.SPIRITS:
            mid, variants, _ac = X.SPIRITS[key]
            return [{"value": v, "label": v, "monster": mid, "count": 1, "variant": v} for v in variants]
        if key in X.CHOICES:
            out = []
            for mid, n, min_level in X.CHOICES[key]:
                m = bestiary.get(mid)
                if key == "animate objects" and m:              # two more objects per slot level above 5th (Medium counts as two, Large four, Huge eight)
                    n = (10 + 2 * max(0, level - 5)) // {"Medium": 2, "Large": 4, "Huge": 8}.get(m["name"].split("(")[-1].rstrip(")"), 1)
                if m and level >= min_level:
                    out.append({"value": mid, "label": f"{m['name']} (CR {m['cr']}, {m['hp']} HP)" + (f" ×{n}" if n > 1 else ""), "monster": mid, "count": n, "variant": None})
            return out if len(out) > 1 else []
        if key in X.LADDERS:
            types, tag, ladder, _top, base_level, per = X.LADDERS[key]
            mult = 1 + max(0, level - base_level) // per
            asc = sorted(ladder)
            out, seen = [], set()
            for m in bestiary.offered() or bestiary.all:     # (no ticked book with creatures: the spell still works)
                if m["type"] not in types or (tag and tag not in m["tags"]) or m["name"] in seen:
                    continue
                top = asc[-1][0] + (max(0, level - base_level) if len(asc) == 1 and tag in ("demon",) else 0)
                if m["cr_num"] > top:
                    continue
                n = next((cnt for cr, cnt in asc if m["cr_num"] <= cr), 1)
                seen.add(m["name"])
                out.append({"value": m["id"], "label": f"{m['name']} (CR {m['cr']}) ×{n * mult}", "monster": m["id"], "count": n * mult, "variant": None, "cr": m["cr_num"]})
            return sorted(out, key=lambda o: (-o["cr"], o["label"]))
        return []

    def summon_options(self, spell_name: str, slot_level: Optional[int] = None) -> list:
        sp = rules.spell(spell_name)
        return [{"value": o["value"], "label": o["label"]} for o in self._summon_options(CR.norm(sp["name"]), slot_level or sp["level"])] if sp else []

    def _summoner_ctx(self, owner: dict, *, level: Optional[int] = None, attack: Optional[int] = None, dc: Optional[int] = None,
                      variant: Optional[str] = None, cls: Optional[str] = None) -> dict:
        """The numbers a summon's stat block borrows from its summoner (spell attack, save DC, spell level, PB...)."""
        char = self._sheet(owner)
        pb = self._prof(owner)
        ctx = {"pb": pb, "level": level, "attack": attack, "dc": dc, "variant": variant or None}
        if char and cls:
            mod = char.mod(SS.CLASS_ABILITY.get(cls, "wis"))
            ctx.update(owner_level=char.class_level(cls), int=char.mod("int"))
            ctx["attack"] = ctx["attack"] if ctx["attack"] is not None else pb + mod
            ctx["dc"] = ctx["dc"] if ctx["dc"] is not None else 8 + pb + mod
            ctx.update(self._subd_summon_ctx(char, cls))        # Bestial Fury, Draconic Essence, Improved Defender (subfeats_d.py)
            if cls == "Artificer" and (char.class_entry("Artificer") or {}).get("subclass") == "Reanimator":
                ctx["burst"] = "4d4" if char.class_level("Artificer") >= 9 else "2d4"      # Improved Reanimation: the companion's Death Burst
        return {k: v for k, v in ctx.items() if v is not None}

    def _companion_owner(self, m: dict) -> Tuple[Optional[dict], Optional[dict]]:
        """A class companion added from the library (Steel Defender, Beast of the Land, Wildfire Spirit): the hero it
        belongs to, the one in the battle with the most levels in that class. (None, None) for an ordinary monster."""
        cls = SS.owner_class(m)
        if not cls:
            return None, None
        heroes = [(self._sheet(c).class_level(cls), c) for c in self.b["combatants"] if self._sheet(c) and self._sheet(c).class_level(cls) > 0]
        if not heroes:
            raise ServiceError(f"{m['name']} belongs to {'an' if cls[0] in 'AEIOU' else 'a'} {cls}: add the {cls} to the battle first.")
        owner = max(heroes, key=lambda x: x[0])[1]
        return owner, self._summoner_ctx(owner, cls=cls)

    def _add_summons(self, att: dict, mid: str, count: int, name: Optional[str], level: int, variant: Optional[str], ac_base: Optional[int],
                     conc: Optional[int], ctx: Optional[dict] = None, spell: Optional[str] = None) -> list:
        m = bestiary.get(mid)
        base = name or m["name"]
        made = []
        for _ in range(count):
            hp = CR.spirit_hp(m["hp_formula"], variant or "", level) if variant is not None or "spell level" in m["hp_formula"] else m["hp"]
            hp = hp or SS.hp(m, ctx or {}) or 1                         # Animated Object: its hit points are only in the formula
            if spell and CR.norm(spell) in X.SPELL_HP:              # Homunculus Servant: 5 + 5 per spell level
                base_hp, per_hp = X.SPELL_HP[CR.norm(spell)]
                hp = base_hp + per_hp * level
            ac = (ac_base + level) if ac_base else m["ac"]
            if ac_base:                                             # Celestial Spirit: "+ 2 (Defender only)"; a Brute, a Tree, an Ankylosaur
                ac += X.SPIRIT_AC_BONUS.get(variant or "", 0)
            label = self._label(base, count > 1)
            c = self._new("enemy", label, hp, hp, ac, ability_mod(m, "dex"), monster=mid, xp=0, span=SPANS.get(m.get("size"), 1),
                          faction=self._side(att), summoned_by=att["id"], summon_conc=conc, summon_spell=spell,
                          tiny=(m.get("size") or "").startswith("Tiny"))
            if ctx and SS.needs_summoner(m):
                c["summon"] = dict(ctx, variant=variant or None) if variant else dict(ctx)
                if spell and CR.norm(spell) in X.SPELL_HP:
                    c["summon"]["spell"] = CR.norm(spell)               # (its Force Strike is the spell's: 1d6 + the spell's level)
            self._add(c, self.b["combatants"].index(att) + 1)           # right after the caster, on its initiative
            where = getattr(self, "_summon_point", None) or att.get("pos")
            if where:
                spot = self._free_near(c, *where)
                if spot:
                    c["pos"] = spot
            made.append(c)
        return made

    def _summon(self, att: dict, sp: dict, level: int, choice: Optional[str], tgt: Optional[dict], attack: Optional[int] = None,
                dc: Optional[int] = None) -> str:
        key = CR.norm(sp["name"])
        caster = att["name"]
        conc = att["id"] if sp.get("concentration") else None
        ctx = self._summoner_ctx(att, level=level, attack=attack, dc=dc)
        if key == "simulacrum":                                        # a copy of the target with half its hit points
            if tgt is None:
                return f"{caster} casts Simulacrum"
            half = max(1, tgt["max_hp"] // 2)
            c = self._new("enemy", self._label(f"{tgt['name']} (simulacrum)", False), half, half, tgt["ac"], tgt["init_bonus"], monster=tgt.get("monster"),
                          xp=0, span=tgt.get("span") or 1, faction=self._side(att), summoned_by=att["id"])
            self._add(c, self.b["combatants"].index(att) + 1)
            if att.get("pos"):
                c["pos"] = self._free_near(c, *att["pos"])
            made = [c]
        else:
            if key in ONLY_ONE:                                        # a new familiar or steed replaces the old one
                for old in [o for o in self.b["combatants"] if o.get("summoned_by") == att["id"] and CR.norm(o.get("summon_spell") or "") == key]:
                    self._vfx_unsummon(old)
                    self.remove(old["id"])
            opts = self._summon_options(key, level)
            pick = next((o for o in opts if o["value"] == choice), opts[0] if opts else None)
            own = next((o for o in self.b["combatants"] if key == "battle familiar" and o.get("summoned_by") == att["id"]
                        and CR.norm(o.get("summon_spell") or "") == "find familiar"), None)
            if own is not None:                                        # an existing familiar is empowered instead (its hit points and type stay)
                return self._empower_familiar(att, sp, own, level, pick, ctx)
            if key in X.SPIRITS:
                mid, _variants, ac_base = X.SPIRITS[key]
                name = f"{bestiary.get(mid)['name']}" + (f" ({pick['variant']})" if pick else "")
                made = self._add_summons(att, mid, 1, name, level, pick["variant"] if pick else "", ac_base, conc, ctx, sp["name"])
            elif pick:
                made = self._add_summons(att, pick["monster"], pick["count"], None, level, None, None, conc, ctx, sp["name"])
            else:                                                      # a single fixed creature
                mid, n, _l = X.CHOICES[key][0]
                made = self._add_summons(att, mid, n, None, level, None, None, conc, ctx, sp["name"])
        self._class_summoned(att, sp, made)                            # Durable Summons, Undead Thralls (classfeats.py)
        self._tome_summoned(att, sp, made)                             # a Planecaller's Codex: advantage on its attacks (spellitems.py)
        small = key in ONLY_ONE or key == "flock of familiars"         # a familiar, a steed: a little puff, no circle
        for c in made:
            kind = "familiar" if small else str((bestiary.get(c.get("monster")) or {}).get("type") or "").lower()
            self._vfx("summon", id=c["id"], type=kind, src=self._magic_source(att, sp), tier=CR.vfx_tier(level))
        names = ", ".join(c["name"] for c in made)
        line = f"{caster} summons {names}" + (" (until concentration ends)" if conc else "")
        self._event(f"{caster}: {sp['name']} → {names}")
        self._commit()
        return line

    def _empower_familiar(self, att: dict, sp: dict, fam: dict, level: int, pick: Optional[dict], ctx: dict) -> str:
        """Battle Familiar cast while a Find Familiar familiar is there: no new creature - the familiar takes the Battle Familiar's game
        statistics, keeps its own hit points and gains temporary hit points equal to the stat block's; when they are gone (or the spell
        ends) it reverts."""
        mid = X.SPIRITS["battle familiar"][0]
        variant = pick["variant"] if pick else "Brute"
        hp = CR.spirit_hp(bestiary.get(mid)["hp_formula"], variant, level)
        fam["empowered"] = {"monster": fam.get("monster"), "ac": fam.get("ac"), "summon": fam.get("summon")}
        fam.update(monster=mid, ac=11 + level + X.SPIRIT_AC_BONUS.get(variant, 0), summon=dict(ctx, variant=variant))
        self._give_temp(fam, hp)
        self._effect_on(fam, sp["name"], [], None, None, None, CR.duration_rounds(sp.get("duration", "")), att["name"],
                        {"empowered_familiar": True, "temp_gone": True}, None, att["id"])
        line = f"{att['name']} casts {sp['name']}: {fam['name']} is empowered ({variant}, {hp} temporary hit points)"
        self._event(f"{att['name']}: {sp['name']} → {fam['name']}")
        return line

    # ---- tokens of conjured things: on the map, no turn of their own, the caster's spell action works through them
    def _conjure_token(self, att: dict, sp: dict, tdef: dict, R: dict, targets: list, conc: Optional[int]) -> dict:
        """Spiritual Weapon, Bigby's Hand...: a token where the spell was aimed, else next to its first target, else by the caster."""
        from .modifiers import TYPES
        hp = self._max_hp(att) if tdef.get("hp") == "caster" else tdef.get("hp")
        tdef = dict(tdef, name=CR.shown(tdef["name"]))           # 'Arcane Hand' when the SRD names it so
        c = self._new("enemy", self._label(f"{tdef['name']} ({att['name']})", False), hp or 1, hp or 1, tdef.get("ac", 10), 0, xp=0,
                      span=tdef.get("span", 1), faction=self._side(att), summoned_by=att["id"],
                      summon_conc=conc, summon_spell=sp["name"], tiny=bool(tdef.get("tiny")),
                      conjured={"spell": sp["name"], "owner": att["id"], "move": tdef.get("move", 0), "sa": None, "bite": tdef.get("bite"),
                             "attack": R.get("attack_bonus"), "rounds": CR.duration_rounds(sp.get("duration", "")),
                             "hittable": bool(tdef.get("ac"))})            # Bigby's Hand, an Unseen Servant: AC and hit points
        self._add(c, self.b["combatants"].index(att) + 1)
        if hp is None:                                         # a force or a spirit: nothing can hurt it or aim at it
            self._effect_on(c, tdef["name"], [], None, None, None, None, att["name"], {"untargetable": True, "immune": list(TYPES)}, None, att["id"])
        where = [int(R["point"][0]), int(R["point"][1])] if R.get("point") else \
            (targets[0]["pos"] if targets and targets[0] is not att and targets[0].get("pos") else att.get("pos"))
        if where:
            c["pos"] = self._free_near(c, *where)
        self._vfx("summon", id=c["id"], type="conjured", src=self._magic_source(att, sp), tier=CR.vfx_tier(R.get("slot_level") or sp["level"]))
        return c

    def _vfx_unsummon(self, c: dict) -> None:
        """A summoned creature or conjured thing about to leave the map: the screens shrink it into a puff."""
        if c.get("pos"):
            self._vfx("unsummon", id=c["id"], at=list(c["pos"]), span=max(1, int(c.get("span") or 1)))

    def _move_token(self, tok: dict, point) -> None:
        feet = tok["conjured"].get("move", 0)
        x, y = int(point[0]), int(point[1])
        if not feet:
            raise ServiceError(f"{tok['name']} can't move.")
        if tok.get("pos") and max(abs(x - tok["pos"][0]), abs(y - tok["pos"][1])) * 5 > feet:
            raise ServiceError(f"{tok['name']} moves up to {feet} ft.")
        if not self._tile_ok(tok, x, y):
            raise ServiceError("That tile is taken or off the map.")
        self._vfx("blink", id=tok["id"], at=tok.get("pos"), to=[x, y])
        tok["pos"] = [x, y]

    def _token_reach(self, tok: dict, tgt: dict) -> None:
        """The token strikes a creature within 5 ft of it; it first moves next to the target if its move gets it there."""
        if not tok.get("pos") or not tgt.get("pos") or self._dist(tok, tgt) <= 5:
            return
        feet = tok["conjured"].get("move", 0)
        x0, y0, x1, y1 = G.box(tgt["pos"], tgt.get("span") or 1)          # any tile touching the target, big ones too
        ring = [(x, y) for x in range(x0 - 1, x1 + 2) for y in range(y0 - 1, y1 + 2) if not (x0 <= x <= x1 and y0 <= y <= y1)]
        near = lambda t: max(abs(t[0] - tok["pos"][0]), abs(t[1] - tok["pos"][1])) * 5
        spots = sorted((t for t in ring if near(t) <= feet and self._tile_ok(tok, *t)), key=near) if feet else []
        if spots:
            self._vfx("blink", id=tok["id"], at=tok["pos"], to=list(spots[0]))
            tok["pos"], tok["at"] = list(spots[0]), None
            return
        raise ServiceError(f"{tgt['name']} is out of {tok['name']}'s reach ({self._dist(tok, tgt)} ft; it moves up to {feet} ft)")

    def _prune_tokens(self) -> None:
        """Tokens whose spell is over: their caster's spell action ran out, or their time did."""
        for t in [c for c in self.b["combatants"] if c.get("conjured")]:
            owner = self._find_or_none(t["conjured"]["owner"])
            sa = t["conjured"].get("sa")
            gone = owner is None or (sa is not None and not any(a["id"] == sa for a in owner.get("spell_actions") or [])) \
                or (t["conjured"].get("rounds") is not None and t["conjured"]["rounds"] <= 0)
            if gone:
                self._vfx_unsummon(t)
                self.b["combatants"].remove(t)
                self._say(f"{t['name']} fades away")

    def _token_turn_start(self, c: dict) -> None:
        """The caster's turn starts: a Faithful Hound bites a foe beside it."""
        for t in [o for o in self.b["combatants"] if (o.get("conjured") or {}).get("owner") == c["id"] and o["conjured"].get("bite") and o.get("pos")]:
            foes = [o for o in self.b["combatants"] if o.get("pos") and self._hostile(c, o) and self._alive(o) and not o.get("conjured")
                    and self._dist(t, o) <= 5]
            if foes:
                atk = {"bonus": t["conjured"].get("attack") or 5, "n": 1, "melee": True, "spell": True, "magical": True, "parts": t["conjured"]["bite"]}
                self._run_r(self._strike(c, t["name"], [foes[0]["id"]], mode="attack", atk=atk, spell=True))
