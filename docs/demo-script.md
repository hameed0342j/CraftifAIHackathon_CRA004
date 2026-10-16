# Demo script (3 minutes)

## 0:00 Problem (20 s)
"A PG warden in Bengaluru finds out about a leak when the tenant below complains. A burst flexible hose wastes
about 1–2 litres a minute and soaks the floor and wiring. Nobody watches the bathroom at 3 am."

## 0:20 What LeakLatch does (20 s)
Show the architecture diagram (README). "A camera sees water pooling and measures how fast it grows. A ₹2,000
ESP32 node next to the valve double-checks with a floor probe, shuts that zone's water, proves the valve
moved with a limit switch, and proves the leak stopped with the camera."

## 0:40 Live closed loop (90 s): `runs/leak/demo.mp4`, or real hardware
1. Leak starts: the pool grows on the left of the camera; the panel shows inflow 1.5 L/min.
2. PipeGen draws the mask; the zone overlay turns amber (**SUSPECT**). Point out area (m²) and growth (m²/min).
3. Water reaches the probe: **CONFIRMING**, then **CLOSED**; the servo turns 90° and the limit-switch LED lights (**VERIFYING**).
4. The growth rate falls to ~0: **LATCHED · verified**. Read out the receipt: trigger event id, 760 ms to the
   limit switch, growth after close +0.00 m²/min.
5. The warden presses reset after the fix; the valve reopens and the leftover puddle does not re-trigger.

## 2:10 It doesn't cry wolf (30 s): `runs/mop`, `runs/zone-lock`, `runs/upstream`, `runs/stuck-valve`
* Mopping a spill: the camera sees water, the probe stays dry, the pool shrinks, so the valve never moves.
* Corridor leak: the bathroom node rejects 50+ events for the wrong zone.
* Overhead-tank overflow: the valve closes but the pool keeps growing, so `FAULT leak_persists` ("look elsewhere").
* Jammed valve: no limit switch, one retry, then `FAULT valve_not_closed` and the alarm.

## 2:40 Engineering proof (20 s)
* `models/trt_report.json`: TensorRT FP16 engine, latency and parity against ONNX Runtime.
* `firmgen`: ESP-IDF v5.5 build, 122 host checks of the same state machine the simulator runs.
* Every MQTT message in every run is validated against the JSON Schemas.
