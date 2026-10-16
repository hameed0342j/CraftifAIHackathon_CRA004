"""YAML configuration for a PipeGen deployment (see configs/*.yaml)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

import yaml

from .tracker import TrackerConfig
from .zones import Zone


@dataclass
class MqttConfig:
    host: str = "localhost"
    port: int = 1883
    username: str | None = None
    password: str | None = None
    tls: bool = False


@dataclass
class ModelConfig:
    backend: str = "auto"  # auto | tensorrt | onnxruntime | oracle
    engine: str | None = "models/leaklatch_waterseg.engine"
    onnx: str | None = "models/leaklatch_waterseg.onnx"
    input_size: int = 320
    threshold: float = 0.5


@dataclass
class PipeConfig:
    site_id: str = "pg-demo-01"
    topic_prefix: str = "leaklatch"
    source: str = "0"  # camera index, video file or RTSP URL
    fps: float = 10.0
    mqtt: MqttConfig = field(default_factory=MqttConfig)
    model: ModelConfig = field(default_factory=ModelConfig)
    tracker: TrackerConfig = field(default_factory=TrackerConfig)
    evidence_dir: str = "evidence"
    snapshot_every: int = 5  # keep an annotated JPEG for the detect, every Nth update, and the clear
    zones: list[Zone] = field(default_factory=list)


def load(path: str | Path) -> PipeConfig:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    root = Path(path).resolve().parent.parent  # configs/ lives in the repo root

    def resolve(p):
        if p is None:
            return None
        return str(p) if Path(p).is_absolute() else str(root / p)

    model = ModelConfig(**raw.get("model", {}))
    model.engine, model.onnx = resolve(model.engine), resolve(model.onnx)
    return PipeConfig(
        site_id=raw.get("site_id", "pg-demo-01"),
        topic_prefix=raw.get("topic_prefix", "leaklatch"),
        source=str(raw.get("source", "0")),
        fps=float(raw.get("fps", 10.0)),
        mqtt=MqttConfig(**raw.get("mqtt", {})),
        model=model,
        tracker=TrackerConfig(**raw.get("tracker", {})),
        evidence_dir=resolve(raw.get("evidence_dir", "evidence")),
        snapshot_every=int(raw.get("snapshot_every", 5)),
        zones=[Zone(**z) for z in raw.get("zones", [])],
    )
