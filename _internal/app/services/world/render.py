"""The world map's picture: a tattered parchment with the land the DM painted on it (numpy only, no Qt).

The land is a soft height mask (mask[y, x] in 0..1, the map's own pixels); the coast is where it crosses WATER, read
through a fixed fractal warp so a round brush still leaves a ragged, believable coastline (Wonderdraft's trick: paint a
soft mask, threshold it, dress the edge). Around the coast: an ink outline, a shadow just inside the land, shallow
water and ripple lines rippling out to sea. The paper (stains, grain, folds, a torn and burnt edge) is the same for
every render of a map, so it is made once per size and kept.

That is the parchment look. The painted looks (painted, teal; and sepia) are Inkarnate's: textured land in wet and dry
patches (or the grounds the DM painted: grassland, desert, snow...), a beach and a bevel along the coast, deep cloudy
water glowing pale round the land with pale strokes off the coast, a framed sheet. Their textures are made once too.

    r = Renderer(w, h, scale=2, seed=7)
    rgba = r.render(mask)                       # (h*scale, w*scale, 4) uint8, the whole map
    rgba = r.render(mask, (x0, y0, x1, y1))     # just that part (map pixels): for live painting
"""
import math
import os
from concurrent.futures import ThreadPoolExecutor
from typing import Optional, Tuple

import numpy as np

WATER = 0.5                                     # the mask's sea level

PAPER = (212, 188, 142)                         # the parchment (old, darkened)
LAND = (222, 202, 156)                          # dry land (a lighter, warmer paper)
LAND_LOW = (198, 186, 140)                      # land by the shore (a greener, darker band)
SEA = (146, 164, 160)                           # the open sea (paper washed grey-blue)
SHALLOW = (182, 186, 162)                       # water by the shore
INK = (58, 40, 26)                              # outlines, ripples, labels
BURNT = (92, 58, 30)                            # the scorched rim of the sheet
CHAR = (40, 24, 12)                             # its very edge

RIPPLES = (4.0, 9.0, 15.0, 22.0)               # ripple lines: their distance off the coast, in map pixels
RIPPLE_SIGMA = 14.0                             # how smooth the ripples' field is (map pixels)
SHADOW_SIGMA = 3.0
SHALLOW_SIGMA = 9.0
GLOW_SIGMA = 22.0                               # the painted look's wide pale haze round the land
WARP = 30.0                                     # how far the coast wanders off the painted line (map pixels)
EDGE = 14.0                                     # how far in the torn edge reaches (map pixels, before its tears)
REACH = int(WARP + GLOW_SIGMA * 3.0 + 4)        # how far round a change of the mask the picture can change (map pixels)
STRIPS = 6                                      # threads the whole map is rendered on
BAND_PX = 700_000                               # output pixels in a band at most (the whole map is rendered in bands)

# the painted look (Inkarnate's: textured colour land, deep cloudy sea glowing pale round the coasts)
LOOKS = ("painted", "teal", "antique", "sepia", "parchment")   # painted with a deep blue sea, with a turquoise one; tan and grey; ink on parchment
COLOUR_LOOKS = ("painted", "teal", "antique")             # the looks whose marks and names are in colour (the others' in ink)
GRASS = ((88, 106, 52), (106, 120, 60), (126, 130, 70), (150, 142, 86))   # wet .. dry ground, by the land's own patches
SAND = (214, 192, 140)                          # the beach just inside the coast
SEAS = {   # look: (the open sea, its lighter clouds and the haze round the land, water by the shore, the pale coast strokes)
    "painted": ((38, 62, 76), (74, 106, 118), (128, 162, 162), (214, 226, 220)),
    "teal": ((18, 66, 80), (30, 104, 116), (72, 170, 168), (200, 238, 230)),
    "sepia": ((176, 178, 172), (196, 196, 190), (214, 214, 208), (250, 250, 246)),
    "antique": ((40, 38, 36), (84, 74, 60), (176, 146, 96), (236, 210, 150)),     # charcoal sea, a warm glow round the land
}
LANDS = {"antique": ((140, 100, 58), (170, 128, 72), (196, 156, 94), (216, 184, 124))}
GRADES = {"antique": ((1.16, 0.97, 0.7), 0.5)}  # a look's colour grade over all of it: (warm tone of the lightness, how much)   # a look's own wet .. dry ground
SEPIA = (1.14, 0.98, 0.72)                      # the sepia look's land: the ground's lightness in tan
COAST = (46, 38, 28)                            # the coastline itself
STROKES = (3.0, 8.0, 14.0)                      # pale strokes off the coast (map pixels)
GROUNDS = {   # the ground the DM paints on the land (painted look): id: (name, colour, its other colour, how textured)
    1: ("Grassland", (96, 124, 56), (122, 140, 66), 1.0),
    2: ("Dry steppe", (166, 150, 92), (190, 170, 108), 1.0),
    3: ("Forest floor", (58, 78, 40), (80, 98, 52), 1.0),
    4: ("Desert sand", (226, 202, 150), (206, 178, 124), 0.6),
    5: ("Snow", (238, 242, 247), (206, 216, 230), 0.35),
    6: ("Bare rock", (152, 134, 106), (122, 106, 86), 1.2),
    7: ("Swamp", (104, 112, 64), (84, 100, 60), 1.1),
    8: ("Farmland", (158, 150, 82), (118, 132, 66), 0.8),
}                                               # (0: the land's own wet and dry patches)
FIELDS = ((186, 168, 92), (134, 150, 70), (158, 128, 84), (200, 182, 104), (112, 134, 62), (172, 160, 96))   # farmland's crops
GROUND_EDGE = 6.0                               # how far a painted ground's edge wanders (map pixels)
REALMS = {   # the realms the DM paints over the land (kept in the ground's high four bits): id: (name, colour)
    1: ("Crimson", (176, 52, 40)), 2: ("Royal blue", (52, 92, 176)), 3: ("Gold", (206, 160, 40)),
    4: ("Green", (60, 140, 64)), 5: ("Purple", (124, 64, 156)), 6: ("Teal", (36, 140, 140)),
    7: ("Orange", (214, 110, 36)), 8: ("Grey", (110, 110, 118)),
}
FRAMES = ("border", "clouds", "none")          # the painted sheet's edge: a gilt-lined border, clouds drifting in, none
FRAME = 7.0                                     # the painted sheet's dark frame (map pixels)
CLOUD_EDGE = 70.0                               # how far in the clouds of the "clouds" frame reach (map pixels)
FRAME_TICK = 16.0                               # its chequered scale: a block this long (map pixels)
CORNER = 18.0                                   # its corner boxes (map pixels square)
GILT = (178, 146, 88)


def _lerp(a, b, t):
    return a + (b - a) * t


def _smooth(t):
    return t * t * (3.0 - 2.0 * t)


def _weights(n: int, wavelength: float, gn: int) -> np.ndarray:
    """(n, gn): how much each grid point counts at each pixel (two of them, smoothstepped)."""
    t = np.arange(n, dtype=np.float32) / wavelength
    i = t.astype(np.int32)
    f = _smooth(t - i)
    m = np.zeros((n, gn), np.float32)
    r = np.arange(n)
    m[r, i] = 1 - f
    m[r, i + 1] = f
    return m


def value_noise(h: int, w: int, wavelength: float, rng: np.random.Generator) -> np.ndarray:
    """Smooth random values in -1..1 over an h×w grid, changing over about `wavelength` pixels."""
    gh, gw = int(h / wavelength) + 3, int(w / wavelength) + 3
    g = rng.uniform(-1.0, 1.0, (gh, gw)).astype(np.float32)
    if wavelength >= 2:                                         # as two matrix products: several times quicker
        return (_weights(h, wavelength, gh) @ g) @ _weights(w, wavelength, gw).T
    ys = np.arange(h, dtype=np.float32) / wavelength
    xs = np.arange(w, dtype=np.float32) / wavelength
    yi, xi = ys.astype(np.int32), xs.astype(np.int32)
    ty, tx = _smooth(ys - yi), _smooth(xs - xi)
    rows = g[:, xi] * (1 - tx) + g[:, xi + 1] * tx            # along x for every grid row: (gh, w)
    return rows[yi] * (1 - ty)[:, None] + rows[yi + 1] * ty[:, None]


def fractal(h: int, w: int, wavelengths, rng: np.random.Generator, gain: float = 0.5) -> np.ndarray:
    out = np.zeros((h, w), np.float32)
    amp, total = 1.0, 0.0
    for wl in wavelengths:
        out += value_noise(h, w, wl, rng) * amp
        total += amp
        amp *= gain
    return out / total


def box_blur(a: np.ndarray, r: int, axis: int) -> np.ndarray:
    """A running mean of 2r+1 along an axis (the ends repeat their edge value)."""
    if r < 1:
        return a
    pad = [(0, 0), (0, 0)]
    pad[axis] = (r + 1, r)
    c = np.cumsum(np.pad(a, pad, mode="edge"), axis=axis, dtype=np.float32)
    if axis == 0:
        return (c[2 * r + 1:] - c[:-2 * r - 1]) / (2 * r + 1)
    return (c[:, 2 * r + 1:] - c[:, :-2 * r - 1]) / (2 * r + 1)


def blur(a: np.ndarray, sigma: float) -> np.ndarray:
    """About a gaussian: three box blurs each way."""
    r = max(1, int(round(sigma * 0.95)))
    for _ in range(3):
        a = box_blur(box_blur(a, r, 0), r, 1)
    return a


def _phi(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _band(field, level, width_px, grad):
    """An anti-aliased line `width_px` wide where `field` crosses `level` (grad: |∇field| per output pixel)."""
    return np.clip(1.0 - np.abs(field - level) / (grad * width_px * 0.5 + 1e-6), 0.0, 1.0)


def _grad(f):
    gy, gx = np.gradient(f)
    return np.sqrt(gx * gx + gy * gy) + 1e-5


def _mix(base, color, a):
    """base (h, w, 3) toward a colour by a (h, w)."""
    c = np.asarray(color, np.float32)
    return base + (c - base) * a[..., None]


class Renderer:
    """Renders one map size (w×h map pixels) at `scale` output pixels per map pixel; keeps its paper and noise."""

    def __init__(self, w: int, h: int, scale: int = 2, seed: int = 1, warp: float = WARP, look: str = "painted",
                 frame="border"):
        self.w, self.h, self.s, self.seed, self.warp = int(w), int(h), int(scale), int(seed), float(warp)
        self.look = look if look in LOOKS else LOOKS[0]
        self.frame = frame if frame in FRAMES else ("none" if frame is False else "border")   # (True / False: border / none)
        H, W, s = self.h * self.s, self.w * self.s, self.s
        rng = np.random.default_rng(self.seed)
        # the coast's warp: big bays and capes down to little nicks, in map pixels
        wl = [w_ * s for w_ in (70.0, 34.0, 16.0, 8.0, 4.0, 2.0, 1.0)]
        self.warp_x = fractal(H, W, wl, rng, 0.5) * self.warp
        self.warp_y = fractal(H, W, wl, rng, 0.5) * self.warp
        grain = fractal(H, W, [s * 3.0, s * 1.2, 1.5], rng, 0.7)
        if self.look == "parchment":
            self._paper(rng, grain)
        else:
            self._textures(rng, grain)

    # ------------------------------------------------------------------ the sheet
    def _paper(self, rng, grain):
        H, W, s = self.h * self.s, self.w * self.s, self.s
        stains = fractal(H, W, [s * 160.0, s * 70.0, s * 30.0, s * 12.0], rng, 0.55)
        blots = np.clip((fractal(H, W, [s * 45.0, s * 18.0, s * 7.0], rng, 0.5) - 0.28) * 4.0, 0, 1)
        tone = 1.0 + stains * 0.07 - blots * 0.03 + grain * 0.035
        # folds: the sheet was folded in three across and in two down
        ys, xs = np.arange(H, dtype=np.float32)[:, None], np.arange(W, dtype=np.float32)[None, :]
        fold = np.zeros((H, W), np.float32)
        for fx in (W / 3.0, 2 * W / 3.0):
            d = xs - fx - fractal(H, 1, [s * 60.0, s * 15.0], rng)[:, :1] * s * 2.0
            fold += np.exp(-(d / (s * 2.2)) ** 2) * 0.06 - np.exp(-((d - s * 1.6) / (s * 1.2)) ** 2) * 0.025
        d = ys - H / 2.0 - fractal(1, W, [s * 60.0, s * 15.0], rng)[:1, :] * s * 2.0
        fold += np.exp(-(d / (s * 2.2)) ** 2) * 0.06 - np.exp(-((d - s * 1.6) / (s * 1.2)) ** 2) * 0.025
        cx, cy = (xs - W / 2) / (W / 2), (ys - H / 2) / (H / 2)      # older and darker toward the sheet's edges
        vignette = np.clip(np.sqrt(cx * cx * 0.8 + cy * cy) - 0.45, 0, 1) * 0.16
        self.tone = tone - fold - vignette
        # the torn edge: how far in from the sheet's border, made ragged
        edge = np.minimum(np.minimum(xs + 0.5, W - xs - 0.5), np.minimum(ys + 0.5, H - ys - 0.5)).astype(np.float32)
        tear = fractal(H, W, [s * 50.0, s * 20.0, s * 8.0, s * 3.0, s * 1.2], rng, 0.6)
        bites = np.clip(fractal(H, W, [s * 26.0, s * 9.0], rng, 0.5) - 0.3, 0, 1) * 2.2     # deeper torn bites here and there
        self.edge = edge - (EDGE * s + tear * EDGE * 0.55 * s + bites * EDGE * 0.9 * s)
        corner = np.sqrt(np.minimum(xs, W - xs) ** 2 + np.minimum(ys, H - ys) ** 2)            # the corners are worn round
        self.edge = np.minimum(self.edge, corner - EDGE * 2.4 * s + tear * 6 * s)

    def _textures(self, rng, grain):
        """The painted look's ground and sea, before the coast is known: kept as pictures (uint8)."""
        H, W, s = self.h * self.s, self.w * self.s, self.s
        self.pal = SEAS[self.look]
        # the ground: wet and dry patches over the land, mottled, with a painterly grain and little dark tufts
        patch = np.clip(0.45 + fractal(H, W, [s * 150.0, s * 70.0, s * 30.0, s * 12.0], rng, 0.6) * 0.95, 0.0, 1.0)
        patch = np.clip(patch + fractal(H, W, [s * 18.0, s * 7.0], rng, 0.5) * 0.22, 0.0, 0.999)
        k = patch * (len(GRASS) - 1)
        i = k.astype(np.int32)
        t = (k - i)[..., None]
        ramp = np.asarray(LANDS.get(self.look, GRASS), np.float32)
        ground = ramp[i] + (ramp[i + 1] - ramp[i]) * t
        detail = fractal(H, W, [s * 22.0, s * 9.0, s * 3.5, s * 1.4], rng, 0.65)
        tufts = fractal(H, W, [s * 1.6, 1.3], rng, 0.6)
        light = 1.0 + detail * 0.16 + grain * 0.05 - np.clip((tufts - 0.32) * 3.0, 0, 1) * 0.16 \
            + np.clip((-tufts - 0.42) * 3.0, 0, 1) * 0.10
        dabs = (rng.random((H, W), dtype=np.float32) < 0.012 / s) * rng.choice(np.float32([-1.0, 1.0]), (H, W))
        tilt = np.where(rng.random((H, W), dtype=np.float32) < 0.5, 1, -1)
        left, right = dabs * (tilt < 0), dabs * (tilt > 0)
        strokes = np.zeros((H, W), np.float32)                   # painted strokes: short blades, leaning either way
        for k in range(int(2 * s) + 2):
            strokes += np.roll(np.roll(right, k // 3, axis=1), -k, axis=0) + np.roll(np.roll(left, -(k // 3), axis=1), -k, axis=0)
        light = light + np.clip(strokes, -1.5, 1.5) * 0.09
        ground *= light[..., None]
        self.ground = np.clip(ground, 0, 255).astype(np.uint8)
        self.light = light.astype(np.float16)                    # (kept small: half floats are plenty for these)
        self.gwarp = (fractal(self.h, self.w, [36.0, 16.0, 7.0], rng, 0.6) * GROUND_EDGE * 2.0,     # (map pixels: a painted
                      fractal(self.h, self.w, [36.0, 16.0, 7.0], rng, 0.6) * GROUND_EDGE * 2.0)     # ground's ragged edge)
        self.mottle = np.clip(0.5 + fractal(H, W, [s * 40.0, s * 15.0, s * 6.0], rng, 0.55) * 1.4, 0.0, 1.0).astype(np.float16)
        self.fieldang = (fractal(H, W, [s * 220.0, s * 110.0], rng, 0.5) * 1.6).astype(np.float16)   # farmland rows' way
        self.beachy = np.clip(0.55 + fractal(H, W, [s * 40.0, s * 14.0, s * 5.0], rng, 0.5) * 1.6, 0.0, 1.0).astype(np.float16)
        # the sea: deep water, clouded lighter here and there
        cloud = np.clip(0.5 + fractal(H, W, [s * 120.0, s * 50.0, s * 20.0, s * 8.0], rng, 0.55) * 1.4, 0.0, 1.0)
        deep, mid = np.asarray(self.pal[0], np.float32), np.asarray(self.pal[1], np.float32)
        sea = deep + (mid - deep) * (cloud * 0.75)[..., None]
        st = 14                                                  # brush streaks along the water: noise stretched sideways
        streak = fractal(H, W // st + 2, [s * 3.0, s * 1.3], rng, 0.55)
        xs = np.arange(W, dtype=np.float32) / st
        xi = xs.astype(np.int32)
        streak = streak[:, xi] + (streak[:, xi + 1] - streak[:, xi]) * (xs - xi)
        sea *= (1.0 + grain * 0.03 + streak * np.clip(cloud * 1.6 - 0.3, 0, 1) * 0.07)[..., None]     # (in patches)
        self.sea = np.clip(sea, 0, 255).astype(np.uint8)
        ys, xs = np.arange(H, dtype=np.float32)[:, None], np.arange(W, dtype=np.float32)[None, :]
        cx, cy = (xs - W / 2) / (W / 2), (ys - H / 2) / (H / 2)      # a little darker toward the frame
        self.shade = (1.0 - np.clip(np.sqrt(cx * cx * 0.7 + cy * cy) - 0.55, 0, 1) * 0.35 + grain * 0.02).astype(np.float16)
        self.border = np.minimum(np.minimum(xs + 0.5, W - xs - 0.5), np.minimum(ys + 0.5, H - ys - 0.5)).astype(np.float32)
        if self.frame == "clouds":                              # billows for the clouds round the sheet
            self.billow = fractal(H, W, [s * 90.0, s * 40.0, s * 18.0, s * 8.0], rng, 0.5).astype(np.float16)

    # ------------------------------------------------------------------ rendering
    def _crop(self, rect) -> Tuple[int, int, int, int]:
        if rect is None:
            return 0, 0, self.w, self.h
        x0, y0, x1, y1 = rect
        x0, y0 = max(0, int(math.floor(x0))), max(0, int(math.floor(y0)))
        x1, y1 = min(self.w, int(math.ceil(x1))), min(self.h, int(math.ceil(y1)))
        return x0, y0, max(x0 + 1, x1), max(y0 + 1, y1)

    def render(self, mask: np.ndarray, rect: Optional[tuple] = None, ground: Optional[np.ndarray] = None) -> np.ndarray:
        """RGBA (uint8) of the map, or of `rect` (map pixels x0, y0, x1, y1) of it. The whole map is made in bands on
        several threads (numpy lets go of the GIL while it works)."""
        if rect is not None:
            return self._render(mask, rect, ground)
        n = max(1, min(STRIPS, (os.cpu_count() or 2)))
        if n == 1:
            return self._render(mask, None, ground)
        bands = min(self.h, max(n, int(math.ceil(self.h * self.w * self.s * self.s / BAND_PX))))   # (small enough to keep
                                                                                                     # the memory down)
        cuts = [round(self.h * i / bands) for i in range(bands + 1)]
        with ThreadPoolExecutor(n, thread_name_prefix="world-band") as pool:
            parts = list(pool.map(lambda i: self._render(mask, (0, cuts[i], self.w, cuts[i + 1]), ground), range(bands)))
        return np.concatenate(parts, axis=0)

    def _render(self, mask: np.ndarray, rect: Optional[tuple] = None, ground: Optional[np.ndarray] = None) -> np.ndarray:
        s = self.s
        x0, y0, x1, y1 = self._crop(rect)
        painted = self.look != "parchment"
        m = int(max(RIPPLE_SIGMA * 3.0 + RIPPLES[-1], GLOW_SIGMA * 3.0 if painted else 0) + 8)   # what the fields need round it
        px0, py0, px1, py1 = max(0, x0 - m), max(0, y0 - m), min(self.w, x1 + m), min(self.h, y1 + m)
        # the smooth fields of the land (ripples, shallows, the shadow inside the coast): worked at map resolution
        f1 = self._sample(mask, px0, py0, px1, py1, 1)
        cover = np.clip(0.5 + (f1 - WATER) / _grad(f1), 0.0, 1.0)
        far = blur(cover, RIPPLE_SIGMA)
        shore = blur(cover, SHALLOW_SIGMA)
        near = blur(cover, SHADOW_SIGMA)
        glow = blur(cover, GLOW_SIGMA) if painted else None
        # only the part shown, from here on, at output resolution
        cx0, cy0, cx1, cy1 = x0 - px0, y0 - py0, x1 - px0, y1 - py0
        k = 2                                                       # map pixels kept round the part, for the upsampling
        kx0, ky0 = max(0, cx0 - k), max(0, cy0 - k)
        kx1, ky1 = min(far.shape[1], cx1 + k), min(far.shape[0], cy1 + k)
        ox, oy = (cx0 - kx0) * s, (cy0 - ky0) * s
        ow, oh = (x1 - x0) * s, (y1 - y0) * s

        def up(a):
            return self._up(a[ky0:ky1, kx0:kx1])[oy:oy + oh, ox:ox + ow]
        gfar = up(_grad(far)) / s
        bevel = up(sum(np.gradient(near))) if painted else None    # (worked whole round the part: no seams)
        relief = None
        if painted:                                                 # the land's height (how high the DM raised it): its
            hgt = blur(np.clip((f1 - WATER) * 2.0, 0, 1), 4.0)     # slopes facing the light lit, the others shaded
            gy_, gx_ = np.gradient(hgt)
            relief = up(-(gx_ + gy_) * 9.0)
        far, shore, near = up(far), up(shore), up(near)
        ex0, ey0, ex1, ey1 = max(0, x0 - 1), max(0, y0 - 1), min(self.w, x1 + 1), min(self.h, y1 + 1)
        f = self._sample(mask, ex0, ey0, ex1, ey1, s)               # (a pixel round it: the slope at its edge as in the whole)
        g = _grad(f)
        crop = (slice((y0 - ey0) * s, (y0 - ey0 + y1 - y0) * s), slice((x0 - ex0) * s, (x0 - ex0 + x1 - x0) * s))
        f, g = f[crop], g[crop]
        land = np.clip(0.5 + (f - WATER) / g, 0.0, 1.0)              # anti-aliased: 0 sea .. 1 land
        if painted:
            gw = None                                           # the painted grounds' shares of each pixel
            if ground is not None and (ground[py0:py1, px0:px1] & 15).any():
                g1 = self._ground(ground, px0, py0, px1, py1) & 15
                gw = {int(k): up(box_blur(box_blur((g1 == k).astype(np.float32), 1, 0), 1, 1)) for k in np.unique(g1)}
            return self._painted(x0, y0, x1, y1, f, g, land, far, gfar, shore, near, up(glow), gw, bevel,
                                 self._realm_fields(ground, px0, py0, px1, py1, up, cover), relief)
        water = 1.0 - land
        realms = self._realm_fields(ground, px0, py0, px1, py1, up, cover)
        # the colours: sea (lighter in the shallows) and land (a darker band by the shore)
        t_sh = np.clip(shore * 2.2, 0, 1)
        t_sh *= np.sqrt(t_sh)
        t_lo = np.clip((1.0 - near) * 1.7, 0, 1) * 0.85
        rgb = np.empty(land.shape + (3,), np.float32)
        for i in range(3):
            sea = SEA[i] + (SHALLOW[i] - SEA[i]) * t_sh
            ground = LAND[i] + (LAND_LOW[i] - LAND[i]) * t_lo
            rgb[..., i] = sea + (ground - sea) * land
        rgb = self._realms(rgb, land, realms)
        # all the ink in one layer: ripple lines out at sea (fading with distance), the shadow inside the coast, the coast
        ink = np.zeros_like(land)
        for i, d in enumerate(RIPPLES):
            ink = np.maximum(ink, _band(far, _phi(-d / RIPPLE_SIGMA), 1.0 + 0.25 * s, gfar) * (0.55 - i * 0.11))
        ink *= water
        sh = np.clip((1.0 - near) * 2.0 - 0.15, 0, 1)
        ink = np.maximum(ink, sh * sh * land * 0.22)
        ink = np.maximum(ink, _band(f, WATER, 1.0 + 0.6 * s, g) * 0.92)
        # the torn, scorched edge of the sheet
        e = self.edge[y0 * s:y1 * s, x0 * s:x1 * s]
        burn = np.clip(1.0 - e / (5.0 * s), 0, 1)
        burn *= burn * 0.75
        char = np.clip(1.0 - e / (1.2 * s), 0, 1) * 0.8
        tone = self.tone[y0 * s:y1 * s, x0 * s:x1 * s]
        out = np.empty(land.shape + (4,), np.uint8)
        for i in range(3):
            c = rgb[..., i]
            c += (INK[i] - c) * ink
            c *= tone
            c += (BURNT[i] - c) * burn
            c += (CHAR[i] - c) * char
            out[..., i] = np.clip(c, 0, 255)
        out[..., 3] = np.clip(e / 1.2 + 0.5, 0, 1) * 255
        return out

    def _ground(self, ground: np.ndarray, x0, y0, x1, y1) -> np.ndarray:
        """The painted ground over map pixels [y0:y1, x0:x1], read through a smooth warp of its own: ragged edges."""
        wx, wy = self.gwarp[0][y0:y1, x0:x1], self.gwarp[1][y0:y1, x0:x1]
        ys = np.clip(np.arange(y0, y1, dtype=np.float32)[:, None] + wy + 0.5, 0, self.h - 1).astype(np.int32)
        xs = np.clip(np.arange(x0, x1, dtype=np.float32)[None, :] + wx + 0.5, 0, self.w - 1).astype(np.int32)
        return ground[ys, xs]

    @staticmethod
    def _realm_fields(ground, x0, y0, x1, y1, up, cover=None) -> dict:
        """Each realm painted round the part: (its edge, sharp; a wide blur of it for the glow inside its border). Over
        the land only (`cover`: the land's share of each map pixel): no border drawn along the coast, where the sea
        meets it."""
        if ground is None:
            return {}
        r1 = ground[y0:y1, x0:x1] >> 4
        out = {}
        dens = {} if cover is None else {r: np.maximum(blur(cover, r), 1e-3) for r in (1.0, 6.0)}
        for k in np.unique(r1):
            if k:
                inside = (r1 == k).astype(np.float32)
                if cover is None:
                    out[int(k)] = (up(blur(inside, 1.0)), up(blur(inside, 6.0)))
                else:
                    inside *= cover
                    out[int(k)] = tuple(up(np.clip(blur(inside, r) / dens[r], 0.0, 1.0)) for r in (1.0, 6.0))
        return out

    @staticmethod
    def _realms(rgb, land, fields) -> np.ndarray:
        """The realms over the land: a light tint, a glow inside each border, the border line itself."""
        for k, (sharp, wide) in fields.items():
            col = np.asarray(REALMS[k][1] if k in REALMS else (90, 90, 90), np.float32)
            inside = np.clip((sharp - 0.5) * 6.0 + 0.5, 0, 1) * land
            rgb = _mix(rgb, col, inside * (0.12 + np.clip((1.0 - wide) * 2.4, 0, 1) ** 2.0 * 0.5))   # (a wash: the biomes show through)
            rgb = _mix(rgb, col * 0.45, np.clip(1.0 - np.abs(sharp - 0.5) / 0.26, 0, 1) * land)
        return rgb

    def _ground_tex(self, k: int, win) -> np.ndarray:
        """A painted ground's colour over the window (output pixels), textured like the land's own."""
        _name, a, b, tex = GROUNDS[k]
        a, b = np.asarray(a, np.float32), np.asarray(b, np.float32)
        t = self.mottle[win]
        light = 1.0 + (self.light[win] - 1.0) * tex
        s = self.s
        if k == 4:                                      # sand: long dunes, each with a lit face and a shaded one
            ys = np.arange(win[0].start, win[0].stop, dtype=np.float32)[:, None] / s
            xs = np.arange(win[1].start, win[1].stop, dtype=np.float32)[None, :] / s
            ph = (xs * 0.55 + ys * 0.85) / 7.0 + self.warp_x[win] / s * 0.09 + self.mottle[win] * 2.0
            saw = ph - np.floor(ph)                             # (slow up the lit side, a sharp crest, the shade behind)
            light = light + np.where(saw < 0.8, saw / 0.8 * 0.1, -0.12 * (1.0 - (saw - 0.8) / 0.2)) - 0.02
            col = (a + (b - a) * t[..., None]) * light[..., None]
            return col
        elif k == 8:                                    # farmland: a patchwork of fields, its rows turning with the land
            ang = self.fieldang[win]
            ys = np.arange(win[0].start, win[0].stop, dtype=np.float32)[:, None] / s + self.warp_y[win] / s * 0.35
            xs = np.arange(win[1].start, win[1].stop, dtype=np.float32)[None, :] / s + self.warp_x[win] / s * 0.35
            u, v = xs * np.cos(ang) + ys * np.sin(ang), -xs * np.sin(ang) + ys * np.cos(ang)
            fu, fv = np.floor(u / 12.0), np.floor(v / 8.0 + np.floor(u / 12.0) * 0.37)
            cell = (np.sin(fu * 12.9898 + fv * 78.233) * 43758.5453) % 1.0
            crops = np.asarray(FIELDS, np.float32)
            col = crops[(cell * len(FIELDS)).astype(np.int32) % len(FIELDS)]
            du = np.abs(u / 12.0 - np.round(u / 12.0)) * 12.0
            dv = np.abs((v / 8.0 + fu * 0.37) - np.round(v / 8.0 + fu * 0.37)) * 8.0
            furrow = np.sin(v * 2.4) * 0.04 * (cell > 0.4)
            hedge = np.clip(1.0 - np.minimum(du, dv) / 0.55, 0, 1)
            col = col * (light * (1.0 + furrow))[..., None]
            return _mix(col, (70, 86, 44), hedge * 0.75)
        col = (a + (b - a) * t[..., None]) * light[..., None]
        if k == 7:                                      # swamp: still pools of water among the reeds
            v = self.beachy[win] * 0.55 + self.mottle[win] * 0.45 + (self.light[win] - 1.0) * 0.5
            col = _mix(col, (150, 160, 116), np.clip(1.0 - np.abs(v - 0.655) * 30.0, 0, 1) * 0.6)     # the pools' pale rims
            col = _mix(col, (48, 74, 70), np.clip((v - 0.675) * 30.0, 0, 1) * 0.85)
        elif k == 5:                                    # snow: drifts with blue shadows on their lee, glints on their crests
            gy, gx = np.gradient(self.mottle[win] + self.beachy[win] * 0.5)
            slope = (gx + gy) * s * 18.0
            col = _mix(col, (176, 192, 214), np.clip(slope, 0, 1) * 0.6)
            col = _mix(col, (255, 255, 255), np.clip(-slope, 0, 1) * 0.5)
        elif k == 6:                                    # bare rock: cracks, and loose stones lit on top
            v = self.beachy[win] * 0.5 + self.mottle[win] * 0.5
            crack = np.clip(1.0 - np.abs(v - 0.55) * 40.0, 0, 1) + np.clip(1.0 - np.abs(v - 0.35) * 40.0, 0, 1)
            broken = np.clip((self.light[win] - 0.98) * 8.0, 0, 1)    # (in pieces, not whole loops)
            col = _mix(col, (62, 54, 48), np.clip(crack, 0, 1) * broken * 0.45)
            col = _mix(col, (196, 186, 170), np.clip((self.light[win] - 1.08) * 6.0, 0, 1) * 0.6)
        return col

    def _painted(self, x0, y0, x1, y1, f, g, land, far, gfar, shore, near, glow, gw=None, bevel=None, realms=None,
                 relief=None) -> np.ndarray:
        """The painted look of the part (map pixels x0..x1, y0..y1): its fields are ready, at output resolution."""
        s = self.s
        win = (slice(y0 * s, y1 * s), slice(x0 * s, x1 * s))
        water = 1.0 - land
        # the sea: lighter in a wide haze round the land, pale in the shallows
        sea = self.sea[win].astype(np.float32)
        _deep, mid, shoal, foam_rgb = self.pal
        sea = sea * (0.82 + 0.18 * np.clip(glow * 6.0, 0, 1))[..., None]       # the deep ocean far out a little darker
        sea = _mix(sea, mid, np.clip(glow * 1.8, 0, 1) * 0.7)
        t = np.clip(shore * 2.2, 0, 1)
        sea = _mix(sea, shoal, t * np.sqrt(t) * 0.8)
        if self.look == "antique":                      # a bright warm glow far out round the land
            sea = _mix(sea, shoal, np.clip(glow * 2.2, 0, 1) ** 1.6 * 0.55)
        foam = np.zeros_like(land)
        for i, d in enumerate(STROKES):
            foam = np.maximum(foam, _band(far, _phi(-d / RIPPLE_SIGMA), 1.0 + 0.5 * s, gfar) * (0.7 - i * 0.2))
        foam = np.maximum(foam, np.clip((near - 0.1) * 2.6, 0, 1) * 0.55)          # the surf right along the coast
        sea = _mix(sea, foam_rgb, foam * water)
        # the ground: darker toward the coast, a broken beach right along it
        ground = self.ground[win].astype(np.float32)
        if gw:                                          # the grounds the DM painted, blended where they meet
            total = sum(gw.values()) + 1e-6
            ground = sum((ground if k == 0 else self._ground_tex(k, win)) * (w / total)[..., None] for k, w in gw.items())
        if self.look == "sepia":                        # tan land, browner toward the coast, a bold white coastline
            lum = ground @ np.float32([0.3, 0.59, 0.11])
            ground = (lum * 0.5 + 112.0)[..., None] * np.float32(SEPIA)
            ground *= (1.0 - np.clip((1.0 - shore) * 1.8, 0, 1) * 0.3)[..., None]
            rgb = sea + (ground - sea) * land[..., None]
            rgb = _mix(rgb, (252, 250, 244), _band(f, WATER, 1.6 + 1.0 * s, g) * 0.95)
        else:
            ground *= (1.0 - np.clip((1.0 - shore) * 1.5, 0, 1) * 0.22)[..., None]
            if bevel is not None:                               # a bevel: coasts facing the light (north-west) lit,
                ground *= (1.0 + np.clip(bevel * 6.0, -0.2, 0.2))[..., None]          # the far ones in shadow
            if relief is not None:                              # the land's slopes lit and shaded
                ground *= (1.0 + np.clip(relief, -0.12, 0.12))[..., None]
            beach = np.clip((0.86 - near) * 4.0, 0, 1) * self.beachy[win]
            if gw and 5 in gw:                                  # (no sand along a snowy shore)
                beach *= 1.0 - gw[5] / total
            ground = _mix(ground, SAND, beach * 0.8)
            rgb = sea + (ground - sea) * land[..., None]
            rgb = _mix(rgb, COAST, _band(f, WATER, 0.9 + 0.5 * s, g) * 0.85)
        rgb = self._realms(rgb, land, realms or {})
        if self.look in GRADES:
            tone, k = GRADES[self.look]
            lum = rgb @ np.float32([0.3, 0.59, 0.11])
            rgb = rgb + (lum[..., None] * np.float32(tone) - rgb) * k
        rgb *= self.shade[win][..., None]
        rgb = self._frame(rgb, win)
        out = np.empty(land.shape + (4,), np.uint8)
        out[..., :3] = np.clip(rgb, 0, 255)
        out[..., 3] = 255
        return out

    def _frame(self, rgb, win):
        """The painted sheet's frame over the window: a dark band with a chequered scale along it, gilt lines either
        side, and a box in each corner with a gilt diamond."""
        s, H, W = self.s, self.h * self.s, self.w * self.s
        b = self.border[win]
        if self.frame == "clouds":
            return self._clouds(rgb, win)
        if self.frame == "none" or b.min() > (CORNER + 3) * s:                    # (nowhere near the edge)
            return rgb
        ys = np.arange(win[0].start, win[0].stop, dtype=np.float32)[:, None] + 0.5
        xs = np.arange(win[1].start, win[1].stop, dtype=np.float32)[None, :] + 0.5
        u, v = np.minimum(xs, W - xs) / s, np.minimum(ys, H - ys) / s     # map pixels from the side, and from the top or bottom
        along = np.where(u < v, ys, xs) / s                     # how far along its side of the frame
        dark = np.clip((FRAME * s - b) + 0.5, 0, 1)
        rgb = _mix(rgb, (24, 19, 14), dark)
        mid = np.clip(1.0 - np.abs(b / s - FRAME * 0.5) / (FRAME * 0.18), 0, 1) * dark       # the scale: gilt and dark blocks
        rgb = _mix(rgb, GILT, mid * (np.floor(along / FRAME_TICK) % 2 == 0) * 0.85)
        for at, wd in ((FRAME + 0.9, 0.55), (FRAME * 0.5 - FRAME * 0.25, 0.3), (FRAME * 0.5 + FRAME * 0.25, 0.3)):
            rgb = _mix(rgb, GILT, np.clip(1.0 - np.abs(b / s - at) / wd, 0, 1))
        inside = (u < CORNER) & (v < CORNER)                    # the corner boxes
        if inside.any():
            box = np.clip((CORNER - np.maximum(u, v)) * s + 0.5, 0, 1)
            rgb = _mix(rgb, (30, 24, 18), box)
            rgb = _mix(rgb, GILT, np.clip(1.0 - np.abs(np.maximum(u, v) - (CORNER - 1.0)) / 0.5, 0, 1) * box)
            dia = np.abs(u - CORNER / 2) + np.abs(v - CORNER / 2)
            rgb = _mix(rgb, (118, 92, 54), np.clip((CORNER * 0.3 - dia) * s, 0, 1))
            rgb = _mix(rgb, GILT, np.clip(1.0 - np.abs(dia - CORNER * 0.3) / 0.6, 0, 1) * box)
            rgb = _mix(rgb, (226, 196, 128), np.clip((CORNER * 0.08 - dia) * s, 0, 1))
        return rgb

    def _clouds(self, rgb, win):
        """Clouds drifting in over the sheet's edges: billowing, lit from above, a soft shadow on the map under them."""
        s = self.s
        b = self.border[win]
        if b.min() > (CLOUD_EDGE + 8) * s:
            return rgb
        bil = self.billow[win]
        d = 1.0 - b / (CLOUD_EDGE * s) + bil * 0.9                 # how deep in the clouds
        rgb = rgb * (1.0 - np.clip((d - 0.2) / 0.35, 0, 1) * 0.3)[..., None]        # their soft shadow, just inside them
        t = np.clip((d - 0.42) / 0.3, 0, 1)
        cover = t * t * (3 - 2 * t)
        gy, gx = np.gradient(bil)
        lit = np.clip(0.7 - (gy + gx * 0.4) * s * 14.0, 0.25, 1.0)                  # lit where the billows face up
        cloud = np.asarray((238, 242, 246), np.float32) * (0.74 + 0.26 * lit)[..., None]
        return rgb + (cloud - rgb) * cover[..., None]

    def _sample(self, mask: np.ndarray, x0, y0, x1, y1, s) -> np.ndarray:
        """The mask over map pixels [y0:y1, x0:x1] at s samples per pixel, bilinear, through the coast's warp."""
        if s == self.s:
            wx, wy = self.warp_x[y0 * s:y1 * s, x0 * s:x1 * s], self.warp_y[y0 * s:y1 * s, x0 * s:x1 * s]
        else:                                                       # (coarser: every s-th of the warp)
            st = self.s // s
            wx = self.warp_x[y0 * self.s:y1 * self.s:st, x0 * self.s:x1 * self.s:st]
            wy = self.warp_y[y0 * self.s:y1 * self.s:st, x0 * self.s:x1 * self.s:st]
        ys = (np.arange(y0 * s, y1 * s, dtype=np.float32)[:, None] + 0.5) / s - 0.5 + wy
        xs = (np.arange(x0 * s, x1 * s, dtype=np.float32)[None, :] + 0.5) / s - 0.5 + wx
        np.clip(ys, 0, self.h - 1.001, out=ys)
        np.clip(xs, 0, self.w - 1.001, out=xs)
        yi, xi = ys.astype(np.int32), xs.astype(np.int32)
        ty, tx = ys - yi, xs - xi
        idx = yi * self.w + xi
        flat = mask.ravel()
        a, b = flat[idx], flat[idx + 1]
        c, d = flat[idx + self.w], flat[idx + self.w + 1]
        top = a + (b - a) * tx
        return top + (c + (d - c) * tx - top) * ty

    def _up(self, a: np.ndarray) -> np.ndarray:
        """A map-resolution field to output pixels (bilinear; scale 2 by fixed weights)."""
        s = self.s
        if s == 1:
            return a
        if s == 2:
            p = np.pad(a, 1, mode="edge")
            rows = np.empty((a.shape[0] * 2, a.shape[1] + 2), np.float32)
            rows[0::2] = p[1:-1] * 0.75 + p[:-2] * 0.25
            rows[1::2] = p[1:-1] * 0.75 + p[2:] * 0.25
            out = np.empty((a.shape[0] * 2, a.shape[1] * 2), np.float32)
            out[:, 0::2] = rows[:, 1:-1] * 0.75 + rows[:, :-2] * 0.25
            out[:, 1::2] = rows[:, 1:-1] * 0.75 + rows[:, 2:] * 0.25
            return out
        h, w = a.shape
        ys = np.clip((np.arange(h * s, dtype=np.float32) + 0.5) / s - 0.5, 0, h - 1.001)
        xs = np.clip((np.arange(w * s, dtype=np.float32) + 0.5) / s - 0.5, 0, w - 1.001)
        yi, xi = ys.astype(np.int32), xs.astype(np.int32)
        ty, tx = (ys - yi)[:, None], xs - xi
        rows = a[:, xi] * (1 - tx) + a[:, xi + 1] * tx
        return rows[yi] * (1 - ty) + rows[yi + 1] * ty


# ---------------------------------------------------------------------- painting the mask
def brush(mask: np.ndarray, x: float, y: float, radius: float, strength: float, mode: str = "raise") -> tuple:
    """One dab of the brush at (x, y) (map pixels); returns the rect it changed (x0, y0, x1, y1).
    raise / lower: up or down by `strength` at the centre, softly less to the rim. smooth: toward the local mean."""
    h, w = mask.shape
    r = max(1.0, float(radius))
    x0, y0 = max(0, int(x - r - 1)), max(0, int(y - r - 1))
    x1, y1 = min(w, int(x + r + 2)), min(h, int(y + r + 2))
    if x0 >= x1 or y0 >= y1:
        return (0, 0, 0, 0)
    ys = np.arange(y0, y1, dtype=np.float32)[:, None] - y
    xs = np.arange(x0, x1, dtype=np.float32)[None, :] - x
    d2 = (xs * xs + ys * ys) / (r * r)
    fall = np.clip(1.0 - d2, 0, 1) ** 2                            # 1 at the centre, 0 at the rim, smooth both ends
    part = mask[y0:y1, x0:x1]
    if mode == "raise":
        part += fall * strength * (1.08 - part * 0.5)               # piles up quickly from the sea, slower when high
    elif mode == "lower":
        part -= fall * strength * (0.58 + part * 0.5)
    elif mode == "smooth":
        k = max(1, int(r * 0.25))
        pad = np.pad(part, k, mode="edge")
        mean = box_blur(box_blur(pad, k, 0), k, 1)[k:-k, k:-k]
        part += (mean - part) * fall * min(1.0, strength * 2.5)
    np.clip(part, 0.0, 1.0, out=part)
    return (x0, y0, x1, y1)


def ground_stroke(ground: np.ndarray, pts, radius: float, kind: int, realm: bool = False) -> tuple:
    """Paint a ground (GROUNDS' id, 0: the land's own) in discs along a line of points; the rect changed. realm: a
    realm (REALMS' id, 0: none) instead, in the high four bits (the ground under it is kept)."""
    h, w = ground.shape
    r = max(1.0, float(radius))
    box, last = None, None
    for p in pts:
        if last is None:
            seq = [p]
        else:
            n = max(1, int(math.hypot(p[0] - last[0], p[1] - last[1]) / max(1.0, r * 0.3)))
            seq = [(last[0] + (p[0] - last[0]) * i / n, last[1] + (p[1] - last[1]) * i / n) for i in range(1, n + 1)]
        for x, y in seq:
            x0, y0 = max(0, int(x - r - 1)), max(0, int(y - r - 1))
            x1, y1 = min(w, int(x + r + 2)), min(h, int(y + r + 2))
            if x0 >= x1 or y0 >= y1:
                continue
            ys = np.arange(y0, y1, dtype=np.float32)[:, None] - y
            xs = np.arange(x0, x1, dtype=np.float32)[None, :] - x
            part, hit = ground[y0:y1, x0:x1], xs * xs + ys * ys <= r * r
            part[hit] = (part[hit] & 15) | (kind << 4) if realm else (part[hit] & 0xF0) | kind
            box = (x0, y0, x1, y1) if box is None else (min(box[0], x0), min(box[1], y0), max(box[2], x1), max(box[3], y1))
        last = p
    return box or (0, 0, 0, 0)


def stroke(mask: np.ndarray, pts, radius: float, strength: float, mode: str = "raise") -> tuple:
    """Dabs along a line of points, a quarter radius apart; the rect changed."""
    box = None
    step = max(1.0, radius * 0.25)
    last = None
    for p in pts:
        if last is None:
            seq = [p]
        else:
            dx, dy = p[0] - last[0], p[1] - last[1]
            n = max(1, int(math.hypot(dx, dy) / step))
            seq = [(last[0] + dx * i / n, last[1] + dy * i / n) for i in range(1, n + 1)]
        for q in seq:
            r = brush(mask, q[0], q[1], radius, strength, mode)
            if r[2] > r[0]:
                box = r if box is None else (min(box[0], r[0]), min(box[1], r[1]), max(box[2], r[2]), max(box[3], r[3]))
        last = p
    return box or (0, 0, 0, 0)


def island(mask: np.ndarray, seed: int, land: float = 0.42, parts: int = 1):
    """A random coast to start from: a few big landmasses and their islands (replaces the mask). parts: how many
    continents (1: one big land in the middle; more: as many lands round the sheet, sea between them)."""
    h, w = mask.shape
    rng = np.random.default_rng(seed)
    n = fractal(h, w, [w / 2.5, w / 5.0, w / 10.0, w / 20.0, w / 40.0], rng, 0.55)
    wx, wy = (fractal(h, w, [w / 4.0, w / 9.0], rng, 0.5) * w * 0.09 for _ in range(2))   # stretched and curled: capes, gulfs
    yy = np.clip(np.arange(h)[:, None] + wy, 0, h - 1).astype(np.int32)
    xx = np.clip(np.arange(w)[None, :] + wx, 0, w - 1).astype(np.int32)
    n = n[yy, xx]
    ys, xs = np.arange(h, dtype=np.float32)[:, None] / h - 0.5, np.arange(w, dtype=np.float32)[None, :] / w - 0.5
    fall = np.sqrt((xs * 1.7) ** 2 + (ys * 2.1) ** 2)                 # sea toward the sheet's edges
    if parts > 1:                                                   # several lands: sea away from each one's middle
        a0 = rng.uniform(0, math.pi * 2)
        centres = [(math.cos(a0 + math.pi * 2 * i / parts) * 0.3 + rng.uniform(-0.03, 0.03),
                    math.sin(a0 + math.pi * 2 * i / parts) * 0.27 + rng.uniform(-0.03, 0.03)) for i in range(parts)]
        k = 1.0 + 0.5 * parts
        fall = np.min([np.sqrt(((xs - cx) * 1.7 * k) ** 2 + ((ys - cy) * 2.1 * k) ** 2) for cx, cy in centres], axis=0) * 0.62
    edge = np.minimum(np.minimum(xs + 0.5, 0.5 - xs) * w, np.minimum(ys + 0.5, 0.5 - ys) * h) / (min(w, h) * 0.1)
    isles = np.clip(fractal(h, w, [w / 14.0, w / 30.0], rng, 0.5) - 0.3, 0, 1) * 1.6        # a few islands off the coasts
    v = n - fall ** 2 * (0.55 if parts == 1 else 1.15)
    v = np.maximum(v, isles * 0.5 + v * 0.5 - 0.02) - np.clip(1.0 - edge, 0, 1) ** 2 * 1.2
    thr = np.quantile(v, 1.0 - land)
    mask[:] = np.clip(WATER + (v - thr) * 3.0, 0.0, 1.0)
