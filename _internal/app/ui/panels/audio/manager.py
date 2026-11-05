"""The Audio window: ambience loops (rain, a campfire, footsteps on mud…) added from a list, each with its own volume,
switched on and off or removed at will, kept in profiles (one per place: the tavern, the forest camp…) that are switched
with a click; timed events (a loop that fades in, stays its seconds and fades out: a carriage passing by, church
bells) started and stopped with a button; one-shot effects (a door, an explosion, a bell) on buttons; whether all this is
heard on this computer, in the voice channel and/or on the player page; and streaming the audio of chosen apps into the
voice channel and to the player page."""
from typing import Callable

from PySide6.QtCore import QSize, Qt, QTimer
from PySide6.QtWidgets import QDialog, QFormLayout, QMenu, QSlider, QStyle, QStyleOptionSlider, QToolButton, QWidget

from ....core import events
from ....core.i18n import tr
from ....services import sound, table
from ....services.battle.icons import SOUNDS as SOUND_ICONS
from ... import dialogs, notify
from ...panel import Panel
from ...widgets.common import (FlowLayout, button, card, check, clear_layout, col, label, row, scroll, spin, stretch,
                               title, tool_button, widget)
from ...widgets.icons import game_icon, icon_button
from ...widgets.pickers import PickList


def _set_checked(box, on: bool):
    box.blockSignals(True)
    box.setChecked(bool(on))
    box.blockSignals(False)


def _info(text: str):
    """A dim ⓘ beside a section's title: how the section works, on hover."""
    lab = label("ⓘ", role="dim", tip=text)
    lab.setCursor(Qt.WhatsThisCursor)
    return lab


def _form(*rows) -> QFormLayout:
    form = QFormLayout()
    form.setContentsMargins(0, 0, 0, 0)
    form.setSpacing(4)
    for name, w in rows:
        form.addRow(name, w)
    return form


class _JumpSlider(QSlider):
    """A slider whose handle jumps to the exact spot clicked (and can be dragged on from there)."""

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            opt = QStyleOptionSlider()
            self.initStyleOption(opt)
            groove = self.style().subControlRect(QStyle.CC_Slider, opt, QStyle.SC_SliderGroove, self)
            handle = self.style().subControlRect(QStyle.CC_Slider, opt, QStyle.SC_SliderHandle, self)
            if not handle.contains(e.position().toPoint()):
                x = e.position().x() - groove.x() - handle.width() / 2
                self.setValue(QStyle.sliderValueFromPosition(self.minimum(), self.maximum(), round(x),
                                                             groove.width() - handle.width()))
        super().mousePressEvent(e)


class _Slider(QWidget):
    """A volume/delay slider with its value beside it; `on_commit(value)` when the user lets go (or uses the keys)."""

    def __init__(self, high: int, step: int, unit: str, on_commit: Callable[[int], None], tip: str = ""):
        super().__init__()
        self.step, self.unit, self.on_commit = step, unit, on_commit
        self.slider = _JumpSlider(Qt.Horizontal)
        self.slider.setRange(0, high // step)
        self.slider.setPageStep(5)
        self.value_label = label("", role="dim")
        self.value_label.setFixedWidth(52)
        self.value_label.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        if tip:
            self.setToolTip(tip)
        self.slider.valueChanged.connect(self._moved)
        self.slider.sliderReleased.connect(self._commit)
        self.setLayout(row(self.slider, self.value_label))

    def value(self) -> int:
        return self.slider.value() * self.step

    def set_value(self, value: int):
        if self.slider.isSliderDown():                 # never move it under the pointer
            return
        self.slider.blockSignals(True)
        self.slider.setValue(round(int(value) / self.step))
        self.slider.blockSignals(False)
        self.value_label.setText(f"{self.value()}{self.unit}")
        self._committed = self.value()

    def _moved(self, _v):
        self.value_label.setText(f"{self.value()}{self.unit}")
        if not self.slider.isSliderDown():
            self._commit()

    def _commit(self):
        if self.value() != getattr(self, "_committed", None):     # a click that jumped is saved once, not again on release
            self._committed = self.value()
            self.on_commit(self.value())


class AudioPanel(Panel):
    def build(self):
        self._loop_keys = None
        self._event_keys = None
        self._event_rows = {}
        self._profile_names = None
        self._chips = []
        self._loop_rows = {}
        self._pids = None
        self._app_rows = {}
        # ---- where it is heard
        self.speakers = check(tr("This computer"), on_change=lambda on: self.run(sound.set_outputs, speakers=on),
                              tip=tr("Play the loops and effects on this computer's speakers.\nTurn it off when you "
                                     "are in the voice channel too, or you hear them twice."))
        self.voice = check(tr("Voice channel"), on_change=lambda on: self.run(sound.set_outputs, voice=on),
                           tip=tr("Mix the loops and effects into what the bot plays in the voice channel."))
        self.web = check(tr("Player page"), on_change=lambda on: self.run(sound.set_outputs, web=on),
                         tip=tr("Mix the loops and effects into the music players hear on the player page\n"
                                "(they press Listen there and set their own volume)."))
        self.out_hint = label("", role="dim")
        self.problem = label("", role="bad", wrap=True, selectable=True)
        out_card = card(row(title(tr("Hear on")), self.speakers, self.voice, self.web, self.out_hint, stretch()),
                        self.problem)
        # ---- ambience loops
        self.loops_volume = _Slider(100, 1, "%", lambda v: self.run(sound.set_volume, v),
                                    tip=tr("The level of every loop together"))
        self.chips_host = QWidget()
        self.chips = FlowLayout(self.chips_host, spacing=4)
        more = tool_button("⋯", tip=tr("Rename, copy or delete this profile"))
        more.setPopupMode(QToolButton.InstantPopup)
        menu = QMenu(more)
        menu.addAction(tr("Rename…"), self._rename_profile)
        menu.addAction(tr("Copy as a new profile…"), lambda: self._new_profile(copy=True))
        menu.addAction(tr("Delete"), self._delete_profile)
        more.setMenu(menu)
        self._profile_tools = (button(tr("New…"), self._new_profile, tip=tr("A new, empty profile for another place")),
                               more)
        self.loops_box = col(spacing=2)
        self.loops_empty = label(tr("No loops yet: Add… rain, a campfire, footsteps on mud…"), role="dim")
        loops_card = card(row(title(tr("Ambience")), _info(tr("Profiles: click one to play it. Its loops are listed below.")), stretch(),
                              button(tr("Add…"), self._add_loops, kind="primary", tip=tr("Add loops to the list")),
                              icon_button("sound-off", lambda: self.run(sound.stop_loops),
                                          tr("All off") + "\n" + tr("Switch every loop off (they stay in the list)"))),
                          self.chips_host, _form((tr("Volume"), self.loops_volume)), self.loops_empty, self.loops_box)
        # ---- timed events
        self.events_box = col(spacing=2)
        self.events_empty = label(tr("No timed events yet: Add… a horse and carriage passing by, church bells…"),
                                  role="dim")
        events_card = card(row(title(tr("Timed events")),
                               _info(tr("Click one to play it: it fades in, stays for its seconds and fades out. Click "
                                        "it again to stop it early.")), stretch(),
                               button(tr("Add…"), self._add_events, kind="primary",
                                      tip=tr("Make loops into timed events"))),
                           self.events_empty, self.events_box)
        self._ticker = QTimer(self)                    # the seconds left on the events playing
        self._ticker.setInterval(500)
        self._ticker.timeout.connect(self._tick)
        # ---- one-shot effects
        self.effects_volume = _Slider(100, 1, "%", lambda v: self.run(sound.set_effects_volume, v))
        self.effects_box = col(spacing=4)
        effects_card = card(row(title(tr("Effects")), stretch(),
                                icon_button("sound-off", lambda: self.run(sound.stop_effects),
                                            tr("Stop") + "\n" + tr("Cut the effects that are still sounding"))),
                            _form((tr("Volume"), self.effects_volume)), self.effects_box)
        self._build_effects()
        # ---- streaming apps (the selected server's)
        self.stream = check(tr("Stream audio"), on_change=lambda on: self._save(stream_audio=on),
                            tip=tr("Play the chosen apps in the voice channel and on the player page."))
        self.mute = check(tr("Mute"), on_change=lambda on: self._save(muted=on))
        self.audio_hint = label("", role="dim")
        self.master = _Slider(200, 1, "%", lambda v: self._save(volume=v))
        self.delay = _Slider(5000, 10, " ms", lambda v: self._save(delay=v),
                             tip=tr("Delay\nHolds the whole stream back by this many milliseconds. Useful for testing "
                                    "or lining the audio up with a video."))
        self.apps_title = label("", role="dim")
        self.apps_box = col(spacing=2)
        self.stream_body = widget(col(row(self.stream, button(tr("Add apps…"), self._pick_apps), self.audio_hint,
                                          stretch(), self.mute),
                                      _form((tr("Master volume"), self.master), (tr("Delay"), self.delay)),
                                      self.apps_title, self.apps_box))
        self.stream_note = label(tr("Pick a server on the toolbar to stream apps into its voice channel and to the "
                                    "player page."), role="dim",
                                 wrap=True)
        stream_card = card(title(tr("Streaming apps")), self.stream_note, self.stream_body)
        self.layout().addWidget(scroll(widget(col(out_card, loops_card, events_card, effects_card, stream_card, stretch(),
                                                  spacing=6))))
        self.on(events.SOUND, self.refresh)
        self.on(events.BOT, self.refresh)
        self.on(events.GUILD, self.refresh)

    def _build_effects(self):
        groups = {}
        for s in sound.catalog()["oneshots"]:
            groups.setdefault(s["group"], []).append(s)
        for group, items in groups.items():
            host = QWidget()
            flow = FlowLayout(host, spacing=4)
            for s in items:
                b = button(tr(s["name"]), lambda k=s["key"]: self.run(sound.play, k),
                           tip=tr("{0}\nFrom freesound.org: {1} (CC0)", tr(s["name"]), s["credit"]))
                pic = SOUND_ICONS.get(s["key"])                 # a picture beside the word: quicker to find on the board
                if pic:
                    b.setIcon(game_icon(pic, 16, "#cbd5e1"))
                    b.setIconSize(QSize(16, 16))
                flow.addWidget(b)
            self.effects_box.addWidget(label(tr(group), role="dim"))
            self.effects_box.addWidget(host)

    # ------------------------------------------------------------------ showing
    def refresh(self):
        v = sound.view()
        _set_checked(self.speakers, v["speakers"])
        _set_checked(self.voice, v["voice"])
        _set_checked(self.web, v["web"])
        self.out_hint.setText("" if v["speakers"] or v["voice_connected"] or v["web"] else
                              tr("Not heard anywhere: the bot isn't in a voice channel."))
        self.problem.setText(v["problem"])
        self.problem.setVisible(bool(v["problem"]))
        self.loops_volume.set_value(v["volume"])
        self.effects_volume.set_value(v["effects"])
        self._refresh_profiles(v["profiles"], v["profile"])
        self._refresh_loops(v["loops"])
        self._refresh_events(v["events"])
        self._refresh_stream()

    def _refresh_profiles(self, names, current: int):
        if names != self._profile_names:
            self._profile_names = names
            while self.chips.count():
                w = self.chips.takeAt(0).widget()
                if w not in self._profile_tools:
                    w.setParent(None)
                    w.deleteLater()
            self._chips = [button(name, lambda i=i: self.run(sound.select_profile, i), checkable=True,
                                  tip=tr("Play this profile")) for i, name in enumerate(names)]
            for w in self._chips + list(self._profile_tools):      # New… and ⋯ follow the last profile
                self.chips.addWidget(w)
        for i, chip in enumerate(self._chips):
            _set_checked(chip, i == current)
        self._profile = current

    def _refresh_loops(self, loops):
        self.loops_empty.setVisible(not loops)
        keys = [x["key"] for x in loops]
        if keys != self._loop_keys:                    # rebuilt only when the list changes: a dragged slider stays
            self._loop_keys = keys
            clear_layout(self.loops_box)
            self._loop_rows = {}
            for x in loops:
                on = check(tr(x["name"]), on_change=lambda v, k=x["key"]: self.run(sound.set_loop_on, k, v),
                           tip=tr("{0}\nFrom freesound.org: {1} (CC0)", tr(x["name"]), x["credit"]))
                on.setMinimumWidth(150)
                slider = _Slider(100, 1, "%", lambda val, k=x["key"]: self.run(sound.set_loop_volume, k, val))
                line = row(on, slider, tool_button("✕", lambda k=x["key"]: self.run(sound.remove_loop, k),
                                                   tip=tr("Remove this loop")))
                line.setStretch(0, 2)
                line.setStretch(1, 3)
                self._loop_rows[x["key"]] = (on, slider)
                self.loops_box.addLayout(line)
        for x in loops:
            on, slider = self._loop_rows[x["key"]]
            _set_checked(on, x["on"])
            slider.set_value(x["volume"])
            slider.setEnabled(x["on"])

    def _refresh_events(self, timed):
        self.events_empty.setVisible(not timed)
        keys = [x["key"] for x in timed]
        if keys != self._event_keys:                   # rebuilt only when the list changes: a dragged slider stays
            self._event_keys = keys
            clear_layout(self.events_box)
            self._event_rows = {}
            for x in timed:
                play = button("", lambda k=x["key"]: self.run(sound.toggle_event, k), checkable=True,
                              tip=tr("{0}\nFrom freesound.org: {1} (CC0)", tr(x["name"]), x["credit"]))
                play.setMinimumWidth(180)
                secs = spin(x["seconds"], 2, 3600, tip=tr("How long it plays, fades included"))
                secs.setSuffix(" s")
                secs.setFixedWidth(64)
                secs.editingFinished.connect(lambda k=x["key"], w=secs: self.run(sound.set_event_seconds, k, w.value()))
                slider = _Slider(100, 1, "%", lambda val, k=x["key"]: self.run(sound.set_event_volume, k, val))
                line = row(play, secs, slider, tool_button("✕", lambda k=x["key"]: self.run(sound.remove_event, k),
                                                           tip=tr("Remove this timed event")))
                line.setStretch(2, 1)
                self._event_rows[x["key"]] = (play, secs, slider, x["name"])
                self.events_box.addLayout(line)
        for x in timed:
            _play, secs, slider, _name = self._event_rows[x["key"]]
            if not secs.hasFocus():
                secs.blockSignals(True)
                secs.setValue(x["seconds"])
                secs.blockSignals(False)
            slider.set_value(x["volume"])
        self._tick()

    def _tick(self):
        """Show which timed events play and how long they have left."""
        playing = sound.events_playing()
        for key, (play, _secs, _slider, name) in self._event_rows.items():
            left = playing.get(key)
            _set_checked(play, left is not None)
            play.setText(("■ " + tr("{0} · {1} s", tr(name), int(left + 0.99))) if left is not None else "▶ " + tr(name))
        if playing and not self._ticker.isActive():
            self._ticker.start()
        elif not playing:
            self._ticker.stop()

    def _refresh_stream(self):
        live = table.server_view() is not None
        self.stream_body.setVisible(live)
        self.stream_note.setVisible(not live)
        if not live:
            return
        a = table.audio_view()
        _set_checked(self.stream, a["stream"])
        _set_checked(self.mute, a["muted"])
        self.master.set_value(a["volume"])
        self.delay.set_value(a["delay"])
        self.audio_hint.setText("" if a["has_channel"] else tr("Pick a voice channel on the Discord bot window."))
        self.apps_title.setText(tr("Volume per app") if a["apps"] else tr("No apps chosen."))
        pids = [x["pid"] for x in a["apps"]]
        if pids != self._pids:                         # rebuilt only when the apps change: a dragged slider stays
            self._pids = pids
            clear_layout(self.apps_box)
            self._app_rows = {}
            for x in a["apps"]:
                name = label("")
                name.setMinimumWidth(80)
                slider = _Slider(200, 1, "%", lambda v, p=x["pid"]: self.run(table.set_app_volume, p, v))
                self._app_rows[x["pid"]] = (name, slider)
                line = row(name, slider, tool_button("✕", lambda p=x["pid"]: self.run(table.remove_stream_app, p),
                                                     tip=tr("Stop streaming this app")))
                line.setStretch(0, 2)
                line.setStretch(1, 3)
                self.apps_box.addLayout(line)
        for x in a["apps"]:
            name, slider = self._app_rows[x["pid"]]
            text = x["label"] or tr("Process {0}", x["pid"])
            name.setText(text[:60] + ("…" if len(text) > 60 else ""))
            name.setToolTip(text)
            slider.set_value(x["volume"])

    # ------------------------------------------------------------------ actions
    def _add_loops(self):
        addable = sound.view()["addable"]
        if not addable:
            notify.info(tr("Every loop is in the list already."))
            return
        d = dialogs.Dialog(self, tr("Add loops"), 420, 520)
        picks = PickList([{"value": x["key"], "label": x["name"], "group": x["group"]} for x in addable],
                         count=len(addable), detail=None)
        d.body.addWidget(picks)
        d.ok_cancel(tr("Add"))
        if d.exec() == QDialog.Accepted and picks.chosen():
            self.run(sound.add_loops, picks.chosen())

    def _new_profile(self, copy: bool = False):
        name = dialogs.ask_text(self, tr("Copy as a new profile") if copy else tr("New profile"),
                                tr("Name (a place, like Tavern or Forest camp)"))
        if name and name.strip():
            self.run(sound.add_profile, name, copy)

    def _rename_profile(self):
        name = dialogs.ask_text(self, tr("Rename profile"), tr("Name"), self._profile_names[self._profile])
        if name and name.strip():
            self.run(sound.rename_profile, self._profile, name)

    def _delete_profile(self):
        if dialogs.confirm(self, tr("Delete the profile {0} and its list of loops?", self._profile_names[self._profile]),
                           yes=tr("Delete")):
            self.run(sound.delete_profile, self._profile)

    def _add_events(self):
        have = {x["key"] for x in sound.view()["events"]}
        options = [{"value": x["key"], "label": x["name"], "group": x["group"]}
                   for x in sound.catalog()["loops"] if x["key"] not in have]
        d = dialogs.Dialog(self, tr("Add timed events"), 420, 520)
        picks = PickList(options, count=len(options), detail=None)
        d.body.addWidget(picks)
        d.ok_cancel(tr("Add"))
        if d.exec() == QDialog.Accepted and picks.chosen():
            self.run(sound.add_events, picks.chosen())

    def _save(self, **values):
        self.run(self.rt.update_server, **values)

    def _pick_apps(self):
        found = self.run(table.apps) or []
        if not found:
            notify.warn(tr("No running apps found (the app list needs Windows)."))
            return
        current = [x["pid"] for x in table.audio_view()["apps"]]
        running = {x["pid"] for x in found}
        options = [{"value": x["pid"], "label": x["label"]} for x in found]
        options += [{"value": p, "label": tr("Process {0} (not running)", p)} for p in current if p not in running]
        d = dialogs.Dialog(self, tr("Apps to capture audio from"), 640, 520)
        picks = PickList(options, count=len(options), selected=current, detail=None)
        d.body.addWidget(picks)
        d.ok_cancel()
        if d.exec() == QDialog.Accepted:
            self.run(table.set_stream_apps, picks.chosen())
