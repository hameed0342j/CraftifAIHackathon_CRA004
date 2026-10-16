"""Turn the Kaggle/Mendeley "Stagnant Water and Wet Surface" YOLO-box dataset into
segmentation masks (Patil & Bhutad, Data in Brief 2021, CC BY 4.0, Mendeley y6zyrnxbfm).

    python -m pipegen.train.prepare --zip "../archive (3).zip"

* exact duplicates are removed BEFORE the split (the Kaggle mirror has 167 copies),
* mask = union of `water` boxes (1); `wet surface` boxes become ignore (255),
  because the boxes are coarse and wet-surface is neither pooled water nor dry floor,
* split 85/15 by content hash, so it is stable across machines.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import zipfile
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[2]
WATER, WET = 0, 1
IGNORE = 255


def masks_from_boxes(lines: list[str], w: int, h: int) -> np.ndarray:
    mask = np.zeros((h, w), np.uint8)
    boxes = []
    for ln in lines:
        p = ln.split()
        if len(p) != 5:
            continue
        c, x, y, bw, bh = int(float(p[0])), *map(float, p[1:])
        x0, y0 = int(round((x - bw / 2) * w)), int(round((y - bh / 2) * h))
        x1, y1 = int(round((x + bw / 2) * w)), int(round((y + bh / 2) * h))
        boxes.append((c, max(0, x0), max(0, y0), min(w, x1), min(h, y1)))
    for c, x0, y0, x1, y1 in boxes:
        if c == WET:
            mask[y0:y1, x0:x1] = IGNORE
    for c, x0, y0, x1, y1 in boxes:
        if c == WATER:
            mask[y0:y1, x0:x1] = 1
    return mask


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--zip", required=True, help="Kaggle archive with 'Stagnant water and Wet surface Dataset/'")
    ap.add_argument("--out", type=Path, default=ROOT / "data" / "stagnant_water")
    args = ap.parse_args()
    zf = zipfile.ZipFile(args.zip)
    names = {n for n in zf.namelist() if not n.endswith("/")}
    imgs = sorted(n for n in names if n.lower().endswith((".jpg", ".jpeg", ".png")))
    (args.out / "images").mkdir(parents=True, exist_ok=True)
    (args.out / "masks").mkdir(parents=True, exist_ok=True)
    seen: set[str] = set()
    split = {"train": [], "val": []}
    dupes = empty = 0
    for n in imgs:
        data = zf.read(n)
        digest = hashlib.md5(data).hexdigest()
        if digest in seen:
            dupes += 1
            continue
        seen.add(digest)
        img = cv2.imdecode(np.frombuffer(data, np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            continue
        label = n.rsplit(".", 1)[0] + ".txt"
        lines = zf.read(label).decode("utf-8", "replace").splitlines() if label in names else []
        if not any(ln.strip() for ln in lines):
            empty += 1
        mask = masks_from_boxes(lines, img.shape[1], img.shape[0])
        stem = digest[:16]
        cv2.imwrite(str(args.out / "images" / f"{stem}.jpg"), img, [cv2.IMWRITE_JPEG_QUALITY, 95])
        cv2.imwrite(str(args.out / "masks" / f"{stem}.png"), mask)
        split["val" if int(digest[:8], 16) % 100 < 15 else "train"].append(stem)
    manifest = {
        "source": "Stagnant Water and Wet Surface (Patil & Bhutad 2021), Mendeley y6zyrnxbfm, CC BY 4.0",
        "doi": "10.1016/j.dib.2021.107752",
        "images_in_zip": len(imgs), "duplicates_removed": dupes, "unlabelled": empty,
        "train": split["train"], "val": split["val"],
    }
    (args.out / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    print(f"{len(seen)} unique images ({dupes} duplicates removed, {empty} unlabelled): "
          f"train {len(split['train'])}, val {len(split['val'])} -> {args.out}")


if __name__ == "__main__":
    main()
