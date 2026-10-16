# LeakLatch — Open-Source Asset Scan (verified 2026-10-16)

**Method.** Metadata was pulled from each platform's own API wherever one exists: GitHub REST/search, Zenodo `/api/records`, arXiv `export.arxiv.org`, and the Hugging Face Hub connector. Four files were downloaded and inspected locally (see §0). Roboflow Universe blocks automated fetches with a Cloudflare 403, so its details come from search-engine snippets and are marked as such. Kaggle pages render client-side; only one was rendered before browser checks stopped. Star counts and dates are as of 2026-10-16.

Scores are composite **Relevance 1–5** for LeakLatch. The Top 5 and Top 3 get a full six-dimension breakdown.

---

## 0. Files you downloaded (inspected, not executed)

| File | What it is | Findings |
|---|---|---|
| `archive (3).zip` (Kaggle) | **Stagnant Water & Wet Surface** — a Kaggle mirror of Mendeley [y6zyrnxbfm](https://data.mendeley.com/datasets/y6zyrnxbfm/4) (Patil & Bhutad, *Data in Brief* 2021, DOI 10.1016/j.dib.2021.107752, **CC BY 4.0** at source) | 2,000 JPEGs at 256×256 with YOLO bbox labels. Classes: `water` (19,562 boxes) and `wet surface` (11,802). About **15.7 boxes per image**; median water box is 1.2% of the frame. **167 exact-duplicate copies** (only 1,833 unique images) and 2 empty label files. The scenes are outdoor Indian roads, soil and paving. Each puddle is covered by many overlapping fragment boxes, and some "wet surface" boxes land on dry ground (e.g. `image406` is a dry crack). Mendeley v4 has 1,976 images; this mirror matches the older 2,000-image v1/v2. |
| `water-controller-master.zip` | [tomekceszke/water-controller](https://github.com/tomekceszke/water-controller) — ★1, pushed 2026-10-15, **MIT** | ESP32 anti-flood valve on **ESP-IDF 5.4.2**. Tiered fail-safe shutoff: Tier 0 is hard-coded at 60 min; Tier 1 runs in its own core-1 task with no network, no allocation and no queue waits. Valve state lives in NVS and survives reboots and OTA. Telemetry goes over MQTT QoS 1. Pure-C rule modules have host unit tests plus a 37-check hardware test. The actuator has **no position feedback**, so a failed close is caught by "flow continues >15 s after the close command". |
| `leak-detection-thesis-main.zip` | [Kether180/leak-detection-thesis](https://github.com/Kether180/leak-detection-thesis) — ★1, **no license** | ResNet50 3-class classifier (oil / water / no-leak) with Stable Diffusion 2.1 synthetic data. Accuracy: real-only 97.5%, synthetic-only 47.5%, hybrid 99.4%, on a small test set (158–263 images). `leak_detector_best.pt` is a **133-byte Git-LFS pointer, not weights**. The README says data and weights are available on request. |
| `SingleImageWaterHazardDetectionWithRAU-master.zip` | [Cow911/SingleImageWaterHazardDetectionWithRAU](https://github.com/Cow911/SingleImageWaterHazardDetectionWithRAU) — ★56, last push 2020, no license | ECCV 2018 Puddle-1000 code (TF1 FCN, "work in progress") plus split lists: 802 train / 183 test. **The dataset link (CloudStor) is dead.** A re-annotated copy is linked from [Lyu-Dakang/AGSENet](https://github.com/Lyu-Dakang/AGSENet) via Quark Pan. |

---

## 1. GitHub (20 query variants via the search API; 169 unique repos triaged)

Zero-hit queries: `"zone-based water detection"` and `"limit switch valve verification"`. `"TensorRT water detection"` returned one hit, and it was irrelevant (an underwater robot).

### 1a. Vision / PipeGen

| Asset | URL | Type | Stars / last push | License | Rel. | Notes |
|---|---|---|---|---|---|---|
| Water_leak_detection_using_Instance_Segmentation_with_YOLO | https://github.com/huynhthanhphong231004IT/Water_leak_detection_using_Instance_Segmentation_with_YOLO | repo | ★0 / 2026-09-23 | none | 4 | YOLO **instance segmentation** with Euler integration of mask area over time, giving a leak-volume estimate. That is essentially LeakLatch's `pool_area` / `growth_rate` math. Its data is Kaggle `reorioll/leakwater-data` (see §2). Reuse the idea, not the code. |
| krishailab/water-leak | https://github.com/krishailab/water-leak | repo / YOLOv8s | ★0 / 2025-10-06 | **none** | 3 | One class. Trained on Roboflow `hindi-data-set/leak-6xwrk-ryq53` (2,445 images). P 80.1, R 67.5, mAP50 73.5, mAP50-95 48.9. Retrain from the CC BY source rather than reuse it. |
| Lyu-Dakang/AGSENet | https://github.com/Lyu-Dakang/AGSENet | repo + data links | ★9 / 2024-11-26 | none | 3 | Road-ponding segmentation (arXiv 2410.16999). Links the **re-annotated Puddle-1000** plus Foggy and Night variants on Quark Pan with access codes. Outdoor only. |
| Kether180/leak-detection-thesis | https://github.com/Kether180/leak-detection-thesis | repo | ★1 / 2025-11-30 | none | 3 | Synthetic-plus-real hybrid recipe (see §0). No weights. |
| Cow911/SingleImageWaterHazardDetectionWithRAU | https://github.com/Cow911/SingleImageWaterHazardDetectionWithRAU | repo | ★56 / 2020-08-28 | none | 2 | Reflection-attention idea is useful for glossy tiles. The code is TF1 and the data link is dead. |
| Qunmasj-Vision-Studio/water_spill_detection411 | https://github.com/Qunmasj-Vision-Studio/water_spill_detection411 | repo + data link | ★0 / 2024-12-25 | none | 2 | 2,400-image segmentation set, class `water`, including some indoor scenes. Data is on kdocs.cn and there are no weights. Provenance is unclear. |
| LeonardoCerv/flowing-vision | https://github.com/LeonardoCerv/flowing-vision | repo | ★0 / 2025-08-04 | MIT (README) | 2 | Hackathon YOLOv5 + OpenVINO trained on 100 images. Targets Intel CPUs, not Jetson. |
| uma26madasu/roboflow-water-leak-detection | https://github.com/uma26madasu/roboflow-water-leak-detection | repo | ★1 / 2025-09-13 | MIT | 2 | Roboflow-based leak detection ("enterprise integration"); not inspected in depth. |
| freedomwebtech/yolo11-water-leak | https://github.com/freedomwebtech/yolo11-water-leak | notebook | ★1 / 2025-01-13 | none | 1 | No README. |
| seonydg/water-floor-detection | https://github.com/seonydg/water-floor-detection | notebook | ★1 / 2023-09-06 | none | 1 | One-line README ("detection of water on the floor"). |
| FalconMadhab/water_puddle_tflite_unet | https://github.com/FalconMadhab/water_puddle_tflite_unet | notebook | ★0 / 2020-09-15 | none | 1 | U-Net to TFLite; stale. |
| vignesh-nagarajan-vn/SchoolPulse-AI | https://github.com/vignesh-nagarajan-vn/SchoolPulse-AI | repo | ★3 / 2026-07-01 | MIT | 2 | Edge-AI suite for schools that includes leak detection. Closest "institutional India-like" framing. |

### 1b. Firmware / valve / FirmGen

| Asset | URL | Type | Stars / last push | License | Rel. | Notes |
|---|---|---|---|---|---|---|
| tomekceszke/water-controller | https://github.com/tomekceszke/water-controller | ESP-IDF firmware | ★1 / 2026-10-15 | **MIT** | **5** | See §0. The best FirmGen reference found: ESP-IDF 5.x, fail-safe tiers, NVS state, MQTT, unit tests. |
| heyitsyang/Whole-House-Water-Leak-Controller | https://github.com/heyitsyang/Whole-House-Water-Leak-Controller | firmware | ★12 / 2025-03-16 | **BSD-3** | 4 | Full MQTT command set. A 5-wire motorized ball valve with **open/closed indicator switches**, and software state re-synced to the real valve position. This is the limit-switch VERIFYING pattern. Arduino/PlatformIO, not IDF. |
| hansrune/BallValveController | https://github.com/hansrune/BallValveController | PCB + firmware | ★4 / 2026-09-04 | NOASSERTION | 4 | ESP32-C3 with CR05 5-wire feedback for **valve-malfunction detection**. A battery returns the valve to its default state on power loss. A local leak-sensor input forces closure without the host. KiCad files included. |
| dchoi98/iot-water-valve | https://github.com/dchoi98/iot-water-valve | HW + firmware + app | ★1 / 2026-03-11 | CERN-OHL-S-2.0 | 3 | **Servo-driven valve** (ESP32Servo) with MQTT over TLS, leak sensor, auto shutoff, and FMEA docs. Arduino. |
| muhammadfikri-dev/esp32-water-leak-detection-valve | https://github.com/muhammadfikri-dev/esp32-water-leak-detection-valve | firmware | ★0 / 2026-09-01 | MIT | 3 | FreeRTOS dual-core split: actuation on core 1, network on core 0. Conductive wetness cable, Kalman filtering, NVS, MQTT. Arduino-ESP32. |
| mm-black65/RainShield | https://github.com/mm-black65/RainShield | firmware | ★0 / 2026-05-28 | MIT | 2 | Wetness sensor drives a servo to close a window; same sensor-to-servo pattern. |
| nihasgoud-stack/esp32-smart-lpg-mitigation-system | https://github.com/nihasgoud-stack/esp32-smart-lpg-mitigation-system | firmware | ★0 / 2026-08-22 | none | 2 | MG995 servo turning a valve on detection (gas). |
| jendabenda712/esp32_water_leak | https://github.com/jendabenda712/esp32_water_leak | firmware | ★0 / 2026-05-29 | none | 1 | Floor leak sensor over MQTT; README is 19 bytes. |

### 1c. Platform infrastructure (not water-specific, but needed)

| Asset | URL | Stars / last push | License | Rel. | Notes |
|---|---|---|---|---|---|
| ultralytics/ultralytics | https://github.com/ultralytics/ultralytics | ★62,570 / 2026-10-16 | **AGPL-3.0** | 5 | YOLO11/26/27 detection and segmentation. `export format=engine` produces TensorRT; Jetson guide at docs.ultralytics.com/guides/nvidia-jetson. |
| dusty-nv/jetson-inference | https://github.com/dusty-nv/jetson-inference | ★9,014 / 2025-10-16 | MIT | 4 | TensorRT segNet/detectNet on Jetson. A permissive alternative to Ultralytics. |
| espressif/esp-idf | https://github.com/espressif/esp-idf | ★19,259 / 2026-10-16 | Apache-2.0 | 5 | v5.5 examples verified to exist: `examples/peripherals/mcpwm/mcpwm_servo_control`, `examples/protocols/mqtt/tcp`. |
| espressif/esp-mqtt | https://github.com/espressif/esp-mqtt | ★753 / 2026-10-01 | Apache-2.0 | 4 | MQTT client; bundled with IDF. |
| espressif/esp-iot-solution | https://github.com/espressif/esp-iot-solution | ★2,701 / 2026-10-14 | Apache-2.0 | 3 | Driver collection; check for button and servo components. |
| facebookresearch/sam2 | https://github.com/facebookresearch/sam2 | ★20,013 / 2026-05-30 | Apache-2.0 | 4 | **Auto-label** your own footage: box prompts become masks, and video propagation gives growth ground truth. |
| NVIDIA-AI-IOT/nanosam | https://github.com/NVIDIA-AI-IOT/nanosam | ★921 / 2023-11-20 | Apache-2.0 | 3 | SAM distilled for real-time TensorRT. Could refine masks on the Jetson. |
| NVIDIA-AI-IOT/nanoowl | https://github.com/NVIDIA-AI-IOT/nanoowl | ★531 / 2025-02-06 | Apache-2.0 | 3 | Open-vocabulary OWL-ViT on TensorRT. Gives a zero-shot "water puddle on floor" baseline before you have data. |
| IDEA-Research/GroundingDINO | https://github.com/IDEA-Research/GroundingDINO | ★10,682 / 2024-08-12 | Apache-2.0 | 3 | Text-prompted boxes for auto-labeling. |
| NVIDIA-AI-IOT/deepstream_python_apps | https://github.com/NVIDIA-AI-IOT/deepstream_python_apps | ★1,897 / 2026-04-01 | NOASSERTION | 3 | DeepStream pipelines; DeepStream ships an MQTT message-broker adapter. |
| AILab-CVC/YOLO-World | https://github.com/AILab-CVC/YOLO-World | ★6,584 / 2025-02-26 | **GPL-3.0** | 2 | Open-vocabulary detector; GPL. |

### 1d. Hydraulic / sensor-only (from the earlier list, now verified)

| Asset | URL | Stars / last push | License | Rel. | Notes |
|---|---|---|---|---|---|
| KIOS-Research/LeakDB | https://github.com/KIOS-Research/LeakDB | ★79 / 2024-10-24 | EUPL-1.2 (code) | 2 | Simulated water-network benchmark; data on Zenodo (see §5). |
| KIOS-Research/Leakage-Repairs-Dataset | https://github.com/KIOS-Research/Leakage-Repairs-Dataset | ★2 / 2026-05-18 | CC BY 4.0 (README) | 2 | Real Cyprus DMA flow series paired with repair logs. |
| Sukrut10k/Smart-Water-Leak-Detection | https://github.com/Sukrut10k/Smart-Water-Leak-Detection | ★6 / 2025-09-18 | none | 2 | Streamlit zone/GIS dashboard idea. |
| gasiepgodoy/WDN-Models-and-Data-Sets | https://github.com/gasiepgodoy/WDN-Models-and-Data-Sets | ★8 / 2026-07-31 | GPL-3.0 | 1 | EPANET models and GraphLeak CSVs. |
| snehaagarwalll/water-leak-detection | https://github.com/snehaagarwalll/water-leak-detection | ★0 / 2025-09-30 | MIT | 1 | Simulated data. |
| wassname/satellite_leak_detection | https://github.com/wassname/satellite_leak_detection | ★32 / 2025-03-30 | none | 1 | Satellite imagery; wrong scale. |
| pasqualedem/GNNLeakDetection | https://github.com/pasqualedem/GNNLeakDetection | ★5 / 2025-11-21 | none | 1 | Code for arXiv 2601.03062. |
| CodersCafeTech/Fluid-Leakage-Detection-With-AI | https://github.com/CodersCafeTech/Fluid-Leakage-Detection-With-AI | ★1 / 2022-12-29 | none | 1 | Stale; flow-sensor ML. |

---

## 2. Kaggle

Downloading requires a Kaggle login, and the Kaggle API needs a token.

| Asset | URL | Type | Size / format | License | Rel. | Notes |
|---|---|---|---|---|---|---|
| Stagnant Water & Wet Surface (your `archive (3).zip`) | mirror of https://data.mendeley.com/datasets/y6zyrnxbfm/4 | images + YOLO boxes | 36.7 MB; 2,000 JPEGs at 256² (1,833 unique) | Unknown on the mirror; **CC BY 4.0 at the Mendeley source** | 3 | Profiled in §0. India-specific outdoor puddles. Noisy fragment boxes and 8% duplicates. |
| LeakWater_Data | https://www.kaggle.com/datasets/reorioll/leakwater-data | images (YOLO layout: train/valid/test + `data.yaml`) | **3.08 GB, 31.5k files** | **Unknown** | 3 | Source data for the instance-segmentation repo in §1a. The largest leak image set found, but unlicensed and undocumented (usability 1.25). |
| Water Leak Dataset | https://www.kaggle.com/datasets/ziya07/water-leak-dataset | time series (CSV) | 85.75 kB (earlier answer, not re-verified) | not verified | 2 | Pressure/flow with leak and burst labels. |
| Smart Water Leak Detection Dataset | https://www.kaggle.com/datasets/talha97s/smart-water-leak-detection-dataset | synthetic tabular | 896.99 kB (earlier answer, not re-verified) | not verified | 2 | Zone and GPS fields; useful for designing the dashboard schema. |
| Water Network Detection (Leakage / No Leakage) | https://www.kaggle.com/datasets/gadingo/water-network-dataset | tabular | 92.42 kB XLSX (earlier answer) | not verified | 1 | Pipe attributes. |
| Indoor floor pooling image dataset | — | — | — | — | — | **Not found.** |

---

## 3. Hugging Face (Hub connector; queries: water leak, water detection, flood detection, flood segmentation, puddle, leak detection, spill)

| Asset | URL | Type | Size | License | Rel. | Notes |
|---|---|---|---|---|---|---|
| water_leakage_voice_data | https://hf.co/datasets/aemreozturk/water_leakage_voice_data | dataset (audio) | <1K clips | CC BY 4.0 | 3 | **Restroom** faucet (1–3 taps × 3 flow levels), flush and hand-wash sounds. Paper: *Sci Rep* 15, 32212 (2025). A cheap acoustic "tap left running" channel for hostel bathrooms. |
| Ayush0000002/Puddle-Detection (Space) | https://hf.co/spaces/Ayush0000002/Puddle-Detection | demo Space | — | none | 2 | Loads YOLOv8 `best.pt` from `Ayush0000002/Puddle-detection-model`. A risk-tier UI idea; weights undocumented. |
| kareem1232/spill_leak_detection (+ `_nano`) | https://hf.co/kareem1232/spill_leak_detection | model | `best.pt` 162.8 MB | none | 2 | Ultralytics-style weights, no model card. A "nano" variant exists. |
| iwin10s/leak-detection-model | https://hf.co/iwin10s/leak-detection-model | model (ViT) | 85.8M params | none | 1 | No card; demo Space. |
| lixintu/*-waterleak (≈20 fine-tunes) | https://hf.co/lixintu/Qwen2-VL-7B-Instruct-waterleakV2.17 | VLM fine-tunes | 7–12B | apache-2.0 tag (but Llama/Pixtral base terms apply) | 1 | Far too heavy for real-time edge use; no cards. |
| zeriix3/waterleak | https://hf.co/datasets/zeriix3/waterleak | tabular | 10M–100M rows | CC BY 4.0 (from Aghashahi 2022 source) | 1 | Lab testbed pipe data. |
| Verso-Industries/water-leak-dataset | https://hf.co/datasets/Verso-Industries/water-leak-dataset | tabular | 1K–10K rows | MIT | 1 | |
| ybli/yolo-water-drip-detection | https://hf.co/datasets/ybli/yolo-water-drip-detection | dataset card only | — | none | 1 | Data lives on data2.cn (external). |
| prithivMLmods/Flood-Image-Detection | https://hf.co/prithivMLmods/Flood-Image-Detection | SigLIP2 classifier | — | Apache-2.0 | 1 | Scene-level flood classification only. |
| Indoor puddle segmentation model or dataset | — | — | — | — | — | **Not found.** |

---

## 4. Roboflow Universe (details from search snippets; pages return a Cloudflare 403 to automated fetches)

| Project | URL | Images | Task / classes | License | Rel. | Notes |
|---|---|---|---|---|---|---|
| puddle (hank-g6unv) | https://universe.roboflow.com/hank-g6unv/puddle-leaew | 1,302 | instance seg / puddle | CC BY 4.0 | 4 | Masks give `pool_area` directly. |
| puddle-segmentation | https://universe.roboflow.com/computervision-naujm/puddle-segmentation-zwiab | 1,836 | segmentation | not shown | 4 | Check the license on the page. |
| Water Segmentation | https://universe.roboflow.com/watersegmentation/water-segmentation-n6ecd | ~9,154 | semantic seg / water | **Public domain** | 4 | Generic water, but the largest and most permissive set. |
| leak (dooropen) | https://universe.roboflow.com/dooropen/leak-6xwrk | ~2.7k (earlier answer) | det / leak, water leak | CC BY 4.0 (earlier answer) | 4 | A fork of it trained krishailab's model. |
| Flaque d'eau | https://universe.roboflow.com/projet-traitement-dimages/flaque-d-eau | 692 | puddle | CC BY 4.0 | 3 | |
| pipe-leak | https://universe.roboflow.com/zbxxx/pipe-leak | 641 | det + model | CC BY 4.0 | 3 | Detects the leak *source* at pipe joints. |
| puddle detection | https://universe.roboflow.com/ren-yzdes/puddle-detection-riyav | ? | det | CC BY 4.0 | 3 | Jun 2025. |
| Water Puddle | https://universe.roboflow.com/projects-pwwbs/water-puddle-joyj6 | ? | puddle | CC BY 4.0 | 3 | May 2025. |
| Water Spill Detection | https://universe.roboflow.com/torp-training/water-spill-detection | 88 | instance seg / water | CC BY 4.0 | 3 | Spill-specific but tiny. |
| Damage Tracking 2 | https://universe.roboflow.com/qwe-sq8de/damage-tracking-2 | ? | "Leaking water", cracks, spalling | ? | 2 | Wall and ceiling seepage, common in Indian buildings. |
| water damage detection | https://universe.roboflow.com/bhardwajs-workspace/water-damage-detection | ? | waterlogging | ? | 2 | |
| water spill (dooropen) | https://universe.roboflow.com/dooropen/water-spill-mmtth | ? | ? | ? | ? | No details visible. |
| Water Leak (school) | https://universe.roboflow.com/school-yfphj/water-leak | 301 | det | CC BY 4.0 | 2 | Sep 2023. |
| pipe leakage | https://universe.roboflow.com/work-upary/pipe-leakage-gvr3a | 120 | det | ? | 1 | |
| Earlier answer's: water-leak-hwh4x/water-leakage-ayy4s (3,542 imgs claimed), projet-industrie/water-puddles-du0za (708 claimed), icews/water-puddles-f5tdo, ff-vzbf7/road-flood-water, flood-extun/flood-detection-system-akszc | (as given) | — | — | — | — | **Not re-verified.** Cloudflare 403, and none appeared in my searches. Open them manually. |

---

## 5. Zenodo (records API; 8 queries)

| Title | URL | DOI | Size | License | Rel. | Notes |
|---|---|---|---|---|---|---|
| LeakDB Dataset | https://zenodo.org/records/13985057 | 10.5281/zenodo.13985057 | 13.9 GB | CC BY 4.0 | 2 | Simulated network scenarios plus scoring code. |
| BattLeDIM Dataset | https://zenodo.org/records/4017659 | 10.5281/zenodo.4017659 | 550.5 MB | CC BY 4.0 | 2 | SCADA flow/pressure with leak logs. |
| Acoustic data — self-supervised acoustic leakage detection | https://zenodo.org/records/18631450 | 10.5281/zenodo.18631450 | 5.65 MB (3 RAR) | CC BY 4.0 | 2 | 1,000 one-second clips (leak / no-leak / noise), outdoor. |
| Hourly Anomaly Scores & Leak Labels | https://zenodo.org/records/15096167 | 10.5281/zenodo.15096167 | 0.82 MB | CC BY 4.0 | 2 | Temporal confirmation logic. |
| Dataset For Water Segmentation (N. A. Muhadi) | https://zenodo.org/records/7269522 | 10.5281/zenodo.7269522 | 110.8 MB | CC BY 4.0 | 3 | RGB water segmentation. Title and metadata only; inspect before use. |
| Properties of leak detection sensor, Arduino & application code (H. Jeong) | https://zenodo.org/records/5592032 | 10.5281/zenodo.5592032 | 2.2 MB | MIT | 2 | Leak-sensor characterization plus Arduino code. Relevant to calibrating the wetness sensor. |
| Leak Detection Physics-Informed Synthetic Dataset | https://zenodo.org/records/19207703 | 10.5281/zenodo.19207703 | 0.2 MB | CC BY 4.0 | 1 | 2,000 synthetic rows. |
| Camera-based indoor pooling dataset | — | — | — | — | — | **Not found.** "Water puddle images" returned only biology figures. |

---

## 6. Papers With Code

**The platform no longer exists.** Meta sunset it in late July 2025, and it now redirects to Hugging Face Trending Papers. Its benchmarks and API are frozen. I ran the equivalent searches on HF Papers instead:

| Paper | URL | Code / data | Rel. | Notes |
|---|---|---|---|---|
| LangGas — zero-shot semi-transparent gas leak detection | https://huggingface.co/papers/2503.02910 | new synthetic dataset | 3 | Pipeline: background subtraction, then zero-shot detection, filtering and segmentation. Transfers well to "new wet region appeared on a static floor". |
| Fine-grained spatial-temporal perception for gas leak segmentation | https://huggingface.co/papers/2505.00295 | — | 2 | Motion cues for amorphous leaks. |
| RT-CAN — RGB-thermal invisible gas detection | https://huggingface.co/papers/2403.17712 | new benchmark | 2 | RGB + thermal fusion. |
| FRED — flooded road multimodal dataset | https://huggingface.co/papers/2605.22018 | dataset | 2 | Confirms Puddle-1000 became inaccessible after CloudStor shut down. |

---

## 7. arXiv (export API; 13 query variants; IDs verified)

| Paper | URL | Code / data | Rel. | Notes |
|---|---|---|---|---|
| AGSENet: robust road ponding detection | https://arxiv.org/abs/2410.16999 | github.com/Lyu-Dakang/AGSENet | 4 | Saliency-enhanced ponding segmentation with re-annotated Puddle-1000 plus Foggy and Night variants. |
| Excretion detection in pigsties (CNN + transformer) | https://arxiv.org/abs/2412.00256 | — | 4 | Segments **puddles on indoor floors** to estimate puddle area. The closest indoor-floor analog to `pool_area`. |
| Liquid leak detection using thermal images | https://arxiv.org/abs/2312.10980 | — | 3 | YOLO and RT-DETR on thermal footage (oil and gas). |
| InfraGPT: VLM-based urban defect pipeline | https://arxiv.org/abs/2510.16017 | — | 3 | CCTV, then YOLO (including fluid leaks), then a VLM that outputs a structured action plan. An evidence-to-action pattern. |
| Time-Reversed Imaging (TRACE-HEI) | https://arxiv.org/abs/2607.22352 | dataset | 3 | Thermal, UV and visible traces of liquid spills. Thermal reveals fresh wetness. |
| Ultralow-power standoff acoustic leak detection | https://arxiv.org/abs/2511.00348 | — | 3 | On-device detection of 0.15 L/min at more than 10 m, including leaks behind walls and floors. |
| AI-driven water segmentation (UNet / ResNet / DeepLabv3) | https://arxiv.org/abs/2501.08266 | not found | 3 | Architecture comparison for pixel-level water. |
| Water flow detection via sound + ML | https://arxiv.org/abs/2501.11151 | — | 2 | Detects ≥100 mL/min in building pipes. |
| Internet-connected residential water leak monitor | https://arxiv.org/abs/1910.13335 | — | 2 | Bathroom slow leaks. |
| AquaFusionNet | https://arxiv.org/abs/2512.06848 | AquaMicro12K (described) | 2 | Edge vision–sensor fusion pattern (water-quality task). |
| 3D tracking of water hazards with polarized stereo | https://arxiv.org/abs/1701.04175 | — | 2 | Polarization as a water cue. |
| Explainable fuzzy GNNs for leak detection | https://arxiv.org/abs/2601.03062 | github.com/pasqualedem/GNNLeakDetection | 1 | Network-scale, not camera-based. |
| Edge perception survey | https://arxiv.org/abs/2605.18457 | — | 1 | Background only. |

---

## Top 5 assets to use immediately

Score order: Vision relevance / Edge / LeakLatch fit / License / Docs / Uniqueness.

| # | Asset | Scores | Why now |
|---|---|---|---|
| 1 | **Ultralytics YOLO11/26-seg → TensorRT on JetPack 6** | 4/5/3/2/5/1 | The fastest route to a `.engine` file that satisfies Track A. Segmentation gives `pool_area`. Mind the AGPL; the MIT fallback is jetson-inference. |
| 2 | **Roboflow segmentation sets:** hank-g6unv/puddle-leaew (1,302, CC BY), puddle-segmentation-zwiab (1,836), watersegmentation (~9k, public domain) | 4/4/3/4/2/2 | Masks rather than boxes. Pre-train on these, then fine-tune on your own floor footage. |
| 3 | **tomekceszke/water-controller** + ESP-IDF v5.5 `mcpwm_servo_control` and `mqtt/tcp` examples | 1/4/5/5/5/4 | MIT and ESP-IDF 5.x. The fail-safe tier design, NVS valve state and host-tested C modules map directly onto IDLE→…→VERIFYING. |
| 4 | **heyitsyang/Whole-House-Water-Leak-Controller** | 1/4/5/5/3/4 | BSD-3. Shows how to read valve **open/closed switches** and resync software state, which is your VERIFYING step. |
| 5 | **SAM 2** for labeling your own hostel footage | 3/2/4/5/5/3 | Box or point prompt, then masks propagated through video. That gives true per-frame `pool_area`, and therefore `growth_rate` ground truth, in hours. |

## Top 3 assets to adapt

| # | Asset | Scores | Adaptation |
|---|---|---|---|
| 1 | **Stagnant Water & Wet Surface** (already downloaded) | 4/4/3/4/4/4 | Remove the 167 duplicates before splitting. Convert fragment boxes to masks with SAM 2 box prompts. Keep `wet surface` as a SUSPECT/hard-negative class. Cite Mendeley CC BY 4.0. |
| 2 | **Euler-integration idea** (huynhthanhphong repo + reorioll/leakwater-data) | 4/3/5/1/2/5 | Reimplement: `growth_rate = d(area_px·k_px→m²)/dt`, smoothed with an EMA. Ask the author to license the data before using it. |
| 3 | **Hybrid synthetic data** (Kether180 thesis) | 3/3/4/1/4/4 | Generate Indian hostel bathroom and corridor floors with water pooling via SD or img2img, and use them only alongside real data (their synthetic-only result was 47%). Reimplement; there's no license. |

## Gaps identified

1. **No permissively licensed indoor-floor pooling segmentation set.** Everything found is outdoor puddles, roads, pipe close-ups or satellite. Nothing covers tiled, Kota-stone or mosaic floors, which are typical in Indian PGs and hostels.
2. **No temporal "growing puddle" sequences** to supervise or benchmark `growth_rate`.
3. **No false-alarm benchmark.** Missing negatives include freshly mopped floors, wet footprints, buckets, glossy-tile reflections and shadows.
4. **No zone-locked detection pipeline** (GitHub "zone-based water detection" returned 0 hits). The ROI-per-zone mapping to `zone_id` is yours to build.
5. **No ESP-IDF servo-valve firmware with limit-switch verification** ("limit switch valve verification" returned 0 hits). The patterns exist: 5-wire valve indicator switches, and water-controller's flow-after-close check. A servo plus a separate limit switch on ESP-IDF 5.5 does not.
6. **No end-to-end Jetson TensorRT → MQTT → ESP32 valve loop** with post-action verification.
7. **No standard event schema.** Define `event_id`, `zone_id`, `pool_area`, `growth_rate` yourself and publish a JSON Schema.

## Recommended searches to run manually

- **Roboflow:** `wet floor`, `floor water`, `spill`, `seepage`, `dampness`, `ceiling leak`, `bathroom floor`, `积水` (standing water), `漏水` (leak), `水たまり` (puddle).
- **Kaggle:** `wet floor`, `liquid spill`, `wall seepage`, `dampness`, `water damage`.
- **GitHub:** `esp-idf servo "limit switch"`, `mcpwm servo valve`, `deepstream mqtt msgbroker`, `yolo seg tensorrt "jetpack 6"`, `"spill detection" robot`, `topic:esp-idf valve`.
- **arXiv / HF Papers:** `"wet floor" detection`, `"liquid spill" retail robot`, `polarization water detection indoor`, `thermal wet surface evaporation`.
- **Other hosts:** IEEE DataPort "stagnant water" (free login), Mendeley [xz2nykszbs](https://data.mendeley.com/datasets/xz2nykszbs/1) "water leakage" (CC BY 4.0, 2020, JSON labels, image count unstated).

## Red flags

1. **Ultralytics is AGPL-3.0.** That's fine for an open hackathon repo. Trained weights and serving code fall under AGPL if distributed; commercial use needs an Enterprise license or jetson-inference (MIT). YOLO-World is **GPL-3.0**.
2. **krishailab/water-leak** has 0 stars, **no license** and undocumented weights. The earlier answer ranked it #3 to "use immediately"; it should not be.
3. **Kaggle mirrors carry "Unknown" licenses.** Cite the Mendeley CC BY 4.0 original. Your zip has **8% exact duplicates**, which will leak across train/val if you split randomly.
4. **reorioll/leakwater-data**: 3 GB, license Unknown, no description.
5. **Paywalled bait repos:** `lonlonago/*`, `nextcombo/*`, `767172261/*`, `QQ767172261/*`, `share2code99/*` ("Sponsor to obtain the full data files"). Qunmasj's data is on kdocs.cn with unclear provenance. Avoid all of them.
6. **Puddle-1000:** the original link is dead, and the AGSENet mirror (Quark Pan with access codes) has no license.
7. **HF models without cards or licenses** (kareem1232, iwin10s, Ayush0000002). The lixintu VLMs are tagged Apache, but Llama 3.2 and Pixtral base terms still apply.
8. **Licenses to read before reusing:** hansrune is NOASSERTION, and dchoi98 is **CERN-OHL-S** (strongly reciprocal for hardware).
9. **Zenodo 19203517 "In Deep Plumbing"** is an advertising PDF with a DOI. Ignore it.
10. **Papers With Code is defunct.** Any PwC link will redirect.

## Corrections to the earlier (pasted) answer

| Claim | Status |
|---|---|
| krishailab license and stars "Not found" | ★0, no license; trained on a 2,445-image fork of `dooropen/leak-6xwrk` |
| LeakDB license "not found" | Repo is EUPL-1.2; Zenodo data is CC BY 4.0 (13.9 GB) |
| BattLeDIM size "Not found" | 550.5 MB, CC BY 4.0 |
| Acoustic leakage data "2.9 MB" | 5.65 MB, 3 RAR files, CC BY 4.0 |
| Hugging Face "Not found" | Partly wrong: assets exist (an audio dataset, puddle and spill models), but none is production-grade |
| Papers With Code "Not found" | The platform shut down in July 2025 |
| Roboflow `water-leakage-ayy4s` / `water-puddles-du0za` stats | Could not re-verify |
| Gaps section | Was truncated; completed above |
