"""The Audio window: the table's sound (ambience loops, timed events, effects, app streaming) and the Discord bot that
carries it into the voice channel, as tabs of one window."""
from ....core.i18n import tr
from ...panel import TabbedPanel
from ...registry import panel
from ..discord.bot import BotPanel
from .manager import AudioPanel


@panel("audio.manager", "Audio", "Tools", icon="🔊", area="center",
       description="Ambience loops, timed events and one-shot effects for the table, heard here and in the Discord voice "
                   "channel; streaming chosen apps; and the Discord bot (token, voice channel, log channel).")
class AudioHub(TabbedPanel):
    def pages(self):
        return [("sound", "🔊 " + tr("Sound"), AudioPanel),
                ("discord", "🤖 " + tr("Discord bot"), BotPanel)]
