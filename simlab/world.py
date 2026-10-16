"""Physical world of the simulator: floor, leaks, pools, valves, sensors, camera.

Two zones share one camera: bathroom-1 (white ceramic) and corridor-2 (grey
Kota stone), each with its own pipe joint, servo valve + limit switch and
wetness probe. Pools are volume-based (3 mm film), so closing a valve really
stops their growth, and the camera sees exactly that.
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

from pipegen.zones import Zone

from . import render
from .scenarios import Leak, Scenario

FILM_DEPTH_M = 0.003   # 1 L of water spreads to ~0.33 m2
EVAPORATION_LPM = 0.01
SERVO_DEG_PER_S = 120.0
LIMIT_DEG = 88.0
PPM = 100.0            # rectified canvas pixels per metre
FLOOR_M = (4.0, 3.0)


@dataclass
class ZoneSpec:
    id: str
    x0: float
    x1: float
    joint: tuple    # leaking pipe joint, metres
    sensor: tuple   # wetness probe, metres


ZONES = [
    ZoneSpec("bathroom-1", 0.0, 2.0, joint=(0.70, 1.00), sensor=(0.79, 1.09)),
    ZoneSpec("corridor-2", 2.0, 4.0, joint=(3.10, 1.80), sensor=(3.19, 1.88)),
]


class Valve:
    def __init__(self, stuck_at: float | None = None) -> None:
        self.angle = 0.0        # 0 = open, 90 = closed
        self.target = 0.0
        self.stuck_at = stuck_at
        self.commands = 0

    def command(self, close: bool) -> None:
        self.target = 90.0 if close else 0.0
        self.commands += 1

    def step(self, dt: float) -> None:
        limit = self.target if self.stuck_at is None else min(self.target, self.stuck_at)
        d = limit - self.angle
        self.angle += float(np.clip(d, -SERVO_DEG_PER_S * dt, SERVO_DEG_PER_S * dt))

    @property
    def limit_pressed(self) -> bool:
        return self.angle >= LIMIT_DEG

    @property
    def open_fraction(self) -> float:
        return max(0.0, 1.0 - self.angle / 90.0) ** 1.5  # a ball valve chokes near closed


class Pool:
    def __init__(self, leak: Leak, xy: tuple, seed: int) -> None:
        self.leak = leak
        w, h = int(FLOOR_M[0] * PPM), int(FLOOR_M[1] * PPM)
        self.shape = render.PuddleShape(h, w, xy[0] * PPM, xy[1] * PPM, np.random.default_rng(seed),
                                        irregularity=0.35)
        self.volume_l = 0.0
        self.started = False

    @property
    def area_m2(self) -> float:
        return self.volume_l / 1000.0 / FILM_DEPTH_M

    @property
    def area_px(self) -> float:
        return self.area_m2 * PPM * PPM


class World:
    def __init__(self, scenario: Scenario, seed: int = 7) -> None:
        self.scenario = scenario
        self.t = 0.0
        self.rng = np.random.default_rng(seed)
        self.zones = {z.id: z for z in ZONES}
        self.valves = {z.id: Valve(scenario.stuck_valve_deg.get(z.id)) for z in ZONES}
        self.pools = []
        for i, leak in enumerate(scenario.leaks):
            xy = leak.source_xy or self.zones[leak.zone].joint
            self.pools.append(Pool(leak, xy, seed + 11 * i))
        self._build_scene(seed)

    # ---- scene ---------------------------------------------------------------
    def _build_scene(self, seed: int) -> None:
        rng = np.random.default_rng(seed)
        w, h = int(FLOOR_M[0] * PPM), int(FLOOR_M[1] * PPM)
        bath = render.FloorStyle(0.3, 2, (222, 226, 228), (170, 175, 178), 0.0, 0.03, 0.6, 0.08)
        corr = render.FloorStyle(0.6, 1, (150, 158, 160), (110, 115, 118), 0.25, 0.05, 0.2, 0.15)
        left = render.floor_texture(bath, w, h, PPM, rng)
        right = render.floor_texture(corr, w, h, PPM, rng)
        split = int(2.0 * PPM)
        tex = np.concatenate([left[:, :split], right[:, split:]], axis=1)
        cv2.rectangle(tex, (split - 4, 0), (split + 4, h), (95, 110, 140), -1)  # door threshold strip
        cv2.rectangle(tex, (int(0.2 * PPM), int(2.5 * PPM)), (int(0.4 * PPM), int(2.7 * PPM)), (120, 120, 120), -1)
        for y in range(int(2.5 * PPM), int(2.7 * PPM), 4):  # floor drain grate
            cv2.line(tex, (int(0.2 * PPM), y), (int(0.4 * PPM), y), (60, 60, 60), 1)
        for z in ZONES:  # wetness probes: small dark pucks on the floor
            cx, cy = int(z.sensor[0] * PPM), int(z.sensor[1] * PPM)
            cv2.rectangle(tex, (cx - 3, cy - 2), (cx + 3, cy + 2), (40, 40, 40), -1)
        lights = [render.Light(1.1 * PPM, 0.8 * PPM, 60, 0.3, 0.9), render.Light(3.0 * PPM, 1.2 * PPM, 70, 1.6, 0.7)]
        self.refl = render.reflections(h, w, lights)
        self.tex = np.clip(tex + 25.0 * self.refl[..., None], 0, 255)  # glossy dry tiles
        out = (640, 480)
        dst = np.float32([[95, 40], [545, 40], [700, 545], [-60, 545]])
        src = np.float32([[0, 0], [w - 1, 0], [w - 1, h - 1], [0, h - 1]])
        self.camera = render.Camera(cv2.getPerspectiveTransform(src, dst), out, (196, 204, 206))

    def _to_camera(self, xy_m: tuple) -> tuple:
        p = np.array([[[xy_m[0] * PPM, xy_m[1] * PPM]]], np.float32)
        q = cv2.perspectiveTransform(p, self.camera.H)[0, 0]
        return float(q[0]) / self.camera.size[0], float(q[1]) / self.camera.size[1]

    def zone_configs(self) -> list[Zone]:
        """PipeGen zones, calibrated exactly like an installer would with a tape measure."""
        out = []
        for z in ZONES:
            corners = [(z.x0 + 0.05, 0.05), (z.x1 - 0.05, 0.05), (z.x1 - 0.05, FLOOR_M[1] - 0.05),
                       (z.x0 + 0.05, FLOOR_M[1] - 0.05)]
            img = [self._to_camera(c) for c in corners]
            out.append(Zone(z.id, polygon=[list(p) for p in img], floor_image_points=[list(p) for p in img],
                            floor_metric_points=[list(c) for c in corners]))
        return out

    # ---- physics ---------------------------------------------------------------
    def step(self, dt: float) -> None:
        self.t += dt
        for v in self.valves.values():
            v.step(dt)
        for p in self.pools:
            L = p.leak
            if self.t < L.start_s:
                continue
            if not p.started:
                p.started = True
                p.volume_l += L.initial_l
            inflow = 0.0
            if L.flow_lpm and (L.stop_s is None or self.t < L.stop_s):
                inflow = L.flow_lpm * (1.0 if not L.controlled else self.valves[L.zone].open_fraction)
            p.volume_l = max(0.0, p.volume_l + (inflow - L.drain_lpm - EVAPORATION_LPM) * dt / 60.0)

    def inflow_lpm(self, zone: str) -> float:
        total = 0.0
        for p in self.pools:
            L = p.leak
            if L.zone == zone and self.t >= L.start_s and L.flow_lpm and (L.stop_s is None or self.t < L.stop_s):
                total += L.flow_lpm * (1.0 if not L.controlled else self.valves[zone].open_fraction)
        return total

    def true_area(self, zone: str) -> float:
        return sum(p.area_m2 for p in self.pools if p.leak.zone == zone)

    def sensor_wet(self, zone: str) -> bool:
        sx, sy = self.zones[zone].sensor
        return any(p.shape.covers(sx * PPM, sy * PPM, p.area_px) for p in self.pools)

    def wetness_raw(self, zone: str) -> int:
        """12-bit ADC of a resistive probe: ~3000 dry, ~1200 wet."""
        base = 1200 if self.sensor_wet(zone) else 3000
        return int(np.clip(base + self.rng.normal(0, 40), 0, 4095))

    @property
    def camera_ok(self) -> bool:
        off = self.scenario.camera_off_after_s
        return off is None or self.t < off

    def render(self) -> tuple[np.ndarray, np.ndarray]:
        w, h = int(FLOOR_M[0] * PPM), int(FLOOR_M[1] * PPM)
        mask = np.zeros((h, w), bool)
        for p in self.pools:
            mask |= p.shape.mask(p.area_px)
        img = render.compose_water(self.tex, mask, self.refl, np.random.default_rng(99), murk=0.15)
        frame = render.photograph(img, self.camera, self.rng, exposure=0.95, noise=2.0)
        return frame, render.warp_mask(mask, self.camera)
