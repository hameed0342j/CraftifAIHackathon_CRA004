"""Export the trained segmenter to ONNX (FP32) plus an FP16 copy for strongly-typed TensorRT.

    python -m pipegen.train.export_onnx
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import onnx
import torch

from .train_seg import build_model

ROOT = Path(__file__).resolve().parents[2]


class Logits(torch.nn.Module):
    def __init__(self, m: torch.nn.Module) -> None:
        super().__init__()
        self.m = m

    def forward(self, image: torch.Tensor) -> torch.Tensor:
        return self.m(image)["out"]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--weights", type=Path, default=ROOT / "models" / "leaklatch_waterseg.pt")
    ap.add_argument("--out", type=Path, default=ROOT / "models" / "leaklatch_waterseg.onnx")
    ap.add_argument("--size", type=int, default=320)
    args = ap.parse_args()

    model = build_model(pretrained_backbone=False)
    model.load_state_dict(torch.load(args.weights, map_location="cpu", weights_only=True))
    net = Logits(model).eval()
    x = torch.randn(1, 3, args.size, args.size)
    export_kw = dict(input_names=["image"], output_names=["logits"], opset_version=17)
    try:
        torch.onnx.export(net, (x,), str(args.out), dynamo=False, **export_kw)
    except TypeError:  # very old torch without the dynamo switch
        torch.onnx.export(net, (x,), str(args.out), **export_kw)
    m = onnx.load(str(args.out))
    onnx.checker.check_model(m)

    import onnxruntime as ort

    with torch.no_grad():
        ref = net(x).numpy()
    got = ort.InferenceSession(str(args.out), providers=["CPUExecutionProvider"]).run(None, {"image": x.numpy()})[0]
    diff32 = float(np.abs(ref - got).max())

    from onnxruntime.transformers.float16 import convert_float_to_float16

    fp16_path = args.out.with_name(args.out.stem + "_fp16.onnx")
    onnx.save(convert_float_to_float16(m, keep_io_types=True), str(fp16_path))
    got16 = ort.InferenceSession(str(fp16_path), providers=["CPUExecutionProvider"]).run(None, {"image": x.numpy()})[0]
    diff16 = float(np.abs(ref - got16).max())
    info = {"onnx": args.out.name, "onnx_fp16": fp16_path.name, "opset": 17, "input": [1, 3, args.size, args.size],
            "max_abs_logit_diff_vs_torch": {"fp32": diff32, "fp16": diff16},
            "size_mb": {"fp32": round(args.out.stat().st_size / 1e6, 2), "fp16": round(fp16_path.stat().st_size / 1e6, 2)}}
    (args.out.parent / "onnx_export.json").write_text(json.dumps(info, indent=1), encoding="utf-8")
    print(json.dumps(info))


if __name__ == "__main__":
    main()
