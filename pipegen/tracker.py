"""Per-zone temporal tracking: persistence gating, area smoothing and growth rate.

growth_rate is the least-squares slope of the smoothed pool area over the last
`window_s` seconds of frames in which water was present, in m^2/min. A leak
gives a sustained positive slope; a closed valve drives it to ~0; mopping
drives it negative.
"""

from __future__ import annotations

import uuid
from collections import deque
from dataclasses import dataclass


@dataclass
class TrackerConfig:
    min_area_m2: float = 0.02     # smaller pools are noise / footprints
    on_frames: int = 5            # consecutive water frames before 'detect'
    off_frames: int = 15          # consecutive dry frames before 'clear'
    window_s: float = 10.0        # growth regression window
    update_period_s: float = 2.0  # 'update' cadence while a pool is present
    ema_alpha: float = 0.35       # area smoothing
    persist_frames: int = 10      # confidence uses persistence over this many frames


@dataclass
class Emission:
    kind: str           # detect | update | clear
    incident_id: str
    pool_area: float    # m2
    growth_rate: float  # m2/min
    confidence: float
    persistence: float
    frames: int


class ZoneTracker:
    def __init__(self, zone_id: str, cfg: TrackerConfig | None = None) -> None:
        self.zone_id = zone_id
        self.cfg = cfg or TrackerConfig()
        self.active = False
        self.incident_id = ""
        self._ema: float | None = None
        self._on = 0
        self._off = 0
        self._last_emit = -1e9
        self._samples: deque[tuple[float, float]] = deque()   # (t, smoothed area) while water present
        self._recent: deque[tuple[bool, float]] = deque(maxlen=self.cfg.persist_frames)
        self._frames = 0
        self.area = 0.0
        self.growth = 0.0
        self.confidence = 0.0

    def _slope_per_min(self) -> float:
        n = len(self._samples)
        if n < 3:
            return 0.0
        t0 = self._samples[0][0]
        ts = [t - t0 for t, _ in self._samples]
        ys = [a for _, a in self._samples]
        mt, my = sum(ts) / n, sum(ys) / n
        var = sum((t - mt) ** 2 for t in ts)
        if var < 1e-9:
            return 0.0
        cov = sum((t - mt) * (y - my) for t, y in zip(ts, ys))
        return cov / var * 60.0

    def update(self, t: float, area_m2: float, frame_conf: float) -> list[Emission]:
        cfg = self.cfg
        present = area_m2 >= cfg.min_area_m2
        self._recent.append((present, frame_conf if present else 0.0))
        self._ema = area_m2 if self._ema is None else cfg.ema_alpha * area_m2 + (1 - cfg.ema_alpha) * self._ema
        if present:
            self._on += 1
            self._off = 0
            self._samples.append((t, self._ema))
        else:
            self._off += 1
            self._on = 0
        while self._samples and t - self._samples[0][0] > cfg.window_s:
            self._samples.popleft()

        hits = [c for p, c in self._recent if p]
        persistence = len(hits) / len(self._recent)
        mean_conf = sum(hits) / len(hits) if hits else 0.0
        self.confidence = max(0.0, min(1.0, mean_conf * (0.5 + 0.5 * persistence)))
        self.area = self._ema if present or self.active else 0.0
        self.growth = self._slope_per_min()
        if self.active:
            self._frames += 1

        out: list[Emission] = []
        if not self.active and self._on >= cfg.on_frames:
            self.active = True
            self.incident_id = uuid.uuid4().hex
            self._frames = self._on
            self._last_emit = t
            out.append(self._emit("detect", persistence))
        elif self.active and self._off >= cfg.off_frames:
            self.active = False
            out.append(self._emit("clear", persistence, area=0.0))
            self._samples.clear()
            self._ema = 0.0
        elif self.active and t - self._last_emit >= cfg.update_period_s:
            self._last_emit = t
            out.append(self._emit("update", persistence))
        return out

    def _emit(self, kind: str, persistence: float, area: float | None = None) -> Emission:
        return Emission(kind, self.incident_id, round(self.area if area is None else area, 4),
                        round(self.growth, 4), round(self.confidence, 3), round(persistence, 2), self._frames)
