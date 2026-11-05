"""Turning a rough hand-drawn stroke into clean map lines, and finding what is near a point (for the eraser).

Coordinates are in tiles (floats); tile corners are whole numbers. A stroke is simplified (Ramer-Douglas-Peucker),
its corners snapped to the nearest tile corners, repeated and in-line corners dropped, and it is closed into a room
when it ends close to where it began. So a wobbly rectangle becomes a rectangle along the grid lines.
"""
import math
from typing import List, Sequence, Tuple

Point = Tuple[float, float]
SIMPLIFY = 0.45          # tiles: how far a wobble may stray from the line it is part of
CLOSE = 1.25             # tiles: a stroke ending this close to its start becomes a closed shape


def _dist_to_segment(p: Point, a: Point, b: Point) -> float:
    (px, py), (ax, ay), (bx, by) = p, a, b
    dx, dy = bx - ax, by - ay
    if dx == dy == 0:
        return math.hypot(px - ax, py - ay)
    t = max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
    return math.hypot(px - (ax + t * dx), py - (ay + t * dy))


def simplify(points: Sequence[Point], eps: float = SIMPLIFY) -> List[Point]:
    """Ramer-Douglas-Peucker: keep only the corners that matter."""
    pts = [tuple(p) for p in points]
    if len(pts) < 3:
        return pts
    far, idx = 0.0, 0
    for i in range(1, len(pts) - 1):
        d = _dist_to_segment(pts[i], pts[0], pts[-1])
        if d > far:
            far, idx = d, i
    if far <= eps:
        return [pts[0], pts[-1]]
    return simplify(pts[: idx + 1], eps)[:-1] + simplify(pts[idx:], eps)


def _collinear(a, b, c) -> bool:
    return (b[0] - a[0]) * (c[1] - a[1]) - (b[1] - a[1]) * (c[0] - a[0]) == 0


def snap(points: Sequence[Point]) -> Tuple[List[List[int]], bool]:
    """A rough stroke -> ([[x, y], ...] on tile corners, closed). An empty list when nothing is left (a dot)."""
    raw = [(float(x), float(y)) for x, y in points]
    if not raw:
        return [], False
    closed = len(raw) > 4 and math.hypot(raw[0][0] - raw[-1][0], raw[0][1] - raw[-1][1]) <= CLOSE
    pts = [(round(x), round(y)) for x, y in simplify(raw)]
    out: List[Tuple[int, int]] = []
    for p in pts:
        if not out or p != out[-1]:
            out.append(p)
    if closed and len(out) > 2 and out[0] == out[-1]:
        out.pop()
    i = 1                                             # drop corners that sit on a straight line
    while len(out) > 2 and i < len(out) - (0 if closed else 1):
        a, b, c = out[i - 1], out[i], out[(i + 1) % len(out)]
        if _collinear(a, b, c):
            out.pop(i)
        else:
            i += 1
    if len(out) < 2:
        return [], False
    if len(out) < 3:
        closed = False
    return [list(p) for p in out], closed


def near_path(p: Point, pts: Sequence[Sequence[float]], closed: bool, radius: float) -> bool:
    segs = list(zip(pts, pts[1:])) + ([(pts[-1], pts[0])] if closed and len(pts) > 2 else [])
    return any(_dist_to_segment(p, tuple(a), tuple(b)) <= radius for a, b in segs)
