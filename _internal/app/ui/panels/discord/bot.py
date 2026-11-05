"""The Discord bot window: the token, start/stop and status; the selected server's voice channel (join/leave), log
channel or thread and which kinds of lines are logged. Streaming apps into the voice channel is on the Audio window."""
from typing import List, Sequence, Tuple

from PySide6.QtWidgets import QComboBox, QFormLayout, QLineEdit, QSizePolicy, QWidget

from ....core import events
from ....core.i18n import tr
from ....services import table
from ...panel import Panel
from ...widgets.common import button, card, check, col, combo, label, line_edit, row, scroll, stretch, title, widget

STATUS = {"stopped": ("Stopped", "dim"), "connecting": ("Connecting…", "warn"), "online": ("Online", "good"),
          "error": ("Error", "bad")}


def _role(w: QWidget, role: str):
    w.setProperty("role", role)
    w.style().unpolish(w)
    w.style().polish(w)


def _set_checked(box, on: bool):
    box.blockSignals(True)
    box.setChecked(bool(on))
    box.blockSignals(False)


def _fill(c: QComboBox, groups: Sequence[Tuple[str, List[dict]]], current):
    """Refill a channel dropdown: '— none —', then each (heading, [{id, name}]) group (a heading is a greyed line).
    A saved channel the bot can't see (offline, deleted) stays listed so it isn't silently replaced."""
    current = str(current or "")
    c.blockSignals(True)
    c.clear()
    c.addItem(tr("— none —"), "")
    ids = set()
    for heading, items in groups:
        if not items:
            continue
        if heading:
            c.addItem(f"— {heading} —")
            c.model().item(c.count() - 1).setEnabled(False)
        for it in items:
            ids.add(str(it["id"]))
            c.addItem(it["name"], str(it["id"]))
    if current and current not in ids:
        c.addItem(tr("Channel {0}", current), current)
    c.setCurrentIndex(max(0, c.findData(current)))
    c.blockSignals(False)


class BotPanel(Panel):
    def build(self):
        self._touched = False
        # ---- the bot
        self.token = line_edit(tip=tr("Bot token\nSaved on this computer; the bot starts by itself when the app opens."),
                               on_enter=self._save_token)
        self.token.setEchoMode(QLineEdit.Password)
        self.token.textEdited.connect(self._typed)
        self.token.editingFinished.connect(self._save_token)
        show = check(tr("Show"), False, lambda on: self.token.setEchoMode(QLineEdit.Normal if on else QLineEdit.Password))
        self.start_b = button(tr("Start"), self._start, kind="primary")
        self.stop_b = button(tr("Stop"), lambda: self.run(self.rt.stop_bot), kind="danger")
        self.status = label("")
        self.members = label(tr("The Server Members Intent is off for this bot: only players who used the bot are "
                                "listed. Turn it on in the Discord developer portal (Bot ▸ Privileged Gateway Intents) "
                                "and restart the bot."), role="warn", wrap=True)
        self.problem = label("", role="bad", wrap=True, selectable=True)
        bot_card = card(row(title(tr("Bot")), stretch(), self.status), row(self.token, show, self.start_b, self.stop_b),
                        self.members, self.problem)
        # ---- the selected server
        self.srv_title = title("")
        self.srv_note = label("", role="dim", wrap=True)
        self.voice = combo(on_change=lambda v: self._save(channel_id=v),
                           tip=tr("Choosing a voice channel joins it at once; choosing none leaves."))
        self.voice.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Fixed)
        self.join_b = button(tr("Join"), lambda: self.run(self.rt.join_voice), tip=tr("Join the chosen voice channel"))
        self.leave_b = button(tr("Leave"), lambda: self.run(table.leave_voice), tip=tr("Leave the voice channel"))
        self.voice_text = label("", wrap=True)
        self.log_ch = combo(on_change=lambda v: self._save(log_channel_id=v),
                            tip=tr("Log channel\nRolls, XP and the battle log are posted here."))
        self.log_thread = combo(on_change=lambda v: self._save(log_thread_id=v),
                                tip=tr("Log to a thread or voice channel chat\nWhen set, log messages go here instead "
                                       "of the log channel."))
        self.kinds = {k: check(tr(name), True, lambda on, k=k: self.run(table.set_log_kind, k, on),
                               tip=tr("{0}\n{1}", tr(name), tr(tip))) for k, name, tip in table.LOG_KINDS}
        form = QFormLayout()
        form.setContentsMargins(0, 0, 0, 0)
        form.setSpacing(4)
        form.addRow(tr("Voice channel"), row(self.voice, self.join_b, self.leave_b))
        form.addRow("", self.voice_text)
        form.addRow(tr("Log channel"), self.log_ch)
        form.addRow(tr("Log to thread / voice chat"), self.log_thread)
        form.addRow(tr("Log"), row(*self.kinds.values(), stretch()))
        self.srv_body = widget(form)
        server_card = card(self.srv_title, self.srv_note, self.srv_body)
        self.layout().addWidget(scroll(widget(col(bot_card, server_card, stretch(), spacing=6))))
        self.on(events.BOT, self.refresh)
        self.on(events.GUILD, self.refresh)

    # ------------------------------------------------------------------ showing
    def refresh(self):
        b = table.bot_view()
        text, role = STATUS.get(b["status"], (b["status"], "dim"))
        self.status.setText(tr(text))
        _role(self.status, role)
        self.start_b.setVisible(not b["running"])
        self.stop_b.setVisible(b["running"])
        if not self._touched:
            self.token.setPlaceholderText(tr("•••••••• (saved - type to replace)") if b["token_set"] else tr("Bot token"))
        self.members.setVisible(b["members_warning"])
        self.problem.setText(tr(b["voice_text"]) if b["status"] == "error" else "")
        self.problem.setVisible(b["status"] == "error")
        sv = table.server_view()
        self.srv_body.setVisible(sv is not None)
        if sv is None:
            void = self.rt.void
            self.srv_title.setText((tr("Void") if void else tr("Server")).upper())
            self.srv_note.setText(tr("Nothing is sent to Discord while the void is selected. Pick a server on the "
                                     "toolbar to set up its voice and log channels.") if void else
                                  tr("Pick a server on the toolbar (the first button is the void)."))
            self.srv_note.show()
            return
        st = sv["settings"]
        self.srv_title.setText((sv["name"] or tr("Server {0}", sv["id"])).upper())
        self.srv_note.setText("" if sv["live"] else tr("Start the bot to list this server's channels."))
        self.srv_note.setVisible(not sv["live"])
        _fill(self.voice, [("", sv["voice"])], st["channel_id"])
        _fill(self.log_ch, [("", sv["text"])], st["log_channel_id"])
        _fill(self.log_thread, [(tr("Threads"), sv["threads"]), (tr("Voice channel chats"), sv["voice"])],
              st["log_thread_id"])
        for k, box in self.kinds.items():
            _set_checked(box, sv["log_kinds"][k])
        self.voice_text.setText(tr(b["voice_text"]))
        self.voice_text.setVisible(b["status"] != "error")      # the error is already under the token
        _role(self.voice_text, "good" if b["voice_connected"] else "bad" if b["voice_text"].startswith("Error")
              else "dim")
        self.join_b.setEnabled(sv["live"] and str(st["channel_id"]).isdigit())
        self.leave_b.setEnabled(b["voice_connected"])

    # ------------------------------------------------------------------ actions
    def _save(self, **values):
        self.run(self.rt.update_server, **values)

    def _typed(self, _text: str):
        self._touched = True

    def _save_token(self):
        if self._touched:
            self._touched = False
            self.run(self.rt.set_token, self.token.text())
            self.token.clear()

    def _start(self):
        self._save_token()
        self.run(self.rt.start_bot)
