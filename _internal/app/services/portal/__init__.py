"""The player portal: a small web page players open in their browser to follow the battle map and play their own
character (rolls, attacks, spells, initiative, moving their token on their turn).

    access.py   one secret link per player (data/portal_access.json) - the key in the link is the login
    api.py      what a player may see and do; everything goes through the same services the editor uses
    server.py   the local web server (127.0.0.1 only) with live updates (server-sent events)
    music.py    the table's sound (the DM's streamed apps and loops) as an Ogg Opus stream players listen to
    tunnel.py   Cloudflare quick tunnel: a public https address for the local server, no router setup
    static/     the page itself (plain HTML/CSS/JS, no build step)

The portal is off until the DM starts it from the Player portal window; nothing listens otherwise.
"""
