"""Pre-render the synthetic indoor-floor dataset (exact masks) in parallel.

    python -m pipegen.train.synth --train 4000 --val 400
"""

from __future__ import annotations

import argparse
from multiprocessing import Pool
from pathlib import Path

import cv2

from simlab.render import random_sample

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "synthetic"


def _one(args: tuple[int, str]) -> None:
    seed, split = args
    img, mask = random_sample(seed)
    cv2.imwrite(str(OUT / split / "images" / f"{seed:06d}.jpg"), img, [cv2.IMWRITE_JPEG_QUALITY, 92])
    cv2.imwrite(str(OUT / split / "masks" / f"{seed:06d}.png"), mask)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--train", type=int, default=4000)
    ap.add_argument("--val", type=int, default=400)
    ap.add_argument("--workers", type=int, default=16)
    args = ap.parse_args()
    jobs = [(s, "train") for s in range(args.train)] + [(1_000_000 + s, "val") for s in range(args.val)]
    for split in ("train", "val"):
        (OUT / split / "images").mkdir(parents=True, exist_ok=True)
        (OUT / split / "masks").mkdir(parents=True, exist_ok=True)
    with Pool(args.workers) as pool:
        for i, _ in enumerate(pool.imap_unordered(_one, jobs, chunksize=16)):
            if i % 500 == 0:
                print(f"{i}/{len(jobs)}", flush=True)
    print(f"wrote {len(jobs)} samples to {OUT}")


if __name__ == "__main__":
    main()
