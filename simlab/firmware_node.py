"""The wiring between the simulated bathroom and the ESP32 running the real FirmGen
image in QEMU. Virtual pins travel over MQTT (firmgen/main/ll_hw_sim.c):

    world -> leaklatch/<site>/sim/<zone>/pins     {"limit": bool, "wet_raw": int}   (every sim step)
    ESP32 -> leaklatch/<site>/sim/<zone>/outputs  {"servo_deg": int, "alarm": bool} (retained)

The node's decisions come only from the firmware: this class just mirrors its
published state and receipts so the simulator panel and reports can show them.
"""

from __future__ import annotations

from pipegen.contract import topic

COUNTERS = ["accepted", "zone_mismatch", "duplicate", "rejected"]


class _RemoteFsm:
    def __init__(self, node: "FirmwareNode") -> None:
        self._n = node

    @property
    def state(self) -> str:
        m = self._n.state_msg
        return m.get("state", "BOOTING") if self._n.online else "OFFLINE"

    @property
    def reason(self) -> str:
        return self._n.state_msg.get("reason", "") if self._n.online else "power off / no MQTT"

    def counter(self, which: int) -> int:
        return int(self._n.state_msg.get("counters", {}).get(COUNTERS[which], 0))


class FirmwareNode:
    kind = "ESP32 firmware in QEMU"

    def __init__(self, bus, world, zone_id: str, site: str, prefix: str) -> None:
        self.bus, self.world, self.zone = bus, world, zone_id
        self.valve = world.valves[zone_id]
        self.pins_topic = f"{prefix}/{site}/sim/{zone_id}/pins"
        self.state_msg: dict = {}
        self.online = False
        self.receipts: list[dict] = []
        self.alarm = False
        self.servo_deg = 0
        self._wet = False
        self.wet_raw = -1
        self.fsm = _RemoteFsm(self)
        bus.subscribe(f"{prefix}/{site}/sim/{zone_id}/outputs", self._on_outputs)
        bus.subscribe(topic(prefix, site, zone_id, "state"), self._on_state)
        bus.subscribe(topic(prefix, site, zone_id, "receipt"), self._on_receipt)

    def _on_outputs(self, _t: str, m: dict) -> None:
        self.servo_deg = int(m.get("servo_deg", 0))
        self.valve.command(self.servo_deg >= 45)
        self.alarm = bool(m.get("alarm", False))

    def _on_state(self, _t: str, m: dict) -> None:
        self.state_msg = m
        self.online = bool(m.get("online"))
        if self.online:
            self._wet = bool(m.get("wet"))
            self.wet_raw = int(m.get("wetness_raw", -1))

    def _on_receipt(self, _t: str, m: dict) -> None:
        self.receipts.append(dict(m))  # own copy: the simulator annotates it for the video

    def tick(self) -> None:
        """Drive the input pins from the physics, like the real wiring would."""
        self.bus.publish(self.pins_topic, {"limit": self.valve.limit_pressed,
                                           "wet_raw": self.world.wetness_raw(self.zone)}, qos=0)
