"""Frames in, zone-locked leak events out.

    frame -> segmenter (TensorRT/ONNX) -> water mask -> per-zone metric area
          -> ZoneTracker (persistence, growth) -> leak_event JSON over MQTT

The pipeline also listens to the valve nodes' state/receipt topics so the
overlay shows the physical loop closing on top of the camera feed.
"""

from __future__ import annotations

import hashlib
import time
import uuid
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path

import cv2
import numpy as np

from .config import PipeConfig
from .contract import SCHEMA_EVENT, iso_utc, topic
from .tracker import Emission, ZoneTracker

STATE_COLOURS = {  # BGR
    None: (200, 200, 200), "IDLE": (90, 200, 90), "SUSPECT": (0, 200, 255), "CONFIRMING": (0, 140, 255),
    "CLOSED": (0, 0, 255), "VERIFYING": (0, 0, 255), "LATCHED": (255, 120, 0), "FAULT": (180, 0, 255),
}


def _label(img: np.ndarray, text: str, org: tuple[int, int], col=(255, 255, 255), scale: float = 0.45) -> None:
    """Text on a translucent dark band: stays legible on bright tiles and after video compression."""
    (tw, th), base = cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, scale, 1)
    x, y = org
    x0, y0, x1, y1 = max(0, x - 4), max(0, y - th - 5), min(img.shape[1], x + tw + 4), min(img.shape[0], y + base + 3)
    roi = img[y0:y1, x0:x1]
    roi[:] = (roi * 0.35).astype(np.uint8)
    cv2.putText(img, text, (x, y), cv2.FONT_HERSHEY_SIMPLEX, scale, col, 1, cv2.LINE_AA)


@dataclass
class ZoneResult:
    zone_id: str
    area_m2: float
    growth: float
    confidence: float
    active: bool
    emissions: list[Emission]


@dataclass
class FrameResult:
    t: float
    water: np.ndarray
    zones: list[ZoneResult]
    infer_ms: float
    events: list[dict] = field(default_factory=list)


class Pipeline:
    def __init__(self, cfg: PipeConfig, segmenter, bus, on_event=None) -> None:
        self.cfg = cfg
        self.segmenter = segmenter
        self.bus = bus
        self.on_event = on_event
        self.trackers = {z.id: ZoneTracker(z.id, cfg.tracker) for z in cfg.zones}
        self.device_state: dict[str, dict] = {}
        self.last_receipt: dict[str, dict] = {}
        self.seq = 0
        self._updates: dict[str, int] = {}
        self._infer_ms: deque[float] = deque(maxlen=50)
        self._frame_t: deque[float] = deque(maxlen=50)
        self.evidence_dir = Path(cfg.evidence_dir)
        self.evidence_dir.mkdir(parents=True, exist_ok=True)
        base = f"{cfg.topic_prefix}/{cfg.site_id}/zone/+"
        bus.subscribe(f"{base}/state", self._on_state)
        bus.subscribe(f"{base}/receipt", self._on_receipt)

    # ---- valve node feedback ------------------------------------------------
    def _on_state(self, topic_: str, msg: dict) -> None:
        self.device_state[msg.get("zone_id", topic_.split("/")[-2])] = msg

    def _on_receipt(self, topic_: str, msg: dict) -> None:
        self.last_receipt[msg.get("zone_id", topic_.split("/")[-2])] = msg

    # ---- per frame -----------------------------------------------------------
    def process(self, frame: np.ndarray, t: float, meta: dict | None = None) -> FrameResult:
        t0 = time.perf_counter()
        prob = self.segmenter.predict(frame, meta)
        infer_ms = (time.perf_counter() - t0) * 1000.0
        self._infer_ms.append(infer_ms)
        self._frame_t.append(t)
        h, w = frame.shape[:2]
        prob_full = cv2.resize(prob, (w, h), interpolation=cv2.INTER_LINEAR)
        water = prob_full >= self.cfg.model.threshold
        result = FrameResult(t, water, [], infer_ms)
        for zone in self.cfg.zones:
            zw = water & zone.roi(w, h)
            area = zone.area_m2(zw)
            conf = float(prob_full[zw].mean()) if zw.any() else 0.0
            tracker = self.trackers[zone.id]
            emissions = tracker.update(t, area, conf)
            for em in emissions:
                result.events.append(self._publish(zone, em, t, frame, zw))
            result.zones.append(ZoneResult(zone.id, tracker.area, tracker.growth, tracker.confidence,
                                           tracker.active, emissions))
        return result

    def _snapshot(self, zone, em: Emission, t: float, frame: np.ndarray, zone_water: np.ndarray) -> tuple[str, str]:
        img = frame.copy()
        tint = img.copy()
        tint[zone_water] = (255, 120, 0)
        img = cv2.addWeighted(tint, 0.35, img, 0.65, 0)
        h, w = img.shape[:2]
        cv2.polylines(img, [zone.polygon_px(w, h)], True, (0, 255, 255), 2)
        label = f"{zone.id} {em.kind} area={em.pool_area:.3f}m2 growth={em.growth_rate:+.3f}m2/min conf={em.confidence:.2f}"
        _label(img, label, (8, 22))
        _label(img, iso_utc(t), (8, h - 10))
        ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 85])
        data = buf.tobytes()
        day = time.strftime("%Y%m%d", time.gmtime(t))
        path = self.evidence_dir / day / f"{em.incident_id[:12]}_{self.seq:06d}_{em.kind}.jpg"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return str(path.relative_to(self.evidence_dir.parent)).replace("\\", "/"), hashlib.sha256(data).hexdigest()

    def _publish(self, zone, em: Emission, t: float, frame: np.ndarray, zone_water: np.ndarray) -> dict:
        self.seq += 1
        n = self._updates.get(em.incident_id, 0)
        self._updates[em.incident_id] = n + 1
        evidence = {
            "backend": self.segmenter.name,
            "model": Path(self.segmenter.model_path).name if self.segmenter.model_path else "oracle",
            "window_s": self.cfg.tracker.window_s,
            "persistence": em.persistence,
            "frames": em.frames,
        }
        if self.segmenter.model_sha256:
            evidence["model_sha256"] = self.segmenter.model_sha256
        if em.kind != "update" or n % max(1, self.cfg.snapshot_every) == 0:
            evidence["snapshot"], evidence["snapshot_sha256"] = self._snapshot(zone, em, t, frame, zone_water)
        event = {
            "schema": SCHEMA_EVENT,
            "event_id": uuid.uuid4().hex,
            "incident_id": em.incident_id,
            "kind": em.kind,
            "site_id": self.cfg.site_id,
            "zone_id": zone.id,
            "timestamp": iso_utc(t),
            "seq": self.seq,
            "confidence": em.confidence,
            "pool_area": em.pool_area,
            "growth_rate": em.growth_rate,
            "evidence": evidence,
        }
        self.bus.publish(topic(self.cfg.topic_prefix, self.cfg.site_id, zone.id, "event"), event, qos=1)
        if self.on_event:
            self.on_event(event)
        return event

    # ---- display -------------------------------------------------------------
    @property
    def fps(self) -> float:
        if len(self._frame_t) < 2 or self._frame_t[-1] == self._frame_t[0]:
            return 0.0
        return (len(self._frame_t) - 1) / (self._frame_t[-1] - self._frame_t[0])

    def overlay(self, frame: np.ndarray, result: FrameResult) -> np.ndarray:
        img = frame.copy()
        tint = img.copy()
        tint[result.water] = (255, 120, 0)
        img = cv2.addWeighted(tint, 0.35, img, 0.65, 0)
        h, w = img.shape[:2]
        for i, zr in enumerate(result.zones):
            zone = next(z for z in self.cfg.zones if z.id == zr.zone_id)
            st = self.device_state.get(zr.zone_id, {})
            state = st.get("state") if st.get("online", True) else None
            col = STATE_COLOURS.get(state, (200, 200, 200))
            cv2.polylines(img, [zone.polygon_px(w, h)], True, col, 2)
            valve = st.get("valve", "?")
            lim = "LS:on" if st.get("limit_switch") else "LS:off"
            wet = "wet" if st.get("wet") else "dry"
            line = (f"{zr.zone_id}: {zr.area_m2:.2f}m2 {zr.growth:+.2f}m2/min c={zr.confidence:.2f} | "
                    f"{state or 'offline'} valve={valve} {lim} {wet}")
            _label(img, line, (8, 22 + 22 * i), col)
        ms = sum(self._infer_ms) / max(1, len(self._infer_ms))
        _label(img, f"{self.segmenter.name}  infer {ms:.1f} ms  {iso_utc(result.t)}", (8, h - 10))
        return img
