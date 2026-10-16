"""Run PipeGen on a camera, video file or RTSP stream.

    python -m pipegen --config configs/site.example.yaml --show
    python -m pipegen --config configs/site.example.yaml --source demo.mp4 --record out.mp4
    python -m pipegen --config configs/real_smu.yaml --no-mqtt --events-jsonl events.jsonl --record out.mp4
"""

from __future__ import annotations

import argparse
import json
import logging
import time

import cv2

from .config import load
from .backends import load_segmenter
from .contract import iso_utc
from .pipeline import Pipeline
from .transport import InprocBus, MqttBus
from .video import VideoSink

log = logging.getLogger("pipegen")


def main() -> None:
    ap = argparse.ArgumentParser(description="LeakLatch PipeGen")
    ap.add_argument("--config", required=True)
    ap.add_argument("--source", help="override: camera index, file or rtsp:// URL")
    ap.add_argument("--backend", choices=["auto", "tensorrt", "onnxruntime"], help="override model.backend")
    ap.add_argument("--show", action="store_true", help="open a preview window")
    ap.add_argument("--record", help="write the annotated stream to this .mp4")
    ap.add_argument("--max-frames", type=int, default=0)
    ap.add_argument("--no-mqtt", action="store_true", help="offline: keep events in-process (use with --events-jsonl)")
    ap.add_argument("--events-jsonl", help="also append every leak_event to this JSON-lines file, "
                                           "as {frame, video_time_s, topic, event}")
    ap.add_argument("--resize", type=int, default=0, help="scale input frames to this width first")
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
    if args.no_mqtt:
        bus = InprocBus()
    else:
        bus = MqttBus(cfg.mqtt.host, cfg.mqtt.port, cfg.mqtt.username, cfg.mqtt.password, cfg.mqtt.tls,
                      client_id=f"pipegen-{cfg.site_id}", will=(health, {"online": False}))
        if not bus.wait_connected(10):
            log.warning("MQTT broker %s:%d not reachable yet; events will be sent once it is", cfg.mqtt.host,
                        cfg.mqtt.port)
    events_file = open(args.events_jsonl, "a", encoding="utf-8") if args.events_jsonl else None
    cursor = {"frame": 0, "fps": cfg.fps}

    def on_event(e: dict) -> None:
        log.info("%s %s area=%.3f growth=%+.3f conf=%.2f", e["zone_id"], e["kind"], e["pool_area"],
                 e["growth_rate"], e["confidence"])
        if events_file:
            rec = {"frame": cursor["frame"], "video_time_s": round(cursor["frame"] / cursor["fps"], 3),
                   "topic": f"{cfg.topic_prefix}/{cfg.site_id}/zone/{e['zone_id']}/event", "event": e}
            events_file.write(json.dumps(rec) + "\n")
            events_file.flush()

    pipe = Pipeline(cfg, seg, bus, on_event=on_event)

    src = int(cfg.source) if cfg.source.isdigit() else cfg.source
    cap = cv2.VideoCapture(src)
    if not cap.isOpened():
        raise SystemExit(f"cannot open source {cfg.source!r}")
    is_file = isinstance(src, str) and not src.startswith(("rtsp://", "http://", "https://"))
    file_fps = cap.get(cv2.CAP_PROP_FPS) or cfg.fps
    cursor["fps"] = file_fps if is_file else cfg.fps
    writer = None
    start = time.time()
    n = 0
    last_health = 0.0
    try:
        while True:
            ok, frame = cap.read()
            if not ok:
                break
            if args.resize and frame.shape[1] != args.resize:
                frame = cv2.resize(frame, (args.resize, round(frame.shape[0] * args.resize / frame.shape[1])),
                                   interpolation=cv2.INTER_AREA)
            t = start + n / file_fps if is_file else time.time()  # video files keep their own timeline
            cursor["frame"] = n
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
                        writer = VideoSink(args.record, file_fps if is_file else cfg.fps,
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
            writer.close()
        if events_file:
            events_file.close()
        bus.close()
        cv2.destroyAllWindows()
    log.info("processed %d frames", n)


if __name__ == "__main__":
    main()
