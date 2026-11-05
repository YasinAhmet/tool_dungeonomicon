"""The SRD 5.1's own names for Player's Handbook and Dungeon Master's Guide content that the books name after their
wizards and heroes ('Bigby's Hand' is the SRD's 'Arcane Hand').

The program ships the SRD under the SRD's names (tools/split_content.py); the core-books module brings the books'
names back. The battle engine and the generators know these spells by the books' names, so they look names up through
`book_name()` and show them through `current_name()` - whichever is installed, the rules work the same.
"""
from typing import Dict

SPELLS: Dict[str, str] = {
    "Melf's Acid Arrow": "Acid Arrow", "Bigby's Hand": "Arcane Hand", "Mordenkainen's Sword": "Arcane Sword",
    "Nystul's Magic Aura": "Arcanist's Magic Aura", "Evard's Black Tentacles": "Black Tentacles",
    "Mordenkainen's Faithful Hound": "Faithful Hound", "Tenser's Floating Disk": "Floating Disk",
    "Otiluke's Freezing Sphere": "Freezing Sphere", "Tasha's Hideous Laughter": "Hideous Laughter",
    "Drawmij's Instant Summons": "Instant Summons", "Otto's Irresistible Dance": "Irresistible Dance",
    "Mordenkainen's Magnificent Mansion": "Magnificent Mansion", "Mordenkainen's Private Sanctum": "Private Sanctum",
    "Otiluke's Resilient Sphere": "Resilient Sphere", "Leomund's Secret Chest": "Secret Chest",
    "Rary's Telepathic Bond": "Telepathic Bond", "Leomund's Tiny Hut": "Tiny Hut",
}
ITEMS: Dict[str, str] = {
    "Apparatus of Kwalish": "Apparatus of the Crab", "Heward's Handy Haversack": "Handy Haversack",
    "Daern's Instant Fortress": "Instant Fortress", "Iron Bands of Bilarro": "Iron Bands of Binding",
    "Nolzur's Marvelous Pigments": "Marvelous Pigments", "Keoghtom's Ointment": "Restorative Ointment",
    "Quiver of Ehlonna": "Efficient Quiver",
    **{f"Quaal's Feather Token, {k}": f"Feather Token, {k}" for k in ("Anchor", "Bird", "Fan", "Swan Boat", "Tree", "Whip")},
}
RENAMED = {"spells": SPELLS, "items": ITEMS}
_BOOK = {srd.lower(): book.lower() for table in RENAMED.values() for book, srd in table.items()}


def book_name(name: str) -> str:
    """The books' name (lower case) of a spell or item for one of its SRD names; any other name lower-cased."""
    low = (name or "").lower()
    return _BOOK.get(low, low)


def current_name(book: str) -> str:
    """The name the installed content gives a spell the engine knows by its book name ('Bigby's Hand' -> 'Arcane
    Hand' when only the SRD is installed)."""
    from .data import rules
    sp = rules.spell(book)
    return sp["name"] if sp else book
