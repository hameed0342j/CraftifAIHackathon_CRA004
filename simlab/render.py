"""Procedural indoor floors with pooled water.

Used twice:
  * synthetic training data with exact masks (pipegen/train), covering the gap
    found in the asset scan: no open dataset of water on Indian indoor floors;
  * the camera of the closed-loop simulator (simlab/world.py).

Everything is drawn on a rectified, top-down floor canvas measured in metres
(`ppm` pixels per metre), then warped into the camera with a homography, so pool
areas in m^2 are known exactly and PipeGen's perspective correction can be tested.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

# BGR base colours seen in Indian PGs/hostels: white/ivory ceramic, beige vitrified,
# grey and green Kota stone, red oxide, mosaic chips, dark granite.
_BASES = [
    (225, 228, 230), (205, 215, 222), (180, 195, 210), (150, 160, 165), (120, 140, 125),
    (95, 105, 160), (140, 150, 150), (70, 70, 75), (190, 200, 200), (160, 175, 190),
]


@dataclass
class FloorStyle:
    tile_m: float        # tile edge length, metres
    grout_px: int
    base: tuple
    grout: tuple
    speckle: float       # mosaic / terrazzo chips
    variation: float     # per-tile colour jitter
    gloss: float         # strength of light reflections on the dry floor (vitrified tiles shine)
    stain: float         # low-frequency dirt


def random_style(rng: np.random.Generator) -> FloorStyle:
    base = np.array(_BASES[rng.integers(len(_BASES))], np.float32) + rng.normal(0, 8, 3)
    grout = np.clip(base * rng.uniform(0.55, 0.95), 0, 255)
    return FloorStyle(
        tile_m=float(rng.choice([0.3, 0.3, 0.45, 0.6, 0.6, 0.8])),
        grout_px=int(rng.integers(1, 4)),
        base=tuple(np.clip(base, 0, 255).tolist()),
        grout=tuple(grout.tolist()),
        speckle=float(rng.choice([0.0, 0.0, 0.15, 0.35])),
        variation=float(rng.uniform(0.0, 0.08)),
        gloss=float(rng.uniform(0.0, 0.9)),
        stain=float(rng.uniform(0.0, 0.25)),
    )


def smooth_noise(h: int, w: int, cells: float, rng: np.random.Generator, octaves: int = 3) -> np.ndarray:
    """Band-limited noise in [-1, 1]; `cells` = features across the larger side."""
    out = np.zeros((h, w), np.float32)
    amp, total = 1.0, 0.0
    for o in range(octaves):
        c = max(2, int(cells * (2 ** o)))
        gh, gw = max(2, int(c * h / max(h, w)) + 2), max(2, int(c * w / max(h, w)) + 2)
        grid = rng.uniform(-1, 1, (gh, gw)).astype(np.float32)
        out += amp * cv2.resize(grid, (w, h), interpolation=cv2.INTER_CUBIC)
        total += amp
        amp *= 0.5
    out /= total
    return np.clip(out / (np.abs(out).max() + 1e-6), -1, 1)


def floor_texture(style: FloorStyle, w: int, h: int, ppm: float, rng: np.random.Generator) -> np.ndarray:
    tile = max(8, int(style.tile_m * ppm))
    img = np.empty((h, w, 3), np.float32)
    img[:] = style.base
    ox, oy = rng.integers(0, tile, 2)
    for ty in range(-1, h // tile + 2):
        for tx in range(-1, w // tile + 2):
            x0, y0 = tx * tile - ox, ty * tile - oy
            jitter = 1.0 + rng.normal(0, style.variation)
            sl = (slice(max(0, y0), max(0, min(h, y0 + tile))), slice(max(0, x0), max(0, min(w, x0 + tile))))
            img[sl] *= jitter
    if style.speckle > 0:
        chips = rng.random((h, w)) < style.speckle * 0.25
        chip_col = rng.uniform(0.5, 1.4, (h, w, 1)).astype(np.float32)
        img = np.where(chips[..., None], img * chip_col, img)
        img = cv2.GaussianBlur(img, (0, 0), 0.6)
    img *= 1.0 + 0.04 * smooth_noise(h, w, 30, rng, 2)[..., None]                 # fine grain
    img *= 1.0 - style.stain * np.clip(smooth_noise(h, w, 3, rng), 0, 1)[..., None]  # dirt
    g = style.grout_px
    for x in range(-ox, w, tile):
        img[:, max(0, x):max(0, x + g)] = style.grout
    for y in range(-oy, h, tile):
        img[max(0, y):max(0, y + g), :] = style.grout
    return np.clip(img, 0, 255)


class PuddleShape:
    """A nested family of masks: thresholding a fixed field at growing levels gives a
    pool that spreads monotonically from its source, like a real leak."""

    def __init__(self, h: int, w: int, cx: float, cy: float, rng: np.random.Generator,
                 irregularity: float = 0.45):
        yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
        ang = rng.uniform(0, np.pi)
        stretch = rng.uniform(1.0, 2.2)  # floors are never level: pools run along the slope
        dx, dy = xx - cx, yy - cy
        u = dx * np.cos(ang) + dy * np.sin(ang)
        v = -dx * np.sin(ang) + dy * np.cos(ang)
        d = np.sqrt((u / stretch) ** 2 + v ** 2)
        self.field = d * (1.0 + irregularity * smooth_noise(h, w, 4, rng, 3))
        self._sorted = np.sort(self.field.ravel())

    def mask(self, area_px: float) -> np.ndarray:
        if area_px <= 0:
            return np.zeros(self.field.shape, bool)
        k = int(min(area_px, self._sorted.size - 1))
        return self.field <= self._sorted[k]

    def covers(self, x: float, y: float, area_px: float) -> bool:
        if area_px <= 0:
            return False
        k = int(min(area_px, self._sorted.size - 1))
        yi = int(np.clip(round(y), 0, self.field.shape[0] - 1))
        xi = int(np.clip(round(x), 0, self.field.shape[1] - 1))
        return bool(self.field[yi, xi] <= self._sorted[k])


def _blob(h: int, w: int, cx: float, cy: float, sx: float, sy: float, ang: float) -> np.ndarray:
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    dx, dy = xx - cx, yy - cy
    u = dx * np.cos(ang) + dy * np.sin(ang)
    v = -dx * np.sin(ang) + dy * np.cos(ang)
    return np.exp(-0.5 * ((u / sx) ** 2 + (v / sy) ** 2)).astype(np.float32)


@dataclass
class Light:
    x: float  # rectified px where the ceiling tube light reflects
    y: float
    length: float
    angle: float
    strength: float


def random_lights(h: int, w: int, rng: np.random.Generator) -> list[Light]:
    return [Light(rng.uniform(0, w), rng.uniform(0, h), rng.uniform(20, 90), rng.uniform(0, np.pi),
                  rng.uniform(0.4, 1.0)) for _ in range(rng.integers(1, 3))]


def reflections(h: int, w: int, lights: list[Light]) -> np.ndarray:
    out = np.zeros((h, w), np.float32)
    for L in lights:  # tube lights reflect as elongated highlights
        out += L.strength * _blob(h, w, L.x, L.y, L.length, L.length * 0.18, L.angle)
    return np.clip(out, 0, 1.5)


def compose_water(tex: np.ndarray, mask: np.ndarray, refl: np.ndarray, rng: np.random.Generator,
                  murk: float | None = None) -> np.ndarray:
    """Water over a floor: darker, slightly blurred (refraction), mirror highlights,
    soft meniscus edge. `refl` is the light-reflection map of the room."""
    if not mask.any():
        return tex
    murk = rng.uniform(0.0, 0.5) if murk is None else murk
    soft = cv2.GaussianBlur(mask.astype(np.float32), (0, 0), 1.6)[..., None]
    under = cv2.GaussianBlur(tex, (0, 0), 1.4)
    tint = np.array([1.04, 1.0, 0.94], np.float32) * (1.0 - 0.1 * murk)  # cool, a bit grey
    water = under * rng.uniform(0.55, 0.8) * tint + murk * 25.0
    # Mostly a darker, wetter floor; a mirror only where a light or window reflects.
    # Some pools catch a bright window/sky and look lighter overall.
    base_sheen = rng.choice([0.0, 0.05, 0.1, 0.35], p=[0.35, 0.3, 0.2, 0.15])
    sheen = base_sheen + refl[..., None]
    water = water + sheen * rng.uniform(120, 200)
    rim = (soft * (1 - soft) * 4.0)
    water = water - rim * rng.uniform(10, 35)
    return np.clip(tex * (1 - soft) + water * soft, 0, 255)


def add_distractors(tex: np.ndarray, refl: np.ndarray, style: FloorStyle, rng: np.random.Generator,
                    ppm: float) -> np.ndarray:
    """Things that fool naive water detectors and are NOT pooled water."""
    h, w = tex.shape[:2]
    out = tex.copy()
    # dry glossy tiles reflect lights too, but without darkening or a boundary
    out += (style.gloss * rng.uniform(40, 120)) * refl[..., None]
    for _ in range(rng.integers(0, 3)):
        kind = rng.integers(4)
        cx, cy = rng.uniform(0, w), rng.uniform(0, h)
        if kind == 0:  # dark stain / dried mark
            m = _blob(h, w, cx, cy, rng.uniform(10, 50), rng.uniform(10, 40), rng.uniform(0, np.pi))
            m *= np.clip(smooth_noise(h, w, 6, rng) + 0.6, 0, 1)
            out *= 1 - 0.35 * m[..., None]
        elif kind == 1:  # soft shadow of a person / door
            m = _blob(h, w, cx, cy, rng.uniform(40, 120), rng.uniform(20, 60), rng.uniform(0, np.pi))
            out *= 1 - 0.4 * m[..., None]
        elif kind == 2:  # plastic bucket seen from above
            r = rng.uniform(0.12, 0.18) * ppm
            col = np.array([rng.uniform(80, 200), rng.uniform(40, 120), rng.uniform(0, 80)])
            cv2.circle(out, (int(cx), int(cy)), int(r), col.tolist(), -1)
            cv2.circle(out, (int(cx), int(cy)), int(r), (col * 0.6).tolist(), 3)
        else:  # slippers
            for k in range(2):
                cv2.ellipse(out, (int(cx + k * 0.1 * ppm), int(cy)), (int(0.05 * ppm), int(0.13 * ppm)),
                            float(rng.uniform(-20, 20)), 0, 360,
                            tuple(float(v) for v in rng.uniform(10, 120, 3)), -1)
    return np.clip(out, 0, 255)


_WALLS = [(205, 210, 210), (190, 215, 200), (215, 205, 180), (175, 200, 220), (150, 150, 155), (60, 60, 65)]


@dataclass
class Camera:
    H: np.ndarray     # rectified floor px -> camera px
    size: tuple       # (w, h)
    wall: tuple | None = None  # paint colour where the camera sees no floor


def random_camera(floor_w: int, floor_h: int, rng: np.random.Generator, out=(640, 480)) -> Camera:
    """A wall/ceiling-mounted camera looking down at the floor at an angle."""
    w, h = out
    near = rng.uniform(-0.25, 0.05) * w   # negative: the floor runs past the frame edges
    far = rng.uniform(0.05, 0.3) * w
    top = rng.uniform(-0.05, 0.2) * h
    skew = rng.uniform(-0.08, 0.08) * w
    dst = np.float32([[far + skew, top], [w - far + skew, top], [w - near, h * rng.uniform(1.0, 1.25)],
                      [near, h * rng.uniform(1.0, 1.25)]])
    src = np.float32([[0, 0], [floor_w - 1, 0], [floor_w - 1, floor_h - 1], [0, floor_h - 1]])
    wall = tuple(float(c) for c in np.array(_WALLS[rng.integers(len(_WALLS))]) * rng.uniform(0.6, 1.05))
    return Camera(cv2.getPerspectiveTransform(src, dst), out, wall)


def photograph(rect_img: np.ndarray, cam: Camera, rng: np.random.Generator, exposure: float | None = None,
               noise: float | None = None, jpeg: bool = True) -> np.ndarray:
    """Warp the rectified floor into the camera and add sensor effects."""
    w, h = cam.size
    wall = cam.wall if cam.wall is not None else (200.0, 205.0, 205.0)
    img = cv2.warpPerspective(rect_img.astype(np.float32), cam.H, (w, h), flags=cv2.INTER_LINEAR,
                              borderMode=cv2.BORDER_CONSTANT, borderValue=wall)
    exposure = rng.uniform(0.55, 1.15) if exposure is None else exposure
    yy, xx = np.mgrid[0:h, 0:w].astype(np.float32)
    vignette = 1.0 - 0.35 * (((xx - w / 2) / w) ** 2 + ((yy - h / 2) / h) ** 2) * 2
    white = np.array([rng.uniform(0.9, 1.1), 1.0, rng.uniform(0.85, 1.1)], np.float32)  # tube light / CFL cast
    img = img * exposure * vignette[..., None] * white
    sigma = rng.uniform(1.0, 6.0) / max(exposure, 0.4) if noise is None else noise
    img = img + rng.normal(0, sigma, img.shape).astype(np.float32)
    img = np.clip(img, 0, 255).astype(np.uint8)
    if jpeg:
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, int(rng.integers(60, 95))])
        img = cv2.imdecode(buf, cv2.IMREAD_COLOR)
    return img


def warp_mask(mask: np.ndarray, cam: Camera) -> np.ndarray:
    w, h = cam.size
    return cv2.warpPerspective(mask.astype(np.uint8), cam.H, (w, h), flags=cv2.INTER_NEAREST)


def random_sample(seed: int, out=(640, 480), ppm: float = 120.0) -> tuple[np.ndarray, np.ndarray]:
    """One synthetic training image + binary water mask (camera view)."""
    rng = np.random.default_rng(seed)
    fw, fh = int(rng.uniform(2.5, 4.5) * ppm), int(rng.uniform(2.0, 3.5) * ppm)
    style = random_style(rng)
    tex = floor_texture(style, fw, fh, ppm, rng)
    lights = random_lights(fh, fw, rng)
    refl = reflections(fh, fw, lights)
    tex = add_distractors(tex, refl, style, rng, ppm)
    mask = np.zeros((fh, fw), bool)
    n_pools = rng.choice([0, 1, 1, 1, 2, 3], p=[0.25, 0.25, 0.2, 0.15, 0.1, 0.05])
    for _ in range(n_pools):
        shape = PuddleShape(fh, fw, rng.uniform(0, fw), rng.uniform(0, fh), rng)
        area_m2 = float(np.exp(rng.uniform(np.log(0.02), np.log(2.0))))
        mask |= shape.mask(area_m2 * ppm * ppm)
    if rng.random() < 0.3:  # wet footprints
        for _ in range(rng.integers(2, 6)):
            cx, cy = rng.uniform(0, fw), rng.uniform(0, fh)
            fp = np.zeros_like(mask, np.uint8)
            cv2.ellipse(fp, (int(cx), int(cy)), (int(0.04 * ppm), int(0.11 * ppm)), float(rng.uniform(0, 180)),
                        0, 360, 1, -1)
            mask |= fp.astype(bool)
    img = compose_water(tex, mask, refl, rng)
    cam = random_camera(fw, fh, rng, out)
    return photograph(img, cam, rng), warp_mask(mask, cam)
