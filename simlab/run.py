"""Closed-loop simulator: world -> camera -> PipeGen -> MQTT contract -> virtual
ESP32 nodes (real C state machine) -> valve -> world.

    python -m simlab.run --scenario leak --backend onnxruntime
    python -m simlab.run --all --backend oracle --no-video      # fast regression run
    python -m simlab.run --scenario leak --mqtt localhost:1883  # through a real broker
    python -m simlab.run --scenario leak --backend tensorrt --mqtt localhost:1883 \
        --qemu-zone bathroom-1 --power-cut 58,5                  # real firmware in an emulated ESP32

Writes runs/<scenario>/{demo.mp4, messages.jsonl, timeline.json, summary.json, report.html, evidence/}
(+ esp32_serial.log in QEMU mode).
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import time
from pathlib import Path

import cv2
import numpy as np

from pipegen.backends import load_segmenter
from pipegen.config import ModelConfig, PipeConfig
from pipegen.contract import SCHEMA_COMMAND, iso_utc, topic, validate
from pipegen.pipeline import STATE_COLOURS, Pipeline
from pipegen.transport import InprocBus, MqttBus
from pipegen.video import VideoSink

from . import report
from .device import VirtualValveNode
from .firmware_node import FirmwareNode
from .scenarios import SCENARIOS, Scenario
from .world import ZONES, World

ROOT = Path(__file__).resolve().parents[1]
SITE, PREFIX = "pg-demo-01", "leaklatch"
log = logging.getLogger("simlab")



STAGE = {  # caption for the firmware zone, by (state, reason) then state
    ("IDLE", "operator_reset"): "Warden resets after the repair: valve reopens; the leftover puddle is ignored (same incident).",
    ("LATCHED", "verified"): "Camera: pool stopped growing. Loop closed and VERIFIED (limit switch + camera).",
    ("LATCHED", "restored_after_reboot"): "ESP32 rebooted: LATCHED restored from flash (NVS). The valve stays shut.",
    ("LATCHED", "mechanical_only"): "No camera after closing: latched on the limit switch alone.",
    ("FAULT", "valve_not_closed"): "Limit switch never closed: FAULT, alarm on. Someone must check the valve.",
    ("FAULT", "leak_persists"): "Valve shut but the pool keeps growing: FAULT. The source is not behind this valve.",
    "SUSPECT": "PipeGen (TensorRT) sees water pooling -> leak_event over MQTT -> ESP32: SUSPECT, checking its probe.",
    "CONFIRMING": "The wetness probe agrees with the camera: two independent senses -> CONFIRMING.",
    "CLOSED": "ESP32 firmware drives the servo: the zone valve is closing.",
    "VERIFYING": "Limit switch pressed: valve mechanically closed. Now the camera must see the growth stop...",
    "OFFLINE": "ESP32 is off / not on MQTT.",
    "BOOTING": "ESP32 booting the FirmGen image...",
}


def caption_for(sc: Scenario, world: World, node, power_off: bool, lost_l: float) -> str:
    if power_off:
        return "POWER CUT: the ESP32 is off. The ball valve holds its position."
    st, rs = node.fsm.state, node.fsm.reason
    text = STAGE.get((st, rs)) or STAGE.get(st)
    if text:
        if st == "LATCHED" and rs == "verified":
            text += f"  Water lost: {lost_l:.2f} L."
        return text
    leak = next((L for L in sc.leaks if L.zone == node.zone), None)
    if leak and world.t >= leak.start_s and not node.receipts:
        return f"A pipe joint in {node.zone} starts leaking ({leak.flow_lpm or leak.initial_l:.1f} L/min)..."
    return "Normal: valve open, floor dry. One camera + PipeGen (TensorRT) watching both zones."


_SERIAL_KEEP = re.compile(r"leaklatch|ll_hw_sim|ll_net|ll_store|=====|esp_netif_handlers|app_main")


def draw_console(lines: list[str], caption: str, title: str) -> np.ndarray:
    strip = np.full((240, 1280, 3), 12, np.uint8)
    strip[:56] = (40, 32, 20)
    _text(strip, caption, (16, 36), 0.62, (255, 255, 255), 1)
    _text(strip, title, (16, 80), 0.5, (0, 200, 255))
    shown = [ln for ln in lines if _SERIAL_KEEP.search(ln)][-7:]
    for k, ln in enumerate(shown):
        col = (90, 220, 90) if ln.startswith("I ") else (0, 200, 255) if ln.startswith("W ") else \
            (80, 80, 255) if ln.startswith("E ") else (200, 200, 200)
        cv2.putText(strip, ln[:150], (16, 106 + 19 * k), cv2.FONT_HERSHEY_PLAIN, 1.05, col, 1, cv2.LINE_AA)
    return strip


def _text(img, s, xy, scale=0.5, col=(235, 235, 235), thick=1):
    cv2.putText(img, s, xy, cv2.FONT_HERSHEY_SIMPLEX, scale, col, thick, cv2.LINE_AA)


def draw_panel(world: World, nodes: dict, sc: Scenario, pipe: Pipeline, receipts: list[dict], t: float) -> np.ndarray:
    p = np.full((480, 640, 3), 28, np.uint8)
    _text(p, "LeakLatch closed loop (simulated hardware)", (14, 26), 0.6, (255, 255, 255), 1)
    _text(p, f"{sc.title}   t = {t:6.1f} s", (14, 50), 0.48, (190, 190, 190))
    for i, z in enumerate(ZONES):
        node = nodes[z.id]
        y0 = 66 + i * 160
        st = node.fsm.state
        col = STATE_COLOURS.get(st, (200, 200, 200))
        cv2.rectangle(p, (10, y0), (630, y0 + 150), (55, 55, 55), 1)
        _text(p, z.id, (20, y0 + 24), 0.6, (255, 255, 255))
        kind = getattr(node, "kind", "virtual node (same C state machine)")
        _text(p, kind, (20, y0 + 42), 0.38, (0, 200, 255) if "QEMU" in kind else (150, 150, 150))
        cv2.rectangle(p, (170, y0 + 6), (330, y0 + 32), col, -1)
        _text(p, st, (178, y0 + 26), 0.6, (0, 0, 0), 2)
        _text(p, node.fsm.reason, (340, y0 + 26), 0.45, (200, 200, 200))
        # ball valve: handle in line with the pipe = open, across it = closed
        v = world.valves[z.id]
        cx, cy = 70, y0 + 95
        cv2.line(p, (cx - 50, cy), (cx + 50, cy), (120, 120, 120), 10)
        cv2.circle(p, (cx, cy), 22, (90, 90, 90), -1)
        a = np.deg2rad(v.angle)
        cv2.line(p, (int(cx - 30 * np.cos(a)), int(cy - 30 * np.sin(a))),
                 (int(cx + 30 * np.cos(a)), int(cy + 30 * np.sin(a))), (0, 200, 255), 6)
        _text(p, f"valve {v.angle:4.0f} deg", (20, y0 + 140), 0.42)
        def led(x, on, label, on_col):
            cv2.circle(p, (x, y0 + 60), 9, on_col if on else (70, 70, 70), -1)
            _text(p, label, (x + 16, y0 + 65), 0.45)
        led(150, v.limit_pressed, "limit switch", (0, 220, 0))
        led(300, node._wet, f"wetness raw {node.wet_raw}", (255, 150, 0))
        led(500, node.alarm, "alarm", (0, 0, 255))
        zr = next((r for r in pipe.trackers.values() if r.zone_id == z.id), None)
        _text(p, f"inflow {world.inflow_lpm(z.id):4.2f} L/min", (150, y0 + 98), 0.45)
        _text(p, f"pool true {world.true_area(z.id):5.2f} m2   seen {zr.area if zr else 0:5.2f} m2   "
                 f"growth {zr.growth if zr else 0:+5.2f} m2/min", (150, y0 + 122), 0.45)
        cnt = node.fsm.counter(1)
        _text(p, f"zone-lock rejections {cnt}", (150, y0 + 144), 0.42, (160, 160, 160))
    _text(p, "receipts (evidence -> action -> proof)", (14, 404), 0.45, (255, 255, 255))
    for k, r in enumerate(receipts[-3:]):
        _text(p, f"{r['_t']:6.1f}s {r['zone_id']}: {r['from']} -> {r['to']} ({r['reason']})", (14, 426 + 18 * k),
              0.42, (200, 220, 255))
    return p


def no_signal(t: float) -> np.ndarray:
    img = np.full((480, 640, 3), 18, np.uint8)
    _text(img, "CAMERA OFFLINE", (200, 230), 0.9, (0, 0, 255), 2)
    _text(img, f"t = {t:.1f} s", (270, 265), 0.6)
    return img


def run(name: str, backend: str = "oracle", out: Path | None = None, video: bool = True, fps: float = 10.0,
        seed: int = 7, mqtt: str | None = None, speed: float = 2.0, show: bool = False,
        onnx: str | None = None, engine: str | None = None, qemu_zone: str | None = None,
        power_cut: tuple[float, float] | None = None) -> dict:
    sc = SCENARIOS[name]
    out = out or ROOT / "runs" / name
    out.mkdir(parents=True, exist_ok=True)
    if qemu_zone and not mqtt:
        mqtt = "localhost:1883"  # the emulated ESP32 reaches the host broker at 10.0.2.2
    world = World(sc, seed)
    epoch = time.time()
    clock = lambda: epoch + world.t  # noqa: E731  simulated wall clock

    records: list[dict] = []
    if mqtt:
        host, _, port = mqtt.partition(":")
        bus = MqttBus(host, int(port or 1883), client_id=f"simlab-{name}", queued=True)
        if not bus.wait_connected(10):
            raise SystemExit(f"MQTT broker {mqtt} not reachable")
        bus.subscribe(f"{PREFIX}/{SITE}/#", lambda tp, pl: None if "/sim/" in tp else records.append(
            {"t": round(world.t, 2), "topic": tp, "payload": pl}))
    else:
        bus = InprocBus()
        bus.tap.append(lambda tp, pl, retain: records.append({"t": round(world.t, 2), "topic": tp, "payload": pl}))

    model = ModelConfig(backend=backend, engine=engine or str(ROOT / "models" / "leaklatch_waterseg.engine"),
                        onnx=onnx or str(ROOT / "models" / "leaklatch_waterseg.onnx"))
    cfg = PipeConfig(site_id=SITE, topic_prefix=PREFIX, model=model, zones=world.zone_configs(),
                     evidence_dir=str(out / "evidence"), fps=fps)
    seg = load_segmenter(model.backend, model.input_size, model.engine, model.onnx)
    pipe = Pipeline(cfg, seg, bus)
    nodes = {z.id: (FirmwareNode(bus, world, z.id, SITE, PREFIX) if z.id == qemu_zone
                    else VirtualValveNode(bus, world, z.id, SITE, PREFIX, clock)) for z in ZONES}

    esp = None
    if qemu_zone:
        from .qemu import QemuEsp32

        esp = QemuEsp32(out)
        esp.start()
        fw = nodes[qemu_zone]
        deadline = time.time() + 90
        while not (fw.online and fw.fsm.state not in ("OFFLINE", "BOOTING")):
            if time.time() > deadline:
                esp.close()
                raise SystemExit(f"ESP32 in QEMU did not come online; see {esp.log_path}")
            fw.tick()
            bus.drain(timeout=0.2)
        log.info("ESP32 (QEMU) online: %s", fw.state_msg.get("state"))

    tall = qemu_zone is not None
    writer = VideoSink(out / "demo.mp4", fps * speed, (1280, 720 if tall else 480)) if video else None
    dt = 1.0 / fps
    commands = sorted(sc.commands)
    timeline: list[dict] = []
    receipts_seen: list[dict] = []
    lost = {z.id: 0.0 for z in ZONES}
    power_off = False
    t_wall = time.perf_counter()
    for step in range(int(round(sc.duration_s / dt))):
        world.step(dt)
        for zid in lost:
            lost[zid] += world.inflow_lpm(zid) * dt / 60.0
        if esp and power_cut:
            if not power_off and power_cut[0] <= world.t < power_cut[0] + power_cut[1] and esp.boots == 1:
                esp.stop()
                power_off = True
            elif power_off and world.t >= power_cut[0] + power_cut[1]:
                esp.start()
                power_off = False
        while commands and commands[0][0] <= world.t:
            _, zone, cmd = commands.pop(0)
            bus.publish(topic(PREFIX, SITE, zone, "cmd"),
                        {"schema": SCHEMA_COMMAND, "cmd": cmd, "by": "warden", "timestamp": iso_utc(clock())})
        bus.drain()
        if world.camera_ok:
            frame, gt = world.render()
            res = pipe.process(frame, clock(), {"gt_mask": gt})
            vis = pipe.overlay(frame, res) if video or show else None
        else:
            vis = no_signal(world.t) if video or show else None
        if mqtt:
            bus.drain(timeout=0.02)  # events take a broker round trip
        for node in nodes.values():
            node.tick()
        bus.drain()
        for node in nodes.values():
            for r in node.receipts:
                if "_t" not in r:
                    r["_t"] = round(world.t, 2)
                    receipts_seen.append(r)
        timeline.append({
            "t": round(world.t, 2),
            "zones": {z.id: {
                "true_area": round(world.true_area(z.id), 4),
                "seen_area": round(pipe.trackers[z.id].area, 4),
                "growth": round(pipe.trackers[z.id].growth, 4),
                "state": nodes[z.id].fsm.state,
                "valve_deg": round(world.valves[z.id].angle, 1),
                "limit": world.valves[z.id].limit_pressed,
                "wet": nodes[z.id]._wet,
                "inflow": round(world.inflow_lpm(z.id), 3),
            } for z in ZONES},
        })
        if vis is not None:
            frame_out = np.hstack([vis, draw_panel(world, nodes, sc, pipe, receipts_seen, world.t)])
            if tall:
                cap = caption_for(sc, world, nodes[qemu_zone], power_off, lost[qemu_zone])
                frame_out = np.vstack([frame_out, draw_console(
                    esp.tail(30), cap, f"ESP32 serial: real FirmGen firmware (ESP-IDF v5.5) running in QEMU "
                                       f"[{'POWER OFF' if power_off else f'power-on #{esp.boots}'}]")])
            if writer:
                writer.write(frame_out)
            if show:
                cv2.imshow("LeakLatch sim", frame_out)
                if cv2.waitKey(1) & 0xFF in (27, ord("q")):
                    break
        if esp:  # the firmware runs in real time: pace the world to the wall clock
            target = t_wall + (step + 1) * dt
            while (now := time.perf_counter()) < target:
                bus.drain(timeout=min(0.02, target - now))
    if writer:
        writer.close()
    if show:
        cv2.destroyAllWindows()
    if mqtt:
        time.sleep(0.5)
        bus.drain()
    if esp:
        esp.close()
    if mqtt:
        bus.close()
    elapsed = time.perf_counter() - t_wall

    # every message on the bus must satisfy its JSON schema
    invalid = []
    for r in records:
        if "schema" in r["payload"]:
            try:
                validate(r["payload"])
            except Exception as e:  # noqa: BLE001
                invalid.append({"topic": r["topic"], "error": str(e).splitlines()[0]})

    summary = summarize(sc, nodes, records, timeline, invalid, backend=seg.name, elapsed=elapsed)
    with open(out / "messages.jsonl", "w", encoding="utf-8") as f:
        for r in records:
            f.write(json.dumps(r) + "\n")
    (out / "timeline.json").write_text(json.dumps(timeline), encoding="utf-8")
    (out / "summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    report.write(out, sc, summary, timeline, records)
    return summary


def summarize(sc: Scenario, nodes: dict, records: list, timeline: list, invalid: list, backend: str,
              elapsed: float) -> dict:
    zones = {}
    checks = []
    for zid, node in nodes.items():
        states = [s["zones"][zid]["state"] for s in timeline]
        closed_at = next((s["t"] for s in timeline if s["zones"][zid]["state"] == "CLOSED"), None)
        detect_at = next((r["t"] for r in records if r["topic"].endswith(f"/{zid}/event")
                          and r["payload"].get("kind") == "detect"), None)
        latched_at = next((s["t"] for s in timeline if s["zones"][zid]["state"] in ("LATCHED", "FAULT")), None)
        leak_start = min((L.start_s for L in sc.leaks if L.zone == zid), default=None)
        zones[zid] = {
            "final_state": node.fsm.state, "final_reason": node.fsm.reason,
            "leak_start_s": leak_start, "first_detect_s": detect_at, "valve_closed_s": closed_at,
            "resolved_s": latched_at, "ever_closed": any(s in ("CLOSED", "VERIFYING", "LATCHED", "FAULT")
                                                         for s in states),
            "zone_lock_rejections": node.fsm.counter(1), "accepted_events": node.fsm.counter(0),
            "receipts": len(node.receipts),
            "max_true_area_m2": max(s["zones"][zid]["true_area"] for s in timeline),
            "water_lost_l": round(sum(s["zones"][zid]["inflow"] for s in timeline) / 60.0 * (
                timeline[1]["t"] - timeline[0]["t"]) if len(timeline) > 1 else 0.0, 2),
        }
        if zid in sc.expect:
            want = sc.expect[zid]
            checks.append({"check": f"{zid} ends {want[0]} ({want[1]})",
                           "ok": (node.fsm.state, node.fsm.reason) == want})
        if zid in sc.expect_never_closed:
            checks.append({"check": f"{zid} valve never closed", "ok": not zones[zid]["ever_closed"]})
    checks.append({"check": "all messages satisfy the JSON schemas", "ok": not invalid})
    return {"scenario": sc.name, "title": sc.title, "backend": backend, "duration_s": sc.duration_s,
            "wall_time_s": round(elapsed, 1), "messages": len(records), "invalid_messages": invalid[:5],
            "zones": zones, "checks": checks, "passed": all(c["ok"] for c in checks)}


def main() -> None:
    ap = argparse.ArgumentParser(description="LeakLatch closed-loop simulator")
    ap.add_argument("--scenario", choices=sorted(SCENARIOS), default="leak")
    ap.add_argument("--all", action="store_true", help="run every scenario")
    ap.add_argument("--backend", default="oracle", choices=["oracle", "onnxruntime", "tensorrt", "auto"])
    ap.add_argument("--onnx"), ap.add_argument("--engine")
    ap.add_argument("--mqtt", help="host:port of a real broker (default: in-process bus)")
    ap.add_argument("--no-video", action="store_true")
    ap.add_argument("--show", action="store_true")
    ap.add_argument("--speed", type=float, default=2.0, help="video playback speed-up")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--qemu-zone", choices=[z.id for z in ZONES],
                    help="run this zone's node as the real firmware in an emulated ESP32 (QEMU)")
    ap.add_argument("--power-cut", help="T,D: cut the emulated ESP32's power at T s for D s")
    args = ap.parse_args()
    cut = tuple(float(v) for v in args.power_cut.split(",")) if args.power_cut else None
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    names = sorted(SCENARIOS) if args.all else [args.scenario]
    results = []
    for name in names:
        out = (args.out / name) if (args.out and args.all) else args.out
        s = run(name, args.backend, out, video=not args.no_video, mqtt=args.mqtt, speed=args.speed,
                show=args.show, onnx=args.onnx, engine=args.engine, qemu_zone=args.qemu_zone, power_cut=cut)
        results.append(s)
        mark = "PASS" if s["passed"] else "FAIL"
        print(f"[{mark}] {name:12s} backend={s['backend']} msgs={s['messages']} wall={s['wall_time_s']}s")
        for c in s["checks"]:
            print(f"    {'ok ' if c['ok'] else 'BAD'} {c['check']}")
    if not all(r["passed"] for r in results):
        raise SystemExit(1)


if __name__ == "__main__":
    main()
