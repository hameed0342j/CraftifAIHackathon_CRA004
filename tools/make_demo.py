"""Assemble the submission demo video (H.264, 1280x720) from simulator runs.

    python -m simlab.run --scenario leak --backend tensorrt --qemu-zone bathroom-1 --power-cut 58,5 --out runs/qemu-leak
    python -m simlab.run --all --backend tensorrt
    python tools/make_demo.py            # -> docs/media/leaklatch_demo.mp4
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipegen.video import VideoSink  # noqa: E402

W, H, FPS = 1280, 720, 20
BG = (24, 20, 16)
ACCENT = (0, 200, 255)


def text(img, s, xy, scale=0.8, col=(240, 240, 240), thick=1, center=False):
    if center:
        (tw, _), _ = cv2.getTextSize(s, cv2.FONT_HERSHEY_SIMPLEX, scale, thick)
        xy = ((W - tw) // 2, xy[1])
    cv2.putText(img, s, xy, cv2.FONT_HERSHEY_SIMPLEX, scale, col, thick, cv2.LINE_AA)


def card(lines: list[tuple], seconds: float, sink: VideoSink) -> None:
    img = np.full((H, W, 3), BG, np.uint8)
    cv2.rectangle(img, (0, 0), (W, 8), ACCENT, -1)
    for s, y, scale, col, thick in lines:
        text(img, s, (0, y), scale, col, thick, center=True)
    for _ in range(int(seconds * FPS)):
        sink.write(img)


def play(path: Path, sink: VideoSink, start_s: float = 0.0, end_s: float | None = None, every: int = 1,
         title: str | None = None, caption: list[str] | None = None) -> None:
    """Copy frames (1 frame = 0.1 s of simulated time) of a run video, optionally framed for 720p."""
    cap = cv2.VideoCapture(str(path))
    n = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
    a, b = int(start_s * 10), min(n, int(end_s * 10) if end_s else n)
    cap.set(cv2.CAP_PROP_POS_FRAMES, a)
    for i in range(a, b):
        ok, f = cap.read()
        if not ok:
            break
        if (i - a) % every:
            continue
        if f.shape[0] != H:  # 1280x480 runs: add a title band on top and a caption band below
            frame = np.full((H, W, 3), BG, np.uint8)
            frame[80:80 + f.shape[0]] = f
            if title:
                text(frame, title, (24, 52), 1.0, ACCENT, 2)
            for k, ln in enumerate(caption or []):
                text(frame, ln, (24, 600 + 38 * k), 0.75)
            f = frame
        sink.write(f)


def play_real(video: Path, events_jsonl: Path, sink: VideoSink, start_s: float, end_s: float, every: int,
              title: str, notes: list[str], credit: str) -> None:
    """Annotated real footage (portrait) on the left, the live leak_event stream on the right."""
    recs = [json.loads(ln) for ln in events_jsonl.read_text(encoding="utf-8").splitlines() if ln.strip()]
    cap = cv2.VideoCapture(str(video))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    a, b = int(start_s * fps), int(end_s * fps)
    cap.set(cv2.CAP_PROP_POS_FRAMES, a)
    for i in range(a, b):
        ok, f = cap.read()
        if not ok:
            break
        if (i - a) % every:
            continue
        frame = np.full((H, W, 3), BG, np.uint8)
        fw = int(f.shape[1] * H / f.shape[0])
        frame[:, :fw] = cv2.resize(f, (fw, H))
        x = fw + 28
        text(frame, title, (x, 50), 0.95, ACCENT, 2)
        for k, ln in enumerate(notes):
            text(frame, ln, (x, 92 + 30 * k), 0.58, (230, 230, 230))
        y = 92 + 30 * len(notes) + 30
        text(frame, "leak_event JSON over MQTT (latest first)", (x, y), 0.6, ACCENT, 1)
        shown = [r for r in recs if r["frame"] <= i][-7:][::-1]
        for k, r in enumerate(shown):
            e = r["event"]
            line = (f"{r['video_time_s']:5.1f}s  {e['kind']:6s} zone={e['zone_id']}  area={e['pool_area']:.2f}  "
                    f"growth={e['growth_rate']:+.1f}  conf={e['confidence']:.2f}")
            col = (90, 220, 90) if e["kind"] == "detect" else (200, 200, 200) if e["kind"] == "update" else (80, 80, 255)
            cv2.putText(frame, line, (x, y + 34 + 28 * k), cv2.FONT_HERSHEY_PLAIN, 1.15, col, 1, cv2.LINE_AA)
        text(frame, credit, (x, H - 22), 0.45, (150, 150, 150))
        sink.write(frame)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--runs", type=Path, default=ROOT / "runs")
    ap.add_argument("--out", type=Path, default=ROOT / "docs" / "media" / "leaklatch_demo.mp4")
    args = ap.parse_args()
    trt = json.loads((ROOT / "models" / "trt_report.json").read_text())
    args.out.parent.mkdir(parents=True, exist_ok=True)
    sink = VideoSink(args.out, FPS, (W, H))
    white, grey = (240, 240, 240), (170, 170, 170)

    card([("LeakLatch", 230, 2.6, ACCENT, 5),
          ("Zone-locked evidence-to-action chain for water leaks in PGs and hostels", 300, 0.85, white, 1),
          ("camera sees water pooling  ->  ESP32 confirms with a floor probe  ->  shuts the zone valve", 380, 0.7, grey, 1),
          ("->  proves it with a limit switch  ->  proves the leak stopped with the camera", 420, 0.7, grey, 1),
          ("CraftifAI Physical AI Hackathon  |  Track A PipeGen + Track B FirmGen + closed loop", 520, 0.65, white, 1),
          ("No hardware was harmed: real firmware in an emulated ESP32, simulated bathroom", 600, 0.6, grey, 1)],
         5.5, sink)
    card([("1.  A real leak, end to end", 300, 1.4, white, 3),
          ("Camera brain: TensorRT FP16 engine (%.1f ms/frame on %s)" % (trt["latency_ms"]["p50"], trt["gpu"]),
           380, 0.62, grey, 1),
          ("Valve node: the real FirmGen firmware (ESP-IDF v5.5) flashed into Espressif's QEMU ESP32", 420, 0.62, grey, 1),
          ("Servo, limit switch and wetness probe wired to the simulated bathroom.  Played at 2x.", 460, 0.62, grey, 1),
          ("Watch for: probe confirms -> valve closes -> limit switch -> VERIFIED -> power cut -> reboot", 520, 0.62, ACCENT, 1)],
         4.0, sink)
    play(args.runs / "qemu-leak" / "demo.mp4", sink)

    card([("2.  It doesn't cry wolf", 320, 1.4, white, 3),
          ("Same TensorRT model, same C state machine, four situations a naive system gets wrong", 390, 0.65, grey, 1)],
         3.0, sink)
    play(args.runs / "mop" / "demo.mp4", sink, 0, 56, every=3, title="Mopping a bucket spill (6x)",
         caption=["The camera sees water, but the pool is shrinking and the probe stays dry.",
                  "SUSPECT -> IDLE (vision_unconfirmed). The valve never moves."])
    play(args.runs / "zone-lock" / "demo.mp4", sink, 0, 38, every=2, title="Leak in the corridor only (4x)",
         caption=["The corridor node closes its own valve and verifies it.",
                  "The bathroom node receives the same events and rejects them: zone lock."])
    play(args.runs / "stuck-valve" / "demo.mp4", sink, 0, 30, every=2, title="Valve jammed at 40 degrees (4x)",
         caption=["The limit switch never closes: one retry, then FAULT valve_not_closed, alarm on.",
                  "LeakLatch never claims a shut-off it cannot prove."])
    play(args.runs / "upstream" / "demo.mp4", sink, 0, 80, every=4, title="Overflow from the overhead tank (8x)",
         caption=["The valve closes and the limit switch confirms, but the camera sees the pool keep growing.",
                  "FAULT leak_persists: the water is not coming through this valve. Look elsewhere."])

    real = args.runs / "real-smu"
    if (real / "annotated.mp4").exists():
        card([("3.  Real footage, honestly", 300, 1.4, white, 3),
              ("A real burst water pipe (Singapore Management University, 2017), found on Wikimedia Commons", 380, 0.62,
               grey, 1),
              ("Same TensorRT model and pipeline: 1,658 frames at 90 fps end to end, 28 schema-valid leak events", 420,
               0.62, grey, 1),
              ("It catches puddles and pooling on paving; it misses a large reflective indoor flood.", 460, 0.62,
               ACCENT, 1),
              ("That gap is why LeakLatch never shuts a valve on the camera alone.", 500, 0.62, ACCENT, 1)],
             4.0, sink)
        play_real(real / "annotated.mp4", real / "events.jsonl", sink, 14, 50, every=2,
                  title="Real input: burst pipe (2x)",
                  notes=["Blue = pixels the model calls water. Zone 'floor' = lower half of the frame.",
                         "Caught: the pool around the worker's feet and the flooded paving.",
                         "Missed: most of the shiny orange indoor floor (thin reflective film).",
                         "False hits on glass and windows above the floor zone are ignored by the zone.",
                         "Growth rate jumps around because this is a moving handheld phone;",
                         "LeakLatch assumes a fixed, wall-mounted camera."],
                  credit="Footage: 'Flooding at the School of Law, Singapore Management University - 20170122', "
                         "Smuconlaw, CC BY-SA 4.0")

    card([("Results", 140, 1.5, ACCENT, 3),
          ("6 / 6 closed-loop scenarios pass  |  every MQTT message validated against JSON Schemas", 230, 0.7, white, 1),
          ("TensorRT %s FP16: %.2f ms p50, %.0f FPS  |  0.997 mask agreement with ONNX" % (
              trt["tensorrt"], trt["latency_ms"]["p50"], trt["throughput_fps"]), 290, 0.7, white, 1),
          ("FirmGen: ESP-IDF v5.5 build, runs in QEMU, 128 host checks of the state machine", 350, 0.7, white, 1),
          ("Survives a power cut: LATCHED restored from flash, valve stays shut", 410, 0.7, white, 1),
          ("~1.5-2.5k INR per zone: ESP32 + servo + ball valve + limit switch + probe", 470, 0.7, white, 1),
          ("github.com/hameed0342j/CraftifAIHackathon_CRA004", 580, 0.95, ACCENT, 2)],
         7.0, sink)
    sink.close()
    print(f"wrote {args.out} ({args.out.stat().st_size / 1e6:.1f} MB)")


if __name__ == "__main__":
    main()
