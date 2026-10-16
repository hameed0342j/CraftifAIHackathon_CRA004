# MQTT contract

The JSON Schemas in [`/contracts`](../contracts) are the source of truth. PipeGen, FirmGen and the
simulator are all tested against them.

| Topic | Direction | QoS | Retained | Schema |
|---|---|---|---|---|
| `leaklatch/{site}/zone/{zone}/event` | PipeGen → nodes | 1 | no | [`leak_event`](../contracts/leak_event.schema.json) |
| `leaklatch/{site}/zone/{zone}/state` | node → all | 1 | **yes** (+ Last Will `online:false`) | [`device_state`](../contracts/device_state.schema.json) |
| `leaklatch/{site}/zone/{zone}/receipt` | node → audit | 1 | no | [`receipt`](../contracts/receipt.schema.json) |
| `leaklatch/{site}/zone/{zone}/cmd` | warden → node | 1 | no | [`command`](../contracts/command.schema.json) |
| `leaklatch/{site}/pipegen/health` | PipeGen → all | 1 | yes | fps, backend, model hash |

## leak_event

```json
{
  "schema": "leaklatch/leak_event/v1",
  "event_id": "5f0c1b8e4d6a4f0f9a3b2c1d0e9f8a7b",
  "incident_id": "a1b2c3d4e5f60718293a4b5c6d7e8f90",
  "kind": "update",
  "site_id": "pg-demo-01",
  "zone_id": "bathroom-1",
  "timestamp": "2026-10-16T17:42:03.512Z",
  "seq": 41,
  "confidence": 0.93,
  "pool_area": 0.184,
  "growth_rate": 0.412,
  "evidence": {
    "backend": "tensorrt-11.4.0.106",
    "model": "leaklatch_waterseg.engine",
    "model_sha256": "…",
    "snapshot": "evidence/20261016/a1b2c3d4e5f6_000041_update.jpg",
    "snapshot_sha256": "…",
    "window_s": 10.0, "persistence": 1.0, "frames": 52
  }
}
```

* `event_id`: unique per message; nodes de-duplicate on it (a 16-entry ring).
* `incident_id`: groups `detect` → `update`… → `clear` for one pool. Nodes use it to stay quiet about a pool the warden already acknowledged.
* `pool_area`: m², perspective-corrected inside the zone polygon.
* `growth_rate`: m²/min, least-squares slope over `window_s`. Negative means shrinking (mopping, draining).

## receipt (one per state transition)

```json
{
  "schema": "leaklatch/receipt/v1", "zone_id": "bathroom-1", "seq": 5,
  "from": "VERIFYING", "to": "LATCHED", "reason": "verified",
  "trigger_event_id": "5f0c1b8e…", "last_event_id": "c0ffee12…", "uptime_ms": 412345,
  "timestamp": "2026-10-16T17:42:31.004Z",
  "evidence": {"confidence": 0.95, "pool_area": 0.2, "growth_rate": 0.003, "wet": true,
               "wetness_raw": 1190, "limit_switch": true},
  "verification": {"mechanical": true, "mechanical_ms": 760, "hydraulic": true,
                   "growth_after_close": 0.003, "close_attempts": 1}
}
```

Transition reasons: `vision_event`, `local_wet`, `confirmed`, `vision_only_override`, `local_failsafe`,
`operator_close`, `limit_switch`, `travel_elapsed`, `verified`, `mechanical_only`, `valve_not_closed`,
`leak_persists`, `limit_released`, `vision_unconfirmed`, `wet_lost`, `vision_cleared`, `confirm_timeout`,
`operator_reset`, `restored_after_reboot`.

## Security

* Use `deploy/mosquitto.conf` and `deploy/leaklatch.acl`: passwords, no anonymous access, and per-role ACLs.
  The camera can only write `event`, a node only its own `state`/`receipt`, and only `warden` can write `cmd`.
* Nodes check the event's topic zone against its payload `zone_id`, the schema id, and field sizes.
  Malformed and foreign-zone events are counted and published in `state.counters`.
* For TLS, set `LL_MQTT_URI` to `mqtts://…` (TLS transport is enabled in `sdkconfig.defaults`) and set
  `mqtt.tls: true` in PipeGen.
