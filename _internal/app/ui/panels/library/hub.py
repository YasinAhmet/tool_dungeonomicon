"""The Library window: the rulebooks by book (and your own homebrew), the monster and item searches, the creature
and item workshops, and the installed content modules, as tabs of one window. An entry picked here is read in the
Inspector; hovering one shows its text."""
from ....core.i18n import tr
from ...panel import TabbedPanel
from ...registry import panel
from ..monsters.workshop import CreatureWorkshop
from .installations import InstallationsPanel
from .itemworkshop import ItemWorkshop
from .rules import RulesPanel
from .searches import ItemsPanel, MonstersPanel


@panel("library.rules", "Library", "Library", icon="📚", area="center",
       description="Every race, class, spell, item, feat and creature by book (and your own rulebooks), the monster and "
                   "item searches, the creature and item workshops, and the installed content modules (install, export, switch "
                   "off or remove books, monster descriptions and art).")
class LibraryPanel(TabbedPanel):
    def pages(self):
        return [("books", "📚 " + tr("Books"), RulesPanel),
                ("monsters", "🐉 " + tr("Monsters"), MonstersPanel),
                ("items", "🎒 " + tr("Items"), ItemsPanel),
                ("workshop", "🛠 " + tr("Creature workshop"), CreatureWorkshop),
                ("itemshop", "⚒ " + tr("Item workshop"), ItemWorkshop),
                ("installations", "📦 " + tr("Installations"), InstallationsPanel)]
