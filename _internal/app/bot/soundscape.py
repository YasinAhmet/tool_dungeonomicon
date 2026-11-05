"""The table's own sound: looping ambience (rain, a campfire, footsteps on mud) and one-shot effects (a door, an
explosion, a bell), mixed at 48 kHz stereo for the voice channel and for this computer's speakers.

    scape = Soundscape(log)
    scape.set_loops({"rain": ("…/rain.ogg", 0.8)})   # exactly these loops play, at these volumes
    scape.play_once("…/door.ogg", 1.0)
    scape.start_event("carriage", "…/carriage.ogg", 1.0, seconds=20, fade=4)   # a loop that comes and goes once
    player = scape.player()                          # one per listener: player.read_pcm(960) -> 20 ms of int16

Every listener (the voice channel, the speakers) gets its own Player, so each keeps its own place in the loops.
Files are decoded once (on a background thread for loops) and shared. Volume changes and loops starting or stopping
fade over a moment, so nothing clicks.
"""
import threading
import time
import weakref
from typing import Callable, Dict, Optional, Tuple

import numpy as np

RATE = 48000
FADE = 0.4                      # seconds a loop takes to fade in or out


def decode(path: str) -> np.ndarray:
    """A sound file as float32 [frames, 2] at RATE."""
    import soundfile as sf
    data, rate = sf.read(path, dtype="float32", always_2d=True)
    data = np.repeat(data, 2, 1) if data.shape[1] == 1 else data[:, :2]
    if rate != RATE and len(data):
        n = int(round(len(data) * RATE / rate))
        x = np.linspace(0, len(data) - 1, n)
        data = np.stack([np.interp(x, np.arange(len(data)), data[:, c]) for c in range(2)], 1).astype(np.float32)
    return np.ascontiguousarray(data)


class Soundscape:
    def __init__(self, log: Callable[[str], None] = print):
        self.log = log
        self._lock = threading.Lock()
        self._clips: Dict[str, np.ndarray] = {}
        self._loops: Dict[str, Tuple[str, float]] = {}       # what should play: key -> (file, volume 0..)
        self._events: Dict[str, list] = {}                   # timed events: key -> [file, volume, seconds, fade, start]
        self._players: "weakref.WeakSet[Player]" = weakref.WeakSet()
        self._loading = threading.Event()

    # ------------------------------------------------------------------ what plays
    def set_loops(self, loops: Dict[str, Tuple[str, float]]):
        """Exactly these loops play: {key: (file, volume)}; files not decoded yet start once they are."""
        with self._lock:
            self._loops = dict(loops)
        self._load()

    def _files(self) -> list:
        return [p for p, _v in self._loops.values()] + [e[0] for e in self._events.values()]

    def _load(self):
        """Decode the files the loops and events need, on a background thread."""
        if any(p not in self._clips for p in self._files()) and not self._loading.is_set():
            self._loading.set()
            threading.Thread(target=self._load_files, daemon=True).start()

    def _load_files(self):
        try:
            while True:
                with self._lock:
                    missing = [p for p in self._files() if p not in self._clips]
                if not missing:
                    return
                try:
                    clip = decode(missing[0])
                except Exception as e:
                    self.log(f"[sound] Could not read {missing[0]}: {e}")
                    clip = np.zeros((RATE // 10, 2), np.float32)
                with self._lock:
                    self._clips[missing[0]] = clip
        finally:
            self._loading.clear()

    def start_event(self, key: str, path: str, volume: float, seconds: float, fade: float):
        """Play a loop once for `seconds` (counted from when it is ready), fading in and out over `fade` seconds."""
        with self._lock:
            self._events[key] = [path, float(volume), float(seconds), max(0.05, float(fade)), None]
        self._load()

    def stop_event(self, key: str):
        """Fade a timed event out now."""
        with self._lock:
            self._events.pop(key, None)

    def set_event_volume(self, key: str, volume: float):
        with self._lock:
            if key in self._events:
                self._events[key][1] = float(volume)

    def events_left(self) -> Dict[str, float]:
        """{key: seconds left} of the timed events playing (or waiting for their file)."""
        now = time.monotonic()
        with self._lock:
            return {k: e[2] if e[4] is None else max(0.0, e[4] + e[2] - now) for k, e in self._events.items()}

    def play_once(self, path: str, volume: float):
        """Play a sound once for every listener."""
        clip = self._clips.get(path)
        if clip is None:
            clip = self._clips[path] = decode(path)
        for p in list(self._players):
            p.shots.append([clip, 0, float(volume)])

    def stop_once(self):
        """Cut every one-shot that is still sounding."""
        for p in list(self._players):
            p.shots.clear()

    def player(self) -> "Player":
        p = Player(self)
        self._players.add(p)
        return p

    def wanted(self) -> Dict[str, Tuple[np.ndarray, float, float]]:
        """{key: (decoded clip, volume, fade seconds)} of the loops and timed events that should sound now."""
        now = time.monotonic()
        with self._lock:
            out = {k: (self._clips[p], v, FADE) for k, (p, v) in self._loops.items() if p in self._clips}
            for k, e in list(self._events.items()):
                path, volume, seconds, fade, start = e
                if path not in self._clips:
                    continue
                if start is None:                              # its time starts once its file is ready
                    start = e[4] = now
                if now >= start + seconds:
                    del self._events[k]
                elif now < start + seconds - fade:             # the fade-out ends when its time is up
                    out["event:" + k] = (self._clips[path], volume, fade)
            return out


class Player:
    """One listener's mix: call read(n) for the next n frames (float32 [n, 2])."""

    def __init__(self, scape: Soundscape):
        self.scape = scape
        self.loops: Dict[str, list] = {}       # key -> [clip, position, volume now, fade seconds, full volume]
        self.shots: list = []                  # [clip, position, volume]
        self.volume = 1.0                      # this listener's own level (0 silences it)

    def read(self, n: int) -> np.ndarray:
        out = np.zeros((n, 2), np.float32)
        want = self.scape.wanted()
        for key in set(self.loops) | set(want):
            clip, target, fade = want.get(key, (None, 0.0, None))
            state = self.loops.get(key)
            if state is None:
                state = self.loops[key] = [clip, 0, 0.0, fade, 0.0]
            elif clip is not None:
                state[0], state[3] = clip, fade
            target *= self.volume
            if target > 0:
                state[4] = target
            clip, pos, vol, fade, full = state
            step = max(full, 0.05) * n / (fade * RATE)            # a whole fade takes `fade` seconds at any level
            new = min(target, vol + step) if target > vol else max(target, vol - step)
            if vol == 0 and new == 0:
                if key not in want:
                    del self.loops[key]
                continue
            idx = (pos + np.arange(n)) % len(clip)
            out += clip[idx] * np.linspace(vol, new, n, dtype=np.float32)[:, None]
            state[1], state[2] = (pos + n) % len(clip), new
        for shot in list(self.shots):
            clip, pos, vol = shot
            part = clip[pos:pos + n]
            out[:len(part)] += part * (vol * self.volume)
            shot[1] = pos + n
            if shot[1] >= len(clip):
                try:
                    self.shots.remove(shot)
                except ValueError:             # stop_once() cleared them meanwhile
                    pass
        return out

    def read_pcm(self, n: int) -> bytes:
        """The next n frames as 16-bit stereo PCM."""
        return (np.clip(self.read(n), -1.0, 1.0) * 32767).astype("<i2").tobytes()


class Speakers:
    """Plays a Player through this computer's default output (PortAudio, via pyaudiowpatch)."""

    def __init__(self, player: Player, log: Callable[[str], None] = print):
        import pyaudiowpatch as pyaudio
        self.player = player
        self._pa = pyaudio.PyAudio()
        self._stream = self._pa.open(format=pyaudio.paInt16, channels=2, rate=RATE, output=True,
                                     frames_per_buffer=RATE // 50, stream_callback=self._callback)
        self._continue = pyaudio.paContinue
        self.log = log

    def _callback(self, _in, frames, _time, _status):
        try:
            return self.player.read_pcm(frames), self._continue
        except Exception as e:
            self.log(f"[sound] speakers: {e}")
            return b"\x00" * (frames * 4), self._continue

    def close(self):
        try:
            self._stream.stop_stream()
            self._stream.close()
        finally:
            self._pa.terminate()


def mix_pcm(frame: bytes, player: Optional[Player]) -> bytes:
    """Add a player's next 20 ms to a 20 ms frame of 16-bit stereo PCM."""
    if player is None:
        return frame
    n = len(frame) // 4
    mixed = np.frombuffer(frame, "<i2").reshape(n, 2) / 32767.0 + player.read(n)
    return (np.clip(mixed, -1.0, 1.0) * 32767).astype("<i2").tobytes()
