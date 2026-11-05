"""One place that turns failures into messages, so panels can call the services without try/except of their own.

    guard(lambda: rt().characters.damage(name, 5))      # a ServiceError becomes a red notification, never a crash
    if guard_ok(rt().battle.remove, cid): ...            # True when it worked (for calls that return nothing)
    @guarded                                             # the same for a whole slot
    def on_click(self): ...

Errors the user caused (bad input, a broken rule) show their own message, translated. Anything else is a bug:
the traceback goes to the log and a short notice to the screen. `install()` also catches whatever escapes a Qt slot.
"""
import functools
import sys
import traceback

from ..core.i18n import tr

_USER_ERRORS = None


def user_errors() -> tuple:
    """Exception types whose message is meant for the user."""
    global _USER_ERRORS
    if _USER_ERRORS is None:
        from ..services.common import ServiceError
        from ..rules.dice import DiceError
        from ..rules.leveling import RulesError
        from ..rules.sheet_html import ExportError
        _USER_ERRORS = (ServiceError, RulesError, DiceError, ExportError, ValueError, KeyError)
    return _USER_ERRORS


def report(exc: BaseException):
    from . import notify
    from ..core.runtime import rt
    if isinstance(exc, user_errors()):
        text = exc.args[0] if isinstance(exc, KeyError) and exc.args else str(exc)
        busy = type(exc).__name__ == "Busy"         # the dice are rolling / a reaction is waiting: not a mistake
        rt().log(f"[{'BUSY' if busy else 'REFUSED'}] editor: {text}")
        (notify.info if busy else notify.error)(tr(str(text)))
        return
    rt().log("[ERROR] " + "".join(traceback.format_exception(type(exc), exc, exc.__traceback__)).rstrip())
    notify.error(tr("Something went wrong: {0}", f"{type(exc).__name__}: {exc}"))


def guard(fn, *args, **kwargs):
    """Run fn; on failure report it and return None."""
    try:
        return fn(*args, **kwargs)
    except Exception as e:                      # noqa: BLE001 - this is the one place that catches everything
        report(e)
        return None


def guard_ok(fn, *args, **kwargs) -> bool:
    """Like guard, for calls that return nothing: True when it worked."""
    try:
        fn(*args, **kwargs)
        return True
    except Exception as e:                      # noqa: BLE001
        report(e)
        return False


def guarded(fn):
    @functools.wraps(fn)
    def wrapper(*args, **kwargs):
        return guard(fn, *args, **kwargs)
    return wrapper


def install():
    """Report exceptions that escape Qt slots instead of letting them vanish into the console."""
    previous = sys.excepthook

    def hook(kind, exc, tb):
        if issubclass(kind, KeyboardInterrupt):
            return previous(kind, exc, tb)
        try:
            report(exc)
        except Exception:
            previous(kind, exc, tb)
    sys.excepthook = hook


attempt = guard_ok
