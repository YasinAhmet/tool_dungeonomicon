"""
Captures audio from one or more Windows processes using WASAPI process loopback
(via proc-tap). If proc-tap fails, falls back to system-wide loopback (pyaudiowpatch).

The apps are captured once however many listen: the voice channel and the player
page each read the same capture through their own MultiProcessLoopbackAudioSource
(with its own volumes), and the capture stops when the last of them is cleaned up.
"""

import collections
import struct
import threading
import queue
import time
import audioop
from typing import Dict, List, Optional, Tuple

import discord

TARGET_RATE = 48000
TARGET_CHANNELS = 2
FRAME_BYTES = 3840  # 20ms at 48kHz/16-bit/stereo
SILENCE = b"\x00" * FRAME_BYTES

# Candidate class names exported by different versions of the `proctap` /
# `proc-tap` package. The installed version in this environment exports
# `ProcessAudioCapture` (confirmed from the `[audio] proctap attributes: [...]`
# debug line in the logs) -- the original list here was missing it entirely,
# which is why proc-tap capture was never actually used and every source
# silently fell back to system loopback.
PROC_TAP_CLASS_NAMES = [
    "ProcessAudioCapture",
    "ProcTap",
    "ProcessTap",
    "AudioCapture",
    "Capture",
    "LoopbackCapture",
]


class _FixedFrameQueue:
    """
    Accumulates arbitrarily-sized incoming PCM byte chunks and only ever
    hands out exactly FRAME_BYTES (20ms @ 48kHz/stereo/16-bit) frames.

    proc-tap (and PortAudio) deliver audio in whatever chunk size the OS
    handed them at capture time -- event-driven, not synced to any
    particular duration. discord.py's Opus encoder calls read() every 20ms
    and expects exactly one 20ms frame back each time. Handing it
    differently-sized chunks misaligns frame boundaries going into the
    encoder, which is heard as static/garbling even when the underlying PCM
    samples themselves are perfectly correct. This class is what actually
    re-syncs the two.
    """

    def __init__(self, maxsize: int = 10):
        self._queue = queue.Queue(maxsize=maxsize)
        self._acc = bytearray()
        self._lock = threading.Lock()

    def push(self, data: bytes) -> None:
        with self._lock:
            self._acc.extend(data)
            while len(self._acc) >= FRAME_BYTES:
                frame = bytes(self._acc[:FRAME_BYTES])
                del self._acc[:FRAME_BYTES]
                try:
                    self._queue.put_nowait(frame)
                except queue.Full:
                    # Prefer keeping the most recent audio over the oldest
                    # buffered frame, so latency doesn't creep up over time.
                    try:
                        self._queue.get_nowait()
                    except queue.Empty:
                        pass
                    try:
                        self._queue.put_nowait(frame)
                    except queue.Full:
                        pass

    def get_nowait(self) -> bytes:
        return self._queue.get_nowait()


class _Readers:
    """The listeners of one capture, each with its own _FixedFrameQueue: every captured chunk goes to all of them."""

    def __init__(self):
        self._queues: List[_FixedFrameQueue] = []
        self._lock = threading.Lock()

    def add(self) -> _FixedFrameQueue:
        q = _FixedFrameQueue(maxsize=10)
        with self._lock:
            self._queues = self._queues + [q]
        return q

    def remove(self, q: _FixedFrameQueue) -> None:
        with self._lock:
            self._queues = [x for x in self._queues if x is not q]

    def push(self, data: bytes) -> None:
        for q in self._queues:
            q.push(data)


class ProcessLoopbackAudioSource:
    """
    Captures audio from a single process using proc-tap.
    Raises RuntimeError if proc-tap isn't available/usable so the caller
    (AppCapture) can decide how to fall back, instead of
    each instance independently grabbing the system-wide loopback device.
    """

    def __init__(self, pid: int, log=print):
        self.log = log
        self._pid = pid
        self.readers = _Readers()
        self._stop_event = threading.Event()
        self._capturer = None
        self._rate_state = None
        self._source_rate = TARGET_RATE
        self._source_channels = TARGET_CHANNELS
        self._is_float = False  # whether frames arrive as float32 samples
        self._format_locked = False  # True once we've confirmed the real format

        self._proc_tap_class, self._proc_tap_module = self._get_proc_tap_class()
        if self._proc_tap_class is None:
            raise RuntimeError("proc-tap not available")

        # NOTE: we deliberately do NOT trust STANDARD_FORMAT / STANDARD_SAMPLE_RATE
        # module constants here. Those describe the library's *documented
        # default*, but per its own docs the actual negotiated format for a
        # given capture session can silently fall back to something else
        # (e.g. 44.1kHz int16 instead of 48kHz float32). Trusting the constant
        # instead of the real session format is exactly what caused loud
        # "static": raw float32 bytes were being read as if they were int16
        # PCM, which turns any signal (even near-silence) into broadband
        # noise, because the bit pattern of a float and an int mean
        # completely different things.
        self._started = threading.Event()
        self._start_error: Optional[Exception] = None
        self._capture_thread = threading.Thread(target=self._capture_loop, daemon=True)
        self._capture_thread.start()

        # Give the capture thread a moment to actually instantiate the
        # capturer so we can fail fast (and let the caller fall back) instead
        # of silently sitting there returning silence forever.
        self._started.wait(timeout=3.0)
        if self._start_error is not None:
            raise self._start_error

        self.log(f"[audio] Started process capture for PID {pid} using {self._proc_tap_class.__name__}")

    def _get_proc_tap_class(self):
        """Try to import proctap and locate the capture class."""
        try:
            import proctap
        except ImportError:
            self.log("[audio] proctap not installed")
            return None, None

        attrs = dir(proctap)
        self.log(f"[audio] proctap attributes: {attrs}")
        for name in PROC_TAP_CLASS_NAMES:
            if hasattr(proctap, name):
                return getattr(proctap, name), proctap
        self.log(f"[audio] no known proc-tap class found among {attrs}")
        return None, None

    def _instantiate_capturer(self, audio_callback):
        """
        Instantiate the proc-tap capture class. Constructor kwargs differ
        slightly between versions of the library, so try the documented
        signature first and fall back to a couple of known variants.
        """
        cls = self._proc_tap_class
        last_err = None
        attempts = [
            lambda: cls(pid=self._pid, on_data=audio_callback),
            lambda: cls(self._pid, on_data=audio_callback),
            lambda: cls(self._pid, callback=audio_callback),
        ]
        for attempt in attempts:
            try:
                return attempt()
            except TypeError as e:
                last_err = e
                continue
        raise last_err

    def _capture_loop(self):
        self.log(f"[audio] Capture loop started for PID {self._pid}")

        def audio_callback(data: bytes, frames: int = 0):
            if self._stop_event.is_set():
                return
            try:
                processed = self._process(data)
                self.readers.push(processed)
            except Exception as e:
                self.log(f"[audio] callback error: {e}")

        try:
            self._capturer = self._instantiate_capturer(audio_callback)
            self._capturer.start()
            self._detect_format()
            self.log(
                f"[audio] ProcTap started for PID {self._pid} "
                f"(rate={self._source_rate}, channels={self._source_channels}, "
                f"float={self._is_float})"
            )
            self._started.set()
            while not self._stop_event.is_set():
                time.sleep(0.1)
        except Exception as e:
            self.log(f"[audio] capture error for PID {self._pid}: {e}")
            self._start_error = e
            self._started.set()
        finally:
            if self._capturer:
                try:
                    self._capturer.stop()
                except Exception:
                    pass
            self.log(f"[audio] capture stopped for PID {self._pid}")

    def _detect_format(self):
        """
        Determine the ACTUAL negotiated sample rate/channels/format for this
        capture session, preferring what the capturer instance itself
        reports (e.g. via a get_format() method) over the library's
        documented "standard" defaults, since those can differ if the
        library fell back internally.
        """
        fmt_info = None
        getter = getattr(self._capturer, "get_format", None)
        if callable(getter):
            try:
                fmt_info = getter()
            except Exception as e:
                self.log(f"[audio] PID {self._pid}: get_format() failed: {e}")

        if isinstance(fmt_info, dict):
            for key in ("sample_rate", "rate", "samplerate"):
                if key in fmt_info:
                    self._source_rate = int(fmt_info[key])
                    break
            for key in ("channels", "num_channels", "nchannels"):
                if key in fmt_info:
                    self._source_channels = int(fmt_info[key])
                    break
            fmt_val = None
            for key in ("format", "sample_format", "dtype", "encoding"):
                if key in fmt_info:
                    fmt_val = fmt_info[key]
                    break
            if fmt_val is not None:
                self._is_float = "float" in str(fmt_val).lower()
            for key in ("sample_width", "bytes_per_sample", "bit_depth", "bits"):
                if key in fmt_info:
                    width_val = fmt_info[key]
                    if width_val in (4, 32):
                        self._is_float = True
                    elif width_val in (2, 16):
                        self._is_float = False
                    break
            self.log(f"[audio] PID {self._pid}: negotiated format via get_format(): {fmt_info}")
        else:
            # No get_format() available (or it failed) -- fall back to the
            # module's documented defaults, but flag clearly that this is a
            # guess, not a confirmed fact, so it's easy to spot in logs if
            # audio still sounds wrong.
            mod = self._proc_tap_module
            self._source_rate = getattr(mod, "STANDARD_SAMPLE_RATE", TARGET_RATE)
            self._source_channels = getattr(mod, "STANDARD_CHANNELS", TARGET_CHANNELS)
            fmt = getattr(mod, "STANDARD_FORMAT", "int16")
            width = getattr(mod, "STANDARD_SAMPLE_WIDTH", 2)
            self._is_float = ("float" in str(fmt).lower()) or (width in (4, 32))
            self.log(
                f"[audio] PID {self._pid}: no get_format() available, GUESSING "
                f"from module defaults (format={fmt!r}, width={width}) -> "
                f"is_float={self._is_float}. If audio still sounds like static, "
                f"this guess is likely wrong -- check the proc-tap docs/source "
                f"for how to query the real per-session format."
            )
        self._format_locked = True

    def _process(self, data: bytes) -> bytes:
        """Convert whatever proc-tap gives us into 48kHz/stereo/16-bit PCM."""
        if self._is_float:
            # audioop can't touch float samples, so convert to int16 first.
            # Getting this wrong (treating float32 bytes as int16, or vice
            # versa) is what produces loud "static" regardless of the
            # source content -- reinterpreting a float's bit pattern as an
            # integer turns even near-silent audio into broadband noise.
            import array
            floats = array.array("f")
            floats.frombytes(data)
            ints = array.array(
                "h", (max(-32768, min(32767, int(s * 32767))) for s in floats)
            )
            data = ints.tobytes()

        if self._source_channels == 1:
            data = audioop.tostereo(data, 2, 1, 1)
        elif self._source_channels > 2:
            data = audioop.tomono(data, 2, 1.0 / self._source_channels, 1.0 / self._source_channels)
            data = audioop.tostereo(data, 2, 1, 1)

        if self._source_rate != TARGET_RATE:
            data, self._rate_state = audioop.ratecv(
                data, 2, TARGET_CHANNELS, self._source_rate, TARGET_RATE, self._rate_state
            )
        return data

    def cleanup(self):
        self._stop_event.set()
        if self._capturer:
            try:
                self._capturer.stop()
            except Exception:
                pass
        if self._capture_thread.is_alive():
            self._capture_thread.join(timeout=2.0)


class SystemLoopbackAudioSource:
    """
    System-wide loopback fallback (pyaudiowpatch). This is inherently
    system-wide, not per-process, so only ONE instance should ever be
    created regardless of how many target PIDs there are -- creating one
    per PID just means N threads fighting over the same WASAPI loopback
    device, which is what caused the repeated
    "[audio] Failed to start system loopback:" errors in the log.
    """

    def __init__(self, log=print):
        self.log = log
        self.readers = _Readers()
        self._stop_event = threading.Event()
        self._rate_state = None
        self._source_rate = 48000
        self._source_channels = 2
        self._pa = None
        self._stream = None
        # Keep a reference to the pyaudiowpatch module on the instance so
        # the stream callback (which runs on PortAudio's own thread) can
        # reach `paContinue`/`paComplete`. The original code referenced a
        # bare `pyaudio` name inside `_system_callback`, but `pyaudio` was
        # only ever a local variable inside `_init_system_loopback` -- so
        # every callback invocation raised a NameError. PortAudio's C layer
        # swallows exceptions raised inside the callback, so this failed
        # silently: the stream looked like it started fine, but no audio
        # frame was ever pushed into the buffer.
        self._pyaudio = None
        self._init_system_loopback()

    def _init_system_loopback(self):
        try:
            import pyaudiowpatch as pyaudio
        except ImportError:
            self.log("[audio] pyaudiowpatch not installed, cannot capture audio")
            return

        self._pyaudio = pyaudio
        self._pa = pyaudio.PyAudio()
        try:
            device = self._pa.get_default_wasapi_loopback()
            self.log(f"[audio] Using system loopback: {device['name']}")
            self._source_rate = int(device["defaultSampleRate"])
            self._source_channels = int(device["maxInputChannels"]) or 2
            self._stream = self._pa.open(
                format=pyaudio.paInt16,
                channels=self._source_channels,
                rate=self._source_rate,
                input=True,
                input_device_index=device["index"],
                frames_per_buffer=1024,
                stream_callback=self._system_callback,
            )
            self._stream.start_stream()
            self.log("[audio] System loopback started")
        except Exception as e:
            self.log(f"[audio] Failed to start system loopback: {e!r}")

    def _system_callback(self, in_data, frame_count, time_info, status):
        pa = self._pyaudio
        if self._stop_event.is_set():
            return (None, pa.paComplete if pa else 0)
        try:
            processed = self._process(in_data)
            self.readers.push(processed)
        except Exception as e:
            self.log(f"[audio] system callback error: {e}")
        return (None, pa.paContinue if pa else 0)

    def _process(self, data: bytes) -> bytes:
        if self._source_channels == 1:
            data = audioop.tostereo(data, 2, 1, 1)
        elif self._source_channels > 2:
            data = audioop.tomono(data, 2, 1.0 / self._source_channels, 1.0 / self._source_channels)
            data = audioop.tostereo(data, 2, 1, 1)
        if self._source_rate != TARGET_RATE:
            data, self._rate_state = audioop.ratecv(
                data, 2, TARGET_CHANNELS, self._source_rate, TARGET_RATE, self._rate_state
            )
        return data

    def cleanup(self):
        self._stop_event.set()
        if self._stream:
            try:
                self._stream.stop_stream()
                self._stream.close()
            except Exception:
                pass
        if self._pa:
            try:
                self._pa.terminate()
            except Exception:
                pass


class AppCapture:
    """
    The chosen apps' audio, captured once for every listener. De-duplicates
    PIDs (the log showed the same PID passed in 5 times) and shares a single
    system-loopback fallback across all PIDs that can't be captured
    individually via proc-tap, instead of opening the system-wide loopback
    device once per PID. Made and closed by _attach()/_detach().
    """

    def __init__(self, pids: List[int], log=print):
        self.log = log
        self.pids = list(dict.fromkeys(pids))  # de-dupe, preserve order
        if len(self.pids) != len(pids):
            self.log(f"[audio] De-duplicated PIDs {pids} -> {self.pids}")
        self.sources: list = []
        self.source_pids: List[Optional[int]] = []      # which process each source belongs to (None: the shared system loopback)
        self.users = 0

        needs_system_fallback = False
        for pid in self.pids:
            try:
                self.sources.append(ProcessLoopbackAudioSource(pid, log))
                self.source_pids.append(pid)
            except RuntimeError as e:
                self.log(f"[audio] proc-tap unavailable for PID {pid} ({e}); will use system loopback")
                needs_system_fallback = True

        if needs_system_fallback:
            # Exactly one shared system-wide fallback, no matter how many
            # PIDs needed it -- system loopback isn't per-process anyway.
            self.sources.append(SystemLoopbackAudioSource(log))
            self.source_pids.append(None)

        self.log(f"[audio] Capture started for PIDs: {self.pids}")

    def cleanup(self):
        for src in self.sources:
            src.cleanup()
        self.log(f"[audio] Capture stopped for PIDs: {self.pids}")


_captures: Dict[Tuple[int, ...], AppCapture] = {}
_captures_lock = threading.Lock()


def _attach(pids: List[int], log) -> Tuple[AppCapture, List[_FixedFrameQueue]]:
    """The running capture of these apps (started if there is none) and a new queue on each of its sources."""
    key = tuple(dict.fromkeys(pids))
    with _captures_lock:
        capture = _captures.get(key)
        if capture is None:
            capture = _captures[key] = AppCapture(list(key), log)
        capture.users += 1
        return capture, [src.readers.add() for src in capture.sources]


def _detach(capture: AppCapture, queues: List[_FixedFrameQueue]):
    """Stop reading a capture; the last listener to leave stops it."""
    with _captures_lock:
        for src, q in zip(capture.sources, queues):
            src.readers.remove(q)
        capture.users -= 1
        last = capture.users <= 0
        if last and _captures.get(tuple(capture.pids)) is capture:
            del _captures[tuple(capture.pids)]
    if last:
        capture.cleanup()


class MultiProcessLoopbackAudioSource(discord.AudioSource):
    """One listener of the chosen apps (the voice channel, the player page): the shared capture mixed with this
    listener's own volumes and delay."""

    def __init__(self, pids: List[int], log=print):
        self.log = log
        self._capture, self._queues = _attach(pids, log)
        self._source_pids = self._capture.source_pids
        self._master, self._per_pid = 1.0, {}
        self._delay_frames = 0                          # the stream is held back by this many 20 ms frames
        self._held = collections.deque()
        self._stop_event = threading.Event()

    def read(self) -> bytes:
        if self._stop_event.is_set():
            return b""
        frames = [self._take(q) for q in self._queues]
        out = self._mix_frames(frames, [self._gain_of(p) for p in self._source_pids])
        if not self._delay_frames and not self._held:
            return out
        self._held.append(out)
        while len(self._held) > self._delay_frames + 1:       # the delay was shortened: catch up
            self._held.popleft()
        if len(self._held) <= self._delay_frames:             # still filling the delay: silence
            return SILENCE
        return self._held.popleft()

    @staticmethod
    def _take(q: _FixedFrameQueue) -> bytes:
        try:
            return q.get_nowait()
        except queue.Empty:
            return SILENCE

    def set_delay(self, milliseconds: float):
        """Hold the whole stream back (handy for testing or lining the audio up with a video)."""
        self._delay_frames = max(0, int(round(float(milliseconds) / 20)))

    def set_gains(self, master: float, per_pid: dict):
        """Live volume: `master` for everything, `per_pid` {pid: factor} for single apps (1.0 = unchanged)."""
        self._master, self._per_pid = max(0.0, float(master)), {int(k): max(0.0, float(v)) for k, v in per_pid.items()}

    def _gain_of(self, pid: Optional[int]) -> float:
        return self._master * (self._per_pid.get(pid, 1.0) if pid is not None else 1.0)

    def _mix_frames(self, frames: List[bytes], gains: Optional[List[float]] = None) -> bytes:
        if gains:
            frames = [f if abs(g - 1.0) < 1e-3 else audioop.mul(f, 2, g) for f, g in zip(frames, gains)]
        if not frames:
            return SILENCE
        sample_count = len(frames[0]) // 2
        mixed = [0] * sample_count
        for frame in frames:
            if len(frame) // 2 != sample_count:
                continue
            samples = struct.unpack(f"<{sample_count}h", frame)
            for i, s in enumerate(samples):
                mixed[i] += s
        mixed = [max(-32768, min(32767, v)) for v in mixed]
        return struct.pack(f"<{sample_count}h", *mixed)

    def is_opus(self) -> bool:
        return False

    def cleanup(self):
        if not self._stop_event.is_set():
            self._stop_event.set()
            _detach(self._capture, self._queues)
