"""Video writer: H.264 (plays in browsers and on GitHub) via imageio-ffmpeg when installed, else OpenCV mp4v."""

from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np


class VideoSink:
    def __init__(self, path: str | Path, fps: float, size: tuple[int, int]) -> None:
        self.size = size
        try:
            import imageio_ffmpeg

            self._gen = imageio_ffmpeg.write_frames(str(path), size, fps=fps, codec="libx264", pix_fmt_in="bgr24",
                                                    pix_fmt_out="yuv420p", quality=7, macro_block_size=8)
            self._gen.send(None)
            self._cv = None
        except ImportError:
            self._gen = None
            self._cv = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, size)

    def write(self, frame: np.ndarray) -> None:
        if frame.shape[1::-1] != tuple(self.size):
            frame = cv2.resize(frame, tuple(self.size))
        if self._gen is not None:
            self._gen.send(np.ascontiguousarray(frame))
        else:
            self._cv.write(frame)

    def close(self) -> None:
        if self._gen is not None:
            self._gen.close()
        else:
            self._cv.release()
