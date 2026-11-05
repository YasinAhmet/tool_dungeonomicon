"""The audio manager: looping ambience (rain, a campfire, footsteps on mud…), timed events (a loop that fades in, stays
a set number of seconds and fades out: a carriage passing by, church bells) and one-shot effects (a door, an explosion,
a bell) for the table, heard on this computer's speakers, in the bot's voice channel and/or on the player page.

The sounds are CC0 recordings from freesound.org in an asset module's assets/sounds ("table-sounds", core/assets.py;
made by tools/build_sounds.py into the project's assets/sounds), listed in its sounds.json - several sound modules join. The choices live in the settings under "sound": the profiles (a named set of loops for a place, each loop
with its volume and whether it is on) and which one plays, the timed events (a loop, its seconds and volume), the
two volumes and the three outputs. app.bot.soundscape
does the mixing.
"""
import importlib
import os
from typing import Dict, List, Optional

from ..bot.volume import gain
from ..core import events
from ..core.runtime import rt

DEFAULTS = {"profiles": [], "profile": 0, "events": [], "volume": 80, "effects": 80, "speakers": True, "voice": True,
            "web": True}

_catalog: Optional[Dict[str, List[dict]]] = None
_state = {"scape": None, "speakers": None, "problem": ""}


def catalog() -> Dict[str, List[dict]]:
    """{"loops": [...], "oneshots": [...]}, each [{key, name, group, file, credit, url, path}] - the sound modules'
    sounds.json joined (the first module's sound of a key wins); 'path' is the sound's full file."""
    global _catalog
    if _catalog is None:
        from ..core import assets
        out: Dict[str, List[dict]] = {"loops": [], "oneshots": []}
        for folder, data in assets.catalogues("sounds", "sounds.json"):
            for kind in out:
                have = {s["key"] for s in out[kind]}
                for s in (data.get(kind) or []) if isinstance(data, dict) else []:
                    if isinstance(s, dict) and s.get("key") and s.get("file") and s["key"] not in have:
                        out[kind].append(dict(s, path=os.path.join(folder, *str(s["file"]).split("/"))))
                        have.add(s["key"])
        _catalog = out
    return _catalog


def forget():
    """The sound modules changed: read their catalogues again."""
    global _catalog
    _catalog = None


def _sound(kind: str, key: str) -> Optional[dict]:
    return next((s for s in catalog()[kind] if s["key"] == key), None)


def settings() -> dict:
    stored = rt().settings.get("sound")
    s = {**DEFAULTS, **(stored if isinstance(stored, dict) else {})}
    if not s["profiles"]:                              # the first time, or a list of loops from before profiles
        s["profiles"] = [{"name": "Default", "loops": s.pop("loops", None) or []}]
    s.pop("loops", None)
    s["profile"] = max(0, min(int(s["profile"] or 0), len(s["profiles"]) - 1))
    return s


def _loops(s: Optional[dict] = None) -> List[dict]:
    """The loops of the profile that plays."""
    s = s or settings()
    return s["profiles"][s["profile"]]["loops"]


def _save_loops(loops: List[dict]):
    s = settings()
    profiles = [dict(p) for p in s["profiles"]]
    profiles[s["profile"]]["loops"] = loops
    _save(profiles=profiles)


def _save(**values):
    rt().settings["sound"] = {**settings(), **values}
    rt().save_config()
    _apply()
    rt().bus.emit(events.SOUND)


# ------------------------------------------------------------------ the engine
def _scape():
    """The mixer (made on first use; None when numpy or soundfile is missing)."""
    if _state["scape"] is None and not _state["problem"]:
        try:
            from ..bot.soundscape import Soundscape
            importlib.import_module("soundfile")       # decodes the files
        except Exception as e:
            _state["problem"] = f"Sound needs numpy and soundfile ({e}). Run: py -3 -m pip install -r requirements.txt"
            rt().log(f"[sound] {_state['problem']}")
            return None
        _state["scape"] = Soundscape(rt().log)
    return _state["scape"]


def _apply():
    """Make the mixer and the outputs match the settings."""
    scape = _scape()
    if scape is None:
        return
    s = settings()
    master = gain(s["volume"])                         # percents are loudness (app.bot.volume)
    loops = {}
    for x in _loops(s):
        info = _sound("loops", x["key"])
        if info and x.get("on", True):
            loops[x["key"]] = (info["path"], master * gain(x.get("volume", 100)))
    scape.set_loops(loops)
    for x in s["events"]:                              # a volume changed while an event plays
        scape.set_event_volume(x["key"], master * gain(x.get("volume", 100)))
    rt().bot_manager.set_sound(scape, s["voice"])
    from .portal.music import music
    music.set_sound(scape, s["web"])
    speakers = _state["speakers"]
    if s["speakers"] and speakers is None:
        try:
            from ..bot.soundscape import Speakers
            _state["speakers"] = Speakers(scape.player(), rt().log)
        except Exception as e:
            rt().log(f"[sound] Could not open the speakers: {e}")
    elif not s["speakers"] and speakers is not None:
        _state["speakers"] = None
        speakers.close()


def resume():
    """At launch: play the loops that were on when the app closed."""
    _apply()


def close():
    speakers, _state["speakers"] = _state["speakers"], None
    if speakers is not None:
        speakers.close()


# ------------------------------------------------------------------ for the window
def view() -> dict:
    """What the audio manager shows: the outputs, the volumes, the profiles' names and which one plays, its loops
    [{key, name, group, volume, on}], the loops that can still be added to it, the timed events
    [{key, name, group, seconds, volume}] and the one-shots [{key, name, group}]."""
    s = settings()
    added = []
    for x in _loops(s):
        info = _sound("loops", x["key"])
        if info:
            added.append({**info, "volume": int(x.get("volume", 100)), "on": bool(x.get("on", True))})
    keys = {x["key"] for x in added}
    timed = []
    for x in s["events"]:
        info = _sound("loops", x["key"])
        if info:
            timed.append({**info, "seconds": int(x.get("seconds", 20)), "volume": int(x.get("volume", 100))})
    return {"speakers": bool(s["speakers"]), "voice": bool(s["voice"]), "web": bool(s["web"]),
            "volume": int(s["volume"]), "effects": int(s["effects"]), "loops": added, "problem": _state["problem"],
            "profiles": [p["name"] for p in s["profiles"]], "profile": s["profile"], "events": timed,
            "addable": [x for x in catalog()["loops"] if x["key"] not in keys], "oneshots": catalog()["oneshots"],
            "voice_connected": rt().bot_manager.voice_connected}


def add_loops(keys) -> None:
    """Add these loops (switched on, at full volume) after the ones already there."""
    have = _loops()
    known = {x["key"] for x in have}
    _save_loops(have + [{"key": k, "volume": 100, "on": True} for k in keys if k not in known and _sound("loops", k)])


def remove_loop(key: str) -> None:
    _save_loops([x for x in _loops() if x["key"] != key])


def _change_loop(key: str, **values):
    _save_loops([{**x, **values} if x["key"] == key else x for x in _loops()])


def set_loop_on(key: str, on: bool) -> None:
    _change_loop(key, on=bool(on))


def set_loop_volume(key: str, volume: int) -> None:
    _change_loop(key, volume=int(volume))


def set_volume(volume: int) -> None:
    """The level of every loop together (percent)."""
    _save(volume=int(volume))


def set_effects_volume(volume: int) -> None:
    _save(effects=int(volume))


def set_outputs(speakers: Optional[bool] = None, voice: Optional[bool] = None, web: Optional[bool] = None) -> None:
    """Hear the sounds on this computer's speakers, in the bot's voice channel and/or on the player page."""
    values = {k: bool(v) for k, v in (("speakers", speakers), ("voice", voice), ("web", web)) if v is not None}
    _save(**values)


def stop_loops() -> None:
    """Switch every loop off (they stay in the list)."""
    _save_loops([{**x, "on": False} for x in _loops()])


# ------------------------------------------------------------------ timed events
def add_events(keys) -> None:
    """Make these loops timed events (20 seconds at full volume to begin with)."""
    have = settings()["events"]
    known = {x["key"] for x in have}
    _save(events=have + [{"key": k, "seconds": 20, "volume": 100} for k in keys if k not in known and _sound("loops", k)])


def remove_event(key: str) -> None:
    stop_event(key)
    _save(events=[x for x in settings()["events"] if x["key"] != key])


def set_event_seconds(key: str, seconds: int) -> None:
    _save(events=[{**x, "seconds": max(2, int(seconds))} if x["key"] == key else x for x in settings()["events"]])


def set_event_volume(key: str, volume: int) -> None:
    _save(events=[{**x, "volume": int(volume)} if x["key"] == key else x for x in settings()["events"]])


def events_playing() -> Dict[str, float]:
    """{key: seconds left} of the timed events playing now."""
    return _state["scape"].events_left() if _state["scape"] is not None else {}


def toggle_event(key: str) -> None:
    """Start a timed event (it fades in, stays its seconds and fades out), or fade it out early if it is playing."""
    if key in events_playing():
        stop_event(key)
        return
    s, scape = settings(), _scape()
    x, info = next((e for e in s["events"] if e["key"] == key), None), _sound("loops", key)
    if scape is None or x is None or info is None:
        return
    seconds = int(x.get("seconds", 20))
    scape.start_event(key, info["path"], gain(s["volume"]) * gain(x.get("volume", 100)),
                      seconds, fade=min(4.0, seconds / 3))
    _apply()                                           # opens the speakers if they aren't yet
    rt().bus.emit(events.SOUND)


def stop_event(key: str) -> None:
    if _state["scape"] is not None:
        _state["scape"].stop_event(key)
        rt().bus.emit(events.SOUND)


# ------------------------------------------------------------------ profiles
def select_profile(index: int) -> None:
    """Play another profile: its loops fade in as the last one's fade out."""
    _save(profile=int(index))


def add_profile(name: str, copy: bool = False) -> None:
    """A new profile (empty, or a copy of the one playing), which then plays."""
    s = settings()
    loops = [dict(x) for x in _loops(s)] if copy else []
    profiles = s["profiles"] + [{"name": str(name).strip() or "Profile", "loops": loops}]
    _save(profiles=profiles, profile=len(profiles) - 1)


def rename_profile(index: int, name: str) -> None:
    name = str(name).strip()
    if name:
        _save(profiles=[{**p, "name": name} if i == index else p for i, p in enumerate(settings()["profiles"])])


def delete_profile(index: int) -> None:
    """Remove a profile; the one that slides into its place plays (removing the only one leaves an empty profile)."""
    s = settings()
    profiles = [p for i, p in enumerate(s["profiles"]) if i != index]
    current = s["profile"] - (1 if index < s["profile"] or index == s["profile"] == len(s["profiles"]) - 1 else 0)
    _save(profiles=profiles, profile=max(0, current))


def play(key: str) -> None:
    """Play a one-shot effect once."""
    info, scape = _sound("oneshots", key), _scape()
    if info and scape is not None:
        scape.play_once(info["path"], gain(settings()["effects"]))


def stop_effects() -> None:
    if _state["scape"] is not None:
        _state["scape"].stop_once()
