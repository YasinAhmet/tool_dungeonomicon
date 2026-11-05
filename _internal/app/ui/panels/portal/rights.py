"""The Player rights window (⚙ on the Player portal page): every right of api.RIGHTS as a switch, in groups. A switch
takes effect at once: the server checks it on every action and the players' pages reload without what is off."""
from typing import Dict

from PySide6.QtWidgets import QWidget

from ....core import events
from ....core.i18n import tr
from ....core.runtime import rt
from ....services.portal import api
from ....services.portal.controller import portal
from ...dialogs import Dialog
from ...errors import guard_ok
from ...widgets.common import card, check, col, label, row, scroll, stretch, title, widget

# "Only look and chat": players follow the game and talk; the DM does everything else.
LOOK_ONLY = {"see_battle", "see_world", "chat", "team_notes", "now_playing", "music"}


def apply_rights(values: Dict[str, bool]) -> bool:
    """Change rights, with what goes with them: the Spotify watcher starts or stops, the pages' players hear of it."""
    if not guard_ok(api.set_settings, values):
        return False
    if "now_playing" in values:
        from ....services.nowplaying import nowplaying
        if values["now_playing"] and portal.running:
            nowplaying.start(lambda: rt().bus.emit(events.NOWPLAYING))
        elif not values["now_playing"]:
            nowplaying.stop()
    if "now_playing" in values or "music" in values:
        rt().bus.emit(events.NOWPLAYING)         # the pages show or hide the song and Listen (and stop playing)
    return True


class RightsDialog(Dialog):
    def __init__(self, parent: QWidget):
        super().__init__(parent, tr("Player rights"), width=660, height=640)
        self.body.addWidget(label(tr("What players may do on their page. A change takes effect at once, on every open "
                                     "page; what is off is hidden from them."), role="dim", wrap=True))
        self.checks = {}
        cards = []
        for group, rows in api.RIGHTS:
            boxes = []
            for key, words, what in rows:
                box = check(tr(words), False, lambda on, k=key: self._set(k, on), tip=tr(what))
                self.checks[key] = box
                boxes.append(box)
                boxes.append(label(tr(what), role="dim", wrap=True))
            cards.append(card(title(tr(group)), *boxes))
        half = 2                                         # maps and the sheet | items, the table and music
        sides = widget(row(col(*cards[:half], stretch()), col(*cards[half:], stretch()), spacing=6))
        self.body.addWidget(scroll(sides), 1)            # (a short screen: it scrolls; wrapped words never clip)
        self.add_button(tr("Allow everything"), lambda: self._preset(set(api.DEFAULTS)))
        self.add_button(tr("Only look and chat"), lambda: self._preset(LOOK_ONLY))
        self.add_button(tr("Done"), self.accept, kind="primary", default=True)
        self.buttons.takeAt(0)                           # the presets on the left, Done on the right (not the base's
        self.buttons.insertStretch(2, 1)                 # stretch before them all)
        self._unsub = rt().bus.subscribe(events.RIGHTS, lambda: guard_ok(self.refresh))
        self.finished.connect(lambda *_: self._unsub())
        self.refresh()

    def refresh(self):
        now = api.settings()
        for key, box in self.checks.items():
            box.blockSignals(True)
            box.setChecked(bool(now[key]))
            box.blockSignals(False)
        self.checks["move_tokens"].setEnabled(bool(now["see_battle"]))    # moving a token needs the map

    def _set(self, key: str, on: bool):
        apply_rights({key: on})
        self.refresh()

    def _preset(self, keys):
        apply_rights({k: k in keys for k in api.DEFAULTS})
        self.refresh()


def open_rights(parent: QWidget):
    RightsDialog(parent).exec()
