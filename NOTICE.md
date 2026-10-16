# Third-party notices and attributions

## Training data

* **Dataset of Stagnant Water and Wet Surface with Annotations.** Sonali Bhutad and Kailas Patil,
  Mendeley Data (y6zyrnxbfm), CC BY 4.0. Paper: *Data in Brief* (2021), doi:10.1016/j.dib.2021.107752.
  Used through its Kaggle re-upload. LeakLatch removes 167 exact duplicates and converts the YOLO boxes
  to coarse masks (`pipegen/train/prepare.py`). The dataset itself is not redistributed in this repository.
* **Synthetic indoor floors.** Generated procedurally by `simlab/render.py` (this repository, MIT).

## Real test footage

* **"Flooding at the School of Law, Singapore Management University - 20170122"** by Smuconlaw,
  Wikimedia Commons, **CC BY-SA 4.0**:
  https://commons.wikimedia.org/wiki/File:Flooding_at_the_School_of_Law,_Singapore_Management_University_-_20170122.webm
  The clip itself is not redistributed here. `docs/media/real_footage.jpg` and the "Real footage" segment of
  `docs/media/leaklatch_demo.mp4` are adaptations: frames with the model's water mask and labels overlaid.
  Those adaptations are licensed under **CC BY-SA 4.0**.

## Model and libraries

* torchvision LR-ASPP MobileNetV3-Large and its ImageNet backbone weights: BSD-3-Clause.
* PyTorch (BSD-style), ONNX / ONNX Runtime (MIT / Apache-2.0), OpenCV (Apache-2.0), NumPy (BSD-3),
  paho-mqtt (EPL-2.0 / EDL-1.0), jsonschema (MIT), PyYAML (MIT).
* NVIDIA TensorRT and cuda-python: NVIDIA license terms. They are installed separately and not redistributed.
* ESP-IDF, esp-mqtt, cJSON: Apache-2.0 / MIT.

No Ultralytics (AGPL-3.0) code or weights are used, so the whole stack can ship under MIT.

## Design references

* tomekceszke/water-controller (MIT): tiered fail-safe and NVS valve-state ideas.
* heyitsyang/Whole-House-Water-Leak-Controller (BSD-3): verifying valve position from switch feedback.
