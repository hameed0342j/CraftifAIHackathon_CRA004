# Hardware: one valve node per zone

## Bill of materials (per zone)

Prices are indicative Indian retail ranges (Oct 2026). Check local vendors (Robu, Robocraze, local hardware stores).

| Part | Suggested | Approx. ₹ | Notes |
|---|---|---|---|
| MCU | ESP32-DevKitC (WROOM-32) | 400–550 | any ESP32 with an ADC1 pin free |
| Actuator | MG996R metal-gear servo (DS3218 20 kg·cm for stiff 3/4" valves) | 300–900 | powered from 5–6 V, **not** the ESP32's 3V3 |
| Valve | 1/2" brass quarter-turn ball valve | 200–400 | the lever is turned by the servo through a 3D-printed or aluminium coupler |
| Limit switch | KW11-3Z roller micro switch | 20–40 | mounted so the coupler presses it only at the fully closed stop |
| Wetness probe | FC-37/YL-83 resistive module (or capacitive probe) | 50–120 | AO to ADC1; place at the floor's low point beneath the joint |
| Power | 5 V 3 A adapter + 1000 µF capacitor across servo supply | 250–350 | servo stall current ~2.5 A |
| Indicator | LED/buzzer (GPIO 2) | 20 | on-board LED works for the demo |
| Enclosure | IP65 junction box, glands | 200–300 | keep electronics above floor level |
| **Total per zone** | | **≈ 1,500–2,500** | |

Shared per site: an NVIDIA Jetson (JetPack 6) or any NVIDIA GPU machine, one USB/CSI/RTSP camera per area, and a Wi-Fi router.

## Wiring (defaults in `idf.py menuconfig → LeakLatch valve node`)

| ESP32 pin | Connects to | Kconfig |
|---|---|---|
| GPIO 18 | servo signal (orange) | `LL_SERVO_GPIO` |
| GND | servo GND (brown), supply GND, switch COM, probe GND | — |
| GPIO 27 | limit switch NO (COM to GND; internal pull-up, pressed = LOW) | `LL_LIMIT_GPIO`, `LL_LIMIT_ACTIVE_LOW` |
| GPIO 34 (ADC1_CH6) | wetness module AO | `LL_WET_GPIO` |
| 3V3 | wetness module VCC | — |
| GPIO 2 | alarm LED / buzzer (+) | `LL_ALARM_GPIO` |
| — | servo V+ (red) to the 5 V supply, **not** the ESP32 | — |

```
 5V PSU (+) ──────────────┬──────────── servo red
                          ╪ 1000 µF
 5V PSU (−) ──┬───────────┴──────────── servo brown
              └─ ESP32 GND ─┬─ limit switch COM
                            └─ probe GND
 ESP32 GPIO18 ─────────────────────────── servo orange (signal)
 ESP32 GPIO27 ─────────────────────────── limit switch NO
 ESP32 GPIO34 ─────────────────────────── probe AO      ESP32 3V3 ── probe VCC
```

## Calibration

1. **Servo angles.** Set `LL_SERVO_OPEN_DEG`/`LL_SERVO_CLOSED_DEG` so the valve lever reaches both stops.
   Adjust the limit-switch bracket so it clicks only in the last ~2° before closed.
2. **Wetness thresholds.** Watch `wetness_raw` in the state topic (`tools/leaklatch_cli.py watch`). Dry is
   usually 2800–3500 and wet 900–1600 on a 12-bit reading. Set `LL_WET_ON_RAW` and `LL_WET_OFF_RAW` with a
   gap of a few hundred for hysteresis.
3. **Camera zones.** Put four tape marks on each zone's floor, read their pixel positions in a frame, and
   measure their positions in metres. Enter both in `configs/site.yaml` (`floor_image_points` /
   `floor_metric_points`).

## Placement rules

* The probe goes where water collects first: beneath the joint, at the floor's low point or slope toward the drain.
  It must not go in the shower area, which is wet every morning.
* One valve per zone, on the branch feeding that zone (wash-basin line, geyser line, toilet cistern line).
  If the water source is not behind the valve, LeakLatch reports `FAULT leak_persists` instead of
  pretending it fixed the leak.
* The camera should look down at 30–60°. Do not aim it at windows: strong glare on wet tiles lowers confidence.
