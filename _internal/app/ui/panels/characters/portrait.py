"""The portrait importer: a picture (a file, the clipboard, one dropped on it or one from the portrait library,
core/portraits.library) cut to a circle and given a token border of the DM's choice. It becomes the character's
token on the battle maps (the players' map too) and its picture on the sheet and in the roster.

    edit_portrait(parent, name)                          # an existing character: saved through rt().characters.set_portrait
    choice = open_portrait_editor(parent, race, cls, current)   # None: cancelled; {}: automatic; else what set_portrait takes
    pm = portrait_pixmap(path, framed, 40)               # a round picture for lists and headers
    import_portraits(parent) / export_portraits(parent)  # portrait modules in and out (services/portrait_packs.py)
"""
import math
import os
from typing import Dict, Optional, Tuple

from PySide6.QtCore import QBuffer, QByteArray, QIODevice, QPointF, QRectF, QSize, Qt, QTimer, Signal
from PySide6.QtGui import (QColor, QConicalGradient, QGuiApplication, QIcon, QImage, QKeySequence, QPainter, QPainterPath,
                           QPen, QPixmap, QShortcut)
from PySide6.QtWidgets import (QColorDialog, QDialog, QFileDialog, QListView, QListWidget, QListWidgetItem, QSizePolicy,
                               QSlider, QWidget)

from ....core import portraits
from ....core.i18n import tr
from ....core.runtime import rt
from ....services import portrait_packs
from ....services.characters import view
from ... import dialogs, notify
from ...dialogs import Dialog
from ...errors import guard
from ...registry import action
from ...theme import COLORS
from ...widgets.common import button, col, combo, label, line_edit, row, stretch, title

OUT = 256                                                # the saved token's size in pixels
PC_RING = "#4f8cff"                                      # the battle's ring for player characters (battle/common.SIDE)
BORDERS = (("gold", "Gold"), ("silver", "Silver"), ("bronze", "Bronze"), ("iron", "Iron"), ("wood", "Wood"),
           ("obsidian", "Obsidian"), ("colour", "A colour of my choice"), ("side", "The battle's ring (side colour)"),
           ("none", "No border"))
# the colours round a ring, from its top left: dark, light, mid, light, dark (a conical gradient shines like metal)
METALS = {"gold": ("#6b4e0e", "#f9e27d", "#a87b12", "#fff4b8", "#8d6a10"),
          "silver": ("#4b5563", "#f3f4f6", "#8b93a1", "#ffffff", "#5b6472"),
          "bronze": ("#4a2a12", "#e7a868", "#8a5226", "#f6cfa0", "#5e3517"),
          "iron": ("#22262c", "#8e96a3", "#3a4049", "#b8c0cc", "#2a2f36"),
          "wood": ("#3b2212", "#8b5a2b", "#5a3519", "#a87444", "#4a2b16"),
          "obsidian": ("#060609", "#4a4a66", "#121218", "#6c6c90", "#0b0b10")}
DEFAULT_BORDER = {"style": "gold", "width": 8, "color": "#8b2c2c"}
ICON = 80                                                # the gallery's portraits, in pixels
# the library's kind of portraits a class starts the gallery on
CLASS_KIND = {**dict.fromkeys(("fighter", "paladin", "ranger", "barbarian", "monk"), "warriors"),
              **dict.fromkeys(("wizard", "sorcerer", "warlock", "cleric", "druid", "bard", "artificer"), "casters"),
              "rogue": "rogues"}


# ---------------------------------------------------------------------- pictures
def to_png(img: QImage) -> bytes:
    data = QByteArray()
    buf = QBuffer(data)
    buf.open(QIODevice.WriteOnly)
    img.save(buf, "PNG")
    return bytes(data)


def _ring_colours(border: dict) -> Tuple[str, ...]:
    if border.get("style") == "colour":
        c = QColor(border.get("color") or DEFAULT_BORDER["color"])
        return tuple(x.name() for x in (c.darker(220), c.lighter(170), c.darker(130), c.lighter(145), c.darker(180)))
    return METALS.get(border.get("style"), METALS["gold"])


def render(inner: QImage, border: dict, size: int = OUT) -> QImage:
    """The finished token: the picture in a circle inside the border (transparent outside the circle). The 'side'
    style draws the battle's ring (border['ring'], blue for player characters), as the battle map will."""
    out = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
    out.fill(Qt.transparent)
    p = QPainter(out)
    p.setRenderHint(QPainter.Antialiasing)
    p.setRenderHint(QPainter.SmoothPixmapTransform)
    style = border.get("style", "gold")
    full = QRectF(1, 1, size - 2, size - 2)
    w = 0.0 if style == "none" else max(2, size // 14) if style == "side" else size * float(border.get("width", 8)) / 100
    hole = full.adjusted(w, w, -w, -w)
    clip = QPainterPath()
    clip.addEllipse(hole.adjusted(-0.5, -0.5, 0.5, 0.5))           # under the ring's inner edge: no gap shows
    p.setClipPath(clip)
    if inner and not inner.isNull():
        p.drawImage(hole, inner)
    p.setClipping(False)
    edge = max(1.0, size / 128)
    if w:
        ring = QPainterPath()
        ring.addEllipse(full)
        cut = QPainterPath()
        cut.addEllipse(hole)
        ring = ring.subtracted(cut)
        if style == "side":
            p.fillPath(ring, QColor(border.get("ring") or PC_RING))
        else:
            stops = _ring_colours(border)
            g = QConicalGradient(full.center(), 135)
            for i, c in enumerate(stops + stops[:1]):
                g.setColorAt(i / len(stops), QColor(c))
            p.fillPath(ring, g)
            p.setPen(QPen(QColor(255, 255, 255, 60), edge))           # a bright line along the ring: a bevel
            p.setBrush(Qt.NoBrush)
            p.drawEllipse(full.adjusted(w * .3, w * .3, -w * .3, -w * .3))
    p.setPen(QPen(QColor(0, 0, 0, 160), edge))
    p.setBrush(Qt.NoBrush)
    p.drawEllipse(full)
    if w:
        p.drawEllipse(hole)
    p.end()
    return out


_round: Dict[tuple, QPixmap] = {}


def portrait_pixmap(path: Optional[str], framed: bool, size: int, ring: str = PC_RING) -> QPixmap:
    """A character's round picture: a framed token as it is, any other picture cut round inside a ring."""
    key = (path, framed, size, ring)
    if key in _round:
        return _round[key]
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    img = QImage(path) if path else QImage()
    if img.isNull():
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(COLORS["raised"]))
        p.drawEllipse(QRectF(1, 1, size - 2, size - 2))
        p.end()
    elif framed:
        pm = QPixmap.fromImage(img.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation))
    else:
        side = min(img.width(), img.height())
        img = img.copy((img.width() - side) // 2, (img.height() - side) // 2, side, side)
        pm = QPixmap.fromImage(render(img.scaled(size * 2, size * 2, Qt.IgnoreAspectRatio, Qt.SmoothTransformation),
                                      {"style": "side", "ring": ring}, size))
    if len(_round) > 300:
        _round.clear()
    _round[key] = pm
    return pm


# ---------------------------------------------------------------------- the crop view
class CropView(QWidget):
    """The picture behind a round window: drag it to move it, the wheel zooms; a picture dropped on it replaces it."""
    changed = Signal()

    def __init__(self):
        super().__init__()
        self.setMinimumSize(300, 300)
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)
        self.setAcceptDrops(True)
        self.setCursor(Qt.OpenHandCursor)
        self.img: Optional[QImage] = None
        self.zoom = 1.0                                  # screen pixels per picture pixel
        self.center = QPointF()                          # the picture point under the circle's centre
        self.press: Optional[QPointF] = None

    def circle(self) -> QRectF:
        side = min(self.width(), self.height()) - 24
        return QRectF((self.width() - side) / 2, (self.height() - side) / 2, side, side)

    def min_zoom(self) -> float:
        return self.circle().width() / max(1, min(self.img.width(), self.img.height())) if self.img else 1.0

    def set_image(self, img: QImage):
        if img is None or img.isNull():
            return
        self.img = img.convertToFormat(QImage.Format_ARGB32)
        self.fit()

    def fit(self):
        if not self.img:
            return
        self.zoom = self.min_zoom()
        self.center = QPointF(self.img.width() / 2, self.img.height() / 2)
        self._moved()

    def look_at(self, fy: float):
        """Move the circle to this fraction of the picture's height (where a portrait's face usually is)."""
        if self.img:
            self.center = QPointF(self.img.width() / 2, self.img.height() * fy)
            self._moved()

    def set_zoom(self, z: float):
        if self.img:
            self.zoom = max(self.min_zoom(), min(z, self.min_zoom() * 8))
            self._moved()

    def _moved(self):
        """Keep the circle covered by the picture, then redraw."""
        if self.img:
            half = self.circle().width() / 2 / self.zoom
            self.center = QPointF(max(half, min(self.center.x(), self.img.width() - half)),
                                  max(half, min(self.center.y(), self.img.height() - half)))
        self.update()
        self.changed.emit()

    def crop(self, size: int = OUT) -> QImage:
        """The square around the circle, at `size` pixels."""
        out = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
        out.fill(Qt.transparent)
        if self.img:
            half = self.circle().width() / 2 / self.zoom
            p = QPainter(out)
            p.setRenderHint(QPainter.SmoothPixmapTransform)
            p.drawImage(QRectF(0, 0, size, size), self.img, QRectF(self.center.x() - half, self.center.y() - half, 2 * half, 2 * half))
            p.end()
        return out

    def paintEvent(self, _e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)
        p.fillRect(self.rect(), QColor(COLORS["bg"]))
        c = self.circle()
        if not self.img:
            p.setPen(QColor(COLORS["dim"]))
            p.drawText(self.rect().adjusted(30, 0, -30, 0), Qt.AlignCenter | Qt.TextWordWrap,
                       tr("Open a picture, paste one (Ctrl+V), drop one here or pick a portrait on the right."))
        else:
            p.save()
            p.translate(c.center())
            p.scale(self.zoom, self.zoom)
            p.translate(-self.center)
            p.drawImage(0, 0, self.img)
            p.restore()
            shade = QPainterPath()
            shade.addRect(QRectF(self.rect()))
            hole = QPainterPath()
            hole.addEllipse(c)
            p.fillPath(shade.subtracted(hole), QColor(0, 0, 0, 150))
        p.setPen(QPen(QColor(COLORS["accent"]), 1.5, Qt.DashLine))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(c)
        p.end()

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.img:
            self.set_zoom(self.zoom)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton and self.img:
            self.press = e.position()
            self.setCursor(Qt.ClosedHandCursor)

    def mouseMoveEvent(self, e):
        if self.press is not None:
            d = e.position() - self.press
            self.press = e.position()
            self.center -= QPointF(d.x() / self.zoom, d.y() / self.zoom)
            self._moved()

    def mouseReleaseEvent(self, _e):
        self.press = None
        self.setCursor(Qt.OpenHandCursor)

    def wheelEvent(self, e):
        self.set_zoom(self.zoom * 1.1 ** (e.angleDelta().y() / 120))

    def dragEnterEvent(self, e):
        m = e.mimeData()
        if m.hasImage() or any(u.isLocalFile() for u in m.urls()):
            e.acceptProposedAction()

    def dropEvent(self, e):
        m = e.mimeData()
        img = QImage(m.imageData()) if m.hasImage() else next((QImage(u.toLocalFile()) for u in m.urls() if u.isLocalFile()), QImage())
        if img.isNull():
            return
        self.set_image(img)
        e.acceptProposedAction()


# ---------------------------------------------------------------------- the window
class PortraitEditor(Dialog):
    def __init__(self, parent, race: str, cls: str, current: Optional[dict] = None, kind: str = ""):
        super().__init__(parent, tr("Portrait"), 1000, 680)
        self.choice: Optional[dict] = None
        current = current or {}
        self.border = dict(DEFAULT_BORDER, **(current.get("border") or {}))

        self.view = CropView()
        self.zoom = QSlider(Qt.Horizontal)
        self.zoom.setRange(0, 100)
        self.zoom.valueChanged.connect(lambda v: self.view.set_zoom(self.view.min_zoom() * 8 ** (v / 100)))
        self.view.changed.connect(self._redraw)
        left = col(self.view, row(label(tr("Zoom")), self.zoom, button(tr("Fit"), self.view.fit)),
                   row(button(tr("Open picture…"), self._open), button(tr("Paste"), self._paste,
                                                                      tip=tr("A picture copied to the clipboard (Ctrl+V)")),
                       stretch()),
                   label(tr("Drag the picture to place the face in the circle; the wheel zooms."), role="dim", wrap=True),
                   spacing=6)
        left.setStretch(0, 1)

        lib = portraits.library()
        counts = {k: sum(k in p["kinds"] for p in lib) for k, _t in portraits.KINDS}
        start_race = portraits.library_race(race)
        start_kind = next((k for k in (kind, CLASS_KIND.get((cls or "").strip().lower()), "adventurers") if k and sum(
            k in p["kinds"] and (not start_race or "race:" + start_race in p["tags"]) for p in lib) >= 8), "adventurers")
        if not any("adventurers" in p["kinds"] and "race:" + start_race in p["tags"] for p in lib):
            start_race = ""
        self.kind = combo([(tr("All portraits ({0})", len(lib)), "")] +
                          [(tr("{0} ({1})", tr(t), counts[k]), k) for k, t in portraits.KINDS if counts[k]],
                          current=start_kind, on_change=lambda _v: self._fill_gallery())
        self.race = combo([(tr("All races"), "")] + [(tr("{0} ({1})", tr(r.title()), n), r)
                                                     for r, n in portraits.library_races()],
                          current=start_race, on_change=lambda _v: self._fill_gallery())
        self.gender = combo([(tr("Anyone"), ""), (tr("Women"), "f"), (tr("Men"), "m")],
                            on_change=lambda _v: self._fill_gallery())
        self.search = line_edit(placeholder=tr("Search: a name, a race, a class, 'knight', 'lich'…"))
        self.typing = QTimer(self)
        self.typing.setSingleShot(True)
        self.typing.setInterval(250)
        self.typing.timeout.connect(self._fill_gallery)
        self.search.textChanged.connect(lambda _t: self.typing.start())
        self.count = label("", role="dim")
        self.words = {p["id"]: " ".join([p["name"]] + [w for t in p["tags"] for w in (t.split(":")[1],
                                                                                      tr(portraits.tag_label(t)))]).lower()
                      for p in lib}
        self.pending = []                                # library items still waiting for their picture
        self.icons = QTimer(self)
        self.icons.setInterval(0)
        self.icons.timeout.connect(self._load_icons)
        self.gallery = QListWidget()
        self.gallery.setViewMode(QListView.IconMode)
        self.gallery.setIconSize(QSize(ICON, ICON))
        self.gallery.setGridSize(QSize(ICON + 10, ICON + 10))
        self.gallery.setResizeMode(QListView.Adjust)
        self.gallery.setMovement(QListView.Static)
        self.gallery.setUniformItemSizes(True)
        self.gallery.setMinimumHeight(220)
        self.gallery.itemClicked.connect(self._pick)
        self.no_library = label(tr("No portrait module is installed: open a picture of your own, paste one or drop one "
                                   "on the circle - or bring portraits in with Import portraits… (a portrait module or "
                                   "a folder of pictures)."), role="dim", wrap=True)
        self._show_library(bool(lib))
        port = row(button(tr("Import portraits…"), self._import,
                          tip=tr("Add a portrait module (.dmmod) or a folder of pictures to the portrait library")),
                   button(tr("Export portraits…"), self._export,
                          tip=tr("Save portraits as a portrait module (.dmmod) to keep or share")), stretch())

        self.style = combo([(tr(t), k) for k, t in BORDERS], current=self.border["style"], on_change=self._style)
        self.colour = button(tr("Colour…"), self._pick_colour, tip=tr("The border's colour"))
        self.width = QSlider(Qt.Horizontal)
        self.width.setRange(3, 18)
        self.width.setValue(int(self.border["width"]))
        self.width.valueChanged.connect(lambda v: (self.border.__setitem__("width", v), self._redraw()))
        self.big, self.small = label(), label()
        for lab in (self.big, self.small):
            lab.setAlignment(Qt.AlignCenter)
        self.note = label("", role="dim", wrap=True)
        right = col(title(tr("Portraits")), row(self.kind, self.race, self.gender), row(self.search, self.count),
                    self.gallery, self.no_library, port,
                    title(tr("Token border")), self.style, row(label(tr("Width")), self.width, self.colour),
                    title(tr("Preview")), row(self.big, self.small, stretch()), self.note, spacing=6)
        right.setStretch(3, 1)
        lay = row(left, right, spacing=12)
        lay.setStretch(0, 5)
        lay.setStretch(1, 4)
        self.body.addLayout(lay, 1)

        auto = self.add_button(tr("Automatic portrait"), self._automatic)
        auto.setToolTip(tr("No picture of its own: its bestiary token") if kind == "monsters" else
                        tr("No picture of its own: the picture of its race"))
        self.buttons.insertWidget(0, auto)
        self.ok_cancel(tr("Use this portrait"), self._use)
        QShortcut(QKeySequence.Paste, self, self._paste)

        self._fill_gallery()
        start = current.get("inner") or (current.get("file") if not current.get("framed") else None)
        self.view.set_image(current.get("image") or (QImage(start) if start and os.path.isfile(start) else None))
        self._style(self.border["style"])

    # ------------------------------------------------------------------ sources
    def _show_library(self, shown: bool):
        for w in (self.kind, self.race, self.gender, self.search, self.count, self.gallery):
            w.setVisible(shown)
        self.no_library.setVisible(not shown)

    def _import(self):
        if import_portraits(self):
            lib = portraits.library()
            self.words = {p["id"]: " ".join([p["name"]] + [w for t in p["tags"] for w in (t.split(":")[1],
                                                                                          tr(portraits.tag_label(t)))]).lower()
                          for p in lib}
            self.kind.setCurrentIndex(0)
            self.race.setCurrentIndex(0)
            self._show_library(bool(lib))
            self._fill_gallery()

    def _export(self):
        shown = [self.gallery.item(i).data(Qt.UserRole + 1) for i in range(self.gallery.count())]
        export_portraits(self, [i for i in shown if i])

    def _fill_gallery(self):
        """The library's portraits of the chosen kind, race and gender; a search looks through all of them."""
        self.icons.stop()
        self.pending = []
        self.gallery.clear()
        words = self.search.text().lower().split()
        kind, race = ("", "") if words else (self.kind.currentData(), self.race.currentData())
        gender = self.gender.currentData()
        self.kind.setEnabled(not words)
        self.race.setEnabled(not words)
        blank = QIcon(portrait_pixmap(None, False, ICON))
        for p in portraits.library():
            if kind and kind not in p["kinds"] or race and "race:" + race not in p["tags"] or                     gender and p["gender"] != gender or any(w not in self.words[p["id"]] for w in words):
                continue
            it = QListWidgetItem(blank, "")
            what = [tr(portraits.tag_label(t)) for kind in ("race:", "class:", "creature:", "folk:") for t in p["tags"]
                    if t.startswith(kind) and t not in ("folk:npc", "folk:hero", "folk:companion")]
            packs = [tr(portraits.tag_label(t)) for t in p["tags"] if t.startswith("pack:")]
            it.setToolTip("\n".join(x for x in (p["name"], ", ".join(what), ", ".join(packs)) if x))
            it.setData(Qt.UserRole, p["path"])
            it.setData(Qt.UserRole + 1, p["id"])
            self.gallery.addItem(it)
            self.pending.append((it, p["thumb"]))
        self.count.setText(tr("{0} portraits", len(self.pending)))
        self.pending.reverse()
        self.icons.start()

    def _load_icons(self):
        """The library's thumbnails, a few at a time so a gallery of thousands opens at once."""
        for _ in range(min(60, len(self.pending))):
            it, thumb = self.pending.pop()
            it.setIcon(QIcon(portrait_pixmap(thumb, False, ICON, COLORS["border"])))
        if not self.pending:
            self.icons.stop()

    def _pick(self, it: QListWidgetItem):
        self.view.set_image(QImage(it.data(Qt.UserRole)))
        self.view.look_at(portraits.FACE)                # a library portrait: tall, the face in its upper part
    def _open(self):
        path, _f = QFileDialog.getOpenFileName(self, tr("Open picture"), "",
                                               tr("Pictures") + " (*.png *.jpg *.jpeg *.webp *.bmp *.gif)")
        if path:
            img = QImage(path)
            if img.isNull():
                self.show_problem(tr("That file isn't a picture this program can read."))
            else:
                self.show_problem("")
                self.view.set_image(img)

    def _paste(self):
        img = QGuiApplication.clipboard().image()
        if img.isNull():
            self.show_problem(tr("There is no picture on the clipboard."))
        else:
            self.show_problem("")
            self.view.set_image(img)

    # ------------------------------------------------------------------ border
    def _style(self, style):
        self.border["style"] = style
        self.colour.setVisible(style == "colour")
        self.width.setEnabled(style not in ("side", "none"))
        self.note.setText(tr("The battle map draws the ring in the side's colour (blue for player characters, grey "
                             "when down).") if style == "side" else
                          tr("The token keeps this border on the battle maps; it fades when the character is down."))
        self._redraw()

    def _pick_colour(self):
        c = QColorDialog.getColor(QColor(self.border["color"]), self, tr("Border colour"))
        if c.isValid():
            self.border["color"] = c.name()
            self._redraw()

    def _redraw(self):
        if self.view.img:
            z = self.view.zoom / max(1e-6, self.view.min_zoom())
            self.zoom.blockSignals(True)
            self.zoom.setValue(round(100 * (0 if z <= 1 else math.log(z, 8))))
            self.zoom.blockSignals(False)
        token = render(self.view.crop(), self.border)
        self.big.setPixmap(QPixmap.fromImage(token.scaled(150, 150, Qt.KeepAspectRatio, Qt.SmoothTransformation)))
        self.small.setPixmap(QPixmap.fromImage(token.scaled(44, 44, Qt.KeepAspectRatio, Qt.SmoothTransformation)))

    # ------------------------------------------------------------------ done
    def _automatic(self):
        self.choice = {}
        self.accept()

    def _use(self):
        if not self.view.img:
            self.show_problem(tr("Choose a picture first."))
            return
        inner = self.view.crop()
        framed = self.border["style"] != "side"
        self.choice = {"png": to_png(render(inner, self.border) if framed else inner), "framed": framed,
                       "inner": to_png(inner), "border": dict(self.border)}
        self.accept()


def open_portrait_editor(parent, race: str, cls: str, current: Optional[dict] = None, kind: str = "") -> Optional[dict]:
    """Modal. None when cancelled, {} for the automatic portrait, else {'png', 'framed', 'inner', 'border'}.
    current: the saved portrait (d['portrait']), or {'image': QImage, 'border': {...}} to go on with an unsaved one.
    kind: the library's kind of portraits to start on (portraits.KINDS, e.g. 'monsters')."""
    d = PortraitEditor(parent, race, cls, current, kind)
    return d.choice if d.exec() == QDialog.Accepted else None


def library_portrait(race: str, cls: str, gender: str = "", rnd=None) -> Optional[dict]:
    """A random library portrait of the race (else the class), never of the other gender ('m', 'f' or '' for either),
    made into a gold-bordered token as the editor would: what open_portrait_editor returns, or None without one."""
    import random
    lib = portraits.library()
    race_tag = "race:" + portraits.library_race(race) if portraits.library_race(race) else ""
    cls_tag = "class:" + (cls or "").strip().lower()

    def score(p) -> int:
        if gender and p["gender"] and p["gender"] != gender or "adventurers" not in p["kinds"]:
            return -1
        if race_tag and race_tag not in p["tags"] or not race_tag and cls_tag not in p["tags"]:
            return -1
        return 2 * (cls_tag in p["tags"]) + (bool(gender) and p["gender"] == gender)
    scored = [(score(p), p) for p in lib]
    best = max((s for s, _p in scored), default=-1)
    if best < 0:
        return None
    pick = (rnd or random).choice([p for s, p in scored if s == best])
    img = QImage(pick["path"])
    if img.isNull():
        return None
    side = min(img.width(), img.height())                        # the editor's start: as wide as it goes, at the face
    top = max(0, min(img.height() - side, int(img.height() * portraits.FACE - side / 2)))
    inner = img.copy((img.width() - side) // 2, top, side, side).scaled(OUT, OUT, Qt.IgnoreAspectRatio, Qt.SmoothTransformation)
    return {"png": to_png(render(inner, DEFAULT_BORDER)), "framed": True, "inner": to_png(inner), "border": dict(DEFAULT_BORDER)}


def edit_portrait(parent, name: str) -> bool:
    info = guard(view.portrait_info, name)
    if info is None:
        return False
    choice = open_portrait_editor(parent, info["race"], info["class"], info["portrait"])
    if choice is None:
        return False
    return guard(rt().characters.set_portrait, name, choice or None) is not None


# ---------------------------------------------------------------------- portrait modules
def import_portraits(parent) -> bool:
    """Bring portraits into the library: a portrait module (.dmmod), or a folder of pictures made into one (a subfolder
    named 'race-dwarf', 'class-wizard', 'female'... tags its pictures). True when something came in."""
    how = dialogs.choose_one(parent, tr("Import portraits"), [(tr("A portrait module (.dmmod)"), "module"),
                                                              (tr("A folder of pictures"), "folder")])
    if how == "module":
        path, _f = QFileDialog.getOpenFileName(parent, tr("Import portraits"), "", tr("Modules (*.dmmod *.dpmod)"))
    elif how == "folder":
        path = QFileDialog.getExistingDirectory(parent, tr("A folder of pictures"))
    else:
        return False
    if not path:
        return False
    name = ""
    if how == "folder":
        name = dialogs.ask_text(parent, tr("Import portraits"), tr("The portrait module's name"),
                                os.path.basename(os.path.normpath(path)))
        if name is None:
            return False
    QGuiApplication.setOverrideCursor(Qt.WaitCursor)
    try:
        meta = guard(portrait_packs.import_path, path, name)
    finally:
        QGuiApplication.restoreOverrideCursor()
    if meta:
        notify.good(tr("Portraits added: {0}", meta.get("name") or meta.get("id")))
    return bool(meta)


def export_portraits(parent, shown_ids=None) -> Optional[str]:
    """Save portraits as a portrait module: the characters' and custom creatures' own pictures, or (from the portrait
    editor) the library portraits its gallery shows. Returns the file's path, or None."""
    own = guard(portrait_packs.own_portraits) or []
    options = []
    if own:
        options.append((tr("My characters' and creatures' portraits ({0})", len(own)), "own"))
    if shown_ids:
        options.append((tr("The portraits the gallery shows ({0})", len(shown_ids)), "shown"))
    if not options:
        notify.warn(tr("There are no portraits to export: give a character a picture of its own first."))
        return None
    what = options[0][1] if len(options) == 1 else dialogs.choose_one(parent, tr("Export portraits"), options)
    if not what:
        return None
    entries = own if what == "own" else portrait_packs.library_entries(shown_ids)
    values = dialogs.form(parent, tr("Export portraits"), [
        {"key": "name", "label": tr("Name"), "value": tr("My portraits"), "required": True},
        {"key": "version", "label": tr("Version"), "value": "1.0"},
        {"key": "author", "label": tr("Made by"), "value": ""}])
    if not values:
        return None
    from ....services import modules as svc
    folder = svc.default_folder()
    os.makedirs(folder, exist_ok=True)
    slug = "portraits-" + ("".join(c if c.isalnum() else "-" for c in values["name"].lower()).strip("-") or "mine")
    dest, _f = QFileDialog.getSaveFileName(parent, tr("Export portraits"),
                                           os.path.join(folder, f"{slug}-{values.get('version') or '1.0'}.dmmod"),
                                           tr("Modules (*.dmmod)"))
    if not dest:
        return None
    QGuiApplication.setOverrideCursor(Qt.WaitCursor)
    try:
        path = guard(portrait_packs.export, entries, dest, values["name"], values.get("version") or "1.0",
                     values.get("author") or "")
    finally:
        QGuiApplication.restoreOverrideCursor()
    if path:
        notify.good(tr("Saved {0} portraits as {1}", len(entries), os.path.basename(path)))
    return path


@action("characters.import_portraits", "Import portraits…", menu="Characters", order=60)
def import_portraits_action(window):
    import_portraits(window)


@action("characters.export_portraits", "Export portraits…", menu="Characters", order=61)
def export_portraits_action(window):
    export_portraits(window)
