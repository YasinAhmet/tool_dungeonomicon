"""The table as the Discord side sees it: servers, the selected server's channels, players and their characters."""
import time
from typing import List

from ..core.runtime import rt
from ..rules.character import Character
from ..rules.data import rules
from .characters.view import summary
from .players import is_manual


def bot_state() -> dict:
    bm = rt().bot_manager
    return {"status": bm.status, "voice_text": bm.voice_text, "voice_connected": bm.voice_connected, "ready": bm.is_ready,
            "members_enabled": bm.members_enabled, "token_set": bool(rt().settings.get("token"))}


def guilds() -> List[dict]:
    """[{id, name, icon_url}] of the servers the bot is in (empty while it is offline)."""
    bm = rt().bot_manager
    icons = bm.guild_icon_urls()
    return [{"id": i, "name": n, "icon_url": icons.get(i)} for n, i in bm.list_guilds()]


def server() -> dict:
    """The selected server's channels and options (None in the void or with no server chosen)."""
    gid, bm = rt().guild_id, rt().bot_manager
    if not gid:
        return None
    voice, text = bm.list_channels(gid)
    return {"id": gid, "settings": rt().server_settings(), "voice": [{"id": i, "name": n} for n, i in voice],
            "text": [{"id": i, "name": f"#{n}"} for n, i in text],
            "threads": [{"id": i, "name": n} for n, i in bm.list_threads(gid)]}


def players() -> dict:
    """{'players': [{id, name, characters, active, manual}], 'members': [{id, name}] (server members with no record yet),
    'characters': roster lines with owners, 'unassigned': character names nobody owns}."""
    r = rt()
    gid = r.guild_id
    members = r.bot_manager.list_members(gid) if gid else []
    stored = r.players.all()
    chars = [c for c in (Character.peek(n) for n in Character.list_characters()) if c]    # only read: the kept sheets
    existing = {c.name for c in chars}
    owners = {c: uid for uid, p in stored.items() for c in p["characters"] if c in existing}
    names = {uid: p["name"] for uid, p in stored.items()}
    names.update({uid: n for n, uid in members})
    out = [{"id": uid, "name": n, "characters": [c for c in stored.get(uid, {"characters": []})["characters"] if c in existing],
            "active": stored.get(uid, {}).get("active"), "manual": is_manual(uid)}
           for uid, n in sorted(names.items(), key=lambda kv: kv[1].lower())]
    if members:                                   # someone with no character who isn't in this server has nothing to show
        present = {uid for _n, uid in members}    # (a player added by hand is in no server: always kept)
        out = [p for p in out if p["characters"] or p["id"] in present or p["manual"]]
    return {"players": out, "members": [{"id": i, "name": n} for n, i in members if i not in stored],
            "characters": [summary(c, owners.get(c.name)) for c in sorted(chars, key=lambda c: c.name.lower())],
            "unassigned": r.players.unassigned(sorted(existing))}


def sources() -> List[dict]:
    """Every sourcebook with whether it is switched on."""
    on = set(rules.active_sources)
    return [{"id": k, "name": v["name"], "group": v.get("group", "other"), "adventure": bool(v.get("adventure")),
             "homebrew": bool(v.get("homebrew")), "on": k in on} for k, v in rules.sources.items()]


# ---------------------------------------------------------------------------- the Bot window and the server strip
SERVER_COLOURS = ("#5865f2", "#3ba55d", "#eb459e", "#d98a14", "#ed4245", "#1abc9c", "#9b59b6", "#e67e22")
LOG_KINDS = (("player_rolls", "Player rolls",
              "Every roll of a character: from its sheet, /roll, initiative and in battle (attacks, damage, saves, healing)."),
             ("npc_rolls", "NPC rolls", "Every roll made by a monster or other non-player creature in battle."),
             ("xp", "XP", "Experience gained by the characters."),
             ("battle", "Battle log", "The battle log: turns, hits, damage and the like."))
_apps_seen = {"at": 0.0, "names": {}}            # pid -> label of the running apps, read at most every 15 s


def initials(name: str) -> str:
    return ("".join(w[0] for w in str(name).split()[:2]) or "?").upper()


def bot_view() -> dict:
    """bot_state() plus what the status widgets show: running (online or connecting) and whether to warn that the
    Server Members Intent is off."""
    b = bot_state()
    return {**b, "running": b["status"] in ("online", "connecting"),
            "members_warning": b["ready"] and not b["members_enabled"]}


def server_strip() -> dict:
    """The toolbar's server picker: {'void': bool, 'guilds': [{id, name, icon_url, initials, colour, selected}]}."""
    r = rt()
    sel = r.guild_id
    return {"void": r.void, "guilds": [{**g, "initials": initials(g["name"]), "colour": SERVER_COLOURS[g["id"] % 8],
                                        "selected": g["id"] == sel} for g in guilds()]}


def server_view() -> dict:
    """server() plus the server's name ('' when the bot is offline), its log kind ticks and whether the channel
    lists are live (the bot online). None in the void or with no server chosen."""
    s = server()
    if s is None:
        return None
    kinds = s["settings"].get("log_kinds") or {}
    return {**s, "name": next((g["name"] for g in guilds() if g["id"] == s["id"]), ""),
            "log_kinds": {k: kinds.get(k, True) is not False for k, _l, _t in LOG_KINDS},
            "live": rt().bot_manager.is_ready}


def apps() -> List[dict]:
    """[{pid, label}] of the running apps whose audio can be streamed (empty where the list isn't available)."""
    try:
        from ..bot.app_windows import list_apps
        found = list_apps()
    except Exception:                     # the list needs Windows (pywin32, psutil)
        found = []
    _apps_seen.update(at=time.monotonic(), names={str(pid): label for label, pid in found})
    return [{"pid": str(pid), "label": label} for label, pid in found]


def _app_names() -> dict:
    if time.monotonic() - _apps_seen["at"] > 15:
        apps()
    return _apps_seen["names"]


def _pids(ss: dict) -> List[str]:
    from ..core.runtime import parse_pids
    return [str(p) for p in parse_pids(ss.get("target_pids", ""))]


def audio_view() -> dict:
    """The selected server's audio streaming: stream/mute/volume/delay and [{pid, label, volume}] of the chosen apps
    (label None when that app isn't running)."""
    ss = rt().server_settings()
    pids = _pids(ss)
    names = _app_names() if pids else {}
    vols = ss.get("app_volumes") or {}
    return {"stream": bool(ss["stream_audio"]), "muted": bool(ss["muted"]), "volume": int(ss["volume"] or 0),
            "delay": int(ss["delay"] or 0), "has_channel": str(ss["channel_id"]).isdigit(),
            "apps": [{"pid": p, "label": names.get(p), "volume": int(vols.get(p, 100))} for p in pids]}


def set_stream_apps(pids) -> None:
    """Stream exactly these apps (pids) in the selected server's voice channel."""
    rt().update_server(target_pids=", ".join(str(p) for p in pids))


def remove_stream_app(pid) -> None:
    ss = rt().server_settings()
    vols = {k: v for k, v in (ss.get("app_volumes") or {}).items() if str(k) != str(pid)}
    rt().update_server(target_pids=", ".join(p for p in _pids(ss) if p != str(pid)), app_volumes=vols)


def set_app_volume(pid, volume: int) -> None:
    ss = rt().server_settings()
    rt().update_server(app_volumes={**(ss.get("app_volumes") or {}), str(pid): int(volume)})


def set_log_kind(kind: str, on: bool) -> None:
    """Whether this kind of line (LOG_KINDS) reaches the selected server's Discord log."""
    ss = rt().server_settings()
    rt().update_server(log_kinds={**(ss.get("log_kinds") or {}), kind: bool(on)})


def leave_voice() -> None:
    rt().bot_manager.leave_voice()
