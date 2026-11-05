"""Read-only rich text for stat blocks, rules entries and sheet texts.

The services produce plain text with light markdown: **bold**, *italic*, line breaks, '• ' bullets. TextView shows it
nicely; `to_html` is there for labels and tooltips that want the same look.
"""
import html
import re

from PySide6.QtCore import QEvent, QObject
from PySide6.QtWidgets import QTextBrowser, QToolTip

from ..theme import COLORS


def to_html(text: str) -> str:
    """Plain text with **bold** / *italic* marks -> HTML (escaped, line breaks kept)."""
    t = html.escape(text or "")
    t = re.sub(r"\*\*(.+?)\*\*", r"<b>\1</b>", t)
    t = re.sub(r"(?<![\w*])\*(?!\s)(.+?)(?<!\s)\*(?![\w*])", r"<i>\1</i>", t)
    t = re.sub(r"`(.+?)`", r"<code>\1</code>", t)
    return t.replace("\n", "<br>")


class TextView(QTextBrowser):
    """Shows text with **bold** marks; the first line can be a heading."""

    def __init__(self, text: str = "", heading_first_line: bool = False, mono: bool = False, parent=None):
        super().__init__(parent)
        self.setOpenExternalLinks(True)
        self.heading_first_line = heading_first_line
        self.mono = mono
        self.document().setDefaultStyleSheet(
            f"b {{ color: {COLORS['text']}; }} h3 {{ color: {COLORS['accent']}; margin: 0 0 4px 0; }} "
            f"code {{ font-family: Consolas; }}")
        if text:
            self.set_text(text)

    def set_text(self, text: str):
        text = text or ""
        if self.heading_first_line and text:
            first, _, rest = text.partition("\n")
            body = f"<h3>{html.escape(first)}</h3>{to_html(rest)}"
        else:
            body = to_html(text)
        if self.mono:
            body = f"<pre style='font-family: Consolas; white-space: pre-wrap'>{body.replace('<br>', chr(10))}</pre>"
        self.setHtml(body)

    def text(self) -> str:
        return self.toPlainText()


def entry_tip(kind: str, ident: str, limit: int = 1800) -> str:
    """A rules entry as a hover text: its name, its book and its rules (long ones cut short)."""
    from ...core.i18n import tr
    from ...rules.describe import describe
    try:
        d = describe(kind, ident)
    except Exception:
        return ""
    text = tr(d["text"])
    if len(text) > limit:
        text = text[:limit].rsplit("\n", 1)[0] + "\n…"
    book = tr(d["book"]) + (" · " + tr("your rulebook") if d["homebrew"] else "")
    return (f"<qt><b style='color:{COLORS['accent']}'>{to_html(tr(d['title']))}</b> "
            f"<span style='color:{COLORS['dim']}'>{to_html(book)}</span><br>{to_html(text)}</qt>")


class HoverTips(QObject):
    """Hover texts for the rows of a list or tree, made when the mouse first rests on a row (not for every row up
    front): HoverTips(tree, lambda item: html). An empty text shows nothing."""

    def __init__(self, view, make):
        super().__init__(view)
        self.view, self.make, self.made = view, make, {}
        view.viewport().installEventFilter(self)

    def forget(self):
        self.made.clear()

    def eventFilter(self, obj, e):
        if e.type() != QEvent.ToolTip:
            return False
        it = self.view.itemAt(e.pos())
        if it is None:
            QToolTip.hideText()
            return True
        key = id(it)
        if key not in self.made:
            try:
                self.made[key] = self.make(it) or ""
            except Exception:
                self.made[key] = ""
        if len(self.made) > 500:
            self.made.clear()
        if self.made.get(key):
            QToolTip.showText(e.globalPos(), self.made[key], self.view.viewport(), self.view.visualItemRect(it))
        else:
            QToolTip.hideText()
        return True
