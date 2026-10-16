"""Run PipeGen on a camera, video file or RTSP stream.

    python -m pipegen --config configs/site.example.yaml --show
    python -m pipegen --config configs/site.example.yaml --source demo.mp4 --record out.mp4
"""

from __future__ import annotations

import argparse
import logging
import time

import cv2

from .config import load
from .backends import load_segmenter
from .contract import iso_utc
from .pipeline import Pipeline
from .transport import MqttBus

log = logging.getLogger("pipegen")


def main() -> None:
    ap = argparse.ArgumentParser(description="LeakLatch PipeGen")
    ap.add_argument("--config", required=True)
    ap.add_argument("--source", help="override: camera index, file or rtsp:// URL")
    ap.add_argument("--backend", choices=["auto", "tensorrt", "onnxruntime"], help="override model.backend")
    ap.add_argument("--show", action="store_true", help="open a preview window")
    ap.add_argument("--record", help="write the annotated stream to this .mp4")
    ap.add_argument("--max-frames", type=int, default=0)
    args = ap.parse_args()
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

    cfg = load(args.config)
    if args.source:
        cfg.source = args.source
    if args.backend:
        cfg.model.backend = args.backend
    seg = load_segmenter(cfg.model.backend, cfg.model.input_size, cfg.model.engine, cfg.model.onnx)
    log.info("backend %s, model %s", seg.name, seg.model_path)

    health = f"{cfg.topic_prefix}/{cfg.site_id}/pipegen/health"
    bus = MqttBus(cfg.mqtt.host, cfg.mqtt.port, cfg.mqtt.username, cfg.mqtt.password, cfg.mqtt.tls,
                  client_id=f"pipegen-{cfg.site_id}", will=(health, {"online": False}))
    if not bus.wait_connected(10):
        log.warning("MQTT broker %s:%d not reachable yet; events will be sent once it is", cfg.mqtt.host,
                    cfg.mqtt.port)
    pipe = Pipeline(cfg, seg, bus, on_event=lambda e: log.info(
        "%s %s area=%.3f growth=%+.3f conf=%.2f", e["zone_id"], e["kind"], e["pool_area"], e["growth_rate"],
        e["confidence"]))

    src = int(cfg.source) if cfg.source.isdigit() else cfg.source
    cap = cv2.VideoCapture(src)
    if not cap.isOpened():
        raise SystemExit(f"cannot open source {cfg.source!r}")
    is_file = isinstance(src, str) and not src.startswith(("rtsp://", "http://", "https://"))
    file_fps = cap.get(cv2.CAP_PROP_FPS) or cfg.fps
    writer = None
    start = time.time()
    n = 0
    last_health = 0.0
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            t = start + n / file_fps if is_file else time.time()  # video files keep their own timeline
            res = pipe.process(frame, t)
            n += 1
            if t - last_health >= 10:
                last_health = t
                bus.publish(health, {"online": True, "backend": seg.name, "fps": round(pipe.fps, 1),
                                     "model_sha256": seg.model_sha256, "timestamp": iso_utc(t)}, retain=True)
            if args.show or args.record:
                vis = pipe.overlay(frame, res)
                if args.record:
                    if writer is None:
                        writer = cv2.VideoWriter(args.record, cv2.VideoWriter_fourcc(*"mp4v"), cfg.fps,
                                                 (vis.shape[1], vis.shape[0]))
                    writer.write(vis)
                if args.show:
                    cv2.imshow("LeakLatch PipeGen", vis)
                    if cv2.waitKey(1) & 0xFF in (27, ord("q")):
                        break
            if args.max_frames and n >= args.max_frames:
                break
    finally:
        cap.release()
        if writer:
            writer.release()
        bus.close()
        cv2.destroyAllWindows()
    log.info("processed %d frames", n)


if __name__ == "__main__":
    main()
