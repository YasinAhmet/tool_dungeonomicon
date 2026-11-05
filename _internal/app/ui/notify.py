"""Short messages in the corner of the main window (toasts). Any thread may call these; they always show on the UI thread.

    notify.info(tr("Saved."))      notify.warn(...)      notify.error(...)
"""
from typing import Callable, Optional

_sink: Optional[Callable[[str, str], None]] = None


def set_sink(fn: Callable[[str, str], None]):
    """The main window shows the messages; before it exists they only go to the log."""
    global _sink
    _sink = fn


def show(message: str, kind: str = "info"):
    if _sink:
        _sink(message, kind)
    else:
        from ..core.runtime import rt
        rt().log(f"[{kind.upper()}] {message}")


def info(message: str):
    show(message, "info")


def good(message: str):
    show(message, "good")


def warn(message: str):
    show(message, "warn")


def error(message: str):
    show(message, "error")
