"""Warden / operator console over MQTT.

    python tools/leaklatch_cli.py watch                      # live states, events and receipts
    python tools/leaklatch_cli.py reset bathroom-1           # leak fixed: reopen the valve
    python tools/leaklatch_cli.py close corridor-2           # manual shut-off
    python tools/leaklatch_cli.py fake-event bathroom-1      # inject a leak event (bench test without a camera)
"""

from __future__ import annotations

import argparse
import sys
import time
import uuid
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from pipegen.contract import SCHEMA_COMMAND, SCHEMA_EVENT, iso_utc, topic  # noqa: E402
from pipegen.transport import MqttBus  # noqa: E402

COLOUR = {"IDLE": 32, "SUSPECT": 33, "CONFIRMING": 33, "CLOSED": 31, "VERIFYING": 31, "LATCHED": 34, "FAULT": 35}


def c(state: str) -> str:
    return f"\033[{COLOUR.get(state, 37)}m{state}\033[0m"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("action", choices=["watch", "reset", "close", "fake-event"])
    ap.add_argument("zone", nargs="?")
    ap.add_argument("--host", default="localhost")
    ap.add_argument("--port", type=int, default=1883)
    ap.add_argument("--site", default="pg-demo-01")
    ap.add_argument("--prefix", default="leaklatch")
    ap.add_argument("--username"), ap.add_argument("--password")
    args = ap.parse_args()
    bus = MqttBus(args.host, args.port, args.username, args.password, client_id=f"cli-{uuid.uuid4().hex[:6]}")
    if not bus.wait_connected(10):
        sys.exit(f"cannot reach MQTT broker {args.host}:{args.port}")

    if args.action in ("reset", "close"):
        if not args.zone:
            sys.exit("zone required")
        bus.publish(topic(args.prefix, args.site, args.zone, "cmd"),
                    {"schema": SCHEMA_COMMAND, "cmd": args.action, "by": "cli", "timestamp": iso_utc(time.time())})
        time.sleep(0.5)
        print(f"sent {args.action} to {args.zone}")
        return
    if args.action == "fake-event":
        if not args.zone:
            sys.exit("zone required")
        inc = uuid.uuid4().hex
        for i, kind in enumerate(["detect", "update", "update", "update", "update"]):
            bus.publish(topic(args.prefix, args.site, args.zone, "event"), {
                "schema": SCHEMA_EVENT, "event_id": uuid.uuid4().hex, "incident_id": inc, "kind": kind,
                "zone_id": args.zone, "timestamp": iso_utc(time.time()), "confidence": 0.9,
                "pool_area": round(0.05 + 0.02 * i, 3), "growth_rate": 0.3})
            print(f"sent {kind} event; wet the probe now to see the valve close")
            time.sleep(2)
        return

    base = f"{args.prefix}/{args.site}/zone/+"

    def on_state(t, m):
        if not m.get("online", True):
            print(f"{time.strftime('%H:%M:%S')} {m['zone_id']:12s} OFFLINE")
            return
        print(f"{time.strftime('%H:%M:%S')} {m['zone_id']:12s} {c(m['state']):>22s} {m['reason']:22s} "
              f"valve={m['valve']:6s} limit={'ON ' if m['limit_switch'] else 'off'} "
              f"wet={'YES' if m['wet'] else 'no '} raw={m['wetness_raw']}")

    def on_event(t, m):
        print(f"{time.strftime('%H:%M:%S')} {m['zone_id']:12s} vision {m['kind']:6s} area={m['pool_area']:.3f}m2 "
              f"growth={m['growth_rate']:+.3f}m2/min conf={m['confidence']:.2f}")

    def on_receipt(t, m):
        v = m["verification"]
        print(f"{time.strftime('%H:%M:%S')} {m['zone_id']:12s} RECEIPT #{m['seq']} {c(m['from'])} -> {c(m['to'])} "
              f"({m['reason']}) trigger={m['trigger_event_id'][:8]} mech={v['mechanical']} hydro={v['hydraulic']}")

    bus.subscribe(f"{base}/state", on_state)
    bus.subscribe(f"{base}/event", on_event)
    bus.subscribe(f"{base}/receipt", on_receipt)
    print(f"watching {args.prefix}/{args.site} on {args.host}:{args.port} (Ctrl+C to stop)")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        bus.close()


if __name__ == "__main__":
    main()
