"""The running apps a user can pick to stream audio from (Windows only)."""
import ctypes
from ctypes import wintypes
from typing import List, Tuple

import psutil
import win32con
import win32gui
import win32process

DWMWA_CLOAKED = 14


def _is_window_cloaked(hwnd) -> bool:
    """
    Detect DWM-cloaked windows. On modern Windows, UWP apps (and some other
    windows) can report IsWindowVisible()==True while not actually being on
    screen -- e.g. suspended, or living on a different virtual desktop.
    Without filtering these out, the list ends up with "ghost" entries that
    look selectable but capture nothing useful.
    """
    try:
        cloaked = wintypes.DWORD(0)
        ctypes.windll.dwmapi.DwmGetWindowAttribute(
            hwnd, DWMWA_CLOAKED, ctypes.byref(cloaked), ctypes.sizeof(cloaked)
        )
        return bool(cloaked.value)
    except Exception:
        return False


def _is_real_app_window(hwnd) -> bool:
    """
    Filter down to windows that represent an actual top-level application
    window a user would recognize -- not tool windows, owned/child popups,
    or cloaked ghost windows.
    """
    if not win32gui.IsWindowVisible(hwnd):
        return False
    if not win32gui.GetWindowText(hwnd):
        return False
    if win32gui.GetParent(hwnd):
        return False  # child/owned window, not a real top-level app window
    try:
        ex_style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
    except Exception:
        ex_style = 0
    if (ex_style & win32con.WS_EX_TOOLWINDOW) and not (ex_style & win32con.WS_EX_APPWINDOW):
        return False
    if _is_window_cloaked(hwnd):
        return False
    return True


def list_apps() -> List[Tuple[str, int]]:
    """[(label, pid)] of the visible top-level windows grouped by process, falling back to all processes."""
    apps = {}  # pid -> {"name": str, "titles": [str, ...]}

    def on_window(hwnd, _):
        if not _is_real_app_window(hwnd):
            return True
        try:
            _, pid = win32process.GetWindowThreadProcessId(hwnd)
        except Exception:
            return True
        entry = apps.setdefault(pid, {"name": None, "titles": []})
        entry["titles"].append(win32gui.GetWindowText(hwnd))
        if entry["name"] is None:
            try:
                entry["name"] = psutil.Process(pid).name()
            except (psutil.NoSuchProcess, psutil.AccessDenied):
                entry["name"] = "Unknown"
        return True

    win32gui.EnumWindows(on_window, None)

    if not apps:
        return sorted(((f"{p.info['name']} (PID: {p.info['pid']})", p.info["pid"])
                       for p in psutil.process_iter(["pid", "name"])), key=lambda e: e[0].lower())

    entries = []
    for pid, info in sorted(apps.items(), key=lambda kv: (kv[1]["name"] or "").lower()):
        extra = len(info["titles"]) - 1
        more = f"  (+{extra} more window{'s' if extra != 1 else ''})" if extra else ""
        entries.append((f"{info['name']} — {info['titles'][0]}{more} (PID: {pid})", pid))
    return entries
