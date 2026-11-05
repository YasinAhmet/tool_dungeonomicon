"""Getting started: a checklist of the first steps (characters, a battle, the player portal, the Discord bot for the
table's sound), each ticked when it is done, with a button that opens the right place. Shown once on the first run,
and from Help ▸ Getting started."""
from ....core.i18n import tr
from ....core.runtime import rt
from ... import dialogs
from ...errors import guard
from ...registry import action, on_start
from ...widgets.common import button, label, row, stretch

SEEN = "seen_getting_started"


def steps(window):
    """(done, title, what to do, button text, what the button does)."""
    from ....services import table
    from ....services.characters import view
    from ....services.portal import tunnel
    from ....services.portal.controller import portal
    chars = view.roster()
    v = rt().battle.view()
    b = table.bot_view()
    host = window.host
    return [
        (bool(chars), tr("Make the characters"),
         tr("The creation wizard follows the Player's Handbook step by step; exported HTML sheets can be imported."),
         tr("New character…"), lambda: host.open_page("characters.roster", "party")),
        (any(c.get("owner") for c in chars), tr("Give each character to its player"),
         tr("In Party, drag a character onto its player: that player's portal link shows it."),
         tr("Open Party"), lambda: host.open_page("characters.roster", "party")),
        (bool(v["combatants"]), tr("Set up a battle"),
         tr("On the Battle map in ✏ Edit: drag creatures from the drawer, draw walls, drop props. Save it as an encounter "
            "from the initiative order beside it to load it at the table."), tr("Open the Battle map"), lambda: window.apply_preset("Battle")),
        (bool(tunnel.find()) or portal.running, tr("Share the table with the players"),
         tr("Party ▸ Player portal: one download from Cloudflare, then each player gets a personal link to the live map "
            "and their character. The address changes each time you start sharing."),
         tr("Open the portal"), lambda: host.open_page("characters.roster", "portal")),
        (b["token_set"], tr("Sound in Discord (optional)"),
         tr("Audio ▸ Discord bot: paste a bot token (discord.com/developers ▸ New Application ▸ Bot ▸ Reset Token; turn on "
            "the Server Members Intent), invite it to your server, pick the voice channel."),
         tr("Open Audio"), lambda: host.open_page("audio.manager", "discord")),
    ]


def show(window):
    d = dialogs.Dialog(window, tr("Getting started"), 560)
    for done, title_, text, btn, go in steps(window):
        head = label(("✅ " if done else "⬜ ") + title_, role="good" if done else "")
        f = head.font()
        f.setBold(True)
        head.setFont(f)
        d.body.addLayout(row(head, stretch(), button(btn, lambda go=go: (d.accept(), guard(go)), kind="" if done else "primary")))
        d.body.addWidget(label(text, role="dim", wrap=True))
    d.body.addWidget(label(tr("Help ▸ Keyboard shortcuts (F1) lists the keys; Layout ▸ Battle arranges the windows for a fight."),
                           role="dim", wrap=True))
    d.add_button(tr("Close"), d.accept, default=True)
    rt().settings[SEEN] = True
    rt().save_config()
    d.exec()


@action("help.start", "Getting started…", menu="Help", order=1)
def getting_started(window):
    guard(show, window)


@on_start
def first_run(window):
    """On the very first start (no characters yet), show the checklist once."""
    from ....services.characters import view
    if not rt().settings.get(SEEN) and not view.roster():
        show(window)
