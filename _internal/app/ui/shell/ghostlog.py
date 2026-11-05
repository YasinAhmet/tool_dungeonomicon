"""The ghost log: the table's feed, the battle log and the console as a see-through strip over the bottom of the
Battle map (or of the biggest window when the map isn't open), instead of a window of its own.

Closed, new table lines (chat, rolls, your commands' answers) float up there for a few seconds and fade (clicks go
through to the map); the battle's lines stay in the Battle filter. Enter (when no text box
has the keyboard) opens it: the history with All / Table / Battle / Console filters, and a line that

    says something to the players          Hello there        (the table chat, as the DM)
    rolls dice                             2d6+3, d20, 4d6-1   (also: d20 adv / d20 dis)
    runs a text command                    /hp Ilya -5         (/help lists them; Tab completes, Up / Down walk back)

Escape, or Enter on an empty line, closes it.
"""
import html
import re
import time
from collections import deque
from typing import Optional
from urllib.parse import quote, unquote

from PySide6.QtCore import QEasingCurve, QPoint, QPropertyAnimation, QRect, Qt, QTimer
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import (QAbstractSpinBox, QComboBox, QCompleter, QFrame, QGraphicsOpacityEffect, QHBoxLayout,
                               QLabel, QLineEdit, QPlainTextEdit, QTextBrowser, QTextEdit, QToolTip, QVBoxLayout, QWidget)

from ...core import events
from ...core.i18n import tr
from ...core.runtime import rt
from ...rules import engine as E
from ...rules.data import rules
from ...rules.describe import UnknownContent, describe
from ...services.battle.icons import CONDITIONS
from .. import dialogs
from ..errors import guard
from ..theme import COLORS
from ..widgets.common import button
from ..widgets.text import to_html

KEEP = 600
PEEK_LINES = 5
PEEK_SECONDS = 7
FILTERS = (("all", "All"), ("table", "Table"), ("battle", "Battle"), ("console", "Console"))
DICE = re.compile(r"^\s*(\d*d\d+|\d+)(\s*[+-]\s*(\d*d\d+|\d+))*\s*$", re.I)
D20_MODE = re.compile(r"^\s*d20\s*([+-]\s*\d+)?\s+(adv|advantage|dis|disadvantage)\s*$", re.I)
BATTLE_MARKS = (("CRITICAL HIT", "good"), ("natural 20", "good"), ("— miss", "dim"), ("defeated", "bad"), ("takes", "warn"),
                ("heals", "good"), ("turn", "accent"), ("round", "accent"))
CONSOLE_MARKS = (("[ERROR]", "bad"), ("❌", "bad"), ("[WARN]", "warn"), ("⚠", "warn"), ("[ADMIN]", "accent"),
                 ("[SUCCESS]", "good"), ("✅", "good"))


ICONS = {"roll": "", "xp": "", "chat": "💬 ", "system": "", "private": ""}
ITEM = "#e8c77e"                       # an item's name in a line (`Potion of Healing`), as on the portal
_CODE = re.compile(r"<code>(.+?)</code>")
_BOLD = re.compile(r"<b>([^<]+)</b>")


def _links(text: str) -> str:
    """`Items` (gold) and condition names become links: their rules on hover."""
    text = _CODE.sub(lambda m: f"<a href='item:{quote(html.unescape(m.group(1)))}' style='color:{ITEM}; text-decoration:none'>"
                               f"{m.group(1)}</a>", text)
    conds = {tr(n): n for n in CONDITIONS}
    return _BOLD.sub(lambda m: f"<a href='cond:{quote(conds[m.group(1)])}' style='color:{COLORS['text']}; text-decoration:none'>"
                               f"<b>{m.group(1)}</b></a>" if m.group(1) in conds else m.group(0), text)


def _tip(link: str) -> str:
    """The hover text of a link in the feed: an item's or a condition's rules."""
    kind, _, name = link.partition(":")
    name = unquote(name)
    if kind == "item":
        try:
            d = describe("items", name)
        except UnknownContent:
            return ""
        body = d["text"][len(d["title"]):].lstrip("\n") if d["text"].startswith(d["title"]) else d["text"]   # (it starts with the name)
        return f"**{tr(d['title'])}**\n{tr(body)[:900]}"
    if kind == "cond":
        text = (rules.conditions.get(name) or {}).get("text", "")
        return f"**{tr(name)}**" + (f"\n{tr(text)}" if text else "")
    return ""


def typing_in(w: Optional[QWidget]) -> bool:
    """True when the keyboard is in a text box (its Enter is its own)."""
    if w is None:
        return False
    if isinstance(w, QLineEdit) or isinstance(w, QAbstractSpinBox):
        return True
    if isinstance(w, (QTextEdit, QPlainTextEdit)):
        return not w.isReadOnly()
    if isinstance(w, QComboBox):
        return w.isEditable()
    return False


class GhostLog(QFrame):
    def __init__(self, window):
        super().__init__(window)
        self.window = window
        self.lines: deque = deque(maxlen=KEEP)               # (source, html, when)
        self.console: deque = deque(maxlen=KEEP)
        self.show_only = "all"
        self.opened = False
        self.history, self.hpos = [], None
        self.feed_id = 0
        self.battle_seen: list = []
        self.log_seen = max(0, rt().log_count - KEEP)
        self.setObjectName("ghost")
        self.setAttribute(Qt.WA_StyledBackground, True)

        # ---- closed: the latest lines, fading
        self.peek = QLabel()
        self.peek.setTextFormat(Qt.RichText)
        self.peek.setWordWrap(True)
        self.peek.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.peek.setStyleSheet("QLabel { background: rgba(10, 12, 18, 150); border-radius: 6px; padding: 4px 8px; }")
        # ---- open: the history, its filters, the line
        self.filters = {}
        top = QHBoxLayout()
        top.setSpacing(2)
        for key, text in FILTERS:
            b = button(tr(text), lambda k=key: self.set_filter(k), kind="flat", checkable=True)
            b.setFocusPolicy(Qt.NoFocus)
            self.filters[key] = b
            top.addWidget(b)
        top.addStretch(1)
        hint = QLabel(tr("Enter: say it · 2d6+3: roll · /command (/help) · Esc: close"))
        hint.setProperty("role", "dim")
        top.addWidget(hint)
        wipe = button("🗑", self._clear_feed, kind="flat", width=26, tip=tr("Clear the table feed for everyone"))
        wipe.setFocusPolicy(Qt.NoFocus)
        top.addWidget(wipe)
        close = button("×", self.close_log, kind="flat", width=24, tip=tr("Close (Esc)"))
        close.setFocusPolicy(Qt.NoFocus)
        top.addWidget(close)
        self.view = QTextBrowser()
        self.view.setOpenLinks(False)
        self.view.setFocusPolicy(Qt.NoFocus)
        self.view.highlighted.connect(self._hover)
        self.view.setStyleSheet("QTextBrowser { background: transparent; border: none; }")
        self.entry = QLineEdit()
        self.entry.setPlaceholderText(tr("Say something to the table, roll (2d6+3, d20 adv), or type a /command"))
        self.entry.returnPressed.connect(lambda: guard(self._send))
        self.entry.installEventFilter(self)
        comp = QCompleter(guard(rt().command_processor.commands) or [], self.entry)
        comp.setCaseSensitivity(Qt.CaseInsensitive)
        self.entry.setCompleter(comp)
        self.panel = QWidget()
        self.panel.setObjectName("ghostpanel")
        self.panel.setStyleSheet(f"#ghostpanel {{ background: rgba(14, 16, 24, 228); border: 1px solid {COLORS['accent']}; "
                                 f"border-radius: 6px; }}")
        box = QVBoxLayout(self.panel)
        box.setContentsMargins(6, 4, 6, 6)
        box.setSpacing(3)
        box.addLayout(top)
        box.addWidget(self.view, 1)
        box.addWidget(self.entry)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.peek)
        lay.addWidget(self.panel)
        self.panel.hide()
        self.fade = QGraphicsOpacityEffect(self)
        self.fade.setOpacity(1.0)
        self.setGraphicsEffect(self.fade)
        self.anim = QPropertyAnimation(self.fade, b"opacity", self)
        self.anim.setDuration(900)
        self.anim.setEasingCurve(QEasingCurve.InQuad)
        self.anim.finished.connect(lambda: self.hide() if not self.opened and self.fade.opacity() < 0.05 else None)
        self.peek_timer = QTimer(self, singleShot=True, interval=PEEK_SECONDS * 1000)
        self.peek_timer.timeout.connect(self._fade_out)
        self.follow = QTimer(self, interval=400)                 # keeps to the bottom of the map as docks move
        self.follow.timeout.connect(self.place)
        self.hide()
        self.set_filter("all", render=False)
        self._read(quiet=True)
        bus = rt().bus
        self._unsub = [bus.subscribe(events.FEED, lambda: guard(self._read)),
                       bus.subscribe(events.BATTLE, lambda: guard(self._read)),
                       bus.subscribe(events.LOG, lambda: guard(self._read_console))]
        self.destroyed.connect(lambda *_: [u() for u in self._unsub])

    # ------------------------------------------------------------------ what comes in
    def _read(self, quiet: bool = False):
        new = []
        for e in rt().feed.since(self.feed_id):
            self.feed_id = e["id"]
            dm = e.get("dm")
            who = (f"<b style='color:{COLORS['warn'] if dm else COLORS['accent']}'>{'👑 ' if dm else ''}"
                   f"{html.escape(e['who'])}</b> " if e.get("who") else "")
            text = html.escape(e["text"]) if e["kind"] == "chat" else to_html(tr(e["text"]))
            text = ICONS.get(e["kind"], "") + _links(text)
            new.append(("table", f"<span style='color:{COLORS['dim']}'>{e['time']}</span> {who}{text}"))
        lines = guard(rt().battle.log_lines) or []
        old = self.battle_seen
        fresh = lines[len(old):] if old and lines[:len(old)] == old else ([] if lines == old else
                                                                          lines if not old else lines[-3:])
        self.battle_seen = lines
        for ln in fresh:
            colour = next((COLORS[k] for word, k in BATTLE_MARKS if word in ln), COLORS["text"])
            new.append(("battle", f"<span style='color:{colour}'>⚔ {html.escape(tr(ln))}</span>"))
        now = time.monotonic()
        for source, text in new:
            self.lines.append((source, text, now))
        if new and not quiet:
            self._changed()

    def _read_console(self):
        for line in rt().log_since(self.log_seen):
            colour = next((COLORS[k] for tag, k in CONSOLE_MARKS if tag in line[:24]), COLORS["dim"])
            self.console.append(f"<span style='color:{colour}'>{html.escape(tr(line))}</span>")
        self.log_seen = rt().log_count
        if self.opened and self.show_only == "console":
            self._render()

    def say(self, text: str, colour: str = ""):
        """A line only the DM sees (a command's answer, a roll's breakdown)."""
        self.lines.append(("mine", f"<i style='color:{colour or COLORS['dim']}'>{to_html(text)}</i>", time.monotonic()))
        self._changed()

    def _changed(self):
        if self.opened:
            self._render()
        else:
            self._peek()

    # ------------------------------------------------------------------ showing
    def _shown(self) -> list:
        if self.show_only == "console":
            return list(self.console)
        if self.show_only == "table":
            return [t for s, t, _w in self.lines if s in ("table", "mine")]
        if self.show_only == "battle":
            return [t for s, t, _w in self.lines if s == "battle"]
        return [t for _s, t, _w in self.lines]

    def _render(self):
        bar = self.view.verticalScrollBar()
        rows = self._shown()[-300:]
        self.view.setHtml("".join(f"<div>{t}</div>" for t in rows) or
                          f"<span style='color:{COLORS['dim']}'>{html.escape(tr('Nothing yet.'))}</span>")
        bar.setValue(bar.maximum())

    def _peek(self):
        """Closed: the latest lines float up and fade after a few seconds."""
        if self._anchor() is None:
            return
        now = time.monotonic()
        recent = [t.split("<br>", 1)[0] + (" …" if "<br>" in t else "")       # (a long answer: its first line)
                  for s, t, w in self.lines if now - w < PEEK_SECONDS and s in ("table", "mine")][-PEEK_LINES:]
        if not recent:
            return
        self.peek.setText("<br>".join(recent))
        self.peek.show()
        self.panel.hide()
        self.setAttribute(Qt.WA_TransparentForMouseEvents, True)
        self.anim.stop()
        self.fade.setOpacity(1.0)
        self.place()
        self.show()
        self.raise_()
        self.follow.start()
        self.peek_timer.start()

    def _fade_out(self):
        if self.opened:
            return
        self.anim.stop()
        self.anim.setStartValue(self.fade.opacity())
        self.anim.setEndValue(0.0)
        self.anim.start()

    def open_log(self, show_only: Optional[str] = None):
        if show_only:
            self.set_filter(show_only, render=False)
        self.opened = True
        self._read_console()
        self.peek_timer.stop()
        self.anim.stop()
        self.fade.setOpacity(1.0)
        self.setAttribute(Qt.WA_TransparentForMouseEvents, False)
        self.peek.hide()
        self.panel.show()
        self.place()
        self.show()
        self.raise_()
        self.follow.start()
        self._render()
        self.entry.setFocus()

    def close_log(self):
        self.opened = False
        self.panel.hide()
        self.hide()
        self.follow.stop()
        self.entry.clearFocus()
        target = self._anchor()
        if target is not None:
            target.setFocus()

    def toggle(self):
        self.close_log() if self.opened else self.open_log()

    def set_filter(self, key: str, render: bool = True):
        self.show_only = key
        for k, b in self.filters.items():
            b.setChecked(k == key)
        if render:
            self._render()
            self.entry.setFocus()

    # ------------------------------------------------------------------ where it sits
    def _anchor(self) -> Optional[QWidget]:
        """The Battle map (its map, under the bars) when it's in sight, else the biggest window in sight."""
        docks = list(getattr(self.window.host, "docks", {}).values())
        seen = [d for d in docks if d.panel.isVisible() and not d.isFloating()]
        for d in seen:
            if d.spec.id == "battle.map":
                return getattr(d.panel, "host", None) or d.panel
        best = max(seen, key=lambda d: d.panel.width() * d.panel.height(), default=None)
        return best.panel if best is not None else self.window.centralWidget()

    def place(self):
        a = self._anchor()
        if a is None or not a.isVisible():
            if not self.opened:
                self.hide()
            return
        top_left = a.mapTo(self.window, QPoint(0, 0))
        r = QRect(top_left, a.size())
        w = max(260, min(r.width() - 24, 900))
        x = r.left() + max(12, (r.width() - w) // 2) if r.width() > 924 else r.left() + 12
        if self.opened:
            h = max(160, min(int(r.height() * 0.55), 400))
        else:
            self.peek.setFixedWidth(w)
            h = self.peek.heightForWidth(w) if self.peek.hasHeightForWidth() else self.peek.sizeHint().height()
            h = max(24, min(h + 4, 200))
        y = max(0, r.bottom() - h - 10)
        self.setGeometry(x, y, w, h)

    # ------------------------------------------------------------------ the line
    def _send(self):
        text = self.entry.text().strip()
        if not text:
            self.close_log()
            return
        if not self.history or self.history[-1] != text:
            self.history.append(text)
        self.hpos = None
        self.entry.clear()
        d20 = D20_MODE.match(text)
        if text.startswith("/"):
            rt().log_action(f"Command: {text}")
            result = guard(rt().command_processor.process, text)
            self.say(f"› {text}" + (f"\n{tr(result)}" if result else ""),
                     COLORS["bad"] if (result or "").startswith(("❌", "⚠")) else "")
        elif d20:
            bonus = int((d20.group(1) or "0").replace(" ", ""))
            mode = "advantage" if d20.group(2).lower().startswith("adv") else "disadvantage"
            total, rolls = E.roll_d20(bonus, mode)
            rt().log(f"[LOG] DM rolled d20 with {mode}: {rolls} => {total}")
            self.say(tr("🎲 d20 {0}: {1} → {2}", tr(mode), ", ".join(map(str, rolls)), total), COLORS["good"])
        elif DICE.match(text) and "d" in text.lower():
            r = guard(rt().dice.roll, text.replace(" ", ""), tr("DM"))
            if r:
                self.say(f"🎲 {text} = {r.total}" + ("" if r.plain else f"  ({r.breakdown})"), COLORS["good"])
        else:
            guard(rt().feed.say, tr("DM"), text, True)

    def eventFilter(self, obj, e):
        if obj is self.entry and e.type() == e.Type.KeyPress:
            if e.key() == Qt.Key_Escape:
                self.close_log()
                return True
            if e.key() in (Qt.Key_Up, Qt.Key_Down) and self.history and not self.entry.completer().popup().isVisible():
                if e.key() == Qt.Key_Up:
                    self.hpos = len(self.history) - 1 if self.hpos is None else max(0, self.hpos - 1)
                    self.entry.setText(self.history[self.hpos])
                elif self.hpos is not None:
                    self.hpos += 1
                    if self.hpos >= len(self.history):
                        self.hpos = None
                        self.entry.clear()
                    else:
                        self.entry.setText(self.history[self.hpos])
                return True
        return super().eventFilter(obj, e)

    def _clear_feed(self):
        if dialogs.confirm(self.window, tr("Clear the table feed for everyone?")):
            guard(rt().feed.clear)
            self.lines = deque(((s, t, w) for s, t, w in self.lines if s != "table"), maxlen=KEEP)
            self._render()

    def _hover(self, url):
        tip = _tip(url.toString())
        if tip:
            QToolTip.showText(QCursor.pos(), f"<qt>{to_html(tip)}</qt>", self.view)
        else:
            QToolTip.hideText()
