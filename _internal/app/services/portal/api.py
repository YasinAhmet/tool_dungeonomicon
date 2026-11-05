"""What a logged-in player sees and may do on the portal. Every action goes through the same services as the
editor and the Discord bot, so rolls reach the app log, the battle log and the Discord log channel alike.

A player only ever acts on characters they own (rt().players). The team inventory (services/team.py) is shared by the
characters playing this session: their players move items in and out of it, hand them to each other, and lay them on
the battle map (in a running battle, on their turn). In a running battle, on their own turn, attacks and
spells are played out on the target they pick (the battle resolves hits and damage); otherwise they are plain rolls
for the DM to apply. Players may move their own token on their turn when the DM allows it.

Settings (rt().settings["portal"]): what players may do (RIGHTS, every one on unless the DM turned it off). Each is
checked here, where the action is done; the page only hides what a player can't use (state()["rights"]).
"""
import os
import re
import time
import zlib
from typing import Dict, List, Optional

from ...core import events
from ...core.i18n import i18n
from ...core.runtime import rt
from ...rules.character import file_stamp
from ...rules.character import saves as character_saves
from ...rules import engine as E
from ...rules import spellcasting as SC
from ...rules.data import rules
from ..battle import ACTIVE, health_word
from ..battle import geometry as G
from ..battle.drawing import SYMBOLS
from ..battle.icons import BADGES, UI, badge_keys, for_attack, for_item, for_spell
from ..battle.itemsprites import sprite_for
from ..battle.props import OPENS, portal_view as prop_view
from ..battle.rooms import plan as room_plan
from ..battle.sight import light_shapes, terrain
from ..battle.view import VEILS, battle_view, draw_box
from ...rules.document import _item_tip
from ..characters.view import sheet_data
from ..common import ServiceError
from ..world import PACES as WORLD_PACES

# What players may do on the portal, in the DM's Player rights window: (group, [(key, label, what it covers)]).
RIGHTS = [
    ("Maps", [
        ("see_battle", "See the battle map", "The battle map: its walls, pictures and where the creatures stand. "
                                            "Off: players see only the turn order"),
        ("move_tokens", "Players move their token", "Players may move their own token on their turn"),
        ("battle_actions", "Turns play out on the map", "On their turn, attacks and spells are played out on the target they pick"),
        ("see_world", "See the world map", "The world map you sent them, the party on it and its route; a tap pings it for everyone"),
    ]),
    ("Dice and the character sheet", [
        ("roll", "Roll dice", "Checks, saves, initiative, death saves, attack and damage rolls and the dice in the feed "
                              "(a turn played out on the map is not a free roll)"),
        ("rest", "Take short and long rests", "Rest from their page and spend hit dice"),
        ("edit_hp", "Change their hit points", "Take damage, heal and set temporary hit points by hand"),
        ("track_uses", "Mark spell slots and uses", "Spend and get back spell slots and feature uses by hand"),
        ("edit_notes", "Write their notes and story", "Their character's notes, personality, ideals, bonds, flaws and backstory"),
    ]),
    ("Items", [
        ("write_items", "Write in items and coins", "Add, change and remove items and coins, their own and the team's"),
        ("trade_items", "Hand items around", "Give items to each other, use the team inventory, add meals to the group's "
                                            "food and lay items on the map"),
    ]),
    ("The table", [
        ("chat", "Chat with the table", "Say things in the table feed"),
        ("commands", "Use /commands", "The same text commands as on Discord, typed in the feed (each still needs its own right)"),
        ("team_notes", "Team notes", "Read and write the team notes"),
        ("duel", "Join duels", "The Duel tab while duel mode is open"),
    ]),
    ("Music", [
        ("now_playing", "Show the Spotify song", "Show players the song Spotify is playing (with a heart button)"),
        ("music", "Players can listen", "Players can listen to the music on the page"),
    ]),
]
DEFAULTS = {k: True for _g, rows in RIGHTS for k, _l, _t in rows}
# A player's action -> the right it needs (attack and cast: only when they are free rolls, see _act).
ACTION_RIGHTS = {"roll": "roll", "check": "roll", "save": "roll", "damage": "roll", "initiative": "roll", "death_save": "roll",
                 "rest": "rest", "prepare_options": "rest", "hit_die": "rest", "hp": "edit_hp",
                 "slot": "track_uses", "resource": "track_uses",
                 "note_add": "edit_notes", "note_edit": "edit_notes", "note_remove": "edit_notes", "details": "edit_notes",
                 "add_item": "write_items", "edit_item": "write_items", "remove_item": "write_items", "coins": "write_items",
                 "team_add": "write_items", "team_edit": "write_items", "team_remove": "write_items",
                 "give": "trade_items", "team_put": "trade_items", "team_take": "trade_items", "team_drop": "trade_items",
                 "drop_item": "trade_items", "give_meal": "trade_items",
                 "chat": "chat", "command": "commands", "world_ping": "see_world", "heart": "now_playing",
                 "move": "move_tokens"}
# The text commands of the feed -> the right each needs (the rest only show things).
COMMAND_RIGHTS = {"/roll": "roll", "/check": "roll", "/save": "roll", "/initiative": "roll", "/attack": "roll", "/cast": "roll",
                  "/damagechar": "edit_hp", "/healchar": "edit_hp", "/rest": "rest", "/hitdie": "rest",
                  "/additem": "write_items", "/removeitem": "write_items", "/buyitem": "write_items",
                  "/senditem": "trade_items", "/addnote": "edit_notes", "/removenote": "edit_notes"}
REFUSED = {
    "see_battle": "The DM keeps the battle map hidden in this game.",
    "move_tokens": "The DM moves the tokens in this battle.",
    "battle_actions": "The DM plays the battle actions in this game.",
    "see_world": "The DM keeps the world map hidden in this game.",
    "roll": "The DM rolls the dice in this game.",
    "rest": "Ask your DM for a rest.",
    "edit_hp": "The DM keeps track of hit points in this game.",
    "track_uses": "The DM keeps track of spell slots and uses in this game.",
    "edit_notes": "The DM keeps the character notes in this game.",
    "write_items": "The DM writes in items and coins in this game.",
    "trade_items": "Ask your DM to hand items around.",
    "chat": "The DM turned off the chat.",
    "commands": "The DM turned off the /commands.",
    "team_notes": "The DM turned off the team notes.",
    "duel": "The DM turned off the duels for you.",
    "now_playing": "The DM turned that off.",
    "music": "The DM turned that off.",
}
DETAILS = ("personality", "ideal", "bond", "flaw", "appearance", "backstory")
FEED_SHOWN = 80
PAGE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "portal.js")
PAGES = [PAGE] + [os.path.join(os.path.dirname(PAGE), f) for f in ("world.js", "duel.js")]   # every script of the page with S('...') words
_JS_STRING = re.compile(r"""\bS\((['"])((?:\\.|(?!\1).)*?)\1""")
_page_strings: List[str] = []


def page_strings() -> List[str]:
    """Every S('...') text of the page (portal.js) - the page's words are defined only there."""
    if not _page_strings:
        text = ""
        for page in PAGES:
            with open(page, encoding="utf-8") as f:
                text += f.read() + "\n"
        found = [re.sub(r"\\(.)", r"\1", m.group(2)) for m in _JS_STRING.finditer(text)]
        _page_strings.extend(dict.fromkeys(found))
    return _page_strings


def settings() -> dict:
    return {**DEFAULTS, **(rt().settings.get("portal") or {})}


def set_setting(key: str, value):
    set_settings({key: value})


def set_settings(values: Dict[str, bool]):
    """Change some rights at once; the open pages reload with them (events.RIGHTS)."""
    bad = [k for k in values if k not in DEFAULTS]
    if bad:
        raise ServiceError(f"Unknown portal setting '{bad[0]}'.")
    rt().settings.setdefault("portal", {}).update({k: bool(v) for k, v in values.items()})
    rt().save_config()
    rt().bus.emit(events.RIGHTS)


def allowed(key: str) -> bool:
    return bool(settings()[key])


def need(key: str):
    """Refuse when the DM turned this right off (in the player's language: the server translates the message)."""
    if not allowed(key):
        raise ServiceError(REFUSED[key])


# ---------------------------------------------------------------------- reading
def me(uid: int) -> dict:
    r = rt()
    mine = r.characters.characters_of(uid)
    active = r.players.active_of(uid)
    return {"id": str(uid), "name": r.players.name_of(uid) or f"Player {uid}", "characters": mine,
            "active": active if active in mine else (mine[0] if mine else None), "lang": i18n.player_language(uid)}


def _t(uid: int):
    """Translate into the player's language (their /language choice)."""
    lang = i18n.player_language(uid)
    return lambda text: i18n.t(text, lang) if isinstance(text, str) else text


def page_words(lang: str) -> Dict[str, str]:
    return {s: i18n.t(s, lang) for s in page_strings()}


strings = page_words                     # the older name


def battle(uid: int) -> Optional[dict]:
    """The battle as players may see it: enemy hit points in words unless the DM revealed them. What is the same for
    every player is made once per change and language (_board); only their own marks and action bar are theirs."""
    lang = i18n.player_language(uid)
    board = _board(lang)
    t = _t(uid)
    mine = set(rt().characters.characters_of(uid))
    out = [dict(c, mine=c["kind"] == "pc" and c["character"] in mine,
                character=c["character"] if c["kind"] == "pc" and c["character"] in mine else None) for c in board["combatants"]]
    pend = board["pending"]
    if pend is not None:                                # a question waits: asked live (one past its time is let pass)
        pend = rt().battle.pending()
        if pend:
            pend = dict(pend, text=t(pend["text"]), mine=pend.get("character") in mine,
                        options=[dict(o, label=t(o["label"]), **{k: t(o[k]) for k in ("group", "choice") if o.get(k)}) for o in pend["options"]])
    return dict(board, combatants=out, my_turn=any(c["mine"] and c["turn"] for c in out), pending=pend,
                actions=_actions(uid, out))


_BOARDS: Dict[tuple, tuple] = {}                       # (battle, language) -> (view, settings, board)


def _board(lang: str, duel: bool = False) -> dict:
    """Everything of the battle that is the same for every player of a language, made once per view of the battle (a
    new one after every change): six pages reloading after a move don't each ask the battle for its zones and rules.
    (The battle this thread works on: the duel's for a duel request, portal/duel.py - always shown.)"""
    view = battle_view(shared=True)
    s = settings() if not duel else dict(settings(), see_battle=True)
    key = (id(rt().battle), lang)
    hit = _BOARDS.get(key)
    if hit and hit[0] is view and hit[1] == s:
        return hit[2]
    t = lambda text: i18n.t(text, lang) if isinstance(text, str) else text    # noqa: E731
    turn = view.get("turn")
    out = []
    for c in view["combatants"]:
        shown = c["kind"] == "pc" or bool(c.get("revealed")) or bool(view.get("reveal_hp"))
        out.append({"id": c["id"], "name": c["name"], "kind": c["kind"], "ally": c.get("faction") == 1, "ring": c.get("faction_color"),
                    "pos": c.get("pos"), "span": max(1, int(c.get("span") or 1)), "init": c.get("init"),
                    "box": list(draw_box(view, c)) if c.get("pos") else None, "tiny": bool(c.get("tiny")),
                    "hp": c["hp"] if shown else None, "max_hp": c["max_hp"] if shown else None,
                    "health": t(health_word(c["hp"], c["max_hp"])), "out": bool(c.get("out")),
                    "veil": list(VEILS[c["veil"]]) if c.get("veil") and not c.get("out") else None,   # [opacity, size, tint]
                    "conditions": [t(x) for x in c.get("conditions") or []], "token": token_stamp(c.get("token")), "framed": bool(c.get("framed")),
                    "badges": badge_keys(c.get("conditions"), c.get("effects")),     # untranslated: conditions, Bless, Rage... on the map
                    "conc": {"spell": t(c["concentrating"]["spell"]), "src": c["concentrating"].get("src") or "arcane"} if c.get("concentrating") else None,
                    "dsaves": c.get("dsaves"),                                     # a dying character's death save pips
                    "held_by": sorted({e["conc_by"] for e in c.get("effects") or [] if e.get("conc_by") is not None} |
                                      ({c["summon_conc"]} if c.get("summon_conc") is not None else set())),
                    "turn": c["id"] == turn, "character": c.get("character")})
    b = rt().battle
    board = {"name": view["name"], "status": view["status"], "round": view["round"], "map": view["map"],
             "combatants": out, "turn": turn, "log": [t(x) for x in list(view.get("log") or [])[-25:]], "settings": s,
             "drawings": [d for d in view.get("drawings") or [] if not (d.get("type") == "image" and d.get("hidden"))], "symbols": {k: v[0] for k, v in SYMBOLS.items()},
             "badge_look": BADGES,                                          # a badge (condition or effect): [picture, colour]
             "rooms": room_plan(view.get("drawings")),
             "lights": light_shapes(terrain(view.get("drawings"))),        # lit areas (shadows cast): shown when the map is dim or dark
             "props": prop_view()["props"], "props_smooth": prop_view()["smooth"], "opens": list(OPENS),
             "ground": [{"id": g["id"], "name": g["name"], "label": t(g["name"]), "qty": g["qty"], "x": g["x"], "y": g["y"], "at": g.get("at"),
                         "sprite": sprite_for(g["name"])}
                        for g in view.get("ground") or []],
             "fx": list(view.get("fx") or [])[-60:], "fx_n": view.get("fx_n", 0),
             "zones": [dict(z, name=t(z["name"]), note="") for z in b.zones_view() if not z["hidden"]], "rules": b.rules_view(),
             "pending": b.pending(),                                        # (only whether one waits: battle() asks it live)
             "hidden": not s["see_battle"]}
    if board["hidden"]:                         # the DM keeps the map to themselves: the turn order, nothing of where
        board.update(combatants=[dict(c, pos=None, box=None) for c in out], drawings=[], props=[], ground=[], fx=[], zones=[],
                     rooms=room_plan([]), lights=light_shapes(terrain([])))
    if len(_BOARDS) > 48:                                                  # (closed duels')
        _BOARDS.clear()
    _BOARDS[key] = (view, s, board)
    return board


def _actions(uid: int, combatants: List[dict]) -> Optional[dict]:
    """The action bar of the player's active character in the battle: everything it can do now (see battle.menu)."""
    if not settings()["battle_actions"]:
        return None
    name = rt().players.active_of(uid)
    me_ = next((c for c in combatants if c["mine"] and (c.get("character") == name or not name)), None)
    return _actions_for(uid, me_["id"]) if me_ else None


def _actions_for(uid: int, cid: int) -> Optional[dict]:
    """A combatant's action bar in the player's language."""
    t = _t(uid)
    try:
        a = dict(rt().battle.available_actions(cid, shared=True))           # only its top level is replaced below
    except ServiceError:
        return None

    def item(i):
        return dict(i, label=t(i["name"]), why=t(i["why"]) if i.get("why") else None, tip=t(i.get("tip") or ""))
    a["groups"] = [dict(g, title=t(g["title"]), items=[item(i) for i in g["items"]]) for g in a["groups"]]
    a["spells"] = [dict(g, title=t(g["title"]), items=[item(i) for i in g["items"]]) for g in a["spells"]]
    a["reactions"] = [dict(r, label=t(r["label"])) for r in a["reactions"]]
    a["toggles"] = _toggles(t, a.get("toggles") or [])
    a["pending"] = None
    return a


def _kept(memo: dict, key, build):
    """build() once per key (the newest only: a key names everything the result depends on). Shared, never changed."""
    hit = memo.get("kv")                               # one tuple: another thread never sees a key with the old value
    if hit is not None and hit[0] == key:
        return hit[1]
    value = build()
    memo["kv"] = (key, value)
    return value


_SHEETS: Dict[str, dict] = {}                          # name -> {"kv": (key, value)}: a character's page sheet


def character(uid: int, name: Optional[str]) -> Optional[dict]:
    """The player's own character, reduced to what the page shows. Built again only when the character's file or the
    player's language changes (every page reloads after each move of a battle)."""
    if not name or name not in rt().characters.characters_of(uid):
        return None
    lang = i18n.player_language(uid)
    key = (lang, character_saves(), file_stamp(name), rt().bus.counts[events.RULES])
    return _kept(_SHEETS.setdefault(name, {}), key, lambda: _character(uid, name))


def _character(uid: int, name: str) -> dict:
    t = _t(uid)
    d = sheet_data(name)
    c = rt().characters.get(name)
    doc = d["doc"]
    return {"name": d["name"], "line": t(d["line"]),
            "vitals": [{"label": t(v["label"]), "value": v["value"], "tip": t(v.get("tip", ""))} for v in doc["vitals"]],
            "abilities": [{"key": a["key"], "name": a["name"], "label": t(a["name"]), "score": a["score"], "mod": a["mod"],
                           "save": a["save"], "save_prof": a["save_prof"], "tip": t(a.get("tip") or ""),
                           "save_tip": t(a.get("save_tip") or "")} for a in doc["abilities"]],
            "skills": [{"name": s["name"], "label": t(s["name"]), "ability": t(s["ability"]), "bonus": s["bonus"],
                        "prof": s["marker"] != "○", "tip": t(s.get("tip") or "")} for s in doc["skills"]],
            "attacks": [{"name": a["weapon"] or a["name"], "label": t(a["name"]), "attack": a["attack"], "damage": t(a["damage"]),
                         "icon": for_attack(a["weapon"] or a["name"]),
                         "tip": t(a.get("tip") or "") + ("\n" + t(a["notes"]) if a.get("notes") else "")}
                        for a in doc["attacks"]],
            "spells": [{"level": g["level"], "title": t(g["title"]),
                        "spells": [{"name": s["name"], "label": t(s["name"]), "ritual": s["ritual"], "time": t(s["time"]),
                                    "icon": for_spell(s["name"]), "range": s["range"], "text": t(s["text"])[:900]}
                                   for s in g["spells"]]} for g in doc["spells"]],
            "slots": [{"key": k, "label": t(lab), "total": n, "left": left} for k, lab, n, left in doc["slot_rows"]],
            "casting": [{"label": t(k["class"]), "dc": k["dc"], "attack": k["attack"]} for k in doc.get("casting") or []],
            "current_hp": c.current_hp, "max_hp": c.max_hp, "temp_hp": d["temp_hp"],
            "conditions": [t(x) for x in d["conditions"]], "exhaustion": d["exhaustion"], "inspiration": d["inspiration"],
            "condition_info": [{"name": x, "label": t(x), "text": t((rules.conditions.get(x) or {}).get("text", ""))}
                               for x in d["conditions"]],
            "death_saves": d["death_saves"], "hit_dice": d["hit_dice"], "xp": d["xp"], "next_xp": d["next_xp"],
            "resources": [{"name": x["name"], "label": t(x["name"]), "max": x["max"], "used": x["used"],
                           "recharge": x["recharge"]} for x in doc["resource_rows"]],
            "defense": [t(x) for x in doc.get("defense_notes") or []],
            "proficiencies": [{"title": t(g["title"]), "items": [t(i["name"]) for i in g["items"]]} for g in doc["proficiency_list"]],
            "features": [{"source": t(g["source"]), "items": [{"name": f["name"], "label": t(f["name"]), "level": f.get("level"),
                                                               "text": t(f.get("text") or "")} for f in g["items"]]}
                         for g in doc["features"]],
            "inventory": [{"name": e["name"], "label": t(e["name"]), "icon": for_item(e["name"]), "qty": e.get("qty", 1),
                           "equipped": bool(e.get("equipped")), "attuned": bool(e.get("attuned")), "attunable": e["attunable"], "wearable": e["wearable"] and not e["usable"],
                           "usable": e["usable"], "note": e.get("note") or "",
                           "tip": t(e.get("tip") or "") + (f"\n\n{e['note']}" if e.get("note") else "")} for e in d["inventory"]],
            "currency": d["currency"], "weight": t(str(doc.get("weight") or "")),
            "notes": [{"id": n["id"], "text": n["text"]} for n in d["notes"]],
            "toggles": _toggles(t, d.get("toggles") or []),
            "details": {k: v for k, v in d["details"].items() if k in DETAILS}}


def team(uid: int) -> Optional[dict]:
    """The team inventory and who shares it, for a player one of whose characters does (None for anyone else)."""
    members = rt().team.members()
    mine = set(rt().characters.characters_of(uid))
    if not mine & set(members):
        return None
    t = _t(uid)
    placed = {c.get("character") for c in battle_view(shared=True)["combatants"] if c["kind"] == "pc" and c.get("pos")}
    f = rt().world.food()
    return {"items": [{"name": e["name"], "label": t(e["name"]), "icon": for_item(e["name"]), "qty": e["qty"], "note": e["note"],
                       "food": e["food"], "tip": t(_item_tip(None, e)) + (f"\n\n{e['note']}" if e["note"] else "")}
                      for e in rt().team.items()],
            "supplies": {k: f[k] for k in ("meals", "days_left", "mouths", "day")},       # the World map's food: the same stock
            "members": [{"name": n, "mine": n in mine, "on_map": n in placed} for n in members]}


def notes(uid: int) -> Optional[dict]:
    """The team notes, for any player with a character (None for anyone else, or when the DM turned them off):
    `editing` names who has a note open (`mine`: this player's own page), `can_delete`: the player wrote it."""
    if not rt().characters.characters_of(uid) or not allowed("team_notes"):
        return None
    own = _note_owner(uid)
    return {"notes": [{**{k: n[k] for k in ("id", "title", "text", "by", "at", "edited_by", "edited_at")},
                       "can_delete": n["uid"] == uid,
                       "editing": n["editing"] and {"who": n["editing"]["who"], "left": n["editing"]["left"],
                                                    "mine": n["editing"]["owner"] == own}}
                      for n in rt().notes.all()]}


def _note_owner(uid: int) -> str:
    return f"p{uid}"


_WORLDS: Dict[int, dict] = {}                          # uid -> {"kv": (key, value)}


def world(uid: int) -> dict:
    """The world map as the players have been sent it (the picture, its marks and names), the party on it (live),
    its route, and the group's food with what each character carries. Built again only after a change of the world,
    the team's pack or a character."""
    n = rt().bus.counts
    key = (i18n.player_language(uid), tuple(rt().characters.characters_of(uid)), n[events.WORLD], n[events.TEAM],
           n[events.CHARACTERS], character_saves(), allowed("see_world"))
    return _kept(_WORLDS.setdefault(uid, {}), key, lambda: _world(uid))


def _world(uid: int) -> dict:
    w = rt().world
    t = _t(uid)
    shown = allowed("see_world")                # off: the group's food still, nothing of the map or where the party is
    pub = w.published() if shown else None
    mine = set(rt().characters.characters_of(uid))
    p = w.party() if shown else {"pos": None, "trail": [], "route": [], "leg": None}
    f = w.food()
    pace = w.settings()["pace"]
    return {"map": {"id": w.mid, "v": pub["v"], "w": pub["w"], "h": pub["h"], "name": pub["name"], "img": f"/worldimg/{w.shown_key()}.webp",
                    "marks": [_terrain(m) for m in pub["marks"]], "labels": pub["labels"], "lines": pub.get("lines") or [],
                    "stamps": _stamps(pub["marks"]), "look": pub.get("look") or "parchment",
                    "grid": pub.get("grid"), "scale_bar": pub.get("scale_bar"),
                    "plaques": bool(pub.get("plaques"))} if pub else None,
            "hidden": not shown,
            "party": p, "route": w.route_info() if shown else {"miles": 0, "days": 0}, "near": w.nearest(*p["pos"], marks=pub["marks"]) if p["pos"] and pub else None,
            "mpp": w.miles_per_px(), "pace": t(pace), "pace_miles": WORLD_PACES[pace],
            "food": {**{k: f[k] for k in ("meals", "day", "average", "days_left", "mouths", "today")},
                     "log": [dict(e, why=t(e["why"])) for e in f["log"][-6:]]},
            "packs": [{"character": m["character"], "mine": m["character"] in mine, "meals": m["meals"],
                       "items": [{"name": e["name"], "label": t(e["name"]), "qty": e["qty"]} for e in m["items"]]}
                      for m in w.member_food()]}


def _stamps(marks: List[dict]) -> Dict[str, list]:
    """How the stamps on the map are drawn: {key: [height in map pixels, anchor]} ('b': standing on its point); an ink
    stamp's also [..., width, paper, ink] (its shapes as SVG path data: the page draws them itself)."""
    from ..world import ART, stamps
    out = {}
    for m in marks:
        e = stamps.get(m.get("art") if m.get("kind") == ART else (stamps.terrain_art(m) or ("",))[0])
        if e and e["key"] not in out:
            out[e["key"]] = [e["h"], e["anchor"]] + ([e["w"], e["p"], e["i"]] if e.get("vector") else [])
    return out


def _terrain(m: dict) -> dict:
    """A sprayed mountain, hill or tree with the painted picture it is drawn with on the painted look ("pa", scale "ps")."""
    from ..world import stamps
    pic = stamps.terrain_art(m)
    return dict(m, pa=pic[0], ps=round(pic[1], 4)) if pic else m


def world_art_path(key: str) -> Optional[str]:
    """A stamp's picture (the same for everyone: the packs' and the DM's own)."""
    from ..world import stamps
    return stamps.path(key) if re.fullmatch(r"[a-z0-9_]+", key or "") else None


def _toggles(t, toggles: List[dict]) -> List[dict]:
    """Situational feat switches, in the player's language (see rules/combat_feats.py)."""
    return [dict(x, label=t(x["label"]), feat_label=t(x["feat"]), does=t(x["does"]), text=t(x.get("text") or "")) for x in toggles]


PARTS = ("battle", "character", "team", "notes", "feed", "world", "now", "duel", "dbattle")


def state(uid: int, strings: bool = False, parts=None) -> dict:
    """What the page shows. The page's words (`strings`, a few hundred) only when asked: on the first load and after a
    language change - the page keeps them, so the frequent reloads stay small. `parts`: only these of PARTS (the ones
    a change touched; the page keeps the rest) - `me`, `music`, `rights` and `languages` always come."""
    who = me(uid)
    want = set(parts or PARTS)
    out = {"me": who, "music": bool(settings()["music"]),             # players may listen to the table's sound (music.py)
           "rights": settings(),                                       # what the DM lets players do (the page hides the rest)
           "languages": [list(x) for x in i18n.languages()]}
    if "battle" in want:
        out["battle"] = battle(uid)
    if "character" in want:
        out["character"] = character(uid, who["active"])
    if "team" in want:
        out["team"] = team(uid)
    if "notes" in want:
        out["notes"] = notes(uid)
    if "feed" in want:
        out["feed"] = feed(uid)
    if "world" in want:
        out["world"] = world(uid)
    if "now" in want:
        from ..nowplaying import nowplaying
        out["now"] = nowplaying.view() if settings()["now_playing"] else None
    if "duel" in want or "dbattle" in want:
        from . import duel                                      # the Duel tab: its lobby, and its fight while it is on
        on = allowed("duel")                                    # off: as if duel mode were closed
        if "duel" in want:
            out["duel"] = duel.lobby(uid) if on else None
        if "dbattle" in want:
            out["dbattle"] = duel.battle(uid) if on else None
    if strings:
        out["strings"] = page_words(who["lang"])
        out["ui_icons"] = UI                                    # the page's own buttons' pictures (kept with the words)
        out["conditions"] = {i18n.t(n, who["lang"]): i18n.t((c or {}).get("text", ""), who["lang"])   # the feed's hover rules
                             for n, c in ((n, rules.conditions.get(n)) for n in BADGES if n in rules.conditions)}
    return out


def feed(uid: int, since: int = 0) -> List[dict]:
    """The table feed (rolls, XP, chat) in the player's language."""
    t = _t(uid)
    return [{**e, "text": t(e["text"]) if e["kind"] != "chat" else e["text"]}
            for e in rt().feed.since(since, FEED_SHOWN)]


# ---------------------------------------------------------------------- doing
def _mine(uid: int, name: Optional[str]) -> str:
    if not name or name not in rt().characters.characters_of(uid):
        raise ServiceError("That isn't one of your characters.")
    return name


def _combatant(uid: int, name: str) -> Optional[dict]:
    """The character's combatant when the battle is running and it is their turn (battle actions allowed)."""
    if not settings()["battle_actions"]:
        return None
    b = rt().battle
    if b.state()["status"] != ACTIVE:
        return None
    cur = b.current()
    return cur if cur and cur["kind"] == "pc" and cur.get("character") == name else None


def _teammate(name: str, to) -> str:
    """Another character sharing the team inventory (or `name` itself when `to` is empty)."""
    to = str(to or name)
    if to not in rt().team.members():
        raise ServiceError("Only the characters playing this session share items.")
    return to


def _token_at(x: int, y: int, skip: Optional[int] = None) -> Optional[dict]:
    return next((o for o in rt().battle.view()["combatants"] if o["id"] != skip and o.get("pos")
                 and o["pos"][0] <= x < o["pos"][0] + (o.get("span") or 1) and o["pos"][1] <= y < o["pos"][1] + (o.get("span") or 1)), None)


def _tile(a: dict):
    ok = all(str(a.get(k, "")).lstrip("-").isdigit() for k in ("x", "y"))
    return (int(a["x"]), int(a["y"])) if ok else None


def _in_battle(name: str) -> Optional[dict]:
    b = rt().battle
    return next((c for c in b.view()["combatants"] if c["kind"] == "pc" and c.get("character") == name), None)


def act(uid: int, action: str, a: dict):
    """Do one thing for the player; returns the text to show (the roll's result, in the player's language), or data
    (a preview)."""
    if a.get("duel") or action.startswith("duel_"):
        need("duel")
        from . import duel                                      # the duel's lobby, or a battle action on the duel
        out = duel.act(uid, action, a)
    else:
        if action in ACTION_RIGHTS:
            need(ACTION_RIGHTS[action])
        if action.startswith("tnote_"):
            need("team_notes")
        if action == "move":
            need("see_battle")
        out = _act(uid, action, a)
    return out if isinstance(out, dict) else (_t(uid)(out) or "")


def _act(uid: int, action: str, a: dict) -> str:
    r = rt()
    who = r.players.name_of(uid) or "Player"
    adv = a.get("adv") if a.get("adv") in ("advantage", "disadvantage") else None
    if action == "choose":
        r.characters.use(uid, _mine(uid, a.get("character")))
        return ""
    if action == "language":
        i18n.set_player_language(uid, str(a.get("lang")))
        return ""
    if action == "roll":
        res = r.dice.roll(str(a.get("expr") or "")[:60], who, who)
        return f"🎲 {a.get('expr')}: {res.total}" + ("" if res.plain else f" ({res.breakdown})")
    if action == "heart":                         # once per song per session, for the whole table
        from ..nowplaying import nowplaying
        return "" if nowplaying.heart(who, r.feed) else "Someone already loved this song."
    if action == "end_turn":                      # only on your own turn
        b = r.battle
        cur = b.current() if b.state()["status"] == ACTIVE else None
        mine = set(r.characters.characters_of(uid))
        if not cur or cur["kind"] != "pc" or cur.get("character") not in mine:
            raise ServiceError("It isn't your turn.")
        b.next_turn()
        return ""
    if action == "chat":
        r.feed.say(who, str(a.get("text") or ""), from_dm=False, user_id=uid)
        return ""
    if action == "world_ping":                    # a ripple on everyone's world map (the DM's too)
        active = r.players.active_of(uid)
        r.world.ping(float(a["x"]), float(a["y"]), active if active in r.characters.characters_of(uid) else who, uid)
        return ""
    if action.startswith("tnote_"):               # the team notes: anyone with a character reads and adds to them
        if not r.characters.characters_of(uid):
            raise ServiceError("Ask your DM to give you a character.")
        active = r.players.active_of(uid)
        by = active if active in r.characters.characters_of(uid) else who
        own = _note_owner(uid)
        if action == "tnote_add":
            r.notes.add(a.get("title"), a.get("text"), by=by, uid=uid)
        elif action == "tnote_begin":             # opens it for editing: no one else can until it is saved or cancelled
            n = r.notes.begin(a.get("id"), own, by)
            return {"title": n["title"], "text": n["text"]}
        elif action == "tnote_hold":              # the editing page, still open
            return {"held": r.notes.hold(a.get("id"), own)}
        elif action == "tnote_save":
            r.notes.save(a.get("id"), own, a.get("title"), a.get("text"), by=by)
        elif action == "tnote_cancel":
            r.notes.cancel(a.get("id"), own)
        elif action == "tnote_remove":
            r.notes.remove(a.get("id"), own, by=by, uid=uid)
        else:
            raise ServiceError("Unknown action.")
        return ""
    if action == "give_meal":                     # one of your character's meals into the group's food
        r.world.give_meal(_mine(uid, a.get("who") or a.get("character")), a.get("item") or None)
        return "Added a meal to the group's food."
    if action == "command":                       # the same text commands as Discord (/hp, /cast, /inventory...)
        text = str(a.get("text") or "").strip()[:300]
        if not text.startswith("/"):
            raise ServiceError("Commands start with / (try /help).")
        if text.split()[0].lower() in ("/sync",):
            raise ServiceError("Only the DM can use that command.")
        if text.split()[0].lower() in COMMAND_RIGHTS:
            need(COMMAND_RIGHTS[text.split()[0].lower()])
        if a.get("character"):
            r.characters.use(uid, _mine(uid, a["character"]))
        return r.command_processor.process(text, uid, who) or ""
    name = _mine(uid, a.get("character"))
    cs = r.characters
    target = a.get("target")
    target = int(target) if str(target or "").isdigit() else None
    if action == "check":
        return cs.roll_check(name, str(a["what"]), adv, who).text
    if action == "save":
        return cs.roll_save(name, str(a["ability"]), adv, who).text
    if action == "attack":
        c = _combatant(uid, name)
        if c is not None:
            return r.battle.pc_attack(c["id"], str(a["weapon"]), adv, target)
        need("roll")
        return cs.attack_roll_and_damage(name, str(a["weapon"]), adv, who).text
    if action == "damage":
        return cs.roll_damage(name, str(a["weapon"]), bool(a.get("crit")), False, who).text
    if action == "cast":
        slot = a.get("slot") or None
        c = _combatant(uid, name)
        if c is not None:
            return r.battle.pc_spell(c["id"], str(a["spell"]), slot, bool(a.get("ritual")), adv, target)
        need("roll")
        return cs.cast_spell(name, str(a["spell"]), slot, bool(a.get("ritual")))["text"]
    if action in ("do", "preview", "reaction_mode"):
        c = _in_battle(name)
        if c is None:
            raise ServiceError(f"{name} isn't in the battle.")
        targets = [int(x) for x in a.get("targets") or [] if str(x).lstrip("-").isdigit()]
        point = a.get("point")
        point = [float(point[0]), float(point[1])] if isinstance(point, list) and len(point) == 2 else None
        item = str(a.get("item") or "")
        if action == "reaction_mode":
            r.battle.set_reaction_mode(c["id"], str(a.get("family")), str(a.get("mode")))
            return ""
        if action == "preview":
            kind, _, arg = item.partition(":")
            if kind == "spell":
                out = r.battle.cast_check(c["id"], arg, a.get("slot") or None, targets or None, point)
                info = r.battle.spell_info(arg, int(a["slot"]) if str(a.get("slot") or "").isdigit() else None)
                out["options"] = info.get("options") or []
                out["why"] = _t(uid)(out["why"]) if out.get("why") else None
                return out
            if kind == "move" and point:
                pv = r.battle.path_preview(c["id"], int(point[0]), int(point[1]))
                pv["why"] = _t(uid)(pv["why"]) if pv.get("why") else None
                return pv
            return {"ok": True}
        need("battle_actions")
        return r.battle.act(c["id"], item, targets or None, point, a.get("slot") or None, a.get("dtype") or None,
                            a.get("option") or None, adv, bool(a.get("ritual")), a.get("metamagic") or None)
    if action == "react":
        p = r.battle.pending()
        mine = set(r.characters.characters_of(uid))
        if not p or p.get("character") not in mine or int(a.get("rid") or 0) != p["rid"]:
            raise ServiceError("Nothing is waiting for your answer.")
        return r.battle.react(p["rid"], a.get("choice") or None)
    if action == "toggle":                        # a situational feat's switch (Great Weapon Master, Sentinel...)
        value = a.get("value")
        cs.set_toggle(name, str(a.get("key")), value if isinstance(value, (bool, str)) else bool(value))
        return ""
    if action == "death_save":
        out = r.battle.roll_death_save(name)                # rolled on every screen when the battle rolls async
        return out if out is not None else cs.death_save(name).text
    if action == "hit_die":
        roll, healed = cs.spend_hit_die(name, a.get("cls") or None)
        return f"🎲 {name}: hit die {roll}, +{healed} HP"
    if action == "use_item":
        c = _in_battle(name)
        if c is not None and r.battle.b.get("status") == "active" and r.battle.use_options(c) and \
                any(o["value"].lower() == str(a["item"]).lower() for o in r.battle.use_options(c)):
            return r.battle.use_item(c["id"], str(a["item"]))      # in a fight: the Use an Object action, with its effect
        return cs.use_item(name, str(a["item"]))
    if action == "drop_item":                     # onto the battle map beside your token (on a creature there: given to it)
        n = int(a.get("amount") or 1)
        c = _in_battle(name)
        if c is None or not c.get("pos"):
            cs.remove_item(name, str(a["item"]), n)
            return ""
        x, y = _tile(a) or c["pos"]
        tok = _token_at(x, y, c["id"])
        near = G.distance_to_tile(c["pos"], c.get("span") or 1, (x, y)) <= 5
        if tok and (near or r.battle.state()["status"] != ACTIVE):     # out of a fight: to any token on the map
            return r.battle.hand_item(name, str(a["item"]), n, tok["id"])
        if not near:
            raise ServiceError("Drop it next to you.")
        r.battle.drop_item(str(a["item"]), n, x, y, character=name)
        return ""
    if action == "give":                          # from your pack to a teammate's
        to = _teammate(name, a.get("to"))
        if to == name:
            raise ServiceError(f"{name} already has it.")
        cs.send_item(name, to, str(a["item"]), int(a.get("amount") or 1))
        return ""
    if action == "team_put":                      # from your pack into the team inventory
        _teammate(name, None)
        r.team.put(name, str(a["item"]), int(a.get("amount") or 1))
        return ""
    if action == "team_take":                     # from the team inventory into your pack (or a teammate's)
        _teammate(name, None)
        r.team.take(str(a["item"]), int(a.get("amount") or 1), _teammate(name, a.get("to")), by=name)
        return ""
    if action == "team_drop":                     # from the team inventory onto the battle map (a creature there gets it)
        _teammate(name, None)
        if r.battle.state()["status"] == ACTIVE:
            cur = r.battle.current()
            if not cur or cur["kind"] != "pc" or cur.get("character") not in r.characters.characters_of(uid):
                raise ServiceError("In a fight you can lay team items on the map on your turn.")
        at = _tile(a)
        if not at:
            raise ServiceError("Put it on a tile of the map.")
        tok = _token_at(*at)
        if tok:
            return r.team.hand(str(a["item"]), int(a.get("amount") or 1), tok["id"], by=name)
        r.team.drop(str(a["item"]), int(a.get("amount") or 1), at[0], at[1], by=name)
        return ""
    if action == "add_item":                      # a quick entry: anything the character picked up, with a description
        cs.add_item(name, str(a.get("item") or ""), int(a.get("amount") or 1), note=f"{name} writes in {a.get('item')}",
                    desc=str(a.get("note") or "") or None)
        return ""
    if action == "edit_item":                     # its count, description or name
        cs.edit_item(name, str(a["item"]), a.get("qty"), a.get("note"), a.get("new_name"))
        return ""
    if action == "team_add":                      # a quick entry into the team inventory
        _teammate(name, None)
        r.team.add(str(a.get("item") or ""), int(a.get("amount") or 1), str(a.get("note") or ""), by=name)
        return ""
    if action == "team_edit":
        _teammate(name, None)
        r.team.edit(str(a["item"]), a.get("qty"), a.get("note"), a.get("new_name"), by=name)
        return ""
    if action == "team_remove":                   # used up, sold, lost
        _teammate(name, None)
        r.team.remove(str(a["item"]), int(a.get("amount") or 1), by=name)
        return ""
    if action == "remove_item":                   # like /removeitem: dropped, sold off-screen, used up...
        n = int(a.get("amount") or 1)
        cs.remove_item(name, str(a["item"]), n)
        return ""
    if action == "coins":                         # {"coins": {"gp": -5, "sp": 3}}
        delta = {k: int(v) for k, v in (a.get("coins") or {}).items() if k in E.COINS and int(v)}
        if not delta:
            raise ServiceError("Enter the amount first.")
        cs.adjust_currency(name, **delta)
        return ""
    if action == "hp":                            # like /damagechar and /healchar
        amount = int(a.get("amount") or 0)
        kind = a.get("kind")
        c = _in_battle(name) if r.battle.state()["status"] == ACTIVE else None
        if kind in ("damage", "heal") and c is not None:
            getattr(r.battle, kind)(c["id"], amount)  # in battle: concentration checks and the battle log
        elif kind == "damage":
            cs.damage(name, amount)
        elif kind == "heal":
            cs.heal(name, amount)
        elif kind == "temp":
            cs.set_temp_hp(name, amount)
        else:
            raise ServiceError("Unknown hit point change.")
        return ""
    if action == "prepare_options":               # what the long rest lets each class prepare (a preview)
        return {"classes": prepare_options(uid, name)}
    if action == "rest":
        prep = a.get("prepare")
        if a.get("kind") == "long":
            cs.long_rest(name, {str(k): list(v) for k, v in prep.items()} if isinstance(prep, dict) else None)
        else:
            cs.short_rest(name)
        return f"🛌 {name}: {'long' if a.get('kind') == 'long' else 'short'} rest"
    if action == "equip":
        cs.set_equipped(name, str(a["item"]), bool(a.get("on")))
        return ""
    if action == "attune":
        cs.set_attuned(name, str(a["item"]), bool(a.get("on")))
        return ""
    if action == "slot":
        (cs.use_slot if a.get("use") else cs.restore_slot)(name, str(a["key"]))
        return ""
    if action == "resource":
        cs.use_resource(name, str(a["resource"]), 1 if a.get("use") else -1)
        return ""
    if action == "note_add":
        cs.add_note(name, str(a.get("text") or "")[:2000])
        return ""
    if action == "note_edit":
        cs.edit_note(name, int(a["id"]), str(a.get("text") or "")[:2000])
        return ""
    if action == "note_remove":
        cs.remove_note(name, int(a["id"]))
        return ""
    if action == "details":
        cs.update_details(name, **{k: str(v)[:4000] for k, v in (a.get("fields") or {}).items() if k in DETAILS})
        return ""
    if action == "initiative":
        return f"⚡ {name}: initiative {r.battle.roll_for_character(name, adv)}"
    if action == "move":                          # (the rights it needs: act)
        c = next((x for x in r.battle.view()["combatants"] if x["kind"] == "pc" and x.get("character") == name), None)
        if c is None:
            raise ServiceError(f"{name} isn't in the battle.")
        cur = r.battle.current()
        if r.battle.state()["status"] == ACTIVE and (not cur or cur["id"] != c["id"]):
            raise ServiceError("You can move your token on your turn.")
        if c.get("pos"):                                     # out of combat too: around the walls, any distance
            return r.battle.walk(c["id"], int(a["x"]), int(a["y"]))
        r.battle.place(c["id"], int(a["x"]), int(a["y"]))
        return ""
    raise ServiceError(f"Unknown action '{action}'.")


def prepare_options(uid: int, name: str) -> List[dict]:
    """The long rest's spell picker: per spellcasting class, its spells to prepare by level (always-prepared ones among
    them), how many it may prepare and what is prepared now; a class that knows its spells is only named."""
    t = _t(uid)
    out = []
    for k in SC.prepare_choices(rt().characters.get(name)):
        row = {"class": k["class"], "label": t(k["class"]), "prepares": k["prepares"]}
        if k["prepares"]:
            levels: Dict[int, list] = {}
            for n in k["pool"]:
                s = rules.spell(n)
                levels.setdefault(s["level"], []).append({
                    "name": n, "label": t(n), "school": t(s["school"]), "time": t(s["casting_time"]), "range": s["range"],
                    "ritual": s["ritual"], "conc": s["concentration"], "icon": for_spell(n), "text": t(s["text"])[:900]})
            row.update(limit=k["limit"], spellbook=k["spellbook"], always=k["always"], prepared=k["prepared"],
                       levels=[{"level": lv, "title": t(f"{E.ordinal(lv)} level"), "spells": sp} for lv, sp in sorted(levels.items())])
        else:
            row["known"] = len(k["known"])
        out.append(row)
    return out


def world_image_path(uid: Optional[int], key: str) -> Optional[str]:
    """The world map's picture the players were sent ("<map>_<version>.webp")."""
    return rt().world.shown_file(key.removesuffix(".webp")) if uid and allowed("see_world") else None


def map_image_path(uid: int, key: str) -> Optional[str]:
    """A picture on the battle map, for a player: only one that's on the map and not hidden from them."""
    if not uid:
        return None
    duels = [r.battle for r in list(rt().duel.rooms.values())]       # (or one on a duel's map)
    for b in ([rt().battle] if allowed("see_battle") else []) + duels:
        if any(d.get("type") == "image" and d.get("img") == key and not d.get("hidden") for d in b.drawings()):
            return b.image_file(key)
    return None


def token_stamp(path: Optional[str]) -> str:
    """A short name of a token picture's version ('' for none): the page keeps a picture by it, so a new portrait (or
    another creature under the same id in the next battle) is fetched again."""
    if not path:
        return ""
    now = time.monotonic()
    hit = _STAMPS.get(path)
    if hit and now - hit[0] < 2.0:                     # looked at for every page after every change: once in 2 s is plenty
        return hit[1]
    try:
        stamp = format(zlib.crc32(f"{path}|{os.path.getmtime(path)}".encode("utf-8")), "x")
    except OSError:
        stamp = ""
    _STAMPS[path] = (now, stamp)
    return stamp


_STAMPS: Dict[str, tuple] = {}                         # token picture -> (checked at, stamp)


def token_path(uid: int, cid: int, duel: Optional[int] = None) -> Optional[str]:
    if duel:                                                    # a token on that duel lobby's map
        room = rt().duel.rooms.get(duel)
        if room is None:
            return None
        with rt().duel.scope(room):
            return token_path(uid, cid)
    view = battle_view(shared=True)
    c = next((x for x in view["combatants"] if x["id"] == cid), None)
    return c.get("token") if c else None


def roster_links(base_url: str, presence: Optional[Dict[int, dict]] = None) -> List[dict]:
    """[{id, name, characters, link, online, last_seen, discord}] - every player who owns a character, with their personal
    portal link and whether their page is open now (last_seen: epoch seconds of their last request, 0 = not seen);
    discord: False for a player added by hand (the DM sends them the link)."""
    from .access import access
    if presence is None:
        from .controller import portal
        presence = portal.presence()
    out = []
    for uid, p in sorted(rt().players.all().items(), key=lambda kv: (kv[1].get("name") or "").lower()):
        chars = rt().characters.characters_of(uid)
        if chars:
            seen = presence.get(int(uid)) or {}
            out.append({"id": uid, "name": p.get("name") or str(uid), "characters": chars,
                        "link": f"{base_url.rstrip('/')}/?k={access.key_for(uid)}" if base_url else "",
                        "online": bool(seen.get("online")), "last_seen": float(seen.get("last_seen") or 0),
                        "discord": not p.get("manual")})
    return out
