"""Virtual ESP32 valve node: same topics, same JSON and the same C state machine
as firmgen/, wired to the simulated valve, limit switch and wetness probe.
Message building mirrors firmgen/main/ll_msg.c field for field."""

from __future__ import annotations

import logging
from collections import deque
from typing import Callable

from pipegen.contract import SCHEMA_COMMAND, SCHEMA_EVENT, SCHEMA_RECEIPT, SCHEMA_STATE, iso_utc, topic

from . import fsm_native as F
from .world import World

log = logging.getLogger(__name__)

WET_ON_RAW, WET_OFF_RAW = 1800, 2300   # same defaults as Kconfig (active-low probe)
FW = "1.0.0-sim"


def _r4(x: float) -> float:
    return round(float(x) * 10000.0) / 10000.0


class VirtualValveNode:
    def __init__(self, bus, world: World, zone_id: str, site: str, prefix: str,
                 clock: Callable[[], float], boot_ms: int = 1500, **cfg_overrides) -> None:
        self.bus, self.world, self.zone = bus, world, zone_id
        self.clock = clock                      # returns the simulated epoch time (s)
        self._t0 = clock()
        self.boot_ms = boot_ms
        self.valve = world.valves[zone_id]
        self.fsm = F.NativeFsm(zone_id, self.now_ms(), **cfg_overrides)
        self.topic_state = topic(prefix, site, zone_id, "state")
        self.topic_receipt = topic(prefix, site, zone_id, "receipt")
        self.topic_cmd = topic(prefix, site, zone_id, "cmd")
        self._wet_buf: deque[int] = deque(maxlen=8)
        self._wet = False
        self.wet_raw = -1
        self.alarm = False
        self.receipts: list[dict] = []
        self.verdicts: list[tuple[float, str, str]] = []
        self._last_wet_ms = -10_000
        self._last_state_ms = 0
        bus.subscribe(f"{prefix}/{site}/zone/+/event", self._on_event)   # every zone: lock enforced in the FSM
        bus.subscribe(self.topic_cmd, self._on_command)
        self._flush(force_state=True)

    def now_ms(self) -> int:
        return int((self.clock() - self._t0) * 1000) + self.boot_ms

    # ---- inputs ---------------------------------------------------------------
    def _on_event(self, topic_: str, msg: dict) -> None:
        parts = topic_.split("/")
        ok = (msg.get("schema") == SCHEMA_EVENT and msg.get("kind") in F.KINDS and len(parts) >= 5
              and parts[-2] == msg.get("zone_id")
              and all(isinstance(msg.get(k), str) and msg[k] for k in ("event_id", "incident_id", "zone_id"))
              and all(isinstance(msg.get(k), (int, float)) for k in ("confidence", "pool_area", "growth_rate")))
        if ok:
            verdict = self.fsm.on_vision(msg["event_id"], msg["incident_id"], msg["zone_id"], F.KINDS[msg["kind"]],
                                         msg["confidence"], msg["pool_area"], msg["growth_rate"], self.now_ms())
        else:
            verdict = self.fsm.on_vision("", "", self.zone, 0, 0.0, 0.0, 0.0, self.now_ms())
        self.verdicts.append((self.clock(), msg.get("zone_id", "?"), verdict))
        self._flush()

    def _on_command(self, topic_: str, msg: dict) -> None:
        if msg.get("schema") != SCHEMA_COMMAND or msg.get("cmd") not in ("reset", "close"):
            log.warning("%s: malformed command ignored", self.zone)
            return
        self.fsm.on_command(F.CMD_RESET if msg["cmd"] == "reset" else F.CMD_CLOSE, self.now_ms())
        self._flush()

    def tick(self) -> None:
        """Called every simulator step (the firmware polls every 20 ms; the sim steps 100 ms)."""
        now = self.now_ms()
        self.fsm.on_limit(self.valve.limit_pressed, now)
        if now - self._last_wet_ms >= 200:
            self._last_wet_ms = now
            self._wet_buf.append(self.world.wetness_raw(self.zone))
            self.wet_raw = sum(self._wet_buf) // len(self._wet_buf)
            if not self._wet and self.wet_raw <= WET_ON_RAW:
                self._wet = True
            elif self._wet and self.wet_raw >= WET_OFF_RAW:
                self._wet = False
            self.fsm.on_wetness(self._wet, now)
        self.fsm.tick(now)
        self._flush(heartbeat=now - self._last_state_ms >= 30_000)

    # ---- outputs --------------------------------------------------------------
    def _flush(self, force_state: bool = False, heartbeat: bool = False) -> None:
        a = self.fsm.take_actions()
        if a & F.ACT_VALVE_CLOSE:
            self.valve.command(True)
        if a & F.ACT_VALVE_OPEN:
            self.valve.command(False)
        if a & F.ACT_ALARM_ON:
            self.alarm = True
        if a & F.ACT_ALARM_OFF:
            self.alarm = False
        if a & F.ACT_RECEIPT:
            for tr in self.fsm.pop_transitions():
                self._publish_receipt(tr)
        if force_state or heartbeat or a & F.ACT_PUBLISH_STATE:
            self._last_state_ms = self.now_ms()
            self.bus.publish(self.topic_state, self.state_message(), qos=1, retain=True)

    def state_message(self) -> dict:
        st = self.fsm.state
        return {
            "schema": SCHEMA_STATE, "zone_id": self.zone, "online": True, "state": st, "reason": self.fsm.reason,
            "valve": "closed" if st in ("CLOSED", "VERIFYING", "LATCHED", "FAULT") else "open",
            "limit_switch": self.valve.limit_pressed, "wet": self._wet, "wetness_raw": self.wet_raw,
            "incident_event_id": self.fsm.trigger_event_id, "uptime_ms": self.now_ms(),
            "timestamp": iso_utc(self.clock()), "fw": FW,
            "counters": {"accepted": self.fsm.counter(0), "zone_mismatch": self.fsm.counter(1),
                         "duplicate": self.fsm.counter(2), "rejected": self.fsm.counter(3)},
        }

    def _publish_receipt(self, tr: F.Transition) -> None:
        msg = {
            "schema": SCHEMA_RECEIPT, "zone_id": self.zone, "seq": tr.seq, "from": F.STATES[tr.from_],
            "to": F.STATES[tr.to], "reason": tr.reason.decode(), "trigger_event_id": tr.trigger_event_id.decode(),
            "last_event_id": tr.last_event_id.decode(), "uptime_ms": tr.t_ms, "timestamp": iso_utc(self.clock()),
            "evidence": {"confidence": _r4(tr.confidence), "pool_area": _r4(tr.pool_area),
                         "growth_rate": _r4(tr.growth_rate), "wet": bool(tr.wet), "wetness_raw": self.wet_raw,
                         "limit_switch": bool(tr.limit_switch)},
            "verification": {"mechanical": bool(tr.mech_verified), "mechanical_ms": tr.mech_verified_after_ms,
                             "hydraulic": bool(tr.hydro_verified), "growth_after_close": _r4(tr.growth_after_close),
                             "close_attempts": tr.close_attempts},
        }
        self.receipts.append(msg)
        log.info("%s #%d %s -> %s (%s)", self.zone, tr.seq, msg["from"], msg["to"], msg["reason"])
        self.bus.publish(self.topic_receipt, msg, qos=1)
