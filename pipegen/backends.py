"""Segmentation backends. All return a water-probability map (float32, model resolution).

tensorrt     compiled .engine (Jetson / any NVIDIA GPU), via TensorRT + cuda-python
onnxruntime  portable fallback (CPU, or CUDA EP when available)
oracle       ground-truth masks from the simulator (pipeline/plumbing tests without a model)
"""

from __future__ import annotations

import hashlib
import logging
from pathlib import Path
from typing import Callable

import cv2
import numpy as np

log = logging.getLogger(__name__)

MEAN = np.array([0.485, 0.456, 0.406], np.float32)
STD = np.array([0.229, 0.224, 0.225], np.float32)


def preprocess(frame_bgr: np.ndarray, size: int) -> np.ndarray:
    img = cv2.resize(frame_bgr, (size, size), interpolation=cv2.INTER_AREA)
    img = cv2.cvtColor(img, cv2.COLOR_BGR2RGB).astype(np.float32) / 255.0
    img = (img - MEAN) / STD
    return np.ascontiguousarray(img.transpose(2, 0, 1)[None])


def sigmoid(x: np.ndarray) -> np.ndarray:
    return 1.0 / (1.0 + np.exp(-np.clip(x, -30, 30)))


def file_sha256(path: str | Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


class OnnxSegmenter:
    def __init__(self, onnx_path: str | Path, size: int) -> None:
        import onnxruntime as ort

        self.size = size
        wanted = ["CUDAExecutionProvider", "CPUExecutionProvider"]
        providers = [p for p in wanted if p in ort.get_available_providers()]
        self.session = ort.InferenceSession(str(onnx_path), providers=providers)
        self.input = self.session.get_inputs()[0].name
        self.name = "onnxruntime-" + self.session.get_providers()[0].replace("ExecutionProvider", "").lower()
        self.model_path = Path(onnx_path)
        self.model_sha256 = file_sha256(onnx_path)

    def logits(self, x: np.ndarray) -> np.ndarray:
        return self.session.run(None, {self.input: x})[0]

    def predict(self, frame_bgr: np.ndarray, meta: dict | None = None) -> np.ndarray:
        return sigmoid(self.logits(preprocess(frame_bgr, self.size))[0, 0])


def _cudart():
    try:
        from cuda.bindings import runtime as cudart  # cuda-python >= 12.6
    except ImportError:  # older cuda-python (JetPack images)
        from cuda import cudart
    return cudart


def _ck(res):
    err, *rest = res if isinstance(res, tuple) else (res,)
    if int(err) != 0:
        raise RuntimeError(f"CUDA error {err}")
    return rest[0] if len(rest) == 1 else rest


class TensorRTSegmenter:
    """Runs a serialized TensorRT engine (8.6 / 10.x / 11.x name-based I/O API)."""

    def __init__(self, engine_path: str | Path, size: int) -> None:
        import tensorrt as trt

        self.size = size
        self.cudart = cudart = _cudart()
        logger = trt.Logger(trt.Logger.WARNING)
        self.engine = trt.Runtime(logger).deserialize_cuda_engine(Path(engine_path).read_bytes())
        if self.engine is None:
            raise RuntimeError(f"could not deserialize {engine_path} (built for another GPU/TensorRT version?)")
        self.ctx = self.engine.create_execution_context()
        names = [self.engine.get_tensor_name(i) for i in range(self.engine.num_io_tensors)]
        self.in_name = next(n for n in names if self.engine.get_tensor_mode(n) == trt.TensorIOMode.INPUT)
        self.out_name = next(n for n in names if self.engine.get_tensor_mode(n) == trt.TensorIOMode.OUTPUT)
        self.in_dtype = trt.nptype(self.engine.get_tensor_dtype(self.in_name))
        out_shape = tuple(self.engine.get_tensor_shape(self.out_name))
        self.h_out = np.empty(out_shape, trt.nptype(self.engine.get_tensor_dtype(self.out_name)))
        in_nbytes = int(np.prod(self.engine.get_tensor_shape(self.in_name))) * np.dtype(self.in_dtype).itemsize
        self.d_in = _ck(cudart.cudaMalloc(in_nbytes))
        self.d_out = _ck(cudart.cudaMalloc(self.h_out.nbytes))
        self.stream = _ck(cudart.cudaStreamCreate())
        self.ctx.set_tensor_address(self.in_name, int(self.d_in))
        self.ctx.set_tensor_address(self.out_name, int(self.d_out))
        self.in_nbytes = in_nbytes
        self.name = f"tensorrt-{trt.__version__}"
        self.model_path = Path(engine_path)
        self.model_sha256 = file_sha256(engine_path)

    def logits(self, x: np.ndarray) -> np.ndarray:
        cudart = self.cudart
        x = np.ascontiguousarray(x, self.in_dtype)
        h2d = cudart.cudaMemcpyKind.cudaMemcpyHostToDevice
        d2h = cudart.cudaMemcpyKind.cudaMemcpyDeviceToHost
        _ck(cudart.cudaMemcpyAsync(self.d_in, x.ctypes.data, self.in_nbytes, h2d, self.stream))
        if not self.ctx.execute_async_v3(int(self.stream)):
            raise RuntimeError("TensorRT execution failed")
        _ck(cudart.cudaMemcpyAsync(self.h_out.ctypes.data, self.d_out, self.h_out.nbytes, d2h, self.stream))
        _ck(cudart.cudaStreamSynchronize(self.stream))
        return self.h_out.astype(np.float32)

    def predict(self, frame_bgr: np.ndarray, meta: dict | None = None) -> np.ndarray:
        return sigmoid(self.logits(preprocess(frame_bgr, self.size))[0, 0])

    def __del__(self) -> None:
        try:
            self.cudart.cudaFree(self.d_in)
            self.cudart.cudaFree(self.d_out)
            self.cudart.cudaStreamDestroy(self.stream)
        except Exception:
            pass


class OracleSegmenter:
    """Returns the simulator's ground-truth mask passed in `meta['gt_mask']`."""

    name = "oracle"
    model_sha256 = None
    model_path = None

    def __init__(self, size: int) -> None:
        self.size = size

    def predict(self, frame_bgr: np.ndarray, meta: dict | None = None) -> np.ndarray:
        gt = (meta or {}).get("gt_mask")
        if gt is None:
            raise ValueError("oracle backend needs meta['gt_mask'] (simulator only)")
        return cv2.resize(gt.astype(np.float32), (self.size, self.size), interpolation=cv2.INTER_AREA) * 0.97


def load_segmenter(backend: str, size: int, engine: str | None, onnx: str | None) -> object:
    if backend == "oracle":
        return OracleSegmenter(size)
    tried: list[str] = []
    if backend in ("auto", "tensorrt") and engine and Path(engine).exists():
        try:
            return TensorRTSegmenter(engine, size)
        except Exception as e:  # missing libs, wrong GPU, ...
            if backend == "tensorrt":
                raise
            tried.append(f"tensorrt: {e}")
    if backend in ("auto", "onnxruntime") and onnx and Path(onnx).exists():
        return OnnxSegmenter(onnx, size)
    raise RuntimeError(f"no usable backend for {backend!r} (engine={engine}, onnx={onnx}) {tried}")


Predictor = Callable[[np.ndarray, dict | None], np.ndarray]
