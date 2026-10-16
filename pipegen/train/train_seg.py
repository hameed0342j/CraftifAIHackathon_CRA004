"""Train the PipeGen water segmenter (LR-ASPP MobileNetV3-Large, 1 output channel).

    python -m pipegen.train.prepare --zip "../archive (3).zip"   # real, India-specific outdoor puddles
    python -m pipegen.train.synth                                # synthetic indoor floors with exact masks
    python -m pipegen.train.train_seg --epochs 30

Every component is permissively licensed (torchvision BSD-3, ImageNet backbone
weights from torchvision), so the trained model can ship under MIT.
"""

from __future__ import annotations

import argparse
import json
import random
import time
from pathlib import Path

import cv2
import numpy as np
import torch
import torch.nn.functional as Fn
from torch.utils.data import ConcatDataset, DataLoader, Dataset, Subset
from torchvision.models import MobileNet_V3_Large_Weights
from torchvision.models.segmentation import lraspp_mobilenet_v3_large

ROOT = Path(__file__).resolve().parents[2]
MEAN = np.array([0.485, 0.456, 0.406], np.float32)
STD = np.array([0.229, 0.224, 0.225], np.float32)
IGNORE = 255


def build_model(pretrained_backbone: bool = True) -> torch.nn.Module:
    weights = MobileNet_V3_Large_Weights.IMAGENET1K_V1 if pretrained_backbone else None
    return lraspp_mobilenet_v3_large(weights=None, weights_backbone=weights, num_classes=1)


class SegFolder(Dataset):
    """images/<stem>.jpg + masks/<stem>.png (0 = dry, 1 = water, 255 = ignore)."""

    def __init__(self, root: Path, stems: list[str], size: int, augment: bool) -> None:
        self.root, self.stems, self.size, self.augment = root, stems, size, augment

    def __len__(self) -> int:
        return len(self.stems)

    def __getitem__(self, i: int):
        s = self.stems[i]
        img = cv2.imread(str(self.root / "images" / f"{s}.jpg"), cv2.IMREAD_COLOR)
        mask = cv2.imread(str(self.root / "masks" / f"{s}.png"), cv2.IMREAD_GRAYSCALE)
        if self.augment:
            img, mask = augment(img, mask)
        img = cv2.resize(img, (self.size, self.size), interpolation=cv2.INTER_AREA)
        mask = cv2.resize(mask, (self.size, self.size), interpolation=cv2.INTER_NEAREST)
        x = (cv2.cvtColor(img, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0 - MEAN) / STD
        return torch.from_numpy(x.transpose(2, 0, 1).copy()), torch.from_numpy(mask.astype(np.int64))


def augment(img: np.ndarray, mask: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    h, w = mask.shape
    s = random.uniform(0.55, 1.0)  # random resized crop
    ch, cw = int(h * s), int(w * s * random.uniform(0.8, 1.25))
    cw = min(cw, w)
    y0, x0 = random.randint(0, h - ch), random.randint(0, w - cw)
    img, mask = img[y0:y0 + ch, x0:x0 + cw], mask[y0:y0 + ch, x0:x0 + cw]
    if random.random() < 0.5:
        img, mask = img[:, ::-1], mask[:, ::-1]
    if random.random() < 0.3:  # small rotation
        a = random.uniform(-12, 12)
        M = cv2.getRotationMatrix2D((img.shape[1] / 2, img.shape[0] / 2), a, 1.0)
        img = cv2.warpAffine(np.ascontiguousarray(img), M, img.shape[1::-1], borderMode=cv2.BORDER_REFLECT)
        mask = cv2.warpAffine(np.ascontiguousarray(mask), M, mask.shape[1::-1], flags=cv2.INTER_NEAREST,
                              borderValue=IGNORE)
    img = img.astype(np.float32)
    img = img * random.uniform(0.6, 1.3) + random.uniform(-25, 25)          # exposure
    img = img * np.array([random.uniform(0.85, 1.15) for _ in range(3)], np.float32)  # white balance
    if random.random() < 0.3:
        img = cv2.GaussianBlur(img, (0, 0), random.uniform(0.5, 1.5))
    if random.random() < 0.4:
        img = img + np.random.normal(0, random.uniform(2, 10), img.shape).astype(np.float32)
    return np.clip(img, 0, 255).astype(np.uint8), np.ascontiguousarray(mask)


def masked_loss(logits: torch.Tensor, target: torch.Tensor) -> torch.Tensor:
    """BCE + soft Dice over labelled pixels only."""
    logits = logits[:, 0]
    valid = (target != IGNORE).float()
    t = (target == 1).float()
    bce = Fn.binary_cross_entropy_with_logits(logits, t, reduction="none")
    bce = (bce * valid).sum() / valid.sum().clamp(min=1)
    p = torch.sigmoid(logits) * valid
    inter = (p * t).sum(dim=(1, 2))
    dice = 1 - (2 * inter + 1) / (p.sum(dim=(1, 2)) + (t * valid).sum(dim=(1, 2)) + 1)
    return bce + 0.5 * dice.mean()


@torch.no_grad()
def evaluate(model: torch.nn.Module, loader: DataLoader, device: str) -> dict:
    model.eval()
    inter = union = tp_img = fp_img = fn_img = tn_img = 0
    for x, y in loader:
        x, y = x.to(device), y.to(device)
        pred = model(x)["out"][:, 0] > 0
        valid = y != IGNORE
        gt = (y == 1) & valid
        pr = pred & valid
        inter += (pr & gt).sum().item()
        union += (pr | gt).sum().item()
        # image level: is there a pool of at least 0.5% of the frame?
        g = gt.flatten(1).float().mean(1) > 0.005
        q = pr.flatten(1).float().mean(1) > 0.005
        tp_img += (g & q).sum().item(); fp_img += (~g & q).sum().item()
        fn_img += (g & ~q).sum().item(); tn_img += (~g & ~q).sum().item()
    model.train()
    return {"iou": inter / max(union, 1),
            "img_precision": tp_img / max(tp_img + fp_img, 1), "img_recall": tp_img / max(tp_img + fn_img, 1),
            "img_counts": [tp_img, fp_img, fn_img, tn_img]}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--epochs", type=int, default=30)
    ap.add_argument("--batch", type=int, default=32)
    ap.add_argument("--size", type=int, default=320)
    ap.add_argument("--lr", type=float, default=2e-3)
    ap.add_argument("--synth-per-epoch", type=int, default=2500)
    ap.add_argument("--workers", type=int, default=4, help="loader processes; each holds a copy of torch (~1-2 GB)")
    ap.add_argument("--out", type=Path, default=ROOT / "models")
    args = ap.parse_args()
    torch.manual_seed(0); random.seed(0); np.random.seed(0)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    if device == "cpu":
        torch.set_num_threads(max(4, (torch.get_num_threads() * 3) // 4))

    real_root = ROOT / "data" / "stagnant_water"
    man = json.loads((real_root / "manifest.json").read_text())
    syn = ROOT / "data" / "synthetic"
    syn_tr = sorted(p.stem for p in (syn / "train" / "images").glob("*.jpg"))
    syn_va = sorted(p.stem for p in (syn / "val" / "images").glob("*.jpg"))
    real_tr = SegFolder(real_root, man["train"], args.size, True)
    real_va = SegFolder(real_root, man["val"], args.size, False)
    syn_train = SegFolder(syn / "train", syn_tr, args.size, True)
    syn_val = SegFolder(syn / "val", syn_va, args.size, False)
    print(f"device {device}; real {len(real_tr)}/{len(real_va)}, synthetic {len(syn_train)}/{len(syn_val)}")

    model = build_model().to(device)
    opt = torch.optim.AdamW(model.parameters(), lr=args.lr, weight_decay=1e-4)
    steps_per_epoch = (len(real_tr) + args.synth_per_epoch) // args.batch
    sched = torch.optim.lr_scheduler.OneCycleLR(opt, max_lr=args.lr, total_steps=args.epochs * steps_per_epoch,
                                                pct_start=0.1)
    use_amp = device == "cuda"
    scaler = torch.amp.GradScaler("cuda", enabled=use_amp)
    kw = dict(batch_size=args.batch, num_workers=args.workers, persistent_workers=args.workers > 0,
              pin_memory=device == "cuda")
    val_real = DataLoader(real_va, shuffle=False, **kw)
    val_syn = DataLoader(syn_val, shuffle=False, **kw)
    best, history = -1.0, []
    args.out.mkdir(parents=True, exist_ok=True)
    for epoch in range(args.epochs):
        idx = random.sample(range(len(syn_train)), min(args.synth_per_epoch, len(syn_train)))
        train = DataLoader(ConcatDataset([real_tr, Subset(syn_train, idx)]), shuffle=True, drop_last=True,
                           batch_size=args.batch, num_workers=args.workers, pin_memory=device == "cuda")
        t0, total, n = time.time(), 0.0, 0
        for step, (x, y) in enumerate(train):
            if step >= steps_per_epoch:
                break
            x, y = x.to(device, non_blocking=True), y.to(device, non_blocking=True)
            with torch.autocast(device_type=device, dtype=torch.float16, enabled=use_amp):
                logits = model(x)["out"]
            loss = masked_loss(logits.float(), y)
            opt.zero_grad(set_to_none=True)
            scaler.scale(loss).backward()
            scaler.step(opt)
            scaler.update()
            sched.step()
            total += loss.item(); n += 1
        mr, ms = evaluate(model, val_real, device), evaluate(model, val_syn, device)
        score = 0.5 * (mr["iou"] + ms["iou"])
        rec = {"epoch": epoch + 1, "loss": round(total / max(n, 1), 4), "val_real": mr, "val_synthetic": ms,
               "score": round(score, 4), "secs": round(time.time() - t0, 1)}
        history.append(rec)
        print(f"epoch {epoch + 1:2d} loss {rec['loss']:.4f} | real IoU {mr['iou']:.3f} "
              f"P/R {mr['img_precision']:.2f}/{mr['img_recall']:.2f} | synth IoU {ms['iou']:.3f} "
              f"P/R {ms['img_precision']:.2f}/{ms['img_recall']:.2f} | {rec['secs']}s", flush=True)
        if score > best:
            best = score
            torch.save(model.state_dict(), args.out / "leaklatch_waterseg.pt")
    best_rec = max(history, key=lambda r: r["score"])
    (args.out / "train_metrics.json").write_text(json.dumps({
        "architecture": "torchvision lraspp_mobilenet_v3_large, 1 class (water), input 3x%dx%d" % (args.size, args.size),
        "data": {"real": man["source"], "real_train": len(real_tr), "real_val": len(real_va),
                 "synthetic_train": len(syn_train), "synthetic_val": len(syn_val)},
        "best": best_rec, "history": history}, indent=1), encoding="utf-8")
    print("best", json.dumps(best_rec))


if __name__ == "__main__":
    main()
