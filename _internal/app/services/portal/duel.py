"""The duels on the player's page (services/duel): the lobbies - any player opens one, joins one, or watches any of
them - who joined the one they look at and as what, what a class and level may pick; and its fight, which the page
shows with the same map, action bar and reaction questions as a battle (portal/api.py, worked out on that duel's
battle). A player plays only their own fighter and what it summoned; everyone else watches. Battle actions the page
sends with "duel" act on the lobby it names."""
from typing import Optional

from ...core.i18n import i18n
from ...core.runtime import rt
from ...rules import quickgen
from ...rules.character import Character
from ...rules.data import rules
from ..battle import ACTIVE
from ..battle.icons import for_spell
from ..common import ServiceError
from ..duel import fighters as F
from . import api

PLAY = ("do", "preview", "reaction_mode", "react", "end_turn", "move", "death_save", "toggle")   # battle actions, on the duel


def lobby(uid: int) -> Optional[dict]:
    """The Duel tab: every lobby, the one this player looks at, the one they joined. None while duel mode is closed."""
    d = rt().duel
    if not d.open:
        return None
    t = api._t(uid)
    with d.lock:
        joined = d.room_of(uid)
        room = d.watched(uid)
        rooms = [{"id": s["id"], "name": s["name"], "host_name": s["host_name"], "host_me": s["host"] == uid, "n": s["n"],
                  "running": s["running"], "status": s["status"], "mine": joined is not None and joined.id == s["id"]}
                 for s in d.rooms_list()]
        v = room.view() if room is not None else None
        mine = room.picks.get(uid) if room is not None else None
    return {"open": True, "rooms": rooms, "joined": {"id": joined.id, "name": joined.name} if joined else None,
            "room": None if v is None else {
                "id": v["id"], "name": v["name"], "host_name": v["host_name"], "host_me": v["host"] == uid,
                "dm_host": v["host"] is None, "running": v["running"], "status": v["status"], "round": v["round"],
                "winner": v["winner"], "fighting": room.fighter_of(uid) is not None,
                "mine": {k: x for k, x in mine.items() if k != "player"} if mine else None,
                "rows": [{"player": r["player"], "me": r["uid"] == uid, "host": r["uid"] == v["host"],
                          "pick": dict(r["pick"], label=t(r["pick"].get("class") or "")),
                          "name": r["name"], "hp": r["hp"], "max_hp": r["max_hp"], "out": r["out"]} for r in v["rows"]]},
            "copies": _copies(uid), "classes": [[c, t(c)] for c in F.classes()], "levels": F.LEVELS, "crs": F.crs()}


def _copies(uid: int) -> list:
    """The player's own characters, any of which they may fight as a copy of."""
    out = []
    for n in rt().characters.characters_of(uid):
        c = Character.peek(n)                          # (only read)
        if c is not None:
            out.append({"name": n, "summary": quickgen.summary(c), "hp": c.current_hp, "max_hp": c.max_hp})
    return out


def battle(uid: int) -> Optional[dict]:
    """The fight of the lobby this player looks at, as they see it (the shape of api.battle), while it is on."""
    d = rt().duel
    room = d.watched(uid) if d.open else None
    if room is None or not room.running:
        return None
    with d.scope(room):
        lang = i18n.player_language(uid)
        board = api._board(lang, duel=True)
        t = api._t(uid)
        mine = room.mine(uid)
        out = [dict(c, mine=c["id"] in mine, character=None) for c in board["combatants"]]
        pend = board["pending"]
        if pend is not None:
            pend = rt().battle.pending()
            if pend:
                pend = dict(pend, text=t(pend["text"]), mine=pend.get("reactor") in mine,
                            options=[dict(o, label=t(o["label"]), **{k: t(o[k]) for k in ("group", "choice") if o.get(k)}) for o in pend["options"]])
        turn = board["turn"]
        cid = turn if turn in mine else room.fighter_of(uid)
        actions = api._actions_for(uid, cid) if cid is not None and any(c["id"] == cid for c in out) else None
        return dict(board, combatants=out, my_turn=turn in mine, pending=pend, actions=actions, duel=True, room=room.id,
                    fighter=room.fighter_of(uid),
                    settings=dict(board["settings"], move_tokens=True, battle_actions=True))


def spells(uid: int, a: dict) -> dict:
    """What a premade of this class and level may pick, for the page's spell picker."""
    cls = str(a.get("class") or "")
    level = int(a["level"]) if str(a.get("level") or "").isdigit() else 0
    if cls not in F.classes() or level not in F.LEVELS:
        raise ServiceError("Pick a class and a level.")
    t = api._t(uid)
    ch = F.spell_choices(cls, level)
    c = ch["caster"]

    def row(n):
        s = rules.spell(n)
        return {"name": n, "label": t(n), "level": s["level"], "school": t(s["school"]), "time": t(s["casting_time"]),
                "range": s["range"], "conc": s["concentration"], "ritual": s["ritual"], "icon": for_spell(n),
                "text": t(s["text"])[:600]}
    return {"summary": ch["summary"], "caster": None if not c else {
        "cantrips": c["cantrips"], "spells": c["spells"], "prepares": c["prepares"], "max_level": c["max_level"],
        "always": [t(x) for x in c["always"]], "picked": c["picked"],
        "options": [row(n) for n in c["cantrip_options"] + c["spell_options"] if rules.spell(n)]}}


def act(uid: int, action: str, a: dict):
    d = rt().duel
    rid = a.get("room")
    if action == "duel_spells":
        return spells(uid, a)
    if action == "duel_monsters":                 # the monsters of a challenge rating, to pick one
        t = api._t(uid)
        return {"monsters": [dict(m, label=t(m["name"]), kind=t(m["type"])) for m in F.monsters(str(a.get("cr") or ""))]}
    if action == "duel_create":                   # a lobby of your own (you are its host)
        d.create(uid, str(a.get("name") or ""))
        return ""
    if action == "duel_watch":                    # look at another lobby
        d.watch(uid, rid)
        return ""
    if action == "duel_join":
        d.join(uid, rid, a.get("pick"))
        return ""
    if action == "duel_leave":
        d.leave(uid)
        return ""
    if action in ("duel_start", "duel_stop", "duel_close"):     # the host's (the service checks it)
        return {"duel_start": d.start, "duel_stop": d.stop, "duel_close": d.close}[action](rid, uid) or ""
    if action not in PLAY:
        raise ServiceError(f"Unknown action '{action}'.")
    room = d.room(rid) if rid is not None else d.watched(uid)
    if room is None or not room.running:
        raise ServiceError("The duel hasn't started.")
    mine = room.mine(uid)
    if not mine:
        raise ServiceError("You are watching this duel.")
    with d.scope(room):
        b = rt().battle
        cur = b.current() if b.b["status"] == ACTIVE else None
        asked = int(a["cid"]) if str(a.get("cid") or "").isdigit() else None
        cid = asked if asked in mine else cur["id"] if cur and cur["id"] in mine else room.fighter_of(uid)
        me = next((c for c in b.view()["combatants"] if c["id"] == cid), None)
        if me is None:
            raise ServiceError("Your fighter isn't in the duel any more.")
        if action == "end_turn":
            if not cur or cur["id"] not in mine:
                raise ServiceError("It isn't your turn.")
            b.next_turn()
            return ""
        if action == "react":
            p = b.pending()
            if not p or p.get("reactor") not in mine or int(a.get("rid") or 0) != p["rid"]:
                raise ServiceError("Nothing is waiting for your answer.")
            return b.react(p["rid"], a.get("choice") or None)
        if action == "death_save":
            if not me.get("character"):
                raise ServiceError("Only a hero rolls death saves.")
            return b.roll_death_save(me["character"]) or ""
        if action == "toggle":
            if not me.get("character"):
                raise ServiceError("Only a hero has those.")
            value = a.get("value")
            b.chars.set_toggle(me["character"], str(a.get("key")), value if isinstance(value, (bool, str)) else bool(value))
            return ""
        if action == "move":
            if b.b["status"] == ACTIVE and (not cur or cur["id"] != cid):
                raise ServiceError("You can move your token on your turn.")
            if me.get("pos"):
                return b.walk(cid, int(a["x"]), int(a["y"]))
            b.place(cid, int(a["x"]), int(a["y"]))
            return ""
        targets = [int(x) for x in a.get("targets") or [] if str(x).lstrip("-").isdigit()]
        point = a.get("point")
        point = [float(point[0]), float(point[1])] if isinstance(point, list) and len(point) == 2 else None
        item = str(a.get("item") or "")
        if action == "reaction_mode":
            b.set_reaction_mode(cid, str(a.get("family")), str(a.get("mode")))
            return ""
        if action == "preview":
            kind, _, arg = item.partition(":")
            if kind == "spell":
                out = b.cast_check(cid, arg, a.get("slot") or None, targets or None, point)
                info = b.spell_info(arg, int(a["slot"]) if str(a.get("slot") or "").isdigit() else None)
                out["options"] = info.get("options") or []
                out["why"] = api._t(uid)(out["why"]) if out.get("why") else None
                return out
            if kind == "move" and point:
                pv = b.path_preview(cid, int(point[0]), int(point[1]))
                pv["why"] = api._t(uid)(pv["why"]) if pv.get("why") else None
                return pv
            return {"ok": True}
        adv = a.get("adv") if a.get("adv") in ("advantage", "disadvantage") else None
        return b.act(cid, item, targets or None, point, a.get("slot") or None, a.get("dtype") or None,
                     a.get("option") or None, adv, bool(a.get("ritual")), a.get("metamagic") or None)
