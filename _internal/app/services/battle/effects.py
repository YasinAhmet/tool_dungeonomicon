"""Effects on creatures: putting them on and taking them off (conditions they carry come and go with them)."""
from typing import Optional


class EffectsMixin:
    # ---- effects on creatures
    def _effect_on(self, tgt: dict, name: str, conds, ab, dc, repeat, rounds, source: str, mods=None, conc_by=None, source_id=None,
                   until=None, ends_on=None):
        """Put an effect on a creature: conditions (unless it is immune), changed numbers (`mods`), a repeated save
        (`repeat` 'start'/'end' with `ab`/`dc`), a length in rounds, or `until` {'start'|'end': creature id} - the start
        or end of that creature's next turn. `conc_by` ties it to a caster's concentration."""
        if conc_by is not None:                                 # the spell already ended (its own damage broke the caster's focus)
            caster = self._find_or_none(conc_by)
            if caster is not None and not caster.get("concentrating"):
                return []
        blocked = {c for _e, cs in self._fxs(tgt, "immune_cond") for c in cs} | self._defenses(tgt).get("immune_cond", set())
        if "Charmed" in conds and "devotion" in self._oath_auras(tgt):      # Aura of Devotion
            blocked = blocked | {"Charmed"}
        if "Frightened" in conds and "courage" in self._oath_auras(tgt):    # Aura of Courage
            blocked = blocked | {"Frightened"}
        conds = [c for c in conds if c not in blocked]
        for cond in conds:
            self._cond(tgt, cond, True, keep_conc=bool((mods or {}).get("keeps_conc")))
        if conc_by is not None:                                 # the condition just knocked out the caster's own spell
            caster = self._find_or_none(conc_by)                # (a caster in its own Stinking Cloud): it ends with it
            if caster is not None and not caster.get("concentrating"):
                kept = {x for o in tgt.get("effects") or [] for x in o["conditions"]}
                for cond in conds:
                    if cond not in kept:
                        self._cond(tgt, cond, False)
                return []
        mods = dict(mods or {})
        if mods.get("aura_ft"):
            self.b["aura_fx"] = True                            # effect lookups start looking at allies' auras
        if ends_on:
            mods["ends_on"] = list(ends_on)
        if repeat or rounds or mods or conc_by or until:
            same = [e for e in tgt.get("effects") or [] if e["name"] == name and e.get("source_id") == source_id and source_id is not None]
            for e in same:                                    # the same effect from the same source doesn't stack: the new one replaces it
                tgt["effects"].remove(e)
            tgt.setdefault("effects", []).append({"name": name, "conditions": list(conds), "ability": ab, "dc": dc, "repeat": repeat,
                                                  "rounds": rounds, "source": source, "mods": mods, "conc_by": conc_by,
                                                  "source_id": source_id, "until": until})
            sp = mods.get("speed")
            t = tgt.get("turn")
            if isinstance(sp, int) and not isinstance(sp, bool) and sp > 0 and t and self.b.get("turn") == tgt["id"] and not same:
                t["move"] = int(t.get("move", 0)) + sp          # Longstrider, Ashardalon's Stride cast mid-turn: the rest of this turn too
                t["speed"] = int(t.get("speed", 0)) + sp
            sm = mods.get("speed_mult")
            if isinstance(sm, (int, float)) and not isinstance(sm, bool) and sm < 1 and t and self.b.get("turn") == tgt["id"] and not same:
                t["move"] = int(int(t.get("move", 0)) * sm)     # Slow Time failed as its turn starts (or on the way in): the rest of this turn too
                t["speed"] = int(int(t.get("speed", 0)) * sm)
        return conds

    def _dot_on(self, tgt: dict, name: str, dot: dict, ab, dc, rounds, source: str, conc_by=None, source_id=None):
        """Damage over time: joined to the effect the same spell already put on the creature (Phantasmal Killer's fear,
        Ensnaring Strike's vines) so one save ends both and the condition isn't left behind - else an effect of its own."""
        mine = next((e for e in tgt.get("effects") or [] if e["name"] == name and e.get("source_id") == source_id and source_id is not None), None)
        if mine is None:
            return self._effect_on(tgt, name, [], ab, dc, None, rounds, source, {"dot": dot}, conc_by, source_id)
        mine["mods"] = dict(mine.get("mods") or {}, dot=dot)
        if ab:
            mine["ability"], mine["dc"] = ab, dc
        return []

    def _loose_concentration(self):
        """Nobody at 0 hit points holds a concentration: a caster its own Delayed Blast Fireball dropped while it was casting
        the next spell started that one's concentration after its fall."""
        for c in self.b["combatants"]:
            if c.get("concentrating") and self._hp_of(c) <= 0:
                self._drop_conc(c, "dropped to 0 hit points")

    def _loose_grapples(self):
        """A grapple ends when its grappler is gone, down or incapacitated, or the held creature is out of its reach (PHB)."""
        from . import conditions as K
        for c in self.b["combatants"]:
            for e in [e for e in c.get("effects") or [] if (e.get("mods") or {}).get("grappler") is not None]:
                g = self._find_or_none(e["mods"]["grappler"])
                if g is None or not g.get("pos") and c.get("pos"):
                    why = "its grappler is gone"
                elif self._hp_of(g) <= 0:
                    why = f"{g['name']} is down"
                elif K.incapacitated(self._conds(g)):
                    why = f"{g['name']} is incapacitated"
                elif c.get("pos") and g.get("pos") and self._dist(g, c) > max(5, self._reach(g)):
                    why = "out of reach"
                else:
                    why = None
                if why:
                    self._effect_off(c, e, why)
            for e in [e for e in c.get("effects") or [] if (e.get("mods") or {}).get("swallowed_by") is not None]:
                g = self._find_or_none(e["mods"]["swallowed_by"])
                if g is None or self._hp_of(g) <= 0:               # out of the corpse, prone (MM)
                    self._effect_off(c, e, "its swallower is down")
                    self._cond(c, "Prone", True)

    def _effect_tail(self, tgt: dict, name: str, sv: dict, att: Optional[dict]):
        """What a save's `then` (a second effect that starts when the first ends: Sir Godfrey's glare paralyzes, then frightens) and
        `ends_on_by` (it ends when the one who cast it deals damage to it) ask of the effect just put on `tgt`."""
        eff = next((e for e in reversed(tgt.get("effects") or []) if e["name"] == name), None)
        if eff is None or not (sv.get("then") or sv.get("ends_on_by")):
            return
        if sv.get("then"):
            eff["mods"]["then"] = dict(sv["then"], name=name + " (" + sv["then"]["name"].lower() + ")", ab=sv["ab"], dc=int(sv["dc"]))
        if sv.get("ends_on_by") and att is not None:
            eff["mods"]["ends_on_by"] = att["id"]

    def _effect_off(self, tgt: dict, eff: dict, why: str):
        if eff in tgt.get("effects", []):
            tgt["effects"].remove(eff)
        kept = {cond for o in tgt.get("effects", []) for cond in o["conditions"]}
        for cond in eff["conditions"]:
            if cond not in kept:
                self._cond(tgt, cond, False)
        self._say(f"{tgt['name']}: {eff['name']} ends ({why})")
        given = int((eff.get("mods") or {}).get("exh_given") or 0)
        if given:                                               # Waves of Exhaustion: the levels it gave go with the spell
            char = self._sheet(tgt)
            if char:
                char.d["exhaustion"] = max(0, int(char.d.get("exhaustion") or 0) - given)
                char.save()
            else:
                tgt["exhaustion"] = max(0, int(tgt.get("exhaustion") or 0) - given)
        if (eff.get("mods") or {}).get("empowered_familiar") and tgt.get("empowered"):     # Battle Familiar ends: back to its own form
            old = tgt.pop("empowered")
            tgt.update(monster=old["monster"], ac=old["ac"])
            if old.get("summon") is None:
                tgt.pop("summon", None)
            else:
                tgt["summon"] = old["summon"]
            tgt["temp_hp"] = 0
        if (eff.get("mods") or {}).get("ends_actions"):        # Sylune's Viper, Elminster's Effulgent Spheres: what the spell let its caster do goes too
            name = eff["mods"]["ends_actions"]
            tgt["spell_actions"] = [a for a in tgt.get("spell_actions") or [] if a.get("spell") != name]
        if (eff.get("mods") or {}).get("ends_form") and (tgt.get("form") or {}).get("name") == eff["mods"]["ends_form"]:
            self._say(f"{tgt['name']} returns to its own shape ({tgt.pop('form')['name']} form ends)")    # a Wabbajack's rat: its minute is up
        if (eff.get("mods") or {}).get("temp_ends"):            # Tomb of Levistus, Heroism: its temporary hit points go with it
            if tgt["kind"] == "pc":
                self.chars.set_temp_hp(tgt["character"], 0)
            else:
                tgt["temp_hp"] = 0
        ends = (eff.get("mods") or {}).get("ends_spell")
        if ends and (tgt.get("concentrating") or {}).get("spell") == ends:      # Primordial Ward's immunity runs out: so does the spell
            self._drop_conc(tgt, f"{ends} runs its course")
        g = (eff.get("mods") or {}).get("grappler")
        if g is not None:                                       # what lasts "until this grapple ends" ends with it
            for e2 in [e for e in tgt.get("effects") or [] if (e.get("mods") or {}).get("with_grapple") == g]:
                self._effect_off(tgt, e2, "the grapple ended")
        if eff["name"].startswith("Haste") and (eff.get("mods") or {}).get("extra_action") and why not in ("dispelled", "cured"):
            self._effect_on(tgt, "Lethargic (Haste ended)", ["Incapacitated"], None, None, None, None, eff.get("source", ""),
                            {"speed_set": 0, "keeps_conc": True}, None, None, until={"end": tgt["id"], "skip": 1 if self.b.get("turn") == tgt["id"] else 0})
        then = (eff.get("mods") or {}).get("then")
        if then and why not in ("dispelled", "cured") and self._hp_of(tgt) > 0:     # "When the paralysis ends, the target is frightened of the knight"
            self._effect_on(tgt, then["name"], then["conds"], then.get("ab"), then.get("dc"), then.get("repeat"), then.get("rounds"),
                            eff.get("source", ""), None, None, eff.get("source_id"))
