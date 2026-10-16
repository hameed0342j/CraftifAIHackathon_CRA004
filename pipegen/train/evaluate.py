"""Evaluate a checkpoint on the held-out real and synthetic sets (single process, low memory).

    python -m pipegen.train.evaluate
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import torch
from torch.utils.data import DataLoader

from .train_seg import SegFolder, build_model, evaluate

ROOT = Path(__file__).resolve().parents[2]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--weights", type=Path, default=ROOT / "models" / "leaklatch_waterseg.pt")
    ap.add_argument("--size", type=int, default=320)
    args = ap.parse_args()
    device = "cuda" if torch.cuda.is_available() else "cpu"
    model = build_model(pretrained_backbone=False)
    model.load_state_dict(torch.load(args.weights, map_location="cpu", weights_only=True))
    model.to(device).eval()
    real_root = ROOT / "data" / "stagnant_water"
    man = json.loads((real_root / "manifest.json").read_text())
    syn = ROOT / "data" / "synthetic" / "val"
    sets = {
        "real_val": SegFolder(real_root, man["val"], args.size, False),
        "synthetic_val": SegFolder(syn, sorted(p.stem for p in (syn / "images").glob("*.jpg")), args.size, False),
    }
    out = {"weights": args.weights.name, "input": args.size}
    for name, ds in sets.items():
        out[name] = {"images": len(ds), **evaluate(model, DataLoader(ds, batch_size=16, num_workers=0), device)}
        print(name, json.dumps(out[name]))
    (ROOT / "models" / "eval_metrics.json").write_text(json.dumps(out, indent=1), encoding="utf-8")


if __name__ == "__main__":
    main()
