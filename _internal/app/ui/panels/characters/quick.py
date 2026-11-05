"""Quick adventurer: a ready-to-play character of any level in a few clicks. Pick a pre-made concept (Dwarven Fighter,
Human Paladin...) or a race and a class, set the level, and the rest (scores, background, skills, subclass, spells,
feats, gear, name, personality) is decided by rules.quickgen. A portrait comes from the portrait library when there
is one; the preview shows the finished sheet. The full creation wizard stays for characters built by hand.

    name = open_quick_creation(parent, owner_id=None, owner_name=None)     # modal; the new character's name or None
"""
import random
from typing import Optional

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import QAbstractSpinBox, QDialog, QGridLayout, QListWidget, QListWidgetItem

from ....core import portraits
from ....core.i18n import tr
from ....core.runtime import rt
from ....rules import leveling as LV
from ....rules import quickgen
from ....rules.creation import race_requirements
from ....rules.data import rules
from ... import errors, notify
from ...dialogs import Dialog
from ...registry import action
from ...widgets.common import book_items, button, col, combo, label, line_edit, row, set_items, spin, stretch, title
from ...widgets.text import TextView
from .choices import attempt
from .portrait import library_portrait, open_portrait_editor, portrait_pixmap, render

CUSTOM = ""                                                         # the concept list's "my own combination"
GENDERS = lambda: [(tr("Any"), ""), (tr("Male"), "male"), (tr("Female"), "female")]


class QuickCreation(Dialog):
    def __init__(self, parent, owner_id: Optional[int], owner_name: Optional[str]):
        super().__init__(parent, tr("Quick adventurer"), 980, 680)
        self.owner_id, self.owner_name = owner_id, owner_name
        self.created: Optional[str] = None
        self.seed = random.randrange(1 << 30)
        self.name_auto = True                       # the name was made up here (remade when race or gender change)
        self.portrait: Optional[dict] = None        # what set_portrait takes; None: the automatic race picture
        self.portrait_auto = bool(portraits.library())   # picked from the library here (picked again on changes)
        self.loading = False

        self.concepts = QListWidget()
        self.concepts.setFixedWidth(210)
        it = QListWidgetItem("✎  " + tr("My own combination"))
        it.setData(Qt.UserRole, CUSTOM)
        self.concepts.addItem(it)
        for a in quickgen.archetypes():
            it = QListWidgetItem(tr(a["title"]))
            it.setData(Qt.UserRole, a["key"])
            it.setToolTip(tr(a["blurb"]))
            self.concepts.addItem(it)
        self.concepts.currentItemChanged.connect(lambda cur, _prev: self._concept(cur.data(Qt.UserRole) if cur else CUSTOM))
        self.blurb = label("", role="dim", wrap=True)
        self.blurb.setFixedWidth(210)

        races = book_items(rules.race_list())
        classes = book_items(rules.class_list())
        self.race = combo(races, "Human" if any(r[1] == "Human" for r in races) else None,
                          on_change=lambda _v: self._race_changed())
        self.subrace = combo(on_change=lambda _v: self._changed())
        self.cls = combo(classes, "Fighter" if any(c[1] == "Fighter" for c in classes) else None,
                         on_change=lambda _v: self._class_changed())
        self.subclass = combo(on_change=lambda _v: self._changed())
        self.level = spin(1, 1, 20, on_change=lambda _v: self._changed(), width=64)
        self.level.setButtonSymbols(QAbstractSpinBox.UpDownArrows)
        self.gender = combo(GENDERS(), on_change=lambda _v: self._gender_changed())
        self.background = combo(on_change=lambda _v: self._changed())
        self.name = line_edit(placeholder=tr("Name"))
        self.name.textEdited.connect(self._name_edited)

        grid = QGridLayout()
        grid.setHorizontalSpacing(10)
        grid.setVerticalSpacing(6)
        for i, (text, w) in enumerate(((tr("Race"), self.race), (tr("Subrace"), self.subrace), (tr("Class"), self.cls),
                                       (tr("Subclass"), self.subclass), (tr("Level"), self.level), (tr("Gender"), self.gender))):
            grid.addWidget(label(text), i // 2, (i % 2) * 2)
            grid.addWidget(w, i // 2, (i % 2) * 2 + 1)
        grid.addWidget(label(tr("Background")), 3, 0)
        grid.addWidget(self.background, 3, 1)
        grid.addWidget(label(tr("Name")), 3, 2)
        grid.addLayout(row(self.name, button("🎲", self._new_name, tip=tr("Another name in the style of the race"))), 3, 3)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)

        self.face = label()
        self.face_note = label("", role="dim", wrap=True)
        has_library = bool(portraits.library())
        lib_button = button(tr("🎲 From the library"), self._library_portrait,
                            tip=tr("Another portrait of this race and class from the portrait library") if has_library
                            else tr("No portrait module is installed (Characters ▸ Import portraits…)."))
        lib_button.setEnabled(has_library)
        face_row = row(self.face, col(title(tr("Portrait")), self.face_note,
                                      row(lib_button, button(tr("Choose portrait…"), self._choose_portrait,
                                                             tip=tr("A portrait from the library or a picture of your own")),
                                          button(tr("Automatic"), lambda: self._set_portrait(None, False)), stretch())),
                       spacing=10)

        self.headline = title("")
        self.preview = TextView()
        right = col(grid, face_row, row(self.headline, stretch(),
                                        button(tr("🎲 Reroll"), self._reroll,
                                               tip=tr("New name, personality and portrait; the build stays the same"))),
                    self.preview, spacing=8)
        right.setStretch(3, 1)
        self.body.addLayout(row(col(label(tr("Concept")), self.concepts, self.blurb, spacing=4), right, spacing=12), 1)

        self.add_button(tr("Cancel"), self.reject)
        self.create_btn = self.add_button(tr("Create"), self.submit, kind="primary", default=True)
        self.timer = QTimer(self)
        self.timer.setSingleShot(True)
        self.timer.setInterval(220)
        self.timer.timeout.connect(self._redraw)

        self.loading = True
        self._fill_race()
        self._fill_class()
        self.loading = False
        self.concepts.setCurrentRow(0)
        self._new_name()
        self._pick_portrait()
        self._changed()

    # ------------------------------------------------------------------ the form
    def _concept_key(self) -> str:
        it = self.concepts.currentItem()
        return it.data(Qt.UserRole) if it else CUSTOM

    def _concept(self, key: str):
        a = quickgen.archetype(key) if key else None
        self.blurb.setText(tr(a["blurb"]) if a else tr("Choose a race, a class and a level; everything else is "
                                                        "decided for you. Pick a concept on the left for a classic hero."))
        if not a:
            return
        self.loading = True
        self.race.setCurrentIndex(max(0, self.race.findData(a["race"])))
        self._fill_race(a.get("subrace"))
        self.cls.setCurrentIndex(max(0, self.cls.findData(a["class"])))
        self._fill_class(a.get("subclass"), a.get("background"))
        self.loading = False
        self._identity_changed()

    def _fill_race(self, subrace: Optional[str] = None):
        req = race_requirements(self.race.currentData())
        items = [(tr("Automatic"), "")] + [(s, s) for s in req["subraces"]]
        set_items(self.subrace, items, subrace or "")
        self.subrace.setEnabled(bool(req["subraces"]))

    def _fill_class(self, subclass: Optional[str] = None, background: Optional[str] = None):
        cls = self.cls.currentData()
        at = quickgen.subclass_level(cls)
        set_items(self.subclass, [(tr("Automatic"), "")] + book_items(LV.subclass_options(cls)),
                  subclass or "")
        self.subclass.setEnabled(at is not None)
        self.subclass.setToolTip(tr("Chosen at level {0}", at) if at else "")
        default = quickgen.PROFILES.get(cls, {}).get("background", "")
        set_items(self.background, [(tr("Automatic ({0})", default) if default else tr("Automatic"), "")] +
                  book_items(rules.background_list()), background or "")

    def _leave_concept(self):
        """A race or class of one's own: the concept's extras (its weapons, its look) no longer apply."""
        if self._concept_key() != CUSTOM:
            self.concepts.blockSignals(True)
            self.concepts.setCurrentRow(0)
            self.concepts.blockSignals(False)
            self._concept(CUSTOM)

    def _race_changed(self):
        if self.loading:
            return
        self._leave_concept()
        self._fill_race()
        self._identity_changed()

    def _class_changed(self):
        if self.loading:
            return
        self._leave_concept()
        self._fill_class()
        self._identity_changed()

    def _gender_changed(self):
        self._identity_changed()

    def _identity_changed(self):
        """Race, class or gender changed: a made-up name and a picked portrait are made again to suit."""
        if self.name_auto:
            self._new_name()
        if self.portrait_auto:
            self._pick_portrait()
        self._changed()

    def _name_edited(self, text: str):
        self.name_auto = not text.strip()
        self._changed()

    def _new_name(self):
        taken = set(rt().characters.names())
        rnd = random.Random()
        for _ in range(50):
            name = quickgen.random_name(self.race.currentData(), self.gender.currentData(), rnd)
            if name not in taken:
                break
        self.name.setText(name)
        self.name_auto = True
        self._changed()

    def _reroll(self):
        self.seed = random.randrange(1 << 30)
        if self.name_auto:
            self._new_name()
        if self.portrait_auto:
            self._pick_portrait()
        self._changed()

    # ------------------------------------------------------------------ portrait
    def _pick_portrait(self):
        g = {"male": "m", "female": "f"}.get(self.gender.currentData(), "")
        choice = errors.guard(library_portrait, self.race.currentData(), self.cls.currentData(), g)
        self._set_portrait(choice, True)

    def _library_portrait(self):
        self._pick_portrait()
        if not self.portrait:
            notify.warn(tr("The portrait library has no portrait for this race and class."))

    def _set_portrait(self, portrait: Optional[dict], auto: bool):
        self.portrait, self.portrait_auto = portrait, auto
        if portrait:
            img = QImage.fromData(portrait["png"])
            pm = QPixmap.fromImage(img.scaled(84, 84, Qt.KeepAspectRatio, Qt.SmoothTransformation) if portrait["framed"]
                                   else render(img, {"style": "side"}, 84))
            self.face_note.setText(tr("From the portrait library; 🎲 for another.") if auto else tr("A portrait of its own."))
        else:
            pm = portrait_pixmap(portraits.of({"race": self.race.currentData()})[0], False, 84)
            self.face_note.setText(tr("Automatic: the picture of its race."))
        self.face.setPixmap(pm)

    def _choose_portrait(self):
        current = {"image": QImage.fromData(self.portrait["inner"]), "border": self.portrait["border"]} if self.portrait else {}
        choice = open_portrait_editor(self, self.race.currentData(), self.cls.currentData(), current)
        if choice is not None:
            self._set_portrait(choice or None, False)

    # ------------------------------------------------------------------ preview and create
    def options(self) -> dict:
        key = self._concept_key()
        base = quickgen.archetype_options(key) if key else {}
        base.update({"race": self.race.currentData(), "subrace": self.subrace.currentData() or None,
                     "class": self.cls.currentData(), "subclass": self.subclass.currentData() or None,
                     "background": self.background.currentData() or base.get("background"),
                     "level": self.level.value(), "gender": self.gender.currentData(),
                     "name": self.name.text().strip(), "seed": self.seed})
        return base

    def _changed(self):
        if not self.loading:
            self.timer.start()

    def _redraw(self):
        try:
            char = quickgen.generate(self.options())
        except LV.RulesError as e:
            self.headline.setText("")
            self.preview.set_text("")
            self.show_problem(tr(str(e)))
            self.create_btn.setEnabled(False)
            return
        except Exception as e:                       # noqa: BLE001 - a bug: reported, the dialog stays usable
            errors.report(e)
            self.create_btn.setEnabled(False)
            return
        self.show_problem("")
        self.create_btn.setEnabled(True)
        self.headline.setText(quickgen.summary(char))
        self.preview.set_text(quickgen.preview_text(char))

    def submit(self):
        self.timer.stop()
        opts = self.options()
        if self.name_auto and opts["name"] in rt().characters.names():
            self._new_name()
            opts["name"] = self.name.text().strip()
        ok, char = attempt(self, rt().characters.create_quick, opts, self.owner_id, self.owner_name)
        if not ok:
            return
        if self.portrait:
            errors.guard(rt().characters.set_portrait, char.name, self.portrait)
        self.created = char.name
        notify.good(tr("Created {0}.", char.name))
        self.accept()


def open_quick_creation(parent=None, owner_id: Optional[int] = None, owner_name: Optional[str] = None) -> Optional[str]:
    """Modal. Returns the new character's name, or None when cancelled."""
    d = errors.guard(QuickCreation, parent, owner_id, owner_name)
    if d is None:
        return None
    return d.created if d.exec() == QDialog.Accepted else None


@action("characters.quick", "Quick adventurer…", menu="Characters", shortcut="Ctrl+Shift+N")
def quick_character(window):
    name = open_quick_creation(window)
    if name:
        rt().select_character(name)
