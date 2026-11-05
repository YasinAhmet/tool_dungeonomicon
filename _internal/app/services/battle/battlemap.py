"""The battle map as text (for Discord's /battlemap): a grid of initiative numbers and the list below it."""
from typing import List

from .constants import ACTIVE, ENDED, health_word

MAX_COLS, MAX_ROWS = 24, 16


def col_name(i: int) -> str:
    """0 -> A, 25 -> Z, 26 -> AA ..."""
    out = ""
    i += 1
    while i:
        i, r = divmod(i - 1, 26)
        out = chr(65 + r) + out
    return out


def tile_name(x: int, y: int) -> str:
    return f"{col_name(x)}{y + 1}"


def _footprint(c: dict):
    x, y = c["pos"]
    n = max(1, int(c.get("span") or 1))
    return [(x + i, y + j) for i in range(n) for j in range(n)]


def _window(placed: List[dict], mw: int, mh: int):
    """The part of the map worth showing: around the creatures, at most MAX_COLS x MAX_ROWS."""
    cells = [t for c in placed for t in _footprint(c)]
    if not cells:
        return 0, 0, min(mw, MAX_COLS), min(mh, MAX_ROWS)
    x0, x1 = max(0, min(t[0] for t in cells) - 1), min(mw - 1, max(t[0] for t in cells) + 1)
    y0, y1 = max(0, min(t[1] for t in cells) - 1), min(mh - 1, max(t[1] for t in cells) + 1)
    x1, y1 = min(x1, x0 + MAX_COLS - 1), min(y1, y0 + MAX_ROWS - 1)
    return x0, y0, x1 - x0 + 1, y1 - y0 + 1


def render(view: dict) -> str:
    """A code-block-ready text: the map, then '1- Ogre ...' for every combatant in initiative order."""
    order = view["combatants"]
    m = view.get("map") or {"w": 30, "h": 20}
    numbers = {c["id"]: i + 1 for i, c in enumerate(order)}
    placed = [c for c in order if c.get("pos")]
    x0, y0, w, h = _window(placed, m["w"], m["h"])
    grid = {}
    for c in placed:
        mark = "x" if (c["kind"] == "enemy" and c["hp"] <= 0) else str(numbers[c["id"]])
        for t in _footprint(c):
            grid[t] = mark
    width = max(2, max((len(v) for v in grid.values()), default=1))
    cell = lambda s: s.rjust(width) + " "
    pad = " " * 3
    lines = [pad + "".join(cell(col_name(x0 + i)) for i in range(w))]
    for j in range(h):
        row = f"{y0 + j + 1:>2} " + "".join(cell(grid.get((x0 + i, y0 + j), "·")) for i in range(w))
        lines.append(row)
    grid_text = "\n".join(l.rstrip() for l in lines)
    reveal = view.get("reveal_hp")
    rows = []
    for c in order:
        n = numbers[c["id"]]
        where = tile_name(*c["pos"]) if c.get("pos") else "—"
        if c["kind"] == "pc":
            health = f"{c['hp']}/{c['max_hp']} HP" + (" DOWN" if c.get("downed") else "")
        elif c["hp"] <= 0:
            health = "defeated"
        elif reveal or c.get("revealed"):
            health = f"{c['hp']}/{c['max_hp']} HP"
        else:
            health = health_word(c["hp"], c["max_hp"])
        cond = f" [{', '.join(c['conditions'])}]" if c.get("conditions") else ""
        turn = "  <- TURN" if view["status"] == ACTIVE and c["id"] == view["turn"] else ""
        rows.append(f"{n}- {c['name']}  {where}  {health}{cond}{turn}")
    head = (f"{view['name']} · Round {view['round']}" if view["status"] == ACTIVE
            else f"{view['name']} · battle over" if view["status"] == ENDED else f"{view['name']} · setting up")
    off = [c["name"] for c in placed if not any(t in {(x0 + i, y0 + j) for i in range(w) for j in range(h)} for t in _footprint(c))]
    note = f"\n(off the shown area: {', '.join(off)})" if off else ""
    events = [e if len(e) <= 130 else e[:129] + "…" for e in (view.get("events") or [])[-5:]]
    recent = "\n\nLast events:\n" + "\n".join(f"- {e}" for e in events) if events else ""
    return f"{head}\n\n{grid_text}\n\n" + "\n".join(rows) + note + recent
