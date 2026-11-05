"""The Party window: the players and their characters in one list (portraits, class, hit points, who plays this
session), the team inventory they share, the team notes everyone reads and adds to, and the player portal (each
player's link to the table and who is connected), on one page: each under a header that folds it away."""
from ....core.i18n import tr
from ...panel import SectionedPanel
from ...registry import panel
from ..portal.share import PortalPanel
from .players import PartyListPanel
from .team import TeamPanel
from .team_notes import TeamNotesPanel


@panel("characters.roster", "Party", "Characters", icon="👥", area="left",
       description="Every character under the player who owns it (select one to show it everywhere, double-click for its "
                   "sheet, right-click to mark who plays this session), the team inventory they share, the team notes "
                   "every player reads and adds to, and the player portal: each player's link to the table and who is "
                   "connected.")
class PartyPanel(SectionedPanel):
    opened = ("party",)

    def pages(self):
        return [("party", "👥 " + tr("Party"), PartyListPanel),
                ("team", "🎒 " + tr("Team inventory"), TeamPanel),
                ("notes", "📝 " + tr("Team notes"), TeamNotesPanel),
                ("portal", "🌐 " + tr("Player portal"), PortalPanel)]
