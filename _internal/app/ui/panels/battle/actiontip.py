"""The action bar's hover card: shown almost at once (Qt's own tooltips wait), small and easy to scan - the icon, name
and what it costs, the generic facts (level and school, range, area, duration...), the roll, a short summary, and why
it can't be used right now."""
import html
from typing import Optional

from PySide6.QtCore import QPoint, Qt, QTimer
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import QApplication, QFrame, QLabel, QVBoxLayout, QWidget

from ....core.i18n import tr

COST = {"action": ("Action", "#4ade80"), "attack": ("Action", "#4ade80"), "multi": ("Action", "#4ade80"),
        "bonus": ("Bonus action", "#fbbf24"), "reaction": ("Reaction", "#c084fc"), "free": ("Free", "#8b93a3"),
        "legendary": ("Legendary", "#f472b6"), "move": ("Movement", "#8b93a3"), "long": ("Longer than a turn", "#f87171"),
        "on_hit": ("On hit", "#c084fc")}


class ActionTip(QFrame):
    def __init__(self):
        super().__init__(None, Qt.ToolTip | Qt.FramelessWindowHint)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setObjectName("actiontip")
        self.setStyleSheet("#actiontip { background: #161a21; border: 1px solid #3a4152; border-radius: 6px; }")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(9, 7, 9, 7)
        self.text = QLabel()
        self.text.setTextFormat(Qt.RichText)
        self.text.setWordWrap(True)
        self.text.setFixedWidth(290)
        lay.addWidget(self.text)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.timeout.connect(self._show_now)
        self.anchor: Optional[QWidget] = None

    def card(self, item: dict) -> str:
        from ....services.battle import icons
        info = item.get("info") or {}
        kind = (item.get("cost") or "action").split(":")[0]
        cost, color = COST.get(kind, (kind, "#8b93a3"))
        if item.get("kind") == "spell":
            color = "#c084fc"
        pic = icons.path(item.get("icon")) if item.get("icon") else None
        img = f"<img src='{html.escape(pic)}' width='22' height='22'>&nbsp;" if pic else ""
        uses = f" · {html.escape(str(item['uses']))}" if item.get("uses") not in (None, "") else ""
        out = [f"<table width='100%' cellspacing='0' cellpadding='0'><tr><td>{img}<b style='font-size:13px'>{html.escape(tr(item['name']))}</b></td>"
               f"<td align='right'><span style='color:{color}'>{html.escape(tr(cost))}</span>"
               f"<span style='color:#8b93a3'>{uses}</span></td></tr></table>"]
        if info.get("tags"):
            out.append(f"<div style='color:#8b93a3; font-size:11px'>{html.escape(' · '.join(tr(t) for t in info['tags']))}</div>")
        if info.get("roll"):
            out.append(f"<div style='color:#a5b4fc; font-size:12px'>{html.escape(info['roll'])}</div>")
        if info.get("text"):
            out.append(f"<div style='color:#cfd4e0; font-size:11.5px; margin-top:3px'>{html.escape(tr(info['text']))}</div>")
        if kind == "on_hit":
            note = tr("Readied: the next hit asks whether to cast it (the slot is spent then). Click again to let it go.") if item.get("readied") \
                else tr("Click to ready it: nothing is spent until a hit lands and you choose to cast it.")
            out.append(f"<div style='color:#c084fc; font-size:11.5px; margin-top:3px'>{html.escape(note)}</div>")
        if item.get("why"):
            out.append(f"<div style='color:#f87171; font-size:11.5px; margin-top:3px'>⛔ {html.escape(tr(item['why']))}</div>")
        if item.get("hotkey"):                             # the map's play bar: number keys pick the first nine
            out.append(f"<div style='color:#8b93a3; font-size:11px; margin-top:3px' align='right'>{html.escape(tr('Key {0}', item['hotkey']))}</div>")
        return "".join(out)

    def show_for(self, anchor: QWidget, item: dict):
        self.anchor = anchor
        self.text.setText(self.card(item))
        self.adjustSize()
        self.timer.start(60)

    def _show_now(self):
        if not self.anchor or not self.anchor.isVisible() or not self.anchor.underMouse():
            return
        a = self.anchor.mapToGlobal(QPoint(0, 0))
        screen = (QApplication.screenAt(QCursor.pos()) or QApplication.primaryScreen()).availableGeometry()
        x = min(max(screen.left() + 4, a.x() - 4), screen.right() - self.width() - 4)
        y = a.y() - self.height() - 6
        if y < screen.top():
            y = a.y() + self.anchor.height() + 6
        self.move(x, y)
        self.show()
        self.raise_()

    def hide_for(self, anchor: QWidget):
        if anchor is self.anchor:
            self.timer.stop()
            self.hide()
            self.anchor = None


_tip: Optional[ActionTip] = None


def action_tip() -> ActionTip:
    global _tip
    if _tip is None:
        _tip = ActionTip()
    return _tip
