# CraftifAI Physical AI Hackathon: LeakLatch submission

**LeakLatch**: a zone-locked evidence-to-action chain that shuts off water leaks in PGs and hostels, and proves it did.

**Participant:** MUHAMMED AL HAMEED M · participant ID **CRA004** · repository https://github.com/hameed0342j/LeakLatch

## Requirement → evidence

### Track A: PipeGen (edge vision)
| Requirement | Where | Evidence |
|---|---|---|
| Detect water pooling from a camera | `pipegen/backends.py`, `pipegen/pipeline.py`, `models/leaklatch_waterseg.onnx` | `models/eval_metrics.json`: IoU 0.71 real / 0.91 synthetic, image P/R ≥ 0.97 |
| **Compile a model to TensorRT** | `pipegen/train/build_trt.py` | `models/trt_report.json`: TensorRT 11.4 FP16 engine, 1.40 ms p50, 0.997 mask agreement with ONNX |
| JSON over MQTT with `event_id, zone_id, timestamp, confidence, pool_area, growth_rate` | `contracts/leak_event.schema.json`, `pipegen/pipeline.py::_publish` | every simulator run validates every message (`runs/*/summary.json`) |
| pool_area in real units | `pipegen/zones.py` (per-pixel floor area from a homography) | `tests/test_pipegen.py::test_zone_area_is_perspective_correct` |
| growth_rate | `pipegen/tracker.py` (least-squares slope, m²/min) | `tests/test_pipegen.py::test_tracker_detect_growth_clear` |

### Track B: FirmGen (ESP32, ESP-IDF v5.5)
| Requirement | Where | Evidence |
|---|---|---|
| ESP-IDF v5.5 firmware | `firmgen/` | `idf.py build` passes (ESP-IDF v5.5, ESP32, 860 KB image); CI job `firmware` |
| Runs on an ESP32 (emulated) | `firmgen/sdkconfig.qemu`, `simlab/qemu.py` | boots in Espressif QEMU; [serial log](docs/sample-runs/qemu-leak/esp32_serial.log) of a full incident and a power cut |
| Subscribe to MQTT | `firmgen/main/ll_net.c`, `app_main.c` | subscribes `leaklatch/{site}/zone/+/event` and `…/{zone}/cmd` |
| Read the local wetness sensor | `firmgen/main/ll_hw.c` | ADC1 oneshot, 8-sample mean, hysteresis |
| Close the servo valve | `ll_hw.c::ll_valve_command` | LEDC 50 Hz, released after travel |
| Verify closure with a limit switch | `ll_fsm.c::verify` | VERIFYING needs the switch; one retry, then `FAULT valve_not_closed` |
| State machine IDLE → SUSPECT → CONFIRMING → CLOSED → VERIFYING | `firmgen/main/ll_fsm.c` | `firmgen/test/test_fsm.c`: 128 checks, 17 scenarios (plus LATCHED and FAULT outcomes) |

### Closed-loop bonus
| Requirement | Evidence |
|---|---|
| A perception event drives a physical action | receipt chain `trigger_event_id` → `CLOSED` (`runs/leak/report.html`) |
| Post-action verification proves the loop closed | **two independent proofs**: limit switch (mechanical) and camera growth → 0 (hydraulic), `VERIFYING → LATCHED (verified)` |
| …and catches when it did not | `upstream` → `FAULT leak_persists`; `stuck-valve` → `FAULT valve_not_closed` |

## Reproduce in 5 minutes (no hardware)

```bash
python -m venv .venv && .venv/Scripts/pip install -e ".[dev]"   # Linux/macOS: .venv/bin/pip
python tools/build_native.py                                    # firmware state machine: 122 host checks
python -m pytest -q                                             # PipeGen + closed-loop scenarios
python -m simlab.run --all --backend onnxruntime                # 6 scenarios with the real model -> runs/*/report.html, demo.mp4
```

## What is real and what is simulated

* **Real:** the trained model and its TensorRT engine, the PipeGen pipeline, the MQTT contract, the ESP-IDF
  firmware (compiles for ESP32), and the state machine. The simulator links the same C object the ESP32 runs.
* **Emulated:** the ESP32 itself, for the demo. The production firmware runs in Espressif QEMU with Ethernet
  instead of Wi-Fi and virtual pins instead of GPIO/ADC/LEDC
  ([demo video](docs/media/leaklatch_demo.mp4)).
* **Simulated:** the bathroom (rendered floor, physics of the pool, servo, limit switch, probe).
* **Not yet validated:** the firmware on a physical ESP32 with servo, switch and probe; the model on footage from
  a real hostel floor. See "Before you submit".

## Relationship to the CraftifAI PipeGen tool

This repository's `pipegen/` package is a hand-written implementation of the Track A requirements: a TensorRT
compile, and JSON over MQTT with `event_id, zone_id, timestamp, confidence, pool_area, growth_rate`. It was
**not generated with CraftifAI's PipeGen tool**, which was not installed on the Windows machine this was built on.
The model and a test clip are packaged so the pipeline can be rebuilt in PipeGen on a supported machine
(an x86-64 Linux PC with an NVIDIA GPU, or a Jetson):

| PipeGen input | Use |
|---|---|
| Model source: *Local, my own model file* | `models/leaklatch_waterseg.onnx` (opset 17), see [models/MODEL_CARD.md](models/MODEL_CARD.md) |
| Model input | `image`: float32 `1×3×320×320`, RGB, ImageNet normalisation (mean 0.485/0.456/0.406, std 0.229/0.224/0.225) |
| Model output | `logits`: float32 `1×1×320×320`; water = sigmoid(logit) ≥ 0.5 |
| Video input: *My own video* | [docs/media/sample_input.mp4](docs/media/sample_input.mp4): 640×480, 10 fps, 60 s raw camera feed, leak → valve shut at 20 s (`tools/export_input_video.py`) |
| Post-processing to reproduce | per-zone area via floor homography and growth rate via a 10 s least-squares slope (`pipegen/zones.py`, `pipegen/tracker.py`), then publish `contracts/leak_event.schema.json` over MQTT |

## Before you submit (team checklist)

- [ ] Flash `firmgen` on the ESP32 and wire it per `docs/hardware.md`. Run the bench test in `firmgen/README.md`.
- [ ] Record 300–800 frames of your own floor (wet and dry, mopping, reflections), label them with box prompts
      (SAM 2 is a good fit), add them as `data/<name>/{images,masks}`, and retrain:
      `python -m pipegen.train.train_seg`.
- [ ] Build the engine **on the Jetson**: `python -m pipegen.train.build_trt` (or `trtexec … --fp16`) and commit `models/trt_report.json`.
- [x] Demo video with the real firmware in an emulated ESP32: `docs/media/leaklatch_demo.mp4`.
- [ ] Optionally re-record on real hardware following `docs/demo-script.md`.
- [x] Participant details (above). Pushed to GitHub; CI builds the firmware and runs every test.
- [ ] If PipeGen is available on a supported machine: import `models/leaklatch_waterseg.onnx` with
      `docs/media/sample_input.mp4` as described above, and answer the PipeGen feedback form from that run.
