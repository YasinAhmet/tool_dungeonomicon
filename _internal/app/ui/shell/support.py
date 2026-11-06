"""The two links at the right end of the main toolbar: Donate (Buy Me a Coffee) and Community (the Discord server).

They are part of the window itself, not a feature module, so they are always there. The icons are drawn from small
SVGs kept here, so they show even with no icon module installed.
"""
from PySide6.QtCore import QByteArray, QRectF, QSize, Qt, QUrl
from PySide6.QtGui import QDesktopServices, QGuiApplication, QIcon, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import QWidget

from ...core.i18n import tr
from ..theme import COLORS
from ..widgets.common import row, tool_button

DONATE_URL = "https://buymeacoffee.com/yakhmet"
COMMUNITY_URL = "https://discord.gg/yPhM2ZaxQe"
ICON = 20

# A cup of coffee with steam over it.
_CUP = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24">
<path d="M8 2.5c-.9 1 .9 2 0 3M11.5 2.5c-.9 1 .9 2 0 3M15 2.5c-.9 1 .9 2 0 3" fill="none" stroke="{dim}"
 stroke-width="1.3" stroke-linecap="round"/>
<path d="M17.5 10.5h1.2a2.8 2.8 0 0 1 0 5.6h-1.9" fill="none" stroke="#ffdd00" stroke-width="2"/>
<path d="M4 8h14l-1.3 10.2A3 3 0 0 1 13.7 21H8.3a3 3 0 0 1-3-2.8z" fill="#ffdd00"/>
<path d="M5.2 11.5h11.6" stroke="#0f1115" stroke-width="1" opacity=".35"/>
</svg>"""

# Discord's mark, in its own blurple.
_DISCORD = """<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path fill="#5865f2" d="M20.317 4.3698a19.7913
19.7913 0 0 0-4.8851-1.5152.0741.0741 0 0 0-.0785.0371c-.211.3753-.4447.8648-.6083 1.2495-1.8447-.2762-3.68-.2762-5.4868
0-.1636-.3933-.4058-.8742-.6177-1.2495a.077.077 0 0 0-.0785-.037 19.7363 19.7363 0 0 0-4.8852 1.515.0699.0699 0 0
0-.0321.0277C.5334 9.0458-.319 13.5799.0992 18.0578a.0824.0824 0 0 0 .0312.0561c2.0528 1.5076 4.0413 2.4228 5.9929
3.0294a.0777.0777 0 0 0 .0842-.0276c.4616-.6304.8731-1.2952 1.226-1.9942a.076.076 0 0 0-.0416-.1057c-.6528-.2476-1.2743-.5495-1.8722-.8923a.077.077
0 0 1-.0076-.1277c.1258-.0943.2517-.1923.3718-.2914a.0743.0743 0 0 1 .0776-.0105c3.9278 1.7933 8.18 1.7933 12.0614
0a.0739.0739 0 0 1 .0785.0095c.1202.099.246.1981.3728.2924a.077.077 0 0 1-.0066.1276 12.2986 12.2986 0 0 1-1.873.8914.0766.0766
0 0 0-.0407.1067c.3604.698.7719 1.3628 1.225 1.9932a.076.076 0 0 0 .0842.0286c1.961-.6067 3.9495-1.5219 6.0023-3.0294a.077.077
0 0 0 .0313-.0552c.5004-5.177-.8382-9.6739-3.5485-13.6604a.061.061 0 0 0-.0312-.0286zM8.02 15.3312c-1.1825
0-2.1569-1.0857-2.1569-2.419 0-1.3332.9555-2.4189 2.157-2.4189 1.2108 0 2.1757 1.0952 2.1568 2.419 0 1.3332-.9555
2.4189-2.1569 2.4189zm7.9748 0c-1.1825 0-2.1569-1.0857-2.1569-2.419 0-1.3332.9554-2.4189 2.1569-2.4189 1.2108 0
2.1757 1.0952 2.1568 2.419 0 1.3332-.946 2.4189-2.1568 2.4189z"/></svg>"""


def _icon(svg: str) -> QIcon:
    ratio = QGuiApplication.primaryScreen().devicePixelRatio() if QGuiApplication.primaryScreen() else 1.0
    px = QPixmap(int(ICON * ratio), int(ICON * ratio))
    px.fill(Qt.transparent)
    p = QPainter(px)
    p.setRenderHint(QPainter.Antialiasing)
    QSvgRenderer(QByteArray(svg.encode("utf-8"))).render(p, QRectF(0, 0, px.width(), px.height()))
    p.end()
    px.setDevicePixelRatio(ratio)
    return QIcon(px)


def _link(svg: str, url: str, tip: str):
    b = tool_button("", lambda: QDesktopServices.openUrl(QUrl(url)), tip=tip)
    b.setIcon(_icon(svg))
    b.setIconSize(QSize(ICON, ICON))
    b.setCursor(Qt.PointingHandCursor)
    return b


def support_links() -> QWidget:
    w = QWidget()
    w.setObjectName("support-links")
    w.setStyleSheet("#support-links { background: transparent; }")         # the toolbar's own colour behind the icons
    w.setLayout(row(_link(_CUP.format(**COLORS), DONATE_URL, tr("Donate")),
                    _link(_DISCORD, COMMUNITY_URL, tr("Community")), spacing=2, margins=0))
    return w
