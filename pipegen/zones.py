"""Zones: image regions locked to one valve, with metric floor calibration.

A zone's pool area is the sum, over water pixels inside its polygon, of the floor
area each pixel covers. With a floor homography H (image -> metres) that per-pixel
area is |det H| / w(x, y)^3, the Jacobian of the projective map, so pools far from
the camera are not under-counted.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import cv2
import numpy as np


@dataclass
class Zone:
    id: str
    polygon: list                     # [[x, y], ...] normalised 0..1 image coordinates
    floor_image_points: list | None = None   # 4 normalised image points on the floor plane
    floor_metric_points: list | None = None  # the same 4 points in metres
    frame_area_m2: float | None = None       # fallback: floor area the whole frame would cover
    _cache: dict = field(default_factory=dict, repr=False)

    def __post_init__(self) -> None:
        if self.floor_image_points is None and self.frame_area_m2 is None:
            raise ValueError(f"zone {self.id}: give floor_image_points+floor_metric_points or frame_area_m2")

    def _prepare(self, w: int, h: int) -> tuple[np.ndarray, np.ndarray]:
        key = (w, h)
        if key not in self._cache:
            roi = np.zeros((h, w), np.uint8)
            pts = np.round(np.asarray(self.polygon, np.float64) * [w, h]).astype(np.int32)
            cv2.fillPoly(roi, [pts], 1)
            if self.floor_image_points is not None:
                src = (np.asarray(self.floor_image_points, np.float64) * [w, h]).astype(np.float32)
                dst = np.asarray(self.floor_metric_points, np.float32)
                H = cv2.getPerspectiveTransform(src, dst).astype(np.float64)
                yy, xx = np.mgrid[0:h, 0:w].astype(np.float64)
                wz = H[2, 0] * (xx + 0.5) + H[2, 1] * (yy + 0.5) + H[2, 2]
                px_area = np.abs(np.linalg.det(H)) / np.abs(wz) ** 3
            else:
                px_area = np.full((h, w), self.frame_area_m2 / (w * h))
            self._cache[key] = (roi.astype(bool), (px_area * roi).astype(np.float32))
        return self._cache[key]

    def roi(self, w: int, h: int) -> np.ndarray:
        return self._prepare(w, h)[0]

    def area_m2(self, water: np.ndarray) -> float:
        """water: bool mask at frame resolution."""
        _, px_area = self._prepare(water.shape[1], water.shape[0])
        return float(px_area[water].sum())

    def polygon_px(self, w: int, h: int) -> np.ndarray:
        return np.round(np.asarray(self.polygon, np.float64) * [w, h]).astype(np.int32)
