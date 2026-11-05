"""The table's sound on the player page: what the DM shares - the apps streamed from the Audio window (the music) and,
when "Player page" is ticked there, the ambience loops and effects - encoded as Opus once and sent to every player who
pressed Listen, as an Ogg stream their browser's <audio> plays. Each player sets their own volume on the page.

    q = music.listen()           # a listener: its queue gets 20 ms Opus packets while the stream runs
    music.leave(q)
    music.refresh()              # the chosen apps or their volumes changed (Runtime.update_server calls it)
    music.set_sound(scape, on)   # the table's sounds (app.services.sound) and whether the page hears them
    OggOpus().head()             # one listener's Ogg stream: the two header pages, then .page(packets)

The apps are captured once for the voice channel and the page together (app.bot.audio_capture); nothing is captured
or encoded while nobody listens.
"""
import queue
import random
import struct
import threading
import time
from typing import List, Optional

from ...core import events

SAMPLES = 960                    # one 20 ms frame at 48 kHz
FRAME = SAMPLES / 48000
BITRATE = 96                     # kbps: plenty for music, about 12 KB/s per listener through the tunnel
PRESKIP = 312                    # the Opus encoder's look-ahead at 48 kHz (RFC 7845 pre-skip)
BACKLOG = 250                    # packets (5 s) kept for a listener whose connection stalls; older ones are dropped


def _crc_table() -> List[int]:
    table = []
    for i in range(256):
        r = i << 24
        for _ in range(8):
            r = ((r << 1) ^ 0x04C11DB7) if r & 0x80000000 else r << 1
        table.append(r & 0xFFFFFFFF)
    return table


_CRC = _crc_table()


def ogg_crc(data: bytes) -> int:
    """Ogg's page checksum (CRC-32, polynomial 0x04C11DB7, not reflected - not zlib's)."""
    c = 0
    for b in data:
        c = ((c << 8) & 0xFFFFFFFF) ^ _CRC[(c >> 24) ^ b]
    return c


class OggOpus:
    """One listener's Ogg Opus stream (RFC 7845): its own serial number, page count and sample position, so a player
    who joins late still gets a stream that starts at its beginning."""

    def __init__(self):
        self.serial = random.getrandbits(32)
        self.seq = 0
        self.granule = 0

    def head(self) -> bytes:
        opus_head = b"OpusHead" + struct.pack("<BBHIhB", 1, 2, PRESKIP, 48000, 0, 0)
        vendor = b"Dungeonomicon"
        opus_tags = b"OpusTags" + struct.pack("<I", len(vendor)) + vendor + struct.pack("<I", 0)
        return self._page([opus_head], 0x02) + self._page([opus_tags])

    def page(self, packets: List[bytes]) -> bytes:
        """A page of Opus packets (20 ms each)."""
        self.granule += SAMPLES * len(packets)
        return self._page(packets)

    def _page(self, packets: List[bytes], flags: int = 0) -> bytes:
        lacing = bytearray()
        for p in packets:
            lacing += b"\xff" * (len(p) // 255) + bytes([len(p) % 255])
        page = bytearray(struct.pack("<4sBBqIIIB", b"OggS", 0, flags, self.granule, self.serial, self.seq, 0, len(lacing)))
        page += lacing
        for p in packets:
            page += p
        struct.pack_into("<I", page, 22, ogg_crc(page))
        self.seq += 1
        return bytes(page)


class Music:
    def __init__(self):
        self.lock = threading.Lock()
        self._listeners: List[queue.Queue] = []
        self._thread: Optional[threading.Thread] = None
        self._dirty = True                     # the settings changed: the pump re-reads them
        self._apps = None                      # the chosen apps (a MultiProcessLoopbackAudioSource) while the pump runs
        self._apps_key: tuple = ()
        self._scape, self._sound_on = None, True
        self._player = None                    # the table's sounds for the page (a soundscape Player)

    @property
    def listeners(self) -> int:
        with self.lock:
            return len(self._listeners)

    def listen(self) -> queue.Queue:
        q: queue.Queue = queue.Queue(maxsize=BACKLOG)
        with self.lock:
            self._listeners.append(q)
            start = self._thread is None
            if start:
                self._dirty = True
                self._thread = threading.Thread(target=self._run, daemon=True, name="portal-music")
                self._thread.start()
        self._changed()
        return q

    def leave(self, q: queue.Queue):
        with self.lock:
            if q in self._listeners:
                self._listeners.remove(q)
        self._changed()

    def refresh(self):
        """Follow the selected server's app streaming (on or off, which apps, their volumes) from the next frame."""
        self._dirty = True

    def set_sound(self, scape, on: bool):
        self._scape, self._sound_on = scape, bool(on)
        self._dirty = True

    @staticmethod
    def _changed():
        from ...core.runtime import rt
        rt().bus.emit(events.PORTAL)

    # ------------------------------------------------------------------ the pump (its own thread)
    def _run(self):
        from ...core.runtime import rt
        try:
            import discord.opus
            encoder = discord.opus.Encoder(bitrate=BITRATE, fec=False)      # over TCP: no packets are lost
            encoder.set_expected_packet_loss_percent(0)
        except Exception as e:
            rt().log(f"[portal] The page's music needs the Opus encoder: {e}")
            self._end()
            return
        due = time.monotonic()
        try:
            while True:
                with self.lock:
                    if not self._listeners:
                        self._end_locked()
                        return
                    listeners = list(self._listeners)
                if self._dirty:
                    self._dirty = False
                    self._follow()
                now = time.monotonic()
                if now < due:
                    time.sleep(due - now)
                    continue
                if now - due > 0.2:            # far behind (the PC was busy or asleep): don't rush to catch up
                    due = now
                due += FRAME
                packet = encoder.encode(self._frame(), SAMPLES)
                for q in listeners:
                    try:
                        q.put_nowait(packet)
                    except queue.Full:         # that player's connection stalled: they skip ahead
                        pass
        except Exception as e:
            rt().log(f"[portal] The page's music stopped: {e}")
            self._end()

    def _end(self):
        """Something went wrong: every listener's stream ends (their pages try again a little later)."""
        with self.lock:
            self._listeners = []
            self._end_locked()
        self._changed()

    def _end_locked(self):
        """The pump stops (holding the lock, so a listener who comes now starts a new one after the apps are let go)."""
        self._close_apps()
        self._player = None
        self._thread = None

    def serving(self, q: queue.Queue) -> bool:
        """False once a listener's stream has been ended."""
        with self.lock:
            return q in self._listeners

    def _frame(self) -> bytes:
        """The next 20 ms of 16-bit stereo PCM: the apps with the table's sounds on top."""
        from ...bot.audio_capture import SILENCE
        apps = self._apps
        frame = (apps.read() if apps is not None else b"") or SILENCE
        if self._player is None:
            return frame
        from ...bot.soundscape import mix_pcm
        return mix_pcm(frame, self._player)

    def _follow(self):
        from ...bot.volume import gain
        from ...core.runtime import parse_pids, rt
        r = rt()
        ss = r.server_settings() if r.guild_id else None
        key = tuple(parse_pids(ss["target_pids"])) if ss and ss["stream_audio"] else ()
        if key != self._apps_key:
            self._close_apps()
            if key:
                from ...bot.audio_capture import MultiProcessLoopbackAudioSource
                try:
                    self._apps = MultiProcessLoopbackAudioSource(list(key), log=r.log)
                except Exception as e:
                    r.log(f"[portal] Could not capture the apps for the page: {e}")
            self._apps_key = key
        if self._apps is not None:             # the same volumes as the voice channel (percents are loudness)
            self._apps.set_gains(0 if ss["muted"] else gain(ss["volume"]),
                                 {int(k): gain(v) for k, v in (ss["app_volumes"] or {}).items()})
        scape = self._scape if self._sound_on else None
        if scape is None:
            self._player = None
        elif self._player is None or self._player.scape is not scape:
            self._player = scape.player()

    def _close_apps(self):
        apps, self._apps, self._apps_key = self._apps, None, ()
        if apps is not None:
            apps.cleanup()


music = Music()
