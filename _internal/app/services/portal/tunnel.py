"""A Cloudflare quick tunnel: a free public https address (https://<words>.trycloudflare.com) that reaches the
portal on this PC. cloudflared makes an outgoing connection to Cloudflare, so no router port is opened and the
home IP stays hidden. The address changes every time the tunnel starts; stopping it makes the address dead.

cloudflared.exe is a single program kept in Documents\\Dungeonomicon\\tools (nothing is installed). `download()`
fetches it from Cloudflare's official GitHub releases and refuses it unless Windows confirms Cloudflare's code
signature.
"""
import os
import re
import shutil
import subprocess
import threading
import urllib.request
from typing import Callable, Optional

from ...core import userdata
from ..common import ServiceError

DOWNLOAD_URL = "https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-windows-amd64.exe"
URL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
_job = None                                          # Windows job object holding cloudflared (see _tie_to_app)


def _tie_to_app(proc: subprocess.Popen):
    """Put cloudflared in a job that Windows closes when this process ends - however it ends (closed, crashed, killed
    from the Task Manager) - so the public link never outlives the app."""
    global _job
    if os.name != "nt":
        return
    try:
        import ctypes
        from ctypes import wintypes
        k32 = ctypes.WinDLL("kernel32", use_last_error=True)
        k32.CreateJobObjectW.restype = wintypes.HANDLE
        k32.SetInformationJobObject.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p, wintypes.DWORD]
        k32.AssignProcessToJobObject.argtypes = [wintypes.HANDLE, wintypes.HANDLE]
        if _job is None:

            class Limits(ctypes.Structure):          # JOBOBJECT_EXTENDED_LIMIT_INFORMATION
                _fields_ = [("PerProcessUserTimeLimit", ctypes.c_int64), ("PerJobUserTimeLimit", ctypes.c_int64),
                            ("LimitFlags", wintypes.DWORD), ("MinimumWorkingSetSize", ctypes.c_size_t),
                            ("MaximumWorkingSetSize", ctypes.c_size_t), ("ActiveProcessLimit", wintypes.DWORD),
                            ("Affinity", ctypes.c_size_t), ("PriorityClass", wintypes.DWORD),
                            ("SchedulingClass", wintypes.DWORD), ("IoInfo", ctypes.c_uint64 * 6),
                            ("ProcessMemoryLimit", ctypes.c_size_t), ("JobMemoryLimit", ctypes.c_size_t),
                            ("PeakProcessMemoryUsed", ctypes.c_size_t), ("PeakJobMemoryUsed", ctypes.c_size_t)]
            job = k32.CreateJobObjectW(None, None)
            info = Limits(LimitFlags=0x2000)          # JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            if not job or not k32.SetInformationJobObject(job, 9, ctypes.byref(info), ctypes.sizeof(info)):
                return
            _job = job                               # never closed: the handle goes when the process does
        k32.AssignProcessToJobObject(_job, wintypes.HANDLE(int(proc._handle)))
    except Exception:                                # noqa: BLE001 - stop() still ends it on a normal close
        pass


def exe_path() -> str:
    return os.path.join(userdata.home(), "tools", "cloudflared.exe")


def find() -> Optional[str]:
    """cloudflared.exe in the tools folder, or one already on the PATH."""
    if os.path.isfile(exe_path()):
        return exe_path()
    return shutil.which("cloudflared")


def signed_by_cloudflare(path: str) -> bool:
    """Windows' own check of the file's Authenticode signature: valid, and signed by Cloudflare."""
    cmd = ["powershell", "-NoProfile", "-NonInteractive", "-Command",
           f"$s = Get-AuthenticodeSignature -LiteralPath '{path}'; \"$($s.Status)|$($s.SignerCertificate.Subject)\""]
    try:
        out = subprocess.run(cmd, capture_output=True, text=True, timeout=60, creationflags=NO_WINDOW).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return False
    status, _, subject = out.partition("|")
    return status == "Valid" and "cloudflare" in subject.lower()


def download(progress: Optional[Callable[[int, int], None]] = None) -> str:
    """Fetch cloudflared.exe (about 60 MB) into the tools folder; returns its path."""
    target = exe_path()
    os.makedirs(os.path.dirname(target), exist_ok=True)
    part = target + ".part"
    try:
        with urllib.request.urlopen(DOWNLOAD_URL, timeout=60) as r, open(part, "wb") as f:
            total, done = int(r.headers.get("Content-Length") or 0), 0
            while True:
                chunk = r.read(1 << 16)
                if not chunk:
                    break
                f.write(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
    except OSError as e:
        raise ServiceError(f"Couldn't download cloudflared: {e}")
    if not signed_by_cloudflare(part):
        os.remove(part)
        raise ServiceError("The downloaded cloudflared isn't signed by Cloudflare, so it was deleted.")
    os.replace(part, target)
    return target


class Tunnel:
    def __init__(self):
        self.proc: Optional[subprocess.Popen] = None
        self.url = ""
        self.error = ""
        self.on_change: Callable[[], None] = lambda: None

    @property
    def running(self) -> bool:
        return self.proc is not None and self.proc.poll() is None

    def start(self, port: int):
        if self.running:
            return
        exe = find()
        if not exe:
            raise ServiceError("cloudflared isn't downloaded yet.")
        self.url, self.error = "", ""
        self.proc = subprocess.Popen([exe, "tunnel", "--no-autoupdate", "--url", f"http://127.0.0.1:{port}"],
                                     stdout=subprocess.PIPE, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                     text=True, encoding="utf-8", errors="replace", creationflags=NO_WINDOW)
        _tie_to_app(self.proc)
        threading.Thread(target=self._watch, args=(self.proc,), daemon=True, name="tunnel").start()

    def _watch(self, proc: subprocess.Popen):
        for line in proc.stdout:
            m = URL_RE.search(line)
            if m and not self.url:
                self.url = m.group(0)
                self.on_change()
            elif "ERR" in line and not self.url:
                self.error = line.strip()[-200:]
        if proc is self.proc:                        # it ended by itself
            self.url = ""
            self.error = self.error or "The tunnel stopped."
            self.proc = None
            self.on_change()

    def stop(self):
        proc, self.proc = self.proc, None
        self.url = ""
        if proc and proc.poll() is None:
            proc.terminate()
            try:
                proc.wait(timeout=5)
            except subprocess.TimeoutExpired:
                proc.kill()
        self.on_change()
