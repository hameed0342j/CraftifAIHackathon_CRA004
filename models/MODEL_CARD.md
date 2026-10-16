# Model card: leaklatch_waterseg

| | |
|---|---|
| Task | binary semantic segmentation of pooled water on floors |
| Architecture | torchvision `lraspp_mobilenet_v3_large`, 1 output channel (logit), ImageNet-pretrained backbone |
| Input | 1×3×320×320 RGB, ImageNet mean/std normalisation (`pipegen/backends.py::preprocess`) |
| Output | 1×1×320×320 logits; water = sigmoid ≥ 0.5 |
| Files | `leaklatch_waterseg.onnx` (FP32, opset 17), `leaklatch_waterseg_fp16.onnx`, `leaklatch_waterseg.engine` (TensorRT 11.4, RTX 5070 Ti; **rebuild per device**) |
| License | MIT (weights); see NOTICE.md for data and backbone attributions |

## Training data

* **Real:** "Stagnant Water and Wet Surface" (Patil & Bhutad 2021, CC BY 4.0). 2,000 images from the Kaggle mirror,
  1,833 after removing exact duplicates; 1,570 train / 263 val, split by content hash. These are outdoor
  roads and soil in India. Box labels become masks: water boxes = 1, wet-surface boxes = ignore.
* **Synthetic:** 4,000 train / 400 val procedural indoor floors (`simlab/render.py`): ceramic, vitrified,
  Kota stone, mosaic and red-oxide tiles; perspective cameras; tube-light reflections on dry glossy tiles,
  stains, shadows, buckets, slippers, footprints; exact masks.
* Augmentation: random resized crop, flip, ±12° rotation, exposure, white balance, blur, noise.
* Optimiser: AdamW + OneCycle (max LR 2e-3), batch 32, BCE + 0.5·Dice over labelled pixels, AMP on an RTX 5070 Ti.
  The planned 40-epoch run was stopped early by the host running out of memory. The published weights are the
  best checkpoint saved before that (selected on mean validation IoU over real + synthetic).

## Evaluation (`python -m pipegen.train.evaluate`)

| Held-out set | images | mask IoU | image precision | image recall |
|---|---|---|---|---|
| real (outdoor puddles, coarse labels) | 263 (only 6 dry) | 0.712 | 0.984 | 0.992 |
| synthetic indoor floors | 400 (136 dry) | 0.910 | 0.973 | 0.981 |

Image-level means a predicted pool larger than 0.5 % of the frame.

## Known limitations

* No real **indoor** floor images were available under an open license (see `docs/asset-scan.md`). Expect a
  domain gap on real hostel bathrooms until a few hundred site frames are added.
* Real-set IoU is measured against coarse box-union masks, so it understates true boundary quality.
* Precision on real dry scenes is weakly measured (6 negatives). The synthetic set covers dry glossy floors.
* Clear water on white tiles with no reflection is the hardest case. LeakLatch never acts on vision alone:
  the wetness probe must agree before any valve moves.
