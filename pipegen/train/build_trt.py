"""Compile the ONNX segmenter into a TensorRT engine, check it against ONNX Runtime
on real validation images, and benchmark it. Run this ON the target device:
engines are specific to the GPU and TensorRT version.

    python -m pipegen.train.build_trt                 # FP16 engine -> models/leaklatch_waterseg.engine
    # Jetson (JetPack 6) alternative with the stock CLI:
    /usr/src/tensorrt/bin/trtexec --onnx=models/leaklatch_waterseg.onnx \
        --saveEngine=models/leaklatch_waterseg.engine --fp16

TensorRT 8.6/10 take the FP32 ONNX plus the FP16 builder flag; TensorRT 11
builds strongly-typed networks only, so the FP16 ONNX copy is used.
"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import cv2
import numpy as np

from pipegen.backends import OnnxSegmenter, TensorRTSegmenter, _ck, _cudart, file_sha256, preprocess, sigmoid

ROOT = Path(__file__).resolve().parents[2]


def build(onnx_fp32: Path, onnx_fp16: Path, engine: Path, fp16: bool, workspace_mb: int) -> dict:
    import tensorrt as trt

    logger = trt.Logger(trt.Logger.WARNING)
    builder = trt.Builder(logger)
    has_fp16_flag = hasattr(trt.BuilderFlag, "FP16")
    flags = 0
    if hasattr(trt.NetworkDefinitionCreationFlag, "EXPLICIT_BATCH"):  # TensorRT 8.x
        flags |= 1 << int(trt.NetworkDefinitionCreationFlag.EXPLICIT_BATCH)
    src = onnx_fp32
    mode = "fp32"
    if fp16 and has_fp16_flag:
        mode = "fp16 (builder flag)"
    elif fp16:
        flags |= 1 << int(trt.NetworkDefinitionCreationFlag.STRONGLY_TYPED)
        src, mode = onnx_fp16, "fp16 (strongly typed)"
    network = builder.create_network(flags)
    parser = trt.OnnxParser(network, logger)
    if not parser.parse_from_file(str(src)):
        errs = [str(parser.get_error(i)) for i in range(parser.num_errors)]
        raise RuntimeError("ONNX parse failed: " + "; ".join(errs))
    config = builder.create_builder_config()
    config.set_memory_pool_limit(trt.MemoryPoolType.WORKSPACE, workspace_mb << 20)
    if fp16 and has_fp16_flag:
        config.set_flag(trt.BuilderFlag.FP16)
    t0 = time.time()
    plan = builder.build_serialized_network(network, config)
    if plan is None:
        raise RuntimeError("TensorRT build failed")
    engine.write_bytes(bytes(plan))
    return {"tensorrt": trt.__version__, "precision": mode, "onnx": src.name, "build_s": round(time.time() - t0, 1)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--onnx", type=Path, default=ROOT / "models" / "leaklatch_waterseg.onnx")
    ap.add_argument("--engine", type=Path, default=ROOT / "models" / "leaklatch_waterseg.engine")
    ap.add_argument("--fp32", action="store_true")
    ap.add_argument("--size", type=int, default=320)
    ap.add_argument("--workspace-mb", type=int, default=1024)
    ap.add_argument("--iters", type=int, default=300)
    args = ap.parse_args()
    fp16_onnx = args.onnx.with_name(args.onnx.stem + "_fp16.onnx")
    info = build(args.onnx, fp16_onnx, args.engine, not args.fp32, args.workspace_mb)

    cudart = _cudart()
    props = _ck(cudart.cudaGetDeviceProperties(0))
    gpu = props.name.decode() if isinstance(props.name, bytes) else str(props.name)
    trt_seg = TensorRTSegmenter(args.engine, args.size)
    ort_seg = OnnxSegmenter(args.onnx, args.size)

    # parity on real validation images (or synthetic ones if the real set is absent)
    real = ROOT / "data" / "stagnant_water"
    imgs = sorted((real / "images").glob("*.jpg"))[:80] or sorted((ROOT / "data" / "synthetic" / "val" / "images").glob("*.jpg"))[:80]
    diffs, agree = [], []
    for p in imgs:
        x = preprocess(cv2.imread(str(p)), args.size)
        a, b = sigmoid(trt_seg.logits(x)[0, 0]), sigmoid(ort_seg.logits(x)[0, 0])
        diffs.append(float(np.abs(a - b).max()))
        ma, mb = a > 0.5, b > 0.5
        u = (ma | mb).sum()
        agree.append(1.0 if u == 0 else float((ma & mb).sum() / u))

    x = preprocess(np.zeros((480, 640, 3), np.uint8), args.size)
    for _ in range(20):
        trt_seg.logits(x)
    lat = []
    for _ in range(args.iters):
        t0 = time.perf_counter()
        trt_seg.logits(x)
        lat.append((time.perf_counter() - t0) * 1000)
    ort_lat = []
    for _ in range(30):
        t0 = time.perf_counter()
        ort_seg.logits(x)
        ort_lat.append((time.perf_counter() - t0) * 1000)
    lat.sort()
    report = {
        **info, "gpu": gpu, "engine": args.engine.name, "engine_sha256": file_sha256(args.engine),
        "engine_mb": round(args.engine.stat().st_size / 1e6, 2),
        "latency_ms": {"mean": round(sum(lat) / len(lat), 3), "p50": round(lat[len(lat) // 2], 3),
                       "p99": round(lat[int(len(lat) * 0.99) - 1], 3)},
        "throughput_fps": round(1000 / (sum(lat) / len(lat)), 1),
        "onnxruntime_cpu_ms": round(sorted(ort_lat)[len(ort_lat) // 2], 2),
        "parity_vs_onnxruntime": {"images": len(imgs), "max_prob_diff": round(max(diffs), 4),
                                  "mean_mask_iou": round(sum(agree) / len(agree), 4)},
        "note": "latency = host->device copy + inference + device->host copy, batch 1, 320x320",
    }
    (args.engine.parent / "trt_report.json").write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    main()
