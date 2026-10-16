# FirmGen: ESP32 valve node (ESP-IDF v5.5)

| File | Role |
|---|---|
| `main/ll_fsm.c/.h` | zone-locked state machine (pure C99, host-tested, also used by the simulator) |
| `main/app_main.c` | control task: owns the FSM, polls the sensors, applies actions, publishes receipts |
| `main/ll_hw.c` | LEDC servo (50 Hz, released after travel), debounced limit switch, ADC1 wetness with hysteresis, alarm |
| `main/ll_hw_sim.c` | QEMU builds only: the same API over MQTT virtual pins |
| `main/ll_net.c` | Wi-Fi STA with reconnect, SNTP, esp-mqtt with Last Will and outbox-queued QoS 1 |
| `main/ll_msg.c` | cJSON codec for the `/contracts` schemas |
| `main/ll_store.c` | NVS persistence of the state (a closed valve stays closed across reboots) |
| `test/test_fsm.c` | 128 host checks, 17 scenarios |

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

## Synthetic flash: run the firmware in QEMU (no ESP32 needed)

`sdkconfig.qemu` builds the same application for Espressif's QEMU ESP32. Because QEMU has no Wi-Fi radio,
ADC, LEDC or servo, `CONFIG_LL_TARGET_QEMU` swaps in two pieces:

* **Network:** the emulated OpenCores Ethernet MAC replaces Wi-Fi (`ll_net.c`). The host broker is `10.0.2.2:1883`.
* **I/O:** `ll_hw_sim.c` replaces `ll_hw.c`. The pins become MQTT messages driven by the simulator's physics:
  `leaklatch/<site>/sim/<zone>/pins` `{"limit":bool,"wet_raw":int}` in, and
  `…/outputs` `{"servo_deg":int,"alarm":bool}` out.

The state machine, control task, NVS persistence, MQTT client and JSON codec are unchanged.

```powershell
python $env:IDF_PATH\tools\idf_tools.py install qemu-xtensa          # once
idf.py -B build_qemu -D SDKCONFIG=build_qemu/sdkconfig -D "SDKCONFIG_DEFAULTS=sdkconfig.defaults;sdkconfig.qemu" build
cd build_qemu; python -m esptool --chip esp32 merge_bin --output qemu_flash_pristine.bin --fill-flash-size 4MB "@flash_args"
# from the repo root, with a broker on localhost:1883:
python -m simlab.run --scenario leak --backend tensorrt --qemu-zone bathroom-1 --power-cut 58,5 --out runs/qemu-leak
```

`simlab/qemu.py` boots the image with a fresh copy of flash, and NVS survives a "power cut" (QEMU killed and
restarted). The serial output is saved to `runs/qemu-leak/esp32_serial.log` and shown live in the video.

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
