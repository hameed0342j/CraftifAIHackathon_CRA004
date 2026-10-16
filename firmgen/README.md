# FirmGen: ESP32 valve node (ESP-IDF v5.5)

| File | Role |
|---|---|
| `main/ll_fsm.c/.h` | zone-locked state machine (pure C99, host-tested, also used by the simulator) |
| `main/app_main.c` | control task: owns the FSM, polls the sensors, applies actions, publishes receipts |
| `main/ll_hw.c` | LEDC servo (50 Hz, released after travel), debounced limit switch, ADC1 wetness with hysteresis, alarm |
| `main/ll_net.c` | Wi-Fi STA with reconnect, SNTP, esp-mqtt with Last Will and outbox-queued QoS 1 |
| `main/ll_msg.c` | cJSON codec for the `/contracts` schemas |
| `main/ll_store.c` | NVS persistence of the state (a closed valve stays closed across reboots) |
| `test/test_fsm.c` | 122 host checks, 16 scenarios |

## Build and flash

```powershell
# Windows: install ESP-IDF v5.5 (https://docs.espressif.com/projects/esp-idf/en/v5.5/esp32/get-started/)
. $env:IDF_PATH\export.ps1
cd firmgen
idf.py menuconfig        # LeakLatch valve node: Wi-Fi, broker URI, site/zone id, pins, thresholds
idf.py build
idf.py -p COM5 flash monitor
```

```bash
# Linux / macOS
. $IDF_PATH/export.sh && cd firmgen && idf.py menuconfig build flash monitor
```

The image is about 860 KB (16% of the 1 MB app partition free) with TLS-capable MQTT.

## Host tests (no ESP32 needed)

```bash
python tools/build_native.py      # builds build/native/ll_fsm.{dll,so} and runs test_fsm (gcc, clang or `pip install ziglang`)
```

## Bench test without a camera

```bash
python tools/leaklatch_cli.py watch                  # terminal 1
python tools/leaklatch_cli.py fake-event bathroom-1  # terminal 2, then wet the probe with a damp cloth
python tools/leaklatch_cli.py reset bathroom-1       # reopen
```

Expected receipts: `IDLE→SUSPECT (vision_event)`, `SUSPECT→CONFIRMING (local_wet)`, `CONFIRMING→CLOSED (confirmed)`,
`CLOSED→VERIFYING (limit_switch)`, then `LATCHED (mechanical_only)` after 60 s. With a running PipeGen
camera, the last step is `LATCHED (verified)`.
